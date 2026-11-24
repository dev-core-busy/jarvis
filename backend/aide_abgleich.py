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
DPKG_INFO = "/var/lib/dpkg/info"
DPKG_STATUS = "/var/lib/dpkg/status"
APT_HISTORY = ("/var/log/apt/history.log", "/var/log/apt/history.log.1.gz")
QUELLE = "/var/lib/jarvis-broker/quelle"
SIGNERS = "/etc/jarvis/allowed_signers"
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
           "ohne_aenderung": False}
    abschnitt = None
    for zeile in text.splitlines():
        if zeile.startswith("Start timestamp:"):
            erg["start"] = _zeitstempel(zeile.split(":", 1)[1])
            continue
        if zeile.startswith("End timestamp:"):
            erg["ende"] = _zeitstempel(zeile.split(":", 1)[1])
            abschnitt = None
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
            abschnitt = None
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
        h = hashlib.md5()  # noqa: S324 – dpkg fuehrt md5, verglichen wird damit
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
    return hashlib.sha1(b"blob %d\0" % len(daten) + daten).hexdigest()  # noqa: S324


def dpkg_laden() -> dict:
    """Pruefsummen, Dateilisten, Conffiles und Versionen aus der dpkg-Datenbank."""
    md5, liste, conff, versionen = {}, {}, {}, {}
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
    return {"md5": md5, "liste": liste, "conff": conff, "versionen": versionen}


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
    kopf = _git(["rev-parse", "HEAD"])
    return baum, (kopf.stdout.decode().strip()[:12] if kopf.returncode == 0 else "")


def _dpkg_laeufe() -> list[tuple[float, float]]:
    """(Start, Ende) jedes Blocks in apt/history.log (auch der rotierten Datei)."""
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
            laeufe.append((st, en))
    return laeufe


def basis_lesen() -> dict | None:
    try:
        with gzip.open(_p(BASIS), "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def basis_schreiben(dp: dict, zeit: float) -> None:
    """Paketstand zum Zeitpunkt des uebernommenen Stands – damit laesst sich
    beim naechsten Mal ein ENTFERNTER Pfad einem aktualisierten Paket zuordnen
    (dpkg kennt entfernte Dateien danach nicht mehr)."""
    ziel = _p(BASIS)
    ziel.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = ziel.with_name(ziel.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({"zeit": zeit, "versionen": dp["versionen"], "pfade": dp["liste"]}, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, ziel)


def kontext_laden(basis_zeit: float | None) -> dict:
    dp = dpkg_laden()
    baum, baum_info = baum_laden()
    basis = basis_lesen()
    if basis_zeit is None and basis:
        basis_zeit = basis.get("zeit")
    laeufe = _dpkg_laeufe()
    return {"dpkg": dp, "baum": baum, "baum_info": baum_info, "basis": basis,
            "basis_zeit": basis_zeit, "laeufe": laeufe,
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


def _paket_geaendert(k: dict, paket: str) -> bool:
    b = k.get("basis") or {}
    return (b.get("versionen") or {}).get(paket) != k["dpkg"]["versionen"].get(paket)


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
        # Ein Verzeichnis aendert Zeit, Linkzahl, Groesse und Blockzahl mit
        # seinem INHALT, und wer es atomar tauscht (Broker-Installation),
        # auch die Inode – die Eintraege darin stehen einzeln im Bericht.
        if typ == "d" and merkmale <= {"m", "c", "n", "b", "i"}:
            return "Verzeichnisinhalt"
        if merkmale & {"p", "u", "g", "l", "A", "X", "E"}:
            return None
    if typ == "f" and art in ("neu", "geaendert") and _mail_erklaert(pfad):
        return "Jarvis-Mailversand (eigene Konfiguration)"
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
        if k.get("baum") is None:
            return "Jarvis-Code nicht pruefbar (%s)" % k.get("baum_info", "")
        return "weicht vom signierten Stand der Broker-Quelle ab (%s)" % k.get("baum_info", "")
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
    z["quelle"] = k["baum_info"] if k["baum"] is not None else ("nicht verwendet: " + k["baum_info"])
    offen = []
    for e in b["eintraege"]:
        grund = einteilen(e, k)
        if grund is None:
            offen.append(dict(e, warum=warum_offen(e, k)))
        else:
            schluessel = grund.split(" ", 1)[0] if grund.startswith(("Paket ", "Bytecode", "Konfiguration")) else grund
            z["erklaert"][schluessel] = z["erklaert"].get(schluessel, 0) + 1
    z["offen_anzahl"] = len(offen)
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
    basis_schreiben(k["dpkg"], b["start"])
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


def mail_melden(z: dict) -> dict | None:
    """Meldung per E-Mail (Quelle "aide"); im Testmodus (W) nie. Wirft nie."""
    if W:
        return None
    try:
        inhalt = mail_text(z)
        if not inhalt:
            return None
        return _mm().senden("aide", inhalt[0], inhalt[1])
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
        basis_schreiben(dpkg_laden(), start)
        z["zustand"], z["uebernommen_von"], z["uebernommen_zeit"] = "uebernommen", wer, _jetzt()
        _zustand_schreiben(z)
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
