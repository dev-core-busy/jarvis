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
check("die Freigabe ist „leer = niemand“",
      "feedback_allowed_users" in QUELLE and "feedback_allowed_group" in QUELLE)

# `_user_may_use_feedback` wirklich ausfuehren: leer muss `False` ergeben.
weiche = None
for k in ast.walk(BAUM):
    if isinstance(k, ast.FunctionDef) and k.name == "_user_may_use_feedback":
        weiche = k
check("der Rechte-Helfer existiert", weiche is not None)
if weiche is not None:
    ns = {"config": type("C", (), {"get_setting": staticmethod(lambda k, d="": "")})(),
          "_norm_login": lambda x: x.lower(),
          "_member_of_any_group": lambda a, b: False,
          "_user_group_dns_cache": {}}
    exec(compile(ast.Module(body=[weiche], type_ignores=[]), "<w>", "exec"), ns)
    f_ = ns["_user_may_use_feedback"]
    check("⚠ leere Freigabe heisst NIEMAND – auch kein Administrator",
          f_("irgendwer") is False)
    ns["config"] = type("C", (), {"get_setting": staticmethod(
        lambda k, d="": "anna,bert" if k == "feedback_allowed_users" else "")})()
    exec(compile(ast.Module(body=[weiche], type_ignores=[]), "<w>", "exec"), ns)
    f_ = ns["_user_may_use_feedback"]
    check("ein eingetragener Benutzer darf (Positivkontrolle)", f_("anna") is True)
    check("ein nicht eingetragener nicht", f_("carla") is False)

FRONT = ROOT / "frontend"
check("die Portal-Kachel steht im Markup",
      'id="pt-card-feedback"' in (FRONT / "portal.html").read_text(encoding="utf-8"))
check("und wird an `permissions.feedback` eingeblendet",
      "permissions.feedback" in (FRONT / "portal.html").read_text(encoding="utf-8"))
st = (FRONT / "settings.html").read_text(encoding="utf-8")
check("der Reiter-Knopf steht im Markup", 'id="settings-tab-btn-feedback"' in st)
check("und sein Panel auch", 'id="settings-tab-feedback"' in st)
check("der Freigabe-Block steht im Sicherheits-Reiter", 'id="sec-sub-feedback"' in st)
check("der Freigabe-Block beschreibt FEEDBACK, nicht AI-Maus",
      "Bildschirmausschnitt" not in st.split('id="sec-sub-feedback"')[1].split("</details>")[0],
      "ein Text, der etwas anderes beschreibt, ist eine Falschaussage")

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
check("app.js blendet den Sicherheits-Block ein", "sec-sub-feedback" in app_js)
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


print("\n" + "=" * 70)
print("\033[1mErgebnis: %d OK, %d FAIL\033[0m" % (_ok, _fail))
sys.exit(1 if _fail else 0)
