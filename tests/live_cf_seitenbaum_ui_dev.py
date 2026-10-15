#!/usr/bin/env python3
"""Optische Abnahme: Confluence-Seitenbaum im /wissen-Informationsextraktor.

Vorgabe 2026-09-27: Seitenauswahl als aufklappbarer Baum (Aeste per Vorgabe
eingeklappt), jede Seite einzeln waehlbar, Haken am Elternteil setzt/entfernt
die Untergeordneten.

jsdom rechnet kein Layout - ob lange Titel umbrechen statt den Container zu
sprengen, ob Einrueckung und Pfeil stimmen und ob der Baum in beiden Themen
lesbar ist, sieht nur ein echter Browser. Gemessen wird die AUSGELIEFERTE
Seite; alle Endpunkte sind gestellt (`Page.addScriptToEvaluateOnNewDocument`),
es geht kein Aufruf an den Dienst und nichts wird importiert.
"""
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

ROOT = Path("/opt/jarvis") if Path("/opt/jarvis/frontend").is_dir() else \
    Path(__file__).resolve().parent.parent
BILDER = Path.home() / ".jarvis-abnahme"
BILDER.mkdir(mode=0o700, exist_ok=True)

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
    """`color-mix` liefert Chrome als `color(srgb a b c)` mit Anteilen 0..1 –
    als 0..255 gelesen ergaebe das fast Schwarz (Register)."""
    s = (s or "").strip()
    m = re.match(r"color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", s)
    if m:
        return tuple(round(float(m.group(i)) * 255) for i in (1, 2, 3))
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        t = [float(x) for x in m.group(1).replace("/", " ").split(",")[:3]]
        return tuple(round(x) for x in t)
    return (0, 0, 0)



LANG = "Ein sehr langer Seitentitel, der in einem schmalen Fenster umbrechen muss, statt seitlich aus dem Baum herauszulaufen – " * 2
PAGES = [
    {"id": "1", "title": "Handbuch", "parent": ""},
    {"id": "11", "title": "Installation", "parent": "1"},
    {"id": "111", "title": LANG, "parent": "11"},
    {"id": "112", "title": "Voraussetzungen", "parent": "11"},
    {"id": "12", "title": "Betrieb", "parent": "1"},
    {"id": "2", "title": "Archiv", "parent": ""},
    {"id": "9", "title": "Verwaiste Seite", "parent": "X"},
]
SPACES = [{"key": "NX", "name": "Contoso Handbuch", "type": "global"}]

VORLAUF = r"""
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
window.addEventListener('unhandledrejection', function (e) {
  window.__fehler += 'ZURUECKWEISUNG: ' + ((e.reason && e.reason.message) || e.reason) + ' | ';
});
try { localStorage.setItem('jarvis_token', 'probe'); localStorage.setItem('jarvis_theme', '__THEMA__'); } catch (e) {}
(function () {
  function antwort(d) {
    return Promise.resolve({ ok: true, status: 200, headers: { get: function () { return null; } },
      json: function () { return Promise.resolve(d); },
      text: function () { return Promise.resolve(JSON.stringify(d)); } });
  }
  window.__rufe = [];
  window.fetch = function (u, o) {
    var url = String(u).split('?')[0];
    var meth = ((o && o.method) || 'GET').toUpperCase();
    window.__rufe.push({ pfad: url, m: meth });
    if (url === '/api/me') return antwort({ is_admin: true, username: 'probe', permissions: {} });
    if (url === '/api/wissen/scope') return antwort({ ok: true, user: 'probe', is_editor: false,
        groups: [{ id: 'g1', name: 'Technik', color: '#888', folders: ['data/rag/x'] }],
        folders: [{ path: 'data/rag/x', name: 'x', display: 'x', root: 'data/rag/x', depth: 0 }] });
    if (url === '/api/wissen/confluence/spaces') return antwort({ ok: true, configured: true, spaces: __SPACES__ });
    if (url === '/api/wissen/confluence/pages') return antwort({ ok: true, pages: __PAGES__ });
    if (url === '/api/wissen/confluence/bindung') return antwort({ ok: true, aktiv: false, bereiche: [] });
    if (url === '/api/wissen/files') return antwort({ ok: true, files: [] });
    return antwort({ ok: true, items: [] });
  };
})();
"""

PROFIL = tempfile.mkdtemp(prefix="chrome-cfbaum-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1400,900",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def ziel_ws():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list",
                                        timeout=2) as a:
                for t in json.loads(a.read()):
                    # NUR type=="page" – /json/list liefert auch Erweiterungen
                    # (Register: sonst haengt man am background.html einer
                    # eingebauten Erweiterung und misst gar nichts).
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:                                          # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


def ende(code):
    chrome.kill()
    shutil.rmtree(PROFIL, ignore_errors=True)
    sys.exit(code)


ws = ziel_ws()
if not ws:
    print("ABBRUCH: kein CDP-Ziel")
    ende(2)
try:
    from websockets.sync.client import connect
except Exception:                                                  # noqa: BLE001
    print("ABBRUCH: python-websockets fehlt im venv.")
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
    r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True,
            awaitPromise=True)
    return (r.get("result") or {}).get("value")


def bild(sock, name):
    r = cdp(sock, "Page.captureScreenshot", format="png")
    p = BILDER / name
    if r.get("data"):
        import base64
        p.write_bytes(base64.b64decode(r["data"]))
        print(f"       Screenshot: {p}")



with connect(ws, open_timeout=20, max_size=60_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    for thema, breite in (("dunkel", 1400), ("hell", 1400), ("dunkel", 420)):
        print(f"\n── {thema} · {breite}px " + "─" * 45)
        cdp(sock, "Emulation.setDeviceMetricsOverride", width=breite, height=900,
            deviceScaleFactor=1, mobile=breite < 600)
        cdp(sock, "Emulation.setEmulatedMedia", media="screen", features=[
            {"name": "prefers-color-scheme", "value": "dark" if thema == "dunkel" else "light"}])
        cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
            source=VORLAUF.replace("__THEMA__", "dark" if thema == "dunkel" else "light")
                          .replace("__SPACES__", json.dumps(SPACES, ensure_ascii=False))
                          .replace("__PAGES__", json.dumps(PAGES, ensure_ascii=False)))
        cdp(sock, "Page.navigate", url="https://127.0.0.1/wissen")
        time.sleep(3.5)
        js(sock, """(function(){document.getElementById('wi-tab-cf').click();
            var i=document.getElementById('wi-cf-space-search'); i.focus();
            i.dispatchEvent(new Event('focus'));})()""")
        time.sleep(0.4)
        js(sock, """(function(){var o=document.querySelector('.wi-cf-opt[data-key="NX"]');
            if(o) o.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true}));})()""")
        time.sleep(0.8)

        fehler = js(sock, "window.__fehler || ''")
        check("keine JS-Fehler auf der Seite", not fehler, fehler or "")
        n = js(sock, "document.querySelectorAll('#wi-cf-tree .wi-cf-cb').length")
        check("POSITIVKONTROLLE: der Baum steht (7 Haken)", n == 7, f"{n}")
        if n != 7:
            ende(2)
        sichtbar = js(sock, """Array.from(document.querySelectorAll('#wi-cf-tree .wi-cf-cb'))
            .filter(function(c){return c.offsetParent!==null;}).length""")
        check("eingeklappt: nur die Wurzeln sichtbar (3)", sichtbar == 3, f"{sichtbar}")
        bild(sock, f"cfbaum-{thema}-{breite}-zu.png")

        # A und A1 aufklappen, Haken an "Installation" (A1) setzen
        js(sock, """(function(){function li(id){return document.querySelector('#wi-cf-tree .wi-cf-cb[value="'+id+'"]').closest('li');}
            li('1').querySelector('.wi-cf-tog').click(); li('11').querySelector('.wi-cf-tog').click();
            document.querySelector('#wi-cf-tree .wi-cf-cb[value="11"]').click();})()""")
        time.sleep(0.3)
        sichtbar = js(sock, """Array.from(document.querySelectorAll('#wi-cf-tree .wi-cf-cb'))
            .filter(function(c){return c.offsetParent!==null;}).length""")
        check("aufgeklappt: 7 Zeilen sichtbar", sichtbar == 7, f"{sichtbar}")
        halb = js(sock, "document.querySelector('#wi-cf-tree .wi-cf-cb[value=\"1\"]').indeterminate")
        check("Handbuch zeigt halben Haken", halb is True)
        mass = js(sock, """(function(){var t=document.getElementById('wi-cf-tree');
            var r=t.getBoundingClientRect(), p=document.getElementById('wi-sec-upload').getBoundingClientRect();
            var rows=Array.from(t.querySelectorAll('.wi-cf-node')).filter(function(n){return n.offsetParent!==null;})
              .map(function(n){var b=n.getBoundingClientRect();return [Math.round(b.top),Math.round(b.bottom),Math.round(b.right)];});
            var ueber=0; for(var i=1;i<rows.length;i++){ if(rows[i][0] < rows[i-1][1]-1) ueber++; }
            var rechts=rows.filter(function(x){return x[2] > r.right+1;}).length;
            var e0=document.querySelector('#wi-cf-tree .wi-cf-cb[value="1"]').getBoundingClientRect().left;
            var e1=document.querySelector('#wi-cf-tree .wi-cf-cb[value="11"]').getBoundingClientRect().left;
            var e2=document.querySelector('#wi-cf-tree .wi-cf-cb[value="111"]').getBoundingClientRect().left;
            return {sw:t.scrollWidth, cw:t.clientWidth, ueber:ueber, rechts:rechts,
                    innen: r.right <= p.right+1, e:[Math.round(e0),Math.round(e1),Math.round(e2)],
                    doc: document.documentElement.scrollWidth, vw: window.innerWidth};})()""")
        check("kein seitlicher Ueberlauf im Baum", mass["sw"] <= mass["cw"] + 1, f"{mass['sw']} > {mass['cw']}")
        check("keine Zeile ragt rechts heraus", mass["rechts"] == 0, str(mass["rechts"]))
        check("Zeilen ueberlappen sich nicht", mass["ueber"] == 0, str(mass["ueber"]))
        check("Baum bleibt im Abschnitt", mass["innen"])
        check("Einrueckung waechst je Ebene", mass["e"][0] < mass["e"][1] < mass["e"][2], str(mass["e"]))
        check("Seite scrollt nicht seitlich", mass["doc"] <= mass["vw"] + 1, f"{mass['doc']} > {mass['vw']}")
        js(sock, "document.getElementById('wi-cf-tree').scrollIntoView({block:'center'})")
        time.sleep(0.2)
        bild(sock, f"cfbaum-{thema}-{breite}-auf.png")

print(f"\nErgebnis: {_ok}/{_ok + _fail}")
ende(1 if _fail else 0)
