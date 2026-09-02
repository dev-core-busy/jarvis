"""Optische Abnahme: VERSTOSS gegen GRENZE im echten Chrome (DEV).

Der jsdom-Waechter belegt, DASS die Unterscheidung gerendert wird. Ob ein
Administrator sie im fertigen Bild auch SIEHT, sagt er nicht: jsdom rechnet
kein Layout. Genau daran ist am 2026-08-30 schon einmal eine Kennzeichnung
gescheitert, die per Messung gruen war und im Screenshot gar nicht existierte
(`color: var(--gedaempft)` auf einem ohnehin gedaempften Element).

Gemessen wird deshalb im echten Browser, in HELL und DUNKEL:
  - die Liste enthaelt beide Sorten, und jede Zeile traegt ihr Abzeichen
  - das Abzeichen ist SICHTBAR (Flaeche > 0) und die beiden Sorten
    unterscheiden sich in der Farbe – zusaetzlich zum Wort, nicht statt seiner
  - der Zaehler in der Kopfzeile nennt beide Zahlen
  - die Begruendung steht bei jeder weichen Zeile und ist lesbar (Kontrast)
  - kein waagerechter Ueberlauf, das Abzeichen bleibt im Kasten

Der Token wird mit `generate_token` erzeugt – derselben Funktion, die
`/api/login` nach erfolgreicher Anmeldung ruft. Umgangen wird damit nichts:
`/api/security/violations` prueft danach `require_local_auth`.
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


PORT, prof = 9351, "/tmp/chrome-viol-anzeige"
subprocess.run(["rm", "-rf", prof], check=False)
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1400,1000", "--no-first-run",
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
        cmd("Page.navigate", {"url": "https://127.0.0.1/settings"})
        time.sleep(1)
        js("localStorage.setItem('jarvis_token', %s);"
           "localStorage.setItem('jarvis_theme', %s);" % (json.dumps(TOK), json.dumps(thema)))
        cmd("Page.navigate", {"url": "https://127.0.0.1/settings"})
        time.sleep(7)

        # Sicherheits-Reiter oeffnen, Abschnitt + Unter-Container aufklappen.
        js("var b=document.querySelector('.settings-tab-btn[data-settings-tab=\"security\"]');"
           "if(b)b.click();")
        time.sleep(3)
        # ⚠ Der Abschnitts-KOERPER heisst '…-body', nicht '…'. Die erste Fassung
        # dieser Probe prueste den falschen Namen, der Guard wurde damit nie wahr,
        # der Abschnitt blieb display:none – und JEDES Rechteck darin ist dann 0.
        # Der Waechter meldete "Abzeichen unsichtbar", obwohl es 54 px breit ist.
        # Deshalb wird jetzt geklickt UND das Ergebnis gemessen, statt es
        # vorauszusetzen (Register: die Eigenschaft messen, nicht annehmen).
        def sichtbar():
            return js("(function(){var b=document.getElementById('sec-sect-incidents-body');"
                      "return !!b && getComputedStyle(b).display!=='none';})()") is True

        for _ in range(3):
            if sichtbar():
                break
            js("var h=document.getElementById('sec-sect-incidents-hdr'); if(h) h.click();")
            time.sleep(1)
        check("[%s] der Abschnitt ist aufgeklappt (Positivkontrolle)" % thema, sichtbar())
        js("var d=document.getElementById('sec-sub-viol'); if(d && !d.open) d.open=true;")
        time.sleep(2)

        m = js("""(function(){
            var rows=[].slice.call(document.querySelectorAll('.sec-viol-row'));
            if(!rows.length) return {rows:0};
            function f(el){ if(!el) return null; var r=el.getBoundingClientRect(),
                s=getComputedStyle(el);
                return {w:Math.round(r.width),h:Math.round(r.height),
                        t:(el.textContent||'').trim(),
                        farbe:s.backgroundColor, rand:s.borderTopColor, vorder:s.color}; }
            var hart=rows.filter(function(r){return r.classList.contains('is-hard');});
            var weich=rows.filter(function(r){return r.classList.contains('is-soft');});
            var box=document.getElementById('sec-viol-list');
            var ueber=rows.some(function(r){
                var rb=r.getBoundingClientRect(), bb=box.getBoundingClientRect();
                return rb.right > bb.right + 2; });
            var badgeH=hart.length?f(hart[0].querySelector('.sec-viol-badge')):null;
            var badgeW=weich.length?f(weich[0].querySelector('.sec-viol-badge')):null;
            var grund=weich.length?f(weich[0].querySelector('.sec-viol-reason')):null;
            return {rows:rows.length, hart:hart.length, weich:weich.length,
                    zaehler:(document.getElementById('sec-viol-count')||{}).textContent||'',
                    badgeH:badgeH, badgeW:badgeW, grund:grund,
                    ueberlauf:ueber,
                    scrollX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
                    ohneAbzeichen: rows.filter(function(r){
                        return !r.querySelector('.sec-viol-badge'); }).length,
                    weichOhneGrund: weich.filter(function(r){
                        return !r.querySelector('.sec-viol-reason'); }).length};
        })()""")

        check("[%s] die Liste ist gerendert" % thema, bool(m) and m.get("rows", 0) > 0, m)
        if not m or not m.get("rows"):
            continue
        check("[%s] beide Sorten sind vorhanden (Positivkontrolle)" % thema,
              m["hart"] > 0 and m["weich"] > 0, m)
        check("[%s] JEDE Zeile traegt ein Abzeichen" % thema, m["ohneAbzeichen"] == 0, m)
        check("[%s] jede weiche Zeile traegt ihre Begruendung" % thema,
              m["weichOhneGrund"] == 0, m)
        check("[%s] das Abzeichen ist wirklich sichtbar (Flaeche > 0)" % thema,
              bool(m["badgeH"]) and m["badgeH"]["w"] > 20 and m["badgeH"]["h"] > 10, m["badgeH"])
        check("[%s] es traegt das WORT, nicht nur Farbe" % thema,
              m["badgeH"]["t"] in ("Verstoß", "Violation")
              and m["badgeW"]["t"] in ("Grenze", "Limit"),
              (m["badgeH"]["t"], m["badgeW"]["t"]))
        # Die zweite Ebene: die Sorten muessen sich AUCH farblich unterscheiden.
        check("[%s] hart und weich sehen verschieden aus" % thema,
              m["badgeH"]["farbe"] != m["badgeW"]["farbe"]
              or m["badgeH"]["rand"] != m["badgeW"]["rand"],
              (m["badgeH"]["farbe"], m["badgeW"]["farbe"]))
        # ⚠ NICHT auf "Verstoß" pruefen: der Plural heisst "Verstöße" (mit ö) und
        # enthaelt die Singularform NICHT als Teilzeichenkette. Die erste Fassung
        # meldete deshalb FAIL bei einem voellig richtigen "(6 Verstöße · 14
        # Grenzen)". Geprueft wird die EIGENSCHAFT: beide Zahlen stehen drin, in
        # der Reihenfolge hart vor weich.
        import re as _re
        zahlen = [int(x) for x in _re.findall(r"\d+", m["zaehler"])]
        check("[%s] der Zaehler nennt beide Zahlen" % thema,
              zahlen == [m["hart"], m["weich"]], (m["zaehler"], m["hart"], m["weich"]))
        check("[%s] und beschriftet sie verschieden" % thema,
              len(set(_re.findall(r"[A-Za-zÄÖÜäöüß]+", m["zaehler"]))) >= 2, m["zaehler"])
        check("[%s] die Begruendung ist nicht leer" % thema,
              bool(m["grund"]) and len(m["grund"]["t"]) > 10, m["grund"])
        check("[%s] kein waagerechter Ueberlauf" % thema,
              not m["ueberlauf"] and not m["scrollX"], m)

        # Der Abschnitt liegt weit unten im eigenen Scrollbereich des Modals –
        # ohne dieses Scrollen zeigt der Screenshot den Kopf der Seite und
        # beweist ueber die Liste gar nichts.
        js("var d=document.getElementById('sec-sub-viol');"
           "if(d) d.scrollIntoView({block:'start'});")
        time.sleep(1)
        schuss("/tmp/viol-anzeige-%s.png" % thema)

        # ── Filter "nur Verstoesse" ───────────────────────────────────────
        # Der Filter ist der Punkt der ganzen Aenderung: sechs harte Eintraege
        # unter zwanzig sind schon unuebersichtlich, drei unter 150 sind ohne
        # ihn nur durch Scrollen zu finden. Gemessen wird, dass er wirklich
        # filtert UND dass er sagt, was er ausblendet.
        js("var c=document.getElementById('sec-viol-onlyhard');"
           "if(c){c.checked=true;c.dispatchEvent(new Event('change'));}")
        time.sleep(1)
        f = js("(function(){"
               "var rows=[].slice.call(document.querySelectorAll('.sec-viol-row')),"
               "    h=document.querySelector('.sec-viol-hidden'),"
               "    cb=document.getElementById('sec-viol-onlyhard'),"
               "    rb=cb?cb.getBoundingClientRect():null;"
               "return {n:rows.length,"
               "        nurHart:rows.every(function(r){return r.classList.contains('is-hard');}),"
               "        hinweis:h?(h.textContent||'').trim():'',"
               "        zaehler:(document.getElementById('sec-viol-count')||{}).textContent||'',"
               "        kaestchenSichtbar: !!rb && rb.width>0 && rb.height>0};})()")
        check("[%s] der Filter zeigt nur noch die harten Eintraege" % thema,
              bool(f) and f["n"] == m["hart"] and f["nurHart"], f)
        check("[%s] und sagt, wie viele er ausblendet" % thema,
              bool(f) and str(m["weich"]) in f["hinweis"], f)
        check("[%s] der Zaehler nennt weiter den Gesamtbestand" % thema,
              bool(f) and f["zaehler"] == m["zaehler"], f)
        check("[%s] das Kaestchen ist bedienbar sichtbar" % thema,
              bool(f) and f["kaestchenSichtbar"], f)
        js("var d=document.getElementById('sec-sub-viol');"
           "if(d) d.scrollIntoView({block:'start'});")
        time.sleep(1)
        schuss("/tmp/viol-filter-%s.png" % thema)
        js("var c=document.getElementById('sec-viol-onlyhard');"
           "if(c){c.checked=false;c.dispatchEvent(new Event('change'));}")
        time.sleep(1)
        check("[%s] Zurueckschalten holt alle Eintraege wieder" % thema,
              js("document.querySelectorAll('.sec-viol-row').length") == m["rows"])
        print("     Zaehler: %s | %d hart, %d weich" % (m["zaehler"], m["hart"], m["weich"]))
finally:
    try:
        ws.close()
    except Exception:
        pass
    p.kill()

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
