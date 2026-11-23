"""Gegenprobe zu test_chat_pdf_ui.js Abschnitt 6 (Einzel-PDF + Doppelstart, 2026-11-23).

Dreht je EINE Eigenschaft in einer Plattenkopie zurueck und erwartet FAILs
MIT Bilanzzeile; stellt danach byte-gleich wieder her (md5).
Exit 0 = alle beissen, 1 = mindestens eine zahnlos, 2 = Basis nicht gruen.
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import hashlib, os, re, subprocess, sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
CJ = W / "frontend/js/chat.js"
CL = W / "frontend/js/chatlib.js"
DATEIEN = [CJ, CL]
TEST = "test_chat_pdf_ui.js"
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()
vorher = {p: md5(p) for p in DATEIEN}
sich = {p: p.read_bytes() for p in DATEIEN}
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def lauf():
    r = subprocess.run(["node", str(W / "tests" / TEST)], capture_output=True, text=True,
                       env=env, timeout=300)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None)


# Die alte Fassung des Einzel-Exports, wie sie bis 2026-11-23 in chat.js stand.
ALT_EINZEL = """function _exportBubblePdf(bubble) {
        const w = window.open('', '_blank');
        if (!w) { alert('Bitte Pop-ups erlauben'); return; }
        w.document.write('<!doctype html><html><body>' + (bubble.innerHTML || '') + '</body></html>');
        w.document.close();
        w.focus();
        setTimeout(() => { try { w.print(); } catch (e) {} }, 350);
    }
    function _exportBubblePdf_neu_unbenutzt(bubble) {"""

PROBEN = [
    ("Einzel-PDF wieder als eigene Fassung (window.open/document.write)", CJ,
     "function _exportBubblePdf(bubble) {", ALT_EINZEL),
    ("Einzel-PDF schickt den ganzen Verlauf statt der einen Zeile", CJ,
     "            rows: [row],\n",
     "            rows: Array.from(row.parentNode.querySelectorAll('.msg-row')),\n"),
    ("Doppelstart-Sperre entfernt", CL,
     "if (_pdfLaeuftSeit && jetzt - _pdfLaeuftSeit < PDF_SPERRE_MS) return false;", ""),
    ("Sperre wird nach dem Export nicht freigegeben", CL,
     "finally { _pdfLaeuftSeit = 0; }", "finally { }"),
    ("Sperre ohne Zeitdeckel", CL,
     "if (_pdfLaeuftSeit && jetzt - _pdfLaeuftSeit < PDF_SPERRE_MS) return false;",
     "if (_pdfLaeuftSeit) return false;"),
    ("Einzahl im Kopf entfernt", CL,
     "(gebaut.stats.nachrichten === 1", "(false"),
]

rc_ende = 1
try:
    rc, f = lauf()
    if rc != 0 or f != 0:
        print(f"ABBRUCH: Basis {TEST} nicht gruen (rc={rc}, fail={f})")
        sys.exit(2)
    print("Basis gruen.")
    gut = 0
    for name, datei, a, n in PROBEN:
        txt = sich[datei].decode()
        if txt.count(a) != 1:
            print(f"  VERFEHLT {name}: Anker {txt.count(a)}x")
            continue
        datei.write_text(txt.replace(a, n, 1))
        try:
            rc, f = lauf()
        finally:
            datei.write_bytes(sich[datei])
        biss = rc == 1 and (f or 0) > 0
        gut += biss
        print(f"  {'OK     ' if biss else 'ZAHNLOS'} {name}: rc={rc} FAIL={f}")
    print(f"{gut} von {len(PROBEN)} beissen.")
    rc_ende = 0 if gut == len(PROBEN) else 1
finally:
    for p in DATEIEN:
        p.write_bytes(sich[p])
    print("byte-gleich:", all(md5(p) == vorher[p] for p in DATEIEN))
sys.exit(rc_ende)
