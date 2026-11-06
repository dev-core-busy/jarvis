#!/usr/bin/env python3
"""Waechter: die Google-OAuth-Dateien unter ``data/google_auth`` sind gesperrt.

ANLASS (gemessen 2026-11-06 auf DEV): ``data/google_auth/gog_client_secret.json``
lag dort mit **0644** und trug ``client_id`` UND ``client_secret`` im Klartext –
lesbar fuer jeden lokalen Benutzer, also auch fuer die Sandbox-Konten der
Domaenenbenutzer, deren Lauf das Dateisystem per ``--dev-bind / /`` sieht und
deren harte Grenze die OS-Rechte sind.

Dazu fiel das Verzeichnis durch JEDEN Filter der Sandbox, am Syntaxbaum gemessen:
``_SECRET_NAMES`` fuehrt ``credentials.json`` (die Datei von
``tools/google_auth.py``), aber nicht ``gog_client_secret.json`` und nicht
``token.json``; ``_SECRET_SUFFIX`` kennt kein ``.json``; ``_SECRET_DIRPARTS``
sind nur ``.ssh``, ``.git``, ``certs``; und ``SHELL_SECRET_PATHS`` nennt
``credentials\\.json``, aber keinen der beiden Google-Namen.

Das ist das Muster "Sperrliste statt Erlaubnisliste": die eine Datei wurde
eingetragen, die zweite heisst anders und ist nie dazugekommen. Deshalb sperrt
der Fix das VERZEICHNIS und nicht die Namen – eine kuenftige dritte Datei ist
damit von sich aus erfasst (Abschnitt 2 prueft genau das).

Vorbild ist ``data/kerberos/http.keytab``: dasselbe Muster an denselben vier
Stellen (``_APP_DENY_REL``, ``PRIVATE_DIRS``, ``PRIVATE_FILES_STRENG``,
``SHELL_SECRET_PATHS``).

GEMESSEN WIRD WIRKUNG, NICHT VORKOMMEN: ``is_sensitive``, ``authorize_fs``,
``fs_target_sensitive``, ``authorize_shell`` und ``harden_data_dirs`` werden
WIRKLICH ausgefuehrt, letzteres gegen einen echten Verzeichnisbaum im
Sandkasten. Ein Test auf das Vorkommen einer Zeichenkette in ``sandbox.py``
waere derselbe Fehler, den ``tests/test_sap_accounts.py`` an dieser Stelle noch
macht.

Laeuft ohne ``backend.config`` – der echte Import schreibt die Live-
``settings.json`` zurueck (Register). Exit 2, wenn es doch geladen wird oder
eine Positivkontrolle nicht messbar ist.
"""

import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def pruefe(bed, text):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text)


from backend import sandbox as SB  # noqa: E402

if "backend.config" in sys.modules:
    print("ABBRUCH (Exit 2): backend.config wurde geladen – der echte Import "
          "schreibt die Live-settings.json zurueck")
    sys.exit(2)

VERZ = "data/google_auth"
GEHEIM = (VERZ + "/gog_client_secret.json", VERZ + "/token.json")
_p = lambda rel: (SB.PROJECT_ROOT / rel).resolve()

# ─── 1. Positivkontrolle: die Sonde unterscheidet ueberhaupt ────────────────
print("1. Positivkontrolle")
harmlos = _p("data/knowledge/beispiel.txt")
if SB.is_sensitive(harmlos):
    print("ABBRUCH (Exit 2): is_sensitive haelt schon einen harmlosen "
          "Wissenspfad fuer sensibel – dann ist Abschnitt 2 trivial wahr")
    sys.exit(2)
pruefe(not SB.is_sensitive(harmlos),
       "ein Wissenspfad gilt NICHT als sensibel (sonst waere alles trivial)")
erlaubt_h, _, _ = SB.authorize_shell("grep -r suchbegriff data/rag")
if not erlaubt_h:
    print("ABBRUCH (Exit 2): authorize_shell verweigert schon eine harmlose "
          "Suche – dann sagt Abschnitt 4 nichts aus")
    sys.exit(2)
pruefe(erlaubt_h, "eine harmlose Suche bleibt in der Shell erlaubt")

# ─── 2. Dateiwerkzeuge: das VERZEICHNIS ist gesperrt, nicht nur zwei Namen ──
print("2. is_sensitive deckt data/google_auth ab")
for rel in GEHEIM:
    pruefe(SB.is_sensitive(_p(rel)), f"gesperrt: {rel}")
pruefe(SB.is_sensitive(_p(VERZ)), f"gesperrt: das Verzeichnis {VERZ} selbst")
# DAS ist der Kern des Fixes: eine Datei, die es heute noch nicht gibt.
pruefe(SB.is_sensitive(_p(VERZ + "/kuenftige_datei.json")),
       "gesperrt: eine kuenftige, heute unbekannte Datei im Verzeichnis")

# ─── 3. Der Backend-Weg nennt den richtigen GRUND ───────────────────────────
# Ohne Eintrag weist authorize_fs mit "nicht im Arbeitsbereich" ab – lesbar war
# die Datei also nie. Aber die BEGRUENDUNG entscheidet, ob ein abgewiesener
# Zugriff als Angriffsindiz zaehlt (fs_target_sensitive -> agent.py: _viol_soft).
# Derselbe Grund steht am Eintrag "data/chats" seit 2026-08-05.
print("3. authorize_fs/fs_target_sensitive: Zugriffsversuch ist ein Angriffsindiz")
for rel in GEHEIM:
    erlaubt, grund = SB.authorize_fs("read", str(_p(rel)), username="pruef.nutzer")
    pruefe(not erlaubt, f"read verweigert: {rel}")
    pruefe("Arbeitsbereich" not in grund and "Arbeitsverzeichnis" not in grund,
           f"Grund ist die Sensibilitaet, nicht der Ort ({rel}): {grund!r}")
    pruefe(SB.fs_target_sensitive(str(_p(rel))),
           f"zaehlt als Angriffsindiz: {rel}")

# ─── 4. Der Shell-Weg ───────────────────────────────────────────────────────
# Hier ist es eine echte Sperre: in der Sandbox sieht der Lauf das Dateisystem,
# die harte Grenze sind die OS-Rechte – und genau die waren 0644.
print("4. authorize_shell")
for cmd in (f"cat {SB.PROJECT_ROOT}/{VERZ}/gog_client_secret.json",
            f"cat {SB.PROJECT_ROOT}/{VERZ}/token.json",
            f"cd {VERZ} && cat gog_client_secret.json",
            f"tar czf /tmp/x.tgz {VERZ}"):
    erlaubt, grund, marke = SB.authorize_shell(cmd)
    pruefe(not erlaubt, f"gesperrt: {cmd[:58]}")
    pruefe(bool(marke), f"Schranke ist benannt (marke={marke!r})")

# ─── 5. Rechte-Haertung, gegen einen echten Baum ausgefuehrt ────────────────
# Der dauerhafte Teil: harden_data_dirs laeuft beim Start und zieht das
# Verzeichnis auf 0750 und die Geheimnisse auf 0600. Ohne diesen Abschnitt
# waere der Fix eine Handarbeit, die bei der naechsten Installation fehlt.
print("5. harden_data_dirs setzt die Rechte wirklich")
with tempfile.TemporaryDirectory() as tmp:
    baum = Path(tmp)
    (baum / VERZ).mkdir(parents=True)
    (baum / VERZ).chmod(0o755)
    for rel in GEHEIM:
        f = baum / rel
        f.write_text("{}", encoding="utf-8")
        f.chmod(0o644)
    # Eine harmlose Nachbardatei, die unangetastet bleiben muss
    vorlage = baum / VERZ / "credentials.json.example"
    vorlage.write_text("{}", encoding="utf-8")
    vorlage.chmod(0o644)
    (baum / "data" / "knowledge").mkdir(parents=True)
    unberuehrt = baum / "data" / "knowledge" / "beispiel.txt"
    unberuehrt.write_text("x", encoding="utf-8")
    unberuehrt.chmod(0o644)

    alt = SB.PROJECT_ROOT
    try:
        SB.PROJECT_ROOT = baum
        # Positivkontrolle: die Lage VOR dem Lauf ist die, die der Vorfall hatte
        if (baum / GEHEIM[0]).stat().st_mode & 0o777 != 0o644:
            print("ABBRUCH (Exit 2): Sandkasten nicht in der Ausgangslage")
            sys.exit(2)
        SB.harden_data_dirs()
    finally:
        SB.PROJECT_ROOT = alt

    modus = lambda p: p.stat().st_mode & 0o777
    pruefe(modus(baum / VERZ) == 0o750,
           f"Verzeichnis {VERZ} auf 0750 (ist {oct(modus(baum / VERZ))})")
    for rel in GEHEIM:
        pruefe(modus(baum / rel) == 0o600,
               f"{rel} auf 0600 (ist {oct(modus(baum / rel))})")
    pruefe(not (modus(baum / GEHEIM[0]) & (stat.S_IROTH | stat.S_IRGRP)),
           "gog_client_secret.json ist weder gruppen- noch weltlesbar")
    pruefe(modus(unberuehrt) == 0o644,
           "eine harmlose Wissensdatei bleibt unangetastet (keine Flaechenwirkung)")

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
