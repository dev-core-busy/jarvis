"""
Google Drive Tool für Jarvis.

Tool-Name: google_drive
Aktionen:
  list_files     – Dateien/Ordner auflisten (optional: in einem Ordner)
  search_files   – Dateien suchen (Drive-Query)
  read_file      – Datei lesen (Google Docs/Sheets als Text; andere: Metadaten)
  create_folder  – Neuen Ordner anlegen
  get_link       – Freigabe-Link einer Datei abrufen
"""

from backend.tools.base import BaseTool


def _get_service():
    from backend.tools.google_auth import get_service
    return get_service("drive", "v3")


_FIELDS = "id, name, mimeType, size, modifiedTime, webViewLink"


class GoogleDriveTool(BaseTool):
    name = "google_drive"
    description = (
        "Liest und verwaltet Google Drive Dateien. "
        "Aktionen: list_files, search_files, read_file, create_folder, get_link."
    )

    def execute(self, action: str, **kwargs) -> str:
        try:
            svc = _get_service()
        except RuntimeError as e:
            return f"❌ Nicht authentifiziert: {e}"
        except Exception as e:
            return f"❌ Verbindungsfehler: {e}"

        try:
            if action == "list_files":
                return self._list_files(svc, kwargs.get("folder_id"), kwargs.get("max_results", 20))
            elif action == "search_files":
                return self._search_files(svc, kwargs.get("query", ""), kwargs.get("max_results", 20))
            elif action == "read_file":
                return self._read_file(svc, kwargs.get("file_id", ""))
            elif action == "create_folder":
                return self._create_folder(svc, kwargs.get("name", "Neuer Ordner"), kwargs.get("parent_id"))
            elif action == "get_link":
                return self._get_link(svc, kwargs.get("file_id", ""))
            else:
                return (f"❌ Unbekannte Aktion: {action}. "
                        "Verfügbar: list_files, search_files, read_file, create_folder, get_link")
        except Exception as e:
            return f"❌ Drive-Fehler: {e}"

    def _list_files(self, svc, folder_id: str | None, max_results: int) -> str:
        q = f"'{folder_id}' in parents and trashed=false" if folder_id else "trashed=false"
        result = svc.files().list(
            q=q, pageSize=max_results, fields=f"files({_FIELDS})",
            orderBy="modifiedTime desc"
        ).execute()
        files = result.get("files", [])
        if not files:
            return "📂 Keine Dateien gefunden."
        lines = [f"📂 {len(files)} Datei(en):"]
        for f in files:
            icon = "📁" if f["mimeType"] == "application/vnd.google-apps.folder" else "📄"
            size = f.get("size", "–")
            lines.append(f"  {icon} {f['name']}\n     ID: {f['id']} | Geändert: {f.get('modifiedTime','')[:10]}")
        return "\n".join(lines)

    def _search_files(self, svc, query: str, max_results: int) -> str:
        if not query:
            return "❌ Bitte query angeben (z.B. 'name contains \"Rechnung\"')."
        q = f"({query}) and trashed=false"
        result = svc.files().list(
            q=q, pageSize=max_results, fields=f"files({_FIELDS})"
        ).execute()
        files = result.get("files", [])
        if not files:
            return f"🔍 Keine Dateien für '{query}' gefunden."
        lines = [f"🔍 {len(files)} Ergebnis(se):"]
        for f in files:
            lines.append(f"  📄 {f['name']}\n     ID: {f['id']}")
        return "\n".join(lines)

    def _read_file(self, svc, file_id: str) -> str:
        if not file_id:
            return "❌ Bitte file_id angeben."
        meta = svc.files().get(fileId=file_id, fields=_FIELDS).execute()
        mime = meta.get("mimeType", "")

        # Google Docs → als Text exportieren
        export_map = {
            "application/vnd.google-apps.document":     ("text/plain",      "📝 Google Doc"),
            "application/vnd.google-apps.spreadsheet":  ("text/csv",        "📊 Google Sheet (CSV)"),
            "application/vnd.google-apps.presentation": ("text/plain",      "📊 Google Slides"),
        }
        if mime in export_map:
            export_mime, label = export_map[mime]
            content = svc.files().export(fileId=file_id, mimeType=export_mime).execute()
            text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
            return f"{label}: {meta['name']}\n{'─'*40}\n{text[:4000]}"

        # Binäre Datei → nur Metadaten
        return (
            f"📄 {meta['name']}\n"
            f"Typ:      {mime}\n"
            f"Größe:    {meta.get('size', '–')} Bytes\n"
            f"Geändert: {meta.get('modifiedTime','')[:10]}\n"
            f"Link:     {meta.get('webViewLink','–')}"
        )

    def _create_folder(self, svc, name: str, parent_id: str | None) -> str:
        meta: dict = {
            "name":     name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            meta["parents"] = [parent_id]
        folder = svc.files().create(body=meta, fields="id, name").execute()
        return f"✅ Ordner '{folder['name']}' erstellt (ID: {folder['id']})"

    def _get_link(self, svc, file_id: str) -> str:
        if not file_id:
            return "❌ Bitte file_id angeben."
        meta = svc.files().get(fileId=file_id, fields="name, webViewLink").execute()
        return f"🔗 {meta['name']}: {meta.get('webViewLink','Kein Link verfügbar')}"
