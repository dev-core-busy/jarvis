#!/usr/bin/env python3
"""Optische Abnahme: Auswahlmodus der Verlaufsleiste in /chat (hell UND dunkel).

jsdom rechnet KEIN Layout – ob die neue Werkzeugzeile ("Alle", "Löschen (n)",
"Abbrechen") in eine 180px schmale Leiste passt, ob sie ueberlaeuft, ob die
Kaestchen die Chatnamen verdecken und ob der Loeschknopf ueberhaupt lesbar ist,
beantwortet nur ein echter Browser. Der jsdom-Waechter
(tests/test_chat_mehrfach_loeschen.js) misst das VERHALTEN, diese Abnahme das
AUSSEHEN – beides zusammen, keines statt des anderen.

Gemessen wird die EIGENSCHAFT, nicht die CSS-Zeile:
  * kein waagerechter Ueberlauf der Leiste, in KEINER der beiden Breiten,
  * jedes Bedienelement liegt vollstaendig INNERHALB der Leiste,
  * die Bedienelemente ueberlappen einander nicht,
  * das Kaestchen verdeckt den Chatnamen nicht,
  * der Text des Loeschknopfs ist lesbar – gemessen an den WIRKLICHEN PIXELN
    des Screenshots, nicht an einer gerechneten Farbe (halbtransparente
    Flaechen liessen sich sonst nur schaetzen).

⚠ 180px ist die Mindestbreite aus chat.js (_CS_W_MIN) – genau dort quetscht
sich der Kopf schon, und genau dort muss die neue Zeile umbrechen statt
ueberzulaufen (Register: eine Flex-Leiste ohne flex-wrap laeuft ueber, und
gemeldet war eine, gemessen waren es sieben).

⚠ Die Bilder landen im HOME (0700), nicht in einem festen /tmp-Pfad: der ist
1777, und ein Lauf unter fremdem Benutzer stirbt dort NACH allen Pruefungen –
also ohne Bilanzzeile, von "nicht gelaufen" nicht zu unterscheiden.

Aufruf: ./venv/bin/python tests/live_chat_sammel_ui_dev.py
"""
import base64
import io
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
    """CSS-Farbe -> (r,g,b), oder None, wenn sie NICHT DECKEND ist.

    ⚠ Chrome liefert `color-mix(...)` als `color(srgb a b c)` mit Anteilen
    0..1 – als 0..255 gelesen ergaebe das fast Schwarz (Register).
    ⚠ Halbtransparent (`rgba(...,0.4)`) gibt None zurueck: darueber laesst
    sich ohne den Untergrund nichts aussagen, und eine geratene Zahl waere
    schlimmer als keine.
    """
    s = (s or "").strip()
    m = re.match(r"color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*(?:/\s*([\d.]+))?\s*\)", s)
    if m:
        if m.group(4) is not None and float(m.group(4)) < 0.999:
            return None
        return tuple(round(float(m.group(i)) * 255) for i in (1, 2, 3))
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        teile = [float(x) for x in m.group(1).replace("/", " ").replace(",", " ").split()]
        if len(teile) >= 4 and teile[3] < 0.999:
            return None
        return tuple(round(x) for x in teile[:3])
    return None


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


NAMEN = ("_renderSidebar", "_renderTools", "_selSetze", "_selModus", "_selAlle")
TEILE = [schneide(n) for n in NAMEN]
if not all(TEILE):
    fehlt = [n for n, t in zip(NAMEN, TEILE) if not t]
    print(f"ABBRUCH: Schnitt unvollstaendig, fehlt: {fehlt}")
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


LEISTE = markup("chat.html", '<aside id="chat-sidebar"', "</aside>")

# ⚠ Modulvariablen fallen aus jedem Funktions-Schnitt heraus (Register) – ohne
# diese Deklarationen stirbt der Lauf an einem nackten ReferenceError, und das
# sieht wie ein Codefehler aus, ist aber der Messaufbau.
PROLOG = """
var _sessions = [], _activeSid = null, _selMode = false, _selIds = new Set();
var $ = function (id) { return document.getElementById(id); };
function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
function _switchSession(id) {}
function _renameSession(s) {}
function _openSessionPrompt(s) {}
function _deleteSession(s) {}
"""

SEITE = """<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<link rel="stylesheet" href="css/theme.css">
<link rel="stylesheet" href="css/chat.css">
</head><body>
<div id="chat-screen" class="chat-screen">
__LEISTE__
<div id="chat-main" class="chat-main"><div style="padding:16px">Chatbereich</div></div>
</div>
<script src="js/icons.js"></script>
<script src="js/i18n.js"></script>
<script>
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
try {
__PROLOG__
__TEILE__
_sessions = [
  { id: 'aaa111', title: 'Angebot Musterfirma GmbH – Rueckfragen' },
  { id: 'bbb222', title: 'Zweiter Chat' },
  { id: 'ccc333', title: 'Dritter Chat' }
];
_activeSid = 'aaa111';
_renderSidebar();
} catch (e) { window.__fehler += 'WURF: ' + e.message; }
window.__modus = function (an) { _selModus(an); };
window.__alle  = function (an) { _selAlle(an); };
window.__breite = function (px) {
  document.getElementById('chat-screen').style.setProperty('--cs-w', px + 'px');
};
window.__mass = function () {
  var l = document.getElementById('chat-sidebar');
  var lr = l.getBoundingClientRect();
  var teile = ['cs-all-wrap', 'cs-seldel', 'cs-selmode'].map(function (id) {
    var e = document.getElementById(id);
    var r = e.getBoundingClientRect();
    return { id: id, x: r.x, y: r.y, w: r.width, h: r.height, r: r.right, b: r.bottom,
             sichtbar: !e.hidden && r.width > 0 && r.height > 0 };
  });
  var zeilen = Array.from(document.querySelectorAll('#cs-list .cs-item')).map(function (z) {
    var cb = z.querySelector('.cs-check'), t = z.querySelector('.cs-title');
    var rc = cb ? cb.getBoundingClientRect() : null, rt = t.getBoundingClientRect();
    return { cb: rc ? { x: rc.x, w: rc.width, h: rc.height, r: rc.right } : null,
             t: { x: rt.x, w: rt.width, r: rt.right } };
  });
  return { leiste: { x: lr.x, r: lr.right, w: lr.width },
           ueberlauf: l.scrollWidth - l.clientWidth,
           teile: teile, zeilen: zeilen,
           knopfText: document.getElementById('cs-seldel').textContent.trim() };
};
</script></body></html>"""

# ⚠ Die Probeseite liegt NICHT unter frontend/: `test_theme_default.js` laeuft
# ueber JEDE HTML-Datei dort und verlangt das Anti-Flacker-Skript – eine
# Probeseite waere ein Fehlalarm in einem fremden Waechter. Sie steht in einem
# Wegwerf-Ordner, css/ und js/ als Symlink daneben.
WEG = Path(tempfile.mkdtemp(prefix="chatsammel-", dir=str(Path.home())))
os.chmod(WEG, 0o755)
for teil in ("css", "js"):
    try:
        (WEG / teil).symlink_to(ROOT / "frontend" / teil)
    except FileExistsError:
        pass
(WEG / "probe.html").write_text(
    SEITE.replace("__LEISTE__", LEISTE).replace("__PROLOG__", PROLOG)
         .replace("__TEILE__", "\n".join(TEILE)), encoding="utf-8")

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
BASIS = f"http://127.0.0.1:{HTTP_PORT}"

PROFIL = tempfile.mkdtemp(prefix="chrome-chsam-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()

# ⚠ --remote-allow-origins ist Pflicht (Chrome >= 111 lehnt CDP sonst ab, und
# der Grund steht NUR im Chrome-Log). Die Ausgabe wird NICHT verschluckt.
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1280,900",
     "--force-device-scale-factor=1", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def cdp_ziel():
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


def raeum():
    for p in (chrome, srv):
        try:
            p.kill()
        except Exception:  # noqa: BLE001
            pass
    shutil.rmtree(PROFIL, ignore_errors=True)
    shutil.rmtree(WEG, ignore_errors=True)


print("=" * 74)
print("Optische Abnahme: Auswahlmodus der Verlaufsleiste (/chat)")
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
    from PIL import Image
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: python-websockets oder Pillow fehlt ({e}).")
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


def bild(sock):
    d = cdp(sock, "Page.captureScreenshot", format="png")
    return Image.open(io.BytesIO(base64.b64decode(d["data"]))).convert("RGB")


def laden(sock, thema):
    cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
        source=("try{localStorage.setItem('jarvis_theme',%r);"
                "localStorage.setItem('jarvis_lang','de');"
                "localStorage.removeItem('jarvis_chat_sidebar_width');"
                "localStorage.removeItem('jarvis_chat_sidebar_collapsed');}catch(e){}"
                % thema))
    cdp(sock, "Page.navigate", url=f"{BASIS}/probe.html")
    for _ in range(60):
        if js(sock, "document.readyState") == "complete":
            break
        time.sleep(0.2)
    js(sock, "document.body.classList.toggle('light', %s)"
       % ("true" if thema == "light" else "false"))
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

        # ── ⚠ POSITIVKONTROLLE DES MESSAUFBAUS – bricht HART ab ────────────
        # Ohne geladenes CSS waere jede Layout-Messung darunter wertlos, und
        # ein 404 auf ein Stylesheet ist still.
        if js(sock, "getComputedStyle(document.getElementById('chat-screen')).display") != "flex":
            print("  ABBRUCH: chat.css nicht geladen – die Messung waere wertlos.")
            raeum()
            sys.exit(2)
        if js(sock, "document.querySelectorAll('#cs-list .cs-item').length") != 3:
            print("  ABBRUCH: die Verlaufsleiste wurde nicht gezeichnet.")
            raeum()
            sys.exit(2)
        check(f"[{thema}] CSS geladen und drei Chats gezeichnet (Positivkontrolle)", True)

        for breite in (240, 180):
            js(sock, f"window.__breite({breite})")
            js(sock, "window.__modus(true); window.__alle(true)")
            time.sleep(0.25)
            m = js(sock, "window.__mass()")
            vor = f"[{thema}/{breite}px]"

            check(f"{vor} alle drei Bedienelemente sind sichtbar",
                  all(t["sichtbar"] for t in m["teile"]),
                  json.dumps([t["id"] for t in m["teile"] if not t["sichtbar"]]))
            check(f"{vor} ⚠ kein waagerechter Ueberlauf der Leiste",
                  m["ueberlauf"] <= 1, f"scrollWidth-clientWidth = {m['ueberlauf']}")
            draussen = [t["id"] for t in m["teile"]
                        if t["x"] < m["leiste"]["x"] - 0.5 or t["r"] > m["leiste"]["r"] + 0.5]
            check(f"{vor} ⚠ jedes Bedienelement liegt INNERHALB der Leiste",
                  not draussen, json.dumps(draussen) + " " + json.dumps(m["teile"]))

            # Ueberlappung: zwei Kaesten ueberdecken sich, wenn sie sich in
            # BEIDEN Achsen schneiden (nebeneinander oder untereinander ist ok).
            ueber = []
            for i in range(len(m["teile"])):
                for j in range(i + 1, len(m["teile"])):
                    a, b = m["teile"][i], m["teile"][j]
                    if (a["x"] < b["r"] - 0.5 and b["x"] < a["r"] - 0.5
                            and a["y"] < b["b"] - 0.5 and b["y"] < a["b"] - 0.5):
                        ueber.append(a["id"] + "/" + b["id"])
            check(f"{vor} die Bedienelemente ueberlappen einander nicht",
                  not ueber, json.dumps(ueber))

            check(f"{vor} jede Zeile hat ein sichtbares Kaestchen",
                  all(z["cb"] and z["cb"]["w"] >= 10 and z["cb"]["h"] >= 10
                      for z in m["zeilen"]), json.dumps(m["zeilen"][0]))
            check(f"{vor} das Kaestchen verdeckt den Chatnamen nicht",
                  all(z["cb"] and z["t"]["x"] >= z["cb"]["r"] - 0.5 for z in m["zeilen"]),
                  json.dumps(m["zeilen"][0]))
            check(f"{vor} fuer den Chatnamen bleibt Platz (>= 60px)",
                  all(z["t"]["w"] >= 60 for z in m["zeilen"]),
                  json.dumps([z["t"]["w"] for z in m["zeilen"]]))
            check(f"{vor} die Zahl der Auswahl steht im Loeschknopf",
                  "3" in (m["knopfText"] or ""), repr(m["knopfText"]))

            # ── Lesbarkeit an den WIRKLICHEN Pixeln ────────────────────────
            # Gerechnete Farben helfen hier nicht: die Leiste ist
            # halbtransparent (--bg-glass), der Knopf hat ruhend gar keine
            # eigene Flaeche. ⚠ BEIDE Zustaende messen: ueberfahren dreht sich
            # das Farbpaar um (weiss auf Rot), und Signalrot liegt genau dort
            # gern unter der Textgrenze.
            k = [t for t in m["teile"] if t["id"] == "cs-seldel"][0]
            kasten = (max(0, int(k["x"])), max(0, int(k["y"])), int(k["r"]), int(k["b"]))

            def lesbar(zustand, sock=sock, kasten=kasten, vor=vor):
                """Kontrast SCHRIFT gegen ihre FLAECHE – nicht hellster gegen
                dunkelsten Bildpunkt.

                ⚠ Der erste Anlauf nahm max/min ueber den ganzen Knopf und
                meldete fuer weisse Schrift auf Signalrot 18,53:1 statt der
                wirklichen 3,70 – ein einziger dunkler Kantenpunkt genuegte.
                Die Sonde haette damit genau den Fall durchgewunken, fuer den
                sie gebaut ist. Gezaehlt werden deshalb nur Farben mit
                nennenswertem ANTEIL (>= 1 %): die haeufigste ist die Flaeche,
                die am weitesten davon entfernte die Schrift.
                """
                im = bild(sock)
                aus = im.crop((kasten[0], kasten[1], min(im.width, kasten[2]),
                               min(im.height, kasten[3])))
                punkte = list(aus.getdata())
                zaehler = {}
                for f in punkte:
                    zaehler[f] = zaehler.get(f, 0) + 1
                schwelle = max(1, len(punkte) // 100)
                haeufig = [f for f, n in zaehler.items() if n >= schwelle]
                if len(haeufig) < 2:
                    check(f"{vor} Loeschknopf {zustand}: zwei Farben messbar", False,
                          f"nur {len(haeufig)} Farbe(n) mit >=1 %")
                    return im
                flaeche = max(haeufig, key=lambda f: zaehler[f])
                schrift = max(haeufig, key=lambda f: abs(leucht(f) - leucht(flaeche)))
                kk = kontrast(schrift, flaeche)
                check(f"{vor} Loeschknopf {zustand} lesbar "
                      f"(Kontrast {kk:.2f}:1, Textgrenze 4.5:1)",
                      kk >= 4.5, f"Schrift {schrift} auf Flaeche {flaeche}")
                return im

            flaeche_ruht = js(sock, "getComputedStyle(document.getElementById('cs-seldel')).backgroundColor")
            im = lesbar("ruhend")

            # ⚠ DER HOVER-ZUSTAND IST AM BILD NICHT MESSBAR. Nachgewiesen und
            # nicht vermutet: nach dem Mausereignis matcht `:hover`, und die
            # berechnete Flaeche WECHSELT – der Screenshot zeigt trotzdem Pixel
            # fuer Pixel denselben Knopf wie ruhend (beide Laeufe exakt 4,92:1).
            # `Page.captureScreenshot` rendert in --headless=new ohne den
            # Zeigerzustand. Eine Pixelmessung waere hier also eine Sonde, die
            # sich selbst misst und den gefaehrlichsten Fall (weisse Schrift auf
            # Signalrot) durchwinkt.
            # Ueberfahren traegt der Knopf eine DECKENDE Flaeche – dort sind die
            # berechneten Farben exakt, und genau die werden verglichen.
            cdp(sock, "Input.dispatchMouseEvent", type="mouseMoved",
                x=(kasten[0] + kasten[2]) / 2, y=(kasten[1] + kasten[3]) / 2, button="none")
            time.sleep(0.25)
            hv = js(sock, """(function(){var e=document.getElementById('cs-seldel');
                var c=getComputedStyle(e);return {hover:e.matches(':hover'),
                bg:c.backgroundColor, fg:c.color};})()""")
            # Positivkontrolle: ohne hergestellten Zustand waere die Messung blind.
            if not hv["hover"] or hv["bg"] == flaeche_ruht:
                print(f"  ABBRUCH: Hover-Zustand nicht hergestellt "
                      f"({flaeche_ruht} -> {hv['bg']}) – die Messung waere blind.")
                raeum()
                sys.exit(2)
            bg, fg = farbe(hv["bg"]), farbe(hv["fg"])
            if bg is None:
                print(f"  ABBRUCH: Hover-Flaeche ist nicht deckend ({hv['bg']}) – "
                      "berechnete Farben taugen dann nicht.")
                raeum()
                sys.exit(2)
            kh = kontrast(fg, bg)
            check(f"{vor} Loeschknopf ueberfahren lesbar "
                  f"(Kontrast {kh:.2f}:1, Textgrenze 4.5:1)", kh >= 4.5,
                  f"Schrift {hv['fg']} auf Flaeche {hv['bg']}")
            cdp(sock, "Input.dispatchMouseEvent", type="mouseMoved", x=900, y=700,
                button="none")
            time.sleep(0.2)

            if breite == 180:
                aus2 = im.crop((0, 0, 320, 400))
                ziel = Path.home() / f"chat-sammel-{thema}.png"
                aus2.save(ziel)
                print(f"  →  Ausschnitt: {ziel}")

            js(sock, "window.__modus(false)")
            time.sleep(0.15)
            m2 = js(sock, "window.__mass()")
            check(f"{vor} zurueck im Normalzustand: kein Ueberlauf, keine Kaestchen",
                  m2["ueberlauf"] <= 1 and all(z["cb"] is None for z in m2["zeilen"]),
                  f"ueberlauf={m2['ueberlauf']}")

raeum()
print("\n" + "=" * 74)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
print("=" * 74)
sys.exit(0 if _fail == 0 else 1)
