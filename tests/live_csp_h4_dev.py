#!/usr/bin/env python3
"""Live auf DEV (BSI H4): traegt jede Seite die CSP, und verstoesst eine Seite beim Laden?

Laeuft AUF DEV (``/opt/jarvis``) gegen den laufenden Dienst ueber HTTPS.

  [A] Kopfzeilen: jede HTML-Seite traegt die Richtlinie im eingestellten Modus,
      noVNC nicht, JSON-Antworten nicht.
  [B] Melde-Endpunkt: ein gestellter Bericht wird angenommen (204) und ist
      ueber /api/security/csp (Admin) lesbar – ohne Token in der URL.
  [C] Echter Browser (headless Chrome ueber CDP): jede Seite angemeldet laden
      und JEDEN ``securitypolicyviolation`` mitschreiben. Im Modus "melden"
      blockiert der Browser nichts, meldet aber genau das, was beim Umschalten
      auf "erzwingen" brechen wuerde. Erwartet: null Verstoesse.

  [D] nur mit ``--freigabe-nachstellen``: Seiten, die in [C] umgeleitet wurden
      (Bereich fuer das Testkonto nicht freigegeben), ein zweites Mal laden –
      im Testbrowser antwortet ``/api/me`` mit allen Freigaben, und jede
      API-Antwort 401/403 wird zu 503 (sonst springt die Seite beim ersten
      Datenabruf zurueck aufs Portal). Gemessen wird damit die Oberflaeche
      samt Fehlerzustaenden, NICHT ihr Verhalten mit echten Daten. Am Server
      aendert sich nichts: keine Freigabe, kein Benutzerrecht.

Veraendert nichts ausser einer Zeile in data/logs/csp_berichte.jsonl (der
gestellte Bericht aus [B], als solcher erkennbar).

Lauf (fuer "erzwingen" vorher den Modus umschalten, danach zuruecksetzen):
  bash /opt/jarvis/deploy/als_dienst.sh /opt/jarvis/venv/bin/python \\
       tests/live_csp_h4_dev.py [--freigabe-nachstellen]

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import base64
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402  (Testkonto aus .env, nie aus dem Repo)

BASIS = "https://127.0.0.1"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

SEITEN = ["/", "/chat", "/settings", "/portal", "/wissen", "/api", "/support-api",
          "/supportagent", "/sap", "/vemas", "/excel", "/email", "/tracks", "/claude",
          "/support", "/userchat", "/jira-addon", "/confluence-addon", "/ai-mouse",
          "/feedback", "/addin/taskpane.html", "/excel-addin/taskpane.html"]

NACHSTELLEN = "--freigabe-nachstellen" in sys.argv[1:]

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def roh(pfad, token=None, methode="GET", rumpf=None, typ="application/json"):
    r = urllib.request.Request(BASIS + pfad, data=rumpf, method=methode)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if rumpf is not None:
        r.add_header("Content-Type", typ)
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=30) as a:
            return a.status, dict(a.headers), a.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


from backend import main as M  # noqa: E402

BENUTZER = os.environ.get("CSP_TESTUSER") or "jarvis"     # lokaler Admin auf DEV
tok = M.generate_token(BENUTZER)

st, _, k = roh("/api/security/csp", tok)
if st != 200:
    print("ABBRUCH (Exit 2): /api/security/csp -> %s %s (Dienst neu gestartet? Admin-Token?)"
          % (st, k[:200]))
    sys.exit(2)
stand = json.loads(k)
MODUS = stand.get("modus")
print("Modus auf DEV: %s" % MODUS)
NAME = {"melden": "content-security-policy-report-only",
        "erzwingen": "content-security-policy"}.get(MODUS)

# ─── [A] Kopfzeilen ──────────────────────────────────────────────────────────
print("[A] Kopfzeilen")
check(NAME is not None, "Modus ist melden oder erzwingen (Positivkontrolle)", str(MODUS))
for pfad in SEITEN:
    st, h, _ = roh(pfad)
    h = {k.lower(): v for k, v in h.items()}
    if st == 404:
        print("  --   %s nicht aktiv (404) – uebersprungen" % pfad)
        continue
    wert = h.get(NAME or "-", "")
    check(st == 200 and "script-src 'self'" in wert and "unsafe-inline" not in wert.split("script-src", 1)[1].split(";")[0],
          "%s: %s mit script-src ohne unsafe-inline" % (pfad, NAME), "%s %r" % (st, wert[:120]))
st, h, _ = roh("/novnc/vnc.html")
h = {k.lower(): v for k, v in h.items()}
check(st != 200 or not any(k.startswith("content-security-policy") for k in h),
      "noVNC ohne Richtlinie", str(st))
st, h, _ = roh("/api/security/csp", tok)
h = {k.lower(): v for k, v in h.items()}
check(not any(k.startswith("content-security-policy") for k in h), "JSON-Antwort ohne Richtlinie")

# ─── [B] Melde-Endpunkt ──────────────────────────────────────────────────────
print("[B] Melde-Endpunkt")
marke = "live-probe-%d" % int(time.time())
bericht = {"csp-report": {"document-uri": "https://probe/%s?token=GEHEIM" % marke,
                          "violated-directive": "script-src-attr", "blocked-uri": "inline"}}
st, _, _ = roh("/api/csp-report", None, "POST", json.dumps(bericht).encode(), "application/csp-report")
check(st == 204, "Bericht ohne Anmeldung angenommen (204)", str(st))
st, _, k = roh("/api/security/csp", tok)
b = json.loads(k).get("berichte", []) if st == 200 else []
treffer = [x for x in b if marke in x.get("seite", "")]
check(len(treffer) == 1, "Bericht in /api/security/csp sichtbar", str(b[:2]))
check(treffer and "GEHEIM" not in json.dumps(treffer), "Token aus der URL entfernt")
st, _, _ = roh("/api/security/csp")
check(st == 401, "Admin-Endpunkt ohne Token -> 401", str(st))

# ─── [C] Echter Browser ──────────────────────────────────────────────────────
print("[C] Browser: Verstoesse beim Laden")
try:
    from websockets.sync.client import connect
except Exception:  # noqa: BLE001
    print("ABBRUCH (Exit 2): python-websockets fehlt")
    sys.exit(2)

PROFIL = tempfile.mkdtemp(prefix="chrome-csp-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1400,900",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def ende(code):
    chrome.kill()
    shutil.rmtree(PROFIL, ignore_errors=True)
    print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
    sys.exit(code)


def ziel_ws():
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


ws = ziel_ws()
if not ws:
    print("ABBRUCH (Exit 2): kein CDP-Ziel")
    ende(2)
_id = [0]


def cdp(sock, m, **p):
    _id[0] += 1
    meine = _id[0]
    sock.send(json.dumps({"id": meine, "method": m, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=60))
        if d.get("method") == "Fetch.requestPaused":
            _abgefangen(sock, d["params"])
            continue
        if d.get("id") == meine:
            return d.get("result", {})


# [D] Freigabe nachstellen: nur im Testbrowser, nur waehrend Fetch aktiv ist.
ME_ALLE = {"username": BENUTZER, "is_admin": True,
           "permissions": {k: True for k in ("sap", "vemas", "email", "tracks", "jira_assist",
                                             "confluence", "ai_mouse", "excel", "support")}}
ZAEHLER = {"me": 0, "verweigert": 0}


def _senden(sock, m, **p):
    """Antwort auf ein abgefangenes Ereignis – ohne auf das Ergebnis zu warten
    (cdp() wartet auf SEINE Kennung und darf hier nicht verschachtelt laufen)."""
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": m, "params": p}))


def _abgefangen(sock, ev):
    rid, url = ev["requestId"], ev["request"]["url"]
    pfad = url.split("://", 1)[-1].split("/", 1)[-1].split("?")[0]
    if pfad == "api/me":
        ZAEHLER["me"] += 1
        body, code = json.dumps(ME_ALLE).encode(), 200
    elif ev.get("responseStatusCode") in (401, 403):
        ZAEHLER["verweigert"] += 1
        body, code = b'{"detail": "csp-probe"}', 503
    else:
        _senden(sock, "Fetch.continueRequest", requestId=rid)   # Antwortphase: unveraendert durch
        return
    _senden(sock, "Fetch.fulfillRequest", requestId=rid, responseCode=code,
            responseHeaders=[{"name": "Content-Type", "value": "application/json"}],
            body=base64.b64encode(body).decode())


def warte(sock, sek):
    """Ereignisse abarbeiten statt blind schlafen – ein abgefangener Abruf, den
    niemand beantwortet, haengt sonst bis zum Timeout."""
    bis = time.time() + sek
    while time.time() < bis:
        try:
            d = json.loads(sock.recv(timeout=max(0.05, bis - time.time())))
        except TimeoutError:
            break
        if d.get("method") == "Fetch.requestPaused":
            _abgefangen(sock, d["params"])


def js(sock, a):
    r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


# Vor jedem Dokument: Token setzen und Verstoesse in window.__csp sammeln.
VORLAUF = """
(function(){
  try { localStorage.setItem('jarvis_token', %s); localStorage.setItem('jarvis_user', %s);
        localStorage.setItem('jarvis_chat_token', %s); localStorage.setItem('jarvis_chat_user', %s); } catch(e) {}
  window.__csp = [];
  document.addEventListener('securitypolicyviolation', function(e){
    window.__csp.push({d: e.effectiveDirective, b: e.blockedURI, q: (e.sourceFile||'').split('?')[0],
                       z: e.lineNumber, s: (e.sample||'').slice(0,60)});
  }, true);
})();
""" % (json.dumps(tok), json.dumps(BENUTZER), json.dumps(tok), json.dumps(BENUTZER))

with connect(ws, open_timeout=20, max_size=60_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    cdp(sock, "Page.addScriptToEvaluateOnNewDocument", source=VORLAUF)
    # Positivkontrolle der Messmethode: ein Inline-Skript auf einer Seite MUSS gemeldet werden
    cdp(sock, "Page.navigate", url=BASIS + "/chat")
    time.sleep(4)
    js(sock, "var s=document.createElement('script');s.textContent='window.__probe=1';document.body.appendChild(s);")
    time.sleep(0.5)
    probe = js(sock, "JSON.stringify(window.__csp)") or "[]"
    if not any(v.get("d", "").startswith("script-src") for v in json.loads(probe)):
        check(False, "Positivkontrolle: eingeschleustes Inline-Skript wird gemeldet", probe)
        print("ABBRUCH (Exit 2): Messmethode sieht keine Verstoesse")
        ende(2)
    check(True, "Positivkontrolle: eingeschleustes Inline-Skript wird gemeldet")

    def messen(pfad, zusatz=""):
        """Seite laden und Verstoesse pruefen. Rueckgabe False = umgeleitet."""
        cdp(sock, "Page.navigate", url=BASIS + pfad)
        warte(sock, 6)
        titel = js(sock, "document.title") or ""
        ort = js(sock, "location.pathname") or ""
        if ort.rstrip("/") != pfad.rstrip("/"):
            # Umleitung (Bereich fuer das Testkonto nicht aktiv) – gemessen waere
            # die Zielseite, nicht diese. Ehrlich als nicht gemessen ausweisen.
            print("  --   %s%s: umgeleitet nach %s – NICHT gemessen" % (pfad, zusatz, ort))
            return False
        roh_v = js(sock, "JSON.stringify(window.__csp||null)")
        if roh_v in (None, "null"):
            print("  --   %s%s: Messung nicht moeglich (kein Dokument)" % (pfad, zusatz))
            return True
        v = json.loads(roh_v)
        # Add-ins: office.js laedt ausserhalb von Office nichts Weiteres – nur unsere Verstoesse zaehlen
        check(not v, "%s%s (%s): keine Verstoesse" % (pfad, zusatz, titel[:30]),
              json.dumps(v[:6], ensure_ascii=False))
        return True

    umgeleitet = [p for p in SEITEN if not messen(p)]

    # ─── [D] Umgeleitete Seiten mit nachgestellter Freigabe ─────────────────
    # "/" leitet IMMER weiter (Startseite -> Portal), das ist keine Freigabefrage.
    umgeleitet = [p for p in umgeleitet if p != "/"]
    if umgeleitet and not NACHSTELLEN:
        print("[D] %d Seite(n) nicht gemessen (%s) – mit --freigabe-nachstellen messbar"
              % (len(umgeleitet), ", ".join(umgeleitet)))
    elif umgeleitet:
        print("[D] Freigabe im Testbrowser nachgestellt: %s" % ", ".join(umgeleitet))
        cdp(sock, "Fetch.enable", patterns=[{"urlPattern": "*/api/*", "requestStage": "Response"}])
        # Positivkontrolle: ohne beantwortetes /api/me ist jede Pruefung darunter
        # die Messung einer Umleitung, nicht der Seite.
        vorher_me = ZAEHLER["me"]
        noch_umgeleitet = [p for p in umgeleitet if not messen(p, " [Freigabe nachgestellt]")]
        cdp(sock, "Fetch.disable")
        check(ZAEHLER["me"] > vorher_me, "Positivkontrolle: /api/me im Testbrowser beantwortet",
              str(ZAEHLER))
        check(not noch_umgeleitet, "jede umgeleitete Seite mit nachgestellter Freigabe gemessen",
              ", ".join(noch_umgeleitet))
        print("  abgefangen: /api/me %d×, verweigerte Datenabrufe -> 503 %d×"
              % (ZAEHLER["me"], ZAEHLER["verweigert"]))

ende(0 if _fail == 0 else 1)
