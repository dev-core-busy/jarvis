#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_m2_anerkennung.py (+ UI-Teil in
tests/test_sicherheitsprotokoll_ui.js): beisst der Waechter?

Jede Probe dreht EINE Zusage der Anerkennung zurueck (Python-Ersetzung ganzer
Zeilen), laesst die Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5, ohne Bytecode,
mit Laufmarke (abgeschossener Lauf wird beim naechsten Start zurueckgenommen).

Bewusst NICHT als Probe: "jeder Bruchgrund einer anerkannten Zeile faellt weg"
(``if b["grund"] == "ohne Schluessel"`` entfernt). Eine anerkennbare Zeile ist
verbunden und hat einen passenden Hash, kann also keinen anderen Bruch tragen –
die Sabotage ist verhaltensgleich, kein blinder Waechter.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKE = ROOT / "tests" / ".gegen_bsi_m2_anerkennung.laufmarke"

SL = "backend/sicherheits_log.py"
MA = "backend/main.py"
JS = "frontend/js/sicherheitsprotokoll.js"

PROBEN = [
    # ── was "festliegt" heisst ──
    ("ohne gesicherte Folgezeile anerkennbar", SL,
     '    return bool(k["verbunden"] and k["umschlossen"])\n',
     '    return bool(k["verbunden"])\n'),
    ("ohne Verweis auf die Vorzeile anerkennbar", SL,
     '    return bool(k["verbunden"] and k["umschlossen"])\n',
     '    return bool(k["umschlossen"])\n'),
    ("Folgezeile muss nicht auf die Zeile verweisen", SL,
     '            if folge and gesichert and e.get("prev") == folge[-1]["hash"]:\n',
     '            if folge and gesichert:\n'),
    ("Folgezeile ohne gueltiges Merkmal genuegt", SL,
     '            if folge and gesichert and e.get("prev") == folge[-1]["hash"]:\n',
     '            if folge and e.get("prev") == folge[-1]["hash"]:\n'),
    # traegt allein die Zusage "falscher eigener Hash" (siehe _anerkennbar)
    ("Folge reisst nicht bei geaendertem Glied", SL,
     '                folge = folge + [k] if passt else []\n',
     '                folge = folge + [k]\n'),
    ("Folge reisst nicht bei fehlender Verkettung", SL,
     '            if not (kandidat and folge and e.get("prev") == folge[-1]["hash"]):\n',
     '            if not (kandidat and folge):\n'),
    ("Folge nur eine Zeile lang (DEV-Fall)", SL,
     '                folge = folge + [k] if passt else []\n',
     '                folge = [k] if passt else []\n'),
    # ── was als Anerkennung zaehlt ──
    ("Anerkennung ohne Merkmal/Verbindung zaehlt", SL,
     '            if gesichert and verbunden and e.get("art") == ART_ANERKANNT:\n',
     '            if e.get("art") == ART_ANERKANNT:\n'),
    ("Anerkennung ohne Verbindung zur Vorzeile zaehlt", SL,
     '            if gesichert and verbunden and e.get("art") == ART_ANERKANNT:\n',
     '            if gesichert and e.get("art") == ART_ANERKANNT:\n'),
    ("Anerkennung zaehlt nicht", SL,
     '            if gesichert and verbunden and e.get("art") == ART_ANERKANNT:\n',
     '            if False:\n'),
    # ── anerkennen() ──
    ("Journal-Vergleich nur ueber den Hash", SL,
     '        if ist == soll:\n', '        if ist.get("hash") == soll.get("hash"):\n'),
    ("Journal-Praefix wird nicht entfernt", SL,
     '            text = text[len(SYSLOG_KENNUNG) + 1:].strip()\n', '            pass\n'),
    ("ohne Journal-Kopie erlaubt", SL, '    if not beleg:\n', '    if False:\n'),
    ("doppelte Anerkennung erlaubt", SL,
     '    if k["anerkannt"] is not None:\n', '    if False:\n'),
    ("nicht festliegende Zeile anerkennbar", SL,
     '    if not _anerkennbar(k):\n', '    if False:\n'),
    ("Grund/Bearbeiter nicht Pflicht", SL,
     '    if not grund or not von:\n', '    if False:\n'),
    ("Anerkennung geht nur als notice nach syslog", SL,
     '    "kette_bruch_anerkannt": logging.WARNING,\n', ''),
    ("Konsolenbefehl meldet immer Exit 0", SL,
     '        sys.exit(0 if r["ok"] else (2 if r.get("abbruch") else 1))\n',
     '        sys.exit(0)\n'),
    # ── Auslieferung und Anzeige ──
    ("Endpunkt verschweigt die Anerkennung", MA,
     '                  "anerkannt": (kette.get("anerkannt") or [])[:10],\n',
     '                  "anerkannt": [],\n'),
    ("Kopfzeile sagt nur 'intakt'", JS,
     "        } else if (k.ok && k.anzahl_anerkannt) {\n",
     "        } else if (false) {\n"),
    ("anerkannte Stellen nicht aufgelistet", JS,
     "        if ((k.anerkannt || []).length) {\n", "        if (false) {\n"),
    ("Freitext ueber String-Ersetzung ($& wirkt)", JS,
     "                    .replace(/\\{([ztegvd])\\}/g, function (m, n) { return String(werte[n]); });\n",
     "                    .replace('{z}', werte.z).replace('{t}', werte.t).replace('{e}', werte.e)"
     ".replace('{g}', werte.g).replace('{v}', werte.v).replace('{d}', werte.d);\n"),
]

DATEIEN = [SL, MA, JS, "tests/test_bsi_m2_anerkennung.py", "tests/test_sicherheitsprotokoll_ui.js"]

WAECHTER = [
    (["python3", "tests/test_bsi_m2_anerkennung.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
    (["node", "tests/test_sicherheitsprotokoll_ui.js"], r"(\d+) OK, (\d+) FAIL"),
]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    for cmd, muster in WAECHTER:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                               cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            return -1, "timeout " + cmd[-1]
        m = re.search(muster, r.stdout)
        if r.returncode == 2 or not m:
            return -1, f"{cmd[-1]} rc={r.returncode} {r.stdout.strip()[-160:]}"
        summe += int(m.group(2))
    return summe, 0


def zuruecknehmen():
    if not MARKE.exists():
        return
    try:
        alt = json.loads(MARKE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        print("ABBRUCH: Laufmarke unlesbar – Arbeitsbaum von Hand pruefen")
        sys.exit(2)
    for d, hexinhalt in alt.items():
        (ROOT / d).write_bytes(bytes.fromhex(hexinhalt))
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgenommen.")


def main() -> int:
    zuruecknehmen()
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, %s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    MARKE.write_text(json.dumps({d: b.hex() for d, b in sicherung.items()}), encoding="utf-8")
    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu, 1), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-58s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-58s Waechter konnte nicht laufen (%s)" % (name, rc))
            else:
                print("  ZAHN %-58s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)
        if MARKE.exists():
            MARKE.unlink()

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
