#!/usr/bin/env python3
"""Durchstich auf DEV: BSI H4 – Umstellung auf Cookie + CSRF im ECHTEN Browser.

Die jsdom-Probe (tests/test_bsi_h4_cookie_ui.js) laedt sitzung.js selbst und
kennt weder Cookies noch die ausgelieferten Seiten. Hier laeuft alles echt:
Chrome bekommt eine Anmeldung von VOR der Umstellung (echtes Token im
localStorage), laedt die ausgelieferten Seiten, und gemessen wird

  A. die Umstellung greift: im Speicher steht danach nur noch das CSRF-Token,
     kein Schluessel traegt mehr ein echtes Token;
  B. das Cookie, wie Chrome es WIRKLICH haelt: HttpOnly, Secure,
     SameSite=Strict, Wert = Sitzungstoken; fuer Skripte unsichtbar
     (document.cookie);
  C. je Bereichsseite (alle mit eigener Route): die EIGENEN Anfragen der
     Seite bekommen kein 401, /api/me ueber JarvisSitzung antwortet 200
     (Positivkontrolle), und im Chat meldet der WebSocket keine ungueltige
     Sitzung.

Laeuft AUF DEV ueber den Hauptschluessel (das Token stellt nur der Dienst aus):
    bash /opt/jarvis/deploy/als_dienst.sh /opt/jarvis/venv/bin/python \\
         tests/live_bsi_h4_cookie_ui_dev.py
Zustand: die Probe-Sitzung wird am Ende widerrufen, das Chrome-Profil geloescht.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402
from backend import main as M  # noqa: E402
from backend import sitzung_cookie as SC  # noqa: E402

# AD-Form `domaene\\name`, wie sie eine echte Anmeldung ins Token schreibt
# (Ausrolltag 12.10.: der Backslash im Cookie-Wert brach jede Anmeldung)
BENUTZER = M._display_name(ziele.wert("JARVIS_DEV_TESTUSER"))
if "\\" not in BENUTZER:
    print("NICHT PRUEFBAR: kein Domaenen-Praefix – %r" % BENUTZER)
    sys.exit(2)
TOKEN = M.generate_token(BENUTZER)
M._sitzung.flush()
# Alle Bereichsseiten mit eigener Route. Eine Seite, fuer die das Konto keine
# Freigabe hat, leitet weiter oder antwortet 403 – beides ist kein 401 und
# stoert die Messung nicht; gemessen wird die ANMELDUNG, nicht die Freigabe.
SEITEN = ["/portal", "/settings", "/chat", "/wissen", "/userchat", "/support",
          "/supportagent", "/email", "/sap", "/vemas", "/tracks", "/excel", "/api",
          "/claude", "/feedback", "/ai-mouse"]

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % str(info)[:300]) if info else ""))


PROFIL = tempfile.mkdtemp(prefix="chrome-h4-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1200,900", "--ignore-certificate-errors",
     "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def aufraeumen():
    try:
        chrome.kill()
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(PROFIL, ignore_errors=True)
    try:
        u, ts, sig = TOKEN.split(":", 2)
        M._sitzung.widerrufe(sig, int(ts))
        M._sitzung.flush()
    except Exception as e:  # noqa: BLE001
        print("  !!   Probe-Sitzung nicht widerrufen: %s" % e)


def cdp_ziel():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as a:
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


ws_url = cdp_ziel()
if not ws_url:
    print("ABBRUCH: kein CDP-Ziel")
    print(chrome.stdout.read(2000) if chrome.poll() is not None else "")
    aufraeumen()
    sys.exit(2)
from websockets.sync.client import connect  # noqa: E402

_id = [0]
EREIGNISSE = []


def cdp(sock, methode, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": methode, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=60))
        if d.get("id") == _id[0]:
            return d.get("result", {})
        if "method" in d:
            EREIGNISSE.append(d)


def pumpen(sock, sekunden):
    ende = time.time() + sekunden
    while time.time() < ende:
        try:
            d = json.loads(sock.recv(timeout=max(0.05, ende - time.time())))
        except TimeoutError:
            break
        if "method" in d:
            EREIGNISSE.append(d)


def js(sock, ausdruck):
    r = cdp(sock, "Runtime.evaluate", expression=ausdruck, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def warte(sock, ausdruck, frist):
    ende = time.time() + frist
    while time.time() < ende:
        if js(sock, ausdruck):
            return True
        pumpen(sock, 0.5)
    return False


def abmeldungen():
    """Jede /api/logout-Anfrage seit dem letzten Leeren, mit Aufrufer (CDP-Initiator)."""
    aus = []
    for e in EREIGNISSE:
        if e.get("method") != "Network.requestWillBeSent":
            continue
        p = e["params"]
        if "/api/logout" not in p.get("request", {}).get("url", ""):
            continue
        st = (p.get("initiator") or {}).get("stack") or {}
        rahmen = []
        while st:
            rahmen += ["%s@%s:%s" % (f.get("functionName") or "?", f.get("url", "").rsplit("/", 1)[-1],
                                      f.get("lineNumber")) for f in st.get("callFrames", [])]
            st = st.get("parent")
        aus.append({"seite": p.get("documentURL", ""), "stapel": rahmen[:8]})
    return aus


SPEICHER = ("(function(){var o={};['jarvis_token','jarvis_chat_token','jarvis_uc_token']"
            ".forEach(function(k){o[k]=localStorage.getItem(k);});return o;})()")

rc = 2
try:
    with connect(ws_url, max_size=80 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        cdp(sock, "Network.enable")
        # Anmeldung von VOR der Umstellung herstellen: gleicher Ursprung, aber
        # eine Adresse ohne Seiten-Skripte, damit nichts vor dem Ablegen laeuft
        cdp(sock, "Page.navigate", url="https://127.0.0.1/api/health")
        pumpen(sock, 2)
        js(sock, "localStorage.clear();localStorage.setItem('jarvis_token'," + json.dumps(TOKEN)
           + ");localStorage.setItem('jarvis_user'," + json.dumps(BENUTZER)
           + ");localStorage.setItem('jarvis_lang','de');true")
        vorher = js(sock, SPEICHER) or {}
        check("Positivkontrolle: Altanmeldung liegt im Speicher", vorher.get("jarvis_token") == TOKEN)

        # ── A ──
        EREIGNISSE.clear()
        cdp(sock, "Page.navigate", url="https://127.0.0.1/portal")
        umgestellt = warte(sock, "(localStorage.getItem('jarvis_token')||'').indexOf('JCS1.')===0", 30)
        pumpen(sock, 6)
        sp = js(sock, SPEICHER) or {}
        ab = abmeldungen()
        check("/portal: keine Seite meldet von selbst ab", not ab, ab)
        check("Umstellung im Browser: jarvis_token traegt das CSRF-Token", umgestellt, sp)
        check("kein Schluessel haelt noch ein echtes Token",
              all(not v or ":" not in v for v in sp.values()), sp)
        check("CSRF-Token passt zum Sitzungstoken", sp.get("jarvis_token") == SC.csrf_fuer(TOKEN))

        # ── B ──
        kekse = cdp(sock, "Network.getCookies", urls=["https://127.0.0.1/"]).get("cookies", [])
        k = next((c for c in kekse if c.get("name") == SC.COOKIE_NAME), None)
        check("Chrome haelt das Cookie", k is not None, [c.get("name") for c in kekse])
        k = k or {}
        check("Cookie: HttpOnly", k.get("httpOnly") is True, k)
        check("Cookie: Secure", k.get("secure") is True, k)
        check("Cookie: SameSite=Strict", k.get("sameSite") == "Strict", k)
        check("Cookie: Wert ergibt das Sitzungstoken", SC.wert_lesen(k.get("value", "")) == TOKEN,
              k.get("value", "")[:60])
        check("Cookie fuer Skripte unsichtbar (document.cookie)",
              SC.COOKIE_NAME not in (js(sock, "document.cookie") or ""))

        # ── C ──
        for seite in SEITEN:
            EREIGNISSE.clear()
            cdp(sock, "Page.navigate", url="https://127.0.0.1" + seite)
            pumpen(sock, 8)
            me = js(sock, "fetch('/api/me',{headers:window.JarvisSitzung.kopfsatz()})"
                          ".then(function(r){return r.status;})")
            ab = abmeldungen()
            check("%s: keine Seite meldet von selbst ab" % seite, not ab, ab)
            check("%s: /api/me ueber JarvisSitzung -> 200 (Positivkontrolle)" % seite, me == 200, me)
            antworten = [e["params"]["response"] for e in EREIGNISSE
                         if e.get("method") == "Network.responseReceived"]
            api = [r for r in antworten if "/api/" in r.get("url", "")]
            r401 = [r["url"].replace("https://127.0.0.1", "") for r in api if r.get("status") == 401]
            check("%s: eigene API-Anfragen der Seite ohne 401 (%d Anfragen)" % (seite, len(api)),
                  len(api) > 0 and not r401, r401 or "keine API-Anfrage gesehen")
            if seite == "/chat":
                frames = [e["params"]["response"].get("payloadData", "") for e in EREIGNISSE
                          if e.get("method") == "Network.webSocketFrameReceived"]
                schlecht = [f[:120] for f in frames
                            if "Nicht autorisiert" in f or "session_invalid" in f
                            or "Sitzung ung" in f]
                check("/chat: WebSocket meldet keine ungueltige Sitzung (%d Rahmen)" % len(frames),
                      not schlecht, schlecht)
            sp = js(sock, SPEICHER) or {}
            check("%s: Speicher weiter ohne echtes Token" % seite,
                  all(not v or ":" not in v for v in sp.values()), sp)
        rc = 0 if _fail == 0 else 1
except SystemExit as e:
    rc = e.code if isinstance(e.code, int) else 2
finally:
    aufraeumen()

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(rc)
