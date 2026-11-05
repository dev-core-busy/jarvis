"""Confluence-Skill.

Anbindung an die Atlassian-Confluence-REST-API (Cloud + Server) ohne
zusaetzliche Abhaengigkeit. Die eigentliche Request-/Auth-Logik liegt im
geteilten ``backend.confluence_client`` (auch von den /api/confluence/*-
Endpoints des Confluence-Reiters genutzt).

Netzwerkaufrufe laufen ueber ``asyncio.to_thread`` (Event-Loop nicht blockieren).
"""

import asyncio

from backend.tools.base import BaseTool
from backend.confluence_client import ConfluenceClient, ConfluenceError, html_to_text


def _client() -> ConfluenceClient:
    """Der Zugang fuer DIESEN Lauf – persoenlicher Token, sonst Sammelzugang.

    Seit 2026-09-29 ist der in der Skill-Config hinterlegte Token nur noch der
    RUECKFALL: wer unter *Mein Confluence-Zugang* (``/confluence-addon``) einen
    eigenen PAT hinterlegt, arbeitet damit – und sieht genau seine eigenen
    Bereiche. Seit 2026-11-05 liest der Skill nur noch (Nur-Lesen im
    ``confluence_client``). Begruendung und Reichweite: Docstring von
    ``backend.confluence_accounts``.

    Der Benutzer kommt aus einem ContextVar, den der Dispatch je Werkzeug-Aufruf
    setzt – NIE aus einem Werkzeug-Argument: sonst koennte das Modell waehlen,
    mit wessen Token es liest.

    DIES IST DIE EINZIGE Konstruktionsstelle des Skills (auch ``_Base._guard``
    laeuft darueber). Waere sie nur halb umgestellt, lieferten zwei Werkzeuge
    desselben Auftrags verschiedene Ergebnisse und niemand koennte erklaeren
    warum – genau der Fehler, der beim Jira-Zugang vier Stellen gekostet hat.
    """
    from backend import confluence_accounts  # noqa: PLC0415 – Zirkelimport
    return confluence_accounts.client_fuer_lauf()


async def _to_thread(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)


def _fmt_err(e: ConfluenceError) -> str:
    if e.status in (401, 403):
        return "❌ Authentifizierung fehlgeschlagen (HTTP %s). Benutzer/API-Token pruefen." % e.status
    if e.status == 404:
        return "❌ Nicht gefunden (HTTP 404). URL/ID/Titel pruefen (Cloud-URL meist mit /wiki)."
    if e.status == 0:
        return "❌ %s" % e
    return "❌ Confluence-Fehler (HTTP %s): %s" % (e.status, e)


class _Base(BaseTool):
    """Gemeinsame Hilfen fuer alle Confluence-Tools."""

    def _guard(self) -> ConfluenceClient | None:
        c = _client()
        return c if c.configured else None


class ConfluenceTestConnectionTool(_Base):
    @property
    def name(self): return "confluence_test_connection"

    @property
    def description(self):
        return "Prueft die Confluence-Verbindung und meldet zugaengliche Spaces."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Confluence ist nicht konfiguriert. Bitte URL und API-Token im Confluence-Reiter eintragen."
        try:
            spaces = await _to_thread(c.spaces, 25)
        except ConfluenceError as e:
            return _fmt_err(e)
        keys = ", ".join(s.get("key", "?") for s in spaces[:10])
        return "✅ Verbindung erfolgreich zu %s (%d Space(s)).%s" % (
            c.base, len(spaces), (" – " + keys) if keys else "")


class ConfluenceListSpacesTool(_Base):
    @property
    def name(self): return "confluence_list_spaces"

    @property
    def description(self):
        return "Listet zugaengliche Confluence-Spaces (Key und Name)."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "limit": {"type": "INTEGER", "description": "Max. Anzahl (Standard 50)."}}, "required": []}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Confluence ist nicht konfiguriert."
        try:
            limit = max(1, min(int(kwargs.get("limit") or 50), 200))
        except (TypeError, ValueError):
            limit = 50
        try:
            spaces = await _to_thread(c.spaces, limit)
        except ConfluenceError as e:
            return _fmt_err(e)
        if not spaces:
            return "Keine Spaces gefunden."
        return "%d Space(s):\n" % len(spaces) + "\n".join(
            "- %s — %s" % (s.get("key", "?"), s.get("name", "")) for s in spaces)


class ConfluenceSearchTool(_Base):
    @property
    def name(self): return "confluence_search"

    @property
    def description(self):
        return ("Sucht Seiten in Confluence (Volltext), optional gefiltert nach "
                "Space-Key und Label. Liefert Titel, ID und Link.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "query": {"type": "STRING", "description": "Suchbegriff (Volltext)."},
            "space": {"type": "STRING", "description": "Optional: Space-Key zum Einschraenken."},
            "label": {"type": "STRING", "description": "Optional: Label zum Einschraenken."},
            "limit": {"type": "INTEGER", "description": "Max. Trefferzahl (Standard 10)."},
        }, "required": []}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Confluence ist nicht konfiguriert."
        query = (kwargs.get("query") or "").strip()
        space = (kwargs.get("space") or "").strip() or None
        label = (kwargs.get("label") or "").strip() or None
        if not query and not space and not label:
            return "Bitte query, space oder label angeben."
        try:
            limit = max(1, min(int(kwargs.get("limit") or 10), 50))
        except (TypeError, ValueError):
            limit = 10
        try:
            data = await _to_thread(c.search, query, space, label, limit)
        except ConfluenceError as e:
            return _fmt_err(e)
        results = data.get("results", [])
        if not results:
            return "Keine Treffer."
        lines = []
        for r in results:
            link = c.link_for(data, r)
            lines.append("- %s (ID %s)%s" % (
                r.get("title", "?"), r.get("id", "?"), ("\n  " + link) if link else ""))
        return "%d Treffer:\n%s" % (len(results), "\n".join(lines))


class ConfluenceGetPageTool(_Base):
    @property
    def name(self): return "confluence_get_page"

    @property
    def description(self):
        return "Ruft den Inhalt einer Seite ab – per Seiten-ID oder Titel (+ Space-Key)."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "page_id": {"type": "STRING", "description": "Seiten-ID (bevorzugt)."},
            "title": {"type": "STRING", "description": "Seitentitel (alternativ)."},
            "space_key": {"type": "STRING", "description": "Space-Key (zusammen mit title)."},
        }, "required": []}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Confluence ist nicht konfiguriert."
        page_id = (kwargs.get("page_id") or "").strip() or None
        title = (kwargs.get("title") or "").strip() or None
        space = (kwargs.get("space_key") or "").strip() or None
        if not page_id and not title:
            return "Bitte page_id ODER title (optional mit space_key) angeben."
        try:
            page = await _to_thread(c.get_page, page_id, title, space)
        except ConfluenceError as e:
            return _fmt_err(e)
        body = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
        sp = ((page.get("space") or {}).get("key")) or "?"
        return "📄 %s (ID %s, Space %s)\n\n%s" % (
            page.get("title", "?"), page.get("id", "?"), sp,
            html_to_text(body) or "(kein Textinhalt)")



class ConfluenceListAttachmentsTool(_Base):
    @property
    def name(self): return "confluence_list_attachments"

    @property
    def description(self):
        return ("Listet die Anhaenge einer Seite (Dateiname und Groesse). Zum HERUNTERLADEN "
                "confluence_download_attachment benutzen – NICHT curl/wget.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "page_id": {"type": "STRING", "description": "ID der Seite."}}, "required": ["page_id"]}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Confluence ist nicht konfiguriert."
        page_id = (kwargs.get("page_id") or "").strip()
        if not page_id:
            return "page_id ist erforderlich."
        try:
            atts = await _to_thread(c.list_attachments, page_id)
        except ConfluenceError as e:
            return _fmt_err(e)
        if not atts:
            return "Keine Anhaenge an Seite %s." % page_id
        # Der Download-Link wird ABSICHTLICH nicht mehr ausgegeben: er ist ohne den
        # PAT nutzlos, und solange er dastand, hat das Modell zuverlaessig curl darauf
        # angesetzt – Ergebnis waren 0-Byte-Dateien ohne Fehlermeldung (2026-07-30).
        # Stattdessen Groesse + der ausdrueckliche Hinweis auf das Download-Tool.
        lines = []
        for a in atts:
            size = ((a.get("extensions", {}) or {}).get("fileSize")
                    or (a.get("metadata", {}) or {}).get("fileSize"))
            try:
                size_txt = " (%s Byte)" % int(size) if size is not None else ""
            except (TypeError, ValueError):
                size_txt = ""
            lines.append("- %s%s" % (a.get("title", "?"), size_txt))
        return ("%d Anhang/Anhaenge:\n%s\n\nHerunterladen mit "
                "confluence_download_attachment(page_id=\"%s\", filename=\"…\") – "
                "ohne filename werden alle geladen." % (len(atts), "\n".join(lines), page_id))


class ConfluenceDownloadAttachmentTool(_Base):
    @property
    def name(self): return "confluence_download_attachment"

    @property
    def description(self):
        return ("Laedt einen Anhang einer Seite nach /tmp und gibt den lokalen Pfad zurueck – "
                "zum Weiterverarbeiten mit pandas/shell. Ohne 'filename' werden ALLE Anhaenge "
                "der Seite geladen. NUR dieses Tool benutzen, NIE curl/wget auf den Anhang-Link: "
                "der Link ist eine Web-Route, die ohne Anmeldung eine leere oder eine "
                "HTML-Datei liefert. Meldet dieses Tool, dass die Zwei-Faktor-Pruefung den "
                "Download blockiert, ist der Anhang NICHT abrufbar – dann NICHT mit curl/wget "
                "weiterprobieren (scheitert genauso), sondern dem Benutzer sagen, dass ein "
                "Administrator den Download-Pfad freischalten muss.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "page_id": {"type": "STRING", "description": "ID der Seite."},
            "filename": {"type": "STRING",
                         "description": "Dateiname des Anhangs (wie in confluence_list_attachments). "
                                        "Leer = alle Anhaenge der Seite."},
        }, "required": ["page_id"]}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Confluence ist nicht konfiguriert."
        page_id = (kwargs.get("page_id") or "").strip()
        if not page_id:
            return "page_id ist erforderlich."
        filename = (kwargs.get("filename") or "").strip()

        names = [filename]
        if not filename:
            try:
                atts = await _to_thread(c.list_attachments, page_id)
            except ConfluenceError as e:
                return _fmt_err(e)
            names = [(a.get("title") or "") for a in atts if a.get("title")]
            if not names:
                return "Keine Anhaenge an Seite %s." % page_id

        # Zielverzeichnis des LAUFS. Der Download passiert im Backend, gelesen
        # wird der Anhang aber meist per Shell IM Lauf – und dort ist /tmp
        # ausschliesslich das Lauf-Verzeichnis (backend/lauf_tmp.py). Ohne diese
        # Zeile laege die Datei im echten /tmp und waere im Lauf nicht vorhanden.
        # Gemeldet wird deshalb der Pfad, den der Lauf SIEHT.
        import os as _os
        try:
            from backend import lauf_tmp as _lt
            ziel_verz = str(_lt.temp_verzeichnis())
        except Exception:  # noqa: BLE001
            ziel_verz = "/tmp"

        ok, failed = [], []
        for nm in names:
            try:
                path, size = await _to_thread(c.download_attachment, page_id, nm, ziel_verz)
                path = "/tmp/" + _os.path.basename(path)
                ok.append((nm, path, size))
            except ConfluenceError as e:
                failed.append((nm, _fmt_err(e)))
            except Exception as e:  # noqa: BLE001
                failed.append((nm, str(e)[:200]))

        lines = []
        for nm, path, size in ok:
            lines.append("- %s -> %s (%d Byte)" % (nm, path, size))
        for nm, why in failed:
            lines.append("- %s -> FEHLER: %s" % (nm, why))
        head = "%d von %d Anhang/Anhaengen geladen:" % (len(ok), len(names))
        return head + "\n" + "\n".join(lines)



def get_tools():
    return [
        ConfluenceTestConnectionTool(),
        ConfluenceListSpacesTool(),
        ConfluenceSearchTool(),
        ConfluenceGetPageTool(),
        ConfluenceListAttachmentsTool(),
        ConfluenceDownloadAttachmentTool(),
    ]
