#!/usr/bin/env python3
"""Waechter: Vorfallsliste – Lautstaerke und Werkzeug-Angebot (2026-09-02).

DREI ZUSAGEN, jede einzeln gemessen:

1. ``_llm_tools`` bietet einem UNPRIVILEGIERTEN Auftraggeber kein Werkzeug an,
   das der Dispatch anschliessend hart abweist. Bis zum 2026-09-02 tat es genau
   das: das Modell bekam ``spawn_agent`` & Co. in jedem Lauf angeboten, griff
   danach, der Aufruf wurde verweigert – ein verbrannter Schritt UND ein
   Eintrag in der Vorfallsliste, den der Benutzer weder angefordert hat noch
   vermeiden kann. Genau deshalb ist ``blocked-tool`` seit dem 2026-08-05 als
   weich eingestuft; das war das Symptom, hier ist die Quelle.

2. Die Erinnerungs-Ausnahme ueberlebt den Filter. Ohne sie kennt das Modell
   ``cron_create`` nicht mehr und "Erinnere mich morgen um 6" ist tot – die
   Ausnahme in ``_reminder_exempt`` waere eine Freigabe fuer nichts.

3. Der DISPATCH bleibt die harte Schranke. Waere der Filter die einzige
   Kontrolle, genuegte ein Modell, das ein nicht deklariertes Werkzeug aufruft
   (kommt vor), oder ein Skill, der am Dispatch vorbei arbeitet.

GEMESSEN, NICHT GELESEN: die echte Property wird per ``ast`` geschnitten und
AUSGEFUEHRT. Eine Quelltext-Pruefung bliebe gruen, wenn jemand den Zweig
spaeter ueberspringt.

FALLSTRICK, der hier schon mehrfach bezahlt wurde: ``_BLOCKED_TOOLS_FOR_LDAP``
ist eine MODUL-Konstante und faellt aus jedem Funktions-Schnitt heraus – sie
wird ausdruecklich mitgeschnitten, sonst wirft der Lauf einen nackten
NameError, statt fehlzuschlagen.
"""
import ast
import pathlib
import sys
import types

WURZEL = pathlib.Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "backend" / "agent.py"

_ok = 0
_fail = 0


def check(beschreibung, bedingung, zusatz=""):
    """check(TEXT, BEDINGUNG) – die Reihenfolge ist Absicht.

    Vertauscht man sie, ist eine nicht-leere Zeichenkette wahr und der Lauf
    meldet lauter OK, ohne eine einzige Bedingung ausgewertet zu haben (genau
    das ist in tests/test_jira_vorlagen.py passiert). Deshalb Exit 2 statt
    einer stillen Fehlmessung.
    """
    global _ok, _fail
    if not isinstance(beschreibung, str) or isinstance(bedingung, str):
        print("ABBRUCH: check(beschreibung, bedingung) vertauscht aufgerufen")
        sys.exit(2)
    if bedingung:
        _ok += 1
        print(f"  \033[32m✓\033[0m {beschreibung}")
    else:
        _fail += 1
        print(f"  \033[31m✗\033[0m {beschreibung}" + (f"  [{zusatz}]" if zusatz else ""))


def sicher(fn, *a, **kw):
    """Ruft fn und macht eine Ausnahme zu einem MESSWERT, nicht zum Abbruch.

    Ein Waechter, der beim Melden abbricht, verschluckt seine eigene Bilanz und
    ist von "nicht gelaufen" nicht zu unterscheiden."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return ("__FEHLER__", f"{type(e).__name__}: {e}")


# ── Schnitt: die echte Property + alles, was sie auf Modulebene braucht ──────
def harness():
    baum = ast.parse(QUELLE.read_text(encoding="utf-8"))
    teile = []
    gefunden = {"const": False, "reminder": False, "prop": False}
    for knoten in baum.body:
        if isinstance(knoten, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_BLOCKED_TOOLS_FOR_LDAP" for t in knoten.targets):
            teile.append(ast.get_source_segment(QUELLE.read_text(encoding="utf-8"), knoten))
            gefunden["const"] = True
        if isinstance(knoten, ast.FunctionDef) and knoten.name == "_reminder_exempt":
            teile.append(ast.get_source_segment(QUELLE.read_text(encoding="utf-8"), knoten))
            gefunden["reminder"] = True
        if isinstance(knoten, ast.ClassDef):
            for m in knoten.body:
                if isinstance(m, ast.FunctionDef) and m.name == "_llm_tools":
                    quelle = ast.get_source_segment(QUELLE.read_text(encoding="utf-8"), m)
                    # Dekorator (@property) steht nicht im Segment
                    teile.append("class _Agent:\n    @property\n"
                                 + "\n".join("    " + z for z in quelle.splitlines()))
                    gefunden["prop"] = True
    if not all(gefunden.values()):
        print(f"ABBRUCH: Schnitt unvollstaendig {gefunden}")
        sys.exit(2)
    ns = {}
    exec("\n\n".join(teile), ns)  # noqa: S102
    return ns


class Werkzeug:
    def __init__(self, name):
        self.name = name


def agent(ns, tools, privilegiert=False, benutzer="nexus\\test", rolle=None):
    a = ns["_Agent"]()
    a._tool_instances = [Werkzeug(n) for n in tools]
    a._actor_is_privileged = lambda: privilegiert
    a.actor_name = lambda: benutzer
    if rolle is not None:
        a._role_tools = rolle
    return a


def namen(a):
    return sorted(t.name for t in a._llm_tools)


print("\n\033[1m1. Der Schnitt selbst\033[0m")
NS = sicher(harness)
if isinstance(NS, tuple):
    print(f"ABBRUCH: {NS[1]}")
    sys.exit(2)
GESPERRT = NS["_BLOCKED_TOOLS_FOR_LDAP"]
check("_BLOCKED_TOOLS_FOR_LDAP ist mitgeschnitten und nicht leer", bool(GESPERRT))
check("die Sperrliste nennt spawn_agent und cron_create",
      {"spawn_agent", "cron_create"} <= set(GESPERRT), str(sorted(GESPERRT)))

# reminders wird von _reminder_exempt importiert -> stellen
_rem = types.ModuleType("backend.reminders")
_rem.is_allowed = lambda u: u == "wa:+4915100000"
sys.modules["backend.reminders"] = _rem
sys.modules.setdefault("backend", types.ModuleType("backend"))

ALLE = sorted(set(GESPERRT) | {"shell_execute", "filesystem", "knowledge_search", "cron_list"})

print("\n\033[1m2. Unprivilegiert: kein Angebot, das der Dispatch abweist\033[0m")
a = agent(NS, ALLE, privilegiert=False)
sicht = sicher(namen, a)
check("die Property laeuft", not isinstance(sicht, tuple), str(sicht))
if not isinstance(sicht, tuple):
    uebrig = sorted(set(sicht) & set(GESPERRT))
    check("KEIN gesperrtes Werkzeug wird dem Modell angeboten", not uebrig,
          "noch angeboten: " + ", ".join(uebrig))
    check("spawn_agent ist weg (der gemeldete Fall)", "spawn_agent" not in sicht)
    check("cron_create ist weg (ohne Erinnerungs-Freigabe)", "cron_create" not in sicht)
    for erlaubt in ("shell_execute", "filesystem", "knowledge_search", "cron_list"):
        check(f"'{erlaubt}' bleibt erhalten", erlaubt in sicht)

print("\n\033[1m3. Privilegiert: unveraendert\033[0m")
b = agent(NS, ALLE, privilegiert=True, benutzer="jarvis")
sicht_p = sicher(namen, b)
check("privilegierter Auftraggeber sieht ALLE Werkzeuge",
      sicht_p == sorted(ALLE), str(sicht_p))

print("\n\033[1m4. Erinnerungs-Ausnahme ueberlebt den Filter\033[0m")
c = agent(NS, ALLE, privilegiert=False, benutzer="wa:+4915100000")
sicht_r = sicher(namen, c)
check("freigegebener Messenger-Absender behaelt cron_create",
      not isinstance(sicht_r, tuple) and "cron_create" in sicht_r, str(sicht_r))
check("er bekommt trotzdem kein spawn_agent",
      not isinstance(sicht_r, tuple) and "spawn_agent" not in sicht_r)
d = agent(NS, ALLE, privilegiert=False, benutzer="wa:+4900000000")
sicht_r2 = sicher(namen, d)
check("ein NICHT freigegebener Absender bekommt cron_create nicht",
      not isinstance(sicht_r2, tuple) and "cron_create" not in sicht_r2)

print("\n\033[1m5. Rollen-Whitelist hat weiterhin Vorrang\033[0m")
e = agent(NS, ALLE, privilegiert=False, rolle={"shell_execute", "spawn_agent"})
sicht_w = sicher(namen, e)
check("_role_tools schneidet wie bisher (und laesst die Sperrliste am Dispatch)",
      sicht_w == ["shell_execute", "spawn_agent"], str(sicht_w))

print("\n\033[1m6. Der Dispatch bleibt die harte Schranke\033[0m")
TEXT = QUELLE.read_text(encoding="utf-8")
check("die Dispatch-Pruefung 'name in _BLOCKED_TOOLS_FOR_LDAP' steht weiter im Code",
      "if name in _BLOCKED_TOOLS_FOR_LDAP and not _reminder_exempt(name, _uname):" in TEXT)
check("und sie steht in _execute_tool, nicht in _llm_tools",
      TEXT.index("if name in _BLOCKED_TOOLS_FOR_LDAP")
      > TEXT.index("def _llm_tools"))

print(f"\n\033[1mErgebnis: {_ok}/{_ok + _fail}\033[0m")
sys.exit(1 if _fail else 0)
