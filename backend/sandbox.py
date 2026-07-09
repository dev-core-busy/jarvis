"""Zentrale, LLM-unabhaengige Zugriffskontrolle fuer nicht-privilegierte
(Domain-/LDAP-)Benutzer.

WICHTIG: Diese Pruefungen werden im Tool-Dispatch ERZWUNGEN – nicht im Prompt.
Sie lassen sich daher NICHT per Prompt, Base64-Kodierung oder "gelernten Fakten"
aushebeln. Prompt-Regeln sind nur zusaetzliche Hinweise; massgeblich ist dieser Code.

Modell:
- filesystem-Tool: Schreiben nur in einen Arbeitsbereich (/tmp, data/documents),
  Lesen/Listen nur in einer Allowlist (Wissens-/Arbeitsverzeichnisse). Alles andere
  (Root-, System-, App-interne Pfade, Secrets) ist gesperrt. Symlinks werden
  aufgeloest (kein Escape ueber /tmp/link -> /etc/shadow).
- shell-Tool: zusaetzlich zu den bestehenden Deny-Mustern werden Verschleierung
  (base64/xxd/eval/pipe-in-shell) und Secret-/Root-Pfade gesperrt. Die HARTE
  Garantie liefert die OS-Sandbox (runuser als unprivilegierter User).
"""

import os
import re
import shlex
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _roots(*paths):
    out = []
    for p in paths:
        try:
            out.append(Path(p).resolve())
        except Exception:
            pass
    return out


# Schreib-Arbeitsbereich fuer Domain-Nutzer
WRITE_ROOTS = _roots("/tmp", str(PROJECT_ROOT / "data" / "documents"))
# Lese-Allowlist fuer Domain-Nutzer (alles andere gesperrt -> Root/System dicht)
READ_ROOTS = _roots(
    "/tmp", "/mnt/jarvis-kb",
    str(PROJECT_ROOT / "data" / "knowledge"),
    str(PROJECT_ROOT / "data" / "documents"),
)

_SECRET_NAMES = {
    ".env", "settings.json", "memory.json", "auth_state.json",
    "credentials.json", "id_rsa", "id_ed25519", "id_dsa", ".htpasswd",
    ".netrc", "shadow", "gshadow", "sudoers",
}
_SECRET_SUFFIX = {".key", ".pem", ".crt", ".cer", ".p12", ".pfx", ".jks", ".keystore"}
_SECRET_DIRPARTS = {".ssh", ".git", "certs"}
_SYSTEM_DENY_PREFIX = ("/root", "/boot", "/proc", "/sys")
# App-interne, sensible Pfade unterhalb des Projekts (relativ)
_APP_DENY_REL = (
    ".env", "settings.json", "data/settings.json", "data/memory.json",
    "data/instructions", "data/logs", "data/conv_log.jsonl",
    "data/audit_log.jsonl", "certs",
)


def _resolve(path: str) -> Path:
    # expanduser + absolut + Symlinks aufloesen (strict=False -> kein Fehler bei
    # nicht existierendem Ziel, z.B. neue Datei in /tmp).
    return Path(os.path.expanduser(str(path or ""))).resolve()


def is_sensitive(rp: Path) -> bool:
    """True fuer Secrets/Config/System-Dateien, die Domain-Nutzer nie sehen duerfen."""
    name = rp.name.lower()
    if name in _SECRET_NAMES or name.startswith(".env"):
        return True
    if rp.suffix.lower() in _SECRET_SUFFIX:
        return True
    parts = {p.lower() for p in rp.parts}
    if parts & _SECRET_DIRPARTS:
        return True
    s = str(rp)
    if s == "/root" or s.startswith(_SYSTEM_DENY_PREFIX):
        return True
    if s.startswith("/etc/sudoers"):
        return True
    for rel in _APP_DENY_REL:
        base = str(PROJECT_ROOT / rel)
        if s == base or s.startswith(base + os.sep):
            return True
    return False


def _under(rp: Path, roots) -> bool:
    for r in roots:
        try:
            rp.relative_to(r)
            return True
        except ValueError:
            continue
    return False


def authorize_fs(action: str, path: str) -> tuple[bool, str]:
    """Zugriffsentscheidung fuers filesystem-Tool (nur Domain-Nutzer).
    Rueckgabe (erlaubt, begruendung)."""
    rp = _resolve(path)
    action = (action or "").lower()
    if action in ("write", "append", "mkdir"):
        if is_sensitive(rp):
            return False, "geschützte Datei"
        if not _under(rp, WRITE_ROOTS):
            return False, "Schreiben ist nur im Arbeitsbereich (/tmp oder data/documents) erlaubt"
        return True, ""
    # read / list / exists
    if is_sensitive(rp):
        return False, "geschützte/sensible Datei"
    if not _under(rp, READ_ROOTS):
        return False, ("Lesen ist nur in den Wissens-/Arbeitsverzeichnissen erlaubt – "
                       "System-, Root- und App-interne Bereiche sind gesperrt")
    return True, ""


# ── Shell: Verschleierung + Secret-/Root-Pfade (Domain-Nutzer) ───────────────
SHELL_OBFUSCATION = re.compile(
    r'\bbase64\b[^\n|]*(?:-d|--decode)|\bbase32\b[^\n|]*-d|'
    r'\bxxd\b[^\n]*\s-r|\buudecode\b|\bopenssl\s+enc\b[^\n]*-d|'
    r'\beval\b|\bsource\b|(?:^|\s)\.\s+/|'
    r'\|\s*(?:bash|sh|zsh|dash|python3?|perl|ruby|php|node)\b|'
    r'\b(?:bash|sh|zsh|dash)\s+-c\b',
    re.IGNORECASE,
)
SHELL_SECRET_PATHS = re.compile(
    r'\.env\b|settings\.json\b|memory\.json\b|auth_state\.json\b|credentials\.json\b|'
    r'/root/|(?:^|\s)/root\b|\.ssh/|\bid_rsa\b|\bid_ed25519\b|\bid_dsa\b|\.netrc\b|'
    r'/etc/shadow\b|/etc/gshadow\b|/etc/sudoers|'
    r'\.key\b|\.pem\b|\.crt\b|\.p12\b|\.pfx\b|\.jks\b|'
    r'/certs/|/\.git/',
    re.IGNORECASE,
)


def authorize_shell(cmd: str) -> tuple[bool, str]:
    """Zusatzpruefung fuer shell_execute (nur Domain-Nutzer), ergaenzt die
    bestehenden Deny-Muster in agent.py."""
    cmd = cmd or ""
    if SHELL_OBFUSCATION.search(cmd):
        return False, "verschleierte/dekodierte Ausführung (base64, eval, pipe-in-shell) ist gesperrt"
    if SHELL_SECRET_PATHS.search(cmd):
        return False, "Zugriff auf ein geschütztes Verzeichnis/eine Secret-Datei ist gesperrt"
    return True, ""


def wrap_sandboxed(command: str, sandbox_user: str) -> str:
    """Verpackt einen Befehl so, dass er als unprivilegierter OS-User laeuft
    (harte Grenze via OS-Rechte, unabhaengig von Base64/Python/etc.)."""
    return "runuser -u %s -- /bin/bash -c %s" % (
        shlex.quote(sandbox_user), shlex.quote(command))
