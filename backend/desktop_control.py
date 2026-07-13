"""Desktop-/Session-Steuerung (root-Operationen), aus main.py herausgeloest.

Wird vom Root-Broker (backend/broker/ops.py) ausgefuehrt – bewusst OHNE
FastAPI-/Backend-Importe, damit der Broker-Prozess leichtgewichtig bleibt.
Enthaelt: Bildschirm entsperren, Desktop-Session wechseln, x11vnc-Neustart.
"""

import os
import subprocess
import time
from pathlib import Path

AUTOLOGIN_CONF = "/etc/lightdm/lightdm.conf.d/50-jarvis-autologin.conf"


def restart_vnc() -> str:
    """x11vnc fuer Display :0 robust neu starten."""
    subprocess.run(["pkill", "-9", "x11vnc"], capture_output=True, timeout=5)
    time.sleep(2)
    result = subprocess.run(
        ["x11vnc", "-display", ":0", "-auth", "guess",
         "-shared", "-forever", "-nopw", "-bg", "-rfbport", "5900"],
        capture_output=True, text=True, timeout=10
    )
    out = (result.stdout or "").strip()
    print(f"[Session-Wechsel] x11vnc gestartet: {out}", flush=True)
    return out


def unlock_desktop_screen(target_user: str = "jarvis") -> None:
    """Bildschirmschoner/Sperre fuer den Desktop-Benutzer deaktivieren.
    Wird beim VNC-Connect und bei Session-Wechsel aufgerufen.

    Strategie (von zuverlaessig nach aufwaendig):
    1. loginctl unlock-sessions  → systemd/PAM-Standard fuer alle Sessions
    2. pkill cinnamon-screensaver → prozessbasiert, funktioniert ohne D-Bus
    3. Aktiven Session-User auf Display :0 dynamisch ermitteln
    4. D-Bus screensaver-Befehl als dieser User
    5. DPMS aufwecken mit korrekter XAUTHORITY
    """
    _XAUTH = "/var/run/lightdm/root/:0"
    _xenv = {"DISPLAY": ":0", "XAUTHORITY": _XAUTH}

    try:
        # ── 1. systemd loginctl ────────────────────────────────────────────
        subprocess.run(["loginctl", "unlock-sessions"], capture_output=True, timeout=5)

        # ── 2. Screensaver-Prozess direkt beenden ─────────────────────────
        subprocess.run(["pkill", "-f", "cinnamon-screensaver"], capture_output=True, timeout=5)
        subprocess.run(["pkill", "-f", "xscreensaver"],         capture_output=True, timeout=5)
        subprocess.run(["pkill", "-f", "gnome-screensaver"],    capture_output=True, timeout=5)

        # ── 3. Aktiven Session-User auf :0 ermitteln ──────────────────────
        uid = None
        user = None
        try:
            who = subprocess.run(["who"], capture_output=True, text=True, timeout=5)
            for line in who.stdout.splitlines():
                if "(:0)" in line or "(:0." in line:
                    user = line.split()[0]
                    break
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
                        uid = parts[1]
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
                uid = str(_pwd.getpwnam(target_user).pw_uid)
                user = target_user
            except KeyError:
                uid = "1001"
                user = target_user

        # ── 4. D-Bus Screensaver-Kommando als Session-User ────────────────
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

        # ── 5. DPMS aufwecken UND Blanking dauerhaft deaktivieren ─────────
        subprocess.run(["xset", "-display", ":0", "dpms", "force", "on"], env=_xenv, capture_output=True, timeout=5)
        subprocess.run(["xset", "-display", ":0", "s", "reset"],          env=_xenv, capture_output=True, timeout=5)
        subprocess.run(["xset", "-display", ":0", "s", "off"],            env=_xenv, capture_output=True, timeout=5)
        subprocess.run(["xset", "-display", ":0", "s", "noblank"],        env=_xenv, capture_output=True, timeout=5)
        subprocess.run(["xset", "-display", ":0", "-dpms"],               env=_xenv, capture_output=True, timeout=5)

        # ── 6. Greeter-Fall: kein aktiver User auf :0 → jarvis einloggen ──
        who2 = subprocess.run(["who"], capture_output=True, text=True, timeout=5)
        display_users = [
            line.split()[0] for line in who2.stdout.splitlines()
            if "(:0)" in line or "(:0." in line
        ]
        # Wenn niemand oder nur lightdm auf :0 → Greeter zeigt → jarvis einloggen.
        # dm-tool ist hier NUTZLOS – stattdessen lightdm neu starten: der
        # Autologin (Conf unten) feuert dann sicher.
        if not display_users or all(u in ("lightdm", "root") for u in display_users):
            print("[VNC] Greeter aktiv – stelle Autologin sicher und starte lightdm neu.", flush=True)
            try:
                os.makedirs(os.path.dirname(AUTOLOGIN_CONF), exist_ok=True)
                with open(AUTOLOGIN_CONF, "w") as _f:
                    _f.write("[Seat:*]\nautologin-user=%s\nautologin-user-timeout=0\n" % target_user)
            except Exception as _e:
                print(f"[VNC] Autologin-Datei schreiben fehlgeschlagen: {_e}", flush=True)
            subprocess.run(["systemctl", "restart", "lightdm"], capture_output=True, timeout=20)
            # Auf die neue Session warten (Autologin braucht ein paar Sekunden) …
            for _i in range(15):
                time.sleep(2)
                _w = subprocess.run(["who"], capture_output=True, text=True, timeout=5)
                if any(l.split()[0] == target_user and ("(:0)" in l or "seat0" in l)
                       for l in _w.stdout.splitlines()):
                    break
            # … und x11vnc an den NEUEN X-Server binden (der alte haengt am toten X).
            subprocess.run(["pkill", "-x", "x11vnc"], capture_output=True, timeout=5)
            time.sleep(1)
            subprocess.run(["x11vnc", "-display", ":0", "-auth", "guess", "-shared",
                            "-forever", "-nopw", "-bg", "-quiet", "-rfbport", "5900"],
                           capture_output=True, timeout=15)
            print("[VNC] lightdm neu gestartet, Autologin ausgeloest, x11vnc neu gebunden.", flush=True)
        else:
            print(f"[VNC] Bildschirmsperre aufgehoben (user={user}, uid={uid})", flush=True)

    except Exception as e:
        print(f"[VNC] Screensaver-Unlock Fehler: {e}", flush=True)


def switch_desktop_session(username: str):
    """Wechselt die aktive Desktop-Session zum angegebenen Benutzer via LightDM-Autologin."""

    def log(msg: str):
        print(msg, flush=True)

    try:
        log(f"[Session-Wechsel] Starte Wechsel zu '{username}'...")

        # 1. Pruefen ob der Benutzer bereits eine aktive grafische Session hat
        result = subprocess.run(
            ["loginctl", "list-sessions", "--no-legend"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] == username:
                # Session-Details pruefen: Type=x11 UND Display gesetzt UND auf seat0
                info = subprocess.run(
                    ["loginctl", "show-session", parts[0],
                     "-p", "Type", "-p", "Display", "-p", "Seat"],
                    capture_output=True, text=True, timeout=5
                )
                props = dict(p.split("=", 1) for p in info.stdout.strip().splitlines() if "=" in p)
                if props.get("Type") in ("x11", "wayland") and props.get("Display") and props.get("Seat") == "seat0":
                    subprocess.run(["loginctl", "activate", parts[0]], timeout=5)
                    log(f"[Session-Wechsel] Bestehende Session {parts[0]} für '{username}' aktiviert.")
                    unlock_desktop_screen(username)
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
                        time.sleep(8)  # Display vollstaendig stabilisieren
                        unlock_desktop_screen(username)
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


def change_linux_password(username: str, new_password: str) -> bool:
    """Setzt das Linux-Kennwort via chpasswd (braucht root). True bei Erfolg."""
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
