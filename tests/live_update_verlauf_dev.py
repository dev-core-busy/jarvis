#!/usr/bin/env python3
"""Live-Probe (nur lesend): liefert GET /api/update/verlauf den Aenderungsverlauf?

Verglichen wird mit einer UNABHAENGIGEN Lesung desselben Repos in dieser Probe
(git log / rev-list direkt), nicht mit dem Parser selbst.

Aufruf AUF dem Server (Token braucht den Hauptschluessel, siehe CLAUDE.md):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_update_verlauf_dev.py <admin>
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen
"""
import json
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
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


def ruf(pfad, token=TOKEN):
    r = urllib.request.Request(BASIS + pfad)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=60) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:                                         # noqa: BLE001
        return 0, {"_fehler": str(e)}


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


s, d = ruf("/api/update/verlauf?limit=20")
if s != 200 or not d.get("ok"):
    print("ABBRUCH: Endpunkt liefert keinen Verlauf (HTTP %s, %s)" % (s, str(d)[:160]))
    sys.exit(2)
commits = d.get("commits") or []
print("Quelle: %s · %d Commits · weitere %s · web %s" % (d.get("ref"), len(commits),
                                                         d.get("weitere"), bool(d.get("web"))))

erwartet = git("log", d.get("ref") or "HEAD", "-20", "--no-merges", "--format=%H").split()
check("dieselben 20 Commits wie git log (Reihenfolge)",
      [c.get("hash_voll") for c in commits] == erwartet,
      "%d gegen %d" % (len(commits), len(erwartet)))
offen = set(git("rev-list", "--no-merges", "HEAD..%s" % (d.get("ref") or "HEAD")).split())
check("Kennzeichen 'eingespielt' stimmt je Commit",
      all(c.get("eingespielt") == (c.get("hash_voll") not in offen) for c in commits))
check("Betreff und Datum je Commit", all(c.get("message") and c.get("date") for c in commits))
check("mindestens ein Commit mit Kurzbeschreibung", any(c.get("beschreibung") for c in commits))
if d.get("web"):
    check("Web-Adresse zeigt auf github.com", d["web"].startswith("https://github.com/"), d["web"])

s2, _ = ruf("/api/update/verlauf", token="")
check("ohne Anmeldung abgewiesen", s2 in (401, 403), str(s2))

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
