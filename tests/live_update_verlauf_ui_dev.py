"""Optische Abnahme: Aenderungsverlauf im Update-Popup (DEV, echter Chrome).

Gemessen, was jsdom nicht kann (kein Layout):
  - Knopf "Aenderungsverlauf" sichtbar in der Fusszeile des Popups
  - nach dem Klick: Liste im Popup, Popup bleibt offen
  - Fusszeile (Zurueck) liegt vollstaendig im Popup UND im Fenster
  - kein waagerechter Ueberlauf der Liste, auch bei 375 px Breite
  - Marke "noch nicht eingespielt" (falls vorhanden) innerhalb ihrer Zeile
Je Thema und Breite ein Screenshot ins HOME (nicht /tmp, siehe Register).
Nur lesend.

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_update_verlauf_ui_dev.py
"""
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
import urllib3
urllib3.disable_warnings()
from backend.main import generate_token

TOK = generate_token("jarvis")
ABLAGE = Path.home() / "abnahme-update-verlauf"
ABLAGE.mkdir(exist_ok=True)
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


PORT = 9351
prof = tempfile.mkdtemp(prefix="chrome-upd-verlauf-")
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--disable-gpu", "--remote-allow-origins=*", "--window-size=1400,900",
                      "--no-first-run", "about:blank"],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
time.sleep(6)
try:
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: kein CDP (%s)" % e)
    p.kill()
    sys.exit(2)
ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
n = [0]


def cmd(m, params=None):
    n[0] += 1
    ws.send(json.dumps({"id": n[0], "method": m, "params": params or {}}))
    while True:
        d = json.loads(ws.recv())
        if d.get("id") == n[0]:
            return d.get("result", {})


def js(code):
    r = cmd("Runtime.evaluate", {"expression": code, "returnByValue": True, "awaitPromise": True})
    return (r.get("result") or {}).get("value")


def schuss(name):
    r = cmd("Page.captureScreenshot", {"format": "png"})
    if r.get("data"):
        (ABLAGE / name).write_bytes(base64.b64decode(r["data"]))


try:
    for thema, breite, hoehe in (("dark", 1400, 900), ("light", 1400, 900), ("dark", 375, 740)):
        tag = "%s/%d" % (thema, breite)
        print("\n\033[1m%s\033[0m" % tag)
        cmd("Emulation.setDeviceMetricsOverride", {"width": breite, "height": hoehe,
                                                   "deviceScaleFactor": 1, "mobile": breite < 600})
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(1)
        js("localStorage.setItem('jarvis_token', %s);localStorage.setItem('jarvis_theme', %s);"
           % (json.dumps(TOK), json.dumps(thema)))
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(6)
        if not js("!!document.getElementById('version-pill')"):
            print("ABBRUCH: Portal ohne Versions-Pill geladen – Probe nicht deutbar")
            sys.exit(2)
        js("document.getElementById('version-pill').click()")
        time.sleep(4)
        btn = js("(function(){var b=document.getElementById('upd-verlauf-btn');if(!b)return null;"
                 "var r=b.getBoundingClientRect();return {w:r.width,h:r.height,t:b.textContent};})()")
        check("[%s] Knopf sichtbar in der Fusszeile" % tag, bool(btn and btn["w"] > 40 and btn["h"] > 16), btn)
        js("document.getElementById('upd-verlauf-btn').click()")
        time.sleep(3)
        lage = js("""(function(){
            var dd=document.getElementById('update-dropdown'), b=document.getElementById('upd-body'),
                z=document.getElementById('upd-zurueck-btn');
            if(!dd||!b||!z) return null;
            var rd=dd.getBoundingClientRect(), rz=z.getBoundingClientRect();
            var offen=[].slice.call(b.querySelectorAll('.upd-commit-offen')).map(function(m){
                var zr=m.closest('.upd-commit').getBoundingClientRect(), mr=m.getBoundingClientRect();
                return mr.right<=zr.right+1 && mr.left>=zr.left-1;});
            return {zu: dd.classList.contains('hidden'), zeilen: b.querySelectorAll('.upd-commit').length,
                zurueckImPopup: rz.top>=rd.top && rz.bottom<=rd.bottom+1,
                zurueckImFenster: rz.bottom<=innerHeight && rz.top>=0,
                popupImFenster: rd.left>=-1 && rd.right<=innerWidth+1,
                ueberlauf: b.scrollWidth-b.clientWidth, markenInnen: offen};})()""")
        if not lage:
            check("[%s] Verlaufsansicht aufgebaut" % tag, False, lage)
            continue
        check("[%s] Popup bleibt offen" % tag, not lage["zu"], lage)
        check("[%s] Liste gefuellt" % tag, lage["zeilen"] >= 1, lage["zeilen"])
        check("[%s] Zurueck-Knopf liegt im Popup" % tag, lage["zurueckImPopup"], lage)
        check("[%s] ... und im Fenster" % tag, lage["zurueckImFenster"], lage)
        check("[%s] Popup ragt nicht aus dem Fenster" % tag, lage["popupImFenster"], lage)
        check("[%s] kein waagerechter Ueberlauf" % tag, lage["ueberlauf"] <= 1, lage["ueberlauf"])
        check("[%s] Marken innerhalb ihrer Zeile" % tag, all(lage["markenInnen"]), lage["markenInnen"])
        schuss("verlauf-%s-%d.png" % (thema, breite))
finally:
    try:
        ws.close()
    except Exception:  # noqa: BLE001
        pass
    p.kill()
    subprocess.run(["rm", "-rf", prof], check=False)

print("\nBilder: %s" % ABLAGE)
print("\n\033[1m%d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(1 if fail else 0)
