"""Jarvis Konfiguration – lädt Einstellungen aus .env"""

import os
import json
import uuid
from pathlib import Path
from dotenv import load_dotenv

# .env aus Projektverzeichnis laden
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    """Zentrale Konfiguration für Jarvis mit Profil-Verwaltung."""

    # Defaults
    DEFAULT_PROVIDERS = {
        "google": {
            "url": "https://api.google.com/genai/v1",
            "models": [
                "gemini-2.5-pro-preview-05-06",
                "gemini-2.5-flash",
                "gemini-2.0-flash",
                "gemini-2.0-flash-lite",
                "gemini-1.5-pro",
                "gemini-1.5-flash",
            ],
        },
        "openrouter": {
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "models": [
                "google/gemini-2.0-flash-001",
                "google/gemini-2.0-flash-lite-001",
                "google/gemini-pro-1.5",
                "anthropic/claude-3.5-sonnet",
                "meta-llama/llama-3.1-405b",
            ],
        },
        "anthropic": {
            "url": "https://api.anthropic.com/v1/messages",
            "models": [
                "claude-opus-4-5",
                "claude-sonnet-4-5",
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ],
        },
        "openai_compatible": {
            "url": "http://localhost:11434/v1/chat/completions",
            "models": [],
        },
    }

    # Sicherheit & Server
    JARVIS_PASSWORD: str = os.getenv("JARVIS_PASSWORD", "jarvis")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    if not SECRET_KEY:
        # Auto-generieren und in Datei persistieren
        _secret_file = Path(__file__).parent.parent / "data" / ".secret_key"
        if _secret_file.exists():
            SECRET_KEY = _secret_file.read_text().strip()
        if not SECRET_KEY:
            import secrets as _secrets
            SECRET_KEY = _secrets.token_hex(32)
            _secret_file.parent.mkdir(parents=True, exist_ok=True)
            _secret_file.write_text(SECRET_KEY)
            print(f"[SECURITY] SECRET_KEY auto-generiert und in {_secret_file} gespeichert", flush=True)
    AGENT_API_KEY: str = os.getenv("AGENT_API_KEY", "")  # API-Key für externen Agent-Task-Zugriff
    SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "443"))
    VNC_PORT: int = int(os.getenv("VNC_PORT", "5900"))
    WEBSOCKIFY_PORT: int = int(os.getenv("WEBSOCKIFY_PORT", "6080"))
    MAX_AGENT_STEPS: int = int(os.getenv("MAX_AGENT_STEPS", "50"))
    COMMAND_TIMEOUT: int = int(os.getenv("COMMAND_TIMEOUT", "120"))
    # Im Docker-Modus settings.json im persistenten Data-Volume speichern
    _data_dir = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
    SETTINGS_FILE = _data_dir / "settings.json"

    # Globale Einstellungen (nicht profil-spezifisch)
    TTS_ENABLED: bool = False
    USE_PHYSICAL_DESKTOP: bool = False

    def __init__(self):
        self.profiles: list[dict] = []
        self.active_profile_id: str = ""
        self._skill_states: dict[str, dict] = {}
        self._mcp_servers: list[dict] = []

        # Profile aus ENV-Variablen initialisieren
        self._init_profiles_from_env()

        # settings.json laden (überschreibt ggf. ENV-Profile)
        self.load_settings()

        # Fallback: mindestens ein Standard-Profil
        if not self.profiles:
            self._create_default_profile()

    def _init_profiles_from_env(self):
        """Erstellt initiale Profile aus Umgebungsvariablen."""
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_key:
            self.profiles.append({
                "id": str(uuid.uuid4()),
                "name": "Google Gemini",
                "provider": "google",
                "model": self.DEFAULT_PROVIDERS["google"]["models"][0],
                "api_url": self.DEFAULT_PROVIDERS["google"]["url"],
                "api_key": gemini_key,
                "auth_method": "api_key",
                "session_key": "",
            })

        or_key = os.getenv("OPENROUTER_API_KEY", "")
        if or_key:
            self.profiles.append({
                "id": str(uuid.uuid4()),
                "name": "OpenRouter",
                "provider": "openrouter",
                "model": self.DEFAULT_PROVIDERS["openrouter"]["models"][0],
                "api_url": self.DEFAULT_PROVIDERS["openrouter"]["url"],
                "api_key": or_key,
                "auth_method": "api_key",
                "session_key": "",
            })

        ant_key = os.getenv("ANTHROPIC_API_KEY", "")
        session_key = os.getenv("ANTHROPIC_SESSION_KEY", "")
        if ant_key or session_key:
            self.profiles.append({
                "id": str(uuid.uuid4()),
                "name": "Anthropic Claude",
                "provider": "anthropic",
                "model": self.DEFAULT_PROVIDERS["anthropic"]["models"][0],
                "api_url": self.DEFAULT_PROVIDERS["anthropic"]["url"],
                "api_key": ant_key,
                "auth_method": "session" if session_key and not ant_key else "api_key",
                "session_key": session_key,
            })

        # Erstes Profil als aktiv setzen
        if self.profiles:
            self.active_profile_id = self.profiles[0]["id"]

    def _create_default_profile(self):
        """Erstellt ein leeres Standard-Profil als Fallback."""
        profile = {
            "id": str(uuid.uuid4()),
            "name": "Standard",
            "provider": "google",
            "model": self.DEFAULT_PROVIDERS["google"]["models"][0],
            "api_url": self.DEFAULT_PROVIDERS["google"]["url"],
            "api_key": "",
            "auth_method": "api_key",
            "session_key": "",
        }
        self.profiles.append(profile)
        self.active_profile_id = profile["id"]

    # ─── Laden / Speichern ─────────────────────────────────────────

    def load_settings(self):
        """Lädt Einstellungen aus settings.json mit Auto-Migration."""
        if not self.SETTINGS_FILE.exists():
            return
        try:
            data = json.loads(self.SETTINGS_FILE.read_text())
            if data.get("version") == 2:
                self._load_v2(data)
            else:
                self._migrate_v1_to_v2(data)
        except Exception as e:
            print(f"Fehler beim Laden der Einstellungen: {e}")

    def _load_v2(self, data: dict):
        """Lädt das v2-Format mit Profilen."""
        self.profiles = data.get("profiles", [])
        self.active_profile_id = data.get("active_profile_id", "")
        self.TTS_ENABLED = data.get("tts_enabled", False)
        self.USE_PHYSICAL_DESKTOP = data.get("use_physical_desktop", False)
        self._skill_states = data.get("skills", {})
        self._mcp_servers = data.get("mcp_servers", [])
        # AGENT_API_KEY: aus settings.json laden, ENV hat Vorrang
        if not os.getenv("AGENT_API_KEY") and data.get("agent_api_key"):
            self.AGENT_API_KEY = data["agent_api_key"]

        # Sicherstellen, dass active_profile_id gültig ist
        if self.profiles and not any(p["id"] == self.active_profile_id for p in self.profiles):
            self.active_profile_id = self.profiles[0]["id"]

    def _migrate_v1_to_v2(self, data: dict):
        """Migriert settings.json v1 (flach) nach v2 (Profile)."""
        self.TTS_ENABLED = data.get("tts_enabled", False)
        self.USE_PHYSICAL_DESKTOP = data.get("use_physical_desktop", False)

        old_provider = data.get("llm_provider", "google")
        model_keys = data.get("model_keys", {})
        api_urls = data.get("api_urls", {})

        provider_configs = {
            "google": {"model_key": "google_model", "name": "Google Gemini"},
            "openrouter": {"model_key": "openrouter_model", "name": "OpenRouter"},
            "anthropic": {"model_key": "anthropic_model", "name": "Anthropic Claude"},
        }

        self.profiles = []
        for prov, cfg in provider_configs.items():
            default_model = self.DEFAULT_PROVIDERS[prov]["models"][0]
            model = data.get(cfg["model_key"], default_model)
            key = model_keys.get(model, "")
            url = api_urls.get(prov, self.DEFAULT_PROVIDERS[prov]["url"])

            if key or prov == old_provider:
                profile = {
                    "id": str(uuid.uuid4()),
                    "name": cfg["name"],
                    "provider": prov,
                    "model": model,
                    "api_url": url,
                    "api_key": key,
                    "auth_method": data.get("anthropic_auth_method", "api_key") if prov == "anthropic" else "api_key",
                    "session_key": data.get("anthropic_session_key", "") if prov == "anthropic" else "",
                }
                self.profiles.append(profile)
                if prov == old_provider:
                    self.active_profile_id = profile["id"]

        if not self.active_profile_id and self.profiles:
            self.active_profile_id = self.profiles[0]["id"]

        self._save_to_file()
        print("Settings von v1 nach v2 migriert.")

    def _save_to_file(self):
        """Speichert alles im v2-Format."""
        data = {
            "version": 2,
            "active_profile_id": self.active_profile_id,
            "tts_enabled": self.TTS_ENABLED,
            "use_physical_desktop": self.USE_PHYSICAL_DESKTOP,
            "agent_api_key": self.AGENT_API_KEY,
            "profiles": self.profiles,
            "skills": self._skill_states,
            "mcp_servers": self._mcp_servers,
        }
        self.SETTINGS_FILE.write_text(json.dumps(data, indent=4))

    def save_global_settings(self, settings: dict):
        """Speichert globale Einstellungen (TTS, Desktop, Agent-API-Key etc.)."""
        if "tts_enabled" in settings:
            self.TTS_ENABLED = settings["tts_enabled"]
        if "use_physical_desktop" in settings:
            self.USE_PHYSICAL_DESKTOP = settings["use_physical_desktop"]
        if "agent_api_key" in settings:
            self.AGENT_API_KEY = settings["agent_api_key"]
        self._save_to_file()

    # ─── Generische Key-Value-Einstellungen ────────────────────────────

    def get_setting(self, key: str, default=None):
        """Liest einen generischen Einstellungswert aus settings.json."""
        try:
            if self.SETTINGS_FILE.exists():
                data = json.loads(self.SETTINGS_FILE.read_text())
                return data.get("extra", {}).get(key, default)
        except Exception:
            pass
        return default

    def save_setting(self, key: str, value):
        """Speichert einen generischen Einstellungswert in settings.json."""
        try:
            data = {}
            if self.SETTINGS_FILE.exists():
                data = json.loads(self.SETTINGS_FILE.read_text())
            if "extra" not in data:
                data["extra"] = {}
            data["extra"][key] = value
            self.SETTINGS_FILE.write_text(json.dumps(data, indent=4))
        except Exception as e:
            print(f"[Config] save_setting Fehler: {e}", flush=True)

    # ─── Skills-Verwaltung ─────────────────────────────────────────

    def get_skill_states(self) -> dict:
        """Gibt alle Skill-Zustände zurück."""
        return self._skill_states

    def save_skill_state(self, name: str, state: dict):
        """Speichert den Zustand eines einzelnen Skills."""
        if name not in self._skill_states:
            self._skill_states[name] = {}
        self._skill_states[name].update(state)
        self._save_to_file()

    def remove_skill_state(self, name: str):
        """Entfernt den Zustand eines Skills."""
        self._skill_states.pop(name, None)
        self._save_to_file()

    # ─── MCP-Server-Verwaltung ───────────────────────────────────────

    def get_mcp_servers(self) -> list[dict]:
        """Gibt alle MCP-Server zurueck."""
        return self._mcp_servers

    def add_mcp_server(self, data: dict) -> dict:
        """Fuegt einen neuen MCP-Server hinzu."""
        server = {
            "id": str(uuid.uuid4()),
            "name": data.get("name", "Neuer Server"),
            "enabled": data.get("enabled", True),
            "transport": data.get("transport", "stdio"),
            "command": data.get("command", ""),
            "args": data.get("args", []),
            "url": data.get("url", ""),
            "env": data.get("env", {}),
        }
        self._mcp_servers.append(server)
        self._save_to_file()
        return server

    def update_mcp_server(self, server_id: str, data: dict) -> dict | None:
        """Aktualisiert einen MCP-Server."""
        for srv in self._mcp_servers:
            if srv["id"] == server_id:
                for key in ["name", "enabled", "transport", "command", "args", "url", "env"]:
                    if key in data:
                        srv[key] = data[key]
                self._save_to_file()
                return srv
        return None

    def remove_mcp_server(self, server_id: str) -> bool:
        """Entfernt einen MCP-Server."""
        before = len(self._mcp_servers)
        self._mcp_servers = [s for s in self._mcp_servers if s["id"] != server_id]
        if len(self._mcp_servers) < before:
            self._save_to_file()
            return True
        return False

    def toggle_mcp_server(self, server_id: str, enabled: bool) -> bool:
        """Aktiviert/deaktiviert einen MCP-Server."""
        for srv in self._mcp_servers:
            if srv["id"] == server_id:
                srv["enabled"] = enabled
                self._save_to_file()
                return True
        return False

    # ─── Profil-CRUD ───────────────────────────────────────────────

    def create_profile(self, data: dict) -> dict:
        """Erstellt ein neues Profil."""
        provider = data.get("provider", "google")
        default_url = self.DEFAULT_PROVIDERS.get(provider, {}).get("url", "")
        profile = {
            "id": str(uuid.uuid4()),
            "name": data.get("name", "Neues Profil"),
            "provider": provider,
            "model": data.get("model", ""),
            "api_url": data.get("api_url", default_url),
            "api_key": data.get("api_key", ""),
            "auth_method": data.get("auth_method", "api_key"),
            "session_key": data.get("session_key", ""),
        }
        self.profiles.append(profile)
        if not self.active_profile_id:
            self.active_profile_id = profile["id"]
        self._save_to_file()
        return profile

    def update_profile(self, profile_id: str, data: dict) -> dict | None:
        """Aktualisiert ein bestehendes Profil."""
        for p in self.profiles:
            if p["id"] == profile_id:
                for key in ["name", "provider", "model", "api_url", "api_key", "auth_method", "session_key"]:
                    if key in data:
                        val = data[key]
                        # Maskierte Keys (***...) nicht überschreiben – Wert unverändert lassen
                        if key in ("api_key", "session_key") and isinstance(val, str) and val.startswith("***"):
                            continue
                        p[key] = val
                self._save_to_file()
                return p
        return None

    def delete_profile(self, profile_id: str) -> bool:
        """Löscht ein Profil. Mindestens eines muss bestehen bleiben."""
        if len(self.profiles) <= 1:
            return False
        self.profiles = [p for p in self.profiles if p["id"] != profile_id]
        if self.active_profile_id == profile_id:
            self.active_profile_id = self.profiles[0]["id"]
        self._save_to_file()
        return True

    def activate_profile(self, profile_id: str) -> bool:
        """Setzt ein Profil als aktiv."""
        if any(p["id"] == profile_id for p in self.profiles):
            self.active_profile_id = profile_id
            self._save_to_file()
            return True
        return False

    # ─── Properties (Fassade für agent.py) ─────────────────────────

    @property
    def active_profile(self) -> dict | None:
        """Gibt das aktuell aktive Profil zurück."""
        for p in self.profiles:
            if p["id"] == self.active_profile_id:
                return p
        return self.profiles[0] if self.profiles else None

    @property
    def LLM_PROVIDER(self) -> str:
        p = self.active_profile
        return p.get("provider", "google") if p else "google"

    @property
    def current_model(self) -> str:
        p = self.active_profile
        return p.get("model", "") if p else ""

    @property
    def current_api_key(self) -> str:
        p = self.active_profile
        return p.get("api_key", "") if p else ""

    @property
    def current_api_url(self) -> str:
        p = self.active_profile
        return p.get("api_url", "") if p else ""

    @property
    def current_auth_method(self) -> str:
        p = self.active_profile
        return p.get("auth_method", "api_key") if p else "api_key"

    @property
    def current_session_key(self) -> str:
        p = self.active_profile
        return p.get("session_key", "") if p else ""

    @property
    def current_prompt_tool_calling(self) -> bool:
        p = self.active_profile
        return bool(p.get("prompt_tool_calling", False)) if p else False

    def validate(self) -> list[str]:
        """Prüft ob das aktive Profil vollständig konfiguriert ist."""
        errors = []
        p = self.active_profile
        if not p:
            errors.append("Kein Profil konfiguriert.")
            return errors
        if p["provider"] == "anthropic" and p.get("auth_method") == "session":
            if not p.get("session_key"):
                errors.append(f"Anthropic Session-Key fehlt im Profil '{p['name']}'.")
        elif p["provider"] != "openai_compatible":
            if not p.get("api_key"):
                errors.append(f"API Key fehlt im Profil '{p['name']}'.")
        return errors


config = Config()
