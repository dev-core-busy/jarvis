#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_webdav_a2wsgi.py ueberhaupt?

Ein Waechter, der nur beim richtigen Stand gruen ist, beweist nichts – er muss beim
falschen Stand ROT werden. Diese Probe legt ihm gebaute Verstoesse vor, darunter den
echten Ausgangszustand vom 2026-10-01 (``from starlette.middleware.wsgi import
WSGIMiddleware``), und verlangt den erwarteten Exit-Code.

DER ARBEITSBAUM WIRD NICHT ANGEFASST. Jede Probe laeuft gegen eine KOPIE in einem
Wegwerf-Verzeichnis, das der Waechter als Wurzel bekommt. Damit entfaellt die ganze
Klasse von Vorfaellen rund um Sabotage-Rueckstaende (abgeschossener Harness, in
derselben Sekunde geschriebene .pyc, Sicherung eines frueheren Laufs) – und zum
Beweis werden die md5-Summen der Originale vor und nach dem Lauf verglichen.

Mitgeprueft wird die Unterscheidung, die hier Geld wert ist: ein echter Verstoss
muss Exit 1 geben ("ich beisse"), ein fehlendes Messmittel Exit 2 ("konnte nicht
laufen"). Wer beides zu Exit 1 verschmilzt, kann einen Abbruch nicht von einem
Befund unterscheiden.

Erwartung: 0 = Stand traegt, 1 = Verstoss erkannt, 2 = konnte nicht laufen.

Lauf:  python3 tests/gegen_webdav_a2wsgi.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
WURZEL = HIER.parent
WAECHTER = HIER / "test_webdav_a2wsgi.py"

# Diese Dateien bekommt die Kopie. Mehr braucht der Waechter nicht: backend.config
# stellt er selbst als Attrappe.
KOPIEREN = [
    Path("requirements.txt"),
    Path("backend/__init__.py"),
    Path("backend/webdav.py"),
    Path("backend/main.py"),
]

DAV = Path("backend/webdav.py")
MAIN = Path("backend/main.py")
REQ = Path("requirements.txt")

# ── Die gebauten Verstoesse ──────────────────────────────────────────────────
# (Name, {Datei: [(alt, neu), ...]}, geloeschte Dateien, erwarteter Exit)
# "alt" muss GENAU EINMAL vorkommen – sonst ist die Sabotage nicht die, die sie
# zu sein behauptet (sie traefe eine eingerueckte Nachbarzeile mit).
FAELLE = [
    ("Ausgangszustand 2026-10-01: Bruecke wieder aus starlette.middleware.wsgi",
     {DAV: [("from a2wsgi import WSGIMiddleware",
             "from starlette.middleware.wsgi import WSGIMiddleware")]}, [], 1),

    ("das abgekuendigte Modul kehrt ueber backend/main.py zurueck",
     {MAIN: [("        from backend.webdav import mount_webdav",
              "        from starlette.middleware.wsgi import WSGIMiddleware\n"
              "        from backend.webdav import mount_webdav")]}, [], 1),

    ("a2wsgi nicht deklariert (der pypdf-Fall: Import in try/except, kein Eintrag)",
     {REQ: [("a2wsgi>=1.10.10\n", "")]}, [], 1),

    ("Teilstring-Falle: 'sse-starlette' statt a2wsgi deklariert",
     {REQ: [("a2wsgi>=1.10.10", "a2wsgi-ersatz>=1.0")]}, [], 1),

    ("enabled wird nicht mehr je Request gelesen (Schalter verdrahtet)",
     {DAV: [("        if not is_webdav_enabled():", "        if False:")]}, [], 1),

    ("abgeschaltet antwortet 200 statt 503",
     {DAV: [('await _text_antwort(send, 503, "WebDAV deaktiviert")',
             'await _text_antwort(send, 200, "WebDAV deaktiviert")')]}, [], 1),

    ("Content-Length luegt (nicht die Laenge des Rumpfs)",
     {DAV: [('str(len(roh)).encode("latin-1")', 'b"0"')]}, [], 1),

    ("verwerfen() nimmt die Bruecke mit -> je Umschaltvorgang ein Threadpool",
     {DAV: [("        self._weiche.ziel = None\n",
             "        self._weiche.ziel = None\n        self._bruecke = None\n")]}, [], 1),

    ("verwerfen() ist wirkungslos -> geaendertes Kennwort greift nie",
     {DAV: [("        self._weiche.ziel = None\n", "        pass\n")]}, [], 1),

    ("Bruecke wird bei JEDEM Request neu gebaut (kein Cache)",
     {DAV: [("        if self._bruecke is None:", "        if True:")]}, [], 1),

    ("Nicht-HTTP-Scopes laufen bis in die Bruecke durch",
     {DAV: [('        if scope["type"] not in ("http",):', "        if False:")]}, [], 1),

    ("_Weiche ohne Ziel laeuft in den TypeError statt fail-closed",
     {DAV: [("        ziel = self.ziel\n        if ziel is None:",
             "        ziel = self.ziel\n        if False:")]}, [], 1),

    ("mount_webdav verdrahtet invalidate_dav_cache nicht",
     {DAV: [("    app.state.invalidate_dav_cache = dav.verwerfen\n", "")]}, [], 1),

    ("DynamicWebDAV umbenannt -> Messgegenstand fehlt, konnte nicht laufen",
     {DAV: [("class DynamicWebDAV:", "class DynamischesWebDAV:")]}, [], 2),

    ("backend/webdav.py fehlt ganz -> konnte nicht laufen", {}, [DAV], 2),

    ("requirements.txt fehlt -> konnte nicht laufen", {}, [REQ], 2),

    ("backend/webdav.py ist syntaktisch kaputt -> konnte nicht laufen",
     {DAV: [("class DynamicWebDAV:", "class DynamicWebDAV(:")]}, [], 2),

    ("unveraenderte Kopie", {}, [], 0),
]


def md5(pfad: Path) -> str:
    return hashlib.md5(pfad.read_bytes()).hexdigest()


def lauf(kopie: Path):
    umgebung = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, str(WAECHTER), str(kopie)],
                       capture_output=True, text=True, timeout=300, env=umgebung)
    return p.returncode, (p.stdout + p.stderr)


def baue_kopie(ziel: Path, patches: dict, loeschen: list) -> list:
    """Kopie anlegen, patchen, loeschen. Rueckgabe: Liste von Problemen."""
    probleme = []
    for rel in KOPIEREN:
        (ziel / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(WURZEL / rel, ziel / rel)
    for rel, ersetzungen in patches.items():
        datei = ziel / rel
        text = datei.read_text(encoding="utf-8")
        for alt, neu in ersetzungen:
            n = text.count(alt)
            if n != 1:
                probleme.append(f"Anker {alt!r} kommt {n}x vor (erwartet 1x) "
                                f"in {rel.as_posix()}")
                continue
            text = text.replace(alt, neu, 1)
        datei.write_text(text, encoding="utf-8")
    for rel in loeschen:
        (ziel / rel).unlink()
    return probleme


# ── Regel statt gepflegter Liste: jede angefasste Datei muss kopiert werden ──
fehlt_in_kopieren = set()
for _, patches, loeschen, _ in FAELLE:
    fehlt_in_kopieren |= ({*patches} | {*loeschen}) - set(KOPIEREN)
if fehlt_in_kopieren:
    print("Exit 2: diese Dateien werden angefasst, aber nicht kopiert: "
          + ", ".join(p.as_posix() for p in sorted(fehlt_in_kopieren)))
    sys.exit(2)

if not WAECHTER.exists():
    print(f"Exit 2: Waechter {WAECHTER} fehlt")
    sys.exit(2)
for rel in KOPIEREN:
    if not (WURZEL / rel).exists():
        print(f"Exit 2: {rel.as_posix()} fehlt im Arbeitsbaum")
        sys.exit(2)

VORHER = {rel: md5(WURZEL / rel) for rel in KOPIEREN}

# ── Positivkontrolle: der Waechter muss am ECHTEN Stand gruen sein ───────────
# Ohne gruenen Basislauf ist jedes ROT unten nicht deutbar – es koennte auch
# heissen, dass der Waechter immer faellt.
rc, ausgabe = lauf(WURZEL)
if rc != 0:
    print(f"Exit 2: Basislauf gegen den echten Arbeitsbaum ist NICHT gruen "
          f"(Exit {rc}). Ohne gruenen Basislauf ist die Gegenprobe nicht deutbar.")
    print(ausgabe[-2000:])
    sys.exit(2)
print("  \033[32m✓\033[0m Basislauf gegen den echten Arbeitsbaum ist gruen")

# ── Durchlauf ────────────────────────────────────────────────────────────────
daneben = []
kaputte_anker = []

with tempfile.TemporaryDirectory(prefix="gegen-webdav-a2wsgi-") as tmp:
    for i, (name, patches, loeschen, erwartet) in enumerate(FAELLE):
        kopie = Path(tmp) / f"stand-{i}"
        kopie.mkdir()
        probleme = baue_kopie(kopie, patches, loeschen)
        if probleme:
            kaputte_anker.append((name, probleme))
            print(f"  \033[31m✗\033[0m Sabotage nicht angewandt – {name}")
            for pr in probleme:
                print(f"      {pr}")
            continue
        rc, ausgabe = lauf(kopie)
        if rc == erwartet:
            print(f"  \033[32m✓\033[0m Exit {rc} (erwartet {erwartet}) – {name}")
        else:
            daneben.append((name, erwartet, rc, ausgabe))
            print(f"  \033[31m✗\033[0m Exit {rc}, ERWARTET {erwartet} – {name}")

# ── Der Arbeitsbaum ist unberuehrt (gemessen, nicht angenommen) ──────────────
verschoben = [rel.as_posix() for rel in KOPIEREN if md5(WURZEL / rel) != VORHER[rel]]

print(f"\n{'─' * 60}")
if kaputte_anker:
    print(f"ABBRUCH (Exit 2): {len(kaputte_anker)} Sabotage(n) liessen sich nicht "
          f"anwenden – ihre Anker treffen nicht mehr.")
    print("  Eine Sabotage, die nicht greift, ist kein Beweis fuer einen Waechter.")
    sys.exit(2)
if verschoben:
    print(f"ABBRUCH (Exit 2): der Arbeitsbaum hat sich veraendert: "
          f"{', '.join(verschoben)}")
    sys.exit(2)
print("  \033[32m✓\033[0m Arbeitsbaum unveraendert (md5 vor/nach gleich)")

if daneben:
    print(f"\nFAIL: {len(daneben)} von {len(FAELLE)} Faellen falsch bewertet – "
          f"der Waechter misst nicht, was er zu messen behauptet.\n")
    for name, erwartet, rc, ausgabe in daneben:
        print(f"── {name}\n   erwartet Exit {erwartet}, war Exit {rc}")
        print("   " + "\n   ".join(ausgabe.strip().splitlines()[-12:]) + "\n")
    sys.exit(1)

print(f"\nOK: alle {len(FAELLE)} Faelle richtig bewertet – der Waechter beisst.")
sys.exit(0)
