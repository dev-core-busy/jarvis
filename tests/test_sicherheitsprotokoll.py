#!/usr/bin/env python3
"""Waechter fuer die Ansicht des Sicherheitsprotokolls (Backend-Seite).

1. ``sicherheits_log.lesen`` (Filter) und ``arten`` gegen eine Wegwerfdatei,
   geschrieben mit dem ECHTEN ``ereignis()`` – inklusive Kette und Schluessel.
2. ``GET /api/security/log`` per AST aus main.py geschnitten und AUSGEFUEHRT:
   Pruefmaterial (prev/hash/mac) geht nicht hinaus, die Kettenaussage schon,
   eine veraenderte Zeile wird gemeldet, der Deckel greift.
3. Als REGEL: auf ``/api/security/log`` gibt es nur GET (kein Loeschweg), und
   der GET haengt an ``require_local_auth`` (Administratoren).

Laeuft ohne fastapi; ``backend.config`` nur als Attrappe (Exit 2 sonst).
"""

import ast
import asyncio
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_ok = _fail = 0


def pruefe(bed, text):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text)


_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(get_setting=lambda k, d=None: d)
sys.modules["backend.config"] = _cfg
from backend import sicherheits_log as SL  # noqa: E402

if getattr(sys.modules["backend.config"], "__file__", None):
    print("ABBRUCH: echtes backend.config geladen", file=sys.stderr)
    sys.exit(2)

SAND = Path(tempfile.mkdtemp(prefix="sprot_test_"))
SL.DATEI = SAND / "sicherheit.jsonl"
SL._letzter_hash = None
SL._letzte_datei = None
_SYSLOG_ORIG = SL._syslog_logger           # fuer Abschnitt 4 (eigener Empfaenger)
SL._syslog_logger = lambda: None          # nichts ins echte Journal
SL.schluessel_setzen("test-geheimnis")
if not str(SL.DATEI).startswith(str(SAND)):
    print("ABBRUCH: Sandkasten greift nicht", file=sys.stderr)
    sys.exit(2)

print("\n== 1. lesen / arten")
SL.ereignis("anmeldung", benutzer="FIRMA\\Mueller", ip="192.0.2.7", ergebnis="erfolg", weg="kennwort")
SL.ereignis("anmeldung_fehlgeschlagen", benutzer="", ip="192.0.2.99", ergebnis="401", weg="windows")
SL.ereignis("admin_aenderung", benutzer="jarvis", ip="192.0.2.8", ergebnis="200", pfad="/api/x")
SL.ereignis("anmeldung", benutzer="meier", ip="192.0.2.7", ergebnis="erfolg")
pruefe(SL.pruefen()["ok"], "Positivkontrolle: frisch geschriebene Kette ist intakt")
alle = SL.lesen()
pruefe([e["art"] for e in alle] == ["anmeldung", "admin_aenderung", "anmeldung_fehlgeschlagen", "anmeldung"],
       "juengste zuerst")
pruefe([e["benutzer"] for e in SL.lesen(benutzer="mueller")] == ["FIRMA\\Mueller"],
       "Benutzerfilter: Teilstring, ohne Gross/Klein, Praefix egal")
pruefe(len(SL.lesen(ip="192.0.2.7")) == 2, "IP-Filter")
pruefe(len(SL.lesen(art="anmeldung", ip="192.0.2.7")) == 2 and not SL.lesen(art="anmeldung", benutzer="jarvis"),
       "Filter wirken zusammen (UND)")
pruefe(len(SL.lesen(limit=1)) == 1, "Deckel")
pruefe(SL.arten() == ["admin_aenderung", "anmeldung", "anmeldung_fehlgeschlagen"],
       "arten(): vorkommende Arten, sortiert, ohne Doppelte")

print("\n== 2. Endpunkt (geschnitten, ausgefuehrt)")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)
fn = next((n for n in BAUM.body if isinstance(n, ast.AsyncFunctionDef)
           and n.name == "sicherheitsprotokoll_lesen"), None)
pruefe(fn is not None, "Endpunkt-Funktion existiert")
if fn is None:
    print("\nBILANZ: %d OK, %d FAIL" % (_ok, _fail))
    sys.exit(1)


class JSONResponse:
    def __init__(self, content, status_code=200, headers=None, media_type=None, background=None):
        self.status_code = status_code
        self.inhalt = content


fn2 = ast.AsyncFunctionDef(**{k: getattr(fn, k) for k in fn._fields})
fn2.decorator_list = []
ns = {"JSONResponse": JSONResponse, "asyncio": asyncio, "_sicherheits_log": SL,
      "Depends": lambda f: None, "require_local_auth": None,
      "_display_name": lambda u: "ANZ:" + u}
exec(compile(ast.fix_missing_locations(ast.Module(body=[fn2], type_ignores=[])), "main.py", "exec"), ns)
lauf = ns["sicherheitsprotokoll_lesen"]

d = asyncio.run(lauf(limit=200, art="", benutzer="", ip="", _u="admin")).inhalt
pruefe(d["ok"] and len(d["eintraege"]) == 4, "liefert alle Eintraege")
pruefe(not any(k in e for e in d["eintraege"] for k in ("prev", "hash", "mac")),
       "Pruefmaterial (prev/hash/mac) geht nicht hinaus")
pruefe(d["eintraege"][0].get("benutzer_anzeige") == "ANZ:meier", "Anzeigename je Eintrag")
pruefe("benutzer_anzeige" not in d["eintraege"][2], "leerer Benutzer bekommt keinen Anzeigenamen")
pruefe(d["kette"]["ok"] is True and d["kette"]["zeilen"] == 4, "Kettenaussage: intakt, 4 Zeilen")
pruefe(d["arten"] == SL.arten() and d["aufbewahrung_tage"] == SL.aufbewahrung_tage(), "Arten und Frist dabei")
d = asyncio.run(lauf(limit=99999, art="", benutzer="", ip="", _u="admin")).inhalt
pruefe(len(d["eintraege"]) == 4, "uebergrosser Deckel wird begrenzt, nicht abgewiesen")
d = asyncio.run(lauf(limit=200, art="anmeldung", benutzer="meier", ip="", _u="admin")).inhalt
pruefe([e["benutzer"] for e in d["eintraege"]] == ["meier"], "Filter kommen beim Lesen an")

# Eine Zeile in der Mitte veraendern -> die Ansicht muss es sagen
zeilen = SL.DATEI.read_text(encoding="utf-8").splitlines()
e = json.loads(zeilen[1])
e["ergebnis"] = "erfolg"
zeilen[1] = json.dumps(e, ensure_ascii=False)
SL.DATEI.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
d = asyncio.run(lauf(limit=200, art="", benutzer="", ip="", _u="admin")).inhalt
pruefe(d["kette"]["ok"] is False and d["kette"]["anzahl_brueche"] >= 1
       and any(b["grund"] == "Inhalt veraendert" for b in d["kette"]["brueche"]),
       "veraenderte Zeile wird als Bruch gemeldet (%s)" % d["kette"]["brueche"])

# Der Deckel ist nur mit MEHR als 1000 Eintraegen messbar – mit vieren waere
# die Pruefung oben trivial wahr, auch ohne jede Begrenzung.
for i in range(1005):
    SL.ereignis("anmeldung", benutzer="last%d" % i, ip="192.0.2.50", ergebnis="erfolg")
d = asyncio.run(lauf(limit=5000, art="", benutzer="", ip="", _u="admin")).inhalt
pruefe(len(d["eintraege"]) == 1000, "Deckel 1000 greift (%d)" % len(d["eintraege"]))

print("\n== 3. Regeln: nur lesen, nur Administratoren")
routen = []
for n in BAUM.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for dek in n.decorator_list:
            if isinstance(dek, ast.Call) and isinstance(dek.func, ast.Attribute) and dek.args \
                    and isinstance(dek.args[0], ast.Constant) \
                    and str(dek.args[0].value).startswith("/api/security/log"):
                routen.append((dek.func.attr, dek.args[0].value, n))
pruefe(len(routen) >= 1, "Positivkontrolle: Route gefunden")
pruefe(all(m == "get" for m, _, _ in routen), "nur GET – kein Loesch- oder Schreibweg (%s)"
       % [m for m, _, _ in routen])
pruefe(all("require_local_auth" in ast.unparse(n.args) for _, _, n in routen),
       "haengt an require_local_auth (Administratoren)")

print("\n== 4. Syslog-Schwere (Datagramme mitgelesen)")
# Befund 2026-10-20: Stufe 25 hiess "Level 25" und SysLogHandler machte daraus
# "warning" – jedes Sicherheitsereignis stand als Warnung im Journal. Gemessen
# wird am DRAHT: PRI = Facility * 8 + Schwere (authpriv = 10).
import logging  # noqa: E402
import logging.handlers  # noqa: E402
import socket  # noqa: E402

empf = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
empf.bind(("127.0.0.1", 0))
empf.settimeout(3)
port = empf.getsockname()[1]
SL._syslog = None
SL._syslog_logger = lambda: _SYSLOG_ORIG(("127.0.0.1", port))


def pri_von(art, **kw):
    SL.ereignis(art, **kw)
    try:
        roh = empf.recv(65535).decode("utf-8", "replace")
    except socket.timeout:
        return None, ""
    return (int(roh[1:roh.index(">")]) if roh.startswith("<") and ">" in roh else None), roh


p1, roh1 = pri_von("anmeldung", benutzer="a.b", ergebnis="erfolg")
pruefe(p1 is not None and "jarvis-security" in roh1,
       "Positivkontrolle: Datagramm mit Kennung empfangen (%s)" % roh1[:40])
pruefe(p1 == 10 * 8 + 5, "gewoehnliches Ereignis kommt als notice an (PRI %s, erwartet 85)" % p1)
p2, _ = pri_von("anmeldung_fehlgeschlagen", ergebnis="401")
pruefe(p2 == 10 * 8 + 4, "Fehlschlag bleibt warning (PRI %s, erwartet 84)" % p2)
p3, _ = pri_von("konto_gesperrt", benutzer="a.b")
pruefe(p3 == 84, "Kontosperre bleibt warning (PRI %s)" % p3)
# Keine globale Aenderung: ein fremder SysLogHandler bildet Stufe 25 weiter
# wie gewohnt ab (sonst haette der Fix das Verhalten anderer Module veraendert).
fremd = logging.handlers.SysLogHandler(address=("127.0.0.1", port))
pruefe(fremd.mapPriority(logging.getLevelName(SL.NOTICE)) == "warning",
       "fremde SysLogHandler bleiben unberuehrt (kein addLevelName, keine Klassenaenderung)")
fremd.close()
empf.close()

print("\nBILANZ: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
