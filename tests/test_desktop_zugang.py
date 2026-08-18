#!/usr/bin/env python3
"""Wer darf an den lokalen Desktop? (Vorgabe des Nutzers, 2026-08-18)

  Administratoren – IMMER, ueber die Sitzung des lokalen Benutzers `jarvis`.
  Der lokale Benutzer `jarvis` selbst.
  SONST NIEMAND.

DREI STELLEN, die das zusammen halten – jede einzeln war offen:

1. ``/ws/vnc`` verlangte nur IRGENDEIN gueltiges Token. Der Knopf im Portal
   haengt zwar an ``is_admin``, aber das ist Sichtbarkeit, keine Berechtigung.
2. **websockify auf 0.0.0.0:6080** lieferte noVNC OHNE Anmeldung aus und
   proxyte auf x11vnc (`-nopw`) – die Haertung von Port 5900 (2026-08-11) war
   damit umgangen. Auf ECHT und DEV gemessen: HTTP 200 von aussen.
3. ``switch_session`` prueste nur das ZEICHENMUSTER des Namens. Ein
   Domaenen-Benutzer, der sich ohne ``nexus\\``-Praefix anmeldete, landete
   damit im LightDM-Autologin, obwohl es das Konto lokal nicht gibt – 25-mal
   auf ECHT, jedes Mal mit x11vnc-Kill und LightDM-Neustart.

Der Test liest Quelltext (kein fastapi, kein Netz):

    python3 tests/test_desktop_zugang.py
"""
import re
import sys
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
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n{t}")


def ohne_kommentare_py(s: str) -> str:
    """Docstrings und #-Kommentare weg – ein Waechter, der seine eigene
    Begruendung liest, prueft nichts (fuenfmal passiert, zuletzt 2026-08-18)."""
    s = re.sub(r'"""(?:.|\n)*?"""', "", s)
    return "\n".join(z for z in s.splitlines() if not z.lstrip().startswith("#"))


def ohne_kommentare_sh(s: str) -> str:
    return "\n".join(z for z in s.splitlines() if not z.lstrip().startswith("#"))


MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


def funktion(quelle: str, name: str) -> str:
    """Der RUMPF genau einer Funktion, per AST geschnitten.

    NOETIG, NICHT KOSMETIK: der erste Anlauf schnitt von ``@app.websocket(...)``
    bis zum naechsten ``@app.`` – das waren 446 Zeilen und enthielt unter
    anderem die Definition ``ALLOWED_USERS = {"jarvis"}``. Eine Pruefung "steht
    ALLOWED_USERS im Handler?" war damit trivial wahr und blieb in der
    Gegenprobe gruen, obwohl die Rechtepruefung ausgebaut war. Ein Waechter, der
    zu weit schneidet, misst fremden Code."""
    import ast
    baum = ast.parse(quelle)
    for k in ast.walk(baum):
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            zeilen = quelle.splitlines()[k.lineno - 1:k.end_lineno]
            return "\n".join(zeilen)
    return ""
OPS = (ROOT / "backend" / "broker" / "ops.py").read_text(encoding="utf-8")
ROOTSH = (ROOT / "start_jarvis_root.sh").read_text(encoding="utf-8")
STARTSH = (ROOT / "start_jarvis.sh").read_text(encoding="utf-8")
FW = (ROOT / "deploy" / "security" / "firewall.sh").read_text(encoding="utf-8")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("1. /ws/vnc – Maus und Tastatur nur fuer Administratoren")
# ═══════════════════════════════════════════════════════════════════════════
_ws = funktion(MAIN, "vnc_websocket_proxy")
check(len(_ws.splitlines()) < 120 and "open_connection" in _ws,
      "der Handler ist sauber geschnitten (%d Zeilen)" % len(_ws.splitlines()))
_ws_code = ohne_kommentare_py(_ws)
check("verify_token(" in _ws_code, "ein Token wird verlangt")
check("_is_admin_user(" in _ws_code,
      "und zusaetzlich Administrator-Rechte geprueft")
check("ALLOWED_USERS" in _ws_code,
      "der lokale Desktop-Benutzer kommt ebenfalls durch")
# Die Reihenfolge ist die Semantik: erst Token, dann Rechte.
check(_ws_code.index("verify_token(") < _ws_code.index("_is_admin_user("),
      "erst Anmeldung, dann Berechtigung")
check("websocket.close(" in _ws_code and _ws_code.count("close(") >= 3,
      "abgewiesen wird mit close(), nicht stillschweigend")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("2. Port 6080 – kein ungeschuetzter Nebenweg mehr")
# ═══════════════════════════════════════════════════════════════════════════
for datei, name in ((ROOTSH, "start_jarvis_root.sh"), (STARTSH, "start_jarvis.sh")):
    code = ohne_kommentare_sh(datei)
    # Nur AUSFUEHRENDE Zeilen (erkennbar an --web=), nicht die pgrep/pkill-
    # Zeilen daneben – die tragen dasselbe Wort und dieselbe Portnummer.
    starts = re.findall(r"--web=[^\n]*?(\S*6080)", code)
    check(bool(starts), "%s: websockify-Start gefunden" % name, str(starts))
    check(all(s.startswith("127.0.0.1:") for s in starts),
          "%s: websockify bindet NUR loopback" % name, str(starts))
    # Die Tailscale-Freischaltung darf 6080 nicht mehr oeffnen.
    freigaben = re.findall(r"for PORT in ([0-9 ]+); do", code)
    check(all("6080" not in f for f in freigaben),
          "%s: 6080 wird nicht mehr freigeschaltet" % name, str(freigaben))

_fw_code = ohne_kommentare_sh(FW)
_liste = _fw_code.split("TCP_OFFEN=(", 1)[1].split(")", 1)[0]
check("6080" not in _liste, "firewall.sh: 6080 steht nicht mehr in TCP_OFFEN", _liste.strip())
for p in ("22", "80", "443"):
    check(p in _liste, "firewall.sh: %s bleibt offen (sonst sperrt man sich aus)" % p)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("3. switch_session – nur ein EXISTIERENDES lokales Konto")
# ═══════════════════════════════════════════════════════════════════════════
_op = OPS.split("def _op_switch_session(", 1)[1].split("\ndef ", 1)[0]
_op_code = ohne_kommentare_py(_op)
check("_DESKTOP_USERS" in _op_code, "es gibt eine Whitelist der Desktop-Konten")
check('_DESKTOP_USERS = {"jarvis"}' in ohne_kommentare_py(OPS),
      "und sie enthaelt genau den lokalen Desktop-Benutzer")
check("pwd.getpwnam(" in _op_code,
      "die EXISTENZ des lokalen Kontos wird geprueft (ein Zeichenmuster ist keine "
      "Berechtigung – genau daran ist der Autologin ins Leere gelaufen)")
check("re.fullmatch" in _op_code, "das Zeichenmuster wird weiterhin geprueft")
# Fail-closed: bei jedem Zweifel KEIN Wechsel.
check(_op_code.count('"ok": False') >= 3,
      "jede Zweifelsstelle endet ohne Wechsel (fail-closed)")

abschnitt("4. Der Login stoesst den Wechsel nur noch fuer Berechtigte an")
_login = MAIN.split("Desktop-Session im Hintergrund wechseln", 1)[1].split("return JSONResponse", 1)[0]
check(len(_login.splitlines()) < 30, "der Login-Ausschnitt ist eng geschnitten")
_login_code = ohne_kommentare_py(_login)
check("ALLOWED_USERS" in _login_code and "_is_admin_user(" in _login_code,
      "nur lokaler Benutzer oder Administrator loesen ihn aus")
check("DESKTOP_USER" in _login_code and "switch_desktop_session, username" not in _login_code,
      "das ZIEL ist fest der lokale Desktop-Benutzer, nie der Login-Name")
check('DESKTOP_USER = "jarvis"' in MAIN, "DESKTOP_USER ist definiert")

# Gegenprobe: der rohe Login-Name darf NIRGENDS mehr in den Wechsel gehen.
check("switch_desktop_session, username" not in ohne_kommentare_py(MAIN),
      "kein Aufruf mehr mit dem rohen Login-Namen (der Fehler vom 13.07.–18.08.)")

print(f"\n{'=' * 62}")
print(f"  {_ok} OK, {_fail} FAIL")
print(f"{'=' * 62}")
sys.exit(1 if _fail else 0)
