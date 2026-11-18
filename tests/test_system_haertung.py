#!/usr/bin/env python3
"""Waechter fuer deploy/security/system_haertung.sh (Haertung B1-B8).

Das Skript laeuft WIRKLICH – im Testmodus (JARVIS_HAERTUNG_TEST=1) gegen einen
Sandkasten (JARVIS_SYS_WURZEL). Geprueft werden Eigenschaften, keine
Textvorkommen:

 1. Exit-Codes: leer --pruefen = 1, --anwenden = 0, danach --pruefen = 0,
    unbekannter Modus = 2, Testmodus ohne Wurzel = 2.
 2. Idempotent: ein zweiter Lauf schreibt nichts (Inhalt UND mtime gleich).
 3. --pruefen aendert nichts – auch nicht an einer abweichenden Datei.
 4. Inhalte: Kernel-Werte, Limits (root eigens!), needrestart nur auflisten,
    Modulsperren, Audit-Regeln nur fuer Personen, AIDE-Ausnahmen (emuliert
    gegen konkrete Pfade), Drop-in, coredump, sudoers 0440 + visudo.
 5. Kein Eingriff in apt (Jarvis verwaltet Remove-Unused-Dependencies selbst).
 6. Eine ungueltige sudoers-Datei wird NICHT eingespielt (Exit 3).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
Das zu pruefende Skript kann ueber JARVIS_SYSTEM_HAERTUNG_SKRIPT umgelenkt
werden (Gegenprobe tests/gegen_system_haertung.py).
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WURZEL_REPO = Path(__file__).resolve().parent.parent
SKRIPT = Path(os.environ.get("JARVIS_SYSTEM_HAERTUNG_SKRIPT",
                             WURZEL_REPO / "deploy" / "security" / "system_haertung.sh"))
OK = FAIL = 0
NICHT_GEPRUEFT = []


def ok(t):
    global OK
    OK += 1
    print("  OK   " + t)


def fail(t):
    global FAIL
    FAIL += 1
    print("  FAIL " + t)


def pruefe(bed, t):
    ok(t) if bed else fail(t)


def lauf(modus, wurzel, skript=None, test=True):
    env = {k: v for k, v in os.environ.items()
           if k not in ("JARVIS_HAERTUNG_TEST", "JARVIS_SYS_WURZEL")}
    if test:
        env["JARVIS_HAERTUNG_TEST"] = "1"
        if wurzel is not None:
            env["JARVIS_SYS_WURZEL"] = str(wurzel)
    p = subprocess.run(["bash", str(skript or SKRIPT), modus], env=env,
                       capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


def zeilen(pfad):
    """Nicht-Kommentar-Zeilen einer Datei (leer, wenn sie fehlt)."""
    try:
        text = Path(pfad).read_text(encoding="utf-8")
    except OSError:
        return []
    return [z.strip() for z in text.splitlines()
            if z.strip() and not z.strip().startswith("#")]


def baum_stempel(wurzel):
    aus = {}
    for p in sorted(Path(wurzel).rglob("*")):
        if p.is_file():
            st = p.stat()
            aus[str(p)] = (hashlib.sha256(p.read_bytes()).hexdigest(), st.st_mtime_ns,
                           oct(st.st_mode & 0o7777))
    return aus


# ── 0. Positivkontrollen ─────────────────────────────────────────────────────
print("[0] Positivkontrollen")
if not SKRIPT.is_file():
    print("ABBRUCH: Skript fehlt: %s" % SKRIPT)
    sys.exit(2)
if subprocess.run(["bash", "-n", str(SKRIPT)]).returncode != 0:
    fail("bash -n: Syntaxfehler im Skript")
    print("ERGEBNIS: %d OK, %d FAIL" % (OK, FAIL))
    sys.exit(1)
ok("Syntax gueltig (bash -n)")

sandkasten = Path(tempfile.mkdtemp(prefix="sys_haertung_"))
try:
    W = sandkasten / "a"
    W.mkdir()

    # ── 1. Exit-Codes ────────────────────────────────────────────────────────
    print("[1] Exit-Codes")
    rc, out = lauf("--pruefen", W)
    pruefe(rc == 1, "leerer Sandkasten: --pruefen meldet Abweichung (Exit %d, erwartet 1)" % rc)
    pruefe(not any(W.rglob("*")), "--pruefen hat im leeren Sandkasten nichts angelegt")
    rc, out = lauf("--anwenden", W)
    if rc != 0 or not (W / "etc").is_dir():
        fail("--anwenden laeuft (Exit %d): %s" % (rc, out.strip()[-200:]))
    else:
        ok("--anwenden laeuft (Exit 0)")
    rc, _ = lauf("--pruefen", W)
    pruefe(rc == 0, "nach --anwenden meldet --pruefen 'alles umgesetzt' (Exit %d)" % rc)
    rc, _ = lauf("--unsinn", W)
    pruefe(rc == 2, "unbekannter Modus: Exit %d (erwartet 2)" % rc)
    leer = sandkasten / "ohne_wurzel_probe"
    rc, _ = lauf("--pruefen", None)
    pruefe(rc == 2, "Testmodus ohne JARVIS_SYS_WURZEL: Exit %d (erwartet 2 – nie das echte /)" % rc)

    # ── 2. Idempotenz ────────────────────────────────────────────────────────
    print("[2] Idempotenz")
    vorher = baum_stempel(W)
    time.sleep(0.05)
    rc, out = lauf("--anwenden", W)
    nachher = baum_stempel(W)
    pruefe(rc == 0 and "geschrieben" not in out,
           "zweiter Lauf schreibt nichts (Ausgabe ohne 'geschrieben')")
    pruefe(vorher == nachher, "zweiter Lauf: Inhalt, mtime und Modus aller Dateien gleich")
    pruefe(len(vorher) == 9, "genau 9 Dateien angelegt (gefunden %d)" % len(vorher))

    # ── 3. --pruefen aendert nichts ──────────────────────────────────────────
    print("[3] --pruefen ist rein lesend")
    sysctl = W / "etc/sysctl.d/90-haertung.conf"
    sysctl.write_text("kernel.sysrq = 1\n", encoding="utf-8")
    vorher = baum_stempel(W)
    rc, out = lauf("--pruefen", W)
    pruefe(rc == 1 and "WEICHT AB" in out, "abweichende Datei wird gemeldet (Exit %d)" % rc)
    pruefe(baum_stempel(W) == vorher, "--pruefen hat die abweichende Datei NICHT angefasst")
    lauf("--anwenden", W)
    pruefe("kernel.sysrq = 1" not in sysctl.read_text(encoding="utf-8"),
           "--anwenden stellt die Datei wieder her")

    # ── 4. Inhalte ───────────────────────────────────────────────────────────
    print("[4] Inhalte")
    # 4a Kernel-Werte
    werte = {}
    for z in zeilen(sysctl):
        k, _, v = z.partition("=")
        werte[k.strip()] = v.strip()
    soll = {
        "kernel.kptr_restrict": "2", "kernel.dmesg_restrict": "1",
        "kernel.unprivileged_bpf_disabled": "1", "kernel.yama.ptrace_scope": "2",
        "kernel.kexec_load_disabled": "1", "kernel.sysrq": "0",
        "kernel.randomize_va_space": "2", "kernel.perf_event_paranoid": "3",
        "net.core.bpf_jit_harden": "2", "dev.tty.ldisc_autoload": "0",
        "fs.suid_dumpable": "0", "fs.protected_hardlinks": "1",
        "fs.protected_symlinks": "1", "fs.protected_fifos": "2", "fs.protected_regular": "2",
        "net.ipv4.ip_forward": "0", "net.ipv4.conf.all.rp_filter": "1",
        "net.ipv4.conf.all.accept_redirects": "0", "net.ipv4.conf.all.send_redirects": "0",
        "net.ipv4.conf.all.accept_source_route": "0", "net.ipv4.conf.all.log_martians": "1",
        "net.ipv4.conf.default.log_martians": "1", "net.ipv4.tcp_syncookies": "1",
        "net.ipv6.conf.all.accept_redirects": "0",
    }
    falsch = {k: (werte.get(k), v) for k, v in soll.items() if werte.get(k) != v}
    pruefe(not falsch, "Kernel-Werte der Checkliste gesetzt%s" % (" – abweichend: %s" % falsch if falsch else ""))
    pruefe("kernel.modules_disabled" not in werte,
           "kernel.modules_disabled NICHT gesetzt (Checkliste 66, cifs laedt nach)")
    pruefe(not any("disable_ipv6" in k for k in werte), "keine IPv6-Abschaltung (eigene Massnahme D8)")

    # 4b Limits – '*' gilt bei pam_limits nicht fuer root
    lim = {tuple(z.split()[:4]) for z in zeilen(W / "etc/security/limits.d/90-nocore.conf")
           if len(z.split()) >= 4}
    for dom in ("*", "root"):
        for typ in ("soft", "hard"):
            pruefe((dom, typ, "core", "0") in lim, "limits: %s %s core 0" % (dom, typ))

    # 4c needrestart nur auflisten
    nr = zeilen(W / "etc/needrestart/conf.d/50-haertung.conf")
    pruefe(any(re.fullmatch(r"\$nrconf\{restart\}\s*=\s*'l';", z) for z in nr),
           "needrestart: $nrconf{restart} = 'l' (nur auflisten, nie selbst neu starten)")
    pruefe(not any(re.search(r"restart\}\s*=\s*'a'", z) for z in nr), "needrestart: kein automatischer Neustart")

    # 4d Modulsperren
    mp = set(zeilen(W / "etc/modprobe.d/haertung.conf"))
    fehlend = [m for m in ("cramfs", "freevxfs", "hfs", "hfsplus", "jffs2", "udf", "usb-storage",
                           "firewire-core", "bluetooth", "dccp", "sctp", "rds", "tipc")
               if "install %s /bin/false" % m not in mp]
    pruefe(not fehlend, "alle 13 Module gesperrt%s" % (" – fehlen: %s" % fehlend if fehlend else ""))

    # 4e Audit: root-cmd nur fuer Personen, Schluessel auch beim Lesen
    au = zeilen(W / "etc/audit/rules.d/50-haertung.rules")
    exe = [z for z in au if "execve" in z]
    pruefe(len(exe) >= 1, "Audit: mindestens eine execve-Regel (root-cmd)")
    pruefe(all("auid>=1000" in z and "auid!=unset" in z for z in exe),
           "Audit: jede execve-Regel nur fuer Personen (auid>=1000, auid!=unset)")
    pruefe(any(z.startswith("-w /etc/jarvis/geheimnis.key") and re.search(r"-p \S*r", z) for z in au),
           "Audit: Hauptschluessel wird auch beim LESEN protokolliert")
    for ziel in ("/etc/sudoers.d/", "/etc/ssh/sshd_config.d/", "/etc/systemd/system/", "/etc/jarvis/"):
        pruefe(any(z.startswith("-w " + ziel) for z in au), "Audit: Ueberwachung von %s" % ziel)

    # 4f AIDE – Ausschlussregeln gegen konkrete Pfade emuliert
    negativ = [z[1:] for z in zeilen(W / "etc/aide/aide.conf.d/95_jarvis_ausnahmen") if z.startswith("!")]

    def ausgenommen(pfad):
        return any(re.match(m, pfad) for m in negativ)
    # Positivkontrolle der Emulation selbst
    if not (re.match("/mnt", "/mnt/x") and not re.match("/mnt", "/opt/mnt")):
        print("ABBRUCH: AIDE-Emulation unbrauchbar")
        sys.exit(2)
    for p in ("/mnt/rag/share_0/x.pdf", "/opt/jarvis/data/x.json", "/opt/jarvis/.git/index",
              "/opt/jarvis/backend/__pycache__/m.pyc", "/home/jarvis/.gvfs/x",
              "/home/jarvis/.cache/doc/x", "/run/user/1001/gvfs/x", "/run/vmblock-fuse/dev",
              "/opt/sentinelone/mount/x", "/opt/sentinelone/ebpfs/bpf_mount/x",
              "/root/.cache/pip/x", "/var/lib/swcatalog/x"):
        pruefe(ausgenommen(p), "AIDE nimmt aus: %s" % p)
    for p in ("/opt/jarvis/backend/main.py", "/opt/jarvis/venv/lib/x.py", "/etc/jarvis/broker-policy.json",
              "/etc/jarvis/geheimnis.key", "/usr/bin/sudo", "/root/.ssh/authorized_keys",
              "/opt/sentinelone/bin/sentinelctl", "/etc/sudoers.d/10-haertung"):
        pruefe(not ausgenommen(p), "AIDE prueft weiter: %s" % p)

    # 4f' Wechselnde Dateien: die Broker-Zaehler ja, die Freigabeliste NIE
    selektiv = []
    for z in zeilen(W / "etc/aide/aide.conf.d/95_jarvis_ausnahmen"):
        if z.startswith("/"):
            teile = z.split()
            selektiv.append((teile[0], teile[-1]))

    def gruppe(pfad):
        treffer = [g for m, g in selektiv if re.match(m, pfad)]
        return treffer[-1] if treffer else None
    pruefe(gruppe("/var/lib/jarvis-broker/zaehler.json") == "VarFile",
           "AIDE fuehrt die Broker-Zaehler als wechselnde Datei (VarFile)")
    pruefe(ausgenommen("/var/lib/jarvis-broker/zaehler.tmp"), "AIDE nimmt die Zwischendatei der Zaehler aus")
    pruefe(gruppe("/etc/jarvis/broker-policy.json") is None and not ausgenommen("/etc/jarvis/broker-policy.json"),
           "AIDE lockert die Freigabeliste NICHT (keine Var*-Regel, keine Ausnahme)")

    # 4g Drop-in, 4h coredump
    di = zeilen(W / "etc/systemd/system/jarvis.service.d/70-coredump.conf")
    pruefe("[Service]" in di and "LimitCORE=0" in di, "Drop-in jarvis.service: [Service] LimitCORE=0")
    pruefe("Storage=none" in zeilen(W / "etc/systemd/coredump.conf.d/90-haertung.conf"), "coredump: Storage=none")

    # 4i sudoers
    sud = W / "etc/sudoers.d/10-haertung"
    pruefe(sud.is_file() and oct(sud.stat().st_mode & 0o777) == "0o440", "sudoers: Datei mit Modus 0440")
    pruefe('Defaults logfile="/var/log/sudo.log"' in zeilen(sud), "sudoers: Protokoll nach /var/log/sudo.log")
    visudo = shutil.which("visudo") or ("/usr/sbin/visudo" if os.path.exists("/usr/sbin/visudo") else None)
    if visudo:
        r = subprocess.run([visudo, "-cf", str(sud)], capture_output=True, text=True)
        pruefe(r.returncode == 0, "sudoers: visudo -cf akzeptiert die Datei")
    else:
        NICHT_GEPRUEFT.append("visudo -cf (visudo fehlt)")

    # ── 5. Kein Eingriff in apt ──────────────────────────────────────────────
    print("[5] apt bleibt unberuehrt")
    apt = [str(p) for p in W.rglob("*") if "/apt/" in str(p) or str(p).endswith("/apt")]
    pruefe(not apt, "keine Datei unter etc/apt (Jarvis verwaltet Remove-Unused-Dependencies)%s"
           % (" – gefunden: %s" % apt if apt else ""))

    # ── 6. Ungueltige sudoers-Datei wird NICHT eingespielt ───────────────────
    print("[6] sudoers-Schranke")
    if not visudo:
        NICHT_GEPRUEFT.append("sudoers-Schranke (visudo fehlt)")
    else:
        text = SKRIPT.read_text(encoding="utf-8")
        anker = "Defaults passwd_tries=3"
        if text.count(anker) != 1:
            fail("sudoers-Schranke: Anker '%s' nicht genau einmal im Skript" % anker)
        else:
            kaputt = sandkasten / "kaputt.sh"
            kaputt.write_text(text.replace(anker, anker + "\n@@@ ungueltig @@@"), encoding="utf-8")
            W2 = sandkasten / "b"
            W2.mkdir()
            rc, out = lauf("--anwenden", W2, skript=kaputt)
            pruefe(rc == 3, "ungueltige sudoers: Abbruch mit Exit 3 (war %d)" % rc)
            pruefe(not (W2 / "etc/sudoers.d/10-haertung").exists(),
                   "ungueltige sudoers: Datei wurde NICHT eingespielt")
            reste = [p.name for p in (W2 / "etc/sudoers.d").glob(".haertung.*")] \
                if (W2 / "etc/sudoers.d").is_dir() else []
            pruefe(not reste, "ungueltige sudoers: keine Zwischendatei liegen geblieben")
finally:
    shutil.rmtree(sandkasten, ignore_errors=True)

if NICHT_GEPRUEFT:
    print("NICHT GEPRUEFT: " + "; ".join(NICHT_GEPRUEFT))
print("ERGEBNIS: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
