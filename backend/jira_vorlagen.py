"""Prompt-Vorlagen fuer die Ticket-Zusammenfassung.

**Was das ist:** benannte Vorlagen, die bestimmen, WORAUF eine Zusammenfassung
hinausläuft – "kurz fuer die Leitung", "technisch mit Verlauf", "was fehlt uns
noch". Der Benutzer waehlt sie im Pulldown der Browser-Erweiterung.

WARUM VORLAGEN UND KEIN FREITEXT (Entscheidung des Nutzers 2026-08-27)
----------------------------------------------------------------------
Gleiche Bauweise wie die Antwort-Stile des Outlook-Add-ins, und aus demselben
Grund: ein Administrator legt sie an, alle sehen dieselben, und was jemand
benutzt hat, ist nachvollziehbar. Ein reiner Freitext je Browser waere nur im
localStorage eines Rechners sichtbar.

**Trotzdem darf jeder eigene anlegen** – ueber das Zahnrad im Fenster. Eigene
Vorlagen gehoeren dem Benutzer und sind fuer niemanden sonst sichtbar; die des
Administrators kann er sehen und benutzen, aber nicht aendern.

DIE VORLAGE BESTIMMT DIE FORM, NICHT DIE BEFUGNIS
-------------------------------------------------
Sie geht als zusaetzlicher Abschnitt in den System-Prompt, HINTER die
Grundaufgabe – dieselbe Reihenfolge und dieselbe Begruendung wie bei den
Antwort-Stilen (Vorfall 2026-08-17: eine Stilvorgabe hob eine
Absender-Bedingung auf). Sie kann nichts freischalten: der Lauf hat ohnehin
keine Werkzeuge.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

# Deckel. Eine Vorlage geht in JEDEN Auftrag – ein Roman darin verdraengt den
# Ticketinhalt aus dem Kontextfenster.
TEXT_MAX = 2000
NAME_MAX = 60
MAX_JE_BENUTZER = 20

_DATEI = Path(__file__).resolve().parent.parent / "data" / "jira_vorlagen.json"

# ── Mitgelieferte Vorschlaege ───────────────────────────────────────────────
# Sie entstehen beim ERSTEN Zugriff, wenn die Datei fehlt – nicht pro fehlender
# Vorlage. Sonst kaeme eine bewusst geloeschte Vorgabe bei jedem Start zurueck
# (dieselbe Regel wie bei den Rollen-Agenten und den E-Mail-Stilen).
VORSCHLAEGE = [
    {
        "name": "Überblick (Standard)",
        "text": ("Fasse den Vorgang für jemanden zusammen, der ihn zum ersten "
                 "Mal sieht: worum es geht, was bisher passiert ist, woran es "
                 "aktuell hängt und was offen bleibt."),
    },
    {
        "name": "Kurz für die Leitung",
        "text": ("Halte dich sehr kurz: höchstens fünf Sätze. Nenne die Lage, "
                 "die Auswirkung für den Kunden und den nächsten Schritt. "
                 "Keine technischen Einzelheiten, keine Namen von Bauteilen "
                 "oder Versionen."),
    },
    {
        "name": "Technisch mit Verlauf",
        "text": ("Gib den technischen Sachstand wieder: Symptom, betroffene "
                 "Komponenten, was bereits geprüft oder ausgeschlossen wurde, "
                 "und welche Spur als Nächstes verfolgt werden sollte. Nenne "
                 "die Stationen des Verlaufs mit Datum, soweit sie im Ticket "
                 "stehen."),
    },
    {
        "name": "Was fehlt uns noch?",
        "text": ("Konzentriere dich ausschließlich darauf, welche Angaben zur "
                 "Bearbeitung fehlen: Welche Fragen sind unbeantwortet, welche "
                 "Daten hat der Melder nicht geliefert, worauf warten wir? "
                 "Formuliere daraus eine kurze Liste konkreter Rückfragen."),
    },
    {
        "name": "Übergabe an Kollegen",
        "text": ("Schreibe eine Übergabe für einen Kollegen, der den Vorgang "
                 "übernimmt: Stand, was bereits zugesagt wurde, womit der "
                 "Kunde rechnet, und was als Nächstes zu tun ist. Weise "
                 "ausdrücklich auf Zusagen mit Termin hin."),
    },
]


class VorlagenFehler(Exception):
    """Fachlicher Fehlschlag mit Text fuer die Oberflaeche."""


def _laden() -> dict:
    if not _DATEI.exists():
        return {"global": [], "benutzer": {}}
    try:
        d = json.loads(_DATEI.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        # Eine beschaedigte Datei darf den Bereich nicht sperren – dann gibt es
        # eben keine Vorlagen. Ueberschrieben wird sie erst beim naechsten
        # Speichern, der Administrator kann sie vorher ansehen.
        return {"global": [], "benutzer": {}}
    if not isinstance(d, dict):
        return {"global": [], "benutzer": {}}
    d.setdefault("global", [])
    d.setdefault("benutzer", {})
    return d


def _speichern(d: dict) -> None:
    _DATEI.parent.mkdir(parents=True, exist_ok=True)
    tmp = _DATEI.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _DATEI)
    try:
        # 0640: die Datei enthaelt keine Zugangsdaten, aber wer sie BESCHREIBEN
        # kann, legt allen Benutzern einen Prompt-Abschnitt in jeden Auftrag.
        _DATEI.chmod(0o640)
    except Exception:  # noqa: BLE001
        pass


def saeen() -> None:
    """Legt die Vorschlaege an – NUR, wenn die Datei noch gar nicht existiert."""
    if _DATEI.exists():
        return
    d = {"global": [], "benutzer": {}}
    for v in VORSCHLAEGE:
        d["global"].append({
            "id": uuid.uuid4().hex[:12],
            "name": v["name"],
            "text": v["text"],
            "erstellt": int(time.time()),
        })
    _speichern(d)


def _pruefe(name: str, text: str) -> tuple:
    n = " ".join(str(name or "").split())[:NAME_MAX]
    t = str(text or "").strip()
    if not n:
        raise VorlagenFehler("Die Vorlage braucht einen Namen.")
    if not t:
        raise VorlagenFehler("Die Vorlage braucht einen Text.")
    if len(t) > TEXT_MAX:
        # ABGELEHNT, nicht gekuerzt: ein stiller Schnitt mitten im Satz aendert
        # die Anweisung, und niemand sieht es.
        raise VorlagenFehler("Der Text ist zu lang (%d von höchstens %d Zeichen)."
                             % (len(t), TEXT_MAX))
    return n, t


def liste(user: str, ist_admin: bool = False) -> dict:
    """Alle Vorlagen, die dieser Benutzer benutzen darf.

    ``global`` sind die des Administrators (nur lesbar, ausser fuer Admins),
    ``eigene`` gehoeren dem Benutzer. Getrennt, weil die Oberflaeche den
    Unterschied zeigen muss: was man aendern kann und was nicht.
    """
    saeen()
    d = _laden()
    return {
        "global": list(d.get("global") or []),
        "eigene": list((d.get("benutzer") or {}).get(_key(user)) or []),
        "darf_global": bool(ist_admin),
    }


def _key(user: str) -> str:
    """Benutzerschluessel – klein und ohne Domaenenanteil.

    Ohne Normalisierung haette dieselbe Person je Anmeldeform (``x`` gegen
    ``firma\\x``) verschiedene Vorlagen; genau diese Klasse Fehler steht im
    Register.
    """
    u = str(user or "").strip().lower()
    if "\\" in u:
        u = u.split("\\", 1)[1]
    if "@" in u:
        u = u.split("@", 1)[0]
    return u or "?"


def speichern(user: str, name: str, text: str, vid: str = "",
              global_: bool = False, ist_admin: bool = False) -> dict:
    """Legt eine Vorlage an oder aendert sie."""
    n, t = _pruefe(name, text)
    if global_ and not ist_admin:
        raise VorlagenFehler("Nur Administratoren dürfen gemeinsame Vorlagen "
                             "anlegen.")
    d = _laden()
    if global_:
        ziel = d.setdefault("global", [])
    else:
        ziel = d.setdefault("benutzer", {}).setdefault(_key(user), [])

    if vid:
        for v in ziel:
            if v.get("id") == vid:
                v["name"], v["text"] = n, t
                _speichern(d)
                return v
        raise VorlagenFehler("Die Vorlage wurde nicht gefunden.")

    if len(ziel) >= MAX_JE_BENUTZER:
        raise VorlagenFehler("Mehr als %d Vorlagen sind nicht vorgesehen."
                             % MAX_JE_BENUTZER)
    neu = {"id": uuid.uuid4().hex[:12], "name": n, "text": t,
           "erstellt": int(time.time())}
    ziel.append(neu)
    _speichern(d)
    return neu


def loeschen(user: str, vid: str, ist_admin: bool = False) -> bool:
    """Loescht eine Vorlage – eine fremde nie.

    Gesucht wird ZUERST bei den eigenen: ein Benutzer soll seine eigene Vorlage
    auch dann loeschen koennen, wenn zufaellig eine globale dieselbe Kennung
    traegt. Eine globale darf nur ein Administrator entfernen.
    """
    d = _laden()
    eigene = d.setdefault("benutzer", {}).setdefault(_key(user), [])
    for i, v in enumerate(eigene):
        if v.get("id") == vid:
            eigene.pop(i)
            _speichern(d)
            return True
    if ist_admin:
        g = d.setdefault("global", [])
        for i, v in enumerate(g):
            if v.get("id") == vid:
                g.pop(i)
                _speichern(d)
                return True
    # Fremd oder unbekannt – in beiden Faellen dieselbe Antwort. Ob eine
    # fremde Vorlage existiert, ist selbst eine Information.
    return False


def text_fuer(user: str, vid: str, ist_admin: bool = False) -> str:
    """Der Prompt-Text einer Vorlage – oder ``""``.

    Gesucht wird nur in dem, was dieser Benutzer benutzen DARF. Damit ist die
    Kennung im Request kein Weg an fremde Vorlagen (sie enthalten zwar keine
    Geheimnisse, aber die Regel kostet nichts).
    """
    if not vid:
        return ""
    d = liste(user, ist_admin)
    for v in (d["eigene"] + d["global"]):
        if v.get("id") == vid:
            return str(v.get("text") or "")[:TEXT_MAX]
    return ""


def markensicher(name: str) -> str:
    """Ein Name, der in einer Abschnittszeile stehen darf."""
    return " ".join(re.sub(r"[=\[\]\r\n]+", " ", str(name or "")).split())[:NAME_MAX]
