"""Optische/funktionale Abnahme im echten Chrome: was steht in der Adresse?

Der Backend-Test belegt, dass der Abruf-Schluessel angenommen wird. Ob die
OBERFLAECHE ihn auch wirklich in die Links schreibt, sagt er nicht – und genau
das war der gemeldete Fehler: in der Adresse stand das Sitzungstoken.
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
import urllib3  # noqa: E402
urllib3.disable_warnings()
from backend.main import generate_token  # noqa: E402

TOK = generate_token("jarvis")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


PORT, prof = 9355, "/tmp/chrome-dlkey"
subprocess.run(["rm", "-rf", prof], check=False)
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
    return (cmd("Runtime.evaluate", {"expression": code, "returnByValue": True,
                                     "awaitPromise": True}).get("result") or {}).get("value")


import os  # noqa: E402
DOCS = "/opt/jarvis/data/documents"
_kand = [f for f in sorted(os.listdir(DOCS)) if "__" in f and not f.startswith(".")
         and os.path.isfile(os.path.join(DOCS, f))] if os.path.isdir(DOCS) else []
if len(_kand) < 2:
    print("ABBRUCH (Exit 2): zwei Dateien in data/documents noetig"); p.kill(); sys.exit(2)
import urllib.parse  # noqa: E402
A = "/api/documents/" + urllib.parse.quote(_kand[-1])
B = "/api/documents/" + urllib.parse.quote(_kand[-2])

try:
    for seite in ("/chat", "/portal", "/wissen", "/settings", "/tracks"):
        print("\n\033[1m%s\033[0m" % seite)
        cmd("Page.navigate", {"url": "https://127.0.0.1" + seite})
        time.sleep(1)
        js("localStorage.setItem('jarvis_token', %s);localStorage.setItem('jarvis_user','jarvis');"
           % json.dumps(TOK))
        cmd("Page.navigate", {"url": "https://127.0.0.1" + seite})
        time.sleep(7)

        check("[%s] dlkey.js ist geladen" % seite, js("!!window.JarvisDL") is True)
        check("[%s] die neue Fassung (Schluessel je Adresse, kein schluessel())" % seite,
              js("typeof window.JarvisDL.fuer === 'function' && "
                 "typeof window.JarvisDL.schluessel === 'undefined'") is True)
        # Pentest F-20: beim ersten Bauen steht der Platzhalter darin, nach dem
        # Sammelabruf der Schluessel GENAU DIESER Adresse.
        # sessionStorage gilt je TAB ueber alle Seiten: ab der zweiten Seite liegt
        # der Schluessel fuer A schon bereit (das ist gewollt und wird gemessen),
        # danach wird geleert, um den Platzhalter-Fall herzustellen.
        if seite != "/chat":
            sofort = js("window.JarvisDL.url(%s)" % json.dumps(A))
            check("[%s] Schluessel der Vorseite wird wiederverwendet (kein neuer Abruf)" % seite,
                  isinstance(sofort, str) and "token=JDL1." in sofort and "warten" not in sofort, sofort)
        js("sessionStorage.removeItem(window.JarvisDL._lager)")
        erst = js("window.JarvisDL.url(%s)" % json.dumps(A))
        check("[%s] erste Adresse: Platzhalter, nie das Sitzungstoken" % seite,
              isinstance(erst, str) and "token=JDL1.warten" in erst and "jarvis%3A" not in erst, erst)
        time.sleep(2)
        ua = js("window.JarvisDL.url(%s)" % json.dumps(A))
        ub = js("window.JarvisDL.url(%s)" % json.dumps(B))
        time.sleep(2)
        ub = js("window.JarvisDL.url(%s)" % json.dumps(B))
        check("[%s] danach traegt die Adresse ihren Schluessel" % seite,
              isinstance(ua, str) and "token=JDL1." in ua and "warten" not in ua, ua)
        holen = ("fetch(%s).then(function(r){return r.status}).catch(function(e){return 'FEHLER '+e})")
        st_a = js(holen % json.dumps(ua))
        check("[%s] Positivkontrolle: Datei A mit ihrem Schluessel -> 200" % seite, st_a == 200, st_a)
        tok_b = (ub or "").split("token=")[-1]
        quer = A + "?token=" + tok_b
        st_q = js(holen % json.dumps(quer))
        check("[%s] ⚠ Datei A mit dem Schluessel von B -> 401 (F-20)" % seite, st_q == 401, st_q)

        # Was steht wirklich im DOM – nach dem Einschwingen?
        roh = js("(function(){var a=[].slice.call(document.querySelectorAll('[href],[src]'))"
                 ".map(function(e){return e.getAttribute('href')||e.getAttribute('src')||'';})"
                 ".filter(function(u){return u.indexOf('token=')>=0;});return a.join(' | ');})()")
        adressen = [u for u in (roh or "").split(" | ") if u]
        schlecht = [u for u in adressen if "token=JDL1." not in u and "ws/vnc" not in u]
        check("[%s] keine gerenderte Adresse traegt ein Sitzungstoken" % seite,
              not schlecht, " ".join(schlecht[:2]))
        wartend = [u for u in adressen if "JDL1.warten" in u or "JDL1%2Ewarten" in u]
        check("[%s] kein Platzhalter bleibt stehen (%d Adressen mit Schluessel)" % (seite, len(adressen)),
              not wartend, " ".join(wartend[:2]))
finally:
    try:
        ws.close()
    except Exception:
        pass
    p.kill()

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
