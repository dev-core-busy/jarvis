"""Gegenprobe zu tests/test_bsi_m5.py: beisst der Waechter?

Jede Probe dreht EINEN Teil von M5 zurueck (Python-Ersetzung ganzer Zeilen),
laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher gruener
Basislauf, danach Byte-Gleichheit aller Dateien per md5, ohne Bytecode, mit
Laufmarke (abgeschossener Lauf wird beim naechsten Start zurueckgenommen).
Harness wie gegen_bsi_m1_m2.py.

⚠ NIE in einem Sammellauf mitlaufen lassen (Register: patcht Dateien).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKE = ROOT / "tests" / ".gegen_bsi_m5.laufmarke"

TR = "backend/geheimnis_tresor.py"
GB = "backend/geheimnis_bestaetigung.py"
CF = "backend/config.py"
MA = "backend/main.py"
SR = "backend/secret_reveal.py"
ML = "backend/mail_accounts.py"
AM = "backend/ai_mouse_signatur.py"
SX = "backend/sandbox.py"
HI = "deploy/security/haertung_installieren.sh"
PW = "frontend/js/pwreveal.js"
SC = "frontend/js/skillcfg.js"
SA = "frontend/js/sap.js"
AP = "frontend/js/app.js"
SK = "backend/secret_key.py"
KS = "backend/knowledge_sync.py"

PROBEN = [
    ("mail_accounts liest den Schluessel wieder selbst", ML,
     "        return Fernet(_tresor.modul_schluessel(SCHLUESSEL_DATEI, SCHLUESSEL_MODUS))\n",
     "        return Fernet(SCHLUESSEL_DATEI.read_bytes().strip())\n"),
    ("ai_mouse_signatur umgeht den Tresor", AM,
     "    roh = _tresor.modul_schluessel(SCHLUESSEL_DATEI, SCHLUESSEL_MODUS)\n",
     "    roh = SCHLUESSEL_DATEI.read_bytes().strip()\n"),
    ("Altbestand wird nicht verpackt", TR,
     "    if roh:\n        if haupt is not None:\n",
     "    if roh:\n        if False:\n"),
    ("verpackt ohne Hauptschluessel: ueberspringt den Fehler", TR,
     "    if roh.startswith(PRAEFIX_SCHLUESSEL):\n",
     "    if roh.startswith(PRAEFIX_SCHLUESSEL) and haupt is not None:\n"),
    ("verpackt ohne Hauptschluessel: legt NEUEN Schluessel an", TR,
     "    if roh.startswith(PRAEFIX_SCHLUESSEL):\n",
     "    if roh.startswith(PRAEFIX_SCHLUESSEL) and haupt is None:\n        roh = b\"\"\n"
     "    if roh.startswith(PRAEFIX_SCHLUESSEL):\n"),
    ("Credential-Verzeichnis wird nicht gelesen", TR,
     "    if cd:\n        aus.append((Path(cd) / CREDENTIAL_NAME, \"systemd-Credential\"))\n",
     ""),
    ("Felder werden nicht verschluesselt", TR,
     "    return _baum(daten, wert_verschluesseln)\n", "    return daten\n"),
    ("Namensregel ohne Endungen (MCP-Token, ibs_api_key)", TR,
     "    return n in GEHEIME_NAMEN or n.endswith(GEHEIME_ENDUNGEN)\n",
     "    return n in GEHEIME_NAMEN\n"),
    ("Namensregel per Teilstring 'token'", TR,
     "    return n in GEHEIME_NAMEN or n.endswith(GEHEIME_ENDUNGEN)\n",
     "    return n in GEHEIME_NAMEN or n.endswith(GEHEIME_ENDUNGEN) or \"token\" in n\n"),
    ("unlesbarer Wert wird geleert statt stehen gelassen", TR,
     "              \"– bleibt verpackt stehen\", flush=True)\n        return wert\n",
     "              \"– bleibt verpackt stehen\", flush=True)\n        return \"\"\n"),
    ("config schreibt settings.json ohne Verpacken", CF,
     "        data = _tresor.verschluessele_baum(data)\n", "        pass\n"),
    ("config verpackt den Altbestand nicht beim Start", CF,
     "            data = _lies_settings_datei(self.SETTINGS_FILE)\n            self._geheimfelder_verpacken()\n",
     "            data = _lies_settings_datei(self.SETTINGS_FILE)\n"),
    ("get_setting liest roh", CF,
     "                data = _lies_settings_datei(self.SETTINGS_FILE)\n                return data.get(\"extra\", {}).get(key, default)\n",
     "                data = json.loads(self.SETTINGS_FILE.read_text())\n                return data.get(\"extra\", {}).get(key, default)\n"),
    ("Profil: leerer Schluessel ueberschreibt", CF,
     "                                and (val.startswith(\"***\") or not val.strip()):\n",
     "                                and val.startswith(\"***\"):\n"),
    ("Bestaetigung an den Benutzer statt an das Token gebunden", GB,
     "    return hashlib.sha256(str(token or \"\").encode(\"utf-8\")).hexdigest()\n",
     "    return \"alle\"\n"),
    ("Bestaetigung laeuft nie ab", GB,
     "    if wer != str(user) or bis <= jetzt:\n", "    if wer != str(user):\n"),
    ("Modulschluessel erst beim ersten Zugriff verpackt (kein Start-Hook)", MA,
     "@app.on_event(\"startup\")\nasync def _geheimnis_modulschluessel_verpacken():\n",
     "async def _geheimnis_modulschluessel_verpacken():\n"),
    ("Start-Verpacken ueberspringt rohe Dateien", TR,
     "        if ist_verpackt(pf):\n            aus[name] = \"war verpackt\"\n            continue\n",
     "        if True:\n            aus[name] = \"war verpackt\"\n            continue\n"),
    ("reveal ohne Bestaetigung", MA,
     "    fehlt = _bestaetigung_fehlt(request, user)\n    if fehlt is not None:\n        _prot(\"bestaetigung fehlt\")\n",
     "    fehlt = None\n    if fehlt is not None:\n        _prot(\"bestaetigung fehlt\")\n"),
    ("Agent-Key ohne Bestaetigung", MA,
     "        _klartext_abruf_protokollieren(user, \"agentkey\", \"bestaetigung fehlt\")\n        return fehlt\n",
     "        pass\n"),
    ("Bestaetigung antwortet 401 (Seite meldet ab)", MA,
     "         \"error\": \"Zum Anzeigen bitte mit deinem Kennwort bestätigen.\"},\n        status_code=403)\n",
     "         \"error\": \"Zum Anzeigen bitte mit deinem Kennwort bestätigen.\"},\n        status_code=401)\n"),
    ("Fehlversuch zaehlt nicht beim Anmeldeschutz", MA,
     "        _record_login_attempt(ip, user)\n        _sicherheits_log.ereignis(\"geheimnis_bestaetigung\"",
     "        _sicherheits_log.ereignis(\"geheimnis_bestaetigung\""),
    ("Kennwort geht trotz Kontosperre an PAM/AD", MA,
     "    gesperrt = _konto_sperre_antwort(user)\n    if gesperrt is not None:\n        return gesperrt\n",
     ""),
    ("Skill-Config wieder im Klartext", MA,
     "    cfg, gesetzt = _sr.skill_config_maskiert(cfg)\n", "    gesetzt = []\n"),
    ("leeres Geheimfeld loescht beim Speichern", MA,
     "    body = _sr.leere_geheimfelder_behalten(body, sm.get_skill_config(name) or {})\n", ""),
    ("Agent-Key-Liste mit Schluessel", MA,
     "    return JSONResponse({\"keys\": [_agent_key_maskiert(k) for k in _load_agent_keys()],\n",
     "    return JSONResponse({\"keys\": _load_agent_keys(),\n"),
    ("WebDAV-Status mit Kennwort", MA,
     "        \"password\": \"\",\n        \"password_gesetzt\": True,\n",
     "        \"password\": cfg.get(\"password\", \"jarvis\"),\n"),
    ("gespeicherter LLM-Key an beliebige Adresse", MA,
     "    if norm(body.get(\"api_url\")) != norm(prof.get(\"api_url\")):\n        return None\n",
     ""),
    ("gespeicherter LLM-Key an anderen Anbieter", MA,
     "    if norm(body.get(\"provider\") or prof.get(\"provider\")) != norm(prof.get(\"provider\")):\n        return None\n",
     ""),
    ("Verschachteltes Geheimfeld nicht maskiert", SR,
     "            elif isinstance(v, dict):\n                aus[k] = _geh(v, p)\n",
     "            elif isinstance(v, dict):\n                aus[k] = v\n"),
    ("Sandbox: Credential-Verzeichnis lesbar", SX,
     "_SYSTEM_DENY_PREFIX = (\"/root\", \"/boot\", \"/proc\", \"/sys\", \"/run/credentials\", \"/etc/jarvis\")\n",
     "_SYSTEM_DENY_PREFIX = (\"/root\", \"/boot\", \"/proc\", \"/sys\")\n"),
    ("Sandbox: Shell darf den Hauptschluessel lesen", SX,
     "    r'geheimnis\\.key\\b|/run/credentials\\b|CREDENTIALS_DIRECTORY\\b|'\n", ""),
    ("Skript ersetzt einen vorhandenen Schluessel", HI,
     "if [ ! -s \"$GEHEIMNIS_DATEI\" ]; then\n", "if true; then\n"),
    ("kein LoadCredential", HI,
     "LoadCredential=geheimnis:$GEHEIMNIS_DATEI\"\n", "\"\n"),
    ("Schluessel weltlesbar", HI,
     "    chmod 0600 \"$GEHEIMNIS_DATEI\"\n", "    chmod 0644 \"$GEHEIMNIS_DATEI\"\n"),
    ("HAERTUNG=aus nimmt auch den Geheimnis-Zugang", HI,
     "    entferne \"$BACKEND_DROPIN\"\n    entferne \"$BROKER_DROPIN\"\n",
     "    entferne \"$BACKEND_DROPIN\"\n    entferne \"$BROKER_DROPIN\"\n    entferne \"$GEHEIMNIS_DROPIN\"\n"),
]

PROBEN += [
    ("UI: kein zweiter Versuch nach der Bestaetigung", PW,
     "                    return bestaetigt ? einmal() : e;\n", "                    return e;\n"),
    ("UI: jeder Abruf oeffnet einen eigenen Dialog", PW,
     "        if (offeneBestaetigung) return offeneBestaetigung;\n", ""),
    ("UI: Abbrechen schliesst den Dialog nicht", PW,
     "            if (huelle.parentNode) huelle.parentNode.removeChild(huelle);\n", ""),
    ("UI: Fehler im Dialog bleibt verborgen", PW,
     "                fehler.hidden = false;\n                pw.focus();\n",
     "                pw.focus();\n"),
    ("UI: abgebrochenes Aufdecken laesst das Feld offen", PW,
     "            if (e.d && e.d.reauth && inp.type !== 'password') {\n",
     "            if (false) {\n"),
    ("UI: skillcfg fuellt das Geheimfeld wieder", SC,
     "                        + ' data-key=\"' + esc(key) + '\" data-type=\"string\" value=\"\"'\n",
     "                        + ' data-key=\"' + esc(key) + '\" data-type=\"string\" value=\"' + esc(val != null ? val : '') + '\"'\n"),
    ("UI: skillcfg ohne Quelle fuer das Auge", SC,
     "                        + ' data-pw-quelle=\"skill\" data-pw-kennung=\"' + esc(name + ':' + key) + '\"'\n",
     ""),
    ("UI: sap.js schreibt das Kennwort wieder ins Feld", SA,
     "                    geheimFeld('sap-hana-pass', 'sap:hana_password', gs.indexOf('hana_password') >= 0);\n",
     "                    if ($('sap-hana-pass')) $('sap-hana-pass').value = c.hana_password || '';\n"),
    ("UI: app.js laedt den Profil-Key wieder beim Oeffnen", AP,
     "            inputKey.placeholder = (profile && profile.api_key) ? '••••••••' : '';\n",
     "            if (id) fetch(`/api/profiles/${id}/key`, {}).then(r => r.json()).then(d => { inputKey.value = d.api_key; });\n"),
]

PROBEN += [
    (".secret_key bleibt roh liegen", SK,
     "    if haupt is not None:\n        # Altbestand im Klartext: verpacken",
     "    if False:\n        # Altbestand im Klartext: verpacken"),
    (".secret_key: ohne Hauptschluessel NEU erzeugt", SK,
     "        if haupt is None:\n            print(f\"[SECURITY] {datei.name} ist verpackt",
     "        if haupt is None:\n            wert = \"\"\n        if False:\n            print(f\"[SECURITY] {datei.name} ist verpackt"),
    ("auth_state: Speichern ohne Verpacken", MA,
     "    _AUTH_STATE_FILE.write_text(json.dumps(_t.verschluessele_baum(state), indent=4))\n",
     "    _AUTH_STATE_FILE.write_text(json.dumps(state, indent=4))\n"),
    ("auth_state: Altbestand wird nicht verpackt", MA,
     "            if _t.hauptfernet() is not None and _t.klartext_felder(roh):\n",
     "            if False:\n"),
    ("auth_state: Laden oeffnet nicht", MA,
     "            state = _t.entschluessele_baum(roh)\n", "            state = roh\n"),
    ("Anmeldung ohne Lesbarkeitspruefung (500 statt Meldung)", MA,
     "        if not _totp_secret_lesbar(user_state[\"totp_secret\"]):\n",
     "        if False:\n"),
    ("knowledge_sync: Speichern ohne Verpacken", KS,
     "        tmp.write_text(json.dumps(_t.verschluessele_baum(daten), indent=2, ensure_ascii=False),\n",
     "        tmp.write_text(json.dumps(daten, indent=2, ensure_ascii=False),\n"),
    ("Start-Hook stoesst auth_state/knowledge_sync nicht an", MA,
     "    for name, fn in ((\"auth_state.json\", _load_auth_state),\n",
     "    for name, fn in ():\n        pass\n    for name, fn in ((\"auth_state.json\", None),\n"),
    ("knowledge_sync: Altbestand wird nicht verpackt", KS,
     "        if nachverpacken:\n", "        if False:\n"),
]

PROBEN += [
    ("Backend ohne Credential wird nicht nachgestartet", HI,
     "        \"$SYSTEMCTL\" try-restart --no-block jarvis.service || true\n", "        true\n"),
    ("Nachstart auch MIT Credential (Neustart bei jedem Broker-Start)", HI,
     "    if \"$SYSTEMCTL\" is-active --quiet jarvis.service && [ ! -e \"$CRED_DATEI\" ]; then\n",
     "    if \"$SYSTEMCTL\" is-active --quiet jarvis.service; then\n"),
    ("Nachstart blockierend (wartet auf den Broker)", HI,
     "try-restart --no-block jarvis.service", "try-restart jarvis.service"),
    ("verpackt ohne Schluessel wird nie gemeldet", TR,
     "    if hauptfernet() is not None:\n        return []\n    d = Path(data_dir)\n",
     "    return []\n    d = Path(data_dir)\n"),
    ("Start-Hook meldet fehlenden Schluessel nicht", MA,
     "            _sicherheits_log.ereignis(\"geheimnis_schluessel_fehlt\", ergebnis=\"fehler\",\n                                      dateien=fehlt)\n",
     "            pass\n"),
]

DATEIEN = [SK, KS, TR, GB, CF, MA, SR, ML, AM, SX, HI, PW, SC, SA, AP,
           "tests/test_bsi_m5.py", "tests/test_bsi_m5_ui.js"]

WAECHTER = [
    (["python3", "tests/test_bsi_m5.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
    (["node", "tests/test_bsi_m5_ui.js"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf():
    """Alle Waechter; Summe der FAILs. -1 = einer konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    for cmd, muster in WAECHTER:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                               cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            return -1, "timeout " + cmd[-1]
        m = re.search(muster, r.stdout)
        if r.returncode == 2 or not m:
            return -1, f"{cmd[-1]} rc={r.returncode} {r.stdout.strip()[-160:]}"
        summe += int(m.group(2))
    return summe, 0


def zuruecknehmen():
    """Rueckstand eines abgeschossenen Laufs zuruecknehmen (Laufmarke)."""
    if not MARKE.exists():
        return
    try:
        alt = json.loads(MARKE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        print("ABBRUCH: Laufmarke unlesbar – Arbeitsbaum von Hand pruefen")
        sys.exit(2)
    for d, hexinhalt in alt.items():
        (ROOT / d).write_bytes(bytes.fromhex(hexinhalt))
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgenommen.")


def main() -> int:
    zuruecknehmen()
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, %s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    MARKE.write_text(json.dumps({d: b.hex() for d, b in sicherung.items()}), encoding="utf-8")
    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu, 1), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-58s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-58s Waechter konnte nicht laufen (%s)" % (name, rc))
            else:
                print("  ZAHN %-58s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)
        if MARKE.exists():
            MARKE.unlink()

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
