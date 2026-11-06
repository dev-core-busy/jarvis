#!/usr/bin/env python3
"""LIVE auf DEV: die Copilot-Endpunkte ueber den ECHTEN Dienst.

AUFRUF AUF DEM SERVER (Token-Ausstellung braucht den Hauptschluessel, BSI M5):

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_copilot_dev.py

NICHT per ``runuser -u jarvis`` – ohne Hauptschluessel ist das ausgestellte
Token mit dem VERPACKTEN ``.secret_key`` signiert und gilt im Dienst nicht
(401, sieht aus wie ein Rechtefehler).

WAS GEMESSEN WIRD – UND WAS AUSDRUECKLICH NICHT
-----------------------------------------------
Messbar ohne Microsoft-Mandant sind die Teile, die in unserer Hand liegen:
Rechte an den vier Endpunkten, die Freigabe-Schranke, die Auskunftsform und die
Sperre der Token-Ablage. Diese Probe laeuft deshalb IMMER.

Der Graph-Teil (Geraete-Anmeldung, echte Recherche) ist erst messbar, wenn ein
Administrator die Entra-Anwendung hinterlegt hat. Solange nicht, wird er
NAMENTLICH UEBERSPRUNGEN und am Ende als "nicht gemessen" ausgewiesen – nicht
als bestanden. "Konnte nicht laufen" muss von "bestanden" unterscheidbar sein.

⚠ SIE AENDERT KEINEN ZUSTAND. Kein Skill-Schalter, keine Freigabe, keine
Einrichtung wird angefasst, und eine Geraete-Anmeldung wird NICHT ausgeloest,
wenn die Anwendung hinterlegt ist – das waere eine echte Anmeldung am
Microsoft-Konto des Betreibers, die niemand bestellt hat.
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402  (Testkonto aus .env, nie aus dem Repo)

BASIS = "https://127.0.0.1"
_KTX = ssl._create_unverified_context()
_ok = _fail = 0
_uebersprungen: list[str] = []


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


from backend import main as M  # noqa: E402
from backend import copilot_client as CC  # noqa: E402
from backend import sandbox as SB  # noqa: E402

BENUTZER = next((u for u in (ziele.finde("JARVIS_DEV_TESTUSER") or "", "jarvis")
                 if u), "jarvis")
TOKEN = M.generate_token(BENUTZER)

# ⚠ EIN ERFUNDENES KONTO TAUGT FUER DIESE MESSUNG NICHT – erster Lauf auf DEV
# am 2026-11-06, 3 FAIL, und zwei davon waren meine Sonde:
# ``pruefkonto.ohne.internet`` hat kein Konto, also weist eine Middleware den
# Aufruf mit **403 NOT_AUTHORIZED** ab, BEVOR der Endpunkt laeuft. Die Zusage
# "device-start ohne Freigabe -> 403" war damit trivial wahr, und zwar aus dem
# falschen Grund – genau die Falle, vor der das Register warnt. Gemessen wird
# deshalb mit dem ECHTEN Testbenutzer, und welcher Zweig gilt, entscheidet
# sein VORGEFUNDENER Freigabe-Zustand; angefasst wird er nicht.
INTERNET_FREI = bool(M._user_has_internet_access(BENUTZER))

print("Benutzer: %s (Internet-Freigabe: %s)"
      % (BENUTZER, "ja" if INTERNET_FREI else "nein"))


def ruf(pfad, methode="GET", rumpf=None, token=TOKEN):
    daten = None if rumpf is None else json.dumps(rumpf).encode()
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=60) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"_fehler": str(e)}


# ─── 0. Positivkontrolle: der Dienst antwortet ueberhaupt ───────────────────
print("0. Positivkontrolle")
st, d = ruf("/api/copilot/status")
if st != 200:
    print("ABBRUCH (Exit 2): /api/copilot/status antwortet %s %r – ohne eine "
          "erreichbare Auskunft ist jede Pruefung darunter trivial wahr. "
          "Laeuft der Dienst mit diesem Stand? (jarvis-dev-reset)" % (st, d))
    sys.exit(2)
check("Status erreichbar (HTTP 200)", st == 200, "HTTP %s" % st)

# ─── 1. Die Auskunft nennt jeden Zustand, den die Oberflaeche braucht ──────
# Eine Anzeige darf keinen Zustand behaupten, den sie nicht kennt (Register) –
# deshalb reist die Freigabe mit, statt einen Knopf anzubieten, der spaeter 403
# antwortet.
print("1. Form der Auskunft")
for feld, typ in (("eingerichtet", bool), ("verbunden", bool),
                  ("konto", str), ("internet_frei", bool),
                  ("skill_aktiv", bool)):
    check("Feld %r ist vorhanden und %s" % (feld, typ.__name__),
          feld in d and isinstance(d[feld], typ),
          "ist %r" % (d.get(feld),))
print("     gemessen: eingerichtet=%r verbunden=%r internet_frei=%r "
      "skill_aktiv=%r" % (d.get("eingerichtet"), d.get("verbunden"),
                          d.get("internet_frei"), d.get("skill_aktiv")))
check("solange nicht verbunden, ist das Konto leer",
      bool(d.get("verbunden")) or d.get("konto") == "",
      "konto=%r" % d.get("konto"))

# ─── 2. Ohne Anmeldung ist nichts erreichbar ───────────────────────────────
print("2. Ohne Token")
for pfad, methode in (("/api/copilot/status", "GET"),
                      ("/api/copilot/device-start", "POST"),
                      ("/api/copilot/device-status", "GET"),
                      ("/api/copilot/connection", "DELETE")):
    st, _ = ruf(pfad, methode, token="")
    check("%s %s ohne Token -> 401" % (methode, pfad), st == 401,
          "HTTP %s" % st)

# ─── 3. Die Internet-Freigabe ist die Schranke, nicht die Oberflaeche ──────
print("3. Freigabe-Schranke am Endpunkt")
# Die Auskunft und die Freigabe-Funktion muessen UEBEREINSTIMMEN – sonst zeigt
# die Oberflaeche einen Zustand, den der Endpunkt nicht teilt.
check("die Auskunft deckt sich mit der Freigabe-Funktion",
      bool(d.get("internet_frei")) == INTERNET_FREI,
      "Auskunft=%r Funktion=%r" % (d.get("internet_frei"), INTERNET_FREI))
st, d2 = ruf("/api/copilot/device-start", "POST", {})
if not INTERNET_FREI:
    # Dieser Zweig ist die eigentliche Messung: ein ANGEMELDETER Benutzer ohne
    # Internet-Freigabe bekommt MEINEN 403 mit MEINEM Grund – nicht den der
    # Middleware (die Unterscheidung ist genau der Fehler vom ersten Lauf).
    check("device-start ohne Freigabe -> 403", st == 403, "HTTP %s %r" % (st, d2))
    check("der Grund kommt vom Endpunkt und nennt die Berechtigungen",
          "Internet-Zugriff" in str(d2.get("error") or ""),
          "%r" % d2)
    check("es ist NICHT die Middleware-Abweisung",
          d2.get("detail") != "NOT_AUTHORIZED", "%r" % d2)
else:
    # Mit Freigabe greift die naechste Schranke: ohne Entra-Anwendung 400.
    check("device-start mit Freigabe, ohne Einrichtung -> 400",
          st == 400 or bool(d.get("eingerichtet")), "HTTP %s %r" % (st, d2))

# ─── 4. Trennen ist idempotent und aendert nichts ──────────────────────────
print("4. Trennen")
# ⚠ EIN TRENNEN IST NICHT RUECKNEHMBAR – mit dem Eintrag ist das
# Refresh-Token weg, und eine Messung kann es nicht wiederherstellen. Ist der
# Benutzer verbunden, wird der Endpunkt deshalb NICHT gerufen; was ohne
# Eingriff messbar ist, wird gemessen, der Rest ausgewiesen (Register: wer
# einen loeschenden Vorgang live misst, prueft vorher, was er treffen kann).
if CC.verbunden(BENUTZER):
    _uebersprungen.append(
        "Trennen fuer %s: dieses Konto IST mit Microsoft verbunden, und ein "
        "Trennen waere nicht ruecknehmbar. Von Hand pruefbar: "
        "DELETE /api/copilot/connection" % BENUTZER)
else:
    st, d3 = ruf("/api/copilot/connection", "DELETE")
    check("DELETE connection -> 200", st == 200, "HTTP %s %r" % (st, d3))
    check("ohne Verbindung meldet es ok=false (keine Behauptung)",
          d3.get("ok") is False, "%r" % d3)
    check("der Aufruf hat nichts angelegt", not CC.verbunden(BENUTZER))

# ─── 5. Die Token-Ablage ist auf DIESEM Server gesperrt ────────────────────
# Der Unit-Waechter messt die Listen. Hier geht es um die Lage auf der Platte:
# in der Sandbox sieht ein Lauf das Dateisystem (``--dev-bind / /``), die harte
# Grenze sind die OS-Rechte.
print("5. Token-Ablage auf der Platte")
_harmlos, _, _ = SB.authorize_shell("grep -r suchbegriff data/rag")
if not _harmlos:
    print("ABBRUCH (Exit 2): authorize_shell verweigert schon eine harmlose "
          "Suche – dann sagt dieser Abschnitt nichts aus.")
    sys.exit(2)
check("eine harmlose Suche bleibt erlaubt (Positivkontrolle)", _harmlos)
for cmd in ("cat /opt/jarvis/data/copilot_auth/tokens.json",
            "cd data/copilot_auth && cat tokens.json",
            "tar czf /tmp/x.tgz data/copilot_auth"):
    erlaubt, grund, marke = SB.authorize_shell(cmd)
    check("Shell gesperrt: %s" % cmd[:52], not erlaubt, grund)
    check("Schranke benannt (%r)" % marke, bool(marke))
erlaubt, grund = SB.authorize_fs(
    "read", "/opt/jarvis/data/copilot_auth/tokens.json", username=BENUTZER)
check("Dateiwerkzeug verweigert das Lesen", not erlaubt, grund)
check("der Grund ist die Sensibilitaet, nicht der Ort",
      "Arbeitsbereich" not in grund and "Arbeitsverzeichnis" not in grund,
      "%r" % grund)

_ablage = CC._DATEI
if _ablage.exists():
    _modus = oct(_ablage.stat().st_mode & 0o777)
    check("die vorhandene Ablage steht auf 0o600 (ist %s)" % _modus,
          (_ablage.stat().st_mode & 0o777) == 0o600)
    _verz_modus = _ablage.parent.stat().st_mode & 0o777
    check("das Verzeichnis steht auf 0o750 (ist %s)" % oct(_verz_modus),
          _verz_modus == 0o750)
else:
    _uebersprungen.append(
        "Rechte der echten Ablage: data/copilot_auth/tokens.json existiert auf "
        "diesem Server noch nicht (niemand hat sein Konto verbunden)")

# ─── 6. Der Graph-Teil – nur mit hinterlegter Entra-Anwendung ──────────────
print("6. Graph-Teil")
st, d4 = ruf("/api/copilot/status")
if not d4.get("eingerichtet"):
    _uebersprungen.append(
        "Geraete-Anmeldung und echte Recherche: die Entra-Anwendung ist nicht "
        "hinterlegt (Einstellungen -> Copilot: Mandanten- und "
        "Anwendungs-Kennung). Bis dahin ist dieser Teil NICHT gemessen")
    # Messbar bleibt, dass der Endpunkt den Grund NENNT statt zu schweigen.
    st, d5 = ruf("/api/copilot/device-start", "POST", {})
    if M._user_has_internet_access(BENUTZER):
        check("device-start ohne Einrichtung -> 400", st == 400, "HTTP %s" % st)
        check("der Grund nennt die fehlende Einrichtung",
              "nicht eingerichtet" in str(d5.get("error") or "").lower()
              or d5.get("grund") == "nicht_eingerichtet",
              "%r" % d5)
    else:
        # Abschnitt 3 hat diesen Fall schon gemessen (403 mit eigenem Grund).
        # Nicht messbar ist hier nur die Reihenfolge der beiden Schranken –
        # und das ist keine Zusage, die jemand braucht.
        print("     (die 403-Schranke steht vor der Einrichtungspruefung – "
              "in Abschnitt 3 gemessen)")
else:
    # ⚠ HIER WIRD NICHTS AUSGELOEST. Eine Geraete-Anmeldung ist eine echte
    # Anmeldung am Microsoft-Konto; sie gehoert in die Hand des Betreibers.
    _uebersprungen.append(
        "Geraete-Anmeldung: die Anwendung IST hinterlegt, aber diese Probe "
        "loest keine echte Anmeldung am Microsoft-Konto aus. Von Hand: "
        "POST /api/copilot/device-start, dann den Code auf der genannten "
        "Seite eingeben und /api/copilot/device-status abfragen")
    check("Status meldet die Einrichtung", d4.get("eingerichtet") is True)
    st, d6 = ruf("/api/copilot/device-status")
    check("device-status ohne laufenden Vorgang -> 200 idle",
          st == 200 and d6.get("status") == "idle", "HTTP %s %r" % (st, d6))

# ─── Bilanz ────────────────────────────────────────────────────────────────
print("\n%d OK, %d FAIL" % (_ok, _fail))
if _uebersprungen:
    print("\nNICHT GEMESSEN (ausdruecklich, nicht bestanden):")
    for z in _uebersprungen:
        print("  - " + z)
sys.exit(1 if _fail else 0)
