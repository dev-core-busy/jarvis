#!/usr/bin/env python3
"""Waechter: Code-Review 2026-10-07, NIEDRIG – Sitzung und Widerruf.

Befunde und was gemessen wird (alles an der WIRKUNG, echte Funktionen aus
main.py per AST, echte Module, Attrappen in echter Signatur):

  [1] sitzung_token: eine unlesbare Ablage startete LEER – abgemeldete Tokens
      galten nach einem Absturz mitten im Schreiben wieder. Jetzt: kein Token
      von vor dem Laden gilt, und das bleibt ueber einen Neustart so.
      Dazu ``sitzung_besteht`` (fuer den Abruf-Schluessel).
  [2] main._load/_save_revocations: dasselbe fuer die Epochen; Speichern
      atomar (ein Fehler mitten im Schreiben laesst die alte Datei stehen).
  [3] /api/verify-token meldete bis zu 30 Tage Restlaufzeit.
  [4] require_admin_or_query liess gesperrte Konten durch.
  [5] /ws/users pruefte das Token nur bei der ersten Nachricht – Abmelden
      beendete die offene Verbindung nicht (weder beim Senden noch still).
  [6] sicherheits_log: Hash-Kette ohne Schluessel liess sich nach einer
      Aenderung in der Mitte neu rechnen.

    python3 tests/test_review_niedrig_sitzung.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import contextvars
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % (detail,)) if detail else ""))


def abbruch(grund):
    print("\n\033[31mABBRUCH\033[0m: %s" % grund)
    sys.exit(2)


# backend.config NUR als Stub – der echte Import schreibt die Live-settings.json
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules.setdefault("backend.config", _cfg)

TMP = Path(tempfile.mkdtemp(prefix="waechter-review-niedrig-"))
from backend import sitzung_token as st  # noqa: E402
from backend import sicherheits_log as SL  # noqa: E402

st.STORE_PATH = TMP / "auth_sitzungen.json"
st.einstellungen_quelle(lambda k, d=None: d)
H = 3600

# ─── [1] sitzung_token ───────────────────────────────────────────────────────
print("\n\033[1m[1] sitzung_token: unlesbare Ablage = fail-closed\033[0m")
st._zuruecksetzen_fuer_test()
jetzt = time.time()
alt_ts = int(jetzt - 60)
st.neu("alt", alt_ts)
st.flush()
st._zuruecksetzen_fuer_test()
check("Positivkontrolle: nach Neustart mit lesbarer Ablage gilt das Token",
      st.pruefe_und_beruehre("alt", alt_ts))
st.widerrufe("alt", alt_ts)
st._zuruecksetzen_fuer_test()
check("Positivkontrolle: abgemeldet bleibt abgemeldet (lesbare Ablage)",
      not st.pruefe_und_beruehre("alt", alt_ts))
st.STORE_PATH.write_text('{"zuletzt": {"abgeschnitten', encoding="utf-8")
st._zuruecksetzen_fuer_test()
check("⚠ unlesbare Ablage: das abgemeldete Token gilt NICHT wieder",
      not st.pruefe_und_beruehre("alt", alt_ts))
check("⚠ … auch kein anderes vorher ausgestelltes",
      not st.pruefe_und_beruehre("anderes", alt_ts))
neu_ts = int(time.time()) + 1
check("Positivkontrolle: ein danach ausgestelltes Token gilt", st.pruefe_und_beruehre("neu", neu_ts))
check("die kaputte Datei bleibt zur Untersuchung liegen",
      any(p.name.startswith("auth_sitzungen.json.kaputt.") for p in TMP.iterdir()))
st._zuruecksetzen_fuer_test()
check("⚠ die Sperre ueberlebt den naechsten Neustart (steht in der Ablage)",
      not st.pruefe_und_beruehre("anderes", alt_ts))

st._zuruecksetzen_fuer_test()
st.STORE_PATH.unlink()
k = st.schluessel("lebt")
check("sitzung_besteht: lebende Sitzung", st.sitzung_besteht(k, int(time.time()) - 60))
st.widerrufe("lebt", int(time.time()) - 60)
check("sitzung_besteht: abgemeldet -> nein", not st.sitzung_besteht(k, int(time.time()) - 60))
check("sitzung_besteht: aelter als die Laufzeit -> nein",
      not st.sitzung_besteht(st.schluessel("x"), int(time.time()) - 13 * H))

# ─── main.py schneiden ───────────────────────────────────────────────────────
MAIN = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
FN = {n.name: n for n in MAIN.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def schneide(ns, *namen):
    for name in namen:
        if name not in FN:
            abbruch("main.py: %s fehlt" % name)
        k = ast.parse(ast.unparse(FN[name])).body[0]
        k.decorator_list = []
        for a in k.args.args + k.args.kwonlyargs:
            a.annotation = None
        k.returns = None
        k.args.defaults = [ast.Constant(None) for _ in k.args.defaults]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[k], type_ignores=[])),
                     "<main:%s>" % name, "exec"), ns)
    return ns


class _HTTPExc(Exception):
    def __init__(self, status_code=0, detail=""):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class _JR:
    def __init__(self, content, status_code=200):
        self.content, self.status_code = content, status_code


# ─── [2] Epochen ─────────────────────────────────────────────────────────────
print("\n\033[1m[2] Widerrufs-Epochen: fail-closed und atomar\033[0m")
st._zuruecksetzen_fuer_test()
st.STORE_PATH.unlink(missing_ok=True)
NS = schneide({
    "time": time, "hmac": hmac, "hashlib": hashlib, "json": json, "os": os,
    "config": types.SimpleNamespace(SECRET_KEY="k" * 64),
    "_sitzung": st, "_revoked_logins": {}, "_WIDERRUF_ALLE": "*",
    "_REVOKED_FILE": TMP / "auth_revocations.json",
    "_norm_login": lambda n: (n or "").split("\\")[-1].lower(),
    "_sitzung_kontext": contextvars.ContextVar("_sk", default=None),
    "_sitzung_herkunft": contextvars.ContextVar("_sh", default=None),
    "_admin_anfrage": contextvars.ContextVar("_aa", default=None),
}, "generate_token", "verify_token", "_epoche_widerrufen", "_load_revocations",
   "_save_revocations")
RF = NS["_REVOKED_FILE"]
t_alt = NS["generate_token"]("anna", ts=int(time.time()) - 120)
check("Positivkontrolle: Token gilt ohne Widerrufsdatei", NS["verify_token"](t_alt) == "anna")
RF.write_text('{"anna": 17', encoding="utf-8")
NS["_load_revocations"]()
check("⚠ unlesbare Widerrufsdatei: vorher ausgestelltes Token gilt NICHT",
      NS["verify_token"](t_alt) is None)
t_neu = NS["generate_token"]("anna", ts=int(time.time()) + 1)
check("Positivkontrolle: neu ausgestelltes Token gilt", NS["verify_token"](t_neu) == "anna")
check("die kaputte Datei bleibt liegen",
      any(p.name.startswith("auth_revocations.json.kaputt.") for p in TMP.iterdir()))
try:
    roh = json.loads(RF.read_text())
except Exception:  # noqa: BLE001
    roh = {}
check("die Sperre steht wieder lesbar auf Platte", "*" in roh, roh)

NS["_revoked_logins"].clear()
NS["_revoked_logins"]["bert"] = int(time.time())
NS["_save_revocations"]()
check("Positivkontrolle: gespeichert", "bert" in RF.read_text())
_echt_dumps = json.dumps
NS["json"] = types.SimpleNamespace(dumps=lambda o: "\udcff", loads=json.loads)  # Schreibfehler
NS["_revoked_logins"]["carl"] = int(time.time())
NS["_save_revocations"]()
NS["json"] = json
try:
    nach = json.loads(RF.read_text())
except Exception:  # noqa: BLE001
    nach = None
check("⚠ Fehler mitten im Schreiben: die alte Datei steht unversehrt",
      isinstance(nach, dict) and "bert" in nach, RF.read_text()[:80])
check("… und kein halbes tmp bleibt neben der Datei liegen",
      not [x.name for x in TMP.iterdir() if x.name.startswith("auth_revocations.json.")
           and x.name.endswith(".tmp")], [x.name for x in TMP.iterdir()])

# ─── [3] verify-token ────────────────────────────────────────────────────────
print("\n\033[1m[3] /api/verify-token: Restlaufzeit\033[0m")


class _Req:
    def __init__(self, body):
        self._b = body
        self.cookies = {}    # wie Starlette: ohne Sitzungs-Cookie (BSI H4)

    async def json(self):
        return self._b


ns3 = schneide({"JSONResponse": _JR, "Request": _Req, "time": time, "_sitzung": st,
                "verify_token": lambda t: "anna", "_user_must_change": lambda u: False,
                "_is_admin_user": lambda u: False,
                "_sitzung_cookie": __import__("backend.sitzung_cookie", fromlist=["x"])},
               "_token_aufloesen", "verify_token_endpoint")
r = asyncio.run(ns3["verify_token_endpoint"](_Req({"token": "anna:%d:x" % (int(time.time()) - H)})))
rest = r.content.get("remaining_seconds", -1)
check("Positivkontrolle: gueltig", r.content.get("valid") is True)
check("⚠ 1 h altes Token: Rest ~11 h, nicht ~30 Tage (%s s)" % rest,
      11 * H - 120 <= rest <= 11 * H + 5, rest)
check("Leerlauf getrennt gemeldet", r.content.get("idle_seconds") == st.leerlauf_s())

# ─── [4] require_admin_or_query ──────────────────────────────────────────────
print("\n\033[1m[4] require_admin_or_query: gesperrte Konten\033[0m")
GESPERRT, MUSS = set(), set()
ns4 = schneide({"HTTPException": _HTTPExc, "Request": object,
                "verify_token": lambda t: "chef" if t == "TOK" else None,
                "_query_benutzer": lambda r: None, "_prot_abruf_abgewiesen": lambda r: None,
                "_user_is_admin": lambda u: True, "_login_still_allowed": lambda u: True,
                "_user_must_change": lambda u: u in MUSS,
                "security_guard": types.SimpleNamespace(is_blocked=lambda u: u in GESPERRT)},
               "require_admin_or_query")
req = types.SimpleNamespace(headers={"Authorization": "Bearer TOK"}, query_params={})


def admin_lauf():
    try:
        return asyncio.run(ns4["require_admin_or_query"](req))
    except _HTTPExc as e:
        return e.status_code


check("Positivkontrolle: Admin kommt durch", admin_lauf() == "chef", admin_lauf())
GESPERRT.add("chef")
check("⚠ gesperrter Admin -> 403", admin_lauf() == 403, admin_lauf())
GESPERRT.clear()
MUSS.add("chef")
check("⚠ Kennwortwechsel ausstehend -> 403", admin_lauf() == 403, admin_lauf())
MUSS.clear()

# ─── [5] /ws/users ───────────────────────────────────────────────────────────
print("\n\033[1m[5] /ws/users: Widerruf beendet die offene Verbindung\033[0m")


class _Zu(Exception):
    pass


class FakeWS:
    def __init__(self):
        self.ein = asyncio.Queue()
        self.raus, self.zu = [], False

    async def accept(self):
        pass

    async def receive_json(self):
        if self.zu:
            raise _Zu()
        d = await self.ein.get()
        if d is None:
            raise _Zu()
        return d

    async def send_json(self, d):
        self.raus.append(d)

    async def close(self, code=1000):
        self.zu = True
        self.ein.put_nowait(None)


GUELTIG = {"TOK_A"}
ZUGESTELLT = []


async def _send(ws, m):
    await ws.send_json(m)


async def _an_user(u, m):
    ZUGESTELLT.append((u, m.get("text")))


ns5 = {"asyncio": asyncio, "time": time, "uuid": __import__("uuid"), "WebSocket": object,
       "_UC_SKILL": "userchat", "_skill_active": lambda s: True,
       "verify_token": lambda t: "anna" if t in GUELTIG else None,
       "_user_must_change": lambda u: False, "_login_still_allowed": lambda u: True,
       "security_guard": types.SimpleNamespace(is_blocked=lambda u: False),
       "_norm_login": lambda n: (n or "").lower(), "_uc_clients": {}, "_uc_history": {},
       "_uc_send": _send, "_uc_send_to_user": _an_user,
       "_uc_broadcast_presence": (lambda: asyncio.sleep(0)),
       "_uc_attachment_max_b64": lambda: 10 ** 6, "_uc_conv_key": lambda a, b: a + "__" + b,
       "_uc_history_max": lambda: 100, "_uc_save_history": lambda: None, "_UC_PRUEF_S": 30,
       # BSI H4: userchat_ws loest das Token ueber _token_aufloesen auf – das ECHTE
       # Modul, keine Attrappe (ein Klartext-Token geht unveraendert durch)
       "_sitzung_cookie": __import__("backend.sitzung_cookie", fromlist=["x"])}
schneide(ns5, "_token_aufloesen", "_uc_sitzung_ungueltig", "_uc_sitzung_beenden", "_uc_waechter",
         "userchat_ws")


async def ws_lauf(still: bool):
    ws = FakeWS()
    t = asyncio.ensure_future(ns5["userchat_ws"](ws))
    await ws.ein.put({"token": "TOK_A"})
    await ws.ein.put({"type": "dm", "to": "bert", "text": "vorher"})
    await asyncio.sleep(0.05)
    GUELTIG.discard("TOK_A")                    # Abmelden / Kennwortwechsel
    if not still:
        await ws.ein.put({"type": "dm", "to": "bert", "text": "nachher"})
    try:
        await asyncio.wait_for(t, 2.0)
        fertig = True
    except asyncio.TimeoutError:
        t.cancel()
        fertig = False
    GUELTIG.add("TOK_A")
    return ws, fertig


ZUGESTELLT.clear()
ws, fertig = asyncio.run(ws_lauf(still=False))
check("Positivkontrolle: vor dem Widerruf wird zugestellt", ("bert", "vorher") in ZUGESTELLT,
      ZUGESTELLT)
check("⚠ nach dem Widerruf: die naechste Nachricht wird NICHT zugestellt",
      ("bert", "nachher") not in ZUGESTELLT, ZUGESTELLT)
check("⚠ … die Verbindung endet mit session_invalid",
      fertig and any(m.get("type") == "session_invalid" for m in ws.raus),
      (fertig, [m.get("type") for m in ws.raus]))
ns5["_UC_PRUEF_S"] = 0.05
ZUGESTELLT.clear()
ws, fertig = asyncio.run(ws_lauf(still=True))
check("⚠ ohne eigene Nachricht: der Waechter schliesst die Verbindung",
      fertig and ws.zu and any(m.get("type") == "session_invalid" for m in ws.raus),
      (fertig, ws.zu, [m.get("type") for m in ws.raus]))

# ─── [6] sicherheits_log ─────────────────────────────────────────────────────
print("\n\033[1m[6] Sicherheitsprotokoll: Kette mit Schluessel\033[0m")
SL.DATEI = TMP / "sicherheit.jsonl"
SL._letzter_hash = SL._letzte_datei = None
SL._syslog_logger = lambda: None
SL.schluessel_setzen("geheim" * 8)
for i in range(4):
    SL.ereignis("anmeldung", benutzer="u%d" % i, ergebnis="ok")
p = SL.pruefen(SL.DATEI)
check("Positivkontrolle: frische Kette ok (%d Zeilen)" % p["zeilen"], p["ok"] and p["zeilen"] == 4, p)
zeilen = [json.loads(z) for z in SL.DATEI.read_text().splitlines()]
check("jede Zeile traegt das Merkmal mac", all(z.get("mac") == 1 for z in zeilen))


def neu_rechnen_ohne_schluessel(zeilen, mac_weg):
    prev = zeilen[0]["prev"]
    raus = []
    for z in zeilen:
        z = dict(z)
        if mac_weg:
            z.pop("mac", None)
        z["prev"] = prev
        ohne = {k: v for k, v in z.items() if k != "hash"}
        if z.get("mac"):
            # ein Angreifer ohne Schluessel kann nur raten
            z["hash"] = hashlib.sha256((prev + SL._kanonisch(ohne)).encode()).hexdigest()
        else:
            z["hash"] = hashlib.sha256((prev + SL._kanonisch(ohne)).encode()).hexdigest()
        prev = z["hash"]
        raus.append(json.dumps(z, ensure_ascii=False))
    return "\n".join(raus) + "\n"


manip = [dict(z) for z in zeilen]
manip[1]["benutzer"] = "jemand_anders"
SL.DATEI.write_text(neu_rechnen_ohne_schluessel(manip, mac_weg=False))
check("⚠ Zeile in der Mitte geaendert, Kette ohne Schluessel neu gerechnet -> Bruch",
      not SL.pruefen(SL.DATEI)["ok"])
SL.DATEI.write_text(neu_rechnen_ohne_schluessel(manip, mac_weg=True))
p = SL.pruefen(SL.DATEI)
check("⚠ … auch wenn das Merkmal ueberall entfernt wurde -> Bruch", not p["ok"], p)
# Altbestand ohne Schluessel bleibt pruefbar; danach geschriebene Zeilen tragen ihn
SL.schluessel_setzen("")
SL.DATEI.unlink()
SL._letzter_hash = SL._letzte_datei = None
SL.ereignis("anmeldung", benutzer="alt")
SL.schluessel_setzen("geheim" * 8)
SL._letzter_hash = SL._letzte_datei = None
SL.ereignis("dienst_start", ergebnis="ok")
p = SL.pruefen(SL.DATEI)
check("Positivkontrolle: Altzeile ohne, danach mit Schluessel -> ok", p["ok"], p)

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
