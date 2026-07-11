"""Internet-Egress-Sperre fuer Benutzer ohne Internet-Freigabe.

Provisioniert und prueft die harte OS-Grenze: shell_execute solcher Benutzer
laeuft als netzwerkgesperrter OS-User (jarvis_sandbox_noinet), dessen
ausgehender Verkehr per nftables auf loopback + internes LAN (RFC1918) + DNS zu
den konfigurierten Resolvern beschraenkt ist; oeffentliches Internet wird
verworfen. Wird ueber Einstellungen -> Sicherheit (Ein-Klick) gesteuert.

Laeuft als root (jarvis.service). Alle Kommandos sind fest verdrahtet; der
einzige dynamische Input sind uid (aus pwd) und Resolver-IPs (aus resolv.conf,
per ipaddress validiert) -> keine Shell-Injection.
"""
import ipaddress
import pwd
import shutil
import subprocess
from pathlib import Path

NOINET_USER = "jarvis_sandbox_noinet"
NFT_CONF = "/etc/nftables-jarvis-egress.conf"
SVC_NAME = "jarvis-egress.service"
SVC_PATH = "/etc/systemd/system/" + SVC_NAME
NFT_TABLE = "jarvis_egress"


def _bin(name, *fallbacks):
    p = shutil.which(name)
    if p:
        return p
    for f in fallbacks:
        if Path(f).exists():
            return f
    return name


NFT = _bin("nft", "/usr/sbin/nft", "/sbin/nft")
USERADD = _bin("useradd", "/usr/sbin/useradd", "/sbin/useradd")
SYSTEMCTL = _bin("systemctl", "/usr/bin/systemctl", "/bin/systemctl")
RUNUSER = _bin("runuser", "/usr/sbin/runuser", "/sbin/runuser", "/usr/bin/runuser")


def _run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        class _R:  # Minimales Ergebnis-Objekt bei Timeout/Fehler
            returncode = 1
            stdout = ""
            stderr = str(e)
        return _R()


def _uid(name):
    try:
        return pwd.getpwnam(name).pw_uid
    except KeyError:
        return None


def _resolvers():
    ips = []
    try:
        for line in Path("/etc/resolv.conf").read_text().splitlines():
            line = line.strip()
            if line.startswith("nameserver"):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        ipaddress.ip_address(parts[1])
                        if parts[1] not in ips:
                            ips.append(parts[1])
                    except ValueError:
                        pass
    except Exception:  # noqa: BLE001
        pass
    return ips


def _nft_active():
    return _run([NFT, "list", "table", "inet", NFT_TABLE]).returncode == 0


def _service_enabled():
    return (_run([SYSTEMCTL, "is-enabled", SVC_NAME]).stdout or "").strip() == "enabled"


def _egress_blocked():
    """Live-Test: versucht als No-Internet-User eine oeffentliche Seite zu laden.
    True = geblockt (gut), False = erreichbar (Luecke), None = User fehlt."""
    if _uid(NOINET_USER) is None:
        return None
    r = _run([RUNUSER, "-u", NOINET_USER, "--", "/bin/bash", "-c",
              "curl -s -m 6 -o /dev/null -w '%{http_code}' https://example.com"],
             timeout=20)
    code = (r.stdout or "").strip()
    # Erreichbar nur bei echtem HTTP-2xx/3xx; 000/leer/Timeout = geblockt
    return not (code[:1] in ("2", "3"))


def status(live=False):
    from backend.config import config
    setting = (config.get_setting("sandbox_shell_user_noinet", "") or "").strip()
    uid = _uid(NOINET_USER)
    st = {
        "configured": bool(setting),
        "setting_value": setting,
        "user": NOINET_USER,
        "user_exists": uid is not None,
        "uid": uid,
        "nft_active": _nft_active(),
        "service_enabled": _service_enabled(),
        "resolvers": _resolvers(),
        "egress_blocked": None,
    }
    if live:
        st["egress_blocked"] = _egress_blocked()
    st["ok"] = bool(st["configured"] and st["user_exists"] and st["nft_active"])
    return st


def _render_nft(uid, resolvers):
    dns = ""
    if resolvers:
        joined = ", ".join(resolvers)
        dns = (f"        ip daddr {{ {joined} }} udp dport 53 accept\n"
               f"        ip daddr {{ {joined} }} tcp dport 53 accept\n")
    return (
        "#!/usr/sbin/nft -f\n"
        "# Auto-generiert von backend/egress_guard.py (Einstellungen -> Sicherheit).\n"
        f"add table inet {NFT_TABLE}\n"
        f"flush table inet {NFT_TABLE}\n"
        f"table inet {NFT_TABLE} {{\n"
        "    chain out {\n"
        "        type filter hook output priority 0; policy accept;\n"
        f"        meta skuid != {uid} accept\n"
        "        ip  daddr 127.0.0.0/8 accept\n"
        "        ip6 daddr ::1 accept\n"
        "        ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16 } accept\n"
        "        ip6 daddr { fe80::/10, fc00::/7 } accept\n"
        f"{dns}"
        "        drop\n"
        "    }\n"
        "}\n"
    )


_SVC_UNIT = (
    "[Unit]\n"
    "Description=Jarvis Egress-Sperre fuer netzwerkgesperrten Sandbox-User\n"
    "After=nftables.service network-pre.target\n"
    "Wants=network-pre.target\n\n"
    "[Service]\n"
    "Type=oneshot\n"
    f"ExecStart={NFT} -f {NFT_CONF}\n"
    f"ExecReload={NFT} -f {NFT_CONF}\n"
    "RemainAfterExit=yes\n\n"
    "[Install]\n"
    "WantedBy=multi-user.target\n"
)


def setup():
    """Idempotente Einrichtung: User + nftables-Regel + Autostart + Einstellung."""
    steps = []

    def step(name, ok, detail=""):
        steps.append({"name": name, "ok": bool(ok), "detail": (detail or "")[:300]})

    # 1) OS-User
    if _uid(NOINET_USER) is None:
        r = _run([USERADD, "-r", "-M", "-d", "/nonexistent",
                  "-s", "/usr/sbin/nologin", NOINET_USER])
        step("OS-Benutzer angelegt", r.returncode == 0, r.stderr)
    else:
        step("OS-Benutzer vorhanden", True)
    uid = _uid(NOINET_USER)
    if uid is None:
        return {"ok": False, "error": "OS-Benutzer konnte nicht angelegt werden",
                "steps": steps, "status": status()}

    # 2) nftables-Regel schreiben (uid + Resolver dynamisch)
    resolvers = _resolvers()
    try:
        Path(NFT_CONF).write_text(_render_nft(uid, resolvers))
        step("Firewall-Regel geschrieben", True, NFT_CONF)
    except Exception as e:  # noqa: BLE001
        step("Firewall-Regel geschrieben", False, str(e))

    # 3) systemd-Unit (Persistenz ueber Reboot)
    try:
        Path(SVC_PATH).write_text(_SVC_UNIT)
        step("Autostart-Dienst geschrieben", True, SVC_PATH)
    except Exception as e:  # noqa: BLE001
        step("Autostart-Dienst geschrieben", False, str(e))

    # 4) Laden + aktivieren
    r = _run([NFT, "-f", NFT_CONF])
    step("Firewall geladen", r.returncode == 0, r.stderr)
    _run([SYSTEMCTL, "daemon-reload"])
    r = _run([SYSTEMCTL, "enable", "--now", SVC_NAME])
    step("Autostart aktiviert", r.returncode == 0, r.stderr)

    # 5) Backend-Einstellung
    try:
        from backend.config import config
        config.save_setting("sandbox_shell_user_noinet", NOINET_USER)
        step("Einstellung gesetzt", True, NOINET_USER)
    except Exception as e:  # noqa: BLE001
        step("Einstellung gesetzt", False, str(e))

    st = status(live=True)
    return {"ok": bool(st.get("ok") and st.get("egress_blocked")),
            "steps": steps, "status": st}
