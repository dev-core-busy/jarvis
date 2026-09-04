"""Operations-Registry des Root-Brokers: Validierung, Policy-Pruefung, Ausfuehrung.

Jede Operation ist benannt und validiert ihre Argumente HART (Whitelists,
Pfad-Prefixe) – der Broker fuehrt nie unvalidierte Eingaben aus. Ausnahme ist
die bewusst generische Operation 'shell_root': sie startet IMMER als
'pending'-Eintrag und laeuft erst nach expliziter Admin-Freigabe.

dispatch() wird sowohl vom Broker-Daemon (Socket) als auch vom root-Fallback
des Clients (Alt-Installationen, Backend laeuft noch als root) genutzt.
"""

import re
import shlex
import subprocess
import time

from backend.broker import policy

# ── Whitelists ───────────────────────────────────────────────────────────────
SYSTEMCTL_UNITS = {
    "jarvis.service", "whatsapp-bridge.service", "lightdm", "lightdm.service",
    "jarvis-egress.service", "jarvis-broker.service",
}
SYSTEMCTL_ACTIONS = {"start", "stop", "restart", "reload", "enable", "disable",
                     "is-active", "is-enabled", "daemon-reload"}
SANDBOX_USER_PREFIX = "jarvis_sandbox"      # harte Grenze: nur Sandbox-User
MOUNT_PREFIX = "/mnt/"                      # Mounts nur unterhalb /mnt/
# Automatische/interne Wartungs- und Status-Ops OHNE forensischen Wert: werden
# WEDER in der Freigabeliste registriert NOCH auditiert, sonst fluten sie beides
# mit inhaltslosen "executed (rc=0)"-Eintraegen (UI-Status-Polls, die im Takt
# feuernde Bildschirm-Entsperrung, VNC-Neustart). Aussagekraeftige Ops
# (shell_root, systemctl, chpasswd, mount_share, certbot, switch_session) werden
# weiterhin vollstaendig auditiert.
READONLY_OPS = {"sandbox_status", "egress_status", "apt_upgrades_status",
                "tika_status", "unlock_screen", "vnc_restart"}


def _norm_cmd(cmd: str) -> str:
    """Kommando fuer den Policy-Key normalisieren (Whitespace kollabieren)."""
    return re.sub(r"\s+", " ", (cmd or "").strip())[:200]


def _run(cmd, timeout=30, input_text=None, neutrale_sprache=False):
    """Befehl ausfuehren.

    ``neutrale_sprache=True`` erzwingt LC_ALL=C. Noetig ueberall dort, wo eine
    Fehlermeldung spaeter GEDEUTET wird: auf einem deutschen System liefert
    ``mount`` "Die Operation ist jetzt in Bearbeitung." statt "Operation now in
    progress" – live auf DEV gemessen (2026-09-04), und jedes Muster, das auf
    den englischen Wortlaut zielt, greift dort ins Leere.
    """
    import os as _os
    umgebung = None
    if neutrale_sprache:
        umgebung = dict(_os.environ)
        umgebung["LC_ALL"] = "C"
        umgebung.pop("LANG", None)
        umgebung.pop("LANGUAGE", None)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, input=input_text, env=umgebung)
        return {"ok": r.returncode == 0, "rc": r.returncode,
                "stdout": r.stdout or "", "stderr": r.stderr or ""}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "rc": -1, "stdout": "", "stderr": str(e)}


def _stream_shell(command: str, cwd: str | None, timeout: int, stream) -> dict:
    """Shell-Befehl mit zeilenweisem stdout-Streaming ausfuehren (wie shell.py)."""
    import os as _os
    env = _os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=cwd or None, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            # EIGENE Prozessgruppe, damit ein Timeout den GANZEN Baum trifft.
            # `proc.kill()` beendet nur die aeussere Shell; die Kette
            # runuser -> setpriv -> bwrap -> bash -> python lief danach weiter
            # (Waise, die weiter Rechenzeit und Speicher verbraucht und in ein
            # gerade abgeraeumtes Lauf-Verzeichnis schreibt). Mit der Isolation
            # faellt das mehr auf, der Fehler ist aber aelter.
            start_new_session=True,
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "rc": -1, "stdout": "", "stderr": str(e)}

    def _abwuergen():
        """Ganze Prozessgruppe beenden – erst freundlich, dann hart."""
        import signal as _sig
        for signum in (_sig.SIGTERM, _sig.SIGKILL):
            try:
                _os.killpg(_os.getpgid(proc.pid), signum)
            except (ProcessLookupError, PermissionError):
                break
            try:
                proc.wait(timeout=3)
                return
            except subprocess.TimeoutExpired:
                continue
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass

    lines = []
    grenze = max(5, timeout)
    deadline = time.monotonic() + grenze
    # WACHHUND, und er ist noetig: die Deadline unten wird nur geprueft, wenn eine
    # ZEILE ankommt. `for line in proc.stdout` blockiert bei einem stillen Befehl
    # (`sleep 300`) unbegrenzt – gemessen am 23.08.2026: der Op-Timeout von 3 s lief
    # ins Leere, erst der Client brach nach 33 s ab, und der Prozessbaum lebte
    # danach WEITER (Waise, die Rechenzeit verbraucht und in ein bereits
    # abgeraeumtes Lauf-Verzeichnis schreibt). Der Fehler ist aelter als die
    # Isolation; mit ihr faellt er auf.
    import threading as _th
    _wachhund = _th.Timer(grenze + 1, _abwuergen)
    _wachhund.daemon = True
    _wachhund.start()
    try:
        for line in proc.stdout:
            if time.monotonic() > deadline:
                _abwuergen()
                return {"ok": False, "rc": -1, "stdout": "\n".join(lines),
                        "stderr": f"Timeout nach {timeout}s. Befehl abgebrochen."}
            line = line.rstrip("\n")
            lines.append(line)
            if stream:
                try:
                    stream(line)
                except Exception:  # noqa: BLE001
                    pass
        proc.wait(timeout=10)
        stderr = (proc.stderr.read() or "") if proc.stderr else ""
    except subprocess.TimeoutExpired:
        _abwuergen()
        return {"ok": False, "rc": -1, "stdout": "\n".join(lines),
                "stderr": f"Timeout nach {timeout}s. Befehl abgebrochen."}
    finally:
        _wachhund.cancel()
    if proc.returncode is not None and proc.returncode < 0:
        # Vom Wachhund beendet: als Timeout melden, nicht als "Signal -9". Der
        # Agent soll wissen, dass er zu lange gebraucht hat.
        return {"ok": False, "rc": -1, "stdout": "\n".join(lines),
                "stderr": f"Timeout nach {timeout}s. Befehl abgebrochen."}
    return {"ok": proc.returncode == 0, "rc": proc.returncode,
            "stdout": "\n".join(lines), "stderr": stderr}


# ── Operationen ──────────────────────────────────────────────────────────────
# Jede Op: key(args) -> Policy-Key, desc(args) -> Beschreibung (Admin-UI),
#          run(args, stream) -> Ergebnis-Dict, default_allow, redact-Felder.

def _op_systemctl(args, stream):
    action = str(args.get("action", "")).strip()
    unit = str(args.get("unit", "")).strip()
    if action not in SYSTEMCTL_ACTIONS:
        return {"ok": False, "rc": -1, "stdout": "", "stderr": f"Aktion nicht erlaubt: {action}"}
    if action == "daemon-reload":
        return _run(["systemctl", "daemon-reload"], timeout=30)
    if unit not in SYSTEMCTL_UNITS:
        return {"ok": False, "rc": -1, "stdout": "", "stderr": f"Unit nicht in Whitelist: {unit}"}
    cmd = ["systemctl", action, unit]
    if action in ("enable", "disable"):
        cmd = ["systemctl", action, "--now", unit] if args.get("now") else cmd
    return _run(cmd, timeout=60)


def _op_unlock_screen(args, stream):
    from backend import desktop_control
    desktop_control.unlock_desktop_screen(str(args.get("target_user") or "jarvis"))
    return {"ok": True, "rc": 0, "stdout": "Bildschirm entsperrt", "stderr": ""}


# Wer darf ueberhaupt Ziel eines Desktop-Session-Wechsels sein?
#
# VORGABE DES NUTZERS (2026-08-18): am lokalen Desktop arbeiten AUSSCHLIESSLICH
# der lokale Benutzer `jarvis` und – ueber genau dessen Sitzung – die
# Administratoren. Sonst niemand.
#
# WARUM DAS HIER STEHT UND NICHT NUR BEIM AUFRUFER: bis heute prueste diese Op
# nur das ZEICHENMUSTER des Namens. Ein Domaenen-Benutzer, der sich als
# `sven.sander` (ohne `nexus\`) anmeldete, kam damit durch – und
# `switch_desktop_session` schrieb diesen Namen in den LightDM-Autologin,
# obwohl es das Konto lokal gar nicht gibt. Auf ECHT ist das 25-mal passiert:
# Autologin auf ein nicht existierendes Konto, x11vnc gekillt, LightDM neu
# gestartet (53 Eintraege im Broker-Journal), danach 40 s vergebliches Warten
# auf eine Session, die nie entsteht. Der laufende Desktop war jedes Mal weg.
#
# Ein Zeichenmuster ist keine Berechtigung. Geprueft wird deshalb beides:
# Whitelist UND Existenz des lokalen Kontos (fail-closed).
_DESKTOP_USERS = {"jarvis"}


def _op_switch_session(args, stream):
    from backend import desktop_control
    username = str(args.get("username", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{0,31}", username):
        return {"ok": False, "rc": -1, "stdout": "", "stderr": "Ungueltiger Benutzername"}
    if username not in _DESKTOP_USERS:
        return {"ok": False, "rc": -1, "stdout": "",
                "stderr": "Der lokale Desktop gehoert '%s'. Ein Session-Wechsel zu "
                          "'%s' ist nicht vorgesehen." % ("/".join(sorted(_DESKTOP_USERS)),
                                                          username)}
    try:
        import pwd
        pwd.getpwnam(username)
    except Exception:  # noqa: BLE001
        return {"ok": False, "rc": -1, "stdout": "",
                "stderr": "'%s' ist kein lokales Konto – der Autologin wuerde ins "
                          "Leere zeigen und den Desktop unbrauchbar machen." % username}
    desktop_control.switch_desktop_session(username)
    return {"ok": True, "rc": 0, "stdout": f"Session-Wechsel zu {username} ausgefuehrt", "stderr": ""}


def _op_vnc_restart(args, stream):
    from backend import desktop_control
    out = desktop_control.restart_vnc()
    return {"ok": True, "rc": 0, "stdout": out or "x11vnc neu gestartet", "stderr": ""}


def _op_chpasswd(args, stream):
    from backend import desktop_control
    username = str(args.get("username", "")).strip()
    password = str(args.get("password", ""))
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{0,31}", username):
        return {"ok": False, "rc": -1, "stdout": "", "stderr": "Ungueltiger Benutzername"}
    ok = desktop_control.change_linux_password(username, password)
    return {"ok": ok, "rc": 0 if ok else 1,
            "stdout": "Kennwort gesetzt" if ok else "", "stderr": "" if ok else "chpasswd fehlgeschlagen"}


def _op_sandbox_exec(args, stream):
    """Shell-Befehl als unprivilegierter Sandbox-User ausfuehren (runuser).
    Harte Grenze: nur User mit Prefix 'jarvis_sandbox' und uid != 0.

    PRIVATES /tmp (seit 2026-08-23): Uebergibt der Aufrufer eine Benutzer-
    Kennung, wird der Befehl zusaetzlich in einen Mount-Namespace gesetzt, in dem
    ``/tmp`` NUR das Arbeitsverzeichnis dieses Benutzers ist. Das Verzeichnis wird
    HIER angelegt und dem Sandbox-Benutzer uebertragen – das ist der Grund, warum
    es ueberhaupt ueber den Broker laeuft: chown braucht root, und beide Seiten
    brauchen Schreibrecht (der Lauf schreibt Ergebnisse, das Backend liefert sie
    aus).

    Das Argument ``arbeit`` ist ABSICHTLICH eine Kennung und kein Pfad (8 Hex);
    die Bindungen werden validiert. Der Broker ist die Sicherheitsgrenze – er
    darf einen Pfad aus dem Backend nicht ungeprueft in einen Mount verwandeln.
    """
    import pwd
    user = str(args.get("user", "")).strip()
    command = str(args.get("command", ""))
    timeout = int(args.get("timeout") or 120)
    if not user.startswith(SANDBOX_USER_PREFIX):
        return {"ok": False, "rc": -1, "stdout": "", "stderr": f"Kein Sandbox-User: {user}"}
    try:
        if pwd.getpwnam(user).pw_uid == 0:
            return {"ok": False, "rc": -1, "stdout": "", "stderr": "Sandbox-User darf nicht uid 0 haben"}
    except KeyError:
        return {"ok": False, "rc": -1, "stdout": "", "stderr": f"OS-Benutzer fehlt: {user}"}
    lauf_dir = None
    binds = []
    rw = []
    try:
        from backend import lauf_tmp as _lt
        lauf_dir = _lt.arbeit_bereitstellen(str(args.get("arbeit") or ""), user)
        if lauf_dir:
            binds = _lt.binds_pruefen(args.get("ro_binds"))
            rw = _lt.rw_binds_pruefen(args.get("rw_binds"))
            # Einhaengepunkte VORHER anlegen (root). Ueberlaesst man das bwrap,
            # gehoeren sie dem Sandbox-Benutzer samt eigener Gruppe und das
            # Backend kann darin nichts mehr aufraeumen.
            _lt.einhaengepunkte(lauf_dir, list(binds) + list(rw), user)
        wrapped = _lt.sandbox_befehl(user, command, lauf_dir, binds,
                                     rw_binds=rw)
    except Exception as e:  # noqa: BLE001
        # Fail-OPEN und laut: eine kaputte Isolation darf nicht jeden
        # Shell-Befehl jedes Netzwerk-Benutzers abschalten.
        print(f"[Broker] Lauf-Isolation nicht anwendbar ({e}) – gemeinsames /tmp",
              flush=True)
        lauf_dir = None
        wrapped = "runuser -u %s -- /bin/bash -c %s" % (shlex.quote(user), shlex.quote(command))
    res = _stream_shell(wrapped, str(lauf_dir) if lauf_dir else "/tmp", timeout, stream)
    # DIE ANTWORT SAGT, OB ISOLIERT WURDE – und das ist keine Statistik, sondern
    # eine Zusage, auf die das Backend seine Pfad-Uebersetzung stuetzt.
    # Der Broker ist ein EIGENER Prozess mit eigener Kopie dieses Moduls; laeuft
    # er noch mit einer Fassung von vor dem /tmp-Umbau, nimmt er `arbeit` klaglos
    # an und ignoriert es. Dann FEHLT dieses Feld – und genau das Fehlen ist die
    # Aussage "nein" (siehe lauf_tmp.melde_ausfuehrung). Vorfall 2026-08-24:
    # ohne diese Rueckmeldung suchte die Auslieferung Ergebnisdateien im
    # Lauf-Verzeichnis, waehrend die Shell ins gemeinsame /tmp schrieb.
    try:
        res["isolation"] = bool(lauf_dir)
    except Exception:  # noqa: BLE001
        pass
    return res


def _op_shell_root(args, stream):
    """Beliebiger Root-Shell-Befehl – laeuft NUR nach expliziter Admin-Freigabe
    (default_allow=False -> erster Aufruf erzeugt einen Pending-Eintrag)."""
    command = str(args.get("command", ""))
    timeout = int(args.get("timeout") or 120)
    cwd = str(args.get("cwd") or "") or None
    if not command.strip():
        return {"ok": False, "rc": -1, "stdout": "", "stderr": "Kein Befehl angegeben"}
    return _stream_shell(command, cwd, timeout, stream)


def _op_lauf_aufraeumen(args, stream):
    """Arbeitsverzeichnis eines Benutzers entfernen (oder alle abgelaufenen).

    Braucht root, weil der Agent darin eigene Unterverzeichnisse anlegt
    (``mkdir /tmp/zwischen``, matplotlib-Cache); die gehoeren dem
    Sandbox-Benutzer mit dessen eigener Gruppe, und das unprivilegierte Backend
    darf darin nichts loeschen. Ohne diesen Weg sammelten sich die Verzeichnisse
    still in /tmp – genau der Zustand, den die Isolation beseitigen soll.

    Die Kennung wird in ``lauf_tmp`` hart geprueft (8 Hex) und ausschliesslich
    unter ARBEIT_ROOT aufgeloest: ein Pfad aus einem Argument kann hier keine
    Loeschung an anderer Stelle ausloesen.
    """
    from backend import lauf_tmp as _lt
    weg = _lt.aufraeumen_root(str(args.get("arbeit") or ""),
                              int(args.get("alter_min") or 0))
    return {"ok": True, "rc": 0, "result": {"entfernt": weg}, "stdout": "", "stderr": ""}


def _op_sandbox_setup(args, stream):
    from backend import sandbox_guard
    return {"ok": True, "rc": 0, "result": sandbox_guard.setup(), "stdout": "", "stderr": ""}


def _op_sandbox_teardown(args, stream):
    from backend import sandbox_guard
    return {"ok": True, "rc": 0, "result": sandbox_guard.teardown(), "stdout": "", "stderr": ""}


def _op_sandbox_status(args, stream):
    from backend import sandbox_guard
    return {"ok": True, "rc": 0, "result": sandbox_guard.status(live=bool(args.get("live"))),
            "stdout": "", "stderr": ""}


def _op_egress_setup(args, stream):
    from backend import egress_guard
    return {"ok": True, "rc": 0, "result": egress_guard.setup(), "stdout": "", "stderr": ""}


def _op_egress_teardown(args, stream):
    from backend import egress_guard
    return {"ok": True, "rc": 0, "result": egress_guard.teardown(), "stdout": "", "stderr": ""}


def _op_egress_status(args, stream):
    from backend import egress_guard
    return {"ok": True, "rc": 0, "result": egress_guard.status(live=bool(args.get("live"))),
            "stdout": "", "stderr": ""}


def _op_apt_upgrades_setup(args, stream):
    from backend import apt_upgrades
    return {"ok": True, "rc": 0, "result": apt_upgrades.setup(), "stdout": "", "stderr": ""}


def _op_apt_upgrades_teardown(args, stream):
    from backend import apt_upgrades
    return {"ok": True, "rc": 0, "result": apt_upgrades.teardown(), "stdout": "", "stderr": ""}


def _op_apt_upgrades_status(args, stream):
    from backend import apt_upgrades
    return {"ok": True, "rc": 0,
            "result": apt_upgrades.status(live=bool(args.get("live"))),
            "stdout": "", "stderr": ""}


def _op_tika_setup(args, stream):
    """Java + tika-app.jar bereitstellen (OneNote-Import, ``*.one``).

    WARUM ALS BROKER-OP UND NICHT NUR IM BOOTSTRAP: Schritt 6e in
    ``start_jarvis_root.sh`` laeuft nur beim BROKER-START. Wer heute ein
    Notizbuch in einen Wissensordner legt, muesste bis zum naechsten Neustart
    warten – und bis dahin sagt ihm nur eine Meldung, dass ein Administrator
    ``sudo bash deploy/tika_setup.sh`` ausfuehren soll. Genau diese Handarbeit
    ist der Zustand, den die Automatik beseitigen soll: mit dieser Op kann das
    unprivilegierte Backend die Einrichtung JEDERZEIT selbst anstossen.

    DER PFAD KOMMT NICHT AUS DEN ARGUMENTEN. Er wird relativ zu diesem Modul
    aufgeloest; ein Argument waere hier gleichbedeutend mit "fuehre ein
    beliebiges Skript als root aus" – also shell_root ohne dessen
    Freigabepflicht. Die Op nimmt UEBERHAUPT keine Argumente entgegen.

    Auto-allow wie die uebrigen System-Ops: sie stellt einen dokumentierten
    Soll-Zustand her, ist idempotent und jederzeit widerrufbar (Sicherheit →
    Root-Freigaben).
    """
    from pathlib import Path as _P
    jdir = _P(__file__).resolve().parent.parent.parent
    script = jdir / "deploy" / "tika_setup.sh"
    if not script.is_file():
        return {"ok": False, "rc": -1, "stdout": "",
                "stderr": f"Setup-Skript fehlt: {script}"}
    # 900 s: apt-get install default-jre-headless (~199 MB) plus 65 MB
    # Download von Maven Central. Der Daemon deckelt ohnehin bei MAX_TIMEOUT.
    return _stream_shell(f"bash {shlex.quote(str(script))}", str(jdir), 900, stream)


def _op_tika_status(args, stream):
    """Ist der OneNote-Import einsatzbereit? (nur lesen, nichts aendern)

    Getrennt von ``tika_setup``, damit der Aufrufer VOR einer 900-Sekunden-Op
    billig nachsehen kann – und damit ein Status-Poll nicht als Root-Eingriff
    in der Freigabeliste und im Audit landet (siehe READONLY_OPS).
    """
    from backend.tools import onenote
    fehlt = onenote.fehlender_baustein()
    return {"ok": True, "rc": 0, "stdout": "", "stderr": "",
            "result": {"bereit": not fehlt,
                       "java": onenote.finde_java() or "",
                       "jar": str(onenote.finde_tika() or "")}}


def _op_mount_share(args, stream):
    """Netzwerk-Freigabe (SMB/NFS/WebDAV) read-only mounten – nur unter /mnt/."""
    from pathlib import Path
    mount_type = str(args.get("type", "smb"))
    source = str(args.get("source", "")).strip()
    mp = str(args.get("mountpoint", "")).strip()
    username = str(args.get("username", ""))
    password = str(args.get("password", ""))
    if not source or not mp.startswith(MOUNT_PREFIX) or ".." in mp:
        return {"ok": False, "rc": -1, "stdout": "", "stderr": "Ungueltige Quelle/Mountpoint (nur /mnt/... erlaubt)"}
    Path(mp).mkdir(parents=True, exist_ok=True)
    if mount_type == "smb":
        opts = "ro"
        if username:
            opts += f",username={username},password={password}"
        else:
            opts += ",guest"
        cmd = ["mount", "-t", "cifs", source, mp, "-o", opts]
    elif mount_type == "nfs":
        cmd = ["mount", "-t", "nfs", "-o", "ro", source, mp]
    elif mount_type == "webdav":
        # davfs2: Credentials in root-eigene Secrets-Datei schreiben
        secrets = Path("/etc/davfs2/secrets")
        secrets.parent.mkdir(parents=True, exist_ok=True)
        line = f"{mp} {username} {password}\n"
        if secrets.exists():
            content = secrets.read_text()
            if mp not in content:
                secrets.write_text(content + line)
        else:
            secrets.write_text(line)
        secrets.chmod(0o600)
        cmd = ["mount", "-t", "davfs", "-o", "ro", source, mp]
    else:
        return {"ok": False, "rc": -1, "stdout": "", "stderr": f"Unbekannter Typ: {mount_type}"}
    # Sprachneutral, weil main.py::_mount_fehler_deuten die Ausgabe deutet.
    return _run(cmd, timeout=20, neutrale_sprache=True)


def _op_umount_share(args, stream):
    mp = str(args.get("mountpoint", "")).strip()
    if not mp.startswith(MOUNT_PREFIX) or ".." in mp:
        return {"ok": False, "rc": -1, "stdout": "", "stderr": "Ungueltiger Mountpoint (nur /mnt/... erlaubt)"}
    return _run(["umount", mp], timeout=15, neutrale_sprache=True)


def _op_certbot_obtain(args, stream):
    """Let's-Encrypt-Zertifikat via certbot standalone holen, Zertifikate nach
    certs/ KOPIEREN (nicht symlinken) und dem Dienst-Benutzer geben – noetig,
    weil das unprivilegierte Backend /etc/letsencrypt nicht lesen darf.
    Renewal-Hook sorgt dafuer, dass Erneuerungen wieder kopiert werden."""
    import os
    import shutil
    from pathlib import Path

    domain = str(args.get("domain", "")).strip()
    email = str(args.get("email", "")).strip()
    service_user = str(args.get("service_user", "jarvis")).strip()
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}$', domain):
        return {"ok": False, "rc": -1, "stdout": "", "stderr": "Ungueltige Domain"}
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return {"ok": False, "rc": -1, "stdout": "", "stderr": "Ungueltige E-Mail"}

    def say(line):
        if stream:
            try:
                stream(line)
            except Exception:  # noqa: BLE001
                pass

    # 1. certbot sicherstellen
    certbot = None
    for cp in ["/usr/bin/certbot", "/usr/local/bin/certbot"]:
        if Path(cp).exists():
            certbot = cp
            break
    if not certbot:
        say("📦 certbot nicht gefunden – installiere...")
        r = _stream_shell("apt-get install -y certbot", None, 300, stream)
        if Path("/usr/bin/certbot").exists():
            certbot = "/usr/bin/certbot"
        else:
            return {"ok": False, "rc": r["rc"], "stdout": r["stdout"],
                    "stderr": "certbot konnte nicht installiert werden"}

    # 2. certbot standalone
    say(f"🌐 Führe certbot aus: {certbot} certonly --standalone -d {domain}")
    cmd = " ".join([certbot, "certonly", "--standalone", "--non-interactive",
                    "--agree-tos", "-m", shlex.quote(email), "-d", shlex.quote(domain)])
    r = _stream_shell(cmd, None, 300, stream)
    if r["rc"] != 0:
        return {"ok": False, "rc": r["rc"], "stdout": r["stdout"],
                "stderr": f"certbot fehlgeschlagen (Exit-Code {r['rc']})"}

    le_fullchain = Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem")
    le_privkey = Path(f"/etc/letsencrypt/live/{domain}/privkey.pem")
    if not le_fullchain.exists() or not le_privkey.exists():
        return {"ok": False, "rc": 1, "stdout": r["stdout"],
                "stderr": f"Zertifikatsdateien nicht gefunden unter /etc/letsencrypt/live/{domain}/"}

    # 3. In certs/ kopieren + Dienst-Benutzer als Eigentuemer
    import pwd
    try:
        pw = pwd.getpwnam(service_user)
        uid, gid = pw.pw_uid, pw.pw_gid
    except KeyError:
        uid = gid = 0
    copied = []
    for certs_dir in [Path("/opt/jarvis/certs")]:
        if not certs_dir.parent.exists():
            continue
        certs_dir.mkdir(parents=True, exist_ok=True)
        cert_dst, key_dst = certs_dir / "server.crt", certs_dir / "server.key"
        for f in (cert_dst, key_dst):
            if f.exists() and not f.is_symlink():
                try:
                    f.rename(f.with_suffix(".bak"))
                except Exception:  # noqa: BLE001
                    pass
            if f.is_symlink():
                f.unlink()
        shutil.copy2(str(le_fullchain), str(cert_dst))
        shutil.copy2(str(le_privkey), str(key_dst))
        os.chmod(key_dst, 0o600)
        os.chmod(cert_dst, 0o644)
        if uid:
            os.chown(cert_dst, uid, gid)
            os.chown(key_dst, uid, gid)
        copied.append(str(certs_dir))
        say(f"📋 Zertifikat kopiert nach {certs_dir}/ (Eigentuemer: {service_user})")

    # 4. Renewal-Hook: bei certbot-Erneuerung erneut kopieren + Dienst neu starten
    hook_dir = Path("/etc/letsencrypt/renewal-hooks/deploy")
    try:
        hook_dir.mkdir(parents=True, exist_ok=True)
        hook = hook_dir / "jarvis-copy-certs.sh"
        hook.write_text(
            "#!/bin/bash\n"
            "# Auto-generiert von Jarvis (backend/broker/ops.py): kopiert erneuerte\n"
            "# Let's-Encrypt-Zertifikate ins Jarvis-certs/-Verzeichnis.\n"
            f"for D in /opt/jarvis/certs; do\n"
            f"  [ -d \"$D\" ] || continue\n"
            f"  cp -L /etc/letsencrypt/live/{domain}/fullchain.pem \"$D/server.crt\"\n"
            f"  cp -L /etc/letsencrypt/live/{domain}/privkey.pem \"$D/server.key\"\n"
            f"  chmod 644 \"$D/server.crt\"; chmod 600 \"$D/server.key\"\n"
            f"  chown {service_user}:{service_user} \"$D/server.crt\" \"$D/server.key\" 2>/dev/null\n"
            "done\n"
            "systemctl restart jarvis.service\n")
        hook.chmod(0o755)
        say("🔁 Renewal-Hook installiert (automatische Erneuerung kopiert Zertifikate erneut)")
    except Exception as e:  # noqa: BLE001
        say(f"⚠️ Renewal-Hook konnte nicht installiert werden: {e}")

    return {"ok": True, "rc": 0, "stdout": "Zertifikat erhalten und installiert: " + ", ".join(copied),
            "stderr": ""}


def _op_broker_mode(script_name: str, unit: str, args):
    """Betriebsart-Wechsel (getrennt <-> Alt-Betrieb) ueber das jeweilige
    Deploy-Skript. Laeuft ALS TRANSIENTE systemd-Unit (systemd-run), weil das
    Skript jarvis.service/jarvis-broker.service neu startet – ein Kind-Prozess
    in deren cgroup wuerde beim Restart mitgekillt. Rueckgabe sofort
    ('gestartet'); Fortschritt via journalctl -u <unit> bzw. Status-Polling."""
    from pathlib import Path as _P
    jdir = _P(__file__).resolve().parent.parent.parent
    script = jdir / "deploy" / "security" / script_name
    if not script.exists():
        return {"ok": False, "rc": -1, "stdout": "",
                "stderr": f"Skript fehlt: {script}"}
    svc_user = str(args.get("service_user") or "jarvis").strip() or "jarvis"
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{0,31}", svc_user):
        return {"ok": False, "rc": -1, "stdout": "", "stderr": "Ungueltiger Dienst-Benutzer"}
    # Preflight SYNCHRON (Fehler sofort in der UI statt Polling-Timeout):
    # Der Dienst-Benutzer muss das Elternverzeichnis betreten koennen – bei
    # Installationen unter /root (0700) wuerde die Migration das Backend
    # unstartbar machen. Das Skript prueft dasselbe nochmal (Defense-in-Depth).
    if script_name == "setup_broker.sh":
        chk = _run(["runuser", "-u", svc_user, "--", "test", "-x", str(jdir.parent)],
                   timeout=10)
        if not chk.get("ok"):
            return {"ok": False, "rc": -1, "stdout": "", "stderr": (
                f"Preflight fehlgeschlagen: Benutzer '{svc_user}' kann "
                f"{jdir.parent} nicht betreten (z.B. Installation unter /root)"
                f"{(' – ' + chk['stderr'].strip()) if chk.get('stderr') else ''}. "
                "Getrennter Betrieb ist mit diesem Layout nicht moeglich – "
                "es wurde nichts veraendert. Jarvis zuerst nach /opt/jarvis umziehen.")}
    cmd = ["systemd-run", "--collect", f"--unit={unit}",
           "bash", str(script), str(jdir)]
    if script_name == "setup_broker.sh":
        cmd.append(svc_user)
    r = _run(cmd, timeout=20)
    if not r.get("ok"):
        return r
    return {"ok": True, "rc": 0, "stderr": "",
            "stdout": (f"Umstellung gestartet (transiente Unit '{unit}'). "
                       f"Die Dienste starten gleich neu – Fortschritt: "
                       f"journalctl -u {unit}")}


def _op_broker_setup(args, stream):
    return _op_broker_mode("setup_broker.sh", "jarvis-broker-migrate", args)


def _op_broker_teardown(args, stream):
    return _op_broker_mode("teardown_broker.sh", "jarvis-broker-restore", args)


# name -> (run, key_fn, desc_fn, default_allow, redact_fields)
_REGISTRY = {
    "broker_setup": (
        _op_broker_setup,
        lambda a: "broker_setup",
        lambda a: "Getrennten Betrieb einrichten/reparieren (unprivilegiertes Backend + Root-Broker)",
        True, (),
    ),
    "broker_teardown": (
        _op_broker_teardown,
        lambda a: "broker_teardown",
        lambda a: "Alt-Betrieb wiederherstellen (Backend als root, Broker-Dienst deaktivieren)",
        True, (),
    ),
    "systemctl": (
        _op_systemctl,
        lambda a: f"systemctl:{a.get('action')}:{a.get('unit') or '-'}",
        lambda a: f"Dienststeuerung: systemctl {a.get('action')} {a.get('unit') or ''}".strip(),
        True, (),
    ),
    "unlock_screen": (
        _op_unlock_screen,
        lambda a: "unlock_screen",
        lambda a: "Desktop-Bildschirmsperre aufheben (VNC-Zugriff)",
        True, (),
    ),
    "switch_session": (
        _op_switch_session,
        lambda a: "switch_session",
        lambda a: "Desktop-Session wechseln (LightDM-Autologin + Neustart)",
        True, (),
    ),
    "vnc_restart": (
        _op_vnc_restart,
        lambda a: "vnc_restart",
        lambda a: "x11vnc-Server neu starten (Display :0)",
        True, (),
    ),
    "chpasswd": (
        _op_chpasswd,
        lambda a: "chpasswd",
        lambda a: "Linux-Kennwort eines Benutzers setzen (Erst-Login/Passwortwechsel)",
        True, ("password",),
    ),
    "sandbox_exec": (
        _op_sandbox_exec,
        lambda a: f"sandbox_exec:{a.get('user')}",
        lambda a: f"Shell-Befehl als unprivilegierter Sandbox-User '{a.get('user')}' ausfuehren",
        True, (),
    ),
    "lauf_aufraeumen": (
        _op_lauf_aufraeumen,
        lambda a: "lauf_aufraeumen",
        lambda a: "Arbeitsverzeichnis eines Benutzers entfernen (privates /tmp)",
        True, (),
    ),
    "sandbox_setup": (
        _op_sandbox_setup, lambda a: "sandbox_setup",
        lambda a: "OS-Sandbox einrichten (User anlegen, Secret-Dateirechte)",
        True, (),
    ),
    "sandbox_teardown": (
        _op_sandbox_teardown, lambda a: "sandbox_teardown",
        lambda a: "OS-Sandbox deaktivieren",
        True, (),
    ),
    "sandbox_status": (
        _op_sandbox_status, lambda a: "sandbox_status",
        lambda a: "OS-Sandbox-Status abfragen (inkl. Isolationstest)",
        True, (),
    ),
    "egress_setup": (
        _op_egress_setup, lambda a: "egress_setup",
        lambda a: "Internet-Egress-Sperre einrichten (nftables + Autostart)",
        True, (),
    ),
    "egress_teardown": (
        _op_egress_teardown, lambda a: "egress_teardown",
        lambda a: "Internet-Egress-Sperre deaktivieren",
        True, (),
    ),
    "egress_status": (
        _op_egress_status, lambda a: "egress_status",
        lambda a: "Egress-Sperre-Status abfragen (inkl. Live-Test)",
        True, (),
    ),
    "apt_upgrades_setup": (
        _op_apt_upgrades_setup, lambda a: "apt_upgrades_setup",
        lambda a: "Automatische Sicherheitsupdates einschalten (unattended-upgrades, "
                  "nur Sicherheits-Quelle, kein Reboot, kein Aufraeumen)",
        True, (),
    ),
    "apt_upgrades_teardown": (
        _op_apt_upgrades_teardown, lambda a: "apt_upgrades_teardown",
        lambda a: "Automatische Sicherheitsupdates ausschalten (Index-Refresh bleibt)",
        True, (),
    ),
    "apt_upgrades_status": (
        _op_apt_upgrades_status, lambda a: "apt_upgrades_status",
        lambda a: "Status der automatischen Sicherheitsupdates abfragen (inkl. Trockenlauf)",
        True, (),
    ),
    "tika_setup": (
        _op_tika_setup, lambda a: "tika_setup",
        lambda a: "OneNote-Import einrichten (Java-Laufzeit + Apache Tika bereitstellen)",
        True, (),
    ),
    "tika_status": (
        _op_tika_status, lambda a: "tika_status",
        lambda a: "Status des OneNote-Imports abfragen (Java + tika-app.jar)",
        True, (),
    ),
    "mount_share": (
        _op_mount_share,
        lambda a: f"mount_share:{a.get('type')}:{a.get('source')}",
        lambda a: f"Netzwerk-Freigabe mounten ({a.get('type')}): {a.get('source')} → {a.get('mountpoint')}",
        True, ("password",),
    ),
    "umount_share": (
        _op_umount_share,
        lambda a: "umount_share",
        lambda a: f"Netzwerk-Freigabe aushaengen: {a.get('mountpoint')}",
        True, (),
    ),
    "certbot_obtain": (
        _op_certbot_obtain,
        lambda a: "certbot_obtain",
        lambda a: f"Let's-Encrypt-Zertifikat beantragen fuer {a.get('domain')}",
        True, (),
    ),
    "shell_root": (
        _op_shell_root,
        lambda a: "shell_root:" + _norm_cmd(str(a.get("command", ""))),
        lambda a: "Root-Shell-Befehl: " + _norm_cmd(str(a.get("command", ""))),
        False, (),   # ← IMMER erst Admin-Freigabe (pending)
    ),
}


def redact_args(op: str, args: dict) -> dict:
    """Sensible Felder (Passwoerter) fuer Audit/Anzeige maskieren."""
    entry = _REGISTRY.get(op)
    if not entry:
        return dict(args or {})
    out = dict(args or {})
    for f in entry[4]:
        if f in out and out[f]:
            out[f] = "***"
    return out


def _args_info(op: str, args: dict) -> str:
    """Kompakte Klartext-Darstellung der konkreten (maskierten) Argumente
    fuers Audit-Log ('welcher Befehl/welche Unit/welcher User genau?') –
    macht die 'Beispiele' in der Admin-UI aussagekraeftig. Interne Felder
    (_context) und Leerwerte werden ausgelassen."""
    red = redact_args(op, args)
    red.pop("_context", None)
    parts = []
    for k, v in red.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        s = _norm_cmd(str(v)) if isinstance(v, str) else str(v)
        if len(s) > 140:
            s = s[:139] + "…"
        parts.append(f"{k}={s}")
    return " ".join(parts)[:300]


def dispatch(op: str, args: dict, user: str = "", stream=None) -> dict:
    """Operation ausfuehren: Policy pruefen (Eintrag beim ersten Auftauchen
    anlegen), bei 'allow' ausfuehren, sonst pending/denied zurueckgeben."""
    args = args or {}
    entry = _REGISTRY.get(op)
    if not entry:
        return {"ok": False, "decision": "unknown-op",
                "error": f"Unbekannte Broker-Operation: {op}"}
    run, key_fn, desc_fn, default_allow, _redact = entry
    try:
        key = key_fn(args)
        desc = desc_fn(args)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "decision": "invalid", "error": f"Ungueltige Argumente: {e}"}

    # Reine Lese-/Statusabfragen (vom Frontend beim Tab-Oeffnen automatisch
    # ausgeloest) sind KEINE sicherheitsrelevanten Operationen: sie werden weder
    # in der Freigabeliste registriert noch auditiert (sonst fluten sie beides
    # mit inhaltslosen "executed (rc=0)"-Eintraegen).
    if op in READONLY_OPS:
        try:
            result = run(args, stream)
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "rc": -1, "stdout": "", "stderr": f"Broker-Op-Fehler: {e}"}
        result.setdefault("ok", False)
        result["decision"] = "allowed"
        result["key"] = key
        return result

    # Rein informativer Ausloeser-Kontext (z.B. Agent-Task-Auszug). Wird NUR
    # ins Audit geschrieben und fliesst nie in key/desc/Policy/Befehl ein.
    context = str(args.get("_context") or "")[:300]
    # Konkrete (maskierte) Argumente dieser Ausfuehrung fuers Audit-Log
    info = _args_info(op, args)

    decision = policy.check(key, op, desc, user, default_allow)
    if decision == policy.DENY:
        policy.audit(user, op, key, "denied", context=context, info=info)
        return {"ok": False, "decision": "denied", "key": key,
                "error": "Vom Administrator abgelehnt"}
    if decision == policy.PENDING:
        policy.audit(user, op, key, "pending", context=context, info=info)
        return {"ok": False, "decision": "pending", "key": key,
                "error": "Wartet auf Admin-Freigabe"}

    t0 = time.monotonic()
    try:
        result = run(args, stream)
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "rc": -1, "stdout": "", "stderr": f"Broker-Op-Fehler: {e}"}
    dur = int((time.monotonic() - t0) * 1000)
    # Detail: stderr hat Vorrang (Fehlerursache); bei Erfolg ein stdout-Auszug,
    # damit auch rc=0-Eintraege aussagen, WAS passiert ist.
    detail = (result.get("stderr") or result.get("stdout") or "")[:200]
    policy.audit(user, op, key, "executed", rc=result.get("rc"),
                 duration_ms=dur, detail=detail, context=context, info=info)
    result.setdefault("ok", False)
    result["decision"] = "allowed"
    result["key"] = key
    return result
