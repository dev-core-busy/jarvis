#!/usr/bin/env python3
"""NUR LESEN: warum greift der Chat-Preprompt auf ECHT nicht?

⚠ Dieses Skript VERAENDERT NICHTS. Es oeffnet keine Datei zum Schreiben, legt
nichts an, loescht nichts und startet keinen Dienst neu. Es beantwortet genau
zwei Fragen:

  1. Steht in irgendeiner Sitzung ein `preprompt` in der meta.json?
     (Ja  -> das Speichern geht, es klemmt beim ANWENDEN.
      Nein -> es klemmt beim SPEICHERN, und der Lauf ist unschuldig.)
  2. Sehen HTTP-Weg und Agentenlauf denselben Ablageordner?

⚠ ES WERDEN KEINE INHALTE AUSGEGEBEN – weder Prompts noch Chat-Titel noch
Nachrichten. Der Preprompt ist Text eines Menschen; fuer die Diagnose genuegen
Laenge und Zeitstempel. Ausgegeben werden nur Kennzahlen.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
from backend import chat_sessions as CS                          # noqa: E402
from backend.benutzer import pfad_teil, norm_user                # noqa: E402

WURZEL = Path("/opt/jarvis/data/chats")
print("=" * 66)
print("  LESEND: Chat-Preprompt auf ECHT")
print("=" * 66)

if not WURZEL.is_dir():
    print("Kein Chat-Verzeichnis unter %s" % WURZEL)
    sys.exit(2)

gesamt = mit_prompt = 0
for ordner in sorted(WURZEL.iterdir()):
    if not ordner.is_dir():
        continue
    treffer = []
    n = 0
    for meta in sorted(ordner.glob("*/meta.json")):
        n += 1
        gesamt += 1
        try:
            d = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:                                        # noqa: BLE001
            continue
        p = (d.get("preprompt") or "").strip()
        if p:
            mit_prompt += 1
            alter = time.time() - meta.stat().st_mtime
            treffer.append((meta.parent.name, len(p), alter / 3600.0))
    if n:
        print("\n%-28s  %2d Sitzungen, %d mit Prompt"
              % (ordner.name, n, len(treffer)))
        for sid, laenge, std in treffer:
            # Nur Kennzahlen – KEIN Inhalt.
            print("    Sitzung %s: %d Zeichen, zuletzt vor %.1f h geaendert"
                  % (sid, laenge, std))

print("\n%s\nBILANZ: %d Sitzungen gesamt, %d mit Chat-Preprompt"
      % ("-" * 66, gesamt, mit_prompt))

if not mit_prompt:
    print("""
⇒ ES IST NIE EINER GESPEICHERT WORDEN. Damit klemmt es beim SPEICHERN
  (Oberflaeche/Endpunkt), nicht beim Anwenden – der Agentenlauf kann nichts
  finden, was nicht da ist. Naechster Schritt: der Speicherweg im Browser.""")
else:
    print("""
⇒ ES IST MINDESTENS EINER GESPEICHERT. Damit ist das Speichern in Ordnung und
  es klemmt beim ANWENDEN (session_id im Lauf, Benutzerzuordnung, Reihenfolge).""")

# ── Zweite Frage: sehen beide Wege denselben Ordner? ───────────────────────
print("\n%s\nOrdner-Zuordnung (beide Wege muessen denselben Ordner treffen):"
      % ("-" * 66,))
for form in ("andreas.bender", "nexus\\andreas.bender",
             "NEXUS\\Andreas.Bender", "andreas.bender@nexus-ag.de"):
    print("  %-30r -> norm=%-20r ordner=%r"
          % (form, norm_user(form), pfad_teil(form, "anonymous")))

# Und was der echte Leser des Agentenlaufs zurueckgibt – ohne Inhalt.
print("\nGegenprobe ueber die ECHTE Lesefunktion (nur Laenge):")
for ordner in sorted(WURZEL.iterdir()):
    if not ordner.is_dir():
        continue
    for meta in sorted(ordner.glob("*/meta.json"))[:40]:
        sid = meta.parent.name
        try:
            t = CS.get_session_preprompt(ordner.name, sid) or ""
        except Exception as e:                                   # noqa: BLE001
            t = "<Fehler: %s>" % e
        if t:
            print("  %s / %s -> %d Zeichen" % (ordner.name, sid, len(t)))
print("=" * 66)
