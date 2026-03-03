"""Skill Loader – lädt dynamisch Skills aus dem skills/ Verzeichnis."""

import importlib
import importlib.util
import json
from pathlib import Path

from backend.tools.base import BaseTool


SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

# Defaults für fehlende Manifest-Felder
MANIFEST_DEFAULTS = {
    "category": "sonstige",
    "icon": "puzzle",
    "system": False,
    "enabled": True,
    "config_schema": {},
    "knowledge_docs": [],
    "dependencies": [],
    "permissions": [],
}


class SkillLoader:
    """Lädt und verwaltet externe Skills/Module."""

    def __init__(self):
        self.loaded_skills: dict[str, dict] = {}

    def discover_skills(self) -> list[dict]:
        """Scannt das Skills-Verzeichnis nach verfügbaren Skills."""
        skills = []

        if not SKILLS_DIR.exists():
            SKILLS_DIR.mkdir(exist_ok=True)
            return skills

        for skill_dir in sorted(SKILLS_DIR.iterdir()):
            if not skill_dir.is_dir():
                continue

            manifest = skill_dir / "skill.json"
            if not manifest.exists():
                continue

            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))

                # Defaults für fehlende Felder setzen (Abwärtskompatibilität)
                for key, default in MANIFEST_DEFAULTS.items():
                    if key not in data:
                        data[key] = default

                data["path"] = str(skill_dir)
                data["dir_name"] = skill_dir.name
                data["loaded"] = skill_dir.name in self.loaded_skills
                skills.append(data)
            except Exception as e:
                skills.append({
                    "name": skill_dir.name,
                    "error": str(e),
                    "path": str(skill_dir),
                    "dir_name": skill_dir.name,
                })

        return skills

    def load_skill(self, skill_name: str) -> list[BaseTool]:
        """Lädt einen Skill und gibt seine Tools zurück."""
        skill_dir = SKILLS_DIR / skill_name
        manifest = skill_dir / "skill.json"

        if not manifest.exists():
            raise FileNotFoundError(f"Skill \"{skill_name}\" nicht gefunden")

        data = json.loads(manifest.read_text(encoding="utf-8"))
        module_name = data.get("module", "main")

        # Python-Modul aus dem Skill-Verzeichnis laden
        module_path = skill_dir / f"{module_name}.py"
        if not module_path.exists():
            raise FileNotFoundError(f"Skill-Modul \"{module_path}\" nicht gefunden")

        spec = importlib.util.spec_from_file_location(
            f"skills.{skill_name}.{module_name}", str(module_path)
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Tools aus dem Modul sammeln
        tools = []
        if hasattr(module, "get_tools"):
            tools = module.get_tools()
        else:
            # Automatisch alle BaseTool-Subklassen finden
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseTool)
                    and attr is not BaseTool
                ):
                    tools.append(attr())

        self.loaded_skills[skill_name] = {
            "manifest": data,
            "tools": tools,
        }

        return tools

    def unload_skill(self, skill_name: str):
        """Entlädt einen Skill."""
        self.loaded_skills.pop(skill_name, None)
