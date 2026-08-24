#!/usr/bin/env python3
"""Privates /tmp pro Agent-Lauf – Mechanik, Uebergaben, Drift-Schranken.

Drei Teile:

1. **Einheiten** – Pfad-Aufloesung, Kennungen, Validierung der Bindungen, die
   Lauf-Klammer. Ohne root und ohne bwrap lauffaehig.
2. **Echte Isolation** – laeuft nur mit installiertem ``bwrap``. Hier wird
   NICHTS nachgebaut: der Aufruf aus ``sandbox_befehl()`` wird wirklich
   ausgefuehrt und gemessen, ob fremde Dateien unsichtbar sind, ob das Ergebnis
   auf dem Host ankommt und ob ``2>/dev/null`` funktioniert. Letzteres mit
   Gegenprobe – mit ``--bind / /`` statt ``--dev-bind / /`` MUSS es scheitern,
   sonst prueft der Test seine eigene Annahme.
3. **Drift-Schranken** – die Teile liegen in fuenf Dateien (lauf_tmp, shell,
   broker/ops, agent, attachments). Ein Waechter je Naht, damit eine halbe
   Reparatur auffaellt und nicht erst auf einem Kundensystem.

SANDKASTEN: Teil 1 biegt die Wurzeln des Moduls in ein Wegwerf-Verzeichnis um
und BRICHT AB (Exit 2), wenn das nicht greift – sonst wuerden die Aufraeum-Tests
die echten Arbeitskopien des laufenden Servers loeschen. "Konnte nicht laufen"
muss von "bestanden" unterscheidbar sein.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import lauf_tmp as lt          # noqa: E402
from backend import attachments as att      # noqa: E402

ok = fail = 0


def pruef(name, bedingung, hinweis=""):
    global ok, fail
    if bedingung:
        ok += 1
        print(f"  ok   {name}")
    else:
        fail += 1
        print(f"  FAIL {name}" + (f" – {hinweis}" if hinweis else ""))


def abschnitt(t):
    print(f"\n── {t} " + "─" * max(0, 60 - len(t)))


# ── Sandkasten ──────────────────────────────────────────────────────────────
WURZEL = Path(__file__).resolve().parent.parent
SANDKASTEN = Path(tempfile.mkdtemp(prefix="lauftmp_test_"))
lt.ARBEIT_ROOT = SANDKASTEN / "arbeit"
lt.ANH_ROOT = SANDKASTEN / "anhaenge"
lt.TMP_ECHT = SANDKASTEN / "tmp"
lt.TMP_ECHT.mkdir(parents=True, exist_ok=True)
for _n in ("ARBEIT_ROOT", "ANH_ROOT", "TMP_ECHT"):
    if not str(getattr(lt, _n)).startswith(str(SANDKASTEN)):
        print(f"ABBRUCH: {_n} zeigt nach {getattr(lt, _n)} – der Test wuerde in "
              f"echte Verzeichnisse schreiben.")
        sys.exit(2)
att.WORK_DIR = lt.TMP_ECHT
if not str(att.WORK_DIR).startswith(str(SANDKASTEN)):
    print("ABBRUCH: attachments.WORK_DIR nicht umgebogen.")
    sys.exit(2)


def isolation_erzwingen(an: bool):
    """Verfuegbarkeit vortaeuschen – die Einheiten-Tests sollen nicht davon
    abhaengen, ob auf diesem Rechner bwrap liegt."""
    lt._verf_cache.clear()
    lt._verf_cache["-"] = (float("inf"), an)
    lt._verf_cache["jarvis_sandbox"] = (float("inf"), an)


# ═══════════════════════════════════════════════════════════════════════════
abschnitt("1. Kennung und Anhang-Ablage")

pruef("Kennung ist 8 Hex", re.fullmatch(r"[0-9a-f]{8}", lt.benutzer_kennung("alice")))
pruef("Kennung normalisiert Domaenen-Praefix",
      lt.benutzer_kennung("nexus\\Alice") == lt.benutzer_kennung("alice"),
      "sonst hat dieselbe Person je Anmeldeform ein eigenes Verzeichnis")
pruef("Kennung normalisiert UPN",
      lt.benutzer_kennung("alice@nexus.int") == lt.benutzer_kennung("alice"))
pruef("Kanal-Kennungen bleiben unterscheidbar",
      lt.benutzer_kennung("wa:+4915") != lt.benutzer_kennung("tg:+4915"))
pruef("leerer Benutzer -> keine Kennung", lt.benutzer_kennung("") == "")
pruef("verschiedene Benutzer -> verschiedene Kennung",
      lt.benutzer_kennung("alice") != lt.benutzer_kennung("bob"))

isolation_erzwingen(False)
ziel_ohne = lt.anhang_ziel("alice", "tabelle.xlsx")
pruef("ohne Isolation: Arbeitskopie direkt in /tmp",
      ziel_ohne.parent == lt.TMP_ECHT, str(ziel_ohne))
isolation_erzwingen(True)
ziel_mit = lt.anhang_ziel("alice", "tabelle.xlsx")
pruef("mit Isolation: Verzeichnis je Benutzer",
      ziel_mit.parent == lt.ANH_ROOT / lt.benutzer_kennung("alice"), str(ziel_mit))
pruef("Anhang-Verzeichnis wurde angelegt", ziel_mit.parent.is_dir())
# DIE DRIFT-SCHRANKE: attachments.py raeumt nach genau diesem Muster ab.
pruef("Name passt auf attachments._NAME_RE (beide Orte)",
      bool(att._NAME_RE.match(ziel_mit.name)) and bool(att._NAME_RE.match(ziel_ohne.name)),
      f"{ziel_mit.name} / {ziel_ohne.name} – sonst bleiben die Kopien bis zum Reboot liegen")
pruef("Name ist nicht erratbar (12 Hex)",
      re.fullmatch(r"anhang_[0-9a-f]{12}_tabelle\.xlsx", ziel_mit.name))

abschnitt("2. Eigentuemer-Schranke der Anhaenge (Backend-Weg)")

a_datei = ziel_mit
a_datei.write_text("geheim")
b_datei = lt.anhang_ziel("bob", "bob.xlsx")
b_datei.write_text("bobs")
pruef("eigener Anhang: True", lt.gehoert_anhang(a_datei, "alice") is True)
pruef("fremder Anhang: False", lt.gehoert_anhang(a_datei, "bob") is False,
      "ohne das oeffnet office_read/xlsx_read_range fremde Arbeitskopien")
pruef("Anhang mit Domaenen-Praefix erkannt",
      lt.gehoert_anhang(a_datei, "nexus\\alice") is True)
pruef("Pfad ausserhalb: None (Frage stellt sich nicht)",
      lt.gehoert_anhang(lt.TMP_ECHT / "x.txt", "alice") is None)
pruef("Wurzel selbst: None", lt.gehoert_anhang(lt.ANH_ROOT, "alice") is None)
pruef("leerer Benutzer bekommt fremde Anhaenge nicht",
      lt.gehoert_anhang(a_datei, "") is False, "fail-closed")

abschnitt("3. Lauf-Klammer")

with lt.lauf_scope("alice", privilegiert=True) as l:
    pruef("privilegiert -> kein Lauf-Verzeichnis", l is None,
          "Screenshot-Werkzeug und Chrome-Profil brauchen das echte /tmp")
with lt.lauf_scope("", privilegiert=False) as l:
    pruef("ohne Benutzer -> kein Lauf-Verzeichnis", l is None)

with lt.lauf_scope("alice", privilegiert=False) as lauf:
    pruef("unprivilegiert -> Lauf gebunden", lauf is not None)
    pruef("Kennung 8 Hex", bool(re.fullmatch(r"[0-9a-f]{8}", lauf.kennung)))
    pruef("Verzeichnis heisst wie die Benutzer-Kennung",
          lauf.verzeichnis == lt.ARBEIT_ROOT / lt.benutzer_kennung("alice"))
    pruef("aktueller_lauf() liefert ihn", lt.aktueller_lauf() is lauf)
    lt.eigenes_verzeichnis_anlegen()
    pruef("Backend kann das Verzeichnis selbst anlegen", lauf.verzeichnis.is_dir())
    (lauf.verzeichnis / "zwischen.xlsx").write_text("x")
    with lt.lauf_scope("alice", privilegiert=False) as innen:
        pruef("verschachtelt -> ERBT (Sub-Agent sieht Elterndateien)", innen is lauf)
    merk = lauf.verzeichnis
pruef("kein Lauf mehr gebunden", lt.aktueller_lauf() is None)
# DER KERN DER UMSTELLUNG (Vorgabe 2026-08-23): das Verzeichnis gehoert dem
# BENUTZER, nicht dem Auftrag. Wuerde es am Lauf-Ende geloescht, liefe
# "und jetzt filtere Spalte C" in No such file or directory.
pruef("nach dem Lauf bleibt das Zwischenprodukt liegen",
      (merk / "zwischen.xlsx").exists(),
      "sonst ist Weiterarbeit an einer nicht ausgelieferten Datei unmoeglich")
with lt.lauf_scope("alice", privilegiert=False) as zweiter:
    pruef("zweiter Lauf DESSELBEN Benutzers bekommt dasselbe Verzeichnis",
          zweiter.verzeichnis == merk)
    pruef("und sieht die Datei des ersten Laufs", (zweiter.verzeichnis / "zwischen.xlsx").exists())
with lt.lauf_scope("bob", privilegiert=False) as fremder:
    pruef("ein ANDERER Benutzer bekommt ein anderes Verzeichnis",
          fremder.verzeichnis != merk, "das ist die Grenze, die gefehlt hat")

abschnitt("4. Pfad-Aufloesung fuer Backend-Werkzeuge")

with lt.lauf_scope("alice", privilegiert=False) as lauf:
    lt.eigenes_verzeichnis_anlegen()
    tmp = str(lt.TMP_ECHT)
    pruef("Modell-Pfad -> Lauf-Verzeichnis",
          lt.aufloesen(tmp + "/ergebnis.xlsx") == str(lauf.verzeichnis / "ergebnis.xlsx"))
    pruef("Unterverzeichnis bleibt erhalten",
          lt.aufloesen(tmp + "/unter/x.csv") == str(lauf.verzeichnis / "unter" / "x.csv"))
    pruef("/tmp selbst -> Lauf-Verzeichnis", lt.aufloesen(tmp) == str(lauf.verzeichnis))
    pruef("Anhang-Pfad bleibt UNVERAENDERT (Host = Modell)",
          lt.aufloesen(str(a_datei)) == str(a_datei),
          "sonst finden xlsx_inspect/office_read den Anhang nicht mehr")
    pruef("Arbeits-Wurzel bleibt unveraendert",
          lt.aufloesen(str(lt.ARBEIT_ROOT / "abc")) == str(lt.ARBEIT_ROOT / "abc"))
    pruef("Pfad ausserhalb /tmp unveraendert",
          lt.aufloesen("/opt/jarvis/data/x") == "/opt/jarvis/data/x")
    pruef("leerer Pfad bleibt leer", lt.aufloesen("") == "")
    pruef("such_wurzeln kennt Lauf UND echtes /tmp",
          lauf.verzeichnis in lt.such_wurzeln() and lt.TMP_ECHT in lt.such_wurzeln())
pruef("ohne Lauf: Aufloesung ist ein No-op",
      lt.aufloesen(str(lt.TMP_ECHT) + "/x") == str(lt.TMP_ECHT) + "/x")

abschnitt("5. Validierung der ro-Bindungen (Broker-Seite)")

echt = lt.TMP_ECHT / "skript.py"
echt.write_text("print(1)")
frei = lt.TMP_ECHT / "offen.py"
frei.write_text("x")
os.chmod(frei, 0o666)
# Die Validierung prueft gegen das ECHTE /tmp – im Sandkasten liegen die Dateien
# anderswo, deshalb wird hier mit echten /tmp-Dateien gearbeitet.
with tempfile.NamedTemporaryFile(dir="/tmp", suffix=".py", delete=False) as f:
    f.write(b"print(1)")
    real = f.name
os.chmod(real, 0o644)
with tempfile.NamedTemporaryFile(dir="/tmp", suffix=".py", delete=False) as f:
    f.write(b"x")
    real_offen = f.name
os.chmod(real_offen, 0o666)
try:
    pruef("echte /tmp-Datei wird akzeptiert", lt.binds_pruefen([real]) == [real])
    pruef("world-writable Quelle wird abgewiesen", lt.binds_pruefen([real_offen]) == [],
          "sonst koennte ein zweiter Lauf die Quelle austauschen")
    pruef("Pfad ausserhalb /tmp abgewiesen", lt.binds_pruefen(["/etc/passwd"]) == [])
    pruef("nicht vorhandene Datei abgewiesen", lt.binds_pruefen(["/tmp/gibtsnicht_xyz"]) == [])
    pruef("Traversal abgewiesen", lt.binds_pruefen(["/tmp/../etc/shadow"]) == [])
    pruef("Nullwerte stoeren nicht", lt.binds_pruefen(None) == [] and lt.binds_pruefen([""]) == [])
    pruef("Deckel bei 64 Bindungen", len(lt.binds_pruefen([real] * 200)) == 64)
finally:
    for f in (real, real_offen):
        try:
            os.unlink(f)
        except OSError:
            pass

abschnitt("6. Der bwrap-Aufruf")

befehl = lt.sandbox_befehl("jarvis_sandbox", "echo hallo",
                           lt.ARBEIT_ROOT / "abcdef01", [str(echt)],
                           _pruefen=True)
pruef("runuser bleibt aussen", befehl.startswith("runuser -u jarvis_sandbox --"))
pruef("setpriv vor bwrap (Ambient-Caps des Dienstes)",
      "setpriv" in befehl and befehl.index("setpriv") < befehl.index("bwrap"),
      "ohne setpriv bricht bwrap IM DIENST ab, bei der Handprobe nicht")
pruef("--dev-bind / / (nicht --bind)", "--dev-bind / /" in befehl,
      "eine gewoehnliche Bindung mountet nodev -> 2>/dev/null scheitert")
pruef("Arbeitsverzeichnis wird auf /tmp gemountet",
      "--bind %s /tmp" % (lt.ARBEIT_ROOT / "abcdef01") in befehl)
pruef("MPL-Cache braucht KEINE Bindung mehr",
      "--bind" in befehl and lt.MPL_ZIEL not in befehl,
      "er liegt im Arbeitsverzeichnis, das je Benutzer existiert")
pruef("ro-Bindung uebernommen", "--ro-bind %s %s" % (echt, echt) in befehl)
pruef("--unshare-pid (keine fremden Prozesse)", "--unshare-pid" in befehl)
pruef("--die-with-parent", "--die-with-parent" in befehl)
pruef("--proc /proc", "--proc /proc" in befehl)
pruef("chdir ins Lauf-Verzeichnis", "--chdir /tmp" in befehl)
ohne = lt.sandbox_befehl("jarvis_sandbox", "echo hallo", None)
pruef("ohne Arbeitsverzeichnis: bisheriger Aufruf",
      ohne.startswith("runuser -u jarvis_sandbox -- /bin/bash -c") and "bwrap" not in ohne,
      "fail-open: ohne Isolation muss alles wie vorher laufen")
isolation_erzwingen(False)
pruef("ohne bwrap: kein bwrap im Aufruf",
      "bwrap" not in lt.sandbox_befehl("jarvis_sandbox", "echo hi",
                                       lt.ARBEIT_ROOT / "abcdef01"))
isolation_erzwingen(True)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("6b. POSITIVKONTROLLE der Verfuegbarkeitspruefung")

# Diese Pruefung fehlte und hat Geld gekostet: alle Abschnitte oben ersetzen
# `bwrap_verfuegbar()` durch einen festen Wert (`isolation_erzwingen`) – ein
# Fehler IN der Pruefung selbst ist damit unsichtbar. Genau das passierte beim
# Entfernen des mpl-Arguments: ein Positionsargument rutschte auf `_pruefen`,
# die Pruefung warf TypeError, und die Isolation war STILL AUS (fail-open).
lt._verf_cache.clear()
if os.path.exists(lt.BWRAP):
    pruef("bwrap_verfuegbar() sagt bei installiertem bwrap wirklich JA",
          lt.bwrap_verfuegbar() is True,
          "sonst laeuft alles ohne Isolation weiter, ohne dass es auffaellt")
    lt._verf_cache.clear()
    with lt.lauf_scope("alice", privilegiert=False) as _echt:
        pruef("und die Klammer bindet dann auch wirklich", _echt is not None)
else:
    print("  (uebersprungen: bwrap ist auf diesem Rechner nicht installiert)")
lt._verf_cache.clear()
os.environ["JARVIS_LAUF_ISOLATION"] = "0"
pruef("Schalter JARVIS_LAUF_ISOLATION=0 wirkt", lt.bwrap_verfuegbar() is False)
del os.environ["JARVIS_LAUF_ISOLATION"]
lt._verf_cache.clear()
isolation_erzwingen(True)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("7. ECHTE Isolation (mit installiertem bwrap)")

if not os.path.exists(lt.BWRAP):
    print("  (uebersprungen: bwrap ist auf diesem Rechner nicht installiert)")
else:
    lauf_dir = Path(tempfile.mkdtemp(prefix="lauf_", dir="/tmp"))
    anh_dir = Path(tempfile.mkdtemp(prefix="anh_", dir="/tmp"))
    fremd = Path(tempfile.mkdtemp(prefix="fremd_", dir="/tmp")) / "fremd.txt"
    fremd.parent.mkdir(parents=True, exist_ok=True)
    fremd.write_text("geheime fremde Arbeitskopie")
    os.chmod(fremd, 0o644)
    (anh_dir / "anhang_0123456789ab_tab.csv").write_text("spalte;wert\na;1\n")
    os.chmod(anh_dir / "anhang_0123456789ab_tab.csv", 0o644)

    def lauf(cmd, ro=(), dev=True):
        b = lt.sandbox_befehl("", cmd, lauf_dir, ro, _pruefen=True)
        if not dev:                     # Gegenprobe: gewoehnliche Bindung
            b = b.replace("--dev-bind / /", "--bind / /")
        r = subprocess.run(["/bin/bash", "-c", b], capture_output=True,
                           text=True, timeout=60)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    rc, aus = lauf("ls -A /tmp")
    pruef("fremde /tmp-Datei ist im Lauf NICHT VORHANDEN",
          rc == 0 and "fremd_" not in aus,
          "das ist der Kern: nicht 'nicht lesbar', sondern nicht existent")
    rc, aus = lauf("cat %s 2>&1" % fremd)
    pruef("fremde Arbeitskopie nicht lesbar", "geheime" not in aus, aus.strip()[:80])

    rc, aus = lauf("echo inhalt > /tmp/ergebnis.txt; echo fertig")
    pruef("Ergebnis landet auf dem HOST im Arbeitsverzeichnis",
          (lauf_dir / "ergebnis.txt").read_text().strip() == "inhalt" if
          (lauf_dir / "ergebnis.txt").exists() else False,
          "ohne diese Uebergabe faellt jeder Download-Chip aus")

    rc, aus = lauf("echo x 2>/dev/null && echo devnull-ok")
    pruef("2>/dev/null funktioniert (--dev-bind)", "devnull-ok" in aus, aus.strip()[:120])
    rc, aus = lauf("echo x 2>/dev/null && echo devnull-ok", dev=False)
    pruef("GEGENPROBE: mit --bind / / scheitert genau das",
          "devnull-ok" not in aus,
          "wenn das hier gruen ist, prueft der Test seine eigene Annahme")

    rc, aus = lauf("cat %s/anhang_0123456789ab_tab.csv" % anh_dir, ro=[str(anh_dir)])
    pruef("eigener Anhang ist im Lauf lesbar", "spalte;wert" in aus, aus.strip()[:120])
    rc, aus = lauf("echo kaputt > %s/anhang_0123456789ab_tab.csv 2>&1" % anh_dir,
                   ro=[str(anh_dir)])
    pruef("Anhang ist im Lauf NICHT beschreibbar", rc != 0,
          "ro-Bindung: der Agent darf den Upload nicht beschaedigen")

    rc, aus = lauf("ps ax | wc -l")
    try:
        anzahl = int((aus.strip().splitlines() or ["999"])[-1])
    except ValueError:
        anzahl = 999
    pruef("keine fremden Prozesse sichtbar (--unshare-pid)", anzahl <= 12, f"{anzahl} Prozesse")

    rc, aus = lauf("python3 -c 'import tempfile,os;print(os.path.dirname(tempfile.mkstemp()[1]))'")
    pruef("Python-Temp landet im Arbeitsverzeichnis", "/tmp" in aus, aus.strip()[:80])

    for d in (lauf_dir, anh_dir, fremd.parent):
        shutil.rmtree(d, ignore_errors=True)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("8. Aufraeumen")

isolation_erzwingen(True)
alt = lt.anhang_ziel("alice", "alt.xlsx")
alt.write_text("alt")
os.utime(alt, (0, 0))
neu = lt.anhang_ziel("alice", "neu.xlsx")
neu.write_text("neu")
weg = att.cleanup(ttl_min=30)
pruef("alte Arbeitskopie im Benutzer-Verzeichnis wird entfernt", alt.name in weg, str(weg))
pruef("junge Arbeitskopie bleibt", neu.exists())

lt.ARBEIT_ROOT.mkdir(parents=True, exist_ok=True)
liegen = lt.ARBEIT_ROOT / ("a" * 8)
liegen.mkdir(exist_ok=True)
(liegen / "rest.txt").write_text("x")
os.utime(liegen, (0, 0))
frisch = lt.ARBEIT_ROOT / ("b" * 8)
frisch.mkdir(exist_ok=True)
weg2 = att.cleanup_arbeit(ttl_min=30)
pruef("abgelaufenes Arbeitsverzeichnis wird entfernt", liegen.name in weg2, str(weg2))
pruef("frisches Arbeitsverzeichnis bleibt", frisch.exists(),
      "die Frist ist die einzige Schranke gegen ein Verzeichnis, in dem gearbeitet wird")
# Untergrenze: eine kleine Frist darf ein Verzeichnis NICHT wegnehmen, in dem
# gerade gearbeitet werden koennte – anders als bei den Arbeitskopien gibt es
# hier kein "Lauf zu Ende, weg damit".
_zwei_std = lt.ARBEIT_ROOT / ("c" * 8)
_zwei_std.mkdir(parents=True, exist_ok=True)
os.utime(_zwei_std, (time.time() - 2 * 3600, time.time() - 2 * 3600))
pruef("Untergrenze 4 Stunden: 2 Stunden alt bleibt trotz ttl_min=1",
      att.cleanup_arbeit(ttl_min=1) == [] and _zwei_std.exists())
os.utime(_zwei_std, (time.time() - 5 * 3600, time.time() - 5 * 3600))
pruef("5 Stunden alt wird entfernt", att.cleanup_arbeit(ttl_min=1) == [("c" * 8)])
pruef("TTL 0 schaltet beides ab",
      att.cleanup(ttl_min=0) == [] and att.cleanup_arbeit(ttl_min=0) == [])

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("8b. Temp-Skripte, Lauf-Eigentuemer, Root-Aufraeumen")

isolation_erzwingen(True)
pruef("ohne Lauf: Temp-Verzeichnis ist /tmp", lt.temp_verzeichnis() == lt.TMP_ECHT)
pruef("chmod nur als Eigentuemer (kein EPERM-Rauschen)",
      "st_uid == os.getuid()" in (WURZEL / "backend/lauf_tmp.py").read_text(),
      "sonst meldet jeder Shell-Befehl nach dem ersten einen Fehler, obwohl alles geht")
with lt.lauf_scope("alice", privilegiert=False) as lauf:
    pruef("mit Lauf: Temp-Verzeichnis IST das Lauf-Verzeichnis",
          lt.temp_verzeichnis() == lauf.verzeichnis,
          "das Skript braucht dann keine eigene Bindung")
    skript = lauf.verzeichnis / "jarvis_probe.py"
    skript.write_text("print(1)")
    os.chmod(skript, 0o600)
    lt.temp_datei_freigeben(str(skript))
    pruef("Temp-Skript wird auf 0644 freigegeben",
          (os.stat(skript).st_mode & 0o777) == 0o644,
          "ALTFEHLER: mit 0600 kann jarvis_sandbox es nicht ausfuehren (Errno 13)")
    # Eigentuemer des Arbeitsbereichs
    fremder = lt.ARBEIT_ROOT / lt.benutzer_kennung("bob")
    fremder.mkdir(parents=True, exist_ok=True)
    (fremder / "ergebnis.xlsx").write_text("fremd")
    pruef("eigene Ergebnisdatei: True",
          lt.gehoert_arbeitsbereich(lauf.verzeichnis / "ergebnis.xlsx", "alice") is True)
    pruef("FREMDE Ergebnisdatei: False",
          lt.gehoert_arbeitsbereich(fremder / "ergebnis.xlsx", "alice") is False,
          "sonst oeffnet ein Backend-Werkzeug die Datei eines fremden Benutzers")
    pruef("mit Domaenen-Praefix erkannt",
          lt.gehoert_arbeitsbereich(lauf.verzeichnis / "x", "nexus\\alice") is True)
    pruef("Wurzel selbst: None", lt.gehoert_arbeitsbereich(lt.ARBEIT_ROOT, "alice") is None)
    pruef("Pfad ausserhalb: None",
          lt.gehoert_arbeitsbereich(lt.TMP_ECHT / "x", "alice") is None)
pruef("ohne bekannten Benutzer ist jeder Arbeitsbereich fremd",
      lt.gehoert_arbeitsbereich(fremder / "ergebnis.xlsx", "") is False, "fail-closed")
pruef("die Pruefung braucht KEINEN laufenden Auftrag",
      lt.gehoert_arbeitsbereich(fremder / "ergebnis.xlsx", "bob") is True,
      "die Grenze ist Benutzer gegen Benutzer, nicht Lauf gegen Lauf")

# Root-Aufraeumen (laeuft auch unprivilegiert, solange die Dateien uns gehoeren)
ziel = lt.ARBEIT_ROOT / ("d" * 8)
(ziel / "unter").mkdir(parents=True, exist_ok=True)
(ziel / "unter" / "x.txt").write_text("x")
pruef("aufraeumen_root entfernt samt Unterverzeichnis",
      lt.aufraeumen_root(("d" * 8)) == [("d" * 8)] and not ziel.exists())
pruef("aufraeumen_root lehnt fremde Muster ab",
      lt.aufraeumen_root("../../etc") == [] and lt.aufraeumen_root("kurz") == [],
      "eine Kennung aus einem Argument darf nichts anderswo loeschen")
alt_arbeit = lt.ARBEIT_ROOT / ("e" * 8)
alt_arbeit.mkdir(parents=True, exist_ok=True)
os.utime(alt_arbeit, (0, 0))
jung = lt.ARBEIT_ROOT / ("f" * 8)
jung.mkdir(parents=True, exist_ok=True)
weg3 = lt.aufraeumen_root("", alter_min=60)
pruef("Kehrbesen nimmt nur alte Verzeichnisse",
      ("e" * 8) in weg3 and jung.exists(), str(weg3))
_symlink = lt.ARBEIT_ROOT / ("9" * 8)
if not _symlink.exists():
    os.symlink("/etc", str(_symlink))
pruef("Symlink wird nicht verfolgt",
      lt.aufraeumen_root(("9" * 8)) == [] and Path("/etc").is_dir(),
      "lstat statt stat – sonst raeumt der Kehrbesen /etc ab")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("8c. Zusatz-Bindungen (Arbeitsverzeichnisse, die den Lauf ueberleben)")

arbeit = Path("/tmp") / ("claude_probe_" + os.urandom(4).hex())
(arbeit / "work").mkdir(parents=True, exist_ok=True)
try:
    pruef("ohne Anmeldung: keine Zusatz-Bindung", lt.zusatz_binds() == ())
    with lt.zusatz_bind(str(arbeit)):
        pruef("angemeldet", lt.zusatz_binds() == (str(arbeit),))
        with lt.lauf_scope("alice", privilegiert=False):
            pruef("Zusatz-Pfad wird NICHT umgeschrieben",
                  lt.aufloesen(str(arbeit / "work" / "x.py")) == str(arbeit / "work" / "x.py"),
                  "sonst suchen die Backend-Werkzeuge im Lauf-Verzeichnis")
            pruef("gewoehnlicher /tmp-Pfad wird weiter umgeschrieben",
                  lt.aufloesen(str(lt.TMP_ECHT / "y.txt")) != str(lt.TMP_ECHT / "y.txt"))
        b = lt.sandbox_befehl("jarvis_sandbox", "echo hi", lt.ARBEIT_ROOT / ("1" * 8),
                              (), _pruefen=True, rw_binds=[str(arbeit)])
        pruef("RW-Bindung landet im bwrap-Aufruf",
              "--bind %s %s" % (arbeit, arbeit) in b)
    pruef("nach dem Verlassen wieder leer", lt.zusatz_binds() == ())
    with lt.zusatz_bind("/etc", "relativ/x", str(arbeit)):
        pruef("fremde Pfade werden verworfen", lt.zusatz_binds() == (str(arbeit),),
              "sonst holt ein Aufrufer beliebige Verzeichnisse in einen Lauf")
    pruef("RW-Validierung: Verzeichnis ok", lt.rw_binds_pruefen([str(arbeit)]) == [str(arbeit)])
    pruef("RW-Validierung: Datei abgewiesen",
          lt.rw_binds_pruefen([str(arbeit / "work" / "gibtsnicht")]) == [])
    pruef("RW-Validierung: /tmp selbst abgewiesen", lt.rw_binds_pruefen(["/tmp"]) == [])
    pruef("RW-Validierung: Verwaltungswurzeln abgewiesen",
          lt.rw_binds_pruefen([str(lt.ANH_ROOT), str(lt.ARBEIT_ROOT)]) == [],
          "eine RW-Bindung auf ANH_ROOT waere Schreibrecht auf ALLE Arbeitskopien")
    pruef("RW-Validierung: Deckel bei 8", len(lt.rw_binds_pruefen([str(arbeit)] * 40)) <= 8)
finally:
    shutil.rmtree(arbeit, ignore_errors=True)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("9. Drift-Schranken (die Naehte zwischen den Dateien)")

def quelle(rel):
    return (WURZEL / rel).read_text(encoding="utf-8")

sh = quelle("backend/tools/shell.py")
pruef("shell.py gibt die Benutzer-Kennung an den Broker",
      '"arbeit": _lauf.kennung if _lauf else ""' in sh)
pruef("shell.py gibt die ro-Bindungen mit", '"ro_binds": _ro_binds' in sh)
pruef("shell.py bindet das Anhang-Verzeichnis ein", "anhang_binds" in sh)
pruef("shell.py setzt TMPDIR", "TMPDIR=/tmp" in sh)
pruef("kein 'rm -f' des Temp-Skripts mehr im Befehl", "rm -f {tmp.name}" not in sh,
      "auf einem Einhaengepunkt scheitert es lautstark")
pruef("Temp-Skripte werden vom Aufrufer entfernt", "_temp_weg(" in sh)
pruef("Temp-Skript liegt im Lauf-Verzeichnis", "_lt.temp_verzeichnis()" in sh)
pruef("Temp-Skript wird lesbar gemacht", "temp_datei_freigeben" in sh)
pruef("Befehl nennt den MODELL-Pfad des Skripts", '"/tmp/" + os.path.basename(tmp.name)' in sh)
pruef("Temp-Skripte werden NICHT mehr gebunden", "_ro_binds = list(_tempdateien)" not in sh)
pruef("lokaler Zweig: eigene Prozessgruppe", "start_new_session=True" in sh)
pruef("Timeout beendet die Gruppe (3 Aufrufstellen)",
      sh.count("self._gruppe_beenden(proc)") == 3,
      "beide Streaming-Zweige und der klassische Modus – die Definition zaehlt nicht mit")

ops = quelle("backend/broker/ops.py")
pruef("Broker nutzt lauf_tmp (keine zweite bwrap-Fassung)",
      "arbeit_bereitstellen" in ops and "sandbox_befehl" in ops)
pruef("Broker validiert die Bindungen", "binds_pruefen" in ops)
pruef("Broker faellt bei Fehlern auf gemeinsames /tmp zurueck",
      "gemeinsames /tmp" in ops, "fail-open, sonst stirbt jeder Shell-Befehl")
pruef("Broker bereitet die Einhaengepunkte vor", "einhaengepunkte(" in ops,
      "sonst legt bwrap sie als Sandbox-Benutzer an und das Aufraeumen scheitert STILL")
pruef("Broker-Op zum Aufraeumen ist registriert",
      '"lauf_aufraeumen": (' in ops and "_op_lauf_aufraeumen" in ops)
pruef("Broker: eigene Prozessgruppe", "start_new_session=True" in ops)
pruef("Broker-Timeout beendet die Gruppe", "_abwuergen()" in ops and "killpg" in ops)
pruef("Broker hat einen WACHHUND (stiller Befehl)", "_wachhund" in ops and "Timer(" in ops,
      "ohne ihn blockiert `for line in proc.stdout` bei `sleep 300` unbegrenzt "
      "und der Prozessbaum ueberlebt den Timeout")
pruef("Wachhund wird im finally abgeraeumt", "_wachhund.cancel()" in ops)
pruef("Abbruch per Signal wird als Timeout gemeldet", "returncode < 0" in ops)

ag = quelle("backend/agent.py")
pruef("run_task oeffnet die Lauf-Klammer", ag.count("_lauf_tmp.lauf_scope(") == 2,
      "run_task UND _run_headless – eine allein waere die halbe Reparatur")
pruef("_deliver_docs nutzt such_wurzeln", "_lauf_tmp.such_wurzeln()" in ag)
pruef("_deliver_docs uebersetzt Textpfade", "_hostpfad(raw)" in ag)
pruef("_deliver_docs prueft die mtime WEITER",
      "_lauf_verz" not in ag and "since - self._DELIVER_TOLERANCE_SEC" in ag,
      "das Arbeitsverzeichnis gehoert dem Benutzer und enthaelt auch Dateien "
      "frueherer Laeufe – es beweist NICHT, dass eine Datei aus diesem Lauf ist")
pruef("Dispatch lenkt Werkzeug-Pfade um", "_lauf_pfade_umleiten(name, tool, exec_args)" in ag)

sbx = quelle("backend/sandbox.py")
pruef("authorize_fs prueft den Anhang-Eigentuemer", "gehoert_anhang" in sbx)
pruef("authorize_fs prueft auch den Arbeitsbereich", "gehoert_arbeitsbereich" in sbx,
      "sonst liest ein Backend-Werkzeug die Ergebnisdatei eines fremden Benutzers")
pruef("wrap_sandboxed delegiert an lauf_tmp", "sandbox_befehl" in sbx)

mn = quelle("backend/main.py")
pruef("main.py legt Arbeitskopien ueber lauf_tmp ab", "_lauf_tmp.anhang_ziel(benutzer" in mn)
pruef("Kehrbesen fuer Arbeitsverzeichnisse ist verdrahtet", "cleanup_arbeit" in mn)
pruef("Kehrbesen laeuft unprivilegiert ueber den Broker",
      'lauf_aufraeumen", {"alter_min"' in mn)
pruef("Zustand wird beim Start gemeldet", "startup_lauf_isolation" in mn)

st = quelle("backend/short_tracks_runner.py")
pruef("Short Tracks gibt den Besitzer mit", "_lauf_tmp.anhang_ziel(besitzer" in st)

cs = quelle("backend/claude_subagent.py")
pruef("Claude-Subagent meldet seinen Wegwerf-Klon an", "zusatz_bind(" in cs,
      "sonst existiert /tmp/claude_subagent/<job> im Lauf NICHT und der Skill ist still kaputt")
pruef("shell.py reicht RW-Bindungen durch", '"rw_binds": _rw_binds' in sh)
pruef("Broker validiert RW-Bindungen", "rw_binds_pruefen" in ops)

off = quelle("skills/office/main.py")
pruef("office_read/-to_pdf uebersetzen /tmp-Pfade", "_lt.aufloesen(path)" in off,
      "sonst findet office_read die Datei nicht, die die Shell gerade schrieb")
conf = quelle("skills/confluence/main.py")
pruef("Confluence-Download legt in das Lauf-Verzeichnis", "temp_verzeichnis()" in conf)
pruef("Confluence meldet den Modell-Pfad", '"/tmp/" + _os.path.basename(path)' in conf)
attq = quelle("backend/attachments.py")
pruef("Frist ist mit Isolation groesser", "DEFAULT_TTL_MIN_ISOLIERT" in attq,
      "ohne Isolation bleibt sie die einzige Schranke und damit kurz")

boot = quelle("start_jarvis_root.sh")
pruef("Bootstrap installiert bubblewrap nach", "bubblewrap" in boot)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("10. Isoliert die AUSFUEHRENDE Seite auch? (Vorfall 2026-08-24)")
# Der Broker ist ein EIGENER Prozess mit eigener Kopie von backend/broker/*.
# Lief er noch mit einer Fassung von vor diesem Umbau, nahm er `arbeit` klaglos
# an und ignorierte es: die Shell schrieb ins gemeinsame /tmp, waehrend das
# Backend weiter uebersetzte und die Ergebnisdatei im Lauf-Verzeichnis suchte.
# Auf ECHT vier Laeufe, zwei fertige Auswertungen unerreichbar – ohne eine
# einzige Zeile im Journal.
pruef("der Broker MELDET, ob er isoliert hat", '"isolation"] = bool(lauf_dir)' in ops,
      "ohne Rueckmeldung kann das Backend die halb aktive Isolation nicht erkennen")
pruef("shell.py wertet die Meldung aus", "melde_ausfuehrung(bool(res.get(\"isolation\")))" in sh)
pruef("nur bei angeforderter Isolation und wirklich gelaufenem Befehl",
      'op == "sandbox_exec" and args.get("arbeit") and "rc" in res' in sh,
      "pending/denied/unreachable sagen nichts ueber die Isolation")

_alt_zustand = lt._ausf_isoliert
try:
    isolation_erzwingen(True)
    lt.melde_ausfuehrung(False)
    pruef("gemeldetes 'nicht isoliert' schaltet die Uebersetzung ab",
          lt.ausfuehrung_unwirksam() is True)
    with lt.lauf_scope("alice", False) as lauf:
        pruef("und es entsteht gar kein Lauf mehr", lauf is None,
              "sonst uebersetzen Auslieferung und Werkzeuge weiter ins Leere")

    # Der Kern: MIT Lauf-Kontext, aber gemeldet unwirksam -> Pfad bleibt.
    _kn = lt.benutzer_kennung("alice")
    _tok = lt._lauf_cv.set(lt.Lauf(lt.ARBEIT_ROOT / _kn, "alice", _kn))
    try:
        modell = str(lt.TMP_ECHT / "ergebnis.xlsx")
        pruef("aufloesen() laesst den Pfad unangetastet",
              lt.aufloesen(modell) == modell,
              f"uebersetzt zu {lt.aufloesen(modell)}")
        lt.melde_ausfuehrung(True)
        pruef("Gegenprobe: nach 'isoliert' wird wieder uebersetzt",
              lt.aufloesen(modell) != modell)
    finally:
        lt._lauf_cv.reset(_tok)

    lt._ausf_isoliert = None
    pruef("ungemessen (None) gilt NICHT als unwirksam",
          lt.ausfuehrung_unwirksam() is False,
          "sonst waere die Isolation nach jedem Dienststart einmal aus")
    with lt.lauf_scope("alice", False) as lauf:
        pruef("und der erste Lauf bekommt seine Klammer", lauf is not None)
    pruef("bericht() weist den Zustand aus", "ausfuehrung_isoliert" in lt.bericht())
finally:
    lt._ausf_isoliert = _alt_zustand

ag = quelle("backend/agent.py")
pruef("ein verfehlter Liefer-Marker wird protokolliert",
      "Liefer-Marker OHNE Auslieferung" in ag,
      "vorher brach der Zweig mit einem nackten `continue` ab – ohne jede Spur")
pruef("und dem Benutzer gemeldet",
      "Konnte nicht zum Download bereitgestellt werden" in ag,
      "der Chip ist der EINZIGE Weg zur Datei; faellt er aus, muss es sichtbar sein")
pruef("gemeldet wird nur beim letzten Text des Laufs",
      "since=_task_start_time, melden=True" in ag,
      "ein Werkzeug-Ergebnis warnt sonst, bevor die Datei entstanden ist")

# ═══════════════════════════════════════════════════════════════════════════
shutil.rmtree(SANDKASTEN, ignore_errors=True)
print(f"\n{'='*66}\nErgebnis: {ok} ok, {fail} FAIL")
sys.exit(1 if fail else 0)
