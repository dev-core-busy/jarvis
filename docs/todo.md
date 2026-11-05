# Offene Punkte

## Gespeicherte Zugangsdaten vom System nehmen

Ziel: Auf dem Server liegen keine Kennwörter und Tokens der angebundenen Systeme
mehr. Die Bereiche werden nacheinander umgestellt.

- [x] **SAP** – Schalter „Anmeldung über die Portal-Kachel fordern“
      (Einstellungen → SAP). Beim Einschalten werden das Kennwort des gemeinsamen
      Zugangs und die Kennwörter aller eigenen Zugänge gelöscht; angemeldet wird
      im Bereich SAP, das Kennwort gilt nur für die Sitzung, der Browser darf es
      sich merken.
- [ ] **VEMAS** – vorerst unverändert, wird später umgestellt.
- [ ] **Jira** – Knopf „persönliche Zugänge erlauben“ (unter Container
      Verbindung); beim Abschalten nach Warnhinweis die persönlichen Zugänge
      löschen und den Container „Persönliche Jira-Zugänge“ ausblenden.
- [ ] **Confluence** – Personal Access Token bleibt; er muss nur lesend
      berechtigt sein.
- [ ] **Outlook** – größerer Umbau: das Add-in greift direkt auf Exchange zu;
      Jarvis dient dort nur noch der Analyse und als Wissensquelle.
