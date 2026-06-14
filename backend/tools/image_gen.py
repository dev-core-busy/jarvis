"""Tool zur Bildgenerierung ueber das AKTIVE LLM-Profil.

Wichtig: Es wird NIEMALS der Provider/das Profil gewechselt. Kann das aktive
Profil keine Bilder erzeugen, bekommt der Nutzer eine klare Meldung.
"""

import uuid
from pathlib import Path

from backend.tools.base import BaseTool
from backend.config import config
from backend.llm import get_provider, ImageGenNotSupported

# Generierte Bilder liegen hier und werden ueber /api/generated/<name> ausgeliefert.
_IMG_DIR = Path(__file__).parent.parent.parent / "data" / "generated_images"


class GenerateImageTool(BaseTool):
    @property
    def name(self) -> str:
        return "generate_image"

    @property
    def description(self) -> str:
        return (
            "Generiert ein Bild aus einer Textbeschreibung mit dem aktuell aktiven LLM-Profil "
            "und gibt es zur Anzeige im Chat zurueck. IMMER aufrufen, wenn der Nutzer ein Bild "
            "moechte (z.B. 'bitte ein Bild von einem Berg', 'generiere ein Bild von ...'). "
            "Erfindet keine Bilder selbst – nutze ausschliesslich dieses Tool."
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
        # Der Agent soll diese Markdown-Bildreferenz UNVERAENDERT in die finale Antwort
        # uebernehmen – alle Frontends rendern sie als Bild.
        return (
            "BILD_ERZEUGT. Gib in deiner finalen Antwort EXAKT die folgende Markdown-Bildreferenz "
            "unveraendert aus (zusammen mit einem kurzen Satz), damit das Bild angezeigt wird:\n\n"
            f"![{prompt[:80]}]({url})"
        )
