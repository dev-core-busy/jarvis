"""Jarvis Konfiguration – lädt Einstellungen aus .env"""

import os
import json
import uuid
from pathlib import Path
from dotenv import load_dotenv

# .env aus Projektverzeichnis laden
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _write_preserve_owner(path: Path, text: str) -> None:
    """Datei schreiben und dabei den bisherigen Eigentuemer erhalten.

    Wichtig fuer den Root-Broker: laeuft er (als root) z.B. sandbox_setup und
    speichert dabei eine Einstellung, darf settings.json nicht ploetzlich
    root gehoeren – sonst kann das unprivilegierte Backend (jarvis.service,
    User=jarvis) seine eigenen Einstellungen nicht mehr schreiben."""
    st = None
    try:
        if path.exists():
            st = path.stat()
    except Exception:  # noqa: BLE001
        st = None
    path.write_text(text)
    try:
        if st is not None and os.geteuid() == 0 and (st.st_uid != 0 or st.st_gid != 0):
            os.chown(path, st.st_uid, st.st_gid)
    except Exception:  # noqa: BLE001
        pass


# Zulaessige Reasoning-Stufen (Denktiefe). "" = Provider-Standard.
# Bewusst hier dupliziert statt aus backend.llm importiert: llm.py importiert
# config.py, ein Gegenimport waere zirkulaer.
REASONING_EFFORT_VALUES = ("", "off", "low", "medium", "high", "max")


def _valid_effort(value) -> str:
    """Filtert eine Reasoning-Stufe; alles Unbekannte wird zu "" (Provider-Standard)."""
    s = str(value or "").strip().lower()
    return s if s in REASONING_EFFORT_VALUES else ""


# Grenzen fuer die Sampling-Temperature. 2.0 ist die Obergrenze, die alle
# unterstuetzten Provider akzeptieren (OpenAI/vLLM 0..2, Gemini 0..2, Anthropic 0..1 –
# ein zu hoher Wert wird dort vom Server abgelehnt, nicht hier).
TEMPERATURE_MIN, TEMPERATURE_MAX = 0.0, 2.0
# Sonderwert: Parameter gar nicht senden (Provider entscheidet selbst). Nötig für
# aktuelle Claude-Modelle, die temperature mit HTTP 400 ablehnen.
TEMPERATURE_AUTO = "auto"


# Grenzen fuer die Vorhaltezeit erzeugter Dokumente (Tage). Unter 15 Tagen
# verschwinden Dateien, die ein Nutzer im Chat-Verlauf noch braucht; ueber 90
# Tagen ist die Aufbewahrung praktisch keine Begrenzung mehr.
DOCS_RETENTION_MIN, DOCS_RETENTION_MAX = 15, 90
# Sonderwert: dauerhaft behalten (kein Aufraeumen).
DOCS_RETENTION_FOREVER = 0


def _valid_retention(value, fallback: int = 30) -> int:
    """Filtert die Vorhaltezeit: 0 (dauerhaft) oder 15..90 Tage.

    ACHTUNG: Die Pruefung darf NICHT ueber Falsyness laufen (``int(v or 30)``) –
    0 ist ein gueltiger Wert ("dauerhaft") und wuerde dabei still zum Standard.
    Werte zwischen 1 und 14 werden auf das Minimum gehoben, nicht auf 0
    abgerundet: aus einer zu knappen Eingabe darf nicht versehentlich
    "dauerhaft" werden, das waere die Umkehrung der Absicht.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return fallback
    if n <= DOCS_RETENTION_FOREVER:
        return DOCS_RETENTION_FOREVER
    return max(DOCS_RETENTION_MIN, min(n, DOCS_RETENTION_MAX))


def _valid_temperature(value):
    """Filtert einen Temperature-Wert fuer ein Profil.

    Rueckgabe:
      "auto" – Parameter weglassen, der Provider entscheidet (STANDARD)
      float  – dieser Wert, auf 0.0..2.0 begrenzt

    Leere und unbrauchbare Eingaben werden zu "auto": ein Tippfehler im
    Profilformular darf kein Profil unbenutzbar machen, und "auto" ist seit
    2026-07-27 der Standard (vorher wurde daraus der feste Wert 0.2).
    """
    if value is None:
        return TEMPERATURE_AUTO
    if isinstance(value, str):
        s = value.strip().lower()
        if not s or s == TEMPERATURE_AUTO:
            return TEMPERATURE_AUTO
        value = s.replace(",", ".")   # deutsche Dezimalkommas zulassen
    try:
        f = float(value)
    except (TypeError, ValueError):
        return TEMPERATURE_AUTO
    if f != f:                        # NaN
        return TEMPERATURE_AUTO
    return max(TEMPERATURE_MIN, min(f, TEMPERATURE_MAX))


def _clean_profile_str(value) -> str:
    """Raeumt ein technisches Profil-Textfeld auf (api_key, session_key, api_url, model).

    Rand-Leerzeichen und Zeilenumbrueche wandern beim Kopieren aus Mail, Terminal
    oder Passwortmanager mit. Im API-Key macht schon EIN angehaengtes Leerzeichen
    den Authorization-Header ungueltig – httpx/h11 antworten mit
    ``Illegal header value``, was im Profil-Formular wie ein Serverfehler aussieht
    (gemeldet 2026-07-30). In Modellname oder URL fuehrt es zu Aufrufen, die ohne
    erkennbaren Grund scheitern. Steuerzeichen werden entfernt, nicht nur getrimmt:
    ein Zeilenumbruch MITTEN im Wert waere eine Header-Injection.

    Bewusst NICHT auf ``name`` angewandt – ein Anzeigename ist Freitext.
    Die Verwendung normalisiert zusaetzlich (``llm.clean_api_key``), damit auch
    bereits gespeicherte Altwerte funktionieren.
    """
    if not isinstance(value, str):
        return value if value is None else str(value)
    return "".join(c for c in value.strip() if ord(c) >= 32 and ord(c) != 127)


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
            os.chmod(str(_secret_file), 0o600)
            print(f"[SECURITY] SECRET_KEY auto-generiert und in {_secret_file} gespeichert", flush=True)
    AGENT_API_KEY: str = os.getenv("AGENT_API_KEY", "")  # API-Key für externen Agent-Task-Zugriff
    SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "443"))
    VNC_PORT: int = int(os.getenv("VNC_PORT", "5900"))
    WEBSOCKIFY_PORT: int = int(os.getenv("WEBSOCKIFY_PORT", "6080"))
    MAX_AGENT_STEPS: int = int(os.getenv("MAX_AGENT_STEPS", "40"))
    COMMAND_TIMEOUT: int = int(os.getenv("COMMAND_TIMEOUT", "120"))
    # Auto-Neuversuch einer /chat-Anfrage bei LLM-Abbruch/Fehler/leerer Antwort
    # (NICHT bei benutzerausgelöstem Stopp). 0 = deaktiviert.
    AUTO_RETRY_MAX: int = int(os.getenv("AUTO_RETRY_MAX", "2"))
    AUTO_RETRY_DELAY_SEC: float = float(os.getenv("AUTO_RETRY_DELAY_SEC", "2.0"))
    # Im Docker-Modus settings.json im persistenten Data-Volume speichern
    _data_dir = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
    SETTINGS_FILE = _data_dir / "settings.json"

    # Globale Einstellungen (nicht profil-spezifisch)
    TTS_ENABLED: bool = False
    TTS_VOICE: str = ""          # z.B. "de-DE-ConradNeural", "" = Server-Standard
    USE_PHYSICAL_DESKTOP: bool = False
    # Timeout (Sekunden) fuer LLM-Anfragen (read/total). Langsame lokale Modelle
    # brauchen mehr Zeit als Cloud-APIs – daher konfigurierbar (10..1800).
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "180"))
    # Voreinstellung fuer die Denktiefe (Reasoning) aller LLM-Aufrufe.
    # "" = Provider-Standard. Zulaessig: off|low|medium|high|max.
    # Vorrang: pro Chat-Anfrage > Profil > diese globale Vorgabe.
    LLM_REASONING_EFFORT: str = os.getenv("LLM_REASONING_EFFORT", "")
    # Obergrenze fuer die Antwortlaenge OpenAI-kompatibler Aufrufe (256..131072).
    # Wird von llm.py::_llm_max_tokens() gelesen. Bis 2026-07-27 existierte das
    # Feld NICHT – der getattr-Default 8192 galt immer, obwohl der Docstring
    # Konfigurierbarkeit versprach.
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "8192"))
    # Kennung des LLM-Profils, das BILDER erzeugt. "" = wie bisher das Profil des
    # laufenden Agenten.
    #
    # WARUM ES DAS BRAUCHT (gemeldet von ECHT 2026-09-02)
    # ---------------------------------------------------
    # Ein Bildmodell ist kein Gespraechsmodell. Am Haus-Server gemessen: FLUX
    # bekommt `tools` uebergeben, antwortet aber mit `tool_calls: None` und
    # einem Bild im `content` – es kann KEIN Tool-Calling. Haengt eine Rolle auf
    # diesem Profil, ruft ihr Agent `generate_image` also NIE auf; das Bild
    # entsteht am Werkzeug vorbei (aus der Modellantwort geborgen) und mit ihm
    # jede Groessenangabe: 5 von 5 Laeufen 1024x1024, egal was verlangt war.
    # Umgekehrt sagt `generate_image` mit einem Textprofil grundsaetzlich ab.
    # Aus BEIDEN Richtungen folgt dasselbe: das Modell fuer Bilder muss vom
    # Gespraechsmodell getrennt sein.
    #
    # VORRANG: dieses Profil gewinnt, wenn es gesetzt ist – sonst gilt
    # unveraendert das Laufprofil. Das weicht bewusst von "Rolle > global" ab
    # (so gilt es fuer das GESPRAECHSmodell): Bildgenerierung ist keine Frage
    # des Gespraechs, sondern eine Faehigkeit, und das Laufprofil einer Rolle
    # ist in der Praxis genau der Fall, der nicht funktioniert. Wer zwei
    # Bildmodelle je Rolle braucht, braucht ein Rollen-Feld – das gibt es
    # bewusst (noch) nicht.
    IMAGE_PROFILE_ID: str = os.getenv("IMAGE_PROFILE_ID", "")
    # Vorhaltezeit erzeugter Dokumente in data/documents/ (Tage). 0 = dauerhaft
    # behalten, sonst 15..90. Wird von backend/documents.py::retention_days()
    # gelesen; das Loeschen der Datei IST der Widerruf der Capability-URL, denn
    # die URL selbst verfaellt nicht.
    DOCS_RETENTION_DAYS: int = int(os.getenv("JARVIS_DOCS_RETENTION_DAYS", "30"))

    def __init__(self):
        self.profiles: list[dict] = []
        self.active_profile_id: str = ""
        # Benutzerbezogene Profilwahl: {normalisierter_login: profile_id}. Leer =
        # der Benutzer nutzt das globale aktive Profil. Ermoeglicht, dass jeder
        # Benutzer ein eigenes LLM-Profil waehlt, ohne andere zu beeinflussen.
        self.user_profiles: dict[str, str] = {}
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
        up = data.get("user_profiles", {})
        self.user_profiles = dict(up) if isinstance(up, dict) else {}
        self.TTS_ENABLED = data.get("tts_enabled", False)
        self.TTS_VOICE = data.get("tts_voice", "")
        self.USE_PHYSICAL_DESKTOP = data.get("use_physical_desktop", False)
        try:
            self.LLM_TIMEOUT = max(10, min(int(data.get("llm_timeout") or 180), 1800))
        except (TypeError, ValueError):
            self.LLM_TIMEOUT = 180
        self.LLM_REASONING_EFFORT = _valid_effort(data.get("llm_reasoning_effort"))
        try:
            self.LLM_MAX_TOKENS = max(256, min(int(data.get("llm_max_tokens") or 8192), 131072))
        except (TypeError, ValueError):
            self.LLM_MAX_TOKENS = 8192
        # Fehlt der Schluessel, bleibt der ENV-/Klassenwert stehen (gleiche
        # Begruendung wie bei docs_retention_days).
        if "image_profile_id" in data:
            self.IMAGE_PROFILE_ID = str(data.get("image_profile_id") or "").strip()
        # Vorhaltezeit: fehlt der Schluessel, bleibt der ENV-/Klassenwert stehen –
        # NICHT auf 30 zurueckfallen, sonst ueberschreibt ein Laden ohne den
        # Schluessel eine bewusst per ENV gesetzte Vorgabe.
        if "docs_retention_days" in data:
            self.DOCS_RETENTION_DAYS = _valid_retention(
                data.get("docs_retention_days"), self.DOCS_RETENTION_DAYS)
        self._skill_states = data.get("skills", {})
        self._mcp_servers = data.get("mcp_servers", [])
        # AGENT_API_KEY: aus settings.json laden, ENV hat Vorrang
        if not os.getenv("AGENT_API_KEY") and data.get("agent_api_key"):
            self.AGENT_API_KEY = data["agent_api_key"]

        # Migration 2026-07-27: "auto" ist der neue Standard fuer temperature.
        # Bestehende Profile haben das Feld gar nicht oder leer – beides wird auf
        # "auto" gesetzt und EINMAL zurueckgeschrieben, damit die Oberflaeche den
        # tatsaechlich wirksamen Wert anzeigt. Ein bereits gesetzter Zahlenwert
        # bleibt unangetastet.
        _migrated = 0
        for p in self.profiles:
            if not isinstance(p, dict):
                continue
            if p.get("temperature", "") in ("", None):
                p["temperature"] = TEMPERATURE_AUTO
                _migrated += 1

        # Sicherstellen, dass active_profile_id gültig ist
        if self.profiles and not any(p["id"] == self.active_profile_id for p in self.profiles):
            self.active_profile_id = self.profiles[0]["id"]
        # Verwaiste Benutzer-Profilwahlen (geloeschte Profile) entfernen
        valid_ids = {p["id"] for p in self.profiles}
        self.user_profiles = {u: pid for u, pid in self.user_profiles.items() if pid in valid_ids}

        # Migration erst NACH allen Aufraeumschritten zurueckschreiben, und nur
        # wenn wirklich etwas geaendert wurde (kein Schreiben bei jedem Start).
        if _migrated:
            print(f"[config] temperature-Migration: {_migrated} Profil(e) auf "
                  f"'{TEMPERATURE_AUTO}' gesetzt", flush=True)
            try:
                self._save_to_file()
            except Exception as e:  # noqa: BLE001
                # Nicht schreibbar (z.B. Rechte) darf den Start nicht verhindern –
                # die Werte gelten dann nur fuer diesen Lauf.
                print(f"[config] temperature-Migration nicht persistiert: {e}", flush=True)

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
        """Speichert alles im v2-Format. Bestehende 'extra'-Section wird erhalten."""
        # Bestehende extra-Section laden (AD-Config, etc.)
        existing_extra = {}
        try:
            if self.SETTINGS_FILE.exists():
                existing = json.loads(self.SETTINGS_FILE.read_text())
                existing_extra = existing.get("extra", {})
        except Exception:
            pass

        data = {
            "version": 2,
            "active_profile_id": self.active_profile_id,
            "user_profiles": self.user_profiles,
            "tts_enabled": self.TTS_ENABLED,
            "tts_voice": self.TTS_VOICE,
            "use_physical_desktop": self.USE_PHYSICAL_DESKTOP,
            "llm_timeout": self.LLM_TIMEOUT,
            "llm_reasoning_effort": self.LLM_REASONING_EFFORT,
            "llm_max_tokens": self.LLM_MAX_TOKENS,
            "image_profile_id": self.IMAGE_PROFILE_ID,
            "docs_retention_days": self.DOCS_RETENTION_DAYS,
            "agent_api_key": self.AGENT_API_KEY,
            "profiles": self.profiles,
            "skills": self._skill_states,
            "mcp_servers": self._mcp_servers,
        }
        if existing_extra:
            data["extra"] = existing_extra
        _write_preserve_owner(self.SETTINGS_FILE, json.dumps(data, indent=4))

    def save_global_settings(self, settings: dict):
        """Speichert globale Einstellungen (TTS, Desktop, Agent-API-Key etc.)."""
        if "tts_enabled" in settings:
            self.TTS_ENABLED = settings["tts_enabled"]
        if "tts_voice" in settings:
            self.TTS_VOICE = settings["tts_voice"]
        if "use_physical_desktop" in settings:
            self.USE_PHYSICAL_DESKTOP = settings["use_physical_desktop"]
        if "llm_timeout" in settings:
            try:
                self.LLM_TIMEOUT = max(10, min(int(settings["llm_timeout"]), 1800))
            except (TypeError, ValueError):
                pass
        if "llm_reasoning_effort" in settings:
            self.LLM_REASONING_EFFORT = _valid_effort(settings["llm_reasoning_effort"])
        if "llm_max_tokens" in settings:
            try:
                self.LLM_MAX_TOKENS = max(256, min(int(settings["llm_max_tokens"]), 131072))
            except (TypeError, ValueError):
                pass
        if "image_profile_id" in settings:
            # Eine unbekannte Kennung wird ABGEWIESEN, nicht gespeichert: sonst
            # zeigt die Einstellung ins Leere und die Bildgenerierung sagt ab,
            # ohne dass jemand den Zusammenhang sieht. "" = abschalten.
            _neu = str(settings["image_profile_id"] or "").strip()
            if not _neu or any(p.get("id") == _neu for p in (self.profiles or [])):
                self.IMAGE_PROFILE_ID = _neu
        if "docs_retention_days" in settings:
            # Bei Muell den ALTEN Wert behalten (Fallback = aktueller Stand), nicht
            # stillschweigend auf 30 zuruecksetzen.
            self.DOCS_RETENTION_DAYS = _valid_retention(
                settings["docs_retention_days"], self.DOCS_RETENTION_DAYS)
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
            _write_preserve_owner(self.SETTINGS_FILE, json.dumps(data, indent=4))
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
            # Duerfen Netzwerk-/Domain-Benutzer die Werkzeuge dieses Servers
            # aufrufen? Vorgabe AUS (fail-closed): der Server arbeitet mit SEINEN
            # hinterlegten Zugangsdaten, die Rechte des Anfragenden im Zielsystem
            # spielen dabei keine Rolle. Nur ein ausdrueckliches True zaehlt –
            # ein "ja"/1 aus einer handgeschriebenen settings.json ist keine
            # bewusste Admin-Entscheidung.
            "allow_network_users": data.get("allow_network_users") is True,
            # stdio-Server in einem Namespace ohne Sicht auf /opt und /home
            # starten (bwrap). Vorgabe AN – abschalten ist die bewusste Ausnahme,
            # deshalb `is not False` und nicht `is True`.
            "sandbox": data.get("sandbox") is not False,
            # Zusaetzliche, NUR LESBARE Pfade fuer den isolierten Prozess
            # (z.B. das Datenverzeichnis eines Dateisystem-Servers).
            "sandbox_paths": list(data.get("sandbox_paths") or []),
        }
        self._mcp_servers.append(server)
        self._save_to_file()
        return server

    def update_mcp_server(self, server_id: str, data: dict) -> dict | None:
        """Aktualisiert einen MCP-Server."""
        for srv in self._mcp_servers:
            if srv["id"] == server_id:
                # ACHTUNG: neues Feld = ZWEI Stellen (add_mcp_server UND diese
                # Whitelist). Fehlt eines, wird der Wert still verworfen.
                for key in ["name", "enabled", "transport", "command", "args", "url", "env"]:
                    if key in data:
                        srv[key] = data[key]
                if "allow_network_users" in data:
                    srv["allow_network_users"] = data["allow_network_users"] is True
                if "sandbox" in data:
                    srv["sandbox"] = data["sandbox"] is not False
                if "sandbox_paths" in data:
                    srv["sandbox_paths"] = list(data["sandbox_paths"] or [])
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
            # Rand-Leerzeichen raus: ein mitkopiertes Leerzeichen im Key macht den
            # Authorization-Header ungueltig ("Illegal header value"), eines in
            # Modell/URL laesst den Aufruf ohne erkennbaren Grund scheitern. Die
            # Verwendung normalisiert zusaetzlich (llm.clean_api_key) – das hier
            # ist die Wurzel, damit nichts Schmutziges erst gespeichert wird.
            "model": _clean_profile_str(data.get("model", "")),
            "api_url": _clean_profile_str(data.get("api_url", default_url)),
            "api_key": _clean_profile_str(data.get("api_key", "")),
            "auth_method": data.get("auth_method", "api_key"),
            "session_key": _clean_profile_str(data.get("session_key", "")),
            # Denktiefe dieses Profils ("" = Provider-Standard). Eine einzelne
            # Chat-Anfrage darf den Wert ueberschreiben (reasoning_effort im Task).
            "reasoning_effort": _valid_effort(data.get("reasoning_effort")),
            # Sampling-Temperature. Standard "auto" = Parameter nicht senden,
            # der Anbieter entscheidet. Alternativ eine Zahl 0.0..2.0.
            "temperature": _valid_temperature(data.get("temperature", TEMPERATURE_AUTO)),
            # Prompt-basiertes Tool-Calling. Stand bis 2026-07-27 in KEINER
            # Persistenz-Liste – der Schalter im Profilformular wirkte deshalb nie.
            "prompt_tool_calling": bool(data.get("prompt_tool_calling", False)),
            # Pro-Profil-Berechtigung (leer = alle duerfen nutzen); analog Wissensgruppen.
            "allowed_users": data.get("allowed_users", ""),
            "allowed_group": data.get("allowed_group", ""),
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
                for key in ["name", "provider", "model", "api_url", "api_key", "auth_method",
                            "session_key", "reasoning_effort", "temperature",
                            "prompt_tool_calling", "allowed_users", "allowed_group"]:
                    if key in data:
                        val = data[key]
                        # Maskierte Keys (***...) nicht überschreiben – Wert unverändert lassen
                        if key in ("api_key", "session_key") and isinstance(val, str) and val.startswith("***"):
                            continue
                        if key == "reasoning_effort":
                            val = _valid_effort(val)
                        elif key == "temperature":
                            val = _valid_temperature(val)
                        elif key == "prompt_tool_calling":
                            val = bool(val)
                        elif key in ("api_key", "session_key", "api_url", "model"):
                            val = _clean_profile_str(val)   # siehe create_profile
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
        # Benutzer, die genau dieses Profil gewaehlt hatten, auf Default zuruecksetzen
        self.user_profiles = {u: pid for u, pid in self.user_profiles.items() if pid != profile_id}
        self._save_to_file()
        return True

    def activate_profile(self, profile_id: str) -> bool:
        """Setzt ein Profil global aktiv (Admin-Default / Fallback)."""
        if any(p["id"] == profile_id for p in self.profiles):
            self.active_profile_id = profile_id
            self._save_to_file()
            return True
        return False

    # ─── Benutzerbezogene Profilwahl ───────────────────────────────
    @staticmethod
    def _norm_user(username: str) -> str:
        """Login auf einen stabilen Schluessel normalisieren (Domain/Case egal)."""
        u = (username or "").strip()
        if "\\" in u:
            u = u.split("\\")[-1]
        if "@" in u:
            u = u.split("@")[0]
        return u.lower()

    def active_profile_id_for_user(self, username: str) -> str:
        """Profil-ID, die DIESER Benutzer nutzt (eigene Wahl, sonst global aktiv)."""
        pid = self.user_profiles.get(self._norm_user(username))
        if pid and any(p["id"] == pid for p in self.profiles):
            return pid
        return self.active_profile_id

    def profile_for_user(self, username: str) -> dict | None:
        """Effektives Profil-Dict fuer diesen Benutzer (Fallback: globales aktives)."""
        pid = self.active_profile_id_for_user(username)
        for p in self.profiles:
            if p["id"] == pid:
                return p
        return self.active_profile

    def set_user_profile(self, username: str, profile_id: str) -> bool:
        """Merkt die Profilwahl eines Benutzers (beeinflusst nur ihn selbst)."""
        if not any(p["id"] == profile_id for p in self.profiles):
            return False
        self.user_profiles[self._norm_user(username)] = profile_id
        self._save_to_file()
        return True

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
