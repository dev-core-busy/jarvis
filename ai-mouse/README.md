# AI Mouse

Portable Windows-11-Anwendung: **rechte Maustaste halten und ziehen**, um einen
Bildschirmausschnitt zu wählen, loslassen, eine Frage aus dem Menü auswählen —
der Ausschnitt geht an **Jarvis** und die Antwort erscheint in einem Fenster.

Ein einfacher Rechtsklick verhält sich unverändert: der Hook hält den Druck
zurück und spielt ihn per `SendInput` echt nach, wenn der Zeiger sich nie bewegt
hat.

> **Herkunft.** Der Code stammt aus `dev-core-busy/ai-mouse` (Commit `0275f00`)
> und sprach dort direkt mit einem lokalen OpenAI-kompatiblen Server (Ollama,
> LM Studio). Am 2026-09-09 auf Jarvis umgestellt — siehe unten.

## Was sich gegenüber dem Ursprung geändert hat

| | vorher | jetzt |
|---|---|---|
| Gegenstelle | Ollama / LM Studio direkt | Jarvis (`/api/ai-mouse/analyze`) |
| Anmeldung | optionaler Bearer-Token in der Datei | beim ersten Start abgefragt, Sitzungstoken DPAPI-verschlüsselt in der Registry |
| Modell, System-Prompt, Temperatur | in `settings.json` | **entfallen** — das entscheidet der Server |
| Fragen | `prompts.json` neben der Exe | im Portal, pro Benutzer — die Anwendung holt sie beim Start |
| Einstellungen | zwei JSON-Dateien | Registry `HKCU\Software\AiMouse` — **keine Dateien mehr** |
| Sprache | fest englisch | DE/EN (`Localization/Texte.cs`) |
| Marke, Farbe | keine | beim Bau einkompiliert (`Configuration/Vorgaben.cs`) |

**Warum Modell und System-Prompt weg sind:** sie standen an jedem Arbeitsplatz
in einer Textdatei. Der System-Prompt ist aber die Schranke, die den Lauf
begrenzt — frei veränderbar wäre er keine. Beides liegt jetzt in
`backend/ai_mouse.py`.

**Warum es gar keine Dateien mehr gibt** (Vorgabe 2026-09-09): eine Anwendung,
die neben sich Dateien braucht, ist keine portable Anwendung. Sie kommt aus dem
Download-Ordner, aus einer Netzfreigabe oder von einem Stick — und dort fehlen
die Dateien oder sind schreibgeschützt. Die wenigen Werte pro Arbeitsplatz
stehen in der Registry (`HKCU`, kein Adminrecht nötig), die Hauswerte sind beim
Bau einkompiliert, und die Fragen liegen beim Server.

## Bauen

Das .NET-8-SDK genügt — **auch auf Linux**. Die EXE muss hier nicht laufen, nur
entstehen:

```bash
bash deploy/ai_mouse_build.sh            # legt vendor/ai-mouse/AiMouse.exe ab
bash deploy/ai_mouse_build.sh --pruefen  # nur nachsehen (Exit 0 = liegt bereit)
```

Gemessen am 2026-09-09: 25 Sekunden, 65,9 MB, `file` meldet
`PE32+ executable for MS Windows (GUI), x86-64`.

Unter Windows tut es auch `.\build.ps1`; das Ergebnis ist dasselbe.

> **Native AOT wird nicht benutzt.** WinForms unterstützt weder AOT noch
> Trimming — deshalb `PublishSingleFile` + `SelfContained`.

## Verteilen

Das **Paket aus dem Portal** nehmen: *AI Mouse* → *Paket herunterladen*. Darin
liegt die Anwendung mit den Hauswerten dieses Servers und eine kurze Anleitung.

⚠ **Deshalb sind Marke und Adresse einkompiliert und werden nicht abgerufen:**
die Anmeldemaske erscheint, *bevor* es eine Sitzung gibt — ein Abruf erreicht sie
nicht. Dieselbe Lehre wie beim Fenster der Jira-Erweiterung, nur eine Ebene
tiefer: dort trägt das ZIP ein `<meta>`, hier trägt die EXE eine Konstante.

Wer die EXE einzeln weitergibt, gibt sie mit denselben Hauswerten weiter — sie
stecken in der Datei. Nach einer Änderung an Marke oder Farbe baut der Server sie
neu, und das Paket ist dann das aktuelle.

## Wo die Bedienung sitzt

Windows 11 versteckt neue Infobereich-Symbole hinter dem `^` neben der Uhr.
Alles ist deshalb an **beiden** Stellen erreichbar:

- das **Gesten-Menü** (nach Rechtsklick + Ziehen) — Fragen, *Einstellungen…*,
  *Beenden*;
- das **Tray-Symbol** — *Einstellungen…*, *Abbrechen*.

*Konfiguration neu laden* gibt es nicht mehr: es gibt keine Dateien, die man neu
einlesen könnte. Die Hauswerte sind einkompiliert, die eigenen Werte gelten beim
Speichern sofort, und die Fragen holt die Anmeldung.

## Der erste Start

Beim **ersten** Start fragt die Anwendung nach **Serveradresse, Benutzer und
Kennwort**. Danach nie wieder: nach der gelungenen Anmeldung landen Adresse,
Benutzername, **Sitzungstoken** und die **Fragen** in der Registry unter
`HKCU\Software\AiMouse`. Jeder weitere Start ist stumm.

⚠ **Die Adresse wird abgefragt, obwohl sie einkompiliert ist.** Der
einkompilierte Wert ist die *Vorbelegung* — wer nichts ändert, bestätigt ihn mit
einem Klick. Ohne die Abfrage wäre eine Anwendung, die aus einem anderen Haus
kommt oder einen zweiten Server ansprechen soll, unbenutzbar, ohne dass die
Maske das sagt.

⚠ **Geschrieben wird erst NACH der gelungenen Anmeldung.** Eine Adresse, die
nicht funktioniert, darf sich nicht festsetzen — sonst trägt die Registry beim
nächsten Start einen Tippfehler, gilt als „eingerichtet", und die Maske fragt
nicht mehr: der Benutzer käme aus der Lage nicht mehr heraus.

## Was gespeichert wird

| Wert | wo | Anmerkung |
| --- | --- | --- |
| `Endpoint` | Registry | beim ersten Start abgefragt |
| `Benutzer` | Registry | **nie ein Kennwort** |
| `Sitzung` | Registry, **DPAPI-verschlüsselt** | das Sitzungstoken |
| `Fragen` | Registry | damit das Menü sofort steht |
| `Sprache`, `TimeoutSeconds`, `DragThreshold`, `CopyResultToClipboard` | Registry | im Einstellungsdialog |
| Marke, Akzentfarbe | **einkompiliert** | vom Server beim Bau gesetzt |

**Ein Kennwort steht nirgends** — auch nicht verschlüsselt. Gespeichert wird das
**Sitzungstoken**: es läuft ab, und ein Administrator kann es serverseitig
entwerten (Zwangsabmeldung). Ein Kennwort könnte beides nicht.

DPAPI (`CurrentUser`) bindet das Token an das Windows-Konto: ein anderer Benutzer
desselben Rechners kann es nicht lesen, eine kopierte Registry-Datei ist woanders
wertlos.

Läuft das Token ab, antwortet der Server mit 401 und die Anmeldemaske erscheint
erneut — dann ohne Adressfeld, denn eingerichtet ist die Anwendung ja.

### Die Fragen

Sie liegen **auf dem Server** und werden im Portal gepflegt: *AI Mouse* →
*Meine Fragen*. Die Anwendung holt sie **nach jeder Anmeldung** und merkt sie
sich; beim nächsten Start steht das Menü sofort, auch ohne Netz.

Ein Administrator kann Fragen als **gemeinsam** hinterlegen — die sieht jeder
Freigegebene und kann sie nicht ändern. Bis zur ersten Anmeldung zeigt das Menü
eine eingebaute Vorgabeliste; ohne sie wäre es beim allerersten Rahmen leer.

⚠ **Ein Adresswechsel räumt Sitzung und Fragen ab.** Beide gehören zum alten
Server bzw. zum alten Konto; sie stehen zu lassen hieße, sie gegen den neuen zu
schicken — ein 401, der wie ein Serverfehler aussieht.

⚠ **Warum nicht mehr `prompts.json`:** eine Datei neben der Exe muss verteilt und
gepflegt werden — auf jedem Arbeitsplatz einzeln. Serverseitig gepflegt gilt eine
Änderung sofort für alle, und der Benutzer braucht keinen Texteditor.

## Wie es funktioniert

| Stufe | Umsetzung |
| --- | --- |
| Geste | `SetWindowsHookEx(WH_MOUSE_LL)` über `WM_RBUTTONDOWN`/`WM_MOUSEMOVE`/`WM_RBUTTONUP` |
| Unterdrückung | Druck **und** Loslassen geben `1` zurück — keine Anwendung sieht einen halben Klick |
| Schwelle | jenseits von `DragThreshold` px gilt es als Geste, darunter wird der Klick nachgespielt |
| Nachspielen | `SendInput` mit `dwExtraInfo`-Marke, damit der Hook eigene Eingaben durchlässt |
| Schutz | über Fenstern mit höherer Integritätsstufe steht die Geste still, statt den Klick zu fressen |
| Überlagerung | rahmenloses `WS_EX_TOPMOST`-Fenster über den gesamten virtuellen Desktop |
| Aufnahme | `Graphics.CopyFromScreen` in physischen Pixeln (Per-Monitor-V2) |
| Transport | PNG als Base64-Data-URI an `/api/ai-mouse/analyze`, Bearer-Token |

## Bekannte Grenzen

- **Der Rechtsklick kommt beim Loslassen an.** Anwendungen, die auf
  `WM_RBUTTONDOWN` reagieren, antworten einen Moment später.
- **Ziehen mit der rechten Maustaste ist belegt** — genau diese Geste beansprucht
  die Anwendung.
- **Über Fenstern mit erhöhten Rechten** wirkt weder Geste noch Einspielung;
  `InjectionGuard` erkennt das und lässt alles durch.
- **60 ms Aufnahmeverzögerung**, damit die Abdunklung nicht im Bild landet.
- **Antworten kommen nicht gestreamt** — das Fenster füllt sich, wenn das Modell
  fertig ist.
- **Das Hausmodell muss Bilder verstehen.** Ein reines Textmodell antwortet auf
  einen Ausschnitt oft mit gar nichts; der Server sagt das dann im Klartext.
- **Nicht im echten Windows erprobt.** Der Umbau ist auf Linux übersetzt und der
  Server-Weg gemessen; ein Lauf auf einem Arbeitsplatz steht aus.
