#!/usr/bin/env python3
"""Optische Abnahme: Wissensgruppen-Pflicht der Confluence-Einbindung.

Vorgabe 2026-09-22: ein ausgewaehlter Bereich muss beim Speichern mindestens
einer Wissensgruppe zugeordnet werden.

⚠ GEMESSEN WIRD DIE AUSGELIEFERTE SEITE, nicht ein Markup-Schnitt – nur so ist
das echte CSS dabei, und die tragende Frage ist hier eine Layout-Frage: die
Zeile der Liste traegt jetzt Name, Ordner, GRUPPEN-CHIPS, Reichweite-Marke UND
den Muelleimer. Ob dabei etwas aus der Zeile faellt, kann eine jsdom-Messung
grundsaetzlich nicht beantworten.

⚠ DER KNOPF WIRD WIRKLICH GEKLICKT, und die Kaestchen werden mit echten
`change`-Ereignissen umgestellt. Der Datenbestand bleibt unberuehrt: `fetch`
ist vollstaendig gestellt, es geht kein Aufruf an den Dienst.

Angemeldet wird nicht: `fetch` und `localStorage` werden VOR dem ersten Skript
der Seite gestellt (`Page.addScriptToEvaluateOnNewDocument`).
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


# ZWEI Gruppen: bei genau einer hakt `groupBoxes` sie von selbst an, und der
# Fall "Bereich gewaehlt, Gruppe fehlt" - also der gemeldete - waere gar nicht
# herstellbar. Ein langer Name ist Absicht: er ist der Layout-Fall.
GRUPPEN = [
    {"id": "technik", "name": "Technik", "color": "#3b82f6", "folders": ["data/rag/x"]},
    {"id": "hb", "name": "Handbücher Technik und Vertrieb 2026",
     "color": "#eb0000", "folders": ["data/rag/x"]},
]
SPACES = [
    {"key": "IBS", "name": "IBS Handbuch", "type": "global"},
    {"key": "NEXUS", "name": "NEXUS Dokumentation", "type": "global"},
]
# Ein Bestand, der beide Lagen zeigt: mit Zuordnung und - als Altbestand - ohne.
BEREICHE = [
    {"id": "b1", "typ": "space", "key": "NXDP", "name": "NEXUS / Digital Pathology",
     "inkl_unter": True, "gruppen": ["technik", "hb"],
     "gruppen_info": [{"id": "technik", "name": "Technik", "color": "#3b82f6"},
                      {"id": "hb", "name": "Handbücher Technik und Vertrieb 2026",
                       "color": "#eb0000"}]},
    {"id": "b2", "typ": "space", "key": "NXDE", "name": "NEXUS / Deutschland",
     "inkl_unter": False, "gruppen": [], "gruppen_info": []},
]

VORLAUF = r"""
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
window.addEventListener('unhandledrejection', function (e) {
  window.__fehler += 'ZURUECKWEISUNG: ' + ((e.reason && e.reason.message) || e.reason) + ' | ';
});
try {
  localStorage.setItem('jarvis_token', 'probe');
  localStorage.setItem('jarvis_theme', '__THEMA__');
} catch (e) {}
(function () {
  function antwort(d) {
    return Promise.resolve({ ok: true, status: 200, headers: { get: function () { return null; } },
      json: function () { return Promise.resolve(d); },
      text: function () { return Promise.resolve(JSON.stringify(d)); } });
  }
  window.__rufe = [];
  window.__bestand = __BEREICHE__;
  window.fetch = function (u, o) {
    var url = String(u).split('?')[0];
    var meth = ((o && o.method) || 'GET').toUpperCase();
    var rumpf = null;
    try { rumpf = (o && o.body) ? JSON.parse(o.body) : null; } catch (e) {}
    window.__rufe.push({ pfad: url, m: meth, body: rumpf });
    if (url === '/api/wissen/confluence/bindung' && meth === 'POST') {
      var info = (rumpf.groups || []).map(function (id) {
        var g = __GRUPPEN__.filter(function (x) { return x.id === id; })[0];
        return { id: id, name: g ? g.name : id, color: g ? g.color : '' };
      });
      var neu = { id: 'neu', typ: 'space', key: rumpf.key, name: rumpf.key,
                  inkl_unter: rumpf.inkl_unter, gruppen: rumpf.groups || [],
                  gruppen_info: info };
      window.__bestand = window.__bestand.concat([neu]);
      return antwort({ ok: true, bereich: neu, bereiche: window.__bestand });
    }
    if (url === '/api/me') { return antwort({ is_admin: true, username: 'probe', permissions: {} }); }
    if (url === '/api/wissen/confluence/bindung') {
      return antwort({ ok: true, aktiv: true, skill_aktiv: true, configured: true,
                       bereiche: window.__bestand });
    }
    if (url === '/api/wissen/confluence/spaces') {
      return antwort({ ok: true, configured: true, spaces: __SPACES__ });
    }
    if (url === '/api/wissen/scope') {
      return antwort({ ok: true, user: 'probe', is_editor: false,
                       groups: __GRUPPEN__,
                       folders: [{ path: 'data/rag/x', name: 'x', display: 'x',
                                   root: 'data/rag/x', depth: 0 }] });
    }
    if (url === '/api/wissen/files') { return antwort({ ok: true, files: [] }); }
    if (url === '/api/knowledge/pending') { return antwort({ ok: true, items: [] }); }
    return antwort({ ok: true });
  };
})();
"""

PROFIL = tempfile.mkdtemp(prefix="chrome-cfbgrp-", dir=str(Path.home()))
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
                    # NUR type=="page" – /json/list liefert auch die eingebauten
                    # Erweiterungen (Register).
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
print("Optische Abnahme: Wissensgruppen-Pflicht der Confluence-Einbindung")
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
    r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def bild(sock, name):
    r = cdp(sock, "Page.captureScreenshot", format="png")
    if r.get("data"):
        import base64
        p = BILDER / name
        p.write_bytes(base64.b64decode(r["data"]))
        print(f"       Screenshot: {p}")


RECHTECK = """(function(){var e=document.querySelector('%s');if(!e)return null;
var r=e.getBoundingClientRect();
return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),
        h:Math.round(r.height),b:Math.round(r.bottom),re:Math.round(r.right)};})()"""

GRUND = """(function(sel){
  var e=document.querySelector(sel); if(!e) return null;
  var c=getComputedStyle(e), g=e, lagen=[];
  while(g){ var b=getComputedStyle(g).backgroundColor;
    var m=/rgba?\\(([^)]+)\\)/.exec(b);
    if(m){ var t=m[1].split(',').map(parseFloat); var a=t.length>3?t[3]:1;
      if(a>0){ lagen.push([t[0],t[1],t[2],a]); if(a>=1) break; } }
    g=g.parentElement; }
  if(!lagen.length||lagen[lagen.length-1][3]<1) lagen.push([255,255,255,1]);
  var out=lagen[lagen.length-1].slice(0,3);
  for(var i=lagen.length-2;i>=0;i--){ var l=lagen[i];
    out=[0,1,2].map(function(k){return l[k]*l[3]+out[k]*(1-l[3]);}); }
  return {fg:c.color, bg:'rgb('+out.map(Math.round).join(', ')+')'};})('%s')"""

with connect(ws, open_timeout=20, max_size=60_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    gruende = {}

    for thema in ("dunkel", "hell"):
        print(f"\n── {thema} " + "─" * 55)
        cdp(sock, "Emulation.setEmulatedMedia", media="screen", features=[
            {"name": "prefers-color-scheme",
             "value": "dark" if thema == "dunkel" else "light"}])
        cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
            source=VORLAUF.replace("__THEMA__", "dark" if thema == "dunkel" else "light")
                          .replace("__BEREICHE__", json.dumps(BEREICHE, ensure_ascii=False))
                          .replace("__SPACES__", json.dumps(SPACES, ensure_ascii=False))
                          .replace("__GRUPPEN__", json.dumps(GRUPPEN, ensure_ascii=False)))
        cdp(sock, "Page.navigate", url="https://127.0.0.1/wissen")
        time.sleep(3.5)

        # ── Positivkontrollen: ohne sie ist alles darunter trivial wahr ─────
        fehler = js(sock, "window.__fehler || ''")
        check("keine JS-Fehler auf der Seite", not fehler, fehler or "")
        auf = js(sock, "(function(){var s=document.getElementById('wi-sec-cfbind');"
                       "if(!s)return 'fehlt';"
                       "if(getComputedStyle(s).display==='none')return 'zu';return 'da';})()")
        check("POSITIVKONTROLLE: der Container ist sichtbar", auf == "da", str(auf))
        n = js(sock, "document.querySelectorAll('#wi-cfb-groups .wi-grp-cfb').length")
        check("POSITIVKONTROLLE: die Wissensgruppen-Reihe ist gefuellt", n == 2, f"{n}")

        # ── Ort: die Pflicht steht UEBER der Auswahlzeile ───────────────────
        rg = js(sock, RECHTECK % "#wi-cfb-groups")
        rp = js(sock, RECHTECK % ".wi-cfb-pick")
        rl = js(sock, RECHTECK % ".wi-cfb-groups-wrap > label")
        check("die Reihe hat eine Flaeche", bool(rg) and rg["h"] > 0 and rg["w"] > 0,
              json.dumps(rg))
        check("⚠ sie steht UEBER der Auswahlzeile", bool(rg) and bool(rp) and rg["b"] <= rp["y"],
              f"groups.b={rg['b'] if rg else '-'} pick.y={rp['y'] if rp else '-'}")
        check("sie ist beschriftet (Pflichtfeld sichtbar)",
              bool(rl) and rl["h"] > 0, json.dumps(rl))
        besch = js(sock, "(function(){var e=document.querySelector"
                         "('.wi-cfb-groups-wrap > label');return e?e.textContent.trim():'';})()")
        check("die Beschriftung ist uebersetzt (i18n greift)",
              "Wissensgruppen" in (besch or "") or "Knowledge groups" in (besch or ""), besch)

        # ── Der gemeldete Fall: Bereich gewaehlt, Gruppe fehlt ─────────────
        js(sock, """(function(){var s=document.getElementById('wi-cfb-space');
          s.value='IBS'; s.dispatchEvent(new Event('change',{bubbles:true}));})()""")
        time.sleep(0.4)
        z = js(sock, "(function(){var b=document.getElementById('wi-cfb-add');"
                     "return {d:b.disabled,t:b.title};})()")
        check("⚠ Bereich gewaehlt, KEINE Gruppe -> Knopf gesperrt", z["d"] is True, json.dumps(z))
        check("⚠ und der title nennt die WISSENSGRUPPE (nicht den Bereich)",
              bool(re.search(r"Wissensgruppe|knowledge group", z["t"] or "", re.I)),
              json.dumps(z))
        js(sock, "(function(){var e=document.querySelector('.wi-cfb-groups-wrap');"
                 "if(e)e.scrollIntoView({block:'center'});})()")
        time.sleep(0.3)
        bild(sock, f"cfb-grp-gesperrt-{thema}.png")

        # Echtes change-Ereignis am Kaestchen
        js(sock, """(function(){
          var c=document.querySelectorAll('#wi-cfb-groups .wi-grp-cfb')[1];
          c.checked=true; c.dispatchEvent(new Event('change',{bubbles:true}));})()""")
        time.sleep(0.4)
        z2 = js(sock, "(function(){var b=document.getElementById('wi-cfb-add');"
                      "return {d:b.disabled,t:b.title,"
                      "posts:(window.__rufe||[]).filter(function(r){"
                      "return r.m==='POST'&&r.pfad==='/api/wissen/confluence/bindung';}).length};})()")
        check("⚠ mit gewaehlter Gruppe ist der Knopf frei", z2["d"] is False, json.dumps(z2))
        check("der title ist dann leer", not z2["t"], json.dumps(z2))
        check("⚠ das Anhaken allein bindet NICHTS ein", z2["posts"] == 0, json.dumps(z2))

        js(sock, "document.getElementById('wi-cfb-add').click()")
        time.sleep(0.9)
        z3 = js(sock, """(function(){
          var p=(window.__rufe||[]).filter(function(r){
            return r.pfad==='/api/wissen/confluence/bindung' && r.m==='POST';});
          return {n:p.length, groups:p[0]&&p[0].body&&p[0].body.groups,
                  zeilen:document.querySelectorAll('#wi-cfb-list .wi-item').length};})()""")
        check("⚠ der Klick loest GENAU EINEN Aufruf aus", z3["n"] == 1, json.dumps(z3))
        check("⚠ und die Zuordnung faehrt mit",
              json.dumps(z3["groups"]) == json.dumps(["hb"]), json.dumps(z3))
        check("der Bereich steht danach in der Liste", z3["zeilen"] == 3, json.dumps(z3))

        # ── Layout der Liste: Chips + Marke + Muelleimer in EINER Zeile ────
        js(sock, "(function(){var e=document.getElementById('wi-cfb-list');"
                 "if(e)e.scrollIntoView({block:'center'});})()")
        time.sleep(0.3)
        bild(sock, f"cfb-grp-liste-{thema}.png")

        li = js(sock, """(function(){
          var z=document.querySelectorAll('#wi-cfb-list .wi-item');
          return Array.prototype.map.call(z, function(e){
            var r=e.getBoundingClientRect();
            var chips=e.querySelectorAll('.wi-chip');
            var tag=e.querySelector('.wi-cfb-scope-tag');
            var del=e.querySelector('.wi-cfb-del');
            var ng=e.querySelector('.wi-cfb-nogrp');
            function rr(x){ if(!x) return null; var q=x.getBoundingClientRect();
              return {x:Math.round(q.x),y:Math.round(q.y),w:Math.round(q.width),
                      h:Math.round(q.height),re:Math.round(q.right),b:Math.round(q.bottom)};}
            return {zeile:{x:Math.round(r.x),re:Math.round(r.right),
                           y:Math.round(r.y),b:Math.round(r.bottom),h:Math.round(r.height)},
                    chips:Array.prototype.map.call(chips, rr),
                    text:e.textContent.replace(/\\s+/g,' ').trim(),
                    tag:rr(tag), del:rr(del), nogrp:rr(ng)};});})()""")
        check("drei Zeilen gemessen", isinstance(li, list) and len(li) == 3,
              str(len(li) if isinstance(li, list) else li))
        if isinstance(li, list) and len(li) == 3:
            z_mit = li[0]
            check("die Zuordnung steht als Chip in der Zeile",
                  len(z_mit["chips"]) == 2 and all(c and c["w"] > 0 for c in z_mit["chips"]),
                  json.dumps(z_mit["chips"]))
            check("die Gruppennamen sind lesbar",
                  "Technik" in z_mit["text"] and "Handbücher" in z_mit["text"], z_mit["text"][:90])
            for nm, f in (("Muelleimer", "del"), ("Reichweite-Marke", "tag")):
                r = z_mit[f]
                check(f"⚠ {nm} bleibt in der Zeile (kein Ueberlauf nach rechts)",
                      bool(r) and r["re"] <= z_mit["zeile"]["re"] + 1,
                      json.dumps({"el": r, "zeile": z_mit["zeile"]}))
                check(f"   und senkrecht INNERHALB der Zeile ({nm})",
                      bool(r) and r["y"] >= z_mit["zeile"]["y"] - 1
                      and r["b"] <= z_mit["zeile"]["b"] + 1,
                      json.dumps({"el": r, "zeile": z_mit["zeile"]}))
            z_alt = li[1]
            check("⚠ Altbestand: die fehlende Zuordnung steht als Marke da",
                  bool(z_alt["nogrp"]) and z_alt["nogrp"]["w"] > 0, json.dumps(z_alt["nogrp"]))
            check("   und sie ist als Text lesbar",
                  "keiner Wissensgruppe" in z_alt["text"] or "no knowledge group" in z_alt["text"],
                  z_alt["text"][:90])
            check("   sie bleibt ebenfalls in der Zeile",
                  bool(z_alt["nogrp"]) and z_alt["nogrp"]["re"] <= z_alt["zeile"]["re"] + 1,
                  json.dumps({"el": z_alt["nogrp"], "zeile": z_alt["zeile"]}))

        # ── Kein waagerechter Ueberlauf – auch nicht schmal ────────────────
        for breite in (1400, 900, 520):
            cdp(sock, "Emulation.setDeviceMetricsOverride", width=breite, height=900,
                deviceScaleFactor=1, mobile=False)
            time.sleep(0.5)
            ueb = js(sock, """(function(){
              var s=document.getElementById('wi-sec-cfbind');
              return s? Math.round(s.scrollWidth - s.clientWidth) : -1;})()""")
            check(f"kein waagerechter Ueberlauf im Container bei {breite}px", (ueb or 0) <= 1,
                  f"{ueb}px")
        cdp(sock, "Emulation.clearDeviceMetricsOverride")
        time.sleep(0.4)

        # ── Kontrast: Beschriftung und Altbestands-Marke ───────────────────
        for sel, name in ((".wi-cfb-groups-wrap > label", "Beschriftung"),
                          (".wi-cfb-nogrp", "Altbestands-Marke")):
            vg = js(sock, GRUND % sel)
            if vg:
                k = kontrast(farbe(vg["fg"]), farbe(vg["bg"]))
                check(f"{name} ≥ 4,5:1 ({k:.2f}:1)", k >= 4.5,
                      f"{vg['fg']} auf {vg['bg']}")
            else:
                check(f"{name} messbar", False, "Element fehlt")

        gruende[thema] = js(sock, "getComputedStyle(document.body).backgroundColor")

    # ⚠ POSITIVKONTROLLE: hell und dunkel muessen ZWEI Messungen gewesen sein.
    # Ein identischer Wert ist zuerst ein Verdacht gegen das Messwerkzeug
    # (Register: zweimal hell gemessen, ohne es zu merken).
    check("⚠ hell und dunkel waren zwei verschiedene Messungen",
          gruende.get("hell") != gruende.get("dunkel"), json.dumps(gruende))

print(f"\n{_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
