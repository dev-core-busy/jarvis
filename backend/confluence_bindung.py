"""Dynamische Confluence-Einbindung: welche Confluence-Bereiche das Wissen speisen.

WAS ES IST: ein Wissens-Editor waehlt unter ``/wissen`` einen Confluence-Bereich
aus einem Pulldown; dieser Bereich erscheint danach als **konfigurierter
Bereich** im Container. Ein weiterer Bereich erscheint als zweiter Eintrag – die
Liste waechst also durch wiederholte Einzelauswahl.

⚠ ES WIRD HIER NOCH NICHTS IMPORTIERT UND NICHTS ABGEGLICHEN (Vorgabe des
Betreibers 2026-09-21: „Baue das ganze nur bis zu diesem Punkt"). Dieses Modul
haelt die EINBINDUNG fest, mehr nicht. Der Abgleich – geplant als Teil des
5-Minuten-Auftrags *Wissensabgleich* – kommt in einem spaeteren Schritt. Die
Oberflaeche sagt das ausdruecklich: ein Container, der eine Einbindung annimmt
und stillschweigend nichts tut, ist von einem kaputten nicht zu unterscheiden.

``inkl_unter`` IST DIE REICHWEITE, und zwar wie vom Betreiber festgelegt: der
gewaehlte Eintrag ist die **Basis** des Imports; mit Haken wird zusaetzlich
alles beruecksichtigt, was diesem Eintrag **untergeordnet** ist (Unterseiten,
untergeordnete Bereiche – was immer Confluence unter dem Eintrag fuehrt), ohne
Haken nur die Basis selbst. **Vorgabe ist AN.** Das Feld wird hier nur
gespeichert; ausgewertet wird es erst vom spaeteren Abgleich.

⚠ JEDE EINBINDUNG TRAEGT MINDESTENS EINE WISSENSGRUPPE (Vorgabe des
Betreibers 2026-09-22). Ohne sie waere beim spaeteren Abgleich nicht
entscheidbar, WOHIN das geholte Wissen gehoert – und die Zuordnung liesse sich
danach nur noch raten. ``gruppen`` haelt die Kennungen; ob der Anlegende sie
ueberhaupt beschreiben darf, prueft der Endpunkt (``_wissen_check_groups``) –
dieses Modul kennt die Wissensgruppen nicht und soll sie nicht kennen.

Die leere Liste wird hier trotzdem ABGEWIESEN, und das ist keine Doppelung des
Endpunkts, sondern die Schranke an der ABLAGE: ein kuenftiger zweiter Aufrufer
(Abgleich, Migrationsskript, Werkzeug) kann damit keinen Eintrag anlegen, der
fachlich unbrauchbar ist. Gemessen wird sie am direkten Modulaufruf.

⚠ ALTBESTAND HAT KEIN ``gruppen`` – und bekommt hier auch keines. Ein geratener
Wert waere eine Zuordnung, die niemand getroffen hat; die Oberflaeche BENENNT
solche Eintraege stattdessen („keiner Wissensgruppe zugeordnet"). Wer sie
zuordnen will, loest die Einbindung und bindet neu ein.

⚠ DIE LISTE IST GLOBAL, NICHT JE BENUTZER. Sie speist die gemeinsame
Wissensdatenbank – zwei Benutzer koennen nicht verschiedene Einbindungen fuer
denselben Bestand haben. ``von`` haelt nur fest, WER eingebunden hat (fuer die
Nachvollziehbarkeit), es ist kein Eigentuemer-Filter.

⚠ DER ANZEIGENAME KOMMT NICHT AUS DEM REQUEST. ``hinzufuegen`` bekommt ihn vom
Aufrufer, und der Endpunkt holt ihn aus der Liste der SICHTBAREN Bereiche.
Koennte ein Client ihn mitschicken, stuende in der Liste ein Name, der zu
keinem Bereich gehoert – und niemand koennte das erkennen, weil daneben ein
gueltiger Schluessel steht.

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
# mit hundert eingebundenen Bereichen liest niemand mehr – und jeder Eintrag
# kostet den spaeteren Abgleich einen Durchlauf gegen ein fremdes System.
MAX_BEREICHE = 50
KEY_MAX = 100
NAME_MAX = 200
# Deckel fuer die Wissensgruppen einer Einbindung. Die harte Schranke ist
# `_wissen_check_groups` im Endpunkt (nur Gruppen aus dem eigenen Bereich, und
# die gibt es wirklich); das hier faengt Muell und Ueberlaenge ab, BEVOR etwas
# in die Ablage geschrieben wird.
MAX_GRUPPEN = 50
GRUPPE_MAX = 80

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


def _laden() -> dict:
    """Bestand lesen. **Streng**: eine beschaedigte Datei wird NICHT
    ueberschrieben – ein Parse-Fehler gibt einen leeren Bestand zurueck, damit
    der Container nicht sperrt, aber ``_speichern`` schreibt nur, was der
    Aufrufer wirklich geaendert hat."""
    p = _pfad()
    if not p.is_file():
        return _leer()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        # ⚠ FAIL-OPEN, ABER NICHT STILL. "Leer" ist hier eine Aussage ("nichts
        # eingebunden"), und wenn sie aus einem FEHLER stammt, ist sie falsch:
        # die Oberflaeche meldet dann "Noch kein Bereich eingebunden", waehrend
        # welche in der Datei stehen. Beim Bau genau so passiert – eine als
        # root geschriebene Datei (0640 root:root) ist fuer den Dienst nicht
        # lesbar, und ohne diese Zeile gibt es dafuer keine einzige Spur.
        print(f"[CF-Bindung] {p} nicht lesbar ({type(e).__name__}: {e}) – "
              f"die Liste erscheint LEER. Pruefe Eigentuemer/Rechte "
              f"(erwartet: jarvis:jarvis 0640) bzw. den JSON-Inhalt.")
        return _leer()
    if not isinstance(d, dict):
        return _leer()
    d.setdefault("bereiche", [])
    if not isinstance(d["bereiche"], list):
        d["bereiche"] = []
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


def liste() -> list[dict]:
    """Alle eingebundenen Bereiche, in der Reihenfolge des Einbindens."""
    with _SPERRE:
        return [dict(b) for b in _laden().get("bereiche", []) if isinstance(b, dict)]


def ist_eingebunden(key: str) -> bool:
    k = str(key or "").strip()
    return bool(k) and any((b.get("key") or "") == k for b in liste())


def hinzufuegen(key: str, name: str, inkl_unter: bool, von: str = "",
                gruppen=None) -> dict:
    """Einen Bereich einbinden. Wirft ``BindungFehler`` mit Klartext.

    ``name`` ist der ANZEIGENAME und gehoert vom Aufrufer aus der Liste der
    sichtbaren Bereiche geholt (siehe Modulkopf). Fehlt er, steht der Schluessel
    da – das ist haesslich, aber keine Falschaussage.

    ``gruppen`` sind die Kennungen der Wissensgruppen, denen der Bereich
    zugeordnet wird – **mindestens eine**. Der Vorgabewert ``None`` ist kein
    Entgegenkommen: er laeuft in dieselbe Abweisung wie eine leere Liste, damit
    ein Aufrufer, der sie schlicht vergisst, LAUT scheitert statt still einen
    unbrauchbaren Eintrag anzulegen.
    """
    # ⚠ DER SCHLUESSEL WIRD NIE GEKUERZT, SONDERN ABGEWIESEN. Eine gekuerzte
    # Kennung ist eine ANDERE Kennung: sie sieht in der Liste plausibel aus,
    # zeigt aber auf einen Bereich, den es nicht gibt – der spaetere Abgleich
    # liefe dauerhaft ins Leere, und niemand koennte das der Eingabe ansehen.
    # (Der ANZEIGENAME darf gekuerzt werden, er ist reine Darstellung.)
    k = str(key or "").strip()
    if not k:
        raise BindungFehler("Es wurde kein Bereich gewaehlt.")
    if len(k) > KEY_MAX or not _KEY_RE.match(k):
        raise BindungFehler("Der Bereichs-Schluessel hat eine unerwartete Form.")
    # VOR der Sperre: die Pruefung ist rein rechnerisch und soll den Bestand
    # nicht blockieren, waehrend sie eine Fehleingabe zurueckweist.
    gr = _gruppen_pruefen(gruppen)
    with _SPERRE:
        d = _laden()
        bereiche = d["bereiche"]
        for b in bereiche:
            if isinstance(b, dict) and (b.get("key") or "") == k:
                raise BindungFehler("Dieser Bereich ist bereits eingebunden.")
        if len(bereiche) >= MAX_BEREICHE:
            raise BindungFehler(
                "Es sind bereits %d Bereiche eingebunden – mehr sind nicht vorgesehen."
                % MAX_BEREICHE)
        eintrag = {
            "id": secrets.token_hex(8),
            # ``typ`` steht heute immer auf "space". Es steht trotzdem in der
            # Ablage, weil der Betreiber die Reichweite ausdruecklich offen
            # formuliert hat („Unterseiten oder Bereiche oder was auch immer"):
            # kommt spaeter eine Seite als Einhaengepunkt dazu, ist der
            # Bestand ohne Migration lesbar.
            "typ": "space",
            "key": k,
            "name": _kuerzen(name, NAME_MAX) or k,
            # ``is True`` und nicht ``bool()``: ein "ja" oder eine 1 aus einer
            # von Hand geschriebenen Datei ist keine bewusste Entscheidung.
            "inkl_unter": inkl_unter is True,
            # Die Zuordnung, ohne die der spaetere Abgleich kein Ziel haette.
            "gruppen": gr,
            "angelegt": datetime.now().isoformat(timespec="seconds"),
            "von": _kuerzen(von, 120),
        }
        bereiche.append(eintrag)
        _speichern(d)
        return dict(eintrag)


def entfernen(bid: str) -> bool:
    """Eine Einbindung loesen. True, wenn wirklich etwas entfernt wurde.

    Es gibt diesen Weg, WEIL eine Einbindung ohne ihn eine Einbahnstrasse
    waere: ein versehentlich gewaehlter Bereich bliebe fuer immer stehen. Er
    ist zugleich der Weg, die Reichweite zu aendern (entfernen, mit anderem
    Haken neu einbinden) – solange es keinen eigenen Umschalter gibt.
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
