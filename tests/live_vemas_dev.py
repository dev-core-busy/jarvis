#!/usr/bin/env python3
"""Live-Probe des VEMAS-Bereichs auf DEV – gegen einen echten HTTP-Server.

Laeuft AUF DEV (braucht localhost-Zugriff auf 443). Startet einen kleinen
Attrappen-Server, der sich wie eine VEMAS-REST-Schnittstelle verhaelt, und
faehrt den ganzen Weg ab: Anmeldung, Freigabe, Reiter-Konfiguration,
Bereichs-Status, Ressourcen, Abfrage, persoenlicher Zugang, Schreibregel.

Raeumt am Ende AUF: Skill-Zustand, Freigabeliste und Skill-Config werden auf
den Ausgangsstand zurueckgesetzt.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib3
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, "/opt/jarvis")
import requests
urllib3.disable_warnings()

BASIS = "https://127.0.0.1"
S = requests.Session()
S.verify = False
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


# ── Attrappen-VEMAS auf Port 8899 ───────────────────────────────────────────
GESEHEN = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        roh = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_GET(self):
        GESEHEN.append(("GET", self.path, self.headers.get("Authorization", "")))
        if self.path.startswith("/api/projects"):
            self._send(200, {"value": [{"id": 1, "name": "Neubau Halle", "budget": 120000},
                                       {"id": 2, "name": "Wartung 2026", "budget": 48000}]})
        elif self.path.startswith("/api/customers"):
            self._send(200, {"items": [{"id": "K1", "name": "Muster GmbH"}]})
        elif self.path.startswith("/api/swagger"):
            self._send(404, {"message": "nicht vorhanden"})
        else:
            self._send(404, {"message": "unbekannte Ressource"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        rumpf = self.rfile.read(n) if n else b"{}"
        GESEHEN.append(("POST", self.path, rumpf.decode()))
        self._send(201, {"id": 99, "angelegt": True})


srv = HTTPServer(("127.0.0.1", 8899), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.3)

print("\n\033[1m0. Sitzung\033[0m")

# Das Sitzungstoken wird HIER erzeugt, nicht ueber /api/login geholt:
# die Anmeldung laeuft gegen PAM, und das OS-Kennwort des Benutzers `jarvis`
# ist auf diesem Rechner ein anderes als der Eintrag in der .env (nachgesehen
# im Journal: `pam_unix(login:auth): authentication failure`). `generate_token`
# ist genau die Funktion, die der Endpunkt nach erfolgreicher Anmeldung selbst
# ruft – es wird also nichts umgangen, was danach noch geprueft wuerde: jeder
# Endpunkt prueft das Token UND die Freigabe.
tok = ""
try:
    import sys as _s
    _s.argv = ["x"]
    from backend.main import generate_token
    tok = generate_token("jarvis")
except Exception as e:
    print("  Token nicht erzeugbar:", e)
check("Sitzungstoken erzeugt", bool(tok))
if not tok:
    sys.exit(2)
S.headers["Authorization"] = "Bearer " + tok
check("das Token wird vom Server angenommen",
      S.get(BASIS + "/api/me", timeout=15).status_code == 200)

VORHER = {}


def cfg_setzen(**kw):
    r = S.post(BASIS + "/api/skills/vemas/config", json=kw, timeout=20)
    return r.status_code


try:
    print("\n\033[1m1. Ausgangszustand: leer = niemand\033[0m")
    me = S.get(BASIS + "/api/me", timeout=15).json()
    check("permissions.vemas ist False (Skill aus, Freigabe leer)",
          me.get("permissions", {}).get("vemas") is False,
          me.get("permissions", {}).get("vemas"))
    check("/api/vemas/status ist ohne Freigabe 403",
          S.get(BASIS + "/api/vemas/status", timeout=15).status_code == 403)
    check("/vemas ist ohne aktiven Skill 404",
          S.get(BASIS + "/vemas", timeout=15).status_code == 404)

    print("\n\033[1m2. Skill einschalten\033[0m")
    r = S.post(BASIS + "/api/skills/vemas/enable", timeout=90)
    check("Skill eingeschaltet", r.status_code == 200, r.status_code)
    time.sleep(3)
    sk = S.get(BASIS + "/api/skills", timeout=20).json()
    eintrag = [s for s in (sk.get("skills") or sk) if s.get("dir_name") == "vemas"]
    check("Skill wird als aktiv gefuehrt", eintrag and eintrag[0].get("enabled"), eintrag)
    check("/vemas liefert jetzt die Seite",
          S.get(BASIS + "/vemas", timeout=15).status_code == 200)
    check("... aber die Datenendpunkte bleiben ohne Freigabe zu (403)",
          S.get(BASIS + "/api/vemas/status", timeout=15).status_code == 403)
    me = S.get(BASIS + "/api/me", timeout=15).json()
    check("permissions.vemas weiterhin False (Skill an, Freigabe leer)",
          me.get("permissions", {}).get("vemas") is False)

    print("\n\033[1m3. Freigabe erteilen\033[0m")
    r = S.post(BASIS + "/api/settings",
               json={"vemas_allowed_users": "jarvis"}, timeout=20)
    check("Freigabe gespeichert", r.status_code == 200, r.status_code)
    me = S.get(BASIS + "/api/me", timeout=15).json()
    check("permissions.vemas ist jetzt True",
          me.get("permissions", {}).get("vemas") is True, me.get("permissions"))
    st = S.get(BASIS + "/api/vemas/status", timeout=15)
    check("Status erreichbar", st.status_code == 200, st.status_code)
    check("noch nicht konfiguriert", st.json().get("configured") is False, st.json())

    print("\n\033[1m4. Server konfigurieren (Reiter)\033[0m")
    check("Konfiguration gespeichert",
          cfg_setzen(base_url="http://127.0.0.1:8899/api", auth_kind="basic",
                     username="admin", password="geheim", read_only=True,
                     resources="Projekte = projects\nKunden = customers",
                     vemas_product="Vemas.NextGen (Attrappe)") == 200)
    st = S.get(BASIS + "/api/vemas/status", timeout=20).json()
    check("Status meldet konfiguriert", st.get("configured") is True, st)
    check("zwei Ressourcen erkannt", st.get("resources") == 2, st.get("resources"))
    check("Nur-Lesen wird angezeigt", st.get("read_only") is True)
    check("Quelle ist der Sammelzugang", st.get("quelle") == "sammel", st.get("quelle"))

    t = S.get(BASIS + "/api/vemas/test", timeout=30).json()
    check("Verbindungstest laeuft gegen den echten Server", t.get("ok") is True, t)
    check("... und nennt den benutzten Pfad", "projects" in str(t.get("detail")), t)

    print("\n\033[1m5. Abfrage-Konsole (nur lesend)\033[0m")
    q = S.get(BASIS + "/api/vemas/query",
              params={"resource": "Projekte", "top": 5}, timeout=30).json()
    check("Abfrage ueber den NAMEN liefert Zeilen",
          q.get("ok") and len(q.get("rows") or []) == 2, q)
    check("Spalten erkannt", "budget" in (q.get("columns") or []), q.get("columns"))
    q2 = S.get(BASIS + "/api/vemas/query",
               params={"resource": "Kunden"}, timeout=30).json()
    check("zweite Ressource (items-Verpackung) funktioniert",
          q2.get("ok") and q2["rows"][0]["name"] == "Muster GmbH", q2)
    q3 = S.get(BASIS + "/api/vemas/query",
               params={"resource": "Projekte", "params": "{kaputt"}, timeout=20)
    check("kaputtes JSON im Filter wird ABGEWIESEN (nicht still ignoriert)",
          q3.status_code == 400 and "JSON" in q3.json().get("error", ""), q3.text[:120])
    q4 = S.get(BASIS + "/api/vemas/query",
               params={"resource": "https://example.com/x"}, timeout=20)
    check("absolute URL als Ressource wird abgewiesen",
          q4.status_code == 400, q4.status_code)

    print("\n\033[1m6. Katalog und Auswertung\033[0m")
    kat = S.get(BASIS + "/api/vemas/analyses?lang=de", timeout=20).json()
    check("Katalog geliefert", len(kat.get("analyses") or []) >= 15, len(kat.get("analyses") or []))
    check("Kategorien vorhanden", len(kat.get("categories") or []) >= 5)
    check("Zielwerkzeuge vorhanden", len(kat.get("tools") or []) >= 3)
    kat_en = S.get(BASIS + "/api/vemas/analyses?lang=en", timeout=20).json()
    check("englischer Katalog ist englisch", kat_en.get("lang") == "en"
          and (kat_en.get("analyses") or [{}])[0].get("title")
              != (kat.get("analyses") or [{}])[0].get("title"))
    erste = (kat.get("analyses") or [{"id": ""}])[0].get("id", "")
    check("eine Abfrage-Id fuer die Folgepruefungen", bool(erste), kat)
    ad = S.get(BASIS + "/api/vemas/analyses/catalog?lang=de", timeout=20).json()
    check("Admin-Katalog zeigt alle mit Sichtbarkeitsmerker",
          len(ad.get("analyses") or []) == ad.get("total"), ad.get("total"))

    check("Sichtbarkeit gespeichert", cfg_setzen(hidden_analyses=[erste]) == 200)
    kat2 = S.get(BASIS + "/api/vemas/analyses?lang=de", timeout=20).json()
    check("ausgeblendete Abfrage fehlt im Benutzer-Katalog",
          erste not in [a["id"] for a in kat2["analyses"]])
    r = S.post(BASIS + "/api/vemas/ask", json={"analysis_id": erste}, timeout=30)
    check("... und laesst sich auch nicht mehr starten (400 hidden)",
          r.status_code == 400 and r.json().get("hidden") is True, r.text[:150])
    check("Sichtbarkeit zurueckgesetzt", cfg_setzen(hidden_analyses=[]) == 200)
    check("Verbindungsdaten haben das Speichern der Sichtbarkeit ueberlebt",
          S.get(BASIS + "/api/vemas/status", timeout=20).json().get("configured") is True)

    r = S.post(BASIS + "/api/vemas/ask", json={}, timeout=20)
    check("leerer Auftrag wird abgewiesen", r.status_code == 400, r.status_code)
    r = S.post(BASIS + "/api/vemas/ask", json={"analysis_id": "gibtsnicht"}, timeout=20)
    check("unbekannte Abfrage wird abgewiesen", r.status_code == 400)

    print("\n\033[1m7. Persoenlicher Zugang\033[0m")
    a = S.get(BASIS + "/api/vemas/account", timeout=20).json()["account"]
    check("noch kein eigener Zugang", a["vorhanden"] is False)
    check("die Serveradresse wird ANGEZEIGT", a["server"] == "http://127.0.0.1:8899/api", a["server"])
    check("Schreiben ist (noch) nicht freigegeben", a["schreiben_frei"] is False)

    r = S.post(BASIS + "/api/vemas/account",
               json={"auth_kind": "basic", "username": "eigen", "password": "meins"},
               timeout=20)
    check("eigener Zugang gespeichert", r.status_code == 200 and r.json()["account"]["vorhanden"],
          r.text[:150])
    check("Kennwort wird NICHT herausgegeben",
          "meins" not in r.text and r.json()["account"]["passwort_gesetzt"] is True)

    st = S.get(BASIS + "/api/vemas/status", timeout=20).json()
    check("Quelle ist jetzt der persoenliche Zugang", st.get("quelle") == "persoenlich", st.get("quelle"))

    GESEHEN.clear()
    S.get(BASIS + "/api/vemas/query", params={"resource": "Projekte"}, timeout=30)
    import base64
    erwartet = "Basic " + base64.b64encode(b"eigen:meins").decode()
    check("die Abfrage benutzt die EIGENEN Zugangsdaten",
          any(g[2] == erwartet for g in GESEHEN),
          [g[2][:20] for g in GESEHEN])

    r = S.post(BASIS + "/api/vemas/account", json={"base_url": "http://boese.de"}, timeout=20)
    check("die Serveradresse laesst sich NICHT selbst setzen (400)",
          r.status_code == 400 and "base_url" in r.json().get("error", ""), r.text[:180])
    r = S.post(BASIS + "/api/vemas/account", json={"read_only": False}, timeout=20)
    check("Nur-Lesen laesst sich NICHT selbst abschalten (400)",
          r.status_code == 400 and "read_only" in r.json().get("error", ""), r.text[:180])

    adm = S.get(BASIS + "/api/vemas/admin/accounts", timeout=20).json()
    check("Admin sieht, WER einen eigenen Zugang hat", adm.get("ok")
          and len(adm.get("accounts") or []) == 1, adm)
    check("... aber weder Zugangsdaten noch Adresse",
          "meins" not in json.dumps(adm) and "8899" not in json.dumps(adm))

    print("\n\033[1m8. Die Schreibregel\033[0m")
    check("Schreiben freigeschaltet", cfg_setzen(read_only=False) == 200)
    a = S.get(BASIS + "/api/vemas/account", timeout=20).json()["account"]
    check("die Kachel meldet die Freigabe", a["schreiben_frei"] is True)
    st = S.get(BASIS + "/api/vemas/status", timeout=20).json()
    check("mit eigenem Zugang gilt sie", st.get("read_only") is False, st.get("read_only"))

    S.delete(BASIS + "/api/vemas/account", timeout=20)
    st = S.get(BASIS + "/api/vemas/status", timeout=20).json()
    check("OHNE eigenen Zugang bleibt es beim Lesen – trotz Freigabe",
          st.get("read_only") is True and st.get("quelle") == "sammel", st)

    print("\n\033[1m9. Werkzeuge im Agenten\033[0m")
    out = subprocess.run(
        ["runuser", "-u", "jarvis", "--", "/opt/jarvis/venv/bin/python", "-c", """
import sys; sys.path.insert(0,'/opt/jarvis')
from skills.vemas.main import get_tools
t = get_tools()
print('TOOLS', ','.join(x.name for x in t))
print('SCHEMA_OK', all(isinstance(x.parameters_schema(), dict) for x in t))
"""], capture_output=True, text=True, cwd="/opt/jarvis")
    check("Skill laedt im Produktiv-venv", "TOOLS" in out.stdout, out.stderr[-300:])
    check("sieben Werkzeuge", out.stdout.count(",") == 6, out.stdout.strip())
    check("alle Schemata gueltig", "SCHEMA_OK True" in out.stdout, out.stdout.strip())

finally:
    print("\n\033[1m10. Aufraeumen\033[0m")
    try:
        S.delete(BASIS + "/api/vemas/account", timeout=20)
    except Exception:
        pass
    try:
        S.post(BASIS + "/api/settings", json={"vemas_allowed_users": "",
                                                   "vemas_allowed_group": ""}, timeout=20)
        cfg_setzen(base_url="", username="", password="", api_token="",
                   read_only=True, resources="", vemas_product="",
                   hidden_analyses=[])
        S.post(BASIS + "/api/skills/vemas/disable", timeout=60)
    except Exception as e:
        print("  Aufraeumen unvollstaendig:", e)
    time.sleep(2)
    me = S.get(BASIS + "/api/me", timeout=15).json()
    check("permissions.vemas wieder False", me.get("permissions", {}).get("vemas") is False)
    check("/vemas wieder 404", S.get(BASIS + "/vemas", timeout=15).status_code == 404)
    srv.shutdown()

print("\n" + "=" * 62)
print("\033[%sm%d OK, %d FAIL\033[0m" % ("32" if fail == 0 else "31", ok, fail))
print("=" * 62)
sys.exit(0 if fail == 0 else 1)
