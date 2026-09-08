"""LIVE Ende-zu-Ende (DEV, echtes Chrome): wirkt die Vorauswahl im NEUEN Chat?

Gemessen wird die GANZE Kette mit den ECHTEN Wissensgruppen von DEV:
  Dialog -> Speichern -> "+ Neuer Chat" -> Filter der Eingabeleiste -> die
  Auswahl, die in der Sitzung landet und mit der naechsten Frage rausgeht.

Der VORGEFUNDENE Stand wird gesichert und am Ende wiederhergestellt.
"""
import json, subprocess, sys, time, urllib.request
import websocket
sys.path.insert(0, "/opt/jarvis"); sys.argv = ["x"]
import urllib3; urllib3.disable_warnings()
from backend.main import generate_token          # noqa: E402
from backend import chat_sessions as cs          # noqa: E402

USER = "jarvis"
TOK = generate_token(USER)
VORHER = cs.get_kb_default(USER)
VORHER_SIDS = {s["id"] for s in cs.list_sessions(USER)}
ok = fail = 0
def check(n, c, d=""):
    global ok, fail
    if not isinstance(n, str): print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if c: ok += 1; print("  \033[32m✓\033[0m %s" % n)
    else: fail += 1; print("  \033[31m✗\033[0m %s%s" % (n, (" – %s" % d) if d else ""))

PORT, prof = 9357, "/tmp/kbvor_ui/prof-e2e"
subprocess.run(["rm", "-rf", prof], check=False, capture_output=True)
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1400,900", "--no-first-run",
                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)
tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
n = [0]
def cmd(m, pr=None):
    n[0] += 1; ws.send(json.dumps({"id": n[0], "method": m, "params": pr or {}}))
    while True:
        d = json.loads(ws.recv())
        if d.get("id") == n[0]: return d.get("result", {})
def js(c):
    r = cmd("Runtime.evaluate", {"expression": c, "returnByValue": True, "awaitPromise": True})
    if r.get("exceptionDetails"): return {"_f": str(r["exceptionDetails"])[:300]}
    return (r.get("result") or {}).get("value")

try:
    cmd("Page.navigate", {"url": "https://127.0.0.1/portal"}); time.sleep(2)
    js("localStorage.setItem('jarvis_token', %s); localStorage.setItem('jarvis_user','jarvis');"
       "localStorage.setItem('jarvis_theme','dark');" % json.dumps(TOK))
    # Ausgangslage: keine Vorauswahl
    cs.save_kb_default(USER, [])
    cmd("Page.navigate", {"url": "https://127.0.0.1/chat"}); time.sleep(9)

    print("\n\033[1m1. Ausgangslage ohne Vorauswahl\033[0m")
    r = js("""(function(){ var b=document.querySelector('#kb-filter-slot .kbgf-btn');
               return b ? b.querySelector('.kbgf-badge').textContent.trim() : 'kein Filter'; })()""")
    check("der Filter der Eingabeleiste ist da (Ausgangs-Badge: %r)" % r,
          isinstance(r, str) and r not in ("kein Filter", ""), repr(r))
    gruppen = js("""(async function(){ var e = await window.KbGroupFilter.loadEntries();
                     return e.map(x=>x.id).join(','); })()""")
    check("die ECHTEN Gruppen von DEV sind da (Positivkontrolle)",
          isinstance(gruppen, str) and "allgemein" in gruppen and "ungrouped" in gruppen, repr(gruppen))

    print("\n\033[1m2. Im Dialog eine Gruppe abwaehlen und speichern\033[0m")
    js("document.getElementById('cs-settings').click()"); time.sleep(3)
    r = js("""(function(){
        var d=document.querySelectorAll('#chat-settings-modal .chs-sect')[1];
        if (!d.open) d.querySelector('summary').click();
        return d.open;
    })()""")
    check("der Wissens-Container laesst sich aufklappen", r is True, repr(r))
    time.sleep(1)
    r = js("""(function(){
        var box=document.getElementById('chs-kb-list');
        var cb=box.querySelector('input[value=\\"erlernt\\"]');
        if(!cb) return 'kein Kaestchen fuer erlernt';
        cb.click();
        return box.querySelectorAll('input:checked').length + '/' + box.querySelectorAll('input').length;
    })()""")
    check("Gruppe 'Erlernt' abgehakt", r == "3/4", repr(r))
    js("document.getElementById('btn-chat-settings-save').click()"); time.sleep(3)
    check("auf der PLATTE steht genau diese Abwahl",
          cs.get_kb_default(USER) == ["erlernt"], repr(cs.get_kb_default(USER)))
    check("der Dialog hat sich nach dem Speichern geschlossen",
          js("document.getElementById('chat-settings-modal').classList.contains('hidden')") is True)

    print("\n\033[1m3. '+' Neuer Chat' -> greift die Vorauswahl?\033[0m")
    js("document.getElementById('cs-new').click()"); time.sleep(5)
    r = js("""(function(){ var b=document.querySelector('#kb-filter-slot .kbgf-btn');
               return b ? b.querySelector('.kbgf-badge').textContent.trim() : 'kein Filter'; })()""")
    check("⚠ der Filter zeigt im NEUEN Chat die Vorauswahl (3/4, nicht 'alle')", r == "3/4", repr(r))

    # Was ist WIRKLICH ausgewaehlt? Ueber das Popup des Filters gelesen – das
    # ist dieselbe Menge, die mit der naechsten Frage als kb_groups rausgeht.
    r = js("""(function(){
        document.querySelector('#kb-filter-slot .kbgf-btn').click();
        var an=[].slice.call(document.querySelectorAll('#kb-filter-slot .kbgf-panel input:checked'))
                 .map(x=>x.value).sort().join(',');
        return an;
    })()""")
    check("⚠ und zwar genau die drei uebrigen Gruppen",
          r == "allgemein,knowledgebase-an-rag,ungrouped", repr(r))

    print("\n\033[1m4. Die Auswahl landet in der Sitzung (Weg zur naechsten Frage)\033[0m")
    sid = js("(function(){ return localStorage.getItem('jarvis_chat_sid_jarvis'); })()")
    check("die neue Sitzung ist bekannt", isinstance(sid, str) and len(sid) > 4, repr(sid))
    check("frisch angelegt hat sie noch KEINE gespeicherte Auswahl (richtig: erst der Turn schreibt)",
          isinstance(sid, str) and (cs.get_meta(USER, sid) or {}).get("kb_groups") is None,
          repr((cs.get_meta(USER, sid) or {}).get("kb_groups")))
    # Eine Aenderung DURCH DEN BENUTZER im Filter loest _persistSession aus –
    # damit ist die Kette "Auswahl -> Sitzung" messbar, ohne ein Modell zu fragen.
    js("""(function(){
        var cb=document.querySelector('#kb-filter-slot .kbgf-panel input[value=\"allgemein\"]');
        if (cb) { cb.checked=false; cb.dispatchEvent(new Event('change', {bubbles:true})); }
    })()""")
    time.sleep(3)
    if isinstance(sid, str):
        gespeichert = (cs.get_meta(USER, sid) or {}).get("kb_groups")
        check("⚠ eine Aenderung im Filter landet in der Sitzung",
              gespeichert == ["knowledgebase-an-rag", "ungrouped"], repr(gespeichert))

    print("\n\033[1m5. Bestandssitzung MIT Verlauf bleibt bei 'alle'\033[0m")
    alt = cs.create_session(USER, "E2E Altbestand")
    cs.save_transcript(USER, alt["id"], [{"role": "user", "text": "alte Frage"},
                                         {"role": "bot", "text": "alte Antwort"}])
    m = cs.get_meta(USER, alt["id"]) or {}
    m.pop("kb_groups", None)
    cs._write_meta(cs._sess_dir(USER, alt["id"]), m)
    check("Testsitzung praepariert (Verlauf da, keine gespeicherte Auswahl)",
          "kb_groups" not in (cs.get_meta(USER, alt["id"]) or {}))
    # Die Liste neu holen und ueber den ECHTEN Klickweg wechseln.
    js("window.location.reload()")
    time.sleep(10)
    geklickt = js("""(function(){
        var el=[].slice.call(document.querySelectorAll('#cs-list .cs-item'))
            .filter(x=>/E2E Altbestand/.test(x.textContent))[0];
        if (!el) return 'nicht in der Liste';
        el.click(); return 'geklickt';
    })()""")
    time.sleep(5)
    aktiv = js("(function(){ return localStorage.getItem('jarvis_chat_sid_jarvis'); })()")
    check("der Wechsel hat WIRKLICH stattgefunden (Positivkontrolle)",
          geklickt == "geklickt" and aktiv == alt["id"], "%r / %r vs %r" % (geklickt, aktiv, alt["id"]))
    r = js("""(function(){ var b=document.querySelector('#kb-filter-slot .kbgf-btn');
               return b ? b.querySelector('.kbgf-badge').textContent.trim() : '-'; })()""")
    check("⚠ dort steht 'alle' – ein laufender Chat wird nicht still umgestellt",
          r in ("alle", "all"), repr(r))
    cs.delete_session(USER, alt["id"])

    print("\n\033[1m6. Vorauswahl 'keine' UEBER DEN DIALOG -> neuer Chat ohne Wissen\033[0m")
    js("document.getElementById('cs-settings').click()"); time.sleep(3)
    js("""(function(){ var d=document.querySelectorAll('#chat-settings-modal .chs-sect')[1];
           if (!d.open) d.querySelector('summary').click(); })()"""); time.sleep(1)
    js("document.getElementById('chs-kb-none').click()"); time.sleep(1)
    js("document.getElementById('btn-chat-settings-save').click()"); time.sleep(3)
    check("alle vier Gruppen sind abgewaehlt gespeichert",
          len(cs.get_kb_default(USER) or []) == 4, repr(cs.get_kb_default(USER)))
    js("document.getElementById('cs-new').click()"); time.sleep(5)
    r = js("""(function(){ var b=document.querySelector('#kb-filter-slot .kbgf-btn');
               return b ? b.querySelector('.kbgf-badge').textContent.trim() : '-'; })()""")
    check("der Filter zeigt 0/4 (neuer Chat startet ohne Wissensdatenbank)", r == "0/4", repr(r))

finally:
    try: ws.close()
    except Exception: pass
    p.terminate()
    subprocess.run(["rm", "-rf", prof], check=False, capture_output=True)
    cs.save_kb_default(USER, VORHER or [])
    # Nur die in diesem Lauf entstandenen Sitzungen abraeumen.
    neu = [s["id"] for s in cs.list_sessions(USER) if s["id"] not in VORHER_SIDS]
    for s in neu: cs.delete_session(USER, s)
    rest = [s["id"] for s in cs.list_sessions(USER) if s["id"] not in VORHER_SIDS]
    gleich = (cs.get_kb_default(USER) == VORHER) and not rest
    print(("  \033[32m✓\033[0m " if gleich else "  \033[31m✗\033[0m ")
          + "Ausgangszustand wiederhergestellt (Vorauswahl %r, %d Test-Sitzungen entfernt, %d Reste)"
          % (cs.get_kb_default(USER), len(neu), len(rest)))
    if gleich: ok += 1
    else: fail += 1

print("\n\033[1mErgebnis: %d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
