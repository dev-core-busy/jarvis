#!/usr/bin/env python3
"""Waechter fuer SAP und VEMAS als zusaetzliche Quelle unter /support.

Laeuft OHNE fastapi: die zu pruefenden Funktionen werden per ``ast`` aus
``backend/main.py`` GESCHNITTEN und wirklich AUSGEFUEHRT – ein Import zoege den
halben Server nach, und eine reine Quelltext-Suche wuerde die eigene Begruendung
im Kommentar mitlesen.

Geprueft wird die REGEL, nicht eine gepflegte Liste:
- die Freigabe ist die ERSTE Schranke im Lauf (Reihenfolge wird GEMESSEN, nicht
  am Vorkommen abgelesen: ein Aufruf, der hinter den Agentenlauf rutscht, waere
  sonst weiter gruen);
- kein anderer Codepfad startet den Agentenlauf an ``_support_fach_block``
  vorbei;
- Absage-Bloecke bleiben aus der KI-Gesamtzusammenfassung heraus.

DRIFT-SCHRANKE mit Exit 2: taucht in den geschnittenen Funktionen ein
``_support_fach_*``-Name auf, der weder geschnitten noch gestubbt ist, bricht
der Lauf ab – ein NameError tief in einer Methode landet sonst im breiten
``except`` und sieht wie ein Codefehler aus.
"""
import ast
import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def abschnitt(t):
    print("\n\033[1m%s\033[0m" % t)


def check(name, cond, detail=""):
    """(Beschreibung, Bedingung) – NICHT umgekehrt."""
    global ok, fail
    if isinstance(name, bool) or not isinstance(name, str):
        print("\033[31mABBRUCH: check() falsch herum aufgerufen "
              "(erst Beschreibung, dann Bedingung)\033[0m")
        sys.exit(2)
    if bool(cond):
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – " + str(detail)) if detail else ""))


def abbruch(text):
    print("\033[31mABBRUCH: %s\033[0m" % text)
    sys.exit(2)


MAIN = ROOT / "backend" / "main.py"
QUELL = MAIN.read_text(encoding="utf-8")
BAUM = ast.parse(QUELL)

# ── Knoten einsammeln ──────────────────────────────────────────────────────
FUNKTIONEN = {}
ZUWEISUNGEN = {}
for n in BAUM.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        FUNKTIONEN[n.name] = n
    elif isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name):
                ZUWEISUNGEN[t.id] = n

GESCHNITTEN = ["_support_fach_erlaubt", "_support_fach_konfiguriert",
               "_support_fach_hinweis_block", "_support_fach_block", "_flatten"]
KONSTANTEN = ["_SUPPORT_FACH", "_SUPPORT_FACH_SCORE", "_SUPPORT_FACH_TIMEOUT"]

for name in GESCHNITTEN:
    if name not in FUNKTIONEN:
        abbruch("Funktion %s nicht in backend/main.py gefunden" % name)
for name in KONSTANTEN:
    if name not in ZUWEISUNGEN:
        abbruch("Konstante %s nicht in backend/main.py gefunden" % name)


# ── Attrappen ──────────────────────────────────────────────────────────────
class _Client:
    def __init__(self, configured=True):
        self.configured = configured


_ZUSTAND = {
    "sap_frei": True, "vemas_frei": True,
    "sap_skill": True, "vemas_skill": True,
    "sap_conf": True, "vemas_conf": True,
    "hinweis": "",
    "antwort": "Umsatz Q3: 1,2 Mio EUR.",
    "wirft": None,
    "laeufe": [],          # Spur: welcher Lauf wurde wirklich gestartet
    "spur": [],            # Spur: Reihenfolge der Schranken
}


def _user_may_use_sap(u):
    _ZUSTAND["spur"].append("freigabe:sap")
    return _ZUSTAND["sap_frei"]


def _user_may_use_vemas(u):
    _ZUSTAND["spur"].append("freigabe:vemas")
    return _ZUSTAND["vemas_frei"]


def _skill_active(name):
    return _ZUSTAND.get(name + "_skill", True)


def _sap_zugang(u):
    _ZUSTAND["spur"].append("zugang:sap")
    return {"client": _Client(_ZUSTAND["sap_conf"]), "quelle": "persoenlich",
            "hinweis": _ZUSTAND["hinweis"]}


def _vemas_zugang(u):
    _ZUSTAND["spur"].append("zugang:vemas")
    return {"client": _Client(_ZUSTAND["vemas_conf"]), "quelle": "sammel",
            "hinweis": _ZUSTAND["hinweis"]}


def _support_fach_zugang(system, user):
    return _sap_zugang(user) if system == "sap" else _vemas_zugang(user)


def _load_sap_instructions(u):
    return ""


def _load_vemas_instructions(u):
    return ""


async def _support_fach_lauf(system, task, user):
    _ZUSTAND["spur"].append("lauf:" + system)
    _ZUSTAND["laeufe"].append((system, task, user))
    if _ZUSTAND["wirft"] is not None:
        raise _ZUSTAND["wirft"]
    return _ZUSTAND["antwort"]


_stub_sap = types.ModuleType("backend.sap_analyses")
_stub_sap.build_task = lambda question="", instructions="", lang="de", **kw: \
    ("SAP-VORSPANN\n" + question) if question else ""
_stub_vemas = types.ModuleType("backend.vemas_analyses")
_stub_vemas.build_task = lambda question="", instructions="", lang="de", **kw: \
    ("VEMAS-VORSPANN\n" + question) if question else ""
sys.modules["backend.sap_analyses"] = _stub_sap
sys.modules["backend.vemas_analyses"] = _stub_vemas

NS = {"asyncio": asyncio, "print": print,
      "_user_may_use_sap": _user_may_use_sap, "_user_may_use_vemas": _user_may_use_vemas,
      "_skill_active": _skill_active, "_sap_zugang": _sap_zugang,
      "_vemas_zugang": _vemas_zugang, "_support_fach_zugang": _support_fach_zugang,
      "_load_sap_instructions": _load_sap_instructions,
      "_load_vemas_instructions": _load_vemas_instructions,
      "_support_fach_lauf": _support_fach_lauf}

modul = ast.Module(body=[ZUWEISUNGEN[k] for k in KONSTANTEN]
                        + [FUNKTIONEN[k] for k in GESCHNITTEN],
                   type_ignores=[])
exec(compile(ast.fix_missing_locations(modul), "<main-schnitt>", "exec"), NS)

# Drift-Schranke: jeder _support_fach_*-Name in den geschnittenen Funktionen
# muss aufloesbar sein, sonst stirbt der Test spaeter still im except.
for fname in GESCHNITTEN:
    for n in ast.walk(FUNKTIONEN[fname]):
        if isinstance(n, ast.Name) and n.id.startswith("_support_fach") \
                and n.id not in NS:
            abbruch("%s benutzt %s – weder geschnitten noch gestubbt" % (fname, n.id))


def lauf(co):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(co)


def reset(**kw):
    _ZUSTAND.update({"sap_frei": True, "vemas_frei": True, "sap_skill": True,
                     "vemas_skill": True, "sap_conf": True, "vemas_conf": True,
                     "hinweis": "", "antwort": "Umsatz Q3: 1,2 Mio EUR.",
                     "wirft": None, "laeufe": [], "spur": []})
    _ZUSTAND.update(kw)


# ═══════════════════════════════════════════════════════════════════════════
abschnitt("1. Die Tabelle deckt beide Fachsysteme ab")
FACH = NS["_SUPPORT_FACH"]
check("SAP und VEMAS stehen in _SUPPORT_FACH", set(FACH) == {"sap", "vemas"}, sorted(FACH))
for k, f in FACH.items():
    check("%s: alle Felder belegt" % k,
          all(f.get(x) for x in ("quelle", "skill", "titel", "bereich", "modul",
                                 "label", "nicht_konfiguriert")))
check("Quellen-Kennungen sind SAP/VEMAS (Filter + Abzeichen)",
      {f["quelle"] for f in FACH.values()} == {"SAP", "VEMAS"})


abschnitt("2. Freigabe: Berechtigung UND aktiver Skill, fail-closed")
reset()
check("freigegeben + Skill an -> erlaubt", NS["_support_fach_erlaubt"]("sap", "u") is True)
reset(sap_frei=False)
check("ohne Freigabe -> nein", NS["_support_fach_erlaubt"]("sap", "u") is False)
reset(sap_skill=False)
check("Skill aus -> nein (die sap_*-Werkzeuge gibt es dann nicht)",
      NS["_support_fach_erlaubt"]("sap", "u") is False)
reset(vemas_frei=False)
check("VEMAS ohne Freigabe -> nein", NS["_support_fach_erlaubt"]("vemas", "u") is False)
reset()
check("unbekanntes System -> nein (fail-closed)",
      NS["_support_fach_erlaubt"]("erp", "u") is False)


abschnitt("3. Der Agentenlauf startet NUR hinter der Freigabe")
reset(sap_frei=False)
b = lauf(NS["_support_fach_block"]("sap", "Umsatz?", "u", "de"))
check("ohne Freigabe: KEIN Agentenlauf", _ZUSTAND["laeufe"] == [], _ZUSTAND["laeufe"])
check("ohne Freigabe: KEIN Zugang aufgeloest (kein Orakel)",
      not any(s.startswith("zugang") for s in _ZUSTAND["spur"]), _ZUSTAND["spur"])
check("ohne Freigabe: Block sagt es im Klartext",
      b and "freigegeben" in b["summary"], b)
check("ohne Freigabe: Block ist aus der KI-Zusammenfassung heraus",
      b and b.get("no_summary") is True)

reset(sap_frei=False, sap_skill=False, vemas_frei=False, vemas_skill=False)
lauf(NS["_support_fach_block"]("vemas", "Projekte?", "api", "de"))
check("API-Schluessel-Benutzer 'api' loest keinen Lauf aus", _ZUSTAND["laeufe"] == [])

# Die REIHENFOLGE wird gemessen: rutscht die Freigabepruefung hinter den Lauf,
# stuende 'lauf:sap' vor 'freigabe:sap' – ein Test, der nur ihr VORKOMMEN
# prueft, bliebe dann gruen.
reset()
lauf(NS["_support_fach_block"]("sap", "Umsatz?", "u", "de"))
check("Reihenfolge gemessen: Freigabe -> Zugang -> Lauf",
      _ZUSTAND["spur"] == ["freigabe:sap", "zugang:sap", "lauf:sap"], _ZUSTAND["spur"])


abschnitt("4. Nicht konfiguriert: ehrliche Absage statt leerem Ergebnis")
reset(sap_conf=False)
b = lauf(NS["_support_fach_block"]("sap", "Umsatz?", "u", "de"))
check("kein Zugang -> kein Agentenlauf", _ZUSTAND["laeufe"] == [])
check("kein Zugang -> Block nennt den Weg", b and "Einstellungen" in b["summary"], b)
check("kein Zugang -> no_summary", b and b.get("no_summary") is True)
check("Absage-Block bleibt sichtbar (voller Anzeigewert)",
      b and b["score"] == NS["_SUPPORT_FACH_SCORE"])


abschnitt("5. Erfolgsfall")
reset()
b = lauf(NS["_support_fach_block"]("sap", "Wie war der Umsatz?", "u", "de"))
check("genau EIN Lauf", len(_ZUSTAND["laeufe"]) == 1)
check("der Auftrag kommt aus build_task des Fachmoduls (Vorspann drin)",
      _ZUSTAND["laeufe"][0][1].startswith("SAP-VORSPANN"), _ZUSTAND["laeufe"][0][1])
check("die Frage des Benutzers steht im Auftrag",
      "Wie war der Umsatz?" in _ZUSTAND["laeufe"][0][1])
check("der Lauf traegt den angemeldeten Benutzer", _ZUSTAND["laeufe"][0][2] == "u")
check("source = SAP (Filter + Abzeichen)", b["source"] == "SAP")
check("Antwort steht im Block", "1,2 Mio" in b["summary"])
check("full_text traegt die reine Antwort", b["full_text"] == _ZUSTAND["antwort"])
check("Link fuehrt in den Bereich", b["link"] == "/sap")
check("KEIN no_summary (echte Quelle)", not b.get("no_summary"))

reset()
b = lauf(NS["_support_fach_block"]("vemas", "Projekte?", "u", "de"))
check("VEMAS nimmt sein eigenes Modul",
      _ZUSTAND["laeufe"][0][1].startswith("VEMAS-VORSPANN"))
check("VEMAS: source/link stimmen", b["source"] == "VEMAS" and b["link"] == "/vemas")

reset(antwort="")
b = lauf(NS["_support_fach_block"]("sap", "Umsatz?", "u", "de"))
check("leere Antwort -> gar kein Block (kein leerer Kasten)", b is None)


abschnitt("6. Rueckfall auf den Sammelzugang bleibt SICHTBAR")
reset(hinweis="Persoenlicher Zugang nicht nutzbar – gelesen mit dem Sammelzugang.")
b = lauf(NS["_support_fach_block"]("sap", "Umsatz?", "u", "de"))
check("Hinweis steht im angezeigten Text", "Sammelzugang" in b["summary"], b["summary"])
check("Hinweis steht NICHT in full_text (der wird weitergegeben)",
      "Sammelzugang" not in b["full_text"], b["full_text"])


abschnitt("7. Fehler und Zeitdeckel enden in einem benannten Block")
reset(wirft=asyncio.TimeoutError())
b = lauf(NS["_support_fach_block"]("sap", "Umsatz?", "u", "de"))
check("Zeitueberschreitung -> Block nennt den Deckel",
      b and str(int(NS["_SUPPORT_FACH_TIMEOUT"])) in b["summary"], b)
check("Zeitueberschreitung -> Verweis auf den Bereich ohne Deckel",
      b and "/sap" in b["summary"])
reset(wirft=RuntimeError("Verbindung weg"))
b = lauf(NS["_support_fach_block"]("sap", "Umsatz?", "u", "de"))
check("Fehler -> Block nennt den Grund", b and "Verbindung weg" in b["summary"], b)
check("Fehler -> no_summary", b and b.get("no_summary") is True)


class _Abbruch(asyncio.CancelledError):
    pass


reset(wirft=_Abbruch())
try:
    lauf(NS["_support_fach_block"]("sap", "Umsatz?", "u", "de"))
    _durch = False
except asyncio.CancelledError:
    _durch = True
check("Abbruch des Benutzers wird DURCHGEREICHT, nicht zum Fehlerblock", _durch)


abschnitt("8. Kein zweiter Weg an der Schranke vorbei")
run_q = FUNKTIONEN.get("_support_run_query")
if run_q is None:
    abbruch("_support_run_query nicht gefunden")
_aufrufer = {}
for name, fn in FUNKTIONEN.items():
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id in ("_support_fach_lauf", "_support_fach_block"):
            _aufrufer.setdefault(n.func.id, set()).add(name)
check("_support_fach_lauf wird AUSSCHLIESSLICH aus _support_fach_block gerufen",
      _aufrufer.get("_support_fach_lauf") == {"_support_fach_block"},
      _aufrufer.get("_support_fach_lauf"))
check("_support_fach_block wird aus _support_run_query gerufen",
      "_support_run_query" in _aufrufer.get("_support_fach_block", set()))
check("_support_fach_block prueft die Freigabe selbst (nicht der Aufrufer)",
      any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
          and n.func.id == "_support_fach_erlaubt"
          for n in ast.walk(FUNKTIONEN["_support_fach_block"])))
check("_support_run_query verlaesst sich NICHT auf eine eigene Freigabepruefung",
      not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_support_fach_erlaubt" for n in ast.walk(run_q)))


abschnitt("9. Absage-Bloecke gehen nicht in die KI-Gesamtzusammenfassung")
summ = FUNKTIONEN.get("_support_ai_summary")
if summ is None:
    abbruch("_support_ai_summary nicht gefunden")
_q = ast.dump(summ)
check("_support_ai_summary filtert 'no_summary'", "no_summary" in _q)
check("die Quellenliste wird gefiltert, nicht 'blocks' roh gelesen",
      "_quellen" in _q)
_txt_summ = ast.get_source_segment(QUELL, summ) or ""
check("die genannte Trefferzahl zaehlt die GEFILTERTEN Quellen",
      "len(_quellen)" in _txt_summ and "len(blocks)" not in _txt_summ)


abschnitt("10. Status-Endpunkt meldet Freigabe UND Konfiguration getrennt")
st = FUNKTIONEN.get("support_status")
if st is None:
    abbruch("support_status nicht gefunden")
_txt_st = ast.get_source_segment(QUELL, st) or ""
check("_allowed wird gemeldet", "_allowed" in _txt_st)
check("_configured wird gemeldet", "_configured" in _txt_st)
check("die Freigabe kommt aus _support_fach_erlaubt", "_support_fach_erlaubt" in _txt_st)
check("der Zugang wird NUR fuer Freigegebene aufgeloest "
      "(sonst kostet er jeden Statusabruf eine Entschluesselung)",
      "_erlaubt and _support_fach_konfiguriert" in _txt_st)
check("die Systeme kommen aus der Tabelle, nicht aus einer zweiten Liste",
      "in _SUPPORT_FACH" in _txt_st)


abschnitt("11. Oberflaeche /support")
HTML = (ROOT / "frontend" / "support.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "js" / "support.js").read_text(encoding="utf-8")
for k in ("sap", "vemas"):
    check("%s: Kaestchen vorhanden" % k, 'id="sup-opt-%s"' % k in HTML)
    check("%s: Huelle startet VERSTECKT im Markup (kein Aufblitzen)" % k,
          'id="sup-opt-%s-wrap" class="hidden"' % k in HTML)
    check("%s: Kaestchen startet gesperrt im Markup" % k,
          'id="sup-opt-%s" disabled' % k in HTML)
    check("%s: steht im Quellen-Filter" % k,
          '<option value="%s">' % k.upper() in HTML)
    check("%s: Flag wird gesendet" % k, ("%s: use" % k) in JS)
check("die Sichtbarkeit folgt _allowed", "_allowed'" in JS or "_allowed']" in JS)
check("die Klickbarkeit folgt _configured", "_configured'" in JS or "_configured']" in JS)
check("Vorgabe AUS (ein Agentenlauf laeuft nicht nebenbei mit)",
      "getPref(k, false)" in JS)
check("ein verstecktes/gesperrtes Kaestchen loest nichts aus",
      "classList.contains('hidden')" in JS and "!el.disabled" in JS
      and "function fachAn(" in JS)
check("das Relevanz-Abzeichen behauptet keine gemessene Relevanz",
      "sup.score_info_fach" in JS)

I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
for key in ("sup.opt_sap", "sup.opt_vemas", "sup.opt_fach_hint",
            "sup.opt_fach_unconf", "sup.score_info_fach"):
    check("i18n %s: DE und EN belegt" % key, I18N.count("'%s':" % key) == 2,
          I18N.count("'%s':" % key))


print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
