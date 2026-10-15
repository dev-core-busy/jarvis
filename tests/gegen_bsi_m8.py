#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_m8.py: beisst der Waechter?

Jede Probe dreht EINEN Teil von M8 zurueck (Python-Ersetzung ganzer Zeilen),
laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher gruener
Basislauf, danach Byte-Gleichheit aller Dateien per md5, ohne Bytecode, mit
Laufmarke (abgeschossener Lauf wird beim naechsten Start zurueckgenommen).

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
MARKE = ROOT / "tests" / ".gegen_bsi_m8.laufmarke"

JO = "backend/broker/journal.py"
OP = "backend/broker/ops.py"
SH = "backend/tools/shell.py"
HI = "deploy/security/haertung_installieren.sh"
SB = "deploy/security/setup_broker.sh"
UG = "backend/url_geheimnis.py"

PROBEN = [
    ("Einheit: jede Einheit erlaubt", JO,
     '    if not _EINHEIT.fullmatch(e):\n', '    if not e:\n'),
    ("Zeilen nicht gedeckelt", JO,
     '    out["zeilen"] = max(1, min(n, ZEILEN_MAX))\n', '    out["zeilen"] = max(1, n)\n'),
    ("Zeitangabe ungeprueft", JO,
     '            if not _ZEIT.fullmatch(v):\n', '            if False:\n'),
    ("Suche als getrennter Wert (Optionsschmuggel)", JO,
     '        cmd.append("--grep=" + norm["suche"])\n', '        cmd += ["--grep", norm["suche"]]\n'),
    ("aus_befehl: ohne -u uebersetzt", JO,
     '    if "einheit" not in args:\n        return None', '    if False:\n        return None'),
    ("aus_befehl: unbekannte Option uebersetzt", JO,
     '            return None              # unbekannte Option -> nicht uebersetzen\n',
     '            i += 1\n            continue\n'),
    ("aus_befehl: Umleitung/; im Kopf erlaubt", JO,
     '    if re.search(r"[;&<>`]|\\$\\(|\\n", kopf):\n', '    if False:\n'),
    ("aus_befehl: || als Rohr", JO,
     '                return -1          # \'||\' -> kein einfaches Rohr, nicht uebersetzen\n',
     '                return i\n'),
    ("Op: Pruefung uebersprungen", OP,
     '        norm = journal.pruefen(args)\n    except ValueError as e:\n',
     '        norm = dict(journal.pruefen({"einheit": "jarvis"}), einheit=str(args.get("einheit")))\n    except ValueError as e:\n'),
    ("Op: ohne Schwaerzung", OP,
     '        aus = "\\n".join(url_geheimnis.schwaerzen(z) for z in aus.split("\\n"))\n',
     '        pass\n'),
    ("Op: Kappungshinweis hinten", OP,
     '        aus = ("[gekappt: die ersten %d Zeichen fehlen]\\n" % gekappt) + aus[-journal.AUSGABE_MAX:]\n',
     '        aus = aus[-journal.AUSGABE_MAX:] + ("\\n[gekappt: die ersten %d Zeichen fehlen]" % gekappt)\n'),
    ("Op: unauditiert (READONLY)", OP,
     '                "tika_status", "unlock_screen", "vnc_restart"}\n',
     '                "tika_status", "unlock_screen", "vnc_restart", "journal_lesen"}\n'),
    ("Shell: auch ohne Broker-Recht uebersetzt", SH,
     '                            if kwargs.get("_root_broker") and os.geteuid() != 0 else None)\n',
     '                            if os.geteuid() != 0 else None)\n'),
    ("Shell: Fortsetzung | grep verworfen", SH,
     '            aus = o.decode("utf-8", errors="replace")\n',
     '            pass\n'),
    ("Haertung: Gruppen bleiben", HI,
     '            if "$GPASSWD" -d "$m8_user" "$grp" >/dev/null 2>&1; then\n',
     '            if true; then\n'),
    ("Haertung: kein Nachstart", HI,
     '            m8_nachstart=1\n', '            :\n'),
    ("Haertung: Testlauf fasst echte Gruppen an", HI,
     '    m8_aktiv=0\n', '    m8_aktiv=1\n'),
    ("Haertung: auch bei HAERTUNG=aus", HI,
     'if [ "$m8_aktiv" = "1" ] && [ "$modus" = "an" ] && [ -n "$m8_user" ]',
     'if [ "$m8_aktiv" = "1" ] && [ -n "$m8_user" ]'),
    ("setup_broker setzt adm wieder", SB,
     'for grp in video; do\n', 'for grp in video adm systemd-journal; do\n'),
    ("Schwaerzen wieder quadratisch", UG,
     '_USERINFO = re.compile(r"(?<![a-zA-Z0-9+.-])(?P<vor>',
     '_USERINFO = re.compile(r"(?P<vor>'),
]

DATEIEN = [JO, OP, SH, HI, SB, UG, "tests/test_bsi_m8.py"]

WAECHTER = [
    (["python3", "tests/test_bsi_m8.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
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
                print("  BISS %-62s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-62s Waechter konnte nicht laufen (%s)" % (name, rc))
            else:
                print("  ZAHN %-62s 0 FAIL – beisst NICHT" % name)
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
