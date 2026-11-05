#!/usr/bin/env python3
"""Live-Probe auf DEV: die IBS-Option unter /support folgt dem Skill im echten Chrome.

jsdom rechnet kein Layout. Ob die Option wirklich verschwindet, zeigt nur ein
Browser, und ob der Schalter im laufenden Dienst wirkt, nur der Dienst selbst.

Schaltet den Skill zum Messen um und stellt den VORGEFUNDENEN Zustand wieder her.

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_support_ibs_skill_dev.py
"""
import json
import subprocess
import sys
import time
import urllib.request

import requests
import urllib3
import websocket

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
urllib3.disable_warnings()
from backend.main import generate_token  # noqa: E402

BASIS = "https://127.0.0.1"
SKILL = "kundenverwaltung"
TOK = generate_token("jarvis")
KOPF = {"Authorization": "Bearer " + TOK, "Content-Type": "application/json"}
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  ✓ %s" % name)
    else:
        fail += 1
        print("  ✗ %s%s" % (name, (" – %s" % detail) if detail else ""))


def status():
    r = requests.get(BASIS + "/api/support/status", headers=KOPF, verify=False, timeout=30)
    r.raise_for_status()
    return r.json()


def schalte(an):
    r = requests.post("%s/api/skills/%s/%s" % (BASIS, SKILL, "enable" if an else "disable"),
                      headers=KOPF, verify=False, timeout=60)
    r.raise_for_status()
    time.sleep(1)


def ibs_treffer():
    rumpf = {"text": "Drucker Fehler", "rag": False, "confluence": False, "jira_open": False,
             "jira_all": False, "ibs": True, "ai": False}
    r = requests.post(BASIS + "/api/support/query", headers=KOPF, data=json.dumps(rumpf),
                      verify=False, timeout=120)
    r.raise_for_status()
    return sum(1 for b in r.json().get("blocks", []) if b.get("source") == "IBS")


VORHER = bool(status().get("ibs_active"))
print("Vorgefunden: Skill %s" % ("an" if VORHER else "aus"))
PORT, PROFIL = 9342, "/tmp/chrome-sup-ibs"
subprocess.run(["rm", "-rf", PROFIL], check=False)
chrome = subprocess.Popen(["google-chrome", "--headless=new", "--remote-debugging-port=%d" % PORT,
                           "--user-data-dir=" + PROFIL, "--ignore-certificate-errors", "--no-sandbox",
                           "--remote-allow-origins=*", "--window-size=1500,1200", "--no-first-run",
                           "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)
tabs = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json" % PORT))
ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
nummer = [0]


def cmd(methode, params=None):
    nummer[0] += 1
    ws.send(json.dumps({"id": nummer[0], "method": methode, "params": params or {}}))
    while True:
        d = json.loads(ws.recv())
        if d.get("id") == nummer[0]:
            return d.get("result", {})


def js(code):
    r = cmd("Runtime.evaluate", {"expression": code, "returnByValue": True, "awaitPromise": True})
    return (r.get("result") or {}).get("value")


def oeffne():
    cmd("Page.navigate", {"url": BASIS + "/portal"})
    time.sleep(2)
    js("localStorage.setItem('jarvis_token', %s)" % json.dumps(TOK))
    cmd("Page.navigate", {"url": BASIS + "/support"})
    time.sleep(4)


def sichtbar(id_):
    return js("(function(){var e=document.getElementById('%s');"
              "return !!(e && e.offsetParent !== null);})()" % id_)


FILTER = "!!document.querySelector('#sup-f-source option[value=\"IBS\"]')"
try:
    print("\n1. Skill an")
    schalte(True)
    check("Status meldet den Skill als aktiv", status().get("ibs_active") is True)
    oeffne()
    check("Positivkontrolle: die Seite ist da", js("location.pathname") == "/support")
    check("IBS-Option sichtbar", sichtbar("sup-opt-ibs-wrap") is True)
    check("IBS im Quellen-Filter", js(FILTER) is True)
    treffer_an = ibs_treffer()
    print("  · IBS-Treffer mit aktivem Skill: %d" % treffer_an)

    print("\n2. Skill aus")
    schalte(False)
    check("Status meldet den Skill als inaktiv", status().get("ibs_active") is False)
    oeffne()
    check("Positivkontrolle: die Seite ist da", js("location.pathname") == "/support")
    check("IBS-Option verschwunden", sichtbar("sup-opt-ibs-wrap") is False)
    check("IBS nicht mehr im Quellen-Filter", js(FILTER) is False)
    check("die uebrigen Quellen stehen weiter da", sichtbar("sup-opt-rag") is True)
    check("Server liefert trotz ibs=true keine IBS-Treffer", ibs_treffer() == 0)
    if not treffer_an:
        print("  · Hinweis: auch mit Skill kein Treffer, die Serverzeile sagt hier wenig aus")
finally:
    schalte(VORHER)
    try:
        ws.close()
    except Exception:
        pass
    chrome.terminate()

print("\nRueckbau")
check("Skill wieder im vorgefundenen Zustand", bool(status().get("ibs_active")) == VORHER)
print("\n%d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
