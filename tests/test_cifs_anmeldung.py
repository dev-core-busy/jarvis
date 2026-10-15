#!/usr/bin/env python3
"""Waechter: kommt eine SMB-Anmeldung mit Domaenenkonto und beliebigem
Kennwort so bei mount.cifs an, dass der Server sie annimmt?

GEMELDET AM 2026-09-28 (ECHT): "//10.0.0.30/Operations/... laesst sich
nicht verbinden – unter Windows geht es, Anmeldedaten sind korrekt."
Gemessen: dieselben Daten meldeten sich mit smbclient an, der Kernel-Mount
scheiterte mit ``Send error in SessSetup = -13``. Auf DEV nachgestellt
(mount.cifs 7.4):

    username=firma/m.mustermann           -> -13
    username=firma\\m.mustermann          -> -13
    username=m.mustermann,domain=FIRMA    -> Mount steht
    username=m.mustermann@firma.local       -> Mount steht

mount.cifs zerlegt DOMAENE\\benutzer also NICHT. Dazu kam ein zweiter Fehler
derselben Stelle: das Kennwort stand als ``password=...`` in der
Optionsliste – ein Komma darin zerbricht sie.

Die Broker-Op wird WIRKLICH ausgefuehrt (``_run`` als Attrappe mit der
echten Signatur), gemessen wird, was als Argumentliste und Umgebung an
``mount`` ginge.
"""

import pathlib
import sys
from pathlib import Path

WURZEL = Path(__file__).parent.parent
sys.path.insert(0, str(WURZEL))
OK = FAIL = 0


def check(text, bedingung, detail=""):
    global OK, FAIL
    if not isinstance(text, str) or isinstance(bedingung, str):
        print(f"\033[31mABBRUCH: check(...) vertauscht: {text!r}\033[0m")
        sys.exit(2)
    if bedingung:
        OK += 1
        print(f"  \033[32m✓\033[0m {text}")
    else:
        FAIL += 1
        print(f"  \033[31m✗\033[0m {text}" + (f"  → {detail}" if detail else ""))


try:
    from backend.broker import ops
except Exception as e:  # noqa: BLE001
    print(f"\033[31mABBRUCH: backend.broker.ops nicht importierbar: {e}\033[0m")
    sys.exit(2)

AUFRUFE = []


def _run_attrappe(cmd, timeout=30, input_text=None, neutrale_sprache=False,
                  umgebung_zusatz=None):
    AUFRUFE.append({"cmd": list(cmd), "env": dict(umgebung_zusatz or {})})
    return {"ok": True, "rc": 0, "stdout": "", "stderr": ""}


def mounten(username, password):
    """(Optionsstring, Zusatz-Umgebung, ganze Argumentliste) eines Aufrufs."""
    AUFRUFE.clear()
    alt_run, alt_frei = ops._run, ops._mp_freimachen
    alt_mkdir = pathlib.Path.mkdir
    ops._run = _run_attrappe
    ops._mp_freimachen = lambda mp: ""
    pathlib.Path.mkdir = lambda self, *a, **k: None
    try:
        erg = ops._op_mount_share({
            "type": "smb", "source": "//server/freigabe/unter",
            "mountpoint": "/mnt/rag/share_test",
            "username": username, "password": password}, None)
    finally:
        ops._run, ops._mp_freimachen = alt_run, alt_frei
        pathlib.Path.mkdir = alt_mkdir
    mount = [a for a in AUFRUFE if a["cmd"][:1] == ["mount"]]
    if not mount:
        return None, None, None, erg
    cmd = mount[-1]["cmd"]
    opts = cmd[cmd.index("-o") + 1] if "-o" in cmd else ""
    return opts, mount[-1]["env"], cmd, erg


def optionen(opts):
    return dict((t.split("=", 1) + [""])[:2] for t in (opts or "").split(","))


# --- Positivkontrolle: die Attrappe greift, die Op erreicht mount ----------
opts, env, cmd, erg = mounten("benutzer", "geheim")
check("Positivkontrolle: die Op ruft mount -t cifs ueber _run auf",
      bool(cmd) and cmd[:3] == ["mount", "-t", "cifs"], str(erg))
if not cmd:
    print("\033[31mABBRUCH: kein mount-Aufruf gemessen\033[0m")
    sys.exit(2)
check("Positivkontrolle: Benutzer ohne Domaene kommt unveraendert an",
      optionen(opts).get("username") == "benutzer", opts)

# --- Fehler 1: DOMAENE\benutzer und DOMAENE/benutzer ------------------------
for eingabe in ("FIRMA\\m.mustermann", "FIRMA/m.mustermann",
                "firma/m.mustermann"):
    opts, env, cmd, erg = mounten(eingabe, "geheim")
    o = optionen(opts)
    check(f"⚠ {eingabe!r}: username= traegt NUR den Benutzer",
          o.get("username") == "m.mustermann", opts)
    check(f"⚠ {eingabe!r}: die Domaene steht in domain=",
          o.get("domain", "").upper() == "FIRMA", opts)

opts, env, cmd, erg = mounten("m.mustermann@firma.local", "geheim")
check("benutzer@domain.tld bleibt, wie es ist (der Server nimmt es so an)",
      optionen(opts).get("username") == "m.mustermann@firma.local"
      and "domain" not in optionen(opts), opts)

opts, env, cmd, erg = mounten("FIRMA\\", "geheim")
check("nur eine Domaene ohne Benutzer wird mit Meldung abgewiesen",
      cmd is None and "Benutzername" in str(erg.get("stderr")), str(erg))

# --- Fehler 2: Kennwort mit Komma -------------------------------------------
KW = "ab,c=d%e\\f"
opts, env, cmd, erg = mounten("FIRMA\\m.mustermann", KW)
check("⚠ das Kennwort steht NICHT in der Argumentliste (Komma, ps)",
      not any(KW in a or "password=ab" in a for a in cmd), " ".join(cmd))
check("⚠ … sondern unveraendert in PASSWD der Umgebung",
      env.get("PASSWD") == KW, str(env))
check("die Optionsliste bleibt zerlegbar (keine fremden Optionen)",
      set(optionen(opts)) <= {"ro", "username", "domain"}, opts)

# --- Gast und leeres Kennwort -----------------------------------------------
opts, env, cmd, erg = mounten("", "")
check("ohne Benutzer: Gastzugang, kein PASSWD",
      "guest" in optionen(opts) and not env.get("PASSWD"), f"{opts} {env}")
opts, env, cmd, erg = mounten("benutzer", "")
check("leeres Kennwort: kein leeres PASSWD (mount.cifs wuerde fragen)",
      "PASSWD" not in env and "password" in optionen(opts), f"{opts} {env}")

print(f"\n{OK} ok, {FAIL} fehlgeschlagen")
sys.exit(1 if FAIL else 0)
