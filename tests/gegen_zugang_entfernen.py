#!/usr/bin/env python3
"""Gegenprobe: beissen die drei Waechter zu "Eigenen Zugang entfernen"?

    tests/test_zugang_entfernen.py        (Auskunft des Servers)
    tests/test_zugang_entfernen_ui.js     (Verhalten in /sap und /vemas)
    tests/test_zugang_knopf_chrome.py     (wirkt `hidden` im Browser?)

Sabotierte KOPIEN in einem Wegwerf-Verzeichnis, uebergeben ueber die Umgebung –
die echten Dateien werden nie angefasst. Vorher ein gruener Basislauf; eine
Probe "beisst" nur mit Exit 1 UND mindestens einem FAIL (Exit 2 und Abstuerze
zaehlen nicht). Jede Probe nimmt GENAU EINE Zusage weg.

NICHT in einem Sammellauf mitlaufen lassen (startet Chrome je Probe).
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen

    python3 tests/gegen_zugang_entfernen.py
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = [
    ("server", [sys.executable, str(HIER / "test_zugang_entfernen.py")]),
    ("verhalten", ["node", str(HIER / "test_zugang_entfernen_ui.js")]),
    ("chrome", [sys.executable, str(HIER / "test_zugang_knopf_chrome.py")]),
]
DATEIEN = {
    "sapmodul": (ROOT / "backend" / "sap_accounts.py", "ZUGANG_SAP_MODUL"),
    "vemasmodul": (ROOT / "backend" / "vemas_accounts.py", "ZUGANG_VEMAS_MODUL"),
    "main": (ROOT / "backend" / "main.py", "ZUGANG_MAIN"),
    "sapportal": (ROOT / "frontend" / "js" / "sap_portal.js", "SAP_PORTAL_JS"),
    "vemasportal": (ROOT / "frontend" / "js" / "vemas_portal.js", "VEMAS_PORTAL_JS"),
    "saphtml": (ROOT / "frontend" / "sap.html", "ZUGANG_SAP_HTML"),
    "vemashtml": (ROOT / "frontend" / "vemas.html", "ZUGANG_VEMAS_HTML"),
    "i18n": (ROOT / "frontend" / "js" / "i18n.js", "ZUGANG_I18N"),
}

FELD = '        "gespeichert": un in alle,\n'
REGEL = "        b.hidden = !_account || _account.gespeichert === false;\n"
FEHLERZWEIG = "                // Server wirklich etwas entfernt hat.\n                if (!d || !d.ok) {\n"
OHNE_FEHLERZWEIG = "                // Server wirklich etwas entfernt hat.\n                if (false) {\n"

# (Name, Datei, alt, neu)
PROBEN = [
    # ── Server ──────────────────────────────────────────────────────────────
    ("SAP: gespeichert ist immer wahr", "sapmodul", FELD, '        "gespeichert": True,\n'),
    ("SAP: gespeichert ist nur ein zweites vorhanden", "sapmodul", FELD,
     '        "gespeichert": bool(_vollstaendig(k)),\n'),
    ("VEMAS: gespeichert ist immer wahr", "vemasmodul", FELD, '        "gespeichert": True,\n'),
    ("VEMAS: gespeichert ist nur ein zweites vorhanden", "vemasmodul", FELD,
     '        "gespeichert": bool(_vollstaendig(k)),\n'),
    ("SAP-Endpunkt meldet immer 'entfernt'", "main",
     '"removed": bool(weg),\n                         "account": sap_accounts.zugang_info(user)})',
     '"removed": True,\n                         "account": sap_accounts.zugang_info(user)})'),
    ("VEMAS-Endpunkt meldet immer 'entfernt'", "main",
     '"removed": bool(weg),\n                         "account": vemas_accounts.zugang_info(user)})',
     '"removed": True,\n                         "account": vemas_accounts.zugang_info(user)})'),
    # ── /sap ────────────────────────────────────────────────────────────────
    ("/sap: Knopf folgt der Kontoauskunft nicht", "sapportal",
     "                accEntfernbar();\n                accRenderHosts();\n",
     "                accRenderHosts();\n"),
    ("/sap: fehlendes Feld nimmt den Knopf weg", "sapportal", REGEL,
     "        b.hidden = !_account || !_account.gespeichert;\n"),
    ("/sap: Knopf haengt an vorhanden statt an gespeichert", "sapportal", REGEL,
     "        b.hidden = !_account || !_account.vorhanden;\n"),
    ("/sap: Knopf ist immer sichtbar", "sapportal", REGEL, "        b.hidden = false;\n"),
    ("/sap: verankertes Zertifikat zieht den Knopf nicht nach", "sapportal",
     "if (d && d.account) { _account = d.account; accEntfernbar(); }",
     "if (d && d.account) { _account = d.account; }"),
    ("/sap: removed:false meldet 'entfernt'", "sapportal",
     "                if (d.removed === false) {\n                    accNote(T('sap.acc_none_stored'",
     "                if (false) {\n                    accNote(T('sap.acc_none_stored'"),
    ("/sap: ein Fehler meldet 'entfernt'", "sapportal", FEHLERZWEIG, OHNE_FEHLERZWEIG),
    # ── /vemas ──────────────────────────────────────────────────────────────
    ("/vemas: Knopf folgt der Kontoauskunft nicht", "vemasportal",
     "                accEntfernbar();\n                accRenderWrite();\n",
     "                accRenderWrite();\n"),
    ("/vemas: fehlendes Feld nimmt den Knopf weg", "vemasportal", REGEL,
     "        b.hidden = !_account || !_account.gespeichert;\n"),
    ("/vemas: Knopf haengt an vorhanden statt an gespeichert", "vemasportal", REGEL,
     "        b.hidden = !_account || !_account.vorhanden;\n"),
    ("/vemas: Knopf ist immer sichtbar", "vemasportal", REGEL, "        b.hidden = false;\n"),
    ("/vemas: removed:false meldet 'entfernt'", "vemasportal",
     "                if (d.removed === false) {\n                    accNote(T('vemas.acc_none_stored'",
     "                if (false) {\n                    accNote(T('vemas.acc_none_stored'"),
    ("/vemas: ein Fehler meldet 'entfernt'", "vemasportal", FEHLERZWEIG, OHNE_FEHLERZWEIG),
    # ── Markup und CSS ──────────────────────────────────────────────────────
    ("/sap: Knopf im Markup nicht verborgen vorbelegt", "saphtml",
     'id="sp-acc-del" type="button" data-i18n="sap.acc_remove" hidden>',
     'id="sp-acc-del" type="button" data-i18n="sap.acc_remove">'),
    ("/sap: hidden wirkt an der Knopfklasse nicht", "saphtml",
     "        .sp-hist-btn[hidden] { display: none; }\n", ""),
    ("/vemas: Knopf im Markup nicht verborgen vorbelegt", "vemashtml",
     'id="vm-acc-del" type="button" hidden\n', 'id="vm-acc-del" type="button"\n'),
    ("/vemas: hidden wirkt an der Knopfklasse nicht", "vemashtml",
     "        .vm-hist-btn[hidden] { display: none; }\n", ""),
    # ── Texte ───────────────────────────────────────────────────────────────
    ("SAP: englischer Text fehlt", "i18n",
     "        'sap.acc_none_stored': 'No personal access was stored.',\n", ""),
    ("VEMAS: deutscher Text fehlt", "i18n",
     "        'vemas.acc_none_stored':        'Es war kein eigener Zugang hinterlegt.',\n", ""),
]


def lauf(umgebung: dict) -> tuple:
    """Alle Pruefstaende; Rueckgabe (Exit, FAIL-Summe, wer biss, Ausgabe).

    Exit 2 bei irgendeinem Pruefstand geht vor (konnte nicht messen); eine
    fehlende Bilanzzeile heisst FAIL None – das zaehlt nicht als Biss."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **umgebung)
    codes, summe, wer, aus = [], 0, [], ""
    for name, befehl in WAECHTER:
        r = subprocess.run(befehl, cwd=str(ROOT), env=env,
                           capture_output=True, text=True, timeout=300)
        m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
        codes.append(r.returncode)
        aus += r.stdout + r.stderr
        if m is None:
            summe = None
        else:
            if summe is not None:
                summe += int(m.group(2))
            if r.returncode == 1 and int(m.group(2)):
                wer.append(name)
    code = 2 if 2 in codes else max(codes)
    return code, summe, wer, aus


def main() -> int:
    nicht_gedeckt = {p[1] for p in PROBEN} - set(DATEIEN)
    if nicht_gedeckt:
        print(f"ABBRUCH: Proben auf unbekannte Dateien: {nicht_gedeckt}")
        return 2
    code, fails, _, aus = lauf({})
    if code != 0 or fails != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (Exit {code}, FAIL {fails})")
        print(aus[-2000:])
        return 2
    print("Basislauf gruen.\n")
    stumm = 0
    with tempfile.TemporaryDirectory(prefix="gegen_zugang_entfernen_") as tmp:
        for i, (name, datei, alt, neu) in enumerate(PROBEN, 1):
            quelle, var = DATEIEN[datei]
            text = quelle.read_text(encoding="utf-8")
            n = text.count(alt)
            if n != 1:
                print(f"  ??     {i:2d} {name} – Anker {n}x gefunden (erwartet 1)")
                stumm += 1
                continue
            ziel = Path(tmp) / f"probe{i}_{quelle.name}"
            ziel.write_text(text.replace(alt, neu), encoding="utf-8")
            code, fails, wer, aus = lauf({var: str(ziel)})
            if code == 1 and fails:
                print(f"  BEISST {i:2d} {name} ({fails} FAIL: {', '.join(wer)})")
            else:
                stumm += 1
                print(f"  STUMM  {i:2d} {name} (Exit {code}, FAIL {fails})")
    print(f"\nErgebnis: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
