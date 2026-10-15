#!/usr/bin/env python3
"""Live-Abnahme: keine Titelleiste laeuft bei schmalem Fenster ueber.

⚠ DAS IST DER WAECHTER FUER DIE KLASSENLISTE IN `theme.css`. Die Regel dort
zaehlt fuenf Leisten-Familien auf – dass die Aufzaehlung VOLLSTAENDIG ist, wird
nicht gepflegt, sondern hier gemessen: eine kuenftige Seite mit eigener
Leisten-Klasse faellt bei 520 px sofort mit einem Ueberlauf auf.

Gemessen wird der ECHTE Ueberlauf im ECHTEN Chrome gegen die AUSGELIEFERTE
Seite – jsdom rechnet kein Layout, und ein Blick ins CSS beantwortet die Frage
"laeuft es ueber?" grundsaetzlich nicht.

DREI POSITIVKONTROLLEN, ohne die der Lauf trivial waere:
  * die Seite ist wirklich DIESE Seite (leitet sie um, misst man das Portal –
    beim ersten Anlauf dreimal passiert);
  * sie hat ueberhaupt eine Titelleiste mit Symbolen;
  * bei 1400 px war schon vorher alles 0 – die Regel darf dort nichts aendern.

⚠ JEDE SEITE BEKOMMT EINE FRISCHE CDP-VERBINDUNG: eine haengende Seite
(WebSocket-Reconnect) reisst sonst alle folgenden Messungen mit in den Timeout,
und der Lauf meldet Befunde ueber Seiten, die er nie gesehen hat.

Aufruf auf DEV:
  runuser -u jarvis -- /opt/jarvis/venv/bin/python /opt/jarvis/tests/live_topbar_umbruch_dev.py
"""
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
SEITEN = ["/portal", "/chat", "/wissen", "/support", "/sap", "/vemas", "/tracks",
          "/email", "/feedback", "/ai-mouse", "/claude", "/userchat", "/settings"]
SCHMAL = [520, 700]
BREIT = 1400

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


# Alle Bereichs-Berechtigungen – sonst leitet die Seite aufs Portal um und die
# Messung gilt einer anderen Seite (die Namen stammen aus main.py, nicht geraten).
RECHTE = ["sap", "vemas", "email", "tracks", "jira_assist", "claudesub",
          "ai_mouse", "feedback", "userchat", "excel", "internet"]

VORLAUF = r"""
try { localStorage.setItem('jarvis_token','probe'); } catch(e){}
(function(){
  function a(d){return Promise.resolve({ok:true,status:200,
    headers:{get:function(){return null;}},
    json:function(){return Promise.resolve(d);},
    text:function(){return Promise.resolve(JSON.stringify(d));}});}
  var R = __RECHTE__, perm = {};
  for (var i=0;i<R.length;i++) perm[R[i]] = true;
  window.fetch=function(u){var p=String(u).split('?')[0];
    if(p==='/api/me')return a({is_admin:true,username:'probe',permissions:perm});
    if(p==='/api/wissen/scope')return a({ok:true,user:'probe',is_editor:true,groups:[],folders:[]});
    return a({ok:true,items:[],files:[],groups:[],bereiche:[],spaces:[],
              fragen:[],formulare:[],sessions:[],skills:[]});};
})();
"""

MESS = """(function(){
  var d=document.documentElement,b=document.body;
  var ue=Math.max(d.scrollWidth-d.clientWidth,b.scrollWidth-b.clientWidth);
  var leiste=document.querySelector('.topbar,.wi-topbar,.pt-topbar,.sa-topbar,.ad-top');
  var gruppe=document.querySelector('.topbar-right,.wi-top-icons,.pt-top-icons,'
             +'.sa-top-icons,.ad-top-icons');
  var w=d.clientWidth, schlimm=null, max=0, alle=document.querySelectorAll('body *');
  for(var i=0;i<alle.length;i++){var e=alle[i],cs=getComputedStyle(e);
    if(cs.display==='none'||cs.visibility==='hidden')continue;
    var r=e.getBoundingClientRect(); if(r.width===0)continue;
    var g=Math.round(r.right-w);
    if(g>max){max=g;var c=(e.className&&e.className.baseVal!==undefined?
      e.className.baseVal:String(e.className||''));
      schlimm=(e.id?'#'+e.id:'')+'.'+c.split(/\\s+/).filter(Boolean).slice(0,2).join('.');}}
  return {url:location.pathname, ue:ue, leiste:!!leiste, gruppe:!!gruppe,
          knoepfe:gruppe?gruppe.querySelectorAll('button,a,.lang-toggle').length:0,
          schlimm:schlimm};
})()"""

PROFIL = tempfile.mkdtemp(prefix="chrome-topbar-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
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
                    # NUR type=="page" – /json/list liefert auch die eingebauten
                    # Erweiterungen (Register).
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
print("Live-Abnahme: Titelleisten laufen nicht mehr ueber")
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
        d = json.loads(sock.recv(timeout=60))
        if d.get("id") == _id[0]:
            return d.get("result", {})


def js(sock, a):
    r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def miss(seite, breite):
    """Eine Seite bei einer Breite – mit EIGENER Verbindung, damit eine
    haengende Seite nicht alle folgenden mitreisst."""
    try:
        with connect(ws, open_timeout=20, max_size=60_000_000) as sock:
            cdp(sock, "Page.enable")
            cdp(sock, "Runtime.enable")
            cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
                source=VORLAUF.replace("__RECHTE__", json.dumps(RECHTE)))
            cdp(sock, "Emulation.setDeviceMetricsOverride", width=breite, height=800,
                deviceScaleFactor=1, mobile=False)
            cdp(sock, "Page.navigate", url=BASIS + seite)
            time.sleep(3.0)
            m = js(sock, MESS) or {}
            try:
                cdp(sock, "Page.navigate", url="about:blank")
            except Exception:                                      # noqa: BLE001
                pass
            return m
    except Exception as e:                                         # noqa: BLE001
        return {"_fehler": "%s: %s" % (type(e).__name__, e)}


gemessen = 0
for seite in SEITEN:
    print("\n── %s " % seite + "─" * (60 - len(seite)))
    ref = miss(seite, BREIT)
    if ref.get("_fehler"):
        _hinweise.append("%s: nicht messbar (%s)" % (seite, ref["_fehler"]))
        print("  --   nicht messbar: %s" % ref["_fehler"])
        continue
    if ref.get("url") != seite:
        _hinweise.append("%s: leitet nach %s um – nicht gemessen" % (seite, ref.get("url")))
        print("  --   leitet nach %s um – nicht gemessen" % ref.get("url"))
        continue

    check("PK: die Seite hat eine Titelleiste mit Symbolen",
          ref.get("leiste") and ref.get("gruppe") and ref.get("knoepfe", 0) >= 2,
          "leiste=%s gruppe=%s knoepfe=%s" % (ref.get("leiste"), ref.get("gruppe"),
                                              ref.get("knoepfe")))
    check("PK: bei %d px laeuft nichts ueber (Referenz)" % BREIT, ref.get("ue") == 0,
          "%s px, %s" % (ref.get("ue"), ref.get("schlimm")))
    for br in SCHMAL:
        m = miss(seite, br)
        if m.get("_fehler"):
            _hinweise.append("%s@%d: nicht messbar (%s)" % (seite, br, m["_fehler"]))
            print("  --   %d px nicht messbar: %s" % (br, m["_fehler"]))
            continue
        check("⚠ bei %d px kein waagerechter Ueberlauf" % br, m.get("ue") == 0,
              "%s px ueber, breitestes: %s" % (m.get("ue"), m.get("schlimm")))
        gemessen += 1

# Ohne gemessene Seiten waere der ganze Lauf trivial wahr.
check("PK: es wurden ueberhaupt Seiten gemessen", gemessen >= 12, "%d" % gemessen)

print("\nErgebnis: %d/%d" % (_ok, _ok + _fail))
if _hinweise:
    print("Nicht gemessen:\n  - " + "\n  - ".join(_hinweise))
ende(0 if _fail == 0 else 1)
