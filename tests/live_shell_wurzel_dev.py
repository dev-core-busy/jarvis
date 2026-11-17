#!/usr/bin/env python3
"""LIVE auf DEV: Pentest "Hardening" F-13/F-16/F-19 ueber den ECHTEN Broker-Weg.

Ein Domain-Benutzer fuehrt Shell-Befehle aus (ShellTool -> Root-Broker ->
runuser -> setpriv -> bwrap). Gemessen wird, was der Lauf vom Server sieht –
und dass alles, was er fuer seine Arbeit braucht, weiter funktioniert.

Positivkontrollen VOR den Sperr-Pruefungen: der Befehl laeuft ueberhaupt, der
Broker bestaetigt die Isolation, und die gesuchten Ziele existieren auf dem Host
– sonst waere "im Lauf nicht vorhanden" trivial wahr.

Aufruf auf DEV (kein Geheimnis noetig, aber Dienstkontext fuer den Broker):
  bash /opt/jarvis/deploy/als_dienst.sh /opt/jarvis/venv/bin/python tests/live_shell_wurzel_dev.py
"""
import asyncio
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
from backend import lauf_tmp as lt                      # noqa: E402
from backend.tools.shell import ShellTool               # noqa: E402

BEN = "livetest.wurzel"
SBX = "jarvis_sandbox"
NOINET = "jarvis_sandbox_noinet"
PROJ = Path("/opt/jarvis")
ok = fail = 0


def check(bez, bed, detail=""):
    global ok, fail
    if bed:
        ok += 1
        print(f"OK   {bez}")
    else:
        fail += 1
        print(f"FAIL {bez}" + (f" – {detail}" if detail else ""))


def sh(cmd, user=SBX):
    return asyncio.run(ShellTool().execute(
        command=cmd, timeout=90, _sandbox_user=user,
        _broker_user=BEN, _broker_context="[live] Shell-Wurzel F-13"))


ZIELE = {
    "Quellcode": PROJ / "backend" / "agent.py",
    "Versionsverlauf .git": PROJ / ".git" / "HEAD",
    "Broker-Konfiguration": Path("/etc/jarvis/broker.conf"),
    "Systemprotokoll": Path("/var/log/dpkg.log"),
}

with lt.lauf_scope(BEN, privilegiert=False) as lauf:
    if lauf is None:
        print("ABBRUCH (Exit 2): kein isolierter Lauf moeglich")
        sys.exit(2)
    print(f"Arbeitsverzeichnis: {lauf.verzeichnis}")
    aus = sh("echo LAEUFT")
    if "LAEUFT" not in aus:
        print(f"ABBRUCH (Exit 2): Shell laeuft nicht: {aus[:300]}")
        sys.exit(2)
    check("Broker bestaetigt die Isolation", lt.ausfuehrung_unwirksam() is False)

    # ── Sperren (F-13/F-16) ────────────────────────────────────────────────
    for name, ziel in ZIELE.items():
        if not ziel.exists():
            print(f"  (uebersprungen: {ziel} existiert auf dem Host nicht)")
            continue
        for user in (SBX, NOINET):
            aus = sh(f"test -e {ziel} && echo SICHTBAR || echo WEG", user=user)
            check(f"{name} im Lauf NICHT VORHANDEN ({user})",
                  "WEG" in aus and "SICHTBAR" not in aus, aus.strip()[-160:])

    # ── F-19: die Kette "kopieren, dann ausliefern" ───────────────────────
    ziel = ZIELE["Quellcode"]
    sh(f"cp {ziel} /tmp/kopie_agent.py 2>/dev/null; true")
    check("Serverdatei laesst sich nicht ins Arbeitsverzeichnis kopieren (F-19)",
          not (Path(lauf.verzeichnis) / "kopie_agent.py").exists())

    # ── Was weiter funktionieren muss ──────────────────────────────────────
    aus = sh("echo x 2>/dev/null >/dev/null && echo DEVNULL-OK")
    check("2>/dev/null funktioniert", "DEVNULL-OK" in aus, aus[-200:])
    aus = sh("""python3 - <<'EOF'
import pandas as pd, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
pd.DataFrame({"a": [1, 2]}).to_excel("/tmp/wurzel.xlsx")
plt.plot([1, 2]); plt.savefig("/tmp/wurzel.png")
print("PY-OK")
EOF""", user=NOINET)
    check("pandas + matplotlib + openpyxl laufen", "PY-OK" in aus, aus[-300:])
    check("Ergebnis kommt auf dem Host an",
          (Path(lauf.verzeichnis) / "wurzel.xlsx").is_file()
          and (Path(lauf.verzeichnis) / "wurzel.png").is_file())
    aus = sh("convert /tmp/wurzel.png /tmp/wurzel.jpg && pdftoppm -v >/dev/null 2>&1; "
             "test -s /tmp/wurzel.jpg && echo BILD-OK", user=NOINET)
    check("ImageMagick laeuft", "BILD-OK" in aus, aus[-200:])
    aus = sh("getent hosts github.com >/dev/null && echo DNS-OK")
    check("Namensaufloesung (Internet-Benutzer)", "DNS-OK" in aus, aus[-200:])
    rag = PROJ / "data" / "rag"
    if rag.is_dir() and any(rag.iterdir()):
        aus = sh(f"ls {rag} | head -1 >/dev/null && test -d {rag} && echo WISSEN-OK")
        check("Wissensordner data/rag ist lesbar", "WISSEN-OK" in aus, aus[-200:])
        aus = sh(f"touch {rag}/schreibprobe 2>/dev/null && echo GESCHRIEBEN || echo ZU")
        check("… aber nicht beschreibbar", "ZU" in aus and not (rag / "schreibprobe").exists(),
              aus[-200:])

    # ── F-18: interne Ablage der Wissensverwaltung ──────────────────────────
    from backend import sandbox as sb                   # noqa: PLC0415
    pend = PROJ / "data" / "knowledge" / "pending"
    grp = PROJ / "data" / "knowledge" / ".groups.json"
    vs = PROJ / "data" / "vector_store"
    if pend.is_dir() and any(pend.iterdir()):
        aus = sh(f"ls -A {pend} 2>&1 | wc -l")
        check("Entwurfs-Ordner ist im Lauf leer (Host hat Entwuerfe)",
              aus.strip().splitlines()[-1:] == ["0"], aus.strip()[-160:])
        _bsp = next(pend.iterdir())
        erl, grund = sb.authorize_fs("read", str(_bsp), username=BEN)
        check("Dateiwerkzeug: Entwurf gesperrt, weich und mit Grund",
              not erl and "Wissensverwaltung" in grund and not sb.fs_target_sensitive(str(_bsp)),
              f"{erl} {grund!r}")
    if grp.is_file():
        aus = sh(f"cat {grp} >/dev/null 2>&1 && echo GELESEN || echo ZU")
        check("Gruppenkonfiguration in der Shell nicht lesbar", "ZU" in aus, aus.strip()[-120:])
        erl, grund = sb.authorize_fs("read", str(grp), username=BEN)
        check("Dateiwerkzeug: Gruppenkonfiguration gesperrt", not erl, grund)
    if vs.is_dir():
        aus = sh(f"test -e {vs} && echo SICHTBAR || echo WEG")
        check("Suchindex im Lauf NICHT VORHANDEN", "WEG" in aus, aus.strip()[-120:])
    for p_, m_ in ((pend, 0o750), (vs, 0o750), (grp, 0o640)):
        if p_.exists():
            check(f"OS-Recht {p_.name}: {oct(m_)}", (p_.stat().st_mode & 0o777) == m_,
                  oct(p_.stat().st_mode & 0o777))

    # Aufraeumen: nur das eigene Material dieses Laufs
    for n in ("wurzel.xlsx", "wurzel.png", "wurzel.jpg"):
        try:
            (Path(lauf.verzeichnis) / n).unlink()
        except OSError:
            pass

# ── Der Dienst selbst liest die gesperrten Ablagen weiter (AI-Maus, Add-ins,
#    /wissen gehen ueber seine API) ─────────────────────────────────────────
import json as _json                                    # noqa: E402
import ssl as _ssl                                      # noqa: E402
import urllib.request as _ur                            # noqa: E402
from backend import main as M                           # noqa: E402

_ctx = _ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = _ssl.CERT_NONE      # lokaler Aufruf auf 127.0.0.1, Zertifikat lautet auf den Namen
_tok = M.generate_token("jarvis")


def _api(pfad):
    r = _ur.Request("https://127.0.0.1" + pfad, headers={"Authorization": f"Bearer {_tok}"})
    with _ur.urlopen(r, context=_ctx, timeout=120) as a:
        return a.status, _json.loads(a.read().decode() or "null")


st, d = _api("/api/knowledge/stats")
check("Dienst: Suchindex-Status 200 mit Eintraegen",
      st == 200 and any(isinstance(v, int) and v > 0 for v in (d or {}).values()), str(d)[:200])
st, d = _api("/api/knowledge/pending")
_n = len(d) if isinstance(d, list) else len((d or {}).get("items") or (d or {}).get("pending") or [])
check("Dienst: Entwurfsliste fuer Admins weiter lesbar", st == 200 and _n > 0, f"{st} n={_n}")
st, d = _api("/api/knowledge/groups")
check("Dienst: Wissensgruppen weiter lesbar", st == 200 and bool(d), str(d)[:120])

# F-02 / F-15: die Dateien sind fuer den Sandbox-Benutzer zu, der Dienst liest
# sie weiter (Systemprompt-Bausteine fuer jeden Lauf, CVE-Seite fuer Admins).
with lt.lauf_scope(BEN, privilegiert=False):
    for pfad_, name_ in ((PROJ / "data" / "instructions" / "soul.md", "Anweisungsdatei"),
                         (PROJ / "data" / "cve" / "ergebnis.json", "CVE-Ergebnis")):
        if pfad_.is_file():
            aus = sh(f"cat {pfad_} >/dev/null 2>&1 && echo GELESEN || echo ZU")
            check(f"{name_} in der Shell nicht lesbar", "ZU" in aus, aus.strip()[-120:])
for d_ in ("instructions", "cve"):
    p_ = PROJ / "data" / d_
    if p_.is_dir():
        check(f"OS-Recht data/{d_}: 0o750", (p_.stat().st_mode & 0o777) == 0o750,
              oct(p_.stat().st_mode & 0o777))
st, d = _api("/api/instructions")
check("Dienst: Anweisungen weiter lesbar (Admin-API)", st == 200 and bool(d), str(d)[:120])
st, d = _api("/api/system/cve")
check("Dienst: Schwachstellen-Seite weiter lesbar (Admin-API)", st == 200 and isinstance(d, dict),
      str(d)[:120])

print(f"\n{ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
