"""OpenClaw Gmail Skill – Wrapper für das gog-CLI-Tool.

Ruft die vorkompilierte gog-Binary (steipete/gog v0.11.0) via Subprocess auf.
Konfiguration: config['account'] = Gmail-Adresse, Config für gog unter /root/.config/gogcli/.

Setup (einmalig auf dem Server als root):
  1. OAuth-Client in Google Cloud Console erstellen (Typ: Desktop App)
  2. gog auth credentials /pfad/zu/client_secret.json
  3. gog auth add user@gmail.com --services gmail
"""

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool

# Pfad zur gog-Binary im Skill-Verzeichnis
_GOG_BIN = Path(__file__).parent / "gog"
# Fallback: gog im PATH
_GOG_FALLBACK = shutil.which("gog") or ""


def _gog_path() -> str:
    """Gibt den Pfad zur gog-Binary zurück."""
    if _GOG_BIN.exists():
        return str(_GOG_BIN)
    if _GOG_FALLBACK:
        return _GOG_FALLBACK
    raise FileNotFoundError("gog-Binary nicht gefunden unter: " + str(_GOG_BIN))


def _get_config() -> dict:
    """Lädt Skill-Konfiguration aus settings.json."""
    try:
        from backend.config import config
        return config.get_skill_states().get("openclaw_gmail", {}).get("config", {})
    except Exception:
        return {}


async def _run_gog(*args: str) -> dict:
    """Führt gog-Befehl aus und gibt geparste JSON-Antwort zurück.

    Returns:
        {"ok": True, "data": ...} bei Erfolg
        {"ok": False, "error": "..."} bei Fehler
    """
    cfg = _get_config()
    account = cfg.get("account", "").strip()

    cmd = [_gog_path(), "--json", "--no-input"]
    if account:
        cmd += ["--account", account]
    cmd += list(args)

    try:
        import os as _os
        _gog_env = _os.environ.copy()
        _gog_env["GOG_KEYRING_BACKEND"] = "file"
        _gog_env["GOG_KEYRING_PASSWORD"] = "jarvis-gog-keyring"
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_gog_env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Timeout (30s) – gog nicht erreichbar"}
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}

    raw = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()

    # Fehlerstatus aus Return-Code
    if proc.returncode != 0:
        msg = err or raw or f"Exit-Code {proc.returncode}"
        return {"ok": False, "error": msg}

    # JSON parsen
    if raw:
        try:
            return {"ok": True, "data": json.loads(raw)}
        except json.JSONDecodeError:
            return {"ok": True, "data": raw}

    return {"ok": True, "data": {}}


def _format_message(msg: dict) -> str:
    """Formatiert eine E-Mail-Nachricht für den Agent."""
    lines = []
    headers = {h["name"].lower(): h["value"]
               for h in msg.get("payload", {}).get("headers", [])}
    lines.append(f"Von:     {headers.get('from', '–')}")
    lines.append(f"An:      {headers.get('to', '–')}")
    lines.append(f"Betreff: {headers.get('subject', '–')}")
    lines.append(f"Datum:   {headers.get('date', '–')}")
    lines.append(f"ID:      {msg.get('id', '–')}")
    snippet = msg.get("snippet", "")
    if snippet:
        lines.append(f"Vorschau: {snippet}")
    return "\n".join(lines)


def _format_thread_list(data: dict) -> str:
    """Formatiert Suchergebnisse (Threads) kompakt."""
    threads = data.get("threads", []) if isinstance(data, dict) else []
    if not threads:
        return "Keine Ergebnisse gefunden."
    lines = [f"Gefunden: {len(threads)} Thread(s)\n"]
    for t in threads:
        lines.append(f"• ID: {t.get('id', '?')} | Snippet: {t.get('snippet', '')[:80]}")
    return "\n".join(lines)


# ─── Tools ────────────────────────────────────────────────────────────

class GmailSearchTool(BaseTool):
    """Sucht E-Mails in Gmail mit Gmail-Suchsyntax."""

    @property
    def name(self) -> str:
        return "gmail_search"

    @property
    def description(self) -> str:
        return (
            "Sucht E-Mails in Gmail. Unterstützt Gmail-Suchsyntax wie: "
            "'from:boss@firma.de', 'subject:Rechnung', 'newer_than:7d', "
            "'has:attachment', 'in:inbox is:unread'. "
            "Gibt Liste der passenden Threads zurück."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail-Suchabfrage, z.B. 'newer_than:7d is:unread' oder 'from:chef@firma.de subject:Projekt'",
                },
                "max": {
                    "type": "integer",
                    "description": "Maximale Anzahl Ergebnisse (Standard: 10)",
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs) -> str:
        query = kwargs.get("query", "")
        cfg = _get_config()
        max_r = str(kwargs.get("max", cfg.get("max_results", "10")))

        result = await _run_gog("gmail", "search", query, "--max", max_r)
        if not result["ok"]:
            return f"❌ Fehler: {result['error']}"
        return _format_thread_list(result["data"])


class GmailListTool(BaseTool):
    """Listet aktuelle E-Mails im Posteingang auf."""

    @property
    def name(self) -> str:
        return "gmail_list"

    @property
    def description(self) -> str:
        return (
            "Listet die neuesten E-Mails im Posteingang auf. "
            "Zeigt Von, Betreff, Datum und ID. "
            "Nützlich für einen schnellen Überblick."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "max": {
                    "type": "integer",
                    "description": "Maximale Anzahl E-Mails (Standard: 10)",
                },
                "unread_only": {
                    "type": "boolean",
                    "description": "Nur ungelesene E-Mails anzeigen (Standard: false)",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cfg = _get_config()
        max_r = str(kwargs.get("max", cfg.get("max_results", "10")))
        unread_only = kwargs.get("unread_only", False)

        query = "in:inbox"
        if unread_only:
            query += " is:unread"

        result = await _run_gog("gmail", "search", query, "--max", max_r)
        if not result["ok"]:
            return f"❌ Fehler: {result['error']}"
        return _format_thread_list(result["data"])


class GmailReadTool(BaseTool):
    """Liest eine bestimmte E-Mail anhand ihrer ID."""

    @property
    def name(self) -> str:
        return "gmail_read"

    @property
    def description(self) -> str:
        return (
            "Liest den vollständigen Inhalt einer E-Mail anhand der Nachrichten-ID. "
            "Die ID erhält man über gmail_search oder gmail_list. "
            "Gibt Von, An, Betreff, Datum und den vollständigen Nachrichtentext zurück."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Die Gmail-Nachrichten-ID (aus gmail_search/gmail_list)",
                },
            },
            "required": ["message_id"],
        }

    async def execute(self, **kwargs) -> str:
        message_id = kwargs.get("message_id", "").strip()
        if not message_id:
            return "❌ message_id fehlt"

        result = await _run_gog("gmail", "get", message_id)
        if not result["ok"]:
            return f"❌ Fehler: {result['error']}"

        data = result["data"]
        if isinstance(data, dict):
            return _format_message(data)
        return str(data)


class GmailSendTool(BaseTool):
    """Sendet eine E-Mail via Gmail."""

    @property
    def name(self) -> str:
        return "gmail_send"

    @property
    def description(self) -> str:
        return (
            "Sendet eine E-Mail über das konfigurierte Gmail-Konto. "
            "Kann an mehrere Empfänger senden, CC und BCC unterstützen."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Empfänger-E-Mail-Adresse(n), kommagetrennt",
                },
                "subject": {
                    "type": "string",
                    "description": "Betreff der E-Mail",
                },
                "body": {
                    "type": "string",
                    "description": "Nachrichtentext (Plaintext)",
                },
                "cc": {
                    "type": "string",
                    "description": "CC-Empfänger (optional), kommagetrennt",
                },
            },
            "required": ["to", "subject", "body"],
        }

    async def execute(self, **kwargs) -> str:
        to      = kwargs.get("to", "").strip()
        subject = kwargs.get("subject", "").strip()
        body    = kwargs.get("body", "").strip()
        cc      = kwargs.get("cc", "").strip()

        if not to or not subject or not body:
            return "❌ Pflichtfelder fehlen: to, subject, body"

        args = ["gmail", "send",
                "--to", to,
                "--subject", subject,
                "--body", body]
        if cc:
            args += ["--cc", cc]

        result = await _run_gog(*args)
        if not result["ok"]:
            return f"❌ Senden fehlgeschlagen: {result['error']}"

        data = result["data"]
        msg_id = data.get("id", "") if isinstance(data, dict) else ""
        return f"✅ E-Mail gesendet{' (ID: ' + msg_id + ')' if msg_id else ''}."


# ─── get_tools() ──────────────────────────────────────────────────────

def get_tools():
    """Gibt alle Tools dieses Skills zurück."""
    return [
        GmailSearchTool(),
        GmailListTool(),
        GmailReadTool(),
        GmailSendTool(),
    ]
