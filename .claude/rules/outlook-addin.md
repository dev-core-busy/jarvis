---
paths:
  - "backend/addin.py"
  - "backend/addin_sso.py"
  - "backend/mail_accounts.py"
  - "frontend/addin/**"
  - "docs/outlook-addin.md"
  - "tests/test_outlook_addin.py"
  - "tests/test_addin_sso.py"
  - "tests/test_addin_update_ui.js"
  - "backend/mail_body.py"
  - "tests/test_mail_styles.py"
  - "tests/test_mail_body.py"
  - "tests/test_mail_signaturen.py"
  - "tests/test_mail_sig_ui.js"
  - "tests/test_tabfill_ui.js"
---

<!-- Ausgelagert aus CLAUDE.md am 2026-08-25. Diese Datei laedt NUR, wenn Claude eine
     der oben genannten Dateien liest. Landkarte + Verweis stehen in CLAUDE.md. -->

## Outlook-Add-in: /email im Aufgabenfenster (2026-08-16)
**Was es ist:** Ein Office-**Web**-Add-in (Office.js), das `/email` in ein Aufgabenfenster in
Outlook holt – Postfach, Regeln, Protokoll – plus das, wofuer es ein Add-in ueberhaupt braucht:
**die markierte Nachricht sofort mit einer Regel verarbeiten** und eine **Antwort-Vorschau**.
Code: `backend/addin.py`, `backend/addin_sso.py`, Routen `/addin/manifest.xml`,
`/addin/taskpane.html`, `/addin/icon-<n>.png`, Endpunkte `POST /api/email/rules/{id}/run_message`,
`POST /api/email/reply/preview|send`, `POST /api/addin/sso`, `GET /api/addin/version`,
`DELETE /api/addin/links/<benutzer>`, Oberflaeche `frontend/addin/`. Anleitung:
`docs/outlook-addin.md`.

### Randbedingungen (bei Microsoft, nicht bei uns)
- **Das NEUE Outlook fuer Windows unterstuetzt KEINE On-Premises-Exchange-Konten** (auch keine
  Hybrid-/Sovereign-Konten) – es oeffnet ein Postfach auf dem hauseigenen Exchange 2019 gar
  nicht erst, unabhaengig von Add-ins. Tragfaehig: **klassisches Outlook** (M365/Office 2021+)
  und **Outlook im Web** des eigenen Exchange; beide deckt das Manifest ab.
- **VSTO/COM war nie eine Option** – das neue Outlook unterstuetzt beides nicht mehr, Microsoft
  verlangt Web-Add-ins. Die laufen zusaetzlich auf Mac und im Web.
- **XML-Manifest, NICHT das unified JSON manifest** – letzteres setzt Bereitstellung ueber
  Microsoft 365 voraus; ein Exchange im Haus kennt nur XML, und darueber laeuft das Sideloading.
  Aus demselben Grund `Mailbox 1.3` als Anforderung: ein hoeherer Satz waere dort **nicht
  installierbar**. `contextless` (Fenster ohne markierte Nachricht) braeuchte 1.14 und scheidet aus.
- **SSO ueber Office/Entra scheidet aus** – das setzt eine Anwendungsregistrierung in
  Microsoft 365 voraus, die ein Exchange im Haus nicht hat.

### Manifest
- **Es wird ERZEUGT, nicht als Datei gepflegt** – jede URL darin muss auf *diesen* Server zeigen;
  eine Repo-Datei muesste pro Server angepasst werden (Drift-Muster der Landing-Page).
  `JARVIS_ADDIN_BASE` ueberschreibt die aus der Anfrage abgeleitete Adresse (Rueckwaertsproxy);
  **das Schema wird hart auf https gesetzt** – Office laedt nichts ueber http, und ein solches
  Manifest scheitert *stillschweigend*.
- **Ein Abruf ueber `localhost` wird mit 400 ABGELEHNT** (`ist_lokale_basis`): ein Manifest mit
  `https://localhost/…` laesst sich klaglos installieren, und das Fenster bleibt danach **leer**.
  Diesen Fehler bringt niemand mit dem Abruf in Verbindung. Die Meldung nennt
  `JARVIS_ADDIN_BASE`. `localhost.firma.de` ist **kein** lokaler Name (Host exakt pruefen).
- **Kennung ist UUIDv5 aus der Basis-URL** – auf demselben Server ueber alle Aktualisierungen
  stabil (eine wechselnde Kennung gaelte als *neues* Add-in), zwei Instanzen am selben Exchange
  kollidieren nicht. Adresswechsel = folgerichtig ein neues Add-in, einmal neu installieren.
- **`xml.sax.saxutils.escape` maskiert KEIN Anfuehrungszeichen** – ein Markenname `Nex"us`
  zerlegte `DefaultValue="…"`. EINE Maskierung `addin.x()` fuer Text *und* Attribute
  (`&quot;` ist in beidem gueltig); zwei Konventionen nebeneinander waren die Fehlerquelle.
- **`--` ist in einem XML-Kommentar verboten** und hat keine Entity – eine Umlaut-Domaene heisst
  im Punycode genau so (`xn--mller-kva`), das Manifest war unlesbar („Das Manifest ist
  ungueltig"). Fuer den Kommentar wird die Adresse entschaerft, in den **Attributen** steht sie
  unveraendert.
- **`Permissions` ist `ReadItem`, und das ist Absicht:** das Fenster liest Kennung, Betreff und
  Absender. **Jede Aenderung am Postfach macht der Server** mit den Zugangsdaten des Benutzers.

### Aktualisierung: der Code JA, das Manifest NEIN
- **Aufgabenfenster, Logik, CSS und Symbole aktualisieren sich von selbst** – die Dateien liegen
  auf diesem Server, `/addin/taskpane.html` geht mit `Cache-Control: no-store` hinaus, die
  Unterressourcen tragen Cache-Buster. **`ADDIN_VERSION` ist dafuer NICHT zu erhoehen.**
- **Das Manifest aktualisiert Microsoft nicht** – automatische Updates gibt es nur fuer Add-ins
  aus dem Store. Bei Installation aus Datei oder URL passiert nichts, auch nicht bei `New-App
  -Url`: das holt das Manifest **einmalig**, ein `Update-App` existiert nicht, `Set-App` aendert
  nur Freigabe und Zustand. Fuer einen Exchange im Haus bleibt `Remove-App` + `New-App`.
  **Der Kommentar an `ADDIN_VERSION` behauptete jahrelang das Gegenteil** – berichtigt.
- **Gebaut wurde nur, was in unserer Hand liegt: das Fenster weist ein veraltetes Manifest AUS.**
  Die Manifest-Version geht als `?mv=` in die Taskpane-URL, das Fenster vergleicht mit
  `GET /api/addin/version` und zeigt ein Band mit Download-Knopf. Der Umweg ueber die URL ist der
  einzige Weg – Office.js hat keine Schnittstelle fuer die eigene Manifest-Version.
- **Drei Faelle, nichts behaupten, was wir nicht wissen:** `mv` kleiner → Band mit beiden Nummern ·
  `mv` fehlt, aber Outlook-Kontext da → Band, das ausdruecklich sagt, die installierte Fassung
  melde ihre Version nicht (das ist der Altbestand) · `mv` fehlt und kein Outlook → **kein Band**.
  `_officeDa` ist NICHT `_office` (letzteres ist `null`, sobald keine Nachricht markiert ist).
- **Der Vergleich ist segmentweise NUMERISCH** – ein String-Vergleich haelt „1.10" fuer kleiner
  als „1.9", und der Fehler faellt erst beim zehnten Manifest auf. `mv` ist Fremdeingabe und wird
  auf seine FORM geprueft; „unbekannt" ist die ehrlichere Auskunft als ein Muellwert.
- `/api/addin/version` haengt an **keiner** Anmeldung (der Wert steht ohnehin im Manifest) und
  liefert `no-store` – sonst beantwortet der Cache die Frage „gibt es etwas Neues" mit gestern.
  Kein Schliessen-Knopf am Band: es scrollt weg, und ein Merker braeuchte `localStorage`, das im
  Aufgabenfenster gesperrt sein kann.
- **Bewusst NICHT gebaut** (Entscheidung des Nutzers): ein PowerShell-Wartungsskript, das die
  zentrale Bereitstellung per `Get-App`-Versionsvergleich selbst nachzieht. Damit bleibt das
  Verteilen Handarbeit – das Band macht nur den Anlass sichtbar.

### Anmeldung: kennwortlos ueber das Exchange-Identity-Token
Microsoft hat diese Token fuer Exchange **Online** abgeschaltet, **fuer on-premises sind sie
ausdruecklich weiter unterstuetzt** – also genau unser Fall.
- **Das Token nennt keine Mailadresse**, nur `msexchuid` + `amurl`. Die Zuordnung entsteht bei
  der **ersten** Anmeldung: das Token geht an `POST /api/login` mit (`addin_token`), die
  Verknuepfung landet in `data/addin_links.json`. **Bewusst am regulaeren Login:** dort sind
  Kennwort, 2FA, AD-Freigabe und Lizenzgrenze schon bestanden; eine zweite Fassung dieser
  Pruefungen waere die Abkuerzung, die spaeter als Luecke auffaellt. Ein Fehlschlag beim
  Verknuepfen kippt die Anmeldung nicht.
- **DER VERTRAUENSANKER IST DIE HINTERLEGTE EWS-ADRESSE.** Ohne ihn koennte sich jemand ein
  einwandfrei signiertes Token von einem *beliebigen* Exchange ausstellen lassen. Der
  `amurl`-Host muss zur Konfiguration passen; **ist keine hinterlegt, gibt es kein SSO**
  (fail-closed).
- Geprueft werden Signatur (RS256 gegen das Zertifikat aus dem Metadaten-Dokument), Herkunft,
  `aud` (= Adresse **unseres** Aufgabenfensters), Laufzeit, `ExIdTok.V1`. `alg` hart auf RS256 –
  `none` ist die klassische JWT-Umgehung. **Unbekanntes `x5t` bricht NICHT ab**: den Beweis
  liefert die Signatur, ein Abbruch liesse nach jedem Zertifikatstausch jede Anmeldung scheitern.
- **Der SSO-Endpunkt fuehrt dieselben Schranken wie `/api/login`, in derselben Reihenfolge:**
  Ratenbegrenzung → Token → Verknuepfung → `_login_still_allowed` → Lizenzgrenze → `record_login`
  → Kontosperre. Fehlt eine, ist SSO der bequemste Weg daran vorbei (ein Test prueft jede).
- **Konten mit 2FA bekommen KEIN SSO** – das Token stammt vom selben Arbeitsplatz und ist kein
  zweiter Faktor.
- `data/addin_links.json` ist 0640 und steht in `_APP_DENY_REL`, `PRIVATE_FILES` und
  `SHELL_SECRET_PATHS`: **wer sie beschreiben kann, traegt sein Postfach auf einen fremden – gern
  administrativen – Benutzer ein und meldet sich als dieser an.** Gespeichert wird nur
  `sha256(msexchuid|amurl)`. `DELETE /api/addin/links/<benutzer>` loest die Verknuepfung, wenn
  ein Postfach den Besitzer wechselt.
- **Der 2FA-Code ging ins Leere:** das Fenster sendete `totp`, `/api/login` liest `totp_code` –
  eine **Anmeldeschleife ohne Fehlermeldung**. Ein Test vergleicht den Feldnamen gegen `app.js`.

### Fenster-Mechanik
- **`office.js` mit `async`, NIEMALS `defer`.** Ein defer-Skript laesst `DOMContentLoaded`
  darauf warten – blockiert eine Firewall das Microsoft-Netz, blieb das Fenster die volle
  TCP-Zeitgrenze **weiss**, und die eigene 4-Sekunden-Grenze kam nie zum Zug. Merkregel: wer eine
  Zeitgrenze gegen ein haengendes Skript baut, muss zuerst pruefen, ob sein Code ueberhaupt
  startet. `officeErmitteln` wartet im 100-ms-Takt bis `OFFICE_WARTE_MS = 4000`.
- **`office.js` darf fehlen** – ohne Internet bleibt das Fenster voll benutzbar (Regeln,
  Postfach, Protokoll), nur der Nachrichtenbezug entfaellt, mit Klartext-Hinweis. Der
  Anbindungs-Zustand steht **im Anmeldeblock** (`ad-login-office`), nicht dahinter: wer an der
  Anmeldung haengenbleibt, kann eine Aussage dahinter nicht lesen.
- **Der Token braucht einen Rueckfall im Arbeitsspeicher** (`_tokenRam` + `addin.no_storage`):
  in Outlook im Web laeuft das Fenster in einem **iframe**, wo Speicher fremder Herkunft
  gesperrt sein kann – `localStorage.setItem` scheiterte still und `start()` zeigte wieder die
  Anmeldung: **Endlosschleife mit richtigem Kennwort und ohne Fehlermeldung.**
- **Der Aussetzer darf im Add-in nicht verschwiegen werden** (nach mehreren Anmeldefehlern haelt
  die Automatik an): wer nur in Outlook arbeitet, saehe seine Regeln sonst stillschweigend
  aufhoeren. Ebenso `ausgesetzt` in `/api/email/admin/overview`.
- **Der Nachrichtenbezug haengt am EWS-Kanal** (`item.itemId` ist eine EWS-Kennung). Bei IMAP
  entfaellt der Knopf mit Erklaerung. Massgeblich ist der **wirksame** Kanal (Wahl des Benutzers,
  sonst Vorgabe des Administrators) – wer nur das Benutzerfeld prueft, haelt ein reines
  IMAP-Haus fuer EWS-faehig.
- **`window.confirm` ist im Add-in verboten** (Register: unterdrueckt in WebView2; gemeldet fuer
  „Regel loeschen", vier Stellen betroffen). Eigener Dialog `frage(text, jaText, gefahr) →
  Promise<boolean>` (`#ad-ask`), Fokus auf **Abbrechen**; **fehlt das Markup, wird mit `true`
  aufgeloest** (fail-open – der Benutzer hat den Knopf schon gedrueckt). In `/email` bleibt
  `confirm` unangetastet. Waechter prueft zusaetzlich, dass `%s` in `*_del_confirm` ersetzt wird.

### Verarbeiten und Antworten
- **Die Verarbeitung EINER Nachricht steht EINMAL** (`mail_runner._verarbeite_eine`), benutzt von
  `regel_lauf` (Zeitplan) **und** `nachricht_lauf` (Add-in). Eine zweite Fassung der Buchhaltung
  (Vermerk, Fehlversuche, Lesestatus, Protokoll) waere in drei Wochen auseinandergelaufen.
- **`run_message`: die Kennung waehlt die NACHRICHT, nicht das Postfach.** Geladen wird immer aus
  dem Postfach des Regel-Besitzers (`konto_fuer(owner)`); ein `msg_id` aus dem Rumpf waere sonst
  der Weg in ein fremdes Postfach. Fremde Regel → **404**, abgeschaltete → 400. Die
  Auswahl-Filter gelten hier bewusst **nicht** (der Benutzer hat von Hand markiert), der
  Verarbeitungsvermerk wird aber gesetzt – sonst antwortet die Automatik ein zweites Mal.
- **DER VORSCHLAGS-LAUF HAT KEINE WERKZEUGE** (`_role_tools = set()` – leere Menge heisst
  „keine", nie auf Falsyness pruefen). Eine Prompt-Injektion in der Mail kann hier **nichts**
  ausloesen; sie koennte hoechstens den Vorschlagstext beeinflussen, und den liest ein Mensch.
  Damit ist dieser Weg **enger abgesichert als ein Regel-Lauf**. Wer hier je ein Werkzeug
  ergaenzt, hebt genau diese Zusage auf.
- **Beim SENDEN laeuft kein Sprachmodell** – der Text kommt aus dem Fenster, der Benutzer hat ihn
  gesehen. Dieselbe Trennung wie bei den Erinnerungen: liefe er noch einmal durch ein Modell,
  waere er wieder eine ausfuehrbare Anweisung.
- **Der Empfaenger ergibt sich aus der NACHRICHT**, nicht aus dem Rumpf des Aufrufs – sonst waere
  der Endpunkt ein Versandweg an beliebige Adressen.
- `_vorschlag_saeubern()` entfernt einen umschliessenden Codeblock und eine FUEHRENDE
  Betreffzeile. **Mehr nicht** – eine „Betreff:"-Zeile mitten im Text bleibt stehen, wer hier
  grosszuegig aufraeumt, loescht Inhalt.
- Der bearbeitete Text wird bei jedem Tastendruck nach `_vorschlag.text` gespiegelt – der Reiter
  wird bei jedem Statusladen und Sprachwechsel neu aufgebaut.
- **„Ton einer Regel uebernehmen" ist entfallen** (Behelf aus der Zeit mit einer Vorgabe je
  Postfach; ein Regel-Prompt beschreibt eine Handlung, keinen Ton). **Dabei wurde eine Luecke
  geschlossen:** `_injektion_pruefen()` lief nur `if regel:` – ob ein Postfach beschossen wird,
  darf nicht davon abhaengen, welches Pulldown jemand bedient. Laeuft jetzt immer.

### Antwort-Stile (`mail_accounts.stile`, seit 2026-08-18)
Mehrere benannte Stile statt einer Vorgabe; **eigener Reiter *Stile*** (seit 2026-08-25,
davor ein Abschnitt unten im Postfach-Reiter – dort lag er hinter Serveradresse, Kennwort und
vier Ordnerfeldern und war nur nach Scrollen erreichbar, obwohl er im taeglichen Gebrauch
haeufiger gebraucht wird als Zugangsdaten, die man einmal eintraegt), waehlbar in der
Vorschau und je Regel. Endpunkte `GET/POST /api/email/styles`, `PUT/DELETE …/{id}`.
- **DREI WEGE, EINE REIHENFOLGE:** ausdrueckliche Auswahl (Pulldown bzw. Feld an der Regel) →
  sprachliche Nennung im Regel-**Prompt** → Standardstil. `STIL_KEINER = "-"` ist die
  ausdrueckliche Wahl „ohne Stil" und muss von „nichts gewaehlt" (leer) unterscheidbar bleiben.
- **DIE AUFLOESUNG IST DETERMINISTISCH UND PASSIERT VOR DEM MODELL.** Der Stilname wird nur im
  Regelfeld und im Regel-Prompt gesucht, **nie** im Nachrichtentext – sonst waere „[[Stil: X]]"
  im Fremdtext ein Hebel auf die Form.
- **Ein Stil bestimmt NUR die Form.** Er steht im Auftrag HINTER Regel und Fremdtext, der
  Vorspann weist ihn als untergeordnet aus und sagt woertlich, dass er keine Aktion ausloest,
  keine Bedingung aufhebt und keinen Empfaenger bestimmt (Lehre aus dem Vorfall 2026-08-17).
- **Der NAME steht nicht in der Abschnittsmarke, sondern als erste Zeile im Abschnitt** – sonst
  wandert eine Zeichenkette, die Struktur ist. `_markensicher()` entfernt `=`, `[`, `]` und
  Zeilenumbrueche aus dem Freitext-Namen.
- **Eigene Endpunkte statt eines Feldes am Postfach-Formular** (`stile` steht NICHT in
  `mail_accounts.AENDERBAR`): ein Formular, das die Liste als Ganzes sendet, ueberschreibt bei
  zwei offenen Fenstern den jeweils anderen Stand.
- **Migration ohne Datenverlust:** `_migrieren()` macht aus einer vorhandenen `antwort_vorgabe`
  einen Stil „Standard" und schreibt **einmalig** zurueck. Das alte Feld bleibt als Spiegel
  stehen; **ein LEERER Wert wird ignoriert**, sonst waere ein Klick auf „Ordner speichern" aus
  einem zwischengespeicherten Add-in der Verlust aller Stiltexte.
- **Beim Loeschen rueckt KEINER nach** – Regeln antworteten sonst in einem Ton, den niemand dafuer
  bestimmt hat. Verwaiste Kennung → Standard **mit Vermerk** (ein Lauf, der wegen einer
  verwaisten Referenz nichts tut, ist der schlechtere Ausgang).
- Namen unter `STIL_PROMPT_MIN = 3` werden im Prompt nicht gesucht („AG", „Du" traefen ueberall);
  der Name wird mit `re.escape` maskiert. `VORGABE_MAX = 6000` (Signatur mit Pflichtangaben),
  Zeichenzaehler ab 70 % – `maxlength` schneidet sonst **still** ab.

#### Automatische Stilwahl – EIN LLM-Aufruf
In JEDEM Stil-Pulldown steht **„automatisch Stil waehlen"** (`STIL_AUTO`) – Vorschau UND
Regel-Formular, Add-in wie `/email`, ohne Bedingungen (**ausdrueckliche Vorgabe des Nutzers**,
nachdem eine erste Fassung sie auf die Vorschau beschraenkt und erst ab zwei Stilen angeboten
hatte). Dann liegen alle Stiltexte im Auftrag, das Modell waehlt und schreibt sofort darin und
meldet die Wahl in einer Kopfzeile `[<Kennung>] STIL: <Name>`.
- **Die Mail muss NICHT zweimal zum Modell.** Gemessen (3 Stile, echtes Modell): Auftrag mit Auto
  **3978** Zeichen gegen **2820** ohne – Aufpreis 1158, waehrend ein zweiter Aufruf allein fuer
  die Wiederholung 2820 gekostet haette.
- **Hier wird bewusst eine Zusage gelockert.** Was bleibt: Opt-in · die Wahl wird gegen die
  hinterlegten Stile **validiert** (erfundener Name wird verworfen) · in der Vorschau wird der
  Stil **angezeigt** · die Anweisung sagt, dass ein Stilname IM Fremdtext keine Anweisung ist.
  **Was das fuer Regeln bedeutet:** dort entscheidet ueber die Form ein Modell, das den Fremdtext
  vor sich hat, und niemand liest gegen.
- **Die Kopfzeile wird IMMER entfernt**, auch bei unbekanntem Namen – sonst steht sie im Postfach
  des Empfaengers. Gelesen wird NACH `_vorschlag_saeubern`. Nennt das Modell keinen Stil, sagt der
  Hinweis, dass der Vorschlag keinem *nachweislich* folgt.
- `AUTO_KATALOG_MAX = 20000`; weggelassene Stile werden **namentlich genannt**, der Standardstil
  faellt nie heraus.
- **Vorspann und Schlusszeile mussten mit** – beide sagten „AUSSCHLIESSLICH den Text der Antwort",
  was der geforderten Kopfzeile widerspricht.
- Live (Qwen3.6-35B): foermliche Reklamation → „Foermlich", lockere Kollegenmail → „Locker", je
  **ein** Aufruf, Kopfzeile sauber entfernt.

### Antwort-Format und Signaturen (2026-08-26)
**Gemeldet:** "in dem Outlook-Add-In werden aktuell Entwuerfe im Text Format erstellt. 'HTML',
'Text' und 'Rich-Text' sollten waehlbar sein. Ausserdem soll auswaehlbar eine Signatur sein."
Code `backend/mail_body.py` (neu), `mail_accounts.signaturen/format_fuer`, vier Endpunkte
`/api/email/signatures`, Felder `format`/`signatur` an Regel und Postfach, Reiter **Antworten**
(hiess bis dahin *Stile* – er haelt jetzt beides).

- **RICH-TEXT GIBT ES NICHT, UND ZWAR NACHGEMESSEN.** exchangelib 5.6.0 auf DEV:
  `BodyField.from_xml` kennt genau `{Body: "Text", HTMLBody: "HTML"}`; EWS' `BodyType` hat daneben
  nur `Best` (rein lesend). Was Outlook "Rich-Text" nennt, ist ausserdem **TNEF**
  (`winmail.dat`) – ein Containerformat, das man selbst erzeugen muesste. Der Eintrag steht
  **sichtbar und abgeschaltet** im Pulldown und nennt beim Zeigen den Grund: weglassen liesse die
  Frage "warum fehlt das?" unbeantwortet, waehlbar machen und HTML daraus erzeugen waere eine
  Behauptung. `norm_format("richtext")` gibt `""` zurueck – **nicht** `"html"`; ein Test haelt das
  fest.
- **Der BodyType haengt an der KLASSE des Wertes, nicht an einem Parameter.** `_Ews._rumpf` gibt
  `HTMLBody(html)` oder den `str` zurueck; ein `str` wird zu `BodyType=Text` – genau daher kam der
  gemeldete Zustand, ohne dass irgendwo ein Format falsch stand. Faellt `HTMLBody` aus (alte
  Bibliothek), geht der TEXT hinaus **mit Journal-Zeile**: die Antwort ist wichtiger als ihr
  Format, aber ein stiller Rueckfall waere nicht diagnostizierbar.
- **IMAP: `add_alternative`, nicht `set_content(subtype="html")`** – der Textteil MUSS bleiben,
  sonst bekommt jedes Programm ohne HTML-Anzeige eine leere Mail. Und **das Zitat muss in BEIDE
  Teile**: zwei Alternativteile mit verschiedenem Inhalt sind ein Fehler, nicht nur haesslich.
- **EINE SIGNATUR IST KEIN STIL – der Unterschied ist die Sicherheitsaussage:** ein Stil ist eine
  **Anweisung an das Modell** (er geht in den Auftrag), eine Signatur ein **fester Text** (sie
  wird hinter die fertige Antwort gesetzt und laeuft NIE durch ein Modell). Eine Signatur traegt
  Pflichtangaben – Rechtsform, Registergericht, Geschaeftsfuehrung. Ein Modell, das sie
  "mitschreibt", formuliert sie um, und **bei einer Regel liest niemand gegen.** Wer Signaturen je
  in den Prompt zurueckverlegt, hebt diese Zusage auf.
- **Deshalb: KEINE Erkennung aus dem Regel-Prompt und KEIN "automatisch waehlen".** Typische
  Signaturnamen sind "Standard", "Kurz", "Englisch" – Woerter, die in jedem zweiten Regeltext
  vorkommen; ein Zufallstreffer haenge eine falsche Anschrift an eine echte Mail. (Beim Stil ist
  die Prompt-Erkennung richtig: einen Ton formuliert man in Prosa.)
- **Die Signatur steht NICHT im Textfeld der Vorschau.** Was dort steht, ist bearbeitbar – eine
  Pflichtangabe darf das nicht sein; ausserdem passt eine HTML-Signatur nicht in eine Textarea.
  Angehaengt wird serverseitig in `antwort_senden`. **Genau deshalb ist der Hinweis Pflicht**
  („Angehaengt wird die Signatur ‚Standard'."), sonst ist sie bis zum Blick ins Postfach
  unsichtbar. Format und Signatur stehen auch im **Protokoll** – wer eine hinausgegangene Antwort
  nachvollzieht, muss sehen, welche Anschrift daran hing.
- **Format und Signatur der REGEL laufen ueber ContextVars** (`current_antwort_format`,
  `current_antwort_signatur`), gesetzt von `_lauf_fuer_nachricht`, gelesen im Werkzeug. **Kein
  Werkzeug-Parameter** – dieselbe Begruendung wie beim Postfach: waere es ein Feld im Schema,
  koennte das MODELL (und damit ein eingeschmuggelter Satz) die Anschrift abwaehlen. Ein Test
  lehnt die Feldnamen im Schema ab. Leer heisst "Vorgabe des Postfachs", **nicht** "keine" – das
  ist der Unterschied zu `SIG_KEINER`.
- **Die HTML-Entschaerfung ist eine ERLAUBNISLISTE mit `html.parser`, kein Regex.** Ein
  `re.sub("<script.*?>")` uebersieht `<img onerror>`, `<svg><script>`, `javascript:`-Ziele und ein
  nicht geschlossenes `<script`. Das Fragment wird zerlegt und aus einer Erlaubnisliste neu
  aufgebaut; ein Test prueft die REGEL („nach der Entschaerfung nur erlaubte Tags"), nicht eine
  Liste bekannter Boesewichte. **Geprueft wird beim BAUEN des Rumpfes, nicht beim Speichern** –
  sonst geht ein Altbestand ungeprueft hinaus.
- **⚠ DER FEHLER, DEN DER TEST GEFUNDEN HAT: void-Elemente in der Toetungsliste.** `<meta>`,
  `<input>`, `<link>`, `<embed>` bekommen NIE ein Ende-Tag. Standen sie bei "mit Inhalt
  verwerfen", kehrte der Tiefenzaehler nie auf 0 zurueck und **alles dahinter verschwand** – und
  ein aus Outlook kopiertes Signatur-HTML beginnt typischerweise mit `<meta>`: die Anschrift waere
  restlos weg gewesen, ohne jede Meldung. Jetzt drei Klassen (`_TOETEN` / `_LEER_WEG` / Rest:
  Tag weg, **Inhalt bleibt**).
- **Kein Markdown beim Umsetzen nach HTML.** Der Text ist von einem Menschen freigegeben; aus
  `**wichtig**` Fettdruck zu machen aendert einen freigegebenen Text nachtraeglich, und `3*4`
  waere Auszeichnung. Uebersetzt wird nur, was in reinem Text keine Bedeutung hat: Absaetze und
  Umbrueche.
- **Vorgabe ist HTML** (`format_fuer` faellt darauf zurueck) – **umgestellt am 2026-08-26 auf
  Vorgabe des Nutzers**, bis dahin Text mit der Begruendung „ein Postfach, das ohne Zutun HTML
  verschickt, waere eine Ueberraschung". In der Praxis war die Ueberraschung die andere: eine
  Signatur mit Logo, Links und Farben wird im Textformat plattgeklopft, und niemand rechnet damit,
  dass eine Antwort aus einem Web-Formular reiner Text ist. **Text bleibt waehlbar** – pro Antwort
  im Pulldown oder dauerhaft am Postfach; ein gespeichertes `"text"` gewinnt gegen die Vorgabe.
  - **⚠ LEER heisst jetzt HTML, und das betrifft DREI Anzeigestellen.** `formatOptionen()` und die
    Feldbelegung in `fuelleKonto`/`zeigeKonto` pruefen deshalb auf **`=== 'text'`**, nicht auf
    `=== 'html'`: andersherum stuende an einem unberuehrten Postfach „Vorgabe (Nur Text)", waehrend
    der Server HTML sendet – eine Anzeige, die einen Zustand behauptet, den sie nicht kennt. Im
    Pulldown steht **HTML zuerst**: die erste Option soll das sein, was ohne Zutun passiert.
  - Der Waechter prueft das FELD (`antwort_format === 'html'` darf nirgends mehr vorkommen), nicht
    das Muster `=== 'html'` – in derselben Funktion steht `gewaehlt === 'html'` fuer die
    vorausgewaehlte Option, und ein grobes Muster meldet die als Verstoss (beim ersten Lauf genau
    so passiert).
- Ein UNGUELTIGER Wert faellt auf die Vorgabe des Postfachs, nicht auf einen geratenen; beim
  SPEICHERN wird er dagegen **abgewiesen** (sonst springt das Feld zurueck und niemand erfaehrt
  warum), und Rich-Text wird namentlich genannt.
- **`antwort_format` steht in `AENDERBAR`, `signaturen` NICHT** – ein Skalar darf ein Formular
  mitsenden, eine Liste wuerde bei zwei offenen Fenstern den jeweils anderen Stand ueberschreiben
  (dieselbe Begruendung wie bei `stile`). Ein UI-Test prueft, dass der Speichern-Knopf des
  Postfachs die Liste nicht mitschickt.
- **Beim Loeschen rueckt KEINE nach**, verwaiste Kennung → Standard **mit Hinweis** (eine Antwort,
  die wegen einer verwaisten Referenz nicht hinausgeht, ist der schlechtere Ausgang). `SIG_KEINER
  = "-"` ist die ausdrueckliche Wahl "ohne" und muss von leer unterscheidbar bleiben.
- **Deckel:** `SIG_TEXT_MAX = 4000`, `SIG_HTML_MAX = 60000`. Der HTML-Deckel ist bewusst viel
  groesser: ein eingebettetes Logo als `data:`-URI ist Kilobyte. Anders als `VORGABE_MAX` haengt
  hier **kein Modell-Kontext** dran – die Begruendung des Stil-Deckels gilt nicht.
- **Der Reiter heisst jetzt „Antworten"** (`addin.tab_stile`, Schluessel unveraendert – nur der
  WERT): er haelt Stile UND Signaturen. Bei 320 px Fensterbreite und fuenf Reitern ist "Stile &
  Signaturen" nicht unterzubringen, und wer Signaturen sucht, findet sie unter "Stile" nicht.
- `.ad-grid2` fuer die zwei Pulldowns nebeneinander: `min-width: 0` ist Pflicht, sonst schrumpft
  ein Grid-Kind nicht unter seine Inhaltsbreite und schiebt das zweite Feld aus dem Fenster.
- **Verifiziert:** `tests/test_mail_body.py` (74, ohne Fremdmodule) ·
  `tests/test_mail_signaturen.py` (98) · `tests/test_mail_sig_ui.js` (89, jsdom gegen die echten
  Dateien; die Antwort-Vorschau wird ENDE ZU ENDE geklickt). Gegenproben beissen einzeln:
  `richtext` durchgelassen 3 FAIL, void-Elemente zurueck in `_TOETEN` 4, Signatur nicht angehaengt
  1, `signatur` im Werkzeug-Schema 1, Rich-Text waehlbar 3.
  **FALLSTRICKE im eigenen Test:** ohne Office-Attrappe wartet das Fenster 4 s und zeigt WEDER
  Anmeldung NOCH Anwendung; und `POST /api/email/account` musste im Mock dasselbe Konto-Objekt
  antworten wie `/status` – mit `{ok:true}` wurde `_konto` null und der Nachricht-Reiter zeigte
  "hinterlege zuerst dein Postfach".

#### „Aus dem Postfach übernehmen" (2026-08-26)
**Gemeldet:** „im Outlook-Add-In ist bei ‚Signatur' nur ‚keine Signatur' auswaehlbar." Zutreffend
– und meine erste Antwort war methodisch wertlos: **ich habe auf DEV gemessen, das Add-in laeuft
gegen ECHT.** Der Befund stimmte danach trotzdem (auf ECHT `signaturen: []`), aber die Frage war
eine andere: **das Postfach HAT eine Signatur**, Jarvis hat sie nur nie abgeholt.
- **Was gelesen wird, ist die Signatur des POSTFACHS**, nicht die aus Outlook auf dem Arbeitsplatz.
  Letztere liegt in `%APPDATA%\Microsoft\Signatures` und ist von hier prinzipiell unerreichbar;
  ausserdem baut Jarvis die Antwort **serverseitig**, sie durchlaeuft Outlooks Verfassen-Weg also
  nie. Erreichbar ist die UserConfiguration **`OWA.UserOptions`** (`signaturetext`,
  `signaturehtml`, `autoaddsignature`) – dasselbe Objekt, das
  `Get-MailboxMessageConfiguration` liest. Am echten Exchange 2019 gemessen: sie liegt im
  **`root`**, ueber `msg_folder_root` kommt `ErrorItemNotFound`.
- **Office.js scheidet aus:** es gibt in KEINEM Requirement Set ein `getSignature…`; ab 1.10 nur
  `setSignatureAsync` (schreiben), und das Manifest ist auf **Mailbox 1.3** festgenagelt, weil ein
  hoeherer Satz auf Exchange 2019 im Haus nicht installierbar ist.
- **`autoaddsignature` kommt als ZEICHENKETTE** `"True"`/`"False"` herein – `bool(wert)` waere fuer
  `"False"` wahr. Die Schluessel werden ohne Ruecksicht auf Gross/Klein gesucht: die
  Kleinschreibung ist eine Beobachtung an EINEM Server, keine Zusage von Microsoft.
- **„Es gibt keine" ist eine AUSKUNFT, kein Fehler** (`leer: True`) – aus „Vorgang fehlgeschlagen"
  kann die Oberflaeche nicht ableiten, dass im Postfach schlicht nichts hinterlegt ist.
  **IMAP gibt aber NICHT `leer` zurueck**, sondern lehnt im Klartext ab: dieser Kanal weiss es
  nicht, und „nichts hinterlegt" waere eine Behauptung ueber etwas Ungeprueftes.
- **Fester Name `SIG_IMPORT_NAME`,** nicht waehlbar: nur so ist eine zweite Uebernahme als
  Auffrischung derselben Kopie erkennbar. Ohne das haette man nach dreimaligem Druecken drei fast
  gleiche Signaturen und wuesste bei keiner, welche aktuell ist. **Aufgefrischt wird unter
  DERSELBEN Kennung** – Regeln zeigen weiter darauf.
- **409 statt stillem Ueberschreiben.** Der vorhandene Eintrag kann von Hand nachbearbeitet worden
  sein. Eigene Fehlerkategorie **`vorhanden`**, damit der Aufrufer die Rueckfrage am STATUS
  aufhaengt und nicht am Meldungstext (ein Waechter, der Texte vergleicht, bricht beim ersten
  Umformulieren). Im Aufgabenfenster **`frage()`, nie `confirm()`** – WebView2 unterdrueckt es.
- **Zu gross wird ABGELEHNT, nicht gekuerzt.** `sig_anlegen` schneidet still auf `SIG_TEXT_MAX`/
  `SIG_HTML_MAX`; bei HTML faellt der Schnitt mitten in ein Tag, und was danach fehlt, sieht
  niemand. Die Meldung nennt beide Zahlen.
- **⚠ DER BEFUND, DEN ERST DIE ECHTE SIGNATUR ZEIGTE: die Logos gehen NICHT mit.** Eine in Outlook
  gebaute Signatur verweist ihre Bilder auf
  `file:///C:/Users/<name>/AppData/Local/.../clip_image002.png` – die Platte des Absenders. Outlook
  loest das beim Verfassen auf und haengt sie als `cid:` an; ein serverseitiger Versand kann das
  nicht, und `_SRC_OK` laesst `file:` zu Recht nicht durch (das waere ein lokaler Dateizugriff).
  Deshalb **zaehlt** `html_entschaerfen_mit_bericht()` sie und die Meldung nennt die Zahl: sonst
  uebernimmt jemand seine Signatur, das Logo fehlt, und **nichts erklaert warum.** An der echten
  Signatur gemessen: 7378 → 5462 Zeichen, **4 Bilder weg**, Text/Anschrift/Mailadresse/Links
  vollstaendig erhalten.
- **Es ist eine KOPIE, keine Verknuepfung** – der Hinweis unter dem Knopf sagt das ausdruecklich.
  Ein Knopf, der einen Abgleich suggeriert, laesst eine spaeter in Outlook geaenderte Anschrift
  unbemerkt falsch hinausgehen.
- **Verifiziert:** `tests/test_mail_signaturen.py` (153). Gegenproben beissen einzeln:
  Groessenpruefung raus 3 FAIL, `autoaddsignature` per `bool()` 1, Status nicht durchgereicht 1,
  Benutzer aus dem Rumpf 1, Bilder-Zaehler raus 1. **Live auf DEV gegen das echte Exchange** ueber
  den HTTP-Weg: `200` (`art: neu`, 1158/7378 Zeichen, `bilder_weg: 4`) · `409` beim zweiten Lauf ·
  `200` (`art: aktualisiert`, gleiche Kennung) mit `ersetzen: true`.
- **FALLSTRICK, ZWEIMAL AM SELBEN TAG bezahlt:** die Probe lief als **root** und schrieb dabei
  `data/email_accounts.json` neu – Eigentuemer danach `root:root` bei 0640, der Dienst als `jarvis`
  bekam `Permission denied` und meldete fuer JEDEN Benutzer „kein Postfach hinterlegt". **Die API
  antwortete dabei freundlich mit einem leeren Konto**; der einzige Hinweis stand im Journal
  (`[Mail] Kontendatei nicht lesbar`). Beim zweiten Mal habe ich den Fehler in der frisch gebauten
  Uebernahme gesucht, obwohl er in meinem eigenen Aufruf lag.
  **Rezept, das beide Male gereicht haette:** Probe-Skript nach `/tmp` (nicht `/root` – dort kommt
  `jarvis` nicht heran) und mit `runuser -u jarvis -- venv/bin/python` starten. Wer in einer Probe
  eine Datendatei SCHREIBT, tut das als Dienstbenutzer; wer nur liest, darf root bleiben.

#### Bedienhilfen
- **Tab-Uebernahme** (`frontend/js/tabfill.js`): TAB uebernimmt in einem **leeren** Feld den
  Beispieltext. **OPT-IN ueber `data-tabfill`, niemals global** – ein Platzhalter ist nicht
  automatisch ein Vorschlag (`vorname.nachname@firma.de` ist eine Formvorgabe, sie zu uebernehmen
  hiesse ein Beispiel zu speichern). Markiert sind nur Freitext-Anweisungen an ein Modell.
  `data-i18n-tabfill` fuer eigene Vorschlagstexte; die Uebernahme feuert `input` (Zaehler und
  Formular-Spiegel haengen daran) und markiert den Text.
- **Feld-Erklaerungen (ⓘ)** als AUFKLAPPENDER Text, nicht als schwebendes Popup – im 320 px
  breiten Fenster waere ein Popup abgeschnitten, `title` ist auf Touch und im Outlook-WebView
  unzuverlaessig. **EIN delegierter Listener** am Dokument, damit jedes spaeter ergaenzte ⓘ
  automatisch wirkt (Markup-Regeln: Register).
- **Beschriftungen:** der Platzhalter der Ordnerfelder heisst „Standardordner" (nicht „Vorgabe" –
  Wortkollision mit dem Feld darunter), das Stilfeld „Stil und Signatur fuer Antworten".
  **Kein „(PrePrompt)"** – die Zielgruppe sind Sachbearbeiter. Der HTML-Rueckfall musste mit.
- **Sicherheits-Erklaerung (ⓘ)** am „Wichtig"-Absatz in `/email` **und** im Regeln-Reiter, beide
  auf `mail.help_security`: „Was du selbst tun musst" (Absender ins FELD, Werkzeuge eng,
  Protokoll ansehen, Versand-Risiko) und „Was das System dagegen tut" – mit der ausdruecklichen
  Grenze, dass die Massnahmen auf der Sprachebene wirken und die harte Grenze der
  Werkzeug-Zuschnitt ist.

### Branding im Fenster
- Drei Stellen, nicht eine: `taskpane.html` bindet `branding.js` ein und nutzt `.topbar-avatar` /
  `.brand-app-name`; Menueband-Symbole ueber **`/addin/icon-<n>.png`** (skaliert das Branding-Logo
  mit Pillow, **fail-safe zum eingebauten Zeichen** bei SVG/Fehler/fehlendem Branding); Download
  heisst `<marke>-outlook-addin.xml` (ASCII-entschaerft, geht in einen `Content-Disposition`-Kopf).
  Texte in `addin.js` sind **markenneutral** formuliert – sie werden per `textContent` gesetzt,
  dorthin kommt `branding.js` nicht.
- **`ADDIN_VERSION` musste hier steigen** (1.2.0.0): Outlook laedt ein geaendertes Manifest nur
  bei gestiegener Version, sonst behalten installierte Add-ins die alten `/static`-URLs.
- **Farb-Fallbacks `var(--x, #hex)`: die Ausnahme, die bleiben muss** – der
  **Konto-gesperrt-Bildschirm** in `chat.html`/`userchat.html` ist als *„Sicherheitsschicht,
  CSS-unabhaengig"* inline gestaltet. Ohne `theme.css` gemessen: ohne Fallback schwarzer Text auf
  transparentem Kasten ueber dunklem Overlay = unlesbar, genau wenn der Benutzer die
  Sperrbegruendung braucht. **Eine Konvention prueft man am Zweck der Stelle, nicht an ihrer Form.**

### Auffindbarkeit
Abschnitt *Outlook-Add-in* in `/email` zwischen Postfach und Regeln, mit Download-Knopf und
aufklappbarer Anleitung – wer gerade sein Postfach hinterlegt hat, ist der Adressat.
**Keine Admin-Rechte noetig.**

### Verifiziert
`tests/test_outlook_addin.py` (192) · `tests/test_addin_sso.py` (193, Token mit echtem
RSA-Schluessel und selbst ausgestelltem X.509 **wirklich signiert** – eine gefaelschte
Signaturpruefung haette den Punkt verfehlt, auf dem alles ruht) · `tests/test_addin_update_ui.js`
(99) · `tests/test_mail_styles.py` (181) · `tests/test_tabfill_ui.js` (41).
**Manifest von Microsofts eigenem Werkzeug abgenommen** (`npx office-addin-manifest validate`) –
der Abfrageteil in `SourceLocation` ist damit belegt zulaessig. Live auf DEV: gefaelschtes Token
vom fremden Exchange 401 mit Nennung der hinterlegten Adresse, `runuser -u jarvis_sandbox -- cat
data/addin_links.json` verweigert. **Im echten Outlook belegt** (Sideload, Menueband, Lauf ueber
„Jetzt verarbeiten", kennwortlose Anmeldung).


#### FALLSTRICK: gleich lange Konstanten + gleiche Sekunde = veraltete `.pyc`
Beim Umstellen der Vorgabe meldeten die Tests nach dem Zurueckdrehen einer Gegenprobe weiter den
alten Wert – die Quelldatei sagte `return mail_body.FORMAT_HTML`, `inspect.getsource` bestaetigte
es, und der **Bytecode enthielt `FORMAT_TEXT`** (`f.__code__.co_names`). Ursache: Python haelt eine
`.pyc` fuer gueltig, wenn **Groesse und mtime in ganzen Sekunden** zur aufgezeichneten Quelle
passen. `FORMAT_TEXT` und `FORMAT_HTML` sind **gleich lang**, und `sed` + `cp` liefen in derselben
Sekunde – beide Merkmale stimmten also, obwohl der Inhalt ein anderer war.
**Zwei verlorene Gegenproben, bis es auffiel.** Merkregel: bei Gegenproben, die eine Konstante
gegen eine gleich lange tauschen, `PYTHONDONTWRITEBYTECODE=1` setzen (oder `__pycache__` leeren) –
und wenn eine Pruefung dem Quelltext widerspricht, **`co_names` ansehen statt der Datei**.
