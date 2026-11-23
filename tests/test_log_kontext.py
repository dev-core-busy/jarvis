#!/usr/bin/env python3
"""Waechter: wer und wodurch an JEDER Protokollzeile (backend/log_kontext.py).

VORFALL (ECHT 2026-11-23 11:21): das Fehlerlog zeigte fuer einen abgebrochenen
Chat-Auftrag nur ``agent:Hauptagent`` / ``ReadTimeout`` – kein Benutzer, keine
Adresse, kein Kanal, kein LLM-Server, kein Zeitlimit. Im Journal stand
``EXCEPTION:`` ohne Text. Vorgabe: aus JEDEM Protokoll muss nachvollziehbar
sein, durch was und von wem ein Problem verursacht wurde.

Gemessen wird die WIRKUNG, nicht ein Vorkommen:

1. das Modul selbst (Kontext erben/ergaenzen/zuruecksetzen, stdout-Huelle,
   Logging-Filter, lesbare Ursache, LLM-Vermerk ohne Geheimnisse);
2. der ECHTE ``run_task`` gegen einen echten, STILLEN LLM-Server (echter
   OpenAI-Provider, echte Huelle aus token_verbrauch, echter httpx-ReadTimeout):
   Journal-Zeile und Fehlerlog-Eintrag tragen Wer/IP/Kanal/Chat/Agent und die
   Ursache samt Server und Zeitlimit; danach ist der Kontext wieder zu;
3. der ECHTE ``run_task_headless`` (Cron-Weg): Auftraggeber und Auftragsquelle
   stehen im Eintrag, und der Fehler steht ueberhaupt im Journal (vorher: nichts);
4. die ECHTE ``_AnfragePfadMiddleware`` (aus main.py geschnitten): jede Zeile
   einer HTTP-Anfrage traegt Adresse und Weg, der Benutzer kommt aus
   ``verify_token`` dazu – ohne Query-String;
5. Regeln am Syntaxbaum fuer die Verdrahtung, die ohne die ganze App nicht
   ausfuehrbar ist (``installieren()`` nach ``basicConfig``, ``verify_token``).

``backend.config`` nur als Attrappe (tests/lib/dispatch_pruefstand). Alles, was
ein Lauf schreibt (Fehlerlog, Token-Statistik, LLM-Verlauf, Audit, Chat-
Kontext), wird in einen Sandkasten gelenkt und das per Positivkontrolle belegt.

    venv/bin/python tests/test_log_kontext.py   (Exit 0 gruen, 1 FAIL, 2 konnte nicht laufen)
"""
import ast
import asyncio
import io
import logging
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
sys.path.insert(0, str(HIER))
sys.path.insert(0, str(HIER / "lib"))

OK = FAIL = 0


def pruefe(bed, text, zusatz=""):
    global OK, FAIL
    if bed:
        OK += 1
        print(f"  OK   {text}")
    else:
        FAIL += 1
        print(f"  FAIL {text}" + (f" – {zusatz}" if zusatz else ""))


def abbruch(grund):
    print(f"ABBRUCH: {grund}")
    sys.exit(2)


try:
    import httpx
    from lib import dispatch_pruefstand as P
    from quell_ausschnitt import segment
    A = P.A
    from backend import log_kontext as lk
    from backend import llm, telemetry, conv_log, token_verbrauch as tv, audit_log
    from backend import wirkung
except Exception as e:  # noqa: BLE001
    abbruch(f"Pruefstand nicht ladbar ({type(e).__name__}: {e}) – mit venv/bin/python starten")

if type(sys.modules["backend.config"].config).__name__ != "CfgAttrappe":
    abbruch("backend.config ist nicht die Attrappe – der echte Import schriebe die Live-settings.json")

# ── Sandkasten ───────────────────────────────────────────────────────────────
SAND = Path(tempfile.mkdtemp(prefix="log_kontext_"))
tv._DIR = SAND / "token"
telemetry._ERRORS_FILE = SAND / "telemetry_errors.json"
telemetry._STATS_FILE = SAND / "telemetry_stats.json"
TRACER = telemetry.JarvisTracer()
telemetry.tracer = TRACER          # agent importiert ``tracer`` je Lauf aus dem Modul
conv_log._CONV_DIR = SAND / "conv"
conv_log._INDEX = conv_log._CONV_DIR / "index.jsonl"
conv_log._OLD_FILE = SAND / "conv_log.json"
audit_log.AUDIT_FILE = SAND / "audit.jsonl"
try:
    from backend import chat_sessions as _cs
    _cs.save_context = lambda *a, **k: None
except Exception:  # noqa: BLE001
    pass
for pfad in (tv._DIR, telemetry._ERRORS_FILE, conv_log._CONV_DIR, audit_log.AUDIT_FILE):
    if SAND not in Path(pfad).resolve().parents:
        abbruch(f"Ablage zeigt nicht in den Sandkasten: {pfad}")


def _aufraeumen():
    shutil.rmtree(SAND, ignore_errors=True)


import atexit  # noqa: E402
atexit.register(_aufraeumen)


def mitschreiben(fn):
    """stdout fuer die Dauer von ``fn`` ueber die ECHTE Huelle in einen Puffer."""
    puffer = io.StringIO()
    alt = sys.stdout
    sys.stdout = lk._KontextStrom(puffer)
    try:
        erg = fn()
    finally:
        sys.stdout = alt
    return erg, puffer.getvalue()


# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 1. Das Modul ===")

pruefe(lk.kennzeichen({}) == "", "ohne Kontext keine Kennzeichnung")
with lk.lauf(wer="max.muster", ip="192.0.2.7", kanal="browser"):
    kz = lk.kennzeichen()
    pruefe(kz == "[wer=max.muster ip=192.0.2.7 kanal=browser]", "Kennzeichnung in fester Reihenfolge", kz)
    with lk.lauf(wer="", agent="sub1"):
        kz2 = lk.kennzeichen()
        pruefe("wer=max.muster" in kz2 and "agent=sub1" in kz2,
               "Unter-Lauf mit leerem Wert ERBT den Auftraggeber", kz2)
    pruefe(lk.kennzeichen() == kz, "nach dem Unter-Lauf wieder der aeussere Kontext", lk.kennzeichen())
pruefe(lk._kv.get() is None, "nach dem Lauf ist der Kontext zu")

tok = lk.oeffnen(ip="192.0.2.9", weg="GET /api/x")
lk.ergaenzen(wer="erika.muster")
lk.ergaenzen(wer="fremd.konto")
pruefe(lk.aktuell().get("wer") == "erika.muster",
       "ergaenzen traegt den Benutzer nach – der ERSTE bleibt", str(lk.aktuell()))
lk.schliessen(tok)
lk.ergaenzen(wer="niemand")
pruefe(lk._kv.get() is None, "ergaenzen ausserhalb eines Kontexts legt keinen an")
with lk.lauf(wer="a b\nc[d]"):
    pruefe(lk.aktuell()["wer"] == "a_b_c(d)", "Werte ohne Leerraum und eckige Klammern (greppbar)",
           lk.aktuell()["wer"])

# stdout-Huelle
def _drucke():
    print("vorher")
    with lk.lauf(wer="max.muster", kanal="browser"):
        print("[AGENT x] drin")
        print("kopf\nfolgezeile")
    print("nachher")
_, aus = mitschreiben(_drucke)
z = aus.splitlines()
pruefe(len(z) == 5, "(Positivkontrolle) alle Zeilen kamen an", repr(aus))
if len(z) == 5:
    pruefe(z[0] == "vorher" and z[4] == "nachher", "ausserhalb eines Kontexts unveraendert", repr(z))
    pruefe(z[1] == "[wer=max.muster kanal=browser] [AGENT x] drin", "print-Zeile im Kontext traegt die Herkunft", z[1])
    pruefe(z[2].startswith("[wer=max.muster") and z[3] == "folgezeile",
           "mehrzeilige Ausgabe: erste Zeile gekennzeichnet, Folgezeilen nicht", repr(z[2:4]))

# Logging: ueber das ECHTE installieren() – wie main.py es tut (Wurzel-Handler
# nach basicConfig). Wurzel und stdout danach wiederherstellen.
wurzel = logging.getLogger()
alt_handler, alt_level, alt_stdout = wurzel.handlers[:], wurzel.level, sys.stdout
strom = io.StringIO()
h = logging.StreamHandler(strom)
wurzel.handlers[:] = [h]
wurzel.setLevel(logging.INFO)
try:
    lk.installieren()
    pruefe(getattr(sys.stdout, "_jarvis_kontext_strom", False), "installieren() umhuellt stdout")
    sys.stdout = alt_stdout
    lg = logging.getLogger("lk_probe")
    lg.info("ohne")
    with lk.lauf(wer="max.muster", weg="POST /api/y"):
        lg.info("mit")
    zeilen = strom.getvalue().splitlines()
    pruefe(zeilen == ["[INFO] lk_probe: ohne", "[INFO] lk_probe: [wer=max.muster weg=POST_/api/y] mit"],
           "Logger-Zeile: Herkunft im Kontext, sonst unveraendert", repr(zeilen))
    try:
        h.format(logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None))
        pruefe(True, "Format ohne Filterlauf wirft nicht (defaults)")
    except Exception as e:  # noqa: BLE001
        pruefe(False, "Format ohne Filterlauf wirft nicht (defaults)", repr(e))
finally:
    sys.stdout = alt_stdout
    wurzel.handlers[:] = alt_handler
    wurzel.setLevel(alt_level)

# Weg aus dem ASGI-Scope
pruefe(lk.weg_aus_scope({"type": "http", "method": "GET", "path": "/api/x", "query_string": b"token=GEHEIM"})
       == "GET /api/x", "Weg ohne Query-String")
pruefe(lk.weg_aus_scope({"type": "websocket", "path": "/ws"}) == "WS /ws", "WebSocket als WS")

# Ursache
ft = lk.fehlertext(httpx.ReadTimeout(""))
pruefe(ft and ft != "ReadTimeout" and "Zeitlimit" in ft, "ReadTimeout ohne Text bekommt eine lesbare Ursache", ft)
pruefe(lk.fehlertext(ValueError("kaputt")) == "kaputt", "eigene Meldung bleibt woertlich")
try:
    try:
        raise OSError("Verbindung abgerissen")
    except OSError as inner:
        raise RuntimeError() from inner
except RuntimeError as e:
    pruefe(lk.fehlertext(e) == "Verbindung abgerissen", "leere Meldung: die der Ursache", lk.fehlertext(e))


class _P:
    anbieter_kennung = "probe"
    base_url = "https://nutzer:GEHEIMWORT@llm.beispiel.de:8443/v1/chat/completions?key=GEHEIMKEY"

    def _get_timeout(self):
        return httpx.Timeout(42.0)


e = httpx.ReadTimeout("")
lk.llm_aufruf_vermerken(e, _P(), "modell-x", 41.96)
lk.llm_aufruf_vermerken(e, _P(), "modell-x", 41.96)
noten = getattr(e, "__notes__", [])
pruefe(len(noten) == 1, "LLM-Vermerk genau einmal je Ausnahme", str(noten))
n = noten[0] if noten else ""
for teil in ("Anbieter probe", "Server llm.beispiel.de:8443", "Modell modell-x", "42.0 s", "Lese-Zeitlimit 42 s"):
    pruefe(teil in n, f"LLM-Vermerk nennt '{teil}'", n)
pruefe("GEHEIM" not in n and "nutzer" not in n, "LLM-Vermerk ohne Benutzer, Kennwort und Query", n)
pruefe("Server llm.beispiel.de:8443" in lk.fehlertext(e), "fehlertext haengt den Vermerk an", lk.fehlertext(e))
c = asyncio.CancelledError()
lk.llm_aufruf_vermerken(c, _P(), "m", 1.0)
pruefe(not getattr(c, "__notes__", None), "ein Stopp (CancelledError) wird nicht als Stoerung vermerkt")

# Telemetrie: Kontext beim START
with lk.lauf(wer="max.muster", kanal="whatsapp"):
    sp = TRACER.start_span("probe", kind="tool")
TRACER.end_span(sp, status="error", error="x")
pruefe(sp.to_dict().get("kontext", {}).get("wer") == "max.muster",
       "Span traegt den Kontext seines Starts (auch wenn er ausserhalb endet)", str(sp.to_dict().get("kontext")))
gespeichert = TRACER.get_errors()
pruefe(bool(gespeichert) and gespeichert[0].get("kontext", {}).get("kanal") == "whatsapp",
       "persistierter Fehlerlog-Eintrag traegt den Kontext", str(gespeichert[:1])[:300])
TRACER.clear_errors("waechter")


# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 2. Echter run_task gegen einen stillen LLM-Server ===")


class StillerServer:
    """Nimmt Verbindungen an und antwortet NIE – ein echter ReadTimeout."""

    def __init__(self):
        self.s = socket.socket()
        self.s.bind(("127.0.0.1", 0))
        self.s.listen(8)
        self.port = self.s.getsockname()[1]
        self.verbindungen = []
        threading.Thread(target=self._annehmen, daemon=True).start()

    def _annehmen(self):
        while True:
            try:
                c, _ = self.s.accept()
                self.verbindungen.append(c)
            except OSError:
                return


SERVER = StillerServer()
PROV = llm.OpenAICompatibleProvider(api_key="", base_url=f"http://127.0.0.1:{SERVER.port}/v1")
PROV._get_timeout = lambda: httpx.Timeout(1.0)
pruefe(getattr(type(PROV).generate_response, "__token_erfassung__", False),
       "(Positivkontrolle) der echte Provider traegt die echte Huelle aus token_verbrauch")
A.get_provider = lambda *a, **k: PROV
A.JarvisAgent.LLM_PROVIDER = property(lambda self: "openai_compatible")
try:
    AG = A.JarvisAgent()
except Exception as e:  # noqa: BLE001
    abbruch(f"JarvisAgent nicht baubar ({type(e).__name__}: {e})")
AG.provider = PROV


class WS:
    def __init__(self):
        self.n = []

    async def send_json(self, m):
        self.n.append(m)


async def _chat():
    t0 = time.monotonic()
    erg = await AG.run_task("Testfrage", WS(), client_type="browser", client_ip="192.0.2.7",
                            username="max.muster", session_id="chat42")
    return erg, time.monotonic() - t0, lk._kv.get()

(ergebnis, dauer, kv_danach), journal = mitschreiben(lambda: asyncio.run(_chat()))
pruefe(len(SERVER.verbindungen) >= 1 and dauer >= 1.0,
       "(Positivkontrolle) der LLM-Aufruf ging wirklich an den stillen Server und lief ins Zeitlimit",
       f"{len(SERVER.verbindungen)} Verbindungen, {dauer:.2f} s")
pruefe(ergebnis == "error", "Lauf endet als Fehler", str(ergebnis))
pruefe(kv_danach is None, "nach run_task ist der Kontext wieder zu (kein Leck in den WebSocket-Task)", str(kv_danach))
ex = [z for z in journal.splitlines() if "EXCEPTION" in z]
pruefe(len(ex) == 1, "(Positivkontrolle) genau eine EXCEPTION-Zeile im Journal", str(ex))
if ex:
    for teil in ("wer=max.muster", "ip=192.0.2.7", "kanal=browser", "chat=chat42", f"agent={AG.agent_id}"):
        pruefe(teil in ex[0], f"Journal-Zeile nennt {teil}", ex[0][:300])
    pruefe("EXCEPTION ReadTimeout:" in ex[0] and f"Server 127.0.0.1:{SERVER.port}" in ex[0]
           and "Lese-Zeitlimit 1 s" in ex[0],
           "Journal-Zeile nennt Typ, Server und Zeitlimit", ex[0][:300])
gestartet = [z for z in journal.splitlines() if "run_task gestartet" in z]
pruefe(bool(gestartet) and gestartet[0].startswith("[wer=max.muster"),
       "schon die Startzeile traegt die Herkunft", str(gestartet[:1]))
fehler = TRACER.get_errors()
haupt = [f for f in fehler if f.get("kind") == "agent"]
pruefe(len(haupt) == 1, "(Positivkontrolle) genau ein Agent-Fehler im Fehlerlog", str(len(haupt)))
if haupt:
    k = haupt[0].get("kontext") or {}
    pruefe(k.get("wer") == "max.muster" and k.get("ip") == "192.0.2.7" and k.get("kanal") == "browser"
           and k.get("chat") == "chat42" and k.get("agent") == AG.agent_id,
           "Fehlerlog-Eintrag: wer/ip/kanal/chat/agent", str(k))
    err = haupt[0].get("error") or ""
    pruefe("Zeitlimit" in err and f"Server 127.0.0.1:{SERVER.port}" in err and "Anbieter openai_compatible" in err,
           "Fehlerlog-Eintrag: lesbare Ursache samt Anbieter und Server (nicht nur 'ReadTimeout')", err)
TRACER.clear_errors("waechter")


# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 3. Echter Lauf ohne Oberflaeche (Cron-Weg) ===")


async def _cron():
    with wirkung.auftrag("cron:probe42", False):
        return await AG.run_task_headless("Cron-Probe", actor={"user": "erika.muster", "privileged": False})

vor = len(SERVER.verbindungen)
(hl_erg, journal_hl) = mitschreiben(lambda: asyncio.run(_cron()))
pruefe(len(SERVER.verbindungen) > vor, "(Positivkontrolle) auch der Cron-Lauf rief den stillen Server",
       f"{vor} -> {len(SERVER.verbindungen)}")
ex = [z for z in journal_hl.splitlines() if "EXCEPTION" in z]
pruefe(len(ex) == 1, "der Fehler steht ueberhaupt im Journal (vorher: keine Zeile)", journal_hl[-400:])
if ex:
    pruefe("wer=erika.muster" in ex[0] and "auftrag=cron:probe42" in ex[0],
           "Journal-Zeile nennt Auftraggeber und Auftragsquelle", ex[0][:300])
fehler = [f for f in TRACER.get_errors() if f.get("kind") == "agent"]
pruefe(len(fehler) == 1, "(Positivkontrolle) genau ein Agent-Fehler im Fehlerlog", str(len(fehler)))
if fehler:
    k = fehler[0].get("kontext") or {}
    pruefe(k.get("wer") == "erika.muster" and k.get("auftrag") == "cron:probe42",
           "Fehlerlog-Eintrag des Cron-Laufs: wer und auftrag", str(k))
    pruefe("Zeitlimit" in (fehler[0].get("error") or "") and fehler[0].get("attributes", {}).get("error.traceback"),
           "Fehlerlog-Eintrag des Cron-Laufs: Ursache und Traceback", str(fehler[0].get("error")))
pruefe("Zeitlimit" in str(hl_erg), "Ergebnistext des Cron-Laufs nennt die Ursache", str(hl_erg)[:200])
TRACER.clear_errors("waechter")


# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 4. Echte Anfrage-Middleware (aus main.py geschnitten) ===")

MAIN_QUELLE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
MAIN_BAUM = ast.parse(MAIN_QUELLE)
klasse = next((n for n in MAIN_BAUM.body if isinstance(n, ast.ClassDef) and n.name == "_AnfragePfadMiddleware"), None)
if klasse is None:
    abbruch("_AnfragePfadMiddleware nicht in main.py")
import contextvars  # noqa: E402
_sitzung_attrappe = type("S", (), {"ANFRAGE_PFAD": contextvars.ContextVar("pfad", default=None)})
ns = {"_sitzung": _sitzung_attrappe, "_log_kontext": lk}
exec(compile(segment(MAIN_QUELLE, klasse), "main.py:_AnfragePfadMiddleware", "exec"), ns)
Mw = ns["_AnfragePfadMiddleware"]


async def _anfrage(scope):
    gesehen = {}

    async def innen(scope_, receive, send):
        gesehen["vorher"] = lk.kennzeichen()
        lk.ergaenzen(wer="max.muster")          # das tut verify_token
        print("[AUTH] Probezeile")
        gesehen["nachher"] = lk.kennzeichen()
    await Mw(innen)(scope, None, None)
    gesehen["draussen"] = lk._kv.get()
    return gesehen

scope = {"type": "http", "method": "POST", "path": "/api/chat/x", "query_string": b"token=GEHEIM",
         "client": ("192.0.2.33", 5555)}
g, aus = mitschreiben(lambda: asyncio.run(_anfrage(scope)))
pruefe(g.get("vorher") == "[ip=192.0.2.33 weg=POST_/api/chat/x]", "Middleware setzt Adresse und Weg", str(g.get("vorher")))
pruefe("wer=max.muster" in (g.get("nachher") or ""), "verify_token-Nachtrag wirkt in der Anfrage", str(g.get("nachher")))
pruefe(aus.startswith("[wer=max.muster ip=192.0.2.33 weg=POST_/api/chat/x] [AUTH] Probezeile"),
       "Journal-Zeile einer Anfrage traegt wer/ip/weg", aus.strip())
pruefe("GEHEIM" not in aus, "kein Query-String im Journal")
pruefe(g.get("draussen") is None, "nach der Anfrage ist der Kontext zu")
g, _ = mitschreiben(lambda: asyncio.run(_anfrage({"type": "websocket", "path": "/ws", "client": ("192.0.2.34", 1)})))
pruefe("weg=WS_/ws" in (g.get("vorher") or ""), "auch WebSocket-Verbindungen bekommen einen Kontext", str(g.get("vorher")))


async def _anfrage_wirft():
    async def innen(scope_, receive, send):
        lk.ergaenzen(wer="max.muster")
        raise KeyError("feld_fehlt")
    try:
        await Mw(innen)({"type": "http", "method": "GET", "path": "/api/kaputt",
                         "client": ("192.0.2.35", 1)}, None, None)
    except KeyError:
        return "weitergereicht"
    return "verschluckt"

g, aus = mitschreiben(lambda: asyncio.run(_anfrage_wirft()))
pruefe(g == "weitergereicht", "unbehandelter Fehler wird weitergereicht (uvicorn antwortet 500)", str(g))
pruefe(aus.startswith("[wer=max.muster ip=192.0.2.35 weg=GET_/api/kaputt] [HTTP] Unbehandelter Fehler KeyError:")
       and "feld_fehlt" in aus, "unbehandelter Fehler: gekennzeichnete Zeile mit Ursache", aus.strip()[:300])


# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 5. Regeln am Syntaxbaum (Verdrahtung in main.py) ===")


def _ist_aufruf(n, objekt, attr):
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr
            and isinstance(n.func.value, ast.Name) and n.func.value.id == objekt)


zeile_basic = min((n.lineno for n in MAIN_BAUM.body if isinstance(n, ast.Expr)
                   and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                   and n.value.func.attr == "basicConfig"), default=None)
zeile_inst = min((n.lineno for n in MAIN_BAUM.body if isinstance(n, ast.Expr)
                  and _ist_aufruf(n.value, "_log_kontext", "installieren")), default=None)
pruefe(zeile_basic is not None, "(Positivkontrolle) logging.basicConfig auf Modulebene gefunden")
pruefe(zeile_inst is not None and zeile_basic is not None and zeile_inst > zeile_basic,
       "main.py ruft _log_kontext.installieren() auf Modulebene NACH basicConfig",
       f"basicConfig {zeile_basic}, installieren {zeile_inst}")
vt = next((n for n in MAIN_BAUM.body if isinstance(n, ast.FunctionDef) and n.name == "verify_token"), None)
pruefe(vt is not None, "(Positivkontrolle) verify_token gefunden")
if vt is not None:
    # Der Nachtrag muss im ERFOLGSZWEIG stehen: im selben Block wie ``return username``.
    treffer = False
    for blk in ast.walk(vt):
        koerper = getattr(blk, "body", None)
        if not isinstance(koerper, list):
            continue
        hat_return = any(isinstance(s, ast.Return) and isinstance(s.value, ast.Name)
                         and s.value.id == "username" for s in koerper)
        hat_ergaenzen = any(isinstance(s, ast.Expr) and _ist_aufruf(s.value, "_log_kontext", "ergaenzen")
                            and any(kw.arg == "wer" for kw in s.value.keywords) for s in koerper)
        treffer = treffer or (hat_return and hat_ergaenzen)
    pruefe(treffer, "verify_token traegt den Benutzer im Erfolgszweig nach (vor 'return username')")


print(f"\n{OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
