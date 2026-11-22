#!/usr/bin/env python3
"""Live-Probe (Chrome, DEV): Sicherheitsprotokoll folgt dem Sprachwechsel.

VORFALL (2026-11-22, im Code gefunden, auf DEV gemessen): vier Module
(sicherheitsprotokoll.js, protokolle.js, fehleranalyse.js, token_verbrauch.js)
hoerten auf `jarvis-lang-changed` am `document`. `i18n.js` sendet das Ereignis
aber am `window` – ein Ereignis am window erreicht einen Zuhoerer am document
nie (es laeuft nicht abwaerts). Nach DE → EN blieben Ereignisnamen, Ketten-
aussage und Zeitformat in der alten Sprache. Die jsdom-Waechter waren gruen,
weil sie das Ereignis SELBST am document ausloesten – sie bestaetigten die
Annahme des Codes statt den echten Weg.

Diese Probe geht deshalb nur den echten Weg: `window.setLang()` →
`applyLang()` → Ereignis. Geprueft:
  1. nach DE → EN stehen Eintraege, Auswahlliste und Kettenaussage auf
     Englisch, die gewaehlte Ereignisart bleibt gewaehlt
  2. EN → DE wieder zurueck
  3. `applyLang()` OHNE Sprachwechsel (feuert das Ereignis ebenfalls, andere
     Module rufen es an vielen Stellen) baut die Auswahlliste NICHT neu auf –
     eine gerade geoeffnete Liste bleibt offen

`fetch` und `localStorage` stehen VOR dem ersten Skript
(`Page.addScriptToEvaluateOnNewDocument`), angemeldet wird nicht.
Aufruf auf DEV: venv/bin/python tests/live_sprachwechsel_ui_dev.py
Exit 0 = gruen, 1 = mindestens ein FAIL, 2 = konnte nicht laufen.
"""
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


ARTEN = ["anmeldung", "anmeldung_fehlgeschlagen", "cve_pruefung", "dienst_start", "konto_gesperrt"]
DATEN = {"eintraege": [{"ts": 1792505727, "art": a, "benutzer": "x", "ip": "192.0.2.1",
                        "ergebnis": "200", "details": {}} for a in ARTEN],
         "arten": ARTEN, "kette": {"ok": True, "zeilen": len(ARTEN), "brueche": [], "anzahl_brueche": 0},
         "aufbewahrung_tage": 365, "syslog": True, "schreibfehler": {"datei": 0}}
DE, EN = "Anmeldung fehlgeschlagen", "Sign-in failed"   # sprot.art.anmeldung_fehlgeschlagen

VORLAUF = r"""
window.__fehler = [];
window.addEventListener('error', function (e) { window.__fehler.push((e.filename || '?') + ': ' + e.message); });
try { localStorage.setItem('jarvis_token', 'probe'); localStorage.setItem('jarvis_lang', 'de'); } catch (e) {}
(function () {
  function antwort(d) {
    return Promise.resolve({ ok: true, status: 200, headers: { get: function () { return null; } },
      json: function () { return Promise.resolve(d); },
      text: function () { return Promise.resolve(JSON.stringify(d)); } });
  }
  window.fetch = function (u) {
    var url = String(u).split('?')[0];
    if (url === '/api/me') return antwort({ is_admin: true, username: 'probe', permissions: {} });
    if (url === '/api/verify-token') return antwort({ valid: true, username: 'probe', is_admin: true });
    if (url === '/api/security/log') return antwort(__DATEN__);
    return antwort({ ok: true, items: [], skills: [], groups: [], profiles: [], entries: [] });
  };
})();
""".replace("__DATEN__", json.dumps(DATEN))

PROFIL = tempfile.mkdtemp(prefix="chrome-sprache-", dir=str(Path.home()))
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1280,900",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ende(code):
    chrome.kill()
    time.sleep(1)
    shutil.rmtree(PROFIL, ignore_errors=True)
    print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
    sys.exit(code)


def ziel_ws():
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


ws = ziel_ws()
if not ws:
    print("ABBRUCH: kein CDP-Ziel")
    ende(2)
try:
    from websockets.sync.client import connect
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Modul fehlt im venv ({e})")
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


# Sichtbarer Zustand des Abschnitts in EINER Abfrage
LAGE = """(function(){var s=document.getElementById('sprot-filter-art');
  var o=s?Array.from(s.options).filter(function(x){return x.value==='anmeldung_fehlgeschlagen';})[0]:null;
  var tb=document.getElementById('sprot-tbody'),k=document.getElementById('sprot-kette');
  var m=document.getElementById('login-screen');
  return {n:s?s.options.length:0, sichtbar:!!(s&&s.offsetParent), wert:s?s.value:'',
          option:o?o.textContent:'', tabelle:tb?tb.textContent:'', kette:k?k.textContent:'',
          lang:window._lang, setLang:typeof window.setLang,
          maske:m?getComputedStyle(m).display:'keine'};})()"""

with connect(ws, open_timeout=20, max_size=80_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    cdp(sock, "Page.addScriptToEvaluateOnNewDocument", source=VORLAUF)
    cdp(sock, "Page.navigate", url="https://127.0.0.1/settings")
    time.sleep(5)
    js(sock, "document.querySelector('[data-settings-tab=\"telemetry\"]').click()")
    time.sleep(0.8)
    js(sock, "document.querySelector('[data-klick=\"sprot-klappen\"]').click()")
    time.sleep(1.5)

    # ── Positivkontrollen: Seite da, Abschnitt deutsch gefuellt ──
    l0 = js(sock, LAGE)
    if (not l0 or not l0["sichtbar"] or l0["n"] != len(ARTEN) + 1 or l0["maske"] not in ("none", "keine")
            or l0["setLang"] != "function" or l0["lang"] != "de" or DE not in l0["tabelle"] or l0["option"] != DE):
        print(f"ABBRUCH: Abschnitt nicht messbar ({l0})")
        ende(2)
    print(f"Positivkontrolle: Abschnitt deutsch gefuellt ({l0['n']} Eintraege in der Auswahl)")
    kette_de = l0["kette"]

    # Eine Art waehlen – der Sprachwechsel darf die Auswahl nicht verwerfen
    js(sock, "(function(){var s=document.getElementById('sprot-filter-art');s.value='cve_pruefung';"
             "s.dispatchEvent(new Event('change'));})()")
    time.sleep(1.0)
    if js(sock, "document.getElementById('sprot-filter-art').value") != "cve_pruefung":
        print("ABBRUCH: Auswahl liess sich nicht setzen")
        ende(2)

    print("\n── 1. DE → EN ueber window.setLang ──")
    js(sock, "window.setLang('en')")
    time.sleep(0.8)
    l1 = js(sock, LAGE)
    check("Sprache ist umgestellt (Messaufbau)", l1["lang"] == "en", l1["lang"])
    check("Ereignisname in der Tabelle englisch", EN in l1["tabelle"] and DE not in l1["tabelle"],
          l1["tabelle"][:120])
    check("Eintrag in der Auswahlliste englisch", l1["option"] == EN, l1["option"])
    check("Kettenaussage neu gezeichnet", l1["kette"] != kette_de and bool(l1["kette"]),
          l1["kette"][:120])
    check("gewaehlte Ereignisart bleibt gewaehlt", l1["wert"] == "cve_pruefung", l1["wert"])

    print("\n── 2. EN → DE zurueck ──")
    js(sock, "window.setLang('de')")
    time.sleep(0.8)
    l2 = js(sock, LAGE)
    check("Ereignisname wieder deutsch", DE in l2["tabelle"] and EN not in l2["tabelle"], l2["tabelle"][:120])
    check("Auswahlliste wieder deutsch", l2["option"] == DE, l2["option"])
    check("Kettenaussage wieder wie am Anfang", l2["kette"] == kette_de, l2["kette"][:120])

    print("\n── 3. applyLang() ohne Wechsel baut die offene Liste nicht neu ──")
    # Zaehler am window: belegt, dass das Ereignis WIRKLICH gefeuert hat –
    # sonst waere "nicht neu gebaut" trivial wahr.
    js(sock, "window.__ereignisse=0;window.addEventListener('jarvis-lang-changed',function(){window.__ereignisse++;});"
             "Array.from(document.getElementById('sprot-filter-art').options).forEach(function(o){o.__marke=1;});")
    r = js(sock, "(function(){var s=document.getElementById('sprot-filter-art');s.scrollIntoView({block:'center'});"
                 "var b=s.getBoundingClientRect();return {x:b.left+b.width/2,y:b.top+b.height/2};})()")
    for t in ("mousePressed", "mouseReleased"):
        cdp(sock, "Input.dispatchMouseEvent", type=t, x=r["x"], y=r["y"], button="left", clickCount=1)
        time.sleep(0.3)
    offen_vorher = js(sock, "document.getElementById('sprot-filter-art').matches(':open')")
    js(sock, "window.applyLang()")
    time.sleep(0.5)
    l3 = js(sock, "(function(){var s=document.getElementById('sprot-filter-art');"
                  "return {n:window.__ereignisse,offen:s.matches(':open'),"
                  "markiert:Array.from(s.options).every(function(o){return o.__marke===1;})};})()")
    if not l3 or l3["n"] < 1:
        print(f"ABBRUCH: applyLang() hat kein Ereignis gefeuert – Pruefung waere trivial ({l3})")
        ende(2)
    check("Positivkontrolle: Liste war vor applyLang() offen", offen_vorher is True, str(offen_vorher))
    check("Eintraege der Auswahlliste nicht neu aufgebaut", l3["markiert"], str(l3))
    check("Liste ist nach applyLang() noch offen", l3["offen"], str(l3))
    cdp(sock, "Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)

    fehler = js(sock, "window.__fehler") or []
    check("keine JS-Fehler", not fehler, "; ".join(fehler)[:300])

ende(0 if _fail == 0 else 1)
