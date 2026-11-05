#!/usr/bin/env python3
"""Waechter: Outlook-Umbau, Punkt e (2026-11-05).

Zusagen:
* Der SERVER greift nur fuer ausgewaehlte Benutzer auf ein Postfach zu
  (Auswahl in Einstellungen → E-Mail, Feld ``server_zugriff_benutzer`` der
  E-Mail-Skill-Config). Leer = niemand. Die Schranke sitzt in
  ``mail_accounts.konto_fuer`` – VOR jeder Entschluesselung.
* Die Automatik ueberspringt Regeln ohne Serverzugriff, BEVOR ein Lauf zaehlt.
* Der Antwortvorschlag nimmt den Inhalt aus dem Add-in – dann oeffnet der
  Server kein Postfach; der Inhalt wird begrenzt.
* ``/api/email/reply/form`` baut nur den Rumpf (Signatur), ohne Postfach und
  ohne Versand.
* Die Auswahl laesst nur Benutzer mit E-Mail-Berechtigung zu (Admin-Endpunkt).

Austauschdateien fuer die Gegenprobe: MS_ACCOUNTS, MS_RUNNER, MS_MAIN.
Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.

    python3 tests/test_mail_serverzugriff.py
"""
import ast
import asyncio
import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n{t}")


def _pfad(var, rel):
    return Path(os.environ.get(var) or ROOT / rel)


KONTEN = _pfad("MS_ACCOUNTS", "backend/mail_accounts.py")
RUNNER = _pfad("MS_RUNNER", "backend/mail_runner.py")
MAIN = _pfad("MS_MAIN", "backend/main.py")

TMP = Path(tempfile.mkdtemp(prefix="mailserver_test_"))
_skill_states = {"email": {"enabled": True, "config": {
    "ews_url": "https://mail.beispiel.de/EWS/Exchange.asmx", "autodiscover": False}}}
_cfg_mod = types.ModuleType("backend.config")


class _Cfg:
    def get_skill_states(self):
        return _skill_states

    def get_setting(self, key, default=None):
        return default

    def save_setting(self, key, value):
        pass


_cfg_mod.config = _Cfg()
sys.modules["backend.config"] = _cfg_mod


def _laden(name, pfad):
    spec = importlib.util.spec_from_file_location(name, pfad)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


try:
    import backend  # noqa: F401
    from backend import mail_client as mc
    ma = _laden("backend.mail_accounts", KONTEN)
    from backend import mail_rules as mr
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Module nicht ladbar: {e}")
    sys.exit(2)

ma.DATA_DIR = TMP
ma.KONTEN_DATEI = TMP / "email_accounts.json"
ma.SCHLUESSEL_DATEI = TMP / ".mailkey"
mr.DATA_DIR = TMP
mr.REGEL_DATEI = TMP / "email_rules.json"
mr.ZUSTAND_DATEI = TMP / "email_state.json"
mr.PROTOKOLL_DATEI = TMP / "email_log.jsonl"
for pf in (ma.KONTEN_DATEI, ma.SCHLUESSEL_DATEI, mr.REGEL_DATEI):
    if not str(pf).startswith(str(TMP)):
        print(f"SANDKASTEN VERLETZT: {pf}")
        sys.exit(2)


def auswahl(wert):
    c = _skill_states["email"]["config"]
    if wert is None:
        c.pop(ma.SERVER_ZUGRIFF_FELD, None)
    else:
        c[ma.SERVER_ZUGRIFF_FELD] = wert


# ═══════════════════════════════════════════════════════════════════════════
section("0. Positivkontrolle: mit Auswahl entsteht ein Konto")
# ═══════════════════════════════════════════════════════════════════════════
auswahl("m.mustermann")
try:
    ma.speichern("m.mustermann", {"adresse": "m.mustermann@beispiel.de", "passwort": "geheim"})
    k = ma.konto_fuer("m.mustermann")
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: mit Auswahl kein Konto ({e}) – Messaufbau kaputt")
    sys.exit(2)
check(k.passwort == "geheim", "mit Auswahl: Konto samt Kennwort")

# ═══════════════════════════════════════════════════════════════════════════
section("1. Auswahl: leer = niemand, normalisiert")
# ═══════════════════════════════════════════════════════════════════════════
for wert, name in ((None, "Feld fehlt"), ("", "leer"), (" , ", "nur Trenner")):
    auswahl(wert)
    try:
        ma.konto_fuer("m.mustermann")
        check(False, f"{name}: kein Serverzugriff")
    except mc.MailFehler as e:
        check(str(e) == ma.SERVER_ZUGRIFF_TEXT, f"{name}: kein Serverzugriff", str(e))
auswahl("FIRMA\\M.Mustermann, e.beispiel@firma.local, wa:+491701234")
check(ma.server_zugriff_liste() == ["m.mustermann", "e.beispiel"],
      "Auswahl normalisiert, Kanal-Kennung verworfen", str(ma.server_zugriff_liste()))
check(ma.server_zugriff("m.mustermann@beispiel.de") and not ma.server_zugriff("x.fremd"),
      "Vergleich normalisiert, Fremde draussen")
check(ma.konto_info("m.mustermann").get("server_zugriff") is True
      and ma.konto_info("x.fremd").get("server_zugriff") is False,
      "konto_info meldet den Serverzugriff (Oberflaeche)")

# Die Schranke steht VOR dem Entschluesseln: ohne Auswahl wird der Schluessel
# nicht einmal angefasst.
auswahl("")
_aufrufe = []
_orig = ma.entschluesseln
ma.entschluesseln = lambda x: (_aufrufe.append(1), _orig(x))[1]
try:
    ma.konto_fuer("m.mustermann")
except mc.MailFehler:
    pass
ma.entschluesseln = _orig
check(not _aufrufe, "ohne Auswahl wird kein Kennwort entschluesselt", str(len(_aufrufe)))

# ═══════════════════════════════════════════════════════════════════════════
section("2. Nachricht aus dem Add-in")
# ═══════════════════════════════════════════════════════════════════════════
try:
    mrun = _laden("backend.mail_runner", RUNNER)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: mail_runner nicht ladbar: {e}")
    sys.exit(2)
n = mrun._nachricht_aus_addin({"von": "a@b.de", "von_name": "A", "betreff": "B" * 900,
                               "text": "x" * (mrun.VORSCHLAG_MAX + 50), "an": ["c@d.de"] * 80,
                               "cc": "kein-array"})
check(n.von == "a@b.de" and len(n.betreff) == 500 and len(n.text) == mrun.VORSCHLAG_MAX,
      "Felder werden begrenzt")
check(len(n.an) == 50 and n.cc == [], "Listen begrenzt, falscher Typ verworfen")


# ── Automatik: Positivkontrolle + Ueberspringen ──
class _MR:
    def __init__(self, regeln):
        self.regeln = regeln
        self.gemerkt = []

    def faellige(self):
        return list(self.regeln)

    def merke_lauf(self, rid):
        self.gemerkt.append(rid)


_gelaufen = []


async def _regel_lauf(regel, *a, **k):
    _gelaufen.append(regel["id"])
    return {"ok": True, "verarbeitet": 0, "regel": regel.get("name"), "owner": regel.get("owner")}


_orig_mr, _orig_lauf, _orig_aktiv = mrun.mail_rules, mrun.regel_lauf, mrun.mail_accounts.skill_aktiv
attrappe = _MR([{"id": "r1", "owner": "m.mustermann", "name": "eins"},
                {"id": "r2", "owner": "x.fremd", "name": "zwei"}])
mrun.mail_rules = attrappe
mrun.regel_lauf = _regel_lauf
mrun.mail_accounts.skill_aktiv = lambda: True
auswahl("m.mustermann")
try:
    asyncio.run(mrun.automatik_durchgang())
finally:
    mrun.mail_rules, mrun.regel_lauf, mrun.mail_accounts.skill_aktiv = _orig_mr, _orig_lauf, _orig_aktiv
check("r1" in _gelaufen, "Positivkontrolle: Regel MIT Serverzugriff laeuft", str(_gelaufen))
check("r2" not in _gelaufen and "r2" not in attrappe.gemerkt,
      "Regel OHNE Serverzugriff: kein Lauf, kein Vermerk", f"{_gelaufen} / {attrappe.gemerkt}")

# ═══════════════════════════════════════════════════════════════════════════
section("3. Regeln am Syntaxbaum")
# ═══════════════════════════════════════════════════════════════════════════
try:
    b_run = ast.parse(RUNNER.read_text(encoding="utf-8"))
    b_main = ast.parse(MAIN.read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Quelltext nicht lesbar: {e}")
    sys.exit(2)


def fn(baum, name):
    return next((x for x in ast.walk(baum) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and x.name == name), None)


def rufe(knoten, name):
    return [c for c in ast.walk(knoten) if isinstance(c, ast.Call) and (
        (isinstance(c.func, ast.Attribute) and c.func.attr == name)
        or (isinstance(c.func, ast.Name) and c.func.id == name))]


av = fn(b_run, "antwort_vorschlag")
rf = fn(b_main, "email_reply_form")
rp = fn(b_main, "email_reply_preview")
sg = fn(b_main, "email_admin_serverzugriff_get")
ss = fn(b_main, "email_admin_serverzugriff_set")
if not all((av, rf, rp, sg, ss)):
    print("ABBRUCH: Funktionen nicht gefunden")
    sys.exit(2)

# konto_fuer im Vorschlag NUR im else-Zweig von `if nachricht is not None`
weiche = next((s for s in ast.walk(av) if isinstance(s, ast.If)
               and isinstance(s.test, ast.Compare) and isinstance(s.test.left, ast.Name)
               and s.test.left.id == "nachricht"), None)
check(weiche is not None, "Positivkontrolle: Weiche 'nachricht' gefunden")
if weiche is not None:
    im_then = rufe(ast.Module(body=weiche.body, type_ignores=[]), "konto_fuer")
    im_else = rufe(ast.Module(body=weiche.orelse, type_ignores=[]), "konto_fuer")
    alle = rufe(av, "konto_fuer")
    check(not im_then and len(im_else) == len(alle) >= 1,
          "Vorschlag mit Add-in-Inhalt oeffnet KEIN Postfach",
          f"then={len(im_then)} else={len(im_else)} gesamt={len(alle)}")
check(any(k.arg == "nachricht" for c in rufe(rp, "antwort_vorschlag") for k in c.keywords),
      "der Vorschau-Endpunkt reicht den Inhalt durch")
verboten = [n for n in ("konto_fuer", "MailClient", "antwort_senden", "run_task_headless")
            if rufe(rf, n)]
check(not verboten and bool(rufe(rf, "signatur_anhaengen")),
      "reply/form: nur Signatur – kein Postfach, kein Versand, kein Modell", str(verboten))


def _haengt_an(f, dep):
    return any(isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "Depends"
               and d.args and isinstance(d.args[0], ast.Name) and d.args[0].id == dep
               for d in ast.walk(f.args))


check(_haengt_an(sg, "require_local_auth") and _haengt_an(ss, "require_local_auth"),
      "Auswahl nur fuer Administratoren")
check(bool(rufe(ss, "_user_may_use_email")), "Speichern prueft die E-Mail-Berechtigung je Eintrag")

print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
