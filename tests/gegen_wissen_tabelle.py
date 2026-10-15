#!/usr/bin/env python3
"""Gegenproben: "Mein Wissen" als Tabelle, Spalte Groesse, Maximieren (/wissen).

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der zustaendige
Waechter das meldet. Eine Probe, die nicht beisst, ist ein Testmangel – kein
Beweis; und wenn die Zusage gar nicht existiert, gehoert die Probe gestrichen.

Wie `gegen_wissen_destillat.py`: jede angefasste Datei steht in der Sicherung
(als REGEL geprueft, Exit 2), Laufmarke gegen einen Rueckstand nach `kill -9`,
gruener Basislauf ist Bedingung, Byte-Gleichheit danach wird nachgesehen.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-wissen-tabelle"
MARKE = ABL / "LAUF"

MAIN = "backend/main.py"
HTML = "frontend/wissen.html"
JS = "frontend/js/wissen.js"
I18N = "frontend/js/i18n.js"
DATEIEN = [MAIN, HTML, JS, I18N]

PY_W = [sys.executable, str(ROOT / "tests" / "test_wissen_groesse.py")]
JS_W = ["node", str(ROOT / "tests" / "test_wissen_tabelle_ui.js")]
SB_UI = ["node", str(ROOT / "tests" / "test_seite_breit_ui.js")]
PY_D = [sys.executable, str(ROOT / "tests" / "test_wissen_datei_freigabe.py")]


def sichern() -> None:
    ABL.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, ABL / rel.replace("/", "__"))
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck() -> None:
    for rel in DATEIEN:
        q = ABL / rel.replace("/", "__")
        if q.is_file():
            shutil.copy2(q, ROOT / rel)


if MARKE.exists():
    print("⚠ Rueckstand eines frueheren Laufs gefunden – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()


def lauf(cmd) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def bewerte(cmd) -> tuple[bool, str]:
    """(hat gemeldet?, Kurztext). Ohne Bilanzzeile = Abbruch – zaehlt als
    Meldung, wird aber ausgewiesen."""
    rc, aus = lauf(cmd)
    # test_seite_breit_ui.js schreibt "N OK, M FAIL" ohne "Ergebnis:".
    bil = [z.strip() for z in aus.splitlines()
           if "Ergebnis:" in z or re.match(r"\s*\d+ OK, \d+ FAIL", z)]
    fails = aus.count("✗")
    if not bil:
        return rc != 0, f"KEINE BILANZ (rc={rc}) – Abbruch statt FAIL"
    return rc != 0, f"{bil[-1]} / {fails} FAIL"


PROBEN = [
    # ── Backend: Groesse ────────────────────────────────────────────────────
    ("⚠ Manifest-Schluessel immer relativ aufgeloest (Freigaben tot)", MAIN,
     "    if erster and (root / erster).exists():\n        return root / rel\n",
     "    return root / rel\n", PY_W),
    ("stummer Einhaengepunkt wird nicht vorher gefragt", MAIN,
     "                if not _safe_exists(mp):\n",
     "                if False:\n", PY_W),
    ("⚠ kein Zeitbudget (haengende Freigabe haelt die Liste auf)", MAIN,
     "    await asyncio.to_thread(th.join, _WISSEN_GROESSE_BUDGET + 0.5)",
     "    await asyncio.to_thread(th.join)", PY_W),
    ("Cache wird nicht benutzt", MAIN,
     "        if c and jetzt - c[1] < _WISSEN_GROESSE_TTL:",
     "        if False:", PY_W),
    ("Endpunkt reicht die Groesse nicht durch", MAIN,
     # `pass` statt Leerzeile: ohne Rumpf waere main.py nicht mehr parsebar,
     # und die Probe maesse einen Syntaxfehler statt der Zusage.
     "        f[\"size\"] = groessen.get(f[\"path\"])\n", "        pass\n", PY_W),
    ("⚠ unbekannte Groesse wird 0 (behauptet 'leere Datei')", MAIN,
     "        f[\"size\"] = groessen.get(f[\"path\"])",
     "        f[\"size\"] = groessen.get(f[\"path\"], 0)", PY_W),

    # ── Frontend: Tabelle und Sortierung ────────────────────────────────────
    ("Liste wird nicht sortiert", JS,
     "        sortieren(shown);\n", "", JS_W),
    ("gleiche Spalte kehrt die Richtung nicht um", JS,
     "                if (_fsort.key === k) _fsort.dir = -_fsort.dir;",
     "                if (_fsort.key === k) _fsort.dir = _fsort.dir;", JS_W),
    ("neue Spalte erbt die alte Richtung", JS,
     "                else { _fsort.key = k; _fsort.dir = 1; }",
     "                else { _fsort.key = k; }", JS_W),
    ("⚠ unbekannte Groesse steht nicht am Ende", JS,
     "                if (an || bn) { if (an && bn) r = 0; else return an ? 1 : -1; }",
     "                if (an || bn) { r = ((a.size || 0) - (b.size || 0)) * d; }", JS_W),
    ("Groesse als Text statt als Zahl verglichen", JS,
     # EINFACHER Textvergleich: vergleichText() sortiert Ziffern schon
     # natuerlich – mit ihm waere die Sabotage wirkungslos (erster Anlauf stumm).
     "                else r = (a.size - b.size) * d;",
     "                else r = (String(a.size) < String(b.size) ? -1 : 1) * d;", JS_W),
    ("Zahl im Namen nicht natuerlich sortiert (Datei 10 vor Datei 2)", JS,
     "sprache(), { numeric: true, sensitivity: 'base' });",
     "sprache(), { sensitivity: 'base' });", JS_W),
    ("⚠ unbekannte Groesse als '0 B' angezeigt", JS,
     "        if (n == null || isNaN(n)) return '–';",
     "        if (n == null || isNaN(n)) n = 0;", JS_W),
    ("aria-sort fehlt (Zustand nur als Zeichen)", JS,
     "                + ' aria-sort=\"' + (aktiv ? (_fsort.dir > 0 ? 'ascending' : 'descending') : 'none') + '\">'",
     "                + '>'", JS_W),
    ("⚠ Tabellenzeile traegt wieder `.wi-item` (display: flex)", JS,
     "            return '<tr class=\"wi-frow\" data-path=\"'",
     "            return '<tr class=\"wi-item wi-frow\" data-path=\"'", JS_W),
    ("Sortierung geht beim Tippen in der Suche verloren", JS,
     "            renderFileList();                 // Name/Ordner sofort",
     "            _fsort = { key: 'name', dir: 1 };\n            renderFileList();", JS_W),
    ("Groessen-Spalte fehlt", JS,
     "            { key: 'size', lbl: 'wissen.col_size', cls: 'wi-fsize' }\n",
     "", JS_W),

    # ── Frontend: Maximieren hinter "Angemeldet als" (ganze Seite breit) ────
    # Seit 2026-09-28 der gemeinsame Baustein (seite_breit.js); dessen
    # Verhalten beisst in gegen_seite_breit.py. Hier: was /wissen-EIGEN ist.
    ("⚠ Knopf wieder in der Titelleiste", HTML,
     '        <div class="wi-top-icons">\n',
     '        <div class="wi-top-icons">\n            <button class="jv-max-btn">&#9974;</button>\n', JS_W),
    ("⚠ Knopf wieder in der Kopfzeile von Mein Wissen", HTML,
     '<span data-i18n="wissen.sec_files">Mein Wissen</span>',
     '<span data-i18n="wissen.sec_files">Mein Wissen</span><button class="jv-max-btn">&#9974;</button>', JS_W),
    ("Knopf fehlt hinter dem Banner", HTML,
     'class="jv-max-btn" id="jv-max"', 'class="jv-max-btn" id="jv-max-weg"', JS_W),
    ("⚠ Knopf IM Banner (renderScope loescht ihn)", HTML,
     'data-i18n="common.loading">Lade…</div>\n            <button type="button" class="jv-max-btn" id="jv-max" data-seite="wissen"\n                    data-speicher="jarvis_wissen_breit" aria-pressed="false"\n                    data-i18n-title="common.maximize" data-i18n-aria="common.maximize"\n                    title="Maximieren" aria-label="Maximieren">&#9974;</button>\n',
     'data-i18n="common.loading">Lade…<button type="button" class="jv-max-btn" id="jv-max" data-seite="wissen"\n                    data-speicher="jarvis_wissen_breit" aria-pressed="false"\n                    data-i18n-title="common.maximize" data-i18n-aria="common.maximize"\n                    title="Maximieren" aria-label="Maximieren">&#9974;</button></div>\n', JS_W),
    ("Bereich nicht als breit-faehig markiert", HTML,
     '<div id="wi-app" class="wi-wrap hidden" data-jv-breit>', '<div id="wi-app" class="wi-wrap hidden">', JS_W),
    ("⚠ gemerkte Breite der Benutzer geht verloren (Schluessel neu)", HTML,
     '                    data-speicher="jarvis_wissen_breit" aria-pressed="false"\n',
     '                    aria-pressed="false"\n', JS_W),
    ("seite_breit.js nicht eingebunden", HTML,
     '    <script src="/static/js/seite_breit.js?v=1"></script>\n', "", SB_UI),

    # ── Oeffnen von Freigabe-Dateien (GET /api/wissen/file) ─────────────────
    ("⚠ Altstand: Schluessel wieder gegen PROJECT_ROOT aufgeloest (89/89 404 auf ECHT)", MAIN,
     "    target = _wissen_absolut(rel).resolve()\n    wurzeln = []",
     "    target = (Path(_wissen_wurzeln()[0]).parent.parent / rel).resolve()\n    wurzeln = []", PY_D),
    ("⚠ Schranke raus (jeder zugeordnete Pfad wird ausgeliefert)", MAIN,
     "    if not _wissen_unter_wurzel(target, wurzeln):\n        return None, \"ausserhalb\"",
     "    if False:\n        return None, \"ausserhalb\"", PY_D),
    ("nur feste Wurzeln zugelassen (konfigurierte Freigaben wieder draussen)", MAIN,
     "    return [root / RAG_REL, root / INFRA_REL, Path(MOUNT_BASIS)] + list(_get_folders())",
     "    return [root / RAG_REL, root / INFRA_REL, Path(MOUNT_BASIS)]", PY_D),
    ("⚠ Symlinks nicht aufgeloest (Ausbruch aus der Freigabe)", MAIN,
     "    target = _wissen_absolut(rel).resolve()\n    wurzeln = []",
     "    target = Path(os.path.normpath(_wissen_absolut(rel)))\n    wurzeln = []", PY_D),
    # Code-Review 2026-10-07: nur Wissensorte, nicht "alles unter PROJECT_ROOT"
    ("⚠ Review: wieder ganz PROJECT_ROOT erlaubt (.env lesbar)", MAIN,
     "    return [root / RAG_REL, root / INFRA_REL, Path(MOUNT_BASIS)] + list(_get_folders())",
     "    return [root] + list(_get_folders())", PY_D),
    ("⚠ Review: versteckte Pfadteile erlaubt (.groups.json lesbar)", MAIN,
     "        if teile and not any(t.startswith(\".\") for t in teile):",
     "        if teile:", PY_D),
    ("⚠ Review: Zuordnung ohne Ortspruefung", MAIN,
     "    if not _wissen_schluessel_erlaubt(kg._rel(path)):\n",
     "    if False and _wissen_schluessel_erlaubt(kg._rel(path)):\n", PY_D),
    # (Keine Probe "ohne normpath": ein `..` ist selbst ein versteckter
    # Pfadteil und wird von der Punktregel schon abgewiesen – die Sabotage
    # waere wirkungslos, keine Luecke im Waechter.)
    ("⚠ ohne Deckel (toter Mount blockiert den Dienst)", MAIN,
     # Anker mit dem GET-Kommentar davor: der Aufrufblock steht seit dem
     # DELETE-Umbau ZWEIMAL in main.py (erster Anlauf: "trifft nicht, 2x").
     "    # schon `resolve()`, und das hier ist ein async-Endpunkt.\n"
     "    from backend.tools.knowledge import _bounded_call\n"
     "    ziel, fehler = await asyncio.to_thread(\n"
     "        _bounded_call, lambda: _wissen_datei_ziel(rel), _WISSEN_DATEI_DECKEL,\n"
     "        (None, \"stumm\"))",
     "    # schon `resolve()`, und das hier ist ein async-Endpunkt.\n"
     "    from backend.tools.knowledge import _bounded_call\n"
     "    ziel, fehler = _wissen_datei_ziel(rel)", PY_D),
    ("⚠ DELETE wieder mit eigener Aufloesung (Freigabe-Dateien 404)", MAIN,
     "    ziel, fehler = await asyncio.to_thread(\n"
     "        _bounded_call, lambda: _wissen_datei_ziel(rel), _WISSEN_DATEI_DECKEL,\n"
     "        (None, \"stumm\"))\n"
     "    if fehler == \"ausserhalb\":\n"
     "        return JSONResponse({\"error\": \"Ungueltiger Pfad\"}, status_code=400)\n"
     "    if fehler == \"stumm\":\n"
     "        return JSONResponse({\"error\": \"Der Speicherort antwortet gerade nicht\"},\n"
     "                            status_code=504)\n"
     "    if fehler:\n"
     "        return JSONResponse({\"error\": \"Nicht gefunden\"}, status_code=404)\n"
     "    target = ziel\n\n    def _loeschen():",
     "    root = Path(__import__('backend.tools.knowledge').tools.knowledge.PROJECT_ROOT).resolve()\n"
     "    target = (root / rel).resolve()\n"
     "    if not target.is_file():\n"
     "        return JSONResponse({\"error\": \"Nicht gefunden\"}, status_code=404)\n\n    def _loeschen():", PY_D),
    ("nur lesende Freigabe wieder als roher 500", MAIN,
     "        if fehl.errno in (_errno.EROFS, _errno.EACCES, _errno.EPERM):",
     "        if False:", PY_D),
    ("⚠ Loeschen ohne Deckel (haengende Freigabe blockiert)", MAIN,
     "    fehl = await asyncio.to_thread(_bounded_call, _loeschen, _WISSEN_DATEI_DECKEL, \"zeit\")",
     "    fehl = _loeschen()", PY_D),

    # ── i18n ────────────────────────────────────────────────────────────────
    ("ein Schluessel fehlt im Englischen", I18N,
     "        'wissen.col_size': 'Size',\n", "", JS_W),
]


def main() -> int:
    unbekannt = {p[1] for p in PROBEN} - set(DATEIEN)
    if unbekannt:
        print(f"\033[31mABBRUCH: nicht gesichert: {sorted(unbekannt)}\033[0m")
        return 2
    sichern()

    print("\033[1mBasislauf\033[0m")
    for cmd, name in ((PY_W, "Backend"), (PY_D, "Datei"), (JS_W, "UI")):
        rc, aus = lauf(cmd)
        bil = [z for z in aus.splitlines() if "Ergebnis:" in z]
        print(f"  {name}: {bil[-1].strip() if bil else 'KEINE BILANZ'}")
        if rc != 0:
            print(f"\033[31mABBRUCH: Basislauf {name} nicht gruen\033[0m")
            zurueck(); MARKE.unlink()
            return 2

    beisst = stumm = kaputt = 0
    print()
    for i, (name, datei, alt, neu, waechter) in enumerate(PROBEN, 1):
        pfad = ROOT / datei
        orig = pfad.read_text(encoding="utf-8")
        if orig.count(alt) != 1:
            print(f"  \033[33m⚠\033[0m {i:2}. {name}\n"
                  f"        SABOTAGE TRIFFT NICHT ({datei}, {orig.count(alt)}x) – Probe unbrauchbar")
            kaputt += 1
            continue
        pfad.write_text(orig.replace(alt, neu, 1), encoding="utf-8")
        try:
            gemeldet, info = bewerte(waechter)
        finally:
            pfad.write_text(orig, encoding="utf-8")
        if gemeldet:
            beisst += 1
            print(f"  \033[32m✓\033[0m {i:2}. {name}\n        {info}")
        else:
            stumm += 1
            print(f"  \033[31m✗\033[0m {i:2}. {name}\n        \033[31mSTUMM\033[0m – {info}")

    print(f"\n\033[1mbeisst: {beisst}/{len(PROBEN)}"
          + (f", stumm: {stumm}" if stumm else "")
          + (f", unbrauchbar: {kaputt}" if kaputt else "") + "\033[0m")

    zurueck()
    rest = [r for r in DATEIEN
            if (ROOT / r).read_bytes() != (ABL / r.replace("/", "__")).read_bytes()]
    MARKE.unlink()
    print("Arbeitsbaum wiederhergestellt: "
          + ("\033[32mja\033[0m" if not rest else f"\033[31mNEIN: {rest}\033[0m"))
    return 0 if (not stumm and not kaputt and not rest) else 1


if __name__ == "__main__":
    sys.exit(main())
