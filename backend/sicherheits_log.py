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

# syslog-Schwere je Ereignisart; alles andere ist "notice"
_SCHWERE = {
    "anmeldung_fehlgeschlagen": logging.WARNING,
    "konto_gesperrt": logging.WARNING,
    "admin_verweigert": logging.WARNING,
}

_lock = threading.Lock()
_letzter_hash: str | None = None
_letzte_datei: str | None = None
_syslog: logging.Logger | None = None
_fehler = {"datei": 0, "syslog": 0}
_mac_schluessel: bytes | None = None


def schluessel_setzen(geheimnis: str) -> None:
    """Schluessel der Kette aus dem Sitzungsschluessel ableiten (main.py beim
    Start). Eigene Ableitung, damit der Sitzungsschluessel selbst nirgends
    als MAC fuer frei waehlbaren Text dient."""
    global _mac_schluessel
    _mac_schluessel = (hashlib.sha256(b"jarvis-sicherheits-log\0" + geheimnis.encode()).digest()
                       if geheimnis else None)


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


def _prev_hash() -> str:
    """Hash der letzten Zeile – gemerkt, solange niemand die Datei getauscht hat."""
    global _letzter_hash, _letzte_datei
    if _letzter_hash is not None and _letzte_datei == str(DATEI.resolve()):
        return _letzter_hash
    zeile = _letzte_zeile(DATEI)
    h = NULL_HASH
    if zeile:
        try:
            h = json.loads(zeile).get("hash") or NULL_HASH
        except Exception:  # noqa: BLE001
            # unlesbare letzte Zeile: Kette ab hier neu verankern, aber den
            # Bruch sichtbar lassen (pruefen() meldet ihn)
            h = NULL_HASH
    _letzter_hash, _letzte_datei = h, str(DATEI.resolve())
    return h


def _syslog_logger() -> logging.Logger | None:
    global _syslog
    if _syslog is not None:
        return _syslog
    if not os.path.exists("/dev/log"):
        return None
    lg = logging.getLogger("jarvis.sicherheit.syslog")
    lg.propagate = False
    lg.setLevel(logging.INFO)
    h = logging.handlers.SysLogHandler(
        address="/dev/log", facility=logging.handlers.SysLogHandler.LOG_AUTHPRIV)
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
    global _letzter_hash
    with _lock:
        try:
            prev = _prev_hash()
            eintrag["prev"] = prev
            if _mac_schluessel:
                eintrag["mac"] = 1
            eintrag["hash"] = _hash(prev, eintrag, _mac_schluessel)
            DATEI.parent.mkdir(parents=True, exist_ok=True)
            neu = not DATEI.exists()
            with DATEI.open("a", encoding="utf-8") as f:
                f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
            if neu:
                try:
                    os.chmod(DATEI, 0o600)
                except OSError:
                    pass
            _letzter_hash = eintrag["hash"]
        except Exception as e:  # noqa: BLE001
            _fehler["datei"] += 1
            print(f"[Sicherheit] Protokoll nicht schreibbar: {e}", flush=True)
    try:
        lg = _syslog_logger()
        if lg is not None:
            lg.log(_SCHWERE.get(art, logging.INFO + 5),
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


def lesen(limit: int = 200, art: str = "") -> list[dict]:
    """Juengste Ereignisse zuerst; Filter wirkt beim Lesen, nicht danach."""
    aus: list[dict] = []
    if not DATEI.exists():
        return aus
    for zeile in reversed(DATEI.read_text(encoding="utf-8", errors="replace").splitlines()):
        if not zeile.strip():
            continue
        try:
            e = json.loads(zeile)
        except Exception:  # noqa: BLE001
            continue
        if art and e.get("art") != art:
            continue
        aus.append(e)
        if len(aus) >= limit:
            break
    return aus


def zustand() -> dict:
    return {"datei": str(DATEI), "fehler": dict(_fehler),
            "syslog": os.path.exists("/dev/log"), "aufbewahrung_tage": aufbewahrung_tage()}


if __name__ == "__main__":  # python3 -m backend.sicherheits_log [pruefen|zeigen]
    import sys
    befehl = sys.argv[1] if len(sys.argv) > 1 else "pruefen"
    if befehl == "pruefen":
        r = pruefen()
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0 if r["ok"] else 1)
    for e in reversed(lesen(int(sys.argv[2]) if len(sys.argv) > 2 else 50)):
        print(json.dumps(e, ensure_ascii=False))
