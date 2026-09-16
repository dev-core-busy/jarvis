#!/usr/bin/env python3
"""Optische Abnahme des Feedback-Bereichs (hell UND dunkel).

jsdom rechnet kein Layout. Gemessen wird mit dem ECHTEN `feedback.css`, dem
ECHTEN Markup aus `feedback.html` und dem ECHTEN Renderer aus `feedback.js`.

Geprueft wird, was eine Messung ueber `textContent` grundsaetzlich NICHT sehen
kann: Ueberlauf, Ueberlappung, Kontrast, und ob ein Stern nach dem Klick
wirklich anders AUSSIEHT.

Die Probeseite liegt NUR fuer den Lauf unter frontend/ und wird danach entfernt
(sie wuerde sonst `test_theme_default` brechen – Register).

Aufruf: cd /opt/jarvis && ./venv/bin/python tests/live_feedback_ui_dev.py
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
sys.path.insert(0, str(ROOT))

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


# ── Markup aus der ECHTEN feedback.html schneiden ───────────────────────────
FH = (ROOT / "frontend" / "feedback.html").read_text(encoding="utf-8")
i = FH.find('<section class="ja-card" data-klapp="form">')
if i < 0:
    print("ABBRUCH: Formular-Container nicht in feedback.html gefunden.")
    sys.exit(2)
j = FH.find("</section>", FH.find('id="fb-status"', i))
if j < 0:
    print("ABBRUCH: Ende des Formular-Containers nicht gefunden.")
    sys.exit(2)
MARKUP = FH[i:j + 10]
for muss in ("fb-tabelle", "fb-senden", "fb-zeile-neu", "fb-pick"):
    if muss not in MARKUP:
        print(f"ABBRUCH: der Schnitt traegt {muss} nicht.")
        sys.exit(2)
# Der Container fuer die eigenen Abgaben gehoert mit dazu.
i2 = FH.find('<section class="ja-card" id="fb-meine-card"')
j2 = FH.find("</section>", FH.find('id="fb-meine"', i2))
MARKUP += "\n" + FH[i2:j2 + 10]

# ⚠ EIN ABSICHTLICH UEBERLANGER Spaltenname und ein unteilbares Wort: genau
# daran sprengt eine Tabelle die Seite, und genau das sieht keine Messung ueber
# textContent.
FORM = {
    "id": "f1", "titel": "Modulbewertung des Geschaeftsbereichs Rechnungswesen",
    "beschreibung": "Bitte bewerte die Module, mit denen du arbeitest.",
    "aktiv": True,
    "spalten": [{"id": "c1", "name": "Modul", "typ": "text"},
                {"id": "c2", "name": "Bewertung", "typ": "sterne"},
                {"id": "c3", "name": "Anmerkung und weitere Hinweise zur Bedienung",
                 "typ": "text"}]}
ABGABE = {
    "id": "a1", "formular_id": "f1", "formular_titel": "Modulbewertung",
    "zeit": "2026-09-14T10:00:00", "benutzer": "anna",
    "spalten": [{"id": "c1", "name": "Modul", "typ": "text"},
                {"id": "c2", "name": "Bewertung", "typ": "sterne"}],
    "zeilen": [{"c1": "Rechnungswesen", "c2": 4},
               # ⚠ MEHRZEILIG: ob ein Umbruch beim Lesen wieder ein Umbruch ist,
               # sieht keine Messung ueber `textContent` – nur die Zellhoehe.
               {"c1": "Erste Zeile\nZweite Zeile\n\nNach einer Leerzeile", "c2": 3},
               {"c1": "Donaudampfschifffahrtsgesellschaftskapitaenspruefung", "c2": 2}]}

SEITE = r"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/css/theme.css">
<link rel="stylesheet" href="/static/css/jira_addon.css">
<link rel="stylesheet" href="/static/css/feedback.css">
</head><body>
<script>try{if(localStorage.getItem('jarvis_theme')!=='dark')document.body.classList.add('light');}catch(e){}</script>
<div id="fb-app" class="hidden"><div class="ja-main" style="max-width:900px;padding:20px;">
__MARKUP__
</div></div>
<script src="/static/js/icons.js"></script>
<script src="/static/js/i18n.js"></script>
<script>
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
window.addEventListener('unhandledrejection', function (e) {
  window.__fehler += 'ZURUECKWEISUNG: ' + ((e.reason && e.reason.message) || e.reason) + ' | ';
});
localStorage.setItem('jarvis_token', 'probe');
// ⚠ `feedback.js` ist eine IIFE OHNE Schnittstelle – es startet sich selbst und
// holt seine Daten. Der Waechter stellt nur `fetch`; das Modul laeuft dann
// seinen ECHTEN Weg. Das ist die vollere Kette, nicht die bequemere.
function antwort(d) {
  return Promise.resolve({ ok: true, status: 200,
    json: function () { return Promise.resolve(d); } });
}
window.fetch = function (u, o) {
  var url = String(u).split('?')[0];
  if (url === '/api/me') { return antwort({ is_admin: true, permissions: { feedback: true } }); }
  if (url === '/api/feedback/formulare') { return antwort({ ok: true, formulare: [__FORM__] }); }
  if (url === '/api/feedback/meine') { return antwort({ ok: true, abgaben: [__ABGABE__] }); }
  return antwort({ ok: true });
};
</script>
<script src="/static/js/feedback.js"></script>
</body></html>"""

ZIEL = ROOT / "frontend" / "_probe_feedback.html"
ZIEL.write_text(SEITE.replace("__MARKUP__", MARKUP)
                     .replace("__FORM__", json.dumps(FORM, ensure_ascii=False))
                     .replace("__ABGABE__", json.dumps(ABGABE, ensure_ascii=False)),
                encoding="utf-8")
try:
    st = os.stat(ROOT / "frontend")
    os.chown(ZIEL, st.st_uid, st.st_gid)
except Exception:                                                  # noqa: BLE001
    pass

PROFIL = tempfile.mkdtemp(prefix="chrome-fb-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1000,900",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def ziel_ws():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list",
                                        timeout=2) as a:
                for t in json.loads(a.read()):
                    # NUR type=="page" – /json/list liefert auch Erweiterungen.
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
print("Optische Abnahme: Feedback-Bereich")
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
            {"name": "prefers-color-scheme", "value": "dark" if thema == "dunkel" else "light"}])
        # ⚠ Den SPEICHERSCHLUESSEL setzen, nicht die Klasse: das
        # Anti-Flacker-Skript und theme.js lesen ihn – wer nur die Klasse
        # abraeumt, bekommt sie Millisekunden spaeter zurueck (Register).
        cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
            source="try{localStorage.setItem('jarvis_theme','%s');"
                   "localStorage.setItem('jarvis_token','probe');}catch(e){}"
                   % ("dark" if thema == "dunkel" else "light"))
        cdp(sock, "Page.navigate",
            url=f"https://127.0.0.1/static/_probe_feedback.html")
        time.sleep(2.5)

        fehler = js(sock, "window.__fehler || ''")
        check("keine JS-Fehler auf der Seite", not fehler, fehler or "")

        # Positivkontrolle: ohne sie ist jede Messung darunter trivial wahr.
        gr = js(sock, "(function(){var t=document.querySelector('#fb-tabelle table');"
                      "return t?Math.round(t.getBoundingClientRect().width):0;})()")
        check("die Tabelle ist ueberhaupt gezeichnet (Positivkontrolle)",
              (gr or 0) > 200, f"Breite {gr}")
        if not gr:
            continue

        grund = farbe(js(sock, "getComputedStyle(document.body).backgroundColor"))
        print(f"       Grundfarbe: {grund}")

        # ── Kein waagerechter Ueberlauf der SEITE ────────────────────────────
        ueber = js(sock, "document.documentElement.scrollWidth - "
                         "document.documentElement.clientWidth")
        check("kein waagerechter Ueberlauf der Seite", (ueber or 0) <= 1,
              f"{ueber}px")
        scroll = js(sock, "(function(){var w=document.querySelector('.fb-tab-wrap');"
                          "return w?(w.scrollWidth>w.clientWidth?1:0):-1;})()")
        check("die Tabelle scrollt notfalls IN ihrem Container",
              scroll in (0, 1), f"wrap fehlt ({scroll})")

        # ── Sterne: gefuellt sieht ANDERS aus als hohl ───────────────────────
        js(sock, "document.querySelector('#fb-tabelle .fb-sterne').children[2].click()")
        time.sleep(0.3)
        gef = js(sock, "!!document.querySelector('#fb-tabelle .fb-stern.is-an .is-gesetzt')")
        hohl = js(sock, "(function(){var b=document.querySelectorAll('#fb-tabelle .fb-stern');"
                        "return !!(b[4] && !b[4].querySelector('.is-gesetzt'));})()")
        check("ein gesetzter Stern ist GEFUELLT", bool(gef))
        check("ein ungesetzter nicht", bool(hohl))
        # Und er ist wirklich SICHTBAR (nicht 0x0).
        sg = js(sock, "(function(){var s=document.querySelector('#fb-tabelle .fb-stern svg');"
                      "if(!s)return 0;var r=s.getBoundingClientRect();"
                      "return Math.round(r.width*100+r.height);})()")
        check("die Sterne haben eine sichtbare Groesse", (sg or 0) > 1000, str(sg))

        stf = farbe(js(sock, "getComputedStyle(document.querySelector("
                             "'#fb-tabelle .fb-stern.is-an')).color"))
        k = kontrast(stf, grund)
        check(f"der gesetzte Stern hebt sich ab (>=3:1) – {k:.2f}:1", k >= 3.0,
              f"{stf} auf {grund}")

        # ── Der Zahlenwert ist LESBAR ───────────────────────────────────────
        wf = farbe(js(sock, "getComputedStyle(document.querySelector("
                            "'#fb-tabelle .fb-sterne-wert')).color"))
        k2 = kontrast(wf, grund)
        check(f"der Zahlenwert ist lesbar (>=4.5:1) – {k2:.2f}:1", k2 >= 4.5,
              f"{wf} auf {grund}")

        # ── Der Muelleimer bleibt IN der Zeile ──────────────────────────────
        raus = js(sock, """(function(){
          var t=document.querySelector('.fb-tab-wrap');
          var d=document.querySelector('#fb-tabelle .fb-row-del');
          if(!t||!d)return -1;
          var a=t.getBoundingClientRect(), b=d.getBoundingClientRect();
          return (b.right>a.right+1||b.left<a.left-1)?1:0;})()""")
        check("der Muelleimer bleibt im Tabellen-Container", raus == 0, str(raus))

        # ── Das Antwortfeld: breit genug, und es WAECHST ────────────────────
        #
        # ⚠ DAS IST DIE MESSUNG, DIE JSDOM NICHT KANN. Dort gibt es kein Layout,
        # `scrollHeight` ist immer 0 – ob ein Absatz im Feld wirklich sichtbar
        # wird oder hinter einer Bildlaufleiste verschwindet, entscheidet sich
        # erst im echten Browser.
        fb = js(sock, "(function(){var i=document.querySelector("
                      "'#fb-tabelle textarea');"
                      "return i?Math.round(i.getBoundingClientRect().width):0;})()")
        check("das Antwortfeld ist benutzbar breit (>=110px)", (fb or 0) >= 110,
              f"{fb}px")
        ist_ta = js(sock, "(function(){var i=document.querySelector("
                          "'#fb-tabelle textarea');return i?1:0;})()")
        check("und es ist ein mehrzeiliges Feld", ist_ta == 1)

        h_vor = js(sock, "(function(){var i=document.querySelector("
                         "'#fb-tabelle textarea');"
                         "return i?Math.round(i.getBoundingClientRect().height):0;})()")
        js(sock, """(function(){
          var i=document.querySelector('#fb-tabelle textarea');
          i.value='Zeile eins\\nZeile zwei\\nZeile drei\\nZeile vier\\nZeile fuenf';
          i.dispatchEvent(new Event('input',{bubbles:true}));})()""")
        time.sleep(0.4)
        h_nach = js(sock, "(function(){var i=document.querySelector("
                          "'#fb-tabelle textarea');"
                          "return i?Math.round(i.getBoundingClientRect().height):0;})()")
        check(f"⚠ das Feld WAECHST mit dem Inhalt ({h_vor} → {h_nach} px)",
              (h_nach or 0) > (h_vor or 0) + 20,
              "ohne Wachsen steht ein Absatz hinter einer Bildlaufleiste")
        # ⚠ `scrollHeight <= clientHeight`: die Hoehenformel muss den RAHMEN
        # mitrechnen (box-sizing: border-box) – sonst bleibt das Feld zwei Pixel
        # zu klein und zeigt dauerhaft eine Bildlaufleiste, obwohl gerade
        # nachgemessen wurde.
        rest = js(sock, "(function(){var i=document.querySelector("
                        "'#fb-tabelle textarea');"
                        "return i?(i.scrollHeight - i.clientHeight):999;})()")
        check("und zeigt danach KEINE Bildlaufleiste", (rest or 0) <= 1,
              f"scrollHeight - clientHeight = {rest}")
        tf = farbe(js(sock, "getComputedStyle(document.querySelector("
                            "'#fb-tabelle textarea')).color"))
        tg = farbe(js(sock, "getComputedStyle(document.querySelector("
                            "'#fb-tabelle textarea')).backgroundColor"))
        # Halbdurchsichtige Flaeche ueber den Seitengrund legen (Register).
        k3 = kontrast(tf, tg if sum(tg) else grund)
        check(f"der getippte Text ist lesbar (>=4.5:1) – {k3:.2f}:1", k3 >= 4.5,
              f"{tf} auf {tg}")
        ueber_ta = js(sock, "document.documentElement.scrollWidth - "
                            "document.documentElement.clientWidth")
        check("das gewachsene Feld sprengt die Seite nicht",
              (ueber_ta or 0) <= 1, f"{ueber_ta}px")

        # ── Die Rueckschau: ein Umbruch ist wieder ein Umbruch ───────────────
        hoehen = js(sock, """(function(){
          var tds=document.querySelectorAll('.fb-abgabe-body .fb-tab tbody td');
          var mehr=0, ein=0;
          for(var i=0;i<tds.length;i++){
            var t=tds[i].textContent||'';
            var h=Math.round(tds[i].getBoundingClientRect().height);
            if(t.indexOf('Erste Zeile')>=0){mehr=h;}
            else if(t.indexOf('Rechnungswesen')>=0){ein=h;}
          }
          return mehr*10000+ein;})()""")
        m_h, e_h = ((hoehen or 0) // 10000), ((hoehen or 0) % 10000)
        check("die mehrzeilige Zelle ist gezeichnet (Positivkontrolle)", m_h > 0,
              f"mehrzeilig {m_h}px, einzeilig {e_h}px")
        check(f"⚠ sie ist HOEHER als eine einzeilige ({m_h} vs. {e_h} px)",
              m_h > e_h + 20,
              "ohne pre-wrap macht HTML aus jedem Umbruch ein Leerzeichen")

        # ── Die eigenen Abgaben: unteilbares Wort sprengt nichts ─────────────
        ueber2 = js(sock, """(function(){
          var b=document.querySelector('.fb-abgabe-body');
          if(!b)return -1;
          return (b.scrollWidth>b.clientWidth)?1:0;})()""")
        check("ein unteilbar langes Wort scrollt IM Abgabe-Container",
              ueber2 in (0, 1), str(ueber2))
        ueber3 = js(sock, "document.documentElement.scrollWidth - "
                          "document.documentElement.clientWidth")
        check("und sprengt die Seite nicht", (ueber3 or 0) <= 1, f"{ueber3}px")

        # ── Der Absende-Knopf ist erreichbar ─────────────────────────────────
        sichtbar = js(sock, """(function(){
          var b=document.getElementById('fb-senden');
          if(!b)return 0;
          var r=b.getBoundingClientRect();
          return (r.width>40 && r.height>20)?1:0;})()""")
        check("der Absende-Knopf hat eine Groesse", sichtbar == 1)

        # Screenshot
        bild = cdp(sock, "Page.captureScreenshot", format="png")
        p = BILDER / f"feedback-{thema}.png"
        import base64
        p.write_bytes(base64.b64decode(bild["data"]))
        print(f"       Screenshot: {p} ({p.stat().st_size} Byte)")

print("\n" + "=" * 74)
print(f"{_ok} OK, {_fail} FAIL")
ende(1 if _fail else 0)
