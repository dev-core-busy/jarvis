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
 7. B14: Inhalte (jarvis-web OHNE faillock, gleiche faillock-Werte in beiden
    Profilen, root ausgenommen, minlen = main.KENNWORT_MIN_LAENGE) und die
    Aktivierung ueber eine pam-auth-update-ATTRAPPE: einmal, danach nicht
    mehr (idempotent), Abweichung im PAM-Stapel wird gemeldet und repariert,
    und bei altem Jarvis-Code (Dienst "login") bleibt faillock AUS.

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


# Attrappe fuer pam-auth-update (B14): schreibt die Zeilen, die das echte
# Werkzeug aus den Profilen erzeugt, in den Sandkasten und protokolliert jeden
# Aufruf NEBEN der Wurzel (<wurzel>.pam.log) - im Baum selbst zaehlte das
# Protokoll als Datei des Skripts.
PAM_ATTRAPPE = r"""#!/bin/bash
log="${JARVIS_SYS_WURZEL}.pam.log"
echo "$*" >> "$log"
d="$JARVIS_SYS_WURZEL/etc/pam.d"; mkdir -p "$d"
printf 'auth\trequisite\tpam_faillock.so preauth deny=5\nauth\t[success=2 default=ignore]\tpam_unix.so nullok\nauth\t[default=die]\tpam_faillock.so authfail deny=5\nauth\trequisite\tpam_deny.so\nauth\trequired\tpam_permit.so\n' > "$d/common-auth"
printf 'account\trequired\tpam_faillock.so\naccount\t[success=1 default=ignore]\tpam_unix.so\n' > "$d/common-account"
printf 'password\trequisite\tpam_pwquality.so retry=3\npassword\t[success=1 default=ignore]\tpam_unix.so obscure use_authtok\n' > "$d/common-password"
"""


def pam_aufrufe(wurzel):
    try:
        return [z for z in Path(str(wurzel) + ".pam.log").read_text().splitlines() if z.strip()]
    except OSError:
        return []


def lauf(modus, wurzel, skript=None, test=True, attrappe=True):
    env = {k: v for k, v in os.environ.items()
           if k not in ("JARVIS_HAERTUNG_TEST", "JARVIS_SYS_WURZEL")}
    env.pop("JARVIS_VISUDO", None)
    env.pop("JARVIS_PAM_AUTH_UPDATE", None)
    if test and attrappe:
        env["JARVIS_PAM_AUTH_UPDATE"] = str(PAM_ATTRAPPE_PFAD)
    if test:
        env["JARVIS_HAERTUNG_TEST"] = "1"
        if wurzel is not None:
            env["JARVIS_SYS_WURZEL"] = str(wurzel)
        # Das in [0] als tauglich GEMESSENE visudo, nicht irgendeines aus dem PATH.
        # Ist keines tauglich, bekommt das Skript einen Namen, den "command -v"
        # nicht aufloest: es ueberspringt die Schranke dann auf dem Weg, der fuer
        # "visudo fehlt" schon vorgesehen ist - sonst fiele es mit dem
        # untauglichen Werkzeug auf Exit 3 und JEDE folgende Pruefung waere ein
        # Folgefehler (CI-Lauf 2026-11-19).
        env["JARVIS_VISUDO"] = globals().get("VISUDO") or "visudo-keines-tauglich-siehe-waechter"
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

# Die sudoers-Schranke des Skripts prueft mit visudo. Ein visudo, das die
# KORREKTE Vorlage ablehnt, ist fuer diese Messung untauglich - eine falsche
# Sonde. Am 2026-11-19 wechselte "ubuntu-latest" auf Ubuntu 26.04, dessen visudo
# "Defaults logfile=" nicht kennt ("unknown setting: 'logfile'"); auf dem
# Zielsystem (Debian 13, visudo 1.9.16p2) ist dieselbe Datei "Analyse OK" (auf
# DEV gemessen). Der Waechter meldete daraufhin vier FAILs und stuerzte danach
# ab - ueber das SKRIPT sagte davon kein einziger etwas.
# Die Vorlage wird aus dem Skript GELESEN, nicht hier wiederholt: eine Kopie
# wuerde beim ersten Satz, der dort dazukommt, still an der Wirklichkeit
# vorbeimessen.
_vorlage = re.search(r"(?ms)^SUDOERS='(.*?)'$", SKRIPT.read_text(encoding="utf-8"))
if not _vorlage:
    print("ABBRUCH: SUDOERS-Vorlage in %s nicht gefunden" % SKRIPT.name)
    sys.exit(2)
_probe = Path(tempfile.mkdtemp(prefix="sys_haertung_visudo_"))
VISUDO = None
_abgelehnt = []
try:
    _pf = _probe / "sudoers_probe"
    _pf.write_text(_vorlage.group(1) + "\n", encoding="utf-8")
    _pf.chmod(0o440)
    # Breit suchen und nach dem WIRKLICHEN Pfad entdoppeln: liegen klassisches
    # sudo und sudo-rs nebeneinander, heisst nur eines von beiden "visudo" - das
    # taugliche kann "visudo.sudo", "visudo-classic" o.ae. heissen. Welches es
    # ist, entscheidet die Probe unten, nicht eine Vermutung ueber Paketnamen.
    _kandidaten, _gesehen = [], set()
    for _k in [shutil.which("visudo")] + sorted(
            str(q) for d in ("/usr/sbin", "/usr/bin", "/sbin", "/bin")
            for q in Path(d).glob("visudo*") if Path(d).is_dir()):
        if not _k or not os.access(_k, os.X_OK):
            continue
        _echt = os.path.realpath(_k)
        if _echt in _gesehen:
            continue
        _gesehen.add(_echt)
        _kandidaten.append(_k)
    for _kand in _kandidaten:
        _p = subprocess.run([_kand, "-cf", str(_pf)], capture_output=True, text=True,
                            env=dict(os.environ, LC_ALL="C"))
        if _p.returncode == 0:
            VISUDO = _kand
            break
        _fassung = subprocess.run([_kand, "-V"], capture_output=True, text=True)
        _abgelehnt.append("%s (%s): %s" % (_kand, (_fassung.stdout.splitlines() or [""])[0].strip(),
                                           (_p.stdout + _p.stderr).strip()[:200]))
finally:
    shutil.rmtree(_probe, ignore_errors=True)
if VISUDO is None:
    # Kein FAIL und kein Exit 2: der Waechter laeuft, nur ZWEI seiner Pruefungen
    # koennen auf diesem Rechner nichts ueber das Skript sagen. Dieselbe
    # Entscheidung wie beim schon vorgesehenen Fall "visudo fehlt" - sie steht
    # namentlich unter NICHT GEPRUEFT, statt als Befund ueber das Skript
    # aufzutreten (am 2026-11-19 waren es vier FAILs und ein Absturz).
    print("  HINWEIS kein visudo auf diesem Rechner beurteilt die sudoers-Vorlage des "
          "Zielsystems:")
    for _z in _abgelehnt or ["(kein visudo gefunden)"]:
        print("          abgelehnt von " + _z)
    NICHT_GEPRUEFT.append("visudo -cf und sudoers-Schranke (vorhandenes visudo beurteilt "
                          "die Zielsyntax nicht: %s)" % "; ".join(_abgelehnt) or "visudo fehlt")
else:
    ok("Positivkontrolle: %s beurteilt die sudoers-Vorlage des Zielsystems" % VISUDO)

# JARVIS_VISUDO darf das Pruefwerkzeug NUR im Testmodus bestimmen - sonst
# entschiede die Umgebung, womit eine Datei geprueft wird, die sudo fuer alle
# sperren kann. Das ist hier am TEXT gemessen, nicht an der Wirkung: ein Lauf
# ohne Testmodus verlangt root und das echte "/", also gerade das, was dieser
# Waechter niemals anfassen darf. Die Grenze ist damit benannt und nicht
# verschwiegen; die Gegenprobe (gegen_system_haertung.py) entfernt die
# TEST-Bedingung und erwartet hier einen Befund.
_sk = SKRIPT.read_text(encoding="utf-8")
# Nur die Zeile UNMITTELBAR vor der Zuweisung ([^\n]*, kein DOTALL): mit einem
# Muster ueber mehrere Zeilen traf "-n \"$TEST\"" auch eine frueher stehende
# Bedingung, und die Probe der Gegenprobe blieb stumm (2026-11-20 gemessen).
_zuweisung = re.search(r'(?m)^(?P<bed>if [^\n]*)\n\s*VISUDO="\$JARVIS_VISUDO"', _sk)
pruefe(bool(_zuweisung) and '-n "$TEST"' in _zuweisung.group("bed"),
       "JARVIS_VISUDO wird nur im Testmodus gelesen (Produktivlauf nimmt das visudo des Systems)")

_pam_zuweisung = re.search(r'(?m)^(?P<bed>if [^\n]*)\n\s*PAM_AUTH_UPDATE="\$JARVIS_PAM_AUTH_UPDATE"', _sk)
pruefe(bool(_pam_zuweisung) and '-n "$TEST"' in _pam_zuweisung.group("bed"),
       "JARVIS_PAM_AUTH_UPDATE wird nur im Testmodus gelesen (Produktivlauf nimmt pam-auth-update des Systems)")

sandkasten = Path(tempfile.mkdtemp(prefix="sys_haertung_"))
PAM_ATTRAPPE_PFAD = sandkasten / "pam-auth-update-attrappe"
PAM_ATTRAPPE_PFAD.write_text(PAM_ATTRAPPE, encoding="utf-8")
PAM_ATTRAPPE_PFAD.chmod(0o755)
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
        fail("--anwenden laeuft (Exit %d): %s" % (rc, out.strip()[-400:]))
        # Alles danach setzt den geschriebenen Baum voraus. Ohne ihn sind die
        # folgenden Pruefungen Folgefehler, und [3] starb am fehlenden
        # Verzeichnis (FileNotFoundError, CI-Lauf 2026-11-19) - ein Absturz
        # verdeckt die eine Zeile, die den Grund traegt.
        print("ABBRUCH der weiteren Pruefungen: ohne gelaufenes --anwenden "
              "waeren sie Folgefehler des Abbruchs oben")
        print("ERGEBNIS: %d OK, %d FAIL" % (OK, FAIL))
        sys.exit(1)
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
    # Formel statt Konstante (hier stand "11" - mit B13 kamen zwei Units dazu):
    # je Zeile der ZIELE-Liste eine Datei, dazu auditd.conf und die drei
    # common-*-Dateien, die pam-auth-update (hier die Attrappe) schreibt (B14).
    _ziele = re.search(r'^ZIELE="\n(.*?)^"', SKRIPT.read_text(encoding="utf-8"), re.S | re.M)
    _n_ziele = len([z for z in (_ziele.group(1) if _ziele else "").splitlines() if z.strip()])
    pruefe(_n_ziele >= 12, "ZIELE-Liste des Skripts gelesen (%d Eintraege)" % _n_ziele)
    _n_soll = _n_ziele + 1 + 3
    pruefe(len(vorher) == _n_soll,
           "genau %d Dateien angelegt – %d Ziele + auditd.conf + 3 PAM-Dateien (gefunden %d)"
           % (_n_soll, _n_ziele, len(vorher)))

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

    # 4f'' Wachsende Logs und fluechtige Laufzeitverzeichnisse
    for p_, g_ in (("/var/log/audit/audit.log", "Log"), ("/var/log/sudo.log", "Log"),
                   ("/var/log/aide/aideinit.log", "Log"), ("/var/log/aide/aideinit.errors", "Log"),
                   ("/var/log/audit/audit.log.3", "LowLog+ANF+ARF"), ("/var/log/sudo.log.2.gz", "LowLog+ANF+ARF"),
                   ("/var/log/sudo.log.1", "LowLog+ANF+ARF"), ("/opt/sentinelone/log/network.1.log", "LowLog+ANF+ARF"),
                   ("/opt/sentinelone/log/agent.log", "LowLog+ANF+ARF")):
        pruefe(gruppe(p_) == g_, "AIDE-Gruppe %s fuer %s (ist %s)" % (g_, p_, gruppe(p_)))
    for p_ in ("/tmp/jarvis-arbeit/0c8b14b2/x", "/tmp/jarvis-anhaenge/0c8b14b2/x",
               "/run/credentials/jarvis.service/geheimnis", "/run/systemd/propagate/jarvis.service/x"):
        pruefe(ausgenommen(p_), "AIDE nimmt aus: %s" % p_)
    for p_ in ("/var/log/auth.log", "/var/log/syslog", "/opt/sentinelone/bin/sentinelctl"):
        pruefe(not ausgenommen(p_) and gruppe(p_) is None,
               "AIDE laesst %s bei der Debian-Vorgabe (keine eigene Regel, keine Ausnahme)" % p_)

    # 4j Rotation fuer sudo.log
    lr = zeilen(W / "etc/logrotate.d/sudo-haertung")
    pruefe("/var/log/sudo.log {" in lr and any(z.startswith("rotate ") for z in lr)
           and "create 0600 root root" in lr, "logrotate: sudo.log rotiert, neue Datei 0600 root")

    # 4k auditd-Speicher (Datei im leeren Sandkasten angelegt)
    ad = {z.split("=")[0].strip(): z.split("=", 1)[1].strip() for z in zeilen(W / "etc/audit/auditd.conf") if "=" in z}
    pruefe(ad.get("max_log_file") == "50" and ad.get("num_logs") == "20",
           "auditd: max_log_file = 50, num_logs = 20 (ist %s/%s)" % (ad.get("max_log_file"), ad.get("num_logs")))

    # 4g Drop-in, 4h coredump
    di = zeilen(W / "etc/systemd/system/jarvis.service.d/70-coredump.conf")
    pruefe("[Service]" in di and "LimitCORE=0" in di, "Drop-in jarvis.service: [Service] LimitCORE=0")
    pruefe("Storage=none" in zeilen(W / "etc/systemd/coredump.conf.d/90-haertung.conf"), "coredump: Storage=none")

    # 4i sudoers
    sud = W / "etc/sudoers.d/10-haertung"
    pruefe(sud.is_file() and oct(sud.stat().st_mode & 0o777) == "0o440", "sudoers: Datei mit Modus 0440")
    pruefe('Defaults logfile="/var/log/sudo.log"' in zeilen(sud), "sudoers: Protokoll nach /var/log/sudo.log")
    # Das in [0] als tauglich gemessene Werkzeug - nicht erneut irgendeines aus
    # dem PATH: ein visudo, das die korrekte Vorlage ablehnt, wuerde hier einen
    # Befund ueber das Skript melden, der keiner ist.
    if VISUDO:
        r = subprocess.run([VISUDO, "-cf", str(sud)], capture_output=True, text=True,
                           env=dict(os.environ, LC_ALL="C"))
        pruefe(r.returncode == 0, "sudoers: visudo -cf akzeptiert die Datei (%s)" % VISUDO)

    # ── 4l. auditd.conf des Pakets: nur zwei Schluessel, Rest bleibt ──────────
    print("[4l] vorhandene auditd.conf")
    W3 = sandkasten / "c"
    (W3 / "etc/audit").mkdir(parents=True)
    debian = ("local_events = yes\nwrite_logs = yes\nlog_file = /var/log/audit/audit.log\nlog_format = ENRICHED\n"
              "max_log_file = 8\nnum_logs = 5\nmax_log_file_action = ROTATE\nspace_left_action = SYSLOG\n"
              "disk_full_action = SUSPEND\n")
    (W3 / "etc/audit/auditd.conf").write_text(debian, encoding="utf-8")
    rc, out = lauf("--pruefen", W3)
    pruefe(rc == 1 and "max_log_file = 8 (soll 50)" in out, "--pruefen meldet die Vorgabe 8 MB als Abweichung")
    lauf("--anwenden", W3)
    neu = zeilen(W3 / "etc/audit/auditd.conf")
    pruefe("max_log_file = 50" in neu and "num_logs = 20" in neu, "auditd.conf: beide Werte gesetzt")
    pruefe(all(z in neu for z in ("log_format = ENRICHED", "max_log_file_action = ROTATE", "disk_full_action = SUSPEND")),
           "auditd.conf: uebrige Zeilen des Pakets unveraendert")
    pruefe(len(neu) == len(debian.strip().splitlines()), "auditd.conf: keine Zeile doppelt angehaengt (%d Zeilen)" % len(neu))

    # ── 5. Kein Eingriff in apt ──────────────────────────────────────────────
    print("[5] apt bleibt unberuehrt")
    apt = [str(p) for p in W.rglob("*") if "/apt/" in str(p) or str(p).endswith("/apt")]
    pruefe(not apt, "keine Datei unter etc/apt (Jarvis verwaltet Remove-Unused-Dependencies)%s"
           % (" – gefunden: %s" % apt if apt else ""))

    # ── 6. Ungueltige sudoers-Datei wird NICHT eingespielt ───────────────────
    print("[6] sudoers-Schranke")
    if not VISUDO:
        print("  HINWEIS uebersprungen - ohne taugliches visudo misst diese Probe "
              "das Werkzeug (siehe [0])")
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

    # ── 7. B14: Kennwortregeln ───────────────────────────────────────────────
    print("[7] B14 Kennwortregeln")
    _text = SKRIPT.read_text(encoding="utf-8")
    _pakete = re.search(r'(?m)^PAKETE="([^"]*)"', _text)
    pruefe(bool(_pakete) and "libpam-pwquality" in _pakete.group(1).split(),
           "Paket libpam-pwquality steht in PAKETE")
    web = [" ".join(z.split()) for z in zeilen(W / "etc/pam.d/jarvis-web")]
    pruefe(web == ["auth required pam_unix.so", "account required pam_unix.so"],
           "jarvis-web: genau pam_unix fuer auth und account (%s)" % web)
    pruefe(not any("faillock" in z for z in web), "jarvis-web: OHNE pam_faillock")
    fl = (W / "usr/share/pam-configs/jarvis-faillock").read_text(encoding="utf-8") \
        if (W / "usr/share/pam-configs/jarvis-faillock").is_file() else ""
    fv = (W / "usr/share/pam-configs/jarvis-faillock-vorab").read_text(encoding="utf-8") \
        if (W / "usr/share/pam-configs/jarvis-faillock-vorab").is_file() else ""
    _authfail = re.search(r"\[default=die\]\s+pam_faillock\.so authfail (.*)", fl)
    _preauth = re.search(r"requisite\s+pam_faillock\.so preauth (.*)", fv)
    pruefe(bool(_authfail) and bool(_preauth), "Profile: authfail [default=die] und preauth requisite")
    _werte = lambda m: dict(t.split("=", 1) for t in m.group(1).split() if "=" in t) if m else {}
    pruefe(_werte(_authfail) == _werte(_preauth) and bool(_werte(_preauth)),
           "beide Profile mit denselben faillock-Werten (%s / %s)" % (_werte(_authfail), _werte(_preauth)))
    pruefe(_werte(_preauth) == {"deny": "5", "unlock_time": "900", "fail_interval": "900"},
           "faillock: 5 Fehlversuche in 15 Minuten sperren 15 Minuten (%s)" % _werte(_preauth))
    pruefe("even_deny_root" not in fl + fv, "root bleibt ausgenommen (kein even_deny_root, Notzugang)")
    pruefe(re.search(r"(?m)^Account:\n\s+required\s+pam_faillock\.so\s*$", fv) is not None,
           "Profil vorab: account required pam_faillock.so (setzt nach Erfolg zurueck)")
    _main = (WURZEL_REPO / "backend" / "main.py").read_text(encoding="utf-8")
    _min = re.search(r"(?m)^KENNWORT_MIN_LAENGE = (\d+)$", _main)
    pq = {z.split("=")[0].strip(): z.split("=", 1)[1].strip()
          for z in zeilen(W / "etc/security/pwquality.conf.d/90-haertung.conf") if "=" in z}
    pruefe(bool(_min) and pq.get("minlen") == _min.group(1) == "14",
           "pwquality minlen = main.KENNWORT_MIN_LAENGE = 14 (%s / %s)"
           % (pq.get("minlen"), _min.group(1) if _min else None))
    pruefe('PAM_DIENST_WEB = "jarvis-web"' in _main and 'PAM_DIENST_WEB = "jarvis-web"' in _text,
           "Schranke im Skript sucht genau die Zeile, die main.py traegt")

    # Aktivierung ueber die Attrappe (Laeufe aus [1]-[3] liegen schon hinter uns)
    auf = pam_aufrufe(W)
    pruefe(len(auf) == 1, "pam-auth-update genau EINMAL aufgerufen ueber [1]-[3] (%d)" % len(auf))
    pruefe(bool(auf) and auf[0].split() == ["--enable", "jarvis-faillock", "jarvis-faillock-vorab"],
           "Aufruf: --enable jarvis-faillock jarvis-faillock-vorab (%s)" % (auf[:1],))
    ca = W / "etc/pam.d/common-auth"
    ca.write_text("\n".join(z for z in ca.read_text().splitlines() if "preauth" not in z) + "\n")
    rc, out = lauf("--pruefen", W)
    pruefe(rc == 1 and "AUS" in out and "preauth" in out,
           "fehlendes faillock preauth in common-auth wird gemeldet (Exit %d)" % rc)
    rc, out = lauf("--anwenden", W)
    pruefe(len(pam_aufrufe(W)) == 2 and "preauth" in ca.read_text(),
           "--anwenden schaltet faillock wieder ein (%d Aufrufe)" % len(pam_aufrufe(W)))
    rc, out = lauf("--pruefen", W)
    pruefe(rc == 0, "danach --pruefen wieder 'alles umgesetzt' (Exit %d)" % rc)

    # Alter Jarvis-Code (Web-Anmeldung ueber "login"): faillock bleibt AUS
    W4 = sandkasten / "alt"
    (W4 / "opt/jarvis/backend").mkdir(parents=True)
    (W4 / "opt/jarvis/backend/main.py").write_text(
        'local_ok = _pam.authenticate(username, password, service="login")\n', encoding="utf-8")
    rc, out = lauf("--anwenden", W4)
    pruefe(rc == 0 and not pam_aufrufe(W4) and "'login'" in out,
           "alter Code: faillock NICHT eingeschaltet, Warnung nennt 'login' (%d Aufrufe)" % len(pam_aufrufe(W4)))
    rc, out = lauf("--pruefen", W4)
    pruefe(rc == 1 and "faillock" in out, "alter Code: --pruefen meldet faillock als AUS (Exit %d)" % rc)
    (W4 / "opt/jarvis/backend/main.py").write_text('PAM_DIENST_WEB = "jarvis-web"\n', encoding="utf-8")
    rc, out = lauf("--anwenden", W4)
    pruefe(len(pam_aufrufe(W4)) == 1, "neuer Code: faillock eingeschaltet (%d Aufruf)" % len(pam_aufrufe(W4)))

    # Testmodus ohne Attrappe: das echte pam-auth-update wird NICHT gerufen
    W5 = sandkasten / "ohne_attrappe"
    W5.mkdir()
    rc, out = lauf("--anwenden", W5, attrappe=False)
    pruefe(rc == 0 and "pam-auth-update uebersprungen" in out,
           "Testmodus ohne Attrappe: pam-auth-update uebersprungen (Exit %d)" % rc)
finally:
    shutil.rmtree(sandkasten, ignore_errors=True)

if NICHT_GEPRUEFT:
    print("NICHT GEPRUEFT: " + "; ".join(NICHT_GEPRUEFT))
print("ERGEBNIS: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
