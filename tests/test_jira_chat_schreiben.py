#!/usr/bin/env python3
"""Waechter: Jira-Kommentar/-Ticket im Chat ueber den PERSOENLICHEN Zugang.

Vorfall ECHT 2026-11-20: "schreibe in Ticket … 'wird nicht mehr benoetigt …'"
endete mit "Das Tool jira_add_comment ist nicht verfuegbar" und frei erfundenen
Ausweichwegen. Ursache: ``_EXTERNAL_WRITE_TOOLS`` in ``agent.py`` nahm die
beiden Schreibwerkzeuge aus ``tools_map`` (der AUSFUEHRUNG), angeboten wurden
sie weiter (die Deklaration kommt aus ``_tool_instances``). Der persoenliche
Schreibweg (Festlegung 2026-11-05: "schreiben kann nur ein persoenlicher
Zugang") war damit im Chat tot.

Zusagen:
1. Jedes Werkzeug aus ``_tool_instances`` landet in ``tools_map`` – an BEIDEN
   Aufbaustellen (``__init__`` und ``reload_skills``). Gemessen durch
   Ausfuehren der geschnittenen Schleifen, nicht am Text.
2. ``_jira_schreiben_moeglich``: persoenlicher Zugang -> ja, gemeinsamer ->
   nein, Aufloesung wirft -> ja (fail-open NUR fuers Angebot, die harte
   Schranke ist JiraClient). Gefragt wird mit dem Benutzer aus ``actor_name()``.
3. ``_gesperrte_weg``: die Schreibwerkzeuge werden nur mit persoenlichem Zugang
   angeboten; alles andere unveraendert, Reihenfolge erhalten.
4. Prompt: der Absatz, der jira_add_comment nennt, haengt am SELBEN Praedikat;
   kein unbedingter Satz "nichts anlegen" fuer Jira mehr.
5. Bestaetigung: beide Werkzeuge sind in ``wirkung.TABELLE`` AUSSEN.
6. Harte Schranke: ein JiraClient ohne ``schreiben`` setzt keinen POST ab.

Sabotierte Kopien fuer die Gegenprobe ueber JS_AGENT, JS_WIRKUNG.
Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.

    python3 tests/test_jira_chat_schreiben.py
"""
import ast
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = Path(os.environ.get("JS_AGENT") or ROOT / "backend" / "agent.py")
WIRKUNG = Path(os.environ.get("JS_WIRKUNG") or ROOT / "backend" / "wirkung.py")
CLIENT = ROOT / "backend" / "jira_client.py"

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if not isinstance(label, str):
        print("ABBRUCH: check(Bedingung, Text) mit vertauschten Argumenten")
        sys.exit(2)
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n{t}")


def abbruch(grund):
    print(f"ABBRUCH: {grund}")
    sys.exit(2)


QUELLE = AGENT.read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)


def _klasse(name):
    for k in BAUM.body:
        if isinstance(k, ast.ClassDef) and k.name == name:
            return k
    abbruch(f"Klasse {name} nicht gefunden")


AG = _klasse("JarvisAgent")


def _methode(name):
    for m in AG.body:
        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == name:
            return m
    return None


def _modulwert(name):
    for k in BAUM.body:
        if isinstance(k, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in k.targets):
            return k
    return None


# ── Attrappe fuer backend.jira_accounts (echte Signatur: aufloesen(user) ->
# dict mit "quelle"; QUELLE_PERSOENLICH/QUELLE_SAMMEL wie im Modul) ─────────
class _Konten(types.ModuleType):
    QUELLE_PERSOENLICH = "persoenlich"
    QUELLE_SAMMEL = "sammel"

    def __init__(self):
        super().__init__("backend.jira_accounts")
        self.lage = "persoenlich"
        self.gefragt = []

    def aufloesen(self, user=None):
        self.gefragt.append(user)
        if self.lage == "wirft":
            raise RuntimeError("Schluesseldatei nicht lesbar")
        return {"client": object(), "quelle": self.lage, "hinweis": "", "benutzer": user}


KONTEN = _Konten()
_paket = types.ModuleType("backend")
_paket.__path__ = []
_paket.jira_accounts = KONTEN
sys.modules["backend"] = _paket
sys.modules["backend.jira_accounts"] = KONTEN

# Die Werte der echten Konstanten gegen die Attrappe stellen – laufen sie
# auseinander, misst Abschnitt 2 eine Welt, die es nicht gibt.
_konto_src = (ROOT / "backend" / "jira_accounts.py").read_text(encoding="utf-8")
if ('QUELLE_PERSOENLICH = "persoenlich"' not in _konto_src
        or 'QUELLE_SAMMEL = "sammel"' not in _konto_src):
    abbruch("Konstanten in jira_accounts.py weichen von der Attrappe ab")


# ═══════════════════════════════════════════════════════════════════════════
section("0. Schnitt und Positivkontrolle")
# ═══════════════════════════════════════════════════════════════════════════
schreib_knoten = _modulwert("_JIRA_SCHREIB_TOOLS")
teile = [k for k in (_modulwert("_SAP_HANA_TOOLS"), _modulwert("_MCP_TOOL_PREFIX"),
                     schreib_knoten) if k is not None]
for k in BAUM.body:
    if isinstance(k, ast.FunctionDef) and k.name in ("_ist_mcp_tool", "_mcp_freigegeben"):
        teile.append(k)
m_weg = _methode("_gesperrte_weg")
m_pred = _methode("_jira_schreiben_moeglich")
if m_weg is None or len(teile) < 4:
    abbruch(f"Schnitt unvollstaendig ({len(teile)} Teile, _gesperrte_weg {m_weg is not None})")
methoden = [m_weg] + ([m_pred] if m_pred is not None else [])
ns = {}
kl = ast.ClassDef(name="_A", bases=[], keywords=[], decorator_list=[], type_params=[],
                  body=methoden)
exec(compile(ast.fix_missing_locations(ast.Module(body=teile + [kl], type_ignores=[])),
             str(AGENT), "exec"), ns)


class _W:
    def __init__(self, name):
        self.name = name


class _Ag(ns["_A"]):
    def __init__(self, user="m.muster"):
        self._user = user

    def actor_name(self):
        return self._user

    def _actor_is_privileged(self):
        return False


W = [_W("jira_search"), _W("jira_add_comment"), _W("shell_execute"),
     _W("jira_create_issue"), _W("jira_get_issue")]
KONTEN.lage = "persoenlich"
try:
    _basis = [t.name for t in _Ag()._gesperrte_weg([_W("shell_execute"), _W("jira_search")])]
except Exception as e:  # noqa: BLE001
    abbruch(f"_gesperrte_weg laeuft im Schnitt nicht: {type(e).__name__}: {e}")
if _basis != ["shell_execute", "jira_search"]:
    abbruch(f"Positivkontrolle: gewoehnliche Werkzeuge kommen nicht durch ({_basis})")
check(True, "_gesperrte_weg laeuft geschnitten, gewoehnliche Werkzeuge bleiben")


# ═══════════════════════════════════════════════════════════════════════════
section("1. tools_map: jedes Werkzeug landet in der Ausfuehrung")
# ═══════════════════════════════════════════════════════════════════════════
def _schleifen():
    """Alle for-Schleifen in JarvisAgent, deren Rumpf tools_map[...] zuweist."""
    gefunden = []
    for m in AG.body:
        if not isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(m):
            if isinstance(n, ast.For) and any(
                    isinstance(z, ast.Assign) and any(
                        isinstance(t, ast.Subscript) and isinstance(t.value, ast.Attribute)
                        and t.value.attr == "tools_map" for t in z.targets)
                    for z in ast.walk(n)):
                gefunden.append((m.name, n))
    return gefunden


# Jede Zuweisung an tools_map[...] muss in einer der Schleifen liegen –
# sonst gibt es einen Aufbauweg, den dieser Abschnitt nicht ausfuehrt.
alle_zuw = [n for n in ast.walk(AG) if isinstance(n, ast.Assign) and any(
    isinstance(t, ast.Subscript) and isinstance(t.value, ast.Attribute)
    and t.value.attr == "tools_map" for t in n.targets)]
schleifen = _schleifen()
in_schleifen = {id(z) for _, s in schleifen for z in ast.walk(s)}
check(alle_zuw and all(id(z) in in_schleifen for z in alle_zuw),
      f"jede tools_map-Zuweisung liegt in einer ausgefuehrten Schleife ({len(alle_zuw)})")
orte = sorted({name for name, _ in schleifen})
check("__init__" in orte and "reload_skills" in orte,
      f"beide Aufbauorte erfasst: {orte}")

for ort, schleife in schleifen:
    selbst = types.SimpleNamespace(
        _tool_instances=[_W("jira_search"), _W("jira_add_comment"),
                         _W("jira_create_issue"), _W("knowledge_search")],
        tools_map={})
    lok = {"self": selbst}
    lok.update({k: v for k, v in ns.items() if not k.startswith("__")})
    try:
        exec(compile(ast.fix_missing_locations(ast.Module(body=[schleife], type_ignores=[])),
                     str(AGENT), "exec"), lok)
    except Exception as e:  # noqa: BLE001
        check(False, f"{ort}: Schleife laeuft", f"{type(e).__name__}: {e}")
        continue
    erwartet = {t.name for t in selbst._tool_instances}
    check(set(selbst.tools_map) == erwartet,
          f"{ort}: alle Werkzeuge in tools_map, auch jira_add_comment/jira_create_issue",
          f"fehlt: {sorted(erwartet - set(selbst.tools_map))}")


# ═══════════════════════════════════════════════════════════════════════════
section("2. Praedikat _jira_schreiben_moeglich")
# ═══════════════════════════════════════════════════════════════════════════
if m_pred is None:
    check(False, "_jira_schreiben_moeglich existiert")
else:
    for lage, erwartet in (("persoenlich", True), ("sammel", False), ("wirft", True)):
        KONTEN.lage = lage
        KONTEN.gefragt.clear()
        try:
            r = _Ag("a.nutzer")._jira_schreiben_moeglich()
        except Exception as e:  # noqa: BLE001
            check(False, f"Lage {lage}: wirft nicht", f"{type(e).__name__}: {e}")
            continue
        check(r is erwartet, f"Lage {lage}: {erwartet}", f"geliefert {r!r}")
    KONTEN.lage = "persoenlich"
    KONTEN.gefragt.clear()
    _Ag("a.nutzer")._jira_schreiben_moeglich()
    check(KONTEN.gefragt == ["a.nutzer"],
          "gefragt wird mit dem Benutzer aus actor_name()", f"{KONTEN.gefragt}")


# ═══════════════════════════════════════════════════════════════════════════
section("3. Angebot an das Modell (_gesperrte_weg)")
# ═══════════════════════════════════════════════════════════════════════════
def _namen(lage):
    KONTEN.lage = lage
    return [t.name for t in _Ag()._gesperrte_weg(W)]


try:
    n_pers = _namen("persoenlich")
    n_samm = _namen("sammel")
    n_wirft = _namen("wirft")
except Exception as e:  # noqa: BLE001
    abbruch(f"_gesperrte_weg wirft: {type(e).__name__}: {e}")
check(n_pers == [t.name for t in W],
      "persoenlicher Zugang: Schreibwerkzeuge angeboten, Reihenfolge erhalten", f"{n_pers}")
check("jira_add_comment" not in n_samm and "jira_create_issue" not in n_samm,
      "gemeinsamer Zugang: keine Schreibwerkzeuge im Angebot", f"{n_samm}")
check(n_samm == ["jira_search", "shell_execute", "jira_get_issue"],
      "gemeinsamer Zugang: alles andere unveraendert", f"{n_samm}")
check(n_wirft == [t.name for t in W],
      "Aufloesung nicht lesbar: Angebot unveraendert (harte Schranke im Client)", f"{n_wirft}")
KONTEN.lage = "sammel"
KONTEN.gefragt.clear()
_Ag()._gesperrte_weg([_W("shell_execute"), _W("jira_search")])
check(KONTEN.gefragt == [],
      "ohne Schreibwerkzeug im Angebot wird nicht nachgefragt", f"{KONTEN.gefragt}")


# ═══════════════════════════════════════════════════════════════════════════
section("4. Prompt-Absatz am selben Praedikat")
# ═══════════════════════════════════════════════════════════════════════════
def _strings(knoten):
    return " ".join(c.value for c in ast.walk(knoten)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str))


run_task = _methode("run_task")
if run_task is None:
    abbruch("run_task nicht gefunden")
def _eigene_strings(zweig):
    """Strings, die der Zweig SELBST anhaengt – ohne verschachtelte if-Bloecke.
    Sonst zaehlt der aeussere ``if _ext_sources:`` als nennender Zweig, nur
    weil er den inneren enthaelt (erster Lauf: genau dieser Fehlalarm)."""
    return " ".join(_strings(s) for s in zweig if not isinstance(s, ast.If))


nennende_ifs = []
for n in ast.walk(run_task):
    if isinstance(n, ast.If) and "jira_add_comment" in _eigene_strings(n.body):
        nennende_ifs.append(n)
check(len(nennende_ifs) >= 1, "es gibt einen Prompt-Zweig, der jira_add_comment nennt")


def _bedingung_ruft_praedikat(test):
    """Die Bedingung ruft das Praedikat – direkt oder ueber eine Variable."""
    def ruft(k):
        return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                   and c.func.attr == "_jira_schreiben_moeglich" for c in ast.walk(k))
    if ruft(test):
        return True
    namen = {x.id for x in ast.walk(test) if isinstance(x, ast.Name)}
    for z in ast.walk(run_task):
        if isinstance(z, ast.Assign) and any(isinstance(t, ast.Name) and t.id in namen
                                             for t in z.targets) and ruft(z.value):
            return True
    return False


for i, f in enumerate(nennende_ifs):
    check(_bedingung_ruft_praedikat(f.test),
          f"Prompt-Zweig {i + 1} mit jira_add_comment haengt an _jira_schreiben_moeglich")
# Kein unbedingter "nichts anlegen"-Satz fuer Jira: der Satz von vorher stand
# im Absatz, der fuer Confluence UND Jira gilt, ausserhalb jeder Bedingung.
alt_satz = "schreibende Aktionen sind bewusst deaktiviert"
check(alt_satz not in _strings(run_task).replace("–", "-").replace("  ", " ")
      and "sind bewusst deaktiviert" not in _strings(run_task),
      "der unbedingte Satz 'schreibende Aktionen sind bewusst deaktiviert' ist weg")


# ═══════════════════════════════════════════════════════════════════════════
section("5. Bestaetigung vor dem Schreiben (wirkung.TABELLE)")
# ═══════════════════════════════════════════════════════════════════════════
wbaum = ast.parse(WIRKUNG.read_text(encoding="utf-8"))
tabelle = None
for k in wbaum.body:
    if isinstance(k, ast.AnnAssign) and getattr(k.target, "id", "") == "TABELLE":
        tabelle = k.value
    if isinstance(k, ast.Assign) and any(getattr(t, "id", "") == "TABELLE" for t in k.targets):
        tabelle = k.value
if not isinstance(tabelle, ast.Dict):
    abbruch("wirkung.TABELLE nicht als Dict-Literal gefunden")
eintrag = {getattr(s, "value", None): v for s, v in zip(tabelle.keys, tabelle.values)}
for name in ("jira_add_comment", "jira_create_issue"):
    v = eintrag.get(name)
    check(isinstance(v, ast.Name) and v.id == "AUSSEN",
          f"{name}: Wirkungsklasse AUSSEN (Bestaetigung)",
          ast.unparse(v) if v is not None else "fehlt")
# Die Menge im Agenten und die Tabelle meinen dieselben Werkzeuge.
if schreib_knoten is None:
    check(False, "_JIRA_SCHREIB_TOOLS existiert in agent.py")
else:
    menge = set(ns.get("_JIRA_SCHREIB_TOOLS") or ())
    check(menge == {"jira_add_comment", "jira_create_issue"},
          "_JIRA_SCHREIB_TOOLS = die beiden Schreibwerkzeuge", f"{sorted(menge)}")


# ═══════════════════════════════════════════════════════════════════════════
section("6. Harte Schranke: gemeinsamer Client setzt keinen POST ab")
# ═══════════════════════════════════════════════════════════════════════════
# Echtes jira_client.py mit einer requests-Attrappe, die jeden Aufruf zaehlt.
anfragen = []
_req = types.ModuleType("requests")


def _request(method, url, **kw):
    anfragen.append((method, url))

    class _R:
        status_code = 200
        text = "{}"

        def json(self):
            return {"id": "1"}
    return _R()


_req.request = _request
sys.modules["requests"] = _req
cns = {"__name__": "jira_client_probe"}
exec(compile(CLIENT.read_text(encoding="utf-8"), str(CLIENT), "exec"), cns)
cfg = {"base_url": "https://jira.beispiel.de", "api_token": "x"}
lese = cns["JiraClient"](cfg)
try:
    lese.add_comment("ABC-1", "Text")
    check(False, "gemeinsamer Client: add_comment wird abgewiesen", "kein Fehler geworfen")
except cns["JiraError"] as e:
    check(cns["NUR_LESEN_TEXT"] in str(e) or cns["NUR_LESEN_TEXT"] in repr(e.args),
          "gemeinsamer Client: Abweisung nennt den Nur-Lesen-Grund", str(e))
check(not any(m.upper() != "GET" for m, _ in anfragen),
      "gemeinsamer Client: kein schreibender Aufruf verlaesst den Prozess", f"{anfragen}")
schreib = cns["JiraClient"](cfg, schreiben=True)
try:
    schreib.add_comment("ABC-1", "Text")
except Exception as e:  # noqa: BLE001
    check(False, "Positivkontrolle: persoenlicher Client schreibt", f"{type(e).__name__}: {e}")
check(any(m.upper() == "POST" for m, _ in anfragen),
      "Positivkontrolle: persoenlicher Client setzt den POST ab", f"{anfragen}")


print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
