#!/usr/bin/env python3
"""Gegenprobe zu tests/test_aide_abgleich.py: beisst der Waechter?

Jede Probe sabotiert eine KOPIE von backend/aide_abgleich.py in einem
Wegwerf-Verzeichnis; der Waechter laedt sie ueber JARVIS_AIDE_ABGLEICH_MODUL.
Die Repo-Datei wird nie angefasst – ein abgebrochener Lauf hinterlaesst keinen
Rueckstand im Arbeitsbaum.

Erwartet je Probe: Waechter Exit 1 (Befund). Exit 0 = Probe beisst NICHT,
Exit 2 = Waechter konnte nicht laufen (zaehlt ebenfalls nicht als Biss).
Vorab muss der Basislauf gegen die unveraenderte Kopie gruen sein.

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODUL = REPO / "backend" / "aide_abgleich.py"
WAECHTER = REPO / "tests" / "test_aide_abgleich.py"

# (Name, alt, neu, erwartete Trefferzahl von 'alt')
PROBEN = [
    ("Pruefsumme der Paketdatei egal",
     'return ("Paket %s" % paket) if _md5_datei(_p(pfad)) == soll else None', 'return "Paket %s" % paket', 1),
    ("geaenderte Rechte erklaert", 'if merkmale & {"p", "u", "g", "l", "A", "X", "E"}:', "if False:", 1),
    ("Verzeichnis mit Rechteaenderung erklaert", 'merkmale <= {"m", "c", "n", "b", "i"}',
     'merkmale <= {"m", "c", "n", "b", "i", "p"}', 1),
    ("Jarvis-Code ohne Inhaltsvergleich", "baum.get(rel) and baum.get(rel) == _git_blob(_p(pfad))", "baum.get(rel) or True", 1),
    ("Signatur der Quelle ungeprueft", 'if r.returncode != 0:\n        return None, "Spitze der Broker-Quelle nicht signiert geprueft"',
     'if False:\n        return None, "Spitze der Broker-Quelle nicht signiert geprueft"', 1),
    ("fremd beschreibbare Quelle zugelassen", "if not _root_privat(teil, 0o022):", "if False:", 1),
    ("Paketverwaltung ohne dpkg-Lauf", 'if k.get("dpkg_seit_basis") and _PAKETVERWALTUNG.match(pfad):',
     "if _PAKETVERWALTUNG.match(pfad):", 2),
    ("entfernt ohne Versionswechsel erklaert", "if paket and _paket_geaendert(k, paket):", "if paket:", 1),
    ("Uebernahme trotz offener Eintraege", "    if offen or waehrend:\n", "    if waehrend:\n", 1),
    ("dpkg waehrend der Pruefung egal", "    if offen or waehrend:\n", "    if offen:\n", 1),
    ("Uebernahme ohne Pruefsumme des Stands", "if _sha256_datei(neu) != sha_soll:", "if False:", 1),
    ("Admin-Uebernahme ohne Kennung", 'if z.get("kennung") != kennung:', "if False:", 1),
    ("neuer Stand zeitlich ungeprueft",
     'if b["start"] is None or not (b["start"] - 5 <= mneu <= (b["ende"] or jetzt) + 120):', "if False:", 1),
    ("Zusammenfassung ungeprueft",
     'erg["vollstaendig"] = erg["ende"] is not None and (passt or (erg["ohne_aenderung"] and not erg["eintraege"]))',
     'erg["vollstaendig"] = erg["ende"] is not None', 1),
    ("Detailangaben als Eintraege", 'if zeile.startswith(("Detailed information", "The attributes of the")):',
     "if False:", 1),
    ("alter Stand nicht aufgehoben", "shutil.copyfile(alt, _p(DB_VORHER))", "pass", 1),
    ("Sicherung wieder unter /var/lib/aide", 'DB_VORHER = ZUSTAND_DIR + "/aide.db.vorher"', 'DB_VORHER = "/var/lib/aide/aide.db.vorher"', 1),
    ("Backslash im Namen entfernt", 'wer = re.sub(r"[^\\w.@\\\\-]"', 'wer = re.sub(r"[^\\w.@-]"', 1),
    ("grub-Kopie ohne Inhaltsvergleich",
     'if quelle and quelle in dp["md5"] and _md5_datei(_p(pfad)) == dp["md5"][quelle][0]:',
     'if quelle and quelle in dp["md5"]:', 1),
    ("Conffile ohne Inhaltsvergleich",
     'return ("Konfiguration von %s (Paketstand)" % paket) if _md5_datei(_p(pfad)) == soll else None',
     'return "Konfiguration von %s (Paketstand)" % paket', 1),
    ("Nachlauf verschweigt Fehler", 'return 1 if z["zustand"] == "fehler" else 0', "return 0", 1),
    ("ausloesender Lauf sperrt die Uebernahme", 'l[1] >= b["start"] and l[0] <= jetzt', 'l[1] >= b["start"] - 1 and l[0] <= jetzt', 1),
    ("gleiche Sekunde gilt nicht als Ueberschneidung", 'l[1] >= b["start"] and l[0] <= jetzt', 'l[1] > b["start"] and l[0] <= jetzt', 1),
    ("ctime-Regel zu weit", 'if merkmale == {"c"} and not groesse:', 'if "c" in merkmale and not groesse:', 1),
    # ── Postfix (2026-11-25) ──
    ("NSS-Kopie ohne Inhaltsvergleich", "if quelle.endswith(ende) and soll == ist and \\", "if quelle.endswith(ende) and \\", 1),
    ("NSS-Kopie aus beliebigem Verzeichnis", 're.match(r"^/(?:usr/)?lib/[^/]+/[^/]+$", quelle)', 're.match(r"^/", quelle)', 1),
    ("etc-Kopie ohne Inhaltsvergleich", "if ist is not None and ist == _sha256_datei(_p(quelle)) else None",
     "if ist is not None else None", 1),
    ("etc-Kopie mit beliebigem Namen", '_POSTFIX_ETC = re.compile(r"^/var/spool/postfix/etc/(?P<datei>localtime',
     '_POSTFIX_ETC = re.compile(r"^/var/spool/postfix/etc/(?P<datei>[^/]+|localtime', 1),
    ("Laufzeit ohne Versionswechsel", '            or not _paket_geaendert(k, "postfix"):', "            or False:", 1),
    ("Laufzeit ohne dpkg-Lauf", 'if art != "neu" or not k.get("dpkg_seit_basis") or "postfix" not in',
     'if art != "neu" or "postfix" not in', 1),
    ("Laufzeit: Dateiart egal", 'return "Laufzeit von Postfix (installiert/aktualisiert)" if typ == soll_typ else None',
     'return "Laufzeit von Postfix (installiert/aktualisiert)"', 1),
    ("Laufzeit: beliebige Datei in pid/", '(?:master\\.pid|(?:inet|unix)\\..+)$"), "f")', '.+$"), "f")', 1),
    ("Laufzeit: auch geaenderte Eintraege", 'if art != "neu" or not k.get("dpkg_seit_basis")',
     'if art not in ("neu", "geaendert") or not k.get("dpkg_seit_basis")', 1),
    ("Startverweis ohne dpkg-Lauf", '    if not m or not k.get("dpkg_seit_basis"):\n        return None\n    skript',
     '    if not m:\n        return None\n    skript', 1),
    ("Startverweis: Ziel egal", 'if ziel == "../init.d/" + m.group("name") else None', "if True else None", 1),
    ("Startverweis ohne Paket", '        if typ != "l" or not paket:', '        if typ != "l":', 1),
    ("Startverweis: Dateiart egal", '        if typ != "l" or not paket:', "        if not paket:", 1),
    ("Startverweis entfernt ohne Update", 'if alt and _paket_geaendert(k, alt) else None', "if alt else None", 1),
    # ── Installierter Stand / Quelle nachziehen (2026-11-25) ──
    ("Stand ohne 40-Hex-Pruefung", "    if _SHA.match(head):\n        return head", "    if head:\n        return head", 1),
    ("Ref-Datei folgt Links", "fd = os.open(pfad, os.O_RDONLY | os.O_NOFOLLOW)", "fd = os.open(pfad, os.O_RDONLY)", 1),
    (".git als Link erlaubt", "        if os.path.islink(g) or not g.is_dir():", "        if not g.is_dir():", 1),
    ("'..' im Ref erlaubt", '    if not m or ".." in m.group(1):', "    if not m:", 1),
    ("Nachziehen auch bei gleichem Stand", "    if ist == soll:\n", "    if False:\n", 1),
    ("Installer mit falschem Commit", '"--nur-quelle", soll]', '"--nur-quelle", "0" * 40]', 1),
    ("Installer ohne Rechtepruefung", "    if not _root_privat(inst, 0o022):\n        return {\"ok\": False, \"grund\": \"Installer fehlt",
     "    if False:\n        return {\"ok\": False, \"grund\": \"Installer fehlt", 1),
    ("Grund fehlt bei offener Code-Datei", 'zusatz = "" if qn.get("ok", True) else', 'zusatz = "" if True else', 1),
    ("Abgleich zieht nicht nach", "    qn = quelle_nachziehen()\n", "    qn = {\"ok\": True}\n", 1),
    ("Syslog-Socket nicht als Laufzeit", '    (re.compile(r"^/var/spool/postfix/dev/log$"), "s"),\n', "", 1),
    ("Neu-angelegt-Regel fuer jede Dateiart", 'if typ == "s" and merkmale <= {"m", "c", "i", "b", "n"} and _SOCKET_NEU_ANGELEGT.match(pfad):',
     'if merkmale <= {"m", "c", "i", "b", "n"} and _SOCKET_NEU_ANGELEGT.match(pfad):', 1),
    ("Neu-angelegt-Regel fuer jeden Socket", 'if typ == "s" and merkmale <= {"m", "c", "i", "b", "n"} and _SOCKET_NEU_ANGELEGT.match(pfad):',
     'if typ == "s" and merkmale <= {"m", "c", "i", "b", "n"}:', 1),
]


def waechter(modul):
    env = dict(os.environ, JARVIS_AIDE_ABGLEICH_MODUL=str(modul), PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, str(WAECHTER)], env=env, capture_output=True, text=True, timeout=180)
    fails = sum(1 for z in p.stdout.splitlines() if z.startswith("  FAIL"))
    return p.returncode, fails


def main():
    if not MODUL.is_file() or not WAECHTER.is_file():
        print("ABBRUCH: Modul oder Waechter fehlt")
        return 2
    original = MODUL.read_text(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp(prefix="gegen_aide_abgleich_"))
    try:
        basis = tmp / "basis.py"
        basis.write_text(original, encoding="utf-8")
        rc, f = waechter(basis)
        if rc != 0:
            print("ABBRUCH: Basislauf nicht gruen (Exit %d, %d FAIL) – keine Probe deutbar" % (rc, f))
            return 2
        print("Basislauf gruen")
        stumm = 0
        for name, alt, neu, n in PROBEN:
            treffer = original.count(alt)
            if treffer != n:
                print("  PROBE KAPUTT  %-42s Anker %d statt %d Treffer" % (name, treffer, n))
                stumm += 1
                continue
            kopie = tmp / "probe.py"
            kopie.write_text(original.replace(alt, neu), encoding="utf-8")
            rc, f = waechter(kopie)
            if rc == 1 and f > 0:
                print("  beisst        %-42s %d FAIL" % (name, f))
            else:
                print("  STUMM         %-42s Exit %d, %d FAIL" % (name, rc, f))
                stumm += 1
        print("ERGEBNIS: %d von %d Proben beissen" % (len(PROBEN) - stumm, len(PROBEN)))
        return 0 if stumm == 0 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
