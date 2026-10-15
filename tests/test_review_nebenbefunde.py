#!/usr/bin/env python3
"""Waechter: Nebenbefunde aus dem Code-Review 2026-09-28.

Vier Befunde, jeder an der WIRKUNG gemessen (nicht am Vorkommen einer Zeile):

  [1] ai_mouse_fragen: bei voller Liste schrieb JEDES Lesen die Datei neu.
  [2] license.instanz_kennung: zwei gleichzeitige Erstaufrufe teilten eine
      Temp-Datei – verschiedene Antworten, eine davon "".
  [3] /api/knowledge/assignments: `{"groups": [1]}` wurde zu `[]` normiert und
      nahm der Datei ALLE Gruppen.
  [4] Anhaenge: ein altes, leeres Kennungs-Verzeichnis konnte zwischen
      `anhang_verzeichnis(anlegen=True)` und dem Schreiben der Kopie per
      `rmdir` verschwinden.

Der fuenfte (Pivot-Rest in excel.js) laeuft in `test_excel_objekt_rest_ui.js`
– er braucht die Office.js-Attrappe.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
FAIL = 0


def check(name: str, bed: bool) -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name)


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


# backend.config NUR als Stub – der echte Import schreibt die Live-settings.json.
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules.setdefault("backend.config", _cfg)

TMP = Path(tempfile.mkdtemp(prefix="waechter-review-"))


# ── [1] ai_mouse_fragen: kein Schreiben bei voller Liste ──────────────────────
print("\n[1] Vorgaben bei voller Liste: Lesen schreibt nicht")
try:
    from backend import ai_mouse_fragen as amf
except Exception as e:  # noqa: BLE001
    abbruch("backend.ai_mouse_fragen nicht importierbar: %s" % e)

_datei = TMP / "ai_mouse_fragen.json"
amf._pfad = lambda: _datei
_schreibe = []
_echt_speichern = amf._speichern


def _zaehlend(d):
    _schreibe.append(1)
    return _echt_speichern(d)


amf._speichern = _zaehlend


def _stand(n_eigene: int) -> dict:
    k = amf._norm("anna")
    return {
        "version": 1, "global_": [], "_gesaet_vorgaben": True,
        "_global_geraeumt": True, "gesaet_fuer": [k],
        "vorgaben": [{"id": "v-neu", "titel": "Neue Vorgabe", "prompt": "p"}],
        "vorgaben_bekommen": {k: []},
        "benutzer": {k: [amf._neu("F%d" % i, "p") for i in range(n_eigene)]},
    }


# Positivkontrolle: mit Platz WIRD geschrieben und die Vorgabe kommt an – sonst
# waere "0 Schreibvorgaenge" unten trivial wahr.
_datei.write_text(json.dumps(_stand(amf.MAX_JE_BENUTZER - 1)), encoding="utf-8")
_schreibe.clear()
_l = amf.liste("anna")
check("Positivkontrolle: mit Platz kommt die Vorgabe an und wird gespeichert",
      len(_schreibe) == 1 and any(e.get("titel") == "Neue Vorgabe" for e in _l))

_datei.write_text(json.dumps(_stand(amf.MAX_JE_BENUTZER)), encoding="utf-8")
_schreibe.clear()
for _ in range(3):
    amf.liste("anna")
check("volle Liste: drei Lesevorgaenge schreiben nichts (ist: %d)" % len(_schreibe),
      len(_schreibe) == 0)
_d = json.loads(_datei.read_text(encoding="utf-8"))
check("volle Liste: die Vorgabe bleibt als 'noch nicht bekommen' stehen",
      "v-neu" not in (_d.get("vorgaben_bekommen") or {}).get(amf._norm("anna"), []))


# ── [2] license.instanz_kennung: erste Kennung gewinnt ────────────────────────
print("\n[2] Instanz-Kennung bei gleichzeitigem Erstaufruf")
try:
    from backend import license as lic
except Exception as e:  # noqa: BLE001
    abbruch("backend.license nicht importierbar: %s" % e)

lic.INSTANZ_FILE = TMP / "data" / ".instanz"
_echt_link, _echt_replace = os.link, os.replace
_innen: list = []
_gerufen = threading.Event()


def _mit_zwischenruf(echt):
    # Genau EIN verschachtelter Erstaufruf, und zwar an der Stelle, an der der
    # aeussere seine Datei gerade einsetzen will – das ist das Wettrennen.
    # ⚠ Die Marke VOR dem Aufruf setzen: der innere Aufruf kommt an dieselbe
    # Stelle, und ohne Marke riefe er sich selbst bis zum RecursionError.
    def f(a, b, *args, **kw):
        if not _gerufen.is_set() and Path(b) == lic.INSTANZ_FILE:
            _gerufen.set()
            _innen.append(lic.instanz_kennung())
        return echt(a, b, *args, **kw)
    return f


os.link = _mit_zwischenruf(_echt_link)
os.replace = _mit_zwischenruf(_echt_replace)
try:
    _aussen = lic.instanz_kennung()
finally:
    os.link, os.replace = _echt_link, _echt_replace

check("Positivkontrolle: der Zwischenruf fand statt", len(_innen) == 1)
_datei_k = ""
try:
    _datei_k = "D1-" + lic.INSTANZ_FILE.read_text().strip()
except Exception:  # noqa: BLE001
    pass
check("beide Aufrufer bekommen eine Kennung (aussen=%r)" % _aussen,
      bool(_aussen) and bool(_innen and _innen[0]))
check("beide bekommen DIESELBE", bool(_innen) and _aussen == _innen[0])
check("und es ist die, die in der Datei steht", _aussen == _datei_k)
check("keine Temp-Datei bleibt liegen",
      [p.name for p in lic.INSTANZ_FILE.parent.iterdir()] == [".instanz"])
check("ein spaeterer Aufruf liest dieselbe", lic.instanz_kennung() == _aussen)


# ── [3] /api/knowledge/assignments: Nicht-Strings loeschen keine Gruppen ──────
print("\n[3] Gruppenzuordnung: fremde Eintraege sind ein 400, kein 'alles weg'")
_main_src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
_baum = ast.parse(_main_src)
_fn = next((n for n in _baum.body if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "knowledge_assignments_set"), None)
_norm_fn = next((n for n in _baum.body if isinstance(n, ast.FunctionDef)
                 and n.name == "_gruppen_normieren"), None)
if _fn is None or _norm_fn is None:
    abbruch("knowledge_assignments_set / _gruppen_normieren nicht in main.py")
_fn.decorator_list = []
for a in _fn.args.args + _fn.args.kwonlyargs:
    a.annotation = None
_fn.args.defaults = [ast.Constant(None) for _ in _fn.args.defaults]
_mod = ast.Module(body=[_norm_fn, _fn], type_ignores=[])
ast.fix_missing_locations(_mod)


class _Antwort:
    def __init__(self, inhalt, status_code=200):
        self.inhalt, self.status_code = inhalt, status_code


class _HTTPFehler(Exception):
    def __init__(self, status_code, detail=""):
        super().__init__(detail)
        self.status_code = status_code


_gesetzt: list = []
_kg = types.ModuleType("backend.knowledge_groups")
_kg.get_assignment = lambda p: ["g1", "g2"]
_kg.get_group = lambda g: {"id": g}
_kg.set_assignment = lambda p, g: (_gesetzt.append((p, list(g))), list(g))[1]
_kg._rel = lambda p: str(p).lstrip("/")   # echte Form: relativer Posix-Schluessel
sys.modules["backend.knowledge_groups"] = _kg
import backend  # noqa: E402
backend.knowledge_groups = _kg

_ns = {"JSONResponse": _Antwort, "HTTPException": _HTTPFehler,
       "_may_edit_knowledge": lambda u: True,
       "_is_kb_group_editor": lambda u, g: True,
       "Depends": lambda x: None, "require_auth": None,
       "Request": object, "__name__": "waechter",
       # Ortspruefung (Code-Review 2026-10-07) misst test_wissen_datei_freigabe;
       # hier geht es nur um die Gruppen – jeder Pfad gilt als Wissensort.
       "_wissen_schluessel_erlaubt": lambda rel: True}
exec(compile(_mod, "main.py", "exec"), _ns)
_endpunkt = _ns["knowledge_assignments_set"]


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


def _rufe(body):
    _gesetzt.clear()
    try:
        r = asyncio.run(_endpunkt(_Req(body), user="admin"))
    except _HTTPFehler as e:
        return e.status_code
    return r.status_code


check("Positivkontrolle: gueltige Liste wird gesetzt",
      _rufe({"path": "a.pdf", "groups": ["g1"]}) == 200 and _gesetzt == [("a.pdf", ["g1"])])
check("Positivkontrolle: leere Liste entfernt (gewollt)",
      _rufe({"path": "a.pdf", "groups": []}) == 200 and _gesetzt == [("a.pdf", [])])
for _body, _txt in (({"path": "a.pdf", "groups": [1]}, "[1]"),
                    ({"path": "a.pdf", "groups": [None]}, "[None]"),
                    ({"path": "a.pdf", "groups": ["g1", 7]}, '["g1", 7]'),
                    ({"path": "a.pdf", "groups": ["  "]}, '["  "]')):
    _st = _rufe(_body)
    check("%s -> 400 und nichts gesetzt (ist: %s, gesetzt: %s)" % (_txt, _st, _gesetzt),
          _st == 400 and _gesetzt == [])


# ── [4] Anhaenge: Anlegen frischt auf, Aufraeumen wartet auf die Sperre ────────
print("\n[4] Anhang-Verzeichnis: kein rmdir zwischen Anlegen und Schreiben")
try:
    from backend import lauf_tmp as lt
    from backend import attachments as att
except Exception as e:  # noqa: BLE001
    abbruch("lauf_tmp/attachments nicht importierbar: %s" % e)

_anh = TMP / "jarvis-anhaenge"
lt.ANH_ROOT = _anh
lt.bwrap_verfuegbar = lambda *a, **k: True
_k = lt.benutzer_kennung("anna")
if not _k:
    abbruch("benutzer_kennung liefert nichts")
(_anh / _k).mkdir(parents=True)
_alt = time.time() - 10 * 3600
os.utime(_anh / _k, (_alt, _alt))
_grenze = time.time() - 4 * 3600

# Positivkontrolle: OHNE Anlegen raeumt der Aufraeumer das alte leere
# Verzeichnis ab – sonst misst die Pruefung darunter nichts.
_weg = att._leere_kennungen_entfernen(_grenze, os.getuid())
check("Positivkontrolle: altes leeres Verzeichnis wird abgeraeumt", _weg == [_k])

(_anh / _k).mkdir(parents=True)
os.utime(_anh / _k, (_alt, _alt))
_z = lt.anhang_verzeichnis("anna", anlegen=True)
check("Positivkontrolle: anhang_verzeichnis liefert das Kennungs-Verzeichnis",
      _z == _anh / _k)
att._leere_kennungen_entfernen(_grenze, os.getuid())
check("nach dem Anlegen ueberlebt es den naechsten Aufraeum-Durchgang",
      (_anh / _k).is_dir())

_sperre = getattr(lt, "ANH_VERZ_SPERRE", None)
check("es gibt eine gemeinsame Sperre", _sperre is not None)
if _sperre is not None:
    # ⚠ Ohne Fix kann das Verzeichnis hier schon fehlen – neu anlegen statt
    # werfen, sonst endet der Waechter ohne Bilanz statt mit FAIL.
    (_anh / _k).mkdir(parents=True, exist_ok=True)
    os.utime(_anh / _k, (_alt, _alt))
    _fertig = threading.Event()
    _t = threading.Thread(target=lambda: (att._leere_kennungen_entfernen(_grenze, os.getuid()),
                                          _fertig.set()), daemon=True)
    with _sperre:
        _t.start()
        _blockiert = not _fertig.wait(0.5)
        # Waehrend der Aufraeumer wartet, frischt das Anlegen auf ...
        try:
            os.utime(_anh / _k)
        except OSError:
            pass                      # schon weg: der Fall, den es zu melden gilt
    _t.join(5)
    check("der Aufraeumer wartet auf die Sperre", _blockiert)
    check("... und sieht danach das frische Verzeichnis", (_anh / _k).is_dir())


print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
