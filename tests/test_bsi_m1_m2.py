#!/usr/bin/env python3
"""Waechter BSI M1 (systemd-Haertung) + M2 (Sicherheitsprotokoll).

Fuehrt aus, was ausfuehrbar ist – Hash-Kette, Admin-Middleware, Anmelde-
protokoll, Installationsskript, Audit-Rotation – und prueft am Syntaxbaum nur
die Verdrahtung, die ohne laufenden Dienst nicht messbar ist.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import contextvars
import copy
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

OK = FAIL = 0


def check(name, bed):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name)


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


TMP = Path(tempfile.mkdtemp(prefix="bsi_m1m2_"))

# ═══════════════════════════════════════════════════════════════════════════
print("[A] Sicherheitsprotokoll: Kette, Frist, syslog")
sl = importlib.import_module("backend.sicherheits_log")
sl.DATEI = TMP / "logs" / "sicherheit.jsonl"
sl._letzter_hash = None
if not str(sl.DATEI).startswith(str(TMP)):
    abbruch("Protokolldatei zeigt aus dem Sandkasten heraus")

gesendet = []


class _Fang:
    def log(self, stufe, text):
        gesendet.append((stufe, text))


sl._syslog = _Fang()

e1 = sl.ereignis("anmeldung", benutzer="anna", ip="10.0.0.1", ergebnis="erfolg", weg="kennwort")
e2 = sl.ereignis("anmeldung_fehlgeschlagen", benutzer="bert", ip="10.0.0.2", ergebnis="401")
e3 = sl.ereignis("admin_aenderung", benutzer="jarvis", ip="10.0.0.3", ergebnis="200",
                 methode="POST", pfad="/api/x")
zeilen = sl.DATEI.read_text().splitlines()
if len(zeilen) != 3:
    abbruch("Positivkontrolle: drei Ereignisse geschrieben, %d Zeilen gefunden" % len(zeilen))
check("Kette beginnt beim Null-Hash", e1["prev"] == sl.NULL_HASH)
check("jede Zeile verweist auf die vorige", e2["prev"] == e1["hash"] and e3["prev"] == e2["hash"])
check("unveraenderte Datei prueft gruen", sl.pruefen()["ok"])
check("Datei ist nur fuer den Eigentuemer lesbar", (sl.DATEI.stat().st_mode & 0o077) == 0)
check("fehlgeschlagene Anmeldung traegt die Quelladresse",
      json.loads(zeilen[1]).get("ip") == "10.0.0.2")

# syslog
check("jedes Ereignis geht auch an syslog", len(gesendet) == 3)
# kein [1] auf eine evtl. leere Liste – das wirft, statt fehlzuschlagen
_sys_fehl = next((g for g in gesendet if '"anmeldung_fehlgeschlagen"' in g[1]), None)
check("syslog: Fehlschlag als Warnung", _sys_fehl is not None and _sys_fehl[0] == 30)
check("syslog-Text ist JSON mit Art und IP",
      _sys_fehl is not None and json.loads(_sys_fehl[1]).get("ip") == "10.0.0.2")

# Manipulation in der Mitte
roh = sl.DATEI.read_text().splitlines()
mitte = json.loads(roh[1]); mitte["ip"] = "1.2.3.4"
sl.DATEI.write_text("\n".join([roh[0], json.dumps(mitte), roh[2]]) + "\n")
r = sl.pruefen()
check("geaenderte Zeile wird erkannt", not r["ok"]
      and any(b["grund"] == "Inhalt veraendert" for b in r["brueche"]))
sl.DATEI.write_text("\n".join([roh[0], roh[2]]) + "\n")
r = sl.pruefen()
check("entfernte Zeile wird erkannt", not r["ok"]
      and any(b["grund"] == "Kette unterbrochen" for b in r["brueche"]))
# Zeile entfernen UND den Verweis der naechsten passend umbiegen: faellt nur auf,
# weil prev mit in den Hash eingeht
nach = json.loads(roh[2]); nach["prev"] = json.loads(roh[0])["hash"]
sl.DATEI.write_text("\n".join([roh[0], json.dumps(nach)]) + "\n")
check("entfernte Zeile mit umgebogenem Verweis wird erkannt", not sl.pruefen()["ok"])
sl.DATEI.write_text("\n".join(roh) + "\n")
sl._letzter_hash = None
check("nach Wiederherstellung wieder gruen", sl.pruefen()["ok"])

# Weiterschreiben nach Neustart (gemerkter Hash weg) haengt korrekt an
sl._letzter_hash = None
e4 = sl.ereignis("abmeldung", benutzer="anna", ip="10.0.0.1", ergebnis="erfolg")
check("nach Neustart: Kette setzt am letzten Hash der Datei an", e4["prev"] == e3["hash"])

# Frist: vorne abschneiden, Kette bleibt ab dem Anker gueltig
alt = [json.loads(z) for z in sl.DATEI.read_text().splitlines()]
for i, e in enumerate(alt):
    e["ts"] = 1000 + i          # 1000, 1001, 1002, 1003
    e["prev"] = alt[i - 1]["hash"] if i else sl.NULL_HASH
    e["hash"] = sl._hash(e["prev"], e)
sl.DATEI.write_text("".join(json.dumps(e) + "\n" for e in alt))
sl._letzter_hash = None
weg = sl.prune_older_than(1002)
r = sl.pruefen()
check("Frist entfernt genau die alten Zeilen", weg == 2 and r["zeilen"] == 2)
check("nach dem Kuerzen: Kette gueltig, Anker = Hash der letzten entfernten Zeile",
      r["ok"] and r["anker"] == alt[1]["hash"])
check("nach dem Kuerzen weiterhin nur fuer den Eigentuemer lesbar",
      (sl.DATEI.stat().st_mode & 0o077) == 0)
e5 = sl.ereignis("abmeldung", benutzer="x")
check("nach dem Kuerzen haengt das naechste Ereignis an die verbliebene Kette",
      e5["prev"] == alt[3]["hash"] and sl.pruefen()["ok"])

# Eine juengere Zeile zwischen alten (Uhr verstellt): nicht dahinter weiterschneiden
alt2 = [{"ts": 10}, {"ts": 5000}, {"ts": 20}]
prev = sl.NULL_HASH
for e in alt2:
    e["prev"] = prev; e["hash"] = sl._hash(prev, e); prev = e["hash"]
sl.DATEI.write_text("".join(json.dumps(e) + "\n" for e in alt2))
sl.prune_older_than(100)
check("Kuerzen stoppt an der ersten juengeren Zeile (kein Bruch mitten in der Kette)",
      sl.pruefen()["ok"] and sl.pruefen()["zeilen"] == 2)

# Aufbewahrung nur nach Alter, eigene Frist
os.environ.pop("JARVIS_SICHERHEITS_LOG_TAGE", None)
check("Vorgabe-Frist 365 Tage", sl.aufbewahrung_tage() == 365)
os.environ["JARVIS_SICHERHEITS_LOG_TAGE"] = "0"
check("0 = dauerhaft", sl.aufbewahrung_tage() == 0)
os.environ["JARVIS_SICHERHEITS_LOG_TAGE"] = "abc"
check("Unsinn -> Vorgabe, nicht 'dauerhaft'", sl.aufbewahrung_tage() == 365)
os.environ.pop("JARVIS_SICHERHEITS_LOG_TAGE", None)

# Schreibfehler kippt nichts
_vorher_datei = sl.DATEI
sperre = TMP / "keinordner"
sperre.write_text("x")
sl.DATEI = sperre / "s.jsonl"
sl._letzter_hash = None
_f = sl._fehler["datei"]
try:
    sl.ereignis("anmeldung", benutzer="z")
    geworfen = False
except Exception:  # noqa: BLE001
    geworfen = True
check("nicht schreibbares Protokoll wirft nicht, wird aber gezaehlt",
      not geworfen and sl._fehler["datei"] == _f + 1)
sl.DATEI = _vorher_datei
sl._letzter_hash = None

# Aufraeumlauf: eigene Frist, auch wenn die Telemetrie dauerhaft aufbewahrt wird
lr = importlib.import_module("backend.log_retention")
alt3 = [{"ts": 1}, {"ts": 2}]
prev = sl.NULL_HASH
for e in alt3:
    e["prev"] = prev; e["hash"] = sl._hash(prev, e); prev = e["hash"]
sl.DATEI.write_text("".join(json.dumps(e) + "\n" for e in alt3))
os.environ["JARVIS_LOG_RETENTION_DAYS"] = "0"
erg = lr.run_all()
os.environ.pop("JARVIS_LOG_RETENTION_DAYS", None)
check("Aufraeumlauf kuerzt das Sicherheitsprotokoll auch bei 'Telemetrie dauerhaft'",
      erg.get("removed", {}).get("sicherheits_log") == 2)

# ═══════════════════════════════════════════════════════════════════════════
print("\n[B] main.py: Anmeldung, Sperre, Admin-Aenderungen")
QUELLE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)


def _fn(name):
    fn = next((n for n in BAUM.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    if fn is None:
        abbruch("%s nicht in main.py" % name)
    return fn


def _ausfuehrbar(*namen, zuweisungen=()):
    teile = []
    for z in zuweisungen:
        n = next((n for n in BAUM.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == z for t in n.targets)), None)
        if n is None:
            abbruch("Zuweisung %s nicht in main.py" % z)
        teile.append(n)
    for name in namen:
        # KOPIE: Dekoratoren am geteilten Baum zu loeschen, machte jede spaetere
        # Pruefung "ist registriert" blind
        fn = copy.deepcopy(_fn(name))
        fn.decorator_list = []
        for a in fn.args.args + fn.args.kwonlyargs:
            a.annotation = None
        fn.returns = None
        teile.append(fn)
    mod = ast.Module(body=teile, type_ignores=[])
    ast.fix_missing_locations(mod)
    return compile(mod, "main.py<auszug>", "exec")


def _deko_namen(fn):
    aus = []
    for d in fn.decorator_list:
        if isinstance(d, ast.Name):
            aus.append(d.id)
        elif isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute):
            aus.append("%s.%s" % (getattr(d.func.value, "id", "?"), d.func.attr))
    return aus


EREIGNISSE: list = []


class _Protokoll:
    @staticmethod
    def ereignis(art, **k):
        EREIGNISSE.append(dict(art=art, **k))
        return {}


class _Antwort:
    def __init__(self, inhalt, status_code=200):
        self.body = json.dumps(inhalt).encode()
        self.status_code = status_code


class _Client:
    def __init__(self, host):
        self.host = host


class _Url:
    def __init__(self, pfad, query=""):
        self.path = pfad
        self.query = query


class _Req:
    def __init__(self, body=None, ip="10.9.8.7", methode="POST", pfad="/api/login", query=""):
        self._body = body or {}
        self.client = _Client(ip)
        self.method = methode
        self.url = _Url(pfad, query)
        self.headers = {}

    async def json(self):
        return self._body


SK = contextvars.ContextVar("_sk", default=None)
AA = contextvars.ContextVar("_aa", default=None)
# Attrappe der Spruehlage in der Form von anmelde_schutz.sprueh_neu_melden:
# genau EINMAL ein Dict, danach None.
SPRUEH: list = []
NS = {
    "json": json, "Request": object,
    "_sicherheits_log": _Protokoll,
    "_sitzung_kontext": SK, "_admin_anfrage": AA,
    "_norm_login": lambda n: (n or "").split("@")[0].split("\\")[-1].strip().lower(),
    "_anmelde_schutz": types.SimpleNamespace(fehlversuch=lambda ip, konto: konto == "opfer",
                                             KONTO_SPERRE_S=900,
                                             sprueh_neu_melden=lambda: SPRUEH.pop(0) if SPRUEH else None,
                                             SPRUEH_FENSTER_S=600, SPRUEH_ABSTAND_S=2.0),
    "time": time,
}
exec(_ausfuehrbar("_antwort_json", "_anmeldung_protokollieren", "_record_login_attempt",
                  "_admin_pruefung_merken", "_sicherheits_protokoll_mw",
                  zuweisungen=("_AENDERNDE_METHODEN", "_KONTO_PFADE")), NS)
prot = NS["_anmeldung_protokollieren"]

# Anmeldung: jeder entschiedene Ausgang, mit IP
EREIGNISSE.clear()
asyncio.run(prot(_Req({"username": "Anna", "password": "geheim"}, ip="10.1.1.1"),
                 _Antwort({"success": True, "username": "anna"}), "kennwort"))
if not EREIGNISSE:
    abbruch("Positivkontrolle: erfolgreiche Anmeldung erzeugt kein Ereignis")
check("erfolgreiche Anmeldung: Art, Benutzer, IP",
      EREIGNISSE[-1]["art"] == "anmeldung" and EREIGNISSE[-1]["benutzer"] == "anna"
      and EREIGNISSE[-1]["ip"] == "10.1.1.1")
check("das Kennwort steht nicht im Protokoll", "geheim" not in json.dumps(EREIGNISSE))
EREIGNISSE.clear()
asyncio.run(prot(_Req({"username": "bert"}, ip="10.2.2.2"),
                 _Antwort({"success": False, "error": "Benutzername oder Passwort falsch"}, 401),
                 "kennwort"))
check("fehlgeschlagene Anmeldung: Art, IP, Status, Grund",
      len(EREIGNISSE) == 1 and EREIGNISSE[0]["art"] == "anmeldung_fehlgeschlagen"
      and EREIGNISSE[0]["ip"] == "10.2.2.2" and EREIGNISSE[0]["ergebnis"] == "401"
      and "falsch" in EREIGNISSE[0].get("grund", ""))
EREIGNISSE.clear()
asyncio.run(prot(_Req({"username": "carl"}),
                 _Antwort({"success": False, "error": "Zu viele"}, 429), "kennwort"))
check("Sperrantwort (429) zaehlt als fehlgeschlagen", len(EREIGNISSE) == 1
      and EREIGNISSE[0]["art"] == "anmeldung_fehlgeschlagen")
EREIGNISSE.clear()
asyncio.run(prot(_Req({"username": "dora"}),
                 _Antwort({"success": False, "requires_totp": True}), "kennwort"))
check("Rueckfrage nach dem zweiten Faktor ist kein Ereignis", EREIGNISSE == [])
EREIGNISSE.clear()
asyncio.run(prot(_Req({}), _Antwort({"ok": True, "username": "emil"}), "outlook_sso"))
check("SSO-Erfolg (ok statt success) wird erkannt",
      len(EREIGNISSE) == 1 and EREIGNISSE[0]["benutzer"] == "emil"
      and EREIGNISSE[0].get("weg") == "outlook_sso")

# Kontosperre
EREIGNISSE.clear()
NS["_record_login_attempt"]("10.3.3.3", "Opfer")
NS["_record_login_attempt"]("10.3.3.3", "anderer")
check("Kontosperre wird protokolliert (nur wenn sie DADURCH entsteht)",
      len(EREIGNISSE) == 1 and EREIGNISSE[0]["art"] == "konto_gesperrt"
      and EREIGNISSE[0]["benutzer"] == "opfer" and EREIGNISSE[0]["ip"] == "10.3.3.3")


# Spruehangriff: EINMAL protokolliert (Password Spraying, 2026-10-15)
EREIGNISSE.clear()
SPRUEH.append({"seit": 1, "bis": 2000000000, "konten": 12})
NS["_record_login_attempt"]("10.4.4.4", "x1")
NS["_record_login_attempt"]("10.4.4.5", "x2")
_sp = [e for e in EREIGNISSE if e["art"] == "spruehangriff"]
check("Spruehangriff wird genau EINMAL protokolliert, mit Kontenzahl",
      len(_sp) == 1 and _sp[0].get("konten") == 12 and _sp[0]["ip"] == "10.4.4.4")


# Verdrahtung am Syntaxbaum: der Anmeldeweg hat EINEN Ausgang ueber das Protokoll
def _ruft(fn, name):
    return [k for k in ast.walk(fn) if isinstance(k, ast.Call)
            and isinstance(k.func, ast.Name) and k.func.id == name]


for route, ablauf, weg in (("login", "_login_ablauf", "kennwort"),
                           ("addin_sso", "_addin_sso_ablauf", "outlook_sso")):
    f = _fn(route)
    rueck = [n for n in ast.walk(f) if isinstance(n, ast.Return)]
    prot_aufrufe = _ruft(f, "_anmeldung_protokollieren")
    check("%s: Route ruft %s und protokolliert '%s'" % (route, ablauf, weg),
          len(_ruft(f, ablauf)) == 1 and len(prot_aufrufe) == 1
          and any(isinstance(a, ast.Constant) and a.value == weg for a in prot_aufrufe[0].args))
    check("%s: genau ein return, und der gibt die protokollierte Antwort zurueck" % route,
          len(rueck) == 1 and isinstance(rueck[0].value, ast.Name)
          and rueck[0].value.id == prot_aufrufe[0].args[1].id if prot_aufrufe else False)
    check("%s: ist als Route registriert, %s nicht" % (route, ablauf),
          any(d.startswith("app.") for d in _deko_namen(f)) and not _deko_namen(_fn(ablauf)))

lo = _fn("logout")
check("logout schreibt 'abmeldung' ins Protokoll",
      any(isinstance(k.func, ast.Attribute) and k.func.attr == "ereignis"
          and k.args and isinstance(k.args[0], ast.Constant) and k.args[0].value == "abmeldung"
          for k in ast.walk(lo) if isinstance(k, ast.Call)))
check("_user_is_admin traegt den Dekorator _admin_pruefung_merken",
      "_admin_pruefung_merken" in _deko_namen(_fn("_user_is_admin")))
check("die Middleware ist registriert",
      "app.middleware" in _deko_namen(_fn("_sicherheits_protokoll_mw")))
vt = _fn("verify_token")
check("verify_token meldet die Sitzung an den Halter",
      any(isinstance(n, ast.Attribute) and n.attr == "setdefault" for n in ast.walk(vt))
      and any(isinstance(n, ast.Name) and n.id == "_admin_anfrage" for n in ast.walk(vt)))

# Middleware AUSGEFUEHRT – der Endpunkt laeuft wie bei Starlette in einer
# eigenen Task bzw. im Threadpool (Kontext-KOPIE): ein neu gesetzter Wert kaeme
# dort nicht zurueck, nur die Aenderung am Halter.
mw = NS["_sicherheits_protokoll_mw"]
ist_admin = NS["_admin_pruefung_merken"](lambda u: u == "jarvis")


THREADS: set = set()


def _endpunkt(nutzer, status, admin_pruefen=True, sitzung=True):
    def innen():
        THREADS.add(threading.get_ident())
        if sitzung:
            SK.set((nutzer, True, False))
            h = AA.get()
            if h is not None:
                h.setdefault("sitzung", nutzer)
        if admin_pruefen:
            ist_admin(nutzer)
        return _Antwort({}, status)

    async def call_next(_req):
        return await asyncio.create_task(asyncio.to_thread(innen))
    return call_next


def _lauf(req, call_next):
    EREIGNISSE.clear()
    asyncio.run(mw(req, call_next))
    return list(EREIGNISSE)


ev = _lauf(_Req(methode="POST", pfad="/api/settings", query="token=GEHEIM", ip="10.4.4.4"),
           _endpunkt("jarvis", 200))
if not THREADS or threading.get_ident() in THREADS:
    abbruch("Positivkontrolle: der Endpunkt lief nicht in einem eigenen Thread "
            "(der Messaufbau stellt die Kontext-Kopie nicht her)")
check("Admin-Aenderung: Art, Benutzer, IP, Methode, Pfad",
      len(ev) == 1 and ev[0]["art"] == "admin_aenderung" and ev[0]["benutzer"] == "jarvis"
      and ev[0]["ip"] == "10.4.4.4" and ev[0]["methode"] == "POST"
      and ev[0]["pfad"] == "/api/settings")
check("Query (Tokens) steht nicht im Protokoll", "GEHEIM" not in json.dumps(ev))
ev = _lauf(_Req(methode="DELETE", pfad="/api/skills/x"), _endpunkt("bert", 403))
check("verweigerte Admin-Aktion: admin_verweigert",
      len(ev) == 1 and ev[0]["art"] == "admin_verweigert" and ev[0]["benutzer"] == "bert")
ev = _lauf(_Req(methode="POST", pfad="/api/chat"), _endpunkt("bert", 200))
check("Nicht-Admin ohne Admin-Bezug: nichts", ev == [])
ev = _lauf(_Req(methode="GET", pfad="/api/settings"), _endpunkt("jarvis", 200))
check("lesende Anfrage: nichts", ev == [])
ev = _lauf(_Req(methode="POST", pfad="/api/change-password", ip="10.5.5.5"),
           _endpunkt("bert", 401, admin_pruefen=False))
check("Kennwortwechsel (auch fehlgeschlagen): konto_aenderung mit Benutzer",
      len(ev) == 1 and ev[0]["art"] == "konto_aenderung" and ev[0]["benutzer"] == "bert"
      and ev[0]["ergebnis"] == "401")
ev = _lauf(_Req(methode="POST", pfad="/api/auth/totp/disable"),
           _endpunkt("bert", 200, admin_pruefen=False))
check("2FA abschalten: konto_aenderung", len(ev) == 1 and ev[0]["art"] == "konto_aenderung")


# Admin-Pruefung ueber ein FREMDES Konto zaehlt nicht fuer den Anfragenden
def _fremd():
    def innen():
        SK.set(("bert", True, False))
        ist_admin("jarvis")
        return _Antwort({}, 200)

    async def call_next(_req):
        return await asyncio.to_thread(innen)
    return call_next


ev = _lauf(_Req(methode="POST", pfad="/api/irgendwas"), _fremd())
check("Admin-Pruefung ueber ein fremdes Konto macht die Anfrage nicht zur Admin-Aenderung",
      ev == [])

# ═══════════════════════════════════════════════════════════════════════════
print("\n[C] systemd-Haertung (Installationsskript ausgefuehrt)")
SKRIPT = ROOT / "deploy" / "security" / "haertung_installieren.sh"
if not SKRIPT.exists():
    abbruch("haertung_installieren.sh fehlt")


def _installieren(user="jarvis", conf=""):
    d = TMP / ("inst_" + user + ("_aus" if conf else ""))
    shutil.rmtree(d, ignore_errors=True)
    (d / "units").mkdir(parents=True)
    (d / "logrotate").mkdir()
    (d / "units" / "jarvis.service").write_text(
        "[Service]\nUser=%s\nGroup=%s\nExecStart=/opt/jarvis/start_jarvis.sh\n" % (user, user))
    if conf:
        (d / "broker.conf").write_text(conf)
    env = dict(os.environ, JARVIS_HAERTUNG_TEST="1", JARVIS_UNIT_DIR=str(d / "units"),
               JARVIS_LOGROTATE_DIR=str(d / "logrotate"),
               JARVIS_BROKER_CONF=str(d / "broker.conf"),
               JARVIS_BROKER_AUDIT="/var/log/jarvis-broker-audit.jsonl")
    r = subprocess.run(["bash", str(SKRIPT), "/opt/jarvis"], env=env, capture_output=True,
                       text=True, timeout=30)
    return d, r, env


def _direktiven(pfad: Path) -> dict:
    """Schluessel=Wert aus einer Unit-Datei (Kommentare und Abschnitte weg)."""
    aus: dict = {}
    if not pfad.exists():
        return aus
    for z in pfad.read_text().splitlines():
        z = z.strip()
        if not z or z.startswith(("#", ";", "[")) or "=" not in z:
            continue
        k, v = z.split("=", 1)
        aus.setdefault(k.strip(), []).append(v.strip())
    return aus


d, r, env = _installieren()
be = _direktiven(d / "units" / "jarvis.service.d" / "50-haertung.conf")
br = _direktiven(d / "units" / "jarvis-broker.service.d" / "50-haertung.conf")
if r.returncode != 0 or len(be) < 8:
    abbruch("Positivkontrolle: Skript lief nicht oder schrieb kaum etwas (rc=%s, %d Direktiven): %s"
            % (r.returncode, len(be), r.stderr[-300:]))
check("Backend: ProtectSystem=strict", be.get("ProtectSystem") == ["strict"])
rw = " ".join(be.get("ReadWritePaths", [])).split()
check("Backend: schreibbar bleiben Projektbaum, Home, /tmp",
      "/opt/jarvis" in rw and "/tmp" in rw and any(p.lstrip("-").endswith("/jarvis")
                                                    and "home" in p for p in rw))
check("Backend: nur CAP_NET_BIND_SERVICE im Bounding-Set",
      be.get("CapabilityBoundingSet") == ["CAP_NET_BIND_SERVICE"])
check("Backend: Adressfamilien begrenzt (ohne AF_PACKET)",
      bool(be.get("RestrictAddressFamilies"))
      and "AF_PACKET" not in be["RestrictAddressFamilies"][0]
      and "AF_UNIX" in be["RestrictAddressFamilies"][0])
for k in ("ProtectKernelModules", "ProtectControlGroups", "LockPersonality",
          "RestrictRealtime", "SystemCallArchitectures", "SystemCallFilter"):
    check("Backend: %s gesetzt" % k, k in be)
# gemessen: brechen lokale Anmeldung (unix_chkpwd) bzw. bwrap (MCP, Shell-Sandbox)
for k in ("NoNewPrivileges", "ProtectKernelTunables", "ProtectKernelLogs", "RestrictSUIDSGID",
          "PrivateTmp", "RestrictNamespaces", "MemoryDenyWriteExecute", "ProtectProc",
          "PrivateDevices", "ProtectClock", "RemoveIPC", "ProtectHostname"):
    check("Backend: %s NICHT gesetzt (bricht nachweislich etwas)" % k,
          k not in be and k not in br)
check("Broker: Drop-in vorhanden", len(br) >= 3)
check("Broker: kein Bounding-Set / ProtectSystem (Root-Aufgaben)",
      "CapabilityBoundingSet" not in br and "ProtectSystem" not in br and "UMask" not in br)

lr_regel = (d / "logrotate" / "jarvis-broker-audit").read_text()
lr_w = {}
for z in lr_regel.splitlines():
    t = z.strip().split()
    if t and not t[0].startswith("#") and t[0] not in ("{", "}") and not t[0].startswith("/"):
        lr_w[t[0]] = t[1:]
check("Audit-Rotation: Datei des Brokers", "/var/log/jarvis-broker-audit.jsonl {" in lr_regel)
check("Audit-Rotation: Loeschen nach Alter (maxage 365)", lr_w.get("maxage") == ["365"])
taktage = {"daily": 1, "weekly": 7, "monthly": 31}
takt = next((taktage[k] for k in taktage if k in lr_w), None)
anzahl = int((lr_w.get("rotate") or ["0"])[0])
check("Audit-Rotation: Stueckzahl greift nie vor dem Alter",
      takt is not None and anzahl * takt >= 365)
check("Audit-Rotation: keine Groessen-Rotation",
      not any(k in lr_w for k in ("size", "maxsize", "minsize")))
check("Audit-Rotation: juengste Vorgaengerdatei bleibt lesbar (delaycompress)",
      "delaycompress" in lr_w)
check("Audit-Rotation: neue Datei 0600 root", lr_w.get("create") == ["0600", "root", "root"])

r2 = subprocess.run(["bash", str(SKRIPT), "/opt/jarvis"], env=env, capture_output=True,
                    text=True, timeout=30)
check("zweiter Lauf schreibt nichts (idempotent)", "geschrieben" not in r2.stdout)

d_root, r_root, _ = _installieren(user="root")
check("Alt-Betrieb (Backend als root): keine Backend-Haertung, Broker schon",
      not (d_root / "units" / "jarvis.service.d" / "50-haertung.conf").exists()
      and (d_root / "units" / "jarvis-broker.service.d" / "50-haertung.conf").exists())

# Notausgang: erst an, dann HAERTUNG=aus
d_aus, _, env_aus = _installieren(conf="QUELLE=github\n")
(d_aus / "broker.conf").write_text("QUELLE=github\nHAERTUNG=aus\n")
subprocess.run(["bash", str(SKRIPT), "/opt/jarvis"], env=env_aus, capture_output=True,
               text=True, timeout=30)
check("HAERTUNG=aus entfernt beide Drop-ins",
      not (d_aus / "units" / "jarvis.service.d" / "50-haertung.conf").exists()
      and not (d_aus / "units" / "jarvis-broker.service.d" / "50-haertung.conf").exists())

# Einbindung: der Broker schreibt die Haertung bei jedem Start, aus seiner Kopie
start = (ROOT / "start_jarvis_root.sh").read_text().splitlines()
aufruf = [i for i, z in enumerate(start)
          if not z.lstrip().startswith("#") and "haertung_installieren.sh" in z
          and z.strip().startswith("bash ")]
broker_start = next((i for i, z in enumerate(start) if z.startswith("# 7.")), None)
check("start_jarvis_root.sh ruft das Skript aus \"$CODE_DIR\" auf",
      bool(aufruf) and "$CODE_DIR/deploy/security/haertung_installieren.sh" in start[aufruf[0]])
check("…und zwar vor dem Start des Brokers",
      bool(aufruf) and broker_start is not None and aufruf[0] < broker_start)
inst = (ROOT / "deploy" / "security" / "broker_installieren.sh").read_text()
check("die root-eigene Kopie enthaelt deploy/ (dort liegt das Skript)",
      any("backend deploy" in z and "tar" in inst for z in inst.splitlines()))
setup = (ROOT / "deploy" / "security" / "setup_broker.sh").read_text().splitlines()
check("setup_broker.sh installiert die Haertung mit",
      any(z.strip().startswith("bash ") and "haertung_installieren.sh" in z for z in setup))

# ═══════════════════════════════════════════════════════════════════════════
print("\n[D] Broker-Audit liest ueber die Rotation hinweg")
os.environ["JARVIS_BROKER_AUDIT"] = str(TMP / "audit.jsonl")
sys.modules.pop("backend.broker.policy", None)
pol = importlib.import_module("backend.broker.policy")
if not str(pol.AUDIT_FILE).startswith(str(TMP)):
    abbruch("Broker-Audit zeigt aus dem Sandkasten heraus")
(TMP / "audit.jsonl.1").write_text("".join(json.dumps({"n": i}) + "\n" for i in range(5)))
(TMP / "audit.jsonl").write_text("".join(json.dumps({"n": i}) + "\n" for i in range(5, 8)))
t = pol.audit_tail(6)
check("kurze aktuelle Datei wird aus .1 aufgefuellt (neueste zuletzt)",
      [e["n"] for e in t] == [2, 3, 4, 5, 6, 7])
t = pol.audit_tail(2)
check("reicht die aktuelle Datei, bleibt .1 aussen vor", [e["n"] for e in t] == [6, 7])
(TMP / "audit.jsonl").unlink()
check("direkt nach dem Drehen (aktuelle Datei fehlt): .1 wird gelesen",
      [e["n"] for e in pol.audit_tail(3)] == [2, 3, 4])

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
