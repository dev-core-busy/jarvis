#!/usr/bin/env python3
"""Fehleranalyse: Dossier zu einem Lauf + Deutung durch das Modell des Admins.

Der Messaufbau stellt den Vorfall vom 2026-10-26 nach (DEV): `filesystem write`
kam ohne `path` an, weil die Modell-Antwort am Laengenlimit abgeschnitten war,
und die Pfadpruefung meldete "Schreiben ist nur im Arbeitsbereich erlaubt".
Das Dossier muss genau das sichtbar machen – die Argumente des Aufrufs, den
Abbruch, die Journalzeile und die Quelltextstelle der Meldung.

Hermetisch: `conv_log` schreibt in einen Sandkasten (Exit 2, wenn ein Pfad
herauszeigt), `backend.config` ist eine Attrappe (der echte Import schreibt die
Live-settings.json zurueck), Journal und Sicherheitsprotokoll werden gestellt.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import json
import shutil
import sys
import tempfile
import types as _pytypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if not isinstance(label, str) or isinstance(cond, str):
        print("TESTFEHLER: check(Text, Bedingung) vertauscht")
        sys.exit(2)
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def abbruch(grund):
    print(f"ABBRUCH (Exit 2): {grund}")
    shutil.rmtree(SANDKASTEN, ignore_errors=True)
    sys.exit(2)


SANDKASTEN = Path(tempfile.mkdtemp(prefix="fehleranalyse_"))

# ── backend.config als Attrappe ─────────────────────────────────────────────
_PROFIL = {"id": "p1", "name": "Testprofil", "provider": "openai_compatible", "model": "probe-modell"}


class _Cfg:
    def profile_for_user(self, user):
        return dict(_PROFIL) if user == "admin" else None


_cfg_mod = _pytypes.ModuleType("backend.config")
_cfg_mod.config = _Cfg()
sys.modules["backend.config"] = _cfg_mod

from backend import conv_log, fehleranalyse as fa, llm, sicherheits_log  # noqa: E402

conv_log._CONV_DIR = SANDKASTEN / "conv"
conv_log._INDEX = conv_log._CONV_DIR / "index.jsonl"
conv_log._OLD_FILE = SANDKASTEN / "gibt_es_nicht.json"
sicherheits_log.DATEI = SANDKASTEN / "sicherheit.jsonl"

print("\n0. Positivkontrolle: der Sandkasten haelt")
for p in (conv_log._CONV_DIR, conv_log._INDEX, conv_log._OLD_FILE, sicherheits_log.DATEI):
    if SANDKASTEN not in Path(p).parents:
        abbruch(f"{p} zeigt aus dem Sandkasten heraus")
check("alle Ablagen liegen im Sandkasten", True)

print("\n1. Der Verlauf haelt Argumente und Abbruch fest")
a = conv_log.args_fuer_verlauf({"action": "write", "_username": "x",
                                "content": "y" * 5000, "liste": [1, 2]})
check("Modell-Argument bleibt", a.get("action") == "write", str(a)[:120])
check("interne Felder des Dispatch fallen weg", "_username" not in a)
check("⚠ ein langer Wert ist gekuerzt UND beziffert",
      "[gekuerzt, 5000 Zeichen gesamt]" in str(a.get("content")), str(a.get("content"))[-60:])
check("verschachtelte Werte bleiben erhalten", a.get("liste") == [1, 2])
check("Nicht-Dict ergibt leeres Dict", conv_log.args_fuer_verlauf(None) == {})
msgs, _ = conv_log._prepare_messages([{"role": "tool", "tool": "filesystem", "content": "x",
                                       "args": {"action": "write"}, "abbruch": "laengenlimit"}])
check("⚠ _prepare_messages reicht args durch", msgs and msgs[0].get("args") == {"action": "write"})
check("⚠ _prepare_messages reicht abbruch durch", msgs and msgs[0].get("abbruch") == "laengenlimit")

print("\n2. abbruch_grund: alle drei Anbieter")
R = llm.LLMResponse
check("OpenAI-kompatibel: finish_reason=length",
      llm.abbruch_grund(R(parts=[], raw={"choices": [{"finish_reason": "length"}]})) == "laengenlimit")
check("OpenAI-kompatibel: stop ist kein Abbruch",
      llm.abbruch_grund(R(parts=[], raw={"choices": [{"finish_reason": "stop"}]})) == "")
check("Anthropic: stop_reason=max_tokens",
      llm.abbruch_grund(R(parts=[], raw=_pytypes.SimpleNamespace(stop_reason="max_tokens"))) == "laengenlimit")
_fr = _pytypes.SimpleNamespace(name="MAX_TOKENS")
check("Gemini: finish_reason MAX_TOKENS",
      llm.abbruch_grund(R(parts=[], raw=_pytypes.SimpleNamespace(
          candidates=[_pytypes.SimpleNamespace(finish_reason=_fr)]))) == "laengenlimit")
check("Rohantwort ohne Angabe: kein Abbruch", llm.abbruch_grund(R(parts=[], raw=None)) == "")
check("kaputte Rohantwort wirft nicht", llm.abbruch_grund(object()) == "")

print("\n3. Der Vorfall als Dossier")
MELDUNG = ("Zugriff verweigert: Schreiben ist nur im Arbeitsbereich "
           "(/tmp oder data/documents) erlaubt.")
conv_log.log_conversation(
    task="liefere eine Befundliste als csv", model="probe-modell", client_ip="192.0.2.1",
    client_type="browser", system_prompt="SYS",
    messages=[{"role": "user", "content": "liefere eine Befundliste als csv"},
              {"role": "tool", "tool": "mcp_x_list", "content": "befund_id,datum\n1,2",
               "args": {"lab_code": "an1"}, "abbruch": ""},
              {"role": "tool", "tool": "filesystem", "content": MELDUNG,
               "args": {"action": "write"}, "abbruch": "laengenlimit"},
              {"role": "tool", "tool": "shell_execute", "content": "z" * 4000,
               "args": {"command": "python3 x.py"}, "abbruch": ""},
              {"role": "assistant", "content": "Fertig."}],
    steps=4, duration_ms=40000, username="firma\\m.mustermann")
kopf = conv_log.get_conversations(limit=1)[0]
LAUF = kopf["id"]
beginn, ende = fa.zeitfenster(kopf)
check("Zeitfenster umfasst den ganzen Lauf",
      ende - beginn >= 40 + fa.FENSTER_VOR_S + fa.FENSTER_NACH_S - 0.01, f"{ende - beginn:.1f}")

JOURNAL = [
    {"zeit": "2026-10-26T06:40:17+01:00", "prozess": "start_jarvis.sh",
     "text": "[AGENT] BLOCKED filesystem action='write' path=None fuer 'm.mustermann': "
             "Schreiben ist nur im Arbeitsbereich (/tmp oder data/documents) erlaubt"},
    {"zeit": "2026-10-26T06:40:18+01:00", "prozess": "start_jarvis.sh",
     "text": "[Telegram] Kein Bot-Token konfiguriert – Bot nicht gestartet."},
    {"zeit": "2026-10-26T06:40:19+01:00", "prozess": "start_jarvis.sh",
     "text": "[AGENT abc] run_task gestartet fuer 'e.beispiel'"},
    {"zeit": "2026-10-26T06:40:20+01:00", "prozess": "jarvis-security",
     "text": "{\"art\": \"admin_aenderung\"}"},
]
_journal_aufrufe = []


async def _journal(b, e, admin):
    _journal_aufrufe.append((b, e, admin))
    return list(JOURNAL), ""

sicherheits_log.lesen = lambda *a, **k: [
    {"ts": kopf["ts"] - 5, "art": "fs-deny", "benutzer": "m.mustermann", "ergebnis": "grenze"},
    {"ts": kopf["ts"] - 99999, "art": "alt", "benutzer": "m.mustermann"}]

erg = asyncio.run(fa.dossier_erstellen(LAUF, "bekommt Zugriff verweigert", "admin",
                                       journal_fn=_journal))
D = erg.get("dossier") or ""
check("Positivkontrolle: Dossier entstanden", erg.get("ok") and len(D) > 200, str(erg)[:200])
if not D:
    abbruch("kein Dossier – Folgepruefungen waeren trivial")
check("Journal mit dem Zeitfenster des Laufs und dem Admin abgefragt",
      _journal_aufrufe and _journal_aufrufe[0][2] == "admin"
      and abs(_journal_aufrufe[0][0] - beginn) < 0.01)
check("⚠ die ARGUMENTE des Aufrufs stehen darin", 'Argumente: {"action": "write"}' in D)
check("⚠ der Abbruch am Laengenlimit ist markiert",
      "[2] Werkzeug filesystem  ⚠ Modell-Antwort am Laengenlimit abgeschnitten" in D)
check("die Problembeschreibung steht darin", "bekommt Zugriff verweigert" in D)
check("⚠ die Journalzeile mit dem Benutzer ist mit ★ markiert",
      "★ 06:40:17 [AGENT] BLOCKED filesystem" in D)
check("die Zeile eines anderen Benutzers ist NICHT markiert",
      "  06:40:19 [AGENT abc] run_task" in D and "★ 06:40:19" not in D)
check("Rauschzeilen fallen weg", "Kein Bot-Token" not in D)
check("Zeilen des Sicherheits-Syslogs fallen weg (stehen im eigenen Abschnitt)",
      "admin_aenderung" not in D)
check("Sicherheitsereignis im Fenster steht darin", "fs-deny" in D)
check("Sicherheitsereignis ausserhalb des Fensters fehlt", " alt " not in D)
check("⚠ die Code-Fundstelle der Meldung ist gefunden", "### backend/sandbox.py:" in D,
      D[D.find("## Code-Fundstellen"):][:300])
_quell = (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8").splitlines()
_soll = next((i + 1 for i, z in enumerate(_quell)
              if "Schreiben ist nur im Arbeitsbereich" in z), None)
check("die Fundstelle nennt die richtige Zeile", _soll is not None and f"sandbox.py:{_soll}" in D,
      f"erwartet {_soll}")
check("⚠ ein langes Ergebnis ist beziffert gekuerzt",
      f"[gekuerzt: {fa.MAX_ERGEBNIS} von 4000 Zeichen]" in D)
check("Kennzahl: ein abgeschnittener Aufruf", erg.get("kennzahlen", {}).get("abgeschnitten") == 1,
      str(erg.get("kennzahlen")))
check("der analysierte Benutzer wird zurueckgegeben (fuer das Sicherheitsprotokoll)",
      erg.get("benutzer") == "firma\\m.mustermann")

print("\n4. Grenzfaelle")
e2 = asyncio.run(fa.dossier_erstellen("gibt-es-nicht", "", "admin", journal_fn=_journal))
check("unbekannter Lauf: ok=False mit Grund", e2 == {"ok": False, "error": "Lauf nicht gefunden"})


async def _journal_kaputt(b, e, admin):
    return [], "Root-Broker nicht erreichbar"

conv_log._body_path(LAUF).unlink()
e3 = asyncio.run(fa.dossier_erstellen(LAUF, "", "admin", journal_fn=_journal_kaputt))
check("Lauf ohne Rumpf: Dossier mit Hinweis statt Absturz",
      e3.get("ok") and "nicht mehr vorhanden" in e3.get("dossier", ""))
check("Journal nicht lesbar: der Grund steht im Dossier",
      "(nicht lesbar: Root-Broker nicht erreichbar)" in e3.get("dossier", ""))
check("Altbestand ohne args wird als solcher benannt",
      "nicht protokolliert" in fa.dossier_bauen(
          kopf, {"messages": [{"role": "tool", "tool": "x", "content": "y"}]},
          [], 0, "", [], [], ""))
check("Meldungskern aus 'Praefix: Grund'", fa._meldung_aus(MELDUNG).startswith("Schreiben ist nur"))
check("keine Fundstelle fuer eine erfundene Meldung",
      fa.fundstellen(["Diese Meldung gibt es in keinem Quelltext 4711"]) == [])

print("\n5. Analyse: Profil des Admins, ohne Werkzeuge, Dossier zwischen Marken")
_aufrufe = []


class _Prov:
    async def generate_response(self, **kw):
        _aufrufe.append(dict(kw, _profil=llm.current_agent_profile.get()))
        return llm.LLMResponse(parts=[llm.LLMPart(text="### Ursache\nleerer Pfad")],
                               raw={"choices": [{"finish_reason": "stop"}]})


_echt_pfl = llm.provider_fuer_lauf
llm.provider_fuer_lauf = lambda prompt_tool_calling=None: (_Prov(), "probe-modell")
try:
    an = asyncio.run(fa.analysieren(D, "admin", "de"))
finally:
    llm.provider_fuer_lauf = _echt_pfl
check("Positivkontrolle: das Modell wurde befragt", len(_aufrufe) == 1, str(an)[:200])
k = _aufrufe[0] if _aufrufe else {}
check("⚠ waehrend des Aufrufs gilt das Profil des ADMINS",
      (k.get("_profil") or {}).get("name") == "Testprofil", str(k.get("_profil")))
check("⚠ danach ist der ContextVar zurueckgesetzt", llm.current_agent_profile.get() is None)
check("⚠ OHNE Werkzeuge (das Dossier ist Fremdtext)", k.get("tools") == [])
_inhalt = ""
try:
    _inhalt = k["contents"][0].parts[0].text
except Exception:  # noqa: BLE001
    pass
import re as _re  # noqa: E402
_m = _re.match(r"DOSSIER-([0-9a-f]{8}) ANFANG\n", _inhalt)
check("Dossier steht zwischen Marken mit Kennung", bool(_m) and
      _inhalt.endswith(f"DOSSIER-{_m.group(1)} ENDE") if _m else False)
check("die Kennung steht auch im Auftrag", bool(_m) and f"DOSSIER-{_m.group(1)}" in k.get("system_prompt", ""))
check("Ergebnis traegt Text, Modell und Profilnamen",
      an.get("ok") and "leerer Pfad" in an.get("analyse", "") and an.get("profil") == "Testprofil")


class _ProvKaputt:
    async def generate_response(self, **kw):
        raise RuntimeError("Verbindung abgelehnt")


llm.provider_fuer_lauf = lambda prompt_tool_calling=None: (_ProvKaputt(), "m")
try:
    an2 = asyncio.run(fa.analysieren("x", "admin", "de"))
finally:
    llm.provider_fuer_lauf = _echt_pfl
check("Modellfehler: ok=False mit Grund, kein Wurf",
      an2.get("ok") is False and "Verbindung abgelehnt" in an2.get("error", ""))
check("Modellfehler: ContextVar trotzdem zurueckgesetzt", llm.current_agent_profile.get() is None)

print("\n6. Der Agent schreibt Argumente und Abbruch in den Verlauf (Syntaxbaum)")
_ag = ast.parse((ROOT / "backend" / "agent.py").read_text(encoding="utf-8"))
_tool_eintraege = []
for n in ast.walk(_ag):
    if (isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "append"
            and getattr(n.func.value, "id", "") == "_conv_messages" and n.args
            and isinstance(n.args[0], ast.Dict)):
        keys = {getattr(kk, "value", None) for kk in n.args[0].keys}
        vals = {getattr(kk, "value", None): v for kk, v in zip(n.args[0].keys, n.args[0].values)}
        if vals.get("role") is not None and getattr(vals["role"], "value", "") == "tool":
            _tool_eintraege.append(keys)
check("Positivkontrolle: zwei Tool-Eintraege (Chat und headless)", len(_tool_eintraege) == 2,
      str(len(_tool_eintraege)))
check("⚠ beide tragen 'args' und 'abbruch'",
      bool(_tool_eintraege) and all({"args", "abbruch"} <= k for k in _tool_eintraege),
      str(_tool_eintraege))

print("\n7. Endpunkte: Admin-Schranke und Sicherheitsprotokoll (Syntaxbaum)")
_main = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
_routen = {}
for n in ast.walk(_main):
    if isinstance(n, ast.AsyncFunctionDef):
        for d in n.decorator_list:
            if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant) \
                    and str(d.args[0].value).startswith("/api/fehleranalyse/"):
                _routen[d.args[0].value] = n
check("Positivkontrolle: drei Routen", set(_routen) == {
    "/api/fehleranalyse/laeufe", "/api/fehleranalyse/dossier", "/api/fehleranalyse/analyse"},
    str(sorted(_routen)))
for pfad, fn in sorted(_routen.items()):
    deps = [ast.unparse(d) for d in fn.args.defaults + fn.args.kw_defaults if d is not None]
    check(f"⚠ {pfad} haengt an require_local_auth",
          any("Depends(require_local_auth)" in x for x in deps), str(deps))
_helfer = next((n for n in ast.walk(_main) if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "_fehleranalyse_dossier"), None)
_ereig = [c for c in ast.walk(_helfer) if isinstance(c, ast.Call)
          and getattr(c.func, "attr", "") == "ereignis"] if _helfer else []
check("⚠ jedes Dossier wird im Sicherheitsprotokoll vermerkt, MIT dem analysierten Benutzer",
      len(_ereig) == 1 and any(kw.arg == "analysiert" for kw in _ereig[0].keywords))
_nutzer = [n.name for n in _routen.values()
           if any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_fehleranalyse_dossier"
                  for c in ast.walk(n))]
check("Dossier UND Analyse laufen ueber diesen Helfer",
      sorted(_nutzer) == ["fehleranalyse_analyse", "fehleranalyse_dossier"], str(_nutzer))

shutil.rmtree(SANDKASTEN, ignore_errors=True)
print(f"\nERGEBNIS: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
