#!/usr/bin/env python3
"""Waechter: MCP-Freigabe je Benutzer/Gruppe und API-Schluessel (2026-10-25).

Was festgehalten wird:

1. ``mcp_rechte.darf_benutzen`` – drei Stufen (alle / Auswahl / niemand),
   Benutzer UND Gruppen ODER-verknuepft, leer = niemand, fail-closed.
2. ``norm_login`` ist dieselbe Regel wie ``main._norm_login`` (die Kopie
   existiert, damit das Modul ohne ``backend.main`` laeuft – also muss die
   Gleichheit GEMESSEN werden, nicht angenommen).
3. API-Schluessel: Header-Form, Header-Injektion abgewiesen, der Schluessel
   verlaesst das Backend nie (POST/PUT-Antwort, Status beider Zweige).
4. config.py: neue Felder an BEIDEN Stellen (add UND update) – die Regel
   "neues Feld = zwei Stellen".
5. Beide HTTP-Transporte schicken den Schluessel (der "http"-Zweig faellt auf
   SSE zurueck – ein Haken nur am Streamable-Weg liesse ihn dort fallen).

``backend.config`` wird NIE importiert (schreibt die Live-settings.json);
config-Methoden laufen per AST-Schnitt auf einem Stub-``self``.

    python3 tests/test_mcp_rechte.py
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
    print("ABBRUCH: mcp_rechte zieht config/main beim Import mit.", file=sys.stderr)
    raise SystemExit(2)

MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
CFG_SRC = (ROOT / "backend" / "config.py").read_text(encoding="utf-8")
MCP_SRC = (ROOT / "backend" / "mcp_client.py").read_text(encoding="utf-8")


def _funktion(quelle, name, klasse=None):
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if klasse and isinstance(knoten, ast.ClassDef) and knoten.name == klasse:
            for f in knoten.body:
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == name:
                    return f
        if not klasse and isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and knoten.name == name:
            return knoten
    print(f"ABBRUCH: {name} nicht gefunden.", file=sys.stderr)
    raise SystemExit(2)


# ── Positivkontrolle der Gruppen-Attrappe ───────────────────────────────────
# Die Attrappe bildet `_member_of_any_group(member_of, groups_raw)` nach: Liste
# von DNs gegen zeilengetrennte Wunschgruppen. Trifft sie den bekannten Fall
# nicht, sind alle Gruppenpruefungen darunter wertlos.
def _passt(dns, gruppen_raw):
    wunsch = {g.strip().lower() for g in gruppen_raw.splitlines() if g.strip()}
    return any(d.lower() in wunsch for d in dns)


G1 = "CN=MCP Nutzer,OU=Gruppen,DC=firma,DC=local"
G2 = "CN=Andere,OU=Gruppen,DC=firma,DC=local"
if not (_passt([G1], G1 + "\n" + G2) and not _passt([G2], G1)):
    print("ABBRUCH: Gruppen-Attrappe trifft den Kontrollfall nicht.", file=sys.stderr)
    raise SystemExit(2)

# ── 1. darf_benutzen ────────────────────────────────────────────────────────
print("\n1. darf_benutzen")
D = lambda srv, u, dns=None: R.darf_benutzen(srv, u, gruppen_dns=dns or [], gruppe_passt=_passt)
check(D(None, "a") is False, "kein Server: nein")
check(D({}, "a") is False, "leer = niemand")
check(D({"allow_network_users": True}, "a") is True, "Stufe alle: ja")
for wert in ("ja", 1, "true", None, False):
    check(D({"allow_network_users": wert}, "a") is False,
          f"allow_network_users={wert!r} ist keine Freigabe")
check(D({"allowed_users": "a.b, c.d"}, "C.D") is True, "Benutzerliste, Gross/Klein")
check(D({"allowed_users": "FIRMA\\c.d"}, "c.d@firma.local") is True,
      "Normalisierung auf BEIDEN Seiten (Domain-Praefix gegen UPN)")
check(D({"allowed_users": "a.b"}, "c.d") is False, "nicht in der Liste: nein")
check(D({"allowed_users": "a.b"}, "") is False, "leerer Benutzer: nein")
check(D({"allowed_group": G1}, "x", [G1]) is True, "Mitglied der Gruppe: ja")
check(D({"allowed_group": G1}, "x", [G2]) is False, "andere Gruppe: nein")
check(D({"allowed_group": G2 + "\n" + G1}, "x", [G1]) is True,
      "mehrere Gruppen zeilengetrennt")
check(D({"allowed_users": "a.b", "allowed_group": G1}, "x", [G1]) is True,
      "Benutzer ODER Gruppe – Gruppe allein genuegt")
check(D({"allowed_users": "x", "allowed_group": G2}, "x", []) is True,
      "Benutzer ODER Gruppe – Liste allein genuegt")


def _wirft(dns, g):
    raise RuntimeError("Verzeichnis weg")


check(R.darf_benutzen({"allowed_group": G1}, "x", gruppe_passt=_wirft) is False,
      "Pruefung wirft: nein (fail-closed)")
check(R.freigabe_art({"allowed_users": " , "}) == "keine",
      "Liste nur aus Trennern zaehlt als leer")

# ── 2. norm_login == main._norm_login ───────────────────────────────────────
print("\n2. norm_login gleich main._norm_login")
_ns = {}
exec(compile(ast.Module(body=[_funktion(MAIN_SRC, "_norm_login")], type_ignores=[]),
             "main", "exec"), _ns)
for probe in ["FIRMA\\M.Muster", "m.muster@firma.local", "  M.MUSTER ", "",
              "a\\b\\c", "x@y@z", "Name"]:
    check(R.norm_login(probe) == _ns["_norm_login"](probe), f"gleich fuer {probe!r}")

# ── 3. Freigabefelder normalisieren ─────────────────────────────────────────
print("\n3. freigabe_normalisieren")
n = R.freigabe_normalisieren({"allowed_users": " a , ,b ", "allowed_group": f"\n{G1}\n\n{G2} \n",
                               "allow_network_users": "ja"})
check(n.get("allowed_users") == "a, b", "Benutzer: getrimmt, leere weg")
check(n.get("allowed_group") == f"{G1}\n{G2}", "Gruppen: zeilengetrennt, leere weg")
check(n.get("allow_network_users") is False, '"ja" wird False')
check(R.freigabe_normalisieren({}) == {}, "nicht gesendet = nicht angefasst (Teil-Update)")

# ── 4. API-Schluessel ───────────────────────────────────────────────────────
print("\n4. auth_header")
check(R.auth_header({}) == {}, "ohne Schluessel: kein Header")
check(R.auth_header({"api_key": "  "}) == {}, "nur Leerraum: kein Header")
check(R.auth_header({"api_key": "abc"}) == {"Authorization": "Bearer abc"},
      "Vorgabe: Authorization: Bearer")
check(R.auth_header({"api_key": "Basic xyz"}) == {"Authorization": "Basic xyz"},
      "Wert mit Schema bleibt unveraendert")
check(R.auth_header({"api_key": "abc", "api_key_header": "X-API-Key"}) == {"X-API-Key": "abc"},
      "eigener Header traegt den Schluessel nackt")
for schlecht in ["X-API-Key\r\nX-Evil: 1", "mit leer", "a:b", "x" * 65]:
    check(not R.header_name_gueltig(schlecht), f"Header-Name abgewiesen: {schlecht[:20]!r}")
    try:
        R.auth_header({"api_key": "k", "api_key_header": schlecht})
        check(False, f"auth_header wirft bei {schlecht[:20]!r}")
    except ValueError:
        check(True, f"auth_header wirft bei {schlecht[:20]!r}")
check(R.header_name_gueltig("") and R.header_name_gueltig("X-API-Key"),
      "leer und X-API-Key gueltig")
try:
    R.auth_header({"api_key": "a\nb"})
    check(False, "Zeilenumbruch im Schluessel wird abgewiesen")
except ValueError:
    check(True, "Zeilenumbruch im Schluessel wird abgewiesen")
o = R.ohne_geheimnisse({"id": "1", "api_key": "geheim"})
check("api_key" not in o and o.get("api_key_gesetzt") is True,
      "ohne_geheimnisse: Wert weg, nur 'gesetzt'")
check(R.ohne_geheimnisse({"id": "1"}).get("api_key_gesetzt") is False, "ohne Schluessel: False")

# Name gilt dem Tresor als geheim -> auf der Platte verpackt.
_tr = {}
_tresor_src = (ROOT / "backend" / "geheimnis_tresor.py").read_text(encoding="utf-8")
_tb = ast.parse(_tresor_src)
_teile = [k for k in _tb.body if isinstance(k, ast.Assign) and any(
    getattr(t, "id", "") in ("GEHEIME_NAMEN", "GEHEIME_ENDUNGEN") for t in k.targets)]
_teile.append(_funktion(_tresor_src, "ist_geheimer_name"))
exec(compile(ast.Module(body=_teile, type_ignores=[]), "tresor", "exec"), _tr)
check(_tr["ist_geheimer_name"]("api_key") is True, "Feld 'api_key' wird im Tresor verpackt")
check(_tr["ist_geheimer_name"]("api_key_header") is False,
      "'api_key_header' ist Konfiguration, kein Geheimnis")

# ── 5. config.py: beide Stellen ─────────────────────────────────────────────
print("\n5. config.py add/update")


class _Self:
    def __init__(self):
        self._mcp_servers = []

    def _save_to_file(self):
        pass


_cns = {"uuid": __import__("uuid")}
for name in ("add_mcp_server", "update_mcp_server"):
    f = _funktion(CFG_SRC, name, klasse="Config")
    exec(compile(ast.Module(body=[f], type_ignores=[]), "config", "exec"), _cns)
add, upd = _cns["add_mcp_server"], _cns["update_mcp_server"]
me = _Self()
srv = add(me, {"name": "t", "transport": "streamable_http", "url": "https://h/mcp",
               "api_key": " k1 ", "api_key_header": "X-API-Key",
               "allowed_users": "a, b", "allowed_group": G1, "allow_network_users": True})
check(srv["api_key"] == "k1" and srv["api_key_header"] == "X-API-Key",
      "add: Schluessel + Header gespeichert")
check(srv["allowed_users"] == "a, b" and srv["allowed_group"] == G1,
      "add: Benutzer + Gruppen gespeichert")
check(srv["allow_network_users"] is True, "add: Stufe alle gespeichert")
srv2 = add(me, {"name": "u"})
check(srv2.get("allowed_users") == "" and srv2.get("allowed_group") == ""
      and srv2.get("api_key") == "",
      "add ohne Angaben: leer (= nur Administratoren)")
sid = srv["id"]
upd(me, sid, {"url": "https://h2/mcp"})
check(me._mcp_servers[0]["api_key"] == "k1", "update OHNE api_key laesst ihn stehen")
check(me._mcp_servers[0]["allowed_users"] == "a, b", "update ohne Freigabe laesst sie stehen")
upd(me, sid, {"api_key": "k2", "allowed_users": "c", "allowed_group": "",
              "allow_network_users": False})
s0 = me._mcp_servers[0]
check(s0["api_key"] == "k2", "update setzt neuen Schluessel")
check(s0["allowed_users"] == "c" and s0["allowed_group"] == "", "update setzt Freigabe")
check(s0["allow_network_users"] is False, "update setzt Stufe alle zurueck")
upd(me, sid, {"api_key": ""})
check(me._mcp_servers[0]["api_key"] == "", "ausdrueckliches '' entfernt den Schluessel")

# ── 6. main.py / mcp_client.py: Schluessel verlaesst das Backend nie ────────
print("\n6. Antworten ohne Schluessel")
for ep in ("add_mcp_server", "update_mcp_server"):
    f = _funktion(MAIN_SRC, ep)
    rueck = [n for n in ast.walk(f) if isinstance(n, ast.Return)]
    json_rueck = [r for r in rueck if isinstance(r.value, ast.Call)
                  and getattr(r.value.func, "id", "") == "JSONResponse"
                  and r.value.args and isinstance(r.value.args[0], ast.Name)]
    check(not json_rueck, f"{ep}: kein Server-Eintrag roh als Antwort")
    gefiltert = [r for r in rueck if isinstance(r.value, ast.Call) and r.value.args
                 and isinstance(r.value.args[0], ast.Call)
                 and getattr(r.value.args[0].func, "id", "") == "ohne_geheimnisse"]
    check(len(gefiltert) == 1, f"{ep}: Antwort geht durch ohne_geheimnisse")
    pruef = [c for c in ast.walk(f) if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") == "header_name_gueltig"]
    check(bool(pruef), f"{ep}: Header-Name wird geprueft")

_zs = {"mcp_rechte": R}
exec(compile(ast.Module(body=[_funktion(MCP_SRC, "_zugang_status")], type_ignores=[]),
             "mcp", "exec"), _zs)
z = _zs["_zugang_status"]({"api_key": "GEHEIMWERT", "url": "https://h", "allowed_users": "a"})
check("GEHEIMWERT" not in repr(z), "Status enthaelt den Schluessel nicht")
check(z["api_key_gesetzt"] is True and z["freigabe"] == "auswahl", "Status: gesetzt + Stufe")
# Beide Status-Zweige (verbunden / nicht verbunden) benutzen ihn.
_status_aufrufe = [c for c in ast.walk(ast.parse(MCP_SRC)) if isinstance(c, ast.Call)
                   and getattr(c.func, "id", "") == "_zugang_status"]
check(len(_status_aufrufe) == 2, f"_zugang_status in BEIDEN Status-Zweigen ({len(_status_aufrufe)})")

# ── 7. Beide HTTP-Transporte schicken den Schluessel ───────────────────────
print("\n7. Transporte")
for meth, client in (("_connect_streamable_http", "streamablehttp_client"),
                     ("_connect_sse", "sse_client")):
    f = _funktion(MCP_SRC, meth, klasse="McpServerConnection")
    aufrufe = [c for c in ast.walk(f) if isinstance(c, ast.Call)
               and getattr(c.func, "id", "") == client]
    kw = [k for c in aufrufe for k in c.keywords if k.arg == "headers"]
    check(len(aufrufe) == 1 and len(kw) == 1
          and isinstance(kw[0].value, ast.Call)
          and getattr(kw[0].value.func, "attr", "") == "_auth_headers",
          f"{meth}: headers=self._auth_headers()")

print(f"\n{'=' * 60}\n{_ok} OK, {_fail} FAIL\n{'=' * 60}")
sys.exit(1 if _fail else 0)
