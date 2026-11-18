#!/usr/bin/env python3
"""Gegenprobe zu tests/test_oidc_anmeldung.py: beisst der Waechter?

Jede Probe dreht EINE Schutzstelle zurueck (Ersetzung ganzer Zeilen), laesst
den Waechter laufen und erwartet mindestens einen FAIL (Exit 1). Vorher
gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5. Ohne
Bytecode. Ein Rueckstand aus einem abgebrochenen Lauf wird beim Start aus der
Sicherung zurueckgelegt.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_oidc_anmeldung.py"
MOD = "backend/oidc_anmeldung.py"
MAIN = "backend/main.py"
SICHERUNG = Path.home() / ".gegen_oidc_sicherung"

PROBEN = [
    ("alg none/HS erlaubt", MOD,
     'ALGORITHMEN = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")\n',
     'ALGORITHMEN = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "none", "HS256")\n'),
    ("Signatur nicht geprueft", MOD,
     "    if not gueltig:\n        raise OidcFehler(\"Die Signatur des id_token ist ungueltig.\")\n",
     "    if False:\n        raise OidcFehler(\"Die Signatur des id_token ist ungueltig.\")\n"),
    ("iss nicht geprueft", MOD,
     '    if str(rumpf.get("iss") or "") != str(issuer or ""):\n',
     '    if False:\n'),
    ("aud nicht geprueft", MOD,
     "    if not client_id or client_id not in empfaenger:\n",
     "    if not client_id:\n"),
    ("azp bei Mehrfach-aud nicht geprueft", MOD,
     '    if len(empfaenger) > 1 and rumpf.get("azp") != client_id:\n',
     '    if False:\n'),
    ("exp nicht geprueft", MOD,
     "    if t > exp + UHR_TOLERANZ_S:\n",
     "    if False:\n"),
    ("nonce nicht geprueft", MOD,
     '    if not nonce or not secrets.compare_digest(str(rumpf.get("nonce") or ""), nonce):\n',
     '    if False:\n'),
    ("fremde Domaene im Namen erlaubt", MOD,
     '        if "@" in name or dom.strip().lower() not in erlaubte_domaenen:\n',
     '        if "@" in name:\n'),
    ("leerer MFA-Nachweis nicht noetig: kaputter Nachweis gilt als belegt", MOD,
     "    if not sep or not claim or not wert:\n        return False\n",
     "    if not sep or not claim or not wert:\n        return True\n"),
    ("Ablage nicht einmalig", MOD,
     "            ein = self._d.pop(str(schluessel or \"\"), None)\n",
     "            ein = self._d.get(str(schluessel or \"\"), None)\n"),
    ("Code-Tausch folgt Weiterleitungen", MOD,
     "        with httpx.Client(verify=ctx, timeout=HTTP_FRIST_S, follow_redirects=False) as c:\n            resp = c.post(url, data=daten, headers=kopf)\n",
     "        with httpx.Client(verify=ctx, timeout=HTTP_FRIST_S, follow_redirects=True) as c:\n            resp = c.post(url, data=daten, headers=kopf)\n"),
    ("Browser-Bindung im Callback fehlt", MAIN,
     "    if not _oidc.bindung_passt(request.cookies.get(_OIDC_COOKIE_VORGANG, \"\"),\n",
     "    if False and _oidc.bindung_passt(request.cookies.get(_OIDC_COOKIE_VORGANG, \"\"),\n"),
    ("lokales Konto ueber IdP erlaubt", MAIN,
     "    if konto in {_norm_login(u) for u in ALLOWED_USERS}:\n",
     "    if konto in ALLOWED_USERS and False:\n"),
    ("Freigabe 'fehler' gilt als ja", MAIN,
     '    if freigabe == "fehler":\n        return _oidc_zurueck(request, "pruefung", konto, "Freigabe nicht pruefbar")\n'
     '    if freigabe != "ja":\n',
     '    if freigabe == "fehler":\n        pass\n'
     '    if freigabe not in ("ja", "fehler"):\n'),
    ("MFA-Schalter ignoriert (immer anerkannt)", MAIN,
     '    if _oidc_mfa_anerkennen() and schein.get("mfa_belegt"):\n',
     '    if schein.get("mfa_belegt"):\n'),
    ("Nachweis ignoriert (Schalter genuegt)", MAIN,
     '    if _oidc_mfa_anerkennen() and schein.get("mfa_belegt"):\n',
     '    if _oidc_mfa_anerkennen():\n'),
    ("Schein nicht verbraucht", MAIN,
     "    if _oidc.SCHEINE.nehmen(schein_id) is None:\n",
     "    if _oidc.SCHEINE.lesen(schein_id) is None:\n"),
    ("falscher Code ohne Fehlversuch", MAIN,
     "            if status == 401:\n                _record_login_attempt(ip, konto)\n",
     "            if False:\n                _record_login_attempt(ip, konto)\n"),
    ("Admin ohne 2FA bekommt Admin-Anzeige", MAIN,
     "    ist_admin = _is_admin_user(konto) and (mit_2fa or not _admin_2fa_pflicht())\n",
     "    ist_admin = _is_admin_user(konto)\n"),
    ("Vorgabe: IdP-Anmeldung an", MAIN,
     '    if not _oidc_schalter("oidc_aktiv"):\n        return None\n',
     '    if not _oidc_schalter("oidc_aktiv", True):\n        return None\n'),
]
DATEIEN = sorted({p[1] for p in PROBEN})


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf() -> tuple[int, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(WAECHTER)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    zeile = next((z for z in reversed(r.stdout.splitlines()) if z.startswith("Ergebnis")), "")
    return r.returncode, zeile


def zurueck() -> None:
    if not SICHERUNG.exists():
        return
    for rel in DATEIEN:
        quelle = SICHERUNG / rel
        if quelle.exists():
            shutil.copy2(quelle, ROOT / rel)
    shutil.rmtree(SICHERUNG)


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Dateiliste unvollstaendig.")
        return 2
    zurueck()  # Rueckstand eines abgebrochenen Laufs
    for name, rel, alt, neu in PROBEN:
        n = (ROOT / rel).read_text(encoding="utf-8").count(alt)
        if n != 1:
            print("ABBRUCH: Anker %dx gefunden – %s" % (n, name))
            return 2
    code, zeile = lauf()
    if code != 0:
        print("ABBRUCH: Basislauf nicht gruen (%s, Exit %d)" % (zeile, code))
        return 2
    print("Basislauf gruen: " + zeile)
    vorher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    SICHERUNG.mkdir(mode=0o700)
    for rel in DATEIEN:
        (SICHERUNG / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, SICHERUNG / rel)
    stumm = []
    try:
        for name, rel, alt, neu in PROBEN:
            pfad = ROOT / rel
            original = pfad.read_text(encoding="utf-8")
            pfad.write_text(original.replace(alt, neu), encoding="utf-8")
            try:
                code, zeile = lauf()
            finally:
                pfad.write_text(original, encoding="utf-8")
            biss = code == 1
            print("%s  %-48s %s (Exit %d)" % ("BEISST" if biss else "STUMM ", name, zeile, code))
            if not biss:
                stumm.append(name)
    finally:
        zurueck()
    nachher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    if nachher != vorher:
        print("FEHLER: Dateien nach der Gegenprobe nicht byte-gleich!")
        return 2
    print("\nDateien byte-gleich wiederhergestellt.")
    print("Bilanz: %d von %d Proben beissen" % (len(PROBEN) - len(stumm), len(PROBEN)))
    return 0 if not stumm else 1


if __name__ == "__main__":
    sys.exit(main())
