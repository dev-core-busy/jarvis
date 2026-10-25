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
from backend import mcp_rechte

# Hoechstens so lange wartet ein Verbindungsaufbau auf den Server. Ein gesunder
# MCP-Server antwortet auf `initialize` in Sekunden (der stdio-Testserver mit
# npm-Start braucht ~3 s). Danach gilt er als stumm – siehe connect().
VERBINDUNGS_FRIST_S = 15


def _innerster_grund(fehler: BaseException) -> str:
    """Den eigentlichen Grund aus einer (verschachtelten) Fehlergruppe ziehen.

    Ein Transportfehler kommt als Gruppe um eine Kette (ConnectError ->
    httpcore -> ssl.SSLCertVerificationError). Fuer den Administrator zaehlt
    das Ende der Kette: bei TLS die ``verify_message`` mit Code, sonst die
    Nachricht des innersten Fehlers. Leer, wenn nichts Brauchbares darin ist.
    """
    import ssl as _ssl
    gesehen: set = set()
    stapel = [fehler]
    kandidat = ""
    while stapel:
        f = stapel.pop()
        if f is None or id(f) in gesehen:
            continue
        gesehen.add(id(f))
        if isinstance(f, _ssl.SSLCertVerificationError):
            text = (f.verify_message or str(f)).strip()
            hinweis = ""
            # 62 = Hostname, 64 = IP-Adresse passt nicht zum Zertifikat
            if f.verify_code in (62, 64):
                hinweis = (" – das Zertifikat gilt nicht fuer die eingetragene "
                           "Adresse. Ueber 'Zertifikat pruefen' laesst es sich "
                           "erlauben (es wird dann gepinnt), oder die Adresse "
                           "wird auf einen der Namen im Zertifikat umgestellt")
            return "TLS-Pruefung (Code %s): %s%s" % (f.verify_code, text, hinweis)
        if isinstance(f, BaseExceptionGroup):
            stapel.extend(f.exceptions)
        stapel.append(getattr(f, "__cause__", None))
        stapel.append(getattr(f, "__context__", None))
        if not isinstance(f, (BaseExceptionGroup, asyncio.CancelledError,
                              GeneratorExit)):
            t = str(f).strip()
            if t and not kandidat:
                kandidat = "%s: %s" % (type(f).__name__, t)
    return kandidat


def _zertifikat_moeglich(srv: dict) -> bool:
    """Hat dieser Server ueberhaupt ein Zertifikat zum Ansehen?

    Nur https-Transporte. Die Frage wird HIER beantwortet und nicht in der
    Oberflaeche: dort waere sie eine zweite Quelle, und `get_status` gibt die
    Adresse bewusst nicht heraus.
    """
    if str(srv.get("transport") or "stdio") == "stdio":
        return False
    return str(srv.get("url") or "").strip().lower().startswith("https://")


def _zugang_status(srv: dict) -> dict:
    """Schluessel und Freigabe fuer die Serverzeile – in BEIDEN Status-Zweigen.

    Der Schluessel selbst verlaesst das Backend nie, nur OB einer hinterlegt
    ist. Die URL ist fuer Administratoren keine Geheimsache und wird fuer das
    Bearbeiten im Schluessel-Feld gebraucht.
    """
    return {
        "url": str(srv.get("url") or ""),
        "api_key_gesetzt": bool(str(srv.get("api_key") or "").strip()),
        "api_key_header": str(srv.get("api_key_header") or ""),
        "allowed_users": str(srv.get("allowed_users") or ""),
        "allowed_group": str(srv.get("allowed_group") or ""),
        "freigabe": mcp_rechte.freigabe_art(srv),
    }

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
    * `ist_mcp = True` + `erlaubt_fuer(benutzer)` – MCP-Werkzeuge darf nur, wer
      fuer den SERVER freigegeben ist (Benutzer/Gruppen, leer = niemand, auch
      kein Admin – backend/mcp_rechte.py). Grund ist das Muster "fremde Zugangsdaten als Vollmacht":
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

    def erlaubt_fuer(self, benutzer: str) -> bool:
        """Darf dieser Benutzer das Werkzeug aufrufen? (gilt auch fuer Admins)

        Liest die Freigabe des Servers AKTUELL aus der Konfiguration (nicht den
        Stand beim Bau des Werkzeugs) – eine geaenderte Benutzer-/Gruppenliste
        wirkt damit sofort. Fail-closed: unbekannter Server = nein.
        """
        srv = next((s for s in config.get_mcp_servers()
                    if s.get("id") == self.server_id), None)
        return mcp_rechte.darf_benutzen(srv, benutzer)

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
        # Besitzer-Task und Stopp-Signal der Verbindung (siehe connect).
        self._besitzer: "asyncio.Task | None" = None
        self._stopp: "asyncio.Event | None" = None

    async def connect(self):
        """Verbindet mit dem MCP-Server; Transport "http" mit SSE-Rueckfall.

        ⚠ DER RUECKFALL BRAUCHT EINEN FRISCHEN BESITZER-TASK (Code-Review
        2026-10-25). Bis dahin stand er als `except Exception` IN
        ``_verbinden`` – toter Code: ein gescheiterter Streamable-HTTP-Versuch
        kommt als CancelledError/BaseExceptionGroup an (siehe unten), und selbst
        abgefangen liefe der SSE-Versuch im noch offenen, level-getriggerten
        anyio-Scope und wuerde sofort wieder gecancelt. Jetzt ist jeder Versuch
        ein eigener ``_ein_versuch`` mit eigenem Besitzer; scheitern beide, nennt
        die Meldung BEIDE Gruende (Register: ein Grund, der eine Ursache
        verschweigt, schickt auf die Suche).
        """
        transport = self.config.get("transport", "stdio")
        if transport != "http":
            await self._ein_versuch(transport)
            return
        # "http" ist der unscharfe Fall: bis 2026-08-14 lief er auf den ALTEN
        # SSE-Transport, gemeint ist heute aber fast immer Streamable HTTP (SSE
        # ist seit 2025-03-26 deprecated). Deshalb erst der aktuelle Standard,
        # bei Misserfolg der alte.
        await self._ein_versuch("streamable_http")
        if self.connected:
            return
        erster = self.error or "unbekannter Fehler"
        print(f"[MCP] {self.name}: Streamable HTTP fehlgeschlagen ({erster}), "
              f"versuche SSE", flush=True)
        self.error = None
        self._zeitueberschreitung = False
        await self._ein_versuch("sse")
        if not self.connected:
            self.error = f"Streamable HTTP: {erster} | SSE: {self.error or 'unbekannter Fehler'}"

    async def _ein_versuch(self, transport: str):
        """EIN Verbindungsversuch mit festem Transport – in einem EIGENEN BESITZER-TASK.

        ⚠ BEZAHLTER VORFALL, ZWEI ANLAEUFE (DEV 2026-10-24/25): der
        Transportfehler eines entfernten Servers (selbstsigniertes Zertifikat)
        hat den GANZEN Dienst in eine Neustartschleife gelegt. Der erste Fix
        fing die CancelledError; der zweite nahm sie mit `uncancel()` zurueck.
        Beide hielten nicht, und der Grund ist die eigentliche Lehre:

        **anyio-Cancel-Scopes sind level-triggered.** `streamablehttp_client`
        haelt eine anyio-TaskGroup; scheitert deren HTTP-Task, wird der Scope
        abgebrochen – und SOLANGE er offen ist, wird jeder weitere `await` in
        diesem Task erneut gecancelt. Der Scope blieb offen, weil der
        Transport ueber den AsyncExitStack betreten und bei einem Fehler NICHT
        verlassen wurde. `uncancel()` setzt nur den asyncio-Zaehler zurueck,
        nicht den anyio-Scope. Folge: der Start starb im naechsten,
        voellig fremden Hook (`_geheimnis_modulschluessel_verpacken`, an seinem
        ersten `to_thread`). Im Nachbau exakt reproduziert – mit UND ohne
        `uncancel()` stirbt der naechste await.

        DESHALB EIN BESITZER-TASK je Verbindung, und er loest BEIDES:
          * Ein fremder Cancel-Scope trifft nur diesen Task, nie den Aufrufer
            (Lifespan, Request). Der wartet nur auf ein Ereignis.
          * Betreten und Verlassen des Transports geschehen im SELBEN Task –
            anyio verlangt das ("Attempted to exit cancel scope in a different
            task than it was entered in", ebenfalls im Journal von DEV). Nach
            einem Fehler verlaesst der Besitzer den Scope SOFORT, bevor irgendein
            anderer `await` kommt; anyio raeumt seinen Cancel beim Verlassen
            selbst ab.

        ``disconnect()`` setzt das Stopp-Signal; der Besitzer schliesst dann
        seinen Stack selbst.
        """
        self._transport_jetzt = transport
        self._stopp = asyncio.Event()
        bereit = asyncio.Event()
        self._besitzer = asyncio.create_task(
            self._besitzer_lauf(bereit), name="mcp-besitzer-%s" % self.name)
        warten = asyncio.create_task(bereit.wait())
        try:
            fertig, _ = await asyncio.wait(
                {self._besitzer, warten}, timeout=VERBINDUNGS_FRIST_S,
                return_when=asyncio.FIRST_COMPLETED)
            if not fertig:
                # ⚠ ZEITUEBERSCHREITUNG – DER SERVER ANTWORTET NICHT NACH MCP.
                # Bezahlt auf DEV (2026-10-25): nachdem das Pinning den
                # TLS-Handshake von "theben" moeglich machte, antwortete der
                # Server auf den MCP-POST mit `text/plain` statt mit MCP
                # ("Unexpected content type"). `initialize()` wartete auf eine
                # Antwort, die nie kam – OHNE Zeitdeckel. Der Lifespan blieb
                # haengen, uvicorn nahm keine Anfrage an, und DEV antwortete
                # auf nichts (Health 000). Vorher hatte der sofort scheiternde
                # Handshake genau das verborgen. Haengen ist fuer den Dienst so
                # schlimm wie abbrechen.
                self._zeitueberschreitung = True
                self.error = ("Keine Antwort in %d s – der Server spricht an "
                              "dieser Adresse kein MCP (falscher Pfad, oder er "
                              "antwortet mit etwas anderem als JSON/SSE)"
                              % VERBINDUNGS_FRIST_S)
                self.connected = False
                self._stopp.set()
                self._besitzer.cancel()
                # Dem Besitzer Gelegenheit geben, seinen Stack im EIGENEN Task
                # zu schliessen – aber begrenzt, sonst haengt connect() erneut.
                await asyncio.wait({self._besitzer}, timeout=5)
        except asyncio.CancelledError:
            # WIR wurden gecancelt (echter Abbruch, z. B. Shutdown waehrend des
            # Aufbaus): den Besitzer mitnehmen, sonst verwaist er samt
            # Subprozess, und den Abbruch durchlassen.
            self._stopp.set()
            self._besitzer.cancel()
            raise
        finally:
            if not warten.done():
                warten.cancel()
        # ⚠ EIN ABBRUCH BLEIBT EIN ABBRUCH – auch ueber die Task-Grenze. Der
        # Besitzer faengt jeden Transportfehler selbst; was ihn trotzdem
        # verlaesst, ist ausschliesslich das Harte (KeyboardInterrupt,
        # SystemExit, auch in einer Gruppe). `asyncio.wait` wirft das aber
        # NICHT weiter, es liefert nur die erledigten Tasks – die erste Fassung
        # des Umbaus hat es damit stillschweigend verschluckt (Waechter
        # test_mcp_lifespan, "SystemExit in einer Gruppe geht durch"). Hier wird
        # es ausdruecklich abgeholt und geworfen; das Abholen verhindert
        # zugleich "Task exception was never retrieved" im Journal.
        b = self._besitzer
        if b is not None and b.done() and not b.cancelled():
            fehler = b.exception()
            if isinstance(fehler, (KeyboardInterrupt, SystemExit)):
                raise fehler
            if isinstance(fehler, BaseExceptionGroup):
                harte, _ = fehler.split((KeyboardInterrupt, SystemExit))
                if harte is not None:
                    raise harte

    async def _besitzer_lauf(self, bereit: "asyncio.Event"):
        """Lebt so lange wie die Verbindung; nur hier wird der Stack betreten
        UND verlassen. Siehe ``connect``."""
        self._exit_stack = AsyncExitStack()
        try:
            await self._verbinden()
            bereit.set()
            if self.connected:
                await self._stopp.wait()
        except asyncio.CancelledError:
            # Ein Abbruch von aussen (Shutdown) oder ein fremder Scope, der
            # bis hierher durchschlaegt. Der Task endet hier ohnehin; NICHT
            # weiterwerfen, sonst steht "Task exception was never retrieved"
            # im Journal. Ein bereits verbundener Server ist dann schlicht
            # getrennt – das ist kein Fehler, den man melden muesste.
            if not self.connected and not self.error:
                self.error = ("Verbindung abgebrochen – der Server hat den "
                              "Transport fallen lassen (Zertifikat, Netz oder "
                              "Protokoll)")
        finally:
            bereit.set()
            # ⚠ SOFORT schliessen, im SELBEN Task, bevor irgendein anderer
            # await kommt: solange der Scope offen ist, wird jeder await
            # gecancelt. `print` ist kein await.
            stapel, self._exit_stack = self._exit_stack, None
            if stapel is not None:
                try:
                    await stapel.aclose()
                except BaseException as e:  # noqa: BLE001
                    if isinstance(e, (KeyboardInterrupt, SystemExit)):
                        raise
                    # ⚠ NACH EINEM FEHLSCHLAG IST DAS DER NACHHALL, KEIN
                    # PROBLEM. Die TaskGroup des Transports meldet beim
                    # Verlassen den Fehler ihres Kind-Tasks noch einmal (als
                    # ExceptionGroup) – das Aufraeumen ist dabei VOLLSTAENDIG
                    # erfolgt, und der Grund steht schon in `self.error`. Die
                    # erste Fassung schrieb dafuer "Aufraeumen unvollstaendig"
                    # bei JEDEM Startversuch eines kaputten Servers: eine
                    # falsche Aussage im Normalbetrieb, die das Journal
                    # entwertet (Register). Gemeldet wird nur, was ohne
                    # vorherigen Fehler beim Schliessen auftritt.
                    nachhall = bool(self.error) and isinstance(
                        e, (BaseExceptionGroup, asyncio.CancelledError))
                    # ⚠ DER NACHHALL TRAEGT DEN ECHTEN GRUND – nicht wegwerfen.
                    # Gemeldet am 2026-10-25: "weiterhin Verbindung
                    # abgebrochen – Zertifikat, Netz oder Protokoll", waehrend
                    # in dieser Gruppe "IP address mismatch, certificate is not
                    # valid for …" stand. Drei Moeglichkeiten zu nennen, wenn
                    # die eine bekannt ist, schickt den Administrator auf die
                    # Suche (Register: ein richtiger, aber unscharfer Grund ist
                    # nutzlos). Der innerste Grund ersetzt die Sammelmeldung.
                    if nachhall and not getattr(self, "_zeitueberschreitung", False):
                        echt = _innerster_grund(e)
                        if echt:
                            self.error = "Verbindung abgebrochen: " + echt
                    if not nachhall:
                        print(f"[MCP] {self.name}: Aufraeumen unvollstaendig – "
                              f"{type(e).__name__}: {e}", flush=True)
            # Genau EINE Zeile je Fehlschlag – mit dem genauesten Grund, den es
            # gibt (praezisiert aus dem Nachhall, sonst die Sammelmeldung).
            if getattr(self, "_grund_offen", False):
                self._grund_offen = False
                print(f"[MCP] {self.name}: {self.error}", flush=True)
            self._session = None
            self.connected = False
            self.tools = []

    async def _verbinden(self):
        """Der eigentliche Verbindungsaufbau – laeuft IM Besitzer-Task.

        Faengt jeden Fehler und traegt den Grund in ``self.error`` ein; er
        verlaesst den Besitzer nur als normales Ende.
        """
        # Den Transport bestimmt der VERSUCH (connect -> _ein_versuch), nicht
        # mehr die Konfiguration allein: "http" wird dort in zwei Versuche zerlegt.
        transport_type = (getattr(self, "_transport_jetzt", None)
                          or self.config.get("transport", "stdio"))
        try:
            from mcp import ClientSession

            if transport_type == "stdio":
                await self._connect_stdio()
            elif transport_type in ("streamable_http", "streamablehttp"):
                await self._connect_streamable_http()
            elif transport_type == "sse":
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
            # ⚠ HIER STAND EIN `cancelling()`-VORBEHALT – und er war falsch:
            # anyio cancelt den Task, um seinen Scope abzubrechen, damit steht
            # `cancelling()` IMMER auf 1, und der Vorbehalt warf jeden
            # Transportfehler als vermeintlichen Shutdown weiter (DEV
            # 2026-10-25). Nach dem Umbau ist er auch ueberfluessig: dieser
            # Code laeuft im BESITZER-Task (`_besitzer_lauf`), dessen Abbruch
            # den Aufrufer nie erreicht. Ein echter Shutdown cancelt den
            # Besitzer von aussen – der endet dann ohnehin.
            #
            # KEIN `uncancel()` und KEIN weiterer await: der Besitzer verlaesst
            # direkt im Anschluss den Scope (finally -> aclose), und anyio
            # raeumt seinen eigenen Cancel beim Verlassen selbst ab. Jeder
            # await DAZWISCHEN wuerde erneut gecancelt (level-triggered).
            # Eine Zeitueberschreitung hat ihren eigenen, genaueren Grund schon
            # gesetzt (connect) – der Abbruch hier ist dann nur deren Folge.
            if not getattr(self, "_zeitueberschreitung", False):
                self.error = ("Verbindung abgebrochen – der Server hat den "
                              "Transport fallen lassen (Zertifikat, Netz oder "
                              "Protokoll)")
            self.connected = False
            # NICHT hier drucken: der eigentliche Grund steckt in der Gruppe,
            # die erst beim Schliessen kommt (Besitzer, finally). Eine Zeile
            # jetzt und eine zweite, genauere danach hiesse zwei Meldungen fuer
            # EINEN Fehler – und die erste waere die unscharfe. Gedruckt wird
            # dort genau einmal.
            self._grund_offen = True
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
            from mcp.shared._httpx_utils import (MCP_DEFAULT_SSE_READ_TIMEOUT,
                                                 MCP_DEFAULT_TIMEOUT)
            # Dieselben Vorgaben wie `create_mcp_http_client` (mcp 1.x), mit den
            # Konstanten DER BIBLIOTHEK statt eigener Zahlen – ein Server haelt
            # den Antwortstrom offen (300 s Lesefrist). Weiterleitungen bleiben
            # wie dort auf der httpx-Vorgabe (aus); die Transporte folgen ihnen
            # innerhalb des Ursprungs selbst.
            # ⚠ KEIN ZWEITER CLIENT (Code-Review 2026-10-25): bis dahin wurde
            # hier `create_mcp_http_client(...)` gebaut, nur um Header und
            # Timeout abzulesen, und nie geschlossen – je Verbindungsversuch ein
            # verwaister AsyncClient samt Pool.
            if timeout is None:
                timeout = httpx.Timeout(MCP_DEFAULT_TIMEOUT,
                                        read=MCP_DEFAULT_SSE_READ_TIMEOUT)
            kw = {"verify": ctx, "timeout": timeout}
            if headers is not None:
                kw["headers"] = headers
            if auth is not None:
                kw["auth"] = auth
            return httpx.AsyncClient(**kw)

        return {"httpx_client_factory": _factory}

    def _auth_headers(self) -> dict | None:
        """API-Schluessel als Header – an BEIDEN HTTP-Transporten (wie das
        Zertifikat: der "http"-Zweig faellt auf SSE zurueck, und dort fehlte
        er sonst). ``None`` ohne Schluessel = Vorgabe der Bibliothek."""
        return mcp_rechte.auth_header(self.config) or None

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
            streamablehttp_client(url=url, headers=self._auth_headers(),
                                  **self._tls_haken()))
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
            sse_client(url=url, headers=self._auth_headers(),
                       **self._tls_haken()))
        read_stream, write_stream = transport
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()

    async def disconnect(self):
        """Trennt die Verbindung – ueber den BESITZER-Task, nicht selbst.

        ⚠ DER STACK WIRD HIER NICHT MEHR GESCHLOSSEN. anyio verlangt, dass ein
        Cancel-Scope in dem Task verlassen wird, in dem er betreten wurde; im
        Journal von DEV stand genau deshalb "Fehler beim Trennen – Attempted to
        exit cancel scope in a different task than it was entered in" (der
        Aufbau lief im Lifespan-, das Trennen im Request-Task). Jetzt setzt
        ``disconnect`` nur das Stopp-Signal, und der Besitzer schliesst seinen
        eigenen Stack. Subprozesse eines stdio-Servers werden damit sauber
        beendet, statt beim Fehlschlag des Schliessens zu verwaisen.

        Wird DIESER Aufruf gecancelt (Shutdown), geht der Abbruch durch – aber
        erst, nachdem der Besitzer seinerseits gestoppt ist. Gewartet wird mit
        `gather(return_exceptions=True)`: ein Fehler im Besitzer gehoert in
        dessen Meldung, nicht in den Aufrufer.
        """
        besitzer = getattr(self, "_besitzer", None)
        stopp = getattr(self, "_stopp", None)
        try:
            if stopp is not None:
                stopp.set()
            if besitzer is not None and not besitzer.done():
                await asyncio.gather(besitzer, return_exceptions=True)
        except asyncio.CancelledError:
            if besitzer is not None and not besitzer.done():
                besitzer.cancel()
            raise
        finally:
            self._besitzer = None
            self._stopp = None
            self._session = None
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
            **_zugang_status(self.config),
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
        alt = mcp_rechte.altschalter_ohne_freigabe(servers)
        if alt:
            print(f"[MCP] HINWEIS: {', '.join(alt)} – frueher fuer 'alle "
                  f"Netzwerk-Benutzer' freigegeben; diese Stufe gibt es nicht mehr, "
                  f"es darf jetzt NIEMAND (auch kein Administrator). Freigabe unter "
                  f"Einstellungen -> MCP -> Berechtigungen setzen.", flush=True)
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
                    **_zugang_status(srv),
                    "sandbox": (srv.get("sandbox") is not False
                                if srv.get("transport", "stdio") == "stdio" else None),
                })
        return result


# Singleton
mcp_manager = McpClientManager()
