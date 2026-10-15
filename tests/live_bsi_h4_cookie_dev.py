#!/usr/bin/env python3
"""Live auf DEV: BSI H4 – Sitzung im HttpOnly-Cookie, CSRF-Token im Kopfsatz.

Gefahren wird ueber den ECHTEN HTTPS-/WSS-Endpunkt des laufenden Dienstes, mit
einer frisch ausgestellten Probe-Sitzung (keine Kennwort-Anmeldung: ein
Fehlversuch zaehlt bei AD-Konten zur Sperre):

  A. POST /api/sitzung/cookie mit dem echten Token: Set-Cookie so, wie der
     Dienst es WIRKLICH ausliefert (__Host-, HttpOnly, Secure, SameSite=Strict,
     Path=/, kein Domain); im Koerper nur das CSRF-Token.
  B. /api/me: CSRF + Cookie -> angemeldet (Positivkontrolle); Cookie ohne
     CSRF, CSRF ohne Cookie, CSRF einer ANDEREN Sitzung -> 401.
  C. /ws: CSRF-Token in der Nachricht + Cookie im Handshake -> Antwort;
     ohne Cookie -> abgewiesen.
  D. POST /api/logout ueber das Cookie: Cookie wird geloescht, die Sitzung
     ist danach ungueltig.

Zustand: beide Probe-Sitzungen werden am Ende widerrufen.

Aufruf AUF DEM SERVER (Token stellt nur der Dienst mit Hauptschluessel aus):
    bash /opt/jarvis/deploy/als_dienst.sh /opt/jarvis/venv/bin/python \\
         tests/live_bsi_h4_cookie_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402  (Testkonto aus .env, nie aus dem Repo)

try:
    from websockets.sync.client import connect
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


def ruf(pfad, bearer=None, cookie=None, methode="GET"):
    r = urllib.request.Request(BASIS + pfad, method=methode,
                               data=b"" if methode == "POST" else None)
    if bearer:
        r.add_header("Authorization", "Bearer " + bearer)
    if cookie:
        r.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=60) as a:
            return a.status, a.read(), a.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


HAENGER = 0


def ws_frage(token, cookie):
    """Wie ``_ws_frage``, aber ein HAENGENDER Handshake wird bis zu dreimal
    wiederholt und gezaehlt – bekannter DEV-Nebenbefund (rund ein Viertel aller
    Handshakes, auch ohne diese Aenderung gemessen, siehe live_bsi_m4_dev.py).
    Ein Haenger ist weder Annahme noch Abweisung."""
    global HAENGER
    for _ in range(3):
        art, wert = _ws_frage(token, cookie)
        if not (art == "fehler" and "handshake" in str(wert)):
            return art, wert
        HAENGER += 1
    return art, wert


def _ws_frage(token, cookie):
    """('antwort', typ) | ('fehler', text). Fragt die Agentenliste ab – ein
    Lesevorgang ohne Wirkung."""
    kopf = {"Cookie": cookie} if cookie else {}
    try:
        with connect(WSS + "/ws", ssl=CTX, open_timeout=30, additional_headers=kopf) as ws:
            ws.send(json.dumps({"type": "get_agents", "token": token}))
            ende = time.time() + 15
            while time.time() < ende:
                m = json.loads(ws.recv(timeout=max(0.1, ende - time.time())))
                if m.get("type") in ("agent_list", "error", "session_invalid"):
                    return "antwort", m.get("type")
            return "fehler", "keine Antwort"
    except Exception as e:  # noqa: BLE001
        return "fehler", "%s: %s" % (type(e).__name__, e)


from backend import main as M  # noqa: E402
from backend import sitzung_cookie as SC  # noqa: E402

# Name in der Form, die eine AD-Anmeldung WIRKLICH ins Token schreibt
# (`domaene\\name`) – am Ausrolltag 12.10. scheiterte genau diese Form am
# Backslash im Cookie-Wert, waehrend die Probe mit dem blossen Namen gruen war.
KONTO = M._display_name(ziele.wert("JARVIS_DEV_TESTUSER"))
if "\\" not in KONTO:
    print("NICHT PRUEFBAR: kein Domaenen-Praefix (ad_domain auf DEV leer?) – %r" % KONTO)
    sys.exit(2)
TOK = M.generate_token(KONTO)
time.sleep(1.1)   # zwei Tokens derselben Sekunde sind identisch (Register)
TOK2 = M.generate_token(KONTO)
M._sitzung.flush()
if TOK == TOK2:
    print("NICHT PRUEFBAR: zwei Probe-Sitzungen sind identisch")
    sys.exit(2)

print("Live DEV: BSI H4 Cookie + CSRF (Konto %s)" % KONTO)
try:
    # ── A ──
    st, roh, kopf = ruf("/api/sitzung/cookie", TOK, methode="POST")
    if st != 200:
        print("NICHT PRUEFBAR: /api/sitzung/cookie -> %s %s" % (st, roh[:200]))
        sys.exit(2)
    csrf = json.loads(roh).get("token", "")
    sk = kopf.get_all("set-cookie") or []
    s0 = sk[0] if len(sk) == 1 else ""
    attr = [a.strip().lower() for a in s0.split(";")]
    check(csrf.startswith(SC.PRAEFIX), "(Positivkontrolle) Antwort traegt ein CSRF-Token", roh[:120])
    check(TOK not in roh.decode() and TOK.split(":")[2] not in roh.decode(),
          "Koerper enthaelt das Sitzungstoken nicht")
    check(len(sk) == 1 and s0.startswith(SC.COOKIE_NAME + "="), "genau ein Set-Cookie __Host-…", sk)
    check("httponly" in attr, "ausgeliefert: HttpOnly", s0[-120:])
    check("secure" in attr, "ausgeliefert: Secure", s0[-120:])
    check("samesite=strict" in attr, "ausgeliefert: SameSite=Strict", s0[-120:])
    check("path=/" in attr, "ausgeliefert: Path=/", s0[-120:])
    check(not any(a.startswith("domain=") for a in attr), "ausgeliefert: kein Domain", s0[-120:])
    # Den Cookie-Wert zurueckschicken, wie der Dienst ihn gesetzt hat
    cookie = s0.split(";", 1)[0]
    check(SC.cookie_aus_kopf(cookie) == TOK, "Cookie-Wert ergibt wieder das Token (AD-Name)", cookie[:80])

    # ── B ──
    st, roh, _ = ruf("/api/me", csrf, cookie)
    check(st == 200, "(Positivkontrolle) CSRF + Cookie -> /api/me 200", (st, roh[:120]))
    st, _, _ = ruf("/api/me", None, cookie)
    check(st == 401, "Cookie ohne CSRF-Kopf -> 401", st)
    st, _, _ = ruf("/api/me", csrf, None)
    check(st == 401, "CSRF ohne Cookie -> 401", st)
    st, _, _ = ruf("/api/me", SC.csrf_fuer(TOK2), cookie)
    check(st == 401, "CSRF einer anderen Sitzung -> 401", st)
    st, _, _ = ruf("/api/me", TOK2, None)
    check(st == 200, "Klartext-Bearer (Apps) weiter 200", st)

    # ── C ──
    art, wert = ws_frage(csrf, cookie)
    check((art, wert) == ("antwort", "agent_list"), "/ws: CSRF + Cookie -> Agentenliste", (art, wert))
    art, wert = ws_frage(csrf, None)
    check((art, wert) == ("antwort", "error"), "/ws: CSRF ohne Cookie -> abgewiesen", (art, wert))

    # ── D ──
    st, _, kopf = ruf("/api/logout", csrf, cookie, methode="POST")
    sk = " ".join(kopf.get_all("set-cookie") or []).lower()
    check(st == 200, "Abmelden ueber das Cookie -> 200", st)
    check(SC.COOKIE_NAME.lower() in sk and "max-age=0" in sk, "Abmelden loescht das Cookie", sk[:200])
    st, _, _ = ruf("/api/me", csrf, cookie)
    check(st == 401, "nach dem Abmelden: Sitzung ungueltig", st)
finally:
    for t in (TOK, TOK2):
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
