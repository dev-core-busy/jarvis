#!/usr/bin/env python3
"""Optische Abnahme des Maximier-Knopfes in /feedback (hell UND dunkel).

⚠ GEMESSEN WIRD DIE AUSGELIEFERTE SEITE, nicht ein Markup-Schnitt: nur so ist
die ECHTE Titelleiste dabei – und genau gegen sie wird gerechnet (`--fb-top`)
und gestapelt (z-index). Eine Probeseite ohne `.topbar` koennte beides gar
nicht zeigen, und sie liesse ausserdem einen Rueckstand unter `frontend/`
(Register: `test_theme_default` laeuft ueber jede HTML-Datei dort).

Angemeldet wird nicht: `fetch` und `localStorage` werden VOR dem ersten Skript
der Seite gestellt (`Page.addScriptToEvaluateOnNewDocument`) – ein spaeteres
`Runtime.evaluate` kaeme zu spaet, die Seite hat sich dann laengst aufs Portal
umgeleitet (Register).

Aufruf auf DEV: cd /opt/jarvis && ./venv/bin/python tests/live_fb_max_ui_dev.py
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


FORM = {
    "id": "f1", "titel": "Modulbewertung",
    "beschreibung": "Bitte bewerte die Module, mit denen du arbeitest.",
    "aktiv": True,
    "spalten": [{"id": "c1", "name": "Modul", "typ": "text"},
                {"id": "c2", "name": "Bewertung", "typ": "sterne"},
                {"id": "c3", "name": "Anmerkung und weitere Hinweise zur Bedienung",
                 "typ": "text"}]}

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
  // Der Klapp-Zustand muss sauber sein: ein zugeklapptes Formular aus einem
  // frueheren Lauf machte jede Messung darunter trivial.
  localStorage.removeItem('jarvis_feedback_zu');
} catch (e) {}
(function () {
  function antwort(d) {
    return Promise.resolve({ ok: true, status: 200, headers: { get: function () { return null; } },
      json: function () { return Promise.resolve(d); },
      text: function () { return Promise.resolve(JSON.stringify(d)); } });
  }
  window.fetch = function (u, o) {
    var url = String(u).split('?')[0];
    if (url === '/api/me') { return antwort({ is_admin: false, permissions: { feedback: true } }); }
    if (url === '/api/feedback/formulare') { return antwort({ ok: true, formulare: [__FORM__] }); }
    if (url === '/api/feedback/meine') { return antwort({ ok: true, abgaben: [] }); }
    return antwort({ ok: true });
  };
})();
"""

PROFIL = tempfile.mkdtemp(prefix="chrome-fbmax-", dir=str(Path.home()))
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
print("Optische Abnahme: Maximieren in /feedback")
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

    for thema in ("dunkel", "hell"):
        print(f"\n── {thema} " + "─" * 55)
        cdp(sock, "Emulation.setEmulatedMedia", media="screen", features=[
            {"name": "prefers-color-scheme",
             "value": "dark" if thema == "dunkel" else "light"}])
        cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
            source=VORLAUF.replace("__THEMA__",
                                   "dark" if thema == "dunkel" else "light")
                          .replace("__FORM__", json.dumps(FORM, ensure_ascii=False)))
        cdp(sock, "Page.navigate", url="https://127.0.0.1/feedback")
        time.sleep(3.0)

        # ── Positivkontrollen: ohne sie ist alles darunter trivial wahr ─────
        fehler = js(sock, "window.__fehler || ''")
        check("keine JS-Fehler auf der Seite", not fehler, fehler or "")
        sichtbar = js(sock, "!!document.querySelector('#fb-app') && "
                            "!document.querySelector('#fb-app').classList.contains('hidden')")
        check("die Seite ist sichtbar (Positivkontrolle)", bool(sichtbar))
        tabW = js(sock, "(function(){var t=document.querySelector('#fb-tabelle table');"
                        "return t?Math.round(t.getBoundingClientRect().width):0;})()")
        check("die Tabelle ist gezeichnet (Positivkontrolle)", (tabW or 0) > 200,
              f"Breite {tabW}")
        if not sichtbar or not tabW:
            bild(sock, f"fbmax-{thema}-KAPUTT.png")
            continue

        grund = farbe(js(sock, "getComputedStyle(document.body).backgroundColor"))
        print(f"       Grundfarbe: {grund}")

        # ── Der Knopf: da, sichtbar, rechts in der Kopfzeile ────────────────
        kb = js(sock, RECHTECK % '.ja-card[data-klapp="form"] [data-act="max"]')
        check("der Knopf ist gezeichnet und hat eine Groesse",
              bool(kb) and kb["w"] > 15 and kb["h"] > 15,
              json.dumps(kb))
        h2 = js(sock, RECHTECK % '.ja-card[data-klapp="form"] .ja-card-head h2')
        check("er steht RECHTS in der Kopfzeile",
              bool(kb) and bool(h2) and kb["x"] > h2["x"] + h2["w"],
              f"Knopf x={kb and kb['x']} / h2 endet {h2 and h2['x'] + h2['w']}")
        caret = js(sock, RECHTECK % '.ja-card[data-klapp="form"] .ja-caret')
        # Gruppe: der Abstand zwischen Knopf und Caret ist klein (gap 6px),
        # nicht ueber die halbe Zeile verteilt.
        if kb and caret:
            luecke = caret["x"] - (kb["x"] + kb["w"])
            check("Knopf und Caret stehen als GRUPPE beieinander",
                  0 <= luecke <= 20, f"Luecke {luecke}px")

        vg = farbe(js(sock, "getComputedStyle(document.querySelector("
                            "'.ja-card[data-klapp=\"form\"] [data-act=\"max\"]')).color"))
        hg = farbe(js(sock, "getComputedStyle(document.querySelector("
                            "'.ja-card[data-klapp=\"form\"]')).backgroundColor"))
        k = kontrast(vg, hg)
        check(f"das Zeichen ist erkennbar (Kontrast {k:.2f}:1, Grafik-Grenze 3:1)",
              k >= 3.0, f"{vg} auf {hg}")

        vorherW = js(sock, RECHTECK % '.ja-card[data-klapp="form"]')["w"]
        bild(sock, f"fbmax-{thema}-1-normal.png")

        # ── Viele Zeilen anlegen: nur dann MUSS der Koerper scrollen ────────
        js(sock, "(function(){var b=document.getElementById('fb-zeile-neu');"
                 "for(var i=0;i<18;i++){b.click();}})()")
        time.sleep(0.4)

        # ── Maximieren ─────────────────────────────────────────────────────
        js(sock, "document.querySelector('.ja-card[data-klapp=\"form\"] "
                 "[data-act=\"max\"]').click()")
        time.sleep(0.6)
        maxi = js(sock, "document.querySelector('.ja-card[data-klapp=\"form\"]')"
                        ".classList.contains('is-max')")
        check("die Karte ist maximiert (Positivkontrolle)", bool(maxi))

        kr = js(sock, RECHTECK % '.ja-card[data-klapp="form"]')
        fensterB = js(sock, "window.innerWidth")
        fensterH = js(sock, "window.innerHeight")
        check("die Karte nutzt die volle Fensterbreite",
              bool(kr) and kr["w"] >= fensterB - 2 and kr["w"] > vorherW + 100,
              f"{kr and kr['w']}px statt {vorherW}px (Fenster {fensterB})")

        bar = js(sock, RECHTECK % '.topbar')
        check("sie beginnt GENAU unter der Titelleiste",
              bool(kr) and bool(bar) and abs(kr["y"] - bar["b"]) <= 2,
              f"Karte y={kr and kr['y']} / Leiste endet {bar and bar['b']}")
        check("und reicht bis zum unteren Rand",
              bool(kr) and abs(kr["b"] - fensterH) <= 2,
              f"unten {kr and kr['b']} / Fenster {fensterH}")

        # ⚠ DIE TITELLEISTE MUSS BEDIENBAR BLEIBEN – das ist die z-index-Zusage.
        #   `elementFromPoint` ist der ehrliche Test: er sagt, was der Klick
        #   wirklich trifft.
        treffer = js(sock, "(function(){var b=document.getElementById('fb-logout-btn');"
                           "if(!b)return 'kein Knopf';var r=b.getBoundingClientRect();"
                           "var e=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);"
                           "return e&&e.closest('#fb-logout-btn')?'knopf':"
                           "(e?e.className||e.tagName:'nichts');})()")
        check("⚠ die Titelleiste bleibt bedienbar (Abmelden ist anklickbar)",
              treffer == "knopf", f"getroffen: {treffer}")

        # ⚠ DER KOERPER MUSS SCROLLEN – das ist die `min-height: 0`-Zusage.
        #   Ohne sie waechst er ueber die Karte hinaus, `overflow-y` bleibt
        #   wirkungslos, und der Absenden-Knopf ist NICHT erreichbar.
        scroll = js(sock, "(function(){var b=document.querySelector("
                          "'.ja-card.is-max > .ja-card-body');if(!b)return null;"
                          "return {s:b.scrollHeight,c:b.clientHeight};})()")
        check("⚠ der Karten-Koerper scrollt (min-height: 0 wirkt)",
              bool(scroll) and scroll["s"] > scroll["c"] + 1,
              json.dumps(scroll))
        # Und der Absenden-Knopf ist durch Scrollen wirklich zu erreichen.
        erreichbar = js(sock, "(function(){var b=document.querySelector("
                              "'.ja-card.is-max > .ja-card-body');"
                              "b.scrollTop=b.scrollHeight;"
                              "var s=document.getElementById('fb-senden');"
                              "var r=s.getBoundingClientRect();"
                              "return r.bottom<=window.innerHeight+1&&r.top>=0;})()")
        check("⚠ und der Absenden-Knopf ist darin erreichbar", bool(erreichbar))

        ueber = js(sock, "document.documentElement.scrollWidth - "
                         "document.documentElement.clientWidth")
        check("kein waagerechter Ueberlauf der Seite", (ueber or 0) <= 0,
              f"{ueber}px")

        bild(sock, f"fbmax-{thema}-2-maximiert.png")

        # ── Escape ─────────────────────────────────────────────────────────
        cdp(sock, "Input.dispatchKeyEvent", type="keyDown", key="Escape",
            code="Escape", windowsVirtualKeyCode=27, nativeVirtualKeyCode=27)
        cdp(sock, "Input.dispatchKeyEvent", type="keyUp", key="Escape",
            code="Escape", windowsVirtualKeyCode=27, nativeVirtualKeyCode=27)
        time.sleep(0.4)
        zurueck = js(sock, "!document.querySelector('.ja-card.is-max')")
        check("Escape verkleinert wieder (echte Tastatur)", bool(zurueck))

print("\n" + "=" * 74)
print(f"{_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
