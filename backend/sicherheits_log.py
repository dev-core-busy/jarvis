"""Sicherheitsereignis-Protokoll (BSI M2).

WAS HIER LANDET
---------------
Anmeldungen (erfolgreich und fehlgeschlagen, mit Quelladresse), Kontosperren,
Abmeldungen, Aenderungen am eigenen Konto (Kennwort, 2FA) und JEDE aendernde
Anfrage, die eine Admin-Pruefung bestanden hat oder an ihr gescheitert ist.
Vorher stand davon nur ein Teil als ``print`` im Journal, fehlgeschlagene
Anmeldungen ohne IP, Admin-Aenderungen nur dort, wo jemand daran gedacht hatte.

ZWEI ABLAGEN, MIT ABSICHT
-------------------------
1. ``data/logs/sicherheit.jsonl`` – je Zeile ein Ereignis mit Hash-Kette:
   ``hash = HMAC-SHA256(k, prev + kanonisches JSON ohne hash)``, Merkmal
   ``"mac": 1`` in der Zeile. ``k`` ist aus dem Sitzungsschluessel abgeleitet
   (``schluessel_setzen``, von main.py beim Start), der seit BSI M5 nur mit
   dem Hauptschluessel lesbar ist.
   WARUM MIT SCHLUESSEL (Code-Review 2026-10-07): bis dahin war es ein
   schluesselloses sha256 – wer Schreibrecht auf die Datei hatte, aenderte
   eine Zeile in der Mitte, rechnete alle folgenden Hashes neu, und
   ``pruefen()`` meldete ``ok``. Mit Schluessel geht das nur noch mit dem
   Hauptschluessel. GRENZE: der laufende Dienst selbst hat den Schluessel –
   gegen eine Uebernahme des Dienstbenutzers schuetzt nur Ablage 2.
   Zeilen von vor der Umstellung (ohne ``mac``) bleiben schluessellos
   pruefbar. Nach der ersten Zeile mit ``mac`` gilt eine ohne als Bruch, und
   mit Schluessel muss die LETZTE Zeile ``mac`` tragen – sonst waere "Merkmal
   ueberall entfernen, schluessellos neu rechnen" der Umweg. Damit das gleich
   nach dem Ausrollen stimmt, schreibt main.py beim Start ``dienst_start``.
   Was die Kette NICHT kann: das Abschneiden am Ende erkennen – wer
   Schreibrecht auf die Datei hat, kann die letzten Zeilen weglassen. Dafuer
   gibt es Ablage 2.
2. syslog (``/dev/log``, Facility authpriv, Kennung ``jarvis-security``): landet
   im Journal, das der Dienstbenutzer nicht aendern kann, und ist der Punkt, an
   dem ein SIEM oder ein zentraler rsyslog die Ereignisse abholt.

Der Anfang der Kette darf fehlen: die Aufbewahrungsfrist schneidet alte Zeilen
vorne ab, die erste verbliebene Zeile ist dann der Anker (``pruefen()`` meldet
ihn, wertet ihn aber nicht als Bruch).

AUFBEWAHRUNG
------------
Nur nach Alter (keine Stueckzahl-Schranke): ``JARVIS_SICHERHEITS_LOG_TAGE``,
Vorgabe 365, ``0`` = dauerhaft. Eigene Frist statt der 90 Tage der Telemetrie,
weil eine Sicherheitsauswertung weiter zurueckreichen muss als die Fehlersuche.

Schreiben darf nie eine Anfrage kippen: jeder Fehler wird geschluckt und
gezaehlt (``zustand()``).
"""

import hashlib
import hmac
import json
import logging
import logging.handlers
import os
import threading
import time
from pathlib import Path

DATEI = Path("data/logs/sicherheit.jsonl")
NULL_HASH = "0" * 64
SYSLOG_KENNUNG = "jarvis-security"
_ENV_TAGE = "JARVIS_SICHERHEITS_LOG_TAGE"
DEFAULT_TAGE = 365

# syslog-Schwere je Ereignisart; alles andere ist "notice".
# ⚠ NOTICE GIBT ES IN PYTHONS logging NICHT. Stufe 25 heisst dort "Level 25",
# und SysLogHandler bildet unbekannte Namen auf "warning" ab – gemessen
# 2026-10-20: JEDES Sicherheitsereignis (auch dienst_start, anmeldung) stand als
# Warnung im Journal, der Filter "Warnungen" war damit wertlos, und ein SIEM sah
# lauter Warnungen. Die Abbildung auf "notice" setzt _syslog_logger am EIGENEN
# Handler (kein logging.addLevelName – das waere eine globale Aenderung).
NOTICE = logging.INFO + 5
_SCHWERE = {
    "anmeldung_fehlgeschlagen": logging.WARNING,
    "konto_gesperrt": logging.WARNING,
    "admin_verweigert": logging.WARNING,
}

_lock = threading.Lock()
_letzter_hash: str | None = None
_letzte_datei: str | None = None
_syslog: logging.Logger | None = None
_fehler = {"datei": 0, "syslog": 0, "ohne_schluessel": 0}
_mac_schluessel: bytes | None = None
# Groesse der Datei nach dem letzten EIGENEN Schreiben – weicht sie ab, hat ein
# anderer Prozess angehaengt, und der gemerkte Hash ist nicht mehr der letzte.
_letzte_groesse: int | None = None
# Nebenprozesse laden den Schluessel einmal selbst (_schluessel()).
_selbst_geladen = False


def _ableiten(geheimnis: str) -> bytes | None:
    return (hashlib.sha256(b"jarvis-sicherheits-log\0" + geheimnis.encode()).digest()
            if geheimnis else None)


def schluessel_setzen(geheimnis: str) -> None:
    """Schluessel der Kette aus dem Sitzungsschluessel ableiten (main.py beim
    Start). Eigene Ableitung, damit der Sitzungsschluessel selbst nirgends
    als MAC fuer frei waehlbaren Text dient."""
    global _mac_schluessel
    _mac_schluessel = _ableiten(geheimnis)


def _schluessel() -> bytes | None:
    """Gesetzter Schluessel – oder, in einem NEBENPROZESS, der selbst geladene.

    WARUM (BSI-Abgleich 2026-10-26): ``python -m backend.abhaengigkeiten`` lief
    am 21.10. von Hand, ohne ``schluessel_setzen``, und schrieb Zeilen OHNE
    ``mac`` – auf DEV und ECHT ist die Kette seither gebrochen. Geladen wird
    ueber ``secret_key.nur_lesen``: nie erzeugt, nie fluechtig. Ohne
    Hauptschluessel (Prozess nicht ueber ``deploy/als_dienst.sh``) gibt es
    deshalb KEINEN Schluessel statt eines falschen.

    Die Fundorte haengen am Ort des Protokolls (``data/`` = ``DATEI`` zwei
    Ebenen hoch, ``.env`` eine darueber) – ein Test im Sandkasten liest so nie
    den Schluessel einer echten Installation.
    """
    global _mac_schluessel, _selbst_geladen
    if _mac_schluessel or _selbst_geladen:
        return _mac_schluessel
    _selbst_geladen = True
    try:
        data = DATEI.resolve().parent.parent
        env = os.environ.get("SECRET_KEY", "")
        if not env.strip():
            try:
                from dotenv import dotenv_values
                env = str(dotenv_values(data.parent / ".env").get("SECRET_KEY") or "")
            except Exception:  # noqa: BLE001
                env = ""
        from backend import secret_key
        _mac_schluessel = _ableiten(secret_key.nur_lesen(env, data / ".secret_key") or "")
    except Exception:  # noqa: BLE001
        _mac_schluessel = None
    return _mac_schluessel


class _OhneSchluessel(Exception):
    """Die Kette traegt Pruefmerkmale, dieser Prozess hat keinen Schluessel."""


def _sperren(f) -> None:
    """Exklusive Sperre ueber Prozessgrenzen (Dienst + Wartungsbefehl)."""
    try:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    except (ImportError, OSError):
        pass


def aufbewahrung_tage() -> int:
    """Frist in Tagen (0 = dauerhaft). Funktion, kein Importwert.

    Seit BSI M9 (2026-10-12) zuerst die Einstellung aus der Oberflaeche
    (backend/loeschfristen.py), dann die Umgebungsvariable."""
    try:
        from backend import loeschfristen
        return loeschfristen.tage("sicherheit")
    except Exception:  # noqa: BLE001
        pass
    roh = os.environ.get(_ENV_TAGE)
    if roh is None or not str(roh).strip():
        return DEFAULT_TAGE
    try:
        tage = int(float(str(roh).replace(",", ".").strip()))
    except (TypeError, ValueError):
        return DEFAULT_TAGE
    return 0 if tage <= 0 else min(tage, 3650)


def _kanonisch(eintrag: dict) -> str:
    return json.dumps(eintrag, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(prev: str, eintrag: dict, schluessel: bytes | None = None) -> str:
    ohne = {k: v for k, v in eintrag.items() if k != "hash"}
    daten = (prev + _kanonisch(ohne)).encode("utf-8")
    if eintrag.get("mac"):
        if not schluessel:
            raise ValueError("Schluessel fehlt")
        return hmac.new(schluessel, daten, hashlib.sha256).hexdigest()
    return hashlib.sha256(daten).hexdigest()


def _letzte_zeile(pfad: Path) -> str:
    """Letzte nicht-leere Zeile, von hinten gelesen (die Datei kann gross sein)."""
    try:
        with pfad.open("rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            rest = b""
            while pos > 0:
                n = min(65536, pos)
                pos -= n
                f.seek(pos)
                rest = f.read(n) + rest
                zeilen = rest.splitlines()
                # erste Zeile eines Blocks kann angeschnitten sein
                for z in reversed(zeilen[1:] if pos > 0 else zeilen):
                    if z.strip():
                        return z.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    return ""


def _letzter_eintrag() -> dict:
    zeile = _letzte_zeile(DATEI)
    if not zeile:
        return {}
    try:
        e = json.loads(zeile)
        return e if isinstance(e, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _prev_hash() -> str:
    """Hash der letzten Zeile – gemerkt, solange niemand die Datei getauscht
    oder (aus einem anderen Prozess) verlaengert hat."""
    global _letzter_hash, _letzte_datei, _letzte_groesse
    try:
        groesse = DATEI.stat().st_size
    except OSError:
        groesse = None
    if (_letzter_hash is not None and _letzte_datei == str(DATEI.resolve())
            and groesse == _letzte_groesse):
        return _letzter_hash
    # unlesbare letzte Zeile: Kette ab hier neu verankern, aber den Bruch
    # sichtbar lassen (pruefen() meldet ihn)
    h = _letzter_eintrag().get("hash") or NULL_HASH
    _letzter_hash, _letzte_datei, _letzte_groesse = h, str(DATEI.resolve()), groesse
    return h


def _syslog_handler(adresse) -> logging.handlers.SysLogHandler:
    """Handler mit authpriv und der Abbildung NOTICE -> "notice" (siehe oben).

    ``adresse``: Pfad des Syslog-Sockets oder (host, port) – Letzteres nur fuer
    den Waechter, der die Datagramme mitliest."""
    h = logging.handlers.SysLogHandler(
        address=adresse, facility=logging.handlers.SysLogHandler.LOG_AUTHPRIV)
    # Am INSTANZ-Woerterbuch, nicht an der Klasse: andere SysLogHandler im
    # Prozess bleiben unberuehrt.
    h.priority_map = dict(h.priority_map)
    h.priority_map[logging.getLevelName(NOTICE)] = "notice"
    return h


def _syslog_logger(adresse="/dev/log") -> logging.Logger | None:
    global _syslog
    if _syslog is not None:
        return _syslog
    if isinstance(adresse, str) and not os.path.exists(adresse):
        return None
    lg = logging.getLogger("jarvis.sicherheit.syslog")
    lg.propagate = False
    lg.setLevel(logging.INFO)
    h = _syslog_handler(adresse)
    h.setFormatter(logging.Formatter(SYSLOG_KENNUNG + ": %(message)s"))
    lg.addHandler(h)
    _syslog = lg
    return lg


def ereignis(art: str, *, benutzer: str = "", ip: str = "", ergebnis: str = "",
             **details) -> dict:
    """Ein Sicherheitsereignis festhalten. Gibt den geschriebenen Eintrag zurueck.

    ``details`` darf KEINE Geheimnisse enthalten – Aufrufer uebergeben Pfade,
    Statuscodes und Gruende, nie Anfragekoerper.
    """
    jetzt = time.time()
    eintrag = {
        "ts": int(jetzt),
        "zeit": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(jetzt)),
        "art": str(art),
        "benutzer": str(benutzer or ""),
        "ip": str(ip or ""),
        "ergebnis": str(ergebnis or ""),
    }
    if details:
        eintrag["details"] = {k: v for k, v in details.items() if v not in (None, "")}
    global _letzter_hash, _letzte_groesse
    with _lock:
        try:
            DATEI.parent.mkdir(parents=True, exist_ok=True)
            neu = not DATEI.exists()
            with DATEI.open("a", encoding="utf-8") as f:
                _sperren(f)
                schluessel = _schluessel()
                # Eine Zeile ohne Merkmal hinter einer mit Merkmal ist fuer
                # pruefen() ein Bruch – also gar nicht erst schreiben. Das
                # Ereignis geht trotzdem nach syslog (Ablage 2, unten).
                if not schluessel and _letzter_eintrag().get("mac"):
                    raise _OhneSchluessel()
                prev = _prev_hash()
                eintrag["prev"] = prev
                if schluessel:
                    eintrag["mac"] = 1
                eintrag["hash"] = _hash(prev, eintrag, schluessel)
                f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
                f.flush()
                _letzter_hash = eintrag["hash"]
                _letzte_groesse = os.fstat(f.fileno()).st_size
            if neu:
                try:
                    os.chmod(DATEI, 0o600)
                except OSError:
                    pass
        except _OhneSchluessel:
            _fehler["ohne_schluessel"] += 1
            print(f"[Sicherheit] '{art}' nur im Journal (jarvis-security), nicht in "
                  f"{DATEI}: dieser Prozess hat den Schluessel der Kette nicht – "
                  "Wartungsbefehle ueber deploy/als_dienst.sh starten.", flush=True)
        except Exception as e:  # noqa: BLE001
            _fehler["datei"] += 1
            print(f"[Sicherheit] Protokoll nicht schreibbar: {e}", flush=True)
    try:
        lg = _syslog_logger()
        if lg is not None:
            lg.log(_SCHWERE.get(art, NOTICE),
                   json.dumps({k: v for k, v in eintrag.items() if k not in ("prev",)},
                              ensure_ascii=False))
    except Exception:  # noqa: BLE001
        _fehler["syslog"] += 1
    return eintrag


def pruefen(pfad: Path | None = None) -> dict:
    """Kette nachrechnen. ``ok`` = keine Zeile veraendert, entfernt oder eingeschoben.

    Der Anker (``prev`` der ersten Zeile) ist kein Bruch: dort hat die Frist
    abgeschnitten oder die Datei begonnen. Ohne Schluessel (``schluessel_setzen``)
    sind Zeilen mit ``mac`` nicht pruefbar – das ist dann KEIN ``ok``.
    """
    pfad = pfad or DATEI
    ergebnis = {"ok": True, "zeilen": 0, "anker": None, "brueche": []}
    mac_gesehen = False
    letzte_ohne_mac = None
    if not pfad.exists():
        return ergebnis
    prev = None
    with pfad.open(encoding="utf-8", errors="replace") as f:
        for nr, zeile in enumerate(f, 1):
            if not zeile.strip():
                continue
            ergebnis["zeilen"] += 1
            try:
                e = json.loads(zeile)
            except Exception:  # noqa: BLE001
                ergebnis["brueche"].append({"zeile": nr, "grund": "kein JSON"})
                prev = None
                continue
            if prev is None and ergebnis["anker"] is None:
                ergebnis["anker"] = e.get("prev")
            elif prev is not None and e.get("prev") != prev:
                ergebnis["brueche"].append({"zeile": nr, "grund": "Kette unterbrochen"})
            letzte_ohne_mac = (nr, not e.get("mac"))
            if e.get("mac"):
                mac_gesehen = True
            elif mac_gesehen:
                # ohne Merkmal nach einer Zeile mit Merkmal: Merkmal entfernt
                # und schluessellos neu gerechnet
                ergebnis["brueche"].append({"zeile": nr, "grund": "ohne Schluessel"})
            try:
                passt = hmac.compare_digest(
                    _hash(e.get("prev") or "", e, _mac_schluessel), str(e.get("hash")))
            except ValueError:
                ergebnis["brueche"].append({"zeile": nr, "grund": "Schluessel fehlt"})
                passt = True
            if not passt:
                ergebnis["brueche"].append({"zeile": nr, "grund": "Inhalt veraendert"})
            prev = e.get("hash")
    if _mac_schluessel and letzte_ohne_mac and letzte_ohne_mac[1]:
        ergebnis["brueche"].append({"zeile": letzte_ohne_mac[0],
                                    "grund": "letzte Zeile ohne Schluessel"})
    ergebnis["ok"] = not ergebnis["brueche"]
    return ergebnis


def prune_older_than(cutoff_ts: float) -> int:
    """Zeilen vor ``cutoff_ts`` vorne abschneiden (Kette bleibt ab dem Anker gueltig).

    Nur ein zusammenhaengender Anfang wird entfernt – eine juengere Zeile
    zwischen alten (Uhr verstellt) bleibt mit allem dahinter stehen, sonst
    entstuende mitten in der Kette ein Bruch.
    """
    if cutoff_ts is None:
        return 0
    with _lock:
        if not DATEI.exists():
            return 0
        zeilen = DATEI.read_text(encoding="utf-8", errors="replace").splitlines()
        weg = 0
        for z in zeilen:
            if not z.strip():
                weg += 1
                continue
            try:
                ts = json.loads(z).get("ts")
            except Exception:  # noqa: BLE001
                break
            if ts is None or ts >= cutoff_ts:
                break
            weg += 1
        if not weg:
            return 0
        rest = [z for z in zeilen[weg:] if z.strip()]
        tmp = DATEI.with_suffix(".jsonl.tmp")
        tmp.write_text(("\n".join(rest) + "\n") if rest else "", encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(DATEI)
        # der gemerkte Hash bleibt gueltig: vorne gekuerzt, das Ende ist dasselbe
        return sum(1 for z in zeilen[:weg] if z.strip())


def lesen(limit: int = 200, art: str = "", benutzer: str = "", ip: str = "") -> list[dict]:
    """Juengste Ereignisse zuerst; Filter wirkt beim Lesen, nicht danach.

    ``art`` exakt, ``benutzer`` und ``ip`` als Teilstring ohne Ruecksicht auf
    Gross/Klein – ein Domaenenname steht mal mit, mal ohne Praefix im Protokoll,
    und wer nach ``mueller`` sucht, meint beide Schreibweisen."""
    aus: list[dict] = []
    if not DATEI.exists():
        return aus
    benutzer = (benutzer or "").strip().lower()
    ip = (ip or "").strip().lower()
    for zeile in reversed(DATEI.read_text(encoding="utf-8", errors="replace").splitlines()):
        if not zeile.strip():
            continue
        try:
            e = json.loads(zeile)
        except Exception:  # noqa: BLE001
            continue
        if art and e.get("art") != art:
            continue
        if benutzer and benutzer not in str(e.get("benutzer") or "").lower():
            continue
        if ip and ip not in str(e.get("ip") or "").lower():
            continue
        aus.append(e)
        if len(aus) >= limit:
            break
    return aus


def arten() -> list[str]:
    """Alle Ereignisarten, die im Protokoll VORKOMMEN (fuer die Auswahlliste).

    Aus der Datei statt aus einer gepflegten Liste: eine neue Art taucht damit
    von selbst im Filter auf, und es steht keine Art zur Wahl, die nie vorkam."""
    gesehen: set[str] = set()
    if not DATEI.exists():
        return []
    for zeile in DATEI.read_text(encoding="utf-8", errors="replace").splitlines():
        if not zeile.strip():
            continue
        try:
            a = json.loads(zeile).get("art")
        except Exception:  # noqa: BLE001
            continue
        if isinstance(a, str) and a:
            gesehen.add(a)
    return sorted(gesehen)


def zustand() -> dict:
    return {"datei": str(DATEI), "fehler": dict(_fehler),
            "syslog": os.path.exists("/dev/log"), "aufbewahrung_tage": aufbewahrung_tage()}


if __name__ == "__main__":  # python3 -m backend.sicherheits_log [pruefen|zeigen]
    import sys
    befehl = sys.argv[1] if len(sys.argv) > 1 else "pruefen"
    if befehl == "pruefen":
        # Ohne Schluessel ist jede Zeile mit Merkmal unpruefbar – das waere eine
        # Liste von Scheinbruechen, kein Ergebnis (BSI-Abgleich 2026-10-26).
        _schluessel()
        if not _mac_schluessel and '"mac"' in (DATEI.read_text(encoding="utf-8", errors="replace")
                                               if DATEI.exists() else ""):
            print(json.dumps({"ok": None, "fehler": "Schluessel der Kette fehlt in diesem "
                              "Prozess – ueber deploy/als_dienst.sh starten"},
                             ensure_ascii=False), flush=True)
            sys.exit(2)
        r = pruefen()
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0 if r["ok"] else 1)
    for e in reversed(lesen(int(sys.argv[2]) if len(sys.argv) > 2 else 50)):
        print(json.dumps(e, ensure_ascii=False))
