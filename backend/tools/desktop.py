"""Desktop Tool – Maus, Tastatur und Fenster-Steuerung."""

import asyncio
import os
from pathlib import Path

from backend.tools.base import BaseTool


def _get_env() -> dict:
    return os.environ.copy()



class DesktopTool(BaseTool):
    """Steuert den Linux-Desktop: Mausklicks, Tastatur, Fenster, Programme."""

    @property
    def name(self) -> str:
        return "desktop_control"

    @property
    def description(self) -> str:
        return (
            "Steuert den Linux-Desktop (X11). Aktionen: "
            "'click' – Mausklick an Position (x, y). "
            "'double_click' – Doppelklick an Position (x, y). "
            "'right_click' – Rechtsklick an Position (x, y). "
            "'middle_click' – Mittelklick an Position (x, y). "
            "'triple_click' – Dreifachklick an Position (x, y) (z.B. Zeile markieren). "
            "'type_text' – Text tippen. "
            "'key_press' – Tastenkombination drücken (z.B. 'ctrl+c', 'Return', 'alt+F4'). "
            "'move_mouse' – Maus bewegen. "
            "'scroll' – Mausrad scrollen (direction: up/down/left/right, amount: Klicks). "
            "'drag_and_drop' – Drag & Drop von (x, y) nach (x2, y2). "
            "'open_app' – Programm starten (z.B. 'firefox', 'nautilus'). "
            "'get_active_window' – Info über aktives Fenster. "
            "'list_windows' – Alle offenen Fenster auflisten. "
            "'focus_window' – Fenster fokussieren (per Name oder ID). "
            "'close_window' – Aktives Fenster schließen. "
            "'minimize_window' – Fenster minimieren. "
            "'maximize_window' – Fenster maximieren. "
            "'resize_window' – Fenstergröße ändern (width, height). "
            "'move_window' – Fenster verschieben (x, y). "
            "'clipboard_get' – Zwischenablage lesen. "
            "'clipboard_set' – Text in Zwischenablage setzen."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "Aktion: click, double_click, right_click, middle_click, triple_click, "
                        "type_text, key_press, move_mouse, scroll, drag_and_drop, open_app, "
                        "get_active_window, list_windows, focus_window, close_window, "
                        "minimize_window, maximize_window, resize_window, move_window, "
                        "clipboard_get, clipboard_set"
                    ),
                },
                "x": {
                    "type": "INTEGER",
                    "description": "X-Koordinate (für click/move_mouse/drag_and_drop/move_window)",
                },
                "y": {
                    "type": "INTEGER",
                    "description": "Y-Koordinate (für click/move_mouse/drag_and_drop/move_window)",
                },
                "x2": {
                    "type": "INTEGER",
                    "description": "Ziel-X-Koordinate (für drag_and_drop)",
                },
                "y2": {
                    "type": "INTEGER",
                    "description": "Ziel-Y-Koordinate (für drag_and_drop)",
                },
                "text": {
                    "type": "STRING",
                    "description": "Text zum Tippen, Programmname, Fenstername oder Clipboard-Inhalt",
                },
                "app_name": {
                    "type": "STRING",
                    "description": "Programmname zum Starten (z.B. bei open_app)",
                },
                "keys": {
                    "type": "STRING",
                    "description": "Tastenkombination (z.B. 'ctrl+c', 'Return', 'alt+F4')",
                },
                "key_combination": {
                    "type": "STRING",
                    "description": "Tastenkombination (z.B. 'ctrl+c', alternativ zu 'keys')",
                },
                "direction": {
                    "type": "STRING",
                    "description": "Scroll-Richtung: up, down, left, right",
                },
                "amount": {
                    "type": "INTEGER",
                    "description": "Scroll-Menge in Klicks (Standard: 3)",
                },
                "width": {
                    "type": "INTEGER",
                    "description": "Fensterbreite (für resize_window)",
                },
                "height": {
                    "type": "INTEGER",
                    "description": "Fensterhöhe (für resize_window)",
                },
                "window_id": {
                    "type": "STRING",
                    "description": "Fenster-ID (für focus_window, optional)",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        x: int = 0,
        y: int = 0,
        x2: int = 0,
        y2: int = 0,
        text: str = "",
        keys: str = "",
        app_name: str = "",
        key_combination: str = "",
        direction: str = "down",
        amount: int = 3,
        width: int = 0,
        height: int = 0,
        window_id: str = "",
        **kwargs,
    ) -> str:
        """Führt Desktop-Aktion aus."""

        try:
            if action == "click":
                return await self._run(f"xdotool mousemove --sync {x} {y} sleep 0.05 click 1")

            elif action == "double_click":
                return await self._run(
                    f"xdotool mousemove {x} {y} click --repeat 2 --delay 100 1"
                )

            elif action == "right_click":
                return await self._run(f"xdotool mousemove {x} {y} click 3")

            elif action == "middle_click":
                return await self._run(f"xdotool mousemove {x} {y} click 2")

            elif action == "triple_click":
                return await self._run(
                    f"xdotool mousemove {x} {y} click --repeat 3 --delay 80 1"
                )

            elif action == "type_text":
                # xdotool type mit kurzer Verzögerung für Zuverlässigkeit
                return await self._run(
                    f"xdotool type --clearmodifiers --delay 20 -- {self._shell_escape(text)}"
                )

            elif action == "key_press":
                # z.B. "ctrl+c" → "xdotool key ctrl+c"
                actual_keys = keys if keys else key_combination
                if not actual_keys:
                    return "Fehler: Keine Taste in 'keys' oder 'key_combination' angegeben."
                return await self._run(f"xdotool key --clearmodifiers {actual_keys}")

            elif action == "move_mouse":
                return await self._run(f"xdotool mousemove {x} {y}")

            elif action == "scroll":
                # Button 4=up, 5=down, 6=left, 7=right
                button_map = {"up": 4, "down": 5, "left": 6, "right": 7}
                btn = button_map.get(direction, 5)
                clicks = max(1, amount)
                return await self._run(
                    f"xdotool mousemove {x} {y} click --repeat {clicks} --delay 50 {btn}"
                )

            elif action == "drag_and_drop":
                return await self._run(
                    f"xdotool mousemove {x} {y} mousedown 1 sleep 0.1 "
                    f"mousemove --sync {x2} {y2} sleep 0.1 mouseup 1"
                )

            elif action == "open_app":
                # Programm im Hintergrund starten
                # LLM nutzt manchmal 'text' und manchmal fälschlicherweise 'app_name'
                actual_text = f"{text} {app_name}".strip()
                app_cmd = text if text else app_name
                
                # Intelligenter Wrapper für VM/root Chrome
                if "firefox" in actual_text.lower() or "chrome" in actual_text.lower() or "browser" in actual_text.lower():
                    # Extrahiere URL falls mitgeliefert (z.B. "firefox https://...")
                    url = ""
                    for part in actual_text.split():
                        if "http://" in part or "https://" in part or "www." in part or ".de" in part or ".com" in part:
                            url = part
                            break
                    
                    if url:
                        # Starte direkt Chrome mit der URL (schnellstes Erreichen der Seite)
                        app_cmd = f"google-chrome --no-sandbox --remote-debugging-port=9222 --user-data-dir=/tmp/jarvis-chrome '{url}'"
                    else:
                        # Starte nur den Browser
                        app_cmd = "google-chrome --no-sandbox --remote-debugging-port=9222 --user-data-dir=/tmp/jarvis-chrome"
                
                if not app_cmd:
                    return "Fehler: Kein Programmname (weder in text noch app_name) angegeben."
                
                proc = await asyncio.create_subprocess_shell(
                    f"setsid {app_cmd} &",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.sleep(1)  # Kurz warten bis Programm startet
                return f"Programm '{app_cmd}' gestartet"

            elif action == "get_active_window":
                wid = await self._run("xdotool getactivewindow")
                name = await self._run(f"xdotool getactivewindow getwindowname")
                geo = await self._run(f"xdotool getactivewindow getwindowgeometry")
                return f"Fenster-ID: {wid}\nName: {name}\nPosition: {geo}"

            elif action == "list_windows":
                return await self._run("wmctrl -l 2>/dev/null || xdotool search --name '' getwindowname %@")

            elif action == "focus_window":
                if window_id:
                    return await self._run(f"wmctrl -i -a {window_id} 2>/dev/null || xdotool windowactivate {window_id}")
                elif text:
                    return await self._run(f"wmctrl -a {self._shell_escape(text)} 2>/dev/null || xdotool search --name {self._shell_escape(text)} windowactivate")
                else:
                    return "Fehler: Kein Fenstername (text) oder window_id angegeben."

            elif action == "close_window":
                if window_id:
                    return await self._run(f"wmctrl -i -c {window_id} 2>/dev/null || xdotool windowclose {window_id}")
                else:
                    return await self._run("xdotool getactivewindow windowclose")

            elif action == "minimize_window":
                if window_id:
                    return await self._run(f"xdotool windowminimize {window_id}")
                else:
                    return await self._run("xdotool getactivewindow windowminimize")

            elif action == "maximize_window":
                if window_id:
                    return await self._run(f"wmctrl -i -r {window_id} -b add,maximized_vert,maximized_horz")
                else:
                    return await self._run("wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz")

            elif action == "resize_window":
                if not width or not height:
                    return "Fehler: width und height müssen angegeben werden."
                if window_id:
                    return await self._run(f"xdotool windowsize {window_id} {width} {height}")
                else:
                    return await self._run(f"xdotool getactivewindow windowsize {width} {height}")

            elif action == "move_window":
                if window_id:
                    return await self._run(f"xdotool windowmove {window_id} {x} {y}")
                else:
                    return await self._run(f"xdotool getactivewindow windowmove {x} {y}")

            elif action == "clipboard_get":
                return await self._run("xclip -selection clipboard -o 2>/dev/null || xsel --clipboard --output 2>/dev/null || echo 'Zwischenablage leer oder xclip/xsel nicht installiert'")

            elif action == "clipboard_set":
                if not text:
                    return "Fehler: Kein Text für die Zwischenablage angegeben."
                return await self._run(f"echo -n {self._shell_escape(text)} | xclip -selection clipboard 2>/dev/null || echo -n {self._shell_escape(text)} | xsel --clipboard --input 2>/dev/null")

            else:
                return f"Unbekannte Aktion: {action}"

        except Exception as e:
            return f"Desktop-Fehler: {str(e)}"

    async def _run(self, cmd: str) -> str:
        """Hilfsfunktion für Shell-Befehle."""
        env = _get_env()
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        result = stdout.decode("utf-8", errors="replace").strip()
        if stderr:
            err = stderr.decode("utf-8", errors="replace").strip()
            if err:
                result += f"\n(stderr: {err})"
        return result or "(OK)"

    def _shell_escape(self, text: str) -> str:
        """Escaped Text für Shell-Befehle."""
        return "'" + text.replace("'", "'\\''") + "'"
