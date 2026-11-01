#!/usr/bin/env python3
"""Fertigen Wissensgraphen eines anderen Servers uebernehmen (Option C des
Vergleichsberichts DEV/ECHT, 2026-11-01).

WARUM: Der Aufbau kostet auf dem Bestand ≈ 13 h Modellzeit (≥ 8.482 Aufrufe).
Liegt auf einem zweiten Server DERSELBE Wissensbestand (1:1 kopiert, gleiche
Zeitstempel), muss er dort nicht noch einmal entstehen – die Ablage
(``data/graph/quellen``) gilt, solange jede Quelldatei dieselbe mtime hat.

Das Skript laeuft auf dem ZIELSERVER, als Dienstbenutzer, gegen einen
entpackten ``data/graph``-Ordner des Quellservers. Es importiert bewusst
NICHTS aus ``backend`` – der echte ``backend.config`` schreibt beim Import die
Live-``settings.json`` zurueck (Register), und ein Uebernahme-Werkzeug darf
keinen Nebenweg in die Konfiguration haben.

    pruefen     <quelle>                 nur messen: passen die Zeitstempel?
    einspielen  <quelle> --uebernehmen   Quellen + Entscheidungen uebernehmen

Uebernommen werden NUR die Extraktionsergebnisse (``quellen/``) und die
Entscheidungen der Pruefliste (``aliasse.json``). NICHT uebernommen:
``graph.json`` (abgeleitet – entsteht neu), ``queue.json``/``status.json``
(Laufzustand des Quellservers) und – ohne ``--mit-widerspruechen`` – die
Widersprueche und Wiki-Seiten: im Vergleich waren nur 3–5 von 26 Funden
brauchbar; sie sollen nicht ungefragt vor Benutzern stehen.

Danach muss der Dienst neu starten: er haelt den Graphen im Speicher und
uebersaehe die neuen Dateien sonst (Register: Zustand hinter dem Ruecken des
Dienstes). Das Skript startet ihn NICHT selbst.

Exit: 0 = in Ordnung · 1 = abgelehnt bzw. Abweichungen · 2 = konnte nicht laufen.
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent


def lokaler_pfad(manifest: str, wurzel: Path) -> Path:
    """Manifest-Form → Datei auf diesem Server (wie ``wissensgraph.absolut``)."""
    if manifest.startswith("mnt/"):
        return Path("/" + manifest)
    return wurzel / manifest


def quellen_lesen(quelle: Path) -> tuple[list[dict], list[str]]:
    """``[{pfad, mtime, datei}]`` aus ``<quelle>/quellen/*.json`` – unlesbare
    Dateien werden GENANNT, nicht still uebergangen."""
    raus, kaputt = [], []
    for p in sorted((quelle / "quellen").glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            pfad, mt = d["pfad"], float(d["mtime"])
        except Exception:  # noqa: BLE001
            kaputt.append(p.name)
            continue
        if not isinstance(pfad, str) or ".." in Path(pfad).parts or pfad.startswith("/"):
            kaputt.append(p.name)
            continue
        raus.append({"pfad": pfad, "mtime": mt, "datei": p.name})
    return raus, kaputt


def pruefen(quelle: Path, wurzel: Path) -> dict:
    """Vergleicht jede gespeicherte Quelle mit der Datei hier. ``gleich`` heisst:
    vorhanden UND dieselbe mtime – nur dann gilt das Extraktionsergebnis."""
    qs, kaputt = quellen_lesen(quelle)
    # ``gesamt`` zaehlt ALLE Dateien, auch unlesbare – sonst meldete pruefen
    # "alles passt", obwohl Dateien unbrauchbar sind (erste Fassung: "4 von 3").
    erg = {"gleich": 0, "geaendert": [], "fehlt": [], "kaputt": kaputt, "gesamt": len(qs) + len(kaputt)}
    for q in qs:
        lp = lokaler_pfad(q["pfad"], wurzel)
        try:
            mt = lp.stat().st_mtime
        except OSError:
            erg["fehlt"].append(q["pfad"])
            continue
        if mt == q["mtime"]:
            erg["gleich"] += 1
        else:
            erg["geaendert"].append(q["pfad"])
    return erg


def einspielen(quelle: Path, wurzel: Path, ersetzen: bool = False,
               mit_widerspruechen: bool = False, trotzdem: bool = False,
               euid: int | None = None) -> tuple[int, str]:
    """Rueckgabe (Exit-Code, Meldung). Schreibt nur bei Exit 0."""
    if (os.geteuid() if euid is None else euid) == 0:
        # Als root angelegte Dateien legen den Dienst lahm (Register: Deploy
        # gehoert dem Dienstbenutzer) – hier gar nicht erst schreiben.
        return 1, "Nicht als root ausfuehren – als Dienstbenutzer (runuser -u jarvis …)."
    erg = pruefen(quelle, wurzel)
    if not erg["gesamt"]:
        return 1, f"Keine Quellen unter {quelle}/quellen – falscher Ordner?"
    abw = len(erg["geaendert"]) + len(erg["fehlt"]) + len(erg["kaputt"])
    if abw and not trotzdem:
        return 1, (f"{abw} von {erg['gesamt']} Quellen passen nicht (geaendert {len(erg['geaendert'])}, "
                   f"fehlt {len(erg['fehlt'])}, unlesbar {len(erg['kaputt'])}). Mit --trotzdem werden "
                   "sie mit uebernommen und beim naechsten Aufbau neu extrahiert.")
    ziel = wurzel / "data" / "graph"
    qd = ziel / "quellen"
    vorhanden = qd.is_dir() and any(qd.glob("*.json"))
    if vorhanden and not ersetzen:
        return 1, f"{ziel} enthaelt schon einen Graphen – mit --ersetzen wird er vorher gesichert und ersetzt."
    sicherung = ""
    if ziel.exists():
        # Eindeutig auch bei zwei Laeufen in derselben Sekunde – os.replace auf
        # einen vorhandenen, nicht leeren Ordner wuerfe sonst mitten im Lauf.
        stempel, n = time.strftime('%Y%m%d-%H%M%S'), 0
        while ziel.with_name(f"graph.vor-uebernahme-{stempel}" + (f"-{n}" if n else "")).exists():
            n += 1
        sicherung = str(ziel.with_name(f"graph.vor-uebernahme-{stempel}" + (f"-{n}" if n else "")))
        os.replace(ziel, sicherung)
    neu = ziel.with_name("graph.uebernahme-tmp")
    if neu.exists():
        shutil.rmtree(neu)
    neu.mkdir(mode=0o750)
    shutil.copytree(quelle / "quellen", neu / "quellen", copy_function=shutil.copy2)
    teile = ["aliasse.json"] + (["widersprueche.json"] if mit_widerspruechen else [])
    for n in teile:
        if (quelle / n).is_file():
            shutil.copy2(quelle / n, neu / n)
    if mit_widerspruechen and (quelle / "wiki").is_dir():
        shutil.copytree(quelle / "wiki", neu / "wiki", copy_function=shutil.copy2)
    os.chmod(neu, 0o750)
    os.replace(neu, ziel)
    return 0, (f"Uebernommen: {erg['gesamt']} Quellen ({erg['gleich']} mit passender mtime), "
               f"{', '.join(teile)}" + (" und Wiki-Seiten" if mit_widerspruechen else "")
               + (f". Vorheriger Stand gesichert: {sicherung}" if sicherung else "")
               + ". Jetzt den Dienst neu starten – er haelt den Graphen im Speicher.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("aktion", choices=("pruefen", "einspielen"))
    ap.add_argument("quelle", type=Path, help="entpackter data/graph-Ordner des Quellservers")
    ap.add_argument("--wurzel", type=Path, default=WURZEL)
    ap.add_argument("--uebernehmen", action="store_true", help="einspielen wirklich ausfuehren")
    ap.add_argument("--ersetzen", action="store_true", help="vorhandenen Graphen sichern und ersetzen")
    ap.add_argument("--trotzdem", action="store_true", help="auch bei abweichenden Zeitstempeln")
    ap.add_argument("--mit-widerspruechen", action="store_true", help="Widersprueche und Wiki-Seiten mitnehmen")
    a = ap.parse_args(argv)
    if not (a.quelle / "quellen").is_dir():
        print(f"ABBRUCH: {a.quelle}/quellen fehlt")
        return 2
    erg = pruefen(a.quelle, a.wurzel)
    print(f"Quellen {erg['gesamt']}: passend {erg['gleich']}, geaendert {len(erg['geaendert'])}, "
          f"fehlt {len(erg['fehlt'])}, unlesbar {len(erg['kaputt'])}")
    for art in ("geaendert", "fehlt", "kaputt"):
        for x in erg[art][:10]:
            print(f"  {art}: {x}")
    if a.aktion == "pruefen":
        return 0 if erg["gesamt"] and erg["gleich"] == erg["gesamt"] else 1
    if not a.uebernehmen:
        print("Nichts geschrieben – zum Ausfuehren --uebernehmen angeben.")
        return 1
    code, text = einspielen(a.quelle, a.wurzel, a.ersetzen, a.mit_widerspruechen, a.trotzdem)
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
