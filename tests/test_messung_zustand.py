#!/usr/bin/env python3
"""Waechter: eine Messung darf keinen Zustand HINTERLASSEN, den sie geraten hat.

⚠ ANLASS (2026-09-09), und der Betreiber hat es zu Recht scharf gemeldet: meine
Live-Proben zur AI-Maus haben den Skill zum Messen eingeschaltet und am Ende
hart wieder AUSgeschaltet – `POST /api/skills/<name>/disable` im finally. Der
Betreiber hatte ihn aber eingeschaltet, um damit zu arbeiten. Jede Messung nahm
ihm den Skill also wieder weg, mehrfach hintereinander.

DIE REGEL, die daraus folgt und fuer JEDE Messung gilt:

    Sichere den VORGEFUNDENEN Zustand und stelle GENAU DEN wieder her.
    Ein geratener Leerwert ("war bestimmt aus") ist keine Wiederherstellung,
    sondern eine Aenderung.

Fuer Freigabefelder war das im Projekt laengst Praxis (`vor = status.get(...)`),
fuer den Skill-Schalter nicht – dieselbe Datei tat beides nebeneinander richtig
und falsch.

Geprueft wird die EIGENSCHAFT: jedes Skript, das einen Skill einschaltet, muss
seinen vorherigen Zustand LESEN. Eine gepflegte Dateiliste gaebe es nicht – der
Waechter durchsucht `tests/` selbst, damit auch ein kuenftiges Skript auffaellt.

    python3 tests/test_messung_zustand.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ok = fail = 0


def check(text, bedingung, zusatz=""):
    global ok, fail
    if bedingung:
        ok += 1
        print("  \033[32m✓\033[0m %s" % text)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (text, ("  → " + str(zusatz)) if zusatz else ""))


def ohne_kommentare(quelle: str) -> str:
    """Zeilenkommentare weg – sonst liest der Waechter seine eigene Begruendung.

    Schlicht und mit Positivkontrolle unten: eine Zustandsmaschine ueber
    Zeichenketten stolpert ueber Anfuehrungszeichen im Text (im Projekt bezahlt).
    """
    return "\n".join(z for z in quelle.split("\n") if not z.lstrip().startswith("#"))


print("\033[1m1. Wer einen Skill EINSCHALTET, muss den Vorzustand lesen\033[0m")

# `enable` ohne vorheriges Lesen des Zustands ist der Fehler: am Ende wird dann
# zwangslaeufig geraten, was vorher galt.
EIN = re.compile(r"/api/skills/([\w.-]+)/enable|save_skill_state\(")
# Woran man erkennt, dass der Vorzustand gelesen wurde. Die Namen sind bewusst
# breit: es geht um die EIGENSCHAFT "es wurde nachgesehen", nicht um eine
# bestimmte Schreibweise.
LIEST = re.compile(
    r"get_skill_states\(\)|/api/skills\b(?![\w/]*/(en|dis)able)|"
    r"\bvorher\b|\bvorgefunden|\bwar_aktiv\b|\bVORHER\b"
)

dateien = sorted(p for p in (ROOT / "tests").glob("*.py")
                 if p.name != Path(__file__).name)
geprueft = betroffen = 0
for p in dateien:
    quelle = ohne_kommentare(p.read_text(encoding="utf-8", errors="replace"))
    if not EIN.search(quelle):
        continue
    betroffen += 1
    geprueft += 1
    check("%s liest den Skill-Zustand, bevor es ihn aendert" % p.name,
          bool(LIEST.search(quelle)),
          "schaltet ein, ohne nachzusehen was vorher galt")

check("es gibt ueberhaupt Skripte dieser Art (Positivkontrolle)", betroffen > 0,
      "kein Skript gefunden – der Waechter prueft dann nichts")


print("\n\033[1m2. Kein hartes 'disable' zum Aufraeumen\033[0m")

# Der eigentliche Schaden: `disable` im Aufraeumzweig BEHAUPTET, der Skill sei
# vorher aus gewesen. Erlaubt ist es nur, wenn im selben Skript auch der Fall
# "war an" behandelt wird – also ein bedingtes Wiederherstellen.
HART = re.compile(r"/api/skills/([\w.-]+)/disable")
BEDINGT = re.compile(
    r"if\s+.*(war_aktiv|vorher|VORHER|war_an)|"
    r"(war_aktiv|vorher|VORHER|war_an)\s*(else|and|or|\?)|"
    r"'enabled':\s*(war_aktiv|vorher|VORHER)|"
    r'"enabled":\s*(war_aktiv|vorher|VORHER)'
)
for p in dateien:
    quelle = ohne_kommentare(p.read_text(encoding="utf-8", errors="replace"))
    m = HART.search(quelle)
    if not m:
        continue
    geprueft += 1
    check("%s schaltet nicht blind ab (Skill %r)" % (p.name, m.group(1)),
          bool(BEDINGT.search(quelle)),
          "ruft disable im Aufraeumen, ohne den Vorzustand zu unterscheiden – "
          "genau der gemeldete Fehler")


print("\n\033[1m3. Der Kommentar-Filter greift wirklich\033[0m")
probe = "# geheim\ncode = 1\n    # auch weg\nx = 2\n"
gefiltert = ohne_kommentare(probe)
check("Kommentarzeilen sind weg", "geheim" not in gefiltert and "auch weg" not in gefiltert)
check("Code bleibt stehen", "code = 1" in gefiltert and "x = 2" in gefiltert)


print("\n\033[1m4. Die Regel steht im Projektgedaechtnis\033[0m")
# Ohne den Eintrag wiederholt sich der Fehler beim naechsten Bereich – die
# Skripte sind Wegwerfcode, die Lehre ist es nicht.
# ⚠ NUR IM ARBEITSBAUM. CLAUDE.md steht in `.gitignore` und wird nicht
# deployt – auf einem Server liegt hoechstens eine alte Kopie (auf DEV eine vom
# 24.08.), und der Waechter meldete dort einen Fehler, den es nicht gibt.
# Erkannt an der Zeit: ist die Datei AELTER als dieser Waechter, gehoert sie
# nicht zu diesem Stand.
claude = ROOT / "CLAUDE.md"
selbst = Path(__file__)
if claude.is_file() and claude.stat().st_mtime >= selbst.stat().st_mtime - 86400:
    txt = claude.read_text(encoding="utf-8", errors="replace")
    check("CLAUDE.md nennt die Regel zum VORGEFUNDENEN Zustand",
          "vorgefundenen Zustand" in txt or "VORGEFUNDENEN Zustand" in txt)
else:
    check("Projektgedaechtnis: uebersprungen (nicht der Stand dieses Waechters)", True)


print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
