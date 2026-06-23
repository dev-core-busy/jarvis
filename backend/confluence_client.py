"""Geteilter Confluence-REST-Client.

Wird sowohl vom Skill (``skills/confluence/main.py``) als auch von den
``/api/confluence/*``-Endpoints (``backend/main.py``, fuer den Confluence-Reiter)
genutzt – damit es nur EINE Implementierung der Auth-/Request-Logik gibt.

Auth:
- Personal Access Token (Server/Data-Center) wird immer als Bearer gesendet.
  Das Benutzerfeld wird nicht benoetigt (PAT ist nicht an einen Benutzer gebunden).

Alle Methoden sind synchron (``requests``). Aufrufer im async-Kontext muessen
sie via ``asyncio.to_thread`` ausfuehren, um den Event-Loop nicht zu blockieren.
"""

from __future__ import annotations

import html
import re

import requests


def get_confluence_config() -> dict:
    """Liest die in der Skill-Config hinterlegten Confluence-Werte."""
    try:
        from backend.config import config
        return config.get_skill_states().get("confluence", {}).get("config", {}) or {}
    except Exception:
        return {}


def html_to_text(s: str, limit: int = 4000) -> str:
    """Reduziert Confluence-Storage-HTML auf lesbaren Text."""
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n", s, flags=re.I)
    s = re.sub(r"</li\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if len(s) > limit:
        s = s[:limit] + " …[gekuerzt]"
    return s


class ConfluenceError(Exception):
    """Fehler bei einer Confluence-Anfrage (mit HTTP-Status)."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


class ConfluenceClient:
    """Minimaler, geteilter Confluence-REST-Client."""

    def __init__(self, cfg: dict | None = None):
        cfg = cfg if cfg is not None else get_confluence_config()
        self.base = (cfg.get("base_url") or "").strip().rstrip("/")
        self.user = (cfg.get("user") or "").strip()
        self.token = (cfg.get("api_token") or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.base and self.token)

    # ── intern ────────────────────────────────────────────────────
    def _headers(self, extra: dict | None = None) -> dict:
        # Server/DC: Personal Access Token IMMER als Bearer senden – auch wenn
        # versehentlich ein Benutzer eingetragen ist (PAT ist nicht user-gebunden).
        h = {"Accept": "application/json", "Authorization": "Bearer " + self.token}
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, path: str, *, params=None, json=None,
                 headers=None, files=None, data=None):
        if not self.configured:
            raise ConfluenceError(0, "Confluence ist nicht konfiguriert (URL/Token fehlen).")
        url = self.base + path
        r = requests.request(
            method, url, params=params or {}, json=json,
            headers=self._headers(headers),
            files=files, data=data, timeout=20)
        if r.status_code >= 400:
            msg = ""
            try:
                j = r.json()
                msg = j.get("message") or j.get("statusText") or ""
            except ValueError:
                msg = (r.text or "")[:200]
            raise ConfluenceError(r.status_code, msg or ("HTTP %s" % r.status_code))
        try:
            return r.json()
        except ValueError:
            return {}

    # ── High-Level ────────────────────────────────────────────────
    def spaces(self, limit: int = 50) -> list[dict]:
        d = self._request("GET", "/rest/api/space", params={"limit": limit})
        return d.get("results", [])

    def spaces_detailed(self, limit: int = 500) -> list[dict]:
        """Alle Spaces (Bereiche) mit Schluessel, Name, Typ und Web-Link.

        Blaettert ueber die Seiten der Confluence-API, bis ``limit`` erreicht
        ist oder keine weiteren Spaces mehr kommen.
        """
        out: list[dict] = []
        start, page = 0, 50
        while len(out) < limit:
            d = self._request("GET", "/rest/api/space",
                              params={"start": start, "limit": page})
            results = d.get("results", [])
            for s in results:
                out.append({
                    "key": s.get("key"),
                    "name": s.get("name"),
                    "type": s.get("type"),
                    "link": self.link_for(d, s),
                })
            if len(results) < page:
                break  # letzte Seite erreicht
            start += page
        return out

    def pages_in_space(self, space: str, limit: int = 500) -> list[dict]:
        """Alle Seiten eines Bereichs (Space) mit ID, Titel und Web-Link."""
        out: list[dict] = []
        start, page = 0, 50
        while len(out) < limit:
            d = self._request("GET", "/rest/api/content",
                              params={"spaceKey": space, "type": "page",
                                      "start": start, "limit": page})
            results = d.get("results", [])
            for s in results:
                out.append({
                    "id": s.get("id"),
                    "title": s.get("title"),
                    "link": self.link_for(d, s),
                })
            if len(results) < page:
                break
            start += page
        return out

    def link_for(self, data: dict, item: dict) -> str:
        link_base = (data.get("_links", {}) or {}).get("base", self.base)
        webui = (item.get("_links", {}) or {}).get("webui", "")
        return (link_base + webui) if webui else ""

    def search(self, query: str = "", space: str | None = None,
               label: str | None = None, limit: int = 25) -> dict:
        """Volltext-/CQL-Suche. Baut aus Filtern eine CQL-Query."""
        clauses = ["type=page"]
        if query:
            clauses.append('text ~ "%s"' % query.replace('"', "'"))
        if space:
            clauses.append('space = "%s"' % space.replace('"', "'"))
        if label:
            clauses.append('label = "%s"' % label.replace('"', "'"))
        cql = " and ".join(clauses) + " order by lastmodified desc"
        return self._request("GET", "/rest/api/content/search",
                             params={"cql": cql, "limit": limit})

    def get_page(self, page_id: str | None = None, title: str | None = None,
                 space: str | None = None) -> dict:
        if page_id:
            return self._request(
                "GET", "/rest/api/content/%s" % page_id,
                params={"expand": "body.storage,version,space"})
        if title:
            params = {"title": title, "expand": "body.storage,version,space", "limit": 1}
            if space:
                params["spaceKey"] = space
            d = self._request("GET", "/rest/api/content", params=params)
            res = d.get("results", [])
            if not res:
                raise ConfluenceError(404, "Keine Seite mit Titel '%s' gefunden." % title)
            return res[0]
        raise ConfluenceError(0, "page_id oder title erforderlich.")

    def create_page(self, space: str, title: str, body: str,
                    parent_id: str | None = None) -> dict:
        payload = {
            "type": "page",
            "title": title,
            "space": {"key": space},
            "body": {"storage": {"value": body or "", "representation": "storage"}},
        }
        if parent_id:
            payload["ancestors"] = [{"id": str(parent_id)}]
        return self._request("POST", "/rest/api/content", json=payload)

    def update_page(self, page_id: str, body: str | None = None,
                    title: str | None = None) -> dict:
        cur = self._request("GET", "/rest/api/content/%s" % page_id,
                            params={"expand": "version,body.storage,space"})
        ver = (cur.get("version", {}) or {}).get("number", 1) + 1
        new_title = title or cur.get("title", "")
        new_body = body if body is not None else \
            (((cur.get("body") or {}).get("storage") or {}).get("value") or "")
        payload = {
            "type": "page",
            "title": new_title,
            "version": {"number": ver},
            "body": {"storage": {"value": new_body, "representation": "storage"}},
        }
        return self._request("PUT", "/rest/api/content/%s" % page_id, json=payload)

    def delete_page(self, page_id: str) -> None:
        self._request("DELETE", "/rest/api/content/%s" % page_id)

    def add_comment(self, page_id: str, body: str) -> dict:
        payload = {
            "type": "comment",
            "container": {"id": str(page_id), "type": "page"},
            "body": {"storage": {"value": body or "", "representation": "storage"}},
        }
        return self._request("POST", "/rest/api/content", json=payload)

    def list_attachments(self, page_id: str) -> list[dict]:
        d = self._request("GET", "/rest/api/content/%s/child/attachment" % page_id,
                         params={"limit": 50})
        return d.get("results", [])

    def upload_attachment(self, page_id: str, file_path: str) -> dict:
        import os
        if not os.path.isfile(file_path):
            raise ConfluenceError(0, "Datei nicht gefunden: %s" % file_path)
        with open(file_path, "rb") as fh:
            files = {"file": (os.path.basename(file_path), fh)}
            return self._request(
                "POST", "/rest/api/content/%s/child/attachment" % page_id,
                headers={"X-Atlassian-Token": "no-check"}, files=files)
