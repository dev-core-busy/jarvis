"""Feedback-Formulare: der Administrator definiert Spalten, der Benutzer fuellt Zeilen.

WAS ES IST: ein Formular ist eine Tabelle nach Excel-Vorbild. Der Administrator
legt die SPALTEN fest (Name + Typ), der Benutzer legt beliebig viele ZEILEN an,
fuellt sie aus und sendet sie ab. Drei Spaltentypen:

    ``text``    ein Eingabefeld
    ``sterne``  eine 5-Sterne-Bewertung (0 = nicht bewertet)
    ``fest``    nur zu lesender Text, vom Administrator je ZEILE vorgegeben

ZWEI BAUFORMEN, und die zweite haengt am Typ ``fest`` (Vorgabe des Betreibers
2026-09-15):

    OHNE feste Zeilen  der Benutzer legt beliebig viele Zeilen an (Bestand)
    MIT festen Zeilen  der Administrator gibt die Zeilen vor – ein
                       Bewertungsbogen: Kriterium | Anmerkung | Bewertung

⚠ ``fest`` UND FESTE ZEILEN GEHOEREN ZUSAMMEN. Eine ``fest``-Spalte in einem
Formular ohne vorgegebene Zeilen waere genau der Widerspruch, den der Betreiber
beim Bau gestrichen hat: der Benutzer legt eine Zeile an, und die Zelle ist
leer und nicht ausfuellbar. ``formular_speichern`` weist das deshalb ab. Feste
Zeilen OHNE ``fest``-Spalte sind dagegen zulaessig – dann sind es schlicht
nummerierte Zeilen, die der Benutzer nicht vermehren kann.

⚠ DER TEXT EINER ``fest``-ZELLE KOMMT AUS DER DEFINITION, NIE AUS DEM REQUEST.
Das ist die tragende Zusage dieses Typs: koennte ein Client ihn mitschicken,
stuende im Export eine Bewertung unter einer Frage, die so nie gestellt wurde –
und niemand koennte das erkennen, weil die Abgabe ihren eigenen Snapshot traegt.

⚠ ES LAEUFT KEIN MODELL. Eine Abgabe wird gespeichert, mehr nicht (Vorgabe des
Betreibers 2026-09-14). Das ist keine Sparmassnahme, sondern der Zuschnitt: die
Zeilen sind Fremdtext von Benutzern, und ein Modellaufruf je Abgabe waere Kosten
und Wartezeit fuer eine Auswertung, die niemand angefordert hat. Wer spaeter
zusammenfassen will, tut das ueber die gespeicherten Abgaben – die Ablage
aendert sich dafuer nicht.

ZWEI DATEIEN, UND DAS IST ABSICHT:

    ``data/feedback_formulare.json``  Definitionen. Klein, wird BEARBEITET.
    ``data/feedback_abgaben.jsonl``   Abgaben. Waechst, wird nur ANGEHAENGT.

Eine gemeinsame Datei muesste bei jeder Abgabe komplett neu geschrieben werden –
dieselbe Lehre wie beim LLM-Verlauf (``conv_log``): Anhaengen kostet unabhaengig
von der Historie gleich viel. Gekappt wird nur, wenn der Deckel wirklich
erreicht ist.

Bauart der Definitionen 1:1 wie ``ai_mouse_fragen``/``jira_vorlagen``: eine
Datei, Kennungen aus ``secrets``, Deckel je Feld, atomar geschrieben, 0640.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path

_SPERRE = threading.Lock()

# ─── Deckel ──────────────────────────────────────────────────────────────────
# Jede Zahl steht fuer eine Bedienbarkeitsgrenze, nicht fuer eine technische:
# ein Formular mit 30 Spalten passt auf keinen Bildschirm, und eine Abgabe mit
# 500 Zeilen liest niemand mehr.
TITEL_MAX = 100
BESCHREIBUNG_MAX = 1000
SPALTE_NAME_MAX = 60
ZELLE_MAX = 2000
MAX_FORMULARE = 40
MAX_SPALTEN = 12
MAX_ZEILEN = 200
# Feste Zeilen sind eine DEFINITION, keine Abgabe – eigener Deckel. 50 Zeilen
# sind ein langer Bewertungsbogen; darueber fuellt ihn niemand mehr aus.
MAX_FESTE_ZEILEN = 50
# Gesamtbestand. Wird er ueberschritten, fallen die AELTESTEN Abgaben heraus –
# und das wird protokolliert, nicht stillschweigend getan.
MAX_ABGABEN = 5000

# Die Spaltentypen. Als Konstante, weil sie an DREI Stellen gebraucht werden
# (Pruefung beim Anlegen, Pruefung der Zellwerte, Katalog fuer die Oberflaeche).
TYP_TEXT = "text"
TYP_STERNE = "sterne"
TYP_FEST = "fest"
SPALTEN_TYPEN = (TYP_TEXT, TYP_STERNE, TYP_FEST)
STERNE_MAX = 5

# ⚠ SCHLUESSEL DER ZEILEN-KENNUNG IN EINER ABGEGEBENEN ZEILE. Er steht neben
# den Spalten-Kennungen im selben dict; eine Kollision ist ausgeschlossen, weil
# Spalten-Kennungen `isalnum()` sind (siehe `_spalten_pruefen`) und dieser
# Schluessel mit `_` beginnt.
#
# Warum ueberhaupt: der feste Text kann spaeter umformuliert werden. Ohne
# Kennung liesse sich „Zeile 3 ueber alle Abgaben hinweg" dann nicht mehr
# beantworten – man haette nur noch zwei verschiedene Texte und keinen Beleg,
# dass dieselbe Frage gemeint war.
ZEILEN_ID = "_zid"

# ⚠ KENNUNGEN DUERFEN AUS DEM REQUEST KOMMEN – sie MUESSEN es sogar: beim
# ANLEGEN eines Formulars mit festen Zeilen braucht der Client die
# Spalten-Kennung bereits, um die Zeilenwerte darunter abzulegen. Er vergibt sie
# deshalb selbst, der Server uebernimmt sie (siehe `_spalten_pruefen`).
#
# Damit ist sie Fremdeingabe, und eine Laengengrenze gehoert dazu: ohne sie
# waeren zwoelf Spalten mit je einem Megabyte Kennung moeglich, und die
# Kennung steht in JEDER Zelle JEDER Abgabe.
_ID_MAX = 32

# Sentinel fuer `formular_speichern(zeilen=...)`: `None` heisst „keine festen
# Zeilen", NICHT ANGEGEBEN heisst „die vorhandenen behalten". Ohne die
# Unterscheidung wuerde ein aelterer Client (halber Deploy) beim Speichern eines
# Titels sämtliche festen Zeilen loeschen.
_ZEILEN_UNGESETZT = object()


class FeedbackFehler(Exception):
    """Fachlicher Fehlschlag mit Text fuer die Oberflaeche."""


def _pfad_formulare() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "feedback_formulare.json"


def _pfad_abgaben() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "feedback_abgaben.jsonl"


def _norm(user: str) -> str:
    """Benutzerschluessel. Ohne Normierung stuende derselbe Mensch je nach
    Tippform mehrfach im Bestand (Register: ``_norm_login``)."""
    u = (user or "").strip().lower()
    if "\\" in u:
        u = u.split("\\", 1)[1]
    if "@" in u:
        u = u.split("@", 1)[0]
    return u


# ═══════════════════════════════════════════════════════════════════════════
#  Formulare (Definitionen)
# ═══════════════════════════════════════════════════════════════════════════

def _laden() -> dict:
    """Bestand lesen. **Streng**: eine beschaedigte Datei wird NICHT ersetzt.

    Ein Parse-Fehler gibt einen leeren Bestand zurueck, damit der Bereich nicht
    sperrt – geschrieben wird aber nur, was der Aufrufer wirklich geaendert hat.
    Eine Automatik, die eine kaputte Datei stillschweigend durch eine leere
    ersetzt, vernichtet die Arbeit des Administrators (Regel aus
    ``ai_mouse_fragen._laden``).
    """
    p = _pfad_formulare()
    if not p.is_file():
        return {"version": 1, "formulare": []}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"version": 1, "formulare": []}
    if not isinstance(d, dict):
        return {"version": 1, "formulare": []}
    if not isinstance(d.get("formulare"), list):
        d["formulare"] = []
    return d


def _speichern(d: dict) -> None:
    """Atomar schreiben, Rechte 0640.

    0640, weil ein Formular Betriebswissen enthaelt (Modulnamen, interne
    Bezeichnungen) – der Sandbox-Benutzer hat darauf nichts zu suchen.
    """
    p = _pfad_formulare()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o640)
    except Exception:  # noqa: BLE001
        pass
    os.replace(tmp, p)


def _spalten_pruefen(roh) -> list[dict]:
    """Die Spaltenliste aus dem Request pruefen und normieren.

    ⚠ DIE KENNUNG WIRD UEBERNOMMEN, WENN SIE MITKOMMT. Das ist die ganze
    Voraussetzung dafuer, dass bestehende Abgaben nach einer Umbenennung noch
    zuzuordnen sind: eine Abgabe speichert die Zellen unter der SPALTEN-Kennung,
    nicht unter dem Namen. Wer beim Bearbeiten neue Kennungen vergibt, macht
    jede vorhandene Abgabe unlesbar – dieselbe Lehre wie beim Verschieben einer
    Jira-Vorlage zwischen eigen und gemeinsam.
    """
    if not isinstance(roh, list):
        raise FeedbackFehler("Die Spalten fehlen oder sind keine Liste.")
    if len(roh) > MAX_SPALTEN:
        raise FeedbackFehler("Es sind hoechstens %d Spalten moeglich." % MAX_SPALTEN)
    raus: list[dict] = []
    gesehen: set[str] = set()
    for e in roh:
        if not isinstance(e, dict):
            continue
        name = str(e.get("name") or "").strip()[:SPALTE_NAME_MAX]
        typ = str(e.get("typ") or "").strip()
        if not name:
            raise FeedbackFehler("Jede Spalte braucht eine Ueberschrift.")
        if typ not in SPALTEN_TYPEN:
            raise FeedbackFehler(
                "Unbekannter Spaltentyp „%s“. Moeglich sind: %s."
                % (typ, ", ".join(SPALTEN_TYPEN)))
        sid = str(e.get("id") or "").strip()
        # Eine doppelte oder unbrauchbare Kennung wird NEU vergeben statt
        # abgewiesen: sie kommt aus dem Request, und ein Formular, das sich
        # wegen einer Kennung nicht speichern laesst, waere eine Sackgasse.
        if not sid or sid in gesehen or not sid.isalnum() or len(sid) > _ID_MAX:
            sid = secrets.token_hex(4)
            while sid in gesehen:
                sid = secrets.token_hex(4)
        gesehen.add(sid)
        raus.append({"id": sid, "name": name, "typ": typ})
    if not raus:
        raise FeedbackFehler("Ein Formular braucht mindestens eine Spalte.")
    # ⚠ EIN FORMULAR NUR AUS `fest`-SPALTEN IST EINE SACKGASSE: der Benutzer
    # kann nichts eintragen, damit ist keine Zeile ausgefuellt, damit laesst
    # sich nie absenden. Lieber beim Anlegen abweisen als den Benutzer vor eine
    # Fehlermeldung laufen lassen, deren Ursache er nicht beheben kann.
    if all(s["typ"] == TYP_FEST for s in raus):
        raise FeedbackFehler(
            "Mindestens eine Spalte muss ausfuellbar sein (Text oder Bewertung) – "
            "sonst kann der Benutzer nichts abgeben.")
    return raus


def _feste_zeilen_pruefen(spalten: list[dict], roh) -> list[dict]:
    """Die vom Administrator vorgegebenen Zeilen pruefen und normieren.

    Aufbau je Zeile: ``{"id": <hex>, "werte": {<spalten_id>: <text>}}``.

    ⚠ WERTE GIBT ES NUR FUER ``fest``-SPALTEN. Ein Vorgabewert fuer eine Text-
    oder Sterne-Spalte waere eine VORBELEGUNG – also etwas anderes als das hier
    Bestellte, und er saehe in der Abgabe wie eine Eingabe des Benutzers aus.
    Fremde Schluessel werden deshalb verworfen, nicht gespeichert.

    ⚠ DIE KENNUNG WIRD UEBERNOMMEN, WENN SIE MITKOMMT – gleiche Begruendung wie
    bei den Spalten: die Abgaben zeigen ueber `ZEILEN_ID` darauf, und eine neu
    vergebene Kennung macht die Zuordnung zu allen bisherigen Abgaben kaputt.
    """
    if roh is None:
        return []
    if not isinstance(roh, list):
        raise FeedbackFehler("Die festen Zeilen sind keine Liste.")
    if len(roh) > MAX_FESTE_ZEILEN:
        raise FeedbackFehler("Es sind hoechstens %d feste Zeilen moeglich."
                             % MAX_FESTE_ZEILEN)
    fest_ids = [s["id"] for s in spalten if s["typ"] == TYP_FEST]
    raus: list[dict] = []
    gesehen: set[str] = set()
    for e in roh:
        if not isinstance(e, dict):
            continue
        roh_werte = e.get("werte")
        werte: dict = {}
        if isinstance(roh_werte, dict):
            for sid in fest_ids:
                werte[sid] = str(roh_werte.get(sid) or "").strip()[:ZELLE_MAX]
        # Eine Zeile ohne jeden Text ist keine Zeile: in einem Bewertungsbogen
        # waere sie eine unbeschriftete Zeile, die niemand zuordnen kann. Sie
        # faellt heraus statt das Speichern scheitern zu lassen – der
        # Administrator hat sie schlicht nicht gefuellt.
        if fest_ids and not any(werte.values()):
            continue
        zid = str(e.get("id") or "").strip()
        if not zid or zid in gesehen or not zid.isalnum() or len(zid) > _ID_MAX:
            zid = secrets.token_hex(4)
            while zid in gesehen:
                zid = secrets.token_hex(4)
        gesehen.add(zid)
        raus.append({"id": zid, "werte": werte})
    return raus


def formulare(nur_aktive: bool = False) -> list[dict]:
    """Alle Formulare. ``nur_aktive`` fuer die Benutzer-Ansicht."""
    with _SPERRE:
        d = _laden()
        raus = [dict(f) for f in d["formulare"] if isinstance(f, dict)]
    if nur_aktive:
        # `is not False`, NICHT Falsyness: ein Altbestand ohne das Feld gilt als
        # aktiv – sonst waeren nach einem Update alle Formulare verschwunden.
        raus = [f for f in raus if f.get("aktiv") is not False]
    return raus


def formular(fid: str) -> dict | None:
    """Ein Formular oder ``None``."""
    for f in formulare():
        if f.get("id") == fid:
            return f
    return None


def formular_speichern(fid: str, titel: str, beschreibung: str,
                       spalten, aktiv: bool = True,
                       zeilen=_ZEILEN_UNGESETZT) -> dict:
    """Formular anlegen (``fid`` leer) oder aendern.

    Die Rechtefrage steht beim AUFRUFER (``require_local_auth`` am Endpunkt) –
    hier liegt nur die Datenhaltung, wie im uebrigen Modul.

    ``zeilen`` sind die vom Administrator vorgegebenen FESTEN Zeilen. Nicht
    angegeben = die vorhandenen behalten (siehe ``_ZEILEN_UNGESETZT``); ``None``
    oder leere Liste = keine festen Zeilen, der Benutzer legt sie selbst an.
    """
    t = (titel or "").strip()[:TITEL_MAX]
    b = (beschreibung or "").strip()[:BESCHREIBUNG_MAX]
    if not t:
        raise FeedbackFehler("Das Formular braucht einen Titel – "
                             "er steht in der Auswahl des Benutzers.")
    sp = _spalten_pruefen(spalten)
    with _SPERRE:
        d = _laden()
        liste = d["formulare"]
        alt = next((f for f in liste if f.get("id") == fid), None) if fid else None
        if fid and alt is None:
            raise FeedbackFehler("Das Formular wurde nicht gefunden.")
        if zeilen is _ZEILEN_UNGESETZT:
            # Bestand uebernehmen und gegen die NEUEN Spalten pruefen: wurde
            # eine `fest`-Spalte entfernt, faellt ihr Text hier heraus.
            vorhanden = (alt or {}).get("zeilen") or []
        else:
            vorhanden = zeilen
        fz = _feste_zeilen_pruefen(sp, vorhanden)
        # ⚠ DIE EINE REGEL, die den Widerspruch aufloest (siehe Modul-Docstring).
        # Sie steht HIER und nicht in `_spalten_pruefen`, weil sie beide Seiten
        # braucht – Spalten allein koennen sie nicht beantworten.
        if any(s["typ"] == TYP_FEST for s in sp) and not fz:
            raise FeedbackFehler(
                "Eine Spalte vom Typ „fester Text“ braucht vorgegebene Zeilen – "
                "sonst bliebe die Zelle leer und der Benutzer koennte sie nicht "
                "fuellen. Lege unter „Feste Zeilen“ mindestens eine an.")
        if alt is not None:
            alt.update({"titel": t, "beschreibung": b, "spalten": sp,
                        "aktiv": bool(aktiv), "zeilen": fz})
            eintrag = alt
        else:
            if len(liste) >= MAX_FORMULARE:
                raise FeedbackFehler("Es sind hoechstens %d Formulare moeglich."
                                     % MAX_FORMULARE)
            eintrag = {"id": secrets.token_hex(6), "titel": t, "beschreibung": b,
                       "spalten": sp, "zeilen": fz, "aktiv": bool(aktiv),
                       "erstellt": datetime.now().isoformat(timespec="seconds")}
            liste.append(eintrag)
        _speichern(d)
    return dict(eintrag)


def formular_loeschen(fid: str) -> bool:
    """Ein Formular entfernen. Unbekannt → ``False`` (Aufrufer: 404).

    ⚠ DIE ABGABEN BLEIBEN LIEGEN und werden NICHT mitgeloescht. Sie sind das
    Ergebnis der Arbeit von Benutzern; ein Klick auf „Formular loeschen“ darf
    sie nicht mitnehmen. Sichtbar bleiben sie in der Auswertung (dort steht
    dann der Formularname aus der Abgabe selbst) und im CSV-Export.
    """
    with _SPERRE:
        d = _laden()
        if not any(f.get("id") == fid for f in d["formulare"]):
            return False
        d["formulare"] = [f for f in d["formulare"] if f.get("id") != fid]
        _speichern(d)
    return True


def formulare_sortieren(ids: list) -> int:
    """Die Reihenfolge der Formulare setzen. Rueckgabe: Anzahl bewegter Eintraege.

    ⚠ TOLERANT IN BEIDE RICHTUNGEN (Regel aus ``ai_mouse_fragen.sortieren``):
    zwischen dem Zeichnen der Liste und dem Ablegen kann ein Formular geloescht
    oder ein neues angelegt worden sein. Unbekannte Kennungen werden
    **verworfen, nicht geraten**; nicht genannte Eintraege behalten ihre Folge
    und landen **hinten** – so verschwindet kein Formular, nur weil die
    Oberflaeche es nicht kannte.
    """
    gewuenscht = [str(x) for x in (ids or []) if isinstance(x, (str, int))]
    if not gewuenscht:
        return 0
    with _SPERRE:
        d = _laden()
        vorhanden = [f for f in d["formulare"] if isinstance(f, dict)]
        nach_id: dict = {}
        for f in vorhanden:
            k = f.get("id")
            if k is not None and k not in nach_id:
                nach_id[k] = f
        raus, gesehen = [], set()
        for k in gewuenscht:
            f = nach_id.get(k)
            if f is not None and k not in gesehen:
                raus.append(f)
                gesehen.add(k)
        raus += [f for f in vorhanden if f.get("id") not in gesehen]
        if [f.get("id") for f in raus] == [f.get("id") for f in vorhanden]:
            return 0
        d["formulare"] = raus
        _speichern(d)
    return len(raus)


# ═══════════════════════════════════════════════════════════════════════════
#  Abgaben
# ═══════════════════════════════════════════════════════════════════════════

def _zelle_pruefen(spalte: dict, wert) -> tuple[str, object]:
    """Einen Zellwert gegen die SPALTENDEFINITION pruefen.

    Rueckgabe ``(anzeige, gespeicherter_wert)`` – ``anzeige`` ist die Fassung
    fuer CSV und Auswertung, ``gespeichert`` die typgerechte.

    ⚠ DER TYP ENTSCHEIDET, NICHT DER GESENDETE WERT. Ein Client kann in eine
    Sterne-Spalte einen Text schicken; ohne diese Pruefung stuende der spaeter
    in einer Auswertung, die Zahlen erwartet.
    """
    typ = spalte.get("typ")
    if typ == TYP_FEST:
        # Darf hier gar nicht ankommen: der Wert einer `fest`-Zelle kommt aus
        # der Definition (`_zeilen_fest_pruefen`), nie aus dem Request. Der
        # Zweig ist die Notbremse, falls kuenftig jemand eine `fest`-Spalte
        # durch den freien Zeilen-Weg schickt – dann steht dort NICHTS, statt
        # dass der Client die Frage bestimmt.
        return "", ""
    if typ == TYP_STERNE:
        try:
            n = int(wert)
        except Exception:  # noqa: BLE001
            n = 0
        # Begrenzen statt abweisen: eine 7 aus einem alten Client soll die
        # Abgabe nicht scheitern lassen, sie ist nur keine 7.
        n = max(0, min(STERNE_MAX, n))
        return (str(n) if n else ""), n
    text = ("" if wert is None else str(wert)).strip()[:ZELLE_MAX]
    return text, text


def _zeilen_pruefen(spalten: list[dict], roh) -> list[dict]:
    """Die Zeilen einer Abgabe pruefen.

    ⚠ UNBEKANNTE SPALTEN WERDEN VERWORFEN. Die Zellen kommen aus dem Request;
    ohne diese Schranke schriebe ein Aufrufer beliebige Felder in die Ablage,
    die spaeter niemand mehr zuordnen kann.

    ⚠ LEERE ZEILEN FALLEN HERAUS – aber erst NACH der Pruefung. Wer auf
    „+ Zeile“ drueckt und sie nicht fuellt, soll keine leere Zeile abgeben;
    eine Zeile mit nur einem Stern ist dagegen eine Aussage und bleibt.
    """
    if not isinstance(roh, list):
        raise FeedbackFehler("Die Zeilen fehlen oder sind keine Liste.")
    if len(roh) > MAX_ZEILEN:
        raise FeedbackFehler("Es sind hoechstens %d Zeilen moeglich." % MAX_ZEILEN)
    raus: list[dict] = []
    for z in roh:
        if not isinstance(z, dict):
            continue
        zeile: dict = {}
        gefuellt = False
        for sp in spalten:
            anzeige, wert = _zelle_pruefen(sp, z.get(sp["id"]))
            zeile[sp["id"]] = wert
            if anzeige:
                gefuellt = True
        if gefuellt:
            raus.append(zeile)
    if not raus:
        raise FeedbackFehler("Es ist keine einzige Zeile ausgefuellt.")
    return raus


def _zeilen_fest_pruefen(spalten: list[dict], feste: list[dict], roh) -> list[dict]:
    """Die Zeilen einer Abgabe zu einem Formular mit FESTEN Zeilen.

    ⚠ DIE REIHENFOLGE UND DIE MENGE KOMMEN AUS DER DEFINITION, nicht aus dem
    Request. Der Client liefert nur die ausgefuellten Zellen und sagt ueber
    ``ZEILEN_ID``, zu welcher Zeile sie gehoeren; alles andere wird verworfen.
    Damit hat JEDE Abgabe zu diesem Formular dieselbe Struktur – genau das
    macht sie ueber Benutzer hinweg vergleichbar, und es ist der Grund, warum
    der Betreiber zusaetzliche freie Zeilen ausgeschlossen hat.

    ⚠ ALLE festen Zeilen werden gespeichert, auch die leer gebliebenen. Wer zu
    einem Kriterium nichts sagt, hinterlaesst eine leere Zelle – im Export steht
    sie unter ihrer Ueberschrift und ist als „nicht beantwortet" lesbar. Faellt
    sie dagegen heraus, verschieben sich die Zeilen zwischen zwei Abgaben, und
    eine Auswertung vergliche Kriterium 3 mit Kriterium 4.

    Ausgefuellt sein muss trotzdem MINDESTENS EINE Zeile (Vorgabe des
    Betreibers: keine Pflicht je Zeile) – sonst waere ein leeres Formular
    abzusenden.
    """
    if roh is not None and not isinstance(roh, list):
        raise FeedbackFehler("Die Zeilen fehlen oder sind keine Liste.")
    eingang: dict = {}
    for z in (roh or []):
        if not isinstance(z, dict):
            continue
        zid = str(z.get(ZEILEN_ID) or "").strip()
        if zid:
            eingang[zid] = z

    raus: list[dict] = []
    gefuellt = False
    for fz in feste:
        geliefert = eingang.get(fz["id"]) or {}
        zeile: dict = {ZEILEN_ID: fz["id"]}
        for sp in spalten:
            if sp["typ"] == TYP_FEST:
                # AUS DER DEFINITION. Siehe Modul-Docstring.
                zeile[sp["id"]] = (fz.get("werte") or {}).get(sp["id"], "")
                continue
            anzeige, wert = _zelle_pruefen(sp, geliefert.get(sp["id"]))
            zeile[sp["id"]] = wert
            if anzeige:
                gefuellt = True
        raus.append(zeile)
    if not gefuellt:
        raise FeedbackFehler("Es ist keine einzige Zeile ausgefuellt.")
    return raus


def _abgaben_lesen() -> list[dict]:
    """Alle Abgaben. Beschaedigte Zeilen werden UEBERSPRUNGEN, nicht verworfen.

    Eine kaputte Zeile darf die uebrigen nicht mitnehmen – bei einer
    JSON-Lines-Datei ist genau das der Vorteil gegenueber einem grossen
    JSON-Dokument.
    """
    p = _pfad_abgaben()
    if not p.is_file():
        return []
    raus: list[dict] = []
    try:
        with p.open("r", encoding="utf-8") as fh:
            for zeile in fh:
                zeile = zeile.strip()
                if not zeile:
                    continue
                try:
                    e = json.loads(zeile)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(e, dict):
                    raus.append(e)
    except Exception:  # noqa: BLE001
        return raus
    return raus


def _abgaben_schreiben(eintraege: list[dict]) -> None:
    """Die Abgaben-Datei vollstaendig neu schreiben (Loeschen, Kappen).

    Der Regelweg ist ANHAENGEN (``abgabe_speichern``) – hier landet nur, was
    die Datei wirklich umbaut. Atomar, damit ein Abbruch nicht die halbe Datei
    hinterlaesst.
    """
    p = _pfad_abgaben()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for e in eintraege:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    try:
        os.chmod(tmp, 0o640)
    except Exception:  # noqa: BLE001
        pass
    os.replace(tmp, p)


def abgabe_speichern(user: str, fid: str, zeilen) -> dict:
    """Eine ausgefuellte Abgabe ablegen.

    ⚠ DER BENUTZER KOMMT VOM AUFRUFER AUS DER ANMELDUNG, nie aus dem Rumpf –
    sonst waere der Endpunkt der bequemste Weg, einem Kollegen eine Abgabe
    unterzuschieben (gleiche Regel wie beim Empfaenger einer Erinnerung).

    ⚠ DIE SPALTEN WERDEN MITGESPEICHERT. Das ist Redundanz mit Absicht: benennt
    der Administrator spaeter eine Spalte um oder entfernt sie, waere die
    Abgabe sonst falsch beschriftet – echte Daten unter einer Ueberschrift, die
    zum Zeitpunkt der Abgabe gar nicht galt. Der Snapshot ist klein (hoechstens
    MAX_SPALTEN Eintraege) und die einzige Moeglichkeit, eine Abgabe spaeter
    richtig zu lesen.
    """
    f = formular(fid)
    if f is None:
        raise FeedbackFehler("Das Formular wurde nicht gefunden.")
    if f.get("aktiv") is False:
        raise FeedbackFehler("Dieses Formular nimmt zurzeit keine Abgaben an.")
    spalten = [s for s in (f.get("spalten") or []) if isinstance(s, dict)]
    if not spalten:
        raise FeedbackFehler("Das Formular hat keine Spalten.")
    feste = [z for z in (f.get("zeilen") or []) if isinstance(z, dict) and z.get("id")]
    if feste:
        geprueft = _zeilen_fest_pruefen(spalten, feste, zeilen)
    else:
        geprueft = _zeilen_pruefen(spalten, zeilen)
    eintrag = {
        "id": secrets.token_hex(8),
        "formular_id": fid,
        # Snapshot: siehe Docstring.
        "formular_titel": f.get("titel") or "",
        "spalten": [{"id": s["id"], "name": s["name"], "typ": s["typ"]}
                    for s in spalten],
        "benutzer": _norm(user),
        "zeit": datetime.now().isoformat(timespec="seconds"),
        "zeilen": geprueft,
    }
    with _SPERRE:
        p = _pfad_abgaben()
        p.parent.mkdir(parents=True, exist_ok=True)
        neu = not p.exists()
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
        if neu:
            try:
                os.chmod(p, 0o640)
            except Exception:  # noqa: BLE001
                pass
        # Kappen nur, wenn der Deckel wirklich erreicht ist – das kostet ein
        # Neuschreiben und passiert deshalb selten.
        alle = _abgaben_lesen()
        if len(alle) > MAX_ABGABEN:
            _abgaben_schreiben(alle[-MAX_ABGABEN:])
    return eintrag


def abgaben(fid: str = "", user: str = "", nur_eigene: bool = False,
            limit: int = 500) -> list[dict]:
    """Abgaben lesen – neueste zuerst.

    ``nur_eigene`` ist die Schranke fuer die Benutzer-Ansicht und wird vom
    AUFRUFER gesetzt (der kennt die Rechtelage). Sie filtert auf den
    **normierten** Benutzer, damit derselbe Mensch seine Abgabe auch nach einer
    anderen Anmeldeschreibweise wiederfindet.
    """
    raus = _abgaben_lesen()
    if fid:
        raus = [a for a in raus if a.get("formular_id") == fid]
    if nur_eigene:
        k = _norm(user)
        raus = [a for a in raus if a.get("benutzer") == k]
    raus.reverse()
    if limit and limit > 0:
        raus = raus[:limit]
    return raus


def abgabe_loeschen(aid: str) -> bool:
    """Eine Abgabe entfernen. Unbekannt → ``False`` (Aufrufer: 404).

    Nur fuer Administratoren (geprueft am Endpunkt): eine Abgabe ist ein
    Ergebnis, kein Entwurf.
    """
    with _SPERRE:
        alle = _abgaben_lesen()
        if not any(a.get("id") == aid for a in alle):
            return False
        _abgaben_schreiben([a for a in alle if a.get("id") != aid])
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  CSV-Export
# ═══════════════════════════════════════════════════════════════════════════

# ⚠ CSV-INJECTION. Excel und LibreOffice werten eine Zelle als FORMEL aus, wenn
# sie mit einem dieser Zeichen beginnt – `=cmd|'/c calc'!A1` ist der bekannte
# Fall. Der Inhalt hier stammt von Benutzern und wird von einem Administrator
# in Excel geoeffnet: ohne Entschaerfung waere der Export ein Weg, auf dessen
# Rechner etwas auszufuehren. Ein Anfuehrungszeichen um den Wert hilft NICHT,
# die Auswertung findet danach statt.
_CSV_GEFAEHRLICH = ("=", "+", "-", "@", "\t", "\r")


def csv_zelle(wert) -> str:
    """Einen Zellwert fuer CSV entschaerfen.

    Ein fuehrendes Apostroph macht aus der Formel Text. Es ist in der Zelle
    SICHTBAR – das ist der bewusste Preis: eine sichtbare Zelle, die harmlos
    ist, schlaegt eine unsichtbare, die ausgefuehrt wird. Betroffen sind nur
    Werte, die wirklich mit einem dieser Zeichen anfangen; eine gewoehnliche
    Zahl oder ein Satz bleibt unangetastet.
    """
    s = "" if wert is None else str(wert)
    if s.startswith(_CSV_GEFAEHRLICH):
        return "'" + s
    return s


def csv_export(fid: str) -> tuple[str, str]:
    """Alle Abgaben eines Formulars als CSV. Rueckgabe ``(dateiname, inhalt)``.

    EINE ZEILE JE FORMULAR-ZEILE, nicht je Abgabe: nur so laesst sich in Excel
    filtern, sortieren und eine Pivot-Tabelle bauen. Die Zugehoerigkeit steht
    in den ersten vier Spalten.

    ⚠ DIE KOPFZEILE IST DIE VEREINIGUNG aus den heutigen Spalten und denen, die
    in den Abgaben vorkommen. Wird eine Spalte spaeter entfernt, stuenden ihre
    Werte sonst nirgends – ein Export, der stillschweigend Daten weglaesst, ist
    schlimmer als eine Spalte zu viel. Die entfallenen tragen den Zusatz
    „(entfernt)“, damit niemand sie fuer aktuell haelt.

    ⚠ TRENNZEICHEN `;` UND BOM: ein deutsches Excel oeffnet eine UTF-8-Datei
    ohne BOM mit zerstoerten Umlauten und trennt an `,` gar nicht. Beides ist
    kein Schoenheitsfehler, sondern der Unterschied zwischen „laesst sich
    oeffnen“ und „muss von Hand importiert werden“.
    """
    import csv  # noqa: PLC0415  (nur hier gebraucht)
    import io  # noqa: PLC0415

    f = formular(fid)
    liste = abgaben(fid=fid, limit=0)
    # Spaltenreihenfolge: erst die heutigen, dann die nur noch historischen.
    spalten: list[dict] = []
    gesehen: set[str] = set()
    for s in ((f or {}).get("spalten") or []):
        if isinstance(s, dict) and s.get("id") not in gesehen:
            spalten.append({"id": s["id"], "name": s.get("name") or s["id"]})
            gesehen.add(s["id"])
    for a in liste:
        for s in (a.get("spalten") or []):
            if isinstance(s, dict) and s.get("id") and s["id"] not in gesehen:
                spalten.append({"id": s["id"],
                                "name": (s.get("name") or s["id"]) + " (entfernt)"})
                gesehen.add(s["id"])

    puffer = io.StringIO()
    # `\r\n` ist das CSV-Zeilenende laut RFC 4180 und das, was Excel erwartet.
    schreiber = csv.writer(puffer, delimiter=";", quoting=csv.QUOTE_MINIMAL,
                           lineterminator="\r\n")
    schreiber.writerow(["Zeitpunkt", "Benutzer", "Abgabe", "Zeile"]
                       + [csv_zelle(s["name"]) for s in spalten])
    # Aelteste zuerst: eine Auswertung liest man chronologisch (`abgaben()`
    # liefert neueste zuerst, das ist die Reihenfolge fuer die ANZEIGE).
    for a in reversed(liste):
        for i, z in enumerate(a.get("zeilen") or [], start=1):
            if not isinstance(z, dict):
                continue
            schreiber.writerow(
                [csv_zelle(a.get("zeit") or ""), csv_zelle(a.get("benutzer") or ""),
                 csv_zelle(a.get("id") or ""), i]
                + [csv_zelle(z.get(s["id"], "")) for s in spalten])

    name = (f or {}).get("titel") or "feedback"
    # Dateiname entschaerfen: er geht in einen HTTP-Kopf.
    sicher = "".join(c if (c.isalnum() or c in " _-") else "_" for c in name).strip()
    sicher = (sicher or "feedback")[:60]
    stempel = datetime.now().strftime("%Y%m%d-%H%M")
    # ⚠ ALS ESCAPE-SEQUENZ, NICHT als Zeichen: ein echtes U+FEFF im Quelltext
    # ist unsichtbar – niemand findet es, und kein Waechter kann es treffen.
    return ("%s_%s.csv" % (sicher, stempel), "\ufeff" + puffer.getvalue())
