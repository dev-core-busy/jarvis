#!/usr/bin/env python3
"""Live-Probe: POST /api/security/unattended/jetzt spielt die Sicherheitsupdates
ueber den Broker WIRKLICH ein (manueller Lauf, Knopf mit dem Dreieck).

Schreibend: der Lauf hebt ausstehende Sicherheitspakete – nur fuer DEV gedacht.
Gemessen wird ueber den laufenden Dienst (Endpunkt -> Broker -> apt) und gegen
eine UNABHAENGIGE Quelle: das Broker-Audit muss die Op fuer diesen Aufruf
fuehren, und die Ausgabe von unattended-upgrade muss vorliegen.

Aufruf AUF dem Server (Token braucht den Hauptschluessel, siehe CLAUDE.md):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_apt_jetzt_dev.py <admin>
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen
"""
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
BASIS = "https://127.0.0.1"
AUDIT = Path("/var/log/jarvis-broker-audit.jsonl")
_KTX = ssl.create_default_context()
_KTX.check_hostname = False
_KTX.verify_mode = ssl.CERT_NONE
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

BENUTZER = sys.argv[1] if len(sys.argv) > 1 else "jarvis"
TOKEN = M.generate_token(BENUTZER)


def ruf(pfad, methode="GET", timeout=240):
    r = urllib.request.Request(BASIS + pfad, method=methode,
                               data=b"" if methode == "POST" else None)
    r.add_header("Authorization", "Bearer " + TOKEN)
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=timeout) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}
    except Exception as e:                                         # noqa: BLE001
        return 0, {"_fehler": str(e)}


# Positivkontrolle: Status lesbar, Begrenzungen wirksam (sonst lehnt der Lauf
# zu Recht ab, und die Probe maesse die Ablehnung statt des Laufs)
s, d = ruf("/api/security/unattended")
if s != 200 or "limits_ok" not in d:
    print("ABBRUCH: Status nicht lesbar (HTTP %s, %s)" % (s, str(d)[:160]))
    sys.exit(2)
if not d.get("limits_ok") or not d.get("package_installed"):
    print("ABBRUCH: Begrenzungen/Paket fehlen auf diesem System – zuerst Einschalten")
    sys.exit(2)
print("Benutzer: %s · Automatik eingeschaltet: %s" % (BENUTZER, d.get("enabled")))

try:
    audit_vorher = AUDIT.stat().st_size
except OSError:
    audit_vorher = 0
t0 = time.time()
s, d = ruf("/api/security/unattended/jetzt", "POST", timeout=2100)
dauer = time.time() - t0
print("Lauf: HTTP %s nach %.1f s" % (s, dauer))
for st in d.get("steps") or []:
    print("   %s %s %s" % ("✓" if st.get("ok") else "✗", st.get("name"),
                         ("– " + st.get("detail")) if not st.get("ok") and st.get("detail") else ""))

check("HTTP 200 und ok", s == 200 and d.get("ok") is True, "%s %s" % (s, str(d.get("error"))[:200]))
namen = [st.get("name", "") for st in d.get("steps") or []]
check("Index-Aktualisierung lief", any("Paketindex" in n for n in namen), namen)
check("unattended-upgrade lief", any("eingespielt" in n for n in namen), namen)
check("Ergebniszeile (Pakete oder 'keine ausstehenden')",
      any("aktualisiert:" in n or "Keine ausstehenden" in n for n in namen), namen)
check("Ausgabe von unattended-upgrade geliefert", bool((d.get("ausgabe") or "").strip()))
print("   Ausgabe (Ende): " + (d.get("ausgabe") or "")[-400:].replace("\n", "\n   "))
check("neuer Status mitgeliefert", isinstance(d.get("status"), dict) and "limits_ok" in d["status"])

# Das Audit gehoert root; als Dienstbenutzer ist es nicht lesbar. Dann
# ausdruecklich als UEBERSPRUNGEN melden, nicht als bestanden.
try:
    with AUDIT.open("rb") as f:
        f.seek(audit_vorher)
        neu = f.read().decode(errors="replace")
    check("Broker-Audit fuehrt apt_upgrades_jetzt", "apt_upgrades_jetzt" in neu)
except OSError as e:
    print("  UEBERSPRUNGEN Broker-Audit nicht lesbar (%s) – als root nachsehen" % e.__class__.__name__)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
