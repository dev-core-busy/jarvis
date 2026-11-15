#!/usr/bin/env python3
"""Live-Probe (DEV, NUR LESEND): "Persoenliche Zugaenge erlauben" in
Confluence, SAP, VEMAS und Jira.

Confluence/Jira: eigenes Feld ``persoenliche_zugaenge``. SAP/VEMAS: der Haken
ist die umgekehrte Kachelpflicht (``kachel_anmeldung``) – dort darf es kein
eigenes Schalterfeld in Admin-Liste und Benutzeransicht geben.

Bewusst OHNE Schreibzugriff: ein Abschalten loescht alle persoenlichen Zugaenge
auf dem Server – unwiderruflich. Das Loeschen selbst ist im Sandkasten gemessen
(test_persoenlich_schalter.py, test_skill_config_nacharbeit.py); hier wird nur
geprueft, dass der ausgerollte Dienst die neuen Felder und Endpunkte liefert
und dass Admin-Liste, Skill-Konfiguration und Benutzeransicht dieselbe Aussage
ueber den Schalter machen.

Auf dem Server (Token braucht den Hauptschluessel, BSI M5):
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_persoenlich_schalter_dev.py
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

BASIS = "https://127.0.0.1"
PROBE_USER = "jarvis"
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def holen(pfad, token=None):
    req = urllib.request.Request(BASIS + pfad)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, context=_ctx, timeout=30) as a:
            roh = a.read().decode("utf-8", "replace")
            try:
                return a.status, json.loads(roh)
            except Exception:  # noqa: BLE001
                return a.status, {"_html": roh}
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:  # noqa: BLE001
        return -1, {"_fehler": str(e)}


try:
    from backend import main as M  # noqa: E402
    TOKEN = M.generate_token(PROBE_USER)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Token nicht erzeugbar: {e}")
    sys.exit(2)

# Positivkontrolle: der Dienst nimmt das Token an (sonst waere jede Aussage leer)
st, me = holen("/api/me", TOKEN)
if st != 200:
    print(f"ABBRUCH: /api/me antwortet {st} – Token gilt im Dienst nicht "
          "(ueber deploy/als_dienst.sh starten?)")
    sys.exit(2)
check(True, "Positivkontrolle: Token gilt im Dienst")

for bereich in ("confluence", "jira"):
    print(f"\n{bereich}")
    st, d = holen(f"/api/{bereich}/admin/accounts", TOKEN)
    check(st == 200 and d.get("ok") is True, "Admin-Liste antwortet", f"{st} {str(d)[:120]}")
    erl = d.get("persoenlich_erlaubt")
    check(isinstance(erl, bool), "Admin-Liste nennt den Schalter", repr(erl))
    st, c = holen(f"/api/skills/{bereich}/config", TOKEN)
    wert = ((c or {}).get("config") or {}).get("persoenliche_zugaenge")
    check(st == 200 and wert in (None, True, False),
          "Skill-Konfiguration lesbar", f"{st} {wert!r}")
    check(erl is (wert is not False),
          "Admin-Liste und Konfiguration sagen dasselbe (Feld fehlt = erlaubt)",
          f"liste={erl!r} cfg={wert!r}")
    if not erl:
        check(d.get("accounts") == [],
              "abgeschaltet: es liegt kein persoenlicher Zugang mehr auf dem Server",
              str(d.get("accounts"))[:120])
    if bereich == "confluence":
        st, a = holen(f"/api/{bereich}/account", TOKEN)
        acc = (a or {}).get("account") or {}
        check(st in (200, 403), f"/api/{bereich}/account antwortet", str(st))
        if st == 200:
            check(acc.get("persoenlich_erlaubt") is erl,
                  "Benutzeransicht nennt denselben Schalter (Bereichsseite blendet danach aus)",
                  repr(acc.get("persoenlich_erlaubt")))

for bereich in ("sap", "vemas"):
    print(f"\n{bereich} (Haken = umgekehrte Kachelpflicht)")
    st, d = holen(f"/api/{bereich}/admin/accounts", TOKEN)
    check(st == 200 and d.get("ok") is True, "Admin-Liste antwortet", f"{st} {str(d)[:120]}")
    check("persoenlich_erlaubt" not in d, "Admin-Liste fuehrt KEIN eigenes Schalterfeld")
    st, c = holen(f"/api/skills/{bereich}/config", TOKEN)
    kachel = bool(((c or {}).get("config") or {}).get("kachel_anmeldung"))
    check(st == 200, "Skill-Konfiguration lesbar", str(st))
    check(d.get("kachel_pflicht") is kachel,
          "Admin-Liste und Konfiguration sagen dasselbe ueber die Kachelpflicht",
          f"liste={d.get('kachel_pflicht')!r} cfg={kachel!r}")
    if kachel:
        check(all(not x.get("kennwort_gespeichert") for x in d.get("accounts") or []),
              "persoenlich aus (Kachel): kein Zugang haelt ein Kennwort auf der Platte")
    st, a = holen(f"/api/{bereich}/account", TOKEN)
    acc = (a or {}).get("account") or {}
    check(st in (200, 403), f"/api/{bereich}/account antwortet", str(st))
    if st == 200:
        check("persoenlich_erlaubt" not in acc,
              "Benutzeransicht ohne Schalterfeld (\"Mein …-Zugang\" bleibt sichtbar)")

print("\nausgelieferte Seite")
st, s = holen("/settings")
html = s.get("_html", "")
for kennung in ("cf-sect-conn", "cf-sect-acc", "cf-persoenlich", "cfacc-liste",
                "sap-sect-conn", "sap-sect-acc", "sap-persoenlich",
                "vemas-sect-conn", "vemas-sect-acc", "vemas-persoenlich"):
    check(f'id="{kennung}"' in html, f"/settings enthaelt #{kennung}")
for kennung in ("sap-kachel-pflicht", "vemas-kachel-pflicht"):
    check(bool(html) and f'id="{kennung}"' not in html, f"/settings enthaelt KEIN #{kennung} mehr")

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
