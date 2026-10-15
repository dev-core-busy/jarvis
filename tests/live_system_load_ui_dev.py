"""Optische Abnahme: Systemauslastung hinter der CPU-Anzeige auf /portal (DEV).

Laeuft AUF DEV (importiert `generate_token` aus /opt/jarvis). Gemessen wird im
echten Chrome, weil jsdom kein Layout rechnet (Register):

  - Nicht-Admin: die CPU-Anzeige ist KEIN Knopf, ein Klick oeffnet nichts.
    ⚠ Auf DEV gibt es keinen ANMELDEBERECHTIGTEN Nicht-Admin (`testnutzer`
    scheitert schon an `/api/me` mit 403 – eine 403 am Endpunkt haette also den
    falschen Grund, und die Anzeige entstuende gar nicht). Nachgestellt wird der
    Fall deshalb mit dem Admin-Token und einem `/api/me`, das `is_admin: false`
    meldet – so entsteht die Anzeige wirklich, und gemessen wird genau die
    Weiche im Modul. Die SERVER-Schranke (`require_local_auth`) prueft
    `tests/test_system_load.py` am Syntaxbaum.
  - Admin: Klick UND Tastatur (Enter) oeffnen das Fenster
  - vier Kacheln, 1..20 Prozesszeilen, absteigend nach CPU
  - der Verlauf WAECHST, solange das Fenster offen ist (Live-Aktualisierung)
  - deckende Flaeche, kein waagerechter Ueberlauf, × und Escape schliessen
  - der Titel der Anzeige folgt der Sprache

Bilder landen im HOME (0700), nicht in einem festen /tmp-Pfad (Register).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import ssl

import websocket

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
import urllib3
urllib3.disable_warnings()
from backend.main import generate_token

TOK = generate_token("jarvis")
ABLAGE = os.path.join(os.path.expanduser("~"), "sysload_ui")
os.makedirs(ABLAGE, exist_ok=True)
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


def api(pfad, tok):
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request("https://127.0.0.1" + pfad,
                                 headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None


# ── Endpunkt ─────────────────────────────────────────────────────────────
print("\n\033[1m0. Endpunkt\033[0m")
st, d = api("/api/system/load", TOK)
if st != 200 or not d:
    print("KONNTE NICHT LAUFEN: /api/system/load als Admin -> %s" % st); sys.exit(2)
check("Admin bekommt 200 mit Prozessliste", 0 < len(d.get("prozesse") or []) <= 20,
      len(d.get("prozesse") or []))

PORT, prof = 9343, os.path.join(ABLAGE, "chrome-profil")
subprocess.run(["rm", "-rf", prof], check=False)
log = open(os.path.join(ABLAGE, "chrome.log"), "w")
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--disable-gpu", "--remote-allow-origins=*", "--window-size=1400,900",
                      "--no-first-run", "about:blank"], stdout=log, stderr=log)
time.sleep(6)
tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
n = [0]


def cmd(m, params=None):
    n[0] += 1
    ws.send(json.dumps({"id": n[0], "method": m, "params": params or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == n[0]:
            return r.get("result", {})


def js(code):
    r = cmd("Runtime.evaluate", {"expression": code, "returnByValue": True,
                                 "awaitPromise": True})
    return (r.get("result") or {}).get("value")


def schuss(datei):
    r = cmd("Page.captureScreenshot", {"format": "png"})
    if r.get("data"):
        import base64
        open(datei, "wb").write(base64.b64decode(r["data"]))


def laden(tok, thema="dark"):
    cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
    time.sleep(1.5)
    js("localStorage.setItem('jarvis_token', %s);"
       "localStorage.setItem('jarvis_theme', %s);" % (json.dumps(tok), json.dumps(thema)))
    cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
    time.sleep(6)


try:
    print("\n\033[1m1. Als Nicht-Administrator (nachgestellt)\033[0m")
    # Ohne Page.enable wird das Skript zwar registriert, aber nie ausgefuehrt
    # (gemessen: `identifier` kommt zurueck, `window.__probe` bleibt leer).
    cmd("Page.enable")
    kein_admin = cmd("Page.addScriptToEvaluateOnNewDocument", {"source": (
        "(function(){var f=window.fetch;window.fetch=function(u,o){"
        "if(String(u).split('?')[0]==='/api/me'){return f(u,o).then(function(r){"
        "return r.json().then(function(d){d.is_admin=false;"
        "return new Response(JSON.stringify(d),{status:200,"
        "headers:{'Content-Type':'application/json'}});});});}"
        "return f(u,o);};})();")})
    laden(TOK)
    check("Positivkontrolle: /api/me meldet der Seite is_admin=false",
          js("fetch('/api/me',{headers:{Authorization:'Bearer '+localStorage.getItem('jarvis_token')}})"
             ".then(function(r){return r.json();}).then(function(d){return d.is_admin;})") is False)
    check("Positivkontrolle: die CPU-Anzeige ist da",
          js("!!document.getElementById('cpu-bar')") is True)
    check("die CPU-Anzeige ist kein Knopf",
          js("(function(){var c=document.getElementById('cpu-bar');"
             "return !c.classList.contains('jv-cpu-klick') && !c.hasAttribute('tabindex');})()") is True)
    js("document.getElementById('cpu-bar').click()")
    time.sleep(1.5)
    check("ein Klick oeffnet nichts",
          js("!document.querySelector('.jv-load-overlay.an')") is True)
    cmd("Page.removeScriptToEvaluateOnNewDocument", {"identifier": kein_admin.get("identifier")})

    for thema in ("dark", "light"):
        print("\n\033[1m2. Als Administrator, Thema '%s'\033[0m" % thema)
        laden(TOK, thema)
        check("[%s] die CPU-Anzeige ist als Knopf ausgestattet" % thema,
              js("(function(){var c=document.getElementById('cpu-bar');"
                 "return !!c && c.classList.contains('jv-cpu-klick') && c.getAttribute('role')==='button'"
                 " && getComputedStyle(c).cursor==='pointer';})()") is True)

        js("document.getElementById('cpu-bar').click()")
        time.sleep(2.5)
        check("[%s] Klick oeffnet das Fenster" % thema,
              js("!!document.querySelector('.jv-load-overlay.an')") is True)
        kacheln = js("document.querySelectorAll('.jv-load-tile').length")
        check("[%s] vier Kacheln (CPU, Speicher, Netz, Platte)" % thema, kacheln == 4, kacheln)
        cpu_werte = js("Array.from(document.querySelectorAll('.jv-load-tab tbody .jv-load-cpuwert'))"
                       ".map(function(e){return parseFloat(e.textContent.replace(',','.'));})")
        check("[%s] 1..20 Prozesszeilen" % thema, 0 < len(cpu_werte or []) <= 20,
              len(cpu_werte or []))
        check("[%s] absteigend nach CPU" % thema,
              bool(cpu_werte) and cpu_werte == sorted(cpu_werte, reverse=True), cpu_werte)
        kerne = js("document.querySelectorAll('.jv-load-core').length")
        check("[%s] je Kern ein Balken" % thema, (kerne or 0) >= 1, kerne)

        # Sortieren (2026-09-28): Klick auf "PID" – und die Folge muss die
        # ECHTEN Takte ueberstehen (die Tabelle wird alle 3 s neu gebaut).
        js("document.querySelector('.jv-load-tab th[data-sort=\"pid\"]').click()")
        time.sleep(0.3)
        pids0 = js("Array.from(document.querySelectorAll('.jv-load-tab tbody tr')).map(function(tr){return parseInt(tr.children[2].textContent,10);})")
        check("[%s] Klick auf PID sortiert absteigend" % thema,
              bool(pids0) and pids0 == sorted(pids0, reverse=True), pids0)
        pkt0 = js("(document.querySelector('.jv-load-line').getAttribute('points')||'')"
                  ".trim().split(' ').length")
        time.sleep(7)
        pkt1 = js("(document.querySelector('.jv-load-line').getAttribute('points')||'')"
                  ".trim().split(' ').length")
        check("[%s] der Verlauf waechst, solange das Fenster offen ist" % thema,
              (pkt1 or 0) > (pkt0 or 0), (pkt0, pkt1))
        pids1 = js("Array.from(document.querySelectorAll('.jv-load-tab tbody tr')).map(function(tr){return parseInt(tr.children[2].textContent,10);})")
        pfeil = js("document.querySelector('.jv-load-tab th[data-sort=\"pid\"]').getAttribute('aria-sort')")
        check("[%s] ⚠ nach zwei echten Takten ist die Tabelle noch nach PID sortiert" % thema,
              bool(pids1) and pids1 == sorted(pids1, reverse=True) and pfeil == "descending",
              (pfeil, pids1))

        deck = js("getComputedStyle(document.querySelector('.jv-load-box')).backgroundColor")
        check("[%s] deckende Flaeche" % thema, bool(deck) and "rgba" not in deck, deck)
        masse = js("(function(){var b=document.querySelector('.jv-load-box');"
                   "var r=b.getBoundingClientRect();"
                   "return {quer: document.documentElement.scrollWidth<=window.innerWidth+1,"
                   "boxQuer: b.scrollWidth<=b.clientWidth+1, imFenster: r.bottom<=window.innerHeight+1};})()")
        check("[%s] kein waagerechter Ueberlauf, Kasten im Fenster" % thema,
              bool(masse and masse["quer"] and masse["boxQuer"] and masse["imFenster"]), masse)
        schuss(os.path.join(ABLAGE, "sysload_%s.png" % thema))

        js("document.querySelector('.jv-load-overlay .jv-pkg-close').click()")
        time.sleep(0.5)
        check("[%s] × schliesst" % thema,
              js("!document.querySelector('.jv-load-overlay.an')") is True)

        js("(function(){var c=document.getElementById('cpu-bar'); c.focus();"
           "c.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));})()")
        time.sleep(2)
        check("[%s] Enter auf der Anzeige oeffnet" % thema,
              js("!!document.querySelector('.jv-load-overlay.an')") is True)
        js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))")
        time.sleep(0.5)
        check("[%s] Escape schliesst" % thema,
              js("!document.querySelector('.jv-load-overlay.an')") is True)

    print("\n\033[1m3. Sprachwechsel\033[0m")
    js("window.setLang && window.setLang('en')")
    time.sleep(0.8)
    t = js("document.getElementById('cpu-bar').title")
    check("der Titel der Anzeige folgt der Sprache", t == "Show system load", t)
    js("window.setLang && window.setLang('de')")
finally:
    try: ws.close()
    except Exception: pass
    p.kill()
    time.sleep(1)
    subprocess.run(["rm", "-rf", prof], check=False)

print("\n\033[1m%d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(1 if fail else 0)
