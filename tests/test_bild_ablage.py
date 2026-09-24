#!/usr/bin/env python3
"""Waechter fuer die Bild-Ablage: Sandbox-Sperre (A) + Vorhaltezeit (B).

Anlass (2026-09-24): `data/generated_images` hatte KEIN Aufraeumen, und der
Ordner war 0755 – auf DEV gemessen konnte `jarvis_sandbox` alle 39 Dateinamen
auflisten und die Bilder lesen, waehrend `data/documents` korrekt verweigerte.
Weil der Dateiname die ganze Zugangskontrolle IST (`/api/generated/<32 Hex>`
kommt ohne Anmeldung aus), war damit die Capability-URL ausgehebelt.

Geprueft wird die EIGENSCHAFT, nicht das Vorkommen:
  * die Loeschregel wird WIRKLICH AUSGEFUEHRT (ob ein Symlink verschont bleibt,
    kann eine Quelltext-Pruefung nicht beantworten),
  * die Sperrlisten als DATENSTRUKTUR – eine Textsuche laese den Kommentar mit,
    der begruendet, warum `generated_images` NICHT in `_APP_DENY_REL` steht,
  * die Endungen als DRIFT-SCHRANKE gegen den Endpunkt in main.py.

    python3 tests/test_bild_ablage.py
"""
import ast
import os
import re
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


def sicher(fn, *a, **kw):
    """Ruft fn und gibt bei einem Wurf den Fehler zurueck.

    Nie ungeprueft dereferenzieren: ein Wurf in einer Pruefung beendet den Lauf
    OHNE Bilanzzeile und ist dann von "nicht gelaufen" nicht zu unterscheiden
    (Register, mehrfach bezahlt).
    """
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return e


# ── backend.config als STUB ───────────────────────────────────────────────────
# Der echte Import migriert Profile und schreibt die Live-settings.json zurueck
# (Register). `bild_ablage` braucht ihn nicht – nur `sandbox` zieht ihn.
_cfg = types.ModuleType("backend.config")


class _Cfg:
    def __getattr__(self, n):
        return ""


_cfg.config = _Cfg()
sys.modules.setdefault("backend.config", _cfg)

from backend import bild_ablage as ba                                   # noqa: E402
from backend import sandbox as sb                                       # noqa: E402

MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")

# ── NAMENS-GUARD, UND ER STEHT GANZ OBEN ─────────────────────────────────────
# Fehlt ein Name (aelterer Stand, umbenannte Funktion), stirbt der Lauf sonst
# mitten im Abschnitt an einem nackten AttributeError – OHNE Bilanzzeile, und
# damit von "nicht gelaufen" nicht zu unterscheiden. Genau so blieb die
# Gegenprobe "ttl_days als KONSTANTE" stumm (Register: der Guard gehoert VOR
# die erste Verwendung).
_FEHLT = [n for n in ("ENDUNGEN", "DEFAULT_TTL_DAYS", "_NAME_RE", "bildordner",
                      "ttl_days", "cleanup", "stats")
          if not hasattr(ba, n)]
if _FEHLT:
    print(f"\nFAIL bild_ablage fehlen Namen: {_FEHLT}")
    print(f"\nErgebnis: 0 OK, {len(_FEHLT)} FAIL")
    sys.exit(1)
for _n in ("PRIVATE_DIRS", "PRIVATE_MODE", "_APP_DENY_REL", "READ_ROOTS",
           "fs_target_sensitive", "authorize_fs"):
    if not hasattr(sb, _n):
        print(f"\nFAIL sandbox fehlt: {_n}")
        print("\nErgebnis: 0 OK, 1 FAIL")
        sys.exit(1)


# ── SANDKASTEN ───────────────────────────────────────────────────────────────
# ⚠ EXIT 2, WENN ER NICHT GREIFT. Dieser Test LOESCHT Dateien – laeuft er gegen
# das echte data/generated_images, sind Bilder aus echten Auftraegen weg. Ein
# Test, der das anrichtet, ist teurer als der Fehler, den er sucht.
_tmp = Path(tempfile.mkdtemp(prefix="jarvis_bildablage_test_"))
ba.bildordner = lambda: _tmp

if "jarvis_bildablage_test_" not in str(ba.bildordner()):
    print("ABBRUCH: bildordner() zeigt nicht in das Wegwerf-Verzeichnis")
    sys.exit(2)
# Und die ECHTE Funktion darf woanders hinzeigen als der Sandkasten – sonst
# prueft die Schranke oben sich selbst.
try:
    from backend.tools.image_gen import _IMG_DIR as _ECHT
    if str(_ECHT) == str(_tmp):
        print("ABBRUCH: echter Bildordner == Sandkasten")
        sys.exit(2)
except Exception:  # noqa: BLE001
    pass                      # ohne Backend-Stack nicht importierbar: in Ordnung

H = "0123456789abcdef" * 2            # 32 Hex
H2 = "fedcba9876543210" * 2
ALT = time.time() - 40 * 86400        # 40 Tage
NEU = time.time() - 2 * 86400         # 2 Tage


def mk(name, mtime, inhalt=b"\x89PNG\r\n\x1a\n"):
    p = _tmp / name
    p.write_bytes(inhalt)
    os.utime(p, (mtime, mtime))
    return p


# ═════════════════════════════════════════════════════════════════════════════
print("\n1. A – Sandbox-Sperre (Datenstruktur, nicht Textsuche)")

check("data/generated_images" in sb.PRIVATE_DIRS,
      "data/generated_images steht in PRIVATE_DIRS")
check(sb.PRIVATE_MODE == 0o750, "PRIVATE_MODE ist 0750")
# Positivkontrolle: die Nachbarn sind unangetastet – ohne sie waere die Pruefung
# auch mit einer kaputten Liste gruen.
for _d in ("data/documents", "data/chats", "data/logs"):
    check(_d in sb.PRIVATE_DIRS, f"Positivkontrolle: {_d} weiterhin in PRIVATE_DIRS")

# ⚠ ABSICHTLICH NICHT in _APP_DENY_REL: das wuerde die HAERTE aendern (Angriffs-
# indiz -> Kontosperre nach 3 Versuchen), nicht die Sperre. Der Pfad liegt aber
# nahe – das Modell hat `/api/generated/<hash>.png` im Kontext. Gemessen als
# Datenstruktur, weil der Quelltext den Grund im Kommentar NENNT.
check("data/generated_images" not in sb._APP_DENY_REL,
      "⚠ NICHT in _APP_DENY_REL (Haerte bleibt weich – geratener Pfad)")
check(sb.fs_target_sensitive(f"data/generated_images/{H}.png") is False,
      "fs_target_sensitive sagt weiterhin False (keine Kontosperre)")
check(sb.fs_target_sensitive("data/chats/x/meta.json") is True,
      "Positivkontrolle: data/chats ist weiterhin HART")


print("\n2. A – der WERKZEUG-Weg war schon zu und bleibt es")
# Nicht der Grund des Fixes, aber die Zusage: `filesystem` kommt nicht heran,
# weil der Ordner nicht in READ_ROOTS steht. Ohne diese Pruefung koennte ihn
# jemand dort nachtragen und die Sperre waere halb.
for akt in ("read", "list", "write"):
    erg = sicher(sb.authorize_fs, akt, f"data/generated_images/{H}.png",
                 "nexus\\testuser")
    ok = isinstance(erg, tuple) and erg[0] is False and str(erg[1]).strip() != ""
    check(ok, f"authorize_fs weist '{akt}' ab – mit Grund")
check(not any("generated_images" in str(r) for r in sb.READ_ROOTS),
      "generated_images steht NICHT in READ_ROOTS")


print("\n3. B – Frist (ttl_days)")
_vorher = os.environ.pop("JARVIS_GENIMG_TTL_DAYS", None)
check(ba.ttl_days() == 30, "Vorgabe ist 30 Tage")
check(ba.DEFAULT_TTL_DAYS == 30, "DEFAULT_TTL_DAYS == 30")
for wert, erwartet, was in (("0", 0, "0 = dauerhaft"),
                            ("-5", 0, "negativ = dauerhaft"),
                            ("7", 7, "7 wird uebernommen"),
                            ("99999", 3650, "Deckel 3650"),
                            ("kaputt", 30, "unbrauchbar -> VORGABE, nicht 0"),
                            ("", 30, "leer -> Vorgabe")):
    os.environ["JARVIS_GENIMG_TTL_DAYS"] = wert
    check(ba.ttl_days() == erwartet, f"ttl_days({wert!r}) == {erwartet} ({was})")
os.environ.pop("JARVIS_GENIMG_TTL_DAYS", None)
# ttl_days ist eine FUNKTION, keine Konstante: ein beim Import gelesener Wert
# waere bis zum Dienststart eingefroren.
_quelle = (ROOT / "backend" / "bild_ablage.py").read_text(encoding="utf-8")
check(re.search(r"^def ttl_days\(", _quelle, re.M) is not None,
      "ttl_days ist eine Funktion (nicht eingefroren)")


print("\n4. B – die Loeschregel wird AUSGEFUEHRT")
a_alt = mk(f"{H}.png", ALT)
a_neu = mk(f"{H2}.png", NEU)
weg, frei = ba.cleanup(days=30)
check(weg == 1, f"genau 1 Bild entfernt (war {weg})")
check(not a_alt.exists(), "40 Tage altes Bild ist weg")
check(a_neu.exists(), "2 Tage altes Bild bleibt")
check(frei > 0, "freigegebene Bytes werden gemeldet")

print("\n4b. dauerhaft (0) fasst NICHTS an")
a_alt2 = mk(f"{H}.png", ALT)
weg0, _ = ba.cleanup(days=0)
check(weg0 == 0 and a_alt2.exists(), "ttl=0 loescht nichts")

print("\n5. B – vier Schranken: nichts Fremdes wird getroffen")
fremd = []
# kein 32-Hex-Name
fremd.append(mk("readme.txt", ALT))
fremd.append(mk("abc.png", ALT))
fremd.append(mk(H[:31] + ".png", ALT))          # 31 Hex
fremd.append(mk(H + "0.png", ALT))              # 33 Hex
fremd.append(mk(H.upper() + ".png", ALT))       # Grossbuchstaben (Endpunkt nimmt sie nicht)
# Endung, die der Endpunkt nicht ausliefert
fremd.append(mk(f"{H2}.svg", ALT))
fremd.append(mk(f"{H2}.exe", ALT))
# versteckte Datei
fremd.append(mk(".owners.json", ALT))
# Unterverzeichnis mit einem alten Bild darin -> kein Abstieg
unter = _tmp / "unter"
unter.mkdir(exist_ok=True)
tief = unter / f"{H}.png"
tief.write_bytes(b"x")
os.utime(tief, (ALT, ALT))
os.utime(unter, (ALT, ALT))
# Symlink auf eine fremde Datei, MIT passendem Namen und altem Ziel
opfer = _tmp / "opfer.dat"
opfer.write_bytes(b"nicht anfassen")
os.utime(opfer, (ALT, ALT))
link = _tmp / f"{'a' * 32}.png"
try:
    link.symlink_to(opfer)
    os.utime(link, (ALT, ALT), follow_symlinks=False)
    _link_ok = True
except Exception:  # noqa: BLE001
    _link_ok = False

weg2, _ = ba.cleanup(days=30)
check(weg2 == 1, f"nur das echte alte Bild entfernt (waren {weg2})")
for p in fremd:
    check(p.exists(), f"bleibt unangetastet: {p.name}")
check(unter.is_dir() and tief.exists(), "kein Abstieg in Unterverzeichnisse")
if _link_ok:
    check(link.is_symlink(), "⚠ Symlink bleibt (lstat, nicht stat)")
    check(opfer.exists() and opfer.read_bytes() == b"nicht anfassen",
          "⚠ Symlink-ZIEL unangetastet")
else:
    check(False, "Symlink-Fall NICHT GEPRUEFT (symlink nicht moeglich)")

print("\n5b. fremder Eigentuemer wird nicht angefasst")
# uid umbiegen statt root zu brauchen: danach gehoert KEINE Datei "uns".
_echt_uid = os.getuid
mk(f"{H}.png", ALT)
os.getuid = lambda: _echt_uid() + 12345
weg3, _ = ba.cleanup(days=30)
os.getuid = _echt_uid
check(weg3 == 0, "bei fremdem Eigentuemer wird nichts geloescht")
check((_tmp / f"{H}.png").exists(), "die Datei liegt noch da")

print("\n5c. ein nicht vorhandener Ordner ist kein Fehler")
_alt_b = ba.bildordner
ba.bildordner = lambda: _tmp / "gibtsnicht"
erg = sicher(ba.cleanup, 30)
check(erg == (0, 0), "fehlender Ordner -> (0, 0), kein Wurf")
ba.bildordner = _alt_b


print("\n6. DRIFT-SCHRANKE: Endungen == was der Endpunkt ausliefert")
# _MEDIA im Endpunkt get_generated_image per AST lesen – nicht per Regex ueber
# die ganze Datei, und nicht nachgebaut.
_ep_endungen = None
_ep_hexlen = None
try:
    baum = ast.parse(MAIN)
    for fn in ast.walk(baum):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and fn.name == "get_generated_image":
            for knoten in ast.walk(fn):
                if isinstance(knoten, ast.Dict) and _ep_endungen is None:
                    schluessel = [k.value for k in knoten.keys
                                  if isinstance(k, ast.Constant)]
                    if schluessel and all(isinstance(s, str) for s in schluessel):
                        _ep_endungen = set(schluessel)
                if isinstance(knoten, ast.Constant) and knoten.value == 32:
                    _ep_hexlen = 32
            break
except Exception as e:  # noqa: BLE001
    print(f"  (AST-Schnitt fehlgeschlagen: {e})")

check(_ep_endungen is not None, "Positivkontrolle: _MEDIA im Endpunkt gefunden")
if _ep_endungen:
    check(set(ba.ENDUNGEN) == _ep_endungen,
          f"ENDUNGEN == Endpunkt-Whitelist ({sorted(ba.ENDUNGEN)})")
check(_ep_hexlen == 32, "Positivkontrolle: Endpunkt verlangt 32 Hex")

# Die EIGENSCHAFT: genau die Namen, die der Endpunkt durchlaesst, darf die
# Aufraeumregel auch treffen. Eine Datei, die der Endpunkt NICHT ausliefert,
# haben wir nicht erzeugt – und was wir nicht erzeugt haben, loeschen wir nicht.
def _endpunkt_ok(name):
    """Nachbildung NUR fuer den Vergleich – die Werte kommen aus dem AST oben."""
    stem, _, ext = name.rpartition(".")
    return (ext.lower() in (_ep_endungen or set())
            and len(stem) == 32
            and all(c in "0123456789abcdef" for c in stem))


_faelle = [f"{H}.png", f"{H2}.webp", f"{H}.jpeg", f"{H}.jpg", f"{H}.gif",
           f"{H}.svg", f"{H}.exe", "readme.txt", f"{H[:31]}.png",
           f"{H}0.png", f"{H.upper()}.png", ".owners.json", f"{H}.PNG"]

# ⚠ DIE ZUSAGE IST EINE RICHTUNG, KEINE SYMMETRIE – und das hat der erste Lauf
# gezeigt: `<hash>.PNG` liefert der Endpunkt aus (er kleinschreibt die Endung),
# mein Muster trifft es nicht. Das ist KEIN Loch, sondern die vierte Schranke:
# kein Schreibweg erzeugt Grossendungen (magische Bytes, MIME-Tabelle, festes
# `.png`), eine solche Datei haben wir also nicht erzeugt – und was wir nicht
# erzeugt haben, loeschen wir nicht. Geprueft wird deshalb:
#   was ich LOESCHE, muss der Endpunkt ausliefern koennen (Teilmenge).
_verletzt = [n for n in _faelle
             if ba._NAME_RE.fullmatch(n) and not _endpunkt_ok(n)]
check(not _verletzt,
      f"⚠ was geloescht wird, liefert der Endpunkt aus (Verstoesse: {_verletzt})")
# Die Gegenrichtung DARF abweichen – aber nur nach oben (Endpunkt toleranter).
# Diese Pruefung haelt den gemessenen Unterschied fest, damit er nicht
# unbemerkt "vervollstaendigt" wird.
_toleranter = [n for n in _faelle
               if _endpunkt_ok(n) and not ba._NAME_RE.fullmatch(n)]
check(_toleranter == [f"{H}.PNG"],
      f"der Endpunkt ist NUR bei Grossendungen toleranter (gemessen: {_toleranter})")
check(any(ba._NAME_RE.fullmatch(n) for n in _faelle)
      and any(not ba._NAME_RE.fullmatch(n) for n in _faelle),
      "Positivkontrolle: die Faelle trennen (nicht alle gleich)")


print("\n7. DRIFT-SCHRANKE: die vier Schreibwege erzeugen passende Namen")
# Wer einen fuenften Schreibweg baut, der anders benennt, faellt hier auf:
# seine Dateien wuerden nie aufgeraeumt (und waeren ueber den Endpunkt auch
# nicht abrufbar).
_schreiber = {
    "backend/tools/image_gen.py": r"uuid4\(\)\.hex",
    "backend/tools/image_search.py": r"uuid4\(\)\.hex",
    "backend/tools/bild_text.py": r"uuid4\(\)\.hex",
    "backend/agent.py": r"sha256\([^)]*\)\.hexdigest\(\)\[:32\]",
}
for datei, muster in _schreiber.items():
    txt = (ROOT / datei).read_text(encoding="utf-8")
    check(re.search(muster, txt) is not None,
          f"{datei}: erzeugt 32-Hex-Namen ({muster})")
# Und beide Namensarten treffen das Muster wirklich:
import hashlib                                                          # noqa: E402
import uuid                                                             # noqa: E402
check(ba._NAME_RE.fullmatch(f"{uuid.uuid4().hex}.png") is not None,
      "uuid4().hex + .png trifft _NAME_RE")
check(ba._NAME_RE.fullmatch(
      f"{hashlib.sha256(b'x').hexdigest()[:32]}.webp") is not None,
      "sha256[:32] + .webp trifft _NAME_RE")


print("\n8. Verdrahtung: der Startup-Hook laeuft wirklich")
# Per AST, nicht per Textsuche – ein Name kommt auch im Kommentar vor.
_hook = None
try:
    baum = ast.parse(MAIN)
    for fn in ast.walk(baum):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and fn.name == "startup_bilder_retention":
            _hook = fn
            break
except Exception as e:  # noqa: BLE001
    print(f"  (AST fehlgeschlagen: {e})")

check(_hook is not None, "startup_bilder_retention existiert")
if _hook:
    deko = [ast.unparse(d) for d in _hook.decorator_list]
    check(any("on_event" in d and "startup" in d for d in deko),
          "ist als @app.on_event('startup') registriert")
    # ⚠ DEN DOCSTRING ABSCHNEIDEN, SONST LIEST DER WAECHTER SEINE EIGENE
    # BEGRUENDUNG. `ast.unparse` nimmt ihn mit, und er nennt `ttl_days()` und
    # "Schleife" in erklaerendem Fliesstext – die Reihenfolge-Pruefung unten
    # schlug damit fehl, obwohl der Code stimmt (beim ersten Lauf bezahlt;
    # im Projekt der achtzehnte Fall dieser Klasse).
    _koerper = list(_hook.body)
    if _koerper and isinstance(_koerper[0], ast.Expr) \
            and isinstance(_koerper[0].value, ast.Constant) \
            and isinstance(_koerper[0].value.value, str):
        _koerper = _koerper[1:]
    rumpf = "\n".join(ast.unparse(s) for s in _koerper)
    check("Vorhaltezeit fuer erzeugte Bilder" not in rumpf,
          "Positivkontrolle: der Docstring ist wirklich abgeschnitten")

    check("_bildablage.cleanup" in rumpf, "ruft bild_ablage.cleanup")
    check("to_thread" in rumpf,
          "ueber asyncio.to_thread (blockierende I/O nicht im Event-Loop)")
    check("ttl_days" in rumpf, "fragt die Frist bei jedem Durchlauf neu")
    check("while True" in rumpf and "sleep" in rumpf,
          "laeuft in einer Schleife (nicht nur beim Start)")
    # Die Schleife muss AUCH bei "dauerhaft" weiterlaufen – sonst greift ein
    # Umstellen von 0 auf 30 erst beim naechsten Dienststart.
    _i_while = rumpf.find("while True")
    _i_ttl = rumpf.find("ttl_days")
    check(0 <= _i_while < _i_ttl,
          "⚠ die Frist wird INNERHALB der Schleife geprueft")

check(re.search(r"^from backend import bild_ablage as _bildablage$", MAIN, re.M)
      is not None, "main.py importiert das Modul")


print("\n9. cleanup fasst NUR den Bildordner an")
# Regel ueber den Syntaxbaum: keine harte Pfadangabe im Modul, die woandershin
# zeigt. Ohne das koennte ein spaeterer Feinschliff einen zweiten Ort einfuehren.
_baum = ast.parse(_quelle)
_pfade = [n.value for n in ast.walk(_baum)
          if isinstance(n, ast.Constant) and isinstance(n.value, str)
          and ("/" in n.value) and n.value.strip() not in ("/",)]
_verdacht = [p for p in _pfade
             if p.startswith("/") or p.startswith("data/") or p.startswith("..")]
check(not _verdacht, f"keine harte Pfadangabe im Modul (gefunden: {_verdacht})")
check(_quelle.count("def bildordner(") == 1,
      "bildordner ist genau einmal definiert (eine Quelle)")

# ⚠ NICHT `"_IMG_DIR" in _quelle` – das blieb wahr, als eine Gegenprobe den
# Import durch einen HARTEN Pfad ersetzte: der Name stand danach nur noch im
# DOCSTRING, der genau diese Regel erklaert (neunzehnter Fall dieser Klasse).
# Und der Pfad-Filter oben greift dort nicht, weil `Path(x) / "data" /
# "generated_images"` gar keinen Schraegstrich enthaelt.
# Gemessen wird deshalb die EIGENSCHAFT ueber den Syntaxbaum: `bildordner()`
# holt den Ordner per echtem IMPORT aus image_gen.
_bo = None
for _fn in ast.walk(_baum):
    if isinstance(_fn, ast.FunctionDef) and _fn.name == "bildordner":
        _bo = _fn
        break
check(_bo is not None, "Positivkontrolle: bildordner() im Syntaxbaum gefunden")
_importiert = False
if _bo:
    for _k in ast.walk(_bo):
        if isinstance(_k, ast.ImportFrom) and "image_gen" in (_k.module or "") \
                and any(a.name == "_IMG_DIR" for a in _k.names):
            _importiert = True
check(_importiert,
      "⚠ bildordner() IMPORTIERT image_gen._IMG_DIR (nicht nachgebaut)")

print("\n10. stats() gibt KEINE Dateinamen heraus")
# Ein Dateiname ist hier die vollstaendige Capability-URL.
mk(f"{H}.png", NEU)
st = sicher(ba.stats)
check(isinstance(st, dict), "stats() liefert ein dict")
if isinstance(st, dict):
    check(st.get("bilder", 0) >= 1, "zaehlt die Bilder")
    check(st.get("ttl_days") == 30, "nennt die Frist")
    flach = repr(st)
    check(H not in flach and "a" * 32 not in flach,
          "⚠ kein Dateiname in der Ausgabe")


# ── Aufraeumen ───────────────────────────────────────────────────────────────
import shutil                                                           # noqa: E402
shutil.rmtree(_tmp, ignore_errors=True)

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
