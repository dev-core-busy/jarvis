"""Skill: Internet-Recherche ueber Microsoft 365 Copilot.

EIN Werkzeug, ``copilot_recherche``. Copilot ist hier ein Dienstleister fuer
TEXT und nichts weiter – er bekommt eine Frage und liefert eine Antwort mit
Quellen. Er hat KEINE Jarvis-Werkzeuge, und die Chat API kann ihm auch keine
geben ("The Chat API only responds with textual responses", Learn-Doku). Eine
praeparierte Webseite kann damit hoechstens den Antworttext beeinflussen – also
dieselbe Klasse wie eine Wissenssuche oder ein Ticket-Kommentar, und gegen die
greift die bestehende Abwehr.

DREI SCHRANKEN, UND KEINE IST HIER ERFUNDEN
-------------------------------------------
1. **Internet-Freigabe des Auftraggebers** (``_user_has_internet_access``,
   leer = niemand, kein Admin-Bypass). Ohne sie gibt es keine Recherche.
   ⚠ DAS IST DER PUNKT, AN DEM DIESES WERKZEUG GEFAEHRLICH WAERE: der
   Backend-Prozess hat Internet, die OS-Sperre aus ``backend/egress_guard.py``
   trifft nur ``shell_execute`` eines gesperrten Benutzers. Ohne die Pruefung
   hier waere dieses Werkzeug ein vollwertiger Internet-Zugang fuer genau die
   Benutzer, denen er genommen wurde – einer, der die nftables-Grenze nicht
   beruehrt und deshalb auch keine Fehlermeldung erzeugt.
2. **Personenbindung** ueber ``copilot_client.current_copilot_user`` (vom
   Dispatch gesetzt). Es gibt kein Werkzeug-Argument fuer den Benutzer: sonst
   koennte ein eingeschmuggelter Satz waehlen, mit wessen Microsoft-Konto –
   und damit mit wessen Postfach-Zugriff – recherchiert wird.
3. **Entschaerfung des Rueckwegs** macht ``backend/werkzeug_rahmen`` zentral
   fuer JEDES Werkzeugergebnis (BSI H8). Hier wird NICHT noch einmal
   entschaerft: zwei Schranken fuer dieselbe Frage machen jede Gegenprobe
   stumm (Register), und man liest das Ergebnis als "blinder Waechter".

WARUM KEINE BESTAETIGUNGSKARTE JE FRAGE
---------------------------------------
Ein Sandbox-Shell-Befehl MIT Internet-Freigabe darf ohne Klick ins Netz senden
– "die Internet-Freigabe selbst ist die Zustimmung" (Betreiberentscheid
2026-10-11, ``backend/wirkung.py``). Eine Recherche ist derselbe Fall, und eine
Karte je Suchanfrage waere unbenutzbar. Wer das aendert, aendert es hier UND in
``wirkung.einstufen()``.

WAS DER BENUTZER WISSEN MUSS – UND WAS NOCH FEHLT
-------------------------------------------------
Die Frage VERLAESST DAS HAUS: Copilot bildet daraus eine eigene Suchanfrage und
schickt sie samt Client-IP an Bing. Fuer diese Anfragen gelten laut Microsoft
weder DPA noch EU Data Boundary ("The ... Data Protection Addendum (DPA) doesn't
apply to the use of generated web search queries"). Deshalb sagt die
Werkzeug-Beschreibung es dem Modell, und das Ergebnis sagt es dem Benutzer.

⚠ RUECKSTAND, BENANNT STATT BEHAUPTET: eine automatische Anonymisierung der
Frage (``backend/anonymisieren.py``) ist NICHT eingebaut. Wer Kundennamen aus
dem Gespraechsverlauf in eine Recherchefrage uebernimmt, schickt sie an Bing.
"""

from backend.tools.base import BaseTool

# Deckel fuer den Antworttext. Die Zahl ist gross genug fuer eine ausfuehrliche
# Recherche und klein genug, dass eine Antwort nicht den halben Kontext frisst.
MAX_ANTWORT = 12000
# Mehr Quellen als das nennt keine brauchbare Antwort; die Liste soll den Text
# nicht verdraengen.
MAX_QUELLEN = 12


def _freigegeben(benutzer: str) -> bool:
    """Internet-Freigabe des Auftraggebers – fail-closed.

    Lazy import von ``backend.main`` wie in ``mail_runner``/
    ``short_tracks_runner``: ein Modulimport waere ein Zirkel, und die
    Freigabe-Funktion ist bewusst DORT verdrahtet, wo der Login-Cache liegt.
    Faellt der Import aus, gilt "nicht freigegeben" – eine nicht lesbare
    Pruefung verweigert (Register).
    """
    if not (benutzer or "").strip():
        return False
    try:
        import backend.main as m  # noqa: PLC0415
        return bool(m._user_has_internet_access(benutzer))
    except Exception as e:  # noqa: BLE001
        print(f"[Copilot] Freigabe-Pruefung nicht moeglich: {e}", flush=True)
        return False


class CopilotRechercheTool(BaseTool):
    """Recherche ueber Microsoft 365 Copilot."""

    @property
    def name(self) -> str:
        return "copilot_recherche"

    @property
    def description(self) -> str:
        return (
            "Stellt eine Recherchefrage an Microsoft 365 Copilot und gibt "
            "dessen Antwort MIT QUELLENANGABEN zurueck. Copilot sucht dafuer "
            "im Internet (Bing) und zusaetzlich im Bestand des Unternehmens "
            "(Postfach, SharePoint, Teams des angemeldeten Benutzers) - was "
            "davon eingeflossen ist, steht in den Quellen. "
            "WICHTIG: die Frage verlaesst das Haus und geht an Microsoft und "
            "an die Bing-Suche. Formuliere sie deshalb SACHLICH und ohne "
            "Kundennamen, Personennamen, Ticketnummern oder interne "
            "Bezeichnungen, sofern sie fuer die Frage nicht unverzichtbar "
            "sind. Fuer eine Frage, die nur den Hausbestand betrifft, ist "
            "knowledge_search der richtige Weg. Copilot fuehrt keine "
            "Aktionen aus und kann nur antworten."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "frage": {
                    "type": "STRING",
                    "description": (
                        "Die Recherchefrage in natuerlicher Sprache. Eine "
                        "Frage je Aufruf; lange Vorhaben in Teilfragen "
                        "zerlegen (die Schnittstelle kennt keine "
                        "langlaufenden Auftraege)."
                    ),
                },
                "nur_web": {
                    "type": "BOOLEAN",
                    "description": (
                        "true (Vorgabe) laesst Copilot im Internet suchen. "
                        "false schaltet die Web-Suche fuer diese eine Frage "
                        "ab - dann antwortet er nur aus dem Bestand des "
                        "Unternehmens."
                    ),
                },
            },
            "required": ["frage"],
        }

    async def execute(self, frage: str = "", nur_web: bool = True, **kwargs) -> str:
        from backend import copilot_client as cc  # noqa: PLC0415

        benutzer = (cc.current_copilot_user.get() or "").strip()
        if not benutzer:
            return ("Recherche nicht moeglich: dieser Lauf hat keinen "
                    "Auftraggeber, dem ein Microsoft-Konto zugeordnet werden "
                    "kann. Microsoft 365 Copilot laesst sich nur im Namen "
                    "eines angemeldeten Benutzers abfragen - ein Lauf ohne "
                    "Oberflaeche (Zeitplan, WhatsApp, Agenten-API) kann das "
                    "Werkzeug deshalb nicht nutzen.")

        if not _freigegeben(benutzer):
            # Der Grund nennt, WER abgelehnt hat und WARUM – ein Modell liest
            # "nicht erlaubt" sonst als Stoerung und raet dem Benutzer, sich
            # an einen Administrator zu wenden (Register, BSI H9).
            return ("Recherche abgelehnt: fuer dieses Konto ist der "
                    "Internet-Zugriff nicht freigegeben (Einstellungen -> "
                    "Sicherheit -> Berechtigungen -> Internet-Zugriff). Das "
                    "ist eine Freigabe-Entscheidung des Administrators, kein "
                    "Fehler und keine Stoerung von Microsoft 365 Copilot. "
                    "Beantworte die Frage ohne Internet-Recherche oder nenne "
                    "dem Benutzer diese Einstellung.")

        if not cc.eingerichtet():
            return ("Recherche nicht moeglich: Microsoft 365 Copilot ist auf "
                    "diesem Server nicht eingerichtet (Mandanten-Kennung und "
                    "Anwendungs-Kennung fehlen unter Einstellungen -> "
                    "Copilot). Das muss ein Administrator einmalig tun.")

        try:
            erg = await cc.recherche(benutzer, frage, web=bool(nur_web))
        except cc.CopilotFehler as e:
            return f"Recherche fehlgeschlagen: {e}"
        except Exception as e:  # noqa: BLE001
            return (f"Recherche fehlgeschlagen (unerwarteter Fehler): "
                    f"{type(e).__name__}: {e}")

        # KEINE eigene Audit-Zeile: ``agent.py::_execute_tool`` protokolliert
        # JEDES Werkzeug mit ``exec_args`` (also der Frage) und der
        # Ergebnislaenge. Eine zweite Zeile hier waere die Dopplung, an der
        # jede Gegenprobe stumm wird – und sie wuerde das Journal entwerten
        # (Register: eine Zeile je Werkzeug-Ergebnis).
        return _ergebnis_text(erg, bool(nur_web))


def _ergebnis_text(erg: dict, web: bool) -> str:
    """Antworttext, Kuerzungshinweis und Quellenliste.

    Der Kuerzungshinweis steht VOR dem gekuerzten Teil – am Ende schneidet ihn
    die naechste Kappung selbst weg, und das Modell haelt den Ausschnitt fuer
    vollstaendig (Register).
    """
    text = str(erg.get("text") or "")
    teile: list[str] = []
    if web:
        teile.append("[Diese Antwort stammt von Microsoft 365 Copilot. Die "
                     "Frage wurde an Microsoft und an die Bing-Suche "
                     "uebermittelt.]")
    else:
        teile.append("[Diese Antwort stammt von Microsoft 365 Copilot, ohne "
                     "Internet-Suche - nur aus dem Bestand des Unternehmens.]")

    if len(text) > MAX_ANTWORT:
        teile.append(f"[Gekuerzt: {MAX_ANTWORT} von {len(text)} Zeichen "
                     f"gezeigt. Stelle eine engere Frage, wenn der Rest "
                     f"gebraucht wird.]")
        text = text[:MAX_ANTWORT]
    teile.append(text)

    quellen = erg.get("quellen")
    if isinstance(quellen, list) and quellen:
        zeilen = []
        for q in quellen[:MAX_QUELLEN]:
            if not isinstance(q, dict):
                continue
            name = str(q.get("name") or "").strip()
            url = str(q.get("url") or "").strip()
            if url and name:
                zeilen.append(f"- {name}: {url}")
            elif url:
                zeilen.append(f"- {url}")
            elif name:
                zeilen.append(f"- {name} (ohne Adresse)")
        if zeilen:
            kopf = "Quellen, die Copilot nennt:"
            if len(quellen) > MAX_QUELLEN:
                kopf = (f"Quellen, die Copilot nennt ({MAX_QUELLEN} von "
                        f"{len(quellen)} gezeigt):")
            teile.append(kopf + "\n" + "\n".join(zeilen))
    else:
        # "Keine" ist eine AUSKUNFT und keine Entwarnung: ohne Quellenangabe
        # ist die Antwort nicht nachpruefbar, und das gehoert gesagt.
        teile.append("Copilot hat zu dieser Antwort keine Quellen genannt - "
                     "sie ist damit nicht nachpruefbar.")
    return "\n\n".join(teile)


def get_tools():
    """Gibt die Tools dieses Skills zurueck."""
    return [CopilotRechercheTool()]
