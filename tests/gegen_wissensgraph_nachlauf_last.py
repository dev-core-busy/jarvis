#!/usr/bin/env python3
"""Gegenproben zu ``test_wissensgraph_nachlauf_last.py``.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der Waechter sie
meldet (Exit 1 mit FAIL-Zeilen UND Bilanz – ein Abbruch ist kein Biss).
Mechanik wie die uebrigen Harnesse: Sicherung auf Platte, Laufmarke nimmt den
Rueckstand eines abgeschossenen Laufs beim naechsten Start zurueck, gruener
Basislauf ist Bedingung, jede angefasste Datei steht geprueft in DATEIEN,
gelaufen wird ohne Bytecode (Register: .pyc aus derselben Sekunde).

    python3 tests/gegen_wissensgraph_nachlauf_last.py
"""
from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-wg-nachlauf"
MARKE = ABL / "LAUF"

WG = "backend/wissensgraph.py"
WGX = "backend/wissensgraph_extraktion.py"
WW = "backend/wissensgraph_widerspruch.py"
WIKI = "backend/wissensgraph_wiki.py"
DATEIEN = [WG, WGX, WW, WIKI]
WAECHTER = [sys.executable, str(ROOT / "tests" / "test_wissensgraph_nachlauf_last.py")]
UMG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

PROBEN = [
    ("Schreiben wieder ueber json.dump (Python-Encoder)", WG,
     "        f.writelines(_json_teile(daten))\n",
     "        json.dump(daten, f, ensure_ascii=False)\n"),
    ("grosse Liste als ein einziges dumps (Speicher an der ganzen Liste)", WG,
     "    elif isinstance(daten, (list, tuple)) and len(daten) > block:\n",
     "    elif False:\n"),
    ("grosses dict als ein einziges dumps", WG,
     "    elif nur_str and len(daten) > block:\n", "    elif False:\n"),
    ("je Element ein dumps statt je Block", WG,
     "        for j in range(0, len(daten), block):\n            yield (\"\" if j == 0 else \", \") + json.dumps(list(daten[j:j + block])",
     "        for j in range(0, len(daten), 1):\n            yield (\"\" if j == 0 else \", \") + json.dumps(list(daten[j:j + 1])"),
    ("Block-Trenner ohne Leerzeichen", WG,
     "            yield (\"\" if j == 0 else \", \") + json.dumps(dict(",
     "            yield (\"\" if j == 0 else \",\") + json.dumps(dict("),
    ("Trenner ohne Leerzeichen", WG,
     '            yield ("" if i == 0 else ", ") + json.dumps(k, ensure_ascii=False) + ": "\n',
     '            yield ("" if i == 0 else ",") + json.dumps(k, ensure_ascii=False) + ": "\n'),
    ("Nicht-String-Schluessel elementweise", WG,
     "    nur_str = isinstance(daten, dict) and all(isinstance(k, str) for k in daten)\n",
     "    nur_str = isinstance(daten, dict) and all(isinstance(k, (str, int, float, type(None))) for k in daten)\n"),
    ("quellen_index ohne Cache", WG,
     "        if _index_cache is not None and _index_cache[0] == schluessel:\n",
     "        if False:\n"),
    ("Cache auch fuer frisch geaenderten Ordner", WG,
     "if time.time() - s.st_mtime > _INDEX_FRISCH_S else None", "if True else None"),
    ("Cache-Schluessel ohne Inode", WG,
     "        schluessel = (str(d), s.st_ino, s.st_mtime_ns)\n",
     "        schluessel = (str(d), s.st_mtime_ns)\n"),
    ("Cache gibt das eigene dict heraus", WG,
     "            return dict(_index_cache[1]), dict(_index_cache[2])\n",
     "            return _index_cache[1], _index_cache[2]\n"),
    ("Widerspruch: Umfang wieder je Knoten und Quelle", WW,
     '        q = {m: stand[m] for m in k["sources"] if m in umfang}\n',
     '        q = {m: stand[m] for m in k["sources"] if m in stand and wgx.im_umfang(m, gruppen or [])}\n'),
    ("Wiki: Umfang wieder je Knoten und Quelle", WIKI,
     "        im = [m for m in q if m in umfang]\n",
     "        im = [m for m in q if wgx.im_umfang(m, gruppen or [])]\n"),
    ("im_umfang_menge ignoriert die Gruppen", WGX,
     "    if gruppen and erlaubt:\n", "    if False:\n"),
    ("im_umfang_menge ohne Isolationsregel", WGX,
     "    erlaubt = [m for m in dict.fromkeys(manifeste) if wg._erlaubt(m)]\n",
     "    erlaubt = list(dict.fromkeys(manifeste))\n"),
    ("_vermerken liest die Ablage zweimal", WW,
     "        wg.widersprueche_schreiben(w, vorher_befunde=vorher)\n",
     "        wg.widersprueche_schreiben(w)\n"),
    ("_vermerken reicht den Stand NACH der Aenderung als vorher", WW,
     "        wg.widersprueche_schreiben(w, vorher_befunde=vorher)\n",
     '        wg.widersprueche_schreiben(w, vorher_befunde=w["befunde"])\n'),
    ("widersprueche_schreiben liest ohne Angabe nicht mehr selbst", WG,
     "        if vorher_befunde is None:\n            vorher_befunde = widersprueche_lesen()[\"befunde\"]\n",
     "        if vorher_befunde is None:\n            vorher_befunde = []\n"),
]


def _ablage(rel: str) -> Path:
    return ABL / rel.replace("/", "__")


def sichern() -> None:
    ABL.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, _ablage(rel))
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck() -> None:
    for rel in DATEIEN:
        if _ablage(rel).is_file():
            shutil.copy2(_ablage(rel), ROOT / rel)


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def aufraeumen() -> None:
    zurueck()
    if MARKE.exists():
        MARKE.unlink()


def lauf() -> tuple[int, str]:
    p = subprocess.run(WAECHTER, cwd=ROOT, capture_output=True, text=True, timeout=300, env=UMG)
    return p.returncode, p.stdout + p.stderr


def bewerte() -> tuple[bool, str]:
    rc, aus = lauf()
    bil = [z for z in aus.splitlines() if z.startswith("Ergebnis:")]
    if not bil:
        return False, f"ABGEBROCHEN rc={rc} (keine Bilanz)"
    fails = sum(1 for z in aus.splitlines() if "✗" in z)
    return rc == 1 and fails > 0, f"{fails} FAIL · {bil[-1]}"


def main() -> int:
    if MARKE.exists():
        print("⚠ Rueckstand eines frueheren Laufs gefunden – wird zurueckgenommen.")
        zurueck()
        MARKE.unlink()
    fremd = {p[1] for p in PROBEN} - set(DATEIEN)
    if fremd:
        print(f"ABBRUCH: Proben fassen Dateien ausserhalb der Sicherung an: {sorted(fremd)}")
        return 2
    rc, aus = lauf()
    if rc != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (rc={rc}) – keine Gegenprobe deutbar")
        print("\n".join(aus.splitlines()[-15:]))
        return 2
    sichern()
    atexit.register(aufraeumen)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(3))
    vorher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    stumm = 0
    for name, rel, alt, neu in PROBEN:
        p = ROOT / rel
        text = p.read_text(encoding="utf-8")
        if text.count(alt) != 1:
            print(f"  ? {name}: Anker {text.count(alt)}x gefunden – Probe trifft nicht")
            stumm += 1
            continue
        p.write_text(text.replace(alt, neu), encoding="utf-8")
        try:
            biss, info = bewerte()
        finally:
            shutil.copy2(_ablage(rel), p)
        print(f"  {'✓ beisst' if biss else '✗ STUMM '}  {name}  ({info})")
        stumm += 0 if biss else 1
    aufraeumen()
    nachher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    if nachher != vorher:
        print("ABBRUCH: Arbeitsbaum nach dem Lauf NICHT byte-gleich – Sicherung pruefen:", ABL)
        return 2
    print(f"\nErgebnis: {len(PROBEN) - stumm} von {len(PROBEN)} Proben beissen")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
