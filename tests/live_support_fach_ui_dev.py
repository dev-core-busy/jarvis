#!/usr/bin/env python3
"""Optische Abnahme der Fachsystem-Kaestchen unter /support im echten Chrome.

jsdom rechnet KEIN Layout: Ueberlappung, Breite und Abgeschnittenes sieht nur
ein Screenshot (Register-Eintrag). Zusaetzlich wird hier GEMESSEN, was ein
Quelltext-Grep nicht beweist: dass die Kaestchen ohne Freigabe wirklich
unsichtbar sind, mit Freigabe erscheinen und dass die Zeile in beiden Themen
nicht ueberlaeuft.

Faellt die Freigabe am Ende auf ihren Ausgangswert zurueck.
"""
import json
import subprocess
import sys
import time
import urllib.request

import websocket

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
import requests
import urllib3
urllib3.disable_warnings()
from backend.main import generate_token
from backend.config import config

TOK = generate_token("jarvis")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


VORHER = config.get_setting("sap_allowed_users", "")
PORT, prof = 9341, "/tmp/chrome-sup-fach"
subprocess.run(["rm", "-rf", prof], check=False)
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1500,1200", "--no-first-run",
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


def oeffne(thema):
    cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
    time.sleep(2)
    js("localStorage.setItem('jarvis_token', %s);"
       "localStorage.setItem('jarvis_theme', %s);" % (json.dumps(TOK), json.dumps(thema)))
    cmd("Page.navigate", {"url": "https://127.0.0.1/support"})
    time.sleep(4)


def sichtbar(id_):
    return js("(function(){var e=document.getElementById('%s');"
              "return !!(e && e.offsetParent !== null);})()" % id_)


try:
    print("\n\033[1m1. Ohne Freigabe: die Kaestchen gibt es gar nicht\033[0m")
    config.save_setting("sap_allowed_users", "")
    config.save_setting("vemas_allowed_users", "")
    time.sleep(0.5)
    oeffne("dark")
    check("die Seite ist da", js("location.pathname") == "/support", js("location.pathname"))
    check("SAP-Kaestchen unsichtbar", sichtbar("sup-opt-sap-wrap") is False)
    check("VEMAS-Kaestchen unsichtbar", sichtbar("sup-opt-vemas-wrap") is False)
    check("die uebrigen Quellen stehen unveraendert da",
          sichtbar("sup-opt-ibs-wrap") is True and sichtbar("sup-opt-rag") is True)

    print("\n\033[1m2. Mit Freigabe: sichtbar, und der Zustand stimmt\033[0m")
    config.save_setting("sap_allowed_users", "jarvis")
    time.sleep(0.5)
    for thema in ("dark", "light"):
        oeffne(thema)
        check("[%s] Thema gesetzt" % thema,
              js("document.body.classList.contains('light')") == (thema == "light"))
        check("[%s] SAP-Kaestchen sichtbar" % thema, sichtbar("sup-opt-sap-wrap") is True)
        check("[%s] VEMAS bleibt weg (Skill aus)" % thema,
              sichtbar("sup-opt-vemas-wrap") is False)
        check("[%s] SAP ist klickbar (Zugang hinterlegt)" % thema,
              js("document.getElementById('sup-opt-sap').disabled") is False)
        check("[%s] Vorgabe AUS – ein Agentenlauf startet nicht ungefragt" % thema,
              js("document.getElementById('sup-opt-sap').checked") is False)
        check("[%s] das Kaestchen sagt im Titel, was es tut" % thema,
              "Fachsystem" in (js("document.getElementById('sup-opt-sap-wrap').title") or ""),
              js("document.getElementById('sup-opt-sap-wrap').title"))
        check("[%s] SAP steht im Quellen-Filter" % thema,
              js("!![].slice.call(document.getElementById('sup-f-source').options)"
                 ".filter(function(o){return o.value==='SAP';})[0]") is True)
        # Es gehoert zu den QUELLEN, nicht zur Ausgabe-Gruppe daneben - die Zeile
        # traegt seit 2026-08-30 zwei benannte Gruppen mit verschiedener Bedeutung.
        check("[%s] es steht bei den Quellen, nicht bei der Ausgabe" % thema,
              js("!!document.getElementById('sup-opt-sap-wrap')"
                 ".closest('#sup-opts-src')") is True)
        check("[%s] die Ausgabe-Option steht abgesetzt in eigener Gruppe" % thema,
              js("!!document.getElementById('sup-opt-ai').closest('#sup-opts-out')") is True
              and js("!document.getElementById('sup-opt-ai').closest('#sup-opts-src')") is True)
        check("[%s] die Beschriftung ist nicht abgeschnitten" % thema,
              js("(function(){var e=document.querySelector('#sup-opt-sap-wrap span');"
                 "return e.scrollWidth <= e.clientWidth + 1;})()") is True)
        check("[%s] kein waagerechter Ueberlauf" % thema,
              js("document.documentElement.scrollWidth <= window.innerWidth + 2") is True,
              js("document.documentElement.scrollWidth + ' > ' + window.innerWidth"))
        # Die Zeile umbricht - die Kaestchen duerfen sich nicht ueberlagern.
        check("[%s] die Quellen-Kaestchen ueberlappen einander nicht" % thema,
              js("(function(){var l=[].slice.call(document.querySelectorAll('.sup-opts label'))"
                 ".filter(function(e){return e.offsetParent!==null;});"
                 "for(var i=0;i<l.length;i++)for(var j=i+1;j<l.length;j++){"
                 "var a=l[i].getBoundingClientRect(),b=l[j].getBoundingClientRect();"
                 "if(a.left<b.right-1&&b.left<a.right-1&&a.top<b.bottom-1&&b.top<a.bottom-1)"
                 "return false;}return true;})()") is True)
        # Sprachwechsel: die Beschriftungen haengen an i18n-Schluesseln.
        js("window.setLang && window.setLang('en');")
        time.sleep(0.6)
        check("[%s] Sprachwechsel bricht nichts" % thema,
              sichtbar("sup-opt-sap-wrap") is True
              and (js("document.querySelector('#sup-opt-sap-wrap span').textContent") or "").strip() == "SAP")
        js("window.setLang && window.setLang('de');")
        time.sleep(0.4)
        bild = cmd("Page.captureScreenshot", {"format": "png"}).get("data") or ""
        import base64
        open("/tmp/support-fach-%s.png" % thema, "wb").write(base64.b64decode(bild))
        check("[%s] Screenshot geschrieben" % thema, len(bild) > 5000)

finally:
    config.save_setting("sap_allowed_users", VORHER or "")
    config.save_setting("vemas_allowed_users", "")
    try:
        ws.close()
    except Exception:
        pass
    p.terminate()
    print("\n\033[1mRueckbau\033[0m")
    check("Freigabe wieder im Ausgangszustand",
          config.get_setting("sap_allowed_users", "") == (VORHER or ""),
          config.get_setting("sap_allowed_users", ""))

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
