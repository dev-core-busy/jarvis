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
READONLY_OPS = {"sandbox_status", "egress_status", "unlock_screen", "vnc_restart"}


def _norm_cmd(cmd: str) -> str:
    """Kommando fuer den Policy-Key normalisieren (Whitespace kollabieren)."""
    return re.sub(r"\s+", " ", (cmd or "").strip())[:200]


def _run(cmd, timeout=30, input_text=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, input=input_text)
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
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "rc": -1, "stdout": "", "stderr": str(e)}

    lines = []
    deadline = time.monotonic() + max(5, timeout)
    try:
        for line in proc.stdout:
            if time.monotonic() > deadline:
                proc.kill()
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
        proc.kill()
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


def _op_switch_session(args, stream):
    from backend import desktop_control
    username = str(args.get("username", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{0,31}", username):
        return {"ok": False, "rc": -1, "stdout": "", "stderr": "Ungueltiger Benutzername"}
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
    Harte Grenze: nur User mit Prefix 'jarvis_sandbox' und uid != 0."""
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
    wrapped = "runuser -u %s -- /bin/bash -c %s" % (shlex.quote(user), shlex.quote(command))
    return _stream_shell(wrapped, "/tmp", timeout, stream)


def _op_shell_root(args, stream):
    """Beliebiger Root-Shell-Befehl – laeuft NUR nach expliziter Admin-Freigabe
    (default_allow=False -> erster Aufruf erzeugt einen Pending-Eintrag)."""
    command = str(args.get("command", ""))
    timeout = int(args.get("timeout") or 120)
    cwd = str(args.get("cwd") or "") or None
    if not command.strip():
        return {"ok": False, "rc": -1, "stdout": "", "stderr": "Kein Befehl angegeben"}
    return _stream_shell(command, cwd, timeout, stream)


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
    return _run(cmd, timeout=20)


def _op_umount_share(args, stream):
    mp = str(args.get("mountpoint", "")).strip()
    if not mp.startswith(MOUNT_PREFIX) or ".." in mp:
        return {"ok": False, "rc": -1, "stdout": "", "stderr": "Ungueltiger Mountpoint (nur /mnt/... erlaubt)"}
    return _run(["umount", mp], timeout=15)


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
