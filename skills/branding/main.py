"""Branding / White-Label Skill.

Stellt das aktive Firmen-Branding bereit. Die eigentliche Anwendung des
Brandings passiert im Frontend (branding.js) anhand des Endpoints
``/api/branding`` – dieser Skill liefert nur den Lese-Zugriff für den Agenten
und dient als Aktivierungs-Schalter (enabled-Zustand steuert die Sichtbarkeit
des Brandings).
"""

import json
from pathlib import Path

from backend.tools.base import BaseTool


def _load_branding_config() -> dict:
    """Liest die in der Skill-Config hinterlegten Branding-Werte."""
    try:
        from backend.config import config
        states = config.get_skill_states()
        return states.get("branding", {}).get("config", {}) or {}
    except Exception:
        return {}


class BrandingInfoTool(BaseTool):
    """Gibt das aktuell konfigurierte Branding zurück."""

    @property
    def name(self) -> str:
        return "branding_info"

    @property
    def description(self) -> str:
        return ("Gibt das aktuell aktive Firmen-Branding zurück "
                "(Firmenname, Farben, Logo-Modus).")

    def parameters_schema(self) -> dict:
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> str:
        cfg = _load_branding_config()
        if not cfg:
            return "Es ist kein eigenes Branding konfiguriert (Standard-Jarvis-Design aktiv)."
        return "Aktuelles Branding:\n" + json.dumps(cfg, ensure_ascii=False, indent=2)


def get_tools():
    return [BrandingInfoTool()]
