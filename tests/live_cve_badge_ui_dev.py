"""Optische Abnahme der Sicherheitsluecken-Badge am ⓘ-Symbol (DEV, echter Chrome).

Gemessen, was ein Quelltext-Grep nicht beweist (Vorgabe 2026-10-29: die Badge
gehoert an "Installierte Pakete", NICHT ans Zahnrad):
  - die Zahl an der Badge ist die aus /api/me (cve_badge.anzahl)
  - sie sitzt IM ⓘ-Knopf und ragt sichtbar ueber dessen Ecke
  - die Zahnrad-Badge zaehlt keine Luecken mit
  - ein Klick auf die Badge oeffnet die Liste GEFILTERT auf betroffene Pakete
Nur lesend: es wird nichts geprueft, behoben oder quittiert.

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_cve_badge_ui_dev.py
"""
import json
import subprocess
import sys
import time
import urllib.request

import websocket

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
import urllib3
urllib3.disable_warnings()
from backend.main import generate_token

TOK = generate_token("jarvis")
TOK_USER = generate_token("contoso\\testnutzer")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


PORT, prof = 9343, "/tmp/chrome-cve-badge-ui"
subprocess.run(["rm", "-rf", prof], check=False)
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1400,900", "--no-first-run",
                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)
tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
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
    r = cmd("Runtime.evaluate", {"expression": code, "returnByValue": True,
                                 "awaitPromise": True})
    return (r.get("result") or {}).get("value")


def schuss(datei):
    r = cmd("Page.captureScreenshot", {"format": "png"})
    if r.get("data"):
        import base64
        open(datei, "wb").write(base64.b64decode(r["data"]))



try:
    for thema in ("dark", "light"):
        print("\n\033[1mThema '%s'\033[0m" % thema)
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(1)
        js("localStorage.setItem('jarvis_token', %s);"
           "localStorage.setItem('jarvis_theme', %s);" % (json.dumps(TOK), json.dumps(thema)))
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(6)
        me = js("fetch('/api/me',{headers:{Authorization:'Bearer '+localStorage.getItem('jarvis_token')}})"
                ".then(function(r){return r.json();})")
        if not isinstance(me, dict) or not me.get("is_admin"):
            print("ABBRUCH: /api/me liefert keinen Administrator – Probe nicht deutbar")
            sys.exit(2)
        soll = (me.get("cve_badge") or {}).get("anzahl", 0)
        if not soll:
            print("ABBRUCH: keine Pakete mit Luecken auf DEV – die Badge ist nicht messbar")
            sys.exit(2)
        text = js("(function(){var b=document.querySelector('#jv-pkg-btn .jv-pkg-badge');"
                  "return b?b.textContent:null;})()")
        check("[%s] die Badge sitzt im ⓘ-Knopf" % thema, text is not None)
        check("[%s] sie zeigt die Zahl aus /api/me" % thema,
              text == (str(soll) if soll <= 99 else "99+"), (text, soll))
        lage = js("(function(){var b=document.getElementById('jv-pkg-btn'),"
                  "e=b&&b.querySelector('.jv-pkg-badge');if(!e)return null;"
                  "var rb=b.getBoundingClientRect(),re=e.getBoundingClientRect();"
                  "return {ueberEcke: re.top<rb.top && re.right>rb.right-2,"
                  "sichtbar: re.width>=14 && re.height>=14,"
                  "bg:getComputedStyle(e).backgroundColor};})()")
        check("[%s] sie ragt sichtbar ueber die rechte obere Ecke" % thema,
              bool(lage and lage["ueberEcke"] and lage["sichtbar"]), lage)
        gear = js("(function(){var g=document.querySelector('.jv-gear-badge');"
                  "return g?g.textContent:'';})()")
        gsoll = (me.get("admin_badge") or {}).get("gesamt", 0)
        check("[%s] die Zahnrad-Badge zaehlt keine Luecken (nur ihre eigene Summe)" % thema,
              gear == ("" if not gsoll else (str(gsoll) if gsoll <= 99 else "99+")), (gear, gsoll))
        r = cmd("Page.captureScreenshot", {"format": "png", "clip": {
            "x": 0, "y": 0, "width": 760, "height": 60, "scale": 2}})
        if r.get("data"):
            import base64
            open("/tmp/cve_badge_%s.png" % thema, "wb").write(base64.b64decode(r["data"]))
        js("document.querySelector('#jv-pkg-btn .jv-pkg-badge').click()")
        time.sleep(5)
        check("[%s] Klick auf die Badge oeffnet die Paketliste" % thema,
              js("!!document.querySelector('.jv-pkg-overlay.an')") is True)
        check("[%s] gefiltert auf betroffene Pakete" % thema,
              js("(function(){var c=document.getElementById('jv-pkg-nurluecken');"
                 "return !!c && c.checked;})()") is True)
        zeilen = js("(function(){var r=document.querySelectorAll('.jv-pkg-tab tbody tr:not(.jv-pkg-cve-zeile)');"
                    "var m=0;for(var i=0;i<r.length;i++){if(r[i].querySelector('.jv-pkg-cve'))m++;}"
                    "return [r.length,m];})()")
        check("[%s] jede gezeigte Zeile traegt eine Markierung" % thema,
              bool(zeilen) and zeilen[0] > 0 and zeilen[0] == zeilen[1], zeilen)
        js("document.querySelector('.jv-pkg-close').click()")
finally:
    try:
        ws.close()
    except Exception:  # noqa: BLE001
        pass
    p.kill()
    subprocess.run(["rm", "-rf", prof], check=False)

print("\n\033[1m%d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(1 if fail else 0)
