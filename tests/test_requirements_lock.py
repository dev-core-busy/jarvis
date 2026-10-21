#!/usr/bin/env python3
"""Waechter: requirements.lock passt zu requirements.txt und traegt Hashes.

WARUM (2026-10-21): die Lock-Datei legt den einen Stand fest, aus dem Docker,
CI und (Phase 2) die Server installieren – ``pip install --require-hashes``.
Damit sie das leisten kann, muss sie
  - fuer JEDES Paket mindestens einen sha256-Hash tragen (sonst bricht
    --require-hashes ab, oder – schlimmer – jemand laesst die Option weg),
  - JEDE Anforderung aus requirements.txt erfuellen (Name, Extras-Grundpaket,
    Grenze) – eine Grenze, die in requirements.txt angehoben wird, ohne die
    Lock neu zu erzeugen, faellt hier auf,
  - torch in GENAU der Fassung des Hinweises "torch==X+cpu" fuehren und
    KEIN CUDA-Paket (nvidia-*, triton) – sonst kaemen ~6 GB zurueck.

BEWUSST NICHT: ein Neu-Aufloesen gegen PyPI (``lock_erneuern.py --pruefen``).
Das meldet "veraltet", sobald irgendein Paket eine neue Version veroeffentlicht –
eine Zeitbombe als Waechter. Geprueft wird die Vertraeglichkeit, nicht die
Aktualitaet.

Dazu die VERBRAUCHER: Dockerfile und Sicherheits-CI installieren aus der Lock
mit --require-hashes und nicht (mehr) aus requirements.txt.

Lauf:  python3 tests/test_requirements_lock.py [lock] [requirements.txt] [Dockerfile] [workflow]
Exit 0 = passt, 1 = Verstoss, 2 = konnte nicht laufen
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "requirements.lock"
REQ = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "requirements.txt"
DOCKERFILE = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "Dockerfile"
WORKFLOW = Path(sys.argv[4]) if len(sys.argv) > 4 else ROOT / ".github" / "workflows" / "sicherheit.yml"

try:
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    from packaging.version import Version
except ImportError:
    print("ABBRUCH (konnte nicht laufen): packaging fehlt")
    sys.exit(2)

ok = 0
fehler = 0


def pruefe(was, bedingung, detail=""):
    global ok, fehler
    if bedingung:
        ok += 1
        print(f"  \033[32m✓\033[0m {was}")
    else:
        fehler += 1
        print(f"  \033[31m✗\033[0m {was}" + (f"\n      {detail}" if detail else ""))


def abbruch(grund):
    print(f"\nABBRUCH (konnte nicht laufen): {grund}")
    sys.exit(2)


EINTRAG = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+?)\s*(\\)?\s*$")
HASH = re.compile(r"^\s+--hash=sha256:[0-9a-f]{64}\s*(\\)?\s*$")


def lese_lock(text: str) -> dict[str, tuple[str, int]]:
    """{kanonischer Name: (Version, Anzahl Hashes)} – Fortsetzungszeilen zaehlen."""
    raus: dict[str, tuple[str, int]] = {}
    aktuell = None
    for zeile in text.splitlines():
        m = EINTRAG.match(zeile)
        if m:
            aktuell = canonicalize_name(m.group(1))
            raus[aktuell] = (m.group(2), 0)
            continue
        if aktuell and HASH.match(zeile):
            v, n = raus[aktuell]
            raus[aktuell] = (v, n + 1)
            continue
        aktuell = None if not zeile.startswith(" ") else aktuell
    return raus


def anforderungen(text: str) -> list[Requirement]:
    raus = []
    for roh in text.splitlines():
        zeile = roh.split("#", 1)[0].strip()
        if zeile:
            raus.append(Requirement(zeile))
    return raus


# ── Positivkontrolle der Sonde ────────────────────────────────────────────────
print("\n\033[1mPositivkontrolle\033[0m")
probe = lese_lock(
    "# kopf\n"
    "alpha==1.2.3 \\\n"
    "    --hash=sha256:" + "a" * 64 + " \\\n"
    "    --hash=sha256:" + "b" * 64 + "\n"
    "    # via x\n"
    "beta-paket==2.0+cpu \\\n"
    "    --hash=sha256:" + "c" * 64 + "\n"
    "gamma==0.1\n")
if probe != {"alpha": ("1.2.3", 2), "beta-paket": ("2.0+cpu", 1), "gamma": ("0.1", 0)}:
    abbruch(f"Lock-Leser liest die Probe falsch: {probe}")
print("  Lock-Leser erkennt Eintraege, Hash-Zahl und den Eintrag OHNE Hash")

for p in (LOCK, REQ, DOCKERFILE, WORKFLOW):
    if not p.is_file():
        abbruch(f"{p} fehlt")
lock_text = LOCK.read_text(encoding="utf-8")
req_text = REQ.read_text(encoding="utf-8")
lock = lese_lock(lock_text)
if len(lock) < 20:
    abbruch(f"nur {len(lock)} Eintraege gelesen – Format geaendert?")
try:
    reqs = anforderungen(req_text)
except Exception as e:  # noqa: BLE001 – ungueltige Zeile = nicht pruefbar
    abbruch(f"requirements.txt nicht lesbar: {e}")

# ── Regeln ────────────────────────────────────────────────────────────────────
print("\n\033[1mHashes\033[0m")
ohne = sorted(n for n, (_, h) in lock.items() if h == 0)
pruefe(f"jedes der {len(lock)} Pakete traegt mindestens einen sha256-Hash", not ohne, ohne[:10])
pruefe("Kopf nennt den Erzeuger (nicht von Hand bearbeiten)",
       "deploy/lock_erneuern.py" in lock_text.split("\n", 3)[0])

print("\n\033[1mrequirements.txt erfuellt\033[0m")
fehlt, verletzt = [], []
for rq in reqs:
    name = canonicalize_name(rq.name)
    if name not in lock:
        fehlt.append(rq.name)
        continue
    v = lock[name][0]
    if rq.specifier and not rq.specifier.contains(Version(v), prereleases=True):
        verletzt.append(f"{rq.name} {rq.specifier} -> {v}")
pruefe(f"alle {len(reqs)} Anforderungen stehen in der Lock", not fehlt, fehlt)
pruefe("jede gesperrte Version erfuellt ihre Grenze", not verletzt, verletzt)

print("\n\033[1mtorch und CUDA\033[0m")
m = re.search(r'"torch==([0-9.]+\+cpu)"', req_text)
if not m:
    abbruch('torch-Hinweis "torch==X+cpu" in requirements.txt fehlt')
pruefe(f"torch in der Fassung des Hinweises ({m.group(1)})",
       lock.get("torch", ("",))[0] == m.group(1), lock.get("torch"))
cuda = sorted(n for n in lock if n.startswith("nvidia-") or n == "triton")
pruefe("kein CUDA-Paket (nvidia-*, triton)", not cuda, cuda)
vorab = sorted(f"{n}=={v}" for n, (v, _) in lock.items()
               if Version(v).is_prerelease or Version(v).is_devrelease)
pruefe("keine Vorab-/Entwicklungsversion (ECHT trug pydantic 2.14.0a1)", not vorab, vorab)

print("\n\033[1mVerbraucher installieren aus der Lock\033[0m")


def befehle(text: str) -> list[str]:
    """pip-install-Befehle ohne Kommentarzeilen, Fortsetzungen zusammengezogen."""
    ohne = "\n".join(z for z in text.splitlines() if not z.lstrip().startswith("#"))
    ohne = re.sub(r"\\\s*\n\s*", " ", ohne)
    return [z.strip() for z in ohne.splitlines() if re.search(r"\bpip install\b", z)]


for name, pfad in (("Dockerfile", DOCKERFILE), ("Sicherheits-CI", WORKFLOW)):
    bs = befehle(pfad.read_text(encoding="utf-8"))
    aus_lock = [b for b in bs if re.search(r"-r\s+requirements\.lock\b", b)]
    pruefe(f"{name}: installiert aus requirements.lock",
           bool(aus_lock), bs)
    pruefe(f"{name}: mit --require-hashes",
           bool(aus_lock) and all("--require-hashes" in b for b in aus_lock), aus_lock)
    pruefe(f"{name}: kein pip install -r requirements.txt mehr",
           not any(re.search(r"-r\s+requirements\.txt\b", b) for b in bs),
           [b for b in bs if "requirements.txt" in b])

print(f"\nErgebnis: {ok} OK, {fehler} FAIL")
sys.exit(1 if fehler else 0)
