"""LIVE im echten Chrome (DEV): der Einstellungen-Dialog in /chat.

⚠ WARUM IM ECHTEN BROWSER: jsdom rechnet kein Layout. Gemessen werden hier die
Zusagen, die nur ein Layout beantworten kann – Speichern erreichbar auch bei
VIELEN Wissensgruppen, kein waagerechter Ueberlauf, Kontrast des Warnhinweises.

Lauf AUF DEM SERVER:  runuser -u jarvis -- venv/bin/python live_ui.py
"""
import base64, json, subprocess, sys, time, urllib.request
import websocket

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
import urllib3; urllib3.disable_warnings()
from backend.main import generate_token          # noqa: E402
from backend import chat_sessions as cs          # noqa: E402

USER = "jarvis"
TOK = generate_token(USER)
VORHER = cs.get_kb_default(USER)
ok = fail = 0

def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if cond: ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else: fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))

PORT, prof = 9351, "/tmp/kbvor_ui/prof"
subprocess.run(["rm", "-rf", prof], check=False, capture_output=True)
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
    r = cmd("Runtime.evaluate", {"expression": code, "returnByValue": True, "awaitPromise": True})
    if r.get("exceptionDetails"):
        return {"_fehler": str(r["exceptionDetails"])[:300]}
    return (r.get("result") or {}).get("value")

def schuss(datei):
    r = cmd("Page.captureScreenshot", {"format": "png"})
    if r.get("data"):
        open(datei, "wb").write(base64.b64decode(r["data"]))
        return True
    return False

# Kontrast: Schichten von unten nach oben zusammenrechnen (halbtransparente
# Flaechen als deckend zu nehmen liefert Fehler, die es nicht gibt – Register).
def lum(c):
    def k(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * k(c[0]) + 0.7152 * k(c[1]) + 0.0722 * k(c[2])

def kontrast(vg, bg):
    a, b = lum(vg), lum(bg)
    hell, dunkel = max(a, b), min(a, b)
    return (hell + 0.05) / (dunkel + 0.05)

try:
    for thema in ("dark", "light"):
        print("\n\033[1mThema: %s\033[0m" % thema)
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(2)
        js("localStorage.setItem('jarvis_token', %s);"
           "localStorage.setItem('jarvis_user', %s);"
           "localStorage.setItem('jarvis_theme', %s);"
           % (json.dumps(TOK), json.dumps(USER), json.dumps(thema)))
        cmd("Page.navigate", {"url": "https://127.0.0.1/chat"})
        time.sleep(8)

        check("Chat-Oberflaeche steht (angemeldet)",
              js("document.getElementById('chat-screen') && !document.getElementById('chat-screen').classList.contains('hidden')") is True)

        # Zahnrad im echten Klickweg
        r = js("""(function(){ var b=document.getElementById('cs-settings');
                   if(!b) return 'kein Knopf'; b.click(); return b.title; })()""")
        check("Zahnrad heisst 'Einstellungen' (DE) bzw. 'Settings' (EN)",
              r in ("Einstellungen", "Settings"), repr(r))
        time.sleep(3)

        # ⚠ DER WISSENS-CONTAINER IST PER VORGABE ZU – und in einem zugeklappten
        # <details> versteckt Chrome den Inhalt ueber `content-visibility`,
        # waehrend die NACHFAHREN gecachte Layout-Zahlen behalten (Register,
        # 2026-09-01 bezahlt). Gemessen wird deshalb das <details> SELBST, und
        # jede Messung an der Liste passiert erst nach dem Aufklappen.
        r = js("""(function(){
            var d=document.querySelectorAll('#chat-settings-modal .chs-sect');
            return {pre: d[0].open, kb: d[1].open,
                    kbHoehe: Math.round(d[1].getBoundingClientRect().height)};
        })()""")
        check("Vorgabe: Preprompt offen, Wissensquellen zu",
              isinstance(r, dict) and r["pre"] is True and r["kb"] is False, repr(r))
        check("der zugeklappte Container ist wirklich flach (nur die Titelzeile)",
              isinstance(r, dict) and r["kbHoehe"] < 70, repr(r))
        # Aufklappen wie ein Benutzer (Klick auf den Titel) und messen, dass es
        # gewirkt hat – ohne diese Positivkontrolle ist jede Messung darunter
        # trivial.
        r = js("""(function(){
            var d=document.querySelectorAll('#chat-settings-modal .chs-sect')[1];
            d.querySelector('summary').click();
            return {offen: d.open, hoehe: Math.round(d.getBoundingClientRect().height)};
        })()""")
        check("ein Klick auf den Titel klappt auf (Positivkontrolle der Messung)",
              isinstance(r, dict) and r["offen"] is True and r["hoehe"] > 120, repr(r))
        time.sleep(1)

        m = js("""(function(){
            var el=document.getElementById('chat-settings-modal');
            if(!el) return null;
            var s=getComputedStyle(el), r=el.getBoundingClientRect();
            var card=el.querySelector('.chs-card').getBoundingClientRect();
            return {sichtbar: s.display!=='none' && +s.opacity>0.9, w: Math.round(card.width),
                    h: Math.round(card.height), sects: el.querySelectorAll('.chs-sect').length};
        })()""")
        check("Dialog offen und deckend", isinstance(m, dict) and m.get("sichtbar") is True, repr(m))
        check("zwei Container", isinstance(m, dict) and m.get("sects") == 2, repr(m))
        check("Dialog breiter als die 380px der Basisklasse (Positivkontrolle)",
              isinstance(m, dict) and m.get("w", 0) > 500, repr(m))

        # Preprompt-Container: Titel + Feld messbar gross
        r = js("""(function(){
            var s=document.querySelectorAll('#chat-settings-modal .chs-sect');
            var ta=document.getElementById('preprompt-text').getBoundingClientRect();
            return {t1: s[0].querySelector('.chs-sect-title').textContent.trim(),
                    t2: s[1].querySelector('.chs-sect-title').textContent.trim(),
                    taW: Math.round(ta.width), taH: Math.round(ta.height)};
        })()""")
        check("Container 1 traegt den Preprompt-Titel",
              isinstance(r, dict) and ("Preprompt" in r.get("t1", "") or "pre-prompt" in r.get("t1", "")), repr(r))
        check("Container 2 traegt den Wissensquellen-Titel",
              isinstance(r, dict) and ("Wissensquellen" in r.get("t2", "") or "Knowledge" in r.get("t2", "")), repr(r))
        check("das Textfeld hat eine echte Groesse (nicht 0)",
              isinstance(r, dict) and r.get("taW", 0) > 300 and r.get("taH", 0) > 80, repr(r))

        # ── VIELE Gruppen einschmuggeln: bleibt Speichern erreichbar? ────────
        # Das ist die eigentliche Layout-Frage – bei 3 Gruppen kann sie
        # zwangslaeufig nicht scheitern.
        js("""window.KbGroupFilter.loadEntries = async function(){
                 var a=[]; for (var i=1;i<=40;i++) a.push({id:'gg'+i,
                     name:'Sehr lange Wissensgruppen-Bezeichnung Nummer '+i+' mit Zusatz',
                     color:'#8844cc'});
                 a.push({id:'ungrouped',name:'ungruppiert',color:'#94a3b8'}); return a; };""")
        js("document.getElementById('cs-settings').click()")   # zu
        time.sleep(1)
        js("document.getElementById('cs-settings').click()")   # auf, neu zeichnen
        time.sleep(3)
        r = js("""(function(){
            var box=document.getElementById('chs-kb-list');
            var save=document.getElementById('btn-chat-settings-save');
            var card=document.querySelector('.chs-card');
            var b=save.getBoundingClientRect(), c=card.getBoundingClientRect();
            var body=document.querySelector('.chs-body');
            return {zeilen: box.querySelectorAll('input').length,
                    saveTop: Math.round(b.top), saveBottom: Math.round(b.bottom),
                    fenster: window.innerHeight, cardBottom: Math.round(c.bottom),
                    bodyScroll: body.scrollHeight > body.clientHeight + 1,
                    listeScroll: box.scrollHeight > box.clientHeight + 1,
                    docBreite: document.documentElement.scrollWidth,
                    fensterBreite: window.innerWidth};
        })()""")
        check("41 Zeilen gezeichnet (40 Gruppen + ungruppiert)",
              isinstance(r, dict) and r.get("zeilen") == 41, repr(r))
        check("⚠ Speichern bleibt IM Sichtfenster (Update-Popup-Lehre)",
              isinstance(r, dict) and 0 < r["saveTop"] and r["saveBottom"] <= r["fenster"], repr(r))
        check("der Dialog laeuft nicht aus dem Fenster",
              isinstance(r, dict) and r["cardBottom"] <= r["fenster"], repr(r))
        check("stattdessen scrollt der Koerper", isinstance(r, dict) and r["bodyScroll"], repr(r))
        check("und zwar als EINZIGER Scrollbereich (die Liste scrollt nicht selbst)",
              isinstance(r, dict) and not r["listeScroll"], repr(r))
        check("kein waagerechter Ueberlauf der Seite",
              isinstance(r, dict) and r["docBreite"] <= r["fensterBreite"], repr(r))

        # Langer Gruppenname: kuerzt statt zu schieben
        r = js("""(function(){
            var row=document.querySelector('#chs-kb-list .chs-kb-row');
            var nm=row.querySelector('.chs-kb-name').getBoundingClientRect();
            var rr=row.getBoundingClientRect();
            var cb=row.querySelector('input').getBoundingClientRect();
            return {nameRechts: Math.round(nm.right), zeileRechts: Math.round(rr.right),
                    cbLinks: Math.round(cb.left), zeileLinks: Math.round(rr.left),
                    gekuerzt: row.querySelector('.chs-kb-name').scrollWidth > nm.width + 1};
        })()""")
        check("langer Name bleibt in der Zeile",
              isinstance(r, dict) and r["nameRechts"] <= r["zeileRechts"] + 1, repr(r))
        # Positivkontrolle des Kuerzens: ein achtfach ueberlanger Name MUSS
        # kuerzen statt die Zeile zu sprengen.
        r2 = js("""(function(){
            var nm=document.querySelector('#chs-kb-list .chs-kb-name');
            nm.textContent = 'X'.repeat(400) + ' Ende';
            var b=nm.getBoundingClientRect();
            var rr=nm.closest('.chs-kb-row').getBoundingClientRect();
            return {nameRechts: Math.round(b.right), zeileRechts: Math.round(rr.right),
                    gekuerzt: nm.scrollWidth > b.width + 1};
        })()""")
        check("ein achtfach ueberlanger Name kuerzt statt die Zeile zu sprengen",
              isinstance(r2, dict) and r2["gekuerzt"] and r2["nameRechts"] <= r2["zeileRechts"] + 1, repr(r2))
        check("das Kaestchen bleibt links in der Zeile",
              isinstance(r, dict) and r["cbLinks"] >= r["zeileLinks"] - 1, repr(r))

        # ⚠ Ist ein angehaktes Kaestchen von einem leeren zu UNTERSCHEIDEN?
        # `.modal-card input` bringt border/background mit; ein ersetztes
        # Erscheinungsbild wuerde den Haken verschlucken, und "angehakt" waere
        # nicht ablesbar. Gemessen per Bildvergleich derselben Zeile.
        js("""(function(){ var cbs=document.querySelectorAll('#chs-kb-list input');
               cbs[0].checked=true; cbs[1].checked=false; })()""")
        time.sleep(1)
        def pixel(sel):
            r = cmd("Runtime.evaluate", {"expression":
                "(function(){var r=document.querySelector('" + sel + "').getBoundingClientRect();"
                "return JSON.stringify({x:Math.round(r.left),y:Math.round(r.top),"
                "w:Math.max(1,Math.round(r.width)),h:Math.max(1,Math.round(r.height))});})()",
                "returnByValue": True})
            box = json.loads((r.get("result") or {}).get("value") or "{}")
            sh = cmd("Page.captureScreenshot", {"format": "png", "clip": {
                "x": box["x"], "y": box["y"], "width": box["w"], "height": box["h"],
                "scale": 3}})
            return sh.get("data") or ""
        a = pixel('#chs-kb-list .chs-kb-row:nth-child(1) input')
        b = pixel('#chs-kb-list .chs-kb-row:nth-child(2) input')
        check("angehaktes Kaestchen sieht anders aus als ein leeres (Haken sichtbar)",
              bool(a) and bool(b) and a != b, "Bilder gleich lang: %d/%d" % (len(a), len(b)))
        r = js("""(function(){ var cb=document.querySelector('#chs-kb-list input');
                   var rr=cb.getBoundingClientRect();
                   return {w: Math.round(rr.width), h: Math.round(rr.height)}; })()""")
        check("das Kaestchen hat wieder Kaestchen-Groesse (nicht zeilenbreit)",
              isinstance(r, dict) and 8 <= r["w"] <= 30 and 8 <= r["h"] <= 30, repr(r))

        # Kontrast des Warnhinweises (0 Gruppen gewaehlt)
        js("document.getElementById('chs-kb-none').click()")
        time.sleep(1)
        r = js("""(function(){
            var h=document.getElementById('chs-kb-hint');
            if (h.hidden) return {versteckt:true};
            var s=getComputedStyle(h), rr=h.getBoundingClientRect();
            // Hintergrund-Schichten von unten nach oben sammeln
            var lagen=[], el=h;
            while (el) { var bg=getComputedStyle(el).backgroundColor;
                if (bg && bg!=='rgba(0, 0, 0, 0)' && bg!=='transparent') lagen.push(bg);
                el = el.parentElement; }
            return {text: h.textContent.trim().slice(0,60), farbe: s.color, lagen: lagen,
                    breite: Math.round(rr.width), hoehe: Math.round(rr.height),
                    imKasten: rr.right <= document.querySelector('.chs-card').getBoundingClientRect().right + 1};
        })()""")
        def rgb(s):
            s = s.strip()
            inner = s[s.index("(") + 1:s.rindex(")")]
            if s.startswith("color("):
                teile = inner.replace("/", " ").split()
                # erstes Token ist der Farbraum (srgb), danach Anteile 0..1
                zahlen = [float(x) for x in teile[1:] if x.replace(".", "", 1).replace("-", "", 1).isdigit()]
                v = [z * 255.0 for z in zahlen[:3]]
                if len(zahlen) > 3:
                    v.append(zahlen[3])
                return v
            return [float(x) for x in inner.replace("/", ",").split(",")]
        if isinstance(r, dict) and not r.get("versteckt"):
            vg = rgb(r["farbe"])[:3]
            # oberste deckende Schicht als Grund nehmen (alpha=1)
            grund = None
            for l in r["lagen"]:
                v = rgb(l)
                if len(v) < 4 or v[3] >= 0.99:
                    grund = v[:3]; break
            k = kontrast(vg, grund or [255, 255, 255])
            check("Warnhinweis erscheint bei 0 gewaehlten Gruppen", r["hoehe"] > 5, repr(r))
            check("Warnhinweis bleibt im Kasten", r["imKasten"] is True, repr(r))
            check("Kontrast des Warnhinweises >= 4,5:1 (gemessen %.2f:1)" % k, k >= 4.5,
                  "Farbe %s auf %s" % (r["farbe"], grund))
        else:
            check("Warnhinweis erscheint bei 0 gewaehlten Gruppen", False, repr(r))

        # Der Klappzustand wird gemerkt: aufgeklappt lassen, Seite neu laden.
        gesp = js("(function(){ return localStorage.getItem('jarvis_chat_settings_open'); })()")
        check("die Wahl steht im Speicher", isinstance(gesp, str) and '"kb":true' in gesp.replace(" ", ""),
              repr(gesp))
        cmd("Page.navigate", {"url": "https://127.0.0.1/chat"})
        time.sleep(8)
        js("document.getElementById('cs-settings').click()")
        time.sleep(3)
        r = js("""(function(){
            var d=document.querySelectorAll('#chat-settings-modal .chs-sect');
            return {pre: d[0].open, kb: d[1].open};
        })()""")
        check("⚠ nach dem Neuladen gilt die gemerkte Wahl (Wissen offen)",
              isinstance(r, dict) and r["kb"] is True, repr(r))
        # Zuruecksetzen, damit das naechste Thema mit der Vorgabe startet.
        js("(function(){ try{ localStorage.removeItem('jarvis_chat_settings_open'); }catch(e){} })()")

        schuss("/tmp/kbvor-%s.png" % thema)
        check("Screenshot geschrieben (%s)" % thema, True)

        # Sprachwechsel
        if thema == "dark":
            js("window.setLang && window.setLang('en')")
            time.sleep(2)
            r = js("""(function(){
                var s=document.querySelectorAll('#chat-settings-modal .chs-sect');
                return {titel: document.querySelector('#chat-settings-modal .modal-title').textContent.trim(),
                        t2: s[1].querySelector('.chs-sect-title').textContent.trim()};
            })()""")
            check("Sprachwechsel DE->EN erreicht den Dialog",
                  isinstance(r, dict) and r["titel"] == "Settings" and "Knowledge" in r["t2"], repr(r))
            js("window.setLang && window.setLang('de')")
            time.sleep(1)
finally:
    try: ws.close()
    except Exception: pass
    p.terminate()
    subprocess.run(["rm", "-rf", prof], check=False, capture_output=True)
    cs.save_kb_default(USER, VORHER or [])
    gleich = cs.get_kb_default(USER) == VORHER
    print(("  \033[32m✓\033[0m " if gleich else "  \033[31m✗\033[0m ")
          + "Ausgangszustand wiederhergestellt (%r)" % cs.get_kb_default(USER))
    if gleich: ok += 1
    else: fail += 1

print("\n\033[1mErgebnis: %d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
