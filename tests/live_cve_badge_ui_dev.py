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
        # Details eines OFFENEN Befunds: Zwischenrelease und Behebung in anderen
        # Debian-Versionen stehen da (7zip-Fall 2026-10-29). Der Befund wird aus
        # dem Ergebnis gewaehlt, nicht fest benannt – DEV aendert seine Pakete.
        paket = js("fetch('/api/system/cve',{headers:{Authorization:'Bearer '+localStorage.getItem('jarvis_token')}})"
                   ".then(function(r){return r.json();}).then(function(d){"
                   "var bs=((d.ergebnis||{}).befunde)||[];for(var i=0;i<bs.length;i++){var b=bs[i];"
                   "if(b.klasse==='offen'&&b.zwischenrelease&&(b.anderswo||[]).length&&(b.pakete||[]).length)"
                   "return b.pakete[0];}return null;})")
        if not paket:
            print("  (kein offener Befund mit Zwischenrelease und Behebung anderswo – Abschnitt nicht messbar)")
        else:
            js("(function(){var k=document.querySelector('button.jv-pkg-cve[data-cve-paket=\"'+%s+'\"]');"
               "if(k){k.scrollIntoView({block:'center'});k.click();}})()" % json.dumps(paket))
            time.sleep(2)
            z = js("(function(){var z=document.querySelectorAll('.jv-pkg-cve-z');var t=[];"
                   "for(var i=0;i<z.length;i++)t.push(z[i].textContent);return t;})()") or []
            check("[%s] Details von %s: Zwischenrelease genannt" % (thema, paket),
                  any("Zwischenrelease eingeplant" in t for t in z), z[:3])
            check("[%s] Details von %s: Behebung in anderen Debian-Versionen genannt" % (thema, paket),
                  any("in anderen Debian-Versionen behoben:" in t for t in z), z[:3])
            # Overlay muss den Text einrahmen, nicht abschneiden (Layout = nur im Browser messbar).
            breite = js("(function(){var z=document.querySelector('.jv-pkg-cve-z');if(!z)return null;"
                        "return [z.scrollWidth,z.clientWidth];})()")
            check("[%s] die Zusatzzeile bricht um statt ueberzulaufen" % thema,
                  bool(breite) and breite[0] <= breite[1] + 1, breite)
            import base64
            import os
            r = cmd("Page.captureScreenshot", {"format": "png"})
            if r.get("data"):
                open(os.path.expanduser("~/cve_details_%s.png" % thema), "wb").write(
                    base64.b64decode(r["data"]))
        # Haekchen "Nur noch nicht gesehene" (2026-10-29): Soll aus der API
        # gerechnet (quittierbar und nicht quittiert, mit Paketzeile), nicht
        # aus der Oberflaeche – sonst prueft die Probe sich selbst.
        soll_neu = js("fetch('/api/system/cve',{headers:{Authorization:'Bearer '+localStorage.getItem('jarvis_token')}})"
                      ".then(function(r){return r.json();}).then(function(d){"
                      "var q={};(d.quittiert||[]).forEach(function(k){q[k]=true;});"
                      "var n=0,p={};((d.ergebnis||{}).befunde||[]).forEach(function(b){"
                      "if(!b.quittierbar||q[b.id])return;n++;"
                      "if(b.bereich==='debian'||(b.bereich==='node'&&(b.pakete||[]).length))"
                      "(b.pakete||[]).forEach(function(x){p[x]=true;});});"
                      "return [n,Object.keys(p).sort()];})") or [0, []]
        haken = js("!!document.getElementById('jv-pkg-nurungesehen')")
        if not soll_neu[0]:
            check("[%s] nichts ungesehen -> kein Haekchen 'Nur noch nicht gesehene'" % thema, haken is False)
        else:
            check("[%s] %d ungesehen -> Haekchen 'Nur noch nicht gesehene' da" % (thema, soll_neu[0]),
                  haken is True)
            js("document.getElementById('jv-pkg-nurungesehen').click()")
            time.sleep(1)
            ist = js("(function(){var r=document.querySelectorAll('.jv-pkg-tab tbody tr:not(.jv-pkg-cve-zeile) td.jv-pkg-n');"
                     "var n=[];for(var i=0;i<r.length;i++)n.push(r[i].firstChild.textContent.trim());"
                     "var c=document.getElementById('jv-pkg-nurungesehen');return [n.sort(), !!c&&c.checked];})()")
            # Zeilendeckel aus der ausgelieferten Datei, nicht abgetippt.
            import re as _re
            _m = _re.search(r"var ZEILEN_MAX = (\d+);",
                            open("/opt/jarvis/frontend/js/syspackages.js", encoding="utf-8").read())
            deckel = int(_m.group(1)) if _m else 0
            check("[%s] angehakt: genau die Pakete mit ungesehenen Befunden" % thema,
                  bool(ist) and deckel > 0 and ist[1] is True and ist[0] == soll_neu[1][:len(ist[0])]
                  and len(ist[0]) == min(len(soll_neu[1]), deckel), (ist, soll_neu[1][:10], deckel))
            # Ungesehenes OHNE Paketzeile (Python, npm, Node ohne Paket) steht
            # im Sammelblock – unter dem Filter aufgeklappt.
            andere = js("(function(){var d=document.querySelector('.jv-pkg-cve-andere');"
                        "return d?[d.open,d.querySelectorAll('li').length]:null;})()")
            print("     -> ungesehen: %d Befunde, Pakete %s, Sammelblock %s"
                  % (soll_neu[0], soll_neu[1][:10], andere))
            if andere:
                check("[%s] angehakt: Sammelblock aufgeklappt" % thema, andere[0] is True, andere)
            js("document.getElementById('jv-pkg-nurungesehen').click()")
            time.sleep(1)
            check("[%s] abgehakt: Liste wieder wie vorher" % thema,
                  js("document.querySelectorAll('.jv-pkg-tab tbody tr:not(.jv-pkg-cve-zeile)').length")
                  == zeilen[0], zeilen)
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
