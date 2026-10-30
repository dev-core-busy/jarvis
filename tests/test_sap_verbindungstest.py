#!/usr/bin/env python3
"""Waechter: Bericht des SAP-Verbindungstests (``SapClient.test``).

Hintergrund (2026-10-30): der Test meldete nur "Katalog erreichbar (1+
Services)" bzw. "22 EntitySet(s) im Service" – der SAP-Administrator konnte
daraus weder ablesen, WAS geprueft wurde, noch gegen welche Adresse, mit
welchem Benutzer und Mandanten. "1+" war zudem keine Zaehlung (``$top=1``).

Geprueft wird gegen einen ECHTEN lokalen HTTP-Server, der den Gateway
nachbildet – keine ``requests``-Attrappe, denn genau die echte Anfrage
(Adresse samt Parametern, Kopfzeilen, Statuscode) ist hier die Zusage:

  1. Standard-Service: $metadata, EntitySet-Namen, Adresse, Status, Mandant
  2. Katalog: ECHTE Zahl ueber $inlinecount, Rueckfall durch Listen
     (genau / "mindestens"), 400 auf $inlinecount, 404 = kein Katalog
  3. Fehlerfall: der Bericht steht trotz Ausnahme (Status, Adresse, Variante)
  4. Kein Kennwort, kein Token, keine Anmeldung aus der Adresse im Bericht
  5. Bearer-Token geht auch beim $metadata-Abruf mit (vorher fehlte er dort)
  6. Endpunkt ``/api/sap/test`` reicht den Bericht in BEIDEN Zweigen durch (AST)
  7. Abfrage-Konsole: Katalog als Service-Pfade RELATIV zur Basis-URL – ein
     fremder Host aus den Katalogdaten wird nie uebernommen
  8. Endpunkte der Konsole: Service-Liste, EntitySets ohne Service (AST)
  9. EntitySets: nicht direkt abrufbare Sets (sap:addressable="false") und der
     Navigationsweg dorthin – V2 ueber AssociationSet, V4 ueber
     NavigationPropertyBinding
 10. Mitladen ($expand): Zeilen fuer die Tabelle bereinigt (nicht geladene
     Navigationen weg, mitgeladene Listen geglaettet), Spalten ueber alle Zeilen

Exit 2 heisst "konnte nicht laufen", 1 "Pruefung fehlgeschlagen", 0 bestanden.

    python3 tests/test_sap_verbindungstest.py [--modul <sap_client.py>] [--main <main.py>]

Die Pfad-Argumente sind fuer die Gegenprobe (gegen_sap_verbindungstest.py): sie
legt sabotierte KOPIEN vor, die echten Dateien werden nie angefasst.
"""
import argparse
import ast
import importlib.util
import http.server
import json
import socket
import sys
import threading
import types
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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


# backend.config nur als Attrappe – der echte Import schreibt die Live-
# settings.json zurueck. sap_client braucht ihn nur ohne uebergebene cfg.
_cfg_mod = types.ModuleType("backend.config")
_cfg_mod.config = types.SimpleNamespace(get_skill_states=lambda: {})
sys.modules["backend.config"] = _cfg_mod

_ap = argparse.ArgumentParser()
_ap.add_argument("--modul", default=str(ROOT / "backend" / "sap_client.py"))
_ap.add_argument("--main", default=str(ROOT / "backend" / "main.py"))
ARGS = _ap.parse_args()

try:
    import requests  # noqa: F401
    import backend  # noqa: F401 – Paket fuer den Modulnamen backend.sap_client
    _spec = importlib.util.spec_from_file_location("backend.sap_client", ARGS.modul)
    sc = importlib.util.module_from_spec(_spec)
    sys.modules["backend.sap_client"] = sc
    _spec.loader.exec_module(sc)
except Exception as e:  # noqa: BLE001
    print(f"Voraussetzung fehlt ({e}) – Test kann nicht laufen.")
    sys.exit(2)

KENNWORT = "Kw-geheim-4711"
TOKEN = "Tok-geheim-0815"
SETS = ["Bestellungen", "Kunden", "Kunden", "Artikel"]   # doppelt: wird einmal gezaehlt
# Katalog wie ein echter Gateway ihn liefert: absolute Adressen mit INTERNEM
# Hostnamen, Versionen als ;v=, Gross-/Kleinschreibung, ein V4-Pfad ausserhalb
# der Basis (Praefix-Falle: /odata4 beginnt mit /odata) und eine leere Adresse.
# V2 nach dem Vorbild von API_SALES_ORDER_SRV: Texte nur ueber Navigation.
# KOEDER: to_TextAlt hat dieselben Rollennamen wie to_Text, aber eine ANDERE
# Relationship – wer nur die Rollen vergleicht, nennt einen falschen Weg.
V2_META = '''<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx"
  xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
  xmlns:sap="http://www.sap.com/Protocols/SAPData">
 <edmx:DataServices m:DataServiceVersion="2.0">
  <Schema Namespace="API_SALES_ORDER_SRV" xmlns="http://schemas.microsoft.com/ado/2008/09/edm">
   <EntityType Name="A_SalesOrderType"><Key><PropertyRef Name="SalesOrder"/></Key>
    <Property Name="SalesOrder" Type="Edm.String"/>
    <NavigationProperty Name="to_Text" Relationship="API_SALES_ORDER_SRV.assoc_Text" FromRole="FromRole_assoc_Text" ToRole="ToRole_assoc_Text"/>
    <NavigationProperty Name="to_TextAlt" Relationship="API_SALES_ORDER_SRV.assoc_Anders" FromRole="FromRole_assoc_Text" ToRole="ToRole_assoc_Text"/>
    <NavigationProperty Name="to_Item" Relationship="API_SALES_ORDER_SRV.assoc_Item" FromRole="FromRole_assoc_Item" ToRole="ToRole_assoc_Item"/>
   </EntityType>
   <EntityType Name="A_SalesOrderItemType"><Key><PropertyRef Name="SalesOrder"/><PropertyRef Name="SalesOrderItem"/></Key>
    <NavigationProperty Name="to_ItemText" Relationship="API_SALES_ORDER_SRV.assoc_ItemText" FromRole="FromRole_assoc_ItemText" ToRole="ToRole_assoc_ItemText"/>
   </EntityType>
   <EntityType Name="A_SalesOrderTextType"><Key><PropertyRef Name="SalesOrder"/><PropertyRef Name="Language"/><PropertyRef Name="LongTextID"/></Key></EntityType>
   <EntityType Name="A_SalesOrderItemTextType"><Key><PropertyRef Name="SalesOrder"/><PropertyRef Name="SalesOrderItem"/></Key></EntityType>
   <EntityContainer Name="API_SALES_ORDER_SRV_Entities" m:IsDefaultEntityContainer="true">
    <EntitySet Name="A_SalesOrder" EntityType="API_SALES_ORDER_SRV.A_SalesOrderType" sap:creatable="false"/>
    <EntitySet Name="A_SalesOrderItem" EntityType="API_SALES_ORDER_SRV.A_SalesOrderItemType" sap:addressable="true"/>
    <EntitySet Name="A_SalesOrderText" EntityType="API_SALES_ORDER_SRV.A_SalesOrderTextType" sap:addressable="false"/>
    <EntitySet Name="A_SalesOrderItemText" EntityType="API_SALES_ORDER_SRV.A_SalesOrderItemTextType" sap:addressable="false"/>
    <AssociationSet Name="assoc_Text" Association="API_SALES_ORDER_SRV.assoc_Text">
     <End EntitySet="A_SalesOrder" Role="FromRole_assoc_Text"/><End EntitySet="A_SalesOrderText" Role="ToRole_assoc_Text"/>
    </AssociationSet>
    <AssociationSet Name="assoc_Item" Association="API_SALES_ORDER_SRV.assoc_Item">
     <End EntitySet="A_SalesOrder" Role="FromRole_assoc_Item"/><End EntitySet="A_SalesOrderItem" Role="ToRole_assoc_Item"/>
    </AssociationSet>
    <AssociationSet Name="assoc_ItemText" Association="API_SALES_ORDER_SRV.assoc_ItemText">
     <End EntitySet="A_SalesOrderItem" Role="FromRole_assoc_ItemText"/><End EntitySet="A_SalesOrderItemText" Role="ToRole_assoc_ItemText"/>
    </AssociationSet>
   </EntityContainer>
  </Schema>
 </edmx:DataServices>
</edmx:Edmx>'''
# V4 (RAP): Namensraum mit Punkten, Target mit Container-Praefix.
V4_META = '''<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
 <edmx:DataServices>
  <Schema Namespace="com.sap.gateway.srvd.zv4.v0001" xmlns="http://docs.oasis-open.org/odata/ns/edm">
   <EntityType Name="KopfType"><Key><PropertyRef Name="Id"/></Key></EntityType>
   <EntityType Name="TextType"><Key><PropertyRef Name="Id"/><PropertyRef Name="Sprache"/></Key></EntityType>
   <EntityContainer Name="Container">
    <EntitySet Name="Kopf" EntityType="com.sap.gateway.srvd.zv4.v0001.KopfType">
     <NavigationPropertyBinding Path="_Text" Target="Container/Text"/>
    </EntitySet>
    <EntitySet Name="Text" EntityType="com.sap.gateway.srvd.zv4.v0001.TextType"/>
   </EntityContainer>
  </Schema>
 </edmx:DataServices>
</edmx:Edmx>'''
PFAD_ZEILEN = [
    {"ID": "ZB_SRV_0001", "Title": "B-Service", "ServiceUrl": "http://intern-gw:8000/sap/opu/odata/sap/ZB_SRV/"},
    {"ID": "ZA_SRV_0002", "Title": "A v2", "ServiceUrl": "http://intern-gw:8000/sap/opu/odata/sap/ZA_SRV;v=0002/"},
    {"ID": "ZA_SRV_0001", "Title": "A-Service", "ServiceUrl": "https://anderer-host/sap/opu/odata/sap/ZA_SRV"},
    {"ID": "ZB_DOPPELT", "Title": "doppelt", "ServiceUrl": "http://intern-gw:8000/SAP/OPU/ODATA/sap/ZB_SRV/"},
    {"ID": "ZV4", "Title": "V4", "ServiceUrl": "http://intern-gw:8000/sap/opu/odata4/sap/zv4/srvd/sap/zv4/0001/"},
    {"ID": "LEER", "Title": "ohne Adresse", "ServiceUrl": ""},
]

# ── Gateway-Nachbildung ─────────────────────────────────────────────
ZUSTAND = {"modus": "count", "zeilen": 3, "anfragen": []}


class _Gateway(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401 – kein Rauschen im Testlauf
        pass

    def _antwort(self, status, body, art="application/json"):
        daten = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", art)
        self.send_header("Content-Length", str(len(daten)))
        self.end_headers()
        self.wfile.write(daten)

    def do_GET(self):  # noqa: N802
        teile = urlsplit(self.path)
        q = parse_qs(teile.query)
        ZUSTAND["anfragen"].append({"pfad": teile.path, "query": q,
                                    "auth": self.headers.get("Authorization", "")})
        modus = ZUSTAND["modus"]
        if modus == "401":
            return self._antwort(401, json.dumps(
                {"error": {"message": {"value": "Anmeldung abgelehnt"}}}))
        if teile.path.endswith("/ZSO_SRV/A_SalesOrder"):
            mit = "to_Text" in (q.get("$expand") or [""])[0]
            text = ({"results": [{"__metadata": {"type": "T"}, "Language": "DE", "LongText": "Hallo",
                                  "to_SalesOrder": {"__deferred": {"uri": "x"}}}]}
                    if mit else {"__deferred": {"uri": "x"}})
            return self._antwort(200, json.dumps({"d": {"results": [
                {"__metadata": {"uri": "u"}, "SalesOrder": "1", "to_Item": {"__deferred": {"uri": "i"}},
                 "to_Text": text}]}}))
        if teile.path.endswith("/ZSO_SRV/$metadata"):
            return self._antwort(200, V2_META, "application/xml")
        if teile.path.endswith("/ZV4/$metadata"):
            return self._antwort(200, V4_META, "application/xml")
        if teile.path.endswith("/$metadata"):
            xml = ('<?xml version="1.0"?><edmx:Edmx xmlns:edmx="x"><Schema xmlns="y">'
                   '<EntityContainer>' + "".join('<EntitySet Name="%s"/>' % n for n in SETS)
                   + '</EntityContainer></Schema></edmx:Edmx>')
            return self._antwort(200, xml, "application/xml")
        if teile.path.endswith("/ServiceCollection"):
            if modus == "pfade":
                return self._antwort(200, json.dumps({"d": {"results": PFAD_ZEILEN}}))
            if modus == "404":
                return self._antwort(404, "nicht da", "text/plain")
            mit_zaehler = "$inlinecount" in q
            if modus == "400" and mit_zaehler:
                return self._antwort(400, json.dumps({"error": {"message": "unbekannt"}}))
            top = int((q.get("$top") or ["100"])[0])
            alle = [{"ID": "Z_SVC_%d" % i, "Title": "S%d" % i} for i in range(ZUSTAND["zeilen"])]
            d = {"results": alle[:top]}
            if modus == "count" and mit_zaehler:
                d["__count"] = str(ZUSTAND["zeilen"])
            return self._antwort(200, json.dumps({"d": d}))
        return self._antwort(404, "unbekannter Pfad", "text/plain")


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Gateway)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASIS = "http://127.0.0.1:%d/sap/opu/odata" % PORT


def client(**extra):
    cfg = {"connection_type": "odata", "odata_base_url": BASIS, "auth_kind": "basic",
           "username": "testuser", "password": KENNWORT, "sap_client": "100",
           "verify_ssl": True}
    cfg.update(extra)
    return sc.SapClient(cfg)


def lauf(modus, zeilen=3, **extra):
    ZUSTAND.update({"modus": modus, "zeilen": zeilen, "anfragen": []})
    c = client(**extra)
    try:
        return c, c.test(), None
    except sc.SapError as e:
        return c, None, e


def ohne_geheimnis(obj):
    t = json.dumps(obj, ensure_ascii=False)
    return KENNWORT not in t and TOKEN not in t


# ══ 0. Positivkontrolle: der Server wird WIRKLICH getroffen ══════════
section("0. Positivkontrolle")
c, res, err = lauf("count", odata_service="ZSVC_SRV")
if err is not None or not ZUSTAND["anfragen"]:
    print(f"  ABBRUCH: Gateway-Nachbildung nicht erreicht ({err}) – Test kann nicht laufen.")
    sys.exit(2)
check(True, "Gateway-Nachbildung beantwortet echte Anfragen (%d)" % len(ZUSTAND["anfragen"]))

# ══ 1. Standard-Service ═════════════════════════════════════════════
section("1. Mit Standard-Service: $metadata")
info = res.get("info") or {}
check(info.get("variante") == "service", "Variante 'service'", repr(info.get("variante")))
check(info.get("entity_sets") == sorted(set(SETS)), "EntitySet-Namen sortiert und einmalig",
      repr(info.get("entity_sets")))
check("3 EntitySet" in (res.get("detail") or "") and "ZSVC_SRV" in (res.get("detail") or ""),
      "Kurzzeile nennt Service und Zahl", res.get("detail"))
adr = info.get("adresse") or ""
check(adr.startswith(BASIS + "/ZSVC_SRV/$metadata"), "Adresse ist die aufgerufene $metadata-URL", adr)
check("sap-client=100" in adr, "Adresse traegt den Mandanten-Parameter", adr)
check(info.get("http_status") == 200, "HTTP-Status 200", repr(info.get("http_status")))
check(isinstance(info.get("dauer_ms"), int) and info["dauer_ms"] >= 0, "Antwortzeit in ms",
      repr(info.get("dauer_ms")))
check(info.get("mandant") == "100" and info.get("benutzer") == "testuser",
      "Mandant und SAP-Benutzer im Bericht", repr((info.get("mandant"), info.get("benutzer"))))
check(info.get("anmeldeart") == "basic", "Anmeldeart basic", repr(info.get("anmeldeart")))
check(info.get("geschaeftsdaten_gelesen") is False, "Bericht sagt: keine Geschaeftsdaten gelesen")
check(ohne_geheimnis(res), "kein Kennwort im Ergebnis")

# ══ 2. Katalog ══════════════════════════════════════════════════════
section("2. Ohne Standard-Service: Gateway-Katalog")
c, res, err = lauf("count", zeilen=137)
info = (res or {}).get("info") or {}
check(err is None and info.get("variante") == "katalog", "Variante 'katalog'", repr(err or info.get("variante")))
check(info.get("anzahl_services") == 137 and info.get("anzahl_genau") is True,
      "echte Zahl ueber $inlinecount (137, genau)",
      repr((info.get("anzahl_services"), info.get("anzahl_genau"))))
check("137" in (res or {}).get("detail", "") and "1+" not in (res or {}).get("detail", ""),
      "Kurzzeile nennt 137 statt '1+'", (res or {}).get("detail"))
check("$inlinecount=allpages" in (info.get("adresse") or ""),
      "Adresse lesbar (Prozent-Kodierung aufgeloest)", info.get("adresse"))
check(len(ZUSTAND["anfragen"]) == 1, "eine einzige Anfrage, wenn der Server zaehlt",
      str(len(ZUSTAND["anfragen"])))

c, res, err = lauf("nocount", zeilen=5)
info = (res or {}).get("info") or {}
check(info.get("anzahl_services") == 5 and info.get("anzahl_genau") is True,
      "ohne Zaehler: durchgezaehlt (5, genau)",
      repr((err, info.get("anzahl_services"), info.get("anzahl_genau"))))

c, res, err = lauf("nocount", zeilen=sc.KATALOG_ZAEHL_MAX + 5)
info = (res or {}).get("info") or {}
check(info.get("anzahl_services") == sc.KATALOG_ZAEHL_MAX and info.get("anzahl_genau") is False,
      "an der Obergrenze: NICHT genau",
      repr((err, info.get("anzahl_services"), info.get("anzahl_genau"))))
check("mindestens" in (res or {}).get("detail", ""), "Kurzzeile sagt 'mindestens'",
      (res or {}).get("detail"))

c, res, err = lauf("400", zeilen=7)
info = (res or {}).get("info") or {}
check(err is None and info.get("anzahl_services") == 7,
      "400 auf $inlinecount: Rueckfall aufs Listen (7)", repr((err, info.get("anzahl_services"))))

c, res, err = lauf("404")
info = (res or {}).get("info") or {}
check(err is None and info.get("variante") == "katalog_fehlt" and info.get("http_status") == 404,
      "404: 'katalog_fehlt' mit Status 404", repr((err, info.get("variante"), info.get("http_status"))))

# ══ 3. Fehlerfall ═══════════════════════════════════════════════════
section("3. Fehlerfall: Bericht trotz Ausnahme")
c, res, err = lauf("401", odata_service="ZSVC_SRV")
check(isinstance(err, sc.SapError) and err.status == 401, "401 wird als Fehler gemeldet", repr(err))
b = c.test_bericht()
check(b.get("variante") == "service" and b.get("http_status") == 401,
      "Bericht: Variante 'service', Status 401", repr((b.get("variante"), b.get("http_status"))))
check("/ZSVC_SRV/$metadata" in (b.get("adresse") or ""), "Bericht: aufgerufene Adresse", b.get("adresse"))
check(ohne_geheimnis(b), "kein Kennwort im Fehlerbericht")

c, res, err = lauf("401")
check(isinstance(err, sc.SapError) and err.status == 401,
      "401 am Katalog wird NICHT als 'kein Katalog' verschluckt", repr((err, res)))

# Geschlossener Port: keine Antwort -> Status 0, Adresse trotzdem da.
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    tot = s.getsockname()[1]
ZUSTAND["anfragen"] = []
c = client(odata_base_url="http://127.0.0.1:%d/sap/opu/odata" % tot)
try:
    c.test()
    err = None
except sc.SapError as e:
    err = e
b = c.test_bericht()
check(isinstance(err, sc.SapError) and err.status == 0, "keine Antwort: SapError mit Status 0", repr(err))
check(b.get("http_status") == 0 and (":%d/" % tot) in (b.get("adresse") or ""),
      "Bericht: Status 0 und die versuchte Adresse samt Parametern",
      repr((b.get("http_status"), b.get("adresse"))))
check("$top=1" in (b.get("adresse") or ""), "versuchte Adresse traegt die Parameter", b.get("adresse"))

# ══ 4. Keine Geheimnisse im Bericht ═════════════════════════════════
section("4. Keine Geheimnisse")
c, res, err = lauf("count", odata_service="ZSVC_SRV", auth_kind="bearer", username="",
                   bearer_token=TOKEN)
info = (res or {}).get("info") or {}
check(err is None and info.get("anmeldeart") == "bearer" and info.get("benutzer") == "",
      "Bearer: Anmeldeart bearer, kein Benutzername", repr((err, info.get("anmeldeart"), info.get("benutzer"))))
check(ohne_geheimnis(res or {}), "kein Token im Ergebnis")
meta = [a for a in ZUSTAND["anfragen"] if a["pfad"].endswith("/$metadata")]
check(bool(meta) and meta[0]["auth"] == "Bearer " + TOKEN,
      "Bearer-Token geht beim $metadata-Abruf mit", repr(meta[:1]))

basis_mit = "http://anmelde:%s@127.0.0.1:%d/sap/opu/odata" % (KENNWORT, PORT)
c, res, err = lauf("count", zeilen=3, odata_base_url=basis_mit)
check(err is None, "Basis-URL mit Anmeldung laeuft", repr(err))
check(ohne_geheimnis(res or {}) and ohne_geheimnis(c.test_bericht()),
      "Anmeldung aus der Adresse steht nicht im Bericht",
      json.dumps((res or {}).get("info"), ensure_ascii=False))

c, res, err = lauf("count", username="")
info = (res or {}).get("info") or {}
check(info.get("anmeldeart") == "keine" and info.get("benutzer") == "",
      "basic ohne Benutzer: Anmeldeart 'keine'", repr((info.get("anmeldeart"), info.get("benutzer"))))
check(all(a["auth"] == "" for a in ZUSTAND["anfragen"]),
      "...und tatsaechlich keine Anmeldung gesendet (Anzeige = Wirkung)",
      repr([a["auth"] for a in ZUSTAND["anfragen"]]))

# ══ 5. Endpunkt reicht den Bericht durch (AST) ══════════════════════
section("5. /api/sap/test")
baum = ast.parse(Path(ARGS.main).read_text(encoding="utf-8"))
fn = [n for n in ast.walk(baum) if isinstance(n, ast.AsyncFunctionDef) and n.name == "sap_test"]
if len(fn) != 1:
    print(f"  ABBRUCH: sap_test nicht eindeutig gefunden ({len(fn)}) – Test kann nicht laufen.")
    sys.exit(2)
antworten = []
for n in ast.walk(fn[0]):
    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "JSONResponse"
            and n.args and isinstance(n.args[0], ast.Dict)):
        werte = {k.value: v for k, v in zip(n.args[0].keys, n.args[0].values)
                 if isinstance(k, ast.Constant)}
        antworten.append(werte)


def _konst(werte, k):
    v = werte.get(k)
    return v.value if isinstance(v, ast.Constant) else None


getestet = [w for w in antworten if _konst(w, "configured") is True]
check({_konst(w, "ok") for w in getestet} == {True, False},
      "Antworten nach einem Test: Erfolg UND Fehler gefunden",
      repr([_konst(w, "ok") for w in getestet]))
check(all("info" in w for w in getestet), "jede Antwort nach einem Test traegt 'info'",
      repr([sorted(w) for w in getestet]))
bericht_aufrufe = [n for n in ast.walk(fn[0]) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute) and n.func.attr == "test_bericht"]
check(len(bericht_aufrufe) >= 1, "Fehlerzweig holt den Bericht ueber test_bericht()")

# ══ 7. Abfrage-Konsole: Service-Pfade aus dem Katalog ═══════════════
section("7. Konsole: Service-Pfade relativ zur Basis-URL")
for basis_variante in (BASIS, BASIS + "/"):
    ZUSTAND.update({"modus": "pfade", "anfragen": []})
    c = client(odata_base_url=basis_variante)
    try:
        r = c.odata.catalog_service_pfade()
    except sc.SapError as e:
        r = {"services": [], "fehler": str(e)}
    namen = [x["service"] for x in r.get("services", [])]
    zusatz = " (Basis mit /)" if basis_variante.endswith("/") else ""
    check(namen == ["sap/ZA_SRV", "sap/ZA_SRV;v=0002", "sap/ZB_SRV"],
          "relative Pfade, einmalig, sortiert" + zusatz, repr(r))
    check(r.get("ausgelassen") == 2, "ausserhalb der Basis und ohne Adresse: 2 ausgelassen" + zusatz,
          repr(r.get("ausgelassen")))
check(all("://" not in n and "intern-gw" not in n and "anderer-host" not in n for n in namen),
      "kein Host aus den Katalogdaten in den Pfaden", repr(namen))
titel = {x["service"]: x["title"] for x in r.get("services", [])}
check(titel.get("sap/ZB_SRV") == "B-Service", "Titel des ERSTEN Eintrags bleibt", repr(titel))
check(r.get("genau") is True, "unter der Obergrenze: genau")

# Der Pfad muss in genau der Form taugen, die die Konsole als Service schickt.
ZUSTAND.update({"modus": "count", "anfragen": []})
c = client()
try:
    c.odata.entity_sets("sap/ZB_SRV")
    fehler = None
except sc.SapError as e:
    fehler = e
pfade = [a["pfad"] for a in ZUSTAND["anfragen"]]
check(fehler is None and pfade == ["/sap/opu/odata/sap/ZB_SRV/$metadata"],
      "gelisteter Pfad erreicht den Service ueber die Basis-URL", repr((fehler, pfade)))

ZUSTAND.update({"modus": "nocount", "zeilen": sc.KATALOG_ZAEHL_MAX + 5, "anfragen": []})
r = client().odata.catalog_service_pfade()
check(r.get("genau") is False, "an der Obergrenze: NICHT genau", repr(r.get("genau")))

# ══ 8. Endpunkte der Konsole (AST) ══════════════════════════════════
section("8. Endpunkte der Konsole")
fns = {n.name: n for n in ast.walk(baum) if isinstance(n, ast.AsyncFunctionDef)}


def _route(fn):
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant):
            return d.args[0].value
    return None


def _depends(fn):
    return [ast.unparse(d) for d in fn.args.defaults if "Depends" in ast.unparse(d)]


f_svc = fns.get("sap_odata_services_api")
f_sets = fns.get("sap_odata_entity_sets_api")
if f_svc is None or f_sets is None:
    print("  ABBRUCH: Konsolen-Endpunkte nicht gefunden – Test kann nicht laufen.")
    sys.exit(2)
check(_route(f_svc) == "/api/sap/odata/services", "Service-Liste unter /api/sap/odata/services",
      repr(_route(f_svc)))
check(_depends(f_svc) == ["Depends(require_sap_access)"], "Service-Liste verlangt die SAP-Freigabe",
      repr(_depends(f_svc)))
check(any(isinstance(n, ast.Attribute) and n.attr == "catalog_service_pfade" for n in ast.walk(f_svc)),
      "Service-Liste kommt aus catalog_service_pfade (relative Pfade)")
# EntitySets ohne Service: Schranke VOR dem Abruf, und abgerufen wird der
# GEPRUEFTE Wert, nicht wieder die rohe Eingabe.
aufrufe = [n for n in ast.walk(f_sets) if isinstance(n, ast.Call) and ast.unparse(n.func) == "asyncio.to_thread"]
check(len(aufrufe) == 1 and len(aufrufe[0].args) == 2 and ast.unparse(aufrufe[0].args[1]) == "svc",
      "entity_sets wird mit dem geprueften Service gerufen", repr([ast.unparse(a) for a in aufrufe]))
schranke = [n for n in ast.walk(f_sets) if isinstance(n, ast.If) and ast.unparse(n.test) == "not svc"
            and any(isinstance(k, ast.Constant) and k.value == "kein_service"
                    for x in ast.walk(n) if isinstance(x, ast.Dict) for k in x.keys)]
check(len(schranke) == 1 and aufrufe and schranke[0].lineno < aufrufe[0].lineno,
      "ohne Service: Antwort mit kein_service VOR dem Abruf")

# ══ 9. Nicht direkt abrufbare EntitySets und der Weg dorthin ════════
section("9. EntitySets: Abrufbarkeit und Navigationsweg")
ZUSTAND.update({"modus": "count", "anfragen": []})
c = client()
try:
    det = {d["name"]: d for d in c.odata.entity_set_details("sap/ZSO_SRV")}
    namen_v2 = c.odata.entity_sets("sap/ZSO_SRV")
except sc.SapError as e:
    det, namen_v2 = {}, []
    print("  (Fehler: %s)" % e)
check(sorted(det) == ["A_SalesOrder", "A_SalesOrderItem", "A_SalesOrderItemText", "A_SalesOrderText"],
      "V2: alle vier EntitySets", repr(sorted(det)))
check(namen_v2 == sorted(det, key=str.lower), "entity_sets() liefert dieselben Namen (eine Quelle)",
      repr(namen_v2))
check(det.get("A_SalesOrderText", {}).get("addressable") is False
      and det.get("A_SalesOrderItemText", {}).get("addressable") is False,
      "V2: sap:addressable=\"false\" erkannt",
      repr({k: v.get("addressable") for k, v in det.items()}))
check(det.get("A_SalesOrder", {}).get("addressable") is True
      and det.get("A_SalesOrderItem", {}).get("addressable") is True,
      "V2: ohne bzw. mit addressable=\"true\" gilt abrufbar")
check(det.get("A_SalesOrderText", {}).get("navigation")
      == [{"von": "A_SalesOrder", "property": "to_Text", "schluessel": ["SalesOrder"]}],
      "V2: Weg zu A_SalesOrderText = A_SalesOrder/to_Text (Koeder to_TextAlt NICHT)",
      repr(det.get("A_SalesOrderText", {}).get("navigation")))
check(det.get("A_SalesOrderItemText", {}).get("navigation")
      == [{"von": "A_SalesOrderItem", "property": "to_ItemText",
           "schluessel": ["SalesOrder", "SalesOrderItem"]}],
      "V2: zusammengesetzter Schluessel des Herkunfts-Sets",
      repr(det.get("A_SalesOrderItemText", {}).get("navigation")))
check(det.get("A_SalesOrder", {}).get("navigation") == [], "V2: Kopf hat keinen eingehenden Weg",
      repr(det.get("A_SalesOrder", {}).get("navigation")))

try:
    det4 = {d["name"]: d for d in c.odata.entity_set_details("sap/ZV4")}
except sc.SapError as e:
    det4 = {}
    print("  (Fehler: %s)" % e)
check(sorted(det4) == ["Kopf", "Text"] and all(d["addressable"] for d in det4.values()),
      "V4: Sets erkannt, ohne SAP-Markierung abrufbar", repr(det4))
check(det4.get("Text", {}).get("navigation") == [{"von": "Kopf", "property": "_Text", "schluessel": ["Id"]}],
      "V4: Weg ueber NavigationPropertyBinding (Target mit Container-Praefix)",
      repr(det4.get("Text", {}).get("navigation")))

# Der Wert VON "ok" muss True sein – "irgendein Wert ist True" traf auch
# kein_service: True (erster Lauf, Sonde falsch, nicht der Code).
ok_rueckgaben = [n for n in ast.walk(f_sets) if isinstance(n, ast.Dict)
                 and any(isinstance(k, ast.Constant) and k.value == "ok"
                         and isinstance(v, ast.Constant) and v.value is True
                         for k, v in zip(n.keys, n.values))]
check(len(ok_rueckgaben) == 1 and any(isinstance(k, ast.Constant) and k.value == "details"
                                      for k in ok_rueckgaben[0].keys),
      "Endpunkt liefert die Details mit aus", repr([ast.unparse(d)[:80] for d in ok_rueckgaben]))
check(len(aufrufe) == 1 and ast.unparse(aufrufe[0].args[0]) == "c.odata.entity_set_details",
      "Endpunkt liest ueber entity_set_details", repr([ast.unparse(a) for a in aufrufe]))

# ══ 10. Mitladen ($expand) ═══════════════════════════════════════════
section("10. Mitladen: Zeilen fuer die Tabelle")
roh = [
    {"__metadata": {"uri": "u1"}, "SalesOrder": "1", "to_Item": {"__deferred": {"uri": "i"}},
     "to_Text": {"results": [{"__metadata": {}, "Language": "DE", "LongText": "Hallo",
                              "to_SalesOrder": {"__deferred": {"uri": "s"}}}]},
     "to_Partner": {"__metadata": {}, "Name": "Contoso"}},
    {"SalesOrder": "2", "to_Text": {"results": []}, "Extra": "x"},
]
spalten, zeilen = sc.tabelle_aus(roh)
check(spalten == ["SalesOrder", "to_Text", "to_Partner", "Extra"],
      "Spalten ueber ALLE Zeilen, ohne nicht geladene Navigation", repr(spalten))
check(zeilen[0]["to_Text"] == [{"Language": "DE", "LongText": "Hallo"}],
      "V2: mitgeladene Liste geglaettet, auch im Kind bereinigt", repr(zeilen[0].get("to_Text")))
check(zeilen[0]["to_Partner"] == {"Name": "Contoso"}, "V2: mitgeladenes Einzelobjekt bleibt Objekt",
      repr(zeilen[0].get("to_Partner")))
check(zeilen[1]["to_Text"] == [], "V2: leere mitgeladene Liste bleibt leere Liste", repr(zeilen[1].get("to_Text")))
check("to_Item" not in zeilen[0] and "__metadata" not in zeilen[0], "nicht Geladenes und __metadata entfernt",
      repr(sorted(zeilen[0])))
v4 = sc.tabelle_aus([{"@odata.etag": "e", "Id": "1", "_Text@odata.navigationLink": "x",
                      "_Text": [{"@odata.etag": "e2", "T": "a"}]}])
check(v4 == (["Id", "_Text"], [{"Id": "1", "_Text": [{"T": "a"}]}]), "V4: Anmerkungen entfernt", repr(v4))
check(sc.tabelle_aus([]) == ([], []), "leere Antwort: keine Spalten, keine Zeilen")

ZUSTAND.update({"modus": "count", "anfragen": []})
c = client()
try:
    mit = c.odata.query("A_SalesOrder", "sap/ZSO_SRV", top=5, expand="to_Text")
    ohne = c.odata.query("A_SalesOrder", "sap/ZSO_SRV", top=5)
    fehler = None
except sc.SapError as e:
    mit, ohne, fehler = [], [], e
q_mit = ZUSTAND["anfragen"][0]["query"] if ZUSTAND["anfragen"] else {}
check(fehler is None and q_mit.get("$expand") == ["to_Text"], "Abruf traegt $expand=to_Text",
      repr((fehler, q_mit)))
check(len(ZUSTAND["anfragen"]) == 2 and "$expand" not in ZUSTAND["anfragen"][1]["query"],
      "ohne Mitladen kein $expand", repr([a["query"] for a in ZUSTAND["anfragen"]]))
sp_mit, z_mit = sc.tabelle_aus(mit)
sp_ohne, _ = sc.tabelle_aus(ohne)
check(sp_mit == ["SalesOrder", "to_Text"] and z_mit and z_mit[0]["to_Text"] == [{"Language": "DE", "LongText": "Hallo"}],
      "echte Antwort mit $expand: Texte als Liste in der Zeile", repr((sp_mit, z_mit)))
check(sp_ohne == ["SalesOrder"], "echte Antwort ohne $expand: keine Verweis-Spalten", repr(sp_ohne))

f_q = fns.get("sap_odata_query_api")
if f_q is None:
    print("  ABBRUCH: sap_odata_query_api nicht gefunden – Test kann nicht laufen.")
    sys.exit(2)
check(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tabelle_aus"
          for n in ast.walk(f_q)), "Abfrage-Endpunkt bereitet ueber tabelle_aus auf")
check(not any(isinstance(n, ast.Constant) and n.value == "__metadata" for n in ast.walk(f_q)),
      "...und hat keine eigene, zweite Bereinigung")

srv.shutdown()
print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
