#!/usr/bin/env python3
"""Gegenprobe zu tests/test_fernzugang.py und tests/test_fernzugang_ui.js: beissen sie?

Jede Probe dreht EINEN Teil zurueck (Python-Ersetzung ganzer Zeilen), laesst den
zustaendigen Waechter laufen und erwartet mindestens einen FAIL. Vorher gruener
Basislauf BEIDER Waechter, danach Byte-Gleichheit aller Dateien per md5. Ohne
Bytecode.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ["python3", "tests/test_fernzugang.py"]
JS = [shutil.which("node") or "node", "tests/test_fernzugang_ui.js"]
FZ = "backend/broker/fernzugang.py"
META = "backend/broker/meta.py"
DAEMON = "backend/broker/daemon.py"
MAIN = "backend/main.py"
FW = "deploy/security/firewall.sh"
SSH = "deploy/security/ssh_haertung.sh"
UI = "frontend/js/fernzugang.js"

PROBEN = [
    # ── Broker-Modul ──
    ("verwerfen nimmt eine bestaetigte Haertung zurueck", FZ, PY,
     '        if not laeuft or _konf().get("SSH_HAERTUNG") == "an":\n',
     '        if not laeuft:\n'),
    ("bestaetigen ohne laufenden Test", FZ, PY,
     '        if not laeuft:\n            return {"ok": False, "meldung": "Kein laufender Test – die Frist ist abgelaufen "\n'
     '                                            "oder er wurde verworfen."}\n        r = _lauf(skript + ["--anwenden"])\n',
     '        r = _lauf(skript + ["--anwenden"])\n'),
    ("Netze ohne Zeichen-Vorpruefung", FZ, PY,
     '_NETZ_ZEICHEN = re.compile(r"^[0-9A-Fa-f.:/,\\s]*$")\n', '_NETZ_ZEICHEN = re.compile(r".*")\n'),
    ("root zaehlt immer als Zugang", FZ, PY,
     '        k["zaehlt"] = k["anzahl"] > 0 and (k["art"] != "root" or root_modus == "schluessel")\n',
     '        k["zaehlt"] = k["anzahl"] > 0\n'),
    ("Fingerabdruecke werden nicht gelesen", FZ, PY,
     '            m = re.match(r"(\\d+)\\s+(\\S+)\\s+(.*?)\\s*\\((\\w+)\\)\\s*$", rest)\n',
     '            m = None\n'),
    ("Frist wird nicht gemerkt", FZ, PY,
     '        if r.returncode == 0:\n            _frist_setzen("haertung", time.time() + FRIST_S)\n', ''),
    # ── Freigabe-Code ──
    ("jede Aktion ohne Code", META, PY,
     '        if aktion != "verwerfen":\n            fehler = _nachweis(args, by, op, audit_key, peer)\n',
     '        if False:\n            fehler = _nachweis(args, by, op, audit_key, peer)\n'),
    ("kein Audit der Ausfuehrung", META, PY,
     '        policy.audit(by, op, audit_key, "executed", rc=erg.get("rc"),\n',
     '        (lambda *a, **k: None)(by, op, audit_key, "executed", rc=erg.get("rc"),\n'),
    # ── Broker-Prozess / API ──
    ("Meta-Ops im Event-Loop", DAEMON, PY,
     # seit 2026-10-18 im eigenen Pool (_KURZ) statt asyncio.to_thread
     '        antwort = await loop.run_in_executor(_KURZ, functools.partial(meta.behandeln, op, args, peer=peer))\n',
     '        antwort = meta.behandeln(op, args, peer=peer)\n'),
    ("Status-Endpunkt ohne Admin-Pflicht", MAIN, PY,
     'async def broker_ssh_status(request: Request, user: str = Depends(require_local_auth)):\n',
     'async def broker_ssh_status(request: Request, user: str = Depends(require_auth)):\n'),
    # ── Skripte ──
    ("zweiter Netze-Test ueberschreibt den Rueckfall-Wert", FW, PY,
     '        if [ ! -f "$RUECKFALL_DATEI" ]; then\n            mkdir -p "$(dirname "$RUECKFALL_DATEI")"\n',
     '        if true; then\n            mkdir -p "$(dirname "$RUECKFALL_DATEI")"\n'),
    ("Netze-Test ohne eingerichteten Filter", FW, PY,
     '        _fw_eingerichtet || { echo "ABBRUCH: Paketfilter nicht eingerichtet',
     '        true || { echo "ABBRUCH: Paketfilter nicht eingerichtet'),
    ("Netze-Test ohne Sitzungspruefung", FW, PY,
     '        if ! bash "$SELF" --zeigen >/dev/null; then\n', '        if false; then\n'),
    ("Rueckfall stellt den alten Wert nicht her", FW, PY,
     '            _konf_setzen SSH_NETZE "\\"$(head -1 "$RUECKFALL_DATEI")\\""\n', ''),
    ("Netze-Test persistiert sofort", FW, PY,
     '        bash "$SELF" --setzen || { bash "$SELF" --rueckfall; exit 1; }\n',
     '        bash "$SELF" --anwenden || { bash "$SELF" --rueckfall; exit 1; }\n'),
    ("SSH-Test trotz aktiver Haertung", SSH, PY,
     '        if [ "$(_konf SSH_HAERTUNG)" = "an" ]; then\n            echo "[SSH] ABBRUCH: Haertung ist bereits aktiv',
     '        if false; then\n            echo "[SSH] ABBRUCH: Haertung ist bereits aktiv'),
    ("Konten-Ausgabe ohne Fingerabdruecke", SSH, PY,
     '            ssh-keygen -lf "$f" 2>/dev/null | sed "s/^/FP $u /"\n', '            :\n'),
    # ── Oberflaeche ──
    ("Verwerfen fragt den Code ab", UI, JS,
     "            if (aktion !== 'verwerfen') {\n                var c = this._code();\n                if (c === null) return;\n"
     "                body.nachweis = c;\n            }\n            var knopf = { test: 'sec-ssh-h-test'",
     "            {\n                var c = this._code();\n                if (c === null) return;\n"
     "                body.nachweis = c;\n            }\n            var knopf = { test: 'sec-ssh-h-test'"),
    ("Rueckfrage vor dem Test wird ignoriert", UI, JS,
     "'Die Anmeldung per Kennwort wird jetzt abgeschaltet.\\n\\nMelde dich danach in einem NEUEN Terminal per SSH mit Schlüssel an. Erst wenn das klappt, hier „Bestätigen“ klicken. Ohne Bestätigung wird die Änderung nach 5 Minuten von selbst zurückgenommen.\\n\\nFortfahren?'))) return;",
     "'Die Anmeldung per Kennwort wird jetzt abgeschaltet.\\n\\nMelde dich danach in einem NEUEN Terminal per SSH mit Schlüssel an. Erst wenn das klappt, hier „Bestätigen“ klicken. Ohne Bestätigung wird die Änderung nach 5 Minuten von selbst zurückgenommen.\\n\\nFortfahren?'))) {}"),
    ("Anleitung klappt nicht von selbst auf", UI, JS,
     "            if (anl && !zm.nein && !zm.schluessel) anl.open = true;\n", ''),
    ("Code-Fehler per alert statt am Knopf", UI, JS,
     "                  self._ergebnis(ergebnisId, !!(d && d.ok), text);\n",
     "                  window.alert(text);\n"),
    ("root-Modus fest statt aus der Auswahl", UI, JS,
     "                body.root_modus = w ? w.value : 'nein';\n", "                body.root_modus = 'nein';\n"),
    ("Paketfilter fehlt: Knopf bleibt aktiv", UI, JS,
     "            if (nTest) nTest.disabled = !!(d && !d.firewall_eingerichtet);\n", ''),
    # ── Maus-Helfer "Erlaubte Netze" ──
    ("Vorschlaege nicht zusammengefasst", UI, JS,
     "                if (gesehen[n.text] !== undefined) { items[gesehen[n.text]].hinweise.push(hinweis); return; }\n", ''),
    ("Abdeckung nur bei exakt gleichem Eintrag", UI, JS,
     "                return n && xn && n.praefix >= xn.praefix && enthaelt(x, ip);\n",
     "                return false;\n"),
    ("keine Warnung fuer ausgesperrte SSH-Herkunft", UI, JS,
     "                if (fehlen.length) {\n", "                if (false) {\n"),
    ("Aktualisieren verwirft die angefangene Liste", UI, JS,
     "            if (!this._netzeGeaendert) {\n", "            if (true) {\n"),
    ("Umfang-Auswahl wirkungslos", UI, JS,
     "            var n = netzNormieren(roh, umfang);\n", "            var n = netzNormieren(roh);\n"),
    ("Host-Bits nicht genullt", UI, JS,
     "        var netz = ip.n & maske;\n", "        var netz = ip.n;\n"),
    ("nach Erfolg bleibt die Liste 'geaendert'", UI, JS,
     "                                function () { self._netzeGeaendert = false; });\n",
     "                                function () {});\n"),
    ("Fehlversuche zaehlen als Anmeldung", FZ, PY,
     '_ANMELDUNG = re.compile(r"^(\\S+)\\s.*Accepted (\\S+) for (\\S+) from (\\S+) port \\d+")\n',
     '_ANMELDUNG = re.compile(r"^(\\S+)\\s.*(?:Accepted|Failed) (\\S+) for (\\S+) from (\\S+) port \\d+")\n'),
    ("Einzeladressen (/32) als lokales Netz", FZ, PY,
     "            if netz.is_loopback or netz.is_link_local or netz.prefixlen == netz.max_prefixlen:\n",
     "            if netz.is_loopback or netz.is_link_local:\n"),
    ("keine Obergrenze fuer Anmelde-Adressen", FZ, PY,
     '    anmeldungen = sorted(je_ip.values(), key=lambda e: e["zuletzt"], reverse=True)[:15]\n',
     '    anmeldungen = sorted(je_ip.values(), key=lambda e: e["zuletzt"], reverse=True)\n'),
    ("Status ohne Adresse der Web-Sitzung", MAIN, PY,
     '    res["deine_adresse"] = request.client.host if request.client else ""\n', ''),
    ("Restfrist wird nicht angezeigt", UI, JS,
     "            this._fristBis.haertung = th.laeuft && th.rest_s != null ? jetzt + th.rest_s * 1000 : 0;\n",
     "            this._fristBis.haertung = 0;\n"),
    # ── Schluessel hinterlegen/entfernen (2026-10-20) ──
    ("Schluessel: jeder Typ zulaessig", FZ, PY,
     '    if not m or m.group(1) not in _TYPEN:\n', '    if not m:\n'),
    ("Schluessel: RSA ohne Mindestlaenge", FZ, PY,
     '    if typ == "ssh-rsa" and bits < RSA_MIN_BITS:\n', '    if False:\n'),
    ("Schluessel: Steuerzeichen im Kommentar bleiben", FZ, PY,
     '    kommentar = "".join(c for c in kommentar if c.isprintable())[:200].strip()\n',
     '    kommentar = kommentar[:200].strip()\n'),
    ("Schluessel: beliebiges Konto", FZ, PY,
     '    ziel = next((k for k in konten if k["name"] == konto), None)\n',
     '    ziel = next((k for k in konten if k["name"] == konto),\n'
     '                {"name": konto, "art": "sudo", "anzahl": 0, "schluessel": []})\n'),
    ("Schluessel: authorized_keys folgt Symlinks", FZ, PY,
     '        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=sfd)\n',
     '        fd = os.open(name, os.O_RDONLY, dir_fd=sfd)\n'),
    ("Schluessel: .ssh folgt Symlinks", FZ, PY,
     '            return os.open(".ssh", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=hfd)\n',
     '            return os.open(".ssh", os.O_RDONLY | os.O_DIRECTORY, dir_fd=hfd)\n'),
    ("Schluessel: Datei mit 0644", FZ, PY,
     '    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=sfd)\n',
     '    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=sfd)\n'),
    ("Schluessel: .ssh mit 0755", FZ, PY,
     '        os.mkdir(".ssh", 0o700, dir_fd=hfd)\n', '        os.mkdir(".ssh", 0o755, dir_fd=hfd)\n'),
    ("Schluessel: Aussperr-Schutz aus", FZ, PY,
     '                    if not zugang:\n', '                    if False:\n'),
    ("Schluessel: Eingabezeile wird roh geschrieben", FZ, PY,
     "        zeile = f\"{k['typ']} {k['daten']}\" + (f\" {k['kommentar']}\" if k[\"kommentar\"] else \"\")\n",
     '        zeile = str(text).strip() + " x"\n'),
    ("Schluessel: ohne Freigabe-Code", META, PY,
     '        fehler = _nachweis(args, by, op, audit_key, peer)\n        if fehler:\n            return fehler\n'
     '        erg = fernzugang.schluessel(',
     '        erg = fernzugang.schluessel('),
    ("Schluessel: Endpunkt ohne Admin-Pflicht", MAIN, PY,
     'async def broker_ssh_schluessel(request: Request, user: str = Depends(require_local_auth)):\n',
     'async def broker_ssh_schluessel(request: Request, user: str = "admin"):\n'),
    ("Schluessel-UI: keine Rueckfrage vor dem Hinterlegen", UI, JS,
     "                if (!window.confirm(T('security.ssh_schl_confirm',\n",
     "                if (false && !window.confirm(T('security.ssh_schl_confirm',\n"),
    ("Schluessel-UI: privater Schluessel nicht erkannt", UI, JS,
     "        if (roh.indexOf('PRIVATE KEY') >= 0) return { fehler: 'privat' };\n", ""),
    ("Schluessel-UI: Fingerabdruck mit Fuellzeichen", UI, JS,
     "            return 'SHA256:' + btoa(s).replace(/=+$/, '');\n",
     "            return 'SHA256:' + btoa(s);\n"),
    ("Schluessel-UI: Entfernen ohne Code", UI, JS,
     "            var c = this._code();\n            if (c === null) return;\n            return this._senden('/api/broker/ssh/schluessel',\n",
     "            var c = '';\n            return this._senden('/api/broker/ssh/schluessel',\n"),
]

DATEIEN = sorted({p[1] for p in PROBEN} | {"tests/test_fernzugang.py", "tests/test_fernzugang_ui.js"})


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf(befehl: list[str]) -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run(befehl, capture_output=True, text=True, timeout=600, cwd=str(ROOT), env=env)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}
    for b in (PY, JS):
        fails, rc = lauf(b)
        if fails != 0:
            print("ABBRUCH: Basislauf %s nicht gruen (FAIL=%s, rc=%s)" % (b[-1], fails, rc))
            return 2
    print("Basislauf gruen (beide Waechter).\n")

    beissen = 0
    try:
        for name, datei, waechter, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                fails, rc = lauf(waechter)
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-55s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-55s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-55s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)" % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
