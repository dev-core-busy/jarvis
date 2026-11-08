"""Windows Desktop Tool – steuert den Windows-Desktop des verbundenen Windows-Clients."""

import asyncio
import base64
import json
import time
import uuid
from pathlib import Path

from backend.tools.base import BaseTool

# ─── Verbindungs-State ───────────────────────────────────────────────────────
# Je BENUTZER, nicht global (Pentest C1) – siehe backend/tools/geraete_verbindungen.py.

from backend.tools.geraete_verbindungen import GeraeteVerbindungen

VERBINDUNGEN = GeraeteVerbindungen("Windows")


def set_windows_ws(ws, benutzer: str = ""):
    """Registrierung (main.py, Nachricht ``register``) fuer den ANMELDENDEN Benutzer.

    ``ws=None`` (frueher: globales Abmelden) wird nicht mehr unterstuetzt –
    getrennt wird je Verbindung ueber ``remove_windows_ws``.
    """
    if ws is None:
        return
    VERBINDUNGEN.registrieren(ws, benutzer)


def remove_windows_ws(ws):
    """Nur den Eintrag DIESER Verbindung entfernen (WebSocket getrennt)."""
    VERBINDUNGEN.trennen(ws)


def on_desktop_result(result: dict, ws=None):
    """Ergebnis nur von der Verbindung annehmen, an die der Befehl ging."""
    return VERBINDUNGEN.ergebnis(result, ws)


def is_connected(benutzer: str | None = None) -> bool:
    return VERBINDUNGEN.verbunden(benutzer)


def _bildpfad(rid: str) -> Path:
    """Screenshot-Ablage: im Lauf-Verzeichnis des Benutzers, sonst /tmp – je
    Aufruf eigener Name (frueher EIN fester Pfad fuer alle Benutzer)."""
    try:
        from backend import lauf_tmp
        verz = lauf_tmp.verzeichnis()
    except Exception:  # noqa: BLE001
        verz = None
    return (Path(verz) if verz else Path("/tmp")) / f"jarvis_winscreen_{rid}.png"


# ─── Tool-Klasse ─────────────────────────────────────────────────────────────

class WindowsDesktopTool(BaseTool):
    """Steuert den Windows-Desktop des verbundenen Jarvis Windows-Clients."""

    @property
    def name(self) -> str:
        return "windows_desktop"

    @property
    def description(self) -> str:
        return (
            "Steuert den Windows-Desktop des verbundenen Windows-Clients. "
            "Aktionen:\n"
            "- 'screenshot': Bildschirmaufnahme\n"
            "- 'open_url': Webseite im Standard-Browser öffnen (url z.B. 'https://www.beispiel.de')\n"
            "- 'open_app': Programm starten (text = Programmname, z.B. 'notepad', 'explorer')\n"
            "- 'mouse_move': Maus bewegen (x, y)\n"
            "- 'mouse_click': Mausklick (x, y, button: left/right/middle)\n"
            "- 'right_click': Rechtsklick (x, y)\n"
            "- 'middle_click': Mittelklick (x, y)\n"
            "- 'mouse_double_click': Doppelklick (x, y)\n"
            "- 'triple_click': Dreifachklick – z.B. Zeile markieren (x, y)\n"
            "- 'drag_and_drop': Drag & Drop von (x,y) nach (x2,y2)\n"
            "- 'scroll': Mausrad scrollen (x, y, direction: up/down/left/right, amount: Klicks)\n"
            "- 'type_text': Text tippen (text) – unterstützt Unicode/Umlaute\n"
            "- 'key_press': Tastenkombination (key, z.B. 'ctrl+c', 'alt+F4', 'win+d', 'Return')\n"
            "- 'shell_exec': Windows-Shell-Befehl ausführen (cmd), gibt stdout+stderr zurück\n"
            "- 'get_active_window': Info über das aktive Fenster (Titel, Klasse, Position, Größe)\n"
            "- 'list_windows': Alle sichtbaren Fenster auflisten (Handle + Titel)\n"
            "- 'focus_window': Fenster in den Vordergrund bringen (text = Teiltitel)\n"
            "- 'close_window': Fenster schließen (text = Teiltitel oder aktives Fenster)\n"
            "- 'minimize_window': Fenster minimieren (text = Teiltitel oder aktives Fenster)\n"
            "- 'maximize_window': Fenster maximieren (text = Teiltitel oder aktives Fenster)\n"
            "- 'restore_window': Fenster wiederherstellen/normalisieren\n"
            "- 'resize_window': Fenstergröße ändern (text = Teiltitel, width, height)\n"
            "- 'move_window': Fenster verschieben (text = Teiltitel, x, y)\n"
            "- 'clipboard_get': Zwischenablage lesen\n"
            "- 'clipboard_set': Text in Zwischenablage setzen (text)\n"
            "Voraussetzung: Windows App muss verbunden und aktiv sein."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "Aktion: screenshot, open_url, open_app, "
                        "mouse_move, mouse_click, right_click, middle_click, "
                        "mouse_double_click, triple_click, drag_and_drop, scroll, "
                        "type_text, key_press, shell_exec, "
                        "get_active_window, list_windows, focus_window, close_window, "
                        "minimize_window, maximize_window, restore_window, "
                        "resize_window, move_window, clipboard_get, clipboard_set"
                    ),
                },
                "url":       {"type": "STRING",  "description": "URL für open_url (z.B. 'https://www.beispiel.de')"},
                "x":         {"type": "NUMBER",  "description": "X-Koordinate (Pixel)"},
                "y":         {"type": "NUMBER",  "description": "Y-Koordinate (Pixel)"},
                "x2":        {"type": "NUMBER",  "description": "Ziel-X für drag_and_drop / move_window"},
                "y2":        {"type": "NUMBER",  "description": "Ziel-Y für drag_and_drop"},
                "button":    {"type": "STRING",  "description": "Maustaste: left, right, middle"},
                "direction": {"type": "STRING",  "description": "Scroll-Richtung: up, down, left, right"},
                "amount":    {"type": "INTEGER", "description": "Scroll-Klicks (Standard: 3)"},
                "text":      {"type": "STRING",  "description": "Text tippen / Fenstertitel (Teilstring) / Programmname"},
                "key":       {"type": "STRING",  "description": "Taste(n), z.B. 'ctrl+c', 'alt+F4', 'win+d'"},
                "cmd":       {"type": "STRING",  "description": "Windows-Shell-Befehl"},
                "width":     {"type": "INTEGER", "description": "Fensterbreite (px) für resize_window"},
                "height":    {"type": "INTEGER", "description": "Fensterhöhe (px) für resize_window"},
                "window_id": {"type": "STRING",  "description": "Fenster-Handle als String (alternativ zu text)"},
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        x: float = 0,
        y: float = 0,
        x2: float = 0,
        y2: float = 0,
        button: str = "left",
        text: str = "",
        key: str = "",
        cmd: str = "",
        url: str = "",
        direction: str = "down",
        amount: int = 3,
        width: int = 0,
        height: int = 0,
        window_id: str = "",
        **kwargs,
    ) -> str:
        # Akteur und Rechte setzt der Dispatch (agent._execute_tool), nie das
        # Modell – Modell-Argumente mit '_' werden dort vorher verworfen.
        akteur = str(kwargs.get("_akteur") or "")
        privilegiert = kwargs.get("_privileged") is True
        ziel = VERBINDUNGEN.client_fuer(akteur, privilegiert)
        if ziel is None:
            return ("❌ Für deinen Benutzer ist kein Windows-Client verbunden. Bitte die "
                    "Jarvis Windows App auf deinem PC starten und mit deinem eigenen "
                    "Konto anmelden.")

        payload = {
            "type":       "desktop_command",
            "action":     action,
            "x":          x,
            "y":          y,
            "x2":         x2,
            "y2":         y2,
            "button":     button,
            "text":       text,
            "key":        key,
            "cmd":        cmd,
            "url":        url,
            "direction":  direction,
            "amount":     amount,
            "width":      width,
            "height":     height,
            "window_id":  window_id,
        }

        result, fehler = await VERBINDUNGEN.senden(ziel, payload, timeout=30.0)
        if fehler:
            return fehler

        if result.get("error"):
            return f"❌ {result['error']}"

        if action == "screenshot" and result.get("data"):
            try:
                png_bytes = base64.b64decode(result["data"])
                bild = _bildpfad(str(result.get("request_id") or uuid.uuid4().hex[:8]))
                bild.write_bytes(png_bytes)
                # IMAGE_BASE64: Format – wird vom Agent-Loop als Inline-Bild ans LLM übergeben
                return f"IMAGE_BASE64:{bild}|{result['data']}"
            except Exception as e:
                return f"❌ Screenshot-Dekodierung fehlgeschlagen: {e}"

        output = result.get("output", "OK")
        exit_code = result.get("exit_code", 0)
        if exit_code != 0:
            return f"⚠ Exit-Code {exit_code}:\n{output}"
        return f"✅ {output}" if output else "✅ OK"
