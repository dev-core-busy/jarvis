#!/usr/bin/env python3
"""Regressionstests fuer die Sicherheitsgates von MCP-Werkzeugen (2026-08-14).

Warum diese Datei existiert: MCP-Werkzeuge werden in
``agent.py::_attach_extra_tools`` in denselben Werkzeugkasten gehaengt wie
Skill-Werkzeuge, stammen aber aus FREMDEM Code und arbeiten mit den Zugangsdaten
des SERVERS. Bis zum 2026-08-14 liefen sie damit an drei Schranken vorbei:

  * dem Internet-Gate (``_INTERNET_TOOLS`` / ``requires_internet``) – ein
    Benutzer ohne Internet-Freigabe erreichte ueber einen MCP-Server genau das,
    was ihm ``curl`` verweigert,
  * der Sperrliste fuer Netzwerk-Benutzer (``_BLOCKED_TOOLS_FOR_LDAP``),
  * jedem Eigentuemer-/Actor-Bezug ("fremde Zugangsdaten als Vollmacht", eines
    der vier Fehlermuster der Endpunkt-Durchsicht vom 2026-08-04).

Gehalten hat nur die Rollen-Whitelist (``agent_roles.effektive_werkzeuge``), weil
sie eine Whitelist ist und ``mcp_*`` dort nicht steht. Diese Tests halten die
Reparatur fest.

Laeuft ohne fastapi/mcp: ``McpRemoteTool`` wird per Quelltext geladen (das
``mcp``-Paket importiert ``mcp_client`` ohnehin erst in ``connect()``),
``_ist_mcp_tool`` per Quelltext aus agent.py. ``backend.config`` ist ein Stub –
der echte Import migriert Profile und schriebe die LIVE-settings.json zurueck.

    python3 tests/test_mcp_gates.py
"""
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_fail = 0
_ok = 0


def check(cond, label):
    global _fail, _ok
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


# ── Sandkasten-Schranke ─────────────────────────────────────────────────────
# backend.config NIE echt importieren: der Import laeuft durch die
# Profil-Migration und schreibt settings.json zurueck. Passiert das im Test,
# steht danach ein Testzustand in der echten Konfiguration.
if "backend.config" in sys.modules:
    print("ABBRUCH: backend.config ist bereits geladen – Test wuerde die echte "
          "settings.json anfassen.", file=sys.stderr)
    raise SystemExit(2)

AGENT_SRC = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
MCP_SRC = (ROOT / "backend" / "mcp_client.py").read_text(encoding="utf-8")
CFG_SRC = (ROOT / "backend" / "config.py").read_text(encoding="utf-8")
MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
JS_SRC = (ROOT / "frontend" / "js" / "mcp.js").read_text(encoding="utf-8")
I18N_SRC = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")

# ── McpRemoteTool isoliert laden ────────────────────────────────────────────
# EXIT 2, nicht 1: "der Test konnte gar nicht laufen" muss von "eine Pruefung ist
# fehlgeschlagen" unterscheidbar sein – sonst sieht eine Gegenprobe gegen einen
# alten Stand wie ein normaler Fehlschlag aus (Lehre aus tests/test_skill_audit.py).
def _hol(pattern, quelle, was, flags=re.S):
    m = re.search(pattern, quelle, flags)
    if not m:
        print(f"ABBRUCH: {was} nicht gefunden – gegen diesen Stand ist der Test "
              f"nicht lauffaehig.", file=sys.stderr)
        raise SystemExit(2)
    return m.group(0)


# `erlaubt_fuer` liest die Freigabe zur Laufzeit aus `config` und wertet sie in
# `mcp_rechte` aus. mcp_rechte importiert weder config noch main – es darf
# echt geladen werden; config bleibt ein Stub mit veraenderbarer Serverliste.
from backend import mcp_rechte as _mcp_rechte


class _CfgStub:
    servers: list = []

    def get_mcp_servers(self):
        return self.servers


_cfg_stub = _CfgStub()
_ns = {"BaseTool": object, "Any": object, "config": _cfg_stub,
       "mcp_rechte": _mcp_rechte}
exec(_hol(r'\nclass McpRemoteTool\(BaseTool\):.*?(?=\n# ─|\nclass McpServerConnection)',
          MCP_SRC, "McpRemoteTool in mcp_client.py"), _ns)
McpRemoteTool = _ns["McpRemoteTool"]

_ans = {"_MCP_TOOL_PREFIX": "mcp_"}
exec(_hol(r'\ndef _ist_mcp_tool\(.*?(?=\ndef |\n# ──|\Z)',
          AGENT_SRC, "_ist_mcp_tool in agent.py"), _ans)
_ist_mcp_tool = _ans["_ist_mcp_tool"]


def mk(server_config=None, tool_name="search"):
    return McpRemoteTool("atlassian", {"name": tool_name, "description": "d"},
                         session=None, server_config=server_config)


# ── 1. Marker am Werkzeug ───────────────────────────────────────────────────
print("\n1. Marker am Werkzeug")
t = mk()
check(getattr(t, "requires_internet", False) is True,
      "requires_internet=True (Internet-Gate greift ueber getattr)")
check(getattr(t, "ist_mcp", False) is True, "ist_mcp=True")
check(t.name.startswith("mcp_"), f"Name traegt den Praefix ({t.name})")
# Der Dispatch fragt genau so ab – wenn sich der Ausdruck aendert, faellt das hier auf.
check('getattr(tool, "requires_internet", False)' in AGENT_SRC,
      "Dispatch prueft requires_internet per getattr")

# ── 2. Kein Altschalter mehr ────────────────────────────────────────────────
# "alle Netzwerk-Benutzer" (allow_network_users) gibt es seit 2026-10-25 nicht
# mehr – Freigabe wie bei SAP & Co., leer = niemand.
print("\n2. Werkzeug traegt keinen Freigabe-Schnappschuss")
check(not hasattr(mk({"allow_network_users": True}), "erlaubt_netzwerk_benutzer"),
      "kein beim Bau eingefrorener Freigabewert am Werkzeug")

# ── 2b. Freigabe zur LAUFZEIT (Benutzer/Gruppen, leer = niemand) ──────────
print("\n2b. erlaubt_fuer liest die aktuelle Freigabe")


def _mit(cfg):
    _cfg_stub.servers = [dict(cfg, id="s1")]
    return mk({"id": "s1"})


check(_mit({}).erlaubt_fuer("m.muster") is False, "nichts freigegeben: gesperrt")
check(_mit({"allow_network_users": True}).erlaubt_fuer("m.muster") is False,
      "Altschalter 'alle Netzwerk-Benutzer' gibt NICHTS mehr frei")
check(_mit({"allowed_users": "a.b, M.Muster"}).erlaubt_fuer("FIRMA\\m.muster") is True,
      "Benutzerliste: Login normalisiert (Domain-Praefix, Gross/Klein)")
check(_mit({"allowed_users": "a.b"}).erlaubt_fuer("m.muster") is False,
      "nicht in der Liste: gesperrt")
check(_mit({"allowed_users": "m.muster"}).erlaubt_fuer("") is False,
      "ohne Benutzernamen: gesperrt")
# Die Freigabe wirkt OHNE Neubau des Werkzeugs – genau das ist der Sinn.
_t = _mit({"allowed_users": "m.muster"})
check(_t.erlaubt_fuer("m.muster") is True, "vorher frei")
_cfg_stub.servers[0]["allowed_users"] = ""
check(_t.erlaubt_fuer("m.muster") is False, "Liste geleert: sofort gesperrt")
_cfg_stub.servers = []
check(_t.erlaubt_fuer("m.muster") is False, "Server entfernt: gesperrt (fail-closed)")

# ── 3. Erkennung im Dispatch ────────────────────────────────────────────────
print("\n3. _ist_mcp_tool")


class _Dummy:
    pass


class _Echt:
    ist_mcp = True


check(_ist_mcp_tool(_Echt(), "mcp_x_y") is True, "Attribut UND Praefix")
check(_ist_mcp_tool(_Echt(), "irgendwas") is True,
      "Attribut allein genuegt (umbenanntes Werkzeug)")
check(_ist_mcp_tool(_Dummy(), "mcp_x_y") is True,
      "Praefix allein genuegt (Werkzeug-Objekt ohne Attribut)")
check(_ist_mcp_tool(None, "mcp_x_y") is True, "auch ohne Werkzeug-Objekt")
check(_ist_mcp_tool(_Dummy(), "shell_execute") is False, "normales Werkzeug: nein")
check(_ist_mcp_tool(_Dummy(), "memory_manage") is False, "normales Werkzeug: nein (2)")
# Ein Werkzeug, das 'mcp' nur ENTHAELT, ist keines – sonst traefe die Sperre
# willkuerliche Namen.
check(_ist_mcp_tool(_Dummy(), "dump_mcp_state") is False,
      "Praefix, nicht Teilstring")

# ── 4. Der Dispatch-Zweig ───────────────────────────────────────────────────
print("\n4. Dispatch-Zweig in agent.py")
_zweig = re.search(r'\n            if \(not _ldap_blocked and _ist_mcp_tool\(tool, name\).*?_ldap_blocked = True\n',
                   AGENT_SRC, re.S)
check(bool(_zweig), "Zweig vorhanden")
_z = _zweig.group(0) if _zweig else ""
check('_mcp_freigegeben(tool, _uname)' in _z,
      "prueft die Freigabe fuer DIESEN Benutzer")
_fns = {}
exec(_hol(r'\ndef _mcp_freigegeben\(.*?(?=\ndef |\n# ──|\Z)', AGENT_SRC,
          "_mcp_freigegeben in agent.py"), _fns)
_mf = _fns["_mcp_freigegeben"]


class _OhneMethode:
    ist_mcp = True


class _Wirft:
    def erlaubt_fuer(self, b):
        raise RuntimeError("kaputt")


class _Ja:
    def erlaubt_fuer(self, b):
        return True


class _Truthy:
    def erlaubt_fuer(self, b):
        return "ja"


check(_mf(_OhneMethode(), "x") is False,
      "fremdes Werkzeug-Objekt ohne erlaubt_fuer: gesperrt (fail-closed)")
check(_mf(_Wirft(), "x") is False, "Pruefung wirft: gesperrt")
check(_mf(_Ja(), "x") is True, "Pruefung sagt True: frei")
check(_mf(_Truthy(), "x") is False, "nur ein echtes True zaehlt")
check('_ldap_blocked = True' in _z, "setzt _ldap_blocked")
# Wie SAP/VEMAS: keine Verstoss-Zaehlung – das MODELL waehlt das Werkzeug.
check('_viol' not in _z, "kein Verstoss-Eintrag (wie SAP/VEMAS)")
check('_privileged' not in _z and 'is_admin' not in _z,
      "kein Admin-Bypass im Zweig (leer = niemand, auch kein Administrator)")
check('Zugriff verweigert' in _z, "Klartext-Absage an das Modell")
check('Einstellungen' in _z, "Meldung nennt den Weg zur Freigabe")

# Der Zweig steht AUSSERHALB der `if not _privileged:`-Kette – kein
# Admin-Bypass, wie bei SAP/VEMAS (Festlegung 2026-10-25).
_pos = AGENT_SRC.find("if (not _ldap_blocked and _ist_mcp_tool(tool, name)")
_vemas = AGENT_SRC.find("BLOCKED VEMAS-Tool")
check(_pos != -1 and AGENT_SRC.find("elif _ist_mcp_tool(tool, name)") == -1,
      "kein Zweig mehr in der 'not _privileged'-Kette")
check(_vemas != -1 and _pos > _vemas, "steht bei den Bereichs-Freigaben (nach VEMAS)")

# ── 5. Konfiguration – das Feld an BEIDEN Stellen ───────────────────────────
print("\n5. config.py")
_add = _hol(r'def add_mcp_server\(.*?(?=\n    def )', CFG_SRC, "add_mcp_server")
_upd = _hol(r'def update_mcp_server\(.*?(?=\n    def )', CFG_SRC, "update_mcp_server")
check('freigabe_normalisieren(data)' in _add and 'freigabe_normalisieren(data)' in _upd,
      "Freigabefelder an BEIDEN Stellen (add und update)")
check('"allow_network_users"' not in _add, "add schreibt den Altschalter nicht mehr")
# Isolation: Vorgabe AN, deshalb `is not False` – bei `is True` waere ein
# Altbestand-Server ohne das Feld ploetzlich ungeschuetzt.
check('data.get("sandbox") is not False' in _add, "add_mcp_server: sandbox Vorgabe AN")
check('data["sandbox"] is not False' in _upd, "update_mcp_server: sandbox Vorgabe AN")
check("sandbox_paths" in _add and "sandbox_paths" in _upd,
      "sandbox_paths an BEIDEN Stellen")
# Die Projektregel "neues Feld = ZWEI Stellen" ist genau der Fehler, an dem
# prompt_tool_calling jahrelang wirkungslos war.
check('srv.pop("allow_network_users", None)' in _upd,
      "update raeumt den Altschalter beim Speichern der Freigabe ab")

# ── 6. Status-Endpunkt zeigt den Zustand ────────────────────────────────────
print("\n6. get_status")
check('"allow_network_users"' not in MCP_SRC,
      "Status meldet den Altschalter nicht mehr (die Freigabe kommt aus _zugang_status)")

# ── 7. Werkzeugkasten wird nachgeladen ──────────────────────────────────────
print("\n7. main.py – Agent erfaehrt von Aenderungen")
# Ohne _reload_agent_tools() wirkt eine Freigabe erst nach Dienst-Neustart:
# Adresse/Schluessel/Zertifikat wirken erst mit neuer Verbindung. Gleiche Falle
# wie beim Skill-Toggle (2026-08-10).
for _ep in ["add_mcp_server", "update_mcp_server", "remove_mcp_server",
            "toggle_mcp_server", "reconnect_mcp_server"]:
    _m2 = re.search(r'async def ' + _ep + r'\(.*?(?=\n@app\.|\n# ─)', MAIN_SRC, re.S)
    check(bool(_m2) and '_reload_agent_tools()' in _m2.group(0),
          f"{_ep} laedt die Werkzeuge neu")

# ── 7b. stdio-Server erbt NICHT die Dienst-Umgebung ─────────────────────────
print("\n7b. Umgebung des stdio-Subprozesses")
# Am echten Referenzserver gemessen (get-env): vorher sah der Fremdprozess 50
# Variablen, darunter AGENT_API_KEY, GEMINI_API_KEY,
# GOOGLE_OAUTH_CLIENT_SECRET und JARVIS_PASSWORD.
# FALLSTRICK (im Projekt der vierte Fall dieser Art): auf den CODE pruefen, nicht
# auf das Wort – der Begruendungskommentar daneben zitiert die alte Zeile woertlich
# und laesst eine naive Textsuche falsch anschlagen.
_code_zeilen = [z for z in MCP_SRC.splitlines() if not z.lstrip().startswith("#")]
check(not any("{**os.environ" in z for z in _code_zeilen),
      "die ganze Dienst-Umgebung wird NICHT mehr durchgereicht")
check("_ENV_WEITERGEBEN" in MCP_SRC, "Whitelist vorhanden")
_wl = _hol(r'_ENV_WEITERGEBEN = \(.*?\n\)', MCP_SRC, "_ENV_WEITERGEBEN")
_ns2 = {}
exec(_wl, _ns2)
WL = _ns2["_ENV_WEITERGEBEN"]
check("PATH" in WL, "PATH dabei (sonst wird npx/python3 nicht gefunden)")
check("HOME" in WL, "HOME dabei (sonst sucht npm seinen Cache in /root)")
for geheim in ("AGENT_API_KEY", "GEMINI_API_KEY", "GOOGLE_OAUTH_CLIENT_SECRET",
               "JARVIS_PASSWORD", "SECRET_KEY", "ANTHROPIC_API_KEY",
               "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
    check(geheim not in WL, f"{geheim} NICHT in der Whitelist")
# Kein Wert mit Geheimnischarakter – auch keiner, der spaeter dazukommt.
_verdaechtig = [n for n in WL
                if any(v in n.upper() for v in ("KEY", "TOKEN", "SECRET", "PASSW", "CREDENTIAL"))]
check(not _verdaechtig, f"kein schluessel-artiger Name in der Whitelist ({_verdaechtig})")
_stdio = _hol(r'async def _connect_stdio\(self\):.*?(?=\n    async def )',
              MCP_SRC, "_connect_stdio")
check("env.update(env_vars)" in _stdio,
      "die konfigurierten env-Variablen kommen weiterhin durch")
check(_stdio.index("_ENV_WEITERGEBEN") < _stdio.index("env.update(env_vars)"),
      "Whitelist zuerst, Konfiguration ueberschreibt sie")

# ── 7c. stdio-Server laeuft isoliert (bwrap) ────────────────────────────────
print("\n7c. Isolation des stdio-Subprozesses")
_bw = {"os": __import__("os")}
exec(_hol(r'_BWRAP = .*?(?=\ndef bwrap_verfuegbar)', MCP_SRC, "_BWRAP-Block"), _bw)
exec(_hol(r'def _bwrap_wrappen.*?(?=\n\n# ─)', MCP_SRC, "_bwrap_wrappen"), _bw)
cmd, bargs = _bw["_bwrap_wrappen"]("npx", ["-y", "paket", "stdio"], [])
z = " ".join(bargs)
check(cmd.endswith("bwrap") or cmd.endswith("setpriv"),
      "Aufruf laeuft ueber bwrap (ggf. hinter setpriv)")
check("bwrap" in z or cmd.endswith("bwrap"), "bwrap ist im Aufruf enthalten")
# Ambient-Capabilities muessen VOR bwrap fallen: die Unit gibt dem Backend
# CAP_NET_BIND_SERVICE (Port 443), das wird vererbt, und bwrap verweigert dann
# den Dienst ("Unexpected capabilities but not setuid"). Im Dienst war die
# Isolation dadurch tot, in jeder Handprobe funktionierte sie.
if cmd.endswith("setpriv"):
    check("--ambient-caps=-all" in z, "Ambient-Capabilities werden abgelegt")
    check("--inh-caps=-all" in z, "vererbbare Capabilities werden abgelegt")
    check(z.index("--ambient-caps=-all") < z.index("bwrap"),
          "setpriv laeuft VOR bwrap")
check("--ro-bind /usr /usr" in z, "/usr nur lesbar eingeblendet")
# Der Kern: das Dienst-Verzeichnis existiert im Namespace NICHT.
check("/opt" not in z, "/opt wird NICHT eingeblendet (Dienst + data/ + .env)")
check(" /home " not in z and "--ro-bind /home" not in z,
      "/home wird NICHT eingeblendet")
for flag, warum in [("--unshare-pid", "eigener PID-Namespace (kein ps/kill auf Dienstprozesse)"),
                    ("--unshare-user", "User-Namespace (laeuft unprivilegiert)"),
                    ("--unshare-ipc", "eigener IPC-Namespace"),
                    ("--die-with-parent", "keine Waisenprozesse"),
                    ("--new-session", "kein steuerndes Terminal"),
                    ("--tmpfs /tmp", "privates /tmp")]:
    check(flag in z, f"{flag} – {warum}")
check(z.rstrip().endswith("-- npx -y paket stdio"),
      "der eigentliche Befehl steht nach dem Trenner --")
# Zusatzpfade: nur absolut und vorhanden, sonst landen sie im Namespace woanders
c2, a2 = _bw["_bwrap_wrappen"]("x", [], ["/usr", "relativ/pfad", "/gibt/es/nicht", ""])
z2 = " ".join(a2)
check(z2.count("--ro-bind /usr /usr") >= 1, "vorhandener Zusatzpfad wird eingeblendet")
check("relativ/pfad" not in z2, "relativer Zusatzpfad wird verworfen")
check("/gibt/es/nicht" not in z2, "nicht vorhandener Zusatzpfad wird verworfen")
check("--bind " not in z2, "Zusatzpfade sind NUR lesbar (kein --bind)")
# Fail-closed: ohne bwrap kein stillschweigend ungeschuetzter Start
_st = _hol(r'async def _connect_stdio\(self\):.*?(?=\n    async def )',
           MCP_SRC, "_connect_stdio (2)")
check('self.config.get("sandbox") is not False' in _st,
      "Vorgabe AN (nur ein ausdrueckliches false schaltet ab)")
check("bwrap_verfuegbar()" in _st and "raise RuntimeError" in _st,
      "fehlt bwrap, wird NICHT ungeschuetzt gestartet (fail-closed)")
check(_st.index("_bwrap_wrappen") > _st.index("env.update(env_vars)"),
      "Wrapping nach dem Env-Aufbau (der Befehl wird ersetzt, nicht die Umgebung)")

# ── 7d. Transport: Streamable HTTP ──────────────────────────────────────────
print("\n7d. Transport")
check("streamablehttp_client" in MCP_SRC, "Streamable-HTTP-Client wird benutzt")
# Seit dem Besitzer-Task-Umbau (2026-10-24) waehlt `_verbinden` den Transport,
# nicht mehr `connect` – der Schnitt folgt dem Code.
_conn = _hol(r'async def _verbinden\(self\):.*?(?=\n    async def )', MCP_SRC, "_verbinden()")
check('"streamable_http"' in _conn, "Transport 'streamable_http' waehlbar")
check('transport_type == "sse"' in _conn, "'sse' waehlt weiterhin den alten Transport")
# "http": erst Streamable HTTP, dann SSE – seit dem Code-Review 2026-10-25 als
# ZWEI Versuche mit je eigenem Besitzer-Task (der fruehere `except Exception`
# in _verbinden war toter Code). Gemessen wird das VERHALTEN von connect():
# die Funktion laeuft wirklich, `_ein_versuch` ist eine Attrappe.
import ast as _ast
import asyncio as _asyncio
_cbaum = _ast.parse(MCP_SRC)
_cfn = next((n for k in _cbaum.body if isinstance(k, _ast.ClassDef) and k.name == "McpServerConnection"
             for n in k.body if isinstance(n, _ast.AsyncFunctionDef) and n.name == "connect"), None)
if _cfn is None:
    print("ABBRUCH: McpServerConnection.connect nicht gefunden", file=sys.stderr)
    raise SystemExit(2)
_cns = {}
exec(compile(_ast.fix_missing_locations(_ast.Module(body=[_ast.ClassDef(
    name="_C", bases=[], keywords=[], decorator_list=[], type_params=[], body=[_cfn])],
    type_ignores=[])), "mcp", "exec"), _cns)


class _Verb(_cns["_C"]):
    def __init__(self, transport, gelingt):
        self.config = {"transport": transport}
        self.name = "x"
        self.connected = False
        self.error = None
        self.versuche = []
        self._gelingt = gelingt

    async def _ein_versuch(self, t):
        self.versuche.append(t)
        self.connected = t in self._gelingt
        self.error = None if self.connected else f"fehler-{t}"


def _lauf(transport, gelingt):
    v = _Verb(transport, gelingt)
    _asyncio.run(v.connect())
    return v


v = _lauf("http", {"sse"})
check(v.versuche == ["streamable_http", "sse"] and v.connected,
      f"'http': erst Streamable HTTP, dann SSE als Rueckfall ({v.versuche})")
v = _lauf("http", {"streamable_http"})
check(v.versuche == ["streamable_http"], "'http': gelingt Streamable HTTP, kein SSE-Versuch")
v = _lauf("http", set())
check("fehler-streamable_http" in (v.error or "") and "fehler-sse" in (v.error or ""),
      f"beide gescheitert: BEIDE Gruende in der Meldung ({v.error})")
v = _lauf("sse", {"sse"})
check(v.versuche == ["sse"], "'sse' ist genau EIN Versuch")
v = _lauf("streamable_http", set())
check(v.versuche == ["streamable_http"], "'streamable_http' faellt NICHT auf SSE zurueck")
_vb = _hol(r'async def _verbinden\(self\):.*?(?=\n    async def )', MCP_SRC, "_verbinden()")
check('"_transport_jetzt"' in _vb, "_verbinden nimmt den Transport des Versuchs")
# Das Dreier-Tupel ist die Falle: sse_client liefert zwei Werte, dieser drei.
_sh = _hol(r'async def _connect_streamable_http\(self\):.*?(?=\n    async def )',
           MCP_SRC, "_connect_streamable_http")
check("transport[0], transport[1]" in _sh,
      "Dreier-Tupel wird korrekt ausgepackt (nicht 'a, b = transport')")

# TLS-Factory (Code-Review 2026-10-25): kein Wegwerf-Client je Versuch.
_th = _hol(r'def _tls_haken\(self\) -> dict:.*?(?=\n    async def )', MCP_SRC, "_tls_haken")
_th_code = "\n".join(z for z in _th.splitlines() if not z.lstrip().startswith("#"))
check(_th_code.count("AsyncClient(") == 1 and "create_mcp_http_client(" not in _th_code,
      "Factory baut genau EINEN Client (kein ungeschlossener zweiter)")
check("MCP_DEFAULT_TIMEOUT" in _th_code and "MCP_DEFAULT_SSE_READ_TIMEOUT" in _th_code,
      "Zeitvorgaben aus den Konstanten der Bibliothek, keine eigenen Zahlen")

# ── 8. Frontend – Fremdtext wird entschaerft ────────────────────────────────
print("\n8. mcp.js")
# Werkzeugnamen und -beschreibungen kommen vom MCP-Server, also aus fremdem
# Code, und gehen in ein innerHTML im ADMIN-Bereich (Sitzungstoken im
# localStorage).
check('function _esc(' in JS_SRC, "Escape-Helfer vorhanden")
for roh in ['${srv.name}', '${t.name}', '${t.description', '${srv.error}', '${srv.id}']:
    check(roh not in JS_SRC, f"kein rohes {roh} im Markup")
check('_esc(srv.name)' in JS_SRC and '_esc(t.name)' in JS_SRC,
      "Servername und Werkzeugname entschaerft")
check('data-action="rechte"' in JS_SRC, "Berechtigungs-Knopf vorhanden")
check('data-f="sandbox" checked' in JS_SRC,
      "Isolations-Kaestchen im Formular, vorbelegt")
check("checked !== false" in JS_SRC,
      "Formular sendet sandbox=true, solange nicht ausdruecklich abgewaehlt")
check('value="streamable_http"' in JS_SRC, "Streamable HTTP im Transport-Pulldown")
check("sandbox_paths" in JS_SRC, "Zusatzpfade im Formular")
check("_rechte(" in JS_SRC, "Handler vorhanden")
# Aufbau der Karte (Wunsch 2026-10-25): Berechtigungen in der KOPFZEILE, die
# Einstellungen IM einklappbaren Teil – kein Zahnrad, kein Formular daneben.
_karte = re.search(r'_renderCard\(srv\) \{.*?\n        \}\n', JS_SRC, re.S)
_k = _karte.group(0) if _karte else ""
_kopf = _k[_k.find('class="mcp-card-header"'):_k.find('class="mcp-card-status"')]
_koerper = _k[_k.find('class="mcp-card-body"'):]
check(bool(_kopf) and 'data-action="rechte"' in _kopf, "Berechtigungen-Knopf in der Kopfzeile")
check('data-action="rechte"' not in _koerper, "kein zweiter Berechtigungen-Knopf im Koerper")
check('data-form-for=' in _koerper, "Einstellungsformular im einklappbaren Teil")
check('data-action="edit"' not in JS_SRC and "gear()" not in JS_SRC, "kein Zahnrad mehr")
# Befund Code-Review 2026-10-25: der gespeicherte Transport bleibt erhalten
# (frueher wurde 'http' im Formular still zu 'streamable_http').
check("'streamable_http' : (cfg.transport" not in JS_SRC
      and "sel.appendChild(o)" in JS_SRC
      and re.search(r"^\s*sel\.value = tr;\s*$", JS_SRC, re.M) is not None,
      "Bearbeiten bewahrt einen Transport ohne eigene Option ('http')")
# Auge am API-Schluessel (gemeldet 2026-10-25: "'Kennwort anzeigen' ohne
# Funktion"): das Feld traegt Quelle und Kennung ueber den gemeinsamen Helfer.
check("window.JarvisPwEye.geheim($('[data-f=\"key\"]'), 'mcp'," in JS_SRC
      and "cfg.id + ':api_key'" in JS_SRC,
      "Schluesselfeld hat eine Quelle fuer das Auge (Bereich 'mcp')")
check(re.search(r'id="mcp-f-', JS_SRC) is None,
      "Formularfelder ohne feste IDs (mehrere Karten koennen offen sein)")
_set = re.search(r'\n        _rechte\(.*?(?=\n        /\*\*|\n        async |\n        _)', JS_SRC, re.S)
_s = _set.group(0) if _set else ""
check("JarvisFreigabe.oeffnen" in _s, "benutzt das gemeinsame Freigabe-Popup")
check("mitAlle" not in JS_SRC and "allow_network_users" not in JS_SRC,
      "keine Stufe 'alle' mehr im Frontend")
check("JSON.stringify({ allowed_users: w.users," in _s and "allowed_group: w.groups" in _s,
      "sendet NUR die zwei Freigabefelder (der Endpunkt merged – ein voller "
      "Formularstand ueberschriebe die Serverdaten)")
check("'PUT'" in _s, "per PUT")

# ── 9. i18n in beiden Sprachen ──────────────────────────────────────────────
print("\n9. i18n")
for key in ["mcp.net_users_hint", "mcp.rights_selected", "mcp.rights_none",
            "mcp.transport_shttp", "mcp.sandbox_label", "mcp.sandbox_on",
            "mcp.sandbox_off", "mcp.sandbox_hint", "mcp.sandbox_paths_label",
            "frg.sum_none", "frg.or_hint"]:
    check(I18N_SRC.count(f"'{key}'") >= 2, f"{key} in DE und EN")
for alt in ["mcp.net_users_on", "mcp.net_users_off", "mcp.net_users_confirm",
            "frg.only_admins", "frg.all", "frg.sum_all"]:
    check(f"'{alt}'" not in I18N_SRC, f"{alt} entfernt (Stufe gibt es nicht mehr)")
_de = re.search(r"'mcp\.net_users_hint':\s*'([^']*)'", I18N_SRC)
check(bool(_de) and "auch kein Administrator" in _de.group(1),
      "Hinweis nennt 'leer = niemand, auch kein Administrator'")

print(f"\n{'='*60}\n{_ok} OK, {_fail} FAIL\n{'='*60}")
sys.exit(1 if _fail else 0)
