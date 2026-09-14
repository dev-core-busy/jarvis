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

import ast
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


# ── Gemeinsame Messfunktionen fuer Abschnitt 1 und 2 ────────────────────────
# ⚠ EIN ECHTER AUFRUF, KEIN VORKOMMEN. Abschnitt 2b traegt diese Lehre seit
# seinem Bau, Abschnitt 2 seit dem 2026-09-14 – Abschnitt 1 hat sie bis dahin
# NICHT angewandt, und das hat genau den Fehlalarm erzeugt, gegen den 2b gebaut
# wurde: `def save_skill_state(self, ...)` einer ATTRAPPE ist keine
# Zustandsaenderung.
#
# GEMESSEN (2026-09-14): der Waechter beurteilte drei voellig hermetische Tests
# – test_license.py, test_onenote_import.py, test_rag_ordner.py. Alle drei
# ersetzen `backend.config` in sys.modules durch eine Attrappe und fassen
# keinen echten Zustand an (ueber einen Audit-Hook nachgemessen: 0
# Schreibzugriffe ausserhalb des /tmp-Sandkastens). Ihr Urteil hing an
# ZUFALLSVOKABULAR: test_onenote_import.py bestand, weil dort eine ZEILENZAHL
# `vorher` heisst; test_rag_ordner.py fiel durch, weil seine Attrappe
# `get_skill_states(self)` schreibt statt `get_skill_states()`.
_ZUSTAND_WORT = ("skill", "enabled")
EIN_HTTP = re.compile(r"/api/skills/[\w.-]+/enable")


def _texte(knoten):
    """Alle Namen und Zeichenketten unterhalb eines AST-Knotens."""
    raus = []
    for k in ast.walk(knoten):
        if isinstance(k, ast.Attribute):
            raus.append(k.attr)
        elif isinstance(k, ast.Name):
            raus.append(k.id)
        elif isinstance(k, ast.Constant) and isinstance(k.value, str):
            raus.append(k.value)
    return raus


def _zustandsnamen(baum):
    """Variablen, denen ein aus dem Skill-Zustand gelesener Wert zugewiesen wird."""
    raus = set()
    for k in ast.walk(baum):
        if not isinstance(k, (ast.Assign, ast.AnnAssign)):
            continue
        wert = k.value
        if wert is None:
            continue
        texte = " ".join(_texte(wert)).lower()
        if not any(w in texte for w in _ZUSTAND_WORT):
            continue
        ziele = k.targets if isinstance(k, ast.Assign) else [k.target]
        for z in ziele:
            for t in ast.walk(z):
                if isinstance(t, ast.Name):
                    raus.add(t.id)
    return raus


def _ersetzt_config(baum):
    """Ersetzt das Skript `backend.config` in sys.modules durch eine Attrappe?

    Dann kann ein `save_skill_state` dort keinen echten Zustand hinterlassen –
    der Aufruf landet in der Attrappe. Ein echter HTTP-Aufruf bleibt davon
    ausdruecklich UNBERUEHRT: der geht am Prozess vorbei an den Dienst.
    """
    for k in ast.walk(baum):
        if isinstance(k, ast.Assign):
            for z in k.targets:
                if (isinstance(z, ast.Subscript)
                        and isinstance(z.slice, ast.Constant)
                        and z.slice.value == "backend.config"):
                    return True
        if isinstance(k, ast.Call) and getattr(k.func, "attr", "") == "setdefault":
            if any(isinstance(a, ast.Constant) and a.value == "backend.config"
                   for a in k.args):
                return True
    return False


def _pfad_treffer(knoten, muster):
    """Zeichenketten-Argumente eines Aufrufs, die wie ein URL-PFAD aussehen.

    ⚠ KEINE CODEZEILE – und das ist beim Bau dieser Regel sofort zugeschnappt:
    der eigene Gegenproben-Harness (`gegen_messung_zustand.py`) traegt ganze
    Skripte als Zeichenkette, und darin steht `/api/skills/x/enable` ebenfalls,
    ohne dass je etwas geschaltet wird. Genau davor warnt Abschnitt 2b. Ein
    echtes Pfad-Literal enthaelt keinen Zeilenumbruch.
    """
    for teil in list(knoten.args) + [w.value for w in knoten.keywords]:
        for t in ast.walk(teil):
            if (isinstance(t, ast.Constant) and isinstance(t.value, str)
                    and "\n" not in t.value and muster.search(t.value)):
                return True
    return False


def schaltet_ein(quelle):
    """(aendert_echten_zustand, arbeitet_mit_attrappe).

    Ein `def` ist kein Aufruf – genau daran ist die alte Textregel gescheitert.
    """
    try:
        baum = ast.parse(quelle)
    except SyntaxError:
        return (False, False)
    attrappe = _ersetzt_config(baum)
    echt = False
    for k in ast.walk(baum):
        if not isinstance(k, ast.Call):
            continue
        # HTTP: der Pfad ist meist zusammengesetzt (BASIS + "/api/skills/…"),
        # deshalb den ganzen Aufruf-Teilbaum absuchen, nicht nur direkte Argumente.
        if _pfad_treffer(k, EIN_HTTP):
            return (True, attrappe)
        f = k.func
        name = f.attr if isinstance(f, ast.Attribute) else \
            (f.id if isinstance(f, ast.Name) else "")
        if name in ("enable_skill", "save_skill_state") and not attrappe:
            echt = True
    return (echt, attrappe)


print("\033[1m1. Wer einen Skill EINSCHALTET, muss den Vorzustand lesen\033[0m")

# Positiv- UND Negativkontrolle der Messfunktion selbst – ohne sie waere nicht
# zu unterscheiden, ob die Regel greift oder ob sie nur nichts findet.
_E_HTTP = "S.post(BASIS + '/api/skills/x/enable', timeout=90)\n"
_E_PY = "config.save_skill_state('x', {'enabled': True})\n"
_E_ATTRAPPE = ("import sys, types\n_m = types.ModuleType('backend.config')\n"
               "sys.modules['backend.config'] = _m\n"
               "class F:\n"
               "    def get_skill_states(self):\n        return {}\n"
               "    def save_skill_state(self, n, s):\n        pass\n")
_E_ATTRAPPE_HTTP = _E_ATTRAPPE + "S.post(B + '/api/skills/x/enable')\n"
check("die Messfunktion erkennt ein Einschalten per HTTP", schaltet_ein(_E_HTTP)[0])
check("sie erkennt einen echten save_skill_state-Aufruf", schaltet_ein(_E_PY)[0])
check("⚠ eine Attrappen-METHODE zaehlt NICHT als Zustandsaenderung",
      schaltet_ein(_E_ATTRAPPE) == (False, True), str(schaltet_ein(_E_ATTRAPPE)))
check("ein HTTP-Aufruf zaehlt auch dann, wenn eine Attrappe danebensteht",
      schaltet_ein(_E_ATTRAPPE_HTTP)[0])

dateien = sorted(p for p in (ROOT / "tests").glob("*.py")
                 if p.name != Path(__file__).name)
# Nur zum BERICHTEN, nicht zum Urteilen: sieht die Datei ueberhaupt nach
# Skill-Zustand aus? Eine ausgeblendete Menge, die niemand nennt, ist genau die
# Falschaussage, die dieser Waechter verhindern soll (Register: cron_list).
SIEHT_AUS = re.compile(r"/api/skills/[\w.-]+/enable|save_skill_state|enable_skill")
geprueft = betroffen = 0
hermetisch = []
for p in dateien:
    quelle = ohne_kommentare(p.read_text(encoding="utf-8", errors="replace"))
    echt, attrappe = schaltet_ein(quelle)
    if not echt:
        if attrappe and SIEHT_AUS.search(quelle):
            hermetisch.append(p.name)
        continue
    betroffen += 1
    geprueft += 1
    try:
        namen = _zustandsnamen(ast.parse(quelle))
    except SyntaxError:
        namen = set()
    check("%s liest den Skill-Zustand, bevor es ihn aendert" % p.name,
          bool(namen),
          "schaltet ein, ohne nachzusehen was vorher galt")

if hermetisch:
    print("  \033[2m(%d Skript(e) arbeiten nur mit Attrappen und hinterlassen "
          "keinen echten Zustand: %s)\033[0m" % (len(hermetisch), ", ".join(hermetisch)))

check("es gibt ueberhaupt Skripte dieser Art (Positivkontrolle)", betroffen > 0,
      "kein Skript gefunden – der Waechter prueft dann nichts")


print("\n\033[1m2. Kein hartes 'disable' zum Aufraeumen\033[0m")

# Der eigentliche Schaden: `disable` im Aufraeumzweig BEHAUPTET, der Skill sei
# vorher aus gewesen. Erlaubt ist es nur, wenn im selben Skript auch der Fall
# "war an" behandelt wird – also ein bedingtes Wiederherstellen.
# ⚠ GEMESSEN WIRD EIN AUFRUF, NICHT EIN VORKOMMEN (Register): `disable_skill`
# steht in `test_license.py` als METHODE EINER ATTRAPPE – ein Textmuster meldete
# den Test, obwohl dort gar kein Skill geschaltet wird. Die HTTP-Form ist immer
# ein Zeichenketten-Argument, die Python-Form muss ein `ast.Call` sein.
HART_HTTP = re.compile(r"/api/skills/([\w.-]+)/disable")


def schaltet_ab(quelle):
    # ⚠ FRUEHER STAND HIER EINE TEXTSUCHE ueber die ganze Quelle. Sie meldete
    # jeden Gegenproben-Harness, der den Pfad als Sabotage-Anker in einer
    # Zeichenkette traegt – dieselbe Falle wie in Abschnitt 1. Gemessen wird
    # jetzt ein AUFRUF mit einem echten Pfad-Literal.
    try:
        baum = ast.parse(quelle)
    except SyntaxError:
        return False
    for k in ast.walk(baum):
        if isinstance(k, ast.Call) and _ist_abschalten(k):
            return True
    return False

# ⚠ HIER STAND EINE GEPFLEGTE NAMENSLISTE (`war_aktiv|vorher|VORHER|war_an`) –
# also genau die Grundlage, vor der das Register warnt: sie ist an dem Tag
# unvollstaendig, an dem jemand seine Variable anders nennt. Sie hat am
# 2026-09-14 `live_feedback_dev.py` gemeldet, obwohl dessen Aufraeumen mit
# `VOR_SKILL` drei Faelle sauber unterscheidet – ein Fehlalarm, und schlimmer:
# ein Skript, das seine Variable `x` nennt und WIRKLICH blind abschaltet, waere
# durchgerutscht.
#
# GEMESSEN WIRD JETZT DIE EIGENSCHAFT: es gibt eine VERZWEIGUNG, deren Zweige
# in verschiedene Richtungen wiederherstellen – einer schaltet EIN, ein anderer
# schaltet AB oder ENTFERNT den Eintrag. Das ist „fallabhaengig wiederhergestellt"
# und haengt an keinem Namen. Ein blindes `disable` im finally hat diese
# Verzweigung per Definition nicht.
# ⚠ ZWEITE KORREKTUR AM SELBEN TAG, und sie ist die lehrreichere: meine erste
# Fassung verlangte eine if-Kette mit einem sichtbaren EINSCHALT-Zweig. Damit
# fielen die drei VEMAS-Proben durch, die es voellig richtig machen – war der
# Skill vorher AN, ist die Wiederherstellung ein **Nichtstun**, und einen Zweig
# dafuer gibt es zu Recht nicht.
#
# DIE EIGENSCHAFT, auf die es ankommt: das Abschalten steht in einer
# VERZWEIGUNG, deren Bedingung einen Wert benutzt, der aus dem Skill-Zustand
# GELESEN wurde. Ein blindes `disable` im finally hat keine solche Bedingung.
# Namensunabhaengig – die alte Liste (`war_aktiv|vorher|…`) war genau die
# Grundlage, vor der das Register warnt.
# `_ZUSTAND_WORT`, `_texte` und `_zustandsnamen` stehen jetzt oben als
# GEMEINSAME Messfunktionen – Abschnitt 1 und 2 beurteilen dieselbe
# Eigenschaft, und zwei Fassungen davon waeren beim naechsten Feinschliff
# auseinandergelaufen.


def _ist_abschalten(knoten):
    if not isinstance(knoten, ast.Call):
        return False
    f = knoten.func
    name = f.attr if isinstance(f, ast.Attribute) else \
        (f.id if isinstance(f, ast.Name) else "")
    if name == "disable_skill":
        return True
    return _pfad_treffer(knoten, HART_HTTP)


def _ist_wiederherstellen(knoten):
    """Ein Aufruf, der den Skill-Zustand setzt oder den Eintrag entfernt."""
    if _ist_abschalten(knoten):
        return True
    if not isinstance(knoten, ast.Call):
        return False
    f = knoten.func
    name = f.attr if isinstance(f, ast.Attribute) else \
        (f.id if isinstance(f, ast.Name) else "")
    if name in ("enable_skill", "remove_skill_state"):
        return True
    return _pfad_treffer(knoten, EIN_HTTP)


def stellt_fallabhaengig_her(quelle):
    """True, wenn eine Verzweigung ueber den GELESENEN Vorzustand schaltet.

    ⚠ WAS DIESE REGEL NICHT KANN, und das gehoert benannt: sie unterscheidet
    ein Abschalten als MESSSCHRITT („Skill aus -> Kachel weg") nicht von einem
    Abschalten im AUFRAEUMEN. Ein Skript darf zwischendurch schalten, solange es
    am Ende fallabhaengig wiederherstellt – und genau das wird gemessen. Was
    ausgeschlossen wird, ist der gemeldete Fall: ein Skript, das den Vorzustand
    NIRGENDS in eine Schaltentscheidung einfliessen laesst.
    """
    try:
        baum = ast.parse(quelle)
    except SyntaxError:
        return False
    namen = _zustandsnamen(baum)
    if not namen:
        return False
    for k in ast.walk(baum):
        if not isinstance(k, (ast.If, ast.IfExp)):
            continue
        if not (set(_texte(k.test)) & namen):
            continue
        zweige = [k.body, k.orelse] if isinstance(k, ast.If) else [[k.body], [k.orelse]]
        for zweig in zweige:
            for st in zweig:
                for t in ast.walk(st):
                    if _ist_wiederherstellen(t):
                        return True
    return False


# Positiv- UND Negativkontrolle der Messfunktion selbst: ohne sie waere nicht
# zu unterscheiden, ob die Regel greift oder ob sie nur nichts findet.
_GUT = ("vorgefunden = config.get_skill_states().get('x', {}).get('enabled')\n"
        "if vorgefunden is True:\n    sm.enable_skill('x')\n"
        "elif vorgefunden is False:\n    sm.disable_skill('x')\n"
        "else:\n    config.remove_skill_state('x')\n")
_GUT2 = ("war_an = any(y.get('enabled') for y in hole('/api/skills'))\n"
         "if not war_an:\n    ruf('/api/skills/x/disable')\n")
_SCHLECHT = ("war_an = any(y.get('enabled') for y in hole('/api/skills'))\n"
             "try:\n    pass\nfinally:\n    ruf('/api/skills/x/disable')\n")
check("die Messfunktion erkennt eine if/elif-Wiederherstellung",
      stellt_fallabhaengig_her(_GUT))
check("sie erkennt auch den Fall 'war an -> nichts tun'",
      stellt_fallabhaengig_her(_GUT2))
check("die Messfunktion erkennt ein blindes Abschalten (Gegenkontrolle)",
      not stellt_fallabhaengig_her(_SCHLECHT))
check("ein gelesener Vorzustand OHNE Schaltentscheidung genuegt nicht",
      not stellt_fallabhaengig_her(
          "war_an = hole('/api/skills')[0].get('enabled')\n"
          "if war_an:\n    print('war an')\n"
          "ruf('/api/skills/x/disable')\n"))
check("eine Attrappen-METHODE zaehlt nicht als Abschalten",
      not schaltet_ab("class X:\n    def disable_skill(self, n):\n        pass\n"))
check("ein echter Aufruf zaehlt sehr wohl (Gegenkontrolle)",
      schaltet_ab("sm.disable_skill('x')\n"))

for p in dateien:
    quelle = ohne_kommentare(p.read_text(encoding="utf-8", errors="replace"))
    if not schaltet_ab(quelle):
        continue
    geprueft += 1
    check("%s schaltet nicht blind ab" % p.name,
          stellt_fallabhaengig_her(quelle),
          "das Abschalten haengt an keiner Bedingung ueber den gelesenen "
          "Vorzustand – genau der gemeldete Fehler")


print("\n\033[1m2b. Eine geaenderte REIHENFOLGE gehoert zurueckgestellt\033[0m")

# ⚠ NEUE ZUSTANDSART, am 2026-09-11 bezahlt. Der Waechter kannte nur
# Skill-Schalter – meine Live-Probe zur Fragen-Reihenfolge hat die Folge der
# sechs echten Fragen umgedreht und am Ende nur die MENGE zurueckgeprueft
# (`sorted(...) == sorted(...)`). Eine Messung, die ihren Gegenstand verstellt
# und dann etwas ANDERES zurueckprueft, ist keine Wiederherstellung.
#
# Geprueft wird die EIGENSCHAFT, nicht ein Wortlaut: wer die Reihenfolge
# schreibt, muss sie (a) vorher merken, (b) am Ende wieder senden und (c) auf
# IDENTITAET pruefen – `sorted()` allein genuegt ausdruecklich nicht.
SORT_MERKT = re.compile(r"\bvorher\b|\bvorgefunden|\bVORHER\b|\bfolge_vor\b")
SORT_IDENT = re.compile(r"==\s*vorher\b|vorher\s*==|nach\s*==\s*vorher")
# ⚠ DRITTE HAELFTE, von einer Gegenprobe gefunden: "merkt" und "prueft auf
# Identitaet" bleiben wahr, wenn nur das ZURUECKSTELLEN fehlt – der Waechter
# war damit fuer genau den Fall blind, den es zu verhindern gilt.
SORT_ZURUECK = re.compile(r'"ids":\s*vorher\b|ids=vorher\b|sortieren\([^)]*vorher')


def schreibt_reihenfolge(quelle: str) -> bool:
    """⚠ EIN ECHTER AUFRUF, KEIN VORKOMMEN. Ein Gegenproben-Harness traegt
    `amf.sortieren(...)` und den Endpunkt-Pfad als SABOTAGE-ANKER in
    Zeichenketten – er fasst keine Daten an und stellt sich ueber seine
    Datei-Sicherung wieder her. Wer das Muster im Text sucht, meldet ihn und
    baut sich einen Fehlalarm (beim Bau dieser Regel gemessen)."""
    try:
        baum = ast.parse(quelle)
    except SyntaxError:
        return False
    for k in ast.walk(baum):
        if not isinstance(k, ast.Call):
            continue
        f = k.func
        if isinstance(f, ast.Attribute) and f.attr == "sortieren":
            return True                      # echter Aufruf der Sortierfunktion
        # Ein HTTP-Aufruf: EIN Argument ist genau der Pfad (keine Codezeile),
        # ein anderes nennt POST.
        lits = [a.value for a in k.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        pfad = any(x.strip().startswith("/api/") and "\n" not in x
                   and x.rstrip("/").endswith("reihenfolge") for x in lits)
        if pfad and any(x == "POST" for x in lits):
            return True
    return False


betroffen_s = 0
for p in dateien:
    quelle = ohne_kommentare(p.read_text(encoding="utf-8", errors="replace"))
    if not schreibt_reihenfolge(quelle):
        continue
    betroffen_s += 1
    geprueft += 2
    check("%s merkt die vorgefundene Reihenfolge" % p.name,
          bool(SORT_MERKT.search(quelle)),
          "aendert die Folge, ohne nachzusehen welche vorher galt")
    check("%s prueft am Ende auf IDENTITAET, nicht nur auf die Menge" % p.name,
          bool(SORT_IDENT.search(quelle)),
          "sorted(...)==sorted(...) laesst eine verdrehte Folge durch – "
          "genau der Fehler vom 2026-09-11")
    geprueft += 1
    check("%s stellt die vorgefundene Reihenfolge wirklich zurueck" % p.name,
          bool(SORT_ZURUECK.search(quelle)),
          "merkt sie und prueft sie, sendet sie aber nie zurueck")

check("es gibt ueberhaupt Skripte dieser Art (Positivkontrolle)",
      betroffen_s > 0,
      "kein Skript schreibt eine Reihenfolge – der Abschnitt prueft dann nichts")


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
