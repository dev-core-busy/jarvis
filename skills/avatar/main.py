"""Avatar-Assistent Skill.

Die eigentliche Figur ist ein Frontend-Widget (frontend/js/avatar.js), das
seinen Zustand ueber ``/api/avatar/config`` liest und Anfragen an
``/api/avatar/ask`` schickt. Dieser Skill dient als Aktivierungs-Schalter
(enabled-Zustand blendet das Widget ein/aus) und gibt dem Agenten Lesezugriff
auf die aktuelle Konfiguration.
"""

from backend.tools.base import BaseTool


class AvatarInfoTool(BaseTool):
    """Gibt die aktuelle Avatar-Konfiguration zurueck."""

    @property
    def name(self) -> str:
        return "avatar_info"

    @property
    def description(self) -> str:
        return ("Gibt die aktuelle Konfiguration des Avatar-Assistenten zurueck "
                "(Grafik, Bildschirmecke, Anzahl hinterlegter eigener Antworten).")

    def parameters_schema(self) -> dict:
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> str:
        from backend import avatar as av
        if not av.is_active():
            return "Der Avatar-Assistent ist derzeit deaktiviert."
        cfg = av.load_config()
        n = len(av.parse_overrides(cfg.get("overrides", "")))
        lines = [
            "Avatar-Assistent (aktiv):",
            f"- Grafik: {cfg['graphic']}",
            f"- Position: {cfg['position']}",
            f"- Anzeigename: {cfg['title'] or '(Standard)'}",
            f"- Bei Spracheingabe vorlesen: {'ja' if cfg['speak_on_voice'] else 'nein'}",
            f"- Eigene Antworten hinterlegt: {n}",
        ]
        return "\n".join(lines)


def get_tools():
    return [AvatarInfoTool()]
