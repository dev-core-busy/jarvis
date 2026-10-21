#!/usr/bin/env python3
"""requirements.lock aus requirements.txt erzeugen – exakte Versionen MIT Hashes.

WARUM (2026-10-21, Paket-Empfehlung eines Dritten, Phase 1): requirements.txt
nennt Grenzen und teils gar keine Version. Jede Installation loest neu auf –
DEV und ECHT unterschieden sich an diesem Tag in 58 von 160 gemeinsamen
Paketen, das Docker-Image und die CI in noch anderen. Die Lock-Datei legt EINEN
Stand fest, und ``pip install --require-hashes`` nimmt nur genau die Dateien an,
deren Pruefsumme darin steht.

QUELLE BLEIBT requirements.txt: dort stehen Grenzen samt Begruendung. Dieses
Skript liest sie, ergaenzt torch (die Fassung aus dem Hinweis "torch==X+cpu" in
requirements.txt) und loest mit uv auf. torch kommt dabei AUSSCHLIESSLICH aus dem
CPU-Index (explizite Quelle), alles andere aus PyPI – mit einem gewoehnlichen
--extra-index-url haette uv auch numpy, jinja2 & Co. vom PyTorch-Spiegel nehmen
koennen.

ZIEL: Python 3.13 auf x86_64-manylinux_2_39. Debian 13 hat glibc 2.41, der
Ubuntu-24.04-Runner der CI 2.39 – ein Rad fuer 2_40 liefe dort nicht.

VORLIEBEN – die Lock waehlt NICHT das Neueste: uv uebernimmt Versionen, die schon
in der Ausgabedatei stehen, solange sie die Grenzen erfuellen. Ein Lauf bevorzugt
also die bestehende Lock (stabil, nur Noetiges bewegt sich). Die ERSTE Lock wurde
mit dem pip-freeze von ECHT als Vorliebe erzeugt (2026-10-21): ohne das waehlte uv
bei blossen Untergrenzen Hauptversionen, die kein Server je gefahren hat
(anthropic 1.17 statt 0.107, filelock 4, opentelemetry-api 1.45 entgegen der
festgelegten OTel-Linie). Fuer eine bewusste Aktualisierung: --neueste.

Lauf:  python3 deploy/lock_erneuern.py            # schreibt requirements.lock
       python3 deploy/lock_erneuern.py --vorlieben freeze.txt   # Vorlieben aus pip freeze
       python3 deploy/lock_erneuern.py --neueste  # ohne Vorlieben (alles so neu wie erlaubt)
       python3 deploy/lock_erneuern.py --pruefen  # Exit 1, wenn die Lock veraltet ist
uv:    UV=/pfad/zu/uv (sonst "uv" aus PATH), Fassung UV_FASSUNG – andere Fassungen
       brechen ab, damit derselbe Eingang dieselbe Datei ergibt.
Exit 0 = ok, 1 = veraltet (--pruefen), 2 = konnte nicht laufen
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
REQ = WURZEL / "requirements.txt"
LOCK = WURZEL / "requirements.lock"
UV_FASSUNG = "0.12.23"
PYTHON = "3.13"
PLATTFORM = "x86_64-manylinux_2_39"
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
BEFEHL = "python3 deploy/lock_erneuern.py"


def abbruch(grund: str) -> None:
    print(f"ABBRUCH (konnte nicht laufen): {grund}", file=sys.stderr)
    sys.exit(2)


def anforderungen(text: str) -> list[str]:
    """Anforderungszeilen ohne Kommentare; Optionen (-r, --index-url) sind hier nicht vorgesehen."""
    raus = []
    for roh in text.splitlines():
        zeile = roh.split("#", 1)[0].strip()
        if not zeile:
            continue
        if zeile.startswith("-"):
            abbruch(f"Option in requirements.txt nicht unterstuetzt: {zeile}")
        raus.append(zeile)
    return raus


def torch_fassung(text: str) -> str:
    m = re.search(r'"torch==([0-9.]+\+cpu)"', text)
    if not m:
        abbruch('torch-Hinweis "torch==X+cpu" in requirements.txt nicht gefunden')
    return m.group(1)


def uv_pfad() -> str:
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        abbruch(f"uv nicht gefunden – pip install uv=={UV_FASSUNG}, dann UV=… oder PATH")
    r = subprocess.run([uv, "--version"], capture_output=True, text=True)
    if UV_FASSUNG not in r.stdout:
        abbruch(f"uv {UV_FASSUNG} erwartet, gefunden: {r.stdout.strip() or r.stderr.strip()}")
    return uv


def erzeugen(ziel: Path, vorlieben: str | None) -> None:
    """vorlieben: Inhalt (name==version-Zeilen), der VOR dem Lauf in die Ausgabe
    geschrieben wird – uv nimmt ihn als bevorzugte Versionen. None = Ausgabe leeren."""
    text = REQ.read_text(encoding="utf-8")
    deps = anforderungen(text) + [f"torch=={torch_fassung(text)}"]
    uv = uv_pfad()
    ziel.write_text(vorlieben or "", encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        pp = Path(tmp) / "pyproject.toml"
        zeilen = ",\n".join(f"    {d!r}".replace("'", '"') for d in deps)
        pp.write_text(
            "[project]\n"
            'name = "jarvis-abhaengigkeiten"\n'
            'version = "0"\n'
            f'requires-python = ">={PYTHON}"\n'
            f"dependencies = [\n{zeilen}\n]\n\n"
            "[tool.uv.sources]\n"
            'torch = { index = "pytorch-cpu" }\n\n'
            "[[tool.uv.index]]\n"
            'name = "pytorch-cpu"\n'
            f'url = "{TORCH_INDEX}"\n'
            "explicit = true\n", encoding="utf-8")
        r = subprocess.run(
            [uv, "pip", "compile", str(pp), "--generate-hashes", "--quiet",
             "--python-version", PYTHON, "--python-platform", PLATTFORM,
             "--custom-compile-command", BEFEHL, "--no-header", "-o", str(ziel)],
            capture_output=True, text=True, cwd=tmp, env=dict(os.environ, UV_NO_CACHE="0"))
        if r.returncode != 0:
            abbruch("uv pip compile: " + (r.stderr or r.stdout).strip()[-800:])
    kopf = (
        f"# ERZEUGT von {BEFEHL} – NICHT von Hand bearbeiten.\n"
        "# Quelle: requirements.txt (Grenzen + Begruendungen) und der torch-Hinweis dort.\n"
        f"# uv {UV_FASSUNG}, Python {PYTHON}, {PLATTFORM}. Installieren:\n"
        f"#   pip install --require-hashes --extra-index-url {TORCH_INDEX} -r requirements.lock\n"
        "# (torch kommt nur vom CPU-Index; die Hashes lassen von dort nichts anderes zu.)\n")
    inhalt = ziel.read_text(encoding="utf-8")
    # uv vermerkt den temporaeren Pfad der Eingabe ("via jarvis-abhaengigkeiten (…)")
    # nicht, wohl aber den Projektnamen – beides ist stabil.
    ziel.write_text(kopf + inhalt, encoding="utf-8")


def main() -> int:
    if not REQ.is_file():
        abbruch(f"{REQ} fehlt")
    args = sys.argv[1:]
    bestehend = LOCK.read_text(encoding="utf-8") if LOCK.is_file() else None
    if "--pruefen" in args:
        with tempfile.TemporaryDirectory() as tmp:
            neu = Path(tmp) / "requirements.lock"
            erzeugen(neu, bestehend)
            if not LOCK.is_file() or neu.read_text(encoding="utf-8") != LOCK.read_text(encoding="utf-8"):
                print("requirements.lock ist VERALTET – neu erzeugen: " + BEFEHL)
                return 1
        print("requirements.lock passt zu requirements.txt")
        return 0
    if "--vorlieben" in args:
        i = args.index("--vorlieben")
        if i + 1 >= len(args) or not Path(args[i + 1]).is_file():
            abbruch("--vorlieben braucht eine vorhandene pip-freeze-Datei")
        # Vorab-/Entwicklungsversionen NICHT als Vorliebe: ECHT trug am 2026-10-21
        # pydantic 2.14.0a1 – ohne Filter haette die Lock die Alpha festgeschrieben.
        from packaging.version import InvalidVersion, Version
        zeilen = []
        for z in Path(args[i + 1]).read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)$", z.strip())
            if not m:
                continue
            try:
                v = Version(m.group(2))
            except InvalidVersion:
                continue
            if not (v.is_prerelease or v.is_devrelease):
                zeilen.append(z.strip())
        vorlieben = "\n".join(zeilen) + "\n"
    elif "--neueste" in args:
        vorlieben = None
    else:
        vorlieben = bestehend
    erzeugen(LOCK, vorlieben)
    n = sum(1 for z in LOCK.read_text(encoding="utf-8").splitlines() if re.match(r"^[A-Za-z0-9]", z))
    print(f"requirements.lock geschrieben: {n} Pakete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
