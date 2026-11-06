# Microsoft 365 Copilot als Recherche-Werkzeug

Der Skill **Microsoft 365 Copilot** gibt dem Agenten das Werkzeug
`copilot_recherche`: er stellt eine Frage, Copilot sucht im Internet (Bing) und
im Bestand des Unternehmens und antwortet mit Quellenangaben.

> **Reifegrad.** Die Chat API steht bei Microsoft unter `/beta`, und Microsoft
> schreibt dazu: *„Use of these APIs in production applications is not
> supported."* Für einen Erprobungsbetrieb geeignet, für den Produktivserver
> erst nach deren Freigabe.

---

## 1. Was vorhanden sein muss

| | |
|---|---|
| **Lizenz** | Eine **Microsoft 365 Copilot**-Add-on-Lizenz für **jeden** Benutzer, der recherchieren soll. Die Chat API gibt es nur mit Add-on; ohne sie antwortet Microsoft mit 403. |
| **Mandant** | Ein Microsoft-365-Mandant mit Entra ID. |
| **Web-Suche** | Die Mandanten-Richtlinie **„Allow web search in Copilot"** (Cloud Policy Service) darf die Web-Suche nicht abschalten. Ist sie nicht konfiguriert, ist Web-Suche an. |
| **Internet-Freigabe** | Jeder recherchierende Benutzer braucht in Jarvis die Internet-Freigabe (Einstellungen → Sicherheit → Berechtigungen). **Leer = niemand**, kein Admin-Bypass. |

**Nicht möglich** – und das ist eine Grenze von Microsoft, keine Entscheidung
von Jarvis: Läufe ohne angemeldeten Benutzer. Die Chat API unterstützt
ausschließlich delegierte Rechte („Application: Not supported"), es gibt also
kein Dienstkonto. Zeitplan-Aufträge, WhatsApp, Mail-Regeln und die Agenten-API
können das Werkzeug nicht nutzen.

---

## 2. Anwendung in Entra ID anlegen

**Eine eigene Registrierung, nicht die des Outlook-Add-ins.** Diese Anwendung
braucht sieben Graph-Leseberechtigungen – darunter `Mail.Read` und
`Sites.Read.All` –, und diese Rechtefläche gehört nicht an einen Anmeldeweg.

1. Entra-Portal → **App-Registrierungen** → *Neue Registrierung*.
   Name frei, Kontotypen: *nur eigenes Verzeichnis*. **Keine** Umleitungs-URI.
2. → **Authentifizierung**: *Öffentliche Clientflows zulassen* auf **Ja**.
   Das ist die Voraussetzung für die Gerätecode-Anmeldung.
   **Kein Clientgeheimnis anlegen** – es wird nicht gebraucht, und der Skill
   nimmt auch keines an.
3. → **API-Berechtigungen** → *Microsoft Graph* → *Delegierte Berechtigungen*,
   alle sieben hinzufügen (**alle**, nicht eine Auswahl – Microsoft:
   *„You need all of these Microsoft Graph permissions to successfully call the
   Microsoft 365 Copilot Chat API"*):

   ```
   Sites.Read.All   Mail.Read   People.Read.All   OnlineMeetingTranscript.Read.All
   Chat.Read        ChannelMessage.Read.All       ExternalItem.Read.All
   ```

   Danach **Administratorzustimmung erteilen**.
4. Aus der Übersicht notieren: **Anwendungs-ID (Client)** und
   **Verzeichnis-ID (Mandant)**.

---

## 3. In Jarvis eintragen

Einstellungen → **Skills** → *Microsoft 365 Copilot* aktivieren. Damit erscheint
der Reiter **Copilot**; dort oben unter *Entra-Anwendung* die beiden Kennungen
eintragen (Mandanten-Kennung, Anwendungs-Kennung).

---

## 4. Konto verbinden (je Benutzer, einmalig)

Im Reiter **Copilot** unter *Verbindung*. Die Fläche nennt zuerst, was noch
fehlt – abgeschalteter Skill, fehlende Entra-Anwendung oder fehlende
Internet-Freigabe –, und zwar mit der Stelle, an der es hängt; der Knopf bleibt
solange gesperrt, statt später mit einem Fehler zu antworten.

Dann: **Microsoft-Konto verbinden** → die angezeigte Seite öffnen, den Code
eintippen, anmelden. Die Fläche holt das Ergebnis selbst ab und zeigt danach
das verbundene Konto. **Verbindung lösen** gibt es daneben; das ist nicht
rücknehmbar, deshalb mit Rückfrage.

Dasselbe über die Endpunkte, etwa für eine Messung:

```bash
curl -sk -X POST https://<server>/api/copilot/device-start -H "Authorization: Bearer <token>"
```

```bash
curl -sk https://<server>/api/copilot/device-status -H "Authorization: Bearer <token>"
```

Dazu `GET /api/copilot/status` (eingerichtet, verbunden, Konto,
Internet-Freigabe, Skill aktiv) und `DELETE /api/copilot/connection`. Alle vier
arbeiten **nur** mit dem angemeldeten Benutzer – der Benutzer kommt nie aus dem
Rumpf, sonst wäre das der Weg in eine fremde Verbindung.

---

## 5. Was der Benutzer wissen muss

**Die Frage verlässt das Haus.** Copilot bildet aus ihr eine eigene Suchanfrage
und sendet sie samt Client-IP an die Bing-Suche. Microsoft stellt klar, dass für
diese Suchanfragen weder der Datenschutz-Nachtrag (DPA) noch die EU Data
Boundary gelten; Bing arbeitet getrennt von Microsoft 365.

* Es findet **keine automatische Anonymisierung** statt. Die
  Werkzeug-Beschreibung hält das Modell zu einer sachlichen Formulierung ohne
  Kundennamen an – das ist eine Bitte, keine Schranke.
* **Mandanten-Grounding ist mitgeschaltet** und per API nicht abschaltbar: eine
  Antwort kann auch Postfach-, SharePoint- oder Teams-Inhalte des Benutzers
  enthalten. Was eingeflossen ist, steht in den Quellen.
* Jede Recherche steht mit ihrer Frage im Audit-Log.

## 6. Wie es gegen Prompt Injection abgesichert ist

Copilot bekommt **keine** Jarvis-Werkzeuge, und die Chat API könnte ihm auch
keine geben – sie liefert ausschließlich Text. Eine präparierte Webseite kann
darüber also keine Aktion auslösen, höchstens den Antworttext beeinflussen.
Damit ist die Recherche dieselbe Klasse wie eine Wissenssuche oder ein
Ticket-Kommentar, und dagegen greift die bestehende Abwehr:
`backend/werkzeug_rahmen` rahmt und entschärft **jedes** Werkzeugergebnis
(BSI H8), bevor es an das Modell geht.

Dass das nötig ist, ist belegt: **EchoLeak (CVE-2025-32711, CVSS 9.3)** war ein
Zero-Click-Angriff auf genau diese Produktlinie – eine präparierte E-Mail
genügte, vorbei an Microsofts eigenem Injektions-Klassifizierer. Serverseitig
behoben, die Fehlerklasse ist damit nicht erledigt.

## 7. Geprüft

* `tests/test_copilot_recherche.py` (103 Prüfungen; `execute()` läuft wirklich,
  die HTTP-Aufrufe werden gezählt, `is_sensitive`/`authorize_fs`/
  `authorize_shell`/`harden_data_dirs` laufen echt)
* `tests/gegen_copilot_recherche.py` – **14 von 14 Proben beißen einzeln**
* `tests/live_copilot_dev.py` – auf DEV 27 OK, 0 FAIL über den echten Dienst;
  der Graph-Teil ist dort ausdrücklich **nicht gemessen** (keine Entra-Anwendung
  hinterlegt) und als solcher ausgewiesen
* `tests/test_copilot_ui.js` (90 Prüfungen; jsdom gegen die **echten** Dateien –
  echtes `settings.html`, echtes `i18n.js`, echtes `copilot.js`; der Abhol-Takt
  wird gezählt, nicht im Quelltext gelesen)
* `tests/gegen_copilot_ui.py` – **16 von 16 Proben beißen einzeln**. Probe 11
  hat dabei einen Mangel im Wächter selbst gefunden: `\.cp-code\b` matchte auch
  in `.cp-code-ungenutzt`, eine umbenannte CSS-Regel hätte weiter als
  „definiert" gegolten

Die Token-Ablage `data/copilot_auth/tokens.json` steht in allen vier Sperrlisten
der Sandbox (`_APP_DENY_REL`, `PRIVATE_DIRS`, `PRIVATE_FILES_STRENG`,
`SHELL_SECRET_PATHS`) – gesperrt ist das **Verzeichnis**, damit eine künftige
zweite Datei von sich aus erfasst ist.
