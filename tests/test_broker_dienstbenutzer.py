#!/usr/bin/env python3
"""Waechter: ``broker_setup`` macht den Dienst nicht zu root (Pentest-Vorbereitung 2026-11-05).

Die Op ist ``default_allow`` (ohne Freigabe-Code). Bis zu diesem Fix nahm sie
``service_user`` ungeprueft an – mit ``root`` schrieb setup_broker.sh
``User=root`` in jarvis.service und gab den Projektbaum root: jeder Prozess mit
uid jarvis wurde root, ohne TOTP.

  [1] ``_dienstbenutzer_abgelehnt`` AUSGEFUEHRT (per AST geschnitten, Konten-
      datenbank als Attrappe): nur der Benutzer aus JARVIS_BROKER_GROUP, nie
      uid/gid 0, nie Mitglied einer root-Gruppe, unbekanntes Konto abgelehnt.
  [2] ``_op_broker_mode`` AUSGEFUEHRT: mit ``service_user=root`` (und anderen
      fremden Werten) wird KEIN Befehl gestartet; ohne Argument (der einzige
      echte Aufrufer, main.py) startet ``systemd-run`` wie bisher.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import ast
import os
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


QUELLE = (ROOT / "backend" / "broker" / "ops.py").read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)
FN = {n.name: n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
for n in ("_dienstbenutzer_abgelehnt", "_op_broker_mode", "_op_broker_setup"):
    if n not in FN:
        abbruch("%s fehlt in backend/broker/ops.py" % n)
GRUPPEN = None
for n in BAUM.body:
    if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_ROOT_GRUPPEN"
                                          for t in n.targets)):
        GRUPPEN = ast.literal_eval(n.value)
if not GRUPPEN:
    abbruch("_ROOT_GRUPPEN nicht gefunden")

# ── Attrappen der Kontodatenbank (echte Signaturen von pwd/grp/os.getgrouplist) ──
KONTEN = {  # name: (uid, gid, [Zusatzgruppen-gids])
    "root": (0, 0, []),
    "jarvis": (995, 995, [995, 44]),
    "admin1": (1001, 1001, [1001, 27]),   # 27 = sudo
    "gid0": (1002, 0, [0]),
}
GRP_NAMEN = {0: "root", 27: "sudo", 44: "video", 995: "jarvis", 1001: "admin1"}


def _getpwnam(name):
    if name not in KONTEN:
        raise KeyError("getpwnam(): name not found: %r" % name)
    uid, gid, _ = KONTEN[name]
    return types.SimpleNamespace(pw_name=name, pw_uid=uid, pw_gid=gid)


def _getgrgid(gid):
    return types.SimpleNamespace(gr_name=GRP_NAMEN.get(gid, str(gid)))


attr_pwd = types.ModuleType("pwd")
attr_pwd.getpwnam = _getpwnam
attr_grp = types.ModuleType("grp")
attr_grp.getgrgid = _getgrgid
attr_os = types.SimpleNamespace(environ={}, getgrouplist=lambda n, g: KONTEN[n][2])

AUFRUFE = []


class _Pfad:
    """Minimal-Path: CODE_ROOT / ... existiert, PROJECT_ROOT hat ein parent."""
    def __init__(self, p):
        self.p = p

    def __truediv__(self, x):
        return _Pfad(self.p + "/" + x)

    @property
    def parent(self):
        return _Pfad(self.p.rsplit("/", 1)[0] or "/")

    def exists(self):
        return True

    def __str__(self):
        return self.p


def _run(cmd, timeout=0, **kw):
    AUFRUFE.append(list(cmd))
    return {"ok": True, "rc": 0, "stdout": "", "stderr": ""}


ns = {"os": attr_os, "re": re, "_ROOT_GRUPPEN": GRUPPEN, "_run": _run,
      "PROJECT_ROOT": _Pfad("/opt/jarvis"), "CODE_ROOT": _Pfad("/usr/local/lib/jarvis-broker")}
mod = ast.Module(body=[FN["_dienstbenutzer_abgelehnt"], FN["_op_broker_mode"],
                       FN["_op_broker_setup"]], type_ignores=[])
sys_alt = {k: sys.modules.get(k) for k in ("pwd", "grp")}
sys.modules["pwd"], sys.modules["grp"] = attr_pwd, attr_grp
try:
    exec(compile(ast.fix_missing_locations(mod), "ops", "exec"), ns)
    ab = ns["_dienstbenutzer_abgelehnt"]
    setup = ns["_op_broker_setup"]

    print("\n[1] _dienstbenutzer_abgelehnt")
    check("(Positivkontrolle) jarvis ist zulaessig", ab("jarvis") == "", ab("jarvis"))
    check("root abgelehnt", ab("root") != "")
    check("anderer Benutzer abgelehnt", ab("admin1") != "")
    attr_os.environ["JARVIS_BROKER_GROUP"] = "root"
    check("auch wenn JARVIS_BROKER_GROUP=root: uid 0 abgelehnt", ab("root") != "", ab("root"))
    attr_os.environ["JARVIS_BROKER_GROUP"] = "admin1"
    check("Mitglied von sudo abgelehnt", "sudo" in ab("admin1"), ab("admin1"))
    attr_os.environ["JARVIS_BROKER_GROUP"] = "gid0"
    check("Primaergruppe 0 abgelehnt", ab("gid0") != "", ab("gid0"))
    attr_os.environ["JARVIS_BROKER_GROUP"] = "fehlt"
    check("unbekanntes Konto abgelehnt", ab("fehlt") != "", ab("fehlt"))
    attr_os.environ.clear()

    print("\n[2] _op_broker_mode")
    AUFRUFE.clear()
    r = setup({}, None)
    gestartet = [c for c in AUFRUFE if c and c[0] == "systemd-run"]
    check("(Positivkontrolle) ohne Argument startet systemd-run mit jarvis",
          r.get("ok") and len(gestartet) == 1 and gestartet[0][-1] == "jarvis", repr((r, AUFRUFE)))
    for wert in ("root", "admin1", "fehlt", "nobody"):
        AUFRUFE.clear()
        r = setup({"service_user": wert}, None)
        check("service_user=%s: abgelehnt, KEIN Befehl gestartet" % wert,
              not r.get("ok") and AUFRUFE == [], repr((r, AUFRUFE)))
finally:
    for k, v in sys_alt.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
