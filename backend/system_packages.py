"""Installierte Debian-Pakete als Bericht – erzeugt bei JEDEM Abruf.

Vorbild ist ein Skript des Betreibers (``system_packages_report.py``), das
``dpkg-query`` ausliest und eine JSON-Datei schreibt. Hier ist bewusst dreierlei
anders:

1. **ES ENTSTEHT KEINE DATEI.** Der Bericht wird bei jedem Abruf frisch
   erzeugt und nur ausgeliefert. Eine Datei auf Platte waere eine zweite
   Wahrheit, die genau dann veraltet ist, wenn man sie braucht – und ein
   Paketstand ist eine Aussage ueber den Server im Moment der Frage, nicht ueber
   den Moment des letzten Skriptlaufs. Ausserdem faellt damit die Frage weg, wem
   die Datei gehoert und wer sie lesen darf.

2. **NUR WIRKLICH INSTALLIERTE PAKETE.** ``dpkg-query -W`` listet auch Pakete
   im Zustand ``rc`` (entfernt, Konfiguration liegt noch) – auf dieser Maschine
   19 von 2844. Sie als "installiert" auszugeben waere schlicht falsch.
   Gefiltert wird ueber den ZWEITEN Buchstaben von ``${db:Status-Abbrev}``
   (der tatsaechliche Zustand); ``ii`` und ``hi`` (auf Hold) zaehlen damit
   beide, ``rc`` nicht. Der Zustand wird mit ausgegeben, sonst ist ein
   zurueckgehaltenes Paket von einem gewoehnlichen nicht zu unterscheiden.

3. **``${binary:Summary}`` statt ``${Description}``.** Letzteres ist die
   MEHRZEILIGE Langbeschreibung; in einer ``|``-getrennten Zeile zerlegt sie
   den Datensatz. Das Vorbild-Skript faengt das mit einem Split auf die
   Zeichenfolge ``\\n`` ab – der trifft nur die literalen zwei Zeichen, nicht
   den echten Umbruch. ``binary:Summary`` ist genau die eine Zusammenfassungs-
   zeile, um die es geht.

⚠ ZU DEN DATUMSANGABEN – sie sind ein HINWEIS, keine Urkunde. dpkg fuehrt kein
Installationsdatum; abgelesen wird die Datei ``/var/lib/dpkg/info/<paket>.list``.
Deren ``mtime`` ist der Zeitpunkt, zu dem dpkg die Dateiliste zuletzt
geschrieben hat (also Installation ODER Aktualisierung), ``ctime`` der letzte
Wechsel am Inode – auch ein ``chmod`` oder ein Wiederherstellen aus einem Backup
schlaegt dort durch. Deshalb heissen die Felder im Bericht zwar wie beim
Vorbild, die Oberflaeche schreibt aber dazu, woher die Werte stammen. Eine
Anzeige, die ein Datum als Installationsdatum ausgibt, das keines ist, behauptet
etwas, das sie nicht weiss.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional

# Feldtrenner. Ein Paketname, eine Version, eine Architektur und ein
# Status-Kuerzel koennen kein ``|`` enthalten; die Zusammenfassung steht als
# LETZTES Feld und wird deshalb nicht weiter zerlegt (``split(maxsplit)``).
_TRENNER = "|"
_FORMAT = (
    "${db:Status-Abbrev}|${Package}|${Version}|${Architecture}"
    "|${Installed-Size}|${binary:Summary}\n"
)

_INFO_DIR = "/var/lib/dpkg/info"

# Harte Deckel. ``dpkg-query`` braucht auf DEV 0,05 s; ein Zeitlimit ist
# trotzdem noetig, weil die dpkg-Datenbank waehrend eines laufenden ``apt``
# gesperrt sein kann und der Aufruf dann haengt.
_TIMEOUT_S = 30


class PaketFehler(RuntimeError):
    """Der Bericht konnte nicht erzeugt werden – mit Klartext-Begruendung."""


def _info_index() -> Dict[str, str]:
    """Paketname -> Pfad der ``.list``-Datei, EINMAL aufgebaut.

    Das Vorbild-Skript ruft ``os.listdir`` fuer jedes Paket erneut, dessen
    ``.list`` nicht unter dem blossen Namen liegt (Multi-Arch:
    ``libfoo:amd64.list``). Bei 2800 Paketen und 10400 Dateien im Verzeichnis
    sind das im ungueltigen Fall Millionen Vergleiche. Einmal lesen kostet
    gemessen 0,03 s.

    Der Eintrag OHNE Architektur-Suffix gewinnt: er ist der eindeutige.
    """
    idx: Dict[str, str] = {}
    try:
        namen = os.listdir(_INFO_DIR)
    except OSError:
        return idx
    for n in namen:
        if not n.endswith(".list"):
            continue
        stamm = n[:-5]
        name, _, _arch = stamm.partition(":")
        # Ein bereits gesetzter Eintrag ohne Suffix wird nicht ueberschrieben.
        if stamm == name or name not in idx:
            idx[name] = os.path.join(_INFO_DIR, n)
    return idx


def _zeit(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def sammle() -> List[Dict[str, Any]]:
    """Liest den Paketbestand. Wirft ``PaketFehler`` mit Klartext.

    Rueckgabe je Paket: ``package``, ``version``, ``architecture``, ``status``,
    ``size_kb`` (int, ``dpkg`` rechnet in KiB), ``install_date``,
    ``update_date``, ``summary``.
    """
    try:
        p = subprocess.run(
            ["dpkg-query", "-W", "-f=" + _FORMAT],
            capture_output=True, text=True, timeout=_TIMEOUT_S,
        )
    except FileNotFoundError:
        raise PaketFehler(
            "dpkg-query wurde nicht gefunden – der Paketbericht gibt es nur auf "
            "Debian-basierten Systemen."
        ) from None
    except subprocess.TimeoutExpired:
        raise PaketFehler(
            f"dpkg-query hat nach {_TIMEOUT_S} s nicht geantwortet. Meist laeuft "
            "gerade eine Paketinstallation und haelt die dpkg-Sperre."
        ) from None

    # ⚠ Ein Rueckgabewert != 0 ist hier NICHT zwingend ein Fehlschlag: dpkg-query
    # meldet 1, wenn EINZELNE Pakete nicht gefunden wurden, liefert die uebrigen
    # aber sauber auf stdout. Entschieden wird deshalb daran, ob Zeilen kamen.
    ausgabe = p.stdout or ""
    if not ausgabe.strip():
        grund = (p.stderr or "").strip().splitlines()
        raise PaketFehler(
            "dpkg-query hat keine Daten geliefert"
            + (": " + grund[0] if grund else ".")
        )

    idx = _info_index()
    pakete: List[Dict[str, Any]] = []
    for zeile in ausgabe.splitlines():
        if not zeile or _TRENNER not in zeile:
            continue
        teile = zeile.split(_TRENNER, 5)
        if len(teile) < 6:
            continue
        status, name, version, arch, groesse, summary = (t.strip() for t in teile)
        if not name:
            continue
        # ZWEITER Buchstabe = tatsaechlicher Zustand. ``ii``/``hi`` = installiert,
        # ``rc`` = entfernt mit Restkonfiguration und gehoert NICHT in eine
        # Liste installierter Pakete.
        if len(status) < 2 or status[1] != "i":
            continue

        pfad = idx.get(name)
        if pfad:
            try:
                st = os.stat(pfad)
                install_date, update_date = _zeit(st.st_ctime), _zeit(st.st_mtime)
            except OSError:
                install_date = update_date = ""
        else:
            install_date = update_date = ""

        try:
            kb = int(groesse)
        except (TypeError, ValueError):
            kb = 0

        pakete.append({
            "package": name,
            "version": version,
            "architecture": arch,
            "status": status,
            "size_kb": kb,
            "install_date": install_date,
            "update_date": update_date,
            "summary": summary,
        })

    pakete.sort(key=lambda d: d["package"].lower())
    return pakete


def bericht() -> Dict[str, Any]:
    """Der vollstaendige Bericht samt Kopfdaten.

    Die Kopfdaten sind kein Beiwerk: ohne ``erzeugt_am`` und ``host`` ist eine
    heruntergeladene Datei nach zwei Tagen nicht mehr zuzuordnen – und bei zwei
    Servern (DEV und ECHT) ist die Verwechslung sonst vorprogrammiert.
    """
    pakete = sammle()
    return {
        "erzeugt_am": datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": _hostname(),
        "anzahl": len(pakete),
        "groesse_kb_gesamt": sum(p["size_kb"] for p in pakete),
        "pakete": pakete,
    }


def _hostname() -> str:
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return ""


def dateiname(host: Optional[str] = None) -> str:
    """Vorschlag fuer den Download – mit Host und Zeitpunkt im Namen.

    Der Zeitpunkt gehoert in den NAMEN, nicht nur in die Datei: wer zwei Staende
    vergleichen will, hat sonst zweimal ``pakete.json`` im Download-Ordner.
    """
    h = "".join(c for c in (host or _hostname()) if c.isalnum() or c in "-_") or "host"
    return f"pakete_{h}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
