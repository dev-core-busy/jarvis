"""Dateisystem Tool – Dateien lesen, schreiben, auflisten."""

import os
from pathlib import Path

from backend.tools.base import BaseTool


class FileSystemTool(BaseTool):
    """Liest, schreibt und listet Dateien/Verzeichnisse auf."""

    @property
    def name(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return (
            "Dateisystem-Operationen. Aktionen: "
            "'read' – Datei lesen (gibt Inhalt zurück). "
            "'write' – Datei schreiben (erstellt/überschreibt). "
            "'append' – Text an Datei anhängen. "
            "'list' – Verzeichnisinhalt auflisten. "
            "'exists' – Prüfen ob Datei/Verzeichnis existiert. "
            "'mkdir' – Verzeichnis erstellen."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Aktion: read, write, append, list, exists, mkdir",
                },
                "path": {
                    "type": "STRING",
                    "description": "Pfad zur Datei oder zum Verzeichnis",
                },
                "content": {
                    "type": "STRING",
                    "description": "Inhalt zum Schreiben (für write/append)",
                },
            },
            "required": ["action", "path"],
        }

    @staticmethod
    def _claim(p: Path) -> None:
        """Selbst geschriebene Datei in data/documents dem Benutzer zuordnen.

        Die Eigentuemer-Schranke ist fail-closed: ohne Eintrag waere eine gerade
        selbst geschriebene Datei fuer den Schreiber sofort wieder unsichtbar.
        """
        try:
            from backend import documents as _documents, sandbox as _sbx
            u = _sbx.tool_user()
            if u and p.resolve().parent == _sbx.DOCS_ROOT:
                _documents.register_upload(p.name, u)
        except Exception:
            pass

    async def execute(
        self,
        action: str,
        path: str,
        content: str = "",
        **kwargs,
    ) -> str:
        """Dateisystem-Operation ausführen."""
        p = Path(path).expanduser()

        try:
            if action == "read":
                if not p.exists():
                    return f"Datei nicht gefunden: {p}"
                if p.is_dir():
                    return f"{p} ist ein Verzeichnis, nicht eine Datei"
                BINARY_EXTENSIONS = {".docx", ".doc", ".pdf", ".xlsx", ".xls", ".pptx", ".ppt", ".odt", ".ods", ".odp", ".zip", ".tar", ".gz", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".mp3", ".mp4", ".wav"}
                if p.suffix.lower() in BINARY_EXTENSIONS:
                    return f"❌ '{p.name}' ist eine Binärdatei ({p.suffix}) und kann nicht direkt gelesen werden. Für Dokumentinhalte knowledge_search verwenden – der Inhalt ist dort bereits korrekt geparst."
                text = p.read_text(encoding="utf-8", errors="replace")
                if len(text) > 10000:
                    return text[:10000] + f"\n\n... (gekürzt, {len(text)} Zeichen gesamt)"
                return text

            elif action == "write":
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                self._claim(p)
                return f"✅ Datei geschrieben: {p} ({len(content)} Zeichen)"

            elif action == "append":
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(content)
                self._claim(p)
                return f"✅ An Datei angehängt: {p}"

            elif action == "list":
                if not p.exists():
                    return f"Verzeichnis nicht gefunden: {p}"
                if not p.is_dir():
                    return f"{p} ist kein Verzeichnis"

                from backend import sandbox as _sbx
                entries = []
                verborgen = 0
                for item in sorted(p.iterdir()):
                    # Eigentuemer-Schranke: in data/documents liegen die Ergebnis-
                    # und Anhangsdateien ALLER Benutzer. Ein Domain-Benutzer sah
                    # hier bis 2026-07-28 fremde Dateinamen (Jira-Exporte,
                    # Angebote). Die Entscheidung trifft backend/sandbox.py.
                    if not _sbx.may_list_entry(p, item.name):
                        verborgen += 1
                        continue
                    prefix = "📁" if item.is_dir() else "📄"
                    size = ""
                    if item.is_file():
                        s = item.stat().st_size
                        if s < 1024:
                            size = f" ({s} B)"
                        elif s < 1024 * 1024:
                            size = f" ({s / 1024:.1f} KB)"
                        else:
                            size = f" ({s / (1024 * 1024):.1f} MB)"
                    entries.append(f"{prefix} {item.name}{size}")

                # Die Zahl der ausgeblendeten Einträge nennen, aber KEINE Namen:
                # sonst wüsste das Modell wieder, dass fremde Dateien existieren.
                # Der Hinweis verhindert, dass es eine gefilterte Liste für
                # vollständig hält und daraus falsche Schlüsse zieht.
                rest = (f"\n({verborgen} Datei(en) anderer Benutzer ausgeblendet)"
                        if verborgen else "")
                if not entries:
                    return f"(Verzeichnis ist leer: {p}){rest}"
                return "\n".join(entries) + rest

            elif action == "exists":
                if p.exists():
                    kind = "Verzeichnis" if p.is_dir() else "Datei"
                    return f"✅ Existiert ({kind}): {p}"
                return f"❌ Existiert nicht: {p}"

            elif action == "mkdir":
                p.mkdir(parents=True, exist_ok=True)
                return f"✅ Verzeichnis erstellt: {p}"

            else:
                return f"Unbekannte Aktion: {action}"

        except PermissionError:
            return f"❌ Zugriff verweigert: {p}"
        except Exception as e:
            return f"Fehler: {str(e)}"
