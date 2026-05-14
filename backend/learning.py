"""Jarvis Learning System – Automatisches Lernen aus Konversationen.

Nach jeder Konversation werden faktische Erkenntnisse aus Tool-Ergebnissen
extrahiert und sofort in der Wissensdatenbank (FAISS) indexiert.

Kern-Prinzip: Lernen bedeutet, etwas NACHHER BESSER ODER RICHTIGER zu machen
als VORHER. Ein gespeicherter Fakt ist nur dann eine Lernerkenntnis, wenn
Jarvis dadurch eine zukuenftige Aufgabe besser oder korrekter erledigen kann.
Ephemere Fakten (aktuelles Datum, momentane Systemzustaende, Einmal-Messwerte)
sind KEIN Lernen und werden explizit ausgefiltert.

Anti-Halluzinations-Schutz:
- Nur Tool-Ergebnisse (role='tool') werden analysiert – keine LLM-Spekulationen.
- LLM-Prompt prueft jeden Fakt am Verbesserungs-Kriterium: "Hilft das in Zukunft?"
- Leere / "NICHTS"-Antworten werden still verworfen.

Architektur:
- learn_from_conversation() wird als asyncio.Task (fire-and-forget) aufgerufen.
- Schreibt Markdown-Datei nach data/knowledge/learned/YYYY-MM/conv_<ts>.md
- Indexiert die Datei sofort in FAISS (kein Warten auf naechsten knowledge_search).
- Fehler sind non-critical und werden nur geloggt.
"""

import asyncio
import logging
import re
import time
from datetime import datetime
from pathlib import Path

_log = logging.getLogger("jarvis.learning")

PROJECT_ROOT = Path(__file__).parent.parent
LEARNED_DIR = PROJECT_ROOT / "data" / "knowledge" / "learned"

# Mindest-Tool-Ergebnisse (kein Lernen bei reinen Gespraechen ohne Tools)
MIN_TOOL_OK_RESULTS = 1

# Max Zeichen pro Tool-Ergebnis im LLM-Kontext (Kosteneffizienz)
MAX_TOOL_RESULT_CHARS = 1000

# Max Tool-Ergebnisse die zum LLM geschickt werden
MAX_TOOL_RESULTS_FOR_LLM = 8

# Tools deren Ergebnisse NICHT als neues Wissen gelten (Retrieval, kein neues Wissen)
SKIP_TOOLS = {
    "knowledge_search",  # Bereits in der DB
    "memory_manage",     # Key-Value-Speicher, kein neues Faktenwissen
    "spawn_agent",       # Meta-Tool
}

# Fehler-Marker in Tool-Ergebnissen
ERROR_MARKERS = ("❌", "fehler:", "error:", "traceback", "exception:", "not found", "failed:")


def _is_error(content: str) -> bool:
    lc = content[:120].lower()
    return any(m in lc for m in ERROR_MARKERS)


def _collect_tool_results(conv_messages: list[dict]) -> list[dict]:
    """Sammelt auswertbare Tool-Ergebnisse aus Konversations-Nachrichten."""
    results = []
    for m in conv_messages:
        if m.get("role") != "tool":
            continue
        tool_name = m.get("tool", "?")
        if tool_name in SKIP_TOOLS:
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if _is_error(content):
            continue
        results.append({
            "tool": tool_name,
            "content": content[:MAX_TOOL_RESULT_CHARS],
        })
        if len(results) >= MAX_TOOL_RESULTS_FOR_LLM:
            break
    return results


def _should_learn(conv_messages: list[dict]) -> bool:
    """Gibt True zurueck wenn die Konversation lernwuerdig ist."""
    ok_results = _collect_tool_results(conv_messages)
    return len(ok_results) >= MIN_TOOL_OK_RESULTS


async def learn_from_conversation(
    task: str,
    conv_messages: list[dict],
    provider,
    model: str,
) -> None:
    """Extrahiert Fakten und speichert sie in FAISS + Wissensdatei.

    Wird als asyncio.Task (fire-and-forget) nach Konversationsende aufgerufen.
    Laeuft im Hintergrund, blockiert NICHT die User-Antwort.
    """
    try:
        tool_results = _collect_tool_results(conv_messages)
        if len(tool_results) < MIN_TOOL_OK_RESULTS:
            _log.debug(f"Lernen uebersprungen: zu wenige nutzbare Tool-Ergebnisse ({len(tool_results)})")
            return

        _log.info(f"Starte Fakten-Extraktion fuer: {task[:80]}")

        # LLM-basierte Fakten-Extraktion
        facts_text = await _extract_facts_llm(task, tool_results, provider, model)
        if not facts_text or facts_text.strip().upper() in ("NICHTS", "KEINE", "NONE", ""):
            _log.debug("Keine lernbaren Fakten extrahiert")
            return

        # Fakten-Datei schreiben + sofort in FAISS indexieren
        await asyncio.to_thread(_save_and_index, task, facts_text)

    except asyncio.CancelledError:
        pass  # Task wurde abgebrochen – kein Problem
    except Exception as e:
        _log.warning(f"Learning fehlgeschlagen (non-critical): {e}")


async def _extract_facts_llm(
    task: str,
    tool_results: list[dict],
    provider,
    model: str,
) -> str:
    """Nutzt das LLM zur Fakten-Extraktion aus Tool-Ergebnissen.

    Gibt extrahierte Fakten als Text oder "" zurueck.
    """
    from google.genai import types

    # Tool-Ergebnisse als lesbaren Block zusammenstellen
    blocks = []
    for r in tool_results:
        blocks.append(f"[{r['tool']}]:\n{r['content']}")
    tool_block = "\n\n".join(blocks)

    task_short = task[:200]

    extraction_prompt = (
        f"Analysiere die folgenden Tool-Ergebnisse aus einer KI-Konversation "
        f"und extrahiere AUSSCHLIESSLICH Erkenntnisse, die Jarvis in ZUKUNFT "
        f"besser oder richtiger machen.\n\n"
        f"KERN-PRUEFUNG fuer jeden Kandidaten-Fakt:\n"
        f"  → 'Wuerde Jarvis dadurch eine kuenftige Aufgabe BESSER oder RICHTIGER erledigen als ohne dieses Wissen?'\n"
        f"  Wenn NEIN: NICHT speichern.\n\n"
        f"STRENG VERBOTEN (kein dauerhafter Mehrwert):\n"
        f"- Aktuelles Datum, aktuelle Uhrzeit oder Zeitstempel jeder Art\n"
        f"- Momentane Systemzustaende die sich staendig aendern (CPU-Last, freier Speicher, laufende Prozesse)\n"
        f"- Einmalige Messwerte oder Zufallsergebnisse ohne Wiederholungspotenzial\n"
        f"- Schlussfolgerungen oder Interpretationen des KI-Assistenten\n"
        f"- Allgemeinwissen das jeder kennt\n"
        f"- Fehlermeldungen (ausser der Loesungsweg ist dauerhaft relevant)\n"
        f"- Informationen die in einer Woche nicht mehr stimmen\n\n"
        f"ERLAUBT (dauerhaft nuetzlich, direkt aus Tool-Ausgaben belegbar):\n"
        f"- Stabile Konfigurationen: IP-Adressen, Ports, Pfade, Dateinamen, Versionsnummern\n"
        f"- Erlernte Vorgehensweisen und Loesungswege die sich wiederholen koennen\n"
        f"- Permanent gueltige Fakten ueber Kunden, Systeme, Produkte\n"
        f"- Fehler-und-Loesung-Paare die kuenftig erneut auftreten koennen\n"
        f"- Inhalte aus gelesenen Dokumenten mit dauerhafter Relevanz\n\n"
        f"Aufgabe war: {task_short}\n\n"
        f"Tool-Ergebnisse:\n{tool_block[:4000]}\n\n"
        f"Gib 2-6 kompakte Stichpunkte aus (je 1-2 Saetze).\n"
        f"Wenn kein einziger Fakt den Zukunfts-Test besteht: antworte mit genau 'NICHTS'.\n"
        f"Format: '- [Stichwort]: Fakt'\n"
        f"Antworte auf Deutsch."
    )

    try:
        resp = await provider.generate_response(
            model=model,
            system_prompt=(
                "Du bist ein strenger Lern-Filter fuer ein KI-System. "
                "Lernen bedeutet: etwas nachher BESSER oder RICHTIGER machen als vorher. "
                "Speichere AUSSCHLIESSLICH Fakten die zukuenftige Aufgaben verbessern. "
                "Ephemere Fakten (Datum, Uhrzeit, momentane Zustaende) sind KEIN Lernen – sofort verwerfen. "
                "Keine Spekulation, keine LLM-Annahmen, nur belegte dauerhafte Erkenntnisse."
            ),
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=extraction_prompt)],
                )
            ],
            tools=[],
        )
        if resp.parts:
            return " ".join(p.text for p in resp.parts if p.text).strip()
    except Exception as e:
        _log.warning(f"Fakten-Extraktion LLM-Aufruf fehlgeschlagen: {e}")

    return ""


def _save_and_index(task: str, facts_text: str) -> None:
    """Schreibt Wissensdatei und indexiert sie sofort in FAISS.

    Laeuft in einem Thread (via asyncio.to_thread).
    """
    # Monatsordner anlegen
    now = datetime.now()
    month_dir = LEARNED_DIR / now.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)

    # Sicherer Dateiname
    ts = int(time.time())
    filepath = month_dir / f"conv_{ts}.md"

    # Task-Kurzname fuer Ueberschrift
    task_clean = re.sub(r'[^\w\s\-]', '', task[:80]).strip()

    content = (
        f"# Gelernt: {task_clean}\n"
        f"Datum: {now.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"{facts_text.strip()}\n"
    )

    filepath.write_text(content, encoding="utf-8")
    _log.info(f"Wissensdatei geschrieben: {filepath.name}")

    # Sofort in FAISS indexieren
    _index_immediately(filepath, content)


def _index_immediately(filepath: Path, content: str) -> None:
    """Indexiert eine neue Wissensdatei direkt in FAISS ohne Bulk-Rebuild."""
    try:
        from backend.tools.knowledge import _get_vector_store, _chunk_text

        vs = _get_vector_store()
        if vs is None:
            _log.debug("VectorStore nicht verfuegbar – FAISS-Indexierung uebersprungen")
            return

        mtime = filepath.stat().st_mtime
        chunks = _chunk_text(content)
        if chunks:
            vs.add_chunks(str(filepath), chunks, mtime)
            _log.info(
                f"FAISS: {len(chunks)} Chunk(s) fuer {filepath.name} sofort indexiert "
                f"(Gesamt: {vs.chunk_count()} Chunks)"
            )
    except Exception as e:
        _log.warning(f"FAISS-Sofort-Indexierung fehlgeschlagen: {e}")


# ─── Statistik-API ────────────────────────────────────────────────────────────

def get_learned_stats() -> dict:
    """Gibt Statistiken ueber gelernte Konversationen zurueck."""
    try:
        if not LEARNED_DIR.exists():
            return {"total_files": 0, "total_size_kb": 0, "months": []}

        files = list(LEARNED_DIR.rglob("conv_*.md"))
        total_size = sum(f.stat().st_size for f in files if f.exists())
        months = sorted({f.parent.name for f in files}, reverse=True)

        return {
            "total_files": len(files),
            "total_size_kb": round(total_size / 1024, 1),
            "months": months[:6],  # Letzte 6 Monate
        }
    except Exception as e:
        _log.warning(f"get_learned_stats fehlgeschlagen: {e}")
        return {"total_files": 0, "total_size_kb": 0, "months": []}
