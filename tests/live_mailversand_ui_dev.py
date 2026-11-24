#!/usr/bin/env python3
"""Abnahme im echten Chrome (DEV): Container "E-Mail-Versand" unter KI & System.

Gemeldet am 2026-11-24, zweimal:
  * "TAB soll den Vorschlagswert eines Eingabefeldes uebernehmen" – die Vorgaben
    fuer Absenderadresse, Absendername und Betreff liessen sich nur abtippen;
  * "warum wird ALLES geloescht bei Fehlgeschlagen" – ein gescheitertes
    Speichern schrieb den alten Server-Stand in die Felder.

Gemessen je Thema (dunkel/hell):
  - Positivkontrolle: Container aufgeklappt, Status geladen, die drei Felder
    tragen die Vorgabe des Servers als Platzhalter (sonst Exit 2);
  - ein ECHTER Tastendruck (Input.dispatchKeyEvent, kein Skript-Ereignis) in
    jedem LEEREN Feld uebernimmt genau die Vorgabe;
  - ungueltiger Absender + Speichern: Meldung am Knopf, die Eingaben (Absender,
    Betreff, Empfaenger) bleiben stehen;
  - es wird NICHTS gespeichert: der Server-Stand ist am Ende derselbe.
Bilder ins HOME: mailversand-<thema>.png.

Einstellungen braucht einen Administrator mit eigenem 2FA-Code (BSI M3):
    python3 tests/live_mit_brokercode.py tests/live_mailversand_ui_dev.py <benutzer>
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
FELDER = (("mv-absender", "absender"), ("mv-absender-name", "absender_name"), ("mv-betreff", "betreff"))
STAND_FELDER = ("empfaenger", "relay", "quellen", "absender", "absender_name", "betreff")


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
        with urllib.request.urlopen(req, context=_KTX, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def stand(tok):
    st, s = api(tok, "GET", "/api/broker/mailversand/status")
    return st, ({k: s.get(k) for k in STAND_FELDER} if st == 200 else s)


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
    st, vorher = stand(tok)
    st2, voll = api(tok, "GET", "/api/broker/mailversand/status")
    if st != 200 or not voll.get("installiert") or not voll.get("vorgabe"):
        print(f"ABBRUCH: Status {st} ohne installierten Mailserver/Vorgaben: {str(voll)[:200]}")
        return 2
    vorgabe = voll["vorgabe"]

    port, prof = 9374, os.path.join(HOME, ".chrome-mailversand")
    subprocess.run(["rm", "-rf", prof], check=False)
    log = open(os.path.join(HOME, "chrome-mailversand.log"), "w")
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

    def taste_tab():
        for art in ("rawKeyDown", "keyUp"):
            cmd("Input.dispatchKeyEvent", {"type": art, "key": "Tab", "code": "Tab",
                                           "windowsVirtualKeyCode": 9, "nativeVirtualKeyCode": 9})

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
            js("fetch('/api/admin/erhoehen',{method:'POST',headers:{'Content-Type':'application/json',"
               "'Authorization':'Bearer '+(window.JarvisSitzung?JarvisSitzung.token():localStorage.getItem('jarvis_token'))},"
               "body:JSON.stringify({code:%s})}).then(r=>r.status)" % json.dumps(neuer_code()))
            cmd("Page.navigate", {"url": "https://127.0.0.1/settings"})
            time.sleep(6)
            js("(function(){var b=document.getElementById('prof-sect-mail-body');"
               "if(b&&b.style.display==='none')document.getElementById('prof-sect-mail-hdr').click();"
               "if(window.MailVersand)MailVersand.onShow();})()")
            time.sleep(4)
            m = js("""(function(){var r={};%s.forEach(function(id){var e=document.getElementById(id);
                 r[id]=e?{ph:e.getAttribute('placeholder'),tab:e.hasAttribute('data-tabfill'),
                 sichtbar:e.offsetParent!==null,wert:e.value}:null;});
                 r.status=(document.getElementById('mv-status')||{}).textContent;return r;})()"""
                   % json.dumps([f for f, _ in FELDER]))
            if not m or any(not m.get(f) or not m[f]["sichtbar"] for f, _ in FELDER) \
                    or m["mv-betreff"]["ph"] != vorgabe["betreff"]:
                print(f"ABBRUCH: Felder nicht sichtbar oder Vorgabe nicht geladen: {m}")
                return 2
            check("Positivkontrolle: Container offen, Vorgaben als Platzhalter", True)
            for fid, schl in FELDER:
                check(f"{fid}: Platzhalter = Vorgabe des Servers, per TAB markiert",
                      m[fid]["ph"] == vorgabe[schl] and m[fid]["tab"], str(m[fid]))
                js("(function(){var e=document.getElementById(%s);e.value='';e.dispatchEvent(new Event('input'));"
                   "e.focus();})()" % json.dumps(fid))
                taste_tab()
                time.sleep(0.3)
                w = js("document.getElementById(%s).value" % json.dumps(fid))
                check(f"{fid}: echter TAB im leeren Feld uebernimmt die Vorgabe", w == vorgabe[schl],
                      f"{w!r} statt {vorgabe[schl]!r}")
            # Fehlerfall wie gemeldet: ungueltiger Absender, Eingaben muessen bleiben
            js("""(function(){document.getElementById('mv-absender').value='kein absender';
                 document.getElementById('mv-betreff').value='[Probe]';
                 document.getElementById('mv-empfaenger').value='probe@beispiel.de';
                 document.getElementById('mv-speichern').click();})()""")
            time.sleep(5)
            f = js("""(function(){var r=document.getElementById('mv-result');return {
                 meldung:r.textContent, sichtbar:r.offsetParent!==null && r.style.display!=='none',
                 abs:document.getElementById('mv-absender').value,
                 betr:document.getElementById('mv-betreff').value,
                 empf:document.getElementById('mv-empfaenger').value};})()""")
            check("Fehler steht als Meldung am Knopf", bool(f) and f["sichtbar"] and "Absender" in f["meldung"], str(f))
            check("nach dem Fehler bleiben Absender, Betreff und Empfaenger stehen",
                  bool(f) and f["abs"] == "kein absender" and f["betr"] == "[Probe]"
                  and f["empf"] == "probe@beispiel.de", str(f))
            bild(f"mailversand-{thema}.png", "#mv-block")
            st, jetzt = stand(tok)
            check("nichts gespeichert: Server-Stand unveraendert", st == 200 and jetzt == vorher,
                  f"{st} {jetzt}")
    finally:
        try:
            ws.close()
        finally:
            p.terminate()
        st, jetzt = stand(tok)
        if st == 200 and jetzt != vorher:
            r = dict(vorher, aktion="speichern", empfaenger=",".join(vorher.get("empfaenger") or []))
            api(tok, "POST", "/api/broker/mailversand", r)
            print("  ! Stand war veraendert – Vorzustand zurueckgestellt")
    print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
    return 1 if _fail else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
