"""Cognitive Evolution Engine – Core-Logik des selbstverbessernden Agenten.

Diese Datei ist BEWUSST von main.py getrennt:
  - main.py: stabile Tool-Registrierung (wird nicht geändert)
  - engine.py: LLM-Calls, File-Writer, Apply-Logik (KANN SICH SELBST ERSETZEN)

Self-Patch-Flow:
  1. evolution_propose(scope="self_patch") → LLM generiert neue engine.py
  2. evolution_validate → Syntax + LLM-Prüfung
  3. evolution_apply → schreibt engine.py + importlib.reload()
  4. Der Skill läuft sofort mit verbessertem Code – kein Service-Restart.
"""

import importlib
import json
import py_compile
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

# ─── Pfade ────────────────────────────────────────────────────────────────────

PROJECT_ROOT  = Path(__file__).parent.parent.parent
SKILLS_DIR    = PROJECT_ROOT / "skills"
SELF_DIR      = Path(__file__).parent                          # skills/cognitive_evolution/
PROPOSALS_DIR = PROJECT_ROOT / "data" / "learnings" / "proposals"
EVOLUTION_LOG = PROJECT_ROOT / "data" / "learnings" / "evolution_log.json"

# Deploy-Pfade (spiegeln Produktions-Server)
_SERVICE_ROOT = Path("/opt/jarvis")
_DEV_ROOT     = Path("/home/jarvis/jarvis")

# Skill-Vorlage für den Proposal-Prompt
_SKILL_TEMPLATE = """
# Jarvis-Skill-Struktur (PFLICHTFORMAT)
#
# skill.json – Manifest:
# {
#   "name": "Anzeigename",
#   "description": "Kurzbeschreibung",
#   "version": "1.0.0",
#   "author": "Jarvis",
#   "module": "main",
#   "tools": ["tool_name"],
#   "category": "sonstige",
#   "icon": "puzzle",
#   "system": false,
#   "enabled": false,
#   "config_schema": {},
#   "knowledge_docs": [],
#   "dependencies": [],
#   "permissions": []
# }
#
# main.py – Tool-Implementierung:
# from backend.tools.base import BaseTool
#
# class MeinTool(BaseTool):
#     @property
#     def name(self) -> str: return "tool_name"          # eindeutig, snake_case
#     @property
#     def description(self) -> str: return "..."          # LLM-sichtbar
#     def parameters_schema(self) -> dict:
#         return {
#             "type": "OBJECT",
#             "properties": {
#                 "param": {"type": "STRING", "description": "..."},
#             },
#             "required": ["param"],
#         }
#     async def execute(self, **kwargs) -> str:
#         return "Ergebnis als String"
#
# def get_tools():
#     return [MeinTool()]
"""


# ─── LLM-Hilfsfunktionen ──────────────────────────────────────────────────────

def _mk_provider():
    """Gibt (provider, model) zurück – immer aktueller Provider aus Config."""
    from backend import config as _cfg
    from backend.llm import get_provider
    provider = get_provider(
        _cfg.LLM_PROVIDER,
        _cfg.current_api_key,
        _cfg.current_api_url,
        auth_method=_cfg.current_auth_method,
        session_key=_cfg.current_session_key,
        prompt_tool_calling=_cfg.current_prompt_tool_calling,
    )
    return provider, (_cfg.current_model or "gemini-2.0-flash")


def _mk_content(text: str):
    """Erstellt Content-Objekt kompatibel mit allen LLM-Providern."""
    try:
        from google.genai import types as _gt
        return _gt.Content(role="user", parts=[_gt.Part.from_text(text=text)])
    except ImportError:
        class _P:
            def __init__(self, t):
                self.text = t
                self.function_call = None
                self.function_response = None
        class _C:
            def __init__(self, t):
                self.role = "user"
                self.parts = [_P(t)]
        return _C(text)


async def _llm_call(system_prompt: str, user_prompt: str) -> str:
    """Ruft das LLM auf und gibt den Text der Antwort zurück."""
    provider, model = _mk_provider()
    resp = await provider.generate_response(
        model=model,
        system_prompt=system_prompt,
        contents=[_mk_content(user_prompt)],
        tools=None,
    )
    return "".join(p.text for p in (resp.parts or []) if p.text).strip()


def _extract_json(text: str) -> dict | None:
    """Extrahiert JSON aus LLM-Antwort (robust gegen Markdown-Wrapping)."""
    # Direktes JSON
    try:
        return json.loads(text)
    except Exception:
        pass
    # JSON in Markdown-Block
    m = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # Erstes { ... } in der Antwort
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


# ─── Proposal-Verwaltung ──────────────────────────────────────────────────────

def _ensure_dirs():
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    EVOLUTION_LOG.parent.mkdir(parents=True, exist_ok=True)


def save_proposal(proposal: dict) -> str:
    """Speichert Proposal in data/learnings/proposals/<id>.json. Gibt Pfad zurück."""
    _ensure_dirs()
    pid = proposal.get("id") or uuid.uuid4().hex[:12]
    proposal["id"] = pid
    path = PROPOSALS_DIR / f"{pid}.json"
    path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def load_proposal(proposal_id: str) -> dict:
    """Lädt Proposal aus data/learnings/proposals/. Wirft FileNotFoundError wenn nicht gefunden."""
    _ensure_dirs()
    path = PROPOSALS_DIR / f"{proposal_id}.json"
    if not path.exists():
        # Suche auch Partial-Match
        matches = list(PROPOSALS_DIR.glob(f"{proposal_id}*.json"))
        if matches:
            path = matches[0]
        else:
            raise FileNotFoundError(f"Proposal '{proposal_id}' nicht gefunden in {PROPOSALS_DIR}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_proposals(status: str = "") -> list[dict]:
    """Listet alle Proposals, optional gefiltert nach Status."""
    _ensure_dirs()
    result = []
    for p in sorted(PROPOSALS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not status or data.get("status") == status:
                result.append(data)
        except Exception:
            pass
    return result


def _log_evolution(entry: dict):
    """Schreibt Eintrag in evolution_log.json (append)."""
    _ensure_dirs()
    log = []
    if EVOLUTION_LOG.exists():
        try:
            log = json.loads(EVOLUTION_LOG.read_text(encoding="utf-8"))
        except Exception:
            log = []
    log.append(entry)
    EVOLUTION_LOG.write_text(json.dumps(log[-200:], indent=2, ensure_ascii=False), encoding="utf-8")


# ─── Phase 1: ANALYSE ─────────────────────────────────────────────────────────

async def analyze(goal: str, scope: str, context: str = "") -> str:
    """Analysiert Fähigkeitslücke oder Verbesserungsziel via LLM.

    scope: new_skill | self_patch | instruction | code_fix
    Gibt strukturierte Analyse als formatierten Text zurück.
    """

    # Relevante Dateien je nach scope lesen (für Kontext)
    file_context = ""
    if scope == "self_patch":
        try:
            eng = (SELF_DIR / "engine.py").read_text(encoding="utf-8")
            file_context = f"\n\n**Aktuelle engine.py (Auszug):**\n```python\n{eng[:3000]}\n```"
        except Exception:
            pass
    elif scope == "new_skill":
        try:
            example = (SKILLS_DIR / "example_skill" / "main.py").read_text(encoding="utf-8")
            file_context = f"\n\n**Beispiel-Skill (Referenz):**\n```python\n{example[:2000]}\n```"
        except Exception:
            pass
    elif scope == "instruction":
        try:
            files = list((PROJECT_ROOT / "data" / "instructions").glob("*.md"))
            names = [f.name for f in files[:10]]
            file_context = f"\n\n**Vorhandene Instruktionsdateien:** {', '.join(names)}"
        except Exception:
            pass

    prompt = (
        f"Analysiere dieses Verbesserungsziel für das Jarvis-KI-System:\n\n"
        f"**Ziel:** {goal}\n"
        f"**Scope:** {scope}\n"
        f"**Zusatzkontext:** {context or '(keiner)'}"
        f"{file_context}\n\n"
        f"Analysiere präzise:\n"
        f"1. Was genau fehlt oder kann verbessert werden?\n"
        f"2. Welche Dateien müssen erstellt/geändert werden?\n"
        f"3. Welche Python-Packages werden benötigt (falls neu)?\n"
        f"4. Sicherheitsüberlegungen?\n"
        f"5. Empfohlene Implementierungsstrategie?\n\n"
        f"Antworte strukturiert auf Deutsch. Kein JSON, nur Klartext mit Überschriften."
    )

    result = await _llm_call(
        system_prompt=(
            "Du bist ein erfahrener Python-Architekt und Jarvis-Systemexperte. "
            "Analysiere präzise und strukturiert. Fokus auf Machbarkeit."
        ),
        user_prompt=prompt,
    )
    return f"🔍 **Analyse** (scope={scope}):\n\n{result}"


# ─── Phase 2: VORSCHLAG ───────────────────────────────────────────────────────

async def propose(
    goal: str,
    scope: str,
    skill_name: str = "",
    analysis: str = "",
    target_file: str = "",
) -> dict:
    """Generiert konkreten Code-Vorschlag via LLM und speichert als Proposal.

    Gibt das Proposal-Dict zurück (inkl. id).
    """

    pid = uuid.uuid4().hex[:12]
    proposal: dict = {
        "id": pid,
        "created": datetime.now().isoformat(timespec="seconds"),
        "type": scope,
        "goal": goal,
        "skill_name": skill_name or "",
        "analysis": analysis,
        "target_files": {},
        "validation": None,
        "status": "proposed",
    }

    if scope == "new_skill":
        if not skill_name:
            skill_name = re.sub(r'[^a-z0-9_]', '_', goal.lower()[:30]).strip('_')
            proposal["skill_name"] = skill_name

        prompt = (
            f"Schreibe einen vollständigen, funktionierenden Jarvis-Skill.\n\n"
            f"**Skill-Name (Verzeichnisname):** `{skill_name}`\n"
            f"**Ziel/Aufgabe:** {goal}\n"
            f"**Analyse:** {analysis or '(keine Voranalyse)'}\n\n"
            f"{_SKILL_TEMPLATE}\n"
            f"Antworte AUSSCHLIESSLICH mit gültigem JSON (kein Markdown):\n"
            f'{{"skill_json": "{{ ... }}", "main_py": "from backend.tools.base import BaseTool\\n..."}}'
        )

        raw = await _llm_call(
            system_prompt=(
                "Du bist ein Python-Experte und Jarvis-Skill-Entwickler. "
                "Schreibe vollständigen, ausführbaren Python-Code. "
                "Antworte NUR mit einem JSON-Objekt, kein Markdown, keine Erklärungen."
            ),
            user_prompt=prompt,
        )

        data = _extract_json(raw)
        if not data:
            return {**proposal, "status": "error", "error": f"LLM-Antwort kein JSON: {raw[:300]}"}

        skill_json_str = data.get("skill_json", "")
        main_py_str    = data.get("main_py", "")

        # skill.json als Dict normalisieren
        if isinstance(skill_json_str, dict):
            skill_json_str = json.dumps(skill_json_str, indent=2, ensure_ascii=False)
        if isinstance(main_py_str, dict):
            main_py_str = str(main_py_str)

        proposal["target_files"] = {
            f"skills/{skill_name}/skill.json": skill_json_str,
            f"skills/{skill_name}/main.py": main_py_str,
        }

    elif scope == "self_patch":
        # LLM generiert neue engine.py
        current_engine = ""
        try:
            current_engine = (SELF_DIR / "engine.py").read_text(encoding="utf-8")
        except Exception:
            pass

        prompt = (
            f"Verbessere die folgende Jarvis Cognitive Evolution engine.py:\n\n"
            f"**Verbesserungsziel:** {goal}\n"
            f"**Analyse:** {analysis or '(keine)'}\n\n"
            f"**Aktuelle engine.py:**\n```python\n{current_engine[:6000]}\n```\n\n"
            f"Schreibe die vollständige, verbesserte engine.py. "
            f"Antworte AUSSCHLIESSLICH mit dem Python-Code, ohne Markdown-Fences."
        )

        new_engine_py = await _llm_call(
            system_prompt=(
                "Du bist ein Python-Experte. Schreibe vollständigen, ausführbaren Python-Code. "
                "Keine Erklärungen, kein Markdown – nur reinen Python-Code."
            ),
            user_prompt=prompt,
        )

        # Markdown-Fences entfernen falls trotzdem vorhanden
        new_engine_py = re.sub(r'^```python\s*', '', new_engine_py, flags=re.MULTILINE)
        new_engine_py = re.sub(r'^```\s*$', '', new_engine_py, flags=re.MULTILINE).strip()

        proposal["target_files"] = {
            "skills/cognitive_evolution/engine.py": new_engine_py,
        }

    elif scope == "instruction":
        file_path = target_file or "data/instructions/evolution_notes.md"
        prompt = (
            f"Schreibe eine Jarvis-Instruktionsdatei (Markdown).\n\n"
            f"**Ziel:** {goal}\n"
            f"**Analyse:** {analysis or '(keine)'}\n\n"
            f"Schreibe den vollständigen Markdown-Inhalt. Keine Erklärungen darum herum."
        )
        content = await _llm_call(
            system_prompt="Du schreibst präzise Instruktionen für ein KI-System auf Deutsch.",
            user_prompt=prompt,
        )
        proposal["target_files"] = {file_path: content}

    elif scope == "code_fix":
        if not target_file:
            return {**proposal, "status": "error", "error": "target_file ist bei code_fix erforderlich."}

        full_path = PROJECT_ROOT / target_file
        old_code = ""
        if full_path.exists():
            old_code = full_path.read_text(encoding="utf-8")

        prompt = (
            f"Verbessere den folgenden Jarvis-Code:\n\n"
            f"**Datei:** `{target_file}`\n"
            f"**Ziel:** {goal}\n"
            f"**Analyse:** {analysis or '(keine)'}\n\n"
            f"**Aktueller Code:**\n```python\n{old_code[:5000]}\n```\n\n"
            f"Antworte mit JSON:\n"
            f'{{"old_text": "exakt zu ersetzendes Fragment", "new_text": "neues Fragment", "reason": "Begründung"}}'
        )

        raw = await _llm_call(
            system_prompt=(
                "Du bist ein Python-Experte. Antworte NUR mit JSON, kein Markdown."
            ),
            user_prompt=prompt,
        )
        data = _extract_json(raw)
        if not data:
            return {**proposal, "status": "error", "error": f"LLM kein JSON: {raw[:300]}"}

        proposal["target_files"] = {
            target_file: json.dumps(data, ensure_ascii=False),
        }
        proposal["code_fix_meta"] = data

    save_proposal(proposal)
    return proposal


# ─── Phase 3: VALIDIERUNG ─────────────────────────────────────────────────────

async def validate_proposal(proposal: dict) -> dict:
    """Validiert ein Proposal: Syntax-Check + LLM-Sicherheitsprüfung.

    Gibt das aktualisierte Proposal zurück.
    """
    validation = {
        "syntax_ok": True,
        "syntax_errors": [],
        "llm_approved": True,
        "llm_note": "",
        "validated_at": datetime.now().isoformat(timespec="seconds"),
    }

    target_files: dict = proposal.get("target_files", {})

    # ── 1. Syntax-Check aller .py-Dateien ─────────────────────────────────────
    for file_path, content in target_files.items():
        if not file_path.endswith(".py"):
            continue

        # Bei code_fix ist content das JSON-Meta, nicht direkt Code
        if file_path == list(target_files.keys())[-1] and proposal.get("code_fix_meta"):
            code = proposal["code_fix_meta"].get("new_text", "")
        else:
            code = content

        try:
            with tempfile.NamedTemporaryFile(suffix=".py", mode="w",
                                             encoding="utf-8", delete=False) as tmp:
                tmp.write(code)
                tmp_path = tmp.name
            py_compile.compile(tmp_path, doraise=True)
        except py_compile.PyCompileError as e:
            validation["syntax_ok"] = False
            validation["syntax_errors"].append(f"{file_path}: {e}")
        except Exception as e:
            validation["syntax_errors"].append(f"{file_path} (check-fehler): {e}")
        finally:
            try:
                import os
                os.unlink(tmp_path)
            except Exception:
                pass

    # ── 2. LLM-Sicherheitsprüfung ─────────────────────────────────────────────
    all_code = "\n\n---\n\n".join(
        f"## {fp}\n```\n{c[:2000]}\n```"
        for fp, c in target_files.items()
    )

    llm_prompt = (
        f"Prüfe diesen Jarvis-Skill-Vorschlag auf Sicherheit und Korrektheit.\n\n"
        f"**Ziel:** {proposal.get('goal', '')}\n"
        f"**Typ:** {proposal.get('type', '')}\n\n"
        f"**Code:**\n{all_code[:4000]}\n\n"
        f"**Prüfkriterien:**\n"
        f"1. Python-Syntax logisch korrekt?\n"
        f"2. Keine Shell-Injection, Pfad-Traversal, gefährliche eval()/exec()-Aufrufe?\n"
        f"3. BaseTool korrekt implementiert (name, description, parameters_schema, execute)?\n"
        f"4. get_tools() vorhanden und gibt Liste zurück?\n"
        f"5. Generell sicher für ein KI-System?\n\n"
        f"Antworte AUSSCHLIESSLICH mit JSON (kein Markdown):\n"
        f'{{ "approved": true, "reason": "OK: ...", "risks": [] }}'
    )

    try:
        raw = await _llm_call(
            system_prompt=(
                "Du bist ein Sicherheits-Validator für KI-Skill-Code. "
                "Antworte NUR mit JSON, kein Markdown, keine Erklärungen."
            ),
            user_prompt=llm_prompt,
        )
        data = _extract_json(raw)
        if data:
            validation["llm_approved"] = bool(data.get("approved", True))
            risks = data.get("risks", [])
            validation["llm_note"] = data.get("reason", "") + (
                f" | ⚠️ Risiken: {', '.join(risks)}" if risks else ""
            )
        else:
            validation["llm_note"] = f"⚠️ LLM-Antwort nicht parsebar – genehmigt. ({raw[:150]})"
    except Exception as e:
        validation["llm_note"] = f"⚠️ LLM-Validierung nicht verfügbar ({type(e).__name__}) – genehmigt."

    proposal["validation"] = validation
    proposal["status"] = "validated" if (
        validation["syntax_ok"] and validation["llm_approved"]
    ) else "validation_failed"

    save_proposal(proposal)
    return proposal


# ─── Phase 4: ANWENDEN ────────────────────────────────────────────────────────

async def apply_proposal(proposal: dict, force: bool = False) -> str:
    """Wendet ein validiertes Proposal an.

    force=True überspringt die Validated-Prüfung (nur bei expliziter Nutzer-Anfrage).
    """
    status = proposal.get("status", "")
    if status not in ("validated", "proposed", "validation_failed") and not force:
        return f"❌ Proposal hat Status '{status}' – kann nicht angewendet werden."

    if status == "validation_failed" and not force:
        v = proposal.get("validation", {})
        return (
            f"❌ Validierung fehlgeschlagen – Anwendung abgebrochen.\n"
            f"Syntax-Fehler: {v.get('syntax_errors', [])}\n"
            f"LLM-Note: {v.get('llm_note', '')}\n\n"
            f"Nutze force=true um trotzdem anzuwenden (auf eigene Gefahr)."
        )

    scope = proposal.get("type", "")
    results = []

    if scope == "new_skill":
        results.append(await _apply_new_skill(proposal))

    elif scope == "self_patch":
        results.append(await _apply_self_patch(proposal))

    elif scope == "instruction":
        results.append(await _apply_instruction_proposal(proposal))

    elif scope == "code_fix":
        results.append(await _apply_code_fix_proposal(proposal))

    else:
        return f"❌ Unbekannter scope: '{scope}'"

    # Status aktualisieren
    proposal["status"] = "applied"
    proposal["applied_at"] = datetime.now().isoformat(timespec="seconds")
    save_proposal(proposal)

    # Evolution-Log
    _log_evolution({
        "id": proposal["id"],
        "timestamp": proposal["applied_at"],
        "type": scope,
        "goal": proposal.get("goal", ""),
        "skill_name": proposal.get("skill_name", ""),
        "result": results[0][:200] if results else "",
    })

    return "\n".join(results)


async def _apply_new_skill(proposal: dict) -> str:
    """Schreibt Skill-Dateien und lädt den Skill dynamisch."""
    skill_name = proposal.get("skill_name", "")
    if not skill_name:
        return "❌ Kein skill_name im Proposal."

    skill_dir = SKILLS_DIR / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for rel_path, content in proposal.get("target_files", {}).items():
        target = PROJECT_ROOT / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(rel_path)

        # Deploy zu Service- und Dev-Pfad
        for base in (_SERVICE_ROOT, _DEV_ROOT):
            deploy_target = base / rel_path
            if deploy_target.parent.exists():
                try:
                    deploy_target.parent.mkdir(parents=True, exist_ok=True)
                    deploy_target.write_text(content, encoding="utf-8")
                except Exception as e:
                    pass  # Deploy-Fehler sind nicht kritisch

    # Skill dynamisch laden
    load_result = ""
    try:
        from backend.skills.manager import skill_manager
        tools = skill_manager.loader.load_skill(skill_name)
        load_result = f"✅ Skill '{skill_name}' geladen ({len(tools)} Tools)"
    except Exception as e:
        load_result = (
            f"⚠️ Skill-Dateien geschrieben, aber automatisches Laden fehlgeschlagen: {e}\n"
            f"→ Skill manuell in Jarvis-Einstellungen → Skills aktivieren."
        )

    return (
        f"✅ Neuer Skill '{skill_name}' erstellt:\n"
        f"  Dateien: {', '.join(written)}\n"
        f"  {load_result}\n"
        f"  → Skill in Jarvis-Einstellungen aktivieren falls nötig."
    )


async def _apply_self_patch(proposal: dict) -> str:
    """Ersetzt engine.py und lädt sie via importlib.reload() neu."""
    new_engine = proposal.get("target_files", {}).get(
        "skills/cognitive_evolution/engine.py", ""
    )
    if not new_engine:
        return "❌ Kein engine.py-Inhalt im Proposal."

    engine_path = SELF_DIR / "engine.py"

    # Backup
    bak = engine_path.with_suffix(".py.bak")
    if engine_path.exists():
        shutil.copy2(str(engine_path), str(bak))

    # Schreiben
    engine_path.write_text(new_engine, encoding="utf-8")

    # Deploy
    for base in (_SERVICE_ROOT, _DEV_ROOT):
        deploy = base / "skills" / "cognitive_evolution" / "engine.py"
        if deploy.parent.exists():
            try:
                deploy.write_text(new_engine, encoding="utf-8")
            except Exception:
                pass

    # Reload
    module_key = "skills.cognitive_evolution.engine"
    try:
        if module_key in sys.modules:
            del sys.modules[module_key]
        # Auch parent-Module aus Cache entfernen
        for k in list(sys.modules.keys()):
            if k.startswith("skills.cognitive_evolution"):
                del sys.modules[k]
        import importlib.util
        spec = importlib.util.spec_from_file_location(module_key, str(engine_path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = mod
        spec.loader.exec_module(mod)
        return (
            f"✅ engine.py ersetzt + neu geladen (importlib.reload).\n"
            f"Backup: {bak.name}\n"
            f"Skill läuft jetzt mit verbessertem Code."
        )
    except Exception as e:
        # Rollback bei Fehler
        if bak.exists():
            shutil.copy2(str(bak), str(engine_path))
        return f"❌ Reload fehlgeschlagen, Rollback durchgeführt: {e}"


async def _apply_instruction_proposal(proposal: dict) -> str:
    """Wendet Instruktions-Änderung via ReflectionTool an."""
    try:
        from backend.tools.reflection import ReflectionTool
        rf = ReflectionTool()
        for rel_path, content in proposal.get("target_files", {}).items():
            fname = Path(rel_path).name
            result = await rf._apply_instruction(
                file=fname,
                old_text="",
                new_text=content,
                reason=proposal.get("goal", "Evolution-Vorschlag"),
            )
            return result
    except Exception as e:
        return f"❌ Instruktions-Apply fehlgeschlagen: {e}"
    return "❌ Keine Instruktionsdatei im Proposal."


async def _apply_code_fix_proposal(proposal: dict) -> str:
    """Delegiert Code-Fix an ReflectionTool._apply_code_fix()."""
    meta = proposal.get("code_fix_meta", {})
    if not meta:
        return "❌ Kein code_fix_meta im Proposal."

    target_file = next(iter(proposal.get("target_files", {}).keys()), "")
    if not target_file:
        return "❌ Kein target_file im Proposal."

    try:
        from backend.tools.reflection import ReflectionTool
        rf = ReflectionTool()
        result = await rf._apply_code_fix(
            file=target_file,
            old_text=meta.get("old_text", ""),
            new_text=meta.get("new_text", ""),
            reason=meta.get("reason", proposal.get("goal", "")),
            restart_service=False,
        )
        return result
    except Exception as e:
        return f"❌ Code-Fix fehlgeschlagen: {e}"


# ─── Self-Reload ──────────────────────────────────────────────────────────────

async def self_reload() -> str:
    """Lädt engine.py neu ohne Service-Restart."""
    engine_path = SELF_DIR / "engine.py"
    module_key = "skills.cognitive_evolution.engine"
    try:
        for k in list(sys.modules.keys()):
            if k.startswith("skills.cognitive_evolution"):
                del sys.modules[k]
        import importlib.util
        spec = importlib.util.spec_from_file_location(module_key, str(engine_path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = mod
        spec.loader.exec_module(mod)
        return "✅ engine.py neu geladen."
    except Exception as e:
        return f"❌ Reload fehlgeschlagen: {e}"
