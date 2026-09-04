"""LIVE auf DEV: der gemeldete Vorfall sperrt nicht mehr – im ECHTEN Dispatch.

Gefahren wird ``AgentManager`` → ``_execute_tool("shell_execute", …)`` in einem
``actor_scope`` eines UNPRIVILEGIERTEN Benutzers – also genau der Weg, der am
04.09. auf ECHT ``jonas.reichelt`` gesperrt hat, mit den drei ECHTEN Befehlen.

Lauf AUF DEM SERVER als Dienstbenutzer:
    runuser -u jarvis -- venv/bin/python /tmp/live_marke_dev.py

Der Testbenutzer wird am Ende vollstaendig aus ``data/security_state.json``
entfernt (und eine etwaige Sperre mit) – der Bestand bleibt unangetastet.
"""
import asyncio
import json
import sys

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]

ok = fail = 0
NUTZER = "livetest.marke"


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


VORFALL = [
    "find /root/jarvis/data/knowledge -type f -iname '*pathos*' -o -iname '*dc*' 2>/dev/null | head -20",
    "grep -ri 'dc-pathos\\|dc pathos\\|dcpat' /root/jarvis/data/knowledge/ 2>/dev/null | head -30",
    "find /root/jarvis/data/knowledge -type f 2>/dev/null | xargs grep -li 'dc-pathos\\|dc pathos\\|dcpat' 2>/dev/null | head -20",
]

from backend import security_guard as sg          # noqa: E402
from backend.agent import AgentManager            # noqa: E402


def zustand():
    try:
        return json.loads(sg._STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def eigene(z):
    v = z.get("violations", {})
    for k in v:
        if sg.norm_user(k) == sg.norm_user(NUTZER):
            return v[k]
    return []


def gesperrt(z):
    return sg._finde_key(z.get("blocked", {}), NUTZER) is not None


def aufraeumen():
    with sg._lock:
        z = sg._load()
        for topf in ("violations", "blocked"):
            d = z.get(topf, {})
            for k in [k for k in d if sg.norm_user(k) == sg.norm_user(NUTZER)]:
                d.pop(k, None)
        sg._save(z)


async def main():
    global ok, fail
    aufraeumen()
    z = zustand()
    check("Positivkontrolle: der Testbenutzer startet ohne Vorfaelle und ohne Sperre",
          not eigene(z) and not gesperrt(z), "%d Eintraege" % len(eigene(z)))
    check("Schwelle ist scharf (%s Verstoesse in %s s)"
          % (sg._autoblock_cfg()["count"], sg._autoblock_cfg()["window"]),
          sg._autoblock_cfg()["enabled"] and sg._autoblock_cfg()["count"] == 3)

    mgr = AgentManager()
    agent = mgr.get_or_create_main()
    check("Hauptagent vorhanden, shell_execute im Werkzeugkasten",
          "shell_execute" in getattr(agent, "tools_map", {}),
          str(list(getattr(agent, "tools_map", {}))[:5]))

    print("\n\033[1mDie drei Befehle des Vorfalls – im echten Dispatch\033[0m")
    antworten = []
    with agent.actor_scope(NUTZER, privileged=False, internet=False):
        for i, cmd in enumerate(VORFALL, 1):
            r = await agent._execute_tool("shell_execute", {"command": cmd})
            antworten.append(r or "")
            print("   %d. %s" % (i, (r or "")[:150].replace("\n", " ")))

    for i, r in enumerate(antworten, 1):
        check("Befehl %d wird abgewiesen" % i, "Zugriff verweigert" in r, r[:80])
        check("… die Meldung nennt '/root'" if i == 1 else "… nennt '/root'",
              "/root" in r, r[:100])
        check("… und den Weg (knowledge_search)" , "knowledge_search" in r, r[:120])

    z = zustand()
    eig = eigene(z)
    check("⚠⚠ DER GEMELDETE FALL: das Konto ist NICHT gesperrt", not gesperrt(z),
          json.dumps(z.get("blocked", {}), ensure_ascii=False)[:200])
    check("… und alle drei Vorfaelle stehen trotzdem im Protokoll", len(eig) == 3,
          "%d" % len(eig))
    marken = {e.get("marke") for e in eig}
    check("… mit derselben Marke", marken == {"pfad:/root"}, str(marken))
    check("… als harte Eintraege (nicht weichgezeichnet)",
          not any(e.get("soft") for e in eig), str([e.get("soft") for e in eig]))

    print("\n\033[1mPositivkontrolle: drei VERSCHIEDENE Schranken sperren weiter\033[0m")
    aufraeumen()
    andere = ["cat /root/geheim.txt", "cat ~/.ssh/id_rsa", "cat /opt/jarvis/data/settings.json"]
    with agent.actor_scope(NUTZER, privileged=False, internet=False):
        for cmd in andere:
            await agent._execute_tool("shell_execute", {"command": cmd})
    z = zustand()
    check("⚠ drei verschiedene Ziele sperren das Konto weiterhin", gesperrt(z),
          json.dumps(eigene(z), ensure_ascii=False)[:160])
    check("… und die Marken sind verschieden",
          len({e.get("marke") for e in eigene(z)}) >= 3,
          str([e.get("marke") for e in eigene(z)]))

    aufraeumen()
    z = zustand()
    check("Ausgangszustand wiederhergestellt (kein Testbenutzer im Bestand)",
          not eigene(z) and not gesperrt(z))


asyncio.run(main())
print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
