"""Die Fragen im Menü von AI Mouse – serverseitig, je Benutzer und gemeinsam.

⚠ SIE LAGEN BIS 2026-09-09 ALS ``prompts.json`` NEBEN DER EXE. Auf Vorgabe des
Betreibers werden sie jetzt hier gehalten und im Portal gepflegt (Kachel
„AI Mouse"). Der Unterschied ist nicht nur der Ort:

* **Sie folgen dem Benutzer, nicht dem Rechner.** Wer an zwei Arbeitsplätzen
  sitzt, hatte vorher zwei Fragenlisten – und nach einem Rechnertausch keine.
* **Gemeinsame Fragen kann ein Administrator für alle setzen.** In einer Datei
  neben der Exe ging das nur per Netzfreigabe und Kopieraktion.
* **Es gibt keine Datei mehr, die jemand von Hand kaputt machen kann.**

WAS DAS NICHT ÄNDERT – und das ist wichtig: die Frage bleibt die **eigene
Anweisung des Benutzers**, wie ein Chat-Text. Sie ist keine Schranke. Was
serverseitig liegen MUSS und aus keinem Request gesetzt werden kann, ist der
SYSTEM-Prompt und die Werkzeug-Whitelist (``backend/ai_mouse.py``). Diese
Liste ist Bedienkomfort – deshalb darf sie auch frei formuliert werden.

Bauart 1:1 wie ``jira_vorlagen``: eine Datei, zwei Töpfe (``global_`` und
``benutzer``), Kennungen aus ``secrets``, Deckel je Feld.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path

_SPERRE = threading.Lock()

# Deckel. Ein Titel ist eine Menüzeile, ein Prompt eine Anweisung an das Modell.
TITEL_MAX = 80
PROMPT_MAX = 2000
# Je Benutzer. Ein Aufklapp-Menü mit hundert Einträgen ist unbedienbar, und die
# Liste geht bei jedem Start über die Leitung.
MAX_JE_BENUTZER = 40
MAX_GEMEINSAM = 40


def _pfad() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "ai_mouse_fragen.json"


class FragenFehler(Exception):
    """Fachlicher Fehlschlag mit Text für die Oberfläche."""


def _laden() -> dict:
    """Bestand lesen. **Streng**: eine beschädigte Datei wird NICHT überschrieben.

    Ein Parse-Fehler gibt einen leeren Bestand zurück, damit der Bereich nicht
    sperrt – aber ``_speichern`` schreibt nur, was der Aufrufer wirklich
    geändert hat. Eine Automatik, die eine kaputte Datei stillschweigend durch
    eine leere ersetzt, vernichtet die Arbeit aller Benutzer.
    """
    p = _pfad()
    if not p.is_file():
        return {"version": 1, "global_": [], "benutzer": {}}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"version": 1, "global_": [], "benutzer": {}}
    if not isinstance(d, dict):
        return {"version": 1, "global_": [], "benutzer": {}}
    d.setdefault("global_", [])
    d.setdefault("benutzer", {})
    if not isinstance(d["global_"], list):
        d["global_"] = []
    if not isinstance(d["benutzer"], dict):
        d["benutzer"] = {}
    return d


def _speichern(d: dict) -> None:
    """Atomar schreiben, Rechte 0640.

    0640, weil die Fragen Betriebswissen enthalten können („prüfe, ob im
    Screenshot eine Kundennummer aus Projekt X steht"). Der Sandbox-Benutzer
    hat darauf nichts zu suchen.
    """
    p = _pfad()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o640)
    except Exception:  # noqa: BLE001
        pass
    os.replace(tmp, p)


def _norm(user: str) -> str:
    """Benutzerschlüssel. Ohne Normierung stünde derselbe Mensch je nach
    Tippform mehrfach im Bestand (Register: `_norm_login`)."""
    u = (user or "").strip().lower()
    if "\\" in u:
        u = u.split("\\", 1)[1]
    if "@" in u:
        u = u.split("@", 1)[0]
    return u


# ─── Vorgaben: was ein neuer Benutzer beim ERSTEN Mal bekommt ────────────────
#
# ⚠ DER UNTERSCHIED ZU „GEMEINSAM" IST DER KERN DIESES ABSCHNITTS, und er ist
# von aussen nicht zu erraten:
#
#   gemeinsam (``global_``)  gilt fuer alle, gehoert dem ADMINISTRATOR – ein
#                            Benutzer sieht sie und kann sie NICHT aendern.
#   Vorgabe   (``vorgaben``) ist eine VORLAGE. Beim ersten Kontakt wird sie in
#                            die eigene Liste des Benutzers KOPIERT – ab da
#                            gehoeren die Eintraege ihm, mit eigenen Kennungen,
#                            und er darf sie aendern und loeschen.
#
# Beides nebeneinander ist Absicht: „diese Frage gilt im Haus verbindlich" und
# „so faengt jeder an" sind verschiedene Aussagen.
_VORGABEN_SAAT = [
    ("Text erkennen (OCR)",
     "Agiere als OCR-System. Erkenne den Text"),
    ("extrahiere Adressdaten (OCR)",
     "Agiere als OCR-System. Extrahiere präzise den sichtbaren Text aus diesem "
     "Bild ohne zusätzliche Kommentare oder Bewertungen. Strukturieren Sie die "
     "erfassten Daten dabei explizit in folgende Adress- und Kontaktdaten: "
     "Nachname, Vorname, Straße und Hausnummer, Postleitzahl, Ort, "
     "E-Mail-Adresse, Mobilnummer, Ansprechpartner sowie ggf. weitere relevante "
     "Felder. Geben Sie ausschließlich die extrahierten und strukturierten "
     "Daten zurück."),
    ("was ist das ?",
     "Beschreibe knapp, was auf diesem Bildschirmausschnitt zu sehen ist und "
     "worum es geht."),
    ("Tabelle zusammenfassen",
     "Fasse die Zahlen oder die Tabelle auf diesem Ausschnitt zusammen: worum "
     "geht es, was fällt auf? Übernimm keine Zahl, die du nicht sicher lesen "
     "kannst."),
    ("suche homepage",
     "suche die homepage der Adresse und zeige sie als klickbaren hyperlink an"),
    ("übersetze nach Deutsch",
     "Agiere als OCR-System. Übersetze den Text nach Deutsch"),
]


def _saeen(d: dict) -> bool:
    """Vorgabe-Liste anlegen und den Altbestand einmalig raeumen.

    Zwei Schritte, beide **genau einmal** – jeder mit eigenem Marker:

    (1) ``vorgaben`` wird mit der eingebauten Saat gefuellt, wenn es sie noch
        gar nicht gibt. NICHT pro fehlendem Eintrag: eine bewusst geloeschte
        Vorgabe kaeme sonst bei jedem Zugriff zurueck (Regel aus
        ``agent_roles.saeen``).

    (2) ⚠ DIE ALTEN GEMEINSAMEN FRAGEN WERDEN GELEERT (Vorgabe des Betreibers
        2026-09-10). Bis dahin lagen die fuenf eingebauten Fragen in
        ``global_`` – dort kann ein Benutzer sie nicht anpassen, und zwei davon
        doppeln sich inhaltlich mit der neuen Vorgabe-Liste.

        **Der Marker ``_global_geraeumt`` ist dabei nicht Beiwerk, sondern die
        ganze Bedingung:** ohne ihn wuerde jede gemeinsame Frage, die ein
        Administrator DANACH anlegt, beim naechsten Laden wieder verschwinden –
        eine Funktion, die still nichts tut.
    """
    geaendert = False
    if "vorgaben" not in d or not isinstance(d.get("vorgaben"), list):
        d["vorgaben"] = []
        geaendert = True
    if not d["vorgaben"] and not d.get("_gesaet_vorgaben"):
        d["vorgaben"] = [_neu(t, p) for t, p in _VORGABEN_SAAT]
        d["_gesaet_vorgaben"] = True
        geaendert = True
    if not d.get("_global_geraeumt"):
        if d.get("global_"):
            d["global_"] = []
        d["_global_geraeumt"] = True
        geaendert = True
    return geaendert


def _uebernehmen(d: dict, user: str) -> bool:
    """Die Vorgaben EINMALIG in die eigene Liste des Benutzers kopieren.

    ⚠ MIT NEUEN KENNUNGEN: die Kopien gehoeren ab jetzt IHM – aendert der
    Administrator spaeter eine Vorgabe, bleibt seine Fassung, wie sie ist. Das
    ist der Sinn von „Vorgabe beim ersten Start" (und der Unterschied zu einer
    gemeinsamen Frage).

    ⚠ DER MARKER JE BENUTZER IST PFLICHT. Ohne ihn kaemen geloeschte Vorgaben
    beim naechsten Start zurueck – dieselbe Einbahnstrasse wie beim
    Willkommens-Chat, nur andersherum: dort durfte er nicht wiederkommen,
    hier darf er es genauso wenig. Die Bedingung ist deshalb der MARKER und
    NICHT „hat der Benutzer schon Fragen": wer seine letzte Frage loescht,
    bekaeme sonst die ganze Vorgabeliste zurueck.
    """
    k = _norm(user)
    if not k:
        return False
    gesaet = d.setdefault("gesaet_fuer", [])
    if not isinstance(gesaet, list):
        gesaet = d["gesaet_fuer"] = []
    if k in gesaet:
        return False
    eigen = d["benutzer"].setdefault(k, [])
    frei = max(0, MAX_JE_BENUTZER - len(eigen))
    for e in (d.get("vorgaben") or [])[:frei]:
        if isinstance(e, dict) and e.get("titel"):
            eigen.append(_neu(e.get("titel", ""), e.get("prompt", "")))
    gesaet.append(k)
    return True


def _neu(titel: str, prompt: str) -> dict:
    return {"id": secrets.token_hex(6), "titel": titel, "prompt": prompt}


def _pruefe(titel: str, prompt: str) -> tuple[str, str]:
    t = (titel or "").strip()[:TITEL_MAX]
    p = (prompt or "").strip()[:PROMPT_MAX]
    if not t:
        raise FragenFehler("Die Frage braucht einen Titel – er steht im Menü.")
    if not p:
        raise FragenFehler("Die Frage braucht einen Text – das ist die "
                           "Anweisung an das Modell.")
    return t, p


def liste(user: str, ist_admin: bool = False) -> list[dict]:
    """Die Fragen DIESES Benutzers: gemeinsame zuerst, eigene danach.

    ``darf_aendern`` sagt je Eintrag, ob der Aufrufer ihn bearbeiten darf –
    gemeinsame nur als Administrator. Ohne dieses Feld müsste die Oberfläche
    die Regel nachbauen, und zwei Fassungen liefen auseinander.
    """
    with _SPERRE:
        d = _laden()
        geaendert = _saeen(d)
        # Der erste Kontakt DIESES Benutzers: Vorgaben in seine Liste kopieren.
        geaendert = _uebernehmen(d, user) or geaendert
        if geaendert:
            _speichern(d)
        eigen = d["benutzer"].get(_norm(user)) or []
        raus = [dict(e, gemeinsam=True, darf_aendern=bool(ist_admin))
                for e in d["global_"] if isinstance(e, dict)]
        raus += [dict(e, gemeinsam=False, darf_aendern=True)
                 for e in eigen if isinstance(e, dict)]
    return raus


def speichern(user: str, fid: str, titel: str, prompt: str,
              gemeinsam: bool = False, ist_admin: bool = False) -> dict:
    """Anlegen (``fid`` leer) oder ändern. Gibt den gespeicherten Eintrag zurück.

    ⚠ GEMEINSAME FRAGEN NUR ALS ADMINISTRATOR – geprüft HIER und nicht nur in
    der Oberfläche: das Feld kommt aus dem Request.

    ⚠ EIN WECHSEL zwischen eigen und gemeinsam ist ein VERSCHIEBEN, und die
    Kennung bleibt dabei dieselbe. Eine neue Kennung wäre ein stiller Verlust
    für jeden, der die Frage als Vorgabe gewählt hat (dieselbe Lehre wie bei
    ``jira_vorlagen``, wo genau das den Wechsel unmöglich machte).
    """
    t, p = _pruefe(titel, prompt)
    if gemeinsam and not ist_admin:
        raise FragenFehler("Gemeinsame Fragen darf nur ein Administrator "
                           "anlegen oder ändern.")
    k = _norm(user)
    with _SPERRE:
        d = _laden()
        _saeen(d)
        eigen = d["benutzer"].setdefault(k, [])
        # In BEIDEN Töpfen suchen: nur so ist ein Verschieben möglich.
        alt_g = next((e for e in d["global_"] if e.get("id") == fid), None) if fid else None
        alt_e = next((e for e in eigen if e.get("id") == fid), None) if fid else None
        if fid and alt_g is None and alt_e is None:
            raise FragenFehler("Die Frage wurde nicht gefunden.")
        if alt_g is not None and not ist_admin:
            raise FragenFehler("Diese Frage gehört allen – nur ein "
                               "Administrator darf sie ändern.")
        eintrag = {"id": fid or secrets.token_hex(6), "titel": t, "prompt": p}
        # Aus beiden Töpfen entfernen, dann in den gewählten legen.
        d["global_"] = [e for e in d["global_"] if e.get("id") != eintrag["id"]]
        d["benutzer"][k] = [e for e in eigen if e.get("id") != eintrag["id"]]
        ziel = d["global_"] if gemeinsam else d["benutzer"][k]
        deckel = MAX_GEMEINSAM if gemeinsam else MAX_JE_BENUTZER
        if len(ziel) >= deckel:
            raise FragenFehler("Es sind höchstens %d Fragen möglich." % deckel)
        ziel.append(eintrag)
        _speichern(d)
    return dict(eintrag, gemeinsam=gemeinsam, darf_aendern=True)


# ─── Vorgaben pflegen (nur Administrator) ────────────────────────────────────
# Die Rechtefrage steht beim AUFRUFER (`require_local_auth` am Endpunkt) – hier
# liegt nur die Datenhaltung, wie im uebrigen Modul.

def vorgaben_liste() -> list[dict]:
    """Die Vorgabe-Fragen (Vorlage fuer neue Benutzer)."""
    with _SPERRE:
        d = _laden()
        if _saeen(d):
            _speichern(d)
        return [dict(e) for e in (d.get("vorgaben") or []) if isinstance(e, dict)]


def vorgabe_speichern(fid: str, titel: str, prompt: str) -> dict:
    """Vorgabe anlegen (``fid`` leer) oder aendern.

    ⚠ WIRKT NUR AUF BENUTZER, DIE ES NOCH NICHT GAB. Wer die Vorgaben schon
    bekommen hat, behaelt SEINE Fassung – das ist die Zusage von „Vorgabe beim
    ersten Start" und der Grund, warum die Kopien eigene Kennungen tragen. Die
    Oberflaeche sagt das ausdruecklich, sonst wartet ein Administrator auf eine
    Wirkung, die nicht kommt.
    """
    t, p = _pruefe(titel, prompt)
    with _SPERRE:
        d = _laden()
        _saeen(d)
        vor = d.setdefault("vorgaben", [])
        if fid:
            alt = next((e for e in vor if e.get("id") == fid), None)
            if alt is None:
                raise FragenFehler("Die Vorgabe wurde nicht gefunden.")
            alt["titel"], alt["prompt"] = t, p
            eintrag = alt
        else:
            if len(vor) >= MAX_GEMEINSAM:
                raise FragenFehler("Es sind höchstens %d Vorgaben möglich."
                                   % MAX_GEMEINSAM)
            eintrag = _neu(t, p)
            vor.append(eintrag)
        _speichern(d)
    return dict(eintrag)


def vorgabe_loeschen(fid: str) -> bool:
    """Eine Vorgabe entfernen. Unbekannt → ``False`` (Aufrufer: 404)."""
    with _SPERRE:
        d = _laden()
        _saeen(d)
        vor = d.get("vorgaben") or []
        if not any(e.get("id") == fid for e in vor):
            return False
        d["vorgaben"] = [e for e in vor if e.get("id") != fid]
        _speichern(d)
    return True


def sortieren(user: str, ids: list, ist_admin: bool = False) -> int:
    """Die Reihenfolge der Fragen setzen. Rückgabe: Anzahl umsortierter Einträge.

    ``ids`` ist die gewünschte Reihenfolge, wie die Oberfläche sie nach dem
    Ziehen sieht – sie darf eigene UND gemeinsame Kennungen in EINER Liste
    enthalten.

    ⚠ SORTIERT WIRD JE TOPF, NICHT ÜBER BEIDE. Die Ansicht ist „gemeinsame
    zuerst, eigene danach" (siehe ``liste``), und daran ändert das Ziehen
    nichts: eine gemeinsame Frage gehört dem Administrator und steht bei JEDEM
    Benutzer. Eine benutzereigene Reihenfolge ÜBER beide Töpfe bräuchte eine
    zusätzliche Zuordnung je Benutzer – die wäre ehrlich machbar (so wie der
    persönliche Standard bei den Jira-Vorlagen), löst aber ein Problem, das es
    praktisch nicht gibt: die sechs Vorgabe-Fragen werden beim ersten Kontakt
    als EIGENE kopiert (``_uebernehmen``), gemeinsame gibt es nur, wenn ein
    Administrator welche anlegt. Die Oberfläche lässt deshalb gar nicht über
    die Gruppengrenze ziehen – ein Ziehen, das nichts bewirkt, wäre schlimmer
    als eines, das nicht angeboten wird.

    ⚠ GEMEINSAME NUR ALS ADMINISTRATOR, geprüft HIER – die Kennungen kommen aus
    dem Request. Ohne diese Schranke könnte jeder Benutzer die Reihenfolge im
    Menü ALLER anderen umstellen.

    ⚠ TOLERANT IN BEIDE RICHTUNGEN, und das ist kein Komfort: zwischen dem
    Zeichnen der Liste und dem Ablegen kann eine Frage gelöscht oder eine neue
    angelegt worden sein (zweiter Browser-Tab, Administrator).
    * Unbekannte Kennungen werden **verworfen, nicht geraten**.
    * Nicht genannte Einträge behalten ihre bisherige relative Reihenfolge und
      landen **hinten** – so verschwindet keine Frage aus dem Menü, nur weil
      die Oberfläche sie nicht kannte.
    """
    k = _norm(user)
    gewuenscht = [str(x) for x in (ids or []) if isinstance(x, (str, int))]
    if not gewuenscht:
        return 0

    def _neu_ordnen(topf: list) -> tuple[list, bool]:
        """(neue Liste, hat sich etwas geändert) – Reihenfolge aus `gewuenscht`."""
        vorhanden = [e for e in topf if isinstance(e, dict)]
        nach_id = {}
        for e in vorhanden:
            eid = e.get("id")
            if eid is not None and eid not in nach_id:
                nach_id[eid] = e
        # Erst die genannten, in der gewuenschten Folge; jede nur EINMAL (eine
        # doppelte Kennung im Request darf den Eintrag nicht verdoppeln).
        raus, gesehen = [], set()
        for eid in gewuenscht:
            e = nach_id.get(eid)
            if e is not None and eid not in gesehen:
                raus.append(e)
                gesehen.add(eid)
        # Dann alles Uebrige, in bisheriger Folge.
        raus += [e for e in vorhanden if e.get("id") not in gesehen]
        return raus, [e.get("id") for e in raus] != [e.get("id") for e in vorhanden]

    with _SPERRE:
        d = _laden()
        bewegt = 0
        eigen_neu, eigen_anders = _neu_ordnen(d["benutzer"].get(k) or [])
        if eigen_anders:
            d["benutzer"][k] = eigen_neu
            bewegt += len(eigen_neu)
        if ist_admin:
            glob_neu, glob_anders = _neu_ordnen(d["global_"])
            if glob_anders:
                d["global_"] = glob_neu
                bewegt += len(glob_neu)
        if bewegt:
            _speichern(d)
    return bewegt


def loeschen(user: str, fid: str, ist_admin: bool = False) -> bool:
    """Eine Frage löschen. Fremd oder unbekannt → ``False`` (der Aufrufer
    antwortet mit 404, nicht 403: ob eine fremde Frage existiert, ist selbst
    eine Information)."""
    k = _norm(user)
    with _SPERRE:
        d = _laden()
        eigen = d["benutzer"].get(k) or []
        if any(e.get("id") == fid for e in eigen):
            d["benutzer"][k] = [e for e in eigen if e.get("id") != fid]
            _speichern(d)
            return True
        if ist_admin and any(e.get("id") == fid for e in d["global_"]):
            d["global_"] = [e for e in d["global_"] if e.get("id") != fid]
            _speichern(d)
            return True
    return False
