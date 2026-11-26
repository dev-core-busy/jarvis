#!/usr/bin/env python3
"""Waechter: die Zahnrad-Badge folgt dem AIDE-Abgleich sofort (gemeldet 2026-11-26).

Die Badge zaehlt die Befunde der Serverueberwachung (``ueberwachung.lesen``),
und die schreibt der Timer nur alle fuenf Minuten. Nach "Nach Durchsicht
uebernehmen" oder "Liste aktualisieren" stand deshalb weiter "AIDE: n
Aenderungen nicht erklaert" am Zahnrad. Gemessen wird die WIRKUNG:

  1. ``ueberwachung.aide_weicht_ab``: erkennt jede Abweichung (offen/uebernommen,
     andere Kennung, Fehler, veraltet) – und meldet KEINE, wo beide gleich sind
     oder der AIDE-Zustand nicht belegt ist.
  2. ``main._badge_aide_nachziehen`` (aus dem echten Quelltext geschnitten und
     ausgefuehrt): ruft bei Abweichung GENAU die Broker-Op
     ``ueberwachung_auffrischen`` und verwirft danach den gemerkten Badge-Stand;
     ohne Abweichung weder Op noch Verwerfen. Und der Endpunkt
     ``GET /api/security/updates`` ruft sie (AST).
  3. Broker-Op ``_op_ueberwachung_auffrischen`` (ausgefuehrt, ``subprocess.run``
     als Attrappe): startet GENAU ``systemctl start jarvis-ueberwachung.service``,
     ist registriert und ohne Freigabe/Audit (READONLY_OPS).

JARVIS_UEBERW_PRUEFLING / JARVIS_MAIN_PRUEFLING / JARVIS_OPS_PRUEFLING lenken auf
Kopien (Gegenprobe von Hand).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "lib"))
from quell_ausschnitt import segment  # noqa: E402

MOD = Path(os.environ.get("JARVIS_UEBERW_PRUEFLING", ROOT / "backend" / "ueberwachung.py"))
MAIN = Path(os.environ.get("JARVIS_MAIN_PRUEFLING", ROOT / "backend" / "main.py"))
OPS = Path(os.environ.get("JARVIS_OPS_PRUEFLING", ROOT / "backend" / "broker" / "ops.py"))

OK = FAIL = 0


def pruefe(bed, text, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  \033[32m✓\033[0m " + text)
    else:
        FAIL += 1
        print("  \033[31m✗\033[0m " + text + (f" – {detail}" if detail else ""))


def ende(code=None):
    print("\n" + "=" * 62)
    print(f"  {OK} OK, {FAIL} FAIL")
    print("=" * 62)
    sys.exit(code if code is not None else (1 if FAIL else 0))


def funktion(quelle: str, baum: ast.Module, name: str):
    for k in baum.body:
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            return k, segment(quelle, k)
    return None, None


# ── 1. aide_weicht_ab ────────────────────────────────────────────────────────
print("\n1. ueberwachung.aide_weicht_ab")
spec = importlib.util.spec_from_file_location("ueberw_pruefling", MOD)
ue = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(ue)
except Exception as e:  # noqa: BLE001
    print(f"  ABBRUCH: Modul nicht ladbar: {e}")
    ende(2)
f = getattr(ue, "aide_weicht_ab", None)
pruefe(callable(f), "Funktion vorhanden (Positivkontrolle)")
if not callable(f):
    ende(2)

JETZT = 1_800_000_000.0
FRISCH = JETZT - 3600
K = "a1b2c3d4e5f60718"


def aide(zustand=None, **kw):
    a = {"eingerichtet": True, "zustand": zustand or {}}
    a.update(kw)
    return a


def bef(art, **werte):
    return {"id": art, "art": art, "stufe": "warnung", "text": "", "werte": werte}


OFFEN = aide({"zustand": "offen", "kennung": K, "zeit": FRISCH, "offen_anzahl": 3})
UEBERN = aide({"zustand": "uebernommen", "zeit": FRISCH})
FEHLER = aide({"zustand": "fehler", "zeit": FRISCH, "grund": "x"})

faelle = [
    # (befunde, aide, erwartet, text)
    ([bef("aide_offen", kennung=K)], UEBERN, True, "Befund offen, Abgleich uebernommen (der gemeldete Fall)"),
    ([], OFFEN, True, "kein Befund, Abgleich offen (Pruefung fertig, Timer noch nicht gelaufen)"),
    ([bef("aide_offen", kennung="ffffffffffffffff")], OFFEN, True, "anderer offener Bericht (andere Kennung)"),
    ([bef("aide_fehler")], UEBERN, True, "Befund Fehler, Abgleich inzwischen gut"),
    ([], FEHLER, True, "Abgleich gescheitert, noch kein Befund"),
    ([bef("aide_veraltet")], UEBERN, True, "Befund 'veraltet', Abgleich frisch"),
    ([], aide({"zustand": "uebernommen", "zeit": JETZT - 4 * 86400}), True, "Abgleich veraltet, noch kein Befund"),
    ([bef("aide_offen", kennung=K)], OFFEN, False, "gleich: beide offen mit derselben Kennung"),
    ([], UEBERN, False, "gleich: nichts offen, kein Befund"),
    ([bef("aide_fehler")], FEHLER, False, "gleich: beide Fehler"),
    ([bef("ssh_fehl"), bef("dienst")], UEBERN, False, "fremde Befunde zaehlen nicht"),
    ([bef("aide_offen", kennung=K)], {"fehler": "Broker weg"}, False, "AIDE-Zustand unbekannt: kein Lauf"),
    ([bef("aide_offen", kennung=K)], aide({}, eingerichtet=False), False, "AIDE nicht eingerichtet: kein Lauf"),
    ([bef("aide_offen", kennung=K)], None, False, "kein AIDE-Zustand: kein Lauf"),
    ([None, "x", bef("aide_offen", kennung=K)], OFFEN, False, "unbrauchbare Eintraege werfen nicht"),
]
for befunde, a, soll, text in faelle:
    try:
        ist = f(befunde, a, jetzt=JETZT)
    except Exception as e:  # noqa: BLE001
        ist = f"wirft {type(e).__name__}: {e}"
    pruefe(ist is soll, text, f"erwartet {soll}, bekam {ist}")

# ── 2. main._badge_aide_nachziehen ───────────────────────────────────────────
print("\n2. main._badge_aide_nachziehen (geschnitten, ausgefuehrt)")
MQ = MAIN.read_text(encoding="utf-8")
MB = ast.parse(MQ)
knoten, quelle = funktion(MQ, MB, "_badge_aide_nachziehen")
pruefe(knoten is not None, "Funktion in main.py (Positivkontrolle)")
if knoten is None:
    ende(2)

endpunkt, _ = funktion(MQ, MB, "security_updates_status")
ruft = endpunkt is not None and any(
    isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
    and isinstance(n.value.func, ast.Name) and n.value.func.id == "_badge_aide_nachziehen"
    for n in ast.walk(endpunkt))
pruefe(ruft, "GET /api/security/updates wartet auf _badge_aide_nachziehen")


def lauf(befunde, aide_stand, eingerichtet=True, broker_wirft=False, broker_ok=True):
    rufe = []
    stand = {"ts": 12345.0, "ttl": 20.0, "wert": {}}

    async def call(op, args, user="", timeout=0):
        rufe.append(op)
        if broker_wirft:
            raise RuntimeError("Socket weg")
        return {"ok": True} if broker_ok else {"ok": False, "error": "Unbekannte Broker-Operation"}

    paket = types.ModuleType("backend")
    paket.__path__ = []
    attr_ue = types.ModuleType("backend.ueberwachung")
    attr_ue.lesen = lambda: {"eingerichtet": eingerichtet, "befunde": befunde}
    attr_ue.aide_weicht_ab = lambda b, a: f(b, a, jetzt=JETZT)
    attr_bc = types.ModuleType("backend.broker_client")
    attr_bc.call = call
    paket.ueberwachung = attr_ue
    paket.broker_client = attr_bc
    alt = {k: sys.modules.get(k) for k in ("backend", "backend.ueberwachung", "backend.broker_client")}
    sys.modules.update({"backend": paket, "backend.ueberwachung": attr_ue, "backend.broker_client": attr_bc})
    try:
        ns = {"asyncio": asyncio, "_admin_badge_stand": stand}
        exec(compile(quelle, "main._badge_aide_nachziehen", "exec"), ns)
        erg = asyncio.run(ns["_badge_aide_nachziehen"](aide_stand, "admin"))
    finally:
        for k, v in alt.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return erg, rufe, stand


erg, rufe, stand = lauf([bef("aide_offen", kennung=K)], UEBERN)
pruefe(rufe == ["ueberwachung_auffrischen"], "Abweichung: genau die Op 'ueberwachung_auffrischen'", str(rufe))
pruefe(stand["ts"] == 0.0, "Abweichung: gemerkter Badge-Stand verworfen", str(stand["ts"]))
pruefe(erg is True, "Abweichung: meldet True")

erg, rufe, stand = lauf([bef("aide_offen", kennung=K)], OFFEN)
pruefe(rufe == [] and stand["ts"] == 12345.0 and erg is False, "gleich: keine Op, Badge-Stand bleibt", f"{rufe} {stand['ts']}")

erg, rufe, stand = lauf([bef("aide_offen", kennung=K)], UEBERN, eingerichtet=False)
pruefe(rufe == [] and stand["ts"] == 12345.0, "Ueberwachung nicht eingerichtet: keine Op", str(rufe))

try:
    erg, rufe, stand = lauf([bef("aide_offen", kennung=K)], UEBERN, broker_wirft=True)
    pruefe(erg is False and stand["ts"] == 12345.0, "Broker wirft: kein Wurf nach aussen, Badge-Stand bleibt")
except Exception as e:  # noqa: BLE001
    pruefe(False, "Broker wirft: kein Wurf nach aussen", repr(e))

erg, rufe, stand = lauf([bef("aide_offen", kennung=K)], UEBERN, broker_ok=False)
pruefe(rufe == ["ueberwachung_auffrischen"] and erg is False and stand["ts"] == 12345.0,
       "Broker lehnt ab (z. B. unbekannte Op): Badge-Stand bleibt, meldet False", f"{erg} {stand['ts']}")

# ── 3. Broker-Op ─────────────────────────────────────────────────────────────
print("\n3. Broker-Op ueberwachung_auffrischen")
OQ = OPS.read_text(encoding="utf-8")
OB = ast.parse(OQ)
knoten, quelle = funktion(OQ, OB, "_op_ueberwachung_auffrischen")
pruefe(knoten is not None, "Op-Funktion in ops.py (Positivkontrolle)")
if knoten is None:
    ende(2)

registriert = readonly = False
for k in OB.body:
    if isinstance(k, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_REGISTRY" for t in k.targets) \
            and isinstance(k.value, ast.Dict):
        for schl, wert in zip(k.value.keys, k.value.values):
            if isinstance(schl, ast.Constant) and schl.value == "ueberwachung_auffrischen" \
                    and isinstance(wert, ast.Tuple) and isinstance(wert.elts[0], ast.Name):
                registriert = wert.elts[0].id == "_op_ueberwachung_auffrischen"
    if isinstance(k, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "READONLY_OPS" for t in k.targets):
        readonly = "ueberwachung_auffrischen" in {e.value for e in ast.walk(k.value) if isinstance(e, ast.Constant)}
pruefe(registriert, "in _REGISTRY auf _op_ueberwachung_auffrischen registriert")
pruefe(readonly, "in READONLY_OPS (keine Freigabe-/Audit-Flut bei jedem Laden des Abschnitts)")

aufrufe = []


class _Erg:
    returncode = 0
    stderr = ""
    stdout = ""


def _run(argv, **kw):
    aufrufe.append(list(argv))
    return _Erg()


sp = types.SimpleNamespace(run=_run, TimeoutExpired=TimeoutError)
paket = types.ModuleType("backend")
paket.__path__ = []
attr_ue = types.ModuleType("backend.ueberwachung")
attr_ue.UNIT = getattr(ue, "UNIT", None)
paket.ueberwachung = attr_ue
alt = {k: sys.modules.get(k) for k in ("backend", "backend.ueberwachung")}
sys.modules.update({"backend": paket, "backend.ueberwachung": attr_ue})
try:
    ns = {"subprocess": sp}
    exec(compile(quelle, "ops._op_ueberwachung_auffrischen", "exec"), ns)
    res = ns["_op_ueberwachung_auffrischen"]({"unit": "ssh.service", "x": "; rm -rf /"}, None)
finally:
    for k, v in alt.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
pruefe(attr_ue.UNIT == "jarvis-ueberwachung.service", "ueberwachung.UNIT ist die Unit des Timers", str(attr_ue.UNIT))
pruefe(aufrufe == [["systemctl", "start", "jarvis-ueberwachung.service"]],
       "startet GENAU die Ueberwachungs-Unit – Argumente werden ignoriert", str(aufrufe))
pruefe(isinstance(res, dict) and res.get("ok") is True, "Antwort ok bei rc 0", str(res))

ende()
