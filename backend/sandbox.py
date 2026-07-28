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

import contextvars
import os
import re
import shlex
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = (PROJECT_ROOT / "data" / "documents").resolve()

# ── Benutzer des laufenden Werkzeug-Aufrufs ──────────────────────────────────
# Wird im Dispatch (agent.py::_execute_tool) fuer die Dauer EINES Aufrufs
# gesetzt. Werkzeuge, die selbst Dateien aufloesen (filesystem, office), fragen
# darueber die Eigentuemer-Schranke ab, ohne dass der Benutzername durch jede
# Signatur gereicht werden muss. LEER = keine Einschraenkung (privilegierte
# Benutzer, Systemlaeufe) – die Schranke gilt nur fuer Domain-Benutzer, genau
# wie die uebrigen Pruefungen in diesem Modul.
_tool_user: contextvars.ContextVar = contextvars.ContextVar("jarvis_tool_user", default="")


def set_tool_user(username: str):
    """Setzt den Benutzer fuer diesen Werkzeug-Aufruf; Rueckgabe = Reset-Token."""
    return _tool_user.set(username or "")


def reset_tool_user(token) -> None:
    try:
        _tool_user.reset(token)
    except Exception:
        pass


def tool_user() -> str:
    return _tool_user.get()


def may_see_document(name: str, username: str | None = None) -> bool:
    """Darf dieser Benutzer die Datei in data/documents sehen?

    Dieselbe Regel wie am HTTP-Endpunkt (`backend/documents.py::may_access`):
    nur der Ersteller, fail-closed ohne Registry-Eintrag. Bis 2026-07-28 gab es
    diese Schranke nur beim Download – ein `filesystem list data/documents` zeigte
    dagegen JEDEM Domain-Benutzer die Dateinamen aller anderen (auf ECHT u.a.
    Jira-Exporte mit Kundendaten und fremde Angebote).
    """
    user = tool_user() if username is None else username
    if not user:
        return True                      # privilegiert / kein Benutzerbezug
    from backend import documents
    return documents.may_access(name, user, is_admin=False)


def may_list_entry(directory, name: str, username: str | None = None) -> bool:
    """Filter fuer Verzeichnis-Auflistungen; greift NUR in data/documents."""
    user = tool_user() if username is None else username
    if not user:
        return True
    try:
        if _resolve(directory) != DOCS_ROOT:
            return True
    except Exception:
        return True
    return may_see_document(name, user)


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
    # .owners.json bildet Dokument -> Benutzer ab: verraet, WER was erzeugt hat.
    # Datei ist zwar 0600, aber ausdruecklich sperren (und aus Auflistungen halten).
    ".owners.json",
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
    # Zeitgesteuerte Auftraege/Trigger ALLER Benutzer + Sicherheits-Zustand:
    # cron_list zeigt nur eigene Auftraege, ein direktes Lesen der Datei wuerde
    # diese Schranke aushebeln.
    "data/scheduled_jobs.json", "data/file_watchers.json", "data/security_state.json",
)


# ── Dateirechte: fremde OS-Benutzer aussperren ───────────────────────────────
# Die Eigentuemer-Schranke der Werkzeuge (may_see_document) wirkt nur IM Backend.
# Shell-Befehle von Domain-Nutzern laufen ueber den Broker als `jarvis_sandbox`
# (runuser) – ein `cat` dort umgeht jede Policy und braucht nur Leserechte im
# Dateisystem. Mit 0755/0644 war das gegeben: jeder Domain-Nutzer konnte die
# Ergebnisdateien UND die Chat-Verlaeufe aller anderen lesen (nachgewiesen auf DEV
# 2026-07-28). Diese Verzeichnisse gehoeren dem Dienst allein.
#
# WICHTIG – was das NICHT leisten kann: alle Domain-Nutzer teilen EINEN
# Sandbox-Benutzer. OS-Rechte koennen sie deshalb nicht voneinander trennen,
# nur vom Dienst-Verzeichnis. Deswegen bekommt der Agent Anhaenge als
# Arbeitskopie in /tmp (main.py) und nicht ueber data/documents.
#
# data/knowledge bleibt ABSICHTLICH lesbar: die Shell soll Wissensdateien
# verarbeiten koennen (READ_ROOTS erlaubt es ausdruecklich).
PRIVATE_DIRS = ("data/documents", "data/chats", "data/logs")
PRIVATE_MODE = 0o750

# Einzelne Dateien direkt in data/, die kein Domain-Nutzer lesen darf. Das
# Verzeichnis data/ selbst bleibt begehbar (Wissensdateien!), deshalb greift hier
# nur der Dateimodus. Inhalt: zeitgesteuerte Auftraege und Trigger ALLER Benutzer
# (Aufgabentexte, Telefonnummern, Webhook-URLs) sowie der Sicherheits-Zustand
# (wer wie oft auffaellig war). Die Werkzeug-Schranken in cron_tool.py filtern
# fremde Auftraege – ein `cat` in der Sandbox umgeht das und braucht nur
# Leserechte, genau wie 2026-07-28 bei data/chats.
PRIVATE_FILES = ("data/scheduled_jobs.json", "data/file_watchers.json",
                 "data/security_state.json")
PRIVATE_FILE_MODE = 0o640


def harden_data_dirs() -> list[str]:
    """Setzt Dienst-Verzeichnisse auf 0750 und private Dateien auf 0640.
    Idempotent, Rueckgabe = Aenderungen."""
    geaendert = []
    for rel in PRIVATE_DIRS:
        d = PROJECT_ROOT / rel
        try:
            if not d.is_dir():
                continue
            ist = d.stat().st_mode & 0o777
            if ist == PRIVATE_MODE:
                continue
            d.chmod(PRIVATE_MODE)
            geaendert.append(f"{rel}: {oct(ist)} -> {oct(PRIVATE_MODE)}")
        except Exception as e:  # noqa: BLE001
            # Kein harter Fehler: laeuft das Backend nicht als Eigentuemer, bleibt
            # es beim alten Modus – dann muss ein Admin es einmal setzen.
            geaendert.append(f"{rel}: FEHLER {e}")
    for rel in PRIVATE_FILES:
        f = PROJECT_ROOT / rel
        try:
            if not f.is_file():
                continue
            ist = f.stat().st_mode & 0o777
            if ist == PRIVATE_FILE_MODE:
                continue
            f.chmod(PRIVATE_FILE_MODE)
            geaendert.append(f"{rel}: {oct(ist)} -> {oct(PRIVATE_FILE_MODE)}")
        except Exception as e:  # noqa: BLE001
            geaendert.append(f"{rel}: FEHLER {e}")
    return geaendert


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
    # Eigentuemer-Schranke in data/documents: dort liegen die Ergebnis- und
    # Anhangsdateien ALLER Benutzer. Das VERZEICHNIS bleibt auflistbar (der
    # Inhalt wird in filesystem.py gefiltert), einzelne fremde Dateien nicht.
    if rp != DOCS_ROOT and _under(rp, [DOCS_ROOT]) and not may_see_document(rp.name):
        return False, "diese Datei gehört einem anderen Benutzer"
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
    r'scheduled_jobs\.json\b|file_watchers\.json\b|security_state\.json\b|'
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
