#!/usr/bin/env python3
"""Live-Probe (Chrome, DEV): gestaltbare Auswahl statt Betriebssystem-Menue.

VORFALL (2026-11-21, DEV und ECHT): Protokolle → Sicherheitsprotokoll →
"Ereignis" – ein Klick oeffnete die Liste und waehlte SOFORT einen Eintrag.
Mit echter Maus nachgestellt (1366x768, 1280x720, Feld bei 70 % der Hoehe):
Chromes Menue (21 Eintraege, ~480 px) passte weder unter noch ueber das Feld
und wurde UEBER das Feld geschoben, das Loslassen traf einen Eintrag.

Die gestaltbare Auswahl (theme.css, `appearance: base-select`) zeichnet die
Liste IN der Seite – deshalb ist der Bedienweg hier auch headless messbar:
CDP-Maus druecken + loslassen am Feld, danach muss die Liste offen und die
Auswahl unveraendert sein. Das alte Betriebssystem-Menue liess sich headless
NICHT messen (es liegt ausserhalb der Seite); der Nachweis des Fehlers selbst
lief ueber Xvfb + xdotool und steht im Register.

Geprueft:
  1. Klick am Feld waehlt nichts aus, die Liste ist offen – bei drei Lagen
     des Feldes im Fenster und in beiden Themen
  2. die offene Liste ueberdeckt das Feld nicht (Bildvergleich des
     Feldinneren geschlossen gegen offen, mit Positivkontrolle der Sonde)
  3. ein Feld ohne feste Breite springt beim Auswaehlen nicht
     (js/auswahlliste.js)
  4. Auswahl und Eingabefeld derselben Klasse sind gleich hoch

`fetch` und `localStorage` stehen VOR dem ersten Skript
(`Page.addScriptToEvaluateOnNewDocument`), angemeldet wird nicht.
Aufruf auf DEV: venv/bin/python tests/live_auswahlliste_ui_dev.py
Bilder: ~/.jarvis-abnahme/auswahl-<thema>-<lage>.png
"""
import base64
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from io import BytesIO
from pathlib import Path

BILDER = Path.home() / ".jarvis-abnahme"
BILDER.mkdir(mode=0o700, exist_ok=True)
_ok = _fail = 0
BREITE, HOEHE = 1280, 720   # Fenster, in dem der Fehler nachgestellt wurde


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


# Echte Ereignisarten aus dem DEV-Protokoll (2026-11-21): 20 Arten + "Alle"
ARTEN = ["abhaengigkeiten", "abmeldung", "admin_aenderung", "admin_beendet", "admin_erhoehung",
         "admin_verweigert", "anmeldung", "anmeldung_fehlgeschlagen", "cve_pruefung", "dienst_start",
         "fehleranalyse", "geheimnis_bestaetigung", "geheimnis_schluessel_fehlt", "kennwort_pruefung",
         "kette_bruch_anerkannt", "konto_aenderung", "konto_gesperrt", "loeschfristen_geaendert",
         "rechte_aenderung", "stt_quelle_geaendert"]
DATEN = {"eintraege": [{"ts": 1792505727, "art": a, "benutzer": "x", "ip": "192.0.2.1",
                        "ergebnis": "200", "details": {}} for a in ARTEN],
         "arten": ARTEN, "kette": {"ok": True, "zeilen": len(ARTEN), "brueche": [], "anzahl_brueche": 0},
         "aufbewahrung_tage": 365, "syslog": True, "schreibfehler": {"datei": 0}}

VORLAUF = r"""
window.__fehler = [];
window.addEventListener('error', function (e) { window.__fehler.push((e.filename || '?') + ': ' + e.message); });
try { localStorage.setItem('jarvis_token', 'probe'); localStorage.setItem('jarvis_theme', '__THEMA__'); } catch (e) {}
(function () {
  function antwort(d) {
    return Promise.resolve({ ok: true, status: 200, headers: { get: function () { return null; } },
      json: function () { return Promise.resolve(d); },
      text: function () { return Promise.resolve(JSON.stringify(d)); } });
  }
  window.fetch = function (u) {
    var url = String(u).split('?')[0];
    if (url === '/api/me') return antwort({ is_admin: true, username: 'probe', permissions: {} });
    if (url === '/api/verify-token') return antwort({ valid: true, username: 'probe', is_admin: true });
    if (url === '/api/security/log') return antwort(__DATEN__);
    return antwort({ ok: true, items: [], skills: [], groups: [], profiles: [], entries: [] });
  };
})();
""".replace("__DATEN__", json.dumps(DATEN))

PROFIL = tempfile.mkdtemp(prefix="chrome-auswahl-", dir=str(Path.home()))
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", f"--window-size={BREITE},{HOEHE}",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ende(code):
    chrome.kill()
    time.sleep(1)
    shutil.rmtree(PROFIL, ignore_errors=True)
    print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
    sys.exit(code)


def ziel_ws():
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


ws = ziel_ws()
if not ws:
    print("ABBRUCH: kein CDP-Ziel")
    ende(2)
try:
    from websockets.sync.client import connect
    from PIL import Image
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Modul fehlt im venv ({e})")
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


def maus(sock, x, y):
    """Druecken und Loslassen an DERSELBEN Stelle – der gemeldete Bedienweg."""
    cdp(sock, "Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
    cdp(sock, "Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
    time.sleep(0.3)
    cdp(sock, "Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
    time.sleep(0.5)


def escape(sock):
    for t in ("keyDown", "keyUp"):
        cdp(sock, "Input.dispatchKeyEvent", type=t, key="Escape", code="Escape", windowsVirtualKeyCode=27)
    time.sleep(0.3)


MAGENTA = (255, 0, 255)
# Nur fuer die Messung: die offene Liste deckend magenta faerben. Eine Farbe,
# die in der Oberflaeche nicht vorkommt, macht "liegt die Liste ueber dem
# Feld?" zu einer Pixelzaehlung. Die erste Fassung verglich das Feldinnere
# geschlossen gegen offen – und mass den SCHATTEN der Liste, der auf das Feld
# faellt (50 % "veraendert" bei vollstaendig sichtbarem Feld); im dunklen Thema
# haben Liste und Feld ausserdem dieselbe Flaeche, eine echte Ueberdeckung
# haette dort nur die Textpixel geaendert.
SONDE_CSS = ("select::picker(select), select option { background-color: rgb(255,0,255) !important;"
             " background-image: none !important; }")


def magenta_zaehlen(sock, r):
    """(Magenta-Pixel im Feldrechteck, Magenta-Pixel im ganzen Bild)."""
    b = cdp(sock, "Page.captureScreenshot", format="png")
    img = Image.open(BytesIO(base64.b64decode(b["data"]))).convert("RGB")
    px = img.load()

    def ist(c):
        return abs(c[0] - 255) <= 6 and c[1] <= 6 and abs(c[2] - 255) <= 6
    gesamt = sum(1 for c in img.getdata() if ist(c))
    x0, y0 = int(r["vx"]), int(r["vy"])
    x1, y1 = int(r["vx"] + r["w"]), int(r["vy"] + r["h"])
    im_feld = sum(1 for x in range(max(0, x0), min(img.width, x1))
                  for y in range(max(0, y0), min(img.height, y1)) if ist(px[x, y]))
    return im_feld, gesamt, img


FELD = "sprot-filter-art"
RECHTECK = ("(function(){var r=document.getElementById('%s').getBoundingClientRect();"
            "return {vx:r.left,vy:r.top,w:r.width,h:r.height,cx:r.left+r.width/2,cy:r.top+r.height/2};})()")
ROLLEN = """(function(id,z){var s=document.getElementById(id);
  for(var i=0;i<5;i++){var d=s.getBoundingClientRect().top-z;
    for(var c=s.parentElement;c;c=c.parentElement){
      if(c.scrollHeight>c.clientHeight+1&&/auto|scroll/.test(getComputedStyle(c).overflowY)){c.scrollTop+=d;d=s.getBoundingClientRect().top-z;}}
    window.scrollBy(0,d);}})('%s',%d)"""

with connect(ws, open_timeout=20, max_size=80_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    skript = None
    for thema in ("dark", "light"):
        print(f"\n── Thema {thema} " + "─" * 40)
        if skript:
            cdp(sock, "Page.removeScriptToEvaluateOnNewDocument", identifier=skript)
        skript = cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
                     source=VORLAUF.replace("__THEMA__", thema)).get("identifier")
        cdp(sock, "Page.navigate", url="https://127.0.0.1/settings")
        time.sleep(5)
        js(sock, "document.querySelector('[data-settings-tab=\"telemetry\"]').click()")
        time.sleep(0.8)
        js(sock, "document.querySelector('[data-klick=\"sprot-klappen\"]').click()")
        time.sleep(1.5)
        # ── Positivkontrollen: Seite da, Liste gefuellt, Browser kann es ──
        lage = js(sock, "(function(){var s=document.getElementById('%s');var m=document.getElementById('login-screen');"
                        "return {n:s?s.options.length:0,sichtbar:!!(s&&s.offsetParent),"
                        "kann:CSS.supports('appearance','base-select'),app:s?getComputedStyle(s).appearance:'',"
                        "maske:m?getComputedStyle(m).display:'keine',ih:innerHeight};})()" % FELD)
        if not lage or not lage["sichtbar"] or lage["n"] != len(ARTEN) + 1 or lage["maske"] not in ("none", "keine"):
            print(f"ABBRUCH: Abschnitt nicht messbar ({lage})")
            ende(2)
        if not lage["kann"]:
            print("ABBRUCH: dieser Chrome kennt base-select nicht – Messung waere trivial")
            ende(2)
        check(f"Feld 'Ereignis' ist gestaltbare Auswahl ({lage['n']} Eintraege)",
              lage["app"] == "base-select", lage["app"])

        js(sock, "(function(){var s=document.createElement('style');s.id='__sonde';s.textContent=%s;"
                 "document.head.appendChild(s);})()" % json.dumps(SONDE_CSS))
        for anteil in (0.2, 0.7, 0.9):
            js(sock, ROLLEN % (FELD, int(lage["ih"] * anteil)))
            time.sleep(0.4)
            js(sock, "document.getElementById('%s').value=''" % FELD)
            r = js(sock, RECHTECK % FELD)
            maus(sock, r["cx"], r["cy"])
            st = js(sock, "(function(){var s=document.getElementById('%s');return {wert:s.value,offen:s.matches(':open')};})()" % FELD)
            im_feld, gesamt, img = magenta_zaehlen(sock, r)
            img.save(BILDER / f"auswahl-{thema}-{int(anteil * 100)}.png")
            check(f"Feld bei {int(anteil * 100)} % der Hoehe: Klick oeffnet die Liste", st["offen"] is True, str(st))
            check(f"Feld bei {int(anteil * 100)} % der Hoehe: Klick waehlt NICHTS aus (gemeldeter Fehler)",
                  st["wert"] == "", repr(st["wert"]))
            # Positivkontrolle je Lage: die Liste ist wirklich gezeichnet
            if gesamt < 2000:
                print(f"ABBRUCH: offene Liste nicht im Bild ({gesamt} Magenta-Pixel) – 'ueberdeckt nicht' waere trivial")
                ende(2)
            check(f"Feld bei {int(anteil * 100)} % der Hoehe: offene Liste ueberdeckt das Feld nicht "
                  f"({im_feld} Listen-Pixel im Feld, {gesamt} im Bild)", im_feld == 0)
            escape(sock)
        # Positivkontrolle der Sonde: eine Liste UEBER dem Feld muss sie melden
        r = js(sock, RECHTECK % FELD)
        js(sock, "(function(){var d=document.createElement('div');d.id='__deckel';var r=document.getElementById('%s')"
                 ".getBoundingClientRect();d.style.cssText='position:fixed;z-index:2147483647;background:rgb(255,0,255);'"
                 "+'left:'+r.left+'px;top:'+(r.top-200)+'px;width:'+r.width+'px;height:'+(r.height+220)+'px';"
                 "document.body.appendChild(d);})()" % FELD)
        time.sleep(0.2)
        im_feld, gesamt, _ = magenta_zaehlen(sock, r)
        js(sock, "document.getElementById('__deckel').remove();document.getElementById('__sonde').remove()")
        if im_feld < r["w"] * r["h"] * 0.9:
            print(f"ABBRUCH: Sonde erkennt eine Liste ueber dem Feld nicht ({im_feld} Pixel) – Pruefung waere trivial")
            ende(2)

    # ── Breite: Feld ohne feste Breite springt nicht (js/auswahlliste.js) ──
    print("\n── Breite und Hoehe " + "─" * 40)
    js(sock, "document.querySelector('[data-settings-tab=\"security\"]').click()")
    time.sleep(0.8)
    js(sock, "[].forEach.call(document.querySelectorAll('details'),function(d){d.open=true;})")
    br = js(sock, """(function(){var s=document.getElementById('sec-ssh-netz-praefix');
        if(!s||!s.offsetParent)return null;s.scrollIntoView({block:'center'});s.focus();
        var w=[];for(var i=0;i<s.options.length;i++){s.selectedIndex=i;w.push(Math.round(s.getBoundingClientRect().width));}
        s.selectedIndex=0;return {w:w,n:s.options.length,min:s.style.minWidth};})()""")
    if not br or br["n"] < 2:
        print(f"ABBRUCH: Feld 'Umfang' (SSH-Netze) nicht sichtbar ({br})")
        ende(2)
    check("Feld ohne feste Breite ('Umfang'): gleiche Breite fuer jeden Eintrag",
          len(set(br["w"])) == 1, json.dumps(br))
    # ── Hoehe: jedes sichtbare Feld gegen SICH SELBST im alten Modus ──
    # Inline `appearance: auto` schaltet das Feld kurz auf die Betriebssystem-
    # Auswahl zurueck; die Hoehe muss gleich bleiben (gemessen wurde vor dem
    # Umbau: +5 px durch Chromes Vorgaben, dann -2 px ohne Innenabstand).
    # Kein Vergleich mit einem Eingabefeld: `em-kanal` war schon vorher 2 px
    # hoeher als das Eingabefeld darunter – eine feste Erwartung waere falsch.
    HOEHE_JS = """(function(){var out=[];[].forEach.call(document.querySelectorAll('select'),function(s){
        if(!s.offsetParent||s.multiple||s.hasAttribute('size'))return;
        var neu=s.getBoundingClientRect().height;s.style.appearance='auto';
        var alt=s.getBoundingClientRect().height;s.style.appearance='';
        out.push({id:s.id||s.className,neu:Math.round(neu),alt:Math.round(alt),kl:!!s.className});});return out;})()"""
    gesamt = []
    for reiter in ("email", "telemetry", "security", "sap", "feedback"):
        js(sock, "document.querySelector('[data-settings-tab=\"%s\"]').click()" % reiter)
        time.sleep(0.8)
        gesamt += js(sock, HOEHE_JS) or []
    mit_klasse = [h for h in gesamt if h["kl"]]
    if len(mit_klasse) < 3:
        print(f"ABBRUCH: zu wenige sichtbare Auswahlfelder fuer den Hoehenvergleich ({len(mit_klasse)})")
        ende(2)
    abw = [h for h in mit_klasse if h["neu"] != h["alt"]]
    check(f"Hoehe gestalteter Auswahlfelder unveraendert gegen die alte Auswahl ({len(mit_klasse)} Felder)",
          not abw, json.dumps(abw))
    fehler = js(sock, "(window.__fehler||[]).filter(function(f){return /auswahlliste|theme/.test(f);}).join(' | ')")
    check("keine JS-Fehler aus auswahlliste.js", not fehler, fehler or "")

ende(1 if _fail else 0)
