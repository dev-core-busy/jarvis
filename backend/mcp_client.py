"""MCP Client Manager – Verbindet Jarvis mit externen MCP-Tool-Servern."""

import asyncio
import json
import os
import uuid
from contextlib import AsyncExitStack
from typing import Any

from backend.tools.base import BaseTool
from backend.config import config
from backend.mcp_tls import CaFehler, ist_pem as _ca_ist_pem


def _zertifikat_moeglich(srv: dict) -> bool:
    """Hat dieser Server ueberhaupt ein Zertifikat zum Ansehen?

    Nur https-Transporte. Die Frage wird HIER beantwortet und nicht in der
    Oberflaeche: dort waere sie eine zweite Quelle, und `get_status` gibt die
    Adresse bewusst nicht heraus.
    """
    if str(srv.get("transport") or "stdio") == "stdio":
        return False
    return str(srv.get("url") or "").strip().lower().startswith("https://")

# Umgebungsvariablen, die ein stdio-MCP-Server erben darf. Bewusst eine
# WHITELIST: was nicht hier steht, kommt nicht durch (fail-closed). Enthaelt
# ausschliesslich das, was ein Prozess zum Starten braucht – kein einziger Wert
# mit Geheimnischarakter. Braucht ein Server mehr, traegt der Administrator es
# im Feld ``env`` der Server-Konfiguration ein; das ist eine bewusste, sichtbare
# Entscheidung fuer genau diesen Server.
#
# PATH und HOME sind Pflicht: ohne PATH findet der Kernel `npx`/`python3` nicht,
# ohne HOME sucht npm seinen Cache in /root und scheitert mit EACCES.
_ENV_WEITERGEBEN = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "PWD",
    "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM", "TMPDIR",
    "PYTHONUNBUFFERED", "PYTHONIOENCODING",
    # Proxy-Angaben: ohne sie erreicht ein Server in abgeschotteten Netzen
    # nichts. Sie enthalten allerdings gelegentlich Zugangsdaten in der URL –
    # wer das nicht will, nimmt sie hier heraus.
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy",
)


# ─── Isolation von stdio-Servern ────────────────────────────────────────────
#
# WARUM NICHT ueber den Root-Broker: `sandbox_exec` fuehrt EINEN Befehl aus und
# gibt stdout/stderr zurueck. Ein stdio-MCP-Server ist das Gegenteil – ein
# langlebiger Prozess mit bidirektionalen Pipes. Das ueber den Broker zu fuehren
# hiesse FD-Passing (SCM_RIGHTS) plus einen eigenen Transport und einen
# Broker-Neustart auf jedem Server; dazu haette `jarvis_sandbox` (Shell
# `nologin`, Home existiert nicht) keinen beschreibbaren npm-Cache.
#
# `bwrap` erreicht dasselbe Ziel OHNE Rechteerhoehung: es laeuft unprivilegiert
# ueber User-Namespaces. Der Prozess behaelt die uid des Dienstes, aber
# /opt/jarvis (und damit data/, .env, settings.json) EXISTIERT in seinem
# Namespace nicht – dieselbe Wirkung wie ein fremder OS-Benutzer, ohne einen
# anzulegen. `--unshare-pid` gibt zusaetzlich das, was OS-Rechte nie leisten:
# der Prozess sieht die uebrigen Prozesse des Dienstes nicht und kann ihnen
# keine Signale senden.
_BWRAP = "/usr/bin/bwrap"

# `setpriv` legt vererbte Capabilities ab, BEVOR bwrap startet.
#
# WARUM DAS NOETIG IST (auf DEV im laufenden Dienst gefunden, 2026-08-14): die
# Unit gibt dem Backend `AmbientCapabilities=CAP_NET_BIND_SERVICE`, damit es als
# unprivilegierter Benutzer an Port 443 darf. Ambient-Capabilities werden an
# JEDEN Kindprozess vererbt – und bwrap bricht dann mit
# „Unexpected capabilities but not setuid, old file caps config?" ab. Die
# Isolation waere also ausgerechnet im Dienst tot gewesen, obwohl sie in jeder
# Handprobe (dort ohne ambient caps) funktionierte.
#
# In einem MCP-Server hat CAP_NET_BIND_SERVICE ohnehin nichts zu suchen, deshalb
# wird immer abgelegt und nicht erst bei Bedarf.
_SETPRIV = "/usr/bin/setpriv"

# Nur lesbar eingeblendet – alles, was ein Programm zum Laufen braucht.
# /opt und /home stehen BEWUSST NICHT hier: dort liegen Dienst und Daten.
_BWRAP_RO = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc")


def bwrap_verfuegbar() -> bool:
    """True, wenn bwrap vorhanden und unprivilegiert benutzbar ist.

    Geprueft wird mit GENAU dem Aufruf, den `_bwrap_wrappen` spaeter baut – nur
    mit ``/bin/true`` als Nutzlast. Eine vereinfachte Probe beweist nichts: die
    erste Fassung band nur /usr ein, worauf schon ``/bin/true`` an der fehlenden
    libc scheiterte und die Funktion auf einem voellig gesunden System False
    meldete (auf DEV genau so passiert).
    """
    if not os.path.exists(_BWRAP):
        return False
    try:
        import subprocess
        cmd, args = _bwrap_wrappen("/bin/true", [], [])
        r = subprocess.run([cmd, *args], capture_output=True, timeout=15)
        if r.returncode != 0:
            print(f"[MCP] bwrap-Probe fehlgeschlagen (rc={r.returncode}): "
                  f"{r.stderr.decode('utf-8', 'replace')[:200]}", flush=True)
        return r.returncode == 0
    except Exception as e:  # noqa: BLE001
        print(f"[MCP] bwrap-Probe nicht ausfuehrbar: {e}", flush=True)
        return False


def _bwrap_wrappen(cmd: str, args: list, extra_ro: list) -> tuple:
    """Baut aus (Befehl, Argumente) einen bwrap-Aufruf.

    ``extra_ro`` sind zusaetzliche, NUR LESBARE Pfade aus der Server-Konfiguration
    – ein Dateisystem-Server braucht schliesslich die Daten, die er ausliefern
    soll. Bewusst kein Schreibzugriff: wer den braucht, hat das Werkzeug falsch
    gewaehlt.
    """
    bargs = []
    for p in _BWRAP_RO:
        if os.path.exists(p):
            bargs += ["--ro-bind", p, p]
    for p in extra_ro:
        p = str(p).strip()
        # Nur absolute, vorhandene Pfade – ein relativer Pfad wuerde im
        # Namespace an einer voellig anderen Stelle landen.
        if p.startswith("/") and os.path.exists(p):
            bargs += ["--ro-bind", p, p]
    # HOME beschreibbar, aber als leeres tmpfs: npm/npx brauchen einen Cache,
    # der darf nur nicht der echte Home des Dienstbenutzers sein.
    heim = os.environ.get("HOME", "/tmp")
    bargs += [
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--tmpfs", heim,
        "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
        # Netz BLEIBT: die meisten Server sind genau dafuer da, und npx laedt
        # sein Paket beim Start. Wer den Zugriff steuern will, nutzt die
        # Internet-Freigabe (requires_internet) bzw. die Egress-Firewall.
        "--die-with-parent",       # Server stirbt mit dem Backend, keine Waisen
        "--new-session",           # kein Zugriff auf das steuernde Terminal
        "--chdir", "/tmp",
        "--",
        cmd, *[str(a) for a in args],
    ]
    if os.path.exists(_SETPRIV):
        return _SETPRIV, ["--inh-caps=-all", "--ambient-caps=-all", "--", _BWRAP, *bargs]
    return _BWRAP, bargs


# ─── MCP Remote Tool Wrapper ────────────────────────────────────────────────

class McpRemoteTool(BaseTool):
    """Wraps ein MCP-Tool als Jarvis BaseTool.

    SICHERHEIT (seit 2026-08-14): Diese Werkzeuge landen ueber
    `agent.py::_attach_extra_tools` im selben Werkzeugkasten wie Skill-Werkzeuge,
    stammen aber aus FREMDEM Code mit FREMDEN Zugangsdaten. Sie tragen deshalb
    zwei Marker, die der Dispatch auswertet:

    * `requires_internet = True` – ein MCP-Server ist per Definition eine externe
      Datenquelle. Ohne diesen Marker erreichte ein Benutzer OHNE Internet-Freigabe
      ueber einen MCP-Server genau das, was ihm `curl` verweigert. Bewusst
      pauschal und nicht je Server konfigurierbar: fail-closed. Auch ein
      stdio-Server ist ein Prozess, den ein Administrator konfiguriert hat, um an
      Daten von woanders zu kommen.
    * `ist_mcp = True` + `erlaubt_netzwerk_benutzer` – Netzwerk-Benutzer duerfen
      MCP-Werkzeuge nur, wenn ein Administrator den SERVER dafuer freigibt
      (Vorgabe AUS). Grund ist das Muster "fremde Zugangsdaten als Vollmacht":
      der Server arbeitet mit seinem hinterlegten Token, die Rechte des
      anfragenden Benutzers im Zielsystem spielen keine Rolle. Genau das war
      eines der vier Fehlermuster der Endpunkt-Durchsicht vom 2026-08-04.
    """

    # Von `_execute_tool` per getattr geprueft – siehe Klassen-Docstring.
    requires_internet = True
    ist_mcp = True

    def __init__(self, server_name: str, tool_info: dict, session: Any,
                 server_config: dict | None = None):
        self._server_name = server_name
        self._tool_name = tool_info.get("name", "unknown")
        self._description = tool_info.get("description", "MCP Tool")
        self._input_schema = tool_info.get("inputSchema", {"type": "object", "properties": {}})
        self._session = session
        _cfg = server_config or {}
        self.server_id = _cfg.get("id", "")
        # Fail-closed: alles ausser einem echten True gilt als "nicht freigegeben"
        # (ein aus JSON gelesenes "ja"/1 ist keine bewusste Admin-Entscheidung).
        self.erlaubt_netzwerk_benutzer = _cfg.get("allow_network_users") is True

    @property
    def name(self) -> str:
        safe_server = self._server_name.replace("-", "_").replace(" ", "_")
        safe_tool = self._tool_name.replace("-", "_").replace(" ", "_")
        return f"mcp_{safe_server}_{safe_tool}"

    @property
    def description(self) -> str:
        return f"[MCP:{self._server_name}] {self._description}"

    def parameters_schema(self) -> dict:
        return self._input_schema

    async def execute(self, **kwargs) -> str:
        try:
            result = await self._session.call_tool(self._tool_name, kwargs)
            texts = []
            for content in result.content:
                if hasattr(content, "text"):
                    texts.append(content.text)
                elif hasattr(content, "data"):
                    texts.append(f"[Binary: {len(content.data)} bytes]")
            return "\n".join(texts) if texts else "Tool ausgefuehrt (keine Textausgabe)"
        except Exception as e:
            return f"❌ MCP-Tool Fehler ({self._server_name}/{self._tool_name}): {e}"


# ─── Server Connection ───────────────────────────────────────────────────────

class McpServerConnection:
    """Verwaltet eine einzelne MCP-Server-Verbindung."""

    def __init__(self, server_config: dict):
        self.config = server_config
        self.id = server_config.get("id", str(uuid.uuid4()))
        self.name = server_config.get("name", "unknown")
        self.connected = False
        self.error: str | None = None
        self.tools: list[McpRemoteTool] = []
        self._session = None
        self._exit_stack: AsyncExitStack | None = None

    async def connect(self):
        """Verbindet mit dem MCP-Server."""
        transport_type = self.config.get("transport", "stdio")
        try:
            from mcp import ClientSession
            self._exit_stack = AsyncExitStack()

            if transport_type == "stdio":
                await self._connect_stdio()
            elif transport_type in ("streamable_http", "streamablehttp"):
                await self._connect_streamable_http()
            elif transport_type == "sse":
                await self._connect_sse()
            elif transport_type == "http":
                # "http" ist der unscharfe Fall: bis 2026-08-14 lief er auf den
                # ALTEN SSE-Transport, gemeint ist heute aber fast immer
                # Streamable HTTP (SSE ist seit 2025-03-26 deprecated). Deshalb
                # erst der aktuelle Standard, bei Misserfolg der alte – so
                # funktionieren bestehende Konfigurationen weiter UND neue
                # Server, die nur noch /mcp anbieten.
                try:
                    await self._connect_streamable_http()
                except Exception as e:  # noqa: BLE001
                    print(f"[MCP] {self.name}: Streamable HTTP fehlgeschlagen ({e}), "
                          f"versuche SSE", flush=True)
                    # Der erste Versuch hat womoeglich schon etwas im ExitStack –
                    # sonst haengt beim naechsten Schliessen ein halb offener
                    # Transport daran.
                    await self._exit_stack.aclose()
                    self._exit_stack = AsyncExitStack()
                    await self._connect_sse()
            else:
                self.error = f"Unbekannter Transport: {transport_type}"
                return

            # Tools entdecken
            tools_response = await self._session.list_tools()
            self.tools = []
            for tool in tools_response.tools:
                tool_info = {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema if hasattr(tool, "inputSchema") else {"type": "object", "properties": {}},
                }
                self.tools.append(McpRemoteTool(self.name, tool_info, self._session,
                                                server_config=self.config))

            self.connected = True
            self.error = None
            print(f"[MCP] {self.name}: Verbunden, {len(self.tools)} Tools entdeckt", flush=True)

        except ImportError:
            self.error = "mcp-Paket nicht installiert (pip install mcp)"
            print(f"[MCP] {self.name}: {self.error}", flush=True)
        except CaFehler as f:
            # Das hinterlegte CA-Zertifikat ist unbrauchbar. Eigener Zweig,
            # damit der Grund nicht wie ein Netz- oder Serverfehler aussieht:
            # hier ist eine EINGABE falsch, und der Administrator soll das Feld
            # korrigieren, statt am Server zu suchen. `CaFehler` nennt den
            # naechsten Schritt bereits selbst.
            self.error = str(f)
            self.connected = False
            print(f"[MCP] {self.name}: Zertifikat nicht verwendbar – {f}",
                  flush=True)
        except asyncio.CancelledError:
            # ⚠ BEZAHLTER VORFALL (DEV 2026-10-24, 34 Neustarts in sechs
            # Minuten): der Transportfehler eines ENTFERNTEN Servers kommt hier
            # als CancelledError an, nicht als Exception. `streamablehttp_client`
            # haelt intern eine anyio-TaskGroup; scheitert deren HTTP-Task (hier
            # ein selbstsigniertes Zertifikat), cancelt der Scope unser
            # wartendes `initialize()`. CancelledError erbt von BaseException –
            # `except Exception` sieht sie NICHT. Sie lief damit durch
            # connect_all und startup_mcp bis in den Starlette-Lifespan:
            # "Application startup failed. Exiting.", Exit 3, systemd startet
            # neu, und der ganze Dienst war wegen EINES optionalen Servers weg.
            #
            # WEITERGEWORFEN WIRD NUR DER ECHTE ABBRUCH: wurde unser eigener
            # Task gecancelt (Shutdown), muss die Ausnahme durch, sonst haengt
            # das Herunterfahren. `cancelling()` unterscheidet genau das – ein
            # blindes Schlucken waere hier der schlechtere Fehler.
            aufgabe = asyncio.current_task()
            if aufgabe is not None and aufgabe.cancelling():
                raise
            self.error = ("Verbindung abgebrochen – der Server hat den Transport "
                          "fallen lassen (Zertifikat, Netz oder Protokoll)")
            self.connected = False
            print(f"[MCP] {self.name}: {self.error}", flush=True)
        except BaseExceptionGroup as gruppe:
            # Dieselbe TaskGroup liefert beim Aufraeumen eine Gruppe (der
            # ConnectError zusammen mit dem GeneratorExit des Streams). Eine
            # BaseExceptionGroup erbt ebenfalls von BaseException, sobald ein
            # Teil das tut – auch sie entkommt `except Exception`.
            harte, _ = gruppe.split((KeyboardInterrupt, SystemExit))
            if harte is not None:
                raise
            self.error = "; ".join(str(e) for e in gruppe.exceptions) or str(gruppe)
            self.connected = False
            print(f"[MCP] {self.name}: Verbindungsfehler – {self.error}", flush=True)
        except Exception as e:
            self.error = str(e)
            self.connected = False
            print(f"[MCP] {self.name}: Verbindungsfehler – {e}", flush=True)

    async def _connect_stdio(self):
        """Stdio-Transport (Subprozess)."""
        from mcp import ClientSession
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        cmd = self.config.get("command", "")
        args = self.config.get("args", [])
        env_vars = self.config.get("env", {})

        # NUR eine Whitelist durchreichen, NICHT die ganze Dienst-Umgebung.
        #
        # Bis 2026-08-14 stand hier ``{**os.environ, **env_vars}``. Am echten
        # Referenzserver gemessen (dessen Werkzeug ``get-env`` gibt die eigene
        # Umgebung aus): der Subprozess sah 50 Variablen, darunter
        # AGENT_API_KEY, GEMINI_API_KEY, GOOGLE_OAUTH_CLIENT_SECRET und
        # JARVIS_PASSWORD. Ein stdio-Server ist FREMDER Code – bei
        # ``npx -y <paket>`` sogar bei jedem Start frisch aus dem Netz geladen –
        # und bekam damit saemtliche Zugangsdaten des Dienstes; mit dem
        # AGENT_API_KEY haette er eigene Agentenauftraege starten koennen.
        #
        # Was ein Server wirklich braucht, traegt der Administrator im Feld
        # ``env`` der Server-Konfiguration ein. Genau dafuer gibt es das Feld –
        # es war nur bisher wirkungslos, weil ohnehin alles durchgereicht wurde.
        env = {k: os.environ[k] for k in _ENV_WEITERGEBEN if k in os.environ}
        env.update(env_vars)

        # Isolation (Vorgabe AN): der Server sieht das Dienst-Verzeichnis nicht.
        # FAIL-CLOSED: fehlt bwrap, wird NICHT still ungeschuetzt gestartet –
        # ein Schutz, der beim Fehlen einer Voraussetzung lautlos ausfaellt, ist
        # kein Schutz (gleiche Entscheidung wie beim Kennwort-Rueckfall in
        # mail_accounts). Der Administrator kann `sandbox: false` setzen; das ist
        # dann eine bewusste, sichtbare Entscheidung.
        if self.config.get("sandbox") is not False:
            if not bwrap_verfuegbar():
                raise RuntimeError(
                    "Isolation angefordert, aber 'bwrap' ist nicht verfuegbar "
                    "(Paket bubblewrap installieren: apt install bubblewrap). "
                    "Alternativ in der Server-Konfiguration 'sandbox' auf false "
                    "setzen – der Server laeuft dann OHNE Isolation und sieht die "
                    "Dateien des Dienstes.")
            cmd, args = _bwrap_wrappen(cmd, args, self.config.get("sandbox_paths") or [])

        server_params = StdioServerParameters(
            command=cmd,
            args=args,
            env=env,
        )

        transport = await self._exit_stack.enter_async_context(stdio_client(server_params))
        read_stream, write_stream = transport
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()

    def _tls_haken(self) -> dict:
        """``{"httpx_client_factory": …}`` – oder ``{}`` ohne eigenes CA-Zert.

        ⚠ EIN LEERES DICT IST DER NORMALFALL und muss es bleiben: ohne
        hinterlegtes Zertifikat wird die Vorgabe der Bibliothek benutzt
        (``create_mcp_http_client``, mit deren Zeitlimits). Eine eigene Factory
        "nur zur Sicherheit" zu uebergeben waere der Weg, bei einem
        Bibliotheks-Update stillschweigend andere Timeouts zu fahren – genau
        die Asymmetrie, an der hier schon einmal ein Threadpool haengenblieb
        (Register: wer eine Bibliothek tauscht, liest den KONSTRUKTOR).

        Die Factory bildet die Signatur von ``create_mcp_http_client`` NACH
        (headers/timeout/auth) und reicht alles durch. Eine bequemere Signatur
        waere eine Kette, die es nicht gibt: die Bibliothek ruft mit genau
        diesen Schluesselwoertern.

        Ein unbrauchbares Zertifikat wird hier NICHT verschluckt – ``CaFehler``
        geht an ``connect()``, das daraus den Klartext-Grund fuer die
        Serverzeile macht. Stillschweigend ohne das Zertifikat zu verbinden
        hiesse, die Pruefung gegen die System-CAs laufen zu lassen und dem
        Administrator "nicht verbunden" ohne Ursache zu zeigen.
        """
        from backend.mcp_tls import ssl_kontext

        ctx = ssl_kontext(self.config.get("ca_cert"))
        if ctx is None:
            return {}

        def _factory(headers=None, timeout=None, auth=None):
            import httpx
            from mcp.shared._httpx_utils import create_mcp_http_client
            # Die Zeitlimits der Bibliothek uebernehmen, NICHT neu erfinden:
            # ein Server haelt den Antwortstrom offen (300 s Lesefrist), und
            # eine eigene Zahl hier waere eine zweite Quelle fuer denselben
            # Wert. Deshalb erst deren Client bauen und nur `verify` setzen.
            vorgabe = create_mcp_http_client(headers=headers, timeout=timeout,
                                             auth=auth)
            return httpx.AsyncClient(verify=ctx, headers=vorgabe.headers,
                                     timeout=vorgabe.timeout, auth=auth,
                                     follow_redirects=False)

        return {"httpx_client_factory": _factory}

    async def _connect_streamable_http(self):
        """Streamable HTTP – der aktuelle Standard fuer entfernte Server.

        Loest SSE ab (deprecated seit 2025-03-26). Die ueblichen Endpunkte enden
        auf ``/mcp``. Der Client liefert hier ein DREIER-Tupel (der dritte Wert
        ist eine Funktion fuer die Session-Id) – wer wie beim SSE-Transport zwei
        Werte auspackt, bekommt einen ValueError, der nach einem Serverfehler
        aussieht.
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        url = self.config.get("url", "")
        transport = await self._exit_stack.enter_async_context(
            streamablehttp_client(url=url, **self._tls_haken()))
        read_stream, write_stream = transport[0], transport[1]
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()

    async def _connect_sse(self):
        """SSE-Transport – ALT (deprecated seit 2025-03-26).

        Bleibt fuer Server, die nur noch das koennen; neue Ziele sollten
        ``streamable_http`` nutzen.

        ⚠ DAS CA-ZERTIFIKAT GILT HIER GENAUSO. `sse_client` nimmt dieselbe
        `httpx_client_factory` – wer den Haken nur am Streamable-Weg setzt,
        laesst ihn fuer die HAELFTE der HTTPS-Transporte ausfallen, und der
        `http`-Zweig oben faellt bei Misserfolg ausdruecklich hierher zurueck.
        Dann waere das hinterlegte Zertifikat genau im Rueckfall wirkungslos
        (Register: wer einen Fix anbringt, zaehlt die Wege).
        """
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        url = self.config.get("url", "")
        transport = await self._exit_stack.enter_async_context(
            sse_client(url=url, **self._tls_haken()))
        read_stream, write_stream = transport
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()

    async def disconnect(self):
        """Trennt die Verbindung.

        ⚠ Hier kommen dieselben BaseException-Abkoemmlinge an wie beim
        Verbinden, und sie sind beim Trennen besonders unangenehm: der Aufruf
        steht in ``connect_server`` VOR dem Neuaufbau und in ``disconnect_all``
        im Shutdown. Im Journal von DEV stand am 2026-10-24 genau eine Zeile
        "Fehler beim Trennen – Attempted to exit cancel scope in a different
        task" – der RuntimeError war von ``except Exception`` noch gedeckt, die
        CancelledError daneben NICHT. Das ``finally`` raeumt in jedem Fall auf:
        ein halb offener Stack waere beim naechsten Versuch die zweite Fehler-
        quelle.
        """
        try:
            if self._exit_stack:
                await self._exit_stack.aclose()
        except asyncio.CancelledError:
            aufgabe = asyncio.current_task()
            if aufgabe is not None and aufgabe.cancelling():
                # Im Shutdown MUSS der Abbruch durch – aber erst, nachdem das
                # finally unten den Zustand saubergemacht hat.
                raise
            print(f"[MCP] {self.name}: Trennen abgebrochen", flush=True)
        except BaseExceptionGroup as gruppe:
            harte, _ = gruppe.split((KeyboardInterrupt, SystemExit))
            if harte is not None:
                raise
            print(f"[MCP] {self.name}: Fehler beim Trennen – {gruppe}", flush=True)
        except Exception as e:
            print(f"[MCP] {self.name}: Fehler beim Trennen – {e}", flush=True)
        finally:
            self._session = None
            self._exit_stack = None
            self.connected = False
            self.tools = []

    def get_status(self) -> dict:
        """Status fuer Frontend."""
        return {
            "id": self.id,
            "name": self.name,
            "transport": self.config.get("transport", "stdio"),
            "connected": self.connected,
            # Es gibt eine Verbindungsinstanz, also HAT es einen Versuch
            # gegeben – im Gegensatz zum Ersatz-Dict im Manager.
            "versucht": True,
            "error": self.error,
            "tool_count": len(self.tools),
            "tools": [{"name": t._tool_name, "description": t._description} for t in self.tools],
            "enabled": self.config.get("enabled", True),
            # Liegt ein eigenes Zertifikat vor – und in welcher Form? NIE der
            # PEM-Block selbst: er ist lang, und in einer Serverzeile sucht
            # niemand danach. Die Pruefung ist dabei immer AN, es gibt kein
            # "verify aus" (siehe backend/mcp_tls.py).
            "ca_cert_art": ("pem" if _ca_ist_pem(self.config.get("ca_cert"))
                            else ("pfad" if (self.config.get("ca_cert") or "").strip()
                                  else "")),
            "zertifikat_moeglich": _zertifikat_moeglich(self.config),
            # Sichtbar machen, WER die Werkzeuge dieses Servers benutzen darf – ein
            # Zustand, den man der Serverzeile sonst nicht ansieht.
            "allow_network_users": self.config.get("allow_network_users") is True,
            # Nur bei stdio aussagekraeftig – ein entfernter Server laeuft
            # ohnehin nicht auf dieser Maschine.
            "sandbox": (self.config.get("sandbox") is not False
                        if self.config.get("transport", "stdio") == "stdio" else None),
        }


# ─── MCP Client Manager (Singleton) ─────────────────────────────────────────

class McpClientManager:
    """Verwaltet alle MCP-Server-Verbindungen."""

    def __init__(self):
        self._connections: dict[str, McpServerConnection] = {}

    async def connect_all(self):
        """Verbindet alle aktivierten MCP-Server aus der Konfiguration.

        ⚠ JE SERVER ABGESICHERT, und das ist ein ANDERER Zweck als die
        Schranke in ``McpServerConnection.connect``: dort geht es darum, dass
        ein Transportfehler den DIENST nicht beendet, hier darum, dass ein
        kaputter Server die ANDEREN nicht verhindert. Vor dem 2026-10-24 brach
        die Schleife beim ersten Fehler ab – bei zwei Servern hing das Ergebnis
        damit an der Reihenfolge in der Konfiguration.
        """
        servers = config.get_mcp_servers()
        for srv in servers:
            if not srv.get("enabled", True):
                continue
            name = srv.get("name") or srv.get("id") or "?"
            try:
                await self.connect_server(srv["id"])
            except Exception as e:  # noqa: BLE001
                # ⚠ HIER BEWUSST NUR `Exception` – die BaseException-Faelle
                # (CancelledError, BaseExceptionGroup) traegt `connect()`, und
                # zwar als EINZIGE Stelle. Eine zweite Schranke fuer dieselbe
                # Frage macht jede Gegenprobe stumm: man liest es als "der
                # Waechter ist blind", obwohl der Code doppelt haelt (Register,
                # hier beim Bau genau so gemessen – die Probe gegen diesen
                # Zweig biss nicht).
                # Was dieser Zweig traegt, ist etwas ANDERES: ein Fehler aus
                # `connect_server` SELBST, bevor `connect()` laeuft – ein
                # Eintrag ohne `id` (KeyError) oder eine kaputte
                # Konfigurationsliste. Ohne ihn haengt bei zwei Servern das
                # Ergebnis an der Reihenfolge in der Konfiguration.
                print(f"[MCP] {name}: uebersprungen – {e}", flush=True)

    async def connect_server(self, server_id: str) -> bool:
        """Verbindet einen einzelnen Server."""
        # Vorherige Verbindung trennen
        if server_id in self._connections:
            await self._connections[server_id].disconnect()

        servers = config.get_mcp_servers()
        srv_config = next((s for s in servers if s["id"] == server_id), None)
        if not srv_config:
            return False

        conn = McpServerConnection(srv_config)
        self._connections[server_id] = conn
        await conn.connect()
        return conn.connected

    async def disconnect_server(self, server_id: str):
        """Trennt einen einzelnen Server."""
        if server_id in self._connections:
            await self._connections[server_id].disconnect()
            del self._connections[server_id]

    async def disconnect_all(self):
        """Trennt alle Server (Shutdown)."""
        for conn in list(self._connections.values()):
            await conn.disconnect()
        self._connections.clear()

    def get_all_tools(self) -> list[BaseTool]:
        """Gibt alle Tools aller verbundenen Server zurueck."""
        tools = []
        for conn in self._connections.values():
            if conn.connected:
                tools.extend(conn.tools)
        return tools

    def get_status(self) -> list[dict]:
        """Status aller Server fuer Frontend."""
        servers = config.get_mcp_servers()
        result = []
        for srv in servers:
            sid = srv["id"]
            if sid in self._connections:
                result.append(self._connections[sid].get_status())
            else:
                result.append({
                    "id": sid,
                    "name": srv.get("name", "?"),
                    "transport": srv.get("transport", "stdio"),
                    "connected": False,
                    # ⚠ `None` heisst hier "es gab KEINEN Versuch", nicht "der
                    # Versuch ist gescheitert" (Code-Review 2026-10-24,
                    # gemeldet als "steht weiterhin Nicht verbunden"). Ohne
                    # diese Unterscheidung macht die Oberflaeche aus einem
                    # abgeschalteten Server denselben Text wie aus einem
                    # fehlgeschlagenen – eine Anzeige, die einen Zustand
                    # behauptet, den sie nicht kennt (Register).
                    "versucht": False,
                    "error": None,
                    "tool_count": 0,
                    "tools": [],
                    "enabled": srv.get("enabled", True),
                    "ca_cert_art": ("pem" if _ca_ist_pem(srv.get("ca_cert"))
                                    else ("pfad" if (srv.get("ca_cert") or "").strip()
                                          else "")),
                    "zertifikat_moeglich": _zertifikat_moeglich(srv),
                    "allow_network_users": srv.get("allow_network_users") is True,
                    "sandbox": (srv.get("sandbox") is not False
                                if srv.get("transport", "stdio") == "stdio" else None),
                })
        return result


# Singleton
mcp_manager = McpClientManager()
