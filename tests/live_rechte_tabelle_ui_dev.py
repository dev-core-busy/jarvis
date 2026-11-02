#!/usr/bin/env python3
"""Durchstich auf DEV: Berechtigungen OHNE "alte Benutzerberechtigungen" (2026-11-02).

Der Container mit den Einzellisten je Bereich ist entfallen; den Bestand haelt
seitdem settings_ad.js im Speicher (window.AdRechte), die Tabelle
"Berechtigungen zuweisen" ist der einzige Weg. Die jsdom-Waechter messen das
gegen Attrappen - hier laeuft alles echt (ausgelieferte Seite, echter Dienst,
echter Bestand):

  0. Positivkontrolle: /settings laedt, der Bestand gilt als geladen
  A. der Bestand im Browser stimmt Feld fuer Feld mit /api/auth/ad_status
  B. keine alten Felder/Container mehr; Tabelle hat Zeilen; die Skill-Spalten
     folgen GENAU den eingeschalteten Skills auf DEV
  C. RUNDLAUF: "Speichern" an der Verbindung laesst JEDE Freigabe unveraendert
     (der gefaehrlichste Fehler dieses Umbaus waere ein Speichern, das Listen
     leert). Weicht etwas ab, wird der Vorzustand zurueckgeschrieben.
  D. der Firewall-Container steht im Abschnitt
  E. der zuletzt benutzte Reiter steht nach dem Neuladen wieder offen
  Bild: ~/.jarvis-abnahme/rechte_tabelle.png

Laeuft AUF DEV ueber den Hauptschluessel (das Token stellt nur der Dienst aus):
    bash /opt/jarvis/deploy/als_dienst.sh /opt/jarvis/venv/bin/python \\
         tests/live_rechte_tabelle_ui_dev.py
Zustand: die Probe-Sitzung wird widerrufen, das Chrome-Profil geloescht; die
Freigaben werden vorher gesichert und bei Abweichung wiederhergestellt.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import base64
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
from backend import main as M  # noqa: E402

ROOT = Path("/opt/jarvis")
BENUTZER = "jarvis"   # lokaler Administrator: /settings und ad_status verlangen ihn
TOKEN = M.generate_token(BENUTZER)
M._sitzung.flush()
BILDER = Path.home() / ".jarvis-abnahme"
BILDER.mkdir(mode=0o700, exist_ok=True)

# Zuordnung aus der AUSGELIEFERTEN settings_ad.js lesen, nicht abtippen
_SAD = (ROOT / "frontend/js/settings_ad.js").read_text(encoding="utf-8")
FREIGABEN = re.findall(
    r"\{\s*feld:\s*'([^']+)',\s*lesen:\s*'([^']+)',\s*schreiben:\s*'([^']+)'\s*\}", _SAD)
# Skill-Spalten aus rechte_matrix.js: sub -> Skill-Verzeichnis (wie app.js)
SKILL_DIR = {"sap": "sap", "vemas": "vemas", "email": "email", "tracks": "short-tracks",
             "jiraassist": "jira", "aimouse": "ai_mouse", "claudesub": "claude_subagent",
             "excel": "excel-addin"}

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


if len(FREIGABEN) != 24:
    print("ABBRUCH: FREIGABEN aus settings_ad.js nicht lesbar (%d statt 24)" % len(FREIGABEN))
    sys.exit(2)

s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
PROFIL = tempfile.mkdtemp(prefix="chrome-rechte-", dir=str(Path.home()))
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1400,1000", "--ignore-certificate-errors",
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


def cdp(sock, methode, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": methode, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=60))
        if d.get("id") == _id[0]:
            return d.get("result", {})


def js(sock, ausdruck):
    r = cdp(sock, "Runtime.evaluate", expression=ausdruck, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


def warte(sock, ausdruck, frist):
    ende = time.time() + frist
    while time.time() < ende:
        if js(sock, ausdruck):
            return True
        time.sleep(0.5)
    return False


# Abruf IM Browser: dieselbe Sitzung (Cookie + CSRF) wie die Seite selbst
def api(sock, pfad, methode="GET", koerper=None):
    a = ("fetch(%s,{method:%s,headers:{'Content-Type':'application/json',"
         "'Authorization':'Bearer '+window.JarvisSitzung.token()}%s})"
         ".then(function(r){return r.json().then(function(j){return {s:r.status,j:j};});})"
         % (json.dumps(pfad), json.dumps(methode),
            (",body:" + json.dumps(json.dumps(koerper))) if koerper is not None else ""))
    return js(sock, a) or {}


def bestand(st):
    return {f[0]: (st.get(f[1]) or "") for f in FREIGABEN}


def zurueckschreiben(sock, vorher):
    koerper = {f[2]: vorher[f[0]] for f in FREIGABEN}
    r = api(sock, "/api/settings", "POST", koerper)
    print("  !!   Vorzustand zurueckgeschrieben: HTTP %s" % r.get("s"))


def lade_settings(sock):
    cdp(sock, "Page.navigate", url="https://127.0.0.1/settings")
    return warte(sock, "!!(window.AdRechte && window._adGeladen && document.getElementById('rmx-tabwrap'))", 40)


rc = 2
vorher = None
try:
    with connect(ws_url, max_size=80 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        cdp(sock, "Page.navigate", url="https://127.0.0.1/api/health")
        time.sleep(2)
        js(sock, "localStorage.clear();localStorage.setItem('jarvis_token'," + json.dumps(TOKEN)
           + ");localStorage.setItem('jarvis_user'," + json.dumps(BENUTZER)
           + ");localStorage.setItem('jarvis_lang','de');true")

        print("\n0. Positivkontrolle")
        if not lade_settings(sock):
            print("ABBRUCH: /settings laedt nicht oder der Bestand gilt nicht als geladen")
            sys.exit(2)
        st = api(sock, "/api/auth/ad_status")
        if st.get("s") != 200:
            print("ABBRUCH: ad_status antwortet %s" % st.get("s"))
            sys.exit(2)
        vorher = bestand(st["j"])
        check("Seite geladen, Bestand geladen, ad_status 200", True)
        check("der Bestand ist nicht leer (sonst waere der Rundlauf trivial)",
              any(vorher.values()), "alle 24 Freigaben leer")

        print("\nA. Bestand im Browser = Server")
        im_browser = js(sock, "(function(){var o={};" + "".join(
            "o[%s]=window.AdRechte.lesen(%s);" % (json.dumps(f[0]), json.dumps(f[0])) for f in FREIGABEN)
            + "return o;})()") or {}
        abw = [k for k in vorher if (im_browser.get(k) or "") != vorher[k]]
        check("alle 24 Freigaben stimmen mit ad_status ueberein", not abw, ", ".join(abw))

        print("\nB. Oberflaeche")
        reste = js(sock, "(function(){var ids=" + json.dumps([f[0] for f in FREIGABEN]) +
                   ";return ids.filter(function(i){return document.getElementById(i);})"
                   ".concat(document.querySelector('[data-sub=\"altrechte\"]')?['altrechte']:[]);})()")
        check("keine alten Felder und kein alter Container im DOM", reste == [], str(reste))
        zeilen = js(sock, "document.querySelectorAll('#rmx-tabwrap tbody tr .rmx-cb').length") or 0
        check("die Tabelle zeigt Kaestchen (Zeilen aus dem echten Bestand)", zeilen > 0, str(zeilen))
        # Antwortform wie in app.js::_skillsOnce: {skills: [...]} (oder die Liste
        # selbst). Erste Fassung las nur die Liste und hielt damit JEDEN Skill
        # fuer aus - sieben FAIL, die eine falsche Sonde waren.
        sj = api(sock, "/api/skills").get("j")
        skills = (sj.get("skills") if isinstance(sj, dict) else sj) or []
        if not skills:
            print("ABBRUCH: /api/skills liefert keine Skills - Spaltenvergleich nicht messbar")
            sys.exit(2)
        an = {s.get("dir_name") for s in skills if isinstance(s, dict) and s.get("enabled")}
        spalten = set(js(sock, "[...document.querySelectorAll('#rmx-tabwrap thead .rmx-sort')]"
                               ".map(function(b){return b.getAttribute('data-sort');})") or [])
        for fest in ("login", "knowledge", "internet", "admins"):
            check("Spalte '%s' ist da" % fest, fest in spalten)
        for sub, d in SKILL_DIR.items():
            check("Spalte '%s' %s (Skill %s %s)" % (sub, "da" if d in an else "fehlt", d, "an" if d in an else "aus"),
                  (sub in spalten) == (d in an), "Spalten: %s" % sorted(spalten))

        print("\nC. Rundlauf: Speichern an der Verbindung")
        js(sock, "window.__gesendet=null;(function(){var f=window.fetch;window.fetch=function(u,o){"
                 "if(String(u).split('?')[0]==='/api/settings'&&o&&o.body)window.__gesendet=JSON.parse(o.body);"
                 "return f.apply(this,arguments);};})();true")
        js(sock, "document.querySelector('[data-klick=\"ad-speichern\"]').click();true")
        gespeichert = warte(sock, "window.__gesendet!==null && [...document.querySelectorAll('.ad-save-status')]"
                                  ".some(function(e){return /gespeichert|saved/i.test(e.textContent);})", 30)
        check("der Speichervorgang lief und meldet Erfolg", gespeichert,
              js(sock, "[...document.querySelectorAll('.ad-save-status')].map(function(e){return e.textContent;}).join('|')"))
        gesendet = js(sock, "window.__gesendet") or {}
        fehlt = [f[2] for f in FREIGABEN if f[2] not in gesendet]
        check("alle 24 Freigaben stehen im Koerper", not fehlt, ", ".join(fehlt))
        nachher = bestand((api(sock, "/api/auth/ad_status").get("j")) or {})
        abw = [k for k in vorher if nachher.get(k) != vorher[k]]
        check("KEINE Freigabe hat sich durch das Speichern veraendert", not abw, ", ".join(abw))
        if abw:
            zurueckschreiben(sock, vorher)

        print("\nD. Firewall-Container")
        fw = js(sock, "(function(){var d=document.querySelector('details.sec-sub[data-sub=\"egress\"]');"
                      "return !!(d && d.querySelector('#sec-egress-setup') && "
                      "d.closest('#sec-sect-ad-body'));})()")
        check("Internet-Sperre (Firewall) steht als eigener Container im Abschnitt", fw)

        print("\nE. Zuletzt benutzter Reiter")
        js(sock, "document.querySelector('.settings-tab-btn[data-settings-tab=\"security\"]').click();true")
        lade_settings(sock)
        time.sleep(2)
        aktiv = js(sock, "[...document.querySelectorAll('.settings-tab-btn.active')].map(function(b){return b.dataset.settingsTab;})")
        check("nach dem Neuladen steht 'Sicherheit' offen", aktiv == ["security"], str(aktiv))

        # Bild des Abschnitts (aufgeklappt)
        js(sock, "(function(){var h=document.getElementById('sec-sect-ad-hdr');"
                 "if(h&&h.classList.contains('is-collapsed'))h.click();"
                 "var t=document.getElementById('rmx-titel');if(t)window.scrollTo(0,t.getBoundingClientRect().top+window.scrollY-120);})();true")
        time.sleep(1.5)
        b = cdp(sock, "Page.captureScreenshot", format="png")
        (BILDER / "rechte_tabelle.png").write_bytes(base64.b64decode(b.get("data", "")))
        print("  Bild: %s" % (BILDER / "rechte_tabelle.png"))

        rc = 0 if _fail == 0 else 1
except SystemExit as e:
    rc = e.code if isinstance(e.code, int) else 2
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: %r" % e)
    if vorher is not None:
        print("  (Bestand vorher war gesichert; bitte ad_status gegen den Vorzustand pruefen)")
    rc = 2
finally:
    aufraeumen()
print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(rc)
