"""Anmeldung fuer die Sitzung: ein Token, der NUR im Arbeitsspeicher liegt.

Gebraucht von ``jira_accounts`` und ``confluence_accounts``, wenn der
Administrator "Persoenliche Zugaenge erlauben" ABGESCHALTET hat (Vorgabe des
Betreibers 2026-11-15): dann darf kein persoenlicher Token auf der Platte
liegen, der Benutzer kann sich aber bei der Anmeldung an Jarvis (oder im
Bereich selbst) fuer die Sitzung anmelden – Bauart wie die Anmeldung ueber die
Portal-Kachel bei SAP/VEMAS (``sap_accounts._SITZUNG``).

EINE Klasse statt zweier Kopien: Jira und Confluence muessen sich hier gleich
verhalten (Laufzeit, Ablauf, Abmelden). Zwei Fassungen liefen beim naechsten
Feinschliff auseinander.

EIN PROZESS: uvicorn laeuft ohne ``--workers`` (siehe main.py), der Speicher
ist deshalb ein schlichtes dict hinter einer Sperre. Ein Dienstneustart meldet
alle ab – gewollt, nichts davon darf die Platte erreichen.
"""

from __future__ import annotations

import threading
import time

LAUFZEIT_S = 12 * 3600          # wie SAP/VEMAS: danach erneut anmelden


class SitzungsSpeicher:
    """benutzer_norm -> {"token", "bis", "anzeigename", "konto"}"""

    def __init__(self, laufzeit_s: int = LAUFZEIT_S):
        self._laufzeit = int(laufzeit_s)
        self._daten: dict = {}
        self._sperre = threading.Lock()

    def _gueltig(self, un: str) -> dict:
        """Eintrag oder {} – ein abgelaufener wird dabei verworfen."""
        s = self._daten.get(un)
        if not s:
            return {}
        if float(s.get("bis") or 0) < time.time():
            self._daten.pop(un, None)
            return {}
        return s

    def setzen(self, un: str, token: str, anzeigename: str = "",
               konto: str = "") -> int:
        """Anmelden. Rueckgabe: Ablaufzeitpunkt (Unix-Zeit)."""
        if not un or not token:
            raise ValueError("Benutzer und Token sind Pflicht.")
        bis = int(time.time() + self._laufzeit)
        with self._sperre:
            self._daten[un] = {"token": token, "bis": bis,
                               "anzeigename": anzeigename or "",
                               "konto": konto or ""}
        return bis

    def token(self, un: str) -> str:
        with self._sperre:
            return str(self._gueltig(un).get("token") or "")

    def info(self, un: str) -> dict:
        """Fuer die Oberflaeche – OHNE Token."""
        with self._sperre:
            s = self._gueltig(un)
            if not s:
                return {"angemeldet": False, "sitzung_bis": 0,
                        "sitzung_anzeigename": "", "sitzung_konto": ""}
            return {"angemeldet": True, "sitzung_bis": int(s.get("bis") or 0),
                    "sitzung_anzeigename": s.get("anzeigename") or "",
                    "sitzung_konto": s.get("konto") or ""}

    def beenden(self, un: str) -> bool:
        with self._sperre:
            return self._daten.pop(un, None) is not None

    def leeren(self) -> int:
        with self._sperre:
            n = len(self._daten)
            self._daten.clear()
            return n


__all__ = ["SitzungsSpeicher", "LAUFZEIT_S"]
