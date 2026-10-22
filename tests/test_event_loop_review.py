#!/usr/bin/env python3
"""Waechter: /api/stt und das Sammel-Loeschen halten den Event-Loop nicht an
(Code-Review 2026-10-07).

Befund: ``stt_transcribe`` rief ``_get_whisper_model()`` direkt im Event-Loop –
die Funktion wartet auf eine threading.Lock, die das Vorladen beim Start
Sekunden bis Minuten haelt, und laedt selbst nach, wenn das Vorladen scheiterte.
``chat_sessions_delete_many`` loeschte bis zu 200 Ordner (rmtree) im Loop. In
beiden Faellen stand der Dienst fuer ALLE Benutzer.

Gemessen an der WIRKUNG: die echten Endpunkte (per AST aus main.py geschnitten)
laufen mit Attrappen, die langsam sind (time.sleep, wie die echte Sperre).
Daneben tickt eine Aufgabe im selben Loop alle 10 ms. Steht der Loop, tickt sie
nicht. Positivkontrolle: dieselbe Messung an einer Funktion, die im Loop
schlaeft, MUSS den Stillstand sehen – sonst misst die Uhr nichts.

    python3 tests/test_event_loop_review.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "backend" / "main.py"
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


def abbruch(grund):
    print("\n\033[31mABBRUCH\033[0m: %s" % grund)
    sys.exit(2)


try:
    BAUM = ast.parse(MAIN.read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    abbruch("main.py nicht lesbar: %s" % e)
FN = {n.name: n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def schneide(name, ns):
    if name not in FN:
        abbruch("main.py: %s fehlt" % name)
    k = ast.parse(ast.unparse(FN[name])).body[0]
    k.decorator_list = []
    for a in k.args.args + k.args.kwonlyargs:
        a.annotation = None
    k.args.defaults = [ast.Constant(None) for _ in k.args.defaults]
    k.args.kw_defaults = [ast.Constant(None) for _ in k.args.kw_defaults]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[k], type_ignores=[])),
                 "<main:%s>" % name, "exec"), ns)
    return ns[name]


class Antwort:
    def __init__(self, content, status_code=200, headers=None):
        self.content, self.status_code = content, status_code


class Anfrage:
    def __init__(self, body=b"", json_body=None, query=None, headers=None, stuecke=None):
        self._b, self._j = body, json_body
        self.query_params = query or {}
        self.headers = headers or {}
        self._stuecke = stuecke
        self.gelesen = 0

    async def body(self):
        return self._b

    async def stream(self):
        # wie Starlette: der Rumpf kommt in Stuecken
        for st in (self._stuecke if self._stuecke is not None else [self._b]):
            self.gelesen += len(st)
            yield st

    async def json(self):
        return self._j


async def gemessen(coro_fabrik):
    """Laeuft ``coro_fabrik()`` und zaehlt die Ticks eines 10-ms-Weckers.
    Rueckgabe (Ergebnis, Dauer_s, Ticks)."""
    ticks = 0
    halt = False

    async def wecker():
        nonlocal ticks
        while not halt:
            await asyncio.sleep(0.01)
            ticks += 1

    w = asyncio.ensure_future(wecker())
    await asyncio.sleep(0.02)
    t0, n0 = time.monotonic(), ticks
    erg = await coro_fabrik()
    dauer = time.monotonic() - t0
    halt = True
    await w
    return erg, dauer, ticks - n0


def lief_weiter(dauer, ticks):
    # erwartet ~dauer/0.01 Ticks; die Haelfte reicht als Beweis, dass der Loop lief
    return ticks >= max(5, int(dauer / 0.01 * 0.5))


LOOP = asyncio.new_event_loop()

# ── Positivkontrolle der Uhr ────────────────────────────────────────────────
print("\n\033[1mPositivkontrolle\033[0m")


async def blockiert():
    time.sleep(0.4)
    return None

_, d, t = LOOP.run_until_complete(gemessen(blockiert))
check("ein time.sleep im Loop wird als Stillstand erkannt (%d Ticks in %.2f s)" % (t, d),
      not lief_weiter(d, t))
if fail:
    abbruch("die Uhr sieht keinen Stillstand – jede Aussage darunter waere wertlos")

# ── /api/stt ────────────────────────────────────────────────────────────────
print("\n\033[1m/api/stt: Modell laden blockiert den Loop nicht\033[0m")
rufe = []


def _langsam_modell(source="chat"):
    rufe.append(source)
    time.sleep(0.4)          # wie die vom Vorladen gehaltene threading.Lock
    return None              # Vorladen gescheitert -> 503


ns = {"JSONResponse": Antwort, "Request": Anfrage, "Depends": lambda x: None,
      "require_auth": None, "asyncio": asyncio, "_STT_MAX_BYTES": 10 ** 6,
      "_get_whisper_model": _langsam_modell, "_STT_ENDUNGEN": {}, "os": __import__("os"),
      "_stt_quelle_fern": lambda: False}
schneide("_rumpf_mit_deckel", ns)
stt = schneide("stt_transcribe", ns)
r, d, t = LOOP.run_until_complete(gemessen(lambda: stt(Anfrage(body=b"abc"), user="anna")))
check("Positivkontrolle: das langsame Modell wurde gefragt", rufe == ["voice_browser"], rufe)
check("… Antwort 503 (nicht eingerichtet)", getattr(r, "status_code", None) == 503,
      getattr(r, "status_code", r))
check("⚠ der Loop lief waehrenddessen weiter (%d Ticks in %.2f s)" % (t, d), lief_weiter(d, t))

# ── /api/stt: Groesse vor dem Lesen, gleichzeitige Transkriptionen ──────────
print("\n\033[1m/api/stt: Groessendeckel und Gleichzeitigkeit (NIEDRIG)\033[0m")
rufe.clear()
MB = 10 ** 6
a1 = Anfrage(headers={"content-length": str(50 * MB)}, stuecke=[b"x" * MB] * 50)
r = LOOP.run_until_complete(stt(a1, user="anna"))
q = r if isinstance(r, Antwort) else None
check("⚠ angekuendigte 50 MB bei 1 MB Deckel -> 413, OHNE ein Byte zu lesen (%d gelesen)" % a1.gelesen,
      getattr(q, "status_code", None) == 413 and a1.gelesen == 0,
      (getattr(q, "status_code", r), a1.gelesen))
a2 = Anfrage(stuecke=[b"x" * (256 * 1024)] * 200)          # 50 MB ohne Ankuendigung
r = LOOP.run_until_complete(stt(a2, user="anna"))
check("⚠ ohne Ankuendigung: 413, und das Lesen bricht an der Grenze ab (%d Bytes gelesen)"
      % a2.gelesen, getattr(r, "status_code", None) == 413 and a2.gelesen <= MB + 256 * 1024,
      (getattr(r, "status_code", r), a2.gelesen))
check("… das Modell wird dafuer gar nicht erst gefragt", rufe == [], rufe)
import threading as _th  # noqa: E402
gleichzeitig = {"jetzt": 0, "max": 0}
_sperre = _th.Lock()


def _transkription(pfad, sprache, prompt, quelle):
    with _sperre:
        gleichzeitig["jetzt"] += 1
        gleichzeitig["max"] = max(gleichzeitig["max"], gleichzeitig["jetzt"])
    time.sleep(0.15)
    with _sperre:
        gleichzeitig["jetzt"] -= 1
    return "hallo"


ns["_get_whisper_model"] = lambda source="chat": object()
ns["_transcribe_audio"] = _transkription
ns["_STT_GLEICHZEITIG"] = 2


async def _sechs():
    ns["_stt_sem"] = asyncio.Semaphore(ns["_STT_GLEICHZEITIG"])
    return await asyncio.gather(*[stt(Anfrage(body=b"abc"), user="u%d" % i) for i in range(6)])


ergebnisse = LOOP.run_until_complete(_sechs())
check("Positivkontrolle: alle sechs Aufnahmen transkribiert",
      all(getattr(e, "content", {}).get("text") == "hallo" for e in ergebnisse),
      [getattr(e, "content", e) for e in ergebnisse])
check("⚠ nie mehr als 2 Transkriptionen gleichzeitig (max %d)" % gleichzeitig["max"],
      gleichzeitig["max"] == 2, gleichzeitig)

# ── Sammel-Loeschen ─────────────────────────────────────────────────────────
print("\n\033[1mSammel-Loeschen: rmtree blockiert den Loop nicht\033[0m")
geloescht = []


def _langsam_loeschen(user, sid):
    time.sleep(0.004)
    geloescht.append(sid)
    return sid != "kaputt"


cs = types.ModuleType("backend.chat_sessions")
cs.delete_session = _langsam_loeschen
sys.modules["backend.chat_sessions"] = cs
pkg = sys.modules.setdefault("backend", types.ModuleType("backend"))
pkg.chat_sessions = cs
vergessen = []
ns = {"JSONResponse": Antwort, "Request": Anfrage, "Depends": lambda x: None,
      "require_auth": None, "asyncio": asyncio, "_CHAT_DELETE_MAX": 200,
      "_chat_kontext_vergessen": lambda u, s: vergessen.append(s)}
dm = schneide("chat_sessions_delete_many", ns)
ids = ["s%03d" % i for i in range(99)] + ["kaputt"]
r, d, t = LOOP.run_until_complete(gemessen(lambda: dm(Anfrage(json_body={"ids": ids}), user="anna")))
check("Positivkontrolle: alle 100 Loeschungen liefen", len(geloescht) == 100, len(geloescht))
c = getattr(r, "content", {}) or {}
check("… Ergebnis benennt Erfolg und Fehlschlag",
      len(c.get("deleted", [])) == 99 and c.get("failed") == ["kaputt"] and c.get("ok") is False, c)
check("… Kontext nur fuer die geloeschten vergessen", len(vergessen) == 99 and "kaputt" not in vergessen)
check("⚠ der Loop lief waehrenddessen weiter (%d Ticks in %.2f s)" % (t, d), lief_weiter(d, t))

# ── AD-Verbindungstest ──────────────────────────────────────────────────────
print("\n\033[1mAD testen: blockiert nicht, schliesst die Verbindung (NIEDRIG)\033[0m")
offen = []


class _Server:                     # Signatur wie ldap3.Server(host, get_info=, connect_timeout=)
    def __init__(self, host, get_info=None, connect_timeout=None):
        self.host = host


class _Conn:                       # wie ldap3.Connection(server, auto_bind=)
    def __init__(self, server, auto_bind=False):
        self.closed = True

    def open(self):
        time.sleep(0.4)            # Verbindungsaufbau zum DC
        self.closed = False
        offen.append(self)

    def unbind(self):
        self.closed = True
        return True


_ldap3 = types.ModuleType("ldap3")
_ldap3.Server, _ldap3.Connection, _ldap3.NONE = _Server, _Conn, "NONE"
sys.modules["ldap3"] = _ldap3
_lt = types.ModuleType("backend.ldap_tls")
_lt.verbinden = lambda host, timeout=5, info=None: object()
_lt._schliessen = lambda c: None
_lt.uebergang = lambda: False
sys.modules["backend.ldap_tls"] = _lt
pkg.ldap_tls = _lt
# Der Verbindungstest liegt seit 2026-10-21 in backend/ldap_directory.py
# (erreichbar()). Geladen wird das ECHTE Modul – sonst misst die Pruefung
# "Verbindung geschlossen" eine Attrappe. backend.config nur als Attrappe: der
# echte Import schriebe die Live-settings.json zurueck.
import importlib.util  # noqa: E402
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(get_setting=lambda k, d=None: d)
sys.modules["backend.config"] = _cfg
pkg.config = _cfg
_spec = importlib.util.spec_from_file_location("backend.ldap_directory", ROOT / "backend" / "ldap_directory.py")
_ldd = importlib.util.module_from_spec(_spec)
sys.modules["backend.ldap_directory"] = _ldd
_spec.loader.exec_module(_ldd)
pkg.ldap_directory = _ldd
ns = {"JSONResponse": Antwort, "Request": Anfrage, "Depends": lambda x: None,
      "require_local_auth": None, "asyncio": asyncio}
ad = schneide("test_ad_connection", ns)
r, d, t = LOOP.run_until_complete(gemessen(
    lambda: ad(Anfrage(json_body={"ad_server": "dc.firma.local", "ad_domain": "firma.local"}),
               _username="chef")))
check("Positivkontrolle: erreichbar gemeldet", getattr(r, "content", {}).get("reachable") is True,
      getattr(r, "content", r))
check("⚠ der Loop lief waehrend des Verbindungsaufbaus weiter (%d Ticks in %.2f s)" % (t, d),
      lief_weiter(d, t))
check("⚠ die Verbindung ist danach geschlossen", len(offen) == 1 and offen[0].closed,
      [c.closed for c in offen])

LOOP.close()
print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
