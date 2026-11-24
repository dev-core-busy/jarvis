#!/usr/bin/env python3
"""Waechter: sensible Laeufe benutzen NUR interne LLMs (backend/llm_standort.py).

ZUSAGE an den Betreiber (2026-11-24): ein Lauf mit dem Schalter "sensible
Daten" schickt keine Inhalte an ein externes Modell. Ist das gewaehlte Profil
extern, wechselt er automatisch auf ein internes; gibt es keines, wird der
Aufruf gesperrt statt gesendet.

Gemessen wird die WIRKUNG:
  A  Erkennung intern/extern (Adresse, Anbieter, Namen, DNS als Attrappe der
     echten Signatur ``_dns_aufloesen(host) -> list|None``)
  B  Handeinstellung ueberstimmt in beide Richtungen; "intern" fuer einen
     Cloud-Anbieter wird abgewiesen
  C  Ziel-Einstufung fuer den Riegel (der strengere Wert gewinnt)
  D  Auswahl des Ersatzprofils (bevorzugt > eingestellt > erstes erlaubtes)
  E  RIEGEL an den ECHTEN Provider-Klassen aus llm.py: im sensiblen Lauf
     erreicht ein externes Ziel den Netz-Client NIE; Positivkontrolle:
     ausserhalb (bzw. mit internem Ziel) erreicht derselbe Aufruf ihn
  F  provider_fuer_lauf / provider_fuer_bild waehlen im sensiblen Lauf intern
  G  Agent: _sensibel_profil_anwenden (aus agent.py geschnitten, ausgefuehrt)
     und Regel am AST: jeder Ausgang von _resolve_profile_for_user ruft es
  H  Verdrahtung als Regel: Prompt-Pruefung im sensiblen Rahmen, Einstellung
     nimmt nur interne Profile, Fehlertext wird nicht umgedeutet

``backend.config`` ist eine Attrappe (der echte Import schreibt settings.json).

Exit 0 = bestanden, 1 = Befund, 2 = konnte nicht laufen.
    venv/bin/python tests/test_llm_standort.py
"""
from __future__ import annotations

import ast
import asyncio
import sys
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
    print(f"\n── {t}")


# ── Attrappe backend.config (echte Form: Objekt ``config`` mit Profil-Liste) ──
class _Cfg:
    def __init__(self):
        self.profiles = []
        self.active_profile_id = ""
        self.SENSIBEL_PROFILE_ID = ""
        self.IMAGE_PROFILE_ID = ""
        self.INTERNE_NETZE = ""

    @property
    def active_profile(self):
        return next((p for p in self.profiles if p["id"] == self.active_profile_id),
                    self.profiles[0] if self.profiles else None)

    # Fassade wie config.py (provider_fuer_lauf liest sie ohne Agentenprofil)
    LLM_PROVIDER = property(lambda s: (s.active_profile or {}).get("provider", "google"))
    current_api_key = property(lambda s: (s.active_profile or {}).get("api_key", ""))
    current_api_url = property(lambda s: (s.active_profile or {}).get("api_url", ""))
    current_auth_method = property(lambda s: "api_key")
    current_session_key = property(lambda s: "")
    current_prompt_tool_calling = property(lambda s: False)
    current_model = property(lambda s: (s.active_profile or {}).get("model", ""))


_cfg_mod = types.ModuleType("backend.config")
CFG = _cfg_mod.config = _Cfg()
sys.modules["backend.config"] = _cfg_mod

try:
    from backend import llm_standort as S
    from backend import sensibel
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Module nicht ladbar: {e}")
    sys.exit(2)

# DNS ist IMMER die Attrappe – ein Waechter fragt kein Netz.
_DNS = {}
S._dns_aufloesen = lambda host: _DNS.get(host)


def _prof(pid, provider="openai_compatible", url="", standort=None, **kw):
    p = {"id": pid, "name": pid, "provider": provider, "api_url": url, "model": "m"}
    if standort is not None:
        p["standort"] = standort
    p.update(kw)
    return p


class _Sens:
    """Sensibler Lauf ohne Aufraeumen (``scope`` raeumt am Ende Dateien und
    Broker ab – hier geht es nur um das Merkmal)."""
    def __enter__(self):
        self.t = sensibel._cv.set({"beginn": 0, "dateien": [], "ablagen": [],
                                   "ergebnisse": [], "kennungen": [], "uebergeben": False})
        return self

    def __exit__(self, *a):
        sensibel._cv.reset(self.t)


# ── A ─────────────────────────────────────────────────────────────────────
section("A  Erkennung")
FAELLE = [
    ("openai_compatible", "http://localhost:11434/v1/chat/completions", "intern"),
    ("openai_compatible", "http://127.0.0.1:8000/v1", "intern"),
    ("openai_compatible", "http://[::1]:8000/v1", "intern"),
    ("openai_compatible", "https://10.20.30.40/v1", "intern"),
    ("openai_compatible", "https://192.168.5.5:8443/v1", "intern"),
    ("openai_compatible", "https://172.16.0.9/v1", "intern"),
    ("openai_compatible", "https://[fd12::5]/v1", "intern"),
    ("openai_compatible", "https://8.8.8.8/v1", "extern"),
    ("openai_compatible", "https://100.64.1.1/v1", "extern"),       # CGNAT ist nicht das eigene Netz
    ("openai_compatible", "https://api.openai.com/v1/chat/completions", "extern"),
    ("openai_compatible", "https://foo.openai.azure.com/x", "extern"),
    ("openai_compatible", "https://api.mistral.ai/v1", "extern"),
    ("openai_compatible", "http://llmserver:8000/v1", "intern"),     # Rechnername ohne Domaene
    ("openai_compatible", "https://gpu.firma.local/v1", "intern"),
    ("openai_compatible", "https://gpu.home.arpa/v1", "intern"),
    ("openai_compatible", "", "intern"),                              # Vorgabe localhost
    ("openrouter", "", "extern"),
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions", "extern"),
    ("google", "http://localhost:1/", "extern"),                      # fester Endpunkt
    ("anthropic", "", "extern"),
    ("anthropic_session", "", "extern"),
]
for prov, url, soll in FAELLE:
    ist, grund = S.auto_einstufen(prov, url)
    check(ist == soll, f"{prov} {url or '(leer)'} -> {soll}", f"{ist} ({grund})")

_DNS["llm.beispiel.de"] = ["10.1.1.1", "fd00::1"]
_DNS["cloud.beispiel.de"] = ["10.1.1.1", "8.8.4.4"]
S._dns_cache.clear()
check(S.auto_einstufen("openai_compatible", "https://llm.beispiel.de/v1")[0] == "intern",
      "DNS: nur private Adressen -> intern")
check(S.auto_einstufen("openai_compatible", "https://cloud.beispiel.de/v1")[0] == "extern",
      "DNS: eine oeffentliche Adresse genuegt -> extern")
check(S.auto_einstufen("openai_compatible", "https://weg.beispiel.de/v1")[0] == "unbekannt",
      "DNS: nicht aufloesbar -> unbekannt")
check(not S.ist_intern(_prof("u", url="https://weg.beispiel.de/v1")),
      "unbekannt gilt NICHT als intern (fail-closed)")
# Cache: dieselbe Frage fragt DNS nicht erneut
_zaehler = []
_alt = S._dns_aufloesen
S._dns_aufloesen = lambda h: (_zaehler.append(h), ["10.9.9.9"])[1]
S._dns_cache.clear()
S.auto_einstufen("openai_compatible", "https://c.beispiel.de/a")
S.auto_einstufen("openai_compatible", "https://c.beispiel.de/b")
check(len(_zaehler) == 1, "DNS-Ergebnis wird zwischengespeichert", f"{len(_zaehler)} Abfragen")
S._dns_aufloesen = _alt

# Interne Netze: Firmennetze in oeffentlich registrierten Bereichen
# (gemessen auf DEV 2026-11-24). Beispielbereich hier: 8.8.0.0/16.
S._dns_cache.clear()
_DNS["haus.beispiel.de"] = ["8.8.4.4"]
check(S.auto_einstufen("openai_compatible", "http://8.8.8.8:9081/v1")[0] == "extern"
      and S.auto_einstufen("openai_compatible", "https://haus.beispiel.de/v1")[0] == "extern",
      "Positivkontrolle: ohne Liste sind IP und Name im Bereich extern")
CFG.INTERNE_NETZE = "8.8.0.0/16, 2001:db8::/32"
ist, grund = S.auto_einstufen("openai_compatible", "http://8.8.8.8:9081/v1")
check(ist == "intern" and "8.8.0.0/16" in grund, "IP im eingetragenen internen Netz -> intern", f"{ist} {grund}")
check(S.auto_einstufen("openai_compatible", "https://haus.beispiel.de/v1")[0] == "intern",
      "Name, der ins interne Netz aufloest -> intern (Cache haelt Adressen, nicht das Urteil)")
check(S.auto_einstufen("openai_compatible", "http://[2001:db8::7]/v1")[0] == "intern",
      "IPv6 im eingetragenen Netz -> intern")
check(S.auto_einstufen("openai_compatible", "http://8.9.1.1/v1")[0] == "extern",
      "Adresse ausserhalb des eingetragenen Netzes bleibt extern")
CFG.INTERNE_NETZE = ""
check(S.netze_lesen("10.0.0.0/8, 8.8.0.0/16\n2001:db8::/32")[1] == []
      and S.netze_lesen("8.8.0.0/16, quatsch")[1] == ["quatsch"],
      "netze_lesen trennt gueltig/ungueltig")

# ── B ─────────────────────────────────────────────────────────────────────
section("B  Handeinstellung")
check(S.einstufen(_prof("a", url="http://localhost:4000/v1", standort="extern"))["standort"] == "extern",
      "lokaler Proxy von Hand extern -> extern")
check(S.einstufen(_prof("b", url="https://8.8.8.8/v1", standort="intern"))["standort"] == "intern",
      "oeffentliche Adresse von Hand intern -> intern")
e = S.einstufen(_prof("c", provider="google", standort="intern"))
check(e["standort"] == "extern", "Google von Hand intern (aus Datei) gilt NICHT", str(e))
check(S.handwert_pruefen("google", "intern")[1] != "", "Speichern: Google intern wird abgewiesen")
check(S.handwert_pruefen("anthropic", "intern")[1] != "", "Speichern: Anthropic intern wird abgewiesen")
check(S.handwert_pruefen("openai_compatible", "intern") == ("intern", ""), "Speichern: openai_compatible intern erlaubt")
check(S.handwert_pruefen("openai_compatible", "quatsch")[1] != "", "Speichern: unbekannter Wert wird abgewiesen")
check(S.einstufen(_prof("d", url="https://8.8.8.8/v1", standort="quatsch"))["standort"] == "extern",
      "ungueltiger Wert in der Datei = auto")

# ── C ─────────────────────────────────────────────────────────────────────
section("C  Ziel-Einstufung fuer den Riegel")
P_LOK = _prof("lok", url="http://localhost:4000/v1/chat/completions")
P_LOK_EXT = _prof("lok2", url="http://localhost:4000/v1/chat/completions", standort="extern")
check(S.ziel_intern("openai_compatible", "http://localhost:4000/v1/chat/completions", [P_LOK])[0],
      "Positivkontrolle: lokales Ziel ohne Handwert -> intern")
check(not S.ziel_intern("openai_compatible", "http://localhost:4000/v1/chat/completions", [P_LOK, P_LOK_EXT])[0],
      "zwei Profile, eines von Hand extern -> extern gewinnt")
check(S.ziel_intern("openai_compatible", "https://8.8.8.8/v1/chat/completions",
                    [_prof("x", url="https://8.8.8.8/v1/chat/completions", standort="intern")])[0],
      "Hand-intern eines passenden Profils gilt fuer das Ziel")
check(not S.ziel_intern("google", "", [_prof("g", provider="google", standort="intern")])[0],
      "Google bleibt fuer den Riegel extern, auch mit Hand-intern")

# ── D ─────────────────────────────────────────────────────────────────────
section("D  Ersatzprofil")
P_EXT = _prof("ext", provider="openrouter")
P_INT1 = _prof("int1", url="http://10.0.0.1/v1", allowed_users="jemand.anders")
P_INT2 = _prof("int2", url="http://10.0.0.2/v1")
P_INT3 = _prof("int3", url="http://10.0.0.3/v1")
CFG.profiles = [P_EXT, P_INT1, P_INT2, P_INT3]
CFG.SENSIBEL_PROFILE_ID = ""
check(S.sensibles_profil("max.muster", P_INT3) is P_INT3, "bevorzugtes internes Profil bleibt")
check(S.sensibles_profil("max.muster", P_EXT) is P_INT2,
      "ohne Einstellung: erstes ERLAUBTES internes (int1 ist eingeschraenkt)")
CFG.SENSIBEL_PROFILE_ID = "int1"
check(S.sensibles_profil("max.muster", P_EXT) is P_INT1,
      "eingestelltes Profil gilt unabhaengig vom Profilrecht")
CFG.SENSIBEL_PROFILE_ID = "ext"
check(S.sensibles_profil("max.muster", P_EXT) is P_INT2, "eingestelltes EXTERNES Profil wird uebergangen")
CFG.profiles = [P_EXT, P_INT1]
CFG.SENSIBEL_PROFILE_ID = ""
check(S.sensibles_profil("max.muster", P_EXT) is None, "kein erlaubtes internes -> None")

# ── E ─────────────────────────────────────────────────────────────────────
section("E  Riegel an den echten Provider-Klassen")
try:
    from backend import llm
    from backend import token_verbrauch
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: llm.py nicht ladbar ({e}) – mit dem venv starten")
    sys.exit(2)
token_verbrauch._in_erfassung.set(True)   # keine Token-Statistik in den echten Bestand


class _Erreicht(Exception):
    pass


_netz = []


class _Client:
    async def post(self, url, **kw):
        _netz.append(url)
        raise _Erreicht(url)


async def _client():
    return _Client()


llm._get_shared_client = _client
CFG.profiles = [P_EXT, P_INT2]


async def _ruf(prov, art="text"):
    _netz.clear()
    try:
        if art == "bild":
            await prov.generate_image("m", "ein Bild")
        else:
            await prov.generate_response("m", "sys", [llm.types.Content(
                role="user", parts=[llm.types.Part(text="GEHEIM")])])
        return "durch"
    except S.ExternGesperrt:
        return "gesperrt"
    except _Erreicht:
        return "netz"
    except Exception as e:  # noqa: BLE001
        return f"anders:{type(e).__name__}:{e}"


def ruf(prov, art="text"):
    return asyncio.run(_ruf(prov, art))


ext = llm.get_provider("openai_compatible", "k", "https://api.openai.com/v1/chat/completions")
inn = llm.get_provider("openai_compatible", "k", "http://10.0.0.2/v1/chat/completions")
r = ruf(ext)
check(r == "netz", "Positivkontrolle: ohne sensiblen Lauf erreicht der Aufruf das Netz", r)
with _Sens():
    r = ruf(ext)
    check(r == "gesperrt" and not _netz, "sensibel + extern: gesperrt, Netz NIE erreicht", f"{r} {_netz}")
    r = ruf(inn)
    check(r == "netz", "sensibel + intern: Aufruf geht durch", r)
    r = ruf(ext, "bild")
    check(r == "gesperrt" and not _netz, "sensibel + extern: auch generate_image gesperrt", f"{r} {_netz}")
    for name, prov in (("google", llm.get_provider("google", "k")),
                       ("anthropic", llm.get_provider("anthropic", "k")),
                       ("openrouter", llm.get_provider("openrouter", "k")),
                       ("anthropic_session", llm.get_provider("anthropic", "", auth_method="session",
                                                              session_key="s"))):
        r = ruf(prov)
        check(r == "gesperrt", f"sensibel: {name} gesperrt", r)
    # Text der Sperre: nennt den Grund, und ohne internes Profil den Weg
    CFG.profiles = [P_EXT]
    # Jede andere Ausnahme (Sperre fehlt -> der Aufruf laeuft in den
    # Netz-Stub) ist ein FAIL dieser Pruefung, kein Absturz des Waechters.
    try:
        asyncio.run(ext.generate_response("m", "s", []))
        txt = ""
    except S.ExternGesperrt as e:
        txt = str(e)
    except Exception as e:  # noqa: BLE001
        txt = f"keine Sperre: {type(e).__name__}"
    check("extern" in txt and "internes LLM-Profil" in txt,
          "ohne internes Profil nennt die Sperre den Weg (Profil einrichten)", txt[:120])
    CFG.profiles = [P_EXT, P_INT2]
# Regel: jede Klasse in llm.py, die einen Netzweg SELBST definiert, traegt den Riegel
ohne = []
for n, k in vars(llm).items():
    if isinstance(k, type) and issubclass(k, llm.LLMProvider) and k is not llm.LLMProvider \
            and k.__module__ == llm.__name__:
        for m in ("generate_response", "generate_image"):
            if m in k.__dict__ and not getattr(k.__dict__[m], "__sensibel_riegel__", False):
                ohne.append(f"{n}.{m}")
check(not ohne, "jede Provider-Klasse traegt den Riegel an ihren Netzwegen", ", ".join(ohne))
_klassen = [k for k in vars(llm).values() if isinstance(k, type) and issubclass(k, llm.LLMProvider)
            and k is not llm.LLMProvider and k.__module__ == llm.__name__]
check(len(_klassen) >= 5, "Positivkontrolle: Provider-Klassen gefunden", str(len(_klassen)))

# ── F ─────────────────────────────────────────────────────────────────────
section("F  provider_fuer_lauf / provider_fuer_bild")
CFG.profiles = [P_EXT, P_INT2]
CFG.active_profile_id = "ext"
CFG.SENSIBEL_PROFILE_ID = ""
llm.current_agent_profile.set(None)
prov, _m = llm.provider_fuer_lauf()
check(prov._standort_ziel()[0] == "openrouter", "Positivkontrolle: ohne sensiblen Lauf das globale (extern)")
with _Sens():
    prov, _m = llm.provider_fuer_lauf()
    check(prov._standort_ziel()[1].startswith("http://10.0.0.2"), "sensibel: global extern -> internes Profil",
          str(prov._standort_ziel()))
    t = llm.current_agent_profile.set(P_EXT)
    prov, _m = llm.provider_fuer_lauf()
    check(prov._standort_ziel()[1].startswith("http://10.0.0.2"), "sensibel: Agentenprofil extern -> intern")
    llm.current_agent_profile.reset(t)
    CFG.IMAGE_PROFILE_ID = "ext"
    prov, _m = llm.provider_fuer_bild()
    check(prov._standort_ziel()[1].startswith("http://10.0.0.2"), "sensibel: externes Bildprofil uebergangen")
    CFG.profiles = [P_EXT]
    prov, _m = llm.provider_fuer_lauf()
    check(asyncio.run(_ruf(prov)) == "gesperrt", "sensibel ohne internes Profil: Aufruf gesperrt")
CFG.IMAGE_PROFILE_ID = ""
CFG.profiles = [P_EXT, P_INT2]
CFG.IMAGE_PROFILE_ID = "ext"
prov, _m = llm.provider_fuer_bild()
check(prov._standort_ziel()[0] == "openrouter", "Positivkontrolle: ohne sensiblen Lauf gilt das Bildprofil")
CFG.IMAGE_PROFILE_ID = ""

# ── G ─────────────────────────────────────────────────────────────────────
section("G  Agent")
AGENT = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
baum = ast.parse(AGENT)
funks = {n.name: n for n in ast.walk(baum) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
if "_sensibel_profil_anwenden" not in funks or "_resolve_profile_for_user" not in funks:
    print("ABBRUCH: _sensibel_profil_anwenden/_resolve_profile_for_user fehlen in agent.py")
    sys.exit(2)
ns = {"_sensibel": sensibel}
exec(compile(ast.Module(body=[funks["_sensibel_profil_anwenden"], funks["_sensibel_statuszeile"]],
                        type_ignores=[]), "agent.py", "exec"), ns)


class _Ag:
    def __init__(self, prof):
        self._active_profile = prof
        self._current_username = "max.muster"

    @property
    def _eff_profile(self):
        return self._active_profile


a = _Ag(P_EXT)
ns["_sensibel_profil_anwenden"](a)
check(a._active_profile is P_EXT and a._sensibel_wechsel is None,
      "Positivkontrolle: ohne sensiblen Lauf bleibt das Profil")
with _Sens():
    a = _Ag(P_EXT)
    ns["_sensibel_profil_anwenden"](a)
    check(a._active_profile is P_INT2, "sensibel: externes Profil -> internes", str(a._active_profile))
    z = ns["_sensibel_statuszeile"](a)
    check("ext" in z and "int2" in z, "Statuszeile nennt alt und neu", z)
    a = _Ag(P_INT2)
    ns["_sensibel_profil_anwenden"](a)
    check(a._active_profile is P_INT2 and "int2" in ns["_sensibel_statuszeile"](a),
          "sensibel: internes Profil bleibt, Statuszeile nennt es")
    CFG.profiles = [P_EXT]
    a = _Ag(P_EXT)
    ns["_sensibel_profil_anwenden"](a)
    check(a._active_profile is P_EXT and "internes LLM-Profil" in ns["_sensibel_statuszeile"](a),
          "sensibel ohne internes: Profil bleibt (Riegel sperrt), Statuszeile sagt es")
    CFG.profiles = [P_EXT, P_INT2]

# Regel: jeder Ausgang von _resolve_profile_for_user nach einer Zuweisung an
# _active_profile ruft _sensibel_profil_anwenden – sonst umginge eine Rolle
# den Wechsel.
rp = funks["_resolve_profile_for_user"]
zuw = [n for n in ast.walk(rp) if isinstance(n, ast.Assign)
       and any(isinstance(t, ast.Attribute) and t.attr == "_active_profile" for t in n.targets)]
aufrufe = [n for n in ast.walk(rp) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and n.func.attr == "_sensibel_profil_anwenden"]


def _folgt_aufruf(z):
    for block in ast.walk(rp):
        for feld in ("body", "orelse"):
            stm = getattr(block, feld, None)
            if isinstance(stm, list) and z in stm:
                rest = stm[stm.index(z) + 1:]
                return any(isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                           and getattr(s.value.func, "attr", "") == "_sensibel_profil_anwenden"
                           for s in rest)
    return False


check(len(zuw) >= 2, "Positivkontrolle: Zuweisungen an _active_profile gefunden", str(len(zuw)))
check(all(_folgt_aufruf(z) for z in zuw), "jede Profilzuweisung wird vom Wechsel gefolgt",
      f"{sum(_folgt_aufruf(z) for z in zuw)}/{len(zuw)}")
# Die Statuszeile wird im Chat-Lauf gesendet
rt = funks.get("run_task")
gesendet = rt is not None and any(
    isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_sensibel_statuszeile" for n in ast.walk(rt))
check(gesendet, "run_task sendet die Statuszeile")
fae = funks.get("_friendly_api_error")
check(fae is not None and "ExternGesperrt" in ast.unparse(fae.body[0]) + ast.unparse(fae.body[1]),
      "_friendly_api_error gibt die Sperre unveraendert weiter (vor jeder Musterpruefung)")

# ── H ─────────────────────────────────────────────────────────────────────
section("H  Verdrahtung")
MAIN = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
pp = next((n for n in ast.walk(MAIN) if isinstance(n, ast.AsyncFunctionDef) and n.name == "prompt_pruefen"), None)
ok_pp = False
if pp is not None:
    for n in ast.walk(pp):
        if isinstance(n, ast.AsyncWith) and any(
                "anfrage" in ast.unparse(i.context_expr) for i in n.items):
            ok_pp = any(isinstance(k, ast.Call) and "pruefen" in ast.unparse(k.func) for k in ast.walk(n))
check(ok_pp, "Prompt-Pruefung laeuft im sensiblen Rahmen der Ablage")
CONF = ast.parse((ROOT / "backend" / "config.py").read_text(encoding="utf-8"))
sg = next((n for n in ast.walk(CONF) if isinstance(n, ast.FunctionDef) and n.name == "save_global_settings"), None)
src_sg = ast.unparse(sg) if sg else ""
check("sensibel_profile_id" in src_sg and "ist_intern" in src_sg,
      "Einstellung 'Profil fuer sensible Daten' prueft auf intern")
# Interne Netze: nur ganz oder gar nicht – ein Tippfehler darf kein Netz still
# wegfallen lassen. Regel: die Zuweisung steht unter ``if not _falsch``.
ok_n = False
for n in ast.walk(sg) if sg else []:
    if isinstance(n, ast.If) and ast.unparse(n.test) == "not _falsch":
        ok_n = any(isinstance(z, ast.Assign) and "INTERNE_NETZE" in ast.unparse(z.targets[0])
                   for z in ast.walk(n))
check(ok_n, "Interne Netze werden nur gespeichert, wenn alle Eintraege gueltig sind")
ss = next((n for n in ast.walk(MAIN) if isinstance(n, ast.AsyncFunctionDef) and n.name == "save_settings"), None)
check(ss is not None and "netze_lesen" in ast.unparse(ss) and "status_code=400" in ast.unparse(ss),
      "API weist ungueltige Netze mit Grund ab (400)")
PC = (ROOT / "frontend" / "js" / "prompt_check.js").read_text(encoding="utf-8")
TR = (ROOT / "frontend" / "js" / "tracks.js").read_text(encoding="utf-8")
check("sensibel: !!(sensEl && sensEl.checked)" in PC and "'st-f-sensibel')" in TR,
      "Prompt-Pruefung in /tracks schickt den Schalter der Ablage mit")

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
