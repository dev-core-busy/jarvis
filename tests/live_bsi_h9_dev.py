#!/usr/bin/env python3
"""Live auf DEV: Bestaetigung vor Loeschwirkung ueber den ECHTEN Chat-WebSocket (BSI H9).

Laeuft AUF DEV (``/opt/jarvis``), spricht ``wss://127.0.0.1/ws`` wie der
Browser-Chat und laesst das echte Modell ein Werkzeug mit Loeschwirkung
aufrufen: ``memory_manage(action='delete')`` auf einen Schluessel, den es nicht
gibt – die Probe veraendert damit nichts, auch wenn die Aktion freigegeben wird.
Kein Skill-Schalter und keine Einstellung wird angefasst.

Drei Faelle, je bis zu drei Versuche (eine Modellantwort ist erst nach
Wiederholung eine Messung; ruft das Modell das Werkzeug gar nicht, ist das
"nicht gemessen", nicht "bestanden"):

1. Browser-Chat, Klick "Ablehnen"  -> Karte kommt, Ergebnis "ABGELEHNT".
2. Browser-Chat, Klick "Ausfuehren" -> Karte kommt, Werkzeug laeuft.
3. Client ohne Dialog (keine Angabe ``bestaetigung``) -> keine Karte,
   Ergebnis "NICHT AUSGEFÜHRT".

H8 misst ``tests/live_bsi_h8_dev.py`` an der Leitung. Eine Modellantwort
("nenne die erste Zeile des Werkzeugergebnisses") war dafuer die falsche Sonde:
das Modell nannte am 2026-10-04 die erste INHALTSzeile, nicht den Rahmen.

    PYTHONDONTWRITEBYTECODE=1 /opt/jarvis/venv/bin/python tests/live_bsi_h9_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import asyncio
import json
import os
import secrets
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

BENUTZER = next((u for u in (ziele.finde("JARVIS_DEV_TESTUSER") or "", "jarvis") if u), "jarvis")
TOKEN = M.generate_token(BENUTZER)
URL = "wss://127.0.0.1/ws"
_KTX = ssl._create_unverified_context()

_ok = _fail = 0


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


async def lauf(auftrag, *, bestaetigung, klick=None, frist=240):
    """Ein Chat-Auftrag. ``klick``: True/False = so auf die Karte antworten."""
    ereignisse = []
    async with websockets.connect(URL, ssl=_KTX, max_size=None) as ws:
        msg = {"type": "task", "text": auftrag, "token": TOKEN, "lang": "de"}
        if bestaetigung:
            msg["bestaetigung"] = True
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
            if m.get("type") == "bestaetigung_anfrage" and klick is not None:
                await ws.send(json.dumps({"type": "bestaetigung_antwort", "id": m["id"],
                                          "erlaubt": klick, "token": TOKEN}))
            txt = str(m.get("message", ""))
            if m.get("type") == "status" and ("Aufgabe abgeschlossen" in txt
                                               or "Anfrage gestoppt" in txt):
                break
    return ereignisse


def auswertung(ereignisse):
    anfragen = [e for e in ereignisse if e.get("type") == "bestaetigung_anfrage"]
    quittungen = [e for e in ereignisse if e.get("type") == "bestaetigung_erledigt"]
    aufrufe = [str(e.get("message", "")) for e in ereignisse
               if e.get("type") == "status" and str(e.get("message", "")).startswith("🔧 Tool: memory_manage")]
    ergebnisse = [str(e.get("message", "")) for e in ereignisse
                  if e.get("type") == "status" and str(e.get("message", "")).startswith("📋 Ergebnis")]
    antwort = " ".join(str(e.get("message", "")) for e in ereignisse
                       if e.get("type") == "status" and e.get("highlight"))
    return anfragen, quittungen, aufrufe, ergebnisse, antwort


SCHLUESSEL = "h9probe_" + secrets.token_hex(3)
AUFTRAG = (f"Lösche bitte mit memory_manage den Gedächtniseintrag '{SCHLUESSEL}' "
           "(action='delete') und sag mir, was dabei herauskam.")


async def fall(name, *, bestaetigung, klick):
    for versuch in range(1, 4):
        ev = await lauf(AUFTRAG, bestaetigung=bestaetigung, klick=klick)
        anf, qu, auf, erg, antw = auswertung(ev)
        if auf:
            print(f"  … {name}: Werkzeug im Versuch {versuch} aufgerufen")
            return anf, qu, auf, erg, antw
        print(f"  … {name}: Versuch {versuch} ohne Werkzeugaufruf – wiederhole")
    return None


async def main():
    print(f"Benutzer: {BENUTZER}, Schluessel: {SCHLUESSEL}")

    print("\n── 1. Browser-Chat, Ablehnen")
    r = await fall("ablehnen", bestaetigung=True, klick=False)
    if r is None:
        print("ABBRUCH: Modell ruft memory_manage nicht auf – nicht gemessen")
        return 2
    anf, qu, auf, erg, antw = r
    check("Karte kommt beim Browser an", len(anf) == 1, str(len(anf)))
    if anf:
        a = anf[0]
        check("Karte: Werkzeug memory_manage, Klasse loeschen",
              a.get("werkzeug") == "memory_manage" and a.get("klasse") == "loeschen", str(a)[:160])
        check("Karte nennt den Schluessel",
              any(SCHLUESSEL in str(v) for _, v in a.get("argumente") or []), str(a.get("argumente")))
    check("Quittung 'abgelehnt'", any(q.get("grund") == "abgelehnt" for q in qu), str(qu))
    check("Werkzeugergebnis ist ABGELEHNT", any("ABGELEHNT" in e for e in erg), str(erg)[:200])

    print("\n── 2. Browser-Chat, Ausfuehren")
    r = await fall("ausfuehren", bestaetigung=True, klick=True)
    if r is None:
        print("ABBRUCH: Modell ruft memory_manage nicht auf – nicht gemessen")
        return 2
    anf, qu, auf, erg, antw = r
    check("Karte kommt", len(anf) == 1, str(len(anf)))
    check("Quittung 'erlaubt'", any(q.get("grund") == "erlaubt" for q in qu), str(qu))
    check("Werkzeug lief (Ergebnis ohne ABGELEHNT/NICHT AUSGEFÜHRT)",
          erg and not any("ABGELEHNT" in e or "NICHT AUSGEFÜHRT" in e for e in erg), str(erg)[:200])

    print("\n── 3. Client ohne Dialog (App)")
    r = await fall("app", bestaetigung=False, klick=None)
    if r is None:
        print("ABBRUCH: Modell ruft memory_manage nicht auf – nicht gemessen")
        return 2
    anf, qu, auf, erg, antw = r
    check("keine Karte an einen Client ohne Dialog", len(anf) == 0, str(len(anf)))
    check("Werkzeugergebnis ist NICHT AUSGEFÜHRT", any("NICHT AUSGEFÜHRT" in e for e in erg), str(erg)[:200])

    print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
    return 0 if _fail == 0 else 1


sys.exit(asyncio.run(main()))
