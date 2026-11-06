"""BSI H10 – die harten Grenzen JEDES Sandbox-Laufs, an einer Stelle.

BEFUND H10 (BSI-Abgleich 2026-09-29, ECHT): "Shell-Sandbox ist optional,
Blocklisten-basiert, ohne Netz-Namespace und ohne Ressourcenlimits;
privilegierte Shell laeuft gar nicht isoliert." Massnahme: Sandbox fuer alle,
Abbruch statt Weiterlaufen ohne Isolation, Ressourcenlimits, Loopback fuer
Sandbox-UIDs sperren.

Was dieses Modul dazu beitraegt (die Kennung/der Namespace selbst bleibt in
``lauf_tmp.sandbox_befehl``):

1. **PFLICHT STATT OPTION.** Der Sandbox-Benutzer kommt nicht mehr nur aus der
   Einstellung ``sandbox_shell_user``: ist sie leer, gilt ``jarvis_sandbox``,
   sobald es den OS-Benutzer gibt. Eine leere Einstellung schaltet die Sandbox
   also NICHT mehr ab – genau das war der Befund (auf DEV am 2026-10-05
   gemessen: Einstellung leer, Domain-Shell lief als Dienstbenutzer).
2. **FAIL-CLOSED** (Betreiberentscheid 2026-10-05, ersetzt die fail-open-
   Festlegung vom 2026-08-23 in ``lauf_tmp``): fehlt eine Grenze – kein
   Sandbox-Benutzer, kein ``bwrap``, kein ``systemd-run``, keine
   Loopback-Sperre –, laeuft der Befehl NICHT, und der Benutzer erfaehrt
   warum. ``bereit()`` ist die eine Pruefung dafuer, Broker und Alt-Betrieb
   rufen dieselbe.
3. **RESSOURCEN** ueber ``systemd-run --scope`` (cgroup v2): Speicher, Anzahl
   Prozesse, CPU-Anteil und eine Laufzeitgrenze. Auf DEV gemessen
   (2026-10-05, als jarvis_sandbox im bwrap): 512 MB bei 256 MB Grenze ->
   beendet, 64 MB laufen (Positivkontrolle); 100 Prozesse bei 32 -> Abbruch;
   eine per ``nohup … & disown`` abgehaengte Waise ist nach ``RuntimeMaxSec``
   weg. **Die Laufzeitgrenze ist mehr als ein zweiter Timeout:** ``killpg``
   erreicht nichts, was sich in eine eigene Sitzung abgesetzt hat – den Scope
   schon. Zeilenweises Streaming bleibt erhalten (gemessen).
4. **NETZ.** Benutzer OHNE Internet-Freigabe laufen mit ``bwrap
   --unshare-net``: im Lauf gibt es nur ein eigenes, leeres ``lo`` (gemessen:
   127.0.0.1:443, 8.8.8.8 und die eigene Adresse unerreichbar). Fuer Benutzer
   MIT Internet geht das nicht; fuer sie sperrt eine nftables-Tabelle den
   LOOPBACK fuer alle Sandbox-UIDs. Gemessen VOR der Sperre: Jarvis selbst
   (443), cups (631) und die eigene Adresse waren aus der Sandbox erreichbar –
   und ein Chrome-Debug-Port, ueber den sich der Browser des Dienstes
   fernsteuern liesse. Deshalb ALLE Ports statt der drei aus dem Bericht.
   DNS auf ``lo`` bleibt offen (ein lokaler Resolver waere sonst tot).

Was es NICHT loest, ehrlich benannt: ohne Netz-Namespace bleiben fuer Benutzer
MIT Internet die abstrakten Unix-Sockets des Hosts erreichbar (sie haengen am
Netz-Namespace, nicht am Dateisystem). Gemessen: der X-Server auf :0 weist eine
Verbindung ohne Cookie ab (Antwort-Byte 0). Und die Grenzen gelten je BEFEHL,
nicht fuer alle Laeufe zusammen.
"""

from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import threading
import time
import uuid

SANDBOX_PREFIX = "jarvis_sandbox"
SBX_USER = "jarvis_sandbox"
NOINET_USER = "jarvis_sandbox_noinet"

SYSTEMD_RUN = "/usr/bin/systemd-run"
NFT_TABELLE = "jarvis_sandbox_lo"

# Vorgaben und erlaubte Bereiche. Der BROKER klemmt auf diese Bereiche – die
# Werte kommen aus settings.json, die der Dienstbenutzer schreiben kann, und
# ein "0" oder "-1" darf die Grenze nicht aufheben.
STANDARD = {"speicher_mb": 2048, "prozesse": 256, "cpu_prozent": 200}
BEREICH = {"speicher_mb": (128, 65536), "prozesse": (16, 4096),
           "cpu_prozent": (10, 6400)}
# Einstellungsschluessel je Grenze (eine Stelle, damit Oberflaeche, Dispatch
# und Status dieselben Namen benutzen).
EINSTELLUNG = {"speicher_mb": "sandbox_grenze_speicher_mb",
               "prozesse": "sandbox_grenze_prozesse",
               "cpu_prozent": "sandbox_grenze_cpu_prozent"}
EINSTELLUNG_ADMINS = "sandbox_auch_admins"
# Vorgabe fuer den Admin-Schalter (Betreiberentscheid 2026-10-11: AN, abschaltbar).
# Bestehende Installationen behalten ihr Verhalten: vorgabe_festschreiben()
# schreibt dort beim ersten Start mit diesem Stand ausdruecklich False fest.
VORGABE_ADMINS = True

# Puffer der Laufzeitgrenze ueber dem Befehls-Timeout: der Timeout des
# Aufrufers soll zuerst greifen (er meldet "Timeout"), der Scope ist das Netz
# fuer alles, was sich abgehaengt hat.
LAUFZEIT_PUFFER_S = 15
LAUFZEIT_MAX_S = 6 * 3600


def _log(msg: str) -> None:
    print(f"[SANDBOX-H10] {msg}", flush=True)


# ── Grenzen ─────────────────────────────────────────────────────────────────

def grenzen_pruefen(roh) -> dict:
    """Rohwerte (Einstellung oder Broker-Argument) auf gueltige Grenzen klemmen.

    Unlesbares faellt auf die Vorgabe, Werte ausserhalb des Bereichs auf die
    naechste Bereichsgrenze. ``bool`` zaehlt NICHT als Zahl (``True`` waere
    sonst 1 MB). Es gibt bewusst keinen Wert, der "ohne Grenze" heisst.
    """
    roh = roh if isinstance(roh, dict) else {}
    aus = {}
    for k, vorgabe in STANDARD.items():
        v = roh.get(k)
        if isinstance(v, bool):
            v = None
        try:
            v = int(v)
        except (TypeError, ValueError):
            v = vorgabe
        lo, hi = BEREICH[k]
        aus[k] = max(lo, min(hi, v))
    return aus


def aus_einstellungen() -> dict:
    """Grenzen aus settings.json (geklemmt)."""
    try:
        from backend.config import config
        roh = {k: config.get_setting(s, None) for k, s in EINSTELLUNG.items()}
    except Exception:  # noqa: BLE001
        roh = {}
    return grenzen_pruefen(roh)


def auch_admins() -> bool:
    """Schalter "Sandbox auch fuer Administratoren" (Vorgabe AN seit 2026-10-11).

    Betreiberentscheid 2026-10-05: waehlbar je Installation; 2026-10-11: Vorgabe
    AN, abschaltbar. AUS heisst: die Shell privilegierter Benutzer laeuft wie
    bisher als Dienstbenutzer (H9: nur nach Klick).

    Nur ein echtes ``bool`` ist eine Entscheidung. Alles andere (nicht gesetzt,
    ``"false"`` als Zeichenkette, unlesbare Einstellung) ergibt die Vorgabe –
    also die SICHERERE Richtung. Bis 2026-10-11 war es umgekehrt (nur ``True``
    schaltete ein), weil die Vorgabe AUS war.
    """
    try:
        from backend.config import config
        v = config.get_setting(EINSTELLUNG_ADMINS, None)
    except Exception:  # noqa: BLE001
        return VORGABE_ADMINS
    return v if isinstance(v, bool) else VORGABE_ADMINS


def vorgabe_festschreiben(bestand: bool):
    """Einmalig beim Start: den Admin-Schalter ausdruecklich setzen, wenn er fehlt.

    Ohne diesen Schritt haette die neue Vorgabe (AN) JEDE bestehende
    Installation beim naechsten Update still umgestellt – dort ist der Schalter
    meist nie gesetzt worden. ``bestand`` (settings.json gab es schon vor diesem
    Prozess) -> ``False`` festschreiben: das Verhalten bleibt, wie es war.
    Erstinstallation -> die Vorgabe festschreiben, damit sie sichtbar in der
    Einstellung steht. Ein bereits gesetzter Wert wird NIE angefasst.
    Rueckgabe: der geschriebene Wert oder None (nichts zu tun / Fehler).
    """
    try:
        from backend.config import config
        if config.get_setting(EINSTELLUNG_ADMINS, None) is not None:
            return None
        wert = False if bestand else VORGABE_ADMINS
        config.save_setting(EINSTELLUNG_ADMINS, wert)
        _log(f"'Sandbox auch fuer Administratoren' festgeschrieben: {wert} "
             f"({'bestehende Installation – Verhalten bleibt' if bestand else 'Erstinstallation – Vorgabe'})")
        return wert
    except Exception as e:  # noqa: BLE001
        _log(f"Vorgabe des Admin-Schalters nicht festgeschrieben: {e}")
        return None


def scope_praefix(grenzen: dict, timeout_s: int) -> list:
    """``systemd-run --scope …`` vor den Befehl – die Ressourcengrenzen.

    ``MemorySwapMax=0``: ohne das wiche ein Lauf an der Speichergrenze in den
    Swap aus und braeuchte die Maschine statt sich selbst zu beenden.
    Der Unit-Name traegt eine Zufallskennung, damit gleichzeitige Laeufe sich
    nicht ins Gehege kommen und ein Scope im Journal auffindbar ist.
    """
    g = grenzen_pruefen(grenzen)
    try:
        t = int(timeout_s)
    except (TypeError, ValueError):
        t = 120
    laufzeit = max(30, min(LAUFZEIT_MAX_S, t + LAUFZEIT_PUFFER_S))
    return [
        SYSTEMD_RUN, "--scope", "--quiet", "--collect",
        "--unit=jarvis-sandbox-" + uuid.uuid4().hex[:12],
        "-p", "MemoryMax=%dM" % g["speicher_mb"],
        "-p", "MemorySwapMax=0",
        "-p", "TasksMax=%d" % g["prozesse"],
        "-p", "CPUQuota=%d%%" % g["cpu_prozent"],
        "-p", "RuntimeMaxSec=%d" % laufzeit,
        "--",
    ]


def grenze_vermutlich_getroffen(rc) -> bool:
    """Exit-Code eines Laufs, den der Scope beendet hat (SIGKILL/SIGTERM).

    Unterscheiden laesst sich Speicher von Laufzeit von aussen nicht sicher –
    die Meldung nennt deshalb alle Grenzen, statt eine zu raten.
    """
    return rc in (137, 143, -9, -15)


# ── Sandbox-Benutzer ────────────────────────────────────────────────────────

def _uid(name: str):
    try:
        return pwd.getpwnam(name).pw_uid
    except (KeyError, TypeError):
        return None


def _gueltig(name: str) -> bool:
    uid = _uid(name)
    return bool(name) and name.startswith(SANDBOX_PREFIX) and uid not in (None, 0)


def sandbox_benutzer(internet: bool) -> tuple:
    """(OS-Benutzer, Grund) fuer einen Sandbox-Lauf – Grund nur, wenn keiner da ist.

    Reihenfolge: Einstellung, sonst der Standardbenutzer, sofern er existiert.
    Ohne Internet: ``sandbox_shell_user_noinet`` bzw. ``jarvis_sandbox_noinet``,
    sonst der normale Sandbox-Benutzer – das Netz ist dann ueber
    ``--unshare-net`` trotzdem zu, der eigene Benutzer ist nur die zweite Lage
    (Egress-Firewall).
    """
    try:
        from backend.config import config
        gesetzt = (config.get_setting("sandbox_shell_user", "") or "").strip()
        gesetzt_ni = (config.get_setting("sandbox_shell_user_noinet", "") or "").strip()
    except Exception:  # noqa: BLE001
        gesetzt, gesetzt_ni = "", ""
    kandidaten = []
    if not internet:
        kandidaten += [gesetzt_ni, NOINET_USER]
    kandidaten += [gesetzt, SBX_USER]
    for k in kandidaten:
        if k and _gueltig(k):
            return k, ""
    falsch = [k for k in (gesetzt, gesetzt_ni) if k and not _gueltig(k)]
    if falsch:
        return "", ("eingestellter Sandbox-Benutzer ungueltig oder nicht vorhanden: "
                    + ", ".join(falsch))
    return "", ("kein Sandbox-Benutzer eingerichtet (Einstellungen → Sicherheit → "
                "Systemschutz / Sandbox → Aktivieren / Reparieren)")


def sandbox_uids() -> list:
    """Alle Sandbox-UIDs dieses Systems (fuer die Loopback-Sperre)."""
    uids = set()
    try:
        for pw in pwd.getpwall():
            if pw.pw_name.startswith(SANDBOX_PREFIX) and pw.pw_uid != 0:
                uids.add(pw.pw_uid)
    except Exception:  # noqa: BLE001
        pass
    return sorted(uids)


# ── Loopback-Sperre ─────────────────────────────────────────────────────────

def lo_regeln(uids) -> str:
    """nftables-Text der Sperre. Atomar ersetzt (anlegen, loeschen, neu).

    Nur ``oif "lo"``: Verkehr an die EIGENE Adresse des Servers geht ebenfalls
    ueber lo und ist damit mit erfasst (gemessen: 443 an der eigenen Adresse
    war vorher erreichbar). Kein uid-loses Drop – Kernel-Sockets (CIFS/NFS)
    tragen keine skuid, siehe egress_guard.
    """
    ids = ", ".join(str(int(u)) for u in uids)
    return (
        f"table inet {NFT_TABELLE} {{}}\n"
        f"delete table inet {NFT_TABELLE}\n"
        f"table inet {NFT_TABELLE} {{\n"
        "    chain out {\n"
        "        type filter hook output priority filter; policy accept;\n"
        f"        oif \"lo\" meta skuid {{ {ids} }} udp dport 53 accept\n"
        f"        oif \"lo\" meta skuid {{ {ids} }} tcp dport 53 accept\n"
        f"        oif \"lo\" meta skuid {{ {ids} }} meta l4proto tcp reject with tcp reset\n"
        f"        oif \"lo\" meta skuid {{ {ids} }} reject\n"
        "    }\n"
        "}\n"
    )


_lo_lock = threading.Lock()
_lo_stand = {"zeit": 0.0, "uids": None}
_LO_FRIST_S = 60.0


def _nft() -> str:
    return shutil.which("nft") or "/usr/sbin/nft"


def lo_sperre_sicherstellen(erzwingen: bool = False) -> tuple:
    """(ok, Grund). Setzt die Sperre (root) – hoechstens einmal je Frist.

    Selbstheilend statt "einmal beim Einrichten": eine Regel, die nur ein
    Knopf herstellt, erreicht keinen Bestandsserver (Register, Egress-Fix
    2026-09-04). Hier stellt sie jeder Sandbox-Lauf her; ein ``nft flush
    ruleset`` von aussen ist nach spaetestens einer Minute geheilt.
    """
    if os.geteuid() != 0:
        return False, "Loopback-Sperre braucht root"
    uids = sandbox_uids()
    if not uids:
        return False, "kein Sandbox-Benutzer vorhanden"
    with _lo_lock:
        jetzt = time.monotonic()
        if (not erzwingen and _lo_stand["uids"] == uids
                and (jetzt - _lo_stand["zeit"]) < _LO_FRIST_S):
            return True, ""
        try:
            r = subprocess.run([_nft(), "-f", "-"], input=lo_regeln(uids),
                               capture_output=True, text=True, timeout=15)
        except Exception as e:  # noqa: BLE001
            return False, f"nft nicht ausfuehrbar: {e}"
        if r.returncode != 0:
            _log(f"Loopback-Sperre nicht gesetzt: {(r.stderr or '').strip()[:200]}")
            _lo_stand.update(zeit=0.0, uids=None)
            return False, "Loopback-Sperre nicht setzbar: " + (r.stderr or "").strip()[:160]
        if _lo_stand["uids"] is None:
            _log(f"Loopback-Sperre aktiv fuer uid {uids}")
        _lo_stand.update(zeit=jetzt, uids=uids)
        return True, ""


def lo_sperre_aktiv() -> bool | None:
    """Ist die Tabelle geladen? None = nicht messbar (kein root)."""
    if os.geteuid() != 0:
        return None
    try:
        r = subprocess.run([_nft(), "list", "table", "inet", NFT_TABELLE],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and "skuid" in (r.stdout or "")
    except Exception:  # noqa: BLE001
        return False


# ── Netz-Sperre: nur oeffentliche Ziele (Befund E1, Pentest-Vorbereitung) ───
#
# BEFUND E1: ein Sandbox-Lauf MIT Internet teilt den Netz-Namensraum des Hosts.
# Die Loopback-Sperre oben schliesst nur ``oif lo``; RFC1918, CGNAT,
# Link-Local (169.254.169.254 = Cloud-Metadaten), Multicast und die IPv6-
# Gegenstuecke waren frei – ein Benutzer mit Internet-Freigabe konnte per
# shell_execute das interne Netz abtasten und interne Dienste (LDAP, SMB,
# Intranet, Verwaltungsoberflaechen) erreichen. Betreiberentscheid: "Nur
# oeffentliche Ziele".
#
# Eigene Tabelle statt Erweiterung von ``jarvis_sandbox_lo``: die Loopback-
# Sperre ist Pflicht fuer JEDEN Lauf, diese nur fuer Laeufe MIT Netz. Scheitert
# nur sie, soll die Shell ohne Internet weiterlaufen (eigene Transaktion,
# eigene Bereitschaftspruefung).
#
# Gilt fuer ALLE Sandbox-UIDs wie die Loopback-Sperre: ein Lauf ohne Internet
# hat ``--unshare-net`` und sieht die Regeln des Hosts gar nicht; wer im
# Host-Namensraum laeuft, hat Internet und faellt genau unter diese Sperre.
#
# Ausnahmen (in dieser Reihenfolge VOR jeder Abweisung):
#   1. DNS (53/udp+tcp) NUR zu den Resolvern aus /etc/resolv.conf – ein lokaler
#      Stub (127.0.0.53) ebenso wie ein interner Resolver. Kein pauschales
#      "Port 53 ins interne Netz".
#   2. ein in der Umgebung eingetragener HTTP(S)-Proxy (Host:Port), falls die
#      Sandbox ueber ihn ins Internet geht.
# Danach: ``oif "lo"`` (Loopback UND alle eigenen Adressen des Servers – Linux
# stellt lokal zugestellten Verkehr ueber lo zu), die reservierten Bereiche
# IPv4/IPv6. Jede Abweisung traegt ``meta skuid`` (Kernel-Sockets wie CIFS/NFS
# haben keinen Eigentuemer und bleiben unberuehrt – Register 2026-09-04) und
# einen Zaehler, an dem die Live-Probe den Treffer misst.

NETZ_TABELLE = "jarvis_sandbox_netz"
RESOLV_CONF = "/etc/resolv.conf"
ETC_ENVIRONMENT = "/etc/environment"
# Root-eigene Broker-Konfiguration (dasselbe Muster wie SSH_NETZE in
# deploy/security/firewall.sh, gelesen wie backend/broker/fernzugang._konf):
#   SANDBOX_INTERN_NETZE="192.0.2.0/24 2001:db8::/48"
# Nachbesserung E1 (DEV-Messung): ein Firmennetz kann einen OEFFENTLICH
# gerouteten Block benutzen – Server, Gateway und Resolver lagen dort in
# keinem RFC-Bereich, interne Dienste waren aus der Sandbox weiter erreichbar.
BROKER_CONF = os.environ.get("JARVIS_BROKER_CONF", "/etc/jarvis/broker.conf")
KONF_INTERN_NETZE = "SANDBOX_INTERN_NETZE"

# Nicht-oeffentliche IPv4-Bereiche (IANA Special-Purpose Registry, RFC 6890).
# Ohne Ueberschneidung – ein Intervall-Set in nftables lehnt sich
# ueberlappende Elemente ab (der Waechter prueft das).
INTERN_V4 = (
    "0.0.0.0/8",          # "dieses Netz"
    "10.0.0.0/8",         # RFC 1918
    "100.64.0.0/10",      # CGNAT, RFC 6598
    "127.0.0.0/8",        # Loopback
    "169.254.0.0/16",     # Link-Local, Cloud-Metadaten
    "172.16.0.0/12",      # RFC 1918
    "192.0.0.0/24",       # IETF-Protokollzuweisungen
    "192.0.2.0/24",       # TEST-NET-1
    "192.88.99.0/24",     # 6to4-Relay (abgekuendigt)
    "192.168.0.0/16",     # RFC 1918
    "198.18.0.0/15",      # Benchmarking
    "198.51.100.0/24",    # TEST-NET-2
    "203.0.113.0/24",     # TEST-NET-3
    "224.0.0.0/4",        # Multicast
    "240.0.0.0/4",        # reserviert, inkl. 255.255.255.255 (Broadcast)
)
# IPv6-Gegenstuecke. ``::ffff:0:0/96`` (IPv4-mapped) geht zwar als IPv4-Paket
# hinaus und wird dort erfasst – steht trotzdem hier, falls ein Stapel es doch
# als IPv6 sendet. 64:ff9b::/96 (NAT64, oeffentlich) bleibt bewusst frei: es
# darf laut RFC 6052 nur globale IPv4-Adressen abbilden; 64:ff9b:1::/48 ist
# die lokale Variante und gesperrt.
INTERN_V6 = (
    "::/127",             # unspezifiziert + Loopback ::1
    "::ffff:0:0/96",      # IPv4-mapped
    "64:ff9b:1::/48",     # NAT64 lokal
    "100::/64",           # Discard
    "2001::/32",          # Teredo
    "2001:db8::/32",      # Dokumentation
    "2002::/16",          # 6to4 (bettet IPv4 ein)
    "fc00::/7",           # Unique Local
    "fe80::/10",          # Link-Local
    "fec0::/10",          # Site-Local (abgekuendigt)
    "ff00::/8",           # Multicast
)

_PROXY_VARIABLEN = ("http_proxy", "https_proxy", "all_proxy", "ftp_proxy")
_PROXY_STANDARDPORT = {"http": 80, "https": 443, "socks": 1080, "socks4": 1080,
                       "socks4a": 1080, "socks5": 1080, "socks5h": 1080}


def resolver_lesen(pfad: str = None) -> list:
    """Nameserver aus resolv.conf (validiert, ohne IPv6-Zonenangabe)."""
    import ipaddress
    aus = []
    try:
        with open(pfad or RESOLV_CONF, encoding="utf-8", errors="replace") as f:
            zeilen = f.read().splitlines()
    except OSError:
        return aus
    for z in zeilen:
        teile = z.split("#", 1)[0].split()
        if len(teile) < 2 or teile[0] != "nameserver":
            continue
        roh = teile[1].split("%", 1)[0]
        try:
            a = str(ipaddress.ip_address(roh))
        except ValueError:
            continue
        if a not in aus:
            aus.append(a)
    return aus


def _env_datei(pfad: str) -> dict:
    """``/etc/environment`` (KEY=WERT, optional in Anfuehrungszeichen)."""
    aus = {}
    try:
        with open(pfad, encoding="utf-8", errors="replace") as f:
            for z in f.read().splitlines():
                z = z.strip()
                if not z or z.startswith("#") or "=" not in z:
                    continue
                k, v = z.split("=", 1)
                k = k.strip()
                if k.startswith("export "):
                    k = k[len("export "):].strip()
                aus[k] = v.strip().strip("'\"")
    except OSError:
        pass
    return aus


def proxy_ziele(umgebung: dict = None, env_datei: str = None, aufloesen=None) -> list:
    """[(ip, port)] der eingetragenen Proxys.

    Quellen: die Prozessumgebung (der Broker vererbt sie an ``runuser``/bwrap,
    also sieht die Sandbox genau diese) und ``/etc/environment`` (pam_env).
    Ein Hostname wird hier aufgeloest, weil nftables nur Adressen kennt; die
    Selbstheilung loest ihn bei jeder Erneuerung neu auf.
    """
    import ipaddress
    import socket
    from urllib.parse import urlsplit
    quellen = [dict(os.environ) if umgebung is None else dict(umgebung),
               _env_datei(env_datei or ETC_ENVIRONMENT)]
    if aufloesen is None:
        def aufloesen(host):
            try:
                return sorted({i[4][0] for i in socket.getaddrinfo(
                    host, None, proto=socket.IPPROTO_TCP)})
            except OSError:
                return []
    ziele = []
    for q in quellen:
        for k, v in q.items():
            if k.lower() not in _PROXY_VARIABLEN or not (v or "").strip():
                continue
            roh = v.strip()
            if "://" not in roh:
                roh = "http://" + roh
            try:
                teile = urlsplit(roh)
                host = teile.hostname
                port = teile.port or _PROXY_STANDARDPORT.get(teile.scheme.lower())
            except ValueError:
                continue
            if not host or not port:
                continue
            try:
                adressen = [str(ipaddress.ip_address(host.split("%", 1)[0]))]
            except ValueError:
                adressen = aufloesen(host)
            for a in adressen:
                try:
                    a = str(ipaddress.ip_address(str(a).split("%", 1)[0]))
                except ValueError:
                    continue
                if (a, int(port)) not in ziele:
                    ziele.append((a, int(port)))
    return ziele


def _konf_lesen(pfad: str = None) -> dict:
    """broker.conf lesen – letzte Zeile gewinnt, wie ``fernzugang._konf`` und
    die Skripte unter deploy/security (dort ``sed … | tail -1``)."""
    import re
    werte = {}
    try:
        with open(pfad or BROKER_CONF, encoding="utf-8", errors="replace") as f:
            for z in f.read().splitlines():
                m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", z)
                if m:
                    werte[m.group(1)] = m.group(2).strip().strip("'\"")
    except OSError:
        pass
    return werte


_gemeldet = set()


def _einmal_melden(text: str) -> None:
    """Journal-Zeile je Inhalt EINMAL je Prozess – die Erneuerung laeuft je
    Frist, eine Zeile je Minute wuerde das Journal entwerten."""
    if text not in _gemeldet:
        _gemeldet.add(text)
        _log(text)


def konf_intern_netze(pfad: str = None) -> list:
    """Zusaetzliche interne Netze aus ``SANDBOX_INTERN_NETZE`` (validiert).

    Leerzeichen-getrennte CIDRs; ein ungueltiger Eintrag wird mit einer
    Journal-Zeile verworfen, die gueltigen gelten weiter (ein Tippfehler darf
    die uebrige Sperre nicht abschalten). Host-Bits werden abgeschnitten
    (``strict=False``), ``/0`` wird verworfen – es saehe wie eine Sperre aus
    und waere eine Sperre des ganzen Internets.
    """
    import ipaddress
    aus = []
    for roh in (_konf_lesen(pfad).get(KONF_INTERN_NETZE) or "").replace(",", " ").split():
        try:
            n = ipaddress.ip_network(roh, strict=False)
        except ValueError:
            _einmal_melden(f"{KONF_INTERN_NETZE}: ungueltiger Eintrag verworfen: {roh!r}")
            continue
        if n.prefixlen == 0:
            _einmal_melden(f"{KONF_INTERN_NETZE}: {roh!r} wuerde alles sperren – verworfen")
            continue
        if str(n) not in aus:
            aus.append(str(n))
    return aus


def _ip_json(*args):
    import json
    try:
        ip = shutil.which("ip") or ("/usr/sbin/ip" if os.path.exists("/usr/sbin/ip") else "/usr/bin/ip")
        r = subprocess.run([ip, "-j", *args], capture_output=True, text=True, timeout=10)
        return json.loads(r.stdout or "[]") if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def angeschlossene_netze(adressen=None, routen=None) -> list:
    """Direkt angeschlossene Netze des Hosts + Netz des Default-Gateways.

    Deckt den Normalfall OHNE Konfiguration ab: wer im selben Netz wie der
    Server steht, ist intern – auch wenn das Netz oeffentlich geroutet ist.
    ``adressen``/``routen`` sind die JSON-Ausgaben von ``ip -j addr show scope
    global`` bzw. ``ip -j route show default`` (fuer den Waechter); ohne sie
    wird ``ip`` aufgerufen (v4 und v6). Liegt das Gateway in keinem
    angeschlossenen Netz (onlink), wird es als Einzeladresse gesperrt.
    """
    import ipaddress
    if adressen is None:
        adressen = _ip_json("addr", "show", "scope", "global")
        if adressen is None:
            _log("angeschlossene Netze nicht lesbar (ip -j addr) – nur RFC- und konfigurierte Bereiche")
            adressen = []
    if routen is None:
        routen = (_ip_json("-4", "route", "show", "default") or []) + \
                 (_ip_json("-6", "route", "show", "default") or [])
    netze = []
    for schnitt in adressen or []:
        for a in (schnitt.get("addr_info") or []):
            if a.get("scope", "global") != "global":
                continue
            try:
                n = ipaddress.ip_network(f"{a.get('local')}/{int(a.get('prefixlen'))}", strict=False)
            except (ValueError, TypeError):
                continue
            if n.prefixlen and n not in netze:
                netze.append(n)
    for r in routen or []:
        try:
            gw = ipaddress.ip_address(str(r.get("gateway") or "").split("%", 1)[0])
        except ValueError:
            continue
        if gw.is_link_local:
            continue
        if not any(gw.version == n.version and gw in n for n in netze):
            netze.append(ipaddress.ip_network(gw))
    return [str(n) for n in netze]


def sperrmengen(zusatz=()) -> tuple:
    """(v4, v6): RFC-Bereiche + Zusatznetze, zusammengefuehrt.

    nftables lehnt in einem Intervall-Set ueberlappende Elemente ab
    ("conflicting intervals") – ein angeschlossenes 10.1.2.0/24 neben 10/8
    haette das Setzen der ganzen Sperre scheitern lassen. Deshalb
    ``collapse_addresses``: Teilnetze verschwinden im Obernetz, Nachbarn werden
    vereinigt.
    """
    import ipaddress
    v4 = [ipaddress.ip_network(x) for x in INTERN_V4]
    v6 = [ipaddress.ip_network(x) for x in INTERN_V6]
    for x in zusatz:
        try:
            n = ipaddress.ip_network(str(x), strict=False)
        except ValueError:
            continue
        (v4 if n.version == 4 else v6).append(n)
    # Python schreibt IPv4-mapped als "::ffff:0.0.0.0/96"; nft bekommt die
    # ausgeschriebene Hex-Form, damit keine Mischschreibweise im Regeltext steht.
    return ([str(n) for n in ipaddress.collapse_addresses(v4)],
            [n.exploded if "." in str(n) else str(n) for n in ipaddress.collapse_addresses(v6)])


def netz_regeln(uids, resolver=(), proxys=(), zusatz=()) -> str:
    """nftables-Text der Netz-Sperre. Atomar ersetzt (anlegen, loeschen, neu).

    Reihenfolge ist die Zusage: alle ``accept`` (Resolver, Proxy) stehen VOR
    der ersten Abweisung; jede Abweisung ist an die Sandbox-UIDs gebunden.
    ``zusatz``: weitere interne Netze (Konfiguration, angeschlossene Netze).
    Ein Resolver darin bleibt erreichbar – aber NUR auf Port 53.
    """
    import ipaddress
    set4, set6 = sperrmengen(zusatz)
    ids = ", ".join(str(int(u)) for u in uids)
    sk = f"meta skuid {{ {ids} }}"
    r4 = [str(ipaddress.ip_address(a)) for a in resolver if ipaddress.ip_address(a).version == 4]
    r6 = [str(ipaddress.ip_address(a)) for a in resolver if ipaddress.ip_address(a).version == 6]
    erlaubt = []
    for fam, liste in (("ip", r4), ("ip6", r6)):
        if liste:
            ziel = ", ".join(liste)
            erlaubt.append(f"        {sk} {fam} daddr {{ {ziel} }} udp dport 53 accept\n")
            erlaubt.append(f"        {sk} {fam} daddr {{ {ziel} }} tcp dport 53 accept\n")
    for adr, port in proxys:
        fam = "ip" if ipaddress.ip_address(adr).version == 4 else "ip6"
        erlaubt.append(f"        {sk} {fam} daddr {ipaddress.ip_address(adr)} "
                       f"tcp dport {int(port)} accept\n")
    sperre = []
    for treffer in ('oif "lo"', "ip daddr @intern4", "ip6 daddr @intern6"):
        sperre.append(f"        {sk} {treffer} meta l4proto tcp counter reject with tcp reset\n")
        sperre.append(f"        {sk} {treffer} counter reject\n")
    return (
        f"table inet {NETZ_TABELLE} {{}}\n"
        f"delete table inet {NETZ_TABELLE}\n"
        f"table inet {NETZ_TABELLE} {{\n"
        "    set intern4 {\n"
        "        type ipv4_addr; flags interval;\n"
        f"        elements = {{ {', '.join(set4)} }}\n"
        "    }\n"
        "    set intern6 {\n"
        "        type ipv6_addr; flags interval;\n"
        f"        elements = {{ {', '.join(set6)} }}\n"
        "    }\n"
        "    chain out {\n"
        "        type filter hook output priority filter; policy accept;\n"
        + "".join(erlaubt) + "".join(sperre) +
        "    }\n"
        "}\n"
    )


_netz_lock = threading.Lock()
_netz_stand = {"zeit": 0.0, "schluessel": None}


def netz_sperre_sicherstellen(erzwingen: bool = False) -> tuple:
    """(ok, Grund). Setzt die Netz-Sperre (root) – hoechstens einmal je Frist.

    Selbstheilend wie die Loopback-Sperre: ``bereit()`` ruft sie vor jedem
    Lauf MIT Netz. Resolver, Proxy, ``SANDBOX_INTERN_NETZE`` und die
    angeschlossenen Netze werden bei jeder Erneuerung neu gelesen
    (spaetestens nach der Frist); aendern sich die UIDs, wird sofort neu
    gesetzt. Ein ``nft flush ruleset`` von aussen ist so nach spaetestens
    einer Frist geheilt.
    """
    if os.geteuid() != 0:
        return False, "Netz-Sperre braucht root"
    uids = sandbox_uids()
    if not uids:
        return False, "kein Sandbox-Benutzer vorhanden"
    with _netz_lock:
        jetzt = time.monotonic()
        if (not erzwingen and _netz_stand["schluessel"] is not None
                and (jetzt - _netz_stand["zeit"]) < _LO_FRIST_S
                and _netz_stand["schluessel"][0] == uids):
            return True, ""
        res = resolver_lesen()
        prx = proxy_ziele()
        konf = konf_intern_netze()
        zus = konf + [n for n in angeschlossene_netze() if n not in konf]
        schluessel = (uids, res, prx, zus)
        try:
            r = subprocess.run([_nft(), "-f", "-"], input=netz_regeln(uids, res, prx, zus),
                               capture_output=True, text=True, timeout=15)
        except Exception as e:  # noqa: BLE001
            _netz_stand.update(zeit=0.0, schluessel=None)
            return False, f"nft nicht ausfuehrbar: {e}"
        if r.returncode != 0:
            _log(f"Netz-Sperre nicht gesetzt: {(r.stderr or '').strip()[:200]}")
            _netz_stand.update(zeit=0.0, schluessel=None)
            return False, ("Sperre interner Netze nicht setzbar: "
                           + (r.stderr or "").strip()[:160])
        if _netz_stand["schluessel"] != schluessel:
            _log(f"Netz-Sperre aktiv fuer uid {uids} (DNS: {res or '-'}, "
                 f"Proxy: {prx or '-'}, Zusatznetze: {zus or '-'})")
        _netz_stand.update(zeit=jetzt, schluessel=schluessel)
        return True, ""


def netz_sperre_aktiv() -> bool | None:
    """Ist die Netz-Sperre geladen? None = nicht messbar (kein root)."""
    if os.geteuid() != 0:
        return None
    try:
        r = subprocess.run([_nft(), "list", "table", "inet", NETZ_TABELLE],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and "skuid" in (r.stdout or "")
    except Exception:  # noqa: BLE001
        return False


# ── Die Pflichtpruefung ─────────────────────────────────────────────────────

def bereit(sandbox_user: str, ohne_netz: bool | None = None) -> tuple:
    """(ok, Grund): kann ein Lauf als ``sandbox_user`` MIT allen Grenzen starten?

    EINE Pruefung fuer Broker und Alt-Betrieb. Jede Antwort ausser ``True``
    heisst: der Befehl laeuft nicht (fail-closed). Der Grund ist fuer Benutzer
    und Journal formuliert, nicht fuer Entwickler.

    ``ohne_netz``: laeuft der Befehl mit ``--unshare-net``? Nur dann ist die
    Netz-Sperre entbehrlich. ``None`` (Aufrufer sagt es nicht) gilt nur fuer
    den netzgesperrten Standardbenutzer als "ohne Netz" – im Zweifel wird die
    Sperre verlangt (fail-closed).
    """
    if not _gueltig(sandbox_user):
        return False, f"Sandbox-Benutzer fehlt oder ist ungueltig: {sandbox_user or '-'}"
    if os.geteuid() != 0:
        return False, "Sandbox-Laeufe brauchen den Root-Broker"
    if not os.path.exists(SYSTEMD_RUN):
        return False, "Ressourcengrenzen nicht verfuegbar (systemd-run fehlt)"
    try:
        from backend import lauf_tmp as _lt
        if not _lt.isolation_gewuenscht():
            return False, "Isolation ist abgeschaltet (JARVIS_LAUF_ISOLATION=0)"
        if not _lt.bwrap_verfuegbar(sandbox_user):
            return False, ("Isolation nicht verfuegbar (bubblewrap fehlt oder "
                           "funktioniert nicht – apt-get install -y bubblewrap)")
    except Exception as e:  # noqa: BLE001
        return False, f"Isolation nicht pruefbar: {e}"
    ok, grund = lo_sperre_sicherstellen()
    if not ok:
        return False, grund
    if ohne_netz is None:
        ohne_netz = sandbox_user == NOINET_USER
    if not ohne_netz:
        # Befund E1: ein Lauf im Host-Namensraum ohne Sperre interner Netze
        # laeuft nicht. Laeufe ohne Internet (eigener Namensraum) trifft das
        # nicht – sie laufen auch dann weiter, wenn nur diese Sperre fehlt.
        ok, grund = netz_sperre_sicherstellen()
        if not ok:
            return False, grund
    return True, ""


def status() -> dict:
    """Zustand fuer die Statusanzeige (laeuft im Broker, also als root)."""
    try:
        from backend import lauf_tmp as _lt
        bwrap = os.path.exists(_lt.BWRAP)
        iso = _lt.isolation_gewuenscht()
    except Exception:  # noqa: BLE001
        bwrap, iso = False, False
    return {
        "pflicht": True,
        "auch_admins": auch_admins(),
        "grenzen": aus_einstellungen(),
        "grenzen_bereich": BEREICH,
        "systemd_run": os.path.exists(SYSTEMD_RUN),
        "bwrap": bwrap,
        "isolation_gewuenscht": iso,
        "lo_sperre": lo_sperre_aktiv(),
        "netz_sperre": netz_sperre_aktiv(),
        "sandbox_uids": sandbox_uids(),
    }
