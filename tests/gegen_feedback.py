#!/usr/bin/env python3
"""Gegenproben zum Feedback-Skill: beisst jeder Waechter EINZELN?

Jede Probe dreht GENAU EINE Zusage zurueck und erwartet, dass der zugehoerige
Waechter das meldet. Beisst eine nicht, ist das ein TESTMANGEL – kein Beweis.

⚠ SICHERUNG AUF PLATTE mit LAUFMARKE. Wird der Lauf abgeschossen (Zeitlimit,
kill -9), bleibt der Arbeitsbaum sonst sabotiert zurueck, und der naechste
Testlauf meldet einen Fehler, den der Code nicht hat (Register: zweimal
bezahlt). Die Marke wird beim geordneten Ende abgeraeumt; liegt sie beim Start
noch da, wird zuerst zurueckgenommen.

⚠ JEDE DATEI, DIE EINE PROBE ANFASST, MUSS IN `DATEIEN` STEHEN – das wird als
REGEL geprueft, nicht gepflegt (Register: die Testdatei selbst fehlte einmal in
der Liste, und die letzte Sabotage blieb stehen).
"""
import atexit
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ABLAGE = pathlib.Path.home() / ".gegen-feedback"
MARKE = ABLAGE / ".laeuft"

DATEIEN = [
    "backend/feedback.py",
    "backend/main.py",
    "backend/sandbox.py",
    "frontend/js/feedback.js",
    "frontend/js/feedback_admin.js",
    "frontend/js/app.js",
    "frontend/feedback.html",
    "frontend/settings.html",
    "frontend/css/feedback.css",
    "frontend/js/i18n.js",
    "frontend/portal.html",
    "tests/test_feedback.py",
    "tests/test_feedback_ui.js",
]

BACKEND = ["python3", str(ROOT / "tests" / "test_feedback.py")]
UI = ["node", str(ROOT / "tests" / "test_feedback_ui.js")]

# (Name, Datei, alt, neu, Kommando)
PROBEN = [
    # ── Backend ────────────────────────────────────────────────────────────
    ("unbekannter Spaltentyp wird durchgelassen", "backend/feedback.py",
     "        if typ not in SPALTEN_TYPEN:",
     "        if False:", BACKEND),
    # ⚠ NACHGEZOGEN 2026-09-15: die Bedingung traegt jetzt zusaetzlich die
    # Laengengrenze. Eine Probe, die ihren Anker nicht mehr findet, meldet
    # „trifft nicht" und sieht wie ein zahnloser Waechter aus.
    ("die Spalten-Kennung wird beim Bearbeiten neu vergeben", "backend/feedback.py",
     "        if not sid or sid in gesehen or not sid.isalnum() or len(sid) > _ID_MAX:",
     "        if True:", BACKEND),
    ("unbekannte Spalten landen in der Abgabe", "backend/feedback.py",
     "        for sp in spalten:\n            anzeige, wert = _zelle_pruefen(sp, z.get(sp[\"id\"]))",
     "        for sp in spalten:\n            zeile.update({k: v for k, v in z.items()})\n            anzeige, wert = _zelle_pruefen(sp, z.get(sp[\"id\"]))",
     BACKEND),
    ("Sterne werden nicht begrenzt", "backend/feedback.py",
     "        n = max(0, min(STERNE_MAX, n))",
     "        n = n", BACKEND),
    ("leere Zeilen bleiben stehen", "backend/feedback.py",
     "        if gefuellt:\n            raus.append(zeile)",
     "        if True:\n            raus.append(zeile)", BACKEND),
    ("der Benutzer wird nicht normiert", "backend/feedback.py",
     '        "benutzer": _norm(user),',
     '        "benutzer": user,', BACKEND),
    ("die Abgabe speichert die Spalten NICHT mit", "backend/feedback.py",
     '        "spalten": [{"id": s["id"], "name": s["name"], "typ": s["typ"]}\n'
     '                    for s in spalten],',
     '        "spalten": [],', BACKEND),
    ("`aktiv` wird ueber Falsyness geprueft", "backend/feedback.py",
     '        raus = [f for f in raus if f.get("aktiv") is not False]',
     '        raus = [f for f in raus if f.get("aktiv")]', BACKEND),
    ("das Loeschen eines Formulars nimmt die Abgaben mit", "backend/feedback.py",
     '        d["formulare"] = [f for f in d["formulare"] if f.get("id") != fid]\n'
     "        _speichern(d)",
     '        d["formulare"] = [f for f in d["formulare"] if f.get("id") != fid]\n'
     "        _speichern(d)\n"
     "        _abgaben_schreiben([a for a in _abgaben_lesen()\n"
     '                            if a.get("formular_id") != fid])', BACKEND),
    ("das Sortieren verwirft nicht genannte Formulare", "backend/feedback.py",
     '        raus += [f for f in vorhanden if f.get("id") not in gesehen]',
     "        raus += []", BACKEND),
    ("eine beschaedigte Datei wird ueberschrieben", "backend/feedback.py",
     '    except Exception:  # noqa: BLE001\n'
     '        return {"version": 1, "formulare": []}\n'
     "    if not isinstance(d, dict):",
     '    except Exception:  # noqa: BLE001\n'
     '        _speichern({"version": 1, "formulare": []})\n'
     '        return {"version": 1, "formulare": []}\n'
     "    if not isinstance(d, dict):", BACKEND),
    ("CSV-Injection wird NICHT entschaerft", "backend/feedback.py",
     "    if s.startswith(_CSV_GEFAEHRLICH):\n        return \"'\" + s",
     "    if False:\n        return \"'\" + s", BACKEND),
    ("das BOM fehlt", "backend/feedback.py",
     '"\\ufeff" + puffer.getvalue()', "puffer.getvalue()", BACKEND),
    ("eine entfernte Spalte faellt aus dem Export", "backend/feedback.py",
     '        for s in (a.get("spalten") or []):\n'
     '            if isinstance(s, dict) and s.get("id") and s["id"] not in gesehen:',
     '        for s in []:\n'
     '            if isinstance(s, dict) and s.get("id") and s["id"] not in gesehen:',
     BACKEND),
    ("der CSV-Dateiname wird nicht entschaerft", "backend/feedback.py",
     '    sicher = "".join(c if (c.isalnum() or c in " _-") else "_" for c in name).strip()',
     "    sicher = name", BACKEND),

    # ── Endpunkte / Verdrahtung ────────────────────────────────────────────
    ("ein Admin-Endpunkt haengt nur an require_auth", "backend/main.py",
     "async def feedback_admin_abgaben(fid: str = \"\", limit: int = 500,\n"
     "                                 user: str = Depends(require_local_auth)):",
     "async def feedback_admin_abgaben(fid: str = \"\", limit: int = 500,\n"
     "                                 user: str = Depends(require_auth)):", BACKEND),
    ("ein Benutzer-Endpunkt haengt nur an require_auth", "backend/main.py",
     "async def feedback_abgabe_senden(request: Request,\n"
     "                                 user: str = Depends(require_feedback_access)):",
     "async def feedback_abgabe_senden(request: Request,\n"
     "                                 user: str = Depends(require_auth)):", BACKEND),
    ("der Benutzer kommt aus dem Rumpf", "backend/main.py",
     "            fb.abgabe_speichern, user,",
     '            fb.abgabe_speichern, str((body or {}).get("user") or user),', BACKEND),
    ("die Datei-I/O laeuft im Event-Loop", "backend/main.py",
     "    liste = await asyncio.to_thread(fb.formulare, True)",
     "    liste = fb.formulare(True)", BACKEND),
    # ⚠ NACHGEZOGEN 2026-09-14: die eigene Freigabeliste ist entfallen, der
    # Bereich haengt an den Wissens-Editoren. Die Sabotage hebt genau das auf.
    # ⚠ Die Zusage lautet seit der Rueckfrage: DASSELBE Praedikat wie die
    # Wissen-Kachel. Beide Sabotagen greifen genau das an.
    ("die Freigabe haengt an gar nichts mehr", "backend/main.py",
     "        return bool(_editable_groups_for(u))",
     "        return True", BACKEND),
    ("Feedback haengt wieder am ENGEREN Praedikat als die Wissen-Kachel",
     "backend/main.py",
     "        return bool(_editable_groups_for(u))",
     "        return _may_edit_knowledge(u)", BACKEND),
    ("die Kachel haengt nicht mehr am Skill", "backend/main.py",
     '            "feedback": (_user_may_use_feedback(user)\n'
     '                         and _skill_active("feedback")),',
     '            "feedback": _user_may_use_feedback(user),', BACKEND),
    ("die Abgaben stehen nicht in der Sperrliste", "backend/sandbox.py",
     '    "data/feedback_formulare.json", "data/feedback_abgaben.jsonl",\n'
     "    # Verankerte SAP-Serverzertifikate",
     "    # Verankerte SAP-Serverzertifikate", BACKEND),
    ("eine Reiter-Sektion ist nicht gebunden", "frontend/js/app.js",
     "                { hdr: 'fb-sect-abg-hdr',  body: 'fb-sect-abg-body',  tog: 'fb-sect-abg-tog'  },\n",
     "", BACKEND),
    ("das Panel steht nicht in allSettingsTabs", "frontend/js/app.js",
     "tabEmail, tabTracks, tabExcel, tabFeedback, tabKundenverwaltung",
     "tabEmail, tabTracks, tabExcel, tabKundenverwaltung", BACKEND),
    # ⚠ ENTFALLEN 2026-09-14 mit dem Freigabe-Block selbst: die Probe zielte auf
    # dessen Hinweistext. Eine Probe, die ihr Ziel nicht mehr findet, bleibt
    # sonst dauerhaft als "trifft nicht" stehen und verwaessert die Bilanz.

    # ── Oberflaeche ────────────────────────────────────────────────────────
    ("die Tabelle wird nicht gezeichnet", "frontend/js/feedback.js",
     "        box.appendChild(wrap);",
     "        if (false) { box.appendChild(wrap); }", UI),
    ("die letzte Zeile wird entfernt statt geleert", "frontend/js/feedback.js",
     "                if (!_zeilen.length) { _zeilen.push(leereZeile()); }",
     "                if (false) { _zeilen.push(leereZeile()); }", UI),
    ("ein zweiter Klick auf denselben Stern setzt ihn erneut", "frontend/js/feedback.js",
     "                    var neu = (alt === stufe) ? 0 : stufe;",
     "                    var neu = stufe;", UI),
    ("die Sterne unterscheiden sich nur in der Farbe", "frontend/js/feedback.js",
     "                b.innerHTML = window.JarvisIcons.star(an);",
     "                b.innerHTML = window.JarvisIcons.star(false);", UI),
    ("die Zahl neben den Sternen fehlt", "frontend/js/feedback.js",
     "            anzeige.textContent = n ? (n + '/5') : '–';",
     "            anzeige.textContent = '';", UI),
    # ⚠ NACHGEZOGEN 2026-09-15: die Pruefung heisst jetzt `_zeilen.some(gefuellt)`
    # (sie muss `fest`-Spalten ausnehmen, sonst gilt jede feste Zeile als
    # ausgefuellt, nur weil ihr Kriterium dasteht).
    ("eine leere Abgabe wird trotzdem gesendet", "frontend/js/feedback.js",
     "        if (!_zeilen.some(gefuellt)) {",
     "        if (false) {", UI),
    ("die Auswahl erscheint auch bei EINEM Formular", "frontend/js/feedback.js",
     "        pick.classList.toggle('hidden', _formulare.length < 2);",
     "        pick.classList.toggle('hidden', false);", UI),
    ("die Knoepfe bleiben ohne Formular bedienbar", "frontend/js/feedback.js",
     "            if (b) { b.disabled = !_aktiv; }",
     "            if (b) { b.disabled = false; }", UI),
    ("eine eigene Abgabe nimmt die HEUTIGEN Spalten", "frontend/js/feedback.js",
     "        var spalten = a.spalten || [];\n"
     "\n"
     "        var thead = document.createElement('thead');\n"
     "        var kz = document.createElement('tr');",
     "        var spalten = (_aktiv && _aktiv.spalten) || [];\n"
     "\n"
     "        var thead = document.createElement('thead');\n"
     "        var kz = document.createElement('tr');", UI),
    ("ein Spaltenname wird als Markup gelesen", "frontend/js/feedback.js",
     "            th.textContent = s.name;          // textContent: Fremdtext",
     "            th.innerHTML = s.name;", UI),
    ("der Editor haengt nicht in der Karte", "frontend/js/feedback_admin.js",
     "            if (karte) { karte.appendChild(form); }",
     "            if (false) { karte.appendChild(form); }", UI),
    ("ein zweiter Klick auf Bearbeiten schliesst nicht", "frontend/js/feedback_admin.js",
     "            if (alt && !wieder && this._offen === (fid || '')) {",
     "            if (false) {", UI),
    ("der Aktiv-Schalter verliert die Spalten", "frontend/js/feedback_admin.js",
     "                          spalten: f.spalten || [], aktiv: !!an });",
     "                          spalten: [], aktiv: !!an });", UI),
    ("die Karten haben keinen Ziehgriff", "frontend/js/feedback_admin.js",
     "                    + griffMarkup(t('fbadm.drag', 'Reihenfolge ändern (ziehen oder Strg+Pfeil)'))",
     "                    + ''", UI),
    # ⚠ DER GEMELDETE FALL (2026-09-14): ohne diese Zeile ist `window.FeedbackAdmin`
    # undefined, `app.js` faengt das mit `if (window.FeedbackAdmin)` ab – und der
    # Reiter bleibt STILL leer. Der UI-Waechter kann das nicht sehen: er laedt die
    # Datei selbst.
    # ⚠ OHNE CACHE-BUSTER IM ANKER: die erste Fassung suchte `?v=1` und traf
    # nach dem naechsten Hochzaehlen nicht mehr – eine Probe, die ihr Ziel
    # verfehlt, sieht wie ein zahnloser Waechter aus (2026-09-15 passiert).
    ("feedback_admin.js wird gar nicht eingebunden", "frontend/settings.html",
     'src="/static/js/feedback_admin.js', 'src="/static/js/gibtesnicht.js', BACKEND),
    ("der Loeschknopf traegt ein × statt des Muelleimers", "frontend/js/feedback_admin.js",
     "                    + window.JarvisIcons.trash() + '</button>'\n"
     "                    + '</div></div>';",
     "                    + '×</button>'\n"
     "                    + '</div></div>';", UI),

    # ── Feste Zeilen + Spaltentyp `fest` (2026-09-15) ──────────────────────
    # Die tragende Zusage zuerst: der feste Text kommt aus der DEFINITION.
    ("⚠ der feste Text kommt aus dem REQUEST", "backend/feedback.py",
     '                zeile[sp["id"]] = (fz.get("werte") or {}).get(sp["id"], "")',
     '                zeile[sp["id"]] = geliefert.get(sp["id"], "")', BACKEND),
    ("die Regel `fest` braucht feste Zeilen ist ausgebaut", "backend/feedback.py",
     '        if any(s["typ"] == TYP_FEST for s in sp) and not fz:',
     "        if False:", BACKEND),
    ("ein Formular nur aus `fest`-Spalten wird angenommen", "backend/feedback.py",
     '    if all(s["typ"] == TYP_FEST for s in raus):',
     "    if False:", BACKEND),
    ("die Reihenfolge kommt aus dem Request", "backend/feedback.py",
     "    for fz in feste:\n"
     "        geliefert = eingang.get(fz[\"id\"]) or {}",
     "    for fz in [eingang.get(f2[\"id\"]) or f2 for f2 in reversed(feste)]:\n"
     "        geliefert = eingang.get(fz.get(\"id\")) or {}", BACKEND),
    # ⚠ `gefuellt` gilt ueber ALLE Zeilen. Eine Sabotage `if gefuellt: append`
    # ist deshalb wirkungslos, sobald die erste Zeile etwas traegt – sie sah wie
    # ein zahnloser Waechter aus und war eine schlecht platzierte Probe.
    ("leere feste Zeilen fallen aus der Abgabe", "backend/feedback.py",
     "        raus.append(zeile)\n    if not gefuellt:",
     "        if any(zeile.get(s2[\"id\"]) for s2 in spalten if s2[\"typ\"] != TYP_FEST):\n"
     "            raus.append(zeile)\n    if not gefuellt:", BACKEND),
    ("eine Abgabe ohne jede Eingabe wird angenommen", "backend/feedback.py",
     "    if not gefuellt:\n"
     '        raise FeedbackFehler("Es ist keine einzige Zeile ausgefuellt.")\n'
     "    return raus",
     "    if False:\n"
     '        raise FeedbackFehler("Es ist keine einzige Zeile ausgefuellt.")\n'
     "    return raus", BACKEND),
    ("die Zeilen-Kennung wird neu vergeben", "backend/feedback.py",
     "        if not zid or zid in gesehen or not zid.isalnum() or len(zid) > _ID_MAX:",
     "        if True:", BACKEND),
    ("die Zeilen-Kennung fehlt in der Abgabe", "backend/feedback.py",
     '        zeile: dict = {ZEILEN_ID: fz["id"]}',
     "        zeile: dict = {}", BACKEND),
    ("ein Vorgabewert wird auch fuer Text-Spalten uebernommen", "backend/feedback.py",
     "            for sid in fest_ids:",
     "            for sid in list(roh_werte.keys()):", BACKEND),
    ("die Kennung ist wieder unbegrenzt lang", "backend/feedback.py",
     "_ID_MAX = 32", "_ID_MAX = 10 ** 9", BACKEND),
    ("der Sentinel ist weg – ein alter Client loescht die Zeilen",
     "backend/main.py",
     '    zeilen = body.get("zeilen") if "zeilen" in body else fb._ZEILEN_UNGESETZT',
     '    zeilen = body.get("zeilen")', BACKEND),

    # ── Oberflaeche ────────────────────────────────────────────────────────
    # ⚠ EINDEUTIGER ANKER: `if (s.typ === TYP_FEST) {` steht viermal in der
    # Datei – die erste Fassung meldete „trifft nicht (4x)".
    ("die feste Zelle wird als Eingabefeld gerendert", "frontend/js/feedback.js",
     "                    td.className = 'fb-c-fest';",
     "                    td.className = 'fb-c-egal'; if (false)", UI),
    ("die festen Zeilen werden gar nicht aufgebaut", "frontend/js/feedback.js",
     "        _zeilen = _aktiv ? zeilenAufbauen() : [];",
     "        _zeilen = _aktiv ? [leereZeile()] : [];", UI),
    ("der Muelleimer bleibt bei festen Zeilen stehen", "frontend/js/feedback.js",
     "            if (fest) {\n                tbody.appendChild(tr);\n                return;\n            }",
     "            if (false) {\n                tbody.appendChild(tr);\n                return;\n            }", UI),
    ("„+ Zeile\" bleibt bei festen Zeilen sichtbar", "frontend/js/feedback.js",
     "        if (neu) { neu.classList.toggle('hidden', !!(_aktiv && festeZeilen().length)); }",
     "        if (neu) { neu.classList.toggle('hidden', false); }", UI),
    ("der Handler laesst eine erzwungene Zeile zu", "frontend/js/feedback.js",
     "                if (!_aktiv || festeZeilen().length) { return; }",
     "                if (!_aktiv) { return; }", UI),
    ("nur die gefuellten festen Zeilen gehen raus", "frontend/js/feedback.js",
     "        var voll = (fest ? _zeilen : _zeilen.filter(gefuellt)).map(function (z) {",
     "        var voll = _zeilen.filter(gefuellt).map(function (z) {", UI),
    ("⚠ der feste Text wird mitgeschickt", "frontend/js/feedback.js",
     "                if (s.typ !== TYP_FEST) { raus[s.id] = z[s.id]; }",
     "                raus[s.id] = z[s.id];", UI),
    ("die Zeilen-Kennung geht nicht mit", "frontend/js/feedback.js",
     "            if (z[ZEILEN_ID]) { raus[ZEILEN_ID] = z[ZEILEN_ID]; }",
     "            if (false) { raus[ZEILEN_ID] = z[ZEILEN_ID]; }", UI),
    ("eine `fest`-Spalte zaehlt als ausgefuellt", "frontend/js/feedback.js",
     "                if (s.typ === TYP_FEST) { return false; }",
     "                if (false) { return false; }", UI),
    ("der Typname driftet gegen das Backend", "frontend/js/feedback.js",
     "    var TYP_FEST = 'fest';", "    var TYP_FEST = 'festtext';", BACKEND),
    ("die Zeilen-Kennung driftet gegen das Backend", "frontend/js/feedback.js",
     "    var ZEILEN_ID = '_zid';", "    var ZEILEN_ID = '_zeile';", BACKEND),
    ("der Editor zieht die Zeilen bei einem Typwechsel nicht nach",
     "frontend/js/feedback_admin.js",
     "                        Admin._entwurf[i].typ = typ.value;",
     "                        Admin._entwurf[i].typ = typ.value; return;", UI),
    ("der Editor vergibt keine Spalten-Kennung", "frontend/js/feedback_admin.js",
     "function neueKennung() {", "function _unbenutzt_neueKennung() {", BACKEND),
    ("der Zeilen-Arbeitsstand ist eine REFERENZ, kein Kopie",
     "frontend/js/feedback_admin.js",
     "                    Object.keys(z.werte || {}).forEach(function (k) { w[k] = z.werte[k]; });\n"
     "                    return { id: z.id, werte: w };",
     "                    return { id: z.id, werte: z.werte };", BACKEND),
    ("der Editor schickt die festen Zeilen nicht mit",
     "frontend/js/feedback_admin.js",
     "                zeilen: this._zeilen || [],", "", UI),
    ("`min-width: 0` fehlt – der Muelleimer wandert aus der Zeile",
     "frontend/css/feedback.css",
     ".fb-z .fb-z-wert { flex: 1 1 auto; min-width: 0; }",
     ".fb-z .fb-z-wert { flex: 1 1 auto; }", BACKEND),
    ("die feste Zelle ist gedaempft (unter 4,5:1)", "frontend/css/feedback.css",
     "    color: var(--text-primary); font-weight: 600;",
     "    color: var(--text-muted); font-weight: 600;", BACKEND),
    ("die `.hidden`-Regel fehlt wieder (Bestandsfehler)",
     "frontend/css/feedback.css",
     ".hidden { display: none !important; }", "", BACKEND),
    ("ein i18n-Text fehlt auf Englisch", "frontend/js/i18n.js",
     "        'fbadm.typ_fest':        'Fixed text (read-only)',", "", BACKEND),
    # Der dritte Hinweis-Zustand: `fest`-Spalte, aber (noch) keine Zeile.
    ("der Hinweis kennt den nicht speicherbaren Zustand nicht",
     "frontend/js/feedback_admin.js",
     "                var lage = !feste.length ? 'frei'\n"
     "                    : ((this._zeilen || []).length ? 'fest' : 'fehlt');",
     "                var lage = !feste.length ? 'frei' : 'fest';", UI),
]


def sichern():
    ABLAGE.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        z = ABLAGE / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, z)     # ⚠ IMMER erneuern: eine alte Sicherung
                                        # stellt einen veralteten Stand her.
    MARKE.write_text("laeuft", encoding="utf-8")


def zurueck():
    for rel in DATEIEN:
        z = ABLAGE / rel.replace("/", "__")
        if z.exists():
            shutil.copy2(z, ROOT / rel)
    if MARKE.exists():
        MARKE.unlink()


def lauf(cmd):
    """(Exit, hat_bilanz, FAIL-Zahl). Eine fehlende Bilanzzeile ist ein
    Abbruch – und der ist von „nicht gelaufen" nicht zu unterscheiden."""
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT),
                       timeout=300, env={**__import__("os").environ,
                                         "JSDOM_PATH": "node_modules/jsdom"})
    aus = r.stdout + r.stderr
    m = re.search(r"(\d+) OK, (\d+) FAIL", aus)
    return r.returncode, bool(m), int(m.group(2)) if m else -1


def main():
    # ⚠ REGEL statt Pflege: jede angefasste Datei muss gesichert werden.
    fehlend = sorted({p[1] for p in PROBEN} - set(DATEIEN))
    if fehlend:
        print("ABBRUCH: nicht gesicherte Dateien in PROBEN: %r" % fehlend)
        sys.exit(2)

    if MARKE.exists():
        print("⚠ Rueckstand eines abgeschossenen Laufs – nehme ihn zurueck")
        zurueck()

    sichern()
    atexit.register(zurueck)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *a: (zurueck(), sys.exit(1)))

    # ⚠ OHNE GRUENE BASIS IST KEINE GEGENPROBE DEUTBAR.
    print("Basislauf…")
    for name, cmd in (("Backend", BACKEND), ("UI", UI)):
        rc, bil, f = lauf(cmd)
        if rc != 0 or not bil:
            print("ABBRUCH: Basislauf %s nicht gruen (exit=%s, bilanz=%s, fail=%s)"
                  % (name, rc, bil, f))
            sys.exit(2)
        print("  Basis %s: gruen" % name)

    beissen = nicht = 0
    for name, rel, alt, neu, cmd in PROBEN:
        datei = ROOT / rel
        s = datei.read_text(encoding="utf-8")
        if s.count(alt) != 1:
            # ⚠ EINE ERSETZUNG OHNE TREFFERKONTROLLE IST KEIN MESSWERT: die
            # Probe saehe wie ein zahnloser Waechter aus, obwohl sie ihr Ziel
            # gar nicht getroffen hat.
            print("  \033[33m?\033[0m %-58s SABOTAGE TRIFFT NICHT (%dx)"
                  % (name, s.count(alt)))
            nicht += 1
            continue
        datei.write_text(s.replace(alt, neu, 1), encoding="utf-8")
        rc, bil, f = lauf(cmd)
        datei.write_text(s, encoding="utf-8")
        if rc != 0 and bil and f > 0:
            print("  \033[32m✓\033[0m %-58s beisst (%d FAIL)" % (name, f))
            beissen += 1
        elif rc != 0 and not bil:
            print("  \033[33m!\033[0m %-58s BRICHT AB ohne Bilanz" % name)
            nicht += 1
        else:
            print("  \033[31m✗\033[0m %-58s BEISST NICHT" % name)
            nicht += 1

    print("\n" + "=" * 78)
    print("beissen: %d von %d" % (beissen, len(PROBEN)))
    sys.exit(1 if nicht else 0)


if __name__ == "__main__":
    main()
