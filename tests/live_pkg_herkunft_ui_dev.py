"""Optische Abnahme: „Wie diese Liste entsteht" im echten Chrome (DEV).

Die Erklaerung ist nur dann eine, wenn sie LESBAR ist – und ob ein langer
`awk`-Einzeiler in einen 1100-px-Kasten passt, sagt kein jsdom-Test und kein
Grep. Gemessen wird deshalb im echten Browser:

  - der Aufklapp-Abschnitt ist da, zugeklappt, und geht auf Klick auf
  - der Befehl steht VOLLSTAENDIG im Kasten (kein waagerechter Ueberlauf,
    keine abgeschnittene Zeile) – er ist der Beleg, ein halber taugt nicht
  - der Kopier-Knopf bleibt neben dem Befehl im Kasten
  - die Tabelle wird nicht weggedrueckt, die Fusszeile nicht hinausgeschoben
  - der Zustand ueberlebt das Tippen in der Suche (der Kasten wird dabei
    komplett neu gebaut – ohne Merker klappte die Erklaerung jedes Mal zu)
  - und beides in HELL und DUNKEL, samt Kontrast des Befehlsblocks
"""
import base64
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
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


PORT, prof = 9347, "/tmp/chrome-pkg-herkunft"
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
        open(datei, "wb").write(base64.b64decode(r["data"]))


try:
    for thema in ("dark", "light"):
        print("\n\033[1mThema '%s'\033[0m" % thema)
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(1)
        js("localStorage.setItem('jarvis_token', %s);"
           "localStorage.setItem('jarvis_theme', %s);" % (json.dumps(TOK), json.dumps(thema)))
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(5)

        js("document.getElementById('jv-pkg-btn').click()")
        time.sleep(5)
        check("[%s] der Kasten steht mit Tabelle" % thema,
              js("!!document.querySelector('.jv-pkg-tab tbody tr')") is True)

        # ── Zugeklappt: der Abschnitt ist da, nimmt aber keinen Platz ──────
        #
        # ⚠ GEMESSEN WIRD DIE HOEHE DES <details>, NICHT DIE DES KINDES. Die
        # erste Fassung dieser Probe fragte `.jv-pkg-wie-in`.offsetHeight und
        # meldete zweimal FAIL, obwohl der Kasten nachweislich richtig aussieht
        # (Screenshot). Grund: Chrome 149 versteckt den Inhalt eines
        # zugeklappten <details> ueber `content-visibility: hidden` am
        # ::details-content – die NACHFAHREN behalten dabei gecachte
        # Layout-Zahlen, `offsetHeight` liefert also weiter einen Wert, obwohl
        # nichts gemalt wird. An einem Minimalbeispiel gegengeprueft: das
        # <details> ist 18 px hoch, sein Kind meldet 136.
        # Register: die EIGENSCHAFT messen, nicht den erstbesten Wert.
        def hoehe():
            return js("(function(){var d=document.querySelector('.jv-pkg-wie');"
                      "return d?Math.round(d.getBoundingClientRect().height):-1;})()")

        zu = js("(function(){var d=document.querySelector('.jv-pkg-wie');"
                "if(!d) return null; var s=d.querySelector('summary');"
                "return {da:true, offen:d.open, text:(s?s.textContent:'').trim()};})()")
        h_zu = hoehe()
        check("[%s] der Abschnitt ist da und zugeklappt" % thema,
              bool(zu and zu["da"] and not zu["offen"]) and 0 < h_zu < 44, (zu, h_zu))
        check("[%s] und traegt seine Beschriftung" % thema,
              bool(zu and len(zu["text"]) > 8), zu)

        # ── Aufklappen und MESSEN ─────────────────────────────────────────
        js("document.querySelector('.jv-pkg-wie > summary').click()")
        time.sleep(1)
        m = js("""(function(){
            var d=document.querySelector('.jv-pkg-wie'),
                inn=d.querySelector('.jv-pkg-wie-in'),
                codes=[].slice.call(d.querySelectorAll('.jv-pkg-cmd')),
                kn=[].slice.call(d.querySelectorAll('.jv-pkg-copy')),
                box=document.querySelector('.jv-pkg-box'),
                fuss=document.querySelector('.jv-pkg-fuss'),
                tab=document.querySelector('.jv-pkg-scroll'),
                rb=box.getBoundingClientRect(), rf=fuss.getBoundingClientRect();
            return {
              offen:d.open,
              anzCode:codes.length,
              // Der Befehl muss VOLLSTAENDIG sichtbar sein - waagerecht
              // abgeschnitten waere er als Beleg wertlos.
              codeUeberlauf:codes.map(function(c){return c.scrollWidth-c.clientWidth;}),
              codeText:codes.map(function(c){return c.textContent.length;}),
              // Der Kopier-Knopf darf nicht aus dem Kasten laufen.
              knopfDrin:kn.every(function(k){var r=k.getBoundingClientRect();
                  return r.right<=rb.right+1 && r.width>0;}),
              anzKnopf:kn.length,
              // Der aufgeklappte Bereich hat einen eigenen Deckel.
              innScrollt:inn.scrollHeight>inn.clientHeight+1,
              innHoehe:Math.round(inn.clientHeight),
              // Die Tabelle darf nicht verschwinden ...
              tabHoehe:Math.round(tab.getBoundingClientRect().height),
              // ... und die Fusszeile nicht aus dem Kasten gedrueckt werden.
              fussDrin:rf.bottom<=rb.bottom+1,
              seiteUeberlauf:document.documentElement.scrollWidth
                             -document.documentElement.clientWidth
            };})()""")
        check("[%s] er klappt auf und zeigt beide Befehle" % thema,
              bool(m and m["offen"] and m["anzCode"] == 2 and m["anzKnopf"] == 2), m)
        # POSITIVKONTROLLE zur Schranke oben: die Messung muss die beiden
        # Zustaende ueberhaupt unterscheiden koennen.
        h_auf = hoehe()
        check("[%s] und wird dabei sichtbar hoeher (%s -> %s px)" % (thema, h_zu, h_auf),
              h_auf > h_zu + 100, (h_zu, h_auf))
        check("[%s] beide Befehle stehen VOLLSTAENDIG im Kasten" % thema,
              bool(m and all(u <= 1 for u in m["codeUeberlauf"])
                   and all(l > 30 for l in m["codeText"])), m)
        check("[%s] die Kopier-Knoepfe bleiben im Kasten" % thema,
              bool(m and m["knopfDrin"]), m)
        check("[%s] die Tabelle wird nicht weggedrueckt" % thema,
              bool(m and m["tabHoehe"] > 120), m)
        check("[%s] die Fusszeile bleibt im Kasten" % thema,
              bool(m and m["fussDrin"]), m)
        check("[%s] kein waagerechter Ueberlauf der Seite" % thema,
              bool(m and m["seiteUeberlauf"] <= 0), m)

        # ── Der Befehl muss auch WIRKLICH der angezeigte sein ──────────────
        txt = js("document.querySelectorAll('.jv-pkg-cmd')[0].textContent")
        check("[%s] der erste Befehl ist der dpkg-Einzeiler" % thema,
              bool(txt and "dpkg-query" in txt and "awk" in txt
                   and "${binary:Summary}" in txt), (txt or "")[:120])

        # ── Lesbarkeit: der Befehl darf nicht in der Flaeche untergehen ────
        kontr = js("""(function(){
            var c=document.querySelector('.jv-pkg-cmd'), s=getComputedStyle(c);
            function rgb(x){var m=x.match(/\\d+/g);return m?m.slice(0,3).map(Number):null;}
            function L(c){return c.map(function(v){v/=255;
              return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);})
              .reduce(function(a,b,i){return a+b*[0.2126,0.7152,0.0722][i];},0);}
            var f=rgb(s.color), b=rgb(s.backgroundColor);
            if(!f||!b) return null;
            var l1=L(f)+0.05, l2=L(b)+0.05;
            return Math.round((Math.max(l1,l2)/Math.min(l1,l2))*100)/100;})()""")
        check("[%s] der Befehlstext ist gut lesbar (Kontrast >= 4.5)" % thema,
              bool(kontr and kontr >= 4.5), kontr)

        # ── ⚠ Der Zustand muss das Neuzeichnen ueberleben ─────────────────
        # `zeichnen()` baut den Kasten bei JEDEM Tastendruck neu auf.
        js("(function(){var s=document.getElementById('jv-pkg-suche');"
           "s.value='bash'; s.dispatchEvent(new Event('input'));})()")
        time.sleep(1)
        nach = js("(function(){var d=document.querySelector('.jv-pkg-wie');"
                  "return {offen:!!(d&&d.open), zeilen:document.querySelectorAll("
                  "'.jv-pkg-tab tbody tr').length};})()")
        check("[%s] die Erklaerung bleibt beim Tippen offen" % thema,
              bool(nach and nach["offen"]), nach)
        check("[%s] und die Suche filtert weiterhin" % thema,
              bool(nach and 0 < nach["zeilen"] < 400), nach)

        schuss("/tmp/pkg_herkunft_%s.png" % thema)

        # ── Sprachwechsel: der Kasten wird neu GERENDERT, nicht neu geholt ─
        if thema == "light":
            js("window.setLang && window.setLang('en')")
            time.sleep(1)
            en = js("(function(){var s=document.querySelector('.jv-pkg-wie > summary');"
                    "return s?s.textContent.trim():'';})()")
            check("[en] die Erklaerung folgt dem Sprachwechsel",
                  bool(en and "How" in en), en)
            schuss("/tmp/pkg_herkunft_en.png")
            js("window.setLang && window.setLang('de')")
finally:
    try: ws.close()
    except Exception: pass
    p.kill()
    time.sleep(1)
    subprocess.run(["rm", "-rf", prof], check=False)

print("\n\033[1m%d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(1 if fail else 0)
