#!/usr/bin/env python3
"""Optische Abnahme (DEV, echtes Chrome): Zeile der Agent-API-Keys.

Vorgabe des Betreibers 2026-11-20: "Gültig bis" steht IN der Zeile zwischen
Neu-generieren und Loeschen, die Bereiche bearbeitet ein Stift in einem
eigenen Fenster. jsdom rechnet kein Layout – ob die Zeile umbricht oder das
Datumsfeld die Knoepfe verdraengt, sieht nur ein echter Browser.

Gemessen je Zeile (Bildschirmkoordinaten, nicht Markup-Reihenfolge):
  - Neu-generieren, "bis"-Feld, Stift, Muelleimer liegen auf EINER Linie
    (senkrechte Mitten innerhalb von 6 px) und in dieser Reihenfolge von links;
  - nichts davon ragt rechts aus der Liste heraus.
Dazu: das Fenster oeffnet sich, ist sichtbar (opacity 1) und zeigt alle
Bereiche; geschlossen wird mit "Abbrechen" – NICHTS wird gespeichert.
Bilder (dunkel/hell) ins HOME: agent-keys-<thema>.png, agent-keys-fenster-<thema>.png.

Positivkontrolle: mindestens eine Zeile ist da, sonst Exit 2.

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_agent_keys_ui_dev.py
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

import websocket

sys.path.insert(0, "/opt/jarvis")
import urllib3  # noqa: E402
urllib3.disable_warnings()
from backend.main import generate_token  # noqa: E402

TOK = generate_token("jarvis")
HOME = os.path.expanduser("~")
PORT, prof = 9371, os.path.join(HOME, ".chrome-agent-keys")
subprocess.run(["rm", "-rf", prof], check=False)
log = open(os.path.join(HOME, "chrome-agent-keys.log"), "w")
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1400,1000", "--no-first-run",
                      "about:blank"], stdout=log, stderr=log)
time.sleep(6)
tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
n = [0]
_ok = _fail = 0


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


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text + (f"  [{info}]" if info else ""))


def bild(name, sel):
    """Ausschnitt um ``sel`` (Seitenkoordinaten: clip rechnet in der SEITE)."""
    r = js("(function(){var e=document.querySelector(%s);if(!e)return null;e.scrollIntoView({block:'center'});"
           "var b=e.getBoundingClientRect();return {x:b.left+scrollX,y:b.top+scrollY,w:b.width,h:b.height};})()"
           % json.dumps(sel))
    if not r:
        return
    time.sleep(0.4)
    d = cmd("Page.captureScreenshot", {"format": "png", "clip": {
        "x": max(0, r["x"] - 10), "y": max(0, r["y"] - 10), "width": r["w"] + 20,
        "height": r["h"] + 20, "scale": 1}}).get("data", "")
    with open(os.path.join(HOME, name), "wb") as fh:
        fh.write(base64.b64decode(d))


MESSEN = r"""(function(){
  var liste = document.getElementById('agent-keys-list');
  if (!liste) return null;
  var rl = liste.getBoundingClientRect();
  return Array.from(liste.querySelectorAll('[data-id]')).map(function(z){
    function m(sel){var e=z.querySelector(sel); if(!e) return null; var b=e.getBoundingClientRect();
      return {l:b.left, r:b.right, mitte:(b.top+b.bottom)/2, w:b.width};}
    return {id:z.dataset.id, regen:m('.ak-regen'), bis:m('.ak-ablauf-feld'), stift:m('.ak-rechte'),
            del:m('.ak-del'), listeR: rl.right};
  });
})()"""

cmd("Runtime.enable")
cmd("Page.enable")
try:
    for thema in ("dark", "light"):
        print(f"\n── Thema {thema}")
        # Anmeldung wie in live_bsi_h4_cookie_ui_dev.py: Token auf einer Seite
        # OHNE Skripte ablegen, dann stellt /portal es auf das HttpOnly-Cookie
        # um (BSI H4) – ein blosses localStorage-Token bekommt sonst 401.
        cmd("Page.navigate", {"url": "https://127.0.0.1/api/health"})
        time.sleep(2)
        js("localStorage.clear(); localStorage.setItem('jarvis_token', %s);"
           "localStorage.setItem('jarvis_user','jarvis'); localStorage.setItem('jarvis_theme', %s);"
           "localStorage.setItem('jarvis_lang','de'); true" % (json.dumps(TOK), json.dumps(thema)))
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        for _ in range(30):
            if js("(localStorage.getItem('jarvis_token')||'').indexOf('JCS1.')===0"):
                break
            time.sleep(1)
        else:
            print("ABBRUCH: Sitzung wurde nicht auf das Cookie umgestellt")
            sys.exit(2)
        cmd("Page.navigate", {"url": "https://127.0.0.1/settings"})
        time.sleep(6)
        # Wie ein Benutzer: ist der Abschnitt zu, die Kopfzeile anklicken
        # (der Klick-Hook laedt die Liste).
        js("(function(){var b=document.getElementById('prof-sect-api-body');"
           "if(b&&b.style.display==='none')document.getElementById('prof-sect-api-hdr').click();})()")
        time.sleep(2.5)
        zeilen = js(MESSEN)
        if not zeilen:
            print("Abruf im Browser:", js("fetch('/api/agent/keys',{headers:{'Authorization':'Bearer '+"
                                          "(window.JarvisSitzung?JarvisSitzung.token():localStorage.getItem('jarvis_token'))}})"
                                          ".then(r=>r.status+' '+r.headers.get('content-type')).catch(e=>'wurf '+e)"))
            print("Diagnose:", js("JSON.stringify({pfad:location.pathname, liste:!!document.getElementById('agent-keys-list'),"
                                  "body:(document.getElementById('prof-sect-api-body')||{}).style&&document.getElementById('prof-sect-api-body').style.display,"
                                  "text:((document.getElementById('agent-keys-list')||{}).textContent||'').slice(0,120),"
                                  "onshow:typeof window.agentKeysOnShow, modal:typeof window._openSettingsModal})"))
            print("ABBRUCH: keine Schluesselzeile sichtbar – Messaufbau defekt")
            sys.exit(2)
        for z in zeilen:
            teile = [z["regen"], z["bis"], z["stift"], z["del"]]
            if None in teile:
                check(f"Zeile {z['id']}: alle vier Elemente da", False, str(teile))
                continue
            mitten = [t["mitte"] for t in teile]
            check(f"Zeile {z['id']}: Neu, bis, Stift, Loeschen auf EINER Linie",
                  max(mitten) - min(mitten) <= 6, "Mitten %s" % [round(x) for x in mitten])
            check(f"Zeile {z['id']}: Reihenfolge von links Neu → bis → Stift → Loeschen",
                  z["regen"]["r"] <= z["bis"]["l"] and z["bis"]["r"] <= z["stift"]["l"]
                  and z["stift"]["r"] <= z["del"]["l"])
            check(f"Zeile {z['id']}: nichts ragt rechts aus der Liste",
                  z["del"]["r"] <= z["listeR"] + 1, "del.r=%d liste.r=%d" % (z["del"]["r"], z["listeR"]))
        bild(f"agent-keys-{thema}.png", "#agent-keys-list")

        js("document.querySelector('#agent-keys-list .ak-rechte').click()")
        time.sleep(1.2)
        f = js("(function(){var m=document.getElementById('ak-rechte-modal');if(!m)return null;"
               "return {offen:m.classList.contains('open'),opac:getComputedStyle(m).opacity,"
               "n:m.querySelectorAll('.ak-rm-bereich').length};})()")
        check("Fenster geht auf und ist sichtbar", bool(f) and f["offen"] and f["opac"] == "1", str(f))
        check("Fenster zeigt alle acht Bereiche", bool(f) and f["n"] == 8, str(f))
        # Optische Abnahme 2026-11-20, erste Fassung: Speichern stand unter acht
        # Eintraegen ausser Sicht, das Kaestchen bei "Chat" war kleiner.
        g = js("(function(){var m=document.querySelector('#ak-rechte-modal .modal-content');"
               "var s=document.querySelector('#ak-rechte-modal .ak-rm-speichern');if(!m||!s)return null;"
               "var a=m.getBoundingClientRect(),b=s.getBoundingClientRect();"
               "var k=[...document.querySelectorAll('#ak-rechte-modal .ak-rm-bereich')].map(function(c){"
               "var r=c.getBoundingClientRect();return [Math.round(r.width),Math.round(r.height),Math.round(r.left)];});"
               "return {sp:[b.top,b.bottom],m:[a.top,a.bottom],vh:innerHeight,k:k};})()")
        check("Speichern ist ohne Scrollen sichtbar (im Fenster und im Bild)",
              bool(g) and g["sp"][0] >= g["m"][0] and g["sp"][1] <= g["m"][1] and g["sp"][1] <= g["vh"], str(g and g["sp"]))
        check("alle Kaestchen gleich gross und auf einer Linie",
              bool(g) and len({tuple(x) for x in g["k"]}) == 1, str(g and g["k"]))
        bild(f"agent-keys-fenster-{thema}.png", "#ak-rechte-modal .modal-content")
        js("var a=document.querySelector('#ak-rechte-modal .ak-rm-abbrechen'); a && a.click();")
        time.sleep(0.5)
        check("Abbrechen schliesst ohne Speichern", js("!document.getElementById('ak-rechte-modal')"))
finally:
    try:
        ws.close()
    finally:
        p.terminate()

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
