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
- [x] **Wissensdatenbank beim Antwortvorschlag** – mit Freigabe des Bereichs
      „Wissensdatenbank (lesend)“ unter Einstellungen → E-Mail darf der Vorschlag
      nachschlagen (nur lesend); das Add-in zeigt, ob und wie oft.
- [x] **Exchange-Explorer entfernt** (Einstellungen → E-Mail).
- [ ] **Outlook (Stufe 2)** – über die Zukunft des Serverzugriffs entscheiden
      (gespeicherte Postfach-Kennwörter der noch ausgewählten Benutzer).

## Vor der Freigabe von E-Mail für alle Benutzer

Aus der Sicherheitsprüfung vor dem Pentest (2026-11-05), bewusst zurückgestellt,
solange E-Mail nur für Testbenutzer freigeschaltet ist:

- [ ] **Mailregeln mit Außenwirkung** – eine Regel mit „Außenwirkung“ lässt den
      Agenten auf eine eingehende fremde Mail hin ohne Bestätigung antworten oder
      weiterleiten. Ein Absender kann damit per eingeschleuster Anweisung Mails
      nach außen weiterleiten lassen. Vor der breiten Freigabe festlegen: ohne
      Bestätigung nur an interne Empfänger (oder nur Antwort an den Absender),
      und Bestandsregeln nicht mehr automatisch auf „an“ setzen
      (`mail_rules.py`, `mail_runner.py`, `wirkung.py`).

## Short Tracks: Fragefeld und Referenzdateien – weitere Ausbaustufen

Gebaut ist (2026-11-06): Referenzdateien je Ablage (z. B. ein
Datenbankschema), die jedem Lauf beiliegen, und ein zuschaltbares Fragefeld
auf der Karte – die Antwort ist Text bzw. SQL, Einzelfragen ohne Verlauf,
Referenzen bis 24.000 Zeichen direkt im Auftrag. Offen:

- [ ] **SQL gegen eine echte Datenbank ausführen** – statt nur SQL
      vorzuschlagen, die Abfrage ausführen und das Ergebnis zeigen. Braucht:
      Verbindungsdaten im Tresor (nicht in der Ablage), einen ausschließlich
      lesenden Datenbankbenutzer, Grenzen für Laufzeit und Ergebnisgröße und
      einen eigenen Werkzeug-Bereich, den ein Administrator freigibt
      (`short_tracks.BEREICHE`).
- [ ] **Nachfragen mit Verlauf** („und jetzt nur 2025“) – heute ist jede Frage
      ein eigener Lauf. Ein Gesprächsfaden je Ablage und Benutzer wäre ein neues
      Konzept: `run_task_headless` hat bewusst keinen Chat-Verlauf, der
      Verlauf müsste begrenzt, je Benutzer getrennt und beim Zurücksetzen
      mitgelöscht werden.
- [ ] **Große Schemata gezielt nachschlagen** – heute wird der Text aller
      Referenzen gekürzt in den Auftrag gelegt (24.000 Zeichen, je Datei
      mindestens 4.000), der Rest ist nur über die Arbeitskopie erreichbar.
      Für sehr große Schemata: eine Suche über die Referenzen (Tabellen-/
      Spaltennamen), die das Modell gezielt abfragt, statt bei jeder Frage den
      ganzen Text mitzuschicken.

## Verschlüsselte Verbindung zu LLM- und Sprachserver

Aus der Sicherheitsprüfung vor dem Pentest (2026-11-08):

- [ ] **TLS zum LLM- und STT-Server** – mehrere LLM-Profile sprechen per
      `http://`, die Spracherkennung per `ws://` mit den internen Servern.
      Chatinhalte (auch Kunden- und Ticketdaten), der API-Schlüssel des
      LLM-Servers und Audio gehen damit unverschlüsselt durchs Netz. Schritte:
      TLS auf LLM- und STT-Server aktivieren (IT), danach die Profile auf
      `https://` bzw. `wss://` umstellen (Einstellungen → KI-Profile,
      Sprachausgabe/-erkennung). Ein HTTPS-Profil existiert bereits.
