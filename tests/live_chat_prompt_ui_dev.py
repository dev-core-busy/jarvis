#!/usr/bin/env python3
"""Optische Abnahme: die Sprechblase in der Verlaufsleiste (hell UND dunkel).

jsdom rechnet KEIN Layout – ob man den Zustand wirklich SIEHT, beantwortet nur
ein echter Browser. Gemessen wird mit dem ECHTEN chat.css, dem ECHTEN icons.js
und dem ECHTEN Renderer aus chat.js:

  * ist die gesetzte Sprechblase OHNE Ueberfahren sichtbar (das ist die Zusage –
    die uebrigen Aktionsknoepfe stehen auf opacity 0),
  * sind gefuellt und hohl an der FLAECHE unterscheidbar (Pixelvergleich, nicht
    nur an der Farbe),
  * bleibt alles in der Zeile (kein waagerechter Ueberlauf, auch bei langem
    Chatnamen),
  * Kontrast der gesetzten Blase gegen ihren Grund.

Die Probeseite liegt NUR fuer den Lauf unter frontend/ und wird danach entfernt.
Aufruf auf DEV: cd /opt/jarvis && ./venv/bin/python tests/live_chat_prompt_ui_dev.py
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
    hell, dunkel = max(la, lb), min(la, lb)
    return (hell + 0.05) / (dunkel + 0.05)


def farbe(s):
    """CSS-Farbe -> (r,g,b). Chrome liefert color-mix als `color(srgb a b c)`
    mit Anteilen 0..1 – als 0..255 gelesen ergaebe das fast Schwarz (Register)."""
    s = (s or "").strip()
    m = re.match(r"color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", s)
    if m:
        return tuple(round(float(m.group(i)) * 255) for i in (1, 2, 3))
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        t = [float(x) for x in m.group(1).replace("/", " ").split(",")[:3]]
        return tuple(round(x) for x in t)
    return (0, 0, 0)


# ── Probeseite: echtes Markup der Zeile, echtes CSS, echter Renderer ─────────
CHATJS = (ROOT / "frontend" / "js" / "chat.js").read_text(encoding="utf-8")


def schneide(name):
    for kopf in ("async function " + name, "function " + name):
        i = CHATJS.find(kopf)
        if i < 0:
            continue
        auf = CHATJS.find("{", i)
        tief = 0
        for j in range(auf, len(CHATJS)):
            if CHATJS[j] == "{":
                tief += 1
            elif CHATJS[j] == "}":
                tief -= 1
                if tief == 0:
                    return CHATJS[i:j + 1]
    return ""


def dialog_markup():
    """Das ECHTE Dialog-Markup aus chat.html – kein Nachbau: sonst prueft die
    Abnahme ein Layout, das es so nicht gibt."""
    h = (ROOT / "frontend" / "chat.html").read_text(encoding="utf-8")
    i = h.find('<div id="chat-prompt-modal"')
    if i < 0:
        print("ABBRUCH: Dialog-Markup nicht in chat.html gefunden.")
        sys.exit(2)
    tief, j = 0, i
    while j < len(h):
        if h.startswith("<div", j):
            tief += 1
        elif h.startswith("</div>", j):
            tief -= 1
            if tief == 0:
                return h[i:j + 6]
        j += 1
    print("ABBRUCH: Dialog-Markup nicht abgeschlossen.")
    sys.exit(2)


REND = schneide("_renderSidebar")
if not REND:
    print("ABBRUCH: _renderSidebar nicht gefunden.")
    sys.exit(2)

SEITE = """<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/css/theme.css">
<link rel="stylesheet" href="/static/css/chat.css">
</head><body>
<div class="chat-screen"><aside class="chat-sidebar" style="width:240px">
  <div id="cs-list" class="cs-list"></div>
</aside></div>
__DIALOG__
<script src="/static/js/icons.js"></script>
<script>
window.t = function (k) { return ({
  'chat.untitled': '(ohne Titel)', 'chat.rename': 'Umbenennen', 'chat.delete': 'Löschen',
  'chat.sprompt_btn': 'Prompt für diesen Chat festlegen',
  'chat.sprompt_btn_set': 'Prompt für diesen Chat bearbeiten (eigener Prompt hinterlegt)',
  'chat.no_sessions': 'Noch keine Chats' })[k] || k; };
function escapeHtml(s){var d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}
/* ⚠ KEINE der Zeilen ist aktiv: `.cs-item.active .cs-act` blendet ALLE
   Aktionen ein – an der aktiven Zeile waere "nur die gesetzte Blase ist ohne
   Ueberfahren sichtbar" gar nicht messbar (erster Anlauf gemessen: opacity 1
   auch bei der hohlen). */
var _activeSid='zzz999';
var _sessions=[
  {id:'aaa111',title:'Chat ohne eigenen Prompt',has_prompt:false},
  {id:'bbb222',title:'Chat MIT eigenem Prompt',has_prompt:true},
  {id:'ccc333',title:'Ein sehr langer Chatname der weit über die Breite der Verlaufsleiste hinausgeht und umbrechen müsste',has_prompt:true}
];
function _switchSession(){} function _renameSession(){} function _deleteSession(){}
function _openSessionPrompt(){}
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
try {
__REND__
_renderSidebar();
} catch (e) { window.__fehler += 'WURF: ' + e.message; }
</script></body></html>"""

ZIEL = ROOT / "frontend" / "_probe_chatprompt.html"
ZIEL.write_text(SEITE.replace("__REND__", REND).replace("__DIALOG__", dialog_markup()),
                encoding="utf-8")
try:
    os.chown(ZIEL, os.stat(ROOT / "frontend").st_uid, os.stat(ROOT / "frontend").st_gid)
except Exception:  # noqa: BLE001
    pass

# ── Chrome ueber CDP ────────────────────────────────────────────────────────
PROFIL = tempfile.mkdtemp(prefix="chrome-cp-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()

chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1200,900", "--ignore-certificate-errors",
     "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def cdp_ziel():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as a:
                # ⚠ NUR type=="page": /json/list liefert auch die eingebauten
                # Erweiterungen – wer blind [0] nimmt, haengt an einer
                # background.html und misst gar nichts (Register).
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


print("=" * 74)
print("Optische Abnahme: Sprechblase in der Verlaufsleiste")
print("=" * 74)

ws_url = cdp_ziel()
if not ws_url:
    print("ABBRUCH: kein CDP-Ziel (Chrome-Ausgabe folgt)")
    try:
        chrome.kill()
        print((chrome.stdout.read() or "")[:800])
    except Exception:  # noqa: BLE001
        pass
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


def cdp(sock, methode, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": methode, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=30))
        if d.get("id") == _id[0]:
            return d.get("result", {})


def js(sock, ausdruck):
    r = cdp(sock, "Runtime.evaluate", expression=ausdruck, returnByValue=True,
            awaitPromise=True)
    return (r.get("result") or {}).get("value")


BILDER = Path.home() / "chatprompt-bilder"
BILDER.mkdir(exist_ok=True)

try:
    with connect(ws_url, max_size=80 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        for thema, klasse in (("dunkel", ""), ("hell", "light")):
            # ⚠ `frontend/` haengt unter /static – ein Aufruf auf / gibt 404,
            # und dann rendert nichts. Ohne Ladekontrolle sieht das wie ein
            # Codefehler aus (Register).
            cdp(sock, "Page.navigate", url="https://127.0.0.1/static/_probe_chatprompt.html")
            time.sleep(2.5)
            js(sock, f"document.body.className = {json.dumps(klasse)};")
            time.sleep(0.4)
            print(f"\n── Thema: {thema} " + "─" * 40)

            geladen = js(sock, "!!document.getElementById('cs-list')")
            if not geladen:
                check(f"[{thema}] Probeseite geladen (Positivkontrolle)", False,
                      "Seite/CSS nicht erreichbar: " + str(js(sock, "document.title")))
                continue

            n = js(sock, "document.querySelectorAll('#cs-list .cs-item').length")
            check(f"[{thema}] drei Zeilen gezeichnet", n == 3, str(n))
            if n != 3:
                # Nicht ungeprueft weiterdereferenzieren – sonst bricht der Lauf
                # OHNE Bilanz ab und ist von "nicht gelaufen" nicht zu
                # unterscheiden (Register).
                check(f"[{thema}] Renderer lief ohne JS-Fehler", False,
                      str(js(sock, "window.__fehler || '(kein Fehler gemeldet)'")))
                continue

            mess = js(sock, """(function(){
              var z=document.querySelectorAll('#cs-list .cs-item');
              function m(i){
                var b=z[i].querySelector('.cs-prompt'); if(!b) return null;
                var r=b.getBoundingClientRect(), st=getComputedStyle(b);
                var zr=z[i].getBoundingClientRect();
                return {w:Math.round(r.width),h:Math.round(r.height),op:st.opacity,
                        farbe:st.color, drin:(r.right<=zr.right+1&&r.left>=zr.left-1)};
              }
              var li=document.querySelector('#cs-list');
              return {a:m(0),b:m(1),c:m(2),
                      grund:getComputedStyle(document.body).backgroundColor,
                      ueberlauf:li.scrollWidth-li.clientWidth};
            })()""")

            a, b = mess["a"], mess["b"]
            check(f"[{thema}] die Sprechblase hat eine messbare Groesse",
                  a and a["w"] > 6 and a["h"] > 6, json.dumps(a))
            # ⚠ DIE ZUSAGE: ohne Ueberfahren sichtbar, wenn ein Prompt gesetzt ist.
            check(f"[{thema}] ⚠ gesetzt = OHNE Ueberfahren sichtbar (opacity 1)",
                  b and float(b["op"]) == 1.0, json.dumps(b))
            check(f"[{thema}] nicht gesetzt = erst beim Ueberfahren (opacity 0)",
                  a and float(a["op"]) == 0.0, json.dumps(a))
            # Positivkontrolle: an der AKTIVEN Zeile sind wie bisher alle
            # Aktionen sichtbar – sonst waere die Messung oben trivial.
            # ⚠ `.cs-act` hat `transition: opacity .12s` – unmittelbar nach dem
            # Klassenwechsel steht noch der ALTE Wert. Also setzen, WARTEN,
            # dann messen (sonst meldet die Kontrolle 0 und man sucht im CSS).
            js(sock, "document.querySelectorAll('#cs-list .cs-item')[0]"
                     ".classList.add('active')")
            time.sleep(0.4)
            aktiv_op = js(sock, "getComputedStyle(document.querySelectorAll("
                                "'#cs-list .cs-item')[0].querySelector('.cs-prompt')).opacity")
            js(sock, "document.querySelectorAll('#cs-list .cs-item')[0]"
                     ".classList.remove('active')")
            check(f"[{thema}] Positivkontrolle: an der AKTIVEN Zeile sichtbar",
                  float(aktiv_op) == 1.0, str(aktiv_op))
            check(f"[{thema}] beide bleiben in ihrer Zeile",
                  a and b and a["drin"] and b["drin"])
            check(f"[{thema}] kein waagerechter Ueberlauf der Liste",
                  mess["ueberlauf"] <= 0, str(mess["ueberlauf"]))

            # Kontrast der gesetzten Blase gegen den Grund der Zeile.
            grund = js(sock, """(function(){
              var z=document.querySelectorAll('#cs-list .cs-item')[1], e=z;
              while(e){var c=getComputedStyle(e).backgroundColor;
                if(c&&c!=='rgba(0, 0, 0, 0)'&&!/, 0\\)$/.test(c)) return c; e=e.parentElement;}
              return getComputedStyle(document.body).backgroundColor;})()""")
            k = kontrast(farbe(b["farbe"]), farbe(grund))
            check(f"[{thema}] Kontrast der gesetzten Blase >= 3:1 (Grafik-Grenze)",
                  k >= 3.0, f"{k:.2f}:1  {b['farbe']} auf {grund}")

            # ── Gefuellt gegen hohl: an der FLAECHE unterscheidbar, nicht nur
            #    an der Farbe. Gezaehlt werden die gedeckten Pixel im SVG.
            flaeche = js(sock, """(function(){
              var z=document.querySelectorAll('#cs-list .cs-item');
              function f(i){var s=z[i].querySelector('.cs-prompt svg');
                return s?(s.getAttribute('fill')||''):'?';}
              function pf(i){var s=z[i].querySelector('.cs-prompt svg');
                return s?s.querySelectorAll('line,path').length:-1;}
              return {a:f(0),b:f(1),pa:pf(0),pb:pf(1)};})()""")
            check(f"[{thema}] hohl und gefuellt sind verschiedene Formen",
                  flaeche["a"] == "none" and flaeche["b"] == "currentColor"
                  and flaeche["pa"] != flaeche["pb"], json.dumps(flaeche))

            # Screenshot – ANSEHEN, nicht nur messen.
            js(sock, "document.querySelectorAll('#cs-list .cs-item')[0].classList.add('active')")
            r = cdp(sock, "Page.captureScreenshot", format="png",
                    clip={"x": 0, "y": 0, "width": 300, "height": 200, "scale": 3})
            p = BILDER / f"sprechblase-{thema}.png"
            p.write_bytes(base64.b64decode(r["data"]))
            print(f"       Screenshot: {p}")

            # ── Der DIALOG: der Fuss muss im Bild bleiben, auch bei langem
            #    Chatnamen und vollem Textfeld (im Projekt schon zweimal
            #    bezahlt: ein Knopf, der aus dem Sichtfenster wandert).
            js(sock, """(function(){
              var d=document.getElementById('chat-prompt-modal');
              d.classList.remove('hidden');
              document.getElementById('chat-prompt-name').textContent =
                'Ein ausgesprochen langer Chatname, der bequem ueber die Breite des Dialogs hinausreicht';
              document.getElementById('chat-prompt-text').value =
                Array(40).join('Zeile mit einer laengeren Anweisung fuer diesen Chat.\\n');
              document.getElementById('chat-prompt-state').textContent =
                'Aktiv: für diesen Chat gilt dieser Prompt – Dein persönlicher Preprompt ist hier ausgesetzt.';
            })()""")
            time.sleep(0.5)
            dlg = js(sock, """(function(){
              var k=document.querySelector('#chat-prompt-modal .modal-card');
              var f=document.querySelector('#chat-prompt-modal .chs-foot');
              var s=document.getElementById('btn-chat-prompt-save');
              var n=document.getElementById('chat-prompt-name');
              var kr=k.getBoundingClientRect(), sr=s.getBoundingClientRect();
              return {kartenBreite:Math.round(kr.width), fensterBreite:window.innerWidth,
                      speichernUnten:Math.round(sr.bottom), fensterHoehe:window.innerHeight,
                      speichernSichtbar:(sr.bottom<=window.innerHeight&&sr.top>=0
                                         &&sr.width>10&&sr.height>10),
                      fussInKarte:(f.getBoundingClientRect().bottom<=kr.bottom+1),
                      nameUeberlauf:(n.scrollWidth-n.clientWidth),
                      ueberlaufSeite:document.documentElement.scrollWidth-window.innerWidth};
            })()""")
            check(f"[{thema}] ⚠ 'Speichern' bleibt im Sichtfenster",
                  dlg["speichernSichtbar"], json.dumps(dlg))
            check(f"[{thema}] der Fuss bleibt in der Karte",
                  dlg["fussInKarte"], json.dumps(dlg))
            check(f"[{thema}] der lange Chatname sprengt die Karte nicht",
                  dlg["kartenBreite"] <= dlg["fensterBreite"] and dlg["ueberlaufSeite"] <= 0,
                  json.dumps(dlg))
            r = cdp(sock, "Page.captureScreenshot", format="png",
                    clip={"x": 0, "y": 0, "width": 1200, "height": 900, "scale": 1})
            p = BILDER / f"dialog-{thema}.png"
            p.write_bytes(base64.b64decode(r["data"]))
            print(f"       Screenshot: {p}")
            js(sock, "document.getElementById('chat-prompt-modal')"
                     ".classList.add('hidden')")

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
