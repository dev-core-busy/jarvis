"""Jarvis FastAPI Server – Haupt-Einstiegspunkt."""

import asyncio
import hashlib
import hmac
import json
import subprocess
import time
from pathlib import Path

import os

import psutil

# ─── Docker-Modus: PAM durch ENV-Variable ersetzen ───────────────────
_DOCKER_MODE = os.getenv("JARVIS_DOCKER", "0") == "1"
_JARVIS_PASSWORD = os.getenv("JARVIS_PASSWORD", "jarvis")

if not _DOCKER_MODE:
    import pam as _pam_module
    _pam = _pam_module.pam()
else:
    _pam = None
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.config import config
from backend.security import get_certificate_path

# ─── App erstellen ────────────────────────────────────────────────────
JARVIS_VERSION = "0.8.0"
app = FastAPI(title="Jarvis", version=JARVIS_VERSION)

# Statische Dateien servieren (mit Cache-Busting Header)
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """JS/CSS-Dateien ohne Browser-Cache ausliefern."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# noVNC-Dateien über Port 443 servieren (verhindert separates SSL-Zertifikat auf Port 6080)
_NOVNC_DIRS = ["/usr/share/novnc", "/usr/share/noVNC", "/snap/novnc/current/usr/share/novnc"]
for _nvdir in _NOVNC_DIRS:
    if Path(_nvdir).is_dir():
        app.mount("/novnc", StaticFiles(directory=_nvdir, html=True), name="novnc")
        break


# ─── WebSocket VNC-Proxy (Same-Origin, kein separates SSL nötig) ──────
@app.websocket("/ws/vnc")
async def vnc_websocket_proxy(websocket: WebSocket):
    """Proxy: Browser-WebSocket → TCP VNC (x11vnc auf Port 5900).

    noVNC sendet Daten über wss://host:443/ws/vnc (gleicher Port/Cert wie UI).
    So entfällt das Problem mit dem separaten SSL-Zertifikat auf Port 6080.
    """
    # Subprotocol nur setzen wenn Client es anbietet (noVNC kann "binary" senden oder nicht)
    requested = websocket.headers.get("sec-websocket-protocol", "")
    subproto = "binary" if "binary" in requested else None
    await websocket.accept(subprotocol=subproto)

    try:
        reader, writer = await asyncio.open_connection("localhost", 5900)
    except (ConnectionRefusedError, OSError):
        await websocket.close(code=1011, reason="VNC nicht erreichbar")
        return

    async def ws_to_tcp():
        """WebSocket-Frames → TCP."""
        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.receive":
                    data = msg.get("bytes") or (msg.get("text", "").encode())
                    if data:
                        writer.write(data)
                        await writer.drain()
                elif msg.get("type") == "websocket.disconnect":
                    break
        except Exception:
            pass
        finally:
            writer.close()

    async def tcp_to_ws():
        """TCP → WebSocket-Frames."""
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                await websocket.send_bytes(data)
        except Exception:
            pass

    done, pending = await asyncio.wait(
        [asyncio.create_task(ws_to_tcp()), asyncio.create_task(tcp_to_ws())],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()

    try:
        await websocket.close()
    except Exception:
        pass


# ─── State ────────────────────────────────────────────────────────────
active_sessions: dict[str, WebSocket] = {}
agent_instance = None  # wird lazy initialisiert (Kompatibilitaet)
agent_manager = None  # AgentManager fuer Multi-Agent Support

# Erlaubte Linux-Benutzer für Web-Login
ALLOWED_USERS = {"jarvis"}


# ─── Hilfsfunktionen ─────────────────────────────────────────────────
def generate_token(username: str) -> str:
    """Token aus Benutzername + Timestamp erzeugen."""
    ts = str(int(time.time()))
    sig = hmac.new(
        config.SECRET_KEY.encode(),
        f"{username}:{ts}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{username}:{ts}:{sig}"


def verify_token(token: str) -> str | None:
    """Token verifizieren (gültig für 24h). Gibt Benutzername zurück oder None."""
    try:
        username, ts, sig = token.split(":", 2)
        age = time.time() - int(ts)
        if age > 86400:
            return None
        expected = hmac.new(
            config.SECRET_KEY.encode(),
            f"{username}:{ts}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(sig, expected):
            return username
        return None
    except Exception:
        return None


def authenticate_linux_user(username: str, password: str) -> bool:
    """Authentifiziert einen Benutzer – via PAM (Linux) oder ENV-Variable (Docker)."""
    if username not in ALLOWED_USERS:
        return False
    if _DOCKER_MODE:
        # Im Docker-Modus: simplen Passwort-Vergleich via ENV-Variable
        return password == _JARVIS_PASSWORD
    return _pam.authenticate(username, password, service="login")


def switch_desktop_session(username: str):
    """Wechselt die aktive Desktop-Session zum angegebenen Benutzer via LightDM-Autologin."""
    import os
    import sys

    AUTOLOGIN_CONF = "/etc/lightdm/lightdm.conf.d/50-jarvis-autologin.conf"

    def log(msg: str):
        print(msg, flush=True)

    def unlock_screen(target_user):
        """Bildschirmschoner deaktivieren nach Login."""
        try:
            uid_result = subprocess.run(
                ["id", "-u", target_user], capture_output=True, text=True, timeout=5
            )
            uid = uid_result.stdout.strip()
            env = {
                "DISPLAY": ":0",
                "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
                "HOME": f"/home/{target_user}",
            }
            # Screensaver sofort deaktivieren
            subprocess.run(
                ["sudo", "-u", target_user, "cinnamon-screensaver-command", "--deactivate"],
                env=env, capture_output=True, timeout=5
            )
            # DPMS (Monitor-Abschaltung) aufwecken
            subprocess.run(
                ["sudo", "-u", target_user, "xset", "-display", ":0", "dpms", "force", "on"],
                env=env, capture_output=True, timeout=5
            )
            subprocess.run(
                ["sudo", "-u", target_user, "xset", "-display", ":0", "s", "reset"],
                env=env, capture_output=True, timeout=5
            )
            log(f"[Session-Wechsel] Bildschirmschoner fuer '{target_user}' deaktiviert.")
        except Exception as e:
            log(f"[Session-Wechsel] Screensaver-Unlock Fehler: {e}")

    def restart_vnc():
        """x11vnc für Display :0 robust neu starten."""
        # Alle x11vnc-Prozesse beenden
        subprocess.run(["pkill", "-9", "x11vnc"], capture_output=True, timeout=5)
        time.sleep(2)
        # Neuen x11vnc starten und prüfen ob er läuft
        result = subprocess.run(
            ["x11vnc", "-display", ":0", "-auth", "guess",
             "-shared", "-forever", "-nopw", "-bg", "-rfbport", "5900"],
            capture_output=True, text=True, timeout=10
        )
        log(f"[Session-Wechsel] x11vnc gestartet: {result.stdout.strip()}")

    try:
        log(f"[Session-Wechsel] Starte Wechsel zu '{username}'...")

        # 1. Prüfen ob der Benutzer bereits eine aktive grafische Session hat
        result = subprocess.run(
            ["loginctl", "list-sessions", "--no-legend"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] == username:
                # Session-Details prüfen: Type=x11 UND Display gesetzt UND auf seat0
                info = subprocess.run(
                    ["loginctl", "show-session", parts[0],
                     "-p", "Type", "-p", "Display", "-p", "Seat"],
                    capture_output=True, text=True, timeout=5
                )
                props = dict(p.split("=", 1) for p in info.stdout.strip().splitlines() if "=" in p)
                if props.get("Type") in ("x11", "wayland") and props.get("Display") and props.get("Seat") == "seat0":
                    subprocess.run(["loginctl", "activate", parts[0]], timeout=5)
                    log(f"[Session-Wechsel] Bestehende Session {parts[0]} für '{username}' aktiviert.")
                    unlock_screen(username)
                    restart_vnc()
                    return

        # 2. LightDM-Autologin per Drop-In-Datei setzen
        os.makedirs(os.path.dirname(AUTOLOGIN_CONF), exist_ok=True)
        with open(AUTOLOGIN_CONF, "w") as f:
            f.write(f"[Seat:*]\nautologin-user={username}\nautologin-user-timeout=0\n")
        log(f"[Session-Wechsel] LightDM-Autologin auf '{username}' gesetzt.")

        # 3. x11vnc stoppen
        subprocess.run(["pkill", "-9", "x11vnc"], capture_output=True, timeout=5)

        # 4. LightDM neu starten (asynchron – blockiert nicht)
        log("[Session-Wechsel] Starte LightDM neu...")
        subprocess.Popen(
            ["systemctl", "restart", "lightdm"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(5)  # LightDM Zeit zum Starten geben

        # 5. Warten bis neue X11-Session gestartet ist
        log(f"[Session-Wechsel] Warte auf Desktop-Session für '{username}'...")
        for attempt in range(20):
            time.sleep(2)
            result2 = subprocess.run(
                ["loginctl", "list-sessions", "--no-legend"],
                capture_output=True, text=True, timeout=5
            )
            for line in result2.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2] == username:
                    info = subprocess.run(
                        ["loginctl", "show-session", parts[0],
                         "-p", "Type", "-p", "Display", "-p", "Seat"],
                        capture_output=True, text=True, timeout=5
                    )
                    props = dict(p.split("=", 1) for p in info.stdout.strip().splitlines() if "=" in p)
                    if props.get("Type") in ("x11", "wayland") and props.get("Display") and props.get("Seat") == "seat0":
                        log(f"[Session-Wechsel] Session für '{username}' erkannt (Display={props.get('Display')}), warte auf Stabilisierung...")
                        time.sleep(8)  # Display vollständig stabilisieren
                        unlock_screen(username)
                        restart_vnc()
                        log(f"[Session-Wechsel] ✅ '{username}' ist jetzt am Desktop angemeldet.")
                        return

        # Fallback
        log("[Session-Wechsel] ⚠️ Timeout - starte x11vnc trotzdem...")
        restart_vnc()

    except Exception as e:
        log(f"[Session-Wechsel] ❌ Fehler: {e}")
        import traceback
        traceback.print_exc()
        try:
            restart_vnc()
        except Exception:
            pass


# ─── HTTP Routes ──────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    """Hauptseite ausliefern (kein Browser-Cache)."""
    index_file = FRONTEND_DIR / "index.html"
    return HTMLResponse(
        content=index_file.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.post("/api/login")
async def login(request: Request):
    """Multi-User Login via Linux PAM → Token + Desktop-Session-Wechsel."""
    body = await request.json()
    username = body.get("username", "").strip().lower()
    password = body.get("password", "")

    if not username or not password:
        return JSONResponse(
            {"success": False, "error": "Benutzername und Passwort erforderlich"},
            status_code=400,
        )

    if authenticate_linux_user(username, password):
        token = generate_token(username)
        # Desktop-Session im Hintergrund wechseln (nur im Nicht-Docker-Modus)
        if not _DOCKER_MODE:
            asyncio.get_event_loop().run_in_executor(None, switch_desktop_session, username)
        return JSONResponse({"success": True, "token": token, "username": username})

    return JSONResponse(
        {"success": False, "error": "Benutzername oder Passwort falsch"},
        status_code=401,
    )


@app.get("/api/version")
async def get_version():
    """Jarvis-Version für Frontend-Anzeige."""
    return JSONResponse({"version": JARVIS_VERSION})


# ─── MCP Server Verwaltung ─────────────────────────────────────────────────
from backend.mcp_client import mcp_manager

@app.on_event("startup")
async def startup_mcp():
    """MCP-Server beim Start verbinden."""
    try:
        await mcp_manager.connect_all()
    except Exception as e:
        print(f"[MCP] Startup-Fehler: {e}", flush=True)

@app.on_event("shutdown")
async def shutdown_mcp():
    """MCP-Server beim Herunterfahren trennen."""
    await mcp_manager.disconnect_all()

@app.get("/api/mcp/servers")
async def get_mcp_servers(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    return JSONResponse(mcp_manager.get_status())

@app.post("/api/mcp/servers")
async def add_mcp_server(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    data = await request.json()
    server = config.add_mcp_server(data)
    if data.get("enabled", True):
        await mcp_manager.connect_server(server["id"])
    return JSONResponse(server)

@app.put("/api/mcp/servers/{server_id}")
async def update_mcp_server(server_id: str, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    data = await request.json()
    result = config.update_mcp_server(server_id, data)
    if not result:
        return JSONResponse({"detail": "Server nicht gefunden"}, status_code=404)
    # Neu verbinden wenn aktiviert
    if result.get("enabled"):
        await mcp_manager.connect_server(server_id)
    else:
        await mcp_manager.disconnect_server(server_id)
    return JSONResponse(result)

@app.delete("/api/mcp/servers/{server_id}")
async def remove_mcp_server(server_id: str, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    await mcp_manager.disconnect_server(server_id)
    if config.remove_mcp_server(server_id):
        return JSONResponse({"ok": True})
    return JSONResponse({"detail": "Server nicht gefunden"}, status_code=404)

@app.post("/api/mcp/servers/{server_id}/toggle")
async def toggle_mcp_server(server_id: str, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    data = await request.json()
    enabled = data.get("enabled", True)
    config.toggle_mcp_server(server_id, enabled)
    if enabled:
        await mcp_manager.connect_server(server_id)
    else:
        await mcp_manager.disconnect_server(server_id)
    return JSONResponse({"ok": True, "enabled": enabled})

@app.post("/api/mcp/servers/{server_id}/reconnect")
async def reconnect_mcp_server(server_id: str, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    success = await mcp_manager.connect_server(server_id)
    return JSONResponse({"ok": success})


# ─── Telemetry API ─────────────────────────────────────────────────────────
from backend.telemetry import tracer

@app.get("/api/telemetry/stats")
async def get_telemetry_stats(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    return JSONResponse(tracer.get_stats())

@app.get("/api/telemetry/spans")
async def get_telemetry_spans(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    limit = int(request.query_params.get("limit", "50"))
    return JSONResponse(tracer.get_recent_spans(limit))

@app.delete("/api/telemetry")
async def clear_telemetry(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    tracer.clear()
    return JSONResponse({"ok": True})


@app.get("/api/config")
async def get_config():
    """Öffentliche Konfiguration für Frontend."""
    return JSONResponse({
        "websockify_port": config.WEBSOCKIFY_PORT,
        "vnc_available": True,
    })
@app.get("/api/cert")
async def download_cert():
    """Zertifikat zum Download anbieten (DER-Format .cer für Windows)."""
    cert_path = get_certificate_path()
    
    if cert_path.exists():
        # Dateiendung bestimmt den MIME-Type
        filename = "jarvis.cer" if cert_path.suffix == ".cer" else "jarvis.crt"
        return FileResponse(
            path=cert_path, 
            filename=filename, 
            media_type="application/x-x509-ca-cert",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    return JSONResponse({"error": "Zertifikat nicht gefunden"}, status_code=404)


@app.get("/api/settings")
async def get_settings():
    """Gibt aktuelle Einstellungen, Profile und Provider-Optionen zurück."""
    return JSONResponse({
        "active_profile_id": config.active_profile_id,
        "profiles": config.profiles,
        "tts_enabled": config.TTS_ENABLED,
        "use_physical_desktop": config.USE_PHYSICAL_DESKTOP,
        "agent_api_key": config.AGENT_API_KEY,
        "defaults": config.DEFAULT_PROVIDERS,
    })


@app.post("/api/settings")
async def save_settings(request: Request):
    """Speichert globale Einstellungen (TTS, Desktop etc.)."""
    body = await request.json()
    config.save_global_settings(body)
    return JSONResponse({"success": True})


# ─── Profil-Verwaltung ─────────────────────────────────────────────
@app.get("/api/profiles")
async def get_profiles():
    """Gibt alle Profile und das aktive Profil zurück."""
    return JSONResponse({
        "profiles": config.profiles,
        "active_profile_id": config.active_profile_id,
        "defaults": config.DEFAULT_PROVIDERS,
    })


@app.post("/api/profiles")
async def create_profile(request: Request):
    """Erstellt ein neues Profil."""
    body = await request.json()
    profile = config.create_profile(body)
    return JSONResponse({"success": True, "profile": profile})


@app.put("/api/profiles/{profile_id}")
async def update_profile(profile_id: str, request: Request):
    """Aktualisiert ein bestehendes Profil."""
    body = await request.json()
    profile = config.update_profile(profile_id, body)
    if profile:
        return JSONResponse({"success": True, "profile": profile})
    return JSONResponse({"success": False, "error": "Profil nicht gefunden"}, status_code=404)


@app.delete("/api/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    """Löscht ein Profil (mindestens eines muss bestehen bleiben)."""
    if config.delete_profile(profile_id):
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "Letztes Profil kann nicht gelöscht werden"}, status_code=400)


@app.post("/api/profiles/{profile_id}/activate")
async def activate_profile(profile_id: str):
    """Setzt ein Profil als aktiv."""
    if config.activate_profile(profile_id):
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "Profil nicht gefunden"}, status_code=404)


@app.get("/api/health")
async def health():
    """Health-Check."""
    errors = config.validate()
    return JSONResponse({
        "status": "ok" if not errors else "warning",
        "errors": errors,
        "cpu_percent": psutil.cpu_percent(interval=0.1),
    })


@app.post("/api/verify-token")
async def verify_token_endpoint(request: Request):
    """Prüft ob ein Token noch gültig ist."""
    body = await request.json()
    tok = body.get("token", "")
    username = verify_token(tok)
    if username:
        return JSONResponse({"valid": True, "username": username})
    return JSONResponse({"valid": False}, status_code=401)


# ─── Skills-Verwaltung ────────────────────────────────────────────
_standalone_skill_manager = None

def _get_skill_manager():
    """Gibt den SkillManager zurueck – nutzt Agent-Instanz falls vorhanden,
    sonst eigenstaendigen SkillManager (z.B. wenn kein API-Key gesetzt)."""
    global agent_instance, _standalone_skill_manager
    if agent_instance is not None:
        return agent_instance.skill_manager
    # Versuche Agent zu erstellen (braucht API-Key)
    try:
        from backend.agent import JarvisAgent
        agent_instance = JarvisAgent()
        return agent_instance.skill_manager
    except Exception:
        # Fallback: SkillManager ohne Agent (Skills browsen/aktivieren geht trotzdem)
        if _standalone_skill_manager is None:
            from backend.skills.manager import SkillManager
            _standalone_skill_manager = SkillManager()
        return _standalone_skill_manager


@app.get("/api/skills")
async def get_skills():
    """Gibt alle Skills mit Status zurück."""
    sm = _get_skill_manager()
    return JSONResponse({"skills": sm.list_skills()})


@app.post("/api/skills/{name}/enable")
async def enable_skill(name: str):
    """Aktiviert einen Skill."""
    sm = _get_skill_manager()
    success = sm.enable_skill(name)
    if agent_instance:
        agent_instance.reload_skills()
    return JSONResponse({"success": success})


@app.post("/api/skills/{name}/disable")
async def disable_skill(name: str):
    """Deaktiviert einen Skill."""
    sm = _get_skill_manager()
    success = sm.disable_skill(name)
    if agent_instance:
        agent_instance.reload_skills()
    return JSONResponse({"success": success})


@app.get("/api/skills/{name}/config")
async def get_skill_config(name: str):
    """Gibt die Konfiguration eines Skills zurück."""
    sm = _get_skill_manager()
    cfg = sm.get_skill_config(name)

    # Google: Aktuelle Werte aus Umgebung einblenden
    if name == "google":
        cfg.setdefault("client_id", os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""))
        cfg.setdefault("client_secret", os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""))

    return JSONResponse({"config": cfg})


@app.post("/api/skills/{name}/config")
async def update_skill_config(name: str, request: Request):
    """Aktualisiert die Konfiguration eines Skills."""
    body = await request.json()
    sm = _get_skill_manager()
    success = sm.update_skill_config(name, body)

    # Google-Spezialfall: Client-ID/Secret in .env schreiben
    if name == "google" and success:
        cid = body.get("client_id", "")
        csecret = body.get("client_secret", "")
        if cid or csecret:
            _update_env_google(cid, csecret)

    return JSONResponse({"success": success})


@app.post("/api/skills/{name}/install")
async def install_skill_deps(name: str):
    """Installiert die Abhängigkeiten eines Skills."""
    sm = _get_skill_manager()
    result = sm.install_dependencies(name)
    return JSONResponse({"result": result})


@app.delete("/api/skills/{name}")
async def uninstall_skill(name: str):
    """Entfernt einen Skill (nur nicht-system Skills)."""
    sm = _get_skill_manager()
    success = sm.uninstall_skill(name)
    if success and agent_instance:
        agent_instance.reload_skills()
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "System-Skill oder nicht gefunden"}, status_code=400)


@app.post("/api/skills/reload")
async def reload_skills():
    """Lädt alle Skills neu (Hot-Reload)."""
    if agent_instance:
        agent_instance.reload_skills()
    return JSONResponse({"success": True})


# ─── Agent Task API (extern, z.B. für Vision-Aktionen) ───────────────

def _verify_agent_api_key(request: Request) -> bool:
    """Prüft API-Key aus X-API-Key Header oder Bearer Token."""
    agent_key = config.AGENT_API_KEY
    if not agent_key:
        return False  # Kein Key konfiguriert → Endpunkt gesperrt

    # X-API-Key Header (bevorzugt)
    header_key = request.headers.get("X-API-Key", "")
    if header_key and hmac.compare_digest(header_key, agent_key):
        return True

    # Fallback: Bearer Token
    bearer = request.headers.get("Authorization", "").replace("Bearer ", "")
    if bearer and hmac.compare_digest(bearer, agent_key):
        return True

    return False


@app.post("/api/agent/task")
async def agent_task(request: Request):
    """Führt eine Aufgabe headless über den Agenten aus.

    Auth: X-API-Key Header oder Bearer Token mit AGENT_API_KEY.
    Body: {"text": "Andreas auf Kamera erkannt", "source": "Raspberry Pi Vision"}
    Response: {"success": true, "result": "..."}

    Der optionale 'source'-Parameter benennt das sendende System.
    Der Task-Text wird automatisch mit Kontext gewrappt, damit das LLM
    weiß, dass die Nachricht extern kommt und NICHT lokale Tools nutzt.

    Typischer Einsatz: Vision-Kamera auf Raspberry Pi erkennt Gesicht
    und informiert den Jarvis-Agenten via HTTP POST.
    """
    if not _verify_agent_api_key(request):
        return JSONResponse(
            {"success": False, "error": "Ungültiger oder fehlender API-Key"},
            status_code=401,
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"success": False, "error": "Ungültiger JSON-Body. Tipp für Windows CMD: Doppelte Anführungszeichen escapen, z.B. {\\\"text\\\": \\\"...\\\"}"},
            status_code=400,
        )

    task_text = body.get("text", "").strip()
    if not task_text:
        return JSONResponse(
            {"success": False, "error": "Kein Task-Text angegeben"},
            status_code=400,
        )

    # Quelle des Aufrufs (optional, z.B. "Raspberry Pi Vision")
    source = body.get("source", "Externes System").strip()

    # Task-Text mit Kontext wrappen, damit das LLM weiß:
    # 1. Die Nachricht kommt von einem EXTERNEN System (nicht lokal)
    # 2. Es soll NICHT die lokale Kamera/Vision verwenden
    # 3. Es soll angemessen reagieren (Begrüßung, Benachrichtigung etc.)
    wrapped_task = (
        f"[Externe Benachrichtigung von: {source}]\n"
        f"{task_text}\n\n"
        f"WICHTIG: Diese Nachricht kommt von einem externen Gerät via API. "
        f"Verwende NICHT die lokale Kamera oder lokale Vision-Tools. "
        f"Reagiere angemessen auf die Benachrichtigung (z.B. Begrüßung, "
        f"Bestätigung, oder die im Profil hinterlegte Aktion ausführen)."
    )

    # Eingehende Benachrichtigung an alle verbundenen WebSocket-Clients senden
    await _broadcast_ws({"type": "status", "message": f"📡 Externe Nachricht von {source}: {task_text}"})

    global agent_instance
    try:
        from backend.agent import JarvisAgent

        if agent_instance is None:
            agent_instance = JarvisAgent()

        result = await agent_instance.run_task_headless(wrapped_task)

        # Ergebnis an Frontend broadcasten
        if result:
            await _broadcast_ws({"type": "status", "message": f"🤖 Antwort: {result[:500]}"})

        return JSONResponse({"success": True, "result": result or ""})

    except Exception as e:
        await _broadcast_ws({"type": "status", "message": f"❌ Agent-Fehler: {str(e)[:200]}"})
        return JSONResponse(
            {"success": False, "error": f"Agent-Fehler: {str(e)[:500]}"},
            status_code=500,
        )


async def _broadcast_ws(message: dict):
    """Sendet eine Nachricht an alle verbundenen WebSocket-Clients."""
    for session_id, ws in list(active_sessions.items()):
        try:
            await ws.send_json(message)
        except Exception:
            pass


# ─── Knowledge Base API ───────────────────────────────────────────────

@app.get("/api/knowledge/stats")
async def get_knowledge_stats():
    """Gibt Statistiken der Knowledge Base zurück."""
    from backend.tools.knowledge import get_stats
    return JSONResponse(get_stats())


@app.post("/api/knowledge/reindex")
async def reindex_knowledge():
    """Erzwingt vollständigen Neuaufbau des Knowledge-Index."""
    import asyncio as _asyncio
    from backend.tools.knowledge import force_reindex
    result = await _asyncio.to_thread(force_reindex)
    return JSONResponse(result)


@app.get("/api/knowledge/files")
async def get_knowledge_files():
    """Gibt alle indizierten Dateien gruppiert nach Ordner zurück."""
    from backend.tools.knowledge import _get_folders, _all_files, PROJECT_ROOT
    folders = _get_folders()
    result = []
    for folder in folders:
        try:
            rel_folder = str(folder.relative_to(PROJECT_ROOT))
        except ValueError:
            rel_folder = str(folder)
        files = []
        if folder.exists():
            for f in sorted(_all_files([folder])):
                size = f.stat().st_size
                size_str = f"{size/1024:.1f} KB" if size >= 1024 else f"{size} B"
                try:
                    rel = str(f.relative_to(PROJECT_ROOT))
                except ValueError:
                    rel = str(f)
                files.append({"path": rel, "name": f.name, "size": size_str})
        result.append({"folder": rel_folder, "exists": folder.exists(), "files": files})
    return JSONResponse(result)


@app.delete("/api/knowledge/files")
async def delete_knowledge_file(request: Request):
    """Löscht eine einzelne Datei aus einem Knowledge-Ordner."""
    from backend.tools.knowledge import _get_folders, PROJECT_ROOT
    data = await request.json()
    file_path = data.get("path", "").strip()
    if not file_path:
        return JSONResponse({"error": "Kein Dateipfad angegeben"}, status_code=400)

    # Sicherheitscheck: Datei muss in einem konfigurierten Knowledge-Ordner liegen
    resolved = (PROJECT_ROOT / file_path).resolve()
    allowed = False
    for folder in _get_folders():
        try:
            resolved.relative_to(folder.resolve())
            allowed = True
            break
        except ValueError:
            continue

    if not allowed:
        return JSONResponse({"error": "Datei liegt nicht in einem Knowledge-Ordner"}, status_code=403)
    if not resolved.is_file():
        return JSONResponse({"error": "Datei nicht gefunden"}, status_code=404)

    resolved.unlink()
    return JSONResponse({"ok": True, "deleted": file_path})


@app.post("/api/knowledge/open-folder")
async def open_knowledge_folder(request: Request):
    """Öffnet einen Knowledge-Ordner im Dateimanager des Server-Desktops."""
    import subprocess, os
    from backend.tools.knowledge import _get_folders, PROJECT_ROOT
    data = await request.json()
    folder_arg = data.get("folder", "").strip()

    target = None
    for f in _get_folders():
        try:
            rel = str(f.relative_to(PROJECT_ROOT))
        except ValueError:
            rel = str(f)
        if rel == folder_arg or str(f) == folder_arg:
            target = f
            break

    if not target:
        return JSONResponse({"error": "Ordner nicht gefunden"}, status_code=404)
    if not target.exists():
        return JSONResponse({"error": "Ordner existiert nicht"}, status_code=404)

    subprocess.Popen(
        ["xdg-open", str(target)],
        env={**os.environ, "DISPLAY": ":1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return JSONResponse({"ok": True})


@app.post("/api/knowledge/upload")
async def upload_knowledge_files(
    files: list[UploadFile] = File(...),
    folder: str = Form("data/knowledge"),
):
    """Dateien per Browser-Upload in einen Knowledge-Ordner hochladen."""
    from backend.tools.knowledge import (
        _get_folders, PROJECT_ROOT,
        EXTENSIONS_TEXT, EXTENSIONS_PDF, EXTENSIONS_DOCX,
        EXTENSIONS_XLSX, EXTENSIONS_PPTX, EXTENSIONS_VIDEO, EXTENSIONS_AUDIO,
    )

    all_exts = (EXTENSIONS_TEXT | EXTENSIONS_PDF | EXTENSIONS_DOCX |
                EXTENSIONS_XLSX | EXTENSIONS_PPTX | EXTENSIONS_VIDEO | EXTENSIONS_AUDIO)

    # Zielordner validieren
    target = None
    for f in _get_folders():
        try:
            rel = str(f.relative_to(PROJECT_ROOT))
        except ValueError:
            rel = str(f)
        if rel == folder or str(f) == folder:
            target = f
            break

    if not target:
        return JSONResponse({"error": f"Ordner '{folder}' nicht konfiguriert"}, status_code=400)

    target.mkdir(parents=True, exist_ok=True)

    saved = []
    rejected = []
    for file in files:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in all_exts:
            rejected.append({"name": file.filename, "reason": f"Format '{suffix}' nicht unterstuetzt"})
            continue

        dest = target / file.filename
        # Dateiname-Kollision: Nummer anhaengen
        counter = 1
        while dest.exists():
            stem = Path(file.filename).stem
            dest = target / f"{stem}_{counter}{suffix}"
            counter += 1

        content = await file.read()
        dest.write_bytes(content)
        size_str = f"{len(content)/1024:.1f} KB" if len(content) >= 1024 else f"{len(content)} B"
        saved.append({"name": dest.name, "size": size_str})

    return JSONResponse({
        "saved": saved,
        "rejected": rejected,
        "total_saved": len(saved),
        "total_rejected": len(rejected),
    })


# ─── Netzwerk-Freigaben (Mounts) ─────────────────────────────────────

_MOUNT_BASE = Path("/mnt/jarvis-kb")


def _get_mounts_config() -> list:
    try:
        states = config.get_skill_states()
        return states.get("knowledge", {}).get("config", {}).get("mounts", [])
    except Exception:
        return []


def _save_mounts_config(mounts: list):
    states = config.get_skill_states()
    kb_state = states.get("knowledge", {})
    kb_cfg = kb_state.get("config", {})
    kb_cfg["mounts"] = mounts
    kb_state["config"] = kb_cfg
    config.save_skill_state("knowledge", kb_state)


def _mount_path(idx: int) -> Path:
    return _MOUNT_BASE / f"share_{idx}"


@app.get("/api/knowledge/mounts")
async def list_mounts():
    mounts = _get_mounts_config()
    result = []
    for i, m in enumerate(mounts):
        mp = _mount_path(i)
        result.append({
            "type": m.get("type", "smb"),
            "source": m.get("source", ""),
            "active": mp.is_mount(),
            "mountpoint": str(mp),
        })
    return JSONResponse(result)


@app.post("/api/knowledge/mounts")
async def add_mount(request: Request):
    data = await request.json()
    source = data.get("source", "").strip()
    mount_type = data.get("type", "smb")
    if not source:
        return JSONResponse({"error": "Quelle fehlt"}, status_code=400)

    mounts = _get_mounts_config()
    mount_entry = {
        "type": mount_type,
        "source": source,
        "username": data.get("username", ""),
        "password": data.get("password", ""),
    }
    mounts.append(mount_entry)
    _save_mounts_config(mounts)

    idx = len(mounts) - 1
    mp = _mount_path(idx)
    mp.mkdir(parents=True, exist_ok=True)

    # Ordner automatisch zur Knowledge-Liste hinzufuegen
    kb_state = config.get_skill_states().get("knowledge", {})
    kb_cfg = kb_state.get("config", {})
    folders = kb_cfg.get("folders", "data/knowledge")
    if str(mp) not in folders:
        folders = folders + "," + str(mp) if folders else str(mp)
        kb_cfg["folders"] = folders
        kb_state["config"] = kb_cfg
        config.save_skill_state("knowledge", kb_state)

    return JSONResponse({"ok": True, "index": idx})


@app.delete("/api/knowledge/mounts/{idx}")
async def remove_mount(idx: int):
    mounts = _get_mounts_config()
    if idx < 0 or idx >= len(mounts):
        return JSONResponse({"error": "Ungueltiger Index"}, status_code=404)

    mp = _mount_path(idx)
    # Unmounten falls aktiv
    if mp.is_mount():
        await asyncio.to_thread(subprocess.run, ["umount", str(mp)], capture_output=True, timeout=10)

    # Ordner aus Knowledge-Liste entfernen
    kb_state = config.get_skill_states().get("knowledge", {})
    kb_cfg = kb_state.get("config", {})
    folders = kb_cfg.get("folders", "data/knowledge")
    folder_list = [f.strip() for f in folders.split(",") if f.strip() and f.strip() != str(mp)]
    kb_cfg["folders"] = ",".join(folder_list) if folder_list else "data/knowledge"
    kb_state["config"] = kb_cfg

    mounts.pop(idx)
    kb_cfg["mounts"] = mounts
    config.save_skill_state("knowledge", kb_state)

    return JSONResponse({"ok": True})


@app.post("/api/knowledge/mounts/{idx}/mount")
async def mount_share(idx: int):
    mounts = _get_mounts_config()
    if idx < 0 or idx >= len(mounts):
        return JSONResponse({"error": "Ungueltiger Index"}, status_code=404)

    m = mounts[idx]
    mp = _mount_path(idx)
    mp.mkdir(parents=True, exist_ok=True)

    mount_type = m.get("type", "smb")
    source = m["source"]
    username = m.get("username", "")
    password = m.get("password", "")

    if mount_type == "smb":
        opts = "ro"
        if username:
            opts += f",username={username},password={password}"
        else:
            opts += ",guest"
        cmd = ["mount", "-t", "cifs", source, str(mp), "-o", opts]
    elif mount_type == "nfs":
        cmd = ["mount", "-t", "nfs", "-o", "ro", source, str(mp)]
    elif mount_type == "webdav":
        # davfs2: Credentials in Datei schreiben
        secrets = Path("/etc/davfs2/secrets")
        secrets.parent.mkdir(parents=True, exist_ok=True)
        line = f"{str(mp)} {username} {password}\n"
        if secrets.exists():
            content = secrets.read_text()
            if str(mp) not in content:
                secrets.write_text(content + line)
        else:
            secrets.write_text(line)
        secrets.chmod(0o600)
        cmd = ["mount", "-t", "davfs", "-o", "ro", source, str(mp)]
    else:
        return JSONResponse({"error": f"Unbekannter Typ: {mount_type}"}, status_code=400)

    result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        return JSONResponse({"error": f"Mount fehlgeschlagen: {result.stderr.strip()}"}, status_code=500)

    return JSONResponse({"ok": True, "mountpoint": str(mp)})


@app.post("/api/knowledge/mounts/{idx}/unmount")
async def unmount_share(idx: int):
    mp = _mount_path(idx)
    if not mp.is_mount():
        return JSONResponse({"ok": True, "hint": "War nicht gemountet"})

    result = await asyncio.to_thread(subprocess.run, ["umount", str(mp)], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        return JSONResponse({"error": f"Unmount fehlgeschlagen: {result.stderr.strip()}"}, status_code=500)

    return JSONResponse({"ok": True})


@app.get("/api/knowledge/webdav/status")
async def webdav_status():
    """WebDAV-Status und Verbindungsdetails."""
    from backend.webdav import _get_webdav_config, is_webdav_enabled
    from backend.tools.knowledge import _get_folders, PROJECT_ROOT
    cfg = _get_webdav_config()
    enabled = is_webdav_enabled()
    folders = _get_folders()
    shares = []
    for f in folders:
        try:
            name = str(f.relative_to(PROJECT_ROOT)).replace("/", "_")
        except ValueError:
            name = f.name
        shares.append(name)
    host = os.getenv("SERVER_IP", "127.0.0.1")
    return JSONResponse({
        "enabled": enabled,
        "url": f"https://{host}/webdav/" if enabled else None,
        "shares": shares if enabled else [],
        "username": cfg.get("username", "jarvis"),
    })


@app.post("/api/knowledge/webdav/config")
async def webdav_config(request: Request):
    """WebDAV aktivieren/deaktivieren + Credentials setzen."""
    data = await request.json()
    states = config.get_skill_states()
    kb_state = states.get("knowledge", {})
    kb_cfg = kb_state.get("config", {})
    webdav = kb_cfg.get("webdav", {})

    if "enabled" in data:
        webdav["enabled"] = bool(data["enabled"])
    if "username" in data:
        webdav["username"] = data["username"]
    if "password" in data and data["password"]:
        webdav["password"] = data["password"]

    kb_cfg["webdav"] = webdav
    kb_state["config"] = kb_cfg
    config.save_skill_state("knowledge", kb_state)

    return JSONResponse({"ok": True, "enabled": webdav.get("enabled", False),
                         "hint": "Server-Neustart noetig fuer WebDAV-Aenderungen"})


# ─── Instructions API ─────────────────────────────────────────────────

INSTRUCTIONS_DIR = Path(__file__).parent.parent / "data" / "instructions"


@app.get("/api/instructions")
async def list_instructions():
    """Listet alle Instruction-Dateien auf."""
    INSTRUCTIONS_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(INSTRUCTIONS_DIR.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        files.append({"name": f.stem, "filename": f.name, "content": content})
    return JSONResponse({"files": files})


@app.get("/api/instructions/{name}")
async def get_instruction(name: str):
    """Liest eine einzelne Instruction-Datei."""
    filepath = INSTRUCTIONS_DIR / f"{name}.md"
    if not filepath.exists():
        return JSONResponse({"error": "Datei nicht gefunden"}, status_code=404)
    return JSONResponse({"name": name, "filename": filepath.name,
                         "content": filepath.read_text(encoding="utf-8")})


@app.post("/api/instructions/{name}")
async def save_instruction(name: str, request: Request):
    """Erstellt oder aktualisiert eine Instruction-Datei."""
    data = await request.json()
    content = data.get("content", "")
    if not name or not name.strip():
        return JSONResponse({"error": "Name darf nicht leer sein"}, status_code=400)
    # Sicherheitscheck: kein Path-Traversal
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
    if not safe_name:
        return JSONResponse({"error": "Ungueltiger Name"}, status_code=400)
    INSTRUCTIONS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = INSTRUCTIONS_DIR / f"{safe_name}.md"
    filepath.write_text(content, encoding="utf-8")
    return JSONResponse({"ok": True, "filename": filepath.name})


@app.delete("/api/instructions/{name}")
async def delete_instruction(name: str):
    """Loescht eine Instruction-Datei."""
    filepath = INSTRUCTIONS_DIR / f"{name}.md"
    if filepath.exists():
        filepath.unlink()
        return JSONResponse({"ok": True})
    return JSONResponse({"error": "Datei nicht gefunden"}, status_code=404)


# ─── Google: .env-Helper ──────────────────────────────────────────────

def _update_env_google(client_id: str, client_secret: str):
    """Schreibt Google-OAuth-Werte in die .env und aktualisiert google_auth."""
    env_path = Path(__file__).parent.parent / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()

    # Bestehende Zeilen aktualisieren oder neue anhängen
    found_id, found_secret = False, False
    for i, line in enumerate(lines):
        if line.startswith("GOOGLE_OAUTH_CLIENT_ID="):
            lines[i] = f"GOOGLE_OAUTH_CLIENT_ID={client_id}"
            found_id = True
        elif line.startswith("GOOGLE_OAUTH_CLIENT_SECRET="):
            lines[i] = f"GOOGLE_OAUTH_CLIENT_SECRET={client_secret}"
            found_secret = True
    if not found_id:
        lines.append(f"GOOGLE_OAUTH_CLIENT_ID={client_id}")
    if not found_secret:
        lines.append(f"GOOGLE_OAUTH_CLIENT_SECRET={client_secret}")

    env_path.write_text("\n".join(lines) + "\n")

    # Auch die laufenden Modul-Variablen aktualisieren
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = client_id
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = client_secret
    try:
        import backend.google_auth as _ga
        _ga.GOOGLE_CLIENT_ID = client_id
        _ga.GOOGLE_CLIENT_SECRET = client_secret
    except Exception:
        pass


# ─── Google OAuth2 (Device Flow) ─────────────────────────────────────

@app.get("/api/google/status")
async def google_status():
    """Gibt den aktuellen Google-Auth-Status zurück."""
    from backend.google_auth import get_status
    import asyncio as _aio
    status = await _aio.to_thread(get_status)
    return JSONResponse(status)


@app.post("/api/google/device-start")
async def google_device_start():
    """Startet den Device Flow – gibt user_code + verification_url zurück."""
    from backend.google_auth import start_device_flow
    import asyncio as _aio
    result = await _aio.to_thread(start_device_flow)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.get("/api/google/device-status")
async def google_device_status():
    """Polling-Endpoint: Status des laufenden Device Flows."""
    from backend.google_auth import get_flow_status
    return JSONResponse(get_flow_status())


@app.post("/api/google/revoke")
async def google_revoke():
    """Widerruft den Google-Zugriff und löscht das Token."""
    from backend.google_auth import revoke
    import asyncio as _aio
    await _aio.to_thread(revoke)
    return JSONResponse({"ok": True})


# ─── OpenClaw Gmail (gog) Setup-Endpoints ────────────────────────────

import subprocess as _sp
from pathlib import Path as _Path

_GOG_BIN          = _Path(__file__).parent.parent / "skills" / "openclaw_gmail" / "gog"
_GOG_CREDS_PATH   = _Path(__file__).parent.parent / "data" / "google_auth" / "gog_client_secret.json"
_gog_connect_proc = None   # laufender gog-auth-add Prozess


def _run_gog(*args, timeout: int = 10) -> dict:
    """Führt gog-Befehl synchron aus, gibt JSON-Dict oder Fehler zurück."""
    if not _GOG_BIN.exists():
        return {"ok": False, "error": "gog-Binary nicht gefunden"}
    try:
        import os as _os
        _gog_env = _os.environ.copy()
        _gog_env["GOG_KEYRING_BACKEND"] = "file"
        _gog_env["GOG_KEYRING_PASSWORD"] = "jarvis-gog-keyring"
        r = _sp.run(
            [str(_GOG_BIN), "--json", "--no-input", *args],
            capture_output=True, text=True, timeout=timeout,
            env=_gog_env,
        )
        out = r.stdout.strip()
        err = r.stderr.strip()
        if r.returncode != 0:
            return {"ok": False, "error": err or out or f"Exit {r.returncode}"}
        if out:
            try:
                import json as _json
                return {"ok": True, "data": _json.loads(out)}
            except Exception:
                return {"ok": True, "data": out}
        return {"ok": True, "data": {}}
    except _sp.TimeoutExpired:
        return {"ok": False, "error": "Timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/google/gog-status")
async def gog_status():
    """Gibt verbundene gog-Konten zurück."""
    import asyncio as _aio
    result = await _aio.to_thread(_run_gog, "auth", "list")
    return JSONResponse(result)


@app.post("/api/google/gog-setup")
async def gog_setup(request: Request):
    """Speichert OAuth-Credentials als client_secret.json + registriert bei gog."""
    import asyncio as _aio, json as _json
    body = await request.json()
    client_id     = body.get("client_id", "").strip()
    client_secret = body.get("client_secret", "").strip()
    email         = body.get("email", "").strip()

    if not client_id or not client_secret or not email:
        return JSONResponse({"ok": False, "error": "client_id, client_secret und email sind erforderlich"}, status_code=400)

    # client_secret.json im erwarteten Google-Format erstellen
    creds_json = {
        "installed": {
            "client_id":      client_id,
            "client_secret":  client_secret,
            "redirect_uris":  ["http://localhost"],
            "auth_uri":       "https://accounts.google.com/o/oauth2/auth",
            "token_uri":      "https://oauth2.googleapis.com/token",
        }
    }
    _GOG_CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _GOG_CREDS_PATH.write_text(_json.dumps(creds_json, indent=2))

    # E-Mail in Skill-Config speichern
    from backend.config import config as _cfg
    _cfg.save_skill_state("openclaw_gmail", {"config": {"account": email, "max_results": "10"}})

    # gog auth credentials registrieren
    result = await _aio.to_thread(_run_gog, "auth", "credentials", "set", str(_GOG_CREDS_PATH))
    if not result["ok"]:
        return JSONResponse(result, status_code=500)

    # Bug-Workaround: gog schreibt client_id in beide Felder – direkt korrigieren
    import pathlib as _pl
    _gog_creds = _pl.Path.home() / ".config" / "gogcli" / "credentials.json"
    _gog_creds.parent.mkdir(parents=True, exist_ok=True)
    _gog_creds.write_text(_json.dumps({"client_id": client_id, "client_secret": client_secret}, indent=2))

    return JSONResponse({"ok": True, "email": email})


@app.post("/api/google/gog-auth-url")
async def gog_get_auth_url(request: Request):
    """Remote-Flow Schritt 1: Gibt die Google-Auth-URL zurück (kein Browser auf Server nötig)."""
    import asyncio as _aio
    body  = await request.json()
    email = body.get("email", "").strip()
    if not email:
        return JSONResponse({"ok": False, "error": "email fehlt"}, status_code=400)
    if not _GOG_BIN.exists():
        return JSONResponse({"ok": False, "error": "gog-Binary nicht gefunden"}, status_code=500)

    # gog auth add --remote --step 1 gibt die Auth-URL auf stdout/stderr aus
    try:
        import os as _os
        _gog_env = _os.environ.copy()
        _gog_env["GOG_KEYRING_BACKEND"] = "file"
        _gog_env["GOG_KEYRING_PASSWORD"] = "jarvis-gog-keyring"
        r = _sp.run(
            [str(_GOG_BIN), "auth", "add", email,
             "--services", "gmail,calendar,drive",
             "--remote", "--step", "1", "--force-consent"],
            capture_output=True, text=True, timeout=15,
            env=_gog_env,
        )
        output = (r.stdout + r.stderr).strip()
        # Auth-URL aus Output extrahieren (beginnt mit https://accounts.google.com)
        import re as _re
        match = _re.search(r'https://accounts\.google\.com\S+', output)
        if match:
            return JSONResponse({"ok": True, "auth_url": match.group(0), "email": email})
        # Fallback: ganzen Output zurückgeben
        return JSONResponse({"ok": False, "error": output or "Keine URL gefunden"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/google/gog-auth-exchange")
async def gog_auth_exchange(request: Request):
    """Remote-Flow Schritt 2: Tauscht Redirect-URL gegen Token."""
    import asyncio as _aio
    body         = await request.json()
    email        = body.get("email", "").strip()
    redirect_url = body.get("redirect_url", "").strip()
    if not email or not redirect_url:
        return JSONResponse({"ok": False, "error": "email und redirect_url erforderlich"}, status_code=400)

    result = await _aio.to_thread(
        _run_gog,
        "auth", "add", email,
        "--services", "gmail,calendar,drive",
        "--remote", "--step", "2",
        f"--auth-url={redirect_url}",
        timeout=20,
    )
    return JSONResponse(result)


@app.delete("/api/google/gog-account")
async def gog_remove_account(request: Request):
    """Entfernt ein gog-Konto."""
    import asyncio as _aio
    body  = await request.json()
    email = body.get("email", "").strip()
    if not email:
        return JSONResponse({"ok": False, "error": "email fehlt"}, status_code=400)
    result = await _aio.to_thread(_run_gog, "auth", "remove", email)
    return JSONResponse(result)


# ─── OpenClaw Marketplace ─────────────────────────────────────────────

@app.get("/api/openclaw/search")
async def openclaw_search(request: Request, q: str = ""):
    """Sucht Skills auf OpenClaw Marketplace.
    Gibt Ergebnisliste zurück – Import erfolgt separat.
    """
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)

    import urllib.request, json as _json
    query = q.strip() or "popular"
    search_url = f"https://clawhub.ai/api/search?q={urllib.parse.quote(query)}"
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": "Jarvis/0.8"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
            raw = data.get("results", data if isinstance(data, list) else [])
            # Einheitliches Format fuer Frontend
            results = []
            for s in raw[:20]:
                results.append({
                    "name": s.get("displayName") or s.get("name") or s.get("slug", ""),
                    "slug": s.get("slug", ""),
                    "description": s.get("summary") or s.get("description", ""),
                    "stars": round(s.get("score", 0), 1) if s.get("score") else None,
                    "author": s.get("author", ""),
                    "url": f"https://clawhub.ai/skills/{s.get('slug', '')}",
                })
    except Exception as e:
        results = []
        _log(f"ClawHub API nicht erreichbar ({e})")

    return JSONResponse({"results": results, "query": query})


@app.get("/api/openclaw/workflow-task")
async def openclaw_workflow_task(
    request: Request,
    description: str = "",
):
    """Gibt den fertigen Agent-Task-Text zurück, der den Import-Workflow ausführt.
    Liest data/workflows/import_openclaw_skill.md und bettet ihn in den Task ein.
    """
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    workflow_path = _Path(__file__).parent.parent / "data" / "workflows" / "import_openclaw_skill.md"
    if workflow_path.exists():
        workflow_md = workflow_path.read_text(encoding="utf-8", errors="replace")
    else:
        workflow_md = "(Workflow-Datei nicht gefunden – nutze allgemeines Vorgehen)"

    target_dir = str(_Path(__file__).parent.parent / "skills_from_openclaw")
    desc_text  = description.strip() or "Zeige mir verfügbare und beliebte OpenClaw Skills"

    task_text = f"""Führe folgenden OpenClaw Skill-Import-Workflow exakt und vollständig aus:

--- WORKFLOW-ANWEISUNGEN START ---
{workflow_md}
--- WORKFLOW-ANWEISUNGEN ENDE ---

Nutzerwunsch: "{desc_text}"
Ziel-Verzeichnis für importierte Skills: {target_dir}

Starte jetzt mit Schritt 1 (Skill-Entdeckung und Websuche)."""

    return JSONResponse({"task": task_text})


# ─── Vision (Gesichtserkennung) ──────────────────────────────────────

def _vision_action_callback(action_type: str, text: str, name: str):
    """Callback fuer Vision-Aktionen (greet, llm) → WebSocket-Broadcast."""
    import asyncio

    if action_type == "greet_audio":
        # Vorgerenderte Audio-Datei abspielen (text = URL-Pfad)
        msg = {"type": "greet_audio", "url": text, "name": name}
    elif action_type == "greet":
        # Live-TTS Fallback
        msg = {"type": "tts", "text": text, "name": name}
    elif action_type == "llm":
        msg = {"type": "status", "message": f"🧠 Vision LLM-Aktion für {name}: {text[:200]}"}
    else:
        return

    # Broadcast an alle WebSocket-Clients (aus Background-Thread heraus)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_broadcast_ws(msg), loop)
        else:
            loop.run_until_complete(_broadcast_ws(msg))
    except Exception:
        # Fallback: neuen Loop erstellen
        try:
            asyncio.run(_broadcast_ws(msg))
        except Exception:
            pass


def _get_vision_engine():
    """Gibt die VisionEngine-Singleton-Instanz zurueck (lazy import)."""
    try:
        from skills.vision.main import get_engine
        engine = get_engine()
        # Callback registrieren falls noch nicht gesetzt
        if engine and engine.on_action is None:
            engine.on_action = _vision_action_callback
        return engine
    except Exception:
        return None


@app.get("/api/vision/status")
async def vision_status(request: Request):
    """Vision-Engine-Status + aktuelle Gesichter."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)
    return JSONResponse(engine.get_status())


@app.post("/api/vision/control")
async def vision_control(request: Request):
    """Kamera starten/stoppen. Body: {action: 'start'|'stop', source: '0'}."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    body = await request.json()
    action = body.get("action", "start")
    source = body.get("source", "0")

    if action == "start":
        # Config-Werte anwenden
        sm = _get_skill_manager()
        cfg = sm.get_skill_config("vision")
        engine.configure(
            tolerance=cfg.get("tolerance", 0.6),
            interval=cfg.get("recognition_interval", 1.0),
            detection_model=cfg.get("detection_model", "hog"),
        )
        # Fallback: Gespeicherte camera_source verwenden wenn Frontend Default '0' schickt
        if source == "0" and cfg.get("camera_source", "0") != "0":
            source = cfg["camera_source"]
        msg = engine.start(source)
    elif action == "stop":
        msg = engine.stop()
    else:
        msg = f"Unbekannte Aktion: {action}"
    return JSONResponse({"message": msg})


@app.get("/api/vision/snapshot")
async def vision_snapshot(request: Request):
    """Aktuelles Kamerabild als JPEG (mit Annotationen). Token via Header ODER ?token= Query."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        # Fallback: Token als Query-Parameter (fuer <img src="..."> ohne Auth-Header)
        token = request.query_params.get("token", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    jpeg = engine.get_snapshot(annotate=True)
    if jpeg is None:
        return JSONResponse({"error": "Kein Kamerabild verfuegbar"}, status_code=404)
    return Response(content=jpeg, media_type="image/jpeg")


@app.get("/api/vision/stream")
async def vision_mjpeg_stream(request: Request):
    """MJPEG-Relay-Stream – erlaubt mehreren Clients den Zugriff auf den Kamera-Feed.

    Auth via ?token= Query ODER ?key=jarvis-stream (fuer Server-zu-Server).
    Nutzung: Als Kamera-Quelle auf anderen Jarvis-Instanzen eintragen.
    """
    # Auth: normaler Token ODER fester Stream-Key
    token = request.query_params.get("token", "")
    stream_key = request.query_params.get("key", "")
    if not verify_token(token) and stream_key != "jarvis-stream":
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    async def generate():
        while True:
            jpeg = engine.get_snapshot(annotate=False)
            if jpeg:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n"
                       b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                       + jpeg + b"\r\n")
            await asyncio.sleep(0.066)  # ~15 FPS

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/vision/face-crop/{index}")
async def vision_face_crop(index: int, request: Request):
    """Aktuellen Face-Crop als JPEG. Token via Header ODER ?token= Query."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        token = request.query_params.get("token", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    with engine._lock:
        crops = list(engine._current_face_crops)
    if index < 0 or index >= len(crops) or not crops[index]:
        return JSONResponse({"error": "Kein Face-Crop verfuegbar"}, status_code=404)
    return Response(content=crops[index], media_type="image/jpeg")


@app.get("/api/vision/cameras")
async def vision_cameras(request: Request):
    """Verfuegbare Kameras auflisten."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    import asyncio as _aio
    cameras = await _aio.to_thread(engine.list_cameras)
    return JSONResponse({"cameras": cameras})


@app.get("/api/vision/preview/{index}")
async def vision_preview(index: int, request: Request):
    """Einzelbild einer bestimmten Kamera (fuer Preview)."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    import asyncio as _aio
    jpeg = await _aio.to_thread(engine.get_preview, index)
    if jpeg is None:
        return JSONResponse({"error": "Kamera nicht verfuegbar"}, status_code=404)
    return Response(content=jpeg, media_type="image/jpeg")


@app.get("/api/vision/profiles")
async def vision_profiles(request: Request):
    """Alle Profile mit Aktionen auflisten."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    profiles = engine.list_profiles()
    actions = engine.get_available_actions()
    return JSONResponse({"profiles": profiles, "actions": actions})


@app.post("/api/vision/profiles")
async def vision_profile_update(request: Request):
    """Profil aktualisieren (Name, Aktion, Aktions-Wert)."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    body = await request.json()
    name = body.get("name", "")
    if not name:
        return JSONResponse({"error": "name erforderlich"}, status_code=400)

    msg = engine.update_profile(
        name,
        display_name=body.get("display_name"),
        action=body.get("action"),
        action_value=body.get("action_value"),
        greet_target=body.get("greet_target"),
    )

    # Bei Begruessungs-Aktion: Audio vorrendern
    action = body.get("action")
    if action == "greet":
        action_value = body.get("action_value", "")
        audio_path = engine.generate_greet_audio(name, action_value)
        if audio_path:
            msg += " Audio generiert."

    return JSONResponse({"message": msg})


@app.post("/api/vision/profiles/rename")
async def vision_profile_rename(request: Request):
    """Profil umbenennen (z.B. nach Training mit Temp-Name)."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    body = await request.json()
    old_name = body.get("old_name", "")
    new_name = body.get("new_name", "")
    if not old_name or not new_name:
        return JSONResponse({"error": "old_name und new_name erforderlich"}, status_code=400)

    msg = engine.rename_profile(old_name, new_name)
    return JSONResponse({"message": msg})


@app.delete("/api/vision/profile/{name}")
async def vision_profile_delete(name: str, request: Request):
    """Profil loeschen."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)
    msg = engine.delete_profile(name)
    return JSONResponse({"message": msg})


@app.get("/api/vision/thumbnail/{name}")
async def vision_thumbnail(name: str, request: Request):
    """Profilbild (erstes Trainingsfoto) als JPEG. Token via Header ODER ?token= Query."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        token = request.query_params.get("token", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    jpeg = engine.get_thumbnail(name)
    if jpeg is None:
        return JSONResponse({"error": "Kein Thumbnail verfuegbar"}, status_code=404)
    return Response(content=jpeg, media_type="image/jpeg")


@app.post("/api/vision/training/start")
async def vision_training_start(request: Request):
    """Training starten. Body: {name: '...', samples: 30}."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    body = await request.json()
    name = body.get("name", "")
    samples = body.get("samples", 30)
    if not name:
        return JSONResponse({"error": "name erforderlich"}, status_code=400)
    msg = engine.start_training(name, samples)
    return JSONResponse({"message": msg})


@app.post("/api/vision/training/stop")
async def vision_training_stop(request: Request):
    """Training stoppen + Modell neu berechnen."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)
    msg = engine.stop_training()
    return JSONResponse({"message": msg})


@app.get("/api/vision/training/status")
async def vision_training_status(request: Request):
    """Training-Fortschritt abfragen."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)
    return JSONResponse(engine.get_training_status())


@app.get("/api/vision/events")
async def vision_events(request: Request, limit: int = 50):
    """Letzte Erkennungs-Events."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)
    return JSONResponse({"events": engine.get_recent_events(limit)})


@app.post("/api/vision/cleanup")
async def vision_cleanup(request: Request):
    """Alle Vision-Daten zuruecksetzen."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)
    msg = engine.cleanup()
    return JSONResponse({"message": msg})


@app.get("/api/vision/greet-audio/{name}")
async def vision_greet_audio(name: str, request: Request):
    """Vorgerenderte Begruessungs-Audio (MP3 bevorzugt, WAV Fallback). Token via Header ODER ?token= Query."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        token = request.query_params.get("token", "")
    if not verify_token(token):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)

    from pathlib import Path as _Path
    audio_dir = _Path(__file__).parent.parent / "data" / "vision" / "audio"
    # MP3 bevorzugt (edge-tts), WAV als Fallback (espeak-ng)
    # Leere Dateien ignorieren (fehlgeschlagene Generierung)
    mp3_path = audio_dir / f"greet_{name}.mp3"
    wav_path = audio_dir / f"greet_{name}.wav"
    if mp3_path.exists() and mp3_path.stat().st_size > 0:
        audio_path = mp3_path
        media_type = "audio/mpeg"
    elif wav_path.exists() and wav_path.stat().st_size > 0:
        audio_path = wav_path
        media_type = "audio/wav"
    else:
        return JSONResponse({"error": "Keine Audio-Datei vorhanden"}, status_code=404)
    return Response(
        content=audio_path.read_bytes(),
        media_type=media_type,
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/vision/download/stream-tools")
async def vision_download_stream_tools(request: Request):
    """Redirect zu jarvis-ai.info fuer Stream-Tools ZIP-Download."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("https://jarvis-ai.info/downloads/jarvis_cam_stream.zip"
    )


# ─── WhatsApp Integration ────────────────────────────────────────────
import urllib.request
import urllib.error
import os
import threading

from backend.tools.wa_logger import log as wa_log, get_logs as wa_get_logs, clear_logs as wa_clear_logs

WA_BRIDGE = "http://127.0.0.1:3001"
_whisper_model = None
_whisper_lock = threading.Lock()


def _get_whisper_model():
    """Lädt das Whisper-Modell (lazy, thread-safe)."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model

        try:
            from faster_whisper import WhisperModel

            # Modell aus WhatsApp-Skill-Config lesen
            sm = _get_skill_manager()
            wa_config = sm.get_skill_config("whatsapp")
            model_name = wa_config.get("whisper_model", "small")

            wa_log("INFO", "transcription", f"Lade Whisper-Modell '{model_name}'...")
            _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
            wa_log("INFO", "transcription", f"Whisper-Modell '{model_name}' geladen")
            return _whisper_model
        except Exception as e:
            wa_log("ERROR", "transcription", f"Whisper-Fehler: {e}")
            return None


def _transcribe_audio(filepath: str, language: str = "de") -> str:
    """Transkribiert eine Audiodatei mit faster-whisper."""
    import time as _time
    model = _get_whisper_model()
    if model is None:
        wa_log("ERROR", "transcription", "Whisper-Modell nicht verfuegbar")
        return "[Transkription fehlgeschlagen: Whisper-Modell nicht verfuegbar]"

    try:
        t0 = _time.time()
        segments, info = model.transcribe(filepath, language=language)
        text = " ".join([seg.text for seg in segments]).strip()
        duration = round(_time.time() - t0, 2)
        if text:
            wa_log("INFO", "transcription", f"Transkription OK ({duration}s): {text[:100]}")
            wa_log("DEBUG", "transcription", f"Voller Text: {text}", meta={
                "duration_s": duration, "language": info.language,
                "language_prob": round(info.language_probability, 3),
                "file": filepath,
            }, debug_only=True)
            return text
        wa_log("WARN", "transcription", "Keine Sprache erkannt", meta={"file": filepath})
        return "[Keine Sprache erkannt]"
    except Exception as e:
        wa_log("ERROR", "transcription", f"Transkription fehlgeschlagen: {e}", meta={"file": filepath})
        return f"[Transkription fehlgeschlagen: {e}]"


def _wa_bridge_request(path: str, method: str = "GET", data: dict = None) -> dict:
    """HTTP-Anfrage an die WhatsApp Bridge (synchron, fuer Thread-Pool)."""
    try:
        url = f"{WA_BRIDGE}{path}"
        if data:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method=method,
            )
        else:
            req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except Exception:
            return {"error": body, "status": e.code}
    except urllib.error.URLError as e:
        return {"error": f"Bridge nicht erreichbar: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


async def _wa_bridge_async(path: str, method: str = "GET", data: dict = None) -> dict:
    """Async Wrapper – fuehrt Bridge-Request im Thread-Pool aus, blockiert Event-Loop nicht."""
    return await asyncio.to_thread(_wa_bridge_request, path, method, data)


@app.get("/api/whatsapp/status")
async def wa_status():
    """WhatsApp Bridge Status (Proxy)."""
    result = await _wa_bridge_async("/status")
    return JSONResponse(result)


@app.get("/api/whatsapp/qr")
async def wa_qr():
    """WhatsApp QR-Code zum Scannen (Proxy)."""
    result = await _wa_bridge_async("/qr")
    return JSONResponse(result)


@app.post("/api/whatsapp/logout")
async def wa_logout():
    """WhatsApp abmelden (Proxy)."""
    result = await _wa_bridge_async("/logout", method="POST")
    return JSONResponse(result)


@app.post("/api/whatsapp/reconnect")
async def wa_reconnect():
    """WhatsApp Reconnect erzwingen (Proxy)."""
    result = await _wa_bridge_async("/reconnect", method="POST")
    return JSONResponse(result)


@app.get("/api/whatsapp/logs")
async def wa_logs(request: Request, lines: int = 100, level: str = None, category: str = None):
    """WhatsApp-Logs abrufen (gefiltert)."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"error": "Nicht autorisiert"}, status_code=401)
    entries = wa_get_logs(lines=lines, level=level, category=category)
    return JSONResponse({"logs": entries, "total": len(entries)})


@app.delete("/api/whatsapp/logs")
async def wa_logs_clear(request: Request):
    """WhatsApp-Logs loeschen."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"error": "Nicht autorisiert"}, status_code=401)
    wa_clear_logs()
    return JSONResponse({"status": "ok", "message": "Logs geloescht"})


@app.get("/api/whatsapp/bridge-logs")
async def wa_bridge_logs(request: Request, lines: int = 100, level: str = None, category: str = None):
    """Bridge-Logs abrufen (Proxy zum Bridge-Service)."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"error": "Nicht autorisiert"}, status_code=401)
    params = f"?lines={lines}"
    if level:
        params += f"&level={level}"
    if category:
        params += f"&category={category}"
    result = await _wa_bridge_async(f"/logs{params}")
    return JSONResponse(result)


@app.delete("/api/whatsapp/bridge-logs")
async def wa_bridge_logs_clear(request: Request):
    """Bridge-Logs loeschen (Proxy zum Bridge-Service + lokaler Fallback)."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return JSONResponse({"error": "Nicht autorisiert"}, status_code=401)
    # Versuche ueber Bridge-API
    result = await _wa_bridge_async("/logs", method="DELETE")
    # Fallback: Falls Bridge nicht erreichbar, Datei direkt loeschen
    if "error" in result:
        bridge_log = Path(__file__).parent.parent / "data" / "logs" / "whatsapp-bridge.log"
        try:
            if bridge_log.exists():
                bridge_log.unlink()
            result = {"status": "ok", "message": "Bridge-Logs direkt geloescht (Fallback)"}
        except Exception as e:
            result = {"error": f"Fallback-Loeschen fehlgeschlagen: {e}"}
    return JSONResponse(result)


@app.post("/api/whatsapp/incoming")
async def wa_incoming(request: Request):
    """Eingehende WhatsApp-Nachrichten von der Bridge verarbeiten.

    Die Bridge sendet hierher:
    - type=text: Textnachricht → direkt als Agent-Task
    - type=voice: Sprachnachricht → Whisper-Transkription → Agent-Task
    - type=image/other: nur loggen
    """
    body = await request.json()

    msg_type = body.get("type", "")
    sender = body.get("from", "unbekannt")
    push_name = body.get("push_name", "")
    timestamp = body.get("timestamp", "")

    wa_log("INFO", "incoming", f"Nachricht: type={msg_type} from=+{sender} ({push_name})")
    wa_log("DEBUG", "incoming", "Vollstaendiger Payload", meta=body, debug_only=True)

    # Prüfen ob WhatsApp-Skill aktiviert ist
    sm = _get_skill_manager()
    wa_config = sm.get_skill_config("whatsapp")

    # Whitelist prüfen
    allowed = wa_config.get("allowed_numbers", "")
    if allowed:
        allowed_list = [n.strip().replace("+", "") for n in allowed.split(",") if n.strip()]
        sender_clean = sender.replace("+", "")
        if allowed_list and sender_clean not in allowed_list:
            wa_log("WARN", "auth", f"Abgelehnt: +{sender} nicht in Whitelist")
            return JSONResponse({"status": "rejected", "reason": "not_whitelisted"})

    task_text = None
    source_info = f"(WhatsApp von +{sender})"

    if msg_type == "text":
        if not wa_config.get("process_text", True):
            wa_log("INFO", "incoming", "Text-Verarbeitung deaktiviert, ignoriere")
            return JSONResponse({"status": "ignored", "reason": "text_disabled"})

        task_text = body.get("text", "").strip()
        if not task_text:
            return JSONResponse({"status": "ignored", "reason": "empty"})

        wa_log("INFO", "incoming", f"Text von +{sender}: {task_text[:100]}")

    elif msg_type == "voice":
        if not wa_config.get("process_voice", True):
            wa_log("INFO", "incoming", "Voice-Verarbeitung deaktiviert, ignoriere")
            return JSONResponse({"status": "ignored", "reason": "voice_disabled"})

        media_path = body.get("media_path", "")
        duration = body.get("duration", 0)

        if not media_path or not os.path.exists(media_path):
            wa_log("ERROR", "incoming", f"Voice-Datei nicht gefunden: {media_path}")
            return JSONResponse({"status": "error", "reason": "file_not_found"})

        wa_log("INFO", "transcription", f"Starte Transkription ({duration}s): {media_path}")

        # Transkription in Thread-Pool (blockiert nicht den Event-Loop)
        loop = asyncio.get_event_loop()
        task_text = await loop.run_in_executor(None, _transcribe_audio, media_path)

        wa_log("INFO", "transcription", f"Ergebnis: {task_text[:200]}")

        # Audio-Datei aufräumen
        try:
            os.remove(media_path)
        except Exception:
            pass

    elif msg_type == "image":
        wa_log("INFO", "incoming", f"Bild von +{sender} (Caption: {body.get('caption', '')})")
        return JSONResponse({"status": "ignored", "reason": "images_not_supported_yet"})

    else:
        wa_log("INFO", "incoming", f"Unbekannter Typ: {msg_type}")
        return JSONResponse({"status": "ignored", "reason": "unsupported_type"})

    # Agent-Task starten und Ergebnis an WhatsApp zurücksenden
    if task_text and not task_text.startswith("["):
        auto_reply = wa_config.get("auto_reply", True)
        wa_log("INFO", "agent", f"Starte Task: {task_text[:100]}")
        asyncio.create_task(_run_wa_task(task_text, sender, source_info, auto_reply))
        return JSONResponse({"status": "processing", "text": task_text})

    return JSONResponse({"status": "received"})


WA_TASK_PROMPT = """Du hast eine WhatsApp-Nachricht von {sender} erhalten. Bearbeite die Anfrage und antworte kurz und praezise (WhatsApp-tauglich, kein Markdown).

Beispiel-Nachrichten und was du tun sollst:
- "Was ist meine IP?" → shell_execute: curl -s ifconfig.me
- "Mach einen Screenshot" → screenshot Tool nutzen, Ergebnis beschreiben
- "Oeffne Firefox" → shell_execute oder desktop_control
- "Wie viel Speicher ist frei?" → shell_execute: df -h oder free -h
- "Wie ist das Wetter?" → shell_execute: curl -s wttr.in/Berlin?format=3
- "Suche nach X" → knowledge_search nutzen
- "Hallo" / "Test" → Kurz antworten, z.B. "Jarvis hier, was kann ich tun?"
- "Starte den Webserver neu" → shell_execute: systemctl restart ...
- "Liste die letzten Logs" → shell_execute: journalctl oder tail

WICHTIG: Antworte NUR mit dem Ergebnis. Kein "Ich werde...", kein "Lass mich...". Direkte Antwort.
Wenn du ein Tool nutzt, fuehre es aus und antworte mit dem Ergebnis.
Speichere Nachrichten NICHT im Memory, ausser der Benutzer sagt explizit "merke dir..." oder "speichere...".

Nachricht:
{text}"""


async def _run_wa_task(task_text: str, sender: str, source_info: str, auto_reply: bool):
    """Führt einen WhatsApp-Auftrag aus und sendet das Ergebnis zurück."""
    global agent_instance

    try:
        from backend.agent import JarvisAgent

        if agent_instance is None:
            agent_instance = JarvisAgent()

        full_task = WA_TASK_PROMPT.format(sender=f"+{sender}", text=task_text)
        wa_log("INFO", "agent", f"Starte Agent-Task: {task_text[:150]}")

        # Agent-Task ohne WebSocket ausführen (Ergebnis sammeln)
        result = await agent_instance.run_task_headless(full_task)

        wa_log("INFO", "agent", f"Ergebnis: {result[:200] if result else '(leer)'}")
        wa_log("DEBUG", "agent", "Volles Ergebnis", meta={"result": result, "sender": sender}, debug_only=True)

        # Antwort an WhatsApp senden
        if auto_reply and result:
            # Ergebnis kürzen falls zu lang (WhatsApp-Limit ~65000 Zeichen)
            reply = result[:4000]
            if len(result) > 4000:
                reply += "\n\n... (gekürzt)"

            _wa_bridge_request("/send", method="POST", data={
                "to": f"+{sender}",
                "message": reply,
            })
            wa_log("INFO", "outgoing", f"Antwort an +{sender} gesendet ({len(reply)} Zeichen)")

    except Exception as e:
        wa_log("ERROR", "agent", f"Task-Fehler: {e}", meta={"sender": sender, "task": task_text[:200]})
        if auto_reply:
            _wa_bridge_request("/send", method="POST", data={
                "to": f"+{sender}",
                "message": f"Jarvis Fehler: {str(e)[:500]}",
            })


# ─── WebSocket ────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Haupt-WebSocket für Agent-Steuerung und Status-Updates."""
    await ws.accept()
    session_id = str(id(ws))
    active_sessions[session_id] = ws

    # CPU-Last-Sender im Hintergrund
    cpu_task = asyncio.create_task(cpu_broadcast(ws))

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            await handle_ws_message(ws, msg)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS Error] {e}")
    finally:
        cpu_task.cancel()
        active_sessions.pop(session_id, None)


async def cpu_broadcast(ws: WebSocket):
    """Sendet CPU-Last alle 2 Sekunden an den Client."""
    try:
        while True:
            cpu = psutil.cpu_percent(interval=0)
            await ws.send_json({"type": "cpu", "value": cpu})
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def handle_ws_message(ws: WebSocket, msg: dict):
    """Verarbeitet eingehende WebSocket-Nachrichten."""
    global agent_instance, agent_manager

    msg_type = msg.get("type", "")

    # Token pruefen
    token = msg.get("token", "")
    if msg_type != "ping" and verify_token(token) is None:
        await ws.send_json({"type": "error", "message": "Nicht autorisiert"})
        return

    if msg_type == "task":
        # Neue Aufgabe starten
        task_text = msg.get("text", "").strip()
        if not task_text:
            await ws.send_json({"type": "error", "message": "Keine Aufgabe angegeben"})
            return

        target_agent_id = msg.get("agent_id", "")

        from backend.agent import JarvisAgent, AgentManager

        # AgentManager initialisieren
        if agent_manager is None:
            agent_manager = AgentManager()

        # Wenn agent_id angegeben und es ein existierender Sub-Agent ist:
        # Nachricht als Follow-Up an den Sub-Agent senden (neuer Task)
        if target_agent_id and agent_manager.get_agent(target_agent_id):
            target = agent_manager.get_agent(target_agent_id)
            if target.is_sub_agent:
                asyncio.create_task(target.run_task(task_text, ws))
                return

        agent = agent_manager.get_or_create_main()
        agent_instance = agent  # Kompatibilitaet

        # Agent-Liste ans Frontend senden
        await ws.send_json({
            "type": "agent_event",
            "event": "started",
            "agent": agent.get_info(),
            "agents": agent_manager.get_all_info(),
        })

        # Aufgabe im Hintergrund starten
        asyncio.create_task(agent.run_task(task_text, ws))

    elif msg_type == "spawn_agent":
        # Sub-Agent starten (vom Frontend oder Hauptagent)
        from backend.agent import AgentManager

        if agent_manager is None:
            await ws.send_json({"type": "error", "message": "Kein AgentManager aktiv"})
            return

        label = msg.get("label", "Sub-Agent")
        task_text = msg.get("text", "").strip()
        if not task_text:
            await ws.send_json({"type": "error", "message": "Keine Aufgabe fuer Sub-Agent"})
            return

        sub = agent_manager.spawn_sub_agent(label, task_text)
        asyncio.create_task(agent_manager.run_sub_agent(sub, task_text, ws))

    elif msg_type == "control":
        # Steuerungsbefehle
        action = msg.get("action", "")
        target_id = msg.get("agent_id", "")

        # Ziel-Agent bestimmen
        target = None
        if agent_manager and target_id:
            target = agent_manager.get_agent(target_id)
        if target is None:
            target = agent_instance

        if target is None:
            await ws.send_json({"type": "error", "message": "Kein Agent aktiv"})
            return

        if action == "pause":
            target.pause()
            await ws.send_json({"type": "status", "message": "⏸️ Agent pausiert",
                                "agent_id": target.agent_id})
        elif action == "resume":
            target.resume()
            await ws.send_json({"type": "status", "message": "▶️ Agent fortgesetzt",
                                "agent_id": target.agent_id})
        elif action == "stop":
            target.stop()
            await ws.send_json({"type": "status", "message": "⏹️ Agent gestoppt",
                                "agent_id": target.agent_id})
        elif action == "stop_all":
            if agent_manager:
                agent_manager.stop_all()
            await ws.send_json({"type": "status", "message": "⏹️ Alle Agents gestoppt"})

    elif msg_type == "get_agents":
        # Agent-Liste anfordern
        agents = agent_manager.get_all_info() if agent_manager else []
        await ws.send_json({"type": "agent_list", "agents": agents})

    elif msg_type == "ping":
        await ws.send_json({"type": "pong"})


# ─── HTTP → HTTPS Redirect (Port 80 → 443) ──────────────────────────
async def _start_http_redirect():
    """Startet einen leichten HTTP-Server auf Port 80, der alles auf HTTPS umleitet."""
    from starlette.applications import Starlette
    from starlette.responses import RedirectResponse as _RR
    from starlette.routing import Route

    async def _redirect(request):
        target = str(request.url).replace("http://", "https://", 1)
        return _RR(target, status_code=301)

    redirect_app = Starlette(routes=[Route("/{path:path}", _redirect)])
    redirect_cfg = uvicorn.Config(redirect_app, host="0.0.0.0", port=80, log_level="warning")
    server = uvicorn.Server(redirect_cfg)
    asyncio.create_task(server.serve())
    print("🔀 HTTP→HTTPS Redirect aktiv (Port 80 → 443)")


# ─── Startup ──────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    """Prüfe Konfiguration beim Start."""
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"⚠️  {e}")
    else:
        port_info = f":{config.SERVER_PORT}" if config.SERVER_PORT != 443 else ""
        print("✅ Jarvis Backend gestartet")
        print(f"🌐 https://{os.getenv('SERVER_IP', '127.0.0.1')}{port_info}")

    # WebDAV-Server mounten (wenn aktiviert)
    try:
        from backend.webdav import get_webdav_app, is_webdav_enabled
        if is_webdav_enabled():
            dav_app = get_webdav_app()
            if dav_app:
                from starlette.middleware.wsgi import WSGIMiddleware
                app.mount("/webdav", WSGIMiddleware(dav_app))
                print("📁 WebDAV-Server aktiv unter /webdav/")
    except Exception as e:
        print(f"⚠️  WebDAV konnte nicht gestartet werden: {e}")

    # HTTP→HTTPS Redirect-Server auf Port 80 starten
    if config.SERVER_PORT == 443:
        try:
            await _start_http_redirect()
        except Exception as e:
            print(f"⚠️  HTTP-Redirect (Port 80) konnte nicht gestartet werden: {e}")

    # Vision auto_start: Kamera automatisch starten wenn konfiguriert
    try:
        import threading
        sm = _get_skill_manager()
        if sm:
            states = config.get_skill_states()
            vis_cfg = states.get("vision", {}).get("config", {})
            if vis_cfg.get("auto_start") and vis_cfg.get("camera_source", "0") != "0":
                source = vis_cfg["camera_source"]
                def _auto_start_vision():
                    import time
                    time.sleep(2)  # Kurz warten bis alles initialisiert
                    engine = _get_vision_engine()
                    if engine and not engine._running:
                        engine.start(source)
                        print(f"📷 Vision auto-start: {source}")
                threading.Thread(target=_auto_start_vision, daemon=True).start()
    except Exception as e:
        print(f"⚠️  Vision auto-start fehlgeschlagen: {e}")


# ─── Direkt ausführen ─────────────────────────────────────────────────
if __name__ == "__main__":
    from pathlib import Path
    cert_dir = Path(__file__).parent.parent / "certs"
    uvicorn.run(
        "backend.main:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        ssl_keyfile=str(cert_dir / "server.key"),
        ssl_certfile=str(cert_dir / "server.crt"),
        reload=True,
    )
