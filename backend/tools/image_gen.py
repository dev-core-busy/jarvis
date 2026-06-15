"""Tool zur Bildgenerierung ueber das AKTIVE LLM-Profil.

Wichtig: Es wird NIEMALS der Provider/das Profil gewechselt. Kann das aktive
Profil keine Bilder erzeugen, bekommt der Nutzer eine klare Meldung.
"""

import re
import uuid
import contextvars
from pathlib import Path

from backend.tools.base import BaseTool
from backend.config import config
from backend.llm import get_provider, ImageGenNotSupported

# Generierte Bilder liegen hier und werden ueber /api/generated/<name> ausgeliefert.
_IMG_DIR = Path(__file__).parent.parent.parent / "data" / "generated_images"

# Pro Agent-Task erzeugte/gefundene Bilder. Wird in run_task_headless mit einer
# frischen Liste gesetzt; die Bild-Tools tragen sich hier ein. So koennen Kanaele,
# die kein Markdown rendern (WhatsApp/Telegram/native Apps), das Bild als Medium senden.
current_task_images: contextvars.ContextVar = contextvars.ContextVar(
    "current_task_images", default=None)


def record_task_image(path, url: str) -> None:
    """Merkt ein erzeugtes/gefundenes Bild fuer den aktuellen Task."""
    lst = current_task_images.get()
    if lst is not None:
        lst.append({"path": str(path), "url": url})


_IMG_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*?/api/generated/[0-9a-f]{32}\.[a-z]+\)")
_IMG_URL_RE = re.compile(r"\S*?/api/generated/[0-9a-f]{32}\.[a-z]+")


def strip_image_refs(text: str) -> str:
    """Entfernt Markdown-Bildreferenzen/URLs auf generierte Bilder aus einem Text
    (fuer Kanaele, die das Bild separat als Medium senden)."""
    t = _IMG_MD_RE.sub("", text or "")
    t = _IMG_URL_RE.sub("", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


class GenerateImageTool(BaseTool):
    @property
    def name(self) -> str:
        return "generate_image"

    @property
    def description(self) -> str:
        return (
            "Erzeugt (generiert) ein NEUES Bild per KI aus einer Textbeschreibung, mit dem aktuell "
            "aktiven LLM-Profil. NUR verwenden, wenn der Nutzer ein Bild ERSTELLEN/GENERIEREN lassen "
            "will – Ausloeser-Verben: generiere, erstelle, erzeuge, male, zeichne "
            "(z.B. 'generiere ein Bild von ...', 'erstelle ein Bild von ...', 'male mir ...'). "
            "NICHT verwenden, um vorhandene Bilder zu SUCHEN/anzuzeigen – dafuer gibt es search_image. "
            "Niemals als Ersatz fuer search_image aufrufen."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Praezise Bildbeschreibung (in der Sprache des Nutzers oder Englisch).",
                }
            },
            "required": ["prompt"],
        }

    async def execute(self, **kwargs) -> str:
        prompt = (kwargs.get("prompt") or kwargs.get("text") or kwargs.get("beschreibung") or "").strip()
        if not prompt:
            return "Fehler: Es wurde keine Bildbeschreibung (prompt) angegeben."

        # Provider aus dem AKTIVEN Profil bauen (kein Wechsel!)
        provider = get_provider(
            config.LLM_PROVIDER,
            config.current_api_key,
            config.current_api_url,
            auth_method=config.current_auth_method,
            session_key=config.current_session_key,
            prompt_tool_calling=config.current_prompt_tool_calling,
        )

        try:
            data = await provider.generate_image(config.current_model, prompt)
        except ImageGenNotSupported:
            return (
                "HINWEIS_AN_NUTZER: Das aktuell aktive LLM-Profil kann keine Bilder generieren. "
                "Teile dem Nutzer freundlich mit, dass dafuer ein bildfaehiges Profil aktiviert "
                "werden muss (z.B. ein Google-Gemini-Profil)."
            )
        except Exception as e:
            return f"HINWEIS_AN_NUTZER: Die Bildgenerierung ist fehlgeschlagen: {e}"

        if not data:
            return "HINWEIS_AN_NUTZER: Es wurden keine Bilddaten erzeugt."

        _IMG_DIR.mkdir(parents=True, exist_ok=True)
        fname = f"{uuid.uuid4().hex}.png"
        try:
            (_IMG_DIR / fname).write_bytes(data)
        except Exception as e:
            return f"HINWEIS_AN_NUTZER: Bild konnte nicht gespeichert werden: {e}"

        url = f"/api/generated/{fname}"
        record_task_image(_IMG_DIR / fname, url)
        # Der Agent soll diese Markdown-Bildreferenz UNVERAENDERT in die finale Antwort
        # uebernehmen – alle Frontends rendern sie als Bild.
        return (
            "BILD_ERZEUGT. Gib in deiner finalen Antwort EXAKT die folgende Markdown-Bildreferenz "
            "unveraendert aus (zusammen mit einem kurzen Satz), damit das Bild angezeigt wird:\n\n"
            f"![{prompt[:80]}]({url})"
        )
