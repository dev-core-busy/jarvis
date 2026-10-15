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


try:
    for seite in ("/chat", "/portal", "/wissen"):
        print("\n\033[1m%s\033[0m" % seite)
        cmd("Page.navigate", {"url": "https://127.0.0.1" + seite})
        time.sleep(1)
        js("localStorage.setItem('jarvis_token', %s);localStorage.setItem('jarvis_user','jarvis');"
           % json.dumps(TOK))
        cmd("Page.navigate", {"url": "https://127.0.0.1" + seite})
        time.sleep(7)

        check("[%s] dlkey.js ist geladen" % seite, js("!!window.JarvisDL") is True)
        # Der Abruf laeuft beim Laden an – kurz Zeit lassen.
        for _ in range(10):
            if js("!!sessionStorage.getItem('jarvis_dlkey')"):
                break
            time.sleep(1)
        lager = js("sessionStorage.getItem('jarvis_dlkey')")
        check("[%s] der Schluessel liegt im sessionStorage" % seite, bool(lager), lager)
        check("[%s] und ist ein Abruf-Schluessel, kein Sitzungstoken" % seite,
              bool(lager) and '"key":"JDL1.' in lager.replace(" ", ""), (lager or "")[:60])

        gebaut = js("(function(){try{return window.JarvisDL.url('/api/documents/x.pptx');}"
                    "catch(e){return 'FEHLER '+e;}})()")
        check("[%s] JarvisDL.url() baut die Adresse mit dem Schluessel" % seite,
              isinstance(gebaut, str) and "token=JDL1." in gebaut, gebaut)
        check("[%s] KEIN Sitzungstoken in der gebauten Adresse" % seite,
              isinstance(gebaut, str) and "jarvis%3A" not in gebaut and ":" not in gebaut.split("token=")[-1],
              gebaut)

        # Und was steht wirklich im DOM?
        roh = js("(function(){var a=[].slice.call(document.querySelectorAll('[href],[src]'))"
                 ".map(function(e){return e.getAttribute('href')||e.getAttribute('src')||'';})"
                 ".filter(function(u){return u.indexOf('token=')>=0;});return a.join(' | ');})()")
        schlecht = [u for u in (roh or "").split(" | ")
                    if u and "token=JDL1." not in u and "ws/vnc" not in u]
        check("[%s] keine gerenderte Adresse traegt ein Sitzungstoken" % seite,
              not schlecht, " ".join(schlecht[:2]))
finally:
    try:
        ws.close()
    except Exception:
        pass
    p.kill()

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
