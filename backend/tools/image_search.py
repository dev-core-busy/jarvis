"""Tool: Bild im Web suchen und INLINE im Chat anzeigen (kein Browser auf dem Desktop).

Nutzt die DuckDuckGo-Bildsuche (ohne API-Key), laedt das gefundene Bild lokal und
liefert es ueber /api/generated/<uuid>.<ext> als Markdown-Bild zurueck.
"""

import re
import uuid

from backend.tools.base import BaseTool
from backend.tools.image_gen import _IMG_DIR  # gemeinsames Ausgabe-Verzeichnis

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_EXT_BY_MIME = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
    "image/gif": "gif", "image/webp": "webp",
}


async def _ddg_image_urls(query: str, limit: int = 6) -> list[str]:
    """Liefert Bild-URLs der DuckDuckGo-Bildsuche (ohne API-Key)."""
    import httpx
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True,
                                 headers={"User-Agent": _UA}) as client:
        # 1) vqd-Token von der Suchseite holen
        r = await client.get("https://duckduckgo.com/", params={"q": query})
        vqd = None
        for pat in (r'vqd="([^"]+)"', r"vqd=([\d-]+)\&", r"vqd='([^']+)'"):
            m = re.search(pat, r.text)
            if m:
                vqd = m.group(1)
                break
        if not vqd:
            return []
        # 2) Bild-JSON abrufen
        r2 = await client.get(
            "https://duckduckgo.com/i.js",
            params={"l": "us-en", "o": "json", "q": query, "vqd": vqd,
                    "f": ",,,", "p": "1", "v7exp": "a"},
            headers={"User-Agent": _UA, "Referer": "https://duckduckgo.com/"},
        )
        data = r2.json()
        return [it.get("image") for it in data.get("results", []) if it.get("image")][:limit]


class SearchImageTool(BaseTool):
    @property
    def name(self) -> str:
        return "search_image"

    @property
    def description(self) -> str:
        return (
            "Sucht ein vorhandenes Bild im Web (DuckDuckGo) und zeigt es INLINE im Chat an. "
            "IMMER nutzen, wenn der Nutzer ein Bild SUCHEN/finden und sehen will "
            "('such ein Bild von ...', 'zeig mir ein Bild von ...'). "
            "OEFFNE dafuer NIEMALS einen Browser auf dem Desktop."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Suchbegriff fuer das Bild, z.B. 'Berg'."}
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs) -> str:
        query = (kwargs.get("query") or kwargs.get("prompt") or kwargs.get("text") or "").strip()
        if not query:
            return "Fehler: Es wurde kein Suchbegriff (query) angegeben."

        try:
            urls = await _ddg_image_urls(query)
        except Exception as e:
            return f"HINWEIS_AN_NUTZER: Bildsuche fehlgeschlagen: {e}"
        if not urls:
            return f"HINWEIS_AN_NUTZER: Es wurde kein Bild zu '{query}' gefunden."

        import httpx
        _IMG_DIR.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True,
                                     headers={"User-Agent": _UA}) as client:
            for url in urls:
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    mime = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    ext = _EXT_BY_MIME.get(mime)
                    if not ext:
                        continue
                    if len(resp.content) > 10 * 1024 * 1024 or len(resp.content) < 200:
                        continue
                    fname = f"{uuid.uuid4().hex}.{ext}"
                    (_IMG_DIR / fname).write_bytes(resp.content)
                    local = f"/api/generated/{fname}"
                    return (
                        "BILD_GEFUNDEN. Gib in deiner finalen Antwort EXAKT die folgende "
                        "Markdown-Bildreferenz unveraendert aus (mit einem kurzen Satz), damit das "
                        f"Bild angezeigt wird:\n\n![{query[:80]}]({local})"
                    )
                except Exception:
                    continue
        return f"HINWEIS_AN_NUTZER: Gefundene Bilder zu '{query}' konnten nicht geladen werden."
