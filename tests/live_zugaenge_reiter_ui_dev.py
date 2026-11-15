#!/usr/bin/env python3
"""Optische Abnahme (DEV, NUR LESEND): Einstellungen → Jira, Confluence, SAP,
Vemas tragen "Verbindung" und "Persoenliche …-Zugaenge" als Klapp-Container,
den Schalter "Persoenliche Zugaenge erlauben" in "Verbindung" – einheitlich.

jsdom rechnet kein Layout; hier misst ein echtes Chrome gegen die AUSGELIEFERTE
/settings, in hellem UND dunklem Thema: beide Container sind gemalt und stehen
in der richtigen Reihenfolge, der Schalter liegt sichtbar im ersten, nichts
laeuft waagerecht ueber. Screenshots landen im HOME (0700), nicht in /tmp.

Es wird NICHTS gespeichert und kein Schalter umgelegt (ein Abschalten loescht
persoenliche Zugaenge – unwiderruflich). Geklickt werden nur Reiter.

Auf DEV: cd /opt/jarvis && bash deploy/als_dienst.sh venv/bin/python tests/live_zugaenge_reiter_ui_dev.py
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
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

sys.path.insert(0, "/opt/jarvis")
os.environ.setdefault("HOME", "/home/jarvis")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


try:
    from backend import main as M  # noqa: E402
    from websockets.sync.client import connect  # noqa: E402
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: %s" % e)
    sys.exit(2)

BASIS = "https://127.0.0.1"
TOKEN = M.generate_token("jarvis")
ABLAGE = Path.home() / "zugaenge-reiter-bilder"
ABLAGE.mkdir(mode=0o700, exist_ok=True)

PROFIL = tempfile.mkdtemp(prefix="zugreiter-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     "--remote-debugging-port=%d" % PORT, "--remote-allow-origins=*",
     "--user-data-dir=%s" % PROFIL, "--window-size=1300,1400",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def ende(code):
    chrome.kill()
    shutil.rmtree(PROFIL, ignore_errors=True)
    sys.exit(code)


def ziel_ws():
    for _ in range(60):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % PORT, timeout=2) as a:
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


_id = [0]


def cdp(sock, m, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": m, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=40))
        if d.get("id") == _id[0]:
            return d.get("result", {})


def js(sock, a):
    r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


REITER = [("jira", "ji", "jira-persoenlich"), ("confluence", "cf", "cf-persoenlich"),
          ("sap", "sap", "sap-persoenlich"), ("vemas", "vemas", "vemas-persoenlich")]

ws = ziel_ws()
if not ws:
    print("ABBRUCH: kein CDP-Ziel")
    ende(2)

with connect(ws, open_timeout=20, max_size=60_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    for thema in ("dark", "light"):
        print("\nThema: %s" % thema)
        cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
            source="try{localStorage.setItem('jarvis_token','%s');"
                   "localStorage.setItem('jarvis_theme','%s');}catch(e){}"
                   "window.__fehler='';window.addEventListener('error',function(e){"
                   "window.__fehler+=(e.message||'')+' | ';});" % (TOKEN, thema))
        cdp(sock, "Page.navigate", url=BASIS + "/settings")
        time.sleep(7)
        if js(sock, "location.pathname") != "/settings":
            print("ABBRUCH: nicht auf /settings gelandet – Anmeldung trug nicht")
            ende(2)
        hell = js(sock, "document.body.classList.contains('light')")
        check("Positivkontrolle: Thema %s ist aktiv" % thema, bool(hell) == (thema == "light"))
        for name, pre, cb in REITER:
            js(sock, "document.getElementById('settings-tab-btn-%s').click()" % name)
            time.sleep(2.5)
            m = js(sock, """(function(){
              function r(id){var e=document.getElementById(id);if(!e)return null;
                var b=e.getBoundingClientRect();return {t:b.top,w:b.width,h:b.height};}
              var c=r('%(p)s-sect-conn'), a=r('%(p)s-sect-acc'), s=r('%(cb)s');
              var cb=document.getElementById('%(cb)s');
              var body=document.getElementById('%(p)s-sect-conn-body');
              return {c:c,a:a,s:s,an:!!(cb&&cb.checked),
                im:!!(cb&&body&&body.contains(cb)),
                aw:getComputedStyle(document.getElementById('%(p)s-sect-acc')).display,
                ueber:document.documentElement.scrollWidth-document.documentElement.clientWidth,
                kp:!!document.getElementById('%(n)s-kachel-pflicht'),
                hdr:(document.querySelector('#%(p)s-sect-conn .kb-collapse-header h3')||{}).textContent};
            })()""" % {"p": pre, "cb": cb, "n": name}) or {}
            c, a, sw = m.get("c"), m.get("a"), m.get("s")
            check("%s: Container \"Verbindung\" gemalt" % name, bool(c) and c["w"] > 300 and c["h"] > 40,
                  str(c))
            check("%s: Titel \"Verbindung\"" % name, (m.get("hdr") or "").strip() == "Verbindung",
                  repr(m.get("hdr")))
            check("%s: Schalter sichtbar im Container \"Verbindung\"" % name,
                  bool(m.get("im")) and bool(sw) and sw["w"] > 0 and sw["h"] > 0, str(sw))
            if m.get("aw") != "none":
                check("%s: \"Persönliche …-Zugänge\" steht UNTER \"Verbindung\"" % name,
                      bool(a) and bool(c) and a["t"] > c["t"] + c["h"] - 1, "%s / %s" % (c, a))
            else:
                print("  …    %s: Container ausgeblendet (persoenliche Zugaenge aus)" % name)
            if name in ("sap", "vemas"):
                # EIN Haken (Betreiber 2026-11-15): "persoenlich aus" IST die Kachelpflicht.
                check("%s: kein zweiter Haken \"Anmeldung über die Portal-Kachel\"" % name,
                      not m.get("kp"))
                # Container folgt dem Haken (Betreiber 2026-11-15): aus = ausgeblendet.
                check("%s: Container \"Persönliche …-Zugänge\" sichtbar genau dann, wenn angehakt" % name,
                      (m.get("aw") != "none") == bool(m.get("an")),
                      "angehakt=%s display=%s" % (m.get("an"), m.get("aw")))
            check("%s: kein waagerechter Ueberlauf" % name, (m.get("ueber") or 0) <= 0,
                  str(m.get("ueber")))
            bild = cdp(sock, "Page.captureScreenshot", format="png")
            if bild.get("data"):
                (ABLAGE / ("%s-%s.png" % (name, thema))).write_bytes(base64.b64decode(bild["data"]))
        fehler = js(sock, "window.__fehler || ''")
        check("keine JS-Fehler (%s)" % thema, not fehler, fehler or "")

print("\nBilder: %s" % ABLAGE)
print("Ergebnis: %d OK, %d FAIL" % (_ok, _fail))
ende(0 if _fail == 0 else 1)
