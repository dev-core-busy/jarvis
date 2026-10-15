#!/usr/bin/env python3
"""Durchstich auf DEV: Bestaetigungskarte in der AUSGELIEFERTEN /chat-Seite (BSI H9).

Die jsdom-Probe (tests/test_bsi_h9_ui.js) laedt das Modul selbst und kann die
Einbindung deshalb nicht beweisen (Register: ein UI-Waechter, der seine
Skripte selbst laedt …). Hier laeuft ALLES echt: Chrome laedt
https://127.0.0.1/chat, der Auftrag geht ueber das Eingabefeld und den
Senden-Knopf, das echte Modell ruft ein Werkzeug mit Loeschwirkung auf
(``memory_manage`` delete auf einen Schluessel, den es nicht gibt – nichts
wird veraendert), die Karte erscheint, und ein ECHTER Mausklick (CDP
Input.dispatchMouseEvent auf die Knopfmitte) lehnt ab.

Laeuft AUF DEV als Dienstbenutzer:
    cd /opt/jarvis && runuser -u jarvis -- env PYTHONDONTWRITEBYTECODE=1 HOME=/home/jarvis \\
        ./venv/bin/python tests/live_bsi_h9_ui_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import base64
import json
import os
import secrets
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

BENUTZER = next((u for u in (ziele.finde("JARVIS_DEV_TESTUSER") or "", "jarvis") if u), "jarvis")
TOKEN = M.generate_token(BENUTZER)
SCHLUESSEL = "h9ui_" + secrets.token_hex(3)
AUFTRAG = (f"Lösche bitte mit memory_manage den Gedächtniseintrag '{SCHLUESSEL}' "
           "(action='delete') und sag mir, was dabei herauskam.")

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


PROFIL = tempfile.mkdtemp(prefix="chrome-h9-", dir=str(Path.home()))
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


def js(sock, ausdruck):
    r = cdp(sock, "Runtime.evaluate", expression=ausdruck, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def warte(sock, ausdruck, frist):
    ende = time.time() + frist
    while time.time() < ende:
        if js(sock, ausdruck):
            return True
        time.sleep(1)
    return False


def klick(sock, selektor):
    """Echter Mausklick auf die Mitte des Elements (nicht el.click())."""
    r = js(sock, f"""(function(){{var e=document.querySelector({json.dumps(selektor)});
        if(!e) return null; e.scrollIntoView({{block:'center'}});
        var b=e.getBoundingClientRect(); return [b.left+b.width/2, b.top+b.height/2];}})()""")
    if not r:
        return False
    for typ in ("mousePressed", "mouseReleased"):
        cdp(sock, "Input.dispatchMouseEvent", type=typ, x=r[0], y=r[1], button="left", clickCount=1)
    return True


rc = 2
try:
    with connect(ws_url, max_size=80 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        cdp(sock, "Page.addScriptToEvaluateOnNewDocument", source=(
            "try{localStorage.setItem('jarvis_chat_token'," + json.dumps(TOKEN) + ");"
            "localStorage.setItem('jarvis_lang','de');}catch(e){}"))
        cdp(sock, "Page.navigate", url="https://127.0.0.1/chat")
        geladen = warte(sock, "!!(document.getElementById('msg-input') && window.JarvisBestaetigung)", 30)
        check("Positivkontrolle: /chat geladen, Modul aus der AUSGELIEFERTEN Seite da", geladen,
              js(sock, "location.href"))
        if not geladen:
            raise SystemExit(2)
        time.sleep(3)   # WebSocket-Verbindung aufbauen lassen

        for versuch in range(1, 4):
            vorher = js(sock, "document.querySelectorAll('.jv-best').length") or 0
            js(sock, f"""(function(){{var i=document.getElementById('msg-input');
                i.value={json.dumps(AUFTRAG)}; i.dispatchEvent(new Event('input',{{bubbles:true}}));}})()""")
            klick(sock, "#btn-send")
            karte = warte(sock, f"document.querySelectorAll('.jv-best').length > {vorher}", 180)
            if karte:
                print(f"  … Karte im Versuch {versuch}")
                break
            print(f"  … Versuch {versuch}: keine Karte (Modell rief das Werkzeug evtl. nicht) – wiederhole")
            warte(sock, "!document.getElementById('btn-stop') || document.getElementById('btn-stop').offsetParent===null", 120)
        if not karte:
            print("ABBRUCH: keine Karte in drei Versuchen – nicht gemessen")
            raise SystemExit(2)

        info = js(sock, """(function(){var k=[...document.querySelectorAll('.jv-best')].pop();
            var b=k.getBoundingClientRect();
            return {titel:k.querySelector('.jv-best-titel').textContent,
                    aktion:k.querySelector('.jv-best-aktion').textContent,
                    args:[...k.querySelectorAll('dd')].map(d=>d.textContent).join('|'),
                    sichtbar: b.height>40 && getComputedStyle(k).display!=='none'
                              && k.closest('.msg-row').style.display!=='none',
                    knoepfe:[...k.querySelectorAll('button')].map(x=>x.textContent)};})()""")
        check("Karte sichtbar im Verlauf", info and info.get("sichtbar"), str(info))
        check("Titel und Wirkung im Klartext",
              info and info.get("titel") == "Bestätigung erforderlich"
              and info.get("aktion") == "Gedächtniseintrag löschen", str(info))
        check("Argumente nennen den Schluessel", info and SCHLUESSEL in info.get("args", ""), str(info))
        check("Knoepfe Ausführen/Ablehnen", info and info.get("knoepfe") == ["Ausführen", "Ablehnen"])

        bild = cdp(sock, "Page.captureScreenshot", format="png")
        ablage = Path.home() / "h9-bilder"
        ablage.mkdir(exist_ok=True)
        (ablage / "karte_offen.png").write_bytes(base64.b64decode(bild.get("data", "")))

        klick(sock, ".jv-best:last-of-type .jv-best-nein") or klick(sock, ".jv-best-row:last-child .jv-best-nein")
        quittiert = warte(sock, """(function(){var k=[...document.querySelectorAll('.jv-best')].pop();
            return k.classList.contains('is-erledigt') && /Abgelehnt/.test(k.querySelector('.jv-best-status').textContent);})()""", 30)
        check("echter Klick 'Ablehnen' → Karte quittiert 'Abgelehnt – nicht ausgeführt'", quittiert,
              js(sock, "[...document.querySelectorAll('.jv-best-status')].pop().textContent"))
        fertig = warte(sock, "(document.body.innerText||'').indexOf('Aufgabe abgeschlossen')>=0 || "
                             "!document.getElementById('btn-stop') || document.getElementById('btn-stop').offsetParent===null", 120)
        check("der Lauf endet danach (kein Haenger)", fertig)
        bild = cdp(sock, "Page.captureScreenshot", format="png")
        (ablage / "karte_abgelehnt.png").write_bytes(base64.b64decode(bild.get("data", "")))
        print(f"  … Bilder: {ablage}")
        rc = 0 if _fail == 0 else 1
except SystemExit as e:
    rc = e.code if isinstance(e.code, int) else 2
finally:
    aufraeumen()

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(rc)
