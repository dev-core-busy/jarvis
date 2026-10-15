"""Waechter: Confluence-Seiten mit Elternbezug fuer den /wissen-Seitenbaum.

Gefahren wird der ECHTE `ConfluenceClient.pages_in_space`; gestellt ist nur
`_request` (Antwortform wie Confluence `/rest/api/content`, `ancestors` von der
Wurzel zur direkten Elternseite). Geprueft wird:
  - with_parent=True fordert `expand=ancestors` an und setzt `parent`
    = ID der DIREKTEN Elternseite ("" fuer Wurzeln),
  - ohne with_parent bleibt Anfrage und Antwort wie bisher (andere Aufrufer),
  - der /wissen-Endpunkt ruft mit with_parent=True (am Syntaxbaum gemessen).
Exit 2, wenn der Client nicht importierbar ist.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

res = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


try:
    from backend.confluence_client import ConfluenceClient
except Exception as e:  # noqa: BLE001
    print(f"Client nicht importierbar ({e}) – NICHT PRUEFBAR")
    sys.exit(2)

SEITEN = [
    {"id": "1", "title": "A", "ancestors": [], "_links": {"webui": "/a"}},
    {"id": "11", "title": "A1", "ancestors": [{"id": "1"}], "_links": {"webui": "/a1"}},
    {"id": "111", "title": "A1a", "ancestors": [{"id": "1"}, {"id": 11}], "_links": {}},
]


def client():
    c = ConfluenceClient({"base_url": "https://cf.invalid", "api_token": "x"})
    c.anfragen = []

    def _request(method, path, params=None, **kw):
        c.anfragen.append(dict(params or {}))
        start = int((params or {}).get("start", 0))
        # Confluence liefert "ancestors" nur, wenn expand es verlangt
        mit = "ancestors" in str((params or {}).get("expand", ""))
        rows = [dict(s) for s in SEITEN[start:start + 50]]
        if not mit:
            for r in rows:
                r.pop("ancestors", None)
        return {"results": rows, "_links": {"base": "https://cf.invalid"}}

    c._request = _request
    return c


print("\n\033[1m0. Positivkontrolle\033[0m")
c = client()
alt = c.pages_in_space("NX", 500)
check("(Positivkontrolle) die Attrappe liefert Seiten", len(alt) == 3, f"{len(alt)}")
if len(alt) != 3:
    sys.exit(2)

print("\n\033[1m1. Ohne with_parent: Bestand unveraendert\033[0m")
check("kein expand in der Anfrage", all("expand" not in a for a in c.anfragen), str(c.anfragen))
check("kein parent-Feld in der Antwort", all("parent" not in p for p in alt), str(alt))

print("\n\033[1m2. with_parent=True\033[0m")
c = client()
neu = c.pages_in_space("NX", 500, True)
check("expand=ancestors angefordert", all(a.get("expand") == "ancestors" for a in c.anfragen), str(c.anfragen))
by = {p["id"]: p for p in neu}
check("Wurzel -> parent ''", by.get("1", {}).get("parent") == "", str(by.get("1")))
check("Kind -> direkte Elternseite", by.get("11", {}).get("parent") == "1", str(by.get("11")))
check("Enkel -> DIREKTE Elternseite, nicht die Wurzel (und als Text)",
      by.get("111", {}).get("parent") == "11", str(by.get("111")))
check("id/title/link bleiben", by.get("11", {}).get("link") == "https://cf.invalid/a1"
      and by.get("11", {}).get("title") == "A1", str(by.get("11")))

print("\n\033[1m3. /wissen-Endpunkt fordert den Elternbezug an (AST)\033[0m")
baum = ast.parse(open(os.path.join(ROOT, "backend", "main.py"), encoding="utf-8").read())
fn = next((n for n in ast.walk(baum)
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "wissen_confluence_pages"), None)
check("(Positivkontrolle) wissen_confluence_pages gefunden", fn is not None)
if fn is None:
    sys.exit(2)
aufrufe = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and n.args
           and isinstance(n.args[0], ast.Attribute) and n.args[0].attr == "pages_in_space"]
check("genau ein pages_in_space-Aufruf", len(aufrufe) == 1, f"{len(aufrufe)}")
mit_parent = False
for a in aufrufe:
    # to_thread(c.pages_in_space, space, limit, with_parent)
    if len(a.args) >= 4 and isinstance(a.args[3], ast.Constant) and a.args[3].value is True:
        mit_parent = True
    for k in a.keywords:
        if k.arg == "with_parent" and isinstance(k.value, ast.Constant) and k.value.value is True:
            mit_parent = True
check("... mit with_parent=True", mit_parent)

ok = sum(res)
print(f"\n\033[1mErgebnis: {ok}/{len(res)}\033[0m")
sys.exit(0 if ok == len(res) else 1)
