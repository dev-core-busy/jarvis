"""Windows Desktop Tool – steuert den Windows-Desktop des verbundenen Windows-Clients."""

import asyncio
import base64
import json
import time
import uuid
from pathlib import Path

from backend.tools.base import BaseTool

# ─── Verbindungs-State ───────────────────────────────────────────────────────

# Aktuelle Windows-Client WebSocket-Verbindung (gesetzt von main.py bei register)
_windows_ws = None
_windows_ws_lock = asyncio.Lock()

# Offene Anfragen: request_id → asyncio.Future
_pending: dict[str, asyncio.Future] = {}

# Pfad für gespeicherte Screenshots
_SCREENSHOT_PATH = Path("/tmp/jarvis_winscreen.png")


def set_windows_ws(ws):
    """Wird von main.py aufgerufen wenn ein Windows-Client sich registriert/trennt."""
    global _windows_ws
    _windows_ws = ws
    if ws is not None:
        print("[windows_desktop] Windows-Client verbunden", flush=True)
    else:
        print("[windows_desktop] Windows-Client getrennt", flush=True)
        # Alle wartenden Requests mit Fehler abbrechen
        for fut in list(_pending.values()):
            if not fut.done():
                fut.set_exception(ConnectionError("Windows-Client getrennt"))
        _pending.clear()


def on_desktop_result(result: dict):
    """Wird von main.py aufgerufen wenn desktop_result ankommt."""
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
            "- 'screenshot': Bildschirmaufnahme (gibt Dateiname zurück)\n"
            "- 'mouse_move': Maus bewegen (x, y)\n"
            "- 'mouse_click': Mausklick (x, y, button: left/right/middle)\n"
            "- 'mouse_double_click': Doppelklick (x, y)\n"
            "- 'type_text': Text tippen (text) – unterstützt Unicode/Umlaute\n"
            "- 'key_press': Tastenkombination (key, z.B. 'ctrl+c', 'alt+F4', 'win+d', 'Return')\n"
            "- 'shell_exec': Windows-Befehl ausführen (cmd), gibt stdout+stderr zurück\n"
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
                        "Aktion: screenshot, mouse_move, mouse_click, mouse_double_click, "
                        "type_text, key_press, shell_exec, clipboard_get, clipboard_set"
                    ),
                },
                "x": {"type": "NUMBER", "description": "X-Koordinate (Pixel)"},
                "y": {"type": "NUMBER", "description": "Y-Koordinate (Pixel)"},
                "button": {"type": "STRING", "description": "Maustaste: left, right, middle"},
                "text": {"type": "STRING", "description": "Text zum Tippen oder in Zwischenablage"},
                "key": {"type": "STRING", "description": "Taste(n), z.B. 'ctrl+c', 'alt+F4'"},
                "cmd": {"type": "STRING", "description": "Windows-Shell-Befehl (cmd.exe /C ...)"},
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        x: float = 0,
        y: float = 0,
        button: str = "left",
        text: str = "",
        key: str = "",
        cmd: str = "",
    ) -> str:
        if _windows_ws is None:
            return "❌ Kein Windows-Client verbunden. Bitte die Jarvis Windows App starten."

        req_id = str(uuid.uuid4())[:8]
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        _pending[req_id] = fut

        payload = {
            "type": "desktop_command",
            "request_id": req_id,
            "action": action,
            "x": x,
            "y": y,
            "button": button,
            "text": text,
            "key": key,
            "cmd": cmd,
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

        # Screenshot: base64 PNG → Datei speichern
        if action == "screenshot" and result.get("data"):
            try:
                png_bytes = base64.b64decode(result["data"])
                _SCREENSHOT_PATH.write_bytes(png_bytes)
                size_kb = len(png_bytes) // 1024
                return (
                    f"✅ Screenshot gespeichert: {_SCREENSHOT_PATH} ({size_kb} KB). "
                    f"Verwende shell_exec mit 'dir' oder andere Tools um den Desktop-Zustand zu beschreiben."
                )
            except Exception as e:
                return f"❌ Screenshot-Dekodierung fehlgeschlagen: {e}"

        output = result.get("output", "OK")
        exit_code = result.get("exit_code", 0)
        if exit_code != 0:
            return f"⚠ Exit-Code {exit_code}:\n{output}"
        return f"✅ {output}" if output else "✅ OK"
