#!/usr/bin/env python3
"""Waechter fuer Befund K3 (ECHT, 2026-09-29): Chat-Verlaeufe und Gedaechtnisse
aller Benutzer waren fuer jeden lokalen Benutzer lesbar.

Gemessen auf ECHT: ``data/chat_history/`` 0755 mit ``<benutzer>.json`` 0644,
27 x ``data/memory_<benutzer>.json`` 0644, dazu ``userchat_history.json``,
``support_history.json``, ``user_sessions.json``, ``issues.json``,
``feedback.json`` 0644. Die Shell-Befehle der Domain-Benutzer laufen als
``jarvis_sandbox`` – ein ``cat`` braucht nur das "o+r".

GEPRUEFT WIRD DIE WIRKUNG, NICHT DAS VORKOMMEN: die echten Funktionen laufen in
einem Sandkasten, danach wird der Dateimodus gemessen. Drei Wege, weil jeder
fuer sich schon einmal der Grund war, dass eine Haertung verpuffte:

1. ``harden_data_dirs`` beim Start (Altbestand, inkl. Muster memory_*.json).
2. Schreibwege mit ``tmp`` + ``replace`` (user_sessions, issues): jede Speicherung
   legt eine NEUE Datei mit der umask an – ein chmod beim Start hielte nur bis
   zum naechsten Flush.
3. Das erste Gedaechtnis eines NEUEN Benutzers (tools/memory.py).

Gegenprobe: dasselbe gegen die ungehaertete Fassung zaehlt die FAILs.
"""
import os
import stat
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(bez, bedingung):
    """check(Beschreibung, Bedingung) – vertauschte Reihenfolge bricht mit Exit 2 ab."""
    global _ok, _fail
    if not isinstance(bez, str) or isinstance(bedingung, str):
        print(f"ABBRUCH: check(Beschreibung, Bedingung) vertauscht: {bez!r}")
        sys.exit(2)
    if bedingung:
        _ok += 1
        print(f"OK   {bez}")
    else:
        _fail += 1
        print(f"FAIL {bez}")


def modus(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def fremd_lesbar(p: Path) -> bool:
    return bool(modus(p) & stat.S_IROTH)


# ── backend.config nur als Stub (der echte Import schreibt die Live-settings.json)
if "backend.config" in sys.modules:
    print("ABBRUCH: backend.config ist bereits geladen.")
    sys.exit(2)
_cfg = types.ModuleType("backend.config")


class _C:
    def get_setting(self, k, d=None):
        return d

    def get(self, k, d=None):
        return d


_cfg.config = _C()
SANDKASTEN = Path(tempfile.mkdtemp(prefix="jarvis_k3_"))
_cfg.PROJECT_ROOT = SANDKASTEN
sys.modules["backend.config"] = _cfg

# Die umask des Dienstes nachbilden: genau sie erzeugt 0644.
os.umask(0o022)

from backend import sandbox as sb                    # noqa: E402

# ── Sandkasten umbiegen; ohne das wuerde die ECHTE data/ angefasst ─────────────
sb.PROJECT_ROOT = SANDKASTEN
if Path(sb.PROJECT_ROOT).resolve() == ROOT.resolve():
    print("ABBRUCH: PROJECT_ROOT zeigt noch auf das Repo.")
    sys.exit(2)

D = SANDKASTEN / "data"
(D / "chat_history").mkdir(parents=True)
(D / "rag").mkdir()
(D / "knowledge").mkdir()
(D / "support_instructions").mkdir()
for p in (D, D / "chat_history", D / "rag", D / "knowledge", D / "support_instructions"):
    p.chmod(0o755)
alt = {
    "chat_history/anna.muster.json": "[]",
    "memory_anna.muster.json": "{}",
    "memory_anna.muster.json.bak": "{}",
    "userchat_history.json": "{}",
    "support_history.json": "{}",
    "user_sessions.json": "{}",
    "issues.json": "[]",
    "feedback.json": "[]",
    # Konversationsprotokoll vor 2026-08-04 und sein Altbestand nach der
    # Migration (auf ECHT am 2026-10-04 gemessen: .migrated 0644).
    "conv_log.json": "[]",
    "conv_log.json.migrated": "[]",
    "telemetry_stats.json": "{}",
    # Handsicherungen mit Zeitstempel (auf DEV am 2026-10-04 gemessen, 0644) –
    # die Namen kennt keine Liste, die Regel "<original>.*" muss sie treffen,
    # auch wenn das Original selbst gar nicht (mehr) da ist.
    "memory_anna.muster.json.bak-20260913-150733": "{}",
    "memory.json.bak-20260913-150733": "{}",
    "security_state.json.bak-20260805-195844": "{}",
    # Strenge Stufe: Sicherung der 2FA-Geheimnisse
    "auth_state.json.bak": "{}",
    # Gegenrichtung: eine Sicherung OHNE privates Original bleibt, wie sie ist
    "oeffentlich.json.bak": "{}",
    "rag/handbuch.txt": "Wissen",
    # Auf ECHT am 2026-10-22 gemessen: Verzeichnis 0755, Dateien 0644, fuer
    # einen fremden Benutzer lesbar – Dateiname ist der Benutzername.
    "support_instructions/anna.muster.md": "Bitte immer auf Deutsch.",
    # Altbestand ohne Schreibweg, ebenfalls 0644 auf ECHT.
    "user_identity.txt": "anna.muster",
}
for rel, inhalt in alt.items():
    f = D / rel
    f.write_text(inhalt, encoding="utf-8")
    f.chmod(0o644)

# ── Positivkontrolle: Ausgangslage ist wirklich die von ECHT ───────────────────
if not all(fremd_lesbar(D / r) for r in alt) or modus(D / "chat_history") != 0o755:
    print("ABBRUCH: Ausgangslage (0644/0755) liess sich nicht herstellen.")
    sys.exit(2)
if not hasattr(sb, "harden_data_dirs"):
    print("ABBRUCH: sandbox.harden_data_dirs fehlt.")
    sys.exit(2)

# ══ 1. Start-Haertung ════════════════════════════════════════════════════════
sb.harden_data_dirs()
check("chat_history/ fuer Fremde nicht mehr begehbar",
      not (modus(D / "chat_history") & (stat.S_IROTH | stat.S_IXOTH)))
# chat_history/<benutzer>.json darf 0644 bleiben – das geschlossene Verzeichnis
# ist die Schranke (wie bei data/chats).
for rel in ("memory_anna.muster.json", "memory_anna.muster.json.bak",
            "userchat_history.json", "support_history.json",
            "user_sessions.json", "issues.json", "feedback.json",
            "conv_log.json", "conv_log.json.migrated", "telemetry_stats.json",
            "memory_anna.muster.json.bak-20260913-150733",
            "memory.json.bak-20260913-150733",
            "security_state.json.bak-20260805-195844"):
    check(f"{rel} nach Start-Haertung nicht fremd lesbar", not fremd_lesbar(D / rel))
check("support_instructions/ fuer Fremde nicht mehr begehbar",
      not (modus(D / "support_instructions") & (stat.S_IROTH | stat.S_IXOTH)))
check("user_identity.txt nach Start-Haertung nicht fremd lesbar",
      not fremd_lesbar(D / "user_identity.txt"))
check("auth_state.json.bak bekommt die STRENGE Stufe des Originals (0600)",
      modus(D / "auth_state.json.bak") == 0o600)
check("oeffentlich.json.bak (kein privates Original) bleibt lesbar",
      fremd_lesbar(D / "oeffentlich.json.bak"))
# Gegenrichtung: was die Shell lesen SOLL, bleibt lesbar.
check("data/ bleibt begehbar (Wissen)", bool(modus(D) & stat.S_IXOTH))
check("data/rag bleibt lesbar", bool(modus(D / "rag") & stat.S_IROTH))
check("data/rag/handbuch.txt bleibt lesbar", fremd_lesbar(D / "rag/handbuch.txt"))
check("data/knowledge bleibt begehbar", bool(modus(D / "knowledge") & stat.S_IXOTH))

# ══ 2. Atomare Schreibwege ═══════════════════════════════════════════════════
from backend import user_sessions as us            # noqa: E402
us.STORE_PATH = D / "user_sessions.json"
us._users.clear()
us._users["anna.muster"] = {"ip": "10.0.0.1"}
us._write_unlocked()
check("user_sessions.json nach Speichern nicht fremd lesbar",
      not fremd_lesbar(D / "user_sessions.json"))

from backend import issues as iss                  # noqa: E402
iss.ISSUES_FILE = D / "issues.json"
iss.ADMIN_SEEN_FILE = D / "issues_admin_seen.json"
iss._save_all([{"id": "1", "text": "Meldung"}])
check("issues.json nach Speichern nicht fremd lesbar", not fremd_lesbar(D / "issues.json"))
iss._save_admin_seen({"admin": "2026-09-29"})
check("issues_admin_seen.json nach Speichern nicht fremd lesbar",
      not fremd_lesbar(D / "issues_admin_seen.json"))

# ══ 3. Neues Gedaechtnis ═════════════════════════════════════════════════════
from backend.tools import memory as mem            # noqa: E402
mem._DATA_DIR = D
mem.MEMORY_FILE = D / "memory.json"
neu = mem._get_memory_path("bert.neu")
if neu.exists() or neu.parent != D:
    print(f"ABBRUCH: Gedaechtnispfad unerwartet: {neu}")
    sys.exit(2)
mem._save_memory_dict({"lieblingsfarbe": "blau"}, "bert.neu")
check("neues memory_<benutzer>.json nicht fremd lesbar",
      neu.exists() and not fremd_lesbar(neu))
mem._save_memory_dict({"lieblingsfarbe": "gruen"}, "bert.neu")
bak = neu.with_suffix(".json.bak")
check("memory_<benutzer>.json.bak nicht fremd lesbar", bak.exists() and not fremd_lesbar(bak))
check("memory_<benutzer>.json nach zweitem Speichern nicht fremd lesbar", not fremd_lesbar(neu))

# ══ 4. Neues chat_history-Verzeichnis (frische Installation) ═════════════════
import shutil                                        # noqa: E402
from backend import chat_history as ch             # noqa: E402
ch._DIR = SANDKASTEN / "frisch" / "chat_history"
ch.append("anna.muster", {"role": "user", "text": "hallo"})
check("frisch angelegtes chat_history/ fuer Fremde nicht begehbar",
      ch._DIR.is_dir() and not (modus(ch._DIR) & (stat.S_IROTH | stat.S_IXOTH)))

# ══ 5. Migration des Konversationsprotokolls NACH der Start-Haertung ═════════
# Die Umbenennung laeuft beim ersten Zugriff auf das Protokoll, also nach
# harden_data_dirs – der Altbestand muss trotzdem sofort privat sein.
from backend import conv_log as cl                 # noqa: E402
MD = SANDKASTEN / "mig" / "data"
MD.mkdir(parents=True)
cl._DATA_DIR = MD
cl._CONV_DIR = MD / "logs" / "conv"
cl._INDEX = cl._CONV_DIR / "index.jsonl"
cl._OLD_FILE = MD / "conv_log.json"
cl._migrated = False
cl._OLD_FILE.write_text('[{"id": "c1", "task": "x", "username": "anna.muster"}]',
                        encoding="utf-8")
cl._OLD_FILE.chmod(0o644)
cl._migrate_once()
mig = MD / "conv_log.json.migrated"
# Positivkontrolle: die Migration ist WIRKLICH gelaufen (sonst waere die
# folgende Pruefung ueber eine fehlende Datei trivial)
if not mig.is_file() or cl._OLD_FILE.exists():
    print("ABBRUCH: Migration im Sandkasten nicht gelaufen.")
    sys.exit(2)
check("conv_log.json.migrated direkt nach der Migration nicht fremd lesbar",
      not fremd_lesbar(mig))

# ══ 6. Telemetrie legt ihre Dateien im Betrieb NEU an ════════════════════════
# Nach dem Loeschen (oder auf einer frischen Installation) entsteht die Datei
# erst beim ersten Speichern – nach der Start-Haertung.
from backend import telemetry as tm                # noqa: E402
TD = SANDKASTEN / "tele" / "data"
tm._STATS_FILE = TD / "telemetry_stats.json"
tm._ERRORS_FILE = TD / "telemetry_errors.json"
if not str(tm._STATS_FILE).startswith(str(SANDKASTEN)):
    print("ABBRUCH: Telemetrie-Pfad nicht im Sandkasten.")
    sys.exit(2)
tr = tm.JarvisTracer()
tr._persist_stats()
tr._persist_error(tm.TraceSpan("probe", kind="tool"))
# Positivkontrolle: beide Dateien sind WIRKLICH neu entstanden
if not (tm._STATS_FILE.is_file() and tm._ERRORS_FILE.is_file()):
    print("ABBRUCH: Telemetrie hat im Sandkasten nichts geschrieben.")
    sys.exit(2)
check("neu angelegtes telemetry_stats.json nicht fremd lesbar",
      not fremd_lesbar(tm._STATS_FILE))
check("neu angelegtes telemetry_errors.json nicht fremd lesbar",
      not fremd_lesbar(tm._ERRORS_FILE))

# ══ 7. Support-Anweisungen: das Verzeichnis entsteht im Betrieb NEU ══════════
# Auf einer frischen Installation legt erst das erste Speichern es an – nach der
# Start-Haertung. Der ECHTE Rumpf aus main.py wird per AST geschnitten und
# ausgefuehrt (main.py laesst sich hier nicht importieren).
import ast                                           # noqa: E402
_quelle = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
_fn = next((n for n in ast.walk(ast.parse(_quelle))
            if isinstance(n, ast.FunctionDef) and n.name == "_support_instr_path"), None)
if _fn is None:
    print("ABBRUCH: _support_instr_path nicht in main.py gefunden.")
    sys.exit(2)
SD = SANDKASTEN / "support" / "backend"
SD.mkdir(parents=True)
_ns = {"Path": Path, "__file__": str(SD / "main.py"),
       "_benutzer": types.SimpleNamespace(pfad_teil=lambda n, f: n or f)}
exec(compile(ast.Module(body=[_fn], type_ignores=[]), "main.py", "exec"), _ns)
_ziel = _ns["_support_instr_path"]("anna.muster")
# Positivkontrolle: der Pfad liegt im Sandkasten und das Verzeichnis entstand
# WIRKLICH durch den Aufruf (sonst waere die Pruefung trivial)
if not str(_ziel).startswith(str(SANDKASTEN)) or not _ziel.parent.is_dir():
    print(f"ABBRUCH: Support-Pfad unerwartet: {_ziel}")
    sys.exit(2)
check("frisch angelegtes support_instructions/ fuer Fremde nicht begehbar",
      not (modus(_ziel.parent) & (stat.S_IROTH | stat.S_IXOTH)))

shutil.rmtree(SANDKASTEN, ignore_errors=True)
print(f"\n{_ok} OK, {_fail} FAIL")
if _ok == 0:
    sys.exit(2)
sys.exit(1 if _fail else 0)
