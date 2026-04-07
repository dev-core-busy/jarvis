"""Android Desktop Tool – steuert das Android-Gerät des verbundenen Android-Clients."""

import asyncio
import uuid

from backend.tools.base import BaseTool

# ─── Verbindungs-State ───────────────────────────────────────────────────────

_android_ws = None
_pending: dict[str, asyncio.Future] = {}


def set_android_ws(ws):
    """Wird von main.py aufgerufen wenn ein Android-Client sich registriert/trennt."""
    global _android_ws
    _android_ws = ws
    if ws is not None:
        print("[android_desktop] Android-Client verbunden", flush=True)
    else:
        print("[android_desktop] Android-Client getrennt", flush=True)
        for fut in list(_pending.values()):
            if not fut.done():
                fut.set_exception(ConnectionError("Android-Client getrennt"))
        _pending.clear()


def on_android_result(result: dict):
    """Wird von main.py aufgerufen wenn desktop_result vom Android-Client ankommt."""
    req_id = result.get("request_id", "")
    fut = _pending.pop(req_id, None)
    if fut and not fut.done():
        fut.set_result(result)


def is_connected() -> bool:
    return _android_ws is not None


# ─── Tool-Klasse ─────────────────────────────────────────────────────────────

class AndroidDesktopTool(BaseTool):
    """Steuert das Android-Gerät des verbundenen Jarvis Android-Clients."""

    @property
    def name(self) -> str:
        return "android_desktop"

    @property
    def description(self) -> str:
        return (
            "Steuert das Android-Gerät des verbundenen Android-Clients.\n"
            "Aktionen:\n"
            "- 'shell_exec': Shell-Befehl auf dem Android-Gerät ausführen (cmd), gibt stdout+stderr zurück\n"
            "- 'launch_app': App starten (text = App-Name z.B. 'Chrome', 'WhatsApp', 'Kamera')\n"
            "- 'list_apps': Alle installierten User-Apps auflisten\n"
            "- 'get_info': Gerätinformationen (Modell, Android-Version, etc.)\n"
            "Voraussetzung: Jarvis Android App muss verbunden und aktiv sein."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Aktion: shell_exec, launch_app, list_apps, get_info",
                },
                "cmd": {
                    "type": "STRING",
                    "description": "Shell-Befehl für shell_exec",
                },
                "text": {
                    "type": "STRING",
                    "description": "App-Name für launch_app (z.B. 'Chrome', 'WhatsApp')",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, cmd: str = "", text: str = "", **_) -> str:
        if _android_ws is None:
            return "❌ Kein Android-Client verbunden. Bitte die Jarvis Android App öffnen."

        req_id = str(uuid.uuid4())[:8]
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        _pending[req_id] = fut

        payload = {
            "type": "desktop_command",
            "request_id": req_id,
            "action": action,
            "cmd": cmd,
            "text": text,
        }

        try:
            await _android_ws.send_json(payload)
        except Exception as e:
            _pending.pop(req_id, None)
            return f"❌ Senden fehlgeschlagen: {e}"

        try:
            result = await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            _pending.pop(req_id, None)
            return "❌ Timeout: Android-Client hat nicht geantwortet (30s)"
        except ConnectionError as e:
            return f"❌ Verbindung verloren: {e}"

        if result.get("error"):
            return f"❌ {result['error']}"

        output = result.get("output", "OK")
        exit_code = result.get("exit_code", 0)
        if exit_code != 0:
            return f"⚠ Exit-Code {exit_code}:\n{output}"
        return f"✅ {output}" if output else "✅ OK"
