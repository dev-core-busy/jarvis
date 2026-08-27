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
    # data/chats = Chat-Verlaeufe ALLER Benutzer. Stand bisher nur in PRIVATE_DIRS
    # (OS-Rechte 0750), war hier aber nicht als sensibel gefuehrt: `authorize_fs`
    # verweigerte den Zugriff nur mit der Begruendung "nicht im Arbeitsbereich".
    # Seit 2026-08-05 macht das einen Unterschied – die Begruendung entscheidet,
    # ob ein abgewiesener Zugriff als Angriffsindiz zaehlt (fs_target_sensitive).
    "data/chats",
    "data/instructions", "data/logs", "data/conv_log.jsonl",
    "data/audit_log.jsonl", "certs",
    # Zeitgesteuerte Auftraege/Trigger ALLER Benutzer + Sicherheits-Zustand:
    # cron_list zeigt nur eigene Auftraege, ein direktes Lesen der Datei wuerde
    # diese Schranke aushebeln.
    "data/scheduled_jobs.json", "data/file_watchers.json", "data/security_state.json",
    # Lizenz-Zustand: Firma, Abteilung, Ansprechpartner-Mail und die
    # Hardware-Bindung. Geht einen Shell-Befehl in der Sandbox nichts an – und
    # ein beschreibbarer Zustand waere der bequemste Weg, sich selbst eine
    # hoehere Stufe zu geben.
    "data/license.json",
    # Rollen-Definitionen (backend/agent_roles.py): der dort gespeicherte Prompt
    # geht in KUENFTIGE Laeufe – dasselbe Persistenz-Substrat wie
    # data/instructions. Ein beschreibbarer Eintrag waere ein dauerhafter Kanal
    # in den System-Prompt eines Rollen-Agenten.
    "data/agent_roles.json",
    # Prompt-Vorlagen des Jira-Assistenten (backend/jira_vorlagen.py). Gleiche
    # Begruendung wie eine Zeile darueber: der Text geht in den System-Prompt
    # JEDER Zusammenfassung, und die globalen Vorlagen gelten fuer alle
    # Benutzer. Der Inhalt ist harmlos, die Schreibbarkeit nicht.
    "data/jira_vorlagen.json",
    # Verankerte SAP-Serverzertifikate (backend/sap_cert.py). Der INHALT ist
    # oeffentlich – die SCHREIBBARKEIT ist das Problem: wer hier eine eigene CA
    # ablegt, laesst eine SAP-Verbindung gegen einen fremden Server laufen, ohne
    # dass die Zertifikatspruefung anschlaegt.
    "data/sap_certs",
    # Login-Caches (main.py::_load_ad_caches): Gruppen-DNs und die Rechte-Flags
    # kb_editor/internet/**admin** aller kuerzlich angemeldeten Benutzer. Lesen
    # verraet die AD-Struktur; SCHREIBEN waere mit `{"admin": true}` der
    # bequemste Weg zu Administratorrechten – deshalb sensibel, nicht bloss
    # "nicht im Arbeitsbereich".
    "data/ad_cache.json",
    # Standort-Synchronisation (backend/knowledge_sync.py): enthaelt die
    # Freigabe-Token DIESER Instanz und die Token FREMDER Standorte im Klartext.
    # Ein Token ist der vollstaendige Lesezugriff auf einen fremden Wissensordner
    # – so sensibel wie eine Skill-Zugangsdatei. SCHREIBEN waere zusaetzlich der
    # Weg, einen eigenen "Standort" einzutragen und damit beliebige Dateien in
    # einen Wissensordner zu spiegeln.
    "data/knowledge_sync.json",
    # E-Mail-Skill (backend/mail_accounts.py, mail_rules.py). Drei Gruende, jeder
    # allein ausreichend:
    #  - `email_accounts.json` + `.mailkey` sind zusammen das KLARTEXT-Kennwort
    #    jedes hinterlegten Postfachs. Der Schluessel ohne die Datei ist nutzlos
    #    und umgekehrt – also muessen BEIDE zu sein.
    #  - `email_rules.json` enthaelt die Prompts aller Benutzer. SCHREIBEN waere
    #    der Weg, einem fremden Benutzer eine Regel unterzuschieben, die spaeter
    #    unter SEINER Kennung laeuft und aus SEINEM Postfach sendet – dasselbe
    #    Persistenz-Substrat wie data/instructions, nur mit Briefkasten.
    #  - `email_log.jsonl` enthaelt Absender und Betreffzeilen fremder Post.
    "data/email_accounts.json", "data/.mailkey",
    "data/email_rules.json", "data/email_state.json", "data/email_log.jsonl",
    # Persoenliche SAP-Zugaenge (backend/sap_accounts.py): `sap_accounts.json` +
    # `.sapkey` sind zusammen das KLARTEXT-Kennwort jedes hinterlegten
    # SAP-Benutzers – der Schluessel ohne die Datei ist nutzlos und umgekehrt,
    # also muessen BEIDE zu sein. SCHREIBEN waere zusaetzlich der Weg, einem
    # fremden Benutzer einen Zugang auf einen fremden Server unterzuschieben
    # (die Host-Freigabeliste prueft nur der Endpunkt, nicht das Dateisystem).
    "data/sap_accounts.json", "data/.sapkey",
    # Outlook-Add-in (backend/addin_sso.py): ordnet Exchange-Postfaecher den
    # Jarvis-Konten zu und ist damit die Grundlage der kennwortlosen Anmeldung.
    # SCHREIBEN heisst hier: das eigene Postfach auf einen fremden – gern einen
    # administrativen – Benutzer eintragen und sich anschliessend als dieser
    # anmelden. Das ist die direkteste Rechteerhoehung im ganzen Verzeichnis.
    "data/addin_links.json",
    # Short Tracks (backend/short_tracks.py): `short_tracks.json` enthaelt die
    # Prompts ALLER Benutzer samt ihrem Werkzeug-Zuschnitt. SCHREIBEN waere der
    # Weg, sich einen Dump mit dem Bereich `shell` anzulegen (oder einen fremden
    # darauf umzustellen) und ihn beim naechsten Ablegen unter der Kennung des
    # dortigen Benutzers laufen zu lassen – dasselbe Persistenz-Substrat wie
    # data/instructions und email_rules.json. `short_tracks_log.jsonl` enthaelt
    # Dateinamen und Ergebnistexte fremder Laeufe.
    "data/short_tracks.json", "data/short_tracks_log.jsonl",
    # Claude Subagent (backend/claude_subagent.py): bildet Delegations-Schluessel
    # auf BENUTZER ab. Seit 2026-08-23 steht der Schluessel dort im KLARTEXT
    # (er wird dauerhaft angezeigt) – Lesen ist damit gleichbedeutend mit
    # "fremde Vollmacht in der Hand". Schreiben bleibt die zweite Gefahr: ein
    # eigener Eintrag laesst kuenftige Laeufe unter fremder Kennung starten.
    # Deshalb steht die Datei zusaetzlich in PRIVATE_FILES_STRENG (0600).
    "data/claude_subagent.json",
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
                 "data/security_state.json", "data/license.json",
                 "data/agent_roles.json", "data/ad_cache.json",
                 "data/knowledge_sync.json", "data/jira_vorlagen.json",
                 "data/email_accounts.json", "data/email_rules.json",
                 "data/email_state.json", "data/email_log.jsonl",
                 "data/addin_links.json", "data/sap_accounts.json",
                 "data/short_tracks.json", "data/short_tracks_log.jsonl")
PRIVATE_FILE_MODE = 0o640

# Die Schluesseldateien der E-Mail-/SAP-Zugangsdaten sind strenger als 0640: sie
# entschluesseln die Kennwoerter. 0600 heisst, dass nicht einmal die Gruppe
# `jarvis` sie lesen kann – ein zusaetzlicher Riegel, falls jemand einen weiteren
# Dienst in diese Gruppe aufnimmt.
# `claude_subagent.json` gehoert seit 2026-08-23 in dieselbe Stufe: der
# Delegations-Schluessel wird dauerhaft angezeigt und liegt deshalb im Klartext
# darin – wer ihn liest, kann Codeauftraege unter fremder Kennung starten.
PRIVATE_FILES_STRENG = ("data/.mailkey", "data/.sapkey",
                        "data/claude_subagent.json")
PRIVATE_FILE_MODE_STRENG = 0o600


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
    for rel in PRIVATE_FILES_STRENG:
        f = PROJECT_ROOT / rel
        try:
            if not f.is_file():
                continue
            ist = f.stat().st_mode & 0o777
            if ist == PRIVATE_FILE_MODE_STRENG:
                continue
            f.chmod(PRIVATE_FILE_MODE_STRENG)
            geaendert.append(f"{rel}: {oct(ist)} -> {oct(PRIVATE_FILE_MODE_STRENG)}")
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


def authorize_fs(action: str, path: str, username: str | None = None) -> tuple[bool, str]:
    """Zugriffsentscheidung fuers filesystem-Tool (nur Domain-Nutzer).

    ``username`` GEHOERT UEBERGEBEN, wenn der Aufrufer den Akteur kennt. Der
    Rueckfall auf ``tool_user()`` gilt nur fuer Aufrufe aus einem Werkzeug
    heraus, wo der ContextVar nachweislich gesetzt ist.

    WARUM DAS EIN PARAMETER IST UND KEIN UMGEBUNGSZUSTAND (Vorfall 2026-08-24):
    die drei Pfad-Freigaben im Dispatch laufen VOR ``set_tool_user`` – dort war
    ``tool_user()`` also der Vorgabewert ``""``. Folge in BEIDE Richtungen:
    ``gehoert_anhang`` verglich gegen eine leere Kennung und wies damit JEDEN
    Benutzer von seiner EIGENEN Arbeitskopie ab, waehrend ``may_see_document``
    ein leeres ``user`` als "keine Einschraenkung" liest und die
    Eigentuemer-Schranke in ``data/documents`` an dieser Stelle gar nicht
    durchsetzte. Eine harte Schranke darf nicht davon abhaengen, wann sie
    aufgerufen wird.

    Rueckgabe (erlaubt, begruendung)."""
    benutzer = tool_user() if username is None else username
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
    if rp != DOCS_ROOT and _under(rp, [DOCS_ROOT]) and not may_see_document(rp.name, benutzer):
        return False, "diese Datei gehört einem anderen Benutzer"
    # Dieselbe Schranke fuer die Arbeitskopien der Anhaenge. Sie liegen seit
    # 2026-08-23 je Benutzer unter /tmp/jarvis-anhaenge/<kennung>/ – vorher
    # direkt in /tmp, und damit konnte ein Domain-Benutzer den Anhang eines
    # anderen ueber JEDES Backend-Werkzeug oeffnen (office_read,
    # xlsx_read_range, create_chart), sobald er den Namen kannte. Den Namen
    # nannte ihm `filesystem list /tmp`.
    try:
        from backend import lauf_tmp as _lt
        if _lt.gehoert_anhang(rp, benutzer) is False:
            return False, "dieser Anhang gehört einem anderen Benutzer"
        # Dasselbe fuer die Arbeitsverzeichnisse. Der Namespace verbirgt sie nur
        # vor der SHELL; ein Werkzeug im Dienstprozess (filesystem, office_read,
        # xlsx_read_range) koennte die Ergebnisdatei eines FREMDEN Benutzers
        # sonst einfach oeffnen – und ein Verzeichnis-Listing nennt die Namen.
        if _lt.gehoert_arbeitsbereich(rp, benutzer) is False:
            return False, "diese Datei gehört einem anderen Benutzer"
    except Exception:  # noqa: BLE001
        pass
    return True, ""


def fs_target_sensitive(path: str) -> bool:
    """True, wenn der Pfad ein Secret-/System-/App-internes Ziel ist.

    Fuer die Frage, ob ein abgewiesener filesystem-Zugriff ein ANGRIFFSINDIZ ist:
    ``read /opt/jarvis/data/settings.json`` ist eines, ``list /opt/nxis`` (ein Pfad,
    den das Modell geraten hat) nicht. Ohne diese Unterscheidung sperrte eine einzige
    Anfrage wie "suche in allen CSV-Dateien" ein Konto, weil das Modell vier
    Verzeichnisse durchprobierte (nachgewiesen 29.07.2026, ECHT).
    Fail-closed: laesst sich der Pfad nicht aufloesen, gilt er als sensibel."""
    try:
        return is_sensitive(_resolve(path))
    except Exception:  # noqa: BLE001
        return True


# ── Shell: Verschleierung + Secret-/Root-Pfade (Domain-Nutzer) ───────────────
# Zwei Regexes, weil sie unterschiedlich geprueft werden MUESSEN:
#  * SHELL_OBFUSCATION – ueberall im Befehl (auch in Anfuehrungszeichen): eine
#    base64-Nutzlast steckt fast immer in einem Argument.
#  * SHELL_EXEC_WORDS – nur AUSSERHALB von Anfuehrungszeichen: das sind Woerter,
#    die als Befehl gefaehrlich und als Suchbegriff voellig harmlos sind.
#    `grep -r "source" /tmp/doku.txt` galt bis 2026-08-05 als "verschleierte
#    Ausfuehrung" – dieselbe Einstufung wie `curl … | bash`.
SHELL_OBFUSCATION = re.compile(
    r'\bbase64\b[^\n|]*(?:-d|--decode)|\bbase32\b[^\n|]*-d|'
    r'\bxxd\b[^\n]*\s-r|\buudecode\b|\bopenssl\s+enc\b[^\n]*-d|'
    # Pipe-in-Shell, aber NICHT das logische ODER: '||' bestand aus zwei Treffern
    # fuer '\|', deshalb galt `python3 -c "import x" || python3 -c "import y"`
    # (das Standardmuster fuer Faehigkeitspruefungen) als Verschleierung.
    r'(?<!\|)\|(?!\|)\s*(?:bash|sh|zsh|dash|python3?|perl|ruby|php|node)\b',
    re.IGNORECASE,
)
SHELL_EXEC_WORDS = re.compile(
    r'\beval\b|\bsource\b|(?:^|\s)\.\s+/|'
    r'\b(?:bash|sh|zsh|dash)\s+-c\b',
    re.IGNORECASE,
)


def strip_quoted(cmd: str) -> str:
    """Ersetzt Inhalte in Anfuehrungszeichen durch Leerzeichen.

    Damit trifft eine Wort-Regel nur den BEFEHL, nicht einen Suchbegriff oder
    Dateinamen. **Fail-closed:** ist ein Anfuehrungszeichen nicht geschlossen, wird
    der Originaltext zurueckgegeben – dann prueft die Regel wieder alles.
    (Die Umgehung ``ev"a"l`` bleibt moeglich, war es aber vorher genauso: die Regex
    trifft den zerlegten Namen ohnehin nicht. Die harte Grenze ist der OS-Benutzer.)"""
    out, i, n = [], 0, len(cmd or "")
    while i < n:
        ch = cmd[i]
        if ch in "\"'":
            k = cmd.find(ch, i + 1)
            if k == -1:
                return cmd                      # offenes Anfuehrungszeichen -> alles pruefen
            out.append(" ")
            i = k + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)
SHELL_SECRET_PATHS = re.compile(
    r'\.env\b|settings\.json\b|memory\.json\b|auth_state\.json\b|credentials\.json\b|'
    r'scheduled_jobs\.json\b|file_watchers\.json\b|security_state\.json\b|'
    r'license\.json\b|license_root\.pub\b|agent_roles\.json\b|ad_cache\.json\b|'
    r'knowledge_sync\.json\b|'
    # Prompt-Vorlagen des Jira-Assistenten: beschreibbar waere das ein
    # dauerhafter Abschnitt im System-Prompt JEDER Zusammenfassung, fuer alle
    # Benutzer (siehe _APP_DENY_REL).
    r'jira_vorlagen\.json\b|'
    # E-Mail-Skill: Postfach-Kennwoerter (email_accounts.json + .mailkey ergeben
    # zusammen den Klartext), fremde Regel-Prompts, fremde Absender/Betreffe.
    r'email_accounts\.json\b|\.mailkey\b|email_rules\.json\b|'
    r'email_state\.json\b|email_log\.jsonl\b|'
    # Outlook-Add-in: Postfach → Jarvis-Konto. Beschreibbar waere das die
    # kuerzeste Rechteerhoehung im Verzeichnis (siehe _APP_DENY_REL).
    r'addin_links\.json\b|'
    # Persoenliche SAP-Zugaenge: sap_accounts.json + .sapkey ergeben zusammen die
    # Klartext-Kennwoerter der SAP-Benutzer.
    r'sap_accounts\.json\b|\.sapkey\b|'
    # Short Tracks: fremde Dump-Prompts samt Werkzeug-Zuschnitt (beschreibbar
    # waere das ein Dump mit `shell` unter fremder Kennung) und die
    # Ergebnistexte fremder Laeufe.
    r'short_tracks\.json\b|short_tracks_log\.jsonl\b|'
    # Claude Subagent: Delegations-Schluessel -> Benutzer. Ein eigener Eintrag
    # laesst kuenftige Laeufe unter fremder Kennung starten.
    r'claude_subagent\.json\b|'
    # data/chats: fremde Chat-Verlaeufe (in der Shell zusaetzlich per 0750 gesperrt)
    r'data/chats\b|'
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
    if SHELL_OBFUSCATION.search(cmd) or SHELL_EXEC_WORDS.search(strip_quoted(cmd)):
        return False, "verschleierte/dekodierte Ausführung (base64, eval, pipe-in-shell) ist gesperrt"
    if SHELL_SECRET_PATHS.search(cmd):
        return False, "Zugriff auf ein geschütztes Verzeichnis/eine Secret-Datei ist gesperrt"
    return True, ""


def wrap_sandboxed(command: str, sandbox_user: str, lauf_dir=None,
                   ro_binds=(), rw_binds=()) -> str:
    """Verpackt einen Befehl so, dass er als unprivilegierter OS-User laeuft
    (harte Grenze via OS-Rechte, unabhaengig von Base64/Python/etc.).

    Mit ``lauf_dir`` kommt die Mount-Namespace-Isolation dazu: ``/tmp`` ist im
    Lauf dann NUR dieses Verzeichnis (siehe ``backend/lauf_tmp.py``). Der Aufbau
    des Aufrufs liegt bewusst dort und nicht hier – der Broker braucht ihn
    genauso, und zwei Fassungen desselben bwrap-Aufrufs waeren in drei Wochen
    auseinandergelaufen.
    """
    from backend import lauf_tmp as _lt
    return _lt.sandbox_befehl(sandbox_user, command, lauf_dir, ro_binds,
                              rw_binds=rw_binds)
