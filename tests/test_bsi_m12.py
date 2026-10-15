#!/usr/bin/env python3
"""Waechter BSI M12 – keine feste Abschaltung der Zertifikatspruefung.

  [A] REGEL ueber backend/** und skills/** (AST): kein ``verify=False`` als
      Konstante, kein ``ssl._create_unverified_context``; jedes ``CERT_NONE``
      steht entweder unter einer Bedingung, die eine Pruef-Einstellung liest
      (Name enthaelt verify/pruef/tls), oder in einer benannten Funktion, die
      nur ein Zertifikat ABHOLT. Dazu Node-Quellen: kein
      ``rejectUnauthorized: false`` / ``NODE_TLS_REJECT_UNAUTHORIZED``.
      Positivkontrolle: die Regel erkennt die alten Fassungen (Webhook fest
      ``verify=False``, Kamera ``CERT_NONE`` nur unter ``startswith("https")``).
  [B] Trigger-Webhook (``file_watcher._do_webhook``, echter Code, httpx-Attrappe):
      Vorgabe prueft, nur ``tls_pruefen=False`` schaltet ab – und JEDER solche
      Aufruf landet im Sicherheitsprotokoll. Feld in add/update, Typpruefung.
  [C] Endpunkte: POST /api/watchers gibt nur bei echtem ``false`` ab
      (Rumpf per AST ausgefuehrt).
  [D] Kamera-Stream (``MjpegStreamReader``): Vorgabe CERT_REQUIRED, nur ein
      ausdrueckliches false aus der Skill-Einstellung schaltet ab; unlesbare
      Einstellung = Pruefung an.
  [E] Standort-Sync: ohne gebundenes Zertifikat KEIN Nutzdaten-Kontext; der
      Verbindungstest bindet das eben ermittelte Zertifikat.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import os
import re
import ssl
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

# watchdog fehlt in manchen Umgebungen (lokale venv). file_watcher braucht es
# nur fuer den Observer, den dieser Waechter nicht startet -> Attrappe mit den
# importierten Namen, NUR wenn das echte Paket fehlt.
try:
    import watchdog  # noqa: F401
except ImportError:
    _wd, _wde, _wdo = (types.ModuleType(n) for n in ("watchdog", "watchdog.events", "watchdog.observers"))
    for _n in ("FileSystemEventHandler", "FileCreatedEvent", "FileModifiedEvent",
               "FileDeletedEvent", "FileMovedEvent"):
        setattr(_wde, _n, type(_n, (), {}))
    _wdo.Observer = type("Observer", (), {})
    sys.modules.update({"watchdog": _wd, "watchdog.events": _wde, "watchdog.observers": _wdo})

OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(info)[:300] + "]") if info else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


TMP = Path(tempfile.mkdtemp(prefix="bsi_m12_"))

# ── Sandkasten: backend.config NICHT echt importieren ─────────────────────────
_cfg = types.ModuleType("backend.config")


class _C:
    SECRET_KEY = "testgeheimnis-bsi-m12"
    skill_states: dict = {}

    def get_setting(self, k, d=None):
        return d

    def get_skill_states(self):
        if isinstance(self.skill_states, Exception):
            raise self.skill_states
        return self.skill_states


_cfg.config = _C()
sys.modules["backend.config"] = _cfg

# Sicherheitsprotokoll als Attrappe mit echter Signatur: ereignis(art, *, benutzer, ip, ergebnis, **details)
_sl = types.ModuleType("backend.sicherheits_log")
_sl.EREIGNISSE = []


def _ereignis(art, *, benutzer="", ip="", ergebnis="", **details):
    e = {"art": art, "benutzer": benutzer, "ip": ip, "ergebnis": ergebnis, "details": details}
    _sl.EREIGNISSE.append(e)
    return e


_sl.ereignis = _ereignis
sys.modules["backend.sicherheits_log"] = _sl
import backend  # noqa: E402
backend.sicherheits_log = _sl

# ═════════════════════════════════════════════════════════════════════════════
print("\n[A] Regel: keine feste Abschaltung der Zertifikatspruefung")

# Funktionen, die NUR ein Zertifikat abholen (kein Token, kein Inhalt).
ABHOLER = {
    ("backend/sap_cert.py", "pruefen"): "holt das Zertifikat zur Anzeige/Bindung",
    ("backend/knowledge_sync.py", "_ermittlungs_kontext"): "nur fuer zertifikat_abfragen",
    ("backend/mail_tls.py", "pruefen"): "holt das Mailserver-Zertifikat zur Anzeige/Bindung",
}
PRUEF_WORT = re.compile(r"verify|pruef|tls", re.I)


def _namen(knoten):
    """Bezeichner (Name/Attribut) in einem Ausdruck – ohne Zeichenketten."""
    out = []
    for n in ast.walk(knoten):
        if isinstance(n, ast.Name):
            out.append(n.id)
        elif isinstance(n, ast.Attribute):
            out.append(n.attr)
    return out


def befunde(rel, quelltext):
    """Verstoesse in EINER Datei: Liste von (zeile, art)."""
    baum = ast.parse(quelltext)
    eltern = {}
    for n in ast.walk(baum):
        for c in ast.iter_child_nodes(n):
            eltern[c] = n
    out = []
    for n in ast.walk(baum):
        if isinstance(n, ast.keyword) and n.arg == "verify" \
                and isinstance(n.value, ast.Constant) and n.value.value is False:
            out.append((n.value.lineno, "verify=False fest"))
        if isinstance(n, ast.Attribute) and n.attr == "_create_unverified_context":
            out.append((n.lineno, "_create_unverified_context"))
        if isinstance(n, ast.Attribute) and n.attr == "CERT_NONE":
            a, fn, bedingt = n, None, False
            while a in eltern:
                a = eltern[a]
                if isinstance(a, ast.If) and any(PRUEF_WORT.search(x) for x in _namen(a.test)):
                    bedingt = True
                if fn is None and isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn = a.name
            if not bedingt and (rel, fn) not in ABHOLER:
                out.append((n.lineno, "CERT_NONE ohne Pruef-Einstellung in %s()" % fn))
    return out


# Positivkontrollen: die Regel erkennt die alten Fassungen und laesst die richtigen durch.
ALT_WEBHOOK = ("async def f(url):\n    async with httpx.AsyncClient(timeout=15.0, verify=False) as c:\n"
               "        await c.post(url)\n")
ALT_KAMERA = ("def open(self):\n    if self._url.startswith('https'):\n"
              "        ctx = ssl.create_default_context()\n        ctx.check_hostname = False\n"
              "        ctx.verify_mode = ssl.CERT_NONE\n")
NEU_KAMERA = ("def open(self):\n    if self._url.startswith('https'):\n"
              "        ctx = ssl.create_default_context()\n        if not self._tls_pruefen:\n"
              "            ctx.verify_mode = ssl.CERT_NONE\n")
UNVERIFIED = "import ssl\nctx = ssl._create_unverified_context()\n"
if not (befunde("x.py", ALT_WEBHOOK) and befunde("x.py", ALT_KAMERA)
        and befunde("x.py", UNVERIFIED) and not befunde("x.py", NEU_KAMERA)):
    abbruch("Positivkontrolle der Regel faellt durch – die Regel ist blind")
print("  (Positivkontrolle: alte Fassungen erkannt, bedingte Fassung durchgelassen)")

WURZELN = [ROOT / "backend", ROOT / "skills"]
for w in WURZELN:
    if not w.is_dir():
        abbruch("Wurzel fehlt: %s" % w)
dateien = [p for w in WURZELN for p in w.rglob("*.py")
           if "node_modules" not in p.parts and "__pycache__" not in p.parts]
if len(dateien) < 100:
    abbruch("nur %d Python-Dateien gefunden – Geltungsbereich falsch?" % len(dateien))
alle = []
for p in dateien:
    rel = str(p.relative_to(ROOT))
    try:
        alle += [(rel, z, a) for z, a in befunde(rel, p.read_text(encoding="utf-8"))]
    except SyntaxError as e:
        abbruch("nicht parsebar: %s (%s)" % (rel, e))
check("Python: keine feste Abschaltung (%d Dateien)" % len(dateien), not alle,
      "; ".join("%s:%d %s" % t for t in alle))
for (rel, fn), grund in ABHOLER.items():
    q = (ROOT / rel).read_text(encoding="utf-8")
    check("Ausnahme %s:%s() existiert noch (%s)" % (rel, fn, grund),
          re.search(r"^\s*def %s\(" % re.escape(fn), q, re.M) is not None)

node = [p for d in ("services", "skills", "frontend/js")
        for p in (ROOT / d).rglob("*.js") if "node_modules" not in p.parts]
if len(node) < 20:
    abbruch("nur %d JS-Dateien gefunden" % len(node))
nfunde = [str(p.relative_to(ROOT)) for p in node
          if re.search(r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED",
                       p.read_text(encoding="utf-8", errors="replace"))]
check("Node: kein rejectUnauthorized:false (%d Dateien)" % len(node), not nfunde, nfunde)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[B] Trigger-Webhook")

_httpx = types.ModuleType("httpx")
_httpx.AUFRUFE = []


class _Antwort:
    status_code = 204


class _Client:
    def __init__(self, **kw):
        self.kw = kw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        _httpx.AUFRUFE.append({"verify": self.kw.get("verify"), "url": url})
        return _Antwort()


_httpx.AsyncClient = _Client
sys.modules["httpx"] = _httpx

try:
    import backend.file_watcher as fw
except Exception as e:  # noqa: BLE001
    abbruch("file_watcher nicht importierbar: %s" % e)

wm = fw.WatcherManager.__new__(fw.WatcherManager)
wm._watchers = []
wm._register = lambda w: None
wm._unregister = lambda i: None
wm._save = lambda: None


async def _hooks():
    _httpx.AUFRUFE.clear()
    _sl.EREIGNISSE.clear()
    await wm._do_webhook("https://ziel.beispiel.de/h", "x", {})
    a = list(_httpx.AUFRUFE)
    e1 = list(_sl.EREIGNISSE)
    _httpx.AUFRUFE.clear()
    w = {"id": "w1", "owner": "admin"}
    await wm._do_webhook("https://ziel.beispiel.de/h", "x", {}, tls_pruefen=False, watcher=w)
    await wm._do_webhook("https://ziel.beispiel.de/h", "x", {}, tls_pruefen=False, watcher=w)
    return a, e1, list(_httpx.AUFRUFE), list(_sl.EREIGNISSE)


vorgabe, ev_vorgabe, aus, ev_aus = asyncio.run(_hooks())
if not vorgabe or not aus:
    abbruch("Webhook-Attrappe wurde nicht aufgerufen")
check("Vorgabe: verify=True", vorgabe[0]["verify"] is True, vorgabe)
check("Vorgabe: kein Protokolleintrag", not ev_vorgabe, ev_vorgabe)
check("ausdruecklich aus: verify=False", all(x["verify"] is False for x in aus), aus)
check("JEDER Aufruf ohne Pruefung protokolliert (2 Aufrufe -> 2 Eintraege)",
      len([e for e in ev_aus if e["art"] == "tls_pruefung_aus"]) == 2, ev_aus)
check("Eintrag nennt Ziel-Host und Watcher, keine Adresse mit Pfad",
      bool(ev_aus) and ev_aus[0]["details"].get("ziel") == "ziel.beispiel.de"
      and ev_aus[0]["details"].get("watcher") == "w1", ev_aus[:1])

w = wm.add_watcher(label="t", action_type="webhook", webhook_url="https://x/")
check("add_watcher: Vorgabe webhook_tls_pruefen=True", w.get("webhook_tls_pruefen") is True, w)
try:
    wm.add_watcher(label="t", webhook_tls_pruefen="nein")
    check("add_watcher: Nicht-bool abgelehnt", False)
except ValueError:
    check("add_watcher: Nicht-bool abgelehnt", True)
check("Feld ist aenderbar (UPDATABLE_FIELDS)", "webhook_tls_pruefen" in wm.UPDATABLE_FIELDS)
wm.update_watcher(w["id"], webhook_tls_pruefen=False)
check("update_watcher: false wird uebernommen", wm.get_watcher(w["id"])["webhook_tls_pruefen"] is False)
try:
    wm.update_watcher(w["id"], webhook_tls_pruefen="false")
    check("update_watcher: Zeichenkette 'false' abgelehnt", False)
except ValueError:
    check("update_watcher: Zeichenkette 'false' abgelehnt", True)

# Ausfuehrungsweg: der Ausloeser reicht das Feld weiter (Alt-Watcher ohne Feld = pruefen)
src_fw = (ROOT / "backend/file_watcher.py").read_text(encoding="utf-8")
baum = ast.parse(src_fw)
weiter = []
for n in ast.walk(baum):
    if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_do_webhook":
        weiter.append({k.arg: ast.unparse(k.value) for k in n.keywords})
check("Ausloeser reicht tls_pruefen weiter (fehlendes Feld = pruefen)",
      any(k.get("tls_pruefen", "").replace('"', "'") ==
          "watcher.get('webhook_tls_pruefen') is not False" for k in weiter), weiter)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[C] Endpunkt POST /api/watchers")

src_main = (ROOT / "backend/main.py").read_text(encoding="utf-8")
mbaum = ast.parse(src_main)
fn = next((n for n in mbaum.body if isinstance(n, ast.AsyncFunctionDef)
           and n.name == "watcher_create"), None)
if fn is None:
    abbruch("watcher_create nicht gefunden")
kw = {}
for n in ast.walk(fn):
    if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add_watcher":
        kw = {k.arg: k.value for k in n.keywords}
ausdruck = kw.get("webhook_tls_pruefen")
check("add_watcher bekommt webhook_tls_pruefen", ausdruck is not None)
if ausdruck is not None:
    def _wert(body):
        return eval(compile(ast.Expression(ausdruck), "<m12>", "eval"), {"body": body})
    check("Endpunkt: fehlt -> pruefen", _wert({}) is True)
    check("Endpunkt: false -> aus", _wert({"webhook_tls_pruefen": False}) is False)
    check("Endpunkt: 'false' (Zeichenkette) -> pruefen", _wert({"webhook_tls_pruefen": "false"}) is True)
    check("Endpunkt: 0 -> pruefen", _wert({"webhook_tls_pruefen": 0}) is True)
einricht = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
            and getattr(n.func, "attr", "") == "ereignis"
            and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "tls_pruefung_aus"]
check("Einrichten ohne Pruefung wird protokolliert", bool(einricht))

# ═════════════════════════════════════════════════════════════════════════════
print("\n[D] Kamera-Stream")

for mod in ("cv2", "numpy"):
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = types.ModuleType(mod)
sys.modules.setdefault("face_recognition", types.ModuleType("face_recognition"))
try:
    sys.path.insert(0, str(ROOT / "skills" / "vision"))
    import vision_engine as ve
except Exception as e:  # noqa: BLE001
    abbruch("vision_engine nicht importierbar: %s" % e)

KONTEXTE = []


class _Stream:
    def read(self, *a):
        return b""


def _urlopen(url, timeout=None, context=None):
    KONTEXTE.append(context)
    return _Stream()


ve.urllib.request.urlopen = _urlopen
ve.MjpegStreamReader("https://kamera.beispiel.de/v").open()
ve.MjpegStreamReader("https://kamera.beispiel.de/v", tls_pruefen=False).open()
if len(KONTEXTE) != 2 or not all(isinstance(c, ssl.SSLContext) for c in KONTEXTE):
    abbruch("urlopen-Attrappe nicht erreicht: %r" % KONTEXTE)
check("Vorgabe: Kamera-Zertifikat wird geprueft", KONTEXTE[0].verify_mode == ssl.CERT_REQUIRED)
check("Vorgabe: Name wird geprueft", KONTEXTE[0].check_hostname is True)
check("ausdruecklich aus: CERT_NONE", KONTEXTE[1].verify_mode == ssl.CERT_NONE)

_cfg.config.skill_states = {}
check("Einstellung fehlt -> pruefen", ve._stream_tls_pruefen() is True)
_cfg.config.skill_states = {"vision": {"config": {"stream_tls_pruefen": False}}}
check("Einstellung false -> aus", ve._stream_tls_pruefen() is False)
_cfg.config.skill_states = {"vision": {"config": {"stream_tls_pruefen": "false"}}}
check("Einstellung 'false' (Zeichenkette) -> pruefen", ve._stream_tls_pruefen() is True)
_cfg.config.skill_states = RuntimeError("nicht lesbar")
check("Einstellung unlesbar -> pruefen (fail-closed)", ve._stream_tls_pruefen() is True)

# start() liest die Einstellung und protokolliert; Wiederverbinden reicht sie weiter
eng = ve.VisionEngine.__new__(ve.VisionEngine)
eng._running = False
eng._tls_pruefen = True
ve.face_recognition = types.SimpleNamespace()
_sl.EREIGNISSE.clear()
KONTEXTE.clear()
_cfg.config.skill_states = {"vision": {"config": {"stream_tls_pruefen": False}}}
ve.threading = types.SimpleNamespace(Thread=lambda **kw: types.SimpleNamespace(start=lambda: None))
try:
    eng.start("https://kamera.beispiel.de/v?token=geheim")
except Exception as e:  # noqa: BLE001
    print("    (start() nach dem Oeffnen abgebrochen: %s)" % e)
check("start(): Einstellung false -> Stream ohne Pruefung",
      bool(KONTEXTE) and KONTEXTE[0].verify_mode == ssl.CERT_NONE, KONTEXTE)
ev = [e for e in _sl.EREIGNISSE if e["art"] == "tls_pruefung_aus"]
check("start(): ohne Pruefung protokolliert", len(ev) == 1, _sl.EREIGNISSE)
check("start(): Protokoll nennt nur den Rechner, nicht das Token",
      bool(ev) and ev[0]["details"].get("ziel") == "kamera.beispiel.de"
      and "geheim" not in repr(ev), ev)
src_ve = (ROOT / "skills/vision/vision_engine.py").read_text(encoding="utf-8")
neu_reader = [ast.unparse(n) for n in ast.walk(ast.parse(src_ve)) if isinstance(n, ast.Call)
              and getattr(n.func, "id", "") == "MjpegStreamReader"]
check("jede Reader-Erzeugung reicht tls_pruefen weiter (%d)" % len(neu_reader),
      len(neu_reader) >= 3 and all("tls_pruefen=self._tls_pruefen" in r for r in neu_reader), neu_reader)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[E] Standort-Sync")
try:
    import backend.knowledge_sync as ks
except Exception as e:  # noqa: BLE001
    abbruch("knowledge_sync nicht importierbar: %s" % e)
try:
    ks._ssl_kontext({})
    check("ohne gebundenes Zertifikat kein Nutzdaten-Kontext", False)
except ValueError:
    check("ohne gebundenes Zertifikat kein Nutzdaten-Kontext", True)
try:
    ks._ssl_kontext()
    check("ohne Argument kein Nutzdaten-Kontext", False)
except ValueError:
    check("ohne Argument kein Nutzdaten-Kontext", True)
check("Ermittlungs-Kontext existiert (nur Handshake)",
      ks._ermittlungs_kontext().verify_mode == ssl.CERT_NONE)
src_ks = (ROOT / "backend/knowledge_sync.py").read_text(encoding="utf-8")
zf = next((n for n in ast.parse(src_ks).body if isinstance(n, ast.FunctionDef)
           and n.name == "zertifikat_abfragen"), None)
aufr = [ast.unparse(n.func) for n in ast.walk(zf) if isinstance(n, ast.Call)] if zf else []
check("zertifikat_abfragen benutzt den Ermittlungs-Kontext",
      "_ermittlungs_kontext" in aufr and "_ssl_kontext" not in aufr, aufr)
nutz = [ast.unparse(n) for n in ast.walk(mbaum) if isinstance(n, ast.Call)
        and ast.unparse(n.func) == "ks._ssl_kontext"]
check("main.py: jeder Sync-Kontext bindet ein Zertifikat (%d)" % len(nutz),
      bool(nutz) and all(n != "ks._ssl_kontext()" for n in nutz), nutz)

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
