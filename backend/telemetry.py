"""OpenTelemetry Tracing fuer Jarvis – Agent-Runs, Tool-Ausfuehrungen, LLM-Calls."""

import time
import json
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

_STATS_FILE  = Path(__file__).parent.parent / "data" / "telemetry_stats.json"
_ERRORS_FILE = Path(__file__).parent.parent / "data" / "telemetry_errors.json"
_MAX_ERRORS  = 200

# ─── Leichtgewichtiger Trace-Speicher (kein externer Collector noetig) ───────

class TraceSpan:
    """Einzelner Trace-Span."""

    def __init__(self, name: str, kind: str = "internal", parent_id: str | None = None):
        self.name = name
        self.kind = kind
        self.parent_id = parent_id
        self.span_id = f"{id(self):x}"
        self.start_time = time.time()
        self.end_time: float | None = None
        self.duration_ms: float = 0
        self.attributes: dict[str, Any] = {}
        self.status: str = "ok"
        self.error: str | None = None

    def end(self, status: str = "ok", error: str | None = None):
        self.end_time = time.time()
        self.duration_ms = round((self.end_time - self.start_time) * 1000, 1)
        self.status = status
        self.error = error

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "name": self.name,
            "kind": self.kind,
            "parent_id": self.parent_id,
            "start_time": self.start_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "attributes": self.attributes,
        }


class JarvisTracer:
    """Leichtgewichtiger Tracer – speichert Spans im Memory mit Ring-Buffer."""

    MAX_SPANS = 1000  # Letzte 1000 Spans behalten

    def __init__(self):
        self._lock = threading.Lock()
        self._spans: list[TraceSpan] = []
        self._stats = {
            "agent_runs": 0,
            "tool_calls": 0,
            "llm_calls": 0,
            "errors": 0,
            "total_duration_ms": 0,
            "tool_durations": defaultdict(list),
            "llm_durations": [],
        }
        self._load_stats()

    def start_span(self, name: str, kind: str = "internal", parent_id: str | None = None) -> TraceSpan:
        """Startet einen neuen Span."""
        span = TraceSpan(name, kind, parent_id)
        return span

    def end_span(self, span: TraceSpan, status: str = "ok", error: str | None = None):
        """Beendet einen Span und speichert ihn."""
        span.end(status, error)
        with self._lock:
            self._spans.append(span)
            if len(self._spans) > self.MAX_SPANS:
                self._spans = self._spans[-self.MAX_SPANS:]

            # Statistiken aktualisieren
            if span.kind == "agent":
                self._stats["agent_runs"] += 1
                self._stats["total_duration_ms"] += span.duration_ms
            elif span.kind == "tool":
                self._stats["tool_calls"] += 1
                tool_name = span.attributes.get("tool.name", span.name)
                self._stats["tool_durations"][tool_name].append(span.duration_ms)
                # Nur letzte 100 pro Tool behalten
                if len(self._stats["tool_durations"][tool_name]) > 100:
                    self._stats["tool_durations"][tool_name] = \
                        self._stats["tool_durations"][tool_name][-100:]
            elif span.kind == "llm":
                self._stats["llm_calls"] += 1
                self._stats["llm_durations"].append(span.duration_ms)
                if len(self._stats["llm_durations"]) > 100:
                    self._stats["llm_durations"] = self._stats["llm_durations"][-100:]

            if status == "error":
                self._stats["errors"] += 1
                self._persist_error(span)
            self._persist_stats()

    def get_stats(self) -> dict:
        """Gibt aggregierte Statistiken zurueck."""
        with self._lock:
            tool_stats = {}
            for name, durations in self._stats["tool_durations"].items():
                if durations:
                    tool_stats[name] = {
                        "calls": len(durations),
                        "avg_ms": round(sum(durations) / len(durations), 1),
                        "min_ms": round(min(durations), 1),
                        "max_ms": round(max(durations), 1),
                    }

            llm_durs = self._stats["llm_durations"]
            llm_stats = {}
            if llm_durs:
                llm_stats = {
                    "calls": len(llm_durs),
                    "avg_ms": round(sum(llm_durs) / len(llm_durs), 1),
                    "min_ms": round(min(llm_durs), 1),
                    "max_ms": round(max(llm_durs), 1),
                }

            return {
                "agent_runs": self._stats["agent_runs"],
                "tool_calls": self._stats["tool_calls"],
                "llm_calls": self._stats["llm_calls"],
                "errors": self._stats["errors"],
                "total_duration_ms": round(self._stats["total_duration_ms"], 1),
                "tool_stats": tool_stats,
                "llm_stats": llm_stats,
            }

    def get_recent_spans(self, limit: int = 50) -> list[dict]:
        """Gibt die letzten N Spans zurueck."""
        with self._lock:
            return [s.to_dict() for s in self._spans[-limit:]]

    def get_errors(self, limit: int = 200) -> list[dict]:
        """Gibt persistierte Fehler-Spans zurueck (ueberlebt Neustarts)."""
        try:
            if _ERRORS_FILE.exists():
                data = json.loads(_ERRORS_FILE.read_text())
                return list(reversed(data[-limit:]))
        except Exception:
            pass
        return []

    def _persist_error(self, span: TraceSpan):
        """Haengt einen Fehler-Span an die persistierte Fehler-Liste an (innerhalb Lock)."""
        try:
            _ERRORS_FILE.parent.mkdir(parents=True, exist_ok=True)
            existing = []
            if _ERRORS_FILE.exists():
                existing = json.loads(_ERRORS_FILE.read_text())
            entry = span.to_dict()
            entry["ts"] = span.start_time
            existing.append(entry)
            if len(existing) > _MAX_ERRORS:
                existing = existing[-_MAX_ERRORS:]
            _ERRORS_FILE.write_text(json.dumps(existing))
        except Exception:
            pass

    def _persist_stats(self):
        """Speichert aggregierte Statistiken auf Disk (kein Lock noetig – wird innerhalb Lock aufgerufen)."""
        try:
            data = {
                "agent_runs": self._stats["agent_runs"],
                "tool_calls": self._stats["tool_calls"],
                "llm_calls": self._stats["llm_calls"],
                "errors": self._stats["errors"],
                "total_duration_ms": self._stats["total_duration_ms"],
                "tool_durations": dict(self._stats["tool_durations"]),
                "llm_durations": self._stats["llm_durations"],
            }
            _STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _STATS_FILE.write_text(json.dumps(data))
        except Exception:
            pass

    def _load_stats(self):
        """Laedt gespeicherte Statistiken beim Start."""
        try:
            if _STATS_FILE.exists():
                data = json.loads(_STATS_FILE.read_text())
                self._stats["agent_runs"] = data.get("agent_runs", 0)
                self._stats["tool_calls"] = data.get("tool_calls", 0)
                self._stats["llm_calls"] = data.get("llm_calls", 0)
                self._stats["errors"] = data.get("errors", 0)
                self._stats["total_duration_ms"] = data.get("total_duration_ms", 0)
                self._stats["tool_durations"] = defaultdict(list, data.get("tool_durations", {}))
                self._stats["llm_durations"] = data.get("llm_durations", [])
        except Exception:
            pass

    def clear(self):
        """Loescht alle Spans, Statistiken und persistierte Fehler."""
        with self._lock:
            self._spans.clear()
            self._stats = {
                "agent_runs": 0,
                "tool_calls": 0,
                "llm_calls": 0,
                "errors": 0,
                "total_duration_ms": 0,
                "tool_durations": defaultdict(list),
                "llm_durations": [],
            }
            self._persist_stats()
            try:
                _ERRORS_FILE.write_text("[]")
            except Exception:
                pass


# Singleton
tracer = JarvisTracer()
