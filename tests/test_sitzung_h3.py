#!/usr/bin/env python3
"""Waechter: BSI-Befund H3 – Sitzungstoken (Laufzeit, Leerlauf, Widerruf).

Befund (BSI-Abgleich ECHT, 2026-09-29): das Token galt fest 30 Tage, kannte
keinen Leerlauf, und weder Abmelden noch Kennwortwechsel machten es ungueltig.
Entscheidung des Betreibers 2026-09-30: 12 h Laufzeit, 2 h Leerlauf.

Gemessen wird an der WIRKUNG:

  [A] backend/sitzung_token.py direkt (Wegwerf-Ablage): Laufzeit, Leerlauf,
      Widerruf je Token, Zukunfts-Zeitstempel, Einstellungen, Persistenz, und
      dass die Ablage kein Token enthaelt.
  [B] die echten Funktionen aus main.py (per AST geholt, Attrappen in echter
      Signatur): generate_token/verify_token, logout, Kennwortwechsel,
      Aufraeumen der Epochen, Revalidierungs-Uebersprung – und als REGEL: kein
      ``_revoked_logins.pop`` ausserhalb des Aufraeumens (das Aufheben beim
      AD-Login belebte alte Tokens wieder).
  [C] Frontend (acorn): beide Kennwort-Dialoge in app.js uebernehmen das
      Ersatz-Token, der Helfer ist fuer beide erreichbar und schreibt es.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
FAIL = 0


def check(name: str, bed: bool) -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name)


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


# backend.config NUR als Stub – der echte Import schreibt die Live-settings.json.
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules.setdefault("backend.config", _cfg)

TMP = Path(tempfile.mkdtemp(prefix="waechter-sitzung-h3-"))

from backend import sitzung_token as st  # noqa: E402

st.STORE_PATH = TMP / "auth_sitzungen.json"
if not str(st.STORE_PATH).startswith(str(TMP)):
    abbruch("Ablage zeigt aus dem Sandkasten heraus")

EINST: dict = {}
st.einstellungen_quelle(lambda k, d=None: EINST.get(k, d))


def frisch(**einst) -> None:
    EINST.clear()
    EINST.update(einst)
    st._zuruecksetzen_fuer_test()
    try:
        st.STORE_PATH.unlink()
    except FileNotFoundError:
        pass


H = 3600
JETZT = time.time()

# ─── [A] Modul ───────────────────────────────────────────────────────────────
print("[A] sitzung_token")
frisch()
# Positivkontrolle: ein frisches Token gilt – sonst sind alle Ablehnungen unten
# trivial wahr.
st.neu("sigA", int(JETZT))
if not st.pruefe_und_beruehre("sigA", int(JETZT), JETZT):
    abbruch("Positivkontrolle: frisches Token wird abgelehnt")
check("Vorgaben 12 h / 120 min", st._grenzen() == (12 * H, 120 * 60))

# Laufzeit: 11 h 59 alt und eben benutzt -> gilt; 12 h + 1 s -> nicht, auch
# wenn es eben benutzt wurde (die Laufzeit ist nicht verlaengerbar).
frisch()
ts = int(JETZT - 12 * H + 60)
st._zuletzt[st.schluessel("s1")] = JETZT - 10
check("11 h 59 alt, eben benutzt -> gilt", st.pruefe_und_beruehre("s1", ts, JETZT))
ts = int(JETZT - 12 * H - 1)
st._zuletzt[st.schluessel("s2")] = JETZT - 10
check("12 h + 1 s alt, eben benutzt -> abgelehnt",
      not st.pruefe_und_beruehre("s2", ts, JETZT))
check("30 Tage alt -> abgelehnt (Altverhalten)",
      not st.pruefe_und_beruehre("s3", int(JETZT - 29 * 24 * H), JETZT))

# Leerlauf
frisch()
ts = int(JETZT - 3 * H)
check("unbekanntes Token, 3 h alt -> abgelehnt (kein Vorschuss)",
      not st.pruefe_und_beruehre("i1", ts, JETZT))
st._zuletzt[st.schluessel("i2")] = JETZT - 119 * 60
check("zuletzt vor 119 min -> gilt", st.pruefe_und_beruehre("i2", ts, JETZT))
st._zuletzt[st.schluessel("i3")] = JETZT - 121 * 60
check("zuletzt vor 121 min -> abgelehnt", not st.pruefe_und_beruehre("i3", ts, JETZT))
# Beruehren wirkt: nach einer gueltigen Anfrage ist der Leerlauf neu gestartet
st._zuletzt[st.schluessel("i4")] = JETZT - 119 * 60
st.pruefe_und_beruehre("i4", ts, JETZT)
check("Anfrage setzt den Leerlauf zurueck",
      st.pruefe_und_beruehre("i4", ts, JETZT + 100 * 60))
check("... und danach 2 h Stille beendet es",
      not st.pruefe_und_beruehre("i4", ts, JETZT + 100 * 60 + 121 * 60))

# Zukunft
frisch()
check("Zeitstempel 3 s in der Zukunft -> gilt (Ersatz-Token)",
      st.pruefe_und_beruehre("z1", int(JETZT + 3), JETZT))
check("Zeitstempel 1 h in der Zukunft -> abgelehnt",
      not st.pruefe_und_beruehre("z2", int(JETZT + H), JETZT))

# Widerruf je Token
frisch()
st.neu("w1", int(JETZT))
st.neu("w2", int(JETZT))
st.widerrufe("w1", int(JETZT))
# Direkt nach dem Widerruf lesen – die naechste gueltige Anfrage schreibt die
# Datei ohnehin (gedrosselt), danach waere "sofort" nicht mehr messbar.
roh = st.STORE_PATH.read_text() if st.STORE_PATH.exists() else ""
check("widerrufenes Token -> abgelehnt", not st.pruefe_und_beruehre("w1", int(JETZT), JETZT))
check("anderes Token desselben Benutzers -> gilt weiter",
      st.pruefe_und_beruehre("w2", int(JETZT), JETZT))

# Persistenz: Widerruf ueberlebt einen Neustart, Ablage enthaelt kein Token
check("Widerruf sofort auf Platte", st.schluessel("w1") in roh)
check("Ablage enthaelt die Signatur nicht", "w1" not in roh.replace(st.schluessel("w1"), ""))
st._zuruecksetzen_fuer_test()
check("nach Neustart weiter widerrufen",
      not st.pruefe_und_beruehre("w1", int(JETZT), JETZT))
if os.name == "posix" and st.STORE_PATH.exists():
    check("Ablage nicht weltlesbar", (st.STORE_PATH.stat().st_mode & 0o004) == 0)

# Einstellungen
frisch(sitzung_max_stunden=1, sitzung_leerlauf_minuten=10)
check("Einstellung 1 h / 10 min greift", st._grenzen() == (H, 600))
st._zuletzt[st.schluessel("e1")] = JETZT - 60
check("mit 1 h Laufzeit: 2 h altes Token abgelehnt",
      not st.pruefe_und_beruehre("e1", int(JETZT - 2 * H), JETZT))
for unsinn in (0, -5, "abc", None):
    frisch(sitzung_max_stunden=unsinn, sitzung_leerlauf_minuten=unsinn)
    check("Unsinn %r -> Vorgabe, nicht 'aus'" % (unsinn,),
          st._grenzen() == (12 * H, 120 * 60))

# ─── [B] main.py ─────────────────────────────────────────────────────────────
print("[B] main.py")
MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN_SRC)


def _fn(name: str):
    fn = next((n for n in BAUM.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name),
              None)
    if fn is None:
        abbruch("%s nicht in main.py" % name)
    return fn


def _funktionen(*namen: str) -> dict:
    teile = []
    for name in namen:
        fn = _fn(name)
        fn.decorator_list = []
        for a in fn.args.args + fn.args.kwonlyargs:
            a.annotation = None
        fn.returns = None
        fn.args.defaults = [ast.Constant(None) for _ in fn.args.defaults]
        teile.append(fn)
    mod = ast.Module(body=teile, type_ignores=[])
    ast.fix_missing_locations(mod)
    return compile(mod, "main.py<auszug>", "exec")


class _JR:
    def __init__(self, inhalt, status_code=200):
        self.body = inhalt
        self.status_code = status_code


class _Req:
    def __init__(self, token):
        self.headers = {"Authorization": "Bearer " + token}
        self.client = None   # wie Starlette ohne Gegenstelle (logout protokolliert die IP)
        self.scope = {}      # wie Starlette: ohne Cookie-Anmeldung (BSI H4) kein Merker


abgemeldet = []
NS = {
    "config": types.SimpleNamespace(SECRET_KEY="k" * 64),
    "time": time, "hmac": hmac, "hashlib": hashlib, "json": json,
    "_sitzung": st,
    "_revoked_logins": {},
    "_WIDERRUF_ALLE": "*",
    "_REVOKED_FILE": TMP / "auth_revocations.json",
    "os": os,
    "_sitzung_herkunft": __import__("contextvars").ContextVar("_sh", default=None),
    "_norm_login": lambda n: (n or "").split("@")[0].split("\\")[-1].strip().lower(),
    "_user_sessions": types.SimpleNamespace(
        record_logout=lambda u, display="": abgemeldet.append(u)),
    "_display_name": lambda u: u,
    "JSONResponse": _JR,
    # BSI M3: verify_token setzt den Sitzungskontext (2FA-Merkmal)
    "_sitzung_kontext": __import__("contextvars").ContextVar("_sk", default=None),
    # BSI M2: verify_token meldet die Sitzung an den Protokoll-Halter, logout
    # schreibt ins Sicherheitsprotokoll
    "_admin_anfrage": __import__("contextvars").ContextVar("_aa", default=None),
    "_sicherheits_log": types.SimpleNamespace(ereignis=lambda *a, **k: {}),
}
exec(_funktionen("generate_token", "verify_token", "_epoche_widerrufen", "logout",
                 "_sitzungen_nach_kennwortwechsel", "_save_revocations",
                 "_revalidierung_ueberspringen"), NS)
gen, ver = NS["generate_token"], NS["verify_token"]

frisch()
t = gen("anna")
if ver(t) != "anna":
    abbruch("Positivkontrolle: frisch ausgestelltes Token wird abgelehnt")
check("gefaelschte Signatur -> abgelehnt", ver(t[:-1] + ("0" if t[-1] != "0" else "1")) is None)


def _token_mit_ts(user, ts):
    sig = hmac.new(NS["config"].SECRET_KEY.encode(), f"{user}:{ts}".encode(),
                   hashlib.sha256).hexdigest()
    return f"{user}:{ts}:{sig}", sig


alt, alt_sig = _token_mit_ts("anna", int(time.time() - 13 * H))
st._zuletzt[st.schluessel(alt_sig)] = time.time() - 5
check("verify_token: 13 h altes, eben benutztes Token -> abgelehnt", ver(alt) is None)
still, _ = _token_mit_ts("anna", int(time.time() - 3 * H))
check("verify_token: 3 h ohne Anfrage -> abgelehnt", ver(still) is None)

# Abmelden: genau dieses Token
frisch()
t1, t2 = gen("bert"), gen("bert")
while t2 == t1:                       # gleiche Sekunde = gleiches Token
    time.sleep(0.2)
    t2 = gen("bert")
asyncio.run(NS["logout"](_Req(t1), "bert"))
check("logout: dieses Token danach ungueltig", ver(t1) is None)
check("logout: zweites Geraet bleibt angemeldet", ver(t2) == "bert")
check("logout: Anwesenheit weiter vermerkt", abgemeldet[-1:] == ["bert"])

# Kennwortwechsel: alle alten weg, Ersatz-Token gilt – sofort, in derselben Sekunde
frisch()
NS["_revoked_logins"].clear()
a1, a2 = gen("carl"), gen("carl")
neu_t = NS["_sitzungen_nach_kennwortwechsel"]("carl")
check("Kennwortwechsel: altes Token ungueltig", ver(a1) is None and ver(a2) is None)
check("Kennwortwechsel: Ersatz-Token sofort gueltig", ver(neu_t) == "carl")
check("Kennwortwechsel: Epoche auf Platte",
      "carl" in NS["_REVOKED_FILE"].read_text())

# Rueckgabe der Endpunkte: beide Zweige (Docker und Linux) liefern das Token
cp = _fn("change_password")
rueck = [n for n in ast.walk(cp) if isinstance(n, ast.Return)]


def _antwort_dict(r):
    """Das Antwort-Dict einer Rueckgabe – erstes Dict-Argument des Aufrufs.
    Seit BSI H4 laeuft die Antwort ueber ``_sitzung_antwort(request, {...})``,
    das Dict steht also nicht mehr zwingend an Position 0."""
    if not isinstance(r.value, ast.Call):
        return None
    for a in r.value.args:
        if isinstance(a, ast.Dict):
            return a
    return None


erfolg = [r for r in rueck if _antwort_dict(r) is not None
          and any(isinstance(k, ast.Constant) and k.value == "success" for k in _antwort_dict(r).keys)
          and any(isinstance(v, ast.Constant) and v.value is True for v in _antwort_dict(r).values)]
mit_token = [r for r in erfolg
             if any(isinstance(k, ast.Constant) and k.value == "token"
                    and isinstance(v, ast.Call) and getattr(v.func, "id", "") == "_sitzungen_nach_kennwortwechsel"
                    for k, v in zip(_antwort_dict(r).keys, _antwort_dict(r).values))]
check("change_password: es gibt Erfolgs-Rueckgaben (Positivkontrolle)", len(erfolg) >= 2)
check("change_password: JEDE Erfolgs-Rueckgabe traegt das Ersatz-Token",
      len(erfolg) >= 2 and len(mit_token) == len(erfolg))

# Aufraeumen der Epochen statt Aufheben beim Login
frisch()
NS["_revoked_logins"].clear()
NS["_revoked_logins"].update({"alt": int(time.time() - 13 * H), "frisch": int(time.time() - H)})
NS["_save_revocations"]()
check("Epoche aelter als Laufzeit wird aufgeraeumt", "alt" not in NS["_revoked_logins"])
check("Epoche innerhalb der Laufzeit bleibt", "frisch" in NS["_revoked_logins"])

pops = []
for fn in BAUM.body:
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("pop", "clear", "__delitem__")
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "_revoked_logins"):
            pops.append(fn.name)
    for n in ast.walk(fn):
        if isinstance(n, ast.Delete) and any(
                isinstance(z, ast.Subscript) and getattr(z.value, "id", "") == "_revoked_logins"
                for z in n.targets):
            pops.append(fn.name)
check("Widerruf wird nur im Aufraeumen entfernt (kein pop beim Login): %s" % sorted(set(pops)),
      set(pops) <= {"_save_revocations"})

# Revalidierung: wer nach dem Widerruf wieder aktiv ist, wird wieder geprueft
NS["_revoked_logins"].clear()
NS["_revoked_logins"]["dora"] = 1000
ueb = NS["_revalidierung_ueberspringen"]
check("Revalidierung: widerrufen, seitdem still -> uebersprungen", ueb("dora", 999) is True)
check("Revalidierung: nach Widerruf wieder aktiv -> geprueft", ueb("dora", 1001) is False)
check("Revalidierung: nie widerrufen -> geprueft", ueb("emil", 5) is False)
rv = [n for n in ast.walk(BAUM) if isinstance(n, ast.Call)
      and getattr(n.func, "id", "") == "_revalidierung_ueberspringen"]
check("Revalidierung benutzt den Helfer", len(rv) >= 1)

# verify_token prueft ueberhaupt die Buchhaltung (sonst waere [A] Dekoration)
vt = _fn("verify_token")
check("verify_token ruft _sitzung.pruefe_und_beruehre",
      any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
          and n.func.attr == "pruefe_und_beruehre" for n in ast.walk(vt)))

# Start-Haertung kennt die Ablage (sonst setzt ein Neustart sie nicht auf 0640)
SB = ast.parse((ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8"))
pf = next((n.value for n in SB.body if isinstance(n, ast.Assign)
           and any(getattr(t, "id", "") == "PRIVATE_FILES" for t in n.targets)), None)
eintraege = {e.value for e in getattr(pf, "elts", []) if isinstance(e, ast.Constant)}
check("sandbox.PRIVATE_FILES gefunden (Positivkontrolle)", "data/auth_revocations.json" in eintraege)
check("sandbox.PRIVATE_FILES enthaelt data/auth_sitzungen.json",
      "data/auth_sitzungen.json" in eintraege)

# ─── [C] Frontend ────────────────────────────────────────────────────────────
print("[C] app.js")
JS = r"""
const path = require('path');
function hole(name) {
    const orte = [process.env[name.toUpperCase() + '_PATH'], name,
                  path.join(process.argv[2], 'data/node_modules', name),
                  path.join(process.argv[2], 'node_modules', name),
                  '/tmp/node_modules/' + name, '/usr/share/nodejs/' + name,
                  path.join(process.argv[2], 'node_modules/jsdom/node_modules', name)];
    for (const k of orte) { if (!k) continue; try { return require(k); } catch (e) {} }
    return null;
}
const acorn = hole('acorn');
if (!acorn) { console.log(JSON.stringify({fehlt: true})); process.exit(0); }
const src = require('fs').readFileSync(path.join(process.argv[2], 'frontend/js/app.js'), 'utf8');
const ast = acorn.parse(src, {ecmaVersion: 'latest', sourceType: 'script'});
const res = {dialoge: 0, mit_uebernahme: 0, helfer: [], helfer_setzt: false, erreichbar: 0};
function kinder(n) { const o = []; for (const k in n) { const v = n[k];
    if (Array.isArray(v)) v.forEach(x => x && typeof x.type === 'string' && o.push(x));
    else if (v && typeof v.type === 'string') o.push(v); } return o; }
function walk(n, f, stapel) { f(n, stapel); stapel.push(n); kinder(n).forEach(k => walk(k, f, stapel)); stapel.pop(); }
function istFetchKennwort(n) { return n.type === 'CallExpression' && n.callee.type === 'Identifier'
    && n.callee.name === 'fetch' && n.arguments[0] && n.arguments[0].value === '/api/change-password'; }
// Helfer-Deklarationen samt umgebendem Block
walk(ast, (n, st) => {
    if (n.type === 'FunctionDeclaration' && n.id && n.id.name === '_uebernimmErsatzToken') {
        res.helfer.push(st[st.length - 1]);
        let tok = false, ls = false;
        walk(n.body, m => {
            if (m.type === 'AssignmentExpression' && m.left.type === 'Identifier' && m.left.name === 'token') tok = true;
            if (m.type === 'CallExpression' && m.callee.type === 'MemberExpression'
                && m.callee.property.name === 'setItem' && m.arguments[0] && m.arguments[0].value === 'jarvis_token') ls = true;
        }, []);
        res.helfer_setzt = tok && ls;
    }
}, []);
walk(ast, (n, st) => {
    if (!istFetchKennwort(n)) return;
    res.dialoge++;
    // umgebende Funktion
    let fn = null; for (let i = st.length - 1; i >= 0; i--) {
        if (/Function/.test(st[i].type)) { fn = st[i]; break; } }
    if (!fn) return;
    if (res.helfer.some(h => st.includes(h))) res.erreichbar++;
    walk(fn, m => {
        if (m.type !== 'IfStatement') return;
        const t = m.test;
        if (!(t.type === 'MemberExpression' && t.property.name === 'success')) return;
        const erst = (m.consequent.body || [])[0];
        if (erst && erst.type === 'ExpressionStatement' && erst.expression.type === 'CallExpression'
            && erst.expression.callee.name === '_uebernimmErsatzToken'
            && erst.expression.arguments[0] && erst.expression.arguments[0].type === 'MemberExpression'
            && erst.expression.arguments[0].property.name === 'token') res.mit_uebernahme++;
    }, []);
}, []);
res.helfer = res.helfer.length;
console.log(JSON.stringify(res));
"""
jsdatei = TMP / "probe.js"
jsdatei.write_text(JS)
try:
    r = subprocess.run(["node", str(jsdatei), str(ROOT)], capture_output=True, text=True, timeout=60)
    erg = json.loads((r.stdout or "").strip().splitlines()[-1])
except Exception as e:  # noqa: BLE001
    abbruch("Frontend-Probe lief nicht: %s – %s" % (e, (r.stderr or "")[-400:] if "r" in dir() else ""))
if erg.get("fehlt"):
    abbruch("acorn nicht verfuegbar")
check("app.js: Kennwort-Dialoge gefunden (Positivkontrolle, 2)", erg["dialoge"] == 2)
check("app.js: genau ein Helfer _uebernimmErsatzToken", erg["helfer"] == 1)
check("app.js: Helfer setzt token und jarvis_token", erg["helfer_setzt"])
check("app.js: beide Dialoge uebernehmen data.token als ersten Schritt",
      erg["mit_uebernahme"] == erg["dialoge"] == 2)
check("app.js: Helfer fuer beide Dialoge erreichbar", erg["erreichbar"] == 2)

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
