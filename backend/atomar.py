"""Atomares Lesen und Schreiben kleiner JSON-Zustandsdateien – EINE Fassung.

Code-Review 2026-10-18: rund fuenfzehn Module hatten je eine eigene
tmp+replace-Variante, mehrere gar keine (``write_text`` direkt aufs
Original). Zwei Fehlerbilder kamen dabei zusammen und kosteten Daten:
  * ein Absturz mitten im Schreiben hinterliess eine halbe Datei,
  * der Lesepfad fiel bei einem Fehler STILL auf eine Vorgabe zurueck – und
    der naechste Schreibvorgang machte die Vorgabe dauerhaft (so verlor
    ``knowledge_groups`` alle Gruppenzuordnungen auf einmal).

Darum hier:
  * ``schreiben``: Temp-Datei im selben Verzeichnis (``O_EXCL``), fsync,
    Modus des Vorgaengers, der vorige LESBARE Stand bleibt als ``.bak``,
    dann ``os.replace`` (ersetzt den Verzeichniseintrag, folgt keinem Link).
  * ``lesen``: fehlt die Datei -> Vorgabe; ist sie da und kaputt -> ``.bak``;
    ist auch die kaputt -> ``Unlesbar`` (fail-closed: der Aufrufer schreibt
    dann NICHT, die Datei bleibt fuer die Reparatur stehen).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path


class Unlesbar(RuntimeError):
    """Datei vorhanden, aber weder sie noch ihre Sicherung lesbar."""

    pass   # ausdruecklich: Waechter entfernen Docstrings vor dem Parsen


def _sicherung(pfad: Path) -> Path:
    return pfad.with_name(pfad.name + ".bak")


def _roh_lesen(pfad: Path):
    return json.loads(pfad.read_text(encoding="utf-8"))


def lesen(pfad, vorgabe=None, pruefen=None):
    """JSON lesen. ``vorgabe`` nur fuer eine FEHLENDE Datei; ``pruefen(daten) -> bool``
    entscheidet, ob der Inhalt die erwartete Form hat (sonst wie kaputt)."""
    pfad = Path(pfad)
    if not pfad.exists():
        return vorgabe() if callable(vorgabe) else vorgabe
    fehler = None
    for kandidat in (pfad, _sicherung(pfad)):
        try:
            daten = _roh_lesen(kandidat)
        except FileNotFoundError:
            continue
        except Exception as e:  # noqa: BLE001
            fehler = fehler or e
            continue
        if pruefen is not None and not pruefen(daten):
            fehler = fehler or ValueError("unerwartete Form")
            continue
        if kandidat != pfad:
            print(f"[Atomar] {pfad.name} unlesbar ({fehler}) – Sicherung verwendet", flush=True)
        return daten
    print(f"[Atomar] {pfad} UNLESBAR und keine lesbare Sicherung ({fehler})", flush=True)
    raise Unlesbar(f"{pfad.name}: {fehler}")


def schreiben(pfad, daten, modus: int | None = None, indent: int | None = 2,
              sicherung: bool = True) -> None:
    """JSON atomar schreiben (siehe Modulkopf)."""
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(daten, ensure_ascii=False, indent=indent)
    try:
        st = os.lstat(pfad)
        alt_modus = st.st_mode & 0o777
    except FileNotFoundError:
        alt_modus = None
    ziel_modus = modus if modus is not None else (alt_modus if alt_modus is not None else 0o644)
    tmp = pfad.with_name(f".{pfad.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), ziel_modus)
        if sicherung and alt_modus is not None:
            try:
                _roh_lesen(pfad)   # nur einen LESBAREN Vorstand sichern
                os.replace(pfad, _sicherung(pfad))
            except Exception:  # noqa: BLE001
                pass
        os.replace(tmp, pfad)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
