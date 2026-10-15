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

    @staticmethod
    def _schreibe(p: Path, text: str, anhaengen: bool) -> None:
        """Schreibt – und ERSETZT eine Datei, die der Shell-Seite gehoert.

        WARUM DAS NOETIG IST (Vorfall 2026-09-03, ECHT): im Arbeitsverzeichnis
        eines Benutzers schreiben ZWEI Identitaeten – die Shell als
        ``jarvis_sandbox*``, dieses Werkzeug als Dienstbenutzer. Eine vorhandene
        Datei zu ueberschreiben verlangt Schreibrecht auf der DATEI; das
        Verzeichnis-Bit hilft dabei nicht. Gemeldet wurde deshalb ein blankes
        "Zugriff verweigert: /tmp/jarvis-arbeit/<kennung>/firewall_chart.py" –
        ein EACCES, der wie eine Sicherheitsentscheidung aussieht, waehrend die
        Datei dem Benutzer selbst gehoert und nur ein Shell-Schritt davor sie
        angelegt hat.

        ``ARBEIT_MODUS``/``umask 002`` beseitigen die Ursache fuer NEUE Dateien.
        Dieser Zweig ist das Netz fuer den Altbestand: nach einem Deploy liegen
        genau die 0644-Dateien der letzten Stunden noch da – und das
        Arbeitsverzeichnis haengt am Benutzer, nicht am Lauf.

        Ersetzen ist ueber das VERZEICHNIS erlaubt (0770, Dienstgruppe), also
        ``unlink`` + neu anlegen. Beim Anhaengen wird der alte Inhalt vorher
        gelesen – lesen darf der Dienst immer.

        **Nur im Arbeitsverzeichnis** (``lauf_tmp.im_lauf``): sonst waere das ein
        allgemeiner "loesche, was du nicht ueberschreiben darfst"-Mechanismus.
        Dass der Pfad ueberhaupt hierher kommt, hat ``authorize_fs`` entschieden –
        seit demselben Tag prueft es auch beim Schreiben, dass der Arbeitsbereich
        dem Benutzer gehoert.
        """
        modus = "a" if anhaengen else "w"
        try:
            with open(p, modus, encoding="utf-8") as f:
                f.write(text)
        except PermissionError:
            from backend import lauf_tmp as _lt
            if not (p.is_file() and _lt.im_lauf(p)):
                raise
            alt = ""
            if anhaengen:
                try:
                    alt = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    raise                       # nicht lesbar -> nichts erfinden
            p.unlink()
            p.write_text(alt + text, encoding="utf-8")
            print(f"[FS] {p} gehoerte der Shell-Seite – ersetzt", flush=True)
        # Beide Seiten sollen die Datei anfassen koennen: das Backend hat gerade
        # mit umask 022 geschrieben, der Sandbox-Benutzer ist in keiner
        # gemeinsamen Gruppe. Ohne diesen Schritt scheitert `>> /tmp/daten.csv`
        # im Lauf an einer Datei, die das Modell selbst angelegt hat.
        try:
            from backend import lauf_tmp as _lt
            _lt.im_lauf_freigeben(p)
        except Exception:  # noqa: BLE001
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
                self._schreibe(p, content, anhaengen=False)
                self._claim(p)
                return f"✅ Datei geschrieben: {p} ({len(content)} Zeichen)"

            elif action == "append":
                p.parent.mkdir(parents=True, exist_ok=True)
                self._schreibe(p, content, anhaengen=True)
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

        except PermissionError as e:
            # Kein Policy-Verbot, sondern das Betriebssystem – das muss die
            # Meldung sagen. "Zugriff verweigert" allein hat auf ECHT die Suche
            # in die falsche Richtung geschickt (vermutete Sandbox-Regel), und
            # das Modell wich auf einen anderen Weg aus statt den Pfad zu aendern.
            return (f"❌ Dateisystem-Fehler (keine Berechtigung) bei {p}: {e.strerror}. "
                    "Das ist keine Sicherheitssperre – die Datei gehört einem anderen "
                    "Systemkonto. Versuche einen anderen Dateinamen.")
        except Exception as e:
            return f"Fehler: {str(e)}"
