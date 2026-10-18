"""Skill Loader – lädt dynamisch Skills aus dem skills/ Verzeichnis."""

import importlib
import importlib.util
import json
from pathlib import Path

from backend.tools.base import BaseTool


SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

# Zwischenspeicher der AUSGEFUEHRTEN Skill-Module (Code-Review 2026-10-18).
# Bis dahin legte jeder neue JarvisAgent (jede Delegation, jeder freie
# Sub-Agent, die Agenten je Lauf von AI-Maus/Jira/Short Tracks) einen eigenen
# SkillManager an – und der fuehrte JEDES Skill-Modul per exec_module neu aus,
# synchron im Event-Loop. Bei acht Delegationen je Auftrag achtmal der ganze
# Bestand; modulweite Zustaende (Caches, Locks, Clients) gab es dabei mehrfach,
# zwei Instanzen sahen das Lock der jeweils anderen nicht.
# Schluessel: (Skill, Modulpfad); gueltig, solange mtime+Groesse gleich sind.
# Neu ausgefuehrt wird bei geaenderter Datei oder ``frisch=True`` (Aktivieren,
# Installieren, reload_all). Die Werkzeug-INSTANZEN entstehen weiter je Agent.
_MODULE: dict = {}

# Defaults für fehlende Manifest-Felder
MANIFEST_DEFAULTS = {
    "category": "sonstige",
    "icon": "puzzle",
    "system": False,
    "enabled": True,
    "config_schema": {},
    "knowledge_docs": [],
    "dependencies": [],
    # Lifecycle-Felder: Installation bei Aktivierung, Aufraeumen bei Deinstallation
    "optional_dependencies": [],   # pip-Pakete, die der Skill nutzt, aber nicht erzwingt (schuetzt vor Purge anderer Skills)
    "system_packages": [],         # apt-Pakete (Installation via Root-Broker)
    "purge_packages": [],          # pip-Pakete, die beim Deinstallieren entfernt werden duerfen (leer = dependencies)
    "data_dirs": [],               # Daten/Verzeichnisse (repo-relativ), die beim Deinstallieren geloescht werden koennen
    "caches": [],                  # Cache-Globs (z.B. ~/.cache/huggingface/...), die beim Deinstallieren geloescht werden koennen
    "install_commands": [],        # Zusatzbefehle bei Installation, z.B. npm install ({cmd, cwd, creates})
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

    def load_skill(self, skill_name: str, frisch: bool = False) -> list[BaseTool]:
        """Lädt einen Skill und gibt seine Tools zurück (Modul aus dem Zwischenspeicher,
        ausser ``frisch`` oder die Datei hat sich geaendert)."""
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

        st = module_path.stat()
        schluessel = (skill_name, str(module_path))
        stempel = (st.st_mtime_ns, st.st_size)
        eintrag = _MODULE.get(schluessel)
        if not frisch and eintrag is not None and eintrag[0] == stempel:
            module = eintrag[1]
        else:
            spec = importlib.util.spec_from_file_location(
                f"skills.{skill_name}.{module_name}", str(module_path)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _MODULE[schluessel] = (stempel, module)

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
