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

    Diese fuenf Bereiche gehoeren dem BENUTZER: er hat die Zugangsdaten selbst
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
    if b == "confluence":
        from backend import confluence_accounts as m
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
    # Seit 2026-09-13 liegt das Kennwort verschluesselt (data/.mountkey).
    # `kennwort_aus` liest beide Formen – ein Altbestand im Klartext bleibt
    # lesbar, bis die Migration ihn umgezogen hat.
    from backend import mount_credentials as _mc
    try:
        wert = _mc.kennwort_aus(mounts[idx] or {})
    except Exception as e:  # noqa: BLE001
        # Der GRUND gehoert an den Benutzer: "kein Kennwort hinterlegt" waere
        # hier die falsche Auskunft – es ist eines da, nur nicht lesbar.
        return "", str(e)
    if not wert:
        return "", "Fuer diese Freigabe ist kein Kennwort hinterlegt."
    return wert, ""


# ─── LLM-Profile, Agent-Keys, Skill-Konfigurationen, WebDAV (seit BSI M5) ──
#
# Bis 2026-10-05 stand hier: "ES GIBT BEWUSST KEINE BEREICHE profil UND
# skill" – die Formulare luden ihr Geheimnis ohnehin im Klartext ins Feld
# (``GET /api/profiles/{id}/key``, ``GET /api/skills/{name}/config``), ein
# zweiter Weg waere toter Code gewesen. BSI M5 hat genau das abgestellt: die
# Formulare bekommen Geheimfelder LEER, und der einzige Weg zum Klartext ist
# dieser hier – nach erneuter Anmeldung, protokolliert. Damit haben die
# Bereiche jetzt Aufrufer (pwreveal.js, app.js). Die Rechte prueft der
# Endpunkt (Admin bzw. Wissens-Editor), wie bei den uebrigen Bereichen.

def profil(kennung: str) -> tuple[str, str]:
    """``<profil-id>:api_key`` oder ``<profil-id>:session_key``."""
    from backend.config import config
    pid, _, feld = str(kennung or "").strip().rpartition(":")
    if feld not in ("api_key", "session_key") or not pid:
        return "", "Kennung muss '<profil-id>:api_key' oder ':session_key' sein."
    for p in config.profiles or []:
        if isinstance(p, dict) and p.get("id") == pid:
            wert = str(p.get(feld) or "")
            return (wert, "") if wert else ("", "In diesem Feld ist nichts gespeichert.")
    return "", "Dieses Profil gibt es nicht."


def agentkey(kennung: str) -> tuple[str, str]:
    """Leer = der einzelne (alte) Agent-API-Key; sonst die Kennung eines
    benannten Schluessels."""
    from backend.config import config
    kid = str(kennung or "").strip()
    if not kid:
        wert = str(config.AGENT_API_KEY or "")
        return (wert, "") if wert else ("", "Kein Agent-API-Key gespeichert.")
    keys = config.get_setting("agent_api_keys", [])
    for k in keys if isinstance(keys, list) else []:
        if isinstance(k, dict) and k.get("id") == kid:
            wert = str(k.get("key") or "")
            return (wert, "") if wert else ("", "Fuer diesen Schluessel ist nichts gespeichert.")
    return "", "Diesen Schluessel gibt es nicht."


def _geheimfeld_name(name) -> bool:
    from backend import geheimnis_tresor as _t
    return _t.ist_geheimer_name(name)


def skill_config_maskiert(cfg: dict) -> tuple[dict, list]:
    """Skill-Konfiguration ohne Geheimfelder (oberste Ebene + verschachtelte
    Objekte). Rueckgabe: (Kopie, Liste der gesetzten Felder als Punkt-Pfad).

    Listen werden nicht durchsucht: ihre Eintraege haben keine stabile Kennung,
    ein Zurueckschreiben "leer = unveraendert" ginge dort ueber den Index – und
    der verschiebt sich beim Loeschen (Register). Wo eine Liste Geheimnisse
    traegt (Freigaben der Wissensdatenbank), hat sie eigene Endpunkte, die
    bereits nur ``has_password`` liefern.
    """
    gesetzt: list = []

    def _geh(o: dict, pfad: str) -> dict:
        aus = {}
        for k, v in o.items():
            p = f"{pfad}.{k}" if pfad else str(k)
            if isinstance(v, str) and _geheimfeld_name(k):
                aus[k] = ""
                if v:
                    gesetzt.append(p)
            elif isinstance(v, dict):
                aus[k] = _geh(v, p)
            else:
                aus[k] = v
        return aus
    return _geh(dict(cfg or {}), ""), gesetzt


def leere_geheimfelder_behalten(neu: dict, alt: dict) -> dict:
    """Ein leer gesendetes Geheimfeld heisst "unveraendert": den gespeicherten
    Wert einsetzen. Gilt auch in verschachtelten Objekten (gleicher Pfad)."""
    def _geh(n, a):
        if not isinstance(n, dict):
            return n
        a = a if isinstance(a, dict) else {}
        aus = {}
        for k, v in n.items():
            if isinstance(v, str) and not v and _geheimfeld_name(k) \
                    and isinstance(a.get(k), str) and a.get(k):
                aus[k] = a[k]
            elif isinstance(v, dict):
                aus[k] = _geh(v, a.get(k))
            else:
                aus[k] = v
        return aus
    return _geh(neu, alt)


# Feldnamen, die bestimmen, WOHIN ein gespeichertes Geheimnis geht. Nur
# Zeichenketten: eine Liste wie sap.allowed_hosts ist eine Erlaubnisliste, kein
# Ziel – das Ziel (odata_base_url, hana_host …) ist immer ein eigenes Feld.
_ADRESS_TEILE = ("url", "host", "server", "endpoint", "adresse", "address", "domain")


def _adressfeld_name(name) -> bool:
    n = str(name or "").strip().lower()
    return bool(n) and not _geheimfeld_name(n) and any(t in n for t in _ADRESS_TEILE)


def _adresse_norm(v) -> str:
    return str(v if v is not None else "").strip().rstrip("/").lower()


def _hat_adresse(o) -> bool:
    return isinstance(o, dict) and any(_adressfeld_name(k) for k in o)


def _hat_geheimnis(o) -> bool:
    return isinstance(o, dict) and any(
        (_geheimfeld_name(k) and isinstance(v, str) and v) or _hat_geheimnis(v)
        for k, v in o.items())


def _gruppe(name) -> tuple:
    """Zugangs-Gruppe eines Adressfelds: die Namensteile VOR dem Adressteil,
    ohne die nichtssagenden ``base``/``api``. ``ibs_api_url`` -> ``("ibs",)``,
    ``base_url`` -> ``()``, ``hana_host`` -> ``("hana",)``, ``rfc_ashost`` -> ``("rfc",)``."""
    teile = str(name or "").strip().lower().split("_")
    for i, t in enumerate(teile):
        if any(x in t for x in _ADRESS_TEILE):
            return tuple(x for x in teile[:i] if x not in ("base", "api"))
    return tuple(teile)


def _bindet(geheim: str, gruppe: tuple, gruppen: set, geheimnisse) -> bool:
    """Geht das Geheimnis an die Adresse der ``gruppe``?

    Ein Geheimnis gehoert der Gruppe, mit deren Namensteilen es beginnt
    (``ibs_api_key`` -> ``ibs``). Gehoert es keiner, gehoert es der Adresse
    ohne Gruppe (``api_token`` -> ``base_url``); gibt es die nicht, den
    Adressen, deren Gruppe kein eigenes Geheimnis hat (sap: ``bearer_token``
    -> ``odata_base_url``, nicht ``hana_host`` mit ``hana_password``) – und
    gibt es auch die nicht, im Zweifel JEDER Adresse des Objekts."""
    def _von(name):
        teile = tuple(str(name).lower().split("_"))
        return {g for g in gruppen if g and teile[:len(g)] == g}
    eigen = _von(geheim)
    if eigen:
        return gruppe in eigen
    if () in gruppen:
        return gruppe == ()
    besetzt = set().union(*(_von(x) for x in geheimnisse)) if geheimnisse else set()
    frei = gruppen - besetzt
    return gruppe in frei if frei else True


def umgeleitete_geheimnisse(neu: dict, alt: dict) -> list:
    """Adressfelder, die sich aendern, waehrend ein zugehoeriges Geheimnis
    "unveraendert" bleibt. Leere Liste = in Ordnung.

    Code-Review 2026-10-07: ``leere_geheimfelder_behalten`` setzte den
    gespeicherten Wert auch dann ein, wenn im SELBEN Speichern die Adresse
    wechselte. Wer eine Sitzung hatte, aber das Geheimnis nicht kannte,
    stellte ``base_url`` auf seinen Server, liess das Token leer und bekam es
    beim naechsten Abruf zugeschickt – am Auge (erneute Anmeldung, BSI M5)
    vorbei. Wer die Adresse aendert, gibt das Geheimnis neu ein.

    Gepaart wird je Zugang (``_bindet``): im jira-Objekt liegen ``base_url`` +
    ``api_token`` UND ``ibs_api_url`` + ``ibs_api_key`` – der Umzug des einen
    darf nicht am Geheimnis des anderen scheitern. Eine Adresse eines
    uebergeordneten Objekts gilt fuer die Geheimnisse darunter, solange das
    Objekt keine eigene Adresse hat."""
    raus: list = []

    def _merk(f):
        if f not in raus:
            raus.append(f)

    def _geh(n, a, pfad, oben):
        if not isinstance(n, dict):
            return
        a = a if isinstance(a, dict) else {}
        adressen = {k for k in set(n) | set(a) if _adressfeld_name(k)}
        gruppen = {_gruppe(k) for k in adressen}
        hier = [k for k, v in n.items()
                if k in adressen and isinstance(v, str)
                and _adresse_norm(v) != _adresse_norm(a.get(k))]
        # Oben merged update_skill_config FLACH: ein weggelassenes Feld bleibt
        # dort ebenso stehen wie ein leeres – und ein weggelassenes Objekt mit
        # all seinen Geheimnissen. Darunter ersetzt ein gesendetes Objekt das
        # alte ganz; stehen bleibt nur, was leer zurueckkommt.
        behalten = [k for k, v in a.items()
                    if _geheimfeld_name(k) and isinstance(v, str) and v
                    and (n.get(k) == "" or (not pfad and k not in n))]
        geheimnisse = [k for k in set(n) | set(a) if _geheimfeld_name(k)]
        for g in behalten:
            for k in hier:
                if _bindet(g, _gruppe(k), gruppen, geheimnisse):
                    _merk(pfad + k)
            if oben:
                for f in oben:
                    _merk(f)
        # Ein Objekt mit EIGENER Adresse (webdav.url) bindet seine Geheimnisse
        # dorthin – die Adresse darueber erreicht sie nicht.
        weg = [k for k, v in a.items()
               if not pfad and isinstance(v, dict) and k not in n and _hat_geheimnis(v)
               and not _hat_adresse(v)]
        if weg:
            for f in oben + [pfad + k for k in hier]:
                _merk(f)
        for k, v in n.items():
            if isinstance(v, dict):
                darueber = [] if (_hat_adresse(v) or _hat_adresse(a.get(k))) \
                    else oben + [pfad + x for x in hier]
                _geh(v, a.get(k), pfad + k + ".", darueber)

    _geh(neu, alt, "", [])
    return raus


def skill(kennung: str) -> tuple[str, str]:
    """``<skill>:<feld>`` bzw. ``<skill>:<objekt>.<feld>`` – nur Geheimfelder."""
    name, _, pfad = str(kennung or "").strip().partition(":")
    teile = [t for t in pfad.split(".") if t]
    if not name or not teile:
        return "", "Kennung muss '<skill>:<feld>' sein."
    if not _geheimfeld_name(teile[-1]):
        # Kein Weg in beliebige Felder: was kein Geheimnis ist, steht ohnehin
        # im Formular – und eine freie Kennung waere ein Lesezugang zu allem.
        return "", f"Das Feld '{teile[-1]}' ist kein Geheimfeld."
    from backend.config import config
    o = ((config.get_skill_states() or {}).get(name) or {}).get("config") or {}
    for t in teile:
        o = o.get(t) if isinstance(o, dict) else None
    wert = o if isinstance(o, str) else ""
    if not wert and name == "google" and teile == ["client_secret"]:
        import os
        wert = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    return (wert, "") if wert else ("", "In diesem Feld ist nichts gespeichert.")


def webdav(_kennung: str = "") -> tuple[str, str]:
    """Kennwort des WebDAV-Zugangs der Wissensdatenbank."""
    from backend.webdav import _get_webdav_config
    wert = str((_get_webdav_config() or {}).get("password") or "")
    return (wert, "") if wert else ("", "Kein WebDAV-Kennwort gespeichert.")


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
    # ⚠ Die Felder liegen unter ``extra`` (config.get_setting) – bis
    # 2026-10-05 stand hier ``getattr(config, feld)``, und das Attribut gibt es
    # nicht: das Auge am AD-Bind-Kennwort meldete IMMER "nichts gespeichert".
    # Der Test war gruen, weil seine Attrappe das Attribut setzte.
    wert = str(config.get_setting(feld, "") or getattr(config, feld, "") or "")
    if not wert:
        return "", "In diesem Feld ist nichts gespeichert."
    return wert, ""


__all__ = [
    "MAX_JE_STUNDE", "EINSTELLUNG_ERLAUBT",
    "drossel_ok", "benutzer_quelle", "mount", "einstellung",
    "profil", "agentkey", "skill", "webdav",
    "skill_config_maskiert", "leere_geheimfelder_behalten",
]
