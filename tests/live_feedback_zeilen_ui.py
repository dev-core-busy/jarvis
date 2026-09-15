#!/usr/bin/env python3
"""Optische Abnahme des Bewertungsbogens – echtes Chrome, hell und dunkel.

⚠ WARUM NICHT NUR JSDOM: dort wird kein Layout gerechnet. Ob der feste Text die
Eingabefelder erdrueckt, ob ein langes Kriterium die Tabelle breiter macht als
das Fenster und ob die feste Zelle ueberhaupt LESBAR ist (Kontrast), sieht nur
ein echter Browser – und der Screenshot.

⚠ DIE PROBESEITE LIEGT NICHT UNTER `frontend/`: `test_theme_default.js` laeuft
ueber JEDE HTML-Datei dort und verlangt das Anti-Flacker-Skript – eine
Wegwerf-Seite liesse einen FREMDEN Waechter fehlschlagen (Register).
"""
import base64
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
_ok = _fail = 0


def check(was, bedingung, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  \033[32m✓\033[0m %s" % was)
    else:
        _fail += 1
        print("  \033[31m✗\033[0m %s%s" % (was, (" – " + detail) if detail else ""))


# ── Wegwerf-Baum mit Symlinks auf die ECHTEN Dateien ────────────────────────
TMP = pathlib.Path(tempfile.mkdtemp(prefix="fb-ui-"))
(TMP / "css").mkdir()
(TMP / "js").mkdir()
# ⚠ DIE DATEIEN WERDEN AUS DER SEITE ABGELEITET, NICHT GERATEN. Meine erste
# Fassung listete drei CSS-Dateien von Hand – `jira_addon.css` fehlte (dort
# liegen `.ja-card` & Co.), die Seite rendert dann NACKT, und der gemessene
# Kontrast war 1,32:1 fuer einen Code, der in Ordnung ist. Gesehen hat das nur
# der Screenshot (Register).
import re as _re  # noqa: PLC0415

_roh = (ROOT / "frontend" / "feedback.html").read_text(encoding="utf-8")
for _art, _unter in (("css", "css"), ("js", "js")):
    for _treffer in _re.findall(r'/static/%s/([A-Za-z0-9_.-]+\.%s)' % (_unter, _art), _roh):
        _q = ROOT / "frontend" / _unter / _treffer
        _z = TMP / _unter / _treffer
        if _q.exists() and not _z.exists():
            os.symlink(_q, _z)
print("  eingebunden: %d CSS, %d JS"
      % (len(list((TMP / "css").iterdir())), len(list((TMP / "js").iterdir()))))

TEXTE = ["Erreichbarkeit der Ansprechpartner", "Reaktionszeit bei Störungen",
         "Fachliche Qualität der Lösungen", "Freundlichkeit im Kontakt",
         "Verständlichkeit der Dokumentation", "Gesamteindruck"]
BOGEN = {
    "id": "fb", "titel": "Gesamtbewertung Nexerius", "aktiv": True,
    "beschreibung": "Bitte bewerte die folgenden Punkte.",
    "spalten": [{"id": "k", "name": "Kriterium", "typ": "fest"},
                {"id": "a", "name": "Anmerkung", "typ": "text"},
                {"id": "b", "name": "Bewertung", "typ": "sterne"}],
    "zeilen": [{"id": "z%d" % i, "werte": {"k": t}} for i, t in enumerate(TEXTE)],
}

# Die echte Seite, nur mit gestellten Endpunkten. Das Markup kommt
# unveraendert aus `frontend/feedback.html`.
html = (ROOT / "frontend" / "feedback.html").read_text(encoding="utf-8")
html = html.replace("/static/css/", "css/").replace("/static/js/", "js/")
stub = """
<script>
(function () {
  localStorage.setItem('jarvis_token', 't');
  var F = %s;
  window.fetch = function (u) {
    var p = String(u).split('?')[0];
    var d = { ok: true };
    if (p === '/api/me') { d = { is_admin: true, permissions: { feedback: true } }; }
    else if (p === '/api/feedback/formulare') { d = { ok: true, formulare: [F] }; }
    else if (p === '/api/feedback/meine') { d = { ok: true, abgaben: [] }; }
    return Promise.resolve({ ok: true, status: 200,
                             json: function () { return Promise.resolve(d); } });
  };
})();
</script>
""" % json.dumps(BOGEN)
html = html.replace("</head>", stub + "</head>", 1)
(TMP / "probe.html").write_text(html, encoding="utf-8")

# ── HTTP-Server (file:// laedt keine Module und hat kein localStorage) ──────
frei = socket.socket()
frei.bind(("127.0.0.1", 0))
PORT = frei.getsockname()[1]
frei.close()


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(TMP), **kw)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

PROFIL = pathlib.Path(tempfile.mkdtemp(prefix="fb-chrome-"))
chrome = subprocess.Popen(
    ["google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     "--remote-debugging-port=0", "--remote-allow-origins=*",
     "--user-data-dir=" + str(PROFIL), "--window-size=1280,900", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

port = None
for _ in range(120):
    z = chrome.stdout.readline()
    if "DevTools listening on ws://" in z:
        port = z.split("127.0.0.1:")[1].split("/")[0]
        break
if not port:
    print("ABBRUCH: Chrome meldet keinen DevTools-Port")
    sys.exit(2)

import websocket  # noqa: E402  (nur hier gebraucht)


def cdp(ws, methode, params=None, _z=[0]):
    _z[0] += 1
    ws.send(json.dumps({"id": _z[0], "method": methode, "params": params or {}}))
    while True:
        a = json.loads(ws.recv())
        if a.get("id") == _z[0]:
            return a.get("result", {})


def js(ws, ausdruck):
    r = cdp(ws, "Runtime.evaluate",
            {"expression": ausdruck, "returnByValue": True, "awaitPromise": True})
    return (r.get("result") or {}).get("value")


BILDER = pathlib.Path.home() / ".fb-abnahme"
BILDER.mkdir(exist_ok=True)

try:
    for thema in ("dark", "light"):
        print("\n\033[1m%s\033[0m" % ("Dunkles Thema" if thema == "dark" else "Helles Thema"))
        ziele = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:%s/json/list" % port, timeout=10).read())
        # ⚠ NUR `type == "page"`: die Liste enthaelt auch Chromes eingebaute
        # Erweiterungen – wer blind [0] nimmt, misst deren Hintergrundseite
        # (Register).
        seiten = [z for z in ziele if z.get("type") == "page"]
        ws = websocket.create_connection(seiten[0]["webSocketDebuggerUrl"],
                                         suppress_origin=True, timeout=30)
        cdp(ws, "Page.enable")
        cdp(ws, "Runtime.enable")
        # Das Thema VOR dem ersten Skript setzen – `theme.js` liest den
        # Speicher beim Laden (Register: sonst misst man zweimal hell).
        cdp(ws, "Page.addScriptToEvaluateOnNewDocument",
            {"source": "localStorage.setItem('jarvis_theme', '%s');" % thema})
        cdp(ws, "Page.navigate", {"url": "http://127.0.0.1:%s/probe.html" % PORT})
        time.sleep(2.5)

        check("die Seite ist geladen (Positivkontrolle)",
              js(ws, "!!document.getElementById('fb-tabelle')"))
        check("das Thema ist gesetzt",
              js(ws, "document.body.classList.contains('light')") == (thema == "light"))
        # ⚠ POSITIVKONTROLLE DES MESSAUFBAUS: ohne wirksames CSS rendert die
        # Seite nackt, und JEDE Layout- und Kontrastmessung darunter ist
        # wertlos (genau so entstand ein Kontrast-„Fehler", den es nicht gab).
        wirkt = js(ws, "(function(){var t=document.querySelector('#fb-tabelle .fb-tab');"
                       "return !!t && getComputedStyle(t).borderCollapse === 'collapse';})()")
        if not wirkt:
            print("\nABBRUCH: das Stylesheet greift nicht – Messung waere wertlos.")
            sys.exit(2)
        check("das Stylesheet greift (Positivkontrolle)", bool(wirkt))

        n = js(ws, "document.querySelectorAll('#fb-tabelle tbody tr').length")
        check("sechs Zeilen sind gezeichnet", n == 6, "gemessen: %s" % n)

        # ⚠ GROESSE MESSEN, nicht nur Vorhandensein: in einem versteckten
        # Vorfahren ist jedes Rechteck 0 und jede Schranke trivial wahr.
        masse = js(ws, """(function(){
          var td = document.querySelector('#fb-tabelle td.fb-c-fest');
          var inp = document.querySelector('#fb-tabelle tbody input[type=text]');
          var tab = document.querySelector('#fb-tabelle .fb-tab');
          if(!td||!inp||!tab) return null;
          var a = td.getBoundingClientRect(), b = inp.getBoundingClientRect();
          return {festB: Math.round(a.width), festH: Math.round(a.height),
                  feldB: Math.round(b.width), tabB: Math.round(tab.scrollWidth),
                  boxB: Math.round(document.documentElement.clientWidth),
                  ueber: document.documentElement.scrollWidth
                         > document.documentElement.clientWidth + 1};
        })()""")
        check("die feste Zelle hat eine Groesse (Positivkontrolle)",
              masse and masse["festB"] > 50 and masse["festH"] > 10,
              json.dumps(masse))
        check("das Eingabefeld daneben behaelt Platz",
              masse and masse["feldB"] >= 140,
              "Feldbreite %s" % (masse or {}).get("feldB"))
        check("⚠ kein waagerechter Ueberlauf",
              masse and not masse["ueber"],
              "Tabelle %s px, Fenster %s px" % ((masse or {}).get("tabB"),
                                                (masse or {}).get("boxB")))

        # Kontrast der festen Zelle – sie wird GELESEN.
        kontrast = js(ws, """(function(){
          function rgb(s){var m=s.match(/[\\d.]+/g)||[];return m.slice(0,3).map(Number);}
          function lum(c){var a=c.map(function(v){v/=255;
            return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);});
            return 0.2126*a[0]+0.7152*a[1]+0.0722*a[2];}
          var td=document.querySelector('#fb-tabelle td.fb-c-fest');
          if(!td) return null;
          var vg=rgb(getComputedStyle(td).color);
          // Deckende Flaeche von unten nach oben suchen (halbtransparente
          // Schichten als deckend zu nehmen ergibt Fantasiewerte - Register).
          var el=td,bg=null;
          while(el){var b=getComputedStyle(el).backgroundColor;
            var m=(b.match(/[\\d.]+/g)||[]).map(Number);
            if(m.length>=3 && (m.length<4 || m[3]>0.95)){bg=m.slice(0,3);break;}
            el=el.parentElement;}
          if(!bg) bg=[0,0,0];
          var l1=lum(vg),l2=lum(bg);
          return Math.round(((Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05))*100)/100;
        })()""")
        check("die feste Zelle ist lesbar (>= 4,5:1)",
              isinstance(kontrast, (int, float)) and kontrast >= 4.5,
              "gemessen: %s:1" % kontrast)

        # ⚠ DIE WIRKUNG MESSEN, NICHT DIE KLASSE. Die erste Fassung fragte
        # `classList.contains('hidden')` – und war gruen, waehrend der Knopf im
        # Screenshot deutlich sichtbar dastand: auf dieser Seite gab es gar
        # keine `.hidden`-Regel. Ein Klassen-Check kann das nie sehen.
        sicht = js(ws, "(function(){var b=document.getElementById('fb-zeile-neu');"
                       "if(!b) return {weg:true};var r=b.getBoundingClientRect();"
                       "return {weg:(r.width===0&&r.height===0),"
                       "disp:getComputedStyle(b).display,br:Math.round(r.width)};})()")
        check("⚠ „+ Zeile\" ist WIRKLICH weg (gemalt, nicht nur klassifiziert)",
              sicht and sicht.get("weg"),
              "display=%s, Breite=%s" % ((sicht or {}).get("disp"),
                                         (sicht or {}).get("br")))
        # Bestandsfehler, der dabei mit aufgefallen ist: die Auswahl bei EINEM
        # Formular (Register: „ein Pulldown mit einem Eintrag ist ein
        # Bedienelement ohne Wahl").
        check("die Formular-Auswahl ist bei EINEM Formular wirklich verborgen",
              js(ws, "(function(){var p=document.getElementById('fb-pick');"
                     "if(!p) return true;var r=p.getBoundingClientRect();"
                     "return r.width===0&&r.height===0;})()"))
        check("kein Muelleimer in der Tabelle",
              js(ws, "document.querySelectorAll('#fb-tabelle .fb-row-del').length") == 0)
        check("der Absenden-Knopf ist im Sichtfeld",
              js(ws, "(function(){var b=document.getElementById('fb-senden');"
                     "if(!b) return false; var r=b.getBoundingClientRect();"
                     "return r.width>0 && r.top < innerHeight;})()"))

        bild = cdp(ws, "Page.captureScreenshot", {"format": "png"})
        ziel = BILDER / ("bogen-%s.png" % thema)
        ziel.write_bytes(base64.b64decode(bild["data"]))
        print("     Screenshot: %s" % ziel)
        ws.close()
finally:
    chrome.terminate()
    try:
        chrome.wait(timeout=10)
    except Exception:  # noqa: BLE001
        chrome.kill()
    srv.shutdown()
    # ⚠ Aufraeumen darf das Ergebnis nicht kippen (Register): Chrome schreibt
    # nach `terminate()` noch, `rmtree` laeuft dann in ENOTEMPTY.
    for p in (TMP, PROFIL):
        shutil.rmtree(p, ignore_errors=True)

print("\n" + "=" * 70)
print("\033[1mErgebnis: %d OK, %d FAIL\033[0m" % (_ok, _fail))
sys.exit(1 if _fail else 0)
