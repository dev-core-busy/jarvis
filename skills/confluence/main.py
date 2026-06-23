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
    return ConfluenceClient()


def _as_storage(body: str) -> str:
    """Plaintext → Confluence-Storage-XHTML (HTML wird unveraendert gelassen)."""
    if not body:
        return ""
    if "<" in body and ">" in body:
        return body  # sieht nach (X)HTML aus
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    return "".join("<p>%s</p>" % p.replace("\n", "<br/>") for p in paras) or "<p></p>"


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


class ConfluenceCreatePageTool(_Base):
    @property
    def name(self): return "confluence_create_page"

    @property
    def description(self):
        return ("Legt eine neue Seite an. Body als Text oder Confluence-Storage-XHTML; "
                "Text wird automatisch in Absaetze umgewandelt.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "space": {"type": "STRING", "description": "Space-Key (z.B. 'DEV')."},
            "title": {"type": "STRING", "description": "Titel der neuen Seite."},
            "body": {"type": "STRING", "description": "Inhalt (Text oder Storage-XHTML)."},
            "parent_id": {"type": "STRING", "description": "Optional: ID der uebergeordneten Seite."},
        }, "required": ["space", "title", "body"]}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Confluence ist nicht konfiguriert."
        space = (kwargs.get("space") or "").strip()
        title = (kwargs.get("title") or "").strip()
        if not space or not title:
            return "space und title sind erforderlich."
        body = _as_storage(kwargs.get("body") or "")
        parent = (kwargs.get("parent_id") or "").strip() or None
        try:
            page = await _to_thread(c.create_page, space, title, body, parent)
        except ConfluenceError as e:
            return _fmt_err(e)
        link = c.link_for(page, page)
        return "✅ Seite angelegt: %s (ID %s)%s" % (
            page.get("title", title), page.get("id", "?"), ("\n" + link) if link else "")


class ConfluenceUpdatePageTool(_Base):
    @property
    def name(self): return "confluence_update_page"

    @property
    def description(self):
        return ("Aktualisiert eine bestehende Seite (Body und/oder Titel). Die "
                "Versionsnummer wird automatisch erhoeht.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "page_id": {"type": "STRING", "description": "ID der zu aendernden Seite."},
            "body": {"type": "STRING", "description": "Neuer Inhalt (Text oder Storage-XHTML)."},
            "title": {"type": "STRING", "description": "Optional: neuer Titel."},
        }, "required": ["page_id"]}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Confluence ist nicht konfiguriert."
        page_id = (kwargs.get("page_id") or "").strip()
        if not page_id:
            return "page_id ist erforderlich."
        body = kwargs.get("body")
        body = _as_storage(body) if body else None
        title = (kwargs.get("title") or "").strip() or None
        if body is None and not title:
            return "Bitte body und/oder title angeben."
        try:
            page = await _to_thread(c.update_page, page_id, body, title)
        except ConfluenceError as e:
            return _fmt_err(e)
        ver = (page.get("version", {}) or {}).get("number", "?")
        return "✅ Seite aktualisiert: %s (ID %s, Version %s)" % (
            page.get("title", "?"), page.get("id", page_id), ver)


class ConfluenceDeletePageTool(_Base):
    @property
    def name(self): return "confluence_delete_page"

    @property
    def description(self):
        return "Loescht (papierkorbt) eine Seite anhand ihrer ID."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "page_id": {"type": "STRING", "description": "ID der zu loeschenden Seite."}},
            "required": ["page_id"]}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Confluence ist nicht konfiguriert."
        page_id = (kwargs.get("page_id") or "").strip()
        if not page_id:
            return "page_id ist erforderlich."
        try:
            await _to_thread(c.delete_page, page_id)
        except ConfluenceError as e:
            return _fmt_err(e)
        return "🗑️ Seite %s geloescht (in den Papierkorb verschoben)." % page_id


class ConfluenceAddCommentTool(_Base):
    @property
    def name(self): return "confluence_add_comment"

    @property
    def description(self):
        return "Fuegt einer Seite einen Kommentar hinzu."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "page_id": {"type": "STRING", "description": "ID der Seite."},
            "body": {"type": "STRING", "description": "Kommentartext."},
        }, "required": ["page_id", "body"]}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Confluence ist nicht konfiguriert."
        page_id = (kwargs.get("page_id") or "").strip()
        body = (kwargs.get("body") or "").strip()
        if not page_id or not body:
            return "page_id und body sind erforderlich."
        try:
            res = await _to_thread(c.add_comment, page_id, _as_storage(body))
        except ConfluenceError as e:
            return _fmt_err(e)
        return "💬 Kommentar hinzugefuegt (ID %s)." % res.get("id", "?")


class ConfluenceListAttachmentsTool(_Base):
    @property
    def name(self): return "confluence_list_attachments"

    @property
    def description(self):
        return "Listet die Anhaenge einer Seite (Dateiname und Download-Link)."

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
        lines = []
        for a in atts:
            dl = (a.get("_links", {}) or {}).get("download", "")
            link = (c.base + dl) if dl else ""
            lines.append("- %s%s" % (a.get("title", "?"), ("\n  " + link) if link else ""))
        return "%d Anhang/Anhaenge:\n%s" % (len(atts), "\n".join(lines))


class ConfluenceUploadAttachmentTool(_Base):
    @property
    def name(self): return "confluence_upload_attachment"

    @property
    def description(self):
        return ("Laedt eine (server-lokale) Datei als Anhang an eine Seite hoch. "
                "file_path ist ein Pfad auf dem Jarvis-Server.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "page_id": {"type": "STRING", "description": "ID der Seite."},
            "file_path": {"type": "STRING", "description": "Pfad der hochzuladenden Datei (auf dem Server)."},
        }, "required": ["page_id", "file_path"]}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Confluence ist nicht konfiguriert."
        page_id = (kwargs.get("page_id") or "").strip()
        file_path = (kwargs.get("file_path") or "").strip()
        if not page_id or not file_path:
            return "page_id und file_path sind erforderlich."
        try:
            res = await _to_thread(c.upload_attachment, page_id, file_path)
        except ConfluenceError as e:
            return _fmt_err(e)
        results = res.get("results", res if isinstance(res, list) else [res])
        name = ""
        try:
            name = results[0].get("title", "")
        except (IndexError, AttributeError):
            pass
        return "📎 Anhang hochgeladen%s (Seite %s)." % ((": " + name) if name else "", page_id)


def get_tools():
    return [
        ConfluenceTestConnectionTool(),
        ConfluenceListSpacesTool(),
        ConfluenceSearchTool(),
        ConfluenceGetPageTool(),
        ConfluenceCreatePageTool(),
        ConfluenceUpdatePageTool(),
        ConfluenceDeletePageTool(),
        ConfluenceAddCommentTool(),
        ConfluenceListAttachmentsTool(),
        ConfluenceUploadAttachmentTool(),
    ]
