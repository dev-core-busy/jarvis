"""Optische Abnahme von /vemas im echten Chrome (DEV), hell und dunkel.

jsdom rechnet KEIN Layout: Ueberlappung, Breite und Abgeschnittenes sieht nur
ein Screenshot (Register-Eintrag). Zusaetzlich wird hier gemessen, was ein
Quelltext-Grep nicht beweist: dass die Kachel wirklich sichtbar ist, dass die
Anmeldeart die richtigen Felder ein- und ausblendet und dass der Muelleimer im
Loeschknopf wirklich ankommt.

Schaltet den Skill vorher ein und danach wieder AUS.
"""
import base64
import json
import subprocess
import sys
import time
import urllib.request

import websocket

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
import requests
import urllib3
urllib3.disable_warnings()
from backend.main import generate_token

TOK = generate_token("jarvis")
S = requests.Session(); S.verify = False
S.headers["Authorization"] = "Bearer " + TOK
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


PORT, prof = 9337, "/tmp/chrome-vemas-ui"
subprocess.run(["rm", "-rf", prof], check=False)

print("\n\033[1m1. Bereich vorbereiten\033[0m")
check("Skill an", S.post("https://127.0.0.1/api/skills/vemas/enable", timeout=90).status_code == 200)
time.sleep(3)
check("Freigabe gesetzt",
      S.post("https://127.0.0.1/api/settings", json={"vemas_allowed_users": "jarvis"},
             timeout=20).status_code == 200)
check("Server konfiguriert",
      S.post("https://127.0.0.1/api/skills/vemas/config",
             json={"base_url": "https://vemas.firma.de/api", "auth_kind": "basic",
                   "username": "admin", "password": "x", "read_only": True,
                   "resources": "Projekte = projects\nKunden = customers\nZeiten = timeentries",
                   "vemas_product": "Vemas.NextGen"}, timeout=20).status_code == 200)

p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1500,1400", "--no-first-run",
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
    r = cmd("Runtime.evaluate", {"expression": code, "returnByValue": True,
                                 "awaitPromise": True})
    return (r.get("result") or {}).get("value")


try:
    for thema in ("dark", "light"):
        print("\n\033[1m2. Seite im Thema '%s'\033[0m" % thema)
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(2)
        js("localStorage.setItem('jarvis_token', %s);"
           "localStorage.setItem('jarvis_theme', %s);" % (json.dumps(TOK), json.dumps(thema)))
        cmd("Page.navigate", {"url": "https://127.0.0.1/vemas"})
        time.sleep(5)

        check("[%s] die Seite ist sichtbar (nicht aufs Portal umgeleitet)" % thema,
              js("location.pathname") == "/vemas" and
              js("!document.getElementById('vm-app').classList.contains('hidden')"),
              js("location.pathname"))
        check("[%s] Thema gesetzt" % thema,
              js("document.body.classList.contains('light')") == (thema == "light"))
        check("[%s] die Verbindungs-Pille sagt 'nur lesend'" % thema,
              "lesend" in (js("document.getElementById('vm-conn').textContent") or ""),
              js("document.getElementById('vm-conn').textContent"))
        check("[%s] das Abfrage-Pulldown ist gefuellt" % thema,
              (js("document.getElementById('vm-analysis').options.length") or 0) > 15,
              js("document.getElementById('vm-analysis').options.length"))
        check("[%s] Gruppen (Kategorien) im Pulldown" % thema,
              (js("document.querySelectorAll('#vm-analysis optgroup').length") or 0) >= 5)
        check("[%s] Serverfeld gefuellt und readonly" % thema,
              js("document.getElementById('vm-acc-server').value") == "https://vemas.firma.de/api"
              and js("document.getElementById('vm-acc-server').readOnly") is True)
        check("[%s] Muelleimer im Loeschknopf angekommen" % thema,
              js("!!document.querySelector('#vm-acc-del svg.jv-ico-trash')") is True)
        check("[%s] Ressourcen als Vorschlagsliste" % thema,
              (js("document.querySelectorAll('#vm-res-list option').length") or 0) == 3)

        # Anmeldeart schaltet die Felder um – das ist Verhalten, kein Markup.
        js("var s=document.getElementById('vm-acc-auth'); s.value='bearer';"
           "s.dispatchEvent(new Event('change'));")
        time.sleep(0.4)
        check("[%s] 'bearer' zeigt das Token-Feld, verbirgt Benutzer/Kennwort" % thema,
              js("document.getElementById('vm-acc-g-token').hidden") is False
              and js("document.getElementById('vm-acc-g-user').hidden") is True)
        js("var s=document.getElementById('vm-acc-auth'); s.value='login';"
           "s.dispatchEvent(new Event('change'));")
        time.sleep(0.4)
        check("[%s] 'login' braucht Benutzer/Kennwort (fuer die Token-Abholung)" % thema,
              js("document.getElementById('vm-acc-g-user').hidden") is False
              and js("document.getElementById('vm-acc-g-token').hidden") is True)
        js("var s=document.getElementById('vm-acc-auth'); s.value='';"
           "s.dispatchEvent(new Event('change'));")

        # Nichts darf waagerecht aus dem Fenster laufen.
        check("[%s] kein waagerechter Ueberlauf" % thema,
              js("document.documentElement.scrollWidth <= window.innerWidth + 2") is True,
              js("document.documentElement.scrollWidth + ' > ' + window.innerWidth"))
        # Die Kachel-Ueberschrift darf die Pille nicht ueberdecken.
        check("[%s] Pille steht neben der Ueberschrift, nicht darauf" % thema,
              js("(function(){var s=document.querySelector('#vm-sect-account summary');"
                 "var p=document.getElementById('vm-acc-pill');"
                 "if(!s||!p)return false;var a=s.getBoundingClientRect(),b=p.getBoundingClientRect();"
                 "return b.left>=a.left && b.right<=a.right+1 && b.height>0;})()") is True)

        # Sprachwechsel muss den Katalog neu holen.
        vorher = js("document.getElementById('vm-analysis').options[1].textContent")
        js("window.setLang && window.setLang('en');")
        time.sleep(2.5)
        nachher = js("document.getElementById('vm-analysis').options[1].textContent")
        check("[%s] Sprachwechsel holt den Katalog neu" % thema, vorher != nachher,
              "%r -> %r" % (vorher, nachher))
        check("[%s] und die Beschriftungen folgen" % thema,
              "Query" in (js("document.querySelector('label[for=vm-analysis]').textContent") or ""),
              js("document.querySelector('label[for=vm-analysis]').textContent"))
        js("window.setLang && window.setLang('de');")
        time.sleep(2.5)

        png = cmd("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        pfad = "/tmp/vemas-%s.png" % thema
        open(pfad, "wb").write(base64.b64decode(png["data"]))
        check("[%s] Screenshot geschrieben" % thema, True, pfad)

    print("\n\033[1m3. Portal-Kachel\033[0m")
    cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
    time.sleep(4)
    check("die VEMAS-Kachel ist sichtbar",
          js("(function(){var c=document.getElementById('pt-card-vemas');"
             "return !!c && !c.classList.contains('hidden') "
             "&& c.getBoundingClientRect().height>0;})()") is True)
    check("... und fuehrt auf /vemas",
          (js("document.getElementById('pt-card-vemas').getAttribute('href')")) == "/vemas")
    png = cmd("Page.captureScreenshot", {"format": "png"})
    open("/tmp/vemas-portal.png", "wb").write(base64.b64decode(png["data"]))

finally:
    print("\n\033[1m4. Aufraeumen\033[0m")
    try:
        ws.close()
    except Exception:
        pass
    p.kill()
    S.post("https://127.0.0.1/api/settings",
           json={"vemas_allowed_users": "", "vemas_allowed_group": ""}, timeout=20)
    S.post("https://127.0.0.1/api/skills/vemas/config",
           json={"base_url": "", "username": "", "password": "", "api_token": "",
                 "read_only": True, "resources": "", "vemas_product": ""}, timeout=20)
    S.post("https://127.0.0.1/api/skills/vemas/disable", timeout=60)
    time.sleep(2)
    check("permissions.vemas wieder False",
          S.get("https://127.0.0.1/api/me", timeout=15).json()
          .get("permissions", {}).get("vemas") is False)

print("\n" + "=" * 62)
print("\033[%sm%d OK, %d FAIL\033[0m" % ("32" if fail == 0 else "31", ok, fail))
print("=" * 62)
sys.exit(0 if fail == 0 else 1)
