"""Tool zur Bildgenerierung.

WELCHES MODELL MALT (geaendert 2026-09-02)
------------------------------------------
Das global eingestellte BILDPROFIL (``config.IMAGE_PROFILE_ID``, Einstellungen
-> KI & System), sonst unveraendert das Profil des laufenden Agenten. Bis dahin
stand hier "es wird NIEMALS das Profil gewechselt" – diese Zusage ist bewusst
aufgegeben: sie traegt in beide Richtungen nicht. Ein Textprofil kann keine
Bilder erzeugen, und ein Bildmodell als Gespraechsmodell kann keine Werkzeuge
aufrufen (am Haus-Server gemessen: FLUX liefert auf ``tools`` ein
``tool_calls: None`` und ein Bild im ``content``). ``generate_image`` war damit
je nach Profil entweder abweisend oder unerreichbar – und im zweiten Fall
verpuffte jede Groessenangabe, weil das Bild am Werkzeug vorbei entstand.

Die vollstaendige Begruendung samt Vorrangregel steht in
``llm.provider_fuer_bild``; die Groessen-Umrechnung in ``llm.bildmasse``.
"""

import re
import uuid
import contextvars
from pathlib import Path

from backend.tools.base import BaseTool
from backend.config import config
from backend import llm
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
from backend.llm import provider_fuer_bild  # noqa: E402


_IMG_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*?/api/generated/[0-9a-f]{32}\.[a-z]+\)")
_IMG_URL_RE = re.compile(r"\S*?/api/generated/[0-9a-f]{32}\.[a-z]+")


def strip_image_refs(text: str) -> str:
    """Entfernt Markdown-Bildreferenzen/URLs auf generierte Bilder aus einem Text
    (fuer Kanaele, die das Bild separat als Medium senden)."""
    t = _IMG_MD_RE.sub("", text or "")
    t = _IMG_URL_RE.sub("", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _endung(data: bytes) -> str:
    """Dateiendung aus den magischen Bytes – Vorgabe ``png``.

    Nur Formen, die ``/api/generated/{name}`` auch ausliefert (dort steht die
    Media-Type-Tabelle). Eine Endung, die der Endpunkt nicht kennt, waere ein
    Bild mit HTTP 400 – also eines, das es gibt und das niemand sieht.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] == b"\xff\xd8":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "png"


def _png_masse(data: bytes):
    """``(breite, hoehe)`` aus dem PNG-Kopf, sonst ``None``.

    Bewusst OHNE Pillow: das Werkzeug laeuft im Backend-Prozess, und ein
    IHDR-Block sind acht Bytes an fester Stelle. Fuer JPEG/WebP wird nichts
    geraten – dann entfaellt die Groessenzeile, statt eine Zahl zu erfinden.
    """
    try:
        if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            return None
        import struct
        w, h = struct.unpack(">II", data[16:24])
        return (int(w), int(h)) if w and h else None
    except Exception:  # noqa: BLE001
        return None


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
            "Niemals als Ersatz fuer search_image aufrufen.\n"
            "GROESSE: Nennt die Aufgabe eine Aufloesung ('1536x640', 'Full HD', "
            "'quadratisch', 'Breitbild', '16:9'), gehoert sie in 'size' bzw. "
            "'aspect_ratio' – NIEMALS in den Prompttext. Im Prompt gelesen wird "
            "sie zum Bildinhalt und bleibt ohne Wirkung."
        )

    def parameters_schema(self) -> dict:
        # DIE GROESSE GEHOERT INS SCHEMA, NICHT IN DEN PROMPTTEXT (Befund
        # 2026-09-02, gemeldet von ECHT): bis dahin kannte das Schema nur
        # `prompt`. Eine Aufloesungsangabe konnte das Modell also gar nicht
        # uebergeben – sie landete im Bildprompt und wurde dort als BILDINHALT
        # gelesen. Am echten Server gemessen: 5 von 5 Laeufen 1024x1024,
        # unabhaengig von der Angabe im Text.
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Praezise Bildbeschreibung (in der Sprache des Nutzers oder Englisch). "
                                   "KEINE Pixelmasse hier hineinschreiben – dafuer gibt es 'size'.",
                },
                "size": {
                    "type": "string",
                    "description": "Optional. Aufloesung in Pixeln als 'BREITExHOEHE', z.B. '1536x640'. "
                                   f"Kanten {llm.BILD_MIN_KANTE}-{llm.BILD_MAX_KANTE} px, "
                                   f"gerundet auf {llm.BILD_RASTER} px. "
                                   "Ohne Angabe entscheidet das Bildmodell (meist 1024x1024).",
                },
                "aspect_ratio": {
                    "type": "string",
                    "description": "Optional. Seitenverhaeltnis, wenn keine genauen Pixel verlangt sind: "
                                   + ", ".join(f"'{v}'" for v in llm.BILD_VERHAELTNISSE)
                                   + ". Wird ignoriert, wenn 'size' gesetzt ist.",
                },
            },
            "required": ["prompt"],
        }

    async def execute(self, **kwargs) -> str:
        prompt = (kwargs.get("prompt") or kwargs.get("text") or kwargs.get("beschreibung") or "").strip()
        if not prompt:
            return "Fehler: Es wurde keine Bildbeschreibung (prompt) angegeben."

        # Fehlertolerant wie beim prompt: Modelle benennen die Felder gern anders.
        roh_size = (kwargs.get("size") or kwargs.get("aufloesung")
                    or kwargs.get("resolution") or kwargs.get("groesse") or "")
        roh_verh = (kwargs.get("aspect_ratio") or kwargs.get("verhaeltnis")
                    or kwargs.get("seitenverhaeltnis") or kwargs.get("ratio") or "")
        try:
            masse = llm.bildmasse(roh_size, roh_verh)
        except llm.BildmassFehler as e:
            # ABWEISEN, NICHT RATEN: eine still verworfene Groessenangabe erzeugt
            # genau den gemeldeten Fehler noch einmal – der Nutzer nennt eine
            # Aufloesung und bekommt eine andere. Das Modell kann sich im selben
            # Schritt korrigieren (Muster des Repair-Loops von create_chart).
            return f"Fehler: {e}"

        # Provider fuer die Bildgenerierung: das eingestellte BILDPROFIL, sonst
        # unveraendert das Profil des laufenden Agenten (Rolle bzw.
        # benutzerbezogen bzw. global aktiv).
        #
        # BIS 2026-09-02 GALT HIER "NIEMALS EIN PROFILWECHSEL" – diese Zusage
        # ist bewusst aufgegeben, weil sie in beide Richtungen nicht traegt:
        # ein Textprofil kann keine Bilder, und ein Bildmodell als Chat-Modell
        # kann keine Werkzeuge aufrufen (am Haus-Server gemessen: FLUX liefert
        # `tool_calls: None`). Ohne die Trennung ist `generate_image` je nach
        # Profil entweder abweisend oder unerreichbar. Die Begruendung steht
        # ausfuehrlich in `llm.provider_fuer_bild`.
        provider, modell = provider_fuer_bild()

        try:
            data = await provider.generate_image(modell, prompt, masse)
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
        # Endung aus den MAGISCHEN BYTES, nicht geraten: bis 2026-09-02 hiess
        # jedes Ergebnis `.png`, weil nur der Google-Weg existierte. Ein
        # OpenAI-kompatibler Bild-Server darf aber JPEG oder WebP liefern, und
        # `/api/generated/{name}` bestimmt den Content-Type aus der ENDUNG –
        # ein JPEG als `.png` waere ein Bild, das es gibt und das der Browser
        # womoeglich nicht anzeigt.
        fname = f"{uuid.uuid4().hex}.{_endung(data)}"
        try:
            (_IMG_DIR / fname).write_bytes(data)
        except Exception as e:
            return f"HINWEIS_AN_NUTZER: Bild konnte nicht gespeichert werden: {e}"

        url = f"/api/generated/{fname}"
        record_task_image(_IMG_DIR / fname, url)

        # DIE GEMESSENEN MASSE, nicht die angeforderten. Ein Modell, das die
        # Wunschgroesse zurueckmeldet, behauptet einen Zustand, den es nicht
        # kennt – der Gemini-Weg kann die Groesse gar nicht erzwingen, und ein
        # Server rundet unter Umstaenden selbst (am echten Server gemessen:
        # 1000x700 kam als 992x688 zurueck).
        echt = _png_masse(data)
        zeile = ""
        if echt:
            zeile = f"\nBildgroesse: {echt[0]}x{echt[1]} px."
            if masse and (echt[0], echt[1]) != (masse["breite"], masse["hoehe"]):
                zeile += (f" ABWEICHUNG von den angeforderten {masse['size']} px – "
                          f"nenne dem Nutzer die tatsaechliche Groesse, nicht die gewuenschte.")
        if masse and masse["hinweis"]:
            zeile += f"\nHinweis zur Groesse: {masse['hinweis']}."

        # Der Agent soll diese Markdown-Bildreferenz UNVERAENDERT in die finale Antwort
        # uebernehmen – alle Frontends rendern sie als Bild.
        return (
            "BILD_ERZEUGT. Gib in deiner finalen Antwort EXAKT die folgende Markdown-Bildreferenz "
            "unveraendert aus (zusammen mit einem kurzen Satz), damit das Bild angezeigt wird:\n\n"
            f"![{prompt[:80]}]({url})" + zeile
        )
