"""Abnahme im ECHTEN Chrome auf DEV: Bild einfuegen und Bild ablegen in /chat.

WARUM DAS NICHT DER jsdom-WAECHTER LEISTET: jsdom rendert nicht und dekodiert
kein Bild. Die Frage des Betreibers lautet aber woertlich, dass die eingefuegte
Grafik SICHTBAR sein soll - das beantwortet nur ein Browser, der sie wirklich
dekodiert (`img.decode()`, `naturalWidth > 0`). Und `ClipboardEvent` mit echtem
`DataTransfer` gibt es in jsdom gar nicht.

GEMESSEN WIRD:
  1) Strg+V mit einem Bild in der Zwischenablage -> Vorschau ueber dem
     Eingabefeld, und das Bild ist WIRKLICH dekodiert.
  2) Der gemeldete Fall: ein JPG, das der Browser OHNE MIME-Typ liefert
     (Drag & Drop) - es muss als Bild gefuehrt werden, nicht als Datei.
  3) Reiner Text beim Einfuegen bleibt unangetastet.

Der Lauf raeumt hinter sich auf: er sendet nichts und legt keine Sitzung an.

    (auf DEV)  /opt/jarvis/venv/bin/python /opt/jarvis/tests/live_chat_einfuegen_ui_dev.py
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

TOK = generate_token("jarvis")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    # Vertauschte Argumente wuerden jede Bedingung wahr machen (Register).
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum")
        sys.exit(2)
    if cond:
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


PORT, PROF = 9366, "/tmp/chrome-chateinf"
subprocess.run(["rm", "-rf", PROF], check=False)
# Chromes Ausgabe NICHT nach DEVNULL: ein verschluckter Startfehler wird sonst
# zu einer Fehldiagnose am eigenen Code (Register).
p = subprocess.Popen(
    ["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
     f"--user-data-dir={PROF}", "--ignore-certificate-errors", "--no-sandbox",
     "--disable-gpu", "--remote-allow-origins=*", "--window-size=1400,900",
     "--no-first-run", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(6)
try:
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: kein CDP – %s" % e)
    p.kill()
    sys.exit(2)
# ⚠ Nur `type == "page"`: /json listet auch die eingebauten Erweiterungen, und
# "der erste" ist keine Identitaet (Register).
seiten = [t for t in tabs if t.get("type") == "page"]
if not seiten:
    print("ABBRUCH: keine Seite im Browser")
    p.kill()
    sys.exit(2)
ws = websocket.create_connection(seiten[0]["webSocketDebuggerUrl"])
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
    if "exceptionDetails" in r:
        return {"__wurf": str(r["exceptionDetails"].get("exception", {}).get("description", ""))[:200]}
    return (r.get("result") or {}).get("value")


JPG = ("/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
       "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
       "AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==")
PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
       "IQAAAABJRU5ErkJggg==")

# Das Sitzungstoken MUSS vor dem ersten Skript der Seite liegen - sonst leitet
# /chat sofort aufs Portal um, und jede Messung darunter ist trivial wahr.
cmd("Page.enable")
cmd("Page.addScriptToEvaluateOnNewDocument",
    {"source": "localStorage.setItem('jarvis_token', %s);" % json.dumps(TOK)})
cmd("Page.navigate", {"url": "https://127.0.0.1/chat"})
time.sleep(9)

print("\n=== 0. Positivkontrolle: die Seite ist wirklich geladen ===")
geladen = js("(function(){return {pfad:location.pathname,"
             " feld:!!document.getElementById('msg-input'),"
             " bar:!!document.getElementById('attach-preview-bar')};})()")
check("/chat ist geladen (keine Umleitung aufs Portal)",
      isinstance(geladen, dict) and geladen.get("pfad") == "/chat", str(geladen))
check("Eingabefeld und Anhang-Leiste sind da",
      isinstance(geladen, dict) and geladen.get("feld") and geladen.get("bar"), str(geladen))

HELFER = """
window.__datei = function (b64, name, mime) {
    const roh = atob(b64); const u = new Uint8Array(roh.length);
    for (let i = 0; i < roh.length; i++) u[i] = roh.charCodeAt(i);
    return mime ? new File([u], name, { type: mime }) : new File([u], name);
};
window.__chip = async function () {
    const c = document.querySelector('#attach-preview-bar .attach-chip');
    if (!c) return { da: false };
    const img = c.querySelector('img');
    let dek = false, breite = 0;
    if (img) { try { await img.decode(); dek = true; breite = img.naturalWidth; } catch (e) {} }
    return { da: true, hatImg: !!img, src: img ? String(img.src).slice(0, 30) : '',
             dekodiert: dek, breite: breite, text: c.textContent.trim().slice(0, 40) };
};
window.__leeren = function () {
    document.querySelectorAll('#attach-preview-bar .attach-chip-remove').forEach(b => b.click());
};
"""
js(HELFER)

print("\n=== 1. Einfuegen (Strg+V) mit einem Bild in der Zwischenablage ===")
js("""(function(){
    const dt = new DataTransfer();
    dt.items.add(window.__datei('%s', '', 'image/png'));
    const ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
    document.getElementById('msg-input').dispatchEvent(ev);
    window.__verhindert = ev.defaultPrevented;
})()""" % PNG)
time.sleep(1.5)
r = js("window.__chip()")
check("eine Vorschau erscheint ueber dem Eingabefeld", isinstance(r, dict) and r.get("da"), str(r))
check("sie zeigt ein Bild (kein Symbol, kein Dateiname)",
      isinstance(r, dict) and r.get("hatImg") and r.get("src", "").startswith("data:image/png"), str(r))
check("⚠ das Bild ist WIRKLICH dekodiert (es ist sichtbar, nicht nur vorhanden)",
      isinstance(r, dict) and r.get("dekodiert") and (r.get("breite") or 0) > 0, str(r))
check("der Vorgang wurde abgefangen (der Browser fuegt nichts daneben ein)",
      js("window.__verhindert") is True)

print("\n=== 2. Der gemeldete Fall: JPG, das der Browser OHNE MIME liefert ===")
js("window.__leeren()")
time.sleep(0.5)
js("""(function(){
    const dt = new DataTransfer();
    dt.items.add(window.__datei('%s', 'foto.jpg', ''));
    const ev = new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true });
    document.getElementById('msg-input').dispatchEvent(ev);
})()""" % JPG)
time.sleep(1.5)
r2 = js("window.__chip()")
check("das abgelegte JPG erscheint als Bild", isinstance(r2, dict) and r2.get("hatImg"), str(r2))
check("es wird als image/jpeg gefuehrt – nicht als Datei",
      isinstance(r2, dict) and r2.get("src", "").startswith("data:image/jpeg"), str(r2))
check("⚠ auch hier ist das Bild dekodiert",
      isinstance(r2, dict) and r2.get("dekodiert") and (r2.get("breite") or 0) > 0, str(r2))

print("\n=== 3. Gegenprobe: reiner Text bleibt unangetastet ===")
js("window.__leeren()")
time.sleep(0.5)
js("""(function(){
    const dt = new DataTransfer();
    dt.setData('text/plain', 'nur text');
    const ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
    document.getElementById('msg-input').dispatchEvent(ev);
    window.__verhindert2 = ev.defaultPrevented;
})()""")
time.sleep(0.8)
r3 = js("window.__chip()")
check("Text erzeugt keinen Anhang", isinstance(r3, dict) and not r3.get("da"), str(r3))
check("Text wird NICHT abgefangen (gewoehnliches Einfuegen bleibt heil)",
      js("window.__verhindert2") is False)

print("\n=== 4. Keine Fehler in der Konsole ===")
fehler = js("(window.__cdpErr||[]).length")
check("die Seite hat keinen JS-Fehler geworfen", fehler in (0, None), str(fehler))

# Aufraeumen: nichts gesendet, keine Sitzung angelegt, Anhaenge entfernt.
js("window.__leeren()")
try:
    ws.close()
finally:
    p.kill()
    subprocess.run(["rm", "-rf", PROF], check=False)

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
