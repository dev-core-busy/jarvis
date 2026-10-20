"""Optische Abnahme: weitere Protokolle im Reiter "Protokolle" (Chrome, DEV).

Sechs Abschnitte (Dienst-Journal, CSP, Update-Verlauf, SSH, Selbstkorrekturen,
Abhaengigkeiten) plus die Filterzeile des Tool-Audit-Logs (Korrektur der
Feldhoehe, 2026-10-20). Gemessen ueber den echten Bedienweg; `fetch` steht vor
dem ersten Skript. Daten: ``PLOG_DATEN`` (JSON, z. B. echte Antworten des
Dienstes) oder die eingebaute Probe. Screenshots: ~/.jarvis-abnahme/plog-*.png
Aufruf auf DEV: venv/bin/python tests/live_protokolle_ui_dev.py
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



PROBE = {
    "journal": {"ok": True, "gekappt": 0, "eintraege": [
        {"zeit": "2026-10-20T17:28:04+02:00", "prozess": "start_jarvis.sh",
         "text": "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: kaputt"},
        {"zeit": "2026-10-20T17:28:03+02:00", "prozess": "start_jarvis.sh", "text": "[AUTH] Warnung"}]},
    "csp": {"modus": "erzwingen", "berichte": [
        {"ts": 1792505727, "seite": "/settings", "direktive": "script-src", "blockiert": "inline",
         "quelle": "/static/js/app.js", "zeile": "12", "anzahl_seit_start": 3, "browser": "Chrome"}]},
    "updates": {"ok": True, "stand": {"hash": "df2e800", "datum": "2026-10-20T18:00:00+02:00", "titel": "feat: x"},
                "eintraege": [{"ts": 1792505800, "art": "update_knopf", "benutzer": "a.b", "ok": False,
                               "vorher": "aaa1111", "nachher": "aaa1111", "fehler": "Signatur fehlt"},
                              {"ts": 1792505700, "art": "stand_geaendert", "vorher": "bbb2222", "nachher": "ccc3333",
                               "titel": "feat: y", "vorgespult": True, "commits": [{"hash": "ccc3333", "titel": "feat: y"}]}]},
    "ssh": {"ok": True, "tage": 7, "art": "", "gekappt": 0, "anzahl": {"angenommen": 2, "fehlgeschlagen": 1, "unbekannt": 0},
            "eintraege": [{"zeit": "2026-10-08T19:11:28+02:00", "art": "fehlgeschlagen", "methode": "password",
                           "konto": "root", "ip": "192.0.2.12", "schluessel": ""},
                          {"zeit": "2026-10-06T19:22:45+02:00", "art": "angenommen", "methode": "publickey",
                           "konto": "root", "ip": "192.0.2.10", "schluessel": "RSA SHA256:abc"}]},
    "fixes": {"ok": True, "vorhanden": False, "eintraege": [], "anzahl": 0},
    "abh": {"ok": True, "vorhanden": True, "alter_s": 900, "zustand": {"zeit": "2026-10-20T16:16:42", "fehler": "",
            "offen": [{"paket": "jinja2", "version": "3.1.4", "id": "GHSA-xxxx", "behoben_in": "3.1.5"}],
            "geaendert": [], "ausgenommen": ["PYSEC-2026-1", "GHSA-yyyy"]}},
}
DATEN = json.loads(Path(os.environ["PLOG_DATEN"]).read_text()) if os.environ.get("PLOG_DATEN") else PROBE
PFADE = {"/api/logs/journal": "journal", "/api/security/csp": "csp", "/api/logs/updates": "updates",
         "/api/logs/ssh": "ssh", "/api/logs/code_fixes": "fixes", "/api/logs/abhaengigkeiten": "abh"}

VORLAUF = r"""
window.__fehler = [];
window.addEventListener('error', function (e) { window.__fehler.push((e.filename || '?') + ': ' + e.message); });
try { localStorage.setItem('jarvis_token', 'probe'); localStorage.setItem('jarvis_theme', '__THEMA__'); } catch (e) {}
(function () {
  var DATEN = __DATEN__, PFADE = __PFADE__;
  function antwort(d) {
    return Promise.resolve({ ok: true, status: 200, headers: { get: function () { return null; } },
      json: function () { return Promise.resolve(d); }, text: function () { return Promise.resolve(JSON.stringify(d)); } });
  }
  window.fetch = function (u) {
    var url = String(u).split('?')[0];
    if (url === '/api/me') { return antwort({ is_admin: true, username: 'probe', permissions: {} }); }
    if (url === '/api/verify-token') { return antwort({ valid: true, username: 'probe', is_admin: true }); }
    if (PFADE[url]) { return antwort(DATEN[PFADE[url]]); }
    if (url === '/api/audit_log') { return antwort([]); }
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
    for thema in ("dunkel", "hell"):
        print(f"\n── {thema} " + "─" * 50)
        cdp(sock, "Emulation.setEmulatedMedia", media="screen", features=[
            {"name": "prefers-color-scheme", "value": "dark" if thema == "dunkel" else "light"}])
        if skript_id:
            cdp(sock, "Page.removeScriptToEvaluateOnNewDocument", identifier=skript_id)
        skript_id = cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
                        source=VORLAUF.replace("__THEMA__", "dark" if thema == "dunkel" else "light")
                        .replace("__DATEN__", json.dumps(DATEN, ensure_ascii=False))
                        .replace("__PFADE__", json.dumps(PFADE))).get("identifier")
        cdp(sock, "Page.navigate", url="https://127.0.0.1/settings")
        time.sleep(4)
        name = js(sock, "(function(){var b=document.querySelector('[data-settings-tab=\"telemetry\"]');"
                        "if(!b)return null; b.click(); return b.textContent.trim();})()")
        check("Reiter heisst \"Protokolle\"", name == "Protokolle", str(name))
        time.sleep(0.6)
        js(sock, "(function(){var h=document.querySelector('[data-klick=\"audit-klappen\"]');if(h)h.click();})()")
        for n in ("journal", "csp", "updates", "ssh", "fixes", "abh"):
            js(sock, "(function(){var h=document.querySelector('[data-plog=\"%s\"]');if(h)h.click();})()" % n)
        time.sleep(1.5)
        maske = js(sock, "(function(){var m=document.getElementById('login-screen');"
                         "return m && getComputedStyle(m).display!=='none' ? 'offen':'zu';})()")
        check("keine Anmeldemaske", maske != "offen", str(maske))
        flaechen = js(sock, "(function(){return ['journal','csp','updates','ssh','fixes','abh'].map(function(n){"
                            "var e=document.getElementById('plog-'+n+'-table');if(!e)return 0;"
                            "var r=e.getBoundingClientRect();return Math.round(r.width*r.height);});})()")
        check("alle sechs Tabellen gemalt", flaechen and all(f > 0 for f in flaechen), str(flaechen))
        if not flaechen or not all(f > 0 for f in flaechen) or maske == "offen":
            print("ABBRUCH: Abschnitte nicht sichtbar – Kontraste waeren keine Messung.")
            print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
            ende(2)
        zeilen = js(sock, "(function(){var o={};['journal','csp','updates','ssh','fixes','abh'].forEach(function(n){"
                          "o[n]=document.querySelectorAll('#plog-'+n+'-tbody tr').length;});return o;})()")
        check("Zeilen gezeichnet", all(v >= 1 for v in zeilen.values()), json.dumps(zeilen))
        fehler = js(sock, "(window.__fehler||[]).filter(function(f){return /protokolle|settings_bedienung/.test(f);}).join(' | ')")
        check("keine JS-Fehler aus den beteiligten Modulen", not fehler, fehler or "")
        for titel, sel in (("Journal-Text", "#plog-journal-tbody .plog-text"),
                           ("Markierung (SSH)", "#plog-ssh-tbody .sprot-art"),
                           ("Markierung (Abhaengigkeiten)", "#plog-abh-tbody .sprot-art"),
                           ("Statuszeile (Abhaengigkeiten)", "#plog-abh-status"),
                           ("Leertext (Selbstkorrekturen)", "#plog-fixes-tbody .audit-empty")):
            k, info = bild_kontrast(sock, sel)
            if k is None:
                check(f"{titel} messbar", False, info)
                continue
            gemessen[(thema, titel)] = round(k, 2)
            check(f"{titel}: Kontrast >= 4,5:1 (gemessen {k:.2f}:1)", k >= 4.5, info)
        # c) Filterzeilen: gleich hohe Felder, Beschriftungen auf einer Linie
        for gruppe, felder in (("Tool-Audit-Log", ["audit-filter-user", "audit-filter-tool", "audit-limit", "audit-apply-btn"]),
                               ("Dienst-Journal", ["plog-journal-einheit", "plog-journal-stufe", "plog-journal-zeitraum",
                                                   "plog-journal-suche", "plog-journal-apply"]),
                               ("SSH", ["plog-ssh-tage", "plog-ssh-art", "plog-ssh-apply"])):
            js(sock, "document.getElementById('%s').scrollIntoView({block:'center'})" % felder[0])
            mass = js(sock, "(function(ids){return ids.map(function(i){var e=document.getElementById(i);"
                            "return e?Math.round(e.getBoundingClientRect().height):-1;});})(%s)" % json.dumps(felder))
            check(f"{gruppe}: Filterfelder gleich hoch {mass}", mass and min(mass) > 0 and max(mass) - min(mass) <= 1)
        audit_l = js(sock, "['audit-filter-user','audit-filter-tool'].map(function(i){return Math.round("
                           "document.querySelector('label[for=\"'+i+'\"]').getBoundingClientRect().top);})")
        check(f"Tool-Audit-Log: Beschriftungen auf einer Linie {audit_l}", audit_l and max(audit_l) - min(audit_l) <= 1)
        # Vorgabe 2026-10-20: kein globales "Zuruecksetzen", keine Kopfzeile dazu
        weg = js(sock, "[!document.getElementById('btn-tele-clear'), !document.getElementById('tele-reset-info')]")
        check("kein Knopf \"Zuruecksetzen\", keine Kopfzeile \"Zuletzt zurueckgesetzt\"", weg == [True, True], str(weg))
        for stelle, sel in (("kopf", "#settings-tab-telemetry"), ("fuss", "#btn-tele-refresh")):
            js(sock, "(function(){var e=document.querySelector('%s');if(e)e.scrollIntoView({block:'%s'});})()"
               % (sel, "start" if stelle == "kopf" else "end"))
            time.sleep(0.3)
            r = cdp(sock, "Page.captureScreenshot", format="png")
            if r.get("data"):
                (BILDER / f"plog-{stelle}-{thema}.png").write_bytes(base64.b64decode(r["data"]))
        ue = js(sock, "document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check("kein waagerechter Ueberlauf der Seite", (ue or 0) <= 0, f"{ue} px")
        for n in ("audit", "journal", "updates", "ssh", "abh"):
            sel = "[data-klick=\"audit-klappen\"]" if n == "audit" else "[data-plog=\"%s\"]" % n
            js(sock, "(function(){var e=document.querySelector('%s');if(e)e.scrollIntoView({block:'start'});})()" % sel)
            time.sleep(0.3)
            r = cdp(sock, "Page.captureScreenshot", format="png")
            if r.get("data"):
                p = BILDER / f"plog-{n}-{thema}.png"
                p.write_bytes(base64.b64decode(r["data"]))
    hell = {k[1]: v for k, v in gemessen.items() if k[0] == "hell"}
    dunkel = {k[1]: v for k, v in gemessen.items() if k[0] == "dunkel"}
    check("POSITIVKONTROLLE: hell und dunkel sind verschiedene Messungen", hell and hell != dunkel,
          json.dumps({"hell": hell, "dunkel": dunkel}, ensure_ascii=False))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
