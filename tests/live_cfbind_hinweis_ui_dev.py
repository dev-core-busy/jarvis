#!/usr/bin/env python3
"""Optische Abnahme: der rote Warnhinweis der Confluence-Einbindung.

Vorgabe 2026-09-21: der Hinweis in *Dynamische Confluence-Einbindung* soll
DEUTLICH (rot) sagen, dass der Bereich noch nicht produktiv verwendbar ist.

⚠ GEMESSEN WIRD DIE AUSGELIEFERTE SEITE, nicht ein Markup-Schnitt - nur so ist
das echte CSS dabei, und genau darum geht es hier: --danger liegt im hellen
Thema bei 3,45:1 und damit UNTER der Grenze. Ein Kontrast, den man schaetzt,
ist im Projekt schon mehrfach falsch gewesen.

Angemeldet wird nicht: `fetch` und `localStorage` werden VOR dem ersten Skript
der Seite gestellt (`Page.addScriptToEvaluateOnNewDocument`).
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


BEREICHE = [
    {"key": "IBS", "name": "IBS Handbuch", "typ": "space", "inkl_unter": True},
    {"key": "~vorname.name@firma.de", "name": "Persoenlicher Bereich",
     "typ": "space", "inkl_unter": False},
]

# Wird VOR dem ersten Skript der Seite ausgefuehrt.
VORLAUF = r"""
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
window.addEventListener('unhandledrejection', function (e) {
  window.__fehler += 'ZURUECKWEISUNG: ' + ((e.reason && e.reason.message) || e.reason) + ' | ';
});
try {
  localStorage.setItem('jarvis_token', 'probe');
  localStorage.setItem('jarvis_theme', '__THEMA__');
} catch (e) {}
(function () {
  function antwort(d) {
    return Promise.resolve({ ok: true, status: 200, headers: { get: function () { return null; } },
      json: function () { return Promise.resolve(d); },
      text: function () { return Promise.resolve(JSON.stringify(d)); } });
  }
  window.fetch = function (u, o) {
    var url = String(u).split('?')[0];
    if (url === '/api/me') { return antwort({ is_admin: true, username: 'probe', permissions: {} }); }
    if (url === '/api/wissen/confluence/bindung') {
      return antwort({ ok: true, aktiv: true, bereiche: __BEREICHE__ });
    }
    if (url === '/api/wissen/scope') { return antwort({ ok: true, groups: [], folders: [] }); }
    if (url === '/api/wissen/files') { return antwort({ ok: true, files: [] }); }
    if (url === '/api/knowledge/pending') { return antwort({ ok: true, items: [] }); }
    return antwort({ ok: true });
  };
})();
"""

PROFIL = tempfile.mkdtemp(prefix="chrome-cfb-", dir=str(Path.home()))
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


print("=" * 74)
print("Optische Abnahme: Warnhinweis der Confluence-Einbindung")
print("=" * 74)

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


RECHTECK = """(function(){var e=document.querySelector('%s');if(!e)return null;
var r=e.getBoundingClientRect();
return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),
        h:Math.round(r.height),b:Math.round(r.bottom)};})()"""

with connect(ws, open_timeout=20, max_size=60_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    gemessen = {}

    for thema in ("dunkel", "hell"):
        print(f"\n── {thema} " + "─" * 55)
        cdp(sock, "Emulation.setEmulatedMedia", media="screen", features=[
            {"name": "prefers-color-scheme",
             "value": "dark" if thema == "dunkel" else "light"}])
        cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
            source=VORLAUF.replace("__THEMA__",
                                   "dark" if thema == "dunkel" else "light")
                          .replace("__BEREICHE__",
                                   json.dumps(BEREICHE, ensure_ascii=False)))
        cdp(sock, "Page.navigate", url="https://127.0.0.1/wissen")
        time.sleep(3.5)

        # ── Positivkontrollen: ohne sie ist alles darunter trivial wahr ─────
        fehler = js(sock, "window.__fehler || ''")
        check("keine JS-Fehler auf der Seite", not fehler, fehler or "")
        auf = js(sock, "(function(){var s=document.getElementById('wi-sec-cfbind');"
                       "if(!s)return 'fehlt';"
                       "if(getComputedStyle(s).display==='none')return 'zu';"
                       "return 'da';})()")
        check("der Container ist ueberhaupt sichtbar", auf == "da", str(auf))

        r = js(sock, RECHTECK % ".wi-cfb-soon")
        check("der Hinweis hat eine Flaeche (POSITIVKONTROLLE)",
              bool(r) and r["h"] > 0 and r["w"] > 0,
              json.dumps(r) if r else "nicht gefunden")

        txt = js(sock, "(function(){var e=document.querySelector('.wi-cfb-soon');"
                       "return e?e.textContent.trim():'';})()")
        check("er sagt, dass es noch nicht produktiv verwendbar ist",
              "produktiv" in txt.lower(), txt[:70])
        check("und er nennt das Datum", "21.09.2026" in txt)

        # ⚠ DIE SCHICHTEN MUESSEN ZUSAMMENGERECHNET WERDEN. Der Hinweis liegt
        # auf rgba(...,0.08) - wer die als deckend liest, misst rot auf rot und
        # meldet 1,47:1 statt des wirklichen Werts (Register, eigener Messfehler
        # in genau diesem Lauf).
        vg = js(sock, """(function(){
          var e=document.querySelector('.wi-cfb-soon'); if(!e) return null;
          var c=getComputedStyle(e), g=e, lagen=[];
          while(g){ var b=getComputedStyle(g).backgroundColor;
            var m=/rgba?\\(([^)]+)\\)/.exec(b);
            if(m){ var t=m[1].split(',').map(parseFloat);
              var a=t.length>3?t[3]:1;
              if(a>0){ lagen.push([t[0],t[1],t[2],a]); if(a>=1) break; } }
            g=g.parentElement; }
          if(!lagen.length||lagen[lagen.length-1][3]<1) lagen.push([255,255,255,1]);
          var out=lagen[lagen.length-1].slice(0,3);
          for(var i=lagen.length-2;i>=0;i--){ var l=lagen[i];
            out=[0,1,2].map(function(k){return l[k]*l[3]+out[k]*(1-l[3]);}); }
          return {fg:c.color, bg:'rgb('+out.map(Math.round).join(', ')+')',
                  fw:c.fontWeight, lagen:lagen.length};})()""")
        if vg:
            fg, bg = farbe(vg["fg"]), farbe(vg["bg"])
            k = kontrast(fg, bg)
            gemessen[thema] = (vg["fg"], round(k, 2))
            check(f"Kontrast des Hinweises >= 4,5:1 (gemessen {k:.2f}:1)", k >= 4.5,
                  f"fg={vg['fg']} bg={vg['bg']}")
            check("die Schrift ist rot (roter Kanal dominiert)",
                  fg[0] > fg[1] + 40 and fg[0] > fg[2] + 40, str(fg))
            check("halbfett abgesetzt", int(vg["fw"]) >= 600, vg["fw"])
        else:
            check("Hinweis messbar", False, "kein Element")

        ue = js(sock, "document.documentElement.scrollWidth - "
                      "document.documentElement.clientWidth")
        check("kein waagerechter Ueberlauf", (ue or 0) <= 0, f"{ue} px")

        js(sock, "(function(){var e=document.querySelector('.wi-cfb-soon');"
                 "if(e)e.scrollIntoView({block:'center'});})()")
        time.sleep(0.4)
        bild(sock, f"cfb-hinweis-{thema}.png")

    # ⚠ Ohne diese Kontrolle waeren zwei identische Messwerte von "zweimal
    # dasselbe Thema gemessen" nicht zu unterscheiden (Register).
    check("POSITIVKONTROLLE: hell und dunkel waren zwei verschiedene Messungen",
          len(gemessen) == 2 and gemessen.get("hell") != gemessen.get("dunkel"),
          json.dumps(gemessen, ensure_ascii=False))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
