#!/usr/bin/env python3
"""Live-Abnahme auf DEV: verankert der Anker eine ECHTE Verbindung?

Als Gegenstelle dient Jarvis' EIGENER HTTPS-Port – der traegt ein selbst
ausgestelltes Zertifikat und ist damit genau der Fall, um den es geht.

**Beruehrt die Konfiguration NICHT.** ``backend.config`` wird bewusst nie
geladen (der Import migriert Profile und schreibt die Live-``settings.json``
zurueck); die Konfiguration wird als dict uebergeben.

Nach dem Lauf bleibt nur die Buendel-Datei unter ``data/sap_certs`` – der
Aufrufer raeumt sie ab.
"""
import sys
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")

import requests                                   # noqa: E402
from backend import sap_cert as sc                # noqa: E402
from backend import sap_client                    # noqa: E402

ok = fail = 0


def check(cond, label, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


HOST, PORT = "localhost", 443
URL = f"https://{HOST}:{PORT}/api/branding"       # ohne Anmeldung erreichbar

print("1. Zertifikat des eigenen HTTPS-Ports pruefen")
erg = sc.pruefen(HOST, PORT, "odata")
print(f"     Vertrauensquelle: {erg.get('system_quelle')}")
print(f"     Inhaber:      {erg.get('inhaber')}")
print(f"     Aussteller:   {erg.get('aussteller')}")
print(f"     Gueltig bis:  {erg.get('gueltig_bis')}")
print(f"     Namen:        {', '.join(erg.get('namen') or [])}")
print(f"     Fingerabdruck:{erg['fingerprint']}")
check(erg["fingerprint"].startswith("sha256:"), "Fingerabdruck ermittelt")
# WICHTIG: gemessen wird der Vertrauensspeicher, den der OData-Kanal wirklich
# benutzt (certifi ueber requests) – NICHT der Systemspeicher. Auf DEV liegt
# eine interne CA im System; der Systemspeicher wuerde hier "vertrauenswuerdig"
# melden, waehrend requests.get() weiterhin mit SSLError scheitert. Genau das
# hat der erste Live-Lauf am 2026-08-23 aufgedeckt.
check(erg["system_ok"] is False,
      "gegen die Quelle von requests: nicht bestaetigt", erg["system_grund"])
check(erg["pin_ok"] is True,
      "…der Anker WUERDE wirken (dritter Handshake)", erg["pin_grund"])
sys_sicht = sc.pruefen(HOST, PORT, "hana")
print(f"     (Systemspeicher saehe: system_ok={sys_sicht['system_ok']} – "
      f"deshalb ist die Quelle je Kanal wichtig)")

print("\n2. Verankern (Fingerabdruck bestaetigen, PEM holt der Server selbst)")
eintrag = sc.bestaetigen(HOST, PORT, erg["fingerprint"])
check(eintrag["pem"].strip() == erg["pem"].strip(), "Zertifikat selbst geholt")
try:
    sc.bestaetigen(HOST, PORT, "sha256:" + "0" * 64)
    check(False, "falscher Fingerabdruck wird abgewiesen")
except sc.ZertFehler:
    check(True, "falscher Fingerabdruck wird abgewiesen")

print("\n3. POSITIVKONTROLLE an einer ECHTEN Verbindung")
cfg_ohne = {"odata_base_url": URL, "verify_ssl": True}
cfg_mit = {"odata_base_url": URL, "verify_ssl": True, "cert_odata": eintrag}


def hol(cfg):
    v = sap_client._verify_odata(cfg, cfg["odata_base_url"])
    try:
        return requests.get(URL, verify=v, timeout=8).status_code, v
    except Exception as e:                        # noqa: BLE001
        return type(e).__name__, v


code_ohne, v_ohne = hol(cfg_ohne)
code_mit, v_mit = hol(cfg_mit)
print(f"     ohne Anker: verify={v_ohne!r} -> {code_ohne}")
print(f"     mit  Anker: verify={v_mit!r} -> {code_mit}")
check(code_ohne != 200, "OHNE Anker scheitert die Verbindung (Gegenprobe)")
check(code_mit == 200, "MIT Anker laeuft sie durch", str(code_mit))
check(isinstance(v_mit, str) and Path(v_mit).exists(), "Buendel-Datei angelegt")
check(oct(Path(v_mit).stat().st_mode & 0o777) == "0o640", "Buendel ist 0640",
      oct(Path(v_mit).stat().st_mode & 0o777))

print("\n4. Ziel-Bindung und Vorrang")
anderes = {"odata_base_url": "https://127.0.0.1:443/x", "verify_ssl": True,
           "cert_odata": eintrag}
check(sap_client._verify_odata(anderes, anderes["odata_base_url"]) is True,
      "Anker fuer 'localhost' gilt bei '127.0.0.1' nicht")
aus = {"odata_base_url": URL, "verify_ssl": False, "cert_odata": eintrag}
check(isinstance(sap_client._verify_odata(aus, URL), str),
      "Anker gewinnt gegen verify_ssl:false (strenger, nicht schwaecher)")
check(sap_client._verify_odata({"odata_base_url": URL, "verify_ssl": False}, URL)
      is False, "ohne Anker bleibt verify_ssl:false unveraendert")

print(f"\n{'=' * 56}\nErgebnis: {ok} OK, {fail} FAIL")
print("Buendel:", v_mit)
sys.exit(1 if fail else 0)
