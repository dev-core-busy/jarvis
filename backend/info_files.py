"""Info-Dokumente fuer das Portal (`frontend_info_files/`).

Ein Ablage-Ordner, in den ein Administrator Dateien legt (Handbuch, Merkblatt,
Formular …). Das Portal zeigt dann oben rechts ein Ordnersymbol mit der Liste;
ist der Ordner leer oder fehlt er, erscheint das Symbol NICHT (die Oberflaeche
soll keinen leeren Ordner anbieten).

Absichtlich getrennt von ``data/documents`` (siehe backend/documents.py): dort
liegen vom Agenten ERZEUGTE Dateien mit Capability-Namen, Eigentuemer-Bindung und
Verfallsfrist. Hier liegen bewusst abgelegte Dateien mit sprechenden Namen, die
JEDER angemeldete Benutzer lesen darf – deshalb auch keine Eigentuemer-Pruefung.

WICHTIG – was hier NICHT hingehoert: Der Ordner ist fuer alle angemeldeten
Benutzer lesbar, auch fuer Netzwerk-/Domain-Benutzer. Vertrauliches gehoert in
die Wissensdatenbank mit Gruppenrechten, nicht hierher.

Pfad-Sicherheit: Der Dateiname aus der URL wird NIE zusammengesetzt und dann
"gehofft" – ``resolve()`` prueft nach der Auflusung, dass die Datei wirklich
direkt in diesem Ordner liegt (kein ``..``, kein Unterordner, kein Symlink nach
draussen). Ohne diese Nachpruefung waere ein Prefix-Vergleich schon durch einen
Symlink zu umgehen.
"""

from __future__ import annotations

import os
from pathlib import Path

# Vorgabe ist der Ordner NEBEN dem Backend, also `/opt/jarvis/frontend_info_files`
# im Betrieb und `<repo>/frontend_info_files` in der Entwicklung. Ueber
# JARVIS_INFO_DIR umstellbar (z.B. auf eine gemountete Freigabe).
INFO_DIR = Path(os.environ.get(
    "JARVIS_INFO_DIR",
    str(Path(__file__).resolve().parent.parent / "frontend_info_files")))

# Endung → Kategorie. Die Kategorie steuert im Frontend das Symbol; sie kommt
# aus dem Backend, damit Liste und Auslieferung dieselbe Einteilung benutzen.
_KINDS: dict[str, str] = {
    "url": "link", "weblink": "link", "link": "link",
    "pdf": "pdf",
    "doc": "word", "docx": "word", "odt": "word", "rtf": "word",
    "xls": "excel", "xlsx": "excel", "ods": "excel", "csv": "excel",
    "ppt": "powerpoint", "pptx": "powerpoint", "odp": "powerpoint",
    "png": "image", "jpg": "image", "jpeg": "image", "gif": "image",
    "webp": "image", "bmp": "image", "svg": "image", "tif": "image", "tiff": "image",
    "txt": "text", "md": "text", "log": "text",
    "zip": "archive", "7z": "archive", "rar": "archive", "gz": "archive",
    "tar": "archive", "tgz": "archive", "bz2": "archive", "xz": "archive",
    "mp4": "video", "mkv": "video", "mov": "video", "avi": "video", "webm": "video",
    "mp3": "audio", "wav": "audio", "ogg": "audio", "m4a": "audio", "flac": "audio",
    "json": "code", "xml": "code", "yml": "code", "yaml": "code", "html": "code",
    "htm": "code", "js": "code", "py": "code", "sh": "code", "sql": "code",
}

# Nur diese Typen zeigt der Browser sinnvoll im Tab an – der Rest wird zum
# Download (ein "inline" ausgeliefertes .docx erscheint sonst als Zeichenmuell).
_INLINE_KINDS = {"pdf", "image", "text"}

# AUSNAHME von _INLINE_KINDS: SVG ist ein Dokument, kein Bild – es darf Skripte
# enthalten, die beim Anzeigen im TAB im Origin des Portals laufen wuerden
# (Zugriff auf localStorage samt Sitzungstoken). Deshalb immer als Download.
# Gleiches gilt fuer HTML-artiges, das ueber die Kategorie 'code' ohnehin schon
# als Anhang geliefert wird.
_NEVER_INLINE_EXT = {"svg", "svgz", "xhtml", "html", "htm", "xml"}

_MEDIA: dict[str, str] = {
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
    "md": "text/plain; charset=utf-8",
    "log": "text/plain; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
    "svg": "image/svg+xml", "tif": "image/tiff", "tiff": "image/tiff",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "zip": "application/zip",
}


def kind_of(name: str) -> str:
    """Kategorie einer Datei anhand der Endung ('file' = unbekannt)."""
    ext = Path(name).suffix.lstrip(".").lower()
    return _KINDS.get(ext, "file")


# ── Verknuepfungen (.url) ────────────────────────────────────────────────────
# Eine Verknuepfung ist eine winzige Textdatei; das Portal soll sie NICHT zum
# Download anbieten, sondern das Ziel oeffnen. Unterstuetzt wird das
# Windows-Format (``[InternetShortcut]`` + ``URL=…``, so entsteht die Datei beim
# Ziehen aus der Adresszeile) und – tolerant – eine Datei, die nur die Adresse
# enthaelt.
_LINK_MAX_BYTES = 8192          # eine Verknuepfung ist winzig; alles Groessere ignorieren

# NUR http/https. `javascript:` waere ein Skript im Origin des Portals (Zugriff
# auf das Sitzungstoken im localStorage), `file:`/`data:` fuehren am Server
# vorbei bzw. lassen beliebiges Markup als Seite laufen. Wer eine Verknuepfung
# ablegen darf, soll damit KEIN Skript ausfuehren koennen.
_LINK_SCHEMES = ("http://", "https://")


def read_link(p: Path) -> str:
    """Liest das Ziel einer Verknuepfungsdatei ('' = keine brauchbare Adresse)."""
    try:
        if p.stat().st_size > _LINK_MAX_BYTES:
            return ""
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    kandidat = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#", "[")):
            continue
        low = line.lower()
        if low.startswith("url="):
            kandidat = line[4:].strip()
            break
        if not kandidat and low.startswith(_LINK_SCHEMES):
            kandidat = line          # Datei enthaelt nur die Adresse
    return kandidat if kandidat.lower().startswith(_LINK_SCHEMES) else ""


def ensure_dir() -> bool:
    """Legt den Ordner an, falls er fehlt. True = vorhanden/erzeugt.

    Der Ordner wird beim Start angelegt, damit ein Administrator Dateien
    einfach hineinkopieren kann, ohne ihn vorher von Hand zu erstellen.
    Fehlende Rechte sind kein Startfehler – dann bleibt das Portalsymbol
    einfach aus (die Liste ist leer).
    """
    try:
        INFO_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[InfoFiles] Ordner {INFO_DIR} nicht anlegbar: {e}", flush=True)
        return False


def list_files() -> list[dict]:
    """Sichtbare Dateien im Info-Ordner, alphabetisch (Gross/Klein egal).

    Ausgeblendet werden versteckte Dateien (``.`` am Anfang), Unterordner und
    alles, was kein regulaeres File ist. Fehlt der Ordner, ist die Liste leer –
    das Portal blendet das Symbol dann aus.
    """
    out: list[dict] = []
    try:
        entries = sorted(INFO_DIR.iterdir(), key=lambda p: p.name.lower())
    except Exception:
        return out
    for p in entries:
        try:
            if p.name.startswith(".") or not p.is_file():
                continue
            st = p.stat()
            eintrag = {
                "name": p.name,
                "ext": p.suffix.lstrip(".").lower(),
                "kind": kind_of(p.name),
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            }
            if eintrag["kind"] == "link":
                ziel = read_link(p)
                if ziel:
                    eintrag["url"] = ziel
                    # Anzeigename ohne Endung: "Kamera.url" wird zu "Kamera" –
                    # der Dateiname IST damit die Beschriftung im Portal.
                    eintrag["label"] = p.stem
                else:
                    # Unbrauchbare Verknuepfung (leer, falsches Schema) wird zur
                    # normalen Datei degradiert, statt einen toten Eintrag zu
                    # zeigen. Auffaellig genug, um den Fehler zu bemerken.
                    eintrag["kind"] = "file"
            out.append(eintrag)
        except Exception:
            continue          # unlesbarer Eintrag darf die Liste nicht kippen
    return out


def resolve(name: str) -> Path | None:
    """Prueft einen Dateinamen aus der URL und gibt den echten Pfad zurueck.

    None bei jedem Zweifel (fail-closed). Geprueft wird in dieser Reihenfolge:
    kein Pfadanteil im Namen, keine versteckte Datei, Datei existiert, und –
    entscheidend – der AUFGELOESTE Pfad liegt unmittelbar im Info-Ordner. Der
    letzte Punkt faengt Symlinks ab, die aus dem Ordner herausfuehren.
    """
    n = (name or "").strip()
    if not n or n.startswith(".") or "/" in n or "\\" in n or n in (".", ".."):
        return None
    if "\x00" in n:
        return None
    p = INFO_DIR / n
    try:
        rp = p.resolve(strict=True)
        if rp.parent != INFO_DIR.resolve() or not rp.is_file():
            return None
    except Exception:
        return None
    return rp


def media_type(name: str) -> str:
    """MIME-Typ fuer die Auslieferung (Fallback: Download-Strom)."""
    import mimetypes
    ext = Path(name).suffix.lstrip(".").lower()
    return _MEDIA.get(ext) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def disposition(name: str) -> str:
    """'inline' fuer im Browser anzeigbare Typen, sonst 'attachment'.

    Aktiv skriptfaehige Formate (SVG, HTML, XML) bleiben trotz passender
    Kategorie ein Download – siehe _NEVER_INLINE_EXT.
    """
    ext = Path(name).suffix.lstrip(".").lower()
    if ext in _NEVER_INLINE_EXT:
        return "attachment"
    return "inline" if kind_of(name) in _INLINE_KINDS else "attachment"
