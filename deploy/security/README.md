# Trennung UI-/Ausführungsebene (Root-Broker)

Das Backend (Web-UI, Chat, Agent) läuft im getrennten Betrieb als
unprivilegierter Benutzer (`jarvis.service`, User=jarvis, Port 443 via
`CAP_NET_BIND_SERVICE`). Alles, was root braucht, läuft über den
**Root-Broker** (`jarvis-broker.service`, root, Unix-Socket
`/run/jarvis-broker.sock`, nur Gruppe `jarvis`):

- **Benannte, validierte Operationen** (`backend/broker/ops.py`): systemctl
  (Unit-Whitelist), VNC/Session/Unlock, chpasswd, Sandbox-/Egress-Setup,
  Mounts (nur `/mnt/`), certbot, `sandbox_exec` (runuser, nur
  `jarvis_sandbox*`-User) und generisches `shell_root`.
- **Auditierbare Freigabeliste** (`/etc/jarvis/broker-policy.json`, nur root):
  Jede Operation wird beim ersten Auftauchen als Eintrag registriert.
  Systemoperationen: automatisch erlaubt (Admin kann widerrufen).
  `shell_root:<befehl>` (Root-Shell des Agenten): startet als **pending** und
  muss unter *Einstellungen → Sicherheit → Root-Freigaben* erlaubt werden.
- **Audit-Log** `/var/log/jarvis-broker-audit.jsonl` (root-eigen, vom Backend
  nicht manipulierbar). API: `/api/broker/status|ops|ops/decide|ops/remove|audit`.

## Migration (pro Server)

```bash
# Code deployen (beide Pfade), dann:
bash /opt/jarvis/deploy/security/setup_broker.sh   # [JARVIS_DIR] [SERVICE_USER]
```

Alt-Betrieb (nicht migriert, Backend als root) funktioniert weiter: der
Broker-Client führt Operationen dann lokal aus – inklusive Policy + Audit,
nur ohne Prozess-Trennung.

**Vertrauensmodell / bekannte Grenze:** Die Admin-Entscheidungen kommen über
das Backend (Web-UI) zum Broker. Ein vollständig kompromittiertes Backend
könnte sich Freigaben selbst erteilen – die Trennung schützt primär davor,
dass Agent-/Prompt-Injection-Code *direkt* mit root läuft, und macht jede
Root-Aktion auditierbar. Policy/Audit-Dateien selbst sind root-only.

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
