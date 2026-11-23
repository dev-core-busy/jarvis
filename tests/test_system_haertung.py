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
 8. D8: IPv6 aus mit Schranke (siehe Abschnitt [8]).
 9. D5: MemorySwapMax=0 fuer Dienst und Broker, Swap-Zeilen der fstab mit
    eigener Marke auskommentiert (und mit SWAP_ERLAUBT=ja genau diese wieder
    zurueck), swapoff ueber eine ATTRAPPE nur bei genug freiem Speicher.
10. E2 (Teil): eigene fstab-Zeile fuer /dev/shm mit noexec (fremde Zeile wird
    gemeldet, nicht geaendert), remount ueber eine mount-ATTRAPPE.

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


# Attrappe fuer ip (D8): die Schranke "nutzt das Netz IPv6?" liest Adressen
# und Routen. Die Lage steht NEBEN der Wurzel (<wurzel>.ipv6): "global" =
# eine globale Adresse, "route" = eine IPv6-Standardroute, fehlt = nichts.
# Ohne Attrappe saehe das Skript das Netz des Pruefrechners.
IP_ATTRAPPE = r"""#!/bin/bash
lage="$(cat "${JARVIS_SYS_WURZEL}.ipv6" 2>/dev/null)"
case "$*" in
    *"addr show scope global"*)
        [ "$lage" = "global" ] && echo "2: ens192    inet6 2001:db8::5/64 scope global dynamic" ;;
    *"route show default"*)
        [ "$lage" = "route" ] && echo "default via fe80::1 dev ens192 proto ra metric 100" ;;
esac
exit 0
"""

# Attrappe fuer nmcli (D8): Zustand je Schnittstelle und Profil als Dateien in
# $NMD (dev_<if>_state, dev_<if>_con, con_<profil>_methode), jeder Aufruf im
# Protokoll $NMD/log. "modify" schreibt die Methode wie das echte Werkzeug.
NM_ATTRAPPE = r"""#!/bin/bash
d="${JARVIS_NMCLI_STAND:?}"
echo "$*" >> "$d/log"
if [ "$1" = "-g" ]; then
    case "$2 $3 $4" in
        "GENERAL.STATE device show") cat "$d/dev_$5_state" 2>/dev/null ;;
        "GENERAL.CONNECTION device show") cat "$d/dev_$5_con" 2>/dev/null ;;
        "ipv6.method connection show") cat "$d/con_$5_methode" 2>/dev/null ;;
    esac
    exit 0
fi
if [ "$1 $2" = "connection modify" ] && [ "$4" = "ipv6.method" ]; then
    echo "$5" > "$d/con_$3_methode"; exit 0
fi
exit 1
"""


# Attrappe fuer swapoff (D5): protokolliert jeden Aufruf neben der
# Ersatzdatei fuer /proc/swaps (<swaps>.log) und nimmt das Geraet dort heraus -
# wie das echte Werkzeug, das den Eintrag in /proc/swaps verschwinden laesst.
SWAPOFF_ATTRAPPE = r"""#!/bin/bash
s="${JARVIS_PROC_SWAPS:?}"
echo "$*" >> "$s.log"
{ head -1 "$s"; tail -n +2 "$s" | awk -v g="$1" '$1 != g'; } > "$s.neu" && mv "$s.neu" "$s"
"""


# Attrappe fuer mount (E2): protokolliert jeden Aufruf neben der Ersatzdatei
# fuer die Optionen von /dev/shm (<datei>.log) und schreibt die neuen Optionen
# hinein - wie ein echtes "mount -o remount,...".
MOUNT_ATTRAPPE = r"""#!/bin/bash
o="${JARVIS_SHM_OPTIONEN:?}"
echo "$*" >> "$o.log"
[ "$1" = "-o" ] && [ "$3" = "/dev/shm" ] || exit 1
echo "rw,${2#remount,},inode64" > "$o"
"""


def mount_aufrufe(opts):
    try:
        return [z for z in Path(str(opts) + ".log").read_text().splitlines() if z.strip()]
    except OSError:
        return []


def swapoff_aufrufe(swaps):
    try:
        return [z for z in Path(str(swaps) + ".log").read_text().splitlines() if z.strip()]
    except OSError:
        return []


def nm_modify(stand):
    try:
        return [z for z in (Path(stand) / "log").read_text().splitlines() if " modify " in " " + z + " "]
    except OSError:
        return []


def pam_aufrufe(wurzel):
    try:
        return [z for z in Path(str(wurzel) + ".pam.log").read_text().splitlines() if z.strip()]
    except OSError:
        return []


def lauf(modus, wurzel, skript=None, test=True, attrappe=True, ipv6_conf=None, nm=None,
         swaps=None, meminfo=None, shm=None):
    env = {k: v for k, v in os.environ.items()
           if k not in ("JARVIS_HAERTUNG_TEST", "JARVIS_SYS_WURZEL")}
    for k in ("JARVIS_VISUDO", "JARVIS_PAM_AUTH_UPDATE", "JARVIS_IP", "JARVIS_IPV6_CONF",
              "JARVIS_NMCLI", "JARVIS_NMCLI_STAND", "JARVIS_PROC_SWAPS", "JARVIS_MEMINFO",
              "JARVIS_SWAPOFF", "JARVIS_MOUNT", "JARVIS_SHM_OPTIONEN"):
        env.pop(k, None)
    if test and shm is not None:
        env["JARVIS_SHM_OPTIONEN"] = str(shm)
        env["JARVIS_MOUNT"] = str(MOUNT_ATTRAPPE_PFAD)
    if test and swaps is not None:
        env["JARVIS_PROC_SWAPS"] = str(swaps)
        env["JARVIS_SWAPOFF"] = str(SWAPOFF_ATTRAPPE_PFAD)
    if test and meminfo is not None:
        env["JARVIS_MEMINFO"] = str(meminfo)
    if test and attrappe:
        env["JARVIS_PAM_AUTH_UPDATE"] = str(PAM_ATTRAPPE_PFAD)
    if test:
        # ip IMMER als Attrappe - sonst entschiede das Netz des Pruefrechners
        # ueber die D8-Schranke, und das Ergebnis haenge am Rechner.
        env["JARVIS_IP"] = str(IP_ATTRAPPE_PFAD)
    if test and ipv6_conf is not None:
        env["JARVIS_IPV6_CONF"] = str(ipv6_conf)
    if test and nm is not None:
        env["JARVIS_NMCLI"] = str(NM_ATTRAPPE_PFAD)
        env["JARVIS_NMCLI_STAND"] = str(nm)
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
_ip_zuweisung = re.search(r'(?m)^(?P<bed>if [^\n]*)\n\s*IP_BEFEHL="\$JARVIS_IP"', _sk)
pruefe(bool(_ip_zuweisung) and '-n "$TEST"' in _ip_zuweisung.group("bed"),
       "JARVIS_IP wird nur im Testmodus gelesen (Produktivlauf nimmt ip des Systems)")
# Der Laufzeitteil von D8: Vorgabe das echte /proc und nmcli, die Ersatzwerte
# NUR im Testmodus - und dort ohne Vorgabe LEER (nie das echte /proc).
pruefe(bool(re.search(r'(?m)^IPV6_CONF="/proc/sys/net/ipv6/conf"\nNMCLI="nmcli"\n'
                      r'if \[ -n "\$TEST" \]; then\n\s*IPV6_CONF="\$\{JARVIS_IPV6_CONF:-\}"\n'
                      r'\s*NMCLI="\$\{JARVIS_NMCLI:-\}"\nfi$', _sk)),
       "JARVIS_IPV6_CONF/JARVIS_NMCLI nur im Testmodus, dort ohne Vorgabe leer")
pruefe(bool(re.search(r'(?m)^PROC_SWAPS="/proc/swaps"\nMEMINFO="/proc/meminfo"\nSWAPOFF="swapoff"\n'
                      r'if \[ -n "\$TEST" \]; then\n\s*PROC_SWAPS="\$\{JARVIS_PROC_SWAPS:-\}"\n'
                      r'\s*MEMINFO="\$\{JARVIS_MEMINFO:-\}"\n\s*SWAPOFF="\$\{JARVIS_SWAPOFF:-\}"\nfi$', _sk)),
       "JARVIS_PROC_SWAPS/JARVIS_MEMINFO/JARVIS_SWAPOFF nur im Testmodus, dort ohne Vorgabe leer")
pruefe(bool(re.search(r'(?m)^MOUNT="mount"\nSHM_OPTIONEN=""\n'
                      r'if \[ -n "\$TEST" \]; then\n\s*MOUNT="\$\{JARVIS_MOUNT:-\}"\n'
                      r'\s*SHM_OPTIONEN="\$\{JARVIS_SHM_OPTIONEN:-\}"\nfi$', _sk)),
       "JARVIS_MOUNT/JARVIS_SHM_OPTIONEN nur im Testmodus, dort ohne Vorgabe leer")

sandkasten = Path(tempfile.mkdtemp(prefix="sys_haertung_"))
PAM_ATTRAPPE_PFAD = sandkasten / "pam-auth-update-attrappe"
PAM_ATTRAPPE_PFAD.write_text(PAM_ATTRAPPE, encoding="utf-8")
PAM_ATTRAPPE_PFAD.chmod(0o755)
IP_ATTRAPPE_PFAD = sandkasten / "ip-attrappe"
IP_ATTRAPPE_PFAD.write_text(IP_ATTRAPPE, encoding="utf-8")
IP_ATTRAPPE_PFAD.chmod(0o755)
NM_ATTRAPPE_PFAD = sandkasten / "nmcli-attrappe"
NM_ATTRAPPE_PFAD.write_text(NM_ATTRAPPE, encoding="utf-8")
NM_ATTRAPPE_PFAD.chmod(0o755)
SWAPOFF_ATTRAPPE_PFAD = sandkasten / "swapoff-attrappe"
SWAPOFF_ATTRAPPE_PFAD.write_text(SWAPOFF_ATTRAPPE, encoding="utf-8")
SWAPOFF_ATTRAPPE_PFAD.chmod(0o755)
MOUNT_ATTRAPPE_PFAD = sandkasten / "mount-attrappe"
MOUNT_ATTRAPPE_PFAD.write_text(MOUNT_ATTRAPPE, encoding="utf-8")
MOUNT_ATTRAPPE_PFAD.chmod(0o755)
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

    # ── 8. D8 IPv6 aus ───────────────────────────────────────────────────────
    print("[8] D8 IPv6")
    ip6 = W / "etc/sysctl.d/90-haertung-ipv6.conf"
    lage = Path(str(W) + ".ipv6")
    soll6 = ["net.ipv6.conf.all.disable_ipv6 = 1", "net.ipv6.conf.default.disable_ipv6 = 1",
             "net.ipv6.conf.lo.disable_ipv6 = 0"]
    # Reihenfolge ist Teil der Zusage: "all" setzt auch lo, die lo-Zeile muss danach kommen.
    pruefe(zeilen(ip6) == soll6, "ohne IPv6 im Netz: eigene Datei, all/default aus, lo zuletzt wieder an (%s)"
           % zeilen(ip6))
    pruefe(oct(ip6.stat().st_mode & 0o777) == "0o644" if ip6.exists() else False, "Datei mit Modus 644")

    lage.write_text("global")
    rc, out = lauf("--pruefen", W)
    pruefe(rc == 1 and "WEICHT AB" in out and "90-haertung-ipv6.conf" in out and "globale IPv6-Adresse" in out,
           "globale Adresse + Datei da: --pruefen meldet den Widerspruch mit Grund (Exit %d)" % rc)
    pruefe(ip6.exists(), "--pruefen hat die Datei nicht entfernt")
    rc, out = lauf("--anwenden", W)
    pruefe(rc == 0 and not ip6.exists() and "entfernt" in out,
           "globale Adresse: --anwenden entfernt die eigene Datei (Exit %d)" % rc)
    rc, out = lauf("--pruefen", W)
    pruefe(rc == 0 and "bleibt an" in out, "danach --pruefen 'alles umgesetzt', IPv6 'bleibt an' (Exit %d)" % rc)

    lage.write_text("route")
    rc, out = lauf("--anwenden", W)
    pruefe(rc == 0 and not ip6.exists() and "Standardroute" in out,
           "IPv6-Standardroute: Datei wird nicht geschrieben (Exit %d)" % rc)

    lage.unlink()
    konf = W / "etc/jarvis/broker.conf"
    konf.parent.mkdir(parents=True, exist_ok=True)
    konf.write_text('SSH_NETZE="192.0.2.0/24"\nIPV6_ERLAUBT="ja"\n', encoding="utf-8")
    rc, out = lauf("--anwenden", W)
    pruefe(rc == 0 and not ip6.exists() and "IPV6_ERLAUBT" in out,
           "IPV6_ERLAUBT=ja (in Anfuehrungszeichen): Datei wird nicht geschrieben (Exit %d)" % rc)
    konf.write_text('IPV6_ERLAUBT=nein\n', encoding="utf-8")
    rc, out = lauf("--anwenden", W)
    pruefe(rc == 0 and zeilen(ip6) == soll6, "IPV6_ERLAUBT=nein und kein IPv6 im Netz: Datei kommt wieder")
    shutil.rmtree(W / "etc/jarvis")

    # Eine FREMDE Datei an derselben Stelle bleibt liegen
    ip6.write_text("# von Hand\nnet.ipv6.conf.all.disable_ipv6 = 1\n", encoding="utf-8")
    lage.write_text("global")
    rc, out = lauf("--anwenden", W)
    pruefe(ip6.exists() and "von Hand" in ip6.read_text(encoding="utf-8") and "nicht von diesem Skript" in out,
           "fremde Datei wird nicht entfernt, die Ausgabe sagt warum")
    lage.unlink()
    lauf("--anwenden", W)

    # Laufzeitteil: wirksamer Wert je Schnittstelle, NetworkManager-Profil
    W6 = sandkasten / "ipv6"
    W6.mkdir()
    conf = sandkasten / "ipv6_conf"
    nmd = sandkasten / "nm"
    nmd.mkdir()
    for name, wert in (("all", 1), ("default", 1), ("lo", 0), ("ens192", 0), ("tailscale0", 0), ("eth1", 0)):
        (conf / name).mkdir(parents=True)
        (conf / name / "disable_ipv6").write_text("%d\n" % wert)
    for name, state, con, meth in (("ens192", "100 (connected)", "Wired connection 1", "auto"),
                                   ("tailscale0", "100 (connected (externally))", "tailscale0", "ignore"),
                                   ("eth1", "10 (unmanaged)", "", "")):
        (nmd / ("dev_%s_state" % name)).write_text(state + "\n")
        (nmd / ("dev_%s_con" % name)).write_text(con + "\n")
        if con:
            (nmd / ("con_%s_methode" % con)).write_text(meth + "\n")

    def werte6():
        return {n: (conf / n / "disable_ipv6").read_text().strip() for n in ("lo", "ens192", "tailscale0", "eth1")}

    rc, out = lauf("--pruefen", W6, ipv6_conf=conf, nm=nmd)
    pruefe(all(("AN          IPv6 auf %s" % n) in out for n in ("ens192", "tailscale0", "eth1")),
           "--pruefen meldet jede Schnittstelle mit disable_ipv6 = 0 (ens192, tailscale0, eth1)")
    pruefe("IPv6 auf lo" not in out, "--pruefen laesst lo aus")
    pruefe('NM          ens192: Profil "Wired connection 1" mit ipv6.method=auto' in out,
           "--pruefen meldet das NM-Profil, das IPv6 wieder einschalten wuerde")
    pruefe("NM          tailscale0" not in out and "NM          eth1" not in out,
           "extern verbundene und nicht verwaltete Schnittstellen sind kein NM-Befund")
    pruefe(werte6() == {"lo": "0", "ens192": "0", "tailscale0": "0", "eth1": "0"} and not nm_modify(nmd),
           "--pruefen aendert weder Werte noch NM-Profile")
    rc, out = lauf("--anwenden", W6, ipv6_conf=conf, nm=nmd)
    pruefe(werte6() == {"lo": "0", "ens192": "1", "tailscale0": "1", "eth1": "1"},
           "--anwenden: alle Schnittstellen aus, lo bleibt an (%s)" % werte6())
    pruefe(nm_modify(nmd) == ["connection modify Wired connection 1 ipv6.method disabled"],
           "--anwenden: genau das NM-Profil von ens192 auf ipv6.method disabled (%s)" % nm_modify(nmd))
    pruefe(not any(("up" in z.split() or "reapply" in z.split()) for z in (nmd / "log").read_text().splitlines()),
           "keine Verbindung neu aufgebaut (kein nmcli up/reapply)")
    rc, out = lauf("--anwenden", W6, ipv6_conf=conf, nm=nmd)
    pruefe(len(nm_modify(nmd)) == 1 and "gesetzt" not in out and "aus          IPv6" not in out,
           "zweiter Lauf aendert nichts mehr (%d modify)" % len(nm_modify(nmd)))
    rc, out = lauf("--pruefen", W6, ipv6_conf=conf, nm=nmd)
    pruefe(rc == 0 and "AN          IPv6" not in out and "NM  " not in out,
           "danach --pruefen ohne IPv6-Befund (Exit %d)" % rc)

    # Schranke gilt auch fuer den Laufzeitteil
    for n in ("ens192", "eth1"):
        (conf / n / "disable_ipv6").write_text("0\n")
    Path(str(W6) + ".ipv6").write_text("global")
    rc, out = lauf("--anwenden", W6, ipv6_conf=conf, nm=nmd)
    pruefe(werte6()["ens192"] == "0" and werte6()["eth1"] == "0",
           "globale Adresse: der Laufzeitteil schaltet nichts ab")
    rc, out = lauf("--pruefen", W6, ipv6_conf=conf, nm=nmd)
    pruefe("AN          IPv6" not in out, "globale Adresse: kein Laufzeit-Befund")
    Path(str(W6) + ".ipv6").unlink()

    # Testmodus ohne Ersatzverzeichnis: das echte /proc wird nicht gelesen
    rc, out = lauf("--pruefen", W6)
    pruefe("IPv6 auf" not in out, "Testmodus ohne JARVIS_IPV6_CONF: kein Wert des Pruefrechners in der Ausgabe")

    # ── 9. D5 kein Swap ──────────────────────────────────────────────────────
    print("[9] D5 Swap")
    for unit in ("jarvis.service", "jarvis-broker.service"):
        d5 = W / "etc/systemd/system" / (unit + ".d") / "75-swap.conf"
        pruefe(zeilen(d5) == ["[Service]", "MemorySwapMax=0"],
               "%s: eigener Drop-in mit MemorySwapMax=0 (%s)" % (unit, zeilen(d5)))
        pruefe(d5.exists() and oct(d5.stat().st_mode & 0o777) == "0o644", "%s: Drop-in mit Modus 644" % unit)

    W9 = sandkasten / "swap"
    (W9 / "etc").mkdir(parents=True)
    fstab = W9 / "etc/fstab"
    ROOT_Z = "UUID=1111 /               ext4    errors=remount-ro 0       1"
    SWAP_Z = "UUID=2222 none            swap    sw              0       0"
    HAND_Z = "# /swapfile none swap sw 0 0"
    TAB_Z = "/dev/sdb1\tnone\tswap\tdefaults\t0\t0"
    SHM_Z = "tmpfs /dev/shm tmpfs defaults,nosuid,nodev,noexec 0 0"
    # Mit richtiger /dev/shm-Zeile: E2 laesst die Datei dann in Ruhe, und die
    # D5-Pruefungen "Zeichen fuer Zeichen gleich" messen nur D5.
    FSTAB_ALT = "# /etc/fstab\n%s\n%s\n%s\n%s\n%s\n" % (ROOT_Z, SWAP_Z, HAND_Z, TAB_Z, SHM_Z)
    fstab.write_text(FSTAB_ALT, encoding="utf-8")
    fstab.chmod(0o640)
    rc, out = lauf("--pruefen", W9)
    pruefe(rc == 1 and "SWAP        %s: UUID=2222" % fstab in out and "SWAP        %s: /dev/sdb1" % fstab in out,
           "--pruefen meldet jede aktive Swap-Zeile, auch mit Tabulatoren (Exit %d)" % rc)
    pruefe("/swapfile" not in out, "--pruefen: eine schon auskommentierte Zeile ist kein Befund")
    pruefe(fstab.read_text(encoding="utf-8") == FSTAB_ALT, "--pruefen aendert die fstab nicht")
    rc, out = lauf("--anwenden", W9)
    erwartet = "# /etc/fstab\n%s\n#haertung-D5# %s\n%s\n#haertung-D5# %s\n%s\n" % (ROOT_Z, SWAP_Z, HAND_Z, TAB_Z, SHM_Z)
    pruefe(fstab.read_text(encoding="utf-8") == erwartet,
           "--anwenden: genau die Swap-Zeilen mit Marke auskommentiert, alles andere Zeichen fuer Zeichen gleich")
    pruefe(oct(fstab.stat().st_mode & 0o777) == "0o640", "Rechte der fstab bleiben (640)")
    st = fstab.stat().st_mtime_ns
    time.sleep(0.02)
    rc, out = lauf("--anwenden", W9)
    pruefe(fstab.stat().st_mtime_ns == st and "auskommentiert" not in out,
           "zweiter Lauf laesst die fstab unberuehrt")
    rc, out = lauf("--pruefen", W9)
    pruefe("SWAP  " not in out, "danach --pruefen ohne Swap-Befund in der fstab")

    (W9 / "etc/jarvis").mkdir()
    (W9 / "etc/jarvis/broker.conf").write_text("SWAP_ERLAUBT='ja'\n", encoding="utf-8")
    rc, out = lauf("--pruefen", W9)
    pruefe(rc == 1 and "von D5 auskommentiert" in out and "SWAP_ERLAUBT" in out,
           "SWAP_ERLAUBT=ja: --pruefen meldet die eigenen Kommentare als Widerspruch (Exit %d)" % rc)
    rc, out = lauf("--anwenden", W9)
    pruefe(fstab.read_text(encoding="utf-8") == FSTAB_ALT,
           "SWAP_ERLAUBT=ja: --anwenden stellt genau den alten Stand her (von Hand auskommentierte Zeile bleibt)")
    rc, out = lauf("--pruefen", W9)
    pruefe("bleibt an   Swap" in out and "SWAP  " not in out, "danach 'bleibt an', kein Swap-Befund")

    # Laufzeitteil ueber Ersatzdateien und die swapoff-Attrappe
    swaps = sandkasten / "swaps"
    meminfo = sandkasten / "meminfo"
    KOPF = "Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n"
    BELEGT = 336696

    def swaps_an():
        swaps.write_text(KOPF + "/dev/sda5                               partition\t5363708\t\t%d\t\t-2\n" % BELEGT)

    def mem(verfuegbar):
        meminfo.write_text("MemTotal:       16383272 kB\nMemAvailable:   %d kB\n" % verfuegbar)

    rc, out = lauf("--pruefen", W9, swaps=swaps, meminfo=meminfo)
    swaps_an(); mem(10000000)
    rc, out = lauf("--anwenden", W9, swaps=swaps, meminfo=meminfo)
    pruefe(not swapoff_aufrufe(swaps), "SWAP_ERLAUBT=ja: kein swapoff")
    shutil.rmtree(W9 / "etc/jarvis")

    rc, out = lauf("--pruefen", W9, swaps=swaps, meminfo=meminfo)
    pruefe(rc == 1 and "SWAP an     /dev/sda5" in out, "--pruefen meldet den aktiven Swap (Exit %d)" % rc)
    pruefe(not swapoff_aufrufe(swaps), "--pruefen ruft kein swapoff")
    mem(2097152 + BELEGT - 1)
    rc, out = lauf("--anwenden", W9, swaps=swaps, meminfo=meminfo)
    pruefe(not swapoff_aufrufe(swaps) and "zu wenig freier Speicher" in out,
           "1 kB unter der Reserve: kein swapoff, Warnung nennt den Grund")
    meminfo.write_text("MemTotal:       16383272 kB\n")
    rc, out = lauf("--anwenden", W9, swaps=swaps, meminfo=meminfo)
    pruefe(not swapoff_aufrufe(swaps) and "zu wenig freier Speicher" in out,
           "MemAvailable unbekannt: kein swapoff")
    mem(2097152 + BELEGT)
    rc, out = lauf("--anwenden", W9, swaps=swaps, meminfo=meminfo)
    pruefe(swapoff_aufrufe(swaps) == ["/dev/sda5"], "genau an der Reserve: swapoff /dev/sda5 einmal (%s)"
           % swapoff_aufrufe(swaps))
    rc, out = lauf("--anwenden", W9, swaps=swaps, meminfo=meminfo)
    pruefe(len(swapoff_aufrufe(swaps)) == 1, "zweiter Lauf ruft kein swapoff mehr")
    rc, out = lauf("--pruefen", W9, swaps=swaps, meminfo=meminfo)
    pruefe(rc == 0 and "SWAP" not in out, "danach --pruefen 'alles umgesetzt' (Exit %d)" % rc)

    # Testmodus ohne Ersatzdateien: das echte /proc/swaps wird nicht gelesen
    rc, out = lauf("--pruefen", W9)
    pruefe("SWAP an" not in out, "Testmodus ohne JARVIS_PROC_SWAPS: kein Swap des Pruefrechners in der Ausgabe")

    # ── 10. E2 /dev/shm ohne Ausfuehrung ─────────────────────────────────────
    print("[10] E2 /dev/shm")
    W10 = sandkasten / "shm"
    (W10 / "etc").mkdir(parents=True)
    fs = W10 / "etc/fstab"
    GRUND = "# /etc/fstab\nUUID=1111 / ext4 errors=remount-ro 0 1\n"
    fs.write_text(GRUND, encoding="utf-8")
    fs.chmod(0o644)
    shm = sandkasten / "shm_optionen"
    shm.write_text("rw,nosuid,nodev,inode64\n")
    rc, out = lauf("--pruefen", W10, shm=shm)
    pruefe(rc == 1 and "FEHLT       %s: /dev/shm mit noexec" % fs in out and "AUSFUEHRBAR /dev/shm" in out,
           "--pruefen meldet fehlende fstab-Zeile und ausfuehrbares /dev/shm (Exit %d)" % rc)
    pruefe(fs.read_text(encoding="utf-8") == GRUND and not mount_aufrufe(shm), "--pruefen aendert nichts")
    rc, out = lauf("--anwenden", W10, shm=shm)
    soll_e2 = ["UUID=1111 / ext4 errors=remount-ro 0 1", "tmpfs /dev/shm tmpfs defaults,nosuid,nodev,noexec 0 0"]
    pruefe(zeilen(fs) == soll_e2 and fs.read_text(encoding="utf-8").startswith(GRUND),
           "--anwenden haengt genau die /dev/shm-Zeile an, der Rest bleibt (%s)" % zeilen(fs))
    pruefe(mount_aufrufe(shm) == ["-o remount,nosuid,nodev,noexec /dev/shm"],
           "--anwenden haengt /dev/shm einmal mit nosuid,nodev,noexec neu ein (%s)" % mount_aufrufe(shm))
    st = fs.stat().st_mtime_ns
    time.sleep(0.02)
    rc, out = lauf("--anwenden", W10, shm=shm)
    pruefe(fs.stat().st_mtime_ns == st and len(mount_aufrufe(shm)) == 1,
           "zweiter Lauf: fstab unberuehrt, kein weiteres remount")
    rc, out = lauf("--pruefen", W10, shm=shm)
    pruefe(rc == 0 and "/dev/shm" not in out.replace("ok          ", ""),
           "danach --pruefen 'alles umgesetzt' (Exit %d)" % rc)

    # Fremde Zeile ohne noexec: melden, nicht aendern
    FREMD = GRUND + "tmpfs /dev/shm tmpfs defaults,nosuid 0 0\n"
    fs.write_text(FREMD, encoding="utf-8")
    rc, out = lauf("--anwenden", W10, shm=shm)
    pruefe(fs.read_text(encoding="utf-8") == FREMD, "fremde /dev/shm-Zeile bleibt unveraendert")
    rc, out = lauf("--pruefen", W10, shm=shm)
    pruefe(rc == 1 and "ohne nodev noexec" in out and "nicht von diesem Skript" in out,
           "fremde Zeile ohne nodev/noexec wird mit den fehlenden Optionen gemeldet (Exit %d)" % rc)

    # Testmodus ohne Ersatzdatei: das /dev/shm des Pruefrechners bleibt unberuehrt
    rc, out = lauf("--pruefen", W10)
    pruefe("AUSFUEHRBAR" not in out, "Testmodus ohne JARVIS_SHM_OPTIONEN: kein /dev/shm des Pruefrechners in der Ausgabe")
finally:
    shutil.rmtree(sandkasten, ignore_errors=True)

if NICHT_GEPRUEFT:
    print("NICHT GEPRUEFT: " + "; ".join(NICHT_GEPRUEFT))
print("ERGEBNIS: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
