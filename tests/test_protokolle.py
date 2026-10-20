#!/usr/bin/env python3
"""Waechter fuer die weiteren Protokolle unter Einstellungen -> Protokolle
(Backend-Seite; die Oberflaeche prueft test_protokolle_ui.js).

1. SSH: ``fernzugang.ssh_zerlegen`` an den ECHTEN Zeilenformen (sshd-session,
   Fingerabdruck, IPv6, invalid user), ``ssh_protokoll`` filtert VOR dem Deckel
   und zaehlt je Art; die Meta-Op ist verdrahtet und AUDITIERT.
2. Update-Verlauf in einem Wegwerf-git-Repo: erfasst -> unveraendert ->
   stand_geaendert (mit Commits) -> Knopf (Erfolg/Fehlschlag) -> umgeschriebene
   Historie (kein Vorspulen) -> Frist.
3. Zerleger: Agent-Korrekturen (gegen das Format, das reflection.py SCHREIBT),
   Abhaengigkeitszustand, Journalzeilen mit Traceback-Fortsetzung.
4. main.py: Endpunkte geschnitten und ausgefuehrt (Journal/SSH mit Broker-
   Attrappe), alle /api/logs/* lesend nur fuer Administratoren, Verdrahtung
   von Start-Hook, Update-Knopf und Aufbewahrungsfrist.

Ohne fastapi; backend.config nur als Attrappe; nichts im echten Bestand.
"""

import ast
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_ok = _fail = 0


def pruefe(bed, text):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text)


_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(get_setting=lambda k, d=None: d)
sys.modules["backend.config"] = _cfg
SAND = Path(tempfile.mkdtemp(prefix="plog_test_"))

# ═══ 1. SSH ═════════════════════════════════════════════════════════════════
print("\n== 1. SSH-Anmeldungen")
from backend.broker import fernzugang as F  # noqa: E402
from backend.broker import meta as M  # noqa: E402

ZEILEN = """2026-10-06T19:22:45+02:00 host sshd-session[3506886]: Accepted publickey for root from 192.0.2.10 port 37258 ssh2: RSA SHA256:abcDEF123
2026-10-07T08:00:00+02:00 host sshd-session[1]: Accepted password for admin from 192.0.2.11 port 4000 ssh2
2026-10-08T19:11:28+02:00 host sshd-session[2]: Failed password for root from 192.0.2.12 port 38350 ssh2
2026-10-08T19:11:29+02:00 host sshd-session[3]: Failed password for invalid user oracle from 192.0.2.13 port 38351 ssh2
2026-10-08T19:11:30+02:00 host sshd-session[4]: Invalid user oracle from 192.0.2.13 port 38351
2026-10-09T10:00:00+02:00 host sshd[5]: Accepted publickey for alt from 2001:db8::1 port 22 ssh2: ED25519 SHA256:xyz
2026-10-09T10:00:01+02:00 host sshd-session[6]: Connection closed by 192.0.2.99 port 1 [preauth]"""
E = F.ssh_zerlegen(ZEILEN)
# Zugriffe absturzsicher: eine Sabotage, die die Liste verkuerzt, soll ein FAIL
# ergeben und keinen IndexError (Register: Absturz ist kein Biss).
g = lambda i: E[i] if -len(E) <= i < len(E) else {}  # noqa: E731
pruefe(len(E) == 6, "sechs Ereignisse, Rauschzeile uebergangen (%d)" % len(E))
pruefe(g(0) == {"zeit": "2026-10-06T19:22:45+02:00", "art": "angenommen", "methode": "publickey",
                "konto": "root", "ip": "192.0.2.10", "schluessel": "RSA SHA256:abcDEF123"},
       "sshd-session-Zeile mit Fingerabdruck")
pruefe(g(1).get("methode") == "password" and g(1).get("schluessel") == "", "Kennwort-Anmeldung ohne Schluessel")
pruefe([g(i).get("art") for i in (2, 3, 4)] == ["fehlgeschlagen", "fehlgeschlagen", "unbekannt"],
       "fehlgeschlagen / invalid user / unbekannt")
pruefe(g(3).get("konto") == "oracle", "bei 'invalid user' das gesuchte Konto, nicht das Wort 'invalid'")
pruefe(g(5).get("ip") == "2001:db8::1" and g(5).get("konto") == "alt", "alter Prozessname sshd[pid], IPv6")

# ssh_protokoll mit Attrappe statt journalctl
_aufrufe = []
F._lauf = lambda cmd, timeout=60: (_aufrufe.append(cmd), types.SimpleNamespace(stdout=ZEILEN))[1]
r = F.ssh_protokoll(7, "")
pruefe(r["ok"] and r["anzahl"] == {"angenommen": 3, "fehlgeschlagen": 2, "unbekannt": 1}, "Zaehler je Art")
pruefe(r["eintraege"][0]["zeit"].startswith("2026-10-09T10:00:00"), "juengste zuerst")
pruefe("-u" in _aufrufe[-1] and "--since" in _aufrufe[-1] and "-7d" in _aufrufe[-1],
       "journalctl mit Einheit und Zeitraum: %s" % " ".join(_aufrufe[-1]))
r = F.ssh_protokoll(99, "fehlgeschlagen")
pruefe(r["tage"] == F.SSH_TAGE_MAX and [e["art"] for e in r["eintraege"]] == ["fehlgeschlagen"] * 2,
       "Zeitraum gedeckelt, Filter liefert nur Fehlschlaege")
pruefe(r["anzahl"]["angenommen"] == 3, "Zaehler gelten fuer den ganzen Zeitraum, nicht nur den Filter")
pruefe(F.ssh_protokoll("x", "boese")["art"] == "", "unbekannte Art -> kein Filter, kein Fehler")
# Filter VOR dem Deckel: viele Erfolge duerfen Fehlschlaege nicht verdraengen
viel = "\n".join("2026-10-01T00:00:%02d+02:00 h sshd-session[1]: Accepted publickey for r from 192.0.2.1 port 1 ssh2: RSA SHA256:a"
                 % (i % 60) for i in range(F.SSH_EINTRAEGE_MAX + 50)) + "\n" + ZEILEN.splitlines()[2]
F._lauf = lambda cmd, timeout=60: types.SimpleNamespace(stdout=viel)
r = F.ssh_protokoll(30, "fehlgeschlagen")
pruefe(len(r["eintraege"]) == 1, "ein Fehlschlag unter %d Erfolgen wird gefunden" % (F.SSH_EINTRAEGE_MAX + 50))
r = F.ssh_protokoll(30, "")
pruefe(len(r["eintraege"]) == F.SSH_EINTRAEGE_MAX and r["gekappt"] == 51, "Deckel greift und wird beziffert")

# Meta-Op: verdrahtet und auditiert
_audit = []
M.policy.audit = lambda *a, **k: _audit.append((a, k))
M.fernzugang = F  # falls das Modul den Namen kennt
F._lauf = lambda cmd, timeout=60: types.SimpleNamespace(stdout=ZEILEN)
erg = M._behandeln("broker.ssh_protokoll", {"tage": 7, "art": "fehlgeschlagen", "by": "admin"})
pruefe(erg and erg.get("ok") and len(erg["eintraege"]) == 2, "Meta-Op broker.ssh_protokoll antwortet")
pruefe(_audit and _audit[-1][0][0] == "admin" and _audit[-1][0][1] == "broker.ssh_protokoll",
       "jede Abfrage im Broker-Audit, mit Benutzer")

# ═══ 2. Update-Verlauf ══════════════════════════════════════════════════════
print("\n== 2. Update-Verlauf (Wegwerf-Repo)")
from backend import update_protokoll as UP  # noqa: E402

REPO = SAND / "repo"
REPO.mkdir()
G = lambda *a: subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True,  # noqa: E731
                              env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@beispiel.de",
                                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@beispiel.de"))
G("init", "-q")
G("config", "commit.gpgsign", "false")


def commit(titel):
    (REPO / "f.txt").write_text(titel)
    G("add", "f.txt")
    G("commit", "-q", "-m", titel)


commit("erster Stand")
UP.WURZEL = REPO
UP.DATEI = SAND / "logs" / "updates.jsonl"
UP.STAND = SAND / "logs" / "update_stand.json"
pruefe(UP.stand()["titel"] == "erster Stand", "Positivkontrolle: stand() liest das Wegwerf-Repo")
e = UP.beim_start()
pruefe(e and e["art"] == "erfasst", "erster Start: Ausgangsstand erfasst, kein erfundener Wechsel")
pruefe(UP.beim_start() is None, "unveraendert: kein Eintrag")
commit("zweiter")
commit("dritter")
e = UP.beim_start()
pruefe(e and e["art"] == "stand_geaendert" and e["anzahl"] == 2 and e["vorgespult"] is True,
       "Wechsel mit zwei neuen Commits")
pruefe([c["titel"] for c in e["commits"]] == ["dritter", "zweiter"], "Commit-Titel, juengster zuerst")
vor = UP.stand()
UP.knopf("FIRMA\\admin", vor, {"ok": False, "error": "x" * 900, "signatur": "fehlt"})
k = UP.lesen()[0]
pruefe(k["art"] == "update_knopf" and k["ok"] is False and k["benutzer"] == "FIRMA\\admin",
       "Fehlschlag ueber den Knopf: Ausloeser und Ergebnis")
pruefe(len(k["fehler"]) <= UP.FEHLER_MAX + 1 and k["grund"] == "signatur", "Fehlertext gedeckelt, Grund benannt")
UP.knopf("admin", vor, {"ok": True, "broker_betroffen": True})
pruefe(UP.lesen()[0]["broker_neustart"] is True and UP.lesen()[0]["ok"] is True, "Erfolg mit Broker-Neustart")
# Historie umgeschrieben: neuer Stand ist KEIN Nachfahre
G("checkout", "-q", "--orphan", "neu")
commit("neue Wurzel")
e = UP.beim_start()
pruefe(e and e["vorgespult"] is False and not e.get("commits"), "umgeschriebene Historie: kein Vorspulen, keine Liste")
pruefe([x["art"] for x in UP.lesen()][:2] == ["stand_geaendert", "update_knopf"], "juengste zuerst")
alt = len(UP.lesen())
pruefe(UP.prune_older_than(9e18) == alt and UP.lesen() == [], "Frist entfernt alles Aeltere")

# ═══ 3. Zerleger ════════════════════════════════════════════════════════════
print("\n== 3. Zerleger")
from backend import protokoll_quellen as PQ  # noqa: E402

# Testmaterial baut der ERZEUGER: das Format steht in reflection.py.
REF = (ROOT / "backend" / "tools" / "reflection.py").read_text(encoding="utf-8")
for feld in ("## Code-Fix: {file}", "Datum: ", "Grund: {reason}", "Backup: {bak.name}", "Deployt nach: "):
    pruefe(feld in REF, "reflection.py schreibt weiterhin '%s'" % feld)
LOG = ("## Code-Fix: backend/a.py\nDatum: 2026-10-01 10:00\nGrund: Tippfehler\nBackup: a.py.bak\n"
       "Deployt nach: /opt/jarvis\n\n## Code-Fix: backend/b.py\nDatum: 2026-10-02 11:00\n"
       "Grund: Grund: mit Doppelpunkt\nBackup: b.py.bak\nDeployt nach: nur lokal\n")
cf = PQ.code_fixes_zerlegen(LOG)
pruefe([x["datei"] for x in cf] == ["backend/b.py", "backend/a.py"], "juengste Korrektur zuerst")
pruefe(cf[0]["grund"] == "Grund: mit Doppelpunkt" and cf[1]["deployt"] == "/opt/jarvis",
       "Felder vollstaendig, Doppelpunkt im Wert bleibt")
PQ.CODE_FIXES = SAND / "fehlt.log"
pruefe(PQ.code_fixes_lesen() == {"ok": True, "vorhanden": False, "eintraege": [], "anzahl": 0},
       "fehlende Datei ist eine Auskunft, kein Fehler")
PQ.CODE_FIXES = SAND / "fixes.log"
PQ.CODE_FIXES.write_text(LOG)
pruefe(PQ.code_fixes_lesen(limit=1)["anzahl"] == 2 and len(PQ.code_fixes_lesen(limit=1)["eintraege"]) == 1,
       "Deckel und Gesamtzahl")

PQ.ABHAENGIGKEITEN = SAND / "abh.json"
pruefe(PQ.abhaengigkeiten_lesen() == {"ok": True, "vorhanden": False}, "ohne Pruefung: vorhanden=False")
PQ.ABHAENGIGKEITEN.write_text(json.dumps({"zeit": "2026-10-20T16:16:42", "offen": [], "fehler": ""}))
a = PQ.abhaengigkeiten_lesen()
pruefe(a["vorhanden"] and a["zustand"]["zeit"] == "2026-10-20T16:16:42" and a["alter_s"] >= 0, "Zustand mit Alter")
PQ.ABHAENGIGKEITEN.write_text("{kaputt")
pruefe(PQ.abhaengigkeiten_lesen()["ok"] is False, "kaputte Datei: Auskunft statt Ausnahme")

J = ("-- Boot abc --\n2026-10-20T17:28:03+02:00 h start_jarvis.sh[530299]: [AUTH] erfolgreich\n"
     "2026-10-20T17:28:04+0200 h start_jarvis.sh[530299]: Traceback (most recent call last):\n"
     '  File "x.py", line 1\nValueError: kaputt\n-- No entries --\n')
jz = PQ.journal_zerlegen(J)
pruefe(len(jz) == 2 and jz[0]["prozess"] == "start_jarvis.sh", "zwei Eintraege, Prozessname ohne PID")
pruefe(jz[1]["text"].count("\n") == 2 and jz[1]["text"].endswith("ValueError: kaputt"),
       "Traceback-Fortsetzung haengt am Eintrag davor")
pruefe(jz[1]["zeit"] == "2026-10-20T17:28:04+0200", "beide Zeitzonenformen (+02:00 / +0200)")

# ═══ 4. main.py ═════════════════════════════════════════════════════════════
print("\n== 4. Endpunkte und Verdrahtung")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)
FN = {n.name: n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


class JSONResponse:
    def __init__(self, content, status_code=200, headers=None, media_type=None, background=None):
        self.status_code = status_code
        self.inhalt = content


def schneiden(name, ns):
    f = FN[name]
    f2 = type(f)(**{k: getattr(f, k) for k in f._fields})
    f2.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[f2], type_ignores=[])), "main.py", "exec"), ns)
    return ns[name]


rufe = []
ANTWORT = {"r": {}}


async def _call(op, args, user="", timeout=0):
    rufe.append((op, args, user))
    return ANTWORT["r"]

bc = types.ModuleType("backend.broker_client")
bc.call = _call
sys.modules["backend.broker_client"] = bc
import backend  # noqa: E402
backend.broker_client = bc
backend.protokoll_quellen = PQ
ns = {"JSONResponse": JSONResponse, "asyncio": asyncio, "Depends": lambda f: None,
      "require_local_auth": None, "_display_name": lambda u: "ANZ:" + u}
schneiden("_broker_antwort_text", ns)
jr = schneiden("protokoll_journal", ns)
ANTWORT["r"] = {"rc": 0, "stdout": J, "gekappt": 0}
r = asyncio.run(jr(einheit="broker", stufe="fehler", zeitraum="7d", suche="  AUTH ", zeilen=99999, user="admin"))
op, args, u = rufe[-1]
pruefe(op == "journal_lesen" and args["einheit"] == "jarvis-broker.service" and u == "admin",
       "Journal ueber journal_lesen, Einheit uebersetzt, Benutzer mitgegeben")
pruefe(args["prioritaet"] == "err" and args["seit"] == "-7d" and args["umgekehrt"] is True
       and args["suche"] == "AUTH" and args["zeilen"] == 2000, "Stufe/Zeitraum uebersetzt, neueste zuerst, Deckel")
pruefe(r.inhalt["ok"] and len(r.inhalt["eintraege"]) == 2, "Zeilen zerlegt")
asyncio.run(jr(einheit="jarvis", stufe="", zeitraum="24h", suche="", zeilen=300, user="admin"))
pruefe("prioritaet" not in rufe[-1][1] and "suche" not in rufe[-1][1], "ohne Stufe/Suche keine leeren Argumente")
n_vorher = len(rufe)
r = asyncio.run(jr(einheit="sshd", stufe="", zeitraum="24h", suche="", zeilen=300, user="admin"))
pruefe(r.status_code == 400 and len(rufe) == n_vorher, "fremde Einheit: 400, der Broker wird nicht gefragt")
ANTWORT["r"] = {"decision": "unknown-op"}
r = asyncio.run(jr(einheit="jarvis", stufe="", zeitraum="1h", suche="", zeilen=300, user="admin"))
pruefe(r.inhalt["ok"] is False and "neu starten" in r.inhalt["error"], "alter Broker: Klartext mit Abhilfe")
ANTWORT["r"] = {"decision": "denied"}
r = asyncio.run(jr(einheit="jarvis", stufe="", zeitraum="1h", suche="", zeilen=300, user="admin"))
pruefe("gesperrt" in r.inhalt["error"], "gesperrt: Klartext")
ANTWORT["r"] = {"rc": 1, "stdout": "", "stderr": ""}
r = asyncio.run(jr(einheit="jarvis", stufe="", zeitraum="1h", suche="nix", zeilen=300, user="admin"))
pruefe(r.inhalt["ok"] is True and r.inhalt["eintraege"] == [], "kein Suchtreffer ist kein Fehler")

sr = schneiden("protokoll_ssh", ns)
ANTWORT["r"] = {"ok": True, "eintraege": [], "anzahl": {}, "type": "result"}
r = asyncio.run(sr(tage=30, art="fehlgeschlagen", user="admin"))
pruefe(rufe[-1][0] == "broker.ssh_protokoll" and rufe[-1][1]["by"] == "admin"
       and rufe[-1][1]["art"] == "fehlgeschlagen", "SSH ueber die Meta-Op, mit by= fuer das Audit")
pruefe("type" not in r.inhalt, "Transportfeld 'type' entfernt")

routen = []
for n in BAUM.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for d in n.decorator_list:
            if isinstance(d, ast.Call) and getattr(d.func, "attr", "") in ("get", "post", "put", "delete", "patch") \
                    and d.args and isinstance(d.args[0], ast.Constant) \
                    and str(d.args[0].value).startswith("/api/logs/") \
                    and not str(d.args[0].value).startswith("/api/logs/retention"):
                routen.append((d.func.attr, d.args[0].value, n))
pfade = sorted(p for _, p, _ in routen)
pruefe(pfade == ["/api/logs/abhaengigkeiten", "/api/logs/code_fixes", "/api/logs/journal",
                 "/api/logs/ssh", "/api/logs/updates"], "fuenf neue Routen: %s" % pfade)
pruefe(all(m == "get" for m, _, _ in routen), "alle nur lesend (GET)")
pruefe(all("require_local_auth" in ast.unparse(n.args) for _, _, n in routen), "alle nur fuer Administratoren")

def ruft(fn_name, ziel):
    """Wird ``ziel`` aufgerufen ODER als Argument uebergeben (asyncio.to_thread(ziel, …))?
    Erste Fassung pruefte nur direkte Aufrufe und meldete den Start-Hook als
    fehlend, der die Funktion an to_thread uebergibt."""
    for x in ast.walk(FN[fn_name]):
        if isinstance(x, ast.Call):
            if ast.unparse(x.func) == ziel or any(ast.unparse(a) == ziel for a in x.args):
                return True
    return False


pruefe("startup_update_verlauf" in FN and ruft("startup_update_verlauf", "update_protokoll.beim_start"),
       "Start-Hook ruft update_protokoll.beim_start")
pruefe(any(ast.unparse(d) == "app.on_event('startup')" for d in FN["startup_update_verlauf"].decorator_list),
       "und ist als Start-Hook registriert")
pruefe(ruft("update_apply", "update_protokoll.knopf"), "Update-Knopf protokolliert Ausloeser und Ergebnis")
pruefe(ruft("update_apply", "update_protokoll.stand"), "und merkt sich den Stand VOR dem Update")
RET = (ROOT / "backend" / "log_retention.py").read_text(encoding="utf-8")
pruefe('("update_verlauf", _prune_update_verlauf)' in RET, "Update-Verlauf unterliegt der Aufbewahrungsfrist")

print("\nBILANZ: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
