#!/usr/bin/env python3
"""Gegenproben zu ``tests/test_confluence_accounts.py`` – beisst der Waechter?

**Eine Gegenprobe, die nicht beisst, ist ein Testmangel – kein Beweis.** Jede
Probe dreht GENAU EINEN Teil des Fixes zurueck und zaehlt die FAIL. Beisst eine
nicht, ist entweder der Waechter zahnlos oder – die erste Frage, nicht die
letzte – die Zusage existiert gar nicht.

REGELN DES HARNESS (jede aus einem bezahlten Vorfall):
  * **Gruener Basislauf ist Pflicht.** Ohne gruene Basis ist keine Gegenprobe
    deutbar (jede Probe zaehlte sonst eine FAIL zu viel).
  * **Sicherung auf PLATTE, vor jeder Probe neu.** Eine Sicherung, die nicht
    erneuert wird, stellt beim zweiten Lauf einen veralteten Stand her und macht
    fertige Arbeit zunichte.
  * **NIE `git checkout` zum Zuruecknehmen** – das verwirft auch die noch nicht
    committete Arbeit am Rest des Baums. Am 2026-09-29 genau so passiert.
  * **Rueckstand beim naechsten Start selbst zuruecknehmen** (Laufmarke), und
    nach dem Wiederherstellen **Byte-Gleichheit per md5 pruefen**.
  * **Kein Bytecode** (`PYTHONDONTWRITEBYTECODE=1`): liegen Sabotage und
    Wiederherstellung in derselben Sekunde und sind gleich gross, laedt ein
    spaeterer Lauf die `.pyc` der SABOTAGE – bei byte-gleicher Quelle.
  * **Gemessen wird der EXIT-CODE und die Bilanzzeile**, nie das Zaehlen von
    FAIL-Zeilen: ein Abbruch ohne Bilanz ist von "nicht gelaufen" nicht zu
    unterscheiden.
  * **Trefferkontrolle je Ersetzung** (`assert`): eine Probe, die ihren Anker
    nicht trifft, sieht wie ein zahnloser Waechter aus und ist keiner.

Lauf:  python3 tests/gegen_confluence_accounts.py
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# BEIDE Waechter, und die FAIL werden SUMMIERT: der eine misst das Modul, der
# andere die ausgefuehrte Seite. Liefe nur einer, blieben alle Proben am
# Frontend stumm – und eine stumme Probe sieht wie ein zahnloser Waechter aus.
WAECHTER = [
    [sys.executable, str(ROOT / "tests" / "test_confluence_accounts.py")],
    ["node", str(ROOT / "tests" / "test_confluence_addon_ui.js")],
]
SICHER = Path.home() / ".gegen-confluence"          # HOME (0700), NICHT /tmp
MARKE = SICHER / ".laeuft"

# Jede Datei, die eine Probe anfasst – als REGEL geprueft, nicht gepflegt.
DATEIEN = [
    "backend/confluence_accounts.py",
    "backend/main.py",
    "backend/agent.py",
    "backend/sandbox.py",
    "backend/secret_reveal.py",
    "skills/confluence/main.py",
    "frontend/confluence_addon.html",
    "frontend/js/confluence_addon.js",
    "frontend/js/i18n.js",
    "frontend/portal.html",
]

UMG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
# jsdom liegt je Maschine anders; ohne Pfad endet der UI-Waechter mit Exit 2 und
# die Gegenproben waeren unbewertbar (nicht "stumm").
if "JSDOM_PATH" not in UMG:
    for _k in ("/tmp/node_modules/jsdom",
               str(Path.home() / "sleek/node_modules/jsdom")):
        if Path(_k).exists():
            UMG["JSDOM_PATH"] = _k
            break


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern() -> None:
    """Sicherung bei JEDEM Lauf erneuern – die Basis ist per Definition der
    richtige Stand (sie wird unmittelbar danach als gruen geprueft)."""
    SICHER.mkdir(mode=0o700, parents=True, exist_ok=True)
    for rel in DATEIEN:
        ziel = SICHER / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, ziel)
    MARKE.write_text("1", encoding="utf-8")


def zurueck(pruefen: bool = True) -> None:
    for rel in DATEIEN:
        q = SICHER / rel.replace("/", "__")
        if not q.exists():
            continue
        shutil.copy2(q, ROOT / rel)
        if pruefen and md5(q) != md5(ROOT / rel):
            print("ABBRUCH: %s nicht byte-gleich wiederhergestellt" % rel)
            sys.exit(2)


def _einer(befehl: list) -> tuple[int, str]:
    """(FAIL-Zahl, Bilanzzeile) EINES Waechters. -1 heisst: keine Bilanz."""
    r = subprocess.run(befehl, capture_output=True, text=True, cwd=str(ROOT),
                       env=UMG, timeout=180)
    aus = r.stdout + r.stderr
    for z in aus.splitlines():
        # Die Bilanz steht nicht immer am Zeilenanfang (ANSI-Escapes, Praefixe) –
        # danach zu suchen hat im Projekt schon vier gruene Waechter wie "keine
        # Bilanz" aussehen lassen.
        if "ERGEBNIS:" in z:
            try:
                return int(z.split("ERGEBNIS:")[1].split(",")[1].split()[0]), z.strip()
            except (IndexError, ValueError):
                break
    # Kein Ergebnis: Abbruch. Der GRUND gehoert dazu, sonst ist die Probe
    # unbewertbar – ein Abbruch ist KEIN Beweis, dass die Zusage gebrochen ist.
    grund = next((z for z in aus.splitlines()
                  if "ABBRUCH" in z or "Error" in z), "")
    return -1, "KEINE BILANZ (%s)" % grund[:110]


def lauf() -> tuple[int, int, str]:
    """(Summe der FAIL, Exit-Ersatz, Bilanzzeilen) ueber ALLE Waechter."""
    summe, zeilen, kaputt = 0, [], False
    for b in WAECHTER:
        f, z = _einer(b)
        zeilen.append(z)
        if f < 0:
            kaputt = True
        else:
            summe += f
    if kaputt:
        return -1, 1, " | ".join(zeilen)
    return summe, (1 if summe else 0), " | ".join(zeilen)


def ersetze(rel: str, alt: str, neu: str, anzahl: int = 1) -> None:
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    assert s.count(alt) == anzahl, \
        "Anker trifft %dx statt %dx in %s – Probe waere wertlos" % (
            s.count(alt), anzahl, rel)
    p.write_text(s.replace(alt, neu), encoding="utf-8")


# ── Die Proben: (Name, Funktion) ────────────────────────────────────────────

def p_skill_sammel():
    """Der Skill baut wieder selbst einen Sammel-Client – der Kern des Umbaus."""
    ersetze("skills/confluence/main.py",
            "    from backend import confluence_accounts  # noqa: PLC0415 – Zirkelimport\n"
            "    return confluence_accounts.client_fuer_lauf()",
            "    return ConfluenceClient()")


def p_leer_loescht():
    """Ein leeres Token-Feld loescht wieder (der Postfach-Fehler)."""
    ersetze("backend/confluence_accounts.py",
            "            wert = str(felder.get(f) or \"\")\n"
            "            if wert.strip():",
            "            wert = str(felder.get(f) or \"\")\n"
            "            if True:")


def p_whitelist_weg():
    """`base_url` ist wieder selbst setzbar (SSRF-Flaeche)."""
    ersetze("backend/confluence_accounts.py",
            'AENDERBAR = ("aktiv",) + GEHEIMFELDER',
            'AENDERBAR = ("aktiv", "base_url", "user") + GEHEIMFELDER')


def p_token_raus():
    """`zugang_info` gibt den Token heraus."""
    ersetze("backend/confluence_accounts.py",
            '        "token_gesetzt": bool((k.get("api_token_enc") or "").strip()),',
            '        "token_gesetzt": bool((k.get("api_token_enc") or "").strip()),\n'
            '        "api_token": klartext(user, "api_token")[0],')


def p_inaktiv_still():
    """Der Rueckfall auf den Sammelzugang laeuft STILL (ohne Hinweis)."""
    ersetze("backend/confluence_accounts.py",
            '                hinweis = ("Dein persoenlicher Confluence-Zugang steht auf "\n'
            '                           "inaktiv – es gilt der gemeinsame Zugang.")',
            '                hinweis = ""')


def p_keine_normierung():
    """Der Benutzerschluessel wird nicht mehr normiert."""
    ersetze("backend/confluence_accounts.py",
            '    return s.split("@")[0].split("\\\\")[-1].strip().lower()',
            "    return s")


def p_kanal_erlaubt():
    """Kanal-Kennungen (wa:/tg:/api:) bekommen einen Zugang."""
    ersetze("backend/confluence_accounts.py",
            '    if ":" in un:\n'
            '        # wa:/tg:/api: – Kanal-Kennungen sind keine Personen mit\n'
            '        # Confluence-Benutzer.\n'
            '        raise ConfluenceKontoFehler(\n'
            '            "Fuer diese Kennung kann kein Confluence-Zugang hinterlegt werden.")',
            "    if False:\n        pass")


def p_test_nimmt_geltenden():
    """Der Verbindungstest prueft den GELTENDEN statt den persoenlichen Zugang.

    Damit meldet er bei kaputtem eigenem Token 'ok', weil der Sammelzugang
    antwortet – und der Benutzer hat keinen Weg zu seinem Fehler.
    """
    ersetze("backend/confluence_accounts.py",
            '    c = ConfluenceClient({"base_url": basis,\n'
            '                          "api_token": entschluesseln(k.get("api_token_enc", ""))})',
            "    c = client_fuer_lauf(user)")


def p_test_faellt_immer_zurueck():
    """Der 404-Rueckfall gilt fuer JEDEN Fehler – ein 401 wird gruengefaerbt."""
    ersetze("backend/confluence_accounts.py",
            '        if getattr(e, "status", 0) != 404:',
            "        if False:")


def p_test_ohne_rueckfall():
    """Kein 404-Rueckfall – ein funktionierender Token gilt als kaputt."""
    ersetze("backend/confluence_accounts.py",
            '        if getattr(e, "status", 0) != 404:',
            "        if True:")


def p_contextvar_weg():
    """agent.py setzt den ContextVar nicht mehr."""
    ersetze("backend/agent.py",
            "                    from backend.confluence_accounts import current_confluence_user as _ccv\n"
            "                    _c_token = _ccv.set(_uname or \"\")",
            "                    _ccv = None")


def p_contextvar_kein_reset():
    """Der ContextVar wird nicht zurueckgenommen (haengt am naechsten Lauf)."""
    ersetze("backend/agent.py",
            "                            _ccv.reset(_c_token)",
            "                            pass")


def p_sperrliste_deny():
    """Die Dateien fallen aus `_APP_DENY_REL`."""
    ersetze("backend/sandbox.py",
            '    "data/confluence_accounts.json", "data/.confluencekey",\n',
            "")


def p_sperrliste_streng():
    """Die Schluesseldatei fallt aus `PRIVATE_FILES_STRENG` (0600 → 0640)."""
    ersetze("backend/sandbox.py",
            '                        "data/.confluencekey",\n', "")


def p_sperrliste_shell():
    """Das Shell-Muster kennt die Dateien nicht mehr."""
    ersetze("backend/sandbox.py",
            "    r'confluence_accounts\\.json\\b|\\.confluencekey\\b|'\n", "")


def p_freigabe_zweimal():
    """Die Freigabe wird an der zweiten Stelle nachgebaut statt gerufen."""
    ersetze("backend/main.py",
            '            "confluence": _user_may_use_confluence_account,',
            '            "confluence": lambda u: bool(u) and _skill_active("confluence"),')


def p_secret_reveal_weg():
    """`secret_reveal` kennt den Bereich nicht – das Auge liefert nichts."""
    ersetze("backend/secret_reveal.py",
            '    if b == "confluence":\n'
            "        from backend import confluence_accounts as m\n"
            "        return m.klartext\n",
            "")


def p_endpunkt_filtert_vor():
    """Der POST filtert vor – ein unbekanntes Feld verschwindet still."""
    ersetze("backend/main.py",
            "        info = confluence_accounts.speichern(user, body)",
            "        info = confluence_accounts.speichern(user, {\n"
            '            k: v for k, v in body.items() if k in ("aktiv", "api_token")})')


def p_endpunkt_admin():
    """Die Endpunkte haengen an `require_local_auth` – der Token wird ein
    Admin-Feature, und genau die Benutzer, um die es geht, bleiben aussen."""
    ersetze("backend/main.py",
            "Depends(require_confluence_account_access)",
            "Depends(require_local_auth)", anzahl=4)


def p_route_weg():
    """Die Seite wird nicht mehr ausgeliefert."""
    ersetze("backend/main.py", '@app.get("/confluence-addon")',
            '@app.get("/confluence-addon-alt")')


def p_permissions_weg():
    """`/api/me` meldet die Freigabe nicht – die Kachel bleibt unsichtbar."""
    ersetze("backend/main.py",
            '            "confluence": _skill_active("confluence"),\n', "")


def p_kachel_weg():
    """Die Portal-Kachel fehlt."""
    # Nur EINMAL: `getElementById('pt-card-confluence')` im Skript traegt
    # Anfuehrungszeichen und ist damit ein anderer Text.
    ersetze("frontend/portal.html", 'id="pt-card-confluence"',
            'id="pt-card-confluence-alt"', anzahl=1)


def p_kachel_nicht_eingeblendet():
    """Die Kachel wird nie eingeblendet."""
    ersetze("frontend/portal.html", "d.permissions.confluence", "false")


def p_auge_weg():
    """Das Kennwortfeld verliert das Auge (Anweisung des Betreibers)."""
    ersetze("frontend/confluence_addon.html", ' data-pw-quelle="confluence"', "")


def p_plugin_container_mit():
    """Der Plugin-Container der Jira-Seite ist mitkopiert (nicht bestellt)."""
    ersetze("frontend/confluence_addon.html",
            '    <details class="ja-sect" id="ca-sect-account" open>',
            '    <details class="ja-sect" id="ja-sect-plugin">\n'
            '        <summary>Browser-Plugin</summary>\n'
            "    </details>\n"
            '    <details class="ja-sect" id="ca-sect-account" open>')


def p_container_zu():
    """Der einzige Container startet zugeklappt (sieht wie ein Ladefehler aus)."""
    ersetze("frontend/confluence_addon.html",
            'id="ca-sect-account" open>', 'id="ca-sect-account">')


def p_i18n_nur_de():
    """Die englischen Schluessel fehlen."""
    ersetze("frontend/js/i18n.js",
            "        'caddon.acc_h':           'My Confluence access',\n", "")


def p_portal_i18n_nur_de():
    """Der Kachel-Titel fehlt in Englisch."""
    ersetze("frontend/js/i18n.js",
            "        'portal.card_confluence':       'Confluence',\n"
            "        'portal.card_confluence_desc':  'Your own Confluence access: "
            "read and write pages with your permissions.',\n", "")


def p_fail_open():
    """Die Seite laesst Unberechtigte herein (fail-open statt fail-closed)."""
    ersetze("frontend/js/confluence_addon.js",
            "        var darf = !!(me && me.permissions && me.permissions.confluence);",
            "        var darf = true;")


def p_aktivitaet_unterstrich():
    """Die Aktivitaets-Kennung traegt einen Unterstrich – trifft nie."""
    ersetze("backend/main.py", '"confluence-addon": "Confluence",',
            '"confluence_addon": "Confluence",')


def p_eigenes_css():
    """Eine zweite Fassung der Kartenoptik als eigene CSS-Datei."""
    ersetze("frontend/confluence_addon.html", "css/jira_addon.css?v=13",
            "css/confluence_addon.css?v=1")
    (ROOT / "frontend" / "css" / "confluence_addon.css").write_text(
        "/* Wegwerf-Probe */\n", encoding="utf-8")


def p_pille_nur_farbe():
    """Die Pille traegt nur noch die Farbe, keinen Text – Farbe allein ist keine
    Information (Projektregel)."""
    ersetze("frontend/js/confluence_addon.js",
            "                pill.textContent = T('caddon.acc_pill_off', 'inaktiv');",
            "                pill.textContent = '';")


def p_leeres_feld_mitsenden():
    """Das leere Token-Feld wird mitgesendet – auf dem Server heisst das
    "unveraendert", aber die Regel gilt dann zweimal und kann auseinanderlaufen.
    """
    ersetze("frontend/js/confluence_addon.js",
            "            if (tok) rumpf.api_token = tok;",
            "            rumpf.api_token = tok;")


def p_feld_nicht_geleert():
    """Das Token-Feld bleibt nach dem Speichern stehen – Klartext im Formular,
    und das naechste Speichern meint dann nicht mehr "unveraendert"."""
    ersetze("frontend/js/confluence_addon.js",
            "            if ($('ca-acc-token')) $('ca-acc-token').value = '';\n", "")


def p_rueckfrage_ignoriert():
    """Die Rueckfrage vor dem Entfernen wird ignoriert."""
    ersetze("frontend/js/confluence_addon.js",
            "            if (!window.confirm(T('caddon.acc_del_ask',\n"
            "                'Eigenen Confluence-Token entfernen? Danach gilt wieder "
            "der gemeinsame Zugang.'))) return;\n", "")


def p_sprachwechsel_weg():
    """Der Sprachwechsel zeichnet den Zustand nicht neu – Pille und Kasten
    bleiben deutsch."""
    ersetze("frontend/js/confluence_addon.js",
            "        window.addEventListener('jarvis-lang-changed', function () {\n"
            "            accZeichnen();\n"
            "        });",
            "        /* nichts */")


def p_kasten_immer_zu():
    """Der Hinweiskasten wird nie sichtbar – wer der Token ist, erfaehrt niemand."""
    ersetze("frontend/js/confluence_addon.js",
            "            note.classList.toggle('is-on', zeilen.length > 0);",
            "            note.classList.remove('is-on');")


def p_serverfeld_schreibbar():
    """Das Serverfeld ist beschreibbar – jemand tippt hinein und wundert sich."""
    ersetze("frontend/confluence_addon.html",
            'id="ca-acc-server" type="text" readonly disabled',
            'id="ca-acc-server" type="text"')


PROBEN = [
    ("Skill baut wieder den Sammel-Client", p_skill_sammel),
    ("leeres Token-Feld loescht", p_leer_loescht),
    ("base_url/user selbst setzbar", p_whitelist_weg),
    ("zugang_info gibt den Token heraus", p_token_raus),
    ("Rueckfall laeuft still (ohne Hinweis)", p_inaktiv_still),
    ("Benutzerschluessel nicht normiert", p_keine_normierung),
    ("Kanal-Kennungen erlaubt", p_kanal_erlaubt),
    ("Test nimmt den GELTENDEN Zugang", p_test_nimmt_geltenden),
    ("404-Rueckfall gilt fuer JEDEN Fehler", p_test_faellt_immer_zurueck),
    ("kein 404-Rueckfall", p_test_ohne_rueckfall),
    ("ContextVar nicht gesetzt", p_contextvar_weg),
    ("ContextVar nicht zurueckgenommen", p_contextvar_kein_reset),
    ("_APP_DENY_REL ohne die Dateien", p_sperrliste_deny),
    ("PRIVATE_FILES_STRENG ohne den Schluessel", p_sperrliste_streng),
    ("Shell-Muster ohne die Dateien", p_sperrliste_shell),
    ("Freigabe an zweiter Stelle nachgebaut", p_freigabe_zweimal),
    ("secret_reveal ohne den Bereich", p_secret_reveal_weg),
    ("Endpunkt filtert den Rumpf vor", p_endpunkt_filtert_vor),
    ("Endpunkte auf require_local_auth", p_endpunkt_admin),
    ("Route entfernt", p_route_weg),
    ("permissions.confluence entfernt", p_permissions_weg),
    ("Portal-Kachel entfernt", p_kachel_weg),
    ("Kachel wird nie eingeblendet", p_kachel_nicht_eingeblendet),
    ("Auge am Kennwortfeld entfernt", p_auge_weg),
    ("Plugin-Container mitkopiert", p_plugin_container_mit),
    ("einziger Container startet zu", p_container_zu),
    ("caddon.* nur deutsch", p_i18n_nur_de),
    ("Kachel-Titel nur deutsch", p_portal_i18n_nur_de),
    ("Seite ist fail-open", p_fail_open),
    ("Aktivitaets-Kennung mit Unterstrich", p_aktivitaet_unterstrich),
    ("eigene CSS-Datei (zweite Fassung)", p_eigenes_css),
    # ── die ausgefuehrte Seite ──
    ("Pille traegt nur Farbe, keinen Text", p_pille_nur_farbe),
    ("leeres Token-Feld wird mitgesendet", p_leeres_feld_mitsenden),
    ("Token-Feld bleibt nach dem Speichern stehen", p_feld_nicht_geleert),
    ("Rueckfrage vor dem Entfernen ignoriert", p_rueckfrage_ignoriert),
    ("Sprachwechsel zeichnet nicht neu", p_sprachwechsel_weg),
    ("Hinweiskasten wird nie sichtbar", p_kasten_immer_zu),
    ("Serverfeld beschreibbar", p_serverfeld_schreibbar),
]


def aufraeumen_extra() -> None:
    """Dateien, die eine Probe ANLEGT, gehoeren ebenfalls weg – ein `zurueck()`
    ueber die bekannten Dateien sieht sie nicht (Register)."""
    p = ROOT / "frontend" / "css" / "confluence_addon.css"
    if p.exists():
        p.unlink()


def main() -> int:
    # Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen.
    if MARKE.exists():
        print("Rueckstand eines frueheren Laufs gefunden – nehme ihn zurueck.")
        zurueck(pruefen=False)
        aufraeumen_extra()
        MARKE.unlink()

    # REGEL statt gepflegter Liste: jede Datei, die eine Probe anfasst, muss in
    # DATEIEN stehen. Geprueft ueber die Anker der Proben selbst.
    fehlt = [r for r in DATEIEN if not (ROOT / r).exists()]
    if fehlt:
        print("ABBRUCH: Datei(en) fehlen: %s" % fehlt)
        return 2

    aufraeumen_extra()
    basis_fail, basis_exit, basis_zeile = lauf()
    print("Basislauf: %s (Exit %d)" % (basis_zeile, basis_exit))
    if basis_fail != 0 or basis_exit != 0:
        print("ABBRUCH: ohne gruenen Basislauf ist keine Gegenprobe deutbar.")
        return 2

    sichern()
    stumm = []
    try:
        for name, fn in PROBEN:
            try:
                fn()
            except AssertionError as e:
                print("  ⚠ PROBE TRIFFT NICHT: %-44s %s" % (name, e))
                stumm.append(name + " (Anker)")
                zurueck()
                aufraeumen_extra()
                continue
            f, code, zeile = lauf()
            zurueck()
            aufraeumen_extra()
            if f > 0:
                print("  beisst  %-44s %d FAIL" % (name, f))
            elif f < 0:
                # Ein Abbruch ist KEIN Beweis: er kann auch heissen, dass die
                # Sabotage den Lauf zerlegt hat, statt eine Zusage zu brechen.
                print("  ABBRUCH %-44s %s" % (name, zeile))
                stumm.append(name + " (Abbruch)")
            else:
                print("  STUMM   %-44s 0 FAIL" % name)
                stumm.append(name)
    finally:
        zurueck()
        aufraeumen_extra()
        if MARKE.exists():
            MARKE.unlink()

    print("\n%d von %d Proben beissen." % (len(PROBEN) - len(stumm), len(PROBEN)))
    if stumm:
        print("STUMM: %s" % ", ".join(stumm))
        print("Eine stumme Gegenprobe ist ein Testmangel – oder die Zusage "
              "existiert nicht. Beides gehoert geklaert, nicht weggelassen.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
