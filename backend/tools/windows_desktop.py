"""Windows Desktop Tool – steuert den Windows-Desktop des verbundenen Windows-Clients."""

import asyncio
import base64
import json
import time
import uuid
from pathlib import Path

from backend.tools.base import BaseTool

# ─── Verbindungs-State ───────────────────────────────────────────────────────

_windows_ws = None
_windows_ws_lock = asyncio.Lock()
_pending: dict[str, asyncio.Future] = {}
_SCREENSHOT_PATH = Path("/tmp/jarvis_winscreen.png")


def set_windows_ws(ws):
    global _windows_ws
    _windows_ws = ws
    if ws is not None:
        print("[windows_desktop] Windows-Client verbunden", flush=True)
    else:
        print("[windows_desktop] Windows-Client getrennt", flush=True)
        for fut in list(_pending.values()):
            if not fut.done():
                fut.set_exception(ConnectionError("Windows-Client getrennt"))
        _pending.clear()


def on_desktop_result(result: dict):
    req_id = result.get("request_id", "")
    fut = _pending.pop(req_id, None)
    if fut and not fut.done():
        fut.set_result(result)


def is_connected() -> bool:
    return _windows_ws is not None


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
            "- 'open_url': Webseite im Standard-Browser öffnen (url z.B. 'https://insv3.de')\n"
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
                "url":       {"type": "STRING",  "description": "URL für open_url (z.B. 'https://insv3.de')"},
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
        if _windows_ws is None:
            return "❌ Kein Windows-Client verbunden. Bitte die Jarvis Windows App starten."

        req_id = str(uuid.uuid4())[:8]
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        _pending[req_id] = fut

        payload = {
            "type":       "desktop_command",
            "request_id": req_id,
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

        try:
            await _windows_ws.send_json(payload)
        except Exception as e:
            _pending.pop(req_id, None)
            return f"❌ Senden fehlgeschlagen: {e}"

        try:
            result = await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            _pending.pop(req_id, None)
            return "❌ Timeout: Windows-Client hat nicht geantwortet (30s)"
        except ConnectionError as e:
            return f"❌ Verbindung verloren: {e}"

        if result.get("error"):
            return f"❌ {result['error']}"

        if action == "screenshot" and result.get("data"):
            try:
                png_bytes = base64.b64decode(result["data"])
                _SCREENSHOT_PATH.write_bytes(png_bytes)
                size_kb = len(png_bytes) // 1024
                return (
                    f"✅ Screenshot gespeichert: {_SCREENSHOT_PATH} ({size_kb} KB). "
                    f"Nutze das screenshot Tool um den Screenshot anzuzeigen."
                )
            except Exception as e:
                return f"❌ Screenshot-Dekodierung fehlgeschlagen: {e}"

        output = result.get("output", "OK")
        exit_code = result.get("exit_code", 0)
        if exit_code != 0:
            return f"⚠ Exit-Code {exit_code}:\n{output}"
        return f"✅ {output}" if output else "✅ OK"
