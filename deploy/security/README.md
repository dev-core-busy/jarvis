# Internet-Egress-Sperre für Benutzer ohne Internet-Freigabe

Benutzer ohne Internet-Freigabe (Einstellungen → Sicherheit → Internet-Zugang)
werden auf zwei Ebenen abgesichert:

1. **Tool-Ebene** (im Hauptprozess, `backend/agent.py`): Tools, die Informationen
   aus dem Internet holen (`search_image`, `browser_control`, `browser_cdp`,
   `google_calendar`, `google_drive`, `google_gmail` sowie jedes Tool mit
   `requires_internet = True`) werden blockiert. Jira/Confluence sind **intern**
   (self-hosted) und daher **nicht** gesperrt.

2. **Netzwerk-Ebene** (OS/Firewall): `shell_execute` läuft für diese Benutzer als
   separater, netzwerkgesperrter OS-User `jarvis_sandbox_noinet` (uid 996). Eine
   nftables-Regel lässt nur loopback, internes LAN (RFC1918) und DNS zu den
   internen Resolvern zu; jeglicher andere ausgehende Verkehr (öffentliches
   Internet) wird verworfen. Das ist die *harte* Grenze und fängt ab, was die
   Egress-Heuristik verpasst (z.B. rohe Sockets).

## Einrichtung (pro Server – auch Echt-System)

```bash
# 1) Netzwerkgesperrten Sandbox-User anlegen
useradd -r -M -d /nonexistent -s /usr/sbin/nologin jarvis_sandbox_noinet
id -u jarvis_sandbox_noinet   # uid merken (hier: 996)

# 2) Falls die uid abweicht: in nftables-jarvis-egress.conf die '996' anpassen.
#    Ebenso die drei Resolver-IPs an /etc/resolv.conf des Servers angleichen.

# 3) Firewall-Regel + Persistenz-Service installieren
cp deploy/security/nftables-jarvis-egress.conf /etc/nftables-jarvis-egress.conf
cp deploy/security/jarvis-egress.service /etc/systemd/system/jarvis-egress.service
nft -f /etc/nftables-jarvis-egress.conf
systemctl daemon-reload && systemctl enable --now jarvis-egress.service

# 4) Backend-Einstellung setzen (persistiert in data/settings.json)
./venv/bin/python -c "from backend.config import config; config.save_setting('sandbox_shell_user_noinet','jarvis_sandbox_noinet')"

# 5) Verifizieren
runuser -u jarvis_sandbox_noinet -- curl -s -m 8 https://example.com   # -> muss scheitern/timeout
runuser -u jarvis_sandbox      -- curl -s -m 8 -o /dev/null -w '%{http_code}\n' https://example.com  # -> 200
```

Die eigenständige nft-Tabelle `inet jarvis_egress` beeinflusst bestehende
Regeln (Docker/NAT/…) nicht. Idempotent (add+flush) – erneutes Laden ist
gefahrlos.

## Bekannter Restrisiko-Hinweis
DNS zu den internen Resolvern ist erlaubt (nötig für Namensauflösung). Ein
theoretisches DNS-Tunneling bleibt damit möglich; für noch strengere Isolation
DNS für uid 996 ganz sperren (Zeilen mit `dport 53` in der .conf entfernen).
