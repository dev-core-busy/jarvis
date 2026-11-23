"""Auswertungs-Vorlagen fuer das Outlook-Add-in ("Zusammenfassen", "Kurz (Team-Leitung)").

**Was das ist:** benannte Anweisungen, mit denen das Add-in die gerade markierte
E-Mail auswertet – zusammenfassen, fuer eine Teamleitung verdichten, Aufgaben
und Fristen herausziehen. Gewaehlt im Pulldown des Aufgabenfensters, gepflegt in
der Kachel **E-Mail** (``/email``). Gemeldet 2026-11-23: "wir benoetigen eine
Moeglichkeit wie beim Jira-Plug-In eigene Abfragen zu hinterlegen".

BAUART 1:1 WIE ``jira_vorlagen`` – mit Absicht
-----------------------------------------------
* Zwei Toepfe in EINER Datei: ``global`` (vom Administrator, fuer alle sichtbar,
  nur von Administratoren aenderbar) und ``benutzer[<name>]`` (eigene, fuer
  niemanden sonst sichtbar).
* Der Standard ist PERSOENLICH (``standard``: Benutzer → Kennung), nicht ein
  Feld an der Vorlage – sonst waere die Wahl des Ersten die Vorauswahl aller.
* Mitgelieferte Vorschlaege entstehen NUR, wenn die Datei noch gar nicht
  existiert. Eine bewusst geloeschte Vorgabe kommt nicht zurueck.

WAS BEWUSST FEHLT (gegenueber Jira)
-----------------------------------
* **Keine ``art``.** Eine Vorlage erzeugt hier immer eine AUSWERTUNG fuer den
  Benutzer selbst, nie einen Text an Dritte. Fuer Antworten gibt es im Add-in
  den eigenen Weg mit Stilen und Signaturen; eine zweite Antwortmaschine waere
  ein zweiter Ort fuer dieselben Schutzregeln.
* **Keine Werkzeug-Bereiche.** Der Lauf hat KEINE Werkzeuge
  (``mail_runner.vorlage_auswerten``). Eine Vorlage kann damit nichts
  freischalten – sie bestimmt nur, worauf die Auswertung hinauslaeuft.

DER TEXT IST EINE ANWEISUNG AN DAS MODELL
-----------------------------------------
Er steht im Auftrag VOR dem Fremdtext und HINTER den Grundregeln (dieselbe
Reihenfolge wie bei Stilen und Jira-Vorlagen). Die Datei ist deshalb in der
Sandbox gesperrt (``backend/sandbox.py``): wer sie beschreiben kann, legt allen
Benutzern einen Abschnitt in jeden Auftrag.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from backend.benutzer import norm_user

# Deckel. Eine Vorlage geht in JEDEN Auftrag – ein Roman darin verdraengt die
# Nachricht aus dem Kontextfenster. Werte wie bei den Jira-Vorlagen.
TEXT_MAX = 2000
NAME_MAX = 60
MAX_JE_BENUTZER = 20

_DATEI = Path(__file__).resolve().parent.parent / "data" / "email_vorlagen.json"
_SPERRE = threading.Lock()

# ── Mitgelieferte Vorschlaege ───────────────────────────────────────────────
# Die ersten beiden sind die beiden Beispiele aus der Meldung. Sie entstehen
# beim ERSTEN Zugriff, wenn die Datei fehlt – nicht pro fehlender Vorlage.
VORSCHLAEGE = [
    {
        "name": "Zusammenfassen",
        "text": ("Fasse die E-Mail sachlich zusammen: worum es geht, was der "
                 "Absender möchte und welche Termine oder Fristen genannt "
                 "werden. Schließe mit den offenen Punkten, die für mich "
                 "daraus folgen."),
    },
    {
        "name": "Kurz (Team-Leitung)",
        "text": ("Halte dich sehr kurz: höchstens drei Sätze für eine "
                 "Teamleitung. Nenne das Anliegen, die Auswirkung und ob eine "
                 "Entscheidung oder Handlung nötig ist. Keine Einzelheiten, "
                 "keine Zitate."),
    },
    {
        "name": "Aufgaben und Fristen",
        "text": ("Liste ausschließlich auf, welche Aufgaben, Bitten und "
                 "Fristen sich aus der E-Mail für mich ergeben – je Punkt eine "
                 "Zeile, mit Datum, falls eines genannt ist. Steht nichts "
                 "darin, sage das in einem Satz."),
    },
]


class VorlagenFehler(Exception):
    """Fachlicher Fehlschlag mit Text fuer die Oberflaeche."""


def _leer() -> dict:
    return {"global": [], "benutzer": {}, "standard": {}}


def _laden() -> dict:
    if not _DATEI.exists():
        return _leer()
    try:
        d = json.loads(_DATEI.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        # Eine beschaedigte Datei darf den Bereich nicht sperren – dann gibt es
        # eben keine Vorlagen. Ueberschrieben wird sie erst beim naechsten
        # Speichern; der Administrator kann sie vorher ansehen.
        return _leer()
    if not isinstance(d, dict):
        return _leer()
    if not isinstance(d.get("global"), list):
        d["global"] = []
    if not isinstance(d.get("benutzer"), dict):
        d["benutzer"] = {}
    if not isinstance(d.get("standard"), dict):
        d["standard"] = {}
    return d


def _speichern(d: dict) -> None:
    _DATEI.parent.mkdir(parents=True, exist_ok=True)
    tmp = _DATEI.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _DATEI)
    try:
        # 0640: keine Zugangsdaten, aber wer sie BESCHREIBEN kann, legt allen
        # Benutzern einen Prompt-Abschnitt in jeden Auftrag.
        _DATEI.chmod(0o640)
    except Exception:  # noqa: BLE001
        pass


def _key(user: str) -> str:
    """Benutzerschluessel – dieselbe Normalisierung wie im ganzen E-Mail-Bereich.

    Ohne sie haette dieselbe Person je Anmeldeform (``x`` gegen ``firma\\x``)
    verschiedene Vorlagen.
    """
    return norm_user(user) or "?"


def _saeen_ungesperrt() -> None:
    """Legt die Vorschlaege an – NUR, wenn die Datei noch gar nicht existiert.

    Aufgerufen auch vor jedem SCHREIBEN, nicht nur beim Lesen: waere der erste
    Zugriff ein Speichern, entstuende die Datei mit genau dieser einen Vorlage,
    und die Vorschlaege kaemen nie mehr (Lehre aus ``jira_vorlagen.speichern``).
    """
    if _DATEI.exists():
        return
    d = _leer()
    for v in VORSCHLAEGE:
        d["global"].append({"id": uuid.uuid4().hex[:12], "name": v["name"],
                            "text": v["text"], "erstellt": int(time.time())})
    _speichern(d)


def saeen() -> None:
    with _SPERRE:
        _saeen_ungesperrt()


def _pruefe(name: str, text: str) -> tuple:
    n = " ".join(str(name or "").split())[:NAME_MAX]
    t = str(text or "").strip()
    if not n:
        raise VorlagenFehler("Die Vorlage braucht einen Namen.")
    if not t:
        raise VorlagenFehler("Die Vorlage braucht eine Anweisung.")
    if len(t) > TEXT_MAX:
        # ABGELEHNT, nicht gekuerzt: ein stiller Schnitt mitten im Satz aendert
        # die Anweisung, und niemand sieht es.
        raise VorlagenFehler("Die Anweisung ist zu lang (%d von höchstens %d "
                             "Zeichen)." % (len(t), TEXT_MAX))
    return n, t


def _standard_aus(d: dict, user: str, sichtbar: list) -> str:
    """Die gepruefte Standard-Kennung – oder ``""``.

    Zeigt der gespeicherte Wert ins Leere (ein Administrator hat eine
    gemeinsame Vorlage geloescht), kommt ``""`` heraus. Geschrieben wird dabei
    nichts – Begruendung wie in ``jira_vorlagen._standard_aus``.
    """
    vid = str((d.get("standard") or {}).get(_key(user)) or "")
    if not vid:
        return ""
    return vid if any(v.get("id") == vid for v in sichtbar) else ""


def liste(user: str, ist_admin: bool = False) -> dict:
    """Alle Vorlagen, die dieser Benutzer benutzen darf.

    ``global`` (gemeinsame) und ``eigene`` getrennt: die Oberflaeche muss
    zeigen, was man aendern darf und was nicht. ``standard`` ist bereits
    geprueft. Rueckgabe sind KOPIEN – ein Aufrufer, der daran etwas verstellt,
    darf nicht den geladenen Bestand treffen.
    """
    with _SPERRE:
        _saeen_ungesperrt()
        d = _laden()
    global_ = [dict(v) for v in d["global"] if isinstance(v, dict)]
    eigene = [dict(v) for v in (d["benutzer"].get(_key(user)) or [])
              if isinstance(v, dict)]
    return {"global": global_, "eigene": eigene, "darf_global": bool(ist_admin),
            "standard": _standard_aus(d, user, eigene + global_),
            "text_max": TEXT_MAX, "name_max": NAME_MAX}


def speichern(user: str, name: str, text: str, vid: str = "",
              global_: bool = False, ist_admin: bool = False) -> dict:
    """Legt eine Vorlage an oder aendert sie.

    ``global_`` UMGESTELLT heisst VERSCHIEBEN zwischen "meine" und "gemeinsam";
    die Kennung bleibt dabei erhalten (persoenliche Standards zeigen darauf).
    Gemeinsam → eigen nimmt die Vorlage allen anderen weg und ist deshalb
    ebenfalls Administratorensache.
    """
    n, t = _pruefe(name, text)
    if global_ and not ist_admin:
        raise VorlagenFehler("Nur Administratoren dürfen gemeinsame Vorlagen "
                             "anlegen.")
    vid = str(vid or "").strip()
    with _SPERRE:
        _saeen_ungesperrt()
        d = _laden()
        eigene = d["benutzer"].setdefault(_key(user), [])
        ziel = d["global"] if global_ else eigene
        quelle = eigene if global_ else d["global"]

        if vid:
            for v in ziel:
                if v.get("id") == vid:
                    v["name"], v["text"] = n, t
                    _speichern(d)
                    return dict(v)
            for i, v in enumerate(quelle):
                if v.get("id") != vid:
                    continue
                if not ist_admin:
                    # Ein Benutzer kann eine gemeinsame Vorlage weder aendern
                    # noch zu seiner eigenen machen. (Eigen → gemeinsam ist
                    # oben schon abgewiesen.)
                    raise VorlagenFehler("Gemeinsame Vorlagen ändert nur ein "
                                         "Administrator.")
                if len(ziel) >= MAX_JE_BENUTZER:
                    raise VorlagenFehler("Mehr als %d Vorlagen sind nicht "
                                         "vorgesehen." % MAX_JE_BENUTZER)
                v["name"], v["text"] = n, t
                quelle.pop(i)
                ziel.append(v)
                _speichern(d)
                return dict(v)
            raise VorlagenFehler("Die Vorlage wurde nicht gefunden.")

        if len(ziel) >= MAX_JE_BENUTZER:
            raise VorlagenFehler("Mehr als %d Vorlagen sind nicht vorgesehen."
                                 % MAX_JE_BENUTZER)
        neu = {"id": uuid.uuid4().hex[:12], "name": n, "text": t,
               "erstellt": int(time.time())}
        ziel.append(neu)
        _speichern(d)
        return dict(neu)


def loeschen(user: str, vid: str, ist_admin: bool = False) -> bool:
    """Loescht eine Vorlage – eine fremde nie.

    Gesucht wird ZUERST bei den eigenen. Eine gemeinsame darf nur ein
    Administrator entfernen. Fremd und unbekannt geben dieselbe Antwort: ob eine
    fremde Vorlage existiert, ist selbst eine Information.
    """
    vid = str(vid or "").strip()
    if not vid:
        return False
    with _SPERRE:
        d = _laden()
        toepfe = [d["benutzer"].setdefault(_key(user), [])]
        if ist_admin:
            toepfe.append(d["global"])
        for topf in toepfe:
            for i, v in enumerate(topf):
                if v.get("id") == vid:
                    topf.pop(i)
                    st = d["standard"]
                    if st.get(_key(user)) == vid:
                        st.pop(_key(user), None)
                    _speichern(d)
                    return True
    return False


def standard_setzen(user: str, vid: str, ist_admin: bool = False) -> str:
    """Markiert eine Vorlage als persoenlichen Standard. ``""`` hebt ihn auf.

    Eine unbekannte Kennung wird ABGEWIESEN, gesucht nur in dem, was dieser
    Benutzer benutzen darf – die Kennung im Request ist damit kein Weg an eine
    fremde Vorlage.
    """
    ziel = str(vid or "").strip()
    with _SPERRE:
        _saeen_ungesperrt()
        d = _laden()
        if ziel:
            sichtbar = list(d["benutzer"].get(_key(user)) or []) + list(d["global"])
            if not any(v.get("id") == ziel for v in sichtbar):
                raise VorlagenFehler("Die Vorlage wurde nicht gefunden.")
            d["standard"][_key(user)] = ziel
        else:
            d["standard"].pop(_key(user), None)
        _speichern(d)
    return ziel


def eintrag_fuer(user: str, vid: str, ist_admin: bool = False) -> dict:
    """Die Vorlage zu einer Kennung – nur aus dem, was der Benutzer benutzen DARF."""
    vid = str(vid or "").strip()
    if not vid:
        return {}
    d = liste(user, ist_admin)
    for v in d["eigene"] + d["global"]:
        if v.get("id") == vid:
            return v
    return {}


def markensicher(name: str) -> str:
    """Ein Name, der in einer Abschnittszeile des Auftrags stehen darf."""
    return " ".join(re.sub(r"[=\[\]\r\n]+", " ", str(name or "")).split())[:NAME_MAX]
