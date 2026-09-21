#!/usr/bin/env python3
"""Optische Abnahme des Suchfeldes im Kopf der Einstellungen (hell UND dunkel).

⚠ GEMESSEN WIRD DIE AUSGELIEFERTE SEITE `/settings`, nicht ein Markup-Schnitt.
Nur dort steht der ECHTE Modal-Kopf mit Titel, Haus, Vollbild und Schliessen
daneben – und genau gegen die rechnet das Feld (es ist das einzige Kind der
Gruppe, das schrumpfen darf). Eine selbst gebaute Probeseite koennte das nicht
zeigen und liesse ausserdem einen Rueckstand unter `frontend/` (Register:
`test_theme_default` laeuft ueber jede HTML-Datei dort).

⚠ DAS PANEL HAENGT IN EINEM CONTAINER MIT `overflow: hidden` (.modal-content).
Die wichtigste Messung hier ist deshalb: bleibt es innerhalb des Modals –
auch auf einem niedrigen Fenster? Ein jsdom-Waechter kann das nicht sagen,
er rechnet kein Layout.

Angemeldet wird nicht: Token und `fetch` werden VOR dem ersten Skript der
Seite gestellt (`Page.addScriptToEvaluateOnNewDocument`) – ein spaeteres
`Runtime.evaluate` kaeme zu spaet, die Seite hat sich dann laengst umgeleitet.

Aufruf auf DEV: cd /opt/jarvis && ./venv/bin/python tests/live_settings_suche_ui_dev.py
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


# Echte Manifeste als Korpus: ein erfundener Bestand belegt nicht, dass die
# Zeilen mit den Feldnamen DIESES Hauses in die Breite passen.
NICHT_INSTALLIERT = "telegram"   # der eine Skill, der die Marke traegt


def korpus():
    raus = []
    d = ROOT / "skills"
    for p in sorted(d.iterdir()):
        m = p / "skill.json"
        if not m.is_file():
            continue
        try:
            s = json.loads(m.read_text(encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            continue
        s["dir_name"] = p.name
        # ⚠ EINER MUSS NICHT INSTALLIERT SEIN. Die Probe tippt weiter unten
        # "telegram" und misst die Marke „nicht installiert“ - bei durchweg
        # installierten Skills kann sie GAR NICHT erscheinen, und die Pruefung
        # verlangt etwas, das der eigene Aufbau ausschliesst (gemessen: null).
        s["installed"] = p.name != NICHT_INSTALLIERT
        s["enabled"] = s["installed"]
        s["path"] = str(p)
        raus.append(s)
    if not any(x["dir_name"] == NICHT_INSTALLIERT for x in raus):
        print(f"ABBRUCH: Skill {NICHT_INSTALLIERT!r} fehlt - die Marke waere "
              f"nicht messbar.")
        sys.exit(2)
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
  // gueltiger Wert - "dunkel" waere still hell (zweimal dasselbe gemessen).
  localStorage.setItem('jarvis_theme', '__THEMAWERT__');
} catch (e) {}
(function () {
  var SKILLS = __SKILLS__;
  function antwort(d) {
    return Promise.resolve({ ok: true, status: 200,
      headers: { get: function () { return null; } },
      json: function () { return Promise.resolve(d); },
      text: function () { return Promise.resolve(JSON.stringify(d)); } });
  }
  window.fetch = function (u) {
    var url = String(u).split('?')[0];
    if (url === '/api/me') {
      return antwort({ username: 'jarvis', is_admin: true, permissions: {} });
    }
    if (url === '/api/skills') { return antwort({ skills: SKILLS }); }
    return antwort({ ok: true });
  };
})();
"""

PROFIL = tempfile.mkdtemp(prefix="chrome-stsuche-", dir=str(Path.home()))
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
print("Optische Abnahme: Suchfeld im Kopf der Einstellungen")
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


SKILLS = json.dumps(korpus())
_vorlauf = [None]          # Kennung des registrierten Vorlauf-Skripts
gruende = {}

with connect(ws, open_timeout=20, max_size=80_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")

    for thema in ("dunkel", "hell"):
        print(f"\n── {thema} " + "─" * 55)
        if _vorlauf[0]:
            cdp(sock, "Page.removeScriptToEvaluateOnNewDocument",
                identifier=_vorlauf[0])
        _vorlauf[0] = cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
            source=VORLAUF.replace("__THEMAWERT__",
                                   "dark" if thema == "dunkel" else "light")
                          .replace("__SKILLS__", SKILLS)).get("identifier")
        cdp(sock, "Emulation.setDeviceMetricsOverride",
            width=1400, height=900, deviceScaleFactor=1, mobile=False)
        cdp(sock, "Page.navigate", url=ZIEL)
        time.sleep(4.0)

        # Positivkontrolle: ohne offenes Modal ist JEDE Messung darunter
        # trivial wahr (ein Rechteck in einem display:none-Vorfahren ist 0).
        auf = js(sock, "!!document.querySelector('#settings-modal.open')")
        if not auf:
            js(sock, "(function(){var m=document.getElementById('settings-modal');"
                     "if(m)m.classList.add('open');"
                     "if(window.SettingsSearch)window.SettingsSearch.init();"
                     "var l=document.getElementById('login-screen');"
                     "if(l)l.classList.remove('active');return 1;})()")
            time.sleep(0.8)
        check("Einstellungen sind offen",
              bool(js(sock, "!!document.querySelector('#settings-modal.open')")))
        kopf = rect(sock, "#settings-modal .modal-header")
        check("der Modal-Kopf hat eine Groesse (Messung nicht trivial)",
              bool(kopf) and kopf["h"] > 20 and kopf["w"] > 200, json.dumps(kopf))

        feld = rect(sock, "#st-such-feld")
        haus = rect(sock, "#btn-home-settings")
        zu = rect(sock, "#btn-close-settings")
        check("Suchfeld ist sichtbar", bool(feld) and feld["w"] > 60 and feld["h"] > 10,
              json.dumps(feld))
        check("es steht LINKS vom Haus", bool(feld) and bool(haus) and feld["r"] <= haus["x"] + 2,
              f"feld.r={feld and feld['r']} haus.x={haus and haus['x']}")
        check("Feld, Haus und Schliessen stehen in EINER Zeile",
              bool(feld) and bool(zu) and abs(feld["y"] - zu["y"]) < 14,
              f"{feld and feld['y']} vs {zu and zu['y']}")
        check("die Symbolgruppe bleibt im Kopf",
              bool(zu) and bool(kopf) and zu["r"] <= kopf["r"] + 1,
              f"zu.r={zu and zu['r']} kopf.r={kopf and kopf['r']}")

        # ── Tippen ueber ECHTE Tastaturereignisse ──────────────────────────
        js(sock, "document.getElementById('st-such-feld').focus()")
        for z in "token":
            cdp(sock, "Input.dispatchKeyEvent", type="keyDown", text=z)
            cdp(sock, "Input.dispatchKeyEvent", type="keyUp")
        time.sleep(1.2)

        n = js(sock, "document.querySelectorAll('#st-such-liste .st-such-item').length")
        check("Treffer werden gezeigt", bool(n) and n > 0, str(n))
        panel = rect(sock, "#st-such-panel")
        inhalt = rect(sock, "#settings-modal .modal-content")
        check("Panel ist sichtbar", bool(panel) and panel["h"] > 40, json.dumps(panel))
        # ⚠ DIE KERNMESSUNG: `.modal-content` traegt `overflow: hidden`.
        check("Panel bleibt INNERHALB des Modals (wird nicht abgeschnitten)",
              bool(panel) and bool(inhalt)
              and panel["b"] <= inhalt["b"] + 1
              and panel["r"] <= inhalt["r"] + 1
              and panel["x"] >= inhalt["x"] - 1,
              f"panel={json.dumps(panel)} inhalt={json.dumps(inhalt)}")

        ueber = js(sock, "document.documentElement.scrollWidth - "
                         "document.documentElement.clientWidth")
        check("kein waagerechter Ueberlauf der Seite", (ueber or 0) <= 1, str(ueber))
        ueberL = js(sock, "(function(){var l=document.getElementById('st-such-liste');"
                          "return l ? l.scrollWidth - l.clientWidth : -1;})()")
        check("kein waagerechter Ueberlauf in der Trefferliste", (ueberL or 0) <= 1, str(ueberL))

        # Ein langer Titel darf die Zeile nicht sprengen – er kuerzt mit Ellipse.
        lang = js(sock, """(function(){
            var z=document.querySelectorAll('#st-such-liste .st-such-item');
            var s=0,m=0;
            for(var i=0;i<z.length;i++){
              var t=z[i].querySelector('.st-such-titel');
              var zr=z[i].getBoundingClientRect(), tr=t.getBoundingClientRect();
              if(tr.right>zr.right+1) s++;
              m=Math.max(m,t.scrollWidth-t.clientWidth);
            }
            return {raus:s,geschnitten:m};})()""")
        check("kein Titel ragt aus seiner Zeile", (lang or {}).get("raus") == 0, json.dumps(lang))

        # Marken bleiben sichtbar (sie stehen NEBEN dem Titel, nicht darin).
        js(sock, "document.getElementById('st-such-feld').value='';")
        js(sock, "document.getElementById('st-such-feld')"
                 ".dispatchEvent(new Event('input',{bubbles:true}));")
        js(sock, "document.getElementById('st-such-feld').focus()")
        for z in "telegram":
            cdp(sock, "Input.dispatchKeyEvent", type="keyDown", text=z)
            cdp(sock, "Input.dispatchKeyEvent", type="keyUp")
        time.sleep(1.0)

        # ── Kontraste ─────────────────────────────────────────────────────
        werte = js(sock, """(function(){
            var p=document.getElementById('st-such-panel');
            var it=document.querySelector('#st-such-liste .st-such-item');
            var ti=it&&it.querySelector('.st-such-titel');
            var pf=it&&it.querySelector('.st-such-pfad');
            var hi=document.getElementById('st-such-hinweis');
            var f=document.getElementById('st-such-feld');
            var g=function(e,k){return e?getComputedStyle(e)[k]:null;};
            return {panelBg:g(p,'backgroundColor'), titel:g(ti,'color'),
                    pfad:g(pf,'color'), hinweis:g(hi,'color'),
                    feldFg:g(f,'color'), feldBg:g(f,'backgroundColor'),
                    kopfBg:g(document.querySelector('#settings-modal .modal-header'),'backgroundColor'),
                    inhaltBg:g(document.querySelector('#settings-modal .modal-content'),'backgroundColor'),
                    seiteBg:g(document.body,'backgroundColor')};})()""")
        seite = farbe(werte["seiteBg"])
        panelbg = mische(werte["panelBg"], seite)
        gruende[thema] = panelbg
        k_titel = kontrast(mische(werte["titel"], panelbg), panelbg)
        k_pfad = kontrast(mische(werte["pfad"], panelbg), panelbg)
        k_hin = kontrast(mische(werte["hinweis"], panelbg), panelbg)
        check(f"Titel lesbar ({k_titel:.2f}:1)", k_titel >= 4.5)
        check(f"Pfadzeile lesbar ({k_pfad:.2f}:1)", k_pfad >= 4.5)
        check(f"Fusszeile lesbar ({k_hin:.2f}:1)", k_hin >= 4.5)
        feldbg = mische(werte["feldBg"], mische(werte["kopfBg"],
                        mische(werte["inhaltBg"], seite)))
        k_feld = kontrast(mische(werte["feldFg"], feldbg), feldbg)
        check(f"Eingabetext lesbar ({k_feld:.2f}:1)", k_feld >= 4.5)

        mark = js(sock, """(function(){
            var m=document.querySelector('#st-such-liste .st-such-mark');
            if(!m)return null;var s=getComputedStyle(m);
            return {bg:s.backgroundColor,txt:m.textContent};})()""")
        check("Fundstelle ist farblich abgesetzt",
              bool(mark) and mark["bg"] not in ("rgba(0, 0, 0, 0)", "transparent"),
              json.dumps(mark))

        marke = js(sock, """(function(){
            var m=document.querySelector('#st-such-liste .st-such-marke');
            if(!m)return null;var r=m.getBoundingClientRect();
            var z=m.closest('.st-such-item').getBoundingClientRect();
            return {w:Math.round(r.width),drin:r.right<=z.right+1&&r.width>4,
                    txt:m.textContent.trim()};})()""")
        check("Marke „nicht installiert“ ist sichtbar und in der Zeile",
              bool(marke) and marke["drin"], json.dumps(marke))

        bild(sock, f"stsuche-{thema}.png")

        # ── Niedriges Fenster: das Panel darf nicht abgeschnitten werden ───
        cdp(sock, "Emulation.setDeviceMetricsOverride",
            width=1100, height=600, deviceScaleFactor=1, mobile=False)
        time.sleep(0.8)
        panel2 = rect(sock, "#st-such-panel")
        inhalt2 = rect(sock, "#settings-modal .modal-content")
        check("auch bei 600 px Fensterhoehe bleibt das Panel im Modal",
              bool(panel2) and bool(inhalt2) and panel2["b"] <= inhalt2["b"] + 1,
              f"panel={json.dumps(panel2)} inhalt={json.dumps(inhalt2)}")
        bild(sock, f"stsuche-{thema}-niedrig.png")

        # ── Schmales Fenster: Symbolgruppe bleibt im Kopf ──────────────────
        cdp(sock, "Emulation.setDeviceMetricsOverride",
            width=520, height=800, deviceScaleFactor=1, mobile=False)
        time.sleep(0.8)
        f3 = rect(sock, "#st-such-feld")
        z3 = rect(sock, "#btn-close-settings")
        h3 = rect(sock, "#btn-home-settings")
        k3 = rect(sock, "#settings-modal .modal-header")
        check("schmal: das Feld schrumpft, bleibt aber benutzbar",
              bool(f3) and f3["w"] >= 60, json.dumps(f3))
        check("schmal: die Symbole behalten ihre Groesse",
              bool(h3) and h3["w"] >= 30, json.dumps(h3))
        check("schmal: Schliessen bleibt im Kopf",
              bool(z3) and bool(k3) and z3["r"] <= k3["r"] + 1,
              f"zu.r={z3 and z3['r']} kopf.r={k3 and k3['r']}")

        # ⚠ DIE MESSUNG, DIE GEFEHLT HAT. Die Eindaemmung wurde nur bei 1400 px
        # geprueft - dort ist links reichlich Platz. Bei 520 px ragte das Panel
        # LINKS aus dem Modal, die Titel waren abgeschnitten; gesehen hat es
        # nur der Screenshot. Sie gehoert genau dorthin, wo es eng wird.
        # ⚠ ERST LEEREN. Ohne das steht "telegramtelegram" im Feld, es gibt
        # KEINEN Treffer - und "das Panel bleibt im Modal" ist ueber einer
        # leeren Liste trivial wahr (im Screenshot gesehen, die Messung war
        # gruen). Deshalb darunter die Positivkontrolle auf echte Treffer.
        js(sock, "document.getElementById('st-such-feld').value='';")
        js(sock, "document.getElementById('st-such-feld')"
                 ".dispatchEvent(new Event('input',{bubbles:true}));")
        js(sock, "document.getElementById('st-such-feld').focus()")
        for z in "telegram":
            cdp(sock, "Input.dispatchKeyEvent", type="keyDown", text=z)
            cdp(sock, "Input.dispatchKeyEvent", type="keyUp")
        time.sleep(1.0)
        n3 = js(sock, "document.querySelectorAll('#st-such-liste .st-such-item').length")
        check("schmal: es gibt ueberhaupt Treffer (Messung nicht trivial)",
              bool(n3) and n3 > 0, str(n3))
        p3 = rect(sock, "#st-such-panel")
        i3 = rect(sock, "#settings-modal .modal-content")
        check("schmal: das Panel bleibt INNERHALB des Modals",
              bool(p3) and bool(i3)
              and p3["x"] >= i3["x"] - 1 and p3["r"] <= i3["r"] + 1,
              f"panel={json.dumps(p3)} inhalt={json.dumps(i3)}")
        # Und der Titel darf dabei nicht aus seiner Zeile laufen - eine
        # Eindaemmung, die den Text abschneidet, waere keine.
        raus3 = js(sock, """(function(){var n=0;
            document.querySelectorAll('#st-such-liste .st-such-item').forEach(
              function(it){var t=it.querySelector('.st-such-titel');
                if(!t)return;var r=t.getBoundingClientRect();
                var z=it.getBoundingClientRect();
                if(r.left<z.left-1||r.right>z.right+1)n++;});
            return n;})()""")
        check("schmal: kein Titel ragt aus seiner Zeile", (raus3 or 0) == 0, str(raus3))
        bild(sock, f"stsuche-{thema}-schmal.png")

        # ── Der gemeldete Fall: „ldap" (2026-09-20) ────────────────────────
        #
        # ⚠ GEMESSEN AN DER AUSGELIEFERTEN SEITE, mit dem ECHTEN app.js: nur
        # dort sind die Reiter eingeblendet und die Klapp-Handler gebunden.
        # Ein Aufbau ohne app.js haette 21 von 29 Reitern versteckt und keinen
        # Handler - die Messung waere gruen und wertlos.
        js(sock, """(function(){var f=document.getElementById('st-such-feld');
            f.value=''; f.dispatchEvent(new Event('input',{bubbles:true}));
            f.focus();})()""")
        for z in "ldap":
            cdp(sock, "Input.dispatchKeyEvent", type="keyDown", text=z)
            cdp(sock, "Input.dispatchKeyEvent", type="keyUp")
        time.sleep(1.2)
        nL = js(sock, "document.querySelectorAll('#st-such-liste .st-such-item').length")
        check("„ldap“ findet etwas (der gemeldete Fall)", bool(nL) and nL > 0, str(nL))
        t1 = js(sock, """(function(){var e=document.querySelector(
            '#st-such-liste .st-such-item .st-such-titel');
            return e?e.textContent:'';})()""") or ""
        check("… und zwar den AD-Abschnitt an erster Stelle",
              ("LDAP" in t1) or ("Active Directory" in t1), t1[:70])
        # Der Pfad nennt den Reiter - sonst weiss niemand, wohin der Klick fuehrt.
        pf1 = js(sock, """(function(){var e=document.querySelector(
            '#st-such-liste .st-such-item .st-such-pfad');
            return e?e.textContent:'';})()""") or ""
        check("die Zeile nennt den Reiter", len(pf1.strip()) > 2, pf1[:70])
        bild(sock, f"stsuche-{thema}-ldap.png")

        # ⚠ UND DER KLICK MUSS WIRKLICH DORTHIN FUEHREN. Ein Treffer, der den
        # Reiter oeffnet und den Abschnitt zu laesst, waere die halbe Zusage.
        js(sock, "document.querySelector('#st-such-liste .st-such-item').click();")
        time.sleep(0.6)
        lage = js(sock, """(function(){
            var sec=document.getElementById('settings-tab-security');
            var hv=document.querySelector('.st-such-treffer');
            var auf=0, zu=0;
            document.querySelectorAll('#settings-tab-security .kb-collapse-body')
              .forEach(function(b){ if(b.style.display==='none') zu++; else auf++; });
            var r=hv?hv.getBoundingClientRect():null;
            return { reiter: sec ? (sec.style.display!=='none') : false,
                     hervor: !!hv, auf: auf, zu: zu,
                     sichtbar: r ? (r.height>0 && r.top<window.innerHeight && r.bottom>0) : false };
        })()""") or {}
        check("der Klick oeffnet den Reiter Sicherheit", lage.get("reiter") is True, json.dumps(lage))
        check("… und klappt einen Abschnitt darin AUF", (lage.get("auf") or 0) > 0, json.dumps(lage))
        check("… und hebt den Punkt hervor", lage.get("hervor") is True, json.dumps(lage))
        check("… und der Punkt steht im Bild", lage.get("sichtbar") is True, json.dumps(lage))
        bild(sock, f"stsuche-{thema}-ldap-ziel.png")

        # ── Der gemeldete Fall: „Gesperrte Konten" (2026-09-21) ────────────
        #
        # Eine Zwischenueberschrift INNERHALB eines Abschnitts – die vierte
        # Ebene, die bis dahin gar nicht indiziert war. Gemessen an der
        # ausgelieferten Seite, weil nur dort die Reiter eingeblendet und die
        # Klapp-Handler gebunden sind.
        js(sock, """(function(){var f=document.getElementById('st-such-feld');
            f.value=''; f.dispatchEvent(new Event('input',{bubbles:true}));
            f.focus();})()""")
        for z in "gesperrte konten":
            cdp(sock, "Input.dispatchKeyEvent", type="keyDown", text=z)
            cdp(sock, "Input.dispatchKeyEvent", type="keyUp")
        time.sleep(1.2)
        nG = js(sock, "document.querySelectorAll('#st-such-liste .st-such-item').length")
        check("„gesperrte konten“ findet etwas (der gemeldete Fall)",
              bool(nG) and nG > 0, str(nG))
        tG = js(sock, """(function(){var e=document.querySelector(
            '#st-such-liste .st-such-item .st-such-titel');
            return e?e.textContent:'';})()""") or ""
        check("… und zwar genau diesen Punkt", tG.strip() == "Gesperrte Konten", tG[:70])
        bild(sock, f"stsuche-{thema}-gesperrt.png")

        js(sock, "document.querySelector('#st-such-liste .st-such-item').click();")
        time.sleep(0.6)
        lg = js(sock, """(function(){
            var hv=document.querySelector('.st-such-treffer');
            var r=hv?hv.getBoundingClientRect():null;
            return { hervor: !!hv,
                     sichtbar: r ? (r.height>0 && r.top<window.innerHeight && r.bottom>0) : false };
        })()""") or {}
        check("der Klick hebt „Gesperrte Konten“ hervor", lg.get("hervor") is True,
              json.dumps(lg))
        check("… und der Punkt steht im Bild", lg.get("sichtbar") is True, json.dumps(lg))
        bild(sock, f"stsuche-{thema}-gesperrt-ziel.png")

        # ⚠ EIN <details> MUSS DER KLICK OEFFNEN. Die Berechtigungs-Bloecke des
        # Sicherheits-Reiters sind so gebaut und starten ZU; ohne das landete
        # der Treffer auf einer geschlossenen Zeile.
        js(sock, """(function(){
            var d=document.querySelector('details.sec-sub[data-sub="internet"]');
            if(d) d.open=false;
            var f=document.getElementById('st-such-feld');
            f.value=''; f.dispatchEvent(new Event('input',{bubbles:true}));
            f.focus();})()""")
        for z in "internet-zugang":
            cdp(sock, "Input.dispatchKeyEvent", type="keyDown", text=z)
            cdp(sock, "Input.dispatchKeyEvent", type="keyUp")
        time.sleep(1.2)
        vor = js(sock, """(function(){var d=document.querySelector(
            'details.sec-sub[data-sub="internet"]'); return d?d.open:null;})()""")
        check("Positivkontrolle: der Block ist VOR dem Klick zu", vor is False, str(vor))
        nI = js(sock, "document.querySelectorAll('#st-such-liste .st-such-item').length")
        check("„internet-zugang“ findet etwas", bool(nI) and nI > 0, str(nI))
        js(sock, "document.querySelector('#st-such-liste .st-such-item').click();")
        time.sleep(0.6)
        nach = js(sock, """(function(){var d=document.querySelector(
            'details.sec-sub[data-sub="internet"]');
            var r=d?d.getBoundingClientRect():null;
            return { open: d?d.open:null,
                     sichtbar: r ? (r.height>0 && r.top<window.innerHeight && r.bottom>0) : false };
        })()""") or {}
        check("der Klick klappt das <details> AUF", nach.get("open") is True, json.dumps(nach))
        check("… und der Block steht im Bild", nach.get("sichtbar") is True, json.dumps(nach))
        bild(sock, f"stsuche-{thema}-internet-ziel.png")

        fehler = js(sock, "window.__fehler")
        check("keine JS-Fehler auf der Seite", not fehler, str(fehler)[:300])

    # ⚠ POSITIVKONTROLLE: waren hell und dunkel wirklich ZWEI Messungen?
    # Ein identischer Wert ist zuerst ein Verdacht gegen das Messwerkzeug
    # (Register: zweimal hell gemessen und den Unterschied nicht bemerkt).
    check("hell und dunkel waren zwei verschiedene Messungen",
          gruende.get("hell") != gruende.get("dunkel"),
          f"{gruende.get('hell')} vs {gruende.get('dunkel')}")

print("\n" + "=" * 74)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
ende(0 if _fail == 0 else 1)
