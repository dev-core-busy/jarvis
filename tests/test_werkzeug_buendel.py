#!/usr/bin/env python3
"""Waechter fuer den aufgabenabhaengigen Werkzeug-Zuschnitt.

Gemessen wird das, worauf die Zusage beruht:
  - der Zuschnitt kann nur WEGNEHMEN, nie hinzufuegen (Rechtefrage),
  - er ist fail-open an drei Stellen (nichts erkannt / leer / Fehler),
  - er ist AUS, solange niemand ihn einschaltet,
  - die REIHENFOLGE bleibt erhalten (ein Umsortieren kostete gemessen +364 %),
  - `werkzeuge_anfordern` hebt ihn fuer den restlichen Lauf auf,
  - das Flag wird bei JEDEM Auftragsstart zurueckgesetzt.
"""
import ast
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OK = FAIL = 0


def check(name, bed):
    global OK, FAIL
    print(("  \033[32m✓\033[0m " if bed else "  \033[31m✗\033[0m ") + name)
    if bed:
        OK += 1
    else:
        FAIL += 1


def sicher(fn, *a, **k):
    """Nie ungeprueft aufrufen: eine werfende Pruefung BRICHT den Lauf ab statt
    fehlzuschlagen - und ein abgebrochener Waechter ist von einem bestandenen
    nicht zu unterscheiden (Register)."""
    try:
        return fn(*a, **k)
    except Exception as e:                                     # noqa: BLE001
        return f"__WURF__ {e}"


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = io.open(os.path.join(REPO, "backend/agent.py"), encoding="utf-8").read()
CFG = io.open(os.path.join(REPO, "backend/config.py"), encoding="utf-8").read()

from backend import werkzeug_buendel as wb                     # noqa: E402


class W:
    def __init__(self, n):
        self.name = n


print("\n\033[1m1. Die Heuristik trifft die Themen\033[0m")
faelle = [
    ("generiere ein Bild einer gruenen Kuh", {"bild"}),
    ("erstelle eine PowerPoint ueber Netzwerke", {"dokument"}),
    ("lies Ticket NXCSO-28878", {"fach"}),
    ("schicke eine WhatsApp an das Team", {"kommunikation"}),
    ("mach einen Screenshot vom Desktop", {"bild", "desktop"}),
]
for text, erwartet in faelle:
    check(f"{text[:44]!r} -> {sorted(erwartet)}",
          sicher(wb.themen, text) == erwartet)
check("⚠ ein Auftrag darf MEHRERE Buendel treffen (additiv, nicht exklusiv)",
      sicher(wb.themen, "erzeuge ein Bild und pack es in eine Praesentation")
      == {"bild", "dokument"})
check("nichts erkannt = keine Aussage (leere Menge)", sicher(wb.themen, "hallo") == set())
check("leerer/kaputter Auftrag wirft nicht",
      sicher(wb.themen, "") == set() and sicher(wb.themen, None) == set())

print("\n\033[1m2. Fail-open: im Zweifel der volle Satz\033[0m")
check("⚠ nichts erkannt -> None (= keine Beschraenkung), NICHT leere Menge",
      sicher(wb.erlaubte_namen, "hallo") is None)
check("ein Thema -> echte Namensmenge",
      isinstance(sicher(wb.erlaubte_namen, "erzeuge ein Bild"), set))
alle = [W(x) for x in ("generate_image", "office_create_word", "shell_execute",
                       "knowledge_search", "windows_desktop", "jira_search")]
gek, grund = sicher(wb.zuschnitt, alle, "erzeuge ein Bild")
check("Zuschnitt greift bei erkanntem Thema", len(gek) < len(alle))
check("und meldet den Grund", isinstance(grund, str) and "bild" in grund)
voll, grund2 = sicher(wb.zuschnitt, alle, "hallo")
check("⚠ ohne Thema bleibt die Liste UNVERAENDERT",
      [t.name for t in voll] == [t.name for t in alle] and "voll" in grund2)
# ⚠ DIE LEER-LAGE MUSS WIRKLICH HERGESTELLT WERDEN: seit der Umkehrung bleibt
# ein Werkzeug OHNE Thema ohnehin stehen - der Fall tritt nur ein, wenn ALLE
# Werkzeuge einem FREMDEN Thema gehoeren.
leer, grund3 = sicher(wb.zuschnitt, [W("office_create_word")], "erzeuge ein Bild")
check("⚠ ein leerer Zuschnitt waere ein Agent ohne Werkzeuge -> voller Satz",
      len(leer) == 1 and "voll" in grund3)
check("⚠ ein Werkzeug OHNE Thema bleibt (die Umkehrung, auf ECHT bezahlt)",
      [t.name for t in sicher(wb.zuschnitt, [W("voellig_unbekannt")],
                              "erzeuge ein Bild")[0]] == ["voellig_unbekannt"])
# Genau die Werkzeuge, die auf ECHT wirklich benutzt werden und in der ersten
# Fassung weggefallen waeren.
_echt = [W(x) for x in ("sap_odata_query", "delegate", "email_entwurf", "spawn_agent",
                        "knowledge_manage", "secret_reveal", "branding_info",
                        "generate_image")]
_g, _ = sicher(wb.zuschnitt, _echt, "generiere ein Bild einer Kuh")
_n = {t.name for t in _g}
check("⚠ delegate bleibt (91x auf ECHT benutzt)", "delegate" in _n)
check("⚠ spawn_agent bleibt (10x)", "spawn_agent" in _n)
check("⚠ Werkzeuge ohne Thema bleiben (secret_reveal, branding_info)",
      {"secret_reveal", "branding_info", "knowledge_manage"} <= _n)
check("fremde Fachwerkzeuge fallen weiterhin weg (sonst spart es nichts)",
      "sap_odata_query" not in _n and "email_entwurf" not in _n)

print("\n\033[1m3. Der Zuschnitt kann nur WEGNEHMEN (Rechtefrage)\033[0m")
for auftrag in ("erzeuge ein Bild", "erstelle eine Excel-Tabelle",
                "lies das Jira-Ticket", "schicke eine Mail", "mach einen Screenshot"):
    g, _ = sicher(wb.zuschnitt, alle, auftrag)
    if isinstance(g, str):
        check(f"{auftrag[:30]}: Aufruf wirft nicht", False)
        continue
    fremd = [t.name for t in g if t not in alle]
    check(f"{auftrag[:30]}: kein Werkzeug hinzugefuegt", not fremd)
check("⚠ auch ein Buendel-Name, der gar nicht in der Liste steht, erscheint nicht",
      all(t.name in {x.name for x in alle}
          for t in (sicher(wb.zuschnitt, alle, "erstelle eine PowerPoint")[0] or [])))

print("\n\033[1m4. Die REIHENFOLGE bleibt (gemessen: Umsortieren = +364 %)\033[0m")
viele = [W(x) for x in ("shell_execute", "generate_image", "knowledge_search",
                        "search_image", "memory_manage", "screenshot")]
g, _ = sicher(wb.zuschnitt, viele, "erzeuge ein Bild")
namen_g = [t.name for t in g]
check("die Teilmenge steht in der Reihenfolge des Aufrufers",
      namen_g == [t.name for t in viele if t.name in namen_g])
check("⚠ NICHT alphabetisch sortiert (das waere bei jedem Aufruf ein anderer Satz)",
      namen_g != sorted(namen_g) or len(namen_g) < 2)
check("zweimal derselbe Auftrag -> identische Liste (cachebar)",
      [t.name for t in sicher(wb.zuschnitt, viele, "erzeuge ein Bild")[0]] == namen_g)

print("\n\033[1m5. Der Kern ist immer dabei\033[0m")
for auftrag in ("erzeuge ein Bild", "erstelle eine PowerPoint", "lies das Ticket"):
    n = sicher(wb.erlaubte_namen, auftrag) or set()
    fehlt = [k for k in wb.KERN if k not in n]
    check(f"{auftrag[:30]}: Kern vollstaendig", not fehlt)
check("⚠ der Rueckweg werkzeuge_anfordern gehoert zum Kern",
      "werkzeuge_anfordern" in wb.KERN)
check("knowledge_search ist im Kern (Punkt 1 macht sie zur Vorbedingung)",
      "knowledge_search" in wb.KERN)

print("\n\033[1m6. Verdrahtung im Agenten - als REGEL, nicht am Wortlaut\033[0m")
baum = ast.parse(AGENT)
fn = {}
for node in ast.walk(baum):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        fn.setdefault(node.name, node)
check("_llm_tools ruft den Zuschnitt", "_buendel_zuschnitt" in AGENT and
      any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_buendel_zuschnitt"
          for n in ast.walk(fn.get("_llm_tools", ast.Module(body=[], type_ignores=[])))))
zus = fn.get("_buendel_zuschnitt")
quelle_zus = ast.get_source_segment(AGENT, zus) if zus else ""
check("der Zuschnitt existiert als eigene Funktion", bool(quelle_zus))
check("⚠ er prueft den Schalter (Vorgabe AUS)",
      "WERKZEUG_BUENDEL" in quelle_zus or "_buendel_aktiv" in quelle_zus)
check("⚠ er respektiert _buendel_voll (der Rueckweg)", "_buendel_voll" in quelle_zus)
check("⚠ jeder Fehler laesst den vollen Satz stehen",
      re.search(r"except[^\n]*\n(?:[^\n]*\n){0,3}?\s*return tools", quelle_zus) is not None)
# Das Flag MUSS an beiden Lauf-Starts zurueckgesetzt werden - eine Stelle allein
# waere die halbe Reparatur (dieselbe Lehre wie bei _delegations_used).
check("⚠ _buendel_voll wird an BEIDEN Lauf-Starts zurueckgesetzt",
      AGENT.count("self._buendel_voll = False") == 2)
check("und ist im Konstruktor gesetzt", "self._buendel_voll: bool = False" in AGENT)
check("werkzeuge_anfordern haengt in _attach_extra_tools (nicht an einem Skill)",
      "WerkzeugeAnfordernTool" in ast.get_source_segment(AGENT, fn["_attach_extra_tools"]))

print("\n\033[1m6b. AUSGESCHALTET aendert sich NICHTS am Angebot\033[0m")
# ⚠ DIESE PRUEFUNG IST BEZAHLT (2026-09-06): `werkzeuge_anfordern` haengt immer
# im Kasten, damit es beim Einschalten sofort da ist - angeboten werden darf es
# aber nur, wenn es etwas bewirkt. Ohne diesen Filter aendert das Feature das
# Angebot auch im AUSGESCHALTETEN Zustand, und drei Bestandstests fielen um
# (test_agent_roles 168->11 FAIL, test_lauf_rechte, test_bild_anzeige).
quelle_llm = ast.get_source_segment(AGENT, fn["_llm_tools"]) or ""
check("⚠ bei ausgeschaltetem Zuschnitt faellt werkzeuge_anfordern aus dem Angebot",
      't.name != "werkzeuge_anfordern"' in quelle_zus)
# ⚠ OHNE DOCSTRING UND KOMMENTARE: der erklaert beide Namen und steht GANZ
# OBEN - eine Positionspruefung auf dem Rohtext liest die eigene Begruendung
# und meldet einen Fehler, den es nicht gibt (Register, 14. Fall).
def _ohne_prosa(q):
    b = ast.parse(q.strip()).body[0]
    koerper = [k for k in b.body if not (isinstance(k, ast.Expr)
               and isinstance(getattr(k, "value", None), ast.Constant)
               and isinstance(k.value.value, str))]
    return "\n".join(ast.unparse(k) for k in koerper)
rumpf = sicher(_ohne_prosa, quelle_zus)
check("Positivkontrolle: der Rumpf wurde ohne Docstring geschnitten",
      isinstance(rumpf, str) and "werkzeuge_anfordern" in rumpf
      and "GEMESSEN am echten vLLM" not in rumpf)
check("und zwar VOR jeder weiteren Entscheidung (auch vor _buendel_voll)",
      isinstance(rumpf, str)
      and "werkzeuge_anfordern" in rumpf and "_buendel_voll" in rumpf
      and rumpf.index("werkzeuge_anfordern") < rumpf.index("_buendel_voll"))
check("die Aktiv-Frage ist fail-closed (Fehler = aus)",
      "_buendel_aktiv" in AGENT and
      re.search(r"except[^\n]*\n\s*return False", ast.get_source_segment(AGENT, fn["_buendel_aktiv"]) or "") is not None)

print("\n\033[1m7. Der Schalter ist AUS, solange niemand ihn setzt\033[0m")
check("Klassen-Vorgabe ist False",
      re.search(r'WERKZEUG_BUENDEL:\s*bool\s*=\s*os\.getenv\([^)]*"0"\)\s*==\s*"1"', CFG) is not None)
check("⚠ aus der settings.json nur `is True` (kein bool()-Rateschluss)",
      'settings["werkzeug_buendel"] is True' in CFG
      and 'data.get("werkzeug_buendel") is True' in CFG)
check("der Wert wird auch ausgegeben (sonst waere er nicht pflegbar)",
      '"werkzeug_buendel": self.WERKZEUG_BUENDEL' in CFG)

print("\n\033[1m8. Der Rueckweg\033[0m")
from backend.tools.werkzeuge_anfordern import WerkzeugeAnfordernTool   # noqa: E402
import asyncio                                                          # noqa: E402


class FakeAgent:
    pass


ag = FakeAgent()
t = WerkzeugeAnfordernTool(ag)
r = sicher(asyncio.run, t.execute(grund="Praesentation"))
check("der Aufruf setzt das Flag am Agenten", getattr(ag, "_buendel_voll", False) is True)
check("und meldet es verstaendlich zurueck",
      isinstance(r, str) and "Werkzeugkasten" in r)
check("⚠ ohne Agent-Bezug wirft es nicht, sondern sagt es",
      "HINWEIS_AN_NUTZER" in str(sicher(asyncio.run, WerkzeugeAnfordernTool(None).execute())))
check("das Schema ist klein (es geht in JEDEN Zuschnitt mit)",
      len(t.description) < 600)

print("\n\033[1m9. Prompt-Zuschnitt\033[0m")
_sp = None
for _n in ast.walk(baum):
    if isinstance(_n, ast.ClassDef):
        for _st in _n.body:
            if (isinstance(_st, ast.Assign) and getattr(_st.targets[0], "id", "") == "SYSTEM_PROMPT"
                    and isinstance(_st.value, ast.Constant)):
                _sp = _st.value.value
check("Positivkontrolle: der SYSTEM_PROMPT wurde gefunden",
      isinstance(_sp, str) and len(_sp) > 5000)

# ⚠ DIE TRAGENDEN REGELN DUERFEN NIE WEGFALLEN. Sie stehen in Abschnitten ohne
# Werkzeug-Nennung bzw. in 16b - waeren sie in einem werkzeuggebundenen Block,
# verschwaende mit dem Zuschnitt eine Sicherheitszusage.
TRAGEND = ["SICHERHEITS-GRUNDREGEL", "UNTRUSTED_CONTEXT", "ANTWORTSPRACHE",
           "JARVIS_DELIVER", "/tmp", "AUTONOMIE"]
for auftrag in ("generiere ein Bild einer Kuh", "erstelle eine PowerPoint",
                "lies das Jira-Ticket NX-1", "schicke eine Mail",
                "zeig die Umsaetze als Balkendiagramm"):
    er = sicher(wb.erlaubte_namen, auftrag)
    paar = sicher(wb.prompt_zuschnitt, _sp, er)
    if isinstance(paar, str):
        check(f"{auftrag[:28]}: Zuschnitt wirft nicht", False)
        continue
    text, weg = paar
    fehlt = [w for w in TRAGEND if w not in text]
    check(f"{auftrag[:28]}: alle tragenden Regeln bleiben ({len(text)} Z.)", not fehlt)
    check(f"{auftrag[:28]}: KEIN toter Verweis auf einen entfernten Punkt",
          not sicher(wb.offene_verweise, text, weg))

check("⚠ ohne erkanntes Thema bleibt der Prompt UNVERAENDERT",
      sicher(wb.prompt_zuschnitt, _sp, None) == (_sp, []))
check("⚠ und mit erkanntem Thema wird wirklich gekuerzt",
      len(sicher(wb.prompt_zuschnitt, _sp,
                 sicher(wb.erlaubte_namen, "lies das Jira-Ticket NX-1"))[0]) < len(_sp) * 0.8)
# Ein Abschnitt ohne Werkzeug-Nennung darf NIE fallen - dort stehen die
# Grundregeln, die von keinem Skill abhaengen.
ohne_wz = [nr for nr, t in sicher(wb._bloecke, _sp)
           if nr and not (set(wb._WERKZEUG_IM_TEXT.findall(t)) - set(wb.KERN))]
_, weg_min = sicher(wb.prompt_zuschnitt, _sp, {"nichts_davon"})
check("⚠ werkzeuglose Abschnitte fallen NIE weg",
      not (set(ohne_wz) & set(weg_min)))
check("Positivkontrolle: bei leerem Zuschnitt faellt ueberhaupt etwas", len(weg_min) > 0)

# Prompt und Werkzeuge muessen aus DERSELBEN Quelle kommen.
q_prompt = ast.get_source_segment(AGENT, fn["_prompt_zugeschnitten"]) or ""
check("⚠ der Prompt-Zuschnitt nutzt _buendel_erlaubt (eine Quelle fuer beides)",
      "_buendel_erlaubt" in q_prompt and "_buendel_erlaubt" in quelle_zus)
check("er ist fail-open (Fehler = voller Prompt)",
      re.search(r"except[^\n]*\n(?:[^\n]*\n){0,3}?\s*return self\.SYSTEM_PROMPT", q_prompt)
      is not None)
check("_base_system_prompt ruft ihn (sonst wirkt er nirgends)",
      "_prompt_zugeschnitten" in (ast.get_source_segment(AGENT, fn["_base_system_prompt"]) or ""))
check("die Rollen-/Sub-Agent-Weiche ist unangetastet",
      "SUB_AGENT_PROMPT" in (ast.get_source_segment(AGENT, fn["_base_system_prompt"]) or ""))

print(f"\n\033[1mErgebnis: {OK} OK, {FAIL} FAIL\033[0m")
sys.exit(1 if FAIL else 0)
