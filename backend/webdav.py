"""WebDAV-Server fuer die Jarvis Knowledge Base.

Stellt Knowledge-Ordner per WebDAV ueber den bestehenden Port 443 bereit.
Nutzung: Windows/Mac/Linux Dateimanager koennen sich verbinden.
"""

import logging
from pathlib import Path

from backend.config import config

_log = logging.getLogger("jarvis.webdav")

PROJECT_ROOT = Path(__file__).parent.parent


def _get_webdav_config() -> dict:
    """Liest WebDAV-Konfiguration aus settings.json."""
    try:
        states = config.get_skill_states()
        return states.get("knowledge", {}).get("config", {}).get("webdav", {})
    except Exception:
        return {}


def is_webdav_enabled() -> bool:
    return _get_webdav_config().get("enabled", False)


def get_webdav_app():
    """Erstellt die WebDAV WSGI-App (gemountet unter /webdav/).

    Returns None wenn WebDAV deaktiviert oder wsgidav nicht installiert ist.
    """
    cfg = _get_webdav_config()
    if not cfg.get("enabled", False):
        return None

    try:
        from wsgidav.wsgidav_app import WsgiDAVApp
    except ImportError:
        _log.warning("wsgidav nicht installiert – WebDAV deaktiviert")
        return None

    # Knowledge-Ordner als WebDAV-Shares
    from backend.tools.knowledge import _get_folders
    folders = _get_folders()

    provider_mapping = {}
    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)
        try:
            share_name = str(folder.relative_to(PROJECT_ROOT)).replace("/", "_")
        except ValueError:
            share_name = folder.name
        provider_mapping[f"/{share_name}"] = str(folder)

    if not provider_mapping:
        return None

    # Credentials (Default: Jarvis-Login)
    username = cfg.get("username", "jarvis")
    password = cfg.get("password", "jarvis")

    dav_config = {
        "provider_mapping": provider_mapping,
        "verbose": 0,
        "logging": {"enable": False},
        "http_authenticator": {
            "domain_controller": None,
            "accept_basic": True,
            "accept_digest": False,
            "default_to_digest": False,
        },
        "simple_dc": {
            "user_mapping": {
                "*": {username: {"password": password}},
            },
        },
    }

    try:
        dav_app = WsgiDAVApp(dav_config)
        _log.info(f"WebDAV-Server konfiguriert: {list(provider_mapping.keys())}")
        return dav_app
    except Exception as e:
        _log.error(f"WebDAV-Initialisierung fehlgeschlagen: {e}")
        return None
