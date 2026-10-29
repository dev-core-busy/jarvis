#!/usr/bin/env python3
"""Live-Probe (nur lesend): liefert GET /api/security/unattended die Felder fuer
den Eintrag "Automatische Sicherheitsupdates" in der Auftragsliste?

Gemessen wird gegen den laufenden Dienst – also ueber den Broker (root), der
history.log und den systemd-Timer liest. Verglichen wird mit einer
UNABHAENGIGEN Lesung derselben Quellen in dieser Probe (eigener JSON-Abruf
von list-timers, eigenes Zaehlen der unattended-Bloecke), nicht mit dem
Parser selbst.

Aufruf AUF dem Server (Token braucht den Hauptschluessel, siehe CLAUDE.md):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_cron_system_dev.py <admin>
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen
"""
import json
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
BASIS = "https://127.0.0.1"
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


def ruf(pfad):
    r = urllib.request.Request(BASIS + pfad)
    r.add_header("Authorization", "Bearer " + TOKEN)
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=240) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:                                         # noqa: BLE001
        return 0, {"_fehler": str(e)}


s, d = ruf("/api/security/unattended")
if s != 200 or "enabled" not in d:
    print("ABBRUCH: Endpunkt nicht erreichbar oder ohne Zustand (HTTP %s, %s)" % (s, str(d)[:120]))
    sys.exit(2)
print("Benutzer: %s · eingeschaltet: %s · ok: %s" % (BENUTZER, d.get("enabled"), d.get("ok")))

zp = d.get("zeitplan")
check("zeitplan geliefert (Broker hat die neue Fassung)", isinstance(zp, dict), d.keys())
zp = zp or {}
roh = subprocess.run(["systemctl", "list-timers", "apt-daily-upgrade.timer", "--all", "--output=json"],
                     capture_output=True, text=True, timeout=15).stdout
eigen = next((t for t in json.loads(roh or "[]") if t.get("unit") == "apt-daily-upgrade.timer"), {})
check("letzter Lauf = eigene Lesung von systemd", eigen.get("last")
      and abs((zp.get("letzter") or 0) - eigen["last"] / 1e6) < 1, (zp.get("letzter"), eigen.get("last")))
check("naechster Lauf liegt in der Zukunft", (zp.get("naechster") or 0) > time.time(), zp.get("naechster"))
check("Ergebnis des Dienstes gelesen", zp.get("ergebnis") in ("success", "exit-code", "timeout", "signal",
                                                              "core-dump", "watchdog", "resources"), zp)

e = d.get("eingespielt")
check("eingespielt ist eine Liste (lesbar)", isinstance(e, list), type(e).__name__)
e = e or []
text = Path("/var/log/apt/history.log").read_text(errors="replace")
bloecke = text.count("Commandline: /usr/bin/unattended-upgrade")
print("  (history.log: %d unattended-Bloecke, geliefert: %d)" % (bloecke, len(e)))
check("Anzahl passt zur eigenen Zaehlung (hoechstens 20, rotierte Datei kann dazukommen)",
      len(e) >= min(bloecke, 20) and len(e) <= 20, (len(e), bloecke))
check("neueste zuerst", [x.get("start") or 0 for x in e] == sorted([x.get("start") or 0 for x in e], reverse=True))
check("jeder Eintrag hat Pakete mit Fassung", all(x.get("pakete") and all(p.get("nach") for p in x["pakete"])
                                                   for x in e), [x for x in e if not x.get("pakete")][:1])
if e:
    t = time.strftime("%d.%m. %H:%M", time.localtime(e[0]["start"]))
    print("  (zuletzt eingespielt %s: %s)" % (t, ", ".join(p["name"] for p in e[0]["pakete"])))

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
