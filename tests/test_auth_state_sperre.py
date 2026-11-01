#!/usr/bin/env python3
"""Waechter: auth_state.json – keine verlorene Aenderung, kein Hash im Event-Loop.

Code-Review 2026-11-01:
* Die Umstellung des Docker-Kennworts bei der Anmeldung lud den GANZEN Zustand,
  aenderte ihn und schrieb ihn zurueck – ohne Sperre gegen andere Schreiber
  (TOTP-Vormerkung, Anmeldeschutz, Kennwortwechsel). Der zuletzt Speichernde
  loeschte die Aenderung des anderen.
* ``change_password`` rechnete den scrypt-Hash (~32 MB) direkt im async-Handler.

Was festgehalten wird:

1. WIRKUNG: ``_auth_state_aendern`` (aus main.py geschnitten, echte Rumpf-
   Logik) mit zwei Threads auf langsamem Laden/Speichern – beide Aenderungen
   ueberleben. Positivkontrolle: DERSELBE Aufbau ohne Sperre verliert eine –
   sonst saehe die Messung einen Wettlauf gar nicht.
2. REGEL (AST): ``_load_auth_state``/``_save_auth_state`` halten die Sperre;
   jede Funktion, die laedt UND speichert, tut beides unter der Sperre.
3. REGEL (AST): kein async-Handler ruft ``kennwort_hash`` direkt.

``backend.main`` wird NICHT importiert.

    python3 tests/test_auth_state_sperre.py
"""
import ast
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)
SPERRE = "_AUTH_STATE_LOCK"

_ok = 0
_fail = 0


def check(cond, label):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


FN = {}
for n in BAUM.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        FN.setdefault(n.name, n)

for name in ("_auth_state_aendern", "_load_auth_state", "_save_auth_state"):
    if name not in FN:
        print(f"ABBRUCH: {name} nicht in main.py gefunden.", file=sys.stderr)
        raise SystemExit(2)

# ─── 1. Wirkung mit zwei Threads ─────────────────────────────────────────────
print("\n1. zwei gleichzeitige Aenderungen ueberleben")


def _lauf(sperre):
    """Fuehrt die GESCHNITTENEN Funktionen gegen einen langsamen Speicher aus."""
    platte = {"state": {"users": {}}}

    def _laden():
        return {"users": dict(platte["state"]["users"])}

    def _speichern(s):
        platte["state"] = {"users": dict(s["users"])}

    # Das Fenster liegt in der AENDERUNG – zwischen Laden und Speichern, wo
    # nur die aeussere Sperre schuetzt. Ein Fenster im Laden selbst reichte
    # nicht: Laden und Speichern sperren auch einzeln, und ein Thread, der die
    # Sperre freigibt, bekommt sie oft sofort wieder (Python-Sperren sind nicht
    # fair) – die Gegenprobe "aeussere Sperre fehlt" biss dann nur jedes
    # zweite Mal.
    def _setze(name, wert):
        def _f(st):
            time.sleep(0.05)
            st["users"][name] = wert
        return _f

    ns = {"_AUTH_STATE_LOCK": sperre,
          "_load_auth_state_ungesperrt": _laden,
          "_save_auth_state_ungesperrt": _speichern}
    modul = ast.Module(body=[FN["_load_auth_state"], FN["_save_auth_state"],
                             FN["_auth_state_aendern"]], type_ignores=[])
    exec(compile(modul, "main.py", "exec"), ns)
    t1 = threading.Thread(target=ns["_auth_state_aendern"], args=(_setze("a", 1),))
    t2 = threading.Thread(target=ns["_auth_state_aendern"], args=(_setze("b", 2),))
    t1.start(); t2.start(); t1.join(5); t2.join(5)
    return platte["state"]["users"]


class _KeineSperre:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


ohne = _lauf(_KeineSperre())
if ohne == {"a": 1, "b": 2}:
    print("ABBRUCH: ohne Sperre geht nichts verloren – der Aufbau stellt den "
          "Wettlauf nicht her, die Messung waere trivial.", file=sys.stderr)
    raise SystemExit(2)
check(True, f"Positivkontrolle: ohne Sperre geht eine Aenderung verloren ({ohne})")
mit = _lauf(threading.RLock())
check(mit == {"a": 1, "b": 2}, f"mit _AUTH_STATE_LOCK ueberleben beide ({mit})")

# ─── 2. Regel: Laden+Speichern nur unter der Sperre ─────────────────────────
print("\n2. Lese-Aendern-Schreiben nur unter der Sperre")


def _haelt_sperre(fn):
    """Steht der GANZE Rumpf (ohne Docstring) in ``with _AUTH_STATE_LOCK:``?"""
    rumpf = [s for s in fn.body
             if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    return (len(rumpf) == 1 and isinstance(rumpf[0], ast.With)
            and any(isinstance(i.context_expr, ast.Name) and i.context_expr.id == SPERRE
                    for i in rumpf[0].items))


for name in ("_load_auth_state", "_save_auth_state", "_auth_state_aendern"):
    check(_haelt_sperre(FN[name]), f"{name}: Rumpf steht unter {SPERRE}")


def _aufrufe(knoten, name, unter_sperre=False, eigene=True):
    """(Aufruf, unter Sperre?) fuer ``name(...)`` – ohne verschachtelte defs."""
    erg = []
    for kind in ast.iter_child_nodes(knoten):
        if isinstance(kind, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and not eigene:
            continue
        sperre = unter_sperre or (isinstance(kind, ast.With) and any(
            isinstance(i.context_expr, ast.Name) and i.context_expr.id == SPERRE
            for i in kind.items))
        if isinstance(kind, ast.Call) and isinstance(kind.func, ast.Name) and kind.func.id == name:
            erg.append(sperre)
        erg += _aufrufe(kind, name, sperre, eigene=False)
    return erg


AUSNAHMEN = {"_auth_state_aendern", "_load_auth_state", "_save_auth_state",
             "_load_auth_state_ungesperrt"}
befunde = []
geprueft = 0
for n in ast.walk(BAUM):
    if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) or n.name in AUSNAHMEN:
        continue
    laden = _aufrufe(n, "_load_auth_state", eigene=False)
    speichern = _aufrufe(n, "_save_auth_state", eigene=False)
    if laden and speichern:
        geprueft += 1
        if not all(laden + speichern):
            befunde.append(f"{n.name} (Zeile {n.lineno})")
check(not befunde, f"keine Funktion laedt+speichert ohne Sperre ({geprueft} mit beidem; "
                   f"Befunde: {befunde})")
roh = [n.lineno for n in ast.walk(BAUM)
       if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
       and n.func.id in ("_save_auth_state_ungesperrt", "_load_auth_state_ungesperrt")]
check(len(roh) == 2, f"die ungesperrten Fassungen ruft nur ihr Wrapper ({len(roh)} Aufrufe)")

# ─── 3. Regel: kein Kennwort-Hash im Event-Loop ─────────────────────────────
print("\n3. kein kennwort_hash direkt in einem async-Handler")
direkt = []
for n in ast.walk(BAUM):
    if isinstance(n, ast.AsyncFunctionDef):
        for c in ast.walk(n):
            if isinstance(c, ast.Call):
                f = c.func
                if (isinstance(f, ast.Attribute) and f.attr == "kennwort_hash") or \
                   (isinstance(f, ast.Name) and f.id == "kennwort_hash"):
                    direkt.append(f"{n.name} (Zeile {c.lineno})")
check(not direkt, f"kennwort_hash nur ueber asyncio.to_thread ({direkt})")
cp = next((n for n in ast.walk(BAUM)
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "change_password"), None)
via_thread = cp is not None and any(
    isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "to_thread"
    and c.args and isinstance(c.args[0], ast.Attribute) and c.args[0].attr == "kennwort_hash"
    for c in ast.walk(cp))
check(via_thread, "change_password rechnet den Hash per asyncio.to_thread (Positivkontrolle)")

# ─── 4. Ueber Prozesse: die echte Sperre gegen einen zweiten Prozess ────────
print("\n4. auth_state_sperre.Sperre wirkt gegen einen ANDEREN Prozess")
import subprocess  # noqa: E402
import tempfile  # noqa: E402

sys.path.insert(0, str(ROOT))
from backend import auth_state_sperre as SP  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="auth_sperre_"))
datei = tmp / "auth_state.json"
datei.write_text("{}")
HALTEN = 0.8
KIND = (
    "import sys, time\n"
    "sys.path.insert(0, %r)\n"
    "from backend import auth_state_sperre as SP\n"
    "s = SP.Sperre(lambda: %r)\n"
    "with s:\n"
    "    print('GESPERRT', flush=True)\n"
    "    time.sleep(%r)\n" % (str(ROOT), str(datei), HALTEN))


def _warten_auf_kind(eigene_sperre):
    """Startet das Kind, wartet bis es sperrt, misst die eigene Wartezeit."""
    kind = subprocess.Popen([sys.executable, "-c", KIND], stdout=subprocess.PIPE, text=True)
    try:
        zeile = kind.stdout.readline().strip()
        if zeile != "GESPERRT":
            return None
        t0 = time.monotonic()
        with eigene_sperre:
            dauer = time.monotonic() - t0
        return dauer
    finally:
        kind.wait(10)


try:
    # Positivkontrolle: eine reine Thread-Sperre wartet NICHT auf das Kind –
    # sonst misst der Aufbau nicht, was die flock-Haelfte beitraegt.
    ohne = _warten_auf_kind(threading.RLock())
    if ohne is None or ohne > HALTEN / 4:
        print(f"ABBRUCH: Aufbau misst nicht (Kind sperrt nicht / RLock wartet {ohne}).",
              file=sys.stderr)
        raise SystemExit(2)
    check(True, f"Positivkontrolle: Thread-Sperre allein wartet nicht ({ohne:.2f} s)")
    mit = _warten_auf_kind(SP.Sperre(lambda: datei))
    check(mit is not None and mit >= HALTEN / 2,
          f"Sperre wartet, bis der andere Prozess freigibt ({mit and round(mit, 2)} s)")
    # Wiedereintritt: _load_auth_state schreibt innerhalb einer Aenderung zurueck.
    s = SP.Sperre(lambda: datei)
    fertig = []

    def _verschachtelt():
        with s:
            with s:
                fertig.append(1)

    t = threading.Thread(target=_verschachtelt, daemon=True)
    t.start(); t.join(3)
    check(fertig == [1], "verschachtelt im selben Thread: kein Selbst-Deadlock")
    check(Path(SP.sperrdatei(datei)).exists(), "Sperrdatei liegt neben auth_state.json")
    # Nicht nutzbare Sperrdatei: Thread-Sperre bleibt, kein Absturz.
    weg = SP.Sperre(lambda: tmp / "fehlt" / "auth_state.json")
    try:
        with weg:
            pass
        check(True, "Sperrdatei nicht anlegbar -> kein Absturz (nur Thread-Sperre)")
    except Exception as e:  # noqa: BLE001
        check(False, f"Sperrdatei nicht anlegbar -> Absturz {e!r}")
finally:
    import shutil  # noqa: E402
    shutil.rmtree(tmp, ignore_errors=True)

# ─── 5. Broker-Konsole: derselbe Sperrweg, abgeleitet aus dem Code ──────────
print("\n5. jarvis-broker-admin sperrt jeden Befehl, der auth_state.json schreibt")
ADM = ast.parse((ROOT / "backend" / "broker" / "admin.py").read_text(encoding="utf-8"))
adm_fn = {n.name: n for n in ADM.body if isinstance(n, ast.FunctionDef)}
menge = set()
for n in ADM.body:
    if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_AUTH_STATE_SCHREIBER"
                                         for t in n.targets):
        menge = {c.value for c in ast.walk(n.value) if isinstance(c, ast.Constant)
                 and isinstance(c.value, str)}
# Befehle aller Zweige von _main, deren Rumpf _auth_state_schreiben ruft.
noetig = set()
for i in ast.walk(adm_fn.get("_main") or ast.Module(body=[], type_ignores=[])):
    if isinstance(i, ast.If) and "befehl" in ast.unparse(i.test) and any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            and c.func.id == "_auth_state_schreiben"
            for c in ast.walk(ast.Module(body=i.body, type_ignores=[]))):
        noetig |= {c.value for c in ast.walk(i.test)
                   if isinstance(c, ast.Constant) and isinstance(c.value, str)}
if not noetig:
    print("ABBRUCH: keinen schreibenden Befehlszweig in admin._main gefunden.", file=sys.stderr)
    raise SystemExit(2)
check(noetig <= menge, f"alle schreibenden Befehle gesperrt (noetig {sorted(noetig)}, "
                       f"gesperrt {sorted(menge)})")
# Wirkung: main() nimmt fuer einen solchen Befehl wirklich die Sperre.
from backend.broker import admin as ADMIN  # noqa: E402
benutzt = []


class _Zaehler:
    def __init__(self, fn):
        benutzt.append(fn())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_echt_sp, _echt_main, _echt_uid = SP.Sperre, ADMIN._main, os.geteuid
SP.Sperre = _Zaehler
ADMIN._main = lambda argv: 0
os.geteuid = lambda: 0
try:
    ADMIN.main(["totp-aus", "x"])
    ADMIN.main(["liste"])
finally:
    SP.Sperre, ADMIN._main, os.geteuid = _echt_sp, _echt_main, _echt_uid
check(len(benutzt) == 1 and str(benutzt[0]).endswith("auth_state.json"),
      f"totp-aus sperrt auth_state.json, liste nicht ({benutzt})")

print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
