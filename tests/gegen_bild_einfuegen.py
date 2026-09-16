#!/usr/bin/env python3
"""Gegenproben zu den Waechtern von 2026-09-16 (Bild-Anhaenge in /chat).

Ein Waechter, der nicht beisst, ist ein TESTMANGEL - kein Beweis. Jede Probe
dreht GENAU EINEN Teil des Fixes zurueck und erwartet, dass der zugehoerige
Waechter das meldet.

⚠ DER HARNESS SICHERT AUF PLATTE und nimmt einen Rueckstand beim naechsten
Start selbst zurueck: ein abgeschossener Lauf (Timeout, kill) liesse den
Arbeitsbaum sonst SABOTIERT liegen, und die naechste Messung meldete Fehler,
die es nicht gibt (Register, mehrfach bezahlt).

    python3 tests/gegen_bild_einfuegen.py
"""
import atexit
import hashlib
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-bild-einfuegen"   # 0700, NICHT /tmp (1777)
MARKE = ABLAGE / "laeuft"

CHAT = ROOT / "frontend/js/chat.js"
MAIN = ROOT / "backend/main.py"
WJS = ROOT / "tests/test_chat_bild_einfuegen.js"
WPY = ROOT / "tests/test_anhang_bild_mime.py"

DATEIEN = [CHAT, MAIN]


def _ziel(p: Path) -> Path:
    # Schluessel ist der RELATIVE PFAD, nicht der Basisname: zwei gleichnamige
    # Dateien wuerden einander sonst still ueberschreiben (Register).
    return ABLAGE / p.relative_to(ROOT).as_posix().replace("/", "__")


def sichern() -> None:
    ABLAGE.mkdir(mode=0o700, parents=True, exist_ok=True)
    for p in DATEIEN:
        shutil.copy2(p, _ziel(p))
    MARKE.write_text("1")


def zurueck() -> None:
    for p in DATEIEN:
        q = _ziel(p)
        if q.exists():
            shutil.copy2(q, p)
    if MARKE.exists():
        MARKE.unlink()


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf(waechter: Path):
    if waechter.suffix == ".js":
        r = subprocess.run(["node", str(waechter)], capture_output=True, text=True,
                           timeout=180, cwd=ROOT)
    else:
        r = subprocess.run([sys.executable, str(waechter)], capture_output=True,
                           text=True, timeout=180, cwd=ROOT)
    aus = r.stdout + r.stderr
    n = aus.count("✗")
    # Eine fehlende Bilanzzeile heisst ABGEBROCHEN - das ist kein Beissen.
    bilanz = "Ergebnis:" in aus
    return n, bilanz, aus


def probe(titel: str, datei: Path, alt: str, neu: str, waechter: Path) -> bool:
    zurueck()
    s = datei.read_text(encoding="utf-8")
    # Trefferkontrolle: eine Ersetzung ohne assert ist kein Messwert - die
    # Probe "beisst" sonst scheinbar nicht, weil sie gar nicht gegriffen hat.
    if s.count(alt) < 1:
        print(f"  ⚠ {titel}: ANKER NICHT GEFUNDEN – Probe verfehlt ihr Ziel")
        return False
    datei.write_text(s.replace(alt, neu, 1), encoding="utf-8")
    n, bilanz, aus = lauf(waechter)
    zurueck()
    if not bilanz:
        print(f"  ⚠ {titel}: der Waechter BRACH AB (keine Bilanz) – das zaehlt nicht als Treffer")
        return False
    if n > 0:
        print(f"  ✓ {titel}: beisst ({n} FAIL)")
        return True
    print(f"  ✗ {titel}: BEISST NICHT – der Waechter ist an dieser Stelle blind")
    return False


PROBEN = [
    # ── Client ────────────────────────────────────────────────────────────
    ("Byte-Erkennung ausgebaut (der gemeldete Zustand)", CHAT,
     "const mimeEff = _bildMimeAusBytes(b64) || mime;",
     "const mimeEff = mime;", WJS),
    ("Byte-Erkennung greift auch bei Nicht-Bildern", CHAT,
     "        return '';\n    }\n\n    async function addFiles",
     "        return 'image/png';\n    }\n\n    async function addFiles", WJS),
    ("Einfuege-Zuhoerer entfernt", CHAT,
     "msgInput.addEventListener('paste'", "msgInput.addEventListener('paste_aus'", WJS),
    ("Einfuegen faengt auch reinen Text ab", CHAT,
     "if (dateien.length === 0) return;   // reiner Text: der Browser macht es selbst\n            e.preventDefault();",
     "e.preventDefault();\n            if (dateien.length === 0) return;", WJS),
    ("namenloses Bild bekommt keinen Namen", CHAT,
     "if (f.name) { dateien.push(f); continue; }", "dateien.push(f); continue;", WJS),
    ("Drop auf dem Eingabefeld entfernt", CHAT,
     "msgInput.addEventListener('drop'", "msgInput.addEventListener('drop_aus'", WJS),
    ("dragover faengt auch gezogenen Text ab", CHAT,
     "if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) e.preventDefault();",
     "e.preventDefault();", WJS),
    ("Einfuegen baut den Anhang selbst (zweiter Weg)", CHAT,
     "await addFiles(dateien);\n        });",
     "_pendingAttachments.push({name:'x',mime_type:'image/png',data:'x',type:'image'});\n        });", WJS),
    # ── Server ────────────────────────────────────────────────────────────
    ("Server-Korrektur ausgebaut", MAIN,
     "                    _magisch = _bild_mime_aus_bytes(_data)",
     "                    _magisch = \"\"", WPY),
    ("Server-Korrektur steht HINTER der Bild-Weiche", MAIN,
     "                if _mime not in _ALLOWED_IMG_MIME:\n                    _magisch = _bild_mime_aus_bytes(_data)\n                    if _magisch:\n                        _mime = _magisch\n",
     "", WPY),
    ("Helfer ohne eigenen base64-Import (still wirkungslos)", MAIN,
     "    import base64 as _b64m\n", "", WPY),
    ("Byte-Tabelle zieht ZIP mit an sich", MAIN,
     '    (b"BM", "image/bmp"),', '    (b"BM", "image/bmp"),\n    (b"PK\\x03\\x04", "image/png"),', WPY),
    ("zu grosses Bild verschwindet wieder wortlos", MAIN,
     '                    else:\n                        # SICHTBAR melden statt wortlos ueberspringen: bis hier',
     '                    elif False:\n                        # SICHTBAR melden statt wortlos ueberspringen: bis hier', WPY),
]


def main() -> int:
    if MARKE.exists():
        print("⚠ Rueckstand eines abgeschossenen Laufs gefunden – wird zurueckgenommen.")
        zurueck()
    # Ohne gruene Basis ist KEINE Gegenprobe deutbar.
    print("=== Basislauf (muss gruen sein) ===")
    for w in (WJS, WPY):
        n, bilanz, aus = lauf(w)
        if n or not bilanz:
            print(f"  ✗ {w.name} ist NICHT gruen – Abbruch, Gegenproben waeren wertlos")
            print(aus[-1500:])
            return 2
        print(f"  ✓ {w.name}: gruen")

    vorher = {p: md5(p) for p in DATEIEN}
    sichern()
    atexit.register(zurueck)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *a: (zurueck(), sys.exit(130)))

    print("\n=== Gegenproben ===")
    treffer = sum(1 for t, d, a, n, w in PROBEN if probe(t, d, a, n, w))
    zurueck()

    print("\n=== Ausgangszustand ===")
    heil = all(md5(p) == vorher[p] for p in DATEIEN)
    print(("  ✓ alle Dateien byte-gleich wiederhergestellt" if heil
           else "  ✗ RUECKSTAND im Arbeitsbaum – von Hand pruefen!"))
    print(f"\nErgebnis: {treffer} von {len(PROBEN)} Proben beissen")
    return 0 if (treffer == len(PROBEN) and heil) else 1


if __name__ == "__main__":
    sys.exit(main())
