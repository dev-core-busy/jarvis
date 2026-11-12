#!/usr/bin/env python3
"""Gegenprobe: beisst Abschnitt D von tests/test_stt_fern.py (Zugangstoken)?

Sabotiert je EINE Zusage in backend/stt_fern.py bzw. backend/main.py und
erwartet Exit 1 mit mindestens einem FAIL. Der Waechter liest beide Dateien
an ihrem festen Ort (Import bzw. AST-Schnitt), deshalb wird IM Arbeitsbaum
gepatcht – mit den Schutzschranken aus dem Register:
  - gruener Basislauf vorher (ohne ihn ist keine Probe deutbar),
  - Sicherung auf Platte im HOME plus Laufmarke; bleibt die Marke nach einem
    Abbruch liegen, stellt der naechste Start zuerst die Sicherung her,
  - Byte-Gleichheit danach per md5, Lauf ohne Bytecode.
NIE in einem Sammellauf ueber tests/ mitlaufen lassen.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WAECHTER = REPO / "tests" / "test_stt_fern.py"
DATEIEN = ["backend/stt_fern.py", "backend/main.py"]
ABLAGE = Path.home() / ".cache" / "jarvis-gegenproben" / "stt_fern_token"
MARKE = ABLAGE / "LAUF_AKTIV"

PROBEN = [
    ("Token geht auch ueber ws:// hinaus", "backend/stt_fern.py",
     "    if token and verschluesselt(url):\n", "    if token:\n"),
    ("kein Authorization-Kopfsatz", "backend/stt_fern.py",
     '        return {"Authorization": "Bearer " + token}\n', "        return {}\n"),
    ("Kopfsaetze erreichen websockets.connect nicht", "backend/stt_fern.py",
     "                                  additional_headers=_kopf(url, token)) as ws:",
     "                                  ) as ws:"),
    ("Steuerzeichen im Token erlaubt", "backend/stt_fern.py",
     "    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token):", "    if False:"),
    ("gespeichertes Token geht an einen fremden Host", "backend/main.py",
     '        token = alt_token if _stt_fern.gleiches_ziel(_alt_url, url) else ""',
     "        token = alt_token"),
    ("Token mit ws:// wird angenommen", "backend/main.py",
     "    if token and not _stt_fern.verschluesselt(url):\n", "    if False:\n"),
    ("GET liefert den Wert", "backend/main.py",
     '"token_gesetzt": bool(_stt_fern.token_lesen(config))})',
     '"token_gesetzt": _stt_fern.token_lesen(config) or False})'),
    ("_transcribe_audio reicht das Token nicht durch", "backend/main.py",
     "            text = _stt_fern.transkribieren(filepath, _fern_url, language,\n"
     "                                            _stt_fern.token_lesen(config))",
     "            text = _stt_fern.transkribieren(filepath, _fern_url, language)"),
    ("Entfernen wirkungslos", "backend/main.py",
     '    entfernen = body.get("token_entfernen") is True', "    entfernen = False"),
    ("Token landet im Sicherheitsprotokoll", "backend/main.py",
     "token_gesetzt=bool(token), token_geaendert", "token_gesetzt=token, token_geaendert"),
]
_fehlt = {p[1] for p in PROBEN} - set(DATEIEN)
if _fehlt:
    print("ABBRUCH (Exit 2): Proben fassen ungesicherte Dateien an:", _fehlt)
    sys.exit(2)

ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def rueckstand_heilen():
    """Liegt die Marke noch (Abbruch mitten in einer Probe), zuerst zuruecklegen."""
    if not MARKE.exists():
        return
    for d in DATEIEN:
        s = ABLAGE / d.replace("/", "__")
        if s.exists():
            (REPO / d).write_bytes(s.read_bytes())
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgelegt.")


def lauf() -> tuple[int, int]:
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       env=ENV, timeout=300, cwd=REPO)
    return r.returncode, r.stdout.count("  FAIL ")


def main() -> int:
    rueckstand_heilen()
    rc, _f = lauf()
    if rc != 0:
        print(f"ABBRUCH (Exit 2): Basislauf nicht gruen (Exit {rc})")
        return 2
    print("Basislauf gruen.\n")
    sich = {d: (REPO / d).read_bytes() for d in DATEIEN}
    ABLAGE.mkdir(parents=True, exist_ok=True, mode=0o700)
    for d, b in sich.items():
        (ABLAGE / d.replace("/", "__")).write_bytes(b)
    MARKE.write_text(str(os.getpid()))
    treffer = 0
    try:
        for name, datei, alt, neu in PROBEN:
            text = sich[datei].decode("utf-8")
            if text.count(alt) != 1:
                print(f"  ???  {name} – Anker {text.count(alt)}x gefunden")
                continue
            (REPO / datei).write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                rc, fails = lauf()
            finally:
                (REPO / datei).write_bytes(sich[datei])
            beisst = rc == 1 and fails > 0
            treffer += beisst
            print(f"  {'OK  ' if beisst else 'ZAHN'} {name:<52} Exit {rc}, {fails} FAIL")
    finally:
        for d, b in sich.items():
            (REPO / d).write_bytes(b)
        gleich = all(md5((REPO / d).read_bytes()) == md5(b) for d, b in sich.items())
        if gleich:
            MARKE.unlink(missing_ok=True)
        print("\nWiederhergestellt, Byte-gleich:", gleich)
    print(f"{treffer}/{len(PROBEN)} Proben beissen")
    return 0 if treffer == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
