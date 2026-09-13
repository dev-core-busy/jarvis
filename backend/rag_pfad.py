"""Wo Wissensordner liegen duerfen – und wie sie heissen, wenn ein Mensch sie liest.

EINE Quelle fuer zwei Aussagen, die vorher an einem Dutzend Stellen einzeln
getroffen wurden:

* **Ort.** Lokale Wissensordner liegen ausschliesslich als Unterordner von
  ``data/rag``; Netzwerk-Freigaben ausschliesslich unter ``/mnt/rag``. Vorher war
  jeder direkte ``data/``-Unterordner erlaubt – also derselbe Raum, in dem auch
  ``data/chats``, ``data/logs`` und ``data/instructions`` liegen. Eine
  Namensliste (``_KB_RESERVED_DATA_DIRS``) hielt die beiden Welten auseinander,
  und die ist an dem Tag unvollstaendig, an dem ein neues Datenverzeichnis
  dazukommt – die vergessene Zeile meldet sich nicht, sie laesst nur einen
  Systemordner als Wissensordner anlegen.
* **Name.** ``data/rag/community/handbuch`` heisst fuer den Leser
  ``community/handbuch``. Der Praefix ist eine Eigenschaft der Installation und
  in JEDER Zeile derselbe – er traegt keine Information und verdraengt die, die
  sich unterscheidet.

⚠ ``data/knowledge`` ist KEIN Wissensordner mehr, aber es bleibt: dort liegen der
interne Entwurfs-Speicher (``pending/``), das Gruppen-Manifest (``.groups.json``)
und die WebDAV-Wurzel. Der Ordner ist damit reine Infrastruktur – wer ihn
umbenennt, muss diese drei Stellen mitziehen.

Das Modul ist absichtlich frei von fastapi und vom SkillManager: es wird aus
``main.py``, ``tools/knowledge.py`` und ``knowledge_sync.py`` benutzt, und ein
Import in die Gegenrichtung waere zirkulaer.
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Wurzel aller LOKALEN Wissensordner. Sie ist selbst KEIN Wissensordner: die
# Vorgabe lautet "nur in Unterordnern von data/rag". Waere die Wurzel selbst
# konfigurierbar, zoege sie jeden Unterordner automatisch mit hinein und die
# Ordner-Verwaltung darueber waere ohne Wirkung.
RAG_REL = "data/rag"

# Wurzel aller Netzwerk-Freigaben (Einhaengepunkte).
MOUNT_BASIS = Path("/mnt/rag")

# Die Vorgaenger-Orte. Sie stehen hier, damit die Migration EINE Quelle hat und
# nicht jede Stelle ihren eigenen Altpfad mitbringt.
ALT_MOUNT_BASIS = Path("/mnt/jarvis-kb")
INFRA_REL = "data/knowledge"


# Verzeichnisse unter ``data/``, die KEIN Wissen sind. Die Liste schuetzt
# ausschliesslich den UMZUG: stuende ein solcher Ordner in der Wissens-Ordnerliste
# (Altbestand, Handarbeit in der settings.json), wuerde er sonst mitsamt Inhalt
# nach ``data/rag/`` verschoben – aus einem Konfigurationsfehler wuerde ein
# Datenverlust. Fuer das ANLEGEN braucht es sie nicht mehr: neue Ordner entstehen
# unter ``data/rag``, dort liegt nichts Fremdes.
SYSTEM_ORDNER = {"knowledge", "vector_store", "chroma_db", "logs", "vision",
                 "instructions", "instructions_default", "learned", "erfahrung",
                 "backups", "wa_media", "chats", "documents", "generated_images",
                 "branding", "vorlagen", "rag"}


def ist_systemordner(pfad) -> bool:
    """True fuer einen direkten ``data/``-Unterordner aus SYSTEM_ORDNER."""
    rel = norm(pfad)
    teile = rel.split("/")
    return len(teile) == 2 and teile[0] == "data" and teile[1].lower() in SYSTEM_ORDNER


def rag_wurzel() -> Path:
    """Absoluter Pfad von ``data/rag``."""
    return PROJECT_ROOT / RAG_REL


def norm(pfad) -> str:
    """Pfadangabe auf die gespeicherte Form bringen: relativ zu PROJECT_ROOT,
    Forward-Slashes, ohne fuehrenden/abschliessenden Schraegstrich.

    Absolute Pfade AUSSERHALB des Projekts (Einhaengepunkte) bleiben absolut –
    sie haben kein Projekt-Relativ.
    """
    s = str(pfad or "").replace("\\", "/").strip()
    if not s:
        return ""
    p = Path(s)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(PROJECT_ROOT).as_posix()
        except (ValueError, OSError):
            return s.rstrip("/") or s
    return s.strip("/")


def ist_rag_ordner(pfad) -> bool:
    """True, wenn der Pfad ein Unterordner von ``data/rag`` ist (beliebig tief).

    Die Wurzel selbst ist ausdruecklich NICHT eingeschlossen – siehe RAG_REL.
    Verglichen wird SEGMENTWEISE ueber den Praefix mit Schraegstrich: ohne ihn
    gilt ``data/rag2`` als Treffer (dieselbe Praefix-Falle wie ``share_1`` in
    ``share_10``).
    """
    rel = norm(pfad)
    return bool(rel) and rel.startswith(RAG_REL + "/")


def ist_mount(pfad) -> bool:
    """True fuer einen Einhaengepunkt unterhalb von ``/mnt/rag`` (oder des
    Vorgaenger-Orts, solange ein System noch nicht migriert ist)."""
    s = str(pfad or "").replace("\\", "/").rstrip("/")
    for basis in (MOUNT_BASIS, ALT_MOUNT_BASIS):
        b = str(basis)
        if s == b or s.startswith(b + "/"):
            return True
    return False


def anzeige(pfad) -> str:
    """Der Pfad, wie ein Mensch ihn in der Oberflaeche liest.

    ``data/rag/community/handbuch`` → ``community/handbuch``
    ``/mnt/rag/share_1/Maris``      → ``share_1/Maris``

    Alles andere bleibt UNVERAENDERT stehen (fail-open in die harmlose
    Richtung): ein Ordner, der aus der Konfiguration genommen wurde, oder ein
    Pfad aus einer aelteren Fassung soll roh sichtbar sein. Eine leere Angabe
    waere genau der Zustand, gegen den diese Funktion gebaut ist.
    """
    s = str(pfad or "").replace("\\", "/").strip().rstrip("/")
    if not s:
        return ""
    for basis in (RAG_REL, str(MOUNT_BASIS), str(ALT_MOUNT_BASIS)):
        if s.startswith(basis + "/"):
            rest = s[len(basis) + 1:].strip("/")
            return rest or s
    # Absoluter Projektpfad (kommt aus `_get_folders()`): erst relativieren.
    rel = norm(s)
    if rel != s and rel.startswith(RAG_REL + "/"):
        return rel[len(RAG_REL) + 1:].strip("/") or rel
    return s


def zu_rag(name: str) -> str:
    """Aus einem blossen Ordnernamen den gespeicherten Pfad machen.

    Toleriert die Schreibweisen, die ein Mensch oder ein aelterer Client
    schickt: ``community``, ``data/community``, ``data/rag/community``. Alle
    drei meinen dasselbe – sie abzulehnen waere Schikane.
    """
    s = str(name or "").replace("\\", "/").strip().strip("/")
    if not s:
        return ""
    # ⚠ DIE PRAEFIXE OHNE TRAILING SLASH MITNEHMEN. `"data/"` wird von
    # `strip("/")` zu `"data"` – ohne diesen Zweig entstand daraus
    # `data/rag/data`, also ein Ordner namens "data" statt einer Absage
    # (vom Bestandstest gefunden). Eine Eingabe, die nur die WURZEL nennt,
    # benennt keinen Ordner und wird abgewiesen.
    if s == RAG_REL or s == "data":
        return ""
    if s.startswith(RAG_REL + "/"):
        s = s[len(RAG_REL) + 1:]
    elif s.startswith("data/"):
        s = s[len("data/"):]
    s = s.strip("/")
    # Nach dem Abstreifen darf kein Praefix uebrig bleiben ("data/data/x").
    if not s or s.startswith("/") or ".." in s.split("/"):
        return ""
    return f"{RAG_REL}/{s}"


def mount_punkt(idx: int) -> Path:
    """Vorgabe-Einhaengepunkt der Freigabe mit dieser Listennummer."""
    return MOUNT_BASIS / f"share_{idx}"
