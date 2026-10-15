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

Optional: ein **Stil** (siehe unten) und ein **Hinweis** für genau diese Antwort
(„freundlich absagen", „Termin bestätigen"). Beides ist freiwillig; der Weg
funktioniert auch, wenn noch gar keine Regel angelegt ist. Im leeren Hinweis-Feld
übernimmt **Tab** den angezeigten Beispieltext, damit man ihn nur noch anpassen
muss.

> Die frühere Auswahl **„Ton einer Regel übernehmen"** ist am 18.08.2026
> entfallen. Sie war der Behelf aus der Zeit, als es genau eine Vorgabe je
> Postfach gab; mit wählbaren Stilen gibt es dafür ein eigenes Feld. Ein
> Regel-Prompt beschreibt ohnehin eine **Handlung** („verschiebe nach …"), keinen
> Ton – und zwei Wege zur selben Frage sind nur verwirrend.

### Stile für Antworten

Was sich nie ändert – Signatur, Sie/Du, „keine Preise oder Termine zusagen",
gewünschte Länge – gehört nicht in das Hinweis-Feld, das man pro Mail neu tippt.
Dafür gibt es **benannte Stile** (Reiter *Postfach*, ebenso in `/email`): so viele,
wie gebraucht werden – etwa „Förmlich", „Locker", „Kurz & knapp". Einer davon ist
der **Standard** (Marke ●); er gilt überall dort, wo nichts anderes gewählt ist.

Gewählt wird ein Stil auf drei Wegen:

| Weg | Wo | Gilt für |
|---|---|---|
| **Pulldown** | Reiter *Nachricht*, über „Antwort vorschlagen" | genau diese Antwort |
| **Feld an der Regel** | „Stil für Antworten dieser Regel" | jeden Lauf dieser Regel |
| **im Regel-Prompt genannt** | z. B. „Antworte im Stil ‚Förmlich'" | jeden Lauf dieser Regel |

Bei mehreren Angaben gewinnt die ausdrückliche Auswahl (Pulldown bzw. Feld) gegen
die Nennung im Prompt; ohne alles gilt der Standard. Der Name wird **aufgelöst,
bevor das Sprachmodell läuft** – eine Stil-Nennung im Text der eingegangenen Mail
bewirkt deshalb nichts.

> **Ein Stil bestimmt ausschließlich die Form** (Sprache, Anrede, Ton, Signatur).
> Er löst keine Aktion aus und hebt keine Bedingung einer Regel auf. Ob überhaupt
> geantwortet wird, entscheidet allein die Regel – am 17.08.2026 hat eine als
> „immer antworten" formulierte Vorgabe genau das einmal überstimmt; seitdem steht
> die Stilvorgabe im Auftrag hinter der Regel und ist ausdrücklich untergeordnet.

Reihenfolge im Auftrag der Vorschau: Stil → Regel-Ton → Hinweis; bei Widerspruch
gewinnt das Speziellere. Ein leeres Textfeld heißt hier wirklich „kein Text"
(anders als beim Kennwort, das man nie sieht).

> **Der Lauf hinter dem Vorschlag hat KEINE Werkzeuge.** Er kann nichts senden,
> nichts weiterleiten, nichts verschieben – er formuliert nur Text. Eine
> Prompt-Injektion in der eingegangenen Mail kann hier also nichts auslösen; sie
> könnte höchstens den Vorschlagstext beeinflussen, und den liest ein Mensch,
> bevor er ihn abschickt. Damit ist dieser Weg deutlich enger abgesichert als
> „Jetzt verarbeiten", wo das Modell die Aktion selbst wählt.

Beim Senden läuft **kein Sprachmodell mehr**: der Text geht so hinaus, wie er im
Feld steht. Der Empfänger ergibt sich aus der beantworteten Nachricht und kann
nicht überschrieben werden. Jeder Versand steht im **Protokoll**.

### Format: HTML oder Text – und warum es kein Rich-Text gibt

Bis zum 26.08.2026 ging jede Antwort als **reiner Text** hinaus. Das war kein
Schalter, der falsch stand, sondern es gab keinen. Jetzt steht in der Vorschau
neben den Knöpfen ein Pulldown **Format**:

| Eintrag | Wirkung |
|---|---|
| **Vorgabe (…)** | das im Reiter *Postfach* eingestellte Format – die Beschriftung nennt es |
| **HTML** | die Antwort wird als HTML-Mail gesendet; Absätze bleiben, die HTML-Signatur wirkt |
| **Nur Text** | reiner Text wie bisher |
| ~~Rich-Text~~ | steht sichtbar da, ist aber **abgeschaltet** |

> **Rich-Text lässt sich nicht erzeugen, und das liegt nicht an Jarvis.**
> Exchange kennt über EWS genau zwei Rumpf-Typen: `HTML` und `Text` (`BodyType`
> kennt daneben nur `Best`, und das ist rein lesend). Was Outlook „Rich-Text"
> nennt, ist außerdem gar kein RTF-Rumpf, sondern **TNEF** – der berüchtigte
> Anhang `winmail.dat`, ein eigenes Containerformat. Der Eintrag bleibt trotzdem
> im Pulldown stehen und nennt beim Zeigen den Grund: sonst bleibt die Frage
> „warum fehlt Rich-Text?" unbeantwortet. Ihn wählbar zu machen und still HTML
> daraus zu erzeugen, wäre die schlechtere Lösung – die Anzeige würde etwas
> behaupten, das nicht passiert.

Die **Vorgabe des Postfachs** steht im Reiter *Postfach* unter **Format neuer
Antworten** (ebenso in `/email`) und gilt überall, wo nichts anderes gewählt ist –
auch für die Antworten, die eine **Regel** automatisch schreibt. Vorgabe ist
**Nur Text**: das ist das Verhalten von vorher, und ein Postfach, das ohne Zutun
plötzlich HTML verschickt, wäre eine Überraschung.

Aus dem Textfeld wird beim HTML-Versand nur das übersetzt, was in reinem Text
keine Bedeutung hat: Leerzeilen werden Absätze, einfache Umbrüche werden
Zeilenumbrüche. **Markdown wird bewusst nicht ausgewertet** – aus `**wichtig**`
wird kein Fettdruck. Der Text ist von einem Menschen freigegeben worden; ihn
nachträglich umzuformatieren wäre eine Änderung an etwas Freigegebenem.

### Signaturen

Eine Signatur ist **kein Stil**. Der Unterschied ist nicht Ordnung, sondern
Wirkung:

* Ein **Stil** ist eine Anweisung an das Sprachmodell – er geht in den Auftrag,
  und das Modell schreibt danach.
* Eine **Signatur** ist ein fester Text – sie wird **hinter** die fertige Antwort
  gesetzt und läuft **nie** durch ein Sprachmodell.

Das ist der ganze Grund für die Trennung: eine Signatur trägt Pflichtangaben –
Rechtsform, Registergericht, Geschäftsführung, Umsatzsteuer-Id. Ein Modell, das
sie „mitschreibt", formuliert sie um, und bei einer Regel liest niemand gegen.

Gepflegt werden Signaturen im Reiter **Antworten** (ebenso in `/email` unter
*Mein Postfach*), so viele wie gebraucht – etwa „Standard", „Kurz", „Englisch".
Eine davon ist der **Standard** (Marke ●) und gilt überall, wo nichts anderes
gewählt ist. Je Signatur gibt es zwei Felder:

* **Signatur (Text)** – wird wörtlich angehängt, mit dem üblichen Trenner `-- `
  davor.
* **HTML-Fassung (optional)** – wirkt nur bei HTML-Antworten und erlaubt Logo,
  Links und Farben. Fehlt sie, wird bei einer HTML-Antwort die Textfassung
  umgesetzt; fehlt umgekehrt die Textfassung, wird für eine Text-Antwort aus dem
  HTML eine Textfassung abgeleitet. **Eine Signatur verschwindet nie, nur weil
  das Format nicht passt.**

> **Aus der HTML-Fassung wird alles entfernt, was ausführbar wäre** – Skripte,
> `on…`-Attribute, `javascript:`-Ziele, eingebettete Rahmen, SVG. Erlaubt bleibt,
> was eine Signatur braucht: Text, Auszeichnung, Links, Bilder (auch als
> eingebettetes `data:`-Bild) und einfache Tabellen. Geprüft wird beim **Senden**,
> nicht beim Speichern – so geht auch eine vor dieser Änderung gespeicherte
> Signatur nicht ungeprüft hinaus.

Gewählt wird eine Signatur auf zwei Wegen:

| Weg | Wo | Gilt für |
|---|---|---|
| **Pulldown** | Vorschau, neben „Senden" | genau diese Antwort |
| **Feld an der Regel** | „Signatur" im Regel-Formular | jeden Lauf dieser Regel |

Anders als beim Stil gibt es **keine Erkennung aus dem Regel-Prompt** und **kein
„automatisch wählen"**. Beides mit Absicht: typische Signaturnamen sind
„Standard", „Kurz", „Englisch" – Wörter, die in jedem zweiten Regeltext
vorkommen, und ein zufälliger Treffer würde eine falsche Anschrift an eine echte
Mail hängen. Und was fest angehängt wird, soll kein Modell aussuchen.

> **Die Signatur steht nicht im Textfeld der Vorschau.** Was dort steht, kann
> geändert werden – eine Pflichtangabe darf das nicht. Stattdessen sagt eine
> Zeile unter den Pulldowns, welche Signatur angehängt wird („Angehängt wird die
> Signatur ‚Standard'."), und im Protokoll steht bei jedem Versand Format und
> Signatur.

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

### Was sich von selbst aktualisiert

**Aufgabenfenster, Logik, CSS und Symbole** – ohne jedes Zutun. Die Dateien
liegen auf diesem Server und werden mit `Cache-Control: no-store` ausgeliefert;
ein Deploy erreicht damit jedes installierte Add-in beim nächsten Öffnen. Das
ist der Teil, der sich ständig ändert, und `ADDIN_VERSION` muss dafür **nicht**
erhöht werden.

### Was sich nicht von selbst aktualisiert

**Das Manifest** – also Menüband-Knopf, Berechtigungen, Anforderungssatz und
die URLs. Microsoft aktualisiert Add-ins automatisch nur, wenn sie aus dem
Store stammen; bei einer Installation aus **Datei oder URL** passiert nichts.
Auch `New-App -Url` holt das Manifest **einmalig beim Installieren** – es gibt
kein `Update-App`, und `Set-App` ändert nur Freigabe und Zustand.

Ändert sich das Manifest also wirklich, sind zwei Schritte nötig:

1. In `backend/addin.py::ADDIN_VERSION` die Zahl erhöhen (Outlook übernimmt ein
   geändertes Manifest nur bei höherer Versionsnummer).
2. Die Datei neu verteilen – Weg A oder B aus Abschnitt 4. Bei Weg B (zentral)
   genügt ein `Remove-App` + `New-App` durch die Administration; bei Weg A muss
   jeder Benutzer sein Add-in einmal neu hinzufügen.

> **Änderungen an den Berechtigungen** verlangen zusätzlich eine erneute
> Zustimmung durch die Administration – bis dahin ist das Add-in für die
> Benutzer gesperrt. Unser Manifest bleibt deshalb bei `ReadItem`.

### Das Fenster sagt selbst, wenn sein Manifest veraltet ist

Die Manifest-Version steht im Abfrageteil der Taskpane-URL
(`taskpane.html?mv=1.2.0.0`). Das Fenster vergleicht sie beim Start mit
`GET /api/addin/version` und zeigt bei Abweichung oben ein Band mit
Download-Knopf. Der Umweg über die URL ist nötig, weil Office.js keine
Schnittstelle hat, mit der ein Add-in die Version seines eigenen Manifests
lesen könnte.

Das Band erscheint **nur, wenn die Abweichung belegt ist**: bei kleinerer `mv`
mit beiden Versionsnummern, bei fehlender `mv` (Manifest von vor dieser
Prüfung) mit dem ausdrücklichen Hinweis, dass die installierte Fassung ihre
Version nicht meldet. Ein direkter Aufruf der Seite im Browser – ohne `mv` und
ohne Outlook-Kontext – zeigt **kein** Band.

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
