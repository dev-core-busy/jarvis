"""jsdom fuer die Riegel der Delegation bereitstellen.

WARUM ES DIESES MODUL GIBT: 47 der 50 JS-Tests dieses Projekts brauchen
``jsdom``. Wer eine Codeaufgabe an eine Jarvis-Installation abgibt
(``deploy/claude_subagent``), nennt dabei einen **Riegel** – die Testdatei, die
das Ergebnis beweist. Der Riegel laeuft in einem frischen Klon des Repos, und
``node_modules/`` steht in ``.gitignore``: dort ist also KEIN jsdom. Ein
UI-Riegel meldet dann "rot", obwohl an der Aenderung nichts falsch ist.

Genau so ist Auftrag ``be31e4825d52`` am 2026-08-31 gescheitert: 17 Pruefungen
gruen, eine rot – und die eine war "jsdom vorhanden". Der Agent hatte alles
richtig gemacht.

⚠ WARUM AUTOMATISCH UND NICHT PER ANLEITUNG: es gibt mehrere Installationen,
auf die der Betreiber keinen Zugriff hat. Ein Hinweis in einer Anleitung
erreicht die nie – dieselbe Begruendung wie bei den Python-Modulen der
Agent-Shell (``start_jarvis_root.sh`` Schritt 6c): *bei mehreren Servern
skaliert nur eine Automatik.*

ZWEI UNTERSCHIEDE ZU JENEM SCHRITT, beide bewusst:

* **Kein root.** Installiert wird nach ``data/node_modules`` – das Verzeichnis
  gehoert dem Dienstbenutzer. Damit braucht es weder den Broker noch eine
  Root-Freigabe, und es funktioniert auch im Alt-Betrieb.
* **Kein Repo-Ballast.** jsdom zieht 58 Pakete (13,2 MB, 1512 Dateien). Die ins
  oeffentliche Repo zu committen hiesse, sie bei JEDEM Auftrag mitzuklonen
  (``git clone --depth 1``) – fuer einen Lauf von 30 bis 60 Sekunden der
  teuerste Teil. Deshalb liegt es neben dem Repo, nicht darin.

Abschaltbar mit ``JARVIS_JSDOM_AUTO=0`` (Server ohne Egress oder mit bewusst
handgepflegtem Paketstand).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# Wurzel des Projekts (dieses Modul liegt in backend/).
WURZEL = Path(__file__).resolve().parent.parent

# ⚠ DIESE LISTE IST DIE EINZIGE QUELLE FUER DEN ORT.
# `claude_subagent.riegel_laufen()` setzt JSDOM_PATH aus derselben Funktion
# (`pfad()`), und `installieren()` schreibt in `ZIEL`. Ein Test haelt fest, dass
# beides zusammenpasst: zwei Orte, die auseinanderlaufen, ergeben einen Riegel,
# der dauerhaft rot bleibt, ohne dass jemand sieht warum.
ZIEL = WURZEL / "data" / "node_modules"

# ⚠ DIE VERSION IST FESTGENAGELT, UND ZWAR AUS EINEM GEMESSENEN GRUND.
# `npm install jsdom` zog am 2026-08-31 die Fassung 30.0.1 – deren
# `engines` verlangt `^22.22.2 || ^24.15.0 || >=26.0.0`. Auf dem Server laeuft
# Node v20.19.2: die Installation MELDETE ERFOLG, und `require` warf danach
# "webidl.util.markAsUncloneable is not a function". Ein Riegel uebersprang
# seinen jsdom-Abschnitt und war gruen, ohne etwas zu pruefen.
#
# jsdom 25 verlangt `node >= 18` und laeuft damit auf allem, was hier im Feld
# steht – und auf allen Installationen DASSELBE, was der eigentliche Zweck der
# Automatik ist. Wer eine neuere Node-Fassung hat und eine neuere jsdom will,
# setzt JSDOM_PATH auf seine eigene Installation; die gewinnt.
PAKET = "jsdom@25.0.1"

# Reihenfolge = Vorrang. Eine gesetzte Umgebungsvariable gewinnt immer: wer den
# Ort bewusst umstellt, will nicht ueberstimmt werden.
def _orte() -> list[Path]:
    aus: list[Path] = []
    umgebung = (os.environ.get("JSDOM_PATH") or "").strip()
    if umgebung:
        aus.append(Path(umgebung))
    aus.append(ZIEL / "jsdom")                 # von hier installiert
    aus.append(WURZEL / "node_modules" / "jsdom")   # Entwicklungsrechner
    return aus


def pfad() -> str:
    """Pfad eines vorhandenen jsdom – oder "" wenn keines gefunden wurde.

    Der Rueckgabewert ist genau das, was als ``JSDOM_PATH`` gesetzt werden
    muss: die Tests machen daraus ein ``require(process.env.JSDOM_PATH)``.
    """
    for p in _orte():
        try:
            if (p / "package.json").is_file():
                return str(p)
        except OSError:
            continue
    return ""


def vorhanden() -> bool:
    """Liegt dort ueberhaupt etwas? (billig, nur Dateisystem)"""
    return bool(pfad())


def lauffaehig(ort: str = "") -> bool:
    """Laesst sich das jsdom dort WIRKLICH laden?

    ⚠ DIESE PRUEFUNG IST DER KERN. `vorhanden()` sagt nur, dass eine
    package.json daliegt – am 2026-08-31 lag dort eine jsdom-Fassung, die zur
    Node-Version des Servers nicht passt. Die Installation meldete Erfolg, und
    erst `require` warf. Ein Riegel uebersprang daraufhin seinen
    jsdom-Abschnitt und meldete gruen, ohne etwas zu pruefen: die Automatik
    haette sich selbst fuer fertig erklaert.
    """
    ort = ort or pfad()
    if not ort:
        return False
    if not shutil.which("node"):
        return False
    try:
        p = subprocess.run(
            ["node", "-e",
             "const j = require(process.argv[1]); if (!j.JSDOM) process.exit(3);",
             ort],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0


def automatik_an() -> bool:
    """Vorgabe AN. Eine Funktion, keine Konstante – ein beim Import gelesener
    Wert waere bis zum Dienstneustart wirkungslos."""
    return (os.environ.get("JARVIS_JSDOM_AUTO") or "1").strip() != "0"


def installieren(timeout: int = 300) -> tuple[bool, str]:
    """jsdom nach ``ZIEL`` installieren. Rueckgabe (erfolg, meldung).

    Idempotent: ist es schon da, wird nichts getan.
    """
    if lauffaehig():
        return True, ""
    if not shutil.which("npm"):
        return False, ("npm ist nicht installiert – UI-Riegel (jsdom) koennen "
                       "auf diesem Server nicht laufen. Abhilfe: Node.js/npm "
                       "installieren, oder JARVIS_JSDOM_AUTO=0 setzen.")
    try:
        ZIEL.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, f"{ZIEL.parent} nicht anlegbar: {e}"

    # --prefix legt ZIEL/node_modules an, --no-fund/--no-audit halten die
    # Ausgabe kurz. Eigener Cache im Zielbaum: HOME des Dienstes ist nicht
    # verlaesslich beschreibbar (dieselbe Falle wie beim HF-Cache, siehe
    # Register), und ein npm ohne Cache-Verzeichnis bricht ab.
    cache = ZIEL.parent / ".npm-cache"
    cmd = ["npm", "install", "--no-save", "--no-fund", "--no-audit",
           "--prefix", str(ZIEL.parent), "--cache", str(cache), PAKET]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(ZIEL.parent))
    except subprocess.TimeoutExpired:
        return False, f"npm-Installation nach {timeout}s abgebrochen (Netz zu langsam?)."
    except OSError as e:
        return False, f"npm nicht startbar: {e}"
    if p.returncode != 0 or not lauffaehig():
        ende = ((p.stderr or p.stdout or "").strip().splitlines() or [""])[-3:]
        return False, ("jsdom-Installation fehlgeschlagen (rc=%d; kein Egress zu "
                       "registry.npmjs.org?): %s" % (p.returncode, " | ".join(ende)))
    return True, f"jsdom installiert: {pfad()}"


def sicherstellen() -> str:
    """Fuer den Start: pruefen, bei Bedarf nachinstallieren, Meldung liefern.

    Leerer String = alles in Ordnung und nichts zu melden. Eine Zeile bei jedem
    Start, die immer dasselbe sagt, wird nach zwei Tagen nicht mehr gelesen.
    """
    if lauffaehig():
        return ""
    # Liegt etwas da, das sich nicht laden laesst, ist das schlimmer als
    # nichts: der Riegel ueberspringt dann seinen jsdom-Abschnitt und meldet
    # gruen. Also austauschen, nicht daneben leben.
    kaputt = pfad()
    if not automatik_an():
        return ("[jsdom] fehlt und JARVIS_JSDOM_AUTO=0 – UI-Riegel der "
                "Delegation koennen hier nicht laufen (bewusst abgeschaltet).")
    ok, meldung = installieren()
    if ok:
        vorspann = ("nicht ladbare Fassung ersetzt – " if kaputt else "")
        return f"[jsdom] {vorspann}{meldung}"
    return (f"[jsdom] WARNUNG: {meldung} Bis dahin lehnt jeder Auftrag mit "
            "einem UI-Riegel ab, obwohl die Aenderung richtig sein kann.")


def bericht() -> str:
    """Einzeiler fuer Diagnose-Endpunkte (immer eine Aussage, auch die gute)."""
    p = pfad()
    if p and lauffaehig(p):
        return f"jsdom vorhanden: {p}"
    if p:
        return (f"jsdom liegt in {p}, laesst sich aber nicht laden (Fassung passt "
                f"nicht zur Node-Version?) – UI-Riegel wuerden ihren "
                f"jsdom-Abschnitt ueberspringen.")
    return ("jsdom fehlt – UI-Riegel (47 der 50 JS-Tests) koennen nicht laufen."
            + ("" if automatik_an() else " Automatik ist per JARVIS_JSDOM_AUTO=0 aus."))
