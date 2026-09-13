"""Jarvis Learning System – Automatisches Lernen aus Konversationen.

Nach jeder Konversation werden faktische Erkenntnisse aus Tool-Ergebnissen
extrahiert und als Markdown-Notiz unter data/erfahrung/ abgelegt.

Kern-Prinzip: Lernen bedeutet, etwas NACHHER BESSER ODER RICHTIGER zu machen
als VORHER. Ein gespeicherter Fakt ist nur dann eine Lernerkenntnis, wenn
Jarvis dadurch eine zukuenftige Aufgabe besser oder korrekter erledigen kann.
Ephemere Fakten (aktuelles Datum, momentane Systemzustaende, Einmal-Messwerte)
sind KEIN Lernen und werden explizit ausgefiltert.

Anti-Halluzinations-Schutz:
- Nur Tool-Ergebnisse (role='tool') werden analysiert – keine LLM-Spekulationen.
- LLM-Prompt prueft jeden Fakt am Verbesserungs-Kriterium: "Hilft das in Zukunft?"
- Leere / "NICHTS"-Antworten werden still verworfen.

WO DAS LANDET – UND WARUM NICHT IN DER WISSENSDATENBANK (Vorgabe 2026-09-13):
Diese Notizen sind VERFAHRENSwissen des Agenten ueber seine eigene Umgebung
(Feldzuordnungen, Namenskonventionen, Shell-Beschraenkungen) – keine
Kundendokumentation. Sie lagen bis 2026-09-13 unter data/knowledge/learned/,
also INNERHALB eines Wissensordners, und wurden damit in dieselbe Vektor-DB
indiziert wie Handbuecher und Kundenunterlagen. Dort trugen sie die
Benutzerfrage als Ueberschrift und waren fuer genau diese Frage der perfekte
semantische Treffer – unabhaengig vom Inhalt. Gegengehalten wurde mit einer
Ranking-Abwertung (LEARNED_PENALTY); die ist ein Konstrukt, das bei jeder
kuenftigen Durchsicht mitgeprueft werden muss und irgendwann still ausfaellt.
Der Ordner liegt deshalb AUSSERHALB jedes Wissensordners: was nicht in der
Ordnerliste steht, kann nicht hineinrutschen – keine Ausnahme, kein Gewicht,
kein Filter. `_all_files()` sieht ihn gar nicht erst.

Architektur:
- learn_from_conversation() wird als asyncio.Task (fire-and-forget) aufgerufen.
- Schreibt Markdown-Datei nach data/erfahrung/YYYY-MM/conv_<ts>_<kennung>.md
  (die Kennung ist der Hash der Aufgabe – daran erkennt der naechste Lauf,
   dass dieselbe Aufgabe schon gelernt wurde, siehe `bereits_gelernt`)
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
# DIE EINE QUELLE fuer den Ort des Erfahrungswissens. Jedes andere Modul
# IMPORTIERT sie – ein nachgebauter Pfad (es gab drei davon) laeuft beim
# naechsten Umzug auseinander, und die vergessene Stelle meldet sich nicht:
# sie schreibt bzw. sucht nur an einem Ort, den niemand mehr liest.
# ⚠ DIESER PFAD DARF NIE UNTER EINEM WISSENSORDNER LIEGEN – sonst indiziert
# `_all_files()` ihn wieder mit (Waechter: tests/test_erfahrung_getrennt.py).
LEARNED_DIR = PROJECT_ROOT / "data" / "erfahrung"

# Der fruehere Ort. Wird nur noch von der einmaligen Migration gelesen.
_ALTER_ORT = PROJECT_ROOT / "data" / "knowledge" / "learned"

# Dateinamens-Praefix der Notizen (Vorgabe 2026-09-13: "conv_" -> "auto_lerned_").
# ⚠ AUCH DAS IST EINE QUELLE, KEINE KONVENTION: der Name stand an acht Stellen
# hart im Code (learning, knowledge_compactor, main, deploy-Skript). Wer ihn
# aendert und eine Stelle vergisst, bekommt keinen Fehler – nur eine Suche, die
# nichts mehr findet: die Dedup-Erkennung haelt jede Aufgabe fuer neu, die
# Statistik zaehlt 0, und die Verdichtung sammelt nichts mehr ein.
NOTIZ_PRAEFIX = "auto_lerned_"

# Praefixe frueherer Fassungen – ausschliesslich fuer die Umbenennung beim
# Umzug. Ein kuenftiger Wechsel traegt hier das dann alte Praefix nach.
_ALTE_PRAEFIXE = ("conv_",)

# Verfahrensdateien, die bis 2026-09-13 AUS DEM REPO in data/knowledge/ lagen
# und damit in der Vektor-DB standen. Sie sind dort entfernt (.gitignore +
# git rm); auf einem Server verschwinden die DATEIEN beim naechsten Pull.
# ⚠ IHRE CHUNKS BLEIBEN DAVON UNBERUEHRT: der Suchpfad raeumt bewusst nichts
# auf (ein kurz nicht erreichbares Netzlaufwerk wuerde sonst seinen ganzen
# Share verlieren), und der Neuaufbau laeuft nur auf Knopfdruck. Bis dahin
# lieferte die Suche Treffer aus Dateien, die es nicht mehr gibt.
_REPO_VERFAHRENSDATEIEN = (
    "browser_automation.md",   # byte-identisch mit der gleichnamigen Instruktion
    "projektinfo.md",          # veraltete Zweitfassung (unaufgeloestes ${SERVER_IP})
    "whatsapp_workflow.md",    # Kernregel steht in den Werkzeug-Beschreibungen
)

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
#   3. Es blaeht die Notizen mit Angaben auf, die der Agent ohnehin hat.
#      (Bis 2026-09-13 war Punkt 3 gravierender: die Notizen lagen im
#       FAISS-Index und verdraengten dort echte Kundendokumentation. Seit dem
#       Umzug nach data/erfahrung/ ist das vom Tisch - der Filter bleibt
#       trotzdem, aus den Gruenden 1 und 2.)
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
        for p in LEARNED_DIR.rglob(f"{NOTIZ_PRAEFIX}*_{kennung}.md"):
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

        # Fakten-Datei schreiben (NICHT indizieren, siehe Modul-Kopf)
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
    """Schreibt die Erfahrungsnotiz nach LEARNED_DIR. Indiziert NICHT.

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
    filepath = month_dir / f"{NOTIZ_PRAEFIX}{ts}_{task_kennung(task)}.md"

    # Task-Kurzname fuer Ueberschrift
    task_clean = re.sub(r'[^\w\s\-]', '', task[:80]).strip()

    content = (
        f"# Gelernt: {task_clean}\n"
        f"Datum: {now.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"{facts_text.strip()}\n"
    )

    filepath.write_text(content, encoding="utf-8")
    _log.info(f"Erfahrungsnotiz geschrieben: {filepath.name}")

    # ⚠ HIER WIRD NICHT INDIZIERT, UND DAS IST DER ZWEITE HALBE FIX.
    # Bis 2026-09-13 stand hier `_index_immediately(filepath, content)` – ein
    # AKTIVER Weg in die Vektor-DB, unabhaengig vom Ordner-Scan. Den Ordner nur
    # zu verschieben haette diesen Kanal OFFEN gelassen: `add_chunks_deferred`
    # nimmt jeden Pfad entgegen, auch einen ausserhalb der Wissensordner. Die
    # Chunks waeren suchbar gewesen und erst beim naechsten VOLL-Reindex als
    # verwaist aufgefallen. Ebenso entfaellt die Zuordnung zur Gruppe "Erlernt":
    # Wissensgruppen ordnen Dateien der Wissensdatenbank – hier gibt es nichts
    # mehr zuzuordnen.


# ─── Umzug aus der Wissensdatenbank (einmalig, 2026-09-13) ───────────────────

def _zielname(name: str) -> str:
    """Dateiname mit aktuellem Praefix. Unbeteiligte Namen bleiben unangetastet.

    ``feedback_*.md`` wird ABSICHTLICH nicht angefasst: das ist eine andere
    Gattung (Benutzer-Bewertungen, geschrieben von main.py) mit anderem Aufbau.
    Ein Verzeichnis kann mehrere Gattungen enthalten – wer ein Muster auf „alle
    Dateien darin" anwendet, hat die Endung geprueft, nicht die Gattung.
    """
    for alt in _ALTE_PRAEFIXE:
        if name.startswith(alt):
            return NOTIZ_PRAEFIX + name[len(alt):]
    return name


def migriere_aus_wissensdatenbank() -> dict:
    """Holt den Bestand aus ``data/knowledge/learned/`` nach ``data/erfahrung/``.

    Drei Schritte, und alle drei sind noetig – der erste allein liesse die
    Notizen weiter in der Vektor-DB stehen:
      1. Dateien verschieben (der alte Ort liegt IN einem Wissensordner).
      2. Die Chunks der alten Pfade aus dem Vektor-Index entfernen. Sonst
         bleiben sie bis zum naechsten VOLL-Reindex suchbar – und der laeuft
         nur auf Knopfdruck. Ein Suchlauf raeumt bewusst nichts auf
         (siehe `_rebuild_vector_index`).
      3. Die Wissensgruppen-Zuordnungen der alten Pfade entfernen, damit keine
         Karteileichen in `.groups.json` zurueckbleiben.

    Idempotent und fail-safe: gibt es den alten Ort nicht, passiert nichts und
    es wird nichts protokolliert (eine Zeile bei jedem Start, die immer
    dasselbe sagt, wird nach zwei Tagen nicht mehr gelesen). Jeder Schritt ist
    einzeln abgesichert – ein fehlgeschlagenes Aufraeumen darf die bereits
    verschobenen Dateien nicht zurueckdrehen.

    ⚠ VERSCHOBEN, NICHT KOPIERT: zwei Staende derselben Notiz waeren genau der
    Zustand, den der Umzug beseitigt – einer davon laege weiter im Index.
    """
    ergebnis = {"verschoben": 0, "umbenannt": 0, "chunks_entfernt": 0, "fehler": []}

    import shutil

    # (0) Notizen, die schon am neuen Ort liegen, aber noch das alte Praefix
    # tragen. Das ist kein theoretischer Fall: wer nur den Ordner umzieht (von
    # Hand, per Restore, per halbem Deploy), haette sonst Dateien, die
    # `bereits_gelernt` und die Statistik nicht mehr finden – die Notiz liegt
    # da, gilt aber als nicht vorhanden.
    if LEARNED_DIR.exists():
        try:
            for datei in sorted(LEARNED_DIR.rglob("*.md")):
                neuer = _zielname(datei.name)
                if neuer == datei.name:
                    continue
                ziel = datei.with_name(neuer)
                try:
                    if ziel.exists():
                        continue
                    datei.rename(ziel)
                    ergebnis["umbenannt"] += 1
                except Exception as e:  # noqa: BLE001
                    ergebnis["fehler"].append(f"{datei.name}: {e}")
        except Exception as e:  # noqa: BLE001
            ergebnis["fehler"].append(f"Umbenennen: {e}")

    if not _ALTER_ORT.exists():
        if ergebnis["umbenannt"]:
            _log.info("Erfahrungsnotizen umbenannt: %d Datei(en) auf '%s'",
                      ergebnis["umbenannt"], NOTIZ_PRAEFIX)
        return ergebnis

    alte_pfade: list[str] = []
    try:
        for quelle in sorted(_ALTER_ORT.rglob("*")):
            if not quelle.is_file():
                continue
            rel = quelle.relative_to(_ALTER_ORT)
            # Verschieben UND umbenennen in einem Zug – zwei getrennte Laeufe
            # haetten einen Zwischenzustand, in dem die Notiz am neuen Ort liegt
            # und von keiner Suche gefunden wird.
            ziel = LEARNED_DIR / rel.parent / _zielname(rel.name)
            try:
                ziel.parent.mkdir(parents=True, exist_ok=True)
                if ziel.exists():
                    # Teilmigration eines frueheren Laufs: der neue Ort gewinnt,
                    # die alte Datei wird nur noch entfernt.
                    quelle.unlink()
                else:
                    shutil.move(str(quelle), str(ziel))
                alte_pfade.append(str(quelle))
                ergebnis["verschoben"] += 1
            except Exception as e:  # noqa: BLE001
                ergebnis["fehler"].append(f"{rel}: {e}")
    except Exception as e:  # noqa: BLE001
        ergebnis["fehler"].append(f"Durchlauf: {e}")

    # Leere Verzeichnisse des alten Ortes abraeumen – ein leerer Ordner unter
    # data/knowledge/ ist harmlos, aber er laedt dazu ein, wieder etwas
    # hineinzulegen.
    if not ergebnis["fehler"]:
        try:
            shutil.rmtree(_ALTER_ORT, ignore_errors=True)
        except Exception as e:  # noqa: BLE001
            ergebnis["fehler"].append(f"Aufraeumen: {e}")

    # Index: die alten Pfade sind jetzt verwaist.
    if alte_pfade:
        try:
            from backend.tools.knowledge import _get_vector_store
            vs = _get_vector_store()
            if vs is not None:
                ergebnis["chunks_entfernt"] = vs.remove_files(alte_pfade)
        except Exception as e:  # noqa: BLE001
            ergebnis["fehler"].append(f"Index: {e}")

        # Wissensgruppen: Zuordnungen der alten Pfade entfernen.
        try:
            from backend import knowledge_groups as kg
            rel_alt = []
            for ap in alte_pfade:
                try:
                    rel_alt.append(str(Path(ap).relative_to(PROJECT_ROOT)))
                except ValueError:
                    pass
            if rel_alt and hasattr(kg, "remove_assignments"):
                kg.remove_assignments(rel_alt)
        except Exception as e:  # noqa: BLE001
            ergebnis["fehler"].append(f"Gruppen: {e}")

    if ergebnis["verschoben"] or ergebnis["fehler"]:
        _log.info(
            "Erfahrungswissen umgezogen: %d Datei(en) nach %s (%d umbenannt), "
            "%d Chunk(s) aus dem Vektor-Index entfernt%s",
            ergebnis["verschoben"], LEARNED_DIR, ergebnis["umbenannt"],
            ergebnis["chunks_entfernt"],
            (" – FEHLER: " + "; ".join(ergebnis["fehler"])) if ergebnis["fehler"] else "",
        )
    return ergebnis


def verfahrensdateien_aus_index_raeumen() -> dict:
    """Chunks der ehemaligen Repo-Verfahrensdateien aus der Vektor-DB nehmen.

    Gegenstueck zu `git rm` + .gitignore (Vorgabe 2026-09-13): auf einem Server
    entfernt der naechste Pull die DATEIEN, ihre Chunks blieben aber bis zum
    naechsten ausdruecklichen Neuaufbau im Index – die Suche lieferte also
    Treffer aus Dateien, die es nicht mehr gibt.

    ⚠ ES WIRD KEINE DATEI ANGEFASST. Liegt eine der drei noch auf der Platte
    (Server ohne Pull, lokal geaenderte Fassung), bleibt sie unberuehrt und
    ihre Chunks bleiben ebenfalls – sonst wuerde dieser Hook eine vorhandene
    Datei stillschweigend unauffindbar machen. Geraeumt wird nur, was WEG ist.

    Die Namensliste ist endlich und bekannt; eine allgemeine Regel „alles
    aufraeumen, was nicht mehr existiert" waere hier gefaehrlich: genau daran
    hat ein kurz nicht erreichbares Netzlaufwerk schon einmal seinen kompletten
    Share aus dem Index verloren (siehe `_rebuild_vector_index`).
    """
    ergebnis = {"chunks_entfernt": 0, "fehler": []}
    try:
        from backend.tools.knowledge import _get_vector_store, _get_folders
        vs = _get_vector_store()
        if vs is None:
            return ergebnis
        indiziert = vs.get_indexed_files()
        if not indiziert:
            return ergebnis

        weg = []
        for ordner in _get_folders():
            for name in _REPO_VERFAHRENSDATEIEN:
                kandidat = ordner / name
                if str(kandidat) in indiziert and not kandidat.exists():
                    weg.append(str(kandidat))
        if weg:
            ergebnis["chunks_entfernt"] = vs.remove_files(weg)
            _log.info("Verfahrensdateien aus dem Vektor-Index entfernt: %d Chunk(s) "
                      "aus %d Datei(en) – %s",
                      ergebnis["chunks_entfernt"], len(weg),
                      ", ".join(Path(w).name for w in weg))
    except Exception as e:  # noqa: BLE001 – darf den Start nie aufhalten
        ergebnis["fehler"].append(str(e))
    return ergebnis


# ─── Statistik-API ────────────────────────────────────────────────────────────

def get_learned_stats() -> dict:
    """Gibt Statistiken ueber gelernte Konversationen zurueck."""
    try:
        if not LEARNED_DIR.exists():
            return {"total_files": 0, "total_size_kb": 0, "months": []}

        files = list(LEARNED_DIR.rglob(f"{NOTIZ_PRAEFIX}*.md"))
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
