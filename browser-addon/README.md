# Jarvis für Jira – Browser-Erweiterung

Wer ein Jira-Ticket offen hat, bekommt über das Symbol in der Symbolleiste

* eine **Zusammenfassung** des Vorgangs (worum es geht, was passiert ist, woran es hängt) und
* einen **Antwortvorschlag** an den Melder, den ein Klick als Kommentar übernimmt
  (**Als Kommentar übernehmen** ersetzt den bisherigen Inhalt des Kommentarfeldes;
  in Jira holt Strg+Z ihn zurück).

**Abgeschickt wird in Jira, von Hand.** Jarvis schreibt nichts in ein Ticket.

## Wie es arbeitet

Die Erweiterung liest **nur die Ticketnummer aus der Adresszeile** (`…/browse/ABC-123`).
Beschreibung und Kommentarverlauf holt der Jarvis-Server selbst über die Jira-API – die
Erweiterung liest den Seiteninhalt nicht. Das ist bewusst so: das DOM ändert sich mit jeder
Jira-Version, die URL nicht, und über die API kommt der vollständige Verlauf statt dessen,
was gerade aufgeklappt ist.

Dahinter läuft **kein Agent**, sondern ein einzelner Modellaufruf ohne Werkzeuge. Der Grund
steht im Kopf von `backend/jira_assist.py`: in ein Ticket schreibt ein Kunde, was er will.

## Seitenleiste oder Popup (seit 0.3.0, Vorgabe seit 0.9.0)

Der Klick auf das Symbol öffnet **voreingestellt die Seitenleiste** – sofern der Browser
eine kennt. Sie bleibt beim Arbeiten im Ticket offen und lässt sich in der Breite
ziehen. Ein Popup kann das nicht – der Browser zeichnet es um seinen Inhalt und klemmt
es auf 800 × 600, eine API zum Bemessen gibt es nicht. Ein Schalter am Fuß des Fensters
stellt jederzeit zurück auf **Popup**.

**Die Vorgabe hat bis 0.8.5 „Popup" gelautet** (umgestellt auf Anweisung 2026-09-03).
Beim Ausrollen ist das eine sichtbare Änderung: wer den Schalter nie angefasst hat,
bekommt ab dem ersten Klick die Leiste. Wer ausdrücklich „Popup" gewählt hat, behält es –
`ansichtLesen()` kennt deshalb **drei** Zustände (`leiste` / `popup` / Feld fehlt), nicht
zwei: eine Vorgabe darf eine Entscheidung nicht überstimmen.

**`leisteMoeglich()` ist Teil der Vorgabe, nicht Beiwerk.** Auf einem Browser ohne
Leiste leert `ansichtAnwenden` den Popup-Pfad, `onClicked` findet danach keine
Leisten-API – und der Klick aufs Symbol öffnet **gar nichts**. Fail-safe ist hier die
schmalere Funktion. Aus demselben Grund bleiben zwei Manifest-Schlüssel unangetastet:
`action.default_popup` (gilt, bis der Service-Worker das erste Mal lief, und ist der
Rückfall, falls `setPopup` scheitert) und `sidebar_action.open_at_install: false` –
Firefox klappte die Leiste sonst schon beim Installieren ungefragt auf, und Chrome kennt
dafür keine Entsprechung. Die Vorgabe greift in beiden Browsern beim **ersten Klick**.

**Es ist dieselbe `popup.html`.** Eine zweite Oberfläche wäre eine Kopie, und Kopien
laufen auseinander – dieselbe Begründung, aus der es zwei Manifeste, aber nur eine
Codebasis gibt. Unterschieden wird über den Abfrageteil `?ansicht=leiste`, aus dem
`ansicht.js` eine Klasse am `<html>` macht.

| | Chrome / Edge | Firefox |
|---|---|---|
| API | `sidePanel` (ab Chrome 114) | `sidebarAction` |
| Manifest | `side_panel.default_path` + Permission `sidePanel` | `sidebar_action.default_panel` |
| Breite gemerkt | **nein**, öffnet wieder mit der Standardbreite | ja |

Drei Punkte, die man beim Anfassen kennen muss:

* **`action.setPopup` ist der Umschalter.** Solange ein Popup gesetzt ist, gewinnt es:
  `openPanelOnActionClick` bleibt wirkungslos und `onClicked` feuert nicht. Erst ein
  **leerer** Popup-Pfad gibt den Klick frei (`background.js::ansichtAnwenden`).
* **Der Abfrageteil steht NICHT im Manifest.** Für `setOptions`/`setPanel` ist ein Pfad
  mit `?…` belegt, für die Manifest-Schlüssel nicht – und ein Manifest, das der Browser
  ablehnt, macht die ganze Erweiterung uninstallierbar. Fällt der Aufruf aus, lädt die
  Leiste ohne Abfrageteil: schmal, aber benutzbar.
* **Vor dem Öffnen darf kein `await` stehen.** `sidePanel.open()` und
  `sidebarAction.toggle()` verlangen eine Benutzergeste, und die ist nach dem ersten
  `await` verbraucht – der Aufruf wird dann abgelehnt, und sichtbar passiert einfach
  nichts.

**Was die Leiste kostet:** sie überlebt den Tab-Wechsel, also muss der Ticketbezug bei
jedem Wechsel neu geprüft werden (`popup.js::tabWechsel`) – sonst stünde ein fertiger
Antwortentwurf zu Ticket A neben dem geöffneten Ticket B. Und `activeTab` gilt nur für
den Tab, aus dem die Leiste geöffnet wurde; für „Meinen Kommentar überarbeiten" und „Einfügen" in weiteren
Tabs erfragt sie einmalig ein dauerhaftes Zugriffsrecht auf den Jira-Server.

**⚠ `sidePanel` und `sidebarAction` NIE über `api` ansprechen.** `api` ist
`browser ?? chrome`, und Chrome definiert inzwischen selbst ein `browser`-Objekt — in dem
`sidePanel` als Chrome-eigene API **nicht** vorkommt. `api.sidePanel` war damit `undefined`,
obwohl `chrome.sidePanel` existiert: die gesamte Panel-Steuerung war ein stiller No-op, und
die Fähigkeitsprüfung meldete „dieser Browser kann das nicht" auf einem Browser, der es kann.
Herstellereigene APIs werden über `zweig(name, methode)` an **beiden** Wurzeln gesucht.
`browser ?? chrome` taugt nur für standardisierte APIs.

Drei weitere Fallen, die das im ersten Anlauf halb tot gemacht haben (gemeldet, Chrome 152):

* **Die Erkennung darf nicht am Abfrageteil hängen.** `?ansicht=leiste` kommt nur mit,
  wenn die Leiste über unseren Weg aufgeht – über **Chromes eigene Seitenleisten-Auswahl**
  lädt sie `side_panel.default_path`, also `popup.html` ohne Abfrageteil, und das Fenster
  hielt sich für ein Popup: kein Tab-Zuhörer, feste Breite. Verbindlich antwortet der
  Hintergrund über `runtime.getContexts` (`kontextArt`); die Klasse aus `ansicht.js` ist
  nur noch der Anfangswert für die Breite.
* **`tabs.onUpdated` darf nicht auf `changeInfo.url` filtern.** Das liefert der Browser nur
  mit der `tabs`-Berechtigung oder einem Host-Recht für genau diese Seite – die Erweiterung
  hat beides von Haus aus nicht. Entschieden wird über den Vergleich in `tabWechsel`.
* **Die Zugriffszeile darf nicht an einer Ticketnummer hängen.** Ohne Host-Recht gibt es
  gar keine Tab-Adresse und damit keine Ticketnummer – die Zeile wäre genau dann verborgen,
  wenn man sie braucht. Den Ort für die Abfrage liefert `GET /api/jira/assist/health` als
  `jira_basis`.

**`ansicht.js` gehört in DREI Listen:** die Einbindung in `popup.html`, `DATEIEN` in
`bauen.sh` und `PAKET_DATEIEN` in `backend/jira_assist.py`. Laufen sie auseinander,
installiert sich das Paket klaglos und die Leiste ist still 380 px schmal.
`tests/test_browser_addon.js` prüft das als Regel, nicht als Aufzählung.

## Die Vorlage ist die Aktion (seit 0.8.0)

Es gibt **ein** Startsymbol – ein Dreieck links vom Pulldown **Vorlage** – und es führt die
gewählte Vorlage aus. Was dabei herauskommt, sagt die **Art** der Vorlage
(`jira_vorlagen.ARTEN`): *Zusammenfassung* für den Bearbeiter oder *Antwort an den Melder*
für den Kunden. Der erste Eintrag heißt **Zusammenfassen** und braucht keine Vorlage –
dahinter steckt der eingebaute Zusammenfassungs-Prompt (seit 0.8.4; bis dahin hieß er
*Ohne Vorlage* und ein Satz darunter erklärte, was dabei herauskommt).

Bis 0.7.1 standen dort zwei Knöpfe, *Zusammenfassen* und *Antwort vorschlagen*. Beide sind
jetzt Vorlagen; die mitgelieferte **Antwort an den Melder** ersetzt den zweiten Knopf und
wird auf bestehenden Servern **einmalig nachgetragen** (`jira_vorlagen._nachtrag_antwort`) –
ohne diesen Nachtrag wäre die Aktion nach dem Update ersatzlos weg.

**Der Modus wird am SERVER aus der Vorlage bestimmt** (`jira_assist.auswerten`), nicht im
Fenster. Das Feld `modus` im Request ist nur ein Wunsch: so gibt es eine Quelle, und ein
Fenster einer älteren Fassung kann keine Antwort-Vorlage als Zusammenfassung fahren.
Ausgenommen ist *Meinen Kommentar überarbeiten* – eine Vorlage darf diese Aufgabe nicht
umbiegen, sonst würde statt einer Korrektur ein völlig neuer Text entstehen.

## Ein gemerkter Lauf JE TICKET (seit 0.9.0)

Gemeldet: *„nach Reiterwechsel ist die Antwort leider wieder weg (oder das Antwort-Feld einfach
nur nicht mehr sichtbar?)"*. Im echten Chrome gemessen: **wirklich weg**. Es gab genau **einen**
Speicherplatz, und der Reiterwechsel rief `felderLeeren` – also die Funktion, die Anzeige *und*
Ablage abräumt. Beim Zurückwechseln stand das Feld leer da, ohne jede Erklärung; in der
Seitenleiste (seit 0.9.0 die Vorgabe) passiert das beim normalen Arbeiten ständig.

Der Speicher ist jetzt eine **Abbildung Ticket → Lauf** (`ergebnisse` in `storage.local`), gedeckelt
auf **fünf** Einträge (`ERGEBNIS_MAX`; verdrängt wird der älteste, ein Eintrag ohne Zeitstempel gilt
als ältester). Ein vor dem Update gemerkter Lauf wird **einmalig migriert**, der alte Einzelplatz
danach entfernt.

* **Die Sicherheitszusage bleibt unangetastet und wird strenger:** angezeigt wird nur der Eintrag,
  dessen `key` dem **offenen** Ticket entspricht. Deshalb eine Abbildung und keine Liste – es gibt
  keinen Zustand, in dem ein Text zu Vorgang A neben Vorgang B steht. Das Fenster fragt je Ticket
  (`{art:"ergebnis", key}`) und bekommt einen fremden Entwurf gar nicht mehr zu sehen.
* **`zustand` liefert das Ergebnis NICHT mehr mit.** Zu dem Zeitpunkt weiß nur das Fenster, welcher
  Vorgang offen ist (es ermittelt den Tab erst danach). Den „letzten" mitzuschicken wäre genau der
  Zustand, gegen den die Schranke gebaut ist.
* **`anzeigeLeeren` vs. `felderLeeren` ist der Kern.** Reiterwechsel → nur Anzeige. Leeren/Reset →
  auch Ablage, und dann mit Ziel: `{wert:null, key}` nimmt einen Eintrag, `{wert:null, alle:true}`
  alle. Ein `{wert:null}` **ohne** beides räumt bewusst nichts – so sah der Aufruf vor dem Fix aus.
* **Der Merk-Timer muss beim Leeren der Anzeige mit.** Wer den Vorschlag bearbeitet hat, hat einen
  Timer offen, der `_letztes` eine halbe Sekunde später zurückschreibt – ohne `clearTimeout`
  schriebe er nach dem Wechsel den Text unter dem Schlüssel des **vorigen** Tickets erneut, mit dem
  Inhalt, den das Feld zufällig gerade hat.
* **Preis, ausdrücklich:** es liegt mehr Kundentext auf der Platte des Arbeitsplatzes – bis zu fünf
  Ticket-Entwürfe, bis zum Leeren, Zurücksetzen oder Abmelden. Deshalb der Deckel: ohne ihn wüchse
  der Bestand mit jedem angesehenen Vorgang weiter, unbemerkt.
* **Was bleibt:** ein Ticket **ohne** Eintrag zeigt ein leeres Feld und **schweigt** – so sieht
  jeder frisch geöffnete Vorgang aus, eine Meldung wäre Rauschen. Wird ein Eintrag durch den Deckel
  verdrängt, ist das von „gab es noch nie" nicht zu unterscheiden.

## Der Abschnitt „⚙ Einstellungen" klappt ein (seit 0.9.0)

Sichtbar bleiben **Zahnrad und Wort**, alles darunter (Pulldown und Hinweis) fällt weg.
**Startzustand ZU**, der Zustand wird gemerkt (`einst_offen` in `storage.local`). Grund: die
Einstellungen werden einmal getroffen und gelten über das Fenster hinaus – sie müssen nicht
bei jedem Öffnen Platz kosten, während darüber die eigentliche Arbeit steht. Gemessen bei
380 × 600: die Seite wird von 536 auf 434 px kürzer.

Vier Punkte, die man beim Anfassen kennen muss:

* **Die Überschrift ist ein `<button>`, kein klickbares `<h2>`.** Ein `<h2>` ist von sich aus
  weder fokussierbar noch als Bedienelement erkennbar – der Abschnitt wäre mit der Tastatur
  nicht aufklappbar. Das CSS nimmt dem Knopf alles Knopfhafte wieder ab und holt Größe,
  Halbfett und Dämpfung über `font: inherit` aus `.abschnitt-titel`.
* **Er trägt `data-ohne-ticket`.** Die Ticket-Sperre sperrt pauschal jeden `<button>` ohne
  dieses Attribut (fail-closed). Ohne es wäre der ganze Abschnitt auf einem Tab **ohne**
  erkanntes Ticket unerreichbar – genau der Fehler, der am 2026-08-31 für das Zahnrad der
  Vorlagen gemeldet wurde: eine Einstellung dieses Browsers hat mit dem offenen Tab nichts
  zu tun.
* **Das Markup startet mit `hidden` und `aria-expanded="false"`.** Ohne beides blitzte der
  Abschnitt bei jedem Öffnen kurz auf, bevor der Zustand aus dem Hintergrund da ist.
* **Der Zustand liegt im Hintergrund, nicht im Fenster.** Das Fenster wird bei jedem Klick
  daneben zerstört; ein Merker im Modul wäre beim nächsten Öffnen weg, und ein Abschnitt, der
  sich jedes Mal wieder zuklappt, ist genau die Sorte Bedienelement, die niemand benutzt.
  `einst_offen` muss deshalb in `einstSchreiben` stehen – ein Feld, das dort fehlt, wird
  **wortlos** verworfen (ein Test prüft das als Regel).

**Der Seitenleisten-Schalter bleibt DRAUSSEN** (Entscheidung 2026-09-03). Er steht bewusst
außerhalb von Anmeldung und Arbeitsbereich: wer in der Leiste steht und zurück zum Fenster
will, muss das auch ohne Konto können – dieser Abschnitt liegt dagegen im Arbeitsbereich.
In der Leiste steht unter ihm **kein Hinweis** mehr; „Die Breite ziehst du an der Kante der
Leiste." war eine Auskunft an jemanden, der die Leiste vor sich hat und ihre Kante sieht. Im
Popup bleibt der Hinweis: dort ist die Wirkung eines Klicks nicht ablesbar.

## Automatik bei neuem Ticket (seit 0.4.0, Vorlagen seit 0.8.0)

Im Pulldown **Bei neuem Ticket automatisch** (unter **⚙ Einstellungen**, eingeklappt) lässt
sich eine **Vorlage** so einstellen, dass
sie von selbst startet, sobald ein Ticket erkannt wird. **Vorgabe ist „Nichts"** – jeder Lauf
kostet eine Auswertung auf dem Server, das darf nicht ungefragt passieren.

Gespeichert wird die **Kennung** der Vorlage im Feld `auto_vorlage`. Der frühere Feldname
`auto_modus` wird nicht mehr gelesen: ein alter Wert ließe sich nicht verlässlich auf eine
Vorlage abbilden, deshalb ist die Automatik nach dem Update **aus**, bis jemand eine Vorlage
wählt. Zeigt die gespeicherte Kennung ins Leere (Vorlage gelöscht), schaltet
`popup.js::autoOptionenZeichnen` die Automatik ab **und sagt es** – ein stilles Umbiegen auf
eine andere Vorlage wäre schlimmer.

*Meinen Kommentar überarbeiten* steht bewusst nicht zur Wahl: es braucht einen Entwurf, den
der Bearbeiter selbst ins Kommentarfeld geschrieben hat – bei einem gerade geöffneten Ticket
gibt es den per Definition nicht.

**„Neu" heißt: höchstens ein automatischer Lauf je Ticket.** Zwei Schranken zusammen:

* **Es läuft nichts, wenn schon ein Ergebnis zu diesem Ticket vorliegt**
  (`popup.js::autoAktionPruefen`, Argument `passt`). Das ist keine Sparmaßnahme: der
  gemerkte Text kann **bearbeitet** sein, und ein automatischer Lauf würde ihn
  überschreiben, ohne dass jemand etwas gedrückt hat.
* **Ein Ringspeicher der letzten 20 Ticketnummern** (`background.js::autoStart`). Ohne ihn
  feuert jeder Tab-Wechsel zurück auf ein schon gesehenes Ticket einen weiteren Lauf – in
  der Seitenleiste, in der man zwischen zwei Vorgängen hin- und herwechselt, wären das zwei
  Läufe je Runde.

Geprüft **und** vermerkt wird im Hintergrund, in einem Schritt: läge dazwischen eine
Nachrichtenrunde, ließen zwei schnelle Tab-Wechsel dieselbe Nummer zweimal durch. Vermerkt
wird **vor** dem Lauf – ein Server, der gerade nicht antwortet, würde sonst bei jedem
Tab-Wechsel erneut angefragt. Preis: schlägt der eine automatische Lauf fehl, gibt es
keinen zweiten von selbst; der Knopf daneben steht bereit.

Der Ring liegt in `storage.local`, nicht im Arbeitsspeicher: das Popup wird bei jedem Klick
daneben zerstört, und unter MV3 beendet der Browser auch den Service-Worker. Beim
**Abmelden** wird er geleert (es sind die Ticketnummern des vorigen Benutzers); die
Einstellung selbst bleibt – sie gehört zu diesem Browser, nicht zu einer Anmeldung.

Ein Umschalten wirkt **ab dem nächsten Ticket**, nicht sofort – das sagt die Rückmeldung
auch. Sofort zu starten hieße, ein bereits angezeigtes Ergebnis zu überschreiben.

## Das Ergebnisfeld ist Rich-Text (seit 0.5.0)

`#f-ergebnis` ist kein `<textarea>` mehr, sondern ein bearbeitbares
`contenteditable`-`<div>`: `**Lösung:**` steht dort **fett** statt als Sternchen.

**Kanonisch bleibt der Text mit `**…**`.** Gespeichert, im Hintergrund abgelegt und an den
Server geschickt wird unverändert diese Form – das Speicherformat hat sich nicht geändert,
`background.js` ist unberührt, `STAND` bleibt 5. Das Feld ist nur eine zweite Darstellung
davon, der Jira-Kommentar die dritte.

* **Aufgebaut wird mit Knoten, nie mit `innerHTML`** (`popup.js::textZuFeld`). Der Text
  stammt aus einem Modell, das Kundentext verarbeitet hat; mit `innerHTML` wäre ein
  `<img src=x onerror=…>` aus einem Ticket im Origin der Erweiterung ausführbar – und dort
  liegt das Sitzungstoken.
* **Ein Parser für alles** (`zuBloecken`). Anzeige und Einfügen bauen aus demselben
  Ergebnis; zwei Parser würden auseinanderlaufen, und dann sähe der Mitarbeiter etwas
  anderes, als der Kunde bekommt.
* **Der Rückweg ist auf echte Browser gemessen**, nicht angenommen: Chrome macht beim Enter
  ein weiteres `<div>`, **Firefox gar keines, sondern ein `<br>` auf oberster Ebene**;
  Strg+B liefert `<b>` oder `<span style="font-weight:700">`; ein leerer Block endet auf
  einem Füllwerk-`<br>`; Einfügen bringt `<i>` und `<span style>` mit. `feldZuText`
  behandelt all das und klopft alles Unbekannte flach.
* **Eingefügt und fallengelassen wird nur Klartext** (`paste`/`drop`), sonst sammelt sich
  Fremdformatierung an.
* **Nebengewinn:** Strg+B im Feld wird als `**…**` zurückgeschrieben – der Mitarbeiter kann
  selbst fett auszeichnen.

### Was beim Einfügen in Jira ankommt

Die geparste Struktur geht als zweites Argument über `executeScript({args})` mit – die
injizierte Funktion darf nichts aus ihrem Modul benutzen (sie wird per `toString`
übertragen) und braucht so keinen eigenen Parser.

* **Ohne Fettstellen ändert sich nichts** gegenüber vorher: `execCommand("insertText")`
  zuerst, Knoten-Rückfall danach.
* **Mit Fettstellen** eine Kaskade mit **Rückleseprobe**: `insertHTML` (selbst gebaut, Text
  über `textContent` – Modelltext berührt nie einen HTML-Parser) → Knoten mit `<strong>` →
  und wenn danach nichts im Feld steht, `insertText` mit bereinigtem Text. Denn die
  Halbfehlerstellungen sind nicht gleich schwer: *Text da, Fett fehlt* ist harmlos,
  *nichts da, meldet aber Erfolg* ist teuer.
* **Textarea-Ziele** (Wiki-Quelltextmodus) können kein Fett und bekommen den **bereinigten**
  Text – ein `**` dort wäre genau das, was der Kunde liest.
* Die Erfolgsmeldung sagt, **ob mit Fettschrift eingefügt wurde**. Damit ist jede Rückmeldung
  aus dem Betrieb ein Beleg statt einer Vermutung.

**Was das Feld nicht kann:** Listen und Kursiv bleiben Text (bewusst – nur Fett).
Ein `**` über einen Zeilenumbruch hinweg bleibt literal. Wer literal `**x**` tippt, sieht es
nach dem nächsten Wiederherstellen fett. Und die native Rückgängig-Kette leidet, sobald ein
Pfad den DOM von Hand anfasst – der Preis eines contenteditable ohne Editor-Bibliothek.

## Ohne erkanntes Ticket ist alles gesperrt

Findet die Erweiterung im offenen Tab keine Ticketnummer, steht im Kopf **„Kein Ticket
gefunden"** und **jeder** Knopf ist deaktiviert – ausgenommen sind nur die mit
`data-ohne-ticket` im Markup: **Anmelden**, **Abmelden** und die **Schließen-Knöpfe** der
Vorlagen-Box und der Einfüge-Rückfrage. Ohne diese vier entstünde ein
Einbahnstraßen-Zustand: von einem fremden Tab aus käme man nie hinein, nie hinaus, und ein
offener Dialog ließe sich nicht mehr wegräumen.

**Die Richtung ist fail-closed.** Gesperrt wird pauschal, ausgenommen wird einzeln – ein
künftig ergänzter Knopf ohne Attribut ist ohne Ticket höchstens einmal zu viel gesperrt.
Andersherum wäre er bedienbar, obwohl er nichts tun kann.

Drei Stellen, die zusammengehören (`popup.js`):

* `knoepfeAktualisieren()` setzt die Sperre und **hält sich während eines Laufs heraus** –
  sonst gäbe ein Tab-Wechsel mitten in der Auswertung die Knöpfe wieder frei.
* `sperre(false)` gibt **nicht blind alles frei**, sondern ruft `knoepfeAktualisieren()`.
  Sonst hätte das Ende eines Laufs die Ticket-Sperre aufgehoben.
* `vorlagenZeichnen()` zieht sie am Ende nach: die Zeilen-Knöpfe der Vorlagenliste
  entstehen erst dort und wären beim nächsten Neuzeichnen wieder bedienbar.

Die Prüfung `if (!_key)` **im Handler** bleibt daneben bestehen. Ein gesperrter Knopf ist
Oberfläche, keine Garantie: `_key` kann sich in der Seitenleiste zwischen Zeichnen und
Klick ändern, und `disabled` lässt sich aus den Entwicklerwerkzeugen entfernen.

## Nach jeder Aktualisierung: Neu laden (⟳)

Chrome liest die **Popup-Seite** bei jedem Öffnen frisch von der Platte, behält den
**Service-Worker** aber im Speicher. Wer die Dateien austauscht, ohne in
`chrome://extensions` auf **Neu laden** zu drücken, bekommt ein neues Fenster und einen
alten Hintergrund — und dann sieht jedes Symptom nach einem Programmierfehler aus.

Dagegen steht `STAND`: eine Zahl, die in `background.js` **und** `popup.js` identisch
gepflegt wird und mit dem Zustand mitgeht. Weicht sie ab, sagt das Fenster im Klartext, dass
neu zu laden ist. **Bei jeder Änderung an den Nachrichtenfällen hochzählen** — ein Test
vergleicht beide Zahlen. Eine Versionsnummer taugt dafür nicht: beide Seiten lesen dasselbe
Manifest von der Platte und melden dieselbe Version, auch wenn der Worker-Code alt ist.

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
