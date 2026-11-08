"""Android Desktop Tool – steuert das Android-Gerät des verbundenen Android-Clients."""

from backend.tools.base import BaseTool

# ─── Verbindungs-State ───────────────────────────────────────────────────────
# Je BENUTZER, nicht global (Pentest C1) – siehe backend/tools/geraete_verbindungen.py.

from backend.tools.geraete_verbindungen import GeraeteVerbindungen

VERBINDUNGEN = GeraeteVerbindungen("Android")


def set_android_ws(ws, benutzer: str = ""):
    """Registrierung (main.py, Nachricht ``register``) fuer den ANMELDENDEN Benutzer."""
    if ws is None:
        return
    VERBINDUNGEN.registrieren(ws, benutzer)


def remove_android_ws(ws):
    """Nur den Eintrag DIESER Verbindung entfernen (WebSocket getrennt)."""
    VERBINDUNGEN.trennen(ws)


def on_android_result(result: dict, ws=None):
    """Ergebnis nur von der Verbindung annehmen, an die der Befehl ging."""
    return VERBINDUNGEN.ergebnis(result, ws)


def is_connected(benutzer: str | None = None) -> bool:
    return VERBINDUNGEN.verbunden(benutzer)


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

    async def execute(self, action: str, cmd: str = "", text: str = "", **kwargs) -> str:
        # Akteur und Rechte setzt der Dispatch, nie das Modell (Pentest C1/C2).
        ziel = VERBINDUNGEN.client_fuer(str(kwargs.get("_akteur") or ""),
                                        kwargs.get("_privileged") is True)
        if ziel is None:
            return ("❌ Für deinen Benutzer ist kein Android-Client verbunden. Bitte die "
                    "Jarvis Android App öffnen und mit deinem eigenen Konto anmelden.")

        payload = {
            "type": "desktop_command",
            "action": action,
            "cmd": cmd,
            "text": text,
        }

        result, fehler = await VERBINDUNGEN.senden(ziel, payload, timeout=30.0)
        if fehler:
            return fehler

        if result.get("error"):
            return f"❌ {result['error']}"

        output = result.get("output", "OK")
        exit_code = result.get("exit_code", 0)
        if exit_code != 0:
            return f"⚠ Exit-Code {exit_code}:\n{output}"
        return f"✅ {output}" if output else "✅ OK"
