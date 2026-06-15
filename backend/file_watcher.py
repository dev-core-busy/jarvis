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
_llm_check_fn = None  # async () -> bool : aktives LLM-Profil erreichbar?
_wa_send_fn = None     # async (path, method, data) -> dict : WhatsApp-Bridge


def init(agent_manager, broadcast_fn, llm_check_fn=None, wa_send_fn=None):
    global _agent_manager, _broadcast_fn, _llm_check_fn, _wa_send_fn
    _agent_manager = agent_manager
    _broadcast_fn = broadcast_fn
    _llm_check_fn = llm_check_fn
    _wa_send_fn = wa_send_fn


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
        """Aktion asynchron ausführen."""
        if _loop and _loop.is_running():
            ctx = {"filepath": filepath, "filename": Path(filepath).name,
                   "event_type": event_type, "src": src or ""}
            asyncio.run_coroutine_threadsafe(
                self._manager._execute(self._watcher["id"], ctx),
                _loop,
            )


class WatcherManager:
    def __init__(self):
        self._observer = Observer()
        self._watchers: list[dict] = []
        self._watches: dict[str, object] = {}  # id → watchdog-Watch
        self._llm_poll_task = None
        self._llm_poll_interval = 60  # Sekunden zwischen LLM-Erreichbarkeitschecks

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
        print(f"[TriggerWatcher] gestartet – {len(self._watchers)} Trigger geladen", flush=True)
        # Hintergrund-Poller fuer llm_down-Trigger
        if self._llm_poll_task is None:
            self._llm_poll_task = _loop.create_task(self._llm_poll_loop())

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

    def add_watcher(self, label: str, trigger_type: str = "file",
                    action_type: str = "agent_task",
                    path: str = "", pattern: str = "*", events: list = None,
                    task: str = "", wa_to: str = "", wa_message: str = "",
                    webhook_url: str = "", webhook_body: str = "",
                    email_to: str = "", email_subject: str = "", email_body: str = "",
                    enabled: bool = True) -> dict:
        watcher = {
            "id": str(uuid.uuid4()),
            "label": label,
            "trigger_type": trigger_type,      # "file" | "llm_down"
            "action_type": action_type,        # "agent_task" | "whatsapp" | "webhook"
            "path": path,
            "pattern": pattern,
            "events": events or ["created"],
            "task": task,
            "wa_to": wa_to,
            "wa_message": wa_message,
            "webhook_url": webhook_url,
            "webhook_body": webhook_body,
            "email_to": email_to,
            "email_subject": email_subject,
            "email_body": email_body,
            "enabled": enabled,
            "last_triggered": None,
            "last_result": None,
            "_llm_state": None,                # interner Zustand fuer llm_down
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
        """Watcher im Observer registrieren (nur Datei-Trigger; llm_down via Poller)."""
        if watcher.get("trigger_type", "file") != "file":
            return
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

    async def _execute(self, watcher_id: str, context: dict) -> str:
        """Aktion eines Triggers ausführen (Agent-Task / WhatsApp / Webhook)."""
        watcher = self.get_watcher(watcher_id)
        if not watcher:
            return "Watcher nicht gefunden"

        filepath = context.get("filepath", "")
        filename = context.get("filename", "")
        event_type = context.get("event_type", "")
        label = watcher["label"]
        action = watcher.get("action_type", "agent_task")

        def _fill(s: str) -> str:
            return (s or "").replace("{filepath}", filepath).replace("{filename}", filename).replace("{event}", event_type)

        print(f"[TriggerWatcher] Event '{event_type}' → '{label}' (Aktion: {action})", flush=True)

        if _broadcast_fn:
            await _broadcast_fn({
                "type": "watcher_event", "event": "started",
                "watcher_id": watcher_id, "label": label,
                "filepath": filepath, "filename": filename, "event_type": event_type,
            })

        result = ""
        t0 = time.time()
        try:
            if action == "whatsapp":
                result = await self._do_whatsapp(watcher.get("wa_to", ""), _fill(watcher.get("wa_message", "")))
            elif action == "webhook":
                result = await self._do_webhook(watcher.get("webhook_url", ""), _fill(watcher.get("webhook_body", "")), context)
            elif action == "email":
                result = await self._do_email(watcher.get("email_to", ""),
                                              _fill(watcher.get("email_subject", "")),
                                              _fill(watcher.get("email_body", "")))
            else:  # agent_task
                if _agent_manager:
                    agent = _agent_manager.get_or_create_main()
                    result = await agent.run_task_headless(_fill(watcher.get("task", "")))
                else:
                    result = "Fehler: AgentManager nicht verfügbar"
            duration = round(time.time() - t0, 1)
            print(f"[TriggerWatcher] '{label}' abgeschlossen in {duration}s", flush=True)
        except Exception as e:
            result = f"Fehler: {e}"
            print(f"[TriggerWatcher] '{label}' Fehler: {e}", flush=True)

        watcher["last_triggered"] = int(time.time())
        watcher["last_result"] = (result or "")[:500]
        self._save()

        if _broadcast_fn:
            await _broadcast_fn({
                "type": "watcher_event", "event": "finished",
                "watcher_id": watcher_id, "label": label, "result": watcher["last_result"],
            })
        return result

    # ─── Aktionen ────────────────────────────────────────────────────────────
    async def _do_whatsapp(self, to: str, message: str) -> str:
        if not _wa_send_fn:
            return "WhatsApp nicht verfügbar (Bridge nicht initialisiert)"
        if not to or not message:
            return "WhatsApp: Empfänger oder Nachricht fehlt"
        r = await _wa_send_fn("/send", method="POST", data={"to": to, "message": message})
        if isinstance(r, dict) and r.get("error"):
            return f"WhatsApp-Fehler: {r.get('error')}"
        return f"WhatsApp an {to} gesendet"

    async def _do_webhook(self, url: str, body: str, context: dict) -> str:
        if not url:
            return "Webhook: keine URL"
        import httpx
        payload = {"text": body, **{k: v for k, v in context.items() if not k.startswith('_')}}
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            resp = await client.post(url, json=payload)
        return f"Webhook {url} → HTTP {resp.status_code}"

    async def _do_email(self, to: str, subject: str, body: str) -> str:
        """E-Mail via Gmail-Tool (OAuth) – LLM-unabhaengig. Erfordert verbundenes Google-Konto."""
        if not to:
            return "E-Mail: kein Empfänger angegeben"

        def _send():
            try:
                from backend.tools.google_gmail import GoogleGmailTool
                return GoogleGmailTool().execute(
                    action="send_mail", to=to,
                    subject=subject or "Jarvis Trigger", body=body or "",
                )
            except Exception as e:
                return f"E-Mail nicht möglich (Google verbunden?): {e}"

        return await asyncio.to_thread(_send)

    # ─── LLM-down Poller ─────────────────────────────────────────────────────
    async def _llm_poll_loop(self):
        """Prüft periodisch das aktive LLM-Profil; feuert llm_down-Trigger beim Übergang erreichbar→down."""
        while True:
            try:
                await asyncio.sleep(self._llm_poll_interval)
                llm_watchers = [w for w in self._watchers
                                if w.get("enabled") and w.get("trigger_type") == "llm_down"]
                if not llm_watchers or not _llm_check_fn:
                    continue
                reachable = bool(await _llm_check_fn())
                for w in llm_watchers:
                    prev = w.get("_llm_state")
                    w["_llm_state"] = reachable
                    # Trigger nur wenn es jetzt down ist UND vorher nicht schon down war (kein Spam)
                    if (not reachable) and (prev is not False):
                        await self._execute(w["id"], {"event_type": "llm_down",
                                                      "filepath": "", "filename": ""})
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TriggerWatcher] LLM-Poll Fehler: {e}", flush=True)

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
