"""Der Rueckweg aus einem zu engen Werkzeug-Zuschnitt.

Ohne dieses Werkzeug waere der aufgabenabhaengige Zuschnitt eine Einbahnstrasse:
liegt die Heuristik daneben, FEHLT dem Modell das noetige Werkzeug - und dann
sagt es erfahrungsgemaess nicht "ich habe es nicht", sondern erfindet eine
Begruendung und weicht auf ein schlechteres Ergebnis aus. Im Projekt mehrfach
belegt ("Die Base64-URL war zu lang", "matplotlib statt generate_image").

Es kostet einen Schritt - aber nur, wenn es wirklich gebraucht wird, und es
macht den Fehlgriff SICHTBAR: jeder Aufruf steht im Audit-Log und ist damit
die Messgrundlage dafuer, ob die Buendel richtig geschnitten sind.

⚠ ES GIBT KEINE RECHTE FREI. Der Zuschnitt kann ohnehin nur wegnehmen, was der
Auftraggeber schon hatte (``werkzeug_buendel.zuschnitt``); dieses Werkzeug
stellt genau diesen Stand wieder her - nicht mehr. Die harte Schranke bleibt
der Dispatch.
"""
from backend.tools.base import BaseTool


class WerkzeugeAnfordernTool(BaseTool):

    # Der Agent setzt das Flag; gelesen wird es in `_llm_tools`.
    ATTRIBUT = "_buendel_voll"

    def __init__(self, agent=None):
        self._agent = agent

    @property
    def name(self) -> str:
        return "werkzeuge_anfordern"

    @property
    def description(self) -> str:
        return ("Fordert den VOLLEN Werkzeugkasten an. Rufe das auf, wenn dir fuer "
                "die Aufgabe ein Werkzeug fehlt, das du hier nicht siehst - statt "
                "die Aufgabe abzulehnen oder auf einen schlechteren Weg auszuweichen. "
                "Ab dem naechsten Schritt stehen alle Werkzeuge zur Verfuegung, die "
                "du ohnehin benutzen duerftest. Es werden dadurch KEINE zusaetzlichen "
                "Rechte frei.")

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "grund": {
                    "type": "STRING",
                    "description": "Wofuer fehlt dir ein Werkzeug? Kurz, z.B. "
                                   "'Praesentation erzeugen' - dient der Auswertung.",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        grund = str(kwargs.get("grund") or "").strip()[:200]
        agent = self._agent
        if agent is None:
            return ("HINWEIS_AN_NUTZER: Der volle Werkzeugkasten konnte nicht "
                    "freigeschaltet werden (kein Agent-Bezug).")
        # ⚠ BEIDES: die ContextVar gilt lauf-lokal (ein paralleler Lauf darf sie
        # nicht sehen und nicht zuruecksetzen), das Attribut ist der Rueckfall
        # fuer Aufrufe ausserhalb eines actor_scope.
        setattr(agent, self.ATTRIBUT, True)
        try:
            from backend.agent import _buendel_voll_cv
            _buendel_voll_cv.set(True)
        except Exception:                                     # noqa: BLE001
            pass
        # ⚠ DER PROMPT MUSS MIT ZURUECK. Er wird EINMAL je Lauf gebaut, die
        # Werkzeugliste bei jedem Schritt neu - ohne dieses Signal bekaeme das
        # Modell zwar office_create_powerpoint zurueck, aber Punkt 16 (die
        # Hausvorlagen-Regeln) bliebe fuer den Rest des Laufs entfernt. Genau
        # diese Lage ist am 2026-09-01 schon einmal bezahlt worden.
        try:
            agent._buendel_prompt_neu = True
        except Exception:                                     # noqa: BLE001
            pass
        print(f"[Buendel] voller Werkzeugkasten angefordert: {grund or '(ohne Grund)'}",
              flush=True)
        return ("Der volle Werkzeugkasten steht ab dem naechsten Schritt zur "
                "Verfuegung. Fahre mit der Aufgabe fort und rufe das passende "
                "Werkzeug jetzt direkt auf.")
