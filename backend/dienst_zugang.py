"""Eigener Zugang (PAT) fuer Serverdienste – unabhaengig vom gemeinsamen Zugang.

VORGABE DES BETREIBERS (2026-11-17): Zwei Dienste bekommen im Admin-Bereich
einen EIGENEN Personal Access Token, der "dediziert und unabhaengig von den
Einstellungen 'gemeinsamer Jira/Confluence Zugang'" genutzt wird:

* **Loesungsarchiv** (``backend/loesungsarchiv.py``) – Einstellungen → Jira →
  Loesungsarchiv; Feld ``loesungsarchiv_api_token`` der Jira-Skill-Config.
* **Dynamische Confluence-Einbindung** (``backend/confluence_abgleich.py``) –
  Einstellungen → Wissen → "Dynamische Confluence-Einbindung"; Feld
  ``einbindung_api_token`` der Confluence-Skill-Config.

WARUM IN DER SKILL-CONFIG und nicht in einer eigenen Datei: dort gilt fuer
Geheimfelder bereits alles, was ein Token braucht – Tresor-Verpackung in
``settings.json`` (``geheimnis_tresor``, der Name endet auf ``_token``),
maskiertes Lesen (``GET /api/skills/{name}/config`` liefert nur
``geheim_gesetzt``), das Auge mit erneuter Anmeldung (``secret_reveal.skill``)
und die Sperrlisten der Datei. Eine eigene Datei haette jede dieser Schranken
ein zweites Mal gebraucht.

DIE ADRESSE KOMMT AUS DER VERBINDUNG des Skills (``base_url``) – wie beim
gemeinsamen und beim persoenlichen Zugang. Ein eigenes Adressfeld waere eine
SSRF-Flaeche ohne Gegenwert (Begruendung in ``jira_accounts``).

OHNE EIGENEN TOKEN gilt wie bisher der gemeinsame Zugang – so aendert das
Einspielen nichts am Betrieb, und die Oberflaeche nennt immer, WELCHER Zugang
gerade gilt (``zustand``). Ist ein eigener Token hinterlegt, wird er benutzt,
gleich wie der gemeinsame Zugang oder der Schalter "Persoenliche Zugaenge"
stehen. Gebaut werden die Clients in den Konten-Modulen
(``jira_accounts.dienst_client`` / ``confluence_accounts.dienst_client``) –
dort liegt die EINE Konstruktionsstelle je System (Waechter
``test_confluence_accounts`` Abschnitt 13, ``test_jira_nur_lesen``). Beide
Dienste lesen nur; der Jira-Client ist Nur-Lesen wie der gemeinsame.

⚠ ADRESSWECHSEL LOESCHT DEN DIENST-TOKEN (``bei_adresswechsel``). Die Regel
"neue Adresse + behaltenes Geheimnis = abweisen" (``secret_reveal.
umgeleitete_geheimnisse``) bindet den Dienst-Token an ``base_url``. Das
Verbindungsformular schickt ihn aber nie mit – mit der Regel allein liesse sich
die Adresse nie mehr aendern, solange ein Dienst-Token liegt. Deshalb wird er
beim Umzug entfernt (er ginge sonst an die neue Adresse, ohne dass ihn dort
jemand eingegeben hat) und muss neu hinterlegt werden; die Antwort nennt das.
"""

from __future__ import annotations

import re

# Dienst -> (Skill, Feld in der Skill-Config). EINE Tabelle: Oberflaeche,
# Endpunkte, Adresswechsel und Clients lesen alle hier.
DIENSTE: dict[str, dict] = {
    "loesungsarchiv": {"skill": "jira", "feld": "loesungsarchiv_api_token",
                       "name": "Lösungsarchiv"},
    "confluence_einbindung": {"skill": "confluence", "feld": "einbindung_api_token",
                              "name": "Dynamische Confluence-Einbindung"},
}

QUELLE_DIENST = "dienst"
QUELLE_SAMMEL = "sammel"

# Ein PAT ist eine Zeichenkette ohne Leerraum. Die Laenge ist grosszuegig
# (Atlassian-PATs haben rund 44 Zeichen) – sie schuetzt nur vor einem
# versehentlich eingefuegten Absatz.
_TOKEN_RE = re.compile(r"^[\x21-\x7e]{8,512}$")


class DienstFehler(ValueError):
    """Eingabe- oder Zustandsfehler – der Endpunkt antwortet mit 400."""


def eintrag(dienst: str) -> dict:
    e = DIENSTE.get(str(dienst or ""))
    if not e:
        raise DienstFehler("Unbekannter Dienst.")
    return e


def _cfg(skill: str) -> dict:
    from backend.config import config  # noqa: PLC0415
    c = ((config.get_skill_states() or {}).get(skill) or {}).get("config") or {}
    return c if isinstance(c, dict) else {}


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def client(dienst: str):
    """Der Client, mit dem dieser Dienst arbeitet. Traegt ``zugang``
    (``quelle``: ``dienst`` oder ``sammel``)."""
    e = eintrag(dienst)
    if e["skill"] == "jira":
        from backend import jira_accounts as m  # noqa: PLC0415
    else:
        from backend import confluence_accounts as m  # noqa: PLC0415
    return m.dienst_client(e["feld"])


def zustand(dienst: str) -> dict:
    """Fuer die Oberflaeche – OHNE Token, auch nicht maskiert."""
    e = eintrag(dienst)
    cfg = _cfg(e["skill"])
    eigen = bool(_text(cfg.get(e["feld"])))
    sammel = bool(_text(cfg.get("api_token")))
    return {
        "dienst": dienst,
        "skill": e["skill"],
        # Kennung fuer das Auge (POST /api/secret/reveal, Quelle "skill").
        "kennung": "%s:%s" % (e["skill"], e["feld"]),
        "token_gesetzt": eigen,
        "adresse_gesetzt": bool(_text(cfg.get("base_url"))),
        "sammel_gesetzt": sammel,
        # Welcher Zugang GILT – leer, wenn keiner nutzbar ist.
        "quelle": QUELLE_DIENST if eigen else (QUELLE_SAMMEL if sammel else ""),
    }


def speichern(dienst: str, token, sm) -> dict:
    """Eigenen Token hinterlegen. Leer ist hier ein Fehler, kein "unveraendert":
    der Knopf "Speichern" ohne Eingabe hat nichts zu tun, und Entfernen hat
    einen eigenen Weg (``loeschen``)."""
    e = eintrag(dienst)
    tok = _text(token)
    if not tok:
        raise DienstFehler("Bitte einen Token eingeben.")
    if not _TOKEN_RE.match(tok):
        raise DienstFehler("Der Token enthält ungültige Zeichen oder hat eine unpassende Länge.")
    if not _text(_cfg(e["skill"]).get("base_url")):
        raise DienstFehler("Es ist noch keine Adresse hinterlegt – bitte zuerst die "
                           "Verbindung des Bereichs einrichten.")
    sm.update_skill_config(e["skill"], {e["feld"]: tok})
    return zustand(dienst)


def loeschen(dienst: str, sm) -> dict:
    e = eintrag(dienst)
    sm.update_skill_config(e["skill"], {e["feld"]: ""})
    return zustand(dienst)


def testen(dienst: str) -> dict:
    """Verbindungstest mit GENAU dem Zugang, den der Dienst benutzt.

    Die Antwort nennt die ``quelle`` – ohne sie hiesse "ok" bei fehlendem
    eigenen Token nur, dass der gemeinsame Zugang antwortet (dieselbe Falle wie
    bei der Fachprobe in "Mein …-Zugang", gemeldet 2026-11-16)."""
    e = eintrag(dienst)
    c = client(dienst)
    quelle = str((getattr(c, "zugang", None) or {}).get("quelle") or "")
    if not getattr(c, "configured", False):
        return {"ok": False, "quelle": quelle,
                "error": "Nicht eingerichtet – Adresse oder Token fehlen."}
    name = konto = ""
    try:
        if e["skill"] == "jira":
            ich = c.myself() or {}
            konto = str(ich.get("name") or ich.get("key") or "").strip()
        else:
            from backend.confluence_client import ConfluenceError  # noqa: PLC0415
            try:
                ich = c.current_user() or {}
                konto = str(ich.get("username") or ich.get("userKey") or "").strip()
            except ConfluenceError as ce:
                # 404 = den Pfad kennt diese Confluence-Fassung nicht (Begruendung
                # in confluence_accounts.testen) – dann ausdruecklich nachmessen.
                if getattr(ce, "status", 0) != 404:
                    raise
                c.spaces(1)
                ich = {}
        name = str(ich.get("displayName") or "").strip()
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "quelle": quelle, "error": str(ex)[:300]}
    return {"ok": True, "quelle": quelle, "anzeigename": name, "konto": konto}


def bei_adresswechsel(skill: str, body: dict, gespeichert: dict) -> list[str]:
    """Vor dem Speichern der Skill-Config: aendert ``body`` die Adresse, wird
    jeder gespeicherte Dienst-Token dieses Skills entfernt, der nicht im
    selben Rumpf neu kommt. Rueckgabe: die betroffenen Dienste.

    ``None`` statt ``""``: ein leeres Geheimfeld heisst "unveraendert"
    (``leere_geheimfelder_behalten``) und haelte das Speichern ueber
    ``umgeleitete_geheimnisse`` auf – genau die Sperre, die hier aufgeloest
    wird. Veraendert NUR ``body``; geschrieben wird erst, wenn alle anderen
    Pruefungen bestanden sind."""
    if not isinstance(body, dict) or "base_url" not in body:
        return []
    from backend.secret_reveal import _adresse_norm  # noqa: PLC0415
    alt = gespeichert if isinstance(gespeichert, dict) else {}
    if _adresse_norm(body.get("base_url")) == _adresse_norm(alt.get("base_url")):
        return []
    raus = []
    for dienst, e in DIENSTE.items():
        if e["skill"] != skill or not _text(alt.get(e["feld"])):
            continue
        if _text(body.get(e["feld"])):
            continue                     # im selben Rumpf neu eingegeben
        body[e["feld"]] = None
        raus.append(dienst)
    return raus
