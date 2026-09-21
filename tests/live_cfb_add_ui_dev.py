#!/usr/bin/env python3
"""Optische Abnahme: der Uebernehmen-Knopf der Confluence-Einbindung.

Vorgabe 2026-09-21: ein Eintrag im Pulldown wird NICHT mehr automatisch
uebernommen, sondern erst auf Knopfdruck.

⚠ DER KNOPF WIRD WIRKLICH GEKLICKT – ob eine Auswahl ihn freigibt und ob
der Klick den Serveraufruf ausloest, kann eine reine Layout-Messung nicht
beantworten. Der Datenbestand bleibt dabei unberuehrt: die Abruf-Funktion
ist vollstaendig gestellt, es geht kein einziger Aufruf an den Dienst.

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


# Nichts eingebunden – damit ist das Pulldown frei und der Knopf pruefbar.
BEREICHE = []
SPACES = [
    {"key": "IBS", "name": "IBS Handbuch", "type": "global"},
    {"key": "NEXUS", "name": "NEXUS Dokumentation", "type": "global"},
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
  window.__rufe = [];
  window.fetch = function (u, o) {
    var url = String(u).split('?')[0];
    var meth = ((o && o.method) || 'GET').toUpperCase();
    var rumpf = null;
    try { rumpf = (o && o.body) ? JSON.parse(o.body) : null; } catch (e) {}
    window.__rufe.push({ pfad: url, m: meth, body: rumpf });
    if (url === '/api/wissen/confluence/bindung' && meth === 'POST') {
      return antwort({ ok: true,
        bereich: { id: 'neu', key: rumpf.key, name: rumpf.key, inkl_unter: rumpf.inkl_unter },
        bereiche: [{ id: 'neu', key: rumpf.key, name: rumpf.key, inkl_unter: rumpf.inkl_unter }] });
    }
    if (url === '/api/me') { return antwort({ is_admin: true, username: 'probe', permissions: {} }); }
    if (url === '/api/wissen/confluence/bindung') {
      return antwort({ ok: true, aktiv: true, bereiche: __BEREICHE__ });
    }
    if (url === '/api/wissen/confluence/spaces') {
      return antwort({ ok: true, configured: true, spaces: __SPACES__ });
    }
    if (url === '/api/wissen/scope') { return antwort({ ok: true, groups: [], folders: [] }); }
    if (url === '/api/wissen/files') { return antwort({ ok: true, files: [] }); }
    if (url === '/api/knowledge/pending') { return antwort({ ok: true, items: [] }); }
    return antwort({ ok: true });
  };
})();
"""

PROFIL = tempfile.mkdtemp(prefix="chrome-cfbadd-", dir=str(Path.home()))
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
print("Optische Abnahme: Uebernehmen-Knopf der Confluence-Einbindung")
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
                          .replace("__BEREICHE__", json.dumps(BEREICHE, ensure_ascii=False))
                          .replace("__SPACES__", json.dumps(SPACES, ensure_ascii=False)))
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
        opt = js(sock, "(function(){var s=document.getElementById('wi-cfb-space');"
                       "return s?s.options.length:0;})()")
        check("POSITIVKONTROLLE: das Pulldown ist gefuellt", (opt or 0) >= 3, f"{opt} Optionen")

        # ── Der Knopf ──────────────────────────────────────────────────────
        rb = js(sock, RECHTECK % "#wi-cfb-add")
        check("der Knopf hat eine Flaeche (POSITIVKONTROLLE)",
              bool(rb) and rb["h"] > 0 and rb["w"] > 0,
              json.dumps(rb) if rb else "nicht gefunden")

        z = js(sock, "(function(){var b=document.getElementById('wi-cfb-add');"
                     "return b?{d:b.disabled,t:b.title,x:b.textContent.trim()}:null;})()")
        check("⚠ ohne Auswahl GESPERRT", bool(z) and z["d"] is True, json.dumps(z))
        check("⚠ und er sagt im title, was zu tun ist",
              bool(z) and bool(z["t"]), json.dumps(z))
        check("die Beschriftung ist gesetzt (i18n greift)",
              bool(z) and z["x"] in ("Übernehmen", "Apply"), z["x"] if z else "")

        # Eine Zeile: Pulldown, Kaestchen und Knopf muessen sich waagerecht
        # ueberlappen - sonst steht der Knopf in einer eigenen Zeile.
        rs = js(sock, RECHTECK % "#wi-cfb-space")
        rk = js(sock, RECHTECK % ".wi-cfb-scope")
        if rb and rs and rk:
            ueb = min(rb["b"], rs["b"]) - max(rb["y"], rs["y"])
            check("Knopf und Pulldown stehen in EINER Zeile", ueb > 5,
                  f"Ueberlappung {ueb}px")
            check("der Knopf steht RECHTS vom Kaestchen", rb["x"] >= rk["x"],
                  f"btn.x={rb['x']} box.x={rk['x']}")
        else:
            check("Zeilenmessung moeglich", False, "Element fehlt")

        # ── Auswahl gibt frei (echtes change-Ereignis) ─────────────────────
        js(sock, """(function(){
          var s=document.getElementById('wi-cfb-space');
          s.value='IBS'; s.dispatchEvent(new Event('change',{bubbles:true}));})()""")
        time.sleep(0.4)
        js(sock, "(function(){var e=document.querySelector('.wi-cfb-pick');"
                 "if(e)e.scrollIntoView({block:'center'});})()")
        time.sleep(0.3)
        bild(sock, f"cfb-add-frei-{thema}.png")
        z2 = js(sock, "(function(){var b=document.getElementById('wi-cfb-add');"
                      "return {d:b.disabled,t:b.title,"
                      "posts:(window.__rufe||[]).filter(function(r){return r.m==='POST' && r.pfad==='/api/wissen/confluence/bindung';}).length};})()")
        check("⚠ die Auswahl GIBT den Knopf frei", z2["d"] is False, json.dumps(z2))
        check("und der title ist dann leer", not z2["t"], json.dumps(z2))
        check("⚠ der Wechsel im Pulldown bindet NICHTS ein", z2["posts"] == 0,
              f"{z2['posts']} POST")

        # ── Der Klick bindet ein ───────────────────────────────────────────
        js(sock, "document.getElementById('wi-cfb-add').click()")
        time.sleep(0.8)
        z3 = js(sock, """(function(){
          var p=(window.__rufe||[]).filter(function(r){
            return r.pfad==='/api/wissen/confluence/bindung' && r.m==='POST';});
          return {n:p.length, key:p[0]&&p[0].body&&p[0].body.key,
                  sub:p[0]&&p[0].body&&p[0].body.inkl_unter,
                  liste:document.querySelectorAll('#wi-cfb-list .wi-item').length,
                  d:document.getElementById('wi-cfb-add').disabled};})()""")
        check("⚠ der KLICK loest GENAU EINEN Serveraufruf aus", z3["n"] == 1, json.dumps(z3))
        check("mit dem gewaehlten Schluessel", z3["key"] == "IBS", json.dumps(z3))
        check("und der Reichweite des Hakens", z3["sub"] is True, json.dumps(z3))
        check("der Bereich steht danach in der Liste", z3["liste"] == 1, json.dumps(z3))
        check("⚠ und der Knopf ist wieder gesperrt (nichts gewaehlt)",
              z3["d"] is True, json.dumps(z3))

        # ── Kontrast der Beschriftung ──────────────────────────────────────
        vg = js(sock, """(function(){
          var e=document.getElementById('wi-cfb-add'); if(!e) return null;
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
          return {fg:c.color, bg:'rgb('+out.map(Math.round).join(', ')+')'};})()""")
        if vg:
            k = kontrast(farbe(vg["fg"]), farbe(vg["bg"]))
            # Fuer die Positivkontrolle taugt die KNOPFfarbe nicht: sie ist
            # in beiden Themen dieselbe (--accent auf #fff). Gemessen wird
            # deshalb der Seitengrund, der sich unterscheiden MUSS.
            grund = js(sock, "getComputedStyle(document.body).backgroundColor")
            gemessen[thema] = (grund, round(k, 2))
            check(f"Kontrast der Beschriftung >= 4,5:1 (gemessen {k:.2f}:1)", k >= 4.5,
                  f"fg={vg['fg']} bg={vg['bg']}")
        else:
            check("Knopf messbar", False, "kein Element")

        MESS_OP = """(function(){
          var e=document.querySelector('%s'); if(!e) return null;
          var c=getComputedStyle(e), op=parseFloat(c.opacity||'1');
          function z(x){var m=/rgba?\\(([^)]+)\\)/.exec(x||'');
            if(!m) return null; var t=m[1].split(',').map(parseFloat);
            return [t[0],t[1],t[2],t.length>3?t[3]:1];}
          var fg=z(c.color)||[255,255,255,1], bg=z(c.backgroundColor)||[0,0,0,1];
          var g=e.parentElement, unten=null;
          while(g && !unten){ var b=z(getComputedStyle(g).backgroundColor);
            if(b && b[3]>=1) unten=b; g=g.parentElement; }
          if(!unten) unten=[255,255,255,1];
          // Knopfflaeche auf den Grund, dann das Ganze mit `opacity` darauf.
          var fl=[0,1,2].map(function(k){return bg[k]*bg[3]+unten[k]*(1-bg[3]);});
          var flO=[0,1,2].map(function(k){return fl[k]*op+unten[k]*(1-op);});
          var txO=[0,1,2].map(function(k){return (fg[k]*fg[3]+fl[k]*(1-fg[3]))*op+unten[k]*(1-op);});
          return {fg:'rgb('+txO.map(Math.round).join(', ')+')',
                  bg:'rgb('+flO.map(Math.round).join(', ')+')', op:op};})()"""

        # ⚠ BESTANDSBEFUND, NICHT VON DIESER AENDERUNG: `.sec-btn:disabled`
        # setzt projektweit `opacity: .5` – weisse Schrift auf aufgehelltem
        # Akzent liegt damit bei rund 2:1. Das trifft JEDEN gesperrten
        # `.sec-btn primary`, auf DIESER Seite auch `#wi-drafts-appsel` (seit
        # jeher). Eine Einzelkorrektur an meinem Knopf waere eine Inkonsistenz,
        # eine globale ein eigener Auftrag. Gemessen wird deshalb die EHRLICHE
        # Zusage: der neue Knopf ist nicht SCHLECHTER als der Bestand daneben.
        vg2 = js(sock, MESS_OP % "#wi-cfb-add")
        vgB = js(sock, MESS_OP % "#wi-drafts-appsel")
        if vg2 and vgB:
            k2 = kontrast(farbe(vg2["fg"]), farbe(vg2["bg"]))
            kB = kontrast(farbe(vgB["fg"]), farbe(vgB["bg"]))
            check(f"gesperrt nicht schlechter als der Bestands-Knopf daneben "
                  f"(neu {k2:.2f}:1, Bestand {kB:.2f}:1 – beides `.sec-btn:disabled`)",
                  k2 >= kB - 0.05, f"neu={vg2['bg']} bestand={vgB['bg']}")
            print(f"       (Bestandsbefund: gesperrte .sec-btn primary liegen bei "
                  f"{kB:.2f}:1 – projektweit, eigener Auftrag)")
        else:
            check("gesperrter Zustand messbar", False, "Element fehlt")

        ue = js(sock, "document.documentElement.scrollWidth - "
                      "document.documentElement.clientWidth")
        check("kein waagerechter Ueberlauf", (ue or 0) <= 0, f"{ue} px")

        # ⚠ SCHMAL WIRD AM CONTAINER GEMESSEN, nicht am Fenster: /wissen laeuft
        # bei 520 px durch die Symbolreihe der Titelleiste ohnehin ueber
        # (Bestand, eigener Abschnitt in der Chronik) – eine Messung am Fenster
        # pruefte dann etwas anderes, als sie behauptet.
        cdp(sock, "Emulation.setDeviceMetricsOverride", width=520, height=900,
            deviceScaleFactor=1, mobile=False)
        time.sleep(0.6)
        eng = js(sock, """(function(){
          var s=document.getElementById('wi-sec-cfbind');
          var b=document.getElementById('wi-cfb-add'); if(!s||!b) return null;
          var rs=s.getBoundingClientRect(), rb=b.getBoundingClientRect();
          return {ueber: Math.round(rb.right - rs.right),
                  sicht: rb.width>0 && rb.height>0};})()""")
        check("schmal (520px): der Knopf bleibt IM Container",
              bool(eng) and eng["sicht"] and eng["ueber"] <= 0,
              json.dumps(eng))
        cdp(sock, "Emulation.clearDeviceMetricsOverride")
        time.sleep(0.4)

        js(sock, "(function(){var e=document.querySelector('.wi-cfb-pick');"
                 "if(e)e.scrollIntoView({block:'center'});})()")
        time.sleep(0.4)
        bild(sock, f"cfb-add-{thema}.png")

    # ⚠ Ohne diese Kontrolle waeren zwei identische Messwerte von "zweimal
    # dasselbe Thema gemessen" nicht zu unterscheiden (Register).
    check("POSITIVKONTROLLE: hell und dunkel waren zwei verschiedene Messungen",
          len(gemessen) == 2 and gemessen.get("hell") != gemessen.get("dunkel"),
          json.dumps(gemessen, ensure_ascii=False))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
