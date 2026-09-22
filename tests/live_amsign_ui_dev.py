#!/usr/bin/env python3
"""Optische Abnahme: Bereitstellung + Code-Signatur im AI-Maus-Reiter.

jsdom rechnet kein Layout. Gemessen wird mit dem ECHTEN theme.css/style.css,
dem ECHTEN Markup aus settings.html und dem ECHTEN Renderer aus
ai_mouse_admin.js - in VIER Zustaenden, weil die Zusage des Panels genau in
ihnen liegt: ohne Werkzeug, ohne Zertifikat, mit Zertifikat, abgelaufen.

⚠ DIE PROBESEITE LIEGT NUR FUER DEN LAUF UNTER frontend/ und wird per atexit
entfernt: `test_theme_default.js` laeuft ueber JEDE HTML-Datei dort und
verlangt das Anti-Flacker-Skript (Register - ein Rueckstand laesst einen
FREMDEN Waechter fehlschlagen).

Aufruf: cd /opt/jarvis && ./venv/bin/python tests/live_amsign_ui_dev.py
"""
import atexit
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
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


def leucht(c):
    def k(x):
        x /= 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * k(c[0]) + 0.7152 * k(c[1]) + 0.0722 * k(c[2])


def kontrast(a, b):
    la, lb = leucht(a), leucht(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def farbe(s):
    """⚠ Chrome liefert color-mix als `color(srgb a b c)` mit Anteilen 0..1 -
    als 0..255 gelesen ergaebe das fast Schwarz und einen Traumkontrast."""
    s = (s or "").strip()
    m = re.match(r"color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", s)
    if m:
        return tuple(round(float(m.group(i)) * 255) for i in (1, 2, 3))
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        t = [float(x) for x in m.group(1).replace("/", " ").split(",")[:3]]
        return tuple(round(x) for x in t)
    return (0, 0, 0)


# ── Markup aus der ECHTEN settings.html ─────────────────────────────────────
SH = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")


def schnitt(cid):
    i = SH.find('<div class="kb-section" id="%s">' % cid)
    if i < 0:
        return ""
    tief, j = 0, i
    while j < len(SH):
        if SH.startswith("<div", j):
            tief += 1
        elif SH.startswith("</div>", j):
            tief -= 1
            if tief == 0:
                break
        j += 1
    return SH[i:j + 6]


MARKUP = schnitt("am-sect-share") + "\n" + schnitt("am-sect-sign")
if "amshare-pfad" not in MARKUP or "amsign-state" not in MARKUP:
    print("ABBRUCH: Container nicht in settings.html gefunden (Exit 2).")
    sys.exit(2)

# ── Die vier Zustaende ──────────────────────────────────────────────────────
HINWEIS = ('Zum Signieren fehlt das Programm „osslsigncode". Es wird beim '
           'Einschalten des Skills mitinstalliert; laeuft der Skill bereits, '
           'genuegt der ⤓-Knopf in der Skill-Liste (Einstellungen → Skills). '
           'Von Hand: apt-get install -y osslsigncode')
ZUSTAENDE = [
    ("ohne Werkzeug", {
        "zertifikat": False, "werkzeug_da": False, "werkzeug_hinweis": HINWEIS,
        "exe_signiert": False, "tsa": "", "tsa_standard": "http://timestamp.digicert.com",
        "letzter_fehler": "", "ohne_zeitstempel": False}),
    ("ohne Zertifikat", {
        "zertifikat": False, "werkzeug_da": True, "werkzeug_hinweis": "",
        "exe_signiert": False, "tsa": "", "tsa_standard": "http://timestamp.digicert.com",
        "letzter_fehler": "", "ohne_zeitstempel": False}),
    ("mit Zertifikat, signiert", {
        "zertifikat": True, "werkzeug_da": True, "werkzeug_hinweis": "",
        "betreff": "NEXUS AG Code Signing", "aussteller": "ROOT-CA-NEXUS",
        "gueltig_bis": "2027-09-21", "abgelaufen": False,
        "exe_signiert": True, "tsa": "http://timestamp.digicert.com",
        "tsa_standard": "http://timestamp.digicert.com",
        "letzter_fehler": "", "ohne_zeitstempel": False}),
    ("abgelaufen + Fehlschlag", {
        "zertifikat": True, "werkzeug_da": True, "werkzeug_hinweis": "",
        "betreff": "NEXUS AG Code Signing", "aussteller": "ROOT-CA-NEXUS",
        "gueltig_bis": "2026-01-01", "abgelaufen": True,
        "exe_signiert": True, "ohne_zeitstempel": True,
        "tsa": "", "tsa_standard": "http://timestamp.digicert.com",
        "letzter_fehler": ("osslsigncode: unable to load certificate - der "
                           "Zeitstempel-Dienst hat nicht geantwortet und das "
                           "Zertifikat ist seit dem 01.01.2026 abgelaufen")}),
]

SEITE = """<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/css/theme.css">
<link rel="stylesheet" href="/static/css/style.css">
</head><body><div class="modal-card" style="max-width:820px;padding:20px;">
__MARKUP__
</div>
<script src="/static/js/icons.js"></script>
<script>
window.t = function (k, f) { return f || k; };
window.getLang = function () { return 'de'; };
localStorage.setItem('jarvis_token', 'probe');
</script>
<script src="/static/js/ai_mouse_admin.js"></script>
<script>
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
window.__zeige = function (d, pfad) {
  try {
    document.getElementById('amshare-pfad').value = pfad;
    AiMouseAdmin.renderSignatur(d);
    return '';
  } catch (e) { return 'WURF: ' + e.message; }
};
</script></body></html>"""

ZIEL = ROOT / "frontend" / "_probe_amsign.html"
ZIEL.write_text(SEITE.replace("__MARKUP__", MARKUP), encoding="utf-8")
try:
    st = os.stat(ROOT / "frontend")
    os.chown(ZIEL, st.st_uid, st.st_gid)
except Exception:  # noqa: BLE001
    pass

PROFIL = tempfile.mkdtemp(prefix="chrome-amsign-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
chrome = None


def aufraeumen():
    if chrome is not None:
        try:
            chrome.kill()
        except Exception:  # noqa: BLE001
            pass
    shutil.rmtree(PROFIL, ignore_errors=True)
    try:
        ZIEL.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


atexit.register(aufraeumen)

s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     "--remote-debugging-port=%d" % PORT, "--remote-allow-origins=*",
     "--user-data-dir=%s" % PROFIL, "--window-size=1000,1100",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def ziel():
    for _ in range(60):
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/json/list" % PORT, timeout=2) as a:
                # ⚠ NUR type=="page" - /json/list liefert auch Erweiterungen,
                #   und `[0]` haengt dann an background.html (Register).
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


print("=" * 74)
print("Optische Abnahme: Bereitstellung + Code-Signatur (AI-Maus-Reiter)")
print("=" * 74)

ws = ziel()
if not ws:
    print("ABBRUCH: kein CDP-Ziel (Exit 2)")
    sys.exit(2)
try:
    from websockets.sync.client import connect
except Exception:  # noqa: BLE001
    print("ABBRUCH: python-websockets fehlt im venv (Exit 2).")
    sys.exit(2)

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


BILDER = Path.home() / "amsign-bilder"
BILDER.mkdir(exist_ok=True)
LANG = "\\\\fileserver.nexus-ag.intern\\Software\\Werkzeuge\\AI-Maus\\AiMouse.exe"
gemessen = {}

with connect(ws, max_size=80 * 1024 * 1024) as sock:
    cdp(sock, "Page.enable")
    for thema, klasse in (("dunkel", ""), ("hell", "light")):
        cdp(sock, "Page.navigate",
            url="https://127.0.0.1/static/_probe_amsign.html")
        time.sleep(2.5)
        js(sock, "document.body.className = %s;" % json.dumps(klasse))
        time.sleep(0.4)
        print("\n── Thema: %s %s" % (thema, "─" * 40))

        check("kein JS-Fehler beim Aufbau", not js(sock, "window.__fehler"),
              js(sock, "window.__fehler"))
        # Positivkontrolle des Messaufbaus: ohne geladenes CSS ist jede
        # Layout- und Kontrastmessung darunter wertlos.
        grund = js(sock, "getComputedStyle(document.body).backgroundColor")
        check("das echte CSS ist geladen (Seitengrund gesetzt)",
              grund not in ("", "rgba(0, 0, 0, 0)"), grund)
        gemessen[thema] = grund

        for name, d in ZUSTAENDE:
            wurf = js(sock, "window.__zeige(%s, %s)"
                      % (json.dumps(d), json.dumps(LANG)))
            check("[%s] Renderer laeuft ohne Wurf" % name, not wurf, wurf)
            txt = js(sock, "document.getElementById('amsign-state').textContent")
            check("[%s] das Panel sagt etwas" % name, bool((txt or "").strip()),
                  repr(txt)[:80])

            # ⚠ Die tragende Aussage ist die ueber die AUSGELIEFERTE Datei -
            #   sie muss in JEDEM Zustand dastehen.
            check("[%s] es steht da, ob die Anwendung signiert ist" % name,
                  "Anwendung ist" in (txt or ""), repr(txt)[:120])
            if d.get("abgelaufen"):
                check("[%s] der Ablauf wird BENANNT" % name,
                      "abgelaufen" in (txt or ""))
            if not d.get("werkzeug_da"):
                check("[%s] das fehlende Werkzeug steht ZUERST" % name,
                      (txt or "").lstrip().startswith("⚠")
                      and "osslsigncode" in (txt or ""))

            ueber = js(sock, """(function () {
              var b = document.getElementById('amsign-state');
              var k = document.querySelector('#am-sect-sign');
              if (!b || !k) { return -1; }
              return Math.round(b.getBoundingClientRect().right
                                - k.getBoundingClientRect().right);
            })()""")
            check("[%s] der Text bleibt im Container" % name,
                  isinstance(ueber, (int, float)) and ueber <= 2, ueber)

        # ── Layout, einmal je Thema ─────────────────────────────────────────
        ov = js(sock, "document.documentElement.scrollWidth - "
                      "document.documentElement.clientWidth")
        check("kein waagerechter Ueberlauf der Seite", (ov or 0) <= 0, ov)

        for cid in ("am-sect-share", "am-sect-sign"):
            raus = js(sock, """(function () {
              var k = document.getElementById(%s);
              if (!k) { return -1; }
              var r = k.getBoundingClientRect(), m = 0;
              k.querySelectorAll('*').forEach(function (e) {
                var b = e.getBoundingClientRect();
                if (b.width) { m = Math.max(m, Math.round(b.right - r.right)); }
              });
              return m;
            })()""" % json.dumps(cid))
            check("%s: nichts ragt heraus" % cid,
                  isinstance(raus, (int, float)) and raus <= 2, raus)

        # Der lange UNC-Pfad ist der Testfall fuer das Eingabefeld.
        feld = js(sock, """(function () {
          var e = document.getElementById('amshare-pfad');
          var k = document.getElementById('am-sect-share');
          if (!e || !k) { return -1; }
          return Math.round(e.getBoundingClientRect().right
                            - k.getBoundingClientRect().right);
        })()""")
        check("der lange UNC-Pfad sprengt das Feld nicht",
              isinstance(feld, (int, float)) and feld <= 2, feld)

        # ⚠ DER DOWNLOAD LIEGT SEIT 2026-09-22 HIER, nicht mehr in der
        #   Benutzer-Kachel. Er gehoert in dieselbe Abnahme wie die
        #   uebrigen Knoepfe des Reiters – sonst ist die Verlagerung
        #   zwar gemessen (jsdom), aber nie GESEHEN.
        for bid in ("amshare-save", "amshare-dl", "amsign-save", "amsign-del"):
            sicht = js(sock, """(function () {
              var e = document.getElementById(%s);
              if (!e) { return 0; }
              var r = e.getBoundingClientRect();
              return r.width > 40 && r.height > 20 ? 1 : 0;
            })()""" % json.dumps(bid))
            check("Knopf %s ist sichtbar und gross genug" % bid, sicht == 1)

        # Kontrast des Hinweistextes - er traegt die Aussage.
        vg = js(sock, "getComputedStyle(document.getElementById('amsign-state'))"
                      ".color")
        hg = js(sock, """(function () {
          var e = document.getElementById('am-sect-sign');
          for (; e; e = e.parentElement) {
            var c = getComputedStyle(e).backgroundColor;
            if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') { return c; }
          }
          return 'rgb(255,255,255)';
        })()""")
        k = kontrast(farbe(vg), farbe(hg))
        check("Zustandstext lesbar (%.2f:1)" % k, k >= 4.5, "%s auf %s" % (vg, hg))

        # Schmales Fenster: bricht die Knopfzeile um statt ueberzulaufen?
        cdp(sock, "Emulation.setDeviceMetricsOverride", width=520, height=900,
            deviceScaleFactor=1, mobile=False)
        time.sleep(0.5)
        ov2 = js(sock, "document.documentElement.scrollWidth - "
                       "document.documentElement.clientWidth")
        check("bei 520 px kein waagerechter Ueberlauf", (ov2 or 0) <= 2, ov2)
        cdp(sock, "Emulation.clearDeviceMetricsOverride")
        time.sleep(0.3)

        js(sock, "window.__zeige(%s, %s)"
           % (json.dumps(ZUSTAENDE[3][1]), json.dumps(LANG)))
        time.sleep(0.4)
        # ⚠ `captureBeyondViewport` wird in --headless=new nicht zuverlaessig
        #   beachtet: der erste Lauf schnitt die Knopfzeile des
        #   Signatur-Containers ab, und genau die will man SEHEN. Also das
        #   Fenster auf die gemessene Seitenhoehe stellen.
        # ⚠ ZWEI BILDER, WEIL EIN AUSSCHNITT NICHT BEIDES ZEIGT.
        #   `captureBeyondViewport` wird in --headless=new nicht zuverlaessig
        #   beachtet - der erste Lauf schnitt genau die Knopfzeile ab, also
        #   das, was man SEHEN will. Statt zu vergroessern wird gescrollt.
        for teil, anker in (("oben", "am-sect-share"), ("knoepfe", "amsign-del")):
            js(sock, """(function () {
              var e = document.getElementById(%s);
              if (e) { e.scrollIntoView({block: 'center'}); }
            })()""" % json.dumps(anker))
            time.sleep(0.4)
            r = cdp(sock, "Page.captureScreenshot", format="png")
            if r.get("data"):
                p = BILDER / ("amsign-%s-%s.png" % (thema, teil))
                p.write_bytes(base64.b64decode(r["data"]))
                print("      Screenshot: %s" % p)

# ⚠ Positivkontrolle: hell und dunkel muessen ZWEI Messungen gewesen sein -
#   ein identischer Seitengrund hiesse, das Thema hat nie gewechselt.
check("hell und dunkel waren zwei verschiedene Messungen",
      gemessen.get("hell") != gemessen.get("dunkel"), gemessen)

print("\n" + "=" * 74)
print("%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
