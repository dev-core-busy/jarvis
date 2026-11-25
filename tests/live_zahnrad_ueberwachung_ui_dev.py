"""Optische Abnahme: Serverueberwachung am Zahnrad, NICHTS an der CPU-Anzeige (DEV, echter Chrome).

WARUM (gemeldet 2026-11-25): "stelle ENDLICH ab, dass 'Serverüberwachung
Warnung' in der CPU Pill angezeigt wird … das gehört in die Zahnrad Badge".
tests/test_ueberwachung_ui.js misst die Kette in jsdom – jsdom rechnet aber kein
Layout. Hier im Browser: die Befundzeilen sind ganze Saetze und muessen im Panel
umbrechen statt abgeschnitten zu werden, und das Panel muss im Fenster liegen.

  - Positivkontrolle: /api/me liefert einen Administrator MIT mindestens einer
    Warnung der Ueberwachung (sonst Exit 2 – nichts zu messen).
  - CPU-Anzeige: keine Markierung, kein Zusatz im Tooltip, kein Abruf von
    /api/system/ueberwachung (Ressourcenliste des Browsers).
  - Panel: eine Zeile je Befund, keine Zeile laeuft ueber, Panel im Fenster,
    beide Themen; Bilder im HOME des Aufrufers.
Nur lesend (nichts gespeichert, nichts uebernommen).

Die Badge sieht nur eine Sitzung MIT Admin-Rechten (seit 2026-11-20 erst nach
dem Code am Zahnrad) – also ein Administrator mit eigenem 2FA-Code:
    python3 tests/live_mit_brokercode.py tests/live_zahnrad_ueberwachung_ui_dev.py <benutzer>
                                                               (root, auf DEV)
Exit 0 = gehalten, 1 = Befund, 2 = konnte nicht laufen.
"""
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, "/opt/jarvis/tests/lib")
if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(2)
BENUTZER = sys.argv[1]
sys.argv = ["x"]
import urllib3  # noqa: E402
urllib3.disable_warnings()
from backend import main as M  # noqa: E402
from zweifaktor_code import code_quelle  # noqa: E402

_auth = M._get_user_auth_state(BENUTZER)
if not _auth.get("totp_enabled"):
    print("ABBRUCH: Konto %s hat keine 2FA – ohne Code keine Admin-Sitzung" % BENUTZER)
    sys.exit(2)
NEUER_CODE = code_quelle(_auth.get("totp_secret"))
TOK = M.generate_token(BENUTZER)
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % (detail,)) if detail else ""))


ABLAGE = Path(tempfile.mkdtemp(prefix="live-zahnrad-", dir=str(Path.home())))
PORT, prof = 9351, tempfile.mkdtemp(prefix="chrome-zahnrad-", dir=str(Path.home()))
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1400,900", "--no-first-run",
                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)
tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
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


try:
    for thema in ("dark", "light"):
        print("\n\033[1mThema '%s'\033[0m" % thema)
        cmd("Page.navigate", {"url": "https://127.0.0.1/api/health"})
        time.sleep(2)
        js("localStorage.clear(); localStorage.setItem('jarvis_token', %s);"
           "localStorage.setItem('jarvis_user', %s); localStorage.setItem('jarvis_theme', %s);"
           "localStorage.setItem('jarvis_lang','de'); true" % (json.dumps(TOK), json.dumps(BENUTZER), json.dumps(thema)))
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        for _ in range(30):
            if js("(localStorage.getItem('jarvis_token')||'').indexOf('JCS1.')===0"):
                break
            time.sleep(1)
        else:
            print("ABBRUCH: Sitzung wurde nicht auf das Cookie umgestellt")
            sys.exit(2)
        st = js("fetch('/api/admin/erhoehen',{method:'POST',headers:{'Content-Type':'application/json',"
                "'Authorization':'Bearer '+(window.JarvisSitzung?JarvisSitzung.token():localStorage.getItem('jarvis_token'))},"
                "body:JSON.stringify({code:%s})}).then(r=>r.status)" % json.dumps(NEUER_CODE()))
        if st != 200:
            print("ABBRUCH: Erhoehung am Zahnrad gelang nicht (%s)" % st)
            sys.exit(2)
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(7)
        me = js("fetch('/api/me',{headers:{Authorization:'Bearer '+(window.JarvisSitzung?JarvisSitzung.token():"
                "localStorage.getItem('jarvis_token'))}}).then(function(r){return r.json();})")
        if not isinstance(me, dict) or not me.get("is_admin"):
            print("ABBRUCH: /api/me liefert keinen Administrator – Probe nicht deutbar")
            sys.exit(2)
        ab = me.get("admin_badge") or {}
        if not ab.get("ue_warnungen"):
            print("ABBRUCH: keine Warnung der Ueberwachung auf DEV – das Panel ist nicht messbar (%s)" % ab)
            sys.exit(2)
        # ── CPU-Anzeige ──
        cpu = js("(function(){var b=document.getElementById('cpu-bar');if(!b)return null;"
                 "var r=performance.getEntriesByType('resource').map(function(e){return e.name;});"
                 "return {kl:b.className,title:b.title||'',aria:b.getAttribute('aria-label')||'',"
                 "klick:b.classList.contains('jv-cpu-klick'),"
                 "ue:r.filter(function(x){return x.indexOf('/api/system/ueberwachung')>=0;}).length};})()")
        if not cpu or not cpu.get("klick"):
            print("ABBRUCH: CPU-Anzeige fehlt oder ohne Admin-Ausstattung – Teil nicht deutbar (%s)" % cpu)
            sys.exit(2)
        check("[%s] CPU-Anzeige ohne Markierung der Ueberwachung" % thema, "jv-ue" not in cpu["kl"], cpu["kl"])
        check("[%s] CPU-Tooltip ohne 'Serverüberwachung'" % thema,
              "berwachung" not in cpu["title"] + cpu["aria"], cpu["title"])
        check("[%s] kein Abruf von /api/system/ueberwachung" % thema, cpu["ue"] == 0, cpu["ue"])
        # ── Badge + Panel ──
        gear = js("(function(){var g=document.querySelector('[data-jarvis-settings] .jv-gear-badge');"
                  "return g?{t:g.textContent,d:g.classList.contains('is-danger')}:null;})()")
        g_soll = ab.get("gesamt", 0)
        check("[%s] Zahnrad-Badge zeigt die Gesamtzahl" % thema,
              bool(gear) and gear["t"] == (str(g_soll) if g_soll <= 99 else "99+"), (gear, g_soll))
        js("(function(){var g=document.querySelector('[data-jarvis-settings] .jv-gear-badge');"
           "g.dispatchEvent(new MouseEvent('mouseenter'));})()")
        time.sleep(1)
        pan = js("(function(){var t=document.querySelector('.jv-gear-tip');if(!t||t.style.display!=='block')return null;"
                 "var r=t.getBoundingClientRect();var z=[].slice.call(t.querySelectorAll('.jv-gear-tip-row[data-ue]'));"
                 "return {l:r.left,o:r.top,r:r.right,u:r.bottom,w:innerWidth,h:innerHeight,"
                 "zeilen:z.map(function(e){var s=e.querySelector('.jv-gear-tip-t');"
                 "return {art:e.getAttribute('data-ue'),tag:e.tagName,text:s?s.textContent:'',"
                 "ueber:s?s.scrollWidth-s.clientWidth:99,hoch:s?s.getBoundingClientRect().height:0};})};})()")
        if not pan:
            check("[%s] Panel oeffnet beim Ueberfahren der Badge" % thema, False)
            continue
        z = pan["zeilen"]
        check("[%s] eine Zeile je Warnung der Ueberwachung" % thema, len(z) == ab["ue_warnungen"],
              (len(z), ab["ue_warnungen"]))
        check("[%s] keine Befundzeile laeuft ueber (Text bricht um)" % thema,
              all(x["ueber"] <= 1 for x in z), [x for x in z if x["ueber"] > 1])
        check("[%s] Panel liegt ganz im Fenster" % thema,
              pan["l"] >= 0 and pan["o"] >= 0 and pan["r"] <= pan["w"] and pan["u"] <= pan["h"], pan)
        aide = [x for x in z if x["art"].startswith("aide_")]
        check("[%s] Zeilen zur Integritaetspruefung sind Knoepfe, die uebrigen nicht" % thema,
              all(x["tag"] == "BUTTON" for x in aide) and all(x["tag"] != "BUTTON" for x in z if x not in aide), z)
        for x in z:
            print("      %-14s %s" % (x["art"], x["text"][:110]))
        rand = 8
        clip = {"x": max(0, pan["l"] - rand), "y": max(0, pan["o"] - 60), "width": pan["r"] - pan["l"] + 2 * rand,
                "height": pan["u"] - pan["o"] + 60 + rand, "scale": 1}
        r = cmd("Page.captureScreenshot", {"format": "png", "clip": clip})
        if r.get("data"):
            bild = ABLAGE / ("zahnrad_%s.png" % thema)
            bild.write_bytes(base64.b64decode(r["data"]))
            print("      Bild: %s" % bild)
finally:
    try:
        # Rechte der Probesitzung wieder abgeben (Vorzustand: keine erhoehte Sitzung)
        js("fetch('/api/admin/erhoehung/beenden',{method:'POST',headers:{'Authorization':'Bearer '+"
           "(window.JarvisSitzung?JarvisSitzung.token():localStorage.getItem('jarvis_token'))}}).then(r=>r.status)")
    except Exception:  # noqa: BLE001
        pass
    try:
        ws.close()
    except Exception:  # noqa: BLE001
        pass
    p.terminate()
    # Chrome schreibt nach terminate() noch ins Profil (Register: ENOTEMPTY) – erst warten
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill()
    subprocess.run(["rm", "-rf", prof], check=False, stderr=subprocess.DEVNULL)

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
