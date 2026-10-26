"""Docker-Image ohne git: Updater meldet den Image-Weg statt eines git-Fehlers.

GEMELDET 2026-10-26 von einem Docker-Anwender: das Image enthaelt weder
/app/.git noch das git-Programm. Der In-App-Updater lief trotzdem in
``git fetch`` und zeigte "git fetch fehlgeschlagen: ... 'git'". Ausserdem lag
/etc/jarvis (broker-policy.json, Freigabe-Schluessel, ggf. geheimnis.key) im
Container-Layer und ging bei jedem Neuaufbau verloren.

Geprueft wird die WIRKUNG:
  1. Im Image-Betrieb ruft weder check_update noch apply_update git auf und
     beide liefern ``image: True`` samt Hinweis auf ``docker compose pull``.
  2. Ausserhalb von Docker und in Docker MIT Checkout + git bleibt der
     git-Weg (Positivkontrolle: dieselbe Attrappe sieht dort git-Aufrufe).
  3. /etc/jarvis ist im Dockerfile ein VOLUME und in beiden Compose-Beispielen
     ein benanntes Volume – und zwar NICHT unter /app/data (BSI M5).

    python3 tests/test_update_image_betrieb.py
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

res = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


try:
    from backend import update_manager as um
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.update_manager nicht ladbar: {e}")
    sys.exit(2)

if not hasattr(um, "image_betrieb"):
    print("  \033[31m✗\033[0m update_manager.image_betrieb fehlt")
    sys.exit(1)

# ── Attrappe fuer subprocess.run: zeichnet git-Aufrufe auf ──────────────────
aufrufe: list[list[str]] = []
_echt_run = subprocess.run


def _attrappe(cmd, *a, **kw):
    aufrufe.append(list(cmd))
    # Antwortform wie subprocess.CompletedProcess; rc 1 = "git sagt nein"
    return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="attrappe")


def _lauf(docker: bool, mit_git_dir: bool, git_da: bool, fn):
    aufrufe.clear()
    with tempfile.TemporaryDirectory() as tmp:
        wurzel = Path(tmp)
        if mit_git_dir:
            (wurzel / ".git").mkdir()
        alt_root, alt_which = um.PROJECT_ROOT, um.shutil.which
        alt_env = os.environ.get("JARVIS_DOCKER")
        um.PROJECT_ROOT = wurzel
        um.shutil.which = (lambda n: "/usr/bin/git") if git_da else (lambda n: None)
        um.subprocess.run = _attrappe
        if docker:
            os.environ["JARVIS_DOCKER"] = "1"
        else:
            os.environ.pop("JARVIS_DOCKER", None)
        try:
            return fn()
        finally:
            um.PROJECT_ROOT, um.shutil.which = alt_root, alt_which
            um.subprocess.run = _echt_run
            if alt_env is None:
                os.environ.pop("JARVIS_DOCKER", None)
            else:
                os.environ["JARVIS_DOCKER"] = alt_env


def _git_aufrufe():
    return [c for c in aufrufe if c and c[0] == "git"]


print("\n=== 1. Positivkontrolle: die Attrappe sieht git-Aufrufe ===")
erg = _lauf(docker=False, mit_git_dir=True, git_da=True, fn=um.check_update)
if not _git_aufrufe():
    print("ABBRUCH: Attrappe sieht ausserhalb von Docker keinen git-Aufruf – Messung blind")
    sys.exit(2)
check("ausserhalb von Docker: check_update ruft git", True)
check("... und meldet KEINEN Image-Betrieb", not erg.get("image"), str(erg))

erg = _lauf(docker=True, mit_git_dir=True, git_da=True, fn=um.check_update)
check("Docker MIT Checkout und git: weiter der git-Weg",
      bool(_git_aufrufe()) and not erg.get("image"), str(erg)[:200])

print("\n=== 2. Image-Betrieb: kein git, sondern Hinweis ===")
for titel, mit_dir, git_da in (("ohne /app/.git", False, True),
                               ("ohne git-Programm", True, False),
                               ("ohne beides (das gemeldete Image)", False, False)):
    erg = _lauf(docker=True, mit_git_dir=mit_dir, git_da=git_da, fn=um.check_update)
    check(f"check_update {titel}: kein git-Aufruf", not _git_aufrufe(), str(_git_aufrufe()))
    check(f"... image=True, ok=True, kein Update angezeigt",
          erg.get("image") is True and erg.get("ok") is True and erg.get("has_update") is False,
          str(erg)[:200])
    check("... Hinweis nennt docker compose pull",
          "docker compose pull" in str(erg.get("hinweis", "")), str(erg.get("hinweis")))

erg = _lauf(docker=True, mit_git_dir=False, git_da=False, fn=um.apply_update)
check("apply_update im Image-Betrieb: kein git-Aufruf", not _git_aufrufe(), str(_git_aufrufe()))
check("... ok=False mit Hinweis statt Absturz",
      erg.get("ok") is False and erg.get("image") is True
      and "docker compose pull" in str(erg.get("error", "")), str(erg)[:200])

print("\n=== 3. main.py: Auto-Update im Image-Betrieb nicht anlegbar ===")
main_src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
m = re.search(r'async def update_settings_set\(.*?\n(?=@app\.)', main_src, re.S)
check("update_settings_set gefunden (Gegenprobe zum Schnitt)", bool(m))
teil = m.group(0) if m else ""
sperre = teil.find("image_betrieb()")
anlegen = teil.find("cron_manager.add_job")
check("Image-Sperre steht VOR dem Anlegen des Auftrags",
      0 < sperre < anlegen, f"sperre={sperre} anlegen={anlegen}")
check("... mit Status 409", "status_code=409" in teil[sperre:anlegen] if sperre > 0 else False)

print("\n=== 4. /etc/jarvis ist persistent – getrennt von /app/data ===")
dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
vol = re.findall(r'^VOLUME\s+\[([^\]]*)\]', dockerfile, re.M)
pfade = [p.strip().strip('"') for v in vol for p in v.split(",")]
check("Dockerfile: VOLUME-Zeile gefunden (Positivkontrolle)", "/app/data" in pfade, str(pfade))
check("Dockerfile: /etc/jarvis ist ein VOLUME", "/etc/jarvis" in pfade, str(pfade))

try:
    import yaml
except Exception:  # noqa: BLE001
    yaml = None
for name in ("docker-compose.yml", "docs/docker-compose.yml"):
    text = (ROOT / name).read_text(encoding="utf-8")
    if yaml is None:
        print(f"ABBRUCH: PyYAML fehlt – {name} nicht pruefbar")
        sys.exit(2)
    doc = yaml.safe_load(text)
    vols = ((doc.get("services") or {}).get("jarvis") or {}).get("volumes") or []
    ziele = {}
    for v in vols:
        teile = str(v).split(":")
        if len(teile) >= 2:
            ziele[teile[1]] = teile[0]
    check(f"{name}: /app/data eingehaengt (Positivkontrolle)", "/app/data" in ziele, str(ziele))
    quelle = ziele.get("/etc/jarvis")
    check(f"{name}: /etc/jarvis eingehaengt", bool(quelle), str(ziele))
    check(f"{name}: ... aus einem EIGENEN Volume, nicht dem von /app/data",
          bool(quelle) and quelle != ziele.get("/app/data"), f"{quelle} / {ziele.get('/app/data')}")
    check(f"{name}: ... und das Volume ist deklariert",
          bool(quelle) and quelle in (doc.get("volumes") or {}), str(list((doc.get("volumes") or {}))))

ok = sum(res)
print(f"\nErgebnis: {ok}/{len(res)}")
sys.exit(0 if all(res) else 1)
