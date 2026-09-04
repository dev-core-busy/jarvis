#!/usr/bin/env python3
"""Misst auf DEV, wie oft das Modell nach `office_create_powerpoint` einen
Phantom-Liefer-Marker setzt (der Fall von ECHT, Lauf 17884986262140001).

Gemessen wird der ROHE Modelltext aus dem Konversationslog - im Chat ist der
Marker unsichtbar (`_clean_doc_refs` entfernt ihn).

Aufruf:  cd /opt/jarvis && runuser -u jarvis -- ./venv/bin/python <datei> [N]
"""
import asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0, "/opt/jarvis")

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
AUFGABE = ("Erstelle eine PowerPoint-Präsentation mit 6 Folien über die Vorteile von "
           "Prozessautomatisierung. Baue auf einer Folie ein echtes Schaubild mit Kästen "
           "und Verbindungspfeilen (kein Aufzählungstext) für den Ablauf: "
           "Auslöser → Prüfung → Verarbeitung → Benachrichtigung.")
CONV = Path("/opt/jarvis/data/logs/conv")


class WS:
    def __init__(self): self.msgs = []
    async def send_json(self, d): self.msgs.append(d)
    async def send_text(self, t): self.msgs.append({"message": t})


async def main():
    from backend.agent import JarvisAgent
    marker = warn = chip = 0
    for i in range(N):
        vorher = {p.name for p in CONV.glob("*.json")}
        ws = WS()
        t0 = time.time()
        await JarvisAgent().run_task(AUFGABE, ws, username="jarvis")
        neu = [p for p in CONV.glob("*.json") if p.name not in vorher]
        roh = ""
        if neu:
            d = json.loads(max(neu, key=lambda p: p.stat().st_mtime).read_text())
            roh = "\n".join(str(m.get("content", "")) for m in d.get("messages", [])
                            if m.get("role") == "assistant")
        m = "JARVIS_DELIVER" in roh
        w = any("Konnte nicht zum Download" in str(x.get("message", "")) for x in ws.msgs)
        c = any("/api/documents/" in str(x.get("message", "")) for x in ws.msgs)
        marker += m; warn += w; chip += c
        print(f"  Lauf {i+1}: {time.time()-t0:5.1f}s  Marker={'JA' if m else 'nein':4}  "
              f"Chip={'ja' if c else 'NEIN':4}  Warnung={'JA' if w else 'nein'}")
        if m:
            i0 = roh.index("[[JARVIS_DELIVER")
            print(f"           -> {roh[i0:i0+80]}")
    print(f"\nBILANZ ueber {N} Laeufe: Phantom-Marker {marker}/{N}, "
          f"Chip {chip}/{N}, Warnung {warn}/{N}")


asyncio.run(main())
