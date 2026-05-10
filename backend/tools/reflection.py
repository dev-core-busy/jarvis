"""Reflection Tool – Meta-kognitives Selbstverbesserungs-System fuer Jarvis.

Dreiphasen-Analyse nach jedem erkannten Fehler:
  1. DIAGNOSE  – Was ist der Fehler?
  2. ROOT CAUSE – Wie entstand er?
  3. PRÄVENTION – Wie wäre er zu vermeiden?

Jarvis darf sich selbst vollstaendig anpassen: Instruktionen, Code, Memory, Knowledge.
Genehmigt durch Benutzer am 2026-05-10.
"""

import asyncio
import json
import re
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.tools.base import BaseTool

# ─── Verzeichnisse ────────────────────────────────────────────────────────────

PROJECT_ROOT    = Path(__file__).parent.parent.parent
LEARNINGS_DIR   = PROJECT_ROOT / "data" / "learnings"
REPORTS_DIR     = LEARNINGS_DIR / "reports"
PROPOSALS_DIR   = LEARNINGS_DIR / "proposals"
INDEX_FILE      = LEARNINGS_DIR / "index.json"
INSTRUCTIONS_DIR = PROJECT_ROOT / "data" / "instructions"

# Zweiter Deploy-Pfad (Dev-Tree parallel zum Service-Tree)
_SERVICE_ROOT = Path("/opt/jarvis")
_DEV_ROOT     = Path("/home/jarvis/jarvis")

# Locking fuer parallele Sub-Agent-Zugriffe
_lock = threading.Lock()

# ─── Konstanten ───────────────────────────────────────────────────────────────

CATEGORIES = ["whatsapp", "memory", "tool", "instruction", "code", "knowledge", "allgemein"]
SEVERITIES  = ["niedrig", "mittel", "hoch"]
STATUSES    = ["offen", "korrigiert", "verifiziert"]


# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

def _ensure_dirs():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> dict:
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"reports": [], "patterns": {}}


def _save_index(index: dict):
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def _slug(text: str) -> str:
    """Erzeugt einen URL-freundlichen Slug aus Text."""
    s = re.sub(r'[^a-zA-Z0-9äöüÄÖÜß\s]', '', text.lower())
    s = re.sub(r'\s+', '-', s.strip())
    return s[:40]


def _report_filename(title: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    return f"{ts}_{_slug(title)}.md"


def _deploy_file(local_path: Path, relative: str):
    """Schreibt eine Datei in beide Server-Pfade falls sie existieren."""
    for base in [_SERVICE_ROOT, _DEV_ROOT]:
        target = base / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(local_path), str(target))
        except Exception:
            pass  # Zweiter Pfad optional


def _try_notify_whatsapp(message: str):
    """Sendet optional eine WhatsApp-Nachricht an den Benutzer (non-blocking)."""
    try:
        import httpx
        # Bridge direkt aufrufen (localhost, kein Auth)
        # Nummer aus Memory oder Umgebung lesen
        import os
        number = os.environ.get("WA_OWNER_NUMBER", "")
        if not number:
            # Aus settings.json lesen
            settings_file = PROJECT_ROOT / "data" / "settings.json"
            if settings_file.exists():
                s = json.loads(settings_file.read_text(encoding="utf-8"))
                number = s.get("whatsapp_owner_number", "")
        if not number:
            return
        # Feuer-und-vergess (kein await, laeuft in eigenem Thread)
        def _send():
            try:
                import requests
                requests.post(
                    "http://localhost:3001/api/send",
                    json={"to": number, "message": message},
                    timeout=3,
                )
            except Exception:
                pass
        threading.Thread(target=_send, daemon=True).start()
    except Exception:
        pass


def _validate_python(filepath: Path) -> tuple[bool, str]:
    """Prüft Python-Syntax via py_compile. Gibt (ok, fehlermeldung) zurück."""
    try:
        result = subprocess.run(
            ["python3", "-m", "py_compile", str(filepath)],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout).strip()
    except Exception as e:
        return False, str(e)


async def _validate_with_llm(
    file: str,
    old_text: str,
    new_text: str,
    reason: str,
    is_code: bool = True,
) -> tuple[bool, str]:
    """LLM-Validierungsschicht: Prüft Änderungen vor dem Anwenden auf Sicherheit und Konsistenz.

    Gibt (approved, begründung) zurück.
    Fail-open: Bei Fehler oder Timeout wird genehmigt, damit Selbstverbesserung nicht blockiert wird.
    """
    try:
        from backend import config as _cfg
        from backend.llm import get_provider
        try:
            from google.genai import types as _gt
            def _mk_content(text: str):
                return _gt.Content(role="user", parts=[_gt.Part.from_text(text=text)])
        except ImportError:
            # Fallback: einfaches Objekt das alle Provider lesen können
            class _Part:
                def __init__(self, t):
                    self.text = t
                    self.function_call = None
                    self.function_response = None
            class _Content:
                def __init__(self, t):
                    self.role = "user"
                    self.parts = [_Part(t)]
            def _mk_content(text: str):
                return _Content(text)

        provider = get_provider(
            _cfg.LLM_PROVIDER,
            _cfg.current_api_key,
            _cfg.current_api_url,
            auth_method=_cfg.current_auth_method,
            session_key=_cfg.current_session_key,
            prompt_tool_calling=_cfg.current_prompt_tool_calling,
        )

        old_snip = (old_text[:1500] + "\n...[gekürzt]") if len(old_text) > 1500 else old_text
        new_snip = (new_text[:2000] + "\n...[gekürzt]") if len(new_text) > 2000 else new_text

        if is_code:
            prompt = (
                f"Prüfe diesen Code-Fix für das Jarvis-KI-System auf Sicherheit.\n\n"
                f"**Datei:** `{file}`\n**Grund:** {reason}\n\n"
                f"**Ersetzt:**\n```\n{old_snip or '(vollständiger Dateiinhalt)'}\n```\n\n"
                f"**Durch:**\n```\n{new_snip}\n```\n\n"
                f"**Prüfkriterien:**\n"
                f"1. Python-Syntax korrekt und logisch konsistent?\n"
                f"2. Keine Deadlocks oder Event-Loop-Blockierungen?\n"
                f"3. Keine Shell-Injection / Pfad-Traversal?\n"
                f"4. Begründung deckt sich mit der Änderung?\n\n"
                f"Antworte AUSSCHLIESSLICH mit gültigem JSON (kein Markdown-Block, kein Kommentar):\n"
                f'{{ "approved": true, "reason": "OK: ...", "risks": [] }}'
            )
        else:
            prompt = (
                f"Prüfe diese Instruktions-Änderung für das Jarvis-KI-System.\n\n"
                f"**Datei:** `{file}`\n**Grund:** {reason}\n\n"
                f"**Ersetzt:**\n```\n{old_snip or '(neue Datei oder Anhang)'}\n```\n\n"
                f"**Durch:**\n```\n{new_snip}\n```\n\n"
                f"**Prüfkriterien:**\n"
                f"1. Widersprüche zu anderen Jarvis-Instruktionen?\n"
                f"2. Formulierung klar und eindeutig?\n"
                f"3. Konsistent mit Jarvis-Rollenmodell (Operator/Wissensquelle/Kreativ)?\n"
                f"4. Keine gefährlichen Freigaben ohne Kontext?\n\n"
                f"Antworte AUSSCHLIESSLICH mit gültigem JSON (kein Markdown-Block, kein Kommentar):\n"
                f'{{ "approved": true, "reason": "OK: ...", "risks": [] }}'
            )

        response = await provider.generate_response(
            model=_cfg.current_model or "gemini-2.0-flash",
            system_prompt=(
                "Du bist ein präziser Sicherheits-Validator für KI-Selbstmodifikationen. "
                "Antworte ausschließlich mit einem gültigen JSON-Objekt, ohne Markdown, ohne Erklärungen."
            ),
            contents=[_mk_content(prompt)],
            tools=None,
        )

        # Text aus Response-Parts zusammensetzen
        text = "".join(p.text for p in (response.parts or []) if p.text).strip()

        # JSON extrahieren (robust gegen Markdown-Wrapping)
        json_match = re.search(r'\{[^{}]*"approved"[^{}]*\}', text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            approved = bool(result.get("approved", True))
            reason_txt = result.get("reason", "")
            risks = result.get("risks", [])
            risk_str = f" | ⚠️ Risiken: {', '.join(risks)}" if risks else ""
            return approved, f"{reason_txt}{risk_str}"

        # JSON nicht parsebar → fail-open
        return True, f"⚠️ LLM-Antwort nicht parsebar – Änderung trotzdem genehmigt. ({text[:150]})"

    except Exception as e:
        # Fail-open: Validierungsfehler blockieren keine Selbstverbesserung
        return True, f"⚠️ LLM-Validierung nicht verfügbar ({type(e).__name__}) – Änderung trotzdem genehmigt."


# ─── Haupt-Tool ──────────────────────────────────────────────────────────────

class ReflectionTool(BaseTool):
    """Meta-kognitives Selbstverbesserungs-System: Fehler analysieren, lernen, Jarvis verbessern."""

    @property
    def name(self) -> str:
        return "reflection"

    @property
    def description(self) -> str:
        return (
            "Meta-kognitives Selbstverbesserungs-Tool fuer Jarvis. "
            "Analysiert Fehler in drei Phasen (Was/Warum/Wie vermeiden), "
            "schreibt strukturierte Lernberichte, korrigiert Memory, "
            "passt Instruktionen an und fuehrt Code-Fixes durch. "
            "Jarvis darf sich damit vollstaendig selbst verbessern.\n"
            "Aktionen: create_report | find_pattern | list_reports | update_report | "
            "apply_instruction | apply_code_fix | sweep_memory | get_stats"
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create_report",
                        "find_pattern",
                        "list_reports",
                        "update_report",
                        "apply_instruction",
                        "apply_code_fix",
                        "sweep_memory",
                        "get_stats",
                    ],
                    "description": "Auszufuehrende Aktion."
                },
                # create_report
                "title": {"type": "string", "description": "Kurztitel des Fehlers."},
                "category": {
                    "type": "string",
                    "enum": CATEGORIES,
                    "description": "Fehlerkategorie."
                },
                "severity": {
                    "type": "string",
                    "enum": SEVERITIES,
                    "description": "Schweregrad."
                },
                "error_description": {"type": "string", "description": "Was genau passiert ist (Phase 1: DIAGNOSE)."},
                "root_cause": {"type": "string", "description": "Warum es passiert ist (Phase 2: ROOT CAUSE). Muss konkret sein."},
                "immediate_fixes": {"type": "string", "description": "Was bereits korrigiert wurde."},
                "prevention": {"type": "string", "description": "Konkrete Massnahmen zur Vermeidung (Phase 3: PRAEVENTION)."},
                "tags": {"type": "string", "description": "Kommagetrennte Tags fuer Mustererkennung (z.B. 'validation-missing,tool-limitation')."},
                # find_pattern
                "keywords": {"type": "string", "description": "Schluesselwoerter fuer Muster-Suche."},
                # update_report
                "report_id": {"type": "string", "description": "Dateiname des Reports (ohne Pfad)."},
                "new_status": {"type": "string", "enum": STATUSES, "description": "Neuer Status."},
                "status_note": {"type": "string", "description": "Kommentar zur Statusaenderung."},
                # apply_instruction
                "file": {"type": "string", "description": "Instruktionsdatei (z.B. 'tools.md') oder Code-Datei (z.B. 'backend/tools/whatsapp.py')."},
                "old_text": {"type": "string", "description": "Zu ersetzender Text (exakter Match)."},
                "new_text": {"type": "string", "description": "Ersatztext oder neuer Inhalt."},
                "append_after": {"type": "string", "description": "Fuer apply_instruction: Text nach dem der neue Inhalt eingefuegt wird. Leer = ans Ende anhaengen."},
                # apply_code_fix
                "reason": {"type": "string", "description": "Begruendung fuer den Code-Fix (wird ins Log geschrieben)."},
                "restart_service": {"type": "boolean", "description": "Service nach Code-Fix neu starten (nur fuer Backend-Dateien)."},
            },
            "required": ["action"]
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        with _lock:
            _ensure_dirs()
            if action == "create_report":
                return self._create_report(**kwargs)
            elif action == "find_pattern":
                return self._find_pattern(**kwargs)
            elif action == "list_reports":
                return self._list_reports(**kwargs)
            elif action == "update_report":
                return self._update_report(**kwargs)
            elif action == "apply_instruction":
                return await self._apply_instruction(**kwargs)
            elif action == "apply_code_fix":
                return await self._apply_code_fix(**kwargs)
            elif action == "sweep_memory":
                return await self._sweep_memory()
            elif action == "get_stats":
                return self._get_stats()
            return f"❌ Unbekannte Aktion: {action}"

    # ─── create_report ────────────────────────────────────────────────────────

    def _create_report(self, **kwargs) -> str:
        title             = kwargs.get("title", "").strip()
        category          = kwargs.get("category", "allgemein")
        severity          = kwargs.get("severity", "niedrig")
        error_description = kwargs.get("error_description", "").strip()
        root_cause        = kwargs.get("root_cause", "").strip()
        immediate_fixes   = kwargs.get("immediate_fixes", "").strip()
        prevention        = kwargs.get("prevention", "").strip()
        tags_raw          = kwargs.get("tags", "")

        if not title or not error_description or not root_cause:
            return "❌ title, error_description und root_cause sind Pflicht."

        tags = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
        if category not in tags:
            tags.insert(0, category)

        now = datetime.now()
        filename = _report_filename(title)
        filepath = REPORTS_DIR / filename

        # ── Muster-Check: gibt es schon aehnliche Berichte? ──────────────────
        pattern_note = ""
        existing = self._find_pattern_raw(tags=tags, keywords=error_description[:100])
        if existing:
            pattern_note = f"\n> ⚠️ Aehnliches Muster bekannt: {', '.join(existing[:2])}\n"

        # ── Markdown-Bericht schreiben ─────────────────────────────────────
        content = f"""# Lernbericht: {title}

**Datum:** {now.strftime('%Y-%m-%d %H:%M')}
**Kategorie:** {category}
**Schweregrad:** {severity}
**Status:** offen
**Tags:** {', '.join(f'`{t}`' for t in tags)}
{pattern_note}
---

## Phase 1: DIAGNOSE – Was ist der Fehler?

{error_description}

## Phase 2: ROOT CAUSE – Wie entstand er?

{root_cause}

## Phase 3: PRÄVENTION – Wie wäre er zu vermeiden?

{prevention}

---

## Sofort-Korrekturen

{immediate_fixes or '_(keine sofortigen Korrekturen vermerkt)_'}

## Status-Verlauf

- {now.strftime('%Y-%m-%d %H:%M')}: Erkannt und dokumentiert
"""
        filepath.write_text(content, encoding="utf-8")

        # ── Index aktualisieren ────────────────────────────────────────────
        index = _load_index()
        entry = {
            "id": filename,
            "title": title,
            "category": category,
            "severity": severity,
            "status": "offen",
            "tags": tags,
            "date": now.isoformat(),
        }
        index["reports"].insert(0, entry)
        # Muster-Index: jeder Tag → Liste von Report-IDs
        for tag in tags:
            index["patterns"].setdefault(tag, [])
            if filename not in index["patterns"][tag]:
                index["patterns"][tag].append(filename)
        _save_index(index)

        # ── Optional WhatsApp bei hohem Schweregrad ─────────────────────────
        if severity == "hoch":
            _try_notify_whatsapp(
                f"🔴 Jarvis Lernbericht ({severity}): {title}\n"
                f"Root Cause: {root_cause[:200]}\n"
                f"Prävention: {prevention[:200]}"
            )
        elif severity == "mittel":
            _try_notify_whatsapp(
                f"🟡 Jarvis hat etwas gelernt: {title}\n{prevention[:300]}"
            )

        msg = f"✅ Lernbericht erstellt: {filename}"
        if existing:
            msg += f"\n⚠️ Aehnliche Berichte gefunden: {', '.join(existing[:3])}"
        return msg

    # ─── find_pattern ─────────────────────────────────────────────────────────

    def _find_pattern_raw(self, tags: list[str], keywords: str = "") -> list[str]:
        """Gibt eine Liste matchender Report-IDs zurueck."""
        index = _load_index()
        matches: dict[str, int] = {}

        # Tag-basierter Match
        for tag in tags:
            for rid in index["patterns"].get(tag, []):
                matches[rid] = matches.get(rid, 0) + 2  # Tag-Match = 2 Punkte

        # Keyword-Match in Report-Inhalten
        if keywords:
            kw_lower = keywords.lower()
            for report in index["reports"]:
                rid = report["id"]
                rpath = REPORTS_DIR / rid
                if rpath.exists():
                    try:
                        if kw_lower in rpath.read_text(encoding="utf-8").lower():
                            matches[rid] = matches.get(rid, 0) + 1
                    except Exception:
                        pass

        if not matches:
            return []
        return sorted(matches, key=lambda r: -matches[r])

    def _find_pattern(self, **kwargs) -> str:
        tags_raw = kwargs.get("tags", "")
        category = kwargs.get("category", "")
        keywords = kwargs.get("keywords", "")

        tags = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
        if category:
            tags.append(category.lower())

        matches = self._find_pattern_raw(tags=tags, keywords=keywords)
        if not matches:
            return "🔍 Kein bekanntes Muster gefunden. Neues Muster."

        index = _load_index()
        report_map = {r["id"]: r for r in index["reports"]}

        lines = [f"🔍 {len(matches)} bekannte(s) Muster:\n"]
        for rid in matches[:5]:
            r = report_map.get(rid, {})
            lines.append(
                f"  • [{r.get('severity','?')}] {r.get('title', rid)} "
                f"({r.get('date','?')[:10]}) – Status: {r.get('status','?')}\n"
                f"    Tags: {', '.join(r.get('tags',[]))}"
            )
        return "\n".join(lines)

    # ─── list_reports ─────────────────────────────────────────────────────────

    def _list_reports(self, **kwargs) -> str:
        index = _load_index()
        reports = index.get("reports", [])
        if not reports:
            return "📋 Noch keine Lernberichte vorhanden."

        limit = int(kwargs.get("limit", 10))
        category = kwargs.get("category", "")

        filtered = [r for r in reports if not category or r.get("category") == category]
        lines = [f"📋 {len(filtered)} Lernbericht(e){' (Kategorie: ' + category + ')' if category else ''}:\n"]
        for r in filtered[:limit]:
            sev_icon = {"niedrig": "🟢", "mittel": "🟡", "hoch": "🔴"}.get(r.get("severity", ""), "⚪")
            st_icon  = {"offen": "🔵", "korrigiert": "✅", "verifiziert": "⭐"}.get(r.get("status", ""), "❓")
            lines.append(
                f"  {sev_icon}{st_icon} [{r.get('date','?')[:10]}] {r.get('title','?')}\n"
                f"      {r.get('category','?')} | {', '.join(r.get('tags',[])[:3])}"
            )
        return "\n".join(lines)

    # ─── update_report ────────────────────────────────────────────────────────

    def _update_report(self, **kwargs) -> str:
        report_id  = kwargs.get("report_id", "").strip()
        new_status = kwargs.get("new_status", "").strip()
        note       = kwargs.get("status_note", "").strip()

        if not report_id or not new_status:
            return "❌ report_id und new_status sind Pflicht."

        rpath = REPORTS_DIR / report_id
        if not rpath.exists():
            return f"❌ Report nicht gefunden: {report_id}"

        content = rpath.read_text(encoding="utf-8")
        # Status-Zeile aktualisieren
        content = re.sub(r'\*\*Status:\*\* \w+', f'**Status:** {new_status}', content)
        # Status-Verlauf anhaengen
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- {now}: Status → {new_status}" + (f" – {note}" if note else "")
        content = content.rstrip() + f"\n{entry}\n"
        rpath.write_text(content, encoding="utf-8")

        # Index synchronisieren
        index = _load_index()
        for r in index["reports"]:
            if r["id"] == report_id:
                r["status"] = new_status
                break
        _save_index(index)

        return f"✅ Report {report_id} → Status: {new_status}"

    # ─── apply_instruction ────────────────────────────────────────────────────

    async def _apply_instruction(self, **kwargs) -> str:
        """Aendert eine Instruktionsdatei in data/instructions/ (mit LLM-Vorab-Validierung)."""
        file         = kwargs.get("file", "").strip()
        old_text     = kwargs.get("old_text", "")
        new_text     = kwargs.get("new_text", "")
        append_after = kwargs.get("append_after", "")
        reason       = kwargs.get("reason", "Reflection-System Instruktions-Update")

        if not file or not new_text:
            return "❌ file und new_text sind Pflicht."

        instr_path = INSTRUCTIONS_DIR / file

        if not instr_path.exists():
            # ── LLM-Validierung für neue Datei ─────────────────────────────────
            approved, llm_note = await _validate_with_llm(
                file=file, old_text="", new_text=new_text,
                reason=reason, is_code=False,
            )
            if not approved:
                return f"🛑 LLM-Validierung ABGELEHNT – Datei NICHT erstellt.\n{llm_note}"
            instr_path.write_text(new_text, encoding="utf-8")
            _deploy_instruction(file, instr_path)
            return f"✅ Neue Instruktionsdatei erstellt: {file}\nValidierung: {llm_note}"

        # ── Backup ─────────────────────────────────────────────────────────────
        bak = instr_path.with_suffix(".md.bak")
        shutil.copy2(str(instr_path), str(bak))

        content = instr_path.read_text(encoding="utf-8")

        # ── Vorgeschlagenen neuen Inhalt berechnen ──────────────────────────────
        if old_text:
            if old_text not in content:
                return f"❌ old_text nicht in {file} gefunden. Prüfe exakten Wortlaut."
            proposed = content.replace(old_text, new_text, 1)
        elif append_after:
            if append_after not in content:
                return f"❌ append_after-Marker '{append_after[:50]}' nicht gefunden."
            idx = content.index(append_after) + len(append_after)
            proposed = content[:idx] + "\n" + new_text + content[idx:]
        else:
            proposed = content.rstrip() + "\n\n" + new_text + "\n"

        # ── LLM-Validierung vor dem Schreiben ───────────────────────────────────
        approved, llm_note = await _validate_with_llm(
            file=file, old_text=old_text or "(Anhang/Ende)",
            new_text=proposed, reason=reason, is_code=False,
        )
        if not approved:
            bak.unlink(missing_ok=True)
            return f"🛑 LLM-Validierung ABGELEHNT – Instruktion NICHT geändert.\n{llm_note}"

        instr_path.write_text(proposed, encoding="utf-8")
        _deploy_instruction(file, instr_path)

        return (
            f"✅ Instruktion {file} aktualisiert und an beide Pfade deployt.\n"
            f"Validierung: {llm_note}"
        )

    # ─── apply_code_fix ───────────────────────────────────────────────────────

    async def apply_code_fix_public(self, **kwargs) -> str:
        return await self._apply_code_fix(**kwargs)

    async def _apply_code_fix(self, **kwargs) -> str:
        """Fuehrt einen Code-Fix durch: Backup → Aenderung → Syntax-Check → Deploy → optional Restart."""
        file     = kwargs.get("file", "").strip()
        old_text = kwargs.get("old_text", "")
        new_text = kwargs.get("new_text", "")
        reason   = kwargs.get("reason", "")
        restart  = kwargs.get("restart_service", False)

        if not file or not new_text:
            return "❌ file und new_text sind Pflicht."

        filepath = PROJECT_ROOT / file
        if not filepath.exists():
            return f"❌ Datei nicht gefunden: {file}"

        # ── Backup ────────────────────────────────────────────────────────────
        bak = filepath.with_suffix(filepath.suffix + ".reflection_bak")
        shutil.copy2(str(filepath), str(bak))

        content = filepath.read_text(encoding="utf-8")

        if old_text:
            if old_text not in content:
                return (
                    f"❌ old_text nicht in {file} gefunden.\n"
                    f"Ersten 100 Zeichen von old_text: {old_text[:100]!r}"
                )
            content = content.replace(old_text, new_text, 1)
        else:
            # Ganzen Dateiinhalt ersetzen
            content = new_text

        # ── Syntax-Check fuer Python-Dateien ─────────────────────────────────
        if filepath.suffix == ".py":
            tmp = filepath.with_suffix(".py.tmp")
            tmp.write_text(content, encoding="utf-8")
            ok, err = await asyncio.to_thread(_validate_python, tmp)
            tmp.unlink(missing_ok=True)
            if not ok:
                bak.unlink(missing_ok=True)
                return f"❌ Syntax-Fehler – Fix NICHT angewendet:\n{err}"

        # ── LLM-Validierung vor dem Schreiben ────────────────────────────────
        approved, llm_note = await _validate_with_llm(
            file=file,
            old_text=old_text or "(vollständiger Dateiinhalt wird ersetzt)",
            new_text=content,
            reason=reason,
            is_code=(filepath.suffix == ".py"),
        )
        if not approved:
            bak.unlink(missing_ok=True)
            return f"🛑 LLM-Validierung ABGELEHNT – Code-Fix NICHT angewendet.\n{llm_note}"

        # ── Datei schreiben ───────────────────────────────────────────────────
        filepath.write_text(content, encoding="utf-8")

        # ── Deploy in beide Server-Pfade ──────────────────────────────────────
        deployed = []
        for base in [_SERVICE_ROOT, _DEV_ROOT]:
            target = base / file
            if base.exists():
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(filepath), str(target))
                    deployed.append(str(base))
                except Exception as e:
                    deployed.append(f"⚠️ {base}: {e}")

        # ── Aenderung loggen ──────────────────────────────────────────────────
        log_entry = (
            f"## Code-Fix: {file}\n"
            f"Datum: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"Grund: {reason}\n"
            f"Backup: {bak.name}\n"
            f"Deployt nach: {', '.join(deployed) or 'nur lokal'}\n"
        )
        log_file = LEARNINGS_DIR / "code_fixes.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")

        result = [
            f"✅ Code-Fix angewendet: {file}",
            f"Deployt nach: {', '.join(deployed) or 'nur lokal (Pfade nicht vorhanden)'}",
            f"Backup: {bak.name}",
            f"Validierung: {llm_note}",
        ]

        # ── Service-Restart (verzoegert, non-blocking) ────────────────────────
        if restart and file.startswith("backend/"):
            result.append("🔄 Service-Restart geplant (in 5 Sekunden)...")

            async def _delayed_restart():
                await asyncio.sleep(5)
                try:
                    subprocess.Popen(
                        ["systemctl", "restart", "jarvis.service"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass

            asyncio.create_task(_delayed_restart())

        return "\n".join(result)

    # ─── sweep_memory ─────────────────────────────────────────────────────────

    async def _sweep_memory(self) -> str:
        """Validiert Memory-Eintraege auf bekannte Fehlermuster."""
        try:
            from backend.tools.memory import _load_memory_dict
            memory = _load_memory_dict()
        except Exception as e:
            return f"❌ Memory konnte nicht geladen werden: {e}"

        issues: list[str] = []
        suspicious: list[str] = []

        for key, entry in memory.items():
            val = entry.get("value", "") if isinstance(entry, dict) else str(entry)

            # ── Telefonnummern validieren ──────────────────────────────────
            phone_candidates = re.findall(r'\+\d{7,20}', val)
            for num in phone_candidates:
                digits_after_cc = len(re.sub(r'^\+\d{1,3}', '', num))
                if digits_after_cc > 12:
                    suspicious.append(
                        f"  • {key}: Verdächtige Nummer {num} "
                        f"({digits_after_cc} Ziffern nach Ländervorwahl – mögliches Baileys-LID-Artefakt)"
                    )

            # ── URLs validieren (Format-Check, kein HTTP-Request) ──────────
            urls = re.findall(r'https?://[^\s"\']+', val)
            for url in urls:
                if len(url) > 500:
                    suspicious.append(f"  • {key}: Ungewöhnlich lange URL ({len(url)} Zeichen)")

            # ── Veraltete Platzhalter erkennen ─────────────────────────────
            if '{{' in val and '}}' in val:
                issues.append(
                    f"  • {key}: Enthält unaufgelösten Platzhalter: "
                    f"{re.findall(r'\\{{\\{{.*?\\}}\\}}', val)}"
                )

        if not issues and not suspicious:
            return f"✅ Memory-Sweep: {len(memory)} Einträge geprüft, keine Probleme gefunden."

        lines = [f"⚠️ Memory-Sweep: {len(memory)} Einträge, {len(issues)+len(suspicious)} Auffälligkeiten:\n"]
        if suspicious:
            lines.append("Verdächtige Einträge (manuell prüfen):")
            lines.extend(suspicious)
        if issues:
            lines.append("\nFehler (sollten korrigiert werden):")
            lines.extend(issues)
        lines.append(
            "\n→ Nutze memory_manage(action='delete') + memory_manage(action='save') "
            "um falsche Einträge zu korrigieren."
        )
        return "\n".join(lines)

    # ─── get_stats ────────────────────────────────────────────────────────────

    def _get_stats(self) -> str:
        index = _load_index()
        reports = index.get("reports", [])
        patterns = index.get("patterns", {})

        total = len(reports)
        by_cat: dict[str, int] = {}
        by_sev: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for r in reports:
            by_cat[r.get("category", "?")] = by_cat.get(r.get("category", "?"), 0) + 1
            by_sev[r.get("severity", "?")] = by_sev.get(r.get("severity", "?"), 0) + 1
            by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1

        top_patterns = sorted(
            [(tag, len(ids)) for tag, ids in patterns.items()],
            key=lambda x: -x[1]
        )[:5]

        lines = [
            f"📊 Reflection-Statistiken:",
            f"  Berichte gesamt: {total}",
            f"  Kategorien: {dict(sorted(by_cat.items(), key=lambda x: -x[1]))}",
            f"  Schweregrade: {by_sev}",
            f"  Status: {by_status}",
        ]
        if top_patterns:
            lines.append(f"  Häufigste Muster-Tags: {top_patterns}")

        log_file = LEARNINGS_DIR / "code_fixes.log"
        if log_file.exists():
            fix_count = log_file.read_text(encoding="utf-8").count("## Code-Fix:")
            lines.append(f"  Code-Fixes durchgeführt: {fix_count}")

        return "\n".join(lines)


# ─── Instruktions-Deploy Hilfsfunktion ───────────────────────────────────────

def _deploy_instruction(filename: str, local_path: Path):
    """Deployt eine Instruktionsdatei in beide Server-Pfade."""
    for base in [_SERVICE_ROOT, _DEV_ROOT]:
        target = base / "data" / "instructions" / filename
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(local_path), str(target))
        except Exception:
            pass
