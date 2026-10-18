#!/usr/bin/env python3
"""Waechter fuer die Befunde K1 und K2 (BSI-Abgleich, ECHT, 2026-09-29).

K1: Der Root-Broker lud Code aus /opt/jarvis, das dem Dienstbenutzer gehoert.
K2: ``broker.policy_decide`` war fuer jeden Prozess der Gruppe ``jarvis`` ohne
    Nachweis erlaubt; dazu automatisch erlaubte Ops mit Root-Wirkung
    (chpasswd fuer jedes Konto, broker_teardown, Mounts mit SUID).

Gemessen wird die WIRKUNG: die echten Funktionen laufen gegen Policy-,
Audit- und Schluesseldateien in einem Wegwerf-Verzeichnis. Nur dort, wo es
um Shell-Skripte geht (Abschnitt 8), wird der Text geprueft – bash hat hier
keinen Syntaxbaum, und die Live-Probe auf DEV deckt die Wirkung ab.
"""
import os
import re
import stat
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(bez, bedingung):
    """check(Beschreibung, Bedingung) – vertauschte Reihenfolge bricht mit Exit 2 ab."""
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
    """Pruefung, die werfen KANN – ein Wurf zaehlt als FAIL, nicht als Abbruch."""
    try:
        check(bez, fn())
    except Exception as e:  # noqa: BLE001
        check(f"{bez} [warf {type(e).__name__}: {e}]", False)


# ── Sandkasten: ALLE Broker-Dateien umbiegen, BEVOR ein Modul geladen wird ────
SK = Path(tempfile.mkdtemp(prefix="jarvis_k1k2_"))
os.environ["JARVIS_BROKER_POLICY"] = str(SK / "policy.json")
os.environ["JARVIS_BROKER_AUDIT"] = str(SK / "audit.jsonl")
os.environ["JARVIS_BROKER_FREIGABE_KEY"] = str(SK / "freigabe.key")
os.environ["JARVIS_BROKER_FREIGABE_STATE"] = str(SK / "freigabe.state")
DATENBAUM = SK / "projektbaum"
DATENBAUM.mkdir()
os.environ["JARVIS_PROJECT_ROOT"] = str(DATENBAUM)

if "backend.config" in sys.modules:
    print("ABBRUCH: backend.config ist bereits geladen.")
    sys.exit(2)
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(get_setting=lambda k, d=None: d)
sys.modules["backend.config"] = _cfg

from backend.broker import CODE_ROOT, PROJECT_ROOT, freigabe, meta, ops, policy  # noqa: E402
from backend.broker import daemon  # noqa: E402

for name, pfad in (("policy", policy.POLICY_FILE), ("audit", policy.AUDIT_FILE),
                   ("freigabe", freigabe.SCHLUESSEL), ("zustand", freigabe.ZUSTAND)):
    if SK not in Path(pfad).parents:
        print(f"ABBRUCH: {name} zeigt aus dem Sandkasten heraus: {pfad}")
        sys.exit(2)
if PROJECT_ROOT != DATENBAUM or CODE_ROOT != ROOT:
    print(f"ABBRUCH: Wurzeln nicht wie erwartet (Code {CODE_ROOT}, Daten {PROJECT_ROOT})")
    sys.exit(2)


def audit_zeilen():
    try:
        return policy.AUDIT_FILE.read_text().splitlines()
    except FileNotFoundError:
        return []


# ══ 1. Freigabe-Code: RFC 6238 und Wiederholschutz ═══════════════════════════
# Testvektor RFC 6238, Anhang B: Schluessel "12345678901234567890", T=59 s,
# SHA-1 → 94287082 (8 Stellen) – 6 Stellen sind die letzten sechs.
import base64  # noqa: E402
RFC_KEY = b"12345678901234567890"
check("RFC-6238-Testvektor (T=59)", freigabe._code(RFC_KEY, 59 // 30) == "287082")
check("RFC-6238-Testvektor (T=1111111109)", freigabe._code(RFC_KEY, 1111111109 // 30) == "081804")

check("ohne Schluessel: nicht eingerichtet", freigabe.pruefen("123456") == (False, "nicht_eingerichtet"))
b32, uri = freigabe.einrichten()
check("Schluesseldatei 0600", stat.S_IMODE(freigabe.SCHLUESSEL.stat().st_mode) == 0o600)
check("otpauth-URI traegt den Schluessel", b32 in uri and uri.startswith("otpauth://totp/"))
KEY = base64.b32decode(b32 + "=" * (-len(b32) % 8))
jetzt = time.time()
code = freigabe._code(KEY, int(jetzt // 30))
check("gueltiger Code wird angenommen", freigabe.pruefen(code, jetzt) == (True, "ok"))
check("derselbe Code ein zweites Mal: verbraucht",
      freigabe.pruefen(code, jetzt) == (False, "nachweis_verbraucht"))
check("falscher Code abgewiesen",
      freigabe.pruefen("000000" if code != "000000" else "111111", jetzt + 30)[0] is False)
check("leerer Code: nachweis_fehlt", freigabe.pruefen("", jetzt) == (False, "nachweis_fehlt"))
freigabe.SCHLUESSEL.chmod(0o644)
check("Schluessel mit 0644: gilt als nicht eingerichtet (fail-closed)",
      freigabe.pruefen(freigabe._code(KEY, int(jetzt // 30) + 1), jetzt + 30)[1] == "nicht_eingerichtet")
freigabe.SCHLUESSEL.chmod(0o600)

# ── 1b. Durchprobieren und Wiederholschutz unter Last (Code-Review 2026-10-07) ──
# Ohne Grenze waere der Code per Schleife ueber den Socket ratbar; ohne Sperre
# um Pruefen+Merken gingen zwei gleichzeitige Anfragen mit demselben Code durch.
import threading  # noqa: E402
freigabe.einrichten()          # frischer Zustand (fehl=0)
b32b = freigabe.SCHLUESSEL.read_text().strip()
KEY = base64.b32decode(b32b + "=" * (-len(b32b) % 8))
t0 = time.time()
richtig = freigabe._code(KEY, int(t0 // 30))
falsch = next(c for c in ("000000", "111111", "222222") if c not in
              {freigabe._code(KEY, int(t0 // 30) + d) for d in (-1, 0, 1)})
erg = [freigabe.pruefen(falsch, t0) for _ in range(freigabe.FEHL_MAX)]
check("Positivkontrolle: die ersten Fehlversuche heissen 'nachweis_falsch'",
      all(e == (False, "nachweis_falsch") for e in erg))
check(f"nach {freigabe.FEHL_MAX} Fehlversuchen: RICHTIGER Code wird abgewiesen (gesperrt)",
      freigabe.pruefen(richtig, t0) == (False, "gesperrt"))
check("Sperre steht im Zustand (ueberlebt Neustart)",
      freigabe._zustand()["gesperrt_bis"] > t0)
check("Sperre hat einen Klartext", "gesperrt" in freigabe.MELDUNG.get("gesperrt", ""))
t1 = t0 + freigabe.SPERRE_S + 31
check("nach Ablauf der Sperre gilt ein richtiger Code wieder",
      freigabe.pruefen(freigabe._code(KEY, int(t1 // 30)), t1) == (True, "ok"))
check("… und der Fehlzaehler steht wieder auf 0", freigabe._zustand()["fehl"] == 0)
t2 = t1 + 60
for _ in range(freigabe.FEHL_MAX - 1):
    freigabe.pruefen(falsch, t2)
check(f"{freigabe.FEHL_MAX - 1} Fehlversuche sperren noch NICHT",
      freigabe.pruefen(freigabe._code(KEY, int(t2 // 30)), t2) == (True, "ok"))

t3 = t2 + 120
gleich = freigabe._code(KEY, int(t3 // 30))
ergebnisse, start = [], threading.Barrier(12)
_echt_schreiben = freigabe._schreibe_privat


def _langsam(p, inhalt):          # Wettlauf-Fenster weit oeffnen
    time.sleep(0.02)
    _echt_schreiben(p, inhalt)


freigabe._schreibe_privat = _langsam
try:
    def _lauf():
        start.wait()
        ergebnisse.append(freigabe.pruefen(gleich, t3))
    fs = [threading.Thread(target=_lauf) for _ in range(12)]
    [f.start() for f in fs]
    [f.join() for f in fs]
finally:
    freigabe._schreibe_privat = _echt_schreiben
check("12 gleichzeitige Anfragen mit demselben Code: GENAU EINE gilt",
      sum(1 for e in ergebnisse if e[0]) == 1 and len(ergebnisse) == 12)
# Der Abschnitt rechnet mit Zeiten in der ZUKUNFT – der verbrauchte Schritt
# liegt danach dort. Frischer Schluessel, damit Abschnitt 2 mit Echtzeit misst.
freigabe.einrichten()
b32b = freigabe.SCHLUESSEL.read_text().strip()
KEY = base64.b32decode(b32b + "=" * (-len(b32b) % 8))

# ══ 2. Meta-Ops: allow/remove nur mit Code, deny/pending ohne ═════════════════
policy.check("shell_root:id", "shell_root", "Root-Shell-Befehl: id", "anna", False)
vorher = {e["key"]: e["decision"] for e in policy.list_ops()}
if vorher.get("shell_root:id") != "pending":
    print("ABBRUCH: Positivkontrolle – Eintrag entstand nicht als pending.")
    sys.exit(2)

r = meta.behandeln("broker.policy_decide", {"key": "shell_root:id", "decision": "allow", "by": "admin"},
                   peer="uid=1001(jarvis)")
check("allow OHNE Code abgewiesen", r is not None and r.get("ok") is False and r.get("grund") == "nachweis_fehlt")
check("... und der Eintrag bleibt pending",
      {e["key"]: e["decision"] for e in policy.list_ops()}.get("shell_root:id") == "pending")
check("... und der Versuch steht im Audit (mit Kernel-Aufrufer)",
      any('"abgewiesen"' in z and "uid=1001(jarvis)" in z for z in audit_zeilen()))

r = meta.behandeln("broker.policy_decide", {"key": "shell_root:id", "decision": "allow",
                                            "by": "admin", "nachweis": "999999"})
check("allow mit FALSCHEM Code abgewiesen", r.get("ok") is False and r.get("grund") == "nachweis_falsch")

r = meta.behandeln("broker.policy_decide", {"key": "shell_root:id", "decision": "deny", "by": "admin"})
check("deny braucht keinen Code", r.get("ok") is True and r["entry"]["decision"] == "deny")

r = meta.behandeln("broker.policy_remove", {"key": "shell_root:id", "by": "admin"})
check("remove OHNE Code abgewiesen", r.get("ok") is False and r.get("grund") == "nachweis_fehlt")
check("... Eintrag noch da", "shell_root:id" in {e["key"] for e in policy.list_ops()})

code2 = freigabe._code(KEY, int(time.time() // 30) + 1)
r = meta.behandeln("broker.policy_decide", {"key": "shell_root:id", "decision": "allow",
                                            "by": "admin", "nachweis": code2})
check("allow MIT gueltigem Code angenommen", r.get("ok") is True and r["entry"]["decision"] == "allow")
r = meta.behandeln("broker.policy_decide", {"key": "shell_root:id", "decision": "allow",
                                            "by": "admin", "nachweis": code2})
check("derselbe Code fuer eine ZWEITE Entscheidung abgewiesen", r.get("ok") is False)

sicher("ping meldet Herkunft des Codes und Code-Einrichtung",
       lambda: (lambda p: "stand" in p and p.get("freigabe_code") is True)(meta.behandeln("broker.ping", {})))

# ══ 3. Automatik verloren → Bestand zurueckgesetzt ═══════════════════════════
check("broker_teardown ist nicht mehr automatisch erlaubt", "broker_teardown" in ops.OHNE_AUTOMATIK)
check("shell_root bleibt freigabepflichtig", "shell_root" in ops.OHNE_AUTOMATIK)
check("Positivkontrolle: systemctl bleibt automatisch", "systemctl" not in ops.OHNE_AUTOMATIK)
# Bestand wie vor dem Umbau: broker_teardown als auto/allow registriert
data = policy._load()
data["ops"]["broker_teardown"] = {"key": "broker_teardown", "op": "broker_teardown",
                                  "decision": "allow", "auto": True, "decided_by": "auto"}
data["ops"]["broker_teardown_bewusst"] = {"key": "broker_teardown_bewusst", "op": "broker_teardown",
                                          "decision": "allow", "auto": False, "decided_by": "admin"}
policy._save(data)
geaendert = policy.herabstufen(ops.OHNE_AUTOMATIK)
nachher = {e["key"]: e["decision"] for e in policy.list_ops()}
check("auto-Eintrag broker_teardown → pending", nachher.get("broker_teardown") == "pending")
check("bewusste Admin-Freigabe bleibt stehen", nachher.get("broker_teardown_bewusst") == "allow")
check("herabstufen meldet genau den einen Eintrag", geaendert == ["broker_teardown"])
r = ops.dispatch("broker_teardown", {}, user="agent")
check("broker_teardown laeuft danach nicht ohne Freigabe", r.get("decision") == "pending")

# ══ 4. chpasswd: nur jarvis, und nur wenn es nicht root werden kann ══════════
aufrufe = []
dc = types.ModuleType("backend.desktop_control")
dc.change_linux_password = lambda u, p: aufrufe.append(u) or True
sys.modules["backend.desktop_control"] = dc
import backend  # noqa: E402
backend.desktop_control = dc

r = ops._op_chpasswd({"username": "root", "password": "Geheim123"}, None)
check("chpasswd fuer root abgewiesen", r.get("ok") is False and "root" not in aufrufe)
r = ops._op_chpasswd({"username": "srvadmin", "password": "Geheim123"}, None)
check("chpasswd fuer ein fremdes Konto abgewiesen", r.get("ok") is False and "srvadmin" not in aufrufe)
# Das eigentliche Kriterium der Whitelist: ein Konto, das EXISTIERT und NICHT
# root werden kann, aber nicht das Anmeldekonto ist. root/srvadmin fielen schon
# an der Root-Pruefung durch – die Gegenprobe "Whitelist entfernt" blieb damit
# gruen (2026-09-29), obwohl die Zusage fehlte.
if ops._kann_root_werden("nobody") != "":
    print("ABBRUCH: Positivkontrolle – 'nobody' gilt hier als root-faehig, taugt nicht als Probe.")
    sys.exit(2)
r = ops._op_chpasswd({"username": "nobody", "password": "Geheim123"}, None)
check("chpasswd fuer ein existierendes, unprivilegiertes Fremdkonto abgewiesen",
      r.get("ok") is False and "nobody" not in aufrufe)
_echt = ops._kann_root_werden
ops._kann_root_werden = lambda u: "Mitglied von sudo"
r = ops._op_chpasswd({"username": "jarvis", "password": "Geheim123"}, None)
check("chpasswd fuer jarvis abgewiesen, wenn jarvis root werden kann",
      r.get("ok") is False and "jarvis" not in aufrufe and "sudo" in r.get("stderr", ""))
ops._kann_root_werden = lambda u: ""
r = ops._op_chpasswd({"username": "jarvis", "password": "Geheim123"}, None)
check("Positivkontrolle: chpasswd fuer unprivilegiertes jarvis laeuft", r.get("ok") is True and aufrufe == ["jarvis"])
# Code-Review 2026-10-18: das KENNWORT ging ungeprueft an chpasswd, das
# zeilenweise liest – "x\nroot:neu" haette root ein Kennwort gesetzt.
for bez, pw in (("Zeilenumbruch", "Geheim123\nroot:Uebernommen1"), ("Wagenruecklauf", "Geheim\r123"),
                ("NUL", "Geheim\x00123"), ("DEL", "Geheim\x7f123"), ("leer", ""),
                ("zu lang", "A" * 257), ("kein Text", ["Geheim123"])):
    aufrufe.clear()
    r = ops._op_chpasswd({"username": "jarvis", "password": pw}, None)
    check(f"chpasswd-Kennwort mit {bez} abgewiesen, chpasswd nie gerufen",
          r.get("ok") is False and aufrufe == [])
aufrufe.clear()
r = ops._op_chpasswd({"username": "jarvis", "password": "Ge:heim 123!" + "ä" * 3}, None)
check("Positivkontrolle: Doppelpunkt, Leerzeichen, Umlaut sind erlaubt", r.get("ok") is True and aufrufe == ["jarvis"])
ops._kann_root_werden = _echt
check("root ist root-faehig (echte Pruefung)", ops._kann_root_werden("root") != "")

# Zweite Schranke im ausfuehrenden Modul (echtes desktop_control, chpasswd als Attrappe)
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("dc_echt", ROOT / "backend" / "desktop_control.py")
dc_echt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc_echt)
_eingaben = []
dc_echt.subprocess = types.SimpleNamespace(
    run=lambda cmd, **kw: _eingaben.append((cmd, kw.get("input"))) or types.SimpleNamespace(returncode=0))
check("desktop_control: Kennwort mit Zeilenumbruch -> False, chpasswd nie gerufen",
      dc_echt.change_linux_password("jarvis", "a\nroot:b") is False and _eingaben == [])
check("desktop_control: Name mit Zeilenumbruch -> False",
      dc_echt.change_linux_password("jarvis\nroot", "Geheim123") is False and _eingaben == [])
check("Positivkontrolle desktop_control: gueltige Eingabe erreicht chpasswd mit genau einer Zeile",
      dc_echt.change_linux_password("jarvis", "Geheim123") is True
      and _eingaben == [(["chpasswd"], "jarvis:Geheim123\n")])

# ══ 4b. unlock_screen: Ziel nur aus _DESKTOP_USERS (Code-Review 2026-10-18) ══
_entsperrt = []
dc.unlock_desktop_screen = lambda u: _entsperrt.append(u)
for ziel in ("root", "jarvis\nautologin-session=x", "s.fischer", "lightdm"):
    _entsperrt.clear()
    r = ops._op_unlock_screen({"target_user": ziel}, None)
    check(f"unlock_screen mit Ziel {ziel!r} abgewiesen", r.get("ok") is False and _entsperrt == [])
_entsperrt.clear()
r = ops._op_unlock_screen({}, None)
check("Positivkontrolle: unlock_screen ohne Ziel entsperrt jarvis", r.get("ok") is True and _entsperrt == ["jarvis"])
_geschrieben = []
dc_echt.subprocess = types.SimpleNamespace(run=lambda *a, **k: _geschrieben.append(a) or
                                           types.SimpleNamespace(returncode=0, stdout="", stderr=""))
dc_echt.unlock_desktop_screen("jarvis\n[Seat:*]\nautologin-user=root")
check("desktop_control.unlock_desktop_screen weist ein Ziel mit Zeilenumbruch ab (kein Unterprozess)",
      _geschrieben == [])
check("unbekanntes Konto gilt als nicht setzbar", ops._kann_root_werden("gibt_es_nicht_k1k2") != "")

# ══ 5. Verbindungen: nur root und der Dienstbenutzer ═════════════════════════
import pwd  # noqa: E402
ich = pwd.getpwuid(os.getuid()).pw_name
daemon.SERVICE_USER = ich
check("unbekannter Aufrufer abgewiesen", daemon._zugelassen(None) is False)
check("root zugelassen", daemon._zugelassen(0) is True)
check("Dienstbenutzer zugelassen", daemon._zugelassen(os.getuid()) is True)
check("fremde uid abgewiesen", daemon._zugelassen(os.getuid() + 12345) is False)

# ══ 6. Mounts ohne SUID/Geraete/Ausfuehrung ══════════════════════════════════
for flag in ("nosuid", "nodev", "noexec", "ro"):
    check(f"MOUNT_OPTS enthaelt {flag}", flag in ops.MOUNT_OPTS.split(","))
check("CIFS mit Anmeldung nutzt MOUNT_OPTS",
      ops._cifs_anmeldung("FIRMA\\anna", "x")[0].startswith(ops.MOUNT_OPTS + ","))
check("CIFS als Gast nutzt MOUNT_OPTS", ops._cifs_anmeldung("", "")[0].startswith(ops.MOUNT_OPTS))
befehle = []
_run, _frei, _kern = ops._run, ops._mp_freimachen, ops._kernel_grund
ops._run = lambda cmd, **k: befehle.append(cmd) or {"ok": True, "rc": 0, "stdout": "", "stderr": ""}
ops._mp_freimachen = lambda mp: ""
import pathlib  # noqa: E402
_mkdir = pathlib.Path.mkdir
pathlib.Path.mkdir = lambda self, *a, **k: None
try:
    ops._op_mount_share({"type": "nfs", "source": "server:/export", "mountpoint": "/mnt/rag/share_997"}, None)
finally:
    pathlib.Path.mkdir = _mkdir
    ops._run, ops._mp_freimachen = _run, _frei
nfs = [c for c in befehle if "nfs" in c]
check("NFS-Mount mit nosuid,nodev,noexec", bool(nfs) and ops.MOUNT_OPTS in nfs[0])

# ══ 6c. shell_root-Freigabe gilt fuer GENAU einen Befehl (Code-Review 2026-10-18) ══
_reg = ops._REGISTRY["shell_root"]
_key = _reg[1]
_basis = "export MPLBACKEND=Agg; " + "x" * 200
check("Positivkontrolle: derselbe Befehl -> derselbe Schluessel",
      _key({"command": _basis + " ; echo a"}) == _key({"command": _basis + " ; echo a"}))
check("gleiche ersten 200 Zeichen, anderer Rest -> ANDERER Schluessel",
      _key({"command": _basis + " ; echo a"}) != _key({"command": _basis + " ; rm -rf /"}))
check("Unterschied nur im Leerraum -> ANDERER Schluessel",
      _key({"command": "echo 'a  b'"}) != _key({"command": "echo 'a b'"}))
_desc = _reg[2]({"command": _basis + "y" * 400 + " ; rm -rf /tmp/x"})   # laenger als die Anzeigegrenze
check("Anzeige nennt die Kuerzung VORN und beziffert sie",
      "Zeichen" in _desc.split(":")[0] and len(_desc) <= 500)

# ══ 6b. Einhaengepunkt: feste Form, kein Symlink (Code-Review 2026-10-18) ════
check("Positivkontrolle: /mnt/rag/share_1 ist zulaessig", ops._mountpunkt_fehler("/mnt/rag/share_1") == "")
check("Altbasis /mnt/jarvis-kb/share_3 ist zulaessig", ops._mountpunkt_fehler("/mnt/jarvis-kb/share_3") == "")
for mp in ("/mnt/rag/share_1/unter", "/mnt/etc", "/mnt/rag/../../etc", "/mnt/rag/share_1\n",
           "/etc/rag/share_1", "/mnt/rag/share_x", "", "/mnt/rag/share_12345"):
    check(f"Einhaengepunkt {mp!r} abgewiesen", ops._mountpunkt_fehler(mp) != "")
import stat as _st  # noqa: E402
_lstat = ops.os.lstat
_echt_lstat = os.lstat


def _lstat_attrappe(p):
    if p == "/mnt/rag":
        return os.stat_result((_st.S_IFLNK | 0o777, 0, 0, 1, 0, 0, 0, 0, 0, 0))
    if p in ("/mnt",):
        return os.stat_result((_st.S_IFDIR | 0o755, 0, 0, 1, 0, 0, 0, 0, 0, 0))
    raise FileNotFoundError(p)


ops.os.lstat = _lstat_attrappe
try:
    _f = ops._mountpunkt_fehler("/mnt/rag/share_1")
finally:
    ops.os.lstat = _echt_lstat
check("Symlink in einer Pfadkomponente (/mnt/rag -> …) abgewiesen", "symbolischer Link" in _f)
befehle.clear()
ops._run = lambda cmd, **k: befehle.append(cmd) or {"ok": True, "rc": 0, "stdout": "", "stderr": ""}
try:
    r = ops._op_umount_share({"mountpoint": "/mnt/fremd"}, None)
    r2 = ops._op_mount_share({"type": "nfs", "source": "server:/export", "mountpoint": "/mnt/x/../../etc"}, None)
finally:
    ops._run = _run
check("umount_share mit fremdem Pfad: abgewiesen, kein umount", r.get("ok") is False and befehle == [])
check("mount_share mit fremdem Pfad: abgewiesen, kein mount", r2.get("ok") is False and befehle == [])

# ══ 7. Skripte kommen aus dem Broker-Code, Ziele aus dem Datenbaum ═══════════
gesehen = []
_ss = ops._stream_shell
ops._stream_shell = lambda cmd, cwd, t, s: gesehen.append((cmd, cwd)) or {"ok": True, "rc": 0, "stdout": "", "stderr": ""}
try:
    ops._op_tika_setup({}, None)
finally:
    ops._stream_shell = _ss
sicher("tika_setup startet das Skript aus CODE_ROOT",
       lambda: str(CODE_ROOT / "deploy" / "tika_setup.sh") in gesehen[0][0])
sicher("tika_setup uebergibt den Datenbaum als JARVIS_DIR",
       lambda: f"JARVIS_DIR={DATENBAUM}" in gesehen[0][0])
sicher("tika_setup nennt keinen Pfad im Datenbaum als auszufuehrendes Skript",
       lambda: str(DATENBAUM / "deploy") not in gesehen[0][0])

# ══ 8. Startskript und Installer: aus dem Projektbaum wird als root nichts gestartet
start = (ROOT / "start_jarvis_root.sh").read_text(encoding="utf-8")
code_zeilen = [z for z in start.splitlines() if z.strip() and not z.lstrip().startswith("#")]
check("kein venv-Python im Root-Start", not any("venv/bin/python" in z for z in code_zeilen))
check("kein Skript aus $JARVIS_DIR/deploy als root",
      not any(re.search(r'\$JARVIS_DIR/deploy/(sandbox_python|tika_setup)', z) for z in code_zeilen))
aimouse = [z for z in code_zeilen if "AIMOUSE_BUILD" in z and "bash" in z]
check("AI-Mouse-Bauskript nur als Dienstbenutzer",
      bool(aimouse) and all("runuser -u jarvis" in z for z in aimouse))
schluss = [z for z in code_zeilen if z.strip().startswith("exec ") and "broker.daemon" in z]
check("Broker mit System-Python gestartet", bool(schluss) and schluss[-1].strip().startswith("exec /usr/bin/python3"))
idx_cd = max((i for i, z in enumerate(code_zeilen) if z.strip() == 'cd "$CODE_DIR"'), default=-1)
idx_exec = max((i for i, z in enumerate(code_zeilen) if "broker.daemon" in z), default=-1)
check("... und aus dem Code-Verzeichnis (sys.path[0])", 0 <= idx_cd < idx_exec)

inst = (ROOT / "deploy" / "security" / "broker_installieren.sh").read_text(encoding="utf-8")
git_zeilen = [z for z in inst.splitlines() if re.search(r'\bgit\s', z) and not z.lstrip().startswith("#")
              and "meldung" not in z and "fehler" not in z]
check("Positivkontrolle: der Installer ruft git auf", len(git_zeilen) >= 3)
check("git nur im root-eigenen Cache, nie im Arbeitsbaum",
      all('"$CACHE"' in z or "clone" in z for z in git_zeilen))
check("Konfiguration wird nicht per source geladen", not re.search(r'^\s*(source|\.)\s+"?\$KONF', inst, re.M))
unit = (ROOT / "deploy" / "security" / "jarvis-broker.service").read_text(encoding="utf-8")
check("Unit startet aus der root-eigenen Kopie",
      "ExecStart=/usr/local/lib/jarvis-broker/start_jarvis_root.sh" in unit)
teardown = (ROOT / "deploy" / "security" / "teardown_broker.sh").read_text(encoding="utf-8")
check("Rueckbau nimmt die Unit nicht aus $JARVIS_DIR",
      'cp "$JARVIS_DIR/jarvis.service"' not in teardown and 'cp "$CODE_DIR/jarvis.service"' in teardown)

import shutil  # noqa: E402
shutil.rmtree(SK, ignore_errors=True)
print(f"\n{_ok} OK, {_fail} FAIL")
if _ok == 0:
    sys.exit(2)
sys.exit(1 if _fail else 0)
