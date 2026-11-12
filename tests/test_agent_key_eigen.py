#!/usr/bin/env python3
"""Waechter: ein selbst gewaehlter Agent-API-Key wird geprueft, BEVOR er gilt.

VORGABE DES BETREIBERS (2026-11-12): der Wert des Agent-API-Keys soll in den
Einstellungen editierbar sein ("ich moechte einen eigenen hinterlegen
koennen"). Der Key oeffnet ``POST /api/agent/task`` – also Agentenlaeufe ohne
Anmeldung. Ein zu kurzer, ein nicht kopfzeilentauglicher oder ein schon
vergebener Key darf deshalb NICHT gespeichert werden.

GEMESSEN WIRD DIE WIRKUNG, nicht das Vorkommen: ``_agent_key_eigener_fehler``
und ``agent_keys_update`` werden per AST aus ``backend/main.py`` geschnitten
(Dekoratoren entfernt) und gegen Attrappen mit der ECHTEN Antwortform
ausgefuehrt. Geprueft wird, was danach im gespeicherten Bestand steht.

Aufruf:  python3 tests/test_agent_key_eigen.py [pfad/zu/main.py]
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen
"""
import ast
import asyncio
import hmac
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "backend" / "main.py"

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  OK   " + name)
    else:
        fail += 1
        print("  FAIL " + name + (" – " + detail if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


# ── Schnitt ─────────────────────────────────────────────────────────────────
try:
    baum = ast.parse(MAIN.read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    abbruch("main.py nicht lesbar: %s" % e)

GESUCHT = {"_agent_key_eigener_fehler", "agent_keys_update", "_agent_key_maskiert",
           "AGENT_KEY_MIN_LAENGE", "AGENT_KEY_MAX_LAENGE"}
teile = []
gefunden = set()
for knoten in baum.body:
    if isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)) and knoten.name in GESUCHT:
        knoten.decorator_list = []
        teile.append(knoten)
        gefunden.add(knoten.name)
    elif isinstance(knoten, ast.Assign) and len(knoten.targets) == 1 \
            and isinstance(knoten.targets[0], ast.Name) and knoten.targets[0].id in GESUCHT:
        teile.append(knoten)
        gefunden.add(knoten.targets[0].id)
if gefunden != GESUCHT:
    abbruch("nicht gefunden: %s" % sorted(GESUCHT - gefunden))


# ── Attrappen mit der echten Form ───────────────────────────────────────────
class JSONResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


class Config:
    AGENT_API_KEY = ""


class Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


BESTAND = []


def _load_agent_keys():
    return json.loads(json.dumps(BESTAND))


def _save_agent_keys(keys):
    BESTAND[:] = json.loads(json.dumps(keys))


async def _json_objekt(request):
    b = await request.json()
    return b if isinstance(b, dict) else {}


ns = {"JSONResponse": JSONResponse, "config": Config, "hmac": hmac,
      "_load_agent_keys": _load_agent_keys, "_save_agent_keys": _save_agent_keys,
      "_json_objekt": _json_objekt, "Request": Request, "Depends": lambda *a: None,
      "require_local_auth": None}
modul = ast.Module(body=teile, type_ignores=[])
try:
    exec(compile(modul, str(MAIN), "exec"), ns)
except Exception as e:  # noqa: BLE001
    abbruch("Schnitt nicht ausfuehrbar: %s" % e)

pruefe = ns["_agent_key_eigener_fehler"]
update = ns["agent_keys_update"]

ALT_A = "a" * 43
ALT_B = "b" * 43
GUT = "Mein-eigener_Key.2026!"


def bestand_neu():
    BESTAND[:] = [{"id": "k1", "name": "eins", "key": ALT_A},
                  {"id": "k2", "name": "zwei", "key": ALT_B}]


def put(kid, body):
    return asyncio.run(update(kid, Request(body), user="probe"))


def key_von(kid):
    for k in BESTAND:
        if k["id"] == kid:
            return k["key"]
    return None


# ── Positivkontrolle: der Schnitt speichert ueberhaupt ──────────────────────
print("\n0) Positivkontrolle")
bestand_neu()
r = put("k1", {"key": GUT})
if r.status_code != 200 or key_von("k1") != GUT:
    abbruch("ein gueltiger eigener Key wird nicht gespeichert (status=%s, key=%r) – "
            "der Pruefstand misst nichts" % (r.status_code, key_von("k1")))
check("gueltiger eigener Key wird gespeichert", True)
check("Antwort gibt den Key NICHT heraus (BSI M5)",
      isinstance(r.content.get("key"), dict) and r.content["key"].get("key") == "",
      repr(r.content.get("key")))

# ── 1) Pruefregel einzeln ───────────────────────────────────────────────────
print("\n1) Pruefregel")
MIN = ns["AGENT_KEY_MIN_LAENGE"]
check("Mindestlaenge ist mindestens 16", MIN >= 16, "MIN=%r" % MIN)
check("gueltig: %d Zeichen" % MIN, pruefe("x" * MIN, [], "k1") == "")
check("zu kurz: %d Zeichen" % (MIN - 1), pruefe("x" * (MIN - 1), [], "k1") != "")
check("zu lang", pruefe("x" * (ns["AGENT_KEY_MAX_LAENGE"] + 1), [], "k1") != "")
check("Leerzeichen abgelehnt", pruefe("abcdefgh ijklmnopq", [], "k1") != "")
check("Umlaut abgelehnt (Kopfzeile)", pruefe("abcdefghijklmnöpq", [], "k1") != "")
check("Steuerzeichen abgelehnt", pruefe("abcdefghijklmnopq\x01", [], "k1") != "")
check("kein Text abgelehnt", pruefe(12345678901234567890, [], "k1") != "")
bestand_neu()
check("Key eines ANDEREN Eintrags abgelehnt", pruefe(ALT_B, BESTAND, "k1") != "")
check("eigener bisheriger Key ist kein Duplikat", pruefe(ALT_A, BESTAND, "k1") == "")
Config.AGENT_API_KEY = "legacy-schluessel-1234567"
check("Legacy-Key abgelehnt", pruefe("legacy-schluessel-1234567", [], "k1") != "")
Config.AGENT_API_KEY = ""

# ── 2) Wirkung am Endpunkt: abgelehnt heisst UNVERAENDERT ───────────────────
print("\n2) Endpunkt: ein abgelehnter Key aendert nichts")
for name, wert in [("zu kurz", "kurz"), ("mit Leerzeichen", "abcdefgh ijklmnopq"),
                   ("Duplikat", ALT_B), ("Umlaut", "abcdefghijklmnöpq")]:
    bestand_neu()
    r = put("k1", {"key": wert})
    check("%s: 400" % name, r.status_code == 400, "status=%s" % r.status_code)
    check("%s: Grund genannt" % name,
          bool(r.content.get("error")) and r.content.get("ok") is False, repr(r.content))
    check("%s: Bestand unveraendert" % name, key_von("k1") == ALT_A, repr(key_von("k1")))

bestand_neu()
r = put("k1", {"key": "  " + GUT + "  "})
check("Leerraum aussen wird abgeschnitten", key_von("k1") == GUT, repr(key_von("k1")))
bestand_neu()
r = put("k1", {"name": "neu"})
check("Umbenennen laesst den Key stehen", key_von("k1") == ALT_A)
bestand_neu()
r = put("k1", {"regenerate": True})
check("Neu generieren geht weiter (nicht durch die Eigen-Pruefung blockiert)",
      r.status_code == 200 and key_von("k1") not in (ALT_A, None)
      and len(key_von("k1") or "") >= MIN)
bestand_neu()
r = put("zz", {"key": GUT})
check("unbekannte Kennung: 404", r.status_code == 404)

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
