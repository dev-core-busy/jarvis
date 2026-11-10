#!/usr/bin/env python3
"""Live auf DEV: aussagekraeftige Eintraege im Sicherheitsprotokoll, ueber die
ECHTEN Endpunkte des laufenden Dienstes (HTTPS, 127.0.0.1).

Gemessen wird ueber ``GET /api/security/log`` – nicht ueber ein zweites Objekt
im Probeprozess (Register). Zwei Anmeldewege je Fall:
  * Bearer-Token im Kopfsatz (Apps, Add-ins)
  * Cookie + CSRF-Token (der BROWSER). Nur hier kopiert die
    ``SitzungCookieMiddleware`` den scope – der Grund, warum die
    Protokoll-Middleware die Route selbst ermittelt.

  A. Positivkontrolle: das Konto ist Administrator (Protokoll lesbar).
  B. Abfragen erzeugen KEINE "Aenderung durch Administrator":
     POST /api/ldap/group_members (leerer Koerper -> 400, kein LDAP-Zugriff)
     und POST /api/verify-token.
  C. Eine Admin-Aktion mit Zielkonto: POST /api/admin/anmeldeschutz/aufheben
     fuer ein Konto, das es nicht gibt (-> 404, aendert nichts): Eintrag mit
     Aktion, Konto, Methode, Pfad.
  D. Eine Admin-Aktion mit Pfadparameter: DELETE /api/feedback/admin/abgaben/<id>
     fuer eine Kennung, die es nicht gibt (-> 404): Eintrag mit Aktion und Objekt.

Zustand: geaendert wird NICHTS (beide Aktionen treffen bewusst ins Leere). Die
PROTOKOLLZEILEN bleiben stehen – sie sind der Beleg (Kennung ``probesprot…``).

Aufruf auf DEV (Tokens brauchen den Hauptschluessel):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python \\
      tests/live_sprot_aussagekraft_dev.py <administrator-konto>
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid

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
        print("  FAIL %s%s" % (text, ("  [%s]" % (str(info)[:400],)) if info else ""))


def abbruch(text):
    print("ABBRUCH – %s" % text)
    sys.exit(2)


if len(sys.argv) < 2:
    abbruch("Aufruf: … live_sprot_aussagekraft_dev.py <administrator-konto>")

from backend import main as M                                      # noqa: E402
from backend import sitzung_cookie as SC                           # noqa: E402

ADMIN = sys.argv[1]
TOKEN = M.generate_token(M._display_name(ADMIN))
KOPF_BEARER = {"Authorization": "Bearer " + TOKEN}
KOPF_COOKIE = {"Authorization": "Bearer " + SC.csrf_fuer(TOKEN),
               "Cookie": "%s=%s" % (SC.COOKIE_NAME, SC.wert_kodieren(TOKEN))}
WEGE = (("Bearer", KOPF_BEARER), ("Cookie", KOPF_COOKIE))


def ruf(pfad, kopf, methode="GET", body=None):
    daten = json.dumps(body).encode() if body is not None else (b"" if methode != "GET" else None)
    r = urllib.request.Request(BASIS + pfad, method=methode, data=daten)
    for k, v in kopf.items():
        r.add_header(k, v)
    if body is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=30) as a:
            return a.status, json.loads(a.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


def eintraege(seit):
    st, d = ruf("/api/security/log?limit=400", KOPF_BEARER)
    if st != 200:
        abbruch("Protokoll nicht lesbar (HTTP %s)" % st)
    return [e for e in d.get("eintraege") or [] if int(e.get("ts") or 0) >= seit]


print("== A. Positivkontrolle")
for name, kopf in WEGE:
    st, _ = ruf("/api/security/log?limit=1", kopf)
    if st != 200:
        abbruch("'%s' ist ueber den Weg %s kein Administrator (HTTP %s)" % (ADMIN, name, st))
    check("Administrator ueber %s: Protokoll lesbar" % name, True)

START = int(time.time())
KENNUNG = "probesprot" + uuid.uuid4().hex[:8]

print("\n== B. Abfragen sind keine Aenderung")
for name, kopf in WEGE:
    st, d = ruf("/api/ldap/group_members", kopf, "POST", {})
    check("%s: Gruppenmitglieder ohne Gruppe -> 400 (Admin-Schranke passiert)" % name, st == 400, (st, d))
    st, d = ruf("/api/verify-token", kopf, "POST", {"token": kopf["Authorization"][7:]})
    check("%s: Token-Pruefung -> 200 gueltig" % name, st == 200 and d.get("valid"), (st, d))

print("\n== C. Admin-Aktion mit Zielkonto")
for name, kopf in WEGE:
    st, d = ruf("/api/admin/anmeldeschutz/aufheben", kopf, "POST", {"konto": KENNUNG + name.lower()})
    check("%s: Sperre eines unbekannten Kontos aufheben -> 404 (aendert nichts)" % name, st == 404, (st, d))

print("\n== D. Admin-Aktion mit Pfadparameter")
for name, kopf in WEGE:
    st, d = ruf("/api/feedback/admin/abgaben/%s%s" % (KENNUNG, name.lower()), kopf, "DELETE")
    check("%s: unbekannte Abgabe entfernen -> 404 (aendert nichts)" % name, st == 404, (st, d))

time.sleep(1)
neu = eintraege(START)
admin = [e for e in neu if e.get("art") == "admin_aenderung"]
pfade = [(e.get("details") or {}).get("pfad") for e in admin]

print("\n== Protokoll")
if not any(KENNUNG in json.dumps(e) for e in admin):
    abbruch("kein einziger Probe-Eintrag im Protokoll – die Messung saehe auch eine "
            "fehlende Abfrage-Zeile nicht (%d neue Eintraege)" % len(neu))
check("keine 'Aenderung durch Administrator' fuer /api/ldap/group_members",
      "/api/ldap/group_members" not in pfade, pfade)
check("keine 'Aenderung durch Administrator' fuer /api/verify-token",
      "/api/verify-token" not in pfade, pfade)
for name, _ in WEGE:
    konto = KENNUNG + name.lower()
    c = [e for e in admin if (e.get("details") or {}).get("konto") == konto]
    d = (c[0].get("details") or {}) if c else {}
    check("%s: genau ein Eintrag mit dem Zielkonto" % name, len(c) == 1, [e.get("details") for e in admin])
    check("%s: Aktion als Satz, Ergebnis 404, Beleg dabei" % name,
          d.get("aktion") == "Konto-Sperre nach Fehlversuchen vorzeitig aufheben"
          and c and c[0].get("ergebnis") == "404"
          and d.get("methode") == "POST" and d.get("pfad") == "/api/admin/anmeldeschutz/aufheben", d)
    o = [e for e in admin if (e.get("details") or {}).get("objekt") == "aid=" + konto]
    d = (o[0].get("details") or {}) if o else {}
    check("%s: Pfadparameter als Objekt, mit Aktion" % name,
          len(o) == 1 and d.get("aktion") == "Eine Abgabe entfernen", [e.get("details") for e in admin])

print("\n== Ergebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
