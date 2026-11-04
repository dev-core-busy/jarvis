#!/usr/bin/env python3
"""Optische Abnahme: Aktivitaetsprotokoll unter Einstellungen -> Protokolle (Chrome, DEV).

jsdom rechnet kein Layout. Gemessen wird ueber den echten Bedienweg (Reiter
"Protokolle", dann Abschnittskopf "Aktivitaeten") an der AUSGELIEFERTEN Seite
mit ihrem echten CSS; die Daten kommen aus einer fetch-Attrappe VOR dem ersten
Skript (Bauform von live_sicherheitsprotokoll_ui_dev.py), angemeldet wird nicht.
Nur lesend.

Aufruf auf DEV: venv/bin/python tests/live_aktivitaet_ui_dev.py
Screenshots: ~/.jarvis-abnahme/akt-<thema>.png
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


EINTRAEGE = [
    {"ts": 1793784644, "benutzer": "jarvis", "benutzer_anzeige": "jarvis", "bereich": "wissen",
     "aktion": "gruppe_geaendert", "objekt": "contoso",
     "details": {"ip": "192.0.2.15", "rechte": True, "felder": ["editors_users"],
                 "editors_users": "probe.editor"}},
    {"ts": 1793784600, "benutzer": "a.b", "benutzer_anzeige": "FIRMA\\a.b", "bereich": "wissen",
     "aktion": "ordner_angelegt",
     "objekt": "data/rag/Beispiele/ein_sehr_langer_ordnername_ohne_umbruchmoeglichkeit_fuer_die_spalte",
     "details": {"ip": "192.0.2.16", "gruppen": ["contoso", "allgemein"]}},
    {"ts": 1793784500, "benutzer": "jarvis", "bereich": "cron", "aktion": "auftrag_geloescht",
     "objekt": "Wissensabgleich", "details": {"ip": "192.0.2.15", "auftrag": "a1b2c3"}},
    {"ts": 1793784400, "benutzer": "jarvis", "bereich": "skills", "aktion": "skill_konfiguriert",
     "objekt": "sap", "details": {"ip": "192.0.2.15", "felder": ["base_url", "client", "user"]}},
]
DATEN = {"ok": True, "gesamt": 4, "bereiche": ["cron", "skills", "wissen"], "eintraege": EINTRAEGE}

VORLAUF = r"""
window.__fehler = [];
window.__urls = [];
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
    if (url === '/api/logs/aktivitaet') { window.__urls.push(String(u)); return antwort(__DATEN__); }
    return antwort({ ok: true, items: [], skills: [], groups: [], profiles: [], entries: [] });
  };
})();
"""

PROFIL = tempfile.mkdtemp(prefix="chrome-akt-", dir=str(Path.home()))
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


with connect(ws, open_timeout=20, max_size=60_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    gemessen = {}
    skript_id = None
    for thema in ("dunkel", "hell"):
        print(f"\n── {thema} " + "─" * 40)
        cdp(sock, "Emulation.setEmulatedMedia", media="screen", features=[
            {"name": "prefers-color-scheme", "value": "dark" if thema == "dunkel" else "light"}])
        if skript_id:
            cdp(sock, "Page.removeScriptToEvaluateOnNewDocument", identifier=skript_id)
        skript_id = cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
                        source=VORLAUF.replace("__THEMA__", "dark" if thema == "dunkel" else "light")
                        .replace("__DATEN__", json.dumps(DATEN, ensure_ascii=False))).get("identifier")
        cdp(sock, "Page.navigate", url="https://127.0.0.1/settings")
        time.sleep(4)
        reiter = js(sock, "(function(){var b=document.querySelector('[data-settings-tab=\"telemetry\"]');"
                          "if(!b)return 'fehlt'; b.click(); return 'ok';})()")
        time.sleep(0.6)
        kopf = js(sock, "(function(){var h=document.querySelector('[data-plog=\"akt\"]');"
                        "if(!h)return 'fehlt'; h.click(); return 'ok';})()")
        time.sleep(1.5)
        check("Reiter und Abschnittskopf gefunden", reiter == "ok" and kopf == "ok", f"{reiter}/{kopf}")
        flaeche = js(sock, "(function(){var e=document.getElementById('plog-akt-table');if(!e)return 0;"
                           "var r=e.getBoundingClientRect();return Math.round(r.width*r.height);})()")
        check("Tabelle ist sichtbar gemalt (Flaeche > 0)", (flaeche or 0) > 0, str(flaeche))
        maske = js(sock, "(function(){var m=document.getElementById('login-screen')||"
                         "document.querySelector('.login-screen');if(!m)return 'keine';"
                         "return getComputedStyle(m).display==='none'?'zu':'offen';})()")
        check("keine Anmeldemaske ueber der Seite", maske != "offen", str(maske))
        if not (flaeche or 0) > 0 or maske == "offen":
            print("ABBRUCH: Abschnitt nicht sichtbar – Messungen waeren wertlos.")
            print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
            ende(2)
        zeilen = js(sock, "document.querySelectorAll('#plog-akt-tbody tr').length")
        check("vier Zeilen gezeichnet", zeilen == 4, str(zeilen))
        roh = js(sock, "[].slice.call(document.querySelectorAll('#plog-akt-tbody td'))"
                       ".map(function(t){return t.textContent;}).filter(function(t){"
                       "return /plog\\.akt\\./.test(t);})")
        check("kein roher i18n-Schluessel in der Tabelle", not roh, json.dumps(roh, ensure_ascii=False))
        texte = js(sock, "document.getElementById('plog-akt-tbody').textContent")
        check("Aktion in Klartext ('Wissensgruppe geändert' / 'Knowledge group changed')",
              ("Wissensgruppe geändert" in (texte or "")) or ("Knowledge group changed" in (texte or "")),
              (texte or "")[:200])
        check("Rechte-Marke 'Berechtigung' in der Zeile der Rechteaenderung",
              js(sock, "(function(){var tr=document.querySelector('#plog-akt-tbody tr');"
                       "return !!tr && /Berechtigung|Permission/.test(tr.textContent) "
                       "&& tr.classList.contains('sprot-zeile-warn');})()"))
        check("IP in der Spalte Herkunft",
              js(sock, "(function(){var tr=document.querySelector('#plog-akt-tbody tr');"
                       "return !!tr && tr.lastElementChild.textContent==='192.0.2.15';})()"))
        opts = js(sock, "[].slice.call(document.querySelectorAll('#plog-akt-bereich option'))"
                        ".map(function(o){return o.value+'='+o.textContent;})")
        check("Bereichsauswahl aus der Antwort gefuellt (Alle + 3)", opts and len(opts) == 4, json.dumps(opts,
              ensure_ascii=False))
        js(sock, "(function(){var s=document.getElementById('plog-akt-bereich');s.value='wissen';"
                 "s.dispatchEvent(new Event('change',{bubbles:true}));})()")
        time.sleep(1.0)
        letzte = js(sock, "window.__urls[window.__urls.length-1]||''")
        check("Bereichswahl geht als Filter an den Server", "bereich=wissen" in (letzte or ""), letzte)
        check("die Auswahl bleibt nach dem Neuzeichnen stehen",
              js(sock, "document.getElementById('plog-akt-bereich').value") == "wissen")
        fehler = js(sock, "(window.__fehler||[]).filter(function(f){return /protokolle|"
                          "settings_bedienung|telemetry/.test(f);}).join(' | ')")
        check("keine JS-Fehler aus den beteiligten Modulen", not fehler, fehler or "")
        for name, sel in (("Marke Warnung", "#plog-akt-tbody .sprot-art-warn"),
                          ("Marke neutral", "#plog-akt-tbody .sprot-art-neutral"),
                          ("Details-Text", "#plog-akt-tbody .plog-text")):
            k, info = bild_kontrast(sock, sel)
            if k is None:
                check(f"{name} messbar", False, info)
                continue
            gemessen[(thema, name)] = round(k, 2)
            check(f"{name}: Kontrast >= 4,5:1 (gemessen {k:.2f}:1)", k >= 4.5, info)
        mass = js(sock, "(function(){var h=['plog-akt-bereich','plog-akt-benutzer','plog-akt-suche',"
                        "'plog-akt-apply'].map(function(i){return Math.round("
                        "document.getElementById(i).getBoundingClientRect().height);});return h;})()")
        check("Filterfelder gleich hoch", mass and max(mass) - min(mass) <= 1, json.dumps(mass))
        ue = js(sock, "document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check("kein waagerechter Ueberlauf der Seite", (ue or 0) <= 0, f"{ue} px")
        js(sock, "(function(){var e=document.querySelector('[data-plog=\"akt\"]');"
                 "if(e)e.scrollIntoView({block:'start'});})()")
        time.sleep(0.4)
        r = cdp(sock, "Page.captureScreenshot", format="png")
        if r.get("data"):
            p = BILDER / f"akt-{thema}.png"
            p.write_bytes(base64.b64decode(r["data"]))
            print(f"       Screenshot: {p}")
    hell = {k[1]: v for k, v in gemessen.items() if k[0] == "hell"}
    dunkel = {k[1]: v for k, v in gemessen.items() if k[0] == "dunkel"}
    check("POSITIVKONTROLLE: hell und dunkel sind verschiedene Messungen", hell and hell != dunkel,
          json.dumps({"hell": hell, "dunkel": dunkel}, ensure_ascii=False))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
