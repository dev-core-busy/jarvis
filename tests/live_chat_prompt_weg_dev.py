#!/usr/bin/env python3
"""Der GANZE Bedienweg des Chat-Preprompts, im echten Chrome gegen den echten Dienst.

Gemeldet: "der preprompt pro /chat Konversation greift nicht".

Die vorhandenen Proben decken die Enden ab (Endpunkt-Rundlauf, Agentenlauf,
Markup/Layout) – NICHT den Weg dazwischen: Sprechblase klicken, tippen,
speichern, und landet es wirklich in der meta.json? Genau dort wird gemessen.

Rein additiv: legt eine eigene Sitzung an und raeumt sie am Ende wieder ab.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
BASIS = "https://127.0.0.1"
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def freier_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


from backend import main as M                                    # noqa: E402
from backend import chat_sessions as CS                          # noqa: E402

BENUTZER = os.environ.get("CHAT_TESTUSER", "jarvis")
TOKEN = M.generate_token(BENUTZER)

# ── Eigene Sitzung anlegen (nicht in fremde greifen) ───────────────────────
sess = CS.create_session(BENUTZER, "ZZ-Probe Preprompt")
SID = sess["id"] if isinstance(sess, dict) else str(sess)
print("Probe-Sitzung: %s" % SID)

PROFIL = tempfile.mkdtemp(prefix="chatprof_")
CDP = freier_port()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     "--ignore-certificate-errors", "--remote-allow-origins=*",
     "--remote-debugging-port=%d" % CDP, "--user-data-dir=" + PROFIL,
     "--window-size=1400,950", "--no-first-run", "--no-default-browser-check",
     "--disable-extensions", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3.0)

try:
    import websocket
except ImportError:
    print("ABBRUCH: websocket-client fehlt.")
    chrome.kill()
    sys.exit(2)

ziel = None
for _ in range(25):
    try:
        liste = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:%d/json/list" % CDP, timeout=5).read().decode())
        # ⚠ /json/list liefert auch Erweiterungen – auf type=="page" filtern.
        seiten = [x for x in liste if x.get("type") == "page"]
        if seiten:
            ziel = seiten[0]
            break
    except Exception:                                            # noqa: BLE001
        pass
    time.sleep(0.6)
if not ziel:
    print("ABBRUCH: keine CDP-Seite.")
    chrome.kill()
    sys.exit(2)

ws = websocket.create_connection(ziel["webSocketDebuggerUrl"], timeout=30)
_id = [0]


def cdp(methode, **p):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": methode, "params": p}))
    while True:
        a = json.loads(ws.recv())
        if a.get("id") == _id[0]:
            return a.get("result", {})


def js(ausdruck):
    r = cdp("Runtime.evaluate", expression=ausdruck, returnByValue=True,
            awaitPromise=True)
    if r.get("exceptionDetails"):
        return {"_wurf": str(r["exceptionDetails"].get("exception", {}).get(
            "description", ""))[:200]}
    return r.get("result", {}).get("value")


try:
    # Token setzen: die Anmeldemaske ist von der Kommandozeile nicht bedienbar.
    cdp("Page.navigate", url=BASIS + "/chat")
    time.sleep(2.0)
    js("localStorage.setItem('jarvis_token', %s)" % json.dumps(TOKEN))
    cdp("Page.navigate", url=BASIS + "/chat")
    time.sleep(6.0)

    # Positivkontrolle – ohne sie ist jede Messung darunter trivial wahr.
    check(js("location.pathname") == "/chat", "die Chat-Seite ist geladen",
          str(js("location.href"))[:120])
    n = js("document.querySelectorAll('.cs-item').length")
    check(isinstance(n, int) and n > 0, "die Sitzungsliste ist gefuellt",
          "Eintraege: %s" % n)

    # ── 1) Gibt es die Sprechblase an der Zeile? ───────────────────────────
    # ⚠ DIE ZEILE TRAEGT KEIN `data-sid` (gemessen, nicht geraten) – gefunden
    # wird sie ueber ihren Titeltext, der Knopf ueber seine echte Klasse
    # `.cs-prompt` aus `chat.js`.
    treffer = js("""(function(){
      var z = null, alle = document.querySelectorAll('.cs-item');
      for (var i=0;i<alle.length;i++)
        if ((alle[i].textContent||'').indexOf('ZZ-Probe Preprompt') > -1) { z = alle[i]; break; }
      if (!z) return {zeile:false, titel:[].slice.call(alle).map(function(x){
          return (x.textContent||'').trim().slice(0,24);}).slice(0,6)};
      var b = z.querySelector('.cs-prompt');
      return {zeile:true, knopf:!!b, titel:b?(b.getAttribute('title')||''):'',
              gesetzt: b?b.classList.contains('is-gesetzt'):null};
    })()""")
    check(isinstance(treffer, dict) and treffer.get("zeile"),
          "die Probe-Sitzung steht in der Liste", str(treffer)[:200])
    check(isinstance(treffer, dict) and treffer.get("knopf"),
          "und traegt die Prompt-Sprechblase", str(treffer)[:220])

    if isinstance(treffer, dict) and treffer.get("knopf"):
        # ── 2) Dialog oeffnen ──────────────────────────────────────────────
        js("""(function(){
          var z = null, alle = document.querySelectorAll('.cs-item');
          for (var i=0;i<alle.length;i++)
            if ((alle[i].textContent||'').indexOf('ZZ-Probe Preprompt') > -1) { z = alle[i]; break; }
          z.querySelector('.cs-prompt').click();
        })()""")
        time.sleep(1.8)
        auf = js("""(function(){
          var m = document.getElementById('chat-prompt-modal');
          if (!m) return {da:false};
          var cs = getComputedStyle(m), r = m.getBoundingClientRect();
          var ta = document.getElementById('chat-prompt-text');
          return {da:true, hidden:m.classList.contains('hidden'),
                  display:cs.display, opacity:cs.opacity, h:Math.round(r.height),
                  sichtbar:(cs.display!=='none' && parseFloat(cs.opacity)>0.05 && r.height>10),
                  feld:!!ta, gesperrt: ta?ta.disabled:null,
                  status:(document.getElementById('chat-prompt-status')||{}).textContent||''};
        })()""")
        check(isinstance(auf, dict) and auf.get("sichtbar"),
              "der Dialog geht SICHTBAR auf", str(auf)[:220])
        check(isinstance(auf, dict) and auf.get("feld") and not auf.get("gesperrt"),
              "das Textfeld ist da und nicht gesperrt", str(auf)[:220])

        # ── 3) Tippen und speichern – ueber den ECHTEN Knopf ───────────────
        TEXT = "Antworte ausschliesslich in Grossbuchstaben."
        js("""(function(){
          var ta = document.getElementById('chat-prompt-text');
          ta.value = %s;
          ta.dispatchEvent(new Event('input', {bubbles:true}));
          var b = document.getElementById('chat-prompt-save');
          if (b) b.click(); else {
            var k = document.querySelectorAll('#chat-prompt-modal button');
            for (var i=0;i<k.length;i++) if (/speich|save/i.test(k[i].textContent)) { k[i].click(); break; }
          }
        })()""" % json.dumps(TEXT))
        time.sleep(2.5)
        nach = js("""(function(){
          var st = document.getElementById('chat-prompt-status');
          return {status:(st?st.textContent:''),
                  offen:!document.getElementById('chat-prompt-modal').classList.contains('hidden')};
        })()""")
        print("     Status im Dialog: %r" % (nach or {}).get("status", ""))

        # ── 4) DIE ENTSCHEIDENDE MESSUNG: steht es auf Platte? ─────────────
        auf_platte = (CS.get_session_preprompt(BENUTZER, SID) or "").strip()
        check(auf_platte == TEXT,
              "der getippte Text steht in der meta.json der Sitzung",
              "gelesen: %r" % auf_platte[:80])

        # ── 5) Und meldet die Liste `has_prompt`? ──────────────────────────
        r = urllib.request.Request(BASIS + "/api/chat/sessions")
        r.add_header("Authorization", "Bearer " + TOKEN)
        try:
            with urllib.request.urlopen(r, context=__import__("ssl")._create_unverified_context(),
                                        timeout=20) as a:
                liste2 = json.loads(a.read().decode())
        except Exception as e:                                   # noqa: BLE001
            liste2 = {"_fehler": str(e)}
        eintrag = [x for x in (liste2.get("sessions") or []) if x.get("id") == SID]
        check(bool(eintrag) and eintrag[0].get("has_prompt") is True,
              "die Sitzungsliste meldet has_prompt=true",
              str(eintrag[:1])[:200])

        # ── 6) Greift er im ECHTEN Lauf? ──────────────────────────────────
        # Gemessen wird der System-Prompt, den der Agent baut – nicht die
        # Antwort des Modells (die haengt am Modell, nicht am Mechanismus).
        from backend import agent as A                            # noqa: E402
        gesehen = {}
        ag = A.JarvisAgent()

        class _Halt(Exception):
            pass

        class _P:
            async def generate_response(self, *a, **kw):
                gesehen["sp"] = kw.get("system_prompt") or (a[1] if len(a) > 1 else "")
                raise _Halt()

        A.get_provider = lambda *a, **kw: _P()
        import asyncio                                            # noqa: E402

        class _WS:
            async def send_json(self, *a, **kw):
                return None

        try:
            asyncio.run(ag.run_task("Sag Hallo.", _WS(), username=BENUTZER,
                                    session_id=SID))
        except Exception:                                         # noqa: BLE001
            pass
        sp = gesehen.get("sp") or ""
        check(TEXT in sp, "der Chat-Prompt steht im System-Prompt des Laufs",
              "Laenge %d, enthaelt Marke: %s" % (
                  len(sp), "PERSÖNLICHE ANWEISUNG" in sp))

finally:
    ws.close()
    chrome.kill()
    shutil.rmtree(PROFIL, ignore_errors=True)
    try:
        CS.delete_session(BENUTZER, SID)
        print("  … Probe-Sitzung entfernt")
    except Exception as e:                                        # noqa: BLE001
        print("  ⚠ Probe-Sitzung NICHT entfernt: %s" % e)

print("\n%s\n  %d OK, %d FAIL\n%s" % ("=" * 62, _ok, _fail, "=" * 62))
sys.exit(1 if _fail else 0)
