#!/usr/bin/env python3
"""Live auf DEV: die Wissensgruppen-Pflicht der Confluence-Einbindung.

Vorgabe 2026-09-22: „ein unter ‚dynamischer Confluence Einbindung' ausgewaehlter
Bereich muss beim Speichern mindestens einer Wissensgruppe zugeordnet werden."

⚠ SIE LEGT EINE EINBINDUNG AN – ALSO RAEUMT SIE SIE AUCH WIEDER AB, und zwar
ueber ``atexit``, nicht am Ende des Skripts: ein Wurf in der Mitte (geratene
Signatur, HTTP-Fehler) liess bei dieser Funktion schon einmal eine
Bindungs-Datei auf DEV liegen (Register 2026-09-21). Am Ende wird der
Dateiinhalt BYTE-GENAU gegen den vorgefundenen verglichen – die beiden echten
Einbindungen dieses Servers (NXDP, NXDE) sind Bestand und gehen die Messung
nichts an.

⚠ DER BENUTZER MUSS EINEN WISSENSBEREICH HABEN, sonst antwortet jeder Endpunkt
403 und jede Pruefung darunter waere trivial wahr (Register: ein Rechte-Test mit
einem nicht berechtigten Benutzer ist gruen aus dem falschen Grund). Ohne
Bereich endet die Probe mit Exit 2.
"""
import atexit
import json
import os
import ssl
import sys
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

BENUTZER = next((u for u in (os.environ.get("CFB_TESTUSER") or "",
                             "jarvis") if u), "jarvis")
TOKEN = M.generate_token(BENUTZER)
GRUPPEN = M._editable_groups_for(BENUTZER)
if not GRUPPEN:
    print("ABBRUCH: %r hat keinen Wissensbereich – jeder Endpunkt antwortet 403,\n"
          "         die Messung waere trivial wahr." % BENUTZER)
    sys.exit(2)
GID = GRUPPEN[0]["id"]
GNAME = GRUPPEN[0].get("name") or GID
print("Benutzer: %s   Wissensgruppen: %s" % (BENUTZER, ", ".join(g["id"] for g in GRUPPEN)))

ABLAGE = Path(CFB._pfad())
VORHER = ABLAGE.read_bytes() if ABLAGE.is_file() else None
print("Ablage: %s (%s Byte)" % (ABLAGE, len(VORHER) if VORHER is not None else "fehlt"))


def ruf(pfad, methode="GET", rumpf=None, token=TOKEN):
    daten = None if rumpf is None else json.dumps(rumpf).encode()
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=90) as a:
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
    """Jeden Probe-Eintrag namentlich loesen – nicht die Datei ueberschreiben:
    dazwischen kann ein Mensch gearbeitet haben."""
    for bid in list(_angelegt):
        ruf("/api/wissen/confluence/bindung/" + bid, "DELETE")
    _angelegt.clear()


atexit.register(abraeumen)

print("\n1. Zustand und Altbestand")
st, d = ruf("/api/wissen/confluence/bindung")
check("GET erreichbar", st == 200, "HTTP %s" % st)
check("Skill aktiv UND konfiguriert (sonst ist der Container ohnehin weg)",
      d.get("aktiv") is True, json.dumps({k: d.get(k) for k in ("skill_aktiv", "configured")}))
if st != 200 or not d.get("aktiv"):
    print("ABBRUCH: ohne aktive Einbindung ist nichts zu messen.")
    sys.exit(2)
bestand = d.get("bereiche") or []
print("     vorgefunden: %d Einbindung(en)" % len(bestand))
for b in bestand:
    print("       %-8s %-34s gruppen=%s info=%s"
          % (b.get("key"), str(b.get("name"))[:34], b.get("gruppen"),
             [g.get("name") for g in (b.get("gruppen_info") or [])]))
alt = [b for b in bestand if not (b.get("gruppen") or [])]
check("⚠ Altbestand ohne Zuordnung bleibt LESBAR (er wird benannt, nicht geraten)",
      all("gruppen" not in b or not b["gruppen"] for b in alt),
      "Altbestand: %d" % len(alt))
check("und er bekommt keine erfundenen Gruppennamen",
      all(not (b.get("gruppen_info") or []) for b in alt))

print("\n2. Ohne Zuordnung wird NICHT gespeichert")
st2, d2 = ruf("/api/wissen/confluence/spaces")
sichtbar = [s for s in (d2.get("spaces") or [])]
belegt = {b.get("key") for b in bestand}
frei = next((s for s in sichtbar if s.get("key") not in belegt), None)
check("sichtbare Confluence-Bereiche vorhanden (Positivkontrolle)",
      len(sichtbar) > 0, "%d" % len(sichtbar))
check("ein freier Bereich zum Messen gefunden", frei is not None)
if frei is None:
    sys.exit(2)
KEY = frei["key"]
print("     Messbereich: %s (%s)" % (KEY, frei.get("name")))

for rumpf, was in [({"key": KEY, "inkl_unter": True}, "groups fehlt ganz"),
                   ({"key": KEY, "inkl_unter": True, "groups": []}, "leere Liste"),
                   ({"key": KEY, "inkl_unter": True, "groups": ["", "  "]}, "nur Leerraum")]:
    st, d = ruf("/api/wissen/confluence/bindung", "POST", rumpf)
    check("⚠ POST abgewiesen (%s)" % was, st == 403, "HTTP %s %s" % (st, d.get("error")))
    check("   und der Grund nennt die Wissensgruppe (%s)" % was,
          "Wissensgruppe" in str(d.get("error")), str(d.get("error"))[:90])

st, d = ruf("/api/wissen/confluence/bindung", "POST",
            {"key": KEY, "inkl_unter": True, "groups": ["gibt-es-nicht"]})
check("⚠ eine fremde/unbekannte Wissensgruppe wird abgewiesen", st == 403,
      "HTTP %s %s" % (st, d.get("error")))
check("   und der Grund nennt sie beim Namen",
      "gibt-es-nicht" in str(d.get("error")), str(d.get("error"))[:90])

st, d = ruf("/api/wissen/confluence/bindung")
check("⚠ nach allen Fehlversuchen ist NICHTS dazugekommen",
      len(d.get("bereiche") or []) == len(bestand),
      "%d statt %d" % (len(d.get("bereiche") or []), len(bestand)))

print("\n3. Mit Zuordnung wird gespeichert – und sie steht in der Ablage")
st, d = ruf("/api/wissen/confluence/bindung", "POST",
            {"key": KEY, "inkl_unter": False, "groups": [GID]})
check("POST mit Wissensgruppe gelingt", st == 200, "HTTP %s %s" % (st, d.get("error")))
neu = d.get("bereich") or {}
if neu.get("id"):
    _angelegt.append(neu["id"])
check("die Antwort traegt die Zuordnung", (neu.get("gruppen") or []) == [GID],
      json.dumps(neu.get("gruppen")))
check("⚠ der Anzeigename des Bereichs kommt vom Server (nicht aus dem Rumpf)",
      (neu.get("name") or "") == (frei.get("name") or KEY), str(neu.get("name")))

roh = json.loads(ABLAGE.read_text(encoding="utf-8"))
mein = next((b for b in roh.get("bereiche", []) if b.get("id") == neu.get("id")), None)
check("⚠ die Zuordnung steht wirklich in der Ablage auf der Platte",
      mein is not None and (mein.get("gruppen") or []) == [GID],
      json.dumps(mein.get("gruppen") if mein else None))
check("die beiden Bestands-Einbindungen sind unberuehrt",
      len(roh.get("bereiche", [])) == len(bestand) + 1,
      "%d" % len(roh.get("bereiche", [])))

st, d = ruf("/api/wissen/confluence/bindung")
mein = next((b for b in (d.get("bereiche") or []) if b.get("id") == neu.get("id")), {})
check("⚠ GET liefert den ANZEIGENAMEN der Wissensgruppe mit",
      [g.get("name") for g in (mein.get("gruppen_info") or [])] == [GNAME],
      json.dumps(mein.get("gruppen_info")))
check("   samt Farbe (fuer den Chip in der Liste)",
      all("color" in g for g in (mein.get("gruppen_info") or [])))

print("\n4. Rechte")
st, _ = ruf("/api/wissen/confluence/bindung", "POST",
            {"key": KEY, "inkl_unter": True, "groups": [GID]}, token=None)
check("ohne Token 401", st == 401, "HTTP %s" % st)
st, _ = ruf("/api/wissen/confluence/bindung", "POST",
            {"key": KEY, "inkl_unter": True, "groups": [GID]}, token="muell")
check("mit Muell-Token 401", st == 401, "HTTP %s" % st)

print("\n5. Rueckweg und Ausgangszustand")
abraeumen()
st, d = ruf("/api/wissen/confluence/bindung")
check("die Probe-Einbindung ist geloest",
      len(d.get("bereiche") or []) == len(bestand),
      "%d statt %d" % (len(d.get("bereiche") or []), len(bestand)))
jetzt = ABLAGE.read_bytes() if ABLAGE.is_file() else None
check("⚠ die Ablage ist BYTE-GLEICH zum vorgefundenen Zustand", jetzt == VORHER,
      "vorher %s / jetzt %s Byte" % (len(VORHER or b""), len(jetzt or b"")))

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
