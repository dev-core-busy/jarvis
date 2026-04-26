"""Jarvis Datei-Watcher – überwacht Ordner und triggert Agent-Tasks bei Dateiänderungen."""

import asyncio
import fnmatch
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileDeletedEvent, FileMovedEvent
from watchdog.observers import Observer

WATCHERS_FILE = Path("data/file_watchers.json")

# Wird von main.py gesetzt
_agent_manager = None
_broadcast_fn = None  # async fn(msg: dict) → sendet an alle WS-Clients
_loop = None          # asyncio Event-Loop (wird beim Start gespeichert)


def init(agent_manager, broadcast_fn):
    global _agent_manager, _broadcast_fn
    _agent_manager = agent_manager
    _broadcast_fn = broadcast_fn


class _JarvisFileHandler(FileSystemEventHandler):
    """Watchdog Event-Handler für einen einzelnen Watcher."""

    def __init__(self, watcher: dict, watcher_manager):
        super().__init__()
        self._watcher = watcher
        self._manager = watcher_manager

    def _matches(self, path: str) -> bool:
        """Prüft ob Dateipfad dem konfigurierten Pattern entspricht."""
        filename = Path(path).name
        pattern = self._watcher.get("pattern", "*")
        return fnmatch.fnmatch(filename, pattern)

    def on_created(self, event):
        if not event.is_directory and "created" in self._watcher.get("events", []):
            if self._matches(event.src_path):
                self._trigger(event.src_path, "created")

    def on_modified(self, event):
        if not event.is_directory and "modified" in self._watcher.get("events", []):
            if self._matches(event.src_path):
                self._trigger(event.src_path, "modified")

    def on_deleted(self, event):
        if not event.is_directory and "deleted" in self._watcher.get("events", []):
            if self._matches(event.src_path):
                self._trigger(event.src_path, "deleted")

    def on_moved(self, event):
        if not event.is_directory and "moved" in self._watcher.get("events", []):
            if self._matches(event.dest_path):
                self._trigger(event.dest_path, "moved", src=event.src_path)

    def _trigger(self, filepath: str, event_type: str, src: str = None):
        """Task asynchron ausführen."""
        if _loop and _loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._manager._execute(self._watcher["id"], filepath, event_type),
                _loop,
            )


class WatcherManager:
    def __init__(self):
        self._observer = Observer()
        self._watchers: list[dict] = []
        self._watches: dict[str, object] = {}  # id → watchdog-Watch

    # ─── Lifecycle ───────────────────────────────────────────────────────────

    def start(self):
        global _loop
        _loop = asyncio.get_event_loop()
        WATCHERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load()
        self._observer.start()
        for w in self._watchers:
            if w.get("enabled"):
                self._register(w)
        print(f"[FileWatcher] gestartet – {len(self._watchers)} Watcher geladen", flush=True)

    def stop(self):
        try:
            self._observer.stop()
            self._observer.join(timeout=3)
        except Exception:
            pass

    # ─── CRUD ────────────────────────────────────────────────────────────────

    def list_watchers(self) -> list[dict]:
        return self._watchers

    def get_watcher(self, watcher_id: str) -> Optional[dict]:
        return next((w for w in self._watchers if w["id"] == watcher_id), None)

    def add_watcher(self, label: str, path: str, pattern: str, events: list,
                    task: str, enabled: bool = True) -> dict:
        watcher = {
            "id": str(uuid.uuid4()),
            "label": label,
            "path": path,
            "pattern": pattern,
            "events": events,
            "task": task,
            "enabled": enabled,
            "last_triggered": None,
            "last_result": None,
        }
        self._watchers.append(watcher)
        if enabled:
            self._register(watcher)
        self._save()
        return watcher

    def update_watcher(self, watcher_id: str, **fields) -> dict:
        watcher = self.get_watcher(watcher_id)
        if not watcher:
            raise ValueError(f"Watcher {watcher_id} nicht gefunden")
        self._unregister(watcher_id)
        watcher.update(fields)
        if watcher.get("enabled"):
            self._register(watcher)
        self._save()
        return watcher

    def delete_watcher(self, watcher_id: str):
        watcher = self.get_watcher(watcher_id)
        if not watcher:
            raise ValueError(f"Watcher {watcher_id} nicht gefunden")
        self._unregister(watcher_id)
        self._watchers = [w for w in self._watchers if w["id"] != watcher_id]
        self._save()

    # ─── Interna ─────────────────────────────────────────────────────────────

    def _register(self, watcher: dict):
        """Watcher im Observer registrieren."""
        path = watcher.get("path", "")
        if not Path(path).is_dir():
            print(f"[FileWatcher] Pfad existiert nicht: '{path}' – Watcher '{watcher['label']}' deaktiviert", flush=True)
            return
        try:
            handler = _JarvisFileHandler(watcher, self)
            watch = self._observer.schedule(handler, path, recursive=False)
            self._watches[watcher["id"]] = watch
            print(f"[FileWatcher] Registriert: '{watcher['label']}' → {path} ({watcher.get('pattern', '*')})", flush=True)
        except Exception as e:
            print(f"[FileWatcher] Fehler beim Registrieren: {e}", flush=True)

    def _unregister(self, watcher_id: str):
        watch = self._watches.pop(watcher_id, None)
        if watch:
            try:
                self._observer.unschedule(watch)
            except Exception:
                pass

    async def _execute(self, watcher_id: str, filepath: str, event_type: str) -> str:
        """Watcher-Task ausführen."""
        watcher = self.get_watcher(watcher_id)
        if not watcher:
            return "Watcher nicht gefunden"

        filename = Path(filepath).name
        task_text = watcher["task"].replace("{filepath}", filepath).replace("{filename}", filename)
        label = watcher["label"]

        print(f"[FileWatcher] Event '{event_type}' → '{label}': {filename}", flush=True)

        # Broadcast: gestartet
        if _broadcast_fn:
            await _broadcast_fn({
                "type": "watcher_event",
                "event": "started",
                "watcher_id": watcher_id,
                "label": label,
                "filepath": filepath,
                "filename": filename,
                "event_type": event_type,
            })

        result = "Fehler: AgentManager nicht verfügbar"
        t0 = time.time()
        try:
            if _agent_manager:
                agent = _agent_manager.get_or_create_main()
                result = await agent.run_task_headless(task_text)
            duration = round(time.time() - t0, 1)
            print(f"[FileWatcher] '{label}' abgeschlossen in {duration}s", flush=True)
        except Exception as e:
            result = f"Fehler: {e}"
            print(f"[FileWatcher] '{label}' Fehler: {e}", flush=True)

        # Ergebnis speichern
        watcher["last_triggered"] = int(time.time())
        watcher["last_result"] = result[:500] if result else ""
        self._save()

        # Broadcast: fertig
        if _broadcast_fn:
            await _broadcast_fn({
                "type": "watcher_event",
                "event": "finished",
                "watcher_id": watcher_id,
                "label": label,
                "result": watcher["last_result"],
            })

        return result

    def _load(self):
        if WATCHERS_FILE.exists():
            try:
                self._watchers = json.loads(WATCHERS_FILE.read_text())
            except Exception as e:
                print(f"[FileWatcher] Ladefehler: {e}", flush=True)
                self._watchers = []
        else:
            self._watchers = []

    def _save(self):
        WATCHERS_FILE.write_text(json.dumps(self._watchers, indent=2, ensure_ascii=False))


# Singleton
watcher_manager = WatcherManager()
