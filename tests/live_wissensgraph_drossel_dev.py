#!/usr/bin/env python3
"""Modell-Last in Einstellungen → Wissen → Wissensgraph, echter Dienst + Chrome (DEV).

Gemessen, was jsdom und die Attrappe nicht koennen:
  - der ECHTE Endpunkt nimmt gueltige Werte, weist Grenzverletzungen und die rohen
    JSON-Woerter NaN/Infinity mit 400 ab (nicht 500) und meldet sie im Status
  - Felder im echten Chrome: zeigen den Stand, Eingabe + Verlassen speichert,
    ungueltig springt zurueck; kein waagerechter Ueberlauf bei 1400 und 520 px
  - keine Skriptfehler in der Konsole
Die vorherigen Werte werden am Ende zurueckgeschrieben – auch bei einem Fehler.
Die Bilder liegen im HOME des Dienstbenutzers (nicht in /tmp, Register).

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_wissensgraph_drossel_dev.py
"""
import base64
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

import websocket

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
from backend.main import generate_token  # noqa: E402

TOK = generate_token("jarvis")
BASIS = "https://127.0.0.1"
HOME = os.path.expanduser("~")
KTX = ssl._create_unverified_context()
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % str(detail)) if detail else ""))


def api(pfad, roh=None):
    """Rueckgabe (Status, JSON). ``roh`` ist der Rumpf als TEXT – NaN laesst sich
    mit json.dumps zwar schreiben, soll hier aber sichtbar genau so ankommen."""
    r = urllib.request.Request(BASIS + pfad, method="POST" if roh is not None else "GET",
                               data=roh.encode() if roh is not None else None)
    r.add_header("Authorization", "Bearer " + TOK)
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=KTX, timeout=30) as a:
            return a.status, json.loads(a.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


EINST = "/api/wissensgraph/einstellungen"
s0, st0 = api("/api/wissensgraph/status")
vorher = (st0.get("einstellungen") or {})
if s0 != 200 or "rate_min_abstand_s" not in vorher:
    print("ABBRUCH: Status nicht lesbar (%s) – Dienst, Token oder Hauptschluessel?" % s0)
    sys.exit(2)
ZURUECK = json.dumps({k: vorher[k] for k in ("rate_min_abstand_s", "rate_max_pro_stunde")})
print("Vorher:", ZURUECK)
p = None
try:
    print("\n1. Endpunkt")
    s, d = api(EINST, '{"rate_min_abstand_s": 3.5, "rate_max_pro_stunde": 700}')
    check("gueltige Werte: 200", s == 200, s)
    e = (api("/api/wissensgraph/status")[1].get("einstellungen") or {})
    check("… im Status sichtbar", e.get("rate_min_abstand_s") == 3.5 and e.get("rate_max_pro_stunde") == 700, e)
    for rumpf in ('{"rate_min_abstand_s": 601}', '{"rate_max_pro_stunde": 100001}', '{"rate_min_abstand_s": -1}',
                  '{"rate_min_abstand_s": NaN}', '{"rate_min_abstand_s": Infinity}',
                  '{"rate_max_pro_stunde": Infinity}', '{"rate_max_pro_stunde": 10.5}'):
        s, _ = api(EINST, rumpf)
        check("abgewiesen mit 400: " + rumpf, s == 400, s)
    e = (api("/api/wissensgraph/status")[1].get("einstellungen") or {})
    check("Abweisungen aendern nichts", e.get("rate_min_abstand_s") == 3.5 and e.get("rate_max_pro_stunde") == 700, e)

    print("\n2. Oberflaeche")
    PORT, prof = 9362, os.path.join(HOME, ".chrome-wissensgraph-drossel")
    subprocess.run(["rm", "-rf", prof], check=False)
    log = open(os.path.join(HOME, "chrome-wissensgraph-drossel.log"), "w")
    p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                          f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                          "--remote-allow-origins=*", "--window-size=1400,1000", "--no-first-run", "about:blank"],
                         stdout=log, stderr=log)
    time.sleep(6)
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
    ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
    n = [0]
    fehler = []

    def cmd(m, params=None):
        n[0] += 1
        ws.send(json.dumps({"id": n[0], "method": m, "params": params or {}}))
        while True:
            d = json.loads(ws.recv())
            if d.get("method") == "Runtime.exceptionThrown":
                fehler.append(d["params"]["exceptionDetails"].get("text", "") + " " +
                              str((d["params"]["exceptionDetails"].get("exception") or {}).get("description", ""))[:600])
            if d.get("id") == n[0]:
                return d.get("result", {})

    def js(code):
        r = cmd("Runtime.evaluate", {"expression": code, "returnByValue": True, "awaitPromise": True})
        return (r.get("result") or {}).get("value")

    def warte(s):
        js("new Promise(r => setTimeout(r, %d))" % int(s * 1000))

    def bild(datei):
        """Das sichtbare Fenster – der Abschnitt liegt in einem inneren Scrollbereich,
        ein Ausschnitt ueber getBoundingClientRect zeigte dort nur leere Flaeche."""
        js("document.querySelector('[data-wg-zahl]').scrollIntoView({block:'center'})")
        warte(0.4)
        r = cmd("Page.captureScreenshot", {"format": "png"})
        open(os.path.join(HOME, datei), "wb").write(base64.b64decode(r.get("data") or b""))

    def seite_oeffnen(thema):
        """Das Thema steht in localStorage und wirkt beim Laden. Die Klasse ``light`` am
        body von Hand zu entfernen ergab ein Gemisch, das es im Betrieb nicht gibt."""
        cmd("Emulation.clearDeviceMetricsOverride")
        cmd("Page.navigate", {"url": BASIS + "/settings"})
        time.sleep(3)
        js("localStorage.setItem('jarvis_theme', %s)" % json.dumps(thema))
        cmd("Page.navigate", {"url": BASIS + "/settings"})
        time.sleep(6)
        js("document.querySelector('[data-settings-tab=\"knowledge\"]').click()")
        warte(1.5)
        js("(function(){var b=document.getElementById('kb-sect-wg-body');"
           "if(b.style.display==='none'){document.getElementById('kb-sect-wg-hdr').click();}})()")
        warte(3)

    def feld(k):
        return "document.querySelector('[data-wg-zahl=\"%s\"]')" % k

    def eingabe(k, wert):
        """Wie ein Mensch: fokussieren, ueberschreiben, verlassen."""
        js("(function(){var h=%s;h.focus();h.select();})()" % feld(k))
        cmd("Input.insertText", {"text": wert})
        js("%s.blur()" % feld(k))
        warte(1.5)

    cmd("Runtime.enable")
    cmd("Page.enable")
    cmd("Page.addScriptToEvaluateOnNewDocument",
        {"source": "try{localStorage.setItem('jarvis_token', %s);}catch(e){}" % json.dumps(TOK)})
    seite_oeffnen("dark")
    check("Positivkontrolle: Abschnitt offen, Status geladen",
          js("document.getElementById('kb-sect-wg-body').style.display!=='none'"
             "&&document.querySelectorAll('#wg-status dt').length>3"))
    check("Felder zeigen den Stand des Servers",
          js(feld("rate_min_abstand_s") + ".value") == "3.5" and js(feld("rate_max_pro_stunde") + ".value") == "700",
          js(feld("rate_min_abstand_s") + ".value"))
    meldung = "document.getElementById('wg-einst-meldung')"
    eingabe("rate_min_abstand_s", "4")
    e = (api("/api/wissensgraph/status")[1].get("einstellungen") or {})
    check("Eingabe + Verlassen speichert am Server", e.get("rate_min_abstand_s") == 4.0, e.get("rate_min_abstand_s"))
    check("… und meldet es", bool(js(meldung + ".textContent")) and "is-ok" in js(meldung + ".className"),
          js(meldung + ".textContent"))
    eingabe("rate_max_pro_stunde", "100001")
    e = (api("/api/wissensgraph/status")[1].get("einstellungen") or {})
    check("ungueltig: nichts gespeichert, Feld springt zurueck, Fehler steht da",
          e.get("rate_max_pro_stunde") == 700 and js(feld("rate_max_pro_stunde") + ".value") == "700"
          and "is-err" in js(meldung + ".className"), js(meldung + ".textContent"))
    for thema, breite in (("dark", 1400), ("dark", 520), ("light", 1400), ("light", 520)):
        if breite == 1400:
            seite_oeffnen(thema)
            check("Thema '%s' ist aktiv" % thema, js("document.body.classList.contains('light')") == (thema == "light"))
        cmd("Emulation.setDeviceMetricsOverride", {"width": breite, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        warte(0.8)
        b = js("(function(){var o=document.getElementById('kb-sect-wg-body').getBoundingClientRect();"
               "var a=Array.from(document.querySelectorAll('.kbwg-zahl *')).map(function(e){return e.getBoundingClientRect();});"
               "return {seite:document.documentElement.scrollWidth-innerWidth,"
               "raus:a.filter(function(r){return r.right>o.right+1||r.left<o.left-1;}).length,n:a.length};})()")
        check("%s, %d px: kein Ueberlauf, Felder im Abschnitt" % (thema, breite),
              b and b["n"] >= 4 and b["seite"] <= 0 and b["raus"] == 0, b)
        bild("wissensgraph_drossel_%d_%s.png" % (breite, thema))
    check("keine Skriptfehler in der Konsole", not fehler, fehler[:3])
finally:
    s, _ = api(EINST, ZURUECK)
    e = (api("/api/wissensgraph/status")[1].get("einstellungen") or {})
    check("Ausgangswerte wiederhergestellt", s == 200 and json.dumps(
        {k: e.get(k) for k in ("rate_min_abstand_s", "rate_max_pro_stunde")}) == ZURUECK, e)
    if p:
        try:
            p.terminate()
            p.wait(10)
        except Exception:  # noqa: BLE001
            pass
        subprocess.run(["rm", "-rf", os.path.join(HOME, ".chrome-wissensgraph-drossel")], check=False)

print("\nErgebnis: %d ok, %d fehlgeschlagen" % (ok, fail))
print("Bilder: %s/wissensgraph_drossel_*.png" % HOME)
sys.exit(1 if fail else 0)
