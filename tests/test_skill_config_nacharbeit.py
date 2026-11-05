#!/usr/bin/env python3
"""Waechter: Nacharbeit nach dem Speichern einer Skill-Konfiguration.

Zwei Zusagen haengen an ``main.py::update_skill_config`` – beide loeschen
gespeicherte Geheimnisse, und beide sind am 2026-11-05 AUSGEFALLEN:

* SAP/VEMAS "Anmeldung ueber die Portal-Kachel fordern" EIN
  → ``kennwoerter_entfernen()`` nimmt allen persoenlichen Zugaengen das
  Kennwort (die Zugaenge selbst bleiben).
* Jira "Persoenliche Zugaenge erlauben" AUS
  → ``alle_entfernen()`` loescht alle persoenlichen Token.

⚠ WARUM ES DIESEN WAECHTER GIBT (bezahlter Vorfall, gemeldet vom Betreiber):
``sm.get_skill_config(name)`` gibt das **lebende** dict aus
``config._skill_states`` heraus, und ``update_skill_config`` schreibt mit
``current_config.update(data)`` in genau dieses Objekt. Die Loeschzweige hingen
an ``not gespeichert.get("kachel_anmeldung")`` – nach dem Speichern war dieser
Wert bereits der NEUE, die Bedingung also nie erfuellt. Folge: die Oberflaeche
meldete "Auf dem Server ist kein SAP-Kennwort gespeichert", und daneben stand
bei fuenf Benutzern "Kennwort noch gespeichert". Der alte Waechter prueste nur,
dass ein AUFRUF von ``kennwoerter_entfernen`` hinter dem Speichern STEHT – ein
Vorkommen, keine Wirkung.

Gemessen wird deshalb die WIRKUNG: die Endpunkt-Funktion wird aus main.py
geschnitten und mit Attrappen AUSGEFUEHRT; der Skill-Manager ist der ECHTE
(``SkillManager.__new__``, die beiden Methoden brauchen nur ``config``), die
``backend.config``-Attrappe spiegelt die Semantik des Originals und wird dagegen
geprueft. Zusaetzlich zwei Regeln am Syntaxbaum: der Vorzustand wird kopiert,
und die Loeschung haengt am ENDZUSTAND, nicht am Umschalt-Moment (sonst bleibt
ein Rest fuer immer liegen, sobald der Moment einmal verpasst wurde).

Laeuft ohne fastapi und ohne Netz. ``backend.config`` ist eine Attrappe – der
echte Import schreibt die Live-settings.json zurueck.
Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.

    python3 tests/test_skill_config_nacharbeit.py
"""
import ast
import asyncio
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if not isinstance(cond, bool):
        print(f"ABBRUCH: check() erwartet eine Bedingung, bekam {type(cond).__name__} "
              f"({label!r}) – vertauschte Argumente?")
        sys.exit(2)
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n{t}")


# Gegenprobe gibt sabotierte KOPIEN ueber die Umgebung mit – die echten Dateien
# werden nie angefasst.
MAIN = Path(os.environ.get("SKNACH_MAIN") or ROOT / "backend" / "main.py")
CONFIG_PY = Path(os.environ.get("SKNACH_CONFIG") or ROOT / "backend" / "config.py")
MANAGER_PY = Path(os.environ.get("SKNACH_MANAGER") or ROOT / "backend" / "skills" / "manager.py")


# ═══════════════════════════════════════════════════════════════════════════
section("0. Positivkontrolle: die Attrappe spiegelt backend/config.py")
# ═══════════════════════════════════════════════════════════════════════════
# Die Attrappe unten gibt in `get_skill_states` das lebende dict heraus und
# merged in `save_skill_state`. Stimmt das nicht mehr mit dem Original, messen
# alle folgenden Abschnitte eine Welt, die es nicht gibt.
try:
    _cbaum = ast.parse(CONFIG_PY.read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: config.py nicht lesbar: {e}")
    sys.exit(2)
_cfn = {n.name: n for n in ast.walk(_cbaum) if isinstance(n, ast.FunctionDef)}
_gss, _sss = _cfn.get("get_skill_states"), _cfn.get("save_skill_state")
if _gss is None or _sss is None:
    print("ABBRUCH: get_skill_states/save_skill_state in config.py nicht gefunden")
    sys.exit(2)


def _gibt_attribut_unverpackt(fn, attr: str) -> bool:
    """Gibt die Funktion `self.<attr>` ohne Kopie zurueck?"""
    for n in ast.walk(fn):
        if (isinstance(n, ast.Return) and isinstance(n.value, ast.Attribute)
                and n.value.attr == attr
                and isinstance(n.value.value, ast.Name) and n.value.value.id == "self"):
            return True
    return False


_lebend = _gibt_attribut_unverpackt(_gss, "_skill_states")
_merged = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "update" for n in ast.walk(_sss))
if not _merged:
    print("ABBRUCH: save_skill_state merged nicht mehr – Attrappe veraltet")
    sys.exit(2)
check(_merged, "save_skill_state merged den Zustand (wie die Attrappe)")
print(f"  …   gemessen: get_skill_states gibt das lebende dict heraus: "
      f"{'ja' if _lebend else 'nein'}")


# ── Attrappe fuer backend.config VOR allen Importen ─────────────────────────
_skill_states: dict = {}
_geschrieben: list = []
_cfg_mod = types.ModuleType("backend.config")


class _Cfg:
    """Spiegelt backend/config.py: lebendes dict heraus, merge beim Speichern.

    Ohne Dateizugriff – der echte Import schreibt die Live-settings.json."""

    def get_skill_states(self):
        return _skill_states

    def save_skill_state(self, name, state):
        if name not in _skill_states:
            _skill_states[name] = {}
        _skill_states[name].update(state)
        _geschrieben.append(name)

    def get_setting(self, key, default=None):
        return default

    def save_setting(self, key, value):
        pass


_cfg_mod.config = _Cfg()
sys.modules["backend.config"] = _cfg_mod

try:
    import backend  # noqa: E402
    backend.config = _cfg_mod
    from backend.skills.manager import SkillManager  # noqa: E402
    from backend import secret_reveal as _sr_echt  # noqa: E402
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: SkillManager/secret_reveal nicht importierbar: {e}")
    sys.exit(2)

# Der ECHTE Manager, aber ohne __init__ (das sucht Skills auf der Platte);
# get_skill_config/update_skill_config brauchen ausschliesslich `config`.
SM = SkillManager.__new__(SkillManager)
for _m in ("get_skill_config", "update_skill_config"):
    if not callable(getattr(SM, _m, None)):
        print(f"ABBRUCH: SkillManager.{_m} fehlt")
        sys.exit(2)

# Premisse messen: gibt der Bestand das lebende dict heraus? Dann ist ein
# Schnappschuss in main.py Pflicht (Abschnitt 2).
_skill_states.clear()
_skill_states["probe"] = {"enabled": True, "config": {"schalter": False}}
_vorher_obj = SM.get_skill_config("probe")
SM.update_skill_config("probe", {"schalter": True})
ALIAS = _vorher_obj.get("schalter") is True
print(f"  …   gemessen: ein vor dem Speichern gelesener Stand aendert sich mit: "
      f"{'ja' if ALIAS else 'nein'}")


# ═══════════════════════════════════════════════════════════════════════════
section("1. Endpunkt schneiden und ausfuehren")
# ═══════════════════════════════════════════════════════════════════════════
try:
    _mbaum = ast.parse(MAIN.read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: main.py nicht lesbar: {e}")
    sys.exit(2)
USC = next((n for n in ast.walk(_mbaum) if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "update_skill_config"), None)
if USC is None:
    print("ABBRUCH: update_skill_config in main.py nicht gefunden")
    sys.exit(2)


class _Antwort:
    """Attrappe fuer JSONResponse – merkt Inhalt und Status."""

    def __init__(self, inhalt, status_code=200):
        self.inhalt = inhalt
        self.status_code = status_code


class _Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


# Attrappen der drei Konten-Module. Die Feldnamen werden NICHT abgetippt,
# sondern aus den echten Modulen gelesen – eine Attrappe mit eigener Liste
# laeuft beim naechsten Feld auseinander.
def _tupel_literal(datei: Path, name: str):
    baum = ast.parse(datei.read_text(encoding="utf-8"))
    for n in baum.body:
        if (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == name):
            try:
                return tuple(ast.literal_eval(n.value))
            except Exception:  # noqa: BLE001
                return None
    return None


def _hat_funktion(datei: Path, name: str, argzahl: int) -> bool:
    baum = ast.parse(datei.read_text(encoding="utf-8"))
    for n in baum.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return len(n.args.args) == argzahl
    return False


SAP_PY = Path(os.environ.get("SKNACH_SAP") or ROOT / "backend" / "sap_accounts.py")
VEM_PY = Path(os.environ.get("SKNACH_VEMAS") or ROOT / "backend" / "vemas_accounts.py")
JIR_PY = Path(os.environ.get("SKNACH_JIRA") or ROOT / "backend" / "jira_accounts.py")
SAP_FELDER = _tupel_literal(SAP_PY, "GEHEIMFELDER")
VEM_FELDER = _tupel_literal(VEM_PY, "GEHEIMFELDER")
if not SAP_FELDER or not VEM_FELDER:
    print("ABBRUCH: GEHEIMFELDER in sap_accounts/vemas_accounts nicht lesbar")
    sys.exit(2)
for _d, _f in ((SAP_PY, "kennwoerter_entfernen"), (VEM_PY, "kennwoerter_entfernen"),
               (JIR_PY, "alle_entfernen")):
    if not _hat_funktion(_d, _f, 0):
        print(f"ABBRUCH: {_d.name}::{_f}() ohne Argumente nicht gefunden")
        sys.exit(2)
check(True, "Positivkontrolle: Geheimfelder und Loeschfunktionen der echten Module gelesen",
      f"sap={len(SAP_FELDER)} vemas={len(VEM_FELDER)}")

SPUR: list = []
REST = {"sap": 0, "vemas": 0, "jira": 0}
WIRFT: set = set()


def _konten_attrappe(schluessel: str, felder, loeschname: str):
    mod = types.ModuleType(f"backend.{schluessel}_attrappe")
    if felder is not None:
        mod.GEHEIMFELDER = felder

    def _loeschen():
        if schluessel in WIRFT:
            raise RuntimeError("Platte voll (Attrappe)")
        # Mitgemessen wird, ob der Stand zum Zeitpunkt des Loeschens schon
        # gespeichert ist: zuerst speichern, dann loeschen.
        gespeichert_jetzt = dict((_skill_states.get(
            "sap" if schluessel == "sap_accounts" else
            "vemas" if schluessel == "vemas_accounts" else "jira", {}) or {}).get("config", {}) or {})
        SPUR.append((loeschname, schluessel, gespeichert_jetzt))
        n = REST[schluessel.split("_")[0]]
        REST[schluessel.split("_")[0]] = 0
        return n

    setattr(mod, loeschname, _loeschen)
    return mod


def _module_stellen():
    for schluessel, felder, loeschname in (
            ("sap_accounts", SAP_FELDER, "kennwoerter_entfernen"),
            ("vemas_accounts", VEM_FELDER, "kennwoerter_entfernen"),
            ("jira_accounts", None, "alle_entfernen")):
        mod = _konten_attrappe(schluessel, felder, loeschname)
        sys.modules[f"backend.{schluessel}"] = mod
        setattr(backend, schluessel, mod)


_module_stellen()

AKTIVITAET: list = []


def _aktivitaet(user, bereich, aktion, ziel=None, **felder):
    AKTIVITAET.append((aktion, ziel, felder))


def _update_env_google(cid, csecret):
    pass


def _Depends(x):
    return x


def _require_local_auth():
    return "pruefer"


NS = {
    "Request": _Request,
    "JSONResponse": _Antwort,
    "Depends": _Depends,
    "require_local_auth": _require_local_auth,
    "_get_skill_manager": lambda: SM,
    "_aktivitaet": _aktivitaet,
    "_update_env_google": _update_env_google,
    "os": os,
    "app": types.SimpleNamespace(post=lambda *a, **k: (lambda f: f)),
}
_schnitt = ast.Module(body=[USC], type_ignores=[])
_schnitt.body[0].decorator_list = []
ast.fix_missing_locations(_schnitt)
try:
    exec(compile(_schnitt, str(MAIN), "exec"), NS)  # noqa: S102
    ENDPUNKT = NS["update_skill_config"]
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: update_skill_config nicht ausfuehrbar: {e}")
    sys.exit(2)
check(callable(ENDPUNKT), "Positivkontrolle: Endpunkt geschnitten und ausfuehrbar")


def lauf(name: str, bestand: dict, body: dict, reste=None, wirft=()):
    """Einen Speichervorgang fahren. Rueckgabe: (antwort, spur, stand)."""
    _skill_states.clear()
    _skill_states[name] = {"enabled": True, "config": dict(bestand)}
    SPUR.clear()
    AKTIVITAET.clear()
    REST.update({"sap": 0, "vemas": 0, "jira": 0})
    REST.update(reste or {})
    WIRFT.clear()
    WIRFT.update(wirft)
    # Das echte secret_reveal, keine Attrappe – "leer = unveraendert" ist Teil
    # der Messung und eine eigene Fassung liefe auseinander.
    sys.modules["backend.secret_reveal"] = _sr_echt
    antwort = asyncio.run(ENDPUNKT(name, _Request(dict(body)), "pruefer"))
    stand = dict((_skill_states.get(name, {}) or {}).get("config", {}) or {})
    return antwort, list(SPUR), stand


def _geloescht(spur, schluessel: str) -> int:
    return sum(1 for e in spur if e[1] == schluessel)


# ═══════════════════════════════════════════════════════════════════════════
section("2. SAP/VEMAS: Kachel-Anmeldung EIN loescht die Kennwoerter")
# ═══════════════════════════════════════════════════════════════════════════
a, spur, stand = lauf("sap", {"kachel_anmeldung": False, "password": "geheim",
                              "username": "sammel"},
                      {"kachel_anmeldung": True, "password": "", "username": "sammel"},
                      reste={"sap": 5})
check(getattr(a, "inhalt", {}).get("success") is True, "Einschalten wird gespeichert",
      str(getattr(a, "inhalt", None)))
check(_geloescht(spur, "sap_accounts") == 1,
      "Einschalten entfernt die Kennwoerter der persoenlichen Zugaenge",
      f"Spur={[e[0:2] for e in spur]}")
check(stand.get("kachel_anmeldung") is True and stand.get("password") == "",
      "der Schalter steht an und das Sammel-Kennwort ist leer", str(stand))
check(bool(spur) and spur[0][2].get("kachel_anmeldung") is True,
      "geloescht wird NACH dem Speichern (der Stand ist schon geschrieben)",
      str(spur[0][2]) if spur else "keine Spur")
check(any(k[0] == "kachel_anmeldung_an" and k[2].get("kennwoerter_entfernt") == 5
          for k in AKTIVITAET), "die Zahl der geleerten Zugaenge wird protokolliert",
      str(AKTIVITAET))

# ⚠ DER GEMELDETE FALL: der Schalter steht SCHON an, und es liegen trotzdem
# Kennwoerter. Haengt die Loeschung am Umschalt-Moment, bleibt der Rest fuer
# immer liegen – genau das war auf dem Server zu sehen.
a, spur, stand = lauf("sap", {"kachel_anmeldung": True, "password": ""},
                      {"kachel_anmeldung": True, "password": ""}, reste={"sap": 5})
check(_geloescht(spur, "sap_accounts") == 1,
      "Schalter schon an + Rest auf der Platte: es wird trotzdem geraeumt",
      f"Spur={[e[0:2] for e in spur]}")

a, spur, stand = lauf("sap", {"kachel_anmeldung": False, "password": "geheim"},
                      {"kachel_anmeldung": False, "password": ""}, reste={"sap": 5})
check(_geloescht(spur, "sap_accounts") == 0,
      "ohne Kachelpflicht wird KEIN Kennwort entfernt",
      f"Spur={[e[0:2] for e in spur]}")
check(stand.get("password") == "geheim",
      "ohne Kachelpflicht heisst ein leeres Feld weiter 'unveraendert'", str(stand))

a, spur, stand = lauf("vemas", {"kachel_anmeldung": False, "password": "geheim"},
                      {"kachel_anmeldung": True, "password": ""}, reste={"vemas": 3})
check(_geloescht(spur, "vemas_accounts") == 1 and _geloescht(spur, "sap_accounts") == 0,
      "VEMAS raeumt sein EIGENES Modul (nicht das von SAP)",
      f"Spur={[e[0:2] for e in spur]}")
check(stand.get("password") == "", "VEMAS: das Sammel-Kennwort ist leer", str(stand))

a, spur, stand = lauf("sap", {"kachel_anmeldung": False},
                      {"kachel_anmeldung": True}, reste={"sap": 2}, wirft={"sap_accounts"})
check(getattr(a, "status_code", 0) == 500
      and getattr(a, "inhalt", {}).get("success") is False,
      "misslingt das Loeschen, meldet der Endpunkt es (500, success False)",
      f"{getattr(a, 'status_code', None)} {getattr(a, 'inhalt', None)}")

# Ein Teil-Speichern aus einem anderen Knopf schickt den Schalter nicht mit –
# der Endzustand bleibt "an", es darf kein Kennwort zurueckkommen.
a, spur, stand = lauf("sap", {"kachel_anmeldung": True, "password": ""},
                      {"username": "sammel", "password": ""}, reste={"sap": 4})
check(_geloescht(spur, "sap_accounts") == 1,
      "Teil-Speichern ohne den Schalter raeumt weiter (Endzustand zaehlt)",
      f"Spur={[e[0:2] for e in spur]}")
check(stand.get("password") == "",
      "Teil-Speichern setzt kein Sammel-Kennwort zurueck", str(stand))


# ═══════════════════════════════════════════════════════════════════════════
section("3. Jira: persoenliche Zugaenge AUS loescht die Token")
# ═══════════════════════════════════════════════════════════════════════════
a, spur, stand = lauf("jira", {"persoenliche_zugaenge": True},
                      {"persoenliche_zugaenge": False}, reste={"jira": 7})
check(_geloescht(spur, "jira_accounts") == 1,
      "Abschalten loescht alle persoenlichen Zugaenge",
      f"Spur={[e[0:2] for e in spur]}")
check(any(k[0] == "jira_persoenliche_zugaenge_aus" and k[2].get("zugaenge_entfernt") == 7
          for k in AKTIVITAET), "die Zahl der entfernten Zugaenge wird protokolliert",
      str(AKTIVITAET))

a, spur, stand = lauf("jira", {"persoenliche_zugaenge": False},
                      {"persoenliche_zugaenge": False}, reste={"jira": 7})
check(_geloescht(spur, "jira_accounts") == 1,
      "schon abgeschaltet + Rest auf der Platte: es wird trotzdem geraeumt",
      f"Spur={[e[0:2] for e in spur]}")

a, spur, stand = lauf("jira", {"persoenliche_zugaenge": False},
                      {"persoenliche_zugaenge": True}, reste={"jira": 7})
check(_geloescht(spur, "jira_accounts") == 0,
      "wieder erlaubt: es wird nichts geloescht",
      f"Spur={[e[0:2] for e in spur]}")

a, spur, stand = lauf("jira", {}, {"base_url": "https://jira.beispiel.de"},
                      reste={"jira": 7})
check(_geloescht(spur, "jira_accounts") == 0,
      "Vorgabe (Feld fehlt ueberall) gilt als erlaubt – kein Loeschen",
      f"Spur={[e[0:2] for e in spur]}")

a, spur, stand = lauf("jira", {"persoenliche_zugaenge": True},
                      {"persoenliche_zugaenge": False}, reste={"jira": 2},
                      wirft={"jira_accounts"})
check(getattr(a, "status_code", 0) == 500
      and getattr(a, "inhalt", {}).get("success") is False,
      "misslingt das Loeschen, meldet der Endpunkt es (500, success False)",
      f"{getattr(a, 'status_code', None)} {getattr(a, 'inhalt', None)}")


# ═══════════════════════════════════════════════════════════════════════════
section("4. Regeln am Syntaxbaum von update_skill_config")
# ═══════════════════════════════════════════════════════════════════════════
def _aufrufe(knoten, name):
    return [n for n in ast.walk(knoten) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Attribute) and n.func.attr == name)
                 or (isinstance(n.func, ast.Name) and n.func.id == name))]


# 4a) Der Vorzustand ist eine KOPIE. Ohne sie traegt er nach dem Speichern den
# neuen Wert (Abschnitt 0 misst, dass der Bestand das lebende dict herausgibt).
_zuw = [n for n in ast.walk(USC) if isinstance(n, ast.Assign)
        and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "gespeichert"]
check(len(_zuw) == 1, "Positivkontrolle: genau eine Zuweisung an 'gespeichert'",
      f"{len(_zuw)}")
_kopiert = False
for z in _zuw:
    v = z.value
    # dict(...) / copy(...) / deepcopy(...) um den Aufruf herum
    if isinstance(v, ast.Call) and (
            (isinstance(v.func, ast.Name) and v.func.id in ("dict", "copy", "deepcopy"))
            or (isinstance(v.func, ast.Attribute) and v.func.attr in ("copy", "deepcopy"))):
        if _aufrufe(v, "get_skill_config"):
            _kopiert = True
check(_kopiert,
      "der gespeicherte Stand wird KOPIERT gelesen (Schnappschuss)",
      "ohne Kopie traegt er nach dem Speichern den neuen Wert"
      if ALIAS else "(der Bestand gibt derzeit Kopien heraus – Guertel bleibt Pflicht)")

# 4b) Die Loeschung haengt nicht am Umschalt-MOMENT. Gemessen als Eigenschaft:
# die Bedingung des if, in dem die Loeschung steht, liest 'gespeichert' nicht.
_speichern = [c.lineno for c in _aufrufe(USC, "update_skill_config")]
check(bool(_speichern), "Positivkontrolle: der Speicher-Aufruf ist gefunden")
# ⚠ KEIN min() auf eine leere Liste: das WIRFT, und ein Lauf ohne Bilanzzeile
# ist von einem bestandenen nicht zu unterscheiden (Register).
_sp_min = min(_speichern) if _speichern else None
for fname in ("kennwoerter_entfernen", "alle_entfernen"):
    rufe = _aufrufe(USC, fname)
    check(len(rufe) == 1, f"Positivkontrolle: genau ein Aufruf von {fname}",
          f"{len(rufe)}")
    if not rufe:
        continue
    check(_sp_min is not None and rufe[0].lineno > _sp_min,
          f"{fname} laeuft NACH dem Speichern",
          f"{rufe[0].lineno} vs {_sp_min}")
    traeger = [n for n in ast.walk(USC) if isinstance(n, ast.If)
               and any(r is c for c in _aufrufe(n, fname) for r in [c])]
    # das innerste if, das den Aufruf enthaelt und eine Bedingung ueber den
    # Schalter traegt: das aeusserste davon entscheidet ueber das Loeschen
    traeger = [n for n in traeger if n.lineno <= rufe[0].lineno]
    check(bool(traeger), f"Positivkontrolle: {fname} steht in einer Verzweigung")
    liest_vorzustand = any(
        isinstance(k, ast.Name) and k.id == "gespeichert"
        for t in traeger for k in ast.walk(t.test))
    check(not liest_vorzustand,
          f"die Entscheidung fuer {fname} haengt am ENDZUSTAND, nicht am Vorzustand",
          "Bedingung liest 'gespeichert' – ein verpasster Umschalt-Moment "
          "laesst den Rest fuer immer liegen")

print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
