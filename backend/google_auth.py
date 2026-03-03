"""Google OAuth2 – Device Flow Authentifizierung für Jarvis.

Workflow:
  1. POST /api/google/device-start → gibt user_code + verification_url zurück
  2. Nutzer geht zu verification_url (google.com/device) und gibt user_code ein
  3. Backend pollt Google im Hintergrund
  4. GET /api/google/device-status → 'pending' | 'authorized' | 'expired' | 'error'
  5. Bei 'authorized' ist Token gespeichert und Google verbunden
"""

import json
import threading
import time
from pathlib import Path
from typing import Optional

import requests

# ─── Konfiguration ────────────────────────────────────────────────────

# OAuth2-Client-Credentials aus .env (GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET)
# Typ: "TV und Geräte mit eingeschränkter Eingabe" in Google Cloud Console
# → Einmalig vom Jarvis-Entwickler erstellen; alle Installationen teilen diese ID
from backend.config import config as _cfg
import os as _os

GOOGLE_CLIENT_ID     = _os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = _os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")

GOOGLE_SCOPES = " ".join([
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
])

TOKEN_PATH = Path(__file__).parent.parent / "data" / "google_auth" / "token.json"

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL       = "https://oauth2.googleapis.com/token"
USERINFO_URL    = "https://www.googleapis.com/oauth2/v2/userinfo"
REVOKE_URL      = "https://oauth2.googleapis.com/revoke"

# ─── Device-Flow-State (im Speicher) ──────────────────────────────────

_state: dict = {
    "status": "idle",        # idle | pending | authorized | expired | error
    "user_code": "",
    "verification_url": "",
    "expires_at": 0.0,
    "message": "",
}
_state_lock = threading.Lock()
_poll_thread: Optional[threading.Thread] = None


# ─── Öffentliche Funktionen ────────────────────────────────────────────

def is_configured() -> bool:
    """Prüft ob Client-ID und Secret in der .env hinterlegt sind."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def get_status() -> dict:
    """Gibt aktuellen Auth-Status zurück."""
    token = _load_token()
    if token:
        email = token.get("email", "")
        return {"configured": is_configured(), "authenticated": True, "email": email}
    with _state_lock:
        flow_status = _state["status"]
    return {
        "configured": is_configured(),
        "authenticated": False,
        "flow_status": flow_status,
    }


def start_device_flow() -> dict:
    """Startet den Device Flow und gibt user_code + verification_url zurück."""
    global _poll_thread

    if not is_configured():
        return {"error": "GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET nicht konfiguriert"}

    try:
        resp = requests.post(DEVICE_CODE_URL, data={
            "client_id": GOOGLE_CLIENT_ID,
            "scope": GOOGLE_SCOPES,
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": f"Google-Anfrage fehlgeschlagen: {e}"}

    device_code      = data.get("device_code", "")
    user_code        = data.get("user_code", "")
    verification_url = data.get("verification_url", "https://www.google.com/device")
    expires_in       = int(data.get("expires_in", 1800))
    interval         = int(data.get("interval", 5))

    with _state_lock:
        _state["status"]           = "pending"
        _state["user_code"]        = user_code
        _state["verification_url"] = verification_url
        _state["expires_at"]       = time.time() + expires_in
        _state["message"]          = ""

    # Hintergrund-Thread für Token-Polling starten
    if _poll_thread and _poll_thread.is_alive():
        pass  # Bereits läuft
    else:
        _poll_thread = threading.Thread(
            target=_poll_for_token,
            args=(device_code, interval, expires_in),
            daemon=True,
        )
        _poll_thread.start()

    return {
        "user_code":        user_code,
        "verification_url": verification_url,
        "expires_in":       expires_in,
    }


def get_flow_status() -> dict:
    """Gibt Status des laufenden Device Flows zurück."""
    with _state_lock:
        return {
            "status":           _state["status"],
            "user_code":        _state["user_code"],
            "verification_url": _state["verification_url"],
            "expires_in_sec":   max(0, int(_state["expires_at"] - time.time())),
            "message":          _state["message"],
        }


def revoke() -> bool:
    """Widerruft das gespeicherte Token und löscht es."""
    token = _load_token()
    if not token:
        return False
    access_token = token.get("access_token", "")
    if access_token:
        try:
            requests.post(REVOKE_URL, params={"token": access_token}, timeout=5)
        except Exception:
            pass  # Lokal sowieso löschen
    _delete_token()
    with _state_lock:
        _state["status"]    = "idle"
        _state["user_code"] = ""
    return True


def get_credentials():
    """Gibt google.oauth2.credentials.Credentials zurück (für API-Calls)."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token = _load_token()
    if not token:
        return None

    creds = Credentials(
        token         = token.get("access_token"),
        refresh_token = token.get("refresh_token"),
        token_uri     = TOKEN_URL,
        client_id     = GOOGLE_CLIENT_ID,
        client_secret = GOOGLE_CLIENT_SECRET,
        scopes        = GOOGLE_SCOPES.split(),
    )
    # Token ggf. auffrischen
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token_from_creds(creds, token.get("email", ""))
        except Exception:
            return None
    return creds


# ─── Interne Funktionen ────────────────────────────────────────────────

def _poll_for_token(device_code: str, interval: int, expires_in: int):
    """Pollt Google bis Token erhalten oder abgelaufen."""
    deadline = time.time() + expires_in

    while time.time() < deadline:
        time.sleep(interval)

        try:
            resp = requests.post(TOKEN_URL, data={
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "device_code":   device_code,
                "grant_type":    "urn:ietf:params:oauth:grant-type:device_code",
            }, timeout=10)
            data = resp.json()
        except Exception as e:
            with _state_lock:
                _state["message"] = str(e)
            continue

        error = data.get("error", "")

        if error == "authorization_pending":
            continue  # Nutzer hat noch nicht bestätigt

        if error == "slow_down":
            interval += 5  # Google will langsamer gepollt werden
            continue

        if error == "expired_token":
            with _state_lock:
                _state["status"]  = "expired"
                _state["message"] = "Code abgelaufen"
            return

        if error:
            with _state_lock:
                _state["status"]  = "error"
                _state["message"] = error
            return

        # Erfolg – Token speichern
        access_token  = data.get("access_token", "")
        refresh_token = data.get("refresh_token", "")
        expires_in_t  = data.get("expires_in", 3600)

        # E-Mail über userinfo abrufen
        email = _fetch_email(access_token)

        _save_token({
            "access_token":  access_token,
            "refresh_token": refresh_token,
            "expires_at":    time.time() + expires_in_t,
            "email":         email,
        })

        with _state_lock:
            _state["status"]  = "authorized"
            _state["message"] = f"Verbunden als {email}"
        return

    # Schleife beendet ohne Erfolg → abgelaufen
    with _state_lock:
        if _state["status"] == "pending":
            _state["status"]  = "expired"
            _state["message"] = "Code abgelaufen"


def _fetch_email(access_token: str) -> str:
    """Holt E-Mail-Adresse des angemeldeten Nutzers."""
    try:
        r = requests.get(USERINFO_URL,
                         headers={"Authorization": f"Bearer {access_token}"},
                         timeout=5)
        return r.json().get("email", "")
    except Exception:
        return ""


def _load_token() -> Optional[dict]:
    """Lädt gespeichertes Token aus Datei."""
    if not TOKEN_PATH.exists():
        return None
    try:
        return json.loads(TOKEN_PATH.read_text())
    except Exception:
        return None


def _save_token(token: dict):
    """Speichert Token als JSON."""
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(token, indent=2))


def _save_token_from_creds(creds, email: str):
    """Speichert refreshtes Token zurück."""
    _save_token({
        "access_token":  creds.token,
        "refresh_token": creds.refresh_token,
        "expires_at":    creds.expiry.timestamp() if creds.expiry else time.time() + 3600,
        "email":         email,
    })


def _delete_token():
    """Löscht gespeichertes Token."""
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
