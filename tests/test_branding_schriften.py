#!/usr/bin/env python3
"""Tests fuer den Schrift-Upload im Branding-Reiter (backend/branding_schriften.py).

AUSGANGSPUNKT: Die Office-Vorlagen verlangen die CI-Schrift, auf dem Server
ist sie nicht installiert – der PDF-Export setzt eine Ersatzschrift. Jetzt
laedt der Administrator die Schriftdatei hoch, und fontconfig (das auch
LibreOffice benutzt) findet sie.

Gemessen wird die WIRKUNG, nicht die Ablage: eine Pruefschrift mit einem
Familiennamen, den es sonst nirgends gibt, wird vor dem Upload von
``fc-match`` NICHT gefunden und danach schon – aus dem Schriftordner.
Die Pruefschrift entsteht hier aus DejaVu Sans, deren name-Tabelle neu
geschrieben wird (fontTools ist nicht auf jedem Server installiert).

Hermetisch: Schriftordner, XDG_CONFIG_HOME und XDG_CACHE_HOME liegen in einem
Wegwerf-Verzeichnis; die fontconfig-Konfiguration des Aufrufers bleibt
unberuehrt.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen (fontconfig-Werkzeuge
oder Ausgangsschrift fehlen, Pruefschrift nicht lesbar).

Lauf:  python3 tests/test_branding_schriften.py
"""

import ast
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = 0
_fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  ✓ {text}")
    else:
        _fail += 1
        print(f"  ✗ {text}" + (f" – {detail}" if detail else ""))


def abbruch(grund):
    print(f"ABBRUCH (konnte nicht laufen): {grund}")
    sys.exit(2)


for werkzeug in ("fc-scan", "fc-match", "fc-cache"):
    if not shutil.which(werkzeug):
        abbruch(f"{werkzeug} fehlt (Paket fontconfig)")

QUELLE = None
for kandidat in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/TTF/DejaVuSans.ttf"):
    if Path(kandidat).is_file():
        QUELLE = Path(kandidat)
        break
if QUELLE is None:
    abbruch("Ausgangsschrift DejaVuSans.ttf nicht gefunden (Paket fonts-dejavu-core)")

TMP = Path(tempfile.mkdtemp(prefix="jarvis_schriften_"))
# VOR dem ersten fontconfig-Aufruf: die Unterprozesse erben die Umgebung.
os.environ["XDG_CONFIG_HOME"] = str(TMP / "config")
os.environ["XDG_CACHE_HOME"] = str(TMP / "cache")

FAMILIE = "Jarvis Pruefschrift 55 Roman"


def _name_tabelle(familie: str) -> bytes:
    """Minimale name-Tabelle (Windows, Unicode, en-US): Familie, Stil, Name, PS-Name."""
    eintraege = [(1, familie), (2, "Regular"), (4, familie),
                 (6, re.sub(r"[^A-Za-z0-9-]", "", familie))]
    daten = b""
    saetze = b""
    for name_id, text in eintraege:
        roh = text.encode("utf-16-be")
        saetze += struct.pack(">HHHHHH", 3, 1, 0x409, name_id, len(roh), len(daten))
        daten += roh
    return struct.pack(">HHH", 0, len(eintraege), 6 + 12 * len(eintraege)) + saetze + daten


def pruefschrift(familie: str) -> bytes:
    """DejaVu Sans mit neuer name-Tabelle (angehaengt, Verzeichnis umgebogen).

    Pruefsummen werden nicht nachgerechnet – FreeType prueft sie nicht."""
    roh = bytearray(QUELLE.read_bytes())
    anzahl = struct.unpack(">H", roh[4:6])[0]
    neu = _name_tabelle(familie)
    while len(roh) % 4:
        roh += b"\x00"
    versatz = len(roh)
    for i in range(anzahl):
        eintrag = 12 + 16 * i
        if roh[eintrag:eintrag + 4] == b"name":
            struct.pack_into(">II", roh, eintrag + 8, versatz, len(neu))
            break
    else:
        abbruch("Ausgangsschrift ohne name-Tabelle")
    return bytes(roh + neu)


def fc_familien(pfad: Path) -> str:
    proc = subprocess.run(["fc-scan", "--format", "%{family}", str(pfad)],
                          capture_output=True, text=True, timeout=20)
    return proc.stdout


from backend import branding_schriften as bs  # noqa: E402

bs.FONT_DIR = TMP / "data" / "branding" / "fonts"

# ── 0. Positivkontrolle ─────────────────────────────────────────────────────
print("\n0. Positivkontrolle")
PRUEF = pruefschrift(FAMILIE)
probe = TMP / "probe.ttf"
probe.write_bytes(PRUEF)
if FAMILIE not in fc_familien(probe):
    abbruch(f"Pruefschrift nicht lesbar – fc-scan: {fc_familien(probe)!r}")
probe.unlink()
vorher = bs.abdeckung([FAMILIE])
if not (vorher and vorher[0].get("gemessen")):
    abbruch("fc-match liefert keine Messung")
pruefe(vorher[0]["gefunden"] is False,
       "vor dem Upload findet fontconfig die Pruefschrift NICHT", repr(vorher))
pruefe(bool(vorher[0]["ersatz"]), "…und nennt die Ersatzschrift", repr(vorher))

# ── 1. Abgewiesene Uploads ──────────────────────────────────────────────────
print("\n1. Abgewiesene Uploads")
ok, fehler, _ = bs.pruefen(PRUEF, "schrift.woff2")
pruefe(not ok and "nicht erlaubt" in fehler, "fremde Endung abgewiesen", fehler)
ok, fehler, _ = bs.pruefen(b"", "leer.ttf")
pruefe(not ok and "leer" in fehler, "leere Datei abgewiesen", fehler)
ok, fehler, _ = bs.pruefen(b"%PDF-1.7 ....", "umbenannt.ttf")
pruefe(not ok and "Kennung" in fehler, "umbenannte PDF-Datei abgewiesen (Inhalt zaehlt)", fehler)
alt = bs.MAX_BYTES
bs.MAX_BYTES = 100
ok, fehler, _ = bs.pruefen(PRUEF, "gross.ttf")
bs.MAX_BYTES = alt
pruefe(not ok and "zu gross" in fehler, "Groessengrenze greift", fehler)
ok, fehler, _ = bs.speichern(b"OTTO" + b"\x00" * 200, "kaputt.otf")
pruefe(not ok and "keine lesbare Schrift" in fehler,
       "Datei mit Kennung, aber ohne Schriftinhalt abgewiesen", fehler)
uebrig = sorted(p.name for p in bs.FONT_DIR.parent.rglob("*") if p.is_file())
pruefe(not any(n.startswith("kaputt") or n.startswith(".upload-") for n in uebrig),
       "abgewiesene Datei bleibt nicht liegen", repr(uebrig))

# ── 2. Upload und Wirkung ───────────────────────────────────────────────────
print("\n2. Upload und Wirkung")
ok, fehler, infos = bs.speichern(PRUEF, "../../Contoso Sans/55 Roman.TTF")
pruefe(ok, "Pruefschrift angenommen", fehler)
name = infos.get("name", "")
pruefe(name == "55_Roman.ttf", "Dateiname bereinigt (nur Basisname, Endung klein)", name)
pruefe((bs.FONT_DIR / name).is_file(), "Datei liegt im Schriftordner")
ausserhalb = [p for p in TMP.rglob("*.ttf") if bs.FONT_DIR not in p.parents]
pruefe(not ausserhalb, "nichts ausserhalb des Schriftordners abgelegt", repr(ausserhalb))
pruefe(any(FAMILIE in s.get("familien", []) for s in infos.get("schnitte", [])),
       "Antwort nennt die erkannte Familie", repr(infos.get("schnitte")))

conf = Path(os.environ["XDG_CONFIG_HOME"]) / "fontconfig" / "conf.d" / "60-jarvis-branding.conf"
pruefe(conf.is_file(), "fontconfig-Eintrag beim Dienstbenutzer angelegt", str(conf))
pruefe(conf.is_file() and f"<dir>{bs.FONT_DIR}</dir>" in conf.read_text(),
       "…mit dem Schriftordner als <dir>")

nachher = bs.abdeckung([FAMILIE])
pruefe(nachher[0]["gefunden"] is True,
       "NACH dem Upload findet fontconfig die Pruefschrift (Wirkung)", repr(nachher))
pruefe(nachher[0].get("eigene") is True and nachher[0].get("datei") == name,
       "…und zwar die hochgeladene Datei", repr(nachher))
pruefe("/" not in nachher[0].get("datei", "/"),
       "Antwort verraet keinen Serverpfad", nachher[0].get("datei"))

eintraege = bs.liste()
pruefe([e["name"] for e in eintraege] == [name], "Liste zeigt die Schrift", repr(eintraege))
pruefe(bool(eintraege) and any(FAMILIE in s.get("familien", [])
                               for s in eintraege[0].get("schnitte", [])),
       "Liste nennt die Schnitte")

z = bs.zustand([FAMILIE])
pruefe(set(z) == {"fonts", "vorlagen", "fontconfig"} and z["fontconfig"] is True,
       "Zustand fuer den Reiter vollstaendig", repr(sorted(z)))

# Ruecksicherung: Eintrag fehlt, Dateien liegen da -> sicherstellen() heilt
conf.unlink()
pruefe(bs.sicherstellen() and conf.is_file(), "fehlender Eintrag wird wiederhergestellt")

# ── 3. Entfernen ────────────────────────────────────────────────────────────
print("\n3. Entfernen")
# Koeder AUSSERHALB des Schriftordners: ohne Pfadpruefung wuerde "../koeder.ttf"
# ihn loeschen (ein nicht existierendes Ziel bewiese nichts).
koeder = bs.FONT_DIR.parent / "koeder.ttf"
koeder.write_bytes(PRUEF)
for boese in ("../koeder.ttf", str(koeder), ".versteckt.ttf", "schrift.pdf", ""):
    ok, fehler = bs.entfernen(boese)
    pruefe(not ok, f"Name {boese!r} abgewiesen", fehler)
pruefe(koeder.is_file(), "Datei ausserhalb des Schriftordners unangetastet")
koeder.unlink()
pruefe((bs.FONT_DIR / name).is_file(), "…und die Schrift ist noch da")
ok, fehler = bs.entfernen("gibtsnicht.ttf")
pruefe(not ok and "nicht gefunden" in fehler, "unbekannte Schrift: nicht gefunden", fehler)
ok, fehler = bs.entfernen(name)
pruefe(ok and not (bs.FONT_DIR / name).exists(), "Schrift entfernt", fehler)
pruefe(bs.abdeckung([FAMILIE])[0]["gefunden"] is False,
       "danach findet fontconfig sie nicht mehr")

# ── 4. Endpunkte in backend/main.py (Syntaxbaum) ────────────────────────────
print("\n4. Endpunkte")
baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
routen = {}
startup = {}
for knoten in ast.walk(baum):
    if not isinstance(knoten, ast.AsyncFunctionDef):
        continue
    for deko in knoten.decorator_list:
        if not (isinstance(deko, ast.Call) and isinstance(deko.func, ast.Attribute)):
            continue
        arg = deko.args[0].value if deko.args and isinstance(deko.args[0], ast.Constant) else None
        if deko.func.attr in ("get", "post", "delete") and isinstance(arg, str):
            routen[(deko.func.attr, arg)] = knoten
        if deko.func.attr == "on_event" and arg == "startup":
            startup[knoten.name] = knoten


def _geschuetzt(fn):
    for vorgabe in fn.args.defaults + fn.args.kw_defaults:
        if (isinstance(vorgabe, ast.Call) and getattr(vorgabe.func, "id", "") == "Depends"
                and vorgabe.args and getattr(vorgabe.args[0], "id", "") == "require_local_auth"):
            return True
    return False


for methode, pfad in (("get", "/api/branding/fonts"), ("post", "/api/branding/font"),
                      ("delete", "/api/branding/font")):
    fn = routen.get((methode, pfad))
    pruefe(fn is not None, f"{methode.upper()} {pfad} vorhanden")
    pruefe(fn is not None and _geschuetzt(fn), f"…nur mit Anmeldung (require_local_auth)")
heiler = startup.get("startup_branding_schriften")
pruefe(heiler is not None and any(
    isinstance(k, ast.Attribute) and k.attr == "sicherstellen" for k in ast.walk(heiler)),
    "Dienststart zieht den fontconfig-Eintrag nach")

# ── 5. Ablage nie im Repo ───────────────────────────────────────────────────
print("\n5. Ablage")
import importlib  # noqa: E402
importlib.reload(bs)
rel = bs.FONT_DIR.relative_to(ROOT).as_posix()
proc = subprocess.run(["git", "check-ignore", "-q", rel + "/probe.ttf"], cwd=ROOT,
                      capture_output=True, timeout=20)
if proc.returncode == 128:
    print("  (git nicht verfuegbar – Pruefung uebersprungen)")
else:
    pruefe(proc.returncode == 0, f"{rel} ist gitignored (lizenzierte Schrift nie im Repo)")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'=' * 60}\nErgebnis: {_ok}/{_ok + _fail} Pruefungen bestanden")
sys.exit(1 if _fail else 0)
