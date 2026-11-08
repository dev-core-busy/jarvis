#!/usr/bin/env python3
"""Waechter: Support-Suche liefert Jira-Daten nur mit Jira-Freigabe (2026-11-08).

Betreiber-Entscheid zu Pentest C4: "ohne Freigabe keine Infos". Die Suche liest
Jira ueber den Sammelzugang (Server-PAT) – ohne Schranke saehe jeder angemeldete
Benutzer Tickets, die ihm die Jira-Freigabe verwehrt.

  [1] ``_support_jira_erlaubt`` AUSGEFUEHRT: leer = nein, ``api`` = ja,
      freigegeben = ja, sonst nein.
  [2] ``_support_summarize_block`` AUSGEFUEHRT: ohne Freigabe wird KEIN
      Jira-Client angelegt (kein Nachladen ueber den Sammelzugang); mit Freigabe
      schon (Positivkontrolle).
  [3] ``_support_run_query`` (AST): die Freigabe schaltet ``use_jira`` NACH der
      Ticket-Key-Erkennung ab (sonst schaltete ein Key Jira wieder ein), und der
      Jira-Abruf haengt an ``use_jira``.
  [4] ``support_summarize`` (AST): der Einzel-Modus weist ohne Freigabe ab,
      BEVOR ``_support_summarize_block`` laeuft.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


Q = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
B = ast.parse(Q)
FN = {n.name: n for n in B.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
for n in ("_support_jira_erlaubt", "_support_summarize_block", "_support_run_query",
          "support_summarize"):
    if n not in FN:
        abbruch("%s fehlt in main.py" % n)

# ── [1] Praedikat ─────────────────────────────────────────────────────────
print("\n[1] _support_jira_erlaubt")
FREI = {"freigegeben"}
ns = {"_user_may_use_jira_assist": lambda u: u in FREI}
exec(compile(ast.fix_missing_locations(ast.Module(body=[FN["_support_jira_erlaubt"]],
                                                  type_ignores=[])), "main", "exec"), ns)
erl = ns["_support_jira_erlaubt"]
check("(Positivkontrolle) freigegebener Benutzer darf", erl("freigegeben") is True)
check("nicht freigegebener Benutzer darf nicht", erl("kollege") is False)
check("leerer Benutzer darf nicht (fail-closed)", erl("") is False and erl(None) is False)
check("API-Schluessel-Benutzer 'api' darf", erl("api") is True)

# ── [2] Nachladen ohne Freigabe ───────────────────────────────────────────
print("\n[2] _support_summarize_block")
ANGELEGT = []


class _Halt(Exception):
    pass


def _jira_client(user=""):
    ANGELEGT.append(user)
    raise _Halt("Attrappe: Abruf erreicht")


# Der Zweig importiert ``backend.jira_client`` VOR dem Client-Aufbau; ohne das
# Modul liefe er ins except und die Positivkontrolle waere nicht erreichbar.
import types as _types  # noqa: E402
_jc = _types.ModuleType("backend.jira_client")
_jc.html_to_text = lambda t, n=0: str(t or "")
sys.modules.setdefault("backend", _types.ModuleType("backend"))
sys.modules["backend.jira_client"] = _jc


def lauf(erlaubt):
    ANGELEGT.clear()
    ns2 = {"asyncio": asyncio, "print": lambda *a, **k: None, "_jira_client": _jira_client,
           "_support_jira_erlaubt": lambda u: erlaubt}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[FN["_support_summarize_block"]],
                                                      type_ignores=[])), "main", "exec"), ns2)
    b = {"source": "JIRA", "_key": "PRJA-1", "key": "PRJA-1", "title": "PRJA-1", "summary": ""}
    try:
        asyncio.run(ns2["_support_summarize_block"](b, 4, "de", "", prof=None, user="kollege"))
    except _Halt:
        pass
    except Exception:  # noqa: BLE001 – spaetere Schritte brauchen Attrappen, die hier fehlen
        pass
    return b


b_ja = lauf(True)
check("(Positivkontrolle) mit Freigabe wird der Jira-Client angelegt", ANGELEGT == ["kollege"],
      repr(ANGELEGT))
b_nein = lauf(False)
check("ohne Freigabe KEIN Jira-Client (kein Abruf ueber den Sammelzugang)", ANGELEGT == [],
      repr(ANGELEGT))
check("ohne Freigabe nennt die Zusammenfassung den Grund",
      "Freigabe" in (b_nein.get("summary") or ""), repr(b_nein.get("summary")))

# ── [3] Reihenfolge in der Suche ──────────────────────────────────────────
print("\n[3] _support_run_query")
rq = FN["_support_run_query"]
an = [n.lineno for n in ast.walk(rq) if isinstance(n, ast.Assign)
      and any(isinstance(t, ast.Name) and t.id == "use_jira" for t in n.targets)
      and isinstance(n.value, ast.Constant) and n.value.value is True]
aus = [n.lineno for n in ast.walk(rq) if isinstance(n, ast.Assign)
       and any(isinstance(t, ast.Name) and t.id == "use_jira" for t in n.targets)
       and isinstance(n.value, ast.Constant) and n.value.value is False]
verw = [n.lineno for n in ast.walk(rq) if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "jira_verweigert" for t in n.targets)
        and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                and c.func.id == "_support_jira_erlaubt" for c in ast.walk(n.value))]
check("(Positivkontrolle) es gibt die Ticket-Key-Einschaltung use_jira = True", bool(an), repr(an))
check("jira_verweigert wird aus _support_jira_erlaubt berechnet", bool(verw), repr(verw))
check("die Abschaltung use_jira = False steht NACH der letzten Einschaltung",
      bool(an) and bool(aus) and max(aus) > max(an), "an=%r aus=%r" % (an, aus))
abruf = [n.lineno for n in ast.walk(rq) if isinstance(n, ast.If)
         and any(isinstance(x, ast.Name) and x.id == "use_jira" for x in ast.walk(n.test))
         and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                 and c.func.id == "_jira_client" for c in ast.walk(n))]
check("der Jira-Abruf haengt an use_jira und steht nach der Abschaltung",
      bool(abruf) and bool(aus) and min(abruf) > max(aus), "abruf=%r aus=%r" % (abruf, aus))

# ── [4] Einzel-Modus ──────────────────────────────────────────────────────
print("\n[4] support_summarize")
ss = FN["support_summarize"]
schranke = [n.lineno for n in ast.walk(ss) if isinstance(n, ast.If)
            and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                    and c.func.id == "_support_jira_erlaubt" for c in ast.walk(n.test))
            and any(isinstance(r, ast.Return) for r in n.body)]
block = [n.lineno for n in ast.walk(ss) if isinstance(n, ast.Call)
         and isinstance(n.func, ast.Name) and n.func.id == "_support_summarize_block"]
check("(Positivkontrolle) der Einzel-Modus ruft _support_summarize_block", bool(block))
check("Freigabe-Schranke mit return VOR dem Abruf",
      bool(schranke) and bool(block) and min(schranke) < min(block),
      "schranke=%r block=%r" % (schranke, block))

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
