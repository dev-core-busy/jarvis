#!/usr/bin/env python3
"""Waechter BSI H11-Rest: x11vnc laeuft nie als root.

Befund (BSI-Abgleich 2026-09-29, ECHT nachgemessen 2026-10-12): x11vnc lief als
root ohne Kennwort. Der Paketfilter laesst nur root und den Dienstbenutzer an
5900/6080; ein Fehler in x11vnc, ausgeloest ueber eine solche Verbindung, waere
trotzdem ein Weg vom Dienstbenutzer zu root.

A. REGEL ueber alle Startstellen: jede x11vnc-Argumentliste in Python (x11vnc +
   -rfbport) steht in x11vnc_befehl() und beginnt mit setpriv (--reuid,
   --clear-groups, --no-new-privs); die Server-Skripte rufen x11vnc nicht selbst
   auf; run.sh startet als root nur ueber den Python-Weg.
B. x11vnc_starten() AUSGEFUEHRT (Attrappe fuer subprocess, echter Dateizugriff
   im Sandkasten): Benutzer-uid im Befehl, Cookie als Kopie 0600 im
   Laufzeitverzeichnis, nicht die Quelldatei, kein `-auth guess`, keine
   geerbte Umgebung.
C. Fail-closed: fehlt der Benutzer, startet NICHTS (kein Rueckfall auf root).
D. Eine liegengebliebene Datei/ein Symlink am Zielort wird ersetzt, nie verfolgt.
E. Aufraeumen erfasst auch die Segmente des VNC-Benutzers.
F. Broker-Start: fremde root-Unit abschalten und root-Instanz umstellen,
   BEVOR x11vnc gestartet wird.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import os
import re
import stat
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [%s]" % info) if info else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


def ohne_sh_kommentare(text):
    return "\n".join(z for z in text.splitlines() if not z.lstrip().startswith("#"))


# ── A ──
print("[A] Regel: jede Startstelle")


def _ist_x11vnc(e):
    if isinstance(e, ast.Constant) and e.value == "x11vnc":
        return True
    return isinstance(e, ast.Call) and any(isinstance(a, ast.Constant) and a.value == "x11vnc"
                                           for a in e.args)


starts = []      # (datei, zeile, funktion, liste)
for p in list(ROOT.glob("backend/**/*.py")) + list(ROOT.glob("skills/**/*.py")):
    if "__pycache__" in p.parts:
        continue
    try:
        baum = ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    for fn in ast.walk(baum):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.List) and any(_ist_x11vnc(e) for e in n.elts) \
                    and any(isinstance(e, ast.Constant) and e.value == "-rfbport" for e in n.elts):
                if not isinstance(fn, ast.Module):
                    starts.append((p.relative_to(ROOT), n.lineno, fn.name, n))
if not starts:
    abbruch("Positivkontrolle: keine x11vnc-Startliste in Python gefunden")
fremd = sorted({"%s:%d (%s)" % (d, z, f) for d, z, f, _ in starts if f != "x11vnc_befehl"})
check("x11vnc wird in Python nur in x11vnc_befehl() zusammengesetzt", not fremd, fremd)
for d, z, f, liste in starts:
    if f != "x11vnc_befehl":
        continue
    werte = [e.value for e in liste.elts if isinstance(e, ast.Constant)]
    erst = liste.elts[0] if liste.elts else None
    check("x11vnc_befehl: beginnt mit setpriv",
          isinstance(erst, ast.Call) and any(isinstance(a, ast.Constant) and a.value == "setpriv"
                                             for a in erst.args))
    texte = [ast.unparse(e) for e in liste.elts]
    check("x11vnc_befehl: wechselt die uid (--reuid)", any("--reuid=" in t for t in texte))
    check("x11vnc_befehl: ohne Gruppen, ohne Faehigkeiten, no_new_privs",
          {"--clear-groups", "--no-new-privs", "--inh-caps=-all"} <= set(werte))
    check("x11vnc_befehl: -localhost, kein -auth guess",
          "-localhost" in werte and "guess" not in werte)
    pos_x = next((i for i, e in enumerate(liste.elts) if _ist_x11vnc(e)), -1)
    pos_r = next((i for i, t in enumerate(texte) if "--reuid=" in t), 99)
    check("x11vnc_befehl: uid-Wechsel steht VOR dem Programm", 0 <= pos_r < pos_x)

for rel in ("start_jarvis_root.sh", "start_jarvis.sh"):
    code = ohne_sh_kommentare((ROOT / rel).read_text(encoding="utf-8"))
    direkt = [z.strip() for z in code.splitlines()
              if re.match(r"^\s*(\S*/)?x11vnc\s", z) or re.search(r"(^|[;&|]\s*)x11vnc\s+-", z.strip())]
    check("%s ruft x11vnc nicht selbst auf" % rel, not direkt, direkt[:3])
    check("%s startet ueber vnc-starten" % rel,
          "python3 -m backend.desktop_control vnc-starten" in code)

RUN = ohne_sh_kommentare((ROOT / "run.sh").read_text(encoding="utf-8"))
m = re.search(r'if \[ "\$\(id -u\)" = "0" \]; then\n(.*?)\n\s*else\n', RUN, re.S)
check("run.sh: als root nur ueber vnc-starten",
      bool(m) and "vnc-starten" in m.group(1) and not re.search(r"^\s*x11vnc\s", m.group(1), re.M))

# ── B ──
print("\n[B] x11vnc_starten() ausgefuehrt")
import backend.desktop_control as dc  # noqa: E402

SANDKASTEN = Path(tempfile.mkdtemp(prefix="h11_vnc_"))
QUELLE = SANDKASTEN / "lightdm-cookie"
QUELLE.write_bytes(b"COOKIE-INHALT")
os.chmod(QUELLE, 0o600)
LZ = SANDKASTEN / "run-jarvis-vnc"
PW = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_name=dc.VNC_BENUTZER)
AUFRUFE = []


def _run(cmd, **kw):
    AUFRUFE.append((list(cmd), kw))
    if cmd[:1] == ["pgrep"]:
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")
    return types.SimpleNamespace(returncode=0, stdout="PORT=5900\n", stderr="")


_echt = (dc.subprocess.run, dc.VNC_LAUFZEIT, dc.vnc_benutzer_sicherstellen)
if not str(LZ).startswith(tempfile.gettempdir()):
    abbruch("Sandkasten liegt nicht im Temp-Verzeichnis")
try:
    dc.subprocess.run = _run
    dc.VNC_LAUFZEIT = str(LZ)
    dc.vnc_benutzer_sicherstellen = lambda: PW
    dc.x11vnc_starten(":0", str(QUELLE))
    xs = [c for c, kw in AUFRUFE if any(str(t).endswith("x11vnc") for t in c) and "-rfbport" in c]
    if len(xs) != 1:
        abbruch("Positivkontrolle: genau ein x11vnc-Start erwartet, gesehen %d" % len(xs))
    cmd, kw = next((c, k) for c, k in AUFRUFE if c is xs[0] or c == xs[0])
    check("Befehl beginnt mit setpriv", os.path.basename(cmd[0]) == "setpriv", cmd[0])
    check("Befehl traegt die uid des VNC-Benutzers", "--reuid=%d" % PW.pw_uid in cmd)
    auth = cmd[cmd.index("-auth") + 1] if "-auth" in cmd else None
    check("-auth zeigt auf die KOPIE im Laufzeitverzeichnis",
          auth is not None and Path(auth).parent == LZ and auth != str(QUELLE), auth)
    if auth and Path(auth).exists():
        st = os.stat(auth)
        check("Kopie hat den Inhalt der Quelle", Path(auth).read_bytes() == b"COOKIE-INHALT")
        check("Kopie ist 0600", stat.S_IMODE(st.st_mode) == 0o600, oct(stat.S_IMODE(st.st_mode)))
        check("Kopie gehoert dem VNC-Benutzer", st.st_uid == PW.pw_uid)
    else:
        check("Kopie existiert", False, auth)
    check("Laufzeitverzeichnis ist 0700", LZ.is_dir() and stat.S_IMODE(os.stat(LZ).st_mode) == 0o700)
    env = kw.get("env") or {}
    check("eigene Umgebung (kein DISPLAY/XAUTHORITY von root geerbt)",
          kw.get("env") is not None and "XAUTHORITY" not in env and "DISPLAY" not in env)

    # ── C ──
    print("\n[C] fail-closed ohne Benutzer")
    AUFRUFE.clear()
    dc.vnc_benutzer_sicherstellen = lambda: None
    dc.x11vnc_starten(":0", str(QUELLE))
    gestartet = [c for c, _ in AUFRUFE if any(str(t).endswith("x11vnc") for t in c) and "-rfbport" in c]
    check("ohne Benutzer kein x11vnc-Start", not gestartet, gestartet)

    # ── D ──
    print("\n[D] liegengebliebenes Ziel wird ersetzt, nie verfolgt")
    dc.vnc_benutzer_sicherstellen = lambda: PW
    opfer = SANDKASTEN / "opfer"
    opfer.write_bytes(b"UNVERAENDERT")
    ziel = LZ / "xauth-0"
    LZ.mkdir(mode=0o700, exist_ok=True)   # fehlt es, ist schon B rot – D soll trotzdem messen
    ziel.unlink(missing_ok=True)
    ziel.symlink_to(opfer)
    AUFRUFE.clear()
    dc.x11vnc_starten(":0", str(QUELLE))
    check("Symlink-Ziel unveraendert", opfer.read_bytes() == b"UNVERAENDERT")
    check("Ziel ist danach eine echte Datei mit Cookie",
          not ziel.is_symlink() and ziel.read_bytes() == b"COOKIE-INHALT")
finally:
    dc.subprocess.run, dc.VNC_LAUFZEIT, dc.vnc_benutzer_sicherstellen = _echt

# ── E ──
print("\n[E] Aufraeumen erfasst den VNC-Benutzer")
IPCS = ("key shmid owner perms bytes nattch status\n"
        "0x0 201 %s 600 4096 0\n0x0 202 jarvis 600 4096 0\n" % dc.VNC_BENUTZER)
IPCS_P = "shmid owner cpid lpid\n201 %s 999981 1\n202 jarvis 999982 1\n" % dc.VNC_BENUTZER
weg = []


def _ipcs(cmd, **kw):
    if cmd == ["ipcs", "-m"]:
        return types.SimpleNamespace(returncode=0, stdout=IPCS, stderr="")
    if cmd == ["ipcs", "-m", "-p"]:
        return types.SimpleNamespace(returncode=0, stdout=IPCS_P, stderr="")
    if cmd[:2] == ["ipcrm", "-m"]:
        weg.append(cmd[2])
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


if os.path.exists("/proc/999981"):
    abbruch("Positivkontrolle: Test-PID 999981 lebt zufaellig")
try:
    dc.subprocess.run = _ipcs
    dc.shm_verwaiste_aufraeumen()
finally:
    dc.subprocess.run = _echt[0]
check("verwaistes Segment des VNC-Benutzers wird entfernt", "201" in weg)
check("fremder Eigentuemer bleibt", "202" not in weg)

# ── F ──
print("\n[F] Broker-Start stellt den Altbestand um, bevor er startet")
z = ohne_sh_kommentare((ROOT / "start_jarvis_root.sh").read_text(encoding="utf-8")).splitlines()


def _zeile(muster):
    return next((i for i, l in enumerate(z) if re.search(muster, l)), None)


i_unit = _zeile(r"systemctl disable --now x11vnc\.service")
i_root = _zeile(r"pgrep -u root -x x11vnc")
i_beenden = _zeile(r"backend\.desktop_control vnc-beenden")
i_start = _zeile(r'_vnc_start "\$DISPLAY"')
check("fremde root-Unit wird abgeschaltet", i_unit is not None)
check("root-Instanz wird erkannt und beendet", i_root is not None and i_beenden is not None)
check("…beides vor dem x11vnc-Start",
      None not in (i_unit, i_root, i_start) and i_unit < i_start and i_root < i_start)

import shutil  # noqa: E402
shutil.rmtree(SANDKASTEN, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
