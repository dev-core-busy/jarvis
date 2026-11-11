#!/usr/bin/env python3
"""Waechter: Syntaxpruefung des SQL-Assistenten (backend/sql_syntax.py).

Geprueft wird die EIGENSCHAFT, nicht das Vorkommen:
  1. Positivkontrolle: sqlglot ist importierbar und in der FESTGELEGTEN
     Fassung (requirements.txt) – sonst Exit 2 bzw. FAIL, denn die
     Strukturregeln sind an genau dieser Fassung gemessen.
  2. Gute Abfragen (alle Dialekte, Fensterfunktionen, CTE, UNION, LISTAGG …)
     bestehen – eine Syntaxpruefung mit Fehlalarmen kippt jede erzeugte Abfrage
     in eine unnoetige Reparaturrunde.
  3. Fehler werden erkannt, AUCH die, die der Parser selbst stillschweigend
     umschreibt (Komma vor FROM, falsche Klausel-Reihenfolge, ON ohne
     Bedingung) – mit Zeile/Spalte und deutschem Text.
  4. HANA/DB2 (kein eigener Parser): Parserbefund = Hinweis, kein Fehler;
     Strukturregeln bleiben Fehler.
  5. Fehlt sqlglot: ``verfuegbar`` False und ``ok`` None – nie "in Ordnung".
  6. ``pruefen_gesamt``: Syntaxfehler stehen VORN in ``fehler`` und kippen
     ``ok``; ``sql_erzeugen`` benutzt es (AST) – sonst liefe die Reparatur-
     runde nicht ueber Syntaxfehler.
  7. main.py: /api/sql/frage und /api/sql/pruefen bauen die Antwort ueber
     DIESELBE Funktion; /api/sql/pruefen haengt an der Freigabe.
  8. Dialektliste: eine Quelle (DIALEKTE), jeder Parsername existiert.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" – " + str(detail)[:400] if detail else ""))


def abbruch(grund):
    print("ABBRUCH (Exit 2): " + grund)
    sys.exit(2)


# backend.config-Attrappe VOR jedem Import (der echte schreibt settings.json).
_cfg_mod = types.ModuleType("backend.config")
_cfg_mod.config = types.SimpleNamespace(get_skill_states=lambda: {})
sys.modules["backend.config"] = _cfg_mod

print("\n1. Positivkontrolle")
try:
    import sqlglot
except ImportError:
    abbruch("sqlglot nicht installiert (pip install -r requirements.txt, bzw. PYTHONPATH)")
try:
    from backend import sql_syntax as X
    from backend import schema_graph_rag as R
    from backend.schema_graph_einstellungen import DIALEKTE
except Exception as e:  # noqa: BLE001
    abbruch(f"Module nicht ladbar: {e}")
m = re.search(r"^sqlglot==([\w.]+)", (ROOT / "requirements.txt").read_text(encoding="utf-8"), re.M)
if not m:
    abbruch("sqlglot==<fassung> fehlt in requirements.txt")
check(f"sqlglot in der festgelegten Fassung {m.group(1)}", sqlglot.__version__ == m.group(1), sqlglot.__version__)
check("Pruefer meldet sich verfuegbar", X.verfuegbar())
# Positivkontrolle ueber einen Fehler, den der PARSER selbst findet – nicht
# ueber eine Strukturregel: sonst machte eine Sabotage an den Regeln aus einem
# Befund ein "konnte nicht laufen" (Register, Positivkontroll-Guard).
probe = X.pruefen("SELECT (a FROM t", "allgemein")
if probe.get("ok") is not False:
    abbruch(f"Positivkontrolle: der Parser erkennt eine offene Klammer nicht ({probe})")

print("\n2. Gute Abfragen bestehen")
GUT = [
    ("allgemein", "SELECT a FROM t"),
    ("allgemein", "SELECT a FROM t;"),
    ("mssql", "SELECT TOP 5 a FROM t ORDER BY a"),
    ("mysql", "SELECT k.land, SUM(a.betrag) AS umsatz FROM vk.kunde k JOIN vk.auftrag a ON a.kunde_id = k.id "
              "WHERE YEAR(a.datum) = 2025 GROUP BY k.land ORDER BY umsatz DESC LIMIT 10"),
    ("oracle", "SELECT LISTAGG(x, ',') WITHIN GROUP (ORDER BY y) FROM t GROUP BY z"),
    ("oracle", "SELECT a FROM t FETCH FIRST 5 ROWS ONLY"),
    ("postgresql", "SELECT STRING_AGG(x, ',' ORDER BY y) FROM t WHERE a=1 GROUP BY z HAVING COUNT(*)>1 ORDER BY 1"),
    ("postgresql", "SELECT EXTRACT(YEAR FROM x.d), ROW_NUMBER() OVER (PARTITION BY a ORDER BY b) FROM s.t x "
                   "WHERE x.d BETWEEN 1 AND 2"),
    ("postgresql", "SELECT DISTINCT ON (a) a FROM t"),
    ("allgemein", "WITH c AS (SELECT a FROM t ORDER BY a) SELECT * FROM c WHERE a IN (SELECT b FROM u GROUP BY b) ORDER BY a"),
    ("allgemein", "SELECT a FROM t UNION ALL SELECT b FROM u WHERE c=1 ORDER BY 1"),
    ("allgemein", 'SELECT "FROM", a FROM t'),
    ("allgemein", "SELECT a -- , \nFROM t"),
    ("allgemein", "SELECT a FROM t1 JOIN t2 USING (id)"),
    ("hana", "SELECT ADD_DAYS(CURRENT_DATE, 3) FROM DUMMY"),
    ("db2", "SELECT a FROM t FETCH FIRST 10 ROWS ONLY"),
    ("sqlite", "SELECT a FROM t LIMIT 5 OFFSET 2"),
    ("snowflake", "SELECT a FROM t QUALIFY ROW_NUMBER() OVER (PARTITION BY a ORDER BY b) = 1"),
]
for d, q in GUT:
    r = X.pruefen(q, d)
    check(f"[{d}] {q[:60]!r}", r["ok"] is True and not r["fehler"], [X.befund_text(b) for b in r["fehler"]])

print("\n3. Fehler werden erkannt (mit Ort und deutschem Text)")
SCHLECHT = [
    ("allgemein", "SELECT a, FROM t", "Überzähliges Komma vor FROM"),
    ("allgemein", "SELECT a FROM t WHERE x IN (1,2,)", "Überzähliges Komma vor )"),
    ("allgemein", "SELECT a FROM t ORDER BY a WHERE b=1", "WHERE steht nach ORDER BY"),
    ("allgemein", "SELECT a FROM t HAVING COUNT(*) > 1 GROUP BY a", "GROUP BY steht nach HAVING"),
    ("postgresql", "SELECT a FROM t t1 JOIN u ON", "Nach ON fehlt die Bedingung"),
    ("allgemein", "SELECT a FROM t1 JOIN t2 USING", "Nach USING fehlt"),
    ("allgemein", "SELECT a FROM t GROUP BY", "Nach GROUP BY fehlt die Liste"),
    ("allgemein", "SELECT a FROM t WHERE a=1 AND", "Nach AND fehlt die Bedingung"),
    ("mssql", "SELECT a FROM t WHERE (x = 1", "Schließende Klammer fehlt"),
    ("oracle", "SELECT a FROM t WHERE x='ab", "nicht geschlossen"),
    ("allgemein", "SELECT a FROM t WHERE x = = 1", "Ausdruck unvollständig"),
    ("allgemein", "SELEC a FROM t", "Unerwartetes Wort"),
]
for d, q, erwartet in SCHLECHT:
    r = X.pruefen(q, d)
    texte = [X.befund_text(b) for b in r["fehler"]]
    check(f"[{d}] {q[:50]!r} -> {erwartet}", r["ok"] is False and any(erwartet in t for t in texte), texte)
r = X.pruefen("SELECT a,\nFROM t", "allgemein")
erst = (r["fehler"] or [{}])[0]
check("Ort: Zeile und Spalte des Kommas", erst.get("zeile") == 1 and isinstance(erst.get("spalte"), int), erst)
r = X.pruefen("SELECT a FROM t WHERE a=1 AND", "allgemein")
check("Dieselbe Stelle nur EINMAL gemeldet (Struktur + Parser)", len(r["fehler"]) == 1, r["fehler"])
r = X.pruefen("", "allgemein")
check("Leer: Fehler, nicht ok", r["ok"] is False and r["fehler"], r)
r = X.pruefen("SELECT 1 " + "x" * (X.MAX_SQL + 1), "allgemein")
check("Zu lang: abgewiesen", r["ok"] is False and "länger" in X.befund_text(r["fehler"][0] if r["fehler"] else {}), r["fehler"])

print("\n4. Dialekte ohne eigenen Parser")
r = X.pruefen("SELEC a FROM t", "hana")
check("HANA: Parserbefund ist Hinweis, ok bleibt True", r["ok"] is True and r["hinweise"] and r["ersatz"] is True, r)
r = X.pruefen("SELECT a, FROM t", "db2")
check("DB2: Strukturregel bleibt Fehler", r["ok"] is False and r["fehler"], r)
r = X.pruefen("SELEC a FROM t", "postgresql")
check("Gegenkontrolle: PostgreSQL macht denselben Befund zum Fehler", r["ok"] is False and not r["hinweise"], r)

print("\n5. Ohne sqlglot")
BLOCKER = (
    "import sys, types, json\n"
    "class B:\n"
    "    def find_spec(self, n, p=None, t=None):\n"
    "        if n == 'sqlglot' or n.startswith('sqlglot.'):\n"
    "            raise ImportError('gesperrt')\n"
    "sys.meta_path.insert(0, B())\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "try:\n"
    "    import sqlglot  # noqa\n"
    "    print('NICHT_GESPERRT'); sys.exit(0)\n"
    "except ImportError:\n"
    "    pass\n"
    "from backend import sql_syntax as X\n"
    "print(json.dumps(X.pruefen('SELECT a, FROM t', 'allgemein')))\n"
)
p = subprocess.run([sys.executable, "-c", BLOCKER, str(ROOT)], capture_output=True, text=True, timeout=60)
if "NICHT_GESPERRT" in p.stdout:
    abbruch("Positivkontrolle: der Blocker nimmt sqlglot nicht weg")
import json  # noqa: E402
try:
    ohne = json.loads(p.stdout.strip().splitlines()[-1])
except Exception:  # noqa: BLE001
    ohne = {}
check("Ohne sqlglot: verfuegbar False", ohne.get("verfuegbar") is False, p.stdout + p.stderr)
check("Ohne sqlglot: ok None (nie 'in Ordnung')", "ok" in ohne and ohne.get("ok") is None, ohne)

print("\n6. pruefen_gesamt und die Reparaturrunde")
_echt = R.pruefen
try:
    R.pruefen = lambda con, sql, erlaubt=None: {"ok": True, "fehler": [], "tabellen": ["t"], "unbelegte_joins": []}
    pg = R.pruefen_gesamt(None, "SELECT a, FROM t", None, "allgemein")
    check("Syntaxfehler kippt ok", pg["ok"] is False, pg)
    check("Syntaxfehler steht VORN in fehler", (pg["fehler"] or [""])[0].startswith("Syntax –"), pg["fehler"])
    check("Syntax-Ergebnis unter 'syntax'", (pg.get("syntax") or {}).get("ok") is False, pg.get("syntax"))
    pg = R.pruefen_gesamt(None, "SELECT a FROM t", None, "allgemein")
    check("Gute Abfrage: ok bleibt True", pg["ok"] is True and pg["syntax"]["ok"] is True, pg)
    R.pruefen = lambda con, sql, erlaubt=None: {"ok": False, "fehler": ["Unbekannte Tabellen: t"], "tabellen": []}
    pg = R.pruefen_gesamt(None, "SELECT a FROM t", None, "allgemein")
    check("Schemafehler bleibt erhalten", pg["ok"] is False and pg["fehler"] == ["Unbekannte Tabellen: t"], pg)
finally:
    R.pruefen = _echt

baum = ast.parse((ROOT / "backend/schema_graph_rag.py").read_text(encoding="utf-8"))
erz = next((n for n in ast.walk(baum) if isinstance(n, ast.AsyncFunctionDef) and n.name == "sql_erzeugen"), None)
if erz is None:
    abbruch("sql_erzeugen nicht gefunden")
namen = [a.id for c in ast.walk(erz) if isinstance(c, ast.Call)
         for a in c.args if isinstance(a, ast.Name)]
check("sql_erzeugen prueft ueber pruefen_gesamt", "pruefen_gesamt" in namen, namen)
check("sql_erzeugen prueft NICHT mehr nur das Schema", "pruefen" not in namen, namen)
aufruf = next((c for c in ast.walk(erz) if isinstance(c, ast.Call)
               and any(isinstance(a, ast.Name) and a.id == "pruefen_gesamt" for a in c.args)), None)
check("... und gibt den Dialekt mit", aufruf is not None and any(isinstance(a, ast.Name) and a.id == "dialekt"
                                                                  for a in aufruf.args))

print("\n7. main.py: eine Antwortform, Freigabe")
mbaum = ast.parse((ROOT / "backend/main.py").read_text(encoding="utf-8"))
fns = {n.name: n for n in ast.walk(mbaum) if isinstance(n, ast.AsyncFunctionDef)}


def ruft(fn, name):
    return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == name for c in ast.walk(fn))


for fname in ("sql_frage", "sql_pruefen_api"):
    fn = fns.get(fname)
    check(f"{fname} vorhanden", fn is not None)
    if fn is None:
        continue
    check(f"{fname} baut die Pruefung ueber _sql_pruefung_antwort", ruft(fn, "_sql_pruefung_antwort"))
    deps = [ast.unparse(d) for d in fn.args.defaults]
    check(f"{fname} haengt an require_schema_access", any("require_schema_access" in d for d in deps), deps)
fn = fns.get("sql_pruefen_api")
if fn is not None:
    deko = [ast.unparse(d) for d in fn.decorator_list]
    check("Route /api/sql/pruefen als POST", "app.post('/api/sql/pruefen')" in deko, deko)
    check("pruefen_gesamt wird benutzt", any(isinstance(c, ast.Attribute) and c.attr == "pruefen_gesamt"
                                              for c in ast.walk(fn)))
    check("Kein Modellaufruf im Pruefen", not any(isinstance(c, ast.Attribute) and c.attr == "sql_erzeugen"
                                                   for c in ast.walk(fn)))

print("\n8. Dialekte")
check("DIALEKT_PARSER deckt genau DIALEKTE ab", set(X.DIALEKT_PARSER) == set(DIALEKTE),
      set(X.DIALEKT_PARSER) ^ set(DIALEKTE))
from sqlglot.dialects.dialect import Dialect  # noqa: E402
fehlend = []
for d, pname in X.DIALEKT_PARSER.items():
    try:
        Dialect.get_or_raise(pname or None)
    except Exception:  # noqa: BLE001
        fehlend.append(pname)
check("Jeder Parsername existiert in sqlglot", not fehlend, fehlend)
check("Ersatz-Dialekte parsen als Standard-SQL", all(X.DIALEKT_PARSER[d] == "" for d in X.OHNE_EIGENEN_PARSER))

print(f"\nBilanz: {OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
