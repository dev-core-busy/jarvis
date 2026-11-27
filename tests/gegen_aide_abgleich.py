#!/usr/bin/env python3
"""Gegenprobe zu tests/test_aide_abgleich.py: beisst der Waechter?

Jede Probe sabotiert eine KOPIE von backend/aide_abgleich.py in einem
Wegwerf-Verzeichnis; der Waechter laedt sie ueber JARVIS_AIDE_ABGLEICH_MODUL.
Proben mit fuenftem Feld sabotieren eine Kopie eines ANDEREN Moduls
(eigene_dateien, Policy, Freigabe, Daemon); der Waechter laedt sie ueber
JARVIS_AIDE_ERSATZ an Stelle des Originals.
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

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODUL = REPO / "backend" / "aide_abgleich.py"
# Zielmodule der Proben mit fuenftem Feld: Kurzname -> (Modulname, Datei)
ZIELE = {
    "ed": ("backend.eigene_dateien", REPO / "backend" / "eigene_dateien.py"),
    "policy": ("backend.broker.policy", REPO / "backend" / "broker" / "policy.py"),
    "freigabe": ("backend.broker.freigabe", REPO / "backend" / "broker" / "freigabe.py"),
    "daemon": ("backend.broker.daemon", REPO / "backend" / "broker" / "daemon.py"),
}
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
    ("Neu-angelegt-Regel fuer jede Dateiart", 'if typ == "s" and merkmale <= {"m", "c", "i", "b", "n"}:',
     'if merkmale <= {"m", "c", "i", "b", "n"}:', 1),
    ("Neu-angelegt-Regel fuer jeden Socket", "            if _SOCKET_NEU_ANGELEGT.match(pfad):",
     "            if True:", 1),
    # ── Dauerlaeufer von ECHT (2026-11-25) ──
    ("Zeit-Regel ignoriert die Groesse", 'and "m" in merkmale and not groesse:', 'and "m" in merkmale:', 1),
    ("Zeit-Regel trotz Pruefsumme", 'merkmale <= {"m", "c", "i", "n"} and "m"', 'merkmale <= {"m", "c", "i", "n", "H"} and "m"', 1),
    ("Zeit-Regel fuer jede Dateiart", 'if typ == "f" and merkmale <= {"m", "c", "i", "n"}', 'if merkmale <= {"m", "c", "i", "n"}', 1),
    ("Code-Rechte ohne Inhaltsvergleich", "if not baum or not baum.get(rel) or baum.get(rel) != _git_blob(_p(pfad)):",
     "if not baum:", 1),
    ("Code-Rechte: Modus egal", "    if (modus & 0o7777) not in erlaubt:\n        return None", "    if False:\n        return None", 1),
    ("Code-Rechte: Gruppenmitglieder egal", "if pwd.getpwuid(uid).pw_gid != gid or grp.getgrgid(gid).gr_mem:",
     "if pwd.getpwuid(uid).pw_gid != gid:", 1),
    ("Code-Rechte: x-Bit egal", "erlaubt = (0o755, 0o775) if rel in _AUSFUEHRBAR else (0o644, 0o664)",
     "erlaubt = (0o644, 0o664, 0o755, 0o775)", 1),
    ("Code-Rechte: Eigentuemerwechsel erlaubt", '{"p", "A", "H", "m", "c", "i", "b", "n"}:',
     '{"p", "A", "H", "m", "c", "i", "b", "n", "u"}:', 1),
    ("Code-Rechte auch fuer die Broker-Kopie", 'if not (pfad.startswith("/opt/jarvis/") or in_quelle) or merkmale', "if merkmale", 1),
    ("eigene Dateien ohne Kette", 'return "vom Broker geschrieben (vermerkt)" if ed.erklaert(pfad, alt, neu) else None',
     'return "vom Broker geschrieben (vermerkt)"', 1),
    ("Datenbank-Pruefsumme an letzter Datei", '            in_details = zeile.startswith("Detailed information")',
     "            in_details = in_details or zeile.startswith(\"Detailed information\")", 1),
    ("SHA256-Fortsetzungszeile ignoriert", "            if in_sha and mf:", "            if False and mf:", 1),
    ("apt-Historie ohne Upgrade", 'r"^(?:Install|Upgrade|Remove', 'r"^(?:Install|Remove', 1),
    ("ohne Basis jedes Paket geaendert", '    return paket in (k.get("pakete_seit") or ())', "    return True", 1),
    ("Konten: UID/Shell egal", "if not (0 < uid < 1000) or f[-1] not in _OHNE_ANMELDUNG:", "if False:", 1),
    ("Konten: bestehende Eintraege egal", "        if jetzt.get(name) != f:\n            return None", "        pass", 1),
    ("Konten: Kennwort neuer Konten egal", 'if art == "shadow" and (name not in neue_konten or not f[0][1]):',
     'if art == "shadow" and name not in neue_konten:', 1),
    ("Konten: Gruppenmitglieder egal", "if not (0 < gid < 1000) or not mitglieder <= neue_konten:", "if not (0 < gid < 1000):", 1),
    ("Konten: Gruppenkennwort egal", "if not f[0][1] or not mitglieder <= neue_konten:", "if not mitglieder <= neue_konten:", 1),
    ("Konten ohne dpkg-Lauf", 'if art is None or not k.get("dpkg_seit_basis") or', "if art is None or", 1),
    ("Konten: spaeterer Stand in die Basis", "basis_schreiben(dpkg_laden(), start, _konten_kandidat_lesen())",
     "basis_schreiben(dpkg_laden(), start, konten_lesen())", 1),
    ("Konten: Kennwort im Klartext", 'f[1] = [hashlib.sha256(pw.encode("utf-8", "replace")).hexdigest()[:16],', "f[1] = [pw,", 1),
    ("Rotation: x-Bit egal", 'if art == "neu" and _LOG_SERIE.match(pfad) and _ohne_ausfuehrung(pfad):',
     'if art == "neu" and _LOG_SERIE.match(pfad):', 1),
    ("Rotation: beliebiger Name", '_LOG_SERIE = re.compile(r"^/var/log/(?:', '_LOG_SERIE = re.compile(r"^/var/log/.*|^/var/log/(?:', 1),
    ("Protokoll-Liste beliebig", '    r"^/var/log/(?:boot', '    r"^/var/log/.*|^/var/log/(?:boot', 1),
    ("AIDE-Arbeitsordner: Eigentuemer egal",
     'return "Arbeitsordner der AIDE-Pruefung" if e_ is not None and _aide_benutzer(e_[0]) else None',
     'return "Arbeitsordner der AIDE-Pruefung"', 1),
    ("wireplumber: ganzes Home", r'_WIREPLUMBER = re.compile(r"^/home/[^/]+/\.local/state/wireplumber/[^/]+$")',
     '_WIREPLUMBER = re.compile(r"^/home/.*$")', 1),
    ("dynamicmaps: Inhalt egal", "return None if zeilen or not _ohne_ausfuehrung(pfad) else",
     "return None if not _ohne_ausfuehrung(pfad) else", 1),
    ("dynamicmaps ohne postfix-Installation",
     'if art == "neu" and pfad == DYNAMICMAPS and k.get("dpkg_seit_basis") and _paket_geaendert(k, "postfix"):',
     'if art == "neu" and pfad == DYNAMICMAPS and k.get("dpkg_seit_basis"):', 1),
    ("entfernt: Verzeichnis mehrerer Pakete", 'if ep and dp.get("liste_n", {}).get(eltern) == 1 and _paket_geaendert(k, ep)',
     "if ep and _paket_geaendert(k, ep)", 1),
    ("entfernt: Paket unveraendert", 'if ep and dp.get("liste_n", {}).get(eltern) == 1 and _paket_geaendert(k, ep)',
     'if ep and dp.get("liste_n", {}).get(eltern) == 1', 1),
    # ── Mail von DEV (2026-11-26) ──
    ("Quelle: Modus egal", "(modus & 0o7777) != (0o755 if rel in _AUSFUEHRBAR else 0o644)", "False", 1),
    ("Quelle: Eigentuemer egal", "if not (_root_konto(uid) and _root_gruppe(gid)) or \\", "if False or \\", 1),
    ("Quelle: umask-002-Toleranz", "    if in_quelle:\n", "    if False:\n", 1),
    ("Sicherung: Rechte egal", "return name if _root_ablage(pfad) else None", "return name", 1),
    ("Sicherung: Eigentuemer egal", "_root_konto(e[0]) and (e[2] & 0o7133) == 0", "(e[2] & 0o7133) == 0", 1),
    ("dpkg-Sicherung: beliebiger Name", 'r"^/var/backups/(?:dpkg', 'r"^/var/backups/.*|^/var/backups/(?:dpkg', 1),
    ("dev-Sicherung: beliebiger Name", '_DEV_SICHERUNG = re.compile(r"^/root/dev-abweichungen-',
     '_DEV_SICHERUNG = re.compile(r"^/root/.*|^/root/dev-abweichungen-', 1),
    ("Protokoll-Liste: wtmp/cups fehlen", '    r"|wtmp\\.db|cups/access_log(?:\\.\\d+)?)$")', '    r")$")', 1),
    ("Mail trotz nichts Neuem", 'return bool(jetzt - vorher), {"offen"', 'return True, {"offen"', 1),
    ("Fehler-Mail jede Nacht", 'return _gemeldet_lesen().get("fehler") != grund, {"fehler": grund}',
     'return True, {"fehler": grund}', 1),
    ("Abdruck ohne neue Pruefsumme", '((sha or {}).get(e.get("pfad")) or ["", ""])[-1]]', '""]', 1),
    ("Uebernahme setzt Meldestand nicht zurueck", "            _gemeldet_schreiben(None)   # neuer Vergleichsstand",
     "            pass   # neuer Vergleichsstand", 1),
    ("Abdruecke nur fuer den ersten Eintrag", '{_abdruck(o, k["sha256"]) for o in offen}',
     '{_abdruck(o, k["sha256"]) for o in offen[:1]}', 1),
    # ── apt-Planer-Protokoll (2026-11-26) ──
    ("eipp: Modus egal", "if (e[2] & 0o7777) not in _EIPP_MODI:", "if False:", 1),
    ("eipp: auch 666/664 erlaubt", "_EIPP_MODI = (0o640, 0o644)", "_EIPP_MODI = (0o640, 0o644, 0o664, 0o666)", 1),
    ("eipp: Eigentuemer egal", "not (_root_konto(e[0]) and _root_gruppe(e[1])):", "False:", 1),
    ("eipp: Gruppe egal", "not (_root_konto(e[0]) and _root_gruppe(e[1])):", "not _root_konto(e[0]):", 1),
    ("eipp: Merkmale egal", 'or not merkmale <= {"p", "A", "m", "c", "i"}:', ":", 1),
    ("eipp: ACL egal", '        return None   # erweiterte ACL vorhanden\n    except OSError:\n        pass\n'
     '    return "apt-Planer', '        pass\n    except OSError:\n        pass\n    return "apt-Planer', 1),
    ("eipp: jede Datei", "if pfad != EIPP or", "if", 1),
    ("eipp: Regel fehlt", "        eipp = _eipp_rechte(pfad, merkmale) if typ", "        eipp = None if typ", 1),
    # ── 27.11.2026: Postfix-Sockets, Installationsvermerk 'lokal', Ordner des Mailversands ──
    ("Postfix-Socket ohne master.cf", 'if m_s and m_s.group("name") in _postfix_dienste():', "if m_s:", 1),
    ("master.cf: Kommentar/Fortsetzung als Dienst", 'if not zeile or zeile[0] in "# \\t":', "if not zeile:", 1),
    ("STAND lokal ohne Nachrechnen", 'stand.get("quelle") == "lokal" and h and h == _kopie_hash(wurzel)',
     'stand.get("quelle") == "lokal"', 1),
    ("STAND: jede Quelle", 'stand.get("quelle") == "lokal" and h and h == _kopie_hash(wurzel)',
     'h and h == _kopie_hash(wurzel)', 1),
    ("Kopie-Hash nicht in Byte-Reihenfolge", "zeilen.sort(key=lambda t: t[0])", "zeilen.sort(key=lambda t: t[0].lower())", 1),
    ("Mail-Ordner: fremde Datei egal", 'return bool(namen) and all(_mail_erklaert(pfad + "/" + n) for n in namen)',
     "return bool(namen)", 1),
    ("Mail-Ordner: leer erklaert", 'return bool(namen) and all(_mail_erklaert(', "return all(_mail_erklaert(", 1),
    ("Mail-Ordner: Rechte egal", "            or (e[2] & 0o7777) != 0o755:", "            or False:", 1),
    # ── andere Module ──
    ("Register: Kette ab beliebigem Stand", "    gesehen, offen = {alt}, [alt]", "    gesehen, offen = set(kanten), list(kanten)", 1, "ed"),
    ("Register: Uebergang nicht vermerkt", "        vermerken(pfad, vorher, sha(pfad))", "        pass", 1, "ed"),
    ("Register: jede Datei", "    return s if s in PFADE else None", "    return s", 1, "ed"),
    ("Policy ohne Vermerk", "    with eigene_dateien.schreibt(pfad):\n        _atomar_schreiben_roh(pfad, data)",
     "    _atomar_schreiben_roh(pfad, data)", 1, "policy"),
    ("Freigabe ohne Vermerk", "    with eigene_dateien.schreibt(p):\n        _schreibe_privat_roh(p, inhalt)",
     "    _schreibe_privat_roh(p, inhalt)", 1, "freigabe"),
    ("Meta-Vermerk auch fuer Shell-Ops", 'if eigene_dateien is None or not op.startswith("broker."):',
     "if eigene_dateien is None:", 1, "daemon"),
    ("Meta-Ops ohne Vermerk", "        eigene_dateien.stand_vermerken(vorher)", "        pass", 1, "daemon"),
]


def waechter(modul, ersatz=None):
    env = dict(os.environ, JARVIS_AIDE_ABGLEICH_MODUL=str(modul), PYTHONDONTWRITEBYTECODE="1",
               JARVIS_AIDE_ERSATZ=json.dumps(ersatz or {}))
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
        for probe in PROBEN:
            name, alt, neu, n = probe[:4]
            ziel = probe[4] if len(probe) > 4 else None
            quelltext = ZIELE[ziel][1].read_text(encoding="utf-8") if ziel else original
            treffer = quelltext.count(alt)
            if treffer != n:
                print("  PROBE KAPUTT  %-42s Anker %d statt %d Treffer" % (name, treffer, n))
                stumm += 1
                continue
            kopie = tmp / ("probe_%s.py" % (ziel or "abgleich"))
            kopie.write_text(quelltext.replace(alt, neu), encoding="utf-8")
            if ziel:
                rc, f = waechter(basis, {ZIELE[ziel][0]: str(kopie)})
            else:
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
