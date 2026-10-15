#!/usr/bin/env python3
"""Optische Abnahme der Knoepfe unter /ai-mouse -> „Meine Fragen".

Gemeldet 2026-09-10: „Button 'Neue Frage' ist nicht im CI". jsdom rechnet kein
Layout - ob ein Knopf wie die uebrigen AUSSIEHT, kann nur ein echter Browser
beantworten. Gemessen wird deshalb am gerenderten Rechteck: Hintergrundfarbe,
Rahmen, Polsterung und Breite gegen den BESTANDSKNOPF derselben Seite.

⚠ Ueber einen HTTP-Server, NICHT ueber file:// - ES-Module und die absoluten
Pfade `/static/...` laden dort nicht (Register).

    python3 tests/live_am_knopf_ui.py
"""
import base64
import http.server
import json
import os
import pathlib
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONT = ROOT / "frontend"
ok = fail = 0


def c(text: str, bed: bool) -> None:
    global ok, fail
    if bed:
        ok += 1
        print(f"  OK   {text}")
    else:
        fail += 1
        print(f"  FAIL {text}")


PROBE = """<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/css/theme.css">
<link rel="stylesheet" href="/static/css/jira_addon.css">
</head><body>
<script>if(localStorage.getItem('jarvis_theme')!=='dark')document.body.classList.add('light');</script>
<main class="ja-main">
<section class="ja-card"><div class="ja-card-body">
  <h2>Anwendung holen</h2>
  <div class="ja-dl">
    <button type="button" class="ja-btn ja-btn-haupt" id="am-download">Paket herunterladen</button>
  </div>
  <h2>Meine Fragen</h2>
  <div id="am-fragen">
    <div class="am-q-card"><div class="am-q-row"><div class="am-q-main">
      <div class="am-q-name">Text erkennen</div>
      <div class="am-q-meta">Gib den Text im Bild wieder.</div>
    </div><div class="am-q-acts"></div></div></div>
  </div>
  __ZEILE__
  <div class="am-q-edit"><div class="am-q-acts-form">__FORM__</div></div>
</div></section></main></body></html>"""

ZEILE_NEU = ('<div class="ja-dl"><button type="button" class="ja-btn" '
             'id="am-frage-neu">Neue Frage</button></div>')
ZEILE_ALT = ('<div class="ja-actions"><button class="btn-secondary" '
             'id="am-frage-neu">Neue Frage</button></div>')
FORM_NEU = ('<button type="button" class="ja-btn ja-btn-haupt" id="am-f-save">Speichern</button>'
            '<button type="button" class="ja-btn" id="am-f-cancel">Abbrechen</button>')
FORM_ALT = ('<button class="btn-primary" id="am-f-save">Speichern</button>'
            '<button class="btn-secondary" id="am-f-cancel">Abbrechen</button>')


def freier_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main() -> int:
    global ok, fail

    # Probeseiten schreiben - NUR fuer den Lauf, danach entfernt.
    seiten = {}
    for name, zeile, form in [("neu", ZEILE_NEU, FORM_NEU), ("alt", ZEILE_ALT, FORM_ALT)]:
        p = FRONT / f".probe_am_{name}.html"
        p.write_text(PROBE.replace("__ZEILE__", zeile).replace("__FORM__", form),
                     encoding="utf-8")
        seiten[name] = p

    port = freier_port()
    hdl = http.server.SimpleHTTPRequestHandler

    class H(hdl):
        def translate_path(self, path):
            path = path.split("?")[0]
            if path.startswith("/static/"):
                return str(FRONT / path[len("/static/"):])
            return str(FRONT / path.lstrip("/"))

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    try:
        werte = {}
        for name in ("neu", "alt"):
            for thema in ("dunkel", "hell"):
                werte[(name, thema)] = chrome_messen(port, name, thema)
        bewerten(werte)
    finally:
        srv.shutdown()
        for p in seiten.values():
            p.unlink(missing_ok=True)

    print(f"\n{ok} OK, {fail} FAIL")
    return 1 if fail else 0


def chrome_messen(port: int, seite: str, thema: str) -> dict:
    """Rendert die Probeseite und liest die Werte ueber CDP aus."""
    dbg = freier_port()
    prof = tempfile.mkdtemp(dir=str(pathlib.Path.home()), prefix=".chrome-am-")
    url = f"http://127.0.0.1:{port}/.probe_am_{seite}.html"
    proc = subprocess.Popen(
        ["google-chrome", "--headless=new", f"--remote-debugging-port={dbg}",
         "--remote-allow-origins=*", "--no-sandbox", "--disable-gpu",
         f"--user-data-dir={prof}", "--window-size=1200,900", url],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        ws = None
        for _ in range(80):
            try:
                roh = urllib.request.urlopen(f"http://127.0.0.1:{dbg}/json/list", timeout=1).read()
                # ⚠ Auch die eingebauten Chrome-ERWEITERUNGEN stehen in der Liste -
                # wer blind [0] nimmt, haengt an chrome-extension:// (Register).
                for t in json.loads(roh):
                    if t.get("type") == "page" and ".probe_am_" in t.get("url", ""):
                        ws = t["webSocketDebuggerUrl"]
                        break
                if ws:
                    break
            except Exception:
                pass
            time.sleep(0.15)
        if not ws:
            print(f"  FAIL Chrome kam nicht hoch ({seite}/{thema})")
            print("       " + proc.stderr.read(400).decode("utf-8", "replace"))
            return {}
        return ws_messen(ws, thema)
    finally:
        proc.kill()
        proc.wait(timeout=10)
        subprocess.run(["rm", "-rf", prof], check=False)


def ws_messen(ws_url: str, thema: str) -> dict:
    """Minimaler CDP-Client ueber die Websocket-Bibliothek von Python."""
    import struct
    import ssl  # noqa
    from urllib.parse import urlparse

    u = urlparse(ws_url)
    s = socket.create_connection((u.hostname, u.port), timeout=10)
    schluessel = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\nOrigin: http://127.0.0.1\r\n\r\n"
               % (u.path, u.hostname, u.port, schluessel)).encode())
    puffer = b""
    while b"\r\n\r\n" not in puffer:
        puffer += s.recv(4096)

    def senden(nachricht: str) -> None:
        daten = nachricht.encode()
        kopf = b"\x81"
        maske = os.urandom(4)
        n = len(daten)
        if n < 126:
            kopf += bytes([0x80 | n])
        elif n < 65536:
            kopf += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            kopf += bytes([0x80 | 127]) + struct.pack(">Q", n)
        s.sendall(kopf + maske + bytes(b ^ maske[i % 4] for i, b in enumerate(daten)))

    def lesen() -> str:
        kopf = s.recv(2)
        laenge = kopf[1] & 0x7F
        if laenge == 126:
            laenge = struct.unpack(">H", s.recv(2))[0]
        elif laenge == 127:
            laenge = struct.unpack(">Q", s.recv(8))[0]
        daten = b""
        while len(daten) < laenge:
            daten += s.recv(laenge - len(daten))
        return daten.decode("utf-8", "replace")

    def rufe(mid: int, methode: str, params: dict):
        senden(json.dumps({"id": mid, "method": methode, "params": params}))
        while True:
            antwort = json.loads(lesen())
            if antwort.get("id") == mid:
                return antwort

    thema_js = ("document.body.classList.%s('light');"
                % ("remove" if thema == "dunkel" else "add"))
    js = thema_js + """
    JSON.stringify((() => {
      const g = id => { const e = document.getElementById(id); if (!e) return null;
        const s = getComputedStyle(e), r = e.getBoundingClientRect();
        return {bg: s.backgroundColor, farbe: s.color, randbreite: s.borderTopWidth,
                randfarbe: s.borderTopColor, padding: s.paddingTop + ' ' + s.paddingLeft,
                radius: s.borderTopLeftRadius, breite: Math.round(r.width),
                hoehe: Math.round(r.height), font: s.fontSize,
                familie: s.fontFamily.split(',')[0]}; };
      const d = document.documentElement;
      return {neu: g('am-frage-neu'), dl: g('am-download'), save: g('am-f-save'),
              cancel: g('am-f-cancel'), ueberlauf: d.scrollWidth > d.clientWidth + 1};
    })())
    """
    rufe(1, "Runtime.enable", {})
    # ⚠ DAS TARGET EXISTIERT, BEVOR DIE SEITE GELADEN IST - wer sofort misst,
    # misst ein leeres DOM und meldet "alle Knoepfe fehlen" (so beim ersten Lauf
    # passiert). Also auf readyState warten, mit ausdruecklichem Fehlschlag.
    mid = 2
    for _ in range(60):
        a = rufe(mid, "Runtime.evaluate",
                 {"expression": "document.readyState + '|' + "
                                "document.querySelectorAll('button').length",
                  "returnByValue": True})
        mid += 1
        wert = a.get("result", {}).get("result", {}).get("value", "")
        if str(wert).startswith("complete") and not str(wert).endswith("|0"):
            break
        time.sleep(0.1)
    else:
        s.close()
        return {}
    antwort = rufe(mid, "Runtime.evaluate", {"expression": js, "returnByValue": True})
    s.close()
    return json.loads(antwort["result"]["result"]["value"])


def bewerten(werte: dict) -> None:
    for thema in ("dunkel", "hell"):
        neu = werte[("neu", thema)]
        alt = werte[("alt", thema)]
        if not neu or not alt:
            c(f"[{thema}] Messung gelungen", False)
            continue
        n, dl, sv, ca = neu["neu"], neu["dl"], neu["save"], neu["cancel"]
        a = alt["neu"]
        # Nie ungeprueft dereferenzieren: ein fehlendes Element liesse den Lauf
        # ABBRECHEN statt fehlzuschlagen - das ist von "nicht gelaufen" nicht zu
        # unterscheiden (Register).
        if not all([n, dl, sv, ca, a]):
            fehlt = [k for k, v in (("neu", n), ("download", dl), ("save", sv),
                                    ("cancel", ca), ("alt", a)) if not v]
            c(f"[{thema}] alle Knoepfe gefunden - es fehlen: {fehlt}", False)
            continue
        # Positivkontrolle: ohne sie waere jede Aussage unten trivial wahr.
        c(f"[{thema}] Positivkontrolle: der Knopf hat eine Groesse "
          f"({n['breite']}x{n['hoehe']})", n["breite"] > 40 and n["hoehe"] > 20)
        c(f"[{thema}] 'Neue Frage' hat dieselbe Hoehe wie 'Paket herunterladen' "
          f"({n['hoehe']} vs {dl['hoehe']})", n["hoehe"] == dl["hoehe"])
        c(f"[{thema}] dieselbe Polsterung ({n['padding']})", n["padding"] == dl["padding"])
        c(f"[{thema}] derselbe Radius ({n['radius']})", n["radius"] == dl["radius"])
        c(f"[{thema}] dieselbe Schrift ({n['familie']} {n['font']})",
          n["font"] == dl["font"] and n["familie"] == dl["familie"])
        c(f"[{thema}] er traegt einen Rahmen ({n['randbreite']})",
          n["randbreite"] not in ("0px", ""))
        c(f"[{thema}] und NICHT den Akzent-Grund der Hauptaktion",
          n["bg"] != dl["bg"])
        c(f"[{thema}] 'Speichern' ist die Hauptaktion (Akzent-Grund)",
          sv["bg"] == dl["bg"])
        c(f"[{thema}] 'Abbrechen' ist es nicht", ca["bg"] == n["bg"])
        c(f"[{thema}] kein waagerechter Ueberlauf", not neu["ueberlauf"])
        # GEGENPROBE IM BROWSER: der GEMELDETE Stand muss messbar anders sein -
        # ohne sie waere nicht belegt, dass die Messung den Fehler ueberhaupt
        # zeigen kann.
        c(f"[{thema}] Gegenprobe: der Altstand sah wirklich anders aus "
          f"(alt {a['padding']}/{a['radius']} vs neu {n['padding']}/{n['radius']})",
          a["padding"] != n["padding"] or a["radius"] != n["radius"]
          or a["familie"] != n["familie"])


if __name__ == "__main__":
    raise SystemExit(main())
