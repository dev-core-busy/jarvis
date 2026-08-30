"""VEMAS.NET-Skill (REST, Vorgabe Nur-Lesen).

Agent-Werkzeuge fuer den Zugriff auf VEMAS.NET (MS Consulting). Die eigentliche
Verbindungs-/Auth-Logik liegt im geteilten ``backend.vemas_client`` (auch von
den ``/api/vemas/*``-Endpunkten des Reiters und des Bereichs ``/vemas``
benutzt) – damit es nur EINE Implementierung gibt.

Alle Netzwerk-Aufrufe laufen ueber ``asyncio.to_thread`` (Event-Loop nicht
blockieren). Nur-Lesen ist im Client hart durchgesetzt und nur ueber die
Administrator-Konfiguration abschaltbar; geschrieben wird zusaetzlich
ausschliesslich mit dem PERSOENLICHEN Zugang (siehe ``vemas_accounts``).
"""

import asyncio
import contextvars
import json

from backend.tools.base import BaseTool
from backend.vemas_client import VemasClient, VemasError, reporting_hinweis

# Der fuer DIESEN Werkzeug-Aufruf aufgeloeste Zugang (siehe _Base.execute).
# ContextVar und nicht Objekt-Attribut: die Werkzeug-Instanzen sind geteilt
# (tools_map), zwei parallele Laeufe wuerden sich sonst den Zugang des jeweils
# anderen unterschieben – dieselbe Lehre wie bei der Actor-Bindung (2026-07-28).
_AKTUELL: contextvars.ContextVar = contextvars.ContextVar("jarvis_vemas_akt",
                                                          default=None)

# Deckel fuer die Rueckgabe an das Modell. Ein VEMAS-Datensatz kann sehr breit
# sein (Kundenakte mit dreissig Feldern); ohne Deckel sprengt eine Abfrage mit
# 200 Zeilen das Kontextfenster, und der Agent bricht mitten im Lauf ab.
_MAX_ZEILEN_AUSGABE = 200
_MAX_FELD_LAENGE = 300


async def _to_thread(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)


def _client() -> VemasClient:
    """Sammelzugang (Administrator-Konfiguration) – Rueckfall ohne Kontext."""
    from backend import vemas_accounts as va  # noqa: PLC0415
    return va.sammel_client()


def _fmt_err(e: VemasError) -> str:
    """Fehlermeldung fuer das Modell – und der Ort, an dem ein Anmeldefehler
    am persoenlichen Zugang VERMERKT wird.

    Der Vermerk gehoert hierher, weil alle Werkzeuge ihre ``VemasError`` selbst
    fangen: eine Zaehlung im Rahmen von ``_Base.execute`` wuerde nie erreicht."""
    zusatz = ""
    try:
        from backend import vemas_accounts as va  # noqa: PLC0415
        akt = _AKTUELL.get() or {}
        if akt.get("quelle") == va.QUELLE_PERSOENLICH and va.ist_anmeldefehler(e):
            va.melde_fehler(akt.get("benutzer") or "", e)
            zusatz = ("\nHINWEIS_AN_NUTZER: Die Anmeldung mit dem persoenlichen "
                      "VEMAS-Zugang ist fehlgeschlagen. Nach %d Fehlversuchen wird "
                      "er ausgesetzt und die Abfragen laufen wieder ueber den "
                      "gemeinsamen Zugang." % va.max_anmeldefehler())
        elif akt.get("quelle") == va.QUELLE_PERSOENLICH:
            va.merke_ergebnis(akt.get("benutzer") or "", False, str(e))
    except Exception:  # noqa: BLE001
        pass
    if e.status == 401:
        return ("❌ Authentifizierung fehlgeschlagen (HTTP 401). Benutzer, "
                "Kennwort oder Token pruefen.%s" % zusatz)
    if e.status == 403:
        # 403 ist KEINE Anmeldefrage (Lehre aus dem SAP-Vorfall 2026-08-25): der
        # Logon lief durch, es fehlt die Berechtigung. Wer hier "Kennwort
        # pruefen" schreibt, schickt Modell UND Benutzer in die falsche
        # Richtung – auf der VEMAS-Seite ist dazu kein Anmeldeversuch zu finden.
        return ("❌ Keine Berechtigung fuer diesen Zugriff (HTTP 403). Die "
                "Anmeldung war erfolgreich – dem VEMAS-Benutzer fehlt die "
                "Berechtigung fuer diese Ressource. Nimm eine andere Quelle "
                "oder lass die Berechtigung in VEMAS vergeben. Details: %s%s"
                % (e, zusatz))
    if e.status == 404:
        return ("❌ Nicht gefunden (HTTP 404). Der Pfad existiert auf diesem "
                "VEMAS-System nicht. Ermittle die vorhandenen Ressourcen mit "
                "'vemas_resources' oder 'vemas_discover', statt weitere Pfade "
                "zu raten.")
    if e.status:
        return "❌ VEMAS-Fehler (Status %s): %s%s" % (e.status, e, zusatz)
    return "❌ %s%s" % (e, zusatz)


def _mit_hinweis(ergebnis, akt: dict):
    """Haengt den Zugangs-Hinweis an das Werkzeug-Ergebnis.

    **Der Hinweis ist nicht Kosmetik.** Faellt ein Lauf auf den Sammelzugang
    zurueck, holt er die Daten mit FREMDEN – in der Regel weiteren –
    Berechtigungen. Ohne diesen Satz saehe der Benutzer Daten, von denen er
    annimmt, sie stammten aus seinem eigenen Zugang."""
    hinweis = (akt or {}).get("hinweis") or ""
    if not hinweis or not isinstance(ergebnis, str):
        return ergebnis
    return "%s\n\nHINWEIS_AN_NUTZER: %s" % (ergebnis, hinweis)


def _kurz(wert) -> str:
    """Ein Feldwert als kurzer Text.

    Verschachtelte Objekte werden als JSON gezeigt statt als ``{...}``: ohne
    dokumentierte API ist die Struktur genau die Information, die das Modell
    braucht, um die naechste Abfrage richtig zu stellen."""
    if wert is None:
        return ""
    if isinstance(wert, (dict, list)):
        s = json.dumps(wert, ensure_ascii=False)
    else:
        s = str(wert)
    s = s.replace("\n", " ").replace("\r", " ").strip()
    return s if len(s) <= _MAX_FELD_LAENGE else s[:_MAX_FELD_LAENGE] + "…"


def _tabelle(zeilen: list, limit: int = _MAX_ZEILEN_AUSGABE) -> str:
    """Kompakte Tabellendarstellung fuer die Agent-Ausgabe.

    Die Spalten kommen aus der VEREINIGUNG der ersten Zeilen, nicht aus der
    ersten allein: JSON-APIs lassen leere Felder gern weg, und eine Spalte, die
    in Zeile 1 fehlt, waere sonst fuer den ganzen Bestand unsichtbar."""
    if not zeilen:
        return "(keine Datensaetze)"
    if not isinstance(zeilen[0], dict):
        return "\n".join(_kurz(z) for z in zeilen[:limit])
    cols: list = []
    for z in zeilen[:25]:
        if isinstance(z, dict):
            for k in z:
                if k not in cols:
                    cols.append(k)
    gezeigt = zeilen[:limit]
    lines = [" | ".join(str(c) for c in cols)]
    lines.append("-|-".join("-" * len(str(c)) for c in cols))
    for z in gezeigt:
        lines.append(" | ".join(_kurz(z.get(c)) if isinstance(z, dict) else ""
                                for c in cols))
    if len(zeilen) > limit:
        lines.append("… (%d weitere Datensaetze; grenze die Abfrage ein)"
                     % (len(zeilen) - limit))
    return "\n".join(lines)


class _Base(BaseTool):
    """Gemeinsame Hilfen fuer alle VEMAS-Werkzeuge.

    ``execute`` ist hier ZENTRAL implementiert und loest den Zugang des
    laufenden Benutzers auf (persoenlicher Zugang mit Vorrang, sonst
    Sammelzugang); die Werkzeuge selbst implementieren ``_run``. Der Umweg ist
    Absicht: Aufloesung, Hinweis und Fehler-Vermerk stehen damit an EINER Stelle
    und gelten automatisch auch fuer kuenftige VEMAS-Werkzeuge. Wer stattdessen
    ``execute`` ueberschreibt, umgeht sie – deshalb der Name ``_run``."""

    async def execute(self, **kwargs):
        from backend import vemas_accounts as va  # noqa: PLC0415
        try:
            akt = va.aufloesen()          # Benutzer kommt aus dem ContextVar
        except Exception as e:            # noqa: BLE001
            # Fail-safe: laesst sich der persoenliche Zugang nicht aufloesen,
            # laeuft es ueber den Sammelzugang weiter (der ist nur lesend).
            print("[VEMAS] Zugang nicht aufloesbar (%s) – Sammelzugang" % e,
                  flush=True)
            akt = {"client": _client(), "quelle": va.QUELLE_SAMMEL,
                   "hinweis": "", "benutzer": ""}
        tok = _AKTUELL.set(akt)
        try:
            res = await self._run(**kwargs)
            if isinstance(res, str) and not res.startswith("❌") \
                    and akt.get("quelle") == va.QUELLE_PERSOENLICH:
                # Erfolg hebt einen laufenden Fehlerzaehler auf – das ist der
                # Rueckweg aus dem Aussetzer ohne jeden Handgriff.
                try:
                    va.merke_ergebnis(akt.get("benutzer") or "", True)
                except Exception:  # noqa: BLE001
                    pass
        finally:
            _AKTUELL.reset(tok)
        return _mit_hinweis(res, akt)

    async def _run(self, **kwargs):        # von den Werkzeugen implementiert
        raise NotImplementedError

    def _guard(self) -> VemasClient | None:
        """Der aufgeloeste Client dieses Aufrufs (None = nichts konfiguriert)."""
        akt = _AKTUELL.get() or {}
        c = akt.get("client") or _client()
        return c if c.configured else None

    def _not_configured(self) -> str:
        return ("VEMAS ist nicht konfiguriert. Ein Administrator hinterlegt "
                "Serveradresse und Zugang unter Einstellungen → Vemas; die "
                "eigenen Zugangsdaten traegt der Benutzer im Bereich VEMAS "
                "unter 'Mein VEMAS-Zugang' ein.")


class VemasTestConnectionTool(_Base):
    @property
    def name(self): return "vemas_test_connection"

    @property
    def description(self):
        return ("Prueft die Verbindung zum VEMAS.NET-System (REST) und meldet "
                "einen kurzen Status samt benutztem Zugang.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        try:
            res = await _to_thread(c.test)
        except VemasError as e:
            return _fmt_err(e)
        prod = (" – " + c.produkt) if c.produkt else ""
        # Welcher Zugang benutzt wurde, gehoert HIER ausdruecklich ins Ergebnis:
        # "Verbindung OK" allein sagt nicht, mit WESSEN Berechtigungen gelesen
        # wird – und genau das ist die Frage, die dieses Werkzeug beantworten soll.
        try:
            from backend import vemas_accounts as _va  # noqa: PLC0415
            zugang = " · %s" % _va.quelle_text((_AKTUELL.get() or {}).get("quelle") or "")
        except Exception:  # noqa: BLE001
            zugang = ""
        modus = "nur lesend" if c.read_only else "lesen und schreiben"
        return "✅ Verbindung OK%s%s [%s]: %s" % (prod, zugang, modus,
                                                 res.get("detail"))


class VemasResourcesTool(_Base):
    @property
    def name(self): return "vemas_resources"

    @property
    def description(self):
        return ("Listet die VEMAS-Ressourcen, die der Administrator hinterlegt "
                "hat (Name und Pfad, z.B. 'Projekte' oder 'Kunden'). IMMER "
                "ZUERST aufrufen, bevor du eine Abfrage stellst – die "
                "REST-Schnittstelle ist je Installation verschieden, geratene "
                "Pfade liefern nur 404.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        res = c.ressourcen()
        if not res:
            return ("Es sind keine Ressourcen hinterlegt. Versuche "
                    "'vemas_discover' (Selbstauskunft des Servers). Bleibt auch "
                    "die leer, muss ein Administrator die Ressourcen unter "
                    "Einstellungen → Vemas eintragen – ohne sie sind die Pfade "
                    "dieses Systems nicht bekannt.")
        lines = ["%d hinterlegte Ressource(n) – benutze den NAMEN in "
                 "'vemas_query':" % len(res)]
        for r in res:
            lines.append("- %s  →  %s" % (r["name"], r["pfad"]))
        return "\n".join(lines)


class VemasDiscoverTool(_Base):
    @property
    def name(self): return "vemas_discover"

    @property
    def description(self):
        return ("Liest die Selbstauskunft der VEMAS-REST-Schnittstelle "
                "(OpenAPI/Swagger) und listet die verfuegbaren Endpunkte. "
                "Benutze das, wenn 'vemas_resources' nicht ausreicht.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "filter": {"type": "STRING",
                       "description": "Nur Endpunkte anzeigen, die diesen Text "
                                      "enthalten (z.B. 'projekt')."}},
            "required": []}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        try:
            d = await _to_thread(c.beschreibung_suchen)
        except VemasError as e:
            return _fmt_err(e)
        if not d.get("gefunden"):
            # Ehrlich sein statt raten: eine erfundene Endpunktliste waere hier
            # der teuerste Fehler – das Modell probierte sie der Reihe nach
            # durch, und jeder Fehlgriff kostet einen Schritt.
            return ("Dieses VEMAS-System liefert keine maschinenlesbare "
                    "Schnittstellenbeschreibung (geprueft: %s). Benutze die vom "
                    "Administrator hinterlegten Ressourcen ('vemas_resources'). "
                    "Rate KEINE Pfade." % ", ".join(d.get("versucht") or []))
        f = (kwargs.get("filter") or "").strip().lower()
        pfade = d.get("pfade") or []
        if f:
            pfade = [p for p in pfade
                     if f in p["pfad"].lower() or f in (p.get("info") or "").lower()]
        if not pfade:
            return ("Beschreibung gefunden (%s), aber kein Endpunkt passt auf "
                    "'%s'." % (d.get("quelle"), f))
        kopf = "Schnittstelle '%s' %s (%s) – %d Endpunkt(e):" % (
            d.get("titel") or "?", d.get("version") or "", d.get("quelle"),
            len(pfade))
        lines = [kopf]
        for p in pfade[:150]:
            lines.append("- %s [%s]%s" % (p["pfad"], ",".join(p["methoden"]),
                                          (" – " + p["info"]) if p.get("info") else ""))
        if len(pfade) > 150:
            lines.append("… (%d weitere; grenze mit 'filter' ein)"
                         % (len(pfade) - 150))
        return "\n".join(lines)


class VemasQueryTool(_Base):
    @property
    def name(self): return "vemas_query"

    @property
    def description(self):
        return ("Liest Datensaetze aus einer VEMAS-Ressource (lesend, HTTP GET). "
                "'resource' ist der NAME aus 'vemas_resources' oder ein Pfad "
                "relativ zur Basis-URL. Zusaetzliche Filter gehen als "
                "'params' mit (JSON-Objekt).")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "resource": {"type": "STRING",
                         "description": "Ressourcen-Name oder Pfad, z.B. 'Projekte'."},
            "params": {"type": "STRING",
                       "description": "Query-Parameter als JSON-Objekt, z.B. "
                                      "{\"von\":\"2026-01-01\"}."},
            "top": {"type": "INTEGER",
                    "description": "Maximale Anzahl Datensaetze (Standard 50)."}},
            "required": ["resource"]}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        res = (kwargs.get("resource") or "").strip()
        if not res:
            return "❌ 'resource' fehlt. Rufe zuerst 'vemas_resources' auf."
        params = _params_lesen(kwargs.get("params"))
        if isinstance(params, str):
            return params                     # Fehlermeldung
        try:
            top = max(1, min(int(kwargs.get("top") or 50), 5000))
        except (TypeError, ValueError):
            top = 50
        try:
            pfad = c.ressource_pfad(res)
            zeilen = await _to_thread(c.abfragen, pfad, params, top)
        except VemasError as e:
            return _fmt_err(e)
        kopf = "%d Datensatz/Datensaetze aus '%s'%s:" % (
            len(zeilen), pfad, (" (Filter: %s)" % json.dumps(params, ensure_ascii=False))
            if params else "")
        return kopf + "\n" + _tabelle(zeilen)


class VemasGetTool(_Base):
    @property
    def name(self): return "vemas_get"

    @property
    def description(self):
        return ("Liest EINEN Datensatz aus VEMAS anhand seiner Kennung "
                "(lesend). Nutze das fuer Details zu einem Projekt, Kunden oder "
                "Vorgang, den eine vorherige Abfrage geliefert hat.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "resource": {"type": "STRING",
                         "description": "Ressourcen-Name oder Pfad, z.B. 'Projekte'."},
            "id": {"type": "STRING", "description": "Kennung des Datensatzes."}},
            "required": ["resource", "id"]}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        res = (kwargs.get("resource") or "").strip()
        kennung = str(kwargs.get("id") or "").strip()
        if not res or not kennung:
            return "❌ 'resource' und 'id' werden beide gebraucht."
        try:
            pfad = c.ressource_pfad(res).rstrip("/") + "/" + kennung
            daten = await _to_thread(c.get, pfad, None)
        except VemasError as e:
            return _fmt_err(e)
        zeilen = c.zeilen_aus(daten)
        if not zeilen:
            return "Kein Datensatz mit der Kennung '%s' in '%s'." % (kennung, res)
        z = zeilen[0]
        if not isinstance(z, dict):
            return _kurz(z)
        return "\n".join("%s: %s" % (k, _kurz(v)) for k, v in z.items())


class VemasWriteTool(_Base):
    """Schreibendes Werkzeug – NUR bei Freigabe und NUR mit eigenem Zugang.

    ZWEI SCHRANKEN, und beide sind noetig:

    (1) Der Administrator muss Schreibzugriffe freischalten (``read_only`` in
        der Skill-Config). Vorgabe ist AUS.
    (2) Der Lauf muss den PERSOENLICHEN Zugang benutzen. Ueber den Sammelzugang
        wird nie geschrieben – ``vemas_accounts._sammel_cfg`` erzwingt dort
        Nur-Lesen, und diese Pruefung hier sagt zusaetzlich WARUM (sonst
        bekaeme der Benutzer nur ein technisches "Nur-Lesen ist aktiv" und
        suchte den Fehler in der Konfiguration des Administrators).

    Warum das kein blosser Komfort ist: ein Schreibvorgang mit dem Sammelkonto
    traegt im VEMAS-Protokoll den falschen Namen und laeuft mit dessen – in der
    Regel weiteren – Rechten. Wer bucht, bucht unter seinem eigenen Konto.

    **DELETE gibt es bewusst nicht** (siehe ``vemas_client._SCHREIBEN``): der
    Agent verarbeitet Fremdtext, und ein Loeschwerkzeug waere darueber
    erreichbar. Loeschen geschieht in VEMAS.
    """

    @property
    def name(self): return "vemas_write"

    @property
    def description(self):
        return ("Legt einen Datensatz in VEMAS an oder aendert ihn (POST/PUT/"
                "PATCH). Steht nur zur Verfuegung, wenn ein Administrator "
                "Schreibzugriffe freigegeben hat UND der Benutzer einen eigenen "
                "VEMAS-Zugang hinterlegt hat. Frage vor dem Schreiben nach, "
                "wenn der Auftrag nicht eindeutig ist.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "resource": {"type": "STRING",
                         "description": "Ressourcen-Name oder Pfad."},
            "method": {"type": "STRING",
                       "description": "POST (neu), PUT oder PATCH (aendern)."},
            "id": {"type": "STRING",
                   "description": "Kennung des zu aendernden Datensatzes "
                                  "(bei PUT/PATCH)."},
            "data": {"type": "STRING",
                     "description": "Der Datensatz als JSON-Objekt."}},
            "required": ["resource", "method", "data"]}

    async def _run(self, **kwargs):
        from backend import vemas_accounts as va  # noqa: PLC0415
        c = self._guard()
        if not c:
            return self._not_configured()
        akt = _AKTUELL.get() or {}
        if akt.get("quelle") != va.QUELLE_PERSOENLICH:
            return ("❌ Schreiben ist ueber den gemeinsamen Zugang nicht "
                    "moeglich. Hinterlege deine eigenen VEMAS-Zugangsdaten im "
                    "Bereich VEMAS unter 'Mein VEMAS-Zugang' – ein "
                    "Schreibvorgang muss im VEMAS-Protokoll deinem Konto "
                    "zuzuordnen sein.")
        if not c.darf_schreiben():
            return ("❌ Schreibzugriffe sind nicht freigegeben. Ein "
                    "Administrator kann sie unter Einstellungen → Vemas "
                    "freischalten (Vorgabe: nur lesend).")
        res = (kwargs.get("resource") or "").strip()
        method = (kwargs.get("method") or "POST").strip().upper()
        daten = _params_lesen(kwargs.get("data"))
        if isinstance(daten, str):
            return daten                      # Fehlermeldung
        if not daten:
            return "❌ 'data' ist leer – ein leerer Datensatz wird nicht gesendet."
        kennung = str(kwargs.get("id") or "").strip()
        if method in ("PUT", "PATCH") and not kennung:
            return "❌ Fuer %s wird die Kennung ('id') des Datensatzes gebraucht." % method
        try:
            pfad = c.ressource_pfad(res)
            if kennung:
                pfad = pfad.rstrip("/") + "/" + kennung
            antwort = await _to_thread(c.anfrage, method, pfad, None, daten)
        except VemasError as e:
            return _fmt_err(e)
        return ("✅ %s auf '%s' ausgefuehrt (mit deinem persoenlichen Zugang).\n%s"
                % (method, pfad, _kurz(antwort) or "(keine Rueckmeldung)"))


class VemasReportingTool(_Base):
    @property
    def name(self): return "vemas_reporting_endpoints"

    @property
    def description(self):
        return ("Nennt die Angaben, mit denen sich dasselbe VEMAS-System direkt "
                "in Excel, Power BI, Tableau oder Qlik anbinden laesst.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def _run(self, **kwargs):
        c = self._guard()
        if not c:
            return self._not_configured()
        eps = reporting_hinweis(c.base)
        lines = ["Anbindung an das konfigurierte VEMAS-System:"]
        for e in eps:
            lines.append("- %s: %s" % (e["name"], e["hinweis"]))
        lines.append("Die Anmeldung erfolgt mit denselben Zugangsdaten wie hier; "
                     "Zugangsdaten werden von diesem Werkzeug NICHT ausgegeben.")
        return "\n".join(lines)


def _params_lesen(wert):
    """Nimmt ein JSON-Objekt als dict ODER als String entgegen.

    Modelle liefern strukturierte Argumente regelmaessig als Zeichenkette – wer
    das nicht toleriert, bekommt eine Fehlermeldung, wo eine Abfrage haette
    laufen koennen. Gibt bei Fehlern die MELDUNG als String zurueck (der
    Aufrufer prueft mit ``isinstance(..., str)``), damit ein Tippfehler nicht
    stillschweigend als "keine Parameter" durchgeht – genau der stille
    Fehlschlag mit Erfolgsmeldung, der bei ``office_create_excel`` teuer war."""
    if wert in (None, "", {}):
        return {}
    if isinstance(wert, dict):
        return wert
    if not isinstance(wert, str):
        return "❌ Parameter muessen ein JSON-Objekt sein (bekommen: %s)." % type(wert).__name__
    try:
        d = json.loads(wert)
    except ValueError as e:
        return "❌ Parameter sind kein gueltiges JSON: %s" % e
    if not isinstance(d, dict):
        return "❌ Parameter muessen ein JSON-OBJEKT sein (z.B. {\"jahr\":2026})."
    return d


def get_tools():
    """Werkzeuge des Skills.

    ``vemas_write`` wird IMMER geliefert – die Freigabe wird zur LAUFZEIT
    geprueft, nicht beim Laden. Grund: die Werkzeugliste entsteht einmal beim
    Aktivieren des Skills; wuerde sie von ``read_only`` abhaengen, waere eine
    spaetere Freigabe bis zum naechsten Dienstneustart wirkungslos, und der
    Administrator haelt seinen Schalter fuer kaputt. Die harte Schranke sitzt
    ohnehin im ``vemas_client`` (``assert_read_only``)."""
    return [
        VemasTestConnectionTool(),
        VemasResourcesTool(),
        VemasDiscoverTool(),
        VemasQueryTool(),
        VemasGetTool(),
        VemasWriteTool(),
        VemasReportingTool(),
    ]
