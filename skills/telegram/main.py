"""Jarvis Telegram Bot Skill – empfängt Nachrichten und sendet Antworten."""

import asyncio
import threading
import time
from typing import Optional

from backend.tools.base import BaseTool
from backend.config import config


# ─── Telegram-Manager ────────────────────────────────────────────────────────

class TelegramBotManager:
    """Verwaltet den Telegram Bot (Polling in Background-Thread)."""

    def __init__(self, bot_token: str, allowed_chat_ids: list[int], welcome_message: str):
        self._token = bot_token
        self._allowed = set(allowed_chat_ids) if allowed_chat_ids else set()
        self._welcome = welcome_message or (
            "👋 Hallo! Ich bin Jarvis, dein KI-Assistent.\n"
            "Schreib mir einfach was du brauchst."
        )
        self._app = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._agent_manager = None

    def start(self, agent_manager):
        """Startet den Bot in einem Background-Thread."""
        self._agent_manager = agent_manager
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="telegram-bot")
        self._thread.start()
        print("[Telegram] Bot gestartet", flush=True)

    def stop(self):
        """Stoppt den Bot."""
        self._running = False
        if self._app and self._loop:
            asyncio.run_coroutine_threadsafe(self._app.stop(), self._loop)
        print("[Telegram] Bot gestoppt", flush=True)

    def _run_loop(self):
        """Event-Loop für den Bot-Thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._start_bot())
        except Exception as e:
            print(f"[Telegram] Bot-Fehler: {e}", flush=True)
        finally:
            self._loop.close()

    async def _start_bot(self):
        """Baut die Telegram-App auf und startet Polling."""
        try:
            from telegram.ext import Application, CommandHandler, MessageHandler, filters
        except ImportError:
            print("[Telegram] python-telegram-bot nicht installiert. "
                  "Bitte Skill-Abhängigkeiten installieren.", flush=True)
            return

        self._app = Application.builder().token(self._token).build()
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        print("[Telegram] Polling läuft…", flush=True)

        # Warten bis Stop-Signal
        while self._running:
            await asyncio.sleep(1)

        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()

    def _is_allowed(self, chat_id: int) -> bool:
        """Prüft ob die Chat-ID erlaubt ist."""
        if not self._allowed:
            return True  # Alle erlaubt wenn keine Einschränkung
        return chat_id in self._allowed

    async def _cmd_start(self, update, context):
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            await update.message.reply_text("❌ Du bist nicht autorisiert diesen Bot zu nutzen.")
            return
        await update.message.reply_text(self._welcome)

    async def _cmd_help(self, update, context):
        if not self._is_allowed(update.effective_chat.id):
            return
        await update.message.reply_text(
            "🤖 **Jarvis Bot**\n\n"
            "Schreib mir einfach eine Aufgabe und ich erledige sie für dich.\n\n"
            "Beispiele:\n"
            "• Wie ist die Serverauslastung?\n"
            "• Starte den Backup-Job\n"
            "• Schicke mir eine Zusammenfassung der Logs\n\n"
            "/start – Willkommensnachricht\n"
            "/help – Diese Hilfe",
            parse_mode="Markdown"
        )

    async def _on_message(self, update, context):
        """Verarbeitet eingehende Nachrichten."""
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            await update.message.reply_text("❌ Du bist nicht autorisiert.")
            return

        text = update.message.text
        user_name = update.effective_user.first_name or "Unbekannt"
        print(f"[Telegram] Nachricht von {user_name} ({chat_id}): {text[:80]}", flush=True)

        # Tippt-Indikator
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Agent-Task ausführen
        result = "Fehler: AgentManager nicht verfügbar"
        if self._agent_manager:
            try:
                main_loop = None
                # Versuche den Haupt-Event-Loop zu finden
                try:
                    from backend.main import _get_main_loop
                    main_loop = _get_main_loop()
                except Exception:
                    pass

                if main_loop and main_loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        self._run_agent(text), main_loop
                    )
                    result = future.result(timeout=120)
                else:
                    result = await self._run_agent(text)
            except Exception as e:
                result = f"Fehler: {e}"

        # Antwort senden (max. 4096 Zeichen)
        if result and len(result) > 4000:
            result = result[:4000] + "…"
        await update.message.reply_text(result or "✅ Erledigt.")

    async def _run_agent(self, task_text: str) -> str:
        """Führt einen Agent-Task headless aus."""
        agent = self._agent_manager.get_or_create_main()
        return await agent.run_task_headless(task_text)

    async def send_message(self, chat_id: int, text: str) -> bool:
        """Sendet eine Nachricht an einen Chat."""
        if not self._app:
            return False
        try:
            await self._app.bot.send_message(chat_id=chat_id, text=text)
            return True
        except Exception as e:
            print(f"[Telegram] Send-Fehler: {e}", flush=True)
            return False


# Singleton
_manager: Optional[TelegramBotManager] = None


# ─── Tool ─────────────────────────────────────────────────────────────────────

class TelegramSendTool(BaseTool):
    """Sendet eine Nachricht über den Telegram Bot."""

    @property
    def name(self) -> str:
        return "telegram_send"

    @property
    def description(self) -> str:
        return (
            "Sendet eine Textnachricht über den Telegram Bot an einen bestimmten Chat. "
            "Die Chat-ID bekommst du wenn jemand den Bot anschreibt (wird im Log angezeigt)."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "integer",
                    "description": "Telegram Chat-ID des Empfängers.",
                },
                "text": {
                    "type": "string",
                    "description": "Zu sendender Text (max. 4096 Zeichen).",
                },
            },
            "required": ["chat_id", "text"],
        }

    async def execute(self, chat_id: int = 0, text: str = "", **kwargs) -> str:
        global _manager
        if not _manager:
            return "Fehler: Telegram Bot ist nicht initialisiert. Skill aktivieren und Bot-Token konfigurieren."
        if not chat_id:
            return "Fehler: chat_id fehlt."
        if not text:
            return "Fehler: text fehlt."
        success = await _manager.send_message(int(chat_id), str(text))
        return f"✅ Telegram-Nachricht gesendet an {chat_id}" if success else "❌ Senden fehlgeschlagen."


# ─── Skill-Entry-Point ────────────────────────────────────────────────────────

def get_tools():
    """Initialisiert den Telegram Bot und gibt das Send-Tool zurück."""
    global _manager

    skill_config = config.get_skill_states().get("telegram", {}).get("config", {})
    bot_token = skill_config.get("bot_token", "").strip()

    if not bot_token:
        print("[Telegram] Kein Bot-Token konfiguriert – Bot nicht gestartet.", flush=True)
        return [TelegramSendTool()]

    allowed_raw = skill_config.get("allowed_chat_ids", "")
    allowed_ids = []
    for part in str(allowed_raw).split(","):
        part = part.strip()
        if part.isdigit():
            allowed_ids.append(int(part))

    welcome = skill_config.get("welcome_message", "")

    _manager = TelegramBotManager(bot_token, allowed_ids, welcome)

    # Agent-Manager aus main.py holen (lazy)
    try:
        from backend.main import agent_manager
        if agent_manager:
            _manager.start(agent_manager)
        else:
            print("[Telegram] AgentManager noch nicht bereit – Bot startet später.", flush=True)
    except Exception as e:
        print(f"[Telegram] Fehler beim Start: {e}", flush=True)

    return [TelegramSendTool()]
