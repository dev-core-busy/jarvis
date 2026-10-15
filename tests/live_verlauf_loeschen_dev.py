#!/usr/bin/env python3
"""Live-Probe auf DEV: einen einzelnen Verlaufseintrag ueber HTTPS loeschen.

FALLSTRICK, im ersten Lauf bezahlt: die Probe sicherte den Dateiinhalt und
stellte ihn am Ende wieder her – die Sicherung enthielt aber schon die
Rueckstaende eines vorigen, gescheiterten Laufs. "Ausgangszustand
wiederhergestellt" war damit gruen, waehrend vier Testeintraege in der
Produktionsdatei lagen. AUFGERAEUMT WIRD DESHALB GEZIELT (Testbenutzer
entfernen, "Live "-Eintraege entfernen), und vorher wird geprueft, dass gar
keine Rueckstaende da sind.

Das Sitzungstoken wird mit `main.generate_token` erzeugt – genau die Funktion,
die /api/login nach erfolgreicher Anmeldung ruft. Umgangen wird damit nichts:
der Endpunkt prueft danach Token UND Benutzer. (Grund: /api/login laeuft auf
DEV gegen PAM, das OS-Kennwort weicht von der .env ab.)
"""
import json
import sys
import urllib.request
import ssl

sys.path.insert(0, "/opt/jarvis")
import backend.main as main  # noqa: E402

BASIS = "https://127.0.0.1"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  OK   %s" % name)
    else:
        fail += 1
        print("  FAIL %s%s" % (name, (" - " + str(detail)) if detail else ""))


def ruf(pfad, token, methode="GET", rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=20) as a:
            return a.status, json.loads(a.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


# Nur der LOKALE Benutzer `jarvis` ist auf DEV anmeldeberechtigt ("leer =
# niemand" gilt fuer AD-Konten) – ein erfundener Name bekommt bei JEDEM
# Endpunkt 403 und bewiese gar nichts. Der zweite Benutzer dient nur der
# Isolationsprobe und wird auf der PLATTE geprueft, nicht ueber HTTP.
ANNA = "jarvis"
BOB = "livetest_bob"
t_anna = main.generate_token(ANNA)

HIST = main._SUPPORT_HIST_FILE


def bestand():
    return main._load_support_history()


def aufraeumen():
    """Entfernt AUSSCHLIESSLICH, was diese Probe angelegt hat."""
    d = bestand()
    d.pop(BOB, None)
    for k in list(d):
        d[k] = [e for e in d[k] if not str(e.get("query", "")).startswith("Live ")]
        if not d[k]:
            d.pop(k)
    HIST.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def rueckstaende():
    d = bestand()
    n = 1 if BOB in d else 0
    for v in d.values():
        n += sum(1 for e in v if str(e.get("query", "")).startswith("Live "))
    return n

if rueckstaende():
    print("ABBRUCH: Rueckstaende einer frueheren Probe im Verlauf – erst aufraeumen.")
    sys.exit(2)
VORHER = {k: len(v) for k, v in bestand().items()}

# Verlauf ueber die ECHTE Aufzeichnungsfunktion anlegen
for q, n in [("Live Drucker klemmt", 4), ("Live VPN geht nicht", 7), ("Live Passwort", 2)]:
    main._record_support_history(ANNA, q, n)
main._record_support_history(BOB, "Live VPN geht nicht", 3)

def live_eintraege(token):
    _, dd = ruf("/api/support/history", token)
    return [e["query"] for e in dd.get("entries", []) if str(e["query"]).startswith("Live ")]


check("Verlauf angelegt (3 Testeintraege)", live_eintraege(t_anna)
      == ["Live Passwort", "Live VPN geht nicht", "Live Drucker klemmt"],
      live_eintraege(t_anna))

s, d = ruf("/api/support/history/entry", t_anna, "DELETE", {"query": "Live VPN geht nicht"})
check("Loeschen antwortet 200/ok", s == 200 and d.get("ok") is True, (s, d))
check("genau ein Eintrag entfernt", d.get("removed") == 1, d)

qs = live_eintraege(t_anna)
check("zwei Testeintraege uebrig, der richtige ist weg",
      qs == ["Live Passwort", "Live Drucker klemmt"], qs)

check("der Verlauf von bob ist unberuehrt (auf der Platte geprueft)",
      [e["query"] for e in main._load_support_history().get(BOB, [])]
      == ["Live VPN geht nicht"], main._load_support_history().get(BOB))

# Benutzer im Rumpf darf nichts bewirken
s, d = ruf("/api/support/history/entry", t_anna, "DELETE",
           {"query": "Live VPN geht nicht", "user": BOB, "username": BOB})
check("ein 'user' im Rumpf greift nicht", d.get("removed") == 0, d)
check("...bob hat seinen Eintrag noch",
      len(main._load_support_history().get(BOB, [])) == 1,
      main._load_support_history().get(BOB))

s, d = ruf("/api/support/history/entry", t_anna, "DELETE", {"query": "  live PASSWORT "})
check("Gross/Klein und Leerraum egal", d.get("removed") == 1, d)

s, d = ruf("/api/support/history/entry", t_anna, "DELETE", {})
check("leere Anfrage -> 400", s == 400, (s, d))

s, d = ruf("/api/support/history/entry", "muell", "DELETE", {"query": "x"})
check("ohne gueltiges Token -> 401", s == 401, (s, d))

# Aufraeumen und GEGENPRUEFEN – nicht am Dateitext, sondern an dem, was da ist.
aufraeumen()
check("keine Rueckstaende der Probe mehr", rueckstaende() == 0, bestand().keys())
check("die echten Verlaeufe sind unveraendert",
      {k: len(v) for k, v in bestand().items()} == VORHER,
      {k: len(v) for k, v in bestand().items()})
s, d = ruf("/api/support/history", t_anna)
check("...auch ueber den Endpunkt gesehen",
      not any(str(e.get("query", "")).startswith("Live ") for e in d.get("entries", [])), d)

# Die Seiten liefern die neuen Bausteine aus
for pfad, marke in [("/static/js/support.js", "sup-hist-del"),
                    ("/static/js/sap_portal.js", "sp-hist-del"),
                    ("/static/js/vemas_portal.js", "vm-hist-del"),
                    ("/static/js/i18n.js", "sup.hist_del")]:
    r = urllib.request.Request(BASIS + pfad)
    with urllib.request.urlopen(r, context=CTX, timeout=20) as a:
        txt = a.read().decode("utf-8", "replace")
    check("%s enthaelt %s" % (pfad, marke), marke in txt)

print("\n%d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
