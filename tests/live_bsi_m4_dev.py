#!/usr/bin/env python3
"""Live auf DEV: BSI M4 – keine Sitzungstokens mehr in Adressen.

Gefahren wird ueber den ECHTEN HTTPS-/WSS-Endpunkt des laufenden Dienstes:
  A. POST /api/vnc/ticket: 2FA-Admin-Sitzung bekommt ein Ticket, eine Sitzung
     ohne 2FA nicht (BSI M3), ohne Kopfsatz 401.
  B. /ws/vnc: ein SITZUNGStoken in der Adresse wird abgewiesen; das Ticket
     oeffnet die Verbindung, und es kommt die RFB-Begruessung von x11vnc
     (Positivkontrolle: der gemeinte Weg lief bis zum Desktop); dasselbe Ticket
     ein zweites Mal wird abgewiesen.
  C. /docs: die Seite verweist auf openapi.json mit ABRUF-Schluessel, nicht mit
     dem Sitzungstoken, und dieser Verweis funktioniert.
  D. Journal seit Probenbeginn: weder Sitzungstoken noch Ticket stehen darin.

Zustand: die beiden Probe-Sitzungen werden am Ende widerrufen.

Aufruf: cd /opt/jarvis && runuser -u jarvis -- env PYTHONDONTWRITEBYTECODE=1 \
            HOME=/home/jarvis venv/bin/python tests/live_bsi_m4_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402  (Testkonto aus .env, nie aus dem Repo)

try:
    from websockets.sync.client import connect
    from websockets.exceptions import InvalidStatus
except ImportError:
    print("NICHT PRUEFBAR: websockets fehlt (venv/bin/python verwenden)")
    sys.exit(2)

BASIS = "https://127.0.0.1"
WSS = "wss://127.0.0.1"
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
        print("  FAIL %s%s" % (label, (" – %s" % str(detail)[:300]) if detail else ""))


def ruf(pfad, token=None, methode="GET"):
    r = urllib.request.Request(BASIS + pfad, method=methode, data=b"" if methode == "POST" else None)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=60) as a:
            return a.status, a.read(), dict(a.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def ws_versuch(pfad):
    """('offen', erste Nachricht) | ('abgewiesen', HTTP-Status) | ('fehler', text).

    WIEDERHOLUNG BEI HAENGENDEM HANDSHAKE (gemessen 2026-10-05, DEV): rund ein
    Viertel aller WebSocket-Handshakes kommt nie zustande – 13 von 60 auf dem
    master-Stand OHNE M4, 18 von 60 mit M4, auch am unveraenderten ``/ws`` und
    ohne jede VNC-Sitzung. Das ist ein eigener Befund, nicht Gegenstand dieser
    Probe. Ein haengender Handshake ist weder Annahme noch Abweisung; er wird
    bis zu dreimal wiederholt und gezaehlt (``HAENGER``), statt als Abweisungs-
    Fehler gemeldet zu werden."""
    global HAENGER
    for _ in range(3):
        t0 = time.time()
        art, wert = _ws_versuch(pfad)
        print("       (%s: %s, %.1f s)" % (pfad.split("?")[0], art, time.time() - t0))
        if not (art == "fehler" and "TimeoutError" in str(wert)):
            return art, wert
        HAENGER += 1
    return art, wert


HAENGER = 0


def _ws_versuch(pfad):
    try:
        with connect(WSS + pfad, ssl=CTX, open_timeout=30, subprotocols=["binary"]) as ws:
            try:
                return "offen", ws.recv(timeout=10)
            except Exception as e:  # noqa: BLE001
                return "offen", "keine Nachricht: %s" % e
    except InvalidStatus as e:
        return "abgewiesen", e.response.status_code
    except Exception as e:  # noqa: BLE001
        return "fehler", "%s: %s" % (type(e).__name__, e)


from backend import main as M  # noqa: E402

ADMIN = ziele.wert("JARVIS_DEV_TESTUSER")
START = time.strftime("%Y-%m-%d %H:%M:%S")
TOK_2FA = M.generate_token(ADMIN, mit_2fa=True)
TOK_OHNE = M.generate_token(ADMIN, mit_2fa=False)
M._sitzung.flush()
geheim = [TOK_2FA, TOK_OHNE]

print("Live DEV: BSI M4 (Konto %s)" % ADMIN)
try:
    # ── A ──
    st, roh, kopf = ruf("/api/vnc/ticket", TOK_2FA, "POST")
    if st != 200:
        print("NICHT PRUEFBAR: /api/vnc/ticket mit 2FA-Admin-Sitzung -> %s %s" % (st, roh[:200]))
        sys.exit(2)
    ticket = json.loads(roh).get("ticket", "")
    geheim.append(ticket)
    check(len(ticket) >= 40, "(Positivkontrolle) 2FA-Admin-Sitzung bekommt ein Ticket")
    check("no-store" in (kopf.get("Cache-Control") or kopf.get("cache-control") or ""),
          "Ticket-Antwort nicht cachebar")
    st, _, _ = ruf("/api/vnc/ticket", None, "POST")
    check(st == 401, "ohne Anmeldung: 401", st)
    pflicht = M._admin_2fa_pflicht()
    st, roh2, _ = ruf("/api/vnc/ticket", TOK_OHNE, "POST")
    if pflicht:
        check(st == 403, "Sitzung ohne 2FA bekommt kein Ticket (2FA-Pflicht an)", st)
    else:
        print("  --   2FA-Pflicht auf DEV aus – Fall 'ohne 2FA' nicht pruefbar")

    # ── B ──
    art, wert = ws_versuch("/ws/vnc?token=" + TOK_2FA)
    check(art == "abgewiesen", "WebSocket mit Sitzungstoken in der Adresse: abgewiesen", (art, wert))
    art, wert = ws_versuch("/ws/vnc?ticket=" + ticket)
    rfb = isinstance(wert, (bytes, bytearray)) and bytes(wert).startswith(b"RFB ")
    if art != "offen":
        print("NICHT PRUEFBAR: Ticket oeffnet den WebSocket nicht (%s, %s)" % (art, wert))
        sys.exit(2)
    check(rfb, "(Positivkontrolle) Ticket oeffnet den Desktop – RFB-Begruessung von x11vnc", wert)
    art, wert = ws_versuch("/ws/vnc?ticket=" + ticket)
    check(art == "abgewiesen", "dasselbe Ticket ein zweites Mal: abgewiesen", (art, wert))
    art, wert = ws_versuch("/ws/vnc?ticket=erfunden" + "x" * 40)
    check(art == "abgewiesen", "erfundenes Ticket: abgewiesen", (art, wert))

    # ── C ──
    st, html, _ = ruf("/docs", TOK_2FA)
    html = html.decode("utf-8", "replace")
    check(st == 200, "/docs erreichbar", st)
    check(TOK_2FA not in html, "/docs enthaelt das Sitzungstoken NICHT")
    import re
    m = re.search(r"/openapi\.json\?token=(JDL1\.[A-Za-z0-9_.\-]+)", html)
    check(bool(m), "/docs verweist mit Abruf-Schluessel auf das Schema")
    if m:
        st, roh, _ = ruf("/openapi.json?token=" + m.group(1))
        check(st == 200 and b'"openapi"' in roh, "Schema-Abruf mit dem Abruf-Schluessel funktioniert", st)
    st, html, _ = ruf("/redoc", TOK_2FA)
    check(st == 200 and TOK_2FA not in html.decode("utf-8", "replace"), "/redoc ohne Sitzungstoken", st)

    # ── D ──
    time.sleep(2)
    j = subprocess.run(["journalctl", "-u", "jarvis.service", "--since", START, "-o", "cat", "--no-pager"],
                       capture_output=True, text=True)
    # Positivkontrolle: seit BSI M8 (2026-10-12) liest der Dienstbenutzer das
    # Systemjournal nicht mehr – journalctl liefert dann Exit 0 und NICHTS, und
    # "kein Token darin" waere trivial wahr. Ohne eine einzige Zeile des Dienstes
    # ist Teil D nicht gemessen (als root ausfuehren).
    if j.returncode != 0 or not j.stdout.strip():
        print("  --   Journal nicht lesbar oder leer (%s) – Teil D NICHT gemessen; "
              "als root ausfuehren (BSI M8)" % (j.stderr.strip()[:80] or "keine Zeile"))
    else:
        sig_teile = [g.rsplit(":", 1)[-1] for g in geheim[:2]] + [ticket]
        check(not any(s and s in j.stdout for s in sig_teile),
              "Journal seit Probenbeginn: kein Token, kein Ticket")
finally:
    for t in (TOK_2FA, TOK_OHNE):
        try:
            u, ts, sig = t.split(":", 2)
            M._sitzung.widerrufe(sig, int(ts))
        except Exception as e:  # noqa: BLE001
            print("  !!   Probe-Sitzung nicht widerrufen: %s" % e)
    M._sitzung.flush()

if HAENGER:
    print("\n  Hinweis: %d haengende(r) Handshake(s) wiederholt (bekannter Nebenbefund)" % HAENGER)
print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
