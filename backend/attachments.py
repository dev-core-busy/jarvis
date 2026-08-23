"""Lebensdauer der Anhang-Arbeitskopien in /tmp.

**Warum es diese Datei gibt.** Ein Chat-Anhang wird zusaetzlich als Arbeitskopie
`/tmp/anhang_<12 Hex>_<name>` abgelegt, weil `data/documents` seit 2026-07-28 auf 0750
steht und die Shell von Domain-Benutzern (als `jarvis_sandbox`) dort nicht hineinkommt –
ohne die Kopie waere "analysiere die angehaengte Tabelle" mit pandas/openpyxl tot.

Die Kopie MUSS fuer `jarvis_sandbox` lesbar sein. Da **alle** Domain-Benutzer als
derselbe OS-Benutzer laufen, heisst das zwangslaeufig: lesbar fuer JEDEN
Domain-Benutzer. Auf DEV nachgestellt (2026-08-05): `runuser -u jarvis_sandbox -- cat
/tmp/anhang_…` liefert den Inhalt, `ls /tmp` listet alles. Dateirechte koennen das
nicht loesen – 0600 wuerde auch den eigenen Lauf aussperren.

**Seit 2026-08-23 loest das der Mount-Namespace** (`backend/lauf_tmp.py`): Anhaenge
liegen in einem Verzeichnis JE BENUTZER und werden nur in dessen eigene Laeufe
eingehaengt; im Lauf ist `/tmp` ausschliesslich das Arbeitsverzeichnis dieses
Benutzers, fremde Arbeitskopien sind dort nicht vorhanden. **Die Frist bleibt trotzdem** – sie ist jetzt
Datenminimierung statt Notbehelf, und sie ist die einzige Schranke, solange auf einem
Server `bwrap` fehlt (dann liegen die Kopien wie bisher direkt in /tmp).

**Warum eine FRIST und nicht "loeschen nach dem Lauf":** der Hinweistext mit dem
/tmp-Pfad steht im Chat-Verlauf und geht in den Kontext der Folgeanfragen ein. Wer die
Datei direkt nach dem Lauf entfernt, laesst "und jetzt Spalte C" mit
`No such file or directory` scheitern – genau die Verarbeitung, die die Kopie
ermoeglichen soll. Die Frist deckt die normale Weiterarbeit ab und raeumt danach auf.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

WORK_DIR = Path("/tmp")
# Genau das Muster aus main.py (`anhang_{uuid4().hex[:12]}_{name}`). Bewusst KEIN
# breites `anhang_*`: in /tmp koennen Dateien anderer Programme liegen, und was dieses
# Modul nicht selbst erzeugt hat, loescht es nicht.
_NAME_RE = re.compile(r'^anhang_[0-9a-f]{12}_')

DEFAULT_TTL_MIN = 30
# Mit Lauf-Isolation ist die Frist kein Sicherheitsmittel mehr, sondern nur noch
# Datenminimierung – fremde Laeufe sehen die Kopie ohnehin nicht. Die 30 Minuten
# waren die Abwaegung "so kurz wie moeglich, so lang wie noetig fuer eine
# Folgefrage"; sie hat aber ihren Preis: wer nach der Mittagspause "und jetzt
# Spalte C" fragt, bekam `No such file or directory`. Mit Isolation kostet ein
# groesseres Fenster keine Trennung mehr, deshalb vier Stunden.
DEFAULT_TTL_MIN_ISOLIERT = 240


def ttl_minutes() -> int:
    """Frist in Minuten (ENV ``JARVIS_ATTACH_TTL_MIN``, 0 = nie loeschen).

    Eine FUNKTION, keine Modulkonstante: ein beim Import gelesener Wert waere bis zum
    naechsten Dienststart eingefroren (gleiche Begruendung wie
    ``documents.retention_days()``). Deckel 10080 Minuten (7 Tage) – eine laengere
    Frist waere praktisch "bis zum Reboot" und damit der Zustand, der behoben wird.

    OHNE ausdrueckliche Vorgabe haengt die Vorgabe daran, ob die Laeufe isoliert
    sind: ohne Isolation bleibt es bei 30 Minuten, denn dann ist die Frist die
    EINZIGE Schranke gegen das Mitlesen fremder Arbeitskopien.
    """
    vorgabe = DEFAULT_TTL_MIN
    try:
        from backend import lauf_tmp as _lt
        if _lt.isolation_gewuenscht() and os.path.exists(_lt.BWRAP):
            vorgabe = DEFAULT_TTL_MIN_ISOLIERT
    except Exception:  # noqa: BLE001
        pass
    try:
        v = int(os.environ.get("JARVIS_ATTACH_TTL_MIN", vorgabe))
    except Exception:  # noqa: BLE001
        return vorgabe
    if v <= 0:
        return 0
    return max(1, min(v, 10080))


def _arbeitswurzeln() -> list:
    """Wo Arbeitskopien liegen koennen: /tmp und die Verzeichnisse je Benutzer.

    Beide Orte, weil beide Betriebsarten vorkommen (mit und ohne Isolation) und
    weil nach einem Umschalten noch Kopien am alten Ort liegen. Die Kennungs-
    Verzeichnisse werden EINE Ebene tief durchsucht, nicht rekursiv – dieselbe
    Zurueckhaltung wie bei "nur direkte Kinder von /tmp".
    """
    wurzeln = [WORK_DIR]
    try:
        from backend.lauf_tmp import ANH_ROOT
        if ANH_ROOT.is_dir():
            wurzeln += [d for d in ANH_ROOT.iterdir() if d.is_dir()]
    except Exception:  # noqa: BLE001
        pass
    return wurzeln


def cleanup_arbeit(ttl_min: int | None = None, now: float | None = None) -> list[str]:
    """Entfernt ABGELAUFENE Arbeitsverzeichnisse (privates /tmp je Benutzer).

    Anders als die Arbeitskopien haengt hier ALLES an der Frist: das Verzeichnis
    gehoert dem Benutzer und ueberlebt seine Laeufe bewusst, damit eine
    Folgefrage das Zwischenprodukt noch findet. Es gibt also keinen Zeitpunkt,
    an dem "der Auftrag ist fertig" auch "weg damit" heisst.

    Die Frist ist ABSICHTLICH grosszuegiger (mindestens 4 h): sie ist die einzige
    Schranke gegen ein Verzeichnis, in dem gerade gearbeitet wird. Ein aktiver
    Lauf haelt die mtime frisch, ein 4 h stiller Benutzer arbeitet nicht mehr.

    **Das eigentliche Aufraeumen kann nur root** (Unterverzeichnisse des
    Sandbox-Benutzers) – siehe ``lauf_tmp.aufraeumen_root`` und die Broker-Op.
    Diese Fassung ist der Weg fuer den Alt-Betrieb (Backend als root) und raeumt
    sonst nur, was ihr gehoert.
    """
    ttl = (ttl_minutes() if ttl_min is None else int(ttl_min))
    if ttl <= 0:
        return []
    ttl = max(ttl, 240)
    grenze = (time.time() if now is None else now) - ttl * 60
    weg: list[str] = []
    try:
        from backend.lauf_tmp import ARBEIT_ROOT as _WURZEL
        if not _WURZEL.is_dir():
            return []
        import shutil as _shutil
        for d in _WURZEL.iterdir():
            try:
                st = d.lstat()
                import stat as _stat
                if not _stat.S_ISDIR(st.st_mode):
                    continue
                if st.st_mtime >= grenze:
                    continue
                _shutil.rmtree(d, ignore_errors=True)
                if not d.exists():
                    weg.append(d.name)
            except FileNotFoundError:
                continue
            except Exception as e:  # noqa: BLE001
                print(f"[Anhang] Arbeitsverzeichnis {d.name} nicht entfernbar: {e}",
                      flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[Anhang] Arbeitsverzeichnisse nicht pruefbar: {e}", flush=True)
    if weg:
        print(f"[Anhang] {len(weg)} abgelaufene(s) Arbeitsverzeichnis(se) entfernt",
              flush=True)
    return weg


def cleanup(ttl_min: int | None = None, now: float | None = None) -> list[str]:
    """Loescht abgelaufene Arbeitskopien; Rueckgabe = entfernte Dateinamen.

    Vier Schranken, damit nie etwas Fremdes getroffen wird:
      * Name muss ``_NAME_RE`` entsprechen,
      * nur direkte Kinder von /tmp (kein Abstieg in Unterverzeichnisse),
      * keine Symlinks und keine Verzeichnisse (``lstat``, nicht ``stat`` – ein Symlink
        auf /etc/passwd wuerde sonst als "alte Datei" gemeldet und entfernt),
      * Eigentuemer muss der eigene Benutzer sein (/tmp ist sticky, fremde Dateien
        liessen sich ohnehin nicht loeschen – die Pruefung vermeidet nur die
        Fehlermeldung und macht die Absicht deutlich).
    """
    ttl = ttl_minutes() if ttl_min is None else int(ttl_min)
    if ttl <= 0:
        return []
    grenze = (time.time() if now is None else now) - ttl * 60
    uid = os.getuid()
    weg: list[str] = []
    eintraege = []
    for wurzel in _arbeitswurzeln():
        try:
            eintraege += list(wurzel.iterdir())
        except Exception as e:  # noqa: BLE001
            print(f"[Anhang] {wurzel} nicht lesbar: {e}", flush=True)
    for p in eintraege:
        if not _NAME_RE.match(p.name):
            continue
        try:
            st = p.lstat()
            import stat as _stat
            if not _stat.S_ISREG(st.st_mode):        # Symlink/Verzeichnis/FIFO
                continue
            if st.st_uid != uid:
                continue
            if st.st_mtime >= grenze:
                continue
            p.unlink()
            weg.append(p.name)
        except FileNotFoundError:
            continue                                  # parallel schon weg
        except Exception as e:  # noqa: BLE001
            print(f"[Anhang] {p.name} nicht entfernbar: {e}", flush=True)
    if weg:
        print(f"[Anhang] {len(weg)} Arbeitskopie(n) nach {ttl} min entfernt", flush=True)
    return weg
