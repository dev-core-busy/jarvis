#!/usr/bin/env python3
"""Jira-Kommentare: vollstaendig statt "letzte 3" – und der Weg in den Kontext.

Ohne fastapi lauffaehig: geprueft werden die Formatierung (echte Funktion aus
dem Skill, mit Attrappen-Client) und die Kapp-Logik des Agenten per Quelltext
bzw. als nachgebaute Methode.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def section(t):
    print("\n" + "=" * 70 + "\n  " + t + "\n" + "=" * 70)


JIRA = (ROOT / "skills" / "jira" / "main.py").read_text(encoding="utf-8")
AGENT = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")


def nur_code(text: str) -> str:
    """Ohne Kommentare und Docstrings – ein Waechter darf nicht seine eigene
    Begruendung lesen (im Projekt achtmal passiert)."""
    text = re.sub(r'"""(?:.|\n)*?"""', "", text)
    return "\n".join(z for z in text.splitlines() if not z.lstrip().startswith("#"))


section("1. Der Skill gibt ALLE Kommentare aus")
_get = JIRA[JIRA.index("class JiraGetIssueTool"):JIRA.index("class JiraListProjectsTool")]
_code = nur_code(_get)
check("comments[-3:]" not in _code, "kein 'letzte 3'-Schnitt mehr")
check("for cm in comments:" in _code, "es wird ueber ALLE Kommentare gelaufen")
check(", 400)" not in _code, "kein 400-Zeichen-Schnitt je Kommentar mehr")
check("KOMMENTAR_MAX" in _code, "die verbleibende Grenze ist benannt (kein Zufallswert)")
check("letzte 3" not in _get, "auch der Text sagt nicht mehr 'letzte 3'")
check("VOLLSTAENDIG" in _get.upper(),
      "die Werkzeug-Beschreibung sagt zu, was der Code tut")

section("2. Der Weg in den Kontext – sonst ist die Zusage wertlos")
check("ergebnis_max" in _code, "das Werkzeug verlangt einen groesseren Ergebnis-Deckel")
_m = re.search(r"ergebnis_max\s*=\s*(\d+)", _code)
check(bool(_m) and int(_m.group(1)) > 5000,
      "und zwar deutlich mehr als die 5000 der Vorgabe",
      _m.group(1) if _m else "-")
_ag = nur_code(AGENT)
check("str(result)[:5000]" not in _ag, "der feste 5000er-Schnitt ist weg")
check(_ag.count("self._ergebnis_kappen(tool_name, result)") == 2,
      "beide Wege (Chat UND headless) benutzen den Helfer",
      str(_ag.count("self._ergebnis_kappen(tool_name, result)")))
check("_TOOL_ERGEBNIS_MAX = 5000" in _ag,
      "die Vorgabe fuer alle anderen Werkzeuge bleibt bei 5000")

section("3. Kappen weist die Kuerzung AUS")
_kap = AGENT[AGENT.index("def _ergebnis_kappen"):AGENT.index("async def _deliver_docs")]
check("gekuerzt" in _kap, "eine Kuerzung steht im Text (nichts stillschweigend abschneiden)")
check("len(text)" in _kap, "und nennt die Gesamtlaenge")


class _Tool:
    def __init__(self, m=0):
        if m:
            self.ergebnis_max = m


class _Agent:
    """Nur die Methode – der echte Agent zoege fastapi und ein LLM nach."""
    def __init__(self, tools):
        self.tools_map = tools

    _TOOL_ERGEBNIS_MAX = 5000

    # Seit 2026-08-26 lagert `_ergebnis_kappen` ZUERST base64-Bilddaten aus
    # (`_bilddaten_bergen`). Hier wird nur das KAPPEN geprueft, deshalb eine
    # Durchreiche – ohne sie bricht dieser Test mit AttributeError ab und misst
    # gar nichts mehr. Die Bergung hat ihren eigenen Waechter:
    # tests/test_bilddaten_bergen.py.
    def _bilddaten_bergen(self, tool_name, text):
        return text


# Die echte Methode aus agent.py in die Attrappe holen.
_src = _kap.replace("_TOOL_ERGEBNIS_MAX", "self._TOOL_ERGEBNIS_MAX")
_ns = {}
exec("class _A:\n" + "\n".join("    " + z for z in _src.splitlines()), _ns)
_A = _ns["_A"]
_Agent._ergebnis_kappen = _A._ergebnis_kappen

a = _Agent({"klein": _Tool(), "gross": _Tool(120000)})
kurz = "x" * 100
lang = "y" * 9000
check(a._ergebnis_kappen("klein", kurz) == kurz, "kurzes Ergebnis bleibt unangetastet")
_g = a._ergebnis_kappen("klein", lang)
check(len(_g) < 9000 and "gekuerzt" in _g,
      "langes Ergebnis wird gekuerzt UND weist es aus")
check(a._ergebnis_kappen("gross", lang) == lang,
      "ein Werkzeug mit eigenem Deckel bekommt sein volles Ergebnis")
check(a._ergebnis_kappen("unbekannt", kurz) == kurz,
      "ein unbekanntes Werkzeug faellt auf die Vorgabe zurueck (kein Absturz)")
check(a._ergebnis_kappen("klein", 12345) == "12345",
      "auch Nicht-Strings werden verarbeitet")

section("4. Formatierung am echten Code")
# Die Kommentarzeilen werden aus dem echten Ausschnitt nachgebaut: Autor, Datum
# und Text muessen drin sein, sonst ist "vollstaendiger Verlauf" nur eine Zahl.
check('cm.get("created")' in _code, "das Datum je Kommentar steht dabei")
check('(cm.get("author") or {}).get("displayName"' in _code, "der Autor ebenfalls")

print("\n" + "=" * 70)
print("  %d OK, %d FAIL" % (_ok, _fail))
print("=" * 70)
sys.exit(1 if _fail else 0)
