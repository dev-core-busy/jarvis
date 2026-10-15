#!/usr/bin/env python3
"""Gegenprobe zu den HOCH-Befunden aus dem Code-Review 2026-10-07.

Je Probe wird EINE Schranke zurueckgedreht und das erwartete Urteil des
zustaendigen Waechters verlangt (Exit 1):

  * i18n: fehlende Schluessel / falscher Abmelde-Schluessel   -> test_i18n_schluessel.js
  * Destillat-Markdown: Bild wieder vor der Linkregel offen  -> test_wissen_destillat_ui.js
  * Freigabekarte: "nicht gesendet" wird verschluckt          -> test_bsi_h9_ui.js
  * Broker-Freigabecode: Sperre / Grenze / Wiederholschutz    -> test_broker_k1k2.py
  * Abruf-Schluessel: Einschraenkung der Sitzung geht verloren -> test_download_key.py
  * Confluence: leere Seitenliste loescht den Bestand         -> test_cf_abgleich.py

Ablauf wie gegen_broker_review.py (gruene Basis, Sicherung im HOME, Laufmarke,
md5, ohne Bytecode, SIGTERM/SIGINT ueber ``finally``).
NICHT in einem Sammellauf ueber ``tests/*`` mitlaufen lassen – patcht den Baum.

Exit 0 = alle Proben wie erwartet, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
import hashlib
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
PY = Path(WURZEL / "venv" / "bin" / "python")
PY = str(PY) if PY.is_file() else sys.executable
W_I18N = ["node", str(WURZEL / "tests" / "test_i18n_schluessel.js")]
W_MD = ["node", str(WURZEL / "tests" / "test_wissen_destillat_ui.js")]
W_H9 = ["node", str(WURZEL / "tests" / "test_bsi_h9_ui.js")]
W_K12 = [PY, str(WURZEL / "tests" / "test_broker_k1k2.py")]
W_DLK = [PY, str(WURZEL / "tests" / "test_download_key.py")]
W_CFA = [PY, str(WURZEL / "tests" / "test_cf_abgleich.py")]
WAECHTER_ALLE = [W_I18N, W_MD, W_H9, W_K12, W_DLK, W_CFA]
SICHERUNG = Path.home() / ".gegen_review_hoch"
MARKE = SICHERUNG / "laeuft"

I18N = "frontend/js/i18n.js"
AM = "frontend/ai_mouse.html"
WD = "frontend/js/wissen_destillat.js"
BEST = "frontend/js/bestaetigung.js"
CHAT = "frontend/js/chat.js"
FG = "backend/broker/freigabe.py"
DK = "backend/download_key.py"
MAIN = "backend/main.py"
CFA = "backend/confluence_abgleich.py"
ERFASST = [I18N, AM, WD, BEST, CHAT, FG, DK, MAIN, CFA]

PROBEN = [
    ("i18n: ext.saving (DE) fehlt wieder", I18N,
     "        'ext.saving': 'Speichere …',\n", "", W_I18N),
    ("i18n: Abmelde-Knopf wieder auf nav.logout", AM,
     'data-i18n-title="chat.logout"', 'data-i18n-title="nav.logout"', W_I18N),
    ("Destillat: Bild wieder direkt ins Markup (Linkregel greift ins alt)", WD,
     "                bilder.push('<img src=\"' + url + '\" alt=\"' + alt + '\">');\n"
     "                return '\\u0000BILD' + (bli++) + '\\u0000';\n",
     "                return '<img src=\"' + url + '\" alt=\"' + alt + '\">';\n", W_MD),
    ("Karte: nicht gesendete Antwort wird verschluckt", BEST,
     "            if (gesendet === false) {\n", "            if (false) {\n", W_H9),
    ("chat.js: wsSend meldet einen geschlossenen Socket nicht", CHAT,
     "        if (!ws || ws.readyState !== 1) return false;\n",
     "        if (!ws || ws.readyState !== 1) return;\n", W_H9),
    ("Freigabecode: Sperre wird nicht beachtet", FG,
     "        if z[\"gesperrt_bis\"] > t:\n", "        if False:\n", W_K12),
    ("Freigabecode: Fehlversuche sperren nie", FG,
     "        gesperrt_bis = t + SPERRE_S if fehl >= FEHL_MAX else 0\n",
     "        gesperrt_bis = 0\n", W_K12),
    ("Freigabecode: Pruefen+Merken ohne Sperre (Wettlauf)", FG,
     "    with _SPERRE:\n", "    if True:\n", W_K12),
    ("Abruf-Schluessel: Art wird beim Pruefen ignoriert", DK,
     "        return user, art != \"v\"\n", "        return user, False\n", W_DLK),
    ("Abruf-Schluessel: alte Form gilt als VOLL", DK,
     "        return user, art != \"v\"\n", "        return user, art == \"e\"\n", W_DLK),
    ("Abruf-Schluessel: Einloesen setzt keinen Sitzungskontext", MAIN,
     "            _sitzung_kontext.set((_norm_login(name), not eingeschraenkt, eingeschraenkt))\n",
     "            pass\n", W_DLK),
    ("Abruf-Schluessel: Ausstellen ohne Einschraenkung", MAIN,
     "        key, exp = _dlkey.erzeugen(user, eingeschraenkt=_sitzung_ohne_admin(user))\n",
     "        key, exp = _dlkey.erzeugen(user)\n", W_DLK),
    ("Confluence: leere Liste loescht wieder den Bestand", CFA,
     "            if not liste and any((a.get(\"space\") or \"\") == key for a in seiten_alt.values()):\n",
     "            if False:\n", W_CFA),
]
DATEIEN = sorted({p[1] for p in PROBEN})

_ok = _fail = 0


def pruefe(bed, text, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  ok   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  -> " + detail) if detail else ""))


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf(cmd):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    e = subprocess.run(cmd, cwd=WURZEL, capture_output=True, text=True, timeout=300, env=env)
    return e.returncode, e.stdout + e.stderr


def zurueck():
    for rel in DATEIEN:
        s = SICHERUNG / rel.replace("/", "__")
        if s.is_file():
            shutil.copyfile(s, WURZEL / rel)


def _signal(signum, _frame):
    raise SystemExit(128 + signum)


if set(DATEIEN) - set(ERFASST):
    print("ABBRUCH (Exit 2): Proben fassen ungesicherte Dateien an: %s"
          % sorted(set(DATEIEN) - set(ERFASST)))
    sys.exit(2)

if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs gefunden – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()

for cmd in WAECHTER_ALLE:
    rc, aus = lauf(cmd)
    if rc != 0:
        print("ABBRUCH (Exit 2): Basislauf %s nicht gruen (Exit %d)." % (Path(cmd[-1]).name, rc))
        print(aus[-1500:])
        sys.exit(2)
print("Basislauf aller Waechter gruen.\n")

SICHERUNG.mkdir(mode=0o700, exist_ok=True)
for rel in DATEIEN:
    shutil.copyfile(WURZEL / rel, SICHERUNG / rel.replace("/", "__"))
soll = {rel: md5(WURZEL / rel) for rel in DATEIEN}
MARKE.write_text("laeuft", encoding="utf-8")
signal.signal(signal.SIGTERM, _signal)
signal.signal(signal.SIGINT, _signal)
try:
    for probe in PROBEN:
        if isinstance(probe[2], list):
            name, rel, schritte, waechter, erwartet = probe
        else:
            name, rel, alt, neu, waechter = probe
            schritte, erwartet = [(alt, neu)], 1
        pfad = WURZEL / rel
        quelle = pfad.read_text(encoding="utf-8")
        treffer = [quelle.count(a) for a, _n in schritte]
        if treffer != [1] * len(schritte):
            pruefe(False, "%s -> Anker eindeutig" % name, "Treffer %s" % treffer)
            continue
        for a, n in schritte:
            quelle = quelle.replace(a, n)
        pfad.write_text(quelle, encoding="utf-8")
        rc, _aus = lauf(waechter)
        pruefe(rc == erwartet, "%s -> %s Exit %d" % (name, Path(waechter[-1]).name, erwartet),
               "Exit %d" % rc)
        zurueck()
        pruefe(md5(pfad) == soll[rel], "%s -> Datei byte-gleich zurueck" % name)
finally:
    zurueck()
    MARKE.unlink(missing_ok=True)

for rel in DATEIEN:
    pruefe(md5(WURZEL / rel) == soll[rel], "%s unveraendert" % rel)
for cmd in WAECHTER_ALLE:
    rc, _ = lauf(cmd)
    pruefe(rc == 0, "Abschlusslauf %s gruen" % Path(cmd[-1]).name, "Exit %d" % rc)
shutil.rmtree(SICHERUNG, ignore_errors=True)

print("\n" + "=" * 70)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
