#!/usr/bin/env python3
"""Optische Abnahme: Suchfeld in "Mein Wissen" (/wissen), hell UND dunkel.

jsdom rechnet KEIN Layout: ob das Feld in seinem Kasten bleibt, ob eine lange
Dateizeile daneben nichts aus dem Bild schiebt und ob der Hinweistext ueberhaupt
lesbar ist (Kontrast), beantwortet nur ein echter Browser.

Gemessen wird die EIGENSCHAFT, nicht die CSS-Zeile:
  * das Suchfeld hat eine echte Groesse und liegt im Abschnitt,
  * kein waagerechter Ueberlauf – auch nicht mit einem unteilbar langen Namen,
  * getippt wird mit ECHTEN Tastaturereignissen (Input.dispatchKeyEvent):
    ein synthetisches `input` aus JS umgeht die Kette, um die es hier geht,
  * die Liste schrumpft sichtbar, und die Leermeldung ist zu lesen,
  * Kontrast des Hinweistextes >= 4.5:1 in BEIDEN Themen.

Die Probeseite liegt in einem WEGWERF-Ordner, nicht unter frontend/:
`test_theme_default.js` laeuft ueber jede HTML-Datei dort und wuerde sie als
Fehlalarm melden (Register). Aufruf: ./venv/bin/python tests/live_wissen_suche_ui_dev.py
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


def misch(vg, hg):
    """Halbdurchsichtige Vordergrundfarbe ueber den gemessenen Grund legen -
    als deckend gelesen kaeme ein Traumwert heraus (Register)."""
    s = (vg or "").strip()
    m = re.match(r"rgba\(([^)]+)\)", s)
    if not m:
        return farbe(vg)
    t = [float(x) for x in m.group(1).split(",")]
    if len(t) < 4:
        return farbe(vg)
    a = t[3]
    h = farbe(hg)
    return tuple(round(t[i] * a + h[i] * (1 - a)) for i in range(3))


# ── Die ECHTE Seite und die ECHTEN Skripte ──────────────────────────────────
HTML = (ROOT / "frontend" / "wissen.html").read_text(encoding="utf-8")

# Die Attrappe der Erweiterungs-API steht VOR den echten Skripten: `wissen.js`
# leitet ohne Sitzungstoken sofort aufs Portal um, und danach misst man das
# Verzeichnis-Listing statt der Seite (Register).
ATTRAPPE = """
<script>
(function () {
  try { localStorage.setItem('jarvis_token', 'probe-token'); } catch (e) {}
  document.cookie = 'jarvis_wissen_gfilter_off=;path=/';
  var GRUPPEN = [
    { id: 'allgemein', name: 'community', color: '#22c55e', folders: ['data/rag/community'] },
    { id: 'technik', name: 'Handbuecher', color: '#8b5cf6', folders: [] }
  ];
  var DATEIEN = [
    { path: 'data/rag/community/Vertrieb/Preisliste.xlsx', name: 'Preisliste.xlsx',
      folder: 'community/Vertrieb', groups: [GRUPPEN[0]] },
    { path: 'mnt/rag/share_1/OneNote-Jasmin/Anleitung SAP.one', name: 'Anleitung SAP.one',
      folder: 'share_1/OneNote-Jasmin', groups: [GRUPPEN[1]] },
    { path: 'data/rag/community/Notizen/urlaub.md', name: 'urlaub.md',
      folder: 'community/Notizen', groups: [GRUPPEN[0]] },
    // Ein unteilbar langer Name: genau daran sprengt ein Layout, das
    // `min-width: 0` vergisst.
    { path: 'data/rag/community/Lang/' + 'Jahresabschlusspruefungsberichtsanlage_2026_Endfassung_final.xlsx',
      name: 'Jahresabschlusspruefungsberichtsanlage_2026_Endfassung_final.xlsx',
      folder: 'community/Lang/Unterordner_mit_sehr_langem_Namen_fuer_die_Messung',
      groups: [GRUPPEN[0]] }
  ];
  function A(k) { return Promise.resolve({ ok: true, status: 200,
                    json: function () { return Promise.resolve(k); } }); }
  window.fetch = function (url) {
    var p = String(url).split('?')[0];
    if (p === '/api/wissen/scope') return A({ ok: true, user: 'anna', is_editor: false,
        is_admin: false, groups: GRUPPEN, folders: [
          { path: 'data/rag/community', name: 'community', root: 'data/rag/community', depth: 0 }] });
    if (p === '/api/wissen/files') return A({ ok: true, files: DATEIEN });
    if (p === '/api/knowledge/content_search') return A({ ok: true, files: [] });
    return A({ ok: true, pending: [], spaces: [], status: 'ok' });
  };
  window.confirm = function () { return false; };
})();
</script>
"""

WEG = Path(tempfile.mkdtemp(prefix="wissuche-", dir=str(Path.home())))
os.chmod(WEG, 0o755)
for teil in ("css", "js"):
    try:
        (WEG / teil).symlink_to(ROOT / "frontend" / teil)
    except FileExistsError:
        pass
# /static/js/... -> js/...   (die echte Seite bindet die echten Pfade ein)
(WEG / "static").mkdir(exist_ok=True)
for teil in ("css", "js"):
    try:
        (WEG / "static" / teil).symlink_to(ROOT / "frontend" / teil)
    except FileExistsError:
        pass
(WEG / "probe.html").write_text(HTML.replace("<body", ATTRAPPE + "<body", 1), encoding="utf-8")

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

PROFIL = tempfile.mkdtemp(prefix="chrome-wis-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()

chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1280,1000",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def cdp_ziel():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as a:
                # ⚠ NUR type=="page": /json/list liefert auch die eingebauten
                # Erweiterungen - wer blind [0] nimmt, misst gar nichts.
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


def raeum():
    for pr in (chrome, srv):
        try:
            pr.kill()
        except Exception:  # noqa: BLE001
            pass
    shutil.rmtree(PROFIL, ignore_errors=True)
    shutil.rmtree(WEG, ignore_errors=True)


print("=" * 74)
print("Optische Abnahme: Suche in 'Mein Wissen' (/wissen)")
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


def tippe(sock, text):
    """Echte Tastaturereignisse - ein aus JS gefeuertes `input` umginge die
    Kette, um die es geht."""
    js(sock, "document.getElementById('wi-files-q').focus()")
    for z in text:
        cdp(sock, "Input.dispatchKeyEvent", type="keyDown", text=z)
        cdp(sock, "Input.dispatchKeyEvent", type="keyUp")
    time.sleep(0.25)


def laden(sock, thema):
    cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
        source=("try{localStorage.setItem('jarvis_theme',%r);}catch(e){}" % thema))
    cdp(sock, "Page.navigate", url=f"{BASIS}/probe.html")
    for _ in range(80):
        time.sleep(0.15)
        if js(sock, "!!document.querySelector('#wi-files-list .wi-item')"):
            break
    # Abschnitt "Mein Wissen" aufklappen, falls zugeklappt - in einem
    # display:none-Vorfahren ist JEDES Rechteck 0 und jede Messung trivial.
    js(sock, """(function(){var s=document.getElementById('wi-sec-files');
        if(s&&s.classList.contains('collapsed')){var h=s.querySelector('h2');if(h)h.click();}
        return true;})()""")
    time.sleep(0.3)


def schuss(sock, name):
    r = cdp(sock, "Page.captureScreenshot", format="png")
    p = Path.home() / f"wissuche-{name}.png"
    import base64
    p.write_bytes(base64.b64decode(r["data"]))
    return p


try:
    with connect(ws_url, max_size=60 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        cdp(sock, "Runtime.enable")

        for thema in ("dark", "light"):
            print(f"\n--- Thema: {thema} ---")
            laden(sock, thema)

            hell = js(sock, "document.body.classList.contains('light')")
            check(f"Thema {thema} wirklich aktiv (Positivkontrolle)",
                  hell == (thema == "light"), f"body.light={hell}")

            n = js(sock, "document.querySelectorAll('#wi-files-list .wi-item').length")
            check("vier Dateizeilen gezeichnet", n == 4, f"gezeichnet={n}")
            if n != 4:
                continue

            # ── Das Feld hat eine echte Groesse ───────────────────────────
            box = js(sock, """(function(){var e=document.getElementById('wi-files-q');
                if(!e)return null;var r=e.getBoundingClientRect();
                return {w:Math.round(r.width),h:Math.round(r.height),
                        t:Math.round(r.top),l:Math.round(r.left)};})()""")
            check("das Suchfeld ist sichtbar und hat eine Groesse",
                  bool(box) and box["w"] > 200 and box["h"] > 20, str(box))

            # Es liegt im Abschnitt und VOR der Dateiliste.
            lage = js(sock, """(function(){
                var f=document.getElementById('wi-files-q').getBoundingClientRect();
                var l=document.getElementById('wi-files-list').getBoundingClientRect();
                var s=document.getElementById('wi-sec-files').getBoundingClientRect();
                return {feldTop:Math.round(f.top),listeTop:Math.round(l.top),
                        secLeft:Math.round(s.left),secRight:Math.round(s.right),
                        feldLeft:Math.round(f.left),feldRight:Math.round(f.right)};})()""")
            check("das Feld steht ueber der Dateiliste",
                  lage["feldTop"] < lage["listeTop"], str(lage))
            check("das Feld bleibt im Abschnitt (kein Ueberstand)",
                  lage["feldLeft"] >= lage["secLeft"] - 2
                  and lage["feldRight"] <= lage["secRight"] + 2, str(lage))

            # ── Kein waagerechter Ueberlauf, auch mit langem Namen ────────
            ueber = js(sock, "document.documentElement.scrollWidth - document.documentElement.clientWidth")
            check("kein waagerechter Ueberlauf der Seite", ueber <= 1, f"Ueberlauf={ueber}px")

            # ── Kontrast des Hinweistextes ───────────────────────────────
            k = js(sock, """(function(){var e=document.getElementById('wi-files-search-hint');
                var s=getComputedStyle(e);var p=e.parentElement,bg='';
                while(p){var b=getComputedStyle(p).backgroundColor;
                  if(b&&b!=='rgba(0, 0, 0, 0)'&&b!=='transparent'){bg=b;break;}p=p.parentElement;}
                return {vg:s.color,bg:bg||getComputedStyle(document.body).backgroundColor};})()""")
            grund = farbe(k["bg"])
            v = misch(k["vg"], k["bg"])
            kw = kontrast(v, grund)
            check(f"Hinweistext lesbar (Kontrast {kw:.2f}:1 >= 4.5)", kw >= 4.5,
                  f"vg={k['vg']} bg={k['bg']}")

            # ── ECHTES Tippen filtert sichtbar ───────────────────────────
            tippe(sock, "urlaub")
            n2 = js(sock, "document.querySelectorAll('#wi-files-list .wi-item').length")
            check("echtes Tippen filtert die Liste auf eine Zeile", n2 == 1, f"Zeilen={n2}")
            zahl = js(sock, "(document.getElementById('wi-files-count')||{}).textContent||''")
            check("der Zaehler nennt die gefilterte Zahl", "1" in zahl and "4" in zahl, zahl)

            # Zum Abschnitt scrollen - ein Screenshot vom Seitenanfang zeigt
            # die Liste gar nicht, und dann sieht man den Zustand nicht, um den
            # es geht.
            js(sock, "document.getElementById('wi-sec-files').scrollIntoView(true)")
            time.sleep(0.3)
            schuss(sock, f"{thema}-gefiltert")

            # ── Leermeldung ist zu lesen ─────────────────────────────────
            js(sock, "document.getElementById('wi-files-q').value=''")
            tippe(sock, "gibtesnicht")
            leer = js(sock, """(function(){var e=document.querySelector('#wi-files-list .wi-empty');
                if(!e)return null;var r=e.getBoundingClientRect();
                return {txt:e.textContent.trim(),w:Math.round(r.width),h:Math.round(r.height)};})()""")
            check("die Leermeldung ist sichtbar",
                  bool(leer) and leer["h"] > 5 and leer["w"] > 50, str(leer))
            check("sie nennt den Suchbegriff",
                  bool(leer) and "gibtesnicht" in leer["txt"], leer and leer["txt"])

            js(sock, "document.getElementById('wi-sec-files').scrollIntoView(true)")
            time.sleep(0.3)
            p = schuss(sock, f"{thema}-leer")
            print(f"  ->   Screenshot: {p}")

            # ── Zuruecksetzen und die lange Zeile ansehen ────────────────
            js(sock, "document.getElementById('wi-files-q').value=''")
            tippe(sock, "j")   # loest input aus, Feld enthaelt 'j'
            js(sock, """(function(){var e=document.getElementById('wi-files-q');
                e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));})()""")
            time.sleep(0.2)
            lang = js(sock, """(function(){
                var rows=[].slice.call(document.querySelectorAll('#wi-files-list .wi-item'));
                var r=rows.filter(function(x){return /Jahresabschluss/.test(x.textContent);})[0];
                if(!r)return null;var rr=r.getBoundingClientRect();
                var b=r.querySelector('.wi-file-del').getBoundingClientRect();
                return {rowRight:Math.round(rr.right),btnRight:Math.round(b.right),
                        btnW:Math.round(b.width)};})()""")
            check("der Muelleimer bleibt bei langem Namen in der Zeile",
                  bool(lang) and lang["btnRight"] <= lang["rowRight"] + 2 and lang["btnW"] > 10,
                  str(lang))

    print("\n" + "=" * 74)
    print(f"ERGEBNIS: {_ok} OK, {_fail} FAIL")
    print("=" * 74)
finally:
    raeum()

sys.exit(1 if _fail else 0)
