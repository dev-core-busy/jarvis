#!/usr/bin/env python3
"""Optische Abnahme: Confluence-Einbindung als BAUM (Vorgabe 2026-09-27).

Echtes Chrome gegen die AUSGELIEFERTE Seite, beide Themen. jsdom rechnet kein
Layout – ob [+] hinter dem Namen in derselben Zeile steht, ob die Einrueckung
die Tiefe zeigt, ob die Listenzeile mit Bearbeiten + Muelleimer nicht
ueberlaeuft und ob die Bedienhilfe lesbar ist, sieht nur ein Browser.

Die Abruf-Funktion ist vollstaendig gestellt (`Page.addScriptToEvaluateOnNewDocument`),
es geht kein Aufruf an den Dienst; der Datenbestand bleibt unberuehrt.
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



BEREICHE = [{"id": "e1", "typ": "auswahl", "name": "CONTOSO Dokumentation · Betrieb mit einem recht langen Namen",
             "gruppen": ["g1"], "gruppen_info": [{"id": "g1", "name": "Knowledgebase an RAG", "color": "#3b82f6"}],
             "auswahl": [{"key": "CONTOSO", "start": True, "ganz": True, "seiten": ["1", "2", "3", "4"], "zweige": ["1", "2"]},
                         {"key": "OPS", "start": False, "ganz": False, "seiten": ["11"], "zweige": []}],
             "abgleich": {"zeit": "2026-09-27T17:50:00", "seiten": 295, "offen": 146, "fehler": ""}},
            {"id": "alt", "typ": "space", "name": "CONTOSO / Deutschland", "gruppen": [],
             "auswahl": [{"key": "CTDE", "start": True, "ganz": False, "seiten": [], "zweige": []}],
             "abgleich": {"zeit": "2026-09-27T17:50:00", "seiten": 0, "offen": 0, "fehler": "keiner Wissensgruppe zugeordnet"}}]
SPACES = [{"key": "CONTOSO", "name": "CONTOSO Dokumentation", "type": "global"},
          {"key": "OPS", "name": "Betrieb", "type": "global"},
          {"key": "~anna-lena.musterfrau@beispiel-schweiz.example", "name": "Anna-Lena Musterfrau – persoenlicher Bereich mit langem Namen", "type": "personal"}]
PAGES = {"CONTOSO": [{"id": "1", "title": "Handbuch", "parent": ""},
                   {"id": "2", "title": "Kapitel A – Installation und Betrieb", "parent": "1"},
                   {"id": "3", "title": "Kapitel A.1", "parent": "2"},
                   {"id": "4", "title": "Kapitel B", "parent": "1"}],
         "OPS": [{"id": "10", "title": "Start", "parent": ""}, {"id": "11", "title": "Detail", "parent": "10"}]}

VORLAUF = r"""
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
window.addEventListener('unhandledrejection', function (e) {
  window.__fehler += 'ZURUECKWEISUNG: ' + ((e.reason && e.reason.message) || e.reason) + ' | '; });
try { localStorage.setItem('jarvis_token', 'probe'); localStorage.setItem('jarvis_theme', '__THEMA__'); } catch (e) {}
(function () {
  function antwort(d) { return Promise.resolve({ ok: true, status: 200, headers: { get: function () { return null; } },
      json: function () { return Promise.resolve(d); }, text: function () { return Promise.resolve(JSON.stringify(d)); } }); }
  var PAGES = __PAGES__;
  window.__rufe = [];
  window.fetch = function (u, o) {
    var url = String(u).split('?')[0], q = String(u).split('?')[1] || '';
    var meth = ((o && o.method) || 'GET').toUpperCase();
    window.__rufe.push({ pfad: url, m: meth });
    if (url === '/api/me') return antwort({ is_admin: true, username: 'probe', permissions: {} });
    if (url === '/api/wissen/confluence/bindung') return antwort({ ok: true, aktiv: true, bereiche: __BEREICHE__ });
    if (url === '/api/wissen/confluence/spaces') return antwort({ ok: true, configured: true, spaces: __SPACES__ });
    if (url === '/api/wissen/confluence/pages') {
      var k = decodeURIComponent((q.match(/space=([^&]*)/) || [])[1] || '');
      return antwort({ ok: true, pages: PAGES[k] || [] }); }
    if (url === '/api/wissen/scope') return antwort({ ok: true, user: 'probe',
        groups: [{ id: 'g1', name: 'Knowledgebase an RAG', color: '#3b82f6', folders: ['data/rag/x'] }],
        folders: [{ path: 'data/rag/x', name: 'x', display: 'x', root: 'data/rag/x', depth: 0 }] });
    if (url === '/api/wissen/files') return antwort({ ok: true, files: [] });
    return antwort({ ok: true });
  };
})();
"""
PROFIL = tempfile.mkdtemp(prefix="chrome-cfbbaum-", dir=str(Path.home()))
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


print("Optische Abnahme: Confluence-Einbindung als Baum")
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


RECHTECK = """(function(){var e=document.querySelector('%s');if(!e)return null;
var r=e.getBoundingClientRect();
return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),
        r:Math.round(r.right),b:Math.round(r.bottom)};})()"""

KONTRAST = """(function(){
  var e=document.querySelector('%s'); if(!e) return null;
  var c=getComputedStyle(e), g=e, lagen=[];
  while(g){ var b=getComputedStyle(g).backgroundColor; var m=/rgba?\\(([^)]+)\\)/.exec(b);
    if(m){ var t=m[1].split(',').map(parseFloat); var a=t.length>3?t[3]:1;
      if(a>0){ lagen.push([t[0],t[1],t[2],a]); if(a>=1) break; } }
    g=g.parentElement; }
  if(!lagen.length||lagen[lagen.length-1][3]<1) lagen.push([255,255,255,1]);
  var out=lagen[lagen.length-1].slice(0,3);
  for(var i=lagen.length-2;i>=0;i--){ var l=lagen[i]; out=[0,1,2].map(function(k){return l[k]*l[3]+out[k]*(1-l[3]);}); }
  return {fg:c.color, bg:'rgb('+out.map(Math.round).join(', ')+')'};})()"""

with connect(ws, open_timeout=20, max_size=60_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    gemessen = {}
    for thema in ("dunkel", "hell"):
        print(f"\n── {thema} " + "─" * 55)
        cdp(sock, "Emulation.setEmulatedMedia", media="screen", features=[
            {"name": "prefers-color-scheme", "value": "dark" if thema == "dunkel" else "light"}])
        cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
            source=VORLAUF.replace("__THEMA__", "dark" if thema == "dunkel" else "light")
                          .replace("__BEREICHE__", json.dumps(BEREICHE, ensure_ascii=False))
                          .replace("__SPACES__", json.dumps(SPACES, ensure_ascii=False))
                          .replace("__PAGES__", json.dumps(PAGES, ensure_ascii=False)))
        cdp(sock, "Page.navigate", url="https://127.0.0.1/wissen")
        time.sleep(3.5)
        fehler = js(sock, "window.__fehler || ''")
        check("keine JS-Fehler auf der Seite", not fehler, fehler or "")
        auf = js(sock, "(function(){var s=document.getElementById('wi-sec-cfbind');"
                       "return !s?'fehlt':(getComputedStyle(s).display==='none'?'zu':'da');})()")
        check("POSITIVKONTROLLE: der Container ist sichtbar", auf == "da", str(auf))
        n = js(sock, "document.querySelectorAll('#wi-cfb-tree li.wi-cfb-sp').length")
        check("POSITIVKONTROLLE: der Baum traegt die Bereiche", n == 3, str(n))
        # Vorgabe 2026-09-28: der Editor ist ZU, bis "Neuer Bereich" oder
        # "Bearbeiten" geklickt wird. Gemessen ueber checkVisibility() -
        # sichtbar heisst: der Browser zeichnet es.
        zu = js(sock, """(function(){var v=function(id){var e=document.getElementById(id);
          return !!e && e.checkVisibility();};
          return {ed:v('wi-cfb-editor'), baum:v('wi-cfb-tree'), grp:v('wi-cfb-groups'),
                  add:v('wi-cfb-add'), neu:v('wi-cfb-new'), liste:v('wi-cfb-list'),
                  ueber:document.documentElement.scrollWidth-document.documentElement.clientWidth};})()""")
        check("⚠ Grundzustand: Gruppen, Baum, Übernehmen NICHT sichtbar",
              bool(zu) and not (zu["ed"] or zu["baum"] or zu["grp"] or zu["add"]), str(zu))
        check("Grundzustand: 'Neuer Bereich' und die Liste sichtbar",
              bool(zu) and zu["neu"] and zu["liste"], str(zu))
        check("Grundzustand: kein waagerechter Ueberlauf", bool(zu) and zu["ueber"] <= 0, str(zu))
        js(sock, "(function(){var e=document.getElementById('wi-cfb-new');if(e)e.scrollIntoView({block:'center'});})()")
        time.sleep(0.4)
        bild(sock, f"cfb-zu-{thema}.png")
        kn = js(sock, KONTRAST % "#wi-cfb-new")
        # ⚠ NICHT in `gemessen`: dort prueft die Positivkontrolle "hell !=
        # dunkel", und `.sec-btn.primary` ist in beiden Themen gleich (Register).
        kv = kontrast(farbe(kn["fg"]), farbe(kn["bg"])) if kn else 0.0
        check(f"Knopf 'Neuer Bereich' lesbar (>= 4,5:1): {kv:.2f}:1", kv >= 4.5, str(kn))
        js(sock, "document.getElementById('wi-cfb-new').click()")
        time.sleep(0.5)
        auf2 = js(sock, """(function(){var v=function(id){var e=document.getElementById(id);
          return !!e && e.checkVisibility();};
          return {ed:v('wi-cfb-editor'), baum:v('wi-cfb-tree'), add:v('wi-cfb-add'),
                  ab:v('wi-cfb-cancel'), neu:v('wi-cfb-new')};})()""")
        check("⚠ nach 'Neuer Bereich': Editor, Baum, Übernehmen und Abbrechen sichtbar",
              bool(auf2) and auf2["ed"] and auf2["baum"] and auf2["add"] and auf2["ab"] and not auf2["neu"],
              str(auf2))

        # [+] am ersten Bereich klicken (echter Klick ueber das DOM)
        js(sock, "document.querySelector('#wi-cfb-tree li.wi-cfb-sp .wi-cfb-tog').click()")
        time.sleep(0.8)
        st = js(sock, """(function(){var li=document.querySelector('#wi-cfb-tree li.wi-cfb-sp');
          var t=li.querySelector('.wi-cfb-tog');
          return {tog:t.textContent, an:li.querySelectorAll('.wi-cfb-cb:checked').length,
                  sicht:li.querySelectorAll('.wi-cf-kids.open').length};})()""")
        check("[+] -> [-], Bereich + 4 Unterbereiche markiert, aufgeklappt",
              st and st["tog"] == "[-]" and st["an"] == 5 and st["sicht"] >= 1, json.dumps(st))
        # Zweig "Handbuch" (Seite 1) aufklappen per Name, damit die Tiefe sichtbar ist
        js(sock, "document.querySelector('#wi-cfb-tree li.wi-cfb-pg .wi-cfb-nm').click()")
        time.sleep(0.4)
        js(sock, "(function(){var x=document.querySelectorAll('#wi-cfb-tree li.wi-cfb-pg[data-id=\"2\"] .wi-cfb-nm');if(x[0])x[0].click();})()")
        time.sleep(0.4)

        rn = js(sock, RECHTECK % "#wi-cfb-tree li.wi-cfb-sp .wi-cfb-nm")
        rt = js(sock, RECHTECK % "#wi-cfb-tree li.wi-cfb-sp .wi-cfb-tog")
        check("⚠ [+]/[-] steht HINTER dem Namen in derselben Zeile",
              bool(rn and rt) and rt["x"] >= rn["r"] - 1 and min(rn["b"], rt["b"]) - max(rn["y"], rt["y"]) > 4,
              f"name={rn} tog={rt}")
        tiefe = js(sock, """(function(){function x(s){var e=document.querySelector(s);
            return e?Math.round(e.getBoundingClientRect().x):null;}
          return [x('#wi-cfb-tree li.wi-cfb-sp .wi-cfb-cb'), x('#wi-cfb-tree li.wi-cfb-pg[data-id="1"] .wi-cfb-cb'),
                  x('#wi-cfb-tree li.wi-cfb-pg[data-id="2"] .wi-cfb-cb'), x('#wi-cfb-tree li.wi-cfb-pg[data-id="3"] .wi-cfb-cb')];})()""")
        check("⚠ die Einrueckung zeigt die Tiefe (Bereich < Seite < Unterseite < Enkel)",
              tiefe and None not in tiefe and tiefe[0] < tiefe[1] < tiefe[2] < tiefe[3], json.dumps(tiefe))
        sp3 = js(sock, RECHTECK % "#wi-cfb-tree li.wi-cfb-sp:nth-child(3) .wi-cf-node")
        tr = js(sock, RECHTECK % "#wi-cfb-tree")
        check("ein langer Bereichsname bleibt im Baum (bricht um statt ueberzulaufen)",
              bool(sp3 and tr) and sp3["r"] <= tr["r"], f"{sp3} / {tr}")

        # Kontraste
        for sel, was in (("#wi-cfb-tree li.wi-cfb-sp .wi-cfb-tog", "[+]/[-]"),
                         ("#wi-cfb-tree li.wi-cfb-sp .wi-cfb-nm", "Bereichsname"),
                         ("[data-i18n=\"wissen.cfb_tree_hint\"]", "Bedienhilfe"),
                         ("#wi-cfb-list .wi-cfb-sync", "Abgleichszeile"),
                         ("#wi-cfb-list .wi-cfb-edit", "Knopf Bearbeiten")):
            vg = js(sock, KONTRAST % sel)
            if vg:
                k = kontrast(farbe(vg["fg"]), farbe(vg["bg"]))
                check(f"Kontrast {was} >= 4,5:1 (gemessen {k:.2f}:1)", k >= 4.5, f"fg={vg['fg']} bg={vg['bg']}")
            else:
                check(f"{was} messbar", False, "nicht gefunden")

        # Liste: Zeile mit Chips, Bearbeiten und Muelleimer
        zeile = js(sock, """(function(){var z=document.querySelector('#wi-cfb-list .wi-item');if(!z)return null;
          var r=z.getBoundingClientRect(), e=z.querySelector('.wi-cfb-edit').getBoundingClientRect(),
              d=z.querySelector('.wi-cfb-del').getBoundingClientRect();
          return {zr:Math.round(r.right), er:Math.round(e.right), dr:Math.round(d.right),
                  gleich: Math.abs((e.top+e.bottom)/2-(d.top+d.bottom)/2) < 6};})()""")
        check("Listenzeile: Bearbeiten und Muelleimer nebeneinander, innerhalb der Zeile",
              bool(zeile) and zeile["gleich"] and zeile["dr"] <= zeile["zr"] and zeile["er"] <= zeile["zr"], json.dumps(zeile))
        grund = js(sock, "getComputedStyle(document.body).backgroundColor")
        gemessen[thema] = grund

        js(sock, "(function(){var e=document.getElementById('wi-sec-cfbind');if(e)e.scrollIntoView({block:'start'});})()")
        time.sleep(0.4)
        bild(sock, f"cfb-baum-{thema}.png")
        js(sock, "(function(){var e=document.getElementById('wi-cfb-list');if(e)e.scrollIntoView({block:'center'});})()")
        time.sleep(0.3)
        bild(sock, f"cfb-baum-liste-{thema}.png")

        # Bearbeiten-Modus
        js(sock, "document.querySelector('#wi-cfb-list .wi-cfb-edit').click()")
        time.sleep(0.8)
        ed = js(sock, """(function(){return {btn:document.getElementById('wi-cfb-add').textContent.trim(),
          ab:getComputedStyle(document.getElementById('wi-cfb-cancel')).display,
          note:document.getElementById('wi-cfb-editnote').textContent};})()""")
        check("Bearbeiten: Knopf 'Speichern', 'Abbrechen' sichtbar, Hinweis nennt den Eintrag",
              ed and ed["btn"] in ("Speichern", "Save") and ed["ab"] != "none" and "CONTOSO" in ed["note"], json.dumps(ed))
        # Vorgabe 2026-09-27: der Editor steht IN der Box des bearbeiteten
        # Eintrags, UNTER dessen Kopfzeile, und ragt nicht aus ihr heraus.
        lage = js(sock, """(function(){var z=document.querySelector('#wi-cfb-list .wi-item[data-id="e1"]'),
          e=document.getElementById('wi-cfb-editor'); if(!z||!e) return null;
          var zr=z.getBoundingClientRect(), er=e.getBoundingClientRect(),
              kr=z.querySelector('.wi-cfb-edit').getBoundingClientRect();
          return {drin: z.contains(e), l:Math.round(er.left-zr.left), r:Math.round(zr.right-er.right),
                  b:Math.round(zr.bottom-er.bottom), unter:Math.round(er.top-kr.bottom)};})()""")
        check("⚠ Bearbeiten: der Editor steht IN der Box des Eintrags, unter ihrer Kopfzeile",
              bool(lage) and lage["drin"] and lage["l"] >= 0 and lage["r"] >= 0 and lage["b"] >= 0
              and lage["unter"] >= 0, json.dumps(lage))
        js(sock, "(function(){var e=document.querySelector('.wi-cfb-actions');if(e)e.scrollIntoView({block:'center'});})()")
        time.sleep(0.3)
        bild(sock, f"cfb-baum-bearbeiten-{thema}.png")

        cdp(sock, "Emulation.setDeviceMetricsOverride", width=520, height=900, deviceScaleFactor=1, mobile=False)
        time.sleep(0.6)
        eng = js(sock, """(function(){var s=document.getElementById('wi-sec-cfbind').getBoundingClientRect();
          var m=0; document.querySelectorAll('#wi-sec-cfbind *').forEach(function(e){
            var r=e.getBoundingClientRect(); if(r.width>0 && r.right>m) m=r.right;});
          return {ueber:Math.round(m - s.right)};})()""")
        check("schmal (520px): nichts im Container ragt ueber seinen Rand", bool(eng) and eng["ueber"] <= 0, json.dumps(eng))
        bild(sock, f"cfb-baum-schmal-{thema}.png")
        cdp(sock, "Emulation.clearDeviceMetricsOverride")
        time.sleep(0.4)

    check("POSITIVKONTROLLE: hell und dunkel waren zwei verschiedene Messungen",
          len(gemessen) == 2 and gemessen.get("hell") != gemessen.get("dunkel"), json.dumps(gemessen))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
