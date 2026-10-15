#!/usr/bin/env python3
"""Optische Abnahme: Lesefortschritt + Protokoll im Wissens-Destillat (/wissen), hell UND dunkel.

jsdom rechnet KEIN Layout und keine Animation: ob der Drehkreis sich WIRKLICH
dreht, ob ein langer Ordnerpfad die Fortschrittszeile sprengt und ob das
Protokoll lesbar ist, beantwortet nur ein echter Browser.

Gemessen wird die EIGENSCHAFT:
  * waehrend des Lesens: Drehkreis sichtbar UND animiert (wiSpin laeuft),
    Text "Lese Datei 2 von 3: …", Balken sichtbar mit ~33 %
  * ein unteilbar langer Pfad sprengt die Zeile nicht (Ellipse, kein
    waagerechter Ueberlauf der Seite) – auch bei 520 px
  * nach dem Ende: Protokoll per ECHTEM Mausklick auf, jede Datei eine Zeile,
    Name und Grund mit Kontrast >= 4.5:1 in BEIDEN Themen
Probeseite in einem WEGWERF-Ordner unter HOME. Aufruf: python3 tests/live_wissen_destillat_fortschritt_ui.py
"""
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


def leucht(c):
    def k(x):
        x /= 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * k(c[0]) + 0.7152 * k(c[1]) + 0.0722 * k(c[2])


def kontrast(a, b):
    la, lb = leucht(a), leucht(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def farbe(s):
    s = (s or "").strip()
    m = re.match(r"color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", s)
    if m:
        return tuple(round(float(m.group(i)) * 255) for i in (1, 2, 3))
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        t = [float(x) for x in m.group(1).replace("/", " ").split(",")[:3]]
        return tuple(round(x) for x in t)
    return (0, 0, 0)


def misch(vg, hg):
    """Halbdurchsichtige Farbe ueber den Grund legen – als deckend gelesen
    kaeme ein Traumwert heraus (Register)."""
    m = re.match(r"rgba\(([^)]+)\)", (vg or "").strip())
    if not m:
        return farbe(vg)
    t = [float(x) for x in m.group(1).split(",")]
    if len(t) < 4:
        return farbe(vg)
    h = farbe(hg)
    return tuple(round(t[i] * t[3] + h[i] * (1 - t[3])) for i in range(3))


HTML = (ROOT / "frontend" / "wissen.html").read_text(encoding="utf-8")

LANG = "Projektablage/" + "Unterordner_mit_einem_sehr_langen_Namen_" * 4 + "Anlage.pdf"
ATTRAPPE = """
<script>
(function () {
  try { localStorage.setItem('jarvis_token', 'probe-token'); localStorage.setItem('jarvis_lang', 'de'); } catch (e) {}
  var G = [{ id: 'technik', name: 'Technik', color: '#8b5cf6', folders: [] }];
  function A(k) { return Promise.resolve({ ok: true, status: 200,
                    json: function () { return Promise.resolve(k); },
                    text: function () { return Promise.resolve(JSON.stringify(k)); } }); }
  // Selbst gesteuerter Strom: window.__schick(obj) liefert eine NDJSON-Zeile.
  window.__schick = null; window.__ende = null;
  window.fetch = function (url) {
    var p = String(url).split('?')[0];
    if (p === '/api/wissen/destillat/extract') {
      var enc = new TextEncoder();
      var body = new ReadableStream({ start: function (c) {
        window.__schick = function (o) { c.enqueue(enc.encode(JSON.stringify(o) + '\\n')); };
        window.__ende = function () { c.close(); };
      } });
      return Promise.resolve(new Response(body, { status: 200,
        headers: { 'Content-Type': 'application/x-ndjson' } }));
    }
    if (p === '/api/wissen/scope') return A({ ok: true, user: 'anna', is_editor: true,
        is_admin: false, groups: G, folders: [] });
    return A({ ok: true, pending: [], spaces: [], status: 'ok', files: [] });
  };
})();
</script>
"""

WEG = Path(tempfile.mkdtemp(prefix="widest-", dir=str(Path.home())))
os.chmod(WEG, 0o755)
(WEG / "static").mkdir()
for teil in ("css", "js", "vendor"):
    if (ROOT / "frontend" / teil).exists():
        (WEG / "static" / teil).symlink_to(ROOT / "frontend" / teil)
(WEG / "probe.html").write_text(HTML.replace("<body", ATTRAPPE + "<body", 1), encoding="utf-8")

srv = subprocess.Popen([sys.executable, "-u", "-m", "http.server", "0", "--bind", "127.0.0.1"],
                       cwd=str(WEG), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
HTTP_PORT = None
for _ in range(40):
    m = re.search(r"port (\d+)", srv.stdout.readline() or "")
    if m:
        HTTP_PORT = int(m.group(1))
        break
if not HTTP_PORT:
    print("ABBRUCH: kein HTTP-Port.")
    srv.kill()
    shutil.rmtree(WEG, ignore_errors=True)
    sys.exit(2)
BASIS = f"http://127.0.0.1:{HTTP_PORT}"

PROFIL = tempfile.mkdtemp(prefix="chrome-widest-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
_s = socket.socket()
_s.bind(("127.0.0.1", 0))
PORT = _s.getsockname()[1]
_s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1280,1000", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

BILDER = Path.home() / "widest-bilder"
BILDER.mkdir(exist_ok=True)


def cdp_ziel():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as a:
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


def raeum():
    for pr in (chrome, srv):
        try:
            pr.kill()
        except Exception:  # noqa: BLE001
            pass
    shutil.rmtree(PROFIL, ignore_errors=True)
    shutil.rmtree(WEG, ignore_errors=True)


ws_url = cdp_ziel()
if not ws_url:
    print("ABBRUCH: kein CDP-Ziel")
    raeum()
    sys.exit(2)
from websockets.sync.client import connect  # noqa: E402

_id = [0]


def cdp(sock, methode, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": methode, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=30))
        if d.get("id") == _id[0]:
            return d.get("result", {})


def js(sock, ausdruck):
    r = cdp(sock, "Runtime.evaluate", expression=ausdruck, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def mausklick(sock, x, y):
    """ECHTER Klick – ein element.click() aus JS umginge Treffer-Pruefung und
    Ueberdeckung, um die es hier geht."""
    for typ in ("mousePressed", "mouseReleased"):
        cdp(sock, "Input.dispatchMouseEvent", type=typ, x=x, y=y, button="left", clickCount=1)
    time.sleep(0.2)


def mitte(sock, sel):
    return js(sock, f"""(function(){{var e=document.querySelector({json.dumps(sel)});
        if(!e)return null;var r=e.getBoundingClientRect();
        return {{x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height}};}})()""")


def laden(sock, thema, breite=1280):
    cdp(sock, "Emulation.setDeviceMetricsOverride", width=breite, height=1000,
        deviceScaleFactor=1, mobile=False)
    cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
        source=("try{localStorage.setItem('jarvis_theme',%r);}catch(e){}" % thema))
    cdp(sock, "Page.navigate", url=f"{BASIS}/probe.html")
    for _ in range(80):
        time.sleep(0.15)
        if js(sock, "!!(document.getElementById('wi-sec-destillat')&&!document.getElementById('wi-sec-destillat').classList.contains('hidden'))"):
            break
    js(sock, """(function(){var s=document.getElementById('wi-sec-destillat');
        if(s&&s.classList.contains('collapsed')){var h=s.querySelector('h2');if(h)h.click();}})()""")
    time.sleep(0.3)


def ablegen(sock):
    js(sock, """(function(){var i=document.getElementById('wi-dest-files');
        var dt=new DataTransfer();
        ['a.pdf','b.one',%s].forEach(function(n){dt.items.add(new File(['x'],n));});
        i.files=dt.files; i.dispatchEvent(new Event('change'));})()""" % json.dumps(LANG))
    time.sleep(0.3)


def schuss(sock, name):
    js(sock, "document.getElementById('wi-dest-exbusy').closest('.wi-section').scrollIntoView(true)")
    time.sleep(0.3)
    r = cdp(sock, "Page.captureScreenshot", format="png")
    p = BILDER / f"{name}.png"
    p.write_bytes(base64.b64decode(r["data"]))
    return p


def ueberlauf(sock):
    return js(sock, "document.documentElement.scrollWidth - document.documentElement.clientWidth")


print("=" * 74)
print("Optische Abnahme: Lesefortschritt + Protokoll (Wissens-Destillat)")
print("=" * 74)
bilder = []
try:
    with connect(ws_url, max_size=60 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        cdp(sock, "Runtime.enable")
        gruende = {}
        for thema in ("dark", "light"):
            print(f"\nThema: {thema}")
            laden(sock, thema)
            # Positivkontrolle: die Themen unterscheiden sich wirklich.
            gruende[thema] = js(sock, "getComputedStyle(document.body).backgroundColor")
            if not js(sock, "!!document.getElementById('wi-dest-exbusy')"):
                print("ABBRUCH: Fortschritts-Element fehlt – ausgelieferte Seite alt?")
                raeum()
                sys.exit(2)
            ablegen(sock)
            js(sock, "window.__schick({art:'datei',i:1,n:3,name:'a.pdf'})")
            js(sock, "window.__schick({art:'datei',i:2,n:3,name:%s})" % json.dumps(LANG))
            time.sleep(0.6)
            z = js(sock, """(function(){var b=document.getElementById('wi-dest-exbusy'),
                s=b.querySelector('.wi-busy-spin'),t=document.getElementById('wi-dest-exbusy-text'),
                f=document.getElementById('wi-dest-exfill'),bar=document.getElementById('wi-dest-exbar'),
                rs=s.getBoundingClientRect(),rb=b.getBoundingClientRect(),rt=t.getBoundingClientRect(),
                sec=b.closest('.wi-section').getBoundingClientRect();
                var a=s.getAnimations?s.getAnimations():[];
                return {sicht:rb.height>0, spinW:rs.width, anim:getComputedStyle(s).animationName,
                  laeuft:a.some(function(x){return x.playState==='running';}),
                  text:t.textContent, textR:rt.right, secR:sec.right, clip:t.scrollWidth>t.clientWidth,
                  fill:f.getBoundingClientRect().width/Math.max(1,bar.getBoundingClientRect().width)};})()""")
            check("Drehkreis sichtbar", bool(z and z["sicht"] and z["spinW"] > 10), z)
            check("… und dreht sich (Animation wiSpin laeuft)",
                  bool(z) and z["anim"] == "wiSpin" and z["laeuft"], z and (z["anim"], z["laeuft"]))
            check('Text "Lese Datei 2 von 3"', bool(z) and z["text"].startswith("Lese Datei 2 von 3"), z and z["text"][:40])
            check("langer Pfad bleibt im Container (Ellipse)",
                  bool(z) and z["textR"] <= z["secR"] + 1 and z["clip"], z and (z["textR"], z["secR"]))
            check("Balken ~33 %", bool(z) and abs(z["fill"] - 1 / 3) < 0.05, z and z["fill"])
            # ⚠ AM LAYOUT, nicht an `hidden`: `.sec-btn` setzte `display` und
            # schlug das Attribut – jsdom meldete "verborgen", das Bild zeigte ihn.
            mk = mitte(sock, "#wi-dest-logbtn")
            check("Protokoll-Knopf ist waehrend des Lesens NICHT zu sehen",
                  bool(mk) and mk["w"] == 0 and mk["h"] == 0, mk)
            check("kein waagerechter Ueberlauf der Seite", (ueberlauf(sock) or 0) <= 0, ueberlauf(sock))
            bilder.append(schuss(sock, f"lesen-{thema}"))

            js(sock, "window.__schick({art:'datei',i:3,n:3,name:'b.one'})")
            js(sock, """window.__schick({art:'fertig',ok:['a.pdf',%s],text:'--- a.pdf ---\\nA',
                fehler:{'b.one':'OneNote-Dateien brauchen den Tika-Dienst – er ist nicht erreichbar.'},gekappt:false,
                protokoll:[{name:'a.pdf',art:'ok',zeichen:12345,bilder:2},
                  {name:'b.one',art:'fehler',grund:'OneNote-Dateien brauchen den Tika-Dienst – er ist nicht erreichbar.'},
                  {name:%s,art:'ok',zeichen:77}]}); window.__ende();""" % (json.dumps(LANG), json.dumps(LANG)))
            time.sleep(0.6)
            m = mitte(sock, "#wi-dest-logbtn")
            check("Protokoll-Knopf sichtbar", bool(m and m["w"] > 0 and m["h"] > 0), m)
            if m:
                mausklick(sock, m["x"], m["y"])
            p = js(sock, """(function(){var l=document.getElementById('wi-dest-log');
                var z=l.querySelectorAll('.wi-dest-logzeile');
                var f=l.querySelector('.wi-dest-logzeile.fehler');
                function k(e){return e?[getComputedStyle(e).color]:null;}
                return {offen:!l.hidden&&l.getBoundingClientRect().height>0, n:z.length,
                  nm:k(f&&f.querySelector('.nm')), gr:k(f&&f.querySelector('.gr')),
                  lr:l.getBoundingClientRect().right, sr:l.closest('.wi-section').getBoundingClientRect().right};})()""")
            check("ECHTER Klick oeffnet das Protokoll mit 3 Zeilen", bool(p and p["offen"] and p["n"] == 3), p)
            check("Protokoll bleibt im Container", bool(p) and p["lr"] <= p["sr"] + 1, p and (p["lr"], p["sr"]))
            hg = gruende[thema]
            # Der Protokollgrund ist rgba(fg, .03) ueber dem Abschnitt – fuer den
            # Kontrast zaehlt der Seitengrund (Abweichung < 1 %).
            for teil in ("nm", "gr"):
                if p and p[teil]:
                    kv = kontrast(misch(p[teil][0], hg), farbe(hg))
                    check(f"Kontrast Protokoll-{teil} >= 4.5:1", kv >= 4.5, f"{kv:.2f}")
            check("kein waagerechter Ueberlauf mit offenem Protokoll", (ueberlauf(sock) or 0) <= 0)
            bilder.append(schuss(sock, f"protokoll-{thema}"))
        check("Positivkontrolle: hell != dunkel", gruende.get("dark") != gruende.get("light"), gruende)

        print("\nSchmal (520 px, hell):")
        laden(sock, "light", breite=520)
        ablegen(sock)
        js(sock, "window.__schick({art:'datei',i:2,n:3,name:%s})" % json.dumps(LANG))
        time.sleep(0.5)
        check("520 px: kein waagerechter Ueberlauf waehrend des Lesens", (ueberlauf(sock) or 0) <= 0, ueberlauf(sock))
        bilder.append(schuss(sock, "lesen-520"))
finally:
    raeum()

print("\nBilder:")
for b in bilder:
    print("  ", b)
print(f"\nErgebnis: {_ok}/{_ok + _fail}")
sys.exit(1 if _fail else 0)
