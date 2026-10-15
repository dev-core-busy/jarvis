#!/usr/bin/env python3
"""Waechter: ein abgewiesener Datei-Abruf hinterlaesst eine Zeile – MIT Grund.

WARUM ES DAS GIBT (bezahlt am 2026-10-01 auf ECHT): ein Download-Chip im Chat
trug wegen eines Frontend-Fehlers gar kein ``?token=``. Der Server antwortete
401, der Browser machte daraus die Frage nach Benutzername und Kennwort – und
im Journal stand ueber DREI TAGE keine einzige Zeile dazu. Die Suche lief
deshalb erst ueber die Eigentuemer-Registry (protokolliert), den Alt-Weg
(protokolliert) und die Loopback-Sperre, bevor der haeufigste Fall uebrig blieb:
der, der nichts schreibt. „Nichts passiert" und „jeder Abruf scheitert" sahen
im Journal identisch aus.

GEMESSEN WIRD DIE EIGENSCHAFT AM SYNTAXBAUM, nicht das Vorkommen einer Zeile:
jedes ``raise HTTPException(401)`` in den beiden Abruf-Dependencies muss die
Protokollzeile VOR sich haben. Damit faellt auch ein kuenftiger dritter
Rueckgabe-Pfad auf, ohne dass jemand eine Liste pflegt.

Dazu wird ``download_key.grund()`` WIRKLICH AUSGEFUEHRT – ob der Grund den
naechsten Schritt nennt (und ob er den Schluessel verschweigt), kann eine
Quelltext-Pruefung nicht beantworten.

Aufruf: python3 tests/test_abruf_401_protokoll.py
Exit 0 = gruen · 1 = Waechter beisst · 2 = konnte nicht laufen
"""
import ast
import base64
import hashlib
import hmac
import importlib.util
import os
import sys
import time
import types

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(WURZEL, "backend", "main.py")
DLKEY = os.path.join(WURZEL, "backend", "download_key.py")

PROT = "_prot_abruf_abgewiesen"
DEPENDENCIES = ("require_auth_or_query", "require_admin_or_query")

ok = fail = 0


def check(text, bed, detail=""):
    global ok, fail
    if not isinstance(bed, bool):
        print("ABBRUCH: check(Text, Bedingung) – Argumente vertauscht: %s" % text)
        sys.exit(2)
    if bed:
        ok += 1
        print("  \033[32m✓\033[0m %s" % text)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (text, (" – " + detail) if detail else ""))


def abbruch(grund):
    print("\033[31mABBRUCH (Exit 2): %s\033[0m" % grund)
    print("Exit 2 = konnte nicht laufen – weder bestanden noch fehlgeschlagen.")
    sys.exit(2)


# ── Grundlage ────────────────────────────────────────────────────────────
print("\n\033[1m1. Grundlage\033[0m")
try:
    QUELLE = open(MAIN, encoding="utf-8").read()
    BAUM = ast.parse(QUELLE)
except Exception as e:  # noqa: BLE001
    abbruch("backend/main.py nicht lesbar/parsebar: %s" % e)

funktionen = {}
for knoten in ast.walk(BAUM):
    if isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)):
        funktionen.setdefault(knoten.name, []).append(knoten)

for name in DEPENDENCIES + (PROT,):
    if name not in funktionen:
        abbruch("%s existiert nicht in main.py – die Regel haette keinen Gegenstand." % name)
    if len(funktionen[name]) != 1:
        abbruch("%s steht %d mal in main.py – der Schnitt waere nicht eindeutig."
                % (name, len(funktionen[name])))
check("main.py parst, alle drei Funktionen sind eindeutig vorhanden", True)


def raise_401(fn):
    """Alle ``raise HTTPException(status_code=401, ...)`` einer Funktion."""
    treffer = []
    for k in ast.walk(fn):
        if not isinstance(k, ast.Raise) or not isinstance(k.exc, ast.Call):
            continue
        name = getattr(k.exc.func, "id", getattr(k.exc.func, "attr", ""))
        if name != "HTTPException":
            continue
        for kw in k.exc.keywords:
            if kw.arg == "status_code" and isinstance(kw.value, ast.Constant) \
                    and kw.value.value == 401:
                treffer.append(k)
    return treffer


# Positivkontrolle: es MUSS 401-Stellen geben, sonst ist die Regel trivial wahr.
alle_401 = {n: raise_401(funktionen[n][0]) for n in DEPENDENCIES}
gesamt = sum(len(v) for v in alle_401.values())
if gesamt == 0:
    abbruch("kein einziges raise HTTPException(401) in den Dependencies gefunden – "
            "die Regel waere trivial erfuellt (Funktion umgebaut?).")
check("%d Stelle(n) mit 401 gefunden (Positivkontrolle)" % gesamt, True)


# ── Die Regel ────────────────────────────────────────────────────────────
print("\n\033[1m2. Jeder 401 wird protokolliert\033[0m")


def prot_zeilen(fn):
    """Zeilennummern der Aufrufe von _prot_abruf_abgewiesen in dieser Funktion."""
    zeilen = []
    for k in ast.walk(fn):
        if isinstance(k, ast.Call):
            name = getattr(k.func, "id", getattr(k.func, "attr", ""))
            if name == PROT:
                zeilen.append(k.lineno)
    return zeilen


for name in DEPENDENCIES:
    fn = funktionen[name][0]
    prot = prot_zeilen(fn)
    check("%s: ruft %s ueberhaupt" % (name, PROT), len(prot) > 0)
    for r in alle_401[name]:
        davor = [z for z in prot if z < r.lineno]
        check("%s: der 401 in Zeile %d hat die Protokollzeile davor"
              % (name, r.lineno), len(davor) > 0,
              "Protokoll-Aufrufe in Zeilen %s" % (prot or "keine"))


# ── Der Grund wird AUSGEFUEHRT ───────────────────────────────────────────
print("\n\033[1m3. Der Grund nennt die Ursache (ausgefuehrt)\033[0m")

# backend.config NUR als Attrappe – der echte Import schreibt die Live-
# settings.json zurueck (Register). Die Attrappe bildet die benutzte
# Schnittstelle nach: SECRET_KEY und get_setting(name, vorgabe).
GEHEIM = "waechter-geheimnis"
stub = types.ModuleType("backend.config")


class _Config:
    SECRET_KEY = GEHEIM

    def get_setting(self, name, vorgabe=None):
        return vorgabe


stub.config = _Config()
sys.modules["backend.config"] = stub
if "backend" not in sys.modules:
    pkg = types.ModuleType("backend")
    pkg.__path__ = [os.path.join(WURZEL, "backend")]
    sys.modules["backend"] = pkg

spec = importlib.util.spec_from_file_location("backend.download_key", DLKEY)
dk = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(dk)
except Exception as e:  # noqa: BLE001
    abbruch("download_key.py nicht ladbar: %s" % e)

if not hasattr(dk, "grund"):
    abbruch("download_key.grund() fehlt – Punkt 3 des Fixes ist nicht da.")


def schluessel(user, exp):
    b = base64.urlsafe_b64encode(user.encode()).decode().rstrip("=")
    sig = hmac.new(GEHEIM.encode(), f"jdl1:{user}:{exp}".encode(),
                   hashlib.sha256).hexdigest()
    return f"JDL1.{b}.{exp}.{sig}"


JETZT = int(time.time())
GUELTIG = schluessel("m.mustermann", JETZT + 600)

# Positivkontrolle ZUERST: nimmt das Modul einen gueltigen Schluessel an?
# Ohne sie waeren alle Abweisungs-Pruefungen trivial wahr.
if dk.pruefen(GUELTIG) != "m.mustermann":
    abbruch("ein gueltiger Abruf-Schluessel wird nicht angenommen – "
            "die Attrappe passt nicht zum Modul, keine Aussage moeglich.")
check("Positivkontrolle: ein gueltiger Schluessel wird angenommen", True)

# Die vier Lagen, die im Journal unterscheidbar sein MUESSEN. Geprueft wird
# nicht der Wortlaut, sondern dass sie sich voneinander unterscheiden und die
# Lage benennen – ein Wortlaut-Test waere bei der naechsten Umformulierung rot.
lagen = {
    "kein Token": "",
    "Sitzungstoken": "m.mustermann:1790000000:abcdef",
    "abgelaufen": schluessel("m.mustermann", JETZT - 600),
    "Signatur": GUELTIG[:-4] + "0000",
}
gruende = {}
for lage, wert in lagen.items():
    try:
        gruende[lage] = dk.grund(wert)
    except Exception as e:  # noqa: BLE001
        gruende[lage] = "<wirft: %s>" % e
    check("Lage '%s' ergibt einen Grund (%s)" % (lage, gruende[lage]),
          isinstance(gruende[lage], str) and len(gruende[lage]) > 5)

check("alle vier Lagen sind unterscheidbar", len(set(gruende.values())) == 4,
      repr(gruende))
check("der Grund 'kein Token' nennt die Adresse",
      "Adresse" in gruende["kein Token"], gruende["kein Token"])
check("der Grund 'abgelaufen' nennt die Laufzeit",
      "abgelaufen" in gruende["abgelaufen"] and "min" in gruende["abgelaufen"],
      gruende["abgelaufen"])

# ── Der Schluessel selbst darf NIE ins Protokoll ─────────────────────────
print("\n\033[1m4. Das Zugangsmerkmal bleibt aus dem Protokoll\033[0m")
for lage, wert in lagen.items():
    if not wert:
        continue
    check("Lage '%s': der Grund enthaelt den Wert NICHT" % lage,
          wert not in gruende[lage], gruende[lage])
    # Auch kein nennenswertes Teilstueck (die Signatur ist das Geheimnis)
    check("Lage '%s': auch kein Teilstueck ab 12 Zeichen" % lage,
          not any(wert[i:i + 12] in gruende[lage]
                  for i in range(0, max(1, len(wert) - 12))),
          gruende[lage])

# ── Bilanz ───────────────────────────────────────────────────────────────
print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
