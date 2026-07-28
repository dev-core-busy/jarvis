"""Automatische Sicherheitsupdates (unattended-upgrades) ein-/ausschaltbar.

Hintergrund (2026-07-28): Auf dem Echt-System hatte ein lokaler Admin eine eigene
systemd-Einheit gebaut, die naechtlich `apt-get update` UND `apt-get autoremove -y`
ausfuehrte. Das Aufraeumen war das Problem – unbeaufsichtigtes Paket-Loeschen kann
Abhaengigkeiten des Agenten entfernen (cmake/boost fuer dlib, ffmpeg fuer Whisper,
X/VNC, LibreOffice-Teile), und der Dienst bricht Stunden spaeter ohne erkennbaren
Zusammenhang. Nach dem Rueckbau fiel auf: `unattended-upgrades` war gar nicht
installiert, die Maschine bekam also ueberhaupt keine automatischen
Sicherheitspatches. Dieses Modul macht daraus einen bewussten, umschaltbaren
Zustand statt einer Handarbeit, die niemand dokumentiert.

BEWUSSTE Begrenzungen der Einrichtung – das ist der Kern des Moduls:
  * **Nur die Sicherheits-Quelle** (`origin=Debian,label=Debian-Security`).
    Keine allgemeinen Versionssprunge unter dem laufenden Dienst.
  * **Kein automatischer Neustart** (`Automatic-Reboot "false"`). Ein
    Produktionsserver startet nicht von selbst um 6 Uhr neu.
  * **Kein Aufraeumen** (`Remove-Unused-Dependencies "false"`). Genau der Punkt,
    der oben zurueckgebaut wurde – er darf nicht durch die Hintertuer
    zurueckkommen.
  * Ausschalten laesst das Paket installiert und den Index-Refresh
    (`Update-Package-Lists "1"`) bestehen: nur das automatische Einspielen geht
    aus. Ein veralteter Index hat auf ECHT eine Skill-Installation gekippt
    (404 auf eine Paketversion, die es nicht mehr gab).

Laeuft als root – im getrennten Betrieb ueber den Root-Broker (benannte Ops
`apt_upgrades_setup|teardown|status`), sonst direkt. Alle Kommandos sind fest
verdrahtet, es gibt keinen dynamischen Input -> keine Shell-Injection.
"""
import re
import shutil
import subprocess
from pathlib import Path

PKG = "unattended-upgrades"
# Debians Standard-Schalterdatei (auch von dpkg-reconfigure benutzt).
PERIODIC_CONF = "/etc/apt/apt.conf.d/20auto-upgrades"
# Eigene Datei fuer die Begrenzungen. Getrennt von 20auto-upgrades, damit ein
# `dpkg-reconfigure unattended-upgrades` sie nicht ueberschreibt. Die 52 sorgt
# fuer eine hoehere Nummer als 50unattended-upgrades (spaeter gelesen = gewinnt).
LIMITS_CONF = "/etc/apt/apt.conf.d/52jarvis-unattended"
LOG = "/var/log/unattended-upgrades/unattended-upgrades.log"
TIMERS = ("apt-daily.timer", "apt-daily-upgrade.timer")

_LIMITS = """// Von Jarvis verwaltet (Einstellungen -> Sicherheit -> Automatische
// Sicherheitsupdates). Haendische Aenderungen werden beim naechsten
// Einschalten ueberschrieben.

// NUR die Sicherheits-Quelle einspielen – keine allgemeinen Versionssprunge
// unter dem laufenden Dienst.
Unattended-Upgrade::Origins-Pattern {
        "origin=Debian,codename=${distro_codename}-security,label=Debian-Security";
};

// Ein Produktionsserver startet nicht von selbst neu.
Unattended-Upgrade::Automatic-Reboot "false";

// KEIN automatisches Aufraeumen: wuerde Abhaengigkeiten des Agenten entfernen
// (cmake/boost fuer dlib, ffmpeg fuer Whisper, X/VNC, LibreOffice-Teile).
Unattended-Upgrade::Remove-Unused-Dependencies "false";
Unattended-Upgrade::Remove-New-Unused-Dependencies "false";

// Keine Mails (kein MTA auf der Maschine) – Nachweis steht im Log.
Unattended-Upgrade::Mail "";
"""

_PERIODIC_ON = """// Von Jarvis verwaltet (Einstellungen -> Sicherheit).
// Paketindex taeglich aktualisieren (Debians apt-daily.timer).
APT::Periodic::Update-Package-Lists "1";
// Sicherheitspatches automatisch einspielen.
APT::Periodic::Unattended-Upgrade "1";
"""

_PERIODIC_OFF = """// Von Jarvis verwaltet (Einstellungen -> Sicherheit).
// Index weiter aktualisieren – ein veralteter Index laesst
// Paketinstallationen mit 404 scheitern.
APT::Periodic::Update-Package-Lists "1";
// KEINE automatischen Upgrades.
APT::Periodic::Unattended-Upgrade "0";
"""


def _bin(name, *fallbacks):
    p = shutil.which(name)
    if p:
        return p
    for f in fallbacks:
        if Path(f).exists():
            return f
    return name


SYSTEMCTL = _bin("systemctl", "/usr/bin/systemctl", "/bin/systemctl")
APT_GET = _bin("apt-get", "/usr/bin/apt-get")
APT_CONFIG = _bin("apt-config", "/usr/bin/apt-config")
DPKG = _bin("dpkg", "/usr/bin/dpkg")
UU = _bin("unattended-upgrade", "/usr/bin/unattended-upgrade")


def _run(cmd, timeout=30, env=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, env=env)
    except Exception as e:  # noqa: BLE001
        class _R:
            returncode = 1
            stdout = ""
            stderr = str(e)
        return _R()


def _pkg_installed() -> bool:
    return _run([DPKG, "-s", PKG], timeout=15).returncode == 0


def _periodic() -> dict:
    """Gelesene APT::Periodic-Werte (aus ALLEN conf.d-Dateien, wie apt sie sieht)."""
    out = (_run([APT_CONFIG, "dump"], timeout=20).stdout or "")
    werte = {}
    for zeile in out.splitlines():
        m = re.match(r'APT::Periodic::(\S+)\s+"([^"]*)"', zeile.strip())
        if m:
            werte[m.group(1)] = m.group(2)
    return werte


def _timer_enabled(unit: str) -> bool:
    return (_run([SYSTEMCTL, "is-enabled", unit], timeout=15).stdout or "").strip() == "enabled"


def _last_run() -> str:
    """Letzte Zeile des unattended-upgrades-Logs (Nachweis, dass es laeuft)."""
    try:
        zeilen = [z for z in Path(LOG).read_text(errors="replace").splitlines() if z.strip()]
        return zeilen[-1][:300] if zeilen else ""
    except Exception:  # noqa: BLE001
        return ""


def _limits_ok() -> bool:
    """Sind unsere Begrenzungen gesetzt? (Datei vorhanden UND Aufraeumen aus)"""
    try:
        txt = Path(LIMITS_CONF).read_text()
    except Exception:  # noqa: BLE001
        return False
    return ('Remove-Unused-Dependencies "false"' in txt
            and 'Automatic-Reboot "false"' in txt
            and "Debian-Security" in txt)


def status(live: bool = False) -> dict:
    """Zustand der automatischen Sicherheitsupdates.

    ``live=True`` fuehrt zusaetzlich einen Trockenlauf aus (aendert nichts) und
    meldet, ob unattended-upgrades tatsaechlich arbeiten wuerde.
    """
    per = _periodic()
    st = {
        "package_installed": _pkg_installed(),
        "update_lists": per.get("Update-Package-Lists", ""),
        "unattended": per.get("Unattended-Upgrade", ""),
        "limits_ok": _limits_ok(),
        "timers": {u: _timer_enabled(u) for u in TIMERS},
        "last_run": _last_run(),
        "dry_run": None,
        "security_only": None,
    }
    st["enabled"] = bool(st["package_installed"] and st["unattended"] == "1")
    # "ok" = eingeschaltet UND mit unseren Begrenzungen UND per Timer erreichbar
    st["ok"] = bool(st["enabled"] and st["limits_ok"]
                    and all(st["timers"].get(u) for u in TIMERS))
    if live and st["package_installed"]:
        r = _run([UU, "--dry-run", "--verbose"], timeout=180)
        aus = ((r.stdout or "") + (r.stderr or ""))
        st["dry_run"] = (aus.strip()[-600:] or f"rc={r.returncode}")
        # Nachweis, dass nur die Sicherheits-Quelle erlaubt ist
        st["security_only"] = ("Debian-Security" in aus) or ("security" in aus.lower())
    return st


def setup() -> dict:
    """Schaltet automatische Sicherheitsupdates EIN (idempotent)."""
    steps = []

    def step(name, ok, detail=""):
        steps.append({"name": name, "ok": bool(ok), "detail": (detail or "")[:300]})

    # 1) Paket installieren (mit Index-Refresh – ohne den scheitert die
    #    Installation auf Maschinen, auf denen lange kein apt lief).
    if _pkg_installed():
        step(f"{PKG} vorhanden", True)
    else:
        import os
        env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
        _run([APT_GET, "update", "-qq"], timeout=300, env=env)
        r = _run([APT_GET, "install", "-y", "-qq", PKG], timeout=600, env=env)
        step(f"{PKG} installiert", r.returncode == 0,
             (r.stderr or r.stdout or "")[-300:])
        if not _pkg_installed():
            return {"ok": False, "error": f"{PKG} konnte nicht installiert werden",
                    "steps": steps, "status": status()}

    # 2) Begrenzungen schreiben (Sicherheits-Quelle, kein Reboot, kein Aufraeumen)
    try:
        Path(LIMITS_CONF).write_text(_LIMITS)
        Path(LIMITS_CONF).chmod(0o644)
        step("Begrenzungen gesetzt", True, LIMITS_CONF)
    except Exception as e:  # noqa: BLE001
        step("Begrenzungen gesetzt", False, str(e))

    # 3) Schalter einschalten
    try:
        Path(PERIODIC_CONF).write_text(_PERIODIC_ON)
        Path(PERIODIC_CONF).chmod(0o644)
        step("Automatik eingeschaltet", True, PERIODIC_CONF)
    except Exception as e:  # noqa: BLE001
        step("Automatik eingeschaltet", False, str(e))

    # 4) Timer aktivieren (ohne sie passiert trotz Schalter nichts)
    for unit in TIMERS:
        r = _run([SYSTEMCTL, "enable", "--now", unit], timeout=60)
        step(f"{unit} aktiv", _timer_enabled(unit), r.stderr)

    st = status(live=True)
    return {"ok": bool(st.get("ok")), "steps": steps, "status": st}


def teardown() -> dict:
    """Schaltet automatische Sicherheitsupdates AUS (idempotent).

    Das Paket bleibt installiert und der Index wird weiter aktualisiert – nur das
    automatische Einspielen entfaellt. Absicht: Wiedereinschalten per Klick, und
    ein frischer Index ist unabhaengig davon noetig (siehe Modul-Docstring).
    """
    steps = []

    def step(name, ok, detail=""):
        steps.append({"name": name, "ok": bool(ok), "detail": (detail or "")[:300]})

    try:
        Path(PERIODIC_CONF).write_text(_PERIODIC_OFF)
        Path(PERIODIC_CONF).chmod(0o644)
        step("Automatik ausgeschaltet", True, PERIODIC_CONF)
    except Exception as e:  # noqa: BLE001
        step("Automatik ausgeschaltet", False, str(e))

    # apt-daily-upgrade.timer stillegen – er ruft unattended-upgrade auf. Mit
    # Schalter 0 tut es nichts, aber abgeschaltet ist es eindeutig.
    r = _run([SYSTEMCTL, "disable", "--now", "apt-daily-upgrade.timer"], timeout=60)
    step("apt-daily-upgrade.timer deaktiviert", not _timer_enabled("apt-daily-upgrade.timer"),
         r.stderr)
    # apt-daily.timer (Index) bleibt bewusst AN.
    r = _run([SYSTEMCTL, "enable", "--now", "apt-daily.timer"], timeout=60)
    step("Index-Aktualisierung bleibt aktiv", _timer_enabled("apt-daily.timer"), r.stderr)

    st = status()
    return {"ok": not st.get("enabled"), "steps": steps, "status": st}
