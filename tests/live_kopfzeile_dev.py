#!/usr/bin/env python3
"""Live-Abnahme der gemeinsamen Titelleiste (kopfzeile.js) im ECHTEN Chrome.

Gemessen wird, was jsdom nicht kann:
  * nach einem Seitenwechsel stehen Update-Pille, CPU und ⓘ SOFORT da – die
    Antworten von /api/me, /api/cpu und /api/update/status sind absichtlich um
    VERZOEGERUNG_MS verzoegert; sichtbar sein koennen sie also nur aus dem
    gemerkten Stand;
  * der Browser fuehrt den Wechsel als View Transition aus (`pagereveal`
    meldet ein `viewTransition`) – das ist der Teil, der die Leiste stehen
    laesst;
  * Logo, Marke, LLM-Punkt, Schild und Abmelden sind auf jeder Seite sichtbar.

POSITIVKONTROLLEN (ohne sie waere der Lauf trivial wahr):
  * beim ERSTEN Aufruf (leerer Merker) sind die Admin-Elemente zum selben
    Messzeitpunkt NICHT sichtbar – die Messung kann den Unterschied sehen;
  * die gemessene Seite ist wirklich die angesteuerte (keine Umleitung);
  * der Wechsel wird von der SEITE ausgeloest (`location.href`), nicht von
    CDP – eine browserseitige Navigation bekommt nie eine View Transition.

Bilder der Leisten landen in ~/kopfzeile-bilder (0700, nicht /tmp).

Aufruf auf DEV:
  runuser -u jarvis -- /opt/jarvis/venv/bin/python /opt/jarvis/tests/live_kopfzeile_dev.py
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

BASIS = "https://127.0.0.1"
START = "/portal"
SEITEN = ["/chat", "/tracks", "/wissen", "/support", "/sap", "/vemas", "/email",
          "/feedback", "/ai-mouse", "/settings", "/claude", "/userchat", "/portal"]
VERZOEGERUNG_MS = 2500
MESSPUNKT_S = 0.8          # deutlich vor der verzoegerten Antwort
BILDER = Path.home() / "kopfzeile-bilder"

_ok = _fail = 0
_hinweise = []


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


RECHTE = ["sap", "vemas", "email", "tracks", "jira_assist", "claudesub",
          "ai_mouse", "feedback", "userchat", "excel", "internet"]

VORLAUF = r"""
try { localStorage.setItem('jarvis_token','probe'); localStorage.setItem('jarvis_user','probe'); } catch(e){}
window.__vt = null; window.__fehler = [];
window.addEventListener('error', function(e){ window.__fehler.push(String(e.message)+' @'+String(e.filename||'').split('/').pop()+':'+e.lineno); });
window.addEventListener('pagereveal', function(e){ window.__vt = !!e.viewTransition; });
(function(){
  var VERZ = __VERZ__;
  function a(d, ms){ var r = {ok:true,status:200,headers:{get:function(){return null;}},
      json:function(){return Promise.resolve(d);},
      text:function(){return Promise.resolve(JSON.stringify(d));}};
    return ms ? new Promise(function(ok){ setTimeout(function(){ ok(r); }, ms); }) : Promise.resolve(r); }
  var R = __RECHTE__, perm = {};
  for (var i=0;i<R.length;i++) perm[R[i]] = true;
  window.fetch=function(u){var p=String(u).split('?')[0];
    // Verzoegert wird /api/me NUR fuer die Leisten-Module: die Seiten selbst
    // blenden ihren App-Bereich erst nach IHRER Antwort ein – eine Verzoegerung
    // dort machte die ganze Seite unsichtbar und mass nicht die Leiste.
    var st=''; try { throw new Error(); } catch(e){ st=String(e.stack||''); }
    var leiste=/kopfzeile\.js|syspackages\.js|cpubar\.js|update_widget\.js|sysload\.js/.test(st);
    if(p==='/api/me')return a({is_admin:true,username:'probe',permissions:perm}, leiste?VERZ:0);
    if(p==='/api/cpu')return a({cpu:37}, VERZ);
    if(p==='/api/update/status')return a({ok:true,has_update:false,jarvis_version:'4.5.6',commits_behind:0}, VERZ);
    if(p==='/api/llm/active-status')return a({status:'ok',profile_name:'Probe'});
    if(p==='/api/verify-token')return a({valid:true,username:'probe',is_admin:true});
    if(p==='/api/wissen/scope')return a({ok:true,user:'probe',is_editor:true,groups:[],folders:[]});
    return a({ok:true,items:[],files:[],groups:[],bereiche:[],spaces:[],
              fragen:[],formulare:[],sessions:[],skills:[]});};
})();
"""

MESS = """(function(){
  function sicht(sel){ var e=document.querySelector(sel); if(!e) return 'fehlt';
    var cs=getComputedStyle(e), r=e.getBoundingClientRect();
    return (cs.display!=='none' && cs.visibility!=='hidden' && r.width>0 && r.height>0) ? 'ja' : 'nein'; }
  var k=document.querySelector('.jv-kopfzeile');
  var r=k?k.getBoundingClientRect():null;
  var t=(document.body&&document.body.textContent||'').trim();
  return {url:location.pathname, vt:window.__vt, kopf:!!k,
          inaktiv:/^404[^0-9]/.test(t) && !document.querySelector('script'), fehler:(window.__fehler||[]).slice(0,3),
          rect:r?{x:r.x,y:r.y,w:r.width,h:r.height}:null,
          logo:sicht('.jv-kopfzeile .topbar-avatar, .jv-kopfzeile .sa-logo'),
          marke:sicht('.jv-kopfzeile .brand-app-name'),
          llm:sicht('.jv-kopfzeile [data-kopf="llm"]'),
          schild:sicht('.jv-kopfzeile #security-indicator, .jv-kopfzeile #jv-kopf-schild'),
          update:sicht('#chat-update-wrap'), cpu:sicht('#cpu-bar'), pakete:sicht('#jv-pkg-btn'),
          abmelden:sicht('.jv-kopfzeile [id*="logout"], .jv-kopfzeile .btn-logout'),
          cpuText:(document.getElementById('cpu-bar-label')||{}).textContent||'',
          admin:document.documentElement.classList.contains('jv-kopf-admin')};
})()"""

PROFIL = tempfile.mkdtemp(prefix="chrome-kopfzeile-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
BILDER.mkdir(mode=0o700, exist_ok=True)
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1400,900",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


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


def ende(code):
    chrome.kill()
    shutil.rmtree(PROFIL, ignore_errors=True)
    sys.exit(code)


print("=" * 74)
print("Live-Abnahme: gemeinsame Titelleiste")
print("=" * 74)

ws = ziel_ws()
if not ws:
    print("ABBRUCH: kein CDP-Ziel (Chrome-Ausgabe:)")
    print(chrome.stdout.read(2000) if chrome.stdout else "")
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
        d = json.loads(sock.recv(timeout=60))
        if d.get("id") == _id[0]:
            return d.get("result", {})


def js(sock, a):
    r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def bild(sock, name, m):
    r = (m or {}).get("rect")
    if not r:
        return
    clip = {"x": 0, "y": max(0, r["y"]), "width": 1400, "height": max(40, r["h"]), "scale": 1}
    d = cdp(sock, "Page.captureScreenshot", format="png", clip=clip)
    if d.get("data"):
        (BILDER / ("%s.png" % name.strip("/").replace("/", "_") or "root")).write_bytes(
            base64.b64decode(d["data"]))


# Was SOFORT aus dem Merker stehen muss: Update-Pille und ⓘ (nur Admin) und
# die CPU (fuer alle, Nachtrag 2026-11-16) – alle drei haengen an verzoegerten
# Antworten und waeren ohne Merker zum Messzeitpunkt noch nicht da.
ADMIN = ("update", "cpu", "pakete")
IMMER = ("logo", "marke", "llm", "schild", "abmelden")

with connect(ws, open_timeout=20, max_size=60_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
        source=VORLAUF.replace("__RECHTE__", json.dumps(RECHTE))
                      .replace("__VERZ__", str(VERZOEGERUNG_MS)))
    cdp(sock, "Emulation.setDeviceMetricsOverride", width=1400, height=900,
        deviceScaleFactor=1, mobile=False)

    # ── Erster Aufruf: leerer Merker ─────────────────────────────────────
    print("\n── erster Aufruf %s (Merker leer) " % START + "─" * 30)
    cdp(sock, "Page.navigate", url=BASIS + START)
    time.sleep(MESSPUNKT_S)
    frueh = js(sock, MESS) or {}
    check("PK: die Seite ist %s" % START, frueh.get("url") == START, frueh.get("url"))
    pk = all(frueh.get(n) != "ja" for n in ADMIN)
    check("PK: ohne Merker sind die Admin-Elemente nach %.1f s noch NICHT da "
          "(die Messung sieht den Unterschied)" % MESSPUNKT_S, pk,
          ", ".join("%s=%s" % (n, frueh.get(n)) for n in ADMIN))
    time.sleep(VERZOEGERUNG_MS / 1000 + 1.5)
    spaet = js(sock, MESS) or {}
    for n in ADMIN:
        check("nach der Antwort von /api/me: %s sichtbar" % n, spaet.get(n) == "ja", spaet.get(n))
    if not pk:
        print("ABBRUCH: ohne Positivkontrolle ist die Sofort-Messung nicht deutbar")
        ende(2)

    # ── Seitenwechsel aus der Seite heraus ────────────────────────────────
    gemessen = 0
    vorher_echt = True   # /portal war eine echte Seite (mit theme.css)
    for ziel in SEITEN:
        print("\n── Wechsel nach %s " % ziel + "─" * (52 - len(ziel)))
        js(sock, "location.href = %s; true" % json.dumps(ziel))
        time.sleep(MESSPUNKT_S)
        m = js(sock, MESS) or {}
        if not m.get("url"):
            # Messpunkt fiel mitten in die Navigation (kein Dokument) – einmal
            # kurz nachfassen, statt die Seite als "nicht gemessen" zu fuehren.
            time.sleep(0.3)
            m = js(sock, MESS) or {}
        if m.get("url") != ziel:
            _hinweise.append("%s: landete auf %s – nicht gemessen" % (ziel, m.get("url")))
            print("  --   landete auf %s – nicht gemessen" % m.get("url"))
            time.sleep(VERZOEGERUNG_MS / 1000 + 0.5)
            continue
        if m.get("inaktiv"):
            # Skill auf DEV aus: der Server liefert eine nackte 404-Seite. Sie
            # traegt kein theme.css – der NAECHSTE Wechsel hat deshalb keine
            # View Transition (beide Dokumente muessen zustimmen).
            _hinweise.append("%s: Bereich auf DEV nicht aktiv (404) – nicht gemessen" % ziel)
            print("  --   Bereich nicht aktiv (404) – nicht gemessen")
            vorher_echt = False
            continue
        if not m.get("kopf"):
            # /settings zeigt die Leiste erst mit dem Einstellungsfenster
            time.sleep(VERZOEGERUNG_MS / 1000 + 0.5)
            m = js(sock, MESS) or {}
        check("Leiste vorhanden", m.get("kopf"), "Fehler: %s" % m.get("fehler"))
        if m.get("fehler"):
            print("  INFO JS-Fehler der Seite: %s" % m.get("fehler"))
        if vorher_echt:
            check("View Transition beim Wechsel", m.get("vt") is True, m.get("vt"))
        else:
            print("  --   View Transition nicht bewertet (Vorgaenger war eine 404-Seite)")
        vorher_echt = True
        for n in IMMER:
            check("%s sichtbar" % n, m.get(n) == "ja", m.get(n))
        for n in ADMIN:
            check("%s SOFORT sichtbar (vor /api/me)" % n, m.get(n) == "ja", m.get(n))
        check("CPU zeigt den gemerkten Wert", m.get("cpuText") == "CPU: 37%", m.get("cpuText"))
        bild(sock, ziel, m)
        gemessen += 1
        time.sleep(VERZOEGERUNG_MS / 1000 + 0.5)

check("PK: es wurden ueberhaupt Seiten gemessen", gemessen >= 10, "%d" % gemessen)
print("\nErgebnis: %d/%d" % (_ok, _ok + _fail))
print("Bilder: %s" % BILDER)
if _hinweise:
    print("Nicht gemessen:\n  - " + "\n  - ".join(_hinweise))
ende(0 if _fail == 0 else 1)
