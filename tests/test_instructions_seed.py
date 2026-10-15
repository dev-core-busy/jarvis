"""Prueft den Instruktions-Bootstrap in einem Wegwerf-Verzeichnis."""
import sys, tempfile, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# agent.py importieren ist teuer/abhaengig -> nur die zwei Funktionen nachbauen
src = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
start = src.index("def _seed_instructions()")
end = src.index("def load_instructions()")
ns = {"Path": pathlib.Path}
tmp = tempfile.TemporaryDirectory(); T = pathlib.Path(tmp.name)
ns["INSTRUCTIONS_DIR"] = T / "instructions"
ns["INSTRUCTIONS_DEFAULT_DIR"] = T / "instructions_default"
exec(src[start:end], ns)
seed = ns["_seed_instructions"]
ok = 0; fail = []
def check(n, c, d=""):
    global ok
    if c: ok += 1; print(f"  \033[32m✓\033[0m {n}")
    else: fail.append(n); print(f"  \033[31m✗\033[0m {n} – {d}")

# Vorgaben anlegen
ns["INSTRUCTIONS_DEFAULT_DIR"].mkdir(parents=True)
for n in ("soul.md", "style.md", "beispiel.md.disabled"):
    (ns["INSTRUCTIONS_DEFAULT_DIR"] / n).write_text("x", encoding="utf-8")

print("\n\033[1m1) Erststart: leeres Verzeichnis wird gefuellt\033[0m")
seed()
got = sorted(p.name for p in ns["INSTRUCTIONS_DIR"].iterdir())
check("alle drei Vorgaben kopiert", got == ["beispiel.md.disabled", "soul.md", "style.md"], str(got))

print("\n\033[1m2) Zweiter Start aendert nichts (idempotent)\033[0m")
(ns["INSTRUCTIONS_DIR"] / "soul.md").write_text("SERVER-FASSUNG", encoding="utf-8")
seed()
check("gepflegte Fassung bleibt unberuehrt",
      (ns["INSTRUCTIONS_DIR"] / "soul.md").read_text(encoding="utf-8") == "SERVER-FASSUNG")

print("\n\033[1m3) Bewusst geloeschte Vorgabe wird NICHT zurueckgeholt\033[0m")
(ns["INSTRUCTIONS_DIR"] / "style.md").unlink()
seed()
check("style.md bleibt geloescht (kein Auffuellen einzelner Dateien)",
      not (ns["INSTRUCTIONS_DIR"] / "style.md").exists())

print("\n\033[1m4) Nur .md zaehlt fuer 'leer'\033[0m")
for p in ns["INSTRUCTIONS_DIR"].iterdir(): p.unlink()
(ns["INSTRUCTIONS_DIR"] / "beispiel.md.disabled").write_text("x", encoding="utf-8")
seed()
check("bei nur .md.disabled wird neu geseedet",
      (ns["INSTRUCTIONS_DIR"] / "soul.md").exists())

print("\n\033[1m5) Fehlende Vorgaben sind kein Fehler\033[0m")
import shutil; shutil.rmtree(ns["INSTRUCTIONS_DEFAULT_DIR"])
for p in ns["INSTRUCTIONS_DIR"].iterdir(): p.unlink()
seed()
check("kein Absturz ohne Vorgabe-Verzeichnis", True)
check("Verzeichnis bleibt leer", list(ns["INSTRUCTIONS_DIR"].iterdir()) == [])

tmp.cleanup()
print(f"\n\033[1mErgebnis: {ok}/{ok+len(fail)}\033[0m")
sys.exit(1 if fail else 0)
