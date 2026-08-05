#!/usr/bin/env python3
"""Bewertet gespeicherte Richtlinien-Verstoesse nach den Regeln vom 2026-08-05 neu.

**Warum das noetig ist:** Bis zum 2026-08-05 zaehlte jeder abgewiesene Werkzeug-Aufruf
als Verstoss – auch reine Sandbox-Grenzen und mehrere nachgewiesene Fehlalarme
(`2>/dev/null` als Schreibziel, `||` als Pipe gelesen, ein vom MODELL gewaehltes
gesperrtes Werkzeug, ein vom Modell geratener Pfad). `security_guard` sperrt ab drei
Verstoessen in zehn Minuten; auf ECHT sind so zwischen dem 09.07. und dem 05.08.
**zehn** Auto-Sperren entstanden. Die Code-Fixes verhindern das kuenftig – der
Altbestand zaehlt aber weiter mit, weil die Sperrpruefung ueber das Zeitfenster
zurueckblickt.

**Was das Skript tut:** Es markiert betroffene Eintraege mit ``soft: true`` und einer
Begruendung (``soft_reason``). Es LOESCHT NICHTS und aendert keinen Text – das
Protokoll bleibt vollstaendig und in der Oberflaeche sichtbar, die Eintraege zaehlen
nur nicht mehr zur Auto-Sperre (``record_violation`` filtert ueber das Feld).

Aufruf (als Dienstbenutzer, damit die Dateirechte erhalten bleiben):
    python3 deploy/security/reclassify_violations.py            # Trockenlauf
    python3 deploy/security/reclassify_violations.py --apply    # schreibt (mit Sicherung)
    python3 deploy/security/reclassify_violations.py --file <pfad> [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_FILE = ROOT / "data" / "security_state.json"

# ── Bewertungsregeln (bewusst aus dem Produktivcode geladen, nicht nachgebaut) ──
# Ein Nachbau wuerde beim naechsten Regel-Fix auseinanderlaufen und genau die
# Eintraege verschonen, die dann neu als Fehlalarm gelten.
_src = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
_ns: dict = {"re": re}
for _n in ("_SHELL_DEV_SINKS", "_SHELL_WRITE_ATTACK_TARGET"):
    _m = re.search(r'\n(' + _n + r'\s*=\s*(?:frozenset\(|re\.compile\().*?\n\))', _src, re.S)
    if not _m:
        sys.exit(f"ABBRUCH: {_n} nicht in backend/agent.py gefunden")
    exec(_m.group(1), _ns)
for _n in ("_strip_heredocs", "_shell_redirect_writes", "_shell_write_targets",
           "_ldap_redirects_safe", "_shell_write_is_attack"):
    _m = re.search(r'\ndef ' + _n + r'\(.*?(?=\ndef |\n[A-Z_]{3,}\s*=|\n# ──|\Z)', _src, re.S)
    if not _m:
        sys.exit(f"ABBRUCH: {_n} nicht in backend/agent.py gefunden")
    exec(_m.group(0), _ns)

_sbx_src = (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8")
_sns: dict = {"re": re}
for _n in ("SHELL_OBFUSCATION", "SHELL_EXEC_WORDS", "SHELL_SECRET_PATHS"):
    _m = re.search(r'\n(' + _n + r'\s*=\s*re\.compile\(.*?\n\))', _sbx_src, re.S)
    if not _m:
        sys.exit(f"ABBRUCH: {_n} nicht in backend/sandbox.py gefunden")
    exec(_m.group(1), _sns)
_m = re.search(r'\ndef strip_quoted\(.*?(?=\ndef |\Z)', _sbx_src, re.S)
exec(_m.group(0), _sns)

# Secret-/System-Ziele fuer fs-deny. Bewusst eine TEXTPRUEFUNG des protokollierten
# Pfades: der Pfad von damals existiert heute vielleicht nicht mehr, ein
# `Path.resolve()` wuerde dann anders entscheiden als die Aufzeichnung.
_FS_SENSITIVE = re.compile(
    r'\.env\b|settings\.json|memory\.json|auth_state|credentials\.json|\.owners\.json|'
    r'scheduled_jobs\.json|file_watchers\.json|security_state\.json|conv_log|audit_log|'
    r'data/instructions|data/chats|data/logs|/certs|\.ssh|id_rsa|id_ed25519|\.netrc|'
    r'/etc/shadow|/etc/gshadow|/etc/sudoers|(?:^|\s|/)/?root(?:/|\b)|/boot/|/proc/|/sys/|'
    r'\.key\b|\.pem\b|\.p12\b|\.pfx\b|\.jks\b|/\.git/',
    re.IGNORECASE,
)


def _cmd_of(entry: dict) -> str:
    """Der vollstaendigste verfuegbare Befehlstext: snippet (JSON der Argumente) ist
    laenger als detail, beides kann gekuerzt sein (bis 2026-08-05: 200/120 Zeichen)."""
    snip = entry.get("snippet") or ""
    try:
        args = json.loads(snip)
        if isinstance(args, dict) and args.get("command"):
            return str(args["command"])
    except Exception:  # noqa: BLE001
        pass
    return entry.get("detail") or ""


def _was_truncated(entry: dict) -> bool:
    """War der protokollierte Text schon am alten Deckel (120/200 Zeichen)?

    Dann beruht die Neubewertung auf einem AUSSCHNITT. Das gehoert in die
    Begruendung: sonst liest sich ein "Fehlalarm" wie eine gesicherte Aussage,
    obwohl der entscheidende Teil des Befehls fehlt."""
    return len(entry.get("detail") or "") >= 120 or len(entry.get("snippet") or "") >= 200


def classify(entry: dict) -> tuple[bool, str]:
    """(soft, begruendung) – soft=True heisst: zaehlt nicht mehr zur Auto-Sperre."""
    pat = entry.get("pattern") or ""

    if pat == "blocked-tool":
        return True, "Werkzeugwahl trifft das Modell, nicht der Benutzer"

    if pat == "fs-deny":
        path = " ".join((entry.get("detail") or "").split()[1:])
        if path and _FS_SENSITIVE.search(path):
            return False, ""
        return True, "geratener Pfad ausserhalb des Arbeitsbereichs (kein Secret-Ziel)"

    if pat == "shell-write":
        cmd = _ns["_strip_heredocs"](_cmd_of(entry))
        if _ns["_ldap_redirects_safe"](cmd):
            return True, "kein Schreibziel (Geraete-Senke bzw. 2>&1) – Fehlalarm"
        if not _ns["_shell_write_is_attack"](cmd):
            return True, "Schreibziel ausserhalb /tmp, aber kein System-/Secret-Ziel"
        return False, ""

    if pat == "shell-illegal":
        cmd = _cmd_of(entry)
        if _sns["SHELL_SECRET_PATHS"].search(cmd):
            return False, ""                     # echter Secret-/Root-Zugriff
        if (_sns["SHELL_OBFUSCATION"].search(cmd)
                or _sns["SHELL_EXEC_WORDS"].search(_sns["strip_quoted"](cmd))):
            return False, ""                     # nach den neuen Regeln weiter Verschleierung
        return True, "nach heutiger Regel keine Verschleierung ('||' bzw. Wort in Anfuehrungszeichen)"

    # shell-forbidden und alles Unbekannte bleiben hart: nicht raten.
    return False, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT_FILE))
    ap.add_argument("--apply", action="store_true", help="Aenderungen schreiben (sonst Trockenlauf)")
    ap.add_argument("--soft-entry", type=int, action="append", default=[], metavar="TS",
                    help="Einzelnen Vorfall (per Zeitstempel) ausdruecklich weich setzen. "
                         "Fuer Faelle, die keine Regel erkennen kann – z.B. der Cron-Lauf "
                         "vom 28.07.2026 03:00, der einem fremden Chat-Benutzer "
                         "zugeschrieben wurde (Actor-Bindung, seither behoben).")
    ap.add_argument("--reason", default="vom Administrator geprueft: kein Angriffsindiz",
                    help="Begruendung fuer --soft-entry")
    a = ap.parse_args()

    path = Path(a.file)
    if not path.exists():
        print(f"Datei nicht vorhanden: {path}")
        return 1
    state = json.loads(path.read_text(encoding="utf-8"))
    viol = state.get("violations", {})

    stats: dict[str, int] = {}
    n_new = 0
    total = 0
    for user, entries in viol.items():
        for e in entries:
            total += 1
            soft, why = classify(e)
            if e.get("ts") in a.soft_entry:       # ausdrueckliche Einzelentscheidung
                soft, why = True, a.reason
            elif soft and _was_truncated(e):
                why += " [Text war gekuerzt – Bewertung anhand des Ausschnitts]"
            if not soft:
                continue
            stats[e.get("pattern", "?")] = stats.get(e.get("pattern", "?"), 0) + 1
            if e.get("soft"):
                continue                          # schon markiert – idempotent
            n_new += 1
            print(f"  {time.strftime('%d.%m %H:%M', time.localtime(e.get('ts', 0)))} "
                  f"{user:24} {e.get('pattern',''):16} {why}")
            if a.apply:
                e["soft"] = True
                e["soft_reason"] = why

    print(f"\n{total} Vorfaelle geprueft, {sum(stats.values())} weich "
          f"({n_new} neu markiert): {stats}")

    # Konten, die NUR noch weiche Vorfaelle haben, koennen nicht mehr durch den
    # Altbestand gesperrt werden. Gesperrte Konten werden NICHT automatisch
    # entsperrt – das ist eine Entscheidung des Administrators.
    blocked = state.get("blocked", {})
    if blocked:
        print("\nWeiter gesperrt (Entsperren bleibt Handarbeit, siehe /api/security/unblock):")
        for u, i in blocked.items():
            print(f"  {u} – {i.get('reason')}")

    if not a.apply:
        print("\nTrockenlauf – nichts geschrieben. Mit --apply anwenden.")
        return 0

    bak = path.with_name(path.name + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, bak)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:                                          # Eigentuemer/Modus der Zieldatei erhalten
        st = path.stat()
        os.chmod(tmp, st.st_mode & 0o777)
        os.chown(tmp, st.st_uid, st.st_gid)
    except Exception as e:                        # noqa: BLE001
        print(f"Hinweis: Rechte konnten nicht uebernommen werden ({e})")
    os.replace(tmp, path)
    print(f"\nGeschrieben. Sicherung: {bak}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
