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

Seit 2026-09-07 raeumt es zusaetzlich DUBLETTEN auf - Notizen, die dieselbe
Aufgabe ein zweites Mal gelernt haben. Auf DEV waren 9 der 10 Notizen derselbe
Auftrag, entstanden in SECHS MINUTEN aus wiederholten Testlaeufen. Das
Kriterium ist dasselbe, das `learning.bereits_gelernt()` kuenftig beim
Schreiben anwendet: gleiche Aufgabe = nicht noch einmal. **Behalten wird die
AELTESTE** - genau die, die der neue Filter durchgelassen haette.

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


def ueberschrift(text: str) -> str:
    """Die Aufgabe aus der ersten Zeile - `# Gelernt: <Aufgabe>`.

    ⚠ NICHT ueber `learning.task_kennung()`: die vorhandenen Dateien tragen
    keine Kennung im Namen, und die Ueberschrift ist eine GEKUERZTE, von
    Sonderzeichen befreite Fassung der Aufgabe. Fuer die Frage "sind das
    dieselben zwei Notizen?" ist genau sie der Vergleichsschluessel.
    """
    erste = (text.splitlines() or [""])[0]
    if not erste.startswith("# Gelernt:"):
        return ""          # Konsolidat und Fremdformate gruppieren nicht
    return " ".join(erste[len("# Gelernt:"):].split()).lower()


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

    weg, bleibt, fremd = [], [], []
    for p in sorted(wurzel.rglob("*.md")):
        # ⚠ NUR conv_*.md - das sind die Dateien des Auto-Learnings, fuer die
        # `_hat_substanz` gebaut ist. `feedback_*.md` schreibt main.py aus einer
        # Benutzer-Bewertung; sie haben ein voellig anderes Format ("## Urspruengliche
        # Antwort", "## Was war schlecht") und faellen deshalb durch die
        # Fakten-Struktur-Pruefung - obwohl sie 3.000 Zeichen echtes Wissen tragen.
        # AUF ECHT WAERE DAS DER SCHADEN GEWESEN: der Trockenlauf dort meldete
        # 5 solcher Dateien als "ohne Wissensgehalt". `knowledge_compactor.py`
        # nimmt sie aus demselben Grund aus ("feedback_* bleibt unberuehrt").
        if not p.name.startswith("conv_"):
            fremd.append(p)
            continue
        try:
            inhalt = faktenteil(p.read_text(encoding="utf-8"))
        except OSError as e:
            print(f"  nicht lesbar, bleibt: {p} ({e})")
            bleibt.append(p)
            continue
        (bleibt if hat_substanz(inhalt) else weg).append(p)

    # ── Dubletten: dieselbe Aufgabe ein zweites Mal gelernt ──────────────
    # Behalten wird die AELTESTE je Aufgabe - genau die, die
    # `learning.bereits_gelernt()` durchgelassen haette; alle spaeteren
    # waeren gar nicht erst entstanden.
    gruppen: dict[str, list[Path]] = {}
    for p in bleibt:
        try:
            k = ueberschrift(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if k:
            gruppen.setdefault(k, []).append(p)
    dublett = []
    for k, gr in gruppen.items():
        if len(gr) > 1:
            gr.sort(key=lambda x: x.stat().st_mtime)      # aelteste zuerst
            dublett.extend(gr[1:])
    if dublett:
        dset = set(dublett)
        bleibt = [p for p in bleibt if p not in dset]
        weg.extend(dublett)

    print(f"Lernnotizen: {len(weg) + len(bleibt) + len(fremd)}")
    print(f"  conv_*  ohne Wissensgehalt : {len(weg) - len(dublett)}")
    print(f"  conv_*  Dubletten (gleiche Aufgabe, aeltere bleibt): {len(dublett)}")
    print(f"  conv_*  bleiben            : {len(bleibt)}")
    print(f"  andere Gattungen (unberuehrt, z.B. feedback_*): {len(fremd)}")
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
