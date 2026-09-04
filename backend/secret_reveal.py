"""Gespeicherte Kennwoerter/Token im Klartext an den Berechtigten herausgeben.

⚠ DAS IST DIE UMKEHRUNG EINER BISHERIGEN ZUSAGE, und sie steht auf
ausdrueckliche, wiederholte Anweisung des Betreibers (2026-09-04): "ich habe
Dich angewiesen alle Kennwortfelder mit einem Auge zu versehen ... das Kennwort
wird auf Klick darauf Sichtbar !!!! UEBERALL umsetzen".

Bis dahin galt in mail_accounts, sap_accounts, vemas_accounts und
jira_accounts woertlich: "kein Endpunkt gibt ein Kennwort heraus, auch nicht
maskiert". Diese Zusage gilt fuer die LISTEN- und STATUS-Endpunkte
unveraendert – sie ist nicht aufgehoben, sondern um EINEN ausdruecklichen,
protokollierten Abrufweg ergaenzt. Der Unterschied ist wesentlich:

  * Die Uebersichten geben weiterhin nichts heraus. Wer eine Kontenliste
    abruft, bekommt kein Geheimnis – auch nicht versehentlich, auch nicht in
    einem Feld, das jemand spaeter ins Log schreibt.
  * Herausgegeben wird nur auf einen EINZELNEN, benannten Abruf ("zeig mir
    genau dieses Feld"), und jeder solche Abruf wird protokolliert.

WAS DAS KOSTET, damit es niemand spaeter fuer harmlos haelt:
  * Wer eine Sitzung uebernimmt (geleaktes Token, offener Rechner), kann die
    hinterlegten Zugangsdaten AUSLESEN – vorher konnte er sie nur BENUTZEN.
  * Ein Administrator kann Sammelzugaenge und LLM-Schluessel im Klartext sehen.
    Er hat sie eingetragen und kann sie ohnehin ueberschreiben – aber
    "ueberschreiben" hinterlaesst eine Spur, "ansehen" bisher nicht. Genau
    deshalb ist die Protokollierung Teil dieses Weges und nicht optional.

WO DIE ARBEIT LIEGT: die vier Konten-Module haben je eine eigene Funktion
``klartext(user, feld)`` – dort, wo der Schluessel und die Feldnamen liegen.
Eine zentrale Fassung muesste die Interna von vier Modulen nachbauen und liefe
beim naechsten Feld auseinander (``mail_accounts`` speichert unter ``pw_enc``,
die anderen unter ``<feld>_enc`` – eine geratene Regel haette dort still
"nichts gespeichert" gemeldet).

DIE RECHTEPRUEFUNG LIEGT JE BEREICH IM AUFRUFER (main.py), nicht hier: sie
braucht die Dependencies und die Freigabelisten. Dieses Modul kennt nur den
WEG zum Klartext – und es gibt nichts heraus, wofuer es keinen Eintrag hat
(fail-closed).
"""

import time

# Wie oft darf ein Benutzer Geheimnisse ansehen? Kein Schutz gegen den
# Berechtigten – eine Bremse gegen ein Skript, das der Reihe nach alles
# abraeumt, und ein deutliches Signal im Protokoll.
MAX_JE_STUNDE = 60

_verlauf: dict = {}


def drossel_ok(user: str) -> tuple[bool, str]:
    """(erlaubt, grund). Zaehlt pro Benutzer im gleitenden Stundenfenster."""
    jetzt = time.time()
    liste = [t for t in _verlauf.get(str(user), []) if jetzt - t < 3600]
    if len(liste) >= MAX_JE_STUNDE:
        return False, (f"Zu viele Abrufe ({MAX_JE_STUNDE} je Stunde). Das ist "
                       f"eine Bremse gegen automatisiertes Auslesen, keine "
                       f"Aussage ueber deine Berechtigung.")
    liste.append(jetzt)
    _verlauf[str(user)] = liste
    return True, ""


def _reset_fuer_tests() -> None:
    _verlauf.clear()


# ─── Quellen ────────────────────────────────────────────────────────────────
#
# Jede Quelle liefert ``(klartext, fehler)``. Ein leerer Klartext MIT leerem
# Fehler darf nie vorkommen – der Aufrufer koennte "nichts gespeichert" dann
# nicht von "hat geklappt" unterscheiden.

def benutzer_quelle(bereich: str):
    """Die ``klartext``-Funktion des Konten-Moduls – oder None.

    Diese vier Bereiche gehoeren dem BENUTZER: er hat die Zugangsdaten selbst
    eingetragen. Der Aufrufer prueft zusaetzlich die Bereichs-Freigabe.
    """
    b = (bereich or "").strip().lower()
    if b == "mail":
        from backend import mail_accounts as m
        return m.klartext
    if b == "sap":
        from backend import sap_accounts as m
        return m.klartext
    if b == "vemas":
        from backend import vemas_accounts as m
        return m.klartext
    if b == "jira":
        from backend import jira_accounts as m
        return m.klartext
    return None


def mount(kennung: str) -> tuple[str, str]:
    """Kennwort einer Netzwerk-Freigabe; Kennung ist ihr Index."""
    from backend.config import config
    try:
        idx = int(str(kennung).strip())
    except (TypeError, ValueError):
        return "", "Kennung muss der Index der Freigabe sein."
    mounts = ((config.get_skill_states().get("knowledge", {}) or {})
              .get("config", {}) or {}).get("mounts") or []
    if idx < 0 or idx >= len(mounts):
        return "", "Diese Freigabe gibt es nicht."
    wert = str((mounts[idx] or {}).get("password") or "")
    if not wert:
        return "", "Fuer diese Freigabe ist kein Kennwort hinterlegt."
    return wert, ""


# ⚠ ES GIBT BEWUSST KEINE BEREICHE "profil" UND "skill".
#
# Beide waeren toter Code mit Rechtefrage: die Formulare, die sie betreffen,
# laden ihr Geheimnis LAENGST im Klartext in das Feld –
#   * LLM-Profile ueber ``GET /api/profiles/{id}/key`` (app.js, eigenes Auge),
#   * die Sammelzugaenge und Token der Skill-Reiter direkt aus
#     ``GET /api/skills/{name}/config`` (sap.js, vemas.js, jira.js,
#     confluence.js, kundenverwaltung.js).
# Dort zeigt das Auge also ohnehin schon den gespeicherten Wert, ohne einen
# zweiten Abrufweg. Ein Zweig ohne Aufrufer waere eine zweite Rechtefrage auf
# dasselbe Geheimnis, die bei jeder kuenftigen Durchsicht mitgeprueft werden
# muesste – dieselbe Ueberlegung wie bei ``prompt_check._KONTEXTE``.
# Wer sie doch braucht, ergaenzt sie MIT Aufrufer und mit Rechteeintrag im
# Endpunkt; ein Test haelt fest, dass sie heute abgewiesen werden.

# ⚠ KEIN FREIER ZUGRIFF AUF settings.json. Eine Kennung aus dem Request wuerde
# sonst JEDES Feld herausgeben – auch den Signierschluessel der Sitzungstoken,
# und damit die Moeglichkeit, Tokens fuer beliebige Benutzer zu bauen. Deshalb
# eine Erlaubnisliste und nicht eine Sperrliste: was hier nicht steht, kommt
# nicht heraus, auch wenn morgen ein neues Feld dazukommt.
EINSTELLUNG_ERLAUBT = (
    "ad_bind_password",
    "ldap_bind_password",
    "webdav_password",
    "smtp_password",
    "imap_password",
)


def einstellung(kennung: str) -> tuple[str, str]:
    """Ein Geheimfeld der globalen Einstellungen (nur aus der Erlaubnisliste)."""
    feld = str(kennung or "").strip()
    if feld not in EINSTELLUNG_ERLAUBT:
        return "", (f"Das Feld '{feld}' ist nicht zum Ansehen freigegeben. "
                    f"Moeglich sind: {', '.join(EINSTELLUNG_ERLAUBT)}.")
    from backend.config import config
    wert = str(getattr(config, feld, "") or "")
    if not wert:
        return "", "In diesem Feld ist nichts gespeichert."
    return wert, ""


__all__ = [
    "MAX_JE_STUNDE", "EINSTELLUNG_ERLAUBT",
    "drossel_ok", "benutzer_quelle", "mount", "einstellung",
]
