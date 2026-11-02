#!/usr/bin/env python3
"""Waechter: Freigabe des HANA-SQL-Kanals durch den Administrator.

Vorfall (ECHT 2026-11-02): eine SAP-Analyse meldete "HANA-SQL gesperrt
(SSL-Fehler)". Der Administrator hatte HANA nie eingerichtet; der Host stand in
einem PERSOENLICHEN Zugang (Kanal OData, HANA-Felder zusaetzlich gefuellt). Die
HANA-Werkzeuge prueften nur "irgendein Kanal ist eingerichtet", liefen in die
Zertifikatspruefung, und das Modell lernte den Fehler als Tatsache. Direkter
SQL-Zugriff ist dort nicht gestattet.

Geprueft wird die WIRKUNG, nicht ein Vorkommen:
  1. ``hana_erlaubt``: Vorgabe nur an, wenn der Administrator HANA eingerichtet
     hat; ausdruecklicher Schalter gewinnt.
  2. ``_HanaClient``: gesperrt => nicht ``configured``, und ``_connect`` erreicht
     den Treiber NICHT (harte Schranke, Treiber-Attrappe zaehlt Aufrufe).
  3. Persoenlicher Zugang: der HANA-Host des Benutzers schaltet die Freigabe
     NICHT ein; Kanal "hana" faellt auf den Sammelzugang zurueck und laesst
     sich bei gesperrtem Kanal nicht speichern.
  4. Werkzeuge: Absage mit Klartext statt Verbindungsversuch – auch bei
     erlaubtem, aber nicht eingerichtetem HANA (Punkt 3 der Meldung).
  5. Angebot an das Modell (``_gesperrte_weg``): die SQL-Werkzeuge fallen weg;
     REGEL: jedes Werkzeug, das ``c.hana.*`` ruft, steht in ``_SAP_HANA_TOOLS``.
  6. Frontend-Vorgabe in sap.js entspricht ``hana_erlaubt`` (zwei Quellen).

``backend.config`` nur als Attrappe (der echte Import schreibt die Live-
settings.json). Exit 2 = konnte nicht laufen.

    python3 tests/test_sap_hana_freigabe.py
"""
import ast
import asyncio
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n{t}")


# ── Attrappe fuer backend.config VOR jedem Import ───────────────────────────
if "backend.config" in sys.modules:
    print("ABBRUCH: backend.config ist schon geladen (echter Import?)")
    sys.exit(2)
TMP = Path(tempfile.mkdtemp(prefix="saphana_test_"))
(TMP / "data").mkdir(parents=True)
_skill_states = {"sap": {"enabled": True, "config": {}}}
_cfg_mod = types.ModuleType("backend.config")


class _Cfg:
    def get_skill_states(self):
        return _skill_states

    def get_setting(self, key, default=None):
        return default

    def save_setting(self, key, value):
        pass


_cfg_mod.config = _Cfg()
sys.modules["backend.config"] = _cfg_mod

# Treiber-Attrappe: zaehlt jeden Verbindungsversuch. Ohne sie waere "der
# Treiber wurde nicht erreicht" nicht messbar (hdbcli fehlt lokal ohnehin).
_verbindungen = []
_hdb = types.ModuleType("hdbcli")
_dbapi = types.ModuleType("hdbcli.dbapi")


def _connect(**kw):
    _verbindungen.append(kw)
    raise RuntimeError("Attrappe: keine Datenbank")


_dbapi.connect = _connect
_hdb.dbapi = _dbapi
sys.modules["hdbcli"] = _hdb
sys.modules["hdbcli.dbapi"] = _dbapi

from backend import sap_client as scl          # noqa: E402
from backend import sap_accounts as sa         # noqa: E402

sa.DATA_DIR = TMP / "data"
sa.KONTEN_DATEI = TMP / "data" / "sap_accounts.json"
sa.SCHLUESSEL_DATEI = TMP / "data" / ".sapkey"
for pfad in (sa.KONTEN_DATEI, sa.SCHLUESSEL_DATEI):
    if not str(pfad).startswith(str(TMP)):
        print(f"SANDKASTEN VERLETZT: {pfad}")
        sys.exit(2)


def admin_config(**felder):
    _skill_states["sap"]["config"] = dict(felder)


# Positivkontrolle der Treiber-Attrappe: ein FREIGEGEBENER, eingerichteter
# Client muss sie erreichen – sonst waere Abschnitt 2 trivial gruen.
_pk = scl._HanaClient({"hana_host": "hana.beispiel.de", "hana_user": "U",
                       "hana_allowed": True})
try:
    _pk._connect()
except scl.SapError:
    pass
if len(_verbindungen) != 1:
    print(f"ABBRUCH: Treiber-Attrappe nicht erreicht ({len(_verbindungen)})")
    sys.exit(2)
_verbindungen.clear()

# ═══════════════════════════════════════════════════════════════════════════
section("1. hana_erlaubt: Vorgabe folgt der Admin-Einrichtung, Schalter gewinnt")
# ═══════════════════════════════════════════════════════════════════════════
he = scl.hana_erlaubt
check(he({}) is False, "nichts gesetzt, kein HANA eingerichtet: AUS (fail-closed)")
check(he({"connection_type": "odata", "hana_host": ""}) is False,
      "OData-Sammelzugang ohne HANA-Host (die Lage auf ECHT): AUS")
check(he({"hana_host": "hana.beispiel.de"}) is True,
      "Admin hat HANA-Host eingetragen, Schalter nie gesetzt: AN (Bestand laeuft weiter)")
check(he({"connection_type": "hana"}) is True, "Kanal hana, Schalter nie gesetzt: AN")
check(he({"hana_host": "hana.beispiel.de", "hana_allowed": False}) is False,
      "ausdruecklich AUS gewinnt gegen eingetragenen Host")
check(he({"hana_allowed": True}) is True, "ausdruecklich AN")
check(he({"hana_host": "h", "hana_allowed": "false"}) is False,
      "Zeichenkette 'false' ist AUS (nicht truthy)")
admin_config(hana_allowed=False, hana_host="h")
check(he() is False, "ohne Argument: liest die Admin-Konfiguration")

# ═══════════════════════════════════════════════════════════════════════════
section("2. _HanaClient: gesperrt heisst nicht konfiguriert und KEIN Treiberaufruf")
# ═══════════════════════════════════════════════════════════════════════════
h = scl._HanaClient({"hana_host": "hana.beispiel.de", "hana_user": "U",
                     "hana_allowed": False})
check(h.eingerichtet is True and h.configured is False,
      "eingerichtet, aber gesperrt: configured=False")
try:
    h.run_select("SELECT 1 FROM DUMMY")
    check(False, "run_select bei gesperrtem Kanal wirft")
except scl.SapError as e:
    check(scl.HANA_GESPERRT_TEXT in str(e), "Absage nennt den Grund", str(e))
check(len(_verbindungen) == 0, "Treiber wurde NICHT erreicht", str(len(_verbindungen)))
leer = scl._HanaClient({"hana_allowed": True})
check("nicht eingerichtet" in leer.nicht_nutzbar_grund(),
      "erlaubt, aber kein Host: eigener Grund", leer.nicht_nutzbar_grund())
try:
    leer.run_select("SELECT 1 FROM DUMMY")
except scl.SapError:
    pass
check(len(_verbindungen) == 0, "auch ohne Host kein Verbindungsversuch an einen leeren Host")
c = scl.SapClient({"connection_type": "odata", "odata_base_url": "https://s4.beispiel.de/x",
                   "hana_host": "hana.beispiel.de", "hana_user": "U", "hana_allowed": False})
check(c.configured and not c.hana.configured, "OData bleibt nutzbar, HANA nicht")
check(not any("HANA" in e["interface"] for e in scl.reporting_endpoints(c)),
      "Reporting-Anbindungen nennen keine HANA-Verbindung")
# Zertifikatsfehler bekommt den Weg zur Abhilfe (kein "gesperrt")
_dbapi.connect = lambda **kw: (_ for _ in ()).throw(
    RuntimeError("SSL certificate validation failed: certificate verify failed"))
try:
    scl._HanaClient({"hana_host": "h", "hana_user": "U", "hana_allowed": True})._connect()
    check(False, "Zertifikatsfehler wirft")
except scl.SapError as e:
    check("Mein SAP-Zugang" in str(e), "Zertifikatsfehler nennt den Weg zum Bestaetigen", str(e)[:160])
_dbapi.connect = _connect

# ═══════════════════════════════════════════════════════════════════════════
section("3. Persoenlicher Zugang: eigener HANA-Host schaltet nichts frei")
# ═══════════════════════════════════════════════════════════════════════════
admin_config(connection_type="odata", odata_base_url="https://s4.beispiel.de/sap/opu/odata",
             allowed_hosts="s4.beispiel.de, hana.beispiel.de")
k = {"connection_type": "odata", "odata_base_url": "https://s4.beispiel.de/sap/opu/odata",
     "hana_host": "hana.beispiel.de", "hana_user": "U"}
cfg = sa._cfg_aus_zugang(k)
check(cfg.get("hana_allowed") is False,
      "Konfiguration traegt die Admin-Freigabe AUSDRUECKLICH (nicht die Vorgabe ueber den Benutzer-Host)",
      repr(cfg.get("hana_allowed")))
check(scl.SapClient(cfg).hana.configured is False, "der gemeldete Fall: HANA ist zu")
admin_config(connection_type="odata", odata_base_url="https://s4.beispiel.de/sap/opu/odata",
             allowed_hosts="s4.beispiel.de, hana.beispiel.de", hana_allowed=True)
check(scl.SapClient(sa._cfg_aus_zugang(k)).hana.configured is True,
      "Gegenkontrolle: freigegeben => persoenlicher HANA-Host nutzbar")

admin_config(connection_type="odata", odata_base_url="https://s4.beispiel.de/sap/opu/odata",
             allowed_hosts="hana.beispiel.de")
try:
    sa.speichern("alice", {"connection_type": "hana", "hana_host": "hana.beispiel.de",
                           "hana_user": "U", "hana_password": "x"})
    check(False, "Zugangsart hana bei gesperrtem Kanal wird abgelehnt")
except sa.SapKontoFehler as e:
    check(scl.HANA_GESPERRT_TEXT in str(e), "Zugangsart hana bei gesperrtem Kanal wird abgelehnt", str(e))

# Bestand: ein HANA-Zugang, der VOR der Sperre gespeichert wurde
admin_config(connection_type="odata", odata_base_url="https://s4.beispiel.de/sap/opu/odata",
             allowed_hosts="hana.beispiel.de", hana_allowed=True)
sa.speichern("bob", {"connection_type": "hana", "hana_host": "hana.beispiel.de",
                     "hana_user": "U", "hana_password": "x"})
check(sa.aufloesen("bob")["quelle"] == sa.QUELLE_PERSOENLICH,
      "Positivkontrolle: freigegeben => persoenlicher HANA-Zugang gilt")
admin_config(connection_type="odata", odata_base_url="https://s4.beispiel.de/sap/opu/odata",
             allowed_hosts="hana.beispiel.de", hana_allowed=False)
z = sa.aufloesen("bob")
check(z["quelle"] == sa.QUELLE_SAMMEL and scl.HANA_GESPERRT_TEXT in z["hinweis"],
      "danach gesperrt: Rueckfall auf den Sammelzugang MIT Grund", json.dumps(z["hinweis"]))

# ═══════════════════════════════════════════════════════════════════════════
section("4. Werkzeuge: Absage mit Klartext statt Verbindungsversuch")
# ═══════════════════════════════════════════════════════════════════════════
_basis = types.ModuleType("backend.tools.base")


class _BaseTool:
    pass


_basis.BaseTool = _BaseTool
sys.modules.setdefault("backend.tools", types.ModuleType("backend.tools"))
sys.modules["backend.tools.base"] = _basis
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("sap_skill_main", ROOT / "skills" / "sap" / "main.py")
skill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(skill)

HANA_WERKZEUGE = {"sap_sql_query": {"sql": "SELECT 1 FROM DUMMY"},
                  "sap_list_tables": {}, "sap_describe_table": {"table": "MARA"}}
werkzeuge = {t.name: t for t in skill.get_tools()}
for gesperrt, cfgx, label in (
        (True, {"connection_type": "odata", "odata_base_url": "https://s4.beispiel.de/x",
                "hana_host": "hana.beispiel.de", "hana_user": "U", "hana_allowed": False},
         "gesperrt"),
        (False, {"connection_type": "odata", "odata_base_url": "https://s4.beispiel.de/x",
                 "hana_allowed": True}, "erlaubt, aber nicht eingerichtet")):
    cli = scl.SapClient(cfgx)
    for name, args in HANA_WERKZEUGE.items():
        _verbindungen.clear()
        tok = skill._AKTUELL.set({"client": cli, "quelle": sa.QUELLE_SAMMEL})
        try:
            res = asyncio.run(werkzeuge[name]._run(**args))
        finally:
            skill._AKTUELL.reset(tok)
        check(isinstance(res, str) and res.startswith("ℹ️") and "OData" in res
              and not _verbindungen,
              f"{label}: {name} sagt ab, nennt OData, kein Verbindungsversuch", str(res)[:120])

# ═══════════════════════════════════════════════════════════════════════════
section("5. Angebot an das Modell + Regel ueber die Werkzeugnamen")
# ═══════════════════════════════════════════════════════════════════════════
AGENT_SRC = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
baum = ast.parse(AGENT_SRC)
teile = []
for knoten in baum.body:
    if isinstance(knoten, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in ("_SAP_HANA_TOOLS", "_MCP_TOOL_PREFIX")
            for t in knoten.targets):
        teile.append(knoten)
    if isinstance(knoten, ast.FunctionDef) and knoten.name in ("_ist_mcp_tool", "_mcp_freigegeben"):
        teile.append(knoten)
methode = None
for knoten in baum.body:
    if isinstance(knoten, ast.ClassDef) and knoten.name == "JarvisAgent":
        for m in knoten.body:
            if isinstance(m, ast.FunctionDef) and m.name == "_gesperrte_weg":
                methode = m
if methode is None or len(teile) != 4:
    print(f"ABBRUCH: Schnitt unvollstaendig ({len(teile)} Teile, Methode {methode is not None})")
    sys.exit(2)
ns = {}
klasse = ast.ClassDef(name="_A", bases=[], keywords=[], decorator_list=[], type_params=[],
                      body=[methode])
exec(compile(ast.fix_missing_locations(ast.Module(body=teile + [klasse], type_ignores=[])),
             "agent", "exec"), ns)


class _Ag(ns["_A"]):
    def __init__(self, sap=True):
        self._current_user_sap = sap
        self._current_user_vemas = True

    def actor_name(self):
        return "alice"


class _W:
    def __init__(self, name):
        self.name = name


W = [_W(n) for n in ("sap_odata_query", "sap_sql_query", "sap_list_tables",
                     "sap_describe_table", "sap_test_connection", "shell_execute")]
admin_config(hana_allowed=False)
n = [t.name for t in _Ag()._gesperrte_weg(W)]
check(n == ["sap_odata_query", "sap_test_connection", "shell_execute"],
      "gesperrt: die drei SQL-Werkzeuge fehlen, der Rest bleibt in Reihenfolge", str(n))
admin_config(hana_allowed=True)
n = [t.name for t in _Ag()._gesperrte_weg(W)]
check(n == [t.name for t in W], "freigegeben: Angebot unveraendert (Prompt-Cache)", str(n))

# REGEL statt Liste: jedes Werkzeug, dessen _run den HANA-Kanal anspricht
# (Attribut-Kette c.hana.*), muss in _SAP_HANA_TOOLS stehen – sonst bliebe ein
# neues SQL-Werkzeug bei gesperrtem Kanal im Angebot.
SKILL_SRC = (ROOT / "skills" / "sap" / "main.py").read_text(encoding="utf-8")
hana_nutzer = set()
for kl in ast.walk(ast.parse(SKILL_SRC)):
    if not isinstance(kl, ast.ClassDef):
        continue
    name = None
    for m in kl.body:
        if isinstance(m, ast.FunctionDef) and m.name == "name":
            for r in ast.walk(m):
                if isinstance(r, ast.Return) and isinstance(r.value, ast.Constant):
                    name = r.value.value
    for m in kl.body:
        if isinstance(m, ast.AsyncFunctionDef) and m.name == "_run":
            if any(isinstance(a, ast.Attribute) and a.attr == "hana" for a in ast.walk(m)):
                hana_nutzer.add(name)
check(len(hana_nutzer) >= 3, "Positivkontrolle: Regel findet HANA-Werkzeuge", str(hana_nutzer))
check(hana_nutzer == set(ns["_SAP_HANA_TOOLS"]),
      "_SAP_HANA_TOOLS == alle Werkzeuge, die c.hana.* ansprechen",
      f"{sorted(hana_nutzer)} gegen {sorted(ns['_SAP_HANA_TOOLS'])}")
fehlt_absage = []
for kl in ast.walk(ast.parse(SKILL_SRC)):
    if isinstance(kl, ast.AsyncFunctionDef) and kl.name == "_run" and any(
            isinstance(a, ast.Attribute) and a.attr == "hana" for a in ast.walk(kl)):
        if not any(isinstance(cn, ast.Call) and getattr(cn.func, "attr", "") == "_hana_absage"
                   for cn in ast.walk(kl)):
            fehlt_absage.append(kl.lineno)
check(not fehlt_absage, "jedes HANA-Werkzeug ruft _hana_absage", str(fehlt_absage))

# ═══════════════════════════════════════════════════════════════════════════
section("6. Frontend-Vorgabe (sap.js) == hana_erlaubt")
# ═══════════════════════════════════════════════════════════════════════════
JS = (ROOT / "frontend" / "js" / "sap.js").read_text(encoding="utf-8")
anfang = JS.find("if ($('sap-hana-allowed')) {")
ende = JS.find("}", JS.find(": !!c.hana_allowed;", anfang)) + 1 if anfang >= 0 else -1
if anfang < 0 or ende <= anfang:
    print("ABBRUCH: Vorgabe-Block in sap.js nicht gefunden")
    sys.exit(2)
block = JS[anfang:ende]
faelle = [{}, {"hana_host": "h"}, {"hana_host": "  "}, {"connection_type": "hana"},
          {"connection_type": "odata"}, {"hana_allowed": False, "hana_host": "h"},
          {"hana_allowed": True}, {"hana_allowed": None, "hana_host": "h"}]
skript = ("const el={checked:null};const $=()=>el;const out=[];"
          + "for (const c of %s) { %s; out.push(el.checked); }" % (json.dumps(faelle), block)
          + "console.log(JSON.stringify(out));")
try:
    r = subprocess.run(["node", "-e", skript], capture_output=True, text=True, timeout=30)
except FileNotFoundError:
    print("ABBRUCH: node fehlt")
    sys.exit(2)
if r.returncode != 0:
    print("ABBRUCH: JS-Block laeuft nicht:", r.stderr[:300])
    sys.exit(2)
js_werte = json.loads(r.stdout)
py_werte = [scl.hana_erlaubt(f) for f in faelle]
check(js_werte == py_werte, "gleiche Entscheidung in allen Faellen", f"JS {js_werte} / PY {py_werte}")
check(JS.count("hana_allowed: checked('sap-hana-allowed')") == 1,
      "Speichern sendet den Schalter mit")

print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
