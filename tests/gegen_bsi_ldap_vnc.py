#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_ldap_vnc.py: beisst der Waechter?

Jede Probe dreht EINEN Fix zurueck (Python-Ersetzung ganzer Zeilen), laesst den
Waechter laufen und erwartet mindestens einen FAIL. Vorher gruener Basislauf,
danach Byte-Gleichheit aller Dateien per md5.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_bsi_ldap_vnc.py"
TLS = "backend/ldap_tls.py"
DIR = "backend/ldap_directory.py"
MAIN = "backend/main.py"
SET = "frontend/settings.html"
SKRIPT = "start_jarvis_root.sh"

PROBEN = [
    # ── H5 ──────────────────────────────────────────────────────────────────
    ("H5: StartTLS-Fehler wieder verschluckt (Rueckfall Klartext)", TLS,
     '        if not ldaps and not conn.start_tls():\n'
     '            raise TlsFehler("der Domain-Controller hat StartTLS abgelehnt")\n',
     '        if not ldaps:\n'
     '            try:\n'
     '                conn.start_tls()\n'
     '            except Exception:\n'
     '                pass\n'),
    ("H5: Zertifikatspruefung aus (CERT_NONE)", TLS,
     '    kw: dict = {"validate": ssl.CERT_REQUIRED}\n',
     '    kw: dict = {"validate": ssl.CERT_NONE}\n'),
    ("H5: Anker gilt fuer jeden Host/Port", TLS,
     '    if nur_anker or sap_cert.passt(eintrag, host, port):\n',
     '    if nur_anker or (eintrag or {}).get("pem"):\n'),
    ("H5: Namensabgleich immer aus", TLS,
     '        if not name_pruefen or (eintrag or {}).get("name_abweichung"):\n',
     '        if True:\n'),
    ("H5: bestaetigen nimmt jeden Fingerabdruck", TLS,
     '    if not hmac.compare_digest(erg["fingerprint"], fingerprint.strip().lower()):\n',
     '    if False:\n'),
    ("H5: Verzeichnis-Suche wieder mit altem Rueckfall", DIR,
     '    from backend import ldap_tls\n'
     '    try:\n'
     '        conn = ldap_tls.verbinden(ad_server, user, pw, timeout=6)\n'
     '    except ldap_tls.TlsFehler as e:\n'
     '        raise RuntimeError("TLS_FAILED: " + str(e)[:160])\n'
     '    except Exception as e:  # noqa: BLE001\n'
     '        raise RuntimeError("BIND_FAILED: " + str(e)[:120])\n',
     '    use_ssl = ad_server.lower().startswith("ldaps://")\n'
     '    server = ldap3.Server(ad_server, use_ssl=use_ssl, get_info=ldap3.NONE, connect_timeout=6)\n'
     '    conn = ldap3.Connection(server, user=user, password=pw, auto_bind=False)\n'
     '    if not use_ssl:\n'
     '        try:\n'
     '            conn.open()\n'
     '            conn.start_tls()\n'
     '        except Exception:\n'
     '            pass\n'),
    ("H5: Login wieder mit altem Rueckfall", MAIN,
     '                conn = ldap_tls.verbinden(ad_server, bind_user, password, timeout=5)\n',
     '                server = ldap3.Server(ad_server, get_info=ldap3.NONE, connect_timeout=5)\n'
     '                conn = ldap3.Connection(server, user=bind_user, password=password, auto_bind=False)\n'
     '                try:\n'
     '                    conn.open()\n'
     '                    conn.start_tls()\n'
     '                except Exception:\n'
     '                    pass\n'),
    ("H5: Login-Endpunkt zaehlt TLS-Abbruch als Fehlversuch", MAIN,
     '        if _auth_details.get("reason") == "ad_tls":\n',
     '        if False:\n'),
    ("H5: Anker-Container im Reiter fehlt", SET,
     '                                <div class="sapcert" id="ad-cert"></div>\n',
     ''),
    ("H5: Frist wird ignoriert (Uebergang immer aktiv)", TLS,
     '    return {"aktiv": datetime.date.today() <= ende, "bis": ende.isoformat()}\n',
     '    return {"aktiv": True, "bis": ende.isoformat()}\n'),
    ("H5: Uebergang auch bei gesetztem Anker", TLS,
     '        if not ue["aktiv"] or sap_cert.passt(eintrag, host, port):\n',
     '        if not ue["aktiv"]:\n'),
    ("H5: Uebergang meldet 'ungeprueft' nicht", TLS,
     '        info["ungeprueft"] = True\n',
     '        pass\n'),
    ("H5: Warnhinweis Uebergang fehlt im Reiter", SET,
     '                                <p id="ad-tls-uebergang" hidden style="margin:6px 0;font-size:0.82rem;color:var(--warning);"></p>\n',
     ''),
    # ── H11 ─────────────────────────────────────────────────────────────────
    ("H11: websockify-Port 6080 nicht gesperrt", SKRIPT,
     '        oif "lo" tcp dport { 5900, 6080 } meta skuid != { $1 } reject with tcp reset\n',
     '        oif "lo" tcp dport { 5900 } meta skuid != { $1 } reject with tcp reset\n'),
    ("H11: Regel ohne uid-Bindung (sperrt alle)", SKRIPT,
     '        oif "lo" tcp dport { 5900, 6080 } meta skuid != { $1 } reject with tcp reset\n',
     '        oif "lo" tcp dport { 5900, 6080 } reject with tcp reset\n'),
    ("H11: Regel wird bei jedem Start verdoppelt", SKRIPT,
     'table inet jarvis_vnc {}\n'
     'delete table inet jarvis_vnc\n',
     ''),
    ("H11: Dienstbenutzer faellt aus der Erlaubnis", SKRIPT,
     '    if [ -n "$uid" ] && [ "$uid" != "0" ]; then echo "0, $uid"; else echo "0"; fi\n',
     '    echo "0"\n'),
    ("H11: Sperre wird nie angewendet", SKRIPT,
     '    if _vnc_sperre_regeln "$VNC_UIDS" | nft -f -; then\n',
     '    if true; then\n'),
]

DATEIEN = sorted({p[1] for p in PROBEN} | {"tests/test_bsi_ldap_vnc.py"})


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    # Ohne Bytecode: Sabotage und Wiederherstellung koennen in DERSELBEN Sekunde
    # mit GLEICHER Groesse liegen – dann haelt Python eine .pyc der Sabotage fuer
    # aktuell, und der naechste Lauf misst sie (2026-09-29: Basislauf 18 FAIL).
    umg = dict(os.environ, PATH=os.environ.get("PATH", "") + ":/usr/sbin:/sbin",
               PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       timeout=600, cwd=str(ROOT), env=umg)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-58s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-58s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-58s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)

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
