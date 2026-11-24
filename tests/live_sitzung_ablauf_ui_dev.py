"""Abnahme im echten Chrome AUF DEM SERVER: abgelaufene Sitzung wird angezeigt,
und nach der Neuanmeldung geht es auf die Seite von vorher zurueck.

Der jsdom-Waechter (test_sitzung_ablauf_ui.js) misst die Logik; Cookies,
echte 401 der Middleware, Stapelreihenfolge und Layout sieht er nicht
(Register: "ein Umbau am Anmeldeweg ist erst gemessen, wenn ein echter Browser
ueber alle Seiten gelaufen ist").

Ablauf je Seite:
  1. mit frischem Token anmelden (das Altformat wird von sitzung.js auf
     Cookie + CSRF umgestellt – also der echte Weg der Weboberflaeche)
  2. Positivkontrolle: Seite geladen, Modul da, Sitzung gilt, kein Hinweis
  3. Sitzung SERVERSEITIG beenden (/api/logout = Widerruf genau dieses Tokens;
     das Token bleibt im Browser liegen, wie nach einem Ablauf)
  4. eine gewoehnliche Anfrage der Seite bekommt 401 → Hinweis sichtbar, oben
  5. "Neu anmelden" → Anmeldeseite; dort neu anmelden → zurueck auf der Seite
Auf EINER Seite zusaetzlich der Rueckkehr-Weg ohne Anfrage: Tab wird wieder
sichtbar (nach Ablauf der Drossel) → Hinweis.

Aufruf auf DEV (seit BSI M5 nur mit Hauptschluessel gueltig):
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_sitzung_ablauf_ui_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

try:
    import websocket
except ImportError:
    print("ABBRUCH (Exit 2): websocket-client fehlt"); sys.exit(2)

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
try:
    import urllib3  # noqa: E402
    urllib3.disable_warnings()
    from backend.main import generate_token  # noqa: E402
except Exception as e:  # noqa: BLE001
    print("ABBRUCH (Exit 2): backend.main nicht ladbar: %s" % e); sys.exit(2)

if not shutil.which("google-chrome"):
    print("ABBRUCH (Exit 2): google-chrome fehlt"); sys.exit(2)

BASIS = "https://127.0.0.1"
# Unter der Adresse messen, unter der Benutzer arbeiten: ist die Firmen-
# Anmeldung eingerichtet, wechselt "/" auf deren feste Rueckkehradresse
# (idp_anmeldung.js Punkt 6) – ein ANDERER Ursprung, und sessionStorage gilt
# je Ursprung. Unter 127.0.0.1 waere das gemerkte Ziel dort unsichtbar (beim
# Bau so gemessen: Probe meldete "zurueck auf /portal" statt der Seite). Die
# Adresse kommt vom Server selbst, nicht aus dem Repo.
try:
    import ssl as _ssl
    _ctx = _ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = _ssl.CERT_NONE
    _st = json.load(urllib.request.urlopen(BASIS + "/api/login/oidc/status", context=_ctx, timeout=10))
    if _st.get("aktiv") and isinstance(_st.get("ursprung"), str) and _st["ursprung"].startswith("https://"):
        BASIS = _st["ursprung"].rstrip("/")
except Exception as e:  # noqa: BLE001
    print("ABBRUCH (Exit 2): Anmeldestatus nicht lesbar: %s" % e); sys.exit(2)
print("gemessen unter dem Ursprung der Anmeldung (%s)" % ("eigener Name" if "127.0.0.1" not in BASIS else "lokal"))
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))
    return cond


ablage = tempfile.mkdtemp(prefix="live-sitzung-ablauf-", dir=os.path.expanduser("~"))
PORT = 9371
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={ablage}/profil", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1280,860", "--no-first-run",
                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ws = None
n = [0]


def cmd(m, params=None):
    n[0] += 1
    ws.send(json.dumps({"id": n[0], "method": m, "params": params or {}}))
    while True:
        d = json.loads(ws.recv())
        if d.get("id") == n[0]:
            return d.get("result", {})


def js(code):
    return (cmd("Runtime.evaluate", {"expression": code, "returnByValue": True,
                                     "awaitPromise": True}).get("result") or {}).get("value")


def warte_bis(code, frist=15.0):
    ende = time.time() + frist
    while time.time() < ende:
        if js(code):
            return True
        time.sleep(0.25)
    return False


def anmelden_und_laden(seite):
    """Frisches Token ablegen und Seite laden. Zwei Tokens desselben Kontos in
    derselben Sekunde sind identisch (Register) – deshalb vorher warten."""
    time.sleep(1.1)
    tok = generate_token("jarvis")
    # Ablegen auf einer NEUTRALEN Adresse desselben Ursprungs: eine Seite wie
    # /portal sieht beim Laden noch kein Token und beendet die Sitzung kurz
    # darauf selbst – asynchron, also NACH dem setItem (beim Bau so gemessen:
    # auf /chat lag danach gar kein Token mehr, die Positivkontrolle fiel).
    cmd("Page.navigate", {"url": BASIS + "/static/js/icons.js"})
    time.sleep(1)
    js("localStorage.clear(); sessionStorage.clear();"
       "localStorage.setItem('jarvis_token', %s); localStorage.setItem('jarvis_user','jarvis');"
       % json.dumps(tok))
    cmd("Page.navigate", {"url": BASIS + seite})
    time.sleep(1)
    # sitzung.js stellt das Altformat auf Cookie + CSRF um – warten, bis es durch ist
    warte_bis("(window.JarvisSitzung && window.JarvisSitzung.token().indexOf('JCS1.') === 0) || false", 10)
    time.sleep(3)


GILT = ("fetch('/api/verify-token',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({token:window.JarvisSitzung.token()})}).then(r=>r.json()).then(d=>d.valid)")
HINWEIS_SICHTBAR = ("(function(){var h=document.querySelector('.jv-sitzung-ablauf');if(!h)return false;"
                    "var r=h.querySelector('.jv-sitzung-ablauf-karte').getBoundingClientRect();"
                    "return getComputedStyle(h).display!=='none'&&r.width>200&&r.height>100;})()")
# Liegt der Hinweis OBEN? Das Element in der Bildmitte muss zur Karte gehoeren.
OBEN = ("(function(){var k=document.querySelector('.jv-sitzung-ablauf-karte');if(!k)return false;"
        "var r=k.getBoundingClientRect();var e=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);"
        "return !!e && k.contains(e);})()")

try:
    time.sleep(5)
    try:
        tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
        ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
    except Exception as e:  # noqa: BLE001
        print("ABBRUCH (Exit 2): Chrome nicht erreichbar: %s" % e); sys.exit(2)
    cmd("Page.enable")

    # /settings fehlt bewusst: das Messkonto hat dort ohne Admin-Erhoehung
    # nichts verloren und wird aufs Portal umgeleitet (gewollt, kein Befund).
    uebersprungen = []
    # /sap ebenso: ohne SAP-Freigabe des Messkontos geht es aufs Portal.
    for seite in ("/chat", "/portal", "/wissen", "/support", "/userchat"):
        print("\n\033[1m%s\033[0m" % seite)
        anmelden_und_laden(seite)
        if js("!document.querySelector('script') && /nicht aktiv/.test(document.body.innerText)"):
            # Bereich auf diesem Server abgeschaltet (404-Seite ohne Skripte):
            # nicht messbar – benannt, nicht als Befund und nicht still.
            print("  – uebersprungen: Bereich auf diesem Server nicht aktiv")
            uebersprungen.append(seite)
            continue
        geladen = js("location.pathname") == seite and js("!!window.JarvisSitzungAblauf") is True
        if not check("[%s] Positivkontrolle: Seite geladen, Modul da" % seite, geladen,
                     "%s / %s" % (js("location.pathname"), js("!!window.JarvisSitzungAblauf"))):
            continue
        check("[%s] Positivkontrolle: Sitzung gilt (Cookie-Verfahren)" % seite, js(GILT) is True)
        check("[%s] angemeldet: kein Hinweis" % seite, js(HINWEIS_SICHTBAR) is False)

        # Sitzung serverseitig beenden – das Token bleibt im Browser liegen.
        st = js("fetch('/api/logout',{method:'POST',headers:window.JarvisSitzung.kopfsatz()})"
                ".then(r=>r.status)")
        if not check("[%s] Sitzung serverseitig beendet (/api/logout)" % seite, st == 200, st):
            continue
        check("[%s] Token liegt weiter im Browser (Lage wie nach Ablauf)" % seite,
              bool(js("window.JarvisSitzung.token()")))

        if seite == "/portal":
            # Rueckkehr-Weg ohne eigene Anfrage: die Drossel (60 s) ablaufen
            # lassen, dann "Tab wieder sichtbar".
            print("    (warte 62 s auf die Drossel fuer den Rueckkehr-Weg)")
            time.sleep(62)
            js("document.dispatchEvent(new Event('visibilitychange')); true")
        else:
            st = js("fetch('/api/me',{headers:window.JarvisSitzung.kopfsatz()}).then(r=>r.status)")
            check("[%s] eine gewoehnliche Anfrage bekommt 401" % seite, st == 401, st)

        da = warte_bis(HINWEIS_SICHTBAR, 10)
        check("[%s] Hinweis 'Sitzung abgelaufen' ist sichtbar" % seite, da)
        if not da:
            continue
        check("[%s] Hinweis liegt ueber der Seite (nichts verdeckt ihn)" % seite, js(OBEN) is True)
        check("[%s] genau ein Hinweis" % seite,
              js("document.querySelectorAll('.jv-sitzung-ablauf').length") == 1)
        if seite == "/chat":
            bild = cmd("Page.captureScreenshot", {"format": "png"}).get("data")
            if bild:
                ziel = os.path.join(ablage, "hinweis_chat.png")
                with open(ziel, "wb") as fh:
                    fh.write(base64.b64decode(bild))
                print("    Bild: %s" % ziel)

        js("document.querySelector('.jv-sitzung-ablauf-los').click(); true")
        auf_wurzel = warte_bis("location.pathname === '/'", 10)
        check("[%s] 'Neu anmelden' fuehrt zur Anmeldeseite" % seite, auf_wurzel, js("location.pathname"))
        time.sleep(2)
        check("[%s] gemerktes Ziel = %s" % (seite, seite),
              js("sessionStorage.getItem('jarvis_rueckkehr')") == seite,
              js("sessionStorage.getItem('jarvis_rueckkehr')"))
        check("[%s] Anmeldeseite hat das abgelaufene Token abgeraeumt" % seite,
              js("window.JarvisSitzung.token()") == "")
        check("[%s] Anmeldemaske sichtbar" % seite,
              js("(function(){var m=document.getElementById('login-screen');"
                 "return !!m && m.classList.contains('active') && m.getBoundingClientRect().height>0;})()") is True)

        # Neu anmelden: frisches Token, Anmeldeseite neu laden – derselbe Weg wie
        # eine erfolgreiche Anmeldung in einem anderen Tab (app.js: gueltiges
        # Token auf / → rueckkehrZiel).
        time.sleep(1.1)
        js("localStorage.setItem('jarvis_token', %s); true" % json.dumps(generate_token("jarvis")))
        cmd("Page.reload")
        zurueck = warte_bis("location.pathname === %s" % json.dumps(seite), 15)
        check("[%s] nach der Anmeldung zurueck auf %s" % (seite, seite), zurueck, js("location.pathname"))
        check("[%s] gemerktes Ziel ist verbraucht" % seite,
              js("sessionStorage.getItem('jarvis_rueckkehr')") is None)
finally:
    try:
        if ws:
            ws.close()
    except Exception:  # noqa: BLE001
        pass
    p.kill()
    try:
        p.wait(timeout=10)
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(os.path.join(ablage, "profil"), ignore_errors=True)

if uebersprungen:
    print("\nnicht gemessen (Bereich aus): %s" % ", ".join(uebersprungen))
print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
