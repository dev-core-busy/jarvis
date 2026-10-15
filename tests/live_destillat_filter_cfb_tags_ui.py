#!/usr/bin/env python3
"""Optische Abnahme: Dateifilter im Destillat + Tag-Feld der Confluence-Einbindung, hell UND dunkel.

jsdom rechnet KEIN Layout: ob die beiden Filterfelder nebeneinander stehen (breit)
bzw. untereinander (520 px), ob das Tag-Feld die Containerbreite haelt und ob
die Beschriftungen lesbar sind, beantwortet nur ein echter Browser.

Gemessen wird die EIGENSCHAFT:
  * der Filterkasten oeffnet per ECHTEM Mausklick auf die Ueberschrift,
    die Zahl der aktiven Muster steht auch zugeklappt da,
  * 1280 px: Whitelist und Blacklist NEBENEINANDER (gleiche Oberkante),
    520 px: UNTEREINANDER; keines ragt aus dem Container,
  * Tag-Feld der Einbindung sichtbar, VOR dem Baum, innerhalb des Containers,
  * die Tag-Zeile eines gespeicherten Eintrags ist sichtbar,
  * Kontrast >= 4.5:1 fuer Beschriftungen/Hinweise in BEIDEN Themen,
  * kein waagerechter Ueberlauf der Seite.
Probeseite in einem WEGWERF-Ordner unter HOME. Aufruf: python3 tests/live_destillat_filter_cfb_tags_ui.py
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

ATTRAPPE = """
<script>
(function () {
  try { localStorage.setItem('jarvis_token', 'probe-token'); localStorage.setItem('jarvis_lang', 'de'); } catch (e) {}
  var G = [{ id: 'technik', name: 'Technik', color: '#8b5cf6', folders: [] }];
  function A(k) { return Promise.resolve({ ok: true, status: 200,
                    json: function () { return Promise.resolve(k); },
                    text: function () { return Promise.resolve(JSON.stringify(k)); } }); }
  window.fetch = function (url) {
    var p = String(url).split('?')[0];
    if (p === '/api/wissen/scope') return A({ ok: true, user: 'anna', is_editor: true,
        is_admin: false, groups: G, folders: [] });
    if (p === '/api/wissen/destillat/filter') return A({ ok: true, weiss: ['*.pdf', '*.docx'],
        schwarz: ['*entwurf*', 'archiv/'] });
    if (p === '/api/wissen/confluence/spaces') return A({ ok: true, configured: true,
        spaces: [{ key: 'CONTOSO', name: 'CONTOSO Dokumentation', type: 'global' },
                 { key: 'OPS', name: 'Betrieb', type: 'global' }] });
    if (p === '/api/wissen/confluence/bindung') return A({ ok: true, skill_aktiv: true, configured: true,
        aktiv: true, bereiche: [{ id: 'e1', typ: 'auswahl', name: 'CONTOSO Dokumentation', gruppen: ['technik'],
          gruppen_info: [{ id: 'technik', name: 'Technik', color: '#8b5cf6' }],
          tags: ['handbuch', 'freigegeben', 'kb-how-to-article'],
          auswahl: [{ key: 'CONTOSO', name: 'CONTOSO Dokumentation', start: true, ganz: true, seiten: [], zweige: [] }],
          abgleich: { zeit: '2026-09-27T20:05:00', seiten: 12, offen: 0, fehler: '' } }] });
    return A({ ok: true, pending: [], items: [], spaces: [], status: 'ok', files: [] });
  };
})();
</script>
"""

WEG = Path(tempfile.mkdtemp(prefix="wifilt-", dir=str(Path.home())))
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

PROFIL = tempfile.mkdtemp(prefix="chrome-wifilt-", dir=str(Path.home()))
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

BILDER = Path.home() / "wifilt-bilder"
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
        if js(sock, "!!(document.getElementById('wi-sec-destillat')&&!document.getElementById('wi-sec-destillat').classList.contains('hidden')&&document.getElementById('wi-sec-cfbind').style.display!=='none'&&document.querySelector('#wi-cfb-list .wi-cfb-tagsum'))"):
            break
    js(sock, """['wi-sec-destillat','wi-sec-cfbind'].forEach(function(id){var s=document.getElementById(id);
        if(s&&s.classList.contains('collapsed')){var h=s.querySelector('h2');if(h)h.click();}})""")
    time.sleep(0.3)


def zeigen(sock, sel):
    """Element in den Blick – UNTER die feste Kopfleiste. ⚠ scrollIntoView(true)
    allein schiebt es DARUNTER: der echte Mausklick traf dann die Kopfleiste
    (beim Bau so gemessen)."""
    js(sock, "(function(){var e=document.querySelector(%s);e.scrollIntoView(true);"
             "var k=document.querySelector('.topbar');window.scrollBy(0,-((k?k.getBoundingClientRect().height:60)+24));})()"
       % json.dumps(sel))
    time.sleep(0.3)


def schuss(sock, name, sel):
    zeigen(sock, sel)
    r = cdp(sock, "Page.captureScreenshot", format="png")
    p = BILDER / f"{name}.png"
    p.write_bytes(base64.b64decode(r["data"]))
    return p


def ueberlauf(sock):
    return js(sock, "document.documentElement.scrollWidth - document.documentElement.clientWidth")


def farben(sock, sel):
    return js(sock, """(function(){var e=document.querySelector(%s);if(!e)return null;
        return getComputedStyle(e).color;})()""" % json.dumps(sel))


def filter_messen(sock, thema, breite, hg):
    zeigen(sock, "#wi-dest-filterbox")
    z = js(sock, "document.getElementById('wi-dest-filterzahl').textContent")
    check(f"[{thema}/{breite}] Zahl der Muster steht zugeklappt im Titel", z == "(4 Muster aktiv)", z)
    vor = js(sock, "document.getElementById('wi-dest-filterbox').open")
    check(f"[{thema}/{breite}] (Positivkontrolle) vor dem Klick zu", vor is False, vor)
    m = mitte(sock, "#wi-dest-filterbox > summary")
    check(f"[{thema}/{breite}] Ueberschrift klickbar", bool(m and m["w"] > 0), m)
    if m:
        mausklick(sock, m["x"], m["y"])
    r = js(sock, """(function(){var b=document.getElementById('wi-dest-filterbox'),
        w=document.getElementById('wi-dest-weiss'),s=document.getElementById('wi-dest-schwarz'),
        sec=b.closest('.wi-section').getBoundingClientRect(),rw=w.getBoundingClientRect(),rs=s.getBoundingClientRect();
        return {offen:b.open,sicht:w.checkVisibility?w.checkVisibility({contentVisibilityAuto:true}):null,wT:rw.top,sT:rs.top,wL:rw.left,sL:rs.left,wR:rw.right,sR:rs.right,wH:rw.height,
                secL:sec.left,secR:sec.right,wv:w.value};})()""")
    # ⚠ NICHT am Rechteck: Chrome gibt dem Inhalt eines GESCHLOSSENEN <details>
    # eine Layout-Box (content-visibility) – 114 px Hoehe bei open=false gemessen.
    check(f"[{thema}/{breite}] ECHTER Klick oeffnet den Filterkasten",
          bool(r and r["offen"] is True and r["sicht"] is True), r)
    check(f"[{thema}/{breite}] geladene Muster stehen im Feld", bool(r) and r["wv"] == "*.pdf\n*.docx", r and r["wv"])
    if breite >= 1000:
        check(f"[{thema}/{breite}] Whitelist und Blacklist NEBENEINANDER",
              bool(r) and abs(r["wT"] - r["sT"]) < 2 and r["sL"] > r["wR"], r)
    else:
        check(f"[{thema}/{breite}] schmal: UNTEREINANDER",
              bool(r) and r["sT"] > r["wT"] + r["wH"] - 1 and abs(r["sL"] - r["wL"]) < 2, r)
    check(f"[{thema}/{breite}] beide Felder bleiben im Container",
          bool(r) and r["wR"] <= r["secR"] + 1 and r["sR"] <= r["secR"] + 1 and r["wL"] >= r["secL"] - 1, r)
    for sel, nm in (('label[for="wi-dest-weiss"]', "Beschriftung"), ("#wi-dest-filterbox > .desc", "Hinweis"),
                    ("#wi-dest-filterbox > summary", "Ueberschrift"), ("#wi-dest-weiss", "Feldtext")):
        c = farben(sock, sel)
        kv = kontrast(misch(c, hg), farbe(hg)) if c else 0
        check(f"[{thema}/{breite}] Kontrast {nm} >= 4.5:1", kv >= 4.5, f"{kv:.2f} ({c})")
    check(f"[{thema}/{breite}] kein waagerechter Ueberlauf", (ueberlauf(sock) or 0) <= 0, ueberlauf(sock))


def tags_messen(sock, thema, breite, hg):
    r = js(sock, """(function(){var i=document.getElementById('wi-cfb-tags'),t=document.getElementById('wi-cfb-tree'),
        sec=i.closest('.wi-section').getBoundingClientRect(),ri=i.getBoundingClientRect(),rt=t.getBoundingClientRect(),
        z=document.querySelector('#wi-cfb-list .wi-cfb-tagsum'),rz=z?z.getBoundingClientRect():null;
        return {iW:ri.width,iH:ri.height,iL:ri.left,iR:ri.right,iB:ri.bottom,tT:rt.top,secL:sec.left,secR:sec.right,
                zH:rz?rz.height:0,zR:rz?rz.right:0,zt:z?z.textContent:''};})()""")
    check(f"[{thema}/{breite}] Tag-Feld sichtbar", bool(r and r["iW"] > 100 and r["iH"] > 20), r)
    check(f"[{thema}/{breite}] Tag-Feld steht VOR (ueber) dem Baum", bool(r) and r["iB"] <= r["tT"], r)
    check(f"[{thema}/{breite}] Tag-Feld bleibt im Container",
          bool(r) and r["iL"] >= r["secL"] - 1 and r["iR"] <= r["secR"] + 1, r)
    check(f"[{thema}/{breite}] Tag-Zeile des Eintrags sichtbar und im Container",
          bool(r) and r["zH"] > 0 and r["zR"] <= r["secR"] + 1 and "handbuch" in r["zt"], r)
    for sel, nm in (('label[for="wi-cfb-tags"]', "Tag-Beschriftung"), ('[data-i18n="wissen.cfb_tags_hint"]', "Tag-Hinweis"),
                    ("#wi-cfb-list .wi-cfb-tagsum", "Tag-Zeile")):
        c = farben(sock, sel)
        kv = kontrast(misch(c, hg), farbe(hg)) if c else 0
        check(f"[{thema}/{breite}] Kontrast {nm} >= 4.5:1", kv >= 4.5, f"{kv:.2f} ({c})")


print("=" * 74)
print("Optische Abnahme: Dateifilter (Destillat) + Tags (Confluence-Einbindung)")
print("=" * 74)
bilder = []
try:
    with connect(ws_url, max_size=60 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        cdp(sock, "Runtime.enable")
        gruende = {}
        for thema, breite in (("dark", 1280), ("light", 1280), ("light", 520), ("dark", 520)):
            print(f"\nThema: {thema}, {breite} px")
            laden(sock, thema, breite)
            hg = js(sock, "getComputedStyle(document.body).backgroundColor")
            gruende[thema] = hg
            if not js(sock, "!!document.getElementById('wi-dest-filterbox')&&!!document.getElementById('wi-cfb-tags')"):
                print("ABBRUCH: neue Elemente fehlen – ausgelieferte Seite alt?")
                raeum()
                sys.exit(2)
            check(f"[{thema}/{breite}] (Positivkontrolle) Einbindung sichtbar, Eintrag geladen",
                  bool(js(sock, "!!document.querySelector('#wi-cfb-list .wi-cfb-tagsum')")))
            filter_messen(sock, thema, breite, hg)
            bilder.append(schuss(sock, f"filter-{thema}-{breite}", "#wi-dest-filterbox"))
            tags_messen(sock, thema, breite, hg)
            bilder.append(schuss(sock, f"tags-{thema}-{breite}", ".wi-cfb-tags-wrap"))
            bilder.append(schuss(sock, f"liste-{thema}-{breite}", "#wi-cfb-list"))
        check("Positivkontrolle: hell != dunkel", gruende.get("dark") != gruende.get("light"), gruende)
finally:
    raeum()

print("\nBilder:")
for b in bilder:
    print("  ", b)
print(f"\nErgebnis: {_ok}/{_ok + _fail}")
sys.exit(1 if _fail else 0)
