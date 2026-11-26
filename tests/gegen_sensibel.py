#!/usr/bin/env python3
"""Gegenproben zum Schalter "sensible Daten" (backend/sensibel.py).

Jede Probe dreht GENAU EINE Zusage zurueck – eine Senke, die wieder Inhalt
schreibt, ein Loeschen, das ausbleibt, eine Verdrahtung, die umgangen wird –
und misst, ob ``tests/test_sensibel.py`` (samt ``test_sensibel_chat.js``)
beisst. Eine Probe, die nicht beisst, ist ein Testmangel – kein Beweis.

SABOTIERT WIRD EINE KOPIE, NICHT DER ARBEITSBAUM (Vorbild
``gegen_short_tracks_fragen.py``): der Betreiber arbeitet parallel an
denselben Dateien (``main.py``, ``agent.py``, ``chat.js``). Jede Probe bekommt
einen frischen Wegwerf-Baum; ein abgeschossener Lauf hinterlaesst dort
hoechstens ein Verzeichnis im temporaeren Bereich.

Gezaehlt wird nur ein ECHTER Biss: Exit 1 MIT Bilanzzeile und mindestens einem
FAIL. Exit 2 oder ein Absturz ohne Bilanz zaehlt als NICHT gebissen.

    python3 tests/gegen_sensibel.py
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY = "tests/test_sensibel.py"
JS = "tests/test_sensibel_chat.js"
FRONT = ["frontend/js/chat.js", "frontend/chat.html"]


def _acorn_ort() -> str:
    """acorn fuer den Wegwerf-Baum: dort gibt es kein node_modules."""
    for p in (os.environ.get("ACORN_PATH") or "", str(ROOT / "node_modules" / "acorn"),
              "/usr/share/nodejs/acorn"):
        if p and Path(p).exists():
            return p
    return ""


def baum() -> Path:
    wurzel = Path(tempfile.mkdtemp(prefix="gegen_sensibel_"))
    ign = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "backend", wurzel / "backend", ignore=ign)
    shutil.copytree(ROOT / "tests" / "lib", wurzel / "tests" / "lib", ignore=ign)
    for rel in FRONT + [PY, JS]:
        ziel = wurzel / rel
        ziel.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, ziel)
    (wurzel / "data").mkdir()
    return wurzel


def lauf(wurzel: Path) -> tuple[int, int, bool]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if _acorn_ort():
        env["ACORN_PATH"] = _acorn_ort()
    try:
        p = subprocess.run([sys.executable, PY], cwd=wurzel, capture_output=True,
                           text=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        return (124, -1, False)
    treffer = re.findall(r"Ergebnis: (\d+) OK, (\d+) FAIL", p.stdout + p.stderr)
    if not treffer:
        return (p.returncode, -1, False)
    return (p.returncode, int(treffer[-1][1]), True)


def patch(wurzel: Path, rel: str, alt: str, neu: str) -> None:
    p = wurzel / rel
    s = p.read_text(encoding="utf-8")
    n = s.count(alt)
    if n != 1:
        raise SystemExit("ABBRUCH: Sabotage-Anker in %s trifft %d-mal statt einmal:\n%s"
                         % (rel, n, alt[:160]))
    p.write_text(s.replace(alt, neu), encoding="utf-8")


PROBEN = []


def probe(name, *aenderungen):
    PROBEN.append((name, aenderungen))


B = "backend/"
LK, CL, AL, CS = B + "log_kontext.py", B + "conv_log.py", B + "audit_log.py", B + "chat_sessions.py"
LE, ME, TE, SG = B + "learning.py", B + "tools/memory.py", B + "telemetry.py", B + "security_guard.py"
ST, RU, OPS, BC = B + "short_tracks.py", B + "short_tracks_runner.py", B + "broker/ops.py", B + "broker_client.py"
DO, SE, UG, LT = B + "documents.py", B + "sensibel.py", B + "url_geheimnis.py", B + "lauf_tmp.py"
MA, AG, CJ = B + "main.py", B + "agent.py", "frontend/js/chat.js"

# ── Journal ──
probe("stdout verschluckt nicht mehr",
      (LK, "        if _sensibel():\n            with self._lock:", "        if False:\n            with self._lock:"))
probe("Logger-Filter laesst Text und Traceback stehen",
      (LK, "        if _sensibel():\n            # Stufe", "        if False:\n            # Stufe"))
# ── Protokolle ──
probe("conv_log schreibt den Inhalt",
      (CL, "    if _sens:\n        task = _sensibel.MARKE", "    if False:\n        task = _sensibel.MARKE"))
probe("Audit: Auftrag im Klartext",
      (AL, '    if _sensibel():\n        task = "[sensibel]"', '    if False:\n        task = "[sensibel]"'))
probe("Audit: Werkzeug-Argumente im Klartext",
      (AL, '    if _sensibel():\n        args = {k: "[sensibel]"', '    if False:\n        args = {k: "[sensibel]"'))
probe("Sitzung: Kontext wird gespeichert",
      (CS, "    if not isinstance(content_dicts, list) or _sensibel():", "    if not isinstance(content_dicts, list):"))
probe("Sitzung: Titel aus dem Inhalt",
      (CS, '    optional einen Titel aus dem ersten Nutzertext."""\n    if _sensibel():\n        return',
           '    optional einen Titel aus dem ersten Nutzertext."""'))
probe("Lernen laeuft im sensiblen Lauf",
      (LE, "        if _sens.aktiv():\n            return", "        if False:\n            return"))
probe("Gedaechtnis schreibbar",
      (ME, "    if _sensibel():\n        return True\n    try:\n        return _kanal() is None",
           "    try:\n        return _kanal() is None"))
probe("Telemetrie gibt den Auftrag heraus",
      (TE, '        if getattr(self, "sensibel", False):', '        if False:'))
probe("Sicherheitsprotokoll: Auszug im Klartext",
      (SG, "        if _s.aktiv() and text:", "        if False:"))
probe("Track-Protokoll mit Inhalt",
      (ST, "        if _sens.aktiv():\n            eintrag = _protokoll_sensibel", "        if False:\n            eintrag = _protokoll_sensibel"))
probe("Ablage-Feld nimmt jeden wahren Wert",
      (ST, '        "sensibel": q.get("sensibel") is True,', '        "sensibel": bool(q.get("sensibel")),'))
probe("Ablage-Feld nicht aenderbar",
      (ST, '             "fragen", "sensibel")', '             "fragen")'))
# ── Broker ──
probe("Broker schwaerzt nicht",
      (OPS, "    if ist_sensibel(args):\n        return {k:", "    if False:\n        return {k:"))
probe("broker_client gibt das Merkmal nicht weiter",
      (BC, '        if _sens.aktiv():\n            args = {**(args or {}), "sensibel": True}',
           '        if False:\n            args = {**(args or {}), "sensibel": True}'))
# ── Dateien ──
probe("Registry vermerkt nichts",
      (DO, '        if _sens.aktiv():\n            eintrag["sensibel"] = True', '        if False:\n            eintrag["sensibel"] = True'))
probe("Zwischenablagen bleiben liegen",
      (SE, "            elif _docs.entfernen(name):", "            elif False:"))
probe("Ergebnisfrist einen Tag statt 15 Minuten",
      (SE, "ERGEBNIS_FRIST_S = 15 * 60", "ERGEBNIS_FRIST_S = 24 * 3600"))
probe("Fristablauf loescht nicht",
      (DO, "                    if float(bis) <= jetzt:", "                    if False:"))
probe("Arbeitskopien bleiben liegen",
      (SE, '    erg["dateien"] = _dateien_loeschen(d["dateien"])', '    erg["dateien"] = 0'))
probe("Access-Log nennt den Dateinamen",
      (UG, "            t = _docs.sensible_namen_schwaerzen(t)", "            pass"))
probe("entfernen nimmt Pfade an",
      (DO, '    if not name or name.startswith(".") or name != (fname or ""):', '    if not name or name.startswith("."):'))
# ── privates /tmp ──
probe("sensibler Lauf im geteilten Verzeichnis",
      (LT, "        if _sk:\n            kennung = _sk", "        if _sk:\n            pass"))
probe("eigenes Verzeichnis gehoert niemandem",
      (LT, "    return bool(lauf is not None and lauf.kennung == teil",
           "    return bool(False and lauf is not None and lauf.kennung == teil"))
# ── Lauf-Merkmal ──
probe("fortsetzen erbt statt ausdruecklich zu setzen",
      (SE, "    token = _cv.set(d)\n    try:\n        yield\n    finally:\n        try:\n            _cv.reset(token)\n        except (ValueError, RuntimeError):\n            pass\n        if d is not None:",
           "    token = _cv.set(d if d is not None else _cv.get())\n    try:\n        yield\n    finally:\n        try:\n            _cv.reset(token)\n        except (ValueError, RuntimeError):\n            pass\n        if d is not None:"))
# ── Verdrahtung ──
probe("WebSocket umgeht die Klammer",
      (MA, "            await _ws_nachricht_behandeln(ws, msg)", "            await handle_ws_message(ws, msg)"))
probe("jeder wahre Wert macht einen Auftrag sensibel",
      (MA, '            and msg.get("sensibel") is True)', '            and bool(msg.get("sensibel")))'))
probe("Hauptlauf raeumt nicht auf",
      (MA, '_hintergrund(_sensibel.uebergeben(_run_main_agent_and_notify()), "Hauptlauf")',
           '_hintergrund(_run_main_agent_and_notify(), "Hauptlauf")'))
probe("Download haelt Browser-Cache und loescht nicht",
      (MA, "    if _documents.ist_sensibel(name):\n        from starlette", "    if False:\n        from starlette"))
probe("Anhang-Merkliste im sensiblen Lauf",
      (MA, "        if _sensibel.aktiv():\n            return\n    except Exception:  # noqa: BLE001\n        pass\n    try:\n        liste = _SESSION_ANHAENGE",
           "        pass\n    except Exception:  # noqa: BLE001\n        pass\n    try:\n        liste = _SESSION_ANHAENGE"))
probe("Ergebnis wird nicht vermerkt",
      (AG, "            _sensibel.ergebnis_merken(url.rsplit(\"/\", 1)[-1])", "            pass"))
probe("normaler Folgelauf bekommt sensiblen Verlauf",
      (RU, "                         and (j.get(\"sensibel\") or not v.get(\"sensibel\"))),", "                         ),"))
probe("Frage zweigt keinen Lauf ab",
      (RU, '        j["_frage"] = (frage or "").strip()\n        _sensibel_abzweigen(j)', '        j["_frage"] = (frage or "").strip()'))
# ── Frontend ──
probe("chat.js: Verlauf landet in localStorage",
      (CJ, "        if (_istSensibel(_activeSid)) { _sensChats.get(_activeSid).history = _chatHistory; return; }\n        if (window.JarvisChatLib",
           "        if (window.JarvisChatLib"))
probe("chat.js: Auftrag ohne Merkmal",
      (CJ, "        if (_istSensibel(_activeSid)) msg.sensibel = true;\n", ""))
probe("chat.js: sensible Kennung wird gemerkt",
      (CJ, "    function _sidMerken(sid) {\n        if (_istSensibel(sid)) return;\n", "    function _sidMerken(sid) {\n"))
probe("chat.js: Server-Liste verdraengt sensible Chats",
      (CJ, "        _sessions = _mitSensiblen(await _csList());", "        _sessions = await _csList();"))
# ── Newsfeed-Uebersetzungen ──
NFU = B + "newsfeed_uebersetzung.py"
probe("Newsfeed-Uebersetzung wird im Lauf abgelegt",
      (NFU, "    from backend import sensibel  # noqa: PLC0415\n    if sensibel.aktiv():\n        return\n"
            "    from backend import newsfeed as nf", "    from backend import newsfeed as nf"))
probe("Newsfeed-Uebersetzung wird im Lauf angestossen",
      (NFU, "    if sensibel.aktiv() or not offen:", "    if not offen:"))

# ── Ablauf ──────────────────────────────────────────────────────────────────
for name, aend in PROBEN:
    for rel, _a, _n in aend:
        if not (rel.startswith("backend/") or rel in FRONT):
            print("ABBRUCH: Probe '%s' sabotiert %s, das nicht kopiert wird" % (name, rel))
            sys.exit(2)

basis = baum()
try:
    code, fails, bilanz = lauf(basis)
    if code != 0 or fails != 0 or not bilanz:
        print("ABBRUCH: Basis ist nicht gruen (exit=%s FAIL=%s Bilanz=%s)" % (code, fails, bilanz))
        sys.exit(2)
finally:
    shutil.rmtree(basis, ignore_errors=True)
print("Basis gruen (Wegwerf-Baum)\n")

stumm, abgestuerzt = [], []
for name, aend in PROBEN:
    w = baum()
    try:
        for rel, alt, neu in aend:
            patch(w, rel, alt, neu)
        code, fails, bilanz = lauf(w)
    finally:
        shutil.rmtree(w, ignore_errors=True)
    if code == 1 and bilanz and fails > 0:
        print("  BEISST  %-58s %d FAIL" % (name, fails))
    elif not bilanz or code not in (0, 1):
        abgestuerzt.append(name)
        print("  ABSTURZ %-58s exit=%s (kein Biss)" % (name, code))
    else:
        stumm.append(name)
        print("  STUMM   %-58s" % name)

print("\n%d Proben: %d beissen, %d stumm, %d abgestuerzt"
      % (len(PROBEN), len(PROBEN) - len(stumm) - len(abgestuerzt), len(stumm), len(abgestuerzt)))
sys.exit(1 if (stumm or abgestuerzt) else 0)
