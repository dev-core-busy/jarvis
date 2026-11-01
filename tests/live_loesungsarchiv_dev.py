#!/usr/bin/env python3
"""Live auf DEV: Endpunkte des Loesungsarchivs am ECHTEN Dienst (2026-11-01).

Aufruf auf dem Server (Token braucht den Hauptschluessel, BSI M5):
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_loesungsarchiv_dev.py

Gemessen:
  * GET liefert Einstellungen, Kennzahlen und die Wissensgruppen.
  * Die Bereichsliste kommt aus dem ECHTEN Jira (Sammelzugang) – oder eine
    Meldung mit Grund, wenn Jira hier nicht eingerichtet ist (dann kein FAIL).
  * Ungueltige Eingaben werden mit 400 und Grund abgewiesen, OHNE dass sich
    Einstellung oder Auftrag aendern.
  * Speichern des VORGEFUNDENEN Stands aendert nichts (Rundreise).
  * Ohne Rechte (kein Token) gibt es nichts.

⚠ WAS DIE PROBE VERAENDERT: hoechstens die Datei ``einstellungen.json`` (mit
dem vorgefundenen Inhalt neu geschrieben). Sie stoesst KEINEN Lauf an – ein
echter Lauf kostet Modellaufrufe und schreibt in die Wissensordner; der gehoert
bewusst ausgeloest, nicht in eine Probe. Am Ende wird der vorgefundene Stand
von Einstellung UND Auftrag gegen den jetzigen geprueft.
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

BENUTZER = os.environ.get("CRON_TESTUSER") or "jarvis"
TOKEN = M.generate_token(BENUTZER)
P = "/api/jira/admin/loesungsarchiv"


def ruf(pfad, methode="GET", rumpf=None, token=True):
    daten = json.dumps(rumpf).encode() if rumpf is not None else (b"" if methode == "POST" else None)
    r = urllib.request.Request(BASIS + pfad, method=methode, data=daten)
    if token:
        r.add_header("Authorization", "Bearer " + TOKEN)
    if rumpf is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=120) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}


def auftrag():
    st, d = ruf("/api/cron")
    jobs = d if isinstance(d, list) else (d.get("jobs") or [])
    j = next((j for j in jobs if j.get("id") == "loesungsarchiv"), None)
    return st, ({k: j.get(k) for k in ("cron", "enabled", "kind")} if j else None)


# ── Positivkontrolle ───────────────────────────────────────────────────────
st, vor = ruf(P)
print("1. Lesen")
if st != 200 or not vor.get("ok"):
    print("ABBRUCH: GET %s -> %s %s (Exit 2)" % (P, st, vor))
    sys.exit(2)
check("GET liefert 200", True)
check("Einstellungen mit Schwellwert", isinstance((vor.get("einstellungen") or {}).get("schwelle"), int), vor.get("einstellungen"))
check("Wissensgruppen zur Auswahl", isinstance(vor.get("gruppen"), list), vor.get("gruppen"))
check("Kennzahlen vorhanden", all(k in vor for k in ("tickets_verarbeitet", "eintraege", "veroeffentlicht")))
st_a, auf_vor = auftrag()
check("Cron-Liste lesbar", st_a == 200, st_a)

print("2. Ohne Anmeldung")
st, _ = ruf(P, token=False)
check("ohne Token kein Zugriff", st in (401, 403), st)

print("3. Bereiche aus Jira")
st, d = ruf(P + "/bereiche")
if st == 200:
    check("Bereichsliste geladen (%d Bereiche)" % len(d.get("bereiche") or []), bool(d.get("bereiche")))
    check("jeder Bereich hat einen Schluessel", all(b.get("key") for b in d.get("bereiche") or []))
else:
    check("ohne Jira: Meldung mit Grund statt 500", st in (400, 502) and bool(d.get("error")), (st, d))

print("4. Ungueltige Eingaben")
basis = dict(vor["einstellungen"])
for name, aenderung in [("Bereich mit Anfuehrungszeichen", {"bereich": 'X" OR 1=1'}),
                        ("Schwelle 0", {"schwelle": 0}),
                        ("Cron-Ausdruck kaputt", {"cron": "jede Nacht"}),
                        ("Startdatum kaputt", {"start": "morgen"}),
                        ("Einschalten ohne Gruppe", {"aktiv": True, "gruppen": []})]:
    st, d = ruf(P, "POST", {**basis, **aenderung})
    check("%s -> 400 mit Grund" % name, st == 400 and bool(d.get("error")), (st, d))
st, nach = ruf(P)
check("Einstellungen nach Fehlversuchen unveraendert",
      nach.get("einstellungen") == vor.get("einstellungen"), (vor.get("einstellungen"), nach.get("einstellungen")))
check("Auftrag nach Fehlversuchen unveraendert", auftrag()[1] == auf_vor, (auf_vor, auftrag()[1]))

print("5. Rundreise mit dem vorgefundenen Stand")
st, d = ruf(P, "POST", basis)
check("Speichern 200", st == 200 and d.get("ok"), (st, d))
st, nach = ruf(P)
check("Einstellungen gleich", nach.get("einstellungen") == vor.get("einstellungen"),
      (vor.get("einstellungen"), nach.get("einstellungen")))
check("Auftrag gleich", auftrag()[1] == auf_vor, (auf_vor, auftrag()[1]))

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
