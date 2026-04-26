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


class WaitForChangeTool(BaseTool):
    """Wartet auf eine sichtbare Änderung auf dem Desktop (Screenshot-Diff)."""

    @property
    def name(self) -> str:
        return "wait_for_screen_change"

    @property
    def description(self) -> str:
        return (
            "Wartet aktiv auf eine sichtbare visuelle Änderung auf dem Desktop. "
            "Macht alle 0.5s einen Screenshot und vergleicht Pixel-Differenz. "
            "Gibt bei Änderung einen neuen Screenshot zurück; bei Timeout eine Fehlermeldung."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "timeout_sec": {
                    "type": "integer",
                    "description": "Maximale Wartezeit in Sekunden (Standard: 15, max: 60).",
                },
                "threshold": {
                    "type": "number",
                    "description": "Pixel-Differenz-Schwellwert 0.0–1.0 (Standard: 0.01 = 1%).",
                },
            },
            "required": [],
        }

    async def execute(self, timeout_sec: int = 15, threshold: float = 0.01, **kwargs) -> str:
        try:
            from PIL import Image, ImageChops
            import io
        except ImportError:
            return "Fehler: Pillow ist nicht installiert."

        timeout_sec = min(int(timeout_sec), 60)
        threshold = max(0.0, min(float(threshold), 1.0))

        screenshot_tool = ScreenshotTool()

        async def _take() -> bytes | None:
            result = await screenshot_tool.execute()
            if result.startswith(IMAGE_PREFIX):
                # Format: IMAGE_BASE64:<path>|<b64>
                b64_part = result[len(IMAGE_PREFIX):].split("|", 1)[-1]
                return base64.b64decode(b64_part)
            return None

        baseline_bytes = await _take()
        if not baseline_bytes:
            return "Fehler: Ausgangsbild konnte nicht aufgenommen werden."

        baseline = Image.open(io.BytesIO(baseline_bytes)).convert("RGB")
        total_pixels = baseline.width * baseline.height
        elapsed = 0.0

        while elapsed < timeout_sec:
            await asyncio.sleep(0.5)
            elapsed += 0.5
            current_bytes = await _take()
            if not current_bytes:
                continue
            current = Image.open(io.BytesIO(current_bytes)).convert("RGB")
            diff = ImageChops.difference(baseline, current)
            # Anzahl veränderter Pixel (beliebiger Kanal > 10)
            changed = sum(1 for px in diff.getdata() if max(px) > 10)
            ratio = changed / total_pixels
            if ratio >= threshold:
                b64 = base64.b64encode(current_bytes).decode()
                return f"{IMAGE_PREFIX}/tmp/jarvis_screenshots/waitforchange.png|{b64}"

        return f"⏱️ Timeout nach {timeout_sec}s – keine sichtbare Änderung erkannt (Schwellwert: {threshold*100:.1f}%)."
