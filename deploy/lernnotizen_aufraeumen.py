#!/usr/bin/env python3
"""Lernnotizen ohne Wissensgehalt entfernen - nach DEMSELBEN Kriterium,
das `learning._hat_substanz()` kuenftig beim Schreiben anwendet.

⚠ DIE FUNKTION WIRD AUS learning.py GELADEN, NICHT NACHGEBAUT. Eine zweite
Fassung liefe beim naechsten Feinschliff auseinander - und dann loescht das
Aufraeumen etwas anderes, als der Filter durchlaesst (dieselbe Lehre wie bei
`reclassify_violations.py`, das seine Regeln ebenfalls aus dem Quelltext holt).

Hintergrund: von 71 Lernnotizen auf DEV hatten 53 als kompletten Inhalt das Wort
"Standardantwort" (15 Zeichen). Sie entstehen bei Auftraegen ohne Wissensgehalt
und standen alle im FAISS-Index, also in jeder Wissenssuche.

    python3 deploy/lernnotizen_aufraeumen.py            # Trockenlauf (Vorgabe)
    python3 deploy/lernnotizen_aufraeumen.py --anwenden # loescht, mit Sicherung

Der Trockenlauf ist die Vorgabe: Loeschen ist nicht umkehrbar.
"""
import argparse
import ast
import io
import os
import shutil
import sys
import tarfile
import time
from pathlib import Path

ZUHAUSE = Path(os.environ.get("JARVIS_DIR", "/opt/jarvis"))


def _hat_substanz_laden():
    """`_hat_substanz` aus learning.py schneiden - ohne das Modul zu importieren
    (das zieht config, LLM-Provider und FAISS mit)."""
    q = io.open(ZUHAUSE / "backend/learning.py", encoding="utf-8").read()
    baum = ast.parse(q)
    teile = [n for n in baum.body
             if (isinstance(n, ast.FunctionDef) and n.name == "_hat_substanz")
             or (isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "MIN_FAKTEN_ZEICHEN")]
    if len(teile) != 2:
        print("ABBRUCH: _hat_substanz nicht gefunden - ohne das Kriterium wird "
              "hier nichts geloescht.")
        sys.exit(2)
    ns = {}
    exec(compile(ast.Module(body=teile, type_ignores=[]), "<schnitt>", "exec"), ns)
    return ns["_hat_substanz"]


def faktenteil(text: str) -> str:
    """Alles nach der Datum-Zeile - der Kopf ist keine Aussage."""
    teile = text.split("\n", 3)
    return (teile[3] if len(teile) > 3 else "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anwenden", action="store_true",
                    help="wirklich loeschen (sonst nur zeigen)")
    args = ap.parse_args()

    hat_substanz = _hat_substanz_laden()
    wurzel = ZUHAUSE / "data/knowledge/learned"
    if not wurzel.is_dir():
        print(f"Kein Verzeichnis {wurzel}")
        return 2

    weg, bleibt = [], []
    for p in sorted(wurzel.rglob("*.md")):
        try:
            inhalt = faktenteil(p.read_text(encoding="utf-8"))
        except OSError as e:
            print(f"  nicht lesbar, bleibt: {p} ({e})")
            bleibt.append(p)
            continue
        (bleibt if hat_substanz(inhalt) else weg).append(p)

    print(f"Lernnotizen: {len(weg) + len(bleibt)}")
    print(f"  ohne Wissensgehalt : {len(weg)}")
    print(f"  bleiben            : {len(bleibt)}")
    if weg:
        print("\n  Beispiele (erste 5):")
        for p in weg[:5]:
            t = faktenteil(p.read_text(encoding='utf-8', errors='replace'))
            print(f"    {p.relative_to(wurzel)}  {len(t):4d} Z.  {t[:50]!r}")
    if not args.anwenden:
        print("\nTROCKENLAUF - nichts geloescht. Mit --anwenden ausfuehren.")
        return 0
    if not weg:
        print("\nNichts zu tun.")
        return 0

    # ⚠ SICHERUNG VOR DEM LOESCHEN. Ein Aufraeumskript ohne Rueckweg ist ein
    # Datenverlust mit freundlichem Namen.
    marke = time.strftime("%Y%m%d-%H%M%S")
    sicherung = ZUHAUSE / f"data/knowledge/learned-muell-{marke}.tgz"
    with tarfile.open(sicherung, "w:gz") as tar:
        for p in weg:
            tar.add(p, arcname=str(p.relative_to(wurzel)))
    n_gesichert = len(tarfile.open(sicherung).getnames())
    if n_gesichert != len(weg):
        print(f"ABBRUCH: Sicherung unvollstaendig ({n_gesichert} von {len(weg)})")
        return 2
    print(f"\nGesichert: {n_gesichert} Dateien -> {sicherung}")

    entfernt = 0
    for p in weg:
        try:
            p.unlink()
            entfernt += 1
        except OSError as e:
            print(f"  nicht geloescht: {p} ({e})")
    print(f"Geloescht: {entfernt}")
    print("\n⚠ JETZT EINEN REINDEX FAHREN - sonst stehen die Chunks weiter im\n"
          "  FAISS-Index und tauchen in jeder Wissenssuche auf:\n"
          "  POST /api/knowledge/reindex   (oder die Kachel in /settings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
