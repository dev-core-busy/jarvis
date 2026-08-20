"""Werkzeug ``excel_vorschlag`` – Zellaenderungen fuer das Excel-Add-in sammeln.

**Dieses Werkzeug schreibt NICHTS.** Es nimmt die vom Modell vorgeschlagenen
Zellaenderungen entgegen, prueft sie (``excel_ask.aenderungen_pruefen``) und
legt sie in der Sammelliste des laufenden Auftrags ab. Geschrieben wird
ausschliesslich im Aufgabenfenster, nachdem der Benutzer sie in einer
Diff-Ansicht gesehen und bestaetigt hat.

WARUM EIN WERKZEUG UND KEIN JSON-BLOCK IN DER ANTWORT
------------------------------------------------------
Ein Block im Antworttext waere die naheliegende Alternative und ist die
schlechtere: er muesste aus Prosa herausgeschnitten werden, das Modell
formatiert ihn mal mit und mal ohne Codezaun, und ein Tippfehler im JSON
bleibt bis zur Anzeige unbemerkt. Ein Werkzeug hat ein Schema, das Modell
kennt die Feldnamen, und die Pruefung laeuft, bevor irgendetwas beim Benutzer
ankommt – **das Modell bekommt den Ablehnungsgrund zurueck und kann im selben
Lauf korrigieren.** Genau das ist der Vorteil, den ein Textblock nicht hat.

Das Werkzeug liegt im allgemeinen Werkzeugkasten (``_attach_extra_tools``),
ist aber nur innerhalb eines Excel-Laufs wirksam: ausserhalb gibt es keine
Sammelliste, und es sagt das im Klartext, statt stillschweigend ins Leere zu
schreiben.
"""

from __future__ import annotations

import json

from backend.tools.base import BaseTool
from backend import excel_ask


class ExcelVorschlagTool(BaseTool):
    """Schlaegt Aenderungen an der im Add-in geoeffneten Arbeitsmappe vor."""

    @property
    def name(self) -> str:
        return "excel_vorschlag"

    @property
    def description(self) -> str:
        return (
            "Schlägt Änderungen an der Arbeitsmappe vor, die der Benutzer "
            "gerade in Excel geöffnet hat. NUR im Excel-Aufgabenfenster "
            "verwendbar. Das Werkzeug schreibt nichts – der Benutzer sieht "
            "jede Zelle mit altem und neuem Inhalt und bestätigt selbst. "
            "Formeln in ENGLISCHER Schreibweise mit Komma als Trennzeichen "
            "(=SUM(A1:A10), =IF(B2>0,B2*0.19,0)); Excel übersetzt sie in die "
            "Sprache des Benutzers. Mehrere Zellen in EINEM Aufruf übergeben, "
            "nicht in mehreren."
        )

    def parameters_schema(self) -> dict:
        # Gemini-Schreibweise (OBJECT/ARRAY/STRING) wie im uebrigen Projekt –
        # ``llm._normalize_schema`` senkt sie fuer OpenAI-kompatible Server
        # (Fix 2026-08-17: ein strenger Server lehnt "OBJECT" mit 400 ab).
        return {
            "type": "OBJECT",
            "properties": {
                "aenderungen": {
                    "type": "ARRAY",
                    "description": "Liste der Zellen, die geändert werden sollen.",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "blatt": {
                                "type": "STRING",
                                "description": "Name des Tabellenblatts. Leer "
                                               "lassen für das aktive Blatt.",
                            },
                            "adresse": {
                                "type": "STRING",
                                "description": "Zelle oder Bereich in "
                                               "A1-Schreibweise, z. B. B7 oder "
                                               "B7:D20. OHNE Blattnamen.",
                            },
                            "formel": {
                                "type": "STRING",
                                "description": "Formel in englischer "
                                               "Schreibweise, beginnend mit =. "
                                               "Entweder formel ODER wert.",
                            },
                            "wert": {
                                "type": "STRING",
                                "description": "Fester Wert (Text oder Zahl), "
                                               "wenn keine Formel gebraucht wird.",
                            },
                            "begruendung": {
                                "type": "STRING",
                                "description": "Ein kurzer Satz, was der Eintrag "
                                               "bewirkt. Wird dem Benutzer neben "
                                               "der Zelle angezeigt.",
                            },
                        },
                        "required": ["adresse"],
                    },
                },
                "zusammenfassung": {
                    "type": "STRING",
                    "description": "Ein Satz über den Vorschlag als Ganzes.",
                },
            },
            "required": ["aenderungen"],
        }

    async def execute(self, **kwargs) -> str:
        puffer = excel_ask.puffer()
        if puffer is None:
            # Das Werkzeug liegt im allgemeinen Kasten und kann deshalb auch im
            # normalen Chat aufgerufen werden. Dort gibt es keine geoeffnete
            # Mappe – das ist kein Fehler, sondern der falsche Ort.
            return ("HINWEIS_AN_NUTZER: Dieses Werkzeug wirkt nur im "
                    "Excel-Aufgabenfenster. Hier gibt es keine geöffnete "
                    "Arbeitsmappe. Für Änderungen an einer Datei sind "
                    "xlsx_edit und xlsx_merge zuständig.")

        roh = kwargs.get("aenderungen")
        # Modelle liefern verschachtelte Argumente gelegentlich als JSON-STRING
        # statt als Liste. Das tolerant zu parsen ist kein Luxus: die harte
        # Variante endet in "keine Änderungen übergeben", obwohl das Modell
        # alles richtig gemeint hat (dieselbe Lehre wie bei xlsx_merge).
        if isinstance(roh, str):
            try:
                roh = json.loads(roh)
            except Exception:  # noqa: BLE001
                return ("Fehler: 'aenderungen' konnte nicht gelesen werden – "
                        "erwartet wird eine Liste von Objekten mit den Feldern "
                        "adresse und formel bzw. wert.")
        if isinstance(roh, dict):
            roh = [roh]          # eine einzelne Aenderung, nicht eingepackt
        if not isinstance(roh, list) or not roh:
            return ("Fehler: Es wurden keine Änderungen übergeben. Erwartet "
                    "wird eine Liste von Objekten mit adresse und formel/wert.")

        gueltig, abgelehnt = excel_ask.aenderungen_pruefen(roh)

        # AUCH die abgelehnten wandern in den Puffer, nicht nur die gueltigen:
        # der Benutzer muss erfahren, dass etwas aussortiert wurde. Sonst sieht
        # er drei statt fuenf Zellen und haelt das fuer den ganzen Vorschlag –
        # dasselbe stille Verschlucken, das die Pruefung verhindern soll.
        if gueltig or abgelehnt:
            puffer.append({
                "aenderungen": gueltig,
                "abgelehnt": abgelehnt,
                "zusammenfassung": str(kwargs.get("zusammenfassung") or "")[:400],
            })

        zeilen = []
        if gueltig:
            zeilen.append("%d Änderung(en) vorgemerkt. Der Benutzer sieht sie "
                          "jetzt zur Bestätigung; du musst nichts weiter tun "
                          "und darfst sie NICHT zusätzlich als Text ausgeben."
                          % len(gueltig))
        if abgelehnt:
            # Der Grund geht ausdruecklich an das Modell zurueck – es kann im
            # selben Lauf korrigieren. Das ist der Zweck der Pruefung an dieser
            # Stelle.
            zeilen.append("%d Eintrag/Einträge wurden ABGELEHNT:" % len(abgelehnt))
            for a in abgelehnt[:20]:
                ort = a.get("adresse") or "(ohne Adresse)"
                if a.get("blatt"):
                    ort = "%s!%s" % (a["blatt"], ort)
                zeilen.append("  - %s: %s" % (ort, a.get("grund", "")))
            if not gueltig:
                zeilen.append("Es wurde nichts vorgemerkt. Korrigiere die "
                              "Einträge und rufe das Werkzeug erneut auf.")
        return "\n".join(zeilen)
