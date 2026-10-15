#!/usr/bin/env python3
"""Durchstich auf DEV: /static/ unter Inhalts-Kennung (backend/static_kennung.py).

Gemessen gegen den LAUFENDEN Dienst und im echten Chrome:

  A. Die ausgelieferten Seiten verweisen auf /static/-Dateien mit
     ``?v=<16 Hex>`` (Positivkontrolle: es gibt solche Einbindungen), und die
     Kennung ist die des Inhalts, den der Dienst unter ihr ausliefert.
  B. Kopfsatz: passende Kennung -> langer Cache; Hand-Nummer, keine Nummer,
     falsche Kennung -> no-cache. Die HTML-Seite selbst bleibt no-store und
     traegt weiter ihre CSP.
  C. Chrome: beim ZWEITEN Besuch einer Seite geht keine Datei mit Kennung mehr
     uebers Netz (transferSize 0); beim ersten Besuch schon (Positivkontrolle,
     sonst misst C einen vorgewaermten Cache). Chrome vertraut dabei genau dem
     Schluessel des DEV-Zertifikats – bei einem Zertifikatsfehler cacht er nichts.

Laeuft AUF DEV ueber den Hauptschluessel:
    bash /opt/jarvis/deploy/als_dienst.sh /opt/jarvis/venv/bin/python \\
         tests/live_static_kennung_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import hashlib
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
import ziele  # noqa: E402
from backend import main as M  # noqa: E402

# Die Form, die eine echte Anmeldung ins Token schreibt (Register: Backslash)
BENUTZER = M._display_name(ziele.wert("JARVIS_DEV_TESTUSER"))
TOKEN = M.generate_token(BENUTZER)
M._sitzung.flush()
BASIS = "https://127.0.0.1"
# "die Seite selbst steht" (Positivkontrolle am Ende von B)
_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % str(info)[:300]) if info else ""))


def _spki():
    """SPKI-Hash (base64 sha256) des Server-Zertifikats. Chrome cacht bei einem
    Zertifikatsfehler GAR NICHTS – mit --ignore-certificate-errors haette C
    einen Messaufbau gemessen, nicht den Dienst (erster Lauf: 63/63 uebers Netz)."""
    import base64
    import ssl as _ssl
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    pem = _ssl.get_server_certificate(("127.0.0.1", 443))
    spki = x509.load_pem_x509_certificate(pem.encode()).public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(hashlib.sha256(spki).digest()).decode()


PROFIL = tempfile.mkdtemp(prefix="chrome-kennung-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1200,900", f"--ignore-certificate-errors-spki-list={_spki()}",
     "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def aufraeumen():
    try:
        chrome.kill()
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(PROFIL, ignore_errors=True)
    try:
        u, ts, sig = TOKEN.split(":", 2)
        M._sitzung.widerrufe(sig, int(ts))
        M._sitzung.flush()
    except Exception as e:  # noqa: BLE001
        print("  !!   Probe-Sitzung nicht widerrufen: %s" % e)


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
    print("ABBRUCH: kein CDP-Ziel")
    print(chrome.stdout.read(2000) if chrome.poll() is not None else "")
    aufraeumen()
    sys.exit(2)
from websockets.sync.client import connect  # noqa: E402

_id = [0]


def js(sock, ausdruck):
    r = cdp(sock, "Runtime.evaluate", expression=ausdruck, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def warte(sock, ausdruck, frist):
    ende = time.time() + frist
    while time.time() < ende:
        if js(sock, ausdruck):
            return True
        pumpen(sock, 0.3)
    return False



import re  # noqa: E402
import ssl  # noqa: E402

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def holen(pfad):
    with urllib.request.urlopen(BASIS + pfad, context=_ctx, timeout=20) as a:
        return a.status, {k.lower(): v for k, v in a.headers.items()}, a.read()


EREIGNISSE = []


def cdp(sock, methode, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": methode, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=60))
        if d.get("id") == _id[0]:
            return d.get("result", {})
        if "method" in d:
            EREIGNISSE.append(d)


def pumpen(sock, sekunden):
    ende = time.time() + sekunden
    while time.time() < ende:
        try:
            d = json.loads(sock.recv(timeout=max(0.05, ende - time.time())))
        except TimeoutError:
            break
        if "method" in d:
            EREIGNISSE.append(d)


rc = 2
try:
    # ── A + B ──
    print("\nA/B. Ausgelieferte Seiten und Kopfsaetze")
    st, kopf, roh = holen("/chat")
    html = roh.decode("utf-8")
    refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
    mit = [r for r in refs if re.search(r"\?v=[0-9a-f]{16}$", r)]
    check("Positivkontrolle: /chat hat Einbindungen mit Kennung (%d von %d)" % (len(mit), len(refs)),
          len(mit) >= 20, refs[:5])
    check("/chat bleibt no-store", "no-store" in kopf.get("cache-control", ""), kopf.get("cache-control"))
    check("/chat traegt weiter seine CSP",
          any(k.lower().startswith("content-security-policy") for k in kopf), list(kopf)[:12])
    check("Content-Length passt zum umgeschriebenen Inhalt",
          int(kopf.get("content-length", "-1")) == len(roh), (kopf.get("content-length"), len(roh)))
    falsch = []
    for r in mit:
        s2, k2, inhalt = holen(r)
        if hashlib.sha256(inhalt).hexdigest()[:16] != r.rsplit("=", 1)[1] or "immutable" not in k2.get("cache-control", ""):
            falsch.append((r, k2.get("cache-control")))
    check("jede Kennung = Hash des ausgelieferten Inhalts, und nur dort langer Cache",
          not falsch, falsch[:3])
    # B haengt NICHT an A: die Kennung wird hier selbst aus dem Inhalt
    # gerechnet (ohne Umschreiben gaebe es sonst nichts zu pruefen, und die
    # Probe stuerzte ohne Bilanzzeile ab – Gegenprobe 2026-10-13)
    probe = "/static/css/theme.css"
    _, _, inhalt = holen(probe)
    _, k1, _ = holen(probe + "?v=" + hashlib.sha256(inhalt).hexdigest()[:16])
    check("selbst gerechnete Kennung -> langer Cache", "immutable" in k1.get("cache-control", ""),
          k1.get("cache-control"))
    for q, name in (("?v=1", "Hand-Nummer"), ("", "ohne Nummer"), ("?v=0000000000000000", "falsche Kennung")):
        _, k3, _ = holen(probe + q)
        check("%s -> no-cache" % name, "no-cache" in k3.get("cache-control", "")
              and "immutable" not in k3.get("cache-control", ""), k3.get("cache-control"))

    # ── C ──
    # Gemessen ueber die Performance-API (transferSize 0 = aus dem Cache), NICHT
    # ueber CDP-Netzereignisse: mit Network.enable umging Chrome hier den Cache
    # vollstaendig (erster Lauf: 63/63 uebers Netz bei korrektem Kopfsatz) – die
    # Sonde haette den Messaufbau gemessen, nicht den Dienst.
    print("\nC. Chrome: zweiter Besuch ohne Netzweg fuer Dateien mit Kennung")
    PERF = ("JSON.stringify(performance.getEntriesByType('resource')"
            ".filter(function(e){return /\\/static\\/[^?]+\\?v=[0-9a-f]{16}$/.test(e.name);})"
            ".map(function(e){return [e.name.split('/').pop(), e.transferSize];}))")
    with connect(ws_url, max_size=80 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        cdp(sock, "Page.navigate", url=BASIS + "/api/health")
        pumpen(sock, 1.5)
        js(sock, "localStorage.setItem('jarvis_token'," + json.dumps(TOKEN)
           + ");localStorage.setItem('jarvis_lang','de');true")
        for seite in ("/portal", "/chat", "/settings"):
            cdp(sock, "Page.navigate", url=BASIS + seite)
            pumpen(sock, 5)
            erst = json.loads(js(sock, PERF) or "[]")
            cdp(sock, "Page.navigate", url=BASIS + "/api/health")
            pumpen(sock, 1)
            cdp(sock, "Page.navigate", url=BASIS + seite)
            pumpen(sock, 5)
            zweit = json.loads(js(sock, PERF) or "[]")
            netz1 = [n for n, g in erst if g > 0]
            netz2 = [n for n, g in zweit if g > 0]
            check("%s erster Besuch: neue Dateien kommen uebers Netz (%d von %d) – Positivkontrolle"
                  % (seite, len(netz1), len(erst)), len(erst) >= 10 and len(netz1) > 0, erst[:3])
            check("%s zweiter Besuch: keine Datei mit Kennung uebers Netz (%d von %d)"
                  % (seite, len(netz2), len(zweit)), len(zweit) >= 10 and not netz2, netz2[:5])
    rc = 0 if _fail == 0 else 1
except SystemExit as e:
    rc = e.code if isinstance(e.code, int) else 2
finally:
    aufraeumen()

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(rc)
