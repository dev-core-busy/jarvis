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

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)


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
SAP = "backend/sap_accounts.py"
VEM = "backend/vemas_accounts.py"
SICHERUNG = Path.home() / ".gegen_oidc_sicherung"

PROBEN = [
    ("alg none/HS erlaubt", MOD,
     'ALGORITHMEN = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")\n',
     'ALGORITHMEN = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "none", "HS256")\n'),
    ("Signatur nicht geprueft", MOD,
     "    if not gueltig:\n        raise OidcFehler(\"Die Signatur des id_token ist ungueltig.\")\n",
     "    if False:\n        raise OidcFehler(\"Die Signatur des id_token ist ungueltig.\")\n"),
    ("iss nicht geprueft", MOD,
     '    if not issuer_gleich(rumpf.get("iss"), issuer):\n',
     '    if False:\n'),
    ("Rechnername wieder Zeichen fuer Zeichen", MOD,
     "    return (x.hostname == y.hostname and x_port == y_port and x.path == y.path\n",
     "    return (x.netloc == y.netloc and x_port == y_port and x.path == y.path\n"),
    ("Pfad ohne Schreibweise verglichen", MOD,
     "    return (x.hostname == y.hostname and x_port == y_port and x.path == y.path\n",
     "    return (x.hostname == y.hostname and x_port == y_port and x.path.lower() == y.path.lower()\n"),
    ("Port ignoriert", MOD,
     "    return (x.hostname == y.hostname and x_port == y_port and x.path == y.path\n",
     "    return (x.hostname == y.hostname and x.path == y.path\n"),
    ("Abfrage ignoriert", MOD,
     "            and x.query == y.query and x.fragment == y.fragment)\n",
     "            and x.fragment == y.fragment)\n"),
    ("Anmeldedaten in der Adresse erlaubt", MOD,
     '    if "@" in x.netloc or "@" in y.netloc or not x.hostname:\n',
     '    if not x.hostname:\n'),
    ("http als Aussteller erlaubt", MOD,
     '    if x.scheme != "https" or y.scheme != "https":\n',
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
     "    if not _oidc.bindung_passt(_bindung_cookie, vorgang.get(\"bindung\", \"\")):\n",
     "    if False and _oidc.bindung_passt(_bindung_cookie, vorgang.get(\"bindung\", \"\")):\n"),
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
    ("Vorgabe MFA wieder aus", MAIN,
     '    return _oidc_schalter("oidc_mfa_anerkennen", True)\n',
     '    return _oidc_schalter("oidc_mfa_anerkennen", False)\n'),
    ("AD-Modus: Vorgabe wieder zusaetzlich", MAIN,
     '_OIDC_AD_MODI = ("fallback", "zusaetzlich")\n',
     '_OIDC_AD_MODI = ("zusaetzlich", "fallback")\n'),
    ("AD-Modus: unbekannter Wert uebernommen", MAIN,
     "    return v if v in _OIDC_AD_MODI else _OIDC_AD_MODI[0]\n",
     "    return v or _OIDC_AD_MODI[0]\n"),
    ("AD-Modus ungeprueft gespeichert", MAIN,
     '        if body["oidc_ad_modus"] not in _OIDC_AD_MODI:\n',
     '        if False:\n'),
    ("Status nennt Modus auch bei ausgeschaltetem IdP", MAIN,
     '        return JSONResponse({"aktiv": False})\n    antwort = {"aktiv": True, "ad_modus": _oidc_ad_modus()}\n',
     '        return JSONResponse({"aktiv": False, "ad_modus": _oidc_ad_modus()})\n    antwort = {"aktiv": True, "ad_modus": _oidc_ad_modus()}\n'),
    ("Status ohne Modus", MAIN,
     '    antwort = {"aktiv": True, "ad_modus": _oidc_ad_modus()}\n',
     '    antwort = {"aktiv": True}\n'),
    # ── Ein Servername fuer die Anmeldemaske (2026-11-19) ──
    ("Status nennt den Ursprung nicht", MAIN,
     '    if ursprung:\n        antwort["ursprung"] = ursprung\n',
     '    if False:\n        antwort["ursprung"] = ursprung\n'),
    ("Status meldet eine abgeleitete Adresse", MAIN,
     '    ursprung = _oidc_ursprung_adresse(cfg.get("redirect_uri", ""))\n',
     '    ursprung = _oidc_ursprung_adresse(cfg.get("redirect_uri", "") or "https://intern.beispiel/cb")\n'),
    ("Ursprung mit Standardport (passt nie zu location.origin)", MAIN,
     '    teil = "" if port == {"https": 443, "http": 80}[schema] else f":{port}"\n',
     '    teil = f":{port}"\n'),
    ("Vorgabe: IdP-Anmeldung an", MAIN,
     '    if not _oidc_schalter("oidc_aktiv"):\n        return None\n',
     '    if not _oidc_schalter("oidc_aktiv", True):\n        return None\n'),
    # ── Zugangsdaten aus dem IdP (2026-11-18) ──
    ("userinfo: sub nicht verglichen", MOD,
     '    if str(d.get("sub") or "") != sub:\n',
     '    if False:\n'),
    ("Zugangs-Claim mit Zeilenumbruch erlaubt", MOD,
     '                and "\\n" not in wert and "\\r" not in wert):\n',
     '                ):\n'),
    ("Zugangs-Claim ohne Laengengrenze", MOD,
     "        if (isinstance(wert, str) and wert.strip() and len(wert) <= MAX_ZUGANG_LAENGE\n",
     "        if (isinstance(wert, str) and wert.strip()\n"),
    ("userinfo auch bei Claims im id_token", MAIN,
     "    if not zug and access_token:\n",
     "    if access_token:\n"),
    ("Claim-WERTE im Protokoll", MAIN,
     '              % ", ".join(sorted(str(k)[:40] for k in claims)[:40]), flush=True)\n',
     '              % ", ".join(sorted(str(v)[:40] for v in claims.values())[:40]), flush=True)\n'),
    ("Zugangsdaten auch bei gesperrtem Account", MAIN,
     "    else:\n        # Zugangsdaten aus dem IdP: erst jetzt, wo die Anmeldung entschieden\n",
     "    if True:\n        # Zugangsdaten aus dem IdP: erst jetzt, wo die Anmeldung entschieden\n"),
    ("nicht faellige Systeme angemeldet", MAIN,
     "        offen = await asyncio.to_thread(_zugang_anmeldungen, konto)\n",
     "        offen = [{'system': s, 'art': 'token' if s in ('jira', 'confluence') else 'kennwort',"
     " 'feld': 'password'} for s in zugaenge]\n"),
    ("SAP-Claim wird nie genutzt", MAIN,
     '        kennwort("sap", sap_accounts,\n',
     '        kennwort("sap-aus", sap_accounts,\n'),
    ("gleiches Kennwort trotzdem neu geschrieben", MAIN,
     '            if not ziel.get("unveraendert"):\n',
     '            if True:\n'),
    ("Freigabe SAP/VEMAS nicht geprueft", MAIN,
     "            if not darf():\n                return None\n            ziel =",
     "            if False:\n                return None\n            ziel ="),
    ("SAP: ausgesetzter Zugang bekommt Kennwort", SAP,
     '    if k.get("ausgesetzt"):\n        return {"grund": "Zugang ausgesetzt"}\n    ct = (k.get("connection_type") or "").strip().lower()\n    if ct == "hana":\n        if not hana_erlaubt(skill_config()):\n            return {"grund": "HANA gesperrt"}\n',
     '    ct = (k.get("connection_type") or "").strip().lower()\n    if ct == "hana":\n        if not hana_erlaubt(skill_config()):\n            return {"grund": "HANA gesperrt"}\n'),
    ("SAP: Kennwort fuellt Bearer-Token", SAP,
     '        if (k.get("auth_kind") or "").strip().lower() == "bearer":\n            return {"grund": "Bearer-Anmeldung"}\n',
     ''),
    ("SAP: ohne Benutzername", SAP,
     '    if not str(benutzer or "").strip():\n        return {"grund": "kein Benutzername"}\n    if not _vollstaendig(k):\n',
     '    if not _vollstaendig(k):\n'),
    ("SAP: Server-Freigabe ignoriert", SAP,
     '    if not all(host_ok(h) for h in _hosts_im_zugang(k)):\n        return {"grund": "Server nicht freigegeben"}\n    unveraendert = False\n',
     '    unveraendert = False\n'),
    ("SAP: Kachel-Anmeldung als unveraendert", SAP,
     '    if not kachel_pflicht() and (k.get(feld + "_enc") or "").strip():\n',
     '    if (k.get(feld + "_enc") or "").strip():\n'),
    ("VEMAS: Kennwort fuellt Token", VEM,
     '    if (k.get("auth_kind") or "").strip().lower() not in ("basic", "login"):\n        return {"grund": "keine Kennwort-Anmeldung"}\n',
     ''),
    ("VEMAS: ausgesetzter Zugang bekommt Kennwort", VEM,
     '    if k.get("ausgesetzt"):\n        return {"grund": "Zugang ausgesetzt"}\n    if (k.get("auth_kind") or "").strip().lower() not in ("basic", "login"):\n',
     '    if (k.get("auth_kind") or "").strip().lower() not in ("basic", "login"):\n'),
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
