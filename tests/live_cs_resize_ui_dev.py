#!/usr/bin/env python3
"""Optische Abnahme: Ziehgriff der Verlaufsleiste in /chat (hell UND dunkel).

jsdom rechnet KEIN Layout und kennt kein Pointer-Capture – ob der Griff zu
treffen ist, ob die Leiste dem Zeiger wirklich folgt und ob dabei nichts aus
dem Bild laeuft, beantwortet nur ein echter Browser.

⚠ GEZOGEN WIRD MIT ECHTEN MAUSEREIGNISSEN (Input.dispatchMouseEvent), nicht mit
selbst gebauten PointerEvents aus JS: die Kette pointerdown → setPointerCapture
→ pointermove ist genau das, was hier zu pruefen ist; ein synthetisches Event
umgeht sie. Eine Positivkontrolle belegt vorab, dass der Weg ueberhaupt traegt –
ohne sie waere "die Breite hat sich nicht geaendert" von einem toten Messaufbau
nicht zu unterscheiden.

Gemessen wird die EIGENSCHAFT, nicht die CSS-Zeile:
  * der Griff liegt zwischen Leiste und Chat und ist breit genug zum Treffen,
  * Ziehen aendert die Breite in die gezogene Richtung,
  * die Grenzen halten (min/max), auch gegen ein schmales Fenster,
  * das EINKLAPPEN funktioniert nach dem Ziehen weiter  ← der teuerste Fall,
  * Doppelklick stellt die Vorgabe her, Pfeiltasten wirken,
  * kein waagerechter Ueberlauf, Griff sichtbar (Kontrast) in beiden Themen.

Die Probeseite liegt NUR fuer den Lauf unter frontend/ und wird danach entfernt.
Aufruf: ./venv/bin/python tests/live_cs_resize_ui_dev.py   (oder python3)
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
    """CSS-Farbe -> (r,g,b). Chrome liefert color-mix als `color(srgb a b c)`
    mit Anteilen 0..1 – als 0..255 gelesen ergaebe das fast Schwarz (Register)."""
    s = (s or "").strip()
    m = re.match(r"color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", s)
    if m:
        return tuple(round(float(m.group(i)) * 255) for i in (1, 2, 3))
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        t = [float(x) for x in m.group(1).replace("/", " ").split(",")[:3]]
        return tuple(round(x) for x in t)
    return (0, 0, 0)


# ── Der ECHTE Code aus chat.js ──────────────────────────────────────────────
CHATJS = (ROOT / "frontend" / "js" / "chat.js").read_text(encoding="utf-8")


def schneide(name):
    for kopf in ("async function " + name, "function " + name):
        i = CHATJS.find(kopf)
        if i < 0:
            continue
        auf = CHATJS.find("{", i)
        tief = 0
        for j in range(auf, len(CHATJS)):
            if CHATJS[j] == "{":
                tief += 1
            elif CHATJS[j] == "}":
                tief -= 1
                if tief == 0:
                    return CHATJS[i:j + 1]
    return ""


# ⚠ MODUL-KONSTANTEN FALLEN AUS JEDEM FUNKTIONS-SCHNITT HERAUS (Register).
# Ohne sie stirbt der Lauf an einem nackten ReferenceError – und das sieht dann
# wie ein Codefehler aus, ist aber der Messaufbau.
KONST = "\n".join(re.findall(r"^\s*const _CS_W_[A-Z]+\s*=.*$", CHATJS, re.M))
NAMEN = ("_csMax", "_csGriff", "_csIstBreite", "_csBreiteAnwenden",
         "_csBreiteZuruecksetzen", "_csGespeicherteBreite",
         "_initSidebarResize", "_setSidebarCollapsed")
TEILE = [schneide(n) for n in NAMEN]
if not KONST or not all(TEILE):
    fehlt = [n for n, t in zip(NAMEN, TEILE) if not t]
    print(f"ABBRUCH: Schnitt unvollstaendig (Konstanten: {bool(KONST)}, fehlt: {fehlt})")
    sys.exit(2)


def markup(datei, marke, ende):
    """Das ECHTE Markup aus chat.html – kein Nachbau."""
    h = (ROOT / "frontend" / datei).read_text(encoding="utf-8")
    i = h.find(marke)
    j = h.find(ende, i)
    if i < 0 or j < 0:
        print(f"ABBRUCH: Markup {marke!r} nicht gefunden.")
        sys.exit(2)
    return h[i:j + len(ende)]


# Leiste + Griff woertlich aus chat.html, damit die Abnahme kein Layout prueft,
# das es so nicht gibt.
LEISTE = markup("chat.html", '<aside id="chat-sidebar"', "</aside>")
GRIFF = markup("chat.html", '<div id="cs-resize"', "></div>")

SEITE = """<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<link rel="stylesheet" href="css/theme.css">
<link rel="stylesheet" href="css/chat.css">
</head><body>
<div id="chat-screen" class="chat-screen">
__LEISTE__
__GRIFF__
<div id="chat-main" class="chat-main"><div style="padding:16px">Chatbereich</div></div>
</div>
<script>
window.t = function (k) { return k; };
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
try {
__KONST__
__TEILE__
_initSidebarResize();
} catch (e) { window.__fehler += 'WURF: ' + e.message; }
window.breite = function () {
  return Math.round(document.getElementById('chat-sidebar').getBoundingClientRect().width);
};
</script></body></html>"""

# ⚠ DIE PROBESEITE LIEGT NICHT UNTER frontend/ – und das ist kein Geschmack:
# `test_theme_default.js` laeuft ueber JEDE HTML-Datei dort und verlangt das
# Anti-Flacker-Skript; eine Probeseite ist damit ein FEHLALARM in einem fremden
# Waechter (beim ersten Lauf gemessen: 12/13). Nach einem `kill -9` bliebe sie
# ausserdem im Arbeitsbaum liegen. Sie steht deshalb in einem Wegwerf-Ordner,
# css/ und js/ als Symlink daneben – `http.server` folgt ihnen.
WEG = Path(tempfile.mkdtemp(prefix="csresize-", dir=str(Path.home())))
os.chmod(WEG, 0o755)
for teil in ("css", "js"):
    try:
        (WEG / teil).symlink_to(ROOT / "frontend" / teil)
    except FileExistsError:
        pass
ZIEL = WEG / "probe.html"
ZIEL.write_text(SEITE.replace("__LEISTE__", LEISTE).replace("__GRIFF__", GRIFF)
                .replace("__KONST__", KONST).replace("__TEILE__", "\n".join(TEILE)),
                encoding="utf-8")

# Ein eigener HTTP-Server: ueber `file://` laedt der Browser die Stylesheets
# nicht (CORS), und ohne CSS waere jede Layout-Messung darunter wertlos.
srv = subprocess.Popen([sys.executable, "-u", "-m", "http.server", "0", "--bind", "127.0.0.1"],
                       cwd=str(WEG), stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True)
HTTP_PORT = None
for _ in range(40):
    zeile = srv.stdout.readline()
    m = re.search(r"port (\d+)", zeile or "")
    if m:
        HTTP_PORT = int(m.group(1))
        break
if not HTTP_PORT:
    print("ABBRUCH: kein HTTP-Port.")
    srv.kill()
    shutil.rmtree(WEG, ignore_errors=True)
    sys.exit(2)
# /static/... -> frontend/...  (die Seite bindet die echten Pfade ein)
BASIS = f"http://127.0.0.1:{HTTP_PORT}"

PROFIL = tempfile.mkdtemp(prefix="chrome-csr-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()

chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1280,900",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def cdp_ziel():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as a:
                # ⚠ NUR type=="page": /json/list liefert auch die eingebauten
                # Erweiterungen – wer blind [0] nimmt, misst gar nichts.
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


def raeum():
    try:
        chrome.kill()
    except Exception:  # noqa: BLE001
        pass
    try:
        srv.kill()
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(PROFIL, ignore_errors=True)
    shutil.rmtree(WEG, ignore_errors=True)


print("=" * 74)
print("Optische Abnahme: Ziehgriff der Verlaufsleiste (/chat)")
print("=" * 74)

ws_url = cdp_ziel()
if not ws_url:
    print("ABBRUCH: kein CDP-Ziel (Chrome-Ausgabe folgt)")
    try:
        chrome.kill()
        print((chrome.stdout.read() or "")[:800])
    except Exception:  # noqa: BLE001
        pass
    raeum()
    sys.exit(2)

try:
    from websockets.sync.client import connect
except Exception:  # noqa: BLE001
    print("ABBRUCH: python-websockets fehlt.")
    raeum()
    sys.exit(2)

_id = [0]


def cdp(sock, methode, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": methode, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=30))
        if d.get("id") == _id[0]:
            return d.get("result", {})


def js(sock, ausdruck):
    r = cdp(sock, "Runtime.evaluate", expression=ausdruck, returnByValue=True,
            awaitPromise=True)
    return (r.get("result") or {}).get("value")


def maus(sock, typ, x, y, knopf="left", klicks=1):
    cdp(sock, "Input.dispatchMouseEvent", type=typ, x=x, y=y, button=knopf,
        buttons=1 if typ != "mouseReleased" else 0, clickCount=klicks)
    time.sleep(0.05)


def ziehe(sock, von_x, y, nach_x):
    """Echter Zug: druecken, in Schritten bewegen, loslassen."""
    maus(sock, "mousePressed", von_x, y)
    schritte = 6
    for i in range(1, schritte + 1):
        maus(sock, "mouseMoved", von_x + (nach_x - von_x) * i / schritte, y)
    maus(sock, "mouseReleased", nach_x, y)
    time.sleep(0.1)


def laden(sock, thema):
    # Thema VOR dem ersten Skript setzen (Register: theme.js liest den Schluessel
    # beim DOMContentLoaded noch einmal – die Klasse allein wird zurueckgesetzt).
    cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
        source=("try{localStorage.setItem('jarvis_theme',%r);"
                "localStorage.removeItem('jarvis_chat_sidebar_width');"
                "localStorage.removeItem('jarvis_chat_sidebar_collapsed');}catch(e){}"
                % thema))
    cdp(sock, "Page.navigate", url=f"{BASIS}/probe.html")
    for _ in range(60):
        if js(sock, "document.readyState") == "complete":
            break
        time.sleep(0.2)
    js(sock, "document.body.classList.toggle('light', %s)" % ("true" if thema == "light" else "false"))
    time.sleep(0.3)


with connect(ws_url, open_timeout=20, max_size=40 * 1024 * 1024) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    cdp(sock, "Emulation.setDeviceMetricsOverride", width=1280, height=900,
        deviceScaleFactor=1, mobile=False)

    for thema in ("dark", "light"):
        print(f"\n── Thema: {thema} ──")
        laden(sock, thema)

        check(f"[{thema}] Seite ohne JS-Fehler aufgebaut",
              not js(sock, "window.__fehler"), js(sock, "window.__fehler"))

        # ── ⚠ POSITIVKONTROLLE DES MESSAUFBAUS, und sie bricht HART ab ──────
        # Beim ersten Anlauf band die Probeseite `/static/css/chat.css` ein –
        # unter dem eigenen HTTP-Server ein 404, also gar kein CSS. Jede
        # Layout-Messung darunter waere wertlos gewesen, ohne dass es auffaellt.
        geladen = js(sock, "getComputedStyle(document.getElementById('chat-screen')).display")
        if geladen != "flex":
            print(f"  ABBRUCH: chat.css nicht geladen (display={geladen!r}) – "
                  "die Messung waere wertlos.")
            raeum()
            sys.exit(2)
        start = js(sock, "window.breite()")
        check(f"[{thema}] Vorgabebreite 240px (CSS greift)", start == 240, start)

        g = js(sock, """(function(){var r=document.getElementById('cs-resize')
            .getBoundingClientRect();var l=document.getElementById('chat-sidebar')
            .getBoundingClientRect();var m=document.getElementById('chat-main')
            .getBoundingClientRect();return {gx:r.x,gw:r.width,gh:r.height,
            lr:l.right,ml:m.x};})()""")
        check(f"[{thema}] Griff ist mind. 5px breit (mit der Maus zu treffen)",
              g["gw"] >= 5, g["gw"])
        check(f"[{thema}] Griff liegt zwischen Leiste und Chat",
              g["gx"] < g["ml"] + 1 and g["gx"] + g["gw"] >= g["lr"] - 1, g)
        check(f"[{thema}] Griff geht ueber die volle Hoehe", g["gh"] > 800, g["gh"])

        gx = g["gx"] + g["gw"] / 2

        # ── 1. Ziehen nach RECHTS verbreitert ───────────────────────────────
        ziehe(sock, gx, 400, gx + 120)
        breiter = js(sock, "window.breite()")
        check(f"[{thema}] Ziehen nach rechts verbreitert (240 -> ~360)",
              abs(breiter - 360) <= 8, breiter)

        # ── 2. Ziehen nach LINKS verschmaelert ──────────────────────────────
        g2 = js(sock, "document.getElementById('cs-resize').getBoundingClientRect().x")
        ziehe(sock, g2 + 3, 400, g2 + 3 - 120)
        schmaler = js(sock, "window.breite()")
        check(f"[{thema}] Ziehen nach links verschmaelert (~360 -> ~240)",
              abs(schmaler - 240) <= 8, schmaler)

        # ── 3. Grenzen ──────────────────────────────────────────────────────
        g3 = js(sock, "document.getElementById('cs-resize').getBoundingClientRect().x")
        ziehe(sock, g3 + 3, 400, 5)                      # ganz nach links
        check(f"[{thema}] Untergrenze haelt (>=180)",
              js(sock, "window.breite()") == 180, js(sock, "window.breite()"))
        g4 = js(sock, "document.getElementById('cs-resize').getBoundingClientRect().x")
        ziehe(sock, g4 + 3, 400, 1270)                   # ganz nach rechts
        weit = js(sock, "window.breite()")
        check(f"[{thema}] Obergrenze haelt (<=560 und Chat behaelt >=360)",
              weit <= 560 and 1280 - weit >= 360, weit)

        # ── 4. ⚠ DER TEUERSTE FALL: Einklappen nach dem Ziehen ──────────────
        js(sock, "_setSidebarCollapsed(true)")
        time.sleep(0.35)
        zu = js(sock, "window.breite()")
        check(f"[{thema}] EINKLAPPEN funktioniert nach dem Ziehen (Breite 0)",
              zu == 0, zu)
        griff_zu = js(sock, "getComputedStyle(document.getElementById('cs-resize')).display")
        check(f"[{thema}] Griff ist eingeklappt nicht sichtbar", griff_zu == "none", griff_zu)
        js(sock, "_setSidebarCollapsed(false)")
        time.sleep(0.35)
        auf = js(sock, "window.breite()")
        check(f"[{thema}] Ausklappen stellt die gezogene Breite wieder her",
              auf == weit, f"{auf} statt {weit}")

        # ── 5. Doppelklick -> Vorgabe ───────────────────────────────────────
        g5 = js(sock, "document.getElementById('cs-resize').getBoundingClientRect().x")
        maus(sock, "mousePressed", g5 + 3, 400, klicks=2)
        maus(sock, "mouseReleased", g5 + 3, 400, klicks=2)
        time.sleep(0.35)
        zurueck = js(sock, "window.breite()")
        check(f"[{thema}] Doppelklick stellt die Vorgabe her (240)", zurueck == 240, zurueck)
        check(f"[{thema}] und raeumt den gespeicherten Wert ab",
              js(sock, "localStorage.getItem('jarvis_chat_sidebar_width')") is None)

        # ── 6. Tastatur ─────────────────────────────────────────────────────
        js(sock, "document.getElementById('cs-resize').focus()")
        for _ in range(3):
            cdp(sock, "Input.dispatchKeyEvent", type="rawKeyDown", key="ArrowRight",
                code="ArrowRight", windowsVirtualKeyCode=39)
            cdp(sock, "Input.dispatchKeyEvent", type="keyUp", key="ArrowRight",
                code="ArrowRight", windowsVirtualKeyCode=39)
        time.sleep(0.3)
        tast = js(sock, "window.breite()")
        # ⚠ DREI DRUCKE IN FOLGE, und das ist der Kern: einzeln gemessen waere
        # der Fehler unsichtbar geblieben. Er kam daher, dass der Handler die
        # Breite MASS statt den gesetzten Wert zu lesen – waehrend der laufenden
        # Transition ist das der Zwischenwert (gemessen: 256 statt 288).
        check(f"[{thema}] drei Pfeildrucke = 3x16px, kein Schritt geht verloren (240 -> 288)",
              tast == 288, tast)

        # ── 7. Kein Ueberlauf, Griff sichtbar ───────────────────────────────
        check(f"[{thema}] kein waagerechter Ueberlauf",
              js(sock, "document.documentElement.scrollWidth <= window.innerWidth + 1"),
              js(sock, "document.documentElement.scrollWidth"))

        # Hover-Farbe des Strichs gegen den Grund der Leiste.
        js(sock, "document.getElementById('cs-resize').classList.add('is-zieht')")
        time.sleep(0.2)
        strich = farbe(js(sock, "getComputedStyle(document.getElementById('cs-resize'),"
                                "'::before').backgroundColor"))
        grund = farbe(js(sock, "getComputedStyle(document.getElementById('chat-main'))"
                               ".backgroundColor") or "rgb(0,0,0)")
        if grund == (0, 0, 0):
            grund = farbe(js(sock, "getComputedStyle(document.body).backgroundColor"))
        k = kontrast(strich, grund)
        check(f"[{thema}] gezogener Griff sichtbar (Kontrast {k:.2f}:1, Grafik-Grenze 3:1)",
              k >= 3.0, f"{strich} auf {grund}")
        js(sock, "document.getElementById('cs-resize').classList.remove('is-zieht')")

        # ── 8. Schmales Fenster: die Obergrenze zieht nach ──────────────────
        js(sock, "localStorage.setItem('jarvis_chat_sidebar_width','540')")
        laden(sock, thema)   # loescht den Schluessel wieder -> erst NACH dem Laden setzen
        js(sock, "localStorage.setItem('jarvis_chat_sidebar_width','540');"
                 "_csBreiteAnwenden(540,true)")
        time.sleep(0.2)
        check(f"[{thema}] 540px im breiten Fenster uebernommen",
              js(sock, "window.breite()") == 540, js(sock, "window.breite()"))
        cdp(sock, "Emulation.setDeviceMetricsOverride", width=800, height=900,
            deviceScaleFactor=1, mobile=False)
        js(sock, "window.dispatchEvent(new Event('resize'))")
        time.sleep(0.3)
        eng = js(sock, "window.breite()")
        check(f"[{thema}] schmales Fenster passt sie ein (Chat behaelt >=360)",
              800 - eng >= 360, f"Leiste {eng} von 800")
        check(f"[{thema}] der GEWUENSCHTE Wert bleibt gespeichert (540)",
              js(sock, "localStorage.getItem('jarvis_chat_sidebar_width')") == "540",
              js(sock, "localStorage.getItem('jarvis_chat_sidebar_width')"))
        cdp(sock, "Emulation.setDeviceMetricsOverride", width=1280, height=900,
            deviceScaleFactor=1, mobile=False)
        js(sock, "window.dispatchEvent(new Event('resize'))")
        time.sleep(0.3)
        check(f"[{thema}] breites Fenster holt die 540 zurueck",
              js(sock, "window.breite()") == 540, js(sock, "window.breite()"))

        # Screenshot zum Ansehen
        bild = cdp(sock, "Page.captureScreenshot", format="png")
        out = Path(f"/tmp/cs-resize-{thema}.png")
        out.write_bytes(base64.b64decode(bild["data"]))
        print(f"  →  Screenshot: {out}")

raeum()
print("\n" + "=" * 74)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
print("=" * 74)
sys.exit(0 if _fail == 0 else 1)
