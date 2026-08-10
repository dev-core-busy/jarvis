"""Protokolliert LLM-Konversationen fuer den Verlauf-Tab – VOLLSTAENDIG.

ZWEI DATEIEN JE KONVERSATION – und warum
----------------------------------------
Bis 2026-08-04 lag alles in EINER Datei ``data/conv_log.json`` und jedes Feld
war beschnitten: Aufgabe auf 200 Zeichen, System-Prompt auf 500, jede Nachricht
auf 300. Auf DEV waren dadurch 19 von 200 Aufgaben abgeschnitten – der Verlauf
zeigte also bei jedem zehnten Eintrag *nicht*, was der Benutzer wirklich
gefragt hat. Fuer eine Fehlersuche ("warum hat das Modell so geantwortet?") ist
ein halber Prompt schlimmer als kein Prompt: man sucht den Fehler in der
Antwort, obwohl er in der abgeschnittenen Frage stand.

Das Beschneiden hatte allerdings einen Grund, und der bleibt gueltig: die Datei
wurde bei JEDER Konversation komplett gelesen und komplett neu geschrieben.
Mit vollstaendigen Inhalten (ein einzelnes Tool-Ergebnis erreichte auf DEV
1,28 MB) waere daraus ein Mehr-MB-Schreibvorgang pro Chat-Nachricht geworden.
Unbeschnitten *und* monolithisch geht also nicht.

Deshalb jetzt getrennt:

``data/logs/conv/index.jsonl``
    Eine Zeile je Konversation, nur Kopfdaten (Zeit, Benutzer, Modell, IP,
    Schritte, Dauer, Fehler, Nachrichtenzahl) und die **vollstaendige Aufgabe**.
    Wird nur ANGEHAENGT – das Schreiben kostet unabhaengig von der Historie
    immer gleich viel. Die Liste in der Oberflaeche kommt allein aus dieser
    Datei und bleibt damit schnell.

``data/logs/conv/<id>.json``
    Der vollstaendige Rumpf: System-Prompt und alle Nachrichten in voller
    Laenge. Wird EINMAL geschrieben und nur gelesen, wenn ein Eintrag in der
    Oberflaeche aufgeklappt wird.

WAS "VOLLSTAENDIG" HIER GARANTIERT
----------------------------------
* Die **Aufgabe** und alle Nachrichten der Rollen ``user``/``system`` sowie der
  **System-Prompt** werden NIE gekuerzt. Das ist die Zusage: der Prompt ist
  vollstaendig.
* Nachrichten anderer Rollen (Tool-Ergebnisse, Modell-Antworten) haben mit
  ``_MAX_MSG_CHARS`` (1 MB) eine Notbremse, der Rumpf insgesamt mit
  ``_MAX_BODY_CHARS`` (8 MB) eine zweite. Beide lagen auf DEV um Groessen-
  ordnungen ueber dem 99. Perzentil (25 KB) – sie greifen praktisch nie. Wenn
  doch, steht es AUSDRUECKLICH im Eintrag (``truncated`` + ``full_len``), damit
  niemand einen gekuerzten Text fuer den ganzen haelt. Genau diese Angabe fehlte
  der alten Fassung: dort war ein "…" am Ende der einzige Hinweis.

ALTERUNG IST DIE EINZIGE SCHRANKE (Vorgabe 2026-08-04)
------------------------------------------------------
Es gibt **keine** Stueckzahl-Begrenzung. Was entfernt wird, entscheidet
ausschliesslich ``prune_older_than()`` ueber das Alter (Zeitplan in
``backend/log_retention.py``, Vorgabe 90 Tage).

Eine zweite Schranke nach Stueckzahl war zunaechst eingebaut und ist bewusst
**wieder entfernt** worden: sie hebelt die Zusage aus. "Diagnosedaten werden 90
Tage vorgehalten" ist falsch, wenn ein Tag mit viel Verkehr die Eintraege von
vorgestern verdraengt – und zwar unsichtbar, genau dann, wenn man sie braucht.

Das hat eine Folge, die man kennen muss: **der Index kann beliebig lang werden.**
Deshalb liest ihn nichts mehr vollstaendig ein, wo es vermeidbar ist:
* ``_iter_index_reversed()`` liest die Datei **von hinten in Bloecken** und
  liefert die jueng<sten Zeilen zuerst. ``get_conversations(limit=…)`` bricht ab,
  sobald genug Treffer da sind – die Antwortzeit haengt damit an ``limit``, nicht
  an der Groesse der Historie.
* ``get_stats()`` zaehlt nur Zeilenumbrueche und liest die **erste und letzte**
  Zeile (O(1) statt O(n) JSON-Arbeit).
Vollstaendig gelesen wird der Index nur noch von ``get_known_ips/users()``
(Filter-Auswahllisten, manuelle Aktion) und beim Aufraeumen.
"""

import json
import os
import threading
import time
from pathlib import Path

_DATA_DIR  = Path(__file__).parent.parent / "data"
_CONV_DIR  = _DATA_DIR / "logs" / "conv"
_INDEX     = _CONV_DIR / "index.jsonl"
_OLD_FILE  = _DATA_DIR / "conv_log.json"        # Altbestand (vor 2026-08-04)

# KEINE Stueckzahl-Schranke – siehe Modul-Docstring. Nur Groessen-Notbremsen
# JE EINTRAG, damit eine einzelne Antwort nicht die Platte fuellt:
_MAX_MSG_CHARS  = 1_000_000   # Notbremse je Nachricht (nicht fuer Prompts)
_MAX_BODY_CHARS = 8_000_000   # Notbremse je Konversation

# Rollen, deren Inhalt unter KEINEN Umstaenden gekuerzt wird.
_NEVER_TRUNCATE = ("user", "system")

_lock = threading.Lock()
_migrated = False


# ─── Ablage ───────────────────────────────────────────────────────────────────

def _ensure_dir():
    _CONV_DIR.mkdir(parents=True, exist_ok=True)


def _body_path(conv_id: str) -> Path:
    """Pfad zum Rumpf. Die Id ist selbst erzeugt (Zeitstempel + Zaehler),
    wird aber trotzdem entschaerft – sie kommt bei ``get_body()`` aus der URL."""
    safe = "".join(c for c in str(conv_id) if c.isalnum() or c in "-_")[:64]
    return _CONV_DIR / f"{safe}.json"


def _read_index() -> list[dict]:
    """Liest den GANZEN Index (aelteste zuerst). Beschaedigte Zeilen werden
    uebersprungen – eine halb geschriebene Zeile darf nicht den ganzen
    Verlauf unlesbar machen.

    Nur fuer Aufraeumen/Migration und die Filter-Auswahllisten. Fuer die
    Anzeige ``_iter_index_reversed()`` benutzen: ohne Stueckzahl-Schranke
    kann diese Datei sehr lang werden.
    """
    if not _INDEX.exists():
        return []
    out = []
    for line in _INDEX.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return out


_TAIL_CHUNK = 256 * 1024


def _iter_index_reversed(chunk: int = _TAIL_CHUNK):
    """Liefert Index-Eintraege von der JUENGSTEN zur aeltesten Zeile.

    Liest die Datei blockweise von hinten. Damit kostet „zeige die letzten 100
    Konversationen" immer gleich viel, egal wie lang die Historie ist – die
    Voraussetzung dafuer, dass es ueberhaupt keine Stueckzahl-Schranke braucht.

    FALLSTRICK: Der erste Teil eines rueckwaerts gelesenen Blocks ist in der
    Regel eine ANGESCHNITTENE Zeile. Sie wird zurueckgehalten (``tail``) und
    erst mit dem naechsten – weiter vorne liegenden – Block zusammengesetzt.
    Wer das vergisst, verliert je Block eine Zeile bzw. bekommt Bruchstuecke.
    """
    if not _INDEX.exists():
        return
    with _INDEX.open("rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        tail = b""
        while pos > 0:
            step = min(chunk, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + tail
            parts = buf.split(b"\n")
            tail = parts[0]                 # unvollstaendig -> zurueckhalten
            for raw in reversed(parts[1:]):
                if not raw.strip():
                    continue
                try:
                    yield json.loads(raw.decode("utf-8", "replace"))
                except Exception:  # noqa: BLE001
                    continue
        if tail.strip():
            try:
                yield json.loads(tail.decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                pass


def _write_index(entries: list[dict]):
    """Schreibt den Index vollstaendig neu (nur beim Aufraeumen/Migrieren)."""
    _ensure_dir()
    tmp = _INDEX.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, _INDEX)     # atomar: kein halber Index nach einem Absturz


def _append_index(entry: dict):
    _ensure_dir()
    with _INDEX.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ─── Migration des Altbestands ────────────────────────────────────────────────

def _migrate_once():
    """Uebertraegt ``data/conv_log.json`` in die neue Ablage.

    Der Altbestand enthaelt nur die gekuerzten Vorschauen – mehr ist nicht
    rekonstruierbar. Die Raender werden deshalb mit ``legacy=True`` markiert:
    ein Eintrag von vorher darf nicht wie ein vollstaendiger aussehen.
    Die Quelldatei wird nach ``conv_log.json.migrated`` umbenannt, nicht
    geloescht – ein Fehler in dieser Funktion darf keine Daten kosten.
    """
    global _migrated
    if _migrated:
        return
    _migrated = True
    try:
        if not _OLD_FILE.exists():
            return
        old = json.loads(_OLD_FILE.read_text(encoding="utf-8"))
        if not isinstance(old, list):
            old = []
        _ensure_dir()
        index = _read_index()
        known = {e.get("id") for e in index}
        added = 0
        for e in old:
            cid = str(e.get("id") or "")
            if not cid or cid in known:
                continue
            msgs = e.get("messages") or []
            body = {
                "id": cid,
                "ts": e.get("ts"),
                "legacy": True,
                "system_prompt": e.get("system_prompt_preview") or "",
                "system_prompt_truncated": bool(e.get("system_prompt_preview")),
                "messages": [{
                    "role": m.get("role", "?"),
                    **({"tool": m["tool"]} if m.get("tool") else {}),
                    "content": m.get("preview") or m.get("content") or "",
                    "truncated": True,
                } for m in msgs],
            }
            try:
                _body_path(cid).write_text(json.dumps(body, ensure_ascii=False),
                                           encoding="utf-8")
            except Exception:  # noqa: BLE001
                continue
            index.append({
                "id": cid,
                "ts": e.get("ts") or 0,
                "task": e.get("task") or "",
                "task_truncated": True,
                "legacy": True,
                "model": e.get("model") or "",
                "username": e.get("username") or "",
                "client_ip": e.get("client_ip") or "unknown",
                "client_type": e.get("client_type") or "browser",
                "steps": e.get("steps") or 0,
                "duration_ms": e.get("duration_ms") or 0,
                "error": e.get("error"),
                "msg_count": len(msgs),
            })
            added += 1
        index.sort(key=lambda x: x.get("ts") or 0)
        _write_index(index)
        _OLD_FILE.rename(_OLD_FILE.with_suffix(".json.migrated"))
        print(f"[conv_log] {added} Alt-Eintraege uebernommen (gekuerzt markiert)",
              flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[conv_log] Migration fehlgeschlagen: {e}", flush=True)


# ─── Schreiben ────────────────────────────────────────────────────────────────

_seq = 0


def _new_id() -> str:
    """Millisekunden + Zaehler. Zwei Konversationen koennen in derselben
    Millisekunde enden (Parallelbetrieb); eine doppelte Id wuerde den Rumpf
    der einen mit dem der anderen ueberschreiben."""
    global _seq
    _seq = (_seq + 1) % 10000
    return f"{int(time.time() * 1000)}{_seq:04d}"


def _prepare_messages(messages: list[dict]) -> tuple[list[dict], int]:
    """Baut die Nachrichtenliste fuer den Rumpf.

    Rueckgabe: (Liste, Anzahl gekuerzter Nachrichten). Prompts (``user``/
    ``system``) bleiben immer unangetastet; das Restbudget des Rumpfes wird
    ausschliesslich zu Lasten der uebrigen Rollen verteilt.
    """
    out: list[dict] = []
    cut_count = 0
    budget = _MAX_BODY_CHARS
    # Prompts zuerst vom Budget abziehen – sie sind unkuerzbar und duerfen
    # nicht dadurch verloren gehen, dass ein Tool-Ergebnis vor ihnen das
    # Budget aufgebraucht hat.
    for m in messages:
        if (m.get("role") or "") in _NEVER_TRUNCATE:
            budget -= len(m.get("content") or "")
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content") or ""
        item: dict = {"role": role}
        if m.get("tool"):
            item["tool"] = m["tool"]
        if role in _NEVER_TRUNCATE:
            item["content"] = content          # unantastbar
        else:
            keep = min(len(content), _MAX_MSG_CHARS, max(budget, 0))
            if keep < len(content):
                item["content"] = content[:keep]
                item["truncated"] = True
                item["full_len"] = len(content)
                cut_count += 1
            else:
                item["content"] = content
            budget -= keep
        out.append(item)
    return out, cut_count


def log_conversation(
    task: str,
    model: str,
    client_ip: str,
    client_type: str,
    system_prompt: str,
    messages: list[dict],   # {"role": str, "content": str|None, "tool": str|None}
    steps: int,
    duration_ms: int,
    error: str | None = None,
    username: str = "",
):
    """Speichert eine abgeschlossene Konversation vollstaendig.

    Erst der Rumpf, dann die Index-Zeile: bricht das Schreiben des Rumpfes ab,
    entsteht kein Index-Eintrag, der auf einen fehlenden Rumpf zeigt. Der
    umgekehrte Weg haette einen Eintrag hinterlassen, der beim Aufklappen
    leer bleibt.
    """
    task = task or ""
    conv_id = _new_id()
    msgs, cut_count = _prepare_messages(messages or [])
    body = {
        "id": conv_id,
        "ts": time.time(),
        "task": task,                        # vollstaendig, auch im Rumpf
        "system_prompt": system_prompt or "",  # vollstaendig
        "messages": msgs,
    }
    entry = {
        "id": conv_id,
        "ts": body["ts"],
        "task": task,                        # vollstaendig – kein [:200] mehr
        "model": model or "",
        "username": username or "",
        "client_ip": client_ip or "unknown",
        "client_type": client_type or "browser",
        "steps": steps,
        "duration_ms": duration_ms,
        "error": error,
        "msg_count": len(msgs),
        "sys_len": len(system_prompt or ""),
    }
    if cut_count:
        entry["truncated_msgs"] = cut_count
    with _lock:
        _migrate_once()
        try:
            _ensure_dir()
            _body_path(conv_id).write_text(json.dumps(body, ensure_ascii=False),
                                          encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"[conv_log] Rumpf nicht gespeichert: {e}", flush=True)
            return
        try:
            _append_index(entry)
        except Exception as e:  # noqa: BLE001
            print(f"[conv_log] Index nicht gespeichert: {e}", flush=True)
            return
        # KEIN Verdraengen nach Stueckzahl. Entfernt wird ausschliesslich nach
        # Alter (prune_older_than) – siehe Modul-Docstring.


def _remove_body(conv_id) -> None:
    try:
        if conv_id:
            _body_path(conv_id).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


# ─── Lesen ────────────────────────────────────────────────────────────────────

def get_conversations(limit: int = 50, ip_filter: str | None = None,
                      user_filter: str | None = None) -> list:
    """Kopfdaten der letzten Konversationen (neueste zuerst), OHNE Nachrichten.

    Die Nachrichten holt die Oberflaeche beim Aufklappen ueber ``get_body()``.
    Wuerde diese Liste die vollstaendigen Inhalte mitliefern, waere die
    getrennte Ablage sinnlos – eine Antwort mit 100 Konversationen koennte
    dann hunderte MB gross werden.

    Liest den Index von hinten und bricht ab, sobald ``limit`` Treffer da sind.
    Der Filter wirkt WAEHREND des Lesens, nicht danach: bei einem seltenen
    Benutzer wuerde ein Nachfilter auf den letzten n Zeilen sonst „keine
    Treffer" melden, obwohl weiter hinten welche liegen – derselbe Fehler wie
    beim Wissensgruppen-Filter am 2026-08-02.
    """
    limit = max(1, limit)
    out: list[dict] = []
    with _lock:
        _migrate_once()
        for e in _iter_index_reversed():
            if ip_filter and e.get("client_ip") != ip_filter:
                continue
            # Normalisiert vergleichen: die Oberflaeche zeigt (und liefert)
            # Namen MIT Domaenen-Praefix, gespeichert ist je nach Tippform des
            # Anmeldefelds mal so, mal ohne. Ein exakter Vergleich liefert dann
            # eine leere Liste, obwohl der Name im Pulldown steht.
            if user_filter and norm_user(e.get("username") or "") != norm_user(user_filter):
                continue
            out.append(e)
            if len(out) >= limit:
                break
    return out


def get_body(conv_id: str) -> dict | None:
    """Vollstaendiger Rumpf einer Konversation (System-Prompt + Nachrichten)."""
    path = _body_path(conv_id)
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def get_known_ips() -> list[str]:
    with _lock:
        _migrate_once()
        entries = _read_index()
    seen = []
    for e in reversed(entries):
        ip = e.get("client_ip", "unknown")
        if ip not in seen:
            seen.append(ip)
    return seen


def get_known_users() -> list[str]:
    with _lock:
        _migrate_once()
        entries = _read_index()
    seen = []
    for e in reversed(entries):
        user = e.get("username", "")
        if user and user not in seen:
            seen.append(user)
    return seen


def get_stats() -> dict:
    """Umfang des Verlaufs (Anzahl, Zeitspanne, Plattenbedarf) fuer die Anzeige.

    Bewusst OHNE vollstaendiges JSON-Parsen: Zeilen werden nur gezaehlt
    (binaer, blockweise), und ausgewertet werden allein die **erste** und
    **letzte** Zeile. Ohne Stueckzahl-Schranke kann der Index sehr lang werden –
    dieser Endpunkt haengt am Telemetrie-Reiter und darf nicht mit der Historie
    langsamer werden.
    """
    count = 0
    oldest = newest = None
    size = 0
    with _lock:
        _migrate_once()
        try:
            if _INDEX.exists():
                with _INDEX.open("rb") as f:
                    while True:
                        blk = f.read(1024 * 1024)
                        if not blk:
                            break
                        count += blk.count(b"\n")
                first = last = None
                for e in _iter_index_reversed():      # jueng<ste Zeile zuerst
                    last = e
                    break
                for e in _read_index_first():
                    first = e
                    break
                oldest = (first or {}).get("ts")
                newest = (last or {}).get("ts")
        except Exception:  # noqa: BLE001
            pass
        try:
            with os.scandir(_CONV_DIR) as it:         # ein Durchlauf, kein glob
                for entry in it:
                    if entry.is_file():
                        size += entry.stat().st_size
        except Exception:  # noqa: BLE001
            pass
    return {"count": count, "oldest_ts": oldest, "newest_ts": newest,
            "bytes": size}


def _read_index_first(max_bytes: int = 64 * 1024):
    """Liefert die ERSTE (aelteste) verwertbare Index-Zeile – nur den Anfang
    der Datei lesen, nicht die ganze."""
    try:
        if not _INDEX.exists():
            return
        with _INDEX.open("rb") as f:
            buf = f.read(max_bytes)
        for raw in buf.split(b"\n"):
            if not raw.strip():
                continue
            try:
                yield json.loads(raw.decode("utf-8", "replace"))
                return
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return


# ─── Aufraeumen ───────────────────────────────────────────────────────────────

def prune_older_than(cutoff_ts: float) -> int:
    """Entfernt Konversationen, die aelter als ``cutoff_ts`` sind (Anzahl zurueck).

    Der Index wird nur neu geschrieben, wenn wirklich etwas wegfaellt.
    Zusaetzlich werden **verwaiste Rumpfdateien** entfernt: ein Absturz zwischen
    Rumpf und Index-Zeile laesst genau solche zurueck, und die wuerde ohne
    diesen Schritt nie jemand aufraeumen.
    """
    with _lock:
        _migrate_once()
        entries = _read_index()
        keep = [e for e in entries if (e.get("ts") or 0) >= cutoff_ts]
        removed = len(entries) - len(keep)
        if removed:
            _write_index(keep)
            alive = {str(e.get("id")) for e in keep}
            for e in entries:
                if str(e.get("id")) not in alive:
                    _remove_body(e.get("id"))
        else:
            alive = {str(e.get("id")) for e in keep}
        # Verwaiste Rumpfdateien (kein Index-Eintrag, aelter als der Schnitt)
        try:
            for p in _CONV_DIR.glob("*.json"):
                if p.stem in alive or p.name == "index.jsonl":
                    continue
                if p.stat().st_mtime < cutoff_ts:
                    p.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        return removed


def clear():
    """Loescht den gesamten Verlauf – Index UND alle Rumpfdateien."""
    with _lock:
        _migrate_once()
        try:
            for p in _CONV_DIR.glob("*.json"):
                p.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            _write_index([])
        except Exception:  # noqa: BLE001
            pass

def norm_user(name: str) -> str:
    """Benutzername auf den blossen Kontonamen reduzieren: ohne Domaenen-Praefix
    (``DOMAIN\\user``), ohne UPN-Suffix (``user@domain``), klein.

    WARUM DER FILTER DAS BRAUCHT: die Oberflaeche zeigt Namen MIT Praefix
    (``nexus\\sven.sander``), gespeichert ist je nach Tippform des Anmeldefelds
    mal so, mal ohne. Ein Vergleich auf dem Rohwert findet dann nichts – und
    eine Filterzeile, die nichts findet, obwohl der Name daneben steht, ist
    genau der Fehler, der am 2026-08-05 im Audit-Log Stunden gekostet hat
    (dort war es Chrome-Autofill, hier waere es unsere eigene Anzeige).

    Kanal-Kennungen (``wa:``/``tg:``/``api:``) bleiben unangetastet – sie tragen
    keinen Domaenenanteil, und ein Zerlegen am Doppelpunkt wuerde sie ruinieren.
    """
    s = (name or "").strip()
    if not s or ":" in s:
        return s.lower()
    return s.split("@")[0].split("\\")[-1].strip().lower()
