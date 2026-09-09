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


def _saeen(d: dict) -> bool:
    """Vorgabe-Fragen anlegen – **nur wenn es noch gar keine gibt**.

    Nicht pro fehlender Frage: eine bewusst gelöschte Vorgabe käme sonst bei
    jedem Zugriff zurück (dieselbe Regel wie bei ``agent_roles.saeen``).
    """
    if d.get("global_") or d.get("_gesaet"):
        return False
    d["global_"] = [
        _neu("Text herausziehen (OCR)",
             "Gib den gesamten sichtbaren Text aus diesem Ausschnitt exakt "
             "wieder – ohne Kommentar, ohne Zusammenfassung. Behalte "
             "Zeilenumbrüche und Reihenfolge bei."),
        _neu("Was ist das?",
             "Beschreibe knapp, was auf diesem Bildschirmausschnitt zu sehen "
             "ist und worum es geht."),
        _neu("Fehlermeldung erklären",
             "Auf dem Ausschnitt ist eine Fehlermeldung oder ein Programmfehler "
             "zu sehen. Erkläre in einfachen Worten, was sie bedeutet, und "
             "nenne den wahrscheinlichsten nächsten Schritt. Rate nicht – was "
             "du nicht erkennen kannst, sagst du."),
        _neu("Tabelle zusammenfassen",
             "Fasse die Zahlen oder die Tabelle auf diesem Ausschnitt zusammen: "
             "worum geht es, was fällt auf? Übernimm keine Zahl, die du nicht "
             "sicher lesen kannst."),
        _neu("Ins Deutsche übersetzen",
             "Übersetze den Text auf diesem Ausschnitt ins Deutsche. Gib nur "
             "die Übersetzung aus."),
    ]
    d["_gesaet"] = True
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
        if _saeen(d):
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
