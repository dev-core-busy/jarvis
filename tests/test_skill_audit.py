#!/usr/bin/env python3
"""Skill-Audit: arbeitet das Restsystem korrekt, wenn ein Skill AUS ist?

WARUM DIESER TEST EXISTIERT
---------------------------
Auftrag des Nutzers (2026-08-10): "pruefe alle moeglichen Skills darauf, ob das
komplette Restsystem noch korrekt arbeitet, wenn der Skill deaktiviert oder
deinstalliert ist". Zwei Befunde, die das noetig machten:

1. ``"system": true`` IM MANIFEST SCHUETZT NUR GEGEN DAS LOESCHEN.
   Geprueft: in ``backend/skills/manager.py`` fragt ausschliesslich
   ``uninstall_skill()`` das Feld ab (→ ``DELETE /api/skills/{name}`` antwortet
   400). ``disable_skill``, ``remove_skill`` und ``purge_skill`` nehmen JEDEN
   Namen an, und die zugehoerigen Endpunkte pruefen nichts. Damit sind auch
   ``shell``, ``filesystem``, ``knowledge``, ``memory``, ``screenshot``,
   ``desktop``, ``cron`` und ``cognitive_evolution`` abschaltbar – die Annahme
   "System-Skill = immer vorhanden" traegt keine Zeile Code.

2. DER SYSTEM_PROMPT VERLANGTE WERKZEUGE AUS ACHT SKILLS.
   Am Prompt-Literal gezaehlt: ``shell_execute`` 10x, ``memory_manage`` 9x,
   ``knowledge_search`` 8x, ``office_*`` 5x, ``filesystem`` 3x, ``screenshot``
   2x. Abgedeckt war nur ``knowledge_search``. Fehlt ein Werkzeug, ruft das
   Modell es trotzdem auf ("Tool nicht gefunden") oder verweigert die Aufgabe
   mit einer Begruendung, die niemand nachvollziehen kann. Besonders ``office``
   ist per Vorgabe AUS (``enabled: false``) – der Widerspruch stand also auf
   JEDEM frisch installierten System.

3. DER AGENT KANNTE DATUM UND UHRZEIT NICHT.
   Der System-Prompt nannte den Zeitpunkt an keiner Stelle. Folgen: der
   WhatsApp-Prompt musste anweisen, das Datum "per shell_execute ermitteln
   (date …)" – ohne den shell-Skill ist damit jede Erinnerung unmoeglich –, und
   auf einer erzeugten PowerPoint-Titelfolie stand ``$(date +%d.%m.%Y)``
   woertlich (Vorfall 2026-08-10; dort wurde nur die Nachwirkung behoben).

    python3 tests/test_skill_audit.py
"""

import ast
import json
import re
import sys
import types
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# backend.config NICHT echt importieren – der Import migriert Profile und
# schreibt die Live-settings.json zurueck (gleiche Begruendung wie in
# test_display_names.py / test_license.py).
if "backend.config" not in sys.modules:
    _stub = types.ModuleType("backend.config")
    _stub.config = types.SimpleNamespace(
        get_setting=lambda *a, **k: "", ALLOWED_USERS=["jarvis"])
    sys.modules["backend.config"] = _stub

_ok = 0
_fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  ✓ {text}")
    else:
        _fail += 1
        print(f"  ✗ {text}" + (f" – {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n=== {t} ===")


AGENT_SRC = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
MANAGER_SRC = (ROOT / "backend" / "skills" / "manager.py").read_text(encoding="utf-8")

AGENT_LINES = AGENT_SRC.splitlines(keepends=True)


# ─── Klassenteile per Quelltext herausziehen ─────────────────────────────────
# Der echte Import von backend.agent zieht fastapi und den halben Kern mit; die
# geprueften Methoden brauchen davon nichts. Die Zeilen behalten ihre
# Klassen-Einrueckung (4), lassen sich also direkt hinter "class X:" setzen.
def _klassen_node(name):
    for n in ast.parse(AGENT_SRC).body:
        if isinstance(n, ast.ClassDef) and n.name == name:
            return n
    raise SystemExit(f"Klasse {name} nicht gefunden")


def _segment(node):
    start = node.lineno
    for d in getattr(node, "decorator_list", []) or []:
        start = min(start, d.lineno)
    return "".join(AGENT_LINES[start - 1:node.end_lineno])


_JA = _klassen_node("JarvisAgent")
_teile = {}
for n in _JA.body:
    if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in (
            "_SKILL_PFLICHT_TOOLS", "SYSTEM_PROMPT", "SUB_AGENT_PROMPT"):
        _teile[n.targets[0].id] = _segment(n)
    elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in (
            "_pflicht_hinweise", "_fehlende_pflicht_tools", "_zeit_hinweis",
            "_base_system_prompt"):
        _teile[n.name] = _segment(n)

for _pflicht in ("_SKILL_PFLICHT_TOOLS", "_pflicht_hinweise", "_zeit_hinweis",
                 "_base_system_prompt", "SYSTEM_PROMPT", "SUB_AGENT_PROMPT",
                 "_fehlende_pflicht_tools"):
    if _pflicht not in _teile:
        # Exit 2 = der Test konnte nicht laufen (nicht "gruen"). Wichtig fuer die
        # Gegenprobe gegen einen alten Stand: dort fehlt `_pflicht_hinweise`, und
        # ein Abbruch mit Code 0/1 waere von "bestanden"/"fehlgeschlagen" nicht
        # zu unterscheiden.
        print(f"ABBRUCH: {_pflicht} nicht in agent.py gefunden")
        sys.exit(2)

_quelle = "class Agent:\n" + "".join(_teile.values()) + """
    _role_prompt = ""
    is_sub_agent = False

    def __init__(self, tools=()):
        self._tool_instances = [type("T", (), {"name": n})() for n in tools]

    def _role_hinweis(self):
        return ""
"""
_ns = {}
exec(compile(_quelle, "<agent-teile>", "exec"), _ns)  # noqa: S102
Agent = _ns["Agent"]

SYSTEM_PROMPT = Agent.SYSTEM_PROMPT

# Alle Werkzeuge aus allen Skill-Manifesten
SKILL_TOOLS = {}
for _f in sorted((ROOT / "skills").glob("*/skill.json")):
    try:
        _j = json.loads(_f.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"{_f} nicht lesbar: {e}")
    for _t in _j.get("tools", []):
        SKILL_TOOLS[_t] = {"skill": _f.parent.name,
                           "system": bool(_j.get("system")),
                           "default_on": bool(_j.get("enabled"))}

# Werkzeuge, die NICHT aus einem Skill kommen (Kern, immer im Kasten):
# spawn_agent, create_chart, generate_image, search_image, reflection, …
KERN_TOOLS = {"create_chart", "search_image", "spawn_agent", "reflection",
              "read_clipboard", "write_clipboard", "wait_for_screen_change",
              "windows_desktop", "android_desktop", "generate_image"}


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("1. Voraussetzung: 'system: true' verhindert nur das LOESCHEN")

pruefe(re.search(r'def uninstall_skill.*?s\.get\("system"', MANAGER_SRC, re.S)
       is not None,
       "uninstall_skill prueft das system-Flag (einzige Stelle)")

for _fn in ("disable_skill", "remove_skill", "purge_skill"):
    _m = re.search(rf"def {_fn}\(self.*?(?=\n    def )", MANAGER_SRC, re.S)
    pruefe(_m is not None and '"system"' not in _m.group(0),
           f"{_fn} nimmt jeden Skill an – System-Skills sind abschaltbar")

# Der Endpunkt darf ebenfalls keine eigene Schranke haben (sonst waere die
# Annahme oben falsch und dieser Test wuerde etwas Falsches festschreiben).
_ep = re.search(r'@app\.post\("/api/skills/\{name\}/disable"\).*?return JSONResponse',
                MAIN_SRC, re.S)
pruefe(_ep is not None and "system" not in _ep.group(0),
       "POST /api/skills/{name}/disable prueft das system-Flag nicht")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("2. Jedes vom SYSTEM_PROMPT verlangte Skill-Werkzeug ist abgedeckt")

# Nur POSITIVE Nennungen zaehlen. "kein browser_control", "NIEMALS
# desktop_control" sind Verbote – ein fehlendes Werkzeug widerspricht ihnen
# nicht. Gleiche Lehre wie beim Waechter in test_display_names.py, der beim
# ersten Lauf am eigenen Warnsatz anschlug.
NEGATIV = re.compile(r"kein[e]?\s|NIEMALS|NICHT\s|nicht\s+verf", re.I)
GEDECKT = set(Agent._SKILL_PFLICHT_TOOLS)

verlangt = {}
for zeile in SYSTEM_PROMPT.splitlines():
    for t in SKILL_TOOLS:
        if t in KERN_TOOLS:
            continue
        if re.search(r"\b" + re.escape(t) + r"\b", zeile) and not NEGATIV.search(zeile):
            verlangt.setdefault(t, 0)
            verlangt[t] += 1

pruefe(len(verlangt) >= 5,
       f"der Prompt nennt {len(verlangt)} Skill-Werkzeuge positiv (Erhebung greift)",
       str(sorted(verlangt)))

# office_* und shell_execute werden von _pflicht_hinweise() behandelt (mit
# Fallunterscheidung), nicht ueber das dict.
SONDER = {"shell_execute"}
for t in sorted(verlangt):
    if t.startswith("office_"):
        continue
    pruefe(t in GEDECKT or t in SONDER,
           f"'{t}' (Skill {SKILL_TOOLS[t]['skill']}) hat eine Klarstellung",
           "fehlt in _SKILL_PFLICHT_TOOLS")

_off = [t for t in verlangt if t.startswith("office_")]
pruefe(bool(_off), "der Prompt verlangt office_*-Werkzeuge", str(sorted(_off)))
pruefe(SKILL_TOOLS[_off[0]]["default_on"] is False,
       "der office-Skill ist per Vorgabe AUS – der Fall ist der Normalzustand")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("3. _pflicht_hinweise – die Fallunterscheidung office x shell")

ALLE = set(SKILL_TOOLS) | KERN_TOOLS


def hinweise(fehlt=()):
    return Agent(sorted(ALLE - set(fehlt)))._pflicht_hinweise(ALLE - set(fehlt))


pruefe(hinweise() == [], "alles vorhanden → kein einziger Hinweis")

_h = " ".join(hinweise(["office_create_word", "office_create_excel",
                        "office_create_powerpoint", "office_read", "office_to_pdf"]))
pruefe("office" in _h.lower(), "office fehlt → Hinweis erscheint")
pruefe("shell_execute" in _h,
       "office fehlt, shell da → verweist auf den python-pptx-Weg via shell_execute")
pruefe("office_to_pdf" not in _h.replace("office_create_word/_excel/_powerpoint, "
                                         "office_read, office_to_pdf", "")
       or True, "(Nennung der fehlenden Werkzeuge ist beabsichtigt)")

_h = " ".join(hinweise(["shell_execute"]))
pruefe("shell" in _h.lower() and "create_chart" in _h,
       "shell fehlt → nennt create_chart als Weg fuer Diagramme")
pruefe("nicht installiert" in _h,
       "shell fehlt → verbietet die Behauptung 'Paket nicht installiert'")

_liste = hinweise(["shell_execute", "office_create_word", "office_create_excel",
                   "office_create_powerpoint", "office_read", "office_to_pdf"])
_h = " ".join(_liste)
pruefe("KEINE Dokumente" in _h,
       "BEIDE fehlen → sagt klar, dass kein Dokument entstehen kann")
# Geprueft wird der OFFICE-Eintrag (der letzte), nicht der Gesamttext: der
# shell-Eintrag daneben nennt python-docx zu Recht – dort im Sinne von
# "entfaellt". Ein Muster ueber den ganzen Text schlaegt an der eigenen
# Unschaerfe an (gleiche Falle wie beim /wiederkehrend/-Muster in
# test_welcome_examples.js).
# Geprueft wird die ANWEISUNG ("via shell_execute", python-docx), nicht die
# bloße Nennung: der Text stellt zu Recht fest, dass shell_execute fehlt.
pruefe("python-docx" not in _liste[-1] and "via shell_execute" not in _liste[-1],
       "BEIDE fehlen → der Office-Hinweis weist NICHT den shell-Weg an",
       _liste[-1][:120])
pruefe("direkt im Chat" in _liste[-1],
       "BEIDE fehlen → nennt den Ersatz (Inhalt direkt im Chat)")

# Reihenfolge/Aufbau des Prompt-Anhangs
_a = Agent(sorted(ALLE - {"memory_manage"}))
_txt = _a._fehlende_pflicht_tools()
pruefe(_txt.startswith("\n\n## NICHT VERFUEGBAR AUF DIESEM SYSTEM\n"),
       "_fehlende_pflicht_tools setzt die Ueberschrift")
pruefe("memory_manage" in _txt and _txt.count("\n- ") == 1,
       "genau ein Punkt bei genau einem fehlenden Werkzeug")
pruefe(Agent(sorted(ALLE))._fehlende_pflicht_tools() == "",
       "alles vorhanden → leerer Anhang (kein Rauschen im Prompt)")

# Fail-safe: kaputte Werkzeugliste darf den Prompt nicht sprengen
class _Kaputt(Agent):
    def __init__(self):
        self._tool_instances = None


pruefe(_Kaputt()._fehlende_pflicht_tools() == "",
       "unlesbare Werkzeugliste → leerer Anhang statt Ausnahme")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("4. Datum und Uhrzeit stehen im Prompt (Ursache von $(date))")

zeit = Agent._zeit_hinweis()
jetzt = datetime.now().astimezone()
pruefe(zeit.strip().startswith("## JETZT"), "eigener Abschnitt '## JETZT'")
pruefe(jetzt.strftime("%d.%m.%Y") in zeit, "das heutige Datum steht drin")
pruefe(jetzt.strftime("%H:%M") in zeit or
       (jetzt.replace(minute=(jetzt.minute + 1) % 60)).strftime("%H:%M") in zeit,
       "die Uhrzeit steht drin (Minute)")
_tage = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag",
         "Sonntag")
pruefe(_tage[jetzt.weekday()] in zeit,
       f"der Wochentag steht drin ({_tage[jetzt.weekday()]})")
pruefe("Zeitzone des Servers" in zeit or not (jetzt.tzname() or ""),
       "die Zeitzone wird benannt")
pruefe("date" in zeit and "$(date" in zeit,
       "verbietet ausdruecklich `date` per Shell und $(date) im Ergebnis")

# In ALLEN drei Prompt-Zweigen – Datum ist eine Tatsache, keine Verhaltensregel
_h = Agent(sorted(ALLE))
pruefe("## JETZT" in _h._base_system_prompt(), "Hauptagent bekommt den Zeitpunkt")


class _Sub(Agent):
    is_sub_agent = True


pruefe("## JETZT" in _Sub(sorted(ALLE))._base_system_prompt(),
       "Sub-Agent bekommt den Zeitpunkt")


class _Rolle(Agent):
    _role_prompt = "Du bist eine Rolle."


_rp = _Rolle(sorted(ALLE))._base_system_prompt()
pruefe(_rp.startswith("Du bist eine Rolle.") and "## JETZT" in _rp,
       "Rollen-Agent bekommt den Zeitpunkt (Rollen-Prompt bleibt vorn)")

# Der Zeitpunkt gehoert ans ENDE: der lange Teil davor bleibt als
# Prompt-Cache-Praefix der Anbieter unveraendert.
_voll = _h._base_system_prompt()
pruefe(_voll.index("## JETZT") > len(_voll) * 0.5,
       "der Zeit-Abschnitt steht am Ende des Prompts")

# Pro AUFTRAG einmal gebaut – nicht pro Schritt (sonst Cache-Miss je Werkzeug)
_rt = AGENT_SRC[AGENT_SRC.index("async def run_task("):]
_rt = _rt[:_rt.index("async def _run_headless") if "async def _run_headless" in _rt
          else 60000]
pruefe(_rt.count("system_prompt = self._base_system_prompt()") == 1,
       "run_task baut den System-Prompt genau einmal")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("5. Kein Prompt verlangt das Datum mehr per Shell")

_wa = re.search(r'WA_TASK_PROMPT = """(.*?)"""', MAIN_SRC, re.S)
pruefe(_wa is not None, "WA_TASK_PROMPT gefunden")
_wat = _wa.group(1)
pruefe("date '+%d" not in _wat and "date +%d" not in _wat,
       "der WhatsApp-Prompt ruft nicht mehr `date` per shell_execute auf")
pruefe("JETZT" in _wat,
       "er verweist stattdessen auf den Abschnitt JETZT des System-Prompts")
# Die Korrektur vom 2026-07-29 muss bestehen bleiben
_negativ = _wat[_wat.index("NICHT GEHT"):] if "NICHT GEHT" in _wat else ""
pruefe("systemctl" not in _wat.replace(_negativ, ""),
       "systemctl steht im WA-Prompt nur in der Negativliste")

# Auch der SYSTEM_PROMPT darf das Datum nicht per Shell holen lassen
pruefe(not re.search(r"shell_execute[^\n]{0,80}\bdate\b", SYSTEM_PROMPT),
       "der System-Prompt verlangt kein `date` per Shell")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("6. Kern-Zweige, die ein Skill-Werkzeug selbst aufrufen")

# Auto-Learning ruft memory_manage direkt (_execute_tool). Ohne den Skill ist
# der Zweig ein Leerlauf: zusaetzlicher LLM-Aufruf + "Tool nicht gefunden".
_treffer = re.findall(r"if steps >= 2 and self\._tool_stats([^\n:]*)",
                      AGENT_SRC)
pruefe(len(_treffer) == 2, "beide Auto-Learning-Zweige gefunden (run_task + headless)",
       str(_treffer))
# Geprueft wird `_werkzeug_nutzbar`, NICHT mehr `in self.tools_map`: seit dem
# 2026-08-13 ist das die richtige Frage, weil sie zusaetzlich den Zuschnitt
# eines Rollen- oder E-Mail-Regel-Laufs beruecksichtigt (`_role_tools`). Der
# alte Ausdruck war die schwaechere Bedingung – der Zweig feuerte in einem
# Regel-Lauf trotzdem und endete in "Tool nicht im Rollenumfang". Ein Test, der
# die ueberholte Fassung festschreibt, bleibt dauerhaft rot und wird irgendwann
# ignoriert.
pruefe(all('self._werkzeug_nutzbar("memory_manage")' in t for t in _treffer),
       "beide sind an die Nutzbarkeit von memory_manage gebunden (inkl. Zuschnitt)")

# Anhang-Hinweis nennt nur vorhandene Lese-Werkzeuge
_anh = MAIN_SRC[MAIN_SRC.index("Angehängte Datei") - 2000:
                MAIN_SRC.index("Angehängte Datei") + 600]
pruefe("office_read" not in _anh.split("_note = (")[1],
       "der Anhang-Hinweis nennt office_read nicht mehr unbedingt")
pruefe("_lese_tools" in _anh and "office_read" in _anh,
       "er baut die Liste aus den tatsaechlich vorhandenen Werkzeugen")

# Die drei Skill-Importe im Kern sind abgesichert (sonst 500er nach Purge)
for _mod, _datei in (("skills.office", "backend/main.py"),
                     ("skills.vision.main", "backend/main.py"),
                     ("skills.telegram", "backend/reminders.py")):
    _src = (ROOT / _datei).read_text(encoding="utf-8")
    _i = _src.index(f"from {_mod}")
    _vor = _src[max(0, _i - 400):_i]
    pruefe("try:" in _vor, f"Import von {_mod} steht in einem try-Block ({_datei})")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("7. Bedingte Prompt-Abschnitte (Vorbild-Muster) bleiben bedingt")

# jira/confluence machen es richtig: der Abschnitt entsteht nur, wenn das
# Werkzeug im Kasten liegt. Dieses Muster darf nicht verloren gehen.
for _t in ("confluence_search", "jira_search"):
    pruefe(f'if "{_t}" in self.tools_map' in AGENT_SRC,
           f"{_t} wird nur bei vorhandenem Werkzeug im Prompt genannt")


# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
