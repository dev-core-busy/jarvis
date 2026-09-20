#!/usr/bin/env python3
"""Gegenproben zum Suchfeld im Kopf der Einstellungen: beisst jeder Waechter
EINZELN?

Jede Probe dreht GENAU EINE Zusage zurueck und erwartet, dass der zugehoerige
Waechter das meldet. Beisst eine nicht, ist das ein TESTMANGEL – kein Beweis;
und die erste Frage ist dann, ob die Zusage ueberhaupt existiert.

⚠ SICHERUNG AUF PLATTE mit LAUFMARKE. Wird der Lauf abgeschossen (Zeitlimit,
kill -9), bleibt der Arbeitsbaum sonst sabotiert zurueck, und der naechste
Testlauf meldet einen Fehler, den der Code nicht hat.

⚠ JEDE DATEI, DIE EINE PROBE ANFASST, MUSS IN `DATEIEN` STEHEN – als REGEL
geprueft, nicht gepflegt.
"""
import atexit
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ABLAGE = pathlib.Path.home() / ".gegen-settings-suche"
MARKE = ABLAGE / ".laeuft"

DATEIEN = [
    "frontend/js/settings_search.js",
    "frontend/js/skills.js",
    "frontend/js/app.js",
    "frontend/js/i18n.js",
    "frontend/settings.html",
    "frontend/css/style.css",
    "tests/test_settings_suche_ui.js",
]

UI = ["node", str(ROOT / "tests" / "test_settings_suche_ui.js")]

# (Name, Datei, alt, neu)
PROBEN = [
    # ── Markup und Platz ───────────────────────────────────────────────────
    # Ein zweites Haus VOR dem Feld: getElementById liefert das erste, damit
    # steht das Feld rechts davon – genau der Zustand, der abgewiesen wird.
    ("Suchfeld steht RECHTS vom Haus", "frontend/settings.html",
     '<div class="st-such-wrap" id="st-such-wrap">',
     '<a id="btn-home-settings" class="btn-icon" href="/portal"></a>'
     '<div class="st-such-wrap" id="st-such-wrap">'),
    ("autocomplete fehlt (Chrome-Autofill)", "frontend/settings.html",
     'id="st-such-feld" class="st-such-feld"\n                               autocomplete="off"',
     'id="st-such-feld" class="st-such-feld"\n                               data-kein-autocomplete="1"'),

    # ── Suchmechanik ───────────────────────────────────────────────────────
    ("ODER statt UND ueber die Worte", "frontend/js/settings_search.js",
     "            if (!gefunden) return null;",
     "            if (!gefunden) continue;"),
    ("Konfigurationsfelder kommen nicht in den Index", "frontend/js/settings_search.js",
     "            var schema = s.config_schema || {};",
     "            var schema = {};"),
    ("Trennzeichen werden NICHT gefaltet", "frontend/js/settings_search.js",
     "            if (istTrenner(z)) continue;",
     "            if (false) continue;"),
    ("Akzente werden NICHT gefaltet", "frontend/js/settings_search.js",
     "                : (z.normalize ? z.normalize('NFD') : z);",
     "                : z;"),
    ("ss-Faltung faellt weg", "frontend/js/settings_search.js",
     "            var teil = (z === 'ß' || z === 'ẞ')",
     "            var teil = (false)"),
    ("Index-Abbildung verworfen (Hervorhebung falsch)", "frontend/js/settings_search.js",
     "                map.push(i);",
     "                map.push(0);"),
    ("ein einzelner Buchstabe oeffnet schon", "frontend/js/settings_search.js",
     "    var MIN_ZEICHEN = 2;",
     "    var MIN_ZEICHEN = 0;"),
    ("nicht installierte Treffer stehen vorn", "frontend/js/settings_search.js",
     "                rang: _index[i].installiert ? 0 : 1,",
     "                rang: _index[i].installiert ? 1 : 0,"),
    ("keine Kuerzung der Liste", "frontend/js/settings_search.js",
     "    var MAX_TREFFER = 12;",
     "    var MAX_TREFFER = 999;"),
    ("die Kuerzung wird verschwiegen", "frontend/js/settings_search.js",
     "        if (_gesamt > _treffer.length) {",
     "        if (false) {"),
    # ⚠ AN DER WIRKSAMEN QUELLE, NICHT AM RUECKFALL. `t(k, d)` nimmt `d` nur,
    # wenn der Schluessel FEHLT – solange er existiert, ist der Rueckfall im
    # Code tot, und eine Sabotage daran misst nichts (erster Lauf: beisst nicht).
    ("die Leermeldung verschweigt den Suchraum", "frontend/js/i18n.js",
     "'stsuche.none':         'Kein Treffer für „{q}“ in den Skills.',",
     "'stsuche.none':         'Kein Treffer für „{q}“.',"),
    ("der Anfangs-Bonus ueberspringt eine Stufe", "frontend/js/settings_search.js",
     "                var wert = f.g * (p === 0 ? 1.2 : 1);",
     "                var wert = f.g * (p === 0 ? 2 : 1);"),
    ("die Fusszeile nennt den Suchraum nicht", "frontend/js/settings_search.js",
     "        els.hinweis.textContent = fuss;",
     "        els.hinweis.textContent = '';"),
    ("die Marke 'nicht installiert' faellt weg", "frontend/js/settings_search.js",
     "                if (!e.installiert) {",
     "                if (false) {"),
    ("die Marke steht wieder IM Titel (wird abgeschnitten)", "frontend/js/settings_search.js",
     "                    + '<span class=\"st-such-titel\">' + markiere(e.titel, tr.mark) + '</span>'\n"
     "                    + marken",
     "                    + '<span class=\"st-such-titel\">' + markiere(e.titel, tr.mark) + marken + '</span>'"),
    ("die Fundstelle wird nicht hervorgehoben", "frontend/js/settings_search.js",
     "        if (!mark || !mark.length) return esc(txt);",
     "        if (true) return esc(txt);"),
    ("der Pfad zum Skill fehlt in der zweiten Zeile", "frontend/js/settings_search.js",
     "        if (e.art === 'feld') return skills + ' › ' + e.skillName;",
     "        if (e.art === 'feld') return skills;"),

    # ── Ziel / Bedienung ───────────────────────────────────────────────────
    ("der Klick fuehrt nirgendwohin", "frontend/js/settings_search.js",
     "            sm.zumKonfigurationspunkt(tr.e.dirName);",
     "            void tr;"),
    ("nach dem Klick bleibt Panel und Begriff stehen", "frontend/js/settings_search.js",
     "        beenden();\n        var sm = window.skillManager;",
     "        var sm = window.skillManager;"),
    ("Escape laeuft bis zum Modal durch", "frontend/js/settings_search.js",
     "                    e.stopPropagation();\n                    e.preventDefault();\n                } else if (offen()) {",
     "                } else if (offen()) {"),
    ("Pfeiltasten bewegen nichts", "frontend/js/settings_search.js",
     "            if (e.key === 'ArrowDown') {",
     "            if (false) {"),
    ("Enter waehlt nichts aus", "frontend/js/settings_search.js",
     "                if (_aktiv >= 0) { waehle(_aktiv); e.preventDefault(); }",
     "                if (false) { waehle(_aktiv); }"),
    ("kein Treffer ist vorausgewaehlt", "frontend/js/settings_search.js",
     "        _aktiv = _treffer.length ? 0 : -1;",
     "        _aktiv = -1;"),

    # ── Die EINE Regel (skills.js) ─────────────────────────────────────────
    ("ein unsichtbarer Reiter zaehlt als Ziel", "frontend/js/skills.js",
     "        if (btn.style.display === 'none') return null;",
     "        if (false) return null;"),
    ("der Dialog hat Vorrang vor dem Reiter", "frontend/js/skills.js",
     "            const tabBtn = tabButtonFor(name);\n            if (tabBtn) return { art: 'reiter', reiter: tabBtn.textContent.trim() };",
     "            const tabBtn = tabButtonFor(name);\n            if (false) return { art: 'reiter', reiter: tabBtn.textContent.trim() };"),
    ("nicht installierte Skills gelten als konfigurierbar", "frontend/js/skills.js",
     "            if (!installiert) return { art: 'moegliche', reiter: '' };",
     "            if (false) return { art: 'moegliche', reiter: '' };"),
    ("ohne Konfigurationspunkt passiert nichts", "frontend/js/skills.js",
     "            await this.zeigeInListe(name, ziel.art === 'liste');",
     "            void name;"),
    ("die Zeile ist nicht adressierbar (installiert)", "frontend/js/skills.js",
     "            item.setAttribute('data-skill', dirName);\n            item.innerHTML = `",
     "            item.innerHTML = `"),
    ("die Zeile ist nicht adressierbar (moeglich)", "frontend/js/skills.js",
     "            item.setAttribute('data-skill', dirName);   // siehe _mkInstalledItem",
     "            // Adresse entfernt"),
    ("der Eintrag wird nicht hervorgehoben", "frontend/js/skills.js",
     "            el.classList.add('sk-item-treffer');",
     "            void el;"),
    ("der Filter der moeglichen Skills bleibt stehen", "frontend/js/skills.js",
     "                this.categoryFilter = 'all';\n                this.searchVal = '';",
     "                void 0;"),
    ("der Abschnitt wird nicht aufgeklappt", "frontend/js/skills.js",
     "            this._abschnittOeffnen(installiert);",
     "            void installiert;"),
    ("ein offener Abschnitt wird blind zugeklappt", "frontend/js/skills.js",
     "            if (!zu) return;",
     "            if (false) return;"),

    # ── Verdrahtung und Drift ──────────────────────────────────────────────
    ("app.js stellt window.skillManager nicht bereit", "frontend/js/app.js",
     "            window.skillManager = skillManager;",
     "            void skillManager;"),
    ("app.js stellt window.jarvisSkillsOnce nicht bereit", "frontend/js/app.js",
     "        window.jarvisSkillsOnce = _skillsOnce;",
     "        void _skillsOnce;"),
    ("app.js ruft SettingsSearch.init() nicht", "frontend/js/app.js",
     "            if (window.SettingsSearch) window.SettingsSearch.init();",
     "            void 0;"),
    ("die Suche baut die Reiterzuordnung nach", "frontend/js/settings_search.js",
     "    var els = {};",
     "    var SKILL_TABS = { jira: 'jira' };\n    var els = {};"),
    ("die Suche holt /api/skills selbst", "frontend/js/settings_search.js",
     "        var holen = (typeof window.jarvisSkillsOnce === 'function')",
     "        var pfad = '/api/skills';\n        void pfad;\n        var holen = (typeof window.jarvisSkillsOnce === 'function')"),

    # ── i18n und CSS ───────────────────────────────────────────────────────
    ("ein stsuche-Schluessel fehlt auf Englisch", "frontend/js/i18n.js",
     "        'stsuche.scope':        'Searches tabs, sections, fields and skills.',",
     "        'stsuche.scope_en':     'Searches tabs, sections, fields and skills.',"),
    ("Panel ohne deckende Flaeche", "frontend/css/style.css",
     "    background: var(--bg-secondary);\n    border: 1px solid var(--border);\n    border-radius: 12px;\n    box-shadow: 0 12px 32px rgba(var(--shadow-rgb), 0.28);",
     "    background: rgba(var(--fg-rgb), 0.05);\n    border: 1px solid var(--border);\n    border-radius: 12px;\n    box-shadow: 0 12px 32px rgba(var(--shadow-rgb), 0.28);"),
    ("Panel waechst nach rechts (wird abgeschnitten)", "frontend/css/style.css",
     "    top: calc(100% + 8px);\n    right: 2rem;",
     "    top: calc(100% + 8px);\n    left: 0;"),
    # ⚠ DER FALL, DEN NUR DER SCHIRM GEZEIGT HAT: mit dem FELD als Bezug misst
    # `max-width` die Feldbreite - bei 520 px ragte das Panel links aus dem
    # Modal und die Titel waren abgeschnitten.
    ("das Panel haengt wieder am Suchfeld statt am Kopf", "frontend/css/style.css",
     "#settings-modal .modal-header { position: relative; }",
     "#settings-modal .modal-header { position: static; }"),
    ("die Panelbreite haengt wieder am Sichtfenster", "frontend/css/style.css",
     "    max-width: calc(100% - 4rem);     /* beide Innenabstaende */",
     "    max-width: min(420px, 62vw);"),
    ("ein Klick INS Panel schliesst es (Auswahl kommt nie zustande)",
     "frontend/js/settings_search.js",
     "            if (els.wrap.contains(e.target) || els.panel.contains(e.target)) return;",
     "            if (els.wrap.contains(e.target)) return;"),
    ("Panelhoehe fest statt am Sichtfenster", "frontend/css/style.css",
     "    max-height: min(46vh, 340px);",
     "    max-height: 340px;"),
    ("Titelzeile darf nicht schrumpfen", "frontend/css/style.css",
     "    min-width: 0;\n    overflow: hidden;\n    text-overflow: ellipsis;\n    white-space: nowrap;\n}\n\n.st-such-pfad {",
     "    overflow: hidden;\n    text-overflow: ellipsis;\n    white-space: nowrap;\n}\n\n.st-such-pfad {"),
    ("die Symbolgruppe schrumpft nicht mehr", "frontend/css/style.css",
     "    flex: 0 1 auto;\n    min-width: 0;\n}\n\n/* Die Symbole der Gruppe schrumpfen NICHT.",
     "    flex: 0 0 auto;\n}\n\n/* Die Symbole der Gruppe schrumpfen NICHT."),
    ("der angesprungene Eintrag faellt optisch nicht auf", "frontend/css/style.css",
     ".sk-item-treffer {\n    box-shadow: 0 0 0 2px var(--accent);",
     ".sk-item-treffer {\n    outline-offset: 0;"),

    # ── Die OBERFLAECHE als Suchraum (gemeldet 2026-09-20) ─────────────────
    # ⚠ DIE ERSTE IST DER GEMELDETE ZUSTAND SELBST: ohne die Oberflaeche im
    # Index findet „ldap" nichts.
    ("KOMPLETT: die Oberflaeche wird gar nicht indiziert", "frontend/js/settings_search.js",
     "            _index = baueOberflaeche(vonSkill).concat(skillTeil);",
     "            _index = skillTeil;"),
    ("Reiter kommen nicht in den Index", "frontend/js/settings_search.js",
     "            if (ausSkill[tab]) continue;\n            raus.push({\n                art: 'reiter',",
     "            if (ausSkill[tab]) continue;\n            if (true) continue;\n            raus.push({\n                art: 'reiter',"),
    ("Abschnitte kommen nicht in den Index", "frontend/js/settings_search.js",
     "        var hdrs = d.querySelectorAll('.kb-collapse-header');",
     "        var hdrs = [];"),
    ("Feldbeschriftungen kommen nicht in den Index", "frontend/js/settings_search.js",
     "        var labs = d.querySelectorAll('label');",
     "        var labs = [];"),
    ("ein versteckter Reiter wird mit indiziert", "frontend/js/settings_search.js",
     "            if (!tab || b.style.display === 'none') continue;",
     "            if (!tab) continue;"),
    ("ein Skill-Reiter erscheint zusaetzlich als Reiter", "frontend/js/settings_search.js",
     "            if (ausSkill[tab]) continue;",
     "            if (false) continue;"),
    ("Beschriftung und Erlaeuterung nicht getrennt", "frontend/js/settings_search.js",
     "            var txt = saeubere(teile[0]);",
     "            var txt = saeubere(teile.join(' '));"),

    # ── Der Sprung ─────────────────────────────────────────────────────────
    ("der Treffer klickt den Reiter nicht", "frontend/js/settings_search.js",
     "        if (tb && tb.style.display !== 'none') tb.click();\n\n        var el = e.el;",
     "        if (false) tb.click();\n\n        var el = e.el;"),
    ("der Abschnitt wird nicht aufgeklappt", "frontend/js/settings_search.js",
     "            if (eig && eig.style.display === 'none') el.click();",
     "            if (false) el.click();"),
    ("blindes click(): ein offener Abschnitt wird ZUgeklappt", "frontend/js/settings_search.js",
     "            if (eig && eig.style.display === 'none') el.click();",
     "            if (eig) el.click();"),
    ("keine Hervorhebung des angesprungenen Punktes", "frontend/js/settings_search.js",
     "        el.classList.add('st-such-treffer');",
     "        if (false) el.classList.add('st-such-treffer');"),
    ("CSS der Hervorhebung fehlt", "frontend/css/style.css",
     ".st-such-treffer {\n    box-shadow: 0 0 0 2px var(--accent);",
     ".st-such-treffer-aus {\n    box-shadow: 0 0 0 2px var(--accent);"),

    # ── Fail-open ──────────────────────────────────────────────────────────
    ("fail-open aufgehoben: ohne Skills gar keine Suche", "frontend/js/settings_search.js",
     "            _index = baueOberflaeche({});\n            _fehlteSkills = true;",
     "            _index = null;\n            _fehlteSkills = true;"),
    ("der fehlende Teil wird verschwiegen", "frontend/js/settings_search.js",
     "        if (_fehlteSkills) {",
     "        if (false) {"),

    # ── Anzeige ────────────────────────────────────────────────────────────
    ("der Pfad nennt den Abschnitt nicht", "frontend/js/settings_search.js",
     "            return e.abschnitt ? e.reiterName + ' › ' + e.abschnitt : e.reiterName;",
     "            return e.reiterName;"),
    ("Leermeldung nennt den Suchraum nicht", "frontend/js/i18n.js",
     "        'stsuche.none':         'Kein Treffer für „{q}“ in den Einstellungen.',",
     "        'stsuche.none':         'Kein Treffer für „{q}“.',"),
]


def sichern():
    ABLAGE.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, ABLAGE / rel.replace("/", "__"))
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
                       timeout=300,
                       env={**os.environ, "JSDOM_PATH": "node_modules/jsdom"})
    aus = r.stdout + r.stderr
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", aus)
    return r.returncode, bool(m), int(m.group(2)) if m else -1


def main():
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

    print("Basislauf…")
    rc, bil, f = lauf(UI)
    if rc != 0 or not bil:
        print("ABBRUCH: Basislauf nicht gruen (exit=%s, bilanz=%s, fail=%s)" % (rc, bil, f))
        sys.exit(2)
    print("  Basis: gruen")

    # Optionaler Filter: `--nur <teil>` faehrt nur die passenden Proben. Fuer
    # das Nachziehen einer einzelnen Probe – der volle Lauf dauert Minuten.
    filt = ""
    if "--nur" in sys.argv:
        filt = sys.argv[sys.argv.index("--nur") + 1].lower()
    proben = [p for p in PROBEN if filt in p[0].lower()] if filt else PROBEN
    if not proben:
        print("ABBRUCH: kein Treffer fuer --nur %r" % filt)
        sys.exit(2)

    beissen = nicht = 0
    for name, rel, alt, neu in proben:
        datei = ROOT / rel
        s = datei.read_text(encoding="utf-8")
        if s.count(alt) != 1:
            # ⚠ EINE ERSETZUNG OHNE TREFFERKONTROLLE IST KEIN MESSWERT.
            print("  \033[33m?\033[0m %-58s SABOTAGE TRIFFT NICHT (%dx)" % (name, s.count(alt)))
            nicht += 1
            continue
        datei.write_text(s.replace(alt, neu, 1), encoding="utf-8")
        rc, bil, f = lauf(UI)
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
    print("beissen: %d von %d" % (beissen, len(proben)))
    sys.exit(1 if nicht else 0)


if __name__ == "__main__":
    main()
