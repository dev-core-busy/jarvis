#!/usr/bin/env python3
"""Der Einstellungs-Reiter „Feedback" gegen die ECHTE ausgelieferte Seite.

⚠ WARUM ES DIESE PROBE GIBT (2026-09-14). Die optische Abnahme
(`live_feedback_admin_ui_dev.py`) baut sich ihre Seite selbst und laedt
`feedback_admin.js` dabei SELBST – sie konnte deshalb strukturell nicht sehen,
dass `settings.html` das Skript gar nicht einband. `window.FeedbackAdmin` waere
im Betrieb `undefined` gewesen, `app.js` faengt das mit `if (window.FeedbackAdmin)`
ab, und der Reiter waere STILL leer geblieben.

Gemessen wird deshalb die AUSGELIEFERTE Seite: echtes `/settings`, echter
Reiter-Klick, echte Endpunkte. Ein Wachtposten im Backend prueft die Einbindung
zusaetzlich als Regel – hier geht es um die Kette bis zum gezeichneten Eintrag.

⚠ DER VORGEFUNDENE ZUSTAND WIRD GEMERKT UND EXAKT WIEDERHERGESTELLT (Register;
`test_messung_zustand.py` prueft das als Regel).

Aufruf auf DEV: cd /opt/jarvis && ./venv/bin/python tests/live_feedback_reiter_echt_dev.py
"""
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
os.environ.setdefault("HOME", "/home/jarvis")

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


import requests                                                     # noqa: E402
requests.packages.urllib3.disable_warnings()                        # noqa: E402
from backend import main as M                                       # noqa: E402
from backend.config import config                                   # noqa: E402

BASIS = "https://127.0.0.1"
TOKEN = M.generate_token("jarvis")
S = requests.Session()
S.verify = False
S.headers["Authorization"] = "Bearer " + TOKEN

# ── Vorgefundenen Zustand merken ────────────────────────────────────────────
_vor = config.get_skill_states()
VOR_SKILL = (_vor.get("feedback") or {}).get("enabled")
VOR_USERS = config.get_setting("ad_knowledge_editors", "")
VOR_GROUP = config.get_setting("ad_knowledge_editors_group", "")
print("vorgefunden: skill=%r users=%r" % (VOR_SKILL, VOR_USERS))

PROFIL = tempfile.mkdtemp(prefix="fbreiter-", dir=str(Path.home()))
os.chmod(PROFIL, 0o700)
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     "--remote-debugging-port=%d" % PORT, "--remote-allow-origins=*",
     "--user-data-dir=%s" % PROFIL, "--window-size=1400,1000",
     "--ignore-certificate-errors", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

FORM_ID = [None]



def _neustart_und_melden(sitzung, basis):
    """Den Dienst neu starten, damit sein RAM-Stand den Eintrag nicht zurueckschreibt.

    ⚠ GEMESSEN WIRD DER DIENST, NICHT DIE DATEI. `config.get_skill_states()` im
    Messprozess liest die gerade bereinigte Datei und meldet brav `None` –
    waehrend der laufende Dienst den Eintrag weiter im RAM haelt und beim
    naechsten Anlass zurueckschreibt (Register: ein Poll auf eine zweite Instanz
    derselben Datei misst nicht den Prozess, der schreibt).

    ⚠ ALS DIENSTBENUTZER SCHEITERT DER NEUSTART – das ist richtig so, und die
    Probe BEHAUPTET dann nichts, sondern sagt, was zurueckbleibt.
    """
    r = subprocess.run(["systemctl", "restart", "jarvis.service"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print("  ⚠ RUECKSTAND: der Dienst liess sich nicht neu starten (%s). "
              "Es bleibt ein Skill-Eintrag {'enabled': False} zurueck – "
              "vorgefunden war GAR KEINER. Wirkung ist dieselbe (Skill aus), "
              "der Zustand aber nicht identisch. Als root aufraeumen:\n"
              "    ./venv/bin/python -c \"from backend.config import config; "
              "config.remove_skill_state('feedback')\" "
              "&& systemctl restart jarvis.service"
              % (r.stderr or r.returncode).strip()[:80])
        return
    time.sleep(10)
    rest = None
    if sitzung is not None and basis:
        try:
            sk = sitzung.get(basis + "/api/skills", timeout=30).json()
            rest = [x for x in (sk.get("skills") or []) if x.get("name") == "feedback"]
        except Exception:                                           # noqa: BLE001
            rest = None
    print("  Dienst neu gestartet; Skill-Eintrag: %s"
          % ("weg" if config.get_skill_states().get("feedback") is None
             else "steht noch"))

def aufraeumen():
    chrome.kill()
    shutil.rmtree(PROFIL, ignore_errors=True)
    try:
        if FORM_ID[0]:
            S.delete(BASIS + "/api/feedback/admin/formulare/" + FORM_ID[0], timeout=20)
        # Vorgefunden war KEINE Datei – eine leere darf nicht zurueckbleiben.
        _f = Path("/opt/jarvis/data/feedback_formulare.json")
        if _f.exists() and not (json.loads(_f.read_text(encoding="utf-8"))
                                .get("formulare") or []):
            _f.unlink()
        config.save_setting("ad_knowledge_editors", VOR_USERS)
        config.save_setting("ad_knowledge_editors_group", VOR_GROUP)
        # Der Skill wird ueber den ECHTEN Endpunkt geschaltet – `enable_skill()`
        # im Messprozess erreicht den Dienst nicht (Skill-Zustaende im RAM).
        if VOR_SKILL is True:
            S.post(BASIS + "/api/skills/feedback/enable", timeout=90)
        elif VOR_SKILL is False:
            S.post(BASIS + "/api/skills/feedback/disable", timeout=90)
        else:
            # ⚠ ES GAB GAR KEINEN EINTRAG – dann darf auch keiner zurueckbleiben,
            # und das ist aufwendiger als es aussieht: der DIENST haelt die
            # Skill-Zustaende im RAM und schreibt sie beim naechsten Anlass
            # zurueck. Ein `remove_skill_state()` aus dem Messprozess allein
            # hinterlaesst deshalb `{'enabled': False, …}` – gemessen, nicht
            # vermutet. Also: abschalten, Eintrag entfernen, Dienst neu starten,
            # UND nachsehen.
            S.post(BASIS + "/api/skills/feedback/disable", timeout=90)
            time.sleep(1)
            if "feedback" in config.get_skill_states():
                config.remove_skill_state("feedback")
            _neustart_und_melden(S, BASIS)
        print("\nFreigabe wiederhergestellt: users=%r group=%r"
              % (config.get_setting("ad_knowledge_editors", ""),
                 config.get_setting("ad_knowledge_editors_group", "")))
        # ⚠ Ueber den Skill-Eintrag sagt diese Stelle bewusst NICHTS – den
        # kennt nur der DIENST; `_neustart_und_melden` berichtet ihn.
    except Exception as e:                                          # noqa: BLE001
        print("Aufraeumen unvollstaendig: %s" % e)


def ende(code):
    aufraeumen()
    sys.exit(code)


def ziel_ws():
    for _ in range(60):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % PORT,
                                        timeout=2) as a:
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:                                           # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


print("=" * 74)
print("Feedback-Reiter gegen die ECHTE /settings")
print("=" * 74)

# ── Lage herstellen: Skill an, ein Formular anlegen ─────────────────────────
r = S.post(BASIS + "/api/skills/feedback/enable", timeout=90)
if r.status_code != 200:
    print("ABBRUCH: Skill liess sich nicht einschalten (%s)" % r.status_code)
    ende(2)
time.sleep(3)
r = S.post(BASIS + "/api/feedback/admin/formulare", timeout=30, json={
    "titel": "Reiter-Probe", "beschreibung": "nur fuer diesen Lauf",
    "spalten": [{"name": "Anmerkung", "typ": "text"},
                {"name": "Bewertung", "typ": "sterne"}], "aktiv": True})
if r.status_code != 200:
    print("ABBRUCH: Formular nicht angelegt (%s)" % r.status_code)
    ende(2)
FORM_ID[0] = (r.json() or {}).get("formular", {}).get("id")
print("Probe-Formular: %s" % FORM_ID[0])

ws = ziel_ws()
if not ws:
    print("ABBRUCH: kein CDP-Ziel")
    ende(2)
try:
    from websockets.sync.client import connect
except Exception:                                                   # noqa: BLE001
    print("ABBRUCH: python-websockets fehlt im venv.")
    ende(2)

_id = [0]


def cdp(sock, m, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": m, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=40))
        if d.get("id") == _id[0]:
            return d.get("result", {})


def js(sock, a):
    r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True,
            awaitPromise=True)
    return (r.get("result") or {}).get("value")


with connect(ws, open_timeout=20, max_size=40_000_000) as sock:
    cdp(sock, "Page.enable")
    cdp(sock, "Runtime.enable")
    # Das Token gehoert VOR das erste Skript der Seite – sonst leitet sie um,
    # und jede Messung darunter waere trivial wahr (Register).
    cdp(sock, "Page.addScriptToEvaluateOnNewDocument",
        source="try{localStorage.setItem('jarvis_token','%s');}catch(e){}"
               "window.__fehler='';window.addEventListener('error',function(e){"
               "window.__fehler+=(e.message||'')+' | ';});" % TOKEN)
    cdp(sock, "Page.navigate", url=BASIS + "/settings")
    time.sleep(6)

    # ── Positivkontrolle: sind wir ueberhaupt auf /settings? ────────────────
    pfad = js(sock, "location.pathname")
    if pfad != "/settings":
        print("  ABBRUCH: gelandet auf %r statt /settings – die Anmeldung hat "
              "nicht getragen, jede Messung darunter waere trivial wahr." % pfad)
        ende(2)
    check("die echte Seite /settings ist geladen (Positivkontrolle)", True)

    fehler = js(sock, "window.__fehler || ''")
    check("keine JS-Fehler beim Laden", not fehler, fehler or "")

    # ── DIE EIGENTLICHE PRUEFUNG ────────────────────────────────────────────
    check("⚠ `feedback_admin.js` ist wirklich geladen (window.FeedbackAdmin)",
          js(sock, "typeof window.FeedbackAdmin") == "object",
          js(sock, "typeof window.FeedbackAdmin"))

    sichtbar = js(sock, "(function(){var b=document.getElementById("
                        "'settings-tab-btn-feedback');"
                        "return b?getComputedStyle(b).display:'(fehlt)';})()")
    check("der Reiter-Knopf ist bei aktivem Skill sichtbar",
          sichtbar not in ("none", "(fehlt)"), str(sichtbar))

    js(sock, "document.getElementById('settings-tab-btn-feedback').click()")
    time.sleep(3)

    check("das Panel ist offen",
          js(sock, "getComputedStyle(document.getElementById("
                   "'settings-tab-feedback')).display") != "none")

    n = js(sock, "document.querySelectorAll('#fbadm-liste .fb-card').length")
    check("⚠ die Formularliste ist GEZEICHNET (kein leerer Reiter)", (n or 0) >= 1,
          "%s Karten" % n)

    titel = js(sock, "(function(){var e=document.querySelector("
                     "'#fbadm-liste .fb-card-name');return e?e.textContent:'';})()")
    check("das angelegte Formular steht darin", "Reiter-Probe" in (titel or ""),
          repr(titel))

    breite = js(sock, "(function(){var k=document.querySelector("
                      "'#fbadm-liste .fb-card');"
                      "return k?Math.round(k.getBoundingClientRect().width):0;})()")
    check("die Karte ist wirklich gemalt (%spx, Positivkontrolle)" % breite,
          (breite or 0) >= 200, str(breite))

    fehler2 = js(sock, "window.__fehler || ''")
    check("kein JS-Fehler nach dem Reiterwechsel", not fehler2, fehler2 or "")

print("\n" + "=" * 74)
print("Ergebnis: %d OK, %d FAIL" % (_ok, _fail))
print("=" * 74)
ende(0 if _fail == 0 else 1)
