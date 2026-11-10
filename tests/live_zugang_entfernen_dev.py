#!/usr/bin/env python3
"""Durchstich auf DEV: "Eigenen Zugang entfernen" im ECHTEN Browser.

Die Waechter messen die Teile einzeln (Auskunft des Servers, Verhalten in
jsdom, Kaskade in Chrome an der Seite ohne Skripte). Hier laeuft die ganze
Kette: echte Sitzung, ausgelieferte Seite, laufender Dienst. Gemessen wird je
Seite (/sap, /vemas), ob der Knopf GENAU dann zu sehen ist, wenn der Dienst
fuer dieses Konto ``gespeichert`` meldet – und "Abmelden" genau dann, wenn die
Kachel-Anmeldung gilt und angemeldet ist.

NUR LESEND: es wird nichts geschaltet, gespeichert oder entfernt. Welche
Richtung (sichtbar / verborgen) gemessen wird, haengt deshalb am Bestand des
Testkontos; die Probe nennt sie in der Ausgabe.

Laeuft AUF DEV ueber den Hauptschluessel (das Token stellt nur der Dienst aus):
    cd /opt/jarvis && bash deploy/als_dienst.sh venv/bin/python \\
         tests/live_zugang_entfernen_dev.py
Zustand: die Probe-Sitzung wird am Ende widerrufen, das Chrome-Profil geloescht.
Bilder: ~/.jarvis-abnahme/zugang-entfernen-<seite>.png
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
sys.argv = ["x"]
import requests  # noqa: E402
import urllib3  # noqa: E402
import ziele  # noqa: E402
from backend import main as M  # noqa: E402

urllib3.disable_warnings()

BENUTZER = M._display_name(ziele.wert("JARVIS_DEV_TESTUSER"))
TOKEN = M.generate_token(BENUTZER)
M._sitzung.flush()
BILDER = Path.home() / ".jarvis-abnahme"
BILDER.mkdir(mode=0o700, exist_ok=True)

# (Seite, API, Praefix, Element, das erst NACH der Kontoauskunft Text traegt)
SEITEN = [
    ("/sap", "/api/sap/account", "sp", "sp-acc-hosts"),
    ("/vemas", "/api/vemas/account", "vm", "vm-acc-write"),
]

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % str(info)[:300]) if info else ""))


PROFIL = tempfile.mkdtemp(prefix="chrome-zugang-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
_s = socket.socket()
_s.bind(("127.0.0.1", 0))
PORT = _s.getsockname()[1]
_s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1300,1100", "--ignore-certificate-errors",
     "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def aufraeumen():
    try:
        chrome.kill()
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(PROFIL, ignore_errors=True)
    try:
        teile = TOKEN.split(":", 2)
        if len(teile) == 3:
            M._sitzung.widerrufe(teile[2], int(teile[1]))
            M._sitzung.flush()
    except Exception as e:  # noqa: BLE001
        print("  !!   Probe-Sitzung nicht widerrufen: %s" % e)


def ende(code):
    aufraeumen()
    print("\n" + "=" * 60)
    print("Ergebnis: %d OK, %d FAIL" % (_ok, _fail))
    sys.exit(code)


def abbruch(text):
    print("ABBRUCH: %s" % text)
    aufraeumen()
    sys.exit(2)


def cdp_ziel():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as a:
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


ws_url = cdp_ziel()
if not ws_url:
    abbruch("kein CDP-Ziel")
try:
    from websockets.sync.client import connect  # noqa: E402
except ImportError:
    abbruch("python-websockets fehlt im venv")

_id = [0]


def cdp(sock, methode, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": methode, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=60))
        if d.get("id") == _id[0]:
            return d.get("result", {})


def pumpen(sock, sekunden):
    schluss = time.time() + sekunden
    while time.time() < schluss:
        try:
            sock.recv(timeout=max(0.05, schluss - time.time()))
        except TimeoutError:
            break


def js(sock, ausdruck):
    r = cdp(sock, "Runtime.evaluate", expression=ausdruck, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def warte(sock, ausdruck, frist):
    schluss = time.time() + frist
    while time.time() < schluss:
        if js(sock, ausdruck):
            return True
        pumpen(sock, 0.5)
    return False


# Lage eines Knopfes: Attribut, berechnete Anzeige und ob er Flaeche hat. Der
# Abschnitt ist ein <details> – zugeklappt haette NICHTS darin Flaeche, also
# wird er vorher geoeffnet (sonst waere "verborgen" trivial wahr).
LAGE = """(function(id){
  var e=document.getElementById(id); if(!e) return null;
  var d=e.closest('details'); if(d) d.open=true;
  var r=e.getBoundingClientRect();
  return {hidden:e.hidden, display:getComputedStyle(e).display, breite:Math.round(r.width),
          x:r.left+window.scrollX, y:r.top+window.scrollY, text:(e.textContent||'').trim()};
})(%s)"""

sitzung = requests.Session()
sitzung.verify = False
sitzung.headers["Authorization"] = "Bearer " + TOKEN
richtungen = set()
try:
    with connect(ws_url, max_size=80 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        # Sitzung ablegen: gleicher Ursprung, aber eine Adresse ohne Seiten-Skripte
        cdp(sock, "Page.navigate", url="https://127.0.0.1/api/health")
        pumpen(sock, 2)
        js(sock, "localStorage.clear();localStorage.setItem('jarvis_token'," + json.dumps(TOKEN)
           + ");localStorage.setItem('jarvis_user'," + json.dumps(BENUTZER)
           + ");localStorage.setItem('jarvis_lang','de');true")
        cdp(sock, "Page.navigate", url="https://127.0.0.1/portal")
        if not warte(sock, "(localStorage.getItem('jarvis_token')||'').indexOf('JCS1.')===0", 30):
            abbruch("die Sitzung kam im Browser nicht an (keine Umstellung auf das Cookie)")

        for seite, api, pre, marke in SEITEN:
            print("\n%s" % seite)
            r = sitzung.get("https://127.0.0.1" + api, timeout=30)
            if r.status_code != 200:
                print("  --   nicht messbar: das Testkonto hat hier keinen Zugriff (HTTP %d)" % r.status_code)
                continue
            konto = (r.json() or {}).get("account") or {}
            if "gespeichert" not in konto:
                check("der Dienst liefert das Feld 'gespeichert'", False, sorted(konto)[:12])
                continue
            soll = konto["gespeichert"] is True
            soll_ab = bool(konto.get("kachel_pflicht") and konto.get("angemeldet"))

            cdp(sock, "Page.navigate", url="https://127.0.0.1" + seite)
            geladen = warte(sock, "location.pathname===%s && !!document.getElementById(%s)"
                            " && (document.getElementById(%s).textContent||'').trim()!==''"
                            % (json.dumps(seite), json.dumps(marke), json.dumps(marke)), 40)
            if not geladen:
                abbruch("%s: die Kontoauskunft kam in der Seite nicht an (Adresse jetzt: %s)"
                        % (seite, js(sock, "location.pathname")))
            pumpen(sock, 1)
            knopf = js(sock, LAGE % json.dumps(pre + "-acc-del"))
            ab = js(sock, LAGE % json.dumps(pre + "-acc-logout"))
            sichern = js(sock, LAGE % json.dumps(pre + "-acc-save"))
            if not knopf or not ab or not sichern:
                abbruch("%s: Knopf fehlt in der ausgelieferten Seite" % seite)
            # Positivkontrolle: der Abschnitt ist offen und hat Flaeche – sonst
            # hiesse "keine Breite" nur "zugeklappt".
            if sichern["display"] == "none" or sichern["breite"] <= 0:
                abbruch("%s: der Abschnitt hat keine Flaeche (%s)" % (seite, sichern))

            ist = knopf["display"] != "none" and knopf["breite"] > 0
            ist_ab = ab["display"] != "none" and ab["breite"] > 0
            richtungen.add("sichtbar" if soll else "verborgen")
            check("'%s' ist %s – der Dienst meldet gespeichert=%s"
                  % (knopf["text"], "sichtbar" if soll else "verborgen", soll), ist is soll, knopf)
            check("'%s' ist %s (Kachel-Anmeldung=%s, angemeldet=%s)"
                  % (ab["text"], "sichtbar" if soll_ab else "verborgen",
                     bool(konto.get("kachel_pflicht")), bool(konto.get("angemeldet"))),
                  ist_ab is soll_ab, ab)

            # Bild der Knopfzeile – clip rechnet in SEITEN-Koordinaten.
            try:
                bild = cdp(sock, "Page.captureScreenshot", format="png", captureBeyondViewport=True,
                           clip={"x": max(0, sichern["x"] - 20), "y": max(0, sichern["y"] - 20),
                                 "width": 1100, "height": 80, "scale": 1})
                ziel = BILDER / ("zugang-entfernen-%s.png" % seite.strip("/"))
                ziel.write_bytes(base64.b64decode(bild.get("data", "")))
                print("  --   Bild: %s" % ziel)
            except Exception as e:  # noqa: BLE001 – das Bild ist Beigabe, kein Urteil
                print("  --   kein Bild (%s)" % e)
except SystemExit:
    raise
except Exception as e:  # noqa: BLE001
    abbruch("%s: %s" % (type(e).__name__, e))

if not (_ok or _fail):
    abbruch("keine Seite war messbar")
print("\ngemessene Richtung(en): %s" % (", ".join(sorted(richtungen)) or "keine"))
ende(1 if _fail else 0)
