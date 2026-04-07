"""Claude Bridge Skill – Sendet Anweisungen an die Claude Desktop-App via xdotool."""

import asyncio
import os
import shutil
import subprocess
import time

from backend.tools.base import BaseTool

# Fenster-Klasse der Claude Desktop-App (Electron-App unter Linux)
_CLAUDE_APP_CLASS = "Claude"


def _get_display_env() -> dict:
    """Gibt Umgebungsvariablen mit DISPLAY zurück (Standard :1 für Jarvis-Desktop)."""
    env = os.environ.copy()
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":1"
    return env


def _get_skill_config() -> dict:
    """Liest die Skill-Config zur Laufzeit aus settings.json."""
    try:
        from backend.config import config
        states = config.get_skill_states()
        return states.get("claude_bridge", {}).get("config", {})
    except Exception:
        return {}


def _ensure_deps(env: dict) -> str | None:
    """
    Stellt sicher, dass xdotool und xclip installiert sind.
    Installiert fehlende Pakete automatisch via apt-get.
    Gibt None zurück wenn alles OK, sonst eine Fehlermeldung.
    """
    missing = [
        pkg for pkg, binary in [("xdotool", "xdotool"), ("xclip", "xclip")]
        if not shutil.which(binary)
    ]
    if not missing:
        return None

    for pkg in missing:
        res = subprocess.run(
            ["apt-get", "install", "-y", pkg],
            capture_output=True, text=True
        )
        if res.returncode != 0:
            err = res.stderr.strip()[:200] if res.stderr else "unbekannter Fehler"
            return f"❌ Konnte '{pkg}' nicht automatisch installieren: {err}"

    # Nach Installation erneut prüfen
    if not shutil.which("xdotool"):
        return "❌ xdotool konnte nicht installiert werden – Claude Bridge nicht verfügbar."
    return None


def _find_claude_app_window(env: dict) -> tuple[str, str] | tuple[None, str]:
    """
    Sucht ausschließlich das Claude Desktop-App Fenster über die Fensterklasse.
    Kein Browser-Fallback. Gibt (window_id, window_name) oder (None, fehlermeldung) zurück.
    """
    # Primär: Suche über Fensterklasse (zuverlässigste Methode für Electron-Apps)
    search = subprocess.run(
        ["xdotool", "search", "--onlyvisible", "--class", _CLAUDE_APP_CLASS],
        capture_output=True, text=True, env=env
    )
    window_ids = [w for w in search.stdout.strip().split("\n") if w.strip()]

    if not window_ids:
        # Sekundär: Suche über exakten Fenstertitel "Claude" (kein Substring-Match)
        search2 = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", f"^{_CLAUDE_APP_CLASS}$"],
            capture_output=True, text=True, env=env
        )
        window_ids = [w for w in search2.stdout.strip().split("\n") if w.strip()]

    if not window_ids:
        return None, (
            "❌ Claude Desktop-App nicht gefunden.\n"
            "Bitte sicherstellen, dass die Claude Desktop-App geöffnet und sichtbar ist "
            "(nicht minimiert, nicht auf einem anderen virtuellen Desktop)."
        )

    # Erstes (und i.d.R. einziges) App-Fenster nehmen
    wid = window_ids[0]
    name_res = subprocess.run(
        ["xdotool", "getwindowname", wid],
        capture_output=True, text=True, env=env
    )
    return wid, name_res.stdout.strip()


def _copy_to_clipboard(text: str, env: dict) -> bool:
    """Kopiert Text in die X11-Zwischenablage via xclip. Gibt True zurück wenn erfolgreich."""
    res = subprocess.run(
        ["xclip", "-selection", "clipboard"],
        input=text.encode("utf-8"), env=env
    )
    return res.returncode == 0


# ─── Tool: claude_send ────────────────────────────────────────────────────────

class ClaudeSendTool(BaseTool):
    """Sendet eine Anweisung an die Claude Desktop-App auf dem Jarvis-Desktop."""

    @property
    def name(self) -> str:
        return "claude_send"

    @property
    def description(self) -> str:
        return (
            "Sendet eine Anweisung oder Nachricht an die Claude Desktop-App "
            "auf dem Linux-Desktop. Installiert fehlende Abhängigkeiten automatisch. "
            "Findet die Claude App über ihre Fensterklasse (kein Browser), aktiviert "
            "das Fenster und überträgt den Text per Zwischenablage + Enter. "
            "Die Claude Desktop-App muss geöffnet und sichtbar sein. "
            "Trigger: 'Instruiere Claude mit: [X]', 'Frage Claude: [X]', "
            "'Delegiere an Claude: [X]', 'Schick an Claude: [X]'."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "instruction": {
                    "type": "STRING",
                    "description": "Die Anweisung oder Nachricht, die an Claude gesendet werden soll.",
                },
                "send_return": {
                    "type": "BOOLEAN",
                    "description": "Ob Enter nach dem Einfügen gedrückt werden soll (Standard: true).",
                },
            },
            "required": ["instruction"],
        }

    async def execute(self, instruction: str, send_return: bool = None, **kwargs) -> str:
        cfg = _get_skill_config()
        delay = float(cfg.get("send_delay", 1.0))
        do_return = send_return if send_return is not None else cfg.get("send_return", True)

        try:
            result = await asyncio.to_thread(self._send, instruction, delay, do_return)
            return result
        except Exception as e:
            return f"❌ Fehler beim Senden an Claude Desktop-App: {e}"

    def _send(self, instruction: str, delay: float, send_return: bool) -> str:
        env = _get_display_env()

        # Abhängigkeiten automatisch sicherstellen
        dep_err = _ensure_deps(env)
        if dep_err:
            return dep_err

        # Claude Desktop-App Fenster suchen (ausschließlich App, kein Browser)
        window_id, window_name = _find_claude_app_window(env)
        if window_id is None:
            return window_name  # enthält die Fehlermeldung

        # Fenster in den Vordergrund holen und fokussieren
        subprocess.run(["xdotool", "windowactivate", "--sync", window_id], env=env)
        subprocess.run(["xdotool", "windowfocus", window_id], env=env)
        time.sleep(delay)

        # Text per Zwischenablage einfügen
        _copy_to_clipboard(instruction, env)
        subprocess.run(["xdotool", "key", "--window", window_id, "ctrl+a"], env=env)
        time.sleep(0.1)
        subprocess.run(["xdotool", "key", "--window", window_id, "ctrl+v"], env=env)
        time.sleep(0.25)

        if send_return:
            subprocess.run(["xdotool", "key", "--window", window_id, "Return"], env=env)

        preview = instruction[:120] + ("…" if len(instruction) > 120 else "")
        return (
            f"✅ Anweisung an Claude Desktop-App '{window_name}' (ID: {window_id}) gesendet.\n"
            f"Inhalt: \"{preview}\""
        )


# ─── Entry Point ──────────────────────────────────────────────────────────────

def get_tools():
    """Gibt die Tools dieses Skills zurück."""
    return [ClaudeSendTool()]
