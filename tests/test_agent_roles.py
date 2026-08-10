#!/usr/bin/env python3
"""Tests: spezialisierte Rollen-Agenten + delegate (sequenziell, mit Rueckmeldung).

WAS HIER ABGESICHERT WIRD
-------------------------
1. **Die Sicherheitsformel.** ``effektive_werkzeuge()`` = Rollen-Whitelist ∩
   (Werkzeuge des Aufrufers − Sperrliste) − delegate. Eine Rolle darf nur
   WEGNEHMEN. Kehrt jemand die Richtung um, ist "Rolle X darf Werkzeug Y" der
   bequemste Weg um ``_BLOCKED_TOOLS_FOR_LDAP`` – also eine dauerhafte
   Rechteerhoehung fuer jeden, der delegieren darf.
2. **Die harte Schranke im Dispatch.** Der Filter in ``_llm_tools`` bestimmt nur,
   was das Modell SIEHT. Modelle rufen auch nicht deklarierte Werkzeuge auf –
   ohne die Pruefung in ``_execute_tool`` waere der Zuschnitt eine Bitte.
3. **Rekursion und Kosten.** Ein Rollen-Agent hat kein ``delegate`` (erste
   Schranke) und der Deckel ``_MAX_DELEGATIONS`` gilt pro Auftrag (zweite).
4. **Die Whitelist beim Aendern.** ``UPDATABLE_FIELDS`` – ohne sie nimmt ein
   ``PUT`` beliebige Felder an (dieselbe Luecke, die scheduler.update_job bis
   2026-07-28 hatte).
5. **Saeen nur beim ersten Mal.** Eine geloeschte Rolle darf nicht bei jedem
   Start zurueckkommen (Lehre aus _seed_instructions).

SANDKASTEN – WICHTIG
--------------------
Teil 1 biegt ``agent_roles.ROLES_FILE`` in ein Wegwerf-Verzeichnis um und prueft
das ausdruecklich nach: bei einer Gegenprobe gegen einen aelteren Modulstand
kann die Umbiegung ins Leere greifen, und dann schreibt der Test in die ECHTE
data/agent_roles.json (genau das ist bei tests/test_log_retention.py passiert).

Teil 3 importiert ``backend.agent`` und damit ``backend.config`` – das kann bei
einer Profil-Migration die Live-settings.json zurueckschreiben. Der Test
vergleicht sie deshalb per md5 vor und nach dem Lauf.

    python3 tests/test_agent_roles.py
"""

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("1. Registry (data/agent_roles.json)")

from backend import agent_roles as R  # noqa: E402

_tmp = Path(tempfile.mkdtemp(prefix="jarvis_rollen_"))
R.ROLES_FILE = _tmp / "agent_roles.json"

# Sandkasten-Schranke: zeigt die Datei WIRKLICH ins Wegwerf-Verzeichnis?
if not str(R.ROLES_FILE).startswith(str(_tmp)):
    print(f"ABBRUCH: ROLES_FILE zeigt auf {R.ROLES_FILE} – nicht in den Sandkasten!")
    sys.exit(2)
pruefe(str(R.ROLES_FILE).startswith(str(_tmp)), "Sandkasten aktiv (echte Datei unberuehrt)")

# ── Saeen ────────────────────────────────────────────────────────────────────
n = R.saeen()
pruefe(n == 3, f"Saeen legt die drei Vorgabe-Rollen an ({n})")
pruefe(R.namen() == ["image_builder", "analyst", "writer"],
       "Kennungen wie vorgesehen", str(R.namen()))
pruefe(R.saeen() == 0, "zweiter Lauf saet NICHT erneut (idempotent)")

# Vorgabe-Rollen tragen KEINE Profil-UUID: eine fest verdrahtete zeigt auf einem
# fremden System ins Nichts.
# Im QUELLTEXT darf keine UUID stehen (auf einem fremden System zeigt sie ins
# Nichts). Beim SAEEN darf `image_builder` dagegen ein zur Laufzeit gefundenes
# Bildprofil bekommen – ohne eines ist die Rolle wertlos und sagt bei jedem
# Bildauftrag nur ab (auf DEV genau so passiert, 2026-08-10).
import re as _re
_SRC_ROLES = (ROOT / "backend" / "agent_roles.py").read_text(encoding="utf-8")
pruefe(not _re.search(r'"profile_id":\s*"[0-9a-f]{8}-', _SRC_ROLES),
       "keine Vorgabe-Rolle hat eine fest verdrahtete Profil-UUID im Quelltext")
pruefe(all(r["profile_id"] == "" for r in R.alle() if r["id"] != "image_builder"),
       "analyst/writer erben das Profil des Aufrufers")
pruefe("def _bildprofil_finden" in _SRC_ROLES
       and "image_builder" in _SRC_ROLES.split("def saeen")[1],
       "image_builder bekommt beim Saeen ein bildfaehiges Profil, falls vorhanden")
pruefe(all(r["description"] for r in R.alle()),
       "jede Vorgabe-Rolle hat eine Beschreibung (Grundlage der Modell-Auswahl)")
pruefe(all(R.DELEGATE_TOOL not in r["tools"] for r in R.alle()),
       "keine Vorgabe-Rolle darf delegieren")

# Geloeschte Rolle darf nicht zurueckkommen
R.loeschen("writer")
R.saeen()
pruefe("writer" not in R.namen(), "geloeschte Rolle kommt beim Saeen NICHT zurueck")

# ── Dateirechte ──────────────────────────────────────────────────────────────
mode = R.ROLES_FILE.stat().st_mode & 0o777
pruefe(mode == 0o640, f"Datei wird mit 0640 angelegt ({oct(mode)})")

# ── Anlegen / Validierung ────────────────────────────────────────────────────
r = R.anlegen({"id": "tester", "name": "Tester", "description": "prueft",
               "prompt": "Du pruefst.", "tools": ["filesystem", "delegate", "filesystem"]})
pruefe(r["tools"] == ["filesystem"],
       "delegate und Doppelte werden aus der Whitelist entfernt", str(r["tools"]))

# Zwei Faelle werden bewusst NORMALISIERT statt abgewiesen – eine Kennung mit
# Grossbuchstaben ist ein Tippfehler mit klarer Absicht, und ein fehlender
# Anzeigename ist kein Grund, die Rolle zu verweigern.
_gross = R.anlegen({"id": "Tester2", "name": "x", "description": "d", "prompt": "p"})
pruefe(_gross["id"] == "tester2", "Grossbuchstaben werden kleingeschrieben, nicht abgewiesen")
_ohnename = R.anlegen({"id": "ohnename", "name": "", "description": "d", "prompt": "p"})
pruefe(_ohnename["name"] == "ohnename", "fehlender Anzeigename faellt auf die Kennung zurueck")
R.loeschen("tester2")
R.loeschen("ohnename")

for schlecht, warum in [
    ({"id": "a", "name": "x", "description": "d", "prompt": "p"}, "zu kurz"),
    ({"id": "mit leer", "name": "x", "description": "d", "prompt": "p"}, "Leerzeichen"),
    ({"id": "tester", "name": "x", "description": "d", "prompt": "p"}, "Kennung doppelt"),
    ({"id": "ohnedesc", "name": "x", "description": "", "prompt": "p"}, "keine Beschreibung"),
    ({"id": "ohneprompt", "name": "x", "description": "d", "prompt": ""}, "kein Prompt"),
    ({"id": "", "name": "x", "description": "d", "prompt": "p"}, "keine Kennung"),
]:
    try:
        R.anlegen(schlecht)
        pruefe(False, f"abgewiesen: {warum}")
    except ValueError as e:
        pruefe(True, f"abgewiesen: {warum} ({str(e)[:40]}…)")

# ── Aendern: Whitelist ───────────────────────────────────────────────────────
geaendert = R.aendern("tester", {"name": "Tester neu", "id": "boeswillig",
                                 "heimlich": "wert", "max_steps": 999})
pruefe(geaendert["id"] == "tester", "die Kennung ist NICHT aenderbar")
pruefe("heimlich" not in geaendert, "unbekannte Felder werden verworfen")
pruefe(geaendert["max_steps"] == R.MAX_STEPS_CAP,
       f"max_steps wird gedeckelt ({geaendert['max_steps']})")
pruefe(geaendert["name"] == "Tester neu", "erlaubtes Feld wird uebernommen")
pruefe(all(f in R.UPDATABLE_FIELDS for f in ("name", "prompt", "tools", "profile_id"))
       and "id" not in R.UPDATABLE_FIELDS,
       "UPDATABLE_FIELDS enthaelt die Nutzfelder, aber nicht 'id'")

try:
    R.aendern("gibtsnicht", {"name": "x"})
    pruefe(False, "Aendern einer unbekannten Rolle wirft")
except ValueError as e:
    pruefe("nicht gefunden" in str(e), "Aendern einer unbekannten Rolle: 'nicht gefunden'")

pruefe(R.loeschen("tester") is True, "Loeschen meldet Erfolg")
pruefe(R.loeschen("tester") is False, "zweites Loeschen meldet False (kein Fehler)")

# ── Deckel ───────────────────────────────────────────────────────────────────
_vorher = len(R.alle())
for i in range(R.MAX_ROLLEN):
    try:
        R.anlegen({"id": f"r{i:02d}", "name": f"R{i}", "description": "d", "prompt": "p"})
    except ValueError as e:
        pruefe("hoechstens" in str(e), f"Deckel bei {len(R.alle())} Rollen greift")
        break
else:
    pruefe(False, "Deckel MAX_ROLLEN greift")
pruefe(len(R.alle()) <= R.MAX_ROLLEN, f"nie mehr als {R.MAX_ROLLEN} Rollen")

# ── Beschaedigte Datei ───────────────────────────────────────────────────────
R.ROLES_FILE.write_text('{"version":1,"roles":[{"id":"gut","name":"G","description":"d",'
                        '"prompt":"p"},{"kaputt":true},"nur ein string"]}', encoding="utf-8")
pruefe(R.namen(nur_aktive=False) == ["gut"],
       "beschaedigte Eintraege werden uebersprungen, nicht die ganze Datei verworfen",
       str(R.namen(nur_aktive=False)))
R.ROLES_FILE.write_text("kein json", encoding="utf-8")
pruefe(R.alle() == [], "unlesbare Datei gilt als leer (kein Absturz)")

# ── Die Sicherheitsformel ────────────────────────────────────────────────────
abschnitt("2. effektive_werkzeuge – die Formel")

rolle = {"id": "x", "tools": ["filesystem", "shell_execute", "spawn_agent",
                              "office_read", "delegate"]}
verfuegbar = {"filesystem", "shell_execute", "spawn_agent", "delegate", "knowledge_search"}

erlaubt, fehlend = R.effektive_werkzeuge(rolle, verfuegbar, gesperrt=set())
pruefe(erlaubt == {"filesystem", "shell_execute", "spawn_agent"},
       "privilegiert: Whitelist ∩ verfuegbar", str(sorted(erlaubt)))
pruefe("delegate" not in erlaubt, "delegate ist NIE dabei (Rekursionsschutz)")
pruefe(fehlend == ["office_read"], f"fehlende Werkzeuge werden gemeldet ({fehlend})")

erlaubt2, fehlend2 = R.effektive_werkzeuge(
    rolle, verfuegbar, gesperrt={"spawn_agent", "shell_execute"})
pruefe(erlaubt2 == {"filesystem"},
       "unprivilegiert: die Sperrliste nimmt weg", str(sorted(erlaubt2)))
pruefe("spawn_agent" in fehlend2 and "shell_execute" in fehlend2,
       "gesperrte Werkzeuge stehen in 'fehlend' (der Aufrufer erfaehrt es)")

# Eine Rolle kann NICHT hinzufuegen
erlaubt3, _ = R.effektive_werkzeuge({"id": "y", "tools": ["gibt_es_nicht"]},
                                    verfuegbar, gesperrt=set())
pruefe(erlaubt3 == set(), "eine Rolle kann kein unbekanntes Werkzeug hinzufuegen")

# Leere Whitelist = Rolle ohne Werkzeuge (legitim), NICHT "alle"
erlaubt4, _ = R.effektive_werkzeuge({"id": "z", "tools": []}, verfuegbar, gesperrt=set())
pruefe(erlaubt4 == set(), "leere Whitelist heisst KEINE Werkzeuge (nicht alle)")

# Beschreibung fuers Werkzeug
R.ROLES_FILE.write_text(json.dumps({"version": 1, "roles": [
    {"id": "aktiv", "name": "A", "description": "macht A", "prompt": "p", "enabled": True},
    {"id": "aus", "name": "B", "description": "macht B", "prompt": "p", "enabled": False},
]}), encoding="utf-8")
txt = R.werkzeug_beschreibung()
pruefe("aktiv" in txt and "macht A" in txt, "Werkzeug-Beschreibung nennt aktive Rollen")
pruefe("aus" not in txt, "abgeschaltete Rollen stehen NICHT in der Beschreibung")
pruefe(R.namen(nur_aktive=True) == ["aktiv"], "namen(nur_aktive) filtert")

# Denktiefen-Stufen muessen zu llm.REASONING_LEVELS passen (Quelltext, kein Import:
# backend.llm zieht die Provider-SDKs mit).
LLM_SRC = (ROOT / "backend" / "llm.py").read_text(encoding="utf-8")
m = re.search(r"REASONING_LEVELS\s*=\s*[\(\[]([^\)\]]*)[\)\]]", LLM_SRC)
stufen = set(re.findall(r'"([a-z]+)"', m.group(1))) if m else set()
pruefe(stufen and stufen | {""} == set(R.EFFORT_STUFEN),
       "EFFORT_STUFEN deckt sich mit llm.REASONING_LEVELS (+ leer)",
       f"{sorted(stufen)} vs {sorted(R.EFFORT_STUFEN)}")

# Modul haengt nicht an backend.config (das wuerde die Live-settings.json migrieren)
SRC_R = (ROOT / "backend" / "agent_roles.py").read_text(encoding="utf-8")
# Entscheidend ist die MODULEBENE: ein Import dort loest beim bloßen `import
# backend.agent_roles` die Profil-Migration aus und schreibt die Live-
# settings.json zurueck. Ein LAZY Import in einer Funktion (hier
# `_bildprofil_finden`, das ein bildfaehiges Profil sucht) ist unschaedlich –
# er laeuft nur, wenn die Funktion gerufen wird.
_modulebene = [z for z in SRC_R.splitlines()
               if z.startswith(("import ", "from ")) and "config" in z]
pruefe(not _modulebene,
       "agent_roles.py importiert backend.config NICHT auf Modulebene",
       str(_modulebene))
pruefe("from backend.config import config" in SRC_R
       and SRC_R.count("    from backend.config") >= 1,
       "…sondern nur lazy in der Funktion")

shutil.rmtree(_tmp, ignore_errors=True)

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("3. Quelltext: Verdrahtung und Schranken")

AGENT = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SBX = (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8")
SKILL = ROOT / "skills" / "agent_orchestrator"
DEL = (SKILL / "main.py").read_text(encoding="utf-8")
MANIFEST = json.loads((SKILL / "skill.json").read_text(encoding="utf-8"))

# a) Der Werkzeugsatz, der ans Modell geht, ist gefiltert – an ALLEN Aufrufen
pruefe("tools=self._tool_instances" not in AGENT,
       "kein Provider-Aufruf umgeht den Filter (tools=self._tool_instances)")
pruefe(AGENT.count("tools=self._llm_tools") >= 6,
       f"alle Provider-Aufrufe nutzen _llm_tools ({AGENT.count('tools=self._llm_tools')})")

# b) Harte Schranke im Dispatch, VOR der Ausfuehrung
i_map = AGENT.find("tool = self.tools_map.get(name)")
i_allow = AGENT.find('_allow = getattr(self, "_role_tools", None)')
i_exec = AGENT.find("await tool.execute(")
pruefe(0 < i_map < i_allow < i_exec,
       "Rollen-Schranke liegt zwischen Werkzeug-Suche und Ausfuehrung")
pruefe("if _allow is not None and name not in _allow" in AGENT,
       "die Schranke prueft auf `is not None` (leere Menge = keine Werkzeuge)")

# c) Delegation an beiden Loops, sequenziell
pruefe(AGENT.count("await self._maybe_delegate(") == 2,
       f"Marker wird in run_task UND _run_headless aufgeloest ({AGENT.count('await self._maybe_delegate(')})")
pruefe("await agent.run_task_headless(" in AGENT,
       "der Rollen-Lauf wird ABGEWARTET (sequenziell, mit Rueckmeldung)")
pruefe("asyncio.create_task(agent.run_task_headless" not in AGENT,
       "kein fire-and-forget beim Rollen-Lauf")

# d) Actor wird ausdruecklich uebergeben (fail-closed)
i_run = AGENT.find("await agent.run_task_headless(")
fenster = AGENT[i_run:i_run + 700]
pruefe('"privileged": self._actor_is_privileged()' in fenster,
       "Privileg des Auftraggebers wird uebergeben (kein Standard 'privilegiert')")
pruefe('"user": self.actor_name()' in fenster, "Benutzer des Auftrags wird uebergeben")
pruefe('"internet"' in fenster and '"sap"' in fenster,
       "Internet-/SAP-Freigabe wird mitvererbt")

# e) Sperrliste greift nur fuer Unprivilegierte – wie im Dispatch
pruefe("if not self._actor_is_privileged():\n            gesperrt = set(_BLOCKED_TOOLS_FOR_LDAP)" in AGENT,
       "die Sperrliste wird bei unprivilegierten Auftraggebern angewandt")

# f) delegate ist NICHT gesperrt (Netzwerk-Benutzer duerfen delegieren) …
i_blocked = AGENT.find("_BLOCKED_TOOLS_FOR_LDAP = {")
block = AGENT[i_blocked:AGENT.find("}", i_blocked)]
pruefe('"delegate"' not in block,
       "delegate steht NICHT in _BLOCKED_TOOLS_FOR_LDAP (Netzwerk-Benutzer duerfen es)")
pruefe('"spawn_agent"' in block, "spawn_agent bleibt gesperrt (unveraendert)")

# g) … dafuer haben Rollen- und Sub-Agenten kein delegate
# Das Werkzeug kommt aus dem SKILL, nicht mehr aus backend/tools –
# `get_enabled_tools()` liefert es aber an JEDEN Agenten, also muss es
# Sub-/Rollen-Agenten aktiv entzogen werden (sonst Rekursion).
pruefe(not (ROOT / "backend" / "tools" / "delegate.py").exists(),
       "backend/tools/delegate.py ist entfernt (das Werkzeug lebt im Skill)")
pruefe("from backend.tools.delegate import" not in AGENT,
       "agent.py importiert das Werkzeug NICHT mehr direkt")
pruefe('if getattr(t, "name", "") != "delegate"' in AGENT,
       "Sub-/Rollen-Agenten wird `delegate` aktiv entzogen (Rekursionsschutz)")
i_entz = AGENT.find('if getattr(t, "name", "") != "delegate"')
pruefe("else:" in AGENT[max(0, i_entz - 800):i_entz]
       and "if not is_sub_agent:" in AGENT[max(0, i_entz - 800):i_entz],
       "der Entzug haengt am is_sub_agent-Zweig")

# Der Skill ist die Schranke: kein Skill -> kein Werkzeug -> kein Prompt-Hinweis
pruefe("def _delegation_moeglich" in AGENT,
       "es gibt EINEN Test dafuer, ob Delegation moeglich ist")
pruefe('any(getattr(t, "name", "") == "delegate" for t in self._tool_instances)' in AGENT,
       "geprueft wird der WERKZEUGKASTEN, nicht der Skill-Name")
i_hint = AGENT.find("def _role_hinweis")
pruefe("if not self._delegation_moeglich():" in AGENT[i_hint:i_hint + 1800],
       "ohne Delegation kein Rollen-Abschnitt im System-Prompt")
i_fb2 = AGENT.find("async def _role_fallback")
pruefe("if not self._delegation_moeglich():" in AGENT[i_fb2:i_fb2 + 2200],
       "ohne Delegation kein Rollen-Rueckfall")

# Manifest
pruefe(MANIFEST.get("tools") == ["delegate"],
       f"Manifest bietet genau `delegate` an ({MANIFEST.get('tools')})")
pruefe(MANIFEST.get("enabled") is False,
       "der Skill ist standardmaessig AUS (Opt-in)")
pruefe("config_schema" not in MANIFEST,
       "kein config_schema – der Reiter zeigt die Rollen-Verwaltung, kein generisches Formular")
# Die vier alten Namen dürfen im ERKLAERENDEN Kommentar stehen (der Modulkopf
# sagt, was hier vorher war und warum es ersetzt wurde) – aber nicht mehr als
# Code. Geprueft wird deshalb der Quelltext OHNE Kommentar- und Doku-Zeilen.
def _nur_code(quelle: str) -> str:
    aus, in_doc = [], False
    for z in quelle.splitlines():
        st = z.strip()
        if st.startswith('"""') or st.endswith('"""'):
            # Modul-/Klassen-Docstrings ueberspringen (auch mehrzeilig)
            in_doc = not in_doc if st.count('"""') == 1 else in_doc
            continue
        if in_doc or st.startswith("#"):
            continue
        aus.append(z)
    return "\n".join(aus)

DEL_CODE = _nur_code(DEL)
for tot in ("orchestrate_task", "agent_status", "agent_collect", "agent_list"):
    pruefe(tot not in DEL_CODE,
           f"das funktionslose Werkzeug '{tot}' ist als Code entfernt")
pruefe(MANIFEST.get("tools") == ["delegate"] and "orchestrate_task" not in str(MANIFEST.get("tools")),
       "das Manifest bietet keines der alten Werkzeuge mehr an")
pruefe("agent-workspaces" not in DEL_CODE,
       "kein Code mehr fuer das alte inbox/outbox-Protokoll")
pruefe("WAS HIER VORHER STAND" in DEL,
       "der Modulkopf erklaert, was ersetzt wurde (Projektstil)")
pruefe("def get_tools" in DEL and "_saeen_still()" in DEL,
       "die Vorgabe-Rollen entstehen beim LADEN des Skills")
pruefe("async def startup_seed_agent_roles" not in MAIN,
       "kein Startup-Hook mehr im Backend (das Saeen haengt am Skill)")

# ── Regression 2026-08-10: image_gen darf seine oeffentlichen Namen behalten ──
# Beim Umstellen auf provider_fuer_lauf fiel `record_task_image` einem
# Block-Ersatz zum Opfer. Folge: `image_search.py` liess sich nicht importieren,
# das Werkzeug `search_image` fehlte STILL im Werkzeugkasten (nur an einer
# Werkzeug-Zaehlung aufgefallen). Ein Quelltext-Test allein hat das nicht
# gesehen – deshalb hier die Namen, die andere Module importieren.
_IMGQ = (ROOT / "backend" / "tools" / "image_gen.py").read_text(encoding="utf-8")
for name in ("def record_task_image", "def strip_image_refs", "current_task_images",
             "_IMG_DIR"):
    pruefe(name in _IMGQ, f"image_gen behaelt '{name}' (wird anderswo importiert)")
_IMGSEARCH = (ROOT / "backend" / "tools" / "image_search.py").read_text(encoding="utf-8")
for imp in re.findall(r"from backend\.tools\.image_gen import ([^\n#]+)", _IMGSEARCH):
    for teil in imp.split(","):
        teil = teil.strip()
        if teil:
            pruefe(teil in _IMGQ,
                   f"image_search importiert '{teil}' – muss in image_gen vorhanden sein")

# ── Zwei Altfehler, die erst durch den Skill sichtbar wurden ────────────────
# 1. reload_skills() ersetzte `_tool_instances` durch die Skill-Werkzeuge und
#    verlor dabei ALLE im Konstruktor angehaengten (spawn_agent, create_chart,
#    generate_image, search_image, Clipboard, Desktop, reflection) – bis zum
#    naechsten Dienst-Neustart, nach JEDEM Skill-Toggle.
pruefe("def _attach_extra_tools" in AGENT,
       "die Nicht-Skill-Werkzeuge haengen in einer eigenen Methode")
pruefe(AGENT.count("self._attach_extra_tools()") == 2,
       f"aufgerufen im Konstruktor UND in reload_skills ({AGENT.count('self._attach_extra_tools()')})")
i_rl = AGENT.find("def reload_skills")
fenster_rl = AGENT[i_rl:i_rl + 1600]
pruefe("self._attach_extra_tools()" in fenster_rl,
       "reload_skills stellt die Zusatz-Werkzeuge wieder her")
pruefe("_gesehen" in fenster_rl,
       "reload_skills entfernt Doppelte nach Namen")
# 2. Der Skill-Toggle lud nur `agent_instance` – nicht den Hauptagenten, auf dem
#    die Chats laufen.
pruefe("def _reload_agent_tools" in MAIN,
       "es gibt einen Helfer, der ALLE lebenden Agenten neu laedt")
pruefe("agent_manager.main_agent" in MAIN[MAIN.find("def _reload_agent_tools"):
                                         MAIN.find("def _reload_agent_tools") + 1600],
       "der Helfer erfasst auch agent_manager.main_agent (dort laufen die Chats)")
pruefe("agent_instance.reload_skills()" not in MAIN,
       "keine Aufrufstelle laedt mehr nur den Verwaltungs-Agenten")
pruefe(MAIN.count("_reload_agent_tools()") >= 6,
       f"alle Skill-Toggle-Stellen nutzen den Helfer ({MAIN.count('_reload_agent_tools()')})")

# Oberflaeche: Reiter nur bei aktivem Skill (vorhandenes Muster), kein
# generisches Formular mehr fuer diesen Skill.
SKCFG = (ROOT / "frontend" / "js" / "skillcfg.js").read_text(encoding="utf-8")
pruefe("agent_orchestrator: 'settings-tab-btn-orchestrator'" in SKCFG,
       "der Reiter-Knopf bleibt an den Skill-Zustand gekoppelt (TAB_BUTTONS)")
pruefe("agent_orchestrator: { container:" not in SKCFG,
       "kein generisches Manifest-Formular fuer diesen Skill (TARGETS)")
pruefe("is_sub_agent=True," in AGENT[AGENT.find("def spawn_role_agent"):
                                     AGENT.find("def spawn_role_agent") + 1400],
       "spawn_role_agent erzeugt einen Sub-Agenten (kein spawn_agent/delegate)")
i_mb = AGENT.find("async def _maybe_delegate")
fenster_mb = AGENT[i_mb:i_mb + 900]
pruefe('if getattr(self, "_role_id", ""):' in fenster_mb and "return result_str" in fenster_mb,
       "zweiter Riegel: ein Rollen-Agent loest keinen Delegations-Marker auf")

# h) Deckel pro Lauf + Reset
pruefe("_MAX_DELEGATIONS = " in AGENT, "Deckel _MAX_DELEGATIONS existiert")
pruefe(AGENT.count("self._delegations_used = 0") >= 2,
       "der Zaehler wird in run_task UND _run_headless zurueckgesetzt")
pruefe("_DELEGATE_RESULT_MAX" in AGENT and "[gekuerzt:" in AGENT,
       "Ergebnis-Deckel vorhanden UND die Kuerzung wird ausgewiesen")

# i) Profil-Vorrang der Rolle
i_prof = AGENT.find("def _resolve_profile_for_user")
fenster_p = AGENT[i_prof:i_prof + 1200]
pruefe('if getattr(self, "_role_profile_id", "")' in fenster_p,
       "das Rollen-Profil hat Vorrang vor der Benutzerwahl")
pruefe("profile_for_user" in fenster_p,
       "ohne Rollen-Profil gilt weiterhin die Benutzerwahl (unveraendert)")

# j) System-Prompt und Schrittgrenze der Rolle
pruefe("def _base_system_prompt" in AGENT and 'if getattr(self, "_role_prompt", "")' in AGENT,
       "der Rollen-Prompt ersetzt den System-Prompt")
i_bp = AGENT.find("def _base_system_prompt")
fenster_bp = AGENT[i_bp:i_bp + 400]
pruefe("return self.SUB_AGENT_PROMPT" in fenster_bp and "self.SYSTEM_PROMPT" in fenster_bp,
       "ohne Rolle bleibt die alte Prompt-Weiche erhalten (Sub-Agent/Hauptagent)")

# ── Prompt-Hinweis und Rollen-Rueckfall (beide aus der DEV-Messung entstanden) ──
pruefe("def _role_hinweis" in AGENT and "SPEZIALISIERTE ROLLEN" in AGENT,
       "der System-Prompt nennt die Rollen zusaetzlich zur Werkzeug-Beschreibung")
pruefe("if not liste:\n            return \"\"" in AGENT,
       "ohne eingerichtete Rolle bleibt der System-Prompt unveraendert")
pruefe("def _role_fallback" in AGENT, "Rollen-Rueckfall bei gescheitertem Werkzeug")
i_fb = AGENT.find("async def _role_fallback")
fenster_fb = AGENT[i_fb:i_fb + 2600]
pruefe("self._looks_like_error(result_str)" in fenster_fb,
       "der Rueckfall greift nur bei einem GESCHEITERTEN Aufruf")
pruefe('if r.get("profile_id")' in fenster_fb,
       "nur Rollen mit EIGENEM Profil – sonst waere die Delegation wirkungslos")
pruefe("if not mit_profil:" in fenster_fb and "kein eigenes LLM-Profil zugewiesen" in fenster_fb,
       "ohne eigenes Profil: Klartext-Hinweis statt sinnloser Delegation")
pruefe("if tool_name in self._fallback_used:" in fenster_fb,
       "hoechstens ein Rueckfall je Werkzeug und Lauf (kein Ping-Pong)")
# generate_image muss das Profil des LAUFENDEN Agenten benutzen – sonst ist eine
# Rolle mit eigenem Bildmodell wirkungslos (auf DEV gemessen: die Rolle bekam
# trotz zugewiesenem Gemini-Profil die Absage des Textmodells).
IMG = (ROOT / "backend" / "tools" / "image_gen.py").read_text(encoding="utf-8")
_LLMQ = (ROOT / "backend" / "llm.py").read_text(encoding="utf-8")
pruefe("provider_fuer_lauf" in IMG and "current_agent_profile as current_llm_profile" in IMG,
       "image_gen nutzt den zentralen Helfer (alter Name bleibt als Alias)")
pruefe("data = await provider.generate_image(modell, prompt)" in IMG,
       "auch das MODELL kommt aus dem Profil des Agenten")
pruefe("if not isinstance(p, dict) or not p:" in _LLMQ,
       "ohne gesetztes Profil gilt unveraendert das globale (kein Verhaltensbruch)")
# Das Google-Bildmodell darf NICHT fest verdrahtet sein: imagen-3.0 war am
# 2026-08-10 abgekuendigt (404) – damit war die Bildgenerierung fuer JEDES
# Google-Profil tot, obwohl das Konto imagen-4.0 und gemini-*-image anbot.
pruefe("imagen-4.0-generate-001" in _LLMQ,
       "aktuelle Imagen-Modelle sind Kandidaten")
pruefe("ist_bildmodell" in _LLMQ,
       "ein Profil-Modell, das selbst ein Bildmodell ist, wird zuerst benutzt")
pruefe("_via_gemini" in _LLMQ and "inline_data" in _LLMQ,
       "Gemini-Bildmodelle (generateContent + inline_data) werden unterstuetzt")
pruefe("self.client.models.list()" in _LLMQ,
       "letzter Rueckfall: Bildmodelle des Kontos suchen statt Namen zu raten")
pruefe("current_agent_profile as _cvp" in AGENT and "_cvp.reset(_p_token)" in AGENT,
       "agent.py setzt das Profil pro Werkzeug-Aufruf und nimmt es zurueck")

# ── Alle Werkzeuge, die selbst ein Modell rufen, MUESSEN provider_fuer_lauf nutzen ──
# Sonst gilt dort weiter das global aktive Profil und das Profil einer Rolle (bzw.
# die benutzerbezogene Wahl) ist wirkungslos. Der Befund vom 2026-08-10 umfasste
# vier Stellen; dieser Waechter haelt sie fest.
LLM = (ROOT / "backend" / "llm.py").read_text(encoding="utf-8")
pruefe("current_agent_profile" in LLM and "def provider_fuer_lauf" in LLM,
       "llm.py stellt ContextVar + provider_fuer_lauf zentral bereit")
pruefe("BEWUSSTE AUSNAHME" in LLM and "_sec_llm_classify" in LLM,
       "die Ausnahme (Jailbreak-Klassifikator) ist am Helfer dokumentiert")

for rel, was in [("backend/tools/reflection.py", "reflection"),
                 ("skills/jira/main.py", "jira_org_analysis"),
                 ("skills/cognitive_evolution/engine.py", "evolution_*"),
                 ("backend/tools/image_gen.py", "generate_image"),
                 ("backend/web_extractor.py", "Extraktor-Rueckfall")]:
    q = (ROOT / rel).read_text(encoding="utf-8")
    pruefe("provider_fuer_lauf" in q, f"{was}: nutzt das Profil des laufenden Agenten")
    pruefe("config.LLM_PROVIDER" not in q and "_cfg.LLM_PROVIDER" not in q,
           f"{was}: baut den Provider NICHT mehr aus der globalen Config")

# Der Klassifikator der Sicherheitsschicht bleibt global – sonst haengt die
# Jailbreak-Pruefung am Profil dessen, der geprueft wird.
i_sec = MAIN.find("async def _sec_llm_classify")
fenster_sec = MAIN[i_sec:i_sec + 3000]
pruefe("config.LLM_PROVIDER" in fenster_sec,
       "_sec_llm_classify nutzt WEITER das globale Profil (Ausnahme)")
# Auf den AUFRUF pruefen, nicht auf das Wort – und dabei Kommentarzeilen
# ausblenden: der Kommentar dort nennt den Helfer ausdruecklich als das, was
# hier NICHT benutzt wird (daran ist dieser Test beim ersten Lauf gescheitert).
_code_sec = "\n".join(z for z in fenster_sec.splitlines()
                      if not z.lstrip().startswith("#"))
pruefe("provider_fuer_lauf" not in _code_sec,
       "_sec_llm_classify ruft den Helfer NICHT auf (nur im Kommentar erwaehnt)")
pruefe("BEWUSST das GLOBALE Profil" in fenster_sec,
       "die Ausnahme ist an der Stelle selbst begruendet")

pruefe("hinweis_an_nutzer" in AGENT,
       "die Fehlererkennung kennt die Konvention HINWEIS_AN_NUTZER (generate_image!)")
# Der System-Prompt darf dem Mechanismus nicht widersprechen: bis 2026-08-10 stand
# dort "KEIN Ersatz, kein anderes Profil" – das verbietet genau die Rolle mit
# eigenem Bildmodell (dieselbe Fehlerklasse wie beim alten WA_TASK_PROMPT).
i_bild = AGENT.find("15. BILDER")
fenster_bild = AGENT[i_bild:i_bild + 700]
pruefe("delegiere dorthin" in fenster_bild,
       "der Bild-Abschnitt des System-Prompts erlaubt die Delegation an eine Rolle")
pruefe("KEINE Web-Suche als Ersatz" in fenster_bild,
       "das Verbot der Web-Suche als Bild-Ersatz bleibt bestehen")
pruefe(AGENT.count("self._fallback_used = set()") >= 3,
       f"der Merker wird im Konstruktor UND in beiden Laeufen gesetzt ({AGENT.count('self._fallback_used = set()')})")
pruefe("tool_name=tool_name, tool_args=tool_args" in AGENT
       and AGENT.count("tool_name=tool_name, tool_args=tool_args") == 2,
       "beide Loops uebergeben Werkzeugname und Argumente")
pruefe(AGENT.count("while steps < self._max_steps():") == 2,
       "beide Loops nutzen die Schrittgrenze des Agenten")

# k) Endpunkte: alle vier auf Admin
for meth, route in [("get", "/api/agent_roles"), ("post", "/api/agent_roles"),
                    ("put", "/api/agent_roles/{role_id}"),
                    ("delete", "/api/agent_roles/{role_id}")]:
    pat = re.compile(re.escape(f'@app.{meth}("{route}")') + r"\s*\nasync def \w+\([^)]*\)",
                     re.S)
    m2 = pat.search(MAIN)
    pruefe(bool(m2) and "require_local_auth" in m2.group(0),
           f"{meth.upper()} {route} haengt an require_local_auth")

pruefe("Depends(require_auth)" not in (pat.search(MAIN).group(0) if pat.search(MAIN) else ""),
       "kein Rollen-Endpunkt haengt an require_auth")

# l) Datei-Schranken
for konst in ("_APP_DENY_REL", "PRIVATE_FILES"):
    i_k = SBX.find(konst + " = (")
    block_k = SBX[i_k:SBX.find("\n)", i_k)] if i_k >= 0 else ""
    pruefe("data/agent_roles.json" in block_k,
           f"agent_roles.json steht in {konst}", f"Block {len(block_k)} Zeichen")
pruefe("agent_roles\\.json" in SBX, "agent_roles.json steht in SHELL_SECRET_PATHS")

# m) Saeen beim Start
pruefe("async def startup_seed_agent_roles" not in MAIN,
       "das Saeen haengt NICHT mehr am Backend-Start, sondern am Skill")

# n) delegate: Rollen dynamisch, Pruefung vor dem Lauf
pruefe("agent_roles.werkzeug_beschreibung()" in DEL,
       "die Rollenliste steht in der WERKZEUG-Beschreibung (dort schaut das Modell hin)")
pruefe("Verfuegbar:" in DEL,
       "unbekannte Rolle: die Meldung nennt die verfuegbaren Rollen")
pruefe("ist abgeschaltet" in DEL,
       "abgeschaltete Rolle wird vom Tippfehler unterschieden")
pruefe("if ids:" in DEL,
       "kein leeres Enum im Schema (manche Provider antworten darauf mit 400)")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("4. Echte Laeufe (Stub-Provider)")

# BEIDE moeglichen Orte pruefen: im Repo liegt settings.json in der Wurzel, auf
# DEV unter data/. Nur einen zu pruefen macht den Wachposten dort gruen, wo die
# Datei gar nicht liegt – und genau vor dieser Migration warnt der Modulkopf.
_settings = [p for p in (ROOT / "settings.json", ROOT / "data" / "settings.json") if p.exists()]
def _set_md5():
    return {str(p): hashlib.md5(p.read_bytes()).hexdigest() for p in _settings}
_md5_vorher = _set_md5()

try:
    import backend.agent as A
    from backend.llm import LLMResponse
    from google.genai import types
    machbar = True
except Exception as e:  # noqa: BLE001
    machbar = False
    print(f"  … uebersprungen (kein venv?): {type(e).__name__}: {e}")

if machbar:
    import asyncio
    import types as _pytypes

    # Registry in den Sandkasten
    _tmp2 = Path(tempfile.mkdtemp(prefix="jarvis_rollen2_"))
    R.ROLES_FILE = _tmp2 / "agent_roles.json"
    R.anlegen({"id": "maler", "name": "Maler", "description": "malt Bilder",
               "prompt": "DU BIST DER MALER.", "tools": ["filesystem"],
               "reasoning_effort": "low", "max_steps": 4})
    R.anlegen({"id": "gesperrt", "name": "Gesperrt", "description": "nutzt Sperrlisten-Werkzeug",
               "prompt": "p", "tools": ["spawn_agent"]})

    # Ein Fake-backend.main: _delegate_to_role holt sich dort den AgentManager.
    # Der echte Import wuerde die ganze App laden (und ihre Startup-Hooks
    # mitbringen) – hier genuegt der Manager.
    if "backend.main" not in sys.modules:
        fake = _pytypes.ModuleType("backend.main")
        fake.agent_manager = A.AgentManager()
        sys.modules["backend.main"] = fake
    _am = sys.modules["backend.main"].agent_manager

    # Provider ist im Test nie "google": der google-Zweig liest
    # response.raw.candidates[0].content, das gibt es an der Attrappe nicht.
    A.JarvisAgent.LLM_PROVIDER = property(lambda self: "openai_compatible")

    def teil(text):
        return types.Part.from_text(text=text)

    def fc(name, **args):
        return types.Part(function_call=types.FunctionCall(name=name, args=args))

    class Stub:
        """Beantwortet Aufrufe der Reihe nach und merkt sich, WAS gefragt wurde."""

        def __init__(self, folge):
            self.folge = list(folge)
            self.aufrufe = []

        async def generate_response(self, model=None, system_prompt=None, contents=None,
                                    tools=None, **kw):
            self.aufrufe.append({
                "system": system_prompt or "",
                "tools": sorted(t.name for t in (tools or [])),
                "text": " ".join(
                    p.text for c in (contents or []) for p in (c.parts or []) if getattr(p, "text", None)),
                "effort": kw.get("reasoning_effort"),
            })
            parts = self.folge.pop(0) if self.folge else [teil("Standardantwort")]
            return LLMResponse(parts=parts, raw=None, usage={})

    class WSAttrappe:
        def __init__(self):
            self.nachrichten = []

        async def send_json(self, msg):
            self.nachrichten.append(msg)

        def texte(self):
            return [m.get("message", "") for m in self.nachrichten]

        def antworten(self):
            return [m["message"] for m in self.nachrichten
                    if m.get("type") == "status" and m.get("highlight")
                    and not m.get("intermediate")]

    _halter = {"s": None}
    A.get_provider = lambda *a, **kw: _halter["s"]

    haupt = A.JarvisAgent()
    _am.main_agent = haupt
    _am.agents[haupt.agent_id] = haupt

    def lauf(folge, username="jarvis"):
        stub = Stub(folge)
        _halter["s"] = stub
        haupt.provider = stub
        haupt._user_histories.clear()
        ws = WSAttrappe()
        outcome = asyncio.run(haupt.run_task("Mal mir ein Bild", ws, username=username))
        return outcome, ws, stub

    try:
        # 1) Orchestrator delegiert -> Rolle antwortet -> Ergebnis im Kontext
        outcome, ws, stub = lauf([
            [fc("delegate", role="maler", task="Zeichne ein Haus")],  # Orchestrator
            [teil("FERTIG: Haus gezeichnet.")],                       # Rollen-Lauf
            [teil("Ich habe das Bild erstellen lassen.")],            # Orchestrator final
        ])
        grundlage = True
    except Exception as e:  # noqa: BLE001
        grundlage = False
        import traceback
        traceback.print_exc()
        pruefe(False, "dynamischer Teil laeuft", f"{type(e).__name__}: {e}")

    if grundlage:
        pruefe(len(stub.aufrufe) >= 3,
               f"drei Laeufe: Orchestrator, Rolle, Orchestrator ({len(stub.aufrufe)})")
        rollen_aufruf = next((a for a in stub.aufrufe if "DU BIST DER MALER." in a["system"]), None)
        pruefe(rollen_aufruf is not None, "der Rollen-Lauf benutzt den ROLLEN-Prompt")
        pruefe(rollen_aufruf and rollen_aufruf["tools"] == ["filesystem"],
               "der Rollen-Lauf bekommt NUR die Werkzeuge der Rolle",
               str(rollen_aufruf and rollen_aufruf["tools"]))
        pruefe(rollen_aufruf and "delegate" not in rollen_aufruf["tools"],
               "der Rollen-Lauf hat kein delegate (keine Rekursion)")
        pruefe(rollen_aufruf and rollen_aufruf["effort"] == "low",
               f"die Denktiefe der Rolle wird gesetzt ({rollen_aufruf and rollen_aufruf['effort']})")
        letzter = stub.aufrufe[-1]
        pruefe("FERTIG: Haus gezeichnet." in letzter["text"],
               "das ERGEBNIS der Rolle steht im Kontext des Orchestrators (Rueckkanal)")
        pruefe(any("Rolle: Maler" in t for t in ws.texte()),
               "der Benutzer sieht, dass eine Rolle arbeitet")
        pruefe(any("Ich habe das Bild erstellen lassen." in t for t in ws.antworten()),
               "die Endantwort des Orchestrators kommt beim Benutzer an")
        pruefe(all(not getattr(a, "_role_id", "") for a in _am.agents.values()),
               "der Rollen-Agent ist nach dem Lauf aus dem Manager entfernt")

        # 2) Unbekannte Rolle: kein Lauf, Meldung nennt die Alternativen
        outcome, ws, stub = lauf([
            [fc("delegate", role="gibtsnicht", task="x")],
            [teil("Dann mache ich es selbst.")],
        ])
        pruefe(any("Unbekannte Rolle" in t and "'maler'" in t for t in ws.texte()),
               "unbekannte Rolle: Klartext mit Liste der verfuegbaren")
        pruefe(len(stub.aufrufe) == 2, f"kein Rollen-Lauf gestartet ({len(stub.aufrufe)})")

        # 3) Netzwerk-Benutzer: Sperrlisten-Werkzeug ist auch ueber die Rolle nicht da
        outcome, ws, stub = lauf([
            [fc("delegate", role="gesperrt", task="x")],
            [teil("ok")],
        ], username="nexus\\testnutzer")
        pruefe(any("kann hier nicht arbeiten" in t and "spawn_agent" in t for t in ws.texte()),
               "Rolle mit Sperrlisten-Werkzeug laeuft NICHT (keine Rechteerhoehung)")

        # 4) Harte Dispatch-Schranke: Rollen-Agent ruft ein fremdes Werkzeug
        rolle = R.holen("maler")
        r_agent = _am.spawn_role_agent(rolle, haupt)
        r_agent._role_tools = {"filesystem"}
        antwort = asyncio.run(r_agent._execute_tool("shell_execute", {"command": "id"}))
        pruefe("Zugriff verweigert" in antwort and "shell_execute" in antwort,
               "nicht deklariertes Werkzeug wird im Dispatch abgewiesen", antwort[:80])
        pruefe("filesystem" in antwort, "die Meldung nennt die verfuegbaren Werkzeuge")
        _am.remove_agent(r_agent.agent_id)

        # 5) Deckel pro Lauf
        haupt._delegations_used = haupt._MAX_DELEGATIONS
        antwort = asyncio.run(haupt._delegate_to_role("maler", "noch eine Aufgabe"))
        pruefe("Obergrenze" in antwort, "der Deckel pro Auftrag greift", antwort[:80])
        haupt._delegations_used = 0

        # 6) Ergebnis-Kuerzung wird ausgewiesen
        _halter["s"] = Stub([[teil("y" * (haupt._DELEGATE_RESULT_MAX + 500))]])
        antwort = asyncio.run(haupt._delegate_to_role("maler", "langer Bericht"))
        pruefe("[gekuerzt:" in antwort, "ein zu langes Rollen-Ergebnis wird gekuerzt UND ausgewiesen")
        pruefe(len(antwort) < haupt._DELEGATE_RESULT_MAX + 300,
               f"die Kuerzung wirkt ({len(antwort)} Zeichen)")

        # 7) Ohne Rolle bleibt alles wie vorher: delegate wird nicht angeboten
        R.ROLES_FILE.write_text('{"version":1,"roles":[]}', encoding="utf-8")
        namen_ohne = [t.name for t in haupt._llm_tools]
        pruefe("delegate" not in namen_ohne,
               "ohne eingerichtete Rolle wird delegate NICHT angeboten")
        pruefe("spawn_agent" in namen_ohne,
               "die uebrigen Werkzeuge des Hauptagenten bleiben unveraendert")

    shutil.rmtree(_tmp2, ignore_errors=True)

_md5_nachher = _set_md5()
pruefe(bool(_settings) and _md5_vorher == _md5_nachher,
       f"settings.json wurde vom Test NICHT veraendert ({len(_settings)} Datei(en) geprueft)",
       f"{_md5_vorher} -> {_md5_nachher}")
pruefe(not (ROOT / "data" / "agent_roles.json").exists()
       or "maler" not in (ROOT / "data" / "agent_roles.json").read_text(),
       "die echte data/agent_roles.json enthaelt keine Testrollen")

print(f"\n{'='*70}")
print(f"Ergebnis: {_ok} bestanden, {_fail} fehlgeschlagen")
sys.exit(0 if _fail == 0 else 1)
