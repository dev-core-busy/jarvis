#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_m6_m7.py: beisst der Waechter?

Jede Probe dreht EINEN Teil der M6/M7-Behebung zurueck (Python-Ersetzung ganzer
Zeilen), laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5. Ohne Bytecode.

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
WAECHTER = ROOT / "tests" / "test_bsi_m6_m7.py"
SSH = "deploy/security/ssh_haertung.sh"
FW = "deploy/security/firewall.sh"
HI = "deploy/security/haertung_installieren.sh"
NODE = "deploy/security/node_aktualisieren.sh"
SJR = "start_jarvis_root.sh"
DF = "Dockerfile"
BDF = "services/whatsapp-bridge/Dockerfile"
INST = "docs/install.sh"
WF = ".github/workflows/sicherheit.yml"
DB = ".github/dependabot.yml"
PA = "deploy/security/pip_audit_ausnahmen.py"
CI = "tests/ci_lauf.py"
REQ = "requirements.txt"
GOMOD = "windows-app-go/go.mod"
AGR = "android/app/build.gradle.kts"
GWP = "android/gradle/wrapper/gradle-wrapper.properties"

PROBEN = [
    # ── M7: ssh_haertung.sh ──
    ("Kennwort-Anmeldung bleibt an", SSH,
     '        "PasswordAuthentication no" \\\n', '        "PasswordAuthentication yes" \\\n'),
    ("Tastatur-interaktiv fehlt im Drop-in", SSH,
     '        "KbdInteractiveAuthentication no" \\\n', ''),
    ("PermitRootLogin yes als Vorgabe", SSH,
     '        *)          echo "no" ;;\n', '        *)          echo "yes" ;;\n'),
    ("Drop-in heisst 50-… (verliert gegen cloud-init)", SSH,
     'DROPIN="$DROPIN_DIR/05-jarvis-haertung.conf"\n',
     'DROPIN="$DROPIN_DIR/60-jarvis-haertung.conf"\n'),
    ("--anwenden ohne Aussperr-Schutz", SSH,
     '    --anwenden)\n        _ist_root\n        _aussperr_schutz "$ERZWINGEN" || exit $?\n',
     '    --anwenden)\n        _ist_root\n'),
    ("Aussperr-Schutz prueft den Aufrufer nicht", SSH,
     '    if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then\n',
     '    if false; then\n'),
    ("nologin-Konten zaehlen als Zugang", SSH,
     '        case "$shell" in */nologin|*/false|"") continue ;; esac\n        [ -n "$home" ] || continue\n',
     '        [ -n "$home" ] || continue\n'),
    ("SSH_ROOT=nein laesst root als Zugang gelten", SSH,
     '    if [ "$(_root_modus)" != "no" ]; then\n', '    if true; then\n'),
    ("--erneuern schreibt auch ohne SSH_HAERTUNG=an", SSH,
     '            *)\n                if [ -z "$TEST" ] && "$SSHD_BIN" -T 2>/dev/null',
     '            *)\n                _schreiben\n                if [ -z "$TEST" ] && "$SSHD_BIN" -T 2>/dev/null'),
    ("--erneuern ignoriert den Aussperr-Schutz", SSH,
     '                if _aussperr_schutz 0 >/dev/null; then\n',
     '                if true; then\n'),
    ("fehlendes Include wird nicht erkannt", SSH,
     '    if ! _include_vorhanden; then\n', '    if false; then\n'),
    # ── M7: Broker-Start ──
    ("Broker-Start ruft ssh_haertung.sh nicht", HI,
     '    JARVIS_BROKER_CONF="$BROKER_CONF" bash "$SSH_SKRIPT" --erneuern || true\n', '    :\n'),
    # ── M7: Firewall ──
    ("SSH_NETZE wird nicht gelesen", FW,
     '\n_ssh_netze_laden\n', '\n'),
    ("22 bleibt trotz SSH_NETZE allgemein offen", FW,
     '    TCP_OFFEN=("${_ohne22[@]}")\n', ''),
    ("IPv6-Netze fehlen an Port 22", FW,
     '        ssh_regeln+="${nl}        ip6 saddr { ${v6//,/, } } tcp dport 22 ct state new accept"\n',
     ''),
    ("eigene Sitzung wird nicht geprueft", FW,
     '    echo "ABBRUCH: eigene Sitzung $client liegt nicht in SSH_NETZE – das naechste Login waere gesperrt." >&2\n    exit 3\n',
     '    return 0\n'),
    ("ungueltiges Netz still verworfen", FW,
     '            *)    echo "SSH_NETZE ungueltig: $zeile" >&2; exit 1 ;;\n', '            *)    ;;\n'),
    # ── M6: Node ──
    ("Dockerfile wieder per setup-Skript in die Shell", DF,
     '    && JARVIS_DIR=/nicht-vorhanden bash /tmp/node_aktualisieren.sh \\\n',
     '    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \\\n'),
    ("Dockerfile kopiert das Skript, fuehrt es aber nicht aus", DF,
     '    && JARVIS_DIR=/nicht-vorhanden bash /tmp/node_aktualisieren.sh \\\n',
     '    && true \\\n'),
    ("Dockerfile zurueck auf bookworm", DF, 'FROM debian:trixie-slim\n', 'FROM debian:bookworm-slim\n'),
    ("Bridge-Image zurueck auf node:20", BDF, 'FROM node:24-slim\n', 'FROM node:20-slim\n'),
    ("install.sh zurueck auf Node 20 (rpm)", INST,
     '            curl -fsSL https://rpm.nodesource.com/setup_24.x | $SUDO bash - >/dev/null 2>&1\n',
     '            curl -fsSL https://rpm.nodesource.com/setup_20.x | $SUDO bash - >/dev/null 2>&1\n'),
    ("install.sh (apt) wieder per setup-Skript in die Shell", INST,
     '            NODE_UEBER_SKRIPT=1\n',
     '            curl -fsSL https://deb.nodesource.com/setup_24.x | $SUDO bash - >/dev/null 2>&1\n'),
    ("install.sh ruft das Node-Skript nicht mehr auf", INST,
     '        $SUDO env JARVIS_DIR="$INSTALL_DIR" bash "$INSTALL_DIR/deploy/security/node_aktualisieren.sh"; then\n',
     '        true; then\n'),
    ("--pruefen meldet immer Erfolg", NODE,
     '    if [ "$m" -ge "$MINDEST" ] 2>/dev/null; then\n', '    if true; then\n'),
    ("MINDEST auf 20", NODE, 'MINDEST=22\n', 'MINDEST=20\n'),
    ("Node-Skript per curl | bash", NODE,
     'curl -fsSL --proto \'=https\' --tlsv1.2 "$SCHLUESSEL_URL" -o "$tmp/key.asc" \\\n',
     'curl -fsSL https://deb.nodesource.com/setup_24.x | bash\ncurl -fsSL --proto \'=https\' --tlsv1.2 "$SCHLUESSEL_URL" -o "$tmp/key.asc" \\\n'),
    ("Broker-Start meldet alte Node-Linie nicht", SJR,
     '    bash "$NODE_SKRIPT" --pruefen >/dev/null \\\n'
     '        || echo "[Broker] WARNUNG: Node $(node --version 2>/dev/null) bekommt keine Sicherheitsupdates mehr (BSI M6)." >&2\n',
     '    :\n'),
    ("Broker-Start legt keinen Node-Timer an", SJR,
     '    systemd-run --collect --unit=jarvis-node-aktualisieren \\\n', '    : \\\n'),
    ("Node-Timer nur beim Start, nicht taeglich", SJR,
     '        --on-active=5min --on-calendar=daily --timer-property=RandomizedDelaySec=30min \\\n',
     '        --on-active=5min \\\n'),
    ("Node-Timer wieder nur unter der Ziel-Linie", SJR,
     '    systemd-run --collect --unit=jarvis-node-aktualisieren \\\n',
     '    bash "$NODE_SKRIPT" --ziel-erreicht || \\\n    systemd-run --collect --unit=jarvis-node-aktualisieren \\\n'),
    ("vorhandener Node-Timer wird nicht gestoppt", SJR,
     '    systemctl stop jarvis-node-aktualisieren.timer >/dev/null 2>&1\n', ''),
    # ── M6: Nachziehen innerhalb der Linie (CVE-2026-111497) ──
    ("--automatisch zieht auf der Ziel-Linie nicht nach", NODE,
     '        _linie_nachziehen\n        exit $?\n', '        exit 0\n'),
    ("Versionsvergleich als Text statt nach dpkg", NODE,
     '    if ! dpkg --compare-versions "$kand" gt "$inst"; then\n',
     '    if [[ ! "$kand" > "$inst" ]]; then\n'),
    ("Nachziehen ueber die Linie hinaus", NODE,
     '    if [ "${kand%%.*}" != "$(_major)" ]; then\n', '    if false; then\n'),
    ("Nachziehen ohne Fremd-Schranke", NODE,
     '    if [ -n "$f" ]; then\n        echo "[Node] ABBRUCH: Nachziehen',
     '    if false; then\n        echo "[Node] ABBRUCH: Nachziehen'),
    ("unbestimmbarer Stand gilt als aktuell", NODE,
     '    if [ -z "$inst" ] || [ -z "$kand" ] || [ "$kand" = "(none)" ]; then\n', '    if false; then\n'),
    ("Nachziehen als blosses install statt --only-upgrade", NODE,
     '        DEBIAN_FRONTEND=noninteractive apt-get install -y --only-upgrade -o DPkg::Lock::Timeout=300 nodejs \\\n',
     '        DEBIAN_FRONTEND=noninteractive apt-get install -y -o DPkg::Lock::Timeout=300 nodejs \\\n'),
    ("Bridge nach dem Nachziehen nicht neu gestartet", NODE,
     '        echo "[Node] nachher: $(node --version 2>/dev/null || echo keins)"\n    fi\n    _bridge_bauen\n',
     '        echo "[Node] nachher: $(node --version 2>/dev/null || echo keins)"\n    fi\n'),
    ("--automatisch prueft fremde Entfernungen nicht", NODE,
     '    if [ -n "$fremd" ]; then\n', '    if false; then\n'),
    ("--automatisch ignoriert NODE_AUTO=aus", NODE,
     "    if [ -f \"$KONF\" ] && grep -qiE '^[[:space:]]*NODE_AUTO[[:space:]]*=[[:space:]]*\"?aus' \"$KONF\"; then\n",
     '    if false; then\n'),
    ("Paket-Hook startet nach jedem Lauf neu (Schleife)", "backend/main.py",
     '                if neu and neu != vorher and not erg.get("zurueckgesetzt"):\n',
     '                if neu:\n'),
    # ── M6: CI ──
    ("gitleaks nur auf dem letzten Commit", WF,
     '          fetch-depth: 0\n      - name: gitleaks holen und pruefen\n',
     '          fetch-depth: 1\n      - name: gitleaks holen und pruefen\n'),
    ("pip-audit ohne Ausnahmeliste", WF,
     '          ARGS=$(python3 deploy/security/pip_audit_ausnahmen.py --argumente)\n', '          ARGS=""\n'),
    ("npm audit entfernt", WF,
     '        run: npm audit --omit=dev --audit-level=moderate\n', '        run: "true"\n'),
    ("Waechter-Lauf entfernt", WF,
     '        run: venv/bin/python tests/ci_lauf.py --parallel 4 --zeitdeckel 300 --ausnahmen-pruefen\n',
     '        run: "true"\n'),
    ("bandit entfernt", WF, '      - run: bandit -q -r backend skills -lll -iii\n', '      - run: "true"\n'),
    ("govulncheck entfernt", WF,
     '            "$(go env GOPATH)/bin/govulncheck" ./...\n', '            true\n'),
    ("govulncheck mit beliebiger Toolchain", WF,
     '          if [ -z "$tc" ]; then echo "go.mod ohne toolchain-Zeile" >&2; exit 1; fi\n'
     '          export GOTOOLCHAIN="$tc"\n',
     '          if [ -z "$tc" ]; then echo "go.mod ohne toolchain-Zeile" >&2; exit 1; fi\n'
     '          export GOTOOLCHAIN=auto\n'),
    ("Go-SBOM ohne Standardbibliothek", WF,
     '            "$(go env GOPATH)/bin/cyclonedx-gomod" app -json -std -licenses=false \\\n',
     '            "$(go env GOPATH)/bin/cyclonedx-gomod" app -json -licenses=false \\\n'),
    ("Android-SBOM entfernt", WF,
     '        run: ./gradlew --no-daemon -q :app:cyclonedxDirectBom\n', '        run: "true"\n'),
    ("Android-SBOM mit Test-Konfigurationen", AGR,
     '    includeConfigs.set(listOf("releaseRuntimeClasspath"))\n', ''),
    ("Gradle-Distribution ohne Pruefsumme", GWP,
     'distributionSha256Sum=f397b287023acdba1e9f6fc5ea72d22dd63669d59ed4a289a29b1a76eee151c6\n', ''),
    ("go.mod ohne toolchain-Zeile", GOMOD, '\ntoolchain go1.27.3\n', '\n'),
    ("kein Pull-Request-Ausloeser", WF,
     '  pull_request:\n    branches: [master]\n', ''),
    ("Dependabot ohne numpy-Grenze", DB,
     "      - dependency-name: numpy\n        versions: ['>=2.1']\n", ''),
    ("pip-audit-Ausnahme ohne Grund erlaubt", PA,
     r'ZEILE = re.compile(r"^(?P<id>[A-Z][A-Z0-9]*-[0-9A-Za-z-]+)\s+(?P<bis>\d{4}-\d{2}-\d{2})\s+#\s*(?P<grund>\S.*)$")' + "\n",
     r'ZEILE = re.compile(r"^(?P<id>[A-Z][A-Z0-9]*-[0-9A-Za-z-]+)\s+(?P<bis>\d{4}-\d{2}-\d{2})\s*#?\s*(?P<grund>.*)$")' + "\n"),
    ("abgelaufene Ausnahme gilt still weiter", PA,
     '        (abgelaufen if bis < heute else gueltig).append(m["id"])\n',
     '        gueltig.append(m["id"])\n'),
    ("CI-Lauf nimmt gegen_* mit", CI,
     '    dateien = sorted(TESTS.glob("test_*.py")) + sorted(TESTS.glob("test_*.js"))\n',
     '    dateien = sorted(TESTS.glob("*_*.py")) + sorted(TESTS.glob("test_*.js"))\n'),
    ("CI-Ausnahme ohne Grund erlaubt", CI,
     '        if not grund:\n', '        if False:\n'),
    # ── M6: Untergrenzen ──
    ("python-dotenv wieder 1.0.1", REQ,
     'python-dotenv>=1.2.2   # Sicherheits-Untergrenze',
     'python-dotenv==1.0.1   # Sicherheits-Untergrenze'),
    ("mcp ohne Untergrenze", REQ, 'mcp>=1.28.1,<2\n', 'mcp>=1.5.0,<2\n'),
]

DATEIEN = [SSH, FW, HI, NODE, SJR, DF, BDF, INST, WF, DB, PA, CI, REQ, GOMOD, AGR, GWP, "backend/main.py", "tests/test_bsi_m6_m7.py"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       timeout=600, cwd=str(ROOT), env=env)
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
                print("  BISS %-55s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-55s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-55s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)" % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
