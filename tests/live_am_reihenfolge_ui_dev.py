#!/usr/bin/env python3
"""Optische Abnahme: Ziehen der Fragen-Reihenfolge (hell UND dunkel).

jsdom rechnet kein Layout. Gemessen wird mit dem ECHTEN `jira_addon.css`, dem
ECHTEN Markup aus `ai_mouse.html` und dem ECHTEN Renderer aus `ai_mouse.js` –
mit den ECHTEN Fragen des Benutzers (nur GELESEN, nie geschrieben).

⚠ DER ZUG WIRD WIRKLICH AUSGELOEST, nicht simuliert: Chrome kennt den
`DataTransfer`-Konstruktor, also lassen sich echte `DragEvent`-Objekte an die
echten Zuhoerer schicken. Das ist KEIN Mauszug des Betriebssystems (dafuer
braeuchte es `Input.setInterceptDrags`) – gemessen wird die Kette vom Ereignis
bis zur neuen Reihenfolge im DOM, und das ist der Teil, der hier entsteht.

Die Probeseite liegt NUR fuer den Lauf unter frontend/ und wird danach entfernt.
Aufruf: cd /opt/jarvis && ./venv/bin/python tests/live_am_reihenfolge_ui_dev.py
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
sys.path.insert(0, str(ROOT))

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


# ── Die ECHTEN Fragen, nur gelesen ──────────────────────────────────────────
from backend import ai_mouse_fragen as amf                         # noqa: E402
from backend import main as M                                      # noqa: E402

BENUTZER = os.environ.get("AIMOUSE_TESTUSER") or "andreas.bender"
FRAGEN = amf.liste(BENUTZER, False)
if len(FRAGEN) < 3:
    print("ABBRUCH: weniger als drei Fragen – eine Reihenfolge ist dann keine.")
    sys.exit(2)
# ⚠ Fuer die Gruppengrenze braucht es eine GEMEINSAME Frage. Gibt es keine,
# wird EINE dazugestellt – sonst waere die Pruefung ueber einer leeren Menge
# trivial wahr. Der Bestand auf Platte bleibt dabei unangetastet.
GEM_ECHT = any(f.get("gemeinsam") for f in FRAGEN)
if not GEM_ECHT:
    FRAGEN = [{"id": "zz-gem", "titel": "Gemeinsame Probe",
               "prompt": "Nur fuer die Gruppengrenze",
               "gemeinsam": True, "darf_aendern": False}] + FRAGEN
EIGEN = [f for f in FRAGEN if not f.get("gemeinsam")]
print(f"Benutzer: {BENUTZER} · {len(FRAGEN)} Fragen "
      f"({len(EIGEN)} eigene, gemeinsame {'echt' if GEM_ECHT else 'gestellt'})")

# Markup aus der ECHTEN ai_mouse.html schneiden (Container um #am-fragen).
AH = (ROOT / "frontend" / "ai_mouse.html").read_text(encoding="utf-8")
# ⚠ ES IST EIN <section>, KEIN <div> – ein Schnitt, der nach `<div class=
# "ja-card"` sucht, findet ihn nicht und meldet einen Fehler, den es nicht gibt.
i = AH.find('<section class="ja-card" data-klapp="fragen">')
if i < 0:
    print("ABBRUCH: Fragen-Container nicht in ai_mouse.html gefunden.")
    sys.exit(2)
j = AH.find("</section>", AH.find('id="am-fragen"', i))
if j < 0:
    print("ABBRUCH: Ende des Fragen-Containers nicht gefunden.")
    sys.exit(2)
MARKUP = AH[i:j + 10]
if "am-fragen" not in MARKUP or "am-q-zug" not in MARKUP:
    print("ABBRUCH: der Schnitt traegt nicht #am-fragen UND #am-q-zug.")
    sys.exit(2)

SEITE = r"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/css/theme.css">
<link rel="stylesheet" href="/static/css/jira_addon.css">
</head><body><div class="ja-wrap" style="max-width:900px;padding:20px;">
__MARKUP__
</div>
<script src="/static/js/icons.js"></script>
<script src="/static/js/i18n.js"></script>
<script>
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
window.addEventListener('unhandledrejection', function (e) {
  window.__fehler += 'ZURUECKWEISUNG: ' + ((e.reason && e.reason.message) || e.reason) + ' | ';
});
localStorage.setItem('jarvis_token', 'probe');
window.__ALLE = __FRAGEN__;
window.__gesendet = [];

// ⚠ `ai_mouse.js` IST EINE IIFE OHNE SCHNITTSTELLE – es startet sich selbst
// und holt seine Daten. Der Waechter kann deshalb nichts "fuettern"; er stellt
// nur `fetch`, und das Modul laeuft seinen ECHTEN Weg. Das ist die vollere
// Kette, nicht die bequemere.
function antwort(d) {
  return Promise.resolve({ ok: true, status: 200,
    json: function () { return Promise.resolve(d); } });
}
window.fetch = function (u, o) {
  var url = String(u), rumpf = (o && o.body) || '';
  if (url.indexOf('/api/ai-mouse/fragen/reihenfolge') === 0) {
    window.__gesendet.push({ url: url, body: rumpf });
    var ids = [];
    try { ids = JSON.parse(rumpf || '{}').ids || []; } catch (e) {}
    var nach = {}, raus = [], gesehen = {};
    window.__ALLE.forEach(function (f) { nach[f.id] = f; });
    ids.forEach(function (x) {
      if (nach[x] && !gesehen[x]) { raus.push(nach[x]); gesehen[x] = 1; } });
    window.__ALLE.forEach(function (f) { if (!gesehen[f.id]) { raus.push(f); } });
    window.__ALLE = raus;                       // wie der Server: gespeichert
    return antwort({ ok: true, bewegt: raus.length, fragen: raus });
  }
  if (url.indexOf('/api/ai-mouse/fragen') === 0) {
    return antwort({ fragen: window.__ALLE });
  }
  // ⚠ `/api/me` MUSS ANTWORTEN: `start()` leitet ohne `permissions.ai_mouse`
  // aufs Portal um, und dann wird gar nichts gezeichnet – die Messung waere
  // trivial wahr (Register: ein Aufbau, der den Regelfall nicht herstellt).
  if (url.indexOf('/api/me') === 0) {
    return antwort({ user: 'probe', is_admin: false,
                     permissions: { ai_mouse: true } });
  }
  if (url.indexOf('/api/ai-mouse/health') === 0) {
    return antwort({ ok: true, freigegeben: true, paket: true,
                     klient_version: '1.0.1', bereiche: [], bereiche_aktiv: [] });
  }
  return antwort({});
};
</script>
<script src="/static/js/ai_mouse.js"></script>
<script>
// Echter Zug: Chrome kennt den DataTransfer-Konstruktor.
window.__zieh = function (vonId, aufId) {
  var a = document.querySelector('.am-q-card[data-qid="' + vonId + '"]');
  var b = document.querySelector('.am-q-card[data-qid="' + aufId + '"]');
  if (!a || !b) { return 'KARTE FEHLT'; }
  var g = a.querySelector('.am-q-griff');
  var dt = new DataTransfer();
  g.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
  var r = b.getBoundingClientRect();
  var ov = new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt,
                                       clientX: r.left + 5, clientY: r.top + r.height - 2 });
  b.dispatchEvent(ov);
  b.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt,
                                          clientX: r.left + 5, clientY: r.top + r.height - 2 }));
  a.querySelector('.am-q-griff').dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
  return ov.defaultPrevented ? 'OK' : 'NICHT ERLAUBT';
};
window.__folge = function () {
  return Array.prototype.map.call(document.querySelectorAll('.am-q-card'),
    function (c) { return c.getAttribute('data-qid'); });
};
</script></body></html>"""

ZIEL = ROOT / "frontend" / "_probe_amreih.html"
ZIEL.write_text(SEITE.replace("__MARKUP__", MARKUP)
                     .replace("__FRAGEN__", json.dumps(FRAGEN, ensure_ascii=False)),
                encoding="utf-8")
try:
    st = os.stat(ROOT / "frontend")
    os.chown(ZIEL, st.st_uid, st.st_gid)
except Exception:                                                  # noqa: BLE001
    pass

PROFIL = tempfile.mkdtemp(prefix="chrome-amr-", dir=str(Path.home()))
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
print("Optische Abnahme: Ziehen der Fragen-Reihenfolge")
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
    if "exceptionDetails" in r:
        e = ((r["exceptionDetails"].get("exception") or {}).get("description")
             or r["exceptionDetails"].get("text") or "?")
        return "JS-WURF: " + str(e)[:140]
    return (r.get("result") or {}).get("value")


def dct(sock, a, name):
    """⚠ Ein Wurf gibt eine ZEICHENKETTE zurueck – `.get()` darauf bricht den
    Lauf OHNE BILANZ ab (Register). Hier wird er zu einem FAIL."""
    w = js(sock, a)
    if isinstance(w, dict):
        return w
    check(f"Messung {name} laeuft (Positivkontrolle)", False, str(w)[:150])
    return {}


BILDER = Path.home() / "amreih-bilder"
BILDER.mkdir(exist_ok=True)
EIGEN_IDS = [f["id"] for f in EIGEN]
GEM_ID = next(f["id"] for f in FRAGEN if f.get("gemeinsam"))

try:
    with connect(ws, max_size=80 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        for thema, klasse in (("dunkel", ""), ("hell", "light")):
            cdp(sock, "Page.navigate",
                url="https://127.0.0.1/static/_probe_amreih.html")
            time.sleep(3.0)
            js(sock, f"document.body.className = {json.dumps(klasse)};")
            time.sleep(0.5)
            print(f"\n── Thema: {thema} " + "─" * 42)

            check("kein JS-Fehler beim Aufbau", not js(sock, "window.__fehler"),
                  str(js(sock, "window.__fehler"))[:120])
            n = js(sock, "document.querySelectorAll('.am-q-card').length")
            check(f"alle {len(FRAGEN)} Karten gezeichnet (Positivkontrolle)",
                  n == len(FRAGEN), f"{n}")
            if n != len(FRAGEN):
                continue

            # ── Der Griff ────────────────────────────────────────────────────
            g = dct(sock, """(function(){
              var c=document.querySelector('.am-q-card[data-qid=%s]');
              var g=c.querySelector('.am-q-griff'), r=g.getBoundingClientRect();
              var s=getComputedStyle(g);
              return {b:Math.round(r.width),h:Math.round(r.height),
                      cur:s.cursor,
                      zieh:g.getAttribute('draggable'),
                      tab:g.getAttribute('tabindex'),
                      rolle:g.getAttribute('role'),
                      aus:g.classList.contains('is-aus'),
                      fg:s.color,bg:getComputedStyle(c).backgroundColor,
                      txt:(g.getAttribute('title')||'')};
            })()""" % json.dumps(EIGEN_IDS[0]), "Griff")
            check("der Griff hat eine Groesse und liegt im Bild",
                  isinstance(g, dict) and g["b"] >= 12 and g["h"] >= 12, str(g))
            check("er zeigt den Greif-Zeiger", g.get("cur") == "grab",
                  str(g.get("cur")))
            # ⚠ KEIN `.disabled` – der Griff ist ein <span>. Gemessen wird,
            # was ihn bedienbar MACHT: ziehbar, fokussierbar, als Knopf
            # angekuendigt, und nicht als "aus" markiert.
            check("er ist an einer eigenen Frage ziehbar und fokussierbar",
                  g.get("zieh") == "true" and g.get("tab") == "0"
                  and g.get("rolle") == "button" and g.get("aus") is False,
                  str({k: g.get(k) for k in ("zieh", "tab", "rolle", "aus")}))
            check("er traegt eine Beschriftung", len(g.get("txt") or "") > 3,
                  str(g.get("txt")))
            k = kontrast(farbe(g["fg"]), farbe(g["bg"]))
            check(f"Kontrast des Griffs {k:.2f}:1 (Grafik-Grenze 3:1)", k >= 3.0)

            # ── Er darf die Zeile nicht sprengen ────────────────────────────
            z = dct(sock, """(function(){
              var c=document.querySelector('.am-q-card[data-qid=%s]');
              var r=c.getBoundingClientRect();
              var kn=c.querySelectorAll('.am-q-row button');
              var letzt=kn[kn.length-1].getBoundingClientRect();
              var g=c.querySelector('.am-q-griff').getBoundingClientRect();
              var t=c.querySelector('.am-q-titel')||c.querySelector('.am-q-main');
              return {drin: letzt.right <= r.right+1 && g.left >= r.left-1,
                      knoepfe: kn.length,
                      titel_breit: Math.round((t?t.getBoundingClientRect().width:0)),
                      scroll: document.documentElement.scrollWidth,
                      klient: document.documentElement.clientWidth};
            })()""" % json.dumps(EIGEN_IDS[0]), "Zeile")
            check("Griff UND Knoepfe bleiben in der Zeile",
                  z.get("drin") is True, str(z))
            check("der Titel hat trotzdem Platz", (z.get("titel_breit") or 0) > 80,
                  str(z.get("titel_breit")))
            check("kein waagerechter Ueberlauf der Seite",
                  z["scroll"] <= z["klient"] + 1,
                  f"{z['scroll']} > {z['klient']}")

            # ── Gemeinsame Frage: gesperrt, aber ohne Layoutsprung ──────────
            v = dct(sock, """(function(){
              var a=document.querySelector('.am-q-card[data-qid=%s] .am-q-griff');
              var b=document.querySelector('.am-q-card[data-qid=%s] .am-q-griff');
              var ra=a.getBoundingClientRect(), rb=b.getBoundingClientRect();
              return {aus:a.classList.contains('is-aus'),
                      zieh:a.getAttribute('draggable'),
                      tab:a.getAttribute('tabindex'),
                      versteckt:a.getAttribute('aria-hidden'),
                      gleich:Math.abs(ra.width-rb.width)<1,
                      links:Math.abs(ra.left-rb.left)<1};
            })()""" % (json.dumps(GEM_ID), json.dumps(EIGEN_IDS[0])), "gesperrter Griff")
            check("an einer gemeinsamen Frage gibt es keinen Griff zum Ziehen",
                  v.get("aus") is True and not v.get("zieh") and not v.get("tab")
                  and v.get("versteckt") == "true", str(v))
            check("er behaelt dabei Breite und Position (kein Sprung)",
                  v.get("gleich") and v.get("links"), str(v))

            # ── DER ZUG, wirklich ausgeloest ────────────────────────────────
            if len(EIGEN_IDS) >= 2:
                vorher = js(sock, "window.__folge()")
                erg = js(sock, "window.__zieh(%s,%s)"
                         % (json.dumps(EIGEN_IDS[0]), json.dumps(EIGEN_IDS[-1])))
                check("der Zug wird angenommen (dragover erlaubt das Ablegen)",
                      erg == "OK", str(erg))
                time.sleep(0.6)
                nachher = js(sock, "window.__folge()")
                check("die Reihenfolge im Bild hat sich geaendert",
                      nachher != vorher,
                      f"{str(vorher)[:60]} -> {str(nachher)[:60]}")
                check("die erste eigene Frage steht jetzt hinten",
                      nachher and nachher[-1] == EIGEN_IDS[0],
                      str(nachher[-3:]))
                check("keine Frage verloren und keine doppelt",
                      sorted(nachher or []) == sorted(vorher or []),
                      f"{len(nachher or [])} von {len(vorher or [])}")
                ges = js(sock, "window.__gesendet")
                check("genau ein Serveraufruf, an den Reihenfolge-Endpunkt",
                      isinstance(ges, list) and len(ges) == 1
                      and ges[0]["url"].endswith("/api/ai-mouse/fragen/reihenfolge"),
                      str(ges)[:140])

                # Die Gruppengrenze: eigen -> gemeinsam muss ABGELEHNT werden.
                js(sock, "window.__gesendet = [];")
                vor2 = js(sock, "window.__folge()")
                erg2 = js(sock, "window.__zieh(%s,%s)"
                          % (json.dumps(EIGEN_IDS[-1]), json.dumps(GEM_ID)))
                time.sleep(0.4)
                check("ueber die Gruppengrenze wird NICHT abgelegt",
                      erg2 == "NICHT ERLAUBT", str(erg2))
                check("dabei aendert sich nichts und es wird nichts gesendet",
                      js(sock, "window.__folge()") == vor2
                      and js(sock, "window.__gesendet.length") == 0)

            # ── Tastatur: derselbe Codeweg ohne Maus ────────────────────────
            cdp(sock, "Page.navigate",
                url="https://127.0.0.1/static/_probe_amreih.html")
            time.sleep(3.0)
            js(sock, f"document.body.className = {json.dumps(klasse)};")
            time.sleep(0.4)
            vorher = js(sock, "window.__folge()")
            tast = dct(sock, """(function(){
              var g=document.querySelector('.am-q-card[data-qid=%s] .am-q-griff');
              g.focus();
              var fokus_vor = document.activeElement === g;
              g.dispatchEvent(new KeyboardEvent('keydown',
                {key:'ArrowDown', ctrlKey:true, bubbles:true, cancelable:true}));
              return {fokus_vor: fokus_vor};
            })()""" % json.dumps(EIGEN_IDS[0]), "Tastatur")
            check("der Griff ist per Tastatur erreichbar",
                  tast.get("fokus_vor") is True, str(tast))
            time.sleep(0.6)
            nach = js(sock, "window.__folge()")
            check("Strg+Pfeil verschiebt die Karte", nach != vorher,
                  f"{str(vorher)[:50]} -> {str(nach)[:50]}")
            check("der Fokus wandert mit (sonst ist der zweite Druck ins Leere)",
                  js(sock, """(function(){
                    var a=document.activeElement;
                    return !!(a && a.classList && a.classList.contains('am-q-griff')
                      && a.closest('.am-q-card').getAttribute('data-qid') === %s);
                  })()""" % json.dumps(EIGEN_IDS[0])) is True)
            # ECHTER Tastendruck – sonst bleibt Chromes Heuristik auf "Maus"
            # und `:focus-visible` greift nie (die Messung waere dann falsch).
            for typ in ("rawKeyDown", "keyUp"):
                cdp(sock, "Input.dispatchKeyEvent", type=typ, key="Tab",
                    code="Tab", windowsVirtualKeyCode=9, nativeVirtualKeyCode=9)
            time.sleep(0.3)
            sb = dct(sock, """(function(){
              var g=document.querySelector('.am-q-card[data-qid=%s] .am-q-griff');
              g.focus(); var s=getComputedStyle(g);
              return {ow: s.outlineWidth, os: s.outlineStyle,
                      passt: g.matches(':focus-visible')};
            })()""" % json.dumps(EIGEN_IDS[0]), "Fokusrahmen")
            check("der Tastatur-Fokus ist sichtbar",
                  sb.get("passt") is True and sb.get("os") not in (None, "none")
                  and (sb.get("ow") or "0px") != "0px", str(sb))

            b = cdp(sock, "Page.captureScreenshot", format="png")
            p = BILDER / f"fragen-{thema}.png"
            p.write_bytes(base64.b64decode(b["data"]))
            print(f"     Screenshot: {p}")
except Exception as e:                                             # noqa: BLE001
    print("ABBRUCH: %s" % e)
    ende(2)

print("\n%s\n  %d OK, %d FAIL\n%s" % ("=" * 74, _ok, _fail, "=" * 74))
chrome.kill()
shutil.rmtree(PROFIL, ignore_errors=True)
ZIEL.unlink(missing_ok=True)
sys.exit(1 if _fail else 0)
