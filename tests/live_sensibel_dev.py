#!/usr/bin/env python3
"""Live auf DEV: hinterlaesst ein SENSIBLER Chat-Lauf irgendwo eine Spur?

Schalter "sensible Daten" (backend/sensibel.py, 2026-11-24). Zwei Laeufe ueber
den echten Chat-WebSocket des laufenden Dienstes, je mit einer EIGENEN Marke
im Auftrag, im Anhang-Inhalt UND im Anhang-Namen:

  1. NORMAL   – Positivkontrolle: die Marke MUSS danach in LLM-Verlauf,
                Audit-Log und Journal stehen. Findet die Suche sie dort nicht,
                ist die Suche blind und das Ergebnis von Lauf 2 wertlos.
  2. SENSIBEL – dieselbe Aufgabe; die Marke darf NIRGENDS stehen.

Die Aufgabe erzeugt eine Ergebnisdatei (Shell + Auslieferung), damit auch
Arbeitsverzeichnis, Ablage und Download gemessen werden: der erste Download
muss gelingen (no-store), der zweite 404 liefern.

Zwei Teile, weil die Suche root braucht (Journal, Broker-Audit, fremde
Verzeichnisse) und der Lauf den Dienst-Schluessel (BSI M5):

    # als Dienst (Token gilt nur so):
    bash /opt/jarvis/deploy/als_dienst.sh env PYTHONDONTWRITEBYTECODE=1 \\
        venv/bin/python tests/live_sensibel_dev.py lauf <benutzer>
    # als root, mit den ausgegebenen Werten:
    PYTHONDONTWRITEBYTECODE=1 python3 tests/live_sensibel_dev.py pruefen \\
        <marke_normal> <marke_sensibel> <seit-epoch>

``<benutzer>``: ein Konto, dessen Laeufe in der Sandbox laufen (Domain-
Benutzer) – nur dann entsteht ein privates Arbeitsverzeichnis, das gemessen
werden kann. ``jarvis`` misst den privilegierten Weg (ohne Lauf-Verzeichnis).

Exit 0 = alles gehalten, 1 = Spur gefunden, 2 = konnte nicht laufen.
"""
import asyncio
import base64
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
BASIS = Path("/opt/jarvis")
_KTX = ssl._create_unverified_context()


# ── Teil 1: Laeufe ──────────────────────────────────────────────────────────

async def _ein_lauf(M, tok, marke, sensibel: bool, sid: str) -> dict:
    import websockets
    csv = f"name;wert\n{marke};1\nzwei;2\ndrei;3\n".encode()
    auftrag = (f"{marke}: Lies die angehaengte CSV-Datei mit der Shell und zaehle die "
               f"Datenzeilen. Erzeuge daraus mit Python eine Excel-Datei "
               f"/tmp/{marke}.xlsx mit denselben Zeilen und liefere sie mir zum Download. "
               f"Antworte kurz.")
    nachricht = {"type": "task", "text": auftrag, "token": tok, "lang": "de",
                 "bestaetigung": True, "session_id": sid,
                 "attachments": [{"name": f"{marke}.csv", "mime_type": "text/csv",
                                  "data": base64.b64encode(csv).decode()}]}
    if sensibel:
        nachricht["sensibel"] = True
    texte, fertig = [], False
    async with websockets.connect("wss://127.0.0.1/ws", ssl=_KTX, max_size=None) as ws:
        await ws.send(json.dumps(nachricht))
        ende = time.time() + 420
        while time.time() < ende:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            except asyncio.TimeoutError:
                continue
            texte.append(json.dumps(m, ensure_ascii=False))
            if m.get("type") == "agent_event" and m.get("event") == "finished":
                fertig = True
                break
        # Verbindung offen lassen, bis das Aufraeumen sicher durch ist: es
        # laeuft im Hintergrundlauf nach dem Ende von run_task.
        await asyncio.sleep(3)
    alles = "\n".join(texte)
    import re
    urls = sorted(set(re.findall(r"/api/documents/[0-9a-f]{32}__[A-Za-z0-9_\-]+\.[A-Za-z0-9]{1,8}", alles)))
    return {"fertig": fertig, "urls": urls, "antwort_hat_marke": marke in alles}


def _download(M, tok, url) -> tuple[int, str]:
    req = urllib.request.Request("https://127.0.0.1" + url,
                                 headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, context=_KTX, timeout=30) as r:
            r.read()
            return r.status, r.headers.get("Cache-Control", "")
    except urllib.error.HTTPError as e:
        return e.code, ""


async def lauf(benutzer: str) -> int:
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("ABBRUCH: websockets fehlt")
        return 2
    from backend import main as M
    tok = M.generate_token(benutzer)
    if not M.verify_token(tok):
        print("ABBRUCH: Token gilt nicht – Probe nicht ueber als_dienst.sh gestartet")
        return 2
    seit = int(time.time()) - 2
    m_norm = "sensprobe-n-" + uuid.uuid4().hex[:10]
    m_sens = "sensprobe-s-" + uuid.uuid4().hex[:10]
    # Sitzungen: normal braucht eine echte (Kontext wird gespeichert), sensibel
    # eine nur im Browser bekannte Kennung wie in chat.js.
    from backend import chat_sessions as cs
    s_norm = cs.create_session(benutzer, "sensprobe")["id"]
    s_sens = "sens-" + uuid.uuid4().hex[:12]
    r1 = await _ein_lauf(M, tok, m_norm, False, s_norm)
    r2 = await _ein_lauf(M, tok, m_sens, True, s_sens)
    dl = {}
    for u in r2["urls"]:
        erst = _download(M, tok, u)
        zweit = _download(M, tok, u)
        dl[u.rsplit("/", 1)[-1][:12] + "…"] = {"erster": erst, "zweiter": zweit}
    print(json.dumps({"benutzer": benutzer, "normal": {**r1, "marke": m_norm, "sitzung": s_norm},
                      "sensibel": {**r2, "marke": m_sens, "sitzung": s_sens,
                                   "downloads": dl}}, ensure_ascii=False, indent=1))
    print(f"PRUEFEN: {m_norm} {m_sens} {seit}")
    return 0 if (r1["fertig"] and r2["fertig"]) else 2


# ── Teil 2: Suche (root) ────────────────────────────────────────────────────

ORTE = [BASIS / "data" / "logs", BASIS / "data" / "chats", BASIS / "data" / "documents",
        BASIS / "data" / "erfahrung", BASIS / "data" / "gedaechtnis",
        BASIS / "data" / "memory.json", BASIS / "data" / "security_state.json",
        BASIS / "data" / "telemetry_errors.json", BASIS / "data" / "short_tracks_log.jsonl",
        BASIS / "data" / "chat_history",
        Path("/tmp/jarvis-arbeit"), Path("/tmp/jarvis-anhaenge"),
        Path("/var/log/jarvis-broker-audit.jsonl")]


def _fundorte(marke: str, seit: int) -> list[str]:
    treffer = []
    for o in ORTE:
        if not o.exists():
            continue
        r = subprocess.run(["grep", "-rlsF", marke, str(o)], capture_output=True, text=True)
        treffer += [z for z in r.stdout.splitlines() if z]
        # Dateinamen (nicht nur Inhalte): Anhang und Ergebnis tragen die Marke
        r = subprocess.run(["find", str(o), "-name", f"*{marke}*"], capture_output=True, text=True)
        treffer += ["NAME " + z for z in r.stdout.splitlines() if z]
    # /tmp oberste Ebene (privilegierter Lauf ohne Lauf-Verzeichnis)
    r = subprocess.run(["find", "/tmp", "-maxdepth", "1", "-name", f"*{marke}*"],
                       capture_output=True, text=True)
    treffer += ["NAME " + z for z in r.stdout.splitlines() if z]
    for unit in ("jarvis.service", "jarvis-broker.service"):
        r = subprocess.run(["journalctl", "-u", unit, "--since", f"@{seit}", "-o", "cat",
                            "--no-pager"], capture_output=True, text=True)
        n = r.stdout.count(marke)
        if n:
            treffer.append(f"JOURNAL {unit}: {n} Zeilen")
    return sorted(set(treffer))


def pruefen(m_norm: str, m_sens: str, seit: int) -> int:
    if os.geteuid() != 0:
        print("ABBRUCH: die Suche braucht root (Journal, fremde Verzeichnisse)")
        return 2
    norm = _fundorte(m_norm, seit)
    sens = _fundorte(m_sens, seit)
    print("NORMAL (Positivkontrolle) – Fundorte:")
    for t in norm:
        print("   ", t)
    print("SENSIBEL – Fundorte:")
    for t in sens:
        print("   ", t)
    pk = (any("/logs/conv/" in t for t in norm) and any("audit.jsonl" in t for t in norm)
          and any(t.startswith("JOURNAL jarvis.service") for t in norm))
    if not pk:
        print("ABBRUCH: Positivkontrolle fehlt (Verlauf, Audit und Journal muessen die "
              "normale Marke tragen) – die Suche waere blind")
        return 2
    print("\nOK: keine Spur des sensiblen Laufs" if not sens else
          f"\nBEFUND: {len(sens)} Spur(en) des sensiblen Laufs")
    return 0 if not sens else 1


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "lauf":
        sys.exit(asyncio.run(lauf(sys.argv[2])))
    if len(sys.argv) >= 5 and sys.argv[1] == "pruefen":
        sys.exit(pruefen(sys.argv[2], sys.argv[3], int(sys.argv[4])))
    print(__doc__)
    sys.exit(2)
