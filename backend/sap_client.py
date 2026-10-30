"""Geteilter SAP-Client (Read-Only).

Wird sowohl vom Skill (``skills/sap/main.py``) als auch von den
``/api/sap/*``-Endpoints (``backend/main.py``, fuer den SAP-Reiter) genutzt –
damit es nur EINE Implementierung der Auth-/Request-Logik gibt (analog
``confluence_client.py``).

Deckt die drei ueblichen Lese-Schnittstellen aktueller SAP-Systeme ab:

* **OData** (V2/V4) – der moderne REST-Zugang von S/4HANA (On-Prem & Cloud),
  SAP Gateway/NetWeaver und BW/4HANA. Das ist zugleich die Schnittstelle, ueber
  die Power BI / Tableau / Qlik ("OData Feed") lesen. Nur GET-Requests.
* **HANA SQL** (``hdbcli``) – direkter, lesender SQL-Zugriff auf SAP HANA,
  HANA Cloud und SAP Datasphere. Erfuellt "direkte SQL-Abfragen". Es sind
  ausschliesslich SELECT/WITH-Anweisungen erlaubt (``assert_read_only_sql``).
* **RFC** (``pyrfc`` + NetWeaver RFC SDK, optional) – klassischer Zugang zu
  ECC 6.0 / NetWeaver ueber lesende Funktionsbausteine (Standard: nur
  ``RFC_READ_TABLE``). ``pyrfc`` ist von SAP nicht mehr gepflegt und braucht das
  native SDK; fehlt es, meldet das Tool das sauber statt zu crashen.

**Read-Only ist hart durchgesetzt**, unabhaengig von der Konfiguration:
OData nur GET, SQL nur SELECT/WITH, RFC nur Whitelist-Bausteine. Das Feld
``read_only`` dokumentiert die Absicht zusaetzlich in der UI.

Alle Netzwerk-/DB-Methoden sind synchron. Aufrufer im async-Kontext muessen sie
via ``asyncio.to_thread`` ausfuehren, um den Event-Loop nicht zu blockieren.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlsplit, urlunsplit

import requests

# Standard-Timeout fuer HTTP-Aufrufe (OData). DB-Timeouts steuert hdbcli selbst.
_HTTP_TIMEOUT = 30

# Gateway-Katalog (V2), relativ zur OData-Basis-URL (…/sap/opu/odata).
KATALOG_PFAD = "iwfnd/catalogservice;v=2/ServiceCollection"
# Obergrenze fuer das Durchzaehlen, wenn der Server keinen $inlinecount liefert.
# Gleich der Kappung in ``catalog_services`` – darueber waere die Zahl ohnehin
# nicht mehr genau, und der Bericht sagt dann "mindestens".
KATALOG_ZAEHL_MAX = 2000


def _anzeige_url(url: str) -> str:
    """Adresse fuer einen Bericht, der an Dritte geht (SAP-Administrator).

    Prozent-Kodierung aufgeloest (``$top`` statt ``%24top``) und eine
    Anmeldung in der Adresse (``benutzer:kennwort@host``) entfernt – sie waere
    sonst im kopierten Bericht. Kennwort und Token stehen bei uns nie in der
    Adresse (Basic-Auth bzw. Kopfzeile), die Basis-URL tippt aber der Benutzer."""
    if not url:
        return ""
    try:
        t = urlsplit(url)
        netloc = t.netloc.rsplit("@", 1)[-1]
        return unquote(urlunsplit((t.scheme, netloc, t.path, t.query, t.fragment)))
    except ValueError:
        return ""

# Read-only Funktionsbausteine, die per RFC aufgerufen werden duerfen.
_RFC_READONLY_WHITELIST = {
    "RFC_READ_TABLE",
    "/SAPDS/RFC_READ_TABLE2",
    "RFC_GET_TABLE_ENTRIES",
    "DDIF_FIELDINFO_GET",
    "RFC_GET_FUNCTION_INTERFACE",
    "RFC_FUNCTION_SEARCH",
    "RFCPING",
}

# SQL-Schluesselwoerter, die eine Anweisung schreibend/steuernd machen. Wird als
# ganzes Wort geprueft; Auftreten irgendwo => abgelehnt.
_SQL_FORBIDDEN = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "MERGE", "UPSERT", "REPLACE", "GRANT", "REVOKE", "CALL", "EXEC",
    "EXECUTE", "RENAME", "COMMENT", "SET", "IMPORT", "EXPORT", "LOAD",
    "UNLOAD", "BACKUP", "RESTORE", "COMMIT", "ROLLBACK", "SAVEPOINT",
    "LOCK", "UNLOCK", "REFRESH",
}


def get_sap_config() -> dict:
    """Liest die in der Skill-Config hinterlegten SAP-Werte."""
    try:
        from backend.config import config
        return config.get_skill_states().get("sap", {}).get("config", {}) or {}
    except Exception:
        return {}


class SapError(Exception):
    """Fehler bei einer SAP-Anfrage (mit optionalem HTTP-/DB-Status)."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


# ── Read-Only-Wache ──────────────────────────────────────────────────
def _strip_sql_comments(sql: str) -> str:
    """Entfernt -- Zeilen- und /* */ Blockkommentare (fuer die Pruefung)."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _strip_string_literals(sql: str) -> str:
    """Ersetzt '...'-Stringliterale (mit '' als Escape) und "..."-Bezeichner
    durch Leerraum – damit die Read-Only-Pruefung Schluesselwoerter/Semikolons
    INNERHALB von Werten (z.B. ``WHERE STATUS = 'SET'`` oder ``= 'a;b'``) nicht
    faelschlich als Verstoss wertet. Nur fuer die PRUEFUNG; ausgefuehrt wird das
    Original."""
    sql = re.sub(r"'(?:''|[^'])*'", " ", sql)
    sql = re.sub(r'"(?:""|[^"])*"', " ", sql)
    return sql


def assert_read_only_sql(sql: str) -> str:
    """Wirft ``SapError``, wenn ``sql`` keine reine Lese-Abfrage ist.

    Erlaubt genau EINE Anweisung, die mit ``SELECT`` oder ``WITH`` (CTE)
    beginnt; verbietet ein zweites Statement (``;`` gefolgt von Inhalt) und
    jedes schreibende/steuernde Schluesselwort als ganzes Wort. Stringliterale
    und Quoted Identifiers werden fuer die Pruefung ausgeblendet, damit ein
    Schluesselwort oder ``;`` als DATENWERT nicht faelschlich abgelehnt wird.
    Gibt die getrimmte Original-Query zurueck (ohne abschliessendes Semikolon)."""
    if not sql or not sql.strip():
        raise SapError(0, "Leere SQL-Abfrage.")
    core = _strip_sql_comments(sql).strip().rstrip(";").strip()
    if not core:
        raise SapError(0, "Leere SQL-Abfrage.")
    scrubbed = _strip_string_literals(core)  # nur fuer die Pruefung
    # Mehrere Anweisungen? (Semikolon ausserhalb von Literalen)
    if ";" in scrubbed:
        raise SapError(0, "Nur eine einzelne Abfrage erlaubt (kein ';').")
    first = re.match(r"[a-zA-Z_]+", scrubbed.strip())
    if not first or first.group(0).upper() not in ("SELECT", "WITH"):
        raise SapError(0, "Nur lesende Abfragen erlaubt (muss mit SELECT oder WITH beginnen).")
    words = set(w.upper() for w in re.findall(r"[A-Za-z_]+", scrubbed))
    bad = words & _SQL_FORBIDDEN
    if bad:
        raise SapError(0, "Verbotenes Schluesselwort in Read-Only-Modus: %s"
                       % ", ".join(sorted(bad)))
    return core


# ── Verankertes Serverzertifikat ─────────────────────────────────────
#
# Der Anker kommt aus derselben Konfiguration wie alles andere: `cert_odata`
# bzw. `cert_hana` (Admin-Anker aus der Skill-Config, persoenlicher Anker legt
# `sap_accounts._cfg_aus_zugang` darueber). Fehlt das Modul oder passt der Anker
# nicht zum Ziel, bleibt es exakt beim bisherigen Verhalten.

def _verify_odata(cfg: dict, basis: str):
    """``verify``-Wert fuer ``requests``: Pfad zum Anker-Buendel, sonst bool."""
    if not cfg.get("cert_odata"):
        return bool(cfg.get("verify_ssl", True))
    try:
        from backend import sap_cert
        host, port = sap_cert.ziel_bestimmen("odata", {"url": basis})
        return sap_cert.verify_fuer(cfg, "cert_odata", host, port)
    except Exception:  # noqa: BLE001
        # Laesst sich das Ziel gar nicht bestimmen (kaputte URL), ist auch nicht
        # entscheidbar, ob der Anker gilt -> es bleibt beim eingestellten Wert.
        # Ein unbrauchbarer Anker AM ZIEL wird dagegen in `verify_fuer`
        # abgefangen und dort auf die volle Pruefung gehoben, nie auf "keine".
        return bool(cfg.get("verify_ssl", True))


# ── OData (V2/V4) ────────────────────────────────────────────────────
class _ODataClient:
    """Lesender OData-Zugriff (nur GET) fuer S/4HANA, Gateway, BW/4HANA."""

    def __init__(self, cfg: dict):
        self.base = (cfg.get("odata_base_url") or "").strip().rstrip("/")
        self.default_service = (cfg.get("odata_service") or "").strip().strip("/")
        self.auth_kind = (cfg.get("auth_kind") or "basic").strip().lower()
        self.user = (cfg.get("username") or "").strip()
        self.password = cfg.get("password") or ""
        self.bearer = (cfg.get("bearer_token") or "").strip()
        # Verankertes Serverzertifikat (backend/sap_cert.py) hat Vorrang: dann ist
        # `verify` der Pfad zu einem Buendel mit GENAU diesem Zertifikat. Die
        # Ziel-Pruefung (Host/Port) sitzt bewusst HIER und nicht beim Aufrufer –
        # so kann kein Aufrufer sie umgehen, und Sammelzugang wie persoenlicher
        # Zugang teilen sich dieselbe Entscheidung.
        self.verify = _verify_odata(cfg, self.base)
        self.sap_client = (cfg.get("sap_client") or "").strip()  # Mandant (sap-client)
        # Letzte HTTP-Anfrage {adresse, http_status, dauer_ms} – fuer den
        # Bericht des Verbindungstests, auch im Fehlerfall.
        self.letzte: dict | None = None

    @property
    def configured(self) -> bool:
        return bool(self.base)

    @property
    def anmeldeart(self) -> str:
        """Welche Anmeldung tatsaechlich mitgeht: ``basic``, ``bearer`` oder
        ``keine``. EINE Entscheidung fuer Anfrage UND Bericht – sonst nennt der
        Bericht eine Anmeldeart, die gar nicht gesendet wurde."""
        if self.auth_kind == "basic" and self.user:
            return "basic"
        if self.auth_kind == "bearer" and self.bearer:
            return "bearer"
        return "keine"

    def _auth(self):
        if self.anmeldeart == "basic":
            return (self.user, self.password)
        return None

    def _headers(self) -> dict:
        h = {"Accept": "application/json"}
        if self.anmeldeart == "bearer":
            h["Authorization"] = "Bearer " + self.bearer
        return h

    def _merke(self, url: str, status: int, t0: float) -> None:
        self.letzte = {"adresse": _anzeige_url(url), "http_status": int(status or 0),
                       "dauer_ms": int((time.monotonic() - t0) * 1000)}

    @staticmethod
    def _url_mit(url: str, params: dict) -> str:
        """Volle Adresse samt Parametern fuer den Fall ohne Antwort."""
        try:
            return requests.Request("GET", url, params=params).prepare().url or url
        except Exception:  # noqa: BLE001
            return url

    def _url(self, path: str) -> str:
        path = (path or "").strip()
        if path.lower().startswith(("http://", "https://")):
            return path
        return self.base + "/" + path.lstrip("/")

    def get(self, path: str, params: dict | None = None) -> dict:
        """Fuehrt einen GET aus und liefert JSON (oder wirft ``SapError``).
        SCHREIBZUGRIFFE SIND NICHT MOEGLICH – hier gibt es nur GET."""
        if not self.configured:
            raise SapError(0, "OData ist nicht konfiguriert (Basis-URL fehlt).")
        p = dict(params or {})
        p.setdefault("$format", "json")
        if self.sap_client:
            p.setdefault("sap-client", self.sap_client)
        url = self._url(path)
        t0 = time.monotonic()
        try:
            r = requests.get(url, params=p, headers=self._headers(),
                             auth=self._auth(), verify=self.verify, timeout=_HTTP_TIMEOUT)
        except requests.RequestException as e:
            self._merke(self._url_mit(url, p), 0, t0)
            raise SapError(0, "Netzwerkfehler: %s" % e)
        self._merke(r.url, r.status_code, t0)
        if r.status_code >= 400:
            msg = ""
            try:
                j = r.json()
                err = j.get("error") if isinstance(j, dict) else None
                if isinstance(err, dict):
                    m = err.get("message")
                    msg = m.get("value") if isinstance(m, dict) else (m or "")
            except ValueError:
                msg = (r.text or "")[:300]
            raise SapError(r.status_code, msg or ("HTTP %s" % r.status_code))
        try:
            return r.json()
        except ValueError:
            return {}

    def get_metadata_xml(self, service: str) -> str:
        """Roh-$metadata (XML) eines Service – fuer Entity-Set-Auflistung."""
        if not self.configured:
            raise SapError(0, "OData ist nicht konfiguriert (Basis-URL fehlt).")
        url = self._url((service or self.default_service).strip("/") + "/$metadata")
        p = {}
        if self.sap_client:
            p["sap-client"] = self.sap_client
        h = self._headers()
        h["Accept"] = "application/xml"
        t0 = time.monotonic()
        try:
            r = requests.get(url, params=p, headers=h,
                             auth=self._auth(), verify=self.verify, timeout=_HTTP_TIMEOUT)
        except requests.RequestException as e:
            self._merke(self._url_mit(url, p), 0, t0)
            raise SapError(0, "Netzwerkfehler: %s" % e)
        self._merke(r.url, r.status_code, t0)
        if r.status_code >= 400:
            raise SapError(r.status_code, (r.text or "")[:300] or ("HTTP %s" % r.status_code))
        return r.text

    def entity_sets(self, service: str = "") -> list[str]:
        """Liste der EntitySets eines Service (aus dem $metadata-XML geparst)."""
        xml = self.get_metadata_xml(service)
        names: list[str] = []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            raise SapError(0, "Konnte $metadata nicht parsen: %s" % e)
        for el in root.iter():
            if el.tag.rsplit("}", 1)[-1] == "EntitySet":
                n = el.get("Name")
                if n:
                    names.append(n)
        return sorted(set(names))

    @staticmethod
    def rows_from(payload: dict) -> list[dict]:
        """Extrahiert die Datenzeilen aus V2- (``d.results``/``d``) oder
        V4-Antworten (``value``)."""
        if not isinstance(payload, dict):
            return []
        if "value" in payload and isinstance(payload["value"], list):  # V4
            return payload["value"]
        d = payload.get("d")
        if isinstance(d, dict):
            if isinstance(d.get("results"), list):
                return d["results"]
            return [d]
        if isinstance(d, list):
            return d
        return []

    def query(self, entity_set: str, service: str = "", *, select: str = "",
              filter: str = "", top: int = 50, skip: int = 0, orderby: str = "",
              expand: str = "") -> list[dict]:
        """Liest Zeilen eines EntitySet (System-Query-Optionen $select/$filter/…)."""
        svc = (service or self.default_service).strip("/")
        if not entity_set:
            raise SapError(0, "entity_set fehlt.")
        path = (svc + "/" + entity_set.strip("/")) if svc else entity_set.strip("/")
        params: dict = {"$top": max(1, min(int(top or 50), 5000))}
        if skip:
            params["$skip"] = max(0, int(skip))
        if select:
            params["$select"] = select
        if filter:
            params["$filter"] = filter
        if orderby:
            params["$orderby"] = orderby
        if expand:
            params["$expand"] = expand
        return self.rows_from(self.get(path, params))

    def catalog_services(self, limit: int = 200) -> list[dict]:
        """Listet verfuegbare OData-Services ueber den Gateway-Katalog (V2).
        Faellt auf einen leeren Katalog zurueck, wenn nicht erreichbar."""
        data = self.get(KATALOG_PFAD,
                        {"$top": max(1, min(int(limit or 200), KATALOG_ZAEHL_MAX))})
        out = []
        for r in self.rows_from(data):
            out.append({
                "id": r.get("ID") or r.get("TechnicalServiceName") or r.get("Title"),
                "title": r.get("Title") or r.get("Description") or "",
                "url": r.get("ServiceUrl") or "",
                "version": r.get("TechnicalServiceVersion") or "",
            })
        return out

    def catalog_count(self) -> tuple[int, bool]:
        """Zahl der Services im Gateway-Katalog als ``(anzahl, genau)``.

        Zuerst ueber ``$inlinecount`` – eine Zeile Nutzlast, der Server zaehlt.
        Liefert er keinen Zaehler (oder lehnt den Parameter mit 400 ab), wird
        bis ``KATALOG_ZAEHL_MAX`` gelistet; genau ist die Zahl dann nur
        unterhalb dieser Grenze. Alle anderen Fehler (401/403/404/5xx) gehen
        unveraendert an den Aufrufer."""
        data = None
        try:
            data = self.get(KATALOG_PFAD, {"$top": 1, "$inlinecount": "allpages"})
        except SapError as e:
            if e.status != 400:
                raise
        d = data.get("d") if isinstance(data, dict) else None
        n = str(d.get("__count") or "").strip() if isinstance(d, dict) else ""
        if n.isdigit():
            return int(n), True
        svcs = self.catalog_services(limit=KATALOG_ZAEHL_MAX)
        return len(svcs), len(svcs) < KATALOG_ZAEHL_MAX


# ── HANA SQL (hdbcli) ────────────────────────────────────────────────
class _HanaClient:
    """Lesender SQL-Zugriff auf SAP HANA / HANA Cloud / Datasphere."""

    def __init__(self, cfg: dict):
        self.host = (cfg.get("hana_host") or "").strip()
        try:
            self.port = int(cfg.get("hana_port") or 443)
        except (TypeError, ValueError):
            self.port = 443
        self.user = (cfg.get("hana_user") or "").strip()
        self.password = cfg.get("hana_password") or ""
        self.encrypt = bool(cfg.get("hana_encrypt", True))
        # Zertifikatspruefung standardmaessig AN (verhindert MITM). Nur fuer
        # HANA-Systeme mit selbstsigniertem Zertifikat bewusst abschaltbar.
        self.validate_cert = bool(cfg.get("hana_ssl_validate", True))
        self.schema = (cfg.get("hana_schema") or "").strip()
        # Verankertes Zertifikat (siehe backend/sap_cert.py). Ein passender Anker
        # SCHALTET DIE PRUEFUNG EIN, auch wenn `hana_ssl_validate` aus steht –
        # verankern ist strenger, nicht schwaecher.
        self.trust_pem = ""        # -> sslTrustStore
        self.name_im_zert = ""     # -> sslHostNameInCertificate
        anker = cfg.get("cert_hana")
        if anker:
            try:
                from backend import sap_cert
                if sap_cert.passt(anker, self.host, self.port):
                    self.trust_pem = anker.get("pem") or ""
                    self.validate_cert = True
                    # Nur HANA kann einen abweichenden Namen ueberbruecken; bei
                    # OData gibt es dafuer keinen Schalter (dort sagt die
                    # Pruefung dem Administrator, dass er die Adresse anpassen
                    # muss). Ohne dieses Feld scheiterte ein Zertifikat, das auf
                    # den FQDN lautet, waehrend im Formular eine IP steht.
                    if anker.get("name_abweichung"):
                        self.name_im_zert = (anker.get("inhaber") or "").strip()
            except Exception as e:  # noqa: BLE001
                print(f"[SAP] HANA-Anker unbrauchbar ({e}) – normale Pruefung",
                      flush=True)
                self.trust_pem = ""
                self.validate_cert = True

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user)

    def _connect(self):
        try:
            from hdbcli import dbapi
        except ImportError:
            raise SapError(0, "hdbcli ist nicht installiert. Bitte den SAP-Skill "
                              "(neu) aktivieren, damit die Abhaengigkeit installiert wird.")
        # `sslTrustStore` nimmt das Zertifikat als PEM entgegen (OpenSSL-Provider,
        # Standard unter Linux). Nur mitgeben, wenn wirklich ein Anker gilt –
        # ein leerer Wert wuerde die Vorgabe des Treibers ueberschreiben.
        # ⚠ NICHT end-to-end geprueft: auf DEV gibt es kein HANA. Belegt ist,
        # dass genau diese Parameter zusammengebaut und uebergeben werden.
        extra = {}
        if self.trust_pem:
            extra["sslTrustStore"] = self.trust_pem
            if self.name_im_zert:
                extra["sslHostNameInCertificate"] = self.name_im_zert
        try:
            conn = dbapi.connect(
                address=self.host, port=self.port,
                user=self.user, password=self.password,
                encrypt=self.encrypt,
                sslValidateCertificate=self.validate_cert,
                autocommit=False,  # nichts wird jemals committed
                **extra,
            )
        except Exception as e:  # dbapi.Error u.a.
            raise SapError(0, "HANA-Verbindung fehlgeschlagen: %s" % e)
        return conn

    def run_select(self, sql: str, max_rows: int = 500) -> dict:
        """Fuehrt eine (garantiert lesende) Abfrage aus und liefert
        ``{columns, rows, truncated}``. Rollt am Ende zurueck – nie ein Commit."""
        core = assert_read_only_sql(sql)
        max_rows = max(1, min(int(max_rows or 500), 10000))
        conn = self._connect()
        try:
            cur = conn.cursor()
            try:
                if self.schema:
                    try:
                        cur.execute("SET SCHEMA %s" % _quote_ident(self.schema))
                    except Exception:
                        pass  # Schema optional – bei Fehler ignorieren
                cur.execute(core)
                cols = [d[0] for d in (cur.description or [])]
                fetched = cur.fetchmany(max_rows + 1)
                truncated = len(fetched) > max_rows
                rows = [_row_to_dict(cols, r) for r in fetched[:max_rows]]
                return {"columns": cols, "rows": rows, "truncated": truncated}
            finally:
                cur.close()
        finally:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def list_tables(self, schema: str = "", limit: int = 200) -> list[dict]:
        """Tabellen und Views eines Schemas (aus SYS-Katalog)."""
        schema = (schema or self.schema).strip()
        limit = max(1, min(int(limit or 200), 5000))
        where = ""
        if schema:
            where = "WHERE SCHEMA_NAME = '%s'" % schema.replace("'", "''")
        sql = ("SELECT SCHEMA_NAME, TABLE_NAME AS OBJECT_NAME, 'TABLE' AS OBJECT_TYPE "
               "FROM SYS.TABLES %s "
               "UNION ALL "
               "SELECT SCHEMA_NAME, VIEW_NAME AS OBJECT_NAME, 'VIEW' AS OBJECT_TYPE "
               "FROM SYS.VIEWS %s "
               "ORDER BY OBJECT_NAME LIMIT %d" % (where, where, limit))
        res = self.run_select(sql, max_rows=limit)
        return res["rows"]

    def describe(self, table: str, schema: str = "") -> list[dict]:
        """Spalten einer Tabelle/View mit Typ."""
        schema = (schema or self.schema).strip()
        table = table.strip()
        if not table:
            raise SapError(0, "Tabellenname fehlt.")
        cond = "TABLE_NAME = '%s'" % table.replace("'", "''")
        if schema:
            cond += " AND SCHEMA_NAME = '%s'" % schema.replace("'", "''")
        sql = ("SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH, SCALE, IS_NULLABLE, POSITION "
               "FROM SYS.TABLE_COLUMNS WHERE %s "
               "UNION ALL "
               "SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH, SCALE, IS_NULLABLE, POSITION "
               "FROM SYS.VIEW_COLUMNS WHERE %s "
               "ORDER BY POSITION" % (cond, cond))
        return self.run_select(sql, max_rows=1000)["rows"]

    def test(self) -> str:
        res = self.run_select("SELECT CURRENT_USER, DATABASE_NAME FROM SYS.DUMMY "
                              "CROSS JOIN SYS.M_DATABASE", max_rows=1)
        row = (res["rows"] or [{}])[0]
        return "%s @ %s" % (row.get("CURRENT_USER", "?"), row.get("DATABASE_NAME", "?"))


# ── RFC (pyrfc, optional) ────────────────────────────────────────────
class _RfcClient:
    """Lesender RFC-Zugriff (nur Whitelist-Bausteine) fuer ECC/NetWeaver."""

    def __init__(self, cfg: dict):
        self.params = {
            "ashost": (cfg.get("rfc_ashost") or "").strip(),
            "sysnr": (cfg.get("rfc_sysnr") or "").strip(),
            "client": (cfg.get("rfc_client") or "").strip(),
            "user": (cfg.get("rfc_user") or "").strip(),
            "passwd": cfg.get("rfc_password") or "",
            "lang": (cfg.get("rfc_lang") or "EN").strip(),
        }

    @property
    def configured(self) -> bool:
        p = self.params
        return bool(p["ashost"] and p["sysnr"] and p["client"] and p["user"])

    def _connect(self):
        try:
            from pyrfc import Connection
        except ImportError:
            raise SapError(0, "pyrfc/NetWeaver-RFC-SDK ist nicht installiert. RFC ist "
                              "optional; nutze OData oder HANA-SQL, oder installiere das "
                              "SAP NW RFC SDK und pyrfc auf dem Server.")
        try:
            return Connection(**{k: v for k, v in self.params.items() if v})
        except Exception as e:
            raise SapError(0, "RFC-Verbindung fehlgeschlagen: %s" % e)

    def call(self, func: str, **kw) -> dict:
        func = (func or "").strip().upper()
        if func not in _RFC_READONLY_WHITELIST:
            raise SapError(0, "RFC-Baustein '%s' ist im Read-Only-Modus nicht "
                           "freigegeben. Erlaubt: %s"
                           % (func, ", ".join(sorted(_RFC_READONLY_WHITELIST))))
        conn = self._connect()
        try:
            return conn.call(func, **kw)
        except Exception as e:
            raise SapError(0, "RFC-Aufruf %s fehlgeschlagen: %s" % (func, e))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def read_table(self, table: str, *, fields: list | None = None,
                   where: str = "", max_rows: int = 100) -> dict:
        """RFC_READ_TABLE (klassischer lesender Tabellenzugriff)."""
        table = (table or "").strip().upper()
        if not table:
            raise SapError(0, "Tabellenname fehlt.")
        options = []
        if where:
            # RFC_READ_TABLE erwartet Zeilen <= 72 Zeichen – lange WHERE aufteilen
            w = where.strip()
            while w:
                options.append({"TEXT": w[:72]})
                w = w[72:]
        fld = [{"FIELDNAME": f.strip().upper()} for f in (fields or []) if f and f.strip()]
        res = self.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                        OPTIONS=options, FIELDS=fld,
                        ROWCOUNT=max(1, min(int(max_rows or 100), 5000)))
        cols = [f.get("FIELDNAME") for f in res.get("FIELDS", [])]
        rows = []
        for entry in res.get("DATA", []):
            vals = [v.strip() for v in (entry.get("WA", "") or "").split("|")]
            rows.append(dict(zip(cols, vals)))
        return {"columns": cols, "rows": rows}


def _quote_ident(name: str) -> str:
    return '"%s"' % name.replace('"', '""')


def _row_to_dict(cols: list, row) -> dict:
    out = {}
    for i, c in enumerate(cols):
        v = row[i] if i < len(row) else None
        # HANA liefert Decimal/bytes/datetime – auf JSON-serialisierbar reduzieren
        if v is not None and not isinstance(v, (str, int, float, bool)):
            v = str(v)
        out[c] = v
    return out


# ── Fassade ──────────────────────────────────────────────────────────
class SapClient:
    """Einheitlicher Einstieg. Waehlt anhand ``connection_type`` den Kanal,
    haelt aber alle Sub-Clients bereit (der Reiter kann mehrere anbieten)."""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg if cfg is not None else get_sap_config()
        self.connection_type = (self.cfg.get("connection_type") or "odata").strip().lower()
        self.product = (self.cfg.get("sap_product") or "").strip()
        self.read_only = bool(self.cfg.get("read_only", True))
        self.odata = _ODataClient(self.cfg)
        self.hana = _HanaClient(self.cfg)
        self.rfc = _RfcClient(self.cfg)
        # Was der letzte ``test()`` geprueft hat – bleibt nach einer Ausnahme
        # stehen, damit der Fehlerbericht dieselben Angaben traegt.
        self.test_info: dict | None = None

    @property
    def configured(self) -> bool:
        return {
            "odata": self.odata.configured,
            "hana": self.hana.configured,
            "rfc": self.rfc.configured,
        }.get(self.connection_type, False)

    def active(self):
        """Der laut ``connection_type`` aktive Sub-Client."""
        return {"odata": self.odata, "hana": self.hana,
                "rfc": self.rfc}.get(self.connection_type, self.odata)

    def _test_variante(self) -> str:
        ct = self.connection_type
        if ct in ("hana", "rfc"):
            return ct
        return "service" if self.odata.default_service else "katalog"

    def _test_info_basis(self) -> dict:
        """Die Angaben, die VOR dem Test feststehen (Ziel, Benutzer, Mandant).

        Nie ein Kennwort oder Token – der Bericht wird kopiert und an den
        SAP-Administrator weitergegeben. ``geschaeftsdaten_gelesen`` steht
        ausdruecklich drin: kein Test liest Datensaetze, ein gruener Test sagt
        also nichts ueber die fachlichen Berechtigungen."""
        info: dict = {"variante": self._test_variante(),
                      "geschaeftsdaten_gelesen": False}
        ct = self.connection_type
        if ct == "hana":
            h = self.hana
            info.update({"adresse": "%s:%d" % (h.host, h.port), "benutzer": h.user,
                         "schema": h.schema, "verschluesselt": bool(h.encrypt)})
        elif ct == "rfc":
            p = self.rfc.params
            info.update({"adresse": p.get("ashost", ""), "systemnummer": p.get("sysnr", ""),
                         "mandant": p.get("client", ""), "benutzer": p.get("user", "")})
        else:
            o = self.odata
            art = o.anmeldeart
            info.update({"basis": _anzeige_url(o.base), "service": o.default_service,
                         "mandant": o.sap_client, "anmeldeart": art,
                         "benutzer": o.user if art == "basic" else ""})
        return info

    def test_bericht(self) -> dict:
        """Bericht zum letzten ``test()`` – auch nach einer Ausnahme.

        Bei OData kommen Adresse, HTTP-Status und Antwortzeit der LETZTEN
        Anfrage dazu; das ist die, an der der Test entschieden wurde."""
        info = dict(self.test_info or self._test_info_basis())
        if info.get("variante") in ("service", "katalog", "katalog_fehlt") and self.odata.letzte:
            info.update(self.odata.letzte)
        return info

    def test(self) -> dict:
        """Prueft die aktive Verbindung; liefert ``{type, detail, info}``.

        ``detail`` ist die Kurzzeile, ``info`` der Bericht fuer den
        SAP-Administrator (siehe ``test_bericht``). Was geprueft wird:

        * OData MIT Standard-Service: ``<service>/$metadata`` – gezaehlt werden
          die dort DEFINIERTEN EntitySets (keine Datensaetze, keine Aussage
          darueber, welche der Benutzer lesen darf).
        * OData OHNE Standard-Service: der Gateway-Katalog
          (``/IWFND/CATALOGSERVICE``), mit der echten Zahl der Services.
        * HANA: Anmeldung samt ``CURRENT_USER``/Datenbankname; RFC: ``RFCPING``."""
        info = self._test_info_basis()
        self.test_info = info
        ct = self.connection_type
        t0 = time.monotonic()
        if ct == "hana":
            detail = self.hana.test()
            info["dauer_ms"] = int((time.monotonic() - t0) * 1000)
            return {"type": "hana", "detail": detail, "info": self.test_bericht()}
        if ct == "rfc":
            self.rfc.call("RFCPING")
            info["dauer_ms"] = int((time.monotonic() - t0) * 1000)
            return {"type": "rfc", "detail": "RFCPING ok (%s)" % self.rfc.params.get("ashost"),
                    "info": self.test_bericht()}
        if info["variante"] == "service":
            sets = self.odata.entity_sets()
            info["entity_sets"] = sets
            return {"type": "odata",
                    "detail": "Service %s: %d EntitySet(s) definiert"
                              % (self.odata.default_service, len(sets)),
                    "info": self.test_bericht()}
        try:
            n, genau = self.odata.catalog_count()
        except SapError as e:
            # Kein SAP-Gateway-Katalog (z.B. S/4HANA Cloud) => 404. Der Server hat
            # geantwortet, die Verbindung steht – nur der Katalog-Pfad fehlt.
            # Auth-/Serverfehler (401/403/5xx) dagegen sind echte Fehler.
            if e.status == 404:
                info["variante"] = "katalog_fehlt"
                return {"type": "odata",
                        "detail": "Server erreichbar, aber kein Gateway-Katalog – "
                                  "bitte Standard-Service angeben",
                        "info": self.test_bericht()}
            raise
        info["anzahl_services"] = n
        info["anzahl_genau"] = genau
        return {"type": "odata",
                "detail": ("Gateway-Katalog erreichbar: %d Service(s)" % n) if genau
                          else ("Gateway-Katalog erreichbar: mindestens %d Services" % n),
                "info": self.test_bericht()}


# ── Reporting-Tool-Anbindungen ────────────────────────────────────────
def reporting_endpoints(client: SapClient) -> list[dict]:
    """Baut aus der aktiven Konfiguration konkrete Verbindungshinweise fuer die
    haeufigsten Reporting-/BI-Tools (Power BI, Tableau, Qlik, Excel, SAC).

    Das sind KEINE neuen Netzverbindungen, sondern die fertigen Angaben, mit
    denen ein Admin dasselbe SAP-System in seinem BI-Tool anbindet – ueber
    genau die Standard-Schnittstellen (OData/SQL/BW), die dieser Skill nutzt."""
    out: list[dict] = []
    o, h, r = client.odata, client.hana, client.rfc

    if o.configured:
        feed = o.base + (("/" + o.default_service.strip("/")) if o.default_service else "")
        out.append({
            "interface": "OData Feed",
            "url": feed,
            "tools": {
                "Power BI": "Daten abrufen → OData-Feed → URL einfuegen (Basic-Auth).",
                "Tableau": "Verbinden → OData → URL + Anmeldung.",
                "Qlik Sense": "OData-Connector (Web Connector Package) → URL.",
                "Excel": "Daten → Aus dem Web / Aus OData-Feed.",
            },
        })
    if h.configured:
        out.append({
            "interface": "SAP HANA (SQL/ODBC/JDBC)",
            "url": "%s:%d" % (h.host, h.port),
            "tools": {
                "Power BI": "Daten abrufen → SAP HANA-Datenbank → Server host:port "
                            "(DirectQuery oder Import).",
                "Tableau": "Verbinden → SAP HANA → Server/Port + Anmeldung.",
                "Qlik Sense": "SAP HANA (ODBC/JDBC) Connector.",
                "SAP Analytics Cloud": "Live-Datenverbindung zu HANA.",
            },
        })
    if r.configured:
        out.append({
            "interface": "SAP BW / RFC / BEx",
            "url": "%s (SysNr %s, Mandant %s)" % (
                r.params.get("ashost"), r.params.get("sysnr"), r.params.get("client")),
            "tools": {
                "Power BI": "Daten abrufen → SAP Business Warehouse (Anwendungsserver) "
                            "→ BEx-Query/InfoProvider.",
                "Tableau": "Verbinden → SAP BW.",
                "Qlik Sense": "SAP BW / BEx Connector.",
            },
        })
    return out
