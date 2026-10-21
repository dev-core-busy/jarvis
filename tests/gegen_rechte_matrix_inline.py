"""Gegenprobe zu test_rechte_matrix_ui, Abschnitt 11 (Tabelle auf der Seite statt
im Popup, 2026-10-21).

Dreht je EINE Zusage des Umbaus in einer Plattenkopie zurueck und erwartet FAILs
MIT Bilanzzeile; stellt danach byte-gleich wieder her (md5).

Gemessen werden die drei Stellen, an denen der Umbau etwas KAPUTT machen kann –
im Popup gab es sie nicht, weil der Bestand "beim Oeffnen" gelesen wurde:
  1. Kein Signal nach dem AD-Abruf  -> die Tabelle bleibt leer, ohne Fehler.
  2. Signal nur im Erfolgsfall      -> nach einem Abbruch ewig "laedt…".
  3. Keine Beobachtung der Bereiche -> ein spaet eingeblendeter Bereich fehlt.
  4. Nachladen wirft offene Haken weg (stiller Datenverlust).
  5. Der eigene Speicherlauf baut NICHT durch (der gespeicherte Stand kommt nie).
  6. "Verwerfen" nimmt nichts zurueck.
  7. Das Popup ist zurueck (Markup ohne #rmx-host).

Exit 0 = alle beissen, 1 = mindestens eine zahnlos, 2 = Basis nicht gruen.
"""
import hashlib, os, re, subprocess, sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
HTML = W / "frontend/settings.html"
RMX = W / "frontend/js/rechte_matrix.js"
AD = W / "frontend/js/settings_ad.js"
TEST = "test_rechte_matrix_ui.js"
# ⚠ DIE TESTDATEI SELBST GEHOERT IN DIE SICHERUNGSLISTE, auch wenn keine Probe
# sie anfasst – zweimal darauf hereingefallen (Register).
DATEIEN = [HTML, RMX, AD, W / "tests" / TEST]
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()
vorher = {p: md5(p) for p in DATEIEN}
sich = {p: p.read_bytes() for p in DATEIEN}
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def lauf():
    r = subprocess.run(["node", str(W / "tests" / TEST)],
                       capture_output=True, text=True, env=env, timeout=300)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None)


# (Name, [(Datei, Anker, Ersatz), …])
PROBEN = [
    ("kein Signal nach dem AD-Abruf", [
        (AD, "            document.dispatchEvent(new CustomEvent('jarvis-ad-geladen',\n"
             "                { detail: { ok: !!window._adGeladen } }));",
             "            void 0;"),
    ]),
    # ⚠ NUR IM ERFOLGSFALL GEMELDET: der haeufigste Fehler beim Nachruesten
    # eines Signals. Solange alles klappt, faellt nichts auf – nach einem
    # Abbruch steht die Anzeige ewig auf "laedt…" und behauptet einen Zustand,
    # den sie nicht kennt. Eine Zeile, syntaktisch sicher: eine Sabotage, die
    # die Datei zerlegt, laesst den Waechter abstuerzen und misst nichts.
    ("Signal nur im Erfolgsfall", [
        (AD, "            document.dispatchEvent(new CustomEvent('jarvis-ad-geladen',",
             "            if (window._adGeladen) document.dispatchEvent(new CustomEvent('jarvis-ad-geladen',"),
    ]),
    ("Bereiche werden nicht beobachtet", [
        (RMX, "        aufbauen();\n        sichtbarkeitBeobachten();",
              "        aufbauen();"),
    ]),
    ("Nachladen wirft offene Haken weg", [
        (RMX, "        if (aenderungen()) {\n"
              "            fussAktualisieren();\n"
              "            status(T('rmx.reloaded_pending'), true);\n"
              "            return;\n"
              "        }\n",
              ""),
    ]),
    ("der eigene Speicherlauf baut nicht durch", [
        (RMX, "        _eigenerSpeicherlauf = true;\n        var ok = await window._adSave();",
              "        var ok = await window._adSave();"),
    ]),
    ("Verwerfen nimmt nichts zurueck", [
        (RMX, "el('rmx-cancel').addEventListener('click', function () { aufbauen(); });",
              "el('rmx-cancel').addEventListener('click', function () { /* nichts */ });"),
    ]),
    ("das Popup ist zurueck (kein #rmx-host im Markup)", [
        (HTML, '<div class="rmx-inline" id="rmx-host"></div>',
               '<div class="rmx-inline"></div>'),
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
        # ⚠ EIN ABSTURZ IST KEIN BISS: Exit 2 heisst "konnte nicht laufen" und
        # ist von einem Befund nicht zu unterscheiden.
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
