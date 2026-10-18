"""Desktop-/Session-Steuerung (root-Operationen), aus main.py herausgeloest.

Wird vom Root-Broker (backend/broker/ops.py) ausgefuehrt – bewusst OHNE
FastAPI-/Backend-Importe, damit der Broker-Prozess leichtgewichtig bleibt.
Enthaelt: Bildschirm entsperren, Desktop-Session wechseln, x11vnc-Neustart.
"""

import os
import re
import subprocess
import time
from pathlib import Path

AUTOLOGIN_CONF = "/etc/lightdm/lightdm.conf.d/50-jarvis-autologin.conf"

# x11vnc belegt fuer das Bildschirmabbild 42 SysV-Shared-Memory-Segmente. Bei
# SIGTERM gibt es sie frei, bei SIGKILL bleiben sie liegen (gemessen DEV
# 2026-10-05: TERM +0, INT +0, KILL +42, systemctl stop +0). Bis dahin stand
# hier `pkill -9 x11vnc` – und restart_vnc() laeuft bei JEDER Anmeldung von
# jarvis/einem Admin. Folge: 4088 verwaiste Segmente auf DEV (Limit shmmni
# 4096, x11vnc startete nicht mehr: "shmget: No space left on device"), 3108 auf ECHT.
X11VNC_TERM_WARTEN_S = 5.0

# BSI H11-Rest (2026-10-12): x11vnc lief als root. Der Paketfilter laesst nur
# root und den Dienstbenutzer an 5900/6080 – ein Fehler in x11vnc (0.9.17, kaum
# noch gepflegt), ausgeloest ueber eine solche Verbindung, waere aber ein Weg
# vom Dienstbenutzer zu root (dieselbe Klasse wie K1). Seitdem laeuft x11vnc
# unter einem eigenen Systembenutzer ohne Anmeldung, ohne Gruppen, ohne
# Faehigkeiten, mit no_new_privs. Den X-Zugang bekommt er ueber eine KOPIE des
# Cookies (0600) in einem eigenen Laufzeitverzeichnis – nicht die Datei von
# lightdm und nicht die des Desktop-Benutzers. Der Dienstbenutzer kann die Kopie
# nicht lesen.
# Fail-closed: laesst sich der Benutzer nicht anlegen, startet x11vnc NICHT
# (kein stiller Rueckfall auf root).
# `-nopw` bleibt: das Kennwort muesste noVNC im Browser kennen, also jedem
# Administrator ausgehaendigt werden – schwaecher als die Pruefung, die heute
# davor steht (Paketfilter je uid, /ws/vnc nur fuer Administratoren).
VNC_BENUTZER = "jarvis-vnc"
VNC_LAUFZEIT = "/run/jarvis-vnc"
VNC_PORT = 5900
_SYSPFAD = "/usr/sbin:/usr/bin:/sbin:/bin"


def _bin(name: str) -> str:
    for d in _SYSPFAD.split(":"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return name


def vnc_benutzer_sicherstellen():
    """Systembenutzer fuer x11vnc anlegen, falls er fehlt. Gibt den pwd-Eintrag oder None."""
    import pwd
    try:
        return pwd.getpwnam(VNC_BENUTZER)
    except KeyError:
        pass
    subprocess.run([_bin("useradd"), "--system", "--no-create-home", "--home-dir", "/nonexistent",
                    "--shell", "/usr/sbin/nologin", "--user-group", VNC_BENUTZER],
                   capture_output=True, text=True, timeout=15)
    try:
        return pwd.getpwnam(VNC_BENUTZER)
    except KeyError:
        return None


def xauth_finden(display: str):
    """Cookie-Datei fuer das Display finden (wie `-auth guess`, aber als root und ohne Dienst).

    lightdm legt sie unter /var/run/lightdm/root/<display> ab; sonst fragt
    `x11vnc -findauth` (lauscht nicht, liest nur). None = Display ohne Cookie (Xvfb).
    """
    lightdm = "/var/run/lightdm/root/%s" % display
    if os.path.isfile(lightdm):
        return lightdm
    try:
        r = subprocess.run([_bin("x11vnc"), "-display", display, "-findauth"],
                           capture_output=True, text=True, timeout=10,
                           env={"PATH": _SYSPFAD, "LC_ALL": "C"})
    except Exception:  # noqa: BLE001
        return None
    for z in (r.stdout or "").splitlines():
        if z.startswith("XAUTHORITY="):
            pfad = z.split("=", 1)[1].strip()
            if pfad and os.path.isfile(pfad):
                return pfad
    return None


def _cookie_kopieren(quelle: str, display: str, pw) -> str:
    """Cookie nach VNC_LAUFZEIT kopieren – 0600, Eigentuemer der VNC-Benutzer."""
    os.makedirs(VNC_LAUFZEIT, mode=0o700, exist_ok=True)
    os.chown(VNC_LAUFZEIT, pw.pw_uid, pw.pw_gid)
    os.chmod(VNC_LAUFZEIT, 0o700)
    ziel = os.path.join(VNC_LAUFZEIT, "xauth-%s" % display.lstrip(":").replace("/", "_"))
    with open(quelle, "rb") as f:
        inhalt = f.read()
    # Neu anlegen statt ueberschreiben: eine liegengebliebene Datei mit fremdem
    # Eigentuemer oder lockeren Rechten wird so nie wiederverwendet.
    try:
        os.unlink(ziel)
    except FileNotFoundError:
        pass
    fd = os.open(ziel, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchown(fd, pw.pw_uid, pw.pw_gid)
        os.write(fd, inhalt)
    finally:
        os.close(fd)
    return ziel


def x11vnc_befehl(display: str, auth, pw) -> list:
    """Argumentliste: x11vnc unter VNC_BENUTZER, ohne Gruppen/Faehigkeiten, nur localhost."""
    # EIN Literal (nicht zusammengesetzt): die Waechter lesen die Liste am Syntaxbaum.
    return [_bin("setpriv"), "--reuid=%d" % pw.pw_uid, "--regid=%d" % pw.pw_gid,
            "--clear-groups", "--no-new-privs", "--inh-caps=-all", "--bounding-set=-all",
            _bin("x11vnc"), "-norc", "-localhost", "-display", display,
            *(["-auth", auth] if auth else []),
            "-shared", "-forever", "-nopw", "-bg", "-quiet", "-rfbport", str(VNC_PORT)]


def x11vnc_starten(display: str = ":0", auth=None) -> str:
    """x11vnc fuer das Display starten – NIE als root. Einzige Startstelle auf dem Server.

    `auth` = Cookie-Datei; ohne Angabe wird sie gesucht (xauth_finden). Laeuft
    schon ein x11vnc, wird er vorher beendet (der neue soll am aktuellen Cookie haengen).
    """
    pw = vnc_benutzer_sicherstellen()
    if pw is None:
        msg = "[VNC] FEHLER: Benutzer %s fehlt und liess sich nicht anlegen – x11vnc NICHT gestartet." % VNC_BENUTZER
        print(msg, flush=True)
        return msg
    if _x11vnc_laeuft():
        x11vnc_beenden()
    quelle = auth or xauth_finden(display)
    kopie = _cookie_kopieren(quelle, display, pw) if quelle else None
    r = subprocess.run(x11vnc_befehl(display, kopie, pw), capture_output=True, text=True,
                       timeout=20, cwd="/", env={"PATH": _SYSPFAD, "HOME": VNC_LAUFZEIT, "LC_ALL": "C"})
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    print("[VNC] x11vnc als %s auf %s gestartet (rc=%s)" % (VNC_BENUTZER, display, r.returncode), flush=True)
    return out


def x11vnc_als_root() -> bool:
    """Laeuft (noch) ein x11vnc mit Eigentuemer root? (Altbestand vor dem Umbau)"""
    return subprocess.run(["pgrep", "-u", "root", "-x", "x11vnc"], capture_output=True,
                          timeout=5).returncode == 0


def _x11vnc_laeuft() -> bool:
    return subprocess.run(["pgrep", "-x", "x11vnc"], capture_output=True,
                          timeout=5).returncode == 0


def shm_verwaiste_aufraeumen() -> int:
    """Verwaiste SysV-Segmente von root/VNC_BENUTZER entfernen: nicht angehaengt UND Erzeuger tot.

    Beide Bedingungen zusammen – ein Segment ohne Anhang, dessen Erzeuger noch
    lebt, kann gleich wieder angehaengt werden und bleibt stehen. Gibt die Zahl
    der entfernten Segmente zurueck; jeder Fehler zaehlt als "nichts entfernt".
    """
    try:
        status = subprocess.run(["ipcs", "-m"], capture_output=True, text=True,
                                timeout=10, env={**os.environ, "LC_ALL": "C"}).stdout
        erzeuger = subprocess.run(["ipcs", "-m", "-p"], capture_output=True, text=True,
                                  timeout=10, env={**os.environ, "LC_ALL": "C"}).stdout
    except Exception:  # noqa: BLE001
        return 0
    # ipcs -m:    key shmid owner perms bytes nattch status
    # ipcs -m -p: shmid owner cpid lpid
    leer = set()
    for z in status.splitlines():
        t = z.split()
        if len(t) >= 6 and t[1].isdigit() and t[2] in ("root", VNC_BENUTZER) and t[5] == "0":
            leer.add(t[1])
    weg = 0
    for z in erzeuger.splitlines():
        t = z.split()
        if len(t) < 3 or not t[0].isdigit() or t[0] not in leer or not t[2].isdigit():
            continue
        if os.path.exists("/proc/%s" % t[2]):
            continue
        if subprocess.run(["ipcrm", "-m", t[0]], capture_output=True, timeout=5).returncode == 0:
            weg += 1
    return weg


def x11vnc_beenden() -> None:
    """x11vnc beenden, ohne Shared Memory liegen zu lassen: TERM, warten, notfalls KILL + Aufraeumen."""
    subprocess.run(["pkill", "-TERM", "-x", "x11vnc"], capture_output=True, timeout=5)
    frist = time.monotonic() + X11VNC_TERM_WARTEN_S
    while time.monotonic() < frist and _x11vnc_laeuft():
        time.sleep(0.25)
    if _x11vnc_laeuft():
        subprocess.run(["pkill", "-KILL", "-x", "x11vnc"], capture_output=True, timeout=5)
        time.sleep(0.5)
        n = shm_verwaiste_aufraeumen()
        print(f"[VNC] x11vnc reagierte nicht auf TERM – hart beendet, {n} Segmente aufgeraeumt",
              flush=True)


def restart_vnc() -> str:
    """x11vnc fuer Display :0 robust neu starten."""
    x11vnc_beenden()
    out = x11vnc_starten(":0")
    print(f"[Session-Wechsel] x11vnc gestartet: {out}", flush=True)
    return out


_ENTSPERR_PAUSE_S = 10.0
_zuletzt_entsperrt = -1e9


def unlock_desktop_screen(target_user: str = "jarvis", erzwingen: bool = False) -> None:
    """Bildschirmschoner/Sperre fuer den Desktop-Benutzer deaktivieren.
    Wird beim VNC-Connect und bei Session-Wechsel aufgerufen.

    Strategie (von zuverlaessig nach aufwaendig):
    1. loginctl unlock-sessions  → systemd/PAM-Standard fuer alle Sessions
    2. pkill cinnamon-screensaver → prozessbasiert, funktioniert ohne D-Bus
    3. Aktiven Session-User auf Display :0 dynamisch ermitteln
    4. D-Bus screensaver-Befehl als dieser User
    5. DPMS aufwecken mit korrekter XAUTHORITY
    """
    # Der Name landet unten in der LightDM-Konfiguration (autologin-user=…) –
    # nur ein schlichter Kontoname, nie ein Zeilenumbruch (Code-Review 2026-10-18).
    if not isinstance(target_user, str) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", target_user):
        print(f"[VNC] unlock_desktop_screen: ungueltiges Ziel {target_user!r:.40} – abgewiesen", flush=True)
        return
    # Takt-Bremse (Code-Review 2026-10-18): ein Aufruf kostet 12-15
    # Unterprozesse und laeuft bei jedem VNC-Verbinden. Innerhalb von
    # _ENTSPERR_PAUSE_S nach dem letzten Lauf hat sich am Zustand nichts
    # Wesentliches geaendert – ueberspringen.
    global _zuletzt_entsperrt
    jetzt = time.monotonic()
    # Nach einem Sitzungswechsel (erzwingen=True) NIE ueberspringen: die neue
    # Sitzung braucht das Entsperren, auch wenn der letzte Lauf eben erst war.
    if not erzwingen and jetzt - _zuletzt_entsperrt < _ENTSPERR_PAUSE_S:
        return
    _zuletzt_entsperrt = jetzt
    _XAUTH = "/var/run/lightdm/root/:0"
    _xenv = {"DISPLAY": ":0", "XAUTHORITY": _XAUTH}

    try:
        # ── 1. systemd loginctl ────────────────────────────────────────────
        subprocess.run(["loginctl", "unlock-sessions"], capture_output=True, timeout=5)

        # ── 2. Screensaver-Prozess direkt beenden ─────────────────────────
        # Verankert (Code-Review 2026-10-18): ``pkill -f xscreensaver`` traf JEDEN
        # Prozess, dessen Kommandozeile das Wort enthaelt (auch ein Editor mit
        # der Datei). ``-x`` geht nicht – der Prozessname ist auf 15 Zeichen
        # gekuerzt ("cinnamon-screen").
        subprocess.run(["pkill", "-f", r"^(\S*/)?(python3?(\.\d+)?\s+)?(\S*/)?(cinnamon-|gnome-)?screensaver(\s|$)"],
                       capture_output=True, timeout=5)
        subprocess.run(["pkill", "-f", r"^(\S*/)?xscreensaver(\s|$)"], capture_output=True, timeout=5)

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
            x11vnc_beenden()
            x11vnc_starten(":0")
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
                    unlock_desktop_screen(username, erzwingen=True)
                    restart_vnc()
                    return

        # 2. LightDM-Autologin per Drop-In-Datei setzen
        os.makedirs(os.path.dirname(AUTOLOGIN_CONF), exist_ok=True)
        with open(AUTOLOGIN_CONF, "w") as f:
            f.write(f"[Seat:*]\nautologin-user={username}\nautologin-user-timeout=0\n")
        log(f"[Session-Wechsel] LightDM-Autologin auf '{username}' gesetzt.")

        # 3. x11vnc stoppen (TERM – SIGKILL liesse 42 SHM-Segmente liegen)
        x11vnc_beenden()

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
                        unlock_desktop_screen(username, erzwingen=True)
                        restart_vnc()
                        log(f"[Session-Wechsel] ✅ '{username}' ist jetzt am Desktop angemeldet.")
                        return

        # Rueckfall
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
    """Setzt das Linux-Kennwort via chpasswd (braucht root). True bei Erfolg.

    Zweite Schranke neben der Broker-Op (Code-Review 2026-10-18): chpasswd
    liest zeilenweise, ein Zeilenumbruch in Name oder Kennwort waere ein
    zweiter Auftrag – fuer ein beliebiges Konto."""
    if (not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{0,31}", username)
            or not isinstance(new_password, str) or not new_password or len(new_password) > 256
            or any(ord(c) < 32 or ord(c) == 127 for c in new_password)):
        print("[AUTH] chpasswd abgewiesen: ungueltiger Name oder Kennwort mit Steuerzeichen", flush=True)
        return False
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


if __name__ == "__main__":  # python3 -m backend.desktop_control shm-aufraeumen (Broker-Start)
    import sys
    if sys.argv[1:] == ["shm-aufraeumen"]:
        print("[VNC] %d verwaiste Shared-Memory-Segmente entfernt" % shm_verwaiste_aufraeumen())
    elif sys.argv[1:2] == ["vnc-starten"] and len(sys.argv) in (3, 4):
        # python3 -m backend.desktop_control vnc-starten <display> [<cookie-datei>]
        # (start_jarvis_root.sh – die Shell startet x11vnc nicht mehr selbst)
        print(x11vnc_starten(sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else None))
        sys.exit(0 if _x11vnc_laeuft() else 1)
    elif sys.argv[1:] == ["vnc-beenden"]:
        x11vnc_beenden()
