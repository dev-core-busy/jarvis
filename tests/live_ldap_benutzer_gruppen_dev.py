#!/usr/bin/env python3
"""Live auf DEV: ``POST /api/ldap/user_groups`` gegen das ECHTE Verzeichnis.

Gemessen wird ueber KREUZ: was der neue Endpunkt als direkte Gruppe meldet,
muss die Mitgliederliste DIESER Gruppe (``/api/ldap/group_members``, eigener
Abfrageweg ueber ``(memberOf=…)``) mit dem Benutzer bestaetigen. Dazu Suche per
Mailadresse = derselbe DN, unbekannter Name = 400 mit Grund, ohne Token = 401.

⚠ DIESE PROBE AENDERT NICHTS – nur lesende Verzeichnisabfragen.
Testkonten stehen nicht im Repo: der erste Benutzer der Verzeichnissuche wird
genommen, ein weiterer kann als Argument mitgegeben werden (wird nur angezeigt).

Aufruf auf DEV (Token gilt nur mit Hauptschluessel, siehe BSI M5):
  bash /opt/jarvis/deploy/als_dienst.sh /opt/jarvis/venv/bin/python \\
       tests/live_ldap_benutzer_gruppen_dev.py [benutzer-oder-mail]
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
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

TOKEN = M.generate_token("jarvis")


def ruf(pfad, rumpf, token=TOKEN):
    r = urllib.request.Request(BASIS + pfad, data=json.dumps(rumpf).encode(), method="POST")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=60) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}
    except Exception as e:                                         # noqa: BLE001
        return 0, {"_fehler": str(e)}


# ── Positivkontrolle: die Verzeichnissuche liefert Benutzer ────────────────
s, d = ruf("/api/ldap/users", {"q": ""})
nutzer = [u for u in (d.get("users") or []) if u.get("sam")] if s == 200 else []
if not nutzer:
    print("ABBRUCH: Verzeichnissuche liefert keine Benutzer (Status %s, %s) – ohne Bestand"
          " ist jede Pruefung trivial" % (s, str(d)[:200]))
    sys.exit(2)

# Ein Benutzer MIT direkter Gruppe, sonst ist die Kreuzpruefung leer
probe = None
for u in nutzer[:25]:
    s, d = ruf("/api/ldap/user_groups", {"user": u["sam"]})
    if s == 200 and d.get("direkt"):
        probe = (u, d)
        break
if not probe:
    print("ABBRUCH: unter den ersten 25 Benutzern keiner mit direkter Gruppe – Kreuzpruefung"
          " nicht moeglich")
    sys.exit(2)
u, d = probe
print("Probe-Konto: %s (%d direkte Gruppen)" % (u["sam"], len(d["direkt"])))

print("\n1. Antwortform")
check("DN vorhanden", bool(d.get("dn")))
check("OU-Pfad ist eine Liste", isinstance((d.get("lage") or {}).get("ou"), list), d.get("lage"))
check("Domaene aus dem DN", bool((d.get("lage") or {}).get("domaene")), d.get("lage"))
check("indirekt Liste oder None", d.get("indirekt") is None or isinstance(d.get("indirekt"), list))
direkt_dns = {g["dn"].lower() for g in d["direkt"]}
check("indirekt ueberschneidet direkt nicht",
      not ({g["dn"].lower() for g in (d.get("indirekt") or [])} & direkt_dns))
check("Primaergruppe nicht unter direkt",
      not d.get("primaer") or d["primaer"]["dn"].lower() not in direkt_dns, d.get("primaer"))

print("\n2. Kreuzpruefung mit der Mitgliederliste")
g = d["direkt"][0]
s2, m = ruf("/api/ldap/group_members", {"group": g["dn"]})
check("Mitgliederliste lesbar", s2 == 200, s2)
check("Benutzer steht in der Mitgliederliste seiner direkten Gruppe",
      any((x.get("sam") or "").lower() == u["sam"].lower() for x in (m.get("members") or [])),
      "%s in %s (%d Mitglieder)" % (u["sam"], g["cn"], len(m.get("members") or [])))

print("\n3. Andere Schreibweisen und Fehler")
if u.get("mail"):
    s3, d3 = ruf("/api/ldap/user_groups", {"user": u["mail"]})
    check("Suche per Mail -> derselbe DN", s3 == 200 and d3.get("dn") == d["dn"], (s3, d3.get("error")))
else:
    print("  (Probe-Konto ohne Mail – Mail-Suche hier nicht messbar)")
s4, d4 = ruf("/api/ldap/user_groups", {"user": "gibt-es-nicht-4711"})
check("unbekannter Name -> 400 mit Grund", s4 == 400 and "nicht im Verzeichnis" in str(d4.get("error")),
      (s4, d4))
s5, _ = ruf("/api/ldap/user_groups", {"user": u["sam"]}, token=None)
check("ohne Anmeldung -> 401", s5 == 401, s5)

if len(sys.argv) > 1:
    s6, d6 = ruf("/api/ldap/user_groups", {"user": sys.argv[1]})
    print("\nAbfrage %r -> %s" % (sys.argv[1], s6))
    if s6 == 200:
        lage = d6.get("lage") or {}
        print("  Name:   %s (%s)" % (d6.get("display"), d6.get("sam")))
        print("  OU:     %s" % " > ".join([lage.get("domaene", "")] + (lage.get("ou") or [])))
        print("  DN:     %s" % d6.get("dn"))
        print("  direkt: %s" % ", ".join(x["cn"] for x in d6.get("direkt") or []) or "-")
        ind = d6.get("indirekt")
        print("  indirekt: %s" % ("nicht ermittelbar" if ind is None
                                  else ", ".join(x["cn"] for x in ind) or "-"))
        print("  primaer: %s" % ((d6.get("primaer") or {}).get("cn") or "-"))
    else:
        print("  %s" % d6)

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
