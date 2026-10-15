#!/usr/bin/env python3
"""Optische Abnahme: "Seite maximieren" (Knopf ⛶ ueber den Kacheln), hell UND dunkel.

jsdom rechnet kein Layout und ignoriert sogar die Spezifitaet – ob
`body.jv-breit [data-jv-breit]` die Deckelung einer Seite wirklich aufhebt, ob
der Knopf sichtbar/klickbar ist und ob er oben rechts ueber den Kacheln steht,
beantwortet nur ein echter Browser.

Gemessen je Seite (Fenster 1400 px):
  * Positivkontrolle: die Seite ist geladen, der Bereich ist gedeckelt
  * der Knopf hat eine Groesse, ist per elementFromPoint erreichbar, steht
    UNTER der Titelleiste, VOR der ersten Kachel und rechtsbuendig zum Bereich
  * ein ECHTER Mausklick macht den Bereich fensterbreit (mindestens +100 px),
    ohne waagerechten Ueberlauf; ein zweiter deckelt wieder
  * der Zustand ueberlebt ein Neuladen
  * Kontrast des Zeichens >= 3:1 (Grafik-Grenze)

Ausgeliefert wird `frontend/` von einem WEGWERF-Server auf 127.0.0.1 (freier
Port) – NICHTS wird unter frontend/ angelegt (Register: test_theme_default
laeuft ueber jede HTML-Datei dort). Angemeldet wird nicht: Token und fetch-
Attrappe stehen VOR dem ersten Skript der Seite
(Page.addScriptToEvaluateOnNewDocument), sonst leitet die Seite aufs Portal um.

Aufruf: python3 tests/live_seite_breit_ui.py   (braucht google-chrome, websockets)
Exit 0 = gruen, 1 = Fehler, 2 = konnte nicht laufen.
"""
import base64
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "frontend"
BILDER = Path.home() / ".jarvis-abnahme"
BILDER.mkdir(mode=0o700, exist_ok=True)

# Route -> (HTML-Datei, Selektor der ersten Kachel)
SEITEN = {
    # Gemessen wird gegen die erste GEZEICHNETE Kachel (Hoehe > 0): /wissen
    # blendet Abschnitte ohne Freigabe aus.
    "/wissen":       ("wissen.html", ".wi-section"),
    "/feedback":     ("feedback.html", ".ja-card"),
    "/tracks":       ("tracks.html", ".st-card"),
    "/support":      ("support.html", ".sup-search-card"),
    "/sap":          ("sap.html", ".sp-card"),
    "/vemas":        ("vemas.html", ".vm-card"),
    "/email":        ("email.html", ".em-card"),
    "/excel":        ("excel.html", ".xp-card"),
    "/jira-addon":   ("jira_addon.html", ".ja-card"),
    "/ai-mouse":     ("ai_mouse.html", ".ja-card"),
    "/claude":       ("claude.html", ".cs-card"),
    "/supportagent": ("supportagent.html", ".sa-download-card"),
    "/api":          ("api.html", None),
}

# `SEITEN_NUR=/feedback,/api` misst nur diese Routen (fuer die Gegenprobe).
if os.environ.get("SEITEN_NUR"):
    _nur = [x.strip() for x in os.environ["SEITEN_NUR"].split(",") if x.strip()]
    if not _nur or any(x not in SEITEN for x in _nur):
        print(f"ABBRUCH: SEITEN_NUR unbekannt: {_nur}")
        sys.exit(2)
    SEITEN = {k: v for k, v in SEITEN.items() if k in _nur}

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
    """`color-mix` liefert Chrome als `color(srgb a b c)` mit Anteilen 0..1."""
    s = (s or "").strip()
    m = re.match(r"color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", s)
    if m:
        return tuple(round(float(m.group(i)) * 255) for i in (1, 2, 3))
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        t = [float(x) for x in m.group(1).replace("/", " ").split(",")[:3]]
        return tuple(round(x) for x in t)
    return (0, 0, 0)


# ── Wegwerf-Server: /static/* -> frontend/*, Routen -> HTML ──────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def translate_path(self, path):
        p = path.split("?", 1)[0].split("#", 1)[0]
        if p in SEITEN:
            return str(FRONT / SEITEN[p][0])
        if p.startswith("/static/"):
            ziel = (FRONT / p[len("/static/"):]).resolve()
            if FRONT.resolve() in ziel.parents:
                return str(ziel)
        return str(FRONT / "__gibt_es_nicht__")


def freier_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


WEB = freier_port()
server = http.server.ThreadingHTTPServer(("127.0.0.1", WEB), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()

# Wird VOR dem ersten Skript der Seite ausgefuehrt. Jede Freigabe "ja"
# (Proxy), jede andere Anfrage eine leere Erfolgsantwort – gemessen wird das
# Layout, nicht die Fachlogik.
VORLAUF = r"""
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += (e.message || 'Ladefehler') + ' | '; });
try {
  localStorage.setItem('jarvis_token', 'probe');
  localStorage.setItem('jarvis_theme', '__THEMA__');
  localStorage.setItem('jarvis_lang', 'de');
  if (!sessionStorage.getItem('__breit_rein')) {
    Object.keys(localStorage).forEach(function (k) {
      if (k.indexOf('jarvis_breit_') === 0) localStorage.removeItem(k); });
    sessionStorage.setItem('__breit_rein', '1');
  }
} catch (e) {}
(function () {
  var alles = new Proxy({}, { get: function () { return true; }, has: function () { return true; } });
  function antwort(d) {
    return Promise.resolve({ ok: true, status: 200, headers: { get: function () { return null; } },
      json: function () { return Promise.resolve(d); },
      text: function () { return Promise.resolve(JSON.stringify(d)); } });
  }
  window.fetch = function (u) {
    var url = String(u).split('?')[0];
    if (url === '/api/me') {
      return antwort({ username: 'probe', is_admin: true, permissions: alles });
    }
    // /wissen hat eine EIGENE Anmeldung ueber den Bereich (Form wie der
    // Endpunkt) – ohne sie stuende die Anmeldemaske ueber der Seite.
    if (url === '/api/wissen/scope') {
      return antwort({ ok: true, user: 'probe', is_editor: false, is_admin: false,
                       groups: [], folders: [] });
    }
    if (url === '/api/wissen/files') { return antwort({ ok: true, files: [] }); }
    return antwort({ ok: true });
  };
})();
"""

PROFIL = tempfile.mkdtemp(prefix="chrome-breit-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
PORT = freier_port()
if not Path("/usr/bin/google-chrome").exists():
    print("ABBRUCH: /usr/bin/google-chrome fehlt")
    sys.exit(2)
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1400,900", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def ende(code):
    chrome.kill()
    server.shutdown()
    shutil.rmtree(PROFIL, ignore_errors=True)
    sys.exit(code)


def ziel_ws():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as a:
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:                                          # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


print("=" * 74)
print("Optische Abnahme: Seite maximieren (Knopf ueber den Kacheln)")
print("=" * 74)
ws = ziel_ws()
if not ws:
    print("ABBRUCH: kein CDP-Ziel")
    ende(2)
try:
    from websockets.sync.client import connect
except Exception:                                                  # noqa: BLE001
    print("ABBRUCH: python-websockets fehlt.")
    ende(2)

_id = [0]


def cdp(sock, m, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": m, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=30))
        if d.get("id") == _id[0]:
            return d.get("result", {})


def js(sock, a):
    r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def bild(sock, name):
    r = cdp(sock, "Page.captureScreenshot", format="png")
    if r.get("data"):
        p = BILDER / name
        p.write_bytes(base64.b64decode(r["data"]))
        return p
    return None


def mausklick(sock, x, y):
    for t in ("mousePressed", "mouseReleased"):
        cdp(sock, "Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1)


# Den gedeckelten Bereich sichtbar machen, falls die Seite ihn hinter einem
# Ladezustand haelt (`.hidden` an einem Vorfahren) – NUR die Vorfahren, sonst
# erschienen fremde Bloecke und verfaelschten die Lage.
SICHTBAR = """(function(){var b=document.querySelector('[data-jv-breit]');if(!b)return false;
for(var e=b;e&&e!==document.body;e=e.parentElement){e.classList.remove('hidden');
if(e.style.display==='none')e.style.display='';}return true;})()"""

MESSEN = """(function(sel){var b=document.querySelector('[data-jv-breit]'),k=document.getElementById('jv-max');
if(!b||!k)return null;var r=b.getBoundingClientRect(),q=k.getBoundingClientRect(),cs=getComputedStyle(b);
var t=document.querySelector('header, .topbar, .wi-topbar, .sa-topbar, .ad-top');var tb=t?t.getBoundingClientRect().bottom:0;
var c=null;if(sel){[].some.call(document.querySelectorAll('[data-jv-breit] '+sel),function(x){if(x.getBoundingClientRect().height>0){c=x;return true;}return false;});}
var ct=c?c.getBoundingClientRect().top:null;
var inhaltRechts=r.right-parseFloat(cs.paddingRight||0);
return {bw:Math.round(r.width),mw:cs.maxWidth,vw:document.documentElement.clientWidth,
kx:Math.round(q.left+q.width/2),ky:Math.round(q.top+q.height/2),kw:Math.round(q.width),kh:Math.round(q.height),
kr:Math.round(q.right),kt:Math.round(q.top),kb:Math.round(q.bottom),ir:Math.round(inhaltRechts),tb:Math.round(tb),ct:ct==null?null:Math.round(ct),
ueber:document.documentElement.scrollWidth-document.documentElement.clientWidth,
an:document.body.classList.contains('jv-breit'),fehler:window.__fehler||''};})(%s)"""

bilder = []
with connect(ws, open_timeout=20, max_size=60_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    for thema in ("dunkel", "hell"):
        cdp(sock, "Emulation.setEmulatedMedia", media="screen", features=[
            {"name": "prefers-color-scheme", "value": "dark" if thema == "dunkel" else "light"}])
        skript = cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
                     source=VORLAUF.replace("__THEMA__", "dark" if thema == "dunkel" else "light"))
        for route, (datei, karte) in SEITEN.items():
            print(f"\n── {thema} {route} " + "─" * max(4, 50 - len(route)))
            # sessionStorage einmal je Seite leeren -> gemerkter Zustand frisch.
            cdp(sock, "Page.navigate", url=f"http://127.0.0.1:{WEB}/__leer__")
            time.sleep(0.2)
            js(sock, "try{sessionStorage.clear()}catch(e){}")
            cdp(sock, "Page.navigate", url=f"http://127.0.0.1:{WEB}{route}")
            time.sleep(1.6)
            ort = js(sock, "location.pathname")
            check("Positivkontrolle: die Seite ist geladen (keine Umleitung)", ort == route, str(ort))
            if ort != route:
                continue
            js(sock, SICHTBAR)
            time.sleep(0.2)
            sel = json.dumps(karte) if karte else "null"
            v = js(sock, MESSEN % sel)
            check("Knopf und Bereich vorhanden", bool(v), str(v))
            if not v:
                continue
            check("Positivkontrolle: der Bereich ist gedeckelt und schmaler als das Fenster",
                  v["mw"].endswith("px") and v["bw"] < v["vw"] - 100, f"{v['bw']} px / max {v['mw']} / {v['vw']}")
            check("der Knopf hat eine Groesse", v["kw"] > 15 and v["kh"] > 15, f"{v['kw']}x{v['kh']}")
            check("… steht unter der Titelleiste", v["kt"] >= v["tb"] - 1, f"oben {v['kt']} / Leiste {v['tb']}")
            if v["ct"] is not None:
                check("… und VOR der ersten Kachel", v["kb"] <= v["ct"] + 1, f"unten {v['kb']} / Kachel {v['ct']}")
            if route != "/api":
                check("… rechtsbuendig zum Inhaltsbereich", abs(v["kr"] - v["ir"]) <= 2, f"{v['kr']} / {v['ir']}")
            treffer = js(sock, f"(function(){{var e=document.elementFromPoint({v['kx']},{v['ky']});"
                               "return !!(e&&e.closest('#jv-max'));})()")
            check("… ist per elementFromPoint erreichbar", bool(treffer))
            vg = farbe(js(sock, "getComputedStyle(document.getElementById('jv-max')).color"))
            hg = farbe(js(sock, "getComputedStyle(document.body).backgroundColor"))
            k = kontrast(vg, hg)
            check(f"… Zeichen erkennbar (Kontrast {k:.2f}:1 >= 3:1)", k >= 3.0, f"{vg} auf {hg}")
            vor = v["bw"]
            if thema == "dunkel" and route in ("/feedback", "/tracks"):
                bilder.append(bild(sock, f"breit-{route[1:]}-{thema}-1-normal.png"))

            mausklick(sock, v["kx"], v["ky"])
            time.sleep(0.3)
            n = js(sock, MESSEN % sel)
            check("echter Klick: body.jv-breit", n["an"] is True)
            check("… Bereich jetzt fensterbreit (mindestens +100 px)",
                  n["mw"] == "none" and n["bw"] >= vor + 100 and n["bw"] >= n["vw"] - 80,
                  f"{vor} -> {n['bw']} px (Fenster {n['vw']}, max {n['mw']})")
            check("… kein waagerechter Ueberlauf", n["ueber"] <= 1, f"{n['ueber']} px")
            if route != "/api":
                check("… Knopf bleibt rechtsbuendig", abs(n["kr"] - n["ir"]) <= 2, f"{n['kr']} / {n['ir']}")
            p = bild(sock, f"breit-{route[1:]}-{thema}-2-maximiert.png")
            bilder.append(p)

            # Neuladen: gemerkt (sessionStorage-Marke verhindert das Leeren)
            cdp(sock, "Page.reload")
            time.sleep(1.6)
            js(sock, SICHTBAR)
            time.sleep(0.2)
            r = js(sock, MESSEN % sel)
            check("nach Neuladen weiter breit (je Browser gemerkt)",
                  bool(r) and r["an"] is True and r["mw"] == "none", str(r and r["mw"]))
            if r:
                mausklick(sock, r["kx"], r["ky"])
                time.sleep(0.3)
                z = js(sock, MESSEN % sel)
                check("zweiter Klick: wieder gedeckelt", z["an"] is False and abs(z["bw"] - vor) <= 1,
                      f"{z['bw']} / vorher {vor}")
            f = js(sock, "window.__fehler || ''")
            if f:
                print(f"       (Seitenfehler ohne Bezug zum Knopf: {f[:160]})")
        cdp(sock, "Page.removeScriptToEvaluateOnNewDocument", identifier=skript.get("identifier"))

print("\nScreenshots:", BILDER)
print("\n" + "=" * 74)
print(f"{_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
