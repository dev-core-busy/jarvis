#!/usr/bin/env python3
"""Optische Abnahme: Sicherheitsprotokoll im Telemetrie-Reiter (Chrome, DEV).

jsdom rechnet kein Layout – ob Markierungen, Kettenzeile und Tabelle in BEIDEN
Themen lesbar sind, zeigt nur die ausgelieferte Seite mit ihrem echten CSS.
Gemessen wird ueber den echten Bedienweg: Reiter "Telemetry" anklicken, dann
den Abschnittskopf. `fetch` und `localStorage` stehen VOR dem ersten Skript
(`Page.addScriptToEvaluateOnNewDocument`), angemeldet wird nicht.

Zwei Zustaende je Thema: Kette intakt und Kette gebrochen.
Aufruf auf DEV: venv/bin/python tests/live_sicherheitsprotokoll_ui_dev.py
Screenshots: ~/.jarvis-abnahme/sprot-<zustand>-<thema>.png
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
    {"ts": 1792505727, "art": "anmeldung_fehlgeschlagen", "benutzer": "", "ip": "127.0.0.1",
     "ergebnis": "503", "details": {"weg": "windows", "grund": "Die Windows-Anmeldung ist auf diesem "
                                    "Server nicht eingerichtet (keine Keytab unter /opt/jarvis/data/"
                                    "kerberos/http.keytab)."}},
    {"ts": 1792505000, "art": "anmeldung", "benutzer": "a.b", "benutzer_anzeige": "FIRMA\\a.b",
     "ip": "192.0.2.7", "ergebnis": "erfolg", "details": {"weg": "kennwort"}},
    {"ts": 1792504000, "art": "admin_aenderung", "benutzer": "jarvis", "ip": "192.0.2.8",
     "ergebnis": "200", "details": {"methode": "POST", "pfad": "/api/settings/branding"}},
    {"ts": 1792503000, "art": "konto_gesperrt", "benutzer": "c.d", "ip": "192.0.2.66",
     "ergebnis": "gesperrt", "details": {"dauer_s": 900}},
    {"ts": 1792502000, "art": "dienst_start", "benutzer": "", "ip": "", "ergebnis": "",
     "details": {}},
]
ARTEN = sorted({e["art"] for e in EINTRAEGE})
INTAKT = {"ok": True, "eintraege": EINTRAEGE, "arten": ARTEN,
          "kette": {"ok": True, "zeilen": 1073, "brueche": [], "anzahl_brueche": 0},
          "aufbewahrung_tage": 365, "syslog": True, "schreibfehler": {"datei": 0}}
BRUCH = dict(INTAKT, kette={"ok": False, "zeilen": 1073, "anzahl_brueche": 2,
                            "brueche": [{"zeile": 17, "grund": "Inhalt veraendert"},
                                        {"zeile": 18, "grund": "Kette unterbrochen"}]})

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
    // app.js prueft die Sitzung hierueber; ohne {valid:true} liegt die
    // Anmeldemaske ueber der Seite und JEDE Messung darunter ist wertlos
    // (erster Lauf: Flaeche 0, Kontraste von unsichtbaren Elementen).
    if (url === '/api/verify-token') { return antwort({ valid: true, username: 'probe', is_admin: true }); }
    if (url === '/api/security/log') { return antwort(__DATEN__); }
    return antwort({ ok: true, items: [], skills: [], groups: [], profiles: [], entries: [] });
  };
})();
"""

PROFIL = tempfile.mkdtemp(prefix="chrome-sprot-", dir=str(Path.home()))
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
    for zustand, daten in (("intakt", INTAKT), ("bruch", BRUCH)):
        for thema in ("dunkel", "hell"):
            print(f"\n── {zustand} / {thema} " + "─" * 40)
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
            kopf = js(sock, "(function(){var h=document.querySelector('[data-klick=\"sprot-klappen\"]');"
                            "if(!h)return 'fehlt'; h.click(); return 'ok';})()")
            time.sleep(1.2)
            # ── Positivkontrollen ──
            check("Reiter und Abschnittskopf gefunden", reiter == "ok" and kopf == "ok", f"{reiter}/{kopf}")
            flaeche = js(sock, "(function(){var e=document.getElementById('sprot-table');if(!e)return 0;"
                               "var r=e.getBoundingClientRect();return Math.round(r.width*r.height);})()")
            check("Tabelle ist sichtbar gemalt (Flaeche > 0)", (flaeche or 0) > 0, str(flaeche))
            maske = js(sock, "(function(){var m=document.getElementById('login-screen')||"
                             "document.querySelector('.login-screen');if(!m)return 'keine';"
                             "return getComputedStyle(m).display==='none'?'zu':'offen';})()")
            check("keine Anmeldemaske ueber der Seite", maske != "offen", str(maske))
            if not (flaeche or 0) > 0 or maske == "offen":
                print("ABBRUCH: Abschnitt nicht sichtbar – Kontraste waeren keine Messung.")
                print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
                ende(2)
            zeilen = js(sock, "document.querySelectorAll('#sprot-tbody tr').length")
            check("fuenf Zeilen gezeichnet", zeilen == 5, str(zeilen))
            fehler = js(sock, "(window.__fehler||[]).filter(function(f){return /sicherheitsprotokoll|"
                              "settings_bedienung/.test(f);}).join(' | ')")
            check("keine JS-Fehler aus den beteiligten Modulen", not fehler, fehler or "")
            # ── Kontraste ──
            ziele = [("Markierung Fehlschlag", "#sprot-tbody .sprot-art-warn"),
                     ("Markierung Erfolg", "#sprot-tbody .sprot-art-ok"),
                     ("Markierung neutral", "#sprot-tbody .sprot-art-neutral"),
                     ("Details-Text", "#sprot-tbody .audit-arg-val"),
                     ("Kettenzeile", "#sprot-kette > div")]
            for name, sel in ziele:
                k, info = bild_kontrast(sock, sel)
                if k is None:
                    check(f"{name} messbar", False, info)
                    continue
                gemessen[(zustand, thema, name)] = round(k, 2)
                check(f"{name}: Kontrast >= 4,5:1 (gemessen {k:.2f}:1)", k >= 4.5, info)
            # Filterzeile: gleich hohe Felder, Beschriftungen auf einer Linie
            # (erster Lauf: "Ereignis" stand hoeher, die "200" war abgeschnitten).
            mass = js(sock, "(function(){var h=['sprot-filter-art','sprot-filter-user','sprot-filter-ip',"
                            "'sprot-limit','sprot-apply-btn'].map(function(i){return Math.round("
                            "document.getElementById(i).getBoundingClientRect().height);});"
                            "var l=['sprot-filter-art','sprot-filter-user','sprot-filter-ip'].map(function(i){"
                            "return Math.round(document.querySelector('label[for=\"'+i+'\"]')"
                            ".getBoundingClientRect().top);});return {h:h,l:l};})()")
            check("Filterfelder gleich hoch", mass and max(mass["h"]) - min(mass["h"]) <= 1, json.dumps(mass))
            check("Beschriftungen auf einer Linie", mass and max(mass["l"]) - min(mass["l"]) <= 1, json.dumps(mass))
            klasse = js(sock, "document.getElementById('sprot-kette').className")
            check("Kettenzustand an der Klasse", ("sprot-kette-bruch" if zustand == "bruch" else "sprot-kette-ok")
                  in (klasse or ""), klasse)
            ue = js(sock, "document.documentElement.scrollWidth - document.documentElement.clientWidth")
            check("kein waagerechter Ueberlauf der Seite", (ue or 0) <= 0, f"{ue} px")
            js(sock, "(function(){var e=document.querySelector('[data-klick=\"sprot-klappen\"]');"
                     "if(e)window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 20);})()")
            time.sleep(0.4)
            r = cdp(sock, "Page.captureScreenshot", format="png")
            if r.get("data"):
                p = BILDER / f"sprot-{zustand}-{thema}.png"
                p.write_bytes(base64.b64decode(r["data"]))
                print(f"       Screenshot: {p}")
    hell = {k[2]: v for k, v in gemessen.items() if k[1] == "hell"}
    dunkel = {k[2]: v for k, v in gemessen.items() if k[1] == "dunkel"}
    check("POSITIVKONTROLLE: hell und dunkel sind verschiedene Messungen", hell and hell != dunkel,
          json.dumps({"hell": hell, "dunkel": dunkel}, ensure_ascii=False))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
