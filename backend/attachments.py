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

**Was dieses Modul kann und was nicht:** Es begrenzt die LEBENSDAUER, nicht die
Sichtbarkeit. Das Fenster schrumpft von "bis zum Reboot" (auf DEV lagen Dateien von
mehreren Tagen in /tmp) auf `ttl_minutes`. Die eigentliche Trennung braucht ein
privates /tmp pro Lauf (Mount-Namespace, `systemd-run -p PrivateTmp=yes` oder
`bwrap --tmpfs /tmp`) – das ist ein eigener Umbau, weil Anhang-Uebergabe und
Ergebnis-Abholung (`agent.py::_deliver_docs` liest aus /tmp) dann ueber ein
pro-Lauf-Verzeichnis laufen muessen.

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


def ttl_minutes() -> int:
    """Frist in Minuten (ENV ``JARVIS_ATTACH_TTL_MIN``, 0 = nie loeschen).

    Eine FUNKTION, keine Modulkonstante: ein beim Import gelesener Wert waere bis zum
    naechsten Dienststart eingefroren (gleiche Begruendung wie
    ``documents.retention_days()``). Deckel 10080 Minuten (7 Tage) – eine laengere
    Frist waere praktisch "bis zum Reboot" und damit der Zustand, der behoben wird.
    """
    try:
        v = int(os.environ.get("JARVIS_ATTACH_TTL_MIN", DEFAULT_TTL_MIN))
    except Exception:  # noqa: BLE001
        return DEFAULT_TTL_MIN
    if v <= 0:
        return 0
    return max(1, min(v, 10080))


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
    try:
        eintraege = list(WORK_DIR.iterdir())
    except Exception as e:  # noqa: BLE001
        print(f"[Anhang] /tmp nicht lesbar: {e}", flush=True)
        return []
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
