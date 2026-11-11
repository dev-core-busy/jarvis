"""Schema-Graph: Indexlauf ueber den Schema-Bestand (inkrementell, abbrechbar).

Ablauf: Dateien finden -> mit ``roh.sqlite`` vergleichen (Groesse + mtime_ns)
-> nur neue/geaenderte im Prozess-Pool zerlegen -> verschwundene austragen
-> Graph ableiten (``schema_graph_store.ableiten``).

**Die Erfassung ist an das Schema gebunden** (Vorgabe des Betreibers
2026-11-10): jede Quelle bringt IHR Dateimuster und IHRE Entscheidung ueber das
Ableiten aus Spaltennamen mit, ``nur`` beschraenkt einen Lauf auf einzelne
Schemata (die uebrigen bleiben unangetastet), und der Status fuehrt je Schema
Fortschritt und Ergebnis (``je_schema``). Gemeinsam bleibt, was technisch EINS
ist: der Graph (er wird nach jeder Aenderung im Ganzen neu abgeleitet) und die
Sperre – es laeuft ein Lauf zugleich.

Drei Eigenschaften, die bei zweistelligen GB tragen muessen:

* **Wiederaufnahme ist der Normalfall.** Eine Datei gilt erst als erledigt,
  wenn ihre Rohfakten geschrieben sind. Ein Abbruch (Knopf, Neustart, OOM)
  verliert nur die Dateien, die gerade in Arbeit waren; der naechste Lauf
  macht dort weiter.
* **Eine Datei, die den Arbeitsprozess toetet, laeuft nicht endlos.** Vor dem
  Zerlegen wird ``versuche`` hochgezaehlt und erst bei Erfolg zurueckgesetzt.
  Steht es bei ``MAX_VERSUCHE``, wird die Datei als ``ausgelassen`` gefuehrt
  und benannt (Negativ-Cache mit Groesse + mtime: aendert sie sich, wird sie
  wieder versucht).
* **Nur ein Lauf zugleich – auch ueber Prozessgrenzen.** ``flock`` auf
  ``index.lock``: Dienst-Thread und Kommandozeile schliessen sich gegenseitig
  aus, und der Kernel gibt die Sperre auch nach ``kill -9`` frei.

Kommandozeile auf dem Server (als root, im Programmverzeichnis)::

    bash deploy/als_dienst.sh venv/bin/python -m backend.schema_graph_index

Ueber ``als_dienst.sh`` und nicht per ``runuser``: ohne ``--ordner`` liest der
Lauf die Skill-Einstellungen ueber ``backend.config``, und das gehoert seit
BSI M5 in die Dienstumgebung (Hauptschluessel per LoadCredential).

Die Arbeitsprozesse sind eigene Interpreter (``python -m
backend.schema_graph_parser``), KEIN ``multiprocessing``: ``fork`` erbte vom
Dienst Threads und Sperren in unbestimmtem Zustand, und ``spawn`` laedt das
Hauptmodul des Elternprozesses neu – im Dienst ``run_jarvis.py``, das
``backend.config`` importiert (gemessen: jeder Arbeitsprozess fuehrte das
Hauptmodul erneut aus). Stirbt ein Arbeitsprozess, wird er ersetzt; der Lauf
geht mit der naechsten Datei weiter.

Dieses Modul importiert ``backend.config`` NICHT (Aufrufer reichen die
Einstellungen herein) – nur die Kommandozeile liest sie, wenn kein Ordner
angegeben ist.
"""
from __future__ import annotations

import fcntl
import fnmatch
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from backend import atomar
from backend import schema_graph_parser as parser
from backend import schema_graph_store as store

MAX_VERSUCHE = 2
STANDARD_MUSTER = "*.sql,*.ddl,*.yaml,*.yml"   # gleich schema_graph_einstellungen.VORGABEN
COMMIT_ALLE_S = 5.0
STATUS_ALLE_S = 2.0
MAX_FEHLER_LISTE = 20

_abbruch = threading.Event()
_thread: threading.Thread | None = None
# Auftrag fuer einen NACHLAUF: kommt waehrend eines Laufs ein Upload/Loeschen,
# wird er nicht verworfen, sondern nach dem Ende noch einmal gefahren (mit den
# NEUESTEN Einstellungen) – sonst fehlte die zuletzt hochgeladene Datei, bis
# jemand von Hand neu erfasst.
_nachlauf: dict | None = None
_nachlauf_sperre = threading.Lock()
_auto_aktiv = False

# Felder eines Schemas im Status (``je_schema``), die ein Lauf zaehlt.
_JE_ZAEHLER = ("dateien_gesamt", "bytes_gesamt", "dateien_neu", "bytes_neu", "dateien_fertig",
               "bytes_fertig", "entfernt")


def status_pfad() -> Path:
    return store.ordner() / "status.json"


def status() -> dict:
    return atomar.lesen(status_pfad(), vorgabe={}) or {}


def _status_schreiben(st: dict) -> None:
    st["aktualisiert"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # Der Status nennt Pfade und Fehlertexte aus dem Schema-Bestand: 0640.
    atomar.schreiben(status_pfad(), st, modus=0o640, sicherung=False)


def anzahl_prozesse(wunsch) -> int:
    """Wie beim Vektorindex: zwei Kerne bleiben frei (Dienst + Suche)."""
    n = os.cpu_count() or 2
    try:
        w = int(wunsch or 0)
    except (TypeError, ValueError):
        w = 0
    obergrenze = max(1, n - 2)
    return max(1, min(w, obergrenze)) if w > 0 else obergrenze


def muster_liste(muster: str) -> list[str]:
    return [m.strip().lower() for m in (muster or STANDARD_MUSTER).split(",") if m.strip()]


def dateien_finden(ordner: list[str], muster: list[str]):
    """(pfad, groesse, mtime_ns) aller passenden Dateien. Symlinks werden NICHT
    verfolgt – ein Link auf ``/`` machte aus dem Schema-Ordner das ganze System."""
    for wurzel in ordner:
        for dp, dn, fn in os.walk(wurzel, followlinks=False):
            dn.sort()
            for name in sorted(fn):
                if not any(fnmatch.fnmatch(name.lower(), m) for m in muster):
                    continue
                p = os.path.join(dp, name)
                try:
                    st = os.stat(p, follow_symlinks=False)
                except OSError:
                    continue
                if not os.path.isfile(p) or os.path.islink(p):
                    continue
                yield p, st.st_size, st.st_mtime_ns


class LaeuftSchon(RuntimeError):
    pass


def _sperre_nehmen():
    store.ordner_anlegen(store.ordner())
    fd = os.open(store.ordner() / "index.lock", os.O_RDWR | os.O_CREAT, 0o640)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise LaeuftSchon("Ein Indexlauf laeuft bereits (anderer Prozess oder Thread).")
    return fd


def quelle_finder(quellen: list[dict]):
    """``datei -> quellen-id`` ueber das LAENGSTE passende Ordner-Praefix.

    Mit Schraegstrich verglichen: sonst gehoerte ``/srv/erp2/x.sql`` zur Quelle
    mit dem Ordner ``/srv/erp`` (dieselbe Praefix-Falle wie ``share_1`` in
    ``share_10``). Keine passende Quelle -> ``""`` (fuer niemanden sichtbar).
    """
    paare = []
    for q in quellen or []:
        for o in q.get("ordner") or []:
            o = os.path.normpath(str(o))
            paare.append((o.rstrip("/") + "/", str(q.get("id") or "")))
    paare.sort(key=lambda t: -len(t[0]))

    def finde(datei: str) -> str:
        d = os.path.normpath(str(datei))
        for praefix, qid in paare:
            if d.startswith(praefix):
                return qid
        return ""
    return finde


def _zuordnung_signatur(quellen, fk_ableiten: bool = True) -> str:
    """Wovon der abgeleitete Graph ausser den Dateien abhaengt: welcher Ordner
    zu welcher Quelle gehoert UND fuer welche Quelle aus Spaltennamen abgeleitet
    wird. Aendert sich nur der Schalter, hat sich keine Datei geaendert – ohne
    ihn in der Signatur meldete der Lauf "unveraendert" und der Graph behielt
    die alten Vermutungen."""
    return json.dumps(sorted((str(q.get("id") or ""), sorted(map(str, q.get("ordner") or [])),
                              bool(q.get("fk_ableiten", fk_ableiten)))
                             for q in quellen or []), ensure_ascii=False)


def _nur_vereinen(a, b):
    """Zwei Beschraenkungen zusammenlegen: ``None`` heisst "alle Schemata" und
    gewinnt, sonst die Vereinigung."""
    if a is None or b is None:
        return None
    return set(a) | set(b)


def ohne_struktur(con, finder) -> dict:
    """``quellen-id -> [pfad]`` der Dateien, die gelesen wurden, Anweisungen
    enthielten und trotzdem NICHTS zum Bestand beitragen.

    Aus dem Bestand gelesen, nicht aus dem Lauf gezaehlt: eine unveraenderte
    Datei wird beim naechsten Lauf nicht mehr angefasst, der Hinweis muss aber
    stehen bleiben, solange sie so daliegt.

    ⚠ WARUM (ECHT 2026-11-11): ein Skriptexport mit 1796 Anweisungen und 0
    erkannten Strukturen stand als "ok" im Bestand, die Erfassung meldete
    "unveraendert" – nirgends ein Wort davon, dass die Datei nichts brachte.

    Bewusst uebergangene Objekte zaehlen NICHT als "ohne Struktur": ein
    YAML-Objektexport legt je SEQUENCE/PACKAGE/FUNCTION/PROCEDURE eine eigene
    Datei an, und der Parser ueberspringt sie absichtlich
    (``objekt_uebersprungen``), ebenso Verzeichnisdateien (``verzeichnis``).
    Auf ECHT standen nach dem Neulesen 2183 solcher Dateien als Hinweis da –
    jede davon richtig gelesen.
    """
    aus: dict = {}
    for p, roh in con.execute("SELECT pfad, stat FROM dateien WHERE stand='ok' AND fakten=0 ORDER BY pfad"):
        try:
            s = json.loads(roh or "{}")
            n = 0
            if isinstance(s, dict):
                n = (int(s.get("anweisungen") or 0) - int(s.get("objekt_uebersprungen") or 0)
                     - int(s.get("verzeichnis") or 0))
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            aus.setdefault(finder(p), []).append(p)
    return aus


def lauf(ordner: list[str], muster: str = STANDARD_MUSTER, prozesse=0,
         fk_ableiten: bool = True, abbruch: threading.Event | None = None,
         nur_ableiten: bool = False, quellen: list[dict] | None = None,
         ordner_schutz: bool = True, nur=None) -> dict:
    """Ein vollstaendiger (inkrementeller) Lauf. Blockiert bis zum Ende.

    ``quellen``: ``[{"id", "ordner": [...], "muster", "fk_ableiten"}]`` – sind
    sie angegeben, sind ihre Ordner die Ordnerliste, und jedes Objekt traegt
    seine Quelle (daran haengt die Sichtbarkeit). ``muster`` und
    ``fk_ableiten`` einer Quelle gelten fuer IHRE Dateien bzw. Objekte; fehlen
    sie, gelten die gleichnamigen Argumente. Ohne ``quellen`` (Tests,
    Kommandozeile mit ``--ordner``) tragen alle Objekte die Quelle ``""``.

    ``nur``: Kennungen der Quellen, die dieser Lauf erfasst (None = alle). Die
    Dateien der UEBRIGEN Quellen werden weder gelesen noch ausgetragen – ihr
    Bestand bleibt, wie er ist. Dateien, die zu KEINER Quelle mehr gehoeren
    (Schema entfernt), traegt jeder Lauf aus, auch ein beschraenkter und einer
    mit leerem ``nur``. Der Graph wird danach im Ganzen neu abgeleitet.

    ``ordner_schutz``: ein nicht erreichbarer oder leerer Ordner traegt seinen
    Bestand NICHT aus (fuer Freigaben, die getrennt sein koennen). Fuer die
    FESTEN lokalen Schema-Ordner (``data/sql_schema_graph/<id>``) ist das
    falsch: dort heisst leer "alles geloescht", und ein fehlender Ordner ist
    ein Schema, in das noch nichts hochgeladen wurde – beides ohne Fehler.
    """
    abbruch = abbruch or threading.Event()
    # Suchplan: (Ordner, Musterliste, Quelle). Je Quelle IHR Muster.
    if quellen:
        ordner = list(dict.fromkeys(o for q in quellen for o in (q.get("ordner") or [])))
        plan = [(o, muster_liste(q.get("muster") or muster), str(q.get("id") or ""))
                for q in quellen for o in (q.get("ordner") or [])]
    else:
        plan = [(o, muster_liste(muster), "") for o in ordner]
    aktiv = None if (nur is None or not quellen) else {str(x) for x in nur}
    finder = quelle_finder(quellen or [])
    fd = _sperre_nehmen()
    # Ergebnisse frueherer Laeufe je Schema mitnehmen: ein Lauf ueber Schema A
    # darf nicht vergessen machen, wann Schema B zuletzt erfasst wurde.
    vorher = status().get("je_schema")
    kennungen = [str(q.get("id") or "") for q in quellen or []]
    st = {"laeuft": True, "phase": "Dateien suchen", "begonnen": time.strftime("%Y-%m-%d %H:%M:%S"),
          "ordner": list(ordner), "dateien_gesamt": 0, "dateien_neu": 0, "dateien_fertig": 0,
          "bytes_gesamt": 0, "bytes_neu": 0, "bytes_fertig": 0, "entfernt": 0,
          "fehler": [], "ausgelassen": [], "ohne_struktur": [], "graph": None, "ende": None, "ergebnis": "",
          "schemata": [], "je_schema": {k: v for k, v in (vorher if isinstance(vorher, dict) else {}).items()
                                        if k in kennungen and isinstance(v, dict)}}
    try:
        _status_schreiben(st)
        # ⚠ EIN NICHT ERREICHBARER ORDNER IST KEIN GELEERTER (Register: ein
        # Einhaengepunkt ohne Mount antwortet sofort und sieht leer aus). Seine
        # bekannten Dateien bleiben stehen; nur wenn KEIN Ordner erreichbar ist,
        # bricht der Lauf ab.
        fehlend = [o for o in ordner if not os.path.isdir(o)]
        if ordner_schutz:
            if ordner and len(fehlend) == len(ordner):
                raise FileNotFoundError("Kein Schema-Ordner erreichbar: " + ", ".join(fehlend))
            for o in fehlend:
                st["fehler"].append(f"Ordner nicht erreichbar, Bestand bleibt stehen: {o}")
        con = store.roh_oeffnen()
        bekannt = {p: (g, m, s, v) for p, g, m, s, v in
                   con.execute("SELECT pfad, groesse, mtime_ns, stand, versuche FROM dateien")}
        todo, gesehen = [], set()
        # Andere Parser-Fassung: ALLES neu lesen (siehe parser.FASSUNG) – sonst
        # bliebe ein mit dem alten Parser erfasster Bestand fuer immer so stehen.
        neu_lesen = bool(bekannt) and store.roh_fassung(con) != parser.FASSUNG
        if neu_lesen:
            st["hinweis"] = (f"Neue Parser-Fassung {parser.FASSUNG} – alle {len(bekannt)} bekannten "
                             "Dateien werden neu gelesen.")
            # Die Fassung gilt fuer den GANZEN Bestand und wird am Ende als
            # erreicht vermerkt – ein auf ein Schema beschraenkter Lauf liesse
            # die uebrigen fuer immer auf dem alten Stand. Also alle.
            aktiv = None
        # Nach der Entscheidung ueber ``aktiv``: was dieser Lauf erfasst.
        st["schemata"] = [k for k in kennungen if aktiv is None or k in aktiv]
        for k in st["schemata"]:
            st["je_schema"][k] = {"begonnen": st["begonnen"], "ende": None, "ergebnis": "",
                                  **{z: 0 for z in _JE_ZAEHLER}, "fehler": [], "ausgelassen": [],
                                  "ohne_struktur": []}
        je = st["je_schema"]
        # Ordner der Quellen, die dieser Lauf NICHT erfasst: ihr Bestand ruht.
        ruhend = tuple(os.path.normpath(o).rstrip("/") + "/" for o, _ml, qid in plan
                       if aktiv is not None and qid not in aktiv)
        if not nur_ableiten:
            suchen = [(o, ml) for o, ml, qid in plan
                      if o not in fehlend and (aktiv is None or qid in aktiv)]
            erreichbar = [o for o, _ml in suchen]
            for o, ml in suchen:
                for p, g, m in dateien_finden([o], ml):
                    if p in gesehen:
                        continue
                    gesehen.add(p)
                    zs = je.get(finder(p))
                    st["dateien_gesamt"] += 1
                    st["bytes_gesamt"] += g
                    if zs is not None:
                        zs["dateien_gesamt"] += 1
                        zs["bytes_gesamt"] += g
                    alt = bekannt.get(p)
                    if alt and alt[0] == g and alt[1] == m and alt[2] in ("ok", "fehler") and not neu_lesen:
                        continue
                    if alt and alt[0] == g and alt[1] == m and (alt[3] or 0) >= MAX_VERSUCHE:
                        st["ausgelassen"].append(p)
                        if zs is not None:
                            zs["ausgelassen"].append(p)
                        continue
                    todo.append((p, g, m))
                    if zs is not None:
                        zs["dateien_neu"] += 1
                        zs["bytes_neu"] += g
            # Ein erreichbarer Ordner OHNE eine einzige gefundene Datei, zu dem
            # der Bestand aber Dateien kennt, gilt ebenfalls als nicht
            # erreichbar (leerer Einhaengepunkt) – gemeldet, nicht ausgetragen.
            for o in (erreichbar if ordner_schutz else []):
                pr = o.rstrip("/") + "/"
                if not any(x.startswith(pr) for x in gesehen) and any(x.startswith(pr) for x in bekannt):
                    fehlend.append(o)
                    st["fehler"].append(f"Ordner ist leer, der Bestand kennt aber Dateien daraus – "
                                        f"nicht ausgetragen (Freigabe getrennt?): {o}")
            schutz = tuple(o.rstrip("/") + "/" for o in fehlend) if ordner_schutz else ()
            # Verschwundene Dateien (und solche ausserhalb der Ordnerliste) –
            # aber nichts aus den Ordnern der Quellen, die dieser Lauf nicht
            # erfasst: dort wurde gar nicht nachgesehen.
            weg = [p for p in bekannt if p not in gesehen and not (schutz and p.startswith(schutz))
                   and not (ruhend and os.path.normpath(p).startswith(ruhend))]
            for p in weg:
                store.roh_entfernen(con, p)
                zs = je.get(finder(p))
                if zs is not None:
                    zs["entfernt"] += 1
            con.commit()
            st["entfernt"] = len(weg)
        st["dateien_neu"] = len(todo)
        st["bytes_neu"] = sum(g for _p, g, _m in todo)
        st["phase"] = "Dateien zerlegen"
        _status_schreiben(st)
        if todo:
            _zerlegen(con, todo, anzahl_prozesse(prozesse), abbruch, st, finder)
        if abbruch.is_set():
            st["ergebnis"] = "abgebrochen"
            return st
        leer = ohne_struktur(con, finder)
        st["ohne_struktur"] = [p for k in sorted(leer) for p in leer[k]
                               if not quellen or k in st["schemata"]]
        for k in st["schemata"]:
            je[k]["ohne_struktur"] = leer.get(k, [])
        if not nur_ableiten and store.roh_fassung(con) != parser.FASSUNG:
            # Erst NACH vollstaendigem Lesen: ein abgebrochener Lauf liest beim
            # naechsten Mal wieder alles (teurer, aber nie ein halber Bestand).
            store.roh_fassung_setzen(con, parser.FASSUNG)
            con.commit()
        # Auch eine geaenderte ZUORDNUNG (Ordner einer anderen Quelle zugeschlagen)
        # verlangt ein neues Ableiten, obwohl sich keine Datei geaendert hat –
        # sonst truege ein Objekt weiter die Quelle, aus der es entfernt wurde.
        sig = _zuordnung_signatur(quellen, fk_ableiten)
        sig_pfad = store.ordner() / "zuordnung.json"
        try:
            sig_alt = sig_pfad.read_text(encoding="utf-8")
        except OSError:
            sig_alt = None
        geaendert = (bool(todo) or st["entfernt"] or not store.graph_pfad().exists()
                     or nur_ableiten or sig_alt != sig)
        if geaendert:
            st["phase"] = "Graph ableiten"
            _status_schreiben(st)

            def melde(t):
                st["phase"] = "Graph ableiten: " + t
                _status_schreiben(st)
            # Mit Quellen entscheidet JEDE fuer ihre Objekte, ob aus Spaltennamen
            # abgeleitet wird; ohne Quellen gilt das Argument fuer alles.
            fk_quellen = ({str(q.get("id") or "") for q in quellen if q.get("fk_ableiten", fk_ableiten)}
                          if quellen else None)
            st["graph"] = store.ableiten(con, fk_ableiten=bool(fk_quellen) if quellen else fk_ableiten,
                                         melde=melde, abbruch=abbruch.is_set, quelle_von=finder,
                                         fk_quellen=fk_quellen)
            if st["graph"].get("abgebrochen"):
                st["ergebnis"] = "abgebrochen"
                return st
            # Erst NACH dem gelungenen Tausch: bricht das Ableiten ab, bleibt die
            # alte Signatur stehen und der naechste Lauf leitet erneut ab.
            tmp = sig_pfad.with_name(f".{sig_pfad.name}.{os.getpid()}.tmp")
            tmp.write_text(sig, encoding="utf-8")
            os.chmod(tmp, 0o640)
            os.replace(tmp, sig_pfad)
        st["ergebnis"] = "fertig" if geaendert else "unveraendert"
        con.close()
        return st
    except Exception as e:  # noqa: BLE001 – der Grund gehoert in den Status
        st["ergebnis"] = "fehler"
        st["fehler"] = (st.get("fehler") or [])[-(MAX_FEHLER_LISTE - 1):] + [f"{type(e).__name__}: {e}"]
        return st
    finally:
        st["laeuft"] = False
        st["ende"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if st.get("phase", "").startswith("Graph ableiten") and st["ergebnis"] == "fertig":
            st["phase"] = "fertig"
        # Das Ergebnis des Laufs gilt fuer jedes Schema, das er erfasst hat.
        for k in st.get("schemata") or []:
            zs = st["je_schema"].get(k)
            if zs is not None:
                zs["ergebnis"] = st["ergebnis"]
                zs["ende"] = st["ende"]
        _status_schreiben(st)
        os.close(fd)


class _Arbeiter:
    """Ein Arbeitsprozess (``python -m backend.schema_graph_parser``) samt
    Lese-Thread. Stirbt der Prozess, liefert ``zerlegen`` ein Fehlerergebnis,
    und der Aufrufer ersetzt ihn – der Lauf geht weiter.
    """

    def __init__(self):
        umg = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "backend.schema_graph_parser"],
            cwd=str(store.PROJECT_ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
            start_new_session=True, env=umg)

    def zerlegen(self, pfad: str) -> dict:
        try:
            self.proc.stdin.write(pfad + "\n")
            self.proc.stdin.flush()
            zeile = self.proc.stdout.readline()
        except (BrokenPipeError, OSError, ValueError):
            zeile = ""
        if not zeile:
            rc = self.proc.poll()
            return {"pfad": pfad, "ok": False, "fakten": [], "stat": {}, "abgestuerzt": True,
                    "fehler": f"Arbeitsprozess beendet (rc={rc}; Speicher?) beim Zerlegen"}
        return json.loads(zeile)

    def beenden(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _zerlegen(con, todo: list, n_proz: int, abbruch: threading.Event, st: dict, finder=None) -> None:
    je = st.get("je_schema") or {}
    finder = finder or (lambda _p: "")
    # Grosse Dateien zuerst: sonst wartet am Ende ein einzelner Prozess auf
    # die 5-GB-Datei, waehrend die anderen nichts mehr zu tun haben.
    todo.sort(key=lambda t: -t[1])
    auftraege: queue.Queue = queue.Queue()
    for t in todo:
        auftraege.put(t)
    ergebnisse: queue.Queue = queue.Queue()
    arbeiter: list[_Arbeiter] = []
    sperre = threading.Lock()

    def schleife():
        a = _Arbeiter()
        with sperre:
            arbeiter.append(a)
        while not abbruch.is_set():
            try:
                t = auftraege.get_nowait()
            except queue.Empty:
                break
            ergebnisse.put(("start", t, None))
            erg = a.zerlegen(t[0])
            ergebnisse.put(("ende", t, erg))
            if erg.get("abgestuerzt"):
                a.beenden()
                if abbruch.is_set():
                    break
                a = _Arbeiter()
                with sperre:
                    arbeiter.append(a)
        a.beenden()

    threads = [threading.Thread(target=schleife, name=f"schema-graph-arbeiter-{i}", daemon=True)
               for i in range(min(n_proz, len(todo)))]
    for th in threads:
        th.start()
    t0 = time.time()
    letzter_commit = letzter_status = time.time()
    try:
        while any(th.is_alive() for th in threads) or not ergebnisse.empty():
            try:
                art, (p, g, m), erg = ergebnisse.get(timeout=STATUS_ALLE_S)
            except queue.Empty:
                art = None
            if art == "start":
                # Versuch VOR dem Zerlegen vermerken (Negativ-Cache gegen eine
                # Datei, die den Arbeitsprozess beendet – auch wenn danach der
                # ganze Dienst stirbt).
                con.execute("INSERT INTO dateien(pfad, groesse, mtime_ns, stand, versuche) "
                            "VALUES (?,?,?,'laeuft',1) ON CONFLICT(pfad) DO UPDATE SET "
                            "versuche=CASE WHEN groesse=excluded.groesse AND mtime_ns=excluded.mtime_ns "
                            "THEN versuche+1 ELSE 1 END, groesse=excluded.groesse, "
                            "mtime_ns=excluded.mtime_ns, stand='laeuft'", (p, g, m))
                con.commit()
            elif art == "ende":
                if erg.get("abgestuerzt"):
                    # Rohfakten NICHT ersetzen: "versuche" bleibt hochgezaehlt
                    # und entscheidet beim naechsten Lauf ueber das Auslassen.
                    con.execute("UPDATE dateien SET stand='laeuft', fehler=? WHERE pfad=?",
                                (erg.get("fehler") or "", p))
                else:
                    store.roh_ersetzen(con, erg, g, m)
                st["dateien_fertig"] += 1
                st["bytes_fertig"] += g
                zs = je.get(finder(p))
                if zs is not None:
                    zs["dateien_fertig"] += 1
                    zs["bytes_fertig"] += g
                if not erg.get("ok"):
                    st["fehler"] = (st["fehler"] + [f"{p}: {erg.get('fehler')}"])[-MAX_FEHLER_LISTE:]
                    if zs is not None:
                        zs["fehler"] = (zs["fehler"] + [f"{p}: {erg.get('fehler')}"])[-MAX_FEHLER_LISTE:]
            jetzt = time.time()
            if jetzt - letzter_commit >= COMMIT_ALLE_S:
                con.commit()
                letzter_commit = jetzt
            if jetzt - letzter_status >= STATUS_ALLE_S:
                dauer = max(0.001, jetzt - t0)
                rate = st["bytes_fertig"] / dauer
                st["mb_pro_s"] = round(rate / 1e6, 1)
                rest = max(0, st["bytes_neu"] - st["bytes_fertig"])
                st["rest_s"] = int(rest / rate) if rate > 0 else None
                _status_schreiben(st)
                letzter_status = jetzt
            if abbruch.is_set():
                with sperre:
                    for a in arbeiter:
                        a.beenden()
    finally:
        con.commit()
        if abbruch.is_set():
            with sperre:
                for a in arbeiter:
                    a.beenden()
        for th in threads:
            th.join(timeout=10)


# ─── Hintergrundlauf im Dienst ──────────────────────────────────────────────

def starten(ordner: list[str], **kw) -> str:
    """Startet einen Lauf in einem Daemon-Thread. Rueckgabe: Meldung."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return "laeuft bereits"
    if status().get("laeuft"):
        # Ein anderer Prozess? Die Sperre entscheidet, nicht der Status (der
        # bleibt nach kill -9 auf "laeuft" stehen).
        try:
            fd = _sperre_nehmen()
            os.close(fd)
        except LaeuftSchon:
            return "laeuft bereits (anderer Prozess)"
    _abbruch.clear()
    _thread = threading.Thread(target=lauf, args=(ordner,), kwargs={**kw, "abbruch": _abbruch},
                               name="schema-graph-index", daemon=True)
    _thread.start()
    return "gestartet"


def anstossen(ordner: list[str], **kw) -> str:
    """Automatische Erfassung nach Upload/Loeschen: startet einen Lauf oder
    merkt einen Nachlauf vor. Rueckgabe "gestartet" oder "vorgemerkt".

    ⚠ Entschieden wird an ``_auto_aktiv`` UNTER DER SPERRE, nicht an
    ``is_alive()``: zwischen "kein Nachlauf vorgemerkt" und dem Ende des
    Threads liegt ein Fenster, in dem ein Upload sonst nur vormerkte – und
    niemand den Auftrag mehr abholte.
    """
    global _nachlauf, _thread, _auto_aktiv
    with _nachlauf_sperre:
        if _auto_aktiv:
            neu = {"ordner": ordner, **kw}
            if _nachlauf is not None:
                # Zwei Vormerkungen fuer verschiedene Schemata: der Nachlauf
                # erfasst BEIDE – sonst verdraengte der zweite Upload den ersten.
                neu["nur"] = _nur_vereinen(_nachlauf.get("nur"), neu.get("nur"))
            _nachlauf = neu
            return "vorgemerkt"
        _auto_aktiv = True
        _abbruch.clear()
        _thread = threading.Thread(target=_lauf_mit_nachlauf, args=(ordner,), kwargs=kw,
                                   name="schema-graph-index", daemon=True)
        _thread.start()
        return "gestartet"


def _lauf_mit_nachlauf(ordner, **kw):
    global _nachlauf, _auto_aktiv
    auftrag = {"ordner": ordner, **kw}
    versuche = 0
    try:
        while True:
            try:
                arg = dict(auftrag)
                lauf(arg.pop("ordner"), abbruch=_abbruch, **arg)
            except LaeuftSchon:
                # Ein Lauf eines ANDEREN Prozesses (Kommandozeile) haelt die
                # Sperre: warten statt verwerfen, sonst ginge der Upload verloren.
                versuche += 1
                if versuche > 120 or _abbruch.is_set():
                    _o = auftrag.get("ordner")
                    print(f"[SchemaGraph] Erfassung von '{_o}' aufgegeben: Sperre "
                          f"eines anderen Prozesses nach {versuche * 30} s nicht "
                          "frei – bitte von Hand erfassen", flush=True)
                    return
                time.sleep(30)
                with _nachlauf_sperre:
                    if _nachlauf is not None:
                        auftrag, _nachlauf = _nachlauf, None
                continue
            except Exception as e:  # noqa: BLE001
                # Der Lauf hat seinen Fehler schon in den Status geschrieben.
                # NICHT hier enden: ein vorgemerkter Nachlauf (Upload waehrend
                # des Laufs) ginge sonst verloren, bis jemand von Hand erfasst.
                print(f"[SchemaGraph] Erfassung fehlgeschlagen: {e}", flush=True)
            with _nachlauf_sperre:
                if _nachlauf is None or _abbruch.is_set():
                    _nachlauf = None
                    _auto_aktiv = False
                    return
                auftrag, _nachlauf = _nachlauf, None
    finally:
        with _nachlauf_sperre:
            _auto_aktiv = False
            if _nachlauf is not None:
                # Der Thread endet mit vorgemerktem Auftrag (fremde Sperre nicht
                # frei oder Abbruch). NICHT liegen lassen: der naechste, fremde
                # Lauf fuehrte ihn sonst mit veralteten Einstellungen ein zweites
                # Mal aus (Review 2026-11-10). Laut melden statt still verwerfen.
                _o = _nachlauf.get("ordner")
                print(f"[SchemaGraph] Vorgemerkte Erfassung von '{_o}' verworfen "
                      "– bitte von Hand erfassen", flush=True)
                _nachlauf = None


def vorgemerkt():
    """Wartet ein Nachlauf? ``None`` = nein, sonst ``{"nur": [Kennungen] | None}``
    (``None`` darin = alle Schemata). Nur fuer die Anzeige."""
    with _nachlauf_sperre:
        if _nachlauf is None:
            return None
        nur = _nachlauf.get("nur")
        return {"nur": None if nur is None else sorted(str(x) for x in nur)}


def laeuft_hier() -> bool:
    """Laeuft ein Lauf in DIESEM Prozess (nur der laesst sich hier abbrechen)?"""
    return _thread is not None and _thread.is_alive()


def abbrechen() -> str:
    if _thread is None or not _thread.is_alive():
        return "kein Lauf in diesem Prozess"
    _abbruch.set()
    return "Abbruch angefordert"


# ─── Kommandozeile ──────────────────────────────────────────────────────────

def _main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Schema-Graph indizieren (inkrementell).")
    ap.add_argument("--ordner", action="append", help="Schema-Ordner (mehrfach moeglich); "
                    "ohne Angabe aus der Skill-Konfiguration")
    ap.add_argument("--muster", default=None)
    ap.add_argument("--prozesse", type=int, default=None)
    ap.add_argument("--ohne-ableiten-aus-namen", action="store_true")
    ap.add_argument("--nur-ableiten", action="store_true", help="nur den Graphen neu ableiten")
    ap.add_argument("--schema", action="append", help="nur dieses Schema erfassen (Kennung, mehrfach "
                    "moeglich); ohne Angabe alle")
    a = ap.parse_args(argv)
    cfg = {}
    if not a.ordner or a.muster is None or a.prozesse is None:
        from backend.config import config  # noqa: PLC0415 – nur hier, siehe Modulkopf
        cfg = config.get_skill_states().get("schema_graph", {}).get("config", {}) or {}
    quellen = None
    if a.ordner:
        ordner = a.ordner
    else:
        from backend import schema_graph_einstellungen as _sge  # noqa: PLC0415
        voll = _sge.aus_zustand(cfg)
        # Je Schema der FESTE Ordner data/sql_schema_graph/<id> (seit 2026-11-07)
        # mit SEINEM Muster und SEINEM Ableiten – wie der Dienst.
        quellen = _sge.quellen(voll)
        # Eine Angabe auf der Kommandozeile gilt fuer alle erfassten Schemata.
        for q in quellen:
            if a.muster:
                q["muster"] = a.muster
            if a.ohne_ableiten_aus_namen:
                q["fk_ableiten"] = False
        ordner = [o for q in quellen for o in q["ordner"]]
        cfg = voll
    if not ordner:
        print("Kein Schema angegeben/konfiguriert.")
        return 2
    nur = None
    if a.schema:
        if quellen is None:
            print("--schema gilt nur ohne --ordner (Schemata aus den Einstellungen).")
            return 2
        unbekannt = sorted(set(a.schema) - {q["id"] for q in quellen})
        if unbekannt:
            print("Unbekanntes Schema: " + ", ".join(unbekannt) + " (bekannt: "
                  + ", ".join(q["id"] for q in quellen) + ")")
            return 2
        nur = set(a.schema)
    t0 = time.time()
    try:
        st = lauf(ordner, muster=a.muster or STANDARD_MUSTER,
                  prozesse=a.prozesse if a.prozesse is not None else cfg.get("prozesse") or 0,
                  fk_ableiten=not a.ohne_ableiten_aus_namen,
                  nur_ableiten=a.nur_ableiten, quellen=quellen, nur=nur,
                  # Feste lokale Ordner: leer heisst geloescht (siehe lauf()).
                  ordner_schutz=quellen is None)
    except LaeuftSchon as e:
        print(str(e))
        return 3
    print(json.dumps({k: v for k, v in st.items() if k != "ausgelassen"}, ensure_ascii=False, indent=1))
    if st.get("ausgelassen"):
        print(f"ausgelassen ({len(st['ausgelassen'])}): " + ", ".join(st["ausgelassen"][:20]))
    print(f"Dauer: {time.time() - t0:.1f} s")
    return 0 if st.get("ergebnis") in ("fertig", "unveraendert") else 1


if __name__ == "__main__":
    raise SystemExit(_main())
