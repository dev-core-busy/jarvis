"""Live-Probe: "Verbindung testen" meldet das GEMESSENE Ziel (Art + Port).

Gemeldet von ECHT 2026-11-18: nach dem Umstellen auf LDAPS stand im Ergebnis
"erreichbar (LDAP Port 389)" – ein fester Text, verbunden wurde ueber 636.
Seitdem gibt POST /api/auth/ad_test ``ziel = {host, port, ldaps}`` aus
``ldap_tls.ziel`` zurueck, und die Oberflaeche nennt Art und Port daraus.

Gemessen ueber den echten HTTP-Weg gegen den eingetragenen Domain-Controller,
einmal ohne Schema (StartTLS) und einmal mit ``ldaps://``.

⚠ DIESE PROBE AENDERT NICHTS – ``ad_test`` speichert nichts und bindet nicht.

Aufruf auf DEV (Token gilt nur mit Hauptschluessel, siehe BSI M5):
  bash /opt/jarvis/deploy/als_dienst.sh /opt/jarvis/venv/bin/python \\
       tests/live_ad_test_ziel_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
BASIS = "https://127.0.0.1"
_KTX = ssl._create_unverified_context()
_ok = _fail = 0


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


from backend import main as M                                      # noqa: E402
from backend.config import config                                  # noqa: E402

TOKEN = M.generate_token("jarvis")


def ruf(pfad, rumpf):
    r = urllib.request.Request(BASIS + pfad, data=json.dumps(rumpf).encode(), method="POST")
    r.add_header("Authorization", "Bearer " + TOKEN)
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=60) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}
    except Exception as e:                                         # noqa: BLE001
        return 0, {"_fehler": str(e)}


roh = (config.get_setting("ad_server", "") or "").strip()
dom = (config.get_setting("ad_domain", "") or "").strip()
host = roh.split("://", 1)[-1].rstrip("/")
if ":" in host and not host.startswith("["):
    host = host.rsplit(":", 1)[0]          # eigenen Port weglassen, gemessen werden die Standards
if not host or not dom:
    print("ABBRUCH: kein Domain-Controller eingetragen – nichts zu messen")
    sys.exit(2)

# ── Positivkontrolle: der Endpunkt antwortet und der DC ist erreichbar ─────
s, d = ruf("/api/auth/ad_test", {"ad_server": host, "ad_domain": dom})
if s != 200 or not d.get("reachable"):
    print("ABBRUCH: ad_test liefert keinen erreichbaren DC (Status %s, %s)" % (s, str(d)[:200]))
    sys.exit(2)

print("\nohne Schema (StartTLS)")
z = d.get("ziel") or {}
check("Antwort traegt ziel", isinstance(d.get("ziel"), dict), str(d)[:200])
check("ziel: Port 389, ldaps=false", z.get("port") == 389 and z.get("ldaps") is False, z)
check("ziel: Host wie angefragt", str(z.get("host", "")).lower() == host.lower(), z)
print("       (tls_ok=%s%s)" % (d.get("tls_ok"), (", " + d.get("tls_error")) if d.get("tls_error") else ""))

print("\nmit ldaps://")
s, d = ruf("/api/auth/ad_test", {"ad_server": "ldaps://" + host, "ad_domain": dom})
z = d.get("ziel") or {}
check("Status 200 und erreichbar", s == 200 and d.get("reachable") is True, (s, str(d)[:200]))
check("ziel: Port 636, ldaps=true", z.get("port") == 636 and z.get("ldaps") is True, z)
check("LDAPS-Verbindung verschluesselt und geprueft (tls_ok)", d.get("tls_ok") is True, d.get("tls_error"))

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
