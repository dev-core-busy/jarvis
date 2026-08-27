# Jarvis für Jira – Browser-Erweiterung

Wer ein Jira-Ticket offen hat, bekommt über das Symbol in der Symbolleiste

* eine **Zusammenfassung** des Vorgangs (worum es geht, was passiert ist, woran es hängt) und
* einen **Antwortvorschlag** an den Melder, den ein Klick ins Jira-Kommentarfeld einfügt.

**Abgeschickt wird in Jira, von Hand.** Jarvis schreibt nichts in ein Ticket.

## Zwei Fenster, und warum

| | wo | wofür |
|---|---|---|
| **Popup** | Fenster am Symbol | Anmeldung und Einrichtung |
| **Panel** | rechts **in** der Jira-Seite | die eigentliche Arbeit |

Gemeldet aus dem Betrieb: *„Fenster und Ergebnis verschwindet, wenn z. B. der Tab gewechselt
wird.“* Ein Browser-Popup schließt, sobald der Benutzer daneben klickt – also genau dann, wenn
er in den Jira-Tab wechselt, um das Kommentarfeld zu öffnen. Deshalb sitzt die Arbeitsfläche
seit Version 0.2 **in der Seite**: ein Klick auf das Symbol setzt sie per
`scripting.executeScript` dort ein, und sie bleibt stehen.

Zwei Gewinne, ein Preis:

* Das Panel überlebt Klicks daneben, den Tabwechsel und einen Wechsel des Tickets innerhalb
  der Anwendung.
* **Das Einfügen wird zuverlässiger**, weil das Panel das Kommentarfeld direkt sieht. Es merkt
  sich, in welchem Feld der Benutzer zuletzt war, und schreibt genau dorthin – aus einem Popup
  heraus war `document.activeElement` bereits verloren.
* **Aber:** ein echtes Neuladen der Seite räumt das Panel ab (Jira Server/DC lädt `/browse/…`
  oft voll neu). Das Ergebnis liegt weiter im Speicher der Erweiterung und ist nach einem Klick
  auf das Symbol wieder da – genau dafür gibt es das Gedächtnis.

Welches der beiden Fenster ein Klick öffnet, entscheidet der Hintergrund über
`action.setPopup()`: angemeldet = Panel, sonst die Anmeldung. Das ist zugleich der Weg zurück –
nach dem Abmelden oder einem abgelaufenen Token (401) erscheint wieder die Maske.

**Der Ticketbezug ist dabei eine Sicherheitsfrage, keine Bequemlichkeit.** Weil das Panel stehen
bleibt, kann der Benutzer längst bei Ticket B sein, während der Text zu Ticket A gehört. Die
Adresse wird deshalb überwacht; bei einer Abweichung steht eine Warnung mit **beiden** Nummern
im Fenster, und das Einfügen fragt zurück.

## Wie es arbeitet

Die Erweiterung liest **nur die Ticketnummer aus der Adresszeile** (`…/browse/ABC-123`).
Beschreibung und Kommentarverlauf holt der Jarvis-Server selbst über die Jira-API – die
Erweiterung liest den Seiteninhalt nicht. Das ist bewusst so: das DOM ändert sich mit jeder
Jira-Version, die URL nicht, und über die API kommt der vollständige Verlauf statt dessen,
was gerade aufgeklappt ist.

Dahinter läuft **kein Agent**, sondern ein einzelner Modellaufruf ohne Werkzeuge. Der Grund
steht im Kopf von `backend/jira_assist.py`: in ein Ticket schreibt ein Kunde, was er will.

## Voraussetzungen

1. Der **Jira-Skill** ist in Jarvis aktiv und konfiguriert (Adresse + Token).
2. Das eigene Konto ist freigeschaltet unter
   *Einstellungen → Sicherheit → Berechtigungen → Jira-Assistent*.
   **Leer heißt niemand** – ohne Eintrag antwortet der Server mit 403, auch Administratoren.
3. Jarvis ist unter **genau dem Namen** erreichbar, auf den sein Zertifikat lautet.
   Nicht über die IP-Adresse: der Aufruf läuft im Hintergrund der Erweiterung, und dort gibt
   es kein „trotzdem fortfahren“ wie in einem Tab – er bricht wortlos ab. `GET
   /api/jira/assist/health` sagt, ob das Zertifikat die benutzte Adresse abdeckt.

## Installieren

```bash
./bauen.sh          # erzeugt dist/jarvis-jira-chrome.zip und -firefox.zip
```

### Chrome / Edge

`chrome://extensions` bzw. `edge://extensions` → **Entwicklermodus** einschalten →
**Entpackt laden** → den Ordner `browser-addon/` wählen (nicht das ZIP).

Beim ersten Anmelden fragt der Browser nach dem Zugriffsrecht für die eingetragene
Jarvis-Adresse. Ohne dieses Recht kann die Erweiterung den Server nicht erreichen.

### Firefox

`about:debugging` → **Dieses Firefox** → **Temporäres Add-on laden** →
`dist/jarvis-jira-firefox.zip`.

> **Temporär heißt temporär** – beim Beenden von Firefox ist die Erweiterung weg.
> Dauerhaft geht in Firefox **nur mit einer Signatur von Mozilla**, und zwar auch für
> selbst verteilte Add-ons: *„All add-ons must be submitted for signing, even if you
> distribute them outside AMO.“* Der Weg dafür ist ein **unlisted**-Upload auf
> addons.mozilla.org; das Paket wird signiert, erscheint aber nicht im öffentlichen
> Verzeichnis. Die automatische Prüfung dauert bis zu 24 Stunden.
>
> Zu bedenken: **der Code geht dabei an Mozilla.** Die Serveradresse steht deshalb nicht im
> Manifest, sondern wird beim ersten Anmelden eingetragen – im Paket steht kein interner Name.

## Verteilen (Phase 2, noch nicht gebaut)

* **Chrome/Edge:** `ExtensionInstallForcelist` per Gruppenrichtlinie, dazu eine selbst
  gehostete `update_manifest.xml` und ein signiertes `.crx` auf dem Jarvis-Server.
  Anders als beim Outlook-Add-in kommen Updates damit automatisch – Microsoft zieht ein
  geändertes Add-in-Manifest nie nach, Chrome schon.
* **Firefox:** `ExtensionSettings` mit `install_url` auf die signierte XPI.

## Aufbau

| Datei | Rolle |
|---|---|
| `manifest.json` | Chrome/Edge – `background.service_worker` |
| `manifest.firefox.json` | Firefox – `background.scripts` + `gecko.id` |
| `background.js` | **alle** Netzaufrufe, der Klick auf das Symbol, das Umschalten Popup/Panel |
| `popup.js` / `.html` / `.css` | Anmeldung und Einrichtung |
| `panel.js` | die Arbeitsfläche – wird auf Klick in die Jira-Seite injiziert |
| `einfuegen.js` | findet das Kommentarfeld; injiziert **und** im Hintergrund geladen |

`einfuegen.js` ist bewusst **kein ES-Modul**: es wird an zwei Orten geladen, und keiner davon
kann `import` – per `executeScript({files})` in die Jira-Seite (injizierte Dateien sind immer
klassische Skripte) und im Hintergrund (Chrome per `importScripts`, Firefox als erster Eintrag
in `background.scripts`). Es registriert sich in `globalThis.__jvEinfuegen`.

Das Panel-Markup liegt in einem **Shadow DOM**: die Jira-Seite sieht genau ein Element, unsere
Klassennamen können mit nichts kollidieren, und Jiras CSS erreicht unsere Knöpfe nicht. Die
Gestaltung steht deshalb als Zeichenkette in `panel.js` – eine CSS-Datei müsste geholt werden
(kein `fetch`, siehe unten) oder per `insertCSS` in die Seite gelegt werden, und dort erreicht
sie den Shadow DOM gar nicht.

**Warum alle Aufrufe im Hintergrund:** unter Manifest V3 unterliegen Content-Scripts der
CORS-Regel der Seite, in der sie laufen; `host_permissions` wirken dort nicht. Nur
Hintergrund-Skripte haben erweiterte Rechte. Gemessen: der Jarvis-Server beantwortet einen
Preflight von `chrome-extension://…` mit **400 Disallowed CORS origin** – aus dem Hintergrund
entsteht dieser Preflight gar nicht erst. Wer einen `fetch` ins Popup oder ins Panel verschiebt,
bricht die Erweiterung mit einer Meldung, die nach einem Serverfehler aussieht. Das Panel redet
deshalb ausschließlich über `runtime.sendMessage` mit dem Hintergrund.

Aus demselben Grund gibt es **kein dauerhaftes Content-Script**: eines auf `https://*/*` würde
bei der Installation „Alle deine Daten auf allen Websites lesen und ändern“ verlangen. Das Panel
entsteht nur auf Klick, und `activeTab` gibt das Recht genau dann und nur für diesen Tab.

## Was noch nicht geprüft ist

* **Das Panel gegen ein echtes Jira.** Panel und Einfügen sind gegen ein nachgebautes DOM
  ausgeführt getestet (Textarea, TinyMCE-iframe, contenteditable, unsichtbares Feld, kein Feld,
  gemerktes Feld, Ticketwechsel, Aufräumen) – aber welchen Editor die Jira-Instanz im Haus
  wirklich ausliefert, ist offen. Ebenso ungeprüft: ob Jiras eigenes CSS oder ein
  Layout-Container das Panel im echten Betrieb verdeckt.
  Findet sich kein Feld, sagt die Erweiterung das und bietet **Kopieren** an; sie tut nie so,
  als hätte sie eingefügt.
* **Ein Lauf im echten Browser.** Die CORS-Freistellung im Hintergrund ist durch die
  Herstellerdoku belegt, aber hier noch nicht mit einem installierten Paket gemessen.
