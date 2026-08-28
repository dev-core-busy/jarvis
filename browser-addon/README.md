# Jarvis für Jira – Browser-Erweiterung

Wer ein Jira-Ticket offen hat, bekommt über das Symbol in der Symbolleiste

* eine **Zusammenfassung** des Vorgangs (worum es geht, was passiert ist, woran es hängt) und
* einen **Antwortvorschlag** an den Melder, den ein Klick ins Jira-Kommentarfeld einfügt.

**Abgeschickt wird in Jira, von Hand.** Jarvis schreibt nichts in ein Ticket.

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

## Verteilen über eine Netzfreigabe (der Weg, der heute benutzt wird)

Statt jeden Benutzer das Paket herunterladen zu lassen, kann es auf einer Netzfreigabe
liegen. Die Anleitungsseite `/jira-addon` zeigt dann **den Pfad zum Kopieren statt des
Download-Knopfes** – eingetragen wird er unter *Einstellungen → Jira → Browser Plugin
Bereitstellung* (Felder `addon_pfad_chrome`, `addon_pfad_firefox` der Skill-Config).

* **Chrome/Edge** braucht den **entpackten Ordner** – der Browser lädt eine Erweiterung
  nie aus einem ZIP. Auf der Freigabe liegt also der Ordnerinhalt.
* **Firefox** braucht die **ZIP-Datei** selbst.

⚠ **Das gebrandete Paket kommt vom SERVER, nicht aus `bauen.sh`.** Marke, Beschreibung und
**Symbol** setzt erst `jira_assist.paket_bauen` beim Abruf zusammen; `bauen.sh` erzeugt
bewusst ein neutrales Paket für die Entwicklung. Wer die Datei für die Freigabe braucht,
holt sie in der Anleitung: *Portal → Jira-Assistent* zeigt Administratoren die
Download-Knöpfe auch dann noch, wenn dort für alle anderen längst der Netzwerkpfad steht.

⚠ **Die Kopie auf der Freigabe driftet.** Sie trägt den Stand des Kopiermoments. Nach einer
Aktualisierung gehört sie **neu** dorthin, sonst installieren die Benutzer weiter den alten
Stand, und niemand sieht warum.

Die Felder leer zu lassen ist ein gültiger Zustand: dann bleibt es beim Download-Knopf.
Der Pfad steht bewusst **nicht im Quelltext** – er ist hausintern, dieses Repo ist
öffentlich, und auf einem anderen Server gibt es die Freigabe nicht.

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
| `background.js` | **alle** Netzaufrufe |
| `popup.js` / `.html` / `.css` | die Oberfläche |
| `einfuegen.js` | wird auf Klick in die Jira-Seite injiziert |

**Warum alle Aufrufe im Hintergrund:** unter Manifest V3 unterliegen Content-Scripts der
CORS-Regel der Seite, in der sie laufen; `host_permissions` wirken dort nicht. Nur
Hintergrund-Skripte haben erweiterte Rechte. Gemessen: der Jarvis-Server beantwortet einen
Preflight von `chrome-extension://…` mit **400 Disallowed CORS origin** – aus dem Hintergrund
entsteht dieser Preflight gar nicht erst. Wer einen `fetch` ins Popup oder ins injizierte
Skript verschiebt, bricht die Erweiterung mit einer Meldung, die nach einem Serverfehler
aussieht.

## Was noch nicht geprüft ist

* **Das Einfügen ins Jira-Kommentarfeld gegen ein echtes Jira.** Die Funktion ist gegen ein
  nachgebautes DOM getestet (Textarea, TinyMCE-iframe, contenteditable, unsichtbares Feld,
  kein Feld) – aber welchen Editor die Jira-Instanz im Haus wirklich ausliefert, ist offen.
  Findet sich kein Feld, sagt die Erweiterung das und bietet **Kopieren** an; sie tut nie so,
  als hätte sie eingefügt.
* **Ein Lauf im echten Browser.** Die CORS-Freistellung im Hintergrund ist durch die
  Herstellerdoku belegt, aber hier noch nicht mit einem installierten Paket gemessen.
