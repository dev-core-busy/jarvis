#!/usr/bin/env python3
"""Live-Abnahme auf DEV: E-Mail-TLS gegen den ECHTEN Exchange (BSI-Abgleich, Skill email).

Gemessen wird OHNE Anmeldung: die EWS-Adresse wird anonym abgerufen – ein
Exchange antwortet darauf mit 401, und genau das ist der Beleg, dass die
TLS-Verbindung zustande kam. Ein Abruf MIT Kennwort waere ein Anmeldeversuch
und zaehlt in der Domaenen-Sperrpolitik mit (das DEV-Postfach ist ohnehin
ausgesetzt).

**Beruehrt die Konfiguration NICHT.** ``backend.config`` wird nie geladen;
``mail_tls._cfg``/``_cfg_schreiben`` werden durch dicts ersetzt, das
Anker-Buendel liegt in einem Wegwerf-Verzeichnis. Die EWS-Adresse wird aus
``data/settings.json`` nur GELESEN (keine echten Adressen im Repo).

Aufruf auf DEV:  runuser -u jarvis -- env PYTHONDONTWRITEBYTECODE=1 \\
                 /opt/jarvis/venv/bin/python tests/live_mail_tls_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests                                    # noqa: E402
from backend import mail_tls, sap_cert             # noqa: E402
from backend import mail_client as mc              # noqa: E402

if "backend.config" in sys.modules:
    print("ABBRUCH: backend.config wurde geladen")
    sys.exit(2)

ok = fail = 0


def check(cond, label, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def _email_cfg():
    s = json.loads((ROOT / "data/settings.json").read_text(encoding="utf-8"))
    stapel = [s]
    while stapel:
        o = stapel.pop()
        if isinstance(o, dict):
            e = o.get("email")
            if isinstance(e, dict) and isinstance(e.get("config"), dict):
                return e["config"]
            stapel.extend(o.values())
    return {}


EWS = mail_tls.ziele(_email_cfg()).get("ews")
if not EWS:
    print("ABBRUCH: auf diesem Server ist keine EWS-Adresse eingetragen")
    sys.exit(2)
HOST, PORT, _ = EWS
URL = mc.ews_url_normieren(_email_cfg().get("ews_url"))
if urlparse(URL).hostname != HOST:
    print("ABBRUCH: Ziel und Adresse passen nicht zusammen")
    sys.exit(2)

SAND = Path(tempfile.mkdtemp(prefix="live_mail_tls_"))
sap_cert.CERT_DIR = SAND / "certs"
_CFG = {}
_GESCHRIEBEN = []
mail_tls._cfg = lambda: dict(_CFG)
mail_tls._cfg_schreiben = lambda d: (_GESCHRIEBEN.append(dict(d)), _CFG.update(d), True)[-1]


def anonym(verify_aus=False):
    s = requests.Session()
    s.mount("https://", mc._anker_adapter_klasse()())
    if verify_aus:
        s.verify = False
    try:
        return s.get(URL, timeout=15).status_code
    except requests.exceptions.SSLError as e:
        return "SSLError: %s" % str(e)[:120]
    except requests.exceptions.RequestException as e:
        return "Netz: %s" % str(e)[:120]


try:
    print("1. Zertifikat des Exchange (Kanal EWS, Speicher wie requests)")
    erg = mail_tls.pruefen("ews", HOST, PORT)
    print(f"     Inhaber:    {erg.get('inhaber')}")
    print(f"     Aussteller: {erg.get('aussteller')}")
    print(f"     Gueltig bis:{erg.get('gueltig_bis')}")
    print(f"     system_ok={erg['system_ok']} ({erg['system_grund'] or '-'}) "
          f"pin_ok={erg['pin_ok']} ({erg['pin_grund'] or '-'})")
    check(erg["fingerprint"].startswith("sha256:"), "Fingerabdruck ermittelt")
    check(erg["system_ok"] or erg["pin_ok"],
          "entweder gilt die gewoehnliche Pruefung oder der Anker wuerde wirken")

    print("\n2. Ohne Anker (so wie nach dem Update ohne Uebernahme)")
    r0 = anonym()
    print(f"     Ergebnis: {r0}")
    if erg["system_ok"]:
        check(r0 == 401, "gewoehnliche Pruefung: anonym 401", r0)
    else:
        check(str(r0).startswith("SSLError"),
              "Positivkontrolle: ohne Anker wird der Exchange abgewiesen", r0)

    print("\n3. Einmalige Uebernahme (Bestand mit abgeschalteter Pruefung)")
    _CFG.clear()
    _CFG["tls_uebernahme_offen"] = ["ews|%s|%d" % (HOST.lower(), PORT)]
    r1 = anonym(verify_aus=True)
    print(f"     Ergebnis: {r1}")
    anker = (_CFG.get("zert_anker") or {}).get("ews") or {}
    if erg["system_ok"]:
        check(not anker and _CFG.get("tls_uebernahme_offen") == [],
              "gewoehnliche Pruefung besteht: nichts verankert, Ziel gestrichen")
    else:
        check(anker.get("fingerprint") == erg["fingerprint"] and anker.get("uebernommen"),
              "das vorgelegte Zertifikat wurde verankert")
        check(_CFG.get("tls_uebernahme_offen") == [], "das Ziel ist gestrichen (genau einmal)")
    check(r1 == 401, "anonymer EWS-Abruf ueber den Adapter: 401 (TLS geprueft und zustande)", r1)

    print("\n4. Gegenkontrolle: fremder Anker fuer dieselbe Adresse")
    fremd = mail_tls.pruefen("ews", "localhost", 443)     # eigenes DEV-Zertifikat
    _CFG.clear()
    _CFG["zert_anker"] = {"ews": dict(fremd, host=HOST, port=PORT, kanal="ews")}
    r2 = anonym(verify_aus=True)
    print(f"     Ergebnis: {r2}")
    check(str(r2).startswith("SSLError"),
          "mit fremdem Anker wird der Exchange abgewiesen (auch bei Session.verify=False)", r2)
finally:
    shutil.rmtree(SAND, ignore_errors=True)

print(f"\nErgebnis: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
