"""Sperre fuer ``data/auth_state.json`` – ueber Threads UND Prozesse.

WARUM (Code-Review 2026-11-01): ``auth_state.json`` wird immer GANZ
geschrieben (laden, aendern, ganz zurueckschreiben). Zwei Schreiber, die
denselben Stand laden, loeschen sich gegenseitig die Aenderung. Schreiber gibt
es in ZWEI Prozessen:

* der Dienst (``backend/main.py``: Anmeldung, TOTP, Anmeldeschutz,
  Kennwortwechsel) – mehrere Threads,
* die Root-Konsole des Brokers (``backend/broker/admin.py``: ``totp-aus``,
  ``totp-uebernehmen``) – ein eigener Prozess.

Eine ``threading.RLock`` allein deckt nur den Dienst. Deshalb zusaetzlich
``fcntl.flock`` auf eine Nachbardatei ``auth_state.json.lock``: die Sperre
haengt an der offenen Datei, gilt fuer alle Prozesse auf diesem Rechner und
faellt beim Prozessende von selbst (kein verwaister Sperrzustand nach einem
Absturz). Gesperrt wird nur beim AEUSSERSTEN Eintritt – die Sperre ist
wiedereintrittsfaehig, weil ``_load_auth_state`` innerhalb einer Aenderung
selbst zurueckschreiben kann.

Die Sperrdatei gehoert dem EIGENTUEMER von ``auth_state.json``: legt root sie
zuerst an, uebergibt er sie (sonst saehe der Dienstbenutzer danach eine
root-eigene 0600-Datei und koennte nie wieder sperren – Register: "Deploy
gehoert dem Dienstbenutzer").

Laesst sich die Sperrdatei nicht oeffnen, gilt nur die Thread-Sperre, und das
steht LAUT im Journal: eine Anmeldung zu verweigern, weil eine Hilfsdatei
fehlt, waere der groessere Schaden als der seltene Wettlauf mit der
Root-Konsole.

Nur Standardbibliothek – der Broker laedt das Modul mit dem SYSTEM-Python.
"""
from __future__ import annotations

import os
import threading

try:
    import fcntl
except ImportError:  # pragma: no cover – nur Linux ist Zielsystem
    fcntl = None


def sperrdatei(datei) -> str:
    """Pfad der Sperrdatei neben ``datei``."""
    return str(datei) + ".lock"


class Sperre:
    """Wiedereintrittsfaehige Sperre: Thread-Sperre plus ``flock``.

    ``datei_fn`` liefert den Pfad von ``auth_state.json`` – als Funktion, damit
    ein Test oder eine Umgebungsvariable den Ort nach dem Anlegen umlenken kann.
    """

    def __init__(self, datei_fn):
        self._datei_fn = datei_fn
        self._rlock = threading.RLock()
        self._tiefe = 0
        self._fd = None
        self._gewarnt = False

    def _oeffnen(self):
        datei = self._datei_fn()
        pfad = sperrdatei(datei)
        fd = os.open(pfad, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.geteuid() == 0:
                # Eigentuemer der Daten uebernehmen (siehe Modulkopf).
                try:
                    st = os.stat(datei)
                    fs = os.fstat(fd)
                    if (fs.st_uid, fs.st_gid) != (st.st_uid, st.st_gid):
                        os.fchown(fd, st.st_uid, st.st_gid)
                except FileNotFoundError:
                    pass
            fcntl.flock(fd, fcntl.LOCK_EX)
        except Exception:
            os.close(fd)
            raise
        return fd

    def __enter__(self):
        self._rlock.acquire()
        try:
            if self._tiefe == 0 and fcntl is not None:
                try:
                    self._fd = self._oeffnen()
                except OSError as e:
                    self._fd = None
                    if not self._gewarnt:
                        self._gewarnt = True
                        print("[AUTH] Sperrdatei fuer auth_state.json nicht nutzbar (%s) – "
                              "nur Thread-Sperre, gleichzeitiges Schreiben der Root-Konsole "
                              "ist NICHT ausgeschlossen." % e, flush=True)
            self._tiefe += 1
        except BaseException:
            self._rlock.release()
            raise
        return self

    def __exit__(self, *exc):
        try:
            self._tiefe -= 1
            if self._tiefe == 0 and self._fd is not None:
                fd, self._fd = self._fd, None
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
        finally:
            self._rlock.release()
        return False
