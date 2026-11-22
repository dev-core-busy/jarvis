"""Sicherungsablage der ``gegen_*``-Harnesse nach geordnetem Ende abraeumen.

WARUM (2026-11-22): rund hundert Gegenproben sichern die Dateien, die sie
sabotieren, auf PLATTE unter ``~/.gegen-<name>`` (0700, NICHT /tmp) - richtig,
denn ein abgeschossener Lauf muss seinen Rueckstand beim naechsten Start
zuruecknehmen koennen. Abgeraeumt wurde am geordneten Ende aber meist nur die
LAUFMARKE, nicht der Ordner. Ergebnis: 37 liegengebliebene Ordner (54 MB) im
Home, jeder ein vollstaendiger Altstand von main.py, i18n.js & Co.

Die Regel hier: geloescht wird nur eine Ablage, die NICHTS MEHR WEISS.
  * Liegt die Laufmarke noch, war das Ende nicht geordnet -> bleibt.
  * Jede Datei darin muss Byte fuer Byte einem Gegenstueck im Arbeitsbaum
    gleichen. Weicht eine ab (Zuruecklegen gescheitert, Lauf mittendrin
    beendet), bleibt die Ablage liegen und der Grund geht nach stderr.
  * Ein ``kill -9`` fuehrt kein atexit aus -> Ablage und Marke bleiben, der
    naechste Start des Harness nimmt den Rueckstand wie bisher zurueck.

Das Gegenstueck wird so gesucht, wie die Harnesse ablegen: ``rel`` mit
``/`` -> ``__`` (oder unveraendert als Unterpfad), wahlweise mit ``.bak``;
gibt es keinen solchen Pfad, ueber den Dateinamen im Arbeitsbaum
(``git ls-files``) - fuer Harnesse, die nur ``p.name`` ablegen.

REIHENFOLGE: atexit arbeitet rueckwaerts. Der Aufruf muss deshalb auf
Modulebene VOR dem ``atexit.register(zurueck)`` des Harness stehen - dann
laeuft das Abraeumen als LETZTES, nach dem Zuruecklegen. Steht er dahinter,
saehe der Helfer den sabotierten Baum und liesse die Ablage (sicher, aber
nutzlos) liegen. Waechter: ``tests/test_gegen_ablage.py``.

    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from gegen_ablage import abraeumen_bei_ende
    abraeumen_bei_ende(ABLAGE, marke=MARKE)
"""
import atexit
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]
_ENDUNGEN = (".bak", ".orig", ".sicher")


def _gleich(a: Path, b: Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _varianten(rel: str) -> list[str]:
    """``rel`` und ``rel`` ohne Sicherungsendung (``x.py.bak`` -> ``x.py``)."""
    aus = [rel]
    for e in _ENDUNGEN:
        if rel.endswith(e) and len(rel) > len(e):
            aus.append(rel[: -len(e)])
    return aus


def _exakte_kandidaten(rel: str, wurzel: Path) -> list[Path]:
    aus = []
    for v in _varianten(rel):
        for k in (v, v.replace("__", "/")):
            p = wurzel / k
            if p.is_file() and p not in aus:
                aus.append(p)
    return aus


def _namens_index(wurzel: Path):
    """Dateiname -> Pfade im Arbeitsbaum (verfolgt + unverfolgt, ohne ignorierte)."""
    try:
        r = subprocess.run(["git", "-C", str(wurzel), "ls-files", "-co", "--exclude-standard", "-z"],
                           capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    index: dict[str, list[Path]] = {}
    for rel in r.stdout.decode("utf-8", "replace").split("\0"):
        if rel:
            index.setdefault(rel.rsplit("/", 1)[-1], []).append(wurzel / rel)
    return index


def grund_zum_behalten(ablage, marke=None, wurzel=WURZEL):
    """None = die Ablage weiss nichts mehr; sonst der Grund, sie zu behalten."""
    ablage, wurzel = Path(ablage), Path(wurzel)
    marke = Path(marke) if marke else None
    # Liegt die Marke IN der Ablage, haelt sie schon der Inhaltsvergleich fest
    # (sie hat kein Gegenstueck im Baum). Diese Zeile traegt allein fuer eine
    # Marke AUSSERHALB der Ablage - und sie liefert den lesbaren Grund.
    if marke is not None and marke.exists():
        return f"Laufmarke liegt noch ({marke.name}) - Ende war nicht geordnet"
    index = None
    for f in sorted(ablage.rglob("*")):
        if f.is_dir() and not f.is_symlink():
            continue
        if not f.is_file() or f.is_symlink():
            return f"{f.relative_to(ablage)}: keine regulaere Datei"
        rel = f.relative_to(ablage).as_posix()
        exakt = _exakte_kandidaten(rel, wurzel)
        if exakt:
            if any(_gleich(f, p) for p in exakt):
                continue
            return f"{rel} weicht vom Arbeitsbaum ab"
        if index is None:
            index = _namens_index(wurzel)
            if index is None:
                return "Arbeitsbaum nicht lesbar (git ls-files)"
        name = rel.rsplit("/", 1)[-1]
        if any(_gleich(f, p) for v in _varianten(name) for p in index.get(v, [])):
            continue
        return f"{rel}: kein gleiches Gegenstueck im Arbeitsbaum"
    return None


def _gesperrt(ablage: Path, wurzel: Path):
    """Harte Grenzen: nur ein Unterordner des Home, nie Home/Arbeitsbaum selbst."""
    a, h, w = ablage.resolve(), Path.home().resolve(), wurzel.resolve()
    if a == h or h not in a.parents:
        return f"liegt nicht unterhalb von {h}"
    if a == w or a in w.parents or w in a.parents:
        return "ueberschneidet sich mit dem Arbeitsbaum"
    return None


def abraeumen(ablage, marke=None, wurzel=WURZEL):
    """Loescht die Ablage, wenn sie nichts mehr weiss; liefert sonst den Grund."""
    ablage = Path(ablage)
    if not ablage.exists():
        return None
    grund = _gesperrt(ablage, Path(wurzel)) or grund_zum_behalten(ablage, marke, wurzel)
    if grund:
        return grund
    shutil.rmtree(ablage)
    return None


def _beim_ende(ablage, marke, wurzel):
    try:
        grund = abraeumen(ablage, marke, wurzel)
    except Exception as exc:  # Abraeumen darf das Ergebnis des Harness nie kippen
        grund = f"Pruefung gescheitert: {exc}"
    if grund:
        print(f"[gegen_ablage] Sicherung bleibt liegen: {ablage} - {grund}", file=sys.stderr)


def abraeumen_bei_ende(ablage, marke=None, wurzel=WURZEL):
    """Meldet das Abraeumen fuer das Prozessende an (atexit, siehe REIHENFOLGE)."""
    atexit.register(_beim_ende, Path(ablage), Path(marke) if marke else None, Path(wurzel))
