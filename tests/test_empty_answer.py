#!/usr/bin/env python3
"""Tests: Lauf endet OHNE Antwort – Nachschlag statt "✅ Aufgabe abgeschlossen".

DER FEHLER, den das absichert: der Abschlusszweig in ``run_task`` meldete
bedingungslos "✅ Aufgabe abgeschlossen", ohne zu pruefen, ob ueberhaupt ein
Antworttext beim Benutzer angekommen ist. Drei Wege dorthin – Parts ohne Text
(denkende Modelle), Text nur aus Leerzeichen, Anzeigetext nach
``_clean_doc_refs``/``_expand_charts`` leer. ``run_outcome`` blieb dabei "ok",
also griff auch der automatische Neuversuch in main.py nicht: die Anfrage galt
als erledigt, obwohl der Benutzer nichts sah.

WICHTIG – warum NICHT der ganze Lauf wiederholt wird: an dieser Stelle sind die
Werkzeuge schon gelaufen. Ein Lauf-Neuversuch wuerde sie ein zweites Mal
ausfuehren (Datei erzeugen, Ticket anlegen, Nachricht senden). Deshalb der
vorhandene ``_try_final``-Pfad: EIN weiterer LLM-Aufruf ohne Werkzeuge. Ein
Test haelt genau das fest (Werkzeug darf nur einmal laufen).

Zwei Teile:
  1. Quelltext-Pruefungen (laufen ueberall, auch ohne fastapi).
  2. Echte Laeufe von ``run_task`` mit Stub-Provider – nur wo fastapi da ist
     (DEV im venv). Ohne fastapi werden sie uebersprungen und gemeldet.
"""

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = 0
_fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  ✓ {text}")
    else:
        _fail += 1
        print(f"  ✗ {text}" + (f" – {detail}" if detail else ""))


# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 1. Quelltext: Backend-Weiche ===")

AGENT = (ROOT / "backend" / "agent.py").read_text()

pruefe("_answer_sent = False" in AGENT, "Merker _answer_sent wird initialisiert")
pruefe("_empty_finish = False" in AGENT, "Merker _empty_finish wird initialisiert")
pruefe(AGENT.count("_answer_sent = True") >= 3,
       "Merker wird an ALLEN Ausgabestellen gesetzt (Kurz-Prompt, Endtext, Final-Aufruf)",
       f"{AGENT.count('_answer_sent = True')} Vorkommen")

# Zwischentexte (intermediate) duerfen NICHT als Antwort zaehlen.
# Bewusst NICHT auf die woertliche Aufrufzeile pruefen: die hat sich am
# 2026-08-12 geaendert (Selbstgespraech-Erkennung, intermediate=is_intermediate
# or _nur_absicht) und der Test schlug an der Formatierung an, nicht am
# Verhalten. Geprueft wird die ABSICHT.
i_send = AGENT.find("await self._send_status(ws, _display, highlight=True")
pruefe(i_send > 0, "Endtext-Ausgabe gefunden")
fenster = AGENT[i_send:i_send + 400]
pruefe("intermediate=is_intermediate" in fenster,
       "die Ausgabe unterscheidet Zwischen- und Endtext")
pruefe("if not is_intermediate" in fenster,
       "nur NICHT-Zwischentexte zaehlen als Antwort (intermediate ist kein Endergebnis)")
# Seit 2026-08-12: ein reines Selbstgespraech ("Ich werde jetzt …") zaehlt
# ebenfalls nicht als Antwort, sonst bleibt der Nachschlag aus und der Benutzer
# sieht eine Absichtserklaerung als Endergebnis (Vorfall mit Tool-Syntax).
pruefe("_nur_absicht" in fenster,
       "ein Selbstgespraech zaehlt nicht als Antwort")

# Die Weiche steht VOR der Erfolgsmeldung
i_weiche = AGENT.find("if not _answer_sent and not _delivered_docs:")
i_fertig = AGENT.find('await self._send_status(ws, "✅ Aufgabe abgeschlossen")')
pruefe(0 < i_weiche < i_fertig,
       "Pruefung steht VOR '✅ Aufgabe abgeschlossen' (sonst waere sie wirkungslos)")
pruefe("_empty_finish = True" in AGENT[i_weiche:i_weiche + 400],
       "die Weiche setzt _empty_finish")
pruefe("_delivered_docs" in AGENT[i_weiche:i_weiche + 120],
       "ein ausgelieferter Download-Chip zaehlt als Ergebnis (kein Nachschlag)")

# Nachbehandlung: derselbe Pfad wie MAX_STEPS / Loop-Detector
pruefe("or _empty_finish) and not stop_scope.stopped" in AGENT,
       "_empty_finish loest die Final-Logik aus (ein Aufruf OHNE Werkzeuge)")
i_final = AGENT.find("or _empty_finish) and not stop_scope.stopped")
pruefe("keine Antwort formuliert" in AGENT[i_final:i_final + 1200],
       "eigene Meldung – nicht 'Maximale Schrittanzahl' oder 'Endlosschleife'")

# Rollback auch im Final-Pfad
i_empty = AGENT.find('run_outcome = "empty"', i_final)
pruefe(i_empty > 0, "Final-Pfad setzt run_outcome=empty (loest den Neuversuch in main.py aus)")
pruefe("_rollback_history" in AGENT[i_empty:i_empty + 1400],
       "Final-Pfad rollt den Verlauf zurueck (Regel: entweder vollstaendig oder unveraendert)")

# Der aeussere Neuversuch existiert und ueberspringt Benutzer-Stopps
MAIN = (ROOT / "backend" / "main.py").read_text()
pruefe("AUTO_RETRY_MAX" in MAIN and "is_final_attempt=_final" in MAIN,
       "automatischer Neuversuch am Aufrufort vorhanden")
pruefe('outcome in ("ok", "stopped")' in MAIN,
       "kein Neuversuch nach Erfolg oder Benutzer-Stopp")
CONFIG = (ROOT / "backend" / "config.py").read_text()
pruefe("AUTO_RETRY_MAX" in CONFIG and "AUTO_RETRY_DELAY_SEC" in CONFIG,
       "die Schalter sind echte Konfigurationswerte (kein getattr-Phantom)")

print("\n=== 2. Quelltext: Frontend-Freigabe ===")

CHAT = (ROOT / "frontend" / "js" / "chat.js").read_text()
pruefe("function _releaseRun(" in CHAT, "_releaseRun vorhanden")
i_close = CHAT.find("ws.onclose")
pruefe(0 < i_close and "_releaseRun('conn')" in CHAT[i_close:i_close + 900],
       "Verbindungsabbruch gibt den Laufzustand frei (sonst bleibt die Eingabe blockiert)")
pruefe("if (!agentRunning) return;" in CHAT,
       "_releaseRun ist idempotent (ein Reconnect im Ruhezustand meldet nichts)")
pruefe("_startRunWatchdog()" in CHAT and "_stopRunWatchdog()" in CHAT,
       "Stille-Wachhund wird gestartet und gestoppt")
i_started = CHAT.find("if (ev === 'started' && !isSub)")
pruefe(0 < i_started and "_startRunWatchdog()" in CHAT[i_started:i_started + 400],
       "Wachhund startet mit dem Lauf")
i_fin = CHAT.find("} else if (ev === 'finished' && !isSub)")
pruefe(0 < i_fin and "_stopRunWatchdog()" in CHAT[i_fin:i_fin + 300],
       "Wachhund endet mit dem Lauf")
pruefe("RUN_SILENCE_MS" in CHAT and "10 * 60 * 1000" in CHAT,
       "Frist ist grosszuegig (Notbremse, kein Zeitmesser)")
pruefe("_lastWsMsgAt = Date.now();" in CHAT[CHAT.find("ws.onmessage"):CHAT.find("ws.onmessage") + 200],
       "JEDE Server-Nachricht setzt die Frist zurueck")
pruefe("function _persistBotAnswer(" in CHAT,
       "Teiltext-Sicherung ist herausgezogen und wird von beiden Wegen genutzt")
pruefe(CHAT.count("_persistBotAnswer()") >= 2,
       "…aus 'finished' UND aus _releaseRun aufgerufen")

I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text()
for key in ("chat.run_lost_conn", "chat.run_lost_silence"):
    pruefe(I18N.count(f"'{key}'") == 2, f"i18n-Schluessel {key} in DE und EN")
pruefe("↻" in I18N[I18N.find("'chat.run_lost_conn'"):I18N.find("'chat.run_lost_conn'") + 300],
       "der Hinweis nennt den Weg zur Wiederholung (↻)")
pruefe("function _retryUserBubble" in CHAT and "msg-retry-btn" in CHAT,
       "halbautomatische Wiederholung (↻ an der Frage) ist vorhanden")

# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 3. Echte Laeufe mit Stub-Provider ===")

try:
    import fastapi  # noqa: F401
    from backend import agent as A
    from backend.llm import LLMResponse
    from google.genai import types
    HABEN_FASTAPI = True
except Exception as e:  # noqa: BLE001
    HABEN_FASTAPI = False
    print(f"  … uebersprungen: {type(e).__name__} ({e}) – auf DEV im venv ausfuehren")

if HABEN_FASTAPI:
    class WSAttrappe:
        """Faengt alles, was der Agent ans Fenster sendet."""

        def __init__(self):
            self.nachrichten = []

        async def send_json(self, msg):
            self.nachrichten.append(msg)

        def antworten(self):
            """Nur die als Endergebnis markierten Texte (highlight, nicht intermediate)."""
            return [m["message"] for m in self.nachrichten
                    if m.get("type") == "status" and m.get("highlight")
                    and not m.get("intermediate")]

        def alle_texte(self):
            return [m.get("message", "") for m in self.nachrichten]

    def teil(text):
        return types.Part.from_text(text=text)

    class Stub:
        """Liefert vorgegebene Antworten der Reihe nach.

        `mit_tools` merkt sich, ob der Aufruf Werkzeuge dabei hatte – so laesst
        sich pruefen, dass der Nachschlag OHNE Werkzeuge passiert.
        """

        def __init__(self, folge):
            self.folge = list(folge)
            self.aufrufe = []

        async def generate_response(self, model=None, system_prompt=None, contents=None,
                                    tools=None, **kw):
            self.aufrufe.append({"tools": bool(tools), "contents": list(contents or [])})
            if self.folge:
                parts = self.folge.pop(0)
            else:
                parts = [teil("Standardantwort")]
            return LLMResponse(parts=parts, raw=None, usage={})

    # ── SANDKASTEN FUER DEN LLM-VERLAUF ──────────────────────────────────
    # `run_task` UND (seit 2026-08-24) `_run_headless` schreiben nach
    # data/logs/conv. Ohne Umbiegen verschmutzt dieser Test den echten Verlauf
    # des laufenden Servers – er tat es bis heute unbemerkt. Wie bei den
    # Tabellen-Tests: umbiegen UND nachweisen, sonst Exit 2 ("konnte nicht
    # laufen" muss von "durchgefallen" unterscheidbar bleiben).
    import tempfile as _tf, shutil as _sh
    from backend import conv_log as _CL
    _SAND = Path(_tf.mkdtemp(prefix="empty_answer_conv_"))
    _ECHT_CONV = _CL._CONV_DIR
    _CL._CONV_DIR = _SAND / "conv"
    _CL._INDEX = _CL._CONV_DIR / "index.jsonl"
    _CL._OLD_FILE = _SAND / "conv_log.json"
    if _CL._CONV_DIR.resolve() == _ECHT_CONV.resolve() or \
            _SAND not in _CL._CONV_DIR.resolve().parents:
        print("ABBRUCH: conv_log zeigt nicht in das Wegwerf-Verzeichnis.")
        sys.exit(2)

    # EINEN echten Agenten bauen (kein __new__-Nachbau: run_task braucht ein
    # vollstaendig eingerichtetes Objekt – Stop-Scopes, Telemetrie, Verlaufs-
    # Buchhaltung).
    _agent = A.JarvisAgent()

    # ── DER PROVIDER MUSS UEBER get_provider GEPATCHT WERDEN ──────────────
    # run_task setzt `self.provider = get_provider(...)` bei JEDEM Lauf neu
    # (agent.py:1255). Ein vorher zugewiesenes Attribut wird dabei
    # ueberschrieben – die erste Testfassung hat deshalb das ECHTE Modell
    # befragt (auf DEV in der Ausgabe gesehen: eine echte Antwort und ein
    # httpx-Aufruf). Ein Test, der versehentlich das Produktionsmodell fragt,
    # beweist nichts und kostet Geld. Mit diesem Patch ist ein echter Aufruf
    # ausgeschlossen.
    _stub_halter = {"s": None}
    A.get_provider = lambda *a, **kw: _stub_halter["s"]

    def lauf(folge, verlauf_vorher=None):
        """Einen run_task-Lauf mit Stub fahren. Rueckgabe (outcome, ws, stub)."""
        stub = Stub(folge)
        _stub_halter["s"] = stub
        _agent.provider = stub
        # Frischer Verlauf je Lauf, damit sich die Faelle nicht beeinflussen.
        _agent._user_histories.clear()
        if verlauf_vorher is not None:
            _agent._user_histories[A._hist_key("jarvis")] = list(verlauf_vorher)
        ws = WSAttrappe()
        outcome = asyncio.run(_agent.run_task("Testfrage", ws, username="jarvis"))
        return outcome, ws, stub

    def verlauf():
        return _agent._user_histories.get(A._hist_key("jarvis"), [])

    # Der Aufbau oben ist bewusst minimal; klappt er nicht, sagt der Test das
    # deutlich, statt eine falsche Sicherheit zu erzeugen.
    try:
        outcome, ws, stub = lauf([[teil("Hier ist die Antwort.")]])
        machbar = True
    except Exception as e:  # noqa: BLE001
        machbar = False
        print(f"  … dynamischer Teil nicht lauffaehig: {type(e).__name__}: {e}")

    if machbar:
        pruefe(all(isinstance(a, dict) for a in stub.aufrufe) and len(stub.aufrufe) > 0,
               "der Stub wird wirklich benutzt (kein Aufruf am echten Modell)")
        pruefe(outcome == "ok", f"Normalfall: outcome ok ({outcome})")
        pruefe(any("Hier ist die Antwort." in t for t in ws.antworten()),
               "Normalfall: Antwort kommt beim Benutzer an")
        pruefe(len(stub.aufrufe) == 1, "Normalfall: genau EIN LLM-Aufruf (kein Nachschlag)")
        pruefe(any("✅ Aufgabe abgeschlossen" in t for t in ws.alle_texte()),
               "Normalfall: Abschlussmeldung erscheint weiterhin")

        # a) Antwort nur aus Leerzeichen -> Nachschlag liefert eine echte Antwort
        outcome, ws, stub = lauf([[teil("   ")], [teil("Nachgelieferte Antwort")]])
        pruefe(any("Nachgelieferte Antwort" in t for t in ws.antworten()),
               "Leerzeichen-Antwort: Nachschlag liefert eine echte Antwort")
        pruefe(not any("✅ Aufgabe abgeschlossen" in t for t in ws.alle_texte()),
               "Leerzeichen-Antwort: KEIN '✅ Aufgabe abgeschlossen' ohne Inhalt")
        pruefe(len(stub.aufrufe) >= 2, "Leerzeichen-Antwort: es gab einen zweiten Aufruf")
        pruefe(stub.aufrufe[-1]["tools"] is False,
               "der Nachschlag laeuft OHNE Werkzeuge (nichts wird doppelt ausgefuehrt)")
        pruefe(outcome == "ok", f"Leerzeichen-Antwort: Lauf gilt danach als erfolgreich ({outcome})")

        # b) Parts ohne jeden Text (denkendes Modell, nur Thinking-Part)
        outcome, ws, stub = lauf([[], [teil("Antwort nach leeren Parts")]])
        pruefe(any("Antwort nach leeren Parts" in t for t in ws.antworten()),
               "Antwort ohne Parts: Kurz-Prompt-Nachfrage liefert eine Antwort")

        # c) Auch der Nachschlag bleibt leer -> outcome empty (Neuversuch greift)
        outcome, ws, stub = lauf([[teil(" ")], [teil("")], [teil("")], [teil("")]])
        pruefe(outcome == "empty",
               f"dauerhaft leer: outcome=empty loest den Neuversuch aus ({outcome})")
        pruefe(any("keine antwort" in t.lower() for t in ws.alle_texte()),
               "dauerhaft leer: der Benutzer wird darauf hingewiesen")
        pruefe(len(verlauf()) == 0,
               f"dauerhaft leer: Verlauf zurueckgerollt, kein Rest im Kontext ({len(verlauf())} Eintraege)")

        # d) Rollback laesst einen VORHANDENEN Verlauf unangetastet
        vorher = [types.Content(role="user", parts=[teil("alte Frage")]),
                  types.Content(role="model", parts=[teil("alte Antwort")])]
        outcome, ws, stub = lauf([[teil("")], [teil("")], [teil("")], [teil("")]], vorher)
        pruefe(outcome == "empty" and len(verlauf()) == 2,
               f"leerer Lauf laesst den bestehenden Verlauf unveraendert ({len(verlauf())} Eintraege)")

        # e) Zwischentext neben einem Werkzeugaufruf ist KEINE Antwort
        class EchoTool:
            name = "echo"
            supports_streaming = False

            async def execute(self, **kw):
                return "Werkzeug-Ergebnis"

        _agent.tools_map["echo"] = EchoTool()
        fc = types.Part.from_function_call(name="echo", args={})
        outcome, ws, stub = lauf([
            [teil("Ich schaue kurz nach …"), fc],   # Zwischentext + Werkzeug
            [teil("   ")],                          # leerer Abschluss
            [teil("Endgueltige Antwort")],           # Nachschlag
        ])
        pruefe(any("Endgueltige Antwort" in t for t in ws.antworten()),
               "Zwischentext + leerer Abschluss: Nachschlag greift trotzdem")
        pruefe(sum(1 for a in stub.aufrufe if a["tools"]) == 2
               and stub.aufrufe[-1]["tools"] is False,
               "Werkzeug-Lauf: der Nachschlag ist der einzige Aufruf OHNE Werkzeuge")
        _agent.tools_map.pop("echo", None)

# ═════════════════════════════════════════════════════════════════════════════
if HABEN_FASTAPI and machbar:
    print("\n=== 4. Headless-Laeufe stehen im LLM-Verlauf ===")
    # Gemeldet am 2026-08-24: ein fehlgeschlagener Short-Tracks-Lauf hinterliess
    # KEINE Spur im LLM-Verlauf. Das Skill-Protokoll sagte "Das Modell hat keine
    # Antwort formuliert", und im Verlauf stand zu diesem Zeitpunkt nur ein
    # fremder Chat-Lauf: keine Werkzeugkette, keine Token-Zahl, kein
    # Abbruchgrund. Nur `run_task` protokollierte, `_run_headless` nicht – also
    # ausgerechnet die Kanaele, die ohne Zuschauer laufen (E-Mail-Regeln, Short
    # Tracks, Cron, Rollen-Agenten).

    class ToolStub:
        name = "echo"
        supports_streaming = False

        async def execute(self, **kw):
            return "Werkzeug-Ergebnis-headless"

    def hl_lauf(folge, rolle=""):
        stub = Stub(folge)
        _stub_halter["s"] = stub
        _agent.provider = stub
        _agent._role_id = rolle
        _agent.tools_map["echo"] = ToolStub()
        try:
            return asyncio.run(_agent.run_task_headless("Headless-Testfrage")), stub
        finally:
            _agent.tools_map.pop("echo", None)
            _agent._role_id = ""

    def letzter_eintrag():
        eintraege = _CL.get_conversations(limit=1)
        return eintraege[0] if eintraege else None

    vorher = len(_CL.get_conversations(limit=500))
    fc = types.Part.from_function_call(name="echo", args={})
    antwort, stub = hl_lauf([[teil("Ich sehe nach …"), fc],
                            [teil("Fertig: das Ergebnis lautet 42.")]],
                            rolle="dump:abc123")
    nachher = _CL.get_conversations(limit=500)
    pruefe(len(nachher) == vorher + 1,
           "ein headless-Lauf erzeugt GENAU EINEN Verlaufs-Eintrag",
           f"{vorher} -> {len(nachher)}")
    e = letzter_eintrag()
    pruefe(bool(e) and e.get("steps") == 1,
           "die Schrittzahl steht drin", str(e and e.get("steps")))
    pruefe(bool(e) and str(e.get("client_type", "")).startswith("headless"),
           "der Kanal ist als headless erkennbar", str(e and e.get("client_type")))
    pruefe(bool(e) and "dump:abc123" in str(e.get("client_type", "")),
           "und nennt die Rolle/Ablage – sonst weiss niemand, WELCHER Lauf es war",
           str(e and e.get("client_type")))
    body = _CL.get_body(e["id"]) if e else {}
    rollen = [m.get("role") for m in (body.get("messages") or [])]
    pruefe("tool" in rollen and "assistant" in rollen,
           "Werkzeugkette UND Antworttexte sind im Rumpf", str(rollen))
    pruefe(any("Werkzeug-Ergebnis-headless" in str(m.get("content", ""))
               for m in (body.get("messages") or [])),
           "das Werkzeug-ERGEBNIS steht drin (ohne es ist die Diagnose blind)")
    pruefe(len(body.get("system_prompt") or "") > 100,
           "der System-Prompt ist dabei (vollstaendig, wie im Chat-Weg)")

    # DER wichtige Fall: ein Lauf OHNE Ergebnis muss ebenfalls im Verlauf stehen
    vorher = len(_CL.get_conversations(limit=500))
    antwort, stub = hl_lauf([[teil("   ")]])
    pruefe(len(_CL.get_conversations(limit=500)) == vorher + 1,
           "auch ein Lauf ohne Antwort wird protokolliert – genau der ist der "
           "interessante")

    _sh.rmtree(_SAND, ignore_errors=True)

print(f"\n{'=' * 62}\nErgebnis: {_ok}/{_ok + _fail} Pruefungen bestanden")
if _fail:
    print(f"FEHLGESCHLAGEN: {_fail}")
sys.exit(1 if _fail else 0)
