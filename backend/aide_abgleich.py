#!/usr/bin/env python3
"""AIDE-Abgleich: Bericht der taeglichen Pruefung einteilen, neuen Stand nur
uebernehmen, wenn jede Aenderung erklaert ist.

WARUM (gemessen auf ECHT am 24.11.2026)
---------------------------------------
Debian laesst die taegliche Pruefung (``dailyaidecheck.service``) bereits als
``aide --update`` laufen: jede Nacht entstehen ein Bericht
(``/var/log/aide/aide.log``) UND ein neuer Stand (``aide.db.new``). Uebernommen
wird er nie (``COPYNEWDB=no``), und den Bericht liest niemand – ohne MTA geht
keine Mail hinaus. Nach jedem Update meldet AIDE deshalb dieselben Aenderungen
Tag fuer Tag weiter, bis jemand von Hand ``aideinit`` ruft. Genau das waere als
Automatik gefaehrlich: ein blindes Uebernehmen nach jedem Update nimmt einen
Einbruch in den Vergleichsstand mit auf und verwischt ihn.

DIESES MODUL teilt jeden Eintrag des Berichts ein:
  * erklaert durch ein Debian-Paket – die Pruefsumme der Datei ist die, die
    dpkg fuer sie fuehrt (``/var/lib/dpkg/info/*.md5sums``, Conffiles aus
    ``/var/lib/dpkg/status``), oder der Pfad steht in der Dateiliste eines
    Pakets (Verzeichnisse, Links);
  * erklaert durch den Jarvis-Stand – die Datei ist byteweise der Stand der
    root-eigenen, signiert geprueften Broker-Quelle
    (``/var/lib/jarvis-broker/quelle``, ``git verify-commit HEAD`` gegen
    ``/etc/jarvis/allowed_signers``);
  * erklaert durch die Paketverwaltung selbst (ld.so.cache, initramfs, ...),
    aber NUR, wenn dpkg seit dem letzten Stand ueberhaupt gelaufen ist;
  * erklaert, weil sich nichts Inhaltliches geaendert hat (nur die ctime;
    Verzeichnis nur mit Inhaltszeit/Linkzahl – seine Eintraege stehen einzeln);
  * erklaert als Kopie: grub-Module (byteweise die Paketdatei) und die
    Chroot-Kopien von Postfix (``/var/spool/postfix/lib/libnss_*`` byteweise
    die Paketdatei, ``/var/spool/postfix/etc/<datei>`` byteweise die Datei
    unter ``/etc``, die AIDE selbst ueberwacht);
  * erklaert als Laufzeit von Postfix: NEUE Sockets, PID-Dateien, Sperre und
    Verzeichnisse genau nach den Mustern von Debians ``31_aide_postfix`` (dort
    als VarFile/VarDir gefuehrt: Eigentuemer und Rechte werden weiter erfasst),
    nur wenn das Paket postfix seit dem Stand installiert oder aktualisiert
    wurde. Bewusst KEINE Ausnahme in der AIDE-Konfiguration – die schaltete die
    Rechtepruefung dieser Dateien ab (DEV 25.11.2026, ``aide --path-check``);
  * erklaert als Startverweis ``/etc/rcN.d/[SK]NN<name>`` -> ``../init.d/<name>``,
    wenn das Startskript zu einem Paket gehoert und dpkg seit dem Stand lief
    (``update-rc.d`` im Paketskript, DEV 24.11.2026 nach ``apt install postfix``);
  * erklaert, weil Inhalt, Rechte und Eigentuemer gleich blieben (nur mtime/
    ctime/Inode – in Debians Regeln wird ``m`` nur zusammen mit den Pruefsummen
    erfasst, ein fehlendes ``H`` heisst also: gleicher Inhalt);
  * Jarvis-Code mit gruppenbeschreibbaren Rechten (umask 002 eines Pulls per
    ``sudo -u``), wenn der Inhalt der signierte Stand ist und die Gruppe
    niemanden ausser dem Dienstbenutzer enthaelt;
  * Dateien, die der Broker selbst unter /etc/jarvis schreibt, ueber eine
    lueckenlose Kette vermerkter Uebergaenge (backend/eigene_dateien.py);
  * Konten (passwd/group/shadow/gshadow), wenn seit dem Stand dpkg lief und nur
    gesperrte Systemkonten HINZUGEKOMMEN sind – gegen den Kontenstand, der mit
    dem Vergleichsstand festgehalten wurde;
  * Protokollrotation, Arbeitsordner der AIDE-Pruefung, Desktop-Zustand
    (wireplumber), das leere dynamicmaps.cf aus Postfix' Paketskript;
  * nicht erklaert – alles andere.

Sind ALLE erklaert, wird ``aide.db.new`` zum neuen Stand. Sonst bleibt der alte
stehen, der Zustand heisst "offen", und ein Administrator sieht die Liste in der
Oberflaeche und kann sie nach Durchsicht uebernehmen (``uebernehmen``, mit
Kennung: es wird genau die Fassung uebernommen, die er gesehen hat). Die
Ueberwachung (B13) meldet einen offenen Abgleich als Warnung.

⚠ ALS ROOT WIRD IN /opt/jarvis KEIN git AUFGERUFEN. ``.git/config`` gehoert dem
  Dienstbenutzer (``core.fsmonitor`` waere ein Weg zu root), und schon ein
  lesendes ``git status`` schreibt ``.git/index`` als root – danach scheitert
  jedes Update des Dienstbenutzers. Am 24.11.2026 auf ECHT bei der Messung zu
  diesem Modul genau so passiert. Verglichen wird deshalb mit dem Baum der
  root-eigenen Broker-Quelle.

⚠ GRENZE: das venv unter /opt/jarvis/venv gehoert dem Dienstbenutzer, seine
  RECORD-Dateien auch. Eine Erklaerung daraus waere eine, die ein
  kompromittierter Dienstbenutzer selbst schreiben kann – venv-Aenderungen
  bleiben deshalb bewusst "nicht erklaert".

Laeuft als root aus der root-eigenen Broker-Kopie mit dem System-Python, nur
Standardbibliothek (Befund K1):
  * ``--nach-pruefung``: als ``ExecStartPost=+`` von ``dailyaidecheck.service``
    (deploy/security/system_haertung.sh)
  * ``--zeigen``: Zustand als JSON
  * die Broker-Ops ``aide_status``, ``aide_pruefen``, ``aide_uebernehmen``
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Testwurzel (nur Waechter): alle Dateizugriffe laufen dann unter ihr, und der
# erwartete Eigentuemer der Broker-Quelle ist der aufrufende Benutzer.
W = os.environ.get("JARVIS_AIDE_WURZEL", "")

BERICHT = "/var/log/aide/aide.log"
DB = "/var/lib/aide/aide.db"
DB_NEU = "/var/lib/aide/aide.db.new"
ZUSTAND_DIR = "/var/lib/jarvis-aide"
# Die Sicherung des alten Stands liegt im (AIDE-ausgenommenen) Zustandsverzeichnis:
# unter /var/lib/aide machte sie jede folgende Pruefung "offen" (DEV 24.11.2026,
# der einzige nicht erklaerte Eintrag nach einer Uebernahme).
DB_VORHER = ZUSTAND_DIR + "/aide.db.vorher"
ZUSTAND = ZUSTAND_DIR + "/abgleich.json"
BASIS = ZUSTAND_DIR + "/basis.json.gz"
SPERRE = ZUSTAND_DIR + "/.sperre"
# Was zuletzt per Mail gemeldet wurde (Abdruecke bzw. Fehlergrund)
GEMELDET = ZUSTAND_DIR + "/gemeldet.json"
# Kontenstand zum geprueften Bericht; wird bei der Uebernahme Teil der Basis
KONTEN_KANDIDAT = ZUSTAND_DIR + "/konten.kandidat.json"
KONTEN_DATEIEN = ("/etc/passwd", "/etc/group", "/etc/shadow", "/etc/gshadow")
# Shells, mit denen ein neu angelegtes Konto als "kein Anmeldekonto" gilt
_OHNE_ANMELDUNG = ("/usr/sbin/nologin", "/sbin/nologin", "/bin/false", "/usr/bin/false")
DPKG_INFO = "/var/lib/dpkg/info"
DPKG_STATUS = "/var/lib/dpkg/status"
APT_HISTORY = ("/var/log/apt/history.log", "/var/log/apt/history.log.1.gz")
QUELLE = "/var/lib/jarvis-broker/quelle"
SIGNERS = "/etc/jarvis/allowed_signers"
# Installierter Stand: aus den DATEIEN in .git gelesen, nie per git (K1)
JARVIS_GIT = "/opt/jarvis/.git"
# Stellt die Quelle auf einen Commit (--nur-quelle), aus der root-eigenen Broker-Kopie
INSTALLER = "/usr/local/lib/jarvis-broker/deploy/security/broker_installieren.sh"
SSH_KEYGEN = "/usr/bin/ssh-keygen"
GIT = "/usr/bin/git"
PRUEF_UNIT = "dailyaidecheck.service"
# Andere AIDE-Laeufe, neben denen keine Pruefung startet (Speicher, siehe unten)
AIDE_UNITS = (PRUEF_UNIT, "aideinit-haertung.service")
# Code-Baeume, deren Dateien gegen den Baum der Broker-Quelle verglichen werden
CODE_BAEUME = ("/opt/jarvis/", "/usr/local/lib/jarvis-broker/", QUELLE + "/")
# So viele nicht erklaerte Eintraege stehen im Zustand (die Zahl immer ganz)
OFFEN_MAX = 500
# Eine AIDE-Pruefung brauchte auf ECHT bis 7,6 GB (24.11.2026, 16 GB RAM, ohne
# Swap seit D5). Darunter startet der Knopf keine Pruefung.
MIN_FREI_KB = 8 * 1024 * 1024

# Dateien, die die Paketverwaltung beim Einspielen selbst erzeugt (Trigger,
# Caches, initramfs). Erklaert nur, wenn dpkg seit dem letzten Stand lief.
_PAKETVERWALTUNG = re.compile(
    r"^(?:/etc/ld\.so\.cache$|/var/cache/ldconfig/|/usr/share/info/dir(?:\.old)?$"
    r"|/var/lib/dpkg/|/var/cache/debconf/|/var/lib/ucf/|/var/cache/man/"
    r"|/boot/initrd\.img-[^/]+$|/(?:usr/)?lib/modules/[^/]+/modules\.[^/]+$"
    r"|/var/lib/initramfs-tools/|/var/log/apt/|/var/lib/apt/|/var/cache/apt/"
    r"|/etc/alternatives/|/var/lib/dpkg/alternatives/|/etc/ssl/certs/"
    r"|/usr/share/mime/|/usr/share/glib-2\.0/schemas/gschemas\.compiled$"
    r"|/usr/share/icons/[^/]+/icon-theme\.cache$|/usr/lib/[^/]+/gdk-pixbuf-2\.0/[^/]+/loaders\.cache$"
    r"|/usr/lib/[^/]+/gio/modules/giomodule\.cache$|/var/lib/systemd/deb-systemd-"
    r"|/etc/systemd/system/[^/]+\.wants/|/var/lib/polkit-1/|/usr/share/applications/mimeinfo\.cache$"
    r"|/var/lib/dbus/|/etc/fonts/|/var/cache/fontconfig/)")
_PYC = re.compile(r"^(?P<dir>.*)/__pycache__/(?P<name>[^/]+?)\.cpython-\d+(?:\.opt-\d)?\.pyc$")
_ABSCHNITT = re.compile(r"^(Added|Removed|Changed) entries:\s*$")
_ARTEN = {"Added": "neu", "Removed": "entfernt", "Changed": "geaendert"}
_SUMME = re.compile(r"^\s+(Added|Removed|Changed) entries:\s+(\d+)\s*$")
_DETAIL_KOPF = re.compile(r"^(?:File|Directory|Link|Socket|FIFO|Block device|Character device|Door|Port): (/.*)$")
_DETAIL_MERKMAL = re.compile(r"^ ([A-Za-z0-9]+)\s*: (.*)$")
_DETAIL_WEITER = re.compile(r"^ {5,}(\S*)\s*\|\s*(\S*)\s*$")


def _p(pfad: str) -> Path:
    return Path(W + pfad) if W else Path(pfad)


def _jetzt() -> float:
    return time.time()


def _protokoll(text: str) -> None:
    """Eine Zeile ins Journal (Kennung jarvis-aide) – im Testmodus nur stdout."""
    print(text, flush=True)
    if W:
        return
    try:
        subprocess.run(["logger", "-t", "jarvis-aide", "-p", "daemon.notice", text],
                       timeout=10, check=False)
    except Exception:  # noqa: BLE001
        pass


# ── Bericht ──────────────────────────────────────────────────────────────────

def _zeitstempel(text: str) -> float | None:
    """``2026-11-24 02:45:59 +0100 (AIDE 0.19.1)`` -> Epoche."""
    m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ([+-]\d{4})", text.strip())
    if not m:
        return None
    try:
        return _epoche(m.group(1), m.group(2))
    except (ValueError, OverflowError):
        return None


def _epoche(lokal: str, versatz: str) -> float:
    """Ortszeit mit ausdruecklichem Versatz -> Epoche (unabhaengig von der TZ
    des Prozesses: ``time.mktime`` wuerde sie anwenden)."""
    import calendar
    t = calendar.timegm(time.strptime(lokal, "%Y-%m-%d %H:%M:%S"))
    vz = 1 if versatz[0] == "+" else -1
    return t - vz * (int(versatz[1:3]) * 3600 + int(versatz[3:5]) * 60)


def bericht_lesen(text: str) -> dict:
    """Eintraege eines AIDE-Berichts (``aide --update``/``--check``).

    ``vollstaendig`` nur mit End-Zeile UND wenn die Zahl der gelesenen
    Eintraege je Art der Zusammenfassung entspricht – ein abgeschnittener oder
    anders aufgebauter Bericht darf nie als "nichts gefunden" gelten.
    """
    erg = {"start": None, "ende": None, "eintraege": [], "summe": {}, "vollstaendig": False,
           "ohne_aenderung": False, "sha256": {}}
    abschnitt = None
    # Detailangaben: "File: /pfad", darunter " SHA256    : alt | neu" und
    # Fortsetzungszeilen (base64 ueber zwei Zeilen umbrochen, ECHT 25.11.2026)
    # EINE Bedingung fuer "wir sind in den Detailangaben": gesetzt von der
    # Kopfzeile "Detailed information", beendet von "The attributes of the"
    # (danach stehen die Pruefsummen von aide.db) und vom Ende.
    in_details, detail, sha_teile, in_sha = False, None, None, False
    for zeile in text.splitlines():
        md = _DETAIL_KOPF.match(zeile) if in_details else None
        if md:
            detail, in_sha = md.group(1), False
            continue
        if in_details and detail is not None:
            ma = _DETAIL_MERKMAL.match(zeile)
            if ma:
                in_sha = ma.group(1) == "SHA256"
                if in_sha:
                    sha_teile = erg["sha256"].setdefault(detail, ["", ""])
                    links, _, rechts = ma.group(2).partition("|")
                    sha_teile[0] += links.strip()
                    sha_teile[1] += rechts.strip()
                continue
            mf = _DETAIL_WEITER.match(zeile)
            if in_sha and mf:
                sha_teile[0] += mf.group(1).strip()
                sha_teile[1] += mf.group(2).strip()
                continue
            in_sha = False
        if zeile.startswith("Start timestamp:"):
            erg["start"] = _zeitstempel(zeile.split(":", 1)[1])
            continue
        if zeile.startswith("End timestamp:"):
            erg["ende"] = _zeitstempel(zeile.split(":", 1)[1])
            abschnitt, in_details = None, False
            continue
        m = _SUMME.match(zeile)
        if m:
            erg["summe"][_ARTEN[m.group(1)]] = int(m.group(2))
            continue
        m = _ABSCHNITT.match(zeile)
        if m:
            abschnitt = _ARTEN[m.group(1)]
            continue
        if zeile.startswith(("Detailed information", "The attributes of the")):
            # "File: /..." und " Linkname : /ziel" tragen ": /" und zaehlten
            # sonst als Eintrag; nach den Datenbank-Attributen gehoeren
            # SHA256-Zeilen zu aide.db, nicht zur letzten Datei.
            abschnitt = None
            in_details = zeile.startswith("Detailed information")
            continue
        if "AIDE found NO differences" in zeile:
            erg["ohne_aenderung"] = True
        if abschnitt and ": /" in zeile:
            attrs, pfad = zeile.split(": ", 1)
            erg["eintraege"].append({"art": abschnitt, "attrs": attrs.rstrip(), "pfad": pfad})
    gezaehlt = {a: 0 for a in _ARTEN.values()}
    for e in erg["eintraege"]:
        gezaehlt[e["art"]] += 1
    passt = all(gezaehlt[a] == erg["summe"].get(a, 0) for a in gezaehlt)
    erg["vollstaendig"] = erg["ende"] is not None and (passt or (erg["ohne_aenderung"] and not erg["eintraege"]))
    return erg


def _merkmale(attrs: str) -> tuple[str, set, bool]:
    """(Typ, geaenderte Merkmale, Groesse geaendert) aus ``f >b... mc..H.. .``."""
    typ = attrs[:1]
    rest = attrs[1:]
    return typ, {c for c in rest if c.isalpha()}, (">" in rest or "<" in rest)


# ── Wissen ueber das System ──────────────────────────────────────────────────

def _md5_datei(pfad: Path) -> str | None:
    try:
        h = hashlib.md5(usedforsecurity=False)  # dpkg fuehrt md5, verglichen wird damit
        with open(pfad, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None


def _sha256_datei(pfad: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(pfad, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None


def _git_blob(pfad: Path) -> str | None:
    try:
        daten = pfad.read_bytes()
    except OSError:
        return None
    return hashlib.sha1(b"blob %d\0" % len(daten) + daten, usedforsecurity=False).hexdigest()  # git-Blob-Kennung


def dpkg_laden() -> dict:
    """Pruefsummen, Dateilisten, Conffiles und Versionen aus der dpkg-Datenbank."""
    md5, liste, conff, versionen, liste_n = {}, {}, {}, {}, {}
    info = _p(DPKG_INFO)
    for f in sorted(info.glob("*.md5sums")):
        paket = f.name[:-len(".md5sums")].split(":")[0]
        try:
            for z in f.read_text(errors="replace").splitlines():
                teile = z.split("  ", 1)
                if len(teile) == 2:
                    md5["/" + teile[1]] = (teile[0], paket)
        except OSError:
            continue
    for f in sorted(info.glob("*.list")):
        paket = f.name[:-len(".list")].split(":")[0]
        try:
            for z in f.read_text(errors="replace").splitlines():
                if z.startswith("/"):
                    liste.setdefault(z, paket)
                    liste_n[z] = liste_n.get(z, 0) + 1
        except OSError:
            continue
    try:
        status = _p(DPKG_STATUS).read_text(errors="replace")
    except OSError:
        status = ""
    for block in status.split("\n\n"):
        name = ver = ""
        installiert = False
        in_conf = False
        for z in block.splitlines():
            if z.startswith("Package: "):
                name = z[9:].strip()
            elif z.startswith("Version: "):
                ver = z[9:].strip()
            elif z.startswith("Status: "):
                installiert = z.strip().endswith(" installed")
            elif z.startswith("Conffiles:"):
                in_conf = True
            elif in_conf and z.startswith(" /"):
                teile = z.split()
                if len(teile) >= 2 and "obsolete" not in teile[2:]:
                    conff[teile[0]] = (teile[1], name)
            elif not z.startswith(" "):
                in_conf = False
        if name and installiert:
            versionen[name] = ver
    return {"md5": md5, "liste": liste, "conff": conff, "versionen": versionen, "liste_n": liste_n}


def _root_privat(pfad: Path, maske: int) -> bool:
    """Gewoehnliche Datei/Verzeichnis (kein Link), Eigentuemer root (im
    Testmodus der Aufrufer), keine Rechtebits aus ``maske``."""
    try:
        st = os.lstat(pfad)
    except OSError:
        return False
    eigner = os.getuid() if W else 0
    import stat as _st
    return not _st.S_ISLNK(st.st_mode) and st.st_uid == eigner and (st.st_mode & maske) == 0


def _git(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    umg = {"PATH": "/usr/bin:/bin", "HOME": "/root" if not W else os.environ.get("HOME", "/tmp"),
           "GIT_CONFIG_NOSYSTEM": "1", "LANG": "C", "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run([GIT if not W else "git", "-C", str(_p(QUELLE))] + args,
                          capture_output=True, timeout=timeout, env=umg)


def baum_laden() -> tuple[dict | None, str]:
    """{relativer Pfad: Blob} des signiert geprueften Stands der Broker-Quelle.

    ``None`` mit Grund, wenn die Quelle fehlt, nicht root-eigen ist oder ihre
    Spitze nicht mit einem zugelassenen Schluessel signiert ist – dann erklaert
    der Jarvis-Stand nichts (fail-closed)."""
    q = _p(QUELLE)
    _AUSFUEHRBAR.clear()
    if not (q / ".git").is_dir():
        return None, "keine Broker-Quelle"
    for teil in (q, q / ".git", q / ".git" / "config"):
        if not _root_privat(teil, 0o022):
            return None, "Broker-Quelle nicht root-eigen oder fremd beschreibbar: %s" % teil.name
    signers = _p(SIGNERS)
    if not _root_privat(signers, 0o022):
        return None, "kein Signatur-Anker"
    r = _git(["-c", "gpg.ssh.allowedSignersFile=" + str(signers),
              "-c", "gpg.ssh.program=" + (SSH_KEYGEN if not W else "ssh-keygen"),
              "verify-commit", "HEAD"])
    if r.returncode != 0:
        return None, "Spitze der Broker-Quelle nicht signiert geprueft"
    r = _git(["ls-tree", "-r", "-z", "HEAD"])
    if r.returncode != 0:
        return None, "Baum der Broker-Quelle nicht lesbar"
    baum = {}
    for eintrag in r.stdout.split(b"\0"):
        if b"\t" not in eintrag:
            continue
        kopf, pfad = eintrag.split(b"\t", 1)
        teile = kopf.split()
        if len(teile) == 3 and teile[1] == b"blob":
            baum[pfad.decode("utf-8", "replace")] = teile[2].decode()
            if teile[0] == b"100755":
                _AUSFUEHRBAR.add(pfad.decode("utf-8", "replace"))
    kopf = _git(["rev-parse", "HEAD"])
    return baum, (kopf.stdout.decode().strip()[:12] if kopf.returncode == 0 else "")


_APT_PAKETE = re.compile(r"^(?:Install|Upgrade|Remove|Purge|Reinstall|Downgrade): (.*)$", re.M)
_APT_NAME = re.compile(r"([a-z0-9][a-z0-9+.\-]+)(?::[a-z0-9_\-]+)? \(")


def _dpkg_laeufe() -> list[tuple[float, float]]:
    """(Start, Ende) jedes Blocks in apt/history.log (auch der rotierten Datei)."""
    return [(s, e) for s, e, _ in _apt_bloecke()]


def _apt_bloecke() -> list[tuple[float, float, set]]:
    """(Start, Ende, angefasste Pakete) je Block in apt/history.log."""
    laeufe = []
    for pfad in APT_HISTORY:
        try:
            if pfad.endswith(".gz"):
                with gzip.open(_p(pfad), "rt", errors="replace") as f:
                    text = f.read()
            else:
                text = _p(pfad).read_text(errors="replace")
        except OSError:
            continue
        for block in re.split(r"\n\s*\n", text):
            s = re.search(r"^Start-Date: (.+)$", block, re.M)
            e = re.search(r"^End-Date: (.+)$", block, re.M)
            if not s:
                continue
            try:
                st = time.mktime(time.strptime(" ".join(s.group(1).split()), "%Y-%m-%d %H:%M:%S"))
                en = time.mktime(time.strptime(" ".join(e.group(1).split()), "%Y-%m-%d %H:%M:%S")) if e else st
            except ValueError:
                continue
            pakete = set()
            for zeile in _APT_PAKETE.findall(block):
                pakete.update(_APT_NAME.findall(zeile))
            laeufe.append((st, en, pakete))
    return laeufe


def basis_lesen() -> dict | None:
    try:
        with gzip.open(_p(BASIS), "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def basis_schreiben(dp: dict, zeit: float, konten: dict | None = None) -> None:
    """Paketstand zum Zeitpunkt des uebernommenen Stands – damit laesst sich
    beim naechsten Mal ein ENTFERNTER Pfad einem aktualisierten Paket zuordnen
    (dpkg kennt entfernte Dateien danach nicht mehr)."""
    ziel = _p(BASIS)
    ziel.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = ziel.with_name(ziel.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({"zeit": zeit, "versionen": dp["versionen"], "pfade": dp["liste"], "konten": konten}, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, ziel)


# Ausfuehrbare Dateien des signierten Stands (Modus 100755), gefuellt von baum_laden
_AUSFUEHRBAR: set = set()

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REF = re.compile(r"^ref: (refs/heads/[A-Za-z0-9._/-]{1,200})$")


def _klein_lesen(pfad: Path, grenze: int = 4 << 20) -> str | None:
    """Gewoehnliche Datei ohne Link am Ende, hoechstens ``grenze`` Bytes."""
    import stat as _st
    try:
        fd = os.open(pfad, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not _st.S_ISREG(st.st_mode) or st.st_size > grenze:
            return None
        return os.read(fd, grenze).decode("ascii", "replace")
    finally:
        os.close(fd)


def installierter_stand() -> str | None:
    """Commit, der unter /opt/jarvis installiert ist – oder None.

    ⚠ OHNE git: ``.git`` gehoert dem Dienstbenutzer, ein git-Aufruf als root
    darin waere ein Weg zu root (Befund K1, Kopf dieser Datei). Gelesen werden
    nur HEAD, die Ref-Datei bzw. packed-refs, und angenommen wird nur eine
    Kennung aus 40 Hex-Zeichen – ein umgebogener Verweis kann damit nichts
    preisgeben, hoechstens auf einen anderen Commit zeigen, und der muss dann
    selbst signiert sein, um etwas zu erklaeren."""
    g = _p(JARVIS_GIT)
    try:
        if os.path.islink(g) or not g.is_dir():
            return None
    except OSError:
        return None
    head = (_klein_lesen(g / "HEAD", 4096) or "").strip()
    if _SHA.match(head):
        return head
    m = _REF.match(head)
    if not m or ".." in m.group(1):
        return None
    ref = m.group(1)
    wert = (_klein_lesen(g / ref, 4096) or "").strip()
    if _SHA.match(wert):
        return wert
    for zeile in (_klein_lesen(g / "packed-refs") or "").splitlines():
        teile = zeile.strip().split(" ")
        if len(teile) == 2 and teile[1] == ref and _SHA.match(teile[0]):
            return teile[0]
    return None


def quelle_nachziehen() -> dict:
    """Stellt die signierte Quelle auf den INSTALLIERTEN Commit, bevor eingeteilt wird.

    WARUM (2026-11-25): bis dahin zog nur ein Broker-Start die Quelle nach. Ein
    Update ohne Broker-Pfad (Update-Pille, Auto-Update, Pull von Hand) liess sie
    auf dem alten Commit stehen, und jede Datei des neuen erschien in der Nacht
    als "nicht erklaert" (ECHT nach eaa8e036, DEV nach jedem c+p). Verglichen
    wird gegen den installierten Commit, nicht gegen die Spitze von master:
    ein Server, der hinterherhinkt, ist kein Befund.

    Der Installer prueft die Signatur selbst; scheitert er, bleibt es beim
    fail-closed-Verhalten von ``baum_laden`` (nichts erklaert, Grund genannt)."""
    soll = installierter_stand()
    if not soll:
        return {"ok": False, "grund": "installierter Stand nicht lesbar"}
    ist = ""
    if (_p(QUELLE) / ".git").is_dir():
        r = _git(["rev-parse", "HEAD"])
        ist = r.stdout.decode().strip() if r.returncode == 0 else ""
    if ist == soll:
        return {"ok": True, "stand": soll[:12], "nachgezogen": False}
    inst = _p(INSTALLER)
    if not _root_privat(inst, 0o022):
        return {"ok": False, "grund": "Installer fehlt oder ist nicht root-eigen", "stand": soll[:12]}
    umg = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"}
    if W:
        umg = dict(os.environ, LANG="C", LC_ALL="C")
    try:
        r = subprocess.run(["/bin/bash", str(inst), "--nur-quelle", soll], capture_output=True,
                           timeout=180, env=umg)
    except (OSError, subprocess.TimeoutExpired) as ex:
        return {"ok": False, "grund": "Installer: %s" % ex, "stand": soll[:12]}
    if r.returncode != 0:
        letzte = ((r.stderr or r.stdout).decode("utf-8", "replace").strip().splitlines() or ["?"])[-1]
        return {"ok": False, "grund": letzte[:200], "stand": soll[:12]}
    return {"ok": True, "stand": soll[:12], "nachgezogen": True, "von": ist[:12]}


def kontext_laden(basis_zeit: float | None) -> dict:
    dp = dpkg_laden()
    qn = quelle_nachziehen()
    if qn.get("nachgezogen") or not qn.get("ok"):
        _protokoll("AIDE-Abgleich: Quelle %s" % (
            "auf den installierten Stand %s nachgezogen (vorher %s)" % (qn.get("stand"), qn.get("von") or "-")
            if qn.get("ok") else "NICHT nachgezogen: %s" % qn.get("grund")))
    baum, baum_info = baum_laden()
    basis = basis_lesen()
    if basis_zeit is None and basis:
        basis_zeit = basis.get("zeit")
    bloecke = _apt_bloecke()
    laeufe = [(s, e) for s, e, _ in bloecke]
    seit = set()
    for _, e, pakete in bloecke:
        if basis_zeit is not None and e >= basis_zeit:
            seit |= pakete
    return {"dpkg": dp, "baum": baum, "baum_info": baum_info, "basis": basis, "quelle_nachziehen": qn,
            "basis_zeit": basis_zeit, "laeufe": laeufe, "pakete_seit": seit,
            "dpkg_seit_basis": basis_zeit is not None and any(e >= basis_zeit for _, e in laeufe)}


# ── Einteilen ────────────────────────────────────────────────────────────────

def _code_rel(pfad: str) -> str | None:
    for wurzel in CODE_BAEUME:
        if pfad.startswith(wurzel):
            return pfad[len(wurzel):]
    return None


# grub-install kopiert Module, Sprachdateien und Schrift aus den Paketen nach
# /boot/grub (gemessen auf DEV 24.11.2026: 333 Eintraege nach einem grub-Update).
# Erklaert ist eine solche Datei nur, wenn sie BYTEWEISE die Paketdatei ist.
# grub.cfg und grubenv bleiben bewusst draussen: sie sind ein Startweg, den
# kein Paket vorgibt.
_GRUB_MODUL = re.compile(r"^/boot/grub/(?P<plattform>[a-z0-9_]+-[a-z0-9]+)/(?P<datei>[^/]+)$")
_GRUB_SPRACHE = re.compile(r"^/boot/grub/locale/(?P<sprache>[^/]+)\.mo$")


def _kopie_quelle(pfad: str) -> str | None:
    m = _GRUB_MODUL.match(pfad)
    if m:
        return "/usr/lib/grub/%s/%s" % (m.group("plattform"), m.group("datei"))
    m = _GRUB_SPRACHE.match(pfad)
    if m:
        return "/usr/share/locale/%s/LC_MESSAGES/grub.mo" % m.group("sprache")
    if pfad == "/boot/grub/fonts/unicode.pf2":
        return "/usr/share/grub/unicode.pf2"
    return None


# Chroot von Postfix (DEV 24.11.2026, gemessen nach ``apt install postfix``):
# /usr/lib/postfix/configure-instance.sh kopiert bei jedem Start die Dateien
# unten aus /etc und die NSS-Module aus /usr/lib/<multiarch>/ nach
# /var/spool/postfix. Die Liste ist die des Skripts – fail-closed: was nicht
# darauf steht, wird nicht erklaert.
_POSTFIX_ETC = re.compile(r"^/var/spool/postfix/etc/(?P<datei>localtime|services|resolv\.conf|hosts"
                          r"|host\.conf|nsswitch\.conf|nss_mdns\.config)$")
_POSTFIX_LIB = re.compile(r"^/var/spool/postfix/lib/(?P<datei>libnss_[A-Za-z0-9_]+\.so\.2)$")
# Laufzeit von Postfix: die Muster von Debians /etc/aide/aide.conf.d/31_aide_postfix
# (DEV 25.11.2026), dort mit VarFile/VarDir – erfasst werden Eigentuemer/Rechte,
# nicht Inhalt und Zeit. Erklaert wird damit nur das ERSTE Auftauchen nach einer
# Installation bzw. einem Update von postfix. Erwartete Dateiart je Muster.
_POSTFIX_LAUFZEIT = (
    (re.compile(r"^/var/lib/postfix/(?:master\.lock|prng_exch|smtpd?_scache\.db)$"), "f"),
    (re.compile(r"^/var/spool/postfix/pid/(?:master\.pid|(?:inet|unix)\..+)$"), "f"),
    (re.compile(r"^/var/spool/postfix/(?:private|public)/[a-z][a-z0-9-]*$"), "s"),
    # Syslog-Socket im Chroot: legt rsyslog ueber die Postfix-Einstellung an
    # (ECHT 25.11.2026: "neu, gehoert keinem Paket"); Debians Regeln kennen ihn nicht.
    (re.compile(r"^/var/spool/postfix/dev/log$"), "s"),
    (re.compile(r"^/var/spool/postfix/(?:active|corrupt|defer(?:red)?|hold|saved|bounce|flush|incoming"
                r"|maildrop|trace|private|public|pid|dev|etc|lib|usr|usr/lib|usr/lib/sasl2)$"), "d"),
    (re.compile(r"^/var/spool/postfix$"), "d"),
    (re.compile(r"^/var/lib/postfix$"), "d"),
)
# Startverweise (System V), angelegt von update-rc.d im Paketskript
# Laufzeit-Sockets, die bei jedem Start NEU angelegt werden (neue Inode, neue
# Zeiten) und fuer die Debian keine Regel ohne Inode fuehrt: nach einem Neustart
# von rsyslog stuende der Syslog-Socket sonst jede Nacht als "geaendert" da.
# Erklaert nur, wenn sich NICHTS ausser Zeit/Inode/Linkzahl geaendert hat –
# Rechte und Eigentuemer bleiben ein Befund (Regel davor in einteilen).
_SOCKET_NEU_ANGELEGT = re.compile(r"^/var/spool/postfix/dev/log$")
_RC_LINK = re.compile(r"^/etc/rc[0-6S]\.d/[SK]\d\d(?P<name>[A-Za-z0-9][A-Za-z0-9._+-]*)$")


def _postfix_kopie(pfad: str, k: dict) -> str | None:
    """Grund, wenn ``pfad`` eine byteweise Kopie aus dem Postfix-Chroot ist."""
    m = _POSTFIX_LIB.match(pfad)
    if m:
        ist = _md5_datei(_p(pfad))
        if ist is None:
            return None
        ende = "/" + m.group("datei")
        for quelle, (soll, paket) in k["dpkg"]["md5"].items():
            # nur /usr/lib/<multiarch>/<datei> bzw. /lib/<multiarch>/<datei>
            if quelle.endswith(ende) and soll == ist and \
                    re.match(r"^/(?:usr/)?lib/[^/]+/[^/]+$", quelle):
                return "Paket %s (Postfix-Kopie von %s)" % (paket, quelle)
        return None
    m = _POSTFIX_ETC.match(pfad)
    if m:
        quelle = "/etc/" + m.group("datei")
        ist = _sha256_datei(_p(pfad))
        return ("Postfix-Kopie von %s" % quelle) if ist is not None and ist == _sha256_datei(_p(quelle)) else None
    return None


def _postfix_laufzeit(art: str, typ: str, pfad: str, k: dict) -> str | None:
    """Neue Laufzeitdatei von Postfix nach einer Installation/einem Update."""
    if art != "neu" or not k.get("dpkg_seit_basis") or "postfix" not in k["dpkg"]["versionen"] \
            or not _paket_geaendert(k, "postfix"):
        return None
    for muster, soll_typ in _POSTFIX_LAUFZEIT:
        if muster.match(pfad):
            return "Laufzeit von Postfix (installiert/aktualisiert)" if typ == soll_typ else None
    return None


def _rc_verweis(art: str, typ: str, pfad: str, k: dict) -> str | None:
    """Grund fuer einen Startverweis, den ein Paketskript angelegt bzw. mit
    einem Update entfernt hat. Nur nach einem dpkg-Lauf seit dem Stand."""
    m = _RC_LINK.match(pfad)
    if not m or not k.get("dpkg_seit_basis"):
        return None
    skript = "/etc/init.d/" + m.group("name")
    if art == "neu":
        paket = k["dpkg"]["liste"].get(skript)
        if typ != "l" or not paket:
            return None
        try:
            ziel = os.readlink(_p(pfad))
        except OSError:
            return None
        return ("Startverweis auf %s (Paket %s)" % (skript, paket)) if ziel == "../init.d/" + m.group("name") else None
    if art == "entfernt":
        alt = ((k.get("basis") or {}).get("pfade") or {}).get(skript)
        return ("Startverweis entfernt mit Update von %s" % alt) if alt and _paket_geaendert(k, alt) else None
    return None


def _paket_geaendert(k: dict, paket: str) -> bool:
    """Wurde ``paket`` seit dem Vergleichsstand installiert, aktualisiert oder
    entfernt? Mit Basis ueber die Versionen; OHNE Basis (Vergleichsstand aus
    aideinit, ECHT 25.11.2026) ueber apt/history.log seit dem Stand. Bis dahin
    galt ohne Basis JEDES Paket als geaendert (None != Version) – fail-open."""
    b = k.get("basis") or {}
    if isinstance(b.get("versionen"), dict):
        return b["versionen"].get(paket) != k["dpkg"]["versionen"].get(paket)
    return paket in (k.get("pakete_seit") or ())


# ── Konten ───────────────────────────────────────────────────────────────────

def _konten_zeilen(text: str, art: str) -> dict:
    """{Name: Felder} – Kennwortfelder nur als Pruefsumme plus "gesperrt"."""
    erg = {}
    for z in text.splitlines():
        if not z or z.startswith("#"):
            continue
        f = z.split(":")
        if art in ("shadow", "gshadow") and len(f) > 1:
            pw = f[1]
            f[1] = [hashlib.sha256(pw.encode("utf-8", "replace")).hexdigest()[:16],
                    pw.startswith(("!", "*"))]
        erg[f[0]] = f[1:]
    return erg


def _konten_art(pfad: str) -> str | None:
    basis = pfad[:-1] if pfad.endswith("-") else pfad
    return basis.rsplit("/", 1)[-1] if basis in KONTEN_DATEIEN else None


def konten_lesen() -> dict | None:
    """Kontenstand (Namen, IDs, Shells, Mitglieder; Kennwoerter nur als
    Pruefsumme). None, wenn eine Datei fehlt – dann erklaert er nichts."""
    erg = {}
    for pfad in KONTEN_DATEIEN:
        try:
            erg[pfad.rsplit("/", 1)[-1]] = _konten_zeilen(_p(pfad).read_text(errors="replace"),
                                                         pfad.rsplit("/", 1)[-1])
        except OSError:
            return None
    return erg


def _konten_erklaert(pfad: str, k: dict) -> str | None:
    """passwd/group/shadow/gshadow (auch die "-"-Sicherung): erklaert, wenn
    seit dem Stand dpkg lief, KEIN bestehender Eintrag sich geaendert hat oder
    verschwunden ist und nur gesperrte Systemkonten bzw. Systemgruppen ohne
    fremde Mitglieder hinzukamen (Paketskripte: postfix/postdrop, ECHT 24.11.)."""
    art = _konten_art(pfad)
    alt = ((k.get("basis") or {}).get("konten") or {})
    if art is None or not k.get("dpkg_seit_basis") or not all(a in alt for a in ("passwd", "group")) \
            or art not in alt:
        return None
    try:
        jetzt = _konten_zeilen(_p(pfad).read_text(errors="replace"), art)
        pw_jetzt = _konten_zeilen(_p("/etc/passwd").read_text(errors="replace"), "passwd")
    except OSError:
        return None
    neue_konten = set()
    for name, f in pw_jetzt.items():
        if name in alt["passwd"]:
            continue
        try:
            uid = int(f[1])
        except (ValueError, IndexError):
            return None
        if not (0 < uid < 1000) or f[-1] not in _OHNE_ANMELDUNG:
            return None
        neue_konten.add(name)
    for name, f in alt[art].items():
        if jetzt.get(name) != f:
            return None
    for name in set(jetzt) - set(alt[art]):
        f = jetzt[name]
        if art == "passwd" and name not in neue_konten:
            return None
        if art == "shadow" and (name not in neue_konten or not f[0][1]):
            return None
        if art == "group":
            try:
                gid = int(f[1])
            except (ValueError, IndexError):
                return None
            mitglieder = {m for m in (f[2] if len(f) > 2 else "").split(",") if m}
            if not (0 < gid < 1000) or not mitglieder <= neue_konten:
                return None
        if art == "gshadow":
            mitglieder = {m for x in f[1:3] for m in (x or "").split(",") if m} if len(f) >= 3 else set()
            if not f[0][1] or not mitglieder <= neue_konten:
                return None
    return "Konten: nur gesperrte Systemkonten aus Paketskripten hinzugekommen"


# ── Rotation, Arbeitsordner, eigene Dateien ──────────────────────────────────

# Protokolle, fuer die Debian keine Regel fuehrt und die deshalb unter "Full"
# fallen – sie werden bei jedem Start bzw. jeder Rotation neu geschrieben
# (gemessen ECHT 25.11.2026). Erklaert wird nur der INHALT: Rechte, Eigentuemer
# und Dateiart prueft die Regel davor in einteilen.
_LOG_ROTATION = re.compile(
    r"^/var/log/(?:boot\.log(?:\.\d+)?|Xorg\.\d+\.log(?:\.old)?|lynis\.log|lynis-report\.dat"
    r"|vmware-[A-Za-z0-9-]+(?:\.\d+)?\.log|jarvis-websockify\.log(?:\.\d+)?"
    r"|unattended-upgrades/unattended-upgrades(?:-dpkg|-shutdown)?\.log(?:\.\d+(?:\.gz)?)?"
    r"|aide/aide\.log\.\d+(?:\.gz)?"
    # DEV 26.11.2026: Anmeldedatenbank (wtmpdb, jede Anmeldung) und das
    # Zugriffsprotokoll von cups (rotiert woechentlich)
    r"|wtmp\.db|cups/access_log(?:\.\d+)?)$")
# Debians naechtliche Sicherung der Paketdatenbank (dpkg-db-backup.timer, 00:00):
# rotiert jede Nacht die Serie .0 -> .1.gz -> ... -> .6.gz und faellt am Ende
# weg. Gemessen DEV 26.11.2026 (dpkg.status/arch/diversions/statoverride);
# alternatives.tar und apt.extended_states gehoeren zur selben Rotation.
_DPKG_SICHERUNG = re.compile(
    r"^/var/backups/(?:dpkg\.(?:status|arch|diversions|statoverride)|alternatives\.tar|apt\.extended_states)"
    r"\.\d+(?:\.gz)?$")
# Sicherungen, die deploy/dev_reset.sh vor einem Zuruecksetzen anlegt (DEV)
_DEV_SICHERUNG = re.compile(r"^/root/dev-abweichungen-\d{8}-\d{6}-\d+\.tgz$")
# Rotierte Fassungen: tauchen bei jeder Rotation neu auf bzw. fallen am Ende weg
_LOG_SERIE = re.compile(r"^/var/log/(?:[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+?(?:\.log)?\.\d+(?:\.gz)?$")
# dailyaidecheck benennt einen liegengebliebenen Arbeitsordner um (Debians
# Regel nimmt nur den aktuellen Ordner aus)
_AIDE_ALTORDNER = re.compile(r"^/var/lib/aide/dailyaidecheck\.old\.[A-Za-z0-9]+"
                             r"(?:/dailyaidecheck(?:/(?:errorlog|arunlog|aerrlog|mailfile))?)?$")
_WIREPLUMBER = re.compile(r"^/home/[^/]+/\.local/state/wireplumber/[^/]+$")
DYNAMICMAPS = "/etc/postfix/dynamicmaps.cf"


def _eigentuemer(pfad: str) -> tuple[int, int, int] | None:
    try:
        st = os.lstat(_p(pfad))
    except OSError:
        return None
    return st.st_uid, st.st_gid, st.st_mode


def _ohne_ausfuehrung(pfad: str) -> bool:
    """Gewoehnliche Datei, kein x-/s-Bit, nicht fuer alle beschreibbar."""
    import stat as _st
    e = _eigentuemer(pfad)
    return e is not None and _st.S_ISREG(e[2]) and (e[2] & 0o7113) == 0


def _root_konto(uid: int) -> bool:
    """root – im Sandkasten (W) der Pruefer selbst."""
    return uid == (os.getuid() if W else 0)


def _root_gruppe(gid: int) -> bool:
    return gid == (os.getgid() if W else 0)


def _root_ablage(pfad: str) -> bool:
    """Gewoehnliche Datei von root, ohne x-/s-Bit, fuer niemanden sonst
    beschreibbar – so legen dpkg-db-backup und dev_reset ihre Sicherungen an."""
    import stat as _st
    e = _eigentuemer(pfad)
    return e is not None and _st.S_ISREG(e[2]) and _root_konto(e[0]) and (e[2] & 0o7133) == 0


def _aide_benutzer(uid: int) -> bool:
    if W:
        return uid == os.getuid()
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name == "_aide"
    except (KeyError, ImportError):
        return False


def _ed():
    try:
        from backend import eigene_dateien  # type: ignore
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import eigene_dateien  # type: ignore
    return eigene_dateien


def _eigene_erklaert(e: dict, k: dict) -> str | None:
    """Vom Broker selbst geschriebene Datei unter /etc/jarvis: lueckenlose
    Kette vermerkter Uebergaenge von der Pruefsumme in aide.db zur neuen."""
    try:
        ed = _ed()
    except Exception:  # noqa: BLE001
        return None
    pfad, art = e["pfad"], e["art"]
    if pfad not in ed.PFADE or art not in ("neu", "geaendert"):
        return None
    if art == "neu":
        alt, neu = None, ed.sha(_p(pfad))
    else:
        teile = (k.get("sha256") or {}).get(pfad)
        if not teile:
            return None
        alt, neu = ed.aus_aide(teile[0]), ed.aus_aide(teile[1])
        if alt is None or neu is None:
            return None
    return "vom Broker geschrieben (vermerkt)" if ed.erklaert(pfad, alt, neu) else None


def _code_rechte(pfad: str, rel: str, merkmale: set, k: dict) -> str | None:
    """Jarvis-Code unter /opt/jarvis, dessen Rechte sich geaendert haben.

    WARUM (ECHT 25.11.2026): ein Pull per ``sudo -u jarvis git pull`` laeuft
    mit der umask aus pam_umask (eigene Gruppe -> 002), die Update-Pille im
    Dienst mit 022. Jede so geschriebene Datei stand danach mit 664/775 als
    "Rechte oder Eigentuemer geaendert" da (23 Eintraege). Erklaert ist das
    NUR, wenn: der Inhalt der signierte Stand ist, Eigentuemer/Gruppe gleich
    blieben, die Rechte 644/664 bzw. 755/775 nach dem Modus im signierten
    Stand sind (kein s-Bit, nichts fuer alle beschreibbar), die Gruppe die
    Primaergruppe des Eigentuemers ist und KEINE weiteren Mitglieder hat
    (Schreibrecht der Gruppe ist dann keines fuer jemand anderen) und keine
    erweiterte ACL besteht."""
    import stat as _st
    # Die signierte Broker-Quelle (root-eigen, umask 022): ihre Dateien stehen
    # nach dem Nachziehen mit GENAU dem Modus des signierten Stands da. DEV
    # 26.11.2026: die Quelle stammte vom 29.09. und trug alle Skripte mit 644;
    # das erste Nachziehen setzte die 18 Dateien mit 100755 im Stand auf 755,
    # und jede davon stand als "Rechte oder Eigentuemer geaendert" in der Mail.
    in_quelle = pfad.startswith(QUELLE + "/")
    # H (Inhalt) ist erlaubt – ihn deckt der Vergleich mit dem signierten Blob
    if not (pfad.startswith("/opt/jarvis/") or in_quelle) or merkmale - {"p", "A", "H", "m", "c", "i", "b", "n"}:
        return None
    baum = k.get("baum")
    if not baum or not baum.get(rel) or baum.get(rel) != _git_blob(_p(pfad)):
        return None
    e = _eigentuemer(pfad)
    if e is None or not _st.S_ISREG(e[2]):
        return None
    uid, gid, modus = e
    if in_quelle:
        # Nur root:root und nur der Modus des Stands – keine umask-002-Toleranz
        if not (_root_konto(uid) and _root_gruppe(gid)) or \
                (modus & 0o7777) != (0o755 if rel in _AUSFUEHRBAR else 0o644):
            return None
        try:
            os.getxattr(_p(pfad), "system.posix_acl_access", follow_symlinks=False)
            return None   # erweiterte ACL vorhanden
        except OSError:
            pass
        return "Jarvis-Stand (signierte Quelle; Rechte wie im Stand)"
    erlaubt = (0o755, 0o775) if rel in _AUSFUEHRBAR else (0o644, 0o664)
    if (modus & 0o7777) not in erlaubt:
        return None
    if modus & 0o020:
        try:
            import grp
            import pwd
            if pwd.getpwuid(uid).pw_gid != gid or grp.getgrgid(gid).gr_mem:
                return None
        except (KeyError, ImportError):
            return None
    try:
        os.getxattr(_p(pfad), "system.posix_acl_access", follow_symlinks=False)
        return None   # erweiterte ACL vorhanden
    except OSError:
        pass
    return "Jarvis-Stand (signiert; Rechte nach umask %s)" % ("002" if modus & 0o020 else "022")


def _mail_erklaert(pfad: str) -> bool:
    """Datei, die backend/mail_meldung.py geschrieben hat – byteweise genau
    der dort vermerkte Stand (Pruefsumme). Ohne das Modul: nie erklaert."""
    try:
        try:
            from backend import mail_meldung  # type: ignore
        except ImportError:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import mail_meldung  # type: ignore
    except Exception:  # noqa: BLE001
        return False
    if W and not mail_meldung.W:
        return False
    return mail_meldung.erklaert(pfad)


def einteilen(e: dict, k: dict) -> str | None:
    """Grund, warum der Eintrag erklaert ist – oder ``None`` (nicht erklaert)."""
    pfad, art = e["pfad"], e["art"]
    typ, merkmale, groesse = _merkmale(e["attrs"])
    dp = k["dpkg"]
    # Rechte, Eigentuemer, Gruppe, Linkziel, ACL/xattr: nie "erklaert" durch
    # eine passende Pruefsumme – ein gesetztes SUID-Bit aendert keinen Inhalt.
    if art == "geaendert":
        if merkmale == {"c"} and not groesse:
            return "nur Inode-Zeit (ctime)"
        # Nur Zeiten/Inode einer Datei: m erfasst Debian ausschliesslich mit den
        # Pruefsummen (StaticFile = m+c+Checksums), ohne "H" ist der Inhalt also
        # gleich (SentinelOne-Koederdateien, neu installierte Kopien, ECHT 25.11.)
        if typ == "f" and merkmale <= {"m", "c", "i", "n"} and "m" in merkmale and not groesse:
            return "Inhalt und Rechte unveraendert (nur Zeit/Inode)"
        # Ein Verzeichnis aendert Zeit, Linkzahl, Groesse und Blockzahl mit
        # seinem INHALT, und wer es atomar tauscht (Broker-Installation),
        # auch die Inode – die Eintraege darin stehen einzeln im Bericht.
        if typ == "d" and merkmale <= {"m", "c", "n", "b", "i"}:
            return "Verzeichnisinhalt"
        if typ == "f" and merkmale & {"p"}:
            rel_c = _code_rel(pfad)
            if rel_c is not None:
                return _code_rechte(pfad, rel_c, merkmale, k)
        if merkmale & {"p", "u", "g", "l", "A", "X", "E"}:
            return None
        if typ == "s" and merkmale <= {"m", "c", "i", "b", "n"} and _SOCKET_NEU_ANGELEGT.match(pfad):
            return "Laufzeit-Socket neu angelegt"
    if typ == "f" and art in ("neu", "geaendert") and _mail_erklaert(pfad):
        return "Jarvis-Mailversand (eigene Konfiguration)"
    if typ == "f":
        eigen = _eigene_erklaert(e, k)
        if eigen:
            return eigen
        if art == "geaendert" and _konten_art(pfad):
            return _konten_erklaert(pfad, k)
        if art == "geaendert" and _LOG_ROTATION.match(pfad):
            return "Protokoll neu geschrieben/rotiert"
        if art == "neu" and _LOG_SERIE.match(pfad) and _ohne_ausfuehrung(pfad):
            return "Protokollrotation (neue Fassung)"
        if art == "entfernt" and _LOG_SERIE.match(pfad):
            return "Protokollrotation (aelteste Fassung entfernt)"
        for muster, name in ((_DPKG_SICHERUNG, "Sicherung der Paketdatenbank (dpkg-db-backup)"),
                             (_DEV_SICHERUNG, "Sicherung von dev_reset")):
            if muster.match(pfad):
                if art == "entfernt":
                    return name + " (entfernt)"
                return name if _root_ablage(pfad) else None
        if art == "geaendert" and _WIREPLUMBER.match(pfad):
            return "Desktop-Zustand (wireplumber)"
        if art == "neu" and pfad == DYNAMICMAPS and k.get("dpkg_seit_basis") and _paket_geaendert(k, "postfix"):
            # Paketskript von postfix legt die Datei mit einer Kopfzeile an;
            # jede andere Zeile wuerde eine Bibliothek in Postfix laden.
            try:
                zeilen = [z for z in _p(pfad).read_text(errors="replace").splitlines()
                          if z.strip() and not z.lstrip().startswith("#")]
            except OSError:
                return None
            return None if zeilen or not _ohne_ausfuehrung(pfad) else "Postfix: leeres dynamicmaps.cf (Paketskript)"
    if art == "neu" and _AIDE_ALTORDNER.match(pfad):
        e_ = _eigentuemer(pfad)
        return "Arbeitsordner der AIDE-Pruefung" if e_ is not None and _aide_benutzer(e_[0]) else None
    rel = _code_rel(pfad)
    if rel is not None:
        baum = k.get("baum")
        if baum is None:
            return None
        if rel == "STAND" and pfad.startswith("/usr/local/lib/jarvis-broker/"):
            try:
                stand = json.loads(_p(pfad).read_text())
            except (OSError, ValueError):
                return None
            return "Jarvis-Stand (Installationsvermerk)" if \
                str(stand.get("commit", ""))[:12] == k.get("baum_info") else None
        if art == "entfernt":
            enthalten = rel in baum or any(r.startswith(rel + "/") for r in baum)
            return None if enthalten else "Jarvis-Stand (im signierten Stand entfernt)"
        if typ == "d":
            return "Jarvis-Stand (Verzeichnis)" if any(r.startswith(rel + "/") for r in baum) else None
        if typ == "f":
            return "Jarvis-Stand (signiert)" if baum.get(rel) and baum.get(rel) == _git_blob(_p(pfad)) else None
        return None
    m = _PYC.match(pfad)
    rc = _rc_verweis(art, typ, pfad, k) or _postfix_laufzeit(art, typ, pfad, k)
    if rc:
        return rc
    if typ == "f" and art in ("neu", "geaendert"):
        kopie = _postfix_kopie(pfad, k)
        if kopie:
            return kopie
    if art in ("neu", "geaendert"):
        if typ == "f" and pfad in dp["md5"]:
            soll, paket = dp["md5"][pfad]
            return ("Paket %s" % paket) if _md5_datei(_p(pfad)) == soll else None
        if typ == "f" and pfad in dp["conff"]:
            soll, paket = dp["conff"][pfad]
            return ("Konfiguration von %s (Paketstand)" % paket) if _md5_datei(_p(pfad)) == soll else None
        if typ != "f" and pfad in dp["liste"]:
            return "Paket %s" % dp["liste"][pfad]
        if m and (m.group("dir") + "/" + m.group("name") + ".py") in dp["liste"]:
            return "Bytecode zu Paket %s" % dp["liste"][m.group("dir") + "/" + m.group("name") + ".py"]
        if typ == "f":
            quelle = _kopie_quelle(pfad)
            if quelle and quelle in dp["md5"] and _md5_datei(_p(pfad)) == dp["md5"][quelle][0]:
                return "Paket %s (Kopie von %s)" % (dp["md5"][quelle][1], quelle)
        if k.get("dpkg_seit_basis") and _PAKETVERWALTUNG.match(pfad):
            return "Paketverwaltung"
        return None
    # entfernt
    basis = k.get("basis") or {}
    paket = (basis.get("pfade") or {}).get(pfad)
    if paket and _paket_geaendert(k, paket):
        return "entfernt mit Update von %s" % paket
    # Ohne Dateiliste von damals (keine Basis): das Verzeichnis gehoert GENAU
    # einem Paket, und das wurde seither aktualisiert (ECHT 25.11.2026:
    # changelog.Debian.amd64.gz eines binNMU, die neue Fassung hat keinen).
    if not paket and typ == "f":
        eltern = pfad.rsplit("/", 1)[0]
        ep = dp["liste"].get(eltern)
        if ep and dp.get("liste_n", {}).get(eltern) == 1 and _paket_geaendert(k, ep) \
                and not (k.get("basis") or {}).get("pfade"):
            return "entfernt mit Update von %s (Verzeichnis des Pakets)" % ep
    if m:
        quelle = m.group("dir") + "/" + m.group("name") + ".py"
        qp = (basis.get("pfade") or {}).get(quelle) or dp["liste"].get(quelle)
        if qp and (_paket_geaendert(k, qp) or quelle not in dp["liste"]):
            return "Bytecode zu Paket %s" % qp
    if k.get("dpkg_seit_basis") and _PAKETVERWALTUNG.match(pfad):
        return "Paketverwaltung"
    return None


def warum_offen(e: dict, k: dict) -> str:
    """Kurzer Grund, warum ein Eintrag NICHT erklaert ist – fuer die Durchsicht.
    Der wichtigste Fall zuerst: eine Paketdatei, deren Inhalt nicht mehr der
    des Pakets ist."""
    pfad, art = e["pfad"], e["art"]
    typ, merkmale, _ = _merkmale(e["attrs"])
    dp = k["dpkg"]
    if art == "geaendert" and merkmale & {"p", "u", "g"}:
        return "Rechte oder Eigentuemer geaendert"
    if art == "geaendert" and "l" in merkmale:
        return "Linkziel geaendert"
    if art != "entfernt" and pfad in dp["md5"]:
        return "Inhalt weicht von Paket %s ab" % dp["md5"][pfad][1]
    if art != "entfernt" and pfad in dp["conff"]:
        return "Konfiguration von %s lokal geaendert" % dp["conff"][pfad][1]
    if _code_rel(pfad) is not None:
        qn = k.get("quelle_nachziehen") or {}
        zusatz = "" if qn.get("ok", True) else "; Quelle nicht auf den installierten Stand %s gebracht: %s" % (
            qn.get("stand", "?"), qn.get("grund", "?"))
        if k.get("baum") is None:
            return "Jarvis-Code nicht pruefbar (%s%s)" % (k.get("baum_info", ""), zusatz)
        return "weicht vom signierten Stand der Broker-Quelle ab (%s%s)" % (k.get("baum_info", ""), zusatz)
    if art == "entfernt":
        return "entfernt, keinem aktualisierten Paket zuzuordnen"
    return "gehoert keinem Paket" if art == "neu" else "geaendert, gehoert keinem Paket"


# ── Zustand, Sperre, Uebernahme ──────────────────────────────────────────────

@contextmanager
def _sperre():
    _p(ZUSTAND_DIR).mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(_p(SPERRE), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def zustand_lesen() -> dict:
    try:
        return json.loads(_p(ZUSTAND).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _zustand_schreiben(z: dict) -> None:
    ziel = _p(ZUSTAND)
    ziel.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = ziel.with_name(ziel.name + ".tmp")
    tmp.write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ziel)


def _konten_kandidat_schreiben(konten: dict | None) -> None:
    """Kontenstand zum Zeitpunkt der Pruefung – wird erst mit der Uebernahme
    Teil der Basis (sonst stuende darin ein Stand, den aide.db nicht kennt)."""
    ziel = _p(KONTEN_KANDIDAT)
    ziel.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = ziel.with_name(ziel.name + ".tmp")
    tmp.write_text(json.dumps(konten), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ziel)


def _konten_kandidat_lesen() -> dict | None:
    try:
        d = json.loads(_p(KONTEN_KANDIDAT).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _db_uebernehmen(sha_soll: str) -> str:
    """aide.db.new -> aide.db, wenn es GENAU die geprueft Fassung ist.
    Leerer Text = ok, sonst der Grund. Der alte Stand bleibt als aide.db.vorher."""
    neu, alt = _p(DB_NEU), _p(DB)
    if _sha256_datei(neu) != sha_soll:
        return "aide.db.new hat sich seit der Pruefung geaendert"
    try:
        vorlage = os.stat(alt) if alt.exists() else os.stat(neu)
        if alt.exists():
            _p(ZUSTAND_DIR).mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(alt, _p(DB_VORHER))
            os.chmod(_p(DB_VORHER), 0o600)
        tmp = alt.with_name(alt.name + ".jarvis-tmp")
        shutil.copyfile(neu, tmp)
        os.chmod(tmp, 0o600)
        if not W:
            os.chown(tmp, vorlage.st_uid, vorlage.st_gid)
            if _p(DB_VORHER).exists():
                os.chown(_p(DB_VORHER), vorlage.st_uid, vorlage.st_gid)
        os.replace(tmp, alt)
    except OSError as ex:
        return "Uebernahme gescheitert: %s" % ex
    if _sha256_datei(alt) != sha_soll:
        return "aide.db nach der Uebernahme nicht die gepruefte Fassung"
    return ""


def abgleichen() -> dict:
    """Den letzten Bericht einteilen und bei sauberem Ergebnis uebernehmen."""
    jetzt = _jetzt()
    z = {"zeit": jetzt, "zustand": "fehler", "grund": "", "bericht": {}, "erklaert": {},
         "offen": [], "offen_anzahl": 0, "kennung": "", "db_neu_sha": ""}
    try:
        text = _p(BERICHT).read_text(errors="replace")
    except OSError as ex:
        z["grund"] = "Bericht nicht lesbar: %s" % ex
        return z
    b = bericht_lesen(text)
    z["bericht"] = {"start": b["start"], "ende": b["ende"], "summe": b["summe"]}
    if not b["vollstaendig"]:
        z["grund"] = "Bericht unvollstaendig oder unbekannt aufgebaut – nichts uebernommen"
        return z
    neu = _p(DB_NEU)
    try:
        mneu = os.stat(neu).st_mtime
    except OSError:
        z["grund"] = "aide.db.new fehlt"
        return z
    # Der neue Stand muss aus DIESEM Lauf stammen (zwischen Start und Ende).
    if b["start"] is None or not (b["start"] - 5 <= mneu <= (b["ende"] or jetzt) + 120):
        z["grund"] = "aide.db.new passt zeitlich nicht zum Bericht"
        return z
    z["db_neu_sha"] = _sha256_datei(neu) or ""
    z["kennung"] = hashlib.sha256((z["db_neu_sha"] + text).encode("utf-8", "replace")).hexdigest()[:16]
    basis_zeit = None
    try:
        basis_zeit = os.stat(_p(DB)).st_mtime
    except OSError:
        pass
    k = kontext_laden((basis_lesen() or {}).get("zeit") or basis_zeit)
    k["sha256"] = b.get("sha256") or {}
    konten = konten_lesen()
    _konten_kandidat_schreiben(konten)
    z["quelle"] = k["baum_info"] if k["baum"] is not None else ("nicht verwendet: " + k["baum_info"])
    z["quelle_nachziehen"] = k.get("quelle_nachziehen") or {}
    offen = []
    for e in b["eintraege"]:
        grund = einteilen(e, k)
        if grund is None:
            offen.append(dict(e, warum=warum_offen(e, k)))
        else:
            schluessel = grund.split(" ", 1)[0] if grund.startswith(("Paket ", "Bytecode", "Konfiguration")) else grund
            z["erklaert"][schluessel] = z["erklaert"].get(schluessel, 0) + 1
    z["offen_anzahl"] = len(offen)
    # Abdruck JEDES offenen Eintrags (auch jenseits von OFFEN_MAX): daran
    # erkennt mail_melden, ob seit der letzten Mail etwas NEUES dazukam.
    # Die neue Pruefsumme gehoert dazu – eine erneut geaenderte Datei ist neu.
    z["abdruecke"] = sorted({_abdruck(o, k["sha256"]) for o in offen})
    # Die schwersten zuerst: wird die Liste gekuerzt, fallen nie sie heraus.
    rang = ("Rechte", "Linkziel", "Inhalt weicht", "Konfiguration")
    offen.sort(key=lambda o: next((i for i, r in enumerate(rang) if o["warum"].startswith(r)), len(rang)))
    z["offen"] = offen[:OFFEN_MAX]
    # Lief dpkg WAEHREND der Pruefung, passen Bericht und Paketstand nicht
    # sicher zueinander – dann nie automatisch uebernehmen.
    # history.log hat Sekunden: ein Lauf, der in DERSELBEN Sekunde endet, in der
    # die Pruefung beginnt, zaehlt mit (fail-closed); der Lauf, der die Pruefung
    # ausgeloest hat, endet davor (DEV 24.11.2026: apt 09:31:17, AIDE 09:31:18 –
    # mit "Start - 1" fing die Bedingung genau ihn).
    waehrend = [l for l in k["laeufe"] if l[1] >= b["start"] and l[0] <= jetzt]
    if waehrend:
        z["grund"] = "Paketverwaltung lief waehrend oder nach der Pruefung"
    if not b["eintraege"]:
        z["zustand"] = "unveraendert"
        return z
    if offen or waehrend:
        z["zustand"] = "offen"
        return z
    fehler = _db_uebernehmen(z["db_neu_sha"])
    if fehler:
        z["zustand"], z["grund"] = "fehler", fehler
        return z
    basis_schreiben(k["dpkg"], b["start"], konten)
    z["zustand"], z["uebernommen_von"], z["uebernommen_zeit"] = "uebernommen", "automatisch", _jetzt()
    return z


def nach_pruefung() -> int:
    """Einstieg fuer ``ExecStartPost=+`` von dailyaidecheck.service."""
    with _sperre():
        z = abgleichen()
        _zustand_schreiben(z)
    summe = z.get("bericht", {}).get("summe", {})
    _protokoll("AIDE-Abgleich: %s – %d neu, %d entfernt, %d geaendert, davon %d nicht erklaert%s"
               % (z["zustand"], summe.get("neu", 0), summe.get("entfernt", 0), summe.get("geaendert", 0),
                  z.get("offen_anzahl", 0), (" (" + z["grund"] + ")") if z.get("grund") else ""))
    mail_melden(z)
    # Ein interner Fehler soll an der Unit sichtbar werden (B13: Unit failed)
    return 1 if z["zustand"] == "fehler" else 0


MAIL_EINTRAEGE = 40


def _mm():
    try:
        from backend import mail_meldung  # type: ignore
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import mail_meldung  # type: ignore
    return mail_meldung


def mail_text(z: dict, sprache: str | None = None) -> tuple[str, str] | None:
    """(Betreff, Text) fuer "offen" und "fehler" in der Sprache der Oberflaeche
    (mail_meldung.text) – sonst None (nichts zu melden). Die Begruendung je
    Eintrag ("warum") bleibt wie in der Anzeige."""
    mm = _mm()
    k = mm.konf()
    sp = sprache or k.get("sprache", "de")
    t = lambda key, d, **w: mm.text(key, d, sp, **w)  # noqa: E731
    summe = z.get("bericht", {}).get("summe", {})
    if z.get("zustand") == "fehler":
        return (t("mvm.aide_fehler_betreff", "AIDE-Abgleich fehlgeschlagen"),
                "\n".join([t("mvm.aide_fehler_text", "Der Abgleich der täglichen Integritätsprüfung ist "
                              "gescheitert: {grund}", grund=z.get("grund") or "?"), "",
                            t("mvm.aide_fehler_stand", "Der bisherige Vergleichsstand bleibt bestehen.")]))
    if z.get("zustand") != "offen":
        return None
    n = int(z.get("offen_anzahl") or 0)
    zeilen = [t("mvm.aide_einleitung", "Die Integritätsprüfung hat Änderungen gefunden, die weder ein Paket "
                "noch der signierte Stand von {marke} erklärt. Der Vergleichsstand wurde NICHT übernommen.",
                marke=k.get("marke", "Jarvis")), "",
              t("mvm.aide_summe", "Gesamt: {neu} neu, {entfernt} entfernt, {geaendert} geändert – davon {n} "
                "nicht erklärt.", neu=summe.get("neu", 0), entfernt=summe.get("entfernt", 0),
                geaendert=summe.get("geaendert", 0), n=n)]
    if z.get("grund"):
        zeilen.append(t("mvm.aide_hinweis", "Hinweis: {grund}", grund=z["grund"]))
    zeilen.append("")
    for o in (z.get("offen") or [])[:MAIL_EINTRAEGE]:
        art = t("mvm.aide_art_" + str(o.get("art", "")), str(o.get("art", "?")))
        zeilen.append("  [%s] %s – %s" % (art, o.get("pfad", "?"), o.get("warum", "")))
    if n > MAIL_EINTRAEGE:
        zeilen.append("  " + t("mvm.aide_weitere", "… und {n} weitere (vollständige Liste in der Oberfläche)",
                               n=n - MAIL_EINTRAEGE))
    zeilen += ["", t("mvm.aide_weg", "Durchsicht und Übernahme: Einstellungen → KI & System → "
                     "Paket-Updates und Integrität → Integritätsprüfung (AIDE).")]
    return (t("mvm.aide_betreff", "AIDE: {n} nicht erklärte Änderung(en)", n=n), "\n".join(zeilen))


def _abdruck(e: dict, sha: dict) -> str:
    teile = [e.get("pfad", ""), e.get("art", ""), e.get("attrs", ""), ((sha or {}).get(e.get("pfad")) or ["", ""])[-1]]
    return hashlib.sha256("\0".join(teile).encode("utf-8", "replace")).hexdigest()[:16]


def _gemeldet_lesen() -> dict:
    try:
        d = json.loads(_p(GEMELDET).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gemeldet_schreiben(d: dict | None) -> None:
    ziel = _p(GEMELDET)
    if d is None:
        try:
            ziel.unlink()
        except OSError:
            pass
        return
    ziel.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = ziel.with_name(ziel.name + ".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ziel)


def meldung_noetig(z: dict) -> tuple[bool, dict | None]:
    """(melden?, Stand, der nach erfolgreichem Versand als gemeldet gilt).

    WARUM (DEV 26.11.2026, "solche unnoetigen Mails"): solange niemand
    uebernimmt, vergleicht AIDE jede Nacht gegen denselben alten Stand und
    findet dieselben Eintraege wieder – bis dahin kam damit JEDE Nacht
    dieselbe Mail. Gemeldet wird jetzt nur, was seit der letzten Mail NEU
    dazukam (Abdruck je Eintrag samt neuer Pruefsumme); ein gleichbleibender
    Fehler ebenso nur einmal. Die Durchsicht in der Oberflaeche zeigt
    weiterhin ALLE offenen Eintraege."""
    zustand = z.get("zustand")
    if zustand == "offen":
        jetzt = set(z.get("abdruecke") or [])
        if not jetzt:   # Altzustand ohne Abdruecke oder nur dpkg waehrend der Pruefung
            jetzt = {"grund:" + str(z.get("grund") or "")}
        vorher = set(_gemeldet_lesen().get("offen") or [])
        return bool(jetzt - vorher), {"offen": sorted(jetzt)}
    if zustand == "fehler":
        grund = str(z.get("grund") or "")
        return _gemeldet_lesen().get("fehler") != grund, {"fehler": grund}
    return False, None


def mail_melden(z: dict) -> dict | None:
    """Meldung per E-Mail (Quelle "aide"); im Testmodus (W) nie. Wirft nie."""
    try:
        noetig, stand = meldung_noetig(z)
        if z.get("zustand") in ("uebernommen", "unveraendert"):
            _gemeldet_schreiben(None)   # neuer Vergleichsstand: alles Spaetere ist neu
        if not noetig:
            if z.get("zustand") in ("offen", "fehler"):
                _protokoll("AIDE-Abgleich: nichts Neues seit der letzten Mail – keine Mail")
            return None
        if W:
            return None
        inhalt = mail_text(z)
        if not inhalt:
            return None
        r = _mm().senden("aide", inhalt[0], inhalt[1])
        # Nur ein zugestellter (oder bewusst nicht gewollter) Versand zaehlt als
        # gemeldet – nach einem Fehlschlag versucht es die naechste Nacht erneut.
        if isinstance(r, dict) and (r.get("gesendet") or (r.get("ok") and not r.get("gedrosselt"))):
            _gemeldet_schreiben(stand)
        return r
    except Exception as e:  # noqa: BLE001
        print("Mail nicht verschickt: %s" % e, flush=True)
        return None


def uebernehmen(kennung: str, wer: str) -> dict:
    """Ein Administrator uebernimmt einen OFFENEN Abgleich nach Durchsicht.

    Nur mit der Kennung, die er gesehen hat: ist inzwischen ein neuer Bericht
    da, gilt sie nicht mehr."""
    if not isinstance(kennung, str) or not re.fullmatch(r"[0-9a-f]{16}", kennung):
        return {"ok": False, "fehler": "Ungueltige Kennung"}
    # Anzeigename wie im Sicherheitsprotokoll, auch in der Domaenenform
    # "domaene\\name" (der Backslash fiel bis 24.11.2026 dem Filter zum Opfer)
    wer = re.sub(r"[^\w.@\\-]", "", str(wer or ""))[:80] or "unbekannt"
    with _sperre():
        z = zustand_lesen()
        if z.get("zustand") != "offen":
            return {"ok": False, "fehler": "Kein offener Abgleich", "zustand": z}
        if z.get("kennung") != kennung:
            return {"ok": False, "fehler": "Inzwischen liegt ein neuerer Bericht vor – bitte neu laden",
                    "zustand": z}
        fehler = _db_uebernehmen(z.get("db_neu_sha", ""))
        if fehler:
            return {"ok": False, "fehler": fehler, "zustand": z}
        start = (z.get("bericht") or {}).get("start") or _jetzt()
        basis_schreiben(dpkg_laden(), start, _konten_kandidat_lesen())
        z["zustand"], z["uebernommen_von"], z["uebernommen_zeit"] = "uebernommen", wer, _jetzt()
        _zustand_schreiben(z)
        _gemeldet_schreiben(None)
    _protokoll("AIDE-Abgleich: %d nicht erklaerte Aenderung(en) von %s uebernommen (Kennung %s)"
               % (z.get("offen_anzahl", 0), wer, kennung))
    return {"ok": True, "zustand": z}


def _systemctl(*args: str, timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip()
    except Exception as ex:  # noqa: BLE001
        return 1, str(ex)


def _laeuft() -> str:
    for unit in AIDE_UNITS:
        rc, out = _systemctl("is-active", unit)
        if out.splitlines()[:1] in (["active"], ["activating"]):
            return unit
    return ""


def _frei_kb() -> int:
    try:
        for z in Path("/proc/meminfo").read_text().splitlines():
            if z.startswith("MemAvailable:"):
                return int(z.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def pruefung_starten() -> dict:
    """Die taegliche Pruefung jetzt anstossen (nach einem Update). Der
    Abgleich laeuft danach als ihr Nachlauf."""
    laeuft = _laeuft()
    if laeuft:
        return {"ok": True, "laeuft": True, "hinweis": "%s laeuft bereits" % laeuft}
    frei = _frei_kb()
    if frei < MIN_FREI_KB:
        return {"ok": False, "fehler": "Zu wenig freier Arbeitsspeicher fuer eine AIDE-Pruefung "
                                       "(%.1f GB frei, gebraucht bis 8 GB)" % (frei / 1048576)}
    # StartLimitBurst=1 in 2 h (Debian-Unit): ohne reset-failed scheitert ein
    # zweiter Start am selben Morgen mit "start request repeated too quickly".
    _systemctl("reset-failed", PRUEF_UNIT)
    rc, out = _systemctl("start", "--no-block", PRUEF_UNIT)
    if rc != 0:
        return {"ok": False, "fehler": "Pruefung nicht startbar: %s" % out[-300:]}
    return {"ok": True, "laeuft": True}


def _naechste_pruefung() -> float | None:
    """Naechster Lauf des Timers als Epoche. Die JSON-Form von list-timers
    liefert Mikrosekunden; ``show -p NextElapseUSecRealtime`` bleibt auch mit
    ``--timestamp=unix`` Text (auf DEV gemessen, systemd 257)."""
    rc, out = _systemctl("list-timers", "dailyaidecheck.timer", "--all", "--output=json")
    try:
        for t in json.loads(out or "[]"):
            if t.get("unit") == "dailyaidecheck.timer" and isinstance(t.get("next"), (int, float)) and t["next"] > 0:
                return t["next"] / 1e6
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def status() -> dict:
    z = zustand_lesen()
    rc, letzte = _systemctl("show", "--timestamp=unix", "-p", "ExecMainExitTimestamp", "--value", PRUEF_UNIT)
    letzte_t = float(letzte[1:]) if re.fullmatch(r"@\d+(?:\.\d+)?", letzte or "") else None
    return {"zustand": z, "laeuft": _laeuft(), "eingerichtet": _p(
        "/etc/systemd/system/dailyaidecheck.service.d/80-jarvis-abgleich.conf").is_file(),
        "letzte_pruefung": letzte_t, "naechste_pruefung": _naechste_pruefung(), "db": _p(DB).exists()}


def main(argv: list[str]) -> int:
    if argv[1:2] == ["--nach-pruefung"]:
        return nach_pruefung()
    if argv[1:2] == ["--zeigen"]:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
        return 0
    print("Aufruf: aide_abgleich.py --nach-pruefung | --zeigen", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
