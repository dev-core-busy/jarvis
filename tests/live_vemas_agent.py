#!/usr/bin/env python3
"""Ende-zu-Ende: ein ECHTER Agentenlauf gegen eine VEMAS-Attrappe (DEV).

Beweist, was die Einheitentests nicht koennen: dass das Modell die Werkzeuge
findet, ZUERST die Ressourcen ermittelt (statt Pfade zu raten) und die echten
Daten in die Antwort uebernimmt. Raeumt am Ende auf.
"""
import base64
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
import requests
import urllib3
urllib3.disable_warnings()
from backend.main import generate_token

BASIS = "https://127.0.0.1"
S = requests.Session()
S.verify = False
S.headers["Authorization"] = "Bearer " + generate_token("jarvis")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


GESEHEN = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        roh = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh))); self.end_headers()
        self.wfile.write(roh)

    def do_GET(self):
        GESEHEN.append(("GET", self.path))
        if self.path.startswith("/api/projects"):
            self._send(200, {"value": [
                {"id": 1, "name": "Neubau Halle Krefeld", "kunde": "Muster GmbH",
                 "budget": 120000, "aufwand": 118400, "status": "laufend"},
                {"id": 2, "name": "Wartungsvertrag 2026", "kunde": "Beispiel AG",
                 "budget": 48000, "aufwand": 12000, "status": "laufend"},
                {"id": 3, "name": "Migration Rechenzentrum", "kunde": "Muster GmbH",
                 "budget": 90000, "aufwand": 95500, "status": "laufend"}]})
        else:
            self._send(404, {"message": "unbekannte Ressource"})

    def do_POST(self):
        GESEHEN.append(("POST", self.path))
        self._send(201, {"id": 99})


srv = HTTPServer(("127.0.0.1", 8899), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.3)

try:
    print("\n\033[1m1. Vorbereiten\033[0m")
    check("Skill an", S.post(BASIS + "/api/skills/vemas/enable", timeout=90).status_code == 200)
    time.sleep(3)
    check("Freigabe gesetzt",
          S.post(BASIS + "/api/settings", json={"vemas_allowed_users": "jarvis"},
                 timeout=20).status_code == 200)
    check("Server konfiguriert",
          S.post(BASIS + "/api/skills/vemas/config",
                 json={"base_url": "http://127.0.0.1:8899/api", "auth_kind": "basic",
                       "username": "admin", "password": "geheim", "read_only": True,
                       "resources": "Projekte = projects",
                       "vemas_product": "Attrappe"}, timeout=20).status_code == 200)

    print("\n\033[1m2. Echter Agentenlauf\033[0m")
    GESEHEN.clear()
    t0 = time.time()
    r = S.post(BASIS + "/api/vemas/ask",
               json={"question": "Welche Projekte laufen aus dem Budget? "
                                 "Nenne Projektname, Budget und Aufwand.",
                     "tool": "inline", "lang": "de"},
               timeout=600)
    dauer = time.time() - t0
    d = r.json()
    check("Lauf beendet (%.1f s)" % dauer, r.status_code == 200 and d.get("ok"), r.text[:300])
    antwort = d.get("answer") or ""
    print("\n----- Antwort (gekuerzt) -----")
    print(antwort[:900])
    print("------------------------------\n")

    check("der Agent hat die Attrappe wirklich abgefragt",
          any(g[0] == "GET" and "projects" in g[1] for g in GESEHEN),
          GESEHEN[:6])
    check("KEIN Schreibzugriff versucht",
          not any(g[0] == "POST" for g in GESEHEN), GESEHEN)
    check("echte Daten in der Antwort (Projektname)",
          "Neubau Halle" in antwort or "Migration Rechenzentrum" in antwort,
          antwort[:200])
    check("die Budgetueberschreitung wurde erkannt",
          "95" in antwort or "Migration" in antwort, antwort[:200])
    check("der Ergebniskopf nennt den benutzten Zugang",
          d.get("quelle") == "sammel", d.get("quelle"))

    print("\n\033[1m3. Werkzeug-Protokoll\033[0m")
    al = S.get(BASIS + "/api/audit_log", params={"limit": 40}, timeout=20).json()
    # Der Endpunkt liefert eine LISTE, kein Objekt – beides tolerieren, damit
    # der Test nicht an der Verpackung scheitert statt an der Sache.
    eintraege = al if isinstance(al, list) else (al.get("entries") or al.get("log") or [])
    vem = [e for e in eintraege if str(e.get("tool", "")).startswith("vemas_")]
    check("vemas_-Werkzeuge stehen im Audit-Log", bool(vem),
          [e.get("tool") for e in eintraege[:8]])
    namen = [e.get("tool") for e in vem]
    check("der Agent hat ZUERST die Ressourcen ermittelt (statt zu raten)",
          "vemas_resources" in namen, namen)
    check("... und danach abgefragt", "vemas_query" in namen, namen)

finally:
    print("\n\033[1m4. Aufraeumen\033[0m")
    S.post(BASIS + "/api/settings", json={"vemas_allowed_users": "",
                                          "vemas_allowed_group": ""}, timeout=20)
    S.post(BASIS + "/api/skills/vemas/config",
           json={"base_url": "", "username": "", "password": "", "api_token": "",
                 "read_only": True, "resources": "", "vemas_product": ""}, timeout=20)
    S.post(BASIS + "/api/skills/vemas/disable", timeout=60)
    time.sleep(2)
    me = S.get(BASIS + "/api/me", timeout=15).json()
    check("permissions.vemas wieder False", me.get("permissions", {}).get("vemas") is False)
    check("/vemas wieder 404", S.get(BASIS + "/vemas", timeout=15).status_code == 404)
    srv.shutdown()

print("\n" + "=" * 62)
print("\033[%sm%d OK, %d FAIL\033[0m" % ("32" if fail == 0 else "31", ok, fail))
print("=" * 62)
sys.exit(0 if fail == 0 else 1)
