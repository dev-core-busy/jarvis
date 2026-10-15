"""Dynamische Confluence-Einbindung: welche Confluence-Inhalte das Wissen speisen.

WAS ES IST (Vorgabe 2026-09-27): ein Wissens-Editor markiert unter ``/wissen``
in einem BAUM Confluence-Bereiche und deren Unterbereiche (den Seitenbaum des
Bereichs) und uebernimmt die Markierung mit EINEM Klick als **einen**
gespeicherten Eintrag – auch dann, wenn mehrere Bereiche markiert sind. Der
Eintrag ist danach editierbar (Bereiche/Unterbereiche hinzu oder weg).
Abgeglichen wird er vom 5-Minuten-Auftrag *Wissensabgleich*
(``backend/confluence_abgleich.py``) – dieses Modul HAELT nur die Auswahl.

DIE AUSWAHL JE BEREICH (``auswahl``: Liste, ein Element je Confluence-Bereich)::

    {"key": "CTDP", "name": "...",   # Anzeigename kommt vom SERVER
     "start": True,                  # der Bereich SELBST ist markiert
     "ganz": False,                  # Bereich samt ALLEN Unterbereichen
     "seiten": ["123", ...],         # einzeln markierte Seiten
     "zweige": ["123", ...]}         # Seiten, deren Zweig KOMPLETT markiert war

⚠ ``ganz`` UND ``zweige`` SIND DIE ANTWORT AUF „UND NEUE SEITEN?" (Entscheidung
des Betreibers 2026-09-27: „Ja, wenn Zweig komplett"). War ein Knoten samt
allem darunter markiert, gilt der Zweig als GANZES – eine spaeter in Confluence
angelegte Unterseite kommt beim Abgleich von selbst dazu. Bei einem teilweise
markierten Zweig zaehlen nur die gespeicherten Seiten. Ein Blatt ist kein
Zweig: wer eine einzelne Seite ohne Unterseiten markiert, hat sich fuer DIESE
Seite entschieden, nicht fuer alles, was irgendwann darunter entsteht.

``start`` ohne weitere Seiten heisst „nur der Bereich selbst" – das ist die
Startseite des Bereichs (die Uebersicht, die Confluence beim Klick auf den
Bereich zeigt). Aufgeloest wird sie erst im Abgleich.

⚠ JEDER EINTRAG TRAEGT MINDESTENS EINE WISSENSGRUPPE (Vorgabe des
Betreibers 2026-09-22). Ohne sie waere beim Abgleich nicht entscheidbar, WOHIN
das geholte Wissen gehoert. ``gruppen`` haelt die Kennungen; ob der Anlegende
sie beschreiben darf, prueft der Endpunkt (``_wissen_check_groups``) – dieses
Modul kennt die Wissensgruppen nicht und soll sie nicht kennen. Die leere Liste
wird hier trotzdem ABGEWIESEN: die Schranke sitzt an der ABLAGE, vor jedem
kuenftigen zweiten Aufrufer.

⚠ ALTBESTAND (``typ: "space"``, bis 2026-09-26): EIN Bereich plus Haken
``inkl_unter``. Er wird beim LESEN in die neue Form gebracht (``inkl_unter``
wird zu ``ganz``, sonst ``start``) und erst beim naechsten Bearbeiten in der
neuen Form geschrieben – eine stille Umschreibung der Ablage beim Lesen waere
eine Aenderung, die niemand ausgeloest hat. Ein Eintrag ohne ``gruppen`` bekommt
auch hier KEINE geratene Zuordnung; die Oberflaeche benennt ihn, und der
Abgleich laesst ihn mit Grund liegen.

⚠ DIE LISTE IST GLOBAL, NICHT JE BENUTZER. Sie speist die gemeinsame
Wissensdatenbank. ``von`` haelt nur fest, WER angelegt bzw. zuletzt geaendert
hat (Nachvollziehbarkeit), es ist kein Eigentuemer-Filter.

⚠ DIE ANZEIGENAMEN KOMMEN NICHT AUS DEM REQUEST. Der Endpunkt holt sie aus der
Liste der SICHTBAREN Bereiche und reicht sie herein; ein ``name`` in der
Auswahl wird hier ueberschrieben, wenn der Aufrufer ``namen`` mitgibt.

⚠ SEITEN-KENNUNGEN WERDEN HIER NUR IN IHRER FORM GEPRUEFT (Ziffern). Ob eine
Seite wirklich in ihrem Bereich liegt, entscheidet der Abgleich: er nimmt nur
Seiten, die in der Seitenliste DIESES Bereichs stehen. Eine untergeschobene
fremde Kennung laeuft dort ins Leere statt in die Wissensdatenbank.

TAGS (Vorgabe 2026-09-27): ``tags`` ist eine Liste von Confluence-Tags
(Labels). Traegt ein Eintrag Tags, uebernimmt der Abgleich von den markierten
Seiten NUR die, die mindestens einen davon tragen; ohne Tags alle markierten
Seiten (wie bisher). Die Tags gehoeren zum EINTRAG, nicht zum Benutzer: der
Abgleich laeuft im Hintergrund fuer alle, ein Filter je Benutzer haette dort
keinen Adressaten. Gespeichert wird klein geschrieben – Confluence selbst
speichert Labels klein, ein ``Handbuch`` fuende sonst nie etwas.

Bauart 1:1 wie ``ai_mouse_fragen``/``jira_vorlagen``: eine Datei, Kennungen aus
``secrets``, Deckel je Feld, atomar geschrieben, 0640.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from datetime import datetime
from pathlib import Path

_SPERRE = threading.Lock()

# Deckel. Kein technisches Limit, sondern eine Bedienbarkeitsgrenze: eine Liste
# mit hundert gespeicherten Eintraegen liest niemand mehr – und jeder Bereich
# darin kostet den Abgleich einen Durchlauf gegen ein fremdes System.
MAX_BEREICHE = 50            # gespeicherte Eintraege
MAX_SPACES_JE_EINTRAG = 50   # Confluence-Bereiche in EINEM Eintrag
# Seiten-Kennungen je Eintrag. Die Baumansicht holt je Bereich hoechstens 500
# Seiten (`wissen_confluence_pages`); 5000 laesst zehn volle Bereiche zu und
# haelt die Ablage trotzdem lesbar klein.
MAX_SEITEN_JE_EINTRAG = 5000
KEY_MAX = 100
NAME_MAX = 200
SEITE_MAX = 30
# Confluence-Seitenkennungen sind Ziffernfolgen (Server/DC wie Cloud). Die FORM
# wird geprueft, damit kein Pfad, kein CQL-Schnipsel und kein Leerraum in die
# Ablage kommt – ob die Seite in ihrem Bereich liegt, entscheidet der Abgleich.
_SEITE_RE = re.compile(r"^[0-9]+$")
# Deckel fuer die Wissensgruppen einer Einbindung. Die harte Schranke ist
# `_wissen_check_groups` im Endpunkt (nur Gruppen aus dem eigenen Bereich, und
# die gibt es wirklich); das hier faengt Muell und Ueberlaenge ab, BEVOR etwas
# in die Ablage geschrieben wird.
MAX_GRUPPEN = 50
GRUPPE_MAX = 80
# Tags je Eintrag. Confluence erlaubt 255 Zeichen je Label; 30 Tags sind schon
# eine Liste, die niemand mehr ueberblickt.
MAX_TAGS = 30
TAG_MAX = 255
# ⚠ NUR EINE FORM-PRUEFUNG, KEINE ERLAUBNISLISTE: welche Sonderzeichen
# Confluence in Labels zulaesst, unterscheidet sich zwischen Server und Cloud.
# Abgewiesen wird, was sicher kein Label ist – Leerraum (Confluence trennt
# Labels daran), Komma/Semikolon (Listentrenner) und Steuerzeichen.
_TAG_BOESE_RE = re.compile(r"[\s,;\x00-\x1f\x7f]")

# ⚠ DIE ZEICHENMENGE IST GEMESSEN, NICHT GERATEN. Eine erste Fassung liess
# `@` weg – am echten Bestand (489 Bereiche) fielen damit **185** durch, naemlich
# ALLE persoenlichen Bereiche (`~vorname.name@firma.de`). Gefunden hat das nur
# der Lauf gegen das echte Confluence; eine erfundene Testmenge haette es nie
# gezeigt. Gemessene Sonderzeichen dort: `~` `.` `-` `@` (laengster Key 39).
# `_` und `+` stehen mit, weil beide in Konten- und Mailnamen vorkommen.
#
# Es bleibt eine ERLAUBNISLISTE (fail-closed) und nur eine FORM-Pruefung gegen
# Tippfehler und Schmuggel (Schraegstriche, Anfuehrungszeichen, Leerzeichen,
# Zeilenumbrueche). Die harte Schranke ist eine andere: der Schluessel muss in
# den SICHTBAREN Bereichen stehen – das prueft der Endpunkt gegen Confluence.
_KEY_RE = re.compile(r"^[A-Za-z0-9._~@+-]+$")


def _pfad() -> Path:
    """Ablage. Bewusst eine **Funktion**, keine Modulkonstante – so kann ein
    Test sie umbiegen, ohne in den echten Bestand zu schreiben."""
    return Path(__file__).resolve().parent.parent / "data" / "confluence_bindung.json"


class BindungFehler(Exception):
    """Fachlicher Fehlschlag mit Text fuer die Oberflaeche."""


def _leer() -> dict:
    return {"version": 1, "bereiche": []}


class BestandUnlesbar(BindungFehler):
    """Die Ablage EXISTIERT, laesst sich aber nicht lesen oder deuten.

    ⚠ DAS IST KEIN LEERER BESTAND. Bis 2026-09-28 gab ``_laden`` hier ``_leer()``
    zurueck – und beide Folgen waren Datenverlust (Code-Review 2026-09-28):
    der Abgleich sah keine Eintraege mehr und raeumte JEDE importierte
    Confluence-Seite ab, und ``hinzufuegen``/``aendern`` schrieben den leeren
    Stand plus den neuen Eintrag UEBER die unlesbare Datei. Wer liest, bekommt
    deshalb diesen Fehler; wer schreibt, schreibt gar nicht."""


def _laden() -> dict:
    """Bestand lesen. **Streng**: nur eine FEHLENDE Datei ist ein leerer
    Bestand. Eine vorhandene, aber unlesbare oder formwidrige Datei wirft
    ``BestandUnlesbar`` – sie wird nie ueberschrieben und nie als „nichts
    eingebunden" gedeutet."""
    p = _pfad()
    if not p.is_file():
        return _leer()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        # Beim Bau genau so passiert – eine als root geschriebene Datei
        # (0640 root:root) ist fuer den Dienst nicht lesbar. Die Protokollzeile
        # bleibt: sie nennt, WAS zu pruefen ist.
        print(f"[CF-Bindung] {p} nicht lesbar ({type(e).__name__}: {e}) – "
              f"Abgleich und Bearbeiten ruhen. Pruefe Eigentuemer/Rechte "
              f"(erwartet: jarvis:jarvis 0640) bzw. den JSON-Inhalt.")
        raise BestandUnlesbar(
            "Die gespeicherten Einbindungen können gerade nicht gelesen werden – "
            "es wird nichts verändert. Bitte den Administrator informieren.") from e
    if not isinstance(d, dict) or not isinstance(d.setdefault("bereiche", []), list):
        print(f"[CF-Bindung] {p} hat eine unerwartete Form – Abgleich und Bearbeiten ruhen.")
        raise BestandUnlesbar(
            "Die gespeicherten Einbindungen haben eine unerwartete Form – "
            "es wird nichts verändert. Bitte den Administrator informieren.")
    return d


def _speichern(d: dict) -> None:
    """Atomar schreiben, Rechte 0640.

    0640, weil die Liste Betriebswissen traegt (welche Confluence-Bereiche
    dieses Haus in seine Wissensdatenbank zieht) – und weil ein BESCHREIBBARER
    Bestand die kuerzeste Art waere, dem spaeteren Abgleich einen fremden
    Bereich unterzuschieben."""
    p = _pfad()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o640)
    except Exception:  # noqa: BLE001
        pass
    os.replace(tmp, p)


def _kuerzen(s, maxlen: int) -> str:
    return (str(s or "").strip())[:maxlen]


def _gruppen_pruefen(gruppen) -> list[str]:
    """Kennungen der Wissensgruppen normieren und pruefen. Wirft ``BindungFehler``.

    ⚠ MINDESTENS EINE IST PFLICHT. Eine Einbindung ohne Ziel kann der spaetere
    Abgleich nicht ausfuehren – er wuesste nicht, welcher Wissensgruppe das
    geholte Wissen gehoert.

    Die FORM wird bewusst nur grob geprueft (Laenge, keine Steuerzeichen): eng
    an der heutigen Id-Vergabe (`knowledge_groups._slugify` liefert `[a-z0-9-]+`)
    wuerde diese Regel bei der naechsten Aenderung dort gueltige Einbindungen
    abweisen. Ob es die Gruppe WIRKLICH gibt und ob der Anlegende sie beschreiben
    darf, entscheidet ohnehin der Endpunkt.
    """
    if gruppen is None:
        gruppen = []
    if isinstance(gruppen, str) or not isinstance(gruppen, (list, tuple)):
        raise BindungFehler("Die Wissensgruppen wurden in unerwarteter Form uebergeben.")
    aus: list[str] = []
    for g in gruppen:
        k = str(g or "").strip()
        if not k:
            continue
        if len(k) > GRUPPE_MAX or any(ord(c) < 32 for c in k):
            raise BindungFehler("Eine Wissensgruppen-Kennung hat eine unerwartete Form.")
        if k not in aus:          # Dubletten still zusammenfassen, Reihenfolge behalten
            aus.append(k)
    if not aus:
        raise BindungFehler("Bitte mindestens eine Wissensgruppe zuordnen.")
    if len(aus) > MAX_GRUPPEN:
        raise BindungFehler(
            "Mehr als %d Wissensgruppen sind nicht vorgesehen." % MAX_GRUPPEN)
    return aus


def _seiten_pruefen(werte, was: str) -> list[str]:
    """Seitenkennungen normieren (Reihenfolge behalten, Dubletten still weg)."""
    if werte is None:
        return []
    if isinstance(werte, str) or not isinstance(werte, (list, tuple)):
        raise BindungFehler("Die %s wurden in unerwarteter Form uebergeben." % was)
    aus: list[str] = []
    for w in werte:
        k = str(w if w is not None else "").strip()
        if not k:
            continue
        # ⚠ ABGEWIESEN, NICHT GEKUERZT – eine gekuerzte Kennung ist eine
        # ANDERE Seite (dieselbe Regel wie beim Bereichs-Schluessel).
        if len(k) > SEITE_MAX or not _SEITE_RE.match(k):
            raise BindungFehler("Eine Seitenkennung hat eine unerwartete Form.")
        if k not in aus:
            aus.append(k)
    return aus


def _tags_pruefen(tags) -> list[str]:
    """Tags normieren und pruefen. Wirft ``BindungFehler``.

    ``None`` und die leere Liste heissen „kein Filter" – beides ist gueltig.
    Klein geschrieben, ein fuehrendes ``#`` faellt weg (so tippt man Tags),
    Dubletten still zusammengefasst, Reihenfolge behalten.
    """
    if tags is None:
        return []
    # ⚠ Ein String ist KEINE Liste – ueber ihn zu iterieren machte aus
    # "handbuch" acht Tags aus je einem Buchstaben.
    if isinstance(tags, (str, bytes)) or not isinstance(tags, (list, tuple)):
        raise BindungFehler("Die Tags wurden in unerwarteter Form uebergeben.")
    aus: list[str] = []
    for t in tags:
        if not isinstance(t, str):
            raise BindungFehler("Die Tags wurden in unerwarteter Form uebergeben.")
        k = t.strip().lstrip("#").strip().lower()
        if not k:
            continue
        # ⚠ ABGEWIESEN, NICHT GEKUERZT: ein gekuerzter Tag ist ein ANDERER Tag
        # und faende im Abgleich still nichts.
        if len(k) > TAG_MAX or _TAG_BOESE_RE.search(k):
            raise BindungFehler("Ein Tag hat eine unerwartete Form (keine Leerzeichen, "
                                "Kommas oder Semikolons innerhalb eines Tags).")
        if k not in aus:
            aus.append(k)
    if len(aus) > MAX_TAGS:
        raise BindungFehler("Mehr als %d Tags in einem Eintrag sind nicht vorgesehen." % MAX_TAGS)
    return aus


def _auswahl_pruefen(auswahl, namen=None) -> list[dict]:
    """Die markierten Bereiche normieren und pruefen. Wirft ``BindungFehler``.

    ``namen`` (optional, ``{key: anzeigename}``) kommt vom Endpunkt aus der
    Liste der SICHTBAREN Bereiche und gewinnt gegen jeden Namen im Rumpf.
    """
    if isinstance(auswahl, (str, bytes)) or not isinstance(auswahl, (list, tuple)):
        raise BindungFehler("Die Auswahl wurde in unerwarteter Form uebergeben.")
    aus: list[dict] = []
    gesehen: set[str] = set()
    seiten_gesamt = 0
    for el in auswahl:
        if not isinstance(el, dict):
            raise BindungFehler("Die Auswahl wurde in unerwarteter Form uebergeben.")
        k = str(el.get("key") or "").strip()
        if not k:
            raise BindungFehler("Es wurde kein Bereich gewaehlt.")
        # ⚠ DER SCHLUESSEL WIRD NIE GEKUERZT, SONDERN ABGEWIESEN. Eine gekuerzte
        # Kennung ist eine ANDERE Kennung: sie sieht in der Liste plausibel aus,
        # zeigt aber auf einen Bereich, den es nicht gibt – der Abgleich liefe
        # dauerhaft ins Leere, und niemand koennte das der Eingabe ansehen.
        if len(k) > KEY_MAX or not _KEY_RE.match(k):
            raise BindungFehler("Der Bereichs-Schluessel hat eine unerwartete Form.")
        if k in gesehen:
            # Zwei Elemente fuer denselben Bereich waeren zwei Aussagen ueber
            # dieselbe Reichweite – welche gilt, liesse sich nicht sagen.
            raise BindungFehler("Ein Bereich steht doppelt in der Auswahl.")
        gesehen.add(k)
        seiten = _seiten_pruefen(el.get("seiten"), "Seiten")
        zweige = _seiten_pruefen(el.get("zweige"), "Zweige")
        # Ein Zweig ist immer auch eine markierte Seite – sonst waere „der
        # Knoten samt allem darunter" markiert, der Knoten selbst aber nicht.
        for z in zweige:
            if z not in seiten:
                seiten.append(z)
        # ``is True``: ein "ja" oder eine 1 aus einer von Hand geschriebenen
        # Datei ist keine bewusste Entscheidung.
        ganz = el.get("ganz") is True
        start = el.get("start") is True or ganz
        if not (start or seiten):
            # Ein Bereich ohne jede Markierung ist keine Auswahl, sondern ein
            # Rest – der Abgleich haette dafuer nichts zu holen.
            continue
        seiten_gesamt += len(seiten)
        name = (namen or {}).get(k) if namen else None
        if name is None:
            name = el.get("name")
        aus.append({"key": k, "name": _kuerzen(name, NAME_MAX) or k,
                    "start": start, "ganz": ganz,
                    # Bei ``ganz`` ist die Seitenliste Beiwerk (alles zaehlt) –
                    # sie wird trotzdem gehalten, damit das Bearbeiten den
                    # Baum so zeigt, wie er uebernommen wurde.
                    "seiten": seiten, "zweige": zweige})
    if not aus:
        raise BindungFehler("Es wurde kein Bereich markiert.")
    if len(aus) > MAX_SPACES_JE_EINTRAG:
        raise BindungFehler("Mehr als %d Bereiche in einem Eintrag sind nicht vorgesehen."
                            % MAX_SPACES_JE_EINTRAG)
    if seiten_gesamt > MAX_SEITEN_JE_EINTRAG:
        raise BindungFehler("Mehr als %d markierte Seiten in einem Eintrag sind nicht "
                            "vorgesehen." % MAX_SEITEN_JE_EINTRAG)
    return aus


def _anzeigename(auswahl: list[dict]) -> str:
    """Name des Eintrags: die Bereichsnamen, in der Reihenfolge der Auswahl."""
    return _kuerzen(" · ".join((a.get("name") or a.get("key") or "") for a in auswahl),
                    NAME_MAX)


def _normiert(b: dict) -> dict:
    """Einen gespeicherten Eintrag in die aktuelle Form bringen (nur LESEN).

    Altbestand ``typ: "space"`` (EIN Bereich + ``inkl_unter``) wird zu einer
    Auswahl mit genau diesem Bereich: mit Haken der ganze Bereich (``ganz``),
    ohne nur der Bereich selbst (``start``). Geschrieben wird dabei NICHTS.
    """
    c = dict(b)
    if not isinstance(c.get("auswahl"), list):
        k = str(c.get("key") or "").strip()
        ganz = c.get("inkl_unter") is True
        c["auswahl"] = ([{"key": k, "name": c.get("name") or k, "start": True,
                          "ganz": ganz, "seiten": [], "zweige": []}] if k else [])
    else:
        c["auswahl"] = [dict(a) for a in c["auswahl"] if isinstance(a, dict)]
    c.setdefault("name", _anzeigename(c["auswahl"]))
    # Eintraege von vor den Tags: kein Filter. Eine kaputte Angabe wird NICHT
    # zu "kein Filter" – das wuerde den ganzen Bereich ins Wissen holen; der
    # Abgleich laesst den Eintrag dann mit Grund liegen (`tags_ungueltig`).
    try:
        c["tags"] = _tags_pruefen(c.get("tags"))
    except BindungFehler:
        c["tags"] = []
        c["tags_ungueltig"] = True
    return c


def liste() -> list[dict]:
    """Alle gespeicherten Eintraege (normiert), in der Reihenfolge des Anlegens."""
    with _SPERRE:
        return [_normiert(b) for b in _laden().get("bereiche", []) if isinstance(b, dict)]


def holen(bid: str) -> dict | None:
    i = str(bid or "").strip()
    return next((b for b in liste() if b.get("id") == i), None) if i else None


def hinzufuegen(auswahl, von: str = "", gruppen=None, namen=None, tags=None) -> dict:
    """Die markierten Bereiche als EINEN neuen Eintrag speichern.

    ``gruppen`` sind die Kennungen der Wissensgruppen – **mindestens eine**.
    Der Vorgabewert ``None`` ist kein Entgegenkommen: er laeuft in dieselbe
    Abweisung wie eine leere Liste, damit ein Aufrufer, der sie schlicht
    vergisst, LAUT scheitert statt still einen unbrauchbaren Eintrag anzulegen.
    """
    # VOR der Sperre: die Pruefungen sind rein rechnerisch und sollen den
    # Bestand nicht blockieren, waehrend sie eine Fehleingabe zurueckweisen.
    aw = _auswahl_pruefen(auswahl, namen)
    gr = _gruppen_pruefen(gruppen)
    tg = _tags_pruefen(tags)
    with _SPERRE:
        d = _laden()
        bereiche = d["bereiche"]
        if len(bereiche) >= MAX_BEREICHE:
            raise BindungFehler(
                "Es sind bereits %d Eintraege gespeichert – mehr sind nicht vorgesehen."
                % MAX_BEREICHE)
        jetzt = datetime.now().isoformat(timespec="seconds")
        eintrag = {
            "id": secrets.token_hex(8),
            "typ": "auswahl",
            "name": _anzeigename(aw),
            "auswahl": aw,
            # Die Zuordnung, ohne die der Abgleich kein Ziel haette.
            "gruppen": gr,
            # Leer = alle markierten Seiten, sonst nur die mit einem der Tags.
            "tags": tg,
            "angelegt": jetzt,
            "geaendert": jetzt,
            "von": _kuerzen(von, 120),
        }
        bereiche.append(eintrag)
        _speichern(d)
        return dict(eintrag)


def aendern(bid: str, auswahl, von: str = "", gruppen=None, namen=None,
           tags=None) -> dict:
    """Einen gespeicherten Eintrag bearbeiten (Bereiche/Unterbereiche hinzu
    oder weg, Wissensgruppen, Tags). Kennung und Anlagedatum bleiben; ``von``
    haelt fest, wer zuletzt geaendert hat. Wirft ``BindungFehler``; ein
    unbekannter Eintrag ist ``KeyError`` (der Endpunkt macht daraus 404).

    ``tags`` wird wie die Auswahl VOLLSTAENDIG ersetzt – ``None`` und ``[]``
    heissen beide „kein Filter". Ein Aufrufer, der die Tags nicht mitschickt,
    hebt den Filter damit auf; das ist Absicht, denn die Oberflaeche schickt
    beim Speichern immer den ganzen Eintrag."""
    aw = _auswahl_pruefen(auswahl, namen)
    gr = _gruppen_pruefen(gruppen)
    tg = _tags_pruefen(tags)
    i = str(bid or "").strip()
    with _SPERRE:
        d = _laden()
        for idx, b in enumerate(d["bereiche"]):
            if isinstance(b, dict) and b.get("id") == i and i:
                neu = {
                    "id": i,
                    "typ": "auswahl",
                    "name": _anzeigename(aw),
                    "auswahl": aw,
                    "gruppen": gr,
                    "tags": tg,
                    "angelegt": b.get("angelegt") or "",
                    "geaendert": datetime.now().isoformat(timespec="seconds"),
                    "von": _kuerzen(von, 120) or b.get("von") or "",
                }
                d["bereiche"][idx] = neu
                _speichern(d)
                return dict(neu)
    raise KeyError(i)


def entfernen(bid: str) -> bool:
    """Einen Eintrag loeschen. True, wenn wirklich etwas entfernt wurde.

    Das Wissen, das der Abgleich aus ihm geholt hat, verschwindet beim
    naechsten Abgleich wieder – es sei denn, ein anderer Eintrag deckt
    dieselben Seiten ab (``confluence_abgleich``).
    """
    i = str(bid or "").strip()
    if not i:
        return False
    with _SPERRE:
        d = _laden()
        vorher = len(d["bereiche"])
        d["bereiche"] = [b for b in d["bereiche"]
                         if not (isinstance(b, dict) and b.get("id") == i)]
        if len(d["bereiche"]) == vorher:
            return False
        _speichern(d)
        return True
