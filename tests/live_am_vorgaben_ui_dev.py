#!/usr/bin/env python3
"""Optische Abnahme: Vorgabe-Fragen im AI-Maus-Reiter (hell UND dunkel).

jsdom rechnet kein Layout. Gemessen wird mit dem ECHTEN style.css, dem ECHTEN
Markup aus settings.html und dem ECHTEN Renderer aus ai_mouse_admin.js – mit
den ECHTEN sechs Vorgaben, darunter der sehr lange Adress-Prompt: genau der
Fall, an dem `min-width: 0` und der Zeilenumbruch zaehlen.

Die Probeseite liegt NUR fuer den Lauf unter frontend/ und wird danach entfernt.
Aufruf: cd /opt/jarvis && ./venv/bin/python tests/live_am_vorgaben_ui_dev.py
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
    """Chrome liefert color-mix als `color(srgb a b c)` mit Anteilen 0..1 –
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


# Die ECHTEN Vorgaben – kein Nachbau: der lange Adress-Prompt ist der Testfall.
from backend import ai_mouse_fragen as amf  # noqa: E402
VORG = amf.vorgaben_liste()
if len(VORG) < 6:
    print("ABBRUCH: es liegen weniger als sechs Vorgaben vor – nichts zu messen.")
    sys.exit(2)

# Markup des Containers aus der ECHTEN settings.html schneiden.
SH = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
i = SH.find('<div class="kb-section" id="am-sect-vorg">')
if i < 0:
    print("ABBRUCH: Container am-sect-vorg nicht in settings.html gefunden.")
    sys.exit(2)
tief, j = 0, i
while j < len(SH):
    if SH.startswith("<div", j):
        tief += 1
    elif SH.startswith("</div>", j):
        tief -= 1
        if tief == 0:
            break
    j += 1
MARKUP = SH[i:j + 6]

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
// Den ECHTEN Renderer mit den ECHTEN Vorgaben fuettern (kein Serveraufruf).
try {
  AiMouseAdmin._vorgaben = __VORGABEN__;
  AiMouseAdmin.bind();
  AiMouseAdmin.vorgabenZeichnen();
} catch (e) { window.__fehler += 'WURF: ' + e.message; }
</script></body></html>"""

ZIEL = ROOT / "frontend" / "_probe_amvorg.html"
ZIEL.write_text(SEITE.replace("__MARKUP__", MARKUP)
                     .replace("__VORGABEN__", json.dumps(VORG, ensure_ascii=False)),
                encoding="utf-8")
try:
    os.chown(ZIEL, os.stat(ROOT / "frontend").st_uid, os.stat(ROOT / "frontend").st_gid)
except Exception:  # noqa: BLE001
    pass

PROFIL = tempfile.mkdtemp(prefix="chrome-amv-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1000,900", "--ignore-certificate-errors",
     "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def ziel():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as a:
                # NUR type=="page" – /json/list liefert auch Erweiterungen.
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


print("=" * 74)
print("Optische Abnahme: Vorgabe-Fragen im AI-Maus-Reiter")
print("=" * 74)

ws = ziel()
if not ws:
    print("ABBRUCH: kein CDP-Ziel")
    chrome.kill()
    shutil.rmtree(PROFIL, ignore_errors=True)
    ZIEL.unlink(missing_ok=True)
    sys.exit(2)
try:
    from websockets.sync.client import connect
except Exception:  # noqa: BLE001
    print("ABBRUCH: python-websockets fehlt im venv.")
    chrome.kill()
    shutil.rmtree(PROFIL, ignore_errors=True)
    ZIEL.unlink(missing_ok=True)
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
    r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


BILDER = Path.home() / "amvorg-bilder"
BILDER.mkdir(exist_ok=True)
try:
    with connect(ws, max_size=80 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        for thema, klasse in (("dunkel", ""), ("hell", "light")):
            cdp(sock, "Page.navigate", url="https://127.0.0.1/static/_probe_amvorg.html")
            time.sleep(2.5)
            js(sock, f"document.body.className = {json.dumps(klasse)};")
            time.sleep(0.4)
            print(f"\n── Thema: {thema} " + "─" * 40)

            fehler = js(sock, "window.__fehler || ''")
            check(f"[{thema}] der Renderer lief ohne JS-Fehler", not fehler, str(fehler)[:120])
            n = js(sock, "document.querySelectorAll('.am-vorg-card').length")
            check(f"[{thema}] alle sechs Vorgaben gezeichnet", n == 6, str(n))
            if n != 6:
                continue

            m = js(sock, """(function(){
              var k=document.querySelectorAll('.am-vorg-card');
              var lang=null, i;
              for(i=0;i<k.length;i++){ if(/Adressdaten/.test(k[i].textContent)) lang=k[i]; }
              var kr=lang.getBoundingClientRect();
              var akt=lang.querySelectorAll('.am-vorg-act');
              var a0=akt[0].getBoundingClientRect(), a1=akt[akt.length-1].getBoundingClientRect();
              var box=document.querySelector('.modal-card').getBoundingClientRect();
              return {karte:Math.round(kr.width), hoehe:Math.round(kr.height),
                      knoepfe:akt.length,
                      knoepfeDrin:(a1.right<=kr.right+1 && a0.left>=kr.left-1),
                      knopfBreite:Math.round(a0.width),
                      ueberlauf:document.documentElement.scrollWidth-window.innerWidth,
                      inBox:(kr.right<=box.right+1)};
            })()""")
            # ⚠ Der lange Adress-Prompt ist der Testfall fuer `min-width: 0`.
            check(f"[{thema}] ⚠ die Knoepfe bleiben in der Zeile (langer Prompt)",
                  m["knoepfeDrin"] and m["knoepfe"] == 2, json.dumps(m))
            check(f"[{thema}] die Karte bleibt im Kasten", m["inBox"], json.dumps(m))
            check(f"[{thema}] kein waagerechter Ueberlauf der Seite",
                  m["ueberlauf"] <= 0, str(m["ueberlauf"]))
            check(f"[{thema}] der lange Prompt bricht um (Karte hoeher als eine Zeile)",
                  m["hoehe"] > 40, str(m["hoehe"]))

            # Formular klappt IN der Karte auf.
            js(sock, "AiMouseAdmin.vorgabeFormular("
                     + json.dumps(VORG[1]["id"]) + ")")
            time.sleep(0.3)
            f = js(sock, """(function(){
              var fo=document.getElementById('amvorg-form');
              if(!fo) return null;
              var k=fo.closest('.am-vorg-card');
              var fr=fo.getBoundingClientRect(), kr=k?k.getBoundingClientRect():null;
              var ti=document.getElementById('amvorg-f-titel');
              var pr=document.getElementById('amvorg-f-prompt');
              var tr=ti?ti.getBoundingClientRect():null, pp=pr?pr.getBoundingClientRect():null;
              return {inKarte:!!k, drin:(kr && fr.bottom<=kr.bottom+1 && fr.top>=kr.top-1),
                      titel:(ti||{}).value||'', breite:Math.round(fr.width),
                      // ⚠ Die FELDBREITE gehoert gemessen: `.form-group` bringt
                      // im Projekt keine mit, und ein fingerbreites Titelfeld
                      // sah in der reinen Struktur-Messung voellig richtig aus.
                      feldT:tr?Math.round(tr.width):0, feldP:pp?Math.round(pp.width):0,
                      feldHoehe:pp?Math.round(pp.height):0};
            })()""")
            check(f"[{thema}] das Formular klappt IN der Karte auf",
                  f and f["inKarte"] and f["drin"], json.dumps(f))
            check(f"[{thema}] und traegt den Titel der Vorgabe",
                  f and f["titel"] == VORG[1]["titel"], str((f or {}).get("titel"))[:60])
            check(f"[{thema}] ⚠ die Eingabefelder nutzen die Breite (>= 70 %)",
                  f and f["feldT"] >= f["breite"] * 0.7 and f["feldP"] >= f["breite"] * 0.7,
                  json.dumps(f))
            check(f"[{thema}] das Textfeld ist mehrzeilig hoch (>= 70 px)",
                  f and f["feldHoehe"] >= 70, str((f or {}).get("feldHoehe")))

            # Kontrast des Hinweistextes (er traegt die wichtigste Aussage).
            kf = js(sock, """(function(){
              var p=document.querySelector('#am-sect-vorg-body .kb-hint');
              var e=p, g=null;
              while(e && !g){var c=getComputedStyle(e).backgroundColor;
                if(c && c!=='rgba(0, 0, 0, 0)' && !/, 0\\)$/.test(c)) g=c; e=e.parentElement;}
              return {vg:getComputedStyle(p).color, bg:g||getComputedStyle(document.body).backgroundColor};
            })()""")
            k = kontrast(farbe(kf["vg"]), farbe(kf["bg"]))
            check(f"[{thema}] Hinweistext lesbar (>= 4,5:1)", k >= 4.5,
                  f"{k:.2f}:1  {kf['vg']} auf {kf['bg']}")

            r = cdp(sock, "Page.captureScreenshot", format="png",
                    clip={"x": 0, "y": 0, "width": 900, "height": 800, "scale": 1})
            p = BILDER / f"vorgaben-{thema}.png"
            p.write_bytes(base64.b64decode(r["data"]))
            print(f"       Screenshot: {p}")
finally:
    try:
        chrome.kill()
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(PROFIL, ignore_errors=True)
    ZIEL.unlink(missing_ok=True)
    check("Probeseite wieder entfernt", not ZIEL.exists())

print("\n" + "=" * 74)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
print("=" * 74)
sys.exit(1 if _fail else 0)
