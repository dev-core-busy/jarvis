#!/usr/bin/env python3
"""Live auf DEV: tragen die Journal-Zeilen eines echten Chat-Auftrags die Herkunft?

Anlass: ECHT 2026-11-23 11:21 – Fehlerlog und Journal nannten weder Benutzer
noch Kanal noch LLM-Server (backend/log_kontext.py, Waechter
test_log_kontext.py). Diese Probe schickt EINEN harmlosen Auftrag ueber den
echten Chat-WebSocket des laufenden Dienstes; die Auftragszeile traegt eine
Marke je Lauf. Ausgewertet wird danach das Journal (als root):

    bash /opt/jarvis/deploy/als_dienst.sh env PYTHONDONTWRITEBYTECODE=1 \\
        venv/bin/python tests/live_log_kontext_dev.py
    journalctl -u jarvis.service --since "-5 min" -o cat | grep <marke>

Ausgabe: die Marke (Zeile ``MARKE=…``). Exit 2, wenn kein Lauf zustande kam.
"""
import asyncio
import json
import ssl
import sys
import uuid

sys.path.insert(0, "/opt/jarvis")

try:
    import websockets  # noqa: E402
except ImportError:
    print("ABBRUCH: websockets fehlt")
    sys.exit(2)

from backend import main as M  # noqa: E402

URL = "wss://127.0.0.1/ws"
_KTX = ssl._create_unverified_context()


async def main():
    tok = M.generate_token("jarvis")
    if not M.verify_token(tok):
        print("ABBRUCH: Token gilt nicht – Probe nicht ueber als_dienst.sh gestartet")
        return 2
    marke = "logkontext-" + uuid.uuid4().hex[:10]
    auftrag = f"{marke}: Antworte nur mit dem Wort OK."
    fertig = False
    async with websockets.connect(URL, ssl=_KTX, max_size=None) as ws:
        await ws.send(json.dumps({"type": "task", "text": auftrag, "token": tok,
                                  "lang": "de", "bestaetigung": True}))
        ende = asyncio.get_event_loop().time() + 180
        while asyncio.get_event_loop().time() < ende:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            except asyncio.TimeoutError:
                continue
            if m.get("type") == "error":
                print("Fehler:", m.get("message"))
                break
            txt = str(m.get("message", ""))
            if m.get("type") == "status" and ("Aufgabe abgeschlossen" in txt or "gestoppt" in txt):
                fertig = True
                break
    print(f"MARKE={marke}")
    print("Lauf abgeschlossen" if fertig else "Lauf ohne Abschlussmeldung")
    return 0 if fertig else 2


sys.exit(asyncio.run(main()))
