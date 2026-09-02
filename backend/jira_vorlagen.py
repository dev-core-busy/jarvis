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

DER STANDARD IST PERSOENLICH (2026-08-28)
-----------------------------------------
Jeder markiert genau EINE Vorlage als seinen Standard – eigene oder gemeinsame;
sie ist danach im Pulldown vorausgewaehlt. Gespeichert unter ``standard`` als
Zuordnung Benutzer → Kennung, NICHT als Feld an der Vorlage: eine gemeinsame
Vorlage gehoert dem Administrator, ihr Standard-Merkmal aber jedem Benutzer
einzeln. Stuende es an der Vorlage, waere die Wahl des Ersten die Wahl aller.

Der Anlass: das Fenster wird bei jedem Klick neu aufgebaut, die Auswahl stand
also bei JEDEM Oeffnen wieder auf "ohne Vorlage". Wer immer dieselbe Form
braucht, musste sie jedes Mal neu heraussuchen.

DIE VORLAGE BESTIMMT DIE FORM – UND SEIT 2026-09-01 DEN WERKZEUG-ZUSCHNITT
--------------------------------------------------------------------------
Der TEXT geht als zusaetzlicher Abschnitt in den System-Prompt, HINTER die
Grundaufgabe – dieselbe Reihenfolge und dieselbe Begruendung wie bei den
Antwort-Stilen (Vorfall 2026-08-17: eine Stilvorgabe hob eine
Absender-Bedingung auf). Er kann nichts freischalten.

Das Feld ``bereiche`` dagegen SCHALTET etwas frei: es nennt die lesenden
Werkzeug-Bereiche (``jira_assist.BEREICHE``), mit denen der Lauf arbeiten darf.
Deshalb ist es das einzige Feld dieses Moduls mit einer Rechtepruefung:

* Gespeichert wird nur, was der Administrator freigeschaltet hat – ein
  gesperrter Bereich wird **benannt und abgewiesen**, nicht stillschweigend
  entfernt (``_pruefe_bereiche``). Ohne diese Pruefung waere die Freigabe eine
  Empfehlung, die ein direkter POST umgeht.
* Und weil eine Freigabe auch ZURUECKGENOMMEN wird, prueft
  ``jira_assist.wirksame_bereiche`` beim Lauf ein zweites Mal. Beide Tore sind
  noetig: das erste erklaert dem Benutzer den Fehler, das zweite haelt ihn.

⚠ WORAUF DIE BEREICHE WIRKEN: auf jede Auswertung der Erweiterung, also auch
auf "meinen Kommentar ueberarbeiten". Der TEXT dagegen wirkt dort NICHT – beim
Ueberarbeiten ist der Entwurf des Mitarbeiters die Vorgabe, eine Vorlage wuerde
ihn ueberschreiben statt ihn zu verbessern.

DIE ART: WAS EINE VORLAGE UEBERHAUPT TUT (2026-09-02)
-----------------------------------------------------
Bis dahin war eine Vorlage immer eine Zusammenfassung, und "Antwort
vorschlagen" war ein eigener Knopf daneben. Seit die Oberflaeche nur noch EIN
Startsymbol hat, das die gewaehlte Vorlage ausfuehrt, muss die Vorlage selbst
sagen, was herauskommen soll: ``art`` ist ``"zusammenfassung"`` (Vorgabe) oder
``"antwort"``.

**Fail-safe ist die Zusammenfassung, nicht die Antwort** (``art_von``): ein
unbekannter Wert, ein Altbestand ohne das Feld, eine beschaedigte Datei – alles
wird zur Zusammenfassung. Die Richtung ist Absicht. Eine Zusammenfassung liest
ein Mitarbeiter; ein Antworttext ist fuer einen KUNDEN gedacht und laeuft unter
eigenen Regeln (nichts zusagen, keine Termine, keine Platzhalter). Im Zweifel
in den strengeren Modus zu fallen ist harmlos, umgekehrt waere es das nicht.

Seit es die Art gibt, wirkt der TEXT in BEIDEN Modi – bei einer Antwort-Vorlage
als Vorgabe fuer Ton und Aufbau des Entwurfs. Vorher wurde er ausserhalb der
Zusammenfassung verworfen; eine Antwort-Vorlage waere damit eine Vorlage
gewesen, deren Anweisung nichts tut.
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

# Was eine Vorlage TUT. Die Reihenfolge ist die des Pulldowns; das ERSTE ist
# zugleich die fail-safe Vorgabe (siehe `art_von`).
ARTEN = ("zusammenfassung", "antwort")

_DATEI = Path(__file__).resolve().parent.parent / "data" / "jira_vorlagen.json"

# ── Mitgelieferte Vorschlaege ───────────────────────────────────────────────
# Sie entstehen beim ERSTEN Zugriff, wenn die Datei fehlt – nicht pro fehlender
# Vorlage. Sonst kaeme eine bewusst geloeschte Vorgabe bei jedem Start zurueck
# (dieselbe Regel wie bei den Rollen-Agenten und den E-Mail-Stilen).
VORSCHLAEGE = [
    {
        "name": "Überblick (Standard)",
        "art": "zusammenfassung",
        "text": ("Fasse den Vorgang für jemanden zusammen, der ihn zum ersten "
                 "Mal sieht: worum es geht, was bisher passiert ist, woran es "
                 "aktuell hängt und was offen bleibt."),
    },
    {
        "name": "Kurz für die Leitung",
        "art": "zusammenfassung",
        "text": ("Halte dich sehr kurz: höchstens fünf Sätze. Nenne die Lage, "
                 "die Auswirkung für den Kunden und den nächsten Schritt. "
                 "Keine technischen Einzelheiten, keine Namen von Bauteilen "
                 "oder Versionen."),
    },
    {
        "name": "Technisch mit Verlauf",
        "art": "zusammenfassung",
        "text": ("Gib den technischen Sachstand wieder: Symptom, betroffene "
                 "Komponenten, was bereits geprüft oder ausgeschlossen wurde, "
                 "und welche Spur als Nächstes verfolgt werden sollte. Nenne "
                 "die Stationen des Verlaufs mit Datum, soweit sie im Ticket "
                 "stehen."),
    },
    {
        "name": "Was fehlt uns noch?",
        "art": "zusammenfassung",
        "text": ("Konzentriere dich ausschließlich darauf, welche Angaben zur "
                 "Bearbeitung fehlen: Welche Fragen sind unbeantwortet, welche "
                 "Daten hat der Melder nicht geliefert, worauf warten wir? "
                 "Formuliere daraus eine kurze Liste konkreter Rückfragen."),
    },
    {
        "name": "Übergabe an Kollegen",
        "art": "zusammenfassung",
        "text": ("Schreibe eine Übergabe für einen Kollegen, der den Vorgang "
                 "übernimmt: Stand, was bereits zugesagt wurde, womit der "
                 "Kunde rechnet, und was als Nächstes zu tun ist. Weise "
                 "ausdrücklich auf Zusagen mit Termin hin."),
    },
]


# ── Die Vorlage, die den frueheren Knopf "Antwort vorschlagen" ersetzt ──────
# Sie ist der Grund, warum es `art` gibt: bis 2026-09-02 war der
# Antwortvorschlag ein eigener Knopf neben dem Zusammenfassen. Seit die
# Oberflaeche nur noch EIN Startsymbol hat, muss diese Aktion als Vorlage
# waehlbar sein – sonst waere sie ersatzlos weg.
#
# Ihr Text bestimmt nur FORM und AUFBAU. Die Schutzregeln fuer Texte, die an
# einen Kunden gehen (nichts zusagen, keine Termine, keine Preise, keine
# Platzhalter), stehen unveraendert im System-Prompt und lassen sich von hier
# aus nicht aufheben – siehe `jira_assist._system_prompt`.
ANTWORT_VORSCHLAG = {
    "name": "Antwort an den Melder",
    "art": "antwort",
    "text": ("Formuliere den Entwurf einer Antwort an den Melder: freundlich, "
             "sachlich und ohne Fachjargon. Nimm zuerst Bezug auf sein "
             "Anliegen, nenne dann den Stand und zum Schluss den nächsten "
             "Schritt."),
}

# WAS EIN FRISCHER SERVER BEKOMMT – eine Quelle, keine Rechnung.
# `saeen()` legt genau das an, und ein Test, der "alle mitgelieferten" zaehlen
# will, zaehlt hier: eine Aufzaehlung im Test waere beim naechsten Vorschlag
# eine Zeitbombe (Register).
SAAT = VORSCHLAEGE + [ANTWORT_VORSCHLAG]

# Marker in der Datei: die Vorlage oben wurde bereits EINMAL nachgetragen.
# Ohne ihn kaeme sie nach dem Loeschen bei jedem Zugriff zurueck – dieselbe
# Regel wie bei `saeen()`, nur fuer einen Nachtrag statt fuer die Erstsaat.
_MARKE_ANTWORT = "saat_antwort"


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
        # Speichern, der Administrator kann sie vorher ansehen.
        return _leer()
    if not isinstance(d, dict):
        return _leer()
    d.setdefault("global", [])
    d.setdefault("benutzer", {})
    # Altbestand kennt das Feld nicht – dann hat eben niemand einen Standard.
    if not isinstance(d.get("standard"), dict):
        d["standard"] = {}
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


def art_von(v) -> str:
    """Die Art einer Vorlage – IMMER ein gueltiger Wert.

    ⚠ DIE RICHTUNG IST DIE SICHERHEITSENTSCHEIDUNG: alles Unklare wird zur
    ``zusammenfassung``. Ein fehlendes Feld (jede Vorlage von vor dem
    2026-09-02), ein Tippfehler in der Datei, ein Wert aus einer kuenftigen
    Fassung – nichts davon darf als ``antwort`` durchgehen. Eine Zusammenfassung
    liest ein Mitarbeiter; ein Antworttext ist fuer einen KUNDEN gedacht und
    laeuft unter eigenen Regeln. In den strengeren Modus zu fallen ist harmlos,
    umgekehrt waere es das nicht.
    """
    if isinstance(v, dict):
        v = v.get("art")
    roh = str(v or "").strip().lower()
    return roh if roh in ARTEN else ARTEN[0]


def _ansicht(v: dict) -> dict:
    """Eine Vorlage, wie die Oberflaeche sie sehen soll.

    KOPIE mit garantiertem ``art``: die Oberflaeche muss die Art nicht selbst
    erraten, und ein Altbestand ohne das Feld wird dabei NICHT auf Platte
    geaendert (``art_von`` beantwortet die Frage beim Lesen). Eine Kopie, weil
    der Rueckgabewert das Haus verlaesst – ein Aufrufer, der daran etwas
    verstellt, darf nicht den geladenen Bestand treffen.
    """
    aus = dict(v or {})
    aus["art"] = art_von(aus)
    return aus


def _nachtrag_antwort() -> None:
    """Traegt ``ANTWORT_VORSCHLAG`` genau EINMAL in eine bestehende Datei nach.

    **Warum es das braucht:** ``saeen()`` legt die Vorschlaege nur an, wenn die
    Datei noch gar nicht existiert – bewusst, sonst kaeme eine geloeschte
    Vorgabe bei jedem Zugriff zurueck. Auf jedem laufenden Server existiert sie
    aber langst. Ohne diesen Nachtrag waere die Aktion "Antwort vorschlagen"
    dort nach dem Update ersatzlos weg: der Knopf ist entfernt, und die Vorlage,
    die ihn ersetzt, gaebe es nicht.

    Der Marker macht daraus einen EINMALIGEN Vorgang. Wer die Vorlage danach
    loescht oder umbenennt, behaelt seine Entscheidung.

    ⚠ EINE BESCHAEDIGTE DATEI WIRD NICHT ANGEFASST. ``_laden()`` gibt bei einem
    Parse-Fehler bewusst einen leeren Bestand zurueck, damit der Bereich nicht
    sperrt – wuerde hier darauf geschrieben, waere der Bestand des Kunden weg,
    obwohl der Administrator ihn noch ansehen wollte. Deshalb liest diese
    Funktion selbst und streng.
    """
    try:
        d = json.loads(_DATEI.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    if not isinstance(d, dict) or d.get(_MARKE_ANTWORT):
        return
    if not isinstance(d.get("global"), list):
        # Kein brauchbarer Bestand – dann ist auch kein Nachtrag moeglich.
        return
    d["global"].append({
        "id": uuid.uuid4().hex[:12],
        "name": ANTWORT_VORSCHLAG["name"],
        "art": ANTWORT_VORSCHLAG["art"],
        "text": ANTWORT_VORSCHLAG["text"],
        "bereiche": [],
        "erstellt": int(time.time()),
    })
    d[_MARKE_ANTWORT] = 1
    _speichern(d)


def saeen() -> None:
    """Legt die Vorschlaege an – NUR, wenn die Datei noch gar nicht existiert.

    Auf einer bestehenden Datei wird stattdessen einmalig die Antwort-Vorlage
    nachgetragen (``_nachtrag_antwort``).
    """
    if _DATEI.exists():
        _nachtrag_antwort()
        return
    d = _leer()
    for v in SAAT:
        d["global"].append({
            "id": uuid.uuid4().hex[:12],
            "name": v["name"],
            "art": art_von(v),
            "text": v["text"],
            "erstellt": int(time.time()),
        })
    # Frisch gesaet heisst: der Nachtrag ist erledigt. Ohne diese Zeile wuerde
    # `_nachtrag_antwort` die Vorlage beim naechsten Zugriff ein zweites Mal
    # anlegen.
    d[_MARKE_ANTWORT] = 1
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


def _pruefe_bereiche(roh):
    """Die Werkzeug-Bereiche einer Vorlage – nur bekannte UND freigeschaltete.

    Rueckgabe ``None`` heisst **Feld nicht gesendet, also unveraendert lassen**;
    eine leere Liste heisst ausdruecklich "keine Bereiche". Nie auf Falsyness
    pruefen – sonst koennte ein Benutzer seine Bereiche nicht mehr abwaehlen
    (dieselbe Falle wie bei ``temperature`` und ``retention_days``).

    Ein abgewiesener Bereich wird BENANNT: sonst speichert jemand "mit
    Wissensdatenbank" und wundert sich spaeter, warum der Lauf nichts
    nachschlaegt (die Lehre aus dem Konto-Endpunkt des E-Mail-Skills, der
    unbekannte Felder still verwarf).
    """
    if roh is None:
        return None
    if isinstance(roh, str):
        gewaehlt = [t.strip() for t in roh.split(",") if t.strip()]
    elif isinstance(roh, (list, tuple)):
        gewaehlt = [str(t).strip() for t in roh if str(t).strip()]
    else:
        # Kein Raten: was nicht als Liste oder Liste-als-Text kommt, ist keine
        # Auswahl.
        raise VorlagenFehler("Die Werkzeug-Bereiche müssen eine Liste sein.")

    from backend import jira_assist as ja  # noqa: PLC0415

    unbekannt = [b for b in gewaehlt if b not in ja.BEREICHE]
    if unbekannt:
        raise VorlagenFehler("Unbekannte Werkzeug-Bereiche: %s"
                             % ", ".join(sorted(set(unbekannt))))
    frei = set(ja.freigegebene_bereiche())
    gesperrt = [b for b in gewaehlt if b not in frei]
    if gesperrt:
        raise VorlagenFehler(
            "Diese Werkzeug-Bereiche sind nicht freigeschaltet: %s. Ein "
            "Administrator gibt sie unter Einstellungen → Jira frei."
            % ", ".join(sorted(set(gesperrt))))
    # Reihenfolge stabil nach BEREICHE, nicht nach Eingabereihenfolge.
    return [b for b in ja.BEREICHE if b in gewaehlt]


def liste(user: str, ist_admin: bool = False) -> dict:
    """Alle Vorlagen, die dieser Benutzer benutzen darf.

    ``global`` sind die des Administrators (nur lesbar, ausser fuer Admins),
    ``eigene`` gehoeren dem Benutzer. Getrennt, weil die Oberflaeche den
    Unterschied zeigen muss: was man aendern kann und was nicht.

    ``standard`` ist die Kennung der persoenlichen Standard-Vorlage – schon
    GEPRUEFT (siehe ``_standard_aus``): zeigt der gespeicherte Wert ins Leere,
    kommt ``""`` heraus. Die Oberflaeche waehlt danach vor und setzt den Stern.

    Jeder Eintrag traegt ``art`` – auch ein Altbestand, der das Feld nicht hat
    (``_ansicht``). Die Oberflaeche startet damit den richtigen Modus und muss
    ihn nicht erraten.
    """
    saeen()
    d = _laden()
    global_ = [_ansicht(v) for v in (d.get("global") or [])]
    eigene = [_ansicht(v) for v in ((d.get("benutzer") or {}).get(_key(user)) or [])]
    return {
        "global": global_,
        "eigene": eigene,
        "darf_global": bool(ist_admin),
        "standard": _standard_aus(d, user, eigene + global_),
    }


def _standard_aus(d: dict, user: str, sichtbar: list) -> str:
    """Die geprueffte Standard-Kennung dieses Benutzers – oder ``""``.

    ⚠ GEPRUEFT WIRD BEIM LESEN, GESCHRIEBEN WIRD DABEI NICHTS. Der Standard
    kann ins Leere zeigen, ohne dass jemand etwas falsch gemacht hat: ein
    Administrator loescht eine GEMEINSAME Vorlage, und sie war fuer zwanzig
    Leute der Standard. Ihre Eintraege einzeln aufzuraeumen hiesse, beim
    Loeschen durch alle Benutzer zu laufen; die Datei bei jedem Lesen
    zurueckzuschreiben waere ein Schreibzugriff auf dem heissen Pfad. Ein
    verwaister Eintrag ist harmlos, solange er nach aussen ``""`` ist – und
    er verschwindet beim naechsten Setzen von selbst.
    """
    vid = str((d.get("standard") or {}).get(_key(user)) or "")
    if not vid:
        return ""
    return vid if any(v.get("id") == vid for v in sichtbar) else ""


def standard_setzen(user: str, vid: str, ist_admin: bool = False) -> str:
    """Markiert eine Vorlage als persoenlichen Standard. ``""`` hebt ihn auf.

    **Der Standard ist immer persoenlich** – auch dann, wenn er auf eine
    gemeinsame Vorlage zeigt. Ein Administrator, der hier seine Wahl trifft,
    setzt sie fuer sich, nicht fuer das Haus; wer eine Haus-Vorgabe will,
    braucht ein eigenes Feld an der Vorlage und keine Umdeutung dieses hier.

    Eine unbekannte Kennung wird ABGEWIESEN, nicht gespeichert: sonst waere
    die Anzeige beim naechsten Oeffnen wieder auf "ohne Vorlage" und niemand
    wuesste warum. Gesucht wird nur in dem, was dieser Benutzer benutzen darf –
    damit ist die Kennung im Request kein Weg an eine fremde Vorlage.
    """
    ziel = str(vid or "").strip()
    schluessel = _key(user)
    d = _laden()
    if ziel:
        sichtbar = (list((d.get("benutzer") or {}).get(schluessel) or [])
                    + list(d.get("global") or []))
        if not any(v.get("id") == ziel for v in sichtbar):
            raise VorlagenFehler("Die Vorlage wurde nicht gefunden.")
        d.setdefault("standard", {})[schluessel] = ziel
    else:
        d.setdefault("standard", {}).pop(schluessel, None)
    _speichern(d)
    return ziel


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
              global_: bool = False, ist_admin: bool = False,
              bereiche=None, art=None) -> dict:
    """Legt eine Vorlage an oder aendert sie.

    ``bereiche=None`` heisst "nicht gesendet" und laesst ein bestehendes Feld
    unangetastet – ein Aufrufer, der die Bereiche nicht kennt (aeltere
    Erweiterung), darf sie nicht loeschen. Dasselbe gilt fuer ``art=None``.

    Ein unbekannter Wert in ``art`` wird ABGEWIESEN, nicht stillschweigend zur
    Zusammenfassung gemacht: hier kommt er aus einem Pulldown, ein Fehlgriff
    ist also ein Fehler des Aufrufers – und eine Vorlage, die etwas anderes tut
    als bestellt, faellt niemandem auf. Beim LESEN ist die Abwaegung umgekehrt
    (``art_von``): dort ist der strengere Modus die richtige Antwort.
    """
    # ⚠ SAEEN AUCH HIER, nicht nur in `liste()`. Ist die Datei noch nicht da und
    # der ERSTE Zugriff ein Schreibvorgang, entsteht sie mit genau dieser einen
    # Vorlage – und `saeen()` legt die mitgelieferten Vorschlaege danach NIE mehr
    # an (es prueft nur, ob die Datei existiert). Auf DEV genau so passiert, mit
    # einer Probe, die direkt `speichern` rief: fuenf Vorschlaege dauerhaft weg,
    # ohne Fehlermeldung.
    saeen()
    n, t = _pruefe(name, text)
    ber = _pruefe_bereiche(bereiche)
    a = None
    if art is not None:
        a = str(art or "").strip().lower()
        if a not in ARTEN:
            raise VorlagenFehler("Unbekannte Art '%s'. Erlaubt sind: %s."
                                 % (art, ", ".join(ARTEN)))
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
                if ber is not None:
                    v["bereiche"] = ber
                if a is not None:
                    v["art"] = a
                _speichern(d)
                return _ansicht(v)
        raise VorlagenFehler("Die Vorlage wurde nicht gefunden.")

    if len(ziel) >= MAX_JE_BENUTZER:
        raise VorlagenFehler("Mehr als %d Vorlagen sind nicht vorgesehen."
                             % MAX_JE_BENUTZER)
    neu = {"id": uuid.uuid4().hex[:12], "name": n, "text": t,
           # Ohne Angabe die Zusammenfassung – dieselbe fail-safe Richtung wie
           # in `art_von`, und der Zustand jeder Vorlage von vor dem 2026-09-02.
           "art": a or ARTEN[0],
           # Neu angelegt OHNE Angabe = keine Bereiche. Fail-closed, und
           # zugleich der Zustand jeder Vorlage, die vor dem 2026-09-01
           # entstanden ist.
           "bereiche": ber or [],
           "erstellt": int(time.time())}
    ziel.append(neu)
    _speichern(d)
    return _ansicht(neu)


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
            _standard_vergessen(d, user, vid)
            _speichern(d)
            return True
    if ist_admin:
        g = d.setdefault("global", [])
        for i, v in enumerate(g):
            if v.get("id") == vid:
                g.pop(i)
                # Nur der EIGENE Eintrag wird geraeumt. Die anderen Benutzer
                # laufen ueber `_standard_aus` ins Leere und bekommen "ohne
                # Vorlage" – siehe die Begruendung dort.
                _standard_vergessen(d, user, vid)
                _speichern(d)
                return True
    # Fremd oder unbekannt – in beiden Faellen dieselbe Antwort. Ob eine
    # fremde Vorlage existiert, ist selbst eine Information.
    return False


def _standard_vergessen(d: dict, user: str, vid: str) -> None:
    """Raeumt den Standard-Eintrag EINES Benutzers, wenn er auf ``vid`` zeigt."""
    st = d.setdefault("standard", {})
    if st.get(_key(user)) == vid:
        st.pop(_key(user), None)


def eintrag_fuer(user: str, vid: str, ist_admin: bool = False) -> dict:
    """Die ganze Vorlage zu einer Kennung – oder ein leeres dict.

    Gesucht wird nur in dem, was dieser Benutzer benutzen DARF. Damit ist die
    Kennung im Request kein Weg an eine fremde Vorlage – und seit die Vorlage
    ein Feld ``bereiche`` traegt, ist das keine Formsache mehr: sie bestimmt den
    Werkzeug-Zuschnitt des Laufs.

    EINE Nachschlage-Funktion fuer Text UND Bereiche. Zwei getrennte waeren zwei
    Aufloesungen derselben Kennung, die beim naechsten Feld auseinanderlaufen.
    """
    if not vid:
        return {}
    d = liste(user, ist_admin)
    for v in (d["eigene"] + d["global"]):
        if v.get("id") == vid:
            return v
    return {}


def text_fuer(user: str, vid: str, ist_admin: bool = False) -> str:
    """Der Prompt-Text einer Vorlage – oder ``""``."""
    return str(eintrag_fuer(user, vid, ist_admin).get("text") or "")[:TEXT_MAX]


def markensicher(name: str) -> str:
    """Ein Name, der in einer Abschnittszeile stehen darf."""
    return " ".join(re.sub(r"[=\[\]\r\n]+", " ", str(name or "")).split())[:NAME_MAX]
