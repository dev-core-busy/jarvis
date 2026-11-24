#!/usr/bin/env python3
"""Optische Abnahme (DEV, echtes Chrome): Vorschlaege und Vorschau "Interne Netze".

KI & System -> System-Einstellungen, Zeile "Interne Netze" (seit 2026-11-24):
unter dem Feld stehen Vorschlaege des Servers (eigene Schnittstellen,
oeffentliche Profiladressen), ein Klick traegt sie ein, und eine Vorschau
nennt VOR dem Speichern, welches Profil seine Einstufung wechselt. jsdom
rechnet kein Layout (tests/test_interne_netze_ui.js misst das Verhalten) –
ob die Knoepfe in der Tabelle bleiben und die Vorschau zu sehen ist, sieht
nur ein Browser.

Gemessen je Thema (dunkel/hell):
  - Positivkontrolle: Feld und Vorschlagszeile sind sichtbar, mindestens ein
    Vorschlag ist da (sonst Exit 2 – dann misst der Rest nichts);
  - kein Vorschlagsknopf ragt rechts aus der Tabelle;
  - Feld LEEREN (wie ein Benutzer, per Eingabe-Ereignis): die Vorschau
    erscheint, ist sichtbar und nennt mindestens einen Wechsel;
  - es wird NICHTS gespeichert: die Liste auf dem Server ist am Ende dieselbe.
Bilder ins HOME: interne-netze-<thema>.png.

Einstellungen braucht einen Administrator, und den gibt es nur ueber den
eigenen 2FA-Code (BSI M3); die Codes liefert live_mit_brokercode.py:

    python3 tests/live_mit_brokercode.py tests/live_interne_netze_ui_dev.py <benutzer>
                                                               (root, auf DEV)
Exit 0 = gehalten, 1 = Befund, 2 = konnte nicht laufen.
"""
import base64
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, "/opt/jarvis/tests/lib")
_KTX = ssl._create_unverified_context()
HOME = os.path.expanduser("~")
_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text + (f"  [{info}]" if info else ""))


def api(tok, methode, pfad, rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    req = urllib.request.Request("https://127.0.0.1" + pfad, data=daten, method=methode,
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=_KTX, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main(benutzer: str) -> int:
    try:
        import websocket
        from backend import main as M
        from zweifaktor_code import code_quelle
    except Exception as e:  # noqa: BLE001
        print(f"ABBRUCH: {e}")
        return 2
    auth = M._get_user_auth_state(benutzer)
    if not auth.get("totp_enabled"):
        print(f"ABBRUCH: Konto {benutzer} hat keine 2FA – ohne Code keine Admin-Sitzung")
        return 2
    neuer_code = code_quelle(auth.get("totp_secret"))
    tok = M.generate_token(benutzer)
    st, r = api(tok, "POST", "/api/admin/erhoehen", {"code": neuer_code()})
    if st != 200 or not r.get("erhoeht"):
        print(f"ABBRUCH: Erhoehung gelang nicht -> {st} {str(r)[:200]}")
        return 2
    st, s = api(tok, "GET", "/api/settings")
    if st != 200 or "interne_netze" not in s:
        print(f"ABBRUCH: /api/settings {st} ohne interne_netze")
        return 2
    vor_netze = s.get("interne_netze", "")

    port, prof = 9373, os.path.join(HOME, ".chrome-interne-netze")
    subprocess.run(["rm", "-rf", prof], check=False)
    log = open(os.path.join(HOME, "chrome-interne-netze.log"), "w")
    p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={port}",
                          f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                          "--remote-allow-origins=*", "--window-size=1400,1000", "--no-first-run",
                          "about:blank"], stdout=log, stderr=log)
    time.sleep(6)
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
    ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
    n = [0]

    def cmd(m, params=None):
        n[0] += 1
        ws.send(json.dumps({"id": n[0], "method": m, "params": params or {}}))
        while True:
            d = json.loads(ws.recv())
            if d.get("id") == n[0]:
                return d.get("result", {})

    def js(code):
        r = cmd("Runtime.evaluate", {"expression": code, "returnByValue": True, "awaitPromise": True})
        return (r.get("result") or {}).get("value")

    def bild(name, sel):
        r = js("(function(){var e=document.querySelector(%s);if(!e)return null;e.scrollIntoView({block:'center'});"
               "var b=e.getBoundingClientRect();return {x:b.left+scrollX,y:b.top+scrollY,w:b.width,h:b.height};})()"
               % json.dumps(sel))
        if not r:
            return
        time.sleep(0.4)
        d = cmd("Page.captureScreenshot", {"format": "png", "clip": {
            "x": max(0, r["x"] - 10), "y": max(0, r["y"] - 10), "width": r["w"] + 20,
            "height": r["h"] + 20, "scale": 1}}).get("data", "")
        with open(os.path.join(HOME, name), "wb") as fh:
            fh.write(base64.b64decode(d))

    cmd("Runtime.enable")
    cmd("Page.enable")
    try:
        for thema in ("dark", "light"):
            print(f"\n── Thema {thema}")
            # Anmeldung wie live_agent_keys_ui_dev.py: Token ablegen, /portal
            # stellt es auf das HttpOnly-Cookie um (BSI H4)
            cmd("Page.navigate", {"url": "https://127.0.0.1/api/health"})
            time.sleep(2)
            js("localStorage.clear(); localStorage.setItem('jarvis_token', %s);"
               "localStorage.setItem('jarvis_user', %s); localStorage.setItem('jarvis_theme', %s);"
               "localStorage.setItem('jarvis_lang','de'); true"
               % (json.dumps(tok), json.dumps(benutzer), json.dumps(thema)))
            cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
            for _ in range(30):
                if js("(localStorage.getItem('jarvis_token')||'').indexOf('JCS1.')===0"):
                    break
                time.sleep(1)
            else:
                print("ABBRUCH: Sitzung wurde nicht auf das Cookie umgestellt")
                return 2
            # Die Cookie-Sitzung ist eine neue Sitzung: eigene Erhoehung (Zahnrad)
            erh = js("fetch('/api/admin/erhoehen',{method:'POST',headers:{'Content-Type':'application/json',"
                     "'Authorization':'Bearer '+(window.JarvisSitzung?JarvisSitzung.token():localStorage.getItem('jarvis_token'))},"
                     "body:JSON.stringify({code:%s})}).then(r=>r.status)" % json.dumps(neuer_code()))
            cmd("Page.navigate", {"url": "https://127.0.0.1/settings"})
            time.sleep(6)
            js("(function(){var b=document.getElementById('prof-sect-tuning-body');"
               "if(b&&b.style.display==='none')document.getElementById('prof-sect-tuning-hdr').click();})()")
            time.sleep(3)
            m = js("""(function(){
              var f=document.getElementById('setting-interne-netze'), v=document.getElementById('interne-netze-vorschlaege');
              if(!f||!v) return null;
              var t=v.closest('table'), tb=t?t.getBoundingClientRect():null, vb=v.getBoundingClientRect();
              var k=[...v.querySelectorAll('button[data-netz]')].map(function(b){var r=b.getBoundingClientRect();
                return {netz:b.dataset.netz,r:Math.round(r.right),w:Math.round(r.width),h:Math.round(r.height)};});
              return {feldSichtbar:f.offsetParent!==null, zeileSichtbar:v.offsetParent!==null && vb.height>0,
                      tabR:tb?Math.round(tb.right):null, knoepfe:k, text:v.textContent.slice(0,200)};})()""")
            if not m or not m["feldSichtbar"] or not m["zeileSichtbar"] or not m["knoepfe"]:
                print(f"ABBRUCH: Feld/Vorschlaege nicht sichtbar oder leer (Erhoehung {erh}): {m}")
                return 2
            check("Positivkontrolle: Feld und Vorschlaege sichtbar, %d Vorschlag/Vorschlaege" % len(m["knoepfe"]), True)
            print("  (Vorschlaege: %s)" % [k["netz"] for k in m["knoepfe"]])
            check("kein Vorschlag ragt rechts aus der Tabelle",
                  all(k["r"] <= m["tabR"] + 1 for k in m["knoepfe"]), str(m))
            check("Vorschlagsknoepfe haben Groesse (gezeichnet)",
                  all(k["w"] > 40 and k["h"] > 15 for k in m["knoepfe"]), str(m["knoepfe"]))
            # Wie ein Benutzer: Feld leeren -> Vorschau (nichts speichern!)
            js("(function(){var f=document.getElementById('setting-interne-netze');f.value='';"
               "f.dispatchEvent(new Event('input'));})()")
            time.sleep(3)
            pv = js("""(function(){var b=document.getElementById('interne-netze-vorschau');
              var r=b.getBoundingClientRect(); return {sichtbar:b.offsetParent!==null&&r.height>0,
              text:b.textContent, farbe:getComputedStyle(b).color};})()""")
            check("Vorschau erscheint nach der Eingabe", bool(pv) and pv["sichtbar"], str(pv))
            check("Vorschau nennt einen Wechsel (intern -> extern) und dass erst Speichern wirkt",
                  bool(pv) and "→" in pv["text"] and "Speichern" in pv["text"], str(pv and pv["text"]))
            print("  (Vorschau: %s)" % (pv and pv["text"]))
            bild(f"interne-netze-{thema}.png", "tr.netze-hilfe")
            st, s = api(tok, "GET", "/api/settings")
            check("nichts gespeichert: Liste auf dem Server unveraendert",
                  st == 200 and s.get("interne_netze", "") == vor_netze, f"{st} {s.get('interne_netze')!r}")
    finally:
        try:
            ws.close()
        finally:
            p.terminate()
        # Sicherheitsnetz: stand die Liste doch anders, den Vorzustand herstellen
        st, s = api(tok, "GET", "/api/settings")
        if st == 200 and s.get("interne_netze", "") != vor_netze:
            api(tok, "POST", "/api/settings", {"interne_netze": vor_netze})
            print("  ! Liste war veraendert – Vorzustand zurueckgestellt")
    print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
    return 1 if _fail else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
