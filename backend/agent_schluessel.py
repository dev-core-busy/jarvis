"""Programmschluessel (Agent-API-Keys): Bereiche und Ablaufdatum (2026-11-20).

WARUM: bis hierher oeffnete JEDER gueltige Schluessel ALLE Wege, die einen
Schluessel annehmen – Agentenlaeufe, den Chat-WebSocket, Wissens- und
Chat-Dateien, Issues, Jira-Nachschlagen, Avatar/Sprache, Support, Feedback –
und das unbefristet. Ein Schluessel fuer eine Kamera, die nur "Person erkannt"
meldet, konnte damit Wissensdateien lesen. Am selben Tag gemessen: ein
Schluessel am Chat-WebSocket bekam sogar den Root-Weg der Shell (behoben in
main.py/agent.py).

REGELN:
- Der BEREICH einer Anfrage ergibt sich aus ihrem PFAD (``bereich_fuer_pfad``),
  an EINER Stelle – nicht an jeder der rund 30 Aufrufstellen. Ein Pfad ohne
  Zuordnung ist fuer JEDEN Schluessel gesperrt (fail-closed): ein neuer
  Endpunkt mit Schluessel-Zugang muss hier eingetragen werden, sonst nimmt er
  keinen Schluessel an (ein Waechter prueft die Zuordnung aller Endpunkte).
- BESTAND: ein Eintrag OHNE Feld ``bereiche`` (vor dieser Aenderung angelegt)
  behaelt die Bereiche, die es HEUTE gibt (``BESTAND``) – laufende Geraete
  fallen nicht aus. Ein kuenftiger Bereich gilt fuer ihn NICHT von selbst.
- NEU angelegte Schluessel bekommen nur ``VORGABE`` (Agent-Auftraege); alles
  weitere hakt der Administrator an. Eine Vorgabe, die im Zweifel mehr
  erlaubt, ist die falsche (Regel seit 2026-07-29).
- ABLAUF: ``"JJJJ-MM-TT"``, gueltig bis Ende dieses Tages (Serverzeit). Ein
  abgelaufener Schluessel faellt aus ``kandidaten`` heraus – damit gilt er an
  JEDEM Weg nicht mehr, auch nicht ueber einen aus ihm abgeleiteten
  Abruf-Schluessel (``_agent_kennung_gueltig`` prueft gegen dieselbe Liste).
- Der Legacy-Schluessel ``AGENT_API_KEY`` (.env) hat alle Bestands-Bereiche und
  kein Ablaufdatum – er ist nicht ueber die Oberflaeche verwaltbar.
"""

from __future__ import annotations

import datetime as _dt
import re
import time

# Reihenfolge = Reihenfolge in der Oberflaeche.
BEREICHE = ("agent", "chat", "dateien", "issues", "jira", "sprache", "support",
            "feedback")
# Bereiche eines Eintrags ohne Feld "bereiche" (Bestand vom 2026-11-20).
# BEWUSST eine eigene Konstante und NICHT ``BEREICHE``: ein spaeter
# hinzugefuegter Bereich soll fuer alte Schluessel nicht von selbst gelten.
BESTAND = ("agent", "chat", "dateien", "issues", "jira", "sprache", "support",
           "feedback")
VORGABE = ("agent",)

# Pfad -> Bereich. Erster passender Eintrag gewinnt; ein Eintrag mit "/" am
# Ende ist ein Praefix, sonst gilt der Pfad selbst ODER alles darunter ("/x"
# trifft "/x" und "/x/…", aber nicht "/xy").
PFADE = (
    ("/api/agent/task", "agent"),
    ("/ws", "chat"),
    ("/api/download-key", "dateien"),
    ("/api/generated/", "dateien"),
    ("/api/documents/", "dateien"),
    ("/api/chat/attachment/", "dateien"),
    ("/api/knowledge/file_read", "dateien"),
    ("/api/knowledge/file_raw", "dateien"),
    ("/api/knowledge/netzquelle", "dateien"),
    ("/api/wissen/file", "dateien"),
    ("/api/info_files/", "dateien"),
    ("/api/issues", "issues"),
    ("/api/jira/phonenumber", "jira"),
    ("/api/jira/crm-number", "jira"),
    ("/api/jira/passende-tickets", "jira"),
    ("/api/avatar/", "sprache"),
    ("/api/tts", "sprache"),
    ("/api/support/", "support"),
    ("/api/feedback", "feedback"),
)

_DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bereich_fuer_pfad(pfad: str) -> str:
    """Bereich eines Anfragepfads – "" ohne Zuordnung (dann fuer Schluessel gesperrt)."""
    p = "/" + str(pfad or "").split("?", 1)[0].lstrip("/")
    for muster, bereich in PFADE:
        if muster.endswith("/"):
            if p.startswith(muster):
                return bereich
        elif p == muster or p.startswith(muster + "/"):
            return bereich
    return ""


def bereiche_von(eintrag: dict) -> tuple:
    """Wirksame Bereiche eines Eintrags (Bestand ohne Feld → ``BESTAND``)."""
    if not isinstance(eintrag, dict) or "bereiche" not in eintrag:
        return BESTAND
    roh = eintrag.get("bereiche")
    if not isinstance(roh, (list, tuple)):
        return ()                   # kaputtes Feld: nichts (fail-closed)
    return tuple(b for b in BEREICHE if b in roh)


def _ende_des_tages(datum: str) -> float | None:
    if not _DATUM.match(str(datum or "")):
        return None
    try:
        tag = _dt.datetime.strptime(datum, "%Y-%m-%d")
    except ValueError:
        return None
    return (tag + _dt.timedelta(days=1)).timestamp()


def abgelaufen(eintrag: dict, jetzt: float | None = None) -> bool:
    """Ist das Ablaufdatum ueberschritten? Kein/leeres Datum = unbefristet.

    Ein UNLESBARES Datum gilt als abgelaufen (fail-closed) – gespeichert wird
    nur, was ``ablauf_pruefen`` durchgelassen hat; was trotzdem darin steht,
    hat jemand von Hand verbogen.
    """
    roh = (eintrag or {}).get("ablauf") if isinstance(eintrag, dict) else None
    if roh in (None, ""):
        return False
    ende = _ende_des_tages(str(roh))
    if ende is None:
        return True
    return (time.time() if jetzt is None else jetzt) >= ende


def kandidaten(eintraege: list, legacy: str = "", bereich: str | None = None,
               jetzt: float | None = None) -> list[str]:
    """Heute gueltige Schluesselwerte – optional nur die mit ``bereich``.

    ``bereich=None``: alle gueltigen (Kurzkennung, Widerrufspruefung).
    ``bereich=""``  : KEINER (Pfad ohne Zuordnung, fail-closed) – das folgt aus
    den beiden Filtern unten ("" ist kein Bereich); bewusst KEINE eigene
    Abfrage dafuer, zwei Schranken fuer dieselbe Frage machen jede Gegenprobe
    stumm (Register).
    """
    raus = []
    if legacy and (bereich is None or bereich in BESTAND):
        raus.append(legacy)
    for e in eintraege or []:
        if not isinstance(e, dict) or not e.get("key"):
            continue
        if abgelaufen(e, jetzt):
            continue
        if bereich is not None and bereich not in bereiche_von(e):
            continue
        raus.append(str(e["key"]))
    return raus


def bereiche_pruefen(roh) -> tuple[list, str]:
    """Eingabe aus der Oberflaeche pruefen: (Liste, Fehler)."""
    if not isinstance(roh, (list, tuple)):
        return [], "bereiche muss eine Liste sein."
    unbekannt = [b for b in roh if b not in BEREICHE]
    if unbekannt:
        return [], "Unbekannte Bereiche: %s" % ", ".join(map(str, unbekannt))
    return [b for b in BEREICHE if b in roh], ""


def ablauf_pruefen(roh) -> tuple[str, str]:
    """Eingabe ``""`` (unbefristet) oder ``"JJJJ-MM-TT"``: (Wert, Fehler)."""
    if roh in (None, ""):
        return "", ""
    s = str(roh).strip()
    if _ende_des_tages(s) is None:
        return "", "Das Ablaufdatum muss die Form JJJJ-MM-TT haben."
    return s, ""


def anzeige(eintrag: dict, jetzt: float | None = None) -> dict:
    """Felder fuer die Liste der Oberflaeche (ohne den Schluessel selbst)."""
    return {"bereiche": list(bereiche_von(eintrag)),
            "ablauf": str((eintrag or {}).get("ablauf") or ""),
            "abgelaufen": abgelaufen(eintrag, jetzt),
            "bestand": isinstance(eintrag, dict) and "bereiche" not in eintrag}
