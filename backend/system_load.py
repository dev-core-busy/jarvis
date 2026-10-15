"""Systemauslastung als Momentaufnahme – fuer das Popup hinter der CPU-Anzeige.

Liefert in EINEM Abruf, was ein Administrator beim Klick auf die CPU-Anzeige
wissen will: CPU (gesamt + je Kern), Speicher, Netzwerk, Festplatte und die
Prozesse, die gerade am meisten CPU ziehen.

⚠ WARUM EIN MESSFENSTER statt eines Einzelwerts: `Process.cpu_percent()` und
alle Raten (Netz-Bytes/s, Platten-Bytes/s) sind DIFFERENZEN zwischen zwei
Zeitpunkten. Ein Einzelaufruf liefert fuer jeden Prozess 0.0 – eine Liste, in
der alles 0 % hat, sieht wie Entwarnung aus und ist eine falsche Sonde. Deshalb
wird am Anfang und am Ende des Fensters gemessen und die Differenz ausgegeben.

⚠ `bericht()` BLOCKIERT fuer die Dauer des Fensters (`time.sleep`) – der
Endpunkt ruft es per `asyncio.to_thread` auf, nie direkt im Event-Loop.

Prozent je Prozess wie bei `top`: 100 % = ein voll ausgelasteter Kern. Ein
Prozess auf vier Kernen kann also 400 % zeigen. Zusaetzlich wird der Anteil an
der GANZEN Maschine mitgeliefert (`cpu_anteil`), damit die Zahl zur CPU-Anzeige
in der Titelleiste passt.

Es entsteht keine Datei und nichts wird zwischengespeichert: der Bericht ist
eine Aussage ueber den Moment der Frage.
"""

from __future__ import annotations

import os
import socket
import time
from datetime import datetime
from typing import Any, Dict, List

import psutil

# Messfenster in Sekunden. Kuerzer macht die Prozentwerte grob (Tick-Aufloesung
# des Kernels ist 10 ms), laenger laesst den Klick traege wirken.
FENSTER_S = 0.5

# Anzahl der gemeldeten Prozesse (Vorgabe: die 20 staerksten).
ANZAHL = 20

# Kommandozeile gekuerzt: ein Java-Aufruf mit Classpath fuellt sonst den Schirm.
CMD_MAX = 300

# Pseudo-Dateisysteme gehoeren nicht in die Plattenliste.
_FS_AUS = {"tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs",
           "cgroup", "cgroup2", "devpts", "mqueue", "debugfs", "tracefs",
           "securityfs", "pstore", "bpf", "autofs", "configfs", "fusectl",
           "hugetlbfs", "ramfs", "efivarfs", "binfmt_misc", "nsfs"}


def _prozesse_vorher() -> Dict[int, psutil.Process]:
    """Startpunkt je Prozess setzen (erster `cpu_percent`-Aufruf gibt 0.0)."""
    procs: Dict[int, psutil.Process] = {}
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)
            procs[p.pid] = p
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return procs


def _prozess_zeile(p: psutil.Process, kerne: int) -> Dict[str, Any] | None:
    try:
        with p.oneshot():
            cpu = p.cpu_percent(None)
            try:
                user = p.username()
            except (psutil.AccessDenied, KeyError):
                user = ""
            try:
                cmd = " ".join(p.cmdline())
            except (psutil.AccessDenied, psutil.ZombieProcess):
                cmd = ""
            try:
                mem = p.memory_info().rss
            except psutil.AccessDenied:
                mem = 0
            try:
                threads = p.num_threads()
            except psutil.AccessDenied:
                threads = 0
            return {
                "pid": p.pid,
                "name": p.name(),
                "user": user,
                "cpu": round(cpu, 1),
                "cpu_anteil": round(cpu / max(1, kerne), 1),
                "rss": mem,
                "mem_prozent": round(p.memory_percent(), 1) if mem else 0.0,
                "threads": threads,
                "status": p.status(),
                "cmd": cmd[:CMD_MAX],
            }
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        # Waehrend des Fensters beendet – gehoert nicht in die Liste.
        return None
    except psutil.AccessDenied:
        return None


def _platten() -> List[Dict[str, Any]]:
    aus: List[Dict[str, Any]] = []
    gesehen = set()
    for part in psutil.disk_partitions(all=False):
        if part.fstype in _FS_AUS or part.mountpoint in gesehen:
            continue
        # Netzlaufwerke (cifs/nfs) auslassen: ein totes Ziel blockiert
        # `statvfs` beliebig lange – dieselbe Klasse wie `Path.is_mount()`.
        if part.fstype in ("cifs", "smb3", "nfs", "nfs4", "fuse.sshfs"):
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        gesehen.add(part.mountpoint)
        aus.append({"mount": part.mountpoint, "fstype": part.fstype,
                    "gesamt": u.total, "belegt": u.used, "frei": u.free,
                    "prozent": u.percent})
    return aus


def bericht(anzahl: int = ANZAHL, fenster: float = FENSTER_S) -> Dict[str, Any]:
    """Momentaufnahme der Systemauslastung. BLOCKIERT `fenster` Sekunden."""
    kerne = psutil.cpu_count(logical=True) or 1

    # ── Startpunkt ──────────────────────────────────────────────────────
    procs = _prozesse_vorher()
    psutil.cpu_percent(None)
    psutil.cpu_percent(None, percpu=True)
    net0 = psutil.net_io_counters()
    try:
        disk0 = psutil.disk_io_counters()
    except Exception:
        disk0 = None
    t0 = time.monotonic()

    time.sleep(fenster)

    # ── Endpunkt ────────────────────────────────────────────────────────
    je_kern = psutil.cpu_percent(None, percpu=True)
    gesamt = psutil.cpu_percent(None)
    net1 = psutil.net_io_counters()
    try:
        disk1 = psutil.disk_io_counters()
    except Exception:
        disk1 = None
    dt = max(1e-3, time.monotonic() - t0)

    zeilen = []
    for p in procs.values():
        z = _prozess_zeile(p, kerne)
        if z is not None:
            zeilen.append(z)
    # Gleichstand nach Speicher, dann PID: sonst springt die Reihenfolge der
    # vielen 0-%-Prozesse bei jedem Abruf.
    zeilen.sort(key=lambda z: (-z["cpu"], -z["rss"], z["pid"]))

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    try:
        last = list(os.getloadavg())
    except OSError:
        last = []

    netz = {
        "rx_rate": max(0.0, (net1.bytes_recv - net0.bytes_recv) / dt),
        "tx_rate": max(0.0, (net1.bytes_sent - net0.bytes_sent) / dt),
        "rx_gesamt": net1.bytes_recv,
        "tx_gesamt": net1.bytes_sent,
    }
    if disk0 is not None and disk1 is not None:
        io = {
            "lesen_rate": max(0.0, (disk1.read_bytes - disk0.read_bytes) / dt),
            "schreiben_rate": max(0.0, (disk1.write_bytes - disk0.write_bytes) / dt),
        }
    else:
        io = {"lesen_rate": None, "schreiben_rate": None}

    return {
        "erzeugt_am": datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "fenster_s": round(dt, 2),
        "cpu": {
            "prozent": gesamt,
            "je_kern": je_kern,
            "kerne": kerne,
            "last": [round(x, 2) for x in last],
        },
        "speicher": {
            "gesamt": mem.total, "belegt": mem.total - mem.available,
            "verfuegbar": mem.available, "prozent": mem.percent,
            "swap_gesamt": swap.total, "swap_belegt": swap.used,
            "swap_prozent": swap.percent,
        },
        "netz": netz,
        "platte": {"io": io, "partitionen": _platten()},
        "prozesse_gesamt": len(zeilen),
        "prozesse": zeilen[:max(1, int(anzahl))],
    }
