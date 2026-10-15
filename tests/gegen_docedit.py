#!/usr/bin/env python3
"""Gegenproben zur Bearbeitungsmaske fuer uebernommene Dokumente.

Eine Gegenprobe, die nicht beisst, ist ein Testmangel - kein Beweis. Jede Probe
dreht EINE Zusage zurueck und zaehlt, wie viele Pruefungen das meldet.

HARNESS-DISZIPLIN (jede Zeile ist ein bezahlter Vorfall, siehe Register):
  * Sicherung auf PLATTE vor jeder Probe, bei jedem Lauf ERNEUERT - eine alte
    Sicherung stellt den Stand von damals her und macht fertige Arbeit zunichte.
  * LAUFMARKE: bleibt sie liegen (kill -9), nimmt der naechste Start den
    Rueckstand selbst zurueck. Beim geordneten Ende wird sie abgeraeumt.
  * Nach dem Wiederherstellen wird BYTE-GLEICHHEIT geprueft, nicht angenommen.
  * Ein gruener BASISLAUF ist Pflicht - ohne gruene Basis ist keine Gegenprobe
    deutbar (jede Probe zaehlte sonst eine FAIL zu viel).
  * Die Liste der gesicherten Dateien wird als REGEL geprueft, nicht gepflegt.
"""
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SICHER = pathlib.Path.home() / ".gegen-sicherung-docedit"
MARKE = SICHER / "LAUF_AKTIV"

WAECHTER = [
    ("tests/test_wissen_docedit_ui.js", "Maske"),
    ("tests/test_kbmatrix_ungrouped_ui.js", "Spalte"),
]

DATEIEN = [
    "frontend/js/wissen.js",
    "frontend/js/kbmatrix.js",
    "frontend/js/i18n.js",
]

# (Name, Datei, alt, neu, erwarteter Waechter)
PROBEN = [
    # ── Die tragende Zusage: PATCH *und* Uebernehmen ──────────────────────
    ("Uebernehmen entfaellt - nur PATCH", "frontend/js/wissen.js",
     """            }).then(function () {
                return fetch('/api/knowledge/pending/' + encodeURIComponent(doc.id) + '/approve', {
                    method: 'POST', headers: authH({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ groups: groups }),
                });
            }).then(function (r) {""",
     """            }).then(function (r) {""", "Maske"),

    # ── Rechte-/Endpunkt-Familie ──────────────────────────────────────────
    ("falsche Endpunkt-Familie (/api/wissen statt /api/knowledge)", "frontend/js/wissen.js",
     "fetch('/api/knowledge/pending/' + encodeURIComponent(doc.id), {",
     "fetch('/api/wissen/pending/' + encodeURIComponent(doc.id), {", "Maske"),

    # ── Pflichten ─────────────────────────────────────────────────────────
    ("Gruppen-Pflicht raus", "frontend/js/wissen.js",
     "            if (!groups.length) { melde(t('wissen.pick_target')); return; }",
     "            if (!groups.length) { /* Pflicht entfernt */ }", "Maske"),

    ("Inhalts-Pflicht raus", "frontend/js/wissen.js",
     """            if (!(patch.facts || []).length && !freigegeben.length) {
                melde(t('kbmatrix.need_content')); return;
            }""",
     "            /* Inhalts-Pflicht entfernt */", "Maske"),

    # ── Q&A: Fremdfelder und geloeschte Paare ─────────────────────────────
    ("Q&A ohne Container-Pruefung (liest fremden Entwurf, laesst Geloeschte stehen)",
     "frontend/js/wissen.js",
     """            var qaEl = $('wi-de-qa');
            if (qaEl) patch.qa_pairs = collectQa(qaEl) || [];""",
     """            var paare = collectQa($('wi-de-qa'));
            if (paare !== null) patch.qa_pairs = paare;""", "Maske"),

    # ── Loeschweg ─────────────────────────────────────────────────────────
    ("Rueckfrage vor dem Loeschen raus", "frontend/js/wissen.js",
     "            if (!confirm(t('ext.delete_approved_confirm'))) return;",
     "            /* Rueckfrage entfernt */", "Maske"),

    ("Entfernen-Knopf erscheint auch ohne Weg", "frontend/js/wissen.js",
     "        var entfBtn = opts.entfernen\n",
     "        var entfBtn = true\n", "Maske"),

    # ── Die Spalte: zwei Bedeutungen ──────────────────────────────────────
    ("Spaltenkopf behauptet wieder \"Bearb.\"", "frontend/js/i18n.js",
     "        'kbmatrix.col_open':             'Öffnen',",
     "        'kbmatrix.col_open':             'Bearb.',", "Spalte"),

    ("jede Zeile gilt als bearbeitbar", "frontend/js/kbmatrix.js",
     "    function _bearbeitbar(row) { return !!(row && row.docId && row.doc); }",
     "    function _bearbeitbar(row) { return true; }", "Spalte"),

    ("keine Zeile gilt als bearbeitbar (gemeldeter Zustand)", "frontend/js/kbmatrix.js",
     "    function _bearbeitbar(row) { return !!(row && row.docId && row.doc); }",
     "    function _bearbeitbar(row) { return false; }", "Spalte"),

    ("Aussehen und Verhalten wieder getrennt (Tooltip kann luegen)", "frontend/js/kbmatrix.js",
     "        if (_bearbeitbar(row) && WP && WP.openDocEdit) {",
     "        if (row.docId && row.doc && WP && WP.openDocEdit) {", "Spalte"),

    ("Klick oeffnet immer die Leseansicht", "frontend/js/kbmatrix.js",
     "        if (_bearbeitbar(row) && WP && WP.openDocEdit) {",
     "        if (false) {", "Spalte"),

    ("Gruppen werden der Maske nicht vorbelegt", "frontend/js/kbmatrix.js",
     "                gruppen: _gids(path),",
     "                gruppen: [],", "Spalte"),

    ("Entfernen-Weg wird nicht durchgereicht", "frontend/js/kbmatrix.js",
     "                entfernen: () => _docAusDb(path, row.docId),",
     "", "Spalte"),

    ("Loeschweg wieder in zwei Fassungen", "frontend/js/kbmatrix.js",
     "                await _docAusDb(path, row.docId);",
     """                await fetch('/api/knowledge/extract/file', {
                    method: 'DELETE', headers: _auth({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ file: path }),
                }).catch(() => {});
                await fetch('/api/knowledge/pending/' + encodeURIComponent(row.docId), {
                    method: 'DELETE', headers: _auth(),
                }).catch(() => {});""", "Spalte"),
]


def md5(p: pathlib.Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern():
    SICHER.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        ziel = SICHER / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, ziel)   # bei JEDEM Lauf erneuern


def zurueck() -> bool:
    heil = True
    for rel in DATEIEN:
        q = SICHER / rel.replace("/", "__")
        if not q.exists():
            continue
        shutil.copy2(q, ROOT / rel)
        if md5(q) != md5(ROOT / rel):
            print(f"  ⚠ NICHT byte-gleich wiederhergestellt: {rel}")
            heil = False
    return heil


def lauf(datei: str) -> int:
    """Fuehrt einen Waechter aus und gibt die Zahl der FAIL zurueck (-1 = Abbruch)."""
    r = subprocess.run([sys.executable.replace("python3", "node") if False else "node",
                        str(ROOT / datei)],
                       capture_output=True, text=True, cwd=ROOT, timeout=120)
    for zeile in r.stdout.splitlines():
        if zeile.startswith("\x1b[1mErgebnis:") or zeile.startswith("Ergebnis:"):
            roh = zeile.replace("\x1b[1m", "").replace("\x1b[0m", "")
            # "Ergebnis: 39 OK, 0 FAIL" - die FAIL-Zahl, NICHT die erste Zahl.
            # (Register: ein Harness, der split()[1] liest, meldet die OK-Zahl
            # und haelt jede Probe fuer beissend.)
            for teil in roh.split(","):
                if "FAIL" in teil:
                    return int("".join(c for c in teil if c.isdigit()))
    return -1


def main():
    if MARKE.exists():
        print("⚠ Rueckstand eines abgebrochenen Laufs - nehme ihn zurueck.")
        zurueck()
        MARKE.unlink(missing_ok=True)

    # REGEL statt gepflegter Liste: jede Datei, die eine Probe anfasst, muss
    # gesichert werden - sonst bleibt eine Sabotage liegen.
    fehlend = {p[1] for p in PROBEN} - set(DATEIEN)
    if fehlend:
        print(f"ABBRUCH: Proben fassen ungesicherte Dateien an: {fehlend}")
        sys.exit(2)

    sichern()
    print("Basislauf (ohne gruene Basis ist keine Gegenprobe deutbar):")
    basis = {}
    for datei, name in WAECHTER:
        n = lauf(datei)
        basis[name] = n
        print(f"  {name}: {n} FAIL")
        if n != 0:
            print("ABBRUCH: Basis ist nicht gruen.")
            sys.exit(2)

    MARKE.parent.mkdir(parents=True, exist_ok=True)
    MARKE.write_text("laeuft")
    beissen = 0
    stumm = []
    try:
        for name, rel, alt, neu, erwartet in PROBEN:
            p = ROOT / rel
            text = p.read_text(encoding="utf-8")
            if alt not in text:
                print(f"  ⚠ {name}: ANKER TRIFFT NICHT - Proben-Mangel, nicht blinder Waechter")
                stumm.append(name + " (Anker)")
                continue
            if text.count(alt) != 1:
                print(f"  ⚠ {name}: Anker {text.count(alt)}x - zu unspezifisch")
                stumm.append(name + " (Anker mehrfach)")
                continue
            p.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                datei_w = next(d for d, nm in WAECHTER if nm == erwartet)
                n = lauf(datei_w)
            finally:
                zurueck()
            if n > 0:
                print(f"  ✓ {name}: {erwartet} meldet {n} FAIL")
                beissen += 1
            elif n < 0:
                print(f"  ⚠ {name}: {erwartet} ABGEBROCHEN ohne Bilanz")
                stumm.append(name + " (Abbruch)")
            else:
                print(f"  ✗ {name}: STUMM - der Waechter sieht es nicht")
                stumm.append(name)
    finally:
        heil = zurueck()
        MARKE.unlink(missing_ok=True)

    # Beim GEORDNETEN Ende die Sicherung abraeumen (Register): bleibt sie
    # liegen, koennte ein spaeterer Lauf einen veralteten Stand herstellen und
    # fertige Arbeit zunichte machen. Nach einem kill -9 bleibt sie samt Marke
    # stehen - genau dann soll das Zuruecknehmen beim naechsten Start greifen.
    if heil:
        shutil.rmtree(SICHER, ignore_errors=True)

    print(f"\nERGEBNIS: {beissen} von {len(PROBEN)} Proben beissen")
    if stumm:
        print("Stumm/mangelhaft: " + ", ".join(stumm))
    if not heil:
        print("⚠ Arbeitsbaum NICHT byte-gleich wiederhergestellt - pruefen!")
        sys.exit(2)
    sys.exit(0 if beissen == len(PROBEN) else 1)


if __name__ == "__main__":
    main()
