# Trennung UI-/Ausführungsebene (Root-Broker)

Das Backend (Web-UI, Chat, Agent) läuft im getrennten Betrieb als
unprivilegierter Benutzer (`jarvis.service`, User=jarvis, Port 443 via
`CAP_NET_BIND_SERVICE`). Alles, was root braucht, läuft über den
**Root-Broker** (`jarvis-broker.service`, root, Unix-Socket
`/run/jarvis-broker.sock`, nur Gruppe `jarvis`):

- **Benannte, validierte Operationen** (`backend/broker/ops.py`): systemctl
  (Unit-Whitelist), VNC/Session/Unlock, chpasswd, Sandbox-/Egress-Setup,
  Mounts (nur `/mnt/`), certbot, `sandbox_lauf` (systemd-run-Grenzen + runuser + bwrap, fail-closed, nur
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

**Vertrauensmodell (seit 2026-09-29, Befunde K1/K2 des BSI-Abgleichs):**

- **Root-eigene Laufzeit.** Der Broker laeuft NICHT mehr aus `/opt/jarvis` (gehoert
  dem Dienstbenutzer), sondern aus `/usr/local/lib/jarvis-broker` (root:root) mit dem
  System-Python. Vorher genuegte eine geaenderte Zeile in `backend/broker/`, im venv
  oder in `start_jarvis_root.sh`, um beim naechsten Neustart root zu sein. Aus dem
  Projektbaum startet root nichts mehr (kein Skript, kein venv, kein git).
- **Quelle der Kopie** steht in `/etc/jarvis/broker.conf` (root-eigen):
  `QUELLE=github` (Vorgabe) – root holt den Stand bei jedem Broker-Start selbst aus
  dem oeffentlichen Repository; der Dienstbenutzer kann ein Auffrischen ausloesen,
  aber nicht bestimmen, WAS installiert wird. `QUELLE=lokal` kopiert aus
  `/opt/jarvis` – nur fuer Entwicklungsrechner, jeder Start warnt im Journal.
  Von Hand: `bash deploy/security/broker_installieren.sh [--quelle lokal]`.
- **Bestandssysteme stellen sich selbst um:** laeuft `start_jarvis_root.sh` noch aus
  dem Projektbaum (alte Unit), legt es die Kopie an, schreibt die Unit um und wechselt
  hinein. Dabei wird auch eine als root laufende `whatsapp-bridge.service` auf den
  Dienstbenutzer umgestellt.
- **Freigaben brauchen einen Nachweis, den nur der Broker pruefen kann.** `allow` und
  das Loeschen eines Eintrags verlangen einen TOTP-Code (Schluessel root-eigen in
  `/etc/jarvis/broker-freigabe.key`). Einrichten als root:
  `jarvis-broker-admin totp-einrichten`. Ohne Code geht es nur ueber die root-Konsole:
  `jarvis-broker-admin liste | erlauben <key> | ablehnen <key> | audit`.
  `deny`/`pending` brauchen keinen Code (sie schraenken nur ein).
- Der Broker prueft den Aufrufer per `SO_PEERCRED` (nur root und der Dienstbenutzer)
  und schreibt dessen uid ins Audit (`peer`) – `user`/`by` sind Angaben des Aufrufers.
- Nicht mehr automatisch erlaubt: `broker_teardown` (macht das Backend wieder zu root).
  `chpasswd` nur noch fuer das Anmeldekonto `jarvis` und nur, wenn es nicht root werden
  kann (sudo-Gruppe/sudoers mit Kennwort). Netzwerk-Mounts mit `nosuid,nodev,noexec`.
- **Bekannte Grenze:** ein Backend, das GENAU in dem Moment kompromittiert ist, in dem
  ein Administrator einen Code eintippt, kann diesen einen Code fuer eine andere
  Entscheidung verwenden (Wiederholschutz: genau eine). Ohne anwesenden Administrator
  – der Fall einer Prompt-Injection – gibt es keine Freigabe.

## systemd-Härtung (BSI M1)

Der Broker schreibt bei **jedem Start** aus seiner root-eigenen Kopie
(`haertung_installieren.sh`):

- `/etc/systemd/system/jarvis.service.d/50-haertung.conf` – Backend:
  `ProtectSystem=strict` (schreibbar nur Projektbaum, Home, `/tmp`, `/var/tmp`,
  `/dev/shm`, `/mnt`, `/media`), `CapabilityBoundingSet=CAP_NET_BIND_SERVICE`,
  begrenzte Adressfamilien, Syscall-Filter, `ProtectKernelModules`,
  `ProtectControlGroups`. `systemd-analyze security`: **9,3 → 4,5** (DEV, 05.10.2026).
- `/etc/systemd/system/jarvis-broker.service.d/50-haertung.conf` – Broker: nur, was
  keine seiner Root-Aufgaben einschränkt (Bewertung bleibt hoch, by design).

Wirksam ab dem nächsten Neustart des jeweiligen Dienstes. **Bewusst nicht gesetzt**
(jeweils gemessen, Begründung im Skript): `NoNewPrivileges` (lokale Anmeldung über
`unix_chkpwd`), `ProtectKernelTunables`/`ProtectKernelLogs`/`ProtectHostname`/
`RestrictSUIDSGID` (bwrap: MCP-Isolation und Shell-Sandbox), `PrivateTmp` (geteiltes
`/tmp` mit Broker und Sandbox). **Notausgang:** `HAERTUNG=aus` in
`/etc/jarvis/broker.conf`, Broker neu starten, dann `jarvis.service`.
Prüfen: `python3 /opt/jarvis/tests/live_bsi_m1_m2_dev.py` (als root).

## Sicherheitsprotokoll (BSI M2)

`data/logs/sicherheit.jsonl` (0600, Hash-Kette) **und** syslog (Facility authpriv,
Kennung `jarvis-security`): Anmeldungen mit Quelladresse (auch fehlgeschlagene und
Outlook-SSO), Kontosperren, Abmeldungen, Kennwort-/2FA-Änderungen und **jede ändernde
Anfrage, die eine Admin-Prüfung bestanden hat oder an ihr gescheitert ist** (Methode,
Pfad ohne Query, Status – nie der Anfragekörper). Aufbewahrung nur nach Alter:
`JARVIS_SICHERHEITS_LOG_TAGE` (Vorgabe 365, `0` = dauerhaft).

- Kette prüfen: `sudo -u jarvis venv/bin/python -m backend.sicherheits_log pruefen`
- Ansehen: `journalctl -t jarvis-security` bzw. `… -m backend.sicherheits_log zeigen 50`
- SIEM/zentrales Log: rsyslog nach `programname == "jarvis-security"` weiterleiten.
  Die Kette erkennt Änderungen und Lücken in der Mitte, nicht das Abschneiden am Ende –
  dafür ist die syslog-Kopie da.
- Broker-Audit `/var/log/jarvis-broker-audit.jsonl`: wöchentlich rotiert
  (`/etc/logrotate.d/jarvis-broker-audit`), gelöscht nach 365 Tagen, nie nach Stückzahl.

## SSH nur per Schlüssel (BSI M7)

`ssh_haertung.sh` schreibt `/etc/ssh/sshd_config.d/05-jarvis-haertung.conf`:
`PasswordAuthentication no`, `KbdInteractiveAuthentication no`,
`PermitEmptyPasswords no`, `PermitRootLogin no` (oder `prohibit-password` mit
`SSH_ROOT=schluessel` in `/etc/jarvis/broker.conf` – DEV deployt als root per
Schlüssel). Die `05` sorgt dafür, dass ein späteres `50-cloud-init.conf` mit
`PasswordAuthentication yes` nicht gewinnt (sshd nimmt den ersten Wert).

**Die erste Umstellung macht ein Mensch** – eine falsche SSH-Sperre sperrt den
Betreiber aus:

```bash
bash /usr/local/lib/jarvis-broker/deploy/security/ssh_haertung.sh --status
bash /usr/local/lib/jarvis-broker/deploy/security/ssh_haertung.sh --test 300   # Rückfall-Timer
#   in einer NEUEN Sitzung: Kennwort muss scheitern, Schlüssel muss gehen
bash /usr/local/lib/jarvis-broker/deploy/security/ssh_haertung.sh --anwenden
```

Vor jedem Schreiben prüft der **Aussperr-Schutz**, dass ein Konto mit Schlüssel root
werden kann (root bei `SSH_ROOT=schluessel`, sonst Mitglied von sudo/wheel) und dass
ein per sudo aufrufendes Konto selbst einen Schlüssel hat – sonst Exit 3
(`--erzwingen` übergeht das, laut). `--anwenden` setzt `SSH_HAERTUNG=an`; ab dann
hält jeder Broker-Start den Drop-in aktuell. Rückweg: `--aus`.

**In der Oberfläche:** *Einstellungen → Sicherheit → Fernzugang (SSH)* zeigt den
wirksamen Zustand (`sshd -T`), die Konten, die root werden können, mit den
Fingerabdrücken ihrer Schlüssel, und eine Anleitung zum Hinterlegen eines Schlüssels.
**Hinterlegen selbst geht dort bewusst nicht** – das wäre ein neuer Weg zu root per SSH
für jeden, der Web-Admin ist und den Code kennt. Härtung und Netze lassen sich dort
umstellen: jede Änderung zuerst als **Test mit Rückfall nach 5 Minuten**, dann
**Bestätigen**; beides mit dem Freigabe-Code der Root-Freigaben (der Broker prüft ihn).
„Sofort zurücknehmen“ während eines Tests braucht keinen Code – es stellt nur den
bestätigten Stand her. Broker-Seite: `backend/broker/fernzugang.py` (ruft dieselben
Skripte wie die Konsole), API `GET /api/broker/ssh/status`,
`POST /api/broker/ssh/haertung|netze`. Eine **Ersteinrichtung des Paketfilters** bleibt
Konsolenarbeit (`firewall.sh --test`/`--anwenden`); der Netze-Rückfall stellt nur
`SSH_NETZE` zurück, nicht „kein Filter“. ⚠ Er setzt dabei den Regelsatz **dieses
Skripts** – eine von Hand ergänzte oder veraltete Regel (z. B. ein altes 6080) fällt
dabei weg.

**Port 22 auf Admin-Netze begrenzen:** `SSH_NETZE="192.0.2.0/24 2001:db8::/48"` in
`/etc/jarvis/broker.conf`, dann `firewall.sh --zeigen` (Trockenlauf), `--test`,
`--anwenden`. Liegt die eigene Sitzung nicht in den Netzen, bricht das Skript ab.
Wer über Tailscale administriert, nimmt `100.64.0.0/10` mit auf.

## Abhängigkeiten, CI, Node (BSI M6)

- **Sicherheits-CI** `.github/workflows/sicherheit.yml` (Push, PR, wöchentlich):
  Wächter-Sammellauf (`tests/ci_lauf.py`), `pip-audit`, `npm audit` der Bridge,
  CycloneDX-SBOM (Python + npm, als Artefakt), `bandit` (nur hoch/hoch), `gitleaks`
  über die ganze Historie. Dazu `.github/dependabot.yml` (pip, npm, Actions, Docker).
- **Ausnahmen sind Dateien mit Grund**, keine Schalter: `tests/ci_ausnahmen.txt`
  (Wächter, die beim Einrichten schon rot waren – ein Rückstand, kein Freibrief),
  `deploy/security/pip_audit_ausnahmen.txt` (mit Prüfdatum; danach wird die CI rot),
  `.gitleaksignore` (einzeln geprüfte Fingerabdrücke).
- **Node:** Node 20 ist seit 30.04.2026 ohne Updates. `node_aktualisieren.sh` hebt
  auf Node 24 LTS (NodeSource, Schlüssel-Fingerabdruck festgeschrieben, kein
  `curl | bash`) und baut die Bridge-Module neu. Vorher ansehen, was apt entfernen
  würde: `node_aktualisieren.sh --simulieren` (ändert nichts). Der Broker-Start meldet
  eine alte Node-Linie im Journal.

## Geheimnisse (BSI M5)

**Hauptschlüssel `/etc/jarvis/geheimnis.key`** (root, 0600) – angelegt von
`haertung_installieren.sh` beim ersten Broker-Start, **nie überschrieben**. Der Dienst
bekommt ihn über den Drop-in `jarvis.service.d/40-geheimnis.conf`
(`LoadCredential=geheimnis:…`); der Dienstbenutzer kann die Datei selbst nicht lesen.
Der Drop-in bleibt auch bei `HAERTUNG=aus` stehen. Läuft `jarvis.service` beim
Broker-Start ohne Credential (gestartet, bevor der Drop-in geladen war – so auf ECHT am
05.10.2026 beim ersten Update), startet der Broker ihn einmal nach; das Backend meldet
den Zustand außerdem laut im Journal (`[Tresor] ⚠⚠ WARNUNG`) und im Sicherheitsprotokoll
(`geheimnis_schluessel_fehlt`).

Damit verpackt (`backend/geheimnis_tresor.py`):
- die Schlüsseldateien der Konten in `data/` (`.mailkey`, `.sapkey`, `.vemaskey`,
  `.jirakey`, `.confluencekey`, `.mountkey`, `.aimousesignkey`) – Inhalt `JGK1:…`;
  das Chiffrat der Konten bleibt unverändert,
- die Geheimfelder in `data/settings.json` (LLM-Schlüssel, Agent-API-Keys,
  AD-Bind-Kennwort, Sammelzugänge der Skills, Tokens in MCP-Umgebungen) – Werte `JGS1:…`,
- `data/.secret_key` (Signierschlüssel der Sitzungstokens) – Inhalt `JGK1:…`,
- die 2FA-Secrets in `data/auth_state.json` und die Freigabe-/Peer-Token in
  `data/knowledge_sync.json` – Werte `JGS1:…`.

Alles geschieht beim ersten Dienststart mit Hauptschlüssel von selbst.

**Prozesse außerhalb des Dienstes** (Live-Proben, Werkzeuge) haben den Hauptschlüssel
nicht: Tokens, die sie ausstellen, gelten im Dienst nicht, und sie sehen verpackte
Werte. Solche Aufrufe als root über `deploy/als_dienst.sh <befehl>` starten (Dienstbenutzer
+ `LoadCredential`), nicht per `runuser -u jarvis`.

**2FA ohne Hauptschlüssel:** Fehlt er oder passt er nicht, meldet die Anmeldung „Zwei-
Faktor-Prüfung gerade nicht möglich" (503). Rückweg, wenn der Schlüssel verloren ist:
als root in `data/auth_state.json` beim Konto `totp_enabled` auf `false` und
`totp_secret` auf `null` setzen – danach meldet es sich ohne 2FA an und richtet sie neu ein.

**⚠ Sicherung:** `data/` allein ist nach M5 **wertlos** für die Kennwörter. Der
Hauptschlüssel gehört in jede Sicherung – **getrennt** von `data/` aufbewahrt (sonst
liegen Schlüssel und Chiffrat wieder beieinander). Ein Restore von `data/` ohne ihn
heißt: alle Kennwörter, Tokens und LLM-Schlüssel neu eintragen.

**Umzug:** Datei nach `/etc/jarvis/geheimnis.key` (root, 0600) kopieren, **bevor** der
Broker auf dem neuen Server zum ersten Mal startet – sonst legt er einen neuen an.

**Ohne Hauptschlüssel** (Docker ohne systemd, Entwicklungsrechner) bleibt alles wie vor
M5 (Klartext bzw. rohe Schlüsseldatei). Docker: `JARVIS_GEHEIMNIS_DATEI` auf eine
eingehängte Schlüsseldatei zeigen lassen. Bereits verpackte Werte gehen ohne Schlüssel
nicht verloren – sie bleiben verpackt stehen und sind nur nicht benutzbar.

**Anzeigen** eines gespeicherten Geheimnisses (Auge am Feld) verlangt eine erneute
Bestätigung mit Kennwort oder 2FA-Code; danach ist **diese** Sitzung 5 Minuten frei.
Fehlversuche zählen beim Anmeldeschutz mit. Formulare und Listen liefern Geheimfelder
leer (leer speichern = unverändert). Zustand: `GET /api/security/geheimnisse` (Admin).

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
#    Ebenso JARVIS_DNS (Platzhalter) mit den Resolver-IPs aus /etc/resolv.conf
#    des Servers fuellen - interne Adressen stehen nie im Repo.

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

# Re-Test der Zugriffskontrolle (`security_retest.py`)

Nach jeder Änderung an `backend/sandbox.py`, am Tool-Dispatch
(`agent._execute_tool`) oder an `security_guard` prüfen:

```bash
cd /opt/jarvis && sudo ./venv/bin/python deploy/security/security_retest.py
```

Das Skript importiert die **echten** Enforcement-Funktionen und repliziert die
Dispatch-Entscheidung 1:1 – es prüft also den Produktivpfad, nicht die
LLM-/Prompt-Ebene. Abgedeckt: die sieben Pentest-Vektoren (Secrets lesen,
Schreiben außerhalb des Arbeitsbereichs, Verschleierung inkl. **kurzer**
Base64-Payloads, settings.json/.env, Lern-Filter, Sub-Agent-Eskalation,
OS-Sandbox via `runuser`) plus Auto-Sperr-Schwelle und Admin-Gegenprobe.

Als root ausführen, sonst entfällt der `runuser`-Teil (Vektor 7). Der
Autoblock-Test läuft in-memory (`_load`/`_save` gepatcht) und verändert die
echte Violations-/Sperr-Datei **nicht** – das Skript ist auf einem
Produktionssystem gefahrlos.

Stand 2026-07-28: alle Prüfungen grün auf Test- **und** Echt-System.

# Dateirechte der Dienst-Verzeichnisse

`sandbox.harden_data_dirs()` setzt `data/documents`, `data/chats` und
`data/logs` bei jedem Start auf **0750**. Grund: die Eigentümer-Schranke der
Werkzeuge wirkt nur im Backend – Shell-Befehle von Domain-Benutzern laufen als
`jarvis_sandbox`, und ein `cat` dort braucht nur Dateisystemrechte. Mit den
Vorgabe-Rechten (0755) konnte damit jeder Domain-Benutzer die Ergebnisdateien
und Chat-Verläufe **aller** anderen lesen.

`data/knowledge` bleibt absichtlich lesbar (die Shell soll Wissensdateien
verarbeiten). Angehängte Dateien bekommt der Agent deshalb als Arbeitskopie
unter `/tmp/anhang_<12 Hex>_<name>`.

Grenze: alle Domain-Benutzer teilen **einen** Sandbox-Benutzer – OS-Rechte
trennen sie vom Dienst-Verzeichnis, aber nicht voneinander. Echte Trennung
bräuchte einen Sandbox-Benutzer pro Person.

```bash
# Prüfen (als root):
stat -c '%a %U:%G %n' /opt/jarvis/data/{documents,chats,logs,knowledge}
runuser -u jarvis_sandbox -- ls /opt/jarvis/data/documents   # -> muss scheitern
```
