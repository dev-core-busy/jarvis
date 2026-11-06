#!/usr/bin/env python3
"""Gegenprobe zu tests/test_sandbox_netz.py (Befund E1): beisst der Waechter?

Jede Probe dreht EINEN Teil des Fixes zurueck (Python-Ersetzung ganzer Zeilen),
laesst den Waechter laufen und erwartet mindestens einen FAIL mit Bilanzzeile –
Exit 2 oder ein Lauf ohne Bilanz zaehlt NICHT als Biss. Vorher gruener
Basislauf, danach Byte-Gleichheit aller Dateien per md5. Ohne Bytecode
(PYTHONDONTWRITEBYTECODE=1). Laufmarke: ein abgeschossener Lauf wird beim
naechsten Start zurueckgenommen.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.

    venv/bin/python tests/gegen_sandbox_netz.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / "venv" / "bin" / "python") if (ROOT / "venv" / "bin" / "python").exists() \
    else sys.executable
MARKE = ROOT / "tests" / ".gegen_sandbox_netz.laufmarke"

SG = "backend/sandbox_grenzen.py"
OP = "backend/broker/ops.py"
WT = "tests/test_sandbox_netz.py"

PROBEN = [
    ("Abweisung ohne uid-Bindung (Kernel-Sockets/CIFS getroffen)", SG,
     '        sperre.append(f"        {sk} {treffer} meta l4proto tcp counter reject with tcp reset\\n")\n'
     '        sperre.append(f"        {sk} {treffer} counter reject\\n")\n',
     '        sperre.append(f"        {treffer} meta l4proto tcp counter reject with tcp reset\\n")\n'
     '        sperre.append(f"        {treffer} counter reject\\n")\n'),
    ("Abweisung VOR den Ausnahmen", SG,
     '        + "".join(erlaubt) + "".join(sperre) +\n',
     '        + "".join(sperre) + "".join(erlaubt) +\n'),
    ("Link-Local/Cloud-Metadaten frei", SG,
     '    "169.254.0.0/16",     # Link-Local, Cloud-Metadaten\n', ""),
    ("CGNAT frei", SG, '    "100.64.0.0/10",      # CGNAT, RFC 6598\n', ""),
    ("Multicast v4 frei", SG, '    "224.0.0.0/4",        # Multicast\n', ""),
    ("ULA (fc00::/7) frei", SG, '    "fc00::/7",           # Unique Local\n', ""),
    ("IPv4-mapped frei", SG, '    "::ffff:0:0/96",      # IPv4-mapped\n', ""),
    ("eigene Adressen/Loopback (oif lo) frei", SG,
     "    for treffer in ('oif \"lo\"', \"ip daddr @intern4\", \"ip6 daddr @intern6\"):\n",
     "    for treffer in (\"ip daddr @intern4\", \"ip6 daddr @intern6\"):\n"),
    ("DNS pauschal (Port 53 ins interne Netz)", SG,
     '            erlaubt.append(f"        {sk} {fam} daddr {{ {ziel} }} udp dport 53 accept\\n")\n',
     '            erlaubt.append(f"        {sk} udp dport 53 accept\\n")\n'),
    ("Proxy nicht erlaubt", SG, "    for adr, port in proxys:\n", "    for adr, port in []:\n"),
    ("Zone der Resolver-Adresse nicht entfernt", SG,
     '        roh = teile[1].split("%", 1)[0]\n', "        roh = teile[1]\n"),
    ("Fehlschlag wird gemerkt (Cache meldet 'gesetzt')", SG,
     "            _netz_stand.update(zeit=0.0, schluessel=None)\n"
     "            return False, (\"Sperre interner Netze nicht setzbar: \"\n",
     "            _netz_stand.update(zeit=jetzt, schluessel=schluessel)\n"
     "            return False, (\"Sperre interner Netze nicht setzbar: \"\n"),
    ("bereit() ohne Netz-Sperre", SG,
     "        ok, grund = netz_sperre_sicherstellen()\n        if not ok:\n            return False, grund\n",
     "        pass\n"),
    ("bereit() nimmt im Zweifel 'ohne Netz' an", SG,
     "        ohne_netz = sandbox_user == NOINET_USER\n", "        ohne_netz = True\n"),
    # ── Nachbesserung: zusaetzliche interne Netze ──
    ("Zusatznetze landen nicht im Set", SG,
     "    set4, set6 = sperrmengen(zusatz)\n", "    set4, set6 = sperrmengen()\n"),
    ("Ueberlappungen nicht zusammengefuehrt (nft: conflicting intervals)", SG,
     "    return ([str(n) for n in ipaddress.collapse_addresses(v4)],\n",
     "    return ([str(n) for n in v4],\n"),
    ("IPv4-mapped in Mischschreibweise", SG,
     '            [n.exploded if "." in str(n) else str(n) for n in ipaddress.collapse_addresses(v6)])\n',
     "            [str(n) for n in ipaddress.collapse_addresses(v6)])\n"),
    ("Konfiguration wird nicht benutzt", SG,
     "        konf = konf_intern_netze()\n", "        konf = []\n"),
    ("angeschlossene Netze werden nicht benutzt", SG,
     "        zus = konf + [n for n in angeschlossene_netze() if n not in konf]\n",
     "        zus = konf\n"),
    ("falscher Schluessel in broker.conf", SG,
     'KONF_INTERN_NETZE = "SANDBOX_INTERN_NETZE"\n', 'KONF_INTERN_NETZE = "SANDBOX_NETZE"\n'),
    ("ein ungueltiger Eintrag verwirft alle", SG,
     '            _einmal_melden(f"{KONF_INTERN_NETZE}: ungueltiger Eintrag verworfen: {roh!r}")\n'
     "            continue\n",
     '            _einmal_melden(f"{KONF_INTERN_NETZE}: ungueltiger Eintrag verworfen: {roh!r}")\n'
     "            return []\n"),
    ("/0 wird angenommen (sperrt das Internet)", SG,
     "        if n.prefixlen == 0:\n", "        if False:\n"),
    ("ungueltiger Eintrag ohne Journal-Zeile", SG,
     '            _einmal_melden(f"{KONF_INTERN_NETZE}: ungueltiger Eintrag verworfen: {roh!r}")\n',
     ""),
    ("nur die Host-Adresse statt des angeschlossenen Netzes", SG,
     "                n = ipaddress.ip_network(f\"{a.get('local')}/{int(a.get('prefixlen'))}\", strict=False)\n",
     "                n = ipaddress.ip_network(str(a.get('local')))\n"),
    ("Onlink-Gateway nicht gesperrt", SG,
     "            netze.append(ipaddress.ip_network(gw))\n", "            pass\n"),
    ("Resolver im Block auf allen Ports offen", SG,
     '            erlaubt.append(f"        {sk} {fam} daddr {{ {ziel} }} tcp dport 53 accept\\n")\n',
     '            erlaubt.append(f"        {sk} {fam} daddr {{ {ziel} }} accept\\n")\n'),
    ("Broker reicht ohne_netz nicht an bereit()", OP,
     "    ok, grund = _sg.bereit(user, ohne_netz=ohne_netz)\n", "    ok, grund = _sg.bereit(user)\n"),
]

DATEIEN = [SG, OP, WT]

WAECHTER = [([PY, WT], r"Ergebnis: (\d+) OK, (\d+) FAIL")]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf():
    """Summe der FAILs. -1 = ein Waechter konnte nicht laufen (kein Biss)."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    for cmd, muster in WAECHTER:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                               cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            return -1, "timeout"
        m = re.search(muster, r.stdout)
        if r.returncode == 2 or not m:
            return -1, f"rc={r.returncode} {r.stdout.strip()[-160:]}"
        summe += int(m.group(2))
    return summe, ""


def zurueck(sicherung: dict):
    for p, inhalt in sicherung.items():
        (ROOT / p).write_bytes(inhalt)


def main():
    fehlend = {p[1] for p in PROBEN} - set(DATEIEN)
    if fehlend:
        print(f"ABBRUCH: Dateien ohne Sicherung: {sorted(fehlend)}")
        return 2
    if MARKE.exists():
        alt = json.loads(MARKE.read_text())
        zurueck({p: bytes.fromhex(h) for p, h in alt.items()})
        MARKE.unlink()
        print("Rueckstand eines abgebrochenen Laufs zurueckgenommen.")
    sicherung = {p: (ROOT / p).read_bytes() for p in DATEIEN}
    vorher = {p: md5(p) for p in DATEIEN}
    basis, grund = lauf()
    if basis != 0:
        print(f"ABBRUCH: Basislauf nicht gruen ({basis} FAIL) {grund}")
        return 2
    print("Basislauf gruen.")
    MARKE.write_text(json.dumps({p: b.hex() for p, b in sicherung.items()}))
    stumm = 0
    try:
        for nr, (name, datei, alt, neu) in enumerate(PROBEN, 1):
            text = (ROOT / datei).read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print(f"  {nr:2d} ANKER {text.count(alt)}x  {name}")
                stumm += 1
                continue
            (ROOT / datei).write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                n, grund = lauf()
            finally:
                zurueck({datei: sicherung[datei]})
            if n > 0:
                print(f"  {nr:2d} BEISST  {n} FAIL  {name}")
            else:
                stumm += 1
                print(f"  {nr:2d} STUMM   {name} {grund}")
    finally:
        zurueck(sicherung)
        if MARKE.exists():
            MARKE.unlink()
    nachher = {p: md5(p) for p in DATEIEN}
    if nachher != vorher:
        print("ABBRUCH: Dateien nach der Gegenprobe nicht byte-gleich!")
        return 2
    print(f"\nByte-Gleichheit aller {len(DATEIEN)} Dateien per md5 bestaetigt.")
    print(f"Gegenprobe: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    return 0 if stumm == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
