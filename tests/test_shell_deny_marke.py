#!/usr/bin/env python3
"""Waechter: eine abgewiesene Schranke nennt sich – und zaehlt einmal.

**Der Vorfall (ECHT, 2026-09-04, 17:11:19/:20/:21):** ``jonas.reichelt`` wurde
gesperrt, nachdem drei LESENDE Suchen in der Wissensdatenbank abgewiesen worden
waren – dreimal derselbe falsche Pfad ``/root/jarvis/data/knowledge``, der in
einem alten Merksatz im Gedaechtnis des Agenten steht und auf diesem Server
nicht existiert. Drei harte Verstoesse in DREI SEKUNDEN = Auto-Sperre.

Zwei Ursachen, beide hier abgesichert:

  1. **Die Meldung nannte nichts.** "Zugriff auf ein geschuetztes Verzeichnis/
     eine Secret-Datei ist gesperrt" sagt weder WAS getroffen wurde noch was zu
     tun ist – also kamen zwei Varianten desselben Pfades hinterher. Dieselbe
     Fehlerklasse wie "curl/wget/ssh/git/…" (Egress) und "mount error(13)".
  2. **Dieselbe Schranke zaehlte dreimal.** Der Befehlstext war jedes Mal ein
     anderer (find / grep / find|xargs), die Tuer aber dieselbe. Dreimal an
     dieselbe Tuer zu fassen ist ein Irrtum – drei verschiedene Tueren sind ein
     Muster, und nur das ist ein Angriffsindiz.

GEMESSEN WIRD AUSGEFUEHRT: ``authorize_shell`` und ``record_violation`` laufen
wirklich, mit den drei ECHTEN Befehlen aus dem Vorfall.

SANDKASTEN mit Exit 2 – ohne ihn schreibt der Test in die echte
``data/security_state.json`` und faelscht damit den Bestand, um den es geht.

Lauf:  timeout 120 python3 tests/test_shell_deny_marke.py
"""
import ast
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def abschnitt(t):
    print("\n\033[1m%s\033[0m" % t)


def check(name, cond, detail=""):
    """(Beschreibung, Bedingung) – NICHT umgekehrt."""
    global ok, fail
    if isinstance(name, bool) or not isinstance(name, str):
        print("\033[31mABBRUCH: check() falsch herum aufgerufen\033[0m")
        sys.exit(2)
    if bool(cond):
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – " + str(detail)) if detail else ""))


def abbruch(text):
    print("\033[31mABBRUCH: %s\033[0m" % text)
    sys.exit(2)


def sicher(fn, *a, **k):
    """Eine Pruefung darf FEHLSCHLAGEN, nicht ABBRECHEN."""
    try:
        return fn(*a, **k), ""
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


# ── Die drei ECHTEN Befehle aus dem Vorfall (woertlich) ────────────────────
VORFALL = [
    "find /root/jarvis/data/knowledge -type f -iname '*pathos*' -o -iname '*dc*' "
    "2>/dev/null | head -20",
    "grep -ri 'dc-pathos\\|dc pathos\\|dcpat' /root/jarvis/data/knowledge/ "
    "2>/dev/null | head -30",
    "find /root/jarvis/data/knowledge -type f 2>/dev/null | xargs grep -li "
    "'dc-pathos\\|dc pathos\\|dcpat' 2>/dev/null | head -20",
]

# ══ 1. Die Meldung nennt den Treffer ═══════════════════════════════════════
abschnitt("1 – Die abgewiesene Schranke nennt sich")

from backend import sandbox as sbx  # noqa: E402

marken = []
for i, cmd in enumerate(VORFALL, 1):
    r, f = sicher(sbx.authorize_shell, cmd)
    if r is None or len(r) != 3:
        check("Befehl %d: authorize_shell liefert (ok, grund, marke)" % i, False,
              f or repr(r))
        continue
    erlaubt, grund, marke = r
    marken.append(marke)
    check("Befehl %d wird abgewiesen (unveraendert)" % i, erlaubt is False)
    check("… und die Meldung NENNT den Treffer '/root'", "/root" in grund, grund[:90])
    check("… und den Weg zur Wissensdatenbank (knowledge_search)",
          "knowledge_search" in grund, grund[:120])
    check("… sie nennt NICHT den ganzen Befehl (der steht im Protokoll)",
          "iname" not in grund and "xargs" not in grund, grund[:120])

check("⚠ alle drei tragen DIESELBE Marke", len(set(marken)) == 1 and marken,
      str(marken))
check("… und die Marke benennt die Schranke, nicht den Befehl",
      marken and marken[0] == "pfad:/root", str(marken[:1]))

abschnitt("1b – Was sich dabei NICHT aendern darf")

r, f = sicher(sbx.authorize_shell, "grep -ri 'pathos' data/knowledge/ | head -30")
check("eine Suche in der echten Wissensdatenbank bleibt erlaubt",
      r is not None and r[0] is True, f or str(r))
r, _f = sicher(sbx.authorize_shell, "cat data/settings.json")
check("eine Secret-DATEI bleibt gesperrt", r is not None and r[0] is False, str(r))
check("… mit anderem Text (der knowledge-Hinweis waere dort irrefuehrend)",
      r is not None and "knowledge_search" not in r[1], str(r)[:120])
check("… und eigener Marke", r is not None and r[2] == "pfad:settings.json", str(r))
r, _f = sicher(sbx.authorize_shell, "echo aGFsbG8= | base64 -d | bash")
check("Verschleierung bleibt gesperrt", r is not None and r[0] is False, str(r))
check("… und traegt die Marke 'obfuskation'",
      r is not None and r[2] == "obfuskation", str(r))
check("… und nennt das getroffene Muster",
      r is not None and "base64" in r[1], str(r)[:140])

# ══ 2. Dieselbe Schranke zaehlt EINMAL ═════════════════════════════════════
abschnitt("2 – Zaehlung: gleiche Marke einmal, verschiedene Marken zaehlen")

SANDKASTEN = Path(tempfile.mkdtemp(prefix="jarvis-marke-test-"))

# backend.config NUR als Attrappe – der echte Import migriert Profile und
# schreibt die LIVE-settings.json zurueck (Register).
_cfg = types.ModuleType("backend.config")


class _C:
    @staticmethod
    def get_setting(name, default=None):
        return {"security_autoblock_enabled": True,
                "security_autoblock_count": 3,
                "security_autoblock_window": 600}.get(name, default)


_cfg.config = _C()
sys.modules.setdefault("backend.config", _cfg)

from backend import security_guard as sg  # noqa: E402

sg._STATE_FILE = SANDKASTEN / "security_state.json"
if not str(sg._STATE_FILE).startswith(str(SANDKASTEN)):
    abbruch("Zustandsdatei zeigt nicht in den Sandkasten: %s" % sg._STATE_FILE)
if sg._autoblock_cfg()["count"] != 3:
    abbruch("Attrappe greift nicht – Schwelle ist %r" % sg._autoblock_cfg())


def frisch():
    """Leerer Zustand fuer den naechsten Fall."""
    try:
        sg._STATE_FILE.unlink()
    except FileNotFoundError:
        pass


def melde(user, marke="", escalate=True, kind="shell-illegal", detail="x"):
    return sg.record_violation(user, "chat", kind, detail, marke=marke,
                               escalate=escalate)


frisch()
res = [melde("anna", "pfad:/root", detail=c) for c in VORFALL]
check("⚠⚠ DER GEMELDETE FALL: dreimal dieselbe Schranke sperrt NICHT",
      not any(r.get("blocked") for r in res), str(res))
check("… die Vorfaelle stehen trotzdem alle im Protokoll",
      res[-1].get("count") == 3, str(res[-1]))

frisch()
res = [melde("bert", "pfad:/root"), melde("bert", "pfad:.ssh/"),
       melde("bert", "pfad:settings.json")]
check("⚠ Positivkontrolle: DREI verschiedene Schranken sperren weiterhin",
      res[-1].get("blocked") is True, str(res))

frisch()
res = [melde("cara"), melde("cara"), melde("cara")]
check("⚠ ohne Marke zaehlt jeder Eintrag einzeln (fail-closed, wie bisher)",
      res[-1].get("blocked") is True, str(res))

frisch()
res = [melde("dora", "pfad:/root"), melde("dora", "pfad:/root"),
       melde("dora"), melde("dora")]
check("gemischt: zwei gleiche + zwei ohne Marke sperren",
      res[-1].get("blocked") is True, str(res))

frisch()
res = [melde("emil", "pfad:/root", escalate=False) for _ in range(5)]
check("weiche Eintraege sperren weiterhin nicht",
      not any(r.get("blocked") for r in res), str(res[-1]))

frisch()
sg.record_violation("fritz", "chat", "shell-illegal", "a", marke="pfad:/root")
zustand = sicher(lambda: __import__("json").loads(
    sg._STATE_FILE.read_text(encoding="utf-8")))[0]
eintrag = (list((zustand or {}).get("violations", {}).values()) or [[{}]])[0][0]
check("die Marke wird gespeichert (sonst zaehlt sie beim naechsten Lauf nicht)",
      eintrag.get("marke") == "pfad:/root", str(eintrag)[:160])
check("… und ersetzt weder detail noch pattern",
      eintrag.get("pattern") == "shell-illegal" and eintrag.get("detail") == "a",
      str(eintrag)[:160])

# ══ 3. Der Dispatch reicht die Marke weiter ════════════════════════════════
abschnitt("3 – REGEL: jeder harte Deny-Zweig setzt eine Marke")

QUELL = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
BAUM = ast.parse(QUELL)
eltern = {}
for knoten in ast.walk(BAUM):
    for kind in ast.iter_child_nodes(knoten):
        eltern[kind] = knoten


def block_von(knoten):
    """Die Anweisungsliste, in der dieser Knoten steht."""
    p = eltern.get(knoten)
    while p is not None:
        for feld in ("body", "orelse", "finalbody"):
            liste = getattr(p, feld, None)
            if isinstance(liste, list) and knoten in liste:
                return liste
        knoten, p = p, eltern.get(p)
    return []


def zuweisungen(liste, ziel):
    return [n for n in liste
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == ziel for t in n.targets)]


viol_stellen = [n for n in ast.walk(BAUM)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_viol" for t in n.targets)
                and not (isinstance(n.value, ast.Constant) and n.value.value is None)]
check("Positivkontrolle: Deny-Zweige gefunden", len(viol_stellen) >= 6,
      str(len(viol_stellen)))

ohne = []
for n in viol_stellen:
    blk = block_von(n)
    weich = any(isinstance(z.value, ast.Constant) and z.value.value is True
                for z in zuweisungen(blk, "_viol_soft"))
    hat_marke = bool(zuweisungen(blk, "_viol_marke"))
    if not (weich or hat_marke):
        ohne.append("Zeile %d" % n.lineno)
check("⚠ jeder HARTE Deny-Zweig setzt _viol_marke (weiche brauchen keine)",
      not ohne, ", ".join(ohne))

aufrufe = [n for n in ast.walk(BAUM)
           if isinstance(n, ast.Call)
           and isinstance(n.func, ast.Attribute)
           and n.func.attr == "record_violation"]
check("Positivkontrolle: record_violation wird im Dispatch gerufen", bool(aufrufe))
check("⚠ und bekommt die Marke uebergeben",
      all(any(k.arg == "marke" for k in a.keywords) for a in aufrufe),
      str(len(aufrufe)))

sig = next((n for n in ast.walk(ast.parse(
    (ROOT / "backend" / "security_guard.py").read_text(encoding="utf-8")))
    if isinstance(n, ast.FunctionDef) and n.name == "record_violation"), None)
check("record_violation kennt den Parameter",
      sig is not None and any(a.arg == "marke" for a in sig.args.args))
vorgabe = ""
if sig is not None:
    args = sig.args.args
    stand = len(args) - len(sig.args.defaults)
    for i, a in enumerate(args):
        if a.arg == "marke" and i >= stand:
            d = sig.args.defaults[i - stand]
            vorgabe = d.value if isinstance(d, ast.Constant) else "?"
check("⚠ Vorgabe ist LEER – ein neuer Zweig verhaelt sich ohne Zutun wie bisher",
      vorgabe == "", repr(vorgabe))

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
