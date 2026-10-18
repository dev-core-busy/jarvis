"""Gemeinsames Geheimnis zwischen Backend und WhatsApp-Bridge.

Code-Review 2026-10-18: die Bridge lauschte nur auf 127.0.0.1 und pruefte
sonst nichts. Jeder lokale Prozess konnte damit Nachrichten in fremdem Namen
senden, die Kopplung loeschen, das Adressbuch lesen – und ueber
``/send-media`` eine beliebige Datei (``.env``) an eine beliebige Nummer
schicken. Umgekehrt nahm ``/api/whatsapp/incoming`` von jedem lokalen
Prozess Auftraege "von einer freigegebenen Nummer" an. Die Grenze 127.0.0.1
trug nicht mehr, seit Agenten-Shell und Skills im selben Host laufen.

Das Geheimnis liegt in ``data/.wa_bridge_secret`` (0600, Dienstbenutzer):
die Sandbox-Konten der Domain-Benutzer koennen es nicht lesen. Wer zuerst
startet (Backend oder Bridge), legt es an (``O_EXCL`` – kein Wettlauf); die
Bridge liest dieselbe Datei (``services/whatsapp-bridge/index.js``).
"""
from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

PFAD = Path(__file__).resolve().parent.parent / "data" / ".wa_bridge_secret"
KOPF = "X-Jarvis-Bridge"
# Einziges Verzeichnis, aus dem der Webhook eine Sprachnachricht liest und
# danach LOESCHT (die Bridge legt sie dort ab).
SPRACH_DIR = "/tmp/jarvis_wa_voice"

_cache: str | None = None


def geheimnis() -> str:
    """Liefert das Geheimnis; legt es beim ersten Bedarf an."""
    global _cache
    if _cache:
        return _cache
    PFAD.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(PFAD, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    wert = PFAD.read_text(encoding="utf-8").strip()
    if len(wert) < 32:
        # Leer/abgeschnitten (Absturz mitten im Anlegen): neu schreiben statt
        # mit einem schwachen Wert weiterzuarbeiten.
        wert = secrets.token_hex(32)
        tmp = PFAD.with_name(PFAD.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(wert)
        os.replace(tmp, PFAD)
    _cache = wert
    return wert


def kopf() -> dict:
    """Kopfzeile fuer jede Anfrage an die Bridge."""
    try:
        return {KOPF: geheimnis()}
    except OSError as e:
        print(f"[WA] Bridge-Geheimnis nicht lesbar: {e}", flush=True)
        return {}


def pruefe(wert: str | None) -> bool:
    """Stimmt der mitgeschickte Wert? Zeitkonstant; ohne Geheimnis: nein."""
    try:
        soll = geheimnis()
    except OSError:
        return False
    return isinstance(wert, str) and bool(wert) and hmac.compare_digest(wert, soll)


def sprachdatei_erlaubt(pfad: str) -> bool:
    """Liegt ``pfad`` (nach Aufloesen aller Links) direkt in SPRACH_DIR?

    Der Webhook loescht die Datei nach der Transkription – ohne diese Schranke
    haette ein Pfad aus dem Anfragekoerper jede Datei geloescht, die der
    Dienst loeschen darf."""
    if not isinstance(pfad, str) or not pfad:
        return False
    try:
        echt = os.path.realpath(pfad)
    except (OSError, ValueError):
        return False
    return os.path.dirname(echt) == os.path.realpath(SPRACH_DIR) and os.path.isfile(echt)
