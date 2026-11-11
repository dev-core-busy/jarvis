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
auf der Karte – die Antwort ist Text bzw. SQL, Referenzen bis 24.000 Zeichen
direkt im Auftrag. Seit 2026-11-08 mit Nachfragen: die bisherigen Fragen
desselben Benutzers an die Ablage gehen mit (12.000 Zeichen, 12 Stunden). Offen:

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

## Sicherheit und Betrieb

- [ ] **Zertifikat des Domänencontrollers (Produktivsystem) – Frist 27.12.2026.**
      Läuft der hinterlegte Anker ab, ohne dass er vorher erneuert wurde, bricht
      die AD-Anmeldung. Alternative: die interne Zertifizierungsstelle in den
      Systemspeicher aufnehmen und den Domänencontroller per FQDN ansprechen.
- [ ] **Sicherheitsprotokoll ans SIEM weiterleiten** (BSI M2 Teil B) – wartet
      auf die angeforderten Zugangsdaten; vorher nichts bauen, was das Ziel
      raten müsste. Bauplan: `deploy/security/siem_weiterleitung.sh` nach dem
      Muster von `ssh_haertung.sh`, Ziel nur in `/etc/jarvis/broker.conf`,
      rsyslog per TCP+TLS mit Zertifikatsprüfung und Plattenpuffer, tägliches
      Lebenszeichen der Hash-Kette, journald-Aufbewahrung ein Jahr.
- [ ] **CSP erzwingen** (BSI H4, Rest) – von „melden“ auf „erzwingen“
      umstellen und die verbliebenen Inline-Stile entfernen.

## SQL-Assistent

Seit 2026-11-11 hängen Einstellungen und Erfassung am Schema (je Schema ein
Container im Reiter). Offen:

- [ ] **Gleichnamige Tabellen in zwei Schemata** – steht dieselbe Tabelle
      (Datenbankschema.Name, z. B. `erp.kunde`) in zwei Schemata, bleibt im
      Graphen nur die des ersten Schemas stehen; im zweiten fehlt sie, der Lauf
      zählt sie lediglich als „doppelt“. Im Sandkasten gemessen (2026-11-11).
      Trifft z. B. Test- und Produktivstand derselben Datenbank als zwei
      Schemata. Kern des Umbaus: Namen je Schema auflösen statt über den ganzen
      Bestand (`schema_graph_store.ableiten`, `_Aufloeser`) – und festlegen, wie
      Suche, Prüfung und Join-Pfade einen Namen auflösen, wenn beide Schemata
      gewählt sind (`schema_graph_rag.py`, `schema_graph_dienst.py`).

## Ausbau

- [ ] **Lösungsarchiv: erster echter Lauf auf DEV** – erst, wenn der laufende
      Wissensgraph-Lauf auf DEV fertig ist. Kurzer Zeitraum (~4 Wochen),
      Test-Wissensgruppe. Messen: Ähnlichkeitsschwelle (0,80 ist ungemessen –
      mehrere Schwellen fahren, Positivkontrolle mit zwei absichtlich gleichen
      Tickets), Anonymisierung an echten Texten, JSON-Quote wiederholt, landet
      die veröffentlichte Datei im Wissensgraphen.
- [ ] **Mehrere Postfächer je Benutzer** (E-Mail) – heute genau eines. Kern des
      Umbaus ist nicht das Datenmodell, sondern die Bindung im Lauf: das
      Postfach kommt aus der Regel bzw. dem Add-in-Token, nie aus dem Modell
      oder dem Nachrichtentext (kein `postfach=`-Argument an Werkzeugen).
      Aussetzer-Zähler je Postfach, Auswahl in `/email` und im Add-in.
- [ ] **Portal-Kachel „Support-Agent“ umbauen** – die Kachel ist versteckt
      (`hidden` in `frontend/portal.html`), `/supportagent` bleibt erreichbar.
      Was umgebaut werden soll, ist noch nicht festgelegt – vor dem Bauen klären.
- [ ] **MCP-Restpunkte** (bewusst offen) – kein OAuth/PKCE im Client;
      MCP-Server laufen außerhalb von Skill-Lebenszyklus, Lizenzzählung und
      Skill-Audit.
- [ ] **Vision „Tür öffnen“** ist ein Platzhalter
      (`skills/vision/vision_engine.py`) – GPIO-/Relais-/API-Anbindung fehlt.

## Optional / Ideen

- [ ] **Spracherkennung:** Fachwörter (Jira, Confluence, SAP, Firewall …) als
      `initial_prompt` für `/api/stt`, vorher/nachher messen (Fehlerquote und
      Zeit); Android-App mit `EXTRA_PREFER_OFFLINE` oder über `transcribe_only`;
      Whisper-Modell für abgeschottete Server vorab bereitstellen
      (`HF_HUB_OFFLINE`).
