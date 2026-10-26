#!/usr/bin/env python3
"""Live auf DEV: Reiter "Fehleranalyse" ueber den ECHTEN HTTPS-Endpunkt.

Gefahren gegen den laufenden Dienst, mit echtem Root-Broker (Journal) und dem
echten Modell im Profil des Testkontos. Ziel ist der Vorfall vom 2026-10-26
(`filesystem write` ohne `path`) – liegt er im Verlauf, muss das Dossier die
BLOCKED-Zeile aus dem Journal und die Fundstelle in `backend/sandbox.py`
enthalten. Sonst wird der juengste Lauf genommen und nur die Form geprueft.

Veraendert: schreibt je Dossier/Analyse einen Eintrag "fehleranalyse" ins
Sicherheitsprotokoll (das ist die Zusage, die hier gemessen wird).

Aufruf auf DEV (Token braucht den Hauptschluessel, BSI M5):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_fehleranalyse_dev.py
Exit 0 = gruen, 1 = Befund, 2 = nicht pruefbar.
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402  (Testkonto aus .env, nie aus dem Repo)
BASIS = "https://127.0.0.1"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def ruf(pfad, token, methode="GET", rumpf=None, timeout=60):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=timeout) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                        # noqa: BLE001
            return e.code, {}


from backend import main as M                                    # noqa: E402

ADMIN = ziele.wert("JARVIS_DEV_TESTUSER")
tok = M.generate_token(ADMIN)

print("Live DEV: Fehleranalyse")
st, d = ruf("/api/fehleranalyse/laeufe?benutzer=" + urllib.parse.quote(ADMIN), tok)
if st != 200 or not d.get("ok"):
    print(f"NICHT PRUEFBAR: /api/fehleranalyse/laeufe -> {st} {str(d)[:200]}")
    sys.exit(2)
laeufe = d.get("laeufe") or []
check(bool(laeufe), "Positivkontrolle: Laeufe des Testkontos vorhanden", str(len(laeufe)))
if not laeufe:
    sys.exit(2)
check(bool((d.get("profil") or {}).get("model")), "das Analyse-Profil des Admins ist bekannt",
      str(d.get("profil")))

# Dieselbe Aufgabe kann mehrmals gelaufen sein (am 2026-10-26 wiederholt, nach
# dem Fix erfolgreich). Der JUENGSTE Treffer ist dann gerade NICHT der Vorfall –
# die erste Fassung dieser Probe nahm ihn und meldete zwei FAILs, die es im Code
# nicht gab. Gesucht wird deshalb der Lauf, dessen Dossier die Sperre zeigt.
kandidaten = [l for l in laeufe if str(l.get("task", "")).startswith("liefere eine Befundliste")][:6]
vorfall, D, d, st = None, "", {}, 0
for l in kandidaten:
    st, d = ruf("/api/fehleranalyse/dossier", tok, "POST",
                {"id": l["id"], "beschreibung": "Live-Probe Fehleranalyse"}, timeout=120)
    if "BLOCKED filesystem" in (d.get("dossier") or ""):
        vorfall, D = l, d.get("dossier") or ""
        break
if kandidaten:
    check(vorfall is not None, "⚠ Vorfall: einer der passenden Laeufe zeigt die BLOCKED-Zeile",
          f"{len(kandidaten)} Kandidaten geprueft")
lauf = vorfall or laeufe[0]
print(f"  (Lauf {lauf.get('id')}, {'Vorfall' if vorfall else 'juengster'}: {str(lauf.get('task'))[:60]})")
if not vorfall:
    st, d = ruf("/api/fehleranalyse/dossier", tok, "POST",
                {"id": lauf["id"], "beschreibung": "Live-Probe Fehleranalyse"}, timeout=120)
    D = d.get("dossier") or ""
check(st == 200 and d.get("ok"), "Dossier: 200 und ok", f"{st} {str(d)[:200]}")
check("## Dienst-Journal" in D and "(nicht lesbar" not in D,
      "⚠ das Journal kam ueber den Root-Broker", D[D.find("## Dienst-Journal"):][:300])
check((d.get("kennzahlen") or {}).get("journal", 0) > 0, "Journalzeilen im Zeitfenster gefunden",
      str(d.get("kennzahlen")))
check("Live-Probe Fehleranalyse" in D, "die Beschreibung steht im Dossier")
if vorfall:
    check("### backend/sandbox.py:" in D, "⚠ Vorfall: die Fundstelle in sandbox.py ist gefunden",
          D[D.find("## Code-Fundstellen"):][:300])

st, s = ruf("/api/security/log?art=fehleranalyse&limit=1", tok)
e = (s.get("eintraege") or s.get("entries") or [{}])[0] if isinstance(s, dict) else {}
check(st == 200 and (e.get("details") or {}).get("lauf") == lauf["id"],
      "⚠ das Dossier steht im Sicherheitsprotokoll, mit Lauf", str(e)[:200])
check((e.get("details") or {}).get("analysiert"), "… und mit dem analysierten Benutzer")

st, a = ruf("/api/fehleranalyse/analyse", tok, "POST",
            {"id": lauf["id"], "beschreibung": "Benutzer meldet 'Zugriff verweigert' beim CSV-Export"},
            timeout=330)
check(st == 200 and a.get("ok"), "Analyse: 200 und ok", f"{st} {str(a)[:200]}")
check(a.get("analyse_ok") and len(a.get("analyse") or "") > 50,
      "das Modell hat geantwortet", a.get("analyse_fehler") or str(a.get("analyse"))[:120])
print("\n----- Antwort des Modells -----\n" + (a.get("analyse") or "")[:3000] + "\n-----")
print(f"  (Modell {a.get('modell')}, Profil {a.get('profil')}, abgeschnitten {a.get('analyse_abgeschnitten')})")

print(f"\nERGEBNIS: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
