"""OS-Sandbox (Systemschutz fuer Netzwerk-/Domain-Benutzer) verwalten.

Analog zu egress_guard: Status, Ein-Klick-Einrichtung und Live-Isolationstest
fuer die Einstellung `sandbox_shell_user`. Shell-Befehle nicht-privilegierter
Benutzer laufen via runuser als unprivilegierter OS-Benutzer.

SEIT BSI H10 (2026-10-05) IST DIE SANDBOX PFLICHT: eine leere Einstellung
faellt auf `jarvis_sandbox` zurueck, das fruehere "Deaktivieren" gibt es nicht
mehr, und ohne Sandbox bekommen Domain-Benutzer keine Shell (fail-closed,
`backend/sandbox_grenzen.py`). Die harte Grenze wirkt
nur, wenn die Secret-Dateien (settings.json, .env) per Dateirechten (600) fuer
diesen Benutzer unlesbar sind – das prueft/erzwingt setup().

Laeuft als root (jarvis.service). Fest verdrahtete Kommandos, kein
benutzergesteuerter Shell-Input -> keine Injection.
"""
import errno
import os
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
    # Projektbaum, nicht die Code-Kopie des Brokers (backend/broker/__init__.py)
    root = Path(os.environ.get("JARVIS_PROJECT_ROOT") or Path(__file__).resolve().parent.parent)
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
    schreiben (soll JA)? Dazu seit BSI H10: erreicht er den Loopback (soll
    NEIN) und laesst sich ein Lauf mit Ressourcengrenzen starten (soll JA)?
    None wenn der User fehlt."""
    if _uid(SBX_USER) is None:
        return None
    from backend.config import config
    from backend import sandbox_grenzen as _sg
    sf = str(config.SETTINGS_FILE)
    r1 = _run([RUNUSER, "-u", SBX_USER, "--", "/bin/bash", "-c",
               "cat " + shlex.quote(sf) + " >/dev/null 2>&1 && echo R || echo N"])
    r2 = _run([RUNUSER, "-u", SBX_USER, "--", "/bin/bash", "-c",
               "t=$(mktemp /tmp/_sbxchk.XXXXXX) && rm -f \"$t\" && echo W || echo N"])
    # Der Dienst selbst lauscht auf 443 – genau das Ziel, das aus der Sandbox
    # nicht erreichbar sein soll. Vorher die Sperre herstellen, sonst misst der
    # Test den Zustand vor dem ersten Lauf.
    _sg.lo_sperre_sicherstellen()
    r3 = _run([RUNUSER, "-u", SBX_USER, "--", "/bin/bash", "-c",
               "timeout 5 bash -c 'exec 3<>/dev/tcp/127.0.0.1/443' 2>/dev/null "
               "&& echo OFFEN || echo ZU"])
    r4 = _run(_sg.scope_praefix(_sg.STANDARD, 20)
              + [RUNUSER, "-u", SBX_USER, "--", "/bin/bash", "-c", "echo G"], timeout=40)
    return {
        "secret_readable": (r1.stdout or "").strip() == "R",
        "tmp_writable": (r2.stdout or "").strip() == "W",
        "loopback_offen": (r3.stdout or "").strip() == "OFFEN",
        "grenzen_anwendbar": (r4.stdout or "").strip() == "G",
    }


def _effektiv():
    """(wirksamer Sandbox-Benutzer, Grund) – wie der Dispatch ihn waehlt."""
    try:
        from backend import sandbox_grenzen as _sg
        return _sg.sandbox_benutzer(internet=True)
    except Exception as e:  # noqa: BLE001
        return "", str(e)


def status(live=False):
    """Zustand der Pflicht-Sandbox (BSI H10).

    ``active`` heisst seit H10: es GIBT einen wirksamen Sandbox-Benutzer – eine
    leere Einstellung schaltet nichts mehr ab, sie faellt auf ``jarvis_sandbox``
    zurueck. Ohne ihn bekommen Domain-Benutzer keine Shell.
    """
    from backend.config import config
    from backend import sandbox_grenzen as _sg
    setting = (config.get_setting("sandbox_shell_user", "") or "").strip()
    wirksam, grund = _effektiv()
    uid = _uid(SBX_USER)
    locked, details = _secrets_status()
    st = {
        "active": bool(wirksam),
        "pflicht": True,
        "setting_value": setting,
        "wirksam": wirksam,
        "grund": grund,
        "user": SBX_USER,
        "user_exists": uid is not None,
        "uid": uid,
        "secrets_locked": locked,
        "secret_files": details,
        "isolation": None,
        "h10": _sg.status(),
    }
    if live:
        st["isolation"] = _isolation()
    h = st["h10"]
    st["ok"] = bool(st["active"] and st["user_exists"] and st["secrets_locked"]
                    and h.get("systemd_run") and h.get("bwrap")
                    and h.get("isolation_gewuenscht") and h.get("lo_sperre") is not False)
    return st


def setup():
    """Idempotente Einrichtung: OS-Benutzer + Secret-Dateirechte + Einstellung
    + (BSI H10) bubblewrap und Loopback-Sperre."""
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
    # O_NOFOLLOW + fchmod (Code-Review 2026-10-18): der Projektbaum gehoert dem
    # Dienstbenutzer – ein Symlink .env -> /etc/<datei> liess root sonst den
    # Modus einer beliebigen Systemdatei auf 0600 setzen.
    for f in _secret_files():
        try:
            fd = os.open(f, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
            step("Rechte gesetzt: " + f.name, True, "600")
        except OSError as e:
            grund = "symbolischer Link – uebersprungen" if e.errno == errno.ELOOP else str(e)
            step("Rechte gesetzt: " + f.name, False, grund)
    if not _secret_files():
        step("Secret-Dateien", True, "keine gefunden (nichts abzusichern)")

    # 3) Einstellung
    try:
        from backend.config import config
        config.save_setting("sandbox_shell_user", SBX_USER)
        step("Einstellung gesetzt", True, SBX_USER)
    except Exception as e:  # noqa: BLE001
        step("Einstellung gesetzt", False, str(e))

    # 4) BSI H10: ohne bubblewrap gibt es fuer Domain-Benutzer keine Shell mehr
    # – also hier HERSTELLEN statt nur melden (Register: ein Hinweis ist keine
    # Automatik).
    from backend import lauf_tmp as _lt
    from backend import sandbox_grenzen as _sg
    if not Path(_lt.BWRAP).exists():
        r = _run(["apt-get", "install", "-y", "bubblewrap"], timeout=300)
        step("Isolation (bubblewrap) installiert", r.returncode == 0, r.stderr)
    else:
        step("Isolation (bubblewrap) vorhanden", True)
    step("Ressourcengrenzen (systemd-run) vorhanden", Path(_sg.SYSTEMD_RUN).exists(),
         _sg.SYSTEMD_RUN)
    ok_lo, grund_lo = _sg.lo_sperre_sicherstellen(erzwingen=True)
    step("Loopback-Sperre fuer Sandbox-Benutzer gesetzt", ok_lo, grund_lo)

    st = status(live=True)
    iso = st.get("isolation") or {}
    ok = bool(st.get("ok") and iso.get("secret_readable") is False and iso.get("tmp_writable")
              and iso.get("loopback_offen") is False and iso.get("grenzen_anwendbar"))
    return {"ok": ok, "steps": steps, "status": st}
