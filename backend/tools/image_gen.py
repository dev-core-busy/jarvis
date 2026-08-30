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
from backend.llm import ImageGenNotSupported

# Generierte Bilder liegen hier und werden ueber /api/generated/<name> ausgeliefert.
_IMG_DIR = Path(__file__).parent.parent.parent / "data" / "generated_images"

# Pro Agent-Task erzeugte/gefundene Bilder. Wird in run_task_headless mit einer
# frischen Liste gesetzt; die Bild-Tools tragen sich hier ein. So koennen Kanaele,
# die kein Markdown rendern (WhatsApp/Telegram/native Apps), das Bild als Medium senden.
current_task_images: contextvars.ContextVar = contextvars.ContextVar(
    "current_task_images", default=None)

def record_task_image(path, url: str) -> None:
    """Merkt ein erzeugtes/gefundenes Bild fuer den aktuellen Task.

    NICHT ENTFERNEN: ``backend/tools/image_search.py`` importiert diese Funktion
    (``from backend.tools.image_gen import _IMG_DIR, record_task_image``). Beim
    Umbau am 2026-08-10 fiel sie einem Block-Ersatz zum Opfer – Folge: das
    Werkzeug ``search_image`` liess sich nicht mehr laden ("SearchImageTool nicht
    geladen: cannot import name 'record_task_image'") und fehlte still im
    Werkzeugkasten. Aufgefallen nur, weil eine Zaehlung der Werkzeuge es zeigte.

    DIESELBE URL WIRD NUR EINMAL GEMERKT. Die URL ist inhaltsadressiert
    (sha256 des Bildinhalts), dieselbe URL ist also zwangslaeufig dasselbe
    Bild – zweimal anzuzeigen ist nie gewollt. Doppelt registriert wird es bei
    JEDER Delegation an eine Rolle: der Rollen-Agent birgt die Bilddaten aus
    seiner Antwort ("(verlauf)"), der Hauptagent noch einmal aus dem
    Werkzeug-Ergebnis ("delegate:image_builder"). Ohne diese Pruefung haengt
    `_mit_bildern` beide Eintraege an.
    GEMELDET VON ECHT 2026-08-30: eine Antwort endete mit zweimal derselben
    Zeile `![Bild](/api/generated/cb20b70d….png)` – ein Bild, doppelt gezeigt.
    """
    lst = current_task_images.get()
    if lst is None:
        return
    if any((e or {}).get("url") == url for e in lst):
        return
    lst.append({"path": str(path), "url": url})


# Das LLM-Profil des LAUFENDEN Agenten liegt zentral in backend/llm.py (dort
# steht auch die Begruendung). Der alte Name bleibt als Alias erhalten, damit
# vorhandene Importe weiter funktionieren.
from backend.llm import current_agent_profile as current_llm_profile  # noqa: E402
from backend.llm import provider_fuer_lauf  # noqa: E402


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

        # Provider aus dem Profil des LAUFENDEN Agenten bauen (kein Wechsel!):
        # das ist bei einem Rollen-Agenten dessen eigenes Profil, sonst das
        # benutzerbezogene bzw. global aktive.
        provider, modell = provider_fuer_lauf(prompt_tool_calling=False)

        try:
            data = await provider.generate_image(modell, prompt)
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
