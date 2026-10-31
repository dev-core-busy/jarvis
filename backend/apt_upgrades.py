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
import time
from pathlib import Path

PKG = "unattended-upgrades"
# Debians Standard-Schalterdatei (auch von dpkg-reconfigure benutzt).
PERIODIC_CONF = "/etc/apt/apt.conf.d/20auto-upgrades"
# Eigene Datei fuer die Begrenzungen. Getrennt von 20auto-upgrades, damit ein
# `dpkg-reconfigure unattended-upgrades` sie nicht ueberschreibt. Die 52 sorgt
# fuer eine hoehere Nummer als 50unattended-upgrades (spaeter gelesen = gewinnt).
LIMITS_CONF = "/etc/apt/apt.conf.d/52jarvis-unattended"
LOG = "/var/log/unattended-upgrades/unattended-upgrades.log"
# Verlauf der EINGESPIELTEN Pakete. Bewusst nicht LOG: das ist lokalisiert
# ("Pakete, welche aktualisiert werden: …") und vermischt echte Laeufe mit den
# Download-Laeufen von apt-daily und den Trockenlaeufen aus status(live=True)
# (auf DEV und ECHT am 2026-10-29 gesehen). history.log hat feste englische
# Schluessel und schreibt nur, was dpkg wirklich angefasst hat.
HISTORY = ("/var/log/apt/history.log", "/var/log/apt/history.log.1.gz")
TIMERS = ("apt-daily.timer", "apt-daily-upgrade.timer")
# Der Timer, der wirklich einspielt (apt-daily.timer frischt nur den Index auf).
UPGRADE_TIMER = "apt-daily-upgrade.timer"
UPGRADE_DIENST = "apt-daily-upgrade.service"
# Obergrenze fuer den Trockenlauf (siehe status(live=True)).
DRY_RUN_TIMEOUT = 45
# Obergrenze fuer den manuellen Lauf (jetzt_ausfuehren). Ein echter Lauf
# laedt und installiert; bei grossem Rueckstand dauert das Minuten.
JETZT_TIMEOUT = 1500

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


_PAKET = re.compile(r"([^\s,()]+) \(([^()]*)\)")


def _zeit(wert: str) -> float | None:
    """``2026-10-25  06:59:50`` (Ortszeit, doppelter Leerraum) -> Epoche."""
    try:
        return time.mktime(time.strptime(" ".join(wert.split()), "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def verlauf_parsen(text: str) -> list[dict]:
    """Bloecke aus apt/history.log, die ``unattended-upgrade`` geschrieben hat.

    Ein Lauf kann MEHRERE Bloecke schreiben (DEV 2026-10-28: thunderbird und
    openjdk im Abstand von einer Sekunde) – jeder Block bleibt ein Eintrag,
    zusammengefasst wird nicht: eine Grenze "gehoert zum selben Lauf" waere
    ein geratenes Zeitfenster.
    ``Upgrade:`` traegt ``(alt, neu)``, ``Install:`` ``(neu[, automatic])``.
    """
    erg = []
    for block in re.split(r"\n\s*\n", text or ""):
        felder = {}
        for zeile in block.splitlines():
            k, sep, v = zeile.partition(": ")
            if sep:
                felder[k.strip()] = v.strip()
        if "unattended-upgrade" not in felder.get("Commandline", ""):
            continue
        pakete = []
        for art in ("Upgrade", "Install"):
            for name, inhalt in _PAKET.findall(felder.get(art, "")):
                teile = [t.strip() for t in inhalt.split(",")]
                if art == "Upgrade":
                    von, nach = teile[0], (teile[1] if len(teile) > 1 else "")
                else:
                    von, nach = "", teile[0]
                pakete.append({"name": name.split(":")[0], "von": von, "nach": nach,
                               "neu": art == "Install"})
        erg.append({"start": _zeit(felder.get("Start-Date", "")),
                    "ende": _zeit(felder.get("End-Date", "")),
                    "pakete": pakete,
                    "fehler": felder.get("Error", "")[:300]})
    return erg


def eingespielt(max_n: int = 20) -> list[dict] | None:
    """Die letzten ``max_n`` Einspielungen, neueste zuerst.

    ``None`` heisst "nicht lesbar" – das ist etwas anderes als die leere Liste
    ("es wurde noch nichts eingespielt"). Gelesen wird auch die rotierte Datei:
    direkt nach dem Monatswechsel ist history.log sonst leer.
    """
    import gzip
    texte, gelesen = [], False
    for pfad in HISTORY:
        try:
            if pfad.endswith(".gz"):
                with gzip.open(pfad, "rt", errors="replace") as f:
                    texte.append(f.read())
            else:
                texte.append(Path(pfad).read_text(errors="replace"))
            gelesen = True
        except FileNotFoundError:
            continue
        except Exception:  # noqa: BLE001
            continue
    if not gelesen:
        return None
    alle = [e for t in texte for e in verlauf_parsen(t)]
    alle.sort(key=lambda e: e["start"] or 0, reverse=True)
    return alle[:max_n]


def zeitplan() -> dict:
    """Naechster und letzter Lauf des Einspiel-Timers samt Ergebnis des Dienstes.

    Zeiten als Epoche oder ``None`` (= unbekannt, NICHT "nie"). Die JSON-Ausgabe
    von ``list-timers`` liefert Mikrosekunden; die Textform von ``systemctl show``
    ist lokalisiert und wird deshalb nicht gelesen.
    """
    import json
    erg = {"naechster": None, "letzter": None, "ergebnis": "", "exit": None}
    r = _run([SYSTEMCTL, "list-timers", UPGRADE_TIMER, "--all", "--output=json"], timeout=15)
    try:
        for t in json.loads(r.stdout or "[]"):
            if t.get("unit") == UPGRADE_TIMER:
                for feld, ziel in (("next", "naechster"), ("last", "letzter")):
                    us = t.get(feld)
                    if isinstance(us, (int, float)) and us > 0:
                        erg[ziel] = us / 1e6
    except (ValueError, TypeError, AttributeError):
        pass
    r = _run([SYSTEMCTL, "show", UPGRADE_DIENST, "-p", "Result", "-p", "ExecMainStatus"],
             timeout=15)
    for zeile in (r.stdout or "").splitlines():
        k, _, v = zeile.partition("=")
        if k == "Result":
            erg["ergebnis"] = v.strip()
        elif k == "ExecMainStatus" and v.strip().lstrip("-").isdigit():
            erg["exit"] = int(v)
    return erg


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
        # Fuer den Eintrag in der Auftragsliste (cron.js): wann laeuft der
        # Timer, und was hat er zuletzt wirklich eingespielt.
        "zeitplan": zeitplan(),
        "eingespielt": eingespielt(),
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


def jetzt_ausfuehren() -> dict:
    """Spielt die Sicherheitsupdates SOFORT ein (manueller Lauf, Admin-Knopf).

    Ruft ``unattended-upgrade`` direkt auf – das Programm selbst prueft den
    Schalter ``APT::Periodic::Unattended-Upgrade`` NICHT (das tut nur
    ``apt.systemd.daily``), der Lauf geht also auch bei ausgeschalteter
    Automatik. Es liest aber dieselben Begrenzungen aus LIMITS_CONF: nur die
    Sicherheits-Quelle, kein Neustart, kein Aufraeumen.

    Fail-closed: ohne wirksame Begrenzungen (``_limits_ok()``) laeuft NICHTS –
    sonst gaelte die Debian-Vorgabe von unattended-upgrades, und die raeumt je
    nach Fassung Pakete auf. Vorher wird der Paketindex aufgefrischt, sonst
    sieht der Lauf die neuesten Sicherheitsmeldungen nicht.
    """
    import os
    steps = []

    def step(name, ok, detail=""):
        steps.append({"name": name, "ok": bool(ok), "detail": (detail or "")[:300]})

    if not _pkg_installed():
        step(f"{PKG} vorhanden", False, "zuerst „Einschalten / Reparieren“")
        return {"ok": False, "error": f"{PKG} ist nicht installiert", "steps": steps,
                "status": status()}
    if not _limits_ok():
        step("Begrenzungen wirksam", False, "zuerst „Einschalten / Reparieren“")
        return {"ok": False, "error": "Begrenzungen nicht wirksam – Lauf abgelehnt",
                "steps": steps, "status": status()}

    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    vorher = eingespielt() or []
    r = _run([APT_GET, "update", "-qq"], timeout=300, env=env)
    step("Paketindex aktualisiert", r.returncode == 0, (r.stderr or r.stdout or "")[-300:])

    r = _run([UU, "--verbose"], timeout=JETZT_TIMEOUT, env=env)
    aus = ((r.stdout or "") + (r.stderr or "")).strip()
    step("Sicherheitsupdates eingespielt", r.returncode == 0,
         aus[-300:] or f"rc={r.returncode}")

    nachher = eingespielt() or []
    # Neu ist, was vorher nicht im Verlauf stand (Vergleich ueber den ganzen Eintrag).
    neu = [e for e in nachher if e not in vorher]
    namen = [p.get("name", "") for e in neu for p in (e.get("pakete") or [])]
    if namen:
        rest = f" (+{len(namen) - 10} weitere)" if len(namen) > 10 else ""
        step(f"{len(namen)} Paket(e) aktualisiert: " + ", ".join(namen[:10]) + rest,
             r.returncode == 0)
    elif r.returncode == 0:
        step("Keine ausstehenden Sicherheitsupdates", True)
    return {"ok": r.returncode == 0, "steps": steps, "ausgabe": aus[-1500:],
            "neu": neu, "status": status()}


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
