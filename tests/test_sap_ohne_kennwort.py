#!/usr/bin/env python3
"""Waechter: persoenlicher SAP-Zugang OHNE Kennwort schickt nichts an SAP (2026-11-19).

Vorfall ECHT 2026-11-19: "Verbindung testen" zeigte die rohe HTML-Seite
"Anmeldung fehlgeschlagen" des SAP-Servers. Der persoenliche Zugang trug nach
dem Hin- und Herschalten der Kachel-Anmeldung nur noch den Benutzernamen, galt
aber weiter als vorrangig – Jarvis meldete den Benutzer mit LEEREM Kennwort an.

Zusagen:

* Ohne Kachelpflicht wird ein persoenlicher Zugang, dem das Geheimnis seiner
  AKTIVEN Anmeldeart fehlt (Basic mit Benutzer ohne Kennwort, Bearer ohne
  Token, RFC/HANA ohne Kennwort), NICHT benutzt – es gilt der Sammelzugang,
  und der Hinweis sagt, was fehlt. Auch beim Verbindungstest
  (``trotz_aussetzer=True``).
* Basic OHNE Benutzernamen geht anonym raus und bleibt unveraendert erlaubt.
* Die IdP-Anmeldung findet den kennwortlosen Zugang weiterhin
  (``idp_kennwort_ziel``) – genau fuer sie bleibt er stehen.
* Eine HTML- oder XML-Fehlerantwort von SAP wird zu einem lesbaren Satz mit
  HTTP-Status, nie zu rohem Markup.

``backend.config`` ist eine Attrappe (der echte Import schreibt die
Live-settings.json zurueck). Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.

    python3 tests/test_sap_ohne_kennwort.py
"""
import importlib.util
import json
import os
import sys
import tempfile
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


# ── Attrappe fuer backend.config VOR dem Import ─────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="sapohnekw_test_"))
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

# Gegenprobe (tests/gegen_sap_ohne_kennwort.py): sabotierte KOPIEN ueber die
# Umgebung, die Originale werden nie angefasst.
MODUL = Path(os.environ.get("SAP_OHNEKW_MODUL") or ROOT / "backend" / "sap_accounts.py")
CLIENT = Path(os.environ.get("SAP_OHNEKW_CLIENT") or ROOT / "backend" / "sap_client.py")
try:
    import backend  # noqa: F401  – Paket zuerst
    _cspec = importlib.util.spec_from_file_location("backend.sap_client", CLIENT)
    sc = importlib.util.module_from_spec(_cspec)
    sys.modules["backend.sap_client"] = sc
    _cspec.loader.exec_module(sc)
    _spec = importlib.util.spec_from_file_location("backend.sap_accounts", MODUL)
    sa = importlib.util.module_from_spec(_spec)
    sys.modules["backend.sap_accounts"] = sa
    _spec.loader.exec_module(sa)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: sap_client/sap_accounts nicht importierbar: {e}")
    sys.exit(2)

sa.DATA_DIR = TMP / "data"
sa.KONTEN_DATEI = TMP / "data" / "sap_accounts.json"
sa.SCHLUESSEL_DATEI = TMP / "data" / ".sapkey"
for pfad in (sa.KONTEN_DATEI, sa.SCHLUESSEL_DATEI):
    if not str(pfad).startswith(str(TMP)):
        print(f"SANDKASTEN VERLETZT: {pfad}")
        sys.exit(2)

BASIS = "https://s4.firma.de/sap/opu/odata"
SAMMEL = dict(connection_type="odata", odata_base_url=BASIS, username="SAMMEL",
              password="sammel-kennwort", allowed_hosts="firma.de")
_skill_states["sap"]["config"] = dict(SAMMEL)
ZUGANG = {"connection_type": "odata", "odata_base_url": BASIS,
          "auth_kind": "basic", "username": "MUSTER"}
KENNWORT = "Geheim-Probe-4711"
U = "m.mustermann"


def zugang_neu(un: str, felder: dict) -> None:
    """Zugang anlegen (ohne Kachelpflicht: Kennwort verschluesselt auf Platte)."""
    sa.speichern(un, felder)


def ohne_geheimnisse(un: str) -> None:
    """Wie nach dem Hin- und Herschalten der Kachel-Anmeldung: nur die
    Geheimfelder dieses Zugangs entfernen, der Zugang bleibt."""
    alle = json.loads(sa.KONTEN_DATEI.read_text(encoding="utf-8"))
    for f in sa.GEHEIMFELDER:
        alle[un].pop(f + "_enc", None)
    sa._speichern(alle)


# ═══════════════════════════════════════════════════════════════════════════
section("0. Positivkontrolle: Zugang MIT Kennwort gilt persoenlich")
# ═══════════════════════════════════════════════════════════════════════════
if sa.kachel_pflicht():
    print("ABBRUCH: Kachelpflicht ist an – der Waechter misst den Weg OHNE sie")
    sys.exit(2)
try:
    zugang_neu(U, dict(ZUGANG, password=KENNWORT))
except sa.SapKontoFehler as e:
    print(f"ABBRUCH: Zugang laesst sich nicht anlegen ({e})")
    sys.exit(2)
z = sa.aufloesen(U, trotz_aussetzer=True)
if z["quelle"] != sa.QUELLE_PERSOENLICH or z["client"].cfg.get("password") != KENNWORT:
    print("ABBRUCH: Zugang mit Kennwort gilt nicht persoenlich – Messaufbau kaputt",
          z["quelle"])
    sys.exit(2)
if not sa.sammel_nutzbar():
    print("ABBRUCH: Sammelzugang gilt nicht als nutzbar – der Rueckfall waere unmessbar")
    sys.exit(2)
check(True, "Positivkontrolle: Zugang mit Kennwort ist persoenlich")

# ═══════════════════════════════════════════════════════════════════════════
section("1. Basic mit Benutzer, ohne Kennwort: Sammelzugang mit Hinweis")
# ═══════════════════════════════════════════════════════════════════════════
ohne_geheimnisse(U)
roh = json.loads(sa.KONTEN_DATEI.read_text(encoding="utf-8"))
check(U in roh and roh[U].get("username") == "MUSTER"
      and not any(k.endswith("_enc") for k in roh[U]),
      "Aufbau: Zugang steht, Benutzername da, kein Geheimnis")
for trotz in (False, True):
    z = sa.aufloesen(U, trotz_aussetzer=trotz)
    check(z["quelle"] == sa.QUELLE_SAMMEL,
          f"trotz_aussetzer={trotz}: Quelle ist der Sammelzugang", z["quelle"])
    check(z["client"].cfg.get("username") == "SAMMEL"
          and z["client"].cfg.get("password") == SAMMEL["password"],
          f"trotz_aussetzer={trotz}: Client traegt die Sammel-Anmeldung, nie MUSTER/leer",
          str({k: z["client"].cfg.get(k) for k in ("username",)}))
    check(z["hinweis"] == sa.KEIN_KENNWORT_TEXT,
          f"trotz_aussetzer={trotz}: Hinweis sagt, dass das Kennwort fehlt", z["hinweis"])
check("Mein SAP-Zugang" in sa.KEIN_KENNWORT_TEXT and "Kennwort" in sa.KEIN_KENNWORT_TEXT,
      "Hinweis nennt den Weg ('Mein SAP-Zugang')")

# ═══════════════════════════════════════════════════════════════════════════
section("2. Kennwort wieder eingetragen: wieder persoenlich")
# ═══════════════════════════════════════════════════════════════════════════
sa.speichern(U, {"password": KENNWORT})
z = sa.aufloesen(U, trotz_aussetzer=True)
check(z["quelle"] == sa.QUELLE_PERSOENLICH and z["client"].cfg.get("password") == KENNWORT,
      "nach dem Eintragen gilt der persoenliche Zugang", z["quelle"])

# ═══════════════════════════════════════════════════════════════════════════
section("3. Bearer ohne Token / Basic ohne Benutzer (anonym)")
# ═══════════════════════════════════════════════════════════════════════════
zugang_neu("t.token", dict(ZUGANG, auth_kind="bearer", username="", bearer_token="tok-1"))
check(sa.aufloesen("t.token")["quelle"] == sa.QUELLE_PERSOENLICH,
      "Positivkontrolle: Bearer MIT Token ist persoenlich")
ohne_geheimnisse("t.token")
z = sa.aufloesen("t.token", trotz_aussetzer=True)
check(z["quelle"] == sa.QUELLE_SAMMEL and z["hinweis"] == sa.KEIN_KENNWORT_TEXT,
      "Bearer OHNE Token: Sammelzugang mit Hinweis", z["quelle"])
zugang_neu("a.anonym", dict(ZUGANG, username=""))
z = sa.aufloesen("a.anonym", trotz_aussetzer=True)
check(z["quelle"] == sa.QUELLE_PERSOENLICH and not z["hinweis"],
      "Basic OHNE Benutzer (anonym) bleibt persoenlich – kein Fehlversuch an einem Benutzer",
      z["quelle"])

# ═══════════════════════════════════════════════════════════════════════════
section("4. RFC ohne Kennwort")
# ═══════════════════════════════════════════════════════════════════════════
RFC = {"connection_type": "rfc", "rfc_ashost": "sap.firma.de", "rfc_sysnr": "00",
       "rfc_client": "100", "rfc_user": "MUSTER"}
try:
    zugang_neu("r.rfc", dict(RFC, rfc_password="rfc-kw"))
except sa.SapKontoFehler as e:
    print(f"ABBRUCH: RFC-Zugang laesst sich nicht anlegen ({e})")
    sys.exit(2)
z = sa.aufloesen("r.rfc", trotz_aussetzer=True)
if z["quelle"] != sa.QUELLE_PERSOENLICH:
    print("ABBRUCH: RFC-Zugang MIT Kennwort gilt nicht persoenlich – Messaufbau kaputt",
          z["quelle"], z["hinweis"])
    sys.exit(2)
ohne_geheimnisse("r.rfc")
z = sa.aufloesen("r.rfc", trotz_aussetzer=True)
check(z["quelle"] == sa.QUELLE_SAMMEL and z["hinweis"] == sa.KEIN_KENNWORT_TEXT,
      "RFC OHNE Kennwort: Sammelzugang mit Hinweis (Geheimnis der AKTIVEN Art)", z["quelle"])

# ═══════════════════════════════════════════════════════════════════════════
section("5. Die IdP-Anmeldung findet den kennwortlosen Zugang weiterhin")
# ═══════════════════════════════════════════════════════════════════════════
ohne_geheimnisse(U)
ziel = sa.idp_kennwort_ziel(U, "aus-dem-idp")
check(ziel.get("feld") == "password" and ziel.get("benutzer") == "MUSTER",
      "idp_kennwort_ziel liefert Feld und Benutzer", str(ziel))

# ═══════════════════════════════════════════════════════════════════════════
section("6. Fehlertexte aus HTML/XML-Antworten")
# ═══════════════════════════════════════════════════════════════════════════
SAP_HTML = ('<html><head><meta http-equiv="content-type" content="text/html; '
            'charset=windows-1252"><title>Anmeldung fehlgeschlagen</title><style>'
            'body { background: #ffffff; text-align: center; }.content { display: table; }'
            '</style></head><body><div class="content"><h1>Anmeldung fehlgeschlagen</h1>'
            '</div></body></html>')
t = sc.http_fehlertext(401, SAP_HTML)
check("Anmeldung fehlgeschlagen" in t and "401" in t and "<" not in t and "{" not in t,
      "SAP-Anmeldeseite -> Titel + HTTP-Status, kein Markup/CSS", t)
t = sc.http_fehlertext(500, "<html><body><h2>Interner &amp; Fehler</h2></body></html>")
check(t.startswith("SAP meldet: Interner & Fehler") and "500" in t,
      "HTML ohne Titel -> erste Ueberschrift, Entitaeten aufgeloest", t)
t = sc.http_fehlertext(403, "<html><body><p>x</p></body></html>")
check("<" not in t and "403" in t, "HTML ohne Titel/Ueberschrift -> kein Markup", t)
XML = ('<?xml version="1.0" encoding="utf-8"?><error xmlns="http://schemas.microsoft.com/'
       'ado/2007/08/dataservices/metadata"><code>/IWFND/MED/170</code><message xml:lang="de">'
       'Kein Service gefunden</message></error>')
t = sc.http_fehlertext(404, XML)
check(t.startswith("Kein Service gefunden") and "404" in t and "<" not in t,
      "Gateway-XML -> <message> + HTTP-Status", t)
check(sc.http_fehlertext(502, "Bad Gateway") == "Bad Gateway",
      "Klartext bleibt Klartext")
check(sc.http_fehlertext(401, "") == "HTTP 401", "leere Antwort -> HTTP-Status")

# Der echte Weg: _ODataClient.get mit einer Attrappe fuer requests.get
# (echte Antwortform: status_code, text, url, json() wirft bei HTML).


class _Antwort:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text
        self.url = BASIS + "/x"

    def json(self):
        raise ValueError("kein JSON")


_echt_get = sc.requests.get
try:
    sc.requests.get = lambda *a, **k: _Antwort(401, SAP_HTML)
    od = sc._ODataClient(dict(SAMMEL))
    for name, aufruf in (("get", lambda: od.get("svc/Set")),
                         ("get_metadata_xml", lambda: od.get_metadata_xml("svc"))):
        try:
            aufruf()
            check(False, f"{name}: 401 wirft SapError")
        except sc.SapError as e:
            check(e.status == 401 and "Anmeldung fehlgeschlagen" in str(e)
                  and "<html" not in str(e).lower(),
                  f"{name}: SapError lesbar, ohne HTML", str(e)[:120])
finally:
    sc.requests.get = _echt_get

print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
