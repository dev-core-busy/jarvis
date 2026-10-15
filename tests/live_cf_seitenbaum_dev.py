"""Live-Probe (DEV): liefert /api/wissen/confluence/pages den Elternbezug?

Laeuft AUF DEM SERVER (sys.path /opt/jarvis) gegen den laufenden Dienst und
das ECHTE Confluence. Misst je Bereich:
  - jede Seite traegt `parent` (Text, "" = Wurzel),
  - Elternverweise zeigen auf Seiten derselben Liste (Rest = Waisen, gezaehlt),
  - mindestens EIN Bereich hat wirklich Unterseiten - sonst ist der Baum
    nicht gemessen, sondern nur flach bestaetigt (Exit 2).
Schreibt nichts. Aufruf: sudo -u jarvis python3 tests/live_cf_seitenbaum_dev.py
"""
import json
import os
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

BENUTZER = os.environ.get("CF_TESTUSER") or "jarvis"
TOKEN = M.generate_token(BENUTZER)
if not M._editable_groups_for(BENUTZER):
    print("ABBRUCH: %r hat keinen Wissensbereich (403 ueberall) – NICHT PRUEFBAR" % BENUTZER)
    sys.exit(2)


def ruf(pfad):
    r = urllib.request.Request(BASIS + pfad)
    r.add_header("Authorization", "Bearer " + TOKEN)
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=120) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


st, d = ruf("/api/wissen/confluence/spaces")
spaces = (d or {}).get("spaces") or []
if st != 200 or not spaces:
    print("ABBRUCH: keine Bereiche (HTTP %s, %s) – NICHT PRUEFBAR" % (st, (d or {}).get("error")))
    sys.exit(2)
print("Bereiche sichtbar: %d" % len(spaces))

mit_baum = 0
for sp in spaces[:int(os.environ.get("CF_MAX_SPACES") or 5)]:
    key = sp.get("key")
    st, d = ruf("/api/wissen/confluence/pages?space=" + urllib.request.quote(key))
    pages = (d or {}).get("pages") or []
    print("\n[%s] HTTP %s, %d Seiten" % (key, st, len(pages)))
    if st != 200 or not d.get("ok"):
        check("%s: Abruf ok" % key, False, (d or {}).get("error"))
        continue
    if not pages:
        continue
    ids = {str(p.get("id")) for p in pages}
    check("%s: jede Seite traegt parent als Text" % key,
          all(isinstance(p.get("parent"), str) for p in pages),
          str([p for p in pages if not isinstance(p.get("parent"), str)][:2]))
    kinder = [p for p in pages if p.get("parent")]
    waisen = [p for p in kinder if p["parent"] not in ids]
    wurzeln = [p for p in pages if not p.get("parent")]
    check("%s: keine Seite ist ihre eigene Elternseite" % key,
          not any(p.get("parent") == str(p.get("id")) for p in pages))
    print("       Wurzeln %d · Unterseiten %d · Waisen %d" % (len(wurzeln), len(kinder), len(waisen)))
    if kinder and len(waisen) < len(kinder):
        mit_baum += 1

if not mit_baum:
    print("\nABBRUCH: kein gemessener Bereich hat Unterseiten – Baum NICHT PRUEFBAR")
    sys.exit(2)
check("mindestens ein Bereich mit echter Hierarchie", mit_baum > 0)
print("\nErgebnis: %d/%d" % (_ok, _ok + _fail))
sys.exit(1 if _fail else 0)
