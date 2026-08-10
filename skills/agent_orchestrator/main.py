"""Agent Orchestrator – Delegation an spezialisierte Rollen-Agenten.

WAS DIESER SKILL BEREITSTELLT
-----------------------------
Ein Werkzeug: ``delegate(role, task)``. Der Hauptagent gibt damit eine
Teilaufgabe an einen vom Administrator definierten Rollen-Agenten (eigener
Prompt, eigener Werkzeugsatz, optional eigenes LLM-Profil), **wartet** auf das
Ergebnis und arbeitet damit weiter. Verwaltet werden die Rollen unter
*Einstellungen → Orchestrator*; die Registry liegt in ``backend/agent_roles.py``.

WARUM DAS EIN SKILL IST
-----------------------
Ohne aktiven Skill liefert ``get_tools()`` nichts – dann gibt es kein
``delegate``, keinen Rollen-Abschnitt im System-Prompt und keinen Rollen-Rückfall
bei gescheiterten Werkzeugen (``agent.py`` prüft dafür, ob das Werkzeug im
Kasten liegt, nicht den Skill-Namen). Der Agent verhält sich dann exakt wie
vorher. Einschalten = mehr Funktion, Ausschalten = zurück auf Anfang.

WAS HIER VORHER STAND (bis 2026-08-10)
--------------------------------------
Ein OpenClaw-Import mit vier Werkzeugen (``orchestrate_task``, ``agent_status``,
``agent_collect``, ``agent_list``), die **Verzeichnisse anlegten und wieder
einlasen** – ``agent-workspaces/<session>/<agent>/{inbox,outbox,status.json}``.
Sie starteten keinen Agenten: der Hauptagent sollte jede „Sub-Agenten"-Rolle
selbst nacheinander abarbeiten, das Feld ``depends_on`` wurde nirgends
ausgewertet, und die sechs „Agent-Typen" waren sechs Beschreibungssätze ohne
Wirkung auf Werkzeuge, Rechte oder Modell. Der Skill war nie aktiviert und
hatte im ganzen Repo keinen Aufrufer. Das Protokoll ist durch echte Rollen
ersetzt; wer die alte Dateiablage sucht, findet sie in der Git-Historie.

MIGRATION: Ein früher angelegtes ``data/agent-workspaces/`` wird NICHT
angetastet und NICHT gelöscht – es enthält möglicherweise Arbeitsergebnisse.
"""

from backend.tools.base import BaseTool


# ─── Vorgabe-Rollen ──────────────────────────────────────────────────────────
# Beim Laden des Skills gesät (also beim Einschalten bzw. beim ersten Start mit
# aktivem Skill) und nur, wenn data/agent_roles.json noch nicht existiert – eine
# bewusst gelöschte Rolle darf nicht bei jedem Neustart zurückkommen.
def _saeen_still() -> None:
    try:
        from backend import agent_roles
        agent_roles.saeen()
    except Exception as e:  # noqa: BLE001
        # Kein Grund, den Skill scheitern zu lassen: ohne Rollen wird `delegate`
        # gar nicht angeboten (agent.py::_llm_tools filtert es dann heraus).
        print(f"[Rollen] Vorgabe-Rollen nicht angelegt: {e}", flush=True)


class DelegateTool(BaseTool):
    """Übergibt eine Teilaufgabe an eine vom Administrator definierte Rolle.

    WIE ES LÄUFT (Marker-Muster wie spawn_agent / create_chart)
    -----------------------------------------------------------
    Ein Werkzeug kann selbst keinen Agenten starten (der AgentManager lebt in
    ``backend.main``, ein Import hier wäre ein Zirkel). Deshalb gibt ``execute()``
    nur einen Marker zurück; ``agent.py`` erkennt ihn direkt nach dem
    Werkzeug-Aufruf, führt den Rollen-Lauf SEQUENZIELL aus (``await``) und
    ersetzt das Werkzeug-Ergebnis durch die Antwort der Rolle. Der Orchestrator
    sieht also das Ergebnis, nicht den Marker – anders als bei ``spawn_agent``,
    das nur "gestartet" meldet und das Ergebnis nie zurückgibt.

    WARUM DIE PRÜFUNG SCHON HIER PASSIERT
    -------------------------------------
    Unbekannte oder abgeschaltete Rolle = Fehlermeldung MIT der Liste der
    verfügbaren Rollen, und es wird gar kein Lauf gestartet. Das Modell kann sich
    im selben Schritt korrigieren (gleiche Überlegung wie beim Repair-Loop von
    ``create_chart`` und bei "Anhang nicht gefunden", das die vorhandenen Namen
    nennt).
    """

    @property
    def name(self) -> str:
        return "delegate"

    @property
    def description(self) -> str:
        # Dynamisch: die Rollenliste wird bei JEDEM Provider-Aufruf neu gelesen
        # (llm.py liest `t.description` pro Anfrage). Eine neu angelegte Rolle
        # ist damit sofort bekannt, ohne Dienst-Neustart.
        from backend import agent_roles

        try:
            liste = agent_roles.werkzeug_beschreibung()
        except Exception:  # noqa: BLE001
            liste = ""

        if not liste:
            return (
                "Uebergibt eine Teilaufgabe an einen spezialisierten Rollen-Agenten. "
                "DERZEIT IST KEINE ROLLE EINGERICHTET – benutze dieses Werkzeug nicht, "
                "sondern erledige die Aufgabe selbst."
            )

        return (
            "Uebergibt eine Teilaufgabe an einen spezialisierten Rollen-Agenten und "
            "gibt DESSEN ERGEBNIS zurueck (du wartest darauf und arbeitest damit weiter).\n"
            "Benutze eine Rolle, wenn sie fuer die Aufgabe eindeutig zustaendig ist – "
            "sie hat einen eigenen Werkzeugsatz und oft ein besser geeignetes Modell. "
            "Fuer alles andere arbeite selbst weiter; delegiere NICHT die ganze Anfrage "
            "und nicht mehrfach dasselbe.\n"
            "Formuliere im 'task' eine vollstaendige, fuer sich verstaendliche Anweisung: "
            "die Rolle sieht das Gespraech NICHT, nur diesen Text.\n\n"
            "Verfuegbare Rollen:\n" + liste
        )

    def parameters_schema(self) -> dict:
        from backend import agent_roles

        try:
            ids = agent_roles.namen(nur_aktive=True)
        except Exception:  # noqa: BLE001
            ids = []
        rolle_schema: dict = {
            "type": "STRING",
            "description": "Kennung der Rolle, z.B. 'analyst'",
        }
        # Als Enum, wenn Rollen da sind: das haelt das Modell davon ab, sich eine
        # Rolle auszudenken. Bei leerer Liste KEIN leeres Enum – manche Provider
        # lehnen das mit HTTP 400 ab.
        if ids:
            rolle_schema["enum"] = ids
        return {
            "type": "OBJECT",
            "properties": {
                "role": rolle_schema,
                "task": {
                    "type": "STRING",
                    "description": (
                        "Die vollstaendige Teilaufgabe fuer die Rolle. Muss ohne "
                        "Gespraechskontext verstaendlich sein (Dateipfade, Zahlen, "
                        "Rahmenbedingungen mitgeben)."
                    ),
                },
            },
            "required": ["role", "task"],
        }

    async def execute(self, role: str = "", task: str = "", **kwargs) -> str:
        import json

        from backend import agent_roles

        # Fehlertolerant: Modelle benennen die Felder gern anders.
        if not role:
            role = kwargs.get("agent") or kwargs.get("name") or kwargs.get("rolle") or ""
        if not task:
            task = (kwargs.get("prompt") or kwargs.get("auftrag")
                    or kwargs.get("instruction") or kwargs.get("aufgabe") or "")

        role = str(role).strip().lower()
        task = str(task).strip()

        try:
            aktive = agent_roles.alle(nur_aktive=True)
        except Exception as e:  # noqa: BLE001
            return f"Fehler: Rollen sind nicht lesbar ({e})."

        if not aktive:
            return ("Fehler: Es ist keine Rolle eingerichtet. Erledige die Aufgabe "
                    "selbst (Rollen legt ein Administrator unter Einstellungen an).")

        def _liste() -> str:
            return ", ".join(f"'{r['id']}'" for r in aktive)

        if not role:
            return f"Fehler: 'role' fehlt. Verfuegbar: {_liste()}."
        if not task:
            return ("Fehler: 'task' fehlt – die Rolle sieht das Gespraech nicht und "
                    "braucht eine vollstaendige Anweisung.")

        treffer = next((r for r in aktive if r["id"] == role), None)
        if treffer is None:
            # Abgeschaltete Rolle vom Tippfehler unterscheiden: sonst sucht der
            # Administrator den Fehler in der Schreibweise.
            alle_ids = {r["id"] for r in agent_roles.alle()}
            if role in alle_ids:
                return (f"Fehler: Die Rolle '{role}' ist abgeschaltet. "
                        f"Verfuegbar: {_liste()}.")
            return f"Fehler: Unbekannte Rolle '{role}'. Verfuegbar: {_liste()}."

        return json.dumps({
            "_delegate": True,
            "role": treffer["id"],
            "task": task,
        })


def get_tools():
    """Wird beim Laden des aktivierten Skills gerufen – hier auch das Säen."""
    _saeen_still()
    return [DelegateTool()]
