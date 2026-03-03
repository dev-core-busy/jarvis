"""
Google OAuth2 Manager für Jarvis.

Verwaltet den OAuth2-Flow und stellt authentifizierte Google-API-Services bereit.

Voraussetzung:
  data/google_auth/credentials.json  – OAuth2-Client-Daten aus Google Cloud Console
  (Vorlage: data/google_auth/credentials.json.example)

Token wird gespeichert in:
  data/google_auth/token.json  – automatisch erneuert bei Ablauf
"""

import json
import os
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
AUTH_DIR     = PROJECT_ROOT / "data" / "google_auth"
CREDS_FILE   = AUTH_DIR / "credentials.json"
TOKEN_FILE   = AUTH_DIR / "token.json"

REDIRECT_URI = f"https://{os.getenv('SERVER_IP', '127.0.0.1')}:8000/api/google/callback"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

_lock = threading.Lock()

# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def credentials_exist() -> bool:
    """Prüft ob credentials.json vorhanden ist."""
    return CREDS_FILE.exists()


def is_authenticated() -> bool:
    """Prüft ob ein gültiges/erneuerbares Token vorliegt."""
    if not TOKEN_FILE.exists():
        return False
    try:
        creds = _load_credentials()
        return creds is not None and (creds.valid or creds.refresh_token is not None)
    except Exception:
        return False


def get_auth_url() -> str:
    """
    Erstellt die OAuth2-Auth-URL.
    Raises FileNotFoundError wenn credentials.json fehlt.
    """
    if not CREDS_FILE.exists():
        raise FileNotFoundError(
            "data/google_auth/credentials.json fehlt. "
            "Bitte nach der Vorlage (credentials.json.example) anlegen."
        )
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(
        str(CREDS_FILE),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return auth_url


def handle_callback(code: str) -> dict:
    """
    Tauscht den Auth-Code gegen Tokens aus und speichert sie.
    Gibt {'ok': True, 'email': '...'} oder {'error': '...'} zurück.
    """
    if not CREDS_FILE.exists():
        return {"error": "credentials.json fehlt"}
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            str(CREDS_FILE),
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI,
        )
        flow.fetch_token(code=code)
        creds = flow.credentials
        _save_token(creds)
        email = _get_email(creds)
        return {"ok": True, "email": email}
    except Exception as e:
        return {"error": str(e)}


def get_service(api_name: str, version: str):
    """
    Gibt einen authentifizierten Google-API-Service zurück.
    Erneuert das Token automatisch falls nötig.
    Raises RuntimeError wenn nicht authentifiziert.
    """
    from googleapiclient.discovery import build
    creds = _load_credentials()
    if creds is None:
        raise RuntimeError("Nicht authentifiziert. Bitte zuerst mit Google verbinden.")
    _maybe_refresh(creds)
    return build(api_name, version, credentials=creds)


def revoke() -> bool:
    """Widerruft den Google-Zugriff und löscht das Token."""
    try:
        if TOKEN_FILE.exists():
            creds = _load_credentials()
            if creds and creds.token:
                import requests as _req
                _req.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": creds.token},
                    headers={"content-type": "application/x-www-form-urlencoded"},
                    timeout=5,
                )
            TOKEN_FILE.unlink(missing_ok=True)
        return True
    except Exception:
        TOKEN_FILE.unlink(missing_ok=True)
        return True


def get_status() -> dict:
    """Gibt den aktuellen Auth-Status zurück."""
    if not credentials_exist():
        return {
            "configured": False,
            "authenticated": False,
            "email": None,
            "message": "credentials.json fehlt – bitte Google Cloud einrichten",
        }
    if not is_authenticated():
        return {
            "configured": True,
            "authenticated": False,
            "email": None,
            "message": "Nicht verbunden",
        }
    try:
        creds = _load_credentials()
        _maybe_refresh(creds)
        email = _get_email(creds)
        return {
            "configured": True,
            "authenticated": True,
            "email": email,
            "message": f"Verbunden als {email}",
        }
    except Exception as e:
        return {
            "configured": True,
            "authenticated": False,
            "email": None,
            "message": f"Fehler: {e}",
        }


# ─── Interne Helfer ────────────────────────────────────────────────────────────

def _load_credentials():
    """Lädt Credentials aus token.json."""
    if not TOKEN_FILE.exists():
        return None
    try:
        from google.oauth2.credentials import Credentials
        with _lock:
            data = json.loads(TOKEN_FILE.read_text())
        return Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes", SCOPES),
        )
    except Exception:
        return None


def _save_token(creds) -> None:
    """Speichert Credentials in token.json."""
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "scopes":        list(creds.scopes or SCOPES),
    }
    with _lock:
        TOKEN_FILE.write_text(json.dumps(data, indent=2))


def _maybe_refresh(creds) -> None:
    """Erneuert das Token falls abgelaufen."""
    if creds and not creds.valid and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        _save_token(creds)


def _get_email(creds) -> str:
    """Holt die E-Mail-Adresse des authentifizierten Nutzers."""
    try:
        from googleapiclient.discovery import build
        service = build("oauth2", "v2", credentials=creds)
        info = service.userinfo().get().execute()
        return info.get("email", "Unbekannt")
    except Exception:
        return "Unbekannt"
