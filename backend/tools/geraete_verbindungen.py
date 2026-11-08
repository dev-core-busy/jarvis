"""Verbindungen zu Geraete-Clients (Windows-App, Android-App) JE BENUTZER.

Pentest-Befund C1 (2026-11-05): ``windows_desktop`` und ``android_desktop``
hielten EINE globale Verbindung. Die WebSocket-Nachricht ``register`` setzte sie
fuer jeden angemeldeten Benutzer – damit fuehrte Benutzer A ``shell_exec`` auf
dem PC von Benutzer B aus, oder A registrierte sich selbst, empfing fremde
``desktop_command``-Nachrichten und faelschte ``desktop_result``.

Jetzt gilt:

* Eine Verbindung gehoert dem Benutzer, der sie REGISTRIERT hat (Login-Token
  der registrierenden Nachricht, normalisiert wie ``main._norm_login``). Eine
  Registrierung mit Agent-Schluessel (ohne Benutzer) liegt unter dem leeren
  Schluessel – sie gehoert dem System, nicht einer Person.
* Ein Befehl geht NUR an den Client des Lauf-Akteurs (vom Dispatch zugewiesen,
  nie vom Modell). Den System-Client (leerer Schluessel) erreichen nur
  privilegierte Laeufe; ein unprivilegierter Lauf ohne Namen erreicht nichts.
* Ein Ergebnis wird nur von der Verbindung angenommen, an die der Befehl
  ging – Zuordnung ueber Befehls-ID UND Verbindung.
* Beim Trennen wird nur der Eintrag DIESER Verbindung entfernt; nur deren
  offene Befehle scheitern.
"""

from __future__ import annotations

import asyncio
import uuid


def norm_benutzer(name: str) -> str:
    """Gleiche Normalisierung wie ``main._norm_login`` (Domaene/UPN weg, klein)."""
    return (name or "").split("@")[0].split("\\")[-1].strip().lower()


class GeraeteVerbindungen:
    """Register ``benutzer -> ws`` plus offene Befehle ``id -> (future, ws)``."""

    def __init__(self, bezeichnung: str):
        self.bezeichnung = bezeichnung
        self._clients: dict[str, object] = {}
        self._offen: dict[str, tuple] = {}

    # ── Anmelden / Abmelden ──────────────────────────────────────────────
    def registrieren(self, ws, benutzer: str) -> str:
        schluessel = norm_benutzer(benutzer)
        alt = self._clients.get(schluessel)
        self._clients[schluessel] = ws
        if alt is not None and alt is not ws:
            # Neue Verbindung desselben Benutzers loest die alte ab – deren
            # offene Befehle bekommen keine Antwort mehr.
            self._offene_abbrechen(alt)
        print(f"[{self.bezeichnung}] Client verbunden fuer "
              f"'{schluessel or '(System-Schluessel)'}'", flush=True)
        return schluessel

    def trennen(self, ws) -> None:
        """Nur den Eintrag DIESER Verbindung entfernen."""
        for k in [k for k, v in self._clients.items() if v is ws]:
            self._clients.pop(k, None)
            print(f"[{self.bezeichnung}] Client getrennt fuer "
                  f"'{k or '(System-Schluessel)'}'", flush=True)
        self._offene_abbrechen(ws)

    def _offene_abbrechen(self, ws) -> None:
        for rid in [r for r, (_f, w) in self._offen.items() if w is ws]:
            fut, _w = self._offen.pop(rid)
            if not fut.done():
                fut.set_exception(ConnectionError(f"{self.bezeichnung}-Client getrennt"))

    # ── Abfragen ─────────────────────────────────────────────────────────
    def client_fuer(self, akteur: str, privilegiert: bool):
        """Die Verbindung, an die ein Befehl dieses Akteurs gehen darf – oder None."""
        schluessel = norm_benutzer(akteur)
        if schluessel:
            ws = self._clients.get(schluessel)
            if ws is not None:
                return ws
            # Privilegierter Benutzer (lokales Konto) ohne eigenen Client: der
            # System-Client (per Agent-Schluessel registriert) gehoert ihm.
            return self._clients.get("") if privilegiert else None
        # Ohne Namen: nur ein privilegierter Lauf (System) erreicht den
        # System-Client; ein unprivilegierter (z.B. Auftrag ohne Besitzer) nichts.
        return self._clients.get("") if privilegiert else None

    def verbunden(self, benutzer: str | None = None) -> bool:
        if benutzer is None:
            return bool(self._clients)
        return norm_benutzer(benutzer) in self._clients

    # ── Ergebnis ─────────────────────────────────────────────────────────
    def ergebnis(self, result: dict, ws) -> bool:
        """Ergebnis annehmen – nur von der Verbindung, an die der Befehl ging."""
        rid = str((result or {}).get("request_id", "") or "")
        eintrag = self._offen.get(rid)
        if eintrag is None:
            return False
        fut, ziel = eintrag
        if ziel is not ws:
            print(f"[{self.bezeichnung}] Ergebnis fuer Befehl {rid} von FREMDER "
                  "Verbindung verworfen", flush=True)
            return False
        self._offen.pop(rid, None)
        if not fut.done():
            fut.set_result(result)
        return True

    # ── Senden ───────────────────────────────────────────────────────────
    async def senden(self, ws, payload: dict, timeout: float = 30.0):
        """Befehl senden und auf das Ergebnis warten.

        Rueckgabe ``(ergebnis, fehlertext)`` – genau eines ist gesetzt.
        """
        rid = str(uuid.uuid4())[:8]
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._offen[rid] = (fut, ws)
        payload = dict(payload, request_id=rid)
        try:
            await ws.send_json(payload)
        except Exception as e:  # noqa: BLE001
            self._offen.pop(rid, None)
            return None, f"❌ Senden fehlgeschlagen: {e}"
        try:
            return await asyncio.wait_for(fut, timeout=timeout), None
        except asyncio.TimeoutError:
            self._offen.pop(rid, None)
            return None, (f"❌ Timeout: {self.bezeichnung}-Client hat nicht "
                          f"geantwortet ({int(timeout)}s)")
        except ConnectionError as e:
            return None, f"❌ Verbindung verloren: {e}"
