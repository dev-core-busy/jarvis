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
    """Reduziert Confluence-Storage-HTML auf lesbaren (Markdown-aehnlichen) Text.
    Block-Elemente werden mit Zeilenumbruechen abgetrennt, Ueberschriften als
    ``##`` markiert und Listenpunkte mit ``- `` versehen, damit das Frontend die
    Struktur rendern kann (frueher klebten Ueberschriften am Folgetext)."""
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<h[1-6][^>]*>", "\n\n## ", s, flags=re.I)   # Ueberschriften markieren
    s = re.sub(r"</h[1-6]\s*>", "\n\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "\n- ", s, flags=re.I)          # Listenpunkte
    s = re.sub(r"</p\s*>", "\n\n", s, flags=re.I)
    s = re.sub(r"</li\s*>", "\n", s, flags=re.I)
    s = re.sub(r"</tr\s*>", "\n", s, flags=re.I)             # Tabellenzeilen
    s = re.sub(r"</(div|table|thead|tbody|section|article|blockquote|ul|ol)\s*>",
               "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
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

    def search_spaces(self, query: str = "", spaces: list | None = None,
                      exclude: bool = False, limit: int = 25) -> dict:
        """Volltextsuche mit Space-Whitelist (``exclude=False``) bzw.
        -Blacklist (``exclude=True``). Ohne ``spaces`` wie ``search()``."""
        clauses = ["type=page"]
        if query:
            clauses.append('text ~ "%s"' % query.replace('"', "'"))
        keys = [s.strip() for s in (spaces or []) if s and s.strip()]
        if keys:
            keylist = ", ".join('"%s"' % k.replace('"', "'") for k in keys)
            clauses.append('space %s (%s)' % ("not in" if exclude else "in", keylist))
        cql = " and ".join(clauses) + " order by lastmodified desc"
        return self._request("GET", "/rest/api/content/search",
                             params={"cql": cql, "limit": limit})

    def search_advanced(self, terms: list | None = None, spaces: list | None = None,
                        exclude: bool = False, limit: int = 25) -> dict:
        """Volltextsuche mit mehreren OR-verknuepften Begriffen + optionalem
        Space-Filter (Whitelist/Blacklist). Sucht NICHT die ganze Phrase."""
        clauses = ["type=page"]
        tt = [t for t in (terms or []) if t and t.strip()]
        if tt:
            ors = " OR ".join('text ~ "%s"' % t.replace('"', "'") for t in tt)
            clauses.append("(%s)" % ors)
        keys = [s.strip() for s in (spaces or []) if s and s.strip()]
        if keys:
            keylist = ", ".join('"%s"' % k.replace('"', "'") for k in keys)
            clauses.append('space %s (%s)' % ("not in" if exclude else "in", keylist))
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

    def get_child_pages(self, page_id: str, limit: int = 100) -> list:
        """Direkte Unterseiten einer Seite (id + title, ohne Inhalt)."""
        d = self._request("GET", "/rest/api/content/%s/child/page" % page_id,
                          params={"limit": limit})
        return [{"id": str(r.get("id")), "title": r.get("title", "")}
                for r in (d.get("results") or [])]

    def get_descendants(self, page_id: str, max_pages: int = 40) -> list:
        """Alle Unterseiten rekursiv (Breitensuche), gedeckelt auf ``max_pages``.

        Der Deckel ist Absicht: ein Confluence-Baum kann hunderte Seiten haben,
        und jede kostet einen HTTP-Aufruf. Wer mehr braucht, gibt mehrere
        Start-Seiten an. Fehler an einem Ast brechen den Lauf NICHT ab – eine
        unlesbare Unterseite darf nicht die ganze Quelle unbrauchbar machen.
        """
        out: list = []
        queue = [str(page_id)]
        seen = {str(page_id)}
        while queue and len(out) < max_pages:
            cur = queue.pop(0)
            try:
                kinder = self.get_child_pages(cur)
            except ConfluenceError:
                continue
            for k in kinder:
                if k["id"] in seen:
                    continue
                seen.add(k["id"])
                out.append(k)
                queue.append(k["id"])
                if len(out) >= max_pages:
                    break
        return out

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

    def attachment_size(self, att: dict) -> int | None:
        """Gemeldete Groesse eines Anhangs aus den Metadaten (oder None)."""
        for src in (att.get("extensions") or {}, att.get("metadata") or {}):
            v = src.get("fileSize")
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    pass
        return None

    def download_attachment(self, page_id: str, filename: str,
                            dest_dir: str = "/tmp") -> tuple[str, int]:
        """Laedt EINEN Anhang authentifiziert herunter. Gibt (Zielpfad, Bytes) zurueck.

        **Warum ueberhaupt eine eigene Methode:** Der Link aus ``list_attachments``
        (``/download/attachments/…``) ist eine **Web-UI-Route**, keine REST-Route. Ein
        ``curl`` darauf laeuft ohne Anmeldung in ``302 -> /login.action`` und schreibt
        wegen fehlendem ``-f`` eine **0 Byte grosse** Datei, ohne zu meckern – genau so
        entstanden am 2026-07-30 sechs leere CSV-Dateien.

        **Und warum sie trotzdem scheitern kann:** Auf diesem Confluence (Server/DC)
        greift vor der Web-Route ein **Zwei-Faktor-Filter**. Der PAT wird akzeptiert,
        die Antwort ist aber ``302`` auf
        ``/plugins/servlet/twofactor/validate_otp`` – folgt man dem, kommt eine
        HTML-Seite mit **HTTP 200** zurueck. Wer die einfach speichert, hat eine
        53 KB grosse HTML-Datei mit der Endung ``.csv`` und merkt es nicht. Eine
        REST-Route fuer die Bytes gibt es auf Server/DC nicht (geprueft:
        ``/rest/api/content/<id>/download``, ``/rest/api/attachment/<id>/download``,
        ``/rest/api/content/<id>/data`` -> alle 404; Basic-Auth mit PAT -> 401).
        Deshalb wird hier NICHT umgeleitet und jede HTML-Antwort als Fehlschlag
        gewertet, mit Klartext-Hinweis, was der Administrator freischalten muss.
        """
        import os
        import re as _re

        atts = self.list_attachments(page_id)
        want = (filename or "").strip()
        match = None
        for a in atts:
            if (a.get("title") or "") == want:
                match = a
                break
        if match is None:                     # Gross-/Kleinschreibung tolerieren
            for a in atts:
                if (a.get("title") or "").lower() == want.lower():
                    match = a
                    break
        if match is None:
            # status=0, damit die eigene Meldung erhalten bleibt: _fmt_err ersetzt
            # 404 durch einen generischen Text und die Namensliste waere weg.
            raise ConfluenceError(0, "Anhang '%s' nicht an Seite %s gefunden. Vorhanden: %s"
                                  % (want, page_id,
                                     ", ".join((a.get("title") or "?") for a in atts) or "keine"))
        dl = (match.get("_links", {}) or {}).get("download", "")
        if not dl:
            raise ConfluenceError(0, "Anhang '%s' hat keinen Download-Link." % want)

        # KEIN allow_redirects: die Umleitung fuehrt auf die Anmelde-/2FA-Seite, und
        # deren HTML kaeme mit HTTP 200 zurueck (siehe Docstring).
        r = requests.get(self.base + dl, headers=self._headers({"Accept": "*/*"}),
                         timeout=60, stream=True, allow_redirects=False)
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("Location", "")
            if "twofactor" in loc or "validate_otp" in loc:
                raise ConfluenceError(0,
                    "Download von '%s' durch die Zwei-Faktor-Pruefung blockiert: der "
                    "Anhang-Link ist eine Web-UI-Route, und der Zugriffstoken darf sie "
                    "nicht passieren (Umleitung auf validate_otp). Abhilfe nur "
                    "serverseitig: den Pfad /download/attachments/* im 2FA-Plugin "
                    "ausnehmen ODER ein Dienstkonto ohne 2FA verwenden. Ein curl/wget "
                    "auf den Link scheitert genauso (leere oder HTML-Datei)." % want)
            raise ConfluenceError(0, "Download von '%s' wurde umgeleitet (HTTP %s -> %s) – "
                                     "nicht angemeldet." % (want, r.status_code, loc[:120]))
        if r.status_code >= 400:
            raise ConfluenceError(r.status_code, "Download fehlgeschlagen (HTTP %s)" % r.status_code)

        ctype = (r.headers.get("Content-Type") or "").lower()
        head = b""
        chunks = []
        total = 0
        for chunk in r.iter_content(chunk_size=65536):
            if not chunk:
                continue
            if not head:
                head = chunk[:200]
            chunks.append(chunk)
            total += len(chunk)

        # Erst pruefen, DANN schreiben – eine falsche Datei soll nie entstehen.
        low = head.lstrip()[:80].lower()
        if "text/html" in ctype or low.startswith(b"<!doctype") or low.startswith(b"<html"):
            raise ConfluenceError(0,
                "Download von '%s' lieferte eine HTML-Seite statt der Datei "
                "(Content-Type %s, %d Byte) – das ist die Anmelde-/2FA-Seite, nicht der "
                "Anhang. Es wurde NICHTS gespeichert." % (want, ctype or "unbekannt", total))
        if total == 0:
            raise ConfluenceError(0, "Anhang '%s' kam leer an (0 Byte, Content-Type %s)."
                                  % (want, ctype or "unbekannt"))
        # Gegen die gemeldete Groesse pruefen: faellt auf, wenn eine Fehlerseite
        # gespeichert wuerde, die nicht als HTML erkennbar ist.
        # Toleranz ist PROZENTUAL (5 %, mindestens 4 Byte) und bewusst nicht absolut:
        # eine feste Untergrenze von 64 Byte liess bei einer 12-Byte-Datei jede
        # Abweichung durch – gerade kleine Dateien braeuchten die Pruefung am meisten.
        # Kein Byte-genauer Vergleich, damit eine geringfuegig abweichende
        # Server-Angabe nicht jeden Download blockiert.
        expect = self.attachment_size(match)
        if expect and abs(total - expect) > max(4, expect * 0.05):
            raise ConfluenceError(0,
                "Anhang '%s' kam in falscher Groesse an (%d Byte, erwartet %d) – "
                "es wurde NICHTS gespeichert." % (want, total, expect))

        # Dateiname aus dem Titel bilden, NICHT aus der URL: der Download-Pfad traegt
        # Query-Parameter (version/modificationDate), die sonst im Namen landen.
        safe = _re.sub(r'[^A-Za-z0-9._-]', "_", os.path.basename(want)).lstrip(".") or "anhang"
        # Zielverzeichnis: bei aktiver Lauf-Isolation das Verzeichnis DIESES
        # Laufs. Der Anhang wird hier vom BACKEND geschrieben, gelesen aber oft
        # per Shell im Lauf – landete er im echten /tmp, waere er dort nicht
        # vorhanden (im Lauf ist /tmp das Lauf-Verzeichnis). Gemeldet wird
        # weiterhin der Modell-Pfad /tmp/<name>, der in beiden Welten stimmt.
        if not dest_dir:
            try:
                from backend import lauf_tmp as _lt
                dest_dir = str(_lt.temp_verzeichnis())
            except Exception:  # noqa: BLE001
                dest_dir = "/tmp"
        os.makedirs(dest_dir, exist_ok=True)
        target = os.path.join(dest_dir, safe)
        with open(target, "wb") as fh:
            for chunk in chunks:
                fh.write(chunk)
        return target, total

    def upload_attachment(self, page_id: str, file_path: str) -> dict:
        import os
        if not os.path.isfile(file_path):
            raise ConfluenceError(0, "Datei nicht gefunden: %s" % file_path)
        with open(file_path, "rb") as fh:
            files = {"file": (os.path.basename(file_path), fh)}
            return self._request(
                "POST", "/rest/api/content/%s/child/attachment" % page_id,
                headers={"X-Atlassian-Token": "no-check"}, files=files)
