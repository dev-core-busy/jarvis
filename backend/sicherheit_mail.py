"""Sicherheitsverletzungen per E-Mail melden – Dienstseite.

Der Dienst darf selbst keine Mail abgeben (Postfix: ``authorized_submit_users =
root``, siehe ``backend/mail_meldung.py``). Er bittet den Broker darum
(``broker.mail_melden``); der baut den Text aus wenigen festen Feldern, prueft,
ob die Meldungsart eingeschaltet ist, und drosselt.

Gesendet werden NUR Metadaten – wer, Kanal, Art der Erkennung, Quelladresse –
nie ein Prompt, ein Befehl oder ein Ausschnitt: die Mail verlaesst den Server.
Damit gilt das auch fuer einen sensiblen Lauf (``backend/sensibel.py``): es
entsteht keine Senke mit Inhalt.

``melden`` kehrt sofort zurueck (Daemon-Thread mit Deckel): eine Sperre, die auf
einen langsamen Relay wartet, haelt sonst die Anfrage des Angreifers – und jede
andere – an.
"""
from __future__ import annotations

import threading

ARTEN = ("konto_gesperrt_angriff", "konto_gesperrt_verstoss", "konto_gesperrt_anmeldung",
         "spruehangriff", "angriff_protokolliert")
FELDER = ("benutzer", "kanal", "muster", "ip", "anzahl")


def _aufruf(args: dict) -> None:
    try:
        from backend import broker_client
        broker_client.call_sync("broker.mail_melden", args, user="sicherheit_mail", timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"[Sicherheit] Mail-Meldung nicht abgegeben: {e}", flush=True)


def melden(art: str, **felder) -> bool:
    """Meldung im Hintergrund abgeben. False = unbekannte Art (nichts getan)."""
    if art not in ARTEN:
        return False
    args = {"art": art}
    for f in FELDER:
        w = felder.get(f)
        if w not in (None, ""):
            args[f] = str(w)[:120]
    threading.Thread(target=_aufruf, args=(args,), daemon=True,
                     name="sicherheit-mail").start()
    return True
