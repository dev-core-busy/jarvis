"""Live-Abnahme im echten Chrome auf DEV: zeigt /portal seine Dokumente?

GEMELDET am 2026-09-03: "unter /portal -> Titel -> Dokumente sind die 6
Dokumente nicht sichtbar". Ursache war ein `_dlk()`, das bei der Umstellung auf
den Abruf-Schluessel in eine andere Funktion hineingeschrieben wurde – der
Aufruf beim Zeichnen lief in einen ReferenceError, den der `catch` der
Ladefunktion verschluckte: Ordnersymbol da, Zaehler "6 Dateien", Liste LEER.

Der jsdom-Waechter (tests/test_dlkey_reichweite.js) haelt das fest. Diese Probe
misst zusaetzlich im ECHTEN Browser gegen den ECHTEN Ordner – denn nur hier
kommen Backend, Abruf-Schluessel und Renderer wirklich zusammen.

Laeuft AUF DEV:  python3 /opt/jarvis/tests/live_info_files_dev.py
"""
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
from backend import info_files as IF  # noqa: E402

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


# Wieviele Dateien liegen wirklich im Ordner? Die Erwartung wird GEMESSEN und
# nicht als Zahl hingeschrieben – eine feste 6 waere beim naechsten abgelegten
# Dokument ein Fehlalarm.
ECHTE = IF.list_files()
print("\033[1mOrdner %s: %d Datei(en)\033[0m" % (IF.INFO_DIR, len(ECHTE)))
if not ECHTE:
    print("ABBRUCH: der Info-Ordner ist leer – dann prueft diese Probe nichts.")
    sys.exit(2)

PORT, prof = 9357, "/tmp/chrome-infofiles"
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
    cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
    time.sleep(1)
    js("localStorage.setItem('jarvis_token', %s);localStorage.setItem('jarvis_user','jarvis');"
       % json.dumps(TOK))
    cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
    time.sleep(7)

    print("\n\033[1m1. Ordnersymbol und Panel\033[0m")
    check("das Ordnersymbol ist sichtbar",
          js("(function(){var w=document.getElementById('pt-info-wrap');"
             "return !!w && getComputedStyle(w).display!=='none';})()") is True)
    # Klick auf das Symbol – genau der Weg des Benutzers.
    js("document.getElementById('pt-info-btn').click()")
    time.sleep(3)
    check("das Panel ist offen",
          js("(function(){var p=document.getElementById('pt-info-panel');"
             "return !!p && !p.hidden && p.getBoundingClientRect().height>0;})()") is True)

    print("\n\033[1m2. Die Eintraege – der gemeldete Fall\033[0m")
    anz = js("document.querySelectorAll('#pt-info-list .pt-info-item').length")
    check("es sind so viele Eintraege wie Dateien im Ordner (%d)" % len(ECHTE),
          anz == len(ECHTE), "gezeichnet: %s" % anz)
    check("jeder Eintrag traegt einen sichtbaren Namen",
          js("[].slice.call(document.querySelectorAll('#pt-info-list .pt-info-name'))"
             ".every(function(e){return (e.textContent||'').trim().length>0;})") is True)
    check("kein Eintrag ragt aus dem Panel (kein waagerechter Ueberlauf)",
          js("(function(){var l=document.getElementById('pt-info-list');"
             "return l.scrollWidth<=l.clientWidth+1;})()") is True)

    print("\n\033[1m3. Die Adressen tragen den Abruf-Schluessel\033[0m")
    adressen = js("[].slice.call(document.querySelectorAll('#pt-info-list .pt-info-item'))"
                  ".map(function(a){return a.getAttribute('href')||'';}).join(' | ')")
    liste = [u for u in (adressen or "").split(" | ") if u]
    dateien = [u for u in liste if u.startswith("/api/info_files/")]
    check("es gibt Datei-Adressen (Positivkontrolle)", bool(dateien), adressen)
    check("jede Datei-Adresse traegt einen Abruf-Schluessel",
          bool(dateien) and all("token=JDL1." in u for u in dateien),
          " ".join(u for u in dateien if "token=JDL1." not in u)[:160])
    check("keine Datei-Adresse traegt ein Sitzungstoken",
          bool(dateien) and not any("jarvis%3A" in u for u in dateien))
    verkn = [u for u in liste if u.startswith("http")]
    check("eine Verknuepfung zeigt auf ihr Ziel, nicht auf den Abruf-Endpunkt",
          all(not u.startswith("/api/") for u in verkn), " ".join(verkn)[:160])

    print("\n\033[1m4. Kein Fehler in der Konsole beim Zeichnen\033[0m")
    # ReferenceError war der Kern des Fehlers – er wurde vom catch verschluckt.
    # Hier wird der Renderer noch einmal DIREKT gerufen: dann schlaegt ein
    # Fehler durch, statt still zu bleiben.
    erg = js("(function(){try{window.JarvisInfoFiles._render();return 'ok';}"
             "catch(e){return 'FEHLER '+e;}})()")
    check("der Renderer laeuft ohne Ausnahme", erg == "ok", str(erg))
    check("und nach dem direkten Aufruf stehen die Eintraege weiter da",
          js("document.querySelectorAll('#pt-info-list .pt-info-item').length") == len(ECHTE))
    print("\n\033[1m5. Die Adresse liefert wirklich die Datei\033[0m")
    # Die ganze Kette: Renderer -> Abruf-Schluessel -> require_auth_or_query.
    # Ohne diesen Schritt bleibt offen, ob der Klick am Ende ein 401 waere.
    stat = js("(function(){var a=document.querySelector(\"#pt-info-list a[href^='/api/info_files/']\");"
              "if(!a) return 'keine Adresse';"
              "return fetch(a.getAttribute('href'),{method:'GET'})"
              ".then(function(r){return r.status+' '+(r.headers.get('content-type')||'');})"
              ".catch(function(e){return 'FEHLER '+e;});})()")
    check("der Abruf ueber die gerenderte Adresse antwortet 200",
          isinstance(stat, str) and stat.startswith("200"), str(stat))
    # Gegenprobe: ohne Schluessel muss derselbe Abruf abgewiesen werden – sonst
    # beweist die 200 oben nichts ueber den Schluessel.
    ohne = js("(function(){var a=document.querySelector(\"#pt-info-list a[href^='/api/info_files/']\");"
              "if(!a) return 'keine Adresse';"
              "return fetch(a.getAttribute('href').split('?')[0])"
              ".then(function(r){return String(r.status);})"
              ".catch(function(e){return 'FEHLER '+e;});})()")
    check("und OHNE Schluessel wird er abgewiesen (Positivkontrolle)",
          ohne in ("401", "403"), str(ohne))

    # ── Die uebrigen drei Module derselben Fehl-Aenderung ───────────────────
    # Der Waechter belegt die Reichweite am Syntaxbaum; hier wird zusaetzlich
    # im echten Browser gemessen, dass der Schluessel-Helfer dort wirklich
    # antwortet. `vision.js` ist der einzige der drei, dessen Helfer von
    # aussen erreichbar ist (Methode der Klasse) – tracks/issues liegen in
    # einer Closure und sind nur ueber ihre Adressen pruefbar.
    print("\n\033[1m6. vision.js im echten Browser (/settings)\033[0m")
    cmd("Page.navigate", {"url": "https://127.0.0.1/settings"})
    time.sleep(8)
    check("der Vision-Manager ist da", js("!!window.visionManager") is True)
    vs = js("(function(){try{return String(window.visionManager._dlk());}"
            "catch(e){return 'FEHLER '+e;}})()")
    check("visionManager._dlk() liefert einen Abruf-Schluessel",
          isinstance(vs, str) and vs.startswith("JDL1."), str(vs)[:80])

finally:
    try:
        ws.close()
    except Exception:
        pass
    p.kill()

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
