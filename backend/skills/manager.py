"""Skill Manager – verwaltet alle Skills (Built-in + externe)."""

import shutil
import subprocess
import sys
from pathlib import Path

from backend.skills.loader import SkillLoader
from backend.config import config


class SkillManager:
    """Zentrale Verwaltung aller Jarvis Skills."""

    def __init__(self):
        self.loader = SkillLoader()
        self._load_enabled_skills()

    def _load_enabled_skills(self):
        """Lädt alle aktivierten Skills."""
        self.loader.loaded_skills.clear()
        skill_states = config.get_skill_states()

        for skill_info in self.loader.discover_skills():
            if "error" in skill_info:
                continue

            skill_name = Path(skill_info["path"]).name
            state = skill_states.get(skill_name, {})
            # Enabled aus Config oder aus Manifest-Default
            enabled = state.get("enabled", skill_info.get("enabled", True))

            if enabled:
                try:
                    self.loader.load_skill(skill_name)
                except Exception as e:
                    print(f"Skill '{skill_name}' konnte nicht geladen werden: {e}")

    def list_skills(self) -> list[dict]:
        """Gibt alle Skills mit Manifest und Status zurück."""
        skills = []
        skill_states = config.get_skill_states()

        for skill_info in self.loader.discover_skills():
            if "error" in skill_info:
                skills.append(skill_info)
                continue

            skill_name = Path(skill_info["path"]).name
            state = skill_states.get(skill_name, {})

            skill_info["enabled"] = state.get("enabled", skill_info.get("enabled", True))
            skill_info["config"] = state.get("config", {})
            skill_info["loaded"] = skill_name in self.loader.loaded_skills

            skills.append(skill_info)

        return skills

    def enable_skill(self, name: str) -> bool:
        """Aktiviert einen Skill."""
        config.save_skill_state(name, {"enabled": True})
        try:
            self.loader.load_skill(name)
            return True
        except Exception as e:
            print(f"Skill '{name}' konnte nicht aktiviert werden: {e}")
            return False

    def disable_skill(self, name: str) -> bool:
        """Deaktiviert einen Skill."""
        config.save_skill_state(name, {"enabled": False})
        self.loader.unload_skill(name)
        return True

    def get_skill_config(self, name: str) -> dict:
        """Gibt die Konfiguration eines Skills zurück."""
        states = config.get_skill_states()
        return states.get(name, {}).get("config", {})

    def update_skill_config(self, name: str, data: dict) -> bool:
        """Aktualisiert die Konfiguration eines Skills."""
        states = config.get_skill_states()
        state = states.get(name, {})
        current_config = state.get("config", {})
        current_config.update(data)
        state["config"] = current_config
        if "enabled" not in state:
            state["enabled"] = True
        config.save_skill_state(name, state)
        return True

    def get_enabled_tools(self) -> list:
        """Gibt alle Tools von aktivierten Skills zurück."""
        tools = []
        for skill_name, skill_data in self.loader.loaded_skills.items():
            tools.extend(skill_data["tools"])
        return tools

    def install_dependencies(self, name: str) -> str:
        """Installiert die Abhängigkeiten eines Skills."""
        skills = self.loader.discover_skills()
        skill_info = None
        for s in skills:
            if Path(s.get("path", "")).name == name:
                skill_info = s
                break

        if not skill_info:
            return f"Skill '{name}' nicht gefunden"

        deps = skill_info.get("dependencies", [])
        if not deps:
            return "Keine Abhängigkeiten definiert"

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install"] + deps,
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                joined = ', '.join(deps)
                return f"Abhängigkeiten installiert: {joined}"
            return f"Fehler: {result.stderr}"
        except Exception as e:
            return f"Fehler bei Installation: {e}"

    def uninstall_skill(self, name: str) -> bool:
        """Entfernt einen Skill (nur nicht-system Skills)."""
        skills = self.loader.discover_skills()
        for s in skills:
            if Path(s.get("path", "")).name == name:
                if s.get("system", False):
                    return False
                self.loader.unload_skill(name)
                shutil.rmtree(s["path"])
                config.remove_skill_state(name)
                return True
        return False

    def reload_all(self):
        """Lädt alle Skills neu."""
        self._load_enabled_skills()
