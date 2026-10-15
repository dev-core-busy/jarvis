#!/usr/bin/env python3
"""Live auf DEV: Confluence-Einbindung als Baum (Vorgabe 2026-09-27).

Misst die Endpunkte am ECHTEN Dienst gegen das ECHTE Confluence:
EIN Eintrag fuer mehrere Bereiche, Anzeigenamen vom Server, Sichtbarkeit,
Seitenkennungs-Form, Wissensgruppen-Pflicht, Bearbeiten (PUT) und Loeschen.

⚠ SIE LEGT EINTRAEGE AN – ALSO RAEUMT SIE SIE AUCH WIEDER AB, ueber ``atexit``
(ein Wurf in der Mitte liess bei dieser Funktion schon einmal eine Datei auf
DEV liegen). Am Ende wird die Ablage BYTE-GENAU gegen den vorgefundenen Stand
verglichen – die Eintraege des Betreibers gehen die Messung nichts an.

⚠ DER CRON-AUFTRAG LAEUFT PARALLEL. Die Probe startet deshalb direkt nach
einem Takt (sie wartet auf die naechste volle 5-Minuten-Marke + 20 s) und
braucht nur Sekunden – ein Probe-Eintrag soll nie in einen Abgleich geraten.

Ohne Wissensbereich des Benutzers bzw. ohne aktive Einbindung: Exit 2.
"""
import atexit
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

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
import backend.confluence_bindung as CFB                           # noqa: E402

BENUTZER = os.environ.get("CFB_TESTUSER") or "jarvis"
TOKEN = M.generate_token(BENUTZER)
GRUPPEN = M._editable_groups_for(BENUTZER)
if not GRUPPEN:
    print("ABBRUCH: %r hat keinen Wissensbereich – die Messung waere trivial wahr." % BENUTZER)
    sys.exit(2)
GID = GRUPPEN[0]["id"]
ABLAGE = Path(CFB._pfad())
VORHER = ABLAGE.read_bytes() if ABLAGE.is_file() else None


def ruf(pfad, methode="GET", rumpf=None, token=TOKEN):
    daten = None if rumpf is None else json.dumps(rumpf).encode()
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=120) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}
    except Exception as e:                                         # noqa: BLE001
        return 0, {"_fehler": str(e)}


_angelegt = []


def abraeumen():
    for bid in list(_angelegt):
        ruf("/api/wissen/confluence/bindung/" + bid, "DELETE")
    _angelegt.clear()


atexit.register(abraeumen)

# Kandidaten VOR dem Warten suchen (dauert, und soll nicht ins Fenster fallen).
st, d = ruf("/api/wissen/confluence/bindung")
if st != 200 or not d.get("aktiv"):
    print("ABBRUCH: Einbindung nicht aktiv (HTTP %s)." % st)
    sys.exit(2)
belegt = {a.get("key") for b in d.get("bereiche") or [] for a in b.get("auswahl") or []}
st2, d2 = ruf("/api/wissen/confluence/spaces")
sichtbar = [s for s in (d2.get("spaces") or []) if s.get("key") not in belegt]
print("Benutzer %s · Gruppe %s · %d sichtbare Bereiche (%d schon eingebunden)"
      % (BENUTZER, GID, len(d2.get("spaces") or []), len(belegt)))
kand = []
for s in sichtbar[:60]:
    stp, dp = ruf("/api/wissen/confluence/pages?space=" + s["key"])
    pages = dp.get("pages") or []
    kinder = [p for p in pages if p.get("parent")]
    if kinder:
        wurzel = kinder[0]["parent"]
        kand.append((s, wurzel, kinder[0]["id"], len(pages)))
    if len(kand) >= 2:
        break
if len(kand) < 2:
    print("ABBRUCH: keine zwei Bereiche mit Unterseiten gefunden – NICHT PRUEFBAR")
    sys.exit(2)
(S1, W1, K1, N1), (S2, W2, K2, N2) = kand
print("Probe-Bereiche: %s (%d Seiten, Zweig %s) und %s (%d Seiten)" % (S1["key"], N1, W1, S2["key"], N2))

# Direkt hinter einen Takt setzen.
jetzt = time.time()
ziel = (int(jetzt // 300) + 1) * 300 + 20
if ziel - jetzt > 60 and (jetzt % 300) < 250:
    ziel = jetzt              # wir sind ohnehin mitten im Fenster
print("warte %.0f s bis hinter den naechsten Takt" % max(0, ziel - jetzt))
time.sleep(max(0, ziel - time.time()))

print("\n1. Anlegen: EIN Eintrag fuer zwei Bereiche")
aw = [{"key": S1["key"], "name": "RUMPF-NAME", "seiten": [W1], "zweige": [W1]},
      {"key": S2["key"], "start": True}]
st, d = ruf("/api/wissen/confluence/bindung", "POST", {"auswahl": aw, "groups": [GID]})
check("POST 200", st == 200, "HTTP %s %s" % (st, d.get("error")))
e = d.get("bereich") or {}
if e.get("id"):
    _angelegt.append(e["id"])
awd = e.get("auswahl") or []
check("⚠ ein Eintrag, beide Bereiche", [a.get("key") for a in awd] == [S1["key"], S2["key"]])
check("⚠ der Anzeigename kommt vom Server, nicht aus dem Rumpf",
      awd and awd[0].get("name") == S1.get("name") and "RUMPF" not in json.dumps(e), json.dumps(awd)[:200])
check("der Zweig steht als Seite und als Zweig da",
      awd and awd[0].get("seiten") == [W1] and awd[0].get("zweige") == [W1])
check("die Gruppe steht dran, mit Namen", e.get("gruppen") == [GID]
      and any(g.get("id") == GID for x in d.get("bereiche") or [] if x.get("id") == e.get("id")
              for g in x.get("gruppen_info") or []))
check("von kommt aus der Anmeldung", bool(e.get("von")))

print("\n2. Abweisungen")
st, d = ruf("/api/wissen/confluence/bindung", "POST",
            {"auswahl": [{"key": "GIBTS-NICHT-" + str(int(time.time())), "start": True}], "groups": [GID]})
check("unsichtbarer Bereich -> 403", st == 403, "HTTP %s %s" % (st, d.get("error")))
st, d = ruf("/api/wissen/confluence/bindung", "POST",
            {"auswahl": [{"key": S1["key"], "seiten": ["12a"]}], "groups": [GID]})
check("Seitenkennung mit Buchstaben -> 400", st == 400, "HTTP %s %s" % (st, d.get("error")))
st, d = ruf("/api/wissen/confluence/bindung", "POST",
            {"auswahl": [{"key": S1["key"], "start": True}], "groups": ["  "]})
check("⚠ ohne Wissensgruppe -> 403 mit dem RICHTIGEN Grund",
      st == 403 and "Wissensgruppe" in (d.get("error") or ""), "HTTP %s %s" % (st, d.get("error")))
st, d = ruf("/api/wissen/confluence/bindung", "POST", {"auswahl": [], "groups": [GID]})
check("leere Auswahl -> 400", st == 400, "HTTP %s" % st)
st, d = ruf("/api/wissen/confluence/bindung", "POST",
            {"auswahl": [{"key": S1["key"], "start": True}], "groups": [GID]}, token=None)
check("ohne Token -> 401", st == 401, "HTTP %s" % st)

print("\n3. Bearbeiten")
if e.get("id"):
    st, d = ruf("/api/wissen/confluence/bindung/" + e["id"], "PUT",
                {"auswahl": [{"key": S1["key"], "seiten": [W1, K1]}], "groups": [GID]})
    g = d.get("bereich") or {}
    check("PUT 200, dieselbe Kennung", st == 200 and g.get("id") == e["id"], "HTTP %s %s" % (st, d.get("error")))
    check("⚠ Bereich entfernt, Unterbereich dazu, kein Zweig mehr",
          [(a.get("key"), a.get("seiten"), a.get("zweige")) for a in g.get("auswahl") or []]
          == [(S1["key"], [W1, K1], [])], json.dumps(g.get("auswahl"))[:200])
    check("das Anlagedatum bleibt", g.get("angelegt") == e.get("angelegt"))
    st, d = ruf("/api/wissen/confluence/bindung/" + e["id"], "PUT",
                {"auswahl": [{"key": S1["key"], "start": True}], "groups": []})
    check("PUT ohne Gruppe -> 403", st == 403, "HTTP %s" % st)
st, d = ruf("/api/wissen/confluence/bindung/gibtsnicht", "PUT",
            {"auswahl": [{"key": S1["key"], "start": True}], "groups": [GID]})
check("PUT auf unbekannten Eintrag -> 404", st == 404, "HTTP %s" % st)

print("\n4. Loeschen und Zustand")
if e.get("id"):
    st, d = ruf("/api/wissen/confluence/bindung/" + e["id"], "DELETE")
    check("DELETE 200", st == 200, "HTTP %s" % st)
    _angelegt.remove(e["id"])
    st, d = ruf("/api/wissen/confluence/bindung/" + e["id"], "DELETE")
    check("zweites DELETE -> 404", st == 404, "HTTP %s" % st)
st, d = ruf("/api/wissen/confluence/bindung")
check("die Liste traegt den Abgleichsstand (Feld vorhanden)",
      all("abgleich" in b for b in d.get("bereiche") or []))
abraeumen()
NACHHER = ABLAGE.read_bytes() if ABLAGE.is_file() else None
check("⚠ die Ablage ist BYTE-GLEICH zum vorgefundenen Stand", NACHHER == VORHER,
      "%s -> %s Byte" % (len(VORHER or b""), len(NACHHER or b"")))
mode = oct(ABLAGE.stat().st_mode & 0o777) if ABLAGE.is_file() else "-"
check("Ablage 0640", mode == "0o640", mode)

print("\nErgebnis: %d/%d" % (_ok, _ok + _fail))
sys.exit(1 if _fail else 0)
