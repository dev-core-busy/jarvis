#!/usr/bin/env python3
"""Optische Abnahme: "Als neue Confluence-Seite" im Wissens-Destillat.

Gemessen wird im ECHTEN Chrome gegen das ECHTE CSS, das ECHTE Markup und den
ECHTEN Renderer – jsdom rechnet kein Layout: Ueberlauf, Abschneiden und
Kontrast sieht nur ein Browser (Register, mehrfach bezahlt).

⚠ DIE PROBESEITE LIEGT NICHT UNTER frontend/ (Register): `test_theme_default`
laeuft ueber JEDE HTML-Datei dort und verlangt das Anti-Flacker-Skript – eine
Wegwerfseite dort liesse einen FREMDEN Waechter fehlschlagen. Sie liegt in
einem Wegwerf-Ordner mit Symlinks auf css/ und js/.

⚠ MARKUP UND CSS WERDEN AUS wissen.html GESCHNITTEN, nicht nachgebaut: eine
Probeseite, die ihr Markup selbst schreibt, prueft ihre eigene Annahme.
"""
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        print(f"  \033[32m✓\033[0m {name}")
        OK += 1
    else:
        print(f"  \033[31m✗\033[0m {name}" + (f"  [{info}]" if info else ""))
        FAIL += 1


def freier_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def leuchtdichte(rgb):
    def k(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (k(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def kontrast(vg, hg):
    a, b = leuchtdichte(vg), leuchtdichte(hg)
    hell, dunkel = max(a, b), min(a, b)
    return (hell + 0.05) / (dunkel + 0.05)


def rgb(s):
    m = re.findall(r"[\d.]+", s or "")
    return tuple(int(float(x)) for x in m[:3]) if len(m) >= 3 else (0, 0, 0)


HTML_QUELLE = (REPO / "frontend" / "wissen.html").read_text(encoding="utf-8")


def schneide(anfang: str, ende: str) -> str:
    a = HTML_QUELLE.find(anfang)
    b = HTML_QUELLE.find(ende, a + 1)
    if a < 0 or b < 0:
        print(f"\033[31mExit 2: Schnittmarke nicht gefunden ({anfang[:40]})\033[0m")
        sys.exit(2)
    return HTML_QUELLE[a:b]


STYLE = schneide("    <style>", "    </style>") + "    </style>"
CONTAINER = schneide('        <div class="wi-section" id="wi-sec-destillat">',
                     "        <!-- Dynamische Confluence-Einbindung.")

SEITE = """<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<link rel="stylesheet" href="css/theme.css"><link rel="stylesheet" href="css/style.css">
__STYLE__
</head><body>
<script>try{if(localStorage.getItem('jarvis_theme')!=='dark')document.body.classList.add('light');}catch(e){}</script>
<div class="wi-wrap" style="max-width:900px;margin:0 auto;padding:16px;">
__CONTAINER__
</div>
<script>
// fetch-Attrappe VOR den Modulen: der Container darf nicht ins echte Netz.
// Route ueber den PFAD, nie ueber die volle URL (Register).
window.fetch = function (url) {
  var pfad = String(url).split('?')[0];
  var d = { ok: true };
  if (pfad === '/api/wissen/destillat/lauf')
    d = { ok: true, markdown: '# Wartung der Anlage\\n\\nInhalt.', bloecke: 1 };
  if (pfad === '/api/wissen/confluence/pages')
    d = { ok: true, pages: [{ id: '1', title: 'Betriebshandbuch', parent: '' },
                            { id: '2', title: 'Kapitel 4 – Wartungsintervalle und Ersatzteile', parent: '1' }] };
  return Promise.resolve({ status: 200,
    json: function () { return Promise.resolve(d); },
    text: function () { return Promise.resolve(JSON.stringify(d)); } });
};
window.WissenPortal = { reloadPending: function () {},
  cfBaum: function (ps) {
    var byId = {}, roots = [];
    ps.forEach(function (p) { byId[String(p.id)] = { id: String(p.id), title: p.title, kids: [] }; });
    ps.forEach(function (p) { var n = byId[String(p.id)], par = p.parent ? String(p.parent) : '';
      if (par && byId[par]) byId[par].kids.push(n); else roots.push(n); });
    return roots; } };
</script>
<script src="js/icons.js"></script>
<script src="js/i18n.js"></script>
<script src="js/wissen_destillat.js"></script>
<script>
window.WissenDestillat.init({ scope: { groups: [{ id: 'technik', name: 'Technik', color: '#4f6ef7' }],
                                       folders: [], user: 'tester' }, token: 'tok' });
// Ueber den ECHTEN Bedienweg in den Ergebniszustand – ein von Hand
// aufgeklappter Kasten stellt den Regelfall nicht her (Register).
var ta = document.getElementById('wi-dest-text');
ta.value = 'Text'; ta.dispatchEvent(new Event('input'));
document.getElementById('wi-dest-run').click();
setTimeout(function () {
  window.WissenDestillat.confluence(true,
    [{ key: 'CTDP', name: 'Produktdokumentation' },
     { key: 'CTDE', name: 'Entwicklung' }]);
  document.getElementById('wi-dest-cf').click();
  var sel = document.getElementById('wi-dest-cfspace');
  sel.value = 'CTDP'; sel.dispatchEvent(new Event('change'));
  setTimeout(function () { window.__bereit = 1; }, 120);
}, 120);
</script></body></html>"""


def main():
    global FAIL
    arbeit = Path(tempfile.mkdtemp(prefix="destcf-"))
    (arbeit / "css").symlink_to(REPO / "frontend/css")
    (arbeit / "js").symlink_to(REPO / "frontend/js")
    (arbeit / "probe.html").write_text(
        SEITE.replace("__STYLE__", STYLE).replace("__CONTAINER__", CONTAINER),
        encoding="utf-8")
    port = freier_port()
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "-b", "127.0.0.1"],
                           cwd=arbeit, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    profil = Path(tempfile.mkdtemp(prefix="destcf-chrome-"))
    dport = freier_port()
    # ⚠ Chrome-Ausgabe NIE nach DEVNULL: ein verschluckter Startfehler wird zu
    # einer Fehldiagnose am eigenen Code (Register).
    chrome = subprocess.Popen([
        "google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
        f"--remote-debugging-port={dport}", f"--user-data-dir={profil}",
        "--remote-allow-origins=*", "--window-size=1000,1100", "about:blank"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    bilder = Path.home() / ".destcf-bilder"   # HOME (0700), nicht /tmp (1777)
    bilder.mkdir(exist_ok=True)
    try:
        for _ in range(40):
            try:
                seiten = json.load(urllib.request.urlopen(f"http://127.0.0.1:{dport}/json/list"))
                ziel = [s for s in seiten if s.get("type") == "page"]
                if ziel:
                    break
            except Exception:
                pass
            time.sleep(0.4)
        else:
            print("\033[31mExit 2: kein CDP-Ziel\033[0m")
            return 2

        import websockets.sync.client as wsc
        ws = wsc.connect(ziel[0]["webSocketDebuggerUrl"], max_size=40 * 1024 * 1024)
        n = [0]

        def ruf(m, p=None):
            n[0] += 1
            ws.send(json.dumps({"id": n[0], "method": m, "params": p or {}}))
            while True:
                a = json.loads(ws.recv())
                if a.get("id") == n[0]:
                    return a.get("result", {})

        def js(ausdruck):
            r = ruf("Runtime.evaluate", {"expression": ausdruck, "returnByValue": True,
                                         "awaitPromise": True})
            return r.get("result", {}).get("value")

        ruf("Page.enable")
        grund_je_thema = {}
        for thema, dunkel in (("dunkel", True), ("hell", False)):
            print(f"\n\033[1m{thema}\033[0m")
            # ⚠ Der Schluessel muss VOR das erste Skript der Seite – ueber
            # Runtime.evaluate auf about:blank erreicht er sie nie (anderer
            # Origin), und der Lauf maesse zweimal dasselbe Thema (Register).
            ruf("Page.addScriptToEvaluateOnNewDocument", {"source":
                f"try{{localStorage.setItem('jarvis_theme','{'dark' if dunkel else 'light'}')}}catch(e){{}}"})
            ruf("Page.navigate", {"url": f"http://127.0.0.1:{port}/probe.html"})
            for _ in range(50):
                time.sleep(0.2)
                if js("window.__bereit === 1"):
                    break
            else:
                check(f"{thema}: Seite wurde bereit", False, "Zeitlimit")
                continue

            # POSITIVKONTROLLE: ist ueberhaupt etwas da? Ohne sie waere jede
            # Ueberlauf-Pruefung darunter trivial wahr (Register).
            check("Positivkontrolle: der Zielkasten ist sichtbar",
                  js("(function(){var b=document.getElementById('wi-dest-cfbox');"
                     "return !!b && !b.hidden && b.getBoundingClientRect().height > 40;})()"))
            check("Positivkontrolle: das Bereichs-Pulldown traegt echte Eintraege",
                  js("document.querySelectorAll('#wi-dest-cfspace option').length") == 3)
            check("Positivkontrolle: der Seitenbaum ist geladen",
                  js("document.querySelectorAll('#wi-dest-cfparent option').length") == 3)

            grund_je_thema[thema] = js(
                "getComputedStyle(document.body).backgroundColor")

            # ── Layout ────────────────────────────────────────────────────
            check("kein waagerechter Ueberlauf der Seite",
                  js("document.documentElement.scrollWidth <= "
                     "document.documentElement.clientWidth + 1"),
                  str(js("document.documentElement.scrollWidth - "
                         "document.documentElement.clientWidth")))
            check("der Kasten laeuft nicht aus dem Container",
                  js("(function(){var b=document.getElementById('wi-dest-cfbox'),"
                     "s=document.getElementById('wi-sec-destillat');"
                     "return b.getBoundingClientRect().right <= s.getBoundingClientRect().right + 1;})()"))
            # ⚠ `.modal-card input`-Klasse der Nachbarn zieht Felder auf volle
            # Breite; hier zaehlt, dass das Titelfeld IM Kasten bleibt.
            check("das Titelfeld bleibt im Kasten",
                  js("(function(){var i=document.getElementById('wi-dest-cftitel'),"
                     "b=document.getElementById('wi-dest-cfbox');"
                     "var a=i.getBoundingClientRect(),c=b.getBoundingClientRect();"
                     "return a.left >= c.left - 1 && a.right <= c.right + 1;})()"),
                  js("JSON.stringify(document.getElementById('wi-dest-cftitel')"
                     ".getBoundingClientRect())"))
            check("die beiden Knoepfe stehen nebeneinander in EINER Zeile",
                  js("(function(){var a=document.getElementById('wi-dest-cfgo')"
                     ".getBoundingClientRect(),b=document.getElementById('wi-dest-cfcancel')"
                     ".getBoundingClientRect();return Math.abs(a.top-b.top) < 2 && a.right <= b.left + 1;})()"))
            check("der Knopf 'Als neue Confluence-Seite' steht in der Knopfzeile",
                  js("(function(){var k=document.getElementById('wi-dest-cf'),"
                     "z=document.querySelector('.wi-dest-actions');"
                     "return !k.hidden && k.getBoundingClientRect().height > 10"
                     " && k.getBoundingClientRect().right <= z.getBoundingClientRect().right + 1;})()"))
            # Der Seitenbaum muss seine Einrueckung SICHTBAR haben.
            check("die Unterseite ist im Pulldown sichtbar eingerueckt",
                  js("document.querySelectorAll('#wi-dest-cfparent option')[2]"
                     ".textContent.charCodeAt(0) === 160"))

            # ── Kontrast ──────────────────────────────────────────────────
            # Gemessen an den BERECHNETEN Farben, nicht am Bild: eine ruhende
            # Flaeche ist oft nicht deckend, und hellster gegen dunkelsten
            # Bildpunkt ist kein Kontrastwert (Register).
            hg = rgb(js("getComputedStyle(document.getElementById('wi-sec-destillat'))"
                        ".backgroundColor") or "")
            if hg == (0, 0, 0) and not dunkel:
                hg = rgb(js("getComputedStyle(document.body).backgroundColor"))
            for kennung, name in (("wi-dest-cfbox", "Hinweistext"),):
                vg = rgb(js(f"getComputedStyle(document.querySelector"
                            f"('#{kennung} .desc')).color"))
                k = kontrast(vg, hg)
                check(f"{name} lesbar (>= 4.5:1)", k >= 4.5, f"{k:.2f}:1 {vg} auf {hg}")
            vgl = rgb(js("getComputedStyle(document.querySelector"
                         "('label[for=\"wi-dest-cftitel\"]')).color"))
            kl = kontrast(vgl, hg)
            check(f"Feldbeschriftung lesbar (>= 4.5:1)", kl >= 4.5,
                  f"{kl:.2f}:1 {vgl} auf {hg}")

            # ── Schmales Fenster ──────────────────────────────────────────
            ruf("Emulation.setDeviceMetricsOverride",
                {"width": 520, "height": 900, "deviceScaleFactor": 1, "mobile": False})
            time.sleep(0.4)
            check("bei 520 px: der Kasten laeuft nicht ueber",
                  js("(function(){var b=document.getElementById('wi-dest-cfbox'),"
                     "s=document.getElementById('wi-sec-destillat');"
                     "return b.getBoundingClientRect().right <= s.getBoundingClientRect().right + 1;})()"))
            check("bei 520 px: die Knoepfe bleiben im Kasten",
                  js("(function(){var z=document.querySelector('.wi-dest-cfbox')||"
                     "document.getElementById('wi-dest-cfbox');"
                     "var k=document.getElementById('wi-dest-cfgo').getBoundingClientRect();"
                     "return k.right <= z.getBoundingClientRect().right + 1;})()"))
            ruf("Emulation.clearDeviceMetricsOverride")
            time.sleep(0.3)

            bild = ruf("Page.captureScreenshot", {"format": "png",
                                                  "captureBeyondViewport": True})
            ziel_datei = bilder / f"destillat-cf-{thema}.png"
            import base64
            ziel_datei.write_bytes(base64.b64decode(bild["data"]))
            print(f"    Screenshot: {ziel_datei}")

        # ⚠ POSITIVKONTROLLE DER MESSMETHODE: hell und dunkel muessen ZWEI
        # verschiedene Messungen gewesen sein. Ein identischer Wert ist zuerst
        # ein Verdacht gegen das Messwerkzeug (Register).
        check("hell und dunkel waren zwei verschiedene Messungen",
              grund_je_thema.get("hell") != grund_je_thema.get("dunkel"),
              str(grund_je_thema))

        fehler = js("JSON.stringify(window.__fehler || null)")
        check("keine JS-Fehler auf der Seite", fehler in (None, "null"), str(fehler))
    finally:
        try:
            chrome.kill()
        except Exception:
            pass
        srv.kill()

    print(f"\n\033[1mErgebnis: {OK}/{OK + FAIL}\033[0m")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
