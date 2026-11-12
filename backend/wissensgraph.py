"""Wissensgraph: Speicher, Datenmodell, Zusammenfuehren, Warteschlange.

Plan: "Wissensgraph fuer das Jarvis-RAG" (Vorlage llm_wiki, nur das Konzept –
llm_wiki steht unter GPL-3.0, hier ist nichts davon uebernommen). Messbericht
Phase 0: ``docs/wissensgraph-phase0-messbericht.md``.

Dieses Modul haelt ALLES, was auf Platte liegt; die LLM-Extraktion und der
Arbeiter stehen in ``backend/wissensgraph_extraktion.py``.

Ablage (JSON wie der Rest des Projekts, kein SQLite)::

    data/graph/
      quellen/<sha256(pfad)>.json  – je Quelldatei: Entitaeten + Relationen
      graph.json                   – zusammengefuehrt, aus quellen/ abgeleitet
      aliasse.json                 – Admin-Entscheidungen (ueberstehen Neuaufbau)
      queue.json                   – Warteschlange, uebersteht einen Neustart
      status.json                  – Fortschritt, Token, letzte Fehler
      unlesbar.json                – Negativ-Cache (Pfad + mtime)

⚠ ORDNER-ISOLATION: in den Graphen kommen NUR Pfade unter ``data/rag/`` und
``/mnt/rag/`` – geprueft an JEDEM Eintritt (``_erlaubt``), nicht nur am
ersten. ``data/erfahrung``, ``data/knowledge`` und Systemordner liegen
ausserhalb dieser beiden Praefixe und kommen damit nie hinein.

⚠ DREI PFADFORMEN: FAISS speichert absolut, ``_vector_search`` relativ, die
Wissensgruppen in der Manifest-Form (``knowledge_groups._rel``: relativ zum
Projekt, Einhaengepunkte ohne fuehrenden Schraegstrich). Der Graph speichert
AUSSCHLIESSLICH die Manifest-Form – ``manifest_form`` ist die eine Umrechnung,
der Waechter prueft sie gegen ``knowledge_groups._rel``.

⚠ SCHLUESSEL IST PFAD + mtime DES INDEX, nicht Pfad + mtime + Groesse wie im
Plan. Die Eingabe der Extraktion sind die Chunks des Vektorindex; deren
Identitaet ist genau dessen mtime (der Index bettet bei jeder mtime-Aenderung
neu ein). Eine Groesse braeuchte ein ``stat`` auf der CIFS-Freigabe und
saehe nichts, was die mtime nicht schon sieht. Zusaetzlich steht in jeder
Quelle die Pruefsumme des Eingabetexts (``text_sha``).

⚠ mtime IST NICHT INHALT (seit 2026-11-12). Eine neue mtime reiht die Datei
ein – ein Modellaufruf folgt aber nur, wenn sich der EINGABETEXT der Extraktion
geaendert hat (``text_sha``). Sonst wird die Quelle nur BESTAETIGT
(``quelle_bestaetigen``): neue ``mtime``, alter ``stand``. ``stand`` ist die
mtime der letzten Extraktion, die wirklich neuen Text gelesen hat; nach ihm
richten sich Widerspruchs- und Wiki-Nachlauf (``inhalts_stand``). Anlass ECHT
2026-11-12: das Loesungsarchiv schrieb nachts 3.073 Dateien neu, in den meisten
nur Zaehler und Ticketliste – der Graph las jede komplett neu (~6.000
Modellaufrufe), und der Nachlauf pruefte danach jeden betroffenen Begriff
erneut, weil sich die mtime seiner Quellen geaendert hatte. Fehlt ``stand``
(Altbestand), gilt die mtime – das Verhalten bleibt dort wie vorher.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import unicodedata
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ORDNER = PROJECT_ROOT / "data" / "graph"

TYPEN = ("person", "organisation", "system", "produkt", "konzept", "ort", "prozess")
TYP_QUELLE = "quelle"
KANTE_ERWAEHNT = "erwaehnt_in"
KANTE_WIDERSPRUCH = "widerspricht"

# Die beiden erlaubten Praefixe in Manifest-Form – MIT Schraegstrich, sonst
# traefe ``data/rag2`` (dieselbe Praefix-Falle wie share_1 in share_10).
ERLAUBT = ("data/rag/", "mnt/rag/")

MAX_FEHLER_LISTE = 20

_sperre = threading.RLock()
_graph_cache: dict | None = None
_graph_veraltet = True
_queue_cache: dict | None = None
# quellen_index()/inhalts_stand(): (Ordner, Inode, mtime_ns) -> beide Indizes.
_index_cache: tuple | None = None
_INDEX_FRISCH_S = 2.0


# ─── Pfade ──────────────────────────────────────────────────────────────────

def _o() -> Path:
    """Ablageordner – als Funktion, damit ein Test ``ORDNER`` umlenken kann."""
    return ORDNER


def manifest_form(pfad) -> str:
    """Absolut/relativ → Manifest-Form (wie ``knowledge_groups._rel``).

    Rein textuell (kein ``resolve``): die Funktion laeuft fuer jeden Eintrag
    eines Indexlaufs, auch fuer Dateien auf einer toten Freigabe.
    """
    s = str(pfad or "").replace("\\", "/").strip()
    if not s:
        return ""
    p = Path(s)
    if p.is_absolute():
        try:
            return p.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return p.as_posix().lstrip("/")
    return p.as_posix().lstrip("/")


def absolut(manifest: str) -> str:
    """Manifest-Form → absoluter Pfad, wie ihn FAISS speichert."""
    m = str(manifest or "")
    if m.startswith("mnt/"):
        return "/" + m
    return str(PROJECT_ROOT / m)


def _erlaubt(manifest: str) -> bool:
    """Gehoert der Pfad in den Graphen? Die EINE Isolationsregel."""
    m = str(manifest or "")
    if not m.startswith(ERLAUBT):
        return False
    teile = m.split("/")
    # ".." oder leere Segmente: ein Pfad, der nach dem Normieren woanders
    # landet, ist kein Pfad unter data/rag.
    if any(t in ("", ".", "..") for t in teile):
        return False
    return len(teile) >= 3


def ist_graph_pfad(pfad) -> bool:
    return _erlaubt(manifest_form(pfad))


def _quell_datei(manifest: str) -> Path:
    h = hashlib.sha256(manifest.encode("utf-8")).hexdigest()[:32]
    return _o() / "quellen" / f"{h}.json"


def _json_lesen(p: Path, vorgabe):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return vorgabe
    except Exception as e:  # noqa: BLE001
        print(f"[Wissensgraph] {p.name} nicht lesbar: {e}", flush=True)
        return vorgabe


def _ordner_anlegen() -> None:
    """Ablage mit 0750 anlegen: der Graph traegt Inhalte aus ALLEN Quellen,
    ein ``cat`` aus der Sandbox der Domain-Benutzer darf ihn nicht lesen
    (``sandbox.PRIVATE_DIRS`` setzt das beim Start nach, hier gilt es sofort)."""
    o = _o()
    if not o.is_dir():
        o.mkdir(parents=True, exist_ok=True)
        try:
            o.chmod(0o750)
        except OSError:
            pass


def _json_teile(daten, tiefe: int = 1, block: int = 1000):
    """Derselbe Text wie ``json.dumps(daten, ensure_ascii=False)``, in Stuecken.

    ⚠ WARUM NICHT ``json.dump(daten, f)``: das benutzt den PYTHON-Encoder
    (``iterencode`` ohne ``_one_shot``) – gemessen auf ECHT 1,27 s fuer die
    17-MB-``widersprueche.json`` gegen 0,17 s mit dem C-Encoder von
    ``json.dumps``, und der Nachlauf schreibt sie je geprueftem Begriff.
    Ein einziges ``dumps`` haelte dafuer die 161-MB-``graph.json`` zweimal im
    Speicher (Text + Bytes). Deshalb: die obersten ``tiefe`` Ebenen werden
    zerlegt, und darunter geht eine grosse Liste bzw. ein grosses dict in
    Bloecken zu ``block`` Elementen an ``dumps`` – C-Tempo, Speicher begrenzt
    auf einen Block. Je ELEMENT ein ``dumps`` waere wieder langsam (auf DEV
    gemessen: 10.649 Eintraege ≈ dreimal ein einzelnes ``dumps``).
    Trenner wie bei ``json.dumps`` (``", "`` und ``": "``)."""
    # Nicht-String-Schluessel wandelt json.dumps selbst um (True -> "true",
    # None -> "null"); ein solches dict geht deshalb im Ganzen an dumps.
    nur_str = isinstance(daten, dict) and all(isinstance(k, str) for k in daten)
    if tiefe > 0 and daten and nur_str:
        yield "{"
        for i, (k, v) in enumerate(daten.items()):
            yield ("" if i == 0 else ", ") + json.dumps(k, ensure_ascii=False) + ": "
            yield from _json_teile(v, tiefe - 1, block)
        yield "}"
    elif tiefe > 0 and isinstance(daten, (list, tuple)) and daten:
        yield "["
        for i, v in enumerate(daten):
            if i:
                yield ", "
            yield from _json_teile(v, tiefe - 1, block)
        yield "]"
    elif isinstance(daten, (list, tuple)) and len(daten) > block:
        # dumps(Teilliste)[1:-1] sind die Elemente samt ", " dazwischen
        yield "["
        for j in range(0, len(daten), block):
            yield ("" if j == 0 else ", ") + json.dumps(list(daten[j:j + block]), ensure_ascii=False)[1:-1]
        yield "]"
    elif nur_str and len(daten) > block:
        paare = list(daten.items())
        yield "{"
        for j in range(0, len(paare), block):
            yield ("" if j == 0 else ", ") + json.dumps(dict(paare[j:j + block]), ensure_ascii=False)[1:-1]
        yield "}"
    else:
        yield json.dumps(daten, ensure_ascii=False)


def _json_schreiben(p: Path, daten) -> None:
    """Atomar: erst Temp-Datei vollstaendig, dann ``os.replace``."""
    _ordner_anlegen()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(_json_teile(daten))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def _veraltet_markieren() -> None:
    global _graph_veraltet
    _graph_veraltet = True


# ─── Namen ──────────────────────────────────────────────────────────────────

# Nur AM ENDE des Namens: "Contoso GmbH" → "contoso", aber "AG-Leitung" bleibt.
_RECHTSFORM = re.compile(r"(?:\s+(?:gmbh(?:\s+co\s+kg)?|ag|kg|ohg|se|e\s?v|ev|inc|ltd|llc|co))+$")


def norm_name(name: str) -> str:
    """Normform eines Entitaetsnamens (Gross/Klein, Umlaute, Rechtsform).

    ⚠ KEINE Plural-Regel, anders als im Plan: deutsche Mehrzahl ist per Regel
    nicht sicher zu treffen ("Status", "Prozess", "Lizenzen") – ein falsches
    Abschneiden fuehrte zwei verschiedene Dinge AUTOMATISCH zusammen. Die
    Mehrzahl faengt der Normierungsschritt des Modells (bekannte Namen im
    Prompt) bzw. die Pruefliste. Messbericht 3.3: selbst e5-Kosinus >= 0,95
    enthielt noch Fehlpaare, automatisch zusammengefuehrt wird deshalb NUR bei
    gleicher Normform.
    """
    s = unicodedata.normalize("NFKC", str(name or "")).casefold()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = re.sub(r"[^\w]+", " ", s).replace("_", " ")
    s = " ".join(s.split())
    s = _RECHTSFORM.sub("", s).strip()
    return s


def norm_art(art: str) -> str:
    """Kantenart vereinheitlichen: "gehört_zu", "gehoert_zu" und "gehört zu"
    sind EINE Art (gemessen auf DEV: alle drei Schreibweisen im selben Lauf,
    obwohl der Prompt snake_case ohne Umlaut vorgibt). Beim Ableiten
    angewandt – gilt damit auch fuer schon gespeicherte Quellen."""
    s = norm_name(art).replace(" ", "_")
    return s[:60] or "bezug"


def knoten_id(name: str) -> str:
    return "e:" + norm_name(name)


# ─── Quellen ────────────────────────────────────────────────────────────────

def quelle_schreiben(pfad, mtime: float, entitaeten: list, relationen: list,
                     modell: str = "", info: dict | None = None) -> bool:
    """Extraktionsergebnis EINER Quelldatei ablegen (ersetzt das vorige).

    Gibt False zurueck (und schreibt nichts), wenn der Pfad nicht in den
    Graphen gehoert – das ist der Eintritt, an dem die Isolation haengt.
    """
    m = manifest_form(pfad)
    if not _erlaubt(m):
        return False
    daten = {"pfad": m, "mtime": float(mtime), "stand": float(mtime), "modell": modell,
             "zeitpunkt": time.time(), "entitaeten": list(entitaeten or []),
             "relationen": list(relationen or []), **(info or {})}
    with _sperre:
        _json_schreiben(_quell_datei(m), daten)
        _veraltet_markieren()
    return True


def stand_von(q: dict) -> float:
    """Inhaltsstand einer Quelle: mtime der letzten Extraktion, die neuen Text
    gelesen hat. Altbestand ohne ``stand``: die mtime (Verhalten wie vorher)."""
    return float(q.get("stand") or q.get("mtime") or 0)


def quelle_bestaetigen(pfad, mtime: float) -> bool:
    """Neue mtime, UNVERAENDERTER Eingabetext: die Quelle uebernimmt die mtime
    (sonst reihte der Abgleich sie immer wieder ein), behaelt Entitaeten,
    Relationen und ``stand``. Der Graph wird NICHT als veraltet markiert – er
    liest aus einer Quelle nur Entitaeten, Relationen und ``stand``, und die
    bleiben gleich. False: keine Quelle da (dann muss extrahiert werden)."""
    m = manifest_form(pfad)
    if not _erlaubt(m):
        return False
    with _sperre:
        q = _json_lesen(_quell_datei(m), None)
        if not isinstance(q, dict) or q.get("pfad") != m:
            return False
        q["stand"] = stand_von(q)
        q["mtime"] = float(mtime)
        q["bestaetigt"] = time.time()
        _json_schreiben(_quell_datei(m), q)
    return True


def quelle_lesen(pfad) -> dict | None:
    m = manifest_form(pfad)
    if not _erlaubt(m):
        return None
    with _sperre:
        q = _json_lesen(_quell_datei(m), None)
    return q if isinstance(q, dict) and q.get("pfad") == m else None


def quellen_alle() -> list[dict]:
    """Alle gespeicherten Quellen. Eine Datei, deren Pfad NICHT (mehr) erlaubt
    ist, wird uebergangen – sie kann nur von Hand hineingelegt worden sein."""
    d = _o() / "quellen"
    raus = []
    with _sperre:
        if not d.is_dir():
            return raus
        for p in sorted(d.glob("*.json")):
            q = _json_lesen(p, None)
            if isinstance(q, dict) and _erlaubt(q.get("pfad", "")):
                raus.append(q)
    return raus


def quellen_index() -> dict[str, float]:
    """``{manifest: mtime}`` aller Quellen – fuer Abgleich und Bereinigen.

    ⚠ GECACHT, und zwar am STAND DES ORDNERS, nicht an einer Liste von
    Schreibstellen: der Nachlauf fragt je Schritt, und jede Frage las alle
    Quelldateien (ECHT 2026-11-09: 13.247 Dateien, 1,1 s CPU je Schritt).
    Jede Aenderung einer Quelle laeuft ueber ``os.replace`` bzw. Anlegen/
    Loeschen und aendert damit die mtime des Ordners – auch die eines fremden
    Prozesses; ein ausgetauschter Ordner (Uebernahme) hat eine andere Inode.
    Die Zeitstempel des Dateisystems sind grob (ext4: ein Kernel-Takt), zwei
    Aenderungen im selben Takt waeren also nicht unterscheidbar: ein Ordner,
    der juenger als ``_INDEX_FRISCH_S`` ist, wird deshalb nie gecacht."""
    return _indizes()[0]


def inhalts_stand() -> dict[str, float]:
    """``{manifest: stand}`` – fuer den NACHLAUF (Widersprueche, Wiki). Gleicher
    Cache wie ``quellen_index``. Eine nur bestaetigte Quelle (neue mtime, Text
    gleich) aendert hier nichts – sonst pruefte der Nachlauf jeden ihrer
    Begriffe erneut, ohne dass sich an den Abschnitten etwas geaendert hat."""
    return _indizes()[1]


def _indizes() -> tuple[dict, dict]:
    """``(quellen_index, inhalts_stand)`` aus EINEM Lesen der Quellen, gecacht
    am Ordnerstand (siehe ``quellen_index``). Gibt immer Kopien heraus."""
    global _index_cache
    d = _o() / "quellen"
    with _sperre:
        try:
            s = d.stat()
        except OSError:
            return {}, {}
        schluessel = (str(d), s.st_ino, s.st_mtime_ns)
        if _index_cache is not None and _index_cache[0] == schluessel:
            return dict(_index_cache[1]), dict(_index_cache[2])
        alle = quellen_alle()
        idx = {q["pfad"]: float(q.get("mtime") or 0) for q in alle}
        stand = {q["pfad"]: stand_von(q) for q in alle}
        _index_cache = (schluessel, idx, stand) if time.time() - s.st_mtime > _INDEX_FRISCH_S else None
        return dict(idx), dict(stand)


def _entfernen_einzeln(m: str) -> bool:
    p = _quell_datei(m)
    if p.exists():
        p.unlink()
        return True
    return False


def quellen_entfernen(pfade) -> int:
    """Quellen entfernen (Pendant zu ``VectorStore.remove_files``)."""
    n = 0
    with _sperre:
        for pf in pfade or []:
            m = manifest_form(pf)
            if not _erlaubt(m):
                continue
            if _entfernen_einzeln(m):
                n += 1
            _queue_austragen(m)
            _unlesbar_austragen(m)
        if n:
            _veraltet_markieren()
        _queue_sichern()
    return n


def _praefix(pfad) -> str:
    return manifest_form(pfad).rstrip("/") + "/"


def praefix_entfernen(prefix) -> int:
    """Alle Quellen unterhalb eines Ordners (``remove_path_prefix``)."""
    pref = _praefix(prefix)
    with _sperre:
        weg = [q["pfad"] for q in quellen_alle() if q["pfad"].startswith(pref)]
        weg += [m for m in list(_queue().keys()) if m.startswith(pref)]
    return quellen_entfernen(weg)


def umbenennen(alt, neu) -> int:
    """Nur Metadaten umschreiben – KEINE neue Extraktion.

    Der Inhalt aendert sich beim Verschieben nicht, nur seine Adresse; der
    Vektorindex behaelt seine mtime (``Path.rename``), also bleibt auch das
    Extraktionsergebnis gueltig. Ziel ausserhalb des Graphen → entfernen.
    """
    a, n = manifest_form(alt), manifest_form(neu)
    if a == n or not _erlaubt(a):
        return 0
    with _sperre:
        if not _erlaubt(n):
            return quellen_entfernen([a])
        q = _json_lesen(_quell_datei(a), None)
        geaendert = 0
        if isinstance(q, dict) and q.get("pfad") == a:
            q["pfad"] = n
            _json_schreiben(_quell_datei(n), q)
            _entfernen_einzeln(a)
            geaendert = 1
            _nebenablagen_umschreiben(a, n)
            _veraltet_markieren()
        wq = _queue()
        if a in wq:
            wq[n] = wq.pop(a)
            _queue_sichern()
        ul = _unlesbar()
        if a in ul:
            ul[n] = ul.pop(a)
            _json_schreiben(_o() / "unlesbar.json", ul)
        return geaendert


def praefix_umbenennen(alt_prefix, neu_prefix) -> int:
    """Ordner umbenannt (``rename_path_prefix``) – nur Metadaten."""
    a, n = _praefix(alt_prefix), _praefix(neu_prefix)
    if a == n:
        return 0
    with _sperre:
        betroffen = {q["pfad"] for q in quellen_alle() if q["pfad"].startswith(a)}
        betroffen |= {m for m in _queue() if m.startswith(a)}
        betroffen |= {m for m in _unlesbar() if m.startswith(a)}
        return sum(umbenennen(m, n + m[len(a):]) for m in sorted(betroffen))


# ─── Pflege-Hooks (vom VectorStore gerufen, absolute Pfade) ─────────────────

def pflege_entfernt(pfade) -> int:
    return quellen_entfernen([p for p in (pfade or []) if ist_graph_pfad(p)])


def pflege_praefix_entfernt(prefix) -> int:
    return praefix_entfernen(prefix) if ist_graph_pfad(str(prefix).rstrip("/") + "/x") else 0


def pflege_umbenannt(alt, neu) -> int:
    return umbenennen(alt, neu)


def pflege_praefix_umbenannt(alt, neu) -> int:
    return praefix_umbenennen(alt, neu)


# ─── Warteschlange ──────────────────────────────────────────────────────────

def _queue() -> dict:
    """``{manifest: {mtime, versuche, seit, fehler}}`` – im Speicher gehalten,
    beim ersten Zugriff von Platte geladen (uebersteht einen Neustart)."""
    global _queue_cache
    if _queue_cache is None:
        roh = _json_lesen(_o() / "queue.json", {})
        _queue_cache = {m: e for m, e in (roh.get("eintraege") or {}).items()
                        if _erlaubt(m) and isinstance(e, dict)} if isinstance(roh, dict) else {}
    return _queue_cache


def _queue_sichern() -> None:
    if _queue_cache is not None:
        _json_schreiben(_o() / "queue.json", {"eintraege": _queue_cache})


def _queue_austragen(m: str) -> None:
    _queue().pop(m, None)


def einreihen(pfad, mtime: float, sichern: bool = True, voll: bool = False) -> bool:
    """Datei zur Extraktion vormerken. Nicht erlaubte Pfade: False, nichts geschieht.

    ``voll``: auch bei unveraendertem Eingabetext extrahieren (Neuaufbau mit
    "voll" – der Administrator will genau das, etwa nach einem Modellwechsel)."""
    m = manifest_form(pfad)
    if not _erlaubt(m):
        return False
    with _sperre:
        wq = _queue()
        alt = wq.get(m)
        if alt and float(alt.get("mtime") or 0) == float(mtime):
            if voll and not alt.get("voll"):
                alt["voll"] = True
                if sichern:
                    _queue_sichern()
            return True
        wq[m] = {"mtime": float(mtime), "versuche": 0, "seit": time.time(), "fehler": ""}
        if voll:
            wq[m]["voll"] = True
        if sichern:
            _queue_sichern()
    return True


def warteschlange_sichern() -> None:
    with _sperre:
        _queue_sichern()


def warteschlange() -> list[tuple[str, dict]]:
    """Eintraege, aelteste zuerst."""
    with _sperre:
        return sorted(((m, dict(e)) for m, e in _queue().items()),
                      key=lambda x: (x[1].get("seit") or 0, x[0]))


def warteschlange_laenge() -> int:
    with _sperre:
        return len(_queue())


def warteschlange_leeren() -> int:
    with _sperre:
        n = len(_queue())
        _queue().clear()
        _queue_sichern()
    return n


def erledigt(m: str, mtime: float) -> None:
    """Eintrag austragen – aber nur, wenn er nicht inzwischen NEUER eingereiht
    wurde (die Datei hat sich waehrend der Extraktion geaendert)."""
    with _sperre:
        e = _queue().get(m)
        if e and float(e.get("mtime") or 0) == float(mtime):
            _queue().pop(m, None)
            _queue_sichern()


def fehlversuch(m: str, mtime: float, grund: str, max_versuche: int) -> bool:
    """Einen Fehlversuch zaehlen. True = endgueltig aufgegeben (Negativ-Cache)."""
    with _sperre:
        e = _queue().get(m)
        if not e or float(e.get("mtime") or 0) != float(mtime):
            return False
        e["versuche"] = int(e.get("versuche") or 0) + 1
        e["fehler"] = str(grund)[:300]
        # ans Ende der Schlange, damit eine kaputte Datei die anderen nicht blockiert
        e["seit"] = time.time()
        aufgegeben = e["versuche"] >= max_versuche
        if aufgegeben:
            _queue().pop(m, None)
            ul = _unlesbar()
            ul[m] = {"mtime": float(mtime), "grund": str(grund)[:300], "zeit": time.time()}
            _json_schreiben(_o() / "unlesbar.json", ul)
        _queue_sichern()
        return aufgegeben


# ─── Negativ-Cache ──────────────────────────────────────────────────────────

def _unlesbar() -> dict:
    d = _json_lesen(_o() / "unlesbar.json", {})
    return d if isinstance(d, dict) else {}


def unlesbar_trifft(m: str, mtime: float) -> bool:
    e = _unlesbar().get(m)
    return bool(e) and float(e.get("mtime") or -1) == float(mtime)


def _unlesbar_austragen(m: str) -> None:
    ul = _unlesbar()
    if m in ul:
        ul.pop(m)
        _json_schreiben(_o() / "unlesbar.json", ul)


# ─── Admin-Entscheidungen ───────────────────────────────────────────────────

def aliasse() -> dict:
    """``{"zusammen": {normform: ziel_normform}, "geloescht": [normform]}``.

    Ueberstehen jeden Neuaufbau, weil ``graph.json`` nur ein Cache ist und die
    Ableitung diese Datei jedes Mal anwendet.
    """
    d = _json_lesen(_o() / "aliasse.json", {})
    if not isinstance(d, dict):
        d = {}
    return {"zusammen": dict(d.get("zusammen") or {}),
            "geloescht": list(d.get("geloescht") or [])}


def _aufloesen(n: str, zusammen: dict) -> str:
    """Normform ueber die Zusammenfuehrungen auf ihr Ziel abbilden (Ketten,
    aber kein Kreis: hoechstens 10 Schritte)."""
    for _ in range(10):
        z = zusammen.get(n)
        if not z or z == n:
            return n
        n = z
    return n


# ─── Ableitung ──────────────────────────────────────────────────────────────

def ableiten(quellen: list[dict] | None = None) -> dict:
    """Den zusammengefuehrten Graphen aus den Quellen bauen.

    * Knoten je Normform (nach Admin-Zusammenfuehrungen), Name = haeufigste
      Schreibweise, Typ = Mehrheit, alle Schreibweisen als Aliasse.
    * Kante je (von, nach, art); ``gewicht`` = Zahl der BELEGENDEN Quellen.
      Messbericht 3.2: die Kantenstabilitaet einer Einzelextraktion lag bei
      0,09 – eine Kante traegt erst, wenn mehrere Quellen sie belegen.
    * Je Quelle ein Dokumentknoten (Typ ``quelle``) und je erwaehnter Entitaet
      eine Kante ``erwaehnt_in``: das ist das Signal Quellen-Ueberlappung.
    """
    if quellen is None:
        quellen = quellen_alle()
    al = aliasse()
    zusammen, geloescht = al["zusammen"], set(al["geloescht"])
    knoten: dict[str, dict] = {}
    kanten: dict[tuple, dict] = {}

    def nid_von(name: str) -> str | None:
        n = norm_name(name)
        if not n:
            return None
        n = _aufloesen(n, zusammen)
        return None if n in geloescht else "e:" + n

    def kante(von, nach, art, quelle):
        k = (von, nach, art)
        e = kanten.setdefault(k, {"von": von, "nach": nach, "art": art, "sources": set()})
        e["sources"].add(quelle)

    for q in quellen:
        src = q["pfad"]
        qid = "q:" + src
        knoten[qid] = {"id": qid, "name": src.rsplit("/", 1)[-1], "typ": TYP_QUELLE,
                       "_namen": Counter(), "_typen": Counter(), "aliasse": set(),
                       "zusammenfassung": "", "sources": {src}}
        lokal: dict[str, str] = {}
        for e in q.get("entitaeten") or []:
            nid = nid_von(e.get("name", ""))
            if not nid:
                continue
            lokal[e.get("name", "")] = nid
            k = knoten.setdefault(nid, {"id": nid, "name": "", "typ": "", "_namen": Counter(),
                                        "_typen": Counter(), "aliasse": set(),
                                        "zusammenfassung": "", "sources": set()})
            k["_namen"][e["name"]] += 1
            if e.get("typ") in TYPEN:
                k["_typen"][e["typ"]] += 1
            k["aliasse"].add(e["name"])
            k["sources"].add(src)
            b = str(e.get("beschreibung") or "")
            if len(b) > len(k["zusammenfassung"]):
                k["zusammenfassung"] = b[:300]
            kante(nid, qid, KANTE_ERWAEHNT, src)
        for r in q.get("relationen") or []:
            von = lokal.get(r.get("von")) or nid_von(r.get("von", ""))
            nach = lokal.get(r.get("nach")) or nid_von(r.get("nach", ""))
            if not von or not nach or von == nach:
                continue
            if von not in knoten or nach not in knoten:
                continue
            kante(von, nach, norm_art(r.get("art") or ""), src)

    # Widersprueche (Phase 6): Kante zwischen den beiden DOKUMENTknoten, nur
    # solange beide Quellen mit der gepruften mtime im Graphen stehen.
    stand = {q["pfad"]: stand_von(q) for q in quellen}
    for b in _widersprueche_gueltig(stand):
        qa, qb = "q:" + b["a"], "q:" + b["b"]
        if qa in knoten and qb in knoten:
            von, nach = sorted((qa, qb))
            kante(von, nach, KANTE_WIDERSPRUCH, b["a"])
            kante(von, nach, KANTE_WIDERSPRUCH, b["b"])

    grad = Counter()
    for (von, nach, _), _e in kanten.items():
        grad[von] += 1
        grad[nach] += 1
    k_liste = []
    for nid, k in knoten.items():
        if k["typ"] != TYP_QUELLE:
            k["name"] = k["_namen"].most_common(1)[0][0] if k["_namen"] else nid[2:]
            k["typ"] = k["_typen"].most_common(1)[0][0] if k["_typen"] else "konzept"
        k_liste.append({"id": nid, "name": k["name"], "typ": k["typ"],
                        "aliasse": sorted(k["aliasse"] - {k["name"]}),
                        "zusammenfassung": k["zusammenfassung"],
                        "sources": sorted(k["sources"]), "grad": grad[nid]})
    e_liste = [{"von": e["von"], "nach": e["nach"], "art": e["art"],
                "gewicht": len(e["sources"]), "sources": sorted(e["sources"])}
               for e in kanten.values()]
    k_liste.sort(key=lambda k: k["id"])
    e_liste.sort(key=lambda e: (e["von"], e["nach"], e["art"]))
    return {"version": 1, "erzeugt": time.time(), "quellen": len(quellen),
            "knoten": k_liste, "kanten": e_liste}


def graph() -> dict:
    """Der aktuelle Graph – neu abgeleitet, wenn sich Quellen geaendert haben."""
    global _graph_cache, _graph_veraltet
    with _sperre:
        if _graph_cache is None or _graph_veraltet:
            _graph_veraltet = False
            _graph_cache = ableiten()
            try:
                _json_schreiben(_o() / "graph.json", _graph_cache)
            except Exception as e:  # noqa: BLE001 – nur ein Cache
                print(f"[Wissensgraph] graph.json nicht geschrieben: {e}", flush=True)
        return _graph_cache


_teil_cache: dict = {}


def teilgraph(erlaubt=None) -> dict:
    """Der Graph, wie er AUS DEN ERLAUBTEN DOKUMENTEN ALLEIN entstuende.

    Fuer Gruppen-Editoren (Rechte 2026-10-31: jeder Wissenseditor sieht seine
    Gruppen, globale Wissenseditoren alles). ⚠ BEWUSST NEU ABGELEITET statt
    aus dem Gesamtgraphen gefiltert: Name (haeufigste Schreibweise), Art,
    Beschreibung, Kanten und ihre Belegzahl, Widerspruchskanten – alles stammt
    dann nur aus erlaubten Quellen. Ein Filter am fertigen Graphen haette die
    Beschreibung aus einem FREMDEN Dokument stehen lassen (sie ist die laengste
    aller Quellen). ``erlaubt=None`` = alles (globaler Editor).
    """
    g = graph()
    if erlaubt is None:
        return g
    erl = {manifest_form(p) for p in erlaubt}
    marke = hashlib.sha256("\n".join(sorted(erl)).encode("utf-8")).hexdigest()
    with _sperre:
        hit = _teil_cache.get(marke)
        if hit and hit[0] == g["erzeugt"]:
            return hit[1]
    t = ableiten([q for q in quellen_alle() if q["pfad"] in erl])
    with _sperre:
        if len(_teil_cache) > 16:
            _teil_cache.clear()
        _teil_cache[marke] = (g["erzeugt"], t)
    return t


def kennzahlen() -> dict:
    g = graph()
    ent = [k for k in g["knoten"] if k["typ"] != TYP_QUELLE]
    begriffs_kanten = [e for e in g["kanten"] if e["art"] not in (KANTE_ERWAEHNT, KANTE_WIDERSPRUCH)]
    return {"quellen": g["quellen"], "entitaeten": len(ent),
            "kanten": len(begriffs_kanten),
            "kanten_mehrfach_belegt": sum(1 for e in begriffs_kanten if e["gewicht"] > 1),
            "widersprueche": sum(1 for e in g["kanten"] if e["art"] == KANTE_WIDERSPRUCH)}


def bekannte_namen(limit: int = 5000) -> list[str]:
    """Namen der Entitaeten, nach Grad absteigend – Kandidaten fuer die Normierung."""
    g = graph()
    ent = [k for k in g["knoten"] if k["typ"] != TYP_QUELLE]
    ent.sort(key=lambda k: -k["grad"])
    return [k["name"] for k in ent[:limit]]


# ─── Ansicht fuer die Admin-Kachel ──────────────────────────────────────────

def _im_ordner(sources, pref: str) -> bool:
    return any(q.startswith(pref) for q in sources)


def ansicht(q: str = "", typ: str = "", ordner: str = "", gruppe: str = "",
            dokumente: bool = True, limit: int = 2000, offset: int = 0, g: dict | None = None) -> dict:
    """Teilgraph fuer die Grafik: gefiltert, nach Grad sortiert, paginiert.

    * ``q``: Treffer in Name/Aliassen (Normform) **plus ihre Nachbarn** – ein
      Treffer ohne Umgebung sagte in einer Graphansicht nichts.
    * ``ordner``/``gruppe``: ein Knoten bleibt, wenn MINDESTENS EINE seiner
      Quellen im Umfang liegt (Wissensgruppen ueber ``filter_paths_by_groups``,
      dieselbe Regel wie die Suche).
    * Kanten nur zwischen ausgelieferten Knoten – sonst zeigte die Grafik
      Kanten ins Leere.
    * ``g``: ein Teilgraph (``teilgraph``) statt des ganzen.
    """
    g = g or graph()
    knoten = g["knoten"]
    if not dokumente:
        knoten = [k for k in knoten if k["typ"] != TYP_QUELLE]
    if typ:
        knoten = [k for k in knoten if k["typ"] == typ or (dokumente and k["typ"] == TYP_QUELLE)]
    if ordner:
        pref = manifest_form(ordner).rstrip("/") + "/"
        knoten = [k for k in knoten if _im_ordner(k["sources"], pref)]
    if gruppe:
        from backend import knowledge_groups as kg
        alle = sorted({s for k in knoten for s in k["sources"]})
        erlaubt = set(kg.filter_paths_by_groups(alle, [gruppe]))
        knoten = [k for k in knoten if erlaubt.intersection(k["sources"])]
    if q:
        nq = norm_name(q)
        treffer = {k["id"] for k in knoten
                   if nq and (nq in norm_name(k["name"])
                              or any(nq in norm_name(a) for a in k["aliasse"]))}
        nachbarn = set()
        for e in g["kanten"]:
            if e["von"] in treffer:
                nachbarn.add(e["nach"])
            if e["nach"] in treffer:
                nachbarn.add(e["von"])
        knoten = [k for k in knoten if k["id"] in treffer | nachbarn]
    else:
        treffer = set()
    knoten = sorted(knoten, key=lambda k: (-k["grad"], k["id"]))
    gefiltert = len(knoten)
    limit = max(1, min(int(limit), 20000))
    offset = max(0, int(offset))
    seite = knoten[offset:offset + limit]
    ids = {k["id"] for k in seite}
    kanten = [e for e in g["kanten"] if e["von"] in ids and e["nach"] in ids]
    return {"knoten": seite, "kanten": kanten, "treffer": sorted(treffer & ids),
            "gesamt": len(g["knoten"]), "gefiltert": gefiltert,
            "offset": offset, "limit": limit, "erzeugt": g["erzeugt"]}


def knoten_detail(kid: str, g: dict | None = None) -> dict | None:
    g = g or graph()
    k = next((x for x in g["knoten"] if x["id"] == kid), None)
    if k is None:
        return None
    namen = {x["id"]: (x["name"], x["typ"]) for x in g["knoten"]}

    def zeile(e, anderer):
        n, t = namen.get(anderer, (anderer, ""))
        return {"id": anderer, "name": n, "typ": t, "art": e["art"],
                "gewicht": e["gewicht"], "sources": e["sources"]}
    aus = [zeile(e, e["nach"]) for e in g["kanten"] if e["von"] == kid]
    ein = [zeile(e, e["von"]) for e in g["kanten"] if e["nach"] == kid]
    return {**k, "ausgehend": aus, "eingehend": ein}


# ─── Relevanzmodell (Phase 3: Graph-erweiterte Suche) ──────────────────────

# Ein Begriff in mehr als diesem Anteil aller Dokumente verbindet nichts – er
# verbaende jedes Dokument mit jedem. Messbericht Meilenstein 2: ohne Dämpfung
# waren "Confluence" (98 von 236) und der Bereichsname die groessten Knoten.
HUB_ANTEIL = 0.2

# Fuellwoerter der Frage, in der Normform von ``norm_name`` (Umlaute als ae/oe/ue).
_FUELLWOERTER = frozenset("""
und oder aber der die das den dem des ein eine einen einem einer eines ist sind war
wird werden wurde wie was wer wo welche welcher welches welchen wann warum wozu
fuer mit von bei auf aus nach im in zu zum zur an am als auch kann koennen muss
muessen soll sollte sollen man ich wir sie es bzw gibt dabei dass ob ueber unter
durch nicht kein keine hat haben gilt mein meine unser unsere ihr ihre dies diese
dieser dieses gibt es noch schon nur mehr sich so the of and for to
""".split())

_rel_cache: dict = {}


def _relevanz_index() -> dict:
    """Dokument→Begriffe, Begriff→Dokumente, Typ, Nachbarschaft (mit Belegen),
    Woerter je Begriffsname.
    Gebaut aus dem abgeleiteten Graphen und mit ihm erneuert."""
    g = graph()
    if _rel_cache.get("erzeugt") == g["erzeugt"]:
        return _rel_cache
    doc_ents: dict[str, set] = {}
    ent_docs: dict[str, set] = {}
    typ: dict[str, str] = {}
    for k in g["knoten"]:
        if k["typ"] == TYP_QUELLE:
            continue
        typ[k["id"]] = k["typ"]
        ent_docs[k["id"]] = set(k["sources"])
        for d in k["sources"]:
            doc_ents.setdefault(d, set()).add(k["id"])
    adj: dict[str, list] = {}
    for e in g["kanten"]:
        if e["art"] == KANTE_ERWAEHNT:
            continue
        adj.setdefault(e["von"], []).append((e["nach"], e["gewicht"], e["sources"]))
        adj.setdefault(e["nach"], []).append((e["von"], e["gewicht"], e["sources"]))
    namen = {k["id"]: tuple(_wortliste(k["name"])) for k in g["knoten"] if k["typ"] != TYP_QUELLE}
    _rel_cache.clear()
    _rel_cache.update(erzeugt=g["erzeugt"], doc_ents=doc_ents, ent_docs=ent_docs,
                      typ=typ, adj=adj, n_docs=max(1, g["quellen"]),
                      namen={e: w for e, w in namen.items() if w})
    return _rel_cache


def _wortliste(text: str) -> list[str]:
    return [w for w in norm_name(text).split() if w not in _FUELLWOERTER]


def _wort_passt(w: str, frage: set) -> bool:
    """Ein Wort des Begriffsnamens steht in der Frage – woertlich oder als
    Beugungsform mit gleichem Anfang ("rechnung"/"rechnungen", "freigabe"/
    "freigaben"; erst ab fuenf Buchstaben, sonst traefe "sap" auch "sapient")."""
    if w in frage:
        return True
    # Fuenf gleiche Anfangsbuchstaben schliessen kurze Woerter von selbst aus.
    return any(len(q) >= 5 and q[:5] == w[:5] and (q.startswith(w) or w.startswith(q))
               and abs(len(q) - len(w)) <= 3 for q in frage)


def frage_begriffe(frage: str, erlaubt=None, hub_anteil: float = HUB_ANTEIL) -> list[str]:
    """Begriffe des Graphen, deren Name VOLLSTAENDIG in der Frage steht (jedes
    Wort, Beugung toleriert) – ohne Hubs und nur mit erlaubtem Beleg."""
    idx = _relevanz_index()
    erl = None if erlaubt is None else {manifest_form(p) for p in erlaubt}
    grenze = max(3, hub_anteil * idx["n_docs"])
    w = set(_wortliste(frage))
    if not w:
        return []
    raus = []
    for e, worte in idx["namen"].items():
        if not all(_wort_passt(x, w) for x in worte):
            continue
        n = sum(1 for d in idx["ent_docs"].get(e, ()) if erl is None or d in erl)
        if 0 < n <= grenze:
            raus.append(e)
    return sorted(raus)


def relevanz(frage: str, start_pfade=(), erlaubt=None, max_dokumente: int = 20,
             hub_anteil: float = HUB_ANTEIL) -> list[tuple[str, float, dict]]:
    """Dokumente, die die Begriffe der FRAGE tragen – ``[(manifest, score,
    {"begriffe": [...]})]``, beste zuerst, ohne die Startdokumente (die
    vorlaeufig besten Treffer der Suche).

    Score = Summe der Seltenheit ``ln(1 + N/df)`` der getroffenen Begriffe:
    ein Begriff aus zwei Dokumenten zaehlt viel, einer aus vierzig wenig.

    Gemessen (docs/wissensgraph-meilenstein5.md): das Vorgaengermodell aus dem
    Plan – vier Signale Dokument zu Dokument, 2-Hop-Expansion – kannte die Frage
    nicht und brachte bei Zusammenhangsfragen einen VERLUST. Der Schritt ueber
    Kanten (Nachbarn der Fragebegriffe, Gewicht 0,25/0,5) senkte das Ergebnis
    ebenfalls; er ist deshalb nicht enthalten. Die Startdokumente erneut zu
    staerken, schob bei Ein-Dokument-Fragen den richtigen Treffer von Platz 1.

    ⚠ FILTER IN DER ABFRAGE: mit ``erlaubt`` zaehlen NUR erlaubte Dokumente –
    als Kandidat und in der Seltenheit (df). Ohne LLM, rein im Speicher.
    """
    import math
    idx = _relevanz_index()
    erl = None if erlaubt is None else {manifest_form(p) for p in erlaubt}
    starts = {manifest_form(p) for p in (start_pfade or [])}
    n = idx["n_docs"] if erl is None else max(1, len(erl & set(idx["doc_ents"])))
    punkte: dict[str, float] = {}
    treffer: dict[str, list] = {}
    for e in frage_begriffe(frage, erl, hub_anteil):
        docs = [d for d in idx["ent_docs"].get(e, ()) if erl is None or d in erl]
        gewicht = math.log(1 + n / len(docs))
        for d in docs:
            if d in starts:
                continue
            punkte[d] = punkte.get(d, 0.0) + gewicht
            treffer.setdefault(d, []).append(e)
    raus = [(d, round(s, 4), {"begriffe": sorted(treffer[d])}) for d, s in punkte.items()]
    raus.sort(key=lambda x: (-x[1], x[0]))
    return raus[:max(1, int(max_dokumente))]


def zusammenhaenge(pfade, erlaubt=None, maximal: int = 5) -> list[str]:
    """Kurze Zeilen "X ↔ Y (über Dokument Z)" fuer die Trefferdokumente einer
    Suche – nur Kanten zwischen Begriffen dieser Dokumente, belegt durch ein
    ERLAUBTES Dokument, staerkste zuerst. Hubs bleiben aussen vor."""
    idx = _relevanz_index()
    erl = None if erlaubt is None else {manifest_form(p) for p in erlaubt}
    docs = [manifest_form(p) for p in (pfade or [])]
    docs = [d for d in docs if d in idx["doc_ents"] and (erl is None or d in erl)]
    grenze = max(3, HUB_ANTEIL * idx["n_docs"])
    ents = {e for d in docs for e in idx["doc_ents"][d]
            if len(idx["ent_docs"].get(e, ())) <= grenze}
    g = graph()
    namen = {k["id"]: k["name"] for k in g["knoten"]}
    zeilen = []
    for e in sorted(g["kanten"], key=lambda x: (-x["gewicht"], x["von"], x["nach"])):
        if e["art"] == KANTE_ERWAEHNT or e["von"] not in ents or e["nach"] not in ents:
            continue
        belege = [b for b in e["sources"] if erl is None or b in erl]
        if not belege:
            continue
        zeilen.append(f"{namen.get(e['von'], e['von'])} ↔ {namen.get(e['nach'], e['nach'])} "
                      f"({e['art'].replace('_', ' ')}, über {belege[0].rsplit('/', 1)[-1]})")
        if len(zeilen) >= maximal:
            break
    return zeilen


# ─── Admin-Entscheidungen: zusammenfuehren, trennen, loeschen ───────────────

def _aliasse_schreiben(d: dict) -> None:
    _json_schreiben(_o() / "aliasse.json", d)
    _veraltet_markieren()


def _roh_aliasse() -> dict:
    d = _json_lesen(_o() / "aliasse.json", {})
    d = d if isinstance(d, dict) else {}
    return {"zusammen": dict(d.get("zusammen") or {}),
            "geloescht": list(d.get("geloescht") or []),
            "getrennt": [list(p) for p in (d.get("getrennt") or []) if isinstance(p, list) and len(p) == 2]}


def _norm_aus_id(kid: str) -> str:
    if not isinstance(kid, str) or not kid.startswith("e:") or len(kid) < 3:
        raise ValueError("Nur Entitaeten (keine Dokumente) koennen bearbeitet werden")
    return kid[2:]


def zusammenfuehren(quelle_id: str, ziel_id: str) -> dict:
    """``quelle`` geht in ``ziel`` auf. Ueberlebt jeden Neuaufbau (aliasse.json);
    ein Kreis (Ziel zeigt schon auf die Quelle) wird abgewiesen."""
    a, b = _norm_aus_id(quelle_id), _norm_aus_id(ziel_id)
    if a == b:
        raise ValueError("Quelle und Ziel sind derselbe Knoten")
    with _sperre:
        d = _roh_aliasse()
        if _aufloesen(b, d["zusammen"]) == a:
            raise ValueError("Das Ziel ist bereits in die Quelle zusammengefuehrt")
        d["zusammen"][a] = b
        d["getrennt"] = [p for p in d["getrennt"] if sorted(p) != sorted([a, b])]
        _aliasse_schreiben(d)
    return {"ok": True, "quelle": quelle_id, "ziel": "e:" + _aufloesen(b, d["zusammen"])}


def trennen(a_id: str, b_id: str) -> dict:
    """Zwei Knoten bleiben getrennt: eine Zusammenfuehrung zwischen ihnen wird
    zurueckgenommen, und das Paar erscheint nicht wieder in der Pruefliste."""
    a, b = _norm_aus_id(a_id), _norm_aus_id(b_id)
    if a == b:
        raise ValueError("Ein Knoten kann nicht von sich selbst getrennt werden")
    with _sperre:
        d = _roh_aliasse()
        zurueck = [x for x in (a, b) if d["zusammen"].get(x) in (a, b)]
        for x in zurueck:
            d["zusammen"].pop(x, None)
        if sorted([a, b]) not in [sorted(p) for p in d["getrennt"]]:
            d["getrennt"].append(sorted([a, b]))
        _aliasse_schreiben(d)
    return {"ok": True, "zurueckgenommen": len(zurueck)}


def knoten_loeschen(kid: str) -> dict:
    """Entitaet ausblenden – bleibt ueber jeden Neuaufbau geloescht (die Quellen
    selbst bleiben unangetastet; ein Dokument loescht man, indem man die Datei loescht)."""
    a = _norm_aus_id(kid)
    with _sperre:
        d = _roh_aliasse()
        if a not in d["geloescht"]:
            d["geloescht"].append(a)
        _aliasse_schreiben(d)
    return {"ok": True}


PRUEF_SCHWELLE = 0.88      # Messbericht 3.3: darunter ueberwiegend Rauschen
_vek_cache: dict = {}


def pruefliste(limit: int = 50, kodieren=None, schwelle: float = PRUEF_SCHWELLE) -> list[dict]:
    """Unsichere Zusammenfuehrungen: verschiedene Normform, e5-Kosinus ab der
    Schwelle. Messbericht 3.3: selbst ≥ 0,95 enthielt Fehlpaare – deshalb
    entscheidet hier ein Mensch, nie ein Automat. Bereits getrennte Paare
    erscheinen nicht wieder. Blockweise, damit ein grosser Graph nicht eine
    N×N-Matrix auf einmal braucht.

    ⚠ GEMESSEN (DEV, 7519 Begriffe, 2026-10-31): die Matrix allein kostet
    18,8 s, ueber der Schwelle liegen 390.699 Paare – die fruehere
    Python-Schleife ging jedes einzeln durch. Jetzt waehlt numpy je Block nur
    die besten ``limit + getrennte`` aus (die obere Dreieckshaelfte), mehr kann
    in die Liste nicht kommen. Die Laufzeit waechst quadratisch mit dem Graphen
    – die Seite holt die Liste deshalb ueber ``pruefliste_stand`` (Hintergrund,
    gepuffert).
    """
    import numpy as np
    g = graph()
    ent = [k for k in g["knoten"] if k["typ"] != TYP_QUELLE]
    if len(ent) < 2:
        return []
    if kodieren is None:
        from backend.tools.vector_store import _encode

        def kodieren(namen):
            return _encode(namen, prefix="query")
    neu = [k["name"] for k in ent if k["name"] not in _vek_cache]
    if neu:
        for nm, v in zip(neu, kodieren(neu)):
            _vek_cache[nm] = np.asarray(v, dtype="float32")
    V = np.stack([_vek_cache[k["name"]] for k in ent])
    n = len(ent)
    getrennt = {tuple(sorted(p)) for p in _roh_aliasse()["getrennt"]}
    bedarf = max(1, int(limit)) + len(getrennt)
    spalten = np.arange(n)
    ks, ki, kj = [], [], []
    for i0 in range(0, n, 500):
        S = V[i0:i0 + 500] @ V.T
        zeilen = np.arange(i0, min(i0 + 500, n))
        S = np.where(spalten[None, :] > zeilen[:, None], S, -2.0)   # nur j > i
        flach = S.ravel()
        k = min(bedarf, flach.size)
        wahl = np.argpartition(-flach, k - 1)[:k]
        wahl = wahl[flach[wahl] >= schwelle]
        ks.append(flach[wahl])
        ki.append(wahl // n + i0)
        kj.append(wahl % n)
    sc, ii, jj = np.concatenate(ks), np.concatenate(ki), np.concatenate(kj)
    # Feste Reihenfolge: Aehnlichkeit absteigend, dann Position (wie zuvor).
    reihe = np.lexsort((jj, ii, -sc))
    raus = []
    for o in reihe:
        a, b = ent[int(ii[o])], ent[int(jj[o])]
        if tuple(sorted([a["id"][2:], b["id"][2:]])) in getrennt:
            continue
        # Vorschlag: der Knoten mit weniger Quellen geht in den mit mehr auf.
        q, z = (a, b) if (len(a["sources"]), a["grad"]) < (len(b["sources"]), b["grad"]) else (b, a)
        raus.append({"aehnlichkeit": round(float(sc[o]), 3),
                     "quelle": {"id": q["id"], "name": q["name"], "typ": q["typ"], "quellen": len(q["sources"])},
                     "ziel": {"id": z["id"], "name": z["name"], "typ": z["typ"], "quellen": len(z["sources"])}})
        if len(raus) >= max(1, int(limit)):
            break
    return raus


# Vorrat fuer die Seite: so viele Paare werden je Berechnung gemerkt.
PRUEF_VORRAT = 200
_pruef: dict = {"erzeugt": None, "paare": [], "zeit": 0.0, "laeuft": False, "fehler": ""}
_pruef_sperre = threading.Lock()


def _pruef_rechnen() -> None:
    try:
        g = graph()
        paare = pruefliste(PRUEF_VORRAT)
        with _pruef_sperre:
            _pruef.update(erzeugt=g["erzeugt"], paare=paare, zeit=time.time(), fehler="")
    except Exception as e:  # noqa: BLE001 – die Seite meldet den Grund
        with _pruef_sperre:
            _pruef["fehler"] = f"{type(e).__name__}: {e}"
    finally:
        with _pruef_sperre:
            _pruef["laeuft"] = False


def pruefliste_stand(limit: int = 50, starten=None) -> dict:
    """Die Pruefliste fuer die Seite – SOFORT, nie nach einer Rechnung.

    * Passt der gemerkte Stand zum aktuellen Graphen: er.
    * Ist er veraltet (Graph seitdem gewachsen): er trotzdem, gekennzeichnet,
      und im Hintergrund wird neu gerechnet. Bereits ENTSCHIEDENES faellt dabei
      sofort heraus – ein Paar, dessen Begriff es nicht mehr gibt (zusammen-
      gefuehrt, geloescht) oder das getrennt wurde.
    * Gibt es noch keinen Stand: leer mit ``laeuft`` – die Seite fragt nach.
    Es rechnet hoechstens EIN Hintergrundlauf zugleich.
    ``starten`` ersetzt im Test den Thread-Start.
    """
    g = graph()
    ids = {k["id"] for k in g["knoten"]}
    getrennt = {tuple(sorted(p)) for p in _roh_aliasse()["getrennt"]}
    with _pruef_sperre:
        aktuell = _pruef["erzeugt"] == g["erzeugt"]
        anstossen = not aktuell and not _pruef["laeuft"]
        if anstossen:
            _pruef["laeuft"] = True
        paare = [p for p in _pruef["paare"]
                 if p["quelle"]["id"] in ids and p["ziel"]["id"] in ids
                 and tuple(sorted([p["quelle"]["id"][2:], p["ziel"]["id"][2:]])) not in getrennt]
        stand = {"paare": paare[:max(1, int(limit))], "zeit": _pruef["zeit"],
                 "veraltet": bool(_pruef["zeit"]) and not aktuell,
                 "laeuft": _pruef["laeuft"], "fehler": _pruef["fehler"]}
    if anstossen:
        (starten or (lambda f: threading.Thread(target=f, daemon=True, name="wg-pruefliste").start()))(_pruef_rechnen)
    return stand


# ─── Status ─────────────────────────────────────────────────────────────────

# ─── Phase 6: Ablagen fuer Widersprueche, Wiki-Seiten, Rueckmeldungen ───────

def widersprueche_lesen() -> dict:
    """``{"geprueft": {kid: {"quellen": {m: mtime}, "zeit", "fehler"?, "versuche"?}},
    "befunde": [{"id", "kid", "name", "a", "b", "mtime_a", "mtime_b",
    "aussage_a", "aussage_b", "erklaerung", "zeit"}]}``"""
    d = _json_lesen(_o() / "widersprueche.json", {})
    if not isinstance(d, dict):
        d = {}
    g = d.get("geprueft") if isinstance(d.get("geprueft"), dict) else {}
    b = d.get("befunde") if isinstance(d.get("befunde"), list) else []
    return {"geprueft": g, "befunde": [x for x in b if isinstance(x, dict)]}


def _widerspruch_kanten(befunde) -> set:
    """Was ``ableiten`` aus den Befunden liest: Dokumentpaar samt geprueften mtimes."""
    return {(b.get("a"), b.get("b"), b.get("mtime_a"), b.get("mtime_b"))
            for b in befunde or [] if isinstance(b, dict)}


def widersprueche_schreiben(d: dict, vorher_befunde: list | None = None) -> None:
    """Ablage schreiben; den Graphen nur dann neu ableiten, wenn sich seine
    Widerspruchskanten aendern. ⚠ Bis 2026-11-01 markierte JEDES Schreiben den
    Graphen als veraltet – der Nachlauf schreibt je geprueftem Begriff, und
    jeder Schritt leitete den ganzen Graphen neu ab (auf DEV 1,4 s plus 58 MB
    graph.json, 5.726-mal fuer 26 Befunde): ein Kern dauerhaft belegt, und die
    Pruefliste rechnete wegen des neuen Zeitstempels nie zu Ende.

    ``vorher_befunde``: die Befunde, wie sie GERADE auf Platte stehen – nur von
    einem Aufrufer, der die Ablage unter derselben ``_sperre`` eben gelesen hat
    (spart das zweite Parsen der 17 MB je Schritt). Ein falscher Wert liesse
    eine Kantenaenderung unbemerkt; ohne Angabe wird wie bisher gelesen."""
    with _sperre:
        if vorher_befunde is None:
            vorher_befunde = widersprueche_lesen()["befunde"]
        vorher = _widerspruch_kanten(vorher_befunde)
        _json_schreiben(_o() / "widersprueche.json", d)
        if _widerspruch_kanten(d.get("befunde")) != vorher:
            _veraltet_markieren()


def _widersprueche_gueltig(stand: dict) -> list[dict]:
    """Befunde, deren BEIDE Quellen mit der geprueften mtime noch im Graphen
    stehen. Hat sich eine Quelle geaendert oder ist sie weg, gilt der Befund
    nicht mehr – die Pruefung des Begriffs laeuft dann neu."""
    raus = []
    for b in widersprueche_lesen()["befunde"]:
        a, z = b.get("a"), b.get("b")
        if (a in stand and z in stand and stand[a] == float(b.get("mtime_a") or -1)
                and stand[z] == float(b.get("mtime_b") or -1)):
            raus.append(b)
    return raus


def widersprueche_gueltig() -> list[dict]:
    return _widersprueche_gueltig(inhalts_stand())


def wiki_index_lesen() -> dict:
    """``{kid: {"datei", "quellen": {m: mtime}, "erzeugt", "modell", "fehler"?, "versuche"?}}``"""
    d = _json_lesen(_o() / "wiki" / "index.json", {})
    return d if isinstance(d, dict) else {}


def wiki_index_schreiben(d: dict) -> None:
    with _sperre:
        _json_schreiben(_o() / "wiki" / "index.json", d)


def _nebenablagen_umschreiben(alt: str, neu: str) -> None:
    """Eine umbenannte Quelle auch in Widerspruechen und Wiki-Index umschreiben –
    sonst gaelten die Befunde nicht mehr und der Begriff liefe (mit
    Modellaufrufen) neu, obwohl sich am Inhalt nichts geaendert hat."""
    w = widersprueche_lesen()
    geaendert = False
    for b in w["befunde"]:
        for f in ("a", "b"):
            if b.get(f) == alt:
                b[f] = neu
                geaendert = True
    for g in w["geprueft"].values():
        q = g.get("quellen") if isinstance(g, dict) else None
        if isinstance(q, dict) and alt in q:
            q[neu] = q.pop(alt)
            geaendert = True
    if geaendert:
        _json_schreiben(_o() / "widersprueche.json", w)
    wi = wiki_index_lesen()
    geaendert = False
    for e in wi.values():
        q = e.get("quellen") if isinstance(e, dict) else None
        if isinstance(q, dict) and alt in q:
            q[neu] = q.pop(alt)
            geaendert = True
    if geaendert:
        _json_schreiben(_o() / "wiki" / "index.json", wi)


# Rueckkopplung aus der Kachel: eine verworfene Auffaelligkeit senkt kuenftig
# das Gewicht aehnlicher Vorschlaege (die Aehnlichkeit rechnet die Seite).
RUECKMELDUNG_ARTEN = ("v", "b", "d", "i", "w")
RUECKMELDUNG_MAX = 500


def _rueck_alle() -> dict:
    d = _json_lesen(_o() / "rueckmeldung.json", {})
    # Bis 2026-10-31 eine gemeinsame Liste (nur Admins sahen die Seite). Seit
    # Gruppen-Editoren eigene Ausschnitte sehen, gilt eine Rueckmeldung JE
    # BENUTZER – das Ausblenden eines Editors stufte sonst Hinweise in fremden
    # Gruppen zurueck. Eine alte Liste ist damit verworfen.
    return {k: v for k, v in d.items() if isinstance(v, list)} if isinstance(d, dict) else {}


def rueckmeldungen(benutzer: str) -> list[dict]:
    return [x for x in _rueck_alle().get(str(benutzer), []) if isinstance(x, dict)]


def rueckmeldung_pruefen(karte) -> dict:
    """Eingabe der Seite validieren – Fremdeingabe, also eng: feste Arten,
    begrenzte Laengen, nur Texte."""
    if not isinstance(karte, dict):
        raise ValueError("Karte muss ein Objekt sein")
    sch, art = karte.get("schluessel"), karte.get("art")
    if not isinstance(sch, str) or not 0 < len(sch) <= 400:
        raise ValueError("schluessel: Text bis 400 Zeichen")
    if art not in RUECKMELDUNG_ARTEN:
        raise ValueError("art: unbekannt")
    raus = {"schluessel": sch, "art": art}
    for feld, maximal in (("knoten", 50), ("typen", 10)):
        v = karte.get(feld, [])
        if not isinstance(v, list) or len(v) > maximal or not all(isinstance(x, str) and len(x) <= 400 for x in v):
            raise ValueError(f"{feld}: Liste von bis zu {maximal} Texten")
        raus[feld] = sorted(set(v))
    return raus


def rueckmeldung_verwerfen(benutzer: str, karte) -> list[dict]:
    k = rueckmeldung_pruefen(karte)
    with _sperre:
        alle = _rueck_alle()
        liste = [x for x in alle.get(str(benutzer), []) if x.get("schluessel") != k["schluessel"]]
        liste.append({**k, "zeit": time.time()})
        alle[str(benutzer)] = liste[-RUECKMELDUNG_MAX:]
        _json_schreiben(_o() / "rueckmeldung.json", alle)
    return alle[str(benutzer)]


def rueckmeldungen_zuruecksetzen(benutzer: str) -> int:
    with _sperre:
        alle = _rueck_alle()
        n = len(alle.pop(str(benutzer), []))
        _json_schreiben(_o() / "rueckmeldung.json", alle)
    return n


def status_lesen() -> dict:
    d = _json_lesen(_o() / "status.json", {})
    return d if isinstance(d, dict) else {}


def status_schreiben(d: dict) -> None:
    with _sperre:
        _json_schreiben(_o() / "status.json", d)


def _zuruecksetzen_fuer_test() -> None:
    """Speicher-Caches verwerfen (Tests lenken ``ORDNER`` um)."""
    global _graph_cache, _graph_veraltet, _queue_cache, _index_cache
    with _sperre:
        _graph_cache, _graph_veraltet, _queue_cache, _index_cache = None, True, None, None
        _vek_cache.clear()
        _pruef.update(erzeugt=None, paare=[], zeit=0.0, laeuft=False, fehler="")
