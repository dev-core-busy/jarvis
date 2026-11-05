#!/usr/bin/env python3
"""Live auf DEV: Speichern mit Kachelpflicht raeumt die Kennwoerter WIRKLICH.

Durchstich ueber den ECHTEN Endpunkt des laufenden Dienstes
(``POST /api/skills/sap/config``) – nicht ueber ein zweites Objekt im
Probeprozess (Register).

⚠ DER GEMELDETE FALL (2026-11-05): der Schalter stand an, die Oberflaeche
meldete "Auf dem Server ist kein SAP-Kennwort gespeichert", und daneben stand
bei fuenf Benutzern "Kennwort noch gespeichert". Ursache war der Vergleich
``not gespeichert.get("kachel_anmeldung")`` NACH dem Speichern – ``gespeichert``
ist das lebende dict des Bestands und trug da schon den neuen Wert. Diese Probe
stellt genau diese Lage her: Schalter SCHON an, Kennwort-Rest auf der Platte.

⚠ SIE AENDERT DEN BESTAND und stellt ihn byte-genau wieder her: in die
Kontendatei wird ein erkennbarer Probe-Rest (kein echtes Geheimnis) geschrieben
und der Originalinhalt am Ende zurueckgeschrieben – auch bei Abbruch (atexit).
Der Schalter selbst wird NICHT verstellt: fehlt die Kachelpflicht, bricht die
Probe mit Exit 2 ab, statt eine Sicherheitseinstellung fuer eine Messung
umzulegen.

Aufruf auf DEV (Tokens brauchen den Hauptschluessel):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python \
      tests/live_kachel_kennwort_dev.py <admin>
"""
import atexit
import json
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
        print("  FAIL %s%s" % (text, ("  [%s]" % (info,)) if info else ""))


from backend import main as M                       # noqa: E402
from backend import sap_accounts as SA              # noqa: E402

if len(sys.argv) < 2:
    print("ABBRUCH – Aufruf: … live_kachel_kennwort_dev.py <admin>")
    sys.exit(2)
ADMIN = sys.argv[1]
TOKEN = M.generate_token(M._display_name(ADMIN))

if not SA.kachel_pflicht():
    print("ABBRUCH – 'Anmeldung ueber die Portal-Kachel' ist AUS. Die Probe legt "
          "keine Sicherheitseinstellung um; bitte den Schalter in /sap setzen.")
    sys.exit(2)

DATEI = Path(SA.KONTEN_DATEI)
if not DATEI.exists():
    print("ABBRUCH – keine Kontendatei: %s" % DATEI)
    sys.exit(2)
ORIGINAL = DATEI.read_bytes()


def _zurueck():
    if DATEI.read_bytes() != ORIGINAL:
        DATEI.write_bytes(ORIGINAL)
        print("  …   Kontendatei byte-genau zurueckgeschrieben")


atexit.register(_zurueck)

alle = json.loads(ORIGINAL.decode("utf-8"))
kandidaten = [k for k, v in alle.items() if isinstance(v, dict)]
if not kandidaten:
    print("ABBRUCH – kein persoenlicher SAP-Zugang auf diesem Server")
    sys.exit(2)
BENUTZER = kandidaten[0]

# Probe-Rest setzen: kein echtes Geheimnis, nur ein nicht-leerer Wert – genau
# darauf prueft `kennwort_gespeichert` (und die Admin-Liste in /sap).
alle[BENUTZER]["password_enc"] = "PROBE-KEIN-ECHTES-GEHEIMNIS"
VORFELDER = {f: alle[BENUTZER].get(f) for f in ("server", "username", "client", "aktiv")}
DATEI.write_text(json.dumps(alle, ensure_ascii=False, indent=2), encoding="utf-8")

print("\n1. Positivkontrolle: die Lage ist hergestellt")
if not SA.kennwort_gespeichert(BENUTZER):
    print("ABBRUCH – der Probe-Rest ist nicht sichtbar, die Messung waere trivial")
    sys.exit(2)
check("Schalter an UND ein Kennwort-Rest liegt auf der Platte", True)
vorher_cfg = dict(M._get_skill_manager().get_skill_config("sap") or {})
check("der Schalter stand VOR dem Speichern schon an (der gemeldete Fall)",
      bool(vorher_cfg.get("kachel_anmeldung")), str(vorher_cfg.get("kachel_anmeldung")))

print("\n2. Speichern ueber den echten Endpunkt")
rumpf = json.dumps({"kachel_anmeldung": True}).encode("utf-8")
anfrage = urllib.request.Request(
    BASIS + "/api/skills/sap/config", data=rumpf, method="POST",
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN})
try:
    with urllib.request.urlopen(anfrage, context=_KTX, timeout=60) as a:
        code, antwort = a.status, json.loads(a.read().decode("utf-8") or "{}")
except urllib.error.HTTPError as e:
    code, antwort = e.code, (e.read().decode("utf-8") or "")[:400]
check("der Endpunkt antwortet mit 200 und success", code == 200
      and isinstance(antwort, dict) and antwort.get("success") is True,
      "%s %s" % (code, antwort))

print("\n3. Wirkung")
check("das Kennwort des persoenlichen Zugangs ist WEG",
      not SA.kennwort_gespeichert(BENUTZER))
jetzt = json.loads(DATEI.read_text(encoding="utf-8"))
check("der Zugang selbst steht noch (Server, Benutzer, Mandant, aktiv)",
      BENUTZER in jetzt and all(jetzt[BENUTZER].get(f) == v for f, v in VORFELDER.items()),
      str({f: jetzt.get(BENUTZER, {}).get(f) for f in VORFELDER}))
check("kein Geheimfeld-Rest mehr im Datensatz",
      not [f for f in jetzt.get(BENUTZER, {}) if f.endswith("_enc")
           and str(jetzt[BENUTZER][f] or "").strip()],
      str([f for f in jetzt.get(BENUTZER, {}) if f.endswith("_enc")]))
nach_cfg = dict(M._get_skill_manager().get_skill_config("sap") or {})
check("der Schalter steht weiter an", bool(nach_cfg.get("kachel_anmeldung")))
check("kein Sammel-Geheimnis auf der Platte",
      not [f for f in SA.GEHEIMFELDER if str(nach_cfg.get(f) or "").strip()],
      str([f for f in SA.GEHEIMFELDER if str(nach_cfg.get(f) or "").strip()]))

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
