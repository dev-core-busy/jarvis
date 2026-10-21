"""Gegenprobe zu test_wissen_quelle_auge (Quelle-Spalte + Auge, 2026-10-21).

Dreht je EINE Zusage in einer Plattenkopie zurueck und erwartet FAILs MIT
Bilanzzeile; stellt danach byte-gleich wieder her (md5).

Exit 0 = alle beissen, 1 = mindestens eine zahnlos, 2 = Basis nicht gruen.
"""
import hashlib, os, re, subprocess, sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
MAIN = W / "backend/main.py"
KBM = W / "frontend/js/kbmatrix.js"
TEST = "test_wissen_quelle_auge.py"
# ⚠ DIE TESTDATEI SELBST GEHOERT IN DIE SICHERUNGSLISTE (Register).
DATEIEN = [MAIN, KBM, W / "tests" / TEST]
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()
vorher = {p: md5(p) for p in DATEIEN}
sich = {p: p.read_bytes() for p in DATEIEN}
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def lauf():
    r = subprocess.run([sys.executable, str(W / "tests" / TEST)],
                       capture_output=True, text=True, env=env, timeout=300)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None)


# Der ganze Zweig, so wie er vor dem Fix NICHT existierte.
ZWEIG = '''    except UnicodeDecodeError:
        # ⚠ EINE PDF IST KEIN SERVERFEHLER. Bis 2026-10-21 flog der
        # UnicodeDecodeError in das breite `except` darunter und wurde zu einem
        # HTTP 500 mit dem Codec-Text ("'utf-8' codec can't decode byte 0xb2 in
        # position 10"). Im Wissens-Portal fuehrte damit JEDER Klick auf das
        # Auge einer PDF-/Office-Datei zu einer Fehlermeldung - also im
        # Normalfall, denn Wissensordner enthalten ueberwiegend solche Dateien.
        # Jetzt ist es eine geordnete Auskunft: der Aufrufer erfaehrt, DASS die
        # Datei kein Text ist und WAS sie ist, und holt sie ueber
        # /api/knowledge/file_raw. Der MIME-Typ kommt von hier, damit das
        # Frontend keine eigene Endungsliste pflegen muss - eine Liste ist an
        # dem Tag unvollstaendig, an dem eine neue Endung dazukommt.
        import mimetypes
        mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        return JSONResponse({"ok": False, "binary": True, "mime": mime,
                             "error": "Datei ist kein UTF-8-Text"})
'''

PROBEN = [
    # Der gemeldete Zustand: der Zweig fehlt, jede Binaerdatei wird wieder 500.
    ("Altstand: kein UnicodeDecodeError-Zweig", [(MAIN, ZWEIG, "")]),
    # Der MIME-Typ fehlt - das Frontend muesste wieder eine Endungsliste pflegen.
    ("kein MIME-Typ in der Antwort", [
        (MAIN, '        return JSONResponse({"ok": False, "binary": True, "mime": mime,\n'
               '                             "error": "Datei ist kein UTF-8-Text"})',
               '        return JSONResponse({"ok": False, "binary": True,\n'
               '                             "error": "Datei ist kein UTF-8-Text"})'),
    ]),
    # Der Codec-Text wandert zurueck in den Grund.
    ("der Grund ist wieder der Codec-Text", [
        (MAIN, '    except UnicodeDecodeError:', '    except UnicodeDecodeError as _ude:'),
        (MAIN, '                             "error": "Datei ist kein UTF-8-Text"})',
               '                             "error": str(_ude)})'),
    ]),
    # Die Quelle-Spalte zeigt wieder den Wurzelordner.
    ("Quelle-Spalte zurueck auf den Wurzelordner", [
        (KBM, "source: doc ? (doc.source_name || doc.url || f.path) : f.path,",
              "source: doc ? (doc.source_name || doc.url || \'\') : (folder.folder || \'\'),"),
    ]),
    # Eine Schranke des Endpunkts faellt weg - der Fix darf sie nicht gelockert
    # haben. Anker mit Kontext: die Zeile steht mehrfach in main.py.
    ("Existenzpruefung in file_read entfernt", [
        (MAIN, '    if not resolved.is_file():\n'
               '        return JSONResponse({"error": "Datei nicht gefunden"}, status_code=404)\n'
               '    try:\n'
               '        content = resolved.read_text(encoding="utf-8")',
               '    try:\n'
               '        content = resolved.read_text(encoding="utf-8")'),
    ]),
]

rc_ende = 1
try:
    rc, f = lauf()
    if rc != 0 or f != 0:
        print(f"ABBRUCH: Basis {TEST} nicht gruen (rc={rc}, FAIL={f})")
        sys.exit(2)
    print("Basis gruen.")
    gut = 0
    for name, patches in PROBEN:
        neu, verfehlt = {}, []
        for datei, anker, ersatz in patches:
            txt = neu.get(datei, sich[datei].decode())
            if txt.count(anker) != 1:
                verfehlt.append(f"{datei.name}: {txt.count(anker)}x")
                continue
            neu[datei] = txt.replace(anker, ersatz, 1)
        if verfehlt:
            print(f"  VERFEHLT {name}: Anker {', '.join(verfehlt)}")
            continue
        for datei, txt in neu.items():
            datei.write_text(txt, encoding="utf-8")
        try:
            rc, f = lauf()
        finally:
            for datei in neu:
                datei.write_bytes(sich[datei])
        # ⚠ EIN ABSTURZ IST KEIN BISS: Exit 2 heisst "konnte nicht laufen".
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
