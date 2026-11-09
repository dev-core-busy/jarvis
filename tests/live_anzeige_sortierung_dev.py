#!/usr/bin/env python3
"""Live DEV: Auswahllisten kommen alphabetisch aus dem laufenden Dienst.

Gegenstueck zu ``tests/test_anzeige_sortierung.py`` (Syntaxbaum + Modul) –
hier ueber den ECHTEN HTTP-Weg gegen die echten Bestaende. Nur lesende
Aufrufe, es wird nichts veraendert.

Positivkontrolle: die QUELLE ist wirklich unsortiert (sonst waere „die
Antwort ist sortiert" trivial wahr). Gemessen an ``conv_log.get_known_users``
desselben Datenbestands, nach derselben Namensaufbereitung.

Aufruf auf DEV (Token braucht den Hauptschluessel, BSI M5):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_anzeige_sortierung_dev.py
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")

BASIS = "https://127.0.0.1"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def ruf(pfad, token, timeout=60):
    r = urllib.request.Request(BASIS + pfad, method="GET")
    r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=timeout) as a:
            return a.status, json.loads(a.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, None


from backend import main as M                                    # noqa: E402
from backend import anzeige_sortierung as S                      # noqa: E402
from backend.conv_log import get_known_users                     # noqa: E402

# Das Testkonto, wenn es eingetragen ist – sonst das lokale Dienstkonto: die
# drei Endpunkte verlangen nur ``require_local_auth``, und gelesen wird nichts,
# was an einem Personenkonto haengt.
KONTO = (os.environ.get("JARVIS_DEV_TESTUSER") or "").strip() or "jarvis"
tok = M.generate_token(KONTO)

print("Live DEV: alphabetische Auswahllisten")
st, benutzer = ruf("/api/conv_log/users", tok)
if st != 200 or not isinstance(benutzer, list):
    print(f"NICHT PRUEFBAR: /api/conv_log/users -> {st}")
    sys.exit(2)
quelle = M._mit_anzeigenamen(get_known_users())
if len(benutzer) < 2 or quelle == S.namen_sortiert(quelle):
    print(f"NICHT PRUEFBAR: Quelle hat {len(quelle)} Eintraege und ist bereits "
          "sortiert – die Messung koennte keinen Unterschied sehen")
    sys.exit(2)
check(True, f"Positivkontrolle: Quelle unsortiert ({len(quelle)} Benutzer)")
check(benutzer == S.namen_sortiert(benutzer),
      "Fehleranalyse/Verlauf: Benutzer alphabetisch", str(benutzer[:8]))
check(set(benutzer) == set(quelle),
      "… und es fehlt keiner (gleiche Menge wie die Quelle)",
      str(set(quelle) ^ set(benutzer)))

st, ips = ruf("/api/conv_log/ips", tok)
check(st == 200 and isinstance(ips, list) and ips == S.ips_sortiert(ips),
      f"Verlauf: IP-Filter numerisch sortiert ({len(ips or [])} Adressen)", str((ips or [])[:8]))

st, d = ruf("/api/security/violations", tok)
users = (d or {}).get("users") if isinstance(d, dict) else None
check(st == 200 and isinstance(users, list) and users == S.namen_sortiert(users),
      f"Zugriffs-Verstoesse: Benutzerfilter alphabetisch ({len(users or [])})", str((users or [])[:8]))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
