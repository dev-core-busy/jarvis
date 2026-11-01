#!/usr/bin/env python3
"""Optische Abnahme (DEV, echtes Chrome): Container-Titel werden beim Ueberfahren
in der Akzentfarbe gezeigt – auf jeder Seite mit Klapp-Containern, hell und dunkel.

jsdom kennt ``:hover`` nicht; hier wird der Zustand per CDP erzwungen
(``CSS.forcePseudoState``) und die BERECHNETE Farbe des Titels gemessen – gegen
``--accent`` der Seite und gegen die Flaeche dahinter (Kontrast).
Positivkontrolle je Seite: ohne Hover hat der Titel eine ANDERE Farbe (sonst
waere die Messung trivial wahr).

Nur lesend. Seiten, die fuer den Probe-Benutzer nicht erreichbar sind (Bereich
aus, keine Freigabe), werden als NICHT GEMESSEN genannt, nicht als bestanden.

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_container_akzent_ui_dev.py [benutzer]

``benutzer``: ein Konto MIT den Bereichsfreigaben (E-Mail, SAP, …) – die
Freigaben kennen bewusst keinen Admin-Bypass, ``jarvis`` wird dort umgeleitet.
Container, die erst ein Dialog bzw. eine Freigabe sichtbar macht (/chat:
Einstellungsdialog, /claude: App-Flaeche), macht die Probe per Skript sichtbar –
gemessen wird die FARBE der Regel, nicht der Zugang; das steht in der Ausgabe.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

import websocket

sys.path.insert(0, "/opt/jarvis")
BENUTZER = sys.argv[1] if len(sys.argv) > 1 else "jarvis"
sys.argv = ["x"]
import urllib3  # noqa: E402
urllib3.disable_warnings()
from backend.main import generate_token  # noqa: E402

TOK = generate_token(BENUTZER)
HOME = os.path.expanduser("~")
SEITEN = ["/wissensgraph", "/settings", "/email", "/tracks", "/claude", "/sap", "/vemas",
          "/jira-addon", "/confluence-addon", "/chat", "/feedback", "/ai-mouse"]
KOEPFE = [".ja-card-head", ".em-card-head", ".st-card-head", ".cs-card-head", ".kb-collapse-header"]
ABSCHNITTE = [".ja-sect > summary", ".sp-sect > summary", ".vm-sect > summary",
              ".chs-sect > summary", ".sec-sub > summary"]
# Sichtbar machen, was erst ein Dialog/eine Freigabe zeigt (nur fuer die Farbmessung).
VORBEREITEN = {
    "/chat": "(function(){var m=document.getElementById('chat-settings-modal');if(!m)return false;"
             "m.classList.remove('hidden');m.classList.add('open');return true;})()",
    "/claude": "(function(){var a=document.getElementById('cs-app');if(!a)return false;"
               "a.classList.remove('hidden');return true;})()",
}
ok = fail = 0
nicht = []


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % str(detail)) if detail else ""))


PORT, prof = 9363, os.path.join(HOME, ".chrome-container-akzent")
subprocess.run(["rm", "-rf", prof], check=False)
log = open(os.path.join(HOME, "chrome-container-akzent.log"), "w")
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1400,1000", "--no-first-run", "about:blank"],
                     stdout=log, stderr=log)
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


def leuchte(rgb):
    def k(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * k(r) + 0.7152 * k(g) + 0.0722 * k(b)


def kontrast(a, b):
    la, lb = sorted([leuchte(a), leuchte(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


SUCHE = """(function(koepfe, abschnitte){
  function sichtbar(e){ var r=e.getBoundingClientRect(); return r.width>0 && r.height>0; }
  var alle = koepfe.map(function(s){return [s,'kopf'];}).concat(abschnitte.map(function(s){return [s,'abschnitt'];}));
  for (var i=0;i<alle.length;i++){
    var liste = document.querySelectorAll(alle[i][0]);
    for (var j=0;j<liste.length;j++){
      var e = liste[j];
      if (!sichtbar(e)) continue;
      var titel = alle[i][1]==='kopf' ? e.querySelector(':scope > h1, :scope > h2, :scope > h3, :scope > h4') : e;
      if (!titel) continue;
      e.setAttribute('data-akzent-probe','1');
      titel.setAttribute('data-akzent-titel','1');
      return {sel: alle[i][0], text: (titel.textContent||'').trim().slice(0,40)};
    }
  }
  return null;
})(%s, %s)""" % (json.dumps(KOEPFE), json.dumps(ABSCHNITTE))

FARBEN = """(function(){
  var t=document.querySelector('[data-akzent-titel]');
  var p=document.createElement('span'); p.style.color='var(--accent)'; document.body.appendChild(p);
  var akz=getComputedStyle(p).color; p.remove();
  var e=t, bg='';
  // Durchscheinende Flaechen (Hover-Toenung rgba(…, 0.04)) sind KEIN Hintergrund –
  // die erste Sonde nahm sie als deckend und meldete 2,66:1 (Messfehler).
  while(e){ var c=getComputedStyle(e).backgroundColor; var m=/rgba?\\(([^)]*)\\)/.exec(c||'');
            var teile=m?m[1].split(','):[]; var alpha=teile.length>3?parseFloat(teile[3]):1;
            if(c && c!=='transparent' && alpha>=0.5){bg=c;break;} e=e.parentElement; }
  return {farbe:getComputedStyle(t).color, akzent:akz, grund:bg||getComputedStyle(document.body).backgroundColor};
})()"""


def rgb(s):
    """``rgb(r, g, b)`` ODER ``color(srgb r g b)`` – Chrome meldet ``color-mix``
    in der zweiten Form mit Anteilen 0..1 (erste Fassung las sie als 0..255
    und meldete 1,00:1 fuer eine Farbe, die exakt stimmte)."""
    import re
    z = [float(x) for x in re.findall(r"[\d.]+", (s or "").replace("srgb", ""))[:3]]
    if len(z) != 3:
        return None
    return [round(c * 255) for c in z] if (s or "").strip().startswith("color(") else z


cmd("Runtime.enable")
cmd("Page.enable")
cmd("DOM.enable")
cmd("CSS.enable")
try:
    for thema in ("dark", "light"):
        print("\n\033[1mThema '%s'\033[0m" % thema)
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(2)
        js("localStorage.setItem('jarvis_token', %s); localStorage.setItem('jarvis_theme', %s);"
           % (json.dumps(TOK), json.dumps(thema)))
        for seite in SEITEN:
            cmd("Page.navigate", {"url": "https://127.0.0.1" + seite})
            time.sleep(4)
            pfad = js("location.pathname")
            vorbereitet = js(VORBEREITEN[seite]) if seite in VORBEREITEN else False
            time.sleep(0.5 if vorbereitet else 0)
            fund = js(SUCHE)
            if pfad != seite or not fund:
                nicht.append("%s/%s (%s)" % (thema, seite, "umgeleitet nach " + str(pfad) if pfad != seite else "kein sichtbarer Container"))
                continue
            vorher = js(FARBEN)
            doc = cmd("DOM.getDocument", {"depth": 0})
            nid = cmd("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": "[data-akzent-probe]"}).get("nodeId")
            cmd("CSS.forcePseudoState", {"nodeId": nid, "forcedPseudoClasses": ["hover"]})
            time.sleep(0.3)
            nach = js(FARBEN)
            cmd("CSS.forcePseudoState", {"nodeId": nid, "forcedPseudoClasses": []})
            name = "[%s] %s %s „%s“%s" % (thema, seite, fund["sel"], fund["text"].split("\n")[0],
                                           " (per Skript sichtbar)" if vorbereitet else "")
            gleich_vorher = rgb(vorher["farbe"]) == rgb(vorher["akzent"])
            check(name + ": Positivkontrolle – ohne Hover NICHT in Akzentfarbe", not gleich_vorher, vorher)
            # Sollwert UNABHAENGIG von der CSS-Regel aus --accent gerechnet: hell pur,
            # dunkel 65 % Akzent + 35 % Weiss (gemessene Lesbarkeitsgrenze).
            akz = rgb(nach["akzent"])
            soll = akz if thema == "light" else [round(c * 0.65 + 255 * 0.35) for c in akz]
            ist = rgb(nach["farbe"])
            check(name + ": beim Ueberfahren in der Akzentfarbe (soll %s)" % soll,
                  bool(ist) and all(abs(a - b) <= 2 for a, b in zip(ist, soll)), nach)
            kv = kontrast(rgb(nach["farbe"]), rgb(nach["grund"])) if rgb(nach["grund"]) else 0
            # Titel sind 1 rem und fett, also NICHT "grosse Schrift" im WCAG-Sinn –
            # Grenze 4,5:1. (Die erste Fassung prueste 3:1 und haette das Haus-Rot
            # auf dunklem Grund mit 3,15:1 durchgewunken.)
            check(name + ": lesbar (Kontrast %.2f:1)" % kv, kv >= 4.5, nach)
finally:
    try:
        p.kill()
    except Exception:  # noqa: BLE001
        pass

if nicht:
    print("\nNICHT GEMESSEN (nicht bestanden, nur nicht erreichbar):")
    for x in nicht:
        print("  - " + x)
print("\nErgebnis: %d ok, %d fehlgeschlagen" % (ok, fail))
sys.exit(1 if fail else 0)
