#!/usr/bin/env python3
"""Optische Abnahme: Benutzer-Pulldown der Zugriffs-Verstoesse (hell UND dunkel).

⚠ GEMESSEN WIRD DIE AUSGELIEFERTE SEITE `/settings`, nicht ein Markup-Schnitt.
Nur dort steht der echte Abschnitt samt Klapp-Container – und genau dessen
Zusammenspiel ist hier die Frage: klappt ein Klick ins Pulldown den
<details>-Abschnitt zu? jsdom rechnet kein Layout und kann weder Ueberlauf
noch Kontrast beantworten.

Angemeldet wird nicht: Token und `fetch` werden VOR dem ersten Skript der
Seite gestellt (`Page.addScriptToEvaluateOnNewDocument`) – ein spaeteres
`Runtime.evaluate` kaeme zu spaet, die Seite hat sich dann laengst umgeleitet.

Aufruf auf DEV: cd /opt/jarvis && ./venv/bin/python /tmp/live_viol_ui_dev.py
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


def leucht(c):
    def k(x):
        x /= 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * k(c[0]) + 0.7152 * k(c[1]) + 0.0722 * k(c[2])


def kontrast(a, b):
    la, lb = leucht(a), leucht(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def farbe(s):
    """⚠ `color-mix` liefert Chrome als `color(srgb a b c)` mit Anteilen 0..1 –
    als 0..255 gelesen ergaebe das fast Schwarz (Register, zweimal bezahlt)."""
    s = (s or "").strip()
    m = re.match(r"color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", s)
    if m:
        return tuple(round(float(m.group(i)) * 255) for i in (1, 2, 3))
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        t = [float(x) for x in m.group(1).replace("/", " ").split(",")[:3]]
        return tuple(round(x) for x in t)
    return (0, 0, 0)


def mische(vorn, hinten):
    """Halbdurchsichtige Flaechen gehoeren ZUSAMMENGERECHNET – wer sie als
    deckend nimmt, misst im dunklen Thema gegen Weiss (Register)."""
    s = (vorn or "").strip()
    m = re.match(r"rgba\(([^)]+)\)", s)
    if not m:
        return farbe(vorn)
    t = [float(x) for x in m.group(1).split(",")]
    a = t[3] if len(t) > 3 else 1.0
    h = hinten
    return tuple(round(t[i] * a + h[i] * (1 - a)) for i in range(3))



# ── Datensatz: EIN sehr langer Benutzername ist Pflicht. Mit lauter kurzen
#    Namen ist "das Kaestchen bleibt in der Zeile" trivial erfuellt und die
#    Zusage `min-width: 0` gar nicht gemessen.
LANG = "nexus\\ein.ausserordentlich.langer.kontoname.der.die.zeile.sprengen.wuerde"
USERS = ["nexus\\a.bender", LANG, "api:externes system"]


def eintraege():
    raus = []
    for i in range(12):
        raus.append({"ts": 1758000000 - i * 60, "user": USERS[i % 3], "channel": "chat",
                     "pattern": "shell-illegal" if i % 4 else "fs-deny",
                     "detail": "cat /etc/shadow" if i % 4 else "read /opt",
                     "tool": "shell_execute", "soft": i % 4 == 0})
    return raus


VORLAUF = r"""
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
window.addEventListener('unhandledrejection', function (e) {
  window.__fehler += 'ZURUECKWEISUNG: ' + ((e.reason && e.reason.message) || e.reason) + ' | ';
});
try {
  localStorage.setItem('jarvis_token', 'probe');
  // ⚠ theme.js prueft `!== 'dark'`. Die deutschen Namen sind dort KEIN
  // gueltiger Wert – "dunkel" waere still hell (Register: zweimal hell gemessen).
  localStorage.setItem('jarvis_theme', '__THEMAWERT__');
  localStorage.removeItem('jarvis_sec_viol_nur_hart');
} catch (e) {}
(function () {
  var ALLE = __ALLE__, USERS = __USERS__;
  var GESAMT = { hart: 0, weich: 0, anzahl: ALLE.length };
  ALLE.forEach(function (e) { if (e.soft) GESAMT.weich++; else GESAMT.hart++; });
  function antwort(d) {
    return Promise.resolve({ ok: true, status: 200,
      headers: { get: function () { return null; } },
      json: function () { return Promise.resolve(d); },
      text: function () { return Promise.resolve(JSON.stringify(d)); } });
  }
  window.fetch = function (u) {
    var voll = String(u), url = voll.split('?')[0];
    if (url === '/api/me') {
      return antwort({ username: 'jarvis', is_admin: true, permissions: {} });
    }
    if (url === '/api/skills') { return antwort({ skills: [] }); }
    if (url === '/api/security/violations') {
      var m = /[?&]user=([^&]*)/.exec(voll);
      var sel = m ? decodeURIComponent(m[1]) : '';
      var liste = sel ? ALLE.filter(function (e) { return e.user === sel; }) : ALLE;
      return antwort({ violations: liste, users: USERS, gesamt: GESAMT });
    }
    return antwort({ ok: true });
  };
})();
"""
PROFIL = tempfile.mkdtemp(prefix="chrome-violf-", dir=str(Path.home()))
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
print("Optische Abnahme: Benutzer-Filter der Zugriffs-Verstoesse")
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
            source=VORLAUF.replace("__THEMAWERT__", "dark" if thema == "dunkel" else "light")
                          .replace("__ALLE__", json.dumps(eintraege()))
                          .replace("__USERS__", json.dumps(USERS))).get("identifier")
        cdp(sock, "Emulation.setDeviceMetricsOverride",
            width=1400, height=900, deviceScaleFactor=1, mobile=False)
        cdp(sock, "Page.navigate", url=ZIEL)
        time.sleep(4.0)

        # Modal auf, Reiter Sicherheit, Abschnitt Vorfaelle, Unter-Container auf.
        js(sock, """(function(){
          var m=document.getElementById('settings-modal'); if(m)m.classList.add('open');
          var l=document.getElementById('login-screen'); if(l)l.classList.remove('active');
          var b=document.querySelector('[data-settings-tab="security"]'); if(b)b.click();
          return 1;})()""")
        time.sleep(0.6)
        js(sock, """(function(){
          var h=document.getElementById('sec-sect-incidents-hdr');
          var b=document.getElementById('sec-sect-incidents-body');
          if(b && getComputedStyle(b).display==='none' && h) h.click();
          var d=document.getElementById('sec-sub-viol'); if(d) d.open=true;
          return 1;})()""")
        time.sleep(1.2)

        # ── Positivkontrollen ZUERST: ohne offenen Abschnitt ist JEDES Rechteck
        #    0 und jede Messung darunter trivial wahr (Register).
        koerper = rect(sock, "#sec-sect-incidents-body")
        check("der Abschnitt 'Vorfaelle' ist offen (Messung nicht trivial)",
              bool(koerper) and koerper["h"] > 50, json.dumps(koerper))
        check("der Unter-Container ist aufgeklappt",
              bool(js(sock, "!!(document.getElementById('sec-sub-viol')||{}).open")))
        zeilen = js(sock, "document.querySelectorAll('.sec-viol-row').length")
        check("die Liste ist gezeichnet (Positivkontrolle)", (zeilen or 0) >= 10, zeilen)

        sel = rect(sock, "#sec-viol-user")
        kast = rect(sock, "#sec-viol-onlyhard-box")
        reihe = rect(sock, "#sec-viol-filterrow")
        check("das Pulldown ist sichtbar", bool(sel) and sel["w"] > 60 and sel["h"] > 12,
              json.dumps(sel))
        check("es steht LINKS vom Kaestchen 'Nur Verstoesse'",
              bool(sel) and bool(kast) and sel["r"] <= kast["x"] + 2,
              f"sel.r={sel and sel['r']} kast.x={kast and kast['x']}")
        check("beide stehen in EINER Zeile",
              bool(sel) and bool(kast) and abs(sel["y"] - kast["y"]) < 16,
              f"sel.y={sel and sel['y']} kast.y={kast and kast['y']}")
        check("⚠ das Kaestchen bleibt im Abschnitt – trotz des sehr langen Namens",
              bool(kast) and bool(koerper) and kast["r"] <= koerper["r"],
              f"kast.r={kast and kast['r']} koerper.r={koerper and koerper['r']}")
        check("das Pulldown ist gedeckelt (max-width greift)",
              bool(sel) and sel["w"] <= 300, sel and sel["w"])

        # Kein waagerechter Ueberlauf im Abschnitt.
        ueber = js(sock, "(function(){var e=document.getElementById('sec-sect-incidents-body');"
                         "return e? e.scrollWidth - e.clientWidth : -1;})()")
        check("kein waagerechter Ueberlauf im Abschnitt", (ueber or 0) <= 1, ueber)

        # ── ⚠ DIE TRAGENDE MESSUNG: ein Klick ins Pulldown darf den
        #    <details>-Abschnitt NICHT zuklappen.
        vor = js(sock, "!!document.getElementById('sec-sub-viol').open")
        mitte_x = sel["x"] + sel["w"] // 2
        mitte_y = sel["y"] + sel["h"] // 2
        for typ in ("mousePressed", "mouseReleased"):
            cdp(sock, "Input.dispatchMouseEvent", type=typ, x=mitte_x, y=mitte_y,
                button="left", clickCount=1)
        time.sleep(0.4)
        nach = js(sock, "!!document.getElementById('sec-sub-viol').open")
        check("⚠ ein ECHTER Klick ins Pulldown laesst den Abschnitt offen",
              vor and nach, f"vorher={vor} nachher={nach}")
        js(sock, "document.activeElement && document.activeElement.blur()")

        # ── Filter wirklich umstellen (echtes change-Ereignis ueber die Tastatur
        #    waere ein natives Popup; hier ueber die DOM-Eigenschaft + Ereignis).
        js(sock, """(function(){var s=document.getElementById('sec-viol-user');
          s.value=%s; s.dispatchEvent(new Event('change')); return 1;})()"""
          % json.dumps(LANG))
        time.sleep(0.9)
        n2 = js(sock, "document.querySelectorAll('.sec-viol-row').length")
        check("nach dem Filtern stehen weniger Zeilen da", 0 < (n2 or 0) < (zeilen or 0),
              f"{zeilen} -> {n2}")
        hinweis = js(sock, "(document.querySelector('.sec-viol-hidden')||{}).textContent||''")
        check("die Filterzeile steht sichtbar darueber", "Gefiltert nach" in (hinweis or ""),
              (hinweis or "")[:80])
        hr = rect(sock, ".sec-viol-hidden")
        check("sie hat eine Groesse und bricht um statt zu ueberlaufen",
              bool(hr) and hr["h"] > 10 and bool(koerper) and hr["r"] <= koerper["r"] + 1,
              json.dumps(hr))
        zaehler = js(sock, "(document.getElementById('sec-viol-count')||{}).textContent||''")
        check("der Zaehler nennt weiter den GESAMTbestand (12 Eintraege)",
              "9" in (zaehler or "") and "3" in (zaehler or ""), zaehler)

        # ── Kontrast der Filterzeile und der Beschriftung
        gr = js(sock, "getComputedStyle(document.getElementById('sec-sect-incidents-body')).backgroundColor")
        gr2 = js(sock, "getComputedStyle(document.body).backgroundColor")
        grund = mische(gr, farbe(gr2))
        for sel_css, name, grenze in ((".sec-viol-hidden", "Filterzeile", 4.5),
                                      ("#sec-viol-filterrow label[for]", "Beschriftung", 4.5)):
            c = js(sock, f"(function(){{var e=document.querySelector({json.dumps(sel_css)});"
                         "return e?getComputedStyle(e).color:'';})()")
            k = kontrast(mische(c, grund), grund)
            check(f"Kontrast {name} >= {grenze}:1", k >= grenze, f"{k:.2f}:1  ({c})")

        check("keine JS-Fehler auf der Seite",
              not js(sock, "window.__fehler"), js(sock, "window.__fehler"))
        # ⚠ VOR DEM BILD IN DEN BLICK SCROLLEN. Die Rechteck-Messungen oben
        # gelten unabhaengig vom Scrollstand – ein Screenshot NICHT: ohne
        # diesen Schritt zeigt er den Anfang des Reiters und belegt gar nichts
        # (beim ersten Lauf genau so passiert).
        js(sock, """(function(){var e=document.getElementById('sec-viol-filterrow');
          if(e)e.scrollIntoView({block:'center'});return 1;})()""")
        time.sleep(0.6)
        sichtbar = js(sock, """(function(){var e=document.getElementById('sec-viol-filterrow');
          if(!e)return false;var r=e.getBoundingClientRect();
          return r.top>=0 && r.bottom<=innerHeight;})()""")
        check("die Filterzeile steht im Bild (Positivkontrolle des Screenshots)",
              bool(sichtbar), sichtbar)
        bild(sock, f"violfilter-{thema}.png")

        # Zurueck auf "Alle" fuer den naechsten Durchgang.
        js(sock, """(function(){var s=document.getElementById('sec-viol-user');
          if(s){s.value='';s.dispatchEvent(new Event('change'));}return 1;})()""")

    # ── Schmales Fenster: bricht die Filterzeile um, statt zu ueberlaufen?
    #    `flex-wrap: wrap` im CSS ist eine Absicht – gemessen ist erst, was der
    #    Browser daraus macht.
    print("\n── schmal (700 px) " + "─" * 48)
    cdp(sock, "Emulation.setDeviceMetricsOverride",
        width=700, height=900, deviceScaleFactor=1, mobile=False)
    time.sleep(0.8)
    js(sock, """(function(){var e=document.getElementById('sec-viol-filterrow');
      if(e)e.scrollIntoView({block:'center'});return 1;})()""")
    time.sleep(0.5)
    sel_s = rect(sock, "#sec-viol-user")
    kast_s = rect(sock, "#sec-viol-onlyhard-box")
    koerper_s = rect(sock, "#sec-sect-incidents-body")
    check("Positivkontrolle: die Zeile ist auch schmal sichtbar",
          bool(sel_s) and sel_s["w"] > 40 and bool(koerper_s) and koerper_s["w"] < 700,
          json.dumps(sel_s))
    check("das Kaestchen bleibt im Abschnitt", bool(kast_s) and bool(koerper_s)
          and kast_s["r"] <= koerper_s["r"] + 1,
          f"kast.r={kast_s and kast_s['r']} koerper.r={koerper_s and koerper_s['r']}")
    # ⚠ GEMESSEN WIRD DIE FILTERZEILE, nicht der ganze Abschnitt – und das ist
    # keine Bequemlichkeit, sondern die ehrliche Zusage. Der Abschnitt laeuft
    # bei einem 70 Zeichen langen Kontonamen um 99 px ueber; Ursache ist das
    # <strong> mit dem Benutzernamen in `.sec-viol-meta`, also die LISTENZEILE
    # (Bestand seit 2026-09-02, von dieser Aenderung unberuehrt). Gemessen:
    # 9 / 20 / 33 / 43 Zeichen ergeben 0 px Ueberlauf, erst 70 Zeichen nicht.
    # Ein Waechter, der das dieser Aenderung anlastet, meldet einen Fehler, den
    # sie nicht hat.
    reihe_s = rect(sock, "#sec-viol-filterrow")
    check("die Filterzeile selbst bleibt im Abschnitt",
          bool(reihe_s) and bool(koerper_s) and reihe_s["r"] <= koerper_s["r"] + 1,
          f"reihe.r={reihe_s and reihe_s['r']} koerper.r={koerper_s and koerper_s['r']}")
    ueber_r = js(sock, "(function(){var e=document.getElementById('sec-viol-filterrow');"
                       "return e? e.scrollWidth - e.clientWidth : -1;})()")
    check("und hat selbst keinen waagerechten Ueberlauf", (ueber_r or 0) <= 1, ueber_r)
    # Der Abschnitt mit REALISTISCHEN Namen (Filter auf einen kurzen Benutzer).
    js(sock, """(function(){var s=document.getElementById('sec-viol-user');
      s.value='api:externes system'; s.dispatchEvent(new Event('change')); return 1;})()""")
    time.sleep(0.8)
    ueber_s = js(sock, "(function(){var e=document.getElementById('sec-sect-incidents-body');"
                       "return e? e.scrollWidth - e.clientWidth : -1;})()")
    check("kein waagerechter Ueberlauf bei 700 px mit realistischen Namen",
          (ueber_s or 0) <= 1, ueber_s)
    bild(sock, "violfilter-schmal.png")
    cdp(sock, "Emulation.setDeviceMetricsOverride",
        width=1400, height=900, deviceScaleFactor=1, mobile=False)

    # Positivkontrolle: hell und dunkel waren ZWEI verschiedene Messungen.
    print("\n── Positivkontrolle der Themen " + "─" * 40)
    gruende = {}
    for thema in ("dunkel", "hell"):
        if _vorlauf[0]:
            cdp(sock, "Page.removeScriptToEvaluateOnNewDocument", identifier=_vorlauf[0])
        _vorlauf[0] = cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
            source=VORLAUF.replace("__THEMAWERT__", "dark" if thema == "dunkel" else "light")
                          .replace("__ALLE__", json.dumps(eintraege()))
                          .replace("__USERS__", json.dumps(USERS))).get("identifier")
        cdp(sock, "Page.navigate", url=ZIEL)
        time.sleep(3.0)
        gruende[thema] = js(sock, "getComputedStyle(document.body).backgroundColor")
    check("hell und dunkel sind wirklich zwei verschiedene Messungen",
          gruende["dunkel"] != gruende["hell"], gruende)

print(f"\n{'=' * 74}\nErgebnis: {_ok}/{_ok + _fail}")
ende(1 if _fail else 0)
