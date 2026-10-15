#!/usr/bin/env python3
"""Durchstich auf DEV: die Anmeldemaske blitzt beim Seitenwechsel NICHT auf.

Gemeldet 2026-10-13: "beim Seitenwechsel oder Kachel-Aufruf kommt immer wieder
die Anmeldemaske kurz auf den Schirm". /chat, /userchat, /settings und `/`
liefern die Maske sichtbar aus und blenden sie erst nach der Sitzungspruefung
aus; sitzung.js verbirgt sie seitdem, solange ein Token vorliegt.

jsdom rechnet weder Layout noch Zeichnen und kennt keine Cookies – gemessen
wird deshalb im echten Chrome gegen die AUSGELIEFERTEN Seiten. Ein Waechter,
der VOR dem ersten Skript der Seite steht (addScriptToEvaluateOnNewDocument),
fragt alle paar Millisekunden und bei jeder DOM-Aenderung, ob `#login-screen`
zeichenbar ist (display, visibility, Flaeche). Das Ergebnis liegt im
sessionStorage, damit es eine Umleitung (`/` → /portal) ueberlebt.

  A. Positivkontrolle OHNE Anmeldung: die Maske MUSS erscheinen, und zwar
     sofort (nicht erst nach dem Deckel in sitzung.js) – sonst sieht die Sonde
     nichts, und B waere trivial gruen.
  B. MIT Anmeldung (Cookie + CSRF-Token, wie nach einer echten Anmeldung):
     auf keiner der Seiten ist die Maske je zeichenbar, und am Ende steht die
     Seite selbst (Chat / Benutzer-Chat / Einstellungen / Portal).

Gegenprobe: gegen den Stand VOR der Aenderung meldet B je Seite FAIL.

Laeuft AUF DEV ueber den Hauptschluessel (das Token stellt nur der Dienst aus):
    bash /opt/jarvis/deploy/als_dienst.sh /opt/jarvis/venv/bin/python \\
         tests/live_anmeldemaske_dev.py
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

# Die Form, die eine echte Anmeldung ins Token schreibt (Register: Backslash)
BENUTZER = M._display_name(ziele.wert("JARVIS_DEV_TESTUSER"))
TOKEN = M.generate_token(BENUTZER)
M._sitzung.flush()
BASIS = "https://127.0.0.1"
# Seite -> Merkmal "die Seite selbst steht" (Positivkontrolle am Ende von B)
SEITEN = {
    "/chat": "!document.getElementById('chat-screen').classList.contains('hidden')",
    "/userchat": "getComputedStyle(document.getElementById('login-screen')).display==='none'",
    "/settings": "!document.getElementById('login-screen').classList.contains('active')",
    "/": "location.pathname.replace(/\\/+$/,'')==='/portal'",
}

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % str(info)[:300]) if info else ""))


# Laeuft vor jedem Seitenskript. Zaehlt Abfragen, in denen die Maske
# zeichenbar war, und merkt den fruehesten Zeitpunkt (ms ab Dokumentbeginn).
SONDE = r"""
(function () {
    var k = '__maske:' + location.pathname.replace(/\/+$/, '');
    var n = 0, frueh = -1, abfragen = 0;
    function sieh() {
        abfragen++;
        var el = document.getElementById('login-screen');
        if (!el) return;
        var cs = getComputedStyle(el), r = el.getBoundingClientRect();
        if (cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0) {
            n++;
            if (frueh < 0) frueh = Math.round(performance.now());
        }
        try { sessionStorage.setItem(k, JSON.stringify({n: n, frueh: frueh, abfragen: abfragen})); } catch (e) {}
    }
    new MutationObserver(sieh).observe(document, {subtree: true, childList: true, attributes: true});
    var t = setInterval(sieh, 5);
    setTimeout(function () { clearInterval(t); }, 8000);
})();
"""

PROFIL = tempfile.mkdtemp(prefix="chrome-maske-", dir=str(Path.home()))
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


def cdp(sock, methode, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": methode, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=60))
        if d.get("id") == _id[0]:
            return d.get("result", {})


def pumpen(sock, sekunden):
    ende = time.time() + sekunden
    while time.time() < ende:
        try:
            sock.recv(timeout=max(0.05, ende - time.time()))
        except TimeoutError:
            break


def js(sock, ausdruck):
    r = cdp(sock, "Runtime.evaluate", expression=ausdruck, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def warte(sock, ausdruck, frist):
    ende = time.time() + frist
    while time.time() < ende:
        if js(sock, ausdruck):
            return True
        pumpen(sock, 0.3)
    return False


def messung(sock, pfad):
    k = "__maske:" + (pfad.rstrip("/") or "")
    return json.loads(js(sock, "sessionStorage.getItem(%s)||'null'" % json.dumps(k)) or "null")


rc = 2
try:
    with connect(ws_url, max_size=80 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        cdp(sock, "Page.addScriptToEvaluateOnNewDocument", source=SONDE)

        # ── A: ohne Anmeldung ─────────────────────────────────────────────
        print("\nA. Positivkontrolle: ohne Anmeldung erscheint die Maske sofort")
        cdp(sock, "Page.navigate", url=BASIS + "/api/health")
        pumpen(sock, 1.5)
        js(sock, "localStorage.clear();sessionStorage.clear();true")
        cdp(sock, "Network.clearBrowserCookies")
        for pfad in ("/chat", "/settings"):
            cdp(sock, "Page.navigate", url=BASIS + pfad)
            pumpen(sock, 3)
            m = messung(sock, pfad) or {}
            check("%s abgemeldet: Sonde lief (%s Abfragen)" % (pfad, m.get("abfragen")),
                  (m.get("abfragen") or 0) > 10, m)
            # 1500 ms liegt klar unter dem Deckel (4000 ms): erscheint sie erst
            # danach, haette die Weiche die Maske auch OHNE Token verborgen
            check("%s abgemeldet: Maske erscheint ohne Verzoegerung (ab %s ms)" % (pfad, m.get("frueh")),
                  (m.get("n") or 0) > 0 and 0 <= (m.get("frueh") or -1) < 1500, m)
        if _fail:
            print("ABBRUCH: die Sonde sieht die Maske nicht – B waere trivial gruen")
            raise SystemExit(2)

        # ── B: angemeldet ────────────────────────────────────────────────
        print("\nB. Angemeldet: die Maske ist auf keiner Seite je zeichenbar")
        cdp(sock, "Page.navigate", url=BASIS + "/api/health")
        pumpen(sock, 1.5)
        js(sock, "localStorage.setItem('jarvis_token'," + json.dumps(TOKEN)
           + ");localStorage.setItem('jarvis_user'," + json.dumps(BENUTZER)
           + ");localStorage.setItem('jarvis_lang','de');true")
        # Umstellung auf Cookie + CSRF ueber das Portal (wie im Betrieb)
        cdp(sock, "Page.navigate", url=BASIS + "/portal")
        umgestellt = warte(sock, "(localStorage.getItem('jarvis_token')||'').indexOf('JCS1.')===0", 30)
        check("Positivkontrolle: Sitzung steht im Cookie-Verfahren", umgestellt)
        for pfad, steht in SEITEN.items():
            js(sock, "sessionStorage.clear();true")
            cdp(sock, "Page.navigate", url=BASIS + pfad)
            angekommen = warte(sock, steht, 15)
            pumpen(sock, 1)
            m = messung(sock, pfad) or {}
            check("%s: Seite steht (Positivkontrolle)" % pfad, angekommen,
                  js(sock, "location.pathname"))
            check("%s: Sonde lief (%s Abfragen)" % (pfad, m.get("abfragen")),
                  (m.get("abfragen") or 0) > 10, m)
            check("%s: Anmeldemaske nie zeichenbar" % pfad, (m.get("n") or 0) == 0, m)
        rc = 0 if _fail == 0 else 1
except SystemExit as e:
    rc = e.code if isinstance(e.code, int) else 2
finally:
    aufraeumen()

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(rc)
