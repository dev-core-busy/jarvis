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
  6. Die Dauerlaeufer von ECHT (25.11.2026, 93 offen): nur Zeit/Inode bei
     gleichem Inhalt; Jarvis-Code mit umask-002-Rechten NUR bei signiertem
     Inhalt, eigener Gruppe ohne Mitglieder, ohne s-Bit; vom Broker selbst
     geschriebene Dateien NUR ueber eine lueckenlose Kette (ein fremder
     Eingriff dazwischen reisst sie); Konten NUR mit hinzugekommenen,
     gesperrten Systemkonten nach einem dpkg-Lauf; Protokollrotation,
     AIDE-Arbeitsordner, wireplumber, leeres dynamicmaps.cf; entfernte
     Paketdateien ohne Basis ueber apt/history.log.

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
# Ersatz fuer weitere Module (JSON {modulname: kopie}, in dieser Reihenfolge):
# eigene_dateien zuerst, damit Policy/Freigabe/Daemon die Kopie importieren.
os.environ["JARVIS_BROKER_POLICY"] = str(W / "etc/jarvis/broker-policy.json")
os.environ["JARVIS_BROKER_FREIGABE_STATE"] = str(W / "etc/jarvis/broker-freigabe.state")
for _name, _pfad in json.loads(os.environ.get("JARVIS_AIDE_ERSATZ", "{}")).items():
    import importlib.util
    _eltern, _, _kurz = _name.rpartition(".")
    _paket = importlib.import_module(_eltern)
    _sp = importlib.util.spec_from_file_location(_name, _pfad)
    _m = importlib.util.module_from_spec(_sp)
    sys.modules[_name] = _m
    setattr(_paket, _kurz, _m)
    _sp.loader.exec_module(_m)
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
          "File: /etc/jarvis/x", " Ctime     : 2026-11-23 17:13:04 +0100 | 2026-11-23 18:32:18 +0100", "",
          "Link: /etc/rc2.d/S01x", " Linkname  : /etc/init.d/x                    | /tmp/y", ""]
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
SKRIPT = "#!/bin/sh\necho signiert\n"
(quelle / "deploy").mkdir()
(quelle / "deploy" / "lauf.sh").write_text(SKRIPT)
os.chmod(quelle / "deploy" / "lauf.sh", 0o755)
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
schreibe("/opt/jarvis/deploy/lauf.sh", SKRIPT, 0o755)

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
    pruefe(not any("/tmp/y" in e["pfad"] or "init.d" in e["pfad"] for e in b["eintraege"]),
           "Detailzeile mit absolutem Linkziel (' Linkname : /...') zaehlt NICHT als Eintrag")
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

    # ── 2c. Installierter Stand und Nachziehen der Quelle (2026-11-25) ───────
    print("[2c] Installierter Stand, Quelle nachziehen, Syslog-Socket")
    QK = git("rev-parse", "HEAD").stdout.strip()
    if len(QK) != 40:
        abbruch("Positivkontrolle: Kennung der Sandkasten-Quelle nicht lesbar")
    GD = W / "opt/jarvis/.git"
    ANDERS = "a" * 40

    def git_dir(head, ref_wert=None, packed=None):
        shutil.rmtree(GD, ignore_errors=True)
        (GD / "refs/heads").mkdir(parents=True)
        (GD / "HEAD").write_text(head)
        if ref_wert is not None:
            (GD / "refs/heads/master").write_text(ref_wert + "\n")
        if packed is not None:
            (GD / "packed-refs").write_text(packed)

    git_dir("ref: refs/heads/master\n", ANDERS)
    pruefe(A.installierter_stand() == ANDERS, "installierter Stand ueber HEAD -> refs/heads/master")
    git_dir("ref: refs/heads/master\n", None, "# pack-refs with: peeled\n%s refs/heads/master\n" % ANDERS)
    pruefe(A.installierter_stand() == ANDERS, "installierter Stand ueber packed-refs")
    git_dir(ANDERS + "\n")
    pruefe(A.installierter_stand() == ANDERS, "losgeloester HEAD (Kennung direkt)")
    # Das Ziel ausserhalb von refs/ EXISTIERT und traegt eine gueltige Kennung –
    # sonst waere die Probe auch ohne die Schranke None (Register: falsche Sonde).
    git_dir("ref: refs/heads/../../x_ziel\n")
    (GD / "x_ziel").write_text(ANDERS + "\n")
    pruefe(A.installierter_stand() is None, "Ref mit '..' wird verworfen (Ziel existiert und waere gueltig)")
    git_dir("ref: refs/heads/master\n", "kein-hash")
    pruefe(A.installierter_stand() is None, "Ref-Datei ohne 40 Hex-Zeichen wird verworfen")
    git_dir("ref: refs/heads/master\n")
    (SANDKASTEN / "link_ziel").write_text(ANDERS + "\n")   # gueltig – nur der LINK darf es verhindern
    (GD / "refs/heads/master").symlink_to(SANDKASTEN / "link_ziel")
    pruefe(A.installierter_stand() is None, "Ref-Datei als Link wird nicht gelesen (Ziel waere gueltig)")
    shutil.rmtree(GD, ignore_errors=True)
    (W / "opt/jarvis/echtes_git").mkdir(parents=True, exist_ok=True)
    (W / "opt/jarvis/echtes_git/HEAD").write_text(ANDERS + "\n")   # gueltig – nur der LINK darf es verhindern
    GD.symlink_to(W / "opt/jarvis/echtes_git")
    pruefe(A.installierter_stand() is None, ".git als Link wird nicht gelesen (Ziel waere gueltig)")
    GD.unlink()

    INST = W / "usr/local/lib/jarvis-broker/deploy/security/broker_installieren.sh"
    INST.parent.mkdir(parents=True, exist_ok=True)
    AUFRUF = SANDKASTEN / "installer_aufrufe.log"

    def installer(rc=0, meldung="Signierte Quelle gestellt"):
        INST.write_text("#!/bin/bash\necho \"$*\" >> %s\necho '%s' >&2\nexit %d\n" % (AUFRUF, meldung, rc))
        os.chmod(INST, 0o755)
        if AUFRUF.exists():
            AUFRUF.unlink()

    def aufrufe():
        return AUFRUF.read_text().splitlines() if AUFRUF.exists() else []

    installer()
    git_dir("ref: refs/heads/master\n", QK)
    q = A.quelle_nachziehen()
    pruefe(q.get("ok") and q.get("nachgezogen") is False and not aufrufe(),
           "Quelle schon auf dem installierten Stand: nichts zu tun, kein Installer-Aufruf (%s)" % q)
    git_dir("ref: refs/heads/master\n", ANDERS)
    q = A.quelle_nachziehen()
    pruefe(q.get("ok") and q.get("nachgezogen") is True and aufrufe() == ["--nur-quelle " + ANDERS],
           "abweichender Stand: Installer genau mit --nur-quelle <installierter Commit> (%s)" % aufrufe())
    installer(rc=1, meldung="[Broker-Installation] FEHLER: Stand aaaaaaa ist nicht signiert")
    q = A.quelle_nachziehen()
    pruefe(not q.get("ok") and "nicht signiert" in q.get("grund", ""),
           "Installer scheitert: Grund steht im Ergebnis (%s)" % q.get("grund"))
    kq = dict(k, quelle_nachziehen=q)
    pruefe("nicht signiert" in A.warum_offen({"art": "geaendert", "attrs": "f >b... mc..H.. .",
                                              "pfad": "/opt/jarvis/backend/y.py"}, kq),
           "der Grund erscheint bei jeder offenen Code-Datei")
    installer()
    os.chmod(INST, 0o777)
    q = A.quelle_nachziehen()
    pruefe(not q.get("ok") and "root-eigen" in q.get("grund", "") and not aufrufe(),
           "fremd beschreibbarer Installer wird NICHT ausgefuehrt")
    shutil.rmtree(GD, ignore_errors=True)
    q = A.quelle_nachziehen()
    pruefe(not q.get("ok") and "nicht lesbar" in q.get("grund", ""), "ohne lesbaren Stand: nichts gestartet, Grund genannt")
    # Der Abgleich ruft das Nachziehen WIRKLICH (ueber kontext_laden)
    installer()
    git_dir("ref: refs/heads/master\n", ANDERS)
    kk2 = A.kontext_laden(JETZT - 86400)
    pruefe(aufrufe() == ["--nur-quelle " + ANDERS] and (kk2.get("quelle_nachziehen") or {}).get("nachgezogen"),
           "kontext_laden zieht die Quelle vor dem Einteilen nach (%s)" % aufrufe())
    shutil.rmtree(GD, ignore_errors=True)
    INST.unlink()

    # Syslog-Socket im Postfix-Chroot (ECHT 25.11.: neu, gehoerte keinem Paket)
    kp2 = dict(k, dpkg_seit_basis=True, basis={"zeit": START, "versionen": {}, "pfade": {}})
    pruefe(grund("neu", "s++++++++++++++++++", "/var/spool/postfix/dev/log", kp2) is not None,
           "Syslog-Socket im Chroot nach Installation von postfix: erklaert")
    pruefe(grund("geaendert", "s =.... mci.... .", "/var/spool/postfix/dev/log") == "Laufzeit-Socket neu angelegt",
           "Syslog-Socket neu angelegt (nur Zeit/Inode): erklaert")
    pruefe(grund("geaendert", "s =.p.. mci.... .", "/var/spool/postfix/dev/log") is None,
           "Syslog-Socket mit geaenderten Rechten: nicht erklaert")
    pruefe(grund("geaendert", "s =.... mci.... .", "/var/spool/postfix/private/fremd") is None
           and grund("geaendert", "f =.... mci.H.. .", "/var/spool/postfix/dev/log") is None
           and grund("geaendert", "l =.... mci.... .", "/var/spool/postfix/dev/log") is None,
           "anderer Socket bzw. Datei statt Socket: nicht erklaert")

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

    # ── 6. Dauerlaeufer von ECHT (25.11.2026) ────────────────────────────────
    print("[6a] Pruefsummen aus den Detailangaben, apt-Historie")
    import base64 as _b64
    ED = importlib.import_module("backend.eigene_dateien")
    if str(ED._p("/etc/jarvis/broker.conf")) != str(W) + "/etc/jarvis/broker.conf":
        abbruch("eigene_dateien benutzt die Sandkasten-Wurzel nicht")

    def b64(hexwert):
        return _b64.b64encode(bytes.fromhex(hexwert)).decode()

    def mit_details(eintraege, details):
        """Bericht mit Detailangaben im Format von AIDE 0.19 (umbrochenes base64)."""
        roh = bericht(eintraege, START, ENDE)
        zus = []
        for pfad, (alt, neu) in details.items():
            zus += ["File: %s" % pfad, " Size      : 10                               | 11",
                    " SHA256    : %-32s | %s" % (alt[:32], neu[:32]),
                    "             %-32s | %s" % (alt[32:], neu[32:]),
                    " SHA512    : xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy", ""]
        roh = roh.replace("Detailed information about changes:\n" + "-" * 51 + "\n\n",
                          "Detailed information about changes:\n" + "-" * 51 + "\n\n" + "\n".join(zus) + "\n")
        # Wie in AIDE 0.19: danach die Attribute der Datenbank, mit eigener SHA256
        return roh.replace("End timestamp:", "The attributes of the (uncompressed) database(s):\n" + "-" * 51
                           + "\n\n/var/lib/aide/aide.db\n SHA256    : " + "Q" * 32 + "\n             "
                           + "Q" * 12 + "\n\nEnd timestamp:")

    HA, HB = hashlib.sha256(b"a").hexdigest(), hashlib.sha256(b"b").hexdigest()
    bd = A.bericht_lesen(mit_details([("geaendert", "f >.... mc..H.. .", "/etc/jarvis/broker.conf")],
                                     {"/etc/jarvis/broker.conf": (b64(HA), b64(HB))}))
    teile = bd.get("sha256", {}).get("/etc/jarvis/broker.conf") or ["", ""]
    pruefe(bd["vollstaendig"] and ED.aus_aide(teile[0]) == HA and ED.aus_aide(teile[1]) == HB,
           "SHA256 alt/neu aus den Detailangaben gelesen, auch ueber die umbrochene Zeile")
    pruefe(ED.aus_aide(teile[0][:30]) is None, "abgeschnittene Pruefsumme gilt nicht")
    pruefe(set(bd.get("sha256", {})) == {"/etc/jarvis/broker.conf"},
           "Pruefsummen nur fuer Dateien mit SHA256-Detailzeile – die der Datenbank-Attribute haengt "
           "an keiner Datei (%s)" % sorted(bd.get("sha256", {})))
    schreibe("/var/log/apt/history.log", "\nStart-Date: 2026-11-25  06:06:50\nUpgrade: zstd:amd64 (1.5.7+dfsg-1, "
             "1.5.7+dfsg-1+deb13u1), libzstd1:amd64 (1.5.7+dfsg-1, 1.5.7+dfsg-1+deb13u1)\nInstall: postfix:amd64 "
             "(3.10.13-0+deb13u1), libnsl2:amd64 (1.3.0-3+b3, automatic)\nEnd-Date: 2026-11-25  06:06:52\n")
    bl = A._apt_bloecke()
    pruefe(len(bl) == 1 and bl[0][2] == {"zstd", "libzstd1", "postfix", "libnsl2"},
           "apt-Historie: Paketnamen aus Install/Upgrade gelesen (%s)" % (bl[0][2] if bl else None))
    (W / "var/log/apt/history.log").unlink()
    k6 = A.kontext_laden(JETZT - 86400)
    pruefe(not A._paket_geaendert(dict(k6, basis=None, pakete_seit=set()), "foo"),
           "OHNE Basis und ohne apt-Eintrag gilt ein Paket NICHT als geaendert (vorher fail-open)")
    pruefe(A._paket_geaendert(dict(k6, basis=None, pakete_seit={"foo"}), "foo"),
           "ohne Basis, Paket in der apt-Historie seit dem Stand: geaendert")

    def g6(art, attrs, pfad, kk=None):
        return A.einteilen({"art": art, "attrs": attrs, "pfad": pfad}, kk or k6)

    print("[6b] Nur Zeit/Inode bei gleichem Inhalt")
    pruefe(g6("geaendert", "f =.... mc..... .", "/srv/.aaa.ini") == "Inhalt und Rechte unveraendert (nur Zeit/Inode)",
           "mtime/ctime ohne Pruefsummen-Aenderung: erklaert (SentinelOne-Koeder)")
    pruefe(g6("geaendert", "f =.... mci.... .", "/usr/local/sbin/jarvis-broker-admin") is not None,
           "neu installierte, byte-gleiche Kopie (neue Inode): erklaert")
    pruefe(g6("geaendert", "f =.... mc..H.. .", "/srv/.aaa.ini") is None, "Pruefsumme geaendert: nicht erklaert")
    pruefe(g6("geaendert", "f >.... mc..... .", "/srv/.aaa.ini") is None, "Groesse geaendert: nicht erklaert")
    pruefe(g6("geaendert", "f =.p.. mc..... .", "/srv/.aaa.ini") is None, "Rechte geaendert: nicht erklaert")
    pruefe(g6("geaendert", "l =.... mc..... .", "/usr/bin/foo-link2") is None, "Verweis: die Regel gilt nur fuer Dateien")

    print("[6c] Jarvis-Code mit umask-002-Rechten")
    X = W / "opt/jarvis/backend/x.py"
    os.chmod(X, 0o664)
    try:
        import grp as _grp
        import pwd as _pwd
        _eigene = _grp.getgrgid(os.getgid())
        if _eigene.gr_mem or _pwd.getpwuid(os.getuid()).pw_gid != os.getgid():
            abbruch("Positivkontrolle: Primaergruppe des Pruefers hat Mitglieder – 6c waere nicht messbar")
    except KeyError:
        abbruch("eigene Gruppe nicht aufloesbar")
    if os.stat(X).st_mode & 0o777 != 0o664:
        abbruch("Positivkontrolle: Rechte 664 nicht gesetzt")
    pruefe((g6("geaendert", "f >bp.. mc..HA. .", "/opt/jarvis/backend/x.py") or "").startswith("Jarvis-Stand (signiert; Rechte"),
           "signierter Inhalt, 644 -> 664, eigene Gruppe ohne Mitglieder: erklaert")
    pruefe(A.warum_offen({"art": "geaendert", "attrs": "f >bp.. mc..HA. .", "pfad": "/opt/jarvis/backend/y.py"}, k6)
           == "Rechte oder Eigentuemer geaendert" and g6("geaendert", "f >bp.. mc..HA. .", "/opt/jarvis/backend/y.py") is None,
           "nicht signierter Inhalt mit 664: nicht erklaert")
    os.chmod(W / "opt/jarvis/backend/y.py", 0o644)
    pruefe(g6("geaendert", "f >bpu. mc..HA. .", "/opt/jarvis/backend/x.py") is None, "Eigentuemer geaendert: nicht erklaert")
    for modus, text in ((0o666, "fuer alle beschreibbar"), (0o4664, "SUID-Bit"), (0o775, "x-Bit ohne Modus 755 im Stand")):
        os.chmod(X, modus)
        pruefe(g6("geaendert", "f >bp.. mc..HA. .", "/opt/jarvis/backend/x.py") is None, "%s: nicht erklaert" % text)
    os.chmod(X, 0o664)
    LS = W / "opt/jarvis/deploy/lauf.sh"
    os.chmod(LS, 0o775)
    pruefe(g6("geaendert", "f =.p.. mc..HA. .", "/opt/jarvis/deploy/lauf.sh") is not None,
           "ausfuehrbare Datei des Stands (100755) mit 775: erklaert")
    os.chmod(LS, 0o664)
    pruefe(g6("geaendert", "f =.p.. mc..HA. .", "/opt/jarvis/deploy/lauf.sh") is None,
           "ausfuehrbare Datei des Stands ohne x-Bit: nicht erklaert")
    os.chmod(LS, 0o755)
    _echt_grp = sys.modules["grp"]

    class _FremdeMitglieder:
        @staticmethod
        def getgrgid(gid):
            g = _echt_grp.getgrgid(gid)
            return type("G", (), {"gr_mem": ["fremd"], "gr_gid": g.gr_gid, "gr_name": g.gr_name})()
    sys.modules["grp"] = _FremdeMitglieder
    try:
        pruefe(g6("geaendert", "f >bp.. mc..HA. .", "/opt/jarvis/backend/x.py") is None,
               "Gruppe mit weiteren Mitgliedern: 664 nicht erklaert")
    finally:
        sys.modules["grp"] = _echt_grp
    pruefe(g6("geaendert", "f =.p.. .c..... .", "/usr/bin/foo") is None,
           "Rechteaenderung AUSSERHALB von /opt/jarvis: weiter nicht erklaert")
    schreibe("/usr/local/lib/jarvis-broker/backend/x.py", CODE, 0o664)
    pruefe(g6("geaendert", "f >bp.. mc..HA. .", "/usr/local/lib/jarvis-broker/backend/x.py") is None,
           "root-eigene Broker-Kopie mit 664 (signierter Inhalt): nicht erklaert")
    os.chmod(X, 0o644)

    print("[6d] Vom Broker selbst geschriebene Dateien: lueckenlose Kette")
    BC = W / "etc/jarvis/broker.conf"
    reg = W / "var/lib/jarvis-aide/eigene.json"
    if reg.exists():
        reg.unlink()
    schreibe("/etc/jarvis/broker.conf", "A=1\n")
    h0 = ED.sha(BC)
    with ED.schreibt(BC):
        BC.write_text("A=1\nMAIL_RELAY=x\n")
    with ED.schreibt(BC):
        BC.write_text("A=1\nMAIL_RELAY=y\n")
    h2 = ED.sha(BC)
    pruefe(ED.erklaert("/etc/jarvis/broker.conf", h0, h2), "zwei Broker-Schreibungen hintereinander: Kette lueckenlos")
    pruefe(not ED.erklaert("/etc/jarvis/broker.conf", hashlib.sha256(b"fremd").hexdigest(), h2),
           "Kette beginnt nicht beim Stand aus aide.db: nicht erklaert")
    BC.write_text("A=1\nMAIL_RELAY=y\nSSH_NETZE=0.0.0.0/0\n")   # fremder Eingriff, nicht vermerkt
    with ED.schreibt(BC):
        BC.write_text(BC.read_text() + "MAIL_SPRACHE=de\n")       # Broker liest, aendert, schreibt
    h4 = ED.sha(BC)
    pruefe(not ED.erklaert("/etc/jarvis/broker.conf", h0, h4),
           "fremder Eingriff zwischen zwei Broker-Schreibungen: Kette reisst, nicht erklaert")
    e6 = {"art": "geaendert", "attrs": "f >.... mc..H.. .", "pfad": "/etc/jarvis/broker.conf"}
    pruefe(g6(**e6, kk=dict(k6, sha256={"/etc/jarvis/broker.conf": (b64(h0), b64(h2))}))
           == "vom Broker geschrieben (vermerkt)", "ueber einteilen: Pruefsummen aus dem Bericht, Kette lueckenlos")
    pruefe(g6(**e6, kk=dict(k6, sha256={"/etc/jarvis/broker.conf": (b64(h0), b64(h4))})) is None,
           "ueber einteilen: Kette mit fremdem Eingriff: nicht erklaert")
    pruefe(g6(**e6, kk=dict(k6, sha256={})) is None, "ohne Pruefsummen im Bericht: nicht erklaert")
    pruefe(g6("geaendert", "f >.p.. mc..H.. .", "/etc/jarvis/broker.conf",
              dict(k6, sha256={"/etc/jarvis/broker.conf": (b64(h0), b64(h2))})) is None,
           "Rechte geaendert: nicht erklaert, auch mit Kette")
    schreibe("/etc/jarvis/anders.conf", "x\n")
    with ED.schreibt(W / "etc/jarvis/anders.conf"):
        (W / "etc/jarvis/anders.conf").write_text("y\n")
    pruefe("/etc/jarvis/anders.conf" not in ED.lesen(), "Datei ausserhalb der Liste wird nicht vermerkt")
    # Die echten Schreibstellen: Policy, Freigabe-Zustand, Meta-Ops des Daemons
    POL = importlib.import_module("backend.broker.policy")
    FRG = importlib.import_module("backend.broker.freigabe")
    if str(POL.POLICY_FILE) != str(W / "etc/jarvis/broker-policy.json") or \
            str(FRG.ZUSTAND) != str(W / "etc/jarvis/broker-freigabe.state"):
        abbruch("Policy/Freigabe nicht auf den Sandkasten umgelenkt (Modul frueher geladen?)")
    POL._atomar_schreiben(POL.POLICY_FILE, {"ops": {"a": {}}})
    p1 = ED.sha(POL.POLICY_FILE)
    POL._atomar_schreiben(POL.POLICY_FILE, {"ops": {"a": {}, "b": {}}})
    pruefe(ED.erklaert("/etc/jarvis/broker-policy.json", None, ED.sha(POL.POLICY_FILE))
           and p1 is not None, "Policy: neu angelegt und geaendert durch den Broker – Kette vermerkt")
    FRG._schreibe_privat(FRG.ZUSTAND, '{"letzter_schritt": 1}')
    pruefe(ED.erklaert("/etc/jarvis/broker-freigabe.state", None, ED.sha(FRG.ZUSTAND)),
           "Freigabe-Zustand: Schreibung des Brokers vermerkt")
    try:
        DMN = importlib.import_module("backend.broker.daemon")
    except Exception as ex:  # noqa: BLE001
        abbruch("Broker-Daemon nicht ladbar: %s" % ex)
    _meta_echt = DMN.meta

    class _Meta:
        @staticmethod
        def behandeln(op, args, peer=""):
            BC.write_text(BC.read_text() + "RDP_ERLAUBT=%s\n" % op)
            return {"ok": True}
    DMN.meta = _Meta
    try:
        vor = ED.sha(BC)
        DMN._meta_mit_vermerk("broker.rdp", {}, peer="")
        nach_meta = ED.sha(BC)
        pruefe(ED.erklaert("/etc/jarvis/broker.conf", vor, nach_meta),
               "Meta-Op (Admin, auch ueber Shell-Skripte): Aenderung an broker.conf vermerkt")
        DMN._meta_mit_vermerk("shell_root", {}, peer="")
        pruefe(not ED.erklaert("/etc/jarvis/broker.conf", nach_meta, ED.sha(BC)),
               "KEINE Meta-Op (z. B. shell_root): Aenderung wird NICHT vermerkt")
    finally:
        DMN.meta = _meta_echt

    print("[6e] Konten")
    PW0 = "root:x:0:0:root:/root:/bin/bash\njarvis:x:1001:1001::/home/jarvis:/bin/bash\n"
    GR0 = "root:x:0:\nsudo:x:27:admin\njarvis:x:1001:\n"
    SH0 = "root:$y$geheim:20000:0:99999:7:::\njarvis:!:20000:0:99999:7:::\n"
    GS0 = "root:*::\nsudo:*::admin\njarvis:!::\n"
    for d, inh in (("passwd", PW0), ("group", GR0), ("shadow", SH0), ("gshadow", GS0)):
        schreibe("/etc/" + d, inh)
    konten0 = A.konten_lesen()
    if not konten0 or "root" not in konten0.get("passwd", {}):
        abbruch("Positivkontrolle: Kontenstand nicht lesbar")
    pruefe(konten0["shadow"]["root"][0][0] != "$y$geheim" and "geheim" not in json.dumps(konten0),
           "Kennwortfelder stehen nur als Pruefsumme im Kontenstand")
    kk6 = dict(k6, dpkg_seit_basis=True, basis={"zeit": START, "versionen": {}, "pfade": {}, "konten": konten0})

    def konten(pw=PW0, gr=GR0, sh=SH0, gs=GS0):
        for d, inh in (("passwd", pw), ("group", gr), ("shadow", sh), ("gshadow", gs)):
            schreibe("/etc/" + d, inh)

    PF = "postfix:x:114:118::/var/spool/postfix:/usr/sbin/nologin\n"
    konten(PW0 + PF, GR0 + "postfix:x:118:\npostdrop:x:119:\n", SH0 + "postfix:!:20416::::::\n",
           GS0 + "postfix:!::\npostdrop:!::\n")
    alle = [g6("geaendert", "f >.... mci.H.. .", "/etc/" + d, kk6) for d in ("passwd", "group", "shadow", "gshadow")]
    pruefe(all(alle), "postfix/postdrop wie auf ECHT hinzugekommen: alle vier Dateien erklaert (%s)" % alle)
    schreibe("/etc/passwd-", PW0)
    pruefe(g6("geaendert", "f >.... mc..H.. .", "/etc/passwd-", kk6) is not None,
           "Sicherung passwd- (Zwischenstand): erklaert")
    pruefe(g6("geaendert", "f >.... mci.H.. .", "/etc/passwd", dict(kk6, dpkg_seit_basis=False)) is None,
           "ohne dpkg-Lauf seit dem Stand: nicht erklaert")
    pruefe(g6("geaendert", "f >.... mci.H.. .", "/etc/passwd",
              dict(kk6, basis=dict(kk6["basis"], konten=None))) is None, "ohne Kontenstand in der Basis: nicht erklaert")
    for pw, text in ((PW0 + "boese:x:0:0::/root:/usr/sbin/nologin\n", "neues Konto mit UID 0"),
                     (PW0 + "boese:x:115:115::/:/bin/bash\n", "neues Systemkonto mit Anmeldeshell"),
                     (PW0 + "mensch:x:1002:1002::/home/m:/usr/sbin/nologin\n", "neues Konto mit UID >= 1000"),
                     (PW0.replace("/root:/bin/bash", "/root:/bin/sh"), "bestehendes Konto geaendert"),
                     ("jarvis:x:1001:1001::/home/jarvis:/bin/bash\n", "bestehendes Konto entfernt")):
        konten(pw=pw)
        pruefe(g6("geaendert", "f >.... mci.H.. .", "/etc/passwd", kk6) is None, "%s: nicht erklaert" % text)
    konten(PW0 + PF, GR0.replace("sudo:x:27:admin", "sudo:x:27:admin,postfix"))
    pruefe(g6("geaendert", "f >.... mci.H.. .", "/etc/group", kk6) is None,
           "neues Konto in eine BESTEHENDE Gruppe (sudo) aufgenommen: nicht erklaert")
    konten(PW0 + PF, GR0 + "boese:x:120:jarvis\n")
    pruefe(g6("geaendert", "f >.... mci.H.. .", "/etc/group", kk6) is None,
           "neue Gruppe mit einem BESTEHENDEN Konto als Mitglied: nicht erklaert")
    konten(PW0 + PF, GR0 + "boese:x:0:\n")
    pruefe(g6("geaendert", "f >.... mci.H.. .", "/etc/group", kk6) is None, "neue Gruppe mit GID 0: nicht erklaert")
    konten(PW0 + PF, sh=SH0 + "postfix:$y$kennwort:20416::::::\n")
    pruefe(g6("geaendert", "f >.... mci.H.. .", "/etc/shadow", kk6) is None,
           "neues Konto MIT Kennwort (nicht gesperrt): nicht erklaert")
    konten(PW0 + PF, sh=SH0.replace("jarvis:!:", "jarvis:$y$neu:") + "postfix:!:20416::::::\n")
    pruefe(g6("geaendert", "f >.... mci.H.. .", "/etc/shadow", kk6) is None,
           "Kennwort eines bestehenden Kontos geaendert: nicht erklaert")
    konten(PW0 + PF, gs=GS0 + "postdrop:$y$x::\n")
    pruefe(g6("geaendert", "f >.... mci.H.. .", "/etc/gshadow", kk6) is None,
           "neue Gruppe mit Gruppenkennwort: nicht erklaert")
    konten()
    # Der Kontenstand wird mit dem Abgleich festgehalten und mit der Uebernahme Basis
    schreibe("/var/lib/aide/aide.db", b"ALTER STAND", 0o600)
    setze_bericht([("neu", "f++++++++++++++++++", "/usr/bin/bar")])
    neuer_stand(b"NEUER STAND 6")
    z6 = A.abgleichen()
    A._zustand_schreiben(z6)
    pruefe((A._konten_kandidat_lesen() or {}).get("passwd", {}).get("root") is not None,
           "Abgleich haelt den Kontenstand zur Pruefung fest")
    konten(PW0 + PF)   # nach der Pruefung angelegt: gehoert NICHT in die Basis
    A.uebernehmen(z6["kennung"], "pruefer")
    with gzip.open(W / "var/lib/jarvis-aide/basis.json.gz", "rt") as f:
        basis6 = json.load(f)
    pruefe("root" in (basis6.get("konten") or {}).get("passwd", {})
           and "postfix" not in (basis6.get("konten") or {}).get("passwd", {}),
           "Uebernahme schreibt den Kontenstand ZUR PRUEFUNG in die Basis (nicht den spaeteren)")
    konten()

    print("[6f] Rotation, Arbeitsordner, wireplumber, dynamicmaps, entfernte Paketdateien")
    pruefe(g6("geaendert", "f <b... mci.H.. .", "/var/log/boot.log.2") is not None
           and g6("geaendert", "f >b... mc..H.. .", "/var/log/aide/aide.log.0") is not None
           and g6("geaendert", "f =.... mci.H.. .", "/var/log/vmware-vmsvc-root.1.log") is not None,
           "rotierte/neu geschriebene Protokolle ohne Debian-Regel: erklaert")
    pruefe(g6("geaendert", "f >b... mc..H.. .", "/var/log/auth.log") is None,
           "anderes Protokoll (nicht in der Liste): nicht erklaert")
    pruefe(g6("geaendert", "f >bp.. mc..H.. .", "/var/log/boot.log") is None, "Protokoll mit geaenderten Rechten: nicht erklaert")
    schreibe("/var/log/mail.log.1", "x\n", 0o640)
    pruefe(g6("neu", "f++++++++++++++++++", "/var/log/mail.log.1") == "Protokollrotation (neue Fassung)",
           "neue rotierte Fassung: erklaert")
    schreibe("/var/log/mail.log.2", "x\n", 0o750)
    pruefe(g6("neu", "f++++++++++++++++++", "/var/log/mail.log.2") is None, "neue 'Fassung' mit x-Bit: nicht erklaert")
    schreibe("/var/log/boese.sh", "x\n", 0o640)
    pruefe(g6("neu", "f++++++++++++++++++", "/var/log/boese.sh") is None, "neue Datei ohne Rotationsnamen: nicht erklaert")
    pruefe(g6("entfernt", "f------------------", "/var/log/aide/aide.log.5.gz") is not None,
           "aelteste Fassung entfernt: erklaert")
    (W / "var/lib/aide/dailyaidecheck.old.oSYHT2jW94/dailyaidecheck").mkdir(parents=True)
    pruefe(g6("neu", "d++++++++++++++++++", "/var/lib/aide/dailyaidecheck.old.oSYHT2jW94/dailyaidecheck")
           == "Arbeitsordner der AIDE-Pruefung", "umbenannter Arbeitsordner von dailyaidecheck: erklaert")
    _aide_echt = A._aide_benutzer
    A._aide_benutzer = lambda uid: False
    try:
        pruefe(g6("neu", "d++++++++++++++++++", "/var/lib/aide/dailyaidecheck.old.oSYHT2jW94/dailyaidecheck") is None,
               "Arbeitsordner, der nicht _aide gehoert: nicht erklaert")
    finally:
        A._aide_benutzer = _aide_echt
    (W / "var/lib/aide/boese").mkdir()
    pruefe(g6("neu", "d++++++++++++++++++", "/var/lib/aide/boese") is None, "anderer Ordner unter /var/lib/aide: nicht erklaert")
    pruefe(g6("geaendert", "f =.... mc..H.. .", "/home/admin/.local/state/wireplumber/stream-properties") is not None
           and g6("geaendert", "f =.... mc..H.. .", "/home/admin/.bashrc") is None,
           "wireplumber-Zustand erklaert, andere Datei im Home nicht")
    kpf = dict(k6, dpkg_seit_basis=True, basis=None, pakete_seit={"postfix"})
    schreibe("/etc/postfix/dynamicmaps.cf", "# dict-type\tso-name (pathname)\tdict-function\tmkmap-function\n")
    pruefe(g6("neu", "f++++++++++++++++++", "/etc/postfix/dynamicmaps.cf", kpf) is not None,
           "dynamicmaps.cf nur mit Kopfzeile nach Installation von postfix: erklaert")
    pruefe(g6("neu", "f++++++++++++++++++", "/etc/postfix/dynamicmaps.cf", dict(kpf, pakete_seit=set())) is None,
           "dynamicmaps.cf ohne Installation von postfix: nicht erklaert")
    schreibe("/etc/postfix/dynamicmaps.cf", "# kopf\npcre\t/tmp/boese.so\tdict_pcre_open\n")
    pruefe(g6("neu", "f++++++++++++++++++", "/etc/postfix/dynamicmaps.cf", kpf) is None,
           "dynamicmaps.cf mit einer Bibliothek: nicht erklaert")
    with open(W / "var/lib/dpkg/info/foo.list", "a") as f:
        f.write("/usr/share/doc/foo\n/usr/share/doc/foo/changelog.Debian.gz\n/usr/share/doc\n")
    schreibe("/var/lib/dpkg/info/zwei.list", "/usr/share/doc\n")
    kd = A.kontext_laden(JETZT - 86400)
    kd = dict(kd, basis=None, pakete_seit={"foo"})
    pruefe((g6("entfernt", "f------------------", "/usr/share/doc/foo/changelog.Debian.amd64.gz", kd) or "")
           .startswith("entfernt mit Update von foo"), "ohne Basis: Datei im Verzeichnis eines aktualisierten Pakets erklaert")
    pruefe(g6("entfernt", "f------------------", "/usr/share/doc/foo/changelog.Debian.amd64.gz", dict(kd, pakete_seit=set()))
           is None, "Paket seit dem Stand nicht angefasst: nicht erklaert")
    pruefe(g6("entfernt", "f------------------", "/usr/share/doc/weg.gz", dict(kd, pakete_seit={"foo", "zwei"})) is None,
           "Verzeichnis gehoert mehreren Paketen: nicht erklaert")

    # ── 7. Mail von DEV (26.11.2026, 258 nicht erklaert) ─────────────────────
    print("[7a] Rechte in der signierten Broker-Quelle")
    QL = "/var/lib/jarvis-broker/quelle"
    k7 = A.kontext_laden(JETZT - 86400)
    if "deploy/lauf.sh" not in A._AUSFUEHRBAR or "backend/x.py" in A._AUSFUEHRBAR:
        abbruch("Positivkontrolle: Modus 100755 aus dem signierten Stand nicht gelesen – 7a waere trivial")

    def g7(art, attrs, pfad, kk=None):
        return A.einteilen({"art": art, "attrs": attrs, "pfad": pfad}, kk or k7)

    QS, QX = quelle / "deploy" / "lauf.sh", quelle / "backend" / "x.py"
    os.chmod(QS, 0o755)
    os.chmod(QX, 0o644)
    pruefe((g7("geaendert", "f =.p.. mci..A. .", QL + "/deploy/lauf.sh") or "").startswith("Jarvis-Stand (signierte Quelle"),
           "Skript der Quelle 644 -> 755 wie im signierten Stand (100755): erklaert")
    pruefe(g7("geaendert", "f >.p.. mci.HA. .", QL + "/backend/x.py") is not None,
           "Datei der Quelle mit 644 wie im Stand: erklaert")
    for modus, text in ((0o775, "775 (keine umask-002-Toleranz in der root-eigenen Quelle)"),
                        (0o644, "Skript ohne x-Bit, obwohl 100755 im Stand"), (0o4755, "SUID-Bit")):
        os.chmod(QS, modus)
        pruefe(g7("geaendert", "f =.p.. mci..A. .", QL + "/deploy/lauf.sh") is None, "Quelle mit %s: nicht erklaert" % text)
    os.chmod(QS, 0o755)
    os.chmod(QX, 0o755)
    pruefe(g7("geaendert", "f =.p.. mci..A. .", QL + "/backend/x.py") is None,
           "Datei der Quelle mit x-Bit, im Stand 100644: nicht erklaert")
    os.chmod(QX, 0o644)
    QX.write_text(CODE + "# untergeschoben\n")
    pruefe(g7("geaendert", "f >.p.. mci.HA. .", QL + "/backend/x.py") is None,
           "Quelle mit anderem Inhalt als der signierte Stand: nicht erklaert")
    QX.write_text(CODE)
    os.chmod(QX, 0o644)
    _rk = A._root_konto
    A._root_konto = lambda uid: False
    try:
        pruefe(g7("geaendert", "f =.p.. mci..A. .", QL + "/deploy/lauf.sh") is None,
               "Datei der Quelle gehoert nicht root: nicht erklaert")
    finally:
        A._root_konto = _rk
    pruefe(g7("geaendert", "f =.pu. mci..A. .", QL + "/deploy/lauf.sh") is None,
           "Eigentuemer der Quelle geaendert: nicht erklaert")

    print("[7b] Debian-Sicherungen, dev_reset, Protokolle")
    for pfad in ("/var/backups/dpkg.status.0", "/var/backups/dpkg.status.1.gz", "/var/backups/alternatives.tar.0",
                 "/var/backups/apt.extended_states.2.gz", "/root/dev-abweichungen-20261125-073844-4056.tgz"):
        schreibe(pfad, "x\n", 0o644)
    pruefe(g7("geaendert", "f >b... mci.H.. .", "/var/backups/dpkg.status.0") is not None
           and g7("neu", "f++++++++++++++++++", "/var/backups/dpkg.status.1.gz") is not None
           and g7("geaendert", "f >b... mci.H.. .", "/var/backups/alternatives.tar.0") is not None
           and g7("geaendert", "f >b... mci.H.. .", "/var/backups/apt.extended_states.2.gz") is not None,
           "naechtliche Rotation von dpkg-db-backup: erklaert")
    pruefe(g7("entfernt", "f------------------", "/var/backups/dpkg.status.6.gz") is not None,
           "aelteste Sicherung der Paketdatenbank entfernt: erklaert")
    pruefe(g7("geaendert", "f =.p.. mci.... .", "/var/backups/dpkg.status.0") is None,
           "Sicherung mit geaenderten Rechten: nicht erklaert")
    os.chmod(W / "var/backups/dpkg.status.0", 0o755)
    pruefe(g7("geaendert", "f >b... mci.H.. .", "/var/backups/dpkg.status.0") is None, "Sicherung mit x-Bit: nicht erklaert")
    os.chmod(W / "var/backups/dpkg.status.0", 0o666)
    pruefe(g7("geaendert", "f >b... mci.H.. .", "/var/backups/dpkg.status.0") is None,
           "Sicherung fuer alle beschreibbar: nicht erklaert")
    os.chmod(W / "var/backups/dpkg.status.0", 0o644)
    _rk = A._root_konto
    A._root_konto = lambda uid: False
    try:
        pruefe(g7("geaendert", "f >b... mci.H.. .", "/var/backups/dpkg.status.0") is None
               and g7("neu", "f++++++++++++++++++", "/root/dev-abweichungen-20261125-073844-4056.tgz") is None,
               "Sicherung, die nicht root gehoert: nicht erklaert")
    finally:
        A._root_konto = _rk
    schreibe("/var/backups/passwd.bak", "x\n", 0o600)
    pruefe(g7("geaendert", "f >b... mci.H.. .", "/var/backups/passwd.bak") is None,
           "andere Datei unter /var/backups: nicht erklaert")
    pruefe(g7("neu", "f++++++++++++++++++", "/root/dev-abweichungen-20261125-073844-4056.tgz") is not None
           and g7("entfernt", "f------------------", "/root/dev-abweichungen-20261124-104814-529912.tgz") is not None,
           "Sicherung von dev_reset: erklaert")
    schreibe("/root/kev2/backend/x.py", "x\n", 0o644)
    schreibe("/root/dev-abweichungen.tgz", "x\n", 0o644)
    pruefe(g7("neu", "f++++++++++++++++++", "/root/kev2/backend/x.py") is None
           and g7("neu", "f++++++++++++++++++", "/root/dev-abweichungen.tgz") is None,
           "andere Dateien in /root: nicht erklaert")
    pruefe(g7("geaendert", "f =.... mc..H.. .", "/var/log/wtmp.db") is not None
           and g7("geaendert", "f <.... mc..H.. .", "/var/log/cups/access_log") is not None
           and g7("geaendert", "f <.... mc..H.. .", "/var/log/cups/access_log.1") is not None,
           "Anmeldedatenbank und cups-Zugriffsprotokoll: erklaert")
    pruefe(g7("geaendert", "f =.p.. mc..... .", "/var/log/wtmp.db") is None,
           "Anmeldedatenbank mit geaenderten Rechten: nicht erklaert")

    print("[7c] Mail nur fuer NEUE Befunde")
    A._gemeldet_schreiben(None)
    z7 = {"zustand": "offen", "abdruecke": ["a1", "b2"]}
    noetig, stand = A.meldung_noetig(z7)
    pruefe(noetig, "erster offener Abgleich: Mail")
    A._gemeldet_schreiben(stand)
    pruefe(not A.meldung_noetig(z7)[0], "dieselben Befunde in der naechsten Nacht: KEINE Mail")
    pruefe(not A.meldung_noetig({"zustand": "offen", "abdruecke": ["a1"]})[0], "ein Befund weniger: keine Mail")
    pruefe(A.meldung_noetig({"zustand": "offen", "abdruecke": ["a1", "b2", "c3"]})[0], "ein NEUER Befund dazu: Mail")
    A._gemeldet_schreiben({"fehler": "aide.db.new fehlt"})
    pruefe(not A.meldung_noetig({"zustand": "fehler", "grund": "aide.db.new fehlt"})[0]
           and A.meldung_noetig({"zustand": "fehler", "grund": "Bericht unvollstaendig"})[0],
           "gleicher Fehler: keine Mail, anderer Fehler: Mail")
    A._gemeldet_schreiben(stand)
    A.mail_melden({"zustand": "uebernommen"})
    pruefe(A.meldung_noetig(z7)[0], "nach einer Uebernahme gilt alles wieder als neu")
    eA = {"pfad": "/etc/x", "art": "geaendert", "attrs": "f >.... mc..H.. ."}
    pruefe(A._abdruck(eA, {"/etc/x": ["p", "A"]}) != A._abdruck(eA, {"/etc/x": ["p", "B"]}),
           "dieselbe Datei erneut geaendert (andere Pruefsumme): neuer Abdruck")
    schreibe("/var/lib/aide/aide.db", b"ALTER STAND", 0o600)
    setze_bericht([("neu", "f++++++++++++++++++", "/usr/bin/bar"), ("neu", "f++++++++++++++++++", "/usr/bin/baz")])
    neuer_stand(b"NEUER STAND 7")
    z7 = A.abgleichen()
    pruefe(z7["zustand"] == "offen" and len(z7.get("abdruecke") or []) == z7["offen_anzahl"] == 2,
           "Abgleich legt fuer JEDEN offenen Eintrag einen Abdruck an (%s / %s)"
           % (len(z7.get("abdruecke") or []), z7.get("offen_anzahl")))
    A._gemeldet_schreiben(None)
finally:
    shutil.rmtree(SANDKASTEN, ignore_errors=True)

print("ERGEBNIS: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
