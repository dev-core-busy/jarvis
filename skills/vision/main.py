"""Jarvis Vision Skill – Gesichtserkennung via USB-/IP-Kamera.

Stellt 5 Tools bereit:
  - vision_control:   Kamera starten/stoppen
  - vision_status:    Status + erkannte Gesichter
  - vision_snapshot:  Kamerabild aufnehmen
  - vision_train:     Gesicht einlernen
  - vision_profiles:  Profile + Aktionen verwalten
"""

import base64
import json
import os
import tempfile
from datetime import datetime

from backend.tools.base import BaseTool

# ── Engine-Singleton ──────────────────────────────────────────────────────────
_engine = None


def get_engine():
    """Lazy-Init der VisionEngine (ueberlebt Agent-Task-Wechsel)."""
    global _engine
    if _engine is None:
        from skills.vision.vision_engine import VisionEngine
        _engine = VisionEngine(data_dir="data/vision")
    return _engine


def get_tools():
    """Entry-Point fuer den SkillManager."""
    engine = get_engine()
    return [
        VisionControlTool(engine),
        VisionStatusTool(engine),
        VisionSnapshotTool(engine),
        VisionTrainTool(engine),
        VisionProfilesTool(engine),
    ]


# Sentinel fuer Bildrueckgabe (wie ScreenshotTool)
IMAGE_PREFIX = "IMAGE_BASE64:"


# ── Tool 1: vision_control ────────────────────────────────────────────────────

class VisionControlTool(BaseTool):
    """Steuert die Vision-Engine (Kamera starten/stoppen)."""

    def __init__(self, engine):
        self._engine = engine

    @property
    def name(self) -> str:
        return "vision_control"

    @property
    def description(self) -> str:
        return (
            "Steuert die Gesichtserkennungs-Kamera. "
            "Aktionen: 'start' (Kamera einschalten), 'stop' (Kamera ausschalten), "
            "'restart' (Neustart). Optional: source='0' fuer USB-Kamera, "
            "oder RTSP/HTTP-URL fuer IP-Kamera."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Aktion: start, stop oder restart",
                },
                "source": {
                    "type": "STRING",
                    "description": (
                        "Kamera-Quelle: '0' fuer erste USB-Kamera, "
                        "oder RTSP/HTTP-URL fuer IP-Kamera. Standard: '0'"
                    ),
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str = "start", source: str = "0", **kw) -> str:
        action = action.lower().strip()
        if action == "start":
            return self._engine.start(source)
        elif action == "stop":
            return self._engine.stop()
        elif action == "restart":
            self._engine.stop()
            return self._engine.start(source)
        else:
            return f"Unbekannte Aktion: '{action}'. Verwende start, stop oder restart."


# ── Tool 2: vision_status ─────────────────────────────────────────────────────

class VisionStatusTool(BaseTool):
    """Fragt den aktuellen Vision-Status ab."""

    def __init__(self, engine):
        self._engine = engine

    @property
    def name(self) -> str:
        return "vision_status"

    @property
    def description(self) -> str:
        return (
            "Zeigt den aktuellen Status der Gesichtserkennung: "
            "ob die Kamera laeuft, welche Gesichter gerade erkannt werden, "
            "letzte Erkennungs-Events und Anzahl bekannter Profile."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kw) -> str:
        status = self._engine.get_status()
        return json.dumps(status, ensure_ascii=False, indent=2)


# ── Tool 3: vision_snapshot ───────────────────────────────────────────────────

class VisionSnapshotTool(BaseTool):
    """Nimmt ein Kamerabild auf und gibt es ans LLM."""

    def __init__(self, engine):
        self._engine = engine

    @property
    def name(self) -> str:
        return "vision_snapshot"

    @property
    def description(self) -> str:
        return (
            "Macht ein Foto mit der Kamera und gibt das Bild zurueck. "
            "Das Bild zeigt erkannte Gesichter mit Rahmen und Namen. "
            "Nuetzlich um zu sehen wer vor der Kamera steht."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "annotate": {
                    "type": "BOOLEAN",
                    "description": (
                        "Gesichter im Bild markieren und Namen anzeigen. Standard: true"
                    ),
                },
            },
            "required": [],
        }

    async def execute(self, annotate: bool = True, **kw) -> str:
        if not self._engine.is_running():
            return "Fehler: Kamera-Feed ist nicht aktiv. Starte zuerst mit vision_control(action='start')."

        jpeg_data = self._engine.get_snapshot(annotate=annotate)
        if jpeg_data is None:
            return "Fehler: Kein Kamerabild verfuegbar."

        # Temporaer speichern + Base64 (wie ScreenshotTool)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp_dir = "/tmp/jarvis_vision"
        os.makedirs(tmp_dir, exist_ok=True)
        filepath = os.path.join(tmp_dir, f"vision_{ts}.jpg")

        with open(filepath, "wb") as f:
            f.write(jpeg_data)

        b64 = base64.b64encode(jpeg_data).decode("utf-8")
        return f"{IMAGE_PREFIX}{filepath}|{b64}"


# ── Tool 4: vision_train ─────────────────────────────────────────────────────

class VisionTrainTool(BaseTool):
    """Trainiert ein neues Gesicht ein."""

    def __init__(self, engine):
        self._engine = engine

    @property
    def name(self) -> str:
        return "vision_train"

    @property
    def description(self) -> str:
        return (
            "Trainiert ein neues Gesicht ein. Die Person muss vor der Kamera stehen. "
            "Es werden mehrere Fotos aufgenommen und daraus ein Erkennungs-Modell "
            "erstellt. Nach dem Training wird das Gesicht automatisch erkannt."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "name": {
                    "type": "STRING",
                    "description": "Name der Person (z.B. 'Andreas', 'Max')",
                },
                "num_samples": {
                    "type": "INTEGER",
                    "description": "Anzahl Trainingsbilder (Standard: 30)",
                },
            },
            "required": ["name"],
        }

    async def execute(self, name: str = "", num_samples: int = 30, **kw) -> str:
        if not name:
            return "Fehler: Name ist erforderlich."
        return self._engine.start_training(name, num_samples)


# ── Tool 5: vision_profiles ──────────────────────────────────────────────────

class VisionProfilesTool(BaseTool):
    """Verwaltet Gesichts-Profile und Aktionen."""

    def __init__(self, engine):
        self._engine = engine

    @property
    def name(self) -> str:
        return "vision_profiles"

    @property
    def description(self) -> str:
        return (
            "Verwaltet bekannte Gesichter und deren Aktionen. "
            "Aktionen: 'list' (alle Profile anzeigen), "
            "'update' (Aktion fuer Profil setzen: webhook/llm/log), "
            "'delete' (Profil loeschen), 'rename' (umbenennen). "
            "Jedes Profil kann eine Aktion haben: "
            "'webhook' (URL aufrufen), 'llm' (Agent-Task starten), 'log' (nur loggen)."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Aktion: list, update, delete oder rename",
                },
                "name": {
                    "type": "STRING",
                    "description": "Profil-ID (fuer update/delete/rename)",
                },
                "new_name": {
                    "type": "STRING",
                    "description": "Neuer Name (nur fuer rename)",
                },
                "face_action": {
                    "type": "STRING",
                    "description": (
                        "Aktionstyp: 'webhook' (HTTP POST an URL), "
                        "'llm' (Agent-Task mit Prompt starten), "
                        "'log' (nur in Events loggen). Nur fuer update."
                    ),
                },
                "action_value": {
                    "type": "STRING",
                    "description": (
                        "Aktions-Wert: URL fuer webhook, Prompt fuer llm. "
                        "Nur fuer update."
                    ),
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str = "list", name: str = "",
                      new_name: str = "", face_action: str = "",
                      action_value: str = "", **kw) -> str:
        action = action.lower().strip()

        if action == "list":
            profiles = self._engine.list_profiles()
            if not profiles:
                return "Keine Gesichts-Profile vorhanden."
            return json.dumps(profiles, ensure_ascii=False, indent=2)

        elif action == "update":
            if not name:
                return "Fehler: 'name' ist fuer update erforderlich."
            return self._engine.update_profile(
                name,
                action=face_action or None,
                action_value=action_value if action_value else None,
            )

        elif action == "delete":
            if not name:
                return "Fehler: 'name' ist fuer delete erforderlich."
            return self._engine.delete_profile(name)

        elif action == "rename":
            if not name or not new_name:
                return "Fehler: 'name' und 'new_name' sind fuer rename erforderlich."
            return self._engine.rename_profile(name, new_name)

        else:
            return f"Unbekannte Aktion: '{action}'. Verwende list, update, delete oder rename."
