"""Cognitive Evolution Skill – Tool-Definitionen.

Diese Datei ist STABIL und wird NICHT durch Self-Patches geändert.
Die gesamte LLM-Logik liegt in engine.py (selbst-patchbar via importlib.reload).

5 Tools:
  1. evolution_analyze  – Phase 1: Gap-Analyse
  2. evolution_propose  – Phase 2: Code-Generierung + Proposal-Speicherung
  3. evolution_validate – Phase 3: Syntax + LLM-Sicherheitsprüfung
  4. evolution_apply    – Phase 4: Anwendung (new_skill / self_patch / instruction / code_fix)
  5. evolution_cycle    – Vollautomatischer Sub-Agent-Zyklus
"""

from backend.tools.base import BaseTool

# Engine-Modul – enthält alle LLM-Calls und File-Writer
from skills.cognitive_evolution import engine as _engine


# ─── Tool 1: ANALYZE ──────────────────────────────────────────────────────────

class EvolutionAnalyzeTool(BaseTool):
    """Phase 1 des Cognitive-Evolution-Zyklus: Gap-Analyse."""

    @property
    def name(self) -> str:
        return "evolution_analyze"

    @property
    def description(self) -> str:
        return (
            "Phase 1 – Analysiert eine Fähigkeitslücke oder ein Verbesserungsziel für Jarvis. "
            "Gibt strukturierte Analyse zurück: was fehlt, welche Dateien betroffen, Strategie. "
            "Scope: new_skill (neuen Skill schreiben), self_patch (engine.py verbessern), "
            "instruction (Instruktionsdatei ändern), code_fix (Backend-Code patchen)."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "goal": {
                    "type": "STRING",
                    "description": "Was soll verbessert oder ergänzt werden? (z.B. 'Jarvis kann keine PDFs lesen')",
                },
                "scope": {
                    "type": "STRING",
                    "description": "Art der Änderung",
                    "enum": ["new_skill", "self_patch", "instruction", "code_fix"],
                },
                "context": {
                    "type": "STRING",
                    "description": "Optionaler Zusatzkontext (Fehlerbeschreibung, Beispiele etc.)",
                },
            },
            "required": ["goal", "scope"],
        }

    async def execute(self, **kwargs) -> str:
        goal    = kwargs.get("goal", "")
        scope   = kwargs.get("scope", "new_skill")
        context = kwargs.get("context", "")
        return await _engine.analyze(goal=goal, scope=scope, context=context)


# ─── Tool 2: PROPOSE ──────────────────────────────────────────────────────────

class EvolutionProposeTool(BaseTool):
    """Phase 2 des Cognitive-Evolution-Zyklus: Code-Generierung."""

    @property
    def name(self) -> str:
        return "evolution_propose"

    @property
    def description(self) -> str:
        return (
            "Phase 2 – LLM generiert konkreten Code oder Text basierend auf dem Ziel. "
            "Bei scope=new_skill: erzeugt skill.json + main.py für einen neuen Skill. "
            "Bei scope=self_patch: generiert verbesserte engine.py für diesen Skill selbst. "
            "Bei scope=instruction: erstellt neuen Instruktionstext. "
            "Bei scope=code_fix: generiert old_text/new_text-Patch für eine Backend-Datei. "
            "Speichert Proposal in data/learnings/proposals/ und gibt die proposal_id zurück."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "goal": {
                    "type": "STRING",
                    "description": "Was soll der neue Code/die Änderung leisten?",
                },
                "scope": {
                    "type": "STRING",
                    "description": "Art der Änderung",
                    "enum": ["new_skill", "self_patch", "instruction", "code_fix"],
                },
                "skill_name": {
                    "type": "STRING",
                    "description": "Verzeichnisname des neuen Skills (nur bei scope=new_skill, snake_case)",
                },
                "analysis": {
                    "type": "STRING",
                    "description": "Ergebnis von evolution_analyze (optional, verbessert Qualität)",
                },
                "target_file": {
                    "type": "STRING",
                    "description": "Relativer Pfad zur Zieldatei (nur bei scope=code_fix, z.B. 'backend/tools/memory.py')",
                },
            },
            "required": ["goal", "scope"],
        }

    async def execute(self, **kwargs) -> str:
        goal        = kwargs.get("goal", "")
        scope       = kwargs.get("scope", "new_skill")
        skill_name  = kwargs.get("skill_name", "")
        analysis    = kwargs.get("analysis", "")
        target_file = kwargs.get("target_file", "")

        proposal = await _engine.propose(
            goal=goal,
            scope=scope,
            skill_name=skill_name,
            analysis=analysis,
            target_file=target_file,
        )

        if proposal.get("status") == "error":
            return f"❌ Fehler bei Proposal-Generierung: {proposal.get('error', '')}"

        files = list(proposal.get("target_files", {}).keys())
        preview = "\n".join(
            f"  • `{f}` ({len(c)} Zeichen)"
            for f, c in list(proposal.get("target_files", {}).items())[:3]
        )

        return (
            f"📝 **Proposal erstellt** (ID: `{proposal['id']}`)\n"
            f"Typ: {scope} | Ziel: {goal[:80]}\n"
            f"Dateien:\n{preview}\n\n"
            f"→ Nächster Schritt: `evolution_validate(proposal_id=\"{proposal['id']}\")`"
        )


# ─── Tool 3: VALIDATE ─────────────────────────────────────────────────────────

class EvolutionValidateTool(BaseTool):
    """Phase 3 des Cognitive-Evolution-Zyklus: Validierung."""

    @property
    def name(self) -> str:
        return "evolution_validate"

    @property
    def description(self) -> str:
        return (
            "Phase 3 – Validiert ein gespeichertes Proposal via Syntax-Check + LLM-Sicherheitsprüfung. "
            "Lädt das Proposal anhand der proposal_id aus data/learnings/proposals/. "
            "Prüft Python-Syntax mit py_compile und lässt ein zweites LLM-Modell den Code sicherheitsprüfen. "
            "Gibt Validierungsergebnis zurück und aktualisiert den Proposal-Status."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "proposal_id": {
                    "type": "STRING",
                    "description": "ID des zu validierenden Proposals (aus evolution_propose)",
                },
            },
            "required": ["proposal_id"],
        }

    async def execute(self, **kwargs) -> str:
        proposal_id = kwargs.get("proposal_id", "")

        try:
            proposal = _engine.load_proposal(proposal_id)
        except FileNotFoundError as e:
            return f"❌ {e}"

        proposal = await _engine.validate_proposal(proposal)
        v = proposal.get("validation", {})

        syntax_icon = "✅" if v.get("syntax_ok") else "❌"
        llm_icon    = "✅" if v.get("llm_approved") else "❌"
        status      = proposal.get("status", "?")

        lines = [
            f"🔬 **Validierung Proposal** `{proposal_id}`",
            f"Status: **{status}**",
            f"{syntax_icon} Syntax-Check: {'OK' if v.get('syntax_ok') else ', '.join(v.get('syntax_errors', []))}",
            f"{llm_icon} LLM-Review: {v.get('llm_note', '(keine Antwort)')}",
        ]

        if status == "validated":
            lines.append(f"\n→ Nächster Schritt: `evolution_apply(proposal_id=\"{proposal_id}\")`")
        elif status == "validation_failed":
            lines.append(f"\n⚠️ Validierung fehlgeschlagen. Mit force=true trotzdem anwenden möglich.")

        return "\n".join(lines)


# ─── Tool 4: APPLY ────────────────────────────────────────────────────────────

class EvolutionApplyTool(BaseTool):
    """Phase 4 des Cognitive-Evolution-Zyklus: Anwendung."""

    @property
    def name(self) -> str:
        return "evolution_apply"

    @property
    def description(self) -> str:
        return (
            "Phase 4 – Wendet ein validiertes Proposal an. "
            "new_skill: Schreibt Skill-Dateien + lädt Skill dynamisch (skill_manager.loader.load_skill). "
            "self_patch: Ersetzt engine.py + lädt sofort via importlib (kein Service-Restart nötig). "
            "instruction: Schreibt Instruktionsdatei via ReflectionTool. "
            "code_fix: Delegiert an ReflectionTool._apply_code_fix (inkl. Backup + Deploy). "
            "Setzt Proposal-Status auf 'applied' und schreibt in evolution_log.json."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "proposal_id": {
                    "type": "STRING",
                    "description": "ID des anzuwendenden Proposals",
                },
                "force": {
                    "type": "BOOLEAN",
                    "description": "true = auch bei fehlgeschlagener Validierung anwenden (nur auf explizite Nutzeranfrage)",
                },
            },
            "required": ["proposal_id"],
        }

    async def execute(self, **kwargs) -> str:
        proposal_id = kwargs.get("proposal_id", "")
        force       = bool(kwargs.get("force", False))

        try:
            proposal = _engine.load_proposal(proposal_id)
        except FileNotFoundError as e:
            return f"❌ {e}"

        return await _engine.apply_proposal(proposal=proposal, force=force)


# ─── Tool 5: CYCLE (vollautomatisch via Sub-Agent) ────────────────────────────

class EvolutionCycleTool(BaseTool):
    """Vollautomatischer Cognitive-Evolution-Zyklus via Sub-Agent."""

    @property
    def name(self) -> str:
        return "evolution_cycle"

    @property
    def description(self) -> str:
        return (
            "Startet einen autonomen Sub-Agenten der alle 4 Phasen des Cognitive-Evolution-Zyklus "
            "selbstständig durchläuft: analyze → propose → validate → apply. "
            "Der Sub-Agent hat Zugriff auf alle evolution_*-Tools und arbeitet ohne Rückfragen. "
            "Ideal für vollautomatische Skill-Generierung oder Self-Improvement-Aufgaben."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "goal": {
                    "type": "STRING",
                    "description": "Verbesserungsziel in natürlicher Sprache (z.B. 'Baue einen Skill der PDFs lesen kann')",
                },
                "scope": {
                    "type": "STRING",
                    "description": "Art der Änderung",
                    "enum": ["new_skill", "self_patch", "instruction", "code_fix"],
                },
                "skill_name": {
                    "type": "STRING",
                    "description": "Verzeichnisname des neuen Skills (bei scope=new_skill empfohlen)",
                },
            },
            "required": ["goal", "scope"],
        }

    async def execute(self, **kwargs) -> str:
        goal       = kwargs.get("goal", "")
        scope      = kwargs.get("scope", "new_skill")
        skill_name = kwargs.get("skill_name", "")

        skill_hint = f" Skill-Name: `{skill_name}`." if skill_name else ""

        task = (
            f"Du bist ein Cognitive Evolution Agent. Führe den vollständigen 4-Phasen-Zyklus durch:\n\n"
            f"**Ziel:** {goal}\n"
            f"**Scope:** {scope}\n"
            f"{skill_hint}\n\n"
            f"**Phasen (in dieser Reihenfolge, keine Rückfragen):**\n"
            f"1. `evolution_analyze(goal=\"{goal}\", scope=\"{scope}\")` – Analyse\n"
            f"2. `evolution_propose(goal=\"{goal}\", scope=\"{scope}\""
            + (f", skill_name=\"{skill_name}\"" if skill_name else "")
            + f", analysis=<ergebnis phase 1>)` – Code generieren\n"
            f"3. `evolution_validate(proposal_id=<id aus phase 2>)` – Validieren\n"
            f"4. `evolution_apply(proposal_id=<id aus phase 2>)` – Anwenden\n\n"
            f"Arbeite vollständig autonom. Berichte nach jeder Phase kurz das Ergebnis."
        )

        import json as _json
        return _json.dumps({
            "_spawn_agent": True,
            "label": f"🧬 Evolution: {goal[:40]}",
            "task": task,
        })


# ─── get_tools ────────────────────────────────────────────────────────────────

def get_tools() -> list:
    return [
        EvolutionAnalyzeTool(),
        EvolutionProposeTool(),
        EvolutionValidateTool(),
        EvolutionApplyTool(),
        EvolutionCycleTool(),
    ]
