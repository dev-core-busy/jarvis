#!/usr/bin/env python3
"""Befund E1 – Sandbox MIT Internet erreicht nur oeffentliche Ziele.

Ein Sandbox-Lauf mit Internet teilt den Netz-Namensraum des Hosts. Bis zu
diesem Fix sperrte nftables fuer ihn nur ``oif lo``; RFC1918, CGNAT,
Link-Local (Cloud-Metadaten), Multicast und die IPv6-Gegenstuecke waren
erreichbar. Gemessen wird – an der ECHTEN Erzeugerfunktion, nicht am Text des
Moduls:

1. ``netz_regeln``: die Sets decken jede nicht-globale Adresse ab (Orakel:
   ``ipaddress.is_global``), lassen globale frei (bis auf benannte, bewusst
   gesperrte Altbereiche) und ueberschneiden sich nicht (nftables lehnt das ab).
2. Kette: jedes ``accept`` steht VOR der ersten Abweisung, jede Abweisung ist an
   genau die Sandbox-UIDs gebunden (Kernel-Sockets wie CIFS tragen keine skuid
   und bleiben unberuehrt), keine ``policy drop``.
3. DNS nur zu den konfigurierten Resolvern, kein pauschales Port-53-Loch;
   Proxy aus der Umgebung bleibt erreichbar.
4. ``resolver_lesen`` / ``proxy_ziele`` an Probedateien.
5. ``netz_sperre_sicherstellen``: setzt GENAU den Text von ``netz_regeln``,
   Frist-Cache, Fehlschlag wird nicht gemerkt, ohne root kein "gesetzt".
6. ``bereit()``: fehlt die Netz-Sperre, kein Lauf MIT Netz – ohne Netz weiter.
7. Broker-Op ``sandbox_lauf`` reicht ``ohne_netz`` an ``bereit()`` (ausgefuehrt
   und am Syntaxbaum).
8. Nachbesserung (DEV: Firmennetz oeffentlich geroutet, kein RFC1918):
   ``SANDBOX_INTERN_NETZE`` aus broker.conf (letzte Zeile gewinnt, ungueltig
   und /0 verworfen mit Journal-Zeile), angeschlossene Netze + Gateway
   automatisch, Resolver im gesperrten Block NUR auf 53, ueberlappende
   Bereiche zusammengefuehrt.

Es laeuft KEIN nft: ``subprocess.run`` wird in Abschnitt 5 durch eine Attrappe
ersetzt, und ``backend.config`` ist eine Attrappe (der echte Import schreibt die
Live-settings.json zurueck).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.

    PYTHONDONTWRITEBYTECODE=1 venv/bin/python tests/test_sandbox_netz.py
"""
import ast
import ipaddress
import os
import pwd as _pwd
import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f" – {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n── {t} " + "─" * max(0, 66 - len(t)))


def abbruch(text):
    print(f"ABBRUCH: {text}")
    sys.exit(2)


SANDKASTEN = Path(tempfile.mkdtemp(prefix="jarvis_e1_"))
_cfg_mod = types.ModuleType("backend.config")


class _Config:
    SETTINGS_FILE = SANDKASTEN / "settings.json"

    def get_setting(self, key, default=None):
        return default

    def save_setting(self, key, value):
        pass


_cfg_mod.config = _Config()
sys.modules["backend.config"] = _cfg_mod

try:
    from backend import sandbox_grenzen as SG
    from backend import lauf_tmp as LT
    from backend.broker import ops as OPS
except Exception as e:  # noqa: BLE001
    abbruch(f"Module nicht importierbar: {type(e).__name__}: {e}")
if sys.modules.get("backend.config") is not _cfg_mod:
    abbruch("backend.config ist nicht die Attrappe")
for name in ("netz_regeln", "netz_sperre_sicherstellen", "resolver_lesen", "proxy_ziele",
             "konf_intern_netze", "angeschlossene_netze", "sperrmengen"):
    if not callable(getattr(SG, name, None)):
        abbruch(f"sandbox_grenzen.{name} fehlt")

UIDS = [995, 996]
# Oeffentlich geroutete Probenetze, BERECHNET statt als Literal (kein Echtwert
# im Repo; die Regel "keine IP-Adressen" gilt fuer Werte aus dem Betrieb).
OEFF4 = ipaddress.IPv4Network((0x2C100000, 20))       # liegt in keinem RFC-Bereich
OEFF4_B = ipaddress.IPv4Network((0x2C200000, 24))
OEFF6 = ipaddress.IPv6Network((0x2A0F << 112, 32))
if any(n.is_private or not n.network_address.is_global for n in (OEFF4, OEFF4_B, OEFF6)):
    abbruch("Probenetze sind nicht global – Messung waere trivial")


def zerlegen(text):
    """(sets, regeln): Set-Elemente je Name und die Regelzeilen der Kette."""
    sets = {}
    for m in re.finditer(r"set (\w+) \{(.*?)\n    \}", text, re.S):
        e = re.search(r"elements = \{([^}]*)\}", m.group(2))
        sets[m.group(1)] = [x.strip() for x in (e.group(1) if e else "").split(",") if x.strip()]
    regeln, in_kette = [], False
    for z in text.splitlines():
        s = z.strip()
        if s.startswith("chain out"):
            in_kette = True
            continue
        if in_kette and s.startswith("type filter"):
            continue
        if in_kette and s == "}":
            in_kette = False
            continue
        if in_kette and s:
            regeln.append(s)
    return sets, regeln


def netze(liste):
    aus = []
    for x in liste:
        try:
            aus.append(ipaddress.ip_network(x, strict=True))
        except ValueError:
            aus.append(None)
    return aus


def gedeckt(adr, liste):
    a = ipaddress.ip_address(adr)
    return any(n is not None and a.version == n.version and a in n for n in liste)


def ist_abweisung(z):
    return bool(re.search(r"\b(reject|drop)\b", z))


def skuid_menge(z):
    m = re.search(r"meta skuid \{([^}]*)\}", z)
    if not m:
        return None
    try:
        return sorted(int(x) for x in m.group(1).split(","))
    except ValueError:
        return None


# ── Positivkontrolle der Zerlegung ──────────────────────────────────────────
TEXT = SG.netz_regeln(UIDS, ["127.0.0.53"], [("10.9.8.7", 3128)])
SETS, REGELN = zerlegen(TEXT)
if not REGELN or "intern4" not in SETS or "intern6" not in SETS:
    abbruch("Regeltext nicht zerlegbar (keine Kette oder keine Sets) – Messwerk blind")
if not any("accept" in z for z in REGELN) or not any(ist_abweisung(z) for z in REGELN):
    abbruch("Zerlegung findet weder accept noch Abweisung – Messwerk blind")
N4, N6 = netze(SETS["intern4"]), netze(SETS["intern6"])

abschnitt("1. Abgedeckte Bereiche (Orakel ipaddress.is_global)")
pruefe(all(n is not None for n in N4 + N6), "alle Set-Elemente sind gueltige Netze",
       str([x for x, n in zip(SETS["intern4"] + SETS["intern6"], N4 + N6) if n is None]))
_basis = [ipaddress.ip_network(x) for x in SG.INTERN_V4 + SG.INTERN_V6]
pruefe(all(any(n is not None and b.version == n.version and b.subnet_of(n) for n in N4 + N6) for b in _basis),
       "jeder RFC-Bereich aus INTERN_V4/INTERN_V6 liegt in den Sets")
pruefe(not any("." in x for x in SETS["intern6"]), "IPv6-Set ohne Mischschreibweise (::ffff:a.b.c.d)",
       str(SETS["intern6"]))


def ueberschneidungen(liste):
    ok = [n for n in liste if n is not None]
    return [(str(a), str(b)) for i, a in enumerate(ok) for b in ok[i + 1:] if a.overlaps(b)]


pruefe(not ueberschneidungen(N4) and not ueberschneidungen(N6),
       "keine Ueberschneidung (nftables-Intervallset lehnt sie ab)",
       str(ueberschneidungen(N4) + ueberschneidungen(N6)))

# Ausdruecklich genannte Ziele des Befunds (je eine Probe je Bereich).
for adr, was in (("10.20.30.40", "RFC1918 10/8"), ("172.16.0.1", "RFC1918 172.16/12 Anfang"),
                 ("172.31.255.254", "RFC1918 172.16/12 Ende"), ("192.168.178.1", "RFC1918 192.168/16"),
                 ("100.64.0.1", "CGNAT"), ("100.127.255.254", "CGNAT Ende"),
                 ("169.254.169.254", "Cloud-Metadaten"), ("127.0.0.1", "Loopback"),
                 ("224.0.0.251", "Multicast"), ("239.255.255.250", "Multicast SSDP"),
                 ("255.255.255.255", "Broadcast"), ("0.0.0.0", "dieses Netz")):
    pruefe(gedeckt(adr, N4), f"v4 gesperrt: {was}")
for adr, was in (("fd00::1", "ULA fd00::/8"), ("fc00::1", "ULA fc00::/8"), ("fe80::1", "Link-Local"),
                 ("::1", "Loopback"), ("::", "unspezifiziert"), ("ff02::1", "Multicast"),
                 ("::ffff:10.0.0.1", "IPv4-mapped RFC1918"), ("::ffff:169.254.169.254", "IPv4-mapped Metadaten")):
    pruefe(gedeckt(adr, N6), f"v6 gesperrt: {was}")

# Orakel ueber ein Raster: jede nicht-globale und jede Multicast-Adresse muss
# gedeckt sein, jede andere globale frei – bis auf benannte Altbereiche, die bewusst mitgesperrt sind.
BEWUSST = [ipaddress.ip_network(x) for x in (
    "192.0.0.0/24",    # IETF-Protokollzuweisungen; nur .9/.10 sind "global" (Anycast-Dienste)
    "192.88.99.0/24",  # 6to4-Relay, RFC 7526 abgekuendigt
    "fec0::/10",       # Site-Local, RFC 3879 abgekuendigt
)]
raster4 = []
for x in range(256):
    for rest in ((0, 0, 1), (16, 5, 5), (64, 0, 1), (88, 99, 1), (168, 1, 1), (254, 169, 254),
                 (255, 255, 255), (51, 100, 7), (0, 113, 9), (18, 0, 1), (19, 255, 1), (0, 2, 3)):
        raster4.append(ipaddress.IPv4Address(bytes([x, *rest])))
raster6 = [ipaddress.IPv6Address(p << 112 | 1) for p in range(0, 0x10000, 0x40)]
raster6 += [ipaddress.IPv6Address(int(ipaddress.IPv6Address(b)) + 7) for b in
            ("fc00::", "fd00::", "fe80::", "fec0::", "ff00::", "ff0e::", "2001::", "2001:db8::",
             "2002::", "64:ff9b:1::", "100::", "::ffff:0:0")]
fehlt, zuviel = [], []
for a in raster4 + raster6:
    ziel = N4 if a.version == 4 else N6
    # Multicast gilt fuer ipaddress als "global", ist aber laut Befund zu.
    intern = (not a.is_global) or a.is_multicast
    if intern and not gedeckt(str(a), ziel):
        fehlt.append(str(a))
    if not intern and gedeckt(str(a), ziel) and not any(a in b for b in BEWUSST if b.version == a.version):
        zuviel.append(str(a))
pruefe(len(raster4) > 3000 and len(raster6) > 1000, "Positivkontrolle: Raster ist dicht",
       f"{len(raster4)}/{len(raster6)}")
pruefe(not fehlt, "jede nicht-globale Rasteradresse ist gesperrt", ", ".join(fehlt[:12]))
pruefe(not zuviel, "keine globale Rasteradresse gesperrt (Internet bleibt erreichbar)", ", ".join(zuviel[:12]))

abschnitt("2. Kette: Reihenfolge und uid-Bindung")
erste_abw = next((i for i, z in enumerate(REGELN) if ist_abweisung(z)), None)
accepts = [i for i, z in enumerate(REGELN) if z.endswith("accept")]
pruefe(erste_abw is not None and accepts and max(accepts) < erste_abw,
       "jedes accept steht VOR der ersten Abweisung", str(REGELN))
abw = [z for z in REGELN if ist_abweisung(z)]
pruefe(abw and all(skuid_menge(z) == UIDS for z in abw),
       "jede Abweisung traegt meta skuid mit genau den Sandbox-UIDs (Kernel-Sockets frei)",
       str([z for z in abw if skuid_menge(z) != UIDS]))
pruefe(all(skuid_menge(z) == UIDS for z in REGELN if z.endswith("accept")),
       "auch die Ausnahmen sind uid-gebunden")
for treffer in ('oif "lo"', "ip daddr @intern4", "ip6 daddr @intern6"):
    pruefe(any(treffer in z for z in abw), f"Abweisung vorhanden fuer {treffer}")
pruefe(all("counter" in z for z in abw), "jede Abweisung zaehlt (Messpunkt der Live-Probe)")
pruefe("policy accept" in TEXT and "policy drop" not in TEXT, "keine policy drop (Kette trifft nur Sandbox-UIDs)")
pruefe(f"delete table inet {SG.NETZ_TABELLE}" in TEXT and TEXT.count(f"table inet {SG.NETZ_TABELLE}") == 3,
       "atomarer Ersatz (anlegen, loeschen, neu)")
pruefe(SG.NETZ_TABELLE != SG.NFT_TABELLE, "eigene Tabelle neben der Loopback-Sperre")
pruefe("hook output" in TEXT and "insert" not in TEXT and "add rule" not in TEXT,
       "Kette am output-Hook, als ganze Tabelle gesetzt (kein add/insert hinter fremde Regeln)")

abschnitt("3. DNS nur zum Resolver, Proxy erreichbar")


def dns_regeln(text):
    return [z for z in zerlegen(text)[1] if "dport 53" in z]


d = dns_regeln(TEXT)
pruefe(len(d) == 2 and all("ip daddr { 127.0.0.53 }" in z and z.endswith("accept") for z in d),
       "lokaler Stub: udp+tcp 53 nur zu 127.0.0.53", str(d))
t2 = SG.netz_regeln(UIDS, ["10.1.2.3", "fd00::53"], [])
d2 = dns_regeln(t2)
pruefe(len(d2) == 4 and all(("daddr { 10.1.2.3 }" in z) or ("daddr { fd00::53 }" in z) for z in d2),
       "interner Resolver v4+v6: genau diese Adressen", str(d2))
pruefe(all("daddr" in z for z in d + d2), "keine Port-53-Ausnahme ohne Zieladresse")
pruefe(not dns_regeln(SG.netz_regeln(UIDS, [], [])), "ohne Resolver keine DNS-Ausnahme")
_, r_ohne = zerlegen(SG.netz_regeln(UIDS, [], []))
pruefe(r_ohne and all(ist_abweisung(z) for z in r_ohne), "ohne Resolver/Proxy: nur Abweisungen")
prx = [z for z in REGELN if "10.9.8.7" in z]
pruefe(len(prx) == 1 and "tcp dport 3128 accept" in prx[0], "Proxy 10.9.8.7:3128 erlaubt", str(prx))
t6 = SG.netz_regeln(UIDS, [], [("fd00::3128", 8080)])
pruefe(any("ip6 daddr fd00::3128 tcp dport 8080 accept" in z for z in zerlegen(t6)[1]),
       "IPv6-Proxy mit ip6 daddr")

abschnitt("4. Resolver und Proxy lesen")
rc = SANDKASTEN / "resolv.conf"
rc.write_text("# Kommentar\nsearch beispiel.de\nnameserver 127.0.0.53\nnameserver fe80::1%eth0\n"
              "nameserver kaputt\nnameserver 127.0.0.53\noptions edns0\n")
r = SG.resolver_lesen(str(rc))
pruefe(r == ["127.0.0.53", "fe80::1"], "resolv.conf: gueltige, ohne Zone, ohne Doppelte", str(r))
pruefe(SG.resolver_lesen(str(SANDKASTEN / "fehlt")) == [], "fehlende Datei -> leer")
envd = SANDKASTEN / "environment"
envd.write_text('HTTPS_PROXY="http://proxy.beispiel.de:3128/"\nPATH=/usr/bin\n')
fake = {"proxy.beispiel.de": ["10.9.8.7"]}
ziele = SG.proxy_ziele(umgebung={"http_proxy": "http://nutzer:geheim@proxy.beispiel.de:3128",
                                  "ALL_PROXY": "socks5h://192.0.2.5", "NO_PROXY": "10.0.0.0/8",
                                  "ftp_proxy": "192.0.2.6:2121"},
                       env_datei=str(envd), aufloesen=lambda h: fake.get(h, []))
pruefe(("10.9.8.7", 3128) in ziele, "Proxy mit Anmeldedaten und Hostnamen", str(ziele))
pruefe(("192.0.2.5", 1080) in ziele, "socks5h ohne Port -> 1080", str(ziele))
pruefe(("192.0.2.6", 2121) in ziele, "ohne Schema -> http, Port uebernommen", str(ziele))
pruefe(len(ziele) == 3, "keine Doppelten, NO_PROXY ist kein Ziel", str(ziele))
pruefe(SG.proxy_ziele(umgebung={}, env_datei=str(envd), aufloesen=lambda h: fake.get(h, []))
       == [("10.9.8.7", 3128)], "/etc/environment wird gelesen")
pruefe(SG.proxy_ziele(umgebung={"https_proxy": "http://unbekannt.beispiel.de:1"},
                      env_datei=str(SANDKASTEN / "fehlt"), aufloesen=lambda h: []) == [],
       "nicht aufloesbarer Proxy -> keine Ausnahme")

abschnitt("5. netz_sperre_sicherstellen (Attrappe statt nft)")


class _OsRoot:
    def __getattr__(self, n):
        return getattr(os, n)

    @staticmethod
    def geteuid():
        return 0


class _R:
    def __init__(self, rc, err=""):
        self.returncode, self.stdout, self.stderr = rc, "", err


AUFRUFE = []
_rc = {"rc": 0}


def _run(cmd, input=None, **k):
    AUFRUFE.append((list(cmd), input))
    return _R(_rc["rc"], "Error: kaputt" if _rc["rc"] else "")


_sicher = {k: getattr(SG, k) for k in ("os", "sandbox_uids", "resolver_lesen", "proxy_ziele",
                                       "konf_intern_netze", "angeschlossene_netze")}
_sicher_sp = SG.subprocess.run
try:
    SG.os = _OsRoot()
    SG.subprocess.run = _run
    SG.sandbox_uids = lambda: list(UIDS)
    SG.resolver_lesen = lambda pfad=None: ["10.1.2.3"]
    SG.proxy_ziele = lambda *a, **k: [("10.9.8.7", 3128)]
    SG.konf_intern_netze = lambda *a, **k: [str(OEFF4)]
    SG.angeschlossene_netze = lambda *a, **k: [str(OEFF4_B)]
    SG._netz_stand.update(zeit=0.0, schluessel=None)
    ok, grund = SG.netz_sperre_sicherstellen()
    pruefe(ok is True and len(AUFRUFE) == 1, "Positivkontrolle: gesetzt, ein nft-Aufruf", f"{ok} {grund} {len(AUFRUFE)}")
    pruefe(AUFRUFE and AUFRUFE[0][0][-2:] == ["-f", "-"]
           and AUFRUFE[0][1] == SG.netz_regeln(UIDS, ["10.1.2.3"], [("10.9.8.7", 3128)],
                                               [str(OEFF4), str(OEFF4_B)]),
           "gesetzt wird GENAU der Text von netz_regeln (Resolver, Proxy, Konfig- + angeschlossene Netze)")
    SG.netz_sperre_sicherstellen()
    pruefe(len(AUFRUFE) == 1, "innerhalb der Frist kein zweiter Aufruf")
    SG.angeschlossene_netze = lambda *a, **k: [str(OEFF4_B), str(OEFF4)]
    SG.netz_sperre_sicherstellen(erzwingen=True)
    pruefe(AUFRUFE[-1][1] == SG.netz_regeln(UIDS, ["10.1.2.3"], [("10.9.8.7", 3128)],
                                            [str(OEFF4), str(OEFF4_B)]),
           "Netz aus Konfiguration UND angeschlossen: einmal, Konfiguration zuerst")
    AUFRUFE.pop()
    SG.netz_sperre_sicherstellen(erzwingen=True)
    pruefe(len(AUFRUFE) == 2, "erzwingen setzt neu")
    SG.sandbox_uids = lambda: UIDS + [997]
    SG.netz_sperre_sicherstellen()
    pruefe(len(AUFRUFE) == 3 and "997" in (AUFRUFE[-1][1] or ""), "neue UID -> sofort neu gesetzt")
    _rc["rc"] = 1
    ok, grund = SG.netz_sperre_sicherstellen(erzwingen=True)
    pruefe(ok is False and "kaputt" in grund, "nft-Fehler -> nicht gesetzt, mit Grund", grund)
    _rc["rc"] = 0
    n = len(AUFRUFE)
    ok, _ = SG.netz_sperre_sicherstellen()
    pruefe(ok is True and len(AUFRUFE) == n + 1, "nach Fehlschlag wird nicht aus dem Cache geantwortet")
    SG.sandbox_uids = lambda: []
    pruefe(SG.netz_sperre_sicherstellen(erzwingen=True)[0] is False, "ohne Sandbox-UID nicht gesetzt")
    SG.os = os
    if os.geteuid() != 0:
        ok, grund = SG.netz_sperre_sicherstellen(erzwingen=True)
        pruefe(ok is False and "root" in grund, "ohne root nicht als gesetzt gemeldet")
finally:
    for k, v in _sicher.items():
        setattr(SG, k, v)
    SG.subprocess.run = _sicher_sp
    SG._netz_stand.update(zeit=0.0, schluessel=None)

abschnitt("6. bereit(): Netz-Sperre fuer Laeufe MIT Netz Pflicht")
_sicher = {k: getattr(SG, k) for k in ("os", "SYSTEMD_RUN", "lo_sperre_sicherstellen",
                                       "netz_sperre_sicherstellen", "_uid")}
_sicher_lt = {k: getattr(LT, k) for k in ("bwrap_verfuegbar", "isolation_gewuenscht")}
_sr = SANDKASTEN / "systemd-run"
_sr.write_text("")
NUIDS = {SG.SBX_USER: 995, SG.NOINET_USER: 996}
_netz = {"v": (True, ""), "n": 0}


def _netz_attrappe(*a, **k):
    _netz["n"] += 1
    return _netz["v"]


try:
    SG.os = _OsRoot()
    SG.SYSTEMD_RUN = str(_sr)
    SG._uid = lambda n: NUIDS.get(n)
    LT.bwrap_verfuegbar = lambda *a, **k: True
    LT.isolation_gewuenscht = lambda: True
    SG.lo_sperre_sicherstellen = lambda *a, **k: (True, "")
    SG.netz_sperre_sicherstellen = _netz_attrappe
    pruefe(SG.bereit(SG.SBX_USER) == (True, "") and _netz["n"] == 1,
           "Positivkontrolle: alles da -> bereit, Netz-Sperre wurde geprueft")
    _netz["v"] = (False, "Sperre interner Netze nicht setzbar")
    ok, grund = SG.bereit(SG.SBX_USER)
    pruefe(ok is False and "interner Netze" in grund, "Netz-Sperre fehlt -> kein Lauf MIT Netz", repr(grund))
    pruefe(SG.bereit(SG.SBX_USER, ohne_netz=False)[0] is False, "… auch bei ausdruecklich ohne_netz=False")
    pruefe(SG.bereit(SG.SBX_USER, ohne_netz=True) == (True, ""), "… Lauf OHNE Netz laeuft weiter")
    pruefe(SG.bereit(SG.NOINET_USER) == (True, ""), "netzgesperrter Standardbenutzer: Vorgabe ohne Netz")
    pruefe(SG.bereit(SG.NOINET_USER, ohne_netz=False)[0] is False,
           "netzgesperrter Benutzer, aber ausdruecklich MIT Netz -> Sperre verlangt")
    SG.lo_sperre_sicherstellen = lambda *a, **k: (False, "Loopback-Sperre nicht setzbar")
    _netz["v"] = (True, "")
    pruefe(SG.bereit(SG.SBX_USER, ohne_netz=True)[0] is False, "Loopback-Sperre bleibt Pflicht fuer alle")
finally:
    for k, v in _sicher.items():
        setattr(SG, k, v)
    for k, v in _sicher_lt.items():
        setattr(LT, k, v)

abschnitt("7. Broker-Op reicht ohne_netz an bereit()")
_sicher_b = SG.bereit
_sicher_pw = _pwd.getpwnam
GESEHEN = []


class _Pw:
    def __init__(self, uid):
        self.pw_uid = uid


try:
    _pwd.getpwnam = lambda n: _Pw(NUIDS[n]) if n in NUIDS else (_ for _ in ()).throw(KeyError(n))
    SG.bereit = lambda u, ohne_netz=None: (GESEHEN.append((u, ohne_netz)), (False, "Attrappe: nicht bereit"))[1]
    r1 = OPS._op_sandbox_lauf({"user": SG.SBX_USER, "command": "true", "ohne_netz": False}, None)
    r2 = OPS._op_sandbox_lauf({"user": SG.SBX_USER, "command": "true", "ohne_netz": True}, None)
    r3 = OPS._op_sandbox_lauf({"user": SG.NOINET_USER, "command": "true"}, None)
    pruefe(len(GESEHEN) == 3, "Positivkontrolle: bereit() wurde dreimal gerufen", str(GESEHEN))
    pruefe(GESEHEN[:1] == [(SG.SBX_USER, False)], "MIT Netz -> bereit(ohne_netz=False)", str(GESEHEN))
    pruefe(GESEHEN[1:2] == [(SG.SBX_USER, True)], "ohne_netz -> bereit(ohne_netz=True)", str(GESEHEN))
    pruefe(GESEHEN[2:3] == [(SG.NOINET_USER, True)], "netzgesperrter Benutzer -> immer ohne Netz", str(GESEHEN))
    pruefe(all(isinstance(r, dict) and r.get("abgelehnt") for r in (r1, r2, r3)),
           "nicht bereit -> abgelehnt")
finally:
    SG.bereit = _sicher_b
    _pwd.getpwnam = _sicher_pw

baum = ast.parse((ROOT / "backend/broker/ops.py").read_text(encoding="utf-8"))
fn = next((n for n in ast.walk(baum) if isinstance(n, ast.FunctionDef) and n.name == "_op_sandbox_lauf"), None)
aufruf = zuweisung = None
if fn is not None:
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "bereit"):
            aufruf = n
        if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ohne_netz" for t in n.targets)):
            zuweisung = zuweisung or n
kw = {k.arg: k.value for k in (aufruf.keywords if aufruf else [])}
pruefe(aufruf is not None and isinstance(kw.get("ohne_netz"), ast.Name) and kw["ohne_netz"].id == "ohne_netz",
       "AST: bereit(..., ohne_netz=ohne_netz)")
pruefe(aufruf is not None and zuweisung is not None and zuweisung.lineno < aufruf.lineno,
       "AST: ohne_netz steht VOR der Pruefung fest")

abschnitt("8. Zusaetzliche interne Netze (oeffentlich gerouteter Firmenblock)")
import contextlib  # noqa: E402
import io  # noqa: E402

konf = SANDKASTEN / "broker.conf"
# Der Schluessel steht hier ABSICHTLICH als Literal: er ist die Zusage an den
# Betreiber (Eintrag in broker.conf), nicht die Konstante des Moduls.
pruefe(SG.KONF_INTERN_NETZE == "SANDBOX_INTERN_NETZE", "Schluessel heisst SANDBOX_INTERN_NETZE")
konf.write_text('SSH_NETZE="192.0.2.0/24"\n'
                'SANDBOX_INTERN_NETZE="10.0.0.0/8 schrott"\n'
                f"SANDBOX_INTERN_NETZE='{OEFF4} kaputt/99 {OEFF6.network_address + 5}/32 0.0.0.0/0 {OEFF4}'\n")
puffer = io.StringIO()
with contextlib.redirect_stdout(puffer):
    kn = SG.konf_intern_netze(str(konf))
pruefe(str(OEFF4) in kn, "Konfiguration: Zusatznetz gelesen (letzte Zeile gewinnt)", str(kn))
pruefe("10.0.0.0/8" not in kn, "fruehere Zeile desselben Schluessels gilt nicht", str(kn))
pruefe(str(OEFF6) in kn, "Host-Bits abgeschnitten (strict=False), IPv6 dabei", str(kn))
pruefe(len(kn) == 2, "ungueltiger Eintrag und /0 verworfen, keine Doppelten", str(kn))
pruefe("kaputt/99" in puffer.getvalue() and "0.0.0.0/0" in puffer.getvalue(),
       "verworfene Eintraege stehen im Journal", puffer.getvalue().strip())
puffer = io.StringIO()
with contextlib.redirect_stdout(puffer):
    SG.konf_intern_netze(str(konf))
pruefe(puffer.getvalue() == "", "dieselbe Meldung nur einmal je Prozess (Journal bleibt lesbar)")
pruefe(SG.konf_intern_netze(str(SANDKASTEN / "fehlt")) == [], "fehlende broker.conf -> keine Zusatznetze")

host = str(OEFF4.network_address + 10)
gw_in = str(OEFF4.network_address + 1)
gw_aus = str(OEFF4_B.network_address + 1)
ADR = [{"ifname": "eth0", "addr_info": [
    {"family": "inet", "local": host, "prefixlen": OEFF4.prefixlen, "scope": "global"},
    {"family": "inet6", "local": str(OEFF6.network_address + 10), "prefixlen": 64, "scope": "global"},
    {"family": "inet6", "local": "fe80::1", "prefixlen": 64, "scope": "link"}]}]
an = SG.angeschlossene_netze(ADR, [{"dst": "default", "gateway": gw_in}])
pruefe(an[:1] == [str(OEFF4)], "angeschlossenes v4-Netz aus der Adresse (Praefix, nicht nur Host)", str(an))
pruefe(any(x.endswith("/64") and ":" in x for x in an), "angeschlossenes globales v6-Netz", str(an))
pruefe(not any(x.startswith("fe80") for x in an), "Link-Scope nicht doppelt aufgenommen", str(an))
pruefe(len(an) == 2, "Gateway im angeschlossenen Netz: kein Extraeintrag", str(an))
an2 = SG.angeschlossene_netze(ADR, [{"gateway": gw_aus}, {"gateway": "fe80::1"}])
pruefe(f"{gw_aus}/32" in an2, "Gateway ausserhalb (onlink) wird als Einzeladresse gesperrt", str(an2))
pruefe(not any(x.startswith("fe80") for x in an2), "Link-Local-Gateway nicht aufgenommen", str(an2))

resolver = str(OEFF4.network_address + 53)
txt = SG.netz_regeln(UIDS, [resolver], [], [str(OEFF4), str(OEFF6)])
s8, r8 = zerlegen(txt)
n4, n6 = netze(s8.get("intern4", [])), netze(s8.get("intern6", []))
pruefe(gedeckt(host, n4) and gedeckt(gw_in, n4), "Zusatznetz v4 ist gesperrt (Server und Gateway darin)")
pruefe(gedeckt(str(OEFF6.network_address + 99), n6), "Zusatznetz v6 ist gesperrt")
pruefe(not gedeckt(str(OEFF4_B.network_address + 1), n4), "Nachbarnetz ausserhalb bleibt frei (Internet)")
pruefe(gedeckt(resolver, n4), "Positivkontrolle: Resolver liegt im gesperrten Block")
mit_res = [(i, z) for i, z in enumerate(r8) if resolver in z]
erste = next((i for i, z in enumerate(r8) if ist_abweisung(z)), None)
pruefe(len(mit_res) == 2 and all(z.endswith("dport 53 accept") for _, z in mit_res),
       "Resolver im Block: genau udp+tcp 53 erlaubt, sonst nichts", str(mit_res))
pruefe(erste is not None and mit_res and max(i for i, _ in mit_res) < erste,
       "Resolver-Ausnahme steht VOR den Sperren")

u4, u6 = SG.sperrmengen(["10.1.2.0/24", "10.0.0.0/8", str(OEFF4), str(OEFF4.network_address + 3) + "/32",
                         str(list(OEFF4.supernet().subnets())[1]), "fd00:1::/48", "kaputt"])
nu4, nu6 = netze(u4), netze(u6)
pruefe(not ueberschneidungen(nu4) and not ueberschneidungen(nu6),
       "ueberlappende Zusatzbereiche zusammengefuehrt (nft: keine conflicting intervals)",
       str(ueberschneidungen(nu4) + ueberschneidungen(nu6)))
pruefe(u4.count("10.0.0.0/8") == 1 and not any(x.startswith("10.1.2.") for x in u4),
       "Teilnetz verschwindet im RFC-Obernetz", str(u4))
pruefe(str(OEFF4.supernet()) in u4, "benachbarte Haelften zu einem Netz vereinigt", str(u4))
pruefe(len(u4) <= len(SG.INTERN_V4) + 1, "Set waechst nicht um Doppelte", str(len(u4)))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
