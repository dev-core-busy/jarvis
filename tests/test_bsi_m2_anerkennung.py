#!/usr/bin/env python3
"""Waechter BSI M2: protokolliert anerkannte Brueche im Sicherheitsprotokoll.

Nachgestellt wird der Vorfall vom 21.10.2026: ein Wartungsbefehl ohne Schluessel
schrieb EINE Zeile ohne Merkmal mitten in die Kette, danach schrieb der Dienst
mit Schluessel weiter. Die Zeile entsteht hier wie damals (``_hash`` ohne
Schluessel, syslog-Kopie ohne ``prev``) – der Erzeuger baut das Material.

Gemessen wird am Verhalten, nicht am Text:
1. die nachgestellte Lage ist ein Bruch (Positivkontrolle, sonst Exit 2),
2. ``anerkennen`` mit identischer Journal-Kopie macht die Kette ``ok``, fuehrt
   die Stelle unter ``anerkannt`` und aendert KEIN vorhandenes Byte,
3. alles, was nicht nachweislich festliegt, wird abgelehnt – und zwar in
   ``anerkennen`` UND in ``pruefen`` (eine von Hand geschriebene Anerkennung
   darf ``pruefen`` nicht umstimmen),
4. die Aufbewahrungsfrist verschiebt die Zeilennummern, nicht die Anerkennung,
5. der Konsolenbefehl (Exit-Codes) und der Endpunkt (geschnitten, ausgefuehrt).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" – " + str(detail) if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


# backend.config nur als Attrappe – der echte Import schreibt die Live-settings.json
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(get_setting=lambda k, d=None: d)
sys.modules["backend.config"] = _cfg
from backend import sicherheits_log as SL  # noqa: E402

if getattr(sys.modules["backend.config"], "__file__", None):
    abbruch("echtes backend.config geladen")

SAND = Path(tempfile.mkdtemp(prefix="bsi_m2_anerk_"))
GEHEIM = "test-geheimnis-m2"
journal = []          # was nach syslog ginge (Ablage 2), als "-o cat"-Zeilen


class _Fang:
    def log(self, stufe, text):
        journal.append((stufe, text))


SL._syslog = _Fang()


class _Uhr:
    """Je Aufruf 10 s weiter – sonst stehen alle Zeilen in derselben Sekunde,
    und das Kuerzen nach Alter (Abschnitt 4) waere nicht steuerbar."""
    jetzt = 1792000000.0
    # vor "def time": im Klassenrumpf verdeckt die Methode sonst das Modul
    strftime = staticmethod(time.strftime)
    gmtime = staticmethod(time.gmtime)

    def time(self):
        _Uhr.jetzt += 10
        return _Uhr.jetzt


SL.time = _Uhr()


def frisch(name):
    """Eigener Sandkasten je Fall: Datei, Zustand des Moduls, Journal."""
    SL.DATEI = SAND / name / "sicherheit.jsonl"
    SL._letzter_hash = SL._letzte_datei = SL._letzte_groesse = None
    SL.schluessel_setzen(GEHEIM)
    SL._selbst_geladen = True
    del journal[:]
    if not str(SL.DATEI).startswith(str(SAND)):
        abbruch("Protokolldatei zeigt aus dem Sandkasten heraus")


def zeile_ohne_schluessel(art="abhaengigkeiten", **details):
    """Wie der Wartungsbefehl am 21.10.: ohne Merkmal, sha256 ohne Schluessel,
    angehaengt an das Ende, Kopie nach syslog ohne ``prev``."""
    letzte = json.loads(SL._letzte_zeile(SL.DATEI))
    jetzt = SL.time.time()
    e = {"ts": int(jetzt), "zeit": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(jetzt)),
         "art": art, "benutzer": "", "ip": "", "ergebnis": "geaendert"}
    if details:
        e["details"] = details
    e["prev"] = letzte["hash"]
    e["hash"] = SL._hash(e["prev"], e, None)
    with SL.DATEI.open("a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    journal.append((20, json.dumps({k: v for k, v in e.items() if k != "prev"},
                                   ensure_ascii=False)))
    return e


def lage(name):
    """Kette mit Merkmal, eine Zeile ohne, danach wieder mit Merkmal."""
    frisch(name)
    SL.ereignis("dienst_start", ergebnis="ok")
    SL.ereignis("anmeldung", benutzer="anna", ip="192.0.2.1", ergebnis="erfolg")
    bruch = zeile_ohne_schluessel(geaendert=["paket 1 -> 2"])
    SL.ereignis("dienst_start", ergebnis="ok")
    SL.ereignis("admin_aenderung", benutzer="anna", ip="192.0.2.1", ergebnis="200")
    return bruch


def jz():
    """Journal als "-o cat"-Zeilen (nur der Text)."""
    return [t for _, t in journal]


# ═══════════════════════════════════════════════════════════════════════════
print("[0] Positivkontrolle: die nachgestellte Lage ist ein Bruch")
bruch = lage("a")
r0 = SL.pruefen()
if r0["ok"] or [b["grund"] for b in r0["brueche"]] != ["ohne Schluessel"]:
    abbruch("Lage nicht nachgestellt: %s" % r0)
if r0["brueche"][0]["zeile"] != 3:
    abbruch("Bruch an unerwarteter Stelle: %s" % r0["brueche"])
check("Bruch an Zeile 3, Grund 'ohne Schluessel', noch nichts anerkannt",
      r0["anerkannt"] == [])
_, ohne = SL._pruefen(SL.DATEI)
k = ohne.get(bruch["hash"])
check("die Zeile liegt nachweislich fest (verbunden, Hash, gesicherte Folgezeile)",
      k is not None and SL._anerkennbar(k), k)

# ═══════════════════════════════════════════════════════════════════════════
print("[1] Anerkennen mit identischer Journal-Kopie")
vorher = SL.DATEI.read_bytes()
r1 = SL.anerkennen(bruch["hash"], grund="Wartungslauf ohne Schluessel, geklaert",
                   von="betreiber", journal_zeilen=jz())
check("anerkennen meldet Erfolg", r1.get("ok") is True, r1)
nach = SL.DATEI.read_bytes()
check("vorhandene Zeilen byte-gleich (nur angehaengt)", nach.startswith(vorher))
neu = [json.loads(z) for z in nach[len(vorher):].decode("utf-8").splitlines() if z.strip()]
check("genau EINE Zeile angehaengt", len(neu) == 1, len(neu))
a = neu[0] if neu else {}
d = a.get("details") or {}
check("Art kette_bruch_anerkannt mit Merkmal", a.get("art") == SL.ART_ANERKANNT and a.get("mac") == 1)
check("nennt Hash, Zeit, Art der Zeile, Grund und Bearbeiter",
      d.get("zeile_hash") == bruch["hash"] and d.get("zeile_zeit") == bruch["zeit"]
      and d.get("zeile_art") == "abhaengigkeiten" and d.get("grund", "").startswith("Wartungslauf")
      and a.get("benutzer") == "betreiber", a)
soll_beleg = hashlib.sha256(SL._kanonisch(
    {k2: v for k2, v in bruch.items() if k2 != "prev"}).encode("utf-8")).hexdigest()
check("Beleg ist der Hash der Journal-Kopie", d.get("beleg") == "journal:" + soll_beleg, d.get("beleg"))
r = SL.pruefen()
check("Kette danach ok", r["ok"] is True, r)
check("Stelle steht unter 'anerkannt' (Zeile, Art, Grund, von, am)",
      len(r["anerkannt"]) == 1 and r["anerkannt"][0]["zeile"] == 3
      and r["anerkannt"][0]["art"] == "abhaengigkeiten" and r["anerkannt"][0]["von"] == "betreiber"
      and r["anerkannt"][0]["am"] == a.get("zeit"), r["anerkannt"])
check("Anerkennung ging als WARNUNG nach syslog",
      any(st == 30 and SL.ART_ANERKANNT in t for st, t in journal))
r1b = SL.anerkennen(bruch["hash"], grund="nochmal", von="x", journal_zeilen=jz())
check("zweite Anerkennung derselben Zeile abgelehnt", r1b.get("ok") is False
      and "bereits" in r1b.get("fehler", ""), r1b)
SL.ereignis("anmeldung", benutzer="anna", ip="192.0.2.1", ergebnis="erfolg")
check("weitergeschrieben bleibt die Kette ok", SL.pruefen()["ok"])

# ═══════════════════════════════════════════════════════════════════════════
print("[2] Ablehnungen in anerkennen() – Datei bleibt unveraendert")


def abgelehnt(name, fall, wort):
    vorher = SL.DATEI.read_bytes()
    r = fall()
    check(name, r.get("ok") is False and wort in r.get("fehler", "")
          and SL.DATEI.read_bytes() == vorher, r)


bruch = lage("b")
abgelehnt("ohne Journal-Kopie", lambda: SL.anerkennen(
    bruch["hash"], grund="g", von="v", journal_zeilen=[]), "Journal")
anders = dict({k2: v for k2, v in bruch.items() if k2 != "prev"},
              details={"geaendert": ["paket 1 -> 3"]})
abgelehnt("Journal-Kopie mit anderem Inhalt (gleicher Hash)", lambda: SL.anerkennen(
    bruch["hash"], grund="g", von="v", journal_zeilen=[json.dumps(anders)]), "Journal")
abgelehnt("unbekannter Hash", lambda: SL.anerkennen(
    "f" * 64, grund="g", von="v", journal_zeilen=jz()), "Keine Zeile")
abgelehnt("Hash einer Zeile MIT Merkmal", lambda: SL.anerkennen(
    json.loads(SL.DATEI.read_text().splitlines()[0])["hash"], grund="g", von="v",
    journal_zeilen=jz()), "Keine Zeile")
abgelehnt("leerer Grund", lambda: SL.anerkennen(
    bruch["hash"], grund="  ", von="v", journal_zeilen=jz()), "Pflicht")
abgelehnt("leerer Bearbeiter", lambda: SL.anerkennen(
    bruch["hash"], grund="g", von="", journal_zeilen=jz()), "Pflicht")
SL._mac_schluessel = None
r = SL.anerkennen(bruch["hash"], grund="g", von="v", journal_zeilen=jz())
check("ohne Schluessel: Abbruch (nicht Ablehnung)", r.get("ok") is False and r.get("abbruch") is True, r)
SL.schluessel_setzen(GEHEIM)
check("mit Praefix 'jarvis-security:' im Journal wird die Kopie gefunden",
      SL._journal_beleg(bruch, ["jarvis-security: " + t for t in jz()]) != "")

# Letzte Zeile ohne Merkmal: keine Folgezeile, also liegt nichts fest
frisch("c")
SL.ereignis("dienst_start", ergebnis="ok")
spitze = zeile_ohne_schluessel()
abgelehnt("letzte Zeile (keine gesicherte Folgezeile)", lambda: SL.anerkennen(
    spitze["hash"], grund="g", von="v", journal_zeilen=jz()), "gesicherte Folgezeile")

# Inhalt nachtraeglich geaendert und schluessellos neu gerechnet
bruch = lage("d")
zeilen = SL.DATEI.read_text(encoding="utf-8").splitlines()
e3 = json.loads(zeilen[2])
e3["details"] = {"geaendert": ["nichts"]}
e3["hash"] = SL._hash(e3["prev"], e3, None)
zeilen[2] = json.dumps(e3, ensure_ascii=False)
SL.DATEI.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
SL._letzter_hash = None
journal.append((20, json.dumps({k2: v for k2, v in e3.items() if k2 != "prev"})))
abgelehnt("geaenderter Inhalt (Folgezeile bricht)", lambda: SL.anerkennen(
    e3["hash"], grund="g", von="v", journal_zeilen=jz()), "gesicherte Folgezeile")

# Inhalt geaendert, alter Hash behalten: Folgezeile passt weiter, Inhalt ist frei
bruch = lage("o")
roh = SL.DATEI.read_text(encoding="utf-8").splitlines()
e3 = json.loads(roh[2])
e3["details"] = {"geaendert": ["paket 1 -> 9"]}
roh[2] = json.dumps(e3, ensure_ascii=False)
SL.DATEI.write_text("\n".join(roh) + "\n", encoding="utf-8")
journal.append((20, json.dumps({k2: v for k2, v in e3.items() if k2 != "prev"})))
abgelehnt("geaenderter Inhalt mit altem Hash (Folgezeile passt noch)", lambda: SL.anerkennen(
    bruch["hash"], grund="g", von="v", journal_zeilen=jz()), "eigener Hash")

# Vorzeile entfernt: die Bruchzeile haengt an nichts mehr
bruch = lage("p")
roh = SL.DATEI.read_text(encoding="utf-8").splitlines()
del roh[1]
SL.DATEI.write_text("\n".join(roh) + "\n", encoding="utf-8")
abgelehnt("Vorzeile entfernt (kein Verweis auf die Zeile davor)", lambda: SL.anerkennen(
    bruch["hash"], grund="g", von="v", journal_zeilen=jz()), "Verweis auf die Zeile davor")

# Eingeschoben: wer Schreibrecht hat, setzt eine eigene Zeile ohne Merkmal VOR die
# echte und schickt eine Kopie nach syslog (das darf der Dienstbenutzer) – sie
# haengt an der Vorzeile, aber die echte Zeile haengt nicht an ihr
bruch = lage("q")
roh = SL.DATEI.read_text(encoding="utf-8").splitlines()
vor = json.loads(roh[1])
x = {"ts": vor["ts"] + 1, "zeit": vor["zeit"], "art": "anmeldung", "benutzer": "mallory", "ip": "",
     "ergebnis": "erfolg", "prev": vor["hash"]}
x["hash"] = SL._hash(x["prev"], x, None)
roh.insert(2, json.dumps(x, ensure_ascii=False))
SL.DATEI.write_text("\n".join(roh) + "\n", encoding="utf-8")
journal.append((20, json.dumps({k2: v for k2, v in x.items() if k2 != "prev"})))
abgelehnt("eingeschobene Zeile vor der echten (Journal-Kopie gefaelscht)", lambda: SL.anerkennen(
    x["hash"], grund="g", von="v", journal_zeilen=jz()), "gesicherte Folgezeile")

# Zwei Zeilen ohne Merkmal hintereinander (DEV 21.10.2026)
def lage_zwei(name):
    frisch(name)
    SL.ereignis("dienst_start", ergebnis="ok")
    z1 = zeile_ohne_schluessel(geaendert=["a 1 -> 2"])
    z2 = zeile_ohne_schluessel(geaendert=["b 1 -> 2"])
    SL.ereignis("dienst_start", ergebnis="ok")
    return z1, z2


z1, z2 = lage_zwei("l")
r = SL.pruefen()
check("Positivkontrolle Folge: zwei Brueche 'ohne Schluessel' (Zeilen 2, 3)",
      [(b["zeile"], b["grund"]) for b in r["brueche"]] == [(2, "ohne Schluessel"), (3, "ohne Schluessel")], r)
r1 = SL.anerkennen(z1["hash"], grund="g", von="v", journal_zeilen=jz())
check("erste Zeile der Folge anerkennbar (gebunden ueber die zweite)", r1.get("ok") is True, r1)
r = SL.pruefen()
check("mit nur einer Anerkennung bleibt die zweite ein Bruch",
      not r["ok"] and [b["zeile"] for b in r["brueche"]] == [3], r)
r2 = SL.anerkennen(z2["hash"], grund="g", von="v", journal_zeilen=jz())
check("beide anerkannt: Kette ok", r2.get("ok") is True and SL.pruefen()["ok"], r2)

z1, z2 = lage_zwei("m")
roh = SL.DATEI.read_text(encoding="utf-8").splitlines()
e2 = json.loads(roh[2])
# zweites Glied geaendert, alter Hash behalten: die gesicherte Zeile danach
# passt weiter, aber der Inhalt des Glieds (samt Verweis auf das erste) ist frei
e2["details"] = {"geaendert": ["b 1 -> 9"]}
roh[2] = json.dumps(e2, ensure_ascii=False)
SL.DATEI.write_text("\n".join(roh) + "\n", encoding="utf-8")
r = SL.pruefen()
if [(b["zeile"], b["grund"]) for b in r["brueche"]] != [(2, "ohne Schluessel"), (3, "ohne Schluessel"),
                                                         (3, "Inhalt veraendert")]:
    abbruch("Lage 'Glied geaendert, Hash behalten' nicht nachgestellt: %s" % r["brueche"])
abgelehnt("Folge mit geaendertem zweiten Glied: erstes Glied nicht gebunden",
          lambda: SL.anerkennen(z1["hash"], grund="g", von="v", journal_zeilen=jz()),
          "gesicherte Folgezeile")

z1, z2 = lage_zwei("n")
roh = SL.DATEI.read_text(encoding="utf-8").splitlines()
e2 = json.loads(roh[2])
e2["prev"] = "a" * 64                  # Verkettung innerhalb der Folge gerissen
e2["hash"] = SL._hash(e2["prev"], e2, None)
roh[2] = json.dumps(e2, ensure_ascii=False)
SL.DATEI.write_text("\n".join(roh) + "\n", encoding="utf-8")
abgelehnt("Folge mit gerissener Verkettung: erstes Glied nicht gebunden",
          lambda: SL.anerkennen(z1["hash"], grund="g", von="v", journal_zeilen=jz()),
          "gesicherte Folgezeile")

# ═══════════════════════════════════════════════════════════════════════════
print("[3] pruefen() laesst sich nicht an anerkennen() vorbei umstimmen")
# a) Anerkennung MIT Merkmal fuer die geaenderte Zeile, direkt geschrieben
SL.ereignis(SL.ART_ANERKANNT, benutzer="x", ergebnis="anerkannt", zeile_hash=e3["hash"], grund="g")
r = SL.pruefen()
check("geaenderte Zeile bleibt Bruch trotz Anerkennungs-Zeile",
      not r["ok"] and not r["anerkannt"]
      and {b["grund"] for b in r["brueche"]} >= {"ohne Schluessel", "Kette unterbrochen"}, r)

# b) von Hand geschriebene Anerkennung OHNE Merkmal (wer nur Schreibrecht hat)
bruch = lage("e")
letzte = json.loads(SL._letzte_zeile(SL.DATEI))
gefaelscht = {"ts": int(time.time()), "zeit": "2026-10-29T00:00:00Z", "art": SL.ART_ANERKANNT,
              "benutzer": "x", "ip": "", "ergebnis": "anerkannt",
              "details": {"zeile_hash": bruch["hash"], "grund": "g"}, "prev": letzte["hash"]}
gefaelscht["hash"] = SL._hash(gefaelscht["prev"], gefaelscht, None)
with SL.DATEI.open("a", encoding="utf-8") as f:
    f.write(json.dumps(gefaelscht) + "\n")
r = SL.pruefen()
check("Anerkennung ohne Merkmal zaehlt nicht", not r["ok"] and not r["anerkannt"], r)

# c) Anerkennung mit FALSCHEM Schluessel (anderer Server, anderes Geheimnis)
bruch = lage("f")
SL.schluessel_setzen("fremder-schluessel")
SL.ereignis(SL.ART_ANERKANNT, benutzer="x", ergebnis="anerkannt", zeile_hash=bruch["hash"], grund="g")
SL.schluessel_setzen(GEHEIM)
r = SL.pruefen()
check("Anerkennung mit fremdem Schluessel zaehlt nicht", not r["ok"] and not r["anerkannt"]
      and any(b["grund"] == "Inhalt veraendert" for b in r["brueche"]), r)

# d) Anerkennung, deren eigene Verbindung zur Vorzeile fehlt (eingeschoben)
bruch = lage("g")
SL.ereignis(SL.ART_ANERKANNT, benutzer="x", ergebnis="anerkannt", zeile_hash=bruch["hash"], grund="g")
zeilen = SL.DATEI.read_text(encoding="utf-8").splitlines()
del zeilen[-2]                         # Vorzeile der Anerkennung entfernt
SL.DATEI.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
r = SL.pruefen()
check("Anerkennung ohne Verbindung zur Vorzeile zaehlt nicht",
      not r["anerkannt"] and any(b["grund"] == "ohne Schluessel" for b in r["brueche"]), r)

# e) ohne Schluessel prueft nichts als anerkannt
bruch = lage("h")
SL.anerkennen(bruch["hash"], grund="g", von="v", journal_zeilen=jz())
SL._mac_schluessel = None
r = SL.pruefen()
check("ohne Schluessel: nichts anerkannt, nicht ok", not r["ok"] and not r["anerkannt"], r)
SL.schluessel_setzen(GEHEIM)
check("mit Schluessel: dieselbe Datei ok", SL.pruefen()["ok"])

# ═══════════════════════════════════════════════════════════════════════════
print("[4] Aufbewahrungsfrist: Nummern wandern, Anerkennung bleibt")
bruch = lage("i")
ok = SL.anerkennen(bruch["hash"], grund="g", von="v", journal_zeilen=jz()).get("ok")
zeilen = [json.loads(z) for z in SL.DATEI.read_text().splitlines()]
weg = SL.prune_older_than(zeilen[1]["ts"])          # nur Zeile 1 ist aelter
r = SL.pruefen()
check("Positivkontrolle: genau eine Zeile vorne abgeschnitten, Anerkennung lag vor",
      ok and weg == 1, (ok, weg))
check("nach dem Kuerzen ok, Stelle jetzt unter Zeile 2 anerkannt",
      r["ok"] and [x["zeile"] for x in r["anerkannt"]] == [2], r)
weg2 = SL.prune_older_than(zeilen[3]["ts"])         # Bruchzeile (3) faellt mit
r = SL.pruefen()
check("Bruchzeile selbst weggekuerzt: ok, verwaiste Anerkennung stoert nicht",
      weg2 == 2 and r["ok"] and r["anerkannt"] == [], (weg2, r))

# ═══════════════════════════════════════════════════════════════════════════
print("[5] Konsolenbefehl")
WURZEL = SAND / "cli"
(WURZEL / "data" / "logs").mkdir(parents=True)
bruch = lage("j")
shutil.copy(SL.DATEI, WURZEL / "data" / "logs" / "sicherheit.jsonl")
umg = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1", SECRET_KEY=GEHEIM,
           JARVIS_SICHERHEITS_LOG_TAGE="0")
# Das Modul schreibt an das ABSOLUTE /dev/log – ein Sandkasten-Verzeichnis
# haelt den Befehl davon nicht ab (erster Lauf 2026-10-29: eine Testzeile im
# Journal des Pruefrechners). Deshalb laeuft der Befehl ueber einen Vorlader,
# der den syslog-Handler stumm schaltet; alles andere ist der echte __main__-Zweig.
VORLADER = SAND / "vorlader.py"
VORLADER.write_text(
    "import logging, logging.handlers, runpy\n"
    "class _Stumm(logging.Handler):\n"
    "    LOG_AUTHPRIV = 10\n"
    "    priority_map = {}\n"
    "    def __init__(self, *a, **k):\n"
    "        super().__init__()\n"
    "    def emit(self, record):\n"
    "        pass\n"
    "logging.handlers.SysLogHandler = _Stumm\n"
    "runpy.run_module('backend.sicherheits_log', run_name='__main__', alter_sys=True)\n",
    encoding="utf-8")
cmd = [sys.executable, str(VORLADER), "anerkennen", "--hash", bruch["hash"],
       "--grund", "geklaert $& {v}", "--von", "betreiber"]


def befehl(stdin, env=umg, args=cmd):
    return subprocess.run(args, input=stdin, capture_output=True, text=True, cwd=str(WURZEL),
                          env=env, timeout=60)


p = befehl("\n".join(jz()) + "\n", env=dict(umg, SECRET_KEY=""))
check("ohne Schluessel: Exit 2", p.returncode == 2, (p.returncode, p.stdout[-300:], p.stderr[-300:]))
p = befehl("")
check("ohne Journal-Kopie: Exit 1", p.returncode == 1 and "Journal" in p.stdout, (p.returncode, p.stdout[-300:]))
p = befehl("\n".join(jz()) + "\n")
check("mit Journal-Kopie: Exit 0", p.returncode == 0, (p.returncode, p.stdout[-400:], p.stderr[-400:]))
p2 = subprocess.run([sys.executable, str(VORLADER), "pruefen"], capture_output=True,
                    text=True, cwd=str(WURZEL), env=umg, timeout=60)
try:
    r = json.loads(p2.stdout)
except Exception:  # noqa: BLE001
    r = {}
check("pruefen danach: Exit 0, Stelle anerkannt",
      p2.returncode == 0 and r.get("ok") is True and len(r.get("anerkannt") or []) == 1,
      (p2.returncode, p2.stdout[-300:]))
check("Freitext im Grund bleibt woertlich", (r.get("anerkannt") or [{}])[0].get("grund") == "geklaert $& {v}")

# ═══════════════════════════════════════════════════════════════════════════
print("[6] Endpunkt /api/security/log liefert die Anerkennung mit")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
fn = next((n for n in ast.parse(MAIN).body if isinstance(n, ast.AsyncFunctionDef)
           and n.name == "sicherheitsprotokoll_lesen"), None)
if fn is None:
    abbruch("Endpunkt-Funktion fehlt in main.py")


class JSONResponse:
    def __init__(self, content, status_code=200, **_kw):
        self.inhalt = content


fn.decorator_list = []
ns = {"JSONResponse": JSONResponse, "asyncio": asyncio, "_sicherheits_log": SL,
      "Depends": lambda f: None, "require_local_auth": None, "_display_name": lambda u: u}
exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), "main.py", "exec"), ns)
bruch = lage("k")
SL.anerkennen(bruch["hash"], grund="geklaert", von="betreiber", journal_zeilen=jz())
k = asyncio.run(ns["sicherheitsprotokoll_lesen"](limit=200, art="", benutzer="", ip="", _u="a")).inhalt["kette"]
check("kette.ok, anzahl_anerkannt 1, Eintrag mit Grund und Bearbeiter",
      k.get("ok") is True and k.get("anzahl_anerkannt") == 1
      and (k.get("anerkannt") or [{}])[0].get("von") == "betreiber"
      and (k.get("anerkannt") or [{}])[0].get("grund") == "geklaert", k)

shutil.rmtree(SAND, ignore_errors=True)
print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
