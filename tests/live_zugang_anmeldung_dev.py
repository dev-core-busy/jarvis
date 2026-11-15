"""Live-Probe (DEV, ohne bleibende Aenderung): Anmeldung fuer die Sitzung bei
Jira/Confluence und der zweite Schritt der Jarvis-Anmeldung (2026-11-15).

Geprueft am ausgerollten Dienst:
* ``GET /api/zugaenge/anmeldung``: 401 ohne Token, 200 mit, Eintraege nur mit
  Feldnamen/Benutzer (kein Geheimnis),
* ``GET /api/<system>/account`` liefert ``sitzungs_modus`` und ``angemeldet``,
* ``POST /api/<system>/account/sitzung`` mit einem absichtlich UNGUELTIGEN
  Token: 400 mit Grund, und danach ist niemand angemeldet,
* ``DELETE …/sitzung``: 200, nichts beendet.

Es entsteht kein Zustand: ein ungueltiger Token wird nie gemerkt, und ein
abgelehnter PAT sperrt kein Konto (anders als ein SAP-Kennwort – SAP/VEMAS
werden hier deshalb bewusst NICHT angemeldet).

Auf dem Server (Token braucht den Hauptschluessel, BSI M5):
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_zugang_anmeldung_dev.py
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


def ruf(pfad, token=None, methode="GET", rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    req = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if daten is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, context=_ctx, timeout=60) as a:
            return a.status, json.loads(a.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return -1, {"_fehler": str(e)}


try:
    from backend import main as M  # noqa: E402
    TOKEN = M.generate_token(PROBE_USER)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Token nicht erzeugbar: {e}")
    sys.exit(2)

st, me = ruf("/api/me", TOKEN)
if st != 200:
    print(f"ABBRUCH: /api/me antwortet {st} – Token gilt im Dienst nicht "
          "(ueber deploy/als_dienst.sh starten?)")
    sys.exit(2)
print(f"  Positivkontrolle: /api/me 200 als {me.get('username')!r}")

print("\n═══ zweiter Anmeldeschritt")
st, _ = ruf("/api/zugaenge/anmeldung")
check(st == 401, "ohne Token: 401", str(st))
st, d = ruf("/api/zugaenge/anmeldung", TOKEN)
check(st == 200 and d.get("ok") is True and isinstance(d.get("anmeldungen"), list),
      "mit Token: 200 und eine Liste", f"{st} {d}")
erlaubt = {"system", "art", "feld", "benutzer", "benutzer_feld"}
check(all(set(e) <= erlaubt for e in d.get("anmeldungen") or []),
      "Eintraege tragen nur Feldnamen und Benutzer", str(d.get("anmeldungen")))
print(f"  (angeboten fuer {PROBE_USER}: {[e.get('system') for e in d.get('anmeldungen') or []]})")

for system in ("confluence", "jira"):
    print(f"\n═══ {system}: Anmeldung fuer die Sitzung")
    st, d = ruf(f"/api/{system}/account", TOKEN)
    if st == 403:
        print(f"  (uebersprungen: {PROBE_USER} hat keine {system}-Freigabe – 403)")
        continue
    a = d.get("account") or {}
    check(st == 200 and "sitzungs_modus" in a and "angemeldet" in a,
          "Kontoansicht meldet sitzungs_modus und angemeldet", f"{st} {sorted(a)}")
    modus = a.get("sitzungs_modus")
    print(f"  (sitzungs_modus auf DEV: {modus})")
    st, d = ruf(f"/api/{system}/account/sitzung", TOKEN, "POST",
                {"api_token": "ungueltiger-probe-token"})
    grund = str(d.get("error") or "")
    check(st == 400 and grund, "ungueltiger Token: 400 mit Grund", f"{st} {grund!r}")
    if modus is False:
        check("erlaubt" in grund, "… bei erlaubten persoenlichen Zugaengen: dieser Weg ist zu", grund)
    st, d = ruf(f"/api/{system}/account", TOKEN)
    check((d.get("account") or {}).get("angemeldet") is False, "danach NICHT angemeldet")
    st, d = ruf(f"/api/{system}/account/sitzung", TOKEN, "DELETE")
    check(st == 200 and d.get("beendet") is False, "Abmelden: 200, nichts zu beenden", f"{st} {d.get('beendet')}")
    st, _ = ruf(f"/api/{system}/account/sitzung", None, "DELETE")
    check(st == 401, "Abmelden ohne Token: 401", str(st))

print(f"\n{'═' * 70}\nERGEBNIS: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
