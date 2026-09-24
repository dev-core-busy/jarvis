#!/usr/bin/env python3
"""Gegenproben zu tests/test_bild_ablage.py – beisst der Waechter einzeln?

Jede Probe dreht GENAU EINE Zusage zurueck und erwartet FAIL. Eine Probe, die
nicht beisst, ist ein Testmangel – oder die Zusage existiert gar nicht; das ist
die erste Frage, nicht die letzte (Register).

    python3 tests/gegen_bild_ablage.py

Harness-Regeln, jede aus einem bezahlten Vorfall:
  * VOR jeder Probe auf Platte sichern, danach byte-genau (md5) zuruecklegen.
  * LAUFMARKE: bleibt sie nach einem `kill -9` liegen, nimmt der naechste Start
    den Rueckstand selbst zurueck – sonst stellt eine alte Sicherung fertige
    Arbeit zunichte.
  * Die Sicherungsliste wird als REGEL geprueft (jede von einer Probe angefasste
    Datei MUSS drin stehen), nicht gepflegt -> Exit 2.
  * Gemessen wird an der BILANZZEILE, nicht am Exit-Code allein.
  * Jede Ersetzung braucht eine Trefferkontrolle, sonst "beisst" sie scheinbar
    nicht, weil sie gar nicht griff.
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_bild_ablage.py"

DATEIEN = [
    "backend/bild_ablage.py",
    "backend/sandbox.py",
    "backend/main.py",
    "tests/test_bild_ablage.py",
]

SICHER = Path.home() / ".gegen-bildablage"
MARKE = SICHER / ".laeuft"


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern():
    SICHER.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        ziel = SICHER / rel.replace("/", "__")     # relativer PFAD als Schluessel,
        ziel.write_bytes((ROOT / rel).read_bytes())  # nicht der Basisname
    MARKE.write_text("1")


def zurueck(pruefen=True):
    for rel in DATEIEN:
        q = SICHER / rel.replace("/", "__")
        if not q.is_file():
            continue
        (ROOT / rel).write_bytes(q.read_bytes())
        if pruefen and md5(ROOT / rel) != md5(q):
            print(f"  ⚠ {rel} NICHT byte-gleich wiederhergestellt")
    MARKE.unlink(missing_ok=True)


def lauf():
    """Waechter fahren; gibt (fails, bilanz_vorhanden, rc) zurueck.

    ⚠ DER EXIT-CODE GEHOERT DAZU. Eine Probe kann auf **Exit 2** zielen
    ("konnte nicht laufen", etwa wenn die Sandkasten-Schranke greift) – wer nur
    FAIL-Zeilen zaehlt, haelt so einen Lauf fuer stumm. Genau so sah die Probe
    "Sandkasten-Schranke entfernt" beim ersten Durchgang aus.
    """
    r = subprocess.run([sys.executable, str(WAECHTER)],
                       capture_output=True, text=True, timeout=180, cwd=str(ROOT))
    m = re.search(r"Ergebnis:\s*(\d+)\s*OK,\s*(\d+)\s*FAIL", r.stdout)
    if not m:
        return None, False, r.returncode
    return int(m.group(2)), True, r.returncode


def patch(rel, alt, neu, anzahl=1):
    """Ersetzt mit TREFFERKONTROLLE."""
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    if s.count(alt) < 1:
        raise AssertionError(f"SABOTAGE TRIFFT NICHT in {rel}: {alt[:70]!r}")
    p.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


# ── Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen ───────────────
if MARKE.exists():
    print("⚠ Rueckstand eines abgebrochenen Laufs gefunden – nehme ihn zurueck")
    zurueck()

# ── REGEL: jede angefasste Datei muss in DATEIEN stehen ─────────────────────
PROBEN = []       # (label, rel, alt, neu)


def probe(label, rel, alt, neu):
    PROBEN.append((label, rel, alt, neu))


# ═════════════════════════════════════════════════════════════════════════════
# A – Sandbox-Sperre
probe("ALTSTAND: generated_images aus PRIVATE_DIRS",
      "backend/sandbox.py",
      'PRIVATE_DIRS = ("data/documents", "data/chats", "data/logs",\n'
      '                "data/generated_images")',
      'PRIVATE_DIRS = ("data/documents", "data/chats", "data/logs")')

probe("Haerte: generated_images DOCH in _APP_DENY_REL (Kontosperre!)",
      "backend/sandbox.py",
      '    "data/claude_subagent.json",\n',
      '    "data/claude_subagent.json",\n    "data/generated_images",\n')

probe("PRIVATE_MODE aufgeweicht (0755)",
      "backend/sandbox.py", "PRIVATE_MODE = 0o750", "PRIVATE_MODE = 0o755")

probe("generated_images in READ_ROOTS (Werkzeug-Weg geoeffnet)",
      "backend/sandbox.py",
      '    str(PROJECT_ROOT / "data" / "documents"),\n)',
      '    str(PROJECT_ROOT / "data" / "documents"),\n'
      '    str(PROJECT_ROOT / "data" / "generated_images"),\n)')

# B – Frist
probe("Vorgabe nicht 30 Tage",
      "backend/bild_ablage.py", "DEFAULT_TTL_DAYS = 30", "DEFAULT_TTL_DAYS = 90")

probe("unbrauchbarer ENV-Wert schaltet AB statt Vorgabe",
      "backend/bild_ablage.py",
      "        print(f\"[Bilder] JARVIS_GENIMG_TTL_DAYS={roh!r} ist keine Zahl – \"\n"
      "              f\"es gilt die Vorgabe {DEFAULT_TTL_DAYS} Tage\", flush=True)\n"
      "        return DEFAULT_TTL_DAYS",
      "        return 0")

probe("Deckel raus",
      "backend/bild_ablage.py", "return min(v, _MAX_TTL_DAYS)", "return v")

probe("ttl_days als KONSTANTE (eingefroren)",
      "backend/bild_ablage.py",
      "def ttl_days() -> int:", "TTL_KONST = 30\n\n\ndef _ttl_days_alt() -> int:")

# B – die vier Schranken
probe("Namensmuster breit (alles mit Endung)",
      "backend/bild_ablage.py",
      '_NAME_RE = re.compile(r"[0-9a-f]{32}\\.(?:" + "|".join(ENDUNGEN) + r")\\Z")',
      '_NAME_RE = re.compile(r".*\\.(?:" + "|".join(ENDUNGEN) + r")\\Z")')

probe("lstat -> stat (Symlink wird verfolgt)",
      "backend/bild_ablage.py", "st = p.lstat()", "st = p.stat()")

probe("Eigentuemer-Pruefung raus",
      "backend/bild_ablage.py",
      "            if st.st_uid != uid:\n                continue\n", "")

probe("Regulaere-Datei-Pruefung raus",
      "backend/bild_ablage.py",
      "            if not _stat.S_ISREG(st.st_mode):      # Symlink/Verzeichnis/FIFO\n"
      "                continue\n", "")

probe("rekursiv (Abstieg in Unterverzeichnisse)",
      "backend/bild_ablage.py",
      "        eintraege = list(ordner.iterdir())",
      "        eintraege = list(ordner.rglob('*'))")

probe("ttl=0 loescht trotzdem",
      "backend/bild_ablage.py",
      "    if tage <= 0:\n        return 0, 0", "    if tage < -1:\n        return 0, 0")

probe("mtime ignoriert (loescht alles)",
      "backend/bild_ablage.py",
      "            if st.st_mtime >= grenze:\n                continue\n", "")

# Drift-Schranken
probe("ENDUNGEN driften (svg dazu)",
      "backend/bild_ablage.py",
      'ENDUNGEN = ("png", "jpg", "jpeg", "gif", "webp")',
      'ENDUNGEN = ("png", "jpg", "jpeg", "gif", "webp", "svg")')

probe("IGNORECASE nachgetragen (weicht die 4. Schranke auf)",
      "backend/bild_ablage.py",
      '_NAME_RE = re.compile(r"[0-9a-f]{32}\\.(?:" + "|".join(ENDUNGEN) + r")\\Z")',
      '_NAME_RE = re.compile(r"[0-9a-f]{32}\\.(?:" + "|".join(ENDUNGEN) + r")\\Z",\n'
      '                      re.IGNORECASE)')

probe("bildordner NACHGEBAUT (harter Pfad, Drift)",
      "backend/bild_ablage.py",
      "    from backend.tools.image_gen import _IMG_DIR\n    return _IMG_DIR",
      "    return Path(__file__).parent.parent / \"data\" / \"generated_images\"")

# stats
probe("stats() gibt Dateinamen heraus",
      "backend/bild_ablage.py",
      '    return {"bilder": anzahl, "bytes": bytes_, "aeltestes": aeltestes,\n'
      '            "ttl_days": ttl_days()}',
      '    _n = [p.name for p in bildordner().iterdir()]\n'
      '    return {"bilder": anzahl, "bytes": bytes_, "aeltestes": aeltestes,\n'
      '            "ttl_days": ttl_days(), "namen": _n}')

# Verdrahtung
probe("Startup-Hook entfernt",
      "backend/main.py",
      "async def startup_bilder_retention():", "async def _aus_startup_bilder_retention():")

probe("Hook ohne to_thread (blockiert den Event-Loop)",
      "backend/main.py",
      "                    await asyncio.to_thread(_bildablage.cleanup)",
      "                    _bildablage.cleanup()")

probe("Frist VOR der Schleife geprueft (Umstellen wirkt erst nach Neustart)",
      "backend/main.py",
      "    async def _loop():\n"
      "        while True:\n"
      "            try:\n"
      "                if _bildablage.ttl_days() > 0:\n"
      "                    await asyncio.to_thread(_bildablage.cleanup)",
      "    async def _loop():\n"
      "        _an = _bildablage.ttl_days() > 0\n"
      "        while True:\n"
      "            try:\n"
      "                if _an:\n"
      "                    await asyncio.to_thread(_bildablage.cleanup)")

probe("Import in main.py entfernt",
      "backend/main.py",
      "from backend import bild_ablage as _bildablage",
      "from backend import bild_ablage as _bildablage_unbenutzt")

# Sandkasten-Schranke des Waechters selbst
# ⚠ DIESE PROBE ZIELT AUF **EXIT 2**, NICHT AUF EIN FAIL.
# Erste Fassung entfernte die SCHRANKE – das war gegenstandslos: sie greift nur,
# wenn das Umbiegen FEHLT, und das Umbiegen stand ja noch da. Richtig ist die
# umgekehrte Sabotage: das UMBIEGEN entfernen. Dann zeigt `bildordner()` auf den
# echten Ordner, und die Schranke MUSS vor jedem Zugriff mit Exit 2 abbrechen.
# Gefahrlos, weil sie VOR dem ersten Schreiben/Loeschen steht – und genau das
# belegt die Probe.
probe("WAECHTER: Sandkasten-Umbiegen entfernt -> Exit 2 muss greifen",
      "tests/test_bild_ablage.py",
      "ba.bildordner = lambda: _tmp\n", "", )


# ── REGEL statt gepflegter Liste ────────────────────────────────────────────
_fremd = {rel for _, rel, _, _ in PROBEN} - set(DATEIEN)
if _fremd:
    print(f"ABBRUCH: Proben fassen Dateien an, die nicht gesichert werden: {_fremd}")
    sys.exit(2)

# ── Basislauf MUSS gruen sein ───────────────────────────────────────────────
print("Basislauf …")
sichern()
basis_fails, basis_bilanz, basis_rc = lauf()
if not basis_bilanz:
    print(f"ABBRUCH: Basislauf ohne Bilanzzeile (rc={basis_rc})")
    zurueck()
    sys.exit(2)
if basis_fails != 0:
    print(f"ABBRUCH: Basislauf ist NICHT gruen ({basis_fails} FAIL) – "
          f"ohne gruene Basis ist keine Gegenprobe deutbar")
    zurueck()
    sys.exit(2)
print(f"  Basis gruen (0 FAIL)\n")

beissen = stumm = 0
for label, rel, alt, neu in PROBEN:
    try:
        patch(rel, alt, neu)
    except AssertionError as e:
        print(f"  ⚠ PROBEN-MANGEL  {label}\n      {e}")
        stumm += 1
        zurueck(pruefen=False)
        sichern()
        continue
    fails, bilanz, rc = lauf()
    zurueck()
    sichern()
    if rc == 2:
        # "Konnte nicht laufen" ist bei einer Schranken-Probe der GEWOLLTE
        # Ausgang und muss von "stumm" unterscheidbar sein.
        print(f"  beisst (Exit 2)   {label}")
        beissen += 1
    elif not bilanz:
        print(f"  ⚠ OHNE BILANZ    {label}  (Waechter abgebrochen statt FAIL, rc={rc})")
        stumm += 1
    elif fails and fails > 0:
        print(f"  beisst ({fails} FAIL)  {label}")
        beissen += 1
    else:
        print(f"  ⚠ STUMM          {label}")
        stumm += 1

zurueck()
print(f"\nErgebnis: {beissen} von {len(PROBEN)} Proben beissen, {stumm} stumm")
# Kontrolle, dass der Arbeitsbaum sauber zurueckliegt
for rel in DATEIEN:
    q = SICHER / rel.replace("/", "__")
    if q.is_file() and md5(ROOT / rel) != md5(q):
        print(f"  ⚠ RUECKSTAND in {rel}")
sys.exit(1 if stumm else 0)
