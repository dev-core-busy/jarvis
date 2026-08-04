"""OpenTelemetry Tracing fuer Jarvis – Agent-Runs, Tool-Ausfuehrungen, LLM-Calls."""

import time
import json
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

_STATS_FILE  = Path(__file__).parent.parent / "data" / "telemetry_stats.json"
_ERRORS_FILE = Path(__file__).parent.parent / "data" / "telemetry_errors.json"

# KEINE Stueckzahl-Schranke fuer das Fehler-Log (Vorgabe 2026-08-04): was
# entfernt wird, entscheidet ausschliesslich das Alter
# (``prune_errors_older_than()``, Zeitplan in backend/log_retention.py).
# Die frueheren 200 Eintraege hoben die Zusage auf: ein Tag mit einem
# hartnaeckigen Fehler verdraengte die Fehler der Vorwoche – und zwar genau
# dann, wenn man sie zum Vergleich gebraucht haette.
#
# Der Span-Ringpuffer (``JarvisTracer.MAX_SPANS``) bleibt begrenzt und ist kein
# Widerspruch dazu: Spans liegen NUR im Speicher, tragen keinen Zeitstempel auf
# Platte und sind nach einem Neustart weg. Das ist kein aufbewahrtes Log,
# sondern eine Live-Anzeige – dort ist die Grenze eine Speicher-Schranke, keine
# Aufbewahrungsregel. Dasselbe gilt fuer die 100 Dauer-Werte je Tool: das ist
# eine Stichprobe fuer Ø/Min/Max, kein Protokoll.

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
            # WAHRE Gesamtzahl der Aufrufe pro Tool (unbegrenzt). Die Zeit-Statistik
            # (min/avg/max) nutzt weiterhin nur die letzten 100 Dauer-Werte pro Tool
            # (tool_durations) – die "Calls"-Spalte darf davon aber NICHT gedeckelt
            # werden, sonst zeigen alle viel genutzten Tools stumpf "100".
            "tool_call_counts": defaultdict(int),
            "tool_durations": defaultdict(list),
            "llm_durations": [],
        }
        # Reset-Nachweis (wann/von wem zuletzt zurueckgesetzt) – ueberlebt Neustart.
        self._last_reset_ts: float | None = None
        self._last_reset_by: str = ""
        # Nachweis JE BEREICH (tools/llm/errors/spans/all). Ohne diesen wuesste
        # ein Admin nach dem Leeren eines einzelnen Bereichs nicht, ob die "0"
        # bedeutet "noch nichts passiert" oder "gerade geleert" – genau die
        # Frage, fuer die der globale Nachweis eingefuehrt wurde.
        self._area_resets: dict[str, dict] = {}
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
                # Wahre Gesamtzahl: unbegrenzt hochzaehlen (fuer die "Calls"-Spalte).
                self._stats["tool_call_counts"][tool_name] += 1
                # Zeit-Stichprobe: nur die letzten 100 Dauer-Werte pro Tool behalten
                # (fuer min/avg/max – nicht fuer die Aufrufzahl).
                self._stats["tool_durations"][tool_name].append(span.duration_ms)
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
            counts = self._stats["tool_call_counts"]
            for name, durations in self._stats["tool_durations"].items():
                if durations:
                    tool_stats[name] = {
                        # Wahre Gesamtzahl (unbegrenzt); Fallback auf Stichprobengroesse
                        # fuer Alt-Daten ohne tool_call_counts.
                        "calls": counts.get(name, len(durations)),
                        # Anzahl Dauer-Werte, aus denen avg/min/max berechnet sind
                        # (max. 100) – macht die "100"-Deckelung transparent.
                        "sample": len(durations),
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
                "last_reset_ts": self._last_reset_ts,
                "last_reset_by": self._last_reset_by,
                "area_resets": dict(self._area_resets),
                "span_count": len(self._spans),
                "span_capacity": self.MAX_SPANS,
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
            # Keine Deckelung – nur die Zeitfrist entfernt Eintraege.
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
                "tool_call_counts": dict(self._stats["tool_call_counts"]),
                "tool_durations": dict(self._stats["tool_durations"]),
                "llm_durations": self._stats["llm_durations"],
                "last_reset_ts": self._last_reset_ts,
                "last_reset_by": self._last_reset_by,
                "area_resets": self._area_resets,
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
                # Alt-Daten ohne tool_call_counts: mit der Stichprobengroesse
                # vorbelegen (untere Schranke – besser als 0), damit die Zahl
                # ab sofort korrekt weiterwaechst.
                saved_counts = data.get("tool_call_counts")
                if saved_counts is None:
                    saved_counts = {n: len(d) for n, d in self._stats["tool_durations"].items()}
                self._stats["tool_call_counts"] = defaultdict(int, saved_counts)
                self._last_reset_ts = data.get("last_reset_ts")
                self._last_reset_by = data.get("last_reset_by", "")
                ar = data.get("area_resets")
                self._area_resets = dict(ar) if isinstance(ar, dict) else {}
        except Exception:
            pass

    # ─── Leeren: einzeln je Bereich und alles zusammen ────────────────────────
    #
    # Vier Bereiche stehen in der Oberflaeche als eigene Abschnitte und sind
    # deshalb auch EINZELN leerbar. Der Grund ist nicht Bequemlichkeit: wer die
    # Tool-Zeiten nach einer Optimierung frisch messen will, musste vorher den
    # gesamten Reiter zuruecksetzen und verlor dabei das Fehler-Log – also genau
    # die Daten, die man nach einer Aenderung braucht.
    #
    # ACHTUNG bei den Zaehlern: "tools" leert ``tool_calls`` mit, "llm" leert
    # ``llm_calls``. ``agent_runs``/``total_duration_ms``/``errors`` gehoeren zu
    # KEINEM der vier Bereiche und bleiben stehen – sie verschwinden nur beim
    # vollstaendigen Zuruecksetzen. Sonst wuerde das Leeren der Tool-Tabelle
    # stillschweigend auch die Stat-Karten oben veraendern.

    def _note_reset(self, area: str, by: str):
        """Haelt fest, wann/von wem ein Bereich geleert wurde (innerhalb Lock)."""
        self._area_resets[area] = {"ts": time.time(),
                                   "by": (by or "unbekannt")[:80]}

    def clear_tool_stats(self, by: str = "") -> dict:
        """Leert nur die Tool-Statistiken (Aufrufzahlen + Zeit-Stichproben)."""
        with self._lock:
            removed = len(self._stats["tool_durations"])
            self._stats["tool_call_counts"] = defaultdict(int)
            self._stats["tool_durations"] = defaultdict(list)
            self._stats["tool_calls"] = 0
            self._note_reset("tools", by)
            self._persist_stats()
        return {"removed": removed}

    def clear_llm_stats(self, by: str = "") -> dict:
        """Leert nur die LLM-Statistiken (Zeit-Stichprobe + Aufrufzahl)."""
        with self._lock:
            removed = len(self._stats["llm_durations"])
            self._stats["llm_durations"] = []
            self._stats["llm_calls"] = 0
            self._note_reset("llm", by)
            self._persist_stats()
        return {"removed": removed}

    def clear_spans(self, by: str = "") -> dict:
        """Leert den Span-Ringpuffer.

        Spans liegen NUR im Speicher – nach einem Dienst-Neustart sind sie
        ohnehin weg. Der Knopf ist trotzdem sinnvoll: er schafft einen
        definierten Nullpunkt fuer eine Messung, ohne den Dienst anzufassen."""
        with self._lock:
            removed = len(self._spans)
            self._spans.clear()
            self._note_reset("spans", by)
            self._persist_stats()
        return {"removed": removed}

    def clear_errors(self, by: str = "") -> dict:
        """Leert das persistierte Fehler-Log.

        Der Zaehler ``errors`` in den Stat-Karten wird MITGENULLT: eine Karte,
        die "7 Fehler" zeigt, waehrend das Fehler-Log leer ist, sieht wie ein
        Fehler der Oberflaeche aus."""
        with self._lock:
            removed = 0
            try:
                if _ERRORS_FILE.exists():
                    removed = len(json.loads(_ERRORS_FILE.read_text()))
            except Exception:
                pass
            self._stats["errors"] = 0
            self._note_reset("errors", by)
            self._persist_stats()
            try:
                _ERRORS_FILE.parent.mkdir(parents=True, exist_ok=True)
                _ERRORS_FILE.write_text("[]")
            except Exception:
                pass
        return {"removed": removed}

    def prune_errors_older_than(self, cutoff_ts: float) -> int:
        """Entfernt Fehler-Eintraege, die aelter als ``cutoff_ts`` sind.

        Alt-Eintraege ohne ``ts`` (aus der Zeit vor dem Zeitstempel) werden
        BEHALTEN, nicht geraten: ein fehlendes Datum ist kein Beweis fuer Alter.
        Sie lassen sich nur ueber „Fehler-Log leeren" entfernen – eine
        Stueckzahl-Schranke, die sie irgendwann verdraengt, gibt es bewusst
        nicht mehr.
        """
        with self._lock:
            try:
                if not _ERRORS_FILE.exists():
                    return 0
                data = json.loads(_ERRORS_FILE.read_text())
                if not isinstance(data, list):
                    return 0
                keep = [e for e in data
                        if e.get("ts") is None or e.get("ts", 0) >= cutoff_ts]
                removed = len(data) - len(keep)
                if removed:
                    _ERRORS_FILE.write_text(json.dumps(keep))
                return removed
            except Exception:
                return 0

    def clear(self, by: str = ""):
        """Loescht alle Spans, Statistiken und persistierte Fehler.

        by: Benutzer, der den Reset ausgeloest hat – wird als Reset-Nachweis
        (wann/von wem) fuer die naechste Anzeige festgehalten."""
        with self._lock:
            self._spans.clear()
            self._stats = {
                "agent_runs": 0,
                "tool_calls": 0,
                "llm_calls": 0,
                "errors": 0,
                "total_duration_ms": 0,
                "tool_call_counts": defaultdict(int),
                "tool_durations": defaultdict(list),
                "llm_durations": [],
            }
            self._last_reset_ts = time.time()
            self._last_reset_by = (by or "unbekannt")[:80]
            # Die Bereichs-Nachweise werden verworfen: nach einem vollstaendigen
            # Zuruecksetzen ist der globale Nachweis die richtige Auskunft, ein
            # aelterer Bereichs-Hinweis daneben waere irrefuehrend.
            self._area_resets = {}
            self._persist_stats()
            try:
                _ERRORS_FILE.write_text("[]")
            except Exception:
                pass


# Singleton
tracer = JarvisTracer()
