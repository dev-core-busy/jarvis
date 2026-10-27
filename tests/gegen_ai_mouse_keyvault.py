#!/usr/bin/env python3
"""Gegenprobe zu tests/test_ai_mouse_keyvault.py: beisst der Waechter?

Jede Probe dreht EINE Zusage des Key-Vault-Weges zurueck, laesst den Waechter
laufen und erwartet mindestens einen FAIL. Vorher gruener Basislauf, danach
Byte-Gleichheit aller Dateien per md5. Ohne Bytecode (Register: eine .pyc aus
derselben Sekunde laedt sonst die Sabotage nach).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_ai_mouse_keyvault.py"
SIG = "backend/ai_mouse_signatur.py"

PROBEN = [
    ("keine Probesignatur beim Einrichten", SIG,
     "    _kv_probesignatur(v, kid, zert, token)\n", ""),
    ("kid darf ausserhalb des Vaults liegen", SIG,
     '    if not kid.lower().startswith(vault.lower() + "/keys/"):\n',
     "    if False:\n"),
    ("Firewall-Fall ohne Klartext", SIG,
     # ALLE drei Zweige auf einmal – einer allein bleibt stumm, weil die
     # nachgebaute Antwort (wie die echte) jeden der drei erfuellt.
     '    if icode == "ForbiddenByFirewall" or "firewall" in msg.lower() \\\n'
     '            or "Client address is not authorized" in msg:\n',
     '    if False:\n'),
    ("gespeichertes Secret auch fuer einen anderen Zugang", SIG,
     '        if (alt.get("vault"), alt.get("tenant"), alt.get("client"),\n'
     '                alt.get("anmeldung", "")) != (v, t, c, a):\n',
     "        if False:\n"),
    ("Vault-Adresse frei waehlbar", SIG,
     r'''        m = re.match(r"^https://([A-Za-z0-9-]+)\.vault\.azure\.net$", wert, re.IGNORECASE)''' + "\n",
     r'''        m = re.match(r"^https://([A-Za-z0-9-]+)\..*$", wert, re.IGNORECASE)''' + "\n"),
    ("Token als Argument statt ueber die Umgebung", SIG,
     "        r = subprocess.run(_jsign_befehl(kv, ziel, tsa), capture_output=True,\n",
     "        r = subprocess.run([x.replace('env:' + KV_TOKEN_VAR, token) for x in "
     "_jsign_befehl(kv, ziel, tsa)], capture_output=True,\n"),
    ("jsign nur am Namen erkannt", SIG,
     '        return JSIGN_JAR.is_file() and _sha(JSIGN_JAR, "sha256") == JSIGN_SHA256\n',
     "        return JSIGN_JAR.is_file()\n"),
    ("Ablauf des Vault-Zertifikats nicht geprueft", SIG,
     '    if meta["ablauf_ts"] and meta["ablauf_ts"] < time.time():\n'
     '        return _kv_fehlschlag("Das Zertifikat im Key Vault ist am %s abgelaufen."\n',
     '    if False:\n'
     '        return _kv_fehlschlag("Das Zertifikat im Key Vault ist am %s abgelaufen."\n'),
    ("Secret im Zustand", SIG,
     '            "secret_gesetzt": bool(kv.get("secret_enc")),\n',
     '            "secret_gesetzt": bool(kv.get("secret_enc")), "secret_enc": kv.get("secret_enc"),\n'),
    ("Umschalten ohne Pruefung", SIG,
     '            if not _kv_konfiguriert(d):\n                raise SignaturFehler("Es ist kein Key-Vault-Zugang hinterlegt.")\n',
     # Der Zweig bleibt syntaktisch stehen (ein leerer if-Block waere ein
     # Syntaxfehler und damit ein Absturz, kein Biss).
     '            if False:\n                raise SignaturFehler("Es ist kein Key-Vault-Zugang hinterlegt.")\n'),
    ("Entfernen laesst das Secret stehen", SIG,
     '        d.pop("kv", None)\n        d["verfahren"] = VERFAHREN_PFX\n',
     '        d["verfahren"] = VERFAHREN_PFX\n'),
    ("Java-Fehler: wieder das Ende der Ausgabe", SIG,
     '            g = _java_grund(r.stderr or r.stdout or "")\n',
     '            g = (r.stderr or r.stdout or "").strip()[-400:]\n'),
    ("Speichern laedt jsign nicht", SIG,
     "    jsign_bereitstellen()\n    return zustand()\n", "    return zustand()\n"),
    ("gespeichertes Secret auch fuer eine andere Anmeldeadresse", SIG,
     '                alt.get("anmeldung", "")) != (v, t, c, a):\n',
     '                a) != (v, t, c, a):\n'),
    ("eingestellte Anmeldeadresse wird ignoriert", SIG,
     '    url = "%s/%s/oauth2/v2.0/token" % (anmeldung or AZURE_ANMELDUNG,\n',
     '    url = "%s/%s/oauth2/v2.0/token" % (AZURE_ANMELDUNG,\n'),
    ("eingestellte jsign-Quelle wird ignoriert", SIG,
     '    return str(_kv(_laden()).get("jsign_quelle") or "") or JSIGN_URL\n',
     '    return JSIGN_URL\n'),
    ("ohne Zeitstempel kein zweiter Versuch", SIG,
     "    versuche = [tsa, \"\"] if tsa else [\"\"]\n",
     "    versuche = [tsa]\n"),
]

DATEIEN = [SIG, "tests/test_ai_mouse_keyvault.py"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    py = ROOT / "venv" / "bin" / "python"
    r = subprocess.run([str(py if py.exists() else sys.executable), str(WAECHTER)],
                       capture_output=True, text=True, timeout=300, cwd=str(ROOT), env=env)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


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
                print("  BISS %-56s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-56s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-56s 0 FAIL – beisst NICHT" % name)
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
