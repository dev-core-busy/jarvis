#!/usr/bin/env python3
"""Gegenproben zu tests/test_chat_bild_verlauf.py – beisst der Waechter EINZELN?

Jede Probe dreht GENAU EINE Stelle des Fixes zurueck. Gearbeitet wird auf einer
KOPIE (``CBV_ROOT``), nie im Arbeitsbaum – der Betreiber arbeitet parallel an
denselben Dateien. Gemessen wird der EXIT-CODE (1 = beisst), jede Ersetzung hat
eine Trefferkontrolle.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_chat_bild_verlauf.py"
# Alles, was der Waechter LIEST, muss in der Kopie liegen - nicht nur das,
# was eine Probe anfasst. icons.js kam am 2026-10-11 dazu: der Waechter laedt
# das ECHTE Modul (statt einer Teil-Attrappe, die beim naechsten Symbol
# stirbt) und loest es NEBEN chat.js auf, also in der Kopie. Ohne diese Zeile
# bricht schon der Basislauf ab, und keine Gegenprobe ist deutbar.
DATEIEN = ["backend/main.py", "frontend/js/chat.js", "frontend/js/icons.js"]

PROBEN = [
    ("Ablagename wird nicht herausgemeldet", "backend/main.py",
     "        ablage.append(ziel.name)\n", "        pass\n"),
    ("WS-Handler reicht ablage= nicht herein", "backend/main.py",
     "_vorh_i,\n                            ablage=_abl_i)", "_vorh_i)"),
    ("Ereignis traegt leere Liste", "backend/main.py",
     '"items": _bild_ablagen}', '"items": []}'),
    ("Endpunkt ohne Eigentuemer-Pruefung", "backend/main.py",
     "if not p.is_file() or not _documents.may_access(name, user, _is_admin_user(user)):",
     "if not p.is_file():"),
    # Diese Probe war seit e9ebf481 (Code-Review 2026-09-28) STUMPF, nicht
    # kaputt: dort wurde die Typ-Erkennung von einer ENDUNGS-Tabelle auf die
    # magischen Bytes des INHALTS umgestellt (_bild_mime_aus_kopf). Der alte
    # Anker ("bmp": "image/bmp"} + re.fullmatch) existiert seitdem nicht mehr,
    # und der Harness brach korrekt mit "Probe unbrauchbar" ab, statt stumm
    # durchzulaufen. Die ZUSAGE ist unveraendert ("nur Rastergrafik") und wird
    # jetzt am heutigen Mechanismus gemessen: SVG in die Magic-Tabelle.
    ("Endpunkt liefert SVG", "backend/main.py",
     '    (b"BM", "image/bmp"),\n',
     '    (b"BM", "image/bmp"),\n    (b"<svg", "image/svg+xml"),\n'),
    ("Endpunkt ohne nosniff", "backend/main.py",
     ',\n                                 "X-Content-Type-Options": "nosniff"}', '}'),
    ("fremde Sitzung wird beschrieben", "frontend/js/chat.js",
     "if (!entry || !_chatHistory.includes(entry) || !Array.isArray(msg.items)) return;",
     "if (!entry || !Array.isArray(msg.items)) return;"),
    ("Verlauf zeigt keine Bilder", "frontend/js/chat.js",
     "            _renderAttachments(bubble, { attachments: _atts });\n", ""),
    ("_dataUrl kennt den Verweis nicht", "frontend/js/chat.js",
     "if (!att.data && att.doc) {", "if (false) {"),
    ("Hinweis wird nie entfernt", "frontend/js/chat.js",
     "            _shownText = entry.text.slice(0, entry.text.length - entry.att_note.length);\n", ""),
    ("teilweise Verweise entfernen den Hinweis", "frontend/js/chat.js",
     "                && _atts.length === entry.att_count) {", "                ) {"),
    ("totes Bild ohne Rueckfall", "frontend/js/chat.js",
     "if (gal && !gal.querySelector('.uc-ig-cell')) bubble.textContent = entry.text;", ""),
]

# ZWEITE KATEGORIE: Proben, die KEIN FAIL erzeugen duerfen, sondern einen
# ABBRUCH mit lesbarer Begruendung (Exit 2).
#
# Der Vorfall vom 2026-10-11 war genau diese Verwechslung: der Waechter
# stuerzte ab, weil chat.js seit dem Stift-Umbau JarvisIcons.setPencil ruft
# und das Modul im Fenster fehlte. Ergebnis war Exit 2 mit der Begruendung
# "node lieferte nichts Lesbares:  s/loader:1613:10)" - also richtig
# kategorisiert, aber nicht diagnostizierbar: die Ursache liess sich nur
# finden, indem man das eingebettete Node-Skript aus der Waechterdatei
# herausloest und von Hand startet.
#
# Geprueft wird deshalb BEIDES: der Exit-Code UND dass die Begruendung das
# Problem benennt. Ein fehlendes Modul ist "konnte nicht laufen", nie ein
# Produktbefund - wer es als FAIL zaehlt, haelt einen kaputten Pruefstand
# fuer eine Messung.
#
# Eintrag: (Titel, Datei, None = Datei LOESCHEN | (alt, neu) = ersetzen,
#           Text, der in der Begruendung stehen MUSS)
ABBRUECHE = [
    ("icons.js fehlt -> Abbruch nennt den PFAD", "frontend/js/icons.js",
     None, "icons.js nicht lesbar"),
    ("JarvisIcons ohne setPencil -> Abbruch nennt den Wurf",
     "frontend/js/icons.js",
     ("        setPencil: function (el) { return setzen(el, STIFT); },\n", ""),
     "setPencil is not a function"),
]


def lauf(wurzel):
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       env={**os.environ, "CBV_ROOT": str(wurzel)}, timeout=180)
    fails = sum(1 for z in r.stdout.splitlines() if z.strip().startswith("✗"))
    return r.returncode, fails, r.stdout


def kopie():
    d = Path(tempfile.mkdtemp(prefix="gegen_cbv_"))
    for rel in DATEIEN:
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, d / rel)
    return d


# Jede Datei, die eine Probe anfasst, muss in der Kopie stehen – als Regel.
if {pr[1] for pr in PROBEN} - set(DATEIEN):
    print("ABBRUCH: Probe auf Datei ausserhalb von DATEIEN")
    sys.exit(2)

basis = kopie()
try:
    rc, _f, out = lauf(basis)
finally:
    shutil.rmtree(basis, ignore_errors=True)
if rc != 0:
    print(out[-1500:])
    print(f"ABBRUCH: Basislauf nicht gruen (exit {rc}) – keine Gegenprobe deutbar")
    sys.exit(2)
print("Basislauf gruen\n")

beissen = 0
for titel, rel, alt, neu in PROBEN:
    d = kopie()
    try:
        p = d / rel
        s = p.read_text(encoding="utf-8")
        if s.count(alt) != 1:
            print(f"  ? {titel}: Ziel {s.count(alt)}x getroffen – Probe unbrauchbar")
            sys.exit(2)
        p.write_text(s.replace(alt, neu), encoding="utf-8")
        rc, fails, _o = lauf(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    ok = rc == 1
    beissen += ok
    print(f"  {'✓' if ok else '✗'} {titel}: exit {rc}, {fails} FAIL")

print(f"\n{beissen} von {len(PROBEN)} Gegenproben beissen einzeln")

# ── Zweite Kategorie: Abbruch (Exit 2) mit LESBARER Begruendung ───────────
print("\nAbbruch-Proben (Exit 2 + Begruendung benennt die Ursache):")
abbruch_ok = 0
for titel, rel, aenderung, erwartet in ABBRUECHE:
    d = kopie()
    try:
        p = d / rel
        if aenderung is None:
            p.unlink()
        else:
            alt, neu = aenderung
            s = p.read_text(encoding="utf-8")
            if s.count(alt) != 1:
                print(f"  ? {titel}: Ziel {s.count(alt)}x getroffen – Probe unbrauchbar")
                sys.exit(2)
            p.write_text(s.replace(alt, neu), encoding="utf-8")
        rc, fails, o = lauf(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    # Exit 2 UND die Begruendung muss den Grund NENNEN. Nur der Exit-Code
    # waere zu wenig: "node lieferte nichts Lesbares: s/loader:1613:10)"
    # hatte ihn auch und war trotzdem nicht diagnostizierbar.
    grund = next((z.strip() for z in o.splitlines() if "ABBRUCH" in z), "")
    ok = rc == 2 and erwartet in grund
    abbruch_ok += ok
    print(f"  {'✓' if ok else '✗'} {titel}: exit {rc}, {fails} FAIL")
    print(f"      Begruendung: {grund or '(keine)'}")
    if not ok and erwartet not in grund:
        print(f"      ERWARTET darin: {erwartet!r}")

print(f"\n{abbruch_ok} von {len(ABBRUECHE)} Abbruch-Proben melden den Grund lesbar")
alle = beissen == len(PROBEN) and abbruch_ok == len(ABBRUECHE)
sys.exit(0 if alle else 1)
