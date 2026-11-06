#!/usr/bin/env python3
"""Live-Probe Befund E1 auf DEV: Sandbox MIT Internet erreicht nur oeffentliche Ziele.

Laeuft AUF DEM SERVER als root (nft lesen/setzen, runuser), im Repo-Verzeichnis:

    cd /opt/jarvis && PYTHONDONTWRITEBYTECODE=1 venv/bin/python tests/live_sandbox_netz_dev.py

Kein Token, kein Geheimnis noetig – deshalb NICHT ueber als_dienst.sh. Die Sperre
wird ueber den ECHTEN Codeweg hergestellt (``sandbox_grenzen.bereit`` –
dieselbe Funktion, die der Broker vor jedem Lauf ruft; der Broker-Prozess hat
eine eigene Kopie des Moduls, er muss also vorher neu gestartet sein, sonst
setzt erst diese Probe die Tabelle). Gemessen wird als ``jarvis_sandbox`` per
``runuser`` – also derselbe Socket-Eigentuemer wie im Lauf, ohne bwrap (bwrap
aendert am Netz-Namensraum MIT Internet nichts).

Gemessen wird nicht "Verbindung scheitert" (ein Ziel ohne Dienst scheitert
auch ohne Sperre), sondern der ZAEHLER der Abweisungsregel: er muss beim
Sandbox-Versuch steigen und beim selben Versuch als root (uid nicht in der
Sperre) NICHT – das ist die uid-Bindung, live.

Pruefungen:
  0. Positivkontrollen: root, Sandbox-Benutzer, nft, Regeln mit Zaehlern.
  1. Regelinspektion: jede Abweisung traegt meta skuid (Kernel-Sockets wie ein
     CIFS-Mount des Kernels tragen keine skuid und werden nicht getroffen),
     jedes accept steht vor der ersten Abweisung.
  2. Oeffentliches Ziel erreichbar – ERST als root gemessen (direkt oder ueber
     den eingetragenen Proxy); ohne Internet auf DEV Exit 2.
  3. DNS-Aufloesung als Sandbox-Benutzer geht (Referenz root).
  4. 10.x / 172.16.x / 192.168.x / 169.254.169.254 / Gateway / ein Ziel im
     angeschlossenen Netz (auch wenn es oeffentlich geroutet ist): Zaehler
     steigt, nicht verbunden; als root steigt er nicht. Ein interner Resolver
     bleibt auf 53 offen, auf anderen Ports zu. Die gesehenen Zusatznetze
     (broker.conf + angeschlossen) werden genannt und im geladenen Set geprueft.
  5. DNS an einen NICHT konfigurierten internen Server: Zaehler steigt.
  6. Eigene Adresse (443): als root erreichbar, als Sandbox nicht.
  7. IPv6-ULA: Zaehler steigt (ohne IPv6-Route: nicht messbar, kein FAIL).

Das oeffentliche Ziel kommt aus ``JARVIS_PROBE_OEFFENTLICH`` (Umgebung oder
.env, ``host[:port]``), sonst ``example.com:443`` (RFC 2606, kein Echtwert).
Interne Ziele sind Adressen aus den RFC-Bereichen bzw. das Gateway aus
``ip route`` – keine Echtwerte im Code.

ZUSTAND: die Probe liest beide Sandbox-Tabellen vorher und stellt sie am Ende
wieder her (gab es eine nicht, wird sie wieder entfernt; gab es sie, wird der
vorgefundene Inhalt zurueckgeschrieben).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deploy"))

_ok = _fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}" + (f"  [{detail}]" if detail else ""))
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f" – {detail}" if detail else ""))


def info(text):
    print(f"  INFO {text}")


def abbruch(text):
    print(f"ABBRUCH (Exit 2): {text}")
    sys.exit(2)


if os.geteuid() != 0:
    abbruch("muss als root auf DEV laufen")

# backend.config nur als Attrappe – sandbox_grenzen braucht es fuer diese
# Probe nicht, und der echte Import schreibt die Live-settings.json zurueck.
_cfg = types.ModuleType("backend.config")


class _C:
    def get_setting(self, k, d=None):
        return d


_cfg.config = _C()
sys.modules["backend.config"] = _cfg

from backend import sandbox_grenzen as SG  # noqa: E402

NFT = shutil.which("nft") or "/usr/sbin/nft"
RUNUSER = shutil.which("runuser") or "/usr/sbin/runuser"
SBX = SG.SBX_USER
if SG._uid(SBX) is None:
    abbruch(f"Sandbox-Benutzer {SBX} fehlt")
if not Path(NFT).exists():
    abbruch("nft fehlt")


def nft(*args, eingabe=None):
    return subprocess.run([NFT, *args], input=eingabe, capture_output=True, text=True, timeout=20)


def tabelle(name):
    r = nft("list", "table", "inet", name)
    return r.stdout if r.returncode == 0 else None


# ── Sonde: dasselbe Python-Stueck als root (Referenz) und als Sandbox ────────
SONDE = r'''
import socket, sys, errno
art, host, port, to = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
try:
    if art == "tcp":
        fam = socket.AF_INET6 if ":" in host else socket.AF_INET
        s = socket.socket(fam, socket.SOCK_STREAM); s.settimeout(to); s.connect((host, port)); print("OK")
    elif art == "udp":
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(to)
        s.sendto(b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x01", (host, port))
        s.recv(512); print("OK")
    elif art == "dns":
        print("OK " + socket.getaddrinfo(host, None)[0][4][0])
    elif art == "connect":
        ziel = sys.argv[5]
        s = socket.create_connection((host, port), to)
        s.sendall(("CONNECT %s HTTP/1.1\r\nHost: %s\r\n\r\n" % (ziel, ziel)).encode())
        print("OK " + s.recv(64).split(b"\r\n")[0].decode(errors="replace"))
except socket.timeout:
    print("TIMEOUT")
except OSError as e:
    print("ERR " + errno.errorcode.get(e.errno or 0, str(e)))
'''


def sonde(als_sandbox, *argv, to=4.0):
    roh = [str(a) for a in argv]
    roh.insert(3, str(to))
    cmd = ["/usr/bin/python3", "-I", "-c", SONDE, *roh]
    if als_sandbox:
        cmd = [RUNUSER, "-u", SBX, "--"] + cmd
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=to + 15, cwd="/")
        zeilen = (r.stdout or r.stderr or "").strip().splitlines()
        return zeilen[-1] if zeilen else "LEER"
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def zaehler(marke):
    """Summe der Pakete aller Abweisungen der Netz-Tabelle mit ``marke``."""
    t = tabelle(SG.NETZ_TABELLE) or ""
    summe = 0
    for z in t.splitlines():
        if marke in z and re.search(r"\b(reject|drop)\b", z):
            m = re.search(r"counter packets (\d+)", z)
            if m:
                summe += int(m.group(1))
    return summe


def messe_sperre(was, marke, *argv):
    """Sandbox: Zaehler steigt, nicht verbunden. root: Zaehler bleibt."""
    vor = zaehler(marke)
    aus = sonde(True, *argv)
    nach = zaehler(marke)
    pruefe(nach > vor and not aus.startswith("OK"),
           f"{was}: als {SBX} abgewiesen (Zaehler +{nach - vor})", aus)
    vor = zaehler(marke)
    aus_r = sonde(False, *argv, to=2.0)
    nach = zaehler(marke)
    pruefe(nach == vor, f"{was}: als root NICHT von der Sperre erfasst (uid-Bindung)", aus_r)


# ── Vorzustand sichern ──────────────────────────────────────────────────────
VORHER = {t: tabelle(t) for t in (SG.NETZ_TABELLE, SG.NFT_TABELLE)}
info("vorgefunden: " + ", ".join(f"{t}={'da' if v else 'fehlt'}" for t, v in VORHER.items()))


def wiederherstellen():
    for t, alt in VORHER.items():
        if alt is None:
            if tabelle(t) is not None:
                r = nft("delete", "table", "inet", t)
                print(f"  zurueck: {t} entfernt (rc={r.returncode})")
        else:
            r = nft("-f", "-", eingabe=f"table inet {t} {{}}\ndelete table inet {t}\n{alt}")
            print(f"  zurueck: {t} vorgefundener Inhalt wieder gesetzt (rc={r.returncode} "
                  f"{(r.stderr or '').strip()[:120]})")


try:
    print("\n── 0. Sperre ueber den echten Codeweg herstellen ─────────────────")
    ok, grund = SG.bereit(SBX)
    pruefe(ok, "sandbox_grenzen.bereit(jarvis_sandbox) im echten Prozess", grund)
    ok2, grund2 = SG.netz_sperre_sicherstellen(erzwingen=True)
    if not ok2:
        abbruch(f"Netz-Sperre nicht setzbar: {grund2}")
    TEXT = tabelle(SG.NETZ_TABELLE) or ""
    if "counter packets" not in TEXT:
        abbruch("Netz-Tabelle ohne Zaehler – Messpunkt fehlt (alter Stand?)")
    info("DNS-Ausnahme fuer: %s" % (SG.resolver_lesen() or "-"))
    PROXYS = SG.proxy_ziele()
    info("Proxy-Ausnahme fuer: %s" % (PROXYS or "-"))
    KONF_NETZE = SG.konf_intern_netze()
    ANG_NETZE = SG.angeschlossene_netze()
    info(f"Zusatznetze aus {SG.BROKER_CONF} ({SG.KONF_INTERN_NETZE}): {KONF_NETZE or '-'}")
    info(f"angeschlossene Netze + Gateway (automatisch): {ANG_NETZE or '-'}")
    SET4 = re.search(r"set intern4 \{.*?elements = \{([^}]*)\}", TEXT, re.S)
    for n in KONF_NETZE + ANG_NETZE:
        nn = ipaddress.ip_network(n)
        if nn.version == 4 and SET4:
            drin = any(nn.subnet_of(ipaddress.ip_network(x.strip()))
                       for x in SET4.group(1).split(",") if x.strip())
            pruefe(drin, f"Zusatznetz {n} steht im geladenen Set intern4")

    print("\n── 1. Regelinspektion (CIFS/Kernel-Sockets) ─────────────────────")
    regeln = [z.strip() for z in TEXT.splitlines()
              if z.strip().startswith("meta ") or " accept" in z or "reject" in z]
    abw = [i for i, z in enumerate(regeln) if re.search(r"\b(reject|drop)\b", z)]
    acc = [i for i, z in enumerate(regeln) if z.endswith("accept")]
    pruefe(abw and all("meta skuid" in regeln[i] for i in abw),
           "jede Abweisung traegt meta skuid (Kernel-Sockets ohne Eigentuemer bleiben frei)")
    pruefe(abw and (not acc or max(acc) < min(abw)), "jedes accept steht vor der ersten Abweisung")
    pruefe("policy drop" not in TEXT, "keine policy drop")
    try:
        cifs = [z.split()[1] for z in Path("/proc/mounts").read_text().splitlines()
                if len(z.split()) > 2 and z.split()[2] in ("cifs", "smb3", "nfs", "nfs4")]
    except OSError:
        cifs = []
    info(f"Netz-Mounts des Kernels aktuell: {len(cifs)} (nicht angefasst; Schutz = skuid-Bindung oben)")

    print("\n── 2. Oeffentliches Ziel (erst als root messen) ─────────────────")
    try:
        from ziele import finde
        ziel = finde("JARVIS_PROBE_OEFFENTLICH") or "example.com:443"
    except Exception:  # noqa: BLE001
        ziel = "example.com:443"
    host, _, port = ziel.partition(":")
    port = int(port or 443)
    ref = sonde(False, "tcp", host, port, to=6.0)
    weg = None
    if ref.startswith("OK"):
        weg = "direkt"
        aus = sonde(True, "tcp", host, port, to=6.0)
        pruefe(aus.startswith("OK"), f"{host}:{port} direkt erreichbar als {SBX}", aus)
    else:
        info(f"root erreicht {host}:{port} nicht direkt ({ref}) – versuche Proxy")
        for padr, pport in PROXYS:
            r = sonde(False, "connect", padr, pport, f"{host}:{port}", to=8.0)
            if " 200" in r:
                weg = f"Proxy {padr}:{pport}"
                aus = sonde(True, "connect", padr, pport, f"{host}:{port}", to=8.0)
                pruefe(" 200" in aus, f"{host}:{port} ueber {weg} erreichbar als {SBX}", aus)
                break
    if weg is None:
        abbruch(f"DEV erreicht {host}:{port} auch als root nicht (direkt: {ref}; Proxys: {PROXYS or '-'}) "
                "– Positivkontrolle unmoeglich")

    print("\n── 3. DNS-Aufloesung ────────────────────────────────────────────")
    ref = sonde(False, "dns", host, 0)
    if ref.startswith("OK"):
        aus = sonde(True, "dns", host, 0)
        pruefe(aus.startswith("OK"), f"{host} wird als {SBX} aufgeloest", aus)
    else:
        info(f"auch root loest {host} nicht auf ({ref}) – DNS laeuft hier nur ueber den Proxy")

    print("\n── 4. Interne Ziele ─────────────────────────────────────────────")
    netz = ipaddress.ip_network
    proben = [
        ("10.0.0.0/8", str(netz("10.0.0.0/8").broadcast_address - 1)),
        ("172.16.0.0/12", str(netz("172.16.0.0/12").broadcast_address - 1)),
        ("192.168.0.0/16", str(netz("192.168.0.0/16").broadcast_address - 1)),
        ("Cloud-Metadaten", str(netz("169.254.0.0/16")[0] + (169 << 8 | 254))),
    ]
    try:
        rt = json.loads(subprocess.run(["ip", "-j", "-4", "route", "show", "default"],
                                       capture_output=True, text=True, timeout=10).stdout or "[]")
        gw = next((r.get("gateway") for r in rt if r.get("gateway")), None)
    except Exception:  # noqa: BLE001
        gw = None
    # Nachbesserung: das Gateway ist jetzt IMMER Ziel – auch in einem
    # oeffentlich gerouteten Firmenblock (dort lag es bei der ersten Messung).
    if gw:
        proben.append(("Gateway", gw))
    else:
        info("kein Default-Gateway gefunden – nicht gemessen")
    erlaubt = {a for a, _ in PROXYS} | set(SG.resolver_lesen())
    try:
        adr_j = json.loads(subprocess.run(["ip", "-j", "-4", "addr", "show", "scope", "global"],
                                          capture_output=True, text=True, timeout=10).stdout or "[]")
        eigene_alle = {a.get("local") for i in adr_j for a in i.get("addr_info", [])}
    except Exception:  # noqa: BLE001
        eigene_alle = set()
    # Ein Ziel im angeschlossenen Netz, das weder eigene Adresse noch Gateway,
    # Resolver oder Proxy ist (Netzadresse+1, +2, …).
    for n in ANG_NETZE:
        nn = ipaddress.ip_network(n)
        if nn.version != 4 or nn.num_addresses < 4:
            continue
        kand = next((str(nn.network_address + k) for k in range(1, 9)
                     if str(nn.network_address + k) not in eigene_alle | erlaubt | {gw}), None)
        if kand:
            proben.append((f"angeschlossenes Netz {n}", kand))
            break
    else:
        info("kein angeschlossenes IPv4-Netz mit freiem Ziel gefunden")
    for was, adr in proben:
        if adr in erlaubt:
            info(f"{was} {adr} ist Resolver/Proxy – bewusst erlaubt (nur Port 53 bzw. Proxy-Port), "
                 "Probe auf geschlossenem Port")
            messe_sperre(f"{was} ({adr}:9, Resolver ausserhalb 53)", "@intern4", "tcp", adr, 9)
            continue
        # Port 9 (discard): auf Gateway/Fremdrechnern i. d. R. geschlossen – gemessen
        # wird ohnehin der Zaehler, nicht die Antwort.
        messe_sperre(f"{was} ({adr}:9)", "@intern4", "tcp", adr, 9)
    for r in [x for x in SG.resolver_lesen() if ipaddress.ip_address(x).version == 4
              and not ipaddress.ip_address(x).is_loopback][:1]:
        vor = zaehler("@intern4")
        aus = sonde(True, "udp", r, 53)
        nach = zaehler("@intern4")
        pruefe(nach == vor, f"Resolver {r}:53 bleibt fuer {SBX} offen (kein Treffer der Sperre)", aus)

    print("\n── 5. DNS an einen nicht konfigurierten internen Server ─────────")
    fremd = str(ipaddress.ip_network("10.0.0.0/8").broadcast_address - 2)
    if fremd not in erlaubt:
        messe_sperre(f"udp {fremd}:53", "@intern4", "udp", fremd, 53)

    print("\n── 6. Eigene Adresse ────────────────────────────────────────────")
    try:
        adr = json.loads(subprocess.run(["ip", "-j", "-4", "addr", "show", "scope", "global"],
                                        capture_output=True, text=True, timeout=10).stdout or "[]")
        eigene = next((a["local"] for i in adr for a in i.get("addr_info", []) if a.get("local")), None)
    except Exception:  # noqa: BLE001
        eigene = None
    if eigene:
        ref = sonde(False, "tcp", eigene, 443)
        if ref.startswith("OK"):
            aus = sonde(True, "tcp", eigene, 443)
            pruefe(not aus.startswith("OK"), "eigene Adresse :443 als Sandbox nicht erreichbar "
                   "(root erreicht sie)", aus)
        else:
            info(f"eigene Adresse :443 auch als root nicht erreichbar ({ref}) – nicht messbar")
    else:
        info("keine globale IPv4-Adresse gefunden – nicht gemessen")

    print("\n── 7. IPv6 (ULA) ────────────────────────────────────────────────")
    ula = str(ipaddress.ip_network("fd00::/8")[1])
    vor = zaehler("@intern6")
    aus = sonde(True, "tcp", ula, 80)
    nach = zaehler("@intern6")
    if nach > vor:
        pruefe(not aus.startswith("OK"), f"{ula}:80 als Sandbox abgewiesen (Zaehler +{nach - vor})", aus)
    elif "ENETUNREACH" in aus or "EADDRNOTAVAIL" in aus:
        info(f"keine IPv6-Route ({aus}) – IPv6 hier nicht messbar, Regeln siehe Abschnitt 1")
    else:
        pruefe(False, f"{ula}:80: Zaehler stieg nicht", aus)
finally:
    print("\n── Zustand wiederherstellen ─────────────────────────────────────")
    wiederherstellen()
    jetzt = {t: tabelle(t) for t in VORHER}
    gleich = all((VORHER[t] is None) == (jetzt[t] is None) for t in VORHER)
    print(f"  Tabellen wie vorgefunden vorhanden/abwesend: {'ja' if gleich else 'NEIN'}")
    if not gleich:
        _fail += 1

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
