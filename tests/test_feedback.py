#!/usr/bin/env python3
"""Waechter fuer den Feedback-Skill (backend/feedback.py + Endpunkte).

Die echten Funktionen werden AUSGEFUEHRT – eine Quelltext-Pruefung koennte
Fragen wie „wird eine unbekannte Spalte wirklich verworfen?" gar nicht
beantworten. Die Endpunkt-Zusagen stehen als REGEL ueber den AST, damit auch
eine KUENFTIGE Route auffaellt, ohne dass jemand eine Liste pflegt.

⚠ SANDKASTEN MIT EXIT 2: dieser Lauf darf NIEMALS in den echten Bestand
schreiben (`data/feedback_*`). Ein Test, der die Formulare des Betreibers
ueberschreibt, ist teurer als der Fehler, den er sucht.
"""

import ast
import json
import os
import shutil
import sys
import tempfile
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(beschreibung, bedingung, detail=""):
    """⚠ ARGUMENTE NICHT VERTAUSCHEN – in `test_jira_vorlagen.py` waren einmal
    ALLE 57 Aufrufe vertauscht, und weil eine nicht-leere Zeichenkette wahr ist,
    meldete der Lauf „57 OK, 0 FAIL", ohne eine einzige Bedingung ausgewertet zu
    haben. Deshalb bricht ein vertauschter Aufruf hier hart ab."""
    global _ok, _fail
    if not isinstance(beschreibung, str) or isinstance(bedingung, str):
        print("ABBRUCH: check(beschreibung, bedingung) vertauscht: %r" % (beschreibung,))
        sys.exit(2)
    if bedingung:
        _ok += 1
        print("  \033[32m✓\033[0m %s" % beschreibung)
    else:
        _fail += 1
        print("  \033[31m✗\033[0m %s%s" % (beschreibung, (" – " + detail) if detail else ""))


def sicher(fn, *a, **kw):
    """Aufruf, der nicht wirft. Nie ungeprueft dereferenzieren: eine Pruefung,
    die WIRFT statt fehlzuschlagen, bricht den Lauf ohne Bilanzzeile ab – und
    das ist von „nicht gelaufen" nicht zu unterscheiden (Register)."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return ("__FEHLER__", e)


def fehler(x):
    return isinstance(x, tuple) and len(x) == 2 and x[0] == "__FEHLER__"


def zelle(abgabe, i, sid):
    """Ein Zellwert aus einer Abgabe – nie ungeprueft dereferenzieren.

    ⚠ `a["zeilen"][1][sid]` wirft, sobald eine Gegenprobe die Abgabe scheitern
    laesst (dann steht dort der Ersatz aus `muss`) – der Lauf endet OHNE
    Bilanzzeile und ist von „nicht gelaufen" nicht zu unterscheiden."""
    try:
        return abgabe["zeilen"][i][sid]
    except Exception:  # noqa: BLE001
        return None


def muss(was, fn, *a, **kw):
    """Ein Aufruf, der GELINGEN muss. Scheitert er, wird das als FAIL gezaehlt
    und ein Ersatz-Datensatz zurueckgegeben – der Lauf geht weiter.

    ⚠ OHNE DAS BRICHT DER WAECHTER AB, sobald eine Gegenprobe eine fruehere
    Zusage verletzt: kein FAIL, KEINE BILANZZEILE, und das ist von „nicht
    gelaufen" nicht zu unterscheiden (Register, hier am 2026-09-14 gemessen)."""
    r = sicher(fn, *a, **kw)
    if fehler(r):
        check(was, False, "wirft: %s" % r[1])
        return {"id": "?", "spalten": [], "zeilen": [], "benutzer": "",
                "formular_titel": "", "titel": ""}
    return r


# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m1. Sandkasten\033[0m")
# ═══════════════════════════════════════════════════════════════════════════
from backend import feedback as fb  # noqa: E402

SAND = pathlib.Path(tempfile.mkdtemp(prefix="fb-test-"))
_ECHT_FORM = fb._pfad_formulare()
_ECHT_ABG = fb._pfad_abgaben()
fb._pfad_formulare = lambda: SAND / "formulare.json"
fb._pfad_abgaben = lambda: SAND / "abgaben.jsonl"

for name, p in (("Formulare", fb._pfad_formulare()), ("Abgaben", fb._pfad_abgaben())):
    if not str(p).startswith(str(SAND)):
        print("ABBRUCH: %s zeigt aus dem Sandkasten heraus: %s" % (name, p))
        sys.exit(2)
print("  \033[32m✓\033[0m beide Pfade liegen im Wegwerf-Verzeichnis")
_ok += 1
# Positivkontrolle: der ECHTE Bestand wird in diesem Lauf nicht angefasst.
_echt_vorher = [(p, p.stat().st_mtime if p.exists() else None)
                for p in (_ECHT_FORM, _ECHT_ABG)]


# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m2. Spalten: Typ, Ueberschrift, Kennung\033[0m")
# ═══════════════════════════════════════════════════════════════════════════
f = muss("Formular anlegen gelingt", fb.formular_speichern, "", "Bewertung",
         "Bitte ausfuellen", [
    {"name": "Modul", "typ": "text"},
    {"name": "Note", "typ": "sterne"},
])
check("Formular angelegt", not fehler(f) and len(f["spalten"]) == 2)
# Robust gegen einen fehlgeschlagenen Anlege-Aufruf (siehe `muss`): ohne
# Ersatzwerte wuerde jeder Folgezugriff werfen und die Bilanz verschlucken.
SP = {s["name"]: s["id"] for s in f.get("spalten", [])}
SP.setdefault("Modul", "?m")
SP.setdefault("Note", "?n")

r = sicher(fb.formular_speichern, "", "X", "", [{"name": "A", "typ": "zahl"}])
check("unbekannter Spaltentyp wird ABGEWIESEN", fehler(r))
check("und die Meldung nennt die moeglichen Typen",
      fehler(r) and "text" in str(r[1]) and "sterne" in str(r[1]))

r = sicher(fb.formular_speichern, "", "X", "", [{"name": "  ", "typ": "text"}])
check("Spalte ohne Ueberschrift wird abgewiesen", fehler(r))

r = sicher(fb.formular_speichern, "", "X", "", [])
check("Formular ohne Spalte wird abgewiesen", fehler(r))

r = sicher(fb.formular_speichern, "", "", "", [{"name": "A", "typ": "text"}])
check("Formular ohne Titel wird abgewiesen", fehler(r))

r = sicher(fb.formular_speichern, "", "X", "",
           [{"name": "S%d" % i, "typ": "text"} for i in range(fb.MAX_SPALTEN + 1)])
check("mehr als MAX_SPALTEN wird abgewiesen", fehler(r))

# ⚠ DIE WICHTIGSTE ZUSAGE DIESES ABSCHNITTS: die Kennung ueberlebt das
# Bearbeiten. Sonst ist JEDE vorhandene Abgabe unlesbar.
f2 = muss("Bearbeiten gelingt", fb.formular_speichern, f["id"], "Bewertung neu", "", [
    {"id": SP["Modul"], "name": "Modul (neu)", "typ": "text"},
    {"id": SP["Note"], "name": "Note", "typ": "sterne"},
])
check("⚠ die Spalten-Kennung bleibt beim Bearbeiten ERHALTEN",
      [s["id"] for s in (f2.get("spalten") or [])] == [SP["Modul"], SP["Note"]],
      "sonst sind alle bisherigen Abgaben nicht mehr zuzuordnen")
check("der Name laesst sich dabei aendern",
      (f2.get("spalten") or [{}])[0].get("name") == "Modul (neu)")

# Doppelte Kennung aus dem Request: neu vergeben statt abweisen.
f3 = muss("Doppel-Formular gelingt", fb.formular_speichern, "", "Doppelt", "", [
    {"id": "aaaa", "name": "A", "typ": "text"},
    {"id": "aaaa", "name": "B", "typ": "text"},
])
ids3 = [s["id"] for s in (f3.get("spalten") or [])]
check("eine doppelte Kennung wird neu vergeben, nicht abgewiesen",
      len(set(ids3)) == 2)
fb.formular_loeschen(f3["id"])


# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m3. Abgabe: Pruefung der Zellen\033[0m")
# ═══════════════════════════════════════════════════════════════════════════
a = muss("die Abgabe gelingt", fb.abgabe_speichern, "NEXUS\\Max.Muster", f["id"], [
    {SP["Modul"]: "Lager", SP["Note"]: 4},
    {SP["Modul"]: "", SP["Note"]: 0},                 # leer  -> faellt heraus
    {SP["Modul"]: "Kasse", SP["Note"]: "99"},         # Sterne begrenzt
    {SP["Modul"]: "Fremd", "UNBEKANNT": "boese"},     # fremde Spalte
])
check("leere Zeilen fallen heraus", len(a.get("zeilen") or []) == 3)
check("Sterne werden auf 0..5 begrenzt",
      zelle(a, 1, SP["Note"]) == fb.STERNE_MAX)
check("⚠ eine UNBEKANNTE Spalte wird verworfen",
      not any("UNBEKANNT" in z for z in (a.get("zeilen") or [])),
      "sonst schreibt ein Aufrufer beliebige Felder in die Ablage")
check("der Benutzer wird normiert (Domaene/UPN weg)",
      a.get("benutzer") == "max.muster")

# ⚠ DER SPALTEN-SNAPSHOT ist die Voraussetzung dafuer, dass eine Abgabe nach
# einer Aenderung noch richtig BESCHRIFTET ist.
check("⚠ die Abgabe speichert die Spalten MIT",
      [s["id"] for s in (a.get("spalten") or [])] == [SP["Modul"], SP["Note"]],
      "sonst stehen echte Daten unter einer Ueberschrift, die damals nicht galt")
check("und den Formulartitel",
      a.get("formular_titel") == "Bewertung neu")

r = sicher(fb.abgabe_speichern, "u", f["id"], [{SP["Modul"]: "", SP["Note"]: 0}])
check("eine Abgabe ohne gefuellte Zeile wird abgewiesen", fehler(r))

r = sicher(fb.abgabe_speichern, "u", "gibtsnicht", [{SP["Modul"]: "x"}])
check("unbekanntes Formular wird abgewiesen", fehler(r))

r = sicher(fb.abgabe_speichern, "u", f["id"],
           [{SP["Modul"]: "x"}] * (fb.MAX_ZEILEN + 1))
check("mehr als MAX_ZEILEN wird abgewiesen", fehler(r))

r = sicher(fb.abgabe_speichern, "u", f["id"], "keine liste")
check("`zeilen` als Zeichenkette wird abgewiesen", fehler(r),
      "ueber einen String zu iterieren ist immer erlaubt und nie gemeint")

lang = "x" * (fb.ZELLE_MAX + 500)
a2 = muss("die Kapp-Abgabe gelingt", fb.abgabe_speichern, "u", f["id"],
          [{SP["Modul"]: lang, SP["Note"]: 3}])
check("ein zu langer Zellwert wird gekappt, nicht abgewiesen",
      len(zelle(a2, 0, SP["Modul"]) or "") == fb.ZELLE_MAX)

# Abgeschaltetes Formular nimmt nichts an.
fb.formular_speichern(f["id"], "Bewertung neu", "",
                      [{"id": SP["Modul"], "name": "Modul", "typ": "text"},
                       {"id": SP["Note"], "name": "Note", "typ": "sterne"}],
                      aktiv=False)
r = sicher(fb.abgabe_speichern, "u", f["id"], [{SP["Modul"]: "x"}])
check("ein ABGESCHALTETES Formular nimmt keine Abgabe an", fehler(r))
check("und es erscheint nicht in der Benutzer-Liste",
      not any(x["id"] == f["id"] for x in fb.formulare(nur_aktive=True)))
check("in der Admin-Liste aber schon",
      any(x["id"] == f["id"] for x in fb.formulare(nur_aktive=False)))
fb.formular_speichern(f["id"], "Bewertung neu", "",
                      [{"id": SP["Modul"], "name": "Modul", "typ": "text"},
                       {"id": SP["Note"], "name": "Note", "typ": "sterne"}],
                      aktiv=True)

# `aktiv` fehlt (Altbestand) -> gilt als AKTIV, nicht als abgeschaltet.
roh = json.loads(fb._pfad_formulare().read_text(encoding="utf-8"))
for e in roh["formulare"]:
    e.pop("aktiv", None)
fb._pfad_formulare().write_text(json.dumps(roh), encoding="utf-8")
check("⚠ ein Altbestand OHNE `aktiv` gilt als aktiv",
      any(x["id"] == f["id"] for x in fb.formulare(nur_aktive=True)),
      "`is not False` statt Falsyness – sonst waeren nach einem Update alle weg")


# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m4. Sichtbarkeit und Loeschen\033[0m")
# ═══════════════════════════════════════════════════════════════════════════
eigene = fb.abgaben(fid=f["id"], user="max.muster", nur_eigene=True)
alle = fb.abgaben(fid=f["id"])
check("`nur_eigene` filtert auf den Benutzer",
      len(eigene) >= 1 and all(x["benutzer"] == "max.muster" for x in eigene))
check("und ohne die Schranke kommen alle", len(alle) > len(eigene))
check("Domaenen-Schreibweise findet die eigene Abgabe wieder",
      len(fb.abgaben(fid=f["id"], user="NEXUS\\MAX.MUSTER", nur_eigene=True)) == len(eigene))
check("neueste zuerst",
      len(alle) < 2 or alle[0]["zeit"] >= alle[-1]["zeit"])

vorher = len(fb.abgaben(fid=f["id"]))
check("eine unbekannte Abgabe zu loeschen meldet False",
      fb.abgabe_loeschen("gibtsnicht") is False)
# ⚠ `alle[0]` wirft bei leerer Liste – und der Lauf endete dann OHNE Bilanz
# (dritte Stelle derselben Falle in diesem Waechter, Register).
check("es gibt ueberhaupt eine Abgabe zum Loeschen (Positivkontrolle)", bool(alle))
check("eine bekannte wird geloescht",
      bool(alle) and fb.abgabe_loeschen(alle[0]["id"]) is True)
check("und ist danach weg",
      bool(alle) and len(fb.abgaben(fid=f["id"])) == vorher - 1)

# ⚠ Ein geloeschtes Formular nimmt seine Abgaben NICHT mit.
rest = len(fb.abgaben(fid=f["id"]))
check("Formular loeschen meldet True", fb.formular_loeschen(f["id"]) is True)
check("unbekanntes Formular meldet False", fb.formular_loeschen(f["id"]) is False)
check("⚠ die ABGABEN bleiben nach dem Loeschen des Formulars liegen",
      len(fb.abgaben(fid=f["id"])) == rest,
      "sie sind das Ergebnis der Arbeit von Benutzern")


# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m5. Reihenfolge\033[0m")
# ═══════════════════════════════════════════════════════════════════════════
fa = fb.formular_speichern("", "A", "", [{"name": "x", "typ": "text"}])
fbb = fb.formular_speichern("", "B", "", [{"name": "x", "typ": "text"}])
fc = fb.formular_speichern("", "C", "", [{"name": "x", "typ": "text"}])
folge = lambda: [x["titel"] for x in fb.formulare()]  # noqa: E731
start = folge()
fb.formulare_sortieren([fc["id"], fa["id"], fbb["id"]])
check("die gewuenschte Reihenfolge wird uebernommen",
      folge()[-3:] == ["C", "A", "B"], "ist: %r" % (folge(),))
fb.formulare_sortieren([fbb["id"], "gibtsnicht"])
check("⚠ eine unbekannte Kennung verliert kein Formular",
      sorted(folge()) == sorted(start), "ist: %r" % (folge(),))
check("und die nicht genannten landen hinten", folge()[0] == "B")
check("eine leere Liste aendert nichts", fb.formulare_sortieren([]) == 0)
for x in (fa, fbb, fc):
    fb.formular_loeschen(x["id"])


# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m6. CSV-Export\033[0m")
# ═══════════════════════════════════════════════════════════════════════════
fx = muss("Export-Formular anlegen gelingt", fb.formular_speichern, "",
          "Export Test", "", [
    {"name": "Modul", "typ": "text"},
    {"name": "Note", "typ": "sterne"},
])
SX = {s["name"]: s["id"] for s in fx.get("spalten", [])}
SX.setdefault("Modul", "?m")
SX.setdefault("Note", "?n")
muss("die Export-Abgabe gelingt", fb.abgabe_speichern, "anna", fx["id"], [
    {SX["Modul"]: "=cmd|'/c calc'!A1", SX["Note"]: 5},
    {SX["Modul"]: "Umlaut: Prüfung", SX["Note"]: 2},
    {SX["Modul"]: "mit;Semikolon", SX["Note"]: 1},
])
name, csvtext = fb.csv_export(fx["id"])

check("⚠ CSV-Injection wird entschaerft",
      "\n'=cmd" in csvtext.replace("\r\n", "\n") or ";'=cmd" in csvtext,
      "ein fuehrendes = macht Excel daraus eine FORMEL")
for z in ("+", "-", "@"):
    check("auch ein fuehrendes `%s` wird entschaerft" % z,
          fb.csv_zelle(z + "boese").startswith("'" + z))
check("eine gewoehnliche Zahl bleibt unangetastet", fb.csv_zelle("42") == "42")
check("und ein gewoehnlicher Satz auch", fb.csv_zelle("Alles gut") == "Alles gut")

check("die Datei beginnt mit einem BOM", csvtext.startswith("﻿"),
      "sonst zerstoert deutsches Excel jeden Umlaut")
check("Trennzeichen ist `;`", "Zeitpunkt;Benutzer;Abgabe;Zeile;" in csvtext)
check("Zeilenende ist CRLF", "\r\n" in csvtext)
check("Umlaute kommen durch", "Prüfung" in csvtext)
check("ein Semikolon im Wert wird gequotet", '"mit;Semikolon"' in csvtext)
check("der Dateiname traegt den Formulartitel", name.startswith("Export Test_"))
check("und endet auf .csv", name.endswith(".csv"))
check("es gibt eine Zeile JE FORMULARZEILE, nicht je Abgabe",
      len([z for z in csvtext.strip().split("\r\n") if z]) == 4)

# ⚠ Eine entfernte Spalte muss im Export TROTZDEM erscheinen.
fb.formular_speichern(fx["id"], "Export Test", "",
                      [{"id": SX["Modul"], "name": "Modul", "typ": "text"}])
_, csv2 = fb.csv_export(fx["id"])
check("⚠ eine ENTFERNTE Spalte steht weiter im Export",
      "(entfernt)" in csv2,
      "ein Export, der stillschweigend Daten weglaesst, ist schlimmer als eine Spalte zu viel")
check("und ihre Werte auch", csv2.count(";5") >= 1 or ";5\r\n" in csv2)

# Ein Dateiname darf keine Pfadtrenner tragen (er geht in einen HTTP-Kopf).
fy = fb.formular_speichern("", "../../etc/passwd \"boese\"", "",
                           [{"name": "a", "typ": "text"}])
n2, _ = fb.csv_export(fy["id"])
check("der Dateiname ist entschaerft",
      "/" not in n2 and ".." not in n2 and '"' not in n2, "ist: %r" % n2)
fb.formular_loeschen(fy["id"])


# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m7. Robustheit der Dateien\033[0m")
# ═══════════════════════════════════════════════════════════════════════════
fb._pfad_formulare().write_text("{kaputt", encoding="utf-8")
check("eine beschaedigte Formulardatei sperrt den Bereich nicht",
      fb.formulare() == [])
check("⚠ und wird NICHT stillschweigend ueberschrieben",
      fb._pfad_formulare().read_text(encoding="utf-8") == "{kaputt",
      "das vernichtet sonst die Arbeit des Administrators")

with fb._pfad_abgaben().open("a", encoding="utf-8") as fh:
    fh.write("{kaputte zeile\n")
check("eine kaputte Abgaben-Zeile nimmt die uebrigen nicht mit",
      len(fb.abgaben()) >= 1)

mode = oct(fb._pfad_abgaben().stat().st_mode)[-3:]
check("die Abgaben-Datei ist 0640", mode == "640", "ist: %s" % mode)

print("  \033[32m✓\033[0m der ECHTE Bestand wurde nicht angefasst"
      if all((p.stat().st_mtime if p.exists() else None) == m
             for p, m in _echt_vorher) else "  \033[31m✗\033[0m ECHTER BESTAND VERAENDERT")
if all((p.stat().st_mtime if p.exists() else None) == m for p, m in _echt_vorher):
    _ok += 1
else:
    _fail += 1

shutil.rmtree(SAND, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m8. Endpunkte: Rechte als REGEL, nicht als Liste\033[0m")
# ═══════════════════════════════════════════════════════════════════════════
# Geprueft wird die EIGENSCHAFT ueber den Syntaxbaum – damit faellt auch eine
# KUENFTIGE Route auf, ohne dass jemand hier eine Liste pflegt.
QUELLE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)


def _ohne_kommentare(quelle: str) -> str:
    """Kommentare UND DOCSTRINGS raus – sonst liest der Waechter seine eigene
    Begruendung.

    ⚠ HIER IST DAS KEIN FEINSCHLIFF, und der Docstring-Teil ist der
    entscheidende: der Text in `main.py`, der das Entfallen der Felder
    ERKLAERT, steht im DOCSTRING von `_user_may_use_feedback` und nennt
    `feedback_allowed_users` woertlich. Ein Filter, der nur `#`-Zeilen
    entfernt, laesst die Regressions-Pruefung dauerhaft rot aussehen – fuer
    einen Zustand, der genau richtig ist (beim Bau gemessen).
    """
    import io
    import tokenize
    try:
        baum = ast.parse(quelle)
    except SyntaxError:
        return quelle
    zeilen = quelle.splitlines(keepends=True)
    versatz = [0]
    for z in zeilen:
        versatz.append(versatz[-1] + len(z))
    zeichen = list(quelle)

    def loesche(z1, s1, z2, s2):
        a, b = versatz[z1 - 1] + s1, versatz[z2 - 1] + s2
        for i in range(a, min(b, len(zeichen))):
            if zeichen[i] != "\n":
                zeichen[i] = " "

    for knoten in ast.walk(baum):
        if not isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                   ast.AsyncFunctionDef)):
            continue
        koerper = getattr(knoten, "body", [])
        if (koerper and isinstance(koerper[0], ast.Expr)
                and isinstance(koerper[0].value, ast.Constant)
                and isinstance(koerper[0].value.value, str)):
            d = koerper[0].value
            loesche(d.lineno, d.col_offset, d.end_lineno, d.end_col_offset)
    try:
        for t in tokenize.generate_tokens(io.StringIO(quelle).readline):
            if t.type == tokenize.COMMENT:
                loesche(t.start[0], t.start[1], t.end[0], t.end[1])
    except Exception:                                # noqa: BLE001
        pass
    return "".join(zeichen)


KOMMENTARFREI = _ohne_kommentare(QUELLE)
# Positivkontrolle des Filters: ohne sie waere nicht zu unterscheiden, ob er
# greift oder ob die Datei den Text schlicht nicht enthaelt.
assert "feedback_allowed_users" in QUELLE, "Erklaer-Kommentar fehlt – Filter unpruefbar"
assert "feedback_allowed_users" not in KOMMENTARFREI, "Kommentarfilter greift nicht"

# Der Rumpf des Rechte-Helfers – daran haengt die Aussage, WORAN die Freigabe haengt.
_perm_helfer = None
for _k in ast.walk(BAUM):
    if isinstance(_k, ast.FunctionDef) and _k.name == "_user_may_use_feedback":
        _perm_helfer = ast.get_source_segment(QUELLE, _k)


def routen():
    """(Pfad, Methode, FunktionsKnoten, Dependency-Namen) je /api/feedback-Route."""
    raus = []
    for k in ast.walk(BAUM):
        if not isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dek in k.decorator_list:
            if not (isinstance(dek, ast.Call) and isinstance(dek.func, ast.Attribute)):
                continue
            if not (isinstance(dek.func.value, ast.Name) and dek.func.value.id == "app"):
                continue
            if not dek.args or not isinstance(dek.args[0], ast.Constant):
                continue
            pfad = dek.args[0].value
            # ⚠ MIT SCHRAEGSTRICH. `POST /api/feedback` (ohne) gibt es seit
            # Langem: das ist die Bewertung einer Chat-Antwort (👍/👎) und hat
            # mit diesem Skill NICHTS zu tun ausser dem Wort. Sie wird unten
            # NAMENTLICH ausgenommen – eine Sammelfreigabe ueber den Praefix
            # waere das Ende dieser Regel.
            if not isinstance(pfad, str) or not pfad.startswith("/api/feedback/"):
                continue
            deps = []
            for arg in list(k.args.args) + list(k.args.kwonlyargs):
                pass
            for d in (k.args.defaults or []) + [x for x in (k.args.kw_defaults or []) if x]:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                        and d.func.id == "Depends" and d.args
                        and isinstance(d.args[0], ast.Name)):
                    deps.append(d.args[0].id)
            raus.append((pfad, dek.func.attr, k, deps))
    return raus


R = routen()
check("es gibt ueberhaupt Feedback-Routen (Positivkontrolle)", len(R) >= 8,
      "gefunden: %d" % len(R))

# ⚠ DIE BESTANDSROUTE `POST /api/feedback` (ohne Schraegstrich) ist die
# Bewertung einer Chat-Antwort und AELTER als dieser Skill. Hier wird nur
# festgehalten, dass sie noch das ist, wofuer die Ausnahme gilt – rutscht sie
# auf etwas anderes, faellt es auf.
_alt = [k for k in ast.walk(BAUM)
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and d.args and isinstance(d.args[0], ast.Constant)
                and d.args[0].value == "/api/feedback" for d in k.decorator_list)]
check("die Bestandsroute /api/feedback ist weiterhin die Antwort-Bewertung",
      len(_alt) == 1 and "rating" in ast.unparse(_alt[0]),
      "sie teilt nur das Wort mit diesem Skill, nicht die Sache")

admin = [r for r in R if r[0].startswith("/api/feedback/admin/")]
nutzer = [r for r in R if not r[0].startswith("/api/feedback/admin/")]
check("es gibt Admin- UND Benutzer-Routen (Positivkontrolle)",
      len(admin) >= 5 and len(nutzer) >= 3)

falsch = [r[0] for r in admin if "require_local_auth" not in r[3]]
check("⚠ JEDE /api/feedback/admin/-Route haengt an require_local_auth",
      not falsch, "offen: %r" % falsch)

falsch = [r[0] for r in nutzer if "require_feedback_access" not in r[3]]
check("⚠ JEDE uebrige /api/feedback/-Route haengt an require_feedback_access",
      not falsch, "offen: %r" % falsch)

# ⚠ DER BENUTZER KOMMT AUS DER ANMELDUNG, NIE AUS DEM RUMPF.
def liest_benutzer_aus_rumpf(knoten):
    for k in ast.walk(knoten):
        if isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute):
            if k.func.attr == "get" and k.args and isinstance(k.args[0], ast.Constant):
                if str(k.args[0].value).lower() in (
                        "user", "benutzer", "username", "benutzername", "owner"):
                    return True
        if isinstance(k, ast.Subscript) and isinstance(k.slice, ast.Constant):
            if str(k.slice.value).lower() in ("user", "benutzer", "username"):
                # Nur im Rumpf-Kontext gefaehrlich; hier reicht der Verdacht.
                return True
    return False


falsch = [r[0] for r in R if liest_benutzer_aus_rumpf(r[2])]
check("⚠ KEINE Route nimmt den Benutzer aus dem Rumpf",
      not falsch,
      "sonst ist der Endpunkt der bequemste Weg, einem Kollegen etwas unterzuschieben: %r"
      % falsch)

# ⚠ DIE ZENTRALE ZUSAGE DES SKILLS: es laeuft KEIN Modell.
MODELL = ("run_task", "run_task_headless", "generate_response", "get_provider",
          "provider_fuer_lauf", "_sec_llm_classify", "llm.")
mod_quelle = (ROOT / "backend" / "feedback.py").read_text(encoding="utf-8")
# Kommentare/Docstrings entfernen – sonst liest der Waechter die eigene
# Begruendung ("ES LAEUFT KEIN MODELL", Register: 15 belegte Faelle).
def ohne_doku(txt):
    baum = ast.parse(txt)
    for k in ast.walk(baum):
        if isinstance(k, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (k.body and isinstance(k.body[0], ast.Expr)
                    and isinstance(k.body[0].value, ast.Constant)
                    and isinstance(k.body[0].value.value, str)):
                k.body = k.body[1:] or [ast.Pass()]
    return ast.unparse(baum)


mod_code = ohne_doku(mod_quelle)
check("Positivkontrolle: der Kommentar-Entferner hat gearbeitet",
      "ES LAEUFT KEIN MODELL" in mod_quelle and "ES LAEUFT KEIN MODELL" not in mod_code)
treffer = [m for m in MODELL if m in mod_code]
check("⚠ backend/feedback.py ruft KEIN Sprachmodell", not treffer,
      "gefunden: %r" % treffer)

rumpf_code = ohne_doku("\n".join(ast.unparse(r[2]) for r in R))
treffer = [m for m in MODELL if m in rumpf_code]
check("⚠ und auch keine der Feedback-Routen", not treffer,
      "eine Abgabe wird gespeichert, mehr nicht: %r" % treffer)

# Blockierende Datei-I/O gehoert in einen Thread (Register: Event-Loop).
ohne_thread = []
for pfad, methode, knoten, _ in R:
    if pfad == "/api/feedback":  # Seitenroute o.ae. gibt es hier nicht
        continue
    code = ast.unparse(knoten)
    if "fb." in code and "to_thread" not in code:
        ohne_thread.append(pfad)
check("jede Route mit Datei-I/O laeuft ueber asyncio.to_thread",
      not ohne_thread, "blockiert den Event-Loop: %r" % ohne_thread)


# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m9. Verdrahtung: Skill, Kachel, Reiter, Sperrlisten\033[0m")
# ═══════════════════════════════════════════════════════════════════════════
from backend import sandbox as sb  # noqa: E402

for datei in ("data/feedback_formulare.json", "data/feedback_abgaben.jsonl"):
    check("%s steht in _APP_DENY_REL" % datei, datei in sb._APP_DENY_REL)
    check("%s steht in PRIVATE_FILES (0640)" % datei, datei in sb.PRIVATE_FILES)
    check("%s wird vom Shell-Muster getroffen" % datei,
          bool(sb.SHELL_SECRET_PATHS.search("cat /opt/jarvis/" + datei)),
          "sonst liest ein `cat` in der Sandbox fremde Abgaben")

manifest = json.loads((ROOT / "skills" / "feedback" / "skill.json").read_text(encoding="utf-8"))
check("der Skill stellt KEINE Agent-Werkzeuge bereit", manifest["tools"] == [])
check("und ist per Vorgabe AUS", manifest["enabled"] is False)
check("er ist kein System-Skill (also deinstallierbar)", manifest["system"] is False)

# ⚠ AN DER STELLE MESSEN, NICHT ueber die ganze Datei: `_skill_active("feedback")`
# steht auch im Admin-Endpunkt („skill_aktiv"), und eine Suche ueber QUELLE bleibt
# deshalb wahr, selbst wenn die Kachel nur noch an der Freigabe haengt. Genau so
# ist diese Pruefung in der Gegenprobe stumm geblieben (Register: die Eigenschaft
# messen, nicht das Vorkommen).
_perm = None
for _k in ast.walk(BAUM):
    if isinstance(_k, ast.Dict):
        for _s, _v in zip(_k.keys, _k.values):
            if isinstance(_s, ast.Constant) and _s.value == "feedback":
                _perm = ast.unparse(_v)
check("der permissions-Eintrag `feedback` wurde gefunden (Positivkontrolle)",
      _perm is not None)
check("`permissions.feedback` verlangt Freigabe UND aktiven Skill",
      _perm is not None and "_user_may_use_feedback" in _perm
      and '_skill_active' in _perm,
      "ist: %s" % _perm)
# ⚠ VORGABE DES BETREIBERS (2026-09-14): KEINE eigene Freigabeliste mehr –
# es gilt, wer WISSEN BEARBEITEN darf. Die alten Felder duerfen nicht
# zurueckkommen; sie waeren eine Einstellung, die gespeichert wird und nichts
# bewirkt, und ein zweiter Ort fuer dieselbe Personengruppe.
check("⚠ die eigene Feedback-Freigabeliste ist ERSATZLOS entfallen",
      "feedback_allowed_users" not in KOMMENTARFREI
      and "feedback_allowed_group" not in KOMMENTARFREI,
      "die alten Felder sind zurueck")
check("⚠ die Freigabe haengt am SELBEN Praedikat wie die Wissen-Kachel",
      "_editable_groups_for" in (_perm_helfer or ""),
      "ist: %s" % (_perm_helfer or "<nicht gefunden>"))

# `_user_may_use_feedback` wirklich ausfuehren. `_editable_groups_for` wird
# dabei gestellt – es liest Gruppendatei UND Index, und geprueft wird hier die
# WEICHE, nicht jene Funktion.
_fn = {}
for k in ast.walk(BAUM):
    if isinstance(k, ast.FunctionDef) and k.name in ("_user_may_use_feedback",
                                                     "_may_edit_knowledge"):
        _fn[k.name] = k
check("der Rechte-Helfer existiert", "_user_may_use_feedback" in _fn)
check("und `_may_edit_knowledge` wurde mitgeschnitten (Positivkontrolle)",
      "_may_edit_knowledge" in _fn)

if len(_fn) == 2:
    def _lauf(bereich=(), editoren="", wirft=False):
        def _egf(u):
            if wirft:
                raise RuntimeError("Gruppendatei kaputt")
            return list(bereich)
        ns = {
            "config": type("C", (), {"get_setting": staticmethod(
                lambda k, d="": editoren if k == "ad_knowledge_editors" else "")})(),
            "ALLOWED_USERS": {"jarvis"},
            "_norm_login": lambda x: (x or "").strip().lower(),
            "_knowledge_editor_cache": {},
            "_gruppe_trifft": lambda *a: False,
            "_editable_groups_for": _egf,
            "print": lambda *a, **k: None,
        }
        exec(compile(ast.Module(body=[_fn["_may_edit_knowledge"],
                                      _fn["_user_may_use_feedback"]],
                                type_ignores=[]), "<w>", "exec"), ns)
        return ns["_user_may_use_feedback"]

    check("⚠ kein Bereich heisst NIEMAND – auch kein Administrator",
          _lauf(bereich=())("irgendwer") is False
          and _lauf(bereich=())("jarvis") is False)
    check("⚠ ein GRUPPEN-Editor darf (das war vorher NICHT so)",
          _lauf(bereich=[{"id": "g1"}])("klaus") is True)
    check("mehrere Gruppen ebenso", _lauf(bereich=[{"id": "a"}, {"id": "b"}])("anna") is True)
    check("ein leerer Benutzername nie", _lauf(bereich=[{"id": "g1"}])("") is False)
    # Fail-safe: der Rueckfall ist die ENGERE Menge, nicht die weitere.
    check("⚠ faellt die Gruppen-Ermittlung aus, gilt der ENGERE Rueckfall",
          _lauf(wirft=True, editoren="anna")("anna") is True
          and _lauf(wirft=True, editoren="anna")("carla") is False)
    check("und der Rueckfall oeffnet nichts, wenn nichts konfiguriert ist",
          _lauf(wirft=True, editoren="")("anna") is False)

FRONT = ROOT / "frontend"
check("die Portal-Kachel steht im Markup",
      'id="pt-card-feedback"' in (FRONT / "portal.html").read_text(encoding="utf-8"))
check("und wird an `permissions.feedback` eingeblendet",
      "permissions.feedback" in (FRONT / "portal.html").read_text(encoding="utf-8"))

# ══ DRIFT-SCHRANKE: Wissen- und Feedback-Kachel muessen DIESELBE Quelle haben ══
# ⚠ VORGABE DES BETREIBERS (Rueckfrage 2026-09-14): „gleiche Berechtigung und
# Sichtbarkeit". Beide leiten sich deshalb aus `_editable_groups_for` ab – die
# Wissen-Kachel ueber `/api/wissen/scope` (Feld `groups`), die Feedback-Kachel
# ueber `permissions.feedback`. Wer eine der beiden Seiten auf ein anderes
# Praedikat umhaengt, bricht die Zusage STILL: beide Kacheln sehen weiter
# richtig aus, nur fuer verschiedene Leute. Gemessen wurde genau das – ein
# Gruppen-Editor sah Wissen und kein Feedback.
_scope_fn = None
for _k in ast.walk(BAUM):
    if (isinstance(_k, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _k.name == "wissen_scope"):
        _scope_fn = ast.get_source_segment(QUELLE, _k)
check("der Scope-Endpunkt wurde gefunden (Positivkontrolle)", _scope_fn is not None)
check("⚠ die Wissen-Kachel leitet sich aus `_editable_groups_for` ab",
      _scope_fn is not None and "_editable_groups_for" in _scope_fn)
check("⚠ die Feedback-Kachel aus DEMSELBEN Praedikat",
      "_editable_groups_for" in (_perm_helfer or ""))
check("die Wissen-Kachel haengt an genau diesem Feld (`groups`)",
      'd.groups && d.groups.length' in (FRONT / "portal.html").read_text(encoding="utf-8"),
      "die Einblende-Bedingung der Wissen-Kachel hat sich geaendert")
st = (FRONT / "settings.html").read_text(encoding="utf-8")
check("der Reiter-Knopf steht im Markup", 'id="settings-tab-btn-feedback"' in st)
check("und sein Panel auch", 'id="settings-tab-feedback"' in st)
# ⚠ UMGEKEHRTE ZUSAGE seit 2026-09-14: der eigene Freigabe-Block ist ERSATZLOS
# entfallen, der Bereich haengt an den Wissens-Editoren. Ein zurueckkehrender
# Block waere ein zweiter Ort fuer dieselbe Personengruppe.
check("⚠ der eigene Freigabe-Block ist aus dem Sicherheits-Reiter entfernt",
      'id="sec-sub-feedback"' not in st,
      "der Block ist zurueck")
check("und seine Felder ebenfalls",
      'id="feedback-allowed-users"' not in st and 'id="feedback-allowed-group"' not in st)
check("die tote Sichtbarkeits-Funktion ist weg",
      "window.updateFeedbackSecVisibility" not in
      (FRONT / "js" / "app.js").read_text(encoding="utf-8"),
      "eine Funktion ohne Bedienelement ist toter Code")
# Der Block, auf den jetzt verwiesen wird, MUSS es geben – sonst nennt die
# Oberflaeche ein Bedienelement, das niemand findet.
check("der Editoren-Block, an dem es jetzt haengt, existiert",
      'id="ad-knowledge-editors"' in st)

app_js = (FRONT / "js" / "app.js").read_text(encoding="utf-8")
# ⚠ DIESE PRUEFUNG STEHT HIER, WEIL DIE EINBINDUNG GEFEHLT HAT (2026-09-14):
# `app.js` ruft `if (window.FeedbackAdmin) …` – ohne das Skript ist der Wert
# `undefined`, der Aufruf faellt STILL aus und der Reiter bleibt leer. Der
# UI-Waechter konnte das nicht sehen: er laedt die Datei selbst.
# Geprueft wird als REGEL ueber ALLE handgebauten Reiter-Module.
for _modul in ("feedback_admin.js", "ai_mouse_admin.js"):
    check("%s ist in settings.html eingebunden" % _modul,
          ("/static/js/" + _modul + "?v=") in st,
          "sonst ist window.*Admin undefined und der Reiter bleibt leer")
check("app.js kennt den Reiter", "settings-tab-feedback" in app_js)
check("app.js ruft FeedbackAdmin.onShow()", "FeedbackAdmin" in app_js)
check("⚠ app.js fasst den entfallenen Sicherheits-Block nicht mehr an",
      "sec-sub-feedback" not in app_js,
      "Verdrahtung auf ein Bedienelement, das es nicht mehr gibt")
check("das Panel steht in allSettingsTabs (sonst bleibt es beim Wechsel stehen)",
      "tabFeedback" in app_js.split("allSettingsTabs = ")[1].split("\n")[0])
check("skills.js kennt den Reiter (Zahnrad-Sprung)",
      "feedback:" in (FRONT / "js" / "skills.js").read_text(encoding="utf-8"))
check("skillcfg.js blendet den Reiter am Skill-Zustand ein",
      "settings-tab-btn-feedback" in (FRONT / "js" / "skillcfg.js").read_text(encoding="utf-8"))

# Die Collapse-Regel: JEDE .kb-section des Reiters muss gebunden sein.
panel = st.split('id="settings-tab-feedback"')[1].split('<div id="settings-tab-')[0]
import re as _re
sektionen = _re.findall(r'class="kb-section" id="(fb-sect-[a-z]+)"', panel)
check("es gibt ueberhaupt Sektionen (Positivkontrolle)", len(sektionen) >= 3)
fehlend = [s_ for s_ in sektionen if (s_ + "-hdr") not in app_js]
check("⚠ JEDE Sektion des Reiters ist in _initFeedbackCollapse gebunden",
      not fehlend, "bleibt sonst zugeklappt und laesst sich nicht oeffnen: %r" % fehlend)


# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m10. Feste Zeilen + Spaltentyp `fest`\033[0m")
# ═══════════════════════════════════════════════════════════════════════════
# Die Bauform fuer einen Bewertungsbogen (Vorgabe des Betreibers 2026-09-15):
# Spalte 1 nur lesbar, Spalte 2 Text, Spalte 3 Sterne – bei 6 vom Administrator
# vorgegebenen Zeilen.
#
# ⚠ DIE TRAGENDE ZUSAGE IST, DASS DER FESTE TEXT AUS DER DEFINITION KOMMT.
# Sie wird AUSGEFUEHRT geprueft, mit einem Request, der ihn zu faelschen
# versucht – eine Quelltext-Suche koennte das nicht beantworten.

check("`fest` ist ein bekannter Spaltentyp", fb.TYP_FEST in fb.SPALTEN_TYPEN)

SP_BOGEN = [{"id": "spkrit", "name": "Kriterium", "typ": "fest"},
            {"id": "spanm", "name": "Anmerkung", "typ": "text"},
            {"id": "spbew", "name": "Bewertung", "typ": "sterne"}]
TEXTE = ["Erreichbarkeit", "Reaktionszeit", "Fachliche Qualität",
         "Freundlichkeit", "Dokumentation", "Gesamteindruck"]
Z_BOGEN = [{"id": "z%d" % i, "werte": {"spkrit": t}} for i, t in enumerate(TEXTE)]

def zv(formular, i, schluessel):
    """Ein Vorgabewert aus einer Formular-DEFINITION – nie ungeprueft.

    ⚠ Gleiche Lehre wie `za`: `f["zeilen"][2]` wirft, sobald eine Gegenprobe
    die Zeilen wegfallen laesst (die Probe „Spalten-Kennung wird neu vergeben"
    tut genau das – dann passen die Werte-Schluessel nicht mehr und die Zeilen
    werden verworfen). Der Lauf endete dadurch OHNE Bilanzzeile.
    """
    if fehler(formular) or not isinstance(formular, dict):
        return None
    zs = formular.get("zeilen") or []
    if not isinstance(zs, list) or i >= len(zs) or not isinstance(zs[i], dict):
        return None
    return (zs[i].get("werte") or {}).get(schluessel)


def zn(formular):
    """Anzahl der festen Zeilen – 0 bei jedem Fehlschlag."""
    if fehler(formular) or not isinstance(formular, dict):
        return 0
    zs = formular.get("zeilen")
    return len(zs) if isinstance(zs, list) else 0


# ── Die Regel, die den alten Widerspruch aufloest ──────────────────────────
r = sicher(fb.formular_speichern, "", "Ohne Zeilen", "", SP_BOGEN, True, [])
check("⚠ `fest`-Spalte OHNE feste Zeilen wird ABGEWIESEN", fehler(r),
      "sonst haette der Benutzer eine Zelle, die er weder lesen noch fuellen kann")
check("die Absage nennt den Weg (nicht nur den Zustand)",
      fehler(r) and "Feste Zeilen" in str(r[1]), str(r)[:90])

r = sicher(fb.formular_speichern, "", "Nur fest", "",
           [{"id": "a", "name": "A", "typ": "fest"}], True,
           [{"id": "z0", "werte": {"a": "x"}}])
check("⚠ ein Formular NUR aus `fest`-Spalten wird abgewiesen (Sackgasse)", fehler(r),
      "der Benutzer koennte nichts eintragen und nie absenden")

# Feste Zeilen OHNE `fest`-Spalte sind dagegen zulaessig: nummerierte Zeilen.
r = sicher(fb.formular_speichern, "", "Nummeriert", "",
           [{"id": "t1", "name": "Text", "typ": "text"}], True,
           [{"id": "n1", "werte": {}}, {"id": "n2", "werte": {}}])
check("feste Zeilen OHNE `fest`-Spalte sind erlaubt", zn(r) == 2)

# ── Der Regelfall ─────────────────────────────────────────────────────────
# ⚠ UEBER `muss`, NICHT ROH: ein roher Aufruf wirft, sobald eine Gegenprobe eine
# fruehere Zusage verletzt (die Probe „Spalten-Kennung wird neu vergeben" laesst
# genau diesen Aufruf scheitern) – der Lauf endet dann OHNE Bilanzzeile und ist
# von „nicht gelaufen" nicht zu unterscheiden.
bogen = muss("den Bewertungsbogen anlegen gelingt", fb.formular_speichern,
             "", "Gesamtbewertung", "Bitte bewerten.", SP_BOGEN, True, Z_BOGEN)
check("6 feste Zeilen gespeichert", zn(bogen) == 6)
check("⚠ die Zeilen-Kennungen werden UEBERNOMMEN, nicht neu vergeben",
      [z.get("id") for z in (bogen.get("zeilen") or []) if isinstance(z, dict)]
      == ["z%d" % i for i in range(6)],
      "eine neue Kennung macht jede bisherige Abgabe unzuordenbar")
check("die Spalten-Kennungen werden uebernommen (sonst zeigen die Zeilenwerte ins Leere)",
      [x.get("id") for x in (bogen.get("spalten") or []) if isinstance(x, dict)]
      == ["spkrit", "spanm", "spbew"])

# ── Abgabe: der Faelschungsversuch ────────────────────────────────────────
ab = sicher(fb.abgabe_speichern, "nexus\\Andreas.Bender", bogen.get("id") or "?", [
    {"_zid": "z0", "spkrit": "GEFAELSCHT", "spanm": "lief gut", "spbew": 5},
    {"_zid": "z3", "spbew": 3},
    {"_zid": "gibtesnicht", "spanm": "darf nicht ankommen"},
])
check("die Abgabe wird angenommen", not fehler(ab), str(ab)[:80])
zeilen_ab = (ab.get("zeilen") or []) if not fehler(ab) else []


def za(i, schluessel):
    """Ein Zellwert aus der Abgabe – NIE ungeprueft dereferenzieren.

    ⚠ `zeilen_ab[3].get(...)` wirft, sobald eine Sabotage Zeilen wegfallen
    laesst: der Lauf endet dann OHNE Bilanzzeile, und das ist von „nicht
    gelaufen" nicht zu unterscheiden. Genau so hat die Gegenprobe „leere feste
    Zeilen fallen aus der Abgabe" statt eines FAIL einen Abbruch gemeldet.
    """
    if not isinstance(zeilen_ab, list) or i >= len(zeilen_ab):
        return None
    z = zeilen_ab[i]
    return z.get(schluessel) if isinstance(z, dict) else None


check("⚠ DER FESTE TEXT KOMMT AUS DER DEFINITION, nicht aus dem Request",
      za(0, "spkrit") == "Erreichbarkeit",
      "sonst stuende im Export eine Bewertung unter einer nie gestellten Frage")
check("alle 6 festen Zeilen sind gespeichert – auch die leeren",
      len(zeilen_ab) == 6,
      "faellt eine heraus, verschieben sich die Zeilen zwischen zwei Abgaben")
check("die Reihenfolge kommt aus der DEFINITION, nicht aus dem Request",
      [z.get(fb.ZEILEN_ID) for z in zeilen_ab if isinstance(z, dict)]
      == ["z%d" % i for i in range(6)])
check("eine unbekannte Zeilen-Kennung wird verworfen",
      all(isinstance(z, dict) and z.get(fb.ZEILEN_ID) in [x["id"] for x in Z_BOGEN]
          for z in zeilen_ab))
check("die eingetragenen Werte kommen an",
      za(0, "spanm") == "lief gut" and za(0, "spbew") == 5
      and za(3, "spbew") == 3)
check("eine nicht ausgefuellte Zeile bleibt leer",
      za(1, "spanm") == "" and za(1, "spbew") == 0)
check("jede Zeile traegt ihre Kennung (fuer eine spaetere Auswertung)",
      bool(zeilen_ab) and all(isinstance(z, dict) and z.get(fb.ZEILEN_ID)
                              for z in zeilen_ab))

r = sicher(fb.abgabe_speichern, "wer", bogen.get("id") or "?", [{"_zid": "z0"}])
check("eine Abgabe OHNE eine einzige Eingabe wird abgewiesen", fehler(r),
      "der feste Text allein macht eine Zeile nicht „ausgefuellt“")
r = sicher(fb.abgabe_speichern, "wer", bogen.get("id") or "?", [])
check("eine leere Zeilenliste wird abgewiesen", fehler(r))

# ── Sentinel: ein aelterer Client darf die Zeilen nicht loeschen ──────────
neu = sicher(fb.formular_speichern, bogen.get("id") or "?", "Neuer Titel", "",
             bogen.get("spalten") or [], True)          # `zeilen` NICHT angegeben
check("⚠ Speichern OHNE `zeilen` BEHAELT die festen Zeilen", zn(neu) == 6,
      "sonst loescht ein halber Deploy beim Titel-Speichern den ganzen Bogen")
check("die Texte sind dabei unveraendert",
      zv(neu, 2, "spkrit") == "Fachliche Qualität")

# ── Der Export traegt den festen Text ─────────────────────────────────────
name_csv, inhalt_csv = fb.csv_export(bogen.get("id") or "?")
check("der CSV-Kopf nennt die feste Spalte", "Kriterium" in inhalt_csv.splitlines()[0])
check("der feste Text steht in der CSV-Zeile", "Erreichbarkeit" in inhalt_csv)
check("der gefaelschte Text steht NICHT im Export", "GEFAELSCHT" not in inhalt_csv)

# ── Ein Vorgabewert gilt NUR fuer `fest`-Spalten ──────────────────────────
# Sonst waere er eine VORBELEGUNG – etwas anderes als das Bestellte, und in der
# Abgabe von einer Eingabe des Benutzers nicht zu unterscheiden.
vorbel = sicher(fb.formular_speichern, "", "Vorbelegt", "", SP_BOGEN, True,
                [{"id": "zv", "werte": {"spkrit": "Frage",
                                        "spanm": "VORBELEGT", "spbew": "5"}}])
check("⚠ ein Vorgabewert fuer eine TEXT-Spalte wird verworfen",
      zn(vorbel) == 1 and zv(vorbel, 0, "spanm") is None,
      "eine Vorbelegung saehe in der Abgabe wie eine Eingabe des Benutzers aus")
check("der Wert der `fest`-Spalte bleibt erhalten",
      zv(vorbel, 0, "spkrit") == "Frage")
ab_v = sicher(fb.abgabe_speichern, "wer",
              (vorbel.get("id") if not fehler(vorbel) else "") or "?",
              [{"_zid": "zv", "spbew": 2}])
check("und er taucht auch in der Abgabe nicht auf",
      not fehler(ab_v) and isinstance(ab_v, dict)
      and ((ab_v.get("zeilen") or [{}])[0] or {}).get("spanm") == "")

# ── Laengengrenze der Kennung (sie ist Fremdeingabe) ──────────────────────
lang = sicher(fb.formular_speichern, "", "Lang", "",
              [{"id": "a" * 500, "name": "A", "typ": "text"}], True, None)
# ⚠ GEGEN EINE FESTE ZAHL, NICHT GEGEN `_ID_MAX`: mit der Konstanten als
# Massstab ist die Pruefung trivial erfuellt, sobald jemand sie hochsetzt –
# genau das hat die Gegenprobe „Kennung wieder unbegrenzt" aufgedeckt.
check("⚠ eine ueberlange Kennung wird NEU vergeben",
      not fehler(lang)
      and len(((lang.get("spalten") or [{}])[0] or {}).get("id") or "") <= 64,
      "sie steht in JEDER Zelle JEDER Abgabe")
check("die Grenze selbst bleibt in einer vernuenftigen Groessenordnung",
      fb._ID_MAX <= 64, "_ID_MAX = %r" % fb._ID_MAX)

# ── Drift-Schranke: dieselben Werte in Backend und beiden Clients ─────────
fb_js = (FRONT / "js" / "feedback.js").read_text(encoding="utf-8")
fbadm_js = (FRONT / "js" / "feedback_admin.js").read_text(encoding="utf-8")
check("⚠ `feedback.js` kennt denselben Typnamen wie das Backend",
      ("var TYP_FEST = '%s'" % fb.TYP_FEST) in fb_js,
      "sonst rendert die Seite die feste Spalte als Eingabefeld")
check("⚠ `feedback.js` kennt dieselbe Zeilen-Kennung wie das Backend",
      ("var ZEILEN_ID = '%s'" % fb.ZEILEN_ID) in fb_js,
      "sonst ordnet der Server keine einzige Zeile zu – ohne Fehlermeldung")
check("⚠ `feedback_admin.js` kennt denselben Typnamen",
      ("var TYP_FEST = '%s'" % fb.TYP_FEST) in fbadm_js)

# ── Regeln im Client, die sich nicht am Ergebnis messen lassen ────────────
check("der Client schickt `fest`-Zellen ausdruecklich NICHT mit",
      "s.typ !== TYP_FEST" in fb_js,
      "was nicht gesendet wird, kann auch nicht gefaelscht aussehen")
check("„+ Zeile“ ist bei festen Zeilen auch im HANDLER gesperrt",
      "festeZeilen().length) { return; }" in fb_js,
      "`hidden` laesst sich aus den Entwicklerwerkzeugen entfernen")
check("eine `fest`-Zelle wird als TEXT gerendert, nicht als gesperrtes Feld",
      "fb-c-fest" in fb_js and "td.textContent" in fb_js)
def ohne_kommentare(js):
    """Zeilenkommentare entfernen.

    ⚠ NOETIG, WEIL DIE BEGRUENDUNGEN LAENGER SIND ALS DIE PRUEFFENSTER: die
    erste Fassung dieser Pruefung suchte in den 300 Zeichen nach der Zuweisung
    und fand `zeilenZeichnen()` nicht – dazwischen stand ein fuenfzeiliger
    Kommentar. Sie meldete einen Fehler, den es nicht gab (Register:
    Prueffenster fester Groesse).

    Entfernt werden nur Zeilen, die NACH dem Einruecken mit `//` beginnen – ein
    `https://` mitten in einer Zeile bleibt damit unangetastet.
    """
    return "\n".join(z for z in js.splitlines() if not z.strip().startswith("//"))


fbadm_ok = ohne_kommentare(fbadm_js)
check("Positivkontrolle: der Kommentar-Filter hat wirklich gefiltert",
      "⚠ DIE ZEILEN MUESSEN NACHZIEHEN" in fbadm_js
      and "⚠ DIE ZEILEN MUESSEN NACHZIEHEN" not in fbadm_ok,
      "ohne diese Kontrolle waeren die Pruefungen darunter trivial wahr")
check("der Editor zieht die Zeilenfelder bei einem TYP-Wechsel nach",
      "Admin._entwurf[i].typ = typ.value;" in fbadm_ok
      and "Admin.zeilenZeichnen();" in fbadm_ok.split(
          "Admin._entwurf[i].typ = typ.value;")[1][:200],
      "sonst faellt erst beim Speichern auf, dass die Zeilen fehlen")
check("der Editor vergibt Spalten-Kennungen SELBST (noetig beim Anlegen)",
      "function neueKennung()" in fbadm_js
      and "id: neueKennung()" in fbadm_js,
      "sonst kennt er beim Anlegen keinen Schluessel fuer die Zeilenwerte")
check("der Arbeitsstand der Zeilen ist eine KOPIE (Abbrechen bleibt wirksam)",
      "Object.keys(z.werte || {})" in fbadm_js)

# Der Endpunkt muss den Sentinel durchreichen – sonst ist die Zusage oben tot.
haupt = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
check("⚠ der Endpunkt unterscheidet „nicht angegeben“ von „leer“",
      '"zeilen" in body' in haupt and "_ZEILEN_UNGESETZT" in haupt,
      "ohne das loescht ein aelterer Client die festen Zeilen")

# Die i18n-Schluessel in BEIDEN Sprachen – ein fehlender englischer Text laesst
# die Oberflaeche dort den Schluessel anzeigen.
i18n = (FRONT / "js" / "i18n.js").read_text(encoding="utf-8")
de_teil, en_teil = i18n.split("en:", 1) if "en:" in i18n else (i18n, "")
for schluessel in ("fbadm.typ_fest", "fbadm.f_rows", "fbadm.row_new", "fbadm.rows_fixed",
                   "fbadm.rows_free", "fbadm.rows_need",
                   "fbadm.row_del", "fbadm.rows_n", "fbadm.row_max",
                   "fbadm.row_n", "fbadm.row_nolabel", "fbadm.drag_row"):
    check("i18n „%s“ in DE und EN" % schluessel,
          i18n.count("'%s'" % schluessel) >= 2,
          "ein fehlender Text zeigt dem Benutzer den Schluessel")

css = (FRONT / "css" / "feedback.css").read_text(encoding="utf-8")
check("`.fb-z` haelt den Muelleimer in der Zeile (`min-width: 0`)",
      "min-width: 0" in css.split(".fb-z .fb-z-wert")[1][:120]
      if ".fb-z .fb-z-wert" in css else False)
# ⚠ BESTANDSFEHLER, gefunden bei der optischen Abnahme: auf `/feedback` gab es
# gar keine `.hidden`-Regel – `classList.add('hidden')` war wirkungslos (der
# „+ Zeile"-Knopf und die Formular-Auswahl standen sichtbar da). Ein
# jsdom-Waechter kann das nicht sehen, die KLASSE ist ja gesetzt.
check("⚠ `/feedback` hat ueberhaupt eine wirksame `.hidden`-Regel",
      ".hidden { display: none !important; }" in css,
      "sonst ist jedes classList.add('hidden') dieser Seite wirkungslos")
geladen = [n for n in ("theme.css", "jira_addon.css", "feedback.css")
           if ("css/" + n) in (FRONT / "feedback.html").read_text(encoding="utf-8")]
check("und sie steht in einer Datei, die die Seite wirklich laedt",
      "feedback.css" in geladen, "geladen: %r" % geladen)

check("die feste Zelle ist nicht gedaempft (sie wird GELESEN)",
      "--text-primary" in css.split("td.fb-c-fest")[1][:200]
      if "td.fb-c-fest" in css else False)


# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m11. Mehrzeilige Antworten (Vorgabe 2026-09-16)\033[0m")
# ═══════════════════════════════════════════════════════════════════════════
#
# ⚠ GEMESSEN WIRD DER GANZE WEG: dass ein Umbruch die Ablage erreicht, dort
# EINHEITLICH liegt und den CSV-Export nicht zerlegt. Ein Test, der nur
# `_mehrzeilig_normieren` prueft, saehe nicht, ob `_zelle_pruefen` sie
# ueberhaupt benutzt.

check("⚠ ein Umbruch ueberlebt die Zellpruefung",
      fb._mehrzeilig_normieren("a\nb") == "a\nb",
      "ohne Umbrueche waere ein mehrzeiliges Feld sinnlos")
check("⚠ CRLF wird zu LF vereinheitlicht",
      fb._mehrzeilig_normieren("a\r\nb") == "a\nb",
      "sonst laegen zwei Schreibweisen desselben Umbruchs im selben Bestand")
check("ein einzelnes CR ebenso (alte Macs, handgebaute Aufrufer)",
      fb._mehrzeilig_normieren("a\rb") == "a\nb")
check("⚠ Leerzeilen am ENDE fallen weg",
      fb._mehrzeilig_normieren("Text\r\n\r\n  ") == "Text",
      "strip() NACH der Normierung – vorher bliebe ein \\r stehen")
check("eine Leerzeile INNEN bleibt (sie trennt Absaetze)",
      fb._mehrzeilig_normieren("a\n\nb") == "a\n\nb")
check("der Zeichendeckel gilt weiterhin",
      len(fb._mehrzeilig_normieren("x\n" * 5000)) == fb.ZELLE_MAX)

# ── Der Rundlauf durch eine echte Abgabe ────────────────────────────────────
fm = muss("Mehrzeilen-Formular anlegen gelingt", fb.formular_speichern, "",
          "Mehrzeilig", "", [{"name": "Antwort", "typ": "text"},
                             {"name": "Note", "typ": "sterne"}])
SM = {s["name"]: s["id"] for s in fm.get("spalten", [])}
LANG = "Erste Zeile\r\nZweite Zeile\r\n\r\nNach einer Leerzeile"
ab = muss("die mehrzeilige Abgabe gelingt", fb.abgabe_speichern, "bea", fm["id"],
          [{SM["Antwort"]: LANG, SM["Note"]: 4}])
gespeichert = (ab or {}).get("zeilen", [{}])[0].get(SM["Antwort"], "")
check("⚠ der gespeicherte Wert traegt die Umbrueche",
      gespeichert.count("\n") == 3, repr(gespeichert))
check("und zwar als LF, nicht als CRLF",
      "\r" not in gespeichert, repr(gespeichert))
check("der Text ist inhaltlich vollstaendig",
      gespeichert == "Erste Zeile\nZweite Zeile\n\nNach einer Leerzeile",
      repr(gespeichert))

# ── CSV: der Umbruch darf die STRUKTUR nicht zerlegen ───────────────────────
#
# ⚠ DAS IST DIE TEUERSTE STELLE. Ein nacktes `\n` in einer Zelle wuerde eine
# CSV-Datei mitten in der Zeile brechen – aus einer Abgabe wuerden vier
# unzusammenhaengende Zeilen, und das faellt erst in Excel auf. Gemessen wird
# mit einem ECHTEN Konsumenten (`csv.reader`), nicht mit einer Textsuche.
import csv as _csv          # noqa: E402  (nur hier gebraucht)
import io as _io            # noqa: E402

_, ctext = fb.csv_export(fm["id"])
zeilen_csv = list(_csv.reader(_io.StringIO(ctext.lstrip("﻿")), delimiter=";"))
check("⚠ der Umbruch zerlegt die CSV-Struktur NICHT",
      len(zeilen_csv) == 2, "gelesen: %d Zeilen statt 2" % len(zeilen_csv))
check("und die Zelle traegt den vollstaendigen Text",
      len(zeilen_csv) == 2 and zeilen_csv[1][4].count("\n") == 3,
      repr(zeilen_csv[1][4] if len(zeilen_csv) == 2 else None))
check("der Wert steht dafuer in Anfuehrungszeichen",
      '"Erste Zeile' in ctext,
      "ohne Quoting bricht die Datei an jedem Umbruch")
# Positivkontrolle: der Leser sieht ueberhaupt die richtige Spaltenzahl –
# sonst waere „2 Zeilen" auch bei einer kaputten Datei zufaellig wahr.
check("Positivkontrolle: die Kopfzeile hat 6 Spalten",
      len(zeilen_csv) == 2 and len(zeilen_csv[0]) == 6,
      repr(zeilen_csv[0] if zeilen_csv else None))

# ── Die Oberflaeche: textarea statt input, und die Anzeige bricht um ────────
fbjs = (FRONT / "js" / "feedback.js").read_text(encoding="utf-8")
fbjs_ok = ohne_kommentare(fbjs)
check("⚠ das Antwortfeld ist ein `textarea`",
      "createElement('textarea')" in fbjs_ok,
      "ein `input` nimmt keinen Umbruch auf")
check("und es gibt kein `input type=text` mehr in der Tabelle",
      "inp.type = 'text'" not in fbjs_ok)
check("⚠ der Fokus-Sprung nach „+ Zeile\" sucht `textarea`",
      "tr:last-child textarea" in fbjs_ok,
      "der alte Selektor faende nichts – der Knopf taete still weniger")
check("die Hoehe wird an den Inhalt angepasst",
      "scrollHeight" in fbjs_ok and "hoeheAnpassen" in fbjs_ok)
check("⚠ bei Hoehe 0 wird NICHTS gesetzt (zugeklappter Container)",
      "inhalt > 0" in fbjs_ok,
      "sonst ist das Feld nach dem Aufklappen unsichtbar (Register)")
check("⚠ und beim Aufklappen wird nachgemessen",
      "hoehenNachziehen" in fbjs_ok and "if (!neuZu)" in fbjs_ok,
      "in einem zugeklappten Container ist scrollHeight 0")

check("⚠ die Lese-Zelle traegt `pre-wrap`",
      "white-space: pre-wrap" in css.split("fb-c-text")[1][:200]
      if "fb-c-text" in css else False,
      "HTML macht aus einem Umbruch sonst ein Leerzeichen")
for datei in ("feedback.js", "feedback_admin.js"):
    quelle = ohne_kommentare((FRONT / "js" / datei).read_text(encoding="utf-8"))
    check("%s zeichnet die Lese-Zelle mit `fb-c-text`" % datei,
          "'fb-c-text'" in quelle,
          "beide Anzeigestellen – eine allein waere die halbe Reparatur")
check("⚠ die tote `input[type=\"text\"]`-Regel ist aus dem Tabellen-CSS raus",
      ".fb-tab input[type=\"text\"]" not in css,
      "eine Regel ohne Gegenstand muss bei jeder Durchsicht mitgeprueft werden")
check("dafuer gibt es eine `.fb-tab textarea`-Regel", ".fb-tab textarea" in css)

fb.formular_loeschen(fm["id"])


print("\n" + "=" * 70)
print("\033[1mErgebnis: %d OK, %d FAIL\033[0m" % (_ok, _fail))
sys.exit(1 if _fail else 0)
