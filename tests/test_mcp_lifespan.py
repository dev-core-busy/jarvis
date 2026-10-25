#!/usr/bin/env python3
"""Waechter: EIN MCP-Server darf den Dienst nicht beenden (2026-10-24).

⚠ BEZAHLTER VORFALL (DEV, 2026-10-24, 34 Neustarts in sechs Minuten):
Ein entfernter MCP-Server ("theben") war per `streamable_http` eingetragen und
antwortete mit einem selbstsignierten Zertifikat. Der Fehler kam NICHT als
`Exception` an, sondern als ``asyncio.CancelledError``: `streamablehttp_client`
haelt intern eine anyio-TaskGroup, und wenn deren HTTP-Task scheitert, cancelt
der Scope unser wartendes ``session.initialize()``. ``CancelledError`` erbt von
``BaseException`` – das ``except Exception`` in ``connect()`` UND das in
``startup_mcp`` sahen sie nicht. Sie lief bis in den Starlette-Lifespan:

    ERROR:    Application startup failed. Exiting.
    systemd:  Main process exited, code=exited, status=3/NOTIMPLEMENTED

Im Journal stand dabei KEINE Zeile "[MCP] Startup-Fehler" – der Beleg, dass der
Handler nie griff. Der Dienst war wegen EINES optionalen Werkzeugs vollstaendig
weg, und zwar erst beim naechsten Neustart, also zeitlich entkoppelt von der
Konfigurationsaenderung, die ihn ausloeste.

GEMESSEN WIRD DIE WIRKUNG, nicht ein `except`-Zweig im Quelltext:
  1. Positivkontrolle – ein gesunder Server wird wirklich verbunden (ohne sie
     waere jede Folgepruefung trivial: ein Aufbau, der nie verbindet, bricht
     auch nie ab).
  2. Ein Server, dessen `initialize()` CancelledError wirft, laesst `connect()`
     normal zurueckkehren und traegt den Grund in `error`.
  3. Dasselbe fuer eine BaseExceptionGroup (so kommt der Fehler beim
     Aufraeumen).
  4. `connect_all()` verbindet die GESUNDEN Server – in BEIDEN Reihenfolgen.
     Vorher hing das Ergebnis an der Reihenfolge in der Konfiguration.
  5. GEGENKONTROLLE: ein ECHTER Abbruch (unser Task wird gecancelt) geht DURCH.
     Ohne sie waere der Fix ein Shutdown, der haengt – der schlechtere Fehler.
  6. KeyboardInterrupt/SystemExit in einer Gruppe gehen ebenfalls durch.
  7. `startup_mcp` in main.py am Syntaxbaum: der Handler deckt BaseException ab.

``backend.config`` und ``mcp`` nur als Attrappen – der echte config-Import
schreibt die Live-settings.json zurueck, und `mcp` ist hier nicht installiert.
Die Attrappen bilden die ECHTEN Signaturen nach (Register).

    venv/bin/python tests/test_mcp_lifespan.py

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
FAIL = 0


def check(name: str, bed: bool, zusatz: str = "") -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" – " + zusatz if zusatz else ""))


def abschnitt(t: str) -> None:
    print("\n" + t)


_bilanz_gedruckt = False


def bilanz_und_ende() -> None:
    global _bilanz_gedruckt
    _bilanz_gedruckt = True
    print("\n" + "=" * 62)
    print("  %d OK, %d FAIL" % (OK, FAIL))
    print("=" * 62)
    sys.exit(1 if FAIL else 0)


# ⚠ "Exit 1 OHNE Bilanzzeile" ist ein EIGENER Befund und von "ich beisse" nicht
# zu unterscheiden – beim Bau dieses Waechters genau einmal passiert (ein
# falscher Klassenname liess ihn mit AttributeError sterben, Exit 1, keine
# Bilanz). Ein stiller Absturz meldet sich jetzt als Exit 2.
def _abbruch_melden():
    if _bilanz_gedruckt:
        return
    print("\n" + "=" * 62)
    print("  ABBRUCH: der Waechter ist vor der Bilanz gestorben – das ist "
          "'konnte nicht laufen', NICHT 'bestanden' und nicht 'beisst'.")
    print("  (bis hierher: %d OK, %d FAIL)" % (OK, FAIL))
    print("=" * 62)
    sys.stdout.flush()
    os._exit(2)



def abbruch(text: str) -> None:
    """'Konnte nicht laufen' – IMMER Exit 2, nie die Bilanz.

    ⚠ BEZAHLT BEIM BAU DER GEGENPROBE (2026-10-25): die Abbruch-Stellen riefen
    `bilanz_und_ende()`, und die endet mit `exit(1 if FAIL else 0)`. Bei null
    FAILs meldete ein ABBRUCH damit "bestanden" – genau der Zustand, gegen den
    die Exit-2-Stufe gebaut ist. Gefunden hat es eine Sonde, die den Messaufbau
    blind machte und Exit 0 statt 2 bekam (Register: ein Abbruch ist von einem
    bestandenen Lauf sonst nicht zu unterscheiden). Zwei der Stellen standen
    schon im Commit e5e51072.
    """
    global _bilanz_gedruckt
    _bilanz_gedruckt = True        # der atexit-Melder soll nicht doppelt melden
    print("ABBRUCH: " + text)
    print("  (bis hierher: %d OK, %d FAIL – 'konnte nicht laufen', NICHT "
          "bestanden)" % (OK, FAIL))
    sys.stdout.flush()
    sys.exit(2)

import atexit                                                      # noqa: E402
import os                                                          # noqa: E402

atexit.register(_abbruch_melden)


# ── Attrappen, VOR dem Import von backend.mcp_client ────────────────────────
# `config` liefert die Serverliste; der echte Import migriert Profile und
# schreibt settings.json (Register).
_server: list = []


class _ConfigStub:
    def get_mcp_servers(self):
        return _server


_cfg_mod = types.ModuleType("backend.config")
_cfg_mod.config = _ConfigStub()
sys.modules["backend.config"] = _cfg_mod

# `mcp` ist hier nicht installiert. Die Attrappe stellt die Namen, die
# `connect()` importiert – mit der ECHTEN Form: ClientSession ist ein
# async context manager, `initialize()` eine Coroutine, `list_tools()` liefert
# ein Objekt mit `.tools`.
class _Tool:
    def __init__(self, name):
        self.name = name
        self.description = "Probe"
        self.inputSchema = {"type": "object", "properties": {}}


class _ToolsAntwort:
    def __init__(self, tools):
        self.tools = tools


class _ClientSession:
    def __init__(self, read_stream, write_stream):
        self._r, self._w = read_stream, write_stream

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def initialize(self):
        return None

    async def list_tools(self):
        return _ToolsAntwort([_Tool("probe_werkzeug")])


_mcp_mod = types.ModuleType("mcp")
_mcp_mod.ClientSession = _ClientSession
_mcp_mod.StdioServerParameters = object
sys.modules["mcp"] = _mcp_mod
for _n in ("mcp.client", "mcp.client.streamable_http", "mcp.client.stdio",
           "mcp.client.sse"):
    _m = types.ModuleType(_n)
    sys.modules[_n] = _m
sys.modules["mcp.client.streamable_http"].streamablehttp_client = (
    lambda **kw: None)

try:
    from backend import mcp_client as MC
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: backend.mcp_client nicht ladbar: %s" % e)
    sys.exit(2)


def _konf(name, transport="streamable_http"):
    return {"id": "id-" + name, "name": name, "transport": transport,
            "url": "https://beispiel.invalid/mcp", "enabled": True}


def _verbindung(name, wirft=None):
    """Eine echte McpServerConnection, deren Transport-Schritt `wirft` auslöst.

    Gepatcht wird NUR der Transport (die Stelle, an der im Vorfall das
    Zertifikat scheiterte) – `connect()` selbst laeuft echt, samt seinen
    except-Zweigen. Ein Nachbau von `connect()` wuerde die Zusage nicht messen.
    """
    c = MC.McpServerConnection(_konf(name))

    async def _transport():
        if wirft is not None:
            raise wirft()
        # Der gesunde Fall: Session setzen, wie der echte Transport es tut.
        c._session = _ClientSession(object(), object())

    c._connect_streamable_http = _transport
    return c


# ── 1./2./3. connect(): der Fehler bleibt beim Server ───────────────────────
abschnitt("1. connect(): ein Transportfehler beendet nichts")


def _gruppe_mit_connect_fehler():
    return BaseExceptionGroup("unhandled errors in a TaskGroup",
                              [ConnectionError("[SSL: CERTIFICATE_VERIFY_FAILED]"),
                               GeneratorExit()])


async def teil1():
    # Positivkontrolle ZUERST: verbindet der Aufbau ueberhaupt?
    gesund = _verbindung("gesund")
    await gesund.connect()
    check("Positivkontrolle: ein gesunder Server wird verbunden",
          gesund.connected is True, "error=%r" % gesund.error)
    check("… und seine Werkzeuge sind da", len(gesund.tools) == 1,
          str(len(gesund.tools)))

    # Der Vorfall: CancelledError aus der TaskGroup des Servers.
    kaputt = _verbindung("kaputt", wirft=asyncio.CancelledError)
    try:
        await kaputt.connect()
        entkommen = None
    except BaseException as e:  # noqa: BLE001
        entkommen = type(e).__name__
    check("eine CancelledError des Servers VERLAESST connect() nicht",
          entkommen is None,
          "entkommen: %s – genau so starb der Lifespan" % entkommen)
    check("… der Server gilt als NICHT verbunden",
          kaputt.connected is False)
    check("… und der Grund steht in error",
          bool(kaputt.error) and "abgebrochen" in (kaputt.error or ""),
          repr(kaputt.error))

    # Dieselbe Lage als Gruppe (so kommt sie beim Aufraeumen).
    gruppe = _verbindung("gruppe", wirft=_gruppe_mit_connect_fehler)
    try:
        await gruppe.connect()
        entkommen2 = None
    except BaseException as e:  # noqa: BLE001
        entkommen2 = type(e).__name__
    check("eine BaseExceptionGroup verlaesst connect() nicht",
          entkommen2 is None, "entkommen: %s" % entkommen2)
    check("… und ihr Inhalt steht im Grund",
          "CERTIFICATE_VERIFY_FAILED" in (gruppe.error or ""),
          repr(gruppe.error))


asyncio.run(teil1())


# ── 4. connect_all(): die anderen Server kommen trotzdem ────────────────────
abschnitt("2. connect_all(): ein kaputter Server stoppt die anderen nicht")


async def teil2(reihenfolge):
    global _server
    _server = [_konf(n) for n in reihenfolge]
    mgr = MC.McpClientManager()

    async def _connect_server(server_id):
        name = server_id.replace("id-", "")
        c = _verbindung(name,
                        wirft=asyncio.CancelledError if name == "kaputt" else None)
        mgr._connections[server_id] = c
        await c.connect()
        return c.connected

    mgr.connect_server = _connect_server
    try:
        await mgr.connect_all()
        entkommen = None
    except BaseException as e:  # noqa: BLE001
        entkommen = type(e).__name__
    # ⚠ KEIN `[...]` IN EINER AUSWERTUNG. Mit Indexzugriff starb dieser
    # Abschnitt an einem KeyError, sobald die Sabotage die CancelledError
    # wieder entkommen liess: der gesunde Server landet dann nie in
    # `_connections`. Der Waechter brach damit VOR der Bilanz ab – und ein
    # Abbruch ist von einem bestandenen Lauf nicht zu unterscheiden, also war
    # die wichtigste Gegenprobe (der Vorfall) nicht als Biss lesbar. `get()`
    # macht daraus ein FAIL (Register).
    verbunden = {n: getattr(mgr._connections.get("id-" + n), "connected", None)
                 for n in reihenfolge}
    return entkommen, verbunden


for _folge in (["kaputt", "gesund"], ["gesund", "kaputt"]):
    _ent, _verb = asyncio.run(teil2(_folge))
    check("Reihenfolge %s: connect_all laeuft durch" % "→".join(_folge),
          _ent is None, "entkommen: %s" % _ent)
    check("Reihenfolge %s: der gesunde Server IST verbunden" % "→".join(_folge),
          _verb.get("gesund") is True, str(_verb))
    check("Reihenfolge %s: der kaputte gilt als nicht verbunden" % "→".join(_folge),
          _verb.get("kaputt") is False, str(_verb))


# ⚠ Der `except Exception`-Zweig in `connect_all` traegt etwas ANDERES als die
# Schranke in `connect()`: einen Fehler aus `connect_server` SELBST, bevor
# `connect()` ueberhaupt laeuft. Der reale Fall ist ein Eintrag OHNE `id`
# (KeyError beim `srv["id"]`) – eine von Hand bearbeitete settings.json. Ohne
# diese Pruefung waere der Zweig ungemessen (die Gegenprobe gegen ihn blieb
# stumm, solange der Waechter `connect_server` ersetzte).
async def teil2b():
    global _server
    _server = [{"name": "ohne_id", "transport": "stdio", "enabled": True},
               _konf("gesund")]
    mgr = MC.McpClientManager()

    async def _connect_server(server_id):
        c = _verbindung(server_id.replace("id-", ""))
        mgr._connections[server_id] = c
        await c.connect()
        return c.connected

    mgr.connect_server = _connect_server
    try:
        await mgr.connect_all()
        entkommen = None
    except BaseException as e:  # noqa: BLE001
        entkommen = "%s: %s" % (type(e).__name__, e)
    # ⚠ DEN ZUSTAND HIER LESEN, IM LAUFENDEN LOOP – nicht nach asyncio.run.
    # Seit dem Besitzer-Task (2026-10-25) haelt jede Verbindung einen Task, der
    # auf ihr Stopp-Signal wartet. `asyncio.run` raeumt beim Beenden alle
    # Tasks ab, der Besitzer setzt dabei voellig korrekt `connected=False` –
    # und eine Pruefung DANACH meldete einen Verbindungsverlust, den es im
    # Dienst (dessen Loop weiterlaeuft) nicht gibt.
    g = mgr._connections.get("id-gesund")
    return entkommen, (None if g is None else g.connected)


_ent2b, _gesund2b = asyncio.run(teil2b())
check("ein Eintrag OHNE id beendet connect_all nicht", _ent2b is None,
      "entkommen: %s" % _ent2b)
check("… und der gesunde Server DANACH wird trotzdem verbunden",
      _gesund2b is True,
      "nicht verbunden" if _gesund2b is None else str(_gesund2b))


# ── 5./6. Gegenkontrolle: ein ECHTER Abbruch muss durch ─────────────────────
abschnitt("3. Gegenkontrolle: der echte Shutdown bricht weiterhin ab")


async def teil3():
    """Ein gecancelter Task MUSS die CancelledError weitergeben.

    ⚠ DER AUFBAU IST DER PUNKT: der Transport muss WARTEN, damit der Cancel ihn
    dort trifft – nur dann zaehlt `Task.cancelling()`, und nur dann ist es der
    Shutdown-Fall. Die erste Fassung liess den Transport die CancelledError
    SELBST werfen (wie im Vorfall) und `cancel()` danach kommen: der Task war
    beim Eintreffen schon im except-Zweig, `cancelling()` stand auf 0, und die
    Pruefung meldete einen Mangel am Fix, den es nicht gab. Ein Messaufbau, der
    den gemeinten Fall nicht herstellt, misst etwas anderes (Register).
    """
    c = MC.McpServerConnection(_konf("shutdown"))
    ergebnis = {}
    im_transport = asyncio.Event()

    async def _wartender_transport():
        im_transport.set()
        await asyncio.sleep(30)        # hier schlaegt der Cancel ein

    c._connect_streamable_http = _wartender_transport

    async def laeuft():
        try:
            await c.connect()
            ergebnis["ende"] = "geschluckt"
        except asyncio.CancelledError:
            ergebnis["ende"] = "durchgelassen"
            raise

    aufgabe = asyncio.create_task(laeuft())
    await im_transport.wait()          # erst warten, DANN cancellen
    aufgabe.cancel()
    try:
        await aufgabe
    except asyncio.CancelledError:
        pass
    # Positivkontrolle des Aufbaus: der Cancel ist wirklich als Cancel
    # angekommen. Ohne sie waere "durchgelassen" auch bei einem Aufbau gruen,
    # der gar nicht cancelt.
    ergebnis["gezaehlt"] = aufgabe.cancelling()
    return ergebnis.get("ende"), ergebnis.get("gezaehlt")


_ende, _gezaehlt = asyncio.run(teil3())
check("Positivkontrolle des Aufbaus: der Cancel kam als Cancel an "
      "(cancelling() > 0)", (_gezaehlt or 0) > 0, "cancelling()=%r" % _gezaehlt)
check("ein gecancelter Task gibt die CancelledError WEITER (Shutdown haengt nicht)",
      _ende == "durchgelassen", "Ergebnis: %r" % _ende)


async def teil4():
    def _harte_gruppe():
        return BaseExceptionGroup("unhandled errors in a TaskGroup",
                                  [SystemExit(3)])
    c = _verbindung("hart", wirft=_harte_gruppe)
    try:
        await c.connect()
        return None
    except BaseException as e:  # noqa: BLE001
        return type(e).__name__


_hart = asyncio.run(teil4())
check("SystemExit in einer Gruppe geht DURCH (ein Abbruch bleibt ein Abbruch)",
      _hart is not None, "geschluckt: %r" % _hart)


# ── 7. startup_mcp in main.py: deckt der Handler BaseException ab? ──────────
abschnitt("4. main.startup_mcp deckt BaseException ab (Syntaxbaum)")
_main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
try:
    _baum = ast.parse(_main)
except SyntaxError as e:
    abbruch("main.py nicht parsebar: %s" % e)

_fn = next((n for n in ast.walk(_baum)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "startup_mcp"),
           None)
if _fn is None:
    abbruch("startup_mcp nicht gefunden – der Waechter kann nichts messen")
check("Positivkontrolle: startup_mcp gefunden", True)

_typen = set()
for _h in (h for n in ast.walk(_fn) if isinstance(n, ast.Try) for h in n.handlers):
    for _t in ([_h.type] if not isinstance(_h.type, ast.Tuple)
               else _h.type.elts):
        if _t is not None:
            _typen.add(ast.unparse(_t))
check("der Handler deckt BaseException ab (CancelledError erbt davon)",
      "BaseException" in _typen, str(sorted(_typen)))
check("… und CancelledError ist eigens benannt (der Shutdown-Fall)",
      any("CancelledError" in t for t in _typen), str(sorted(_typen)))
check("… KeyboardInterrupt/SystemExit gehen ausdruecklich durch",
      any("KeyboardInterrupt" in t for t in _typen), str(sorted(_typen)))
# Und der Dienst darf nicht an einem fehlenden connect_all haengen: die
# Zusage im Docstring ist, dass er OHNE MCP weiterlaeuft.
check("startup_mcp sagt zu, dass der Dienst ohne MCP weiterlaeuft",
      "OHNE MCP" in (ast.get_docstring(_fn) or "")
      or any("OHNE MCP" in ast.unparse(n) for n in ast.walk(_fn)
             if isinstance(n, ast.Constant)))

# ── 5. DIE ECHTE ANYIO-MECHANIK (der Vorfall vom 2026-10-25) ────────────────
abschnitt("5. Echte anyio-Mechanik: level-triggered Cancel-Scope")
# ⚠ WARUM DIESER ABSCHNITT DIE ABSCHNITTE 1-3 NICHT ERSETZT, SONDERN ERGAENZT:
# dort wirft die Attrappe die CancelledError DIREKT. Das hat den ersten Fix
# bestehen lassen (23/0 gruen), waehrend er auf DEV nicht hielt – denn der
# echte Weg ist ein ANDERER: `streamablehttp_client` haelt eine
# anyio-TaskGroup, ihr Scope wird abgebrochen, und anyio-Scopes sind
# LEVEL-TRIGGERED. Solange der Scope offen ist, wird JEDER weitere await im
# Task erneut gecancelt – auch in fremdem Code. Auf DEV starb so der Hook
# `_geheimnis_modulschluessel_verpacken`, mit und ohne `uncancel()`.
# Ein Messaufbau, der die Mechanik des echten Ablaufs nicht herstellt, misst
# den Glueckfall (Register).
#
# Deshalb laeuft hier `_connect_streamable_http` UNGEPATCHT – nachgebaut ist
# nur der Transport, und zwar mit echtem anyio.
try:
    import anyio
    import contextlib as _ctx
except ImportError as e:
    abbruch("anyio fehlt (%s) – ohne es ist Abschnitt 5 nicht messbar" % e)


def _transport_mit_taskgroup(scheitert: bool):
    """Wie `streamablehttp_client`: eine anyio-TaskGroup um die Streams.

    Scheitert ihr Hintergrund-Task, bricht anyio den Scope ab – genau wie bei
    einem selbstsignierten Zertifikat im POST-Task.
    """
    @_ctx.asynccontextmanager
    async def _cm(url="", **_kw):
        async with anyio.create_task_group() as tg:
            async def _post():
                await anyio.sleep(0.02)
                if scheitert:
                    raise ConnectionError("[SSL: CERTIFICATE_VERIFY_FAILED] "
                                          "self-signed certificate")
                await anyio.sleep(3600)
            # Benannt: anyio startet Kinder ueber einen WRAPPER, `_post` steht
            # dann nicht in repr(coro) – die erste Leck-Pruefung fand den Task
            # deshalb nie und blieb in der Gegenprobe stumm.
            tg.start_soon(_post, name="mcp-probe-transport")
            try:
                yield ("read", "write", lambda: None)
            finally:
                tg.cancel_scope.cancel()
    return _cm


class _WartendeSession:
    """Wie `ClientSession`: `initialize()` WARTET auf den Server.

    Das ist der Punkt, an dem der abgebrochene Scope den Task trifft.
    """
    def __init__(self, r, w):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def initialize(self):
        await anyio.sleep(2)

    async def list_tools(self):
        return _ToolsAntwort([_Tool("probe_werkzeug")])


class _SchnelleSession(_WartendeSession):
    async def initialize(self):
        return None


def _mcp_fuer(scheitert: bool, session_cls):
    sys.modules["mcp.client.streamable_http"].streamablehttp_client = \
        _transport_mit_taskgroup(scheitert)
    sys.modules["mcp"].ClientSession = session_cls


async def _naechster_hook():
    """Wie `_geheimnis_modulschluessel_verpacken`: ein to_thread im Lifespan."""
    try:
        await asyncio.to_thread(lambda: 42)
        return "lief"
    except BaseException as e:  # noqa: BLE001
        return "STARB: %s" % type(e).__name__


# (a) POSITIVKONTROLLE DES AUFBAUS: der ALTE Weg (Transport im SELBEN Task
# betreten, Fehler gefangen, Stack offen) MUSS den naechsten Hook sterben
# lassen. Tut er das nicht, stellt dieser Aufbau den Vorfall nicht her, und
# jede Pruefung unten waere trivial gruen – also Exit 2, nicht "bestanden".
async def _alter_weg():
    from contextlib import AsyncExitStack
    _mcp_fuer(True, _WartendeSession)
    stack = AsyncExitStack()
    from mcp import ClientSession as _CS
    from mcp.client.streamable_http import streamablehttp_client as _shc
    try:
        tr = await stack.enter_async_context(_shc(url="https://x.invalid/mcp"))
        s = await stack.enter_async_context(_CS(tr[0], tr[1]))
        await s.initialize()
    except asyncio.CancelledError:
        a = asyncio.current_task()
        while a is not None and a.cancelling() > 0:
            a.uncancel()             # wie der zweite, gescheiterte Fix
    ergebnis = await _naechster_hook()
    # Erst NACH der Messung aufraeumen – und im SELBEN Task. Sonst raeumt
    # `asyncio.run` den offen gelassenen Generator beim Beenden in einem
    # fremden Task ab, und auf stderr stuende ein Traceback, der wie ein Defekt
    # des NEUEN Codes aussieht (genau so gesehen). Die Positivkontrolle soll
    # den alten Fehler herstellen, nicht das Protokoll verschmutzen.
    try:
        await stack.aclose()
    except BaseException:  # noqa: BLE001
        pass
    return ergebnis


_journal5 = ""
_loop_meldungen5 = []
_alt = asyncio.run(_alter_weg())
if not _alt.startswith("STARB"):
    abbruch("der Aufbau stellt den Vorfall NICHT her (alter Weg: %s) – "
          "Abschnitt 5 kann nichts messen" % _alt)
check("Positivkontrolle: der ALTE Weg laesst den naechsten Hook sterben "
      "(auch mit uncancel) – der Aufbau stellt den Vorfall her", True)


# (b) DER ECHTE connect() mit kaputtem Server: der Aufrufer bleibt heil.
async def _neuer_weg_kaputt():
    import io
    import contextlib as _c3
    _mcp_fuer(True, _WartendeSession)
    c = MC.McpServerConnection(_konf("theben"))      # KEIN Patch am Transport
    puffer = io.StringIO()
    try:
        with _c3.redirect_stdout(puffer):
            await c.connect()
        entkommen = None
    except BaseException as e:  # noqa: BLE001
        entkommen = type(e).__name__
    global _journal5
    _journal5 = puffer.getvalue()
    a = asyncio.current_task()
    gezaehlt = a.cancelling() if a else -1
    hook = await _naechster_hook()
    zustand = (c.connected, c.error)
    await c.disconnect()
    return entkommen, gezaehlt, hook, zustand


_ent5, _gez5, _hook5, (_verb5, _err5) = asyncio.run(_neuer_weg_kaputt())
check("ein kaputter Server VERLAESST connect() nicht (echter anyio-Weg)",
      _ent5 is None, "entkommen: %s" % _ent5)
check("der Aufrufer ist danach NICHT gecancelt (cancelling() == 0)",
      _gez5 == 0, "cancelling()=%s" % _gez5)
check("der NAECHSTE Hook laeuft (der eigentliche Vorfall: er starb auf DEV)",
      _hook5 == "lief", _hook5)
check("der Server gilt als nicht verbunden, mit Grund",
      _verb5 is False and bool(_err5), "connected=%s error=%r" % (_verb5, _err5))
# ⚠ Eine Falschmeldung im Normalbetrieb entwertet das Journal: bei JEDEM
# Startversuch eines kaputten Servers stand zuerst "Aufraeumen unvollstaendig",
# obwohl das Aufraeumen vollstaendig war (die TaskGroup meldet nur den schon
# bekannten Transportfehler nach). Der Grund gehoert EINMAL ins Journal.
check("das Journal nennt den Grund – und KEIN falsches 'unvollstaendig'",
      "abgebrochen" in _journal5 and "unvollstaendig" not in _journal5,
      _journal5.strip()[:160])


# (c) connect_all mit [kaputt, gesund] auf dem echten Weg: der gesunde wird
# verbunden, und der Hook danach laeuft.
async def _alle():
    global _server
    _server = [_konf("theben"), dict(_konf("gesund"), transport="stdio")]
    mgr = MC.McpClientManager()

    # Der gesunde Server laeuft ueber stdio – hier nachgebaut als schneller
    # Transport. Der kaputte bleibt auf dem ungepatchten Streamable-Weg.
    async def _gesund_stdio(self_):
        self_._session = _SchnelleSession(None, None)
    MC.McpServerConnection._connect_stdio = _gesund_stdio
    _mcp_fuer(True, _WartendeSession)
    try:
        await mgr.connect_all()
        entkommen = None
    except BaseException as e:  # noqa: BLE001
        entkommen = type(e).__name__
    hook = await _naechster_hook()
    gesund = mgr._connections.get("id-gesund")
    g = None if gesund is None else gesund.connected
    await mgr.disconnect_all()
    return entkommen, hook, g


_ent5c, _hook5c, _g5c = asyncio.run(_alle())
check("connect_all mit kaputtem Server laeuft durch (echter Weg)",
      _ent5c is None, "entkommen: %s" % _ent5c)
check("… der Hook danach laeuft", _hook5c == "lief", _hook5c)
check("… und der gesunde Server IST verbunden", _g5c is True, str(_g5c))


# (d) AUFRAEUMEN IM SELBEN TASK: ein ERFOLGREICH verbundener Server wird von
# einem ANDEREN Task getrennt (wie Request -> Shutdown). Vorher stand dabei
# "Attempted to exit cancel scope in a different task" im Journal; mit dem
# Besitzer schliesst der Task seinen Stack selbst.
async def _trennen_aus_anderem_task():
    # ⚠ DIE ECHTE FOLGE EINES NICHT GESCHLOSSENEN STACKS IST KEIN LAUFENDER
    # TASK, sondern eine Meldung. Ohne `aclose` faellt der Transport-Generator
    # an den asyncgen-Finalizer, und der schliesst ihn in einem FREMDEN Task:
    # "an error occurred during closing of asynchronous generator" samt
    # "Attempted to exit cancel scope in a different task" – woertlich so im
    # Journal von DEV. Die erste Fassung zaehlte nur laufende Tasks; die hatte
    # der Finalizer laengst beseitigt, und die Gegenprobe blieb stumm.
    # Gesammelt wird deshalb, was der Loop an Fehlern meldet.
    loop = asyncio.get_running_loop()
    meldungen = []
    loop.set_exception_handler(lambda _l, ctx: meldungen.append(
        "%s | %s" % (ctx.get("message", ""), ctx.get("exception", ""))))
    _mcp_fuer(False, _SchnelleSession)               # gesunder Transport
    c = MC.McpServerConnection(_konf("gesund2"))
    await c.connect()
    verbunden = c.connected

    def _transport_tasks():
        return [x for x in asyncio.all_tasks()
                if not x.done() and x.get_name() == "mcp-probe-transport"]
    # POSITIVKONTROLLE der Zaehlung: WAEHREND der Server verbunden ist, MUSS
    # sie den laufenden Transport-Task sehen. Ohne sie ist "0 nach dem Trennen"
    # auch dann gruen, wenn die Zaehlung blind ist – genau so gewesen.
    vorher_laufend = len(_transport_tasks())
    import io
    import contextlib as _c2
    puffer = io.StringIO()
    with _c2.redirect_stdout(puffer):
        await asyncio.create_task(c.disconnect())    # ANDERER Task
    import gc
    gc.collect()                    # den Finalizer deterministisch laufen lassen
    await asyncio.sleep(0.05)
    global _loop_meldungen5
    _loop_meldungen5 = list(meldungen)
    # ⚠ "Sauber aufgeraeumt" heisst auch: der Hintergrund-Task des Transports
    # LAEUFT NICHT MEHR. Schliesst niemand den Stack, laeuft er weiter (hier:
    # 3600 s), und JEDER Reconnect liesse einen weiteren liegen – ein Leck,
    # das kein Fehler meldet. Gezaehlt am echten Zustand der Tasks.
    return (verbunden, puffer.getvalue(), c.connected,
            len(_transport_tasks()), vorher_laufend)


_v5d, _aus5d, _nach5d, _rest5d, _vor5d = asyncio.run(_trennen_aus_anderem_task())
check("Positivkontrolle der Zaehlung: waehrend der Verbindung laeuft der "
      "Transport-Task (sie ist nicht blind)", _vor5d >= 1,
      "%d gesehen" % _vor5d)
check("Positivkontrolle: der gesunde Server war verbunden", _v5d is True,
      str(_v5d))
check("Trennen aus einem ANDEREN Task raeumt sauber auf (kein "
      "'Aufraeumen unvollstaendig')",
      "unvollstaendig" not in _aus5d and "different task" not in _aus5d,
      _aus5d.strip()[:120])
check("… und danach gilt der Server als getrennt", _nach5d is False,
      str(_nach5d))
check("… und KEIN Transport-Task laeuft mehr (sonst leckt jeder Reconnect)",
      _rest5d == 0, "%d Transport-Task(s) laufen weiter" % _rest5d)
check("… und der Loop meldet KEIN Schliessen in fremdem Task "
      "(die Zeile aus dem DEV-Journal)",
      not any("asynchronous generator" in m or "different task" in m
              for m in _loop_meldungen5),
      "; ".join(_loop_meldungen5)[:200])

bilanz_und_ende()
