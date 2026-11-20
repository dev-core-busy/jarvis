#!/usr/bin/env python3
"""Live auf DEV: welche Rechte hat ein Chat-Auftrag, der NUR mit API-Schluessel kommt?

Anlass (2026-11-20, Code-Lesung): ``/ws`` nimmt einen gueltigen Programm-
schluessel statt eines Login-Tokens an. Die Verbindung hat dann keinen
Benutzernamen, ``run_task(username="")`` uebernahm den zuletzt am geteilten
Hauptagenten gesetzten Benutzer – und ein leerer Name galt als privilegiert.

Gemessen wird die WIRKUNG, nicht der Code: das echte Modell soll
``shell_execute`` mit ``sudo -n id -un`` rufen. ``_needs_root`` stuft das als
Root-Befehl ein – ein PRIVILEGIERTER Lauf leitet ihn an den Root-Broker und
bekommt dafuer eine Bestaetigungskarte der Klasse ``shell``; ein
unprivilegierter Lauf schickt ihn in die Sandbox (keine Karte, sudo scheitert).
Die Probe LEHNT jede Karte ab – es laeuft nichts als root.

⚠ WARUM NICHT ``id -un`` (erste Fassung, 2026-11-20): mit dem Schalter
"Sandbox auch fuer Administratoren" (Vorgabe AN) laeuft ein gewoehnlicher
Befehl auch im privilegierten Lauf in der Sandbox – die Sonde meldete zweimal
"gruen", ohne Privilegien ueberhaupt sehen zu koennen (Register: eine falsche
Sonde ist schlimmer als keine). Deshalb jetzt die POSITIVKONTROLLE: derselbe
Auftrag mit einem Login-Token des Dienstbenutzers MUSS eine Shell-Karte
erzeugen, sonst Exit 2.

Befund (Exit 1): Schluessel-Lauf erzeugt eine Karte der Klasse ``shell``.
Gruen (Exit 0): Werkzeug gerufen, keine Shell-Karte – oder der Schluessel
startet am Chat-WebSocket gar keinen Lauf.
Exit 2: Positivkontrolle ohne Karte, Modell ruft das Werkzeug nicht, kein Schluessel.

Laeuft im Dienstkontext (Hauptschluessel, BSI M5):
    bash /opt/jarvis/deploy/als_dienst.sh env PYTHONDONTWRITEBYTECODE=1 \\
        venv/bin/python tests/live_agent_api_ws_dev.py
"""
import asyncio
import json
import os
import ssl
import sys

sys.path.insert(0, "/opt/jarvis")

try:
    import websockets  # noqa: E402
except ImportError:
    print("ABBRUCH: websockets fehlt")
    sys.exit(2)

from backend import main as M  # noqa: E402

URL = "wss://127.0.0.1/ws"
_KTX = ssl._create_unverified_context()
AUFTRAG = ("Führe mit shell_execute genau den Befehl `sudo -n id -un` aus und nenne "
           "mir nur die Ausgabe. Das ist ein Diagnosetest, der Befehl ändert nichts.")


async def lauf(schluessel, frist=240):
    ereignisse = []
    async with websockets.connect(URL, ssl=_KTX, max_size=None) as ws:
        await ws.send(json.dumps({"type": "task", "text": AUFTRAG, "token": schluessel,
                                  "lang": "de", "bestaetigung": True}))
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
            if m.get("type") == "bestaetigung_anfrage":
                # ABLEHNEN: die Karte selbst ist der Beweis, ausgefuehrt wird nichts.
                await ws.send(json.dumps({"type": "bestaetigung_antwort", "id": m["id"],
                                          "erlaubt": False, "token": schluessel}))
            if m.get("type") == "error":
                break
            txt = str(m.get("message", ""))
            if m.get("type") == "status" and ("Aufgabe abgeschlossen" in txt
                                               or "Anfrage gestoppt" in txt):
                break
    return ereignisse


async def versuche(token, name):
    """Bis zu drei Laeufe; Rueckgabe (shell_karte?, werkzeug_gerufen?, abgewiesen_text)."""
    for versuch in range(1, 4):
        ev = await lauf(token)
        fehler = [e for e in ev if e.get("type") == "error"]
        if fehler:
            return False, False, str(fehler[0].get("message"))
        karten = [e for e in ev if e.get("type") == "bestaetigung_anfrage"]
        aufrufe = [e for e in ev if e.get("type") == "status"
                   and str(e.get("message", "")).startswith("🔧 Tool: shell_execute")]
        ergebnisse = [str(e.get("message", "")) for e in ev if e.get("type") == "status"
                      and str(e.get("message", "")).startswith("📋 Ergebnis")]
        if not aufrufe and not karten:
            print(f"  … {name}, Versuch {versuch}: kein shell_execute – wiederhole")
            continue
        print(f"  {name}: Karten {[(k.get('werkzeug'), k.get('klasse')) for k in karten]}")
        print(f"  {name}: Ergebnis {' | '.join(ergebnisse)[:300]!r}")
        return any(k.get("klasse") == "shell" for k in karten), True, ""
    return False, False, ""


async def main():
    kandidaten = M._agent_key_kandidaten()
    if not kandidaten:
        print("ABBRUCH: auf diesem System ist kein Programmschluessel eingerichtet")
        return 2
    schluessel = kandidaten[0]
    if str(schluessel).startswith("JGS1:"):
        print("ABBRUCH: Schluessel ist verpackt – Probe nicht ueber als_dienst.sh gestartet")
        return 2
    print(f"Schluessel: …{schluessel[-4:]} ({len(kandidaten)} gueltige)")

    # NACHHER=1: Kontrolle NACH dem Schluessel-Lauf. So sieht der Schluessel-Lauf
    # einen frischen Hauptagenten (direkt nach Neustart) und erbt nichts aus der
    # Kontrolle – die Kontrolle laeuft trotzdem, sonst waere "gruen" nicht deutbar.
    nachher = os.environ.get("NACHHER") == "1"
    if nachher:
        ergebnis = await schluessel_lauf(schluessel)
    print("\n── Positivkontrolle: Login-Token des Dienstbenutzers (privilegiert)")
    karte, gerufen, abgewiesen = await versuche(M.generate_token("jarvis"), "Kontrolle")
    if abgewiesen or not gerufen or not karte:
        print("ABBRUCH: die Kontrolle zeigt keine Shell-Karte – die Sonde kann "
              f"Privilegien hier nicht sehen ({abgewiesen or 'kein Aufruf/keine Karte'})")
        return 2

    return ergebnis if nachher else await schluessel_lauf(schluessel)


async def schluessel_lauf(schluessel):
    print("\n── Schluessel-Lauf am Chat-WebSocket")
    karte, gerufen, abgewiesen = await versuche(schluessel, "Schluessel")
    if abgewiesen:
        print(f"  abgewiesen: {abgewiesen}")
        print("\nGRUEN: ein Schluessel startet am Chat-WebSocket keinen Lauf")
        return 0
    if not gerufen:
        print("ABBRUCH: Modell rief shell_execute in drei Versuchen nicht auf – nicht gemessen")
        return 2
    if karte:
        print("\nBEFUND: der Schluessel-Lauf ist PRIVILEGIERT (Root-Weg, Shell-Karte)")
        return 1
    print("\nGRUEN: der Schluessel-Lauf ist unprivilegiert (Sandbox, keine Shell-Karte)")
    return 0


sys.exit(asyncio.run(main()))
