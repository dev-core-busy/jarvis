"""Optische Abnahme des Paket-Kastens im echten Chrome (DEV), hell und dunkel.

jsdom rechnet KEIN Layout: Ueberlappung, Breite, ein aus dem Kasten gedruecktes
Bedienelement und ein waagerechter Ueberlauf sind nur mit einem echten Browser
zu sehen (Register). Zusaetzlich wird hier GEMESSEN, was ein Quelltext-Grep
nicht beweist:

  - der Knopf steht wirklich RECHTS NEBEN der CPU-Anzeige (Koordinaten)
  - er ist fuer einen Nicht-Admin NICHT DA (nicht nur ausgeblendet)
  - der Kasten deckt wirklich ab (Deckkraft der Flaeche gemessen)
  - der Tabellenkopf klebt beim Scrollen (Position nach dem Scrollen)
  - nichts laeuft waagerecht ueber, und die Fusszeile bleibt im Kasten
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
TOK_USER = generate_token("nexus\\testnutzer")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


PORT, prof = 9341, "/tmp/chrome-pkg-ui"
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
    # ── Nicht-Admin: der Knopf darf gar nicht erst entstehen ───────────────
    print("\n\033[1m1. Als Nicht-Administrator\033[0m")
    cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
    time.sleep(2)
    js("localStorage.setItem('jarvis_token', %s);" % json.dumps(TOK_USER))
    cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
    time.sleep(4)
    check("der ⓘ-Knopf entsteht fuer einen Nicht-Admin gar nicht",
          js("!document.getElementById('jv-pkg-btn')") is True)

    for thema in ("dark", "light"):
        print("\n\033[1m2. Als Administrator, Thema '%s'\033[0m" % thema)
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(1)
        js("localStorage.setItem('jarvis_token', %s);"
           "localStorage.setItem('jarvis_theme', %s);" % (json.dumps(TOK), json.dumps(thema)))
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(5)

        check("[%s] Thema gesetzt" % thema,
              js("document.body.classList.contains('light')") == (thema == "light"))
        check("[%s] der ⓘ-Knopf ist da und sichtbar" % thema,
              js("(function(){var b=document.getElementById('jv-pkg-btn');"
                 "return !!b && b.offsetWidth>0 && b.offsetHeight>0;})()") is True)

        # ⚠ Die Vorgabe lautet "rechts von CPU Auslastung" - das ist eine
        # Koordinatenaussage, keine Markup-Aussage.
        lage = js("(function(){var c=document.getElementById('cpu-bar'),"
                  "b=document.getElementById('jv-pkg-btn');"
                  "if(!c||!b) return null; var rc=c.getBoundingClientRect(),"
                  "rb=b.getBoundingClientRect();"
                  "return {links:rb.left>=rc.right-1, luecke:Math.round(rb.left-rc.right),"
                  "gleicheZeile:Math.abs((rb.top+rb.height/2)-(rc.top+rc.height/2))<12};})()")
        check("[%s] der Knopf steht RECHTS neben der CPU-Anzeige" % thema,
              bool(lage and lage["links"]), lage)
        check("[%s] und in derselben Zeile, mit knappem Abstand" % thema,
              bool(lage and lage["gleicheZeile"] and 0 <= lage["luecke"] <= 14), lage)
        # Der Knopf darf NICHT in der rechten Symbolgruppe landen - deren
        # Reihenfolge ist projektweit festgeschrieben.
        check("[%s] er sitzt nicht in der rechten Symbolgruppe" % thema,
              js("!document.querySelector('.pt-top-icons #jv-pkg-btn')") is True)

        # ── Kasten oeffnen ────────────────────────────────────────────────
        js("document.getElementById('jv-pkg-btn').click()")
        time.sleep(4)
        check("[%s] der Kasten geht auf" % thema,
              js("!!document.querySelector('.jv-pkg-overlay.an')") is True)
        anz = js("document.querySelectorAll('.jv-pkg-tab tbody tr').length")
        check("[%s] die Tabelle ist gefuellt" % thema, (anz or 0) > 50, anz)
        check("[%s] die Kopfzeile nennt Anzahl und Groesse" % thema,
              "Pakete" in (js("document.querySelector('.jv-pkg-meta').textContent") or ""),
              js("document.querySelector('.jv-pkg-meta').textContent"))
        # Die Restzahl MUSS dastehen - sonst haelt der Leser die gekuerzte
        # Liste fuer den ganzen Bestand.
        check("[%s] die Fusszeile nennt die nicht gezeigten Pakete" % thema,
              "weitere" in (js("document.querySelector('.jv-pkg-fuss').textContent") or ""),
              js("document.querySelector('.jv-pkg-fuss').textContent")[:80])

        # DECKENDE Flaeche: darunter liegen die Portal-Karten mit Text.
        deck = js("(function(){var s=getComputedStyle(document.querySelector('.jv-pkg-box'));"
                  "return s.backgroundColor;})()")
        check("[%s] der Kasten hat eine DECKENDE Flaeche" % thema,
              bool(deck) and "rgba" not in deck, deck)

        # Nichts laeuft ueber, und die Fusszeile bleibt IM Kasten.
        masse = js("(function(){var b=document.querySelector('.jv-pkg-box'),"
                   "f=document.querySelector('.jv-pkg-fuss');"
                   "var rb=b.getBoundingClientRect(), rf=f.getBoundingClientRect();"
                   "return {imKasten: rf.bottom<=rb.bottom+1, quer:"
                   "document.documentElement.scrollWidth<=window.innerWidth+1,"
                   "boxQuer: b.scrollWidth<=b.clientWidth+1};})()")
        check("[%s] die Fusszeile steht IM Kasten (min-height:0 wirkt)" % thema,
              bool(masse and masse["imKasten"]), masse)
        check("[%s] kein waagerechter Ueberlauf" % thema,
              bool(masse and masse["quer"] and masse["boxQuer"]), masse)

        # Der Tabellenkopf klebt - gemessen NACH dem Scrollen.
        kleb = js("(function(){var s=document.querySelector('.jv-pkg-scroll');"
                  "s.scrollTop=600; var th=s.querySelector('thead th');"
                  "var r=th.getBoundingClientRect(), rs=s.getBoundingClientRect();"
                  "return Math.abs(r.top-rs.top)<3;})()")
        check("[%s] der Tabellenkopf bleibt beim Scrollen stehen" % thema, kleb is True)
        js("document.querySelector('.jv-pkg-scroll').scrollTop=0")

        # Suche
        js("var s=document.getElementById('jv-pkg-suche'); s.value='python3';"
           "s.dispatchEvent(new Event('input'));")
        time.sleep(0.6)
        gef = js("document.querySelectorAll('.jv-pkg-tab tbody tr').length")
        check("[%s] die Suche filtert" % thema, 0 < (gef or 0) < (anz or 0), (gef, anz))
        check("[%s] und findet nur Passendes" % thema,
              js("Array.from(document.querySelectorAll('.jv-pkg-tab tbody tr'))"
                 ".every(function(r){return r.textContent.toLowerCase().indexOf('python3')>=0;})")
              is True)
        js("var s=document.getElementById('jv-pkg-suche'); s.value='';"
           "s.dispatchEvent(new Event('input'));")
        time.sleep(0.5)

        # Sortieren nach Groesse: der groesste Eintrag muss nach oben.
        js("Array.from(document.querySelectorAll('.jv-pkg-tab th'))"
           ".find(function(h){return h.dataset.sort==='size_kb';}).click()")
        time.sleep(0.5)
        check("[%s] Sortieren nach Groesse beginnt beim groessten" % thema,
              js("(function(){var t=document.querySelectorAll('.jv-pkg-tab tbody .jv-pkg-r');"
                 "return /GiB|MiB/.test(t[0].textContent);})()") is True,
              js("document.querySelector('.jv-pkg-tab tbody .jv-pkg-r').textContent"))

        # ── Download: GEMESSEN, nicht geglaubt ────────────────────────────
        # Ein `<a href>` kann keinen Authorization-Header setzen; der Link
        # braeuchte `?token=` und das Sitzungstoken stuende in der Adresszeile,
        # im Verlauf und in jedem Proxy-Log. Der Blob umgeht das - also wird
        # nachgesehen, dass wirklich ein Blob entsteht und der Dateiname sitzt.
        js("window.__dl=null; window.__blob=null;"
           "var echt=URL.createObjectURL;"
           "URL.createObjectURL=function(b){window.__blob=b; return echt(b);};"
           "var klick=HTMLAnchorElement.prototype.click;"
           "HTMLAnchorElement.prototype.click=function(){"
           "  window.__dl={name:this.download, href:this.href};};")
        js("document.querySelector('.jv-pkg-dl').click()")
        time.sleep(0.6)
        dl = js("window.__dl")
        check("[%s] der Download loest wirklich aus" % thema, bool(dl), dl)
        check("[%s] mit Host und Zeitpunkt im Dateinamen" % thema,
              bool(dl) and dl["name"].endswith(".json") and "pakete_" in dl["name"], dl)
        check("[%s] ueber einen blob:, NICHT ueber eine URL mit Token" % thema,
              bool(dl) and dl["href"].startswith("blob:") and "token" not in dl["href"], dl)
        groesse = js("window.__blob ? window.__blob.size : 0")
        typ = js("window.__blob ? window.__blob.type : ''")
        check("[%s] der Blob ist JSON und nicht leer" % thema,
              typ == "application/json" and (groesse or 0) > 10000, (typ, groesse))
        # Der Inhalt muss der Bericht sein - nicht irgendetwas.
        inhalt = js("(function(){return window.__blob ? window.__blob.text() : '';})()")
        check("[%s] und enthaelt den vollstaendigen Bericht" % thema,
              bool(inhalt) and '"pakete"' in inhalt and '"erzeugt_am"' in inhalt,
              (inhalt or "")[:80])

        schuss("/tmp/pkg_%s.png" % thema)

        # Schliessen
        js("document.querySelector('.jv-pkg-close').click()")
        time.sleep(0.5)
        check("[%s] × schliesst den Kasten" % thema,
              js("!document.querySelector('.jv-pkg-overlay.an')") is True)
        js("document.getElementById('jv-pkg-btn').click()")
        time.sleep(3)
        js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))")
        time.sleep(0.4)
        check("[%s] Escape schliesst ihn ebenfalls" % thema,
              js("!document.querySelector('.jv-pkg-overlay.an')") is True)

    print("\n\033[1m3. Sprachwechsel\033[0m")
    js("window.setLang && window.setLang('en')")
    time.sleep(0.8)
    check("der Knopf-Titel folgt der Sprache",
          "Installed" in (js("document.getElementById('jv-pkg-btn').title") or ""),
          js("document.getElementById('jv-pkg-btn').title"))
    js("window.setLang && window.setLang('de')")
finally:
    try: ws.close()
    except Exception: pass
    p.kill()
    # ⚠ Ein Aufraeumschritt darf das Ergebnis nicht kippen (Register): Chrome
    # schreibt nach kill() noch, `rm -rf` liefe sonst in ENOTEMPTY.
    time.sleep(1)
    subprocess.run(["rm", "-rf", prof], check=False)

print("\n\033[1m%d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(1 if fail else 0)
