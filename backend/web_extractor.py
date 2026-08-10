"""Jarvis Web-Extraktor – URL / Datei abrufen, per LLM strukturieren, als Pending-Dokument speichern."""

import asyncio
import json
import logging
import re
import time
import uuid
from pathlib import Path

_log = logging.getLogger("jarvis.extractor")

# Absolut ableiten, nicht relativ zum Arbeitsverzeichnis: sonst legt jeder
# Aufrufer ausserhalb des Dienstes (Wartungsskript, Cron, Test) seine Entwuerfe
# woanders ab – und dort greift _is_pending_path() nicht, die Entwuerfe wuerden
# als Wissen indiziert.
PROJECT_ROOT = Path(__file__).parent.parent
PENDING_DIR = PROJECT_ROOT / "data" / "knowledge" / "pending"

# Vorhaltezeit fuer bereits uebernommene Entwuerfe (Revisionsspur: "was schlug
# das Modell vor, was machte der Mensch daraus"). 0 = nie aufraeumen.
APPROVED_RETENTION_DAYS = 90

# ─── LLM-Prompt ──────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = """\
Analysiere den folgenden Inhalt und erstelle eine strukturierte Wissensextraktion.

Ausgabe AUSSCHLIESSLICH als valides JSON-Objekt mit diesen Feldern:
{
  "title": "Prägnanter Titel des Inhalts",
  "summary": "Zusammenfassung in 3-5 Sätzen",
  "facts": [
    "Kernfakt 1 als vollständiger Satz",
    "Kernfakt 2 als vollständiger Satz"
  ],
  "qa_pairs": [
    {"q": "Frage 1?", "a": "Antwort 1."},
    {"q": "Frage 2?", "a": "Antwort 2."}
  ]
}

Regeln:
- Sprache: Deutsch (auch wenn der Quelltext Englisch ist)
- 3–10 Kernfakten
- {qa_rule}
- Keine Quellenangaben, keine URLs in den Antworten
- Kein Markdown, keine Code-Blöcke um das JSON

Inhalt:
---
{content}
---
"""

_QA_RULE_DEFAULT = "5–15 Frage-Antwort-Paare – präzise, eigenständig verständlich, direkt aus dem Inhalt"


# Regel fuer "gar keine Fragen erzeugen". Der Schluessel muss trotzdem im JSON
# stehen, sonst weicht das Modell vom vorgegebenen Schema ab.
_QA_RULE_NONE = ('KEINE Frage-Antwort-Paare. Das Feld "qa_pairs" MUSS ein leeres '
                 'Array [] sein – erfinde auf keinen Fall Fragen')


def _clamp_qa_count(qa_count) -> int | None:
    """Gewuenschte Fragenanzahl validieren.

    Rueckgabe:
      ``None`` – kein Wunsch angegeben (unbrauchbare Eingabe) -> Default-Regel
      ``0``    – AUSDRUECKLICH keine Fragen erzeugen
      1..50    – genau diese Anzahl

    Die 0 war bis 2026-07-28 nicht von "kein Wunsch" zu unterscheiden (beides
    ``None``) – deshalb erzeugte der Extraktor auch dann Fragen, wenn der Haken
    „Fragen & Antworten generieren (KI)" AUS war. Aufrufer duerfen daher NICHT
    per Falsyness pruefen (``if n:``), sondern muessen ``n == 0`` abfragen.
    """
    try:
        n = int(qa_count)
    except (TypeError, ValueError):
        return None
    return max(1, min(n, 50)) if n > 0 else 0


def _build_prompt(content: str, qa_count=None) -> str:
    """Extraktions-Prompt bauen; qa_count = vom Benutzer gewuenschte Fragenanzahl."""
    n = _clamp_qa_count(qa_count)
    if n == 0:
        rule = _QA_RULE_NONE
    elif n:
        rule = (f"genau {n} Frage-Antwort-Paare – präzise, eigenständig verständlich, "
                f"direkt aus dem Inhalt")
    else:
        rule = _QA_RULE_DEFAULT
    return _EXTRACT_PROMPT.replace("{qa_rule}", rule).replace("{content}", content)


def _drop_qa_if_unwanted(qa_list, qa_count):
    """Erzwingt "keine Fragen" auch dann, wenn das Modell die Anweisung ignoriert.

    Ein Prompt ist eine Bitte, keine Garantie – ohne diese Schranke landen bei
    ``qa_count=0`` trotzdem Fragen im Entwurf.
    """
    return [] if _clamp_qa_count(qa_count) == 0 else qa_list


def _profile_provider(prof=None):
    """(provider, model) fuer die Extraktion – aus dem uebergebenen LLM-Profil
    (per-User, z.B. Pulldown auf /wissen) oder dem globalen Aktiv-Profil."""
    from backend.config import config
    from backend.llm import get_provider
    p = prof or config.active_profile or {}
    if p:
        provider = get_provider(
            p.get("provider", "google"), p.get("api_key", ""), p.get("api_url", ""),
            auth_method=p.get("auth_method", "api_key"),
            session_key=p.get("session_key", ""), prompt_tool_calling=False,
        )
        return provider, p.get("model", "")
    # Alt-Konfiguration ohne Profile
    # Kein Profil uebergeben: dann das des LAUFENDEN Agenten, sonst das global
    # aktive (llm.provider_fuer_lauf). Ausserhalb eines Agentenlaufs – und dort
    # liegen alle heutigen Aufrufer – ist das Verhalten unveraendert.
    from backend.llm import provider_fuer_lauf
    return provider_fuer_lauf(prompt_tool_calling=False)


# ─── Abschnittsweise Extraktion ──────────────────────────────────────────────
# Bis 2026-08-01 sah der Extraktor nur die ERSTEN 8000 Zeichen eines Dokuments.
# Bei einem laengeren Handbuch fiel alles danach STILL weg – niemand erfuhr,
# dass zwei Drittel nie betrachtet wurden. Das war der unangenehmste Teil: der
# Fehler war unsichtbar, das Ergebnis sah vollstaendig aus.
FENSTER_ZEICHEN = 8000
# Ueberlappung, damit ein Fakt oder eine Anleitung, die genau auf der Grenze
# liegt, nicht in BEIDEN Fenstern halbiert ankommt und in keinem verwertbar ist.
FENSTER_UEBERLAPPUNG = 400
# Deckel. 12 Fenster sind rund 92.000 Zeichen (~14.000 Woerter) und zwoelf
# LLM-Aufrufe. Darueber hinaus waere der Import weder bezahlbar noch abwartbar;
# was nicht mehr betrachtet wurde, wird AUSGEWIESEN statt verschwiegen.
MAX_FENSTER = 12


def _fenster(text: str) -> list[str]:
    """Zerlegt den Text in ueberlappende Fenster, moeglichst an Absatzgrenzen.

    Der Schnitt wandert bis zu 600 Zeichen zurueck, um einen Absatz- oder
    Satzwechsel zu treffen. Mitten im Satz zu trennen kostet an beiden Seiten
    Verstaendlichkeit – das Modell erfindet dann den fehlenden Rest dazu.
    """
    text = text or ""
    if len(text) <= FENSTER_ZEICHEN:
        return [text] if text.strip() else []
    out, pos = [], 0
    while pos < len(text) and len(out) < MAX_FENSTER:
        ende = min(pos + FENSTER_ZEICHEN, len(text))
        if ende < len(text):
            fenster = text[pos:ende]
            for trenner in ("\n\n", "\n", ". "):
                schnitt = fenster.rfind(trenner)
                if schnitt > FENSTER_ZEICHEN - 600:
                    ende = pos + schnitt + len(trenner)
                    break
        stueck = text[pos:ende]
        if stueck.strip():
            out.append(stueck)
        if ende >= len(text):
            break
        pos = max(ende - FENSTER_UEBERLAPPUNG, pos + 1)
    return out


def _norm_key(s: str) -> str:
    """Vergleichsform fuer Dubletten zwischen Fenstern (Klein, ohne Satzzeichen)."""
    return re.sub(r"[^a-z0-9äöüß ]+", "", str(s).lower()).strip()


async def _extract_ein_fenster(content: str, fallback_title: str, qa_count, prof) -> dict:
    """Ein LLM-Durchgang ueber genau ein Fenster."""
    from google.genai import types
    provider, _model = _profile_provider(prof)
    prompt = _build_prompt(content, qa_count)
    response = await provider.generate_response(
        model=_model,
        system_prompt="Du bist ein Wissensextraktor. Antworte ausschließlich mit dem angeforderten JSON.",
        contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
        tools=[],
    )
    raw_text = "".join(p.text for p in (response.parts or []) if getattr(p, "text", None))
    m = re.search(r'\{[\s\S]*\}', raw_text)
    if not m:
        raise ValueError(f"LLM lieferte kein gültiges JSON: {raw_text[:200]}")
    data = json.loads(m.group(0))
    return {
        "title": str(data.get("title", fallback_title)).strip()[:300],
        "summary": str(data.get("summary", "")).strip(),
        "facts": [str(f).strip() for f in data.get("facts", []) if str(f).strip()],
        "qa_pairs": [{"q": str(p.get("q", "")).strip(), "a": str(p.get("a", "")).strip()}
                     for p in data.get("qa_pairs", []) if str(p.get("q", "")).strip()],
    }


async def extract_structured_from_text(text: str, fallback_title: str = "", qa_count=None,
                                        prof: dict = None) -> dict:
    """Schickt beliebigen Text durch den Wissensextraktor-LLM und liefert
    {title, summary, facts, qa_pairs, coverage}.

    Lange Texte werden ABSCHNITTSWEISE verarbeitet und die Ergebnisse
    zusammengefuehrt – vorher sah das Modell nur die ersten 8000 Zeichen.

    ``coverage`` beschreibt, WIE VIEL tatsaechlich betrachtet wurde:
    ``{chars_total, chars_seen, windows, truncated}``. Das Feld ist der Kern
    der Aenderung: selbst wenn ein Dokument den Deckel sprengt, ist der Verlust
    ab jetzt SICHTBAR statt stillschweigend.

    qa_count: gewuenschte Fragenanzahl fuer das GESAMTE Dokument (nicht je
    Fenster – sie wird verteilt und am Ende zugeschnitten).
    prof: LLM-Profil des Benutzers (None = globales Aktiv-Profil).
    """
    ganz = text or ""
    fenster = _fenster(ganz)
    if not fenster:
        return {"title": fallback_title, "summary": "", "facts": [], "qa_pairs": [],
                "coverage": {"chars_total": len(ganz), "chars_seen": 0,
                             "windows": 0, "truncated": False}}

    # Fragen auf die Fenster verteilen. Ohne das liefert jedes Fenster die volle
    # Anzahl – bei 8 Fenstern und "10 Fragen" waeren es 80.
    if qa_count is None:
        je_fenster = None
    elif qa_count == 0:
        je_fenster = 0
    else:
        je_fenster = max(1, -(-int(qa_count) // len(fenster)))

    titel = fallback_title
    zusammen: list[str] = []
    fakten: list[str] = []
    fakten_gesehen: set[str] = set()
    qa: list[dict] = []
    qa_gesehen: set[str] = set()

    for i, stueck in enumerate(fenster):
        try:
            teil = await _extract_ein_fenster(stueck, fallback_title, je_fenster, prof)
        except Exception as e:
            # EIN gescheitertes Fenster darf nicht das ganze Dokument kosten.
            # Bei einem einzigen Fenster gibt es aber nichts zu retten – dann
            # bleibt die Ausnahme, sonst entstuende ein leerer Entwurf ohne
            # erkennbaren Grund.
            if len(fenster) == 1:
                raise
            _log.warning("Extraktion: Abschnitt %d/%d fehlgeschlagen: %s", i + 1, len(fenster), e)
            continue
        # Der Titel kommt aus dem ERSTEN Fenster: dort steht die Ueberschrift des
        # Dokuments. Spaetere Fenster benennen nur ihren Abschnitt.
        if i == 0 and teil.get("title"):
            titel = teil["title"]
        if teil.get("summary"):
            zusammen.append(teil["summary"])
        for f in teil.get("facts", []):
            k = _norm_key(f)
            if k and k not in fakten_gesehen:
                fakten_gesehen.add(k)
                fakten.append(f)
        for p in teil.get("qa_pairs", []):
            k = _norm_key(p.get("q", ""))
            if k and k not in qa_gesehen:
                qa_gesehen.add(k)
                qa.append(p)

    gesehen = sum(len(s) for s in fenster) - FENSTER_UEBERLAPPUNG * max(0, len(fenster) - 1)
    coverage = {
        "chars_total": len(ganz),
        "chars_seen": min(max(gesehen, 0), len(ganz)),
        "windows": len(fenster),
        "truncated": len(fenster) >= MAX_FENSTER and gesehen < len(ganz),
    }
    # Mehrere Zusammenfassungen bleiben getrennt stehen, statt sie durch einen
    # weiteren LLM-Aufruf zu verschmelzen: das waere ein zusaetzlicher
    # Kostenpunkt und eine weitere Fehlerquelle, und die Zusammenfassung ist im
    # Audit ohnehin bearbeitbar. Der Mensch sieht so ausserdem die Gliederung.
    summary = "\n\n".join(zusammen)
    return {
        "title": titel,
        "summary": summary,
        "facts": fakten,
        "qa_pairs": _drop_qa_if_unwanted(qa[:int(qa_count)] if qa_count else qa, qa_count),
        "coverage": coverage,
    }


async def extract_to_pending(text: str, title: str = "", source: str = "",
                             qa_count=None, prof: dict = None) -> dict:
    """Beliebigen Text → strukturierte Extraktion → gespeichertes Pending-Dokument.

    Wiederverwendbar fuer Quellen ohne eigene Datei-/HTTP-Pipeline (z.B. Confluence).
    ``source`` wird als Herkunft/Link im Pending-Dokument hinterlegt.
    ``qa_count``: 0 = ausdruecklich keine Fragen, 1..50 = genau so viele,
    None = Default-Regel. Fehlte bis 2026-07-28 komplett – der Confluence-Import
    erzeugte deshalb IMMER Fragen, egal was in der Oberflaeche eingestellt war.
    ``prof``: LLM-Profil des Benutzers (None = globales Aktiv-Profil).
    """
    structured = await extract_structured_from_text(text, fallback_title=title,
                                                   qa_count=qa_count, prof=prof)
    doc_id = str(uuid.uuid4())[:8]
    qa_pairs = _drop_qa_if_unwanted([
        {"id": str(uuid.uuid4())[:6], "q": p.get("q", ""), "a": p.get("a", ""),
         "approved": True}
        for p in structured.get("qa_pairs", []) if p.get("q")
    ], qa_count)
    pending = {
        "id": doc_id,
        "url": source,
        "title": (structured.get("title") or title or "Dokument")[:300],
        "summary": structured.get("summary", ""),
        "facts": structured.get("facts", []),
        "qa_pairs": qa_pairs,
        # Wie viel des Dokuments tatsaechlich betrachtet wurde – gehoert an den
        # Entwurf, damit die Pruefansicht es zeigen kann.
        "coverage": structured.get("coverage"),
        "created_at": int(time.time()),
        "status": "pending",
    }
    save_pending(pending)
    return pending


# ─── Datei-Typ Erkennung ─────────────────────────────────────────────────────

# Content-Type → Dateiendung für direkte Datei-Downloads via URL
_CT_TO_SUFFIX: dict[str, str] = {
    "application/pdf":                                                          ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword":                                                       ".doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":       ".xlsx",
    "application/vnd.ms-excel":                                                 ".xls",
    "application/vnd.oasis.opendocument.spreadsheet":                          ".ods",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/csv":                                                                 ".csv",
    "audio/mpeg":   ".mp3",
    "audio/mp4":    ".m4a",
    "audio/wav":    ".wav",
    "audio/ogg":    ".ogg",
    "video/mp4":    ".mp4",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "image/jpeg":   ".jpg",
    "image/png":    ".png",
    "image/gif":    ".gif",
    "image/bmp":    ".bmp",
    "image/webp":   ".webp",
    "image/tiff":   ".tiff",
}
_FILE_SUFFIXES: frozenset[str] = frozenset(
    ".pdf .docx .doc .xlsx .xls .ods .pptx .csv "
    ".mp3 .m4a .wav .ogg .mp4 .mov .mkv .avi "
    ".jpg .jpeg .png .gif .bmp .tif .tiff .webp".split()
)

# Bild-Endung -> MIME (fuer den optionalen Vision-Pass an das LLM)
_IMAGE_MIME: dict[str, str] = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
    ".tif": "image/tiff", ".tiff": "image/tiff",
}


# ─── URL abrufen ─────────────────────────────────────────────────────────────

async def _http_get(url: str):
    """Führt einen GET-Request aus und gibt das httpx-Response-Objekt zurück."""
    try:
        import httpx
    except ImportError:
        raise RuntimeError("httpx nicht installiert. Bitte: pip install httpx")

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; JarvisBot/1.0; +https://jarvis-ai.info)",
        "Accept": "*/*",
        "Accept-Language": "de,en;q=0.7",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp


def _html_to_text(html: str) -> tuple[str, str]:
    """Einfache HTML→Text Konvertierung ohne externe Deps."""
    # Titel extrahieren
    title_m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    title = _strip_tags(title_m.group(1)) if title_m else "Unbekannter Titel"
    title = title.strip()[:200]

    # Script/Style/Nav/Footer entfernen
    for tag in ('script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript'):
        html = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', ' ', html, flags=re.I | re.S)

    # Blockstruktur mit Leerzeilen
    for tag in ('p', 'div', 'section', 'article', 'h1', 'h2', 'h3', 'h4', 'li', 'br', 'tr'):
        html = re.sub(rf'</?{tag}[^>]*>', '\n', html, flags=re.I)

    # Restliche Tags entfernen
    text = _strip_tags(html)

    # Whitespace normalisieren
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if len(l) > 2]
    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return title, text.strip()


def _strip_tags(html: str) -> str:
    return re.sub(r'<[^>]+>', '', html)


# ─── LLM-Extraktion ──────────────────────────────────────────────────────────

async def extract_from_url(url: str, qa_count=None, prof: dict = None) -> dict:
    """URL → strukturiertes Pending-Dokument.
    Erkennt automatisch ob die URL auf eine HTML-Seite oder eine Datei zeigt
    (PDF, DOCX, XLSX, PPTX, Audio/Video …) und wählt die passende Pipeline.
    qa_count: gewuenschte Anzahl Frage-Antwort-Paare; prof: LLM-Profil des Benutzers."""
    from pathlib import Path as _Path

    resp = await _http_get(url)

    # Content-Type auswerten (nur Typ, ohne Parameter wie charset)
    ct = resp.headers.get("content-type", "").lower().split(";")[0].strip()
    url_suffix = _Path(url.split("?")[0]).suffix.lower()

    # Datei-Pipeline? → Content-Type hat Vorrang, dann URL-Endung
    detected_suffix = _CT_TO_SUFFIX.get(ct) or (url_suffix if url_suffix in _FILE_SUFFIXES else None)

    if detected_suffix:
        # Dateiname aus URL ableiten
        raw_name = _Path(url.split("?")[0]).name
        filename = raw_name if raw_name.endswith(detected_suffix) else (raw_name or "dokument") + detected_suffix
        # Datei-Pipeline mit Original-URL als Quelle
        return await extract_from_file(filename, resp.content, source_url=url,
                                       qa_count=qa_count, prof=prof)

    # ── HTML-Pipeline ──────────────────────────────────────────────────────────
    page_title, content = _html_to_text(resp.text)
    if not content.strip():
        raise ValueError("Seite enthält keinen lesbaren Text")

    # Ueber die GEMEINSAME Funktion, nicht mit eigener LLM-Logik: hier stand
    # bis 2026-08-01 eine zweite, fast identische Kopie des Aufrufs samt
    # eigenem `content[:8000]`. Lange Webseiten wurden dadurch abgeschnitten,
    # auch nachdem die abschnittsweise Verarbeitung existierte – und jede
    # kuenftige Aenderung am Extraktor haette man an zwei Stellen machen muessen.
    structured = await extract_structured_from_text(
        content, fallback_title=page_title, qa_count=qa_count, prof=prof)

    qa_pairs = _drop_qa_if_unwanted([
        {"id": str(uuid.uuid4())[:6], "q": p.get("q", ""), "a": p.get("a", ""),
         "approved": True}
        for p in structured.get("qa_pairs", []) if p.get("q")
    ], qa_count)

    pending = {
        "id": str(uuid.uuid4())[:8],
        "url": url,
        "title": structured.get("title") or page_title,
        "summary": structured.get("summary", ""),
        "facts": structured.get("facts", []),
        "qa_pairs": qa_pairs,
        "coverage": structured.get("coverage"),
        "created_at": int(time.time()),
        "status": "pending",
    }

    save_pending(pending)
    return pending


# ─── Pending-Dokument-Verwaltung ─────────────────────────────────────────────

def _ensure_dir():
    PENDING_DIR.mkdir(parents=True, exist_ok=True)


def save_pending(doc: dict) -> str:
    _ensure_dir()
    path = PENDING_DIR / f"{doc['id']}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc["id"]


def list_pending() -> list[dict]:
    _ensure_dir()
    result = []
    for f in sorted(PENDING_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            result.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return result


def get_pending(doc_id: str) -> dict | None:
    path = PENDING_DIR / f"{doc_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def update_pending(doc_id: str, data: dict) -> bool:
    doc = get_pending(doc_id)
    if not doc:
        return False
    # Erlaubte Felder aktualisieren. created_by: Ersteller-Zuordnung fuer /wissen
    # (dortige Pending-Liste zeigt nur EIGENE Entwuerfe – ohne dieses Feld wuerde
    # jeder Entwurf herausgefiltert und "unten" bliebe leer).
    for field in ("title", "summary", "facts", "qa_pairs", "created_by"):
        if field in data:
            doc[field] = data[field]
    save_pending(doc)
    return True


def _target_dir_for_groups(groups) -> Path:
    """Zielordner fuer ein freigegebenes Dokument.

    Bevorzugt einen Speicherordner der gewaehlten Wissensgruppe – dort liegt auch
    die hochgeladene Originaldatei. Vorher landete jeder Extrakt im ERSTEN
    konfigurierten Ordner (in der Regel ``data/knowledge``), also ausgerechnet in
    dem Ordner, den /wissen als Ablageziel gar nicht anbietet: Original und
    Extrakt lagen dann in verschiedenen Ordnern.
    Rueckfall bleibt der erste konfigurierte Ordner.
    """
    from backend.tools.knowledge import _get_folders, PROJECT_ROOT as _ROOT
    folders = _get_folders()
    default = folders[0]
    if not groups:
        return default
    try:
        from backend import knowledge_groups as kg
        configured = {str(f) for f in folders}
        for gid in groups:
            g = kg.get_group(gid) or {}
            for rel in g.get("folders", []):
                cand = Path(rel)
                if not cand.is_absolute():
                    cand = _ROOT / rel
                if str(cand) in configured:
                    return cand
    except Exception:
        pass
    return default


def _index_single_file(path: Path, content: str) -> bool:
    """Haengt EINE neue Wissensdatei sofort in den Vektor-Index ein.

    Ersetzt den frueheren ``force_reindex()``-Aufruf. Der baute den Index mit
    ``vs.clear()`` von Grund auf neu – fuer eine einzige neue Markdown-Datei
    wurde die gesamte Wissensdatenbank erneut geparst und eingebettet (auf dem
    Produktivsystem 893 Dateien inkl. PDF/OCR/Whisper), und waehrend des Laufs
    war der Index leer, sodass JEDE Suche "keine Treffer" meldete.

    Gleiches Muster wie ``learning.py::_index_immediately()``.
    Gibt False zurueck, wenn kein Vektor-Index verfuegbar ist (dann muss der
    Aufrufer den TF-IDF-Weg gehen).
    """
    try:
        from backend.tools.knowledge import (_get_vector_store, _chunk_text,
                                             invalidate_files_cache)
        vs = _get_vector_store()
        if vs is None:
            return False
        chunks = _chunk_text(content)
        if chunks:
            vs.add_chunks(str(path), chunks, path.stat().st_mtime)
        invalidate_files_cache()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[Extraktor] Sofort-Indizierung fehlgeschlagen ({e}) – "
              f"fallback auf Reindex", flush=True)
        return False


def approve_pending(doc_id: str, reindex: bool = True, groups=None) -> dict:
    """Genehmigte Items als .md in die Wissens-DB schreiben.
    Das Pending-Dokument bleibt erhalten (status='approved') fuer die Verlaufsansicht.
    ``reindex=False`` ueberspringt die Index-Aktualisierung (fuer Bulk-Importe).
    ``groups`` (optional): Liste von Gruppen-IDs, denen das erzeugte Dokument als
    logisches Tag zugeordnet wird (Modell B)."""
    doc = get_pending(doc_id)
    if not doc:
        raise FileNotFoundError(f"Pending-Dokument {doc_id} nicht gefunden")

    from backend.tools.knowledge import PROJECT_ROOT, force_reindex

    target_dir = _target_dir_for_groups(groups)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Sicherer Dateiname
    safe_title = re.sub(r'[^\w\s\-äöüÄÖÜß]', '', doc["title"])
    safe_title = re.sub(r'\s+', '_', safe_title.strip())[:60]
    filename = f"extract_{doc_id}_{safe_title}.md"
    target_path = target_dir / filename

    # Markdown-Dokument aufbauen
    source_label = doc.get("source_name") or doc.get("url", "")
    lines = [f"# {doc['title']}", "", f"> Quelle: {source_label}", ""]

    if doc.get("summary"):
        lines += ["## Zusammenfassung", "", doc["summary"], ""]

    approved_facts = doc.get("facts", [])
    if approved_facts:
        lines += ["## Kernfakten", ""]
        for fact in approved_facts:
            lines.append(f"- {fact}")
        lines.append("")

    approved_qa = [p for p in doc.get("qa_pairs", []) if p.get("approved", True)]
    if approved_qa:
        lines += ["## Fragen & Antworten", ""]
        for pair in approved_qa:
            if pair.get("q") and pair.get("a"):
                lines += [f"**F: {pair['q']}**", f"A: {pair['a']}", ""]

    md_content = "\n".join(lines)
    target_path.write_text(md_content, encoding="utf-8")

    # Pending-Dokument als "approved" markieren (nicht loeschen – Verlauf erhalten)
    doc["status"] = "approved"
    doc["approved_at"] = int(time.time())
    # Wissensordner duerfen ABSOLUT und ausserhalb des Projektverzeichnisses
    # liegen (Netzlaufwerke sind ausdruecklich vorgesehen). relative_to() wirft
    # dann ValueError – und zwar NACHDEM die Datei schon geschrieben wurde: die
    # Freigabe endete mit HTTP 500, der Entwurf blieb "offen", die Datei lag
    # aber bereits im Ordner. Beim Testen aufgefallen (2026-07-30).
    try:
        doc["file"] = str(target_path.relative_to(PROJECT_ROOT))
    except ValueError:
        doc["file"] = str(target_path)
    doc["qa_count"] = len(approved_qa)
    doc["fact_count"] = len(approved_facts)
    save_pending(doc)

    # Gruppenzuordnung (logische Tags) fuer das erzeugte Dokument setzen.
    if groups:
        try:
            from backend import knowledge_groups as kg
            kg.set_assignment(doc["file"], groups)
        except Exception:
            pass

    # Neue Datei in den Index einhaengen. Das ist ein Anhaengen (Millisekunden),
    # KEIN Neuaufbau – siehe _index_single_file().
    if reindex and not _index_single_file(target_path, md_content):
        # Kein Vektor-Index verfuegbar (nur TF-IDF): dort bleibt der Voll-Lauf
        # der einzige Weg, den Bestand nachzuziehen.
        def _reindex_and_trim():
            force_reindex()
            try:
                from backend.tools.vector_store import release_memory_to_os
                release_memory_to_os()
            except Exception:
                pass

        import threading
        threading.Thread(target=_reindex_and_trim, daemon=True).start()

    return {
        "file": doc["file"],
        "qa_count": len(approved_qa),
        "fact_count": len(approved_facts),
    }


def delete_pending(doc_id: str) -> bool:
    path = PENDING_DIR / f"{doc_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def cleanup_approved(days: int = None) -> int:
    """Raeumt uebernommene Entwuerfe nach Ablauf der Vorhaltezeit ab.

    OFFENE Entwuerfe werden NIE geloescht – nur was bereits in der
    Wissensdatenbank steht (``status='approved'``). Ohne diese Routine wuchs
    ``pending/`` unbegrenzt, und ``list_pending()`` liest bei jedem Aufruf alle
    Dateien. Gibt die Anzahl geloeschter Dateien zurueck.
    """
    limit = APPROVED_RETENTION_DAYS if days is None else int(days)
    if limit <= 0:
        return 0
    cutoff = time.time() - limit * 86400
    removed = 0
    try:
        _ensure_dir()
        for f in PENDING_DIR.glob("*.json"):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
                if str(doc.get("status") or "") != "approved":
                    continue
                stamp = float(doc.get("approved_at") or doc.get("created_at") or 0)
                if stamp and stamp < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:  # noqa: BLE001 – eine kaputte Datei stoppt nicht den Rest
                continue
    except Exception:  # noqa: BLE001
        return removed
    return removed


# ─── Datei-Extraktion ────────────────────────────────────────────────────────

async def extract_from_file(filename: str, content: bytes, source_url: str | None = None,
                            qa_count=None, prof: dict = None) -> dict:
    """Datei → Text-Extraktion → LLM → Pending-Dokument.
    Unterstützt: PDF, DOCX, XLSX, PPTX, TXT, MD, CSV und Audio/Video via Whisper.
    source_url: wird gesetzt wenn die Datei über eine URL heruntergeladen wurde.
    qa_count: vom Benutzer gewuenschte Anzahl Frage-Antwort-Paare (1..50).
    prof: LLM-Profil des Benutzers (None = globales Aktiv-Profil)."""
    import asyncio as _asyncio
    import os as _os
    import tempfile as _tempfile
    from pathlib import Path as _Path

    suffix = _Path(filename).suffix.lower() or ".bin"

    # Temp-Datei mit korrektem Suffix anlegen (damit _extract_text das Format erkennt)
    fd, tmp_path = _tempfile.mkstemp(suffix=suffix, prefix="jarvis_ext_")
    try:
        _os.close(fd)
        _Path(tmp_path).write_bytes(content)

        # Blockierende Text-Extraktion (PDF-Parsing, Whisper, …) im Thread ausführen
        from backend.tools.knowledge import _extract_text
        text = await _asyncio.to_thread(
            _extract_text, _Path(tmp_path), 50 * 1024 * 1024
        )
    finally:
        try:
            _os.unlink(tmp_path)
        except Exception:
            pass

    is_image = suffix in _IMAGE_MIME
    ocr_text = (text or "").strip()

    if is_image:
        # Bilder: NICHT abbrechen, wenn OCR leer ist – ein vision-faehiges LLM kann das
        # Bild trotzdem auswerten. Der OCR-Text wird zur Pruefung/Korrektur mitgegeben.
        content_for_llm = (
            f"[Bild: {filename}]\n\n"
            f"Per OCR (Tesseract) erkannter Text:\n{ocr_text or '(kein Text per OCR erkannt)'}\n\n"
            "Aufgabe: Pruefe und korrigiere den OCR-Text anhand des Bildes und beschreibe "
            "relevante visuelle Inhalte (Diagramme, Tabellen, Objekte, Beschriftungen). "
            "Extrahiere daraus das Wissen."
        )[:8000]
    else:
        if not ocr_text:
            raise ValueError(
                f"Datei enthält keinen extrahierbaren Text (Format: {suffix}). "
                "Unterstützt: PDF, DOCX, XLSX, PPTX, TXT, MD, CSV, Bilder (OCR via Tesseract), "
                "MP3/M4A/WAV (Transkription via Whisper), MP4/MOV/MKV."
            )
        # TEXTDATEIEN GEHEN UEBER DIE ABSCHNITTSWEISE EXTRAKTION.
        # Hier stand bis 2026-08-01 `ocr_text[:8000]` – ein hochgeladenes
        # Handbuch wurde also nach den ersten Seiten abgeschnitten, ohne dass
        # es irgendwo auftauchte. Das ist der Hauptfall dieser Funktion.
        # Der BILD-Pfad unten bleibt einstufig: dort haengt das Bild selbst am
        # Aufruf (Vision), und ein Bild ist eine Seite – 8000 Zeichen OCR
        # reichen dafuer.
        structured = await extract_structured_from_text(
            f"[Datei: {filename}]\n\n{ocr_text}",
            fallback_title=filename, qa_count=qa_count, prof=prof)
        qa_pairs = _drop_qa_if_unwanted([
            {"id": str(uuid.uuid4())[:6], "q": p.get("q", ""), "a": p.get("a", ""),
             "approved": True}
            for p in structured.get("qa_pairs", []) if p.get("q")
        ], qa_count)
        pending = {
            "id":          str(uuid.uuid4())[:8],
            "url":         source_url or f"file://{filename}",
            "source_type": "url" if source_url else "file",
            "source_name": filename,
            "title":       structured.get("title") or filename,
            "summary":     structured.get("summary", ""),
            "facts":       structured.get("facts", []),
            "qa_pairs":    qa_pairs,
            "coverage":    structured.get("coverage"),
            "created_at":  int(time.time()),
            "status":      "pending",
        }
        save_pending(pending)
        return pending

    # ── Ab hier nur noch der BILD-Pfad (Vision) ────────────────────────────
    from google.genai import types

    provider, _model = _profile_provider(prof)

    prompt = _build_prompt(content_for_llm, qa_count)

    # Bild nur anhaengen, wenn nicht zu gross (Provider-Limits); sonst nur OCR-Text
    _vision = is_image and len(content) <= 8 * 1024 * 1024

    async def _call_llm(with_image: bool):
        parts = []
        if with_image:
            parts.append(types.Part.from_bytes(data=content, mime_type=_IMAGE_MIME[suffix]))
        parts.append(types.Part.from_text(text=prompt))
        return await provider.generate_response(
            model=_model,
            system_prompt="Du bist ein Wissensextraktor. Antworte ausschließlich mit dem angeforderten JSON.",
            contents=[types.Content(role="user", parts=parts)],
            tools=[],
        )

    if _vision:
        try:
            response = await _call_llm(with_image=True)
        except Exception as _img_err:
            # Profil nicht vision-faehig o.ae. -> Text-only-Fallback (nur OCR-Text/Beschreibung)
            print(f"⚠️  Vision-Pass fehlgeschlagen, nutze nur OCR-Text: {_img_err}")
            response = await _call_llm(with_image=False)
    else:
        response = await _call_llm(with_image=False)

    raw_text = ""
    if response.parts:
        for p in response.parts:
            if getattr(p, "text", None):
                raw_text += p.text

    json_match = re.search(r'\{[\s\S]*\}', raw_text)
    if not json_match:
        raise ValueError(f"LLM lieferte kein gültiges JSON: {raw_text[:300]}")

    data = json.loads(json_match.group(0))

    doc_id = str(uuid.uuid4())[:8]
    qa_pairs = _drop_qa_if_unwanted([
        {
            "id": str(uuid.uuid4())[:6],
            "q": str(pair.get("q", "")).strip(),
            "a": str(pair.get("a", "")).strip(),
            "approved": True,
        }
        for pair in data.get("qa_pairs", [])
    ], qa_count)

    pending = {
        "id":          doc_id,
        "url":         source_url or f"file://{filename}",
        "source_type": "url" if source_url else "file",
        "source_name": filename,
        "title":   str(data.get("title", filename)).strip()[:300],
        "summary": str(data.get("summary", "")).strip(),
        "facts":   [str(f).strip() for f in data.get("facts", []) if str(f).strip()],
        "qa_pairs":    qa_pairs,
        "created_at":  int(time.time()),
        "status":      "pending",
    }

    save_pending(pending)
    return pending
