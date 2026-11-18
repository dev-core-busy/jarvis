"""Optische Abnahme: Popups der Kopfzeile liegen OBEN (DEV, echter Chrome).

WARUM (gemeldet 2026-11-18): das Popup der Update-Pill und "Angemeldete
Benutzer" lagen in Einstellungen -> Sicherheit -> Berechtigungen teilweise
HINTER Kaestchen und Feldern. Ursache: `view-transition-name` (theme.css) macht
die Kopfzeile zu einem eigenen Stapelkontext; ohne z-index lag sie auf Ebene 0,
und spaetere Inhalte mit eigener Ebene (.form-group mit transform aus der
fadeIn-Animation) wurden darueber gemalt. Ein z-index am Popup hilft dagegen
nicht – er wirkt nur innerhalb der Leiste. jsdom rechnet kein Layout; das ist
nur im Browser messbar.

Gemessen je Popup ueber ein Raster von Punkten: `elementFromPoint` muss das
Popup selbst (oder ein Kind) liefern.
  - Positivkontrolle: Popup ist offen und hat eine Flaeche (sonst Exit 2).
  - Gegenkontrolle: dieselbe Messung mit z-index:auto an der Leiste MUSS
    Verdeckung finden – sonst misst die Probe nichts (Exit 2).
Nur lesend (eingefuegtes Stylesheet wird wieder entfernt, nichts gespeichert).

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_kopfzeile_popups_ui_dev.py
"""
import json
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
import urllib3  # noqa: E402
urllib3.disable_warnings()
from backend.main import generate_token  # noqa: E402

TOK = generate_token("jarvis")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


def abbruch(text):
    print("ABBRUCH (Exit 2): " + text)
    raise SystemExit(2)


PORT = 9361
prof = tempfile.mkdtemp(prefix="chrome-kopf-popups-")
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--disable-gpu", "--remote-allow-origins=*", "--window-size=1400,900",
                      "--no-first-run", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)
n = [0]
ws = None


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


# Anteil verdeckter Rasterpunkte eines offenen Popups; null = Popup zu/ohne Flaeche
ZAEHLE = r"""(function(sel){var dd=document.querySelector(sel); if(!dd) return null;
  var r=dd.getBoundingClientRect(); if(r.width<50||r.height<50||getComputedStyle(dd).display==='none') return null;
  var n=0,p=0,wer={};
  for(var y=r.top+4;y<r.bottom-2;y+=10) for(var x=r.left+4;x<r.right-2;x+=16){
    if(x<0||y<0||x>innerWidth||y>innerHeight) continue; p++;
    var e=document.elementFromPoint(x,y); if(e&&!dd.contains(e)){n++; var k=e.tagName.toLowerCase()+(e.id?'#'+e.id:''); wer[k]=(wer[k]||0)+1;}}
  return {verdeckt:n, punkte:p, wer:wer};})"""

OEFFNEN = {
    "#update-dropdown": "document.getElementById('version-pill').click()",
    "#pt-usr-panel": "document.getElementById('pt-usr-btn').click()",
}


def messen(ort, leiste, popups):
    for sel in popups:
        # alles schliessen, dann genau dieses Popup oeffnen
        # Jedes Popup auf SEINE Art schliessen: Update ueber die Klasse "hidden",
        # Benutzer ueber das hidden-ATTRIBUT (sessions.js) – eine Klasse dort
        # bliebe stehen und hielte das Panel beim Oeffnen zu.
        js("var d=document.getElementById('update-dropdown'); if(d) d.classList.add('hidden');"
           "var u=document.getElementById('pt-usr-panel'); if(u) u.setAttribute('hidden','');")
        time.sleep(0.5)
        js(OEFFNEN[sel]); time.sleep(2)
        m = js(ZAEHLE + "('%s')" % sel)
        if not m or m["punkte"] < 50:
            abbruch("%s: Popup %s nicht offen oder ohne Flaeche (%s)" % (ort, sel, m))
        check("%s: %s liegt oben (%d/%d Punkte verdeckt)" % (ort, sel, m["verdeckt"], m["punkte"]),
              m["verdeckt"] == 0, m["wer"])
        # Gegenkontrolle: ohne z-index an der Leiste muss die Probe den Fehler sehen
        js("var st=document.createElement('style');st.id='gegenprobe';st.textContent='%s{z-index:auto!important}';"
           "document.head.appendChild(st);" % leiste)
        time.sleep(0.3)
        g = js(ZAEHLE + "('%s')" % sel)
        js("var s=document.getElementById('gegenprobe'); if(s) s.remove();")
        if not g or g["verdeckt"] == 0:
            abbruch("%s: Gegenkontrolle sieht ohne z-index keine Verdeckung (%s) – Probe misst nichts" % (ort, g))
        print("    (Gegenkontrolle ohne z-index: %d/%d verdeckt)" % (g["verdeckt"], g["punkte"]))


try:
    try:
        tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
    except Exception as e:  # noqa: BLE001
        abbruch("kein CDP (%s)" % e)
    ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
    cmd("Page.navigate", {"url": "https://127.0.0.1/portal"}); time.sleep(1)
    js("localStorage.setItem('jarvis_token', %s)" % json.dumps(TOK))

    print("\n\033[1mEinstellungen -> Sicherheit -> Berechtigungen\033[0m")
    cmd("Page.navigate", {"url": "https://127.0.0.1/settings"}); time.sleep(6)
    js("document.querySelector('.settings-tab-btn[data-settings-tab=\"security\"]').click()"); time.sleep(2)
    js("(function(){var h=document.getElementById('sec-sect-ad-hdr'); if(h&&h.classList.contains('is-collapsed')) h.click();"
       "[].slice.call(document.querySelectorAll('#sec-sect-ad-body details')).forEach(function(d){d.open=true;});"
       "var b=document.getElementById('sec-sect-ad-body'); if(b) b.scrollIntoView({block:'start'});})()"); time.sleep(2)
    if not js("document.querySelectorAll('#sec-sect-ad-body input[type=checkbox]').length > 0"):
        abbruch("Berechtigungen nicht aufgeklappt – Messung nicht deutbar")
    messen("Einstellungen", "#settings-modal .modal-header", ["#update-dropdown", "#pt-usr-panel"])

    print("\n\033[1m/chat\033[0m")
    cmd("Page.navigate", {"url": "https://127.0.0.1/chat"}); time.sleep(6)
    messen("/chat", ".chat-main > header.topbar", ["#update-dropdown"])
finally:
    try:
        if ws:
            ws.close()
    except Exception:  # noqa: BLE001
        pass
    p.kill()
    subprocess.run(["rm", "-rf", prof], check=False)

print("\n\033[1m%d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(1 if fail else 0)
