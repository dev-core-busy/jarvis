"""Jarvis FastAPI Server – Haupt-Einstiegspunkt."""

import asyncio
import hashlib
import hmac
import json
import subprocess
import time
import uuid
from pathlib import Path

import httpx

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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from fastapi.middleware.cors import CORSMiddleware

from backend.config import config
from backend.security import get_certificate_path

# ─── App erstellen ────────────────────────────────────────────────────
JARVIS_VERSION = "0.9.0"
app = FastAPI(title="Jarvis", version=JARVIS_VERSION)

# ─── CORS: Nur Same-Origin und explizit konfigurierte Domains erlauben ──
_cors_origins = [
    f"https://{os.getenv('SERVER_IP', '127.0.0.1')}",
    f"https://{os.getenv('SERVER_IP', '127.0.0.1')}:{config.SERVER_PORT}",
]
# Zusätzliche CORS-Origins aus Settings laden (z.B. Tailscale-Hostname)
_extra_origins = config.get_setting("cors_origins", "")
if _extra_origins:
    _cors_origins.extend(o.strip() for o in _extra_origins.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD",
                   "PROPFIND", "PROPPATCH", "MKCOL", "COPY", "MOVE", "LOCK", "UNLOCK"],
    allow_headers=["*"],
)

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


# ─── PWA Root-Dateien (müssen unter / erreichbar sein, nicht /static/) ───
@app.get("/manifest.json", include_in_schema=False)
async def pwa_manifest():
    f = FRONTEND_DIR / "manifest.json"
    if not f.exists():
        raise HTTPException(status_code=404)
    from fastapi.responses import FileResponse
    return FileResponse(str(f), media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@app.get("/sw.js", include_in_schema=False)
async def pwa_service_worker():
    f = FRONTEND_DIR / "sw.js"
    if not f.exists():
        raise HTTPException(status_code=404)
    from fastapi.responses import FileResponse
    return FileResponse(str(f), media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})

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
    # Auth: Token als Query-Parameter prüfen (WebSocket kann keine Header setzen)
    token = websocket.query_params.get("token", "")
    _vnc_user = verify_token(token)
    if not _vnc_user:
        await websocket.close(code=4001, reason="Nicht authentifiziert")
        return
    if _user_must_change(_vnc_user):
        await websocket.close(code=4003, reason="Kennwort muss zuerst geaendert werden")
        return

    # Subprotocol nur setzen wenn Client es anbietet (noVNC kann "binary" senden oder nicht)
    requested = websocket.headers.get("sec-websocket-protocol", "")
    subproto = "binary" if "binary" in requested else None
    await websocket.accept(subprotocol=subproto)

    try:
        reader, writer = await asyncio.open_connection("localhost", 5900)
    except (ConnectionRefusedError, OSError):
        await websocket.close(code=1011, reason="VNC nicht erreichbar")
        return

    # Desktop-Sperre beim VNC-Connect automatisch aufheben
    asyncio.create_task(asyncio.to_thread(_unlock_desktop_screen))

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


def _unlock_desktop_screen(target_user: str = "jarvis") -> None:
    """Bildschirmschoner/Sperre fuer den Desktop-Benutzer deaktivieren.
    Wird beim VNC-Connect und bei Session-Wechsel aufgerufen.

    Strategie (von zuverlässig nach aufwändig):
    1. loginctl unlock-sessions  → systemd/PAM-Standard für alle Sessions
    2. pkill cinnamon-screensaver → prozessbasiert, funktioniert ohne D-Bus
    3. Aktiven Session-User auf Display :0 dynamisch ermitteln
    4. D-Bus screensaver-Befehl als dieser User
    5. DPMS aufwecken mit korrekter XAUTHORITY
    """
    # Bekannte X-Auth-Datei fuer Display :0 (lightdm setzt diese)
    _XAUTH = "/var/run/lightdm/root/:0"
    _xenv  = {"DISPLAY": ":0", "XAUTHORITY": _XAUTH}

    try:
        # ── 1. systemd loginctl ────────────────────────────────────────────────
        subprocess.run(["loginctl", "unlock-sessions"], capture_output=True, timeout=5)

        # ── 2. Screensaver-Prozess direkt beenden (zuverlässigste Methode) ─────
        subprocess.run(["pkill", "-f", "cinnamon-screensaver"], capture_output=True, timeout=5)
        subprocess.run(["pkill", "-f", "xscreensaver"],         capture_output=True, timeout=5)
        subprocess.run(["pkill", "-f", "gnome-screensaver"],    capture_output=True, timeout=5)

        # ── 3. Aktiven Session-User auf :0 ermitteln ───────────────────────────
        uid  = None
        user = None
        try:
            # `who` liefert z.B.: "andreas seat0  2026-04-28 09:00 (:0)"
            who = subprocess.run(["who"], capture_output=True, text=True, timeout=5)
            for line in who.stdout.splitlines():
                if "(:0)" in line or "(:0." in line:
                    user = line.split()[0]
                    break
            # loginctl als Fallback: erste Seat0-Session die kein Greeter ist
            if not user:
                sess = subprocess.run(
                    ["loginctl", "list-sessions", "--no-legend"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in sess.stdout.splitlines():
                    parts = line.split()
                    # Format: SESSION UID USER SEAT CLASS ...
                    if len(parts) >= 5 and parts[3] == "seat0" and parts[4] != "greeter" and parts[2] not in ("lightdm", "root", ""):
                        user = parts[2]
                        uid  = parts[1]
                        break
            if user and not uid:
                uid_r = subprocess.run(["id", "-u", user], capture_output=True, text=True, timeout=5)
                uid = uid_r.stdout.strip() or None
        except Exception:
            pass

        # Fallback auf target_user wenn kein aktiver User gefunden
        if not uid:
            import pwd as _pwd
            try:
                uid  = str(_pwd.getpwnam(target_user).pw_uid)
                user = target_user
            except KeyError:
                uid  = "1001"
                user = target_user

        # ── 4. D-Bus Screensaver-Kommando als Session-User ─────────────────────
        dbus_sock = f"/run/user/{uid}/bus"
        if Path(dbus_sock).exists():
            dbus_env = {**_xenv, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={dbus_sock}", "HOME": f"/home/{user}"}
            subprocess.run(
                ["sudo", "-u", f"#{uid}", "cinnamon-screensaver-command", "--deactivate"],
                env=dbus_env, capture_output=True, timeout=5,
            )
            subprocess.run(
                ["sudo", "-u", f"#{uid}", "xdg-screensaver", "reset"],
                env=dbus_env, capture_output=True, timeout=3,
            )

        # ── 5. DPMS aufwecken UND Blanking dauerhaft deaktivieren ──────────────
        #    "force on" weckt nur einmalig; bei ferngesteuertem Desktop zusaetzlich
        #    Screensaver/DPMS komplett abschalten, damit nichts wieder blankt
        #    (verhindert auch das DPMS-bedingte "Redscreen" bei VNC-Fullscreen).
        subprocess.run(["xset", "-display", ":0", "dpms", "force", "on"], env=_xenv, capture_output=True, timeout=5)
        subprocess.run(["xset", "-display", ":0", "s", "reset"],          env=_xenv, capture_output=True, timeout=5)
        subprocess.run(["xset", "-display", ":0", "s", "off"],            env=_xenv, capture_output=True, timeout=5)
        subprocess.run(["xset", "-display", ":0", "s", "noblank"],        env=_xenv, capture_output=True, timeout=5)
        subprocess.run(["xset", "-display", ":0", "-dpms"],               env=_xenv, capture_output=True, timeout=5)

        # ── 6. Greeter-Fall: kein aktiver User auf :0 → jarvis einloggen ──────
        # Pruefen ob Greeter laeuft (kein normaler User auf :0)
        who2 = subprocess.run(["who"], capture_output=True, text=True, timeout=5)
        display_users = [
            line.split()[0] for line in who2.stdout.splitlines()
            if "(:0)" in line or "(:0." in line
        ]
        # Wenn niemand oder nur lightdm auf :0 → Greeter zeigt → jarvis einloggen
        if not display_users or all(u in ("lightdm", "root") for u in display_users):
            print("[VNC] Greeter aktiv – setze Autologin auf jarvis und starte Session.", flush=True)
            _AUTOLOGIN_CONF = "/etc/lightdm/lightdm.conf.d/50-jarvis-autologin.conf"
            try:
                import os as _os
                _os.makedirs(_os.path.dirname(_AUTOLOGIN_CONF), exist_ok=True)
                with open(_AUTOLOGIN_CONF, "w") as _f:
                    _f.write("[Seat:*]\nautologin-user=jarvis\nautologin-user-timeout=0\n")
            except Exception as _e:
                print(f"[VNC] Autologin-Datei schreiben fehlgeschlagen: {_e}", flush=True)
            # dm-tool: jarvis-Session direkt starten (kein LightDM-Neustart noetig)
            subprocess.run(["dm-tool", "switch-to-user", "jarvis"], capture_output=True, timeout=10)
            print("[VNC] dm-tool switch-to-user jarvis ausgefuehrt.", flush=True)
        else:
            print(f"[VNC] Bildschirmsperre aufgehoben (user={user}, uid={uid})", flush=True)

    except Exception as e:
        print(f"[VNC] Screensaver-Unlock Fehler: {e}", flush=True)


# ─── State ────────────────────────────────────────────────────────────
active_sessions: dict[str, WebSocket] = {}
agent_instance = None  # wird lazy initialisiert (Kompatibilitaet)
agent_manager = None  # AgentManager fuer Multi-Agent Support
# Client-Typ pro WebSocket-Verbindung
# Schlüssel: id(ws), Wert: "browser" | "windows_desktop" | "android"
_ws_client_types: dict[int, str] = {}
# Authentifizierter Benutzer pro WebSocket-Verbindung
_ws_usernames: dict[int, str] = {}
# Alle aktiven WebSocket-Verbindungen (für Broadcasts)
_active_ws: set = set()

# ─── User-Chat State ──────────────────────────────────────────────────
# Username → Liste aktiver WebSocket-Verbindungen (mehrere Tabs möglich)
_uc_clients: dict[str, list[WebSocket]] = {}

# Nachrichten-Historie: conv_key → [msg, ...]
_uc_history: dict[str, list] = {}
_UC_HISTORY_FILE = Path("data/userchat_history.json")
_UC_HISTORY_MAX  = 200   # max. Nachrichten pro Konversation

def _uc_conv_key(u1: str, u2: str) -> str:
    """Eindeutiger Konversations-Schlüssel (alphabetisch sortiert)."""
    return "__".join(sorted([u1, u2]))

def _uc_load_history():
    """Lädt die Nachrichten-Historie aus der JSON-Datei."""
    if _UC_HISTORY_FILE.exists():
        try:
            raw = json.loads(_UC_HISTORY_FILE.read_text(encoding="utf-8"))
            _uc_history.clear()
            for k, v in raw.items():
                _uc_history[k] = v
        except Exception as e:
            print(f"⚠️  userchat_history laden fehlgeschlagen: {e}")

def _uc_save_history():
    """Speichert die Nachrichten-Historie in die JSON-Datei."""
    try:
        _UC_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _UC_HISTORY_FILE.write_text(
            json.dumps(_uc_history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"⚠️  userchat_history speichern fehlgeschlagen: {e}")

async def _uc_send(ws: WebSocket, msg: dict):
    """Sendet eine Nachricht an einen User-Chat-Client (silent bei Fehler)."""
    try:
        await ws.send_json(msg)
    except Exception:
        pass

async def _uc_send_to_user(username: str, msg: dict):
    """Leitet eine Nachricht an alle WebSocket-Verbindungen eines Users weiter."""
    for ws in list(_uc_clients.get(username, [])):
        await _uc_send(ws, msg)

async def _uc_broadcast_presence():
    """Sendet die aktuelle Online-User-Liste an alle verbundenen User-Chat-Clients."""
    users = [{"username": u, "online": True} for u in _uc_clients if _uc_clients[u]]
    msg = {"type": "presence", "users": users}
    for username, conns in list(_uc_clients.items()):
        for ws in list(conns):
            await _uc_send(ws, msg)

def _get_client_type(ws) -> str:
    return _ws_client_types.get(id(ws), "browser")

def _get_ws_username(ws) -> str:
    return _ws_usernames.get(id(ws), "")

# Erlaubte Linux-Benutzer für Web-Login
ALLOWED_USERS = {"jarvis"}

# ─── CPU-Polling (zentralisiert, 1x pro 2s statt pro Client) ─────────
_cached_cpu_percent: float = 0.0

async def _cpu_poll_task():
    """Background-Task: CPU-Auslastung alle 2s aktualisieren."""
    global _cached_cpu_percent
    while True:
        _cached_cpu_percent = await asyncio.to_thread(psutil.cpu_percent, interval=1)
        await asyncio.sleep(2)

@app.on_event("startup")
async def startup_cpu_poll():
    asyncio.create_task(_cpu_poll_task())

# ─── Rate-Limiting (Login-Schutz) ────────────────────────────────────
_login_attempts: dict[str, list[float]] = {}
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 300  # 5 Minuten

def _check_rate_limit(ip: str) -> bool:
    """Prueft ob IP zu viele Login-Versuche hat. True = erlaubt."""
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    # Alte Eintraege entfernen
    attempts = [t for t in attempts if now - t < _LOGIN_WINDOW]
    _login_attempts[ip] = attempts
    return len(attempts) < _LOGIN_MAX_ATTEMPTS

def _record_login_attempt(ip: str):
    """Zeichnet einen Login-Versuch auf."""
    _login_attempts.setdefault(ip, []).append(time.time())

def _wa_bridge_request_safe(path: str) -> dict:
    """Sichere Bridge-Anfrage fuer Health-Check (faengt alle Fehler)."""
    try:
        import urllib.request as _ur
        with _ur.urlopen(f"http://127.0.0.1:3001{path}", timeout=2) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {"error": "nicht erreichbar"}


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
    """Token verifizieren (gültig für 30 Tage). Gibt Benutzername zurück oder None."""
    try:
        username, ts, sig = token.split(":", 2)
        age = time.time() - int(ts)
        if age > 2592000:  # 30 Tage
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


def _group_cn_prefix(group_dn: str) -> str:
    """Baut 'cn=<wert>,' (lowercase) aus einem Gruppen-DN fuer den Praefix-Vergleich
    gegen memberOf-Eintraege. Bewusst KEIN lstrip('cn=') – das entfernt die Zeichen-
    menge {c,n,=} und wuerde z.B. 'cn=network-...' faelschlich zu 'etwork-...'
    verstuemmeln (das 'n' von 'network' faellt mit weg)."""
    g = (group_dn or "").strip().lower()
    if g.startswith("cn="):
        g = g[3:]
    return f"cn={g.split(',')[0]},"


def _norm_login(name: str) -> str:
    """Normalisiert einen Login ODER Listen-Eintrag auf den blossen sAMAccountName:
    entfernt Domain-Praefix (DOMAIN\\user), UPN-Suffix (user@domain) und Whitespace,
    lowercased. WICHTIG: muss auf BEIDE Seiten (eingeloggter User UND konfigurierte
    Allowlist-Eintraege) angewandt werden, sonst matcht 'nexus\\andreas.bender' aus
    der Liste nie gegen den eingeloggten 'andreas.bender'."""
    return (name or "").split("@")[0].split("\\")[-1].strip().lower()


async def require_auth(request: Request) -> str:
    """FastAPI Dependency: Prueft Bearer-Token und gibt Username zurueck.
    Sperrt zusaetzlich den lokalen jarvis-User, solange das Erst-Kennwort nicht
    geaendert wurde (serverseitig erzwungen, NICHT per F5/API umgehbar)."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    username = verify_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    if _user_must_change(username):
        raise HTTPException(status_code=403, detail="Kennwort muss zuerst geaendert werden.")
    return username


async def require_auth_pwchange(request: Request) -> str:
    """Wie require_auth, aber OHNE die must_change-Sperre – nur fuer den
    Kennwort-Aendern-Endpoint (sonst Deadlock)."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    username = verify_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    return username


async def require_local_auth(request: Request) -> str:
    """FastAPI Dependency: Nur lokale Benutzer (ALLOWED_USERS) duerfen Admin-Aktionen ausfuehren."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    username = verify_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    # Lokaler jarvis ODER per Sicherheitseinstellungen freigeschalteter AD-Admin
    if username not in ALLOWED_USERS and not _user_is_admin(username):
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen diese Aktion ausführen (Sicherheit → LDAP → Administratoren).")
    if _user_must_change(username):
        raise HTTPException(status_code=403, detail="Kennwort muss zuerst geaendert werden.")
    return username


async def require_knowledge_editor(request: Request, user: str = Depends(require_auth)) -> str:
    """FastAPI Dependency: Prüft ob der Benutzer Wissen bearbeiten darf.

    Erlaubt wenn:
    - Keine Editor-Einschränkung konfiguriert (bestehende Behavior beibehalten)
    - Lokaler Admin (ALLOWED_USERS)
    - AD-User in ad_knowledge_editors-Benutzerliste
    - AD-User in ad_knowledge_editors_group (wird beim Login gecacht)
    """
    editors_raw = config.get_setting("ad_knowledge_editors", "").strip()
    editors_group = config.get_setting("ad_knowledge_editors_group", "").strip()

    # Keine Einschränkung konfiguriert → alle dürfen (bestehende Behavior bleibt erhalten)
    if not editors_raw and not editors_group:
        return user

    # Lokale Admins immer erlaubt
    if user in ALLOWED_USERS:
        return user

    plain = user.split("@")[0].split("\\")[-1].lower()

    # Benutzerliste (kein LDAP nötig, sofort wirksam)
    if editors_raw:
        allowed_list = {_norm_login(u) for u in editors_raw.split(",") if u.strip()}
        if plain in allowed_list:
            return user
        if not editors_group:
            raise HTTPException(status_code=403,
                detail="Keine Berechtigung zum Bearbeiten von Wissen – Benutzer nicht in Editoren-Liste")

    # Gruppen-Check via Login-Cache
    if editors_group:
        if _knowledge_editor_cache.get(plain, False):
            return user
        raise HTTPException(status_code=403,
            detail="Keine Berechtigung zum Bearbeiten von Wissen – "
                   "nicht in Editor-Gruppe (ggf. neu einloggen für Gruppen-Aktualisierung)")

    raise HTTPException(status_code=403, detail="Keine Berechtigung zum Bearbeiten von Wissen")


async def require_auth_or_query(request: Request) -> str:
    """Auth via Header ODER ?token= Query-Parameter (fuer img/audio Tags)."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    username = verify_token(token)
    if not username:
        token = request.query_params.get("token", "")
        username = verify_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    if _user_must_change(username):
        raise HTTPException(status_code=403, detail="Kennwort muss zuerst geaendert werden.")
    return username


def _mask_key(key: str) -> str:
    """Maskiert einen API-Key fuer sichere Anzeige (nur letzte 4 Zeichen sichtbar)."""
    if not key or len(key) < 8:
        return "***" if key else ""
    return "***" + key[-4:]


def _ad_user_allowed(conn, username: str, base_dn: str) -> bool:
    """Prüft AD-Whitelist nach erfolgreichem Bind.

    Gibt True zurück wenn:
    - Weder Benutzerliste noch Gruppe konfiguriert (alle AD-User erlaubt)
    - Benutzername in ad_allowed_users-Liste
    - User ist Mitglied der ad_allowed_group
    """
    import ldap3

    # Benutzernamen normalisieren (nur den sAMAccountName, ohne Domain-Teil)
    plain = username.split("@")[0].split("\\")[-1].lower()

    # ── Benutzerliste prüfen ──────────────────────────────────────────
    allowed_users_raw = config.get_setting("ad_allowed_users", "")
    if allowed_users_raw.strip():
        allowed = {_norm_login(u) for u in allowed_users_raw.split(",") if u.strip()}
        if plain not in allowed:
            print(f"[AUTH] AD-Whitelist: '{plain}' nicht in erlaubten Benutzern {allowed}", flush=True)
            return False
        print(f"[AUTH] AD-Whitelist: '{plain}' in Benutzerliste – Zugriff erlaubt", flush=True)
        return True

    # ── Gruppen-Filter prüfen ─────────────────────────────────────────
    allowed_group = config.get_setting("ad_allowed_group", "").strip()
    if allowed_group:
        # LDAP-Sonderzeichen escapen (verhindert LDAP-Injection)
        safe_plain = plain.replace("\\", "\\5c").replace("*", "\\2a").replace(
            "(", "\\28").replace(")", "\\29").replace("\x00", "\\00")
        # User-DN über sAMAccountName suchen
        conn.search(
            search_base=base_dn,
            search_filter=f"(sAMAccountName={safe_plain})",
            attributes=["memberOf", "dn"],
        )
        if not conn.entries:
            print(f"[AUTH] AD-Gruppe: User '{plain}' nicht im Directory gefunden", flush=True)
            return False
        member_of = conn.entries[0]["memberOf"].values if "memberOf" in conn.entries[0] else []
        # Vergleich case-insensitiv
        group_lower = allowed_group.lower()
        for g in member_of:
            if g.lower() == group_lower or g.lower().startswith(_group_cn_prefix(allowed_group)):
                print(f"[AUTH] AD-Gruppe: '{plain}' ist Mitglied von '{allowed_group}' – Zugriff erlaubt", flush=True)
                return True
        print(f"[AUTH] AD-Gruppe: '{plain}' NICHT Mitglied von '{allowed_group}' – Zugriff verweigert", flush=True)
        return False

    # ── Keine Einschränkung konfiguriert → alle AD-User erlaubt ──────
    return True


# ─── Wissens-Bearbeitungsrechte ───────────────────────────────────────
# Cache: sAMAccountName (lower) → bool (darf Wissen bearbeiten)
# Wird beim AD-Login befüllt und beim Speichern neuer Editor-Einstellungen geleert.
_knowledge_editor_cache: dict[str, bool] = {}


def _check_knowledge_edit_permission_with_conn(username: str, conn, base_dn: str) -> bool:
    """Prüft ob ein AD-User Wissen bearbeiten darf (nur beim Login aufrufbar – LDAP-Bind aktiv).

    Gibt True zurück wenn:
    - Weder Editoren-Liste noch Editoren-Gruppe konfiguriert (alle dürfen)
    - Benutzername in ad_knowledge_editors-Liste
    - User ist Mitglied der ad_knowledge_editors_group
    """
    editors_raw = config.get_setting("ad_knowledge_editors", "").strip()
    editors_group = config.get_setting("ad_knowledge_editors_group", "").strip()

    # Keine Einschränkung → alle AD-User dürfen Wissen bearbeiten
    if not editors_raw and not editors_group:
        return True

    plain = username.split("@")[0].split("\\")[-1].lower()

    # Benutzerliste prüfen
    if editors_raw:
        allowed = {_norm_login(u) for u in editors_raw.split(",") if u.strip()}
        if plain in allowed:
            return True
        if not editors_group:
            return False  # Liste konfiguriert, User nicht drin, keine Gruppe → Nein

    # Gruppen-Check via LDAP (Bind ist aktiv)
    if editors_group and conn is not None:
        safe_plain = plain.replace("\\", "\\5c").replace("*", "\\2a").replace(
            "(", "\\28").replace(")", "\\29").replace("\x00", "\\00")
        try:
            conn.search(
                search_base=base_dn,
                search_filter=f"(sAMAccountName={safe_plain})",
                attributes=["memberOf"],
            )
            if conn.entries:
                member_of = conn.entries[0]["memberOf"].values if "memberOf" in conn.entries[0] else []
                group_lower = editors_group.lower()
                for g in member_of:
                    if g.lower() == group_lower or g.lower().startswith(_group_cn_prefix(editors_group)):
                        print(f"[AUTH] Knowledge-Editor Gruppe: '{plain}' darf Wissen bearbeiten", flush=True)
                        return True
            print(f"[AUTH] Knowledge-Editor Gruppe: '{plain}' NICHT in Gruppe '{editors_group}'", flush=True)
        except Exception as e:
            print(f"[AUTH] Knowledge-Editor Gruppen-Check Fehler: {e}", flush=True)

    return False


_internet_access_cache: dict[str, bool] = {}
_admin_access_cache: dict[str, bool] = {}


def _check_internet_access_with_conn(username: str, conn, base_dn: str) -> bool:
    """Prüft ob ein AD-User Internet-Abfragen machen darf (nur beim Login – LDAP-Bind aktiv).

    Gibt True zurück wenn: weder Liste noch Gruppe konfiguriert (alle dürfen),
    Benutzer in ad_internet_users-Liste, oder Mitglied der ad_internet_group.
    """
    users_raw = config.get_setting("ad_internet_users", "").strip()
    grp = config.get_setting("ad_internet_group", "").strip()
    if not users_raw and not grp:
        return True

    plain = username.split("@")[0].split("\\")[-1].lower()

    if users_raw:
        allowed = {_norm_login(u) for u in users_raw.split(",") if u.strip()}
        if plain in allowed:
            return True
        if not grp:
            return False

    if grp and conn is not None:
        safe_plain = plain.replace("\\", "\\5c").replace("*", "\\2a").replace(
            "(", "\\28").replace(")", "\\29").replace("\x00", "\\00")
        try:
            conn.search(
                search_base=base_dn,
                search_filter=f"(sAMAccountName={safe_plain})",
                attributes=["memberOf"],
            )
            if conn.entries:
                member_of = conn.entries[0]["memberOf"].values if "memberOf" in conn.entries[0] else []
                group_lower = grp.lower()
                for g in member_of:
                    if g.lower() == group_lower or g.lower().startswith(_group_cn_prefix(grp)):
                        print(f"[AUTH] Internet-Zugang Gruppe: '{plain}' erlaubt", flush=True)
                        return True
            print(f"[AUTH] Internet-Zugang Gruppe: '{plain}' NICHT in Gruppe '{grp}'", flush=True)
        except Exception as e:
            print(f"[AUTH] Internet-Zugang Gruppen-Check Fehler: {e}", flush=True)

    return False


def _user_has_internet_access(user: str) -> bool:
    """Laufzeit-Check: Darf dieser Benutzer Internet-Abfragen machen?

    Lokale/privilegierte User immer. Sonst: keine Einschränkung konfiguriert → alle;
    in ad_internet_users-Liste → ja; Gruppen-Mitgliedschaft via Login-Cache.
    """
    u = (user or "").strip()
    if not u or u in ALLOWED_USERS or u in {"jarvis", "root"}:
        return True
    users_raw = config.get_setting("ad_internet_users", "").strip()
    grp = config.get_setting("ad_internet_group", "").strip()
    if not users_raw and not grp:
        return True
    plain = u.split("@")[0].split("\\")[-1].lower()
    if users_raw:
        allowed = {_norm_login(x) for x in users_raw.split(",") if x.strip()}
        if plain in allowed:
            return True
        if not grp:
            return False
    return _internet_access_cache.get(plain, False)


def _check_admin_with_conn(username: str, conn, base_dn: str) -> bool:
    """Prüft ob ein AD-User Admin-Aktionen ausfuehren darf (nur beim Login – Bind aktiv).

    Gibt True zurück wenn: Benutzer in ad_admins-Liste, oder Mitglied der
    ad_admins_group. Ohne Konfiguration: False (nur lokale Admins).
    """
    users_raw = config.get_setting("ad_admins", "").strip()
    grp = config.get_setting("ad_admins_group", "").strip()
    if not users_raw and not grp:
        return False

    plain = username.split("@")[0].split("\\")[-1].lower()

    if users_raw:
        allowed = {_norm_login(u) for u in users_raw.split(",") if u.strip()}
        if plain in allowed:
            return True
        if not grp:
            return False

    if grp and conn is not None:
        safe_plain = plain.replace("\\", "\\5c").replace("*", "\\2a").replace(
            "(", "\\28").replace(")", "\\29").replace("\x00", "\\00")
        try:
            conn.search(
                search_base=base_dn,
                search_filter=f"(sAMAccountName={safe_plain})",
                attributes=["memberOf"],
            )
            if conn.entries:
                member_of = conn.entries[0]["memberOf"].values if "memberOf" in conn.entries[0] else []
                group_lower = grp.lower()
                for g in member_of:
                    if g.lower() == group_lower or g.lower().startswith(_group_cn_prefix(grp)):
                        print(f"[AUTH] Admin-Recht Gruppe: '{plain}' erlaubt", flush=True)
                        return True
            print(f"[AUTH] Admin-Recht Gruppe: '{plain}' NICHT in Gruppe '{grp}'", flush=True)
        except Exception as e:
            print(f"[AUTH] Admin-Recht Gruppen-Check Fehler: {e}", flush=True)

    return False


def _user_is_admin(user: str) -> bool:
    """Darf dieser Benutzer Admin-Aktionen (Update, Profile, Skills, MCP, …) ausfuehren?

    Lokale Admins (ALLOWED_USERS/jarvis/root) immer. AD-Benutzer nur, wenn in
    ad_admins-Liste oder Mitglied der ad_admins_group (Login-Cache). Ohne
    Konfiguration: KEINE AD-Admins (nur lokal) – bewusst restriktiver Default.
    """
    u = (user or "").strip()
    if not u:
        return False
    if u in ALLOWED_USERS or u in {"jarvis", "root"}:
        return True
    users_raw = config.get_setting("ad_admins", "").strip()
    grp = config.get_setting("ad_admins_group", "").strip()
    if not users_raw and not grp:
        return False
    plain = u.split("@")[0].split("\\")[-1].lower()
    if users_raw:
        allowed = {_norm_login(x) for x in users_raw.split(",") if x.strip()}
        if plain in allowed:
            return True
        if not grp:
            return False
    return _admin_access_cache.get(plain, False)


def authenticate_linux_user(username: str, password: str) -> bool:
    """Authentifiziert einen Benutzer – erst PAM/lokal, dann AD/LDAP (wenn konfiguriert)."""

    # ─── 1. Lokale Authentifizierung (PAM / Docker) – immer zuerst ───
    if username in ALLOWED_USERS:
        local_ok = False
        if _DOCKER_MODE:
            state = _load_auth_state()
            docker_pw = state.get("docker_password", {}).get(username)
            if docker_pw is not None:
                # Gespeichertes Passwort ist SHA-256-Hash
                pw_hash = hashlib.sha256(password.encode()).hexdigest()
                local_ok = hmac.compare_digest(pw_hash, docker_pw)
            else:
                local_ok = password == _JARVIS_PASSWORD
        else:
            local_ok = _pam.authenticate(username, password, service="login")
        if local_ok:
            print(f"[AUTH] Lokaler Login erfolgreich: {username}", flush=True)
            return True
        # Lokaler User bekannt, aber Passwort falsch → kein AD-Versuch
        print(f"[AUTH] Lokaler Login fehlgeschlagen: {username}", flush=True)
        return False

    # ─── 2. Active Directory / LDAP (nur für nicht-lokale User) ──────
    ad_server = config.get_setting("ad_server", "")
    ad_domain = config.get_setting("ad_domain", "")
    if ad_server and ad_domain:
        try:
            import ldap3
            # Benutzername normalisieren: falls kein @ und kein \ enthalten, Domain anhaengen
            bind_user = username
            if "@" not in bind_user and "\\" not in bind_user:
                bind_user = f"{username}@{ad_domain}"
            # Base-DN aus Domain ableiten: firma.local → DC=firma,DC=local
            base_dn = ",".join(f"DC={part}" for part in ad_domain.split("."))
            # TLS verwenden wenn ldaps:// oder StartTLS wenn ldap://
            use_ssl = ad_server.lower().startswith("ldaps://")
            server = ldap3.Server(ad_server, use_ssl=use_ssl, get_info=ldap3.NONE, connect_timeout=5)
            conn = ldap3.Connection(server, user=bind_user, password=password, auto_bind=False)
            # StartTLS bei unverschlüsselten Verbindungen versuchen
            if not use_ssl:
                try:
                    conn.open()
                    conn.start_tls()
                except Exception:
                    pass  # Fallback auf Plain wenn DC kein StartTLS unterstützt
            if conn.bind():
                # Credentials korrekt – Whitelist prüfen + Wissens-Recht cachen
                allowed = _ad_user_allowed(conn, username, base_dn)
                # Wissens-Bearbeitungsrecht während des aktiven Binds ermitteln und cachen
                plain_key = username.split("@")[0].split("\\")[-1].lower()
                _knowledge_editor_cache[plain_key] = _check_knowledge_edit_permission_with_conn(
                    username, conn, base_dn
                )
                _internet_access_cache[plain_key] = _check_internet_access_with_conn(
                    username, conn, base_dn
                )
                _admin_access_cache[plain_key] = _check_admin_with_conn(
                    username, conn, base_dn
                )
                conn.unbind()
                if allowed:
                    print(f"[AUTH] AD-Login erfolgreich: {bind_user}", flush=True)
                    return True
                else:
                    print(f"[AUTH] AD-Login verweigert (Whitelist): {bind_user}", flush=True)
                    return False
            else:
                _desc = conn.result.get('description', 'ungueltige Anmeldedaten')
                print(f"[AUTH] AD-Login fehlgeschlagen: {username} – {_desc}", flush=True)
                return False
        except ImportError:
            print("[AUTH] ldap3 nicht installiert", flush=True)
        except Exception as e:
            err_type = type(e).__name__
            if "LDAPSocketOpen" in err_type or "LDAPSocket" in err_type:
                print(f"[AUTH] AD nicht erreichbar ({ad_server}): {e}", flush=True)
            else:
                print(f"[AUTH] AD Fehler ({err_type}): {e}", flush=True)

    return False


# ─── Auth-State (Kennwort-Änderung / 2FA-Vorbereitung) ───────────────
_AUTH_STATE_FILE = Path(__file__).parent.parent / "data" / "auth_state.json"

def _load_auth_state() -> dict:
    """Lädt den Auth-State aus der JSON-Datei."""
    try:
        if _AUTH_STATE_FILE.exists():
            return json.loads(_AUTH_STATE_FILE.read_text())
    except Exception:
        pass
    return {}

def _save_auth_state(state: dict):
    """Speichert den Auth-State in die JSON-Datei."""
    _AUTH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _AUTH_STATE_FILE.write_text(json.dumps(state, indent=4))

def _get_user_auth_state(username: str) -> dict:
    """Gibt den Auth-State eines Benutzers zurück (Defaults: must_change_password=True)."""
    state = _load_auth_state()
    users = state.get("users", {})
    return users.get(username, {
        "must_change_password": True,
        "totp_enabled": False,
        "totp_secret": None,
    })

def _set_user_auth_state(username: str, updates: dict):
    """Aktualisiert den Auth-State eines Benutzers."""
    state = _load_auth_state()
    if "users" not in state:
        state["users"] = {}
    if username not in state["users"]:
        state["users"][username] = {
            "must_change_password": True,
            "totp_enabled": False,
            "totp_secret": None,
        }
    state["users"][username].update(updates)
    _save_auth_state(state)

def _user_must_change(username: str) -> bool:
    """True, wenn der LOKALE jarvis-Benutzer bei der ersten Anmeldung das Kennwort
    noch aendern muss. Domaenen-/AD-Benutzer: IMMER False (wird NIE erzwungen).
    Dient als serverseitige Sperre – nicht per F5/API umgehbar."""
    if username not in ALLOWED_USERS:
        return False
    return bool(_get_user_auth_state(username).get("must_change_password", True))

def _validate_password_strength(password: str, username: str) -> list[str]:
    """Prüft Kennwort-Stärke (mittlere Sicherheit). Gibt Fehlerliste zurück."""
    import re
    errors = []
    if len(password) < 8:
        errors.append("Mindestens 8 Zeichen erforderlich.")
    if len(password) > 128:
        errors.append("Maximal 128 Zeichen erlaubt.")
    if not re.search(r'[A-Z]', password):
        errors.append("Mindestens ein Großbuchstabe erforderlich.")
    if not re.search(r'[a-z]', password):
        errors.append("Mindestens ein Kleinbuchstabe erforderlich.")
    if not re.search(r'[0-9]', password):
        errors.append("Mindestens eine Ziffer erforderlich.")
    if password.lower() == username.lower():
        errors.append("Kennwort darf nicht mit dem Benutzernamen identisch sein.")
    if password.lower() in ("jarvis", "password", "passwort", "12345678", "123456789"):
        errors.append("Kennwort zu einfach – bitte ein sichereres Kennwort wählen.")
    return errors

def _change_linux_password(username: str, new_password: str) -> bool:
    """Setzt das Linux-Kennwort via chpasswd (läuft als root). Gibt True bei Erfolg zurück."""
    try:
        proc = subprocess.run(
            ['chpasswd'],
            input=f'{username}:{new_password}\n',
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode == 0
    except Exception as e:
        print(f"[AUTH] chpasswd Fehler: {e}", flush=True)
        return False


def switch_desktop_session(username: str):
    """Wechselt die aktive Desktop-Session zum angegebenen Benutzer via LightDM-Autologin."""
    import os
    import sys

    AUTOLOGIN_CONF = "/etc/lightdm/lightdm.conf.d/50-jarvis-autologin.conf"

    def log(msg: str):
        print(msg, flush=True)

    def unlock_screen(target_user):
        """Delegiert an die Modul-Level-Funktion."""
        _unlock_desktop_screen(target_user)

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


@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    """Chat-UI ausliefern (separater Web-Zugang)."""
    chat_file = FRONTEND_DIR / "chat.html"
    return HTMLResponse(
        content=chat_file.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/userchat", response_class=HTMLResponse)
async def userchat_page():
    """User-zu-User-Chat-UI ausliefern."""
    f = FRONTEND_DIR / "userchat.html"
    return HTMLResponse(
        content=f.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/portal", response_class=HTMLResponse)
async def portal_page():
    """Portal-/Startseite fuer Nicht-Admins (Chat / Benutzer-Chat / Support)."""
    f = FRONTEND_DIR / "portal.html"
    return HTMLResponse(
        content=f.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/users/online")
async def get_online_users(user: str = Depends(require_auth)):
    """Gibt Liste der aktuell im User-Chat verbundenen User zurück."""
    users = [u for u, conns in _uc_clients.items() if conns]
    return JSONResponse({"users": users})


@app.websocket("/ws/users")
async def userchat_ws(ws: WebSocket):
    """WebSocket-Endpoint für den User-zu-User-Chat."""
    await ws.accept()
    username: str | None = None
    try:
        # Erste Nachricht muss Auth-Token enthalten
        raw = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
        token_str = raw.get("token", "")
        username = verify_token(token_str)
        if not username:
            await ws.send_json({"type": "error", "message": "Nicht autorisiert"})
            await ws.close()
            return
        if _user_must_change(username):
            await ws.send_json({"type": "error", "message": "Kennwort muss zuerst geaendert werden."})
            await ws.close()
            return

        # Client registrieren
        if username not in _uc_clients:
            _uc_clients[username] = []
        _uc_clients[username].append(ws)

        # Willkommens-Nachricht + aktuelle User-Liste senden
        online_users = [{"username": u, "online": True} for u in _uc_clients if _uc_clients[u]]
        await _uc_send(ws, {"type": "connected", "username": username, "users": online_users})
        # Presence-Update an alle senden
        await _uc_broadcast_presence()

        # Chat-Historie senden: alle Konversationen dieses Users
        user_history: dict[str, list] = {}
        for key, msgs in _uc_history.items():
            parts = key.split("__")
            if username in parts:
                partner = parts[0] if parts[1] == username else parts[1]
                user_history[partner] = msgs
        if user_history:
            await _uc_send(ws, {"type": "history", "conversations": user_history})

        # Nachrichten-Loop
        while True:
            try:
                data = await ws.receive_json()
            except Exception:
                break

            msg_type = data.get("type", "")

            if msg_type == "dm":
                to_user = data.get("to", "")
                text = data.get("text", "").strip()
                raw_atts = data.get("attachments", [])
                if not to_user or (not text and not raw_atts):
                    continue
                # Anhänge validieren (max 5 MB pro Datei, max 5 Anhänge)
                _UC_OK_MIME = {
                    "image/jpeg","image/jpg","image/png","image/gif","image/webp","image/bmp",
                    "audio/wav","audio/mp3","audio/mpeg","audio/ogg","audio/webm","audio/aac",
                    "audio/flac","audio/m4a","audio/x-m4a",
                    "video/mp4","video/webm","video/ogg","video/quicktime",
                    "application/pdf",
                }
                clean_atts = []
                for _a in raw_atts[:5]:
                    _am = (_a.get("mime_type","") or "").strip().lower()
                    _ad = _a.get("data","")
                    _an = _a.get("name","datei")[:80]
                    if _am in _UC_OK_MIME and _ad and len(_ad) <= 7_000_000:  # ~5 MB binary
                        clean_atts.append({"name": _an, "mime_type": _am, "data": _ad})
                msg_id = str(uuid.uuid4())[:8]
                msg = {
                    "type": "dm",
                    "from": username,
                    "to": to_user,
                    "text": text or "",
                    "ts": int(time.time() * 1000),
                    "msg_id": msg_id,
                    "status": "delivered",
                }
                if clean_atts:
                    msg["attachments"] = clean_atts
                # In Historie speichern
                key = _uc_conv_key(username, to_user)
                if key not in _uc_history:
                    _uc_history[key] = []
                _uc_history[key].append(msg)
                if len(_uc_history[key]) > _UC_HISTORY_MAX:
                    _uc_history[key] = _uc_history[key][-_UC_HISTORY_MAX:]
                _uc_save_history()
                # An Empfänger senden (auch wenn offline – erhält Nachricht via Historie)
                await _uc_send_to_user(to_user, msg)
                # Echo an Sender
                await _uc_send(ws, msg)

            elif msg_type == "read":
                # Empfänger hat Nachrichten von `partner` gelesen
                partner = data.get("from", "")
                if not partner:
                    continue
                key = _uc_conv_key(username, partner)
                updated_ids = []
                for m in _uc_history.get(key, []):
                    if (m.get("from") == partner
                            and m.get("to") == username
                            and m.get("status") != "read"):
                        m["status"] = "read"
                        updated_ids.append(m.get("msg_id"))
                if updated_ids:
                    _uc_save_history()
                    # Sender benachrichtigen (Doppel-Haken)
                    await _uc_send_to_user(partner, {
                        "type": "msg_status",
                        "conv_with": username,
                        "status": "read",
                        "msg_ids": updated_ids,
                    })

            elif msg_type == "typing":
                to_user = data.get("to", "")
                if to_user:
                    await _uc_send_to_user(to_user, {"type": "typing", "from": username})

            elif msg_type == "dm_edit":
                # Eigene Nachricht editieren (nur Text). Aenderungen werden
                # an beide Seiten der Konversation gepusht.
                to_user = data.get("to", "")
                msg_id  = data.get("msg_id", "")
                new_text = (data.get("text", "") or "").strip()
                if not to_user or not msg_id or not new_text:
                    continue
                key = _uc_conv_key(username, to_user)
                edited = None
                for m in _uc_history.get(key, []):
                    if m.get("msg_id") == msg_id and m.get("from") == username:
                        m["text"] = new_text[:5000]
                        m["edited_at"] = int(time.time() * 1000)
                        edited = m
                        break
                if not edited:
                    continue
                _uc_save_history()
                evt = {
                    "type": "dm_edit",
                    "msg_id": msg_id,
                    "from": username,
                    "to":   to_user,
                    "text": edited["text"],
                    "edited_at": edited["edited_at"],
                }
                await _uc_send_to_user(to_user, evt)
                await _uc_send(ws, evt)

            elif msg_type == "dm_delete":
                # Eigene Nachricht loeschen. Beide Seiten erhalten das Event;
                # Anhaenge werden mitentfernt.
                to_user = data.get("to", "")
                msg_id  = data.get("msg_id", "")
                if not to_user or not msg_id:
                    continue
                key = _uc_conv_key(username, to_user)
                removed_msg = None
                if key in _uc_history:
                    new_list = []
                    for m in _uc_history[key]:
                        if m.get("msg_id") == msg_id and m.get("from") == username:
                            removed_msg = m
                            continue
                        new_list.append(m)
                    if removed_msg:
                        _uc_history[key] = new_list
                        _uc_save_history()
                if not removed_msg:
                    continue
                evt = {
                    "type": "dm_delete",
                    "msg_id": msg_id,
                    "from": username,
                    "to":   to_user,
                }
                await _uc_send_to_user(to_user, evt)
                await _uc_send(ws, evt)

            elif msg_type == "reaction":
                to_user = data.get("to", "")
                msg_id  = data.get("msg_id", "")
                emoji   = data.get("emoji", "")
                if not to_user or not msg_id or not emoji or len(emoji) > 12:
                    continue
                key = _uc_conv_key(username, to_user)
                removed = False
                for m in _uc_history.get(key, []):
                    if m.get("msg_id") == msg_id:
                        if "reactions" not in m:
                            m["reactions"] = {}
                        if emoji not in m["reactions"]:
                            m["reactions"][emoji] = []
                        if username in m["reactions"][emoji]:
                            m["reactions"][emoji].remove(username)
                            removed = True
                            if not m["reactions"][emoji]:
                                del m["reactions"][emoji]
                        else:
                            m["reactions"][emoji].append(username)
                        break
                _uc_save_history()
                rxn_msg = {
                    "type": "reaction",
                    "msg_id": msg_id,
                    "emoji": emoji,
                    "from": username,
                    "removed": removed,
                }
                await _uc_send_to_user(to_user, rxn_msg)
                await _uc_send(ws, rxn_msg)  # Echo an Sender

    except asyncio.TimeoutError:
        pass
    except Exception:
        pass
    finally:
        # Client sauber entfernen
        if username and username in _uc_clients:
            try:
                _uc_clients[username].remove(ws)
            except ValueError:
                pass
            if not _uc_clients[username]:
                del _uc_clients[username]
        await _uc_broadcast_presence()


@app.post("/api/login")
async def login(request: Request):
    """Multi-User Login via Linux PAM → Token + Desktop-Session-Wechsel."""
    client_ip = request.client.host if request.client else "unknown"

    # Rate-Limiting
    if not _check_rate_limit(client_ip):
        return JSONResponse(
            {"success": False, "error": "Zu viele Login-Versuche. Bitte warte 5 Minuten."},
            status_code=429,
        )

    body = await request.json()
    username = body.get("username", "").strip().lower()
    password = body.get("password", "")

    if not username or not password:
        return JSONResponse(
            {"success": False, "error": "Benutzername und Passwort erforderlich"},
            status_code=400,
        )

    # Lokale User (ALLOWED_USERS) immer erlaubt.
    # AD/LDAP-User erlaubt wenn LDAP konfiguriert – authenticate_linux_user() prueft dann Zugriffsrechte.
    _ad_srv = config.get_setting("ad_server", "")
    _ad_dom = config.get_setting("ad_domain", "")
    if username not in ALLOWED_USERS and not (_ad_srv and _ad_dom):
        _record_login_attempt(client_ip)
        print(f"[AUTH] Anmeldung verweigert (kein LDAP, nicht in ALLOWED_USERS): {username}", flush=True)
        return JSONResponse(
            {"success": False, "error": "Benutzername oder Passwort falsch"},
            status_code=401,
        )

    if not authenticate_linux_user(username, password):
        _record_login_attempt(client_ip)
        return JSONResponse(
            {"success": False, "error": "Benutzername oder Passwort falsch"},
            status_code=401,
        )

    user_state = _get_user_auth_state(username)
    # Nur der lokale jarvis-Benutzer muss bei der ersten Anmeldung aendern;
    # Domaenen-/AD-Benutzer NIEMALS.
    must_change = _user_must_change(username)

    # 2FA aktiviert? → TOTP-Code prüfen
    if user_state.get("totp_enabled") and user_state.get("totp_secret"):
        totp_code = body.get("totp_code", "").strip()
        if not totp_code:
            # Passwort korrekt, aber 2FA-Code fehlt → Frontend zeigt TOTP-Eingabe
            return JSONResponse({"success": False, "requires_totp": True,
                                 "error": "2FA-Code erforderlich"})
        import pyotp
        totp = pyotp.TOTP(user_state["totp_secret"])
        if not totp.verify(totp_code, valid_window=1):
            _record_login_attempt(client_ip)
            return JSONResponse(
                {"success": False, "requires_totp": True,
                 "error": "Ungültiger 2FA-Code"},
                status_code=401,
            )

    token = generate_token(username)
    # Desktop-Session im Hintergrund wechseln (nur im Nicht-Docker-Modus)
    if not _DOCKER_MODE:
        asyncio.get_event_loop().run_in_executor(None, switch_desktop_session, username)
    return JSONResponse({"success": True, "token": token, "username": username,
                         "must_change_password": must_change,
                         "is_admin": _is_admin_user(username)})


# ─── 2FA / TOTP (Google Authenticator etc.) ──────────────────────────

@app.get("/api/auth/totp/status")
async def totp_status(username: str = Depends(require_auth)):
    """Gibt zurück ob 2FA für den Benutzer aktiviert ist."""
    user_state = _get_user_auth_state(username)
    return JSONResponse({
        "enabled": bool(user_state.get("totp_enabled")),
    })


@app.post("/api/auth/totp/setup")
async def totp_setup(username: str = Depends(require_auth)):
    """Generiert ein neues TOTP-Secret + QR-Code (Base64 PNG).
    Aktiviert 2FA noch NICHT – erst nach Verifizierung via /totp/verify.
    """
    import pyotp
    import qrcode
    import qrcode.image.pil
    import io
    import base64

    secret = pyotp.random_base32()
    # Provisioning-URI für Google Authenticator / Authy etc.
    totp = pyotp.TOTP(secret)
    # Benutzer-Label: Domain-Prefix entfernen für Übersichtlichkeit
    display_name = username.split("\\")[-1] if "\\" in username else username
    uri = totp.provisioning_uri(name=display_name, issuer_name="Jarvis")

    # QR-Code als Base64-PNG generieren
    img = qrcode.make(uri, image_factory=qrcode.image.pil.PilImage, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    # Secret temporär speichern (noch nicht aktiviert!)
    _set_user_auth_state(username, {"totp_secret": secret, "totp_enabled": False})

    return JSONResponse({
        "secret": secret,
        "qr_code": f"data:image/png;base64,{qr_b64}",
        "uri": uri,
    })


@app.post("/api/auth/totp/verify")
async def totp_verify(request: Request, username: str = Depends(require_auth)):
    """Verifiziert den ersten TOTP-Code und aktiviert 2FA."""
    body = await request.json()
    code = body.get("code", "").strip()
    if not code:
        return JSONResponse({"success": False, "error": "Code erforderlich"}, status_code=400)

    user_state = _get_user_auth_state(username)
    secret = user_state.get("totp_secret")
    if not secret:
        return JSONResponse({"success": False, "error": "Kein TOTP-Setup gefunden"}, status_code=400)

    import pyotp
    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        return JSONResponse({"success": False, "error": "Ungültiger Code"}, status_code=401)

    # 2FA aktivieren
    _set_user_auth_state(username, {"totp_enabled": True})
    return JSONResponse({"success": True, "message": "2FA aktiviert"})


@app.post("/api/auth/totp/disable")
async def totp_disable(request: Request, username: str = Depends(require_auth)):
    """Deaktiviert 2FA. Erfordert aktuelles Passwort zur Bestätigung."""
    body = await request.json()
    password = body.get("password", "")
    if not password:
        return JSONResponse({"success": False, "error": "Passwort zur Bestätigung erforderlich"}, status_code=400)

    if not authenticate_linux_user(username, password):
        return JSONResponse({"success": False, "error": "Falsches Passwort"}, status_code=401)

    _set_user_auth_state(username, {"totp_enabled": False, "totp_secret": None})
    return JSONResponse({"success": True, "message": "2FA deaktiviert"})


@app.post("/api/change-password")
async def change_password(request: Request, username: str = Depends(require_auth_pwchange)):
    """Kennwort ändern – benötigt altes Kennwort zur Verifikation."""
    body = await request.json()
    old_password = body.get("old_password", "")
    new_password = body.get("new_password", "")
    confirm_password = body.get("confirm_password", "")

    if not old_password or not new_password or not confirm_password:
        return JSONResponse({"success": False, "error": "Alle Felder müssen ausgefüllt sein."}, status_code=400)

    if new_password != confirm_password:
        return JSONResponse({"success": False, "error": "Neues Kennwort und Bestätigung stimmen nicht überein."}, status_code=400)

    # Altes Kennwort prüfen
    if not authenticate_linux_user(username, old_password):
        return JSONResponse({"success": False, "error": "Aktuelles Kennwort ist falsch."}, status_code=403)

    # Kennwort-Stärke prüfen
    errors = _validate_password_strength(new_password, username)
    if errors:
        return JSONResponse({"success": False, "error": " ".join(errors)}, status_code=400)

    # Neues Kennwort muss sich vom alten unterscheiden
    if old_password == new_password:
        return JSONResponse({"success": False, "error": "Neues Kennwort muss sich vom aktuellen unterscheiden."}, status_code=400)

    # Kennwort setzen
    if _DOCKER_MODE:
        # Im Docker-Modus: Passwort als SHA-256-Hash in data/auth_state.json speichern
        state = _load_auth_state()
        if "docker_password" not in state:
            state["docker_password"] = {}
        state["docker_password"][username] = hashlib.sha256(new_password.encode()).hexdigest()
        _save_auth_state(state)
        _set_user_auth_state(username, {"must_change_password": False})
        print(f"[AUTH] Docker-Kennwort für '{username}' erfolgreich geändert.", flush=True)
        return JSONResponse({"success": True})

    ok = await asyncio.to_thread(_change_linux_password, username, new_password)
    if not ok:
        return JSONResponse({"success": False, "error": "Kennwort konnte nicht gesetzt werden."}, status_code=500)

    # must_change_password Flag löschen
    _set_user_auth_state(username, {"must_change_password": False})
    print(f"[AUTH] Kennwort für '{username}' erfolgreich geändert.", flush=True)
    return JSONResponse({"success": True})


@app.get("/api/version")
async def get_version():
    """Jarvis-Version für Frontend-Anzeige."""
    return JSONResponse({"version": JARVIS_VERSION})


# ─── Update-System ────────────────────────────────────────────────────────────

@app.get("/api/update/status")
async def update_status(user: str = Depends(require_auth)):
    """Prüft ob eine neue Version im Git-Repository verfügbar ist (git fetch)."""
    from backend.update_manager import check_update
    result = await asyncio.to_thread(check_update)
    result["jarvis_version"] = JARVIS_VERSION
    return JSONResponse(result)


@app.post("/api/update/apply")
async def update_apply(user: str = Depends(require_local_auth)):
    """Führt git pull aus und startet den Service neu."""
    from backend.update_manager import apply_update, restart_service_delayed
    result = await asyncio.to_thread(apply_update)
    if result["ok"]:
        restart_service_delayed(delay_sec=2.0)
    return JSONResponse(result)


@app.get("/api/update/settings")
async def update_settings_get(user: str = Depends(require_auth)):
    """Gibt Auto-Update-Einstellungen zurück."""
    auto_schedule = config.get_setting("auto_update_schedule", "never")
    return JSONResponse({"auto_update_schedule": auto_schedule})


@app.post("/api/update/settings")
async def update_settings_set(request: Request, user: str = Depends(require_local_auth)):
    """Speichert Auto-Update-Einstellungen und legt ggf. Cron-Job an."""
    body    = await request.json()
    schedule = body.get("auto_update_schedule", "never")

    VALID = {"never", "daily", "weekly"}
    if schedule not in VALID:
        return JSONResponse({"error": "Ungültiger Wert"}, status_code=400)

    config.save_setting("auto_update_schedule", schedule)

    # Cron-Job verwalten
    from backend.scheduler import cron_manager
    _AUTO_JOB_ID = "system_auto_update"

    # Alten Job entfernen
    try: cron_manager.delete_job(_AUTO_JOB_ID)
    except Exception: pass

    if schedule != "never":
        cron_expr = "0 3 * * *" if schedule == "daily" else "0 3 * * 1"
        cron_manager.add_job(
            label="Auto-Update (System)",
            cron=cron_expr,
            task=(
                "Führe ein Jarvis-System-Update durch:\n"
                "1. Prüfe ob Updates auf GitHub verfügbar sind\n"
                "2. Falls ja: git pull und Neustart\n"
                "Nutze dafür den shell_execute-Tool mit: "
                "cd /opt/jarvis && git fetch origin && git pull origin master && "
                "systemctl restart jarvis.service"
            ),
            enabled=True,
            job_id=_AUTO_JOB_ID,
        )

    return JSONResponse({"ok": True, "auto_update_schedule": schedule})


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
async def get_mcp_servers(user: str = Depends(require_auth)):
    return JSONResponse(mcp_manager.get_status())

@app.post("/api/mcp/servers")
async def add_mcp_server(request: Request, user: str = Depends(require_local_auth)):
    data = await request.json()
    server = config.add_mcp_server(data)
    if data.get("enabled", True):
        await mcp_manager.connect_server(server["id"])
    return JSONResponse(server)

@app.put("/api/mcp/servers/{server_id}")
async def update_mcp_server(server_id: str, request: Request, user: str = Depends(require_local_auth)):
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
async def remove_mcp_server(server_id: str, user: str = Depends(require_local_auth)):
    await mcp_manager.disconnect_server(server_id)
    if config.remove_mcp_server(server_id):
        return JSONResponse({"ok": True})
    return JSONResponse({"detail": "Server nicht gefunden"}, status_code=404)

@app.post("/api/mcp/servers/{server_id}/toggle")
async def toggle_mcp_server(server_id: str, request: Request, user: str = Depends(require_local_auth)):
    data = await request.json()
    enabled = data.get("enabled", True)
    config.toggle_mcp_server(server_id, enabled)
    if enabled:
        await mcp_manager.connect_server(server_id)
    else:
        await mcp_manager.disconnect_server(server_id)
    return JSONResponse({"ok": True, "enabled": enabled})

@app.post("/api/mcp/servers/{server_id}/reconnect")
async def reconnect_mcp_server(server_id: str, user: str = Depends(require_local_auth)):
    success = await mcp_manager.connect_server(server_id)
    return JSONResponse({"ok": success})


# ─── Telemetry API ─────────────────────────────────────────────────────────
from backend.telemetry import tracer

@app.get("/api/telemetry/stats")
async def get_telemetry_stats(user: str = Depends(require_auth)):
    return JSONResponse(tracer.get_stats())

@app.get("/api/telemetry/spans")
async def get_telemetry_spans(request: Request, user: str = Depends(require_auth)):
    limit = int(request.query_params.get("limit", "50"))
    return JSONResponse(tracer.get_recent_spans(limit))

@app.get("/api/telemetry/errors")
async def get_telemetry_errors(user: str = Depends(require_auth)):
    return JSONResponse(tracer.get_errors())

@app.delete("/api/telemetry")
async def clear_telemetry(user: str = Depends(require_auth)):
    tracer.clear()
    return JSONResponse({"ok": True})


# ─── Konversations-Verlauf ────────────────────────────────────────────────────
from backend.conv_log import get_conversations, get_known_ips, get_known_users, clear as clear_conv_log

@app.get("/api/conv_log")
async def api_conv_log(request: Request, user: str = Depends(require_auth)):
    limit = int(request.query_params.get("limit", "50"))
    ip = request.query_params.get("ip") or None
    username = request.query_params.get("user") or None
    return JSONResponse(get_conversations(limit=limit, ip_filter=ip, user_filter=username))

@app.get("/api/conv_log/ips")
async def api_conv_log_ips(user: str = Depends(require_auth)):
    return JSONResponse(get_known_ips())

@app.get("/api/conv_log/users")
async def api_conv_log_users(user: str = Depends(require_auth)):
    return JSONResponse(get_known_users())

@app.delete("/api/conv_log")
async def api_conv_log_clear(user: str = Depends(require_auth)):
    clear_conv_log()
    return JSONResponse({"ok": True})


@app.get("/api/context/stats")
async def api_context_stats(user: str = Depends(require_auth)):
    """Aktuelle Kontext-Statistiken des Hauptagenten."""
    agent = agent_manager.main_agent
    if not agent:
        return JSONResponse({"history_entries": 0, "compress_threshold": 30,
                             "fills_pct": 0, "session_input_tokens": 0,
                             "session_output_tokens": 0, "session_total_tokens": 0,
                             "estimated_history_tokens": 0, "agent_state": "idle"})
    return JSONResponse(agent.get_context_stats())


@app.post("/api/context/compress")
async def api_context_compress(user: str = Depends(require_auth)):
    """Erzwingt sofortige History-Komprimierung."""
    agent = agent_manager.main_agent
    if not agent:
        return JSONResponse({"error": "Kein aktiver Agent"}, status_code=404)
    result = await agent.force_compress()
    return JSONResponse(result)


@app.post("/api/context/clear")
async def api_context_clear(user: str = Depends(require_auth)):
    """Löscht die Chat-History des aktuellen Benutzers (neues Gespräch)."""
    agent = agent_manager.main_agent
    if not agent:
        return JSONResponse({"ok": True, "cleared": 0})
    history = agent._user_histories.pop(user, [])
    # Falls gerade aktiv: auch live-Referenz leeren
    if agent._current_chat_history is history:
        history.clear()
        agent._current_chat_history = []
    return JSONResponse({"ok": True, "cleared": len(history)})


# ════════════════════════════════════════════════════════════════════════════
# PROTOCOL: truncate_user_msg_index — "Nachricht editieren"-Feature
# ────────────────────────────────────────────────────────────────────────────
# Alle Chat-Clients (Web, Android, Windows) MUESSEN den folgenden Algorithmus
# IDENTISCH umsetzen, damit Backend-History, lokale History und sichtbare UI
# konsistent bleiben:
#
#   1. Index ermitteln: position der editierten Nachricht innerhalb der
#      User-Rollen (0-basiert, nur Rolle=="user" zaehlen).
#   2. UI: alle Nachrichten NACH der editierten Bubble entfernen.
#   3. Lokale History: auf die ersten (userIndex+1) User-Eintraege kuerzen
#      und Text der editierten Nachricht ersetzen.
#   4. WS-Nachricht senden:
#        { "type":"task", "text": neuerText, "token": ...,
#          "truncate_user_msg_index": userIndex, "lang": ... }
#   5. Backend trimmt seine `_user_histories[user]` via
#      `_truncate_history_to_user_index(history, userIndex)` BEVOR die
#      neue (editierte) Frage angehaengt und das LLM erneut aufgerufen wird.
#
# Implementierungen (bei Protokoll-Aenderungen alle synchron halten!):
#   - frontend/js/chatlib.js   :: truncateHistoryToUserIndex + submitEdit
#   - frontend/js/app.js       :: _submitEdit (Hauptseite)
#   - frontend/js/chat.js      :: _submitEdit (Chat-Standalone / PWA)
#   - windows-app-go/chat.go   :: editUserMessageAt
#   - windows-app-go/ws_client.go :: SendTaskWithTruncate
#   - android/.../ChatRepository.kt :: editUserMessage
#   - android/.../JarvisWebSocket.kt :: sendTaskWithTruncate
# ════════════════════════════════════════════════════════════════════════════
def _truncate_history_to_user_index(history: list, keep_user_count: int) -> int:
    """
    Trimmt die Chat-History des Backends so, dass die ersten `keep_user_count`
    User-Nachrichten (inkl. ihrer Antworten) erhalten bleiben und alles danach
    entfernt wird.

    Beispiel:
        history = [user0, model0, user1, model1, user2, model2]
        keep_user_count = 1 → [user0, model0]
        keep_user_count = 2 → [user0, model0, user1, model1]
        keep_user_count = 0 → []  (alles löschen)

    Rückgabe: Anzahl der entfernten Einträge.
    """
    if not history or keep_user_count < 0:
        return 0
    user_seen = 0
    cut_at = len(history)
    for idx, entry in enumerate(history):
        role = getattr(entry, "role", None)
        if role == "user":
            if user_seen == keep_user_count:
                cut_at = idx
                break
            user_seen += 1
    removed = len(history) - cut_at
    if removed > 0:
        del history[cut_at:]
    return removed


@app.post("/api/context/truncate")
async def api_context_truncate(request: Request, user: str = Depends(require_auth)):
    """
    Trimmt die Chat-History des Users auf die ersten N User-Nachrichten.
    Wird für das 'Nachricht editieren'-Feature genutzt: bevor die editierte
    Frage gesendet wird, löscht der Client alles ab dem Edit-Punkt.

    Body: { "keep_user_count": int }
    """
    body = await request.json()
    keep = int(body.get("keep_user_count", 0))
    agent = agent_manager.main_agent
    if not agent:
        return JSONResponse({"ok": True, "removed": 0, "remaining": 0})
    history = agent._user_histories.get(user)
    if history is None:
        return JSONResponse({"ok": True, "removed": 0, "remaining": 0})
    removed = _truncate_history_to_user_index(history, keep)
    return JSONResponse({"ok": True, "removed": removed, "remaining": len(history)})


@app.post("/api/context/threshold")
async def api_context_threshold(request: Request, user: str = Depends(require_auth)):
    """Setzt den Komprimierungs-Schwellwert (Anzahl History-Einträge)."""
    body = await request.json()
    threshold = int(body.get("threshold", 30))
    threshold = max(4, min(200, threshold))
    # Auf laufenden Agenten anwenden
    agent = agent_manager.main_agent
    if agent:
        agent._compress_threshold = threshold
    # Persistieren
    config.save_setting("compress_threshold", threshold)
    return JSONResponse({"threshold": threshold, "ok": True})


@app.post("/api/system/restart")
async def system_restart(user: str = Depends(require_local_auth)):
    """Startet den Jarvis-Dienst neu (via systemctl)."""
    import subprocess, threading
    def _do_restart():
        import time; time.sleep(1)
        subprocess.run(["systemctl", "restart", "jarvis.service"], check=False)
    threading.Thread(target=_do_restart, daemon=True).start()
    return JSONResponse({"ok": True, "message": "Neustart eingeleitet"})


def _check_vnc_available() -> bool:
    """Prüft ob x11vnc auf Port 5900 erreichbar ist (schneller TCP-Connect)."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(("localhost", 5900))
        s.close()
        return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


@app.post("/api/vnc/unlock")
async def vnc_unlock(user: str = Depends(require_auth)):
    """Desktop-Sperre manuell aufheben (Screensaver deaktivieren)."""
    await asyncio.to_thread(_unlock_desktop_screen)
    return JSONResponse({"ok": True})


@app.get("/api/config")
async def get_config():
    """Öffentliche Konfiguration für Frontend."""
    vnc_ok = await asyncio.get_event_loop().run_in_executor(None, _check_vnc_available)
    return JSONResponse({
        "websockify_port": config.WEBSOCKIFY_PORT,
        "vnc_available": vnc_ok,
    })


def _is_admin_user(username: str) -> bool:
    """True fuer lokalen jarvis (ALLOWED_USERS) oder freigeschaltete AD-Admins."""
    return (username in ALLOWED_USERS) or _user_is_admin(username)


@app.get("/api/me")
async def get_me(user: str = Depends(require_auth)):
    """Gibt den aktuell angemeldeten Benutzernamen zurueck (fuer Titelleisten-Anzeige)."""
    return JSONResponse({"username": user, "is_admin": _is_admin_user(user)})
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


@app.get("/api/generated/{name}")
async def get_generated_image(name: str):
    """Liefert ein generiertes/gesuchtes Bild aus.

    Auth via Capability-URL: der Dateiname ist ein nicht erratbarer 32-stelliger
    Hex-UUID. So funktionieren <img>-Tags in allen Frontends ohne Token-Handling.
    """
    _MEDIA = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
              "gif": "image/gif", "webp": "image/webp"}
    stem, _, ext = name.rpartition(".")
    ext = ext.lower()
    if ext not in _MEDIA or not (len(stem) == 32 and all(c in "0123456789abcdef" for c in stem)):
        return JSONResponse({"error": "ungueltiger Name"}, status_code=400)
    p = Path(__file__).parent.parent / "data" / "generated_images" / name
    if not p.exists():
        return JSONResponse({"error": "nicht gefunden"}, status_code=404)
    return FileResponse(str(p), media_type=_MEDIA[ext],
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/documents/{name}")
async def get_document(name: str):
    """Liefert ein erzeugtes Office-Dokument aus (Office-Skill).

    Auth via Capability-URL: der Name hat das Schema <32-Hex>__<Basis>.<ext>.
    Der Download traegt den lesbaren Originalnamen (Content-Disposition).
    """
    import re
    _MEDIA = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pdf":  "application/pdf",
    }
    m = re.fullmatch(r"([0-9a-f]{32})__([A-Za-z0-9_\-]+)\.(docx|xlsx|pptx|pdf)", name)
    if not m:
        return JSONResponse({"error": "ungueltiger Name"}, status_code=400)
    base, ext = m.group(2), m.group(3)
    p = Path(__file__).parent.parent / "data" / "documents" / name
    if not p.exists():
        return JSONResponse({"error": "nicht gefunden"}, status_code=404)
    return FileResponse(str(p), media_type=_MEDIA[ext],
                        filename=f"{base}.{ext}",
                        headers={"Cache-Control": "private, max-age=3600"})


# ─── Geteilte Anzeige-History (Hauptfenster + jarvis/chat teilen denselben Verlauf) ───
async def _broadcast_shared_history(user: str, payload: dict):
    """Sendet ein Shared-History-Event an ALLE /ws-Verbindungen dieses Benutzers
    (Live-Sync zwischen Hauptfenster und /chat ohne Neuladen). Das Ursprungs-
    Fenster ignoriert sein eigenes Event anhand der mitgesendeten client_id."""
    for w in list(_active_ws):
        try:
            if _ws_usernames.get(id(w)) == user:
                await w.send_json(payload)
        except Exception:
            pass


@app.get("/api/chat/shared-history")
async def chat_history_get(user: str = Depends(require_auth)):
    import backend.chat_history as ch
    return JSONResponse({"messages": ch.load(user)})


@app.post("/api/chat/shared-history/append")
async def chat_history_append(request: Request, user: str = Depends(require_auth)):
    import backend.chat_history as ch
    body = await request.json()
    msg = body.get("message")
    result = ch.append(user, msg)
    # Live-Sync: die neue Nachricht an die anderen Fenster desselben Benutzers pushen
    if msg:
        await _broadcast_shared_history(user, {
            "type": "shared_history_append",
            "message": msg,
            "origin": body.get("client_id", ""),
        })
    return JSONResponse({"messages": result})


@app.put("/api/chat/shared-history")
async def chat_history_replace(request: Request, user: str = Depends(require_auth)):
    import backend.chat_history as ch
    body = await request.json()
    msgs = body.get("messages", [])
    return JSONResponse({"messages": ch.replace(user, msgs)})


@app.delete("/api/chat/shared-history")
async def chat_history_clear(user: str = Depends(require_auth)):
    import backend.chat_history as ch
    ch.clear(user)
    return JSONResponse({"ok": True})


@app.get("/api/settings")
async def get_settings(user: str = Depends(require_auth)):
    """Gibt aktuelle Einstellungen, Profile und Provider-Optionen zurück."""
    # API-Keys maskiert zurueckgeben
    safe_profiles = []
    for p in config.profiles:
        sp = {**p, "api_key": _mask_key(p.get("api_key", "")),
              "session_key": _mask_key(p.get("session_key", ""))}
        safe_profiles.append(sp)
    return JSONResponse({
        "active_profile_id": config.active_profile_id,
        "profiles": safe_profiles,
        "tts_enabled": config.TTS_ENABLED,
        "tts_voice": config.TTS_VOICE,
        "use_physical_desktop": config.USE_PHYSICAL_DESKTOP,
        "agent_api_key": _mask_key(config.AGENT_API_KEY),
        "defaults": config.DEFAULT_PROVIDERS,
    })


@app.post("/api/settings")
async def save_settings(request: Request, user: str = Depends(require_local_auth)):
    """Speichert globale Einstellungen (TTS, Desktop, AD-Config etc.)."""
    body = await request.json()
    config.save_global_settings(body)
    # AD-Konfiguration separat persistieren
    if "ad_server" in body:
        config.save_setting("ad_server", body["ad_server"])
    if "ad_domain" in body:
        config.save_setting("ad_domain", body["ad_domain"])
    if "ad_allowed_users" in body:
        config.save_setting("ad_allowed_users", body["ad_allowed_users"])
    if "ad_allowed_group" in body:
        config.save_setting("ad_allowed_group", body["ad_allowed_group"])
    if "ad_knowledge_editors" in body:
        config.save_setting("ad_knowledge_editors", body["ad_knowledge_editors"])
        _knowledge_editor_cache.clear()  # Cache leeren → Benutzer müssen sich für Gruppenprüfung neu einloggen
    if "ad_knowledge_editors_group" in body:
        config.save_setting("ad_knowledge_editors_group", body["ad_knowledge_editors_group"])
        _knowledge_editor_cache.clear()
    if "ad_internet_users" in body:
        config.save_setting("ad_internet_users", body["ad_internet_users"])
        _internet_access_cache.clear()
    if "ad_internet_group" in body:
        config.save_setting("ad_internet_group", body["ad_internet_group"])
        _internet_access_cache.clear()
    if "ad_admins" in body:
        config.save_setting("ad_admins", body["ad_admins"])
        _admin_access_cache.clear()
    if "ad_admins_group" in body:
        config.save_setting("ad_admins_group", body["ad_admins_group"])
        _admin_access_cache.clear()
    return JSONResponse({"success": True})


@app.post("/api/auth/ad_test")
async def test_ad_connection(request: Request, _username: str = Depends(require_auth)):
    """Prüft ob der Domain-Controller erreichbar ist (reiner Verbindungstest, kein Bind)."""
    body = await request.json()
    ad_server = body.get("ad_server", "").strip()
    ad_domain = body.get("ad_domain", "").strip()
    if not ad_server or not ad_domain:
        return JSONResponse({"reachable": False, "error": "Server und Domain erforderlich"})
    try:
        import ldap3
        server = ldap3.Server(ad_server, get_info=ldap3.NONE, connect_timeout=5)
        conn = ldap3.Connection(server, auto_bind=False)
        conn.open()
        conn.closed
        return JSONResponse({"reachable": True})
    except ImportError:
        return JSONResponse({"reachable": False, "error": "ldap3 nicht installiert"})
    except Exception as e:
        return JSONResponse({"reachable": False, "error": str(e)})


@app.get("/api/auth/ad_status")
async def get_ad_status(user: str = Depends(require_auth)):
    """Gibt den aktuellen AD/LDAP-Konfigurationsstatus zurueck."""
    ad_server = config.get_setting("ad_server", "")
    ad_domain = config.get_setting("ad_domain", "")
    allowed_users = config.get_setting("ad_allowed_users", "")
    allowed_group = config.get_setting("ad_allowed_group", "")
    knowledge_editors = config.get_setting("ad_knowledge_editors", "")
    knowledge_editors_group = config.get_setting("ad_knowledge_editors_group", "")
    return JSONResponse({
        "configured": bool(ad_server and ad_domain),
        "server": ad_server,
        "domain": ad_domain,
        "allowed_users": allowed_users,
        "allowed_group": allowed_group,
        "access_mode": (
            "group"   if allowed_group else
            "users"   if allowed_users else
            "open"    # alle AD-User erlaubt
        ),
        "knowledge_editors": knowledge_editors,
        "knowledge_editors_group": knowledge_editors_group,
        "knowledge_edit_mode": (
            "group"     if knowledge_editors_group else
            "users"     if knowledge_editors else
            "all"       # alle authentifizierten Benutzer dürfen
        ),
        "internet_users": config.get_setting("ad_internet_users", ""),
        "internet_group": config.get_setting("ad_internet_group", ""),
        "internet_mode": (
            "group"     if config.get_setting("ad_internet_group", "") else
            "users"     if config.get_setting("ad_internet_users", "") else
            "all"       # alle Benutzer haben Internet-Zugang
        ),
        "admins": config.get_setting("ad_admins", ""),
        "admins_group": config.get_setting("ad_admins_group", ""),
        "admin_mode": (
            "group"     if config.get_setting("ad_admins_group", "") else
            "users"     if config.get_setting("ad_admins", "") else
            "none"      # nur lokaler jarvis
        ),
    })


# ─── SSL / Let's Encrypt Endpoints ────────────────────────────────────
@app.get("/api/settings/ssl")
async def get_ssl_info(user: str = Depends(require_auth)):
    """Gibt aktuelle SSL-Zertifikat-Infos zurück: Domain, Ablaufdatum, Is-Let's-Encrypt."""
    import ssl as _ssl
    import datetime

    # Prüfen ob Let's Encrypt Zertifikat aktiv ist
    le_live_dir = Path("/etc/letsencrypt/live")
    is_letsencrypt = False
    domain = ""
    expiry = ""

    # Aktuell verwendete Zertifikatspfade ermitteln
    cert_file = Path("/opt/jarvis/certs/server.crt")
    if not cert_file.exists():
        cert_file = Path(__file__).parent.parent / "certs" / "server.crt"

    try:
        # Prüfen ob cert ein Symlink auf letsencrypt ist
        resolved = cert_file.resolve()
        if "letsencrypt" in str(resolved):
            is_letsencrypt = True
            # Domain aus Pfad extrahieren
            parts = resolved.parts
            if "live" in parts:
                idx = parts.index("live")
                if idx + 1 < len(parts):
                    domain = parts[idx + 1]

        # Ablaufdatum aus Zertifikat lesen
        if cert_file.exists():
            cert_bytes = cert_file.read_bytes()
            x509 = _ssl._ssl._test_decode_cert  # type: ignore
            # openssl x509 -noout -enddate nutzen (robuster)
            result = subprocess.run(
                ["openssl", "x509", "-noout", "-enddate", "-subject", "-in", str(cert_file)],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if line.startswith("notAfter="):
                    expiry_str = line.split("=", 1)[1].strip()
                    # Format: "Dec 31 23:59:59 2025 GMT"
                    try:
                        dt = datetime.datetime.strptime(expiry_str, "%b %d %H:%M:%S %Y %Z")
                        expiry = dt.strftime("%d.%m.%Y")
                    except Exception:
                        expiry = expiry_str
                if "CN=" in line and not domain:
                    for part in line.split("/"):
                        if part.startswith("CN="):
                            domain = part[3:].strip()

    except Exception as e:
        pass

    return JSONResponse({
        "is_letsencrypt": is_letsencrypt,
        "domain": domain,
        "expiry": expiry,
        "cert_path": str(cert_file),
    })


@app.post("/api/settings/letsencrypt")
async def request_letsencrypt(request: Request, user: str = Depends(require_local_auth)):
    """Beantragt ein Let's Encrypt Zertifikat via certbot (standalone).
    Streamt den Fortschritt als Textzeilen zurück."""
    body = await request.json()
    domain = body.get("domain", "").strip()
    email = body.get("email", "").strip()

    if not domain or not email:
        return JSONResponse({"error": "Domain und E-Mail erforderlich"}, status_code=400)

    # Einfache Validierung
    import re as _re
    if not _re.match(r'^[a-zA-Z0-9][a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}$', domain):
        return JSONResponse({"error": "Ungültige Domain"}, status_code=400)
    if not _re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return JSONResponse({"error": "Ungültige E-Mail-Adresse"}, status_code=400)

    async def _stream():
        yield f"🔍 Starte Let's Encrypt Zertifikatsanfrage für {domain}...\n"

        # 1. certbot installieren falls nicht vorhanden
        certbot_path = None
        for cp in ["/usr/bin/certbot", "/usr/local/bin/certbot"]:
            if Path(cp).exists():
                certbot_path = cp
                break

        if not certbot_path:
            yield "📦 certbot nicht gefunden – installiere...\n"
            proc = await asyncio.create_subprocess_exec(
                "apt-get", "install", "-y", "certbot",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async for line in proc.stdout:
                yield line.decode(errors="replace")
            await proc.wait()
            if Path("/usr/bin/certbot").exists():
                certbot_path = "/usr/bin/certbot"
                yield "✅ certbot installiert\n"
            else:
                yield "❌ certbot konnte nicht installiert werden\n"
                return

        # 2. Port-80-Redirect pausieren (damit certbot standalone Port 80 nutzen kann)
        yield "⏸️  Pausiere HTTP-Redirect für certbot-Challenge...\n"

        # 3. certbot standalone ausführen
        yield f"🌐 Führe certbot aus: {certbot_path} certonly --standalone -d {domain}\n"
        cmd = [
            certbot_path, "certonly",
            "--standalone",
            "--non-interactive",
            "--agree-tos",
            "-m", email,
            "-d", domain,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for line in proc.stdout:
            yield line.decode(errors="replace")
        rc = await proc.wait()

        if rc != 0:
            yield f"\n❌ certbot fehlgeschlagen (Exit-Code {rc})\n"
            return

        yield "\n✅ Let's Encrypt Zertifikat erfolgreich erhalten!\n"

        # 4. Symlinks in certs/ setzen
        le_fullchain = Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem")
        le_privkey = Path(f"/etc/letsencrypt/live/{domain}/privkey.pem")

        if not le_fullchain.exists() or not le_privkey.exists():
            yield f"❌ Zertifikatsdateien nicht gefunden unter /etc/letsencrypt/live/{domain}/\n"
            return

        for certs_dir in [Path("/opt/jarvis/certs"), Path(__file__).parent.parent / "certs"]:
            certs_dir.mkdir(parents=True, exist_ok=True)
            cert_dst = certs_dir / "server.crt"
            key_dst = certs_dir / "server.key"
            # Backup der alten Zertifikate
            for f in [cert_dst, key_dst]:
                if f.exists() and not f.is_symlink():
                    f.rename(f.with_suffix(".bak"))
            # Symlinks setzen
            try:
                if cert_dst.is_symlink():
                    cert_dst.unlink()
                if key_dst.is_symlink():
                    key_dst.unlink()
                cert_dst.symlink_to(le_fullchain)
                key_dst.symlink_to(le_privkey)
                yield f"🔗 Symlinks gesetzt: {certs_dir}/server.crt → {le_fullchain}\n"
            except Exception as e:
                yield f"⚠️  Symlink-Fehler in {certs_dir}: {e}\n"
                # Fallback: Kopieren
                import shutil
                shutil.copy2(str(le_fullchain), str(cert_dst))
                shutil.copy2(str(le_privkey), str(key_dst))
                os.chmod(str(key_dst), 0o600)
                yield f"📋 Zertifikat kopiert nach {certs_dir}/\n"

        yield "\n✅ Fertig! Bitte starten Sie den Jarvis-Service neu:\n"
        yield "   systemctl restart jarvis.service\n"

    return StreamingResponse(_stream(), media_type="text/plain")


@app.post("/api/settings/ssl/custom")
async def upload_custom_cert(request: Request, user: str = Depends(require_local_auth)):
    """Lädt ein eigenes SSL-Zertifikat hoch (PEM-Format)."""
    body = await request.json()
    cert_pem = body.get("cert", "").strip()
    key_pem = body.get("key", "").strip()

    if not cert_pem or not key_pem:
        return JSONResponse({"error": "cert und key erforderlich"}, status_code=400)

    if "BEGIN CERTIFICATE" not in cert_pem:
        return JSONResponse({"error": "Ungültiges Zertifikat (kein PEM-Format)"}, status_code=400)
    if "BEGIN" not in key_pem or "PRIVATE KEY" not in key_pem:
        return JSONResponse({"error": "Ungültiger Private Key (kein PEM-Format)"}, status_code=400)

    for certs_dir in [Path("/opt/jarvis/certs"), Path(__file__).parent.parent / "certs"]:
        certs_dir.mkdir(parents=True, exist_ok=True)
        cert_dst = certs_dir / "server.crt"
        key_dst = certs_dir / "server.key"
        # Backup
        for f in [cert_dst, key_dst]:
            if f.exists():
                f.rename(f.with_suffix(".bak"))
        cert_dst.write_text(cert_pem)
        key_dst.write_text(key_pem)
        os.chmod(str(key_dst), 0o600)

    return JSONResponse({"success": True, "message": "Zertifikat gespeichert. Bitte Service neu starten."})



# ─── Profil-Verwaltung ─────────────────────────────────────────────
@app.get("/api/profiles")
async def get_profiles(user: str = Depends(require_auth)):
    """Gibt alle Profile und das aktive Profil zurück."""
    safe_profiles = []
    for p in config.profiles:
        sp = {**p, "api_key": _mask_key(p.get("api_key", "")),
              "session_key": _mask_key(p.get("session_key", ""))}
        safe_profiles.append(sp)
    return JSONResponse({
        "profiles": safe_profiles,
        "active_profile_id": config.active_profile_id,
        "defaults": config.DEFAULT_PROVIDERS,
    })


@app.post("/api/profiles")
async def create_profile(request: Request, user: str = Depends(require_local_auth)):
    """Erstellt ein neues Profil."""
    body = await request.json()
    profile = config.create_profile(body)
    return JSONResponse({"success": True, "profile": profile})


@app.put("/api/profiles/{profile_id}")
async def update_profile(profile_id: str, request: Request, user: str = Depends(require_local_auth)):
    """Aktualisiert ein bestehendes Profil."""
    body = await request.json()
    profile = config.update_profile(profile_id, body)
    if profile:
        return JSONResponse({"success": True, "profile": profile})
    return JSONResponse({"success": False, "error": "Profil nicht gefunden"}, status_code=404)


@app.delete("/api/profiles/{profile_id}")
async def delete_profile(profile_id: str, user: str = Depends(require_local_auth)):
    """Löscht ein Profil (mindestens eines muss bestehen bleiben)."""
    if config.delete_profile(profile_id):
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "Letztes Profil kann nicht gelöscht werden"}, status_code=400)


@app.get("/api/settings/agentkey")
async def get_agent_key(user: str = Depends(require_local_auth)):
    """Gibt den unmasked Agent API Key zurück (für Eye-Button)."""
    return JSONResponse({"agent_api_key": config.AGENT_API_KEY or ""})


# ─── Mehrere benannte Agent-API-Keys ─────────────────────────────────

def _load_agent_keys() -> list:
    keys = config.get_setting("agent_api_keys", [])
    return keys if isinstance(keys, list) else []


def _save_agent_keys(keys: list):
    config.save_setting("agent_api_keys", keys)


@app.get("/api/agent/keys")
async def agent_keys_list(user: str = Depends(require_local_auth)):
    """Listet die benannten API-Keys (Admin)."""
    return JSONResponse({"keys": _load_agent_keys(), "legacy": bool(config.AGENT_API_KEY)})


@app.post("/api/agent/keys")
async def agent_keys_create(request: Request, user: str = Depends(require_local_auth)):
    """Erzeugt einen neuen benannten API-Key."""
    import secrets, uuid
    body = await request.json()
    name = (body.get("name") or "").strip() or "Unbenannt"
    keys = _load_agent_keys()
    entry = {"id": uuid.uuid4().hex[:8], "name": name,
             "key": secrets.token_urlsafe(32), "created": int(time.time())}
    keys.append(entry)
    _save_agent_keys(keys)
    return JSONResponse({"ok": True, "key": entry})


@app.put("/api/agent/keys/{kid}")
async def agent_keys_update(kid: str, request: Request, user: str = Depends(require_local_auth)):
    """Benennt einen Key um bzw. generiert ihn neu (body: name und/oder regenerate)."""
    import secrets
    body = await request.json()
    keys = _load_agent_keys()
    found = None
    for k in keys:
        if k.get("id") == kid:
            if "name" in body:
                k["name"] = (body.get("name") or "").strip() or k.get("name", "Unbenannt")
            if body.get("regenerate"):
                k["key"] = secrets.token_urlsafe(32)
            elif body.get("key"):
                k["key"] = str(body["key"]).strip()
            found = k
            break
    if not found:
        return JSONResponse({"ok": False, "error": "Key nicht gefunden"}, status_code=404)
    _save_agent_keys(keys)
    return JSONResponse({"ok": True, "key": found})


@app.delete("/api/agent/keys/{kid}")
async def agent_keys_delete(kid: str, user: str = Depends(require_local_auth)):
    """Löscht einen benannten API-Key."""
    keys = _load_agent_keys()
    new = [k for k in keys if k.get("id") != kid]
    if len(new) == len(keys):
        return JSONResponse({"ok": False, "error": "Key nicht gefunden"}, status_code=404)
    _save_agent_keys(new)
    return JSONResponse({"ok": True})


@app.get("/api/profiles/{profile_id}/key")
async def get_profile_key(profile_id: str, user: str = Depends(require_local_auth)):
    """Gibt die unmasked API- und Session-Keys eines Profils zurück (für Eye-Button)."""
    for p in config.profiles:
        if p["id"] == profile_id:
            return JSONResponse({
                "api_key": p.get("api_key", ""),
                "session_key": p.get("session_key", ""),
            })
    return JSONResponse({"error": "Profil nicht gefunden"}, status_code=404)


async def _probe_llm_connection(provider: str, api_url: str, api_key: str,
                                model: str, auth_method: str = "api_key",
                                session_key: str = "") -> dict:
    """Prüft die Erreichbarkeit eines LLM-Endpoints und ob das Modell existiert.

    Rückgabe-Dict (kompatibel zu /api/profiles/test):
      success: bool          – Endpoint grundsätzlich erreichbar?
      model_found: bool      – konfiguriertes Modell verfügbar?
      message / error: str
      latency_ms: int
    Wird sowohl vom Formular-Test (POST) als auch vom Profil-Status (GET) genutzt.
    """
    api_url = (api_url or "").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if auth_method == "session" and session_key:
        headers["Authorization"] = f"Bearer {session_key}"
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            # Schritt 1: Models-Endpoint (schnell)
            if provider == "openai_compatible":
                models_url = f"{api_url}/models"
            elif provider == "google":
                t0 = time.monotonic()
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                resp = await client.get(gemini_url, timeout=httpx.Timeout(10.0, connect=5.0))
                latency = int((time.monotonic() - t0) * 1000)
                if resp.status_code == 400:
                    return {"success": False, "error": "API-Key ungültig (400 Bad Request)", "latency_ms": latency}
                if resp.status_code == 403:
                    return {"success": False, "error": "API-Key ungültig oder keine Berechtigung (403 Forbidden)", "latency_ms": latency}
                if resp.status_code >= 400:
                    return {"success": False, "error": f"Gemini API Fehler {resp.status_code}: {resp.text[:120]}", "latency_ms": latency}
                data = resp.json()
                model_ids = sorted([m.get("name", "").replace("models/", "") for m in data.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])])
                model_found = model in model_ids
                if model_found:
                    msg = f"Gemini API OK – '{model}' ✓ ({len(model_ids)} Modelle verfügbar)"
                else:
                    flash_models = [m for m in model_ids if "flash" in m.lower()]
                    hint = "Verfügbare Flash-Modelle: " + ", ".join(flash_models[:8]) if flash_models else "Verfügbare Modelle: " + ", ".join(model_ids[:8])
                    msg = f"Gemini API OK aber '{model}' nicht gefunden!\n{hint}"
                return {
                    "success": True,
                    "message": msg,
                    "latency_ms": latency,
                    "model_found": model_found,
                    "available_models": model_ids,
                }
            elif provider in ("anthropic", "anthropic_session"):
                t0 = time.monotonic()
                anthropic_url = "https://api.anthropic.com/v1/models"
                anthropic_headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
                resp = await client.get(anthropic_url, headers=anthropic_headers, timeout=httpx.Timeout(10.0, connect=5.0))
                latency = int((time.monotonic() - t0) * 1000)
                if resp.status_code == 401:
                    return {"success": False, "error": "API-Key ungültig (401 Unauthorized)", "latency_ms": latency}
                if resp.status_code >= 400:
                    return {"success": False, "error": f"Anthropic API Fehler {resp.status_code}: {resp.text[:120]}", "latency_ms": latency}
                data = resp.json()
                model_ids = [m.get("id", "") for m in data.get("data", [])]
                model_found = model in model_ids
                return {
                    "success": True,
                    "message": f"Anthropic API OK – {len(model_ids)} Modelle verfügbar" + (f", '{model}' ✓" if model_found else f" – '{model}' nicht gefunden!"),
                    "latency_ms": latency,
                    "model_found": model_found,
                }
            elif provider == "openrouter":
                models_url = "https://openrouter.ai/api/v1/models"
            else:
                return {"success": False, "error": f"Unbekannter Provider: {provider}"}

            t0 = time.monotonic()
            resp = await client.get(models_url, headers=headers)
            latency = int((time.monotonic() - t0) * 1000)

            if resp.status_code == 401:
                return {"success": False, "error": "API (Application Programming Interface)-Key ungültig (401 Unauthorized)", "latency_ms": latency}
            if resp.status_code == 404:
                return {"success": False, "error": f"Endpunkt nicht gefunden: {models_url}", "latency_ms": latency}
            if resp.status_code >= 400:
                return {"success": False, "error": f"HTTP (Hypertext Transfer Protocol) {resp.status_code}: {resp.text[:100]}", "latency_ms": latency}

            data = resp.json()
            model_ids = [m["id"] for m in data.get("data", [])]
            model_found = model in model_ids

            return {
                "success": True,
                "message": f"Verbindung OK – {len(model_ids)} Modell(e) verfügbar" + (f", Modell '{model}' gefunden ✓" if model_found else f" – Modell '{model}' NICHT gefunden!"),
                "latency_ms": latency,
                "model_found": model_found,
                "models": model_ids[:10],
            }

    except httpx.ConnectError as e:
        return {"success": False, "error": f"Verbindung fehlgeschlagen: {e}"}
    except httpx.TimeoutException:
        return {"success": False, "error": "Timeout (Zeitüberschreitung) – Server antwortet nicht innerhalb von 15s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/profiles/test")
async def test_profile_connection(request: Request, user: str = Depends(require_auth)):
    """Testet die Verbindung mit den aktuellen Formularwerten (nicht gespeicherten)."""
    body = await request.json()
    result = await _probe_llm_connection(
        provider=body.get("provider", ""),
        api_url=body.get("api_url", ""),
        api_key=body.get("api_key", ""),
        model=body.get("model", ""),
        auth_method=body.get("auth_method", "api_key"),
        session_key=body.get("session_key", ""),
    )
    return JSONResponse(result)


async def _list_llm_models(provider: str, api_url: str, api_key: str,
                           auth_method: str = "api_key", session_key: str = "") -> dict:
    """Liefert die VOLLE Liste verfuegbarer Modelle eines Providers (fuer 'Discover')."""
    api_url = (api_url or "").rstrip("/")
    key = session_key if (auth_method == "session" and session_key) else api_key
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            if provider == "google":
                if not key:
                    return {"success": False, "error": "API-Key fehlt"}
                r = await client.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}")
                if r.status_code >= 400:
                    return {"success": False, "error": f"Gemini {r.status_code}: {r.text[:120]}"}
                models = sorted({m.get("name", "").replace("models/", "")
                                 for m in r.json().get("models", [])
                                 if "generateContent" in m.get("supportedGenerationMethods", [])})
            elif provider in ("anthropic", "anthropic_session"):
                if not key:
                    return {"success": False, "error": "API-Key fehlt"}
                r = await client.get("https://api.anthropic.com/v1/models",
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
                if r.status_code >= 400:
                    return {"success": False, "error": f"Anthropic {r.status_code}: {r.text[:120]}"}
                models = [m.get("id", "") for m in r.json().get("data", [])]
            elif provider == "openrouter":
                r = await client.get("https://openrouter.ai/api/v1/models")
                if r.status_code >= 400:
                    return {"success": False, "error": f"OpenRouter {r.status_code}: {r.text[:120]}"}
                models = sorted(m.get("id", "") for m in r.json().get("data", []))
            elif provider == "openai_compatible":
                headers = {}
                if key:
                    headers["Authorization"] = f"Bearer {key}"
                r = await client.get(f"{api_url}/models", headers=headers)
                if r.status_code >= 400:
                    return {"success": False, "error": f"HTTP {r.status_code}: {r.text[:120]}"}
                models = sorted(m.get("id", "") for m in r.json().get("data", []))
            else:
                return {"success": False, "error": f"Unbekannter Provider: {provider}"}
        models = [m for m in models if m]
        return {"success": True, "models": models}
    except httpx.ConnectError as e:
        return {"success": False, "error": f"Verbindung fehlgeschlagen: {e}"}
    except httpx.TimeoutException:
        return {"success": False, "error": "Timeout – Server antwortet nicht"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/profiles/models")
async def list_profile_models(request: Request, user: str = Depends(require_auth)):
    """Liefert verfuegbare Modelle fuer die aktuellen Formularwerte (Discover-Button)."""
    body = await request.json()
    result = await _list_llm_models(
        provider=body.get("provider", ""),
        api_url=body.get("api_url", ""),
        api_key=body.get("api_key", ""),
        auth_method=body.get("auth_method", "api_key"),
        session_key=body.get("session_key", ""),
    )
    return JSONResponse(result)


@app.get("/api/profiles/{profile_id}/test")
async def test_saved_profile_connection(profile_id: str, user: str = Depends(require_auth)):
    """Prüft die Erreichbarkeit eines GESPEICHERTEN Profils (Status-Pill in der Übersicht).

    Nutzt den serverseitig hinterlegten Key → der echte Key verlässt den Server nicht.
    Liefert zusätzlich 'status' (ok/degraded/down) für die Ampel-Anzeige im Frontend.
    """
    prof = next((p for p in config.profiles if p.get("id") == profile_id), None)
    if not prof:
        return JSONResponse({"success": False, "error": "Profil nicht gefunden", "status": "down"}, status_code=404)

    result = await _probe_llm_connection(
        provider=prof.get("provider", ""),
        api_url=prof.get("api_url", ""),
        api_key=prof.get("api_key", ""),
        model=prof.get("model", ""),
        auth_method=prof.get("auth_method", "api_key"),
        session_key=prof.get("session_key", ""),
    )
    # Ampel: erreichbar + Modell vorhanden → grün; erreichbar aber Modell fehlt → gelb; nicht erreichbar → rot
    if result.get("success"):
        result["status"] = "ok" if result.get("model_found", True) else "degraded"
    else:
        result["status"] = "down"
    return JSONResponse(result)


@app.get("/api/llm/active-status")
async def llm_active_status(user: str = Depends(require_auth)):
    """Erreichbarkeit des AKTIVEN LLM-Profils – fuer die Verbindungsstatus-Pill.
    status: ok (erreichbar) | degraded (erreichbar, Modell fehlt) | down (nicht erreichbar)."""
    prof = config.active_profile
    if not prof:
        return JSONResponse({"success": False, "status": "down", "error": "Kein aktives Profil"})
    result = await _probe_llm_connection(
        provider=prof.get("provider", ""),
        api_url=prof.get("api_url", ""),
        api_key=prof.get("api_key", ""),
        model=prof.get("model", ""),
        auth_method=prof.get("auth_method", "api_key"),
        session_key=prof.get("session_key", ""),
    )
    if result.get("success"):
        result["status"] = "ok" if result.get("model_found", True) else "degraded"
    else:
        result["status"] = "down"
    result["profile_name"] = prof.get("name", "")
    return JSONResponse(result)


@app.post("/api/profiles/{profile_id}/activate")
async def activate_profile(profile_id: str, user: str = Depends(require_local_auth)):
    """Setzt ein Profil als aktiv."""
    if config.activate_profile(profile_id):
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "Profil nicht gefunden"}, status_code=404)


@app.post("/api/feedback")
async def api_feedback(request: Request):
    """Benutzer-Feedback zu einer Jarvis-Antwort (👍 / 👎 / ❌ Falsch)."""
    body = await request.json()

    # Token optional (Jarvis-Auth oder anonymous)
    token_str = (
        request.headers.get("Authorization", "").replace("Bearer ", "")
        or body.get("token", "")
    )
    user = verify_token(token_str) or "anonymous"

    rating   = body.get("rating", "")        # "positive" | "negative" | "wrong"
    user_msg = body.get("user_message", "")
    bot_resp = body.get("bot_response", "")

    if rating not in ("positive", "negative", "wrong"):
        return JSONResponse({"success": False, "error": "Ungültiges Rating"}, status_code=400)

    # In data/feedback.json speichern
    feedback_file = Path("data/feedback.json")
    feedbacks = []
    if feedback_file.exists():
        try:
            feedbacks = json.loads(feedback_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    feedbacks.append({
        "ts": int(time.time() * 1000),
        "user": user,
        "rating": rating,
        "user_message": user_msg[:500],
        "bot_response": bot_resp[:500],
    })
    feedbacks = feedbacks[-500:]
    feedback_file.parent.mkdir(parents=True, exist_ok=True)
    feedback_file.write_text(json.dumps(feedbacks, ensure_ascii=False, indent=2), encoding="utf-8")

    if rating == "positive":
        return JSONResponse({"success": True, "message": "👍 Danke! Das freut mich.", "analysis": ""})

    # Für negative/wrong: LLM-Analyse synchron awaiten und im Response zurückgeben
    analysis = await _feedback_self_improve(user_msg, bot_resp, rating)
    verb = "falsch" if rating == "wrong" else "unzureichend"
    return JSONResponse({
        "success": True,
        "message": (
            f"🔧 Danke für dein Feedback! Ich habe analysiert, warum die Antwort {verb} war, "
            "und eine Lernnotiz gespeichert."
        ),
        "analysis": analysis,
    })


async def _feedback_self_improve(user_msg: str, bot_resp: str, rating: str) -> str:
    """LLM analysiert schlechte Antwort, speichert Lernnotiz und gibt Analyse zurück."""
    import datetime
    try:
        from backend.config import config as _cfg
        from backend.llm import get_provider

        try:
            from google.genai import types as _gt
            def _mk_part(t):
                return _gt.Content(role="user", parts=[_gt.Part.from_text(text=t)])
        except ImportError:
            class _P:
                def __init__(self, t): self.text = t; self.function_call = None; self.function_response = None
            class _C:
                def __init__(self, t): self.role = "user"; self.parts = [_P(t)]
            def _mk_part(t): return _C(t)

        provider = get_provider(
            _cfg.LLM_PROVIDER,
            _cfg.current_api_key,
            _cfg.current_api_url,
            auth_method=_cfg.current_auth_method,
            session_key=_cfg.current_session_key,
            prompt_tool_calling=_cfg.current_prompt_tool_calling,
        )
        reason = "falsch" if rating == "wrong" else "schlecht/unzureichend"
        prompt = (
            f"Du bist Jarvis. Ein Benutzer hat eine deiner Antworten als '{reason}' bewertet.\n\n"
            f"Frage des Benutzers:\n{user_msg}\n\n"
            f"Deine Antwort (bewertet als '{reason}'):\n{bot_resp[:600]}\n\n"
            f"Erstelle eine strukturierte Lernnotiz mit folgenden Abschnitten:\n\n"
            f"## Was war {reason}?\n"
            f"(2-3 Sätze Analyse des Fehlers)\n\n"
            f"## Bessere Alternativen\n"
            f"Formuliere 3-5 konkrete alternative Antworten auf die Frage, die besser gewesen wären. "
            f"Nummeriere sie (1. 2. 3. ...) und erkläre jeweils kurz warum diese Variante besser ist.\n\n"
            f"## Lernregel\n"
            f"(1-2 Sätze: Welche Regel soll Jarvis für zukünftige ähnliche Fragen beachten?)"
        )
        contents = [_mk_part(prompt)]
        response = await provider.generate_response(
            model=_cfg.current_model,
            system_prompt="Du bist ein KI-Assistent der eigene Fehler analysiert, bessere Alternativen formuliert und daraus Lernregeln ableitet.",
            contents=contents,
            tools=[],
        )
        analysis = ""
        for part in (response.parts or []):
            if getattr(part, "text", None):
                analysis += part.text

        if not analysis.strip():
            return ""

        ts_str = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        note_dir = Path("data/knowledge/learned")
        note_dir.mkdir(parents=True, exist_ok=True)
        note_file = note_dir / f"feedback_{int(time.time())}.md"
        note_file.write_text(
            f"# Feedback-Lernnotiz ({rating}) – {ts_str}\n\n"
            f"## Benutzerfrage\n{user_msg}\n\n"
            f"## Ursprüngliche Antwort (bewertet: {reason})\n{bot_resp[:400]}\n\n"
            f"{analysis}\n",
            encoding="utf-8",
        )
        return analysis
    except Exception as e:
        print(f"⚠️  Feedback-Selbstoptimierung fehlgeschlagen: {e}")
        return ""


@app.get("/api/health")
async def health():
    """Erweiterter Health-Check mit System- und Service-Status."""
    errors = config.validate()

    # System-Infos
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    # Service-Checks
    services = {}
    # VNC
    try:
        r, _ = await asyncio.open_connection("localhost", 5900)
        r.close()
        services["vnc"] = "ok"
    except Exception:
        services["vnc"] = "down"

    # WhatsApp Bridge
    try:
        result = await asyncio.to_thread(_wa_bridge_request_safe, "/status")
        services["whatsapp_bridge"] = "ok" if "error" not in result else "down"
    except Exception:
        services["whatsapp_bridge"] = "down"

    # LLM konfiguriert?
    services["llm"] = "ok" if config.active_profile.get("api_key") else "no_key"

    return JSONResponse({
        "status": "ok" if not errors else "warning",
        "errors": errors,
        "cpu_percent": _cached_cpu_percent,
        "memory_percent": mem.percent,
        "disk_percent": disk.percent,
        "services": services,
    })


@app.post("/api/verify-token")
async def verify_token_endpoint(request: Request):
    """Prüft ob ein Token noch gültig ist. Gibt verbleibende Sekunden zurueck."""
    body = await request.json()
    tok = body.get("token", "")
    username = verify_token(tok)
    if username:
        try:
            _, ts, _ = tok.split(":", 2)
            # Token ist 30 Tage gueltig (siehe verify_token) – verbleibende Zeit
            # MUSS mit derselben Lebensdauer gerechnet werden, sonst werden gueltige
            # Sitzungen > 24h faelschlich als negativ ("laeuft in -xxx Min ab") angezeigt.
            remaining = max(0, 2592000 - (time.time() - int(ts)))
        except Exception:
            remaining = 0
        return JSONResponse({"valid": True, "username": username, "remaining_seconds": int(remaining),
                             "must_change_password": _user_must_change(username),
                             "is_admin": _is_admin_user(username)})
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
async def get_skills(user: str = Depends(require_auth)):
    """Gibt alle Skills mit Status zurück."""
    sm = _get_skill_manager()
    return JSONResponse({"skills": sm.list_skills()})


@app.post("/api/skills/{name}/enable")
async def enable_skill(name: str, user: str = Depends(require_local_auth)):
    """Aktiviert einen Skill."""
    sm = _get_skill_manager()
    success = sm.enable_skill(name)
    if agent_instance:
        agent_instance.reload_skills()
    return JSONResponse({"success": success})


@app.post("/api/skills/{name}/disable")
async def disable_skill(name: str, user: str = Depends(require_local_auth)):
    """Deaktiviert einen Skill (bleibt installiert)."""
    sm = _get_skill_manager()
    success = sm.disable_skill(name)
    if agent_instance:
        agent_instance.reload_skills()
    return JSONResponse({"success": success})


@app.post("/api/skills/{name}/remove")
async def remove_skill(name: str, user: str = Depends(require_local_auth)):
    """Entfernt einen Skill aus 'Installierte' (→ 'Moegliche'), ohne Dateien
    zu loeschen. Pendant zum 'x'-Button (vs. Toggle = nur deaktivieren)."""
    sm = _get_skill_manager()
    success = sm.remove_skill(name)
    if agent_instance:
        agent_instance.reload_skills()
    return JSONResponse({"success": success})


@app.get("/api/skills/{name}/config")
async def get_skill_config(name: str, user: str = Depends(require_auth)):
    """Gibt die Konfiguration eines Skills zurück."""
    sm = _get_skill_manager()
    cfg = sm.get_skill_config(name)

    # Google: Aktuelle Werte aus Umgebung einblenden
    if name == "google":
        cfg.setdefault("client_id", os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""))
        cfg.setdefault("client_secret", os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""))

    return JSONResponse({"config": cfg})


@app.post("/api/skills/{name}/config")
async def update_skill_config(name: str, request: Request, user: str = Depends(require_local_auth)):
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
async def install_skill_deps(name: str, user: str = Depends(require_local_auth)):
    """Installiert die Abhängigkeiten eines Skills."""
    sm = _get_skill_manager()
    result = sm.install_dependencies(name)
    return JSONResponse({"result": result})


@app.delete("/api/skills/{name}")
async def uninstall_skill(name: str, user: str = Depends(require_local_auth)):
    """Entfernt einen Skill (nur nicht-system Skills)."""
    sm = _get_skill_manager()
    success = sm.uninstall_skill(name)
    if success and agent_instance:
        agent_instance.reload_skills()
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "System-Skill oder nicht gefunden"}, status_code=400)


@app.post("/api/skills/reload")
async def reload_skills(user: str = Depends(require_local_auth)):
    """Lädt alle Skills neu (Hot-Reload)."""
    if agent_instance:
        agent_instance.reload_skills()
    return JSONResponse({"success": True})


# ─── Branding / White-Label ──────────────────────────────────────────
_BRANDING_DIR = Path(__file__).parent.parent / "data" / "branding"
_BRANDING_LOGO_EXTS = {"png", "jpg", "jpeg", "svg", "webp", "gif"}


def _branding_state() -> tuple[bool, dict]:
    """Gibt (enabled, config) des Branding-Skills zurück."""
    states = config.get_skill_states()
    st = states.get("branding", {})
    return bool(st.get("enabled", False)), (st.get("config", {}) or {})


def _branding_logo_stem(variant: str) -> str:
    """Dateistamm je Logo-Variante (dark = Standard, light = Hell-Modus)."""
    return "logo_light" if variant == "light" else "logo"


def _branding_logo_path(variant: str = "dark") -> Path | None:
    """Sucht eine vorhandene Logo-Datei (data/branding/<stem>.<ext>)."""
    stem = _branding_logo_stem(variant)
    for ext in _BRANDING_LOGO_EXTS:
        p = _BRANDING_DIR / f"{stem}.{ext}"
        if p.exists():
            return p
    return None


@app.get("/api/branding")
async def get_branding():
    """Liefert das aktive Branding (öffentlich – wird schon auf der Loginseite gebraucht).

    Nur wenn der Branding-Skill aktiviert ist, werden Werte geliefert; sonst
    ``active: false`` → Frontend rendert das Standard-Jarvis-Design.

    Farben und Logo gibt es getrennt für Dunkel- (``colors``/``logo_url``) und
    Hell-Modus (``colors_light``/``logo_url_light``). Fehlt eine Hell-Variante,
    faellt das Frontend auf die Dunkel-Variante zurueck.
    """
    enabled, cfg = _branding_state()
    if not enabled:
        return JSONResponse({"active": False})

    ts = int(time.time())
    logo = _branding_logo_path("dark")
    logo_light = _branding_logo_path("light")
    return JSONResponse({
        "active": True,
        "company_name": cfg.get("company_name", ""),
        "core_letter": cfg.get("core_letter", ""),
        "logo_mode": cfg.get("logo_mode", "letter"),
        "colors": cfg.get("colors", {}) or {},
        "colors_light": cfg.get("colors_light", {}) or {},
        "logo_url": ("/api/branding/logo?t=%d" % ts) if logo else "",
        "logo_url_light": ("/api/branding/logo?variant=light&t=%d" % ts) if logo_light else "",
    })


@app.get("/api/branding/logo")
async def get_branding_logo(variant: str = "dark"):
    """Serviert das hochgeladene Firmenlogo (öffentlich)."""
    logo = _branding_logo_path(variant)
    if not logo:
        return JSONResponse({"error": "kein Logo"}, status_code=404)
    media = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "svg": "image/svg+xml", "webp": "image/webp", "gif": "image/gif",
    }.get(logo.suffix.lstrip(".").lower(), "application/octet-stream")
    return FileResponse(str(logo), media_type=media)


@app.post("/api/branding/logo")
async def upload_branding_logo(file: UploadFile = File(...),
                               variant: str = Form("dark"),
                               user: str = Depends(require_local_auth)):
    """Lädt ein Firmenlogo hoch (ersetzt ein vorhandenes der gleichen Variante)."""
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in _BRANDING_LOGO_EXTS:
        return JSONResponse(
            {"success": False, "error": f"Format .{ext} nicht erlaubt"},
            status_code=400)
    variant = "light" if variant == "light" else "dark"
    stem = _branding_logo_stem(variant)
    _BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    # Alte Logos dieser Variante (egal welche Endung) entfernen
    for old in _BRANDING_DIR.glob(f"{stem}.*"):
        try:
            old.unlink()
        except OSError:
            pass
    data = await file.read()
    (_BRANDING_DIR / f"{stem}.{ext}").write_bytes(data)
    suffix = "&variant=light" if variant == "light" else ""
    return JSONResponse({"success": True,
                         "logo_url": "/api/branding/logo?t=%d%s" % (int(time.time()), suffix)})


@app.delete("/api/branding/logo")
async def delete_branding_logo(variant: str = "dark",
                               user: str = Depends(require_local_auth)):
    """Entfernt das hochgeladene Firmenlogo der angegebenen Variante."""
    variant = "light" if variant == "light" else "dark"
    stem = _branding_logo_stem(variant)
    removed = False
    for old in _BRANDING_DIR.glob(f"{stem}.*"):
        try:
            old.unlink()
            removed = True
        except OSError:
            pass
    return JSONResponse({"success": True, "removed": removed})


# ─── Confluence (für den Confluence-Reiter; teilt sich Client mit dem Skill) ──

def _confluence_client():
    from backend.confluence_client import ConfluenceClient
    return ConfluenceClient()


# Referenzen auf laufende Bereichs-Import-Jobs halten (sonst GC durch asyncio)
_bg_confluence_tasks: set = set()


@app.get("/api/confluence/test")
async def confluence_test(user: str = Depends(require_auth)):
    """Prueft die gespeicherte Confluence-Verbindung (fuer den Reiter)."""
    from backend.confluence_client import ConfluenceError
    c = _confluence_client()
    if not c.configured:
        return JSONResponse({"ok": False, "configured": False,
                             "error": "Nicht konfiguriert (URL/Token fehlen)."})
    try:
        spaces = await asyncio.to_thread(c.spaces, 50)
        return JSONResponse({"ok": True, "configured": True, "base": c.base,
                             "count": len(spaces),
                             "spaces": [{"key": s.get("key"), "name": s.get("name")} for s in spaces]})
    except ConfluenceError as e:
        return JSONResponse({"ok": False, "configured": True, "status": e.status,
                             "error": str(e)})


@app.get("/api/confluence/spaces")
async def confluence_spaces_api(user: str = Depends(require_auth)):
    """Listet alle Confluence-Bereiche (Spaces) mit Link – fuer den Wissen-Reiter."""
    from backend.confluence_client import ConfluenceError
    c = _confluence_client()
    if not c.configured:
        return JSONResponse({"ok": False, "configured": False,
                             "error": "Nicht konfiguriert (URL/Token fehlen)."})
    try:
        spaces = await asyncio.to_thread(c.spaces_detailed, 500)
        spaces.sort(key=lambda s: (s.get("name") or "").lower())
        return JSONResponse({"ok": True, "configured": True, "base": c.base,
                             "count": len(spaces), "spaces": spaces})
    except ConfluenceError as e:
        return JSONResponse({"ok": False, "configured": True, "status": e.status,
                             "error": str(e)})


@app.get("/api/confluence/pages")
async def confluence_pages_api(space: str = "", user: str = Depends(require_auth)):
    """Listet die Seiten eines Bereichs (Space) – fuer die Auswahl im Extraktor."""
    from backend.confluence_client import ConfluenceError
    c = _confluence_client()
    if not c.configured:
        return JSONResponse({"ok": False, "error": "Nicht konfiguriert."}, status_code=400)
    if not space.strip():
        return JSONResponse({"ok": False, "error": "Space-Key fehlt."}, status_code=400)
    try:
        pages = await asyncio.to_thread(c.pages_in_space, space.strip(), 500)
        pages.sort(key=lambda p: (p.get("title") or "").lower())
        return JSONResponse({"ok": True, "count": len(pages), "pages": pages})
    except ConfluenceError as e:
        return JSONResponse({"ok": False, "status": e.status, "error": str(e)})


@app.get("/api/confluence/search")
async def confluence_search_api(q: str = "", space: str = "", label: str = "",
                                limit: int = 20, user: str = Depends(require_auth)):
    """Suche fuer den Reiter – liefert Treffer mit Link."""
    from backend.confluence_client import ConfluenceError
    c = _confluence_client()
    if not c.configured:
        return JSONResponse({"ok": False, "error": "Nicht konfiguriert."}, status_code=400)
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 20
    try:
        data = await asyncio.to_thread(c.search, q.strip(), space.strip() or None,
                                       label.strip() or None, limit)
        items = [{
            "id": r.get("id"), "title": r.get("title"),
            "type": r.get("type"), "link": c.link_for(data, r),
        } for r in data.get("results", [])]
        return JSONResponse({"ok": True, "results": items})
    except ConfluenceError as e:
        return JSONResponse({"ok": False, "status": e.status, "error": str(e)})


@app.get("/api/confluence/page")
async def confluence_page_api(id: str = "", title: str = "", space: str = "",
                              user: str = Depends(require_auth)):
    """Seiteninhalt fuer den Reiter (als Text)."""
    from backend.confluence_client import ConfluenceError, html_to_text
    c = _confluence_client()
    if not c.configured:
        return JSONResponse({"ok": False, "error": "Nicht konfiguriert."}, status_code=400)
    try:
        page = await asyncio.to_thread(c.get_page, id.strip() or None,
                                       title.strip() or None, space.strip() or None)
        body = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
        return JSONResponse({"ok": True,
                             "id": page.get("id"), "title": page.get("title"),
                             "space": (page.get("space") or {}).get("key"),
                             "link": c.link_for(page, page),
                             "text": html_to_text(body, 8000)})
    except ConfluenceError as e:
        return JSONResponse({"ok": False, "status": e.status, "error": str(e)})


# ─── Jira (Reiter: Ticketsuche) ──────────────────────────────────────

def _jira_client():
    from backend.jira_client import JiraClient
    return JiraClient()


@app.get("/api/jira/test")
async def jira_test(user: str = Depends(require_auth)):
    """Prueft die gespeicherte Jira-Verbindung (fuer den Reiter)."""
    from backend.jira_client import JiraError
    c = _jira_client()
    if not c.configured:
        return JSONResponse({"ok": False, "configured": False,
                             "error": "Nicht konfiguriert (URL/Token fehlen)."})
    try:
        me = await asyncio.to_thread(c.myself)
        return JSONResponse({"ok": True, "configured": True, "base": c.base,
                             "user": me.get("displayName") or me.get("name"),
                             "email": me.get("emailAddress", "")})
    except JiraError as e:
        return JSONResponse({"ok": False, "configured": True, "status": e.status,
                             "error": str(e)})


@app.get("/api/jira/search")
async def jira_search_api(q: str = "", project: str = "", status: str = "",
                          issuetype: str = "", assignee: str = "", jql: str = "",
                          limit: int = 25, user: str = Depends(require_auth)):
    """Ticketsuche fuer den Reiter – liefert Treffer mit Link."""
    from backend.jira_client import JiraError, issue_brief
    c = _jira_client()
    if not c.configured:
        return JSONResponse({"ok": False, "error": "Nicht konfiguriert."}, status_code=400)
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 25
    query = (jql or "").strip() or c.build_jql(
        q.strip(), project.strip() or None, status.strip() or None,
        issuetype.strip() or None, assignee.strip() or None)
    try:
        data = await asyncio.to_thread(c.search, query, limit)
        items = [issue_brief(it, c.base) for it in data.get("issues", [])]
        return JSONResponse({"ok": True, "total": data.get("total", len(items)),
                             "jql": query, "results": items})
    except JiraError as e:
        return JSONResponse({"ok": False, "status": e.status, "error": str(e), "jql": query})


@app.get("/api/jira/issue")
async def jira_issue_api(key: str = "", user: str = Depends(require_auth)):
    """Ticketdetails fuer den Reiter (Beschreibung als Text + Kommentare)."""
    from backend.jira_client import JiraError, html_to_text, issue_brief
    c = _jira_client()
    if not c.configured:
        return JSONResponse({"ok": False, "error": "Nicht konfiguriert."}, status_code=400)
    if not key.strip():
        return JSONResponse({"ok": False, "error": "key fehlt."}, status_code=400)
    try:
        it = await asyncio.to_thread(c.get_issue, key.strip())
        b = issue_brief(it, c.base)
        f = it.get("fields", {}) or {}
        comments = [{
            "author": (cm.get("author") or {}).get("displayName", "?"),
            "body": html_to_text(cm.get("body") or "", 1500),
        } for cm in (((f.get("comment") or {}).get("comments")) or [])[-10:]]
        b["description"] = html_to_text(f.get("description") or "", 8000)
        b["comments"] = comments
        return JSONResponse({"ok": True, **b})
    except JiraError as e:
        return JSONResponse({"ok": False, "status": e.status, "error": str(e)})


# ─── Support-Assistent (/support) ────────────────────────────────────

def _skill_active(name: str) -> bool:
    """True, wenn der Skill installiert UND aktiviert ist."""
    try:
        st = config.get_skill_states().get(name, {}) or {}
        return bool(st.get("enabled"))
    except Exception:
        return False


_SUPPORT_STOP = set("der die das und oder ist mit fuer für von im in den dem ein eine "
                    "auf zu wie was wer wann wo bei aus the a an of to and or is".split())


def _support_tokens(s: str) -> set:
    import re
    return {t for t in re.split(r"[^0-9a-zA-ZäöüÄÖÜß]+", (s or "").lower())
            if len(t) > 2 and t not in _SUPPORT_STOP}


def _support_terms(query: str) -> list:
    """Extrahiert sinnvolle Suchbegriffe aus der Anfrage – Codes/Identifier
    (z.B. CRM-10550, NXDCS-357), Kunden-/Auftragsnummern, zitierte Phrasen,
    sonst bedeutungstragende Woerter. Verhindert, dass die ganze Anfrage als
    Phrase gesucht wird (was bei Saetzen 0 Treffer liefert)."""
    import re
    q = query or ""
    terms: list[str] = []

    def _add(x):
        x = (x or "").strip()
        if x and x not in terms:
            terms.append(x)

    # Zusammengesetzte Tokens mit Bindestrich als PHRASE behandeln
    # (z.B. ibsv3-server, e-arztbrief, dc-vserver) – nicht in Einzelwörter zerlegen.
    for m in re.findall(r"\b[0-9A-Za-zÄÖÜäöü]+(?:-[0-9A-Za-zÄÖÜäöü]+)+\b", q):
        if re.search(r"[A-Za-zÄÖÜäöü]", m):
            _add(m)
    for m in re.findall(r"\b[A-Za-zÄÖÜäöü]{2,}-?\d{2,}\b", q):  # CRM-10550, ABC123
        _add(m)
    for m in re.findall(r"\b\d{4,}\b", q):                       # lange Zahlen
        _add(m)
    for m in re.findall(r'"([^"]{2,})"', q):                     # zitierte Phrasen
        _add(m)
    if terms:
        return terms[:6]
    for w in re.split(r"[^0-9A-Za-zäöüÄÖÜß]+", q):               # sonst: Woerter
        if len(w) > 3 and w.lower() not in _SUPPORT_STOP:
            _add(w)
    return terms[:6] or ([q.strip()] if q.strip() else [])


def _support_jira_jql(query: str, open_only: bool = True) -> str:
    """JQL aus den extrahierten Begriffen (OR-verknuepft), nach Aktualitaet.
    ``open_only`` beschraenkt auf unaufgeloeste (offene) Vorgaenge."""
    from backend.jira_client import crm_org_clause
    terms = _support_terms(query)
    clauses = []
    if terms:
        # Ist eine CRM-Kunden-ID dabei -> NUR exakte Organisationsfeld-Suche (alle
        # Tickets des Kunden, praezise). Sonst Volltext ueber alle Begriffe (OR).
        crm_clauses = [c for c in (crm_org_clause(t) for t in terms) if c]
        if crm_clauses:
            parts = crm_clauses
        else:
            parts = ['text ~ "%s"' % t.replace('"', "'") for t in terms]
        clauses.append("(" + " OR ".join(parts) + ")")
    if open_only:
        clauses.append("resolution = Unresolved")
    jql = " AND ".join(clauses)
    return (jql + " ORDER BY updated DESC") if jql else "ORDER BY updated DESC"


@app.get("/support", response_class=HTMLResponse)
async def support_page():
    """Support-Oberflaeche ausliefern – nur wenn der Skill aktiv ist."""
    if not _skill_active("support_assistant"):
        return HTMLResponse("<h1>404 – Support-Assistent nicht aktiv</h1>", status_code=404)
    f = FRONTEND_DIR / "support.html"
    return HTMLResponse(content=f.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/api/support/status")
async def support_status(user: str = Depends(require_auth)):
    """Status fuer die Support-Oberflaeche (Checkbox-Sichtbarkeit)."""
    cfg = config.get_skill_states().get("support_assistant", {}).get("config", {}) or {}
    def _cap(v, d):
        try:
            return max(2, min(int(v), 20))
        except (TypeError, ValueError):
            return d
    return JSONResponse({
        "active": _skill_active("support_assistant"),
        "jira_active": _skill_active("jira"),
        "confluence_active": _skill_active("confluence"),
        "has_prompt": bool((cfg.get("system_prompt") or "").strip()),
        "summary_lines_max": _cap(cfg.get("summary_lines"), 5),
        "result_lines_max": _cap(cfg.get("result_lines"), 2),
    })


def _two_line(text: str, limit: int = 180) -> str:
    import re
    t = re.sub(r"\s+", " ", (text or "")).strip()
    return (t[:limit] + "…") if len(t) > limit else t


def _first_url(text: str) -> str:
    import re
    m = re.search(r"https?://[^\s)\]}>\"']+", text or "")
    return m.group(0) if m else ""


def _rag_source_link(rel: str, chunk: str) -> str:
    """Quell-Link fuer einen Wissens-Treffer: URL aus dem Chunk, sonst aus der
    Quelldatei (z.B. der ``> Quelle: <url>``-Kopf importierter Dokumente)."""
    u = _first_url(chunk)
    if u:
        return u
    try:
        from backend.tools.knowledge import PROJECT_ROOT
        p = PROJECT_ROOT / rel
        if p.is_file() and p.stat().st_size < 300_000:
            return _first_url(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return ""


_RAG_TITLE_KEYS = ["topic", "title", "titel", "name", "subject", "betreff",
                   "frage", "question", "summary", "category", "kategorie"]
_RAG_BODY_KEYS = ["content_text", "content", "text", "antwort", "answer", "body",
                  "description", "beschreibung", "inhalt", "value"]


def _support_readable(stem: str, chunk: str) -> tuple[str, str]:
    """Macht einen Wissens-Chunk lesbar: liefert (Titel, Zusammenfassung).

    JSON-Inhalte (z.B. faq.json, Konversations-Logs) werden geparst und sinnvolle
    Felder extrahiert, statt rohes JSON anzuzeigen. Hash-/leere Titel werden durch
    ein passendes Inhaltsfeld ersetzt.
    """
    import json as _json
    import re as _re
    text = chunk or ""
    title = _re.sub(r"^extract_[0-9a-f]+_", "", stem or "").replace("_", " ").strip()
    is_weak = (not title) or len(title) < 4 or bool(_re.fullmatch(r"[0-9a-f]{6,}", title))

    # JSON erkennen (ganzer Chunk oder eingebettetes Objekt)
    obj = None
    s = text.strip()
    for cand in (s, (_re.search(r"\{.*\}", s, _re.S).group(0) if _re.search(r"\{.*\}", s, _re.S) else None)):
        if not cand:
            continue
        try:
            d = _json.loads(cand)
        except Exception:
            continue
        if isinstance(d, list) and d:
            d = next((x for x in d if isinstance(x, dict)), None)
        if isinstance(d, dict):
            obj = d
            break

    def _pick(d, keys):
        low = {k.lower(): v for k, v in d.items()}
        for k in keys:
            v = low.get(k)
            if isinstance(v, (str, int, float)) and str(v).strip():
                return str(v).strip()
        return ""

    summary = text
    if obj is not None:
        t = _pick(obj, _RAG_TITLE_KEYS)
        body = _pick(obj, _RAG_BODY_KEYS)
        if t and is_weak:
            title = t
        if body:
            summary = body
        elif is_weak:
            # kein bekanntes Textfeld → erstes laengeres String-Feld als Inhalt
            for v in obj.values():
                if isinstance(v, str) and len(v.strip()) > 20:
                    summary = v.strip()
                    break
    elif is_weak:
        # Klartext: erste sinnvolle (nicht JSON-artige) Zeile als Titel
        first = next((ln.strip(" #*->") for ln in text.splitlines()
                      if len(ln.strip(" #*->")) > 3
                      and not ln.lstrip().startswith(('"', '{', '}', '[', ']'))), "")
        if first:
            title = first

    return (_two_line(title, 90) or (stem or "Dokument")), _two_line(summary, 600)


async def _support_ai_summary(query: str, blocks: list, system_prompt: str, lines: int = 5,
                              lang: str = "de") -> str:
    """LLM-Kurzzusammenfassung der Top-Quellen (best effort). Stellt das
    konfigurierte Prompt der Instruktion voran. ``lines`` begrenzt die Laenge."""
    if not blocks:
        return ""
    try:
        lines = max(1, min(int(lines or 5), 20))
    except (TypeError, ValueError):
        lines = 5
    try:
        from backend.llm import get_provider
        from google.genai import types
        if str(lang).lower().startswith("en"):
            base = ("You are a support assistant. Matching results (tickets, "
                    "knowledge/Confluence pages) for the query were ALREADY found and "
                    "are listed below. In at most %d sentences, give a helpful overview: "
                    "what the results are about, which topics/cases are relevant. Refer "
                    "concretely to the listed content. There ARE results — do NOT claim "
                    "that no information is available. Reply in English, readable prose "
                    "(no JSON)." % lines)
        else:
            base = ("Du bist ein Support-Assistent. Zu der Anfrage wurden bereits passende "
                    "Treffer (Tickets, Wissens-/Confluence-Seiten) gefunden – sie stehen "
                    "unten. Gib in hoechstens %d Saetzen einen hilfreichen Ueberblick: "
                    "worum es in den Treffern geht und welche Themen/Vorgaenge relevant "
                    "sind. Beziehe dich konkret auf die gelisteten Inhalte. Es liegen "
                    "Treffer vor – behaupte NICHT, es gaebe keine Informationen. Antworte "
                    "auf Deutsch in lesbarem Fliesstext (kein JSON)." % lines)
        sysp = ((system_prompt.strip() + "\n\n") if system_prompt.strip() else "") + base
        src = "\n".join("- [%s] %s — %s" % (b.get("source", ""), b.get("title", ""),
                                            b.get("summary", ""))
                        for b in blocks[:10])
        user_text = "Anfrage: %s\n\nGefundene Treffer (%d):\n%s" % (query, len(blocks), src)
        provider = get_provider(
            config.LLM_PROVIDER, config.current_api_key, config.current_api_url,
            auth_method=config.current_auth_method,
            session_key=config.current_session_key, prompt_tool_calling=False)
        resp = await provider.generate_response(
            model=config.current_model, system_prompt=sysp,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=user_text)])],
            tools=[])
        return "".join(p.text for p in (resp.parts or []) if getattr(p, "text", None)).strip()
    except Exception as e:
        print("[Support] AI-Zusammenfassung fehlgeschlagen: %s" % e, flush=True)
        return ""


async def _support_summarize_block(b: dict, lines: int, lang: str, system_prompt: str):
    """Erzeugt eine mehrzeilige KI-Zusammenfassung EINES Treffers (Ticket /
    Confluence-Seite / Wissens-Chunk) und schreibt sie in ``b['summary']``.
    Bei Jira wird zusaetzlich die Beschreibung + die letzten Kommentare nachgeladen.
    Best effort – Fehler lassen die urspruengliche Kurzfassung unveraendert."""
    try:
        lines = max(2, min(int(lines or 4), 20))
    except (TypeError, ValueError):
        lines = 4
    content = (b.get("_content") or b.get("summary") or "").strip()
    # Jira: vollstaendigen Vorgang (Beschreibung + Kommentare) nachladen
    if b.get("source") == "JIRA" and b.get("_key"):
        try:
            from backend.jira_client import html_to_text as _jt
            c = _jira_client()
            it = await asyncio.to_thread(c.get_issue, b["_key"])
            f = it.get("fields", {}) or {}
            parts = [b.get("title", ""), f.get("summary") or ""]
            desc = _jt(f.get("description") or "", 3000)
            if desc:
                parts.append(desc)
            for cm in (((f.get("comment") or {}).get("comments")) or [])[-3:]:
                parts.append("Kommentar: " + _jt(cm.get("body") or "", 500))
            content = "\n".join(p for p in parts if p).strip()
        except Exception as e:
            print("[Support] Jira-Detail %s fehlgeschlagen: %s" % (b.get("_key"), e), flush=True)
    if not content:
        return
    try:
        from backend.llm import get_provider
        from google.genai import types
        if str(lang).lower().startswith("en"):
            base = ("Summarize the following item (support ticket, knowledge/Confluence "
                    "page) in at most %d sentences as readable English prose (no JSON, no "
                    "bullet points). Focus on the essential facts, the problem and any "
                    "solution. Reply only with the summary." % lines)
        else:
            base = ("Fasse den folgenden Eintrag (Support-Ticket, Wissens-/Confluence-Seite) "
                    "in hoechstens %d Saetzen als lesbaren deutschen Fliesstext zusammen "
                    "(kein JSON, keine Aufzaehlung). Konzentriere dich auf die wesentlichen "
                    "Fakten, das Problem und – falls vorhanden – die Loesung. Antworte nur "
                    "mit der Zusammenfassung." % lines)
        sysp = ((system_prompt.strip() + "\n\n") if (system_prompt or "").strip() else "") + base
        user_text = "%s\n\n%s" % (b.get("title", ""), content[:6000])
        provider = get_provider(
            config.LLM_PROVIDER, config.current_api_key, config.current_api_url,
            auth_method=config.current_auth_method,
            session_key=config.current_session_key, prompt_tool_calling=False)
        resp = await provider.generate_response(
            model=config.current_model, system_prompt=sysp,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=user_text)])],
            tools=[])
        txt = "".join(p.text for p in (resp.parts or []) if getattr(p, "text", None)).strip()
        if txt:
            b["summary"] = txt
    except Exception as e:
        print("[Support] Pro-Treffer-Zusammenfassung fehlgeschlagen: %s" % e, flush=True)


def _support_jira_base() -> str:
    """Basis-URL der Jira-Instanz (fuer das Verlinken von Ticket-Keys in
    Ausgabetexten), oder leer wenn Jira nicht aktiv/konfiguriert."""
    try:
        if _skill_active("jira"):
            c = _jira_client()
            if c.configured:
                return (c.base or "").rstrip("/")
    except Exception:
        pass
    return ""


# ─── Userspezifische Support-Anweisungen (dauerhaft, sessionuebergreifend) ────
def _support_instr_path(user: str) -> Path:
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in (user or "anon")).strip("_") or "anon"
    d = Path(__file__).parent.parent / "data" / "support_instructions"
    d.mkdir(parents=True, exist_ok=True)
    return d / (safe + ".md")


def _load_support_instructions(user: str) -> str:
    try:
        p = _support_instr_path(user)
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except Exception:
        return ""


@app.get("/api/support/instructions")
async def support_instructions_get(user: str = Depends(require_auth)):
    """Liest die persoenlichen Support-Anweisungen des Benutzers (Markdown)."""
    return JSONResponse({"ok": True, "instructions": _load_support_instructions(user)})


@app.post("/api/support/instructions")
async def support_instructions_set(request: Request, user: str = Depends(require_auth)):
    """Speichert die persoenlichen Support-Anweisungen (dauerhaft, je Benutzer)."""
    body = await request.json()
    text = (body.get("instructions") or "")[:20000]
    try:
        _support_instr_path(user).write_text(text, encoding="utf-8")
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/support/query")
async def support_query(request: Request):
    """Support-Anfrage: RAG-, Jira- und/oder Confluence-Treffer, nach Relevanz (%)
    sortiert, plus optionale LLM-Kurzzusammenfassung (mit vorangestelltem Prompt).

    Auth: Benutzer-Token (Bearer) ODER externer API-Key (Header ``X-API-Key`` bzw.
    Bearer = ``AGENT_API_KEY``) – fuer Aufrufe aus anderen Anwendungen.
    """
    import time as _t
    t0 = _t.time()
    # ── Auth: Benutzer-Token oder externer API-Key ──────────────────
    _bearer = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = verify_token(_bearer)
    if not user:
        user = "api" if _verify_agent_api_key(request) else None
    if not user:
        return JSONResponse({"ok": False, "error": "Nicht authentifiziert"}, status_code=401)
    if not _skill_active("support_assistant"):
        return JSONResponse({"ok": False, "error": "Support-Assistent ist nicht aktiv."}, status_code=403)
    body = await request.json()
    query = (body.get("text") or body.get("query") or "").strip()
    use_rag = body.get("rag", True)
    use_jira = body.get("jira", True)
    use_conf = body.get("confluence", True)
    use_ai = body.get("ai", True)
    open_only = body.get("open_only", True)
    lang = (body.get("lang") or "de")
    _sacfg = config.get_skill_states().get("support_assistant", {}).get("config", {}) or {}
    try:
        jira_limit = max(1, min(int(_sacfg.get("jira_limit") or 12), 50))
    except (TypeError, ValueError):
        jira_limit = 12
    if not query:
        return JSONResponse({"ok": False, "error": "Bitte eine Anfrage eingeben."}, status_code=400)

    qtokens = _support_tokens(query)
    blocks: list[dict] = []
    jira_total = None   # Gesamtzahl gefundener Jira-Treffer (vor 12er-Deckelung)

    # ── RAG (Wissensdatenbank) ──────────────────────────────────────
    if use_rag:
        try:
            from backend.tools.knowledge import rag_search
            results = await rag_search(query, 8)
            rag_max = max((s for s, _, _ in results), default=1.0) or 1.0
            for score, rel, chunk in results:
                pct = round(score * 100) if rag_max <= 1.0 else round(score / rag_max * 100)
                pct = max(1, min(int(pct), 100))
                stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                title, summary = _support_readable(stem, chunk)
                link = await asyncio.to_thread(_rag_source_link, rel, chunk)
                blocks.append({"source": "WISSEN", "title": title,
                               "summary": summary, "score": pct,
                               "link": link, "source_label": title,
                               "doc": rel, "doc_name": rel.rsplit("/", 1)[-1]})
        except Exception as e:
            print("[Support] RAG-Suche fehlgeschlagen: %s" % e, flush=True)

    # ── Jira-Tickets ────────────────────────────────────────────────
    if use_jira and _skill_active("jira"):
        try:
            from backend.jira_client import JiraError, issue_brief
            c = _jira_client()
            if c.configured:
                jql = _support_jira_jql(query, open_only)
                data = await asyncio.to_thread(c.search, jql, jira_limit)
                jira_total = data.get("total")
                for i, it in enumerate(data.get("issues", [])):
                    b = issue_brief(it, c.base)
                    overlap = len(qtokens & _support_tokens(b.get("summary") or "")) / (len(qtokens) or 1)
                    # Treffer sind relevanz-sortiert → Rang-Komponente, durch Titel-Overlap angehoben
                    pct = max(20, min(round(max(overlap * 100, 85 - i * 8)), 96))
                    meta = " · ".join(x for x in [b.get("status"), b.get("type"),
                                                  b.get("assignee")] if x)
                    summary = (b.get("summary") or "")
                    if meta:
                        summary += " — " + meta
                    blocks.append({"source": "JIRA", "title": b.get("key") or "Ticket",
                                   "summary": _two_line(summary, 600), "score": pct,
                                   "link": b.get("link") or "",
                                   "source_label": b.get("key") or "Ticket",
                                   "key": b.get("key")})
        except JiraError as e:
            print("[Support] Jira-Suche fehlgeschlagen: %s" % e, flush=True)
        except Exception as e:
            print("[Support] Jira-Suche Fehler: %s" % e, flush=True)

    # ── Confluence-Seiten ───────────────────────────────────────────
    if use_conf and _skill_active("confluence"):
        from backend.confluence_client import ConfluenceError as _CErr, html_to_text as _cf_html
        try:
            cc = _confluence_client()
            if cc.configured:
                _sa = config.get_skill_states().get("support_assistant", {}).get("config", {}) or {}
                _mode = _sa.get("conf_filter_mode") or "off"
                _spaces = _sa.get("conf_spaces") or []
                _terms = _support_terms(query)
                _filt_spaces = _spaces if (_mode in ("whitelist", "blacklist") and _spaces) else None
                data = await asyncio.to_thread(cc.search_advanced, _terms, _filt_spaces,
                                               _mode == "blacklist", 6)
                for i, r in enumerate(data.get("results", [])):
                    title = r.get("title") or "Seite"
                    summary = ""
                    try:
                        pg = await asyncio.to_thread(cc.get_page, r.get("id"), None, None)
                        raw = (((pg.get("body") or {}).get("storage") or {}).get("value")) or ""
                        summary = _cf_html(raw, 600)
                    except Exception:
                        pass
                    overlap = len(qtokens & _support_tokens(title + " " + summary)) / (len(qtokens) or 1)
                    # relevanz-sortiert → Rang-Komponente, durch Overlap angehoben
                    pct = max(20, min(round(max(overlap * 100, 86 - i * 9)), 96))
                    blocks.append({"source": "CONFLUENCE", "title": title,
                                   "summary": _two_line(summary or title, 600), "score": pct,
                                   "link": cc.link_for(data, r), "source_label": title})
        except _CErr as e:
            print("[Support] Confluence-Suche fehlgeschlagen: %s" % e, flush=True)
        except Exception as e:
            print("[Support] Confluence-Suche Fehler: %s" % e, flush=True)

    blocks.sort(key=lambda b: b["score"], reverse=True)

    cfg = config.get_skill_states().get("support_assistant", {}).get("config", {}) or {}

    def _cap(v, d):
        try:
            return max(2, min(int(v), 20))
        except (TypeError, ValueError):
            return d
    sum_max = _cap(cfg.get("summary_lines"), 5)   # Admin-Maximum
    res_max = _cap(cfg.get("result_lines"), 2)
    # Benutzer-Vorgabe (sitzungsueberdauernd im Browser) – auf [2, Maximum] begrenzt
    eff_sum = sum_max
    if body.get("summary_lines") is not None:
        eff_sum = max(2, min(_cap(body.get("summary_lines"), sum_max), sum_max))

    ai_summary = ""
    if use_ai:
        _sys = cfg.get("system_prompt") or ""
        _user_instr = _load_support_instructions(user)
        if _user_instr.strip():
            _sys = ((_sys + "\n\n") if _sys.strip() else "") + \
                "Persoenliche Anweisungen des Benutzers (immer beachten):\n" + _user_instr.strip()
        ai_summary = await _support_ai_summary(query, blocks, _sys, eff_sum, lang)

    _record_support_history(user, query, len(blocks))

    return JSONResponse({
        "ok": True, "query": query,
        "jira_active": _skill_active("jira"),
        "confluence_active": _skill_active("confluence"),
        "jira_base": _support_jira_base(),  # fuer Ticket-Key-Links in Ausgabetexten
        "blocks": blocks,
        "ai_summary": ai_summary,
        "result_lines": res_max,           # Maximum (Anzeige-Begrenzung clientseitig)
        "summary_lines_max": sum_max,
        "result_lines_max": res_max,
        "jira_total": jira_total,          # Gesamtzahl gefundener Jira-Treffer
        "open_only": bool(open_only),
        "took_ms": int((_t.time() - t0) * 1000),
    })


@app.post("/api/support/summarize")
async def support_summarize(request: Request):
    """On-Demand-KI-Zusammenfassung EINES Treffers (Button je Ergebnisbox).
    Aktuell fuer Jira-Tickets: laedt den Vorgang (Beschreibung + Kommentare) und
    fasst ihn in ``result_lines`` Saetzen zusammen.

    Auth: Benutzer-Token (Bearer) ODER externer API-Key (analog /api/support/query).
    """
    _bearer = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = verify_token(_bearer)
    if not user:
        user = "api" if _verify_agent_api_key(request) else None
    if not user:
        return JSONResponse({"ok": False, "error": "Nicht authentifiziert"}, status_code=401)
    if not _skill_active("support_assistant"):
        return JSONResponse({"ok": False, "error": "Support-Assistent ist nicht aktiv."}, status_code=403)
    body = await request.json()
    source = (body.get("source") or "JIRA").upper()
    key = (body.get("key") or "").strip()
    lang = body.get("lang") or "de"
    if source != "JIRA" or not key:
        return JSONResponse({"ok": False, "error": "Nur Jira-Tickets werden unterstuetzt."},
                            status_code=400)
    if not _skill_active("jira"):
        return JSONResponse({"ok": False, "error": "Jira-Skill ist nicht aktiv."}, status_code=403)

    cfg = config.get_skill_states().get("support_assistant", {}).get("config", {}) or {}

    def _cap(v, d):
        try:
            return max(2, min(int(v), 20))
        except (TypeError, ValueError):
            return d
    res_max = _cap(cfg.get("result_lines"), 2)
    lines = res_max
    if body.get("lines") is not None:
        lines = max(2, min(_cap(body.get("lines"), res_max), res_max))

    b = {"source": "JIRA", "key": key, "_key": key, "title": key, "summary": ""}
    await _support_summarize_block(b, lines, lang, cfg.get("system_prompt") or "")
    summary = (b.get("summary") or "").strip()
    if not summary:
        return JSONResponse({"ok": False, "error": "Zusammenfassung fehlgeschlagen."},
                            status_code=502)
    return JSONResponse({"ok": True, "key": key, "summary": summary,
                         "jira_base": _support_jira_base()})


# ─── Support-Verlauf (benutzerabhaengig) ─────────────────────────────

_SUPPORT_HIST_FILE = Path(__file__).parent.parent / "data" / "support_history.json"
_support_hist_lock = None
_SUPPORT_HIST_MAX = 50


def _get_hist_lock():
    global _support_hist_lock
    if _support_hist_lock is None:
        import threading as _thr
        _support_hist_lock = _thr.Lock()
    return _support_hist_lock


def _load_support_history() -> dict:
    try:
        if _SUPPORT_HIST_FILE.exists():
            return json.loads(_SUPPORT_HIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _record_support_history(user: str, query: str, total: int):
    """Fuegt eine Anfrage dem benutzerabhaengigen Verlauf hinzu (Deduplizierung,
    Cap auf _SUPPORT_HIST_MAX)."""
    query = (query or "").strip()
    if not query:
        return
    with _get_hist_lock():
        data = _load_support_history()
        entries = data.get(user, [])
        # gleiche Anfrage entfernen (kommt neu nach oben)
        entries = [e for e in entries if (e.get("query") or "").strip().lower() != query.lower()]
        entries.insert(0, {"query": query, "ts": int(time.time()), "total": total})
        data[user] = entries[:_SUPPORT_HIST_MAX]
        try:
            _SUPPORT_HIST_FILE.parent.mkdir(parents=True, exist_ok=True)
            _SUPPORT_HIST_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        except Exception as e:
            print("[Support] Verlauf speichern fehlgeschlagen: %s" % e, flush=True)


@app.get("/api/support/history")
async def support_history_get(user: str = Depends(require_auth)):
    """Liefert den Such-Verlauf des angemeldeten Benutzers (neueste zuerst)."""
    data = _load_support_history()
    return JSONResponse({"ok": True, "entries": data.get(user, [])})


@app.delete("/api/support/history")
async def support_history_clear(user: str = Depends(require_auth)):
    """Loescht den Such-Verlauf des angemeldeten Benutzers."""
    with _get_hist_lock():
        data = _load_support_history()
        if user in data:
            data.pop(user, None)
            try:
                _SUPPORT_HIST_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
            except Exception:
                pass
    return JSONResponse({"ok": True})


# ─── Agent Task API (extern, z.B. für Vision-Aktionen) ───────────────

def _is_valid_agent_key(presented: str) -> bool:
    """Prüft einen präsentierten Key timing-sicher gegen den Legacy-Key
    (AGENT_API_KEY) ODER einen der benannten Keys. Genutzt von HTTP- UND
    WebSocket-Auth (Konsistenz: benannte Keys gelten ueberall)."""
    if not presented:
        return False
    candidates = []
    if config.AGENT_API_KEY:
        candidates.append(config.AGENT_API_KEY)
    candidates.extend(k.get("key", "") for k in _load_agent_keys() if k.get("key"))
    for c in candidates:
        if c and hmac.compare_digest(presented, c):
            return True
    return False


def _verify_agent_api_key(request: Request) -> bool:
    """Prüft API-Key aus X-API-Key Header oder Bearer Token gegen Legacy- ODER
    benannte Keys."""
    presented = request.headers.get("X-API-Key", "") \
        or request.headers.get("Authorization", "").replace("Bearer ", "")
    return _is_valid_agent_key(presented)


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
async def get_knowledge_stats(user: str = Depends(require_auth)):
    """Gibt Statistiken der Knowledge Base zurück."""
    from backend.tools.knowledge import get_stats
    data = get_stats()
    # Mount-Pfade aus der Ordner-Liste herausfiltern – sie erscheinen unter "Netzwerk-Freigaben"
    mount_prefix = str(_MOUNT_BASE)
    data["folders"] = [f for f in data.get("folders", [])
                       if not f["path"].startswith(mount_prefix)]
    return JSONResponse(data)


@app.post("/api/knowledge/reindex")
async def reindex_knowledge(user: str = Depends(require_knowledge_editor)):
    """Startet vollständigen Neuaufbau des Knowledge-Index (non-blocking)."""
    import asyncio as _asyncio
    from backend.tools.knowledge import force_reindex, get_index_progress, _set_progress
    progress = get_index_progress()
    if progress.get("running"):
        return JSONResponse({"started": False, "message": "Indizierung läuft bereits"})
    # Im Hintergrund starten, danach Speicher freigeben
    async def _run_reindex():
        await _asyncio.to_thread(force_reindex)
        try:
            from backend.tools.vector_store import release_memory_to_os
            await _asyncio.to_thread(release_memory_to_os)
        except Exception:
            pass
    asyncio.create_task(_run_reindex())
    return JSONResponse({"started": True})


@app.get("/api/knowledge/index_progress")
async def get_knowledge_index_progress(user: str = Depends(require_auth)):
    """Liefert aktuellen Fortschritt der Indizierung."""
    from backend.tools.knowledge import get_index_progress
    return JSONResponse(get_index_progress())


@app.get("/api/knowledge/learned_stats")
async def get_learned_stats(user: str = Depends(require_auth)):
    """Liefert Statistiken ueber automatisch gelernte Konversations-Fakten."""
    from backend.learning import get_learned_stats
    return JSONResponse(get_learned_stats())


@app.get("/api/knowledge/files")
async def get_knowledge_files(user: str = Depends(require_auth)):
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
async def delete_knowledge_file(request: Request, user: str = Depends(require_knowledge_editor)):
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
    # Aus FAISS-Index entfernen
    try:
        from backend.tools.knowledge import _get_vector_store
        vs = _get_vector_store()
        if vs:
            vs.remove_file(str(resolved))
    except Exception:
        pass
    return JSONResponse({"ok": True, "deleted": file_path})


@app.get("/api/knowledge/learned")
async def list_learned_files(user: str = Depends(require_auth)):
    """Listet alle automatisch gelernten Konversations-Dateien."""
    from backend.learning import LEARNED_DIR, PROJECT_ROOT as LRN_ROOT
    result = []
    if not LEARNED_DIR.exists():
        return JSONResponse(result)
    for md in sorted(LEARNED_DIR.rglob("conv_*.md"), reverse=True)[:100]:
        try:
            stat = md.stat()
            content = md.read_text(encoding="utf-8")
            # Titel aus erster Zeile
            first_line = content.splitlines()[0].lstrip("# ").strip() if content else md.name
            try:
                rel = str(md.relative_to(LRN_ROOT))
            except ValueError:
                rel = str(md)
            result.append({
                "path": rel,
                "name": md.name,
                "title": first_line[:80],
                "size_kb": round(stat.st_size / 1024, 1),
                "mtime": stat.st_mtime,
                "preview": content[:200],
            })
        except Exception:
            continue
    return JSONResponse(result)


def _kb_first_heading(content: str) -> str:
    """Erste Markdown-Ueberschrift bzw. erste nicht-leere Zeile als Titel."""
    for line in content.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("# ").strip()
    for line in content.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _kb_struct_summary(content: str) -> str:
    """Strukturelle Zusammenfassung: erster Fliesstext-Absatz (ohne Ueberschriften)."""
    for para in content.split("\n\n"):
        p = " ".join(l.strip() for l in para.splitlines() if not l.strip().startswith("#")).strip()
        if len(p) >= 30:
            return p[:400]
    return ""


def _kb_struct_facts(content: str) -> list[str]:
    """Strukturelle Fakten: Aufzaehlungs-/Inhaltszeilen (ohne Ueberschriften), dedupliziert."""
    facts, seen = [], set()
    for line in content.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        s = s.lstrip("-*•0123456789. \t").strip()
        if len(s) < 8 or s in seen:
            continue
        seen.add(s)
        facts.append(s)
        if len(facts) >= 60:
            break
    return facts


def _collect_knowledge_documents(include_embeddings: bool) -> tuple[list[dict], dict]:
    """Sammelt die Wissensbasis als Dokumente im Extraktor-Schema (strukturell, ohne LLM).
    Gruppiert die Vektor-DB-Chunks pro Quelldatei; ergaenzt gelernte conv_*.md, die
    (noch) nicht indexiert sind. Gibt (documents, vector_meta)."""
    import hashlib as _hl
    from pathlib import Path as _P
    docs_by_file: dict[str, dict] = {}
    vmeta = {"available": False, "file_count": 0, "chunk_count": 0}
    try:
        from backend.tools.knowledge import _get_vector_store
        vs = _get_vector_store()
        if vs is not None:
            meta = list(getattr(vs, "_meta", []) or [])
            vmeta.update(available=True, file_count=vs.file_count(), chunk_count=vs.chunk_count())
            vecs = None
            if include_embeddings and meta:
                try:
                    vecs = vs._vectors_at(list(range(len(meta))))
                except Exception as _ve:
                    vmeta["embeddings_error"] = str(_ve)
            for i, m in enumerate(meta):
                fp = m.get("file_path") or "unbekannt"
                d = docs_by_file.setdefault(fp, {"chunks": [], "mtime": m.get("mtime")})
                ch = {"chunk_index": m.get("chunk_index"), "text": m.get("text", "")}
                if vecs is not None:
                    try:
                        ch["embedding"] = [round(float(x), 6) for x in vecs[i]]
                    except Exception:
                        pass
                d["chunks"].append(ch)
    except Exception as e:
        vmeta["error"] = str(e)

    # Gelernte Konversationen ergaenzen, falls nicht im Vektor-Index
    try:
        from backend.learning import LEARNED_DIR
        if LEARNED_DIR.exists():
            indexed = {str(_P(fp).resolve()) for fp in docs_by_file}
            for md in LEARNED_DIR.rglob("conv_*.md"):
                if str(md.resolve()) in indexed:
                    continue
                try:
                    docs_by_file[str(md)] = {
                        "chunks": [{"chunk_index": 0, "text": md.read_text(encoding="utf-8")}],
                        "mtime": md.stat().st_mtime,
                    }
                except Exception:
                    continue
    except Exception:
        pass

    documents = []
    for fp, d in docs_by_file.items():
        chunks = sorted(d["chunks"], key=lambda c: (c.get("chunk_index") or 0))
        content = "\n\n".join(c["text"] for c in chunks if c.get("text"))
        title = _kb_first_heading(content) or _P(fp).name
        doc = {
            "id": _hl.md5(fp.encode("utf-8")).hexdigest()[:8],
            "source": fp,
            "source_name": _P(fp).name,
            "title": title[:300],
            "summary": _kb_struct_summary(content),
            "facts": _kb_struct_facts(content),
            "qa_pairs": [],
            "content": content,
            "chunk_count": len(chunks),
            "mtime": d.get("mtime"),
            "enriched": False,
        }
        if include_embeddings:
            doc["chunks"] = chunks
        documents.append(doc)
    documents.sort(key=lambda x: (x.get("mtime") or 0), reverse=True)
    return documents, vmeta


def _zip_knowledge_export(payload: dict) -> bytes:
    import io as _io, zipfile as _zip
    buf = _io.BytesIO()
    with _zip.ZipFile(buf, "w", _zip.ZIP_DEFLATED) as zf:
        zf.writestr("wissen_export.json", json.dumps(payload, ensure_ascii=False, indent=2))
    return buf.getvalue()


def _zip_knowledge_export_split(payload: dict) -> bytes:
    """ZIP mit je EINER JSON-Datei pro Originaldokument (Verzeichnis 'dokumente/')
    plus _manifest.json (Metadaten + Dateiliste, ohne die Dokumente selbst)."""
    import io as _io, zipfile as _zip
    docs = payload.get("documents", [])
    manifest = {k: v for k, v in payload.items() if k != "documents"}
    files, seen = [], set()
    buf = _io.BytesIO()
    with _zip.ZipFile(buf, "w", _zip.ZIP_DEFLATED) as zf:
        for doc in docs:
            base = "".join(c if (c.isalnum() or c in "._-") else "_"
                           for c in str(doc.get("source_name") or doc.get("id") or "dokument"))
            base = base.strip("_")[:80] or "dokument"
            did = str(doc.get("id") or "")
            name = f"dokumente/{did}__{base}.json"
            n, i = name, 1
            while n in seen:   # Kollisionen vermeiden
                n = f"dokumente/{did}_{i}__{base}.json"
                i += 1
            seen.add(n)
            zf.writestr(n, json.dumps(doc, ensure_ascii=False, indent=2))
            files.append({"file": n, "id": doc.get("id"),
                          "title": doc.get("title"), "source": doc.get("source")})
        manifest["files"] = files
        zf.writestr("_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buf.getvalue()


@app.get("/api/knowledge/export")
async def export_knowledge_zip(embeddings: int = 0, llm: int = 0, split: int = 0, user: str = Depends(require_knowledge_editor)):
    """Exportiert die komplette Wissensbasis als JSON (ZIP) im Informationsextraktor-
    Schema (ein Dokument je Quelle mit title/summary/facts/qa_pairs/content).
    ?embeddings=1 = Roh-Vektoren je Chunk; ?llm=1 = facts/qa_pairs per LLM nachextrahieren;
    ?split=1 = je eine JSON-Datei pro Dokument (Verzeichnis 'dokumente/') statt einer grossen."""
    import datetime as _dt
    documents, vmeta = await asyncio.to_thread(_collect_knowledge_documents, bool(embeddings))

    enrich_errors = 0
    if llm and documents:
        from backend.web_extractor import extract_structured_from_text
        sem = asyncio.Semaphore(4)   # begrenzte Parallelitaet gegen Token-/Last-Spitzen

        async def _enrich(doc):
            nonlocal enrich_errors
            async with sem:
                try:
                    ex = await extract_structured_from_text(doc["content"], doc["title"])
                    doc["title"] = ex["title"] or doc["title"]
                    doc["summary"] = ex["summary"]
                    doc["facts"] = ex["facts"]
                    doc["qa_pairs"] = ex["qa_pairs"]
                    doc["enriched"] = True
                except Exception:
                    enrich_errors += 1
        await asyncio.gather(*[_enrich(d) for d in documents[:80]])  # Cap gegen Extremlaeufe

    payload = {
        "schema": "jarvis-knowledge-export/v1",
        "format": "informationsextraktor",
        "exported_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "llm_enriched": bool(llm),
        "embeddings_included": bool(embeddings),
        "enrich_errors": enrich_errors,
        "vector_store": vmeta,
        "document_count": len(documents),
        "documents": documents,
    }
    if embeddings:
        # Roh-Vektoren sind modellspezifisch -> ohne diese Angaben unbrauchbar.
        try:
            from backend.tools.vector_store import MODEL_NAME as _EMB_MODEL, EMBEDDING_DIM as _EMB_DIM
        except Exception:
            _EMB_MODEL, _EMB_DIM = "unbekannt", 0
        payload["embedding_model"] = {
            "name": _EMB_MODEL,
            "dim": _EMB_DIM,
            "normalized": True,
            "similarity": "cosine (Inner Product auf normierten Vektoren)",
            "passage_prefix": "passage: ",
            "query_prefix": "query: ",
            "note": ("Die 'embedding'-Vektoren sind NUR mit exakt diesem Modell sinnvoll "
                     "(gleicher Vektorraum). Ein anderes Zielsystem sollte sie ignorieren und "
                     "stattdessen 'text'/'content' mit dem eigenen Embedding-Modell neu einbetten."),
        }
    _builder = _zip_knowledge_export_split if split else _zip_knowledge_export
    data = await asyncio.to_thread(_builder, payload)
    _sfx = "_pro_dokument" if split else ""
    fname = f"jarvis_wissen{_sfx}_{_dt.datetime.now():%Y%m%d_%H%M%S}.zip"
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/api/knowledge/file_read")
async def read_knowledge_file(path: str, user: str = Depends(require_auth)):
    """Liest den Inhalt einer Text-Datei aus dem Knowledge-Verzeichnis."""
    from backend.tools.knowledge import _get_folders, PROJECT_ROOT
    from backend.learning import LEARNED_DIR
    resolved = (PROJECT_ROOT / path).resolve()
    # Sicherheitscheck: Datei muss in Knowledge- oder Learned-Verzeichnis liegen
    allowed = str(resolved).startswith(str(LEARNED_DIR.resolve()))
    if not allowed:
        for folder in _get_folders():
            try:
                resolved.relative_to(folder.resolve())
                allowed = True
                break
            except ValueError:
                continue
    if not allowed:
        return JSONResponse({"error": "Zugriff verweigert"}, status_code=403)
    if not resolved.is_file():
        return JSONResponse({"error": "Datei nicht gefunden"}, status_code=404)
    try:
        content = resolved.read_text(encoding="utf-8")
        return JSONResponse({"ok": True, "content": content})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/api/knowledge/file_write")
async def write_knowledge_file(request: Request, user: str = Depends(require_knowledge_editor)):
    """Aktualisiert den Inhalt einer gelernten Datei und re-indexiert sie in FAISS."""
    from backend.learning import LEARNED_DIR, PROJECT_ROOT as LRN_ROOT
    data = await request.json()
    path = data.get("path", "").strip()
    content = data.get("content", "")
    if not path:
        return JSONResponse({"error": "Kein Pfad"}, status_code=400)
    resolved = (LRN_ROOT / path).resolve()
    # Nur Dateien innerhalb LEARNED_DIR dürfen geschrieben werden
    if not str(resolved).startswith(str(LEARNED_DIR.resolve())):
        return JSONResponse({"error": "Zugriff verweigert"}, status_code=403)
    if not resolved.exists():
        return JSONResponse({"error": "Datei nicht gefunden"}, status_code=404)
    try:
        resolved.write_text(content, encoding="utf-8")
        # FAISS re-indexieren
        try:
            from backend.learning import _index_immediately
            _index_immediately(resolved, content)
        except Exception:
            pass
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/knowledge/open-folder")
async def open_knowledge_folder(request: Request, user: str = Depends(require_auth)):
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
    user: str = Depends(require_knowledge_editor),
):
    """Dateien per Browser-Upload in einen Knowledge-Ordner hochladen."""
    from backend.tools.knowledge import (
        _get_folders, PROJECT_ROOT,
        EXTENSIONS_TEXT, EXTENSIONS_PDF, EXTENSIONS_DOCX,
        EXTENSIONS_XLSX, EXTENSIONS_PPTX, EXTENSIONS_VIDEO, EXTENSIONS_AUDIO,
        EXTENSIONS_IMAGE,
    )

    all_exts = (EXTENSIONS_TEXT | EXTENSIONS_PDF | EXTENSIONS_DOCX |
                EXTENSIONS_XLSX | EXTENSIONS_PPTX | EXTENSIONS_VIDEO | EXTENSIONS_AUDIO |
                EXTENSIONS_IMAGE)

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


# ─── Web-Extraktor ───────────────────────────────────────────────────────────

@app.post("/api/knowledge/extract")
async def knowledge_extract(request: Request, user: str = Depends(require_knowledge_editor)):
    """Ruft eine URL ab, extrahiert per LLM Wissen und speichert als Pending-Dokument."""
    body = await request.json()
    url = (body.get("url") or "").strip()
    if not url:
        return JSONResponse({"error": "Keine URL angegeben"}, status_code=400)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        from backend.web_extractor import extract_from_url
        doc = await extract_from_url(url)
        return JSONResponse(doc)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/knowledge/extract/upload")
async def knowledge_extract_upload(
    file: UploadFile = File(...),
    user: str = Depends(require_knowledge_editor),
):
    """Datei hochladen → Text extrahieren → LLM → Pending-Dokument."""
    _SUPPORTED = {
        ".pdf", ".txt", ".md", ".rst", ".csv",
        ".docx", ".doc", ".xlsx", ".ods", ".pptx",
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp",
        ".mp3", ".m4a", ".wav", ".ogg",
        ".mp4", ".mov", ".mkv", ".avi",
    }
    suffix = Path(file.filename or "file").suffix.lower()
    if suffix not in _SUPPORTED:
        return JSONResponse(
            {"error": f"Format nicht unterstützt: '{suffix}'. Erlaubt: {', '.join(sorted(_SUPPORTED))}"},
            status_code=415,
        )
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        return JSONResponse({"error": "Datei zu groß (max. 50 MB)"}, status_code=413)
    try:
        from backend.web_extractor import extract_from_file
        doc = await extract_from_file(file.filename, content)
        return JSONResponse(doc, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/knowledge/extract/confluence")
async def knowledge_extract_confluence(request: Request, user: str = Depends(require_knowledge_editor)):
    """Importiert Confluence-Inhalte in den Extraktor.

    Body:
    - ``{"page_id": "123"}`` – Einzelseite (synchron)
    - ``{"space": "KEY"}``  – ganzer Bereich (Hintergrund-Job)
    - ``{"audit": false}``  – auditlos: direkt in die Wissens-DB schreiben
      (ohne Pending/Review). Standard ist ``audit: true`` (mit Review).
    """
    from backend.confluence_client import ConfluenceError, html_to_text
    from backend.web_extractor import extract_to_pending, approve_pending
    body = await request.json()
    page_id = (body.get("page_id") or "").strip()
    space = (body.get("space") or "").strip()
    audit = body.get("audit", True)  # False = auditloser Direkt-Import
    c = _confluence_client()
    if not c.configured:
        return JSONResponse({"error": "Confluence ist nicht konfiguriert."}, status_code=400)

    def _page_text(page: dict) -> str:
        raw = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
        return html_to_text(raw, 8000)

    # ── Einzelseite (synchron) ──────────────────────────────────────────
    if page_id:
        try:
            page = await asyncio.to_thread(c.get_page, page_id, None, None)
            text = _page_text(page)
            if not text.strip():
                return JSONResponse({"error": "Seite enthält keinen lesbaren Text."}, status_code=422)
            doc = await extract_to_pending(text, page.get("title", ""), c.link_for(page, page))
            if not audit:
                # auditlos: sofort in die Wissens-DB schreiben
                res = await asyncio.to_thread(approve_pending, doc["id"], True)
                return JSONResponse({"ok": True, "audited": False, "id": doc["id"],
                                     "title": doc["title"], "file": res.get("file")},
                                    status_code=201)
            return JSONResponse(doc, status_code=201)
        except ConfluenceError as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── Ganzer Bereich (Hintergrund-Job) ────────────────────────────────
    if space:
        try:
            pages = await asyncio.to_thread(c.pages_in_space, space, 500)
        except ConfluenceError as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        if not pages:
            return JSONResponse({"error": "Bereich enthält keine Seiten."}, status_code=404)

        async def _bulk(space_key: str, page_list: list, do_audit: bool):
            for p in page_list:
                try:
                    full = await asyncio.to_thread(c.get_page, p["id"], None, None)
                    text = _page_text(full)
                    if text.strip():
                        doc = await extract_to_pending(text, full.get("title", ""),
                                                       c.link_for(full, full))
                        if not do_audit:
                            # auditlos: schreiben, aber NICHT pro Seite reindizieren
                            await asyncio.to_thread(approve_pending, doc["id"], False)
                except Exception as ex:
                    print(f"[Confluence-Bulk] Seite {p.get('id')} übersprungen: {ex}", flush=True)
            if not do_audit:
                # nach allen Seiten EINMAL reindizieren
                try:
                    from backend.tools.knowledge import force_reindex
                    await asyncio.to_thread(force_reindex)
                except Exception as ex:
                    print(f"[Confluence-Bulk] Reindex fehlgeschlagen: {ex}", flush=True)

        task = asyncio.create_task(_bulk(space, pages, audit))
        _bg_confluence_tasks.add(task)
        task.add_done_callback(_bg_confluence_tasks.discard)
        return JSONResponse({"ok": True, "started": True, "total": len(pages),
                             "audited": bool(audit), "space": space}, status_code=202)

    return JSONResponse({"error": "page_id oder space erforderlich."}, status_code=400)


@app.get("/api/knowledge/pending")
async def knowledge_pending_list(user: str = Depends(require_auth)):
    from backend.web_extractor import list_pending
    return JSONResponse(list_pending())


@app.get("/api/knowledge/pending/{doc_id}")
async def knowledge_pending_get(doc_id: str, user: str = Depends(require_auth)):
    from backend.web_extractor import get_pending
    doc = get_pending(doc_id)
    if not doc:
        return JSONResponse({"error": "Nicht gefunden"}, status_code=404)
    return JSONResponse(doc)


@app.patch("/api/knowledge/pending/{doc_id}")
async def knowledge_pending_update(doc_id: str, request: Request, user: str = Depends(require_knowledge_editor)):
    from backend.web_extractor import update_pending
    data = await request.json()
    ok = update_pending(doc_id, data)
    return JSONResponse({"ok": ok})


@app.post("/api/knowledge/pending/{doc_id}/approve")
async def knowledge_pending_approve(doc_id: str, user: str = Depends(require_knowledge_editor)):
    from backend.web_extractor import approve_pending
    try:
        result = approve_pending(doc_id)
        return JSONResponse({"ok": True, **result})
    except FileNotFoundError:
        return JSONResponse({"error": "Nicht gefunden"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/knowledge/pending/{doc_id}")
async def knowledge_pending_delete(doc_id: str, user: str = Depends(require_knowledge_editor)):
    from backend.web_extractor import delete_pending
    ok = delete_pending(doc_id)
    return JSONResponse({"ok": ok})


@app.delete("/api/knowledge/extract/file")
async def knowledge_extract_file_delete(request: Request, user: str = Depends(require_knowledge_editor)):
    """Löscht eine genehmigte Extraktions-MD-Datei und startet Reindex."""
    body = await request.json()
    rel_path = (body.get("file") or "").strip().lstrip("/")
    if not rel_path:
        return JSONResponse({"ok": False, "error": "Kein Dateipfad"}, status_code=400)
    from backend.config import config as _cfg
    target = Path(_cfg.PROJECT_ROOT) / rel_path
    # Sicherheitscheck: Datei muss im knowledge-Ordner liegen und extract_ prefix haben
    try:
        target.resolve().relative_to(Path(_cfg.PROJECT_ROOT).resolve())
    except ValueError:
        return JSONResponse({"ok": False, "error": "Ungültiger Pfad"}, status_code=400)
    if not target.name.startswith("extract_"):
        return JSONResponse({"ok": False, "error": "Nur extract_*-Dateien können gelöscht werden"}, status_code=400)
    if target.exists():
        target.unlink()
    # Reindex im Hintergrund
    asyncio.create_task(asyncio.to_thread(lambda: __import__('backend.tools.knowledge', fromlist=['force_reindex']).force_reindex()))
    return JSONResponse({"ok": True})


@app.get("/api/knowledge/mounts")
async def list_mounts(user: str = Depends(require_auth)):
    mounts = _get_mounts_config()
    result = []
    for i, m in enumerate(mounts):
        mp = _mount_path(i)
        result.append({
            "type": m.get("type", "smb"),
            "source": m.get("source", ""),
            "active": mp.is_mount(),
            "auto_mount": m.get("auto_mount", True),
            "mountpoint": str(mp),
        })
    return JSONResponse(result)


@app.post("/api/knowledge/mounts")
async def add_mount(request: Request, user: str = Depends(require_auth)):
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
async def remove_mount(idx: int, user: str = Depends(require_auth)):
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


@app.put("/api/knowledge/mounts/{idx}")
async def update_mount(idx: int, request: Request, user: str = Depends(require_auth)):
    """Aktualisiert Typ, Quelle und Credentials einer bestehenden Freigabe."""
    mounts = _get_mounts_config()
    if idx < 0 or idx >= len(mounts):
        return JSONResponse({"error": "Ungueltiger Index"}, status_code=404)
    data = await request.json()
    source = data.get("source", "").strip()
    if not source:
        return JSONResponse({"error": "Quelle fehlt"}, status_code=400)
    # Unmounten falls aktiv (neue Credentials erfordern Neuverbindung)
    mp = _mount_path(idx)
    if mp.is_mount():
        await asyncio.to_thread(subprocess.run, ["umount", str(mp)], capture_output=True, timeout=10)
    mounts[idx] = {
        "type": data.get("type", "smb"),
        "source": source,
        "username": data.get("username", ""),
        "password": data.get("password", ""),
    }
    _save_mounts_config(mounts)
    return JSONResponse({"ok": True})


@app.post("/api/knowledge/mounts/{idx}/mount")
async def mount_share(idx: int, user: str = Depends(require_auth)):
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

    # auto_mount aktivieren – Benutzer will diese Freigabe verbunden haben
    mounts[idx]["auto_mount"] = True
    _save_mounts_config(mounts)

    # Nach erfolgreichem Mount Index automatisch neu aufbauen
    try:
        from backend.tools.knowledge import force_reindex
        await asyncio.to_thread(force_reindex)
        print(f"[knowledge] Reindex nach Mount {source} → {mp}", flush=True)
    except Exception as e:
        print(f"[knowledge] Reindex nach Mount fehlgeschlagen: {e}", flush=True)

    return JSONResponse({"ok": True, "mountpoint": str(mp)})


@app.post("/api/knowledge/mounts/{idx}/unmount")
async def unmount_share(idx: int, user: str = Depends(require_auth)):
    mp = _mount_path(idx)
    if not mp.is_mount():
        # Auch bei bereits getrenntem Mount: auto_mount deaktivieren
        mounts = _get_mounts_config()
        if 0 <= idx < len(mounts):
            mounts[idx]["auto_mount"] = False
            _save_mounts_config(mounts)
        return JSONResponse({"ok": True, "hint": "War nicht gemountet"})

    result = await asyncio.to_thread(subprocess.run, ["umount", str(mp)], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        return JSONResponse({"error": f"Unmount fehlgeschlagen: {result.stderr.strip()}"}, status_code=500)

    # auto_mount deaktivieren – manuelle Trennung respektieren
    mounts = _get_mounts_config()
    if 0 <= idx < len(mounts):
        mounts[idx]["auto_mount"] = False
        _save_mounts_config(mounts)

    return JSONResponse({"ok": True})


@app.get("/api/knowledge/webdav/status")
async def webdav_status(user: str = Depends(require_auth)):
    """WebDAV-Status und Verbindungsdetails."""
    from backend.webdav import _get_webdav_config, is_webdav_enabled
    from backend.tools.knowledge import PROJECT_ROOT
    cfg = _get_webdav_config()
    enabled = is_webdav_enabled()
    # WebDAV zeigt nur den lokalen Knowledge-Ordner
    local_kb = PROJECT_ROOT / "data" / "knowledge"
    shares = [str(local_kb)]
    # Alle nicht-loopback IPv4-Adressen ermitteln
    import socket
    urls = []
    if enabled:
        try:
            hostname = socket.gethostname()
            all_ips = socket.gethostbyname_ex(hostname)[2]
        except Exception:
            all_ips = []
        # Fallback: hostname -I Methode
        try:
            import subprocess
            out = subprocess.check_output(["hostname", "-I"], text=True).strip()
            all_ips += out.split()
        except Exception:
            pass
        seen = set()
        for ip in all_ips:
            ip = ip.strip()
            if ip and not ip.startswith("127.") and not ip.startswith("::") and ip not in seen:
                seen.add(ip)
                urls.append(f"https://{ip}/webdav/")
        if not urls:
            urls = [f"https://{os.getenv('SERVER_IP','<server-ip>')}/webdav/"]
    return JSONResponse({
        "enabled": enabled,
        "urls": urls,
        "url": urls[0] if urls else None,
        "shares": shares if enabled else [],
        "username": cfg.get("username", "jarvis"),
        "password": cfg.get("password", "jarvis"),
    })


@app.post("/api/knowledge/webdav/config")
async def webdav_config(request: Request, user: str = Depends(require_auth)):
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

    # DAV-Cache invalidieren → nächster Request baut App neu (oder gibt 503 wenn disabled)
    try:
        if hasattr(app.state, "invalidate_dav_cache"):
            app.state.invalidate_dav_cache()
    except Exception:
        pass

    return JSONResponse({"ok": True, "enabled": webdav.get("enabled", False)})


# ─── Instructions API ─────────────────────────────────────────────────

INSTRUCTIONS_DIR = Path(__file__).parent.parent / "data" / "instructions"


@app.get("/api/instructions")
async def list_instructions(user: str = Depends(require_auth)):
    """Listet alle Instruction-Dateien auf."""
    INSTRUCTIONS_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(INSTRUCTIONS_DIR.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        files.append({"name": f.stem, "filename": f.name, "content": content})
    return JSONResponse({"files": files})


@app.get("/api/instructions/{name}")
async def get_instruction(name: str, user: str = Depends(require_auth)):
    """Liest eine einzelne Instruction-Datei."""
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
    if not safe_name:
        return JSONResponse({"error": "Ungültiger Name"}, status_code=400)
    filepath = INSTRUCTIONS_DIR / f"{safe_name}.md"
    if not filepath.exists():
        return JSONResponse({"error": "Datei nicht gefunden"}, status_code=404)
    return JSONResponse({"name": safe_name, "filename": filepath.name,
                         "content": filepath.read_text(encoding="utf-8")})


@app.post("/api/instructions/{name}")
async def save_instruction(name: str, request: Request, user: str = Depends(require_auth)):
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
async def delete_instruction(name: str, user: str = Depends(require_auth)):
    """Loescht eine Instruction-Datei."""
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
    if not safe_name:
        return JSONResponse({"error": "Ungültiger Name"}, status_code=400)
    filepath = INSTRUCTIONS_DIR / f"{safe_name}.md"
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
async def google_status(user: str = Depends(require_auth)):
    """Gibt den aktuellen Google-Auth-Status zurück."""
    from backend.google_auth import get_status
    import asyncio as _aio
    status = await _aio.to_thread(get_status)
    return JSONResponse(status)


@app.post("/api/google/device-start")
async def google_device_start(user: str = Depends(require_auth)):
    """Startet den Device Flow – gibt user_code + verification_url zurück."""
    from backend.google_auth import start_device_flow
    import asyncio as _aio
    result = await _aio.to_thread(start_device_flow)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.get("/api/google/device-status")
async def google_device_status(user: str = Depends(require_auth)):
    """Polling-Endpoint: Status des laufenden Device Flows."""
    from backend.google_auth import get_flow_status
    return JSONResponse(get_flow_status())


@app.post("/api/google/revoke")
async def google_revoke(user: str = Depends(require_auth)):
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
async def gog_status(user: str = Depends(require_auth)):
    """Gibt verbundene gog-Konten zurück."""
    import asyncio as _aio
    result = await _aio.to_thread(_run_gog, "auth", "list")
    return JSONResponse(result)


@app.post("/api/google/gog-setup")
async def gog_setup(request: Request, user: str = Depends(require_auth)):
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
async def gog_get_auth_url(request: Request, user: str = Depends(require_auth)):
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
async def gog_auth_exchange(request: Request, user: str = Depends(require_auth)):
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
async def gog_remove_account(request: Request, user: str = Depends(require_auth)):
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
async def openclaw_search(q: str = "", user: str = Depends(require_auth)):
    """Sucht Skills auf OpenClaw Marketplace.
    Gibt Ergebnisliste zurück – Import erfolgt separat.
    """

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
        print(f"[WARN] ClawHub API nicht erreichbar ({e})")

    return JSONResponse({"results": results, "query": query})


@app.get("/api/openclaw/workflow-task")
async def openclaw_workflow_task(
    description: str = "",
    user: str = Depends(require_auth),
):
    """Gibt den fertigen Agent-Task-Text zurück, der den Import-Workflow ausführt.
    Liest data/workflows/import_openclaw_skill.md und bettet ihn in den Task ein.
    """
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
async def vision_status(user: str = Depends(require_auth)):
    """Vision-Engine-Status + aktuelle Gesichter."""
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)
    return JSONResponse(engine.get_status())


@app.post("/api/vision/control")
async def vision_control(request: Request, user: str = Depends(require_auth)):
    """Kamera starten/stoppen. Body: {action: 'start'|'stop', source: '0'}."""
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
async def vision_snapshot(user: str = Depends(require_auth_or_query)):
    """Aktuelles Kamerabild als JPEG (mit Annotationen). Token via Header ODER ?token= Query."""
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

    Auth via ?token= Query ODER ?key=<stream_key> (fuer Server-zu-Server).
    Nutzung: Als Kamera-Quelle auf anderen Jarvis-Instanzen eintragen.
    """
    # Auth: normaler Token ODER konfigurierbarer Stream-Key
    token = request.query_params.get("token", "")
    stream_key = request.query_params.get("key", "")
    expected_key = config.get_skill_states().get("vision", {}).get("config", {}).get("stream_key", "jarvis-stream")
    if not verify_token(token) and stream_key != expected_key:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
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
async def vision_face_crop(index: int, user: str = Depends(require_auth_or_query)):
    """Aktuellen Face-Crop als JPEG. Token via Header ODER ?token= Query."""
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    with engine._lock:
        crops = list(engine._current_face_crops)
    if index < 0 or index >= len(crops) or not crops[index]:
        return JSONResponse({"error": "Kein Face-Crop verfuegbar"}, status_code=404)
    return Response(content=crops[index], media_type="image/jpeg")


@app.get("/api/vision/cameras")
async def vision_cameras(user: str = Depends(require_auth)):
    """Verfuegbare Kameras auflisten."""
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    import asyncio as _aio
    cameras = await _aio.to_thread(engine.list_cameras)
    return JSONResponse({"cameras": cameras})


@app.get("/api/vision/preview/{index}")
async def vision_preview(index: int, user: str = Depends(require_auth_or_query)):
    """Einzelbild einer bestimmten Kamera (fuer Preview)."""
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    import asyncio as _aio
    jpeg = await _aio.to_thread(engine.get_preview, index)
    if jpeg is None:
        return JSONResponse({"error": "Kamera nicht verfuegbar"}, status_code=404)
    return Response(content=jpeg, media_type="image/jpeg")


@app.get("/api/vision/profiles")
async def vision_profiles(user: str = Depends(require_auth)):
    """Alle Profile mit Aktionen auflisten."""
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    profiles = engine.list_profiles()
    actions = engine.get_available_actions()
    return JSONResponse({"profiles": profiles, "actions": actions})


@app.post("/api/vision/profiles")
async def vision_profile_update(request: Request, user: str = Depends(require_auth)):
    """Profil aktualisieren (Name, Aktion, Aktions-Wert)."""
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
async def vision_profile_rename(request: Request, user: str = Depends(require_auth)):
    """Profil umbenennen (z.B. nach Training mit Temp-Name)."""
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
async def vision_profile_delete(name: str, user: str = Depends(require_auth)):
    """Profil loeschen."""
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)
    msg = engine.delete_profile(name)
    return JSONResponse({"message": msg})


@app.get("/api/vision/thumbnail/{name}")
async def vision_thumbnail(name: str, user: str = Depends(require_auth_or_query)):
    """Profilbild (erstes Trainingsfoto) als JPEG. Token via Header ODER ?token= Query."""
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)

    jpeg = engine.get_thumbnail(name)
    if jpeg is None:
        return JSONResponse({"error": "Kein Thumbnail verfuegbar"}, status_code=404)
    return Response(content=jpeg, media_type="image/jpeg")


@app.post("/api/vision/training/start")
async def vision_training_start(request: Request, user: str = Depends(require_auth)):
    """Training starten. Body: {name: '...', samples: 30}."""
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
async def vision_training_stop(user: str = Depends(require_auth)):
    """Training stoppen + Modell neu berechnen."""
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)
    msg = engine.stop_training()
    return JSONResponse({"message": msg})


@app.get("/api/vision/training/status")
async def vision_training_status(user: str = Depends(require_auth)):
    """Training-Fortschritt abfragen."""
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)
    return JSONResponse(engine.get_training_status())


@app.get("/api/vision/events")
async def vision_events(limit: int = 50, user: str = Depends(require_auth)):
    """Letzte Erkennungs-Events."""
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)
    return JSONResponse({"events": engine.get_recent_events(limit)})


@app.post("/api/vision/cleanup")
async def vision_cleanup(user: str = Depends(require_auth)):
    """Alle Vision-Daten zuruecksetzen."""
    engine = _get_vision_engine()
    if not engine:
        return JSONResponse({"error": "Vision-Skill nicht geladen"}, status_code=503)
    msg = engine.cleanup()
    return JSONResponse({"message": msg})


@app.get("/api/vision/greet-audio/{name}")
async def vision_greet_audio(name: str, user: str = Depends(require_auth_or_query)):
    """Vorgerenderte Begruessungs-Audio (MP3 bevorzugt, WAV Fallback). Token via Header ODER ?token= Query."""

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


# ─── TTS API ─────────────────────────────────────────────────────────────────

@app.post("/api/tts")
async def tts_synthesize(request: Request):
    """Text-to-Speech via edge-tts. Gibt MP3-Audio zurück."""
    # Auth: Bearer-Token, X-API-Key als Login-Token oder Agent-API-Key
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    xkey = request.headers.get("X-API-Key", "")
    if not (verify_token(token) or verify_token(xkey) or _verify_agent_api_key(request)):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)

    body = await request.json()
    text  = body.get("text", "").strip()
    voice = body.get("voice", "de-DE-ConradNeural")

    if not text:
        return JSONResponse({"error": "Kein Text angegeben"}, status_code=400)

    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        audio_bytes = b"".join(chunks)
        if not audio_bytes:
            return JSONResponse({"error": "Keine Audiodaten generiert"}, status_code=500)
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache"},
        )
    except ImportError:
        return JSONResponse({"error": "edge-tts nicht installiert"}, status_code=503)
    except Exception as e:
        # Fallback auf Standardstimme wenn Voice ungültig
        if "voice" in str(e).lower() or "invalid" in str(e).lower():
            try:
                import edge_tts as _et
                communicate = _et.Communicate(text, "de-DE-KatjaNeural")
                chunks = []
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        chunks.append(chunk["data"])
                audio_bytes = b"".join(chunks)
                return Response(content=audio_bytes, media_type="audio/mpeg",
                                headers={"Cache-Control": "no-cache"})
            except Exception as e2:
                return JSONResponse({"error": str(e2)}, status_code=500)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/tts/voices")
async def tts_voices(request: Request):
    """Verfügbare edge-tts Stimmen (gefiltert nach Sprache, Standard: de-)."""
    # Auth: Bearer-Token, X-API-Key als Login-Token oder Agent-API-Key
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    xkey = request.headers.get("X-API-Key", "")
    if not (verify_token(token) or verify_token(xkey) or _verify_agent_api_key(request)):
        return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)

    locale = request.query_params.get("locale", "de-")
    try:
        import edge_tts
        all_voices = await edge_tts.list_voices()
        voices = [
            {"name": v["ShortName"], "gender": v["Gender"], "locale": v["Locale"],
             "display": v.get("FriendlyName", v["ShortName"])}
            for v in all_voices if v["Locale"].startswith(locale)
        ]
        return JSONResponse(voices)
    except ImportError:
        return JSONResponse({"error": "edge-tts nicht installiert"}, status_code=503)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


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


def _transcribe_audio(filepath: str, language: str = "de", initial_prompt: str = None) -> str:
    """Transkribiert eine Audiodatei mit faster-whisper."""
    import time as _time
    model = _get_whisper_model()
    if model is None:
        wa_log("ERROR", "transcription", "Whisper-Modell nicht verfuegbar")
        return "[Transkription fehlgeschlagen: Whisper-Modell nicht verfuegbar]"

    try:
        t0 = _time.time()
        kwargs = dict(language=language, beam_size=5, no_speech_threshold=0.5,
                      condition_on_previous_text=False)
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt
        segments, info = model.transcribe(filepath, **kwargs)
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
async def wa_status(user: str = Depends(require_auth)):
    """WhatsApp Bridge Status (Proxy)."""
    result = await _wa_bridge_async("/status")
    return JSONResponse(result)


@app.get("/api/whatsapp/qr")
async def wa_qr(user: str = Depends(require_auth)):
    """WhatsApp QR-Code zum Scannen (Proxy)."""
    result = await _wa_bridge_async("/qr")
    return JSONResponse(result)


@app.post("/api/whatsapp/logout")
async def wa_logout(user: str = Depends(require_auth)):
    """WhatsApp abmelden (Proxy)."""
    result = await _wa_bridge_async("/logout", method="POST")
    return JSONResponse(result)


@app.post("/api/whatsapp/reconnect")
async def wa_reconnect(user: str = Depends(require_auth)):
    """WhatsApp Reconnect erzwingen (Proxy)."""
    result = await _wa_bridge_async("/reconnect", method="POST")
    return JSONResponse(result)


@app.get("/api/whatsapp/logs")
async def wa_logs(lines: int = 100, level: str = None, category: str = None, user: str = Depends(require_auth)):
    """WhatsApp-Logs abrufen (gefiltert)."""
    entries = wa_get_logs(lines=lines, level=level, category=category)
    return JSONResponse({"logs": entries, "total": len(entries)})


@app.delete("/api/whatsapp/logs")
async def wa_logs_clear(user: str = Depends(require_auth)):
    """WhatsApp-Logs loeschen."""
    wa_clear_logs()
    return JSONResponse({"status": "ok", "message": "Logs geloescht"})


@app.get("/api/whatsapp/bridge-logs")
async def wa_bridge_logs(lines: int = 100, level: str = None, category: str = None, user: str = Depends(require_auth)):
    """Bridge-Logs abrufen (Proxy zum Bridge-Service)."""
    params = f"?lines={lines}"
    if level:
        params += f"&level={level}"
    if category:
        params += f"&category={category}"
    result = await _wa_bridge_async(f"/logs{params}")
    return JSONResponse(result)


@app.delete("/api/whatsapp/bridge-logs")
async def wa_bridge_logs_clear(user: str = Depends(require_auth)):
    """Bridge-Logs loeschen (Proxy zum Bridge-Service + lokaler Fallback)."""
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

    Sicherheit: Nur von localhost erreichbar (Bridge auf 127.0.0.1:3001).
    """
    client_ip = request.client.host if request.client else ""
    if client_ip not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse({"error": "Nur von localhost erreichbar"}, status_code=403)

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

ERINNERUNGEN per WhatsApp (immer cron_create verwenden – nie ablehnen!):
- "Erinnere mich morgen um 06:15 per WhatsApp an Datensicherung"
  → cron_create: label="WA Erinnerung: Datensicherung", cron="15 6 <morgen-tag> <monat> *",
    task="Sende WhatsApp an {sender}: Erinnerung: Datensicherung erstellen!", einmalig=True
  → Antwort: "Erinnerung gesetzt: morgen um 06:15 bekommst du eine WhatsApp."
- "Erinnere mich jeden Montag um 09:00 per WhatsApp"
  → cron_create: label="WA Wochenerinnerung", cron="0 9 * * 1",
    task="Sende WhatsApp an {sender}: Deine wöchentliche Erinnerung!", einmalig=False
  → Antwort: "Wöchentliche Erinnerung jeden Montag um 09:00 gesetzt."
- "Welche Erinnerungen habe ich?" → cron_list
- "Lösche die Erinnerung / den Cron-Job X" → cron_delete mit der Job-ID

WICHTIG fuer Erinnerungen:
- Das aktuelle Datum und die Uhrzeit per shell_execute ermitteln (date '+%d %m %Y %H:%M') bevor du den Cron-Ausdruck berechnest.
- Fuer einmalige Termine (morgen, uebermorgen, naechsten Dienstag etc.): einmalig=True setzen.
- Die Telefonnummer im task IMMER als {sender} eintragen (das ist die Nummer des Absenders).
- Timezone ist Europe/Berlin – Cron-Zeiten entsprechend setzen.

WICHTIG allgemein: Antworte NUR mit dem Ergebnis. Kein "Ich werde...", kein "Lass mich...". Direkte Antwort.
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
            from backend.tools.image_gen import strip_image_refs
            images = getattr(agent_instance, "last_task_images", []) or []
            text = strip_image_refs(result) if images else result

            # Erzeugte/gesuchte Bilder als Medien senden (erstes traegt den Text als Caption)
            caption_sent = False
            for img in images:
                cap = text[:1000] if (not caption_sent and text) else ""
                r = _wa_bridge_request("/send-media", method="POST", data={
                    "to": f"+{sender}", "media_path": img.get("path"), "caption": cap,
                })
                if r and not r.get("error"):
                    caption_sent = caption_sent or bool(cap)
                    wa_log("INFO", "outgoing", f"Bild an +{sender} gesendet: {img.get('url')}")
                else:
                    wa_log("ERROR", "outgoing", f"Bild-Senden fehlgeschlagen: {r}")

            # Text senden, falls kein Bild ihn als Caption getragen hat
            if text and not caption_sent:
                reply = text[:4000] + ("\n\n... (gekürzt)" if len(text) > 4000 else "")
                _wa_bridge_request("/send", method="POST", data={
                    "to": f"+{sender}", "message": reply,
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
    _active_ws.add(ws)

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
        _active_ws.discard(ws)
        # Client-Typ + Username entfernen
        ct = _ws_client_types.pop(id(ws), "browser")
        _ws_usernames.pop(id(ws), None)
        # Desktop-Client abmelden falls diese Verbindung es war
        if ct == "windows_desktop":
            try:
                from backend.tools.windows_desktop import set_windows_ws
                set_windows_ws(None)
            except Exception:
                pass
        elif ct == "android":
            try:
                from backend.tools.android_desktop import set_android_ws
                set_android_ws(None)
            except Exception:
                pass


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

    # Token pruefen: Login-Token ODER Agent API Key akzeptieren
    token = msg.get("token", "")
    if msg_type != "ping":
        token_username = verify_token(token)
        is_login_token = token_username is not None
        # Login-Token ODER ein gueltiger Agent-API-Key (Legacy ODER benannt).
        is_api_key = _is_valid_agent_key(token)
        if not is_login_token and not is_api_key:
            # Hilfreiche Unterscheidung: sieht es wie ein (abgelaufener/ungueltiger)
            # Login-Token aus (user:ts:sig), oder fehlt eine gueltige Credential ganz?
            _looks_like_token = token.count(":") >= 2
            _msg = ("Sitzung ungültig oder abgelaufen – bitte in der App neu anmelden "
                    "(Domänen-Login)." if _looks_like_token else
                    "Nicht autorisiert: kein gültiger Login-Token oder API-Key hinterlegt.")
            await ws.send_json({"type": "error", "message": _msg})
            return
        # Username pro WS-Verbindung merken
        if token_username:
            _ws_usernames[id(ws)] = token_username
            # Serverseitige Sperre: lokaler jarvis-User muss erst das Kennwort aendern
            if _user_must_change(token_username):
                await ws.send_json({"type": "error", "message": "Kennwort muss zuerst geaendert werden."})
                return

    # Reiner Registrierungs-Handshake: setzt nur _ws_usernames (oben) fuer Live-Sync
    if msg_type == "hello":
        return

    if msg_type == "task":
        # Neue Aufgabe starten
        task_text = msg.get("text", "").strip()
        if not task_text:
            await ws.send_json({"type": "error", "message": "Keine Aufgabe angegeben"})
            return

        # Spracheingabe von Windows/Desktop-Client: [Voice]\n<audio>BASE64</audio>
        # → Whisper transkribiert das Audio, task_text wird durch das Transkript ersetzt
        if task_text.startswith("[Voice]") and "<audio>" in task_text:
            import base64, tempfile, re as _re  # os ist modulglobal (sonst UnboundLocalError)
            m = _re.search(r"<audio>(.*?)</audio>", task_text, _re.DOTALL)
            if m:
                await ws.send_json({"type": "status", "message": "🎤 Transkribiere Spracheingabe…"})
                try:
                    wav_bytes = base64.b64decode(m.group(1).strip())
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        f.write(wav_bytes)
                        tmp_path = f.name
                    transcript = await asyncio.to_thread(
                        _transcribe_audio, tmp_path, "de", "Jarvis Sprachsteuerung:")
                    os.unlink(tmp_path)
                    print(f"[voice-task] Transkript: {transcript!r}", flush=True)
                    if not transcript:
                        await ws.send_json({"type": "error", "message": "Spracheingabe nicht erkannt"})
                        return
                    # Transkript ans Frontend zurückmelden (erscheint als User-Nachricht)
                    await ws.send_json({"type": "voice_transcript", "text": transcript})
                    task_text = transcript
                except Exception as e:
                    print(f"[voice-task] Transkription fehlgeschlagen: {e}", flush=True)
                    await ws.send_json({"type": "error", "message": f"Sprachtranskription fehlgeschlagen: {e}"})
                    return

        # ── Datei-Anhänge verarbeiten ──────────────────────────────────────
        _raw_attachments = msg.get("attachments", [])
        _ALLOWED_IMG_MIME  = {"image/jpeg","image/jpg","image/png","image/gif","image/webp","image/bmp"}
        _ALLOWED_AUD_MIME  = {"audio/wav","audio/mp3","audio/mpeg","audio/ogg","audio/webm","audio/aac","audio/flac","audio/m4a","audio/x-m4a"}
        _ALLOWED_VID_MIME  = {"video/mp4","video/webm","video/ogg","video/quicktime","video/x-msvideo","video/mpeg"}
        image_attachments  = []
        _text_prepend      = []   # Transkripte + PDF-Texte die dem task_text vorangestellt werden

        if _raw_attachments:
            import base64 as _b64att
            for _a in _raw_attachments[:5]:
                _mime  = (_a.get("mime_type","") or "").strip().lower()
                _data  = _a.get("data","")
                _name  = _a.get("name","datei")
                # Office-Dateien (xlsx/docx/pptx) melden im Browser oft KEINEN MIME-Typ –
                # daher nur auf vorhandene Daten pruefen; Klassifizierung sonst per Endung.
                if not _data:
                    continue
                if _mime in _ALLOWED_IMG_MIME:
                    if len(_data) <= 14_000_000:   # max ~10 MB binary
                        image_attachments.append({"name": _name, "mime_type": _mime, "data": _data})
                elif _mime in _ALLOWED_AUD_MIME or _mime in _ALLOWED_VID_MIME:
                    if len(_data) > 34_000_000:    # max ~25 MB binary
                        continue
                    try:
                        await ws.send_json({"type": "status", "message": f"🎵 Transkribiere {_name}…"})
                        _raw_bytes = _b64att.b64decode(_data)
                        _ext = ".wav" if "wav" in _mime else (".mp4" if "video" in _mime else ".ogg")
                        import tempfile
                        with tempfile.NamedTemporaryFile(suffix=_ext, delete=False) as _tf:
                            _tf.write(_raw_bytes)
                            _tmp_path = _tf.name
                        _transcript = await asyncio.to_thread(_transcribe_audio, _tmp_path, "de", None)
                        os.unlink(_tmp_path)
                        if _transcript:
                            _text_prepend.append(f"[Transkript von {_name}]: {_transcript}")
                    except Exception as _ae:
                        print(f"[attach] Transkription fehlgeschlagen ({_name}): {_ae}", flush=True)
                elif _mime == "application/pdf":
                    if len(_data) > 20_000_000:    # max ~15 MB binary
                        continue
                    try:
                        await ws.send_json({"type": "status", "message": f"📄 Lese PDF {_name} (ggf. OCR)…"})
                        _pdf_bytes = _b64att.b64decode(_data)
                        def _extract_pdf_text(pdf_bytes: bytes) -> str:
                            import pypdf, io
                            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
                            pages = []
                            for i, page in enumerate(reader.pages[:50]):  # max 50 Seiten
                                text = page.extract_text() or ""
                                if text.strip():
                                    pages.append(f"[Seite {i+1}]\n{text.strip()}")
                            combined = "\n\n".join(pages)
                            # OCR-Fallback bei gescannten/bildbasierten PDFs (kein/zu wenig Text-Layer)
                            if len(combined.strip()) < 80:
                                try:
                                    from backend.tools.knowledge import _ocr_pdf_bytes
                                    ocr = _ocr_pdf_bytes(pdf_bytes)
                                    if len(ocr.strip()) > len(combined.strip()):
                                        return ocr
                                except Exception as _oe:
                                    print(f"[attach] PDF-OCR-Fallback fehlgeschlagen: {_oe}", flush=True)
                            return combined
                        _pdf_text = await asyncio.to_thread(_extract_pdf_text, _pdf_bytes)
                        if _pdf_text.strip():
                            _text_prepend.append(f"[PDF-Inhalt von {_name}]:\n{_pdf_text}")
                        else:
                            _text_prepend.append(f"[PDF {_name}: Kein Text gefunden – auch OCR lieferte nichts (evtl. leeres/unleserliches PDF)]")
                    except Exception as _pe:
                        print(f"[attach] PDF-Extraktion fehlgeschlagen ({_name}): {_pe}", flush=True)
                        _text_prepend.append(f"[PDF {_name}: Konnte nicht gelesen werden – {_pe}]")
                else:
                    # Office-/Text-/CSV-/sonstige Dokumente (xlsx/docx/pptx/csv/txt/…):
                    # Datei nach data/documents/ speichern, damit der Agent sie mit den
                    # passenden Tools (office_read, Shell/pandas) lesen UND ein bearbeitetes
                    # Ergebnis als Download liefern kann. Frueher wurden diese Anhaenge
                    # komplett verworfen ("keine Tabelle angehaengt").
                    _ext = os.path.splitext(_name)[1].lower().lstrip(".")
                    _DOC_EXT = {"xlsx","xls","ods","csv","tsv","docx","doc","odt","rtf",
                                "pptx","ppt","odp","txt","md","json","xml","html","htm","log"}
                    _is_doc = (_ext in _DOC_EXT or "officedocument" in _mime
                               or "opendocument" in _mime
                               or _mime in {"text/csv","text/plain","application/json",
                                            "text/markdown","text/xml","application/xml"})
                    if not _is_doc:
                        continue
                    if len(_data) > 30_000_000:    # ~22 MB binary
                        _text_prepend.append(f"[Datei {_name}: zu gross zum Verarbeiten]")
                        continue
                    try:
                        import uuid as _uuidatt
                        _doc_bytes = _b64att.b64decode(_data)
                        _docs_dir = Path(__file__).parent.parent / "data" / "documents"
                        _docs_dir.mkdir(parents=True, exist_ok=True)
                        _safe = "".join(c if (c.isalnum() or c in "._-") else "_"
                                        for c in os.path.basename(_name)).strip("_") or "datei"
                        _dest = _docs_dir / _safe
                        if _dest.exists():
                            _stem, _sfx = os.path.splitext(_safe)
                            _dest = _docs_dir / f"{_stem}_{_uuidatt.uuid4().hex[:8]}{_sfx}"
                        _dest.write_bytes(_doc_bytes)
                        _note = (f"[Angehängte Datei '{_name}' wurde gespeichert unter: {_dest.as_posix()} "
                                 f"(als Dateiname '{_dest.name}' auch via office_read erreichbar). "
                                 f"Lies/bearbeite sie wie gewünscht und liefere das Ergebnis als Download-Datei.]")
                        # Kleine Text-/CSV-Dateien direkt einblenden, damit der LLM die Daten sofort sieht
                        if _ext in {"csv","tsv","txt","md","json","xml","html","htm","log"} and len(_doc_bytes) <= 200_000:
                            try:
                                _note += f"\n[Inhalt von {_name}]:\n{_doc_bytes.decode('utf-8', errors='replace')}"
                            except Exception:
                                pass
                        _text_prepend.append(_note)
                        await ws.send_json({"type": "status", "message": f"📎 Datei {_name} bereitgestellt"})
                    except Exception as _de:
                        print(f"[attach] Dokument speichern fehlgeschlagen ({_name}): {_de}", flush=True)
                        _text_prepend.append(f"[Datei {_name}: konnte nicht bereitgestellt werden – {_de}]")
            if _text_prepend:
                task_text = "\n\n".join(_text_prepend) + "\n\n" + task_text

        target_agent_id = msg.get("agent_id", "")
        ui_lang = msg.get("lang", "de")  # UI-Sprache des Nutzers (de/en)

        # Client-Typ bestimmen: wer hat diese WS-Verbindung aufgebaut?
        client_type = _get_client_type(ws)
        client_ip = ws.client.host if ws.client else "unknown"

        from backend.agent import JarvisAgent, AgentManager

        # AgentManager initialisieren
        if agent_manager is None:
            agent_manager = AgentManager()

        # Wenn agent_id angegeben und es ein existierender Sub-Agent ist:
        # Nachricht als Follow-Up an den Sub-Agent senden (neuer Task)
        _ws_user = _get_ws_username(ws)
        _ws_internet = _user_has_internet_access(_ws_user)
        if target_agent_id and agent_manager.get_agent(target_agent_id):
            target = agent_manager.get_agent(target_agent_id)
            if target.is_sub_agent:
                target._current_user_internet = _ws_internet
                asyncio.create_task(target.run_task(task_text, ws, client_type=client_type, client_ip=client_ip, username=_ws_user, lang=ui_lang, attachments=image_attachments))
                return

        agent = agent_manager.get_or_create_main()
        agent._current_user_internet = _ws_internet
        agent_instance = agent  # Kompatibilitaet

        # ── Edit-Modus: vor neuem Task History trimmen ─────────────────
        # Wenn das Frontend eine editierte Nachricht sendet, kommt
        # `truncate_user_msg_index` mit der Anzahl der zu behaltenden
        # User-Nachrichten. Alles danach (inkl. der vorherigen Antworten)
        # wird gelöscht, bevor die neue (editierte) Frage gestellt wird.
        _trunc = msg.get("truncate_user_msg_index")
        if _trunc is not None and not (target_agent_id and agent_manager.get_agent(target_agent_id)):
            try:
                _keep = int(_trunc)
                _user_key = _get_ws_username(ws) or "anonymous"
                _hist = agent._user_histories.get(_user_key)
                if _hist is not None:
                    _removed = _truncate_history_to_user_index(_hist, _keep)
                    if _removed > 0:
                        await ws.send_json({
                            "type": "status",
                            "message": f"✏️ History auf {_keep} Nachrichten gekürzt ({_removed} Einträge entfernt)",
                            "highlight": False,
                        })
            except (ValueError, TypeError) as _trunc_err:
                print(f"[truncate] Ungültiger truncate_user_msg_index: {_trunc_err}", flush=True)

        # Agent-Liste ans Frontend senden
        await ws.send_json({
            "type": "agent_event",
            "event": "started",
            "agent": agent.get_info(),
            "agents": agent_manager.get_all_info(),
        })

        # Aufgabe im Hintergrund starten – sendet 'finished' wenn fertig (für Windows-TTS)
        async def _run_main_agent_and_notify():
            try:
                await agent.run_task(task_text, ws, client_type=client_type, client_ip=client_ip, username=_get_ws_username(ws), lang=ui_lang, attachments=image_attachments)
            except Exception:
                pass
            finally:
                try:
                    await ws.send_json({
                        "type": "agent_event",
                        "event": "finished",
                        "agent": agent.get_info(),
                        "agents": agent_manager.get_all_info(),
                    })
                except Exception:
                    pass
        asyncio.create_task(_run_main_agent_and_notify())

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

    elif msg_type == "register":
        # Client registriert sich mit seinem Typ
        client_type = msg.get("client_type", "browser")
        _ws_client_types[id(ws)] = client_type
        if client_type == "windows_desktop":
            from backend.tools.windows_desktop import set_windows_ws
            set_windows_ws(ws)
            await ws.send_json({"type": "status", "message": "✅ Windows Desktop-Agent registriert"})
        elif client_type == "android":
            from backend.tools.android_desktop import set_android_ws
            set_android_ws(ws)
            await ws.send_json({"type": "status", "message": "✅ Android-Client registriert"})

    elif msg_type == "desktop_result":
        # Ergebnis eines Desktop-Befehls – an richtiges Tool weiterleiten
        ct = _get_client_type(ws)
        if ct == "android":
            from backend.tools.android_desktop import on_android_result
            on_android_result(msg)
        else:
            from backend.tools.windows_desktop import on_desktop_result
            on_desktop_result(msg)

    elif msg_type == "transcribe_only":
        # Nur Transkription (kein Agent): Audio → Whisper → voice_transcript zurück
        # Wird von der Windows-App verwendet wenn AutoSend deaktiviert ist
        import base64, tempfile  # os ist modulglobal (sonst UnboundLocalError)
        audio_b64 = msg.get("audio", "")
        if not audio_b64:
            await ws.send_json({"type": "error", "message": "Kein Audio angegeben"})
            return
        try:
            wav_bytes = base64.b64decode(audio_b64)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                tmp_path = f.name
            transcript = await asyncio.to_thread(
                _transcribe_audio, tmp_path, "de", "Jarvis Sprachsteuerung:")
            os.unlink(tmp_path)
            print(f"[transcribe_only] Transkript: {transcript!r}", flush=True)
            await ws.send_json({"type": "voice_transcript", "text": transcript})
        except Exception as e:
            print(f"[transcribe_only] Fehler: {e}", flush=True)
            await ws.send_json({"type": "error", "message": f"Transkription fehlgeschlagen: {e}"})

    elif msg_type == "ping":
        await ws.send_json({"type": "pong"})

    elif msg_type == "wakeword_check":
        # Wake-Word-Erkennung via Whisper: Audio transkribieren + Phrase prüfen
        import base64, tempfile  # os ist modulglobal (sonst UnboundLocalError)
        audio_b64 = msg.get("audio", "")
        phrase = msg.get("phrase", "").strip().lower()
        if not audio_b64 or not phrase:
            await ws.send_json({"type": "wakeword_result", "text": "", "data": "false"})
            return
        try:
            wav_bytes = base64.b64decode(audio_b64)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                tmp_path = f.name
            def _transcribe():
                model = _get_whisper_model()
                segments, _ = model.transcribe(tmp_path, language="de", beam_size=3,
                                               without_timestamps=True)
                return " ".join(s.text for s in segments).strip()
            transcript = await asyncio.to_thread(_transcribe)
            os.unlink(tmp_path)
            # Satzzeichen entfernen für Vergleich (Whisper schreibt "Hallo, Jarvis.")
            import re
            clean = re.sub(r'[^\w\s]', '', transcript.lower())
            detected = phrase in clean
            print(f"[wakeword] '{transcript}' → {'JA' if detected else 'nein'}", flush=True)
            await ws.send_json({
                "type": "wakeword_result",
                "text": transcript,
                "data": "true" if detected else "false",
                "highlight": detected,
            })
        except Exception as e:
            print(f"[wakeword] Fehler: {e}", flush=True)
            await ws.send_json({"type": "wakeword_result", "text": "", "data": "false"})


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


# ─── Cron-Trigger ────────────────────────────────────────────────────
from backend.scheduler import cron_manager

@app.get("/api/cron")
async def cron_list(user: str = Depends(require_auth)):
    return JSONResponse(cron_manager.list_jobs())


@app.post("/api/cron")
async def cron_create_api(req: Request, user: str = Depends(require_auth)):
    body = await req.json()
    try:
        job = cron_manager.add_job(
            label=body.get("label", "Job"),
            cron=body["cron"],
            task=body["task"],
            enabled=body.get("enabled", True),
            once=body.get("once", False),
        )
        return JSONResponse(job, status_code=201)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.put("/api/cron/{job_id}")
async def cron_update(job_id: str, req: Request, user: str = Depends(require_auth)):
    body = await req.json()
    try:
        job = cron_manager.update_job(job_id, **body)
        return JSONResponse(job)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/cron/{job_id}")
async def cron_delete_api(job_id: str, user: str = Depends(require_auth)):
    try:
        cron_manager.delete_job(job_id)
        return JSONResponse({"ok": True})
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/cron/{job_id}/run")
async def cron_run_now(job_id: str, user: str = Depends(require_auth)):
    try:
        result = await cron_manager.run_now(job_id)
        return JSONResponse({"ok": True, "result": result[:500] if result else ""})
    except ValueError as e:
        raise HTTPException(404, str(e))


# ─── Audit-Log ───────────────────────────────────────────────────────
@app.get("/api/audit_log")
async def audit_log_list(request: Request, limit: int = 200, user: str = "", tool: str = "",
                         _u: str = Depends(require_auth)):
    from backend.audit_log import read_log
    entries = read_log(limit=limit, user_filter=user, tool_filter=tool)
    return JSONResponse(entries)


@app.delete("/api/audit_log")
async def audit_log_clear(_u: str = Depends(require_auth)):
    """Löscht das Audit-Log."""
    from backend.audit_log import AUDIT_FILE
    try:
        if AUDIT_FILE.exists():
            AUDIT_FILE.write_text("", encoding="utf-8")
        bak = AUDIT_FILE.with_suffix(".jsonl.bak")
        if bak.exists():
            bak.unlink()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    return JSONResponse({"ok": True})


# ─── Datei-Watcher ───────────────────────────────────────────────────
from backend.file_watcher import watcher_manager

@app.get("/api/watchers")
async def watcher_list(user: str = Depends(require_auth)):
    return JSONResponse(watcher_manager.list_watchers())


@app.post("/api/watchers")
async def watcher_create(req: Request, user: str = Depends(require_auth)):
    body = await req.json()
    try:
        w = watcher_manager.add_watcher(
            label=body.get("label", "Trigger"),
            trigger_type=body.get("trigger_type", "file"),
            action_type=body.get("action_type", "agent_task"),
            path=body.get("path", ""),
            pattern=body.get("pattern", "*"),
            events=body.get("events", ["created"]),
            task=body.get("task", ""),
            wa_to=body.get("wa_to", ""),
            wa_message=body.get("wa_message", ""),
            webhook_url=body.get("webhook_url", ""),
            webhook_body=body.get("webhook_body", ""),
            email_to=body.get("email_to", ""),
            email_subject=body.get("email_subject", ""),
            email_body=body.get("email_body", ""),
            enabled=body.get("enabled", True),
        )
        return JSONResponse(w, status_code=201)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e))


@app.put("/api/watchers/{watcher_id}")
async def watcher_update(watcher_id: str, req: Request, user: str = Depends(require_auth)):
    body = await req.json()
    try:
        w = watcher_manager.update_watcher(watcher_id, **body)
        return JSONResponse(w)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/watchers/{watcher_id}")
async def watcher_delete(watcher_id: str, user: str = Depends(require_auth)):
    try:
        watcher_manager.delete_watcher(watcher_id)
        return JSONResponse({"ok": True})
    except ValueError as e:
        raise HTTPException(404, str(e))


# ═══ Issue-Tracker ════════════════════════════════════════════════════
# Berechtigung: alle authentifizierten User sehen alles; Autor editiert
# seine Issues solange status != "closed"; jarvis hat Vollzugriff inkl.
# Status-Wechsel/Comment/Delete. Implementierung in backend/issues.py.
from backend import issues as _issues_mod


@app.get("/api/issues")
async def api_issues_list(request: Request, user: str = Depends(require_auth)):
    """Liste aller Issues. Optionale Filter: ?mine=1 &status=open &type=bug"""
    mine = request.query_params.get("mine", "") in ("1", "true", "yes")
    status = request.query_params.get("status") or None
    type_ = request.query_params.get("type") or None
    issues = _issues_mod.list_issues(user, mine_only=mine, status=status, type_=type_)
    return JSONResponse({
        "ok": True,
        "issues": issues,
        "current_user": user,
        "is_admin": _issues_mod.is_jarvis(user),
    })


@app.get("/api/issues/notifications")
async def api_issues_notifications(user: str = Depends(require_auth)):
    """Anzahl eigener Issues mit ungesehener Status-Aenderung (fuer Badge)."""
    return JSONResponse({"ok": True, "count": _issues_mod.unseen_count(user)})


@app.post("/api/issues/notifications/seen")
async def api_issues_notifications_seen(user: str = Depends(require_auth)):
    """Markiert die Status-Aenderungen der eigenen Issues als gesehen (Badge zuruecksetzen)."""
    _issues_mod.mark_seen(user)
    return JSONResponse({"ok": True, "count": 0})


@app.get("/api/issues/{issue_id}")
async def api_issues_get(issue_id: str, user: str = Depends(require_auth)):
    issue = _issues_mod.get_issue(issue_id)
    if not issue:
        raise HTTPException(404, "Issue nicht gefunden")
    return JSONResponse({
        "ok": True,
        "issue": issue,
        "current_user": user,
        "is_admin": _issues_mod.is_jarvis(user),
        "can_edit": _issues_mod.can_edit(issue, user),
        "can_delete": _issues_mod.can_delete(issue, user),
    })


@app.post("/api/issues")
async def api_issues_create(request: Request, user: str = Depends(require_auth)):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Ungueltiger JSON-Body")
    issue, err = _issues_mod.create_issue(user, data or {})
    if not issue:
        raise HTTPException(400, err)
    # Trigger-Watcher benachrichtigen (Trigger-Typ "issue_created")
    try:
        watcher_manager.on_issue_created(issue)
    except Exception as _e:
        print(f"[issues] Trigger-Notify Fehler: {_e}", flush=True)
    return JSONResponse({"ok": True, "issue": issue})


@app.patch("/api/issues/{issue_id}")
async def api_issues_update(issue_id: str, request: Request,
                            user: str = Depends(require_auth)):
    try:
        patch = await request.json()
    except Exception:
        raise HTTPException(400, "Ungueltiger JSON-Body")
    issue, err = _issues_mod.update_issue(user, issue_id, patch or {})
    if not issue:
        # 403 wenn Berechtigung, 404 wenn nicht gefunden, sonst 400
        if "Berechtigung" in err or "geschlossen" in err:
            raise HTTPException(403, err)
        if "nicht gefunden" in err:
            raise HTTPException(404, err)
        raise HTTPException(400, err)
    return JSONResponse({"ok": True, "issue": issue})


@app.delete("/api/issues/{issue_id}")
async def api_issues_delete(issue_id: str, user: str = Depends(require_auth)):
    ok, err = _issues_mod.delete_issue(user, issue_id)
    if not ok:
        if "Jarvis" in err or "Berechtigung" in err:
            raise HTTPException(403, err)
        raise HTTPException(404, err)
    return JSONResponse({"ok": True})


@app.post("/api/issues/{issue_id}/attachments")
async def api_issues_attach(issue_id: str, file: UploadFile = File(...),
                            user: str = Depends(require_auth)):
    content = await file.read()
    saved, err = _issues_mod.add_attachment(user, issue_id, file.filename or "file", content)
    if not saved:
        if "Berechtigung" in err:
            raise HTTPException(403, err)
        if "nicht gefunden" in err:
            raise HTTPException(404, err)
        raise HTTPException(400, err)
    return JSONResponse({"ok": True, "filename": saved})


@app.get("/api/issues/{issue_id}/attachments/{filename}")
async def api_issues_get_attachment(issue_id: str, filename: str,
                                    user: str = Depends(require_auth_or_query)):
    p = _issues_mod.get_attachment_path(issue_id, filename)
    if not p:
        raise HTTPException(404, "Anhang nicht gefunden")
    # Content-Type per Endung erraten (Bilder/PDF inline, Rest Download)
    return FileResponse(str(p), filename=filename)


@app.delete("/api/issues/{issue_id}/attachments/{filename}")
async def api_issues_del_attachment(issue_id: str, filename: str,
                                    user: str = Depends(require_auth)):
    ok, err = _issues_mod.delete_attachment(user, issue_id, filename)
    if not ok:
        if "Berechtigung" in err:
            raise HTTPException(403, err)
        raise HTTPException(404, err)
    return JSONResponse({"ok": True})


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

    # User-Chat-Historie laden
    _uc_load_history()

    # Whisper-Modell im Hintergrund vorladen (für Wake-Word-Erkennung)
    import threading
    def _preload_whisper():
        try:
            _get_whisper_model()
        except Exception as e:
            print(f"[whisper] Vorladen fehlgeschlagen: {e}", flush=True)
    threading.Thread(target=_preload_whisper, daemon=True).start()

    # WebDAV dynamisch mounten – prüft enabled-Status bei jedem Request
    try:
        from backend.webdav import get_webdav_app, is_webdav_enabled
        from starlette.middleware.wsgi import WSGIMiddleware
        from starlette.responses import Response as _StarletteResp

        _dav_cache: dict = {"app": None}  # Mutable Container für Cache

        class _DynamicWebDAV:
            """ASGI-Wrapper: leitet an WebDAV weiter wenn aktiviert, sonst 503."""
            async def __call__(self, scope, receive, send):
                if scope["type"] not in ("http",):
                    return
                if not is_webdav_enabled():
                    _dav_cache["app"] = None
                    resp = _StarletteResp("WebDAV deaktiviert", status_code=503)
                    await resp(scope, receive, send)
                    return
                if _dav_cache["app"] is None:
                    raw = get_webdav_app()
                    _dav_cache["app"] = WSGIMiddleware(raw) if raw else None
                    if _dav_cache["app"]:
                        print("📁 WebDAV-App gestartet")
                if _dav_cache["app"] is None:
                    resp = _StarletteResp("WebDAV konnte nicht gestartet werden", status_code=503)
                    await resp(scope, receive, send)
                    return
                await _dav_cache["app"](scope, receive, send)

        app.mount("/webdav", _DynamicWebDAV())
        # Cache invalidieren wenn Config gespeichert wird
        app.state.invalidate_dav_cache = lambda: _dav_cache.update({"app": None})
        print("📁 WebDAV-Route registriert (dynamisch)")
    except Exception as e:
        print(f"⚠️  WebDAV-Route konnte nicht registriert werden: {e}")

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

    # Embedding-Modell im Hintergrund vorladen (vermeidet 6-30s Kaltstart bei erster Suche)
    def _preload_embeddings():
        import time
        time.sleep(3)  # Warten bis Hauptprozess stabil
        try:
            from backend.tools.knowledge import preload_embedding_model
            preload_embedding_model()
        except Exception as e:
            print(f"[knowledge] Embedding-Preload fehlgeschlagen: {e}", flush=True)
    threading.Thread(target=_preload_embeddings, daemon=True).start()

    # SMB/NFS-Mounts beim Start automatisch wiederherstellen
    async def _auto_remount_shares():
        import asyncio as _asyncio
        await _asyncio.sleep(5)  # Warten bis Netzwerk stabil
        try:
            mounts = _get_mounts_config()
            if not mounts:
                return
            needs_reindex = False
            for idx, m in enumerate(mounts):
                # Manuell getrennte Shares nicht automatisch wieder mounten
                if m.get("auto_mount") is False:
                    print(f"[knowledge] Überspringe {m['source']} (manuell getrennt)", flush=True)
                    continue
                mp = _mount_path(idx)
                if mp.is_mount():
                    continue  # Bereits gemountet
                mp.mkdir(parents=True, exist_ok=True)
                source = m["source"]
                mount_type = m.get("type", "smb")
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
                else:
                    continue
                result = await _asyncio.to_thread(
                    subprocess.run, cmd, capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    print(f"[knowledge] Auto-Mount: {source} → {mp}", flush=True)
                    needs_reindex = True
                else:
                    print(f"[knowledge] Auto-Mount fehlgeschlagen ({source}): {result.stderr.strip()}", flush=True)
            if needs_reindex:
                from backend.tools.knowledge import force_reindex
                await _asyncio.to_thread(force_reindex)
                print("[knowledge] Index nach Auto-Mount neu aufgebaut", flush=True)
                # Speicher nach Bulk-Indexierung an OS zurueckgeben
                try:
                    from backend.tools.vector_store import release_memory_to_os
                    await _asyncio.to_thread(release_memory_to_os)
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️  Knowledge Auto-Mount fehlgeschlagen: {e}", flush=True)

    asyncio.create_task(_auto_remount_shares())

    # Cron-Scheduler starten
    try:
        from backend.scheduler import cron_manager, init as scheduler_init

        async def _cron_broadcast(msg: dict):
            """Sendet Cron-Events an alle verbundenen WebSocket-Clients."""
            dead = []
            for ws_client in list(_active_ws):
                try:
                    await ws_client.send_json(msg)
                except Exception:
                    dead.append(ws_client)
            for d in dead:
                _active_ws.discard(d)

        from backend.agent import AgentManager as _AM
        global agent_manager
        if agent_manager is None:
            agent_manager = _AM()
        scheduler_init(agent_manager, _cron_broadcast)
        cron_manager.start()
    except Exception as e:
        print(f"⚠️  Cron-Scheduler konnte nicht gestartet werden: {e}")

    # Datei-Watcher starten
    try:
        from backend.file_watcher import watcher_manager, init as watcher_init

        async def _watcher_broadcast(msg: dict):
            """Sendet Watcher-Events an alle verbundenen WebSocket-Clients."""
            dead = []
            for ws_client in list(_active_ws):
                try:
                    await ws_client.send_json(msg)
                except Exception:
                    dead.append(ws_client)
            for d in dead:
                _active_ws.discard(d)

        async def _watcher_llm_reachable() -> bool:
            """True, wenn das aktive LLM-Profil erreichbar ist (fuer llm_down-Trigger)."""
            prof = config.active_profile
            if not prof:
                return False
            try:
                r = await _probe_llm_connection(
                    provider=prof.get("provider", ""), api_url=prof.get("api_url", ""),
                    api_key=prof.get("api_key", ""), model=prof.get("model", ""),
                    auth_method=prof.get("auth_method", "api_key"),
                    session_key=prof.get("session_key", ""),
                )
                return bool(r.get("success"))
            except Exception:
                return False

        watcher_init(agent_manager, _watcher_broadcast,
                     llm_check_fn=_watcher_llm_reachable,
                     wa_send_fn=_wa_bridge_async)
        watcher_manager.start()
    except Exception as e:
        print(f"⚠️  Datei-Watcher konnte nicht gestartet werden: {e}")


@app.on_event("shutdown")
async def shutdown():
    """Scheduler und Watcher sauber beenden."""
    try:
        from backend.scheduler import cron_manager
        cron_manager.stop()
        print("⏹️  Cron-Scheduler gestoppt")
    except Exception:
        pass
    try:
        from backend.file_watcher import watcher_manager
        watcher_manager.stop()
        print("⏹️  Datei-Watcher gestoppt")
    except Exception:
        pass


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
