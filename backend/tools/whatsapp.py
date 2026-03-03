"""WhatsApp Tools – Nachrichten senden und Bridge-Status abfragen."""

import json
import urllib.request
import urllib.error

from backend.tools.base import BaseTool

# Bridge laeuft lokal auf Port 3001
BRIDGE_URL = "http://127.0.0.1:3001"


class WhatsAppSendTool(BaseTool):
    """Sendet eine WhatsApp-Nachricht ueber die Bridge."""

    @property
    def name(self) -> str:
        return "whatsapp_send"

    @property
    def description(self) -> str:
        return (
            "Sendet eine WhatsApp-Textnachricht an eine Telefonnummer. "
            "Die Nummer muss im internationalen Format sein (z.B. +491234567890). "
            "WhatsApp muss verbunden sein (QR-Code gescannt)."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "to": {
                    "type": "STRING",
                    "description": "Telefonnummer des Empfaengers im internationalen Format (z.B. +491234567890)",
                },
                "message": {
                    "type": "STRING",
                    "description": "Die zu sendende Textnachricht",
                },
            },
            "required": ["to", "message"],
        }

    async def execute(self, to: str = "", message: str = "", **kwargs) -> str:
        """Sendet eine WhatsApp-Nachricht."""
        if not to or not message:
            return "Fehler: 'to' und 'message' sind Pflichtfelder."

        try:
            data = json.dumps({"to": to, "message": message}).encode("utf-8")
            req = urllib.request.Request(
                f"{BRIDGE_URL}/send",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("success"):
                    return f"Nachricht an {to} gesendet."
                return f"Fehler: {result}"
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                err = json.loads(body)
                return f"Fehler ({e.code}): {err.get('error', body)}"
            except Exception:
                return f"Fehler ({e.code}): {body}"
        except urllib.error.URLError as e:
            return f"WhatsApp Bridge nicht erreichbar: {e.reason}"
        except Exception as e:
            return f"Fehler: {str(e)}"


class WhatsAppStatusTool(BaseTool):
    """Fragt den Status der WhatsApp-Verbindung ab."""

    @property
    def name(self) -> str:
        return "whatsapp_status"

    @property
    def description(self) -> str:
        return (
            "Zeigt den aktuellen Status der WhatsApp-Verbindung an: "
            "ob verbunden, QR-Code bereit, verbundene Nummer, Nachrichtenzaehler."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        """Fragt den Bridge-Status ab."""
        try:
            req = urllib.request.Request(f"{BRIDGE_URL}/status", method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            state = data.get("state", "unbekannt")
            number = data.get("connected_number")
            has_qr = data.get("has_qr", False)
            msg_count = data.get("message_count", 0)
            error = data.get("last_error")

            lines = [f"WhatsApp-Status: {state}"]
            if number:
                lines.append(f"Verbundene Nummer: +{number}")
            if has_qr:
                lines.append("QR-Code bereit zum Scannen (siehe Frontend-Settings)")
            lines.append(f"Empfangene Nachrichten: {msg_count}")
            if error:
                lines.append(f"Letzter Fehler: {error}")

            return "\n".join(lines)
        except urllib.error.URLError:
            return "WhatsApp Bridge nicht erreichbar. Ist der Service gestartet?"
        except Exception as e:
            return f"Fehler: {str(e)}"
