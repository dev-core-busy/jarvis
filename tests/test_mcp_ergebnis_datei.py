#!/usr/bin/env python3
"""Waechter: grosse MCP-Ergebnisse liegen als Datei vor, `write` ohne Inhalt scheitert laut.

Vorfall DEV 2026-10-25: "liefere eine theben Befundliste … als csv". Das
MCP-Werkzeug lieferte 270.000 Zeichen CSV; um eine Datei daraus zu machen,
haette das Modell alles als `content` von `filesystem write` wiederholen
muessen. Der Aufruf kam abgeschnitten OHNE `content` an, `write` meldete
"✅ … (0 Zeichen)", und das Modell holte die Daten erneut (zweite
Bestaetigungskarte).

Gemessen wird die WIRKUNG der echten Funktionen:
  * ``_ergebnis_kappen`` + ``_mcp_ergebnis_ablegen`` per AST aus
    backend/agent.py geschnitten, ``lauf_tmp`` als Attrappe mit derselben
    Signatur (aufloesen bildet /tmp/<name> in einen Sandkasten ab),
  * ``FileSystemTool`` echt importiert (keine schweren Abhaengigkeiten).

Lauf:  python3 tests/test_mcp_ergebnis_datei.py
"""
import ast
import asyncio
import csv
import io
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("JARVIS_TEST_ROOT") or Path(__file__).resolve().parent.parent)
AGENT = ROOT / "backend" / "agent.py"
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        fail += 1
        print(f"  ❌ {name}" + (f" – {detail}" if detail else ""))


SANDKASTEN = Path(tempfile.mkdtemp(prefix="mcp_datei_"))
LAUF = SANDKASTEN / "lauf"
LAUF.mkdir()


class _LaufTmp:
    """Attrappe von backend.lauf_tmp – nur die drei benutzten Funktionen."""
    kaputt = False

    @staticmethod
    def temp_verzeichnis():
        return LAUF

    @classmethod
    def aufloesen(cls, pfad):
        if cls.kaputt:
            raise OSError("Attrappe: Ablage scheitert")
        s = str(pfad)
        return str(LAUF / s[len("/tmp/"):]) if s.startswith("/tmp/") else s

    @staticmethod
    def im_lauf_freigeben(pfad):
        return None


def _host(modell):
    return LAUF / str(modell)[len("/tmp/"):]


# ── Schnitt aus agent.py ─────────────────────────────────────────────────
src = AGENT.read_text(encoding="utf-8")
baum = ast.parse(src)
teile = []
for k in baum.body:
    if isinstance(k, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                                         {"_TOOL_ERGEBNIS_MAX", "_MCP_DATEI_AB", "_MCP_TOOL_PREFIX",
                                          "_ABLAGE_KOPF"}
                                         for t in k.targets):
        teile.append(k)
    elif isinstance(k, ast.FunctionDef) and k.name in ("_ist_mcp_tool", "_csv_fuer_excel",
                                                          "_ohne_ablagehinweis"):
        teile.append(k)
methoden = []
for k in ast.walk(baum):
    if isinstance(k, ast.ClassDef):
        for m in k.body:
            if isinstance(m, ast.FunctionDef) and m.name in ("_ergebnis_kappen",
                                                              "_mcp_ergebnis_ablegen"):
                methoden.append(m)
namen = sorted({getattr(t, "id", "") for k in teile if isinstance(k, ast.Assign)
                for t in k.targets} | {k.name for k in teile if isinstance(k, ast.FunctionDef)})
if len(teile) != 7 or len(methoden) != 2:
    print(f"ABBRUCH: Bausteine nicht gefunden (Modul {namen}, Methoden "
          f"{[m.name for m in methoden]})")
    shutil.rmtree(SANDKASTEN, ignore_errors=True)
    sys.exit(2)

klasse = ast.ClassDef(name="_Agent", bases=[], keywords=[], body=methoden,
                      decorator_list=[], type_params=[])
modul = ast.fix_missing_locations(ast.Module(body=teile + [klasse], type_ignores=[]))
ns = {"re": re, "time": time, "uuid": uuid, "Path": Path, "_lauf_tmp": _LaufTmp}
exec(compile(modul, "agent_schnitt", "exec"), ns)


class _Werkzeug:
    def __init__(self, name, mcp, grenze=0):
        self.name = name
        self.ist_mcp = mcp
        self.ergebnis_max = grenze


class Agent(ns["_Agent"]):
    agent_id = "test"

    def __init__(self, werkzeuge):
        self.tools_map = {w.name: w for w in werkzeuge}

    def _bilddaten_bergen(self, tool_name, text):
        return text


MCP = "mcp_theben_list_befunde"
agent = Agent([_Werkzeug(MCP, True, -1), _Werkzeug("mcp_x_begrenzt", True, 8000),
               _Werkzeug("knowledge_search", False)])
GRENZE = ns["_TOOL_ERGEBNIS_MAX"]

# Wie die echte theben-Liste: Komma-CSV, Felder in Anfuehrungszeichen mit
# Kommas darin, Umlaute, leere Felder. Genau daran scheiterte die erste
# Fassung (Trenner gezaehlt statt geparst -> .txt).
kopf = "befund_id,eingangsdatum,nachname,empfaenger,pathologisch,sendezeit\n"
zeilen = "".join(f'{100000 + i},2026-10-2{i % 5},Müller-{i},"MVZ Beispiel, BSNR: {i}",0,\n'
                 for i in range(6000))
CSV = kopf + zeilen
ERWARTET = [z for z in csv.reader(io.StringIO(CSV)) if z]


def _lies_csv(pfad):
    with open(pfad, encoding="utf-8-sig", newline="") as f:
        return [z for z in csv.reader(f, delimiter=";") if z]

print("\n0. Positivkontrolle: der Messaufbau stellt den Vorfall her")
check("CSV ist groesser als die Ablageschwelle", len(CSV) > ns["_MCP_DATEI_AB"], str(len(CSV)))
check("Sandkasten ist leer", not any(LAUF.iterdir()))
if fail:
    print("ABBRUCH: Messaufbau unbrauchbar")
    shutil.rmtree(SANDKASTEN, ignore_errors=True)
    sys.exit(2)

print("\n1. Grosses MCP-Ergebnis, Grenze unbegrenzt")
aus = agent._ergebnis_kappen(MCP, CSV)
m = re.match(r"\[VOLLSTAENDIGES ERGEBNIS GESPEICHERT: (/tmp/\S+) ", aus)
check("⚠ der Hinweis steht VORN und nennt einen /tmp-Pfad", bool(m), aus[:120])
modell = m.group(1) if m else ""
datei = _host(modell) if modell else None
check("die Datei existiert im Lauf-Verzeichnis", bool(datei) and datei.is_file(), str(datei))
check("⚠ Endung .csv erkannt – trotz Kommas in Anfuehrungszeichen",
      modell.endswith(".csv"), modell)
ist = _lies_csv(datei) if datei and datei.is_file() else []
check("Positivkontrolle: das Original hat 6 Spalten und Kommas in Feldern",
      len(ERWARTET[1]) == 6 and "," in ERWARTET[1][3], str(ERWARTET[1]))
check("⚠ mit ';' gelesen ergibt die Datei ZELLGENAU die Originaltabelle",
      ist == ERWARTET, f"{len(ist)} gegen {len(ERWARTET)} Zeilen")
check("die Datei beginnt mit BOM (Excel liest sonst Umlaute falsch)",
      bool(datei) and datei.is_file() and datei.read_bytes()[:3] == b"\xef\xbb\xbf")
erster_teil = aus.split("\n\n", 1)[0]
check("⚠ der Hinweis enthaelt KEINEN Liefer-Marker (sonst liefert ihn das System selbst aus)",
      "[[JARVIS_DELIVER" not in erster_teil, erster_teil[:300])
check("der Hinweis nennt Pfad, Liefer-Marker und einen echten Anzeigenamen",
      modell in erster_teil and "Liefer-Marker" in erster_teil
      and "theben_list_befunde.csv" in erster_teil and "<" not in erster_teil, erster_teil)
check("der Hinweis sagt, dass es Semikolon-CSV ist", "Semikolon" in erster_teil)
check("das Ergebnis selbst bleibt vollstaendig (Grenze unbegrenzt)", aus.endswith(CSV))
check("der Hinweis verbietet das Abschreiben per filesystem write",
      "filesystem write" in aus.split("\n\n", 1)[0])

print("\n2. Grosses MCP-Ergebnis mit eigener Grenze")
aus2 = agent._ergebnis_kappen("mcp_x_begrenzt", CSV)
m2 = re.match(r"\[VOLLSTAENDIGES ERGEBNIS GESPEICHERT: (/tmp/\S+) ", aus2)
check("Hinweis vorn", bool(m2), aus2[:80])
check("gekuerzt auf die Grenze (+ Hinweise)", len(aus2) < 8000 + 1500, str(len(aus2)))
check("der Kuerzungsvermerk verweist auf die Datei",
      bool(m2) and f"vollstaendig in {m2.group(1)}" in aus2[-200:], aus2[-200:])

print("\n3. Wann NICHT abgelegt wird")
vorher = set(LAUF.iterdir())
lang_nicht_mcp = agent._ergebnis_kappen("knowledge_search", CSV)
check("kein MCP-Werkzeug: kein Hinweis", "GESPEICHERT" not in lang_nicht_mcp[:200])
kurz = "a,b\n1,2\n"
check("kurzes MCP-Ergebnis: byte-gleich", agent._ergebnis_kappen(MCP, kurz) == kurz)
fehler = "❌ MCP-Tool Fehler (theben/list_befunde): " + "x" * (GRENZE * 2)
check("MCP-Fehlertext: keine Datei", "GESPEICHERT" not in agent._ergebnis_kappen(MCP, fehler)[:200])
check("in keinem dieser Faelle entstand eine Datei", set(LAUF.iterdir()) == vorher,
      str(set(LAUF.iterdir()) - vorher))

print("\n4. Endungen und Trenner")
semi = "a;b;c\n" + "".join(f"{i};x;\"y;z\"\n" for i in range(2000))
ms = re.match(r"\[VOLLSTAENDIGES ERGEBNIS GESPEICHERT: (/tmp/\S+) ",
              agent._ergebnis_kappen(MCP, semi))
check("schon Semikolon-CSV: Inhalt bleibt unveraendert",
      bool(ms) and ms.group(1).endswith(".csv")
      and _host(ms.group(1)).read_text(encoding="utf-8-sig") == semi)
schief = "a,b,c\n" + "1,2\n" * 3000
mf = re.match(r"\[VOLLSTAENDIGES ERGEBNIS GESPEICHERT: (/tmp/\S+) ",
              agent._ergebnis_kappen(MCP, schief))
check("ungleiche Spaltenzahl: KEIN CSV, Text byte-gleich als .txt",
      bool(mf) and mf.group(1).endswith(".txt")
      and _host(mf.group(1)).read_text(encoding="utf-8") == schief)
js = '[{"id": 1}' + ', {"id": 2}' * 3000 + "]"
mj = re.match(r"\[VOLLSTAENDIGES ERGEBNIS GESPEICHERT: (/tmp/\S+) ",
              agent._ergebnis_kappen(MCP, js))
check("JSON -> .json", bool(mj) and mj.group(1).endswith(".json"))
prosa = ("Das ist ein Satz ohne Trenner. " * 400)
mp = re.match(r"\[VOLLSTAENDIGES ERGEBNIS GESPEICHERT: (/tmp/\S+) ",
              agent._ergebnis_kappen(MCP, prosa))
check("Fliesstext -> .txt", bool(mp) and mp.group(1).endswith(".txt"))
check("JSON byte-gleich abgelegt",
      bool(mj) and _host(mj.group(1)).read_text(encoding="utf-8") == js)

print("\n5. Fail-safe: scheitert die Ablage, bleibt das Ergebnis wie bisher")
_LaufTmp.kaputt = True
aus5 = agent._ergebnis_kappen(MCP, CSV)
_LaufTmp.kaputt = False
check("ohne Hinweis, Ergebnis unveraendert", aus5 == CSV)

print("\n6. filesystem write/append ohne `content`")
sys.path.insert(0, str(ROOT))
try:
    from backend.tools.filesystem import FileSystemTool
except Exception as ex:  # noqa: BLE001
    print(f"ABBRUCH: FileSystemTool nicht ladbar: {ex}")
    shutil.rmtree(SANDKASTEN, ignore_errors=True)
    sys.exit(2)
fs = FileSystemTool()
ziel = SANDKASTEN / "befunde.csv"
r = asyncio.run(fs.execute(action="write", path=str(ziel)))
check("⚠ write ohne content meldet einen Fehler", r.startswith("❌"), r)
check("⚠ … und legt KEINE Datei an", not ziel.exists())
r = asyncio.run(fs.execute(action="append", path=str(ziel)))
check("append ohne content meldet einen Fehler", r.startswith("❌"), r)
r = asyncio.run(fs.execute(action="write", path=str(ziel), content=""))
check("ausdruecklich leerer Inhalt bleibt erlaubt", r.startswith("✅") and ziel.is_file()
      and ziel.stat().st_size == 0, r)
r = asyncio.run(fs.execute(action="write", path=str(ziel), content="a,b\n"))
check("Positivkontrolle: normales write schreibt", ziel.read_text() == "a,b\n", r)
r = asyncio.run(fs.execute(action="read", path=str(ziel)))
check("read ohne content ist unberuehrt", r == "a,b\n", r)

print("\n7. Anzeige und Auslieferung sehen den Ablage-Hinweis NICHT")
ohne = ns["_ohne_ablagehinweis"]
voll = agent._ergebnis_kappen(MCP, CSV)
check("Positivkontrolle: das Ergebnis traegt den Hinweis mit /tmp-Pfad",
      voll.startswith(ns["_ABLAGE_KOPF"]) and "/tmp/" in voll[:300])
sichtbar = ohne(voll)
check("⚠ ohne Hinweis bleibt GENAU das Werkzeug-Ergebnis (kein /tmp-Pfad mehr)",
      sichtbar == CSV, sichtbar[:120])
check("ein Ergebnis ohne Hinweis bleibt unveraendert", ohne(CSV) == CSV)

# Regel am Syntaxbaum: der Aufruf von _deliver_docs fuer ein WERKZEUG-Ergebnis
# und die Statuszeile bekommen den bereinigten Text, nicht result_str.
rt = next((f for f in ast.walk(baum) if isinstance(f, ast.AsyncFunctionDef)
           and f.name == "run_task"), None)
check("Positivkontrolle: run_task gefunden", rt is not None)
liefer = [c for c in ast.walk(rt) if isinstance(c, ast.Call)
          and getattr(c.func, "attr", "") == "_deliver_docs"] if rt else []
werkzeug_aufrufe = [c for c in liefer if len(c.args) >= 2
                    and not any(k.arg == "melden" for k in c.keywords)]
check("Positivkontrolle: genau ein Werkzeug-Ergebnis-Aufruf von _deliver_docs",
      len(werkzeug_aufrufe) == 1, str(len(werkzeug_aufrufe)))
arg = werkzeug_aufrufe[0].args[1] if werkzeug_aufrufe else None
zuw = {a.targets[0].id: a.value for a in ast.walk(rt) if isinstance(a, ast.Assign)
       and len(a.targets) == 1 and isinstance(a.targets[0], ast.Name)} if rt else {}
quelle = zuw.get(arg.id) if isinstance(arg, ast.Name) else arg
check("⚠ _deliver_docs bekommt den Text durch _ohne_ablagehinweis",
      isinstance(quelle, ast.Call) and getattr(quelle.func, "id", "") == "_ohne_ablagehinweis",
      ast.unparse(arg) if arg is not None else "-")
status = [c for c in ast.walk(rt) if isinstance(c, ast.Call)
          and getattr(c.func, "attr", "") == "_send_status" and len(c.args) >= 2
          and "Ergebnis:" in ast.unparse(c.args[1])] if rt else []
check("die Statuszeile '📋 Ergebnis' zeigt den bereinigten Text",
      len(status) == 1 and "result_str" not in ast.unparse(status[0].args[1])
      and isinstance(arg, ast.Name) and arg.id in ast.unparse(status[0].args[1]),
      ast.unparse(status[0].args[1]) if status else "nicht gefunden")

shutil.rmtree(SANDKASTEN, ignore_errors=True)
print(f"\nERGEBNIS: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
