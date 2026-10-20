"""Newsfeed: kurze Informationsbloecke, die Administratoren pflegen und /portal zeigt.

WAS ES IST: ein Block hat eine Ueberschrift, einen Text von ein bis drei Saetzen
und ein Erstellungsdatum. Das Portal zeigt die DREI NEUESTEN als Laufband in
einer Kachel: ein Block bleibt ``verweil_s`` Sekunden stehen, rollt dann in
``scroll_s`` Sekunden nach oben hinaus, der naechste rollt hinterher.

⚠ ALLE ZEITSTEMPEL SETZT DER SERVER, NIE DER REQUEST. Sie entscheiden, welche
drei Bloecke zu sehen sind – koennte ein Client sie mitschicken, liesse sich ein
alter Block nach vorn schieben, ohne dass es in der Liste auffaellt.

⚠ EINE BEARBEITUNG IST EINE NEUIGKEIT (Vorgabe des Betreibers 2026-10-20). Die
Reihenfolge haengt am STAND eines Blocks = Zeitpunkt der letzten Bearbeitung,
sonst der Erstellung (``_stand``). Das Erstellungsdatum bleibt dabei stehen und
wird weiter angezeigt. Ohne diese Regel liefe Vorgabe b) ins Leere: ein
deaktivierter aelterer Block wird durch Bearbeiten wieder aktiv – stuende er
nach Erstellung sortiert, kaeme er nie unter die drei sichtbaren.

DEAKTIVIEREN (``aktiv: False``): der Block bleibt im Einstellungs-Reiter
sichtbar und bearbeitbar, erscheint im Portal aber nicht. Wieder aktiv wird er
AUSSCHLIESSLICH durch Bearbeiten – einen eigenen Einschalter gibt es bewusst
nicht. Das Deaktivieren aendert den Stand NICHT: es ist keine Neuigkeit.

AUSBLENDEN (je Benutzer): der Benutzer blendet den Newsfeed bis zu dem STAND
aus, den er gesehen hat. Er erscheint wieder, sobald der neueste sichtbare
Block einen juengeren Stand hat – also nach einer neuen Meldung oder einer
Bearbeitung. Gespeichert wird der Stand, den der CLIENT gezeigt hat, nicht
der aktuelle des Servers: kam zwischen Laden und Klick eine neue Meldung
dazu, wuerde sie sonst ungesehen mit ausgeblendet. Eigene Datei
(``AUSGEBLENDET_DATEI``), damit Benutzerklicks und Admin-Pflege nicht um
dieselbe Datei konkurrieren.

⚠ „EIN BIS DREI SAETZE" WIRD UEBER DIE LAENGE BEGRENZT, NICHT GEZAEHLT. Ein
Satzzaehler ueber Punkte scheitert an „z. B.", „Nr. 5" und „v1.2" und wiese
damit gueltige Texte ab. Der Deckel (``TEXT_MAX``) haelt die Kachel lesbar; der
Hinweis in der Oberflaeche nennt die Vorgabe.

⚠ AUSSERHALB DES BEREICHS WIRD ABGEWIESEN, NICHT STILL BESCHNITTEN. Wer 0,1 s
Verweilzeit eintraegt und danach 1 s sieht, haelt die Einstellung fuer kaputt –
ein stiller Fehlschlag mit Erfolgsmeldung (Register).

Ablage in EINER kleinen Datei (``data/newsfeed.json``), atomar ueber
``backend.atomar`` geschrieben. Bauform wie ``feedback``: Kennungen aus
``secrets``, Deckel je Feld, Sperre um Lesen-Aendern-Schreiben.
"""

from __future__ import annotations

import re
import secrets
import threading
from datetime import datetime
from pathlib import Path

from backend import atomar

_SPERRE = threading.Lock()

# Modulvariable statt Konstante im Funktionsrumpf: die Tests lenken sie in
# einen Sandkasten um.
DATEI = Path("data/newsfeed.json")
AUSGEBLENDET_DATEI = Path("data/newsfeed_ausgeblendet.json")

# ─── Deckel ──────────────────────────────────────────────────────────────────
TITEL_MAX = 80
# Drei normale Saetze passen hinein; mehr liest im Vorbeirollen niemand.
TEXT_MAX = 400
MAX_EINTRAEGE = 100
# So viele Bloecke zeigt das Portal (Vorgabe des Betreibers 2026-10-20).
ANZEIGE_ANZAHL = 3
# Ausblend-Eintraege (je Benutzer einer). Darueber werden die aeltesten verworfen
# – der Benutzer sieht den Newsfeed dann schlimmstenfalls einmal zu viel.
MAX_AUSGEBLENDET = 5000
# Form eines Stands: ISO-Zeitstempel auf die Sekunde, wie ``_jetzt`` ihn schreibt.
_STAND_FORM = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

# ─── Einstellungen: Vorgabe und erlaubter Bereich (Sekunden) ────────────────
VERWEIL_VORGABE = 3.0
VERWEIL_MIN, VERWEIL_MAX = 1.0, 60.0
SCROLL_VORGABE = 0.8
SCROLL_MIN, SCROLL_MAX = 0.2, 5.0

# Steuerzeichen raus, jeder Leerraum (auch ein Zeilenumbruch) wird EIN
# Leerzeichen – das Laufband zeigt Fliesstext, keinen Umbruch.
_STEUER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LEER = re.compile(r"\s+")


class NewsfeedFehler(ValueError):
    """Eine Eingabe, die abgewiesen wird – der Text geht so an die Oberflaeche."""

    pass


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _vorgabe() -> dict:
    return {"einstellungen": {"verweil_s": VERWEIL_VORGABE,
                              "scroll_s": SCROLL_VORGABE},
            "eintraege": []}


def _form_ok(d) -> bool:
    return (isinstance(d, dict) and isinstance(d.get("eintraege", []), list)
            and isinstance(d.get("einstellungen", {}), dict))


def _laden() -> dict:
    """Bestand lesen. Eine unlesbare Datei wirft (``atomar.Unlesbar``) – der
    Aufrufer schreibt dann NICHT, sonst ersetzte die Vorgabe den Bestand."""
    d = atomar.lesen(DATEI, vorgabe=_vorgabe, pruefen=_form_ok)
    d.setdefault("eintraege", [])
    d.setdefault("einstellungen", {})
    return d


def _speichern(d: dict) -> None:
    atomar.schreiben(DATEI, d, modus=0o640)


def _bereinigen(s, deckel: int, feld: str) -> str:
    if s is None:
        s = ""
    if not isinstance(s, str):
        raise NewsfeedFehler(f"{feld}: Text erwartet.")
    s = _LEER.sub(" ", _STEUER.sub("", s)).strip()
    if not s:
        raise NewsfeedFehler(f"{feld} fehlt.")
    if len(s) > deckel:
        raise NewsfeedFehler(f"{feld} ist zu lang ({len(s)} von höchstens {deckel} Zeichen).")
    return s


def _zahl(wert, feld: str, lo: float, hi: float) -> float:
    # bool ist in Python eine Unterklasse von int – True waere sonst 1 Sekunde.
    if isinstance(wert, bool):
        raise NewsfeedFehler(f"{feld}: Zahl erwartet.")
    try:
        z = float(wert)
    except (TypeError, ValueError):
        raise NewsfeedFehler(f"{feld}: Zahl erwartet.") from None
    if z != z or not (lo <= z <= hi):   # z != z: NaN
        raise NewsfeedFehler(f"{feld} muss zwischen {lo:g} und {hi:g} Sekunden liegen.")
    return round(z, 2)


def einstellungen(d: dict | None = None) -> dict:
    """Die wirksamen Einstellungen – fehlende oder kaputte Werte durch die Vorgabe."""
    roh = (d if d is not None else _laden()).get("einstellungen") or {}
    aus = {}
    for feld, vorgabe, lo, hi in (("verweil_s", VERWEIL_VORGABE, VERWEIL_MIN, VERWEIL_MAX),
                                  ("scroll_s", SCROLL_VORGABE, SCROLL_MIN, SCROLL_MAX)):
        try:
            aus[feld] = _zahl(roh.get(feld, vorgabe), feld, lo, hi)
        except NewsfeedFehler:
            aus[feld] = vorgabe
    return aus


def _stand(e: dict) -> str:
    """Zeitpunkt der letzten Bearbeitung, sonst der Erstellung (Modulkopf)."""
    return str(e.get("geaendert") or e.get("erstellt") or "")


def _aktiv(e: dict) -> bool:
    # Fehlt das Feld (Bestand vor 2026-10-20), gilt der Block als aktiv.
    return e.get("aktiv") is not False


def _sortiert(liste: list) -> list:
    # Juengster Stand zuerst. Die Kennung als zweiter Schluessel macht die Folge
    # bei gleicher Sekunde stabil (sonst springt die Anzeige zwischen Abrufen).
    return sorted((e for e in liste if isinstance(e, dict)),
                  key=lambda e: (_stand(e), str(e.get("id") or "")),
                  reverse=True)


def alle() -> list:
    """Alle Bloecke (auch deaktivierte), juengster Stand zuerst – fuer den Reiter."""
    with _SPERRE:
        return _sortiert(_laden()["eintraege"])


def _ausgeblendet_laden() -> dict:
    d = atomar.lesen(AUSGEBLENDET_DATEI, vorgabe=dict,
                     pruefen=lambda x: isinstance(x, dict))
    return d


def anzeige(benutzer: str = "") -> dict:
    """Was das Portal braucht: die neuesten AKTIVEN Bloecke, ihr Stand, ob
    ``benutzer`` diesen Stand ausgeblendet hat, und die Einstellungen.

    ⚠ Eine unlesbare Ausblend-Datei zeigt den Newsfeed (fail-open ist hier
    richtig: das Schlimmste ist eine Meldung, die jemand schon weggeklickt
    hatte – waehrend eine Meldung, die niemand sieht, ihren Zweck verfehlt).
    """
    with _SPERRE:
        d = _laden()
    sichtbar = [e for e in _sortiert(d["eintraege"]) if _aktiv(e)][:ANZEIGE_ANZAHL]
    stand = max((_stand(e) for e in sichtbar), default="")
    weg = False
    if benutzer and stand:
        try:
            gesehen = _ausgeblendet_laden().get(benutzer)
        except atomar.Unlesbar:
            gesehen = None
        weg = isinstance(gesehen, str) and gesehen >= stand
    return {"eintraege": sichtbar, "stand": stand, "ausgeblendet": weg,
            **einstellungen(d)}


def ausblenden(benutzer: str, stand) -> str:
    """Den Newsfeed fuer ``benutzer`` bis ``stand`` (vom Client gezeigt) ausblenden."""
    if not benutzer:
        raise NewsfeedFehler("Benutzer fehlt.")
    if not isinstance(stand, str) or not _STAND_FORM.match(stand):
        raise NewsfeedFehler("Stand fehlt oder hat eine unbekannte Form.")
    with _SPERRE:
        d = _ausgeblendet_laden()
        d.pop(benutzer, None)          # neu ans Ende: Reihenfolge = Alter
        d[benutzer] = stand
        while len(d) > MAX_AUSGEBLENDET:
            d.pop(next(iter(d)))
        atomar.schreiben(AUSGEBLENDET_DATEI, d, modus=0o640)
    return stand


def eintrag_speichern(eid: str, titel, text) -> dict:
    """Block anlegen (``eid`` leer) oder aendern. Unbekannte Kennung → Fehler."""
    titel = _bereinigen(titel, TITEL_MAX, "Überschrift")
    text = _bereinigen(text, TEXT_MAX, "Text")
    with _SPERRE:
        d = _laden()
        liste = d["eintraege"]
        if eid:
            for e in liste:
                if isinstance(e, dict) and e.get("id") == eid:
                    e["titel"], e["text"] = titel, text
                    e["geaendert"] = _jetzt()
                    # Bearbeiten ist der EINZIGE Weg zurueck (Modulkopf).
                    e["aktiv"] = True
                    _speichern(d)
                    return dict(e)
            raise NewsfeedFehler("Der Eintrag wurde nicht gefunden.")
        if len(liste) >= MAX_EINTRAEGE:
            raise NewsfeedFehler(f"Höchstens {MAX_EINTRAEGE} Einträge – bitte alte löschen.")
        e = {"id": secrets.token_hex(6), "erstellt": _jetzt(),
             "titel": titel, "text": text, "aktiv": True}
        liste.append(e)
        _speichern(d)
        return dict(e)


def eintrag_deaktivieren(eid: str) -> dict | None:
    """Block deaktivieren. ``None`` = unbekannte Kennung (nichts geschrieben).

    Der Stand bleibt unveraendert – Deaktivieren ist keine Neuigkeit."""
    with _SPERRE:
        d = _laden()
        for e in d["eintraege"]:
            if isinstance(e, dict) and e.get("id") == eid:
                if _aktiv(e):
                    e["aktiv"] = False
                    _speichern(d)
                return dict(e)
        return None


def eintrag_loeschen(eid: str) -> bool:
    """Block entfernen. ``False`` = unbekannte Kennung (nichts geschrieben)."""
    with _SPERRE:
        d = _laden()
        vorher = len(d["eintraege"])
        d["eintraege"] = [e for e in d["eintraege"]
                          if not (isinstance(e, dict) and e.get("id") == eid)]
        if len(d["eintraege"]) == vorher:
            return False
        _speichern(d)
        return True


def einstellungen_setzen(verweil_s, scroll_s) -> dict:
    """Verweil- und Scrolldauer setzen (Sekunden). Ausserhalb → Fehler."""
    neu = {"verweil_s": _zahl(verweil_s, "Verweilzeit", VERWEIL_MIN, VERWEIL_MAX),
           "scroll_s": _zahl(scroll_s, "Scrolldauer", SCROLL_MIN, SCROLL_MAX)}
    with _SPERRE:
        d = _laden()
        d["einstellungen"] = neu
        _speichern(d)
    return dict(neu)
