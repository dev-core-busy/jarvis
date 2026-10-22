#!/usr/bin/env python3
"""Optische Abnahme der Zeile "Spracheingabe (STT)" in KI & System -> System-Einstellungen
(hell UND dunkel), an der AUSGELIEFERTEN Seite /settings in Chrome.

Misst: die Zeile steht direkt vor "Sprachausgabe (TTS)"; der gespeicherte Stand
(GET /api/settings/stt) wird geladen; das Adressfeld erscheint nur bei "fern",
ist breit genug und bleibt in seiner Zelle (jsdom rechnet kein Layout);
Speichern schickt quelle+url, und das Pruefergebnis steht AM Knopf; keine
JS-Fehler. Screenshots je Thema unter ~/.jarvis-abnahme/.

Angemeldet wird nicht: Token und fetch-Attrappe stehen VOR dem ersten Skript
der Seite (Page.addScriptToEvaluateOnNewDocument). ⚠ Die Attrappe muss
/api/verify-token mit {valid: true} beantworten – sonst meldet sich die Seite
ab, openModal laeuft nie, und JEDE Ladepruefung schlaegt fehl, ohne dass der
Code schuld ist (beim Bau so gemessen: 8 FAIL aus der Attrappe).

Aufruf auf DEV: cd /opt/jarvis && runuser -u jarvis -- env HOME=/home/jarvis \
    venv/bin/python tests/live_stt_einstellung_ui_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
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

ROOT = Path("/opt/jarvis") if Path("/opt/jarvis/frontend").is_dir() else \
    Path(__file__).resolve().parent.parent
ZIEL = os.environ.get("JARVIS_URL", "https://127.0.0.1/settings")
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


VORLAUF = r"""
window.__fehler = '';
window.__posts = [];
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
window.addEventListener('unhandledrejection', function (e) {
  window.__fehler += 'ZURUECKWEISUNG: ' + ((e.reason && e.reason.message) || e.reason) + ' | ';
});
var _ce = console.error; console.error = function () { window.__fehler += 'console.error: ' + Array.prototype.join.call(arguments, ' ') + ' | '; return _ce.apply(console, arguments); };
try { localStorage.setItem('jarvis_token', 'probe'); localStorage.setItem('jarvis_theme', '__THEMAWERT__'); } catch (e) {}
(function () {
  function antwort(d) {
    return Promise.resolve({ ok: true, status: 200, headers: { get: function () { return null; } },
      json: function () { return Promise.resolve(d); }, text: function () { return Promise.resolve(JSON.stringify(d)); } });
  }
  window.fetch = function (u, init) {
    var url = String(u).split('?')[0];
    if (url === '/api/me') return antwort({ username: 'jarvis', is_admin: true, permissions: {} });
    if (url === '/api/skills') return antwort({ skills: [] });
    if (url === '/api/verify-token') return antwort({ valid: true, username: 'jarvis', is_admin: true });
    if (url === '/api/settings') return antwort({ profiles: [], active_profile_id: '', defaults: {}, tts_voice: '', llm_timeout: 180 });
    if (url === '/api/settings/stt') {
      if (init && init.method === 'POST') {
        window.__posts.push(JSON.parse(init.body));
        return antwort({ ok: true, quelle: 'fern', url: 'ws://stt-dienst.beispiel.de:8090/ws/stt',
                         erreichbar: { ok: true, detail: 'ok', modell: 'faster-whisper-large-v3', geraet: 'cuda' } });
      }
      return antwort({ quelle: 'fern', url: 'ws://stt-dienst.beispiel.de:8090/ws/stt', quellen: ['lokal', 'fern'] });
    }
    return antwort({ ok: true });
  };
})();
"""
PROFIL = tempfile.mkdtemp(prefix="chrome-sttzeile-", dir=str(Path.home()))
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
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as a:
                for t in json.loads(a.read()):
                    # ⚠ NUR type=="page": /json/list liefert auch die eingebauten
                    # Erweiterungen; wer blind [0] nimmt, misst deren
                    # background.html und damit gar nichts (Register).
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
print("Optische Abnahme: Zeile Spracheingabe (STT)")
print("Ziel:", ZIEL)
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
        d = json.loads(sock.recv(timeout=40))
        if d.get("id") == _id[0]:
            if "error" in d:
                raise RuntimeError(f"{m}: {d['error']}")
            return d.get("result", {})


def js(sock, a):
    r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def bild(sock, name):
    r = cdp(sock, "Page.captureScreenshot", format="png")
    if r.get("data"):
        p = BILDER / name
        p.write_bytes(base64.b64decode(r["data"]))
        print(f"       Screenshot: {p}")


RECHTECK = """(function(){var e=document.querySelector(%s);if(!e)return null;
var r=e.getBoundingClientRect();
return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),
        h:Math.round(r.height),r:Math.round(r.right),b:Math.round(r.bottom)};})()"""


def rect(sock, sel):
    return js(sock, RECHTECK % json.dumps(sel))



_vorlauf = [None]
with connect(ws, open_timeout=20, max_size=80_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    for thema in ("dunkel", "hell"):
        print(f"\n── {thema} " + "─" * 55)
        if _vorlauf[0]:
            cdp(sock, "Page.removeScriptToEvaluateOnNewDocument", identifier=_vorlauf[0])
        _vorlauf[0] = cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
            source=VORLAUF.replace("__THEMAWERT__", "dark" if thema == "dunkel" else "light")).get("identifier")
        cdp(sock, "Emulation.setDeviceMetricsOverride", width=1400, height=900, deviceScaleFactor=1, mobile=False)
        cdp(sock, "Page.navigate", url=ZIEL)
        time.sleep(4.0)
        if not js(sock, "!!document.querySelector('#settings-modal.open')"):
            js(sock, "(function(){var m=document.getElementById('settings-modal');if(m)m.classList.add('open');"
                     "var l=document.getElementById('login-screen');if(l)l.classList.remove('active');return 1;})()")
            time.sleep(0.8)
        check("Einstellungen sind offen", bool(js(sock, "!!document.querySelector('#settings-modal.open')")))
        js(sock, "(function(){var b=document.querySelector('[data-settings-tab=profiles]');if(b)b.click();"
                 "var h=document.getElementById('prof-sect-tuning-hdr');if(h&&h.classList.contains('is-collapsed'))h.click();return 1;})()")
        time.sleep(1.0)
        reihenfolge = js(sock, """(function(){var a=document.getElementById('setting-stt-quelle'),
            b=document.getElementById('setting-tts-voice'); if(!a||!b) return null;
            var za=a.closest('tr'), zb=b.closest('tr'); var n=za.nextElementSibling, s=0;
            while(n && n!==zb){ s++; n=n.nextElementSibling; } return n===zb ? s : -1;})()""")
        check("Zeile steht direkt vor „Sprachausgabe (TTS)“ (nur die Hinweiszeile dazwischen)", reihenfolge == 1, str(reihenfolge))
        check("gespeicherter Stand geladen: fern + Adresse",
              js(sock, "document.getElementById('setting-stt-quelle').value") == "fern"
              and "beispiel.de" in (js(sock, "document.getElementById('setting-stt-url').value") or ""))
        js(sock, "document.getElementById('setting-stt-quelle').closest('tr').scrollIntoView({block:'center'})")
        time.sleep(0.5)
        feld = rect(sock, "#setting-stt-url")
        zelle = js(sock, "(function(){var r=document.getElementById('setting-stt-url').closest('td').getBoundingClientRect();return {x:Math.round(r.x),r:Math.round(r.right)};})()")
        check("Adressfeld sichtbar und breit genug", bool(feld) and feld["w"] >= 200 and feld["h"] > 15, json.dumps(feld))
        check("Adressfeld bleibt in seiner Zelle", bool(feld) and bool(zelle) and feld["r"] <= zelle["r"] + 1, f"{feld} {zelle}")
        z = js(sock, """(function(){var r=document.getElementById('setting-stt-quelle').closest('tr').getBoundingClientRect();
            return {x:Math.round(r.x),y:Math.round(r.y+window.scrollY),w:Math.round(r.width),h:Math.round(r.height)};})()""")
        js(sock, "document.getElementById('btn-save-stt').click()")
        time.sleep(0.8)
        status = js(sock, "document.getElementById('stt-status').textContent") or ""
        check("Speichern schickt quelle+url", js(sock, "JSON.stringify(window.__posts)") ==
              json.dumps([{"quelle": "fern", "url": "ws://stt-dienst.beispiel.de:8090/ws/stt"}], separators=(",", ":")),
              js(sock, "JSON.stringify(window.__posts)"))
        check("Ergebnis steht am Knopf", "large-v3" in status, status)
        r = cdp(sock, "Page.captureScreenshot", format="png", clip={"x": 0, "y": max(0, z["y"] - 70), "width": 1400, "height": z["h"] + 140, "scale": 1})
        p = BILDER / f"stt_zeile_{thema}.png"; p.write_bytes(base64.b64decode(r["data"])); print("       Screenshot:", p)
        js(sock, "(function(){var s=document.getElementById('setting-stt-quelle');s.value='lokal';s.dispatchEvent(new Event('change'));return 1;})()")
        time.sleep(0.3)
        check("bei „Auf diesem Server“ verschwindet das Adressfeld",
              js(sock, "document.getElementById('setting-stt-url').hidden && document.getElementById('setting-stt-url').getBoundingClientRect().height===0"))
        fehler = js(sock, "window.__fehler") or ""
        check("keine JS-Fehler", not fehler, fehler[:300])
print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
