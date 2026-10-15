#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_m1_m2.py: beisst der Waechter?

Jede Probe dreht EINEN Teil von M1/M2 zurueck (Python-Ersetzung ganzer
Zeilen), laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5, ohne Bytecode,
mit Laufmarke (abgeschossener Lauf wird beim naechsten Start zurueckgenommen).

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
MARKE = ROOT / "tests" / ".gegen_bsi_m1_m2.laufmarke"

SL = "backend/sicherheits_log.py"
MA = "backend/main.py"
LR = "backend/log_retention.py"
PO = "backend/broker/policy.py"
HI = "deploy/security/haertung_installieren.sh"
SJ = "start_jarvis_root.sh"
SB = "deploy/security/setup_broker.sh"

PROBEN = [
    # ── Sicherheitsprotokoll ──
    ("Hash ohne Vorgaenger (Kette nur Pruefsumme)", SL,
     '    return hashlib.sha256((prev + _kanonisch(ohne)).encode("utf-8")).hexdigest()\n',
     '    return hashlib.sha256(_kanonisch({k: v for k, v in ohne.items() if k != "prev"})'
     '.encode("utf-8")).hexdigest()\n'),
    ("pruefen() sieht keine Luecke", SL,
     '            elif prev is not None and e.get("prev") != prev:\n',
     '            elif False:\n'),
    ("kein syslog", SL,
     '        lg = _syslog_logger()\n', '        lg = None\n'),
    ("Protokoll weltlesbar", SL,
     '                    os.chmod(DATEI, 0o600)\n', '                    os.chmod(DATEI, 0o644)\n'),
    ("Kuerzen schneidet hinter juengeren Zeilen weiter", SL,
     '            if ts is None or ts >= cutoff_ts:\n                break\n',
     '            if ts is None or ts >= cutoff_ts:\n                continue\n'),
    ("Kuerzen macht die Datei weltlesbar", SL,
     '        os.chmod(tmp, 0o600)\n', ''),
    ("Unsinn-Frist heisst dauerhaft", SL,
     '    except (TypeError, ValueError):\n        return DEFAULT_TAGE\n',
     '    except (TypeError, ValueError):\n        return 0\n'),
    ("Schreibfehler wirft", SL,
     '            _fehler["datei"] += 1\n', '            raise\n'),
    # ── Aufraeumlauf ──
    ("Sicherheitsprotokoll nur mit Telemetrie-Frist gekuerzt", LR,
     '        if _tage:\n', '        if _tage and cut is not None:\n'),
    # ── main.py ──
    ("Login ohne Protokoll", MA,
     # Nur die Protokollzeile: seit 2026-10-15 steht zwischen Ablauf und
     # Protokoll die Mindestdauer gegen Password Spraying.
     '    await _anmeldung_protokollieren(request, resp, "kennwort")\n', ''),
    ("SSO ohne Protokoll", MA,
     '    await _anmeldung_protokollieren(request, resp, "outlook_sso")\n', ''),
    ("Fehlschlaege nicht protokolliert", MA,
     '        elif status >= 400:\n            _sicherheits_log.ereignis("anmeldung_fehlgeschlagen"',
     '        elif False:\n            _sicherheits_log.ereignis("anmeldung_fehlgeschlagen"'),
    ("Fehlschlag ohne IP", MA,
     '            _sicherheits_log.ereignis("anmeldung_fehlgeschlagen", benutzer=name, ip=ip,\n',
     '            _sicherheits_log.ereignis("anmeldung_fehlgeschlagen", benutzer=name, ip="",\n'),
    ("Rueckfrage 2FA zaehlt als Fehlschlag", MA,
     '        elif status >= 400:\n            _sicherheits_log.ereignis("anmeldung_fehlgeschlagen"',
     '        else:\n            _sicherheits_log.ereignis("anmeldung_fehlgeschlagen"'),
    ("Kontosperre nicht protokolliert", MA,
     '    if _anmelde_schutz.fehlversuch(ip, _norm_login(username) if username else ""):\n'
     '        _sicherheits_log.ereignis("konto_gesperrt"',
     '    _anmelde_schutz.fehlversuch(ip, _norm_login(username) if username else "")\n'
     '    if False:\n        _sicherheits_log.ereignis("konto_gesperrt"'),
    ("Abmeldung nicht protokolliert", MA,
     '    _sicherheits_log.ereignis("abmeldung", benutzer=user,\n',
     '    (lambda *a, **k: None)("abmeldung", benutzer=user,\n'),
    ("_user_is_admin ohne Dekorator", MA,
     '@_admin_pruefung_merken\ndef _user_is_admin(', 'def _user_is_admin('),
    ("Halter per set() statt Aenderung (kommt aus dem Threadpool nicht zurueck)", MA,
     '                halter["admin"] = bool(halter.get("admin")) or bool(ergebnis)\n',
     '                _admin_anfrage.set({"benutzer": kx[0], "admin": bool(ergebnis)})\n'),
    ("fremdes Konto zaehlt als Admin-Anfrage", MA,
     '            if kx is not None and kx[0] == _norm_login(user):\n                halter["benutzer"]',
     '            if kx is not None:\n                halter["benutzer"]'),
    ("Pfad samt Query (Tokens) im Protokoll", MA,
     '        pfad = request.url.path\n        ip = request.client.host if request.client else ""\n'
     '        status = response.status_code\n',
     '        pfad = request.url.path + "?" + request.url.query\n'
     '        ip = request.client.host if request.client else ""\n'
     '        status = response.status_code\n'),
    ("verweigerte Admin-Aktion nicht protokolliert", MA,
     '            elif status == 403:\n', '            elif False:\n'),
    ("Kennwortwechsel nicht protokolliert", MA,
     '_KONTO_PFADE = ("/api/change-password", "/api/auth/totp/")\n',
     '_KONTO_PFADE = ("/api/auth/totp/",)\n'),
    ("Middleware nicht registriert", MA,
     '@app.middleware("http")\nasync def _sicherheits_protokoll_mw(',
     'async def _sicherheits_protokoll_mw('),
    ("verify_token meldet die Sitzung nicht", MA,
     '                _halter.setdefault("sitzung", _norm_login(username))\n',
     '                pass\n'),
    # ── Broker-Audit ──
    ("audit_tail ignoriert die gedrehte Datei", PO,
     '        if len(lines) < n and vorher.exists():\n', '        if False:\n'),
    # ── Haertung ──
    ("NoNewPrivileges im Backend (bricht lokale Anmeldung)", HI,
     'ProtectSystem=strict\n', 'ProtectSystem=strict\nNoNewPrivileges=yes\n'),
    ("ProtectKernelTunables im Backend (bricht bwrap)", HI,
     'ProtectKernelModules=yes\n', 'ProtectKernelModules=yes\nProtectKernelTunables=yes\n'),
    ("ProtectHostname im Backend (bricht bwrap zusammen mit ProtectSystem)", HI,
     'ProtectControlGroups=yes\n', 'ProtectControlGroups=yes\nProtectHostname=yes\n'),
    ("ProtectSystem fehlt", HI, 'ProtectSystem=strict\n', ''),
    ("Projektbaum nicht schreibbar", HI,
     'ReadWritePaths=$JARVIS_DIR -$svc_home', 'ReadWritePaths=-$svc_home'),
    ("Bounding-Set fehlt", HI, 'CapabilityBoundingSet=CAP_NET_BIND_SERVICE\n', ''),
    ("Backend-Haertung auch im Alt-Betrieb als root", HI,
     '    if [ -n "$svc_user" ] && [ "$svc_user" != "root" ]; then\n',
     '    if [ -n "$svc_user" ]; then\n'),
    ("Notausgang wirkungslos", HI, '    modus="aus"\n', '    modus="an"\n'),
    ("nicht idempotent", HI,
     '    if [ -f "$ziel" ] && [ "$(cat "$ziel")" = "$inhalt" ]; then\n',
     '    if false; then\n'),
    ("Rotation ohne Altersgrenze", HI, '    maxage 365\n', ''),
    ("Rotation nach Stueckzahl (rotate 4)", HI, '    rotate 1000\n', '    rotate 4\n'),
    ("Rotation nach Groesse", HI, '    weekly\n', '    weekly\n    size 10M\n'),
    ("Rotation komprimiert sofort (.1 unlesbar)", HI, '    delaycompress\n', ''),
    ("Broker-Start ruft die Haertung nicht", SJ,
     '    bash "$CODE_DIR/deploy/security/haertung_installieren.sh" "$JARVIS_DIR" \\\n',
     '    true "$CODE_DIR/deploy/security/haertung_installieren.sh" "$JARVIS_DIR" \\\n'),
    ("setup_broker ohne Haertung", SB,
     'bash "$SELF_DIR/haertung_installieren.sh" "$JARVIS_DIR" || true\n', ''),
]

DATEIEN = [SL, MA, LR, PO, HI, SJ, SB, "tests/test_bsi_m1_m2.py"]

WAECHTER = [
    (["python3", "tests/test_bsi_m1_m2.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
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
