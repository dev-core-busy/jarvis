# Offene Punkte

## Gespeicherte Zugangsdaten vom System nehmen

Ziel: Auf dem Server liegen keine Kennwörter und Tokens der angebundenen Systeme
mehr. Die Bereiche werden nacheinander umgestellt.

- [x] **SAP** – Schalter „Anmeldung über die Portal-Kachel fordern“
      (Einstellungen → SAP). Beim Einschalten werden das Kennwort des gemeinsamen
      Zugangs und die Kennwörter aller eigenen Zugänge gelöscht; angemeldet wird
      im Bereich SAP, das Kennwort gilt nur für die Sitzung, der Browser darf es
      sich merken.
- [x] **VEMAS** – wie SAP: Schalter „Anmeldung über die Portal-Kachel fordern“
      (Einstellungen → Vemas); gespeicherte Kennwörter/Token werden nach
      Warnhinweis gelöscht, angemeldet wird im Bereich VEMAS für die Sitzung.
- [x] **Jira** – Schalter „Persönliche Zugänge erlauben“ (Container
      Verbindung); beim Abschalten nach Warnhinweis werden die persönlichen
      Zugänge gelöscht und „Persönliche Jira-Zugänge“ / „Mein Jira-Zugang“
      ausgeblendet. Der gemeinsame Zugang ist hart nur lesend (allgemeiner
      Jira-Lesezugang); schreiben kann nur ein persönlicher Zugang.
- [x] **Confluence** – Nur-Lesen ist hart erzwungen (wie SAP, nicht
      abschaltbar); der Personal Access Token braucht nur Leserechte. Einzige
      Ausnahme: „Als neue Confluence-Seite“ beim Destillat im Bereich Wissen.
- [x] **Jira-Browser-Erweiterung** – dort ist nur noch die Anmeldung an Jarvis
      hinterlegt; alle Jira-Lesezugriffe, die sie auslöst (Ticket laden,
      Nachschlage-Werkzeuge), laufen über den gemeinsamen Jira-Lesezugang.
- [x] **Outlook (Stufe 1)** – das Add-in liest die markierte Mail selbst aus
      Exchange (Office.js, Recht bleibt „ReadItem") und öffnet die Antwort in
      Outlook; Jarvis formuliert nur. Der Serverzugriff auf Postfächer (Regeln,
      Mail-Werkzeuge, /email) bleibt vorerst für Benutzer, die unter
      Einstellungen → E-Mail ausgewählt sind.
- [ ] **Outlook (Stufe 2)** – über die Zukunft des Serverzugriffs entscheiden
      (gespeicherte Postfach-Kennwörter); ggf. Jarvis als Wissensquelle für den
      Antwortvorschlag.
