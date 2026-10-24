#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_h9.py (+ test_bsi_h9_ui.js): beisst der Waechter?

Jede Probe dreht EINEN Teil des H9-Fixes zurueck (Python-Ersetzung ganzer
Zeilen), laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5. Laeuft ohne
Bytecode (PYTHONDONTWRITEBYTECODE=1) und mit dem venv-Python, weil der
Waechter einen echten Agentenlauf macht.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.

    venv/bin/python tests/gegen_bsi_h9.py
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_bsi_h9.py"
UI = ROOT / "tests" / "test_bsi_h9_ui.js"
MAILREGELN = ROOT / "tests" / "test_email_rules.py"
WI = "backend/wirkung.py"
AG = "backend/agent.py"
MA = "backend/main.py"
CJ = "frontend/js/chat.js"
BJ = "frontend/js/bestaetigung.js"
AB = "backend/adressbuch.py"
EM = "skills/email/main.py"
PY = str(ROOT / "venv" / "bin" / "python") if (ROOT / "venv" / "bin" / "python").exists() \
    else sys.executable

PROBEN = [
    # (name, datei, alt, neu) – Proben an Frontend-Dateien pruefen den UI-Waechter
    # Anker bewusst KURZ: die alte Fassung trug die ganze Aufrufzeile mit und
    # traf nach einer Aenderung an ihr nicht mehr (Kommentar und vierter
    # Parameter kamen dazu). Ein Anker, der den halben Rumpf abschreibt, ist
    # eine Zeitbombe – er faellt als "???" aus, nicht als Befund.
    ("Tor im Dispatch entfernt", AG,
     "                if _klasse:\n", "                if False:\n"),
    ("Sandbox-Angabe immer wahr", AG,
     "                    sandbox=bool(exec_args.get('_sandbox_user')),\n",
     "                    sandbox=True,\n"),
    ("Shell ohne Sandbox fragt nicht", WI,
     "        return None if sandbox else SHELL\n", "        return None\n"),
    ("email_senden nicht eingestuft", WI,
     "    \"email_senden\": AUSSEN,\n", ""),
    ("Papierkorb-Verschieben nicht erkannt", WI,
     "    return LOESCHEN if _PAPIERKORB.search(ziel) else None\n", "    return None\n"),
    ("MCP ohne Angabe gilt als harmlos", WI,
     "    elif fremd:\n        return AUSSEN\n", "    elif fremd:\n        return None\n"),
    ("scheiternde Einstufung fail-open", WI,
     "            # unbekannt heisst hier: fragen.\n            return AUSSEN\n",
     "            # unbekannt heisst hier: fragen.\n            return None\n"),
    ("Kanal wird nie gelesen", WI,
     "    kanal = kanal_cv.get()\n", "    kanal = None\n"),
    ("Client ohne Dialog darf trotzdem", WI,
     "    if not kanal.kann_bestaetigen or kanal.ws is None:\n", "    if kanal.ws is None:\n"),
    ("Frist gilt als Freigabe", WI,
     "            return hinweis_frist(name)\n", "            return None\n"),
    ("fremder Benutzer darf freigeben", WI,
     "        if username != soll:\n", "        if False:\n"),
    ("jeder wahre Wert gibt frei", WI,
     "        (erlaubt is True, aenderungen if isinstance(aenderungen, dict) else {}))\n",
     "        (bool(erlaubt), aenderungen if isinstance(aenderungen, dict) else {}))\n"),
    # ── Korrektur eines Empfaengers in der Karte ────────────────────────────
    ("Korrektur geht in die ANZEIGE statt in die Ausfuehrung", AG,
     "                    _nein = await _wirkung.freigabe(name, args, _klasse, exec_args)\n",
     "                    _nein = await _wirkung.freigabe(name, args, _klasse, args)\n"),
    ("Weissliste der aenderbaren Felder aufgehoben", WI,
     "        if f not in erlaubt:\n", "        if False:\n"),
    ("Korrektur wird auch bei ABLEHNEN uebernommen", WI,
     "        geaendert = uebernehmen(name, exec_args, korrekturen) if erlaubt else []\n",
     "        geaendert = uebernehmen(name, exec_args, korrekturen)\n"),
    ("Zeilenumbruch im getippten Wert bleibt stehen", WI,
     "        neu = \" \".join(str(\"\" if wert is None else wert).split())[:AENDERBAR_MAX]\n",
     "        neu = str(\"\" if wert is None else wert)[:AENDERBAR_MAX]\n"),
    ("Audit protokolliert den Vorschlag statt des Ausgefuehrten", AG,
     "                    args=exec_args,\n", "                    args=args,\n"),
    ("Karte bietet gar keine aenderbaren Felder an", WI,
     "            \"aenderbar\": aenderbare_felder(name, args),\n",
     "            \"aenderbar\": [],\n"),
    ("keine Quittung an die Karte", WI,
     "        if erledigt_grund != \"nicht_zustellbar\":\n", "        if False:\n"),
    ("Anfrage bleibt nach Ende offen", WI,
     "        _offen.pop(kennung, None)\n", "        pass\n"),
    ("App gilt als dialogfaehig", MA,
     "        _kann_bestaetigen = msg.get(\"bestaetigung\") is True\n",
     "        _kann_bestaetigen = True\n"),
    ("Antwort-Benutzer aus der Nachricht", MA,
     "        _wirkung.antwort(str(msg.get(\"id\") or \"\"), _ws_usernames.get(id(ws), \"\"),\n",
     "        _wirkung.antwort(str(msg.get(\"id\") or \"\"), str(msg.get(\"user\") or \"\"),\n"),
    ("Kanal je Lauf nicht gesetzt", AG,
     "        if bestaetigung is not None:\n            _kanal_token = _wirkung.kanal_cv.set(",
     "        if False:\n            _kanal_token = _wirkung.kanal_cv.set("),
    ("Browser-Chat sagt bestaetigung nicht", CJ,
     "        const msg = { type: 'task', text: finalText, lang: window._lang || 'de', bestaetigung: true };\n",
     "        const msg = { type: 'task', text: finalText, lang: window._lang || 'de' };\n"),
    ("Karte per innerHTML (XSS)", BJ,
     "                    dl.appendChild(_el('dd', null, wert));\n",
     "                    var dd2 = _el('dd'); dd2.innerHTML = wert;"
     " dl.appendChild(dd2);\n"),
    # Anker bewusst OHNE die Folgezeile: die alte Fassung zog
    # `status.textContent = erlaubt` mit und traf nicht mehr, nachdem zwischen
    # dem Sperren und dem Status das Einsammeln der Korrekturen dazukam.
    ("Knoepfe nach dem Klick nicht gesperrt (Doppelklick)", BJ,
     "            ja.disabled = true;\n            nein.disabled = true;\n", ""),
    ("Server-Quittung ueberschreibt den Status nicht", BJ,
     "        if (st) {\n            st.textContent = T('bestaetigung.status.' + grund,\n",
     "        if (st && !st.textContent) {\n            st.textContent = T('bestaetigung.status.' + grund,\n"),
    ("ohne Modul wird gewartet statt abgelehnt", CJ,
     "                    wsSend({ type: 'bestaetigung_antwort', id: msg.id, erlaubt: false });\n", ""),
    # ── Empfaengerfeld in der Karte (Oberflaeche) ───────────────────────────
    ("Karte beachtet die Freigabe des Servers nicht", BJ,
     "                if (aenderbar.indexOf(feld) >= 0) {\n",
     "                if (false) {\n"),
    ("Korrektur wird nicht mitgesendet", BJ,
     "                if (erlaubt === true && anzahl) paket.aenderungen = korrekturen;\n", ""),
    ("Korrektur geht auch bei ABLEHNEN mit", BJ,
     "                if (erlaubt === true && anzahl) paket.aenderungen = korrekturen;\n",
     "                paket.aenderungen = korrekturen;\n"),
    ("unveraenderte Felder gelten als Korrektur", BJ,
     "                if (neu !== String(urwerte[f] == null ? '' : urwerte[f]).trim()) {\n",
     "                if (true) {\n"),
    ("Treffer aus dem Verzeichnis per innerHTML (XSS)", BJ,
     "                b.appendChild(_el('span', 'jv-best-v-name', String(t.name || '')));\n",
     "                var sn = _el('span', 'jv-best-v-name');"
     " sn.innerHTML = String(t.name || ''); b.appendChild(sn);\n"),
    ("Fehler der Adressbuch-Suche wird verschluckt", BJ,
     "                    meldung.textContent = String((res.d && res.d.error)\n",
     "                    meldung.textContent = String((res.d && res.d.nichts)\n"),
    ("Vorschlag des Modells wird nicht mehr gezeigt", BJ,
     "                    dd.appendChild(_el('div', 'jv-best-vorschlag-war',\n",
     "                    if (false) dd.appendChild(_el('div', 'jv-best-vorschlag-war',\n"),
    ("Feld bleibt nach der Antwort tippbar", BJ,
     "                try { felder[f].festschreiben(); } catch (e) { /* nur Anzeige */ }\n", ""),
    ("Suche ohne Sitzungstoken", BJ,
     "                if (tok) kopf['Authorization'] = 'Bearer ' + tok;\n", ""),
    # ── Riegel gegen den zweiten Anlauf nach einer Ablehnung ────────────────
    ("Riegel aus: zweiter Anlauf bekommt wieder eine Karte", WI,
     "    _schon = verweigert_grund(name)\n", "    _schon = \"\"\n"),
    ("Ablehnung wird nicht gemerkt", WI,
     "            _verweigert_merken(name, \"abgelehnt\")\n", "            pass\n"),
    ("Frist wird nicht gemerkt", WI,
     "            _verweigert_merken(name, \"frist\")\n", "            pass\n"),
    ("Riegel sperrt den ganzen Lauf statt je Werkzeug", WI,
     "        if wz == str(name or \"\"):\n", "        if True:\n"),
    ("Lauf-Klammer fehlt (Riegel wirkungslos)", AG,
     "        _verweigert_token = _wirkung.lauf_oeffnen()\n",
     "        _verweigert_token = None\n"),
    # ⚠ Die Luecke aus dem Code-Review 2026-10-24: `run_sub_agent` ruft
    # `run_task` erneut, und ein unbedingtes `set(set())` gab dem Unter-Agenten
    # ein frisches, LEERES Set – die Delegation war damit der Weg um den Riegel
    # herum. Die AST-Pruefung ("Klammer wird genau einmal geoeffnet") war dabei
    # gruen, deshalb muss diese Probe die WIRKUNG treffen.
    ("Unter-Agent bekommt ein frisches Set (Delegation umgeht den Riegel)", WI,
     "    if isinstance(verweigert_cv.get(), set):\n        return None\n"
     "    return verweigert_cv.set(set())\n",
     "    return verweigert_cv.set(set())\n"),
    ("Adressbuch-Klammer erbt nicht (geprueft gilt als ungeprueft)", AB,
     "    if isinstance(aufgeloest_cv.get(), set):\n        return None\n"
     "    return aufgeloest_cv.set(set())\n",
     "    return aufgeloest_cv.set(set())\n"),
    # ── Herkunft der Adresse ────────────────────────────────────────────────
    ("Herkunft wird nicht mitgeschickt", WI,
     "            \"herkunft\": herkunft_felder(name, args),\n", ""),
    ("unbekannte Herkunft gilt als geprueft", WI,
     "        raus[feld] = (\"unbekannt\" if ist is None\n",
     "        raus[feld] = (\"aufgeloest\" if ist is None\n"),
    ("eine uebernommene Adresse unter mehreren faellt nicht auf", AB,
     "    return all(a in menge for a in adressen)\n",
     "    return any(a in menge for a in adressen)\n"),
    ("die Suche vermerkt ihre Treffer nicht", EM,
     "            adressbuch.merken([t.get(\"adresse\") for t in treffer])\n",
     "            pass\n"),
    ("Karte zeigt die Herkunft nicht an", BJ,
     "                    if (hk === 'uebernommen' || hk === 'aufgeloest') {\n",
     "                    if (false) {\n"),
    ("uebernommen wird nicht als Warnung gekennzeichnet", BJ,
     "                        var hz = _el('div', 'jv-best-herkunft is-' + hk,\n",
     "                        var hz = _el('div', 'jv-best-herkunft',\n"),
    # ── Versendemaske OHNE Empfaenger ───────────────────────────────────────
    ("Pflichtfeld wird nicht angeboten (keine Maske ohne Empfaenger)", WI,
     "    return [f for f in erlaubt if f in (args or {}) or f in muss]\n",
     "    return [f for f in erlaubt if f in (args or {})]\n"),
    ("Pflichtfelder werden der Karte nicht gemeldet", WI,
     "            \"pflicht\": pflichtfelder(name),\n", ""),
    ("ein gewaehlter Empfaenger wird verworfen (Pflicht ignoriert)", WI,
     "        if f not in (ziel or {}) and f not in set(pflichtfelder(name)):\n",
     "        if f not in (ziel or {}):\n"),
    ("email_senden hat kein Pflichtfeld mehr", WI,
     "    \"email_senden\": (\"an\",),\n    \"email_weiterleiten\": (\"an\",),\n", ""),
    ("Karte traegt fehlende Pflichtfelder nicht nach", BJ,
     "        if (_offeneP.length) {\n", "        if (false) {\n"),
    ("Ausfuehren bleibt trotz leerem Pflichtfeld frei", BJ,
     "            ja.disabled = !!fehlt;\n", "            ja.disabled = false;\n"),
    ("die Karte sagt nicht, dass der Empfaenger fehlt", BJ,
     "                _pflichtHinweis.textContent = fehlt\n",
     "                _pflichtHinweis.textContent = false\n"),
    # Anker mit der Vorzeile: der Rueckruf steht ZWEIMAL (Tippen und
    # Vorschlags-Klick) – ein Anker ohne Kontext traf beide und faellt im
    # Harness als "???" aus.
    ("Tippen loest die Pflichtpruefung nicht aus", BJ,
     "            timer = setTimeout(function () { suchen(wert); }, TIPP_MS);\n"
     "            if (typeof beiAenderung === 'function') beiAenderung('getippt');\n",
     "            timer = setTimeout(function () { suchen(wert); }, TIPP_MS);\n"),
    # ── Zusagen am Feld muessen das Feld einloesen (Code-Review 2026-10-24) ──
    # Die erste Fassung hatte EINEN Hinweis an allen Empfaengerfeldern aller
    # drei Werkzeuge. Jede dieser Proben stellt eine der drei Luecken her.
    ("cc verspricht wieder die Versendemaske (Kopie faellt still weg)", EM,
     '                   "description": ("Kopie-Empfaenger (optional)."\n'
     '                                   + _AN_BASIS + _CC_HINWEIS)},\n',
     '                   "description": ("Kopie-Empfaenger (optional)."\n'
     '                                   + _AN_BASIS + _AN_MASKE)},\n'),
    ("email_entwurf bekommt die Masken-Zusage (widerspricht sich selbst)", EM,
     '                   "description": "Empfaenger (darf leer bleiben)." + _AN_BASIS},\n',
     '                   "description": ("Empfaenger (darf leer bleiben)."\n'
     '                                   + _AN_BASIS + _AN_MASKE)},\n'),
    ("ohne Oberflaeche laeuft der leere Empfaenger weiter (Regel-Fehlversuch)", EM,
     "            if not mail_anhang.mit_mensch():\n", "            if False:\n"),
    # ── Herkunft nach einer Korrektur ───────────────────────────────────────
    ("Herkunft wird nach der Korrektur nicht nachgezogen (Warnung bleibt)", BJ,
     "            if (!hz || !felder[feld]) return;\n",
     "            if (true) return;\n"),
    ("der WEG der Korrektur wird nicht durchgereicht", BJ,
     "                    if (typeof beiAenderung === 'function') beiAenderung('adressbuch');\n",
     "                    if (typeof beiAenderung === 'function') beiAenderung();\n"),
]

DATEIEN = [WI, AG, MA, CJ, BJ, AB, EM, "tests/test_bsi_h9.py",
           "tests/test_bsi_h9_ui.js", "tests/test_email_rules.py"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    """Beide Waechter; Summe der FAILs. -1 = einer konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    # ⚠ DRITTER WAECHTER: `test_email_rules.py` gehoert dazu, seit Proben an
    # `skills/email/main.py` haengen (der Merker der Adressbuch-Suche). Ohne
    # ihn blieb die Probe "die Suche vermerkt ihre Treffer nicht" stumm – nicht
    # weil der Waechter blind war, sondern weil er nicht LIEF.
    for cmd, muster in (([PY, str(WAECHTER)], r"Ergebnis: (\d+) bestanden, (\d+) fehlgeschlagen"),
                        (["node", str(UI)], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
                        ([PY, str(MAILREGELN)], r"(\d+) OK, (\d+) FAIL")):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=600, cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            # Ein haengender Waechter ist "konnte nicht laufen" – das Harness
            # darf daran nicht selbst sterben (2026-10-04 so passiert).
            return -1, "timeout"
        m = re.search(muster, r.stdout)
        if r.returncode == 2 or not m:
            return -1, r.returncode
        summe += int(m.group(2))
    return summe, 0


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-52s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-52s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-52s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
