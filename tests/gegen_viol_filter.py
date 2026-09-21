#!/usr/bin/env python3
"""Gegenproben zum Benutzer-Filter der Zugriffs-Verstoesse.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob ein Waechter das
meldet. Eine Probe, die nicht beisst, ist ein Testmangel – kein Beweis.

⚠ SICHERUNG: jede angefasste Datei wird VOR dem Lauf auf Platte gesichert und
danach byte-genau zurueckgestellt. Eine Laufmarke faengt den Fall ab, dass der
Lauf abgeschossen wird (dann bleibt der Rueckstand liegen und der naechste
Start nimmt ihn selbst zurueck).
"""
import atexit
import hashlib
import io
import os
import pathlib
import signal
import subprocess
import sys

WURZEL = pathlib.Path(__file__).resolve().parent.parent
ABLAGE = pathlib.Path(os.path.expanduser("~")) / ".gegen-violfilter"
MARKE = ABLAGE / "LAUFT"

DATEIEN = [
    "backend/security_guard.py",
    "backend/main.py",
    "frontend/js/security_incidents.js",
    "frontend/js/i18n.js",
    "frontend/settings.html",
    "frontend/css/style.css",
    # Die Waechter selbst: eine Probe sabotiert sie, um zu pruefen, ob ein
    # zahnloser Waechter auffaellt.
    "tests/test_viol_filter.py",
    "tests/test_viol_filter_ui.js",
]


def _pfad(rel):
    return WURZEL / rel


def _ablage(rel):
    z = ABLAGE / rel
    z.parent.mkdir(parents=True, exist_ok=True)
    return z


def sichern():
    ABLAGE.mkdir(parents=True, exist_ok=True, mode=0o700)
    for rel in DATEIEN:
        _ablage(rel).write_bytes(_pfad(rel).read_bytes())
    MARKE.write_text("1")


def zurueck(still=False):
    fehler = []
    for rel in DATEIEN:
        q = _ablage(rel)
        if not q.exists():
            continue
        _pfad(rel).write_bytes(q.read_bytes())
        if hashlib.md5(_pfad(rel).read_bytes()).hexdigest() != \
           hashlib.md5(q.read_bytes()).hexdigest():
            fehler.append(rel)
    if fehler:
        print("⚠ NICHT zurueckgestellt: %s" % fehler)
    if MARKE.exists():
        MARKE.unlink()
    if not still:
        print("  (Arbeitsbaum wiederhergestellt)")


def lauf(cmd):
    r = subprocess.run(cmd, cwd=WURZEL, shell=True, capture_output=True, text=True)
    aus = (r.stdout or "") + (r.stderr or "")
    fails = aus.count("✗")
    hat_bilanz = "Ergebnis:" in aus
    return r.returncode, fails, hat_bilanz, aus


def ersetze(rel, alt, neu, anzahl=1):
    p = _pfad(rel)
    s = io.open(p, encoding="utf-8").read()
    if s.count(alt) < anzahl:
        raise AssertionError("SABOTAGE TRIFFT NICHT (%dx) in %s: %.70s"
                             % (s.count(alt), rel, alt))
    io.open(p, "w", encoding="utf-8").write(s.replace(alt, neu, anzahl))


# ── Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen ──────────────
if MARKE.exists():
    print("Rueckstand eines frueheren Laufs gefunden – nehme ihn zurueck.")
    zurueck(still=True)

PROBEN = []


def probe(name, fn, cmd):
    PROBEN.append((name, fn, cmd))


PY_W = "python3 tests/test_viol_filter.py"
JS_W = "node tests/test_viol_filter_ui.js"

# ── 1: der Filter wirkt NACH dem Schnitt (der eigentliche Fehler) ───────────
probe("Filter erst NACH dem Schnitt (nachtraeglich)",
      lambda: ersetze("backend/security_guard.py",
                      """    if user_filter:
        # VOR dem Schnitt""",
                      """    flat.sort(key=lambda x: x.get("ts", 0), reverse=True)
    flat = flat[:limit]
    if user_filter:
        # NACH dem Schnitt"""),
      PY_W)

# ── 2: gar kein Filter ──────────────────────────────────────────────────────
probe("Filter-Argument wird ignoriert",
      lambda: ersetze("backend/security_guard.py",
                      "    if user_filter:\n", "    if False:\n"),
      PY_W)

# ── 3: nur roh vergleichen (Domaenen-Praefix bricht) ────────────────────────
probe("nur roh vergleichen, nicht normalisiert",
      lambda: ersetze("backend/security_guard.py",
                      '                or (f_norm and norm_user(e.get("user") or "") == f_norm)',
                      "                or False"),
      PY_W)

# ── 4: Teiltreffer erlauben (ein Name ist kein Suchbegriff) ─────────────────
probe("Teiltreffer statt Gleichheit",
      lambda: ersetze("backend/security_guard.py",
                      '                if (e.get("user") or "").strip().lower() == f_roh',
                      '                if f_roh in (e.get("user") or "").strip().lower()'),
      PY_W)

# ── 5: Benutzerliste aus der ANGEZEIGTEN Liste statt dem Speicher ──────────
probe("Benutzerliste nur aus den neuesten 150",
      lambda: ersetze("backend/security_guard.py",
                      "    return [u for u, _ in sorted(letzte.items(), key=lambda p: (-p[1], p[0]))]",
                      "    return sorted({e.get('user') for e in list_recent_violations(150) if e.get('user')})"),
      PY_W)

# ── 6: Eintraege ohne Benutzer werden angeboten ─────────────────────────────
probe("Eintrag ohne Benutzer landet im Pulldown",
      lambda: ersetze("backend/security_guard.py",
                      '        user = e.get("user") or ""\n        if not user:\n            continue',
                      '        user = e.get("user") or "?"'),
      PY_W)

# ── 7: Endpunkt reicht den Filter nicht durch ───────────────────────────────
probe("Endpunkt ignoriert ?user=",
      lambda: ersetze("backend/main.py",
                      "    liste = security_guard.list_recent_violations(150, user_filter=uf)",
                      "    liste = security_guard.list_recent_violations(150)"),
      PY_W)

# ── 8: Endpunkt liefert keine Benutzerliste ─────────────────────────────────
probe("Endpunkt liefert 'users' nicht mit",
      lambda: ersetze("backend/main.py",
                      "    for n in _mit_anzeigenamen(security_guard.known_violation_users()):",
                      "    for n in []:  # known_violation_users"),
      PY_W)

# ── 9: 'gesamt' aus der GEFILTERTEN Liste (Zaehler luegt) ───────────────────
probe("'gesamt' wird aus der gefilterten Liste gerechnet",
      lambda: ersetze("backend/main.py",
                      "    voll = liste if not uf else security_guard.list_recent_violations(150)",
                      "    voll = liste"),
      PY_W)

# ── 10: Client filtert selbst statt den Server zu fragen ───────────────────
probe("Client haengt ?user= nicht an (filtert also nicht)",
      lambda: ersetze("frontend/js/security_incidents.js",
                      "            if (u) url += '?user=' + encodeURIComponent(u);",
                      "            /* kein Parameter */"),
      JS_W)

# ── 11: Wechsel loest keinen neuen Abruf aus ────────────────────────────────
probe("Wechsel im Pulldown loest keinen Abruf aus",
      lambda: ersetze("frontend/js/security_incidents.js",
                      "                sel.addEventListener('change', function () { Mgr.loadViolations(); });",
                      "                /* kein Zuhoerer */"),
      JS_W)

# ── 12: Zaehler nimmt die gefilterten Zahlen ────────────────────────────────
probe("Zaehler nennt die GEFILTERTEN Zahlen",
      lambda: ersetze("frontend/js/security_incidents.js",
                      "            var g = Mgr._violGesamt\n                || { hart: hart, weich: weich, anzahl: list.length };",
                      "            var g = { hart: hart, weich: weich, anzahl: list.length };"),
      JS_W)

# ── 13: Filterzeile ueber der Liste fehlt ───────────────────────────────────
probe("die Liste sagt nicht, dass sie gefiltert ist",
      lambda: ersetze("frontend/js/security_incidents.js",
                      "            if (uf) {\n                hinweis += '<p class=\"kb-hint sec-viol-hidden\">'",
                      "            if (false) {\n                hinweis += '<p class=\"kb-hint sec-viol-hidden\">'"),
      JS_W)

# ── 14: Leermeldung luegt wieder ────────────────────────────────────────────
probe("Leermeldung behauptet 'nichts passiert' trotz Filter",
      lambda: ersetze("frontend/js/security_incidents.js",
                      "                } else if (uf) {",
                      "                } else if (false) {"),
      JS_W)

# ── 15: Name per innerHTML ins Pulldown ─────────────────────────────────────
probe("Benutzername unmaskiert ins Pulldown",
      lambda: ersetze("frontend/js/security_incidents.js",
                      "                o.value = u; o.textContent = u;",
                      "                o.value = u; o.innerHTML = u;"),
      JS_W)

# ── 16: Auswahl faellt beim Neuaufbau weg ───────────────────────────────────
probe("nicht mehr gelisteter Benutzer springt stumm auf 'Alle'",
      lambda: ersetze("frontend/js/security_incidents.js",
                      "            if (cur && alle.indexOf(cur) === -1) alle.push(cur);",
                      "            /* nicht beibehalten */"),
      JS_W)

# ── 17: Kaestchen verschwindet bei leerer gefilterter Liste ────────────────
probe("Kaestchen 'Nur Verstoesse' haengt an der gefilterten Liste",
      lambda: ersetze("frontend/js/security_incidents.js",
                      "            if (box2) box2.hidden = !g.anzahl;",
                      "            if (box2) box2.hidden = !list.length;"),
      JS_W)

# ── 18: Benutzer-Filter wird gemerkt (verbirgt fremde Verstoesse) ──────────
probe("Benutzer-Filter wird im localStorage gemerkt",
      lambda: ersetze("frontend/js/security_incidents.js",
                      "                sel.addEventListener('change', function () { Mgr.loadViolations(); });",
                      "                sel.addEventListener('change', function () { "
                      "try { localStorage.setItem('jarvis_sec_viol_user', sel.value); } catch (e) {} "
                      "Mgr.loadViolations(); });"),
      JS_W)

# ── 19: Pulldown zurueck ins <summary> ──────────────────────────────────────
probe("Pulldown steht wieder im <summary> (klappt den Abschnitt zu)",
      lambda: (
          ersetze("frontend/settings.html",
                  '                                        <span class="sec-sub-hint" id="sec-viol-count"></span>',
                  '                                        <span class="sec-sub-hint" id="sec-viol-count"></span>\n'
                  '                                        <select id="sec-viol-user" class="sec-viol-user">'
                  '<option value="">Alle Benutzer</option></select>'),
          ersetze("frontend/settings.html",
                  '                                            <select id="sec-viol-user" class="sec-viol-user">\n'
                  '                                                <option value="" data-i18n="security.viol_all_users">Alle Benutzer</option>\n'
                  '                                            </select>\n', '')),
      JS_W)

# ── 20: Pulldown ganz aus dem Markup ────────────────────────────────────────
probe("Pulldown fehlt im Markup",
      lambda: ersetze("frontend/settings.html", 'id="sec-viol-user"', 'id="sec-viol-user-weg"', 1),
      JS_W)

# ── 21: i18n nur deutsch ────────────────────────────────────────────────────
probe("Filterzeile nur auf Deutsch (EN-Schluessel fehlt)",
      lambda: ersetze("frontend/js/i18n.js",
                      "        'security.viol_user_active':    'Filtered by {u}: {n} of {m} entries.',\n", ""),
      JS_W)

# ── 22: CSS min-width raus ──────────────────────────────────────────────────
probe("min-width: 0 am Pulldown entfernt",
      lambda: ersetze("frontend/css/style.css",
                      ".sec-viol-user {\n    min-width: 0;\n", ".sec-viol-user {\n"),
      JS_W)

def main():
    sichern()
    atexit.register(zurueck, True)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *_: (zurueck(True), sys.exit(130)))

    # Basislauf: ohne gruene Basis ist keine Gegenprobe deutbar.
    print("\033[1mBasislauf\033[0m")
    basis_ok = True
    for cmd in (PY_W, JS_W):
        rc, f, bil, aus = lauf(cmd)
        zeile = [l for l in aus.splitlines() if "Ergebnis:" in l]
        print("  %-42s rc=%d  %s" % (cmd, rc, zeile[-1].strip() if zeile else "(KEINE BILANZ)"))
        if rc != 0 or not bil:
            basis_ok = False
    if not basis_ok:
        print("\033[31mABBRUCH: Basis ist nicht gruen – Gegenproben waeren nicht deutbar.\033[0m")
        zurueck()
        return 2

    print("\n\033[1mGegenproben\033[0m")
    beissen = 0
    for i, (name, fn, cmd) in enumerate(PROBEN, 1):
        try:
            fn()
        except AssertionError as e:
            print("  \033[33m%2d. %-58s %s\033[0m" % (i, name, e))
            zurueck(still=True)
            sichern()
            continue
        rc, f, bil, aus = lauf(cmd)
        zurueck(still=True)
        sichern()
        # Gemessen wird der EXIT-CODE samt Bilanzzeile, nicht das Zaehlen von
        # FAIL-Zeilen: ein Lauf, der ohne Bilanz abbricht, hat nichts gemessen.
        if not bil:
            print("  \033[33m%2d. %-58s ABGEBROCHEN (keine Bilanz)\033[0m" % (i, name))
        elif rc != 0:
            beissen += 1
            print("  \033[32m%2d. %-58s beisst (%d FAIL)\033[0m" % (i, name, f))
        else:
            print("  \033[31m%2d. %-58s BEISST NICHT\033[0m" % (i, name))

    gesamt = len(PROBEN)
    print("\n\033[1mErgebnis: %d/%d Proben beissen\033[0m" % (beissen, gesamt))
    zurueck()
    return 0 if beissen == gesamt else 1


if __name__ == "__main__":
    sys.exit(main())
