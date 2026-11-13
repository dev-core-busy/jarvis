#!/usr/bin/env python3
"""Optische Abnahme: Token-Verbrauch-Analyse im Reiter "Protokolle" (Chrome, DEV).

jsdom rechnet kein Layout – ob Diagramm, Achsen, Legende, Kacheln und Tooltip
in BEIDEN Themen lesbar sind und nichts ueberlaeuft, zeigt nur die
ausgelieferte Seite mit ihrem echten CSS. Gemessen ueber den echten Bedienweg
(Reiter anklicken, dann den Abschnittskopf); `fetch` und `localStorage` stehen
VOR dem ersten Skript (`Page.addScriptToEvaluateOnNewDocument`), angemeldet
wird nicht. Helfer (Chrome/CDP/Kontrast am Bild) wie in
live_sicherheitsprotokoll_ui_dev.py.

Zwei Datensaetze: die ECHTE Auswertung von DEV (token_verbrauch.auswerten im
Prozess, gleiche Dateien wie der Dienst) und ein dichter Probe-Datensatz mit
neun Reihen (alle Farben + Uebrige), je in hellem und dunklem Thema.

Aufruf auf DEV: venv/bin/python tests/live_token_verbrauch_ui_dev.py
Screenshots: ~/.jarvis-abnahme/tv-<daten>-<thema>.png
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

sys.path.insert(0, "/opt/jarvis")

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
    s = (s or "").strip()
    m = re.match(r"color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", s)
    if m:
        return tuple(round(float(m.group(i)) * 255) for i in (1, 2, 3))
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        return tuple(round(float(x)) for x in m.group(1).replace("/", " ").split(",")[:3])
    return (0, 0, 0)


PROFIL = tempfile.mkdtemp(prefix="chrome-tv-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1400,1000",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


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


def ende(code):
    chrome.kill()
    shutil.rmtree(PROFIL, ignore_errors=True)
    sys.exit(code)


ws = ziel_ws()
if not ws:
    print("ABBRUCH: kein CDP-Ziel")
    ende(2)
try:
    from websockets.sync.client import connect
except Exception:  # noqa: BLE001
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


def bild_kontrast(sock, sel):
    """Schrift gegen ihre FLAECHE, gemessen am gerenderten Bild (Register).

    Die erste Fassung rechnete die CSS-Hintergrundschichten zusammen und nahm
    dabei das halbtransparente Abdunkel-Overlay HINTER dem Einstellungsfenster
    mit: im hellen Thema kamen 2,5:1 heraus, waehrend der Screenshot dunkle
    Schrift auf hellem Grund zeigte. Jetzt: Ausschnitt des Elements, Histogramm,
    nur Farben mit >= 1 % Anteil; die haeufigste ist die Flaeche, die in der
    Leuchtdichte am weitesten entfernte die Schrift. (Hellster gegen dunkelsten
    Bildpunkt waere KEIN Kontrastwert – ein Kantenpixel genuegt.)

    Ausgeschnitten wird das TEXTRECHTECK (Range), nicht die Box: in der 925 px
    breiten Kettenzeile lag die Schrift unter 1 % der Bildpunkte, und die
    Messung verglich zwei Gruentoene der Flaeche (1,05:1 bei gut lesbarer
    Schrift im Screenshot)."""
    from io import BytesIO
    from PIL import Image
    r = js(sock, "(function(){var e=document.querySelector('%s');if(!e)return null;"
                 "e.scrollIntoView({block:'center'});var rg=document.createRange();"
                 "rg.selectNodeContents(e);var b=rg.getBoundingClientRect();"
                 "return {x:b.left+window.scrollX,y:b.top+window.scrollY,w:b.width,h:b.height};})()"
           % sel.replace("'", "\\'"))
    if not r or r["w"] < 2 or r["h"] < 2:
        return None, "kein Rechteck"
    time.sleep(0.2)
    # clip rechnet in SEITENkoordinaten (Register) – daher +scroll oben
    b = cdp(sock, "Page.captureScreenshot", format="png",
            clip={"x": r["x"], "y": r["y"], "width": r["w"], "height": r["h"], "scale": 1})
    if not b.get("data"):
        return None, "kein Bild"
    img = Image.open(BytesIO(base64.b64decode(b["data"]))).convert("RGB")
    farben = img.getcolors(maxcolors=1 << 20) or []
    gesamt = sum(n for n, _ in farben) or 1
    wichtig = sorted([(n, c) for n, c in farben if n / gesamt >= 0.01], reverse=True)
    if len(wichtig) < 2:
        return None, f"nur {len(wichtig)} Farbe(n) mit >= 1 %"
    flaeche = wichtig[0][1]
    schrift = max((c for _, c in wichtig[1:]), key=lambda c: abs(leucht(c) - leucht(flaeche)))
    return kontrast(schrift, flaeche), f"Flaeche {flaeche} Schrift {schrift}"



# ── Datensaetze ──────────────────────────────────────────────────────────────
try:
    from backend import token_verbrauch as _tv
    ECHT = _tv.auswerten(7, "llm", {})
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: echte Auswertung nicht lesbar: {e}")
    sys.exit(2)
ECHT.setdefault("anzeige_benutzer", {})
ECHT["aufbewahrung_tage"] = 90

_jetzt = time.time()
_achse = [_jetzt - 86400 * (7 - i) for i in range(8)]
_namen = ["anthropic · claude-sonnet", "openai_compatible · Qwen/Qwen3.6-35B-A3B-FP8",
          "google · gemini-flash", "openrouter · mistral-large", "anthropic · claude-haiku",
          "openai_compatible · llama-70b", "google · gemini-pro", "openrouter · deepseek"]
_reihen = []
for i, n in enumerate(_namen):
    ein = [int((9 - i) * 41000 * (1 + ((t * 7 + i * 3) % 5) / 4)) for t in range(8)]
    _reihen.append({"schluessel": n, "ein": ein, "aus": [v // 12 for v in ein],
                    "aufrufe": [v // 9000 for v in ein]})
_reihen.append({"schluessel": "__uebrige__", "anzahl": 5, "ein": [12000] * 8, "aus": [900] * 8,
                "aufrufe": [3] * 8})
PROBE = {
    "von": _achse[0], "bis": _jetzt, "tage": 7, "raster": "tag", "gruppe": "llm", "filter": {},
    "zeitachse": _achse, "reihen": _reihen,
    "tabelle": [{"schluessel": r["schluessel"] if r["schluessel"] != "__uebrige__" else "kleinmodell",
                 "aufrufe": sum(r["aufrufe"]), "ein": sum(r["ein"]), "aus": sum(r["aus"]),
                 "ohne_angabe": 0, "fehler": 0, "ms": 1200 * sum(r["aufrufe"])} for r in _reihen]
             + [{"schluessel": "anthropic_session · ohne-zaehlung", "aufrufe": 4, "ein": 0, "aus": 0,
                 "ohne_angabe": 4, "fehler": 1, "ms": 3000}],
    "summe": {"aufrufe": sum(sum(r["aufrufe"]) for r in _reihen) + 4,
              "ein": sum(sum(r["ein"]) for r in _reihen), "aus": sum(sum(r["aus"]) for r in _reihen),
              "cache_lesen": 812345, "ohne_angabe": 4, "fehler": 1},
    "optionen": {"llm": _namen, "benutzer": ["a.nutzer", ""], "dienst": ["agent", "wissensgraph_extraktion"],
                 "werkzeug": ["", "knowledge_search"], "kanal": ["browser", ""]},
    "erfasst_seit": _achse[0] - 3600, "anzeige_benutzer": {"a.nutzer": "BEISPIEL\\a.nutzer"},
    "aufbewahrung_tage": 90,
}

VORLAUF = r"""
window.__fehler = [];
window.addEventListener('error', function (e) {
  window.__fehler.push((e.filename || '?') + ': ' + e.message);
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
  window.fetch = function (u) {
    var url = String(u).split('?')[0];
    if (url === '/api/me') { return antwort({ is_admin: true, username: 'probe', permissions: {} }); }
    if (url === '/api/verify-token') { return antwort({ valid: true, username: 'probe', is_admin: true }); }
    if (url === '/api/logs/token_verbrauch') { return antwort(__DATEN__); }
    return antwort({ ok: true, items: [], skills: [], groups: [], profiles: [], entries: [] });
  };
})();
"""


def farbe_js(sock, ausdruck):
    return farbe(js(sock, ausdruck) or "")


with connect(ws, open_timeout=20, max_size=60_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    skript_id = None
    gemessen = {}
    print(f"echte DEV-Auswertung: {ECHT['summe']}  Reihen={len(ECHT['reihen'])}")
    for name_daten, daten in (("echt", ECHT), ("probe", PROBE)):
        for thema in ("dunkel", "hell"):
            print(f"\n── {name_daten} / {thema} " + "─" * 40)
            cdp(sock, "Emulation.setEmulatedMedia", media="screen", features=[
                {"name": "prefers-color-scheme", "value": "dark" if thema == "dunkel" else "light"}])
            if skript_id:
                cdp(sock, "Page.removeScriptToEvaluateOnNewDocument", identifier=skript_id)
            skript_id = cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
                            source=VORLAUF.replace("__THEMA__", "dark" if thema == "dunkel" else "light")
                            .replace("__DATEN__", json.dumps(daten, ensure_ascii=False))).get("identifier")
            cdp(sock, "Page.navigate", url="https://127.0.0.1/settings")
            time.sleep(4)
            reiter = js(sock, "(function(){var b=document.querySelector('[data-settings-tab=\"telemetry\"]');"
                              "if(!b)return 'fehlt'; b.click(); return 'ok';})()")
            time.sleep(0.6)
            kopf = js(sock, "(function(){var h=document.querySelector('[data-klick=\"tv-klappen\"]');"
                            "if(!h)return 'fehlt'; h.click(); return 'ok';})()")
            time.sleep(1.5)
            check("Reiter und Abschnittskopf gefunden", reiter == "ok" and kopf == "ok", f"{reiter}/{kopf}")
            flaeche = js(sock, "(function(){var e=document.querySelector('#tv-diagramm svg');if(!e)return 0;"
                               "var r=e.getBoundingClientRect();return Math.round(r.width*r.height);})()")
            maske = js(sock, "(function(){var m=document.getElementById('login-screen')||"
                             "document.querySelector('.login-screen');if(!m)return 'keine';"
                             "return getComputedStyle(m).display==='none'?'zu':'offen';})()")
            check("Diagramm ist sichtbar gemalt (Flaeche > 0)", (flaeche or 0) > 0, str(flaeche))
            check("keine Anmeldemaske ueber der Seite", maske != "offen", str(maske))
            if not (flaeche or 0) > 0 or maske == "offen":
                print("ABBRUCH: Diagramm nicht sichtbar – Messungen waeren wertlos.")
                print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
                ende(2)
            fehler = js(sock, "(window.__fehler||[]).filter(function(f){return /token_verbrauch|"
                              "settings_bedienung|telemetry/.test(f);}).join(' | ')")
            check("keine JS-Fehler aus den beteiligten Modulen", not fehler, fehler or "")
            segs = js(sock, "document.querySelectorAll('#tv-diagramm rect.tv-seg').length")
            erwartet = sum(1 for r in daten["reihen"] for i in range(len(r["ein"])) if r["ein"][i] + r["aus"][i] > 0)
            check("Teilsaeulen gezeichnet wie Werte ungleich 0", segs == erwartet, f"{segs}/{erwartet}")
            # Diagramm passt in seinen Kasten, Seite laeuft nicht ueber
            lage = js(sock, "(function(){var b=document.getElementById('tv-diagramm').getBoundingClientRect();"
                            "var s=document.querySelector('#tv-diagramm svg').getBoundingClientRect();"
                            "var k=document.getElementById('tv-kennzahlen').getBoundingClientRect();"
                            "return {raus:Math.round(s.right-b.right),breite:Math.round(s.width),"
                            "kasten:Math.round(b.width),kraus:Math.round(k.right-b.right)};})()")
            check("Diagramm ragt nicht aus seinem Kasten und nutzt die Breite",
                  lage and lage["raus"] <= 0 and lage["breite"] >= lage["kasten"] - 2, json.dumps(lage))
            ue = js(sock, "document.documentElement.scrollWidth - document.documentElement.clientWidth")
            check("kein waagerechter Ueberlauf der Seite", (ue or 0) <= 0, f"{ue} px")
            # Filterzeilen: gleich hohe Felder, Beschriftungen je Zeile auf einer Linie
            mass = js(sock, "(function(){var ids=['tv-zeitraum','tv-gruppe','tv-mass','tv-f-llm','tv-f-benutzer',"
                            "'tv-f-dienst','tv-f-werkzeug','tv-f-kanal'];var h=ids.map(function(i){return Math.round("
                            "document.getElementById(i).getBoundingClientRect().height);});"
                            "var z=Math.round(document.getElementById('tv-zuruecksetzen').getBoundingClientRect().height);"
                            "return {h:h,z:z};})()")
            check("Auswahlfelder und Knopf gleich hoch", mass and max(mass["h"] + [mass["z"]]) - min(mass["h"] + [mass["z"]]) <= 1,
                  json.dumps(mass))
            # Kontraste (Schrift gegen Flaeche, am Bild)
            for name, sel in (("Kachelwert", "#tv-kennzahlen .tv-kachel-wert"),
                              ("Kachelname", "#tv-kennzahlen .tv-kachel-name"),
                              ("Tabellenzahl", "#tv-tbody td.tv-zahl"),
                              ("Hinweis ohne Zaehlung", "#tv-zusatz")):
                k, info = bild_kontrast(sock, sel)
                if k is None:
                    if name == "Hinweis ohne Zaehlung" and not (daten["summe"].get("ohne_angabe") or daten["summe"].get("cache_lesen")):
                        continue
                    check(f"{name} messbar", False, info)
                    continue
                gemessen[(name_daten, thema, name)] = round(k, 2)
                check(f"{name}: Kontrast >= 4,5:1 (gemessen {k:.2f}:1)", k >= 4.5, info)
            # Achsenbeschriftung: SVG-Text, berechnete Fuellfarbe gegen die Flaeche
            # (am Bild ist 11-px-Text zu klein fuer ein Histogramm mit >= 1 %).
            # Hintergrund = erste DECKENDE Flaeche (Alpha 1). Die erste Fassung nahm
            # die 2-%-Toenung rgba(255,255,255,0.02) und rechnete – weil farbe() den
            # Alphawert ignoriert – im dunklen Thema gegen WEISS: 16 FAIL, waehrend
            # der Screenshot alles lesbar zeigte (Register: durchscheinende Flaechen
            # sind kein Hintergrund).
            grund = js(sock, "(function(){for(var e=document.getElementById('tv-diagramm');e;e=e.parentElement){"
                             "var c=getComputedStyle(e).backgroundColor;var m=c.match(/rgba?\\(([^)]+)\\)/);"
                             "if(!m)continue;var t=m[1].split(/[ ,\\/]+/).filter(Boolean);"
                             "if(t.length<4||parseFloat(t[3])>=1)return c;}return null;})()")
            check("Positivkontrolle: deckende Flaeche hinter dem Diagramm gefunden", bool(grund), str(grund))
            grund = grund or "rgb(0,0,0)"
            leg = js(sock, "getComputedStyle(document.querySelector('#tv-legende .tv-legende-eintrag')).color")
            kl = kontrast(farbe(leg), farbe(grund))
            gemessen[(name_daten, thema, "Legende")] = round(kl, 2)
            check(f"Legende: Kontrast >= 4,5:1 (gemessen {kl:.2f}:1)", kl >= 4.5, f"{leg} auf {grund}")
            achse = js(sock, "getComputedStyle(document.querySelector('#tv-diagramm .tv-achsentext')).fill")
            ka = kontrast(farbe(achse), farbe(grund))
            check(f"Achsenbeschriftung: Kontrast >= 4,5:1 (gemessen {ka:.2f}:1)", ka >= 4.5, f"{achse} auf {grund}")
            # Reihenfarben gegen die Flaeche: grafische Objekte >= 3:1 (WCAG 1.4.11)
            fills = js(sock, "(function(){var o={};document.querySelectorAll('#tv-diagramm rect.tv-seg').forEach("
                             "function(r){var k=(r.getAttribute('class')||'').split(' ').pop();o[k]=getComputedStyle(r).fill;});"
                             "return o;})()") or {}
            for kl, f in sorted(fills.items()):
                kf = kontrast(farbe(f), farbe(grund))
                gemessen[(name_daten, thema, kl)] = round(kf, 2)
                check(f"Reihenfarbe {kl}: >= 3:1 gegen die Flaeche (gemessen {kf:.2f}:1)", kf >= 3.0, f"{f} auf {grund}")
            marken = js(sock, "Array.from(document.querySelectorAll('#tv-diagramm text[text-anchor=end]'))"
                              ".map(function(t){return t.textContent;})")
            check("Y-Marken ohne krumme Rundung (kein ',3'/',8' wie bei Vierteln)",
                  marken and not any(re.search(r",[3789]", m) for m in marken), str(marken))
            check("Reihenfarben sind verschieden", len(set(fills.values())) == len(fills), json.dumps(fills))
            # Tooltip: ueber die mittlere Saeule fahren
            pos = js(sock, "(function(){var t=document.querySelectorAll('#tv-diagramm rect.tv-treffer');"
                           "var r=t[Math.floor(t.length/2)];r.scrollIntoView({block:'center'});"
                           "var b=r.getBoundingClientRect();return {x:b.left+b.width/2,y:b.top+b.height/2};})()")
            time.sleep(0.3)
            pos = js(sock, "(function(){var t=document.querySelectorAll('#tv-diagramm rect.tv-treffer');"
                           "var b=t[Math.floor(t.length/2)].getBoundingClientRect();return {x:b.left+b.width/2,y:b.top+b.height/2};})()")
            cdp(sock, "Input.dispatchMouseEvent", type="mouseMoved", x=pos["x"], y=pos["y"])
            time.sleep(0.3)
            tip = js(sock, "(function(){var t=document.getElementById('tv-tipp');if(!t||t.hidden)return null;"
                           "var b=t.getBoundingClientRect(),k=document.getElementById('tv-diagramm').getBoundingClientRect();"
                           "return {zeilen:t.querySelectorAll('.tv-tipp-zeile').length,links:Math.round(b.left-k.left),"
                           "rechts:Math.round(k.right-b.right),bg:getComputedStyle(t).backgroundColor,"
                           "text:t.textContent.slice(0,120)};})()")
            check("Tooltip erscheint beim Ueberfahren", bool(tip), str(tip))
            if tip:
                check("Tooltip bleibt im Diagrammkasten (waagerecht)", tip["links"] >= 0 and tip["rechts"] >= 0, json.dumps(tip))
                check("Tooltip hat eine deckende Flaeche", not re.search(r"rgba\([^)]*,\s*0(\.\d+)?\)", tip["bg"]), tip["bg"])
            r = cdp(sock, "Page.captureScreenshot", format="png")
            if r.get("data"):
                p = BILDER / f"tv-{name_daten}-{thema}.png"
                p.write_bytes(base64.b64decode(r["data"]))
                print(f"       Screenshot: {p}")
            cdp(sock, "Input.dispatchMouseEvent", type="mouseMoved", x=5, y=5)
    hell = {k[2]: v for k, v in gemessen.items() if k[1] == "hell"}
    dunkel = {k[2]: v for k, v in gemessen.items() if k[1] == "dunkel"}
    check("POSITIVKONTROLLE: hell und dunkel sind verschiedene Messungen", hell and hell != dunkel,
          json.dumps({"hell": hell, "dunkel": dunkel}, ensure_ascii=False))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
