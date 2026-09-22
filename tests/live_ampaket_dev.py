#!/usr/bin/env python3
"""Live: /api/ai-mouse/paket – Freigabe ODER Administrator (DEV).

Belegt die Zusage des Umbaus vom 2026-09-22: der Download liegt im
ADMIN-REITER, und `require_aimouse_access` kennt bewusst keinen Admin-Bypass –
ohne den neuen Zweig `require_aimouse_paket` waere der Knopf dort ein 403.

⚠ REIN LESEND. Es wird KEINE Freigabe umgestellt (Register: eine Messung
stellt den vorgefundenen Zustand wieder her, sie veraendert ihn nicht). Auf DEV
ist `jarvis` Administrator und NICHT AI-Maus-freigegeben – genau die Lage, die
der Zweig deckt. Ist er dort doch freigegeben, sagt die Probe es und die
Aussage waere schwaecher; sie bricht dann mit Exit 2 ab.

⚠ KEIN HEAD: der Endpunkt ist `@app.get`, Starlette beantwortet HEAD darauf
nicht (405). Beim ersten Lauf hat genau das zwei Fehlschlaege gemeldet, die es
nicht gab.
"""
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
from backend import main as M  # noqa: E402

ok = fail = 0


def check(t, b):
    global ok, fail
    print(("  OK   " if b else "  FAIL ") + t)
    if b:
        ok += 1
    else:
        fail += 1


_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def hole(pfad, token=None, grenze=None):
    r = urllib.request.Request("https://127.0.0.1" + pfad)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, context=_ctx, timeout=300) as a:
            roh = a.read(grenze) if grenze else a.read()
            return a.status, a.headers, roh
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()[:400]


print("=== /api/ai-mouse/paket: Freigabe ODER Administrator ===")
tok = M.generate_token("jarvis")

# Die LAGE zuerst – ohne sie sagt ein 200 nichts ueber den Admin-Zweig.
admin = M._is_admin_user("jarvis")
frei = M._user_may_use_aimouse("jarvis")
check("Positivkontrolle: jarvis ist Administrator", admin)
print("     (AI-Maus-Freigabe fuer jarvis: %s)" % frei)
if not admin:
    print("ABBRUCH: ohne Administratorrechte ist die Aussage nicht messbar.")
    sys.exit(2)
if frei:
    print("ABBRUCH: jarvis ist hier freigegeben – dann belegt ein 200 den")
    print("         ADMIN-Zweig nicht. Mit einem Konto ohne Freigabe messen.")
    sys.exit(2)

st, hd, roh = hole("/api/ai-mouse/paket", tok)
check("Admin OHNE Freigabe bekommt das Paket (HTTP 200)", st == 200)
check("…als ZIP", "zip" in (hd.get("Content-Type") or "").lower())
check("…mit Dateinamen im Kopf", "filename=" in (hd.get("Content-Disposition") or ""))
check("…und es ist wirklich ein ZIP (PK-Signatur, > 1 MB)",
      roh[:2] == b"PK" and len(roh) > 1_000_000)
print("     (%.1f MB, %s)" % (len(roh) / 1e6, hd.get("Content-Disposition")))

st2, _, _ = hole("/api/ai-mouse/paket")
check("ohne Token 401", st2 == 401)
st3, _, _ = hole("/api/ai-mouse/paket", "muell")
check("mit Muell-Token 401", st3 == 401)

# ⚠ GEGENRICHTUNG – sonst waere „alles auf Admin" eine triviale Loesung:
#   das Paket ist der EINZIGE Endpunkt mit Admin-Zweig, die Arbeits-Endpunkte
#   bleiben eng. Ein Administrator ohne Freigabe bekommt eine Anwendung, die
#   sich bei ihm nicht anmelden kann – das ist keine Rechteerweiterung.
st4, _, r4 = hole("/api/ai-mouse/fragen", tok)
check("fragen bleibt fuer den Admin OHNE Freigabe gesperrt (403)", st4 == 403)
check("…und nennt den Grund", b"freigeschaltet" in r4)
st5, _, _ = hole("/api/ai-mouse/health", tok)
check("health bleibt ebenfalls gesperrt (403)", st5 == 403)

print("\n%d OK, %d FAIL" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
