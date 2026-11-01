#!/usr/bin/env python3
"""Optische Abnahme /wissensgraph im echten Chrome (DEV), hell und dunkel.

Gemessen, was jsdom nicht kann (kein Layout, kein WebGL, keine Worker):
  - die Grafik wird wirklich gezeichnet (WebGL 2 ueber SwiftShader, Renderer da,
    sichtbare Bildpunkte in der Flaeche, die Anordnung lief und wurde gemerkt)
  - Hover dimmt alles ausser dem Knoten und seinen Nachbarn
  - Klick oeffnet das Detail, Suche hebt hervor, Faerbung schaltet um
  - kein waagerechter Ueberlauf bei 1400 und 520 px, Legende lesbar (Kontrast)
  - keine Skriptfehler in der Konsole
Nur lesend: es wird nichts zusammengefuehrt, geloescht oder neu aufgebaut.
Die Bilder liegen danach im HOME des Dienstbenutzers (nicht in /tmp, Register).

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_wissensgraph_ui_dev.py
"""
import base64
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

import websocket

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
import urllib3  # noqa: E402
urllib3.disable_warnings()
from backend.main import generate_token  # noqa: E402

TOK = generate_token("jarvis")
HOME = os.path.expanduser("~")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        # str(): ein Tupel als Formatargument wirft – und ein Waechter, der beim
        # Melden abstuerzt, endet ohne Bilanz (Register).
        print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % str(detail)) if detail else ""))


PORT, prof = 9361, os.path.join(HOME, ".chrome-wissensgraph-ui")
subprocess.run(["rm", "-rf", prof], check=False)
log = open(os.path.join(HOME, "chrome-wissensgraph-ui.log"), "w")
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1400,1000", "--no-first-run",
                      "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "about:blank"],
                     stdout=log, stderr=log)
time.sleep(6)
tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
n = [0]
fehler = []


def cmd(m, params=None):
    n[0] += 1
    ws.send(json.dumps({"id": n[0], "method": m, "params": params or {}}))
    while True:
        d = json.loads(ws.recv())
        if d.get("method") == "Runtime.exceptionThrown":
            fehler.append(d["params"]["exceptionDetails"].get("text", "") + " " +
                          str((d["params"]["exceptionDetails"].get("exception") or {}).get("description", ""))[:1500])
        if d.get("method") == "Runtime.consoleAPICalled" and d["params"].get("type") == "error":
            fehler.append(" ".join(str(a.get("value", a.get("description", ""))) for a in d["params"].get("args", []))[:200])
        if d.get("id") == n[0]:
            return d.get("result", {})


def js(code):
    r = cmd("Runtime.evaluate", {"expression": code, "returnByValue": True, "awaitPromise": True})
    return (r.get("result") or {}).get("value")


def bild(datei, clip=None):
    par = {"format": "png"}
    if clip:
        par["clip"] = dict(clip, scale=1)
    r = cmd("Page.captureScreenshot", par)
    daten = base64.b64decode(r.get("data") or b"")
    if datei:
        open(datei, "wb").write(daten)
    return daten


def leuchte(rgb):
    def k(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * k(r) + 0.7152 * k(g) + 0.0722 * k(b)


def kontrast(a, b):
    la, lb = sorted([leuchte(a), leuchte(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def maus(art, x, y):
    cmd("Input.dispatchMouseEvent", {"type": art, "x": x, "y": y, "button": "left", "clickCount": 1})


cmd("Runtime.enable")
cmd("Page.enable")
try:
    from PIL import Image
    for thema in ("dark", "light"):
        print("\n\033[1mThema '%s'\033[0m" % thema)
        cmd("Emulation.clearDeviceMetricsOverride")
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(2)
        js("localStorage.setItem('jarvis_token', %s); localStorage.setItem('jarvis_theme', %s);"
           "localStorage.removeItem('jarvis_wg_pos');" % (json.dumps(TOK), json.dumps(thema)))
        cmd("Page.navigate", {"url": "https://127.0.0.1/wissensgraph"})
        time.sleep(4)
        bereit = False
        for _ in range(30):
            st = js("(function(){var W=window.WissensgraphIntern;var a=document.getElementById('wg-app');"
                    "return {sichtbar:!!a&&!a.classList.contains('hidden'),"
                    "knoten:W&&W.graph()?W.graph().order:0,renderer:!!(W&&W.renderer()),"
                    "pos:Object.keys(JSON.parse(localStorage.getItem('jarvis_wg_pos')||'{}')).length};})()")
            if st and st.get("pos"):
                bereit = True
                break
            time.sleep(1)
        check("[%s] Positivkontrolle: Seite sichtbar und Graph geladen" % thema,
              bool(st and st.get("sichtbar") and st.get("knoten")), st)
        if not (st and st.get("sichtbar") and st.get("knoten")):
            print("ABBRUCH – Seite nicht aufgebaut, Folgepruefungen nicht deutbar")
            sys.exit(2)
        check("[%s] WebGL 2 und Renderer vorhanden" % thema,
              js("window.WissensgraphIntern.grafikMoeglich()") is True and st.get("renderer"), st)
        check("[%s] Anordnung lief und wurde gemerkt (Positions-Cache)" % thema, bereit, st)
        time.sleep(1.5)
        # WIRKUNG der Faerbung: grau ueberall waere "kein Befund" fuer jede
        # Pruefung auf Dimmen/Hervorheben – deshalb zuerst die Vielfalt.
        farb = js("(function(){var W=window.WissensgraphIntern,G=W.graph(),R=W.renderer(),s={};"
                  "G.forEachNode(function(n){var d=R.getNodeDisplayData(n);if(d&&d.color)s[d.color]=1;});"
                  "return Object.keys(s).length;})()")
        check("[%s] Faerbung nach Art: mindestens drei Knotenfarben (%s)" % (thema, farb), (farb or 0) >= 3, farb)
        # sigma 4: die Beschriftungsfarbe steht in den ANZEIGEDATEN je Knoten.
        lab = js("(function(){var W=window.WissensgraphIntern,G=W.graph(),R=W.renderer(),f={};"
                 "G.forEachNode(function(n){var d=R.getNodeDisplayData(n);f[String(d&&d.labelColor)]=1;});"
                 "return {ist:Object.keys(f),"
                 "soll:getComputedStyle(document.body).getPropertyValue('--text-primary').trim()};})()") or {}
        check("[%s] Beschriftung in der Textfarbe des Themas" % thema,
              bool(lab.get("soll")) and lab.get("ist") == [lab.get("soll")], lab)
        verb = js("(function(){function d(id){return getComputedStyle(document.getElementById(id)).display;}"
                  "return {detail:d('wg-detail'),hinweis:document.getElementById('wg-hinweis').classList.contains('hidden')?d('wg-hinweis'):'(gezeigt)'};})()")
        check("[%s] Verborgenes ist wirklich unsichtbar (Detail, leerer Hinweis)" % thema,
              verb["detail"] == "none" and verb["hinweis"] in ("none", "(gezeigt)"), verb)
        hinweis = js("(function(){var h=document.getElementById('wg-hinweis');"
                     "return h.classList.contains('hidden')?'':h.textContent;})()")
        check("[%s] keine Fehlermeldung ueber der Grafik" % thema, not hinweis, hinweis)
        rect = js("(function(){var r=document.getElementById('wg-graph').getBoundingClientRect();"
                  "return {x:r.left+scrollX,y:r.top+scrollY,w:r.width,h:r.height,vx:r.left,vy:r.top};})()")
        png = bild(os.path.join(HOME, "wissensgraph_%s.png" % thema))
        img = Image.open(io.BytesIO(png)).convert("RGB")
        aus = img.crop((int(rect["vx"]) + 2, int(rect["vy"]) + 2,
                        int(rect["vx"] + rect["w"]) - 2, int(rect["vy"] + rect["h"]) - 2))
        farben = aus.getcolors(maxcolors=1 << 20) or []
        haeufigst = max(farben)[1] if farben else (0, 0, 0)
        anders = sum(c for c, f in farben if sum(abs(a - b) for a, b in zip(f, haeufigst)) > 40)
        anteil = anders / max(1, aus.size[0] * aus.size[1])
        check("[%s] in der Grafikflaeche ist gezeichnet (%.1f %% Bildpunkte)" % (thema, 100 * anteil),
              anteil > 0.005, anteil)

        # Hover auf den Knoten mit dem hoechsten Grad
        ziel = js("(function(){var W=window.WissensgraphIntern,G=W.graph(),R=W.renderer(),best=null;"
                  "G.forEachNode(function(n,a){if(a.typ!=='quelle'&&(!best||a.grad>G.getNodeAttribute(best,'grad')))best=n;});"
                  "var d=R.getNodeDisplayData(best),v=R.framedGraphToViewport(d);"
                  "var r=document.getElementById('wg-graph').getBoundingClientRect();"
                  "var fremd=null;G.forEachNode(function(n){if(!fremd&&n!==best&&!G.areNeighbors(n,best))fremd=n;});"
                  "return {id:best,label:G.getNodeAttribute(best,'label'),x:r.left+v.x,y:r.top+v.y,fremd:fremd};})()")
        maus("mouseMoved", ziel["x"], ziel["y"])
        time.sleep(0.8)
        gedimmt = js("(function(){var W=window.WissensgraphIntern,R=W.renderer();"
                     "var soll=getComputedStyle(document.body).getPropertyValue('--graph-gedimmt').trim();"
                     "var d=R.getNodeDisplayData(%s);return {farbe:d&&d.color,soll:soll};})()" % json.dumps(ziel["fremd"]))
        kv2 = js("(function(){var W=window.WissensgraphIntern,G=W.graph(),R=W.renderer(),fremd=null;"
                 "G.forEachEdge(function(k,a,s,t){if(!fremd&&s!==%s&&t!==%s)fremd=k;});"
                 "var d=fremd?R.getEdgeDisplayData(fremd):null;return d?d.visibility:null;})()"
                 % (json.dumps(ziel["id"]), json.dumps(ziel["id"])))
        check("[%s] Hover blendet fremde Kanten aus" % thema, kv2 == "hidden", kv2)
        check("[%s] Hover dimmt einen fremden Knoten" % thema,
              bool(gedimmt) and gedimmt.get("farbe") == gedimmt.get("soll"), gedimmt)
        # Beschriftungen beim groessten Knoten gedeckelt (Ueberlappung, 2026-10-31):
        # gemessen an den Anzeigedaten, die sigma wirklich zeichnet.
        besch = js("(function(){var W=window.WissensgraphIntern,G=W.graph(),R=W.renderer(),n=0,nb=0,kt=0;"
                   "G.forEachNode(function(k){var d=R.getNodeDisplayData(k);if(d&&d.labelVisibility==='visible')n++;});"
                   "nb=G.degree(%s);"
                   "G.forEachEdge(function(k){var d=R.getEdgeDisplayData(k);if(d&&d.label&&d.visibility!=='hidden')kt++;});"
                   "return {erzwungen:n,nachbarn:nb,kantentexte:kt,max:W.MAX_BESCHRIFTUNGEN,maxk:W.MAX_KANTENTEXTE};})()"
                   % json.dumps(ziel["id"]))
        check("[%s] Hover: Positivkontrolle – der Knoten hat mehr Nachbarn als Beschriftungen (%s)"
              % (thema, besch and besch.get("nachbarn")), bool(besch) and besch["nachbarn"] > besch["max"], besch)
        check("[%s] Hover: erzwungene Beschriftungen gedeckelt (%s)" % (thema, besch and besch.get("erzwungen")),
              bool(besch) and 1 < besch["erzwungen"] <= besch["max"] + 1, besch)
        check("[%s] Hover: Kantentexte gedeckelt (%s)" % (thema, besch and besch.get("kantentexte")),
              bool(besch) and 0 < besch["kantentexte"] <= besch["maxk"], besch)
        kasten = js("(function(){var R=window.WissensgraphIntern.renderer(),d=R.getNodeDisplayData(%s);"
                    "return {ist:d&&d.backdropColor,soll:getComputedStyle(document.body).getPropertyValue('--bg-secondary').trim()};})()"
                    % json.dumps(ziel["id"]))
        check("[%s] Hover-Kasten im Grund des Themas (%s)" % (thema, kasten and kasten.get("ist")),
              bool(kasten) and kasten.get("soll") and kasten.get("ist") == kasten.get("soll"), kasten)
        bild(os.path.join(HOME, "wissensgraph_%s_hover.png" % thema))
        maus("mousePressed", ziel["x"], ziel["y"])
        maus("mouseReleased", ziel["x"], ziel["y"])
        time.sleep(1.5)
        det = js("(function(){var d=document.getElementById('wg-detail');"
                 "return {offen:!d.classList.contains('hidden'),name:(d.querySelector('.wg-d-name')||{}).textContent||''};})()")
        check("[%s] Klick oeffnet das Detail des Knotens" % thema,
              det.get("offen") and det.get("name") == ziel["label"], (det, ziel["label"]))
        wk = js("(function(){var w=document.querySelector('#wg-detail .wg-wiki');"
                "return w?{text:w.textContent.slice(0,200),knopf:!!w.querySelector('.wg-wiki-knopf')}:null;})()")
        check("[%s] Detail: Wiki-Abschnitt mit Knopf (ohne zu erzeugen)" % thema,
              bool(wk) and wk.get("knopf") and "Wiki-Seite" in wk.get("text", ""), wk)
        bild(os.path.join(HOME, "wissensgraph_%s_detail.png" % thema))
        maus("mouseMoved", 5, 5)
        js("document.getElementById('wg-detail-zu').click()")

        # Suche: der zweite Begriff wird hervorgehoben, ein fremder gedimmt
        js("(function(){var f=document.getElementById('wg-suche');f.value=%s;"
           "f.dispatchEvent(new Event('input',{bubbles:true}));})()" % json.dumps(ziel["label"]))
        time.sleep(1.5)
        such = js("(function(){var W=window.WissensgraphIntern,R=W.renderer();"
                  "var soll=getComputedStyle(document.body).getPropertyValue('--graph-gedimmt').trim();"
                  "return {treffer:R.getNodeDisplayData(%s).color!==soll};})()" % json.dumps(ziel["id"]))
        check("[%s] Suche hebt den Treffer hervor" % thema, such and such.get("treffer"), such)
        js("(function(){var f=document.getElementById('wg-suche');f.value='';"
           "f.dispatchEvent(new Event('input',{bubbles:true}));})()")
        time.sleep(0.6)

        # Zoom-Knoepfe: das Kameraverhaeltnis muss sich aendern (und es darf
        # keine Konsolenfehler geben – sigma 4 kennt kein animatedZoom mehr).
        r0 = js("window.WissensgraphIntern.renderer().getCamera().ratio")
        js("document.getElementById('wg-zoom-plus').click()")
        time.sleep(0.8)
        r1 = js("window.WissensgraphIntern.renderer().getCamera().ratio")
        js("document.getElementById('wg-zoom-minus').click()")
        time.sleep(0.8)
        js("document.getElementById('wg-zoom-minus').click()")
        time.sleep(0.8)
        r2 = js("window.WissensgraphIntern.renderer().getCamera().ratio")
        js("document.getElementById('wg-einpassen').click()")
        time.sleep(0.8)
        r3 = js("window.WissensgraphIntern.renderer().getCamera().ratio")
        check("[%s] Zoom +, −, Einpassen wirken" % thema,
              None not in (r0, r1, r2, r3) and r1 < r0 and r2 > r1 and abs(r3 - 1) < 0.05, (r0, r1, r2, r3))

        # Filter Wissensgruppe (gemeldet 2026-10-31: "Laden fehlgeschlagen"): die
        # Seite baut beim Filterwechsel den Graphen neu – die GRAFIK muss danach
        # an DEMSELBEN Graphen haengen, den die Seite benutzt, und es darf keine
        # Fehlermeldung stehen. jsdom hat keinen Renderer und sah das nie.
        wahl = js("(function(){var s=document.getElementById('wg-gruppe');var o=null;"
                  "for(var i=0;i<s.options.length;i++){if(s.options[i].value){o=s.options[i].value;break;}}"
                  "if(!o)return null;s.value=o;s.dispatchEvent(new Event('change',{bubbles:true}));return o;})()")
        time.sleep(4)
        nach = js("(function(){var W=window.WissensgraphIntern,R=W.renderer(),h=document.getElementById('wg-hinweis');"
                  "return {gleich:!!R&&R.getGraph()===W.graph(),knoten:W.graph()?W.graph().order:-1,"
                  "fehler:h&&!h.classList.contains('hidden')&&h.classList.contains('is-err')?h.textContent:''};})()")
        check("[%s] Positivkontrolle: eine Wissensgruppe gewaehlt (%s)" % (thema, wahl), bool(wahl), wahl)
        check("[%s] Filter Wissensgruppe: keine Fehlermeldung" % thema, bool(nach) and not nach.get("fehler"), nach)
        check("[%s] Filter Wissensgruppe: Grafik zeigt den neuen Graphen" % thema, bool(nach) and nach.get("gleich"), nach)
        js("(function(){var s=document.getElementById('wg-gruppe');s.value='';s.dispatchEvent(new Event('change',{bubbles:true}));})()")
        time.sleep(4)
        zur = js("(function(){var W=window.WissensgraphIntern,R=W.renderer(),h=document.getElementById('wg-hinweis');"
                 "return {gleich:!!R&&R.getGraph()===W.graph(),"
                 "fehler:h&&!h.classList.contains('hidden')&&h.classList.contains('is-err')?h.textContent:''};})()")
        check("[%s] Filter zurueck auf alle: keine Fehlermeldung, Grafik am Graphen" % thema,
              bool(zur) and not zur.get("fehler") and zur.get("gleich"), zur)

        # Pruefliste (gemeldet 2026-10-31: kein Ergebnis, kein Kreis): Klick zeigt
        # SOFORT den drehenden Kreis, der Knopf ist gesperrt, und die Liste kommt
        # ohne weiteres Zutun, sobald der Hintergrund fertig ist.
        js("document.getElementById('wg-pruef-laden').click()")
        time.sleep(0.3)
        sofort = js("(function(){var b=document.getElementById('wg-pruefliste');var s=b.querySelector('.jv-pkg-spin');"
                    "return {kreis:!!s,dreht:s?getComputedStyle(s).animationName:'',gesperrt:document.getElementById('wg-pruef-laden').disabled};})()")
        # Zwei richtige Lagen: es wird gerechnet (Kreis dreht, Knopf gesperrt) –
        # oder der Stand war schon fertig und die Liste steht sofort da (zweiter
        # Durchgang; dort ist ein Kreis gar nicht noetig).
        schon = js("document.querySelectorAll('#wg-pruefliste .wg-paar').length")
        check("[%s] Pruefliste: sofort drehender Kreis mit gesperrtem Knopf – oder schon fertig (%s Paare)" % (thema, schon),
              bool(sofort) and ((sofort.get("kreis") and sofort.get("dreht") not in ("", "none") and sofort.get("gesperrt"))
                                or (not sofort.get("kreis") and (schon or 0) > 0)), (sofort, schon))
        fertig = None
        for _ in range(60):
            time.sleep(2)
            fertig = js("(function(){var b=document.getElementById('wg-pruefliste');"
                        "return {paare:b.querySelectorAll('.wg-paar').length,kreis:!!b.querySelector('.jv-pkg-spin'),"
                        "frei:!document.getElementById('wg-pruef-laden').disabled,text:b.textContent.slice(0,120)};})()")
            if fertig and fertig.get("frei"):
                break
        check("[%s] Pruefliste: Ergebnis kommt von selbst, Kreis weg, Knopf frei (%s Paare)"
              % (thema, fertig and fertig.get("paare")),
              bool(fertig) and fertig.get("frei") and not fertig.get("kreis") and fertig.get("paare", 0) > 0, fertig)

        # Faerbung
        js("document.getElementById('wg-faerbung').click()")
        time.sleep(0.6)
        leg = js("document.getElementById('wg-legende').textContent")
        farbI = js("(function(){var W=window.WissensgraphIntern,G=W.graph(),R=W.renderer(),s={};"
                   "G.forEachNode(function(n){var d=R.getNodeDisplayData(n);if(d&&d.color)s[d.color]=1;});"
                   "return Object.keys(s).length;})()")
        check("[%s] Inselfaerbung: mindestens drei Farben (%s)" % (thema, farbI), (farbI or 0) >= 3, farbI)
        check("[%s] Faerbung nach Themen-Inseln: Legende mit Zusammenhalt" % thema, "Zusammenhalt" in (leg or ""),
              (leg or "")[:120])
        bild(os.path.join(HOME, "wissensgraph_%s_inseln.png" % thema))
        js("document.getElementById('wg-faerbung').click()")

        # Kontrast der Legende gegen ihre Karte
        far = js("(function(){function rgb(s){return (s.match(/[\\d.]+/g)||[]).slice(0,3).map(Number);}"
                 "var l=document.querySelector('#wg-legende .wg-leg');var k=document.querySelector('.ja-card');"
                 "return {fg:rgb(getComputedStyle(l).color),bg:rgb(getComputedStyle(k).backgroundColor)};})()")
        kv = kontrast(far["fg"], far["bg"])
        check("[%s] Legende lesbar: Kontrast %.2f:1" % (thema, kv), kv >= 4.5, far)

        # Kein waagerechter Ueberlauf – breit und schmal
        for breite in (1400, 520):
            cmd("Emulation.setDeviceMetricsOverride", {"width": breite, "height": 900,
                                                       "deviceScaleFactor": 1, "mobile": False})
            time.sleep(1.2)
            ue = js("document.documentElement.scrollWidth - window.innerWidth")
            check("[%s] %d px: kein waagerechter Ueberlauf (%s px)" % (thema, breite, ue), ue is not None and ue <= 0, ue)
            if breite == 520:
                bild(os.path.join(HOME, "wissensgraph_%s_520.png" % thema))
        cmd("Emulation.clearDeviceMetricsOverride")

        # Gemerkte Container (gemeldet 2026-10-31): Grafik und Pflege zugeklappt
        # speichern, neu laden – sie bleiben zu, und die Grafik entsteht erst beim
        # Aufklappen (sigma ohne Flaeche bricht sonst ab).
        js("localStorage.setItem('jarvis_wissensgraph_zu', JSON.stringify(['graph','pflege']))")
        cmd("Page.navigate", {"url": "https://127.0.0.1/wissensgraph"})
        kz = None
        for _ in range(30):
            time.sleep(1)
            kz = js("(function(){var W=window.WissensgraphIntern;function zu(i){var k=document.querySelector("
                    "'.ja-card[data-klapp=\"'+i+'\"]');return k?k.classList.contains('is-zu'):null;}"
                    "return {knoten:W&&W.graph()?W.graph().order:0,renderer:!!(W&&W.renderer()),"
                    "graph:zu('graph'),pflege:zu('pflege'),insights:zu('insights')};})()")
            if kz and kz.get("knoten"):
                break
        check("[%s] Klapp: Positivkontrolle – Graph nach dem Neuladen geladen (%s Knoten)" % (thema, kz and kz.get("knoten")),
              bool(kz) and kz.get("knoten", 0) > 0, kz)
        check("[%s] Klapp: Grafik und Pflege bleiben nach dem Neuladen zu, Auffaelligkeiten offen" % thema,
              bool(kz) and kz.get("graph") is True and kz.get("pflege") is True and kz.get("insights") is False, kz)
        check("[%s] Klapp: zugeklappte Grafik hat noch keinen Renderer" % thema, bool(kz) and not kz.get("renderer"), kz)
        js("document.querySelector('.ja-card[data-klapp=\"graph\"] .ja-card-head').click()")
        time.sleep(1.5)
        auf = js("(function(){var W=window.WissensgraphIntern,b=document.getElementById('wg-graph').getBoundingClientRect();"
                 "var c=document.querySelector('#wg-graph canvas');"
                 "return {renderer:!!W.renderer(),hoehe:Math.round(b.height),canvas:c?c.width:0,"
                 "zu:JSON.parse(localStorage.getItem('jarvis_wissensgraph_zu')||'null')};})()")
        check("[%s] Klapp: Aufklappen baut die Grafik mit Flaeche (%s)" % (thema, auf),
              bool(auf) and auf.get("renderer") and auf.get("hoehe", 0) > 100 and auf.get("canvas", 0) > 100, auf)
        check("[%s] Klapp: gespeichert ist danach nur noch die Pflege" % thema, bool(auf) and auf.get("zu") == ["pflege"], auf)
        bild(os.path.join(HOME, "wissensgraph_%s_aufgeklappt.png" % thema))

        # Zustand mit Kreis: gegen den ECHTEN Arbeiter auf DEV – gemessen wird die
        # Uebereinstimmung von Anzeige und Status, nicht ein bestimmter Zustand.
        js("document.querySelector('.ja-card[data-klapp=\"pflege\"] .ja-card-head').click()")
        time.sleep(2.5)
        zst = js("(async function(){var st=await fetch('/api/wissensgraph/status',{credentials:'same-origin',"
                 "headers:window.JarvisSitzung?window.JarvisSitzung.kopfsatz():{}}).then(function(r){return r.json();});"
                 "await window.WissensgraphIntern.statusHolen();"
                 "var dd=document.querySelector('#wg-status dl dd');var s=dd?dd.querySelector('.jv-pkg-spin'):null;"
                 "return {arbeitet:window.WissensgraphIntern.arbeitetGerade(st),laeuft:st.laeuft,aktuell:st.aktuell||'',"
                 "text:dd?dd.textContent:'',kreis:!!s,dreht:s?getComputedStyle(s).animationName:''};})()")
        check("[%s] Zustand: Kreis genau dann, wenn der Dienst arbeitet (%s)" % (thema, zst and zst.get("text")),
              bool(zst) and zst.get("kreis") == zst.get("arbeitet")
              and (not zst.get("kreis") or zst.get("dreht") not in ("", "none")), zst)
        bild(os.path.join(HOME, "wissensgraph_%s_zustand.png" % thema))
        js("localStorage.removeItem('jarvis_wissensgraph_zu')")
    # Bestandsbefund, NICHT aus dieser Seite: branding.js startet auf /portal das
    # Portal-Video, die Abnahme verlaesst /portal sofort, und das abgelehnte
    # play()-Promise faengt dort kein try/catch (branding.js, Video-Zweig).
    # Genau diese eine Meldung wird ausgenommen, mit Grund – alles andere zaehlt.
    bestand = [f for f in fehler if "play() request was interrupted" in f]
    fehler = [f for f in fehler if f not in bestand]
    if bestand:
        print("     (Bestandsbefund ausgenommen: %d x play()-Abbruch des Portal-Videos)" % len(bestand))
    check("keine Skriptfehler in der Konsole", not fehler, fehler[:3])
finally:
    try:
        p.terminate()
        p.wait(10)
    except Exception:  # noqa: BLE001
        pass
    subprocess.run(["rm", "-rf", prof], check=False)

print("\nErgebnis: %d ok, %d fehlgeschlagen" % (ok, fail))
print("Bilder: %s/wissensgraph_*.png" % HOME)
sys.exit(1 if fail else 0)
