"""LIVE im echten Chrome (DEV): das Auge zeigt das GESPEICHERTE Kennwort.

⚠ WARUM IM ECHTEN BROWSER: jsdom rechnet kein Layout, und die Kette
Auge → fetch → Endpunkt → Fernet → Feld laeuft nur hier vollstaendig. Der
jsdom-Waechter misst den Renderweg, diese Probe misst das ERGEBNIS.

Der Wert wird NIE ausgegeben – verglichen wird gegen den auf der Platte
gespeicherten Klartext, gemeldet werden Laenge und Gleichheit.

Lauf AUF DEM SERVER:
    runuser -u jarvis -- venv/bin/python /tmp/live_pwreveal_ui_dev.py
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
import urllib3
urllib3.disable_warnings()
from backend.main import generate_token
from backend.config import config

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


mounts = ((config.get_skill_states().get("knowledge", {}) or {})
          .get("config", {}) or {}).get("mounts") or []
IDX = next((i for i, m in enumerate(mounts) if (m or {}).get("password")), None)
if IDX is None:
    print("ABBRUCH: auf DEV liegt keine Freigabe mit Kennwort – nichts zu messen")
    sys.exit(2)
ERWARTET = str(mounts[IDX]["password"])

PORT, prof = 9347, "/tmp/chrome-pwreveal"
subprocess.run(["rm", "-rf", prof], check=False)
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1500,1000", "--no-first-run",
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
    if r.get("exceptionDetails"):
        return {"_fehler": str(r["exceptionDetails"])[:200]}
    return (r.get("result") or {}).get("value")


def schuss(datei):
    r = cmd("Page.captureScreenshot", {"format": "png"})
    if r.get("data"):
        open(datei, "wb").write(base64.b64decode(r["data"]))


try:
    for thema in ("dark", "light"):
        print("\n\033[1mThema: %s\033[0m" % thema)
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(2)
        js("localStorage.setItem('jarvis_token', %s);"
           "localStorage.setItem('jarvis_theme', %s);"
           % (json.dumps(TOK), json.dumps(thema)))
        cmd("Page.navigate", {"url": "https://127.0.0.1/settings"})
        time.sleep(6)

        # ⚠ DAS MODAL MUSS AUF, SONST IST NICHTS MESSBAR. Im geschlossenen
        # Zustand liegt der ganze Reiter in einem `display:none`-Vorfahren –
        # jedes Rechteck darin ist dann 0, und eine Pruefung "das Auge liegt im
        # Feld" ist mit 0 <= 0 trivial wahr. Genau diese Falle hat beim ersten
        # Lauf ein "Auge 0x0 px" gemeldet, obwohl es 23x23 ist (Register:
        # dieselbe Klasse wie die Vorfallsliste am 2026-09-02).
        js("window._openSettingsModal && window._openSettingsModal()")
        time.sleep(2)
        js("""(function(){
            var b = document.querySelector('[data-settings-tab=\"knowledge\"]');
            if (b) b.click();
        })()""")
        time.sleep(2)

        # ⚠ UND DER KLAPP-CONTAINER MUSS AUF. "Netzwerk-Freigaben" startet zu;
        # im eingeklappten Zustand ist jedes Rechteck darin 0 – die erste
        # Fassung meldete deshalb "Auge 0x0 px", obwohl es 23x23 ist.
        js("""(function(){
            var b = document.getElementById('kb-sect-net-body');
            if (!b) return 'kein body';
            if (getComputedStyle(b).display !== 'none') return 'schon offen';
            var h = b.previousElementSibling;
            if (h) h.click();
            return 'geklickt';
        })()""")
        time.sleep(1)

        # Die Freigabenliste ueber den ECHTEN Weg holen und das Formular
        # ueber den ECHTEN Klickpfad oeffnen (showEditMount haengt am ✏️).
        js("window.knowledgeManager && window.knowledgeManager.fetchMounts()")
        time.sleep(3)
        js("window.knowledgeManager.showEditMount(%d)" % IDX)
        time.sleep(1)

        # Welcher Vorfahr verbirgt noch? (Ein Klapp-Container startet zu –
        # Register: im eingeklappten Zustand ist NICHTS messbar.)
        verdeckt = js("""(function(){
            var f = document.getElementById('kb-mount-edit-%d');
            if (!f) return 'FORMULAR FEHLT';
            var kette = [];
            for (var e = f; e && e !== document.documentElement; e = e.parentElement) {
                var cs = getComputedStyle(e);
                if (cs.display === 'none' || cs.visibility === 'hidden')
                    kette.push((e.id || e.className || e.tagName) + ':' + cs.display);
            }
            return kette.join(' | ') || 'nichts verdeckt';
        })()""" % IDX)
        print("    verdeckende Vorfahren: %s" % verdeckt)

        d = js("""(function(){
            var f = document.getElementById('kb-mount-edit-%d');
            if (!f) return {da:false};
            var inp = f.querySelector('.kb-mount-edit-pass');
            if (!inp) return {da:true, feld:false};
            var auge = null;
            for (var k = inp.parentElement.firstElementChild; k; k = k.nextElementSibling)
                if (k.classList && k.classList.contains('jv-pw-eye')) auge = k;
            var ri = inp.getBoundingClientRect(), ra = auge ? auge.getBoundingClientRect() : null;
            return {da:true, feld:true, auge: !!auge,
                    typ: inp.type, platz: inp.placeholder,
                    quelle: inp.dataset.pwQuelle, kennung: inp.dataset.pwKennung,
                    feldbreite: Math.round(ri.width),
                    innen: ra ? (ra.right <= ri.right + 2 && ra.left >= ri.left) : false,
                    breite: ra ? Math.round(ra.width) : 0,
                    hoehe: ra ? Math.round(ra.height) : 0,
                    pad: getComputedStyle(inp).paddingRight,
                    ueberlauf: document.documentElement.scrollWidth > window.innerWidth + 1};
        })()""" % IDX)
        check("das Bearbeiten-Formular ist offen und traegt das Kennwortfeld",
              isinstance(d, dict) and d.get("feld"), str(d)[:180])
        if not (isinstance(d, dict) and d.get("feld")):
            continue
        check("Positivkontrolle der MESSUNG: das Feld hat ueberhaupt eine Groesse",
              (d.get("feldbreite") or 0) > 20, "Feldbreite %s" % d.get("feldbreite"))
        check("⚠ das Auge sitzt INNERHALB des Feldes", d.get("auge") and d.get("innen"),
              str(d)[:200])
        check("… und ist %sx%s px gross" % (d.get("breite"), d.get("hoehe")),
              (d.get("breite") or 0) >= 14 and (d.get("hoehe") or 0) >= 14, str(d))
        check("… das Feld haelt Platz frei (%s)" % d.get("pad"),
              d.get("pad", "").startswith("38"), d.get("pad"))
        check("das Feld ist verborgen und zeigt Sterne",
              d.get("typ") == "password" and "•" in (d.get("platz") or ""),
              "%s / %r" % (d.get("typ"), d.get("platz")))
        check("die Quelle ist gesetzt (mount:%s)" % d.get("kennung"),
              d.get("quelle") == "mount" and d.get("kennung") == str(IDX), str(d)[:120])
        check("kein waagerechter Ueberlauf", not d.get("ueberlauf"))

        # ── DER KERN: klicken und den WERT messen ─────────────────────────
        js("""(function(){
            var f = document.getElementById('kb-mount-edit-%d');
            var inp = f.querySelector('.kb-mount-edit-pass');
            for (var k = inp.parentElement.firstElementChild; k; k = k.nextElementSibling)
                if (k.classList && k.classList.contains('jv-pw-eye')) k.click();
        })()""" % IDX)
        time.sleep(2)
        e = js("""(function(){
            var f = document.getElementById('kb-mount-edit-%d');
            var inp = f.querySelector('.kb-mount-edit-pass');
            var auge = null;
            for (var k = inp.parentElement.firstElementChild; k; k = k.nextElementSibling)
                if (k.classList && k.classList.contains('jv-pw-eye')) auge = k;
            return {typ: inp.type, laenge: (inp.value||'').length, wert: inp.value,
                    platz: inp.placeholder, titel: auge ? auge.title : ''};
        })()""" % IDX)
        check("⚠ ein Klick macht das Feld sichtbar", e.get("typ") == "text", str(e.get("typ")))
        check("⚠⚠ DER GESPEICHERTE WERT STEHT IM FELD (%d Zeichen)" % len(ERWARTET),
              e.get("wert") == ERWARTET, "geliefert %d Zeichen" % (e.get("laenge") or 0))
        check("… der Sterne-Platzhalter ist weg (er stand fuer genau diesen Wert)",
              not (e.get("platz") or "").strip("•") == "" or not e.get("platz"),
              repr(e.get("platz")))
        check("… und die Beschriftung sagt jetzt 'verbergen'",
              "verberg" in (e.get("titel") or "").lower(), e.get("titel"))

        # Zweiter Klick: verbergen, Wert bleibt (er ist schon geholt).
        js("""(function(){
            var f = document.getElementById('kb-mount-edit-%d');
            var inp = f.querySelector('.kb-mount-edit-pass');
            for (var k = inp.parentElement.firstElementChild; k; k = k.nextElementSibling)
                if (k.classList && k.classList.contains('jv-pw-eye')) k.click();
        })()""" % IDX)
        time.sleep(1)
        z = js("""(function(){
            var f = document.getElementById('kb-mount-edit-%d');
            var inp = f.querySelector('.kb-mount-edit-pass');
            return {typ: inp.type, laenge: (inp.value||'').length};
        })()""" % IDX)
        check("ein zweiter Klick verbirgt wieder", z.get("typ") == "password", str(z))
        check("… der geholte Wert bleibt im Feld (kein zweiter Serveraufruf noetig)",
              z.get("laenge") == len(ERWARTET), str(z))

        # ── Felder, die VERBORGEN entstanden sind ─────────────────────────
        # ⚠ DAS IST DER TEIL, DEN JSDOM NICHT KANN: dort gibt es kein Layout.
        # Gemessen wird OHNE jede Interaktion am Feld – die Breite des Wrappers
        # wird aus der Breitenangabe des Feldes uebernommen, nicht aus einer
        # Messung (die im geschlossenen Dialog 0 waere).
        js("""(function(){
            var b = document.querySelector('[data-settings-tab=\"security\"]');
            if (b) b.click();
        })()""")
        time.sleep(2)
        js("""(function(){
            var i = document.getElementById('ad-bind-password'); if (!i) return;
            for (var e = i; e; e = e.parentElement) {
                var cs = getComputedStyle(e);
                if (cs.display === 'none' && e.previousElementSibling)
                    e.previousElementSibling.click();
            }
            i.scrollIntoView({block: 'center'});
        })()""")
        time.sleep(2)
        a = js("""(function(){
            var i = document.getElementById('ad-bind-password');
            if (!i) return {fehlt: true};
            var w = i.parentElement;
            var auge = w.querySelector(':scope > .jv-pw-eye');
            if (!auge) return {kein_auge: true};
            var ri = i.getBoundingClientRect(), ra = auge.getBoundingClientRect();
            return {feld: Math.round(ri.width), abstand: Math.round(ri.right - ra.right),
                    innen: ra.right <= ri.right + 2 && ra.left >= ri.left,
                    sichtbar: ri.width > 0, wrapBreite: w.style.width};
        })()""")
        check("Positivkontrolle: das AD-Feld ist sichtbar (%s px)" % (
              a.get("feld") if isinstance(a, dict) else a),
              isinstance(a, dict) and a.get("sichtbar"), str(a)[:150])
        if isinstance(a, dict) and a.get("sichtbar"):
            check("⚠ ein VERBORGEN entstandenes Feld (60 %%) hat sein Auge im Feld "
                  "(Abstand %s px, Wrapper %s)" % (a.get("abstand"), a.get("wrapBreite")),
                  a.get("innen") and 4 <= (a.get("abstand") or 0) <= 14, str(a))

        # ── Handverdrahtetes Auge: es darf KEIN zweites daneben stehen ─────
        js("""(function(){
            var b = document.querySelector('[data-settings-tab=\"profiles\"]');
            if (b) b.click();
        })()""")
        time.sleep(2)
        z = js("""(function(){
            var i = document.getElementById('profile-api-key');
            if (!i) return {fehlt: true};
            var blk = i.closest('.input-group') || i.parentElement;
            var n = 0;
            blk.querySelectorAll('.jv-pw-eye, button').forEach(function (el) {
                if ((el.classList && el.classList.contains('jv-pw-eye'))
                    || /eye|auge|toggle/i.test((el.id || '') + ' ' + (el.className || ''))) n++;
            });
            return {augen: n};
        })()""")
        check("⚠ am Profil-Schluessel steht GENAU EIN Auge (das handverdrahtete)",
              isinstance(z, dict) and z.get("augen") == 1, str(z))

        schuss("/tmp/pwreveal-%s.png" % thema)
        print("    Screenshot: /tmp/pwreveal-%s.png" % thema)
finally:
    try:
        ws.close()
    except Exception:  # noqa: BLE001
        pass
    p.terminate()
    subprocess.run(["rm", "-rf", prof], check=False)

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
