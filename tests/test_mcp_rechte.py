#!/usr/bin/env python3
"""Waechter: MCP-Freigabe je Benutzer/Gruppe und API-Schluessel (2026-10-25).

Was festgehalten wird:

1. ``mcp_rechte.darf_benutzen`` – Benutzer UND Gruppen ODER-verknuepft,
   leer = niemand (auch kein Admin), kein "alle" mehr, fail-closed.
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
for wert in (True, "ja", 1, "true", None, False):
    check(D({"allow_network_users": wert}, "a") is False,
          f"Altschalter allow_network_users={wert!r} gibt nichts frei")
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

# ── 1b. Altschalter wird beim Start gemeldet, nicht still ──────────────────
print("\n1b. altschalter_ohne_freigabe")
_alt = R.altschalter_ohne_freigabe([
    {"name": "a", "allow_network_users": True},
    {"name": "b", "allow_network_users": True, "allowed_users": "x"},
    {"name": "c"}, {"name": "d", "allow_network_users": "ja"}, "kaputt"])
check(_alt == ["a"], f"nur 'Altschalter UND leer' wird gemeldet ({_alt})")
_ca = ast.unparse(_funktion((ROOT / "backend" / "mcp_client.py").read_text(encoding="utf-8"),
                            "connect_all", klasse="McpClientManager"))
# connect_all WIRKLICH ausfuehren und die Ausgabe abfangen – "der Aufruf
# kommt vor" waere ein Vorkommen, keine Wirkung (Register; die Gegenprobe
# `if False:` blieb damit stumm).
import asyncio as _aio  # noqa: E402
import contextlib as _ctx  # noqa: E402
import io as _io  # noqa: E402
_cafn = _funktion((ROOT / "backend" / "mcp_client.py").read_text(encoding="utf-8"),
                  "connect_all", klasse="McpClientManager")


class _CfgA:
    def get_mcp_servers(self):
        return [{"id": "1", "name": "altserver", "allow_network_users": True, "enabled": False}]


_cans = {"config": _CfgA(), "mcp_rechte": R}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
    name="_M", bases=[], keywords=[], decorator_list=[], type_params=[], body=[_cafn])],
    type_ignores=[])), "mcp", "exec"), _cans)
_puf = _io.StringIO()
with _ctx.redirect_stdout(_puf):
    _aio.run(_cans["_M"]().connect_all())
check("altserver" in _puf.getvalue() and "NIEMAND" in _puf.getvalue(),
      "connect_all meldet den Altschalter beim Start im Journal (ausgefuehrt)")

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
                               "allow_network_users": True})
check(n.get("allowed_users") == "a, b", "Benutzer: getrimmt, leere weg")
check(n.get("allowed_group") == f"{G1}\n{G2}", "Gruppen: zeilengetrennt, leere weg")
check("allow_network_users" not in n, "Altschalter wird nicht uebernommen")
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
check("allow_network_users" not in srv, "add: Altschalter wird nicht geschrieben")
check(srv["api_key"] == "k1" and srv["api_key_header"] == "X-API-Key",
      "add: Schluessel + Header gespeichert")
check(srv["allowed_users"] == "a, b" and srv["allowed_group"] == G1,
      "add: Benutzer + Gruppen gespeichert")
srv2 = add(me, {"name": "u"})
check(srv2.get("allowed_users") == "" and srv2.get("allowed_group") == ""
      and srv2.get("api_key") == "",
      "add ohne Angaben: leer (= nur Administratoren)")
sid = srv["id"]
me._mcp_servers[0]["allow_network_users"] = True   # Altbestand nachstellen
upd(me, sid, {"url": "https://h2/mcp"})
check(me._mcp_servers[0]["api_key"] == "k1", "update OHNE api_key laesst ihn stehen")
check(me._mcp_servers[0]["allowed_users"] == "a, b", "update ohne Freigabe laesst sie stehen")
upd(me, sid, {"api_key": "k2", "allowed_users": "c", "allowed_group": "",
              })
s0 = me._mcp_servers[0]
check(s0["api_key"] == "k2", "update setzt neuen Schluessel")
check(s0["allowed_users"] == "c" and s0["allowed_group"] == "", "update setzt Freigabe")
check("allow_network_users" not in s0, "update raeumt den Altschalter ab")
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
    check(len(gefiltert) >= 1, f"{ep}: Antwort geht durch ohne_geheimnisse")
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

# ── 8. Angebot an das Modell = was der Dispatch zulaesst (DEV 2026-10-25) ──
print("\n8. _gesperrte_weg / _mcp_prompt_block (agent.py)")
AGENT_SRC = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
_ans = {"_MCP_TOOL_PREFIX": "mcp_"}
_teile = [_funktion(AGENT_SRC, "_ist_mcp_tool"), _funktion(AGENT_SRC, "_mcp_freigegeben")]
exec(compile(ast.Module(body=_teile, type_ignores=[]), "agent", "exec"), _ans)
_klasse = ast.ClassDef(name="_A", bases=[], keywords=[], decorator_list=[], type_params=[],
                       body=[_funktion(AGENT_SRC, "_gesperrte_weg", klasse="JarvisAgent"),
                             _funktion(AGENT_SRC, "_mcp_prompt_block", klasse="JarvisAgent")])
exec(compile(ast.fix_missing_locations(ast.Module(body=[_klasse], type_ignores=[])),
             "agent", "exec"), _ans)


class _W:
    def __init__(self, name, mcp=False, frei=True, server=""):
        self.name = name
        if mcp:
            self.ist_mcp = True
            self._server_name = server
            self.erlaubt_fuer = lambda b: frei


class _Ag(_ans["_A"]):
    def __init__(self, priv, sap=None, vemas=None, tools=()):
        self._priv = priv
        if sap is not None:
            self._current_user_sap = sap
        if vemas is not None:
            self._current_user_vemas = vemas
        self._tool_instances = list(tools)

    def _actor_is_privileged(self):
        return self._priv

    def actor_name(self):
        return "m.muster"


W = [_W("sap_query"), _W("vemas_resources"), _W("vemas_discover"), _W("shell_execute"),
     _W("mcp_theben_list_befunde", True, True, "theben"),
     _W("mcp_geheim_x", True, False, "geheim")]
namen = lambda ag: [t.name for t in ag._gesperrte_weg(W)]
check([x for x in namen(_Ag(True)) if not x.startswith("mcp_")]
      == [t.name for t in W if not t.name.startswith("mcp_")],
      "ohne Laufwerte (Vorgabe True): SAP/VEMAS bleiben")
n = namen(_Ag(True, sap=False, vemas=False))
check("vemas_resources" not in n and "vemas_discover" not in n,
      "keine VEMAS-Freigabe: vemas_* wird NICHT angeboten (der gemeldete Fall)")
check("sap_query" not in n, "keine SAP-Freigabe: sap_* wird nicht angeboten")
check("shell_execute" in n and "mcp_geheim_x" not in n,
      "auch PRIVILEGIERT: nicht freigegebener MCP-Server faellt weg (kein Admin-Bypass)")
n = namen(_Ag(False, sap=True, vemas=True))
check("mcp_geheim_x" not in n and "mcp_theben_list_befunde" in n,
      "unprivilegiert: nur freigegebene MCP-Server")
check(namen(_Ag(True, sap=True, vemas=True)) == [t.name for t in W if t.name != "mcp_geheim_x"],
      "mit Freigaben: alles Erlaubte bleibt, Reihenfolge unveraendert (Prompt-Cache)")

_llm = ast.unparse(_funktion(AGENT_SRC, "_llm_tools", klasse="JarvisAgent"))
check("self._gesperrte_weg(self._tool_instances)" in _llm,
      "_llm_tools filtert VOR der Rollen-Whitelist (gilt auch fuer Rollen)")
_bloecke = [c for c in ast.walk(ast.parse(AGENT_SRC)) if isinstance(c, ast.Call)
            and getattr(c.func, "attr", "") == "_mcp_prompt_block"]
check(len(_bloecke) == 2, f"MCP-Block in BEIDEN Prompt-Wegen (Chat + headless): {len(_bloecke)}")

import types  # noqa: E402
_fake = types.ModuleType("backend.mcp_client")


class _Mgr:
    def get_status(self):
        return [{"name": "theben", "enabled": True, "connected": True},
                {"name": "kaputt", "enabled": True, "connected": False,
                 "error": "TLS-Pruefung: certificate is not valid for '192.0.2.8'",
                 "allowed_users": "m.muster"},
                {"name": "fremd", "enabled": True, "connected": False,
                 "error": "401 Unauthorized", "allowed_users": "jemand.anders"},
                {"name": "aus", "enabled": False, "connected": False,
                 "allowed_users": "m.muster"}]


_fake.mcp_manager = _Mgr()
_alt = sys.modules.get("backend.mcp_client")
sys.modules["backend.mcp_client"] = _fake
try:
    blk = _Ag(False, tools=W)._mcp_prompt_block()
finally:
    if _alt is None:
        sys.modules.pop("backend.mcp_client", None)
    else:
        sys.modules["backend.mcp_client"] = _alt
check("'theben': mcp_theben_list_befunde" in blk, "Block nennt Server -> Werkzeug")
check("mcp_geheim_x" not in blk,
      "Werkzeug eines nicht freigegebenen Servers erscheint NICHT")
check("NICHT freigegeben" in blk and "• 'geheim'" in blk and "Berechtigungen" in blk,
      "nicht freigegebener Server: Name + Weg zur Freigabe")
check("• 'kaputt'" in blk, "freigegebener, nicht verbundener Server wird genannt")
check("192.0.2.8" not in blk and "certificate" not in blk and "401" not in blk,
      "KEIN Fehlertext im Prompt (interne Adressen; wechselt je Versuch)")
check("'fremd'" not in blk, "nicht verbundener Server OHNE Freigabe wird nicht genannt")
check("'aus'" not in blk, "abgeschalteter Server wird nicht genannt")
check("VEMAS" in blk and "KEINE" in blk, "Block grenzt Fachsysteme ausdruecklich ab")

# Position: hinter dem Gedaechtnis, vor der Benutzer-Anweisung (Prompt-Cache).
_rt = AGENT_SRC[AGENT_SRC.find("async def run_task"):]
_p_mem = _rt.find("system_prompt += gedaechtnis_block(memory_context)")
_p_mcp = _rt.find("system_prompt += self._mcp_prompt_block()")
_p_pre = _rt.find("system_prompt += _pre_block")
check(-1 not in (_p_mem, _p_mcp, _p_pre) and _p_mem < _p_mcp < _p_pre,
      "Chat: MCP-Block nach dem Gedaechtnis, vor der Benutzer-Anweisung")
_basis = AGENT_SRC.find("system_prompt = _mit_plotstyle(self._base_system_prompt())\n")
check(_basis != -1 and not AGENT_SRC[_basis:_basis + 200].count("_mcp_prompt_block"),
      "headless: Block nicht mehr direkt hinter dem Basisprompt")

# ── 8b. PUT nur mit Freigabe verbindet NICHT neu ───────────────────────────
print("\n8b. Freigabe-PUT ohne Neuaufbau")
_u = _funktion(MAIN_SRC, "update_mcp_server")
_u_src = ast.unparse(_u)
check("set(data) <= MCP_NUR_FREIGABE" in _u_src, "Weiche 'nur Freigabe' vorhanden")
check(_u_src.find("MCP_NUR_FREIGABE") < _u_src.find("connect_server"),
      "die Weiche steht VOR connect_server (frueher Ausstieg)")
_nf = [k for k in ast.parse(MAIN_SRC).body if isinstance(k, ast.Assign)
       and any(getattr(t, "id", "") == "MCP_NUR_FREIGABE" for t in k.targets)]
_nfw = {e.value for k in _nf for e in ast.walk(k.value) if isinstance(e, ast.Constant)
        and isinstance(e.value, str)}
check(_nfw == {"allowed_users", "allowed_group"},
      f"nur die Freigabefelder (sonst blieben Adresse/Schluessel ohne Wirkung): {_nfw}")

# ── 9. GET .../konfig gibt keine Geheimnisse heraus ────────────────────────
print("\n9. Konfig-Endpunkt")
_k = _funktion(MAIN_SRC, "mcp_server_konfig")
_dicts = [d for d in ast.walk(_k) if isinstance(d, ast.Dict) and len(d.keys) > 5]
_schl = {k.value for d in _dicts for k in d.keys if isinstance(k, ast.Constant)}
check(bool(_schl), "Antwort-Dict gefunden (Positivkontrolle)")
for verboten in ("api_key", "env", "ca_cert"):
    check(verboten not in _schl, f"Schluessel '{verboten}' NICHT in der Antwort")
check("env_namen" in _schl and "api_key_gesetzt" in _schl,
      "nur Namen bzw. 'gesetzt'")
_dep = [k for k in ast.walk(_k) if isinstance(k, ast.Call)
        and getattr(k.func, "id", "") == "Depends"
        and any(getattr(a, "id", "") == "require_local_auth" for a in k.args)]
check(len(_dep) == 1, "nur fuer Administratoren (require_local_auth)")

if "backend.config" in sys.modules:
    print("ABBRUCH: backend.config wurde waehrend des Laufs importiert.", file=sys.stderr)
    raise SystemExit(2)

print(f"\n{'=' * 60}\n{_ok} OK, {_fail} FAIL\n{'=' * 60}")
sys.exit(1 if _fail else 0)
