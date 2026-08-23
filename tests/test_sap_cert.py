#!/usr/bin/env python3
"""Tests fuer das Pruefen und Verankern des SAP-Serverzertifikats.

Laeuft ohne fastapi und ohne SAP-System:

* ``backend.config`` wird als Attrappe in ``sys.modules`` gelegt – der ECHTE
  Import migriert beim Laden die LIVE-``settings.json`` und schreibt sie zurueck
  (dieselbe Falle wie in test_sap_accounts.py und test_email_rules.py).
* Alle Pfade zeigen in ein Wegwerf-Verzeichnis; ein SANDKASTEN-WAECHTER bricht
  mit Exit 2 ab, wenn danach noch einer auf ``data/`` des Repos zeigt.

**Der Kern ist ein ECHTER lokaler TLS-Server** mit selbst erzeugten
Zertifikaten. Eine Attrappe wuerde genau das nicht pruefen, worauf hier alles
ruht: dass ein verankertes Zertifikat eine echte ``requests``-Verbindung
zustande bringt – und ein falsches sie weiterhin verhindert. Deshalb gibt es
die drei Faelle "ohne Anker scheitert / mit Anker laeuft / mit FREMDEM Anker
scheitert wieder" als Positivkontrolle und Gegenprobe.

Exit 2 heisst "konnte nicht laufen", 1 "Pruefung fehlgeschlagen", 0 bestanden.

    python3 tests/test_sap_cert.py
"""
import datetime
import http.server
import json
import re
import socket
import ssl
import sys
import tempfile
import threading
import types
from pathlib import Path

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


try:
    import requests
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except Exception as e:  # noqa: BLE001
    print(f"Voraussetzung fehlt ({e}) – Test kann nicht laufen.")
    sys.exit(2)


# ── Attrappe fuer backend.config VOR dem Import ─────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="sapcert_test_"))
(TMP / "data").mkdir(parents=True)

_skill_states = {"sap": {"enabled": True, "config": {}}}
_cfg_mod = types.ModuleType("backend.config")


class _Cfg:
    def get_skill_states(self):
        return _skill_states

    def get_setting(self, key, default=None):
        return default

    def save_setting(self, key, value):
        pass


_cfg_mod.config = _Cfg()
sys.modules.setdefault("backend.config", _cfg_mod)

from backend import sap_cert as sc            # noqa: E402
from backend import sap_accounts as sa        # noqa: E402
from backend import sap_client                # noqa: E402

sc.CERT_DIR = TMP / "data" / "sap_certs"
sa.DATA_DIR = TMP / "data"
sa.KONTEN_DATEI = TMP / "data" / "sap_accounts.json"
sa.SCHLUESSEL_DATEI = TMP / "data" / ".sapkey"

_ECHTES_DATA = ROOT / "data"
for modul in (sc, sa):
    for name in dir(modul):
        wert = getattr(modul, name)
        if isinstance(wert, Path) and name.isupper() and name != "PROJECT_ROOT":
            try:
                drin = wert == _ECHTES_DATA or _ECHTES_DATA in wert.parents
            except Exception:  # noqa: BLE001
                drin = False
            if drin:
                print(f"SANDKASTEN VERLETZT: {modul.__name__}.{name} = {wert}")
                sys.exit(2)


def admin_config(**felder):
    _skill_states["sap"]["config"] = dict(felder)


# ── Ein echter TLS-Server mit selbst erzeugtem Zertifikat ───────────────────

def zertifikat_bauen(cn: str, sans: list[str], tage: int = 30,
                     start_vor_tagen: int = 1):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Testhaus AG")])
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    b = (x509.CertificateBuilder()
         .subject_name(name).issuer_name(name)
         .public_key(key.public_key())
         .serial_number(x509.random_serial_number())
         .not_valid_before(jetzt - datetime.timedelta(days=start_vor_tagen))
         .not_valid_after(jetzt + datetime.timedelta(days=tage)))
    eintraege = []
    for s in sans:
        try:
            import ipaddress
            eintraege.append(x509.IPAddress(ipaddress.ip_address(s)))
        except ValueError:
            eintraege.append(x509.DNSName(s))
    if eintraege:
        b = b.add_extension(x509.SubjectAlternativeName(eintraege), critical=False)
    zert = b.sign(key, hashes.SHA256())
    return (zert.public_bytes(serialization.Encoding.PEM).decode(),
            key.private_bytes(serialization.Encoding.PEM,
                              serialization.PrivateFormat.TraditionalOpenSSL,
                              serialization.NoEncryption()).decode())


class _Stumm(http.server.BaseHTTPRequestHandler):
    def do_GET(self):                      # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"d":{"results":[]}}')

    def log_message(self, *a):             # kein Rauschen im Testlauf
        pass


class _StummerServer(http.server.HTTPServer):
    """Die Zertifikatspruefung baut TLS auf und legt sofort wieder auf – ohne
    je eine Anfrage zu senden. Genau das ist der Sinn (es geht nur um das
    Zertifikat), fuer den Server ist es aber ein abgebrochener Client und er
    schreibt einen kompletten Traceback. Der wuerde die Testausgabe
    unbrauchbar machen."""

    def handle_error(self, request, client_address):
        pass


def server_starten(cert_pem: str, key_pem: str):
    cf = TMP / f"srv_{abs(hash(cert_pem)) % 10**8}.pem"
    cf.write_text(cert_pem + key_pem, encoding="ascii")
    srv = _StummerServer(("127.0.0.1", 0), _Stumm)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cf))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


# Zertifikat A lautet auf localhost (passt), B auf einen fremden Namen.
PEM_A, KEY_A = zertifikat_bauen("localhost", ["localhost", "127.0.0.1"])
PEM_B, KEY_B = zertifikat_bauen("ganz.woanders.example", ["ganz.woanders.example"])
PEM_ALT, KEY_ALT = zertifikat_bauen("localhost", ["localhost", "127.0.0.1"],
                                    tage=-1, start_vor_tagen=40)

SRV_A, PORT_A = server_starten(PEM_A, KEY_A)
SRV_B, PORT_B = server_starten(PEM_B, KEY_B)
SRV_ALT, PORT_ALT = server_starten(PEM_ALT, KEY_ALT)


# ═══════════════════════════════════════════════════════════════════════════
section("1. Ziel bestimmen")
# ═══════════════════════════════════════════════════════════════════════════

check(sc.ziel_bestimmen("odata", {"url": "https://s4.firma.de:8443/sap/opu"})
      == ("s4.firma.de", 8443), "OData: Host und Port aus der URL")
check(sc.ziel_bestimmen("odata", {"url": "https://s4.firma.de/sap"})
      == ("s4.firma.de", 443), "OData: Standardport 443")
check(sc.ziel_bestimmen("odata", {"url": "s4.firma.de"}) == ("s4.firma.de", 443),
      "OData: fehlendes Schema wird zu https ergaenzt")
check(sc.ziel_bestimmen("hana", {"host": "hana.firma.de", "port": "30015"})
      == ("hana.firma.de", 30015), "HANA: Host und Port")
check(sc.ziel_bestimmen("hana", {"host": "hana.firma.de:30015"})
      == ("hana.firma.de", 30015), "HANA: 'host:port' aus Copy&Paste")

for fall, angabe in (("http statt https", {"url": "http://s4.firma.de"}),
                     ("leere Adresse", {"url": ""}),
                     ("Port ausserhalb", {"host": "h", "port": "70000"})):
    kanal = "hana" if "host" in angabe else "odata"
    try:
        sc.ziel_bestimmen(kanal, angabe)
        check(False, f"abgewiesen: {fall}")
    except sc.ZertFehler:
        check(True, f"abgewiesen: {fall}")
try:
    sc.ziel_bestimmen("rfc", {"host": "x"})
    check(False, "RFC hat kein Serverzertifikat -> abgewiesen")
except sc.ZertFehler:
    check(True, "RFC hat kein Serverzertifikat -> abgewiesen")


# ═══════════════════════════════════════════════════════════════════════════
section("2. Pruefen: die drei Urteile werden GEMESSEN")
# ═══════════════════════════════════════════════════════════════════════════

erg_a = sc.pruefen("localhost", PORT_A)
check(erg_a["fingerprint"].startswith("sha256:") and len(erg_a["fingerprint"]) == 71,
      "Fingerabdruck im erwarteten Format", erg_a["fingerprint"][:20])
check(erg_a["system_ok"] is False, "selbst ausgestellt -> System-Pruefung scheitert")
check(erg_a["pin_ok"] is True, "…aber der Anker WUERDE wirken (dritter Handshake)")
check(erg_a["selbstsigniert"] is True, "als selbstsigniert erkannt")
check(erg_a["inhaber"] == "localhost", "Inhaber gelesen", erg_a["inhaber"])
check("Testhaus AG" in erg_a["aussteller"] or erg_a["aussteller"] == "localhost",
      "Aussteller gelesen", erg_a["aussteller"])
check("localhost" in erg_a["namen"], "SAN-Namen gelesen", str(erg_a["namen"]))
check(bool(erg_a["gueltig_bis"]), "Laufzeit gelesen", erg_a["gueltig_bis"])
check(erg_a["pem"].startswith("-----BEGIN CERTIFICATE-----"), "PEM liegt bei")

# Zertifikat auf einen FREMDEN Namen: verankern wuerde nichts nuetzen, weil der
# Namensabgleich weiterhin scheitert. Genau dafuer gibt es den dritten
# Handshake – ohne ihn haette der Knopf etwas versprochen, das nicht traegt.
erg_b = sc.pruefen("localhost", PORT_B)
check(erg_b["system_ok"] is False, "fremder Name: System-Pruefung scheitert")
check(erg_b["pin_ok"] is False, "fremder Name: Anker wuerde NICHT wirken")
check(bool(erg_b["pin_grund"]), "…und der Grund wird genannt", erg_b["pin_grund"])
check("ganz.woanders.example" in erg_b["namen"],
      "die Namen im Zertifikat werden genannt (Weg zur Loesung)")

erg_alt = sc.pruefen("localhost", PORT_ALT)
check(erg_alt["pin_ok"] is False, "abgelaufen: Anker wuerde nicht wirken")
check("abgelaufen" in (erg_alt["pin_grund"] + erg_alt["system_grund"]).lower(),
      "…und 'abgelaufen' steht im Klartext",
      erg_alt["pin_grund"] or erg_alt["system_grund"])

try:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        toter_port = s.getsockname()[1]
    sc.pruefen("127.0.0.1", toter_port)
    check(False, "unerreichbarer Server -> ZertFehler")
except sc.ZertFehler as e:
    check("nicht erreichbar" in str(e), "unerreichbarer Server -> Klartext", str(e)[:60])


# ── Der Vertrauensspeicher muss der des KANALS sein ─────────────────────────
# GEFUNDEN AUF DEV (2026-08-23): dort liegt eine interne CA im Systemspeicher.
# `ssl.create_default_context()` sagte deshalb "vertrauenswuerdig", waehrend
# genau dieselbe Verbindung ueber `requests` (certifi!) mit SSLError scheiterte.
# Die Anzeige haette "nichts zu tun" gemeldet, und die SAP-Verbindung waere
# trotzdem tot geblieben – die Fehlerklasse "eine Zusage, die der Code nicht
# haelt". Hier deterministisch nachgestellt ueber REQUESTS_CA_BUNDLE.
import os                                                        # noqa: E402
_bundle = TMP / "nur_a.pem"
_bundle.write_text(PEM_A, encoding="ascii")
os.environ["REQUESTS_CA_BUNDLE"] = str(_bundle)
try:
    odata_sicht = sc.pruefen("localhost", PORT_A, "odata")
    hana_sicht = sc.pruefen("localhost", PORT_A, "hana")
finally:
    os.environ.pop("REQUESTS_CA_BUNDLE", None)
check(odata_sicht["system_ok"] is True,
      "OData misst das CA-Buendel von requests (dort ist das Zertifikat bekannt)")
check(str(_bundle) in odata_sicht["system_quelle"],
      "…und nennt die benutzte Quelle", odata_sicht["system_quelle"])
check(hana_sicht["system_ok"] is False,
      "HANA misst den Systemspeicher (dort ist es unbekannt) – nicht dasselbe!")
check(hana_sicht["system_quelle"] == "Systemspeicher",
      "…und nennt ihn so", hana_sicht["system_quelle"])
check(sc.pruefen("localhost", PORT_A, "odata")["system_ok"] is False,
      "ohne die Umgebungsvariable gilt wieder certifi (Zertifikat unbekannt)")


# ═══════════════════════════════════════════════════════════════════════════
section("3. Buendel-Datei")
# ═══════════════════════════════════════════════════════════════════════════

pfad = sc.bundle_pfad(erg_a["pem"])
p = Path(pfad)
check(p.exists() and p.read_text().strip() == erg_a["pem"].strip(),
      "Buendel enthaelt genau das verankerte Zertifikat")
check(oct(p.stat().st_mode & 0o777) == "0o640", "Buendel ist 0640",
      oct(p.stat().st_mode & 0o777))
check(sc.bundle_pfad(erg_a["pem"]) == pfad, "idempotent: gleicher Inhalt, gleiche Datei")
check(sc.bundle_pfad(erg_b["pem"]) != pfad, "anderes Zertifikat -> andere Datei")
for muell in ("", "kein zertifikat", "-----BEGIN CERTIFICATE----- <script>"):
    try:
        sc.bundle_pfad(muell)
        check(False, f"Muell abgewiesen: {muell[:20]!r}")
    except sc.ZertFehler:
        check(True, f"Muell abgewiesen: {muell[:20]!r}")


# ═══════════════════════════════════════════════════════════════════════════
section("4. POSITIVKONTROLLE: der Anker traegt eine ECHTE Verbindung")
# ═══════════════════════════════════════════════════════════════════════════
# Ohne diese drei Faelle waere "verankert" eine Behauptung.

url_a = f"https://localhost:{PORT_A}/sap/opu"
eintrag_a = sc.eintrag_bauen(erg_a)

cfg_ohne = {"odata_base_url": url_a, "verify_ssl": True}
cfg_mit = {"odata_base_url": url_a, "verify_ssl": True, "cert_odata": eintrag_a}
cfg_falsch = {"odata_base_url": url_a, "verify_ssl": True,
              "cert_odata": sc.eintrag_bauen(
                  dict(erg_b, host="localhost", port=PORT_A))}


def holt(cfg) -> tuple[bool, str]:
    v = sap_client._verify_odata(cfg, cfg["odata_base_url"])
    try:
        r = requests.get(url_a, verify=v, timeout=5)
        return r.status_code == 200, ""
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__


ok_ohne, _ = holt(cfg_ohne)
ok_mit, grund_mit = holt(cfg_mit)
ok_falsch, _ = holt(cfg_falsch)
check(ok_ohne is False, "OHNE Anker scheitert die Verbindung (Gegenprobe)")
check(ok_mit is True, "MIT Anker laeuft sie durch", grund_mit)
check(ok_falsch is False, "mit FREMDEM Anker scheitert sie wieder")

# Ziel-Bindung: derselbe Anker, anderes Ziel -> gilt nicht.
cfg_anderes_ziel = {"odata_base_url": f"https://localhost:{PORT_B}/sap",
                    "verify_ssl": True, "cert_odata": eintrag_a}
v = sap_client._verify_odata(cfg_anderes_ziel, cfg_anderes_ziel["odata_base_url"])
check(v is True, "Anker fuer Port A gilt bei Port B nicht (Ziel-Bindung)", repr(v))
check(sc.passt(eintrag_a, "localhost", PORT_A) is True, "passt(): richtiges Ziel")
check(sc.passt(eintrag_a, "andere.host", PORT_A) is False, "passt(): anderer Host")
check(sc.passt(eintrag_a, "LOCALHOST", PORT_A) is True, "passt(): Gross/Klein egal")
check(sc.passt(None, "localhost", PORT_A) is False, "passt(): ohne Eintrag False")

# Der Anker STICHT den abgeschalteten Haken – verankern ist strenger.
cfg_aus = {"odata_base_url": url_a, "verify_ssl": False, "cert_odata": eintrag_a}
v_aus = sap_client._verify_odata(cfg_aus, url_a)
check(isinstance(v_aus, str), "Anker gewinnt gegen verify_ssl:false", repr(v_aus))
check(sap_client._verify_odata({"odata_base_url": url_a, "verify_ssl": False}, url_a)
      is False, "ohne Anker bleibt verify_ssl:false unveraendert")
check(sap_client._verify_odata({"odata_base_url": url_a}, url_a) is True,
      "ohne alles gilt weiterhin: pruefen")

# Kaputte URL -> es bleibt beim eingestellten Wert, kein Absturz.
check(sap_client._verify_odata({"odata_base_url": "http://x", "verify_ssl": True,
                                "cert_odata": eintrag_a}, "http://x") is True,
      "unbestimmbares Ziel -> eingestellter Wert, kein Absturz")


# ═══════════════════════════════════════════════════════════════════════════
section("5. Bestaetigen: das PEM kommt nie aus dem Request")
# ═══════════════════════════════════════════════════════════════════════════

e = sc.bestaetigen("localhost", PORT_A, erg_a["fingerprint"])
check(e["pem"].strip() == erg_a["pem"].strip(),
      "bestaetigen() holt das Zertifikat selbst")
check(e["host"] == "localhost" and e["port"] == PORT_A, "Ziel steht im Eintrag")
check(e["name_abweichung"] is False, "kein Namensproblem bei passendem Zertifikat")
try:
    sc.bestaetigen("localhost", PORT_A, erg_b["fingerprint"])
    check(False, "falscher Fingerabdruck wird abgewiesen")
except sc.ZertFehler as err:
    check("geaendert" in str(err), "falscher Fingerabdruck wird abgewiesen")
for muell in ("", "sha256:xx", "abc", "sha256:" + "z" * 64):
    try:
        sc.bestaetigen("localhost", PORT_A, muell)
        check(False, f"kein Fingerabdruck: {muell[:16]!r} abgewiesen")
    except sc.ZertFehler:
        check(True, f"kein Fingerabdruck: {muell[:16]!r} abgewiesen")
check(sc.fingerabdruck_gueltig(erg_a["fingerprint"].upper()) is True,
      "Grossschreibung im Fingerabdruck ist erlaubt")

check("pem" not in sc.info(eintrag_a), "info() gibt das PEM NICHT heraus")
check(sc.info(eintrag_a).get("fingerprint") == erg_a["fingerprint"],
      "info() nennt den Fingerabdruck")
check(sc.info(None) == {} and sc.info({"host": "x"}) == {},
      "info() ohne Anker ist leer")


# ═══════════════════════════════════════════════════════════════════════════
section("6. Persoenlicher Zugang: Freigabeliste und Whitelist")
# ═══════════════════════════════════════════════════════════════════════════

admin_config(allowed_hosts="localhost")
info = sa.zertifikat_binden("nexus\\andrea.ladd", "odata", "localhost", PORT_A,
                            erg_a["fingerprint"])
check(info["cert"]["odata"]["eigen"].get("fingerprint") == erg_a["fingerprint"],
      "eigener Anker gespeichert und in zugang_info sichtbar")
check("pem" not in json.dumps(info["cert"]), "zugang_info liefert kein PEM")

konten = json.loads(sa.KONTEN_DATEI.read_text(encoding="utf-8"))
check(konten["andrea.ladd"]["cert_odata"]["pem"].startswith("-----BEGIN"),
      "…das PEM liegt aber gespeichert vor (fuer die Verbindung)")

admin_config(allowed_hosts="nur.dieser.de")
try:
    sa.zertifikat_binden("nexus\\andrea.ladd", "odata", "localhost", PORT_A,
                         erg_a["fingerprint"])
    check(False, "Host ausserhalb der Freigabeliste wird abgewiesen")
except sa.SapKontoFehler as err:
    check("nicht freigegeben" in str(err),
          "Host ausserhalb der Freigabeliste wird abgewiesen", str(err)[:50])
try:
    sa.host_pruefen("localhost")
    check(False, "host_pruefen() weist denselben Host ab")
except sa.SapKontoFehler:
    check(True, "host_pruefen() weist denselben Host ab")

admin_config(allowed_hosts="localhost")
# Ueber speichern() darf KEIN Anker hineinkommen – sonst waere der Endpunkt ein
# Weg, einen beliebigen Vertrauensanker einzuschleusen.
check("cert_odata" not in sa.AENDERBAR and "cert_hana" not in sa.AENDERBAR,
      "cert_* stehen NICHT in AENDERBAR")
try:
    sa.speichern("nexus\\andrea.ladd", {"cert_odata": {"pem": PEM_B, "host": "x"}})
    check(False, "speichern() weist ein untergeschobenes Zertifikat ab")
except sa.SapKontoFehler as err:
    check("cert_odata" in str(err), "speichern() weist ein untergeschobenes "
                                    "Zertifikat ab", str(err)[:60])

info = sa.zertifikat_loesen("nexus\\andrea.ladd", "odata")
check(info["cert"]["odata"]["eigen"] == {}, "Loesen entfernt den eigenen Anker")
info = sa.zertifikat_loesen("nexus\\andrea.ladd", "odata")
check(info["cert"]["odata"]["eigen"] == {}, "Loesen ist idempotent")
for kanal in ("rfc", "quatsch", ""):
    try:
        sa.zertifikat_binden("nexus\\andrea.ladd", kanal, "localhost", PORT_A,
                             erg_a["fingerprint"])
        check(False, f"unbekannter Kanal {kanal!r} abgewiesen")
    except sa.SapKontoFehler:
        check(True, f"unbekannter Kanal {kanal!r} abgewiesen")


# ═══════════════════════════════════════════════════════════════════════════
section("7. Vorrang: eigener Anker vor dem des Administrators")
# ═══════════════════════════════════════════════════════════════════════════

admin_anker = sc.eintrag_bauen(sc.pruefen("localhost", PORT_B))
admin_config(allowed_hosts="localhost", verify_ssl=True, cert_odata=admin_anker)
sa.speichern("nexus\\andrea.ladd", {
    "connection_type": "odata", "odata_base_url": url_a,
    "username": "SAPUSER", "password": "geheim"})

cfg = sa._cfg_aus_zugang(json.loads(sa.KONTEN_DATEI.read_text())["andrea.ladd"])
check(cfg["cert_odata"] == admin_anker,
      "ohne eigenen Anker gilt der des Administrators")

sa.zertifikat_binden("nexus\\andrea.ladd", "odata", "localhost", PORT_A,
                     erg_a["fingerprint"])
cfg = sa._cfg_aus_zugang(json.loads(sa.KONTEN_DATEI.read_text())["andrea.ladd"])
check(cfg["cert_odata"]["fingerprint"] == erg_a["fingerprint"],
      "eigener Anker sticht den des Administrators")
check(sa.zugang_info("nexus\\andrea.ladd")["cert"]["odata"]["admin"].get("fingerprint")
      == admin_anker["fingerprint"],
      "die Oberflaeche sieht trotzdem, WAS der Administrator verankert hat")

# Und der Client benutzt ihn dann auch wirklich.
klient = sap_client.SapClient(cfg)
check(isinstance(klient.odata.verify, str), "SapClient nimmt den Anker",
      repr(klient.odata.verify))
check(Path(klient.odata.verify).read_text().strip() == erg_a["pem"].strip(),
      "…und zwar genau das eigene Zertifikat")


# ═══════════════════════════════════════════════════════════════════════════
section("8. HANA: die Parameter werden korrekt zusammengebaut")
# ═══════════════════════════════════════════════════════════════════════════
# Ein echter HANA-Lauf ist hier nicht moeglich (kein HANA auf DEV). Geprueft
# wird, WAS an dbapi.connect ginge – das ist die Haelfte, die in unserer Hand
# liegt; die andere steht so auch im Code-Kommentar.

anker_h = sc.eintrag_bauen(dict(sc.pruefen("localhost", PORT_A)))
h = sap_client._HanaClient({"hana_host": "localhost", "hana_port": PORT_A,
                            "hana_user": "U", "hana_ssl_validate": False,
                            "cert_hana": anker_h})
check(h.trust_pem.strip() == erg_a["pem"].strip(), "HANA: sslTrustStore gesetzt")
check(h.validate_cert is True,
      "HANA: Anker schaltet die Pruefung EIN, trotz hana_ssl_validate:false")
check(h.name_im_zert == "", "HANA: kein sslHostNameInCertificate noetig")

anker_b = sc.eintrag_bauen(dict(sc.pruefen("localhost", PORT_B)))
h2 = sap_client._HanaClient({"hana_host": "localhost", "hana_port": PORT_B,
                             "hana_user": "U", "cert_hana": anker_b})
check(anker_b["name_abweichung"] is True, "HANA: Namensabweichung erkannt")
check(h2.name_im_zert == "ganz.woanders.example",
      "HANA: sslHostNameInCertificate aus dem Zertifikat", h2.name_im_zert)

h3 = sap_client._HanaClient({"hana_host": "andere", "hana_port": PORT_A,
                             "hana_user": "U", "hana_ssl_validate": False,
                             "cert_hana": anker_h})
check(h3.trust_pem == "" and h3.validate_cert is False,
      "HANA: Anker fuer ein anderes Ziel bleibt wirkungslos")

quelle = (ROOT / "backend" / "sap_client.py").read_text(encoding="utf-8")
rumpf = quelle[quelle.index("def _connect(self):", quelle.index("_HanaClient")):]
rumpf = rumpf[:rumpf.index("def run_select")]
for feld in ("sslTrustStore", "sslHostNameInCertificate", "**extra"):
    check(feld in rumpf, f"HANA-Verbindung uebergibt {feld}")


# ═══════════════════════════════════════════════════════════════════════════
section("9. Endpunkte, Sperrliste, Oberflaeche")
# ═══════════════════════════════════════════════════════════════════════════

main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


def dependency(pfad: str, methode: str = "post") -> str:
    m = re.search(r'@app\.%s\("%s"\)\s*\nasync def [a-z_]+\(([^)]*)\)'
                  % (methode, re.escape(pfad)), main)
    return m.group(1) if m else ""


for pfad, methode, dep in (
        ("/api/sap/admin/cert/probe", "post", "require_local_auth"),
        ("/api/sap/admin/cert/trust", "post", "require_local_auth"),
        ("/api/sap/admin/cert", "delete", "require_local_auth"),
        ("/api/sap/cert/probe", "post", "require_sap_access"),
        ("/api/sap/cert/trust", "post", "require_sap_access"),
        ("/api/sap/cert", "delete", "require_sap_access")):
    args = dependency(pfad, methode)
    check(dep in args, f"{methode.upper()} {pfad} haengt an {dep}",
          args[:70] or "Route nicht gefunden")

# Der Benutzer-Zweig MUSS die Freigabeliste erzwingen – sonst ist die Pruefung
# ein Portscanner fuer jeden SAP-Freigegebenen.
probe = main[main.index('@app.post("/api/sap/cert/probe")'):]
probe = probe[:probe.index('@app.post("/api/sap/cert/trust")')]
check("host_pruefen" in probe, "Benutzer-Probe prueft die Host-Freigabe")
check("erg.pop(\"pem\"" in probe, "…und gibt das PEM nicht heraus")

adminprobe = main[main.index('@app.post("/api/sap/admin/cert/probe")'):]
adminprobe = adminprobe[:adminprobe.index('@app.post("/api/sap/admin/cert/trust")')]
check("erg.pop(\"pem\"" in adminprobe, "Admin-Probe gibt das PEM nicht heraus")

sb = (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8")
deny = sb[sb.index("_APP_DENY_REL = ("):]
deny = deny[:deny.index("\n)")]
check('"data/sap_certs"' in deny, "data/sap_certs steht in _APP_DENY_REL")

sapjs = (ROOT / "frontend" / "js" / "sap.js").read_text(encoding="utf-8")
collect = sapjs[sapjs.index("_collect: function ()"):]
collect = collect[:collect.index("save: function")]
check("cert_odata" not in collect and "cert_hana" not in collect,
      "sap.js::_collect() sendet KEINE cert_*-Felder (sonst loescht Speichern "
      "den Anker)")

certjs = (ROOT / "frontend" / "js" / "sapcert.js").read_text(encoding="utf-8")
# Fremdtext (Aussteller, Namen) darf nie per innerHTML gesetzt werden. Der
# einzige erlaubte Fall ist das Muelleimer-SVG aus JarvisIcons.
inner = re.findall(r"innerHTML\s*=\s*([^\n;]+)", certjs)
check(all("JarvisIcons" in i for i in inner),
      "sapcert.js setzt Fremdtext nie per innerHTML", str(inner))
check("JarvisIcons.trash" in certjs,
      "Loesen-Knopf traegt den Muelleimer (Symbol-Semantik)")
check("&times;" not in certjs and "'×'" not in certjs,
      "…und kein × fuer eine Loeschaktion")
check("z.fingerprint" in certjs and "letzte.fingerprint" in certjs,
      "verankert wird ueber den Fingerabdruck, nicht ueber ein PEM")
check("pem" not in re.sub(r"/\*.*?\*/", "", certjs, flags=re.S).split("function mount")[1],
      "sapcert.js sendet nie ein PEM")

for datei, marke in (("settings.html", 'id="sapcert-odata"'),
                     ("settings.html", 'id="sapcert-hana"'),
                     ("sap.html", 'id="sp-cert-odata"'),
                     ("sap.html", 'id="sp-cert-hana"')):
    txt = (ROOT / "frontend" / datei).read_text(encoding="utf-8")
    check(marke in txt, f"{datei}: Anker {marke} vorhanden")
    check(txt.index("sapcert.js") < txt.index(
        "sap_portal.js" if datei == "sap.html" else "js/sap.js?"),
        f"{datei}: sapcert.js wird vor dem Reiter-Skript geladen")

theme = (ROOT / "frontend" / "css" / "theme.css").read_text(encoding="utf-8")
check(".sapcert-box" in theme, "CSS steht in theme.css (beide Seiten laden es)")
style = (ROOT / "frontend" / "css" / "style.css").read_text(encoding="utf-8")
check(".sapcert-box" not in style, "…und NICHT zusaetzlich in style.css (Drift)")


for srv in (SRV_A, SRV_B, SRV_ALT):
    srv.shutdown()

print(f"\n{'='*60}\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
