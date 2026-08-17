# Outlook-Add-in

Bringt den Bereich **/email** in ein Aufgabenfenster in Outlook: eigenes Postfach
hinterlegen, Regeln anlegen und pflegen, Protokoll lesen – und zusätzlich das,
wofür es ein Add-in überhaupt braucht: **die gerade markierte Nachricht sofort
mit einer Regel verarbeiten**.

---

## 1. Zuerst das Wichtigste: wo es läuft – und wo nicht

Es ist ein **Office-Web-Add-in** (Office.js). Das ist keine Vorliebe, sondern die
einzige tragfähige Bauform: das neue Outlook für Windows unterstützt **keine
VSTO- und COM-Add-ins** mehr, migriert werden muss auf Web-Add-ins.

| Client | Läuft das Add-in? |
|---|---|
| **Klassisches Outlook für Windows** (Microsoft 365 / Office 2021+, Windows 11) | **Ja** |
| **Outlook im Web** (OWA des eigenen Exchange 2019) | **Ja** |
| **Outlook für Mac** (aktuelle Versionen) | Ja |
| **Neues Outlook für Windows** – Postfach in **Exchange Online** | Ja |
| **Neues Outlook für Windows** – Postfach auf **Exchange im Haus** | **Nein – und das liegt nicht am Add-in** |

> **Die Einschränkung kommt von Microsoft, nicht von uns.** Das neue Outlook für
> Windows unterstützt derzeit **keine On-Premises-, Hybrid- oder Sovereign-
> Exchange-Konten**; es kann ein Postfach auf einem Exchange 2019 im Haus gar
> nicht erst öffnen („We couldn't reach the email server"), unabhängig von
> Add-ins. Wer sein Postfach auf dem hauseigenen Exchange hat, benutzt also
> **klassisches Outlook oder Outlook im Web** – dort läuft dieses Add-in
> vollständig.
>
> Quellen:
> [Supported accounts in new Outlook for Windows](https://learn.microsoft.com/en-us/microsoft-365-apps/outlook/get-started/supported-account-types) ·
> [Develop Outlook add-ins for the new Outlook on Windows](https://learn.microsoft.com/en-us/office/dev/add-ins/outlook/one-outlook)
>
> Sobald Microsoft On-Premises-Konten im neuen Outlook unterstützt, läuft das
> Add-in dort **ohne Änderung** mit – das Manifest deckt diesen Client bereits ab.

Das Manifest wurde mit Microsofts eigenem Prüfwerkzeug abgenommen
(`npx office-addin-manifest validate` → *„The manifest is valid."*). Als
unterstützte Plattformen meldet es: Outlook 2016/2019+ auf Windows und Mac,
Outlook im Web sowie Outlook auf Windows (Microsoft 365).

---

## 2. Voraussetzungen

1. **Der E-Mail-Skill ist aktiv** (*Einstellungen → Skills*), Serverdaten sind
   unter *Einstellungen → E-Mail* hinterlegt, und die Benutzer sind unter
   *Sicherheit → Berechtigungen → E-Mail-Zugriff* freigeschaltet. Ohne das sagt
   das Aufgabenfenster im Klartext, was fehlt – es funktioniert dann nur nicht.
2. **Der Jarvis-Server ist per HTTPS unter einem Namen erreichbar, dem der
   Arbeitsplatz vertraut.** Das ist die häufigste Hürde: Office lädt
   Add-in-Inhalte ausschließlich über HTTPS, und ein Zertifikat, dem Windows
   nicht traut, führt zu einem **leeren Aufgabenfenster ohne Fehlermeldung**.
   * Bei einem selbst ausgestellten Zertifikat muss `jarvis.cer` auf jedem
     Arbeitsplatz unter *Vertrauenswürdige Stammzertifizierungsstellen* liegen
     (per Gruppenrichtlinie verteilbar) – derselbe Schritt, der auch für die
     Kennwortverwaltung des Browsers nötig ist.
   * Bequemer ist ein regulär ausgestelltes Zertifikat für den internen Namen.
3. **Steht der Server hinter einem Rückwärtsproxy**, muss die im Manifest
   verwendete Adresse die sein, die der *Arbeitsplatz* aufruft. Notfalls fest
   setzen: `JARVIS_ADDIN_BASE=https://jarvis.firma.intern` in der Umgebung des
   Dienstes (oder `addin_base_url` in den Einstellungen). Ohne Angabe wird die
   Adresse aus der Anfrage abgeleitet, was in den meisten Fällen genügt.

---

## 3. Manifest holen

**Für Benutzer – der normale Weg:** im Bereich **/email** steht der Abschnitt
*Outlook-Add-in* mit dem Knopf **„Add-in-Datei herunterladen"** und einer
Kurzanleitung. Dafür sind **keine Administrator-Rechte nötig**; jeder, der den
E-Mail-Bereich benutzen darf, kann sich das Add-in selbst einrichten.

**Direkt (für Administratoren und zum Verteilen):**

```
https://<jarvis-server>/addin/manifest.xml
```

Die Datei wird zum Download angeboten (`jarvis-outlook-addin.xml`). Sie wird
**bei jedem Abruf neu erzeugt** und enthält bereits die richtigen Adressen –
es ist nichts von Hand zu ersetzen.

> **Die Adresse muss die sein, unter der die Arbeitsplätze den Server
> erreichen.** Ein Abruf über `localhost` oder `127.0.0.1` (etwa direkt auf dem
> Server oder durch einen SSH-Tunnel) wird deshalb mit **HTTP 400 abgelehnt** –
> ein solches Manifest ließe sich klaglos installieren, und das Aufgabenfenster
> bliebe danach leer. Wo der Host-Kopf nicht stimmt (Rückwärtsproxy), setzt man
> `JARVIS_ADDIN_BASE` bzw. die Einstellung `addin_base_url`.

> Nicht von Hand bearbeiten. Änderungen gehen beim nächsten Abruf verloren; alles
> Einstellbare steckt in der Serverkonfiguration (Name folgt dem Branding).

---

## 4. Installieren

### Weg A – einzelner Benutzer, Outlook im Web (schnellster Weg zum Ausprobieren)

1. Outlook im Web öffnen → **Einstellungen** → **Allgemein** → **Add-Ins verwalten**
   (bzw. *Meine Add-Ins*).
2. **Benutzerdefiniertes Add-In hinzufügen** → **Aus Datei hinzufügen…**
3. Die Datei `jarvis-outlook-addin.xml` wählen, Warnung bestätigen.

Das Add-in erscheint danach **auch im klassischen Outlook am Arbeitsplatz** –
Web-Add-ins hängen am Postfach, nicht am Gerät.

### Weg B – für alle Benutzer, Exchange im Haus

In der **Exchange-Verwaltungskonsole**:

*Organisation → Apps → +  → Aus Datei hinzufügen* (bzw. per PowerShell)

```powershell
New-App -OrganizationApp -FileData ([System.IO.File]::ReadAllBytes("C:\jarvis-outlook-addin.xml")) `
        -DefaultStateForUser Enabled
```

Auf einzelne Benutzer begrenzen mit `-Mailbox <postfach>` statt `-OrganizationApp`.

### Weg C – Microsoft 365 (nur wenn die Postfächer in der Cloud liegen)

*Microsoft 365 Admin Center → Einstellungen → Integrierte Apps → App hochladen →
Benutzerdefinierte App → Manifestdatei hochladen*.

---

## 5. Bedienung

Im Menüband einer geöffneten E-Mail erscheint die Gruppe mit dem Knopf
**„&lt;Marke&gt; E-Mail"**. **Beim ersten Öffnen meldet man sich einmal an** –
denselben Daten wie im Browser. Ab dann meldet sich das Fenster von selbst an
(siehe Abschnitt 5.1). Danach vier Reiter:

| Reiter | Inhalt |
|---|---|
| **Nachricht** | Betreff und Absender der markierten Mail, **Antwort vorschlagen** (Abschnitt 5.2), Auswahl einer aktiven Regel, **Jetzt verarbeiten** |
| **Regeln** | Regeln anlegen, ändern, pausieren, Testlauf, löschen – vollständig wie in `/email` |
| **Postfach** | eigene Zugangsdaten, Ordner, Verbindungstest |
| **Protokoll** | die letzten Läufe mit Ergebnis |

**„Jetzt verarbeiten" ist echt, kein Trockenlauf.** Die Regel läuft auf genau
dieser Nachricht und kann tatsächlich antworten, weiterleiten oder verschieben –
deshalb die Rückfrage davor. Die Auswahl-Filter der Regel (nur ungelesen,
Absender, Betreff) gelten hier bewusst **nicht**: die Nachricht wurde von Hand
gewählt. Die Nachricht gilt danach als verarbeitet, damit die Automatik sie nicht
ein zweites Mal beantwortet.

### 5.1 Anmeldung ohne Kennwort (einmal anlernen)

Ab der zweiten Benutzung kommt keine Anmeldemaske mehr. Dahinter steht der Weg,
den Microsoft für **Exchange im eigenen Haus** vorsieht:

1. Outlook stellt dem Fenster ein vom **Exchange signiertes Token** aus
   (`getUserIdentityTokenAsync`).
2. Das Fenster schickt es an `POST /api/addin/sso`.
3. Der Server prüft die Signatur gegen das Zertifikat des Exchange und weiß
   damit, **welches Postfach** dranhängt.

**Warum trotzdem einmal Kennwort?** Das Token nennt kein Konto und keine
Mailadresse – nur eine undurchsichtige Postfach-Kennung. Die Zuordnung zum
Jarvis-Konto entsteht bei der ersten Anmeldung: das Token geht dort mit, und
die Verknüpfung wird gespeichert (`data/addin_links.json`).

> **Für Exchange Online gibt es das nicht.** Microsoft hat diese Token dort
> abgeschaltet; **für Exchange on-premises sind sie ausdrücklich weiter
> unterstützt**. Liegen die Postfächer in der Cloud, bleibt es bei der
> Anmeldung im Fenster.

**Voraussetzung:** Unter *Einstellungen → E-Mail* muss die **EWS-Adresse**
hinterlegt sein. Sie ist der Vertrauensanker – der Server nimmt nur Token an,
deren Metadaten-Adresse auf genau diesen Exchange zeigt. Ohne Eintrag gibt es
keine kennwortlose Anmeldung (und der Grund steht im Fenster).

**Zwei-Faktor-Konten sind ausgenommen.** Wer 2FA eingeschaltet hat, meldet sich
im Fenster weiterhin mit Kennwort und Code an: das Exchange-Token stammt vom
selben Arbeitsplatz und ist deshalb kein zweiter Faktor.

**Postfach wechselt den Besitzer?** *Einstellungen* → `DELETE
/api/addin/links/<benutzer>` löst die Verknüpfung; die Übersicht liefert
`GET /api/addin/links` (beides nur für Administratoren). Ohne das meldete sich
der neue Inhaber weiterhin als der alte Benutzer an.

### 5.2 Antwort vorschlagen – erst ansehen, dann senden

Im Reiter **Nachricht** steht über dem Regel-Block der Knopf **„Antwort
vorschlagen"**. Er formuliert eine Antwort auf die markierte Mail und zeigt sie
in einem bearbeitbaren Feld. Gesendet wird erst mit **„Senden"** – oder mit
**„Als Entwurf"**, wenn die Antwort noch in Outlook durchgesehen werden soll.
**„Neu formulieren"** verwirft den Vorschlag und fragt erneut.

Optional: ein **Hinweis** („freundlich absagen", „Termin bestätigen") und der
**Ton einer eigenen Regel** – deren Prompt beschreibt ja bereits, wie geantwortet
werden soll. Beides ist freiwillig; der Weg funktioniert auch, wenn noch gar
keine Regel angelegt ist.

> **Der Lauf hinter dem Vorschlag hat KEINE Werkzeuge.** Er kann nichts senden,
> nichts weiterleiten, nichts verschieben – er formuliert nur Text. Eine
> Prompt-Injektion in der eingegangenen Mail kann hier also nichts auslösen; sie
> könnte höchstens den Vorschlagstext beeinflussen, und den liest ein Mensch,
> bevor er ihn abschickt. Damit ist dieser Weg deutlich enger abgesichert als
> „Jetzt verarbeiten", wo das Modell die Aktion selbst wählt.

Beim Senden läuft **kein Sprachmodell mehr**: der Text geht so hinaus, wie er im
Feld steht. Der Empfänger ergibt sich aus der beantworteten Nachricht und kann
nicht überschrieben werden. Jeder Versand steht im **Protokoll**.

### Was das Add-in **nicht** kann

* **Postfächer über IMAP**: die Kennung, die Outlook liefert, ist eine
  EWS-Kennung. Bei einem IMAP-Postfach entfällt der Knopf „Jetzt verarbeiten"
  mit einem Hinweis – Regelverwaltung und Zeitplan sind davon unberührt.
* **Ohne Internetverbindung am Arbeitsplatz**: `office.js` kommt von Microsoft.
  Fehlt es, bleibt das Fenster benutzbar (Regeln, Postfach, Protokoll), nur der
  Bezug zur markierten Nachricht entfällt – mit Klartext-Hinweis.

---

## 6. Sicherheit – was hier gilt

* Das Add-in fordert nur **`ReadItem`**: es liest Kennung, Betreff und Absender
  der markierten Nachricht. **Jede Änderung am Postfach macht der Server** mit
  den Zugangsdaten des Benutzers, nicht der Browser.
* Jeder Datenabruf hängt serverseitig an `require_email_access` und filtert auf
  den angemeldeten Benutzer. Eine fremde Regel ist nicht sichtbar und antwortet
  mit „nicht gefunden" – kein Existenz-Orakel.
* Die Nachricht wird immer aus dem Postfach des **Regel-Besitzers** geladen. Die
  Kennung aus dem Aufruf wählt die Nachricht, **nicht das Postfach**.
* Der Regel-Lauf ist wie jeder Regel-Lauf **unprivilegiert** und auf die
  Werkzeuge der Regel beschränkt. Über diesen Weg gibt es keine Systemrechte.
* Das Kennwort des Postfachs wird nie angezeigt und von keiner Schnittstelle
  herausgegeben – nur „gesetzt: ja/nein".
* Der **Antwort-Vorschlag** läuft ohne jedes Werkzeug und kann deshalb nichts
  auslösen; der **Versand** läuft ohne Sprachmodell und geht ausschließlich an
  den Absender der beantworteten Nachricht.
* Die kennwortlose Anmeldung führt **dieselben Schranken wie `/api/login`**:
  Ratenbegrenzung, AD-Freigabe (auch nachträglich entzogene), Kontosperre,
  Lizenz-Benutzergrenze, Anwesenheits-Buchhaltung. Sie ist kein Nebeneingang.
* Ein Token wird nur angenommen, wenn **Signatur**, **Herkunft** (der
  konfigurierte Exchange), **Zielgruppe** (die Adresse dieses Aufgabenfensters)
  und **Laufzeit** stimmen. Fehlt die EWS-Adresse in der Konfiguration, ist die
  kennwortlose Anmeldung aus – nicht „irgendein Exchange".
* `data/addin_links.json` ordnet Postfächer den Konten zu und ist deshalb
  0640 und in allen Sandbox-Sperrlisten: wer sie beschreiben könnte, meldete
  sich als beliebiger Benutzer an.

Es bleibt die Eigenschaft des E-Mail-Bereichs, dass der Text einer eingehenden
Nachricht **Fremdeingabe im Prompt** ist. Das Add-in ändert daran nichts, weder
zum Guten noch zum Schlechten: es benutzt dieselbe Verarbeitung wie der
Zeitplan. Die Hinweise in `CLAUDE.md` zum Injektionsschutz gelten unverändert.

---

## 7. Aktualisieren

Änderungen am Aufgabenfenster (HTML/JS/CSS) wirken sofort – die Dateien liegen
auf dem Server, das Add-in lädt sie bei jedem Öffnen.

**Ein neues Manifest muss nur ausgerollt werden, wenn sich das Manifest selbst
ändert** (Knöpfe, Berechtigungen, Anforderungssatz). Dann in
`backend/addin.py::ADDIN_VERSION` die Zahl erhöhen und die Datei neu verteilen –
Outlook übernimmt ein geändertes Manifest nur bei höherer Versionsnummer.

Die Add-in-Kennung wird aus der Serveradresse abgeleitet und bleibt dabei
stabil. Zwei Jarvis-Instanzen am selben Exchange kollidieren nicht.
**Ändert sich die Serveradresse, ändert sich die Kennung** – das Add-in gilt dann
als ein neues und muss einmal neu installiert werden (das alte vorher entfernen).

---

## 8. Fehlersuche

| Symptom | Ursache und Abhilfe |
|---|---|
| Aufgabenfenster bleibt **leer/weiß** | Zertifikat. Die Serveradresse einmal im Browser des Arbeitsplatzes aufrufen – erscheint eine Zertifikatswarnung, fehlt `jarvis.cer` im Zertifikatsspeicher (siehe Abschnitt 2). |
| Exchange lehnt das Manifest ab | Manifest **erneut herunterladen** statt eine alte Kopie zu nehmen; bei Aktualisierungen muss die Version gestiegen sein. |
| Knopf erscheint **nicht** im Menüband | Add-in am Postfach installiert? Outlook einmal neu starten. Im klassischen Outlook: *Datei → Add-Ins verwalten*. |
| „Dein Konto ist für den E-Mail-Bereich nicht freigeschaltet" | *Einstellungen → Sicherheit → Berechtigungen → E-Mail-Zugriff*. **Leer heißt niemand** – auch Administratoren müssen eingetragen sein. |
| „Der E-Mail-Skill ist abgeschaltet" | *Einstellungen → Skills* → E-Mail einschalten (installiert `exchangelib` nach). |
| Kein Knopf „Jetzt verarbeiten" | Entweder kein Postfach hinterlegt, keine aktive Regel, oder das Postfach läuft über IMAP (Hinweis steht im Fenster). |
| Es kommt weiterhin jedes Mal die Anmeldemaske | Steht im Fenster ein Grund? Meist fehlt die **EWS-Adresse** (*Einstellungen → E-Mail*), oder das Konto hat **2FA** eingeschaltet (dann ist das so gewollt). Bei „Token stammt von einem anderen Exchange-Server" stimmt die hinterlegte Adresse nicht mit der überein, die Outlook benutzt. |
| „Das Token wurde für eine andere Adresse ausgestellt" | Das Add-in ist unter einer anderen Serveradresse installiert, als der Server jetzt benutzt. Manifest neu holen – oder `JARVIS_ADDIN_BASE` auf die Adresse setzen, unter der die Arbeitsplätze den Server erreichen. |
| Add-in debuggen | Klassisches Outlook: Rechtsklick im Fenster → *Debuggen*. Neues Outlook: `olk.exe --devtools`. Outlook im Web: die Entwicklerwerkzeuge des Browsers. |

---

## 9. Dateien

| Datei | Zweck |
|---|---|
| `backend/addin.py` | erzeugt das Manifest passend zum Server, Dateiname und Symbole folgen dem Branding |
| `backend/addin_sso.py` | prüft die Exchange-Identity-Token, verwaltet die Verknüpfung Postfach ↔ Konto |
| `backend/main.py` | Routen `/addin/manifest.xml`, `/addin/taskpane.html`, Endpunkt `POST /api/email/rules/{id}/run_message` |
| `backend/mail_runner.py` | `nachricht_lauf()` – eine benannte Nachricht verarbeiten, mit derselben Buchhaltung wie der Zeitplan |
| `backend/mail_runner.py` | `antwort_vorschlag()` / `antwort_senden()` – Vorschau ohne Werkzeuge, Versand ohne Sprachmodell |
| `frontend/addin/taskpane.html` | Aufgabenfenster (Markup und Gestaltung) |
| `frontend/addin/addin.js` | Anmeldung, Outlook-Kontext, Regeln, Postfach, Protokoll |
| `frontend/addin/icon-*.png` → `/addin/icon-<n>.png` | Symbole; ohne Branding-Logo die eingebauten |
| `tests/test_outlook_addin.py` | Wächter Manifest/Fenster (192 Prüfungen) |
| `tests/test_addin_sso.py` | Wächter kennwortlose Anmeldung + Antwort-Vorschau (112 Prüfungen, echte Signaturen) |
