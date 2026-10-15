#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_h11_vnc_benutzer.py: beisst der Waechter?

Jede Probe dreht EINEN Teil der Behebung (x11vnc nie als root) zurueck; gruener
Basislauf vorher, Byte-Gleichheit nachher, ohne Bytecode, mit Laufmarke.
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKE = ROOT / "tests" / ".gegen_bsi_h11_vnc_benutzer.laufmarke"
DC = "backend/desktop_control.py"
SJ = "start_jarvis_root.sh"
RUN = "run.sh"
T = "tests/test_bsi_h11_vnc_benutzer.py"

PROBEN = [
    ("x11vnc ohne setpriv (als root)", DC,
     '    return [_bin("setpriv"), "--reuid=%d" % pw.pw_uid, "--regid=%d" % pw.pw_gid,\n'
     '            "--clear-groups", "--no-new-privs", "--inh-caps=-all", "--bounding-set=-all",\n'
     '            _bin("x11vnc"),',
     '    return [_bin("x11vnc"),'),
    ("ohne no_new_privs", DC,
     '"--clear-groups", "--no-new-privs", "--inh-caps=-all"', '"--clear-groups", "--inh-caps=-all"'),
    ("Rueckfall auf root ohne Benutzer", DC,
     '        print(msg, flush=True)\n        return msg\n',
     '        print(msg, flush=True)\n'
     '        return subprocess.run(["x11vnc", "-localhost", "-display", display, "-auth", "guess",\n'
     '                               "-nopw", "-bg", "-rfbport", "5900"], capture_output=True, text=True).stdout\n'),
    ("Cookie-Quelle direkt statt Kopie", DC,
     "    kopie = _cookie_kopieren(quelle, display, pw) if quelle else None\n",
     "    kopie = quelle\n"),
    ("Kopie 0644", DC,
     "os.O_NOFOLLOW, 0o600)", "os.O_NOFOLLOW, 0o644)"),
    ("Ziel wird verfolgt statt ersetzt", DC,
     "    try:\n        os.unlink(ziel)\n    except FileNotFoundError:\n        pass\n"
     "    fd = os.open(ziel, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)\n",
     "    fd = os.open(ziel, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)\n"),
    ("Umgebung von root geerbt", DC,
     'env={"PATH": _SYSPFAD, "HOME": VNC_LAUFZEIT, "LC_ALL": "C"})', "env=None)"),
    ("restart_vnc startet wieder selbst", DC,
     '    out = x11vnc_starten(":0")\n',
     '    out = subprocess.run(["x11vnc", "-localhost", "-display", ":0", "-auth", "guess", "-nopw",\n'
     '                          "-bg", "-rfbport", "5900"], capture_output=True, text=True).stdout\n'),
    ("VNC-Segmente nicht aufgeraeumt", DC,
     't[2] in ("root", VNC_BENUTZER)', 't[2] == "root"'),
    ("Startskript ruft x11vnc wieder selbst", SJ,
     '    (cd "$CODE_DIR" && python3 -m backend.desktop_control vnc-starten "$@")\n',
     '    x11vnc -localhost -display "$1" -auth guess -shared -forever -nopw -bg -quiet -rfbport 5900\n'),
    ("fremde root-Unit bleibt", SJ,
     "    systemctl disable --now x11vnc.service >/dev/null 2>&1 \\\n",
     "    true >/dev/null 2>&1 \\\n"),
    ("root-Instanz bleibt", SJ,
     "if pgrep -u root -x x11vnc >/dev/null; then\n", "if false; then\n"),
    ("run.sh als root wieder direkt", RUN,
     '        python3 -m backend.desktop_control vnc-starten "$XDISPLAY" >/dev/null \\\n',
     '        x11vnc -localhost -display "$XDISPLAY" -nopw -bg -rfbport 5900 >/dev/null \\\n'),
]

DATEIEN = [DC, SJ, RUN, T]

WAECHTER = [
    (["python3", T], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf():
    """Alle Waechter; Summe der FAILs. -1 = einer konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    for cmd, muster in WAECHTER:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                               cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            return -1, "timeout " + cmd[-1]
        m = re.search(muster, r.stdout)
        if r.returncode == 2 or not m:
            return -1, f"{cmd[-1]} rc={r.returncode} {r.stdout.strip()[-160:]}"
        summe += int(m.group(2))
    return summe, 0


def zuruecknehmen():
    """Rueckstand eines abgeschossenen Laufs zuruecknehmen (Laufmarke)."""
    if not MARKE.exists():
        return
    try:
        alt = json.loads(MARKE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        print("ABBRUCH: Laufmarke unlesbar – Arbeitsbaum von Hand pruefen")
        sys.exit(2)
    for d, hexinhalt in alt.items():
        (ROOT / d).write_bytes(bytes.fromhex(hexinhalt))
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgenommen.")


def main() -> int:
    zuruecknehmen()
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, %s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    MARKE.write_text(json.dumps({d: b.hex() for d, b in sicherung.items()}), encoding="utf-8")
    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu, 1), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-58s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-58s Waechter konnte nicht laufen (%s)" % (name, rc))
            else:
                print("  ZAHN %-58s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)
        if MARKE.exists():
            MARKE.unlink()

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
