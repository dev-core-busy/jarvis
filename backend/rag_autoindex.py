"""Automatischer Wissens-Index: jede Aenderung kommt OHNE Zutun im RAG an.

⚠ WARUM ES DAS GIBT (Vorgabe 2026-09-21). Bis dahin war die einzige Automatik
ein Nebeneffekt der SUCHE: ``knowledge_search`` ruft ``_rebuild_vector_index``
(force=False). Das hatte drei Loecher, und jedes einzelne heisst "eine Aenderung
kommt NICHT an":

  1. **Ohne Suche passiert gar nichts.** Wer eine Datei auf der Freigabe aendert
     und niemand sucht, hat sie nie im Index.
  2. ``INLINE_LIMIT = 10`` - hoechstens zehn Dateien je Suche. Ein Schwung von
     fuenfzig braucht fuenf Suchen, und der Rest steht nur im Journal.
  3. **Loeschungen wirken gar nicht.** Verwaiste Eintraege raeumt ausschliesslich
     der ausdrueckliche Neuaufbau - eine geloeschte Datei liefert also weiter
     Treffer, unbegrenzt lange.

⚠ WARUM POLLING UND KEIN DATEI-WATCHER. Der naheliegende Weg (``watchdog``, wie
in ``backend/file_watcher.py``) traegt hier NICHT: inotify meldet ausschliesslich
Aenderungen, die der EIGENE Kernel ausfuehrt. Aendert jemand eine Datei auf dem
Windows-Server, sieht der CIFS-Mount davon kein Ereignis. Ein Watcher waere also
genau fuer den wichtigsten Fall - die SMB-Freigabe - blind und gaebe dabei das
Gefuehl, die Sache sei erledigt. Ein Takt deckt jeden Fall ab, auch Loeschungen.

⚠ WARUM NICHT EINFACH ``force_reindex`` IN EINEN TAKT. Weil der fuer den
AUSDRUECKLICHEN Neuaufbau gebaut ist und bei JEDEM Lauf Spuren zieht: er
schreibt ``status: running`` ins Lauf-Protokoll und setzt
``_set_progress(running=True)``. Alle fuenf Minuten hiesse das: die Anzeige
"Letzter Indexlauf" ist entwertet, die Fortschrittsanzeige flackert dauernd -
und ein Dienst-Neustart mitten im Takt sieht fuer ``resume_interrupted_reindex``
wie ein ABSTURZ aus und loest eine Wiederaufnahme aus.

Deshalb: erst eine **rein lesende Vorpruefung**, und nur wenn wirklich etwas
anliegt, laeuft der EINE vorhandene Weg (``force_reindex(incremental=True)``).
Im Regelfall - nichts geaendert - passiert damit gar nichts und niemand merkt
den Lauf. Einen zweiten Indizierweg gibt es ausdruecklich NICHT; die Erkennung
teilt sich mit dem Reindex dieselben Funktionen (``_geaenderte_dateien``,
``_verwaiste_dateien``), sonst driften Vorpruefung und Lauf auseinander.

⚠ AUSGELOEST WIRD ES VON EINEM CRON-AUFTRAG (Vorgabe 2026-09-21), sichtbar und
steuerbar unter *Einstellungen → Tasks → Cron-Aufgaben*. Der fruehere eigene
Takt im Startup-Hook ist damit ENTFALLEN - zwei Ausloeser fuer dieselbe Sache
waeren zwei Fassungen, und der Administrator koennte den einen abschalten,
waehrend der andere weiterlaeuft: "ich habe es doch deaktiviert, warum
indiziert es trotzdem?" ist genau der Zustand, den niemand erklaeren kann.

⚠ DER AUFTRAG LAEUFT OHNE AGENT. ``scheduler._execute`` hat dafuer einen
eigenen Zweig (``kind="wissensabgleich"``), wie bei den Erinnerungen. Wer ihn
durch einen Agentenlauf ersetzt, macht aus einer deterministischen
Wartungsaufgabe einen LLM-Aufruf, der raten darf, ob er etwas tut.
"""
from __future__ import annotations

import os
import threading
import time

def abgeschaltet() -> bool:
    """NOTAUS ueber die Dienstumgebung (``JARVIS_RAG_AUTOINDEX=0``).

    ⚠ NICHT DER REGELWEG. Gesteuert wird ueber den Cron-Auftrag - Intervall
    aendern, deaktivieren, loeschen. Diese Variable ist der Weg fuer einen
    Server, auf dem der Abgleich generell nicht laufen soll, ohne dafuer am
    Datenbestand zu drehen; sie wirkt AUCH, wenn der Auftrag aktiv ist.

    ⚠ FUNKTION, KEINE KONSTANTE - ein beim Import gelesener Wert waere bis zum
    Dienstneustart eingefroren, und genau daran ist im Projekt schon mehrfach
    eine Einstellung wirkungslos geblieben.

    Vorgabe ist AN: alles ausser einem ausdruecklichen Aus zaehlt als ein.
    """
    roh = str(os.environ.get("JARVIS_RAG_AUTOINDEX", "")).strip().lower()
    return roh in ("0", "false", "nein", "off", "aus")


# Zustand nur im Speicher: die Frage "laeuft die Automatik" ist nach einem
# Neustart ohnehin neu zu beantworten, und den letzten ECHTEN Indexlauf fuehrt
# `last_index.json` bereits. Eine zweite Datei waere ein zweiter Zustand, der
# driften kann.
_zustand_lock = threading.Lock()
_zustand: dict = {
    "letzte_pruefung": 0.0,     # wann zuletzt nachgesehen wurde
    "letzte_aenderung": 0.0,    # wann zuletzt wirklich etwas indiziert wurde
    "laeufe": 0,                # wie oft ein Reindex angestossen wurde
    "pruefungen": 0,
    "letzter_grund": "",        # was den letzten Lauf ausgeloest hat
    "letzter_fehler": "",
}


def zustand() -> dict:
    """Momentaufnahme fuer die Oberflaeche (Kopie, damit niemand hineinschreibt).

    ⚠ ``aktiv`` wird aus dem ECHTEN Auftrag abgeleitet, nicht behauptet: er muss
    existieren, aktiviert sein und der Notaus darf nicht greifen. Eine Anzeige,
    die "Automatik laeuft" sagt, waehrend der Administrator den Auftrag gerade
    deaktiviert hat, waere genau die Falschaussage, wegen der im Projekt schon
    mehrfach am falschen Ende gesucht wurde.
    """
    with _zustand_lock:
        d = dict(_zustand)
    d["notaus"] = abgeschaltet()
    job = None
    try:
        from backend.scheduler import cron_manager
        job = cron_manager.get_job(AUFTRAG_ID)
    except Exception:  # noqa: BLE001
        pass
    d["auftrag_da"] = job is not None
    d["auftrag_an"] = bool(job and job.get("enabled"))
    d["cron"] = (job or {}).get("cron", "")
    d["aktiv"] = d["auftrag_an"] and not d["notaus"]
    return d


def _merken(**felder) -> None:
    with _zustand_lock:
        _zustand.update(felder)


def pruefen() -> dict:
    """Liegt etwas an? **Rein lesend - stoesst KEINEN Indexlauf an.**

    Gibt ``{"geaendert": n, "verwaist": n, "dateien": n, "ordner": n}`` zurueck.
    ``geaendert`` zaehlt neue UND inhaltlich geaenderte Dateien (mtime),
    ``verwaist`` die Index-Eintraege, deren Datei es nicht mehr gibt.

    ⚠ ``streng=True`` bei den nutzbaren Ordnern ist hier Pflicht, nicht Kosmetik:
    nur so gilt ein bewusst getrenntes oder stummes Netzlaufwerk als "nicht
    aufraeumbar" und seine Eintraege werden gar nicht erst als verwaist
    gezaehlt. Ohne das meldete der Takt bei jeder getrennten Freigabe hunderte
    Loeschungen und stiesse einen Lauf an, der sie zu Recht nicht ausfuehrt.
    """
    from backend.tools import knowledge as K

    vs = K._get_vector_store()
    if vs is None:
        return {"geaendert": 0, "verwaist": 0, "dateien": 0, "ordner": 0,
                "hinweis": "kein Vektor-Index"}

    indexed = vs.get_indexed_files()
    folders = K._get_folders()
    alive = K._nutzbare_ordner(folders, indexed, streng=True)
    files = K._all_files(alive)

    geaendert = K._geaenderte_dateien(files, indexed)
    verwaist = K._verwaiste_dateien({str(f) for f in files}, indexed, alive)

    return {
        "geaendert": len(geaendert),
        "verwaist": len(verwaist),
        "dateien": len(files),
        "ordner": len(alive),
        # ⚠ HEISST BEWUSST NICHT "grund": `lauf()` mischt dieses dict in seine
        # Rueckgabe, und ein zweiter Schluessel gleichen Namens hat dort den
        # Grund des Laufs ueberschrieben - die Meldung war leer, obwohl sie
        # gesetzt wurde. Vom Waechter gefunden, nicht beim Lesen.
        "hinweis": "",
    }


def lauf() -> dict:
    """Ein Takt-Durchgang: nachsehen und nur bei Bedarf indizieren.

    Rueckgabe immer ein dict mit ``indiziert`` (bool) und ``grund`` (Klartext) -
    auch im Fehlerfall. Ein Takt, der still scheitert, waere von "nichts zu tun"
    nicht zu unterscheiden, und dann merkt niemand, dass die Automatik tot ist.
    """
    from backend.tools import knowledge as K

    if abgeschaltet():
        return {"indiziert": False,
                "grund": "Wissensabgleich ist abgeschaltet (JARVIS_RAG_AUTOINDEX=0)"}

    # Laeuft bereits ein Reindex (Wiederaufnahme nach Absturz, Auto-Mount,
    # Knopf in der Oberflaeche)? Dann NICHT zusaetzlich scannen - der Scan
    # konkurriert sonst mit dem laufenden Lauf um dieselben Netzlaufwerke.
    try:
        if K.get_index_progress().get("running"):
            _merken(letzte_pruefung=time.time())
            return {"indiziert": False, "grund": "Indexlauf laeuft bereits"}
    except Exception:  # noqa: BLE001
        pass

    try:
        stand = pruefen()
    except Exception as e:  # noqa: BLE001
        _merken(letzte_pruefung=time.time(), letzter_fehler=f"{type(e).__name__}: {e}"[:200])
        return {"indiziert": False, "grund": f"Pruefung fehlgeschlagen: {e}"}

    with _zustand_lock:
        _zustand["letzte_pruefung"] = time.time()
        _zustand["pruefungen"] += 1
        _zustand["letzter_fehler"] = ""

    if stand.get("hinweis"):
        # z.B. "kein Vektor-Index": nicht dasselbe wie "nichts zu tun", und als
        # "nichts geaendert" gemeldet suchte niemand mehr nach der Ursache.
        return {**stand, "indiziert": False, "grund": stand["hinweis"]}

    if not stand["geaendert"] and not stand["verwaist"]:
        return {**stand, "indiziert": False, "grund": "nichts geaendert"}

    grund = (f"{stand['geaendert']} neu/geaendert, "
             f"{stand['verwaist']} geloescht")
    try:
        # DER EINE vorhandene Weg. incremental=True: kein vs.clear(), aber das
        # Aufraeumen verwaister Eintraege laeuft - genau deshalb kommen
        # Loeschungen ueberhaupt an.
        K.force_reindex(incremental=True)
    except Exception as e:  # noqa: BLE001
        _merken(letzter_fehler=f"{type(e).__name__}: {e}"[:200])
        return {**stand, "indiziert": False, "grund": f"Indexlauf fehlgeschlagen: {e}"}

    with _zustand_lock:
        _zustand["letzte_aenderung"] = time.time()
        _zustand["laeufe"] += 1
        _zustand["letzter_grund"] = grund
    return {**stand, "indiziert": True, "grund": grund}


# ══ Der Cron-Auftrag ══════════════════════════════════════════════════════
AUFTRAG_ID = "wissensabgleich"
AUFTRAG_CRON = "*/5 * * * *"          # alle fuenf Minuten
_SAAT_MARKE = "wissensabgleich_gesaet"


def _auftrag_anlegen(cron: str = "") -> dict:
    """Den Wartungsauftrag anlegen bzw. ersetzen.

    ⚠ ``owner_privileged=False`` ist hier richtig und kein Versehen: der Job
    startet KEINEN Agenten und fuehrt nichts aus, was Rechte braeuchte - er
    ruft eine Funktion im Dienst. Systemrechte waeren eine Vollmacht ohne
    Gegenstand. Deshalb zeigt die Oberflaeche fuer ihn auch keinen
    Uebernehmen-Knopf (🔑), genau wie bei den Erinnerungen.
    """
    from backend.scheduler import cron_manager
    return cron_manager.add_job(
        label="Wissensabgleich",
        cron=cron or AUFTRAG_CRON,
        task="Sieht nach, ob sich in den Wissensordnern etwas geaendert hat, "
             "und indiziert nur dann nach (kein Agentenlauf).",
        enabled=True,
        job_id=AUFTRAG_ID,
        kind="wissensabgleich",
        created_via="rag_autoindex",
    )


def auftrag_vorhanden() -> bool:
    try:
        from backend.scheduler import cron_manager
        return cron_manager.get_job(AUFTRAG_ID) is not None
    except Exception:  # noqa: BLE001
        return False


def auftrag_sicherstellen() -> dict:
    """Beim Dienststart: den Auftrag EINMALIG anlegen.

    ⚠ MIT MARKE, und die ist der ganze Punkt: ohne sie kaeme ein bewusst
    GELOESCHTER Auftrag bei jedem Neustart zurueck - aus einer Entscheidung des
    Administrators wuerde ein wiederkehrender Fehler. Dieselbe Ueberlegung wie
    bei den Vorgabe-Rollen und der nachgetragenen Jira-Vorlage.

    Der Rueckweg ist ``auftrag_wiederherstellen()`` - eine Einbahnstrasse waere
    hier teuer: ohne Auftrag gibt es gar keine Automatik mehr.
    """
    try:
        from backend.config import config
        if auftrag_vorhanden():
            return {"angelegt": False, "grund": "vorhanden"}
        if config.get_setting(_SAAT_MARKE):
            return {"angelegt": False, "grund": "bewusst geloescht"}
        _auftrag_anlegen()
        config.save_setting(_SAAT_MARKE, True)
        return {"angelegt": True, "grund": "erstmalig angelegt"}
    except Exception as e:  # noqa: BLE001
        return {"angelegt": False, "grund": f"fehlgeschlagen: {e}"}


def auftrag_wiederherstellen(cron: str = "") -> dict:
    """Den Auftrag auf ausdruecklichen Wunsch neu anlegen (Rueckweg).

    Anders als ``auftrag_sicherstellen`` fragt das die Marke NICHT - hier hat
    ein Administrator ausdruecklich darum gebeten.
    """
    from backend.config import config
    job = _auftrag_anlegen(cron)
    try:
        config.save_setting(_SAAT_MARKE, True)
    except Exception:  # noqa: BLE001
        pass
    return {"angelegt": True, "job": job}
