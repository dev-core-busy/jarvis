#!/usr/bin/env python3
"""Waechter: ein gespeichertes MCP-Geheimnis geht nicht still an ein neues Ziel.

Code-Review 2026-11-01: ``config.update_mcp_server`` behaelt ``api_key`` und
``env``, wenn das Formular sie nicht sendet ("leer lassen = unveraendert") –
auch wenn im selben Speichern ``url``/``command``/``args``/``transport``
wechseln. Der Schluessel ging damit beim Neuverbinden an eine frei gewaehlte
Adresse, ohne je eingegeben oder aufgedeckt worden zu sein (BSI M5).

Was festgehalten wird:

0. Positivkontrolle: die ZUSAGE, gegen die die Schranke steht, existiert –
   ``update_mcp_server`` behaelt einen nicht gesendeten Schluessel wirklich
   (sonst waere jede Pruefung unten gegenstandslos).
1. ``mcp_rechte.geheimnis_umleitung`` – Ziel geaendert UND Geheimnis behalten
   -> beanstandet; neu eingegeben, ausdruecklich entfernt, kein Geheimnis oder
   gleiches Ziel (auch mit Rand-Leerzeichen/Schraegstrich) -> frei.
2. Der PUT-Endpunkt in ``main.py`` fragt die Schranke VOR dem Speichern und
   kehrt bei einem Befund zurueck (AST, nicht Text).

``backend.config`` und ``backend.main`` werden NIE importiert.

    python3 tests/test_mcp_umleitung.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if "backend.config" in sys.modules:
    print("ABBRUCH: backend.config ist bereits geladen.", file=sys.stderr)
    raise SystemExit(2)

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


from backend import mcp_rechte as R  # noqa: E402

if "backend.config" in sys.modules or "backend.main" in sys.modules:
    print("ABBRUCH: mcp_rechte hat backend.config/main nachgeladen.", file=sys.stderr)
    raise SystemExit(2)

# ─── 0. Positivkontrolle: die Zusage "leer = unveraendert" existiert ─────────
print("\n0. update_mcp_server behaelt einen nicht gesendeten Schluessel")
cfg_src = (ROOT / "backend" / "config.py").read_text(encoding="utf-8")
cfg_baum = ast.parse(cfg_src)
upd = next((n for n in ast.walk(cfg_baum)
            if isinstance(n, ast.FunctionDef) and n.name == "update_mcp_server"), None)
if upd is None:
    print("ABBRUCH: config.update_mcp_server nicht gefunden.", file=sys.stderr)
    raise SystemExit(2)
ns: dict = {"_ergebnis_max": lambda v: v}
exec(compile(ast.Module(body=[upd], type_ignores=[]), "config.py", "exec"), ns)


class _Stub:
    def __init__(self, srv):
        self._mcp_servers = [srv]

    def _save_to_file(self):
        pass


def _srv(**kw):
    s = {"id": "s1", "name": "x", "enabled": True, "transport": "http",
         "url": "https://mcp.beispiel.de/mcp", "command": "", "args": [],
         "env": {}, "api_key": "geheim-123456", "api_key_header": ""}
    s.update(kw)
    return s


stub = _Stub(_srv())
try:
    erg = ns["update_mcp_server"](stub, "s1", {"url": "https://anders.beispiel.de/mcp"})
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: update_mcp_server laeuft im Stub nicht: {e!r}", file=sys.stderr)
    raise SystemExit(2)
if not (erg and erg.get("api_key") == "geheim-123456"
        and erg.get("url") == "https://anders.beispiel.de/mcp"):
    # Die Zusage gibt es nicht (mehr) – dann ist die Schranke gegenstandslos
    # und die Pruefungen unten waeren trivial. Kein Befund, sondern ein Grund,
    # diesen Waechter neu zu bewerten.
    print("ABBRUCH: update_mcp_server behaelt den Schluessel nicht mehr – "
          "Waechter neu bewerten.", file=sys.stderr)
    raise SystemExit(2)
check(True, "Positivkontrolle: Schluessel bleibt bei neuer URL stehen (die Luecke ist real)")

# ─── 1. Die Schranke ─────────────────────────────────────────────────────────
print("\n1. geheimnis_umleitung")
U = R.geheimnis_umleitung
http = _srv()
stdio = _srv(transport="stdio", url="", command="npx", args=["-y", "server-github"],
             env={"GITHUB_TOKEN": "ghp_abcdef"}, api_key="")

check(U(http, {"url": "https://angreifer.beispiel.de/mcp"}) == ["api_key"],
      "neue URL, Schluessel nicht gesendet -> api_key neu eingeben")
check(U(http, {"url": "https://angreifer.beispiel.de/mcp", "api_key": "neu-999"}) == [],
      "neue URL MIT neu eingegebenem Schluessel -> frei")
check(U(http, {"url": "https://angreifer.beispiel.de/mcp", "api_key": ""}) == [],
      "neue URL, Schluessel ausdruecklich entfernt -> frei")
check(U(http, {"transport": "sse"}) == ["api_key"],
      "Transportwechsel behaelt den Schluessel -> beanstandet")
check(U(http, {"name": "umbenannt", "api_key_header": "X-API-Key"}) == [],
      "nur Name/Header-Name geaendert -> frei")
check(U(http, {"url": "  https://mcp.beispiel.de/mcp/ ", "transport": "http",
               "command": "", "args": []}) == [],
      "gleiches Ziel mit Leerzeichen und Schraegstrich (Formular sendet alles) -> frei")
check(U(_srv(api_key=""), {"url": "https://anders.beispiel.de/mcp"}) == [],
      "kein Schluessel hinterlegt -> nichts zu beanstanden")

check(U(stdio, {"command": "/tmp/fremd.sh"}) == ["env"],
      "neuer Befehl, Umgebung nicht gesendet -> env neu eingeben")
check(U(stdio, {"args": ["-y", "anderes-paket"]}) == ["env"],
      "neue Argumente, Umgebung nicht gesendet -> env neu eingeben")
check(U(stdio, {"command": "/tmp/fremd.sh", "env": {"GITHUB_TOKEN": "neu"}}) == [],
      "neuer Befehl MIT neuer Umgebung -> frei")
check(U(_srv(env={"T_TOKEN": "x"}, api_key="k-1234567"),
        {"url": "https://anders.beispiel.de/mcp"}) == ["api_key", "env"],
      "beide behalten -> beide genannt")
check(U(None, {"url": "x"}) == [] and U(http, ["kein", "objekt"]) == [],
      "unbekannter Server / kein Objekt -> keine Ausnahme")

# ─── 2. Der Endpunkt fragt VOR dem Speichern ─────────────────────────────────
print("\n2. PUT /api/mcp/servers/{id} prueft vor config.update_mcp_server")
main_baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
ep = next((n for n in ast.walk(main_baum)
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "update_mcp_server"), None)
check(ep is not None, "Endpunkt update_mcp_server gefunden")


def _ruft(knoten, name):
    for c in ast.walk(knoten):
        if isinstance(c, ast.Call):
            f = c.func
            if (isinstance(f, ast.Name) and f.id == name) or \
               (isinstance(f, ast.Attribute) and f.attr == name):
                return True
    return False


if ep is not None:
    body = ep.body
    i_save = next((i for i, s in enumerate(body) if _ruft(s, "update_mcp_server")), None)
    i_frage = next((i for i, s in enumerate(body)
                    if isinstance(s, ast.Assign) and _ruft(s, "geheimnis_umleitung")), None)
    check(i_save is not None, "Endpunkt speichert ueber config.update_mcp_server")
    check(i_frage is not None, "Endpunkt ruft geheimnis_umleitung (als Zuweisung)")
    if i_save is not None and i_frage is not None:
        check(i_frage < i_save, "die Schranke steht VOR dem Speichern")
        ziel = body[i_frage].targets[0]
        var = ziel.id if isinstance(ziel, ast.Name) else None
        # Ein if ueber genau diese Variable, das zurueckkehrt – zwischen Frage
        # und Speichern. Sonst waere die Frage gestellt und die Antwort egal.
        # Die Bedingung IST die Variable (``if felder:``) – ein Vorkommen in
        # einem groesseren Ausdruck (``if False and felder``) zaehlt nicht.
        waechter = [s for s in body[i_frage + 1:i_save]
                    if isinstance(s, ast.If)
                    and isinstance(s.test, ast.Name) and s.test.id == var
                    and any(isinstance(n, ast.Return) for n in s.body)]
        check(bool(var) and bool(waechter),
              "ein Befund fuehrt zur Rueckkehr, bevor gespeichert wird")

print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
