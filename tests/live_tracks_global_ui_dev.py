#!/usr/bin/env python3
"""Optische Abnahme des Kaestchens "Fuer alle Benutzer" im ECHTEN Chrome.

jsdom rechnet kein Layout – Ueberlappung, Ueberlauf und Kontrast sieht nur ein
echter Browser. Geprueft wird in HELL und DUNKEL.

Gemessen wird am ECHTEN `tracks.js` mit dem ECHTEN CSS und dem ECHTEN
`i18n.js`; die Serverantworten kommen aus einer Attrappe, damit die Probe
nichts im Bestand anlegt.
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

ROOT = "/opt/jarvis/frontend"
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def freier_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ── Probeseite: echtes tracks.html mit gestubbtem fetch ────────────────────
# ⚠ Ein `file://`-Aufruf laedt keine Module und faellt bei relativen Pfaden auf
# die Nase – es braucht einen echten HTTP-Server (Register).
TMP = tempfile.mkdtemp(prefix="tracksui_")
shutil.copytree(ROOT, os.path.join(TMP, "static"), dirs_exist_ok=True)
seite = open(os.path.join(ROOT, "tracks.html"), encoding="utf-8").read()

DUMPS = [
    {"id": "a" * 12, "owner": "andreas.bender", "global": False, "name": "Rechnung",
     "beschreibung": "Rechnungen auswerten", "prompt": "Lies die Rechnung.",
     "bereiche": ["basis"], "dateitypen": ["pdf"], "mehrfach": "einzeln",
     "profile_id": "", "reasoning_effort": "", "max_steps": 0, "enabled": True,
     "laeufe": 3},
    {"id": "b" * 12, "owner": "admin", "global": True, "name": "Protokoll",
     "beschreibung": "", "prompt": "Fasse zusammen.", "bereiche": ["basis"],
     "dateitypen": [], "mehrfach": "gemeinsam", "profile_id": "",
     "reasoning_effort": "", "max_steps": 0, "enabled": True, "laeufe": 0},
]
STATUS = {"ok": True, "dumps": DUMPS, "ist_admin": True, "aktiv": True,
          "grenzen": {"name_max": 60, "beschreibung_max": 200, "prompt_max": 8000,
                      "max_mb": 20, "max_dateien": 20},
          "bereiche": [{"id": "basis", "name": "Lesen + Dokumente erzeugen",
                        "hinweis": "Pflicht", "pflicht": True, "freigegeben": True}]}

stub = """
<script>
localStorage.setItem('jarvis_token','T');
(function(){
  var S = %s;
  window.fetch = function(u, o){
    u = String(u); o = o || {};
    var p = u.split('?')[0], d = {ok:true};
    if (p.indexOf('/api/tracks/status') === 0) d = S;
    else if (p.indexOf('/api/tracks/jobs') === 0) d = {ok:true, jobs:[]};
    else if (p.indexOf('/api/tracks/count') === 0) d = {ok:true, offen:0, neu:0};
    // ⚠ `permissions.tracks` IST PFLICHT: tracks.js leitet fail-closed aufs
    // Portal um, wenn es fehlt. Ohne dieses Feld misst die Probe das Portal
    // statt der Ablagen-Seite – die Positivkontrolle hat genau das gefangen.
    else if (p.indexOf('/api/me') === 0) d = {ok:true, username:'andreas.bender',
        is_admin:true, permissions:{tracks:true}};
    return Promise.resolve({ok:true, status:200, json:function(){return Promise.resolve(d);},
                            text:function(){return Promise.resolve(JSON.stringify(d));}});
  };
})();
</script>
""" % json.dumps(STATUS)
seite = seite.replace("</head>", stub + "</head>")
seite = seite.replace('src="/static/', 'src="static/').replace('href="/static/', 'href="static/')
open(os.path.join(TMP, "probe.html"), "w", encoding="utf-8").write(seite)

PORT = freier_port()
srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT),
                        "--bind", "127.0.0.1", "-d", TMP],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.2)

PROFIL = tempfile.mkdtemp(prefix="chromeprof_")
CDP = freier_port()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     "--remote-allow-origins=*", "--remote-debugging-port=%d" % CDP,
     "--user-data-dir=" + PROFIL, "--window-size=1280,900",
     "--no-first-run", "--no-default-browser-check", "--disable-extensions",
     "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
time.sleep(3.0)

try:
    import websocket                                             # noqa: F401
except ImportError:
    print("ABBRUCH: websocket-client fehlt – ohne CDP keine Messung.")
    chrome.kill(); srv.kill()
    sys.exit(2)
import websocket                                                 # noqa: E402

# ⚠ /json/list liefert auch die eingebauten Chrome-ERWEITERUNGEN. Wer blind
# [0] nimmt, haengt an einer Erweiterungsseite statt an der Seite (Register).
# ⚠ UND Chrome oeffnet mit frischem Profil `chrome://newtab/`, NICHT die als
# Argument uebergebene Adresse (auf DEV gemessen). Deshalb wird die Probeseite
# ueber CDP NAVIGIERT statt gehofft.
ziel = None
for _ in range(25):
    try:
        liste = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:%d/json/list" % CDP, timeout=5).read().decode())
        seiten = [x for x in liste if x.get("type") == "page"]
        if seiten:
            ziel = seiten[0]
            break
    except Exception:                                            # noqa: BLE001
        pass
    time.sleep(0.6)
if not ziel:
    print("ABBRUCH: keine CDP-Seite gefunden.")
    chrome.kill(); srv.kill()
    sys.exit(2)

ws = websocket.create_connection(ziel["webSocketDebuggerUrl"], timeout=25)
_id = [0]


def js(ausdruck):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": "Runtime.evaluate",
                        "params": {"expression": ausdruck, "returnByValue": True,
                                   "awaitPromise": True}}))
    while True:
        a = json.loads(ws.recv())
        if a.get("id") == _id[0]:
            r = a.get("result", {}).get("result", {})
            if a.get("result", {}).get("exceptionDetails"):
                return {"_wurf": str(a["result"]["exceptionDetails"])[:200]}
            return r.get("value")


ADRESSE = "http://127.0.0.1:%d/probe.html" % PORT
_id[0] += 1
ws.send(json.dumps({"id": _id[0], "method": "Page.navigate",
                    "params": {"url": ADRESSE}}))
while True:
    a = json.loads(ws.recv())
    if a.get("id") == _id[0]:
        break
time.sleep(4.0)

# Positivkontrolle: ohne sie waere jede Messung darunter trivial wahr.
check(js("location.pathname") == "/probe.html",
      "die Probeseite ist geladen", str(js("location.href"))[:120])
check(js("document.querySelectorAll('.st-dump').length") == 2,
      "und aufgebaut (2 Ablagen gezeichnet)",
      str(js("document.body && document.body.innerHTML.length"))[:80])

for thema in ("dunkel", "hell"):
    print("\n── Thema: %s ──" % thema)
    js("document.body.classList.%s('light')"
       % ("add" if thema == "hell" else "remove"))
    # Globale Ablage bearbeiten
    js("document.querySelector('.st-dump[data-dump=\"bbbbbbbbbbbb\"] "
       "[data-act=\\'edit\\']').click()")
    time.sleep(1.0)
    mass = js("""(function(){
      var g = document.getElementById('st-f-global');
      if (!g) return {da:false};
      var lab = g.closest('label'), r = lab.getBoundingClientRect();
      var f = document.getElementById('st-form').getBoundingClientRect();
      var save = document.getElementById('st-f-save').getBoundingClientRect();
      var cs = getComputedStyle(g);
      return {da:true, checked:g.checked, breite:r.width, hoehe:r.height,
              links:r.left, rechts:r.right, formRechts:f.right,
              saveOben:save.top, saveSichtbar: save.top < innerHeight,
              text:(lab.textContent||'').trim().slice(0,40),
              gr: g.getBoundingClientRect().width,
              ueberlauf: document.documentElement.scrollWidth > innerWidth};
    })()""")
    check(isinstance(mass, dict) and mass.get("da"),
          "[%s] das Kaestchen steht beim Bearbeiten" % thema, str(mass)[:160])
    if isinstance(mass, dict) and mass.get("da"):
        check(mass.get("checked") is True,
              "[%s] und ist bei der globalen Ablage angehakt" % thema)
        check(mass.get("gr", 0) > 8,
              "[%s] es ist sichtbar gross (%.0f px)" % (thema, mass.get("gr", 0)))
        check(mass.get("rechts", 1e9) <= mass.get("formRechts", 0) + 1,
              "[%s] die Zeile bleibt im Formular" % thema,
              "%.0f > %.0f" % (mass.get("rechts", 0), mass.get("formRechts", 0)))
        check(not mass.get("ueberlauf"),
              "[%s] kein waagerechter Ueberlauf" % thema)
        check(mass.get("saveSichtbar"),
              "[%s] 'Speichern' bleibt im Sichtfenster" % thema)
        check("alle" in (mass.get("text") or "").lower(),
              "[%s] die Beschriftung nennt 'alle': %r" % (thema, mass.get("text")))
    # Hilfetext aufklappen
    js("var b=document.querySelector('[data-help=\\'st-help-global\\']'); b&&b.click()")
    time.sleep(0.6)
    hilfe = js("""(function(){
      var h = document.getElementById('st-help-global');
      if (!h) return null;
      var r = h.getBoundingClientRect();
      return {txt:(h.textContent||'').trim(), h:r.height,
              rechts:r.right, innen: r.right <= document.getElementById('st-form').getBoundingClientRect().right + 1};
    })()""")
    check(isinstance(hilfe, dict) and hilfe.get("h", 0) > 0,
          "[%s] der Hilfetext ist sichtbar" % thema, str(hilfe)[:120])
    if isinstance(hilfe, dict):
        check("nicht ändern" not in (hilfe.get("txt") or ""),
              "[%s] er behauptet NICHT mehr 'lässt sich nicht ändern'" % thema)
        check("entzieht sie allen anderen" in (hilfe.get("txt") or ""),
              "[%s] sondern nennt die Folge des Zuruecknehmens" % thema)
        check(hilfe.get("innen"), "[%s] und bleibt im Kasten" % thema)
    # Screenshot
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": "Page.captureScreenshot",
                        "params": {"format": "png"}}))
    while True:
        a = json.loads(ws.recv())
        if a.get("id") == _id[0]:
            roh = a.get("result", {}).get("data")
            if roh:
                p = "/tmp/tracks_global_%s.png" % thema
                open(p, "wb").write(base64.b64decode(roh))
                print("  … Screenshot: %s" % p)
            break
    js("var c=document.getElementById('st-f-cancel'); c&&c.click()")
    time.sleep(0.4)

ws.close()
chrome.kill()
srv.kill()
shutil.rmtree(TMP, ignore_errors=True)
shutil.rmtree(PROFIL, ignore_errors=True)

print("\n%s\n  %d OK, %d FAIL\n%s" % ("=" * 60, _ok, _fail, "=" * 60))
sys.exit(1 if _fail else 0)
