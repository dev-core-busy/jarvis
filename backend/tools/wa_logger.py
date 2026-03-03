"""WhatsApp Logger – Strukturiertes Logging fuer die WhatsApp-Integration."""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

# Log-Verzeichnis und Datei
LOG_DIR = Path(__file__).parent.parent.parent / "data" / "logs"
LOG_FILE = LOG_DIR / "whatsapp.log"
MAX_LOG_LINES = 2000  # Max. Eintraege bevor aelteste geloescht werden

_lock = threading.Lock()


def _ensure_dir():
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(level: str, category: str, message: str, meta: dict | None = None, debug_only: bool = False):
    """Schreibt einen strukturierten Log-Eintrag.

    Args:
        level: "INFO", "DEBUG", "WARN", "ERROR"
        category: "incoming", "outgoing", "transcription", "agent", "bridge", "auth", "config"
        message: Kurze Beschreibung
        meta: Optionale Zusatzdaten (dict)
        debug_only: Wenn True, wird nur geschrieben wenn Debug-Modus aktiv
    """
    if debug_only and not _is_debug_enabled():
        return

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level.upper(),
        "cat": category,
        "msg": message,
    }
    if meta:
        entry["meta"] = meta

    line = json.dumps(entry, ensure_ascii=False)

    # Auch auf stdout ausgeben
    print(f"[WhatsApp/{category}] {level}: {message}")

    with _lock:
        _ensure_dir()
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")

            # Rotation: Wenn zu viele Zeilen, aelteste entfernen
            _rotate_if_needed()
        except Exception as e:
            print(f"[WhatsApp/Logger] Schreibfehler: {e}")


def get_logs(lines: int = 100, level: str | None = None, category: str | None = None) -> list[dict]:
    """Liest die letzten N Log-Eintraege, optional gefiltert."""
    _ensure_dir()
    if not LOG_FILE.exists():
        return []

    entries = []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                    if level and entry.get("level") != level.upper():
                        continue
                    if category and entry.get("cat") != category:
                        continue
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass

    return entries[-lines:]


def clear_logs():
    """Loescht alle Log-Eintraege."""
    with _lock:
        try:
            if LOG_FILE.exists():
                LOG_FILE.unlink()
        except Exception as e:
            print(f"[WhatsApp/Logger] Loeschen fehlgeschlagen: {e}")
    # WICHTIG: log() NACH dem Lock-Release aufrufen (sonst Deadlock!)
    log("INFO", "config", "Logs geloescht")


def _rotate_if_needed():
    """Entfernt aelteste Eintraege wenn MAX_LOG_LINES ueberschritten."""
    try:
        if not LOG_FILE.exists():
            return
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        if len(all_lines) > MAX_LOG_LINES:
            keep = all_lines[-MAX_LOG_LINES:]
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.writelines(keep)
    except Exception:
        pass


def _is_debug_enabled() -> bool:
    """Prueft ob Debug-Modus in der WhatsApp-Skill-Config aktiv ist."""
    try:
        settings_path = Path(__file__).parent.parent.parent / "settings.json"
        if not settings_path.exists():
            return False
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
        wa_config = settings.get("skills", {}).get("whatsapp", {}).get("config", {})
        return wa_config.get("debug_mode", False)
    except Exception:
        return False
