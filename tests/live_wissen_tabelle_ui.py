#!/usr/bin/env python3
"""Optische Abnahme: "Mein Wissen" als Tabelle + Maximieren (/wissen), hell UND dunkel.

jsdom rechnet KEIN Layout: ob die vier Spaltenkoepfe in einer Zeile stehen, ob
eine lange Zeile die Tabelle sprengt, ob der Knopf ⛶
klickbar ist und ob "maximiert" die Seite wirklich breiter macht, beantwortet
nur ein echter Browser.

Gemessen wird die EIGENSCHAFT:
  * vier Spaltenkoepfe, sichtbar, auf EINER Hoehe, links nach rechts
  * die Tabelle bleibt im Abschnitt, kein waagerechter Ueberlauf der SEITE –
    auch mit unteilbar langem Namen und bei 520 px Fensterbreite
  * die Groesse steht rechtsbuendig
  * Kontrast der Kopfzeile >= 4.5:1 in BEIDEN Themen
  * der Knopf ⛶ sitzt hinter "Angemeldet als" ganz oben in der Seite (weder
    in der Titelleiste noch in "Mein Wissen"), ein ECHTER Mausklick macht
    ALLE Abschnitte fensterbreit, ein zweiter deckelt wieder auf 900 px;
    beide Zustaende ueberleben ein Neuladen (je Browser gemerkt)
  * ein ECHTER Klick auf einen Spaltenkopf sortiert

Probeseite in einem WEGWERF-Ordner unter HOME (Register: nicht unter
frontend/, nicht in festes /tmp). Aufruf: python3 tests/live_wissen_tabelle_ui.py
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

ROOT = Path(__file__).resolve().parent.parent

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
    """Halbdurchsichtige Farbe ueber den Grund legen – als deckend gelesen
    kaeme ein Traumwert heraus (Register)."""
    m = re.match(r"rgba\(([^)]+)\)", (vg or "").strip())
    if not m:
        return farbe(vg)
    t = [float(x) for x in m.group(1).split(",")]
    if len(t) < 4:
        return farbe(vg)
    h = farbe(hg)
    return tuple(round(t[i] * t[3] + h[i] * (1 - t[3])) for i in range(3))


HTML = (ROOT / "frontend" / "wissen.html").read_text(encoding="utf-8")

ATTRAPPE = """
<script>
(function () {
  try { localStorage.setItem('jarvis_token', 'probe-token'); localStorage.setItem('jarvis_lang', 'de'); } catch (e) {}
  document.cookie = 'jarvis_wissen_gfilter_off=;path=/';
  var G = [
    { id: 'allgemein', name: 'community', color: '#22c55e', folders: ['data/rag/community'] },
    { id: 'technik', name: 'Handbuecher_und_Anleitungen', color: '#8b5cf6', folders: [] }
  ];
  var D = [
    { path: 'data/rag/community/Vertrieb/Preisliste.xlsx', name: 'Preisliste.xlsx',
      folder: 'community/Vertrieb', groups: [G[0]], size: 48213 },
    { path: 'mnt/rag/share_1/OneNote-Ablage/Anleitungen SAP.one', name: 'Anleitungen SAP.one',
      folder: 'share_1/OneNote-Muster/0039_Beispiel', groups: [G[1], G[0]], size: 46509328 },
    { path: 'data/rag/community/Notizen/urlaub.md', name: 'urlaub.md',
      folder: 'community/Notizen', groups: [G[0]], size: 812 },
    { path: 'mnt/rag/share_3/x/offline.pdf', name: 'offline.pdf',
      folder: 'share_3/x', groups: [G[1]], size: null },
    { path: 'data/rag/community/Lang/Jahresabschlusspruefungsberichtsanlage_2026_Endfassung_final.xlsx',
      name: 'Jahresabschlusspruefungsberichtsanlage_2026_Endfassung_final.xlsx',
      folder: 'community/Lang/Unterordner_mit_sehr_langem_Namen_fuer_die_Messung',
      groups: [G[0]], size: 1234567 }
  ];
  function A(k) { return Promise.resolve({ ok: true, status: 200,
                    json: function () { return Promise.resolve(k); } }); }
  window.fetch = function (url) {
    var p = String(url).split('?')[0];
    if (p === '/api/wissen/scope') return A({ ok: true, user: 'anna', is_editor: false,
        is_admin: false, groups: G, folders: [
          { path: 'data/rag/community', name: 'community', root: 'data/rag/community', depth: 0 }] });
    if (p === '/api/wissen/files') return A({ ok: true, files: D });
    return A({ ok: true, pending: [], spaces: [], status: 'ok', files: [] });
  };
  window.confirm = function () { return false; };
})();
</script>
"""

WEG = Path(tempfile.mkdtemp(prefix="wistab-", dir=str(Path.home())))
os.chmod(WEG, 0o755)
(WEG / "static").mkdir()
for teil in ("css", "js", "vendor"):
    if (ROOT / "frontend" / teil).exists():
        (WEG / "static" / teil).symlink_to(ROOT / "frontend" / teil)
(WEG / "probe.html").write_text(HTML.replace("<body", ATTRAPPE + "<body", 1), encoding="utf-8")

srv = subprocess.Popen([sys.executable, "-u", "-m", "http.server", "0", "--bind", "127.0.0.1"],
                       cwd=str(WEG), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
HTTP_PORT = None
for _ in range(40):
    m = re.search(r"port (\d+)", srv.stdout.readline() or "")
    if m:
        HTTP_PORT = int(m.group(1))
        break
if not HTTP_PORT:
    print("ABBRUCH: kein HTTP-Port.")
    srv.kill()
    shutil.rmtree(WEG, ignore_errors=True)
    sys.exit(2)
BASIS = f"http://127.0.0.1:{HTTP_PORT}"

PROFIL = tempfile.mkdtemp(prefix="chrome-wistab-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
_s = socket.socket()
_s.bind(("127.0.0.1", 0))
PORT = _s.getsockname()[1]
_s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1280,1000", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

BILDER = Path.home() / "wistab-bilder"
BILDER.mkdir(exist_ok=True)


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
    for pr in (chrome, srv):
        try:
            pr.kill()
        except Exception:  # noqa: BLE001
            pass
    shutil.rmtree(PROFIL, ignore_errors=True)
    shutil.rmtree(WEG, ignore_errors=True)


ws_url = cdp_ziel()
if not ws_url:
    print("ABBRUCH: kein CDP-Ziel")
    raeum()
    sys.exit(2)
from websockets.sync.client import connect  # noqa: E402

_id = [0]


def cdp(sock, methode, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": methode, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=30))
        if d.get("id") == _id[0]:
            return d.get("result", {})


def js(sock, ausdruck):
    r = cdp(sock, "Runtime.evaluate", expression=ausdruck, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def mausklick(sock, x, y):
    """ECHTER Klick – ein element.click() aus JS umginge Treffer-Pruefung und
    Ueberdeckung, um die es hier geht."""
    for typ in ("mousePressed", "mouseReleased"):
        cdp(sock, "Input.dispatchMouseEvent", type=typ, x=x, y=y, button="left", clickCount=1)
    time.sleep(0.2)


def mitte(sock, sel):
    return js(sock, f"""(function(){{var e=document.querySelector({json.dumps(sel)});
        if(!e)return null;var r=e.getBoundingClientRect();
        return {{x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height}};}})()""")


def laden(sock, thema, breite=1280):
    cdp(sock, "Emulation.setDeviceMetricsOverride", width=breite, height=1000,
        deviceScaleFactor=1, mobile=False)
    cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
        source=("try{localStorage.setItem('jarvis_theme',%r);}catch(e){}" % thema))
    cdp(sock, "Page.navigate", url=f"{BASIS}/probe.html")
    for _ in range(80):
        time.sleep(0.15)
        if js(sock, "!!document.querySelector('#wi-files-list .wi-frow')"):
            break
    js(sock, """(function(){var s=document.getElementById('wi-sec-files');
        if(s&&s.classList.contains('collapsed')){var h=s.querySelector('h2');if(h)h.click();}})()""")
    time.sleep(0.3)


def schuss(sock, name):
    js(sock, "document.getElementById('wi-sec-files').scrollIntoView(true)")
    time.sleep(0.3)
    r = cdp(sock, "Page.captureScreenshot", format="png")
    p = BILDER / f"{name}.png"
    p.write_bytes(base64.b64decode(r["data"]))
    return p


print("=" * 74)
print("Optische Abnahme: 'Mein Wissen' als Tabelle + Maximieren (/wissen)")
print("=" * 74)
bilder = []
seitengrund = {}
try:
    with connect(ws_url, max_size=60 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        cdp(sock, "Runtime.enable")
        for thema in ("dark", "light"):
            print(f"\n--- Thema: {thema} ---")
            laden(sock, thema)
            seitengrund[thema] = js(sock, "getComputedStyle(document.body).backgroundColor")
            n = js(sock, "document.querySelectorAll('#wi-files-list .wi-frow').length")
            check("Positivkontrolle: fuenf Zeilen gezeichnet", n == 5, f"n={n}")
            if n != 5:
                continue

            koepfe = js(sock, """[].map.call(document.querySelectorAll('#wi-files-list th[data-sort]'),
                function(t){var r=t.getBoundingClientRect();return {k:t.dataset.sort,
                l:Math.round(r.left),t:Math.round(r.top),w:Math.round(r.width),h:Math.round(r.height)};})""")
            check("vier Spaltenkoepfe", len(koepfe or []) == 4, str(koepfe))
            check("alle sichtbar (Breite und Hoehe > 0)",
                  all(k["w"] > 20 and k["h"] > 10 for k in koepfe or [{"w": 0, "h": 0}]), str(koepfe))
            check("auf EINER Hoehe", len({k["t"] for k in koepfe or []}) == 1, str(koepfe))
            check("links nach rechts: Name, Ordner, Wissensgruppen, Groesse",
                  [k["k"] for k in sorted(koepfe or [], key=lambda k: k["l"])] == ["name", "folder", "groups", "size"],
                  str(koepfe))

            lage = js(sock, """(function(){var t=document.querySelector('#wi-files-list table').getBoundingClientRect();
                var s=document.getElementById('wi-sec-files').getBoundingClientRect();
                return {tl:Math.round(t.left),tr:Math.round(t.right),sl:Math.round(s.left),sr:Math.round(s.right)};})()""")
            check("die Tabelle bleibt im Abschnitt", lage["tl"] >= lage["sl"] and lage["tr"] <= lage["sr"], str(lage))
            ueber = js(sock, "document.documentElement.scrollWidth-document.documentElement.clientWidth")
            check("kein waagerechter Ueberlauf der Seite (trotz langem Namen)", ueber <= 1, f"{ueber}px")

            lang = js(sock, """(function(){var r=[].filter.call(document.querySelectorAll('#wi-files-list .wi-frow'),
                function(x){return /Jahresabschluss/.test(x.textContent);})[0];
                var w=document.querySelector('#wi-files-list .wi-ftable-wrap').getBoundingClientRect();
                var b=r.querySelector('.wi-file-del').getBoundingClientRect();
                return {br:Math.round(b.right),wr:Math.round(w.right),bw:Math.round(b.width)};})()""")
            check("Muelleimer der langen Zeile bleibt sichtbar im Rahmen",
                  lang["bw"] > 10 and lang["br"] <= lang["wr"] + 1, str(lang))

            rechts = js(sock, """(function(){var c=document.querySelector('#wi-files-list td.wi-fsize');
                var r=document.createRange();r.selectNodeContents(c);var t=r.getBoundingClientRect(),z=c.getBoundingClientRect();
                return {text:Math.round(z.right-t.right),links:Math.round(t.left-z.left)};})()""")
            check("Groesse steht rechtsbuendig", rechts["text"] <= 12 and rechts["links"] > rechts["text"], str(rechts))

            # ⚠ Ein INAKTIVER Kopf: der aktive steht bewusst in der Hauptfarbe –
            # an ihm gemessen kam ein Traumwert (16,96:1) heraus, und die
            # gedaempften Koepfe waren ungeprueft.
            k = js(sock, """(function(){var e=document.querySelector('#wi-files-list th[data-sort="folder"][aria-sort="none"] .wi-sortbtn');
                var p=e,bg='';while(p){var b=getComputedStyle(p).backgroundColor;
                  if(b&&b!=='rgba(0, 0, 0, 0)'&&b!=='transparent'){bg=b;break;}p=p.parentElement;}
                return {vg:getComputedStyle(e).color,bg:bg||getComputedStyle(document.body).backgroundColor};})()""")
            kw = kontrast(misch(k["vg"], k["bg"]), farbe(k["bg"]))
            check(f"inaktiver Spaltenkopf lesbar (Kontrast {kw:.2f}:1 >= 4.5)", kw >= 4.5, str(k))

            # ── echter Klick auf einen Spaltenkopf ─────────────────────────
            js(sock, "document.getElementById('wi-sec-files').scrollIntoView(true)")
            time.sleep(0.2)
            m = mitte(sock, "#wi-files-list th[data-sort='size'] .wi-sortbtn")
            mausklick(sock, m["x"], m["y"])
            erste = js(sock, "document.querySelector('#wi-files-list .wi-frow .wi-fname').textContent.trim()")
            check("echter Klick auf 'Groesse' sortiert (kleinste zuerst)", erste == "urlaub.md", erste)
            letzte = js(sock, "[].slice.call(document.querySelectorAll('#wi-files-list .wi-frow .wi-fname')).pop().textContent.trim()")
            check("… unbekannte Groesse steht am Ende", letzte == "offline.pdf", letzte)
            bilder.append(schuss(sock, f"{thema}-normal"))

            # ── Maximieren mit echtem Klick (Knopf hinter "Angemeldet als") ─
            check("KEIN Maximieren-Knopf in der Titelleiste oder in 'Mein Wissen'",
                  js(sock, "!document.querySelector('.wi-topbar .jv-max-btn, #wi-sec-files .jv-max-btn')") is True)
            js(sock, "window.scrollTo(0,0)")
            time.sleep(0.2)
            m = mitte(sock, "#jv-max")
            check("Knopf hat eine Groesse", bool(m) and m["w"] > 15 and m["h"] > 15, str(m))
            if not m:
                continue
            lg = js(sock, """(function(){var b=document.getElementById('wi-scope-banner').getBoundingClientRect(),
                k=document.getElementById('jv-max').getBoundingClientRect(),
                t=document.querySelector('.wi-topbar').getBoundingClientRect();
                return {br:Math.round(b.right),bm:Math.round(b.top+b.height/2),bt:Math.round(b.top),
                        kl:Math.round(k.left),km:Math.round(k.top+k.height/2),tb:Math.round(t.bottom),
                        txt:document.getElementById('wi-scope-banner').textContent.trim()};})()""")
            check("Positivkontrolle: Banner zeigt 'Angemeldet als'", "Angemeldet als" in (lg or {}).get("txt", ""), str(lg))
            check("Knopf steht RECHTS hinter dem Banner, auf derselben Hoehe",
                  lg["kl"] >= lg["br"] and abs(lg["km"] - lg["bm"]) <= 2, str(lg))
            check("… ganz oben: unter der Titelleiste, vor jedem Abschnitt",
                  lg["bt"] >= lg["tb"] and js(sock, "document.querySelector('.wi-section:not([style*=\"none\"])')"
                                              ".getBoundingClientRect().top") > lg["bt"], str(lg))
            treffer = js(sock, f"(function(){{var e=document.elementFromPoint({m['x']},{m['y']});"
                               "return !!(e&&e.closest('#jv-max'));})()")
            check("Knopf ist per elementFromPoint erreichbar (nichts liegt darueber)", treffer)
            breiten = """(function(){var r=[];[].forEach.call(document.querySelectorAll('#wi-app > .wi-section, #wi-app > .wi-scope-row'),
                function(x){var q=x.getBoundingClientRect();if(q.width>0)r.push({id:x.id||x.className,l:Math.round(q.left),w:Math.round(q.width)});});
                return {r:r,vw:document.documentElement.clientWidth};})()"""
            vor = js(sock, breiten)
            check("Positivkontrolle: vorher hoechstens 900 px breit",
                  bool(vor["r"]) and all(x["w"] <= 900 for x in vor["r"]), str(vor))
            mausklick(sock, m["x"], m["y"])
            time.sleep(0.2)
            nach = js(sock, breiten)
            soll = nach["vw"] - 2 * 18
            check(f"maximiert: ALLE Abschnitte fensterbreit ({soll} px = Fenster - Rand)",
                  len(nach["r"]) == len(vor["r"]) and all(abs(x["w"] - soll) <= 1 for x in nach["r"]), str(nach))
            check("… und breiter als vorher", all(x["w"] > 900 for x in nach["r"]), str(nach))
            check("… kein Abschnitt ist fixiert",
                  js(sock, "[].every.call(document.querySelectorAll('.wi-section'),function(x){return getComputedStyle(x).position!=='fixed';})") is True)
            ueber = js(sock, "document.documentElement.scrollWidth-document.documentElement.clientWidth")
            check("maximiert: kein waagerechter Ueberlauf", ueber <= 1, f"{ueber}px")
            lage = js(sock, """(function(){var t=document.querySelector('#wi-files-list table').getBoundingClientRect();
                var s=document.getElementById('wi-sec-files').getBoundingClientRect();
                return {tl:Math.round(t.left),tr:Math.round(t.right),sl:Math.round(s.left),sr:Math.round(s.right)};})()""")
            check("maximiert: die Tabelle waechst mit und bleibt im Abschnitt",
                  lage["tl"] >= lage["sl"] and lage["tr"] <= lage["sr"] and lage["tr"] - lage["tl"] > 900, str(lage))
            r = cdp(sock, "Page.captureScreenshot", format="png")
            p = BILDER / f"{thema}-maximiert.png"
            p.write_bytes(base64.b64decode(r["data"]))
            bilder.append(p)
            # Der Zustand ueberlebt das NEULADEN (je Browser gemerkt, Vorgabe
            # 2026-09-27) – im ECHTEN Browser gemessen: jsdom hat je Seite
            # einen eigenen Speicher und sieht ein Neuladen nie.
            laden(sock, thema)
            neu = js(sock, breiten)
            check("nach Neuladen: weiterhin maximiert",
                  bool(neu["r"]) and all(x["w"] > 900 for x in neu["r"]), str(neu))
            check("… und der Knopf sagt 'Verkleinern'",
                  js(sock, "document.getElementById('jv-max').getAttribute('aria-pressed')") == "true")
            m = mitte(sock, "#jv-max")
            mausklick(sock, m["x"], m["y"])
            time.sleep(0.2)
            zur = js(sock, breiten)
            check("zweiter Klick: wieder auf 900 px gedeckelt", all(x["w"] <= 900 for x in zur["r"]), str(zur))
            laden(sock, thema)
            zur2 = js(sock, breiten)
            check("nach Neuladen: bleibt verkleinert", bool(zur2["r"]) and all(x["w"] <= 900 for x in zur2["r"]), str(zur2))

            # ── schmales Fenster ───────────────────────────────────────────
            laden(sock, thema, breite=520)
            ueber = js(sock, "document.documentElement.scrollWidth-document.documentElement.clientWidth")
            check("520 px: kein waagerechter Ueberlauf der Seite", ueber <= 1, f"{ueber}px")
            lage = js(sock, """(function(){var w=document.querySelector('#wi-files-list .wi-ftable-wrap');
                var s=document.getElementById('wi-sec-files').getBoundingClientRect(),r=w.getBoundingClientRect();
                return {wr:Math.round(r.right),sr:Math.round(s.right),sw:w.scrollWidth,cw:w.clientWidth};})()""")
            check("520 px: der Tabellenrahmen bleibt im Abschnitt", lage["wr"] <= lage["sr"], str(lage))
            # ⚠ Die Ueberlauf-Messung allein war GRUEN, waehrend der Screenshot
            # den Dateinamen auf sieben Zeichen je Zeile zerquetscht zeigte.
            # Gemessen wird deshalb auch die Breite der Namensspalte.
            nb = js(sock, "Math.round(document.querySelector('#wi-files-list td.wi-fname').getBoundingClientRect().width)")
            fs = js(sock, "parseFloat(getComputedStyle(document.querySelector('#wi-files-list td.wi-fname')).fontSize)")
            check(f"520 px: Namensspalte bleibt lesbar breit ({nb} px >= 10 em)", nb >= 10 * fs, f"{nb}px / {fs}px")
            bilder.append(schuss(sock, f"{thema}-520"))

    check("Positivkontrolle: hell und dunkel waren zwei verschiedene Messungen",
          len(set(seitengrund.values())) == 2, str(seitengrund))
    print("\nScreenshots:")
    for b in bilder:
        print(f"  {b}")
    print("\n" + "=" * 74)
    print(f"ERGEBNIS: {_ok} OK, {_fail} FAIL")
    print("=" * 74)
finally:
    raeum()

sys.exit(1 if _fail else 0)
