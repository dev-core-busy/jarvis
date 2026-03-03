"""Screenshot Tool – erstellt Screenshots des Desktops und sendet das Bild ans LLM."""

import asyncio
import base64
import os
from pathlib import Path
from datetime import datetime

from backend.tools.base import BaseTool


# Sentinel-Prefix, damit der Agent-Loop das Bild-Payload erkennt.
IMAGE_PREFIX = "IMAGE_BASE64:"

# Timeout für Screenshot-Kommandos (Sekunden)
SCREENSHOT_TIMEOUT = 10

def _get_env() -> dict:
    return os.environ.copy()



class ScreenshotTool(BaseTool):
    """Erstellt Screenshots des Linux-Desktops."""

    SCREENSHOT_DIR = Path("/tmp/jarvis_screenshots")

    @property
    def name(self) -> str:
        return "screenshot"

    @property
    def description(self) -> str:
        return (
            "Erstellt einen Screenshot des aktuellen Desktops und gibt das Bild "
            "zurück, damit du den Inhalt sehen und analysieren kannst. "
            "Nutze dies um den aktuellen Zustand des Desktops zu sehen und z.B. "
            "Buttons, Text oder UI-Elemente zu lokalisieren."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "region": {
                    "type": "STRING",
                    "description": (
                        "Optional: Bereich als 'x,y,breite,höhe'. "
                        "Leer lassen für ganzen Bildschirm."
                    ),
                },
                "filename": {
                    "type": "STRING",
                    "description": "Optional: Dateiname für den Screenshot",
                },
            },
            "required": [],
        }

    async def _run_cmd(self, cmd: str, env: dict) -> tuple[int, str, str]:
        """Führt einen Befehl mit Timeout aus."""
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=SCREENSHOT_TIMEOUT
            )
            return (
                proc.returncode or 0,
                stdout.decode("utf-8", errors="replace").strip(),
                stderr.decode("utf-8", errors="replace").strip(),
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return (-1, "", f"Timeout nach {SCREENSHOT_TIMEOUT}s")

    async def execute(
        self,
        region: str = "",
        filename: str = "",
        **kwargs,
    ) -> str:
        """Screenshot erstellen und als Base64 zurückgeben."""
        self.SCREENSHOT_DIR.mkdir(exist_ok=True)

        if not filename:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{ts}.png"

        filepath = self.SCREENSHOT_DIR / filename
        env = _get_env()
        display = env.get("DISPLAY", ":0")
        xauth = env.get("XAUTHORITY", "")

        errors = []

        # Methode 1: scrot
        if region:
            parts = region.split(",")
            if len(parts) == 4:
                x, y, w, h = parts
                cmd = f"scrot -a {x},{y},{w},{h} {filepath}"
            else:
                return "Ungültiges Region-Format. Verwende: x,y,breite,höhe"
        else:
            cmd = f"scrot --silent {filepath}"

        rc, out, err = await self._run_cmd(cmd, env)
        if rc != 0 or not filepath.exists():
            errors.append(f"scrot: {err}")
            # Methode 2: import (ImageMagick) mit Timeout
            cmd2 = f"import -window root -display {display} {filepath}"
            rc2, out2, err2 = await self._run_cmd(cmd2, env)
            if rc2 != 0 or not filepath.exists():
                errors.append(f"import: {err2}")
                # Methode 3: xwd + ffmpeg/pnmtopng
                tmp_xwd = str(filepath).replace(".png", ".xwd")
                cmd3 = f"xwd -root -silent -display {display} > {tmp_xwd} && convert {tmp_xwd} {filepath} 2>&1; rm -f {tmp_xwd}"
                rc3, out3, err3 = await self._run_cmd(cmd3, env)
                if rc3 != 0 or not filepath.exists():
                    errors.append(f"xwd+convert: {err3}")

        if filepath.exists():
            # Bild als Base64 lesen und ans LLM zurückgeben
            image_data = filepath.read_bytes()
            b64 = base64.b64encode(image_data).decode("utf-8")
            return f"{IMAGE_PREFIX}{filepath}|{b64}"
        else:
            return (
                f"❌ Screenshot konnte nicht erstellt werden "
                f"(DISPLAY={display}, XAUTH={xauth}). "
                f"Fehler: {'; '.join(errors)}"
            )
