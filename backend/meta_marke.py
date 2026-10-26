"""Meta-Angaben zwischen zwei U+2063 (INVISIBLE SEPARATOR).

GEMELDET 2026-10-26 von einem Docker-Anwender: ein vorgeschalteter Proxy
klammert Meta-Angaben einer Antwort (verbesserter Prompt, Eskalation,
Quellenliste) in das unsichtbare Zeichen U+2063. Im Chat stoert das nicht, die
Marke ist unsichtbar. Zwei Stellen lasen den Inhalt aber als Antwort:

  * die Sprachausgabe las ihn vor ("[Prompt optimiert] ..."),
  * die Download-Erkennung hielt Dateinamen aus der Quellenliste fuer
    behauptete Ergebnisdateien und meldete sie als nicht bereitstellbar.

Bewusst EINE Quelle fuer die Regel: Web (/api/tts) und Auslieferung benutzen
diese Funktion, die Android-App spiegelt sie in ``VorleseText.kt``.

Ein EINZELNES Zeichen ohne Gegenstueck entfernt nur sich selbst. Den Rest der
Antwort bis zum Ende zu verschlucken waere bei einem abgeschnittenen Block
schlimmer als ein vorgelesener Meta-Rest – der Benutzer hoerte dann gar nichts.
"""

from __future__ import annotations

import re

MARKE = "⁣"
_BLOCK = re.compile(MARKE + "[^" + MARKE + "]*" + MARKE)


def ohne_meta(text: str, ersatz: str = " ") -> str:
    """``text`` ohne die Bloecke zwischen zwei Marken und ohne lose Marken."""
    if not text or MARKE not in text:
        return text or ""
    return _BLOCK.sub(ersatz, text).replace(MARKE, "")
