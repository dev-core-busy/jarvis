"""SAP-Skill (Read-Only).

Agent-Tools fuer den lesenden Zugriff auf SAP-Systeme. Die eigentliche
Verbindungs-/Auth-Logik liegt im geteilten ``backend.sap_client`` (auch von den
``/api/sap/*``-Endpoints des SAP-Reiters genutzt).

Alle Netzwerk-/DB-Aufrufe laufen ueber ``asyncio.to_thread`` (Event-Loop nicht
blockieren). Read-Only ist im Client hart durchgesetzt (siehe sap_client).
"""

import asyncio
import contextvars

from backend.tools.base import BaseTool
from backend.sap_client import SapClient, SapError, reporting_endpoints

# Der fuer DIESEN Werkzeug-Aufruf aufgeloeste Zugang (siehe _Base.execute).
# ContextVar und nicht Objekt-Attribut: die Werkzeug-Instanzen sind geteilt
# (tools_map), zwei parallele Laeufe wuerden sich sonst den Zugang des jeweils
# anderen unterschieben – dieselbe Lehre wie bei der Actor-Bindung (2026-07-28).
_AKTUELL: contextvars.ContextVar = contextvars.ContextVar("jarvis_sap_akt", default=None)


def _client() -> SapClient:
    """Sammelzugang (Administrator-Konfiguration) – Rueckfall ohne Kontext."""
    return SapClient()


async def _to_thread(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)


def _fmt_err(e: SapError) -> str:
    """Fehlermeldung fuer das Modell – und der Ort, an dem ein Anmeldefehler
    am persoenlichen Zugang VERMERKT wird.

    Der Vermerk gehoert hierher, weil alle Werkzeuge ihre ``SapError`` selbst
    fangen: eine Zaehlung im Rahmen von ``_Base.execute`` wuerde nie erreicht.
    Nach ``sap_accounts.max_anmeldefehler()`` Fehlversuchen wird der Zugang
    ausgesetzt und die Abfragen laufen wieder ueber den Sammelzugang – das
    schuetzt den SAP-Benutzer vor der Sperre durch ``login/fails_to_user_lock``.
    """
    zusatz = ""
    try:
        from backend import sap_accounts as _sa  # noqa: PLC0415
        akt = _AKTUELL.get() or {}
        if akt.get("quelle") == _sa.QUELLE_PERSOENLICH and _sa.ist_anmeldefehler(e):
            _sa.melde_fehler(akt.get("benutzer") or "", e)
            zusatz = ("\nHINWEIS_AN_NUTZER: Die Anmeldung mit dem persoenlichen "
                      "SAP-Zugang ist fehlgeschlagen. Nach %d Fehlversuchen wird er "
                      "ausgesetzt und die Abfragen laufen wieder ueber den "
                      "gemeinsamen Lesezugang." % _sa.max_anmeldefehler())
        elif akt.get("quelle") == _sa.QUELLE_PERSOENLICH:
            _sa.merke_ergebnis(akt.get("benutzer") or "", False, str(e))
    except Exception:  # noqa: BLE001
        pass
    if e.status in (401, 403):
        return ("❌ Authentifizierung fehlgeschlagen (HTTP %s). Benutzer/Passwort/Token "
                "pruefen.%s" % (e.status, zusatz))
    if e.status == 404:
        return "❌ Nicht gefunden (HTTP 404). URL/Service/EntitySet pruefen."
    if e.status:
        return "❌ SAP-Fehler (Status %s): %s%s" % (e.status, e, zusatz)
    return "❌ %s%s" % (e, zusatz)


def _mit_hinweis(ergebnis, akt: dict):
    """Haengt den Zugangs-Hinweis an das Werkzeug-Ergebnis.

    **Der Hinweis ist nicht Kosmetik.** Faellt ein Lauf auf den Sammelzugang
    zurueck, holt er die Daten mit FREMDEN – in der Regel weiteren –
    SAP-Berechtigungen. Ohne diesen Satz saehe der Benutzer Zahlen, von denen er
    annimmt, sie stammten aus seinem eigenen Zugang."""
    hinweis = (akt or {}).get("hinweis") or ""
    if not hinweis or not isinstance(ergebnis, str):
        return ergebnis
    return "%s\n\nHINWEIS_AN_NUTZER: %s" % (ergebnis, hinweis)


def _table(columns: list, rows: list, limit: int = 50) -> str:
    """Kompakte Tabellendarstellung fuer die Agent-Ausgabe."""
    if not rows:
        return "(keine Zeilen)"
    cols = columns or list(rows[0].keys())
    shown = rows[:limit]
    lines = [" | ".join(str(c) for c in cols)]
    lines.append("-|-".join("-" * len(str(c)) for c in cols))
    for r in shown:
        lines.append(" | ".join(str(r.get(c, "")) for c in cols))
    extra = ""
    if len(rows) > limit:
        extra = "\n… (%d weitere Zeilen)" % (len(rows) - limit)
    return "\n".join(lines) + extra


class _Base(BaseTool):
    """Gemeinsame Hilfen fuer alle SAP-Tools.

    ``execute`` ist hier ZENTRAL implementiert und loest den Zugang des laufenden
    Benutzers auf (persoenlicher Zugang mit Vorrang, sonst Sammelzugang); die
    Werkzeuge selbst implementieren ``_run``. Der Umweg ist Absicht: Aufloesung,
    Hinweis und Fehler-Vermerk stehen damit an EINER Stelle und gelten
    automatisch auch fuer kuenftige SAP-Werkzeuge. Wer stattdessen ``execute``
    ueberschreibt, umgeht sie – deshalb der Name ``_run``.
    """

    async def execute(self, **kwargs):
        from backend import sap_accounts as sa  # noqa: PLC0415
        try:
            akt = sa.aufloesen()          # Benutzer kommt aus dem ContextVar
        except Exception as e:            # noqa: BLE001
            # Fail-safe: laesst sich der persoenliche Zugang nicht aufloesen,
            # laeuft es wie vor 2026-08-17 ueber den Sammelzugang weiter.
            print("[SAP] Zugang nicht aufloesbar (%s) – Sammelzugang" % e, flush=True)
            akt = {"client": _client(), "quelle": sa.QUELLE_SAMMEL,
                   "hinweis": "", "benutzer": ""}
        tok = _AKTUELL.set(akt)
        try:
            res = await self._run(**kwargs)
            if isinstance(res, str) and not res.startswith("❌") \
                    and akt.get("quelle") == sa.QUELLE_PERSOENLICH:
                # Erfolg hebt einen laufenden Fehlerzaehler auf – das ist der
                # Rueckweg aus dem Aussetzer ohne jeden Handgriff.
                try:
                    sa.merke_ergebnis(akt.get("benutzer") or "", True)
                except Exception:  # noqa: BLE001
                    pass
        finally:
            _AKTUELL.reset(tok)
        return _mit_hinweis(res, akt)

    async def _run(self, **kwargs):        # von den Werkzeugen implementiert
        raise NotImplementedError

    def _guard(self) -> SapClient | None:
        """Der aufgeloeste Client dieses Aufrufs (None = nichts konfiguriert)."""
        akt = _AKTUELL.get() or {}
        c = akt.get("client") or _client()
        return c if c.configured else None

    def _not_configured(self) -> str:
        return ("SAP ist nicht konfiguriert. Entweder hinterlegt ein Administrator "
                "einen gemeinsamen Lesezugang unter Einstellungen → SAP, oder der "
                "Benutzer traegt seinen eigenen SAP-Zugang im SAP-Bereich unter "
                "'Mein SAP-Zugang' ein.")


class SapTestConnectionTool(_Base):
    @property
    def name(self): return "sap_test_connection"

    @property
    def description(self):
        return ("Prueft die aktive SAP-Verbindung (OData, HANA-SQL oder RFC – je nach "
                "konfiguriertem Verbindungstyp) und meldet einen kurzen Status.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        try:
            res = await _to_thread(c.test)
        except SapError as e:
            return _fmt_err(e)
        prod = (" – " + c.product) if c.product else ""
        # Welcher Zugang benutzt wurde, gehoert HIER ausdruecklich ins Ergebnis:
        # "Verbindung OK" allein sagt nicht, mit WESSEN Berechtigungen gelesen
        # wird – und genau das ist die Frage, die dieses Werkzeug beantworten soll.
        try:
            from backend import sap_accounts as _sa  # noqa: PLC0415
            zugang = " · %s" % _sa.quelle_text((_AKTUELL.get() or {}).get("quelle") or "")
        except Exception:  # noqa: BLE001
            zugang = ""
        return "✅ Verbindung OK [%s]%s%s: %s" % (res.get("type"), prod, zugang,
                                                 res.get("detail"))


class SapOdataServicesTool(_Base):
    @property
    def name(self): return "sap_odata_services"

    @property
    def description(self):
        return ("Listet verfuegbare OData-Services ueber den SAP-Gateway-Katalog. "
                "Nur im OData-Modus sinnvoll.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "limit": {"type": "INTEGER", "description": "Max. Anzahl (Standard 100)."}},
            "required": []}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        try:
            limit = max(1, min(int(kwargs.get("limit") or 100), 2000))
        except (TypeError, ValueError):
            limit = 100
        try:
            svcs = await _to_thread(c.odata.catalog_services, limit)
        except SapError as e:
            return _fmt_err(e)
        if not svcs:
            return "Keine Services gefunden (Katalog leer oder nicht erreichbar)."
        lines = ["%d Service(s):" % len(svcs)]
        for s in svcs:
            lines.append("- %s — %s" % (s.get("id") or "?", s.get("title") or ""))
        return "\n".join(lines)


class SapOdataEntitySetsTool(_Base):
    @property
    def name(self): return "sap_odata_entity_sets"

    @property
    def description(self):
        return "Listet die EntitySets (Tabellen/Views) eines OData-Service aus dessen $metadata."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "service": {"type": "STRING", "description": "Service-Pfad (optional, sonst Standard-Service)."}},
            "required": []}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        svc = (kwargs.get("service") or "").strip()
        try:
            sets = await _to_thread(c.odata.entity_sets, svc)
        except SapError as e:
            return _fmt_err(e)
        if not sets:
            return "Keine EntitySets gefunden."
        return "%d EntitySet(s):\n%s" % (len(sets), "\n".join("- " + s for s in sets))


class SapOdataQueryTool(_Base):
    @property
    def name(self): return "sap_odata_query"

    @property
    def description(self):
        return ("Liest Datenzeilen eines OData-EntitySet (nur GET). Unterstuetzt "
                "$select, $filter, $top, $skip, $orderby, $expand.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "entity_set": {"type": "STRING", "description": "Name des EntitySet, z.B. 'A_SalesOrder'."},
            "service": {"type": "STRING", "description": "Service-Pfad (optional, sonst Standard-Service)."},
            "select": {"type": "STRING", "description": "$select: kommaseparierte Felder."},
            "filter": {"type": "STRING", "description": "$filter-Ausdruck (OData-Syntax)."},
            "top": {"type": "INTEGER", "description": "Max. Zeilen (Standard 50)."},
            "skip": {"type": "INTEGER", "description": "$skip (Offset)."},
            "orderby": {"type": "STRING", "description": "$orderby-Ausdruck."},
            "expand": {"type": "STRING", "description": "$expand (Navigationseigenschaften)."},
        }, "required": ["entity_set"]}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        entity_set = (kwargs.get("entity_set") or "").strip()
        if not entity_set:
            return "entity_set ist erforderlich."
        try:
            top = max(1, min(int(kwargs.get("top") or 50), 5000))
        except (TypeError, ValueError):
            top = 50
        try:
            rows = await _to_thread(
                c.odata.query, entity_set, (kwargs.get("service") or "").strip(),
                select=(kwargs.get("select") or "").strip(),
                filter=(kwargs.get("filter") or "").strip(),
                top=top, skip=int(kwargs.get("skip") or 0),
                orderby=(kwargs.get("orderby") or "").strip(),
                expand=(kwargs.get("expand") or "").strip())
        except SapError as e:
            return _fmt_err(e)
        if not rows:
            return "Keine Zeilen."
        cols = [k for k in rows[0].keys() if k != "__metadata"]
        clean = [{k: v for k, v in r.items() if k != "__metadata"} for r in rows]
        return "%d Zeile(n) aus %s:\n%s" % (len(rows), entity_set, _table(cols, clean))


class SapSqlQueryTool(_Base):
    @property
    def name(self): return "sap_sql_query"

    @property
    def description(self):
        return ("Fuehrt eine LESENDE SQL-Abfrage gegen SAP HANA aus. Es sind nur "
                "SELECT/WITH-Anweisungen erlaubt; schreibende Statements werden abgelehnt.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "sql": {"type": "STRING", "description": "SELECT- oder WITH-Abfrage (eine Anweisung)."},
            "max_rows": {"type": "INTEGER", "description": "Max. Zeilen (Standard 200, max 10000)."},
        }, "required": ["sql"]}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        sql = (kwargs.get("sql") or "").strip()
        if not sql:
            return "sql ist erforderlich."
        try:
            max_rows = max(1, min(int(kwargs.get("max_rows") or 200), 10000))
        except (TypeError, ValueError):
            max_rows = 200
        try:
            res = await _to_thread(c.hana.run_select, sql, max_rows)
        except SapError as e:
            return _fmt_err(e)
        rows = res.get("rows", [])
        if not rows:
            return "Abfrage OK – keine Zeilen."
        note = "\n⚠️ Ergebnis bei %d Zeilen abgeschnitten." % max_rows if res.get("truncated") else ""
        return "%d Zeile(n):\n%s%s" % (len(rows), _table(res.get("columns", []), rows), note)


class SapListTablesTool(_Base):
    @property
    def name(self): return "sap_list_tables"

    @property
    def description(self):
        return "Listet Tabellen und Views eines HANA-Schemas (aus dem SYS-Katalog)."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "schema": {"type": "STRING", "description": "Schema-Name (optional, sonst Standard-Schema)."},
            "limit": {"type": "INTEGER", "description": "Max. Anzahl (Standard 200)."},
        }, "required": []}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        try:
            limit = max(1, min(int(kwargs.get("limit") or 200), 5000))
        except (TypeError, ValueError):
            limit = 200
        try:
            rows = await _to_thread(c.hana.list_tables, (kwargs.get("schema") or "").strip(), limit)
        except SapError as e:
            return _fmt_err(e)
        if not rows:
            return "Keine Objekte gefunden."
        return "%d Objekt(e):\n%s" % (len(rows), _table(
            ["SCHEMA_NAME", "OBJECT_NAME", "OBJECT_TYPE"], rows, limit=200))


class SapDescribeTableTool(_Base):
    @property
    def name(self): return "sap_describe_table"

    @property
    def description(self):
        return "Beschreibt die Spalten (Name/Typ/Laenge) einer HANA-Tabelle oder -View."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "table": {"type": "STRING", "description": "Tabellen-/View-Name."},
            "schema": {"type": "STRING", "description": "Schema (optional)."},
        }, "required": ["table"]}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        table = (kwargs.get("table") or "").strip()
        if not table:
            return "table ist erforderlich."
        try:
            rows = await _to_thread(c.hana.describe, table, (kwargs.get("schema") or "").strip())
        except SapError as e:
            return _fmt_err(e)
        if not rows:
            return "Keine Spalten gefunden (Tabelle/Schema pruefen)."
        return "%s: %d Spalte(n):\n%s" % (table, len(rows), _table(
            ["COLUMN_NAME", "DATA_TYPE_NAME", "LENGTH", "SCALE", "IS_NULLABLE"], rows, limit=500))


class SapRfcReadTableTool(_Base):
    @property
    def name(self): return "sap_rfc_read_table"

    @property
    def description(self):
        return ("Liest eine SAP-Tabelle klassisch per RFC (RFC_READ_TABLE). Nur lesend; "
                "benoetigt eine RFC-Konfiguration und das SAP NW RFC SDK.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "table": {"type": "STRING", "description": "SAP-Tabellenname, z.B. 'MARA'."},
            "fields": {"type": "STRING", "description": "Kommaseparierte Feldliste (optional)."},
            "where": {"type": "STRING", "description": "WHERE-Bedingung (OpenSQL, optional)."},
            "max_rows": {"type": "INTEGER", "description": "Max. Zeilen (Standard 100)."},
        }, "required": ["table"]}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        table = (kwargs.get("table") or "").strip()
        if not table:
            return "table ist erforderlich."
        fields = [f for f in (kwargs.get("fields") or "").split(",") if f.strip()]
        try:
            max_rows = max(1, min(int(kwargs.get("max_rows") or 100), 5000))
        except (TypeError, ValueError):
            max_rows = 100
        try:
            res = await _to_thread(c.rfc.read_table, table, fields=fields,
                                   where=(kwargs.get("where") or "").strip(), max_rows=max_rows)
        except SapError as e:
            return _fmt_err(e)
        rows = res.get("rows", [])
        if not rows:
            return "Keine Zeilen."
        return "%d Zeile(n) aus %s:\n%s" % (len(rows), table, _table(res.get("columns", []), rows))


class SapReportingEndpointsTool(_Base):
    @property
    def name(self): return "sap_reporting_endpoints"

    @property
    def description(self):
        return ("Liefert fertige Verbindungsangaben, mit denen die gaengigen Reporting-/BI-Tools "
                "(Power BI, Tableau, Qlik, Excel, SAP Analytics Cloud) an das konfigurierte "
                "SAP-System angebunden werden – ueber dieselben Standard-Schnittstellen (OData/SQL/BW).")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def _run(self, **kwargs):
        # Der AUFGELOESTE Client, nicht der Sammelzugang: die Verbindungsangaben
        # sollen zu dem Zugang passen, mit dem der Benutzer auch liest – sonst
        # baut er sein BI-Werkzeug auf ein anderes System als seine Auswertung.
        c = (_AKTUELL.get() or {}).get("client") or _client()
        eps = reporting_endpoints(c)
        if not eps:
            return ("Keine Schnittstelle konfiguriert. Bitte im SAP-Reiter OData-, HANA- "
                    "oder RFC-Zugangsdaten hinterlegen – oder einen eigenen SAP-Zugang "
                    "im SAP-Bereich unter 'Mein SAP-Zugang'.")
        out = ["Reporting-/BI-Anbindungen fuer dieses SAP-System:"]
        for e in eps:
            out.append("\n▶ %s\n  Endpunkt: %s" % (e["interface"], e.get("url") or "?"))
            for tool, hint in e.get("tools", {}).items():
                out.append("  • %s: %s" % (tool, hint))
        return "\n".join(out)


def get_tools():
    return [
        SapTestConnectionTool(),
        SapOdataServicesTool(),
        SapOdataEntitySetsTool(),
        SapOdataQueryTool(),
        SapSqlQueryTool(),
        SapListTablesTool(),
        SapDescribeTableTool(),
        SapRfcReadTableTool(),
        SapReportingEndpointsTool(),
    ]
