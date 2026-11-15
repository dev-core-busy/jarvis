#!/usr/bin/env python3
"""Live auf DEV: fehlt kb_groups im Auftrag, gilt die Auswahl der SITZUNG.

Vorfall ECHT 2026-11-06: "Wiederholen" im Chat schickte den Auftrag ohne
``kb_groups``, ein fehlendes Feld hiess "alle Gruppen", und die Wissenssuche
lieferte Wissen aus einer abgewaehlten Gruppe. Diese Probe misst den Rueckfall
ueber den ECHTEN Chat-WebSocket bis in das Werkzeugergebnis.

Die Sonde haengt NICHT am Index-Inhalt: die Probe-Sitzung speichert die
Auswahl "keine Gruppe" ([]). Kommt sie beim Werkzeug an, antwortet
``knowledge_search`` mit der festen Sperrmeldung "Keine Wissensgruppen
ausgewählt" – das kann nur der Filterweg erzeugen.

  A. Positivkontrolle: dieselbe Sitzung, ausdruecklich ``kb_groups: null``
     -> KEINE Sperrmeldung (sonst misst B nichts).
  B. Gemeldeter Weg: Feld FEHLT -> Sperrmeldung (vorher: Suche ueber alles).
  C. Gegenkontrolle der Sonde: ``kb_groups: []`` ausdruecklich -> Sperrmeldung.

Das Modell entscheidet, ob es das Werkzeug ruft – je Fall bis zu drei
Versuche; ohne Aufruf ist es "nicht gemessen" (Exit 2), nicht "bestanden".
Die Probe-Sitzung wird am Ende geloescht (vorgefundener Zustand).

Seit BSI M5 nur ueber den Dienst-Wrapper (sonst gilt das Token nicht):
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_kb_auswahl_rueckfall_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import asyncio
import json
import os
import ssl
import sys

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402

try:
    import websockets  # noqa: E402
except ImportError:
    print("ABBRUCH: websockets fehlt")
    sys.exit(2)

from backend import main as M  # noqa: E402
from backend import chat_sessions as cs  # noqa: E402

BENUTZER = next((u for u in (ziele.finde("JARVIS_DEV_TESTUSER") or "", "jarvis") if u), "jarvis")
TOKEN = M.generate_token(BENUTZER)
URL = "wss://127.0.0.1/ws"
_KTX = ssl._create_unverified_context()
SPERRE = "Keine Wissensgruppen ausgewählt"
AUFTRAG = ("Rufe bitte genau einmal das Werkzeug knowledge_search mit query "
           "'Benutzerverwaltung' auf und nenne mir nur die erste Zeile des Ergebnisses.")

_ok = _fail = 0


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


async def lauf(sid, kb_feld, frist=240):
    """Ein Auftrag. ``kb_feld``: "fehlt" oder der zu sendende Wert."""
    ereignisse = []
    async with websockets.connect(URL, ssl=_KTX, max_size=None) as ws:
        msg = {"type": "task", "text": AUFTRAG, "token": TOKEN, "lang": "de",
               "bestaetigung": True, "session_id": sid}
        if kb_feld != "fehlt":
            msg["kb_groups"] = kb_feld
        await ws.send(json.dumps(msg))
        ende = asyncio.get_event_loop().time() + frist
        while asyncio.get_event_loop().time() < ende:
            try:
                roh = await asyncio.wait_for(ws.recv(), timeout=10)
            except asyncio.TimeoutError:
                continue
            m = json.loads(roh)
            if m.get("type") == "cpu":
                continue
            ereignisse.append(m)
            txt = str(m.get("message", ""))
            if m.get("type") == "status" and ("Aufgabe abgeschlossen" in txt or "Anfrage gestoppt" in txt):
                break
    return ereignisse


def werkzeug(ereignisse):
    """(rief knowledge_search?, Ergebniszeilen)"""
    st = [str(e.get("message", "")) for e in ereignisse if e.get("type") == "status"]
    gerufen = any(s.startswith("🔧 Tool: knowledge_search") for s in st)
    ergebnisse = [s for s in st if s.startswith("📋 Ergebnis")]
    return gerufen, ergebnisse


async def fall(name, sid, kb_feld):
    for versuch in range(1, 4):
        gerufen, erg = werkzeug(await lauf(sid, kb_feld))
        if gerufen and erg:
            print("  … %s: Werkzeug im Versuch %d aufgerufen" % (name, versuch))
            return erg
        print("  … %s: Versuch %d ohne Werkzeugaufruf – wiederhole" % (name, versuch))
    return None


async def main():
    sess = cs.create_session(BENUTZER, "Probe kb-Rueckfall")
    sid = sess["id"]
    try:
        cs.save_kb_groups(BENUTZER, sid, [])
        meta = cs.get_meta(BENUTZER, sid) or {}
        print("Benutzer: %s, Sitzung: %s, gespeichert: %r" % (BENUTZER, sid, meta.get("kb_groups")))
        if meta.get("kb_groups") != []:
            print("ABBRUCH: Auswahl der Probe-Sitzung steht nicht")
            return 2

        print("\n── A. Positivkontrolle: kb_groups ausdruecklich null")
        a = await fall("A", sid, None)
        if a is None:
            print("ABBRUCH: Modell ruft knowledge_search nicht auf – nicht gemessen")
            return 2
        check("A: keine Sperrmeldung (null = alle, die Nachricht entscheidet)",
              not any(SPERRE in e for e in a), a[0][:160])
        if _fail:
            print("ABBRUCH: Positivkontrolle verfehlt – B waere nicht deutbar")
            return 2

        print("\n── B. Feld fehlt (der gemeldete Weg)")
        b = await fall("B", sid, "fehlt")
        if b is None:
            print("ABBRUCH: Modell ruft knowledge_search nicht auf – nicht gemessen")
            return 2
        check("B: die gespeicherte Auswahl ([] = keine) kommt beim Werkzeug an",
              any(SPERRE in e for e in b), b[0][:160])

        print("\n── C. Gegenkontrolle der Sonde: kb_groups ausdruecklich []")
        c = await fall("C", sid, [])
        if c is None:
            print("ABBRUCH: Modell ruft knowledge_search nicht auf – nicht gemessen")
            return 2
        check("C: Sperrmeldung bei ausdruecklich leerer Auswahl", any(SPERRE in e for e in c), c[0][:160])
    finally:
        weg = cs.delete_session(BENUTZER, sid)
        print("\nProbe-Sitzung entfernt: %s" % weg)
        if not weg:
            print("  FAIL Probe-Sitzung %s liegt noch – bitte entfernen" % sid)

    print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
