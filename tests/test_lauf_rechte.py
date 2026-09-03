#!/usr/bin/env python3
"""Waechter fuer den Vorfall vom 2026-09-03 (ECHT): drei Fixes in einem Lauf.

1. ``_shell_internet_hit`` – die Egress-Heuristik traf Wortlaute in
   ZEICHENKETTEN ("SSH"/"HTTP" als Beschriftung in einem Firewall-Diagramm) und
   sperrte damit jedes Netz-/Portdiagramm fuer Benutzer ohne Internet-Freigabe.
2. ``ARBEIT_MODUS``/``umask 002``/``im_lauf_freigeben`` – im Arbeitsverzeichnis
   schreiben ZWEI Identitaeten (Shell als ``jarvis_sandbox*``, Werkzeuge als
   Dienstbenutzer); keine konnte die Datei der anderen ueberschreiben.
3. ``FileSystemTool._schreibe`` – Netz fuer den Altbestand: Datei der jeweils
   anderen Seite wird ersetzt statt mit blankem "Zugriff verweigert" abgewiesen.

Dazu die Luecke, die beim Bauen auffiel: die Eigentuemer-Schranke in
``authorize_fs`` galt nur fuers LESEN.

GEMESSEN, NICHT GELESEN: alle vier Abschnitte fuehren die echten Funktionen aus.
Ein Quelltext-Grep haette Punkt 1 nie gefunden – die Regexe waren ja alle da.
"""
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(bez, bedingung):
    """check(Beschreibung, Bedingung) – Reihenfolge wird ERZWUNGEN.

    In `test_jira_vorlagen.py` waren am 2026-08-28 alle 57 Aufrufe vertauscht;
    eine nicht-leere Zeichenkette ist wahr, der Lauf meldete "57 OK, 0 FAIL"
    ohne eine einzige Bedingung ausgewertet zu haben. Exit 2, nicht 1: "konnte
    nicht laufen" darf nie wie "bestanden" aussehen.
    """
    global _ok, _fail
    if not isinstance(bez, str) or isinstance(bedingung, str):
        print(f"ABBRUCH: check(Beschreibung, Bedingung) vertauscht: {bez!r}")
        sys.exit(2)
    if bedingung:
        _ok += 1
        print(f"OK   {bez}")
    else:
        _fail += 1
        print(f"FAIL {bez}")


def sicher(bez, fn):
    """Ruft eine Pruefung, die werfen KANN, und wertet den Wurf als FAIL.

    Register: nie ungeprueft dereferenzieren – eine Gegenprobe, die abbricht,
    sieht wie ein bestandener Lauf aus (kein FAIL, keine Bilanzzeile).
    """
    try:
        check(bez, fn())
    except Exception as e:  # noqa: BLE001
        check(f"{bez} [warf {type(e).__name__}: {e}]", False)


# ══ Sandkasten ═══════════════════════════════════════════════════════════════
SANDKASTEN = Path(tempfile.mkdtemp(prefix="jarvis_rechte_"))

from backend import lauf_tmp as lt              # noqa: E402
from backend import sandbox as sb               # noqa: E402

lt.ARBEIT_ROOT = SANDKASTEN / "jarvis-arbeit"
lt.ANH_ROOT = SANDKASTEN / "jarvis-anhaenge"
lt.ARBEIT_ROOT.mkdir(parents=True)
lt.ANH_ROOT.mkdir(parents=True)

# Register: der Sandkasten-Waechter bricht mit Exit 2 ab, wenn eine Wurzel nicht
# umgebogen ist – ein Test, der in das echte /tmp/jarvis-arbeit schreibt, koennte
# die Arbeitsdateien laufender Auftraege anfassen.
for _name in ("ARBEIT_ROOT", "ANH_ROOT"):
    _w = str(getattr(lt, _name))
    if not _w.startswith(str(SANDKASTEN)):
        print(f"ABBRUCH: {_name} zeigt nach {_w} – nicht in den Sandkasten")
        sys.exit(2)

print("── 1. Egress-Heuristik: Beschriftung ist kein Befehl ──")
# ``backend.agent`` braucht fastapi (in dieser Umgebung nicht installiert), also
# werden die drei Funktionen samt ihrer Regexe HERAUSGESCHNITTEN und wirklich
# ausgefuehrt. ``backend.sandbox`` wird dabei ECHT importiert – ``strip_quoted``
# ist der Kern des Fixes und darf keine Attrappe sein.
_A = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
_ns = {"re": re}
for _von, _bis in (("_CMD_SPLIT = re.compile", "def _forbidden_command_hit"),
                   ("_LOOPBACK =", "# ── Instructions aus")):
    exec(compile(_A[_A.index(_von):_A.index(_bis)], "agent.py-schnitt", "exec"), _ns)
for _n in ("_shell_internet_hit", "_shell_hits_internet", "_cmd_segmente"):
    if _n not in _ns:
        print(f"ABBRUCH: {_n} nicht im Schnitt – Waechter misst nichts")
        sys.exit(2)
_shell_internet_hit = _ns["_shell_internet_hit"]
_shell_hits_internet = _ns["_shell_hits_internet"]
_cmd_segmente = _ns["_cmd_segmente"]
# Positivkontrolle des Schnitts: die echte strip_quoted MUSS erreichbar sein,
# sonst faellt _shell_internet_hit still in seinen fail-closed-Zweig und jede
# "frei"-Pruefung waere aus dem falschen Grund gruen bzw. rot.
if not hasattr(sb, "strip_quoted"):
    print("ABBRUCH: backend.sandbox.strip_quoted fehlt")
    sys.exit(2)

FIREWALL = """python3 << 'EOF'
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ports = [("22", "SSH"), ("80", "HTTP"), ("443", "HTTPS"), ("6080", "noVNC")]
plt.savefig('/tmp/firewall_chart.png')
EOF"""

MUSS_FREI = [
    ("Firewall-Diagramm (der gemeldete Fall)", FIREWALL),
    ("grep nach ssh in einem Log", "grep -rn 'ssh' /tmp/journal.txt"),
    ("echo mit HTTP-Label", "echo 'HTTP 80 offen'"),
    ("matplotlib-Import allein", 'python3 -c "import matplotlib.pyplot as plt"'),
    ("curl auf localhost", "curl -s http://localhost:8080/api/health"),
    ("Datei mit ftp im Namen lesen", "cat /tmp/ftp_bericht.txt"),
    ("pandas liest eine CSV", 'python3 -c "import pandas as pd; pd.read_csv(\'/tmp/a.csv\')"'),
    ("Label mit git im Wort", "echo 'Anzahl Digits: 5'"),
]
MUSS_BLOCKEN = [
    ("curl auf eine externe URL", "curl -s https://example.com/x"),
    ("curl schemenlos", "curl example.com"),
    ("wget extern", "wget https://firma.de/a.zip"),
    ("ssh als Befehl", "ssh user@host 'ls'"),
    ("git clone", "git clone https://github.com/x/y"),
    ("urlopen in Anfuehrungszeichen", 'python3 -c "import urllib.request; urllib.request.urlopen(\'https://x.de\')"'),
    ("requests.get", 'python3 -c "import requests; requests.get(\'https://x.de\')"'),
    ("sudo davor", "sudo curl https://x.de"),
    ("nc hinter einer Pipe", "cat /etc/hostname | nc example.com 9000"),
    ("xargs wget", "echo url | xargs wget https://x.de"),
    ("socat", "socat TCP:example.com:80 -"),
    ("scp nach draussen", "scp /tmp/a.txt user@host:/tmp/"),
    ("Semikolon-Kette", "cd /tmp; curl https://x.de"),
]
for _n, _c in MUSS_FREI:
    _t = _shell_internet_hit(_c)
    check(f"frei:   {_n}" + (f"  [blockiert wegen {_t!r}]" if _t else ""), not _t)
for _n, _c in MUSS_BLOCKEN:
    check(f"blockt: {_n}", bool(_shell_internet_hit(_c)))

check("bool-Fassung bleibt fuer Bestands-Aufrufer erhalten",
      _shell_hits_internet("curl https://x.de") is True
      and _shell_hits_internet(FIREWALL) is False)
check("Treffer wird BENANNT (fuer die Meldung)",
      _shell_internet_hit("ssh host") == "ssh")
check("leerer Befehl ist kein Treffer", _shell_internet_hit("") == "")
# Anfuehrungszeichen leeren verhindert PSEUDO-SEGMENTE: `_CMD_SPLIT` trennt an
# `;`, und ohne strip_quoted beginnt das zweite Segment mit einem fremden Wort.
check("Trennzeichen IN Anfuehrungszeichen erzeugt keinen Fehlalarm",
      not _shell_internet_hit('grep "foo; ssh host" /tmp/a.txt'))
# Fail-closed: bei OFFENEM Anfuehrungszeichen gibt strip_quoted den Originaltext
# zurueck – dann entsteht das Pseudo-Segment und die Regel greift wieder.
check("offenes Anfuehrungszeichen -> streng (fail-closed)",
      bool(_shell_internet_hit('grep "foo; ssh host /tmp/a.txt')))
# Und die Befehlsposition bleibt auch dort verankert: ein echo bleibt ein echo.
check("offenes Anfuehrungszeichen ohne Trennzeichen bleibt harmlos",
      not _shell_internet_hit('echo "ssh'))
check("_cmd_segmente streift Wrapper ab",
      _cmd_segmente("sudo nohup curl x")[0].startswith("curl"))
# Die Nutzlast-Erkennung MUSS ueber den rohen Befehl laufen – sonst sieht sie
# `python3 -c "...urlopen..."` nicht mehr (alles in Anfuehrungszeichen).
_src_agent = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
_i = _src_agent.index("def _shell_internet_hit")
_j = _src_agent.index("def _shell_hits_internet")
_rumpf = _src_agent[_i:_j]
_rumpf_ohne_doc = _rumpf.split('"""')[2] if _rumpf.count('"""') >= 2 else _rumpf
check("_SCRIPT_NET wird auf den ROHEN Befehl angewandt",
      "_SCRIPT_NET.search(cmd)" in _rumpf_ohne_doc)
check("_NET_TOOLS/_DL_TOOLS nur mit match (Befehlsposition)",
      "_NET_TOOLS.match(seg)" in _rumpf_ohne_doc
      and "_DL_TOOLS.match(seg)" in _rumpf_ohne_doc
      and "_NET_TOOLS.search" not in _rumpf_ohne_doc
      and "_DL_TOOLS.search" not in _rumpf_ohne_doc)
# Der Dispatch darf einen Fehltreffer NICHT als Sicherheitsverstoss zaehlen
# (sonst sperrt ein Diagramm nach drei Versuchen ein Konto).
_i2 = _src_agent.index("elif name == \"shell_execute\" and (_net_hit")
_umfeld = _src_agent[_i2:_i2 + 1200]
check("Internet-Sperre setzt keinen Verstoss (_viol)", "_viol =" not in _umfeld)
check("Meldung nennt das getroffene Wort", "{_net_hit}" in _umfeld)

print("── 2. Rechte im Arbeitsverzeichnis ──")
check("ARBEIT_MODUS traegt setgid", bool(lt.ARBEIT_MODUS & stat.S_ISGID))
check("ARBEIT_MODUS bleibt 0770 fuer Owner/Gruppe",
      (lt.ARBEIT_MODUS & 0o777) == 0o770)
check("ARBEIT_MODUS gibt 'other' NICHTS", (lt.ARBEIT_MODUS & 0o007) == 0)
check("LAUF_DATEI_MODUS ist beidseitig beschreibbar",
      (lt.LAUF_DATEI_MODUS & 0o666) == 0o666)
check("LAUF_DATEI_MODUS ist NICHT ausfuehrbar",
      (lt.LAUF_DATEI_MODUS & 0o111) == 0)

_src_lt = (ROOT / "backend" / "lauf_tmp.py").read_text(encoding="utf-8")
_ib = _src_lt.index("def arbeit_bereitstellen")
_jb = _src_lt.index("# ── Lauf-Klammer")
_bereit = _src_lt[_ib:_jb]
# Reihenfolge: chown loescht setgid – chmod MUSS danach kommen.
check("arbeit_bereitstellen: chmod NACH chown (chown loescht setgid)",
      _bereit.index("os.chown(ziel") < _bereit.index("os.chmod(ziel"))
check("arbeit_bereitstellen benutzt ARBEIT_MODUS",
      "os.chmod(ziel, ARBEIT_MODUS)" in _bereit)
check("kein festes 0o770 mehr in lauf_tmp",
      "0o770" not in _src_lt)

# umask: nur im ISOLIERTEN Zweig, und VOR dem Befehl.
_cmd_iso = lt.sandbox_befehl("jarvis_sandbox", "echo hallo",
                             lauf_dir=str(lt.ARBEIT_ROOT / "abcd1234"),
                             _pruefen=True)
_cmd_offen = lt.sandbox_befehl("jarvis_sandbox", "echo hallo", lauf_dir=None,
                               _pruefen=True)
check("isolierter Befehl setzt umask 002", "umask 002;" in _cmd_iso)
# NIE .index() in einer Pruefung: fehlt die Marke, WIRFT sie – der Lauf bricht
# dann ohne Bilanzzeile ab und ist von "nicht gelaufen" nicht zu unterscheiden.
# Genau so verlief die erste Gegenprobe zu dieser Zeile.
check("umask steht VOR dem Befehl",
      0 <= _cmd_iso.find("umask 002") < _cmd_iso.find("echo hallo"))
check("ohne Isolation KEIN umask (gemeinsames /tmp bleibt streng)",
      "umask" not in _cmd_offen)
check("bwrap-Aufbau ist unveraendert (--dev-bind bleibt)",
      "--dev-bind" in _cmd_iso and "--unshare-pid" in _cmd_iso)

# im_lauf / im_lauf_freigeben WIRKLICH ausfuehren
_lauf = lt.ARBEIT_ROOT / "abcd1234"
_lauf.mkdir()
_drin = _lauf / "ergebnis.csv"
_drin.write_text("x", encoding="utf-8")
os.chmod(_drin, 0o644)
_draussen = SANDKASTEN / "draussen.csv"
_draussen.write_text("x", encoding="utf-8")
os.chmod(_draussen, 0o644)
check("im_lauf erkennt eine Datei im Arbeitsverzeichnis", lt.im_lauf(_drin) is True)
check("im_lauf erkennt eine Datei ausserhalb", lt.im_lauf(_draussen) is False)
lt.im_lauf_freigeben(_drin)
lt.im_lauf_freigeben(_draussen)
check("im_lauf_freigeben hebt die Datei im Lauf auf 0666",
      (_drin.stat().st_mode & 0o777) == 0o666)
check("im_lauf_freigeben laesst eine Datei AUSSERHALB unangetastet (1777!)",
      (_draussen.stat().st_mode & 0o777) == 0o644)
_weg = _lauf / "gibtsnicht.csv"
sicher("im_lauf_freigeben wirft nicht bei fehlender Datei",
       lambda: lt.im_lauf_freigeben(_weg) is None)
# Kein chmod auf eine FREMDE Datei und keines auf eine schon richtige: sonst
# steht bei jedem `filesystem write` auf eine Shell-Datei eine EPERM-Zeile im
# Journal (live auf DEV genau so passiert).
_src_frei = _src_lt[_src_lt.index("def im_lauf_freigeben"):_src_lt.index("def temp_datei_freigeben")]
_rumpf_frei = _src_frei.split('"""')[2]
check("im_lauf_freigeben chmod't nur als Eigentuemer",
      "st.st_uid != os.getuid()" in _rumpf_frei)
check("im_lauf_freigeben chmod't nicht, wenn der Modus schon stimmt",
      "== LAUF_DATEI_MODUS" in _rumpf_frei)
_schon = _lauf / "schon_richtig.csv"
_schon.write_text("x", encoding="utf-8")
os.chmod(_schon, lt.LAUF_DATEI_MODUS)
_vorher = _schon.stat().st_mtime_ns
lt.im_lauf_freigeben(_schon)
check("richtige Datei bleibt unberuehrt", _schon.stat().st_mtime_ns == _vorher)

print("── 3. filesystem write ersetzt die Datei der anderen Seite ──")
import asyncio                                   # noqa: E402
from backend.tools.filesystem import FileSystemTool  # noqa: E402

_tool = FileSystemTool()
# Eine Datei, die der laufende Prozess NICHT beschreiben kann – dieselbe Lage,
# die auf ECHT durch den Sandbox-Benutzer entsteht (dort fremde uid, hier fehlendes
# Schreibbit; beides ergibt EACCES beim open('w')).
_fremd = _lauf / "firewall_chart.py"
_fremd.write_text("alt", encoding="utf-8")
os.chmod(_fremd, 0o444)


def _lauf_schreiben(inhalt, anhaengen=False):
    return asyncio.run(_tool.execute("append" if anhaengen else "write",
                                     str(_fremd), inhalt))


def _eacces_wirklich():
    """Ohne diese Kontrolle waere Abschnitt 3 trivial gruen: schreibt der Prozess
    die Datei einfach so, ist der Rueckfall nie gelaufen."""
    try:
        with open(_fremd, "w", encoding="utf-8") as f:
            f.write("test")
        return False
    except PermissionError:
        return True


sicher("Positivkontrolle: open('w') scheitert hier wirklich", _eacces_wirklich)


_erg = _lauf_schreiben("neu")
check("write auf die fremde Datei meldet Erfolg", _erg.startswith("✅"))
check("write hat den Inhalt wirklich ersetzt",
      _fremd.read_text(encoding="utf-8") == "neu")
check("ersetzte Datei ist danach beidseitig beschreibbar",
      (_fremd.stat().st_mode & 0o666) == 0o666)

# append muss den alten Inhalt behalten
_fremd2 = _lauf / "daten.csv"
_fremd2.write_text("kopf\n", encoding="utf-8")
os.chmod(_fremd2, 0o444)
_erg2 = asyncio.run(_tool.execute("append", str(_fremd2), "zeile\n"))
check("append auf die fremde Datei meldet Erfolg", _erg2.startswith("✅"))
check("append verliert den alten Inhalt NICHT",
      _fremd2.read_text(encoding="utf-8") == "kopf\nzeile\n")

# AUSSERHALB des Arbeitsverzeichnisses bleibt es ein Fehler – kein allgemeines
# "loesche, was du nicht ueberschreiben darfst".
_draussen_ro = SANDKASTEN / "fremd_draussen.txt"
_draussen_ro.write_text("alt", encoding="utf-8")
os.chmod(_draussen_ro, 0o444)
_erg3 = asyncio.run(_tool.execute("write", str(_draussen_ro), "neu"))
check("ausserhalb des Laufs wird NICHT ersetzt",
      _draussen_ro.read_text(encoding="utf-8") == "alt")
check("und die Meldung sagt, dass es KEINE Sicherheitssperre ist",
      "keine Sicherheitssperre" in _erg3 and "Berechtigung" in _erg3)
check("die alte, irrefuehrende Meldung ist weg",
      not _erg3.startswith("❌ Zugriff verweigert:"))

# Neue Dateien im Lauf werden gleich freigegeben (Gegenrichtung: die Shell
# muss die Datei des Backends anfassen koennen).
_neu = _lauf / "vom_backend.py"
asyncio.run(_tool.execute("write", str(_neu), "print(1)"))
check("neue Backend-Datei im Lauf ist fuer die Shell beschreibbar",
      (_neu.stat().st_mode & 0o666) == 0o666)
_neu_draussen = SANDKASTEN / "neu_draussen.py"
asyncio.run(_tool.execute("write", str(_neu_draussen), "print(1)"))
check("neue Datei AUSSERHALB bleibt bei der umask des Dienstes",
      (_neu_draussen.stat().st_mode & 0o002) == 0)

print("── 4. Eigentuemer-Schranke gilt auch beim SCHREIBEN ──")
_eigen = lt.benutzer_kennung("alice")
_fremd_k = lt.benutzer_kennung("bob")
(lt.ARBEIT_ROOT / _eigen).mkdir(exist_ok=True)
(lt.ARBEIT_ROOT / _fremd_k).mkdir(exist_ok=True)
for _aktion in ("write", "append", "mkdir"):
    _erlaubt, _grund = sb.authorize_fs(_aktion, str(lt.ARBEIT_ROOT / _fremd_k / "x.xlsx"), "alice")
    check(f"{_aktion} in ein FREMDES Arbeitsverzeichnis wird abgewiesen", not _erlaubt)
    check(f"{_aktion}: die Begruendung nennt den Eigentuemer", "Benutzer" in _grund)
_erlaubt, _ = sb.authorize_fs("write", str(lt.ARBEIT_ROOT / _eigen / "x.xlsx"), "alice")
check("write ins EIGENE Arbeitsverzeichnis bleibt erlaubt", _erlaubt)
_erlaubt, _ = sb.authorize_fs("read", str(lt.ARBEIT_ROOT / _fremd_k / "x.xlsx"), "alice")
check("read auf fremd bleibt abgewiesen (Bestand)", not _erlaubt)
# Anhaenge desselben Weges
(lt.ANH_ROOT / _fremd_k).mkdir(exist_ok=True)
_erlaubt, _ = sb.authorize_fs("write", str(lt.ANH_ROOT / _fremd_k / "a.xlsx"), "alice")
check("write in eine fremde Anhang-Arbeitskopie wird abgewiesen", not _erlaubt)
# Gegenrichtung: data/documents darf NICHT ueber diese Schranke laufen, sonst
# waere eine neue Datei fuer ihren eigenen Erzeuger unschreibbar.
_erlaubt, _ = sb.authorize_fs("write", str(sb.DOCS_ROOT / "neu.xlsx"), "alice")
check("write nach data/documents bleibt moeglich (wer schreibt, besitzt)", _erlaubt)
_erlaubt, _ = sb.authorize_fs("write", "/etc/passwd", "alice")
check("write auf /etc bleibt gesperrt", not _erlaubt)
_erlaubt, _ = sb.authorize_fs("write", "/tmp/harmlos.txt", "alice")
check("write ins gewoehnliche /tmp bleibt erlaubt", _erlaubt)

# Positivkontrolle des Sandkastens: das echte /tmp/jarvis-arbeit wurde nie angefasst.
check("Sandkasten: kein Schreibzugriff auf das echte /tmp/jarvis-arbeit",
      not str(lt.ARBEIT_ROOT).startswith("/tmp/jarvis-arbeit"))

shutil.rmtree(SANDKASTEN, ignore_errors=True)
print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
