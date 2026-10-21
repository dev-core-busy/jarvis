"""Waechter: Wissensgruppen-Tabelle – Spalte "Quelle" und das Auge (2026-10-21).

Zwei gemeldete Befunde, beide auf DEV reproduziert:
  (a) Die Spalte "Quelle" zeigte fuer Dateien ohne Extraktor-Dokument den
      KONFIGURIERTEN Wissensordner statt des Orts der Datei – fuer alles in
      einem Unterordner also einen abgeschnittenen Pfad.
  (b) /api/knowledge/file_read las JEDE Datei als UTF-8. Eine PDF- oder
      Office-Datei ergab HTTP 500 mit dem Codec-Text; das Auge fuehrte damit
      im Normalfall zu einer Fehlermeldung.

Gemessen wird AUSGEFUEHRT, nicht gelesen: der Endpunkt-Rumpf wird per `ast`
geschnitten und gegen echte Dateien in einem Sandkasten gefahren – ob eine
echte Binaerdatei 200 oder 500 ergibt, kann eine Quelltext-Pruefung nicht
beantworten.

  python3 tests/test_wissen_quelle_auge.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

W = Path(__file__).resolve().parent.parent
_ok = _fail = 0
BILANZ = False


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


def abbruch(grund):
    print("ABBRUCH: %s" % grund)
    sys.exit(2)


def abschnitt(t):
    print("\n%s" % t)


# ── Endpunkt-Rumpf schneiden ───────────────────────────────────────────────
QUELLE = (W / "backend/main.py").read_text(encoding="utf-8")
baum = ast.parse(QUELLE)
fn = None
for k in ast.walk(baum):
    if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == "read_knowledge_file":
        fn = k
        break
if fn is None:
    abbruch("read_knowledge_file nicht in backend/main.py gefunden")

# ⚠ SANDKASTEN MIT EXIT 2: der Endpunkt loest gegen PROJECT_ROOT auf. Zeigt ein
# Pfad aus dem Wegwerf-Verzeichnis heraus, hat der Lauf nicht gemessen, was er
# behauptet – und "konnte nicht laufen" muss von "bestanden" unterscheidbar sein.
SAND = Path(tempfile.mkdtemp(prefix="jv_auge_"))
WURZEL = SAND / "projekt"
ORDNER = WURZEL / "data" / "rag" / "beispiel"
ORDNER.mkdir(parents=True)
LEARNED = WURZEL / "data" / "erfahrung"
LEARNED.mkdir(parents=True)


class _Antwort:
    """Attrappe fuer JSONResponse – bildet die ECHTE Signatur nach."""

    def __init__(self, inhalt, status_code=200):
        self.inhalt = inhalt
        self.status_code = status_code


def _liegt_unter(p, wurzel):
    try:
        Path(p).resolve().relative_to(Path(wurzel).resolve())
        return True
    except ValueError:
        return False


class _Wurf:
    """Ein Wurf im Endpunkt ist ein BEFUND, kein Abbruch des Laufs.

    ⚠ OHNE DAS ENDET EINE GEGENPROBE OHNE BILANZZEILE – und "konnte nicht
    laufen" ist von "ich beisse" nicht zu unterscheiden (Register). Die
    Sabotage "der UnicodeDecodeError-Zweig fehlt" ist genau so ein Fall."""

    def __init__(self, e):
        self.status_code = 599
        self.inhalt = {"error": "%s: %s" % (type(e).__name__, e)}


def ruf(pfad):
    """Fuehrt den geschnittenen Endpunkt mit gestellter Umgebung aus."""
    ns = {
        "JSONResponse": _Antwort,
        "_liegt_unter": _liegt_unter,
        "Depends": lambda *a, **k: None,
        "require_auth_or_agent": None,
        "app": type("A", (), {"get": lambda *a, **k: (lambda f: f)})(),
    }
    # Die Importe im Rumpf gegen den Sandkasten stellen
    import types
    mod_k = types.ModuleType("backend.tools.knowledge")
    mod_k._get_folders = lambda: [ORDNER]
    mod_k.PROJECT_ROOT = WURZEL
    mod_l = types.ModuleType("backend.learning")
    mod_l.LEARNED_DIR = LEARNED
    sys.modules["backend.tools.knowledge"] = mod_k
    sys.modules["backend.learning"] = mod_l
    quelle = ast.get_source_segment(QUELLE, fn)
    # Dekorator weglassen – ast.get_source_segment liefert ihn nicht mit
    exec(compile(ast.parse(quelle), "<endpunkt>", "exec"), ns)
    try:
        return asyncio.run(ns["read_knowledge_file"](pfad, user="probe"))
    except Exception as e:
        return _Wurf(e)


try:
    # ── 1. Sandkasten ──────────────────────────────────────────────────────
    abschnitt("1. Sandkasten greift")
    if not str(ORDNER).startswith(str(SAND)):
        abbruch("Sandkasten-Pfad zeigt hinaus: %s" % ORDNER)
    check("der Wegwerf-Baum liegt ausserhalb des Repos",
          not str(SAND).startswith(str(W)), str(SAND))

    # ── 2. Text bleibt Text ────────────────────────────────────────────────
    abschnitt("2. Positivkontrolle: eine Textdatei kommt weiterhin als Text")
    (ORDNER / "notiz.md").write_text("# Titel\nInhalt mit Umlaut: äöü\n", encoding="utf-8")
    a = ruf("data/rag/beispiel/notiz.md")
    check("HTTP 200", a.status_code == 200, str(a.status_code))
    check("ok=True und Inhalt da",
          a.inhalt.get("ok") is True and "Umlaut" in a.inhalt.get("content", ""),
          json.dumps(a.inhalt)[:80])
    check("kein binary-Hinweis bei Text", not a.inhalt.get("binary"))

    # ── 3. Der gemeldete Fall ──────────────────────────────────────────────
    abschnitt("3. Eine Datei, die kein UTF-8 ist (der gemeldete Fall)")
    # ⚠ ECHTE NICHT-DEKODIERBARE BYTES. Ein selbstgebautes Mini-PDF aus reinem
    # ASCII laesst sich als UTF-8 lesen – damit waere der Fall gar nicht
    # hergestellt und jede Pruefung darunter trivial wahr (beim Bau passiert).
    roh = b"PK\x03\x04\x14\x00\x08\x08\x08\x00\xb2\x9c\x1dZ\x00\x00\x00\x00"
    (ORDNER / "tabelle.xlsx").write_bytes(roh)
    try:
        roh.decode("utf-8")
        abbruch("Positivkontrolle: die Probebytes SIND als UTF-8 lesbar")
    except UnicodeDecodeError:
        check("Positivkontrolle: die Probe ist wirklich nicht als UTF-8 lesbar", True)
    b = ruf("data/rag/beispiel/tabelle.xlsx")
    check("KEIN HTTP 500 mehr (ein Format ist kein Serverfehler)",
          b.status_code == 200, str(b.status_code))
    check("ok=False mit binary=True",
          b.inhalt.get("ok") is False and b.inhalt.get("binary") is True,
          json.dumps(b.inhalt)[:90])
    check("der MIME-Typ kommt MIT (damit das Frontend keine Endungsliste braucht)",
          b.inhalt.get("mime") == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          str(b.inhalt.get("mime")))
    check("der Grund steht nicht mehr als Codec-Text da",
          "codec" not in str(b.inhalt.get("error", "")).lower(),
          str(b.inhalt.get("error")))

    # Unbekannte Endung: ein MIME-Typ muss trotzdem kommen, sonst kann das
    # Frontend nicht entscheiden.
    (ORDNER / "daten.unbekannt").write_bytes(b"\xff\xfe\x00\x01")
    c = ruf("data/rag/beispiel/daten.unbekannt")
    check("unbekannte Endung: Rueckfall auf application/octet-stream",
          c.inhalt.get("mime") == "application/octet-stream", str(c.inhalt.get("mime")))

    # ── 4. Die uebrigen Zusagen bleiben ────────────────────────────────────
    abschnitt("4. Die Schranken des Endpunkts sind unberuehrt")
    d = ruf("../../etc/passwd")
    check("Pfad ausserhalb der Wissensordner: 403", d.status_code == 403, str(d.status_code))
    e = ruf("data/rag/beispiel/gibtsnicht.md")
    check("nicht vorhandene Datei: 404", e.status_code == 404, str(e.status_code))

    # ── 5. REGEL: die Quelle-Spalte nimmt den Dateipfad ────────────────────
    abschnitt("5. REGEL: die Spalte 'Quelle' zeigt nicht mehr den Wurzelordner")
    kbm = (W / "frontend/js/kbmatrix.js").read_text(encoding="utf-8")
    # ⚠ KOMMENTARE RAUS: die Begruendung des Fixes nennt `folder.folder`
    # woertlich – ein Waechter, der seine eigene Erklaerung liest, prueft nichts.
    import re as _re
    ohne = _re.sub(r"/\*[\s\S]*?\*/", " ", kbm)
    ohne = _re.sub(r"(^|[^:])//[^\n]*", r"\1", ohne)
    check("Positivkontrolle: der Kommentarfilter greift",
          len(ohne) < len(kbm) and "_rows.push" in ohne,
          "%d -> %d" % (len(kbm), len(ohne)))
    m = _re.search(r"source:\s*([^\n]+)", ohne)
    check("es gibt genau eine source-Zuweisung", bool(m) and ohne.count("source:") == 1,
          str(ohne.count("source:")))
    zeile = m.group(1) if m else ""
    check("der Rueckfall ist der DATEIPFAD, nicht der Ordner",
          "f.path" in zeile and "folder.folder" not in zeile, zeile.strip()[:90])

    BILANZ = True
    print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
    sys.exit(1 if _fail else 0)
finally:
    shutil.rmtree(SAND, ignore_errors=True)
    if not BILANZ:
        print("ABBRUCH ohne Bilanz")
