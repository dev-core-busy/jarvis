"""Gegenproben zu test_standard_zugang: beisst der Waechter, wenn der Fix fehlt?"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
TEST = W / "tests" / "test_standard_zugang.py"

PROBEN = [
    ("'jarvis' gilt nicht mehr als Standard", "backend/standard_zugang.py",
     '    "jarvis",\n', ""),
    ("Docker nimmt JARVIS_PASSWORD=jarvis wieder an", "backend/standard_zugang.py",
     "    if not ist_standardkennwort(env_wert):\n        return env_wert.strip()\n",
     "    if env_wert:\n        return env_wert.strip()\n"),
    ("Erstkennwort-Datei ohne 0600", "backend/standard_zugang.py",
     "        os.chmod(str(datei), 0o600)\n", "        pass\n"),
    ("Login erzwingt den Wechsel nicht mehr", "backend/main.py",
     '        _set_user_auth_state(username, {"must_change_password": True})\n    user_state',
     '        pass\n    user_state'),
    ("Docker-Kennwort wieder fest 'jarvis'", "backend/main.py",
     '    _standard_zugang.docker_erstkennwort(\n        os.getenv("JARVIS_PASSWORD", ""),\n'
     '        Path(__file__).parent.parent / "data" / ".erstkennwort")\n    if _DOCKER_MODE else "")\n',
     '    os.getenv("JARVIS_PASSWORD", "jarvis"))\n'),
    ("install.sh: Pruefung erkennt 'jarvis' nicht", "docs/install.sh",
     'exit((crypt("jarvis", $h) // "") eq $h ? 0 : 1);', 'exit 1;'),
    ("install.sh: leeres Kennwort gilt als individuell", "docs/install.sh",
     '        exit 0 if $h eq "";\n', ''),
    ("install.sh: neuer Benutzer wieder jarvis:jarvis", "docs/install.sh",
     "    $SUDO useradd -m -s /bin/bash jarvis >/dev/null 2>&1\n    _erstkennwort_setzen\n",
     '    $SUDO useradd -m -s /bin/bash jarvis >/dev/null 2>&1\n    echo "jarvis:jarvis" | $SUDO chpasswd\n'),
    ("Docker: x11vnc wieder auf 0.0.0.0", "docker/entrypoint.sh",
     "    -nopw \\\n    -localhost \\\n", "    -nopw \\\n    -listen 0.0.0.0 \\\n"),
    ("Docker: websockify wieder auf allen Adressen", "docker/entrypoint.sh",
     '        "127.0.0.1:$NOVNC_PORT" \\\n', '        "$NOVNC_PORT" \\\n'),
    ("run.sh: websockify wieder auf allen Adressen", "run.sh",
     '/usr/bin/websockify --web="$NOVNC_DIR" "127.0.0.1:$WEBSOCKIFY_PORT"',
     '/usr/bin/websockify --web="$NOVNC_DIR" "$WEBSOCKIFY_PORT"'),
    ("Compose veroeffentlicht 6080 wieder", "docker-compose.yml",
     '      - "443:443"     # Web-UI (HTTPS)\n',
     '      - "443:443"     # Web-UI (HTTPS)\n      - "6080:6080"   # noVNC\n'),
    ("Dockerfile EXPOSE 6080 wieder", "Dockerfile", "EXPOSE 80 443\n", "EXPOSE 80 443 6080\n"),
    ("Landingpage nennt wieder jarvis / jarvis", "docs/index.html",
     '<span class="t-de">Login: <strong style="color:var(--text-secondary)">jarvis</strong> / Erstkennwort aus der Abschlussmeldung</span>',
     '<span class="t-de">Login: <strong style="color:var(--text-secondary)">jarvis / jarvis</strong></span>'),
    ("Compose-Vorgabe wieder :-jarvis", "docs/docker-compose.yml",
     '"${JARVIS_PASSWORD:-}"', '"${JARVIS_PASSWORD:-jarvis}"'),
    ("Sandbox: .secret_key nicht mehr 0600", "backend/sandbox.py",
     '                        "data/.secret_key", "data/auth_state.json",\n',
     '                        "data/auth_state.json",\n'),
    ("Sandbox: Shell-Sperre fuer .secret_key fehlt", "backend/sandbox.py",
     "    r'\\.secret_key\\b|\\.erstkennwort\\b|'\n", ""),
    ("Sandbox: Dateiwerkzeug sieht .erstkennwort nicht als sensibel", "backend/sandbox.py",
     '    ".secret_key", ".erstkennwort",\n', '    ".secret_key",\n'),
    ("SSH: Drop-in erlaubt Kennwort weiter", "docs/install.sh",
     "'    PasswordAuthentication no'", "'    PasswordAuthentication yes'"),
    ("SSH: Match fehlt -> gilt fuer ALLE Benutzer", "docs/install.sh",
     "'Match User jarvis' ", ""),
    ("SSH: Bestandskonto ohne Schluessel wird trotzdem umgestellt", "docs/install.sh",
     'if [[ "${JARVIS_NEU_ANGELEGT:-0}" == 1 ]] || $SUDO test -s ~jarvis/.ssh/authorized_keys; then\n',
     'if true; then\n'),
]
DATEIEN = sorted({p[1] for p in PROBEN})
ORIG = {f: (W / f).read_bytes() for f in DATEIEN}


def zurueck():
    for f, b in ORIG.items():
        (W / f).write_bytes(b)


def lauf():
    r = subprocess.run([sys.executable, str(TEST)], capture_output=True, text=True, timeout=300)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, bool(m), int(m.group(2)) if m else -1


rc, b, f = lauf()
if rc or not b or f:
    print(f"ABBRUCH: Basis nicht gruen (rc={rc} bilanz={b} fails={f})")
    sys.exit(2)
print("Basis gruen.\n")

gut = 0
try:
    for name, rel, a, n in PROBEN:
        zurueck()
        s = (W / rel).read_text(encoding="utf-8")
        if s.count(a) != 1:
            print(f"  ⚠ VERFEHLT  {name} (Anker {s.count(a)}x)")
            continue
        (W / rel).write_text(s.replace(a, n, 1), encoding="utf-8")
        rc, b, f = lauf()
        zurueck()
        ok = rc != 0 and b and f > 0
        gut += ok
        print(f"  {'OK     ' if ok else 'ZAHNLOS'}  {name}: {f} FAIL" + ("" if b else " (OHNE BILANZ!)"))
finally:
    zurueck()
    for fn, bts in ORIG.items():
        if hashlib.md5((W / fn).read_bytes()).digest() != hashlib.md5(bts).digest():
            print(f"  ⚠ RUECKSTAND in {fn}")
print(f"\n{gut} von {len(PROBEN)} beissen einzeln.")
sys.exit(0 if gut == len(PROBEN) else 1)
