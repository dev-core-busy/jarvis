#!/usr/bin/env python3
"""Waechter fuer backend/aide_abgleich.py: wird ein neuer AIDE-Stand NUR
uebernommen, wenn jede Aenderung erklaert ist?

Alles laeuft in einem Sandkasten (JARVIS_AIDE_WURZEL): eigene dpkg-Datenbank,
ein AIDE-Bericht in der Form von AIDE 0.19, ein mit einem SSH-Schluessel
SIGNIERTER Git-Stand als Broker-Quelle (echtes ``git verify-commit``, kein
Nachbau) und je ein alter und neuer Vergleichsstand. Gemessen wird die
WIRKUNG: welche Datei danach aide.db ist.

Die Zusagen:
  1. Bericht: Eintraege und Zusammenfassung stimmen ueberein, sonst gilt er
     als unvollstaendig (ein abgeschnittener Bericht ist nie "nichts gefunden").
  2. Einteilung: Paketdatei mit passender Pruefsumme erklaert, mit
     abweichender NICHT; geaenderte Rechte nie durch eine Pruefsumme erklaert;
     Jarvis-Code nur bei gleichem Inhalt wie der SIGNIERTE Stand; ohne
     Signatur oder bei fremd beschreibbarer Quelle erklaert der Code nichts;
     Paketverwaltungsdateien nur nach einem dpkg-Lauf; entfernte Pfade nur
     mit einem Paket, dessen Version sich seit dem Stand geaendert hat.
  3. Uebernahme: sauber -> aide.db ist aide.db.new, alter Stand bleibt als
     aide.db.vorher; ein einziger nicht erklaerter Eintrag -> aide.db bleibt.
  4. Admin-Uebernahme nur mit der gesehenen Kennung und nur, solange
     aide.db.new unveraendert ist.
  5. Fail-closed: neuer Stand passt zeitlich nicht zum Bericht, dpkg lief
     waehrend der Pruefung, Bericht abgeschnitten -> nichts uebernommen.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import gzip
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def pruefe(bed, text):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + text)
    else:
        FAIL += 1
        print("  FAIL " + text)


def abbruch(text):
    print("ABBRUCH: " + text)
    sys.exit(2)


for werkzeug in ("git", "ssh-keygen"):
    if not shutil.which(werkzeug):
        abbruch("%s fehlt – der signierte Stand laesst sich nicht herstellen" % werkzeug)

# Die Quelle muss "nicht fremd beschreibbar" sein; eine umask 002 der Shell
# machte jedes Sandkasten-Verzeichnis gruppenbeschreibbar (lokal gemessen).
os.umask(0o022)
SANDKASTEN = Path(tempfile.mkdtemp(prefix="aide_abgleich_"))
W = SANDKASTEN / "w"
W.mkdir()
os.environ["JARVIS_AIDE_WURZEL"] = str(W)
sys.path.insert(0, str(REPO))
# Die Gegenprobe (tests/gegen_aide_abgleich.py) laesst eine sabotierte KOPIE
# pruefen; der Arbeitsbaum wird dabei nie angefasst.
_KOPIE = os.environ.get("JARVIS_AIDE_ABGLEICH_MODUL", "")
if _KOPIE:
    import importlib.util
    _spec = importlib.util.spec_from_file_location("aide_abgleich_probe", _KOPIE)
    A = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(A)
else:
    A = importlib.import_module("backend.aide_abgleich")

# Positivkontrolle: der Sandkasten ist wirklich die Wurzel (sonst liefe jede
# Pruefung gegen das echte /var/lib/aide)
if str(A._p("/var/lib/aide/aide.db")) != str(W) + "/var/lib/aide/aide.db":
    abbruch("Modul benutzt die Sandkasten-Wurzel nicht")


def schreibe(pfad, inhalt, modus=0o644):
    p = W / pfad.lstrip("/")
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(inhalt, str):
        inhalt = inhalt.encode()
    p.write_bytes(inhalt)
    os.chmod(p, modus)
    return p


def lies(pfad):
    """Inhalt oder None – eine Pruefung darf nicht werfen (sonst Exit 1 ohne
    FAIL-Zeile, von "nicht gelaufen" nicht zu unterscheiden)."""
    try:
        return (W / pfad.lstrip("/")).read_bytes()
    except OSError:
        return None


def md5(b):
    return hashlib.md5(b.encode() if isinstance(b, str) else b).hexdigest()


def zeitstempel(t):
    return time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(t))


def bericht(eintraege, start, ende, ohne_ende=False, summe=None):
    """AIDE-0.19-Bericht wie auf ECHT gemessen (24.11.2026)."""
    arten = {"neu": "Added", "entfernt": "Removed", "geaendert": "Changed"}
    z = summe or {a: sum(1 for e in eintraege if e[0] == a) for a in arten}
    t = ["Start timestamp: %s (AIDE 0.19.1)" % zeitstempel(start),
         "AIDE found differences between database and filesystem!!", "",
         "Summary:", "  Total number of entries:\t1000",
         "  Added entries:\t\t%d" % z["neu"], "  Removed entries:\t\t%d" % z["entfernt"],
         "  Changed entries:\t\t%d" % z["geaendert"], ""]
    for a, name in arten.items():
        teil = [e for e in eintraege if e[0] == a]
        if not teil:
            continue
        t += ["-" * 51, "%s entries:" % name, "-" * 51, ""]
        t += ["%s: %s" % (attrs, pfad) for _, attrs, pfad in teil]
        t.append("")
    t += ["-" * 51, "Detailed information about changes:", "-" * 51, "",
          "File: /etc/jarvis/x", " Ctime     : 2026-11-23 17:13:04 +0100 | 2026-11-23 18:32:18 +0100", ""]
    if not ohne_ende:
        t.append("End timestamp: %s (AIDE 0.19.1)" % zeitstempel(ende))
    return "\n".join(t) + "\n"


# ── Sandkasten: dpkg ─────────────────────────────────────────────────────────
FOO = "#!/bin/sh\necho foo\n"
FOO_CONF = "a=1\n"
schreibe("/usr/bin/foo", FOO, 0o755)
schreibe("/usr/lib/python3/dist-packages/foo/__init__.py", "")
schreibe("/usr/lib/python3/dist-packages/foo/__pycache__/__init__.cpython-313.pyc", b"\x00pyc")
schreibe("/usr/lib/grub/i386-pc/normal.mod", b"MOD")
schreibe("/boot/grub/i386-pc/normal.mod", b"MOD")
schreibe("/etc/foo.conf", FOO_CONF)
schreibe("/var/lib/dpkg/info/foo.md5sums",
         "%s  usr/bin/foo\n%s  usr/lib/grub/i386-pc/normal.mod\n" % (md5(FOO), md5("MOD")))
schreibe("/var/lib/dpkg/info/foo.list", "/.\n/usr\n/usr/bin\n/usr/bin/foo\n/usr/lib/python3/dist-packages/foo\n"
         "/usr/lib/python3/dist-packages/foo/__init__.py\n/usr/lib/grub/i386-pc/normal.mod\n/usr/bin/foo-link\n")
schreibe("/var/lib/dpkg/status", "Package: foo\nStatus: install ok installed\nVersion: 2.0\n"
         "Conffiles:\n /etc/foo.conf %s\n\nPackage: alt\nStatus: install ok installed\nVersion: 1.0\n\n" % md5(FOO_CONF))
schreibe("/usr/bin/bar", "fremd\n", 0o755)
# Postfix (DEV 24.11.2026): Startskript, NSS-Modul fuer den Chroot, Kopien aus /etc
NSS = b"\x7fELF nss"
schreibe("/etc/init.d/postfix", "#!/bin/sh\n", 0o755)
schreibe("/etc/init.d/fremd", "#!/bin/sh\n", 0o755)
schreibe("/usr/lib/x86_64-linux-gnu/libnss_mdns.so.2", NSS)
schreibe("/var/lib/dpkg/info/postfix.list", "/.\n/etc\n/etc/init.d\n/etc/init.d/postfix\n")
schreibe("/var/lib/dpkg/info/libnss-mdns:amd64.md5sums", "%s  usr/lib/x86_64-linux-gnu/libnss_mdns.so.2\n"
         "%s  usr/share/beispiel/sub/libnss_alt.so.2\n" % (md5(NSS), md5(NSS)))
schreibe("/var/lib/dpkg/info/libnss-mdns:amd64.list", "/usr/lib/x86_64-linux-gnu/libnss_mdns.so.2\n")
with open(W / "var/lib/dpkg/status", "a") as _f:
    _f.write("Package: postfix\nStatus: install ok installed\nVersion: 3.10.13\n\n"
             "Package: libnss-mdns\nStatus: install ok installed\nArchitecture: amd64\nVersion: 0.15\n\n")
schreibe("/etc/hosts", "127.0.0.1 localhost\n")
schreibe("/var/spool/postfix/etc/hosts", "127.0.0.1 localhost\n")
schreibe("/etc/services", "smtp 25/tcp\n")
schreibe("/var/spool/postfix/etc/services", "smtp 25/tcp\n# untergeschoben\n")
schreibe("/var/spool/postfix/lib/libnss_mdns.so.2", NSS)
schreibe("/var/spool/postfix/lib/libnss_boese.so.2", NSS)
schreibe("/var/spool/postfix/lib/libnss_alt.so.2", NSS)
schreibe("/etc/passwd", "x\n")   # byte-gleich: nur die Liste des Skripts entscheidet
schreibe("/var/spool/postfix/etc/passwd", "x\n")
for _ziel, _link in (("../init.d/postfix", "/etc/rc2.d/S01postfix"), ("../init.d/postfix", "/etc/rc0.d/K01postfix"),
                     ("/tmp/boese", "/etc/rc3.d/S01postfix"), ("../init.d/fremd", "/etc/rc2.d/S02fremd")):
    (W / _link.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(_ziel, W / _link.lstrip("/"))

# ── Sandkasten: signierte Broker-Quelle und Jarvis-Baum ──────────────────────
CODE = "print('signiert')\n"
quelle = W / "var/lib/jarvis-broker/quelle"
(quelle / "backend").mkdir(parents=True)
(quelle / "backend" / "x.py").write_text(CODE)
schluessel = SANDKASTEN / "signatur"
subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "pruef@beispiel.de", "-f", str(schluessel)],
               check=True, capture_output=True)
pub = (SANDKASTEN / "signatur.pub").read_text().split()
schreibe("/etc/jarvis/allowed_signers", 'pruef@beispiel.de namespaces="git" %s %s\n' % (pub[0], pub[1]))
genv = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", HOME=str(SANDKASTEN))


def git(*args):
    return subprocess.run(["git", "-C", str(quelle), *args], capture_output=True, text=True, env=genv)


git("init", "-q")
git("add", "-A")
r = git("-c", "user.name=Pruef", "-c", "user.email=pruef@beispiel.de", "-c", "gpg.format=ssh",
        "-c", "user.signingkey=%s" % schluessel, "commit", "-q", "-S", "-m", "signierter Stand")
if r.returncode != 0:
    abbruch("signierter Commit nicht moeglich: %s" % (r.stderr or r.stdout)[-300:])
schreibe("/opt/jarvis/backend/x.py", CODE)
schreibe("/opt/jarvis/backend/y.py", "print('untergeschoben')\n")

# ── Vergleichsstaende ────────────────────────────────────────────────────────
JETZT = time.time()
START, ENDE = JETZT - 600, JETZT - 300
schreibe("/var/lib/aide/aide.db", b"ALTER STAND", 0o600)
os.utime(W / "var/lib/aide/aide.db", (JETZT - 86400, JETZT - 86400))


def neuer_stand(inhalt=b"NEUER STAND", mtime=None):
    p = schreibe("/var/lib/aide/aide.db.new", inhalt, 0o600)
    t = (START + ENDE) / 2 if mtime is None else mtime
    os.utime(p, (t, t))


def setze_bericht(eintraege, **kw):
    schreibe("/var/log/aide/aide.log", bericht(eintraege, START, ENDE, **kw))


def kontext():
    return A.kontext_laden(JETZT - 86400)


try:
    # ── 1. Bericht ───────────────────────────────────────────────────────────
    print("[1] Bericht lesen")
    E = [("neu", "f++++++++++++++++++", "/usr/bin/bar"),
         ("geaendert", "f >b... mc..H.. .", "/usr/bin/foo"),
         ("entfernt", "f------------------", "/usr/share/alt/weg")]
    b = A.bericht_lesen(bericht(E, START, ENDE))
    pruefe(b["vollstaendig"] and len(b["eintraege"]) == 3, "vollstaendiger Bericht: 3 Eintraege, vollstaendig")
    pruefe(not any(e["pfad"] == "/etc/jarvis/x" for e in b["eintraege"]),
           "die Detailangaben ('File: /...') zaehlen NICHT als Eintrag")
    pruefe(abs((b["start"] or 0) - START) < 2, "Startzeit samt Zeitzonen-Versatz gelesen")
    pruefe(not A.bericht_lesen(bericht(E, START, ENDE, ohne_ende=True))["vollstaendig"],
           "ohne End-Zeile: NICHT vollstaendig")
    pruefe(not A.bericht_lesen(bericht(E, START, ENDE, summe={"neu": 2, "entfernt": 1, "geaendert": 1}))["vollstaendig"],
           "Zusammenfassung passt nicht zu den Eintraegen: NICHT vollstaendig")

    # ── 2. Einteilung ────────────────────────────────────────────────────────
    print("[2] Einteilung")
    k = kontext()
    pruefe(k["baum"] is not None and "backend/x.py" in k["baum"],
           "Positivkontrolle: signierter Stand der Broker-Quelle gelesen (%s)" % k["baum_info"])
    if k["baum"] is None:
        abbruch("ohne lesbaren signierten Stand sind die Code-Pruefungen trivial")

    def grund(art, attrs, pfad, kk=None):
        return A.einteilen({"art": art, "attrs": attrs, "pfad": pfad}, kk or k)

    pruefe((grund("geaendert", "f >b... mc..H.. .", "/usr/bin/foo") or "").startswith("Paket foo"),
           "Paketdatei mit passender Pruefsumme: erklaert durch das Paket")
    schreibe("/usr/bin/foo", FOO + "# untergeschoben\n", 0o755)
    pruefe(grund("geaendert", "f >b... mc..H.. .", "/usr/bin/foo") is None,
           "Paketdatei mit ABWEICHENDER Pruefsumme: nicht erklaert")
    pruefe(A.warum_offen({"art": "geaendert", "attrs": "f >b... mc..H.. .", "pfad": "/usr/bin/foo"}, k)
           .startswith("Inhalt weicht von Paket foo ab"), "Grund benennt das Paket, dessen Inhalt abweicht")
    schreibe("/usr/bin/foo", FOO, 0o755)
    pruefe(grund("geaendert", "f =.p.. .c..... .", "/usr/bin/foo") is None,
           "geaenderte Rechte bei passender Pruefsumme: NICHT erklaert (SUID aendert keinen Inhalt)")
    pruefe(grund("geaendert", "f =.... .c..... .", "/etc/jarvis/geheimnis.key") == "nur Inode-Zeit (ctime)",
           "nur die ctime geaendert: erklaert")
    pruefe(grund("geaendert", "d >b... mci. .. .", "/usr/local/lib/jarvis-broker") == "Verzeichnisinhalt",
           "Verzeichnis mit Inhaltszeit/Groesse/Inode: erklaert (Eintraege stehen einzeln)")
    pruefe(grund("geaendert", "d =.p.. mc.. .. .", "/usr/lib") is None, "Verzeichnis mit geaenderten Rechten: nicht erklaert")
    pruefe(grund("neu", "f++++++++++++++++++", "/usr/bin/bar") is None, "fremde neue Datei: nicht erklaert")
    pruefe(grund("neu", "l++++++++++++++++++", "/usr/bin/foo-link") == "Paket foo", "Link aus der Dateiliste: erklaert")
    pruefe((grund("geaendert", "f >.... mc..H.. .", "/etc/foo.conf") or "").startswith("Konfiguration von foo"),
           "Conffile im Paketstand: erklaert")
    schreibe("/etc/foo.conf", "a=2\n")
    pruefe(grund("geaendert", "f >.... mc..H.. .", "/etc/foo.conf") is None, "lokal geaendertes Conffile: nicht erklaert")
    pruefe((grund("neu", "f++++++++++++++++++",
                  "/usr/lib/python3/dist-packages/foo/__pycache__/__init__.cpython-313.pyc") or "").startswith("Bytecode"),
           "Bytecode zu einer Paketdatei: erklaert")
    pruefe((grund("geaendert", "f =.... mci.H.. .", "/boot/grub/i386-pc/normal.mod") or "").startswith("Paket foo (Kopie"),
           "grub-Modul byteweise gleich der Paketdatei: erklaert")
    schreibe("/boot/grub/i386-pc/normal.mod", b"MOD-ANDERS")
    pruefe(grund("geaendert", "f =.... mci.H.. .", "/boot/grub/i386-pc/normal.mod") is None,
           "grub-Modul ungleich der Paketdatei: nicht erklaert")
    pruefe(grund("geaendert", "f =.... mci.H.. .", "/boot/grub/grub.cfg") is None, "grub.cfg: nie erklaert")
    pruefe((grund("geaendert", "f >b... mc..H.. .", "/opt/jarvis/backend/x.py") or "").startswith("Jarvis-Stand"),
           "Jarvis-Code gleich dem signierten Stand: erklaert")
    pruefe(grund("geaendert", "f >b... mc..H.. .", "/opt/jarvis/backend/y.py") is None,
           "Jarvis-Code, den der signierte Stand nicht enthaelt: nicht erklaert")
    pruefe(grund("entfernt", "f------------------", "/opt/jarvis/backend/alt.py") == "Jarvis-Stand (im signierten Stand entfernt)",
           "Jarvis-Datei, die im signierten Stand fehlt, darf verschwinden")
    pruefe(grund("entfernt", "f------------------", "/opt/jarvis/backend/x.py") is None,
           "Jarvis-Datei, die der signierte Stand ENTHAELT, darf nicht verschwinden")
    # Paketverwaltung nur nach einem dpkg-Lauf
    pruefe(grund("geaendert", "f =.... mci.H.. .", "/etc/ld.so.cache") is None,
           "ld.so.cache ohne dpkg-Lauf seit dem Stand: nicht erklaert")
    k2 = dict(k, dpkg_seit_basis=True)
    pruefe(grund("geaendert", "f =.... mci.H.. .", "/etc/ld.so.cache", k2) == "Paketverwaltung",
           "ld.so.cache nach einem dpkg-Lauf: erklaert")
    # Entfernt: nur mit geaenderter Paketversion seit dem Stand
    k3 = dict(k, basis={"zeit": START, "versionen": {"foo": "1.0", "alt": "1.0"},
                        "pfade": {"/usr/share/foo/weg": "foo", "/usr/share/alt/weg": "alt"}})
    pruefe(grund("entfernt", "f------------------", "/usr/share/foo/weg", k3) == "entfernt mit Update von foo",
           "entfernter Pfad eines aktualisierten Pakets: erklaert")
    pruefe(grund("entfernt", "f------------------", "/usr/share/alt/weg", k3) is None,
           "entfernter Pfad eines UNVERAENDERTEN Pakets: nicht erklaert")

    # ── 2b. Postfix (DEV 24./25.11.2026) ─────────────────────────────────────
    print("[2b] Postfix: Chroot-Kopien, Laufzeit, Startverweise")
    kp = dict(k, dpkg_seit_basis=True, basis={"zeit": START, "versionen": {"foo": "2.0"}, "pfade": {}})
    if kp["dpkg"]["versionen"].get("postfix") != "3.10.13" or "/etc/init.d/postfix" not in kp["dpkg"]["liste"]:
        abbruch("Positivkontrolle: postfix steht nicht im Sandkasten-dpkg – Abschnitt 2b waere trivial")
    pruefe((grund("neu", "f++++++++++++++++++", "/var/spool/postfix/lib/libnss_mdns.so.2") or "")
           .startswith("Paket libnss-mdns (Postfix-Kopie von /usr/lib/x86_64-linux-gnu/libnss_mdns.so.2)"),
           "NSS-Modul im Chroot byteweise gleich der Paketdatei: erklaert")
    pruefe(grund("neu", "f++++++++++++++++++", "/var/spool/postfix/lib/libnss_boese.so.2") is None,
           "NSS-Modul, das kein Paket fuehrt (gleicher Inhalt, anderer Name): nicht erklaert")
    pruefe(grund("neu", "f++++++++++++++++++", "/var/spool/postfix/lib/libnss_alt.so.2") is None,
           "gleichnamige Paketdatei AUSSERHALB von /usr/lib/<multiarch>: keine Quelle")
    schreibe("/var/spool/postfix/lib/libnss_mdns.so.2", NSS + b"x")
    pruefe(grund("geaendert", "f >b... mc..H.. .", "/var/spool/postfix/lib/libnss_mdns.so.2") is None,
           "NSS-Modul im Chroot mit anderem Inhalt: nicht erklaert")
    schreibe("/var/spool/postfix/lib/libnss_mdns.so.2", NSS)
    pruefe(grund("neu", "f++++++++++++++++++", "/var/spool/postfix/etc/hosts") == "Postfix-Kopie von /etc/hosts",
           "Chroot-Kopie byteweise gleich der Datei unter /etc: erklaert")
    pruefe(grund("neu", "f++++++++++++++++++", "/var/spool/postfix/etc/services") is None,
           "Chroot-Kopie mit anderem Inhalt als /etc: nicht erklaert")
    if lies("/etc/passwd") != lies("/var/spool/postfix/etc/passwd"):
        abbruch("Positivkontrolle: /etc/passwd und die Chroot-Datei sind nicht byte-gleich – Probe waere trivial")
    pruefe(grund("neu", "f++++++++++++++++++", "/var/spool/postfix/etc/passwd") is None,
           "Datei im Chroot, die das Postfix-Skript nicht kopiert (auch byte-gleich): nicht erklaert")
    pruefe(grund("geaendert", "f =.p.. .c..... .", "/var/spool/postfix/etc/hosts") is None,
           "Chroot-Kopie mit geaenderten Rechten: nicht erklaert (vor jeder Kopie-Regel)")
    # Laufzeit nur nach Installation/Update von postfix
    pruefe(grund("neu", "s++++++++++++++++++", "/var/spool/postfix/private/smtp", kp) == "Laufzeit von Postfix (installiert/aktualisiert)",
           "neuer Socket nach Installation von postfix: erklaert")
    pruefe(grund("neu", "f++++++++++++++++++", "/var/spool/postfix/pid/master.pid", kp) is not None
           and grund("neu", "f++++++++++++++++++", "/var/lib/postfix/prng_exch", kp) is not None
           and grund("neu", "d++++++++++++++++++", "/var/spool/postfix/maildrop", kp) is not None,
           "PID-Datei, Zufallsvorrat und Warteschlangen-Verzeichnis nach Installation: erklaert")
    pruefe(grund("neu", "f++++++++++++++++++", "/var/spool/postfix/private/smtp", kp) is None,
           "falsche Dateiart (Datei statt Socket): nicht erklaert")
    pruefe(grund("neu", "f++++++++++++++++++", "/var/spool/postfix/pid/boese.sh", kp) is None
           and grund("neu", "f++++++++++++++++++", "/var/spool/postfix/usr/lib/sasl2/x.so", kp) is None,
           "fremde Datei unter /var/spool/postfix: nicht erklaert")
    kp_gleich = dict(kp, basis={"zeit": START, "versionen": {"postfix": "3.10.13"}, "pfade": {}})
    pruefe(grund("neu", "s++++++++++++++++++", "/var/spool/postfix/private/smtp", kp_gleich) is None,
           "neuer Socket OHNE Versionswechsel von postfix: nicht erklaert")
    pruefe(grund("neu", "s++++++++++++++++++", "/var/spool/postfix/private/smtp", dict(kp, dpkg_seit_basis=False)) is None,
           "neuer Socket ohne dpkg-Lauf seit dem Stand: nicht erklaert")
    pruefe(grund("geaendert", "f >.... mc..H.. .", "/var/spool/postfix/pid/master.pid", kp) is None,
           "GEAENDERTE Laufzeitdatei (Inhalt): nicht erklaert – nur das erste Auftauchen")
    pruefe(grund("geaendert", "s =.p.. .c..... .", "/var/spool/postfix/private/smtp", kp) is None,
           "Socket mit geaenderten Rechten: nicht erklaert, auch nach einem Update")
    # Startverweise
    pruefe((grund("neu", "l++++++++++++++++++", "/etc/rc2.d/S01postfix", kp) or "").startswith(
           "Startverweis auf /etc/init.d/postfix (Paket postfix)")
           and grund("neu", "l++++++++++++++++++", "/etc/rc0.d/K01postfix", kp) is not None,
           "Startverweis S/K auf das Paketskript nach einem dpkg-Lauf: erklaert")
    pruefe(grund("neu", "l++++++++++++++++++", "/etc/rc2.d/S01postfix", dict(kp, dpkg_seit_basis=False)) is None,
           "Startverweis ohne dpkg-Lauf seit dem Stand: nicht erklaert")
    pruefe(grund("neu", "l++++++++++++++++++", "/etc/rc3.d/S01postfix", kp) is None,
           "Startverweis mit fremdem Ziel (/tmp/boese): nicht erklaert")
    pruefe(grund("neu", "l++++++++++++++++++", "/etc/rc2.d/S02fremd", kp) is None,
           "Startverweis auf ein Skript, das keinem Paket gehoert: nicht erklaert")
    pruefe(grund("neu", "f++++++++++++++++++", "/etc/rc2.d/S01postfix", kp) is None,
           "Datei statt Verweis unter rcN.d: nicht erklaert")
    kp_weg = dict(kp, basis={"zeit": START, "versionen": {"postfix": "3.9.0"}, "pfade": {"/etc/init.d/postfix": "postfix"}})
    pruefe(grund("entfernt", "l------------------", "/etc/rc2.d/S01postfix", kp_weg) == "Startverweis entfernt mit Update von postfix",
           "entfernter Startverweis eines aktualisierten Pakets: erklaert")
    pruefe(grund("entfernt", "l------------------", "/etc/rc2.d/S01postfix",
                 dict(kp_weg, basis=dict(kp_weg["basis"], versionen={"postfix": "3.10.13"}))) is None,
           "entfernter Startverweis ohne Update: nicht erklaert")

    # Quelle ohne Signatur bzw. fremd beschreibbar: der Code erklaert nichts
    signers = W / "etc/jarvis/allowed_signers"
    gesichert = signers.read_text()
    signers.write_text("fremd@beispiel.de ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n")
    baum, info = A.baum_laden()
    pruefe(baum is None and "signiert" in info, "Spitze mit unbekanntem Schluessel: Quelle erklaert nichts (%s)" % info)
    signers.write_text(gesichert)
    os.chmod(quelle / ".git" / "config", 0o666)
    baum, info = A.baum_laden()
    pruefe(baum is None and "fremd beschreibbar" in info, "fremd beschreibbare Quelle: erklaert nichts (%s)" % info)
    os.chmod(quelle / ".git" / "config", 0o644)
    pruefe(A.baum_laden()[0] is not None, "danach wieder lesbar (Positivkontrolle der Wiederherstellung)")

    # ── 3. Uebernahme ────────────────────────────────────────────────────────
    print("[3] Uebernahme")
    schreibe("/usr/bin/foo", FOO, 0o755)
    sauber = [("geaendert", "f >b... mc..H.. .", "/usr/bin/foo"),
              ("geaendert", "f =.... .c..... .", "/etc/jarvis/geheimnis.key"),
              ("geaendert", "f >b... mc..H.. .", "/opt/jarvis/backend/x.py")]
    setze_bericht(sauber)
    neuer_stand()
    z = A.abgleichen()
    pruefe(z["zustand"] == "uebernommen", "alles erklaert: Zustand 'uebernommen' (ist %s, %s)" % (z["zustand"], z.get("grund")))
    pruefe(lies("/var/lib/aide/aide.db") == b"NEUER STAND", "alles erklaert: aide.db IST der neue Stand")
    pruefe(lies("/var/lib/jarvis-aide/aide.db.vorher") == b"ALTER STAND",
           "alter Stand bleibt als aide.db.vorher im Zustandsverzeichnis")
    pruefe(not (W / "var/lib/aide/aide.db.vorher").exists(),
           "KEINE Sicherung unter /var/lib/aide - AIDE prueft das Verzeichnis und meldete sie bei jedem Lauf")
    with gzip.open(W / "var/lib/jarvis-aide/basis.json.gz", "rt") as f:
        basis = json.load(f)
    pruefe(basis.get("versionen", {}).get("foo") == "2.0" and basis.get("pfade", {}).get("/usr/bin/foo") == "foo",
           "Paketstand zum neuen Stand festgehalten (fuer spaeter entfernte Pfade)")

    schreibe("/var/lib/aide/aide.db", b"ALTER STAND", 0o600)
    setze_bericht(sauber + [("neu", "f++++++++++++++++++", "/usr/bin/bar")])
    neuer_stand(b"NEUER STAND 2")
    z = A.abgleichen()
    pruefe(z["zustand"] == "offen" and z["offen_anzahl"] == 1, "ein nicht erklaerter Eintrag: Zustand 'offen' mit 1")
    pruefe(lies("/var/lib/aide/aide.db") == b"ALTER STAND", "ein nicht erklaerter Eintrag: aide.db UNVERAENDERT")
    pruefe(z["offen"][0]["pfad"] == "/usr/bin/bar" and z["offen"][0]["warum"] == "gehoert keinem Paket",
           "die Liste nennt den Eintrag und den Grund")

    # ── 4. Admin-Uebernahme ──────────────────────────────────────────────────
    print("[4] Admin-Uebernahme")
    A._zustand_schreiben(z)
    r = A.uebernehmen("0" * 16, "pruefer")
    pruefe(not r["ok"] and lies("/var/lib/aide/aide.db") == b"ALTER STAND",
           "fremde Kennung: abgelehnt, aide.db unveraendert")
    pruefe(not A.uebernehmen("kein-hex", "pruefer")["ok"], "ungueltige Kennung: abgelehnt")
    neuer_stand(b"INZWISCHEN ANDERS")
    r = A.uebernehmen(z["kennung"], "pruefer")
    pruefe(not r["ok"] and lies("/var/lib/aide/aide.db") == b"ALTER STAND",
           "aide.db.new seit der Pruefung geaendert: abgelehnt")
    neuer_stand(b"NEUER STAND 2")
    r = A.uebernehmen(z["kennung"], "FIRMA\\pruef.er<>;")
    pruefe(r["ok"] and lies("/var/lib/aide/aide.db") == b"NEUER STAND 2",
           "gesehene Kennung, unveraenderter Stand: uebernommen")
    pruefe(A.zustand_lesen().get("uebernommen_von") == "FIRMA\\pruef.er",
           "Zustand nennt, wer uebernommen hat - Domaenenform erhalten, Fremdzeichen weg (%s)"
           % A.zustand_lesen().get("uebernommen_von"))
    pruefe(not A.uebernehmen(z["kennung"], "pruefer")["ok"], "ein zweites Mal: abgelehnt (kein offener Abgleich mehr)")

    # ── 5. Fail-closed ───────────────────────────────────────────────────────
    print("[5] Fail-closed")
    schreibe("/var/lib/aide/aide.db", b"ALTER STAND", 0o600)
    setze_bericht(sauber)
    neuer_stand(mtime=START - 3600)
    z = A.abgleichen()
    pruefe(z["zustand"] == "fehler" and lies("/var/lib/aide/aide.db") == b"ALTER STAND",
           "neuer Stand aelter als der Bericht: Fehler, nichts uebernommen")
    neuer_stand()
    setze_bericht(sauber, ohne_ende=True)
    z = A.abgleichen()
    pruefe(z["zustand"] == "fehler" and lies("/var/lib/aide/aide.db") == b"ALTER STAND",
           "abgeschnittener Bericht: Fehler, nichts uebernommen")
    setze_bericht(sauber)
    lauf = time.strftime("%Y-%m-%d  %H:%M:%S", time.localtime(START + 60))
    schreibe("/var/log/apt/history.log", "\nStart-Date: %s\nCommandline: apt-get upgrade\nEnd-Date: %s\n" % (lauf, lauf))
    z = A.abgleichen()
    pruefe(z["zustand"] == "offen" and lies("/var/lib/aide/aide.db") == b"ALTER STAND",
           "dpkg lief waehrend der Pruefung: nicht automatisch uebernommen")
    # Der Lauf, der die Pruefung AUSGELOEST hat, endet vor ihr (DEV 24.11.2026:
    # apt 09:31:17, AIDE 09:31:18) - er darf die Uebernahme nicht sperren.
    davor = time.strftime("%Y-%m-%d  %H:%M:%S", time.localtime(START - 1))
    schreibe("/var/log/apt/history.log", "\nStart-Date: %s\nCommandline: apt-get upgrade\nEnd-Date: %s\n" % (davor, davor))
    schreibe("/var/lib/aide/aide.db", b"ALTER STAND", 0o600)
    neuer_stand()
    z = A.abgleichen()
    pruefe(z["zustand"] == "uebernommen", "dpkg endete eine Sekunde VOR der Pruefung: uebernommen (ist %s, %s)"
           % (z["zustand"], z.get("grund")))
    gleich = time.strftime("%Y-%m-%d  %H:%M:%S", time.localtime(START))
    schreibe("/var/log/apt/history.log", "\nStart-Date: %s\nCommandline: apt-get upgrade\nEnd-Date: %s\n" % (davor, gleich))
    schreibe("/var/lib/aide/aide.db", b"ALTER STAND", 0o600)
    neuer_stand()
    z = A.abgleichen()
    pruefe(z["zustand"] == "offen", "dpkg endete in DERSELBEN Sekunde, in der die Pruefung begann: nicht automatisch (fail-closed)")
    (W / "var/log/apt/history.log").unlink()
    schreibe("/var/log/aide/aide.log", "Start timestamp: %s (AIDE 0.19.1)\nAIDE found NO differences between database "
             "and filesystem. Looks okay!!\n\nEnd timestamp: %s (AIDE 0.19.1)\n" % (zeitstempel(START), zeitstempel(ENDE)))
    z = A.abgleichen()
    pruefe(z["zustand"] == "unveraendert", "Bericht ohne Aenderungen: Zustand 'unveraendert' (ist %s)" % z["zustand"])
    (W / "var/log/aide/aide.log").unlink()
    pruefe(A.nach_pruefung() == 1, "fehlender Bericht: Nachlauf endet mit 1 (die Unit wird als gescheitert sichtbar)")
finally:
    shutil.rmtree(SANDKASTEN, ignore_errors=True)

print("ERGEBNIS: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
