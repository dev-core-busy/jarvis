"""Klick-Test im echten Chrome: Willkommens-Chat loeschen, Knopf druecken,
pruefen dass die Sitzung UND die Beispiel-Karte wirklich erscheinen.
jsdom faellt hier aus (nicht installiert) – und ein Quelltext-Grep beweist
nicht, dass der Knopf verdrahtet ist."""
import base64, json, subprocess, sys, time, urllib.request
import websocket

PORT, prof = 9334, "/tmp/chrome-jarvis-klick"
subprocess.run(["rm", "-rf", prof])
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1280,900", "--no-first-run",
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
def js(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    return r.get("result", {}).get("value")

TOKEN, BASE = sys.argv[1], "https://127.0.0.1"
res = []
def check(name, cond, detail=""):
    res.append(bool(cond))
    print(("  \033[32m✓\033[0m " if cond else "  \033[31m✗\033[0m ") + name + ("" if cond else f" – {detail}"))

cmd("Page.enable"); cmd("Runtime.enable")
cmd("Page.navigate", {"url": BASE + "/chat"}); time.sleep(3)
js(f"localStorage.setItem('jarvis_token','{TOKEN}');localStorage.setItem('jarvis_theme','light')")
cmd("Page.navigate", {"url": BASE + "/chat"}); time.sleep(9)

def sitzungen():
    return js("""(async () => {
      const r = await fetch('/api/chat/sessions', {headers:{Authorization:'Bearer '+localStorage.getItem('jarvis_token')}});
      const d = await r.json();
      return d.sessions.filter(s => s.title === 'Beispiel Prompts').length;
    })()""")

# 1) Ausgangslage herstellen: den Willkommens-Chat wirklich loeschen
js("""(async () => {
  const h = {Authorization:'Bearer '+localStorage.getItem('jarvis_token')};
  const d = await (await fetch('/api/chat/sessions',{headers:h})).json();
  for (const s of d.sessions.filter(x => x.title === 'Beispiel Prompts'))
    await fetch('/api/chat/sessions/'+s.id, {method:'DELETE', headers:h});
  return true;
})()""")
cmd("Page.navigate", {"url": BASE + "/chat"}); time.sleep(9)
check("Ausgangslage: kein Willkommens-Chat mehr", sitzungen() == 0, str(sitzungen()))
check("Knopf ist da und bedienbar",
      js("(()=>{const b=document.getElementById('cs-welcome');return !!b && !b.disabled;})()"))

# 2) Klicken – wie ein Mensch, nicht per Funktionsaufruf
js("document.getElementById('cs-welcome').click()"); time.sleep(4)
check("nach dem Klick genau EIN Willkommens-Chat", sitzungen() == 1, str(sitzungen()))
check("die Sitzung steht in der Seitenleiste",
      js("[...document.querySelectorAll('.cs-item .cs-title')].some(e=>e.textContent.trim()==='Beispiel Prompts')"))
check("und ist die AKTIVE Sitzung",
      js("(document.querySelector('.cs-item.active .cs-title')||{}).textContent === 'Beispiel Prompts'"),
      str(js("(document.querySelector('.cs-item.active .cs-title')||{}).textContent")))
check("die Beispiel-Karte ist gerendert",
      js("!!document.querySelector('.welcome-card')"))
check("mit 10 anklickbaren Beispielen",
      js("document.querySelectorAll('.welcome-card .wex-chip').length") == 10,
      str(js("document.querySelectorAll('.welcome-card .wex-chip').length")))
toast = js("(()=>{const t=document.getElementById('attach-toast');return t?{txt:t.textContent,sichtbar:t.classList.contains('show')}:null;})()") or {}
check("Rueckmeldung wurde angezeigt",
      "Beispiel Prompts" in (toast.get("txt") or "") and toast.get("sichtbar"), str(toast))
check("Hinweis nennt den Weg zurueck",
      "Verlaufsleiste" in (js("(document.querySelector('.welcome-card-hint')||{}).textContent") or ""),
      str(js("(document.querySelector('.welcome-card-hint')||{}).textContent"))[:120])

# 3) Zweiter Klick darf keinen zweiten Chat anlegen
js("document.getElementById('cs-welcome').click()"); time.sleep(4)
check("zweiter Klick legt KEINEN zweiten an", sitzungen() == 1, str(sitzungen()))

# 4) Sprachwechsel: der Knopf muss mitgehen
js("window.setLang('en')"); time.sleep(1)
check("EN-Beschriftung folgt dem Sprachwechsel",
      (js("document.getElementById('cs-welcome').textContent") or "").strip() == "Example prompts",
      str(js("document.getElementById('cs-welcome').textContent")))
js("window.setLang('de')"); time.sleep(1)
check("DE-Beschriftung kommt zurueck",
      (js("document.getElementById('cs-welcome').textContent") or "").strip() == "Beispiel-Prompts",
      str(js("document.getElementById('cs-welcome').textContent")))

png = cmd("Page.captureScreenshot", {"format": "png"})
open(sys.argv[2], "wb").write(base64.b64decode(png["data"]))
print(f"\n\033[1mErgebnis: {sum(res)}/{len(res)}\033[0m   Screenshot: {sys.argv[2]}")
ws.close(); p.terminate()
sys.exit(0 if all(res) else 1)
