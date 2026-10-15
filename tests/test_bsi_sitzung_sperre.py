#!/usr/bin/env python3
"""Waechter: Endpunkte mit eigener Token-Pruefung halten dieselben Sperren ein
wie ``require_auth`` (BSI-Abgleich Abschnitt 5, Skill "avatar", 2026-10-13).

Befund: ``/api/avatar/*`` pruefte nur ``verify_token`` – ein gesperrtes Konto,
eines mit offenem Kennwortwechsel oder ohne Anmeldeberechtigung bekam weiter
Antworten. Dasselbe Muster stand an ``/api/tts``, ``/api/tts/voices``,
``/api/support/query``, ``/api/support/summarize`` und ``/api/vision/stream``.

Gemessen wird zweierlei:

1. **Regel am Syntaxbaum:** jede Funktion in ``backend/main.py``, die
   ``verify_token`` ruft, ruft auch eine Sperrpruefung – oder steht mit Grund in
   ``AUSNAHMEN``. Eine neue Stelle mit dem alten Muster faellt so auf, ohne
   dass sie jemand in eine Liste eintraegt.
2. **Wirkung:** die Helfer und die betroffenen Endpunkte werden aus dem Quelltext
   geloest und mit Attrappen ausgefuehrt: gesperrt -> 403, VOR dem Lesen des
   Rumpfs; ohne Anmeldung -> 401; frei -> weder 401 noch 403.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import hmac
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "backend" / "main.py"

SPERR_AUFRUFE = {"is_blocked", "_login_still_allowed", "_sitzung_gesperrt",
                 "_sitzung_oder_schluessel"}

# Funktion -> Grund. Jede Zeile muss weiter existieren (sonst veraltet).
AUSNAHMEN = {
    "require_auth_pwchange": "Kennwortwechsel muss bei offenem Wechsel gehen (sonst Deadlock)",
    "_query_benutzer": "Hilfsfunktion; der Aufrufer require_auth_or_query prueft die Sperren",
    "security_my_block": "zeigt einem gesperrten Konto den Grund seiner Sperre",
    "verify_token_endpoint": "meldet nur Gueltigkeit und offenen Kennwortwechsel, keine Daten",
}

# Endpunkte, deren Wirkung ausgefuehrt wird.
ENDPUNKTE = ["avatar_get_config", "avatar_graphics", "avatar_ask", "avatar_stop",
             "tts_synthesize", "tts_voices", "support_query", "support_summarize",
             "vision_mjpeg_stream"]

ok = fail = 0


def pruefe(bed: bool, text: str) -> None:
    global ok, fail
    if bed:
        ok += 1
        print("  OK   " + text)
    else:
        fail += 1
        print("  FAIL " + text)


def aufrufe(fn: ast.AST) -> set:
    namen = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                namen.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                namen.add(n.func.attr)
    return namen


# ── Attrappen ────────────────────────────────────────────────────────────────
class _Antwort:
    def __init__(self, inhalt=None, status_code=200, **_):
        self.inhalt, self.status_code = inhalt, status_code


class _HTTPFehler(Exception):
    def __init__(self, status_code=500, detail=""):
        super().__init__(detail)
        self.status_code = status_code


class _RumpfGelesen(Exception):
    """Der Endpunkt hat den Rumpf gelesen – er war also durch die Pruefung."""


class _Anfrage:
    def __init__(self, token: str):
        kopf = {"Authorization": "Bearer " + token} if token else {}
        self.headers = kopf
        self.query_params = {"token": token} if token else {}
        self.client = None

    async def json(self):
        raise _RumpfGelesen()


class _Waechterlein:
    def __init__(self, gesperrt):
        self.gesperrt = gesperrt

    def is_blocked(self, user):
        return user in self.gesperrt


class _Konfig:
    def get_skill_states(self):
        return {}


def namensraum(zustand: dict) -> dict:
    """Stubs mit der echten Signatur: verify_token(token) -> name|None usw."""
    return {
        "Request": object, "JSONResponse": _Antwort, "HTTPException": _HTTPFehler,
        "hmac": hmac, "config": _Konfig(),
        "verify_token": lambda t: {"tok-anna": "anna", "tok-gesperrt": "gesperrt",
                                   "tok-wechsel": "wechsel", "tok-entzogen": "entzogen"}.get(t),
        "_user_must_change": lambda u: u == "wechsel",
        "security_guard": _Waechterlein({"gesperrt"}),
        "_login_still_allowed": lambda u: u != "entzogen",
        "_verify_agent_api_key": lambda r: zustand.get("api", False),
        "_skill_active": lambda n: True,
        "_get_vision_engine": lambda: None,
    }


def ausfuehren(fn_src: str, name: str, ns: dict, token: str):
    """Endpunkt ausfuehren -> Statuscode, 'durch' (Rumpf gelesen / weitergelaufen)."""
    exec(compile(fn_src, "<%s>" % name, "exec"), ns)  # noqa: S102
    try:
        erg = asyncio.run(ns[name](_Anfrage(token)))
    except _HTTPFehler as e:
        return e.status_code
    except _RumpfGelesen:
        return "durch"
    except Exception:  # noqa: BLE001 – lief hinter der Pruefung in eine Attrappe
        return "durch"
    return getattr(erg, "status_code", "durch")


def main() -> int:
    try:
        baum = ast.parse(MAIN.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print("ABBRUCH: backend/main.py nicht lesbar: %s" % e)
        return 2
    funktionen = {}
    for n in ast.walk(baum):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funktionen.setdefault(n.name, n)

    # Positivkontrolle: ohne verify_token und die Helfer misst hier nichts.
    nutzer = [f for f in funktionen.values() if "verify_token" in aufrufe(f)]
    fehlend = [x for x in ["verify_token", "_sitzung_gesperrt", "_sitzung_oder_schluessel"] + ENDPUNKTE
               if x not in funktionen]
    if not nutzer or fehlend:
        print("ABBRUCH: Positivkontrolle – fehlt: %s, verify_token-Aufrufer: %d"
              % (fehlend, len(nutzer)))
        return 2

    print("Regel: verify_token nur zusammen mit Sperrpruefung")
    for f in sorted(nutzer, key=lambda f: f.lineno):
        if f.name in AUSNAHMEN:
            continue
        pruefe(bool(aufrufe(f) & SPERR_AUFRUFE),
               "%s (Zeile %d) prueft die Sperren" % (f.name, f.lineno))
    for name in AUSNAHMEN:
        pruefe(name in funktionen and "verify_token" in aufrufe(funktionen[name]),
               "Ausnahme %s ist noch aktuell" % name)

    def quelle(name):
        knoten = funktionen[name]
        knoten.decorator_list = []
        return ast.unparse(knoten)

    helfer = quelle("_sitzung_gesperrt") + "\n" + quelle("_sitzung_oder_schluessel")

    print("\nWirkung der Helfer")
    for token, api, erwartet in [
        ("tok-anna", False, ("anna", 200)),
        ("tok-gesperrt", False, (None, 403)),
        ("tok-wechsel", False, (None, 403)),
        ("tok-entzogen", False, (None, 403)),
        ("", True, ("", 200)),
        ("", False, (None, 401)),
        ("tok-gesperrt", True, (None, 403)),   # Schluessel hebt die Sperre NICHT auf
    ]:
        ns = namensraum({"api": api})
        exec(compile(helfer, "<helfer>", "exec"), ns)  # noqa: S102
        erg = ns["_sitzung_oder_schluessel"](_Anfrage(token))
        pruefe(erg == erwartet, "Token %-13r api=%-5s -> %r (erwartet %r)"
               % (token, api, erg, erwartet))

    print("\nWirkung an den Endpunkten")
    for name in ENDPUNKTE:
        src = helfer + "\n" + quelle(name)
        for token, erwartet in [("tok-gesperrt", 403), ("tok-wechsel", 403),
                                ("tok-entzogen", 403), ("", 401)]:
            st = ausfuehren(src, name, namensraum({}), token)
            pruefe(st == erwartet, "%s mit %-13r -> %r (erwartet %r)"
                   % (name, token or "ohne", st, erwartet))
        st = ausfuehren(src, name, namensraum({}), "tok-anna")
        pruefe(st not in (401, 403), "%s mit gueltiger Sitzung -> %r (nicht 401/403)"
               % (name, st))

    print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
