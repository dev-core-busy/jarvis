# User – Wer ist der Benutzer?

## Profil
- **Name:** User
- **Rolle:** Entwickler, Betreiber und Auftraggeber von Jarvis
- **Technisches Niveau:** Sehr versiert – Linux, Python, Go, JavaScript, Docker, Git, GitHub Actions, FTP
- **Sprache:** Deutsch; technische Begriffe auf Englisch sind ok

## Arbeitsweise
- Klare, direkte Aufgaben – erwartet direkte Umsetzung ohne Rückfragen bei eindeutigen Tasks
- Keine Erklärungen zu Dingen, die User bereits kennt
- Testet selbst – kein Babysitting bei Standardaufgaben
- Reagiert sehr ungehalten wenn Ergebnisse als „fertig" gemeldet werden ohne tatsächliche Verifikation
- Kurze Anweisungen – Kontext wird selbst erschlossen

## Präferenzen
- Kurze Antworten bevorzugt, außer die Aufgabe erfordert Detail
- Fehler sofort melden, nicht vertuschen
- Lösungen liefern, nicht nur Analysen
- Ergebnisse immer selbst prüfen (API-Call, Logfile, etc.) – nicht nur behaupten

## Deployment
- Immer an BEIDE Pfade deployen: `/opt/jarvis/` (Prod/systemd) und `/home/jarvis/jarvis/` (Dev)
- Danach `systemctl restart jarvis.service` wenn Backend-Dateien geändert wurden
- Einziger Instruktions-Ordner: `data/instructions/`

## Kontext
- Jarvis-Server: `root@{{SERVER_IP}}` (Debian 13)
- SSH: `ssh -i {{SSH_KEY_PATH}} root@{{SERVER_IP}}`
- Weitere Plattformen: Windows Desktop App (Go/Fyne), Android App, jarvis-ai.info Landing Page
- WhatsApp-Benachrichtigungen für wichtige Ereignisse sind gewünscht
