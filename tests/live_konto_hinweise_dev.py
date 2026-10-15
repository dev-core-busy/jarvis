#!/usr/bin/env python3
"""Live auf DEV: Hinweis "deine 2FA wurde zurueckgesetzt" – Endpunkt UND Karte im Browser.

Ohne Admin-Kennwort laesst sich keine echte Ruecksetzung ausloesen. Der Vermerk
wird deshalb so hergestellt, wie ihn die Ruecksetzung schreibt – an einem
ZUSAETZLICHEN Schluessel ``zzprobe\\<testkonto>``. Der Dienst ordnet ihn ueber
_norm_login derselben Person zu (genau die Schreibweisen-Falle, die der Hinweis
abdecken muss), und die ECHTEN Eintraege des Testkontos bleiben unberuehrt.

Gemessen: GET /api/auth/hinweise, Karte auf der AUSGELIEFERTEN /chat-Seite im
echten Chrome (hell + dunkel, Screenshot nach ~/abnahme-konto-hinweise/),
echter Klick auf "Verstanden" -> Vermerk serverseitig weg. Am Ende: Probe-
Schluessel entfernt, alle anderen Eintraege byte-gleich wie vorgefunden.

⚠ /chat und nicht /settings: der Sicherheits-Reiter ruft beim Oeffnen
/api/auth/totp/setup und schreibt damit selbst in auth_state.json (Befund
2026-10-04) – die Messung wuerde den Zustand veraendern, den sie prueft.

Aufruf: cd /opt/jarvis && runuser -u jarvis -- env PYTHONDONTWRITEBYTECODE=1 \
            HOME=/home/jarvis venv/bin/python tests/live_konto_hinweise_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import base64
import copy
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402

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


def ruf(pfad, token, rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method="POST" if daten is not None else "GET")
    r.add_header("Authorization", "Bearer " + token)
    if daten is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=60) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


from backend import main as M  # noqa: E402

BENUTZER = ziele.wert("JARVIS_DEV_TESTUSER")
TOK = M.generate_token(BENUTZER)
PROBE = "zzprobe\\" + M._norm_login(BENUTZER)
BILDER = Path.home() / "abnahme-konto-hinweise"


def andere():
    return {k: v for k, v in copy.deepcopy(M._load_auth_state().get("users") or {}).items() if k != PROBE}


print("Live DEV: Hinweis an das Konto nach 2FA-Ruecksetzung (%s)" % PROBE)
st, d = ruf("/api/auth/hinweise", TOK)
if st != 200:
    print("NICHT PRUEFBAR: /api/auth/hinweise -> %s" % st)
    sys.exit(2)
if d.get("hinweise"):
    print("NICHT PRUEFBAR: Testkonto hat schon einen echten Hinweis – nicht anfassen.")
    sys.exit(2)
check(True, "(Positivkontrolle) Endpunkt erreichbar, kein Hinweis vorhanden")
VORHER = andere()
if PROBE in (M._load_auth_state().get("users") or {}):
    print("NICHT PRUEFBAR: Probe-Schluessel existiert schon")
    sys.exit(2)
if any(v.get("totp_enabled") for k, v in VORHER.items() if M._norm_login(k) == M._norm_login(BENUTZER)):
    print("NICHT PRUEFBAR: Testkonto hat 2FA an – der Hinweis waere zu Recht unterdrueckt.")
    sys.exit(2)

chrome = None
PROFIL = tempfile.mkdtemp(prefix="chrome-kh-", dir=str(Path.home()))
try:
    AM = int(time.time()) - 3600
    M._set_user_auth_state(PROBE, {"must_change_password": False, "totp_enabled": False, "totp_secret": None,
                                   "totp_zurueckgesetzt": {"von": "Probe-Admin", "am": AM}})
    st, d = ruf("/api/auth/hinweise", TOK)
    check(st == 200 and d.get("hinweise") == [{"art": "totp_zurueckgesetzt", "von": "Probe-Admin", "am": AM}],
          "Hinweis wird ueber die ANDERE Schreibweise gefunden", str(d))

    # ── Karte im echten Chrome ──
    BILDER.mkdir(exist_ok=True)
    os.chmod(PROFIL, 0o700)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
    chrome = subprocess.Popen(["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
                               f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
                               f"--user-data-dir={PROFIL}", "--window-size=1100,800",
                               "--ignore-certificate-errors", "about:blank"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    ws = None
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as a:
                ws = next((t["webSocketDebuggerUrl"] for t in json.loads(a.read()) if t.get("type") == "page"), None)
            if ws:
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    from websockets.sync.client import connect
    n = [0]

    def cdp(sock, m, **p):
        n[0] += 1
        sock.send(json.dumps({"id": n[0], "method": m, "params": p}))
        while True:
            x = json.loads(sock.recv(timeout=30))
            if x.get("id") == n[0]:
                return x.get("result", {})

    def js(sock, a):
        r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True, awaitPromise=True)
        return (r.get("result") or {}).get("value") if "exceptionDetails" not in r else "WURF"

    with connect(ws, max_size=80 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        for thema in ("dark", "light"):
            skript = cdp(sock, "Page.addScriptToEvaluateOnNewDocument", source=(
                "localStorage.setItem('jarvis_chat_token', %s);localStorage.setItem('jarvis_token', %s);"
                "localStorage.setItem('jarvis_theme', '%s');sessionStorage.clear();"
                "window.__fehler='';window.addEventListener('error',function(e){window.__fehler+=e.message+' | ';});"
                % (json.dumps(TOK), json.dumps(TOK), thema)))
            cdp(sock, "Page.navigate", url=BASIS + "/chat")
            time.sleep(5)
            info = js(sock, "(function(){var k=document.querySelector('.jkh-karte'); if(!k) return null;"
                            " var r=k.getBoundingClientRect(); return {text:k.textContent, x:r.left, y:r.top, w:r.width, h:r.height,"
                            " bg:getComputedStyle(k).backgroundColor, fehler: window.__fehler};})()")
            check(isinstance(info, dict), f"[{thema}] Karte erscheint auf /chat")
            if isinstance(info, dict):
                check("Probe-Admin" in info["text"], f"[{thema}] nennt den Administrator")
                check(not info["fehler"], f"[{thema}] keine JS-Fehler", info["fehler"])
                check(info["x"] >= 0 and info["x"] + info["w"] <= 1100, f"[{thema}] Karte liegt ganz im Fenster", str(info))
                check(not info["bg"].startswith("rgba") or info["bg"].endswith(", 1)"), f"[{thema}] deckende Flaeche", info["bg"])
                b = cdp(sock, "Page.captureScreenshot", format="png",
                        clip={"x": max(0, info["x"] - 10), "y": max(0, info["y"] - 10),
                              "width": info["w"] + 20, "height": info["h"] + 20, "scale": 1})
                (BILDER / f"karte_{thema}.png").write_bytes(base64.b64decode(b["data"]))
            cdp(sock, "Page.removeScriptToEvaluateOnNewDocument", identifier=skript.get("identifier"))
        # Echter Klick auf "Verstanden" (Seite steht noch, helles Thema)
        js(sock, "document.querySelector('.jkh-gelesen').click()")
        time.sleep(1.5)
        check(js(sock, "!document.querySelector('.jkh-karte')") is True, "Verstanden: Karte verschwindet")
    st, d = ruf("/api/auth/hinweise", TOK)
    check(st == 200 and d.get("hinweise") == [], "Verstanden: serverseitig quittiert", str(d))
    check(not (M._load_auth_state()["users"].get(PROBE) or {}).get("totp_zurueckgesetzt"),
          "Vermerk am Probe-Schluessel abgeraeumt")
finally:
    if chrome:
        chrome.kill()
    shutil.rmtree(PROFIL, ignore_errors=True)
    st_ = M._load_auth_state()
    if PROBE in (st_.get("users") or {}):
        del st_["users"][PROBE]
        M._save_auth_state(st_)
    check(PROBE not in (M._load_auth_state().get("users") or {}), "Probe-Schluessel entfernt")
    check(andere() == VORHER, "alle anderen Eintraege wie vorgefunden")

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
