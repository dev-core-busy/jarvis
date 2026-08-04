"""Jarvis Audit-Log – strukturiertes JSONL-Logging aller Tasks und Tool-Ausführungen."""

import json
import threading
import time
from pathlib import Path

AUDIT_FILE = Path("data/logs/audit.jsonl")
_lock = threading.Lock()


def _bak() -> Path:
    """Pfad der alten Rotations-Sicherung.

    Bewusst eine FUNKTION: als Modulkonstante waere der Wert beim Import an den
    damaligen ``AUDIT_FILE`` gebunden. Tests biegen ``AUDIT_FILE`` auf ein
    Wegwerf-Verzeichnis um – eine fixierte Konstante zeigte dann weiter auf die
    echte Datei unter ``data/logs/``.
    """
    return AUDIT_FILE.with_suffix(".jsonl.bak")

# KEINE Groessen-Rotation mehr (Vorgabe 2026-08-04): was entfernt wird,
# entscheidet ausschliesslich das Alter (``prune_older_than()``, Zeitplan in
# backend/log_retention.py).
#
# Warum die Rotation weg ist: bei 10 MB wurde die Datei nach ``.jsonl.bak``
# umbenannt – und ``read_log()`` las nur die AKTIVE Datei. Die Eintraege waren
# damit aus der Oberflaeche verschwunden, ohne geloescht zu sein. Genau das ist
# eine Stueckzahl-Schranke in Verkleidung: sie entscheidet ueber Sichtbarkeit
# nach Datenmenge statt nach Alter.
#
# Die Datei kann dadurch gross werden. Deshalb liest ``read_log()`` sie
# blockweise VON HINTEN und bricht ab, sobald ``limit`` Treffer da sind – die
# Antwortzeit haengt am Limit, nicht an der Dateigroesse.
_TAIL_CHUNK = 256 * 1024


def _ensure_dir():
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)


def log_task(user: str, task: str, client_type: str = "", client_ip: str = ""):
    """Loggt den Start einer Benutzer-Anfrage (auch ohne Tool-Aufruf)."""
    entry = {
        "ts": int(time.time()),
        "user": user or "unknown",
        "tool": "[task]",
        "args": {
            "task": task[:200] + ("…" if len(task) > 200 else ""),
            **({"client_type": client_type} if client_type else {}),
            **({"client_ip": client_ip} if client_ip else {}),
        },
        "result_len": None,
        "duration_ms": None,
    }
    _write(entry)


def log_tool(user: str, tool: str, args: dict, result_len: int, duration_ms: int):
    """Loggt einen Tool-Aufruf als JSONL-Zeile."""
    entry = {
        "ts": int(time.time()),
        "user": user or "unknown",
        "tool": tool,
        "args": {k: v for k, v in args.items() if not k.startswith("_")},  # interne Args ausblenden
        "result_len": result_len,
        "duration_ms": duration_ms,
    }
    _write(entry)


def _write(entry: dict):
    """Haengt einen Eintrag an die Log-Datei an.

    Keine Rotation nach Groesse (siehe oben) – nur Anhaengen. Damit kostet das
    Schreiben unabhaengig von der Historie immer gleich viel.
    """
    line = json.dumps(entry, ensure_ascii=False)
    with _lock:
        _ensure_dir()
        with AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def prune_older_than(cutoff_ts: float) -> int:
    """Entfernt Audit-Zeilen, die aelter als ``cutoff_ts`` sind (Anzahl zurueck).

    Betrifft die aktive Datei UND die Rotations-Sicherung ``.jsonl.bak``: die
    entstand bei 10 MB, war fuer die Oberflaeche danach unsichtbar und wurde
    von nichts je wieder angefasst – ein Log, das man nicht sieht und nicht
    loeschen kann, ist genau das Gegenteil von belastbar.

    Zeilen OHNE ``ts`` bleiben stehen (fehlendes Datum ist kein Altersbeweis);
    beschaedigte Zeilen werden verworfen – sie sind nicht auswertbar und ein
    Aufraeumlauf ist die Gelegenheit, sie loszuwerden.

    Neu geschrieben wird atomar ueber eine Nebendatei: ein Absturz mitten im
    Schreiben darf kein halbes Audit-Log hinterlassen.
    """
    removed = 0
    with _lock:
        for path in (AUDIT_FILE, _bak()):
            try:
                if not path.exists():
                    continue
                keep: list[str] = []
                dropped = 0
                for line in path.read_text(encoding="utf-8",
                                           errors="replace").splitlines():
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:  # noqa: BLE001
                        dropped += 1
                        continue
                    ts = entry.get("ts")
                    if ts is not None and ts < cutoff_ts:
                        dropped += 1
                        continue
                    keep.append(line)
                if not dropped:
                    continue
                if keep:
                    tmp = path.with_suffix(path.suffix + ".tmp")
                    tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
                    tmp.replace(path)
                elif path == AUDIT_FILE:
                    path.write_text("", encoding="utf-8")
                else:
                    # Leere Sicherung braucht niemand – ganz weg damit.
                    path.unlink(missing_ok=True)
                removed += dropped
            except Exception as e:  # noqa: BLE001
                print(f"[audit_log] Aufraeumen von {path.name} fehlgeschlagen: {e}",
                      flush=True)
    return removed


def stats() -> dict:
    """Umfang des Audit-Logs (Zeilen, Zeitspanne, Bytes) fuer die Anzeige.

    Bewusst OHNE die Datei vollstaendig zu parsen: Zeilen werden binaer
    gezaehlt, ausgewertet werden nur die **erste** und die **letzte** Zeile
    (aeltester/neuester Zeitpunkt). Ohne Groessen-Rotation kann die Datei lang
    werden, und dieser Wert haengt am Telemetrie-Reiter – er darf nicht mit der
    Historie langsamer werden.
    """
    out = {"lines": 0, "bytes": 0, "oldest_ts": None, "newest_ts": None}
    with _lock:
        for path in (AUDIT_FILE, _bak()):
            try:
                if not path.exists():
                    continue
                out["bytes"] += path.stat().st_size
                with path.open("rb") as f:
                    while True:
                        blk = f.read(1024 * 1024)
                        if not blk:
                            break
                        out["lines"] += blk.count(b"\n")
                    # Neuester Eintrag: letzte verwertbare Zeile von hinten
                    for line in _iter_reversed(path):
                        try:
                            ts = json.loads(line).get("ts")
                        except Exception:  # noqa: BLE001
                            continue
                        if ts is None:
                            continue
                        if out["newest_ts"] is None or ts > out["newest_ts"]:
                            out["newest_ts"] = ts
                        break
                    # Aeltester Eintrag: erste verwertbare Zeile vom Anfang
                    f.seek(0)
                    head = f.read(64 * 1024)
                for line in head.split(b"\n"):
                    if not line.strip():
                        continue
                    try:
                        ts = json.loads(line.decode("utf-8", "replace")).get("ts")
                    except Exception:  # noqa: BLE001
                        continue
                    if ts is None:
                        continue
                    if out["oldest_ts"] is None or ts < out["oldest_ts"]:
                        out["oldest_ts"] = ts
                    break
            except Exception:  # noqa: BLE001
                pass
    return out


def _iter_reversed(path: Path, chunk: int = _TAIL_CHUNK):
    """Liefert die Zeilen einer Datei von der LETZTEN zur ersten.

    Liest blockweise von hinten. FALLSTRICK: der erste Teil eines rueckwaerts
    gelesenen Blocks ist in der Regel eine angeschnittene Zeile – sie wird
    zurueckgehalten und erst mit dem naechsten Block zusammengesetzt.
    """
    try:
        if not path.exists():
            return
        with path.open("rb") as f:
            f.seek(0, 2)
            pos = f.tell()
            tail = b""
            while pos > 0:
                step = min(chunk, pos)
                pos -= step
                f.seek(pos)
                buf = f.read(step) + tail
                parts = buf.split(b"\n")
                tail = parts[0]
                for raw in reversed(parts[1:]):
                    if raw.strip():
                        yield raw.decode("utf-8", "replace")
            if tail.strip():
                yield tail.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return


def read_log(limit: int = 500, user_filter: str = "", tool_filter: str = "") -> list[dict]:
    """Liest die letzten N Audit-Log-Einträge (neueste zuerst).

    Liest von hinten und bricht ab, sobald ``limit`` Treffer da sind – ohne
    Groessen-Rotation kann die Datei lang werden, die Antwortzeit soll aber am
    Limit haengen. Reichen die Treffer nicht, wird die alte Rotations-Sicherung
    ``.jsonl.bak`` mitgelesen: die Eintraege darin sind vorhanden und nur durch
    die frühere Rotation aus der Anzeige gefallen.
    """
    _ensure_dir()
    entries: list[dict] = []
    with _lock:
        for path in (AUDIT_FILE, _bak()):
            for line in _iter_reversed(path):
                try:
                    entry = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if user_filter and user_filter.lower() not in (entry.get("user") or "").lower():
                    continue
                if tool_filter and tool_filter.lower() not in (entry.get("tool") or "").lower():
                    continue
                entries.append(entry)
                if len(entries) >= limit:
                    return entries
    return entries
