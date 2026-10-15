"""Inhalts-Kennung fuer /static/-Adressen: dauerhaft cachen, ohne je zu veralten.

WARUM (2026-10-13): jede Datei unter /static/ ging mit ``no-cache`` hinaus. Bei
jedem Seitenwechsel fragte der Browser deshalb JEDE eingebundene Datei neu nach
(Portal 33, Chat 41, Einstellungen 64) – je Datei ein Netzweg, bei HTTP/1.1
hoechstens sechs gleichzeitig. Der Server antwortet in 5 ms mit 304, der Preis
liegt in den Wegen dazwischen.

Ein langer Cache auf die von Hand gepflegten ``?v=N`` waere die naheliegende
Abhilfe – und genau die falsche: ``test_cache_buster.py`` prueft, dass alle
Seiten DIESELBE Nummer tragen, nicht dass die Nummer zum INHALT passt (Register:
zwei Zweige vergaben dieselbe Nummer fuer verschiedene Inhalte). Eine vergessene
Nummer haette Browser auf einer alten Fassung festgehalten, ohne Rueckweg.

Deshalb bildet der SERVER die Kennung aus dem Inhalt:

  1. ``html_umschreiben`` ersetzt beim Ausliefern einer HTML-Seite in jedem
     ``src``/``href`` auf eine Datei unter /static/ die Abfrage durch
     ``?v=<Inhalts-Kennung>``.
  2. ``cache_kopf`` vergibt den langen Cache NUR, wenn das ``v`` der Anfrage
     GLEICH der aktuellen Kennung der Datei ist. Alles andere (Hand-Nummer,
     keine Nummer, veraltete Kennung, unbekannte Datei) bleibt ``no-cache``.

Die Zusage haengt allein an (2): eine Adresse mit langem Cache bezeichnet
nachweislich genau den Inhalt, der unter ihr ausgeliefert wurde. Eine Seite, die
(1) nicht durchlaeuft, oder ein Skript, das eine Datei mit Hand-Nummer
nachlaedt, wird dadurch nicht falsch – nur nicht schneller.

Die von Hand gepflegten ``?v=N`` im Quelltext bleiben stehen und schaden nicht:
sie sind die Fassung fuer jeden Weg, der nicht umschreibt.
"""
from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from typing import Optional

LANG = "private, max-age=31536000, immutable"
KURZ = "no-cache, must-revalidate"

# Nur ausgelieferte Bausteine, keine Seiten: eine HTML-Datei unter /static/
# bleibt immer kurz (ihr eigener Inhalt verweist auf weitere Kennungen).
ENDUNGEN = frozenset({
    "js", "css", "png", "jpg", "jpeg", "gif", "svg", "webp", "ico",
    "woff", "woff2", "ttf", "otf",
})

_wurzel: Optional[Path] = None
_cache: dict = {}            # rel -> (mtime_ns, groesse, kennung)
_sperre = threading.Lock()

# src="/static/js/x.js?v=3"  |  href='/static/css/y.css'
# Gruppe 3 (die Abfrage) nur, wenn sie AUSSCHLIESSLICH aus v=… besteht – eine
# Adresse mit weiteren Parametern bleibt unangetastet.
_REF = re.compile(
    r"""(\b(?:src|href)\s*=\s*(["']))/static/([A-Za-z0-9_][A-Za-z0-9_./-]*)"""
    r"""(\?v=[A-Za-z0-9._-]*)?(?=\2)""")


def wurzel_setzen(pfad: Path) -> None:
    """Das Verzeichnis, das unter /static/ ausgeliefert wird."""
    global _wurzel
    _wurzel = Path(pfad).resolve()
    with _sperre:
        _cache.clear()


def _datei(rel: str) -> Optional[Path]:
    """Die Datei hinter einer /static/-Adresse – None, wenn sie nicht in
    Frage kommt (falsche Endung, ausserhalb der Wurzel, keine Datei)."""
    if _wurzel is None or not rel or "\\" in rel:
        return None
    if rel.rsplit(".", 1)[-1].lower() not in ENDUNGEN or "." not in rel:
        return None
    try:
        p = (_wurzel / rel).resolve()
        if not p.is_relative_to(_wurzel) or not p.is_file():
            return None
        return p
    except (OSError, ValueError):
        return None


def kennung(rel: str) -> Optional[str]:
    """Inhalts-Kennung (16 Hex) der Datei unter /static/<rel>, None wenn es
    keine passende Datei gibt. Gemerkt je (mtime, Groesse); gelesen wird nur
    nach einer Aenderung."""
    p = _datei(rel)
    if p is None:
        return None
    try:
        st = p.stat()
    except OSError:
        return None
    with _sperre:
        alt = _cache.get(rel)
    if alt and alt[0] == st.st_mtime_ns and alt[1] == st.st_size:
        return alt[2]
    try:
        k = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except OSError:
        return None
    with _sperre:
        _cache[rel] = (st.st_mtime_ns, st.st_size, k)
    return k


def cache_kopf(pfad: str, v: Optional[str]) -> str:
    """Cache-Control fuer eine Anfrage an ``pfad`` (beginnt mit /static/) mit
    dem Abfragewert ``v``. Lang NUR bei Gleichheit mit der aktuellen Kennung."""
    if not v or not pfad.startswith("/static/"):
        return KURZ
    k = kennung(pfad[len("/static/"):])
    return LANG if k is not None and v == k else KURZ


def html_umschreiben(text: str) -> str:
    """Jede /static/-Einbindung im Markup auf ``?v=<Inhalts-Kennung>``.
    Unbekannte Dateien bleiben, wie sie stehen."""
    def ersetzen(m: re.Match) -> str:
        k = kennung(m.group(3))
        if k is None:
            return m.group(0)
        return "%s/static/%s?v=%s" % (m.group(1), m.group(3), k)
    return _REF.sub(ersetzen, text)
