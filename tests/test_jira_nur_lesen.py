#!/usr/bin/env python3
"""Waechter: gemeinsamer Jira-Zugang nur lesend + Schalter "Persoenliche Zugaenge
erlauben" (2026-11-05, analog zur SAP-Kachel-Anmeldung).

Zusagen:
* ``JiraClient`` liest nur – Vorgabe, fail-closed. Schreiben (POST) geht nur mit
  ``schreiben=True``, und das setzt ausschliesslich der PERSOENLICHE Zugang in
  ``jira_accounts.aufloesen``.
* Schalter aus: kein persoenlicher Zugang greift (auch kein Rest in der Datei),
  neue werden abgelehnt, ``alle_entfernen`` loescht alle; Feld fehlt = erlaubt.
* ``main.update_skill_config`` loescht beim ABSCHALTEN alle persoenlichen Token.
* Einstellungen → Jira: Nur-Lesen angehakt+gesperrt, Schalter vorhanden.
* Browser-Erweiterung (Punkt f): alles, was sie ausloest, liest ueber den
  gemeinsamen Lesezugang – ``jira_assist._client``, die Jira-Werkzeuge im
  Assistentenlauf (``nur_gemeinsam``) und die health-Route.

Sabotierte Kopien fuer die Gegenprobe ueber JI_CLIENT, JI_ACCOUNTS, JI_MAIN,
JI_SETTINGS, JI_SKILL. Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.

    python3 tests/test_jira_nur_lesen.py
"""
import ast
import importlib.util
import json
import os
import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _pfad(var, rel):
    return Path(os.environ.get(var) or ROOT / rel)


CLIENT = _pfad("JI_CLIENT", "backend/jira_client.py")
KONTEN = _pfad("JI_ACCOUNTS", "backend/jira_accounts.py")
MAIN = _pfad("JI_MAIN", "backend/main.py")
SETTINGS = _pfad("JI_SETTINGS", "frontend/settings.html")
SKILL = _pfad("JI_SKILL", "skills/jira/main.py")
ASSIST = _pfad("JI_ASSIST", "backend/jira_assist.py")

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


SKILLCFG = {"jira": {"config": {"base_url": "https://jira.beispiel.de", "api_token": "sammel"}}}
_cfg = types.ModuleType("backend.config")


class _C:
    def get_skill_states(self):
        return SKILLCFG

    def get_setting(self, k, d=None):
        return d


_cfg.config = _C()
sys.modules["backend.config"] = _cfg


def _laden(name, pfad):
    spec = importlib.util.spec_from_file_location(name, pfad)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


try:
    import backend  # noqa: F401
    jc = _laden("backend.jira_client", CLIENT)
    ja = _laden("backend.jira_accounts", KONTEN)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Module nicht ladbar: {e}")
    sys.exit(2)

TMP = Path(tempfile.mkdtemp(prefix="jira_nurlesen_"))
ja.DATA_DIR = TMP
ja.KONTEN_DATEI = TMP / "jira_accounts.json"
ja.SCHLUESSEL_DATEI = TMP / ".jirakey"
if not str(ja.KONTEN_DATEI).startswith(str(TMP)):
    print("SANDKASTEN VERLETZT")
    sys.exit(2)

GESENDET = []


class _Antwort:
    status_code = 200
    text = "{}"

    def json(self):
        return {"displayName": "X", "name": "x"}


def _request(method, url, **kw):
    GESENDET.append(method.upper())
    return _Antwort()


jc.requests.request = _request


def schalter(wert):
    c = SKILLCFG["jira"]["config"]
    if wert is None:
        c.pop("persoenliche_zugaenge", None)
    else:
        c["persoenliche_zugaenge"] = wert


# ═══════════════════════════════════════════════════════════════════════════
section("0. Positivkontrolle: Lesen geht, die Netz-Attrappe sieht es")
# ═══════════════════════════════════════════════════════════════════════════
c = jc.JiraClient()
try:
    c._request("GET", "/rest/api/2/myself")
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: GET scheitert ({e})")
    sys.exit(2)
if GESENDET != ["GET"]:
    print(f"ABBRUCH: Netz-Attrappe sieht den GET nicht ({GESENDET})")
    sys.exit(2)
check(True, "GET erreicht das Netz")

# ═══════════════════════════════════════════════════════════════════════════
section("1. Client: Nur-Lesen ist die Vorgabe")
# ═══════════════════════════════════════════════════════════════════════════
for m in ("POST", "PUT", "DELETE", "post"):
    GESENDET.clear()
    try:
        c._request(m, "/rest/api/2/issue", json={})
        check(False, f"{m} ohne schreiben=True abgelehnt", "kein Fehler")
    except jc.JiraError as e:
        check(str(e) == jc.NUR_LESEN_TEXT and not GESENDET, f"{m} abgelehnt, nichts gesendet",
              f"{e} / {GESENDET}")
GESENDET.clear()
try:
    c.add_comment("PRJA-1", "x")
    check(False, "Kommentar ueber den gemeinsamen Zugang abgelehnt")
except jc.JiraError:
    check(not GESENDET, "Kommentar ueber den gemeinsamen Zugang abgelehnt")
GESENDET.clear()
w = jc.JiraClient({"base_url": "https://jira.beispiel.de", "api_token": "p"}, schreiben=True)
try:
    w._request("POST", "/rest/api/2/issue/PRJA-1/comment", json={})
    check(GESENDET == ["POST"], "mit schreiben=True geht POST", str(GESENDET))
except jc.JiraError as e:
    check(False, "mit schreiben=True geht POST", str(e))

# ═══════════════════════════════════════════════════════════════════════════
section("2. Aufloesung: wer darf schreiben?")
# ═══════════════════════════════════════════════════════════════════════════
schalter(None)
check(ja.persoenlich_erlaubt() is True, "Feld fehlt -> persoenliche Zugaenge erlaubt")
# Kein ungeschuetzter Aufruf: lehnt eine Sabotage das Speichern ab, ist das
# ein FAIL mit Bilanz, kein Absturz.
try:
    ja.speichern("m.mustermann", {"api_token": "persoenlich-1"})
    ja.speichern("e.beispiel", {"api_token": "persoenlich-2"})
    check(True, "Schalter an: persoenliche Token lassen sich speichern")
except ja.JiraKontoFehler as e:
    check(False, "Schalter an: persoenliche Token lassen sich speichern", str(e))
z = ja.aufloesen("m.mustermann")
check(z["quelle"] == ja.QUELLE_PERSOENLICH and z["client"].schreiben is True,
      "persoenlicher Zugang darf schreiben", f'{z["quelle"]} / {z["client"].schreiben}')
z = ja.aufloesen("niemand")
check(z["quelle"] == ja.QUELLE_SAMMEL and z["client"].schreiben is False,
      "gemeinsamer Zugang liest nur", f'{z["quelle"]} / {z["client"].schreiben}')
check(ja.sammel_client().schreiben is False, "sammel_client() liest nur")

# ═══════════════════════════════════════════════════════════════════════════
section("3. Schalter aus")
# ═══════════════════════════════════════════════════════════════════════════
schalter(False)
check(ja.persoenlich_erlaubt() is False, "Schalter aus erkannt")
z = ja.aufloesen("m.mustermann")
check(z["quelle"] == ja.QUELLE_SAMMEL and z["client"].schreiben is False,
      "ein Rest in der Datei greift NICHT", z["quelle"])
try:
    ja.speichern("m.mustermann", {"api_token": "neu"})
    check(False, "neuer Token wird abgelehnt")
except ja.JiraKontoFehler as e:
    check(str(e) == ja.ABGESCHALTET_TEXT, "neuer Token wird abgelehnt", str(e))
try:
    ja.testen("m.mustermann")
    check(False, "Verbindungstest des eigenen Tokens abgelehnt")
except ja.JiraKontoFehler as e:
    check(str(e) == ja.ABGESCHALTET_TEXT, "Verbindungstest des eigenen Tokens abgelehnt", str(e))
check(ja.zugang_info("m.mustermann").get("persoenlich_erlaubt") is False,
      "zugang_info meldet 'abgeschaltet' (Oberflaeche blendet aus)")
# ── Punkt f: nur_gemeinsam schlaegt den persoenlichen Zugang ──
schalter(None)
try:
    ja.speichern("m.mustermann", {"api_token": "persoenlich-1"})
except ja.JiraKontoFehler:
    pass
check(ja.aufloesen("m.mustermann")["quelle"] == ja.QUELLE_PERSOENLICH,
      "Positivkontrolle: ohne Marke gilt der persoenliche Zugang")
_ng = ja.nur_gemeinsam.set(True)
try:
    z = ja.aufloesen("m.mustermann")
finally:
    ja.nur_gemeinsam.reset(_ng)
check(z["quelle"] == ja.QUELLE_SAMMEL and z["client"].schreiben is False,
      "Lauf der Erweiterung: gemeinsamer Lesezugang trotz eigenem Token", z["quelle"])
check(ja.aufloesen("m.mustermann")["quelle"] == ja.QUELLE_PERSOENLICH,
      "nach dem Zuruecksetzen wieder der persoenliche Zugang")
schalter(False)
n = ja.alle_entfernen()
check(n == 2, "alle_entfernen loescht beide Zugaenge", str(n))
_rest = ja.KONTEN_DATEI.read_text(encoding="utf-8") if ja.KONTEN_DATEI.exists() else "{}"
check(json.loads(_rest) == {}, "Kontendatei ist leer")
check("persoenlich-1" not in _rest, "kein Token-Rest")
schalter(None)

# ═══════════════════════════════════════════════════════════════════════════
section("4. Regeln am Syntaxbaum")
# ═══════════════════════════════════════════════════════════════════════════
try:
    baeume = {p: ast.parse(p.read_text(encoding="utf-8")) for p in (KONTEN, MAIN, SKILL)}
    baum_main = baeume[MAIN]
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Quelltext nicht lesbar: {e}")
    sys.exit(2)
# Weitere Konstruktionsstellen (Support-Suche, Loesungsarchiv, Assistent)
baeume[ROOT / "backend/loesungsarchiv.py"] = ast.parse(
    (ROOT / "backend/loesungsarchiv.py").read_text(encoding="utf-8"))
baeume[ASSIST] = ast.parse(ASSIST.read_text(encoding="utf-8"))
baum_assist = baeume[ASSIST]

schreibstellen = []
for pfad, baum in baeume.items():
    for fn in ast.walk(baum):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "JiraClient"
                    and any(k.arg == "schreiben" for k in n.keywords)):
                schreibstellen.append((pfad.name, fn.name))
check(schreibstellen == [(KONTEN.name, "aufloesen")],
      "schreiben=True NUR im persoenlichen Zweig von aufloesen", str(schreibstellen))

usc = next((n for n in ast.walk(baum_main) if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "update_skill_config"), None)
adm = next((n for n in ast.walk(baum_main) if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "jira_admin_accounts"), None)
if usc is None or adm is None:
    print("ABBRUCH: update_skill_config/jira_admin_accounts nicht gefunden")
    sys.exit(2)


def _aufrufe(knoten, name):
    return [n for n in ast.walk(knoten) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == name]


speichern = [c.lineno for c in _aufrufe(usc, "update_skill_config")]
entfernen = [c.lineno for c in _aufrufe(usc, "alle_entfernen")]
check(bool(speichern) and any(z > min(speichern) for z in entfernen),
      "Abschalten loescht NACH dem Speichern alle persoenlichen Token",
      f"speichern={speichern} entfernen={entfernen}")
check(bool(_aufrufe(adm, "persoenlich_erlaubt")), "Admin-Liste meldet den Schalter")

# ── Punkt f am Syntaxbaum ──
def _fn(baum, name):
    return next((n for n in ast.walk(baum) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == name), None)


ac, al = _fn(baum_assist, "_client"), _fn(baum_assist, "_agent_lauf")
hl = _fn(baum_main, "jira_assist_health")
if ac is None or al is None or hl is None:
    print("ABBRUCH: jira_assist._client/_agent_lauf oder health-Route nicht gefunden")
    sys.exit(2)
check(bool(_aufrufe(ac, "sammel_client")) and not _aufrufe(ac, "aufloesen"),
      "jira_assist._client: gemeinsamer Lesezugang, kein persoenlicher")
check(bool(_aufrufe(hl, "sammel_client")) and not _aufrufe(hl, "aufloesen"),
      "health-Route fragt den gemeinsamen Lesezugang")
setz = [c for c in _aufrufe(al, "set") if isinstance(c.func.value, ast.Attribute)
        and c.func.value.attr == "nur_gemeinsam" and c.args
        and isinstance(c.args[0], ast.Constant) and c.args[0].value is True]
warte = [c.lineno for c in ast.walk(al) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
         and c.func.attr == "wait_for"]
check(bool(setz) and bool(warte) and min(c.lineno for c in setz) < min(warte),
      "Assistentenlauf setzt nur_gemeinsam VOR dem Agentenlauf",
      f"set={[c.lineno for c in setz]} wait_for={warte}")
zurueck = [c for t in ast.walk(al) if isinstance(t, ast.Try) for f in t.finalbody
           for c in ast.walk(f) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
           and c.func.attr == "reset" and isinstance(c.func.value, ast.Attribute)
           and c.func.value.attr == "nur_gemeinsam"]
check(bool(zurueck), "...und nimmt es im finally zurueck")

# ═══════════════════════════════════════════════════════════════════════════
section("5. Einstellungen → Jira")
# ═══════════════════════════════════════════════════════════════════════════
html = SETTINGS.read_text(encoding="utf-8")
ro = re.search(r'<input[^>]*\bid="jira-read-only"[^>]*>', html)
check(ro is not None and re.search(r"\bchecked\b", ro.group(0)) and re.search(r"\bdisabled\b", ro.group(0)),
      "Nur-Lesen des gemeinsamen Zugangs: angehakt UND gesperrt", ro.group(0) if ro else "fehlt")
pe = re.search(r'<input[^>]*\bid="jira-persoenlich"[^>]*>', html)
check(pe is not None and not re.search(r"\bdisabled\b", pe.group(0)),
      "Schalter 'Persoenliche Zugaenge erlauben' vorhanden und bedienbar")
conn = html.find('id="ji-sect-conn-body"')
acc = html.find('id="ji-sect-acc"')
check(conn >= 0 and pe is not None and conn < pe.start() < acc,
      "Schalter steht im Container 'Verbindung'")

print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
