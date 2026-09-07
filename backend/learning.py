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
- Schreibt Markdown-Datei nach data/knowledge/learned/YYYY-MM/conv_<ts>_<kennung>.md
  (die Kennung ist der Hash der Aufgabe – daran erkennt der naechste Lauf,
   dass dieselbe Aufgabe schon gelernt wurde, siehe `bereits_gelernt`)
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


# Sicherheits-/Rechte-bezogene "Fakten" werden NIEMALS gelernt – sonst koennte ein
# Angreifer per Prompt-Injection dauerhaft eine Rechte-Anhebung "beibringen"
# (z.B. "root-Verzeichnis ist erlaubt"). Solche Zeilen werden vor dem Speichern verworfen.
_LEARN_DENY = re.compile(
    r'(?:\broot\b|\bsudo\b|privileg|berechtigt|uneingeschr|ohne\s+einschr|keine\s+einschr|'
    r'vollzugriff|full\s+access|\bbypass\b|jailbreak|overrid|ignorier|'
    r'passwor|\bsecret\b|api[-_ ]?key|\btoken\b|\.env|settings\.json|id_rsa|chmod|/etc/|base64|'
    r'darf\s+alles|keine\s+regeln)',
    re.IGNORECASE,
)


# ── Hat die Extraktion ueberhaupt Wissen geliefert? ───────────────────────
# ⚠ AN ECHTEN DATEN GEMESSEN (DEV, 2026-09-06): von 71 Lernnotizen hatten
# **53** als kompletten Inhalt das Wort "Standardantwort" - 75 % Muell, jede
# davon im FAISS-Index und damit in jeder kuenftigen Suche. Sie entstehen bei
# Auftraegen ohne Wissensgehalt ("Erzeuge ein Bild von einem Hund"): das Modell
# liefert eine Floskel, und die wurde ungeprueft geschrieben.
#
# Der bisherige Filter war eine WORTLISTE ("NICHTS","KEINE","NONE") - genau die
# Grundlage, die an dem Tag unvollstaendig ist, an dem ein Modell eine neue
# Floskel erfindet. Geprueft wird deshalb die EIGENSCHAFT:
#   - Laenge: gemessen 15 Zeichen (Muell) gegen >=170 (echtes Wissen). Die
#     Schwelle liegt mit grossem Abstand dazwischen.
#   - Struktur: echte Fakten folgen dem Format "- [Kategorie]: Text", das der
#     Extraktions-Prompt verlangt. Eine Floskel hat es nie.
# Beide Kriterien zusammen, weil jedes allein zu schwach waere: ein langer
# Fliesstext ohne Struktur kann Wissen sein, eine kurze Zeile MIT Struktur auch.
MIN_FAKTEN_ZEICHEN = 80


def _hat_substanz(facts_text: str) -> bool:
    """Ist das Wissen - oder eine Floskel? (True = speichern)"""
    t = (facts_text or "").strip()
    if len(t) < MIN_FAKTEN_ZEICHEN:
        return False
    # Mindestens eine Zeile im geforderten Format "- [Kategorie]: Inhalt".
    for zeile in t.splitlines():
        z = zeile.strip()
        if z.startswith("-") and "[" in z and "]" in z and ":" in z.split("]", 1)[1]:
            return True
    return False


# ── Wissen ueber JARVIS SELBST ist kein Wissen ueber die Welt ─────────────
# ⚠ AN ECHTEN DATEN GEMESSEN (DEV, 2026-09-07): von 108 Faktenzeilen des
# gesamten Bestands (Archiv + laufender Monat + Konsolidat) reden **22** ueber
# Jarvis selbst - eigene Installationspfade und eigene Werkzeugnamen. Der Satz
# "Die Standardvorlage liegt unter /opt/jarvis/data/vorlagen/standard.pptx"
# steht SECHSMAL im Bestand, jedes Mal anders formuliert.
#
# Das ist aus drei Gruenden wertlos bis schaedlich:
#   1. Es steht bereits im System-Prompt bzw. in der Werkzeug-Beschreibung und
#      geht damit ohnehin bei JEDER Anfrage mit - gelernt ist es doppelt.
#   2. Es ist teilweise FALSCH: gemessen wurde "office_create_powerpoint
#      erwartet fuer layout ausschliesslich abschnitt oder bild" - das ist ein
#      Ausschnitt der Alias-Liste, nicht die Liste.
#   3. Es fuellt den FAISS-Index und verdraengt bei jeder Wissenssuche echte
#      Kundendokumentation (LEARNED_PENALTY daempft, entfernt aber nicht).
#
# DIE REGEL WIRD ABGELEITET, NICHT GEPFLEGT: die Pfade kommen aus PROJECT_ROOT
# (also aus der eigenen Installation), die Werkzeugnamen aus den Werkzeugen,
# die in GENAU DIESEM Lauf gearbeitet haben. Eine gepflegte Namensliste waere
# an dem Tag unvollstaendig, an dem jemand einen Skill hinzufuegt.
#
# ⚠ DIE REGEL IST BEWUSST ENG. Gemessen kostet eine breitere Fassung (bare
# `/tmp`, `backend/`, `tests/`) vier weitere Zeilen - und wuerde jeden
# Kundenfakt treffen, in dem zufaellig `/tmp` vorkommt ("der Medistar-Import
# legt seine Logs unter /tmp/medistar ab"). Dieselbe Falle wie die verworfene
# Vokal-Regel im OneNote-Import: drei Muellzeilen gegen still verlorenes
# Wissen ist ein schlechter Handel.

def _eigene_pfade() -> list[str]:
    """Installationspfade dieser Jarvis-Instanz (aus PROJECT_ROOT abgeleitet)."""
    pfade = {str(PROJECT_ROOT)}
    # Der Dienstbenutzer heisst wie das Projekt; sein Home taucht in
    # Shell-Ergebnissen genauso auf wie der Installationspfad.
    pfade.add(f"/home/{PROJECT_ROOT.name}")
    pfade.add(f"{PROJECT_ROOT.name}_sandbox")
    return [p for p in pfade if len(p) >= 6]


def _redet_ueber_sich_selbst(zeile: str, werkzeuge: set[str]) -> bool:
    """Beschreibt die Zeile Jarvis SELBST statt der Welt des Nutzers?"""
    lc = zeile.lower()
    for p in _eigene_pfade():
        if p.lower() in lc:
            return True
    for w in werkzeuge:
        # Wortgrenze: `delegate` darf nicht in "delegated" treffen.
        if w and re.search(rf"\b{re.escape(w.lower())}\b", lc):
            return True
    return False


def _ohne_selbstbezug(facts_text: str, werkzeuge: set[str]) -> str:
    """Entfernt Zeilen, die ueber Jarvis selbst reden."""
    if not werkzeuge and not _eigene_pfade():
        return facts_text
    kept = []
    for line in (facts_text or "").splitlines():
        if line.strip() and _redet_ueber_sich_selbst(line, werkzeuge):
            _log.info("Lern-Filter: Selbstauskunft verworfen (steht schon im "
                      "System-Prompt): %s", line.strip()[:100])
            continue
        kept.append(line)
    return "\n".join(kept).strip()


# ── Dieselbe Aufgabe wird nicht zweimal gelernt ───────────────────────────
# ⚠ DER GEMELDETE FEHLER (DEV, 2026-09-07): unter "gelerntes Wissen" stand
# NEUNMAL dieselbe Zeile "Gelernt: Erstelle eine PowerPoint-Praesentation mit
# 6 Folien ueber die Vorteile...". Gemessen: neun Notizen in SECHS MINUTEN
# (04.09., 07:38-07:44), alle aus demselben, wiederholt gefahrenen Auftrag.
#
# ⚠ ZWEI INHALTSBASIERTE ANSAETZE WURDEN GEMESSEN UND VERWORFEN - das ist der
# Grund, warum hier die AUFGABE und nicht der INHALT verglichen wird:
#   - lexikalisch (Wortueberdeckung der Faktenzeilen): erkannte 7 von 51
#     Zeilen, uebersprang **0** Dateien. Das Modell formuliert jedes Mal neu.
#   - semantisch (e5-Embeddings, dasselbe Modell wie der Vektor-Store):
#     Dubletten-Paare median 0.857, fremde Paare median 0.823 - die
#     Verteilungen ueberlappen, e5 komprimiert Cosine auf ein schmales Band.
# Die Aufgabe dagegen ist ueber alle neun Laeufe BYTE-GLEICH.
#
# Gemessen ueber 684 echte Konversationen auf DEV: 68 % aller Laeufe
# wiederholen eine schon gesehene Aufgabe ("mal mir ein bild" 99x,
# "testfrage" 80x). Jeder dieser Laeufe kostete bisher einen LLM-Aufruf zur
# Fakten-Extraktion UND eine weitere Datei im Index.
#
# KEIN INDEXFILE: die Kennung steht im DATEINAMEN. Damit ist der Bestand auf
# Platte die einzige Wahrheit - wer eine Notiz loescht, laesst die Aufgabe von
# selbst wieder lernbar werden. Ein Index daneben wuerde driften und im
# Zweifel Wissen dauerhaft blockieren.

_WIEDERHOL_FENSTER_VORGABE = 14


def wiederhol_fenster_tage() -> int:
    """Wie lange gilt eine Aufgabe als 'schon gelernt'? (0 = Dedup aus)

    FUNKTION, keine Modulkonstante - ein beim Import gelesener Wert waere bis
    zum Dienstneustart eingefroren.
    """
    import os
    try:
        v = int(os.environ.get("JARVIS_LERN_FENSTER_TAGE", _WIEDERHOL_FENSTER_VORGABE))
    except (TypeError, ValueError):
        return _WIEDERHOL_FENSTER_VORGABE
    return max(0, min(v, 365))


def _norm_task(task: str) -> str:
    """Vergleichsform der Aufgabe (die Extraktion sieht ohnehin nur 200 Zeichen)."""
    return re.sub(r"\s+", " ", (task or "")).strip().lower()[:200]


def task_kennung(task: str) -> str:
    """Kurzer, stabiler Schluessel der Aufgabe - steht im Dateinamen."""
    import hashlib
    return hashlib.sha1(_norm_task(task).encode("utf-8")).hexdigest()[:10]


def bereits_gelernt(task: str) -> Path | None:
    """Gibt die vorhandene Notiz zurueck, wenn diese Aufgabe schon gelernt wurde.

    FAIL-SAFE IN DIE LERNENDE RICHTUNG: jeder Fehler gibt None zurueck, es wird
    also gelernt. Ein fehlgeschlagener Vergleich kostet eine Dublette, ein
    faelschlich angenommenes "kenne ich schon" kostet Wissen.
    """
    fenster = wiederhol_fenster_tage()
    if fenster <= 0:
        return None
    kennung = task_kennung(task)
    if not _norm_task(task):
        return None
    grenze = time.time() - fenster * 86400
    try:
        for p in LEARNED_DIR.rglob(f"conv_*_{kennung}.md"):
            # Das Konsolidat traegt keine Aufgaben-Kennung und kann hier nicht
            # treffen; der Vollstaendigkeit halber bleibt es trotzdem aussen vor.
            if p.parent.name == "konsolidiert":
                continue
            if p.stat().st_mtime >= grenze:
                return p
    except Exception as e:  # noqa: BLE001 - Lernen darf daran nicht scheitern
        _log.debug(f"Dedup-Pruefung fehlgeschlagen (es wird gelernt): {e}")
    return None


def _sanitize_learned(facts_text: str) -> str:
    """Entfernt sicherheits-/rechte-bezogene Zeilen aus den zu lernenden Fakten."""
    kept = []
    for line in (facts_text or "").splitlines():
        if line.strip() and _LEARN_DENY.search(line):
            _log.info(f"Lern-Filter: sicherheitsrelevante Zeile verworfen: {line.strip()[:100]}")
            continue
        kept.append(line)
    return "\n".join(kept).strip()


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

        # ⚠ DIE PRUEFUNG STEHT VOR DER EXTRAKTION, nicht danach: sie spart den
        # LLM-Aufruf. Gemessen betrifft das 68 % aller Laeufe.
        schon = bereits_gelernt(task)
        if schon is not None:
            _log.info("Auto-Learning uebersprungen: diese Aufgabe wurde bereits "
                      "gelernt (%s, Fenster %d Tage) - %.60s",
                      schon.name, wiederhol_fenster_tage(), task)
            return

        _log.info(f"Starte Fakten-Extraktion fuer: {task[:80]}")

        # LLM-basierte Fakten-Extraktion
        facts_text = await _extract_facts_llm(task, tool_results, provider, model)
        if not facts_text or facts_text.strip().upper() in ("NICHTS", "KEINE", "NONE", ""):
            _log.debug("Keine lernbaren Fakten extrahiert")
            return

        # Sicherheits-Filter: rechte-/secret-bezogene "Fakten" niemals lernen
        facts_text = _sanitize_learned(facts_text)
        # Selbstauskunft verwerfen (eigene Pfade / eigene Werkzeuge). Die
        # Werkzeugnamen kommen aus DIESEM Lauf - keine gepflegte Liste.
        facts_text = _ohne_selbstbezug(
            facts_text,
            {(m.get("tool") or "").strip() for m in conv_messages if m.get("role") == "tool"},
        )
        # ⚠ SUBSTANZ-PRUEFUNG NACH dem Saeubern: erst danach steht fest, was
        # wirklich uebrig bleibt. Ohne sie landeten 75 % Floskeln im Index.
        if facts_text and not _hat_substanz(facts_text):
            _log.info("Auto-Learning: kein verwertbares Wissen (%d Zeichen, "
                      "keine Fakten-Struktur) - nicht gespeichert: %r",
                      len(facts_text.strip()), facts_text.strip()[:60])
            return
        if not facts_text:
            _log.info("Lernen uebersprungen: nur sicherheitsrelevante/gefilterte Inhalte")
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
        f"- Informationen die in einer Woche nicht mehr stimmen\n"
        f"- Angaben ueber DICH SELBST: eigene Installationspfade, Namen und Parameter "
        f"deiner eigenen Werkzeuge, eigene Vorlagen- und Verzeichnisorte, eigene "
        f"Sicherheits- und Sandbox-Regeln. Das steht bereits in deinem System-Prompt "
        f"und in den Werkzeug-Beschreibungen - es ist kein neues Wissen.\n\n"
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
    # Die Kennung im Dateinamen IST der Dedup-Speicher (siehe bereits_gelernt):
    # kein Indexfile daneben, das driften koennte.
    filepath = month_dir / f"conv_{ts}_{task_kennung(task)}.md"

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

    # Der Gruppe "Erlernt" zuordnen. Das geschah bisher NUR beim Oeffnen der
    # Gruppenseite – bis dahin galt die Datei als "ungruppiert", und der
    # Wissensgruppen-Filter lieferte je nach Vorgeschichte andere Ergebnisse.
    try:
        from backend import knowledge_groups as kg
        rel = str(filepath.relative_to(PROJECT_ROOT))
        kg.auto_assign_system_files([rel])
    except Exception as e:  # noqa: BLE001 – Lernen darf daran nicht scheitern
        _log.debug(f"Gruppen-Zuordnung der Lernnotiz fehlgeschlagen: {e}")


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
            # GEDROSSELT speichern statt bei jeder Notiz den kompletten Index:
            # add_chunks() mit save=True schrieb Index UND Metadaten vollstaendig
            # neu – bei 16.000 Chunks rund 50 MB fuer ein paar hundert Byte
            # neuen Inhalt. Die Notiz ist trotzdem sofort suchbar (der Index im
            # Speicher ist vollstaendig) und durch das Journal auch sofort
            # absturzsicher; nur die teure Serialisierung wird gebuendelt.
            geschrieben = vs.add_chunks_deferred(str(filepath), chunks, mtime)
            _log.info(
                f"FAISS: {len(chunks)} Chunk(s) fuer {filepath.name} sofort indexiert "
                f"(Gesamt: {vs.chunk_count()} Chunks"
                + (", Index gesichert)" if geschrieben else ", Journal)")
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
