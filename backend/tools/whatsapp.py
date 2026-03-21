"""WhatsApp Tools – Nachrichten senden und Bridge-Status abfragen."""

import json
import urllib.request
import urllib.error
import urllib.parse

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
        # LLMs verwenden manchmal 'phone_number' statt 'to'
        if not to:
            to = kwargs.get("phone_number", "")
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


class WhatsAppContactsTool(BaseTool):
    """Durchsucht das WhatsApp-Adressbuch nach Kontakten."""

    @property
    def name(self) -> str:
        return "whatsapp_contacts"

    @property
    def description(self) -> str:
        return (
            "Durchsucht das WhatsApp-Adressbuch nach einem Kontakt anhand des Namens. "
            "Gibt Telefonnummer, gespeicherten Namen und Anzeigenamen zurueck. "
            "Nutze dieses Tool, wenn der Benutzer eine WhatsApp-Nachricht an einen "
            "Namen statt an eine Telefonnummer senden will."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "search": {
                    "type": "STRING",
                    "description": "Suchbegriff: Name oder Telefonnummer (teilweise genuegt)",
                },
            },
            "required": ["search"],
        }

    async def execute(self, search: str = "", **kwargs) -> str:
        """Durchsucht die Kontaktliste."""
        if not search:
            return "Fehler: 'search' ist ein Pflichtfeld."

        try:
            url = f"{BRIDGE_URL}/contacts?search={urllib.parse.quote(search)}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            results = data.get("contacts", [])
            if not results:
                return f"Kein Kontakt gefunden fuer '{search}'."

            lines = [f"{len(results)} Kontakt(e) gefunden:"]
            for c in results[:10]:  # Max 10 Ergebnisse
                name = c.get("name") or c.get("notify") or c.get("verified_name") or "Unbekannt"
                phone = c.get("phone", "")
                extra = []
                if c.get("name"):
                    extra.append(f"Gespeichert: {c['name']}")
                if c.get("notify") and c.get("notify") != c.get("name"):
                    extra.append(f"Anzeigename: {c['notify']}")
                info = f"  +{phone} – {name}"
                if extra:
                    info += f" ({', '.join(extra)})"
                lines.append(info)

            if len(results) > 10:
                lines.append(f"  ... und {len(results) - 10} weitere")

            return "\n".join(lines)
        except urllib.error.URLError:
            return "WhatsApp Bridge nicht erreichbar. Ist der Service gestartet?"
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
