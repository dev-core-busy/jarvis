"""OS-Sandbox (Systemschutz fuer Netzwerk-/Domain-Benutzer) verwalten.

Analog zu egress_guard: Status, Ein-Klick-Einrichtung, Deaktivierung und
Live-Isolationstest fuer die Einstellung `sandbox_shell_user`. Ist sie gesetzt,
laufen Shell-Befehle nicht-privilegierter Benutzer via runuser als
unprivilegierter OS-Benutzer (Arbeitsverzeichnis /tmp). Die harte Grenze wirkt
nur, wenn die Secret-Dateien (settings.json, .env) per Dateirechten (600) fuer
diesen Benutzer unlesbar sind – das prueft/erzwingt setup().

Laeuft als root (jarvis.service). Fest verdrahtete Kommandos, kein
benutzergesteuerter Shell-Input -> keine Injection.
"""
import pwd
import shlex
import shutil
import subprocess
from pathlib import Path

SBX_USER = "jarvis_sandbox"


def _bin(name, *fallbacks):
    p = shutil.which(name)
    if p:
        return p
    for f in fallbacks:
        if Path(f).exists():
            return f
    return name


USERADD = _bin("useradd", "/usr/sbin/useradd", "/sbin/useradd")
RUNUSER = _bin("runuser", "/usr/sbin/runuser", "/sbin/runuser", "/usr/bin/runuser")


def _run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        class _R:
            returncode = 1
            stdout = ""
            stderr = str(e)
        return _R()


def _uid(name):
    try:
        return pwd.getpwnam(name).pw_uid
    except KeyError:
        return None


def _secret_files():
    files = []
    try:
        from backend.config import config
        files.append(Path(config.SETTINGS_FILE))
    except Exception:  # noqa: BLE001
        pass
    root = Path(__file__).resolve().parent.parent
    for name in (".env",):
        p = root / name
        if p.exists():
            files.append(p)
    return files


def _secrets_status():
    """(alle_gesperrt?, Detailliste). Gesperrt = keine Gruppen-/Andere-Rechte."""
    all_locked = True
    details = []
    for f in _secret_files():
        try:
            mode = f.stat().st_mode & 0o777
            locked = (mode & 0o077) == 0  # weder Gruppe noch Andere haben Rechte
            details.append({"file": str(f), "mode": oct(mode), "locked": locked})
            if not locked:
                all_locked = False
        except Exception:  # noqa: BLE001
            pass
    if not details:
        all_locked = False
    return all_locked, details


def _isolation():
    """Live-Test: darf der Sandbox-User Secrets lesen (soll NEIN) und /tmp
    schreiben (soll JA)? None wenn der User fehlt."""
    if _uid(SBX_USER) is None:
        return None
    from backend.config import config
    sf = str(config.SETTINGS_FILE)
    r1 = _run([RUNUSER, "-u", SBX_USER, "--", "/bin/bash", "-c",
               "cat " + shlex.quote(sf) + " >/dev/null 2>&1 && echo R || echo N"])
    r2 = _run([RUNUSER, "-u", SBX_USER, "--", "/bin/bash", "-c",
               "t=$(mktemp /tmp/_sbxchk.XXXXXX) && rm -f \"$t\" && echo W || echo N"])
    return {
        "secret_readable": (r1.stdout or "").strip() == "R",
        "tmp_writable": (r2.stdout or "").strip() == "W",
    }


def status(live=False):
    from backend.config import config
    setting = (config.get_setting("sandbox_shell_user", "") or "").strip()
    uid = _uid(SBX_USER)
    locked, details = _secrets_status()
    st = {
        "active": bool(setting),
        "setting_value": setting,
        "user": SBX_USER,
        "user_exists": uid is not None,
        "uid": uid,
        "secrets_locked": locked,
        "secret_files": details,
        "isolation": None,
    }
    if live:
        st["isolation"] = _isolation()
    st["ok"] = bool(st["active"] and st["user_exists"] and st["secrets_locked"])
    return st


def setup():
    """Idempotente Einrichtung: OS-Benutzer + Secret-Dateirechte + Einstellung."""
    steps = []

    def step(name, ok, detail=""):
        steps.append({"name": name, "ok": bool(ok), "detail": (detail or "")[:300]})

    # 1) OS-Benutzer
    if _uid(SBX_USER) is None:
        r = _run([USERADD, "-r", "-M", "-d", "/nonexistent",
                  "-s", "/usr/sbin/nologin", SBX_USER])
        step("OS-Benutzer angelegt", r.returncode == 0, r.stderr)
    else:
        step("OS-Benutzer vorhanden", True)
    if _uid(SBX_USER) is None:
        return {"ok": False, "error": "OS-Benutzer konnte nicht angelegt werden",
                "steps": steps, "status": status()}

    # 2) Secret-Dateien absichern (600 = nur root)
    for f in _secret_files():
        try:
            f.chmod(0o600)
            step("Rechte gesetzt: " + f.name, True, "600")
        except Exception as e:  # noqa: BLE001
            step("Rechte gesetzt: " + f.name, False, str(e))
    if not _secret_files():
        step("Secret-Dateien", True, "keine gefunden (nichts abzusichern)")

    # 3) Einstellung
    try:
        from backend.config import config
        config.save_setting("sandbox_shell_user", SBX_USER)
        step("Einstellung gesetzt", True, SBX_USER)
    except Exception as e:  # noqa: BLE001
        step("Einstellung gesetzt", False, str(e))

    st = status(live=True)
    iso = st.get("isolation") or {}
    ok = bool(st.get("ok") and iso.get("secret_readable") is False and iso.get("tmp_writable"))
    return {"ok": ok, "steps": steps, "status": st}


def teardown():
    """Deaktiviert die OS-Sandbox: leert `sandbox_shell_user`. Nicht-privilegierte
    Shell laeuft dann wieder als Dienst-Benutzer (nur Code-Haertung). Benutzer
    ohne Internet-Freigabe bleiben ueber die Egress-Sperre (eigener User)
    weiterhin gekapselt. Dateirechte + OS-Benutzer bleiben bestehen."""
    steps = []

    def step(name, ok, detail=""):
        steps.append({"name": name, "ok": bool(ok), "detail": (detail or "")[:300]})

    try:
        from backend.config import config
        config.save_setting("sandbox_shell_user", "")
        step("OS-Sandbox deaktiviert (Einstellung geleert)", True)
    except Exception as e:  # noqa: BLE001
        step("OS-Sandbox deaktiviert (Einstellung geleert)", False, str(e))

    st = status()
    return {"ok": (not st["active"]), "steps": steps, "status": st}
