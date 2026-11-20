#!/usr/bin/env python3
"""Waechter: verworfene Pakete werden protokolliert (Haertung B11, Checkliste 52).

Zusage: jede Filterkette schreibt, was sie verwirft, gedrosselt ins
Kernel-Journal – mit festen Praefixen, an denen die Ueberwachung (B13) sucht:
  nft-in-drop:   eingehend   (deploy/security/firewall.sh, Kette input / JARVIS-IN)
  nft-fwd-drop:  weitergeleitet (firewall.sh, Kette forward / FORWARD)
  nft-out-drop:  ausgehend   (backend/egress_guard.py, nur der Sandbox-Benutzer)

GEMESSEN, nicht gesucht:
  [0] Positivkontrollen: nft prueft im Wegwerf-Namensraum (unshare -rn) WIRKLICH
      – ein kaputter Satz faellt durch, ein guter nicht. Ohne das Exit 2.
  [1] nft-Weg: der Regelsatz aus ``firewall.sh --zeigen`` (mit und ohne
      SSH_NETZE) – die Log-Regel ist die LETZTE der Kette, steht hinter jedem
      accept, ist gedrosselt und nimmt nur Pakete an den Host (kein Multicast-
      Rauschen: auf DEV verbrauchte mDNS sonst die Drossel); ``nft -c`` nimmt
      den Satz an.
  [2] iptables-Weg: ``firewall.sh --setzen`` im Sandkasten mit Attrappen, die
      jeden Aufruf mitschreiben – je Familie ist die letzte JARVIS-IN-Regel die
      LOG-Regel; FORWARD bekommt sie nur, wenn sie fehlt (kein Wachsen je Lauf).
  [3] Ausgang: ``_render_nft`` – die Log-Regel steht direkt vor dem drop, ist an
      den Sandbox-Benutzer gebunden (sonst protokollierte sie Kernel-Sockets) und
      nennt ihn (flags skuid). Der Satz wird im Namensraum GELADEN, und die echte
      ``nft list``-Ausgabe gilt fuer ``kette_veraltet()`` nicht als veraltet.

Fuer die Gegenprobe: JARVIS_FW_PRUEFLING / JARVIS_EGRESS_PRUEFLING zeigen auf
Kopien; die Repo-Dateien werden nie angefasst.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FW = Path(os.environ.get("JARVIS_FW_PRUEFLING") or REPO / "deploy" / "security" / "firewall.sh")
EG = Path(os.environ.get("JARVIS_EGRESS_PRUEFLING") or REPO / "backend" / "egress_guard.py")
RATE_NFT = "limit rate 5/minute"
NUR_HOST = "meta pkttype host"
OK = FAIL = 0


def check(name, bedingung, detail=""):
    global OK, FAIL
    if bedingung:
        OK += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        FAIL += 1
        print(f"  \033[31m✗\033[0m {name}" + (f" – {detail}" if detail else ""))


def abbruch(grund):
    print(f"ABBRUCH: {grund}")
    sys.exit(2)


def nft_pruefen(text):
    """``nft -c`` im eigenen Netz-Namensraum: (rc, Meldung)."""
    with tempfile.NamedTemporaryFile("w", suffix=".nft", delete=False) as f:
        f.write(text)
    try:
        p = subprocess.run(["unshare", "-rn", "nft", "-c", "-f", f.name],
                           capture_output=True, text=True, timeout=30)
        return p.returncode, (p.stderr or p.stdout).strip()[:300]
    finally:
        os.unlink(f.name)


def nft_laden_und_listen(text, tabelle):
    """Satz im Namensraum laden und die Tabelle so listen, wie nft sie zeigt."""
    with tempfile.NamedTemporaryFile("w", suffix=".nft", delete=False) as f:
        f.write(text)
    try:
        p = subprocess.run(["unshare", "-rn", "sh", "-c",
                            'nft -f "$1" && nft list table inet "$2"', "sh", f.name, tabelle],
                           capture_output=True, text=True, timeout=30)
        return p.returncode, p.stdout
    finally:
        os.unlink(f.name)


def kette(text, name):
    """Regelzeilen der Kette ``name`` (ohne type-Zeile) – oder None."""
    m = re.search(r"chain %s \{(.*?)\n\s*\}" % re.escape(name), text, re.S)
    if not m:
        return None
    return [z.strip() for z in m.group(1).splitlines()
            if z.strip() and not z.strip().startswith("type ")]


# ── 0 Positivkontrollen ──────────────────────────────────────────────────────
print("\033[1m0 – Messwerkzeug\033[0m")
for werkzeug in ("nft", "unshare"):
    if not shutil.which(werkzeug):
        abbruch(f"{werkzeug} fehlt – ohne echten nft-Parser ist die Syntax nicht messbar")
if not FW.is_file() or not EG.is_file():
    abbruch(f"Pruefling fehlt ({FW} / {EG})")
# Guter und kaputter Satz unterscheiden sich in GENAU einem Wort – sonst koennte
# der kaputte aus einem anderen Grund scheitern und belegte nichts.
_PROBE = ('table inet t {\n    chain c {\n        type filter hook input priority 0;\n'
          '        limit rate 5/minute %s prefix "x"\n    }\n}\n')
rc, msg = nft_pruefen(_PROBE % "log")
if rc != 0:
    abbruch(f"nft -c im Namensraum laeuft nicht ({msg}) – unprivilegierte Namensraeume gesperrt?")
rc_kaputt, _ = nft_pruefen(_PROBE % "lag")
if rc_kaputt == 0:
    abbruch("nft -c nimmt einen kaputten Satz an – die Syntaxpruefung waere trivial gruen")
print("  nft -c im Namensraum: guter Satz rc 0, kaputter Satz rc %d" % rc_kaputt)


# ── 1 nft-Weg (ECHT) ─────────────────────────────────────────────────────────
print("\n\033[1m1 – nft-Weg: firewall.sh --zeigen\033[0m")


def zeigen(conf, sitzung=None):
    d = Path(tempfile.mkdtemp(prefix="jv_fwlog_"))
    try:
        bc = d / "broker.conf"
        bc.write_text(conf)
        e = {k: v for k, v in os.environ.items() if k != "SSH_CONNECTION"}
        e["JARVIS_BROKER_CONF"] = str(bc)
        if sitzung:
            e["SSH_CONNECTION"] = f"{sitzung} 50000 192.0.2.254 22"
        return subprocess.run(["bash", str(FW), "--zeigen"], env=e, capture_output=True,
                              text=True, timeout=60)
    finally:
        shutil.rmtree(d, ignore_errors=True)


for titel, conf, sitzung in (("ohne SSH_NETZE", "", None),
                             ("mit SSH_NETZE", 'SSH_NETZE="192.0.2.0/24 2001:db8::/48"\n',
                              "192.0.2.10")):
    r = zeigen(conf, sitzung)
    eingang = kette(r.stdout, "input") if r.returncode == 0 else None
    weiter = kette(r.stdout, "forward") if r.returncode == 0 else None
    if not eingang or weiter is None or not any("accept" in z for z in eingang):
        print(r.stdout, r.stderr)
        abbruch(f"--zeigen ({titel}) liefert keinen deutbaren Regelsatz")
    letzte = eingang[-1]
    check(f"{titel}: letzte input-Regel protokolliert mit 'nft-in-drop: '",
          letzte == f'{NUR_HOST} {RATE_NFT} log prefix "nft-in-drop: "', letzte)
    check(f"{titel}: genau eine Log-Regel in input",
          sum(" log " in f" {z} " for z in eingang) == 1, eingang)
    i_log = next((i for i, z in enumerate(eingang) if " log " in f" {z} "), -1)
    check(f"{titel}: jede accept-Regel steht VOR der Log-Regel",
          i_log >= 0 and all(i < i_log for i, z in enumerate(eingang) if "accept" in z), eingang)
    check(f"{titel}: forward protokolliert mit 'nft-fwd-drop: '",
          bool(weiter) and weiter[-1] == f'{NUR_HOST} {RATE_NFT} log prefix "nft-fwd-drop: "', weiter)
    check(f"{titel}: Policy bleibt drop (die Log-Regel verwirft nicht selbst)",
          r.stdout.count("policy drop;") == 2 and not any("drop" in z for z in eingang + weiter
                                                          if " log " not in f" {z} "), r.stdout)
    rc, msg = nft_pruefen(r.stdout)
    check(f"{titel}: nft -c nimmt den Satz an", rc == 0, msg)


# ── 2 iptables-Weg (DEV) ─────────────────────────────────────────────────────
print("\n\033[1m2 – iptables-Weg: firewall.sh --setzen (Attrappen)\033[0m")


def iptables_lauf(forward_vorhanden):
    """--setzen im Sandkasten. Rueckgabe: Liste (programm, [argumente])."""
    d = Path(tempfile.mkdtemp(prefix="jv_fwlog_ipt_"))
    try:
        fake = d / "bin"
        fake.mkdir()
        log = d / "aufrufe.log"
        # -C (vorhanden?): fuer die FORWARD-Log-Regel je nach Fall, sonst NEIN –
        # ein immer-0 liesse die while-Schleife ueber die Altregeln endlos drehen.
        fw_c = "exit 0" if forward_vorhanden else "exit 1"
        rumpf = ('printf "%%s" "$(basename "$0")" >> "%s"; for a in "$@"; do printf "\\t%%s" "$a" >> "%s"; done; '
                 'echo >> "%s"\n'
                 'if [ "$1" = "-C" ]; then [ "$2" = "FORWARD" ] && %s; exit 1; fi\nexit 0\n') % (log, log, log, fw_c)
        for name in ("iptables", "ip6tables"):
            (fake / name).write_text("#!/bin/bash\n" + rumpf)
            (fake / name).chmod(0o755)
        for name, inhalt in (("systemctl", "exit 1"), ("ss", "exit 0")):
            (fake / name).write_text("#!/bin/bash\n" + inhalt + "\n")
            (fake / name).chmod(0o755)
        bc = d / "broker.conf"
        bc.write_text('SSH_NETZE="192.0.2.0/24 2001:db8::/48"\n')
        e = {k: v for k, v in os.environ.items() if k != "SSH_CONNECTION"}
        e.update(PATH=f"{fake}:/usr/bin:/bin", JARVIS_FW_TEST="1", JARVIS_BROKER_CONF=str(bc))
        p = subprocess.run(["bash", str(FW), "--setzen"], env=e, capture_output=True,
                           text=True, timeout=60)
        zeilen = log.read_text().splitlines() if log.exists() else []
        return p.returncode, [(z.split("\t")[0], z.split("\t")[1:]) for z in zeilen], p.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


rc, aufrufe, err = iptables_lauf(forward_vorhanden=False)
if rc != 0 or not any(a[:2] == ["-A", "JARVIS-IN"] for _, a in aufrufe):
    abbruch(f"--setzen im Sandkasten lief nicht (rc {rc}, {err.strip()[:200]})")
LOG_IN = ["-m", "pkttype", "--pkt-type", "unicast", "-m", "limit", "--limit", "5/min", "-j", "LOG", "--log-prefix", "nft-in-drop: "]
LOG_FWD = ["-m", "pkttype", "--pkt-type", "unicast", "-m", "limit", "--limit", "5/min", "-j", "LOG", "--log-prefix", "nft-fwd-drop: "]
for prog in ("iptables", "ip6tables"):
    jin = [a for p, a in aufrufe if p == prog and a[:2] == ["-A", "JARVIS-IN"]]
    check(f"{prog}: letzte JARVIS-IN-Regel ist die LOG-Regel", bool(jin) and jin[-1][2:] == LOG_IN,
          jin[-1] if jin else "keine")
    check(f"{prog}: genau eine LOG-Regel in JARVIS-IN",
          sum("LOG" in a for a in jin) == 1, [a for a in jin if "LOG" in a])
    fwd = [a for p, a in aufrufe if p == prog and a[:2] == ["-A", "FORWARD"]]
    check(f"{prog}: FORWARD bekommt die LOG-Regel, wenn sie fehlt",
          fwd == [["-A", "FORWARD"] + LOG_FWD], fwd)
    pol = [a for p, a in aufrufe if p == prog and a[:1] == ["-P"]]
    check(f"{prog}: Policy INPUT DROP bleibt", ["-P", "INPUT", "DROP"] in pol, pol)
rc, aufrufe, err = iptables_lauf(forward_vorhanden=True)
fwd = [a for p, a in aufrufe if a[:2] == ["-A", "FORWARD"]]
check("FORWARD: steht die LOG-Regel schon da, kommt keine zweite dazu", rc == 0 and fwd == [], fwd)


# ── 3 Ausgang (egress_guard) ─────────────────────────────────────────────────
print("\n\033[1m3 – Ausgang: egress_guard._render_nft\033[0m")
spec = importlib.util.spec_from_file_location("egress_pruefling", EG)
eg = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(eg)
    satz = eg._render_nft(996, ["192.0.2.53"])
except Exception as e:  # noqa: BLE001
    abbruch(f"egress_guard nicht ladbar: {e}")
aus = kette(satz, "out")
if not aus or "meta skuid 996 drop" not in aus:
    abbruch("_render_nft liefert keine deutbare Kette")
logs = [z for z in aus if " log " in f" {z} "]
check("genau eine Log-Regel", len(logs) == 1, logs)
log = logs[0] if logs else ""
check("sie steht DIREKT vor dem drop", aus.index("meta skuid 996 drop") == aus.index(log) + 1
      if log else False, aus)
check("an den Sandbox-Benutzer gebunden (sonst Kernel-Sockets im Journal)",
      log.startswith("meta skuid 996 "), log)
check("gedrosselt, Praefix 'nft-out-drop: ', nennt den Benutzer (flags skuid)",
      RATE_NFT in log and 'log prefix "nft-out-drop: "' in log and log.endswith("flags skuid"), log)
rc, msg = nft_pruefen(satz)
check("nft -c nimmt den Satz an", rc == 0, msg)
rc, gelistet = nft_laden_und_listen(satz, eg.NFT_TABLE)
if rc != 0 or "chain out" not in gelistet:
    abbruch(f"Ausgangskette laesst sich im Namensraum nicht laden/listen (rc {rc})")
check("geladen: die Log-Regel ist im Kernel angekommen",
      'log prefix "nft-out-drop: " flags skuid' in gelistet, gelistet)


class _R:
    def __init__(self, out):
        self.returncode, self.stdout, self.stderr = 0, out, ""


eg._run = lambda cmd, timeout=15: _R(gelistet)
veraltet, zeilen = eg.kette_veraltet()
check("kette_veraltet() haelt die echte Liste fuer aktuell (keine Selbstheilung)",
      veraltet is False, zeilen)

print(f"\nERGEBNIS: {OK} OK, {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
