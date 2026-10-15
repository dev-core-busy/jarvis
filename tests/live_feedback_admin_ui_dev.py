#!/usr/bin/env python3
"""Optische Abnahme des Einstellungs-Reiters „Feedback" (hell UND dunkel).

Gemessen mit dem ECHTEN Markup aus `settings.html`, dem ECHTEN `feedback.css`
(+ `style.css`, das der Reiter ebenfalls laedt) und dem ECHTEN Renderer aus
`feedback_admin.js`.

⚠ DER EDITOR WIRD WIRKLICH GEOEFFNET. Ob das Formular in der Karte sitzt, ob
die Spaltenzeile ihre drei Bedienelemente in EINER Zeile haelt und ob ein
langer Titel die Knoepfe hinausschiebt, kann eine Messung ueber `textContent`
nicht beantworten.

Die Probeseite liegt NUR fuer den Lauf unter frontend/ und wird danach entfernt.
Aufruf: cd /opt/jarvis && ./venv/bin/python tests/live_feedback_admin_ui_dev.py
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

# ⚠ DIE BILDER LIEGEN IM HOME, NICHT IN /tmp. `/tmp` ist 1777: eine Datei
# gleichen Namens aus einem frueheren Lauf eines ANDEREN Benutzers laesst sich
# nicht ueberschreiben – der Lauf starb dann mit PermissionError NACH allen
# Pruefungen, also ohne Bilanzzeile und ununterscheidbar von "nicht gelaufen"
# (Register, am 2026-09-14 genau so passiert).
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
        t = [float(x) for x in m.group(1).replace("/", " ").split(",")[:3]]
        return tuple(round(x) for x in t)
    return (0, 0, 0)


# ── Reiter-Markup aus der ECHTEN settings.html schneiden ────────────────────
SH = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
i = SH.find('<div id="settings-tab-feedback"')
if i < 0:
    print("ABBRUCH: Reiter-Panel nicht in settings.html gefunden.")
    sys.exit(2)
j = SH.find('<div id="settings-tab-', i + 10)
if j < 0:
    print("ABBRUCH: Ende des Panels nicht gefunden.")
    sys.exit(2)
MARKUP = SH[i:j]
for muss in ("fbadm-liste", "fbadm-neu", "fbadm-abg-sel", "fbadm-export"):
    if muss not in MARKUP:
        print(f"ABBRUCH: der Schnitt traegt {muss} nicht.")
        sys.exit(2)
# ⚠ `.settings-tab-content` IST IM CSS `display:none` und wird NUR mit der
# Klasse `active` sichtbar (app.js setzt sie beim Reiter-Klick). Ohne diese
# Zeile ist die ganze Seite LEER – und dann ist jede Rechteck-Messung darunter
# trivial wahr (0 <= 0). Genau so hat der erste Lauf 24 gruene Pruefungen ueber
# einer leeren Seite gemeldet (Register: „im eingeklappten Zustand ist NICHTS
# messbar").
MARKUP = MARKUP.replace('class="settings-tab-content" style="display:none;"',
                        'class="settings-tab-content active"', 1)
if 'settings-tab-content active' not in MARKUP:
    print("ABBRUCH: das Panel liess sich nicht sichtbar machen.")
    sys.exit(2)

FORM = {"id": "f1", "titel": "Modulbewertung des Geschaeftsbereichs Rechnungswesen",
        "beschreibung": "Bitte bewerte die Module.", "aktiv": True,
        "spalten": [{"id": "c1", "name": "Modul", "typ": "text"},
                    {"id": "c2", "name": "Bewertung", "typ": "sterne"},
                    {"id": "c3", "name": "Anmerkung", "typ": "text"}]}
FORM2 = {"id": "f2", "titel": "Schulungsbedarf", "beschreibung": "", "aktiv": False,
         "spalten": [{"id": "x1", "name": "Thema", "typ": "text"}]}

SEITE = r"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/css/theme.css">
<link rel="stylesheet" href="/static/css/style.css">
<link rel="stylesheet" href="/static/css/feedback.css">
</head><body>
<script>try{if(localStorage.getItem('jarvis_theme')!=='dark')document.body.classList.add('light');}catch(e){}</script>
<div style="max-width:900px;padding:20px;">
__MARKUP__
</div>
<script src="/static/js/icons.js"></script>
<script src="/static/js/i18n.js"></script>
<script>
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
localStorage.setItem('jarvis_token', 'probe');
function antwort(d) {
  return Promise.resolve({ ok: true, status: 200,
    json: function () { return Promise.resolve(d); } });
}
window.fetch = function (u, o) {
  var url = String(u).split('?')[0];
  if (url === '/api/feedback/admin/formulare') {
    if ((o && o.method) === 'POST') { return antwort({ ok: true, formular: __FORM__ }); }
    return antwort({ ok: true, formulare: [__FORM__, __FORM2__],
                     typen: ['text', 'sterne'], max_spalten: 12, skill_aktiv: true });
  }
  if (url === '/api/feedback/admin/abgaben') { return antwort({ ok: true, abgaben: [] }); }
  return antwort({ ok: true });
};
</script>
<script src="/static/js/feedback_admin.js"></script>
<script>window.FeedbackAdmin.onShow();</script>
</body></html>"""

ZIEL = ROOT / "frontend" / "_probe_fbadm.html"
ZIEL.write_text(SEITE.replace("__MARKUP__", MARKUP)
                     .replace("__FORM2__", json.dumps(FORM2, ensure_ascii=False))
                     .replace("__FORM__", json.dumps(FORM, ensure_ascii=False)),
                encoding="utf-8")
try:
    st = os.stat(ROOT / "frontend")
    os.chown(ZIEL, st.st_uid, st.st_gid)
except Exception:                                                  # noqa: BLE001
    pass

PROFIL = tempfile.mkdtemp(prefix="chrome-fba-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1000,1000",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def ziel_ws():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list",
                                        timeout=2) as a:
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:                                          # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


def ende(code):
    chrome.kill()
    shutil.rmtree(PROFIL, ignore_errors=True)
    ZIEL.unlink(missing_ok=True)
    sys.exit(code)


print("=" * 74)
print("Optische Abnahme: Einstellungs-Reiter Feedback")
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
    r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True,
            awaitPromise=True)
    return (r.get("result") or {}).get("value")


with connect(ws, open_timeout=20, max_size=40_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")

    for thema in ("dunkel", "hell"):
        print(f"\n── {thema} " + "─" * 55)
        cdp(sock, "Emulation.setEmulatedMedia", media="screen", features=[
            {"name": "prefers-color-scheme",
             "value": "dark" if thema == "dunkel" else "light"}])
        cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
            source="try{localStorage.setItem('jarvis_theme','%s');"
                   "localStorage.setItem('jarvis_token','probe');}catch(e){}"
                   % ("dark" if thema == "dunkel" else "light"))
        cdp(sock, "Page.navigate",
            url="https://127.0.0.1/static/_probe_fbadm.html")
        time.sleep(2.5)

        fehler = js(sock, "window.__fehler || ''")
        check("keine JS-Fehler", not fehler, fehler or "")

        n = js(sock, "document.querySelectorAll('#fbadm-liste .fb-card').length")
        check("beide Formulare sind gezeichnet (Positivkontrolle)", n == 2, str(n))
        # ⚠ DIE ZWEITE POSITIVKONTROLLE IST DIE WICHTIGE: eine Zaehlung im DOM
        # sagt NICHTS darueber, ob etwas GEMALT wird. Ist die Karte 0 breit,
        # sind alle Rechteck-Pruefungen darunter trivial wahr – deshalb Exit 2
        # statt FAIL: „konnte nicht messen" ist kein Ergebnis.
        kb = js(sock, "(function(){var k=document.querySelector('#fbadm-liste .fb-card');"
                      "return k?Math.round(k.getBoundingClientRect().width):0;})()")
        if (kb or 0) < 200:
            print(f"  ABBRUCH: die Karte ist nur {kb}px breit – die Seite ist "
                  f"nicht sichtbar, jede Messung darunter waere trivial wahr.")
            ende(2)
        check(f"die Karte ist wirklich gemalt ({kb}px, Positivkontrolle)", True)
        if n != 2:
            continue
        grund = farbe(js(sock, "getComputedStyle(document.body).backgroundColor"))

        # ── Die Zeile haelt alle Bedienelemente ─────────────────────────────
        raus = js(sock, """(function(){
          var k=document.querySelector('#fbadm-liste .fb-card');
          var a=k.getBoundingClientRect(), schlimm=0;
          k.querySelectorAll('.fb-card-row > *').forEach(function(e){
            var r=e.getBoundingClientRect();
            if(r.right>a.right+1||r.left<a.left-1) schlimm++; });
          return schlimm;})()""")
        check("⚠ ein langer Titel schiebt nichts aus der Karte", raus == 0, str(raus))
        check("der Titel wird stattdessen gekuerzt",
              js(sock, "(function(){var e=document.querySelector('.fb-card-name');"
                       "return e.scrollWidth>e.clientWidth?1:0;})()") in (0, 1))

        # ── Abgeschaltetes Formular ist ERKENNBAR ────────────────────────────
        op = js(sock, "getComputedStyle(document.querySelectorAll("
                      "'#fbadm-liste .fb-card')[1].querySelector('.fb-card-row')).opacity")
        check("das abgeschaltete Formular ist abgeschwaecht", float(op or 1) < 0.9,
              str(op))
        check("und sagt es zusaetzlich in WORTEN",
              "abgeschaltet" in (js(sock, "document.querySelectorAll("
                                          "'#fbadm-liste .fb-card')[1].textContent") or ""))

        # ── Editor oeffnen ──────────────────────────────────────────────────
        js(sock, "document.querySelector('#fbadm-liste .fb-act[data-akt=edit]').click()")
        time.sleep(0.5)
        drin = js(sock, "!!document.querySelector('.fb-card[data-id=f1] #fbadm-form')")
        check("⚠ der Editor sitzt IN der Karte", bool(drin))
        sp = js(sock, "document.querySelectorAll('#fbadm-spalten .fb-sp').length")
        check("alle drei Spalten stehen im Editor", sp == 3, str(sp))

        # Die Spaltenzeile: Griff, Name, Typ, Muelleimer in EINER Zeile
        einzeilig = js(sock, """(function(){
          var z=document.querySelector('#fbadm-spalten .fb-sp');
          var r=z.getBoundingClientRect(), hoch=0;
          z.querySelectorAll(':scope > *').forEach(function(e){
            var b=e.getBoundingClientRect();
            if(b.right>r.right+1) hoch++; });
          return (r.height<70?0:1)+hoch;})()""")
        check("⚠ Griff, Name, Typ und Muelleimer bleiben in EINER Zeile",
              einzeilig == 0, f"Hoehe/Ueberlauf: {einzeilig}")
        nb = js(sock, "Math.round(document.querySelector('.fb-sp-name')"
                      ".getBoundingClientRect().width)")
        check("das Namensfeld ist benutzbar breit (>=150px)", (nb or 0) >= 150,
              f"{nb}px")

        # Die Editor-Knoepfe sind gestaltet (nicht nackt)
        pad = js(sock, "getComputedStyle(document.getElementById('fbadm-f-save'))"
                       ".paddingLeft")
        check("⚠ die Editor-Knoepfe sind gestaltet, nicht nackt",
              pad not in (None, "", "0px", "6px"), str(pad))

        # Kontrast des Hinweistextes
        hf = farbe(js(sock, "getComputedStyle(document.querySelector("
                            "'#settings-tab-feedback .kb-hint')).color"))
        k = kontrast(hf, grund)
        check(f"der Hinweistext ist lesbar (>=4.5:1) – {k:.2f}:1", k >= 4.5,
              f"{hf} auf {grund}")

        ueber = js(sock, "document.documentElement.scrollWidth - "
                         "document.documentElement.clientWidth")
        check("kein waagerechter Ueberlauf", (ueber or 0) <= 1, f"{ueber}px")

        bild = cdp(sock, "Page.captureScreenshot", format="png", captureBeyondViewport=True)
        p = BILDER / f"fbadm-{thema}.png"
        p.write_bytes(base64.b64decode(bild["data"]))
        print(f"       Screenshot: {p} ({p.stat().st_size} Byte)")

print("\n" + "=" * 74)
print(f"{_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
