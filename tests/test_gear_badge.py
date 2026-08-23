#!/usr/bin/env python3
"""Zaehler fuer die Zahnrad-Badge: offene Root-Freigaben + gesperrte Konten.

Die Badge selbst prueft tests/test_gear_badge_ui.js. Hier geht es um die
Serverseite, und dort ist genau EINE Frage heikel: der Zaehler haengt am
Root-Broker, also an einem FREMDEN Prozess ueber einen Unix-Socket, und er
sitzt auf dem heissen Pfad JEDER Seite (/api/me). Ein haengender Broker darf
den Seitenaufbau eines Administrators nicht bremsen – das war am 2026-08-11
schon einmal ein 20-Sekunden-Freeze fuer ALLE Benutzer (GET
/api/knowledge/mounts, `Path.is_mount()` auf ein totes CIFS-Ziel).

Der Test laedt ``backend.main`` NICHT (kein fastapi, und der echte Import von
``backend.config`` schreibt die Live-settings.json zurueck). Die drei
Funktionen werden per AST aus dem Quelltext geschnitten und mit Attrappen
wirklich AUSGEFUEHRT – eine Quelltext-Suche wuerde die Frist nicht messen.

    python3 tests/test_gear_badge.py
"""
import ast
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" - {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n{t}")


def ohne_kommentare(s: str) -> str:
    """Docstrings und #-Kommentare weg. Ein Waechter, der seine eigene
    Begruendung liest, prueft nichts (im Projekt sechsmal passiert)."""
    s = re.sub(r'"""(?:.|\n)*?"""', "", s)
    return "\n".join(z for z in s.splitlines() if not z.lstrip().startswith("#"))


MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


def schnitt(name: str) -> str:
    """Rumpf genau einer Funktion, per AST – nicht 'von X bis zum naechsten Y'.
    Ein Schnitt, der zu weit greift, misst fremden Code (Lehre 2026-08-18)."""
    baum = ast.parse(MAIN)
    for k in ast.walk(baum):
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            return "\n".join(MAIN.splitlines()[k.lineno - 1:k.end_lineno])
    return ""


# ═══════════════════════════════════════════════════════════════════════════
abschnitt("1. Die Funktionen sind da und sauber geschnitten")
# ═══════════════════════════════════════════════════════════════════════════
_messen = schnitt("_admin_badge_messen")
_badge = schnitt("_admin_badge")
_me = schnitt("get_me")
check(bool(_messen), "_admin_badge_messen gefunden")
check(bool(_badge), "_admin_badge gefunden")
check(bool(_me) and "admin_badge" in _me, "get_me liefert admin_badge")
check(len(_messen.splitlines()) < 40 and len(_badge.splitlines()) < 45,
      "beide Funktionen sind kurz (Gegenprobe zum Schnitt)",
      f"{len(_messen.splitlines())}/{len(_badge.splitlines())}")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("2. Rechte und Kosten an /api/me")
# ═══════════════════════════════════════════════════════════════════════════
_me_code = ohne_kommentare(_me)


def pos(text: str, teil: str) -> int:
    """NIE ``.index()`` in einer Pruefung: das WIRFT, statt fehlzuschlagen –
    der Lauf bricht dann ab und sieht wie ein bestandener aus (zuletzt am
    2026-08-19 passiert)."""
    return text.find(teil)


_aufruf = "await asyncio.to_thread(_admin_badge, user)"
check("if ist_admin:" in _me_code and _aufruf in _me_code,
      "gezaehlt wird NUR fuer Administratoren")
# Entscheidend ist nicht die Reihenfolge zur Lizenzpruefung, sondern dass der
# Aufruf im Admin-Zweig steht und nicht davor.
_p_if, _p_call = pos(_me_code, "if ist_admin:"), pos(_me_code, _aufruf)
check(_p_if >= 0 and _p_call > _p_if,
      "der Aufruf liegt INNERHALB des Admin-Zweigs", f"{_p_if}/{_p_call}")
check(_aufruf in _me_code,
      "der blockierende Teil laeuft im Thread, nicht im Event-Loop")
check("_ADMIN_BADGE_LEER" in _me_code,
      "ein normaler Benutzer bekommt Nullen, nicht das Feld gar nicht")

_messen_code = ohne_kommentare(_messen)
check("broker_client.mode() != \"none\"" in _messen_code,
      "ohne erreichbaren Broker wird gar nicht gefragt")
check("call_sync" in _messen_code,
      "der Broker-Aufruf ist synchron (er laeuft schon im Thread)")

_badge_code = ohne_kommentare(_badge)
check("threading.Thread" in _badge_code and "daemon=True" in _badge_code
      and ".join(_ADMIN_BADGE_TIMEOUT)" in _badge_code,
      "harter Deckel ueber Daemon-Thread + join()")
check("asyncio.wait_for" not in _badge_code,
      "NICHT asyncio.wait_for – das kehrt bei haengendem Executor nicht zurueck")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("3. Die Funktionen wirklich ausfuehren")
# ═══════════════════════════════════════════════════════════════════════════
# Attrappen: ein Broker-Modul und security_guard. Beides wird von den
# Funktionen selbst importiert bzw. als Modulglobale erwartet.
#
# Geschnitten wird von der ersten Konstante bis zum Ende von `_admin_badge` –
# die Konstanten gehoeren dazu, sonst laeuft der Block nicht.
quelle_block = []
nehmen = False
for zeile in MAIN.splitlines():
    if zeile.startswith("_ADMIN_BADGE_TTL "):
        nehmen = True
    if nehmen:
        quelle_block.append(zeile)
    if nehmen and zeile.strip() == 'return dict(box["wert"])':
        break
BLOCK = "\n".join(quelle_block)
check("_ADMIN_BADGE_TTL" in BLOCK and "def _admin_badge_messen" in BLOCK
      and "def _admin_badge(" in BLOCK,
      "Konstanten + beide Funktionen als ausfuehrbarer Block geschnitten")


class FakeGuard:
    def __init__(self, n=0):
        self.n = n
        self.aufrufe = 0

    def list_blocked(self):
        self.aufrufe += 1
        return [{"user": f"u{i}"} for i in range(self.n)]


def baue(pending=0, gesperrt=0, mode="broker", broker_ok=True, haenge=False):
    """Fuehrt den Block mit Attrappen aus und liefert (namespace, guard)."""
    import time as _time
    guard = FakeGuard(gesperrt)
    bc = types.ModuleType("backend.broker_client")

    def _mode():
        return mode

    def _call_sync(op, args, user="", timeout=0):
        if haenge:
            _time.sleep(timeout + 5)
        if not broker_ok:
            return {"ok": False, "error": "Broker nicht erreichbar"}
        return {"ok": True, "ops": (
            [{"decision": "pending"}] * pending
            + [{"decision": "allow"}, {"decision": "deny"}])}

    bc.mode = _mode
    bc.call_sync = _call_sync
    paket = types.ModuleType("backend")
    paket.broker_client = bc
    sys.modules["backend"] = paket
    sys.modules["backend.broker_client"] = bc
    ns = {"security_guard": guard, "time": _time}
    exec(compile(BLOCK, "<badge>", "exec"), ns)
    return ns, guard


# — Zaehlen —
ns, guard = baue(pending=3, gesperrt=2)
w = ns["_admin_badge_messen"]("jarvis")
check(w == {"root_pending": 3, "gesperrt": 2, "gesamt": 5},
      "zaehlt pending-Freigaben und Sperren zusammen", str(w))
check(guard.aufrufe == 1, "security_guard genau einmal gefragt")

ns, _ = baue(pending=0, gesperrt=0)
check(ns["_admin_badge_messen"]("x")["gesamt"] == 0,
      "nichts offen = 0 (keine Badge)")

# Nur `pending` zaehlt – allow/deny stehen ebenfalls in der Liste.
ns, _ = baue(pending=1, gesperrt=0)
check(ns["_admin_badge_messen"]("x")["root_pending"] == 1,
      "freigegebene und abgelehnte Ops zaehlen NICHT mit")

# — Broker weg: die Sperren muessen trotzdem gezaehlt werden —
ns, _ = baue(pending=5, gesperrt=4, mode="none")
w = ns["_admin_badge_messen"]("x")
check(w == {"root_pending": 0, "gesperrt": 4, "gesamt": 4},
      "ohne Broker fehlt nur SEINE Zahl, nicht die ganze Badge", str(w))
ns, _ = baue(pending=5, gesperrt=4, broker_ok=False)
check(ns["_admin_badge_messen"]("x")["gesperrt"] == 4,
      "ein Broker-Fehler kippt die Sperren-Zahl nicht")

# — Frist: der zweite Aufruf misst NICHT erneut —
ns, guard = baue(pending=1, gesperrt=1)
a = ns["_admin_badge"]("x")
b = ns["_admin_badge"]("x")
check(a == b and guard.aufrufe == 1,
      "innerhalb der Frist wird der gemerkte Stand geliefert",
      f"{guard.aufrufe} Messungen")
# Frist kuenstlich ablaufen lassen
ns["_admin_badge_stand"]["ts"] = 0.0
ns["_admin_badge"]("x")
check(guard.aufrufe == 2, "nach Ablauf der Frist wird neu gemessen",
      f"{guard.aufrufe} Messungen")

# — Zeitueberschreitung: alter Stand bleibt, Frist wird laenger —
ns, guard = baue(pending=2, gesperrt=0)
erst = ns["_admin_badge"]("x")
check(erst.get("gesamt") == 2, "Ausgangslage gemessen (Gegenprobe)", str(erst))
ns["_admin_badge_stand"]["ts"] = 0.0
ns["_ADMIN_BADGE_TIMEOUT"] = 0.2          # Test soll nicht drei Sekunden warten
ns["_admin_badge_messen"] = lambda u: (__import__("time").sleep(2), {})[1]
danach = ns["_admin_badge"]("x")
# .get() und nicht [..]: ein fehlender Schluessel WIRFT und der Lauf bricht ab –
# die Gegenprobe "Deckel entfernt" lieferte dann gar keine Zahl und sah aus wie
# ein bestandener Lauf (in dieser Sitzung genau so passiert).
check(danach.get("gesamt") == 2,
      "bei Zeitueberschreitung bleibt der letzte Stand stehen (nicht 0)",
      str(danach))
check(ns["_admin_badge_stand"].get("ttl") == ns["_ADMIN_BADGE_TTL_FEHLER"],
      "und die Frist wird verlaengert (kein Thread-Nachschub alle 20 s)")

# — Eine Ausnahme in der Messung darf /api/me nicht kippen —
ns, _ = baue()
def _kracht(u):
    raise RuntimeError("kaputt")
ns["_admin_badge_messen"] = _kracht
ns["_admin_badge_stand"]["ts"] = 0.0
try:
    r = ns["_admin_badge"]("x")
    check(isinstance(r, dict), "eine Ausnahme in der Messung wird geschluckt", str(r))
except Exception as e:  # noqa: BLE001
    check(False, "eine Ausnahme in der Messung wird geschluckt", repr(e))

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("4. Kein zweiter Endpunkt, keine zweite Fassung")
# ═══════════════════════════════════════════════════════════════════════════
SBTN = (ROOT / "frontend" / "js" / "settings_btn.js").read_text(encoding="utf-8")
check("/api/broker/status" not in SBTN,
      "das Frontend fragt NICHT /api/broker/status (Roundtrip je Seite)")
check("/api/security/incidents" not in SBTN,
      "und auch nicht die Vorfallsliste")
check(SBTN.count("fetch('/api/me'") == 2,
      "genau zwei Abrufe von /api/me: Erstpruefung + Takt",
      str(SBTN.count("fetch('/api/me'")))

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
