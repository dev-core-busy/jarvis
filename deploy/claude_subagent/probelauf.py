#!/opt/jarvis/venv/bin/python
"""Machbarkeitsprobe "Claude Subagent" - treibt EINEN Agentenlauf an.

Bewusst IN-PROCESS statt ueber ``POST /api/agent/task``: jener Endpunkt wrappt
den Auftragstext mit einem Benachrichtigungs-Text ("Reagiere angemessen auf die
Benachrichtigung, z.B. Begruessung, Bestaetigung"). Fuer eine Coding-Aufgabe ist
das ein Stoerfaktor - die Probe wuerde die Untauglichkeit DIESES Endpunkts
messen statt der Faehigkeit des Modells. Der Zielentwurf bekommt ohnehin einen
eigenen Endpunkt ohne Wrapper.

Der Lauf ist UNPRIVILEGIERT (``privileged=False``) - genau wie im Zielentwurf.
Damit gilt fuer ihn das volle Pfad-Confinement: Schreiben nur /tmp und
data/documents, Lesen nur /tmp + Wissensverzeichnisse. Der Arbeitsbereich liegt
unter /tmp/csprobe/work, ist also erreichbar - /opt/jarvis dagegen NICHT.

Aufruf:  cs_run.py <aufgabendatei>
"""
import asyncio
import hashlib
import os
import pathlib
import sys
import time

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.path.insert(0, "/opt/jarvis")
os.chdir("/opt/jarvis")

SETTINGS = pathlib.Path("/opt/jarvis/data/settings.json")


def md5(p: pathlib.Path) -> str:
    """Fingerabdruck der Live-Konfiguration - Schutz gegen ungewollte Migration."""
    try:
        return hashlib.md5(p.read_bytes()).hexdigest()
    except Exception:
        return "-"


_vorher = md5(SETTINGS)

from backend.agent import JarvisAgent  # noqa: E402  (erst nach dem Fingerabdruck)


async def main() -> None:
    aufgabe = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    agent = JarvisAgent()
    print(f"[probe] Werkzeuge im Kasten: {len(agent.tools_map)}", flush=True)
    print(f"[probe] Auftragslaenge: {len(aufgabe)} Zeichen", flush=True)

    t0 = time.monotonic()
    try:
        ergebnis = await agent.run_task_headless(
            aufgabe,
            actor={"user": "api:claude-subagent-probe", "privileged": False},
        )
    except Exception as e:  # Ausnahme ist ein Messergebnis, kein Abbruchgrund
        ergebnis = f"(AUSNAHME) {type(e).__name__}: {e}"
    dauer = time.monotonic() - t0

    print(f"[probe] DAUER_S {dauer:.1f}", flush=True)
    print("[probe] ===ERGEBNIS===", flush=True)
    print(ergebnis or "(leere Antwort)", flush=True)
    print("[probe] ===ENDE===", flush=True)


asyncio.run(main())

_nachher = md5(SETTINGS)
print(f"[probe] settings.json: {'UNVERAENDERT' if _vorher == _nachher else '!!! GEAENDERT !!!'}"
      f" ({_vorher[:8]} -> {_nachher[:8]})", flush=True)
