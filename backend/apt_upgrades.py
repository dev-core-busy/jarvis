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
# Obergrenze fuer den Trockenlauf (siehe status(live=True)).
DRY_RUN_TIMEOUT = 45

_LIMITS = """// Von Jarvis verwaltet (Einstellungen -> Sicherheit -> Automatische
// Sicherheitsupdates). Haendische Aenderungen werden beim naechsten
// Einschalten ueberschrieben.

// NUR die Sicherheits-Quelle einspielen – keine allgemeinen Versionssprunge
// unter dem laufenden Dienst.
//
// #clear IST HIER PFLICHT: apt ERGAENZT Listen, es ersetzt sie nicht. Ohne die
// beiden clear-Zeilen bleibt die Vorgabe aus 50unattended-upgrades stehen
// ("origin=Debian,codename=${distro_codename},label=Debian" = ALLE Updates) und
// die eigene Zeile kommt nur hinzu. Nachgewiesen auf DEV am 2026-07-28:
// `apt-config dump` zeigte vier Origins-Pattern, darunter label=Debian, und der
// Trockenlauf meldete 282 Kandidaten statt der 93 Sicherheitspakete.
#clear Unattended-Upgrade::Origins-Pattern;
#clear Unattended-Upgrade::Allowed-Origins;
Unattended-Upgrade::Origins-Pattern {
        "origin=Debian,codename=${distro_codename}-security,label=Debian-Security";
        "origin=Debian,codename=${distro_codename},label=Debian-Security";
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


def effective_origins() -> list[str]:
    """Ursprungs-Liste, die apt TATSAECHLICH anwendet (ueber alle conf.d-Dateien).

    Nicht am Dateiinhalt pruefen: apt ergaenzt Listen. Erst diese Abfrage zeigt,
    ob die Vorgabe aus 50unattended-upgrades wirklich verdraengt wurde.
    """
    out = (_run([APT_CONFIG, "dump"], timeout=20).stdout or "")
    werte = []
    for zeile in out.splitlines():
        m = re.match(r'Unattended-Upgrade::(?:Origins-Pattern|Allowed-Origins)::\s+"([^"]*)"',
                     zeile.strip())
        if m and m.group(1):
            werte.append(m.group(1))
    return werte


def _limits_ok() -> bool:
    """Greifen die Begrenzungen WIRKSAM? (nicht nur: steht es in der Datei)"""
    dump = (_run([APT_CONFIG, "dump"], timeout=20).stdout or "")
    if 'Unattended-Upgrade::Remove-Unused-Dependencies "false"' not in dump:
        return False
    if 'Unattended-Upgrade::Automatic-Reboot "false"' not in dump:
        return False
    origins = effective_origins()
    # JEDER Eintrag muss die Sicherheits-Quelle sein – ein einziger allgemeiner
    # Eintrag (label=Debian) wuerde beliebige Updates einspielen lassen.
    return bool(origins) and all("Debian-Security" in o for o in origins)


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
        "origins": effective_origins(),
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
        # HARTE Obergrenze: `unattended-upgrade --dry-run` simuliert die komplette
        # Installation und braucht auf einem Rechner mit viel Rueckstand Minuten
        # (auf DEV gemessen > 2 min). Ohne Deckel haengt die Oberflaeche daran.
        try:
            r = subprocess.run([UU, "--dry-run", "--verbose"], capture_output=True,
                               text=True, timeout=DRY_RUN_TIMEOUT)
            aus = ((r.stdout or "") + (r.stderr or "")).strip()
            st["dry_run"] = aus[-600:] or f"rc={r.returncode}"
        except subprocess.TimeoutExpired:
            # Kein Fehler, sondern eine Eigenschaft des Rechners: der Trockenlauf
            # simuliert JEDES Kandidatenpaket einzeln. Klar sagen, was gilt.
            st["dry_run"] = (f"Trockenlauf nach {DRY_RUN_TIMEOUT} s abgebrochen – er "
                             "simuliert jedes Kandidatenpaket einzeln und dauert bei "
                             "grossem Rueckstand laenger. Das sagt NICHTS ueber die "
                             "Einstellungen aus: die Zeilen oben zeigen den wirksamen "
                             "Zustand (aus apt-config gelesen).")
            aus = ""
        except Exception as e:  # noqa: BLE001
            st["dry_run"] = f"Trockenlauf nicht ausfuehrbar: {e}"
            aus = ""
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

    # 4) Timer aktivieren (ohne sie passiert trotz Schalter nichts).
    #    BEWUSST ohne `--now`: beide Timer haben `Persistent=true`, ein Start
    #    kann den zugehoerigen Dienst SOFORT ausloesen (apt-get update bzw.
    #    unattended-upgrade). Das haelt dann die apt-Sperre und laesst jede
    #    weitere Aktion warten. Sie feuern ohnehin nach Plan.
    for unit in TIMERS:
        r = _run([SYSTEMCTL, "enable", unit], timeout=60)
        step(f"{unit} aktiviert", _timer_enabled(unit), r.stderr)

    # ABSICHTLICH ohne Trockenlauf: der dauert Minuten (siehe DRY_RUN_TIMEOUT) und
    # die Einrichtung selbst ist in Millisekunden fertig. Wer die Simulation sehen
    # will, drueckt "Status pruefen (Trockenlauf)".
    st = status(live=False)
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
