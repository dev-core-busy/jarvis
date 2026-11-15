#!/usr/bin/env python3
"""Optische Abnahme (DEV, echtes Chrome): jeder Inhalt eines Einstellungs-Reiters
steht in einem Container.

Gemeldet 2026-11-15: in mehreren Reitern (MCP, Anweisungen, SAP ab „OData" …)
standen Bereiche frei auf der Seite statt in einem Container wie die uebrigen.

Gemessen wird nach dem ECHTEN Rendern (viele Reiter zeichnet erst ihr Modul):
jeder Reiterknopf wird geklickt, danach wird jedes sichtbare Inhaltselement
(Text, Feld, Knopf, Tabelle, Bild) gesucht, das bis zum Panel hinauf KEINEN
Container-Vorfahren hat. Container ist alles, was als Karte gezeichnet wird:
eigene Flaeche ODER Rahmen, plus abgerundete Ecken (``.kb-section`` und die
Bauformen der Module). Das Kriterium ist die BERECHNETE Darstellung, nicht ein
Klassenname – eine Klassenliste waere am Tag des naechsten Moduls unvollstaendig.
Erlaubt ist die Reiter-Einleitung VOR dem ersten Container; dazwischen und
danach darf nichts lose stehen (Ausnahmen benannt, mit Grund, in ``LOSE``).

Positivkontrolle: im Reiter „Newsfeed" (bekannt richtig) liegt alles in
Containern, und ein absichtlich frei eingefuegter Absatz WIRD gefunden – sonst
Exit 2.

Nur lesend.

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_settings_container_ui_dev.py
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

import websocket

sys.path.insert(0, "/opt/jarvis")
# Optional: Reiternamen -> je Reiter ein ganzseitiges Bildschirmfoto ins HOME
BILDER = sys.argv[1:]
sys.argv = ["x"]
import urllib3  # noqa: E402
urllib3.disable_warnings()
from backend.main import generate_token  # noqa: E402

TOK = generate_token("jarvis")
HOME = os.path.expanduser("~")
PORT, prof = 9367, os.path.join(HOME, ".chrome-settings-container")
subprocess.run(["rm", "-rf", prof], check=False)
log = open(os.path.join(HOME, "chrome-settings-container.log"), "w")
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1400,1000", "--no-first-run",
                      "about:blank"], stdout=log, stderr=log)
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
    r = cmd("Runtime.evaluate", {"expression": code, "returnByValue": True, "awaitPromise": True})
    return (r.get("result") or {}).get("value")


# Lose Elemente eines Panels: sichtbar, mit eigenem Inhalt, ohne Karten-Vorfahren.
LOSE = r"""(function(panelId){
  var panel = document.getElementById(panelId);
  if (!panel) return null;
  function sichtbar(e){ var r=e.getBoundingClientRect(); return r.width>0 && r.height>0
      && getComputedStyle(e).visibility!=='hidden'; }
  function deckend(c){ var m=/rgba?\(([^)]*)\)/.exec(c||''); if(!m) return false;
      var t=m[1].split(','); return t.length<4 || parseFloat(t[3])>0.02; }
  function karte(e){
      if (e.classList.contains('kb-section')) return true;
      var s=getComputedStyle(e);
      var rand = ['Top','Right','Bottom','Left'].filter(function(k){
          return parseFloat(s['border'+k+'Width'])>0 && s['border'+k+'Style']!=='none'; }).length >= 3;
      var flaeche = deckend(s.backgroundColor);
      var rund = parseFloat(s.borderTopLeftRadius) >= 4;
      // Ein Eingabefeld/Knopf hat selbst Rahmen und Radius - er ist Inhalt, keine Karte.
      if (/^(INPUT|SELECT|TEXTAREA|BUTTON|LABEL|A|CODE|SPAN|SUMMARY)$/.test(e.tagName)) return false;
      var r=e.getBoundingClientRect();
      // 24 px: ein ZUGEKLAPPTER Container ist nur so hoch wie sein Kopf (erste
      // Fassung verlangte 40 px und meldete die Protokolle als lose).
      return (rand || flaeche) && rund && r.width >= 240 && r.height >= 24;
  }
  // Die Reiter-Einleitung VOR dem ersten Container ist erlaubt (Beschreibung
  // des Reiters); lose ist alles zwischen und nach den Containern.
  var ersteKarte = null, kandidaten = panel.querySelectorAll('*');
  for (var k=0;k<kandidaten.length;k++){ if (sichtbar(kandidaten[k]) && karte(kandidaten[k])) { ersteKarte = kandidaten[k]; break; } }
  function einleitung(e){ return ersteKarte && !ersteKarte.contains(e)
      && (e.compareDocumentPosition(ersteKarte) & Node.DOCUMENT_POSITION_FOLLOWING); }
  // Benannte Ausnahmen MIT Grund:
  //  btn-tele-refresh - Fusszeilen-Aktion fuer ALLE Protokolle des Reiters;
  //  test_protokolle_ui.js und live_protokolle_ui_dev.py messen sie als Fuss.
  var AUSNAHMEN = ['btn-tele-refresh'];
  function ausnahme(e){ for (var x=e; x && x!==panel; x=x.parentElement){ if (AUSNAHMEN.indexOf(x.id)>=0) return true; } return false; }
  function inKarte(e){ for (var x=e.parentElement; x && x!==panel; x=x.parentElement){ if (karte(x)) return true; } return false; }
  var funde = [];
  var alle = panel.querySelectorAll('*');
  for (var i=0;i<alle.length;i++){
    var e = alle[i];
    if (!sichtbar(e) || karte(e)) continue;
    var traegt = /^(INPUT|SELECT|TEXTAREA|BUTTON|TABLE|IMG|CANVAS|SVG)$/.test(e.tagName.toUpperCase());
    if (!traegt){ for (var c=e.firstChild;c;c=c.nextSibling){ if (c.nodeType===3 && c.textContent.trim()){ traegt=true; break; } } }
    if (!traegt || inKarte(e) || einleitung(e) || ausnahme(e)) continue;
    // Nur das AEUSSERSTE lose Element je Ast melden.
    var x=e.parentElement, schonDa=false;
    while (x && x!==panel){ if (x.hasAttribute('data-lose-probe')) { schonDa=true; break; } x=x.parentElement; }
    if (schonDa) continue;
    // Den obersten Vorfahren unterhalb des Panels als Ortsangabe nehmen.
    var top=e; while (top.parentElement && top.parentElement!==panel) top=top.parentElement;
    // Den FUND markieren, nicht den Ort - sonst verschluckt der erste Fund
    // in einem kb-container alle weiteren darin (erste Fassung, 2026-11-15).
    e.setAttribute('data-lose-probe','1');
    funde.push({tag:e.tagName.toLowerCase(), id:e.id||'', top:(top.id?'#'+top.id:top.tagName.toLowerCase()+'.'+(top.className||'').toString().split(' ')[0]),
                text:(e.innerText||e.value||e.placeholder||'').trim().replace(/\s+/g,' ').slice(0,70)});
  }
  panel.querySelectorAll('[data-lose-probe]').forEach(function(x){ x.removeAttribute('data-lose-probe'); });
  return funde;
})(%s)"""

cmd("Runtime.enable")
cmd("Page.enable")
gesamt = {}
try:
    cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
    time.sleep(2)
    js("localStorage.setItem('jarvis_token', %s); localStorage.setItem('jarvis_theme','dark');" % json.dumps(TOK))
    cmd("Page.navigate", {"url": "https://127.0.0.1/settings"})
    time.sleep(6)
    reiter = js("[...document.querySelectorAll('.settings-tab-btn[data-settings-tab]')]"
                ".filter(b=>getComputedStyle(b).display!=='none').map(b=>b.dataset.settingsTab)") or []

    # Positivkontrolle
    js("document.querySelector('.settings-tab-btn[data-settings-tab=\"newsfeed\"]').click()")
    time.sleep(2)
    sauber = js(LOSE % json.dumps("settings-tab-newsfeed"))
    js("(function(){var q=document.createElement('p');q.id='probe-lose';q.textContent='Probe';"
       "document.getElementById('settings-tab-newsfeed').appendChild(q);})()")
    mit = js(LOSE % json.dumps("settings-tab-newsfeed")) or []
    js("document.getElementById('probe-lose').remove()")
    if sauber is None or sauber or not any(f["id"] == "probe-lose" for f in mit) or len(reiter) < 15:
        print("ABBRUCH: Messaufbau defekt – Newsfeed sauber=%s, Probe gefunden=%s, Reiter=%d"
              % (sauber, [f["id"] for f in mit], len(reiter)))
        sys.exit(2)
    print("Positivkontrolle ok: %d sichtbare Reiter\n" % len(reiter))

    for r in reiter:
        js("document.querySelector('.settings-tab-btn[data-settings-tab=\"%s\"]').click()" % r)
        time.sleep(2.5)
        # Klapp-Abschnitte oeffnen, damit auch ihr Inhalt gemessen wird
        js("document.querySelectorAll('#settings-tab-%s details').forEach(d=>d.open=true);"
           "document.querySelectorAll('#settings-tab-%s .kb-collapse-body').forEach(b=>{b.style.display='';});" % (r, r))
        time.sleep(0.5)
        funde = js(LOSE % json.dumps("settings-tab-" + r)) or []
        if r in BILDER or "alle" in BILDER:
            import base64
            # Das Panel liegt in einem rollenden Dialog: fuer das Bild alle
            # Vorfahren auf volle Hoehe stellen (nur in dieser Wegwerf-Sitzung).
            hoehe = js("(function(){var e=document.getElementById('settings-tab-%s');"
                       "for(var x=e.parentElement;x&&x!==document.documentElement;x=x.parentElement){"
                       "x.style.maxHeight='none';x.style.height='auto';x.style.overflow='visible';"
                       "if(getComputedStyle(x).position==='fixed')x.style.position='absolute';}"
                       "return Math.ceil(document.documentElement.scrollHeight);})()" % r) or 1000
            cmd("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": int(hoehe),
                "deviceScaleFactor": 1, "mobile": False})
            time.sleep(0.8)
            bild = cmd("Page.captureScreenshot", {"format": "png"}).get("data", "")
            with open(os.path.join(HOME, "settings-container-%s.png" % r), "wb") as fh:
                fh.write(base64.b64decode(bild))
            cmd("Emulation.clearDeviceMetricsOverride")
            cmd("Page.reload")
            time.sleep(6)
        gesamt[r] = funde
        print("%-20s %s" % (r, "ok" if not funde else "%d lose" % len(funde)))
        for f in funde:
            print("    %-28s <%s%s> %s" % (f["top"][:28], f["tag"], ("#" + f["id"]) if f["id"] else "", f["text"]))
finally:
    try:
        p.kill()
    except Exception:  # noqa: BLE001
        pass

fehl = sum(1 for v in gesamt.values() if v)
print("\nErgebnis: %d Reiter ok, %d mit losen Inhalten" % (len(gesamt) - fehl, fehl))
sys.exit(1 if fehl else 0)
