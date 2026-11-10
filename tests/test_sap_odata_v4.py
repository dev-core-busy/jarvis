#!/usr/bin/env python3
"""Waechter: OData-V4-Katalog und V4-Dienste ueber die Kennung ``v4:`` (2026-11-10).

Hintergrund: die Abfrage-Konsole in /sap kannte nur den V2-Katalog
(``iwfnd/catalogservice;v=2``). S/4HANA bietet neuere Dienste (RAP, CDS) nur als
OData V4 an; sie liegen unter ``…/sap/opu/odata4`` NEBEN der konfigurierten
Basis ``…/sap/opu/odata``. Statt eine zweite Basis-URL einzufuehren, traegt der
Service-Pfad die Wurzel als Kennung (``v4:<pfad>``) – Host, Port, Anmeldung und
verankertes Zertifikat bleiben dieselben.

Geprueft gegen einen ECHTEN lokalen HTTP-Server (keine requests-Attrappe):

  1. V4-Wurzel: abgeleitet aus …/odata (mit und ohne Schraegstrich), leer bei
     anderer Basis – und dann laesst eine v4:-Kennung keine Anfrage los
  2. Katalog: Services unter DefaultSystem (mit $expand), absolute UND relative
     ServiceUrl, fremder Host wird nicht uebernommen, ausserhalb der Wurzel und
     ohne Adresse ausgelassen, Folgeseiten nur unter der Wurzel, $format nicht
     doppelt, Obergrenze → "nicht genau"
  3. Eine gelistete Kennung erreicht $metadata und Daten des V4-Dienstes, mit
     Anmeldung, auf demselben Host
  4. Endpunkt /api/sap/odata/services fragt beide Kataloge, V4 erst NACH der
     401-Schranke (AST)
  5. Werkzeug sap_odata_services: nach 401 von V2 kein zweiter Logon (AST)
  6. Eine vollstaendige Adresse im Service-Feld laesst KEINE Anfrage los –
     vorher ging die Anmeldung damit an jeden beliebigen Host (auch http)

Exit 2 "konnte nicht laufen", 1 "Pruefung fehlgeschlagen", 0 bestanden.

    python3 tests/test_sap_odata_v4.py [--modul <sap_client.py>] [--main <main.py>] [--skill <main.py>]
"""
import argparse
import ast
import base64
import http.server
import importlib.util
import json
import socket
import sys
import threading
import types
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n{t}")


# backend.config nur als Attrappe – der echte Import schreibt die Live-settings.json.
_cfg_mod = types.ModuleType("backend.config")
_cfg_mod.config = types.SimpleNamespace(get_skill_states=lambda: {})
sys.modules["backend.config"] = _cfg_mod

_ap = argparse.ArgumentParser()
_ap.add_argument("--modul", default=str(ROOT / "backend" / "sap_client.py"))
_ap.add_argument("--main", default=str(ROOT / "backend" / "main.py"))
_ap.add_argument("--skill", default=str(ROOT / "skills" / "sap" / "main.py"))
ARGS = _ap.parse_args()

try:
    import requests  # noqa: F401
    import backend  # noqa: F401
    _spec = importlib.util.spec_from_file_location("backend.sap_client", ARGS.modul)
    sc = importlib.util.module_from_spec(_spec)
    sys.modules["backend.sap_client"] = sc
    _spec.loader.exec_module(sc)
except Exception as e:  # noqa: BLE001
    print(f"Voraussetzung fehlt ({e}) – Test kann nicht laufen.")
    sys.exit(2)

BENUTZER, KENNWORT = "pruefer", "Kw-geheim-4711"
V4_WURZEL = "/sap/opu/odata4"
KATALOG = V4_WURZEL + "/iwfnd/config/default/iwfnd/catalog/0002/ServiceGroups"

# Seite 1 – so, wie das Gateway die Gruppen liefert: Services unter
# DefaultSystem, mal absolute, mal relative Adresse, ein INTERNER Hostname,
# ein Pfad ausserhalb der Wurzel (V2-Basis) und ein Eintrag ohne Adresse.
SEITE1 = {"value": [
    {"GroupId": "ZGRP_A", "Description": "Gruppe A", "DefaultSystem": {"Services": [
        {"ServiceId": "ZSVC_A", "ServiceVersion": "0001", "Description": "Dienst A",
         "ServiceUrl": V4_WURZEL + "/sap/zgrp_a/srvd_a2x/sap/zsvc_a/0001/"},
        {"ServiceId": "ZSVC_INTERN", "ServiceVersion": "0001", "Description": "Intern",
         "ServiceUrl": "https://intern-gw.beispiel.de:8443" + V4_WURZEL + "/sap/zgrp_a/srvd/sap/zsvc_intern/0001/"},
    ]}},
    {"GroupId": "ZGRP_B", "Description": "Gruppe B", "DefaultSystem": {"Services": [
        # relativ zur Katalogadresse …/catalog/0002/ – sieben Ebenen hoch = Wurzel
        {"ServiceId": "ZSVC_REL", "ServiceVersion": "0002", "Description": "",
         "ServiceUrl": "../../../../../../sap/zgrp_b/srvd_a2x/sap/zsvc_rel/0002/"},
        {"ServiceId": "ZSVC_DRAUSSEN", "ServiceVersion": "0001", "Description": "V2-Ort",
         "ServiceUrl": "/sap/opu/odata/sap/ZSVC_DRAUSSEN/"},
        {"ServiceId": "ZSVC_LEER", "ServiceVersion": "0001", "Description": "ohne Adresse"},
    ]}},
], "@odata.nextLink": "ServiceGroups?$expand=DefaultSystem($expand=Services)&$skiptoken=2&$format=json"}

SEITE2 = {"value": [
    {"GroupId": "ZGRP_C", "Description": "Gruppe C", "DefaultSystem": {"Services": [
        {"ServiceId": "ZSVC_C", "ServiceVersion": "0001", "Description": "Dienst C",
         "ServiceUrl": V4_WURZEL + "/sap/zgrp_c/srvd_a2x/sap/zsvc_c/0001/"},
    ]}},
], "@odata.nextLink": "/sap/opu/odata/fremd/ServiceGroups?$skiptoken=3"}

V4_META = '''<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
 <edmx:DataServices>
  <Schema Namespace="com.sap.gateway.srvd_a2x.zsvc_a.v0001" xmlns="http://docs.oasis-open.org/odata/ns/edm">
   <EntityType Name="AuftragType"><Key><PropertyRef Name="Auftrag"/></Key>
    <Property Name="Auftrag" Type="Edm.String"/></EntityType>
   <EntityContainer Name="Container">
    <EntitySet Name="Auftrag" EntityType="com.sap.gateway.srvd_a2x.zsvc_a.v0001.AuftragType"/>
   </EntityContainer>
  </Schema>
 </edmx:DataServices>
</edmx:Edmx>'''

ZUSTAND = {"anfragen": [], "katalog_zeilen": None}


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401 – Testserver schweigt
        pass

    def _json(self, code, obj):
        roh = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_GET(self):  # noqa: N802
        teile = urlsplit(self.path)
        params = parse_qsl(teile.query, keep_blank_values=True)
        ZUSTAND["anfragen"].append({"pfad": teile.path, "params": params,
                                    "auth": self.headers.get("Authorization") or ""})
        erwartet = "Basic " + base64.b64encode(f"{BENUTZER}:{KENNWORT}".encode()).decode()
        if self.headers.get("Authorization") != erwartet:
            return self._json(401, {"error": {"message": {"value": "Anmeldung fehlt"}}})
        if teile.path == KATALOG:
            p = dict(params)
            if ZUSTAND["katalog_zeilen"]:
                return self._json(200, {"value": [{"GroupId": "G", "DefaultSystem": {"Services": [
                    {"ServiceId": "S%d" % i, "ServiceUrl": V4_WURZEL + "/sap/g/srvd/sap/s%d/0001/" % i}
                    for i in range(ZUSTAND["katalog_zeilen"])]}}]})
            return self._json(200, SEITE2 if p.get("$skiptoken") == "2" else SEITE1)
        if teile.path == V4_WURZEL + "/sap/zgrp_a/srvd_a2x/sap/zsvc_a/0001/$metadata":
            roh = V4_META.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(roh)))
            self.end_headers()
            return self.wfile.write(roh)
        if teile.path == V4_WURZEL + "/sap/zgrp_a/srvd_a2x/sap/zsvc_a/0001/Auftrag":
            return self._json(200, {"@odata.context": "$metadata#Auftrag",
                                    "value": [{"Auftrag": "4711"}, {"Auftrag": "4712"}]})
        return self._json(404, {"error": {"message": {"value": "unbekannt: " + teile.path}}})


def _freier_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _freier_port()
_srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
BASIS = f"http://127.0.0.1:{PORT}/sap/opu/odata"


def client(**cfg):
    c = {"connection_type": "odata", "odata_base_url": BASIS, "auth_kind": "basic",
         "username": BENUTZER, "password": KENNWORT}
    c.update(cfg)
    return sc.SapClient(c)


# Positivkontrolle: der Testserver antwortet und prueft die Anmeldung wirklich.
try:
    import requests as _rq
    _a = _rq.get(f"http://127.0.0.1:{PORT}{KATALOG}", timeout=5)
    _b = _rq.get(f"http://127.0.0.1:{PORT}{KATALOG}", auth=(BENUTZER, KENNWORT), timeout=5)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Testserver nicht erreichbar ({e}).")
    sys.exit(2)
if _a.status_code != 401 or _b.status_code != 200 or not _b.json().get("value"):
    print(f"ABBRUCH: Testserver verhaelt sich nicht wie erwartet ({_a.status_code}/{_b.status_code}).")
    sys.exit(2)

# ══ 1. V4-Wurzel ════════════════════════════════════════════════════
section("1. V4-Wurzel aus der Basis-URL")
check(client().odata.v4_base == f"http://127.0.0.1:{PORT}/sap/opu/odata4", "…/odata → …/odata4",
      client().odata.v4_base)
check(client(odata_base_url=BASIS + "/").odata.v4_base == f"http://127.0.0.1:{PORT}/sap/opu/odata4",
      "…/odata/ (mit Schraegstrich) → …/odata4")
anders = client(odata_base_url=f"http://127.0.0.1:{PORT}/proxy/sap")
check(anders.odata.v4_base == "", "andere Basis: keine geratene V4-Wurzel", repr(anders.odata.v4_base))
ZUSTAND["anfragen"] = []
try:
    anders.odata.catalog_v4_service_pfade()
    fehler = None
except sc.SapError as e:
    fehler = e
check(fehler is not None and ZUSTAND["anfragen"] == [],
      "andere Basis: Katalog meldet den Grund, ohne eine Anfrage zu senden", repr((fehler, ZUSTAND["anfragen"])))
try:
    anders.odata.entity_sets("v4:sap/x/srvd/sap/y/0001")
    fehler = None
except sc.SapError as e:
    fehler = e
check(fehler is not None and ZUSTAND["anfragen"] == [],
      "andere Basis: v4:-Kennung laesst keine Anfrage los", repr((fehler, ZUSTAND["anfragen"])))

# ══ 2. Katalog ══════════════════════════════════════════════════════
section("2. V4-Katalog")
ZUSTAND.update({"anfragen": [], "katalog_zeilen": None})
try:
    r = client().odata.catalog_v4_service_pfade()
except sc.SapError as e:
    r = {"services": [], "fehler": str(e)}
namen = [x["service"] for x in r.get("services", [])]
check(namen == ["v4:sap/zgrp_a/srvd/sap/zsvc_intern/0001", "v4:sap/zgrp_a/srvd_a2x/sap/zsvc_a/0001",
                "v4:sap/zgrp_b/srvd_a2x/sap/zsvc_rel/0002", "v4:sap/zgrp_c/srvd_a2x/sap/zsvc_c/0001"],
      "Kennungen relativ zur V4-Wurzel, sortiert, beide Seiten", repr(r))
check(r.get("ausgelassen") == 2, "ausserhalb der Wurzel und ohne Adresse: 2 ausgelassen", repr(r.get("ausgelassen")))
check(all("://" not in n and "intern-gw" not in n for n in namen), "kein Host aus den Katalogdaten", repr(namen))
titel = {x["service"]: x for x in r.get("services", [])}
check(titel.get("v4:sap/zgrp_a/srvd_a2x/sap/zsvc_a/0001", {}).get("title") == "Dienst A"
      and titel.get("v4:sap/zgrp_a/srvd_a2x/sap/zsvc_a/0001", {}).get("version") == "0001",
      "Titel und Version aus dem Service", repr(titel))
check(titel.get("v4:sap/zgrp_b/srvd_a2x/sap/zsvc_rel/0002", {}).get("title") == "Gruppe B",
      "ohne Beschreibung: Titel der Gruppe", repr(titel))
kat = [a for a in ZUSTAND["anfragen"] if a["pfad"] == KATALOG]
check(len(kat) == 2, "genau zwei Katalogseiten gefragt (die fremde Folgeseite nicht)",
      repr([(a["pfad"], a["params"]) for a in ZUSTAND["anfragen"]]))
check(bool(kat) and ("$expand", "DefaultSystem($expand=Services)") in kat[0]["params"],
      "erste Seite mit $expand der Services", repr(kat[:1]))
check(len(kat) == 2 and [k for k, _ in kat[1]["params"]].count("$format") == 1
      and ("$skiptoken", "2") in kat[1]["params"],
      "Folgeseite: $skiptoken uebernommen, $format nicht doppelt", repr(kat[1:]))
check(not any(a["pfad"].startswith("/sap/opu/odata/") for a in ZUSTAND["anfragen"]),
      "Folgeseite ausserhalb der Wurzel wird nicht verfolgt")
check(r.get("genau") is True, "unter der Obergrenze: genau")

ZUSTAND.update({"anfragen": [], "katalog_zeilen": 7})
r = client().odata.catalog_v4_service_pfade(limit=5)
check(len(r.get("services", [])) == 5 and r.get("genau") is False,
      "an der Obergrenze: gekappt und NICHT genau", repr((len(r.get("services", [])), r.get("genau"))))
ZUSTAND["katalog_zeilen"] = None

# ══ 3. Kennung erreicht den V4-Dienst ═══════════════════════════════
section("3. v4:-Kennung erreicht $metadata und Daten")
ZUSTAND["anfragen"] = []
c = client()
try:
    sets = c.odata.entity_sets("v4:sap/zgrp_a/srvd_a2x/sap/zsvc_a/0001")
    zeilen = c.odata.query("Auftrag", "v4:sap/zgrp_a/srvd_a2x/sap/zsvc_a/0001", top=10)
    fehler = None
except sc.SapError as e:
    sets, zeilen, fehler = [], [], e
check(fehler is None and sets == ["Auftrag"], "EntitySets aus dem V4-$metadata", repr((fehler, sets)))
check([z.get("Auftrag") for z in zeilen] == ["4711", "4712"], "Zeilen aus der V4-Antwort (value)", repr(zeilen))
pfade = [a["pfad"] for a in ZUSTAND["anfragen"]]
check(pfade == [V4_WURZEL + "/sap/zgrp_a/srvd_a2x/sap/zsvc_a/0001/$metadata",
                V4_WURZEL + "/sap/zgrp_a/srvd_a2x/sap/zsvc_a/0001/Auftrag"],
      "Anfragen gehen an die V4-Wurzel desselben Hosts", repr(pfade))
check(all(a["auth"].startswith("Basic ") for a in ZUSTAND["anfragen"]), "Anmeldung geht mit")
# Rueckwirkung: V2-Kennungen unveraendert unter der Basis
ZUSTAND["anfragen"] = []
try:
    c.odata.entity_sets("sap/ZB_SRV")
except sc.SapError:
    pass
check([a["pfad"] for a in ZUSTAND["anfragen"]] == ["/sap/opu/odata/sap/ZB_SRV/$metadata"],
      "V2-Pfad bleibt unter der Basis", repr([a["pfad"] for a in ZUSTAND["anfragen"]]))

# ══ 4. Endpunkt (AST) ═══════════════════════════════════════════════
section("4. Endpunkt /api/sap/odata/services")
try:
    baum = ast.parse(Path(ARGS.main).read_text(encoding="utf-8"))
    skill_baum = ast.parse(Path(ARGS.skill).read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Quelltext nicht lesbar ({e}).")
    sys.exit(2)
fn = next((n for n in ast.walk(baum) if isinstance(n, ast.AsyncFunctionDef)
           and n.name == "sap_odata_services_api"), None)
if fn is None:
    print("ABBRUCH: sap_odata_services_api nicht gefunden – Test kann nicht laufen.")
    sys.exit(2)


def _attr_zeilen(baum_, name):
    return [n.lineno for n in ast.walk(baum_) if isinstance(n, ast.Attribute) and n.attr == name]


def _schranke_401(baum_):
    """Zeilen der if-Zweige, die auf 401 pruefen UND zurueckkehren."""
    zeilen = []
    for n in ast.walk(baum_):
        if isinstance(n, ast.If) and any(isinstance(k, ast.Constant) and k.value == 401
                                         for k in ast.walk(n.test)) \
                and any(isinstance(b, ast.Return) for b in n.body):
            zeilen.append(n.lineno)
    return zeilen


v2z, v4z, s401 = _attr_zeilen(fn, "catalog_service_pfade"), _attr_zeilen(fn, "catalog_v4_service_pfade"), _schranke_401(fn)
check(len(v2z) == 1 and len(v4z) == 1, "Endpunkt fragt V2- und V4-Katalog je einmal", repr((v2z, v4z)))
check(bool(s401) and bool(v2z) and bool(v4z) and v2z[0] < s401[0] < v4z[0],
      "V4 erst NACH der 401-Schranke (kein zweiter abgelehnter Logon)", repr((v2z, s401, v4z)))

# ══ 5. Werkzeug (AST) ═══════════════════════════════════════════════
section("5. Werkzeug sap_odata_services")
klasse = None
for n in ast.walk(skill_baum):
    if isinstance(n, ast.ClassDef):
        for f in n.body:
            if (isinstance(f, ast.FunctionDef) and f.name == "name"
                    and any(isinstance(k, ast.Constant) and k.value == "sap_odata_services" for k in ast.walk(f))):
                klasse = n
if klasse is None:
    print("ABBRUCH: Werkzeug sap_odata_services nicht gefunden – Test kann nicht laufen.")
    sys.exit(2)
run = next((f for f in klasse.body if isinstance(f, ast.AsyncFunctionDef) and f.name == "_run"), None)
v2z = _attr_zeilen(run, "catalog_services") if run else []
v4z = _attr_zeilen(run, "catalog_v4_service_pfade") if run else []
s401 = _schranke_401(run) if run else []
check(len(v4z) == 1, "Werkzeug fragt den V4-Katalog", repr(v4z))
check(bool(s401) and bool(v2z) and bool(v4z) and v2z[0] < s401[0] < v4z[0],
      "Werkzeug: V4 erst NACH der 401-Schranke", repr((v2z, s401, v4z)))

# ══ 6. Keine fremde Adresse als Service ═════════════════════════════
section("6. Vollstaendige Adresse im Service-Feld")
# Positivkontrolle: ein zweiter Server auf dieser Maschine, der JEDE Anfrage
# samt Kopfzeilen mitschreibt – kommt dort etwas an, ist die Anmeldung geleckt.
FREMD = []


class _Fremd(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        FREMD.append({"pfad": self.path, "auth": self.headers.get("Authorization") or ""})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"d":{"results":[]}}')


FPORT = _freier_port()
_fsrv = http.server.ThreadingHTTPServer(("127.0.0.1", FPORT), _Fremd)
threading.Thread(target=_fsrv.serve_forever, daemon=True).start()
try:
    _rq.get(f"http://127.0.0.1:{FPORT}/probe", timeout=5)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: zweiter Testserver nicht erreichbar ({e}).")
    sys.exit(2)
if len(FREMD) != 1:
    print("ABBRUCH: der fremde Server schreibt Anfragen nicht mit – Messaufbau unbrauchbar.")
    sys.exit(2)
FREMD.clear()
fremd = f"http://127.0.0.1:{FPORT}/sap/opu/odata/sap/ZFREMD_SRV"
c = client()
for beschreibung, aufruf in (
        ("entity_sets", lambda: c.odata.entity_sets(fremd)),
        ("query", lambda: c.odata.query("Set", fremd)),
        ("get", lambda: c.odata.get(fremd + "/Set")),
        ("HTTPS-Schreibweise", lambda: c.odata.entity_sets(fremd.replace("http://", "HTTPS://"))),
):
    ZUSTAND["anfragen"] = []
    try:
        aufruf()
        fehler = None
    except sc.SapError as e:
        fehler = e
    check(fehler is not None and fehler.status == 0 and not FREMD and not ZUSTAND["anfragen"],
          f"{beschreibung}: fremde Adresse abgelehnt, keine Anfrage an irgendwen",
          repr((fehler, FREMD, ZUSTAND["anfragen"])))
check(fehler is not None and "Basis-URL" in str(fehler), "Ablehnungsgrund nennt den erlaubten Weg", repr(fehler))
_fsrv.shutdown()

_srv.shutdown()
print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
