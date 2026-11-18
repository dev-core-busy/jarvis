"""Memory Tool – Persistenter Speicher für Fakten und Präferenzen."""

import json
import os

from backend import atomar as _atomar  # atomar + fail-closed (Code-Review 2026-10-18)
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.benutzer import norm_user, pfad_teil
from backend.sandbox import privat_machen
from backend.tools.base import BaseTool

# Memory-Verzeichnis
_DATA_DIR = Path(__file__).parent.parent.parent / "data"

# Legacy-Datei (Rückwärtskompatibilität)
MEMORY_FILE = _DATA_DIR / "memory.json"

# Gedaechtnisse je Benutzer liegen in einem EIGENEN Ordner (Pentest "Hardening"
# F-14, 2026-11-18). Vorher lagen sie als data/memory_<vorname.nachname>.json
# direkt in data/ – das muss fuer die Wissensordner begehbar bleiben (0755),
# also konnte jedes lokale Konto die Namen auflisten: auf ECHT gemessen 79
# Dateien, 45 Klarnamen, sichtbar fuer das Administrationskonto, nobody und jarvis_sandbox. Die
# Inhalte waren 0640 und blieben zu – die Dateinamen selbst SIND die
# Benutzerliste. Ein 0750-Ordner verbirgt sie vor jedem Konto ausserhalb der
# Dienstgruppe. Bewusst NICHT data/memory: das ist der Notizordner des Skills
# agent_autonomy_kit (Vorgabe memory_dir).
GEDAECHTNIS_NAME = "gedaechtnis"
GEDAECHTNIS_MODUS = 0o750


def gedaechtnis_dir() -> Path:
    """Ordner der Gedaechtnisse je Benutzer. Eine FUNKTION, keine Konstante:
    Tests lenken ``_DATA_DIR`` in einen Sandkasten um – ein beim Import
    berechneter Pfad zeigte dann weiter auf das echte data/."""
    return _DATA_DIR / GEDAECHTNIS_NAME

# Thread-Lock fuer parallelen Zugriff (Sub-Agents laufen in Threads)
_lock = threading.Lock()
_umzug_lock = threading.Lock()

# In-Memory Caches pro Benutzer
_cache: dict | None = None          # Legacy-Alias (zeigt auf "jarvis"-Cache)
_user_caches: dict[str, dict | None] = {}


def _get_memory_path(username: str = "") -> Path:
    """Gibt den Memory-Dateipfad für einen Benutzer zurück.

    Leerer Username / 'jarvis' → Rückwärtskompatibel: data/memory.json
    Andere User → data/gedaechtnis/memory_{pfad_teil}.json (F-14, siehe oben;
    der Altbestand direkt in data/ wird per ``umziehen()`` verschoben).

    ⚠ DER NAME WIRD NORMALISIERT (Fix 2026-09-07). Vorher stand hier ein
    ``re.sub`` auf dem ROHEN Namen: ``firma\\k.schmidt`` ergab
    ``memory_firma_k_schmidt.json`` und ``k.schmidt`` daneben
    ``memory_k_schmidt.json`` – ZWEI Gedaechtnisse fuer einen Menschen,
    und welches er bekam, hing daran, wie er sich angemeldet hat. Die
    Zusammenfuehrung des Altbestands macht ``benutzer_migration``.
    """
    if not username or norm_user(username) == "jarvis":
        return MEMORY_FILE
    return gedaechtnis_dir() / f"memory_{pfad_teil(username)}.json"


def _ordner_bereit() -> Path:
    """Legt ``data/gedaechtnis`` mit 0750 an bzw. zieht den Modus nach.

    ``mkdir(mode=...)`` haengt an der umask, deshalb danach ausdruecklich
    ``chmod``. Laeuft der Aufrufer als root (Wartungsskript, Probe), bekommt
    der Ordner den Eigentuemer von ``data/`` – ein root-eigener Ordner liesse
    den Dienst danach kein Gedaechtnis mehr schreiben.
    """
    d = gedaechtnis_dir()
    if not d.is_dir():
        d.mkdir(mode=GEDAECHTNIS_MODUS, exist_ok=True)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            st = _DATA_DIR.stat()
            os.chown(d, st.st_uid, st.st_gid)
    if (d.stat().st_mode & 0o777) != GEDAECHTNIS_MODUS:
        try:
            os.chmod(d, GEDAECHTNIS_MODUS)
        except OSError:
            pass                  # fremder Eigentuemer: harden_data_dirs meldet es
    return d


def umziehen() -> dict:
    """Verschiebt den Altbestand ``data/memory_*`` nach ``data/gedaechtnis/``.

    Idempotent, gedacht fuer den Dienststart (vor ``benutzer_migration`` und vor
    dem ersten Laden). Erfasst Original, ``.bak`` und Handsicherungen
    (``.bak-<zeit>``) – sie tragen dieselben Daten und denselben Namen.
    ``data/memory.json`` (Gedaechtnis des Dienstes, kein Benutzername) bleibt.

    Liegt am Ziel schon eine Datei gleichen Namens: bei gleichem Inhalt wird
    die Altkopie entfernt, sonst als ``<name>.vor-umzug-<zeit>`` IM Ordner
    abgelegt – das Ziel gewinnt (es hat der neue Code geschrieben), verloren
    geht nichts. Rueckgabe zaehlt nur; die Dateinamen gehoeren nicht ins
    Journal, sie sind genau das, was F-14 verbergen soll.
    """
    erg = {"verschoben": 0, "doppelt": 0, "konflikt": 0, "fehler": []}
    alte = sorted(p for p in _DATA_DIR.glob("memory_*")
                  if p.is_file() and not p.is_symlink())
    if not alte:
        return erg
    ziel_dir = _ordner_bereit()
    marke = datetime.now().strftime("%Y%m%d-%H%M%S")
    # EIGENE Sperre, nicht _lock: der Rueckweg in _load_memory_dict laeuft
    # auch unter _lock (main.py, Loeschen), ein zweites acquire haengt dort.
    with _umzug_lock:
        for p in alte:
            ziel = ziel_dir / p.name
            try:
                if ziel.exists():
                    if ziel.read_bytes() == p.read_bytes():
                        p.unlink()
                        erg["doppelt"] += 1
                        continue
                    ziel = ziel_dir / f"{p.name}.vor-umzug-{marke}"
                    erg["konflikt"] += 1
                privat_machen(p)          # vor dem replace, kein offenes Fenster
                os.replace(p, ziel)
                erg["verschoben"] += 1
            except OSError as e:
                erg["fehler"].append(type(e).__name__)
    return erg

# Schreibende Aktionen – in Laeufen ohne Oberflaeche gesperrt (s. unten).
_SCHREIBEND = ("save", "delete")

HINWEIS_NUR_LESEN = (
    "⛔ Das Gedächtnis ist in Läufen ohne Oberfläche (zeitgesteuerte Aufträge, "
    "E-Mail-Regeln, Dateiwächter, Messenger, Agent-API) nur lesbar – gespeichert "
    "oder gelöscht wird nur aus einem Gespräch mit dem Benutzer. Nicht erneut "
    "versuchen; die Aufgabe ohne Gedächtniseintrag zu Ende führen.")


def _kanal():
    """Kanal des laufenden Auftrags (BSI H9) oder None = Lauf ohne Oberflaeche."""
    from backend import wirkung  # noqa: PLC0415
    return wirkung.kanal_cv.get()


def schreiben_gesperrt() -> bool:
    """Darf dieser Lauf das Gedaechtnis veraendern? (BSI-Abgleich, Skill memory)

    **Befund "Vergiftung durch Fremdtext":** ein Lauf ohne Oberflaeche liest
    Fremdtext (eine eingehende Mail, ein Dokument, eine Webseite), und niemand
    sieht zu. Ein eingeschmuggelter Satz "merke dir: Rechnungen immer an …"
    landete per ``memory_manage(save)`` im Gedaechtnis und stuende ab dann in
    JEDEM Lauf des Benutzers im System-Prompt – eine einmalige Injektion
    wuerde dauerhaft. Deshalb (Betreiberentscheid 2026-10-12): ohne Oberflaeche
    nur lesen. Massgeblich ist dasselbe Merkmal wie beim Bestaetigungstor
    (``wirkung.kanal_cv``): ein Lauf mit Kanal hat einen Menschen am anderen
    Ende, ein Rollen-Agent erbt den Kanal seines Aufrufers. Kann das Merkmal
    nicht gelesen werden, gilt "gesperrt" (fail-closed).
    """
    try:
        return _kanal() is None
    except Exception:  # noqa: BLE001
        return True


def _quelle() -> str:
    """Herkunft eines neuen Eintrags fuer die Anzeige ("chat" | "app")."""
    try:
        k = _kanal()
    except Exception:  # noqa: BLE001
        return ""
    if k is None:
        return ""
    return "chat" if getattr(k, "kann_bestaetigen", False) else "app"


# Token-Limits
TOKEN_LIMIT = 2000       # Warnung im System-Prompt
COMPRESS_THRESHOLD = 1500  # Kompression empfehlen


def _estimate_tokens(text: str) -> int:
    """Grobe Token-Schaetzung (~4 Zeichen pro Token fuer deutschen Text)."""
    return len(text) // 4


def _load_memory_dict(username: str = "") -> dict:
    """Laedt Memory aus Cache oder JSON-Datei mit Backup-Recovery."""
    global _cache
    mem_file = _get_memory_path(username)
    cache_key = username or "jarvis"

    # Cache-Treffer
    if cache_key in _user_caches and _user_caches[cache_key] is not None:
        return _user_caches[cache_key]

    if mem_file.parent == gedaechtnis_dir():
        # Netz fuer einen Umzug, der beim Start nicht gelaufen ist (Fehler,
        # Prozess ausserhalb des Dienstes): sonst saehe der Benutzer ein leeres
        # Gedaechtnis, und das naechste save spaltete es in zwei Dateien.
        if not mem_file.exists() and (_DATA_DIR / mem_file.name).exists():
            umziehen()
        _ordner_bereit()
    else:
        mem_file.parent.mkdir(parents=True, exist_ok=True)
    if mem_file.exists():
        try:
            data = json.loads(mem_file.read_text(encoding="utf-8"))
            _user_caches[cache_key] = data
            if cache_key == "jarvis":
                _cache = data  # Legacy-Alias
            return data
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[MEMORY] WARNUNG: {mem_file.name} korrupt ({e}), versuche Backup...", flush=True)
            bak = mem_file.with_suffix(".json.bak")
            if bak.exists():
                try:
                    data = json.loads(bak.read_text(encoding="utf-8"))
                    print(f"[MEMORY] Backup geladen ({len(data)} Eintraege)", flush=True)
                    _atomar.schreiben(mem_file, data, sicherung=False)  # atomar (Code-Review 2026-10-18)
                    privat_machen(mem_file)
                    _user_caches[cache_key] = data
                    if cache_key == "jarvis":
                        _cache = data
                    return data
                except Exception:
                    pass
            print(f"[MEMORY] Kein nutzbares Backup für {cache_key}, starte mit leerem Memory", flush=True)
    _user_caches[cache_key] = {}
    if cache_key == "jarvis":
        _cache = {}
    return _user_caches[cache_key]


def _save_memory_dict(memory: dict, username: str = ""):
    """Speichert Memory mit Backup der vorherigen Version und aktualisiert Cache."""
    global _cache
    mem_file = _get_memory_path(username)
    cache_key = username or "jarvis"
    if mem_file.parent == gedaechtnis_dir():
        _ordner_bereit()
    else:
        mem_file.parent.mkdir(parents=True, exist_ok=True)
    if mem_file.exists():
        shutil.copy2(mem_file, mem_file.with_suffix(".json.bak"))
        privat_machen(mem_file.with_suffix(".json.bak"))
    # atomar (Code-Review 2026-10-18); die .bak legt copy2 oben schon an
    _atomar.schreiben(mem_file, memory, sicherung=False)
    # Ein NEUER Benutzer bekommt die Datei hier zum ersten Mal – mit der umask des
    # Dienstes waere sie 0644 und bis zum naechsten Neustart fuer die Sandbox
    # lesbar (ECHT 2026-09-29: 27 Gedaechtnisse so). Siehe sandbox.PRIVATE_FILE_GLOBS.
    privat_machen(mem_file)
    _user_caches[cache_key] = memory
    if cache_key == "jarvis":
        _cache = memory


class MemoryTool(BaseTool):
    """Speichert und ruft persistente Informationen ab (Fakten, Präferenzen, Notizen)."""

    @property
    def name(self) -> str:
        return "memory_manage"

    @property
    def description(self) -> str:
        return (
            "Verwaltet den persistenten Speicher (Memory) von Jarvis. "
            "Nutze dieses Tool, um wichtige Informationen dauerhaft zu speichern, "
            "abzurufen oder zu löschen. Beispiele: Benutzerpräferenzen, Projektnamen, "
            "IP-Adressen, häufig benutzte Befehle, Notizen. "
            "Memory überlebt Neustarts und steht in allen zukünftigen Gesprächen zur Verfügung. "
            "Bei zu grossem Memory: action='compress' um alte wissen_-Eintraege zusammenzufassen."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Aktion: 'save' (Key-Value speichern), 'get' (einzelnen Key abrufen), 'list' (ALLE Eintraege auflisten – nutze dies um alles ueber den User zu erfahren), 'delete' (Key loeschen), 'search' (nach Begriff suchen), 'compress' (alte wissen_-Eintraege zusammenfassen).",
                    "enum": ["save", "get", "list", "delete", "search", "compress"]
                },
                "key": {
                    "type": "string",
                    "description": "Schlüssel des Memory-Eintrags (z.B. 'user_name', 'server_ip'). Benötigt bei save, get, delete."
                },
                "value": {
                    "type": "string",
                    "description": "Wert zum Speichern. Nur bei action='save' benötigt."
                },
                "query": {
                    "type": "string",
                    "description": "Suchbegriff. Nur bei action='search' benötigt."
                }
            },
            "required": ["action"]
        }

    async def execute(self, **kwargs) -> str:
        with _lock:
            return self._execute_inner(**kwargs)

    def _execute_inner(self, **kwargs) -> str:
        action = str(kwargs.get("action", "")).strip().strip('"\'\\')
        key = kwargs.get("key", "")
        value = kwargs.get("value", "")
        query = kwargs.get("query", "")
        username = str(kwargs.get("_username", "") or "")

        if action in _SCHREIBEND and schreiben_gesperrt():
            print(f"[Memory] {action} abgewiesen: Lauf ohne Oberflaeche "
                  f"(Benutzer {username or 'jarvis'})", flush=True)
            return HINWEIS_NUR_LESEN

        memory = _load_memory_dict(username)

        if action == "save":
            if not key or not value:
                return "❌ 'key' und 'value' sind für 'save' erforderlich."
            # Validierung
            if len(key) > 100:
                return "❌ Key zu lang (max 100 Zeichen)."
            if len(str(value)) > 5000:
                return "❌ Value zu lang (max 5000 Zeichen)."
            if not re.match(r'^[a-zA-Z0-9_.\-äöüÄÖÜß ]+$', str(key)):
                return "❌ Key enthält ungueltige Zeichen. Erlaubt: Buchstaben, Zahlen, _ . - Leerzeichen"
            memory[key] = {
                "value": str(value),
                "updated": datetime.now().isoformat(),
                "quelle": _quelle(),
            }
            _save_memory_dict(memory, username)
            count = len(memory)
            tokens = _estimate_tokens(json.dumps(memory, ensure_ascii=False))
            hint = f" (Memory: {count} Eintraege, ~{tokens} Tokens)" if tokens > COMPRESS_THRESHOLD else ""
            return f"💾 Gespeichert: {key} = {value}{hint}"

        elif action == "get":
            if not key:
                return "❌ 'key' ist für 'get' erforderlich."
            if key in memory:
                entry = memory[key]
                return f"📌 {key} = {entry['value']}  (Stand: {entry.get('updated', '?')})"
            return f"❓ Kein Eintrag für '{key}' gefunden."

        elif action in ("list", "load_all", "get_all"):
            if not memory:
                return "📭 Memory ist leer."
            tokens = _estimate_tokens(json.dumps(memory, ensure_ascii=False))
            output = f"📋 Memory ({len(memory)} Einträge, ~{tokens} Tokens):\n"
            for k, v in sorted(memory.items()):
                output += f"  • {k}: {v['value']}\n"
            if tokens > COMPRESS_THRESHOLD:
                output += f"\n⚠️ Memory ist gross (~{tokens} Tokens). Nutze action='compress' zum Zusammenfassen."
            return output

        elif action == "delete":
            if not key:
                return "❌ 'key' ist für 'delete' erforderlich."
            if key in memory:
                del memory[key]
                _save_memory_dict(memory, username)
                return f"🗑️ Gelöscht: {key}"
            return f"❓ Kein Eintrag '{key}' zum Löschen gefunden."

        elif action == "search":
            if not query:
                return "❌ 'query' ist für 'search' erforderlich."
            q = query.lower()
            results = []
            for k, v in memory.items():
                if q in k.lower() or q in v["value"].lower():
                    results.append(f"  • {k}: {v['value']}")
            if results:
                return f"🔍 {len(results)} Treffer für '{query}':\n" + "\n".join(results)
            return f"🔍 Keine Treffer für '{query}'."

        elif action == "compress":
            wissen = {k: v for k, v in memory.items() if k.startswith("wissen_")}
            if len(wissen) < 5:
                return f"📊 Nur {len(wissen)} wissen_-Eintraege vorhanden – Kompression nicht noetig (min. 5)."
            tokens = _estimate_tokens(json.dumps(wissen, ensure_ascii=False))
            if tokens < COMPRESS_THRESHOLD:
                return f"📊 wissen_-Eintraege haben ~{tokens} Tokens – unter Schwellwert ({COMPRESS_THRESHOLD}), Kompression nicht noetig."

            entries_text = "\n".join(f"- {k}: {v['value']}" for k, v in sorted(wissen.items()))
            return (
                f"📊 {len(wissen)} wissen_-Eintraege mit ~{tokens} geschaetzten Tokens gefunden.\n\n"
                f"Bitte fasse folgende Eintraege zusammen und speichere sie als weniger, "
                f"konsolidierte wissen_-Eintraege via memory_manage(action='save'). "
                f"Loesche danach die alten Keys via memory_manage(action='delete').\n\n"
                f"Aktuelle Eintraege:\n{entries_text}"
            )

        return f"❌ Unbekannte Aktion: {action}. Erlaubt: save, get, list, delete, search, compress."


def load_memory_context(username: str = "") -> str:
    """Lädt alle Memory-Einträge als Kontext-String für den System-Prompt.

    Wird beim Start jeder Konversation automatisch injiziert.
    """
    memory = _load_memory_dict(username)
    if not memory:
        return ""

    # Wissens-Cache und normale Einträge trennen
    wissen = []
    fakten = []
    for key, entry in sorted(memory.items()):
        val = entry.get("value", "") if isinstance(entry, dict) else str(entry)
        if key.startswith("wissen_"):
            wissen.append(f"- {key[7:]}: {val}")
        else:
            fakten.append(f"- {key}: {val}")

    lines = []
    if wissen:
        lines.append("Gelerntes Wissen (direkt nutzen, NICHT erneut nachschlagen):")
        lines.extend(wissen)
    if fakten:
        if lines:
            lines.append("")
        lines.append("Gespeicherte Fakten:")
        lines.extend(fakten)

    context = "\n".join(lines)

    # Token-Check
    tokens = _estimate_tokens(context)
    if tokens > TOKEN_LIMIT:
        context += (
            f"\n\n⚠️ WARNUNG: Memory ist sehr gross (~{tokens} Tokens). "
            f"Nutze memory_manage(action='compress') um alte wissen_-Eintraege zusammenzufassen!"
        )

    return context


def load_selective_memory(task_text: str = "", username: str = "") -> str:
    """Laedt Memory selektiv: Strategien/Tipps immer, Rest nur wenn relevant.

    Bei kleinem Memory (<50 Eintraege) wird alles geladen.
    Bei grossem Memory werden nur relevante Eintraege + Strategien geladen.
    """
    memory = _load_memory_dict(username)
    if not memory:
        return ""

    # Bei kleinem Memory: alles laden (alter Weg)
    if len(memory) < 50:
        return load_memory_context(username)

    # Bei grossem Memory: selektiv laden
    task_lower = task_text.lower() if task_text else ""
    task_words = set(re.split(r'\W+', task_lower)) - {'', 'der', 'die', 'das', 'und', 'oder',
        'in', 'von', 'zu', 'mit', 'auf', 'fuer', 'ist', 'ein', 'eine', 'den', 'dem',
        'the', 'a', 'an', 'and', 'or', 'in', 'of', 'to', 'for', 'is', 'was', 'wie',
        'was', 'ich', 'du', 'wir', 'mir', 'mich', 'bitte', 'kannst', 'mache', 'zeige'}

    # Immer laden: Strategien, Tool-Tipps, Fehler-Wissen, Praeferenzen
    always_prefixes = ('strategie_', 'tool_tipp_', 'fehler_', 'praeferenz_')

    strategien = []
    relevante = []
    rest_count = 0

    for key, entry in sorted(memory.items()):
        val = entry.get("value", "") if isinstance(entry, dict) else str(entry)
        key_lower = key.lower()
        val_lower = val.lower()

        # Strategien und Tool-Tipps immer laden
        if any(key_lower.startswith(p) for p in always_prefixes):
            prefix_label = key.split('_', 1)[0]
            strategien.append(f"- [{prefix_label}] {key}: {val}")
            continue

        # Relevanz pruefen: Ueberlappung zwischen Task-Woertern und Key/Value
        combined = key_lower + " " + val_lower
        matches = sum(1 for w in task_words if len(w) > 2 and w in combined)
        if matches > 0:
            relevante.append((matches, f"- {key}: {val}"))
        else:
            rest_count += 1

    # Sortiere relevante nach Anzahl Matches (absteigend)
    relevante.sort(key=lambda x: -x[0])

    lines = []
    if strategien:
        lines.append("Gelernte Strategien & Tipps (ZUERST pruefen, bevor du loslegst):")
        lines.extend(strategien)
    if relevante:
        if lines:
            lines.append("")
        lines.append("Relevanter Memory-Kontext:")
        lines.extend(entry for _, entry in relevante[:20])  # Max 20 relevante
    if rest_count > 0:
        lines.append(f"\n({rest_count} weitere Memory-Eintraege verfuegbar – nutze memory_manage(action='search') bei Bedarf)")

    # Wissen immer mit laden (kompakt)
    wissen = []
    for key, entry in sorted(memory.items()):
        if key.startswith("wissen_"):
            val = entry.get("value", "") if isinstance(entry, dict) else str(entry)
            wissen.append(f"- {key[7:]}: {val}")
    if wissen:
        if lines:
            lines.append("")
        lines.append("Gelerntes Wissen:")
        lines.extend(wissen)

    context = "\n".join(lines)
    tokens = _estimate_tokens(context)
    if tokens > TOKEN_LIMIT:
        context += f"\n\n⚠️ Memory gross (~{tokens} Tokens) – memory_manage(action='compress') empfohlen."

    return context
