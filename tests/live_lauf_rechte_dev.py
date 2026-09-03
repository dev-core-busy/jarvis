#!/usr/bin/env python3
"""LIVE auf DEV: der gemeldete Ablauf vom 2026-09-03, ueber den ECHTEN Broker-Weg.

Zwei Identitaeten schreiben in dasselbe Arbeitsverzeichnis – Shell als
`jarvis_sandbox`, Werkzeuge als Dienstbenutzer. Gemessen werden Eigentuemer,
Gruppe und Modus der ECHTEN Dateien, nicht nachgebaute.
"""
import asyncio
import os
import pwd
import grp
import re
import stat
import sys

sys.path.insert(0, "/opt/jarvis")
from backend import lauf_tmp as lt                      # noqa: E402
from backend.tools.shell import ShellTool               # noqa: E402
from backend.tools.filesystem import FileSystemTool     # noqa: E402
from backend import sandbox as sb                       # noqa: E402

BEN = "livetest.rechte"
SBX = "jarvis_sandbox"
NOINET = "jarvis_sandbox_noinet"
ok = fail = 0


def check(bez, bed):
    global ok, fail
    if bed:
        ok += 1
        print(f"OK   {bez}")
    else:
        fail += 1
        print(f"FAIL {bez}")


def sh(cmd, user=SBX):
    return asyncio.run(ShellTool().execute(
        command=cmd, timeout=60, _sandbox_user=user,
        _broker_user=BEN, _broker_context="[live] Rechte-Messung"))


def fs(action, pfad, inhalt=""):
    # genau wie der Dispatch: Modell-Pfad -> Host-Pfad
    return asyncio.run(FileSystemTool().execute(action, lt.aufloesen(pfad), inhalt))


def info(p):
    st = os.stat(p)
    return (pwd.getpwuid(st.st_uid).pw_name, grp.getgrgid(st.st_gid).gr_name,
            oct(st.st_mode & 0o7777))


print(f"Dienstbenutzer: {pwd.getpwuid(os.getuid()).pw_name}")
with lt.lauf_scope(BEN, privilegiert=False) as lauf:
    print(f"Arbeitsverzeichnis: {lauf.verzeichnis}")

    # ── 1) Shell schreibt, wie im gemeldeten Lauf ────────────────────────────
    aus = sh("echo \"print('firewall')\" > /tmp/firewall_chart.py; id -un; stat -c '%U %G %a' /tmp/firewall_chart.py")
    print("   Shell:", " | ".join(aus.strip().splitlines()[-3:]))
    check("Isolation war aktiv (Broker hat sie bestaetigt)",
          not lt.ausfuehrung_unwirksam())
    hostdatei = lauf.verzeichnis / "firewall_chart.py"
    check("Datei liegt im Arbeitsverzeichnis des Benutzers", hostdatei.is_file())
    if hostdatei.is_file():
        u, g, m = info(hostdatei)
        print(f"   Host: {u}:{g} {m}")
        check(f"Eigentuemer ist der Sandbox-Benutzer ({u})", u == SBX)
        check(f"Gruppe ist die DIENSTgruppe – setgid wirkt ({g})",
              g == pwd.getpwuid(os.getuid()).pw_name)
        check(f"gruppen-beschreibbar – umask 002 wirkt ({m})",
              bool(os.stat(hostdatei).st_mode & stat.S_IWGRP))
    vu, vg, vm = info(lauf.verzeichnis)
    print(f"   Verzeichnis: {vu}:{vg} {vm}")
    check("Arbeitsverzeichnis traegt setgid",
          bool(os.stat(lauf.verzeichnis).st_mode & stat.S_ISGID))

    # ── 2) DER GEMELDETE FALL: Backend ueberschreibt die Shell-Datei ─────────
    erg = fs("write", "/tmp/firewall_chart.py", "print('vom backend')")
    print("   filesystem write ->", erg.strip()[:90])
    check("filesystem write auf die Shell-Datei GELINGT (vorher PermissionError)",
          erg.startswith("✅"))
    check("Inhalt wirklich ersetzt",
          hostdatei.read_text(encoding="utf-8") == "print('vom backend')")

    # ── 3) Gegenrichtung: Shell haengt an eine Backend-Datei an ──────────────
    erg = fs("write", "/tmp/vom_backend.csv", "kopf\n")
    check("Backend legt eine Datei im Lauf an", erg.startswith("✅"))
    u, g, m = info(lauf.verzeichnis / "vom_backend.csv")
    print(f"   Backend-Datei: {u}:{g} {m}")
    aus = sh("echo 'zeile' >> /tmp/vom_backend.csv && echo ANGEHAENGT; cat /tmp/vom_backend.csv")
    check("Shell darf die Backend-Datei erweitern", "ANGEHAENGT" in aus)
    check("Inhalt beider Seiten steht drin",
          (lauf.verzeichnis / "vom_backend.csv").read_text(encoding="utf-8") == "kopf\nzeile\n")

    # ── 4) ALTBESTAND: 0644-Datei der Shell (wie vor dem Fix) ────────────────
    sh("umask 022; echo alt > /tmp/altbestand.py; stat -c '%a' /tmp/altbestand.py")
    alt_p = lauf.verzeichnis / "altbestand.py"
    check("Altbestand-Datei ist NICHT gruppen-beschreibbar (0644)",
          alt_p.is_file() and not (os.stat(alt_p).st_mode & stat.S_IWGRP))
    erg = fs("write", "/tmp/altbestand.py", "neu")
    check("EACCES-Netz greift beim Altbestand (unlink + neu)",
          erg.startswith("✅") and alt_p.read_text(encoding="utf-8") == "neu")

    # ── 5) Unterverzeichnis des Laufs erbt setgid (Aufraeumen bleibt moeglich)
    sh("mkdir -p /tmp/zwischen && touch /tmp/zwischen/a.txt")
    unter = lauf.verzeichnis / "zwischen"
    if unter.is_dir():
        u, g, m = info(unter)
        print(f"   Unterverzeichnis: {u}:{g} {m}")
        check("Unterverzeichnis erbt setgid", bool(os.stat(unter).st_mode & stat.S_ISGID))
        check("Unterverzeichnis traegt die Dienstgruppe",
              g == pwd.getpwuid(os.getuid()).pw_name)
        check("Dienst kann darin aufraeumen (rmtree wuerde gelingen)",
              os.access(unter, os.W_OK | os.X_OK))
    else:
        check("Unterverzeichnis angelegt", False)

    # ── 6) Fremdes Arbeitsverzeichnis bleibt zu (auch SCHREIBEND) ───────────
    fremd = lt.ARBEIT_ROOT / lt.benutzer_kennung("jemand.anders")
    erlaubt, grund = sb.authorize_fs("write", str(fremd / "ergebnis.xlsx"), BEN)
    check(f"write in ein fremdes Arbeitsverzeichnis abgewiesen ({grund})", not erlaubt)
    erlaubt, _ = sb.authorize_fs("write", str(lauf.verzeichnis / "x.txt"), BEN)
    check("write ins eigene bleibt erlaubt", erlaubt)

    # ── 7) Der eigentliche Nutzen: das Firewall-Diagramm laeuft jetzt ───────
    A = open("/opt/jarvis/backend/agent.py", encoding="utf-8").read()
    ns = {"re": re}
    for von, bis in (("_CMD_SPLIT = re.compile", "def _forbidden_command_hit"),
                     ("_LOOPBACK =", "# ── Instructions aus")):
        exec(compile(A[A.index(von):A.index(bis)], "agent-schnitt", "exec"), ns)
    treffer = ns["_shell_internet_hit"]
    FW = """python3 - <<'EOF'
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ports = [("22","SSH"), ("80","HTTP"), ("443","HTTPS"), ("6080","noVNC")]
fig, ax = plt.subplots(figsize=(6,3))
ax.bar([p[1] for p in ports], [int(p[0]) for p in ports])
ax.set_title("Offene Ports")
plt.savefig('/tmp/firewall_diagramm.png', dpi=80)
print("PNG geschrieben")
EOF"""
    check("Firewall-Diagramm passiert die Egress-Heuristik", not treffer(FW))
    check("curl auf eine externe URL bleibt gesperrt (Positivkontrolle)",
          treffer("curl -s https://example.com") == "curl")
    aus = sh(FW, user=NOINET)
    png = lt.ARBEIT_ROOT / lt.benutzer_kennung(BEN) / "firewall_diagramm.png"
    check("Diagramm laeuft im netzgesperrten Sandbox-Benutzer wirklich durch",
          "PNG geschrieben" in aus)
    check("PNG ist auf dem Host angekommen",
          png.is_file() and png.stat().st_size > 1000)
    if png.is_file():
        print(f"   PNG: {png.stat().st_size} Bytes, {info(png)}")

print(f"\n{ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
