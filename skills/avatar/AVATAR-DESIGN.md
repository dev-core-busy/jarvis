# Eigenen Avatar gestalten und einbinden

Diese Anleitung beschreibt vollständig, wie die Figur des Avatar-Assistenten
gegen ein eigenes Design getauscht wird – vom Bild bis zum fertigen Eintrag im
Auswahlfeld *Einstellungen → Avatar → Figur/Grafik*. Alle Angaben sind gegen den
laufenden DEV-Server geprüft (Stand 2026-07-30).

---

## 1. Drei Wege – welcher passt?

| Weg | Aufwand | Ergebnis | Wann |
|---|---|---|---|
| **A – Firmenlogo** (`graphic = branding`) | Minuten | Logo schwebt und pulsiert beim Sprechen | Schnell, ohne Grafikarbeit. Kein Mimik/Gestik. |
| **B – SVG-Platzhalter anpassen** | ~1 h, Code-Änderung | Vektor-Roboter mit Augen und Mund-Animation | Eigene Hausfarben, aber keine echte Figur. |
| **C – eigener Sprite-Satz** | halber Tag | Vollwertige Figur mit Animationen (wie Clippy) | Der eigentliche Weg für ein eigenes Maskottchen. |

Weg C ist **drop-in**: Ordner ablegen, fertig. Kein Code, kein Dienst-Neustart –
`backend/avatar.py::sprite_agents()` liest den Ordner bei jedem Aufruf neu.

---

## 2. Weg A – Firmenlogo als Figur

1. *Einstellungen → Skills → Branding* aktivieren und Logo hochladen
   (Hell-/Dunkel-Variante möglich).
2. *Einstellungen → Avatar → Figur/Grafik* → **branding**.

Das Logo wird auf 84×84 px eingepasst, schwebt dauerhaft leicht auf und ab und
pulsiert während der Sprachausgabe (`.jav-logo.talking`, `avatar.css`). Fehlt ein
Logo, fällt die Anzeige automatisch auf Clippy zurück – die Ecke bleibt nie leer.

---

## 3. Weg B – den SVG-Platzhalter umgestalten

Der Platzhalter steckt als Inline-SVG in `frontend/js/avatar.js::placeholder()`.
Er nutzt ausschließlich Theme-Variablen (`var(--accent)`, `var(--bg-secondary)`),
übernimmt also automatisch die Branding-Farben.

Zwei Klassen sind funktional und müssen erhalten bleiben:

* `.jav-mouth` – wird während der Sprachausgabe animiert (`scaleY`),
* `.jav-antenna` – blinkt dabei mit.

Die äußere Klasse `jav-ph` liefert das Schweben. Nach der Änderung den
Cache-Buster `avatar.js?v=N` in **allen neun** HTML-Seiten hochzählen.

> Farben immer über CSS-Variablen, nie fest verdrahtet – sonst bricht der
> Hell-Modus und das Branding wirkt nicht.

---

## 4. Weg C – eigener Sprite-Satz (empfohlen)

### 4.1 Was ein „Agent" ist

Ein Agent ist ein Ordner unter `frontend/vendor/clippy/agents/<Name>/`:

```
frontend/vendor/clippy/agents/Nexerius/
  agent.js         Pflicht – Animationsdaten
  map.png          Pflicht – Spritesheet mit allen Einzelbildern
  sounds-mp3.js    Pflicht – auch wenn es keine Töne gibt (s. 4.6)
  sounds-ogg.js    Pflicht – dito
```

**Der Ordnername ist der Agentenname** und muss zeichengenau mit dem Namen in
`agent.js` und in den beiden Sound-Dateien übereinstimmen. Er erscheint
unverändert im Auswahlfeld.

Zum Vergleich der mitgelieferte Clippy: Rahmen 124×93 px, `map.png`
3348×3162 px, 43 Animationen, 1,3 MB.

### 4.2 Die Bilder

| Anforderung | Wert |
|---|---|
| Format | PNG mit **Alphakanal** (transparenter Hintergrund) |
| Größe je Frame | alle Frames **exakt gleich groß**; sinnvoll 100–140 px breit, 80–110 px hoch |
| Ausrichtung | Figur immer an derselben Stelle im Rahmen (Standbein unten mittig) – sonst „springt" sie zwischen den Frames |
| Beleuchtung/Stil | über alle Frames identisch; kein Bodenschatten, keine Hintergrundfläche |
| Frames je Animation | 4–12 reichen; bei 100 ms je Frame ergibt das 0,4–1,2 s |

Der Anzeigebereich im Widget ist 124×100 px (`#jav-figure`). Deutlich größere
Rahmen werden nicht beschnitten, sprengen aber das Layout.

### 4.3 Welche Animationen sinnvoll sind

Jarvis spielt gezielt nur diese Namen ab (`avatar.js::gesture()`), jeweils der
erste vorhandene aus der Liste:

| Anlass | Namen (in dieser Reihenfolge geprüft) |
|---|---|
| Frage läuft | `Thinking`, `Processing`, `GetAttention` |
| Antwort da | `Explain`, `Congratulate`, `GestureRight`, `Wave` |
| Ruhezustand | irgendeine Animation, deren Name mit **`Idle`** beginnt |

Ein brauchbarer Minimalsatz sind also vier Animationen: `Idle1_1`, `Thinking`,
`Explain`, `Greeting`. Alles darüber ist Kür; unbekannte Namen schaden nicht.

### 4.4 Bauen mit dem mitgelieferten Skript

```bash
# Quellordner: ein Unterordner je Animation, darin die Frames in Reihenfolge
meine_figur/
  Idle1_1/    001.png 002.png 003.png 004.png
  Thinking/   001.png ...
  Explain/    001.png ...
  Greeting/   001.png ...

python3 skills/avatar/tools/build_agent.py meine_figur Nexerius
```

Das Skript (benötigt `Pillow`) legt das Spritesheet an, schreibt `agent.js` samt
Koordinaten, erzeugt die beiden Stummdateien und meldet am Ende den
scp-Befehl. Es fasst identische Frames automatisch zusammen, passt abweichend
große Bilder proportional ein und ergänzt eine fehlende `Idle`-Animation
selbstständig (siehe 4.6, Regel 2).

Sonderfall **Standbild**: ein flacher Ordner mit einem einzigen PNG genügt –
daraus wird eine Ein-Frame-Animation `Idle1_1`.

Optionen: `--framesize 124x93` (Rahmen erzwingen), `--duration 120` (ms je
Frame), `--force` (Zielordner überschreiben), `--out <pfad>`.

### 4.5 Einbinden

```bash
scp -r frontend/vendor/clippy/agents/Nexerius \
    root@<server>:/opt/jarvis/frontend/vendor/clippy/agents/
```

Danach *Einstellungen → Skills → Avatar-Assistent → Zahnrad → Figur/Grafik* –
der neue Name steht in der Liste. **Kein Dienst-Neustart nötig.** Im Browser
ggf. einmal hart neu laden (das Spritesheet wird gecacht).

### 4.6 Die fünf harten Regeln

Diese Punkte sind kein Stil, sondern Funktionsbedingungen. Verstöße führen zu
einer leeren Ecke oder zum stillen Rückfall auf Clippy – ohne Fehlermeldung.

1. **Name = Ordnername = Bezeichner in `agent.js` und in beiden Sound-Dateien.**
   Weicht einer ab, wartet clippy.js endlos auf ein Ereignis, das nie kommt.
2. **Mindestens eine Animation, deren Name mit `Idle` beginnt.** Nach dem
   Einblenden sucht clippy.js von sich aus eine Leerlauf-Animation. Findet es
   keine, wird überhaupt nichts gezeichnet – die Figur bleibt unsichtbar,
   obwohl alle Dateien korrekt geladen sind.
3. **`sounds-mp3.js` und `sounds-ogg.js` müssen existieren**, auch ohne Töne.
   Inhalt genau eine Zeile:
   ```js
   clippy.soundsReady('Nexerius', {});
   ```
   *Nachgewiesen:* Ohne diese Dateien liefert der Server 404, clippy.js ruft
   **weder** den Erfolgs- **noch** den Fehler-Rückruf auf. Das Widget fällt erst
   nach seiner eigenen 6-Sekunden-Grenze auf Clippy zurück (`avatar.js::
   loadSprite`). Im Test war nach 9 s tatsächlich Clippy zu sehen.
4. **Alle Frames gleich groß, `framesize` stimmt.** Die Koordinaten im
   `agent.js` sind die linke obere Ecke des Ausschnitts im Spritesheet; eine
   falsche Rahmengröße verschiebt jedes Bild.
5. **Transparenter Hintergrund.** Ein weißer Kasten um die Figur fällt im
   Dunkel-Modus sofort auf.

### 4.7 `agent.js` von Hand (ohne Skript)

```js
clippy.ready('Nexerius', {
  "overlayCount": 1,          // Ebenen je Frame – 1 genügt fast immer
  "sounds": [],               // Ton-Kennungen; leer = keine Töne
  "framesize": [124, 93],     // Breite, Höhe eines Frames in map.png
  "animations": {
    "Idle1_1": { "frames": [
      { "duration": 100, "images": [[0, 0]] },      // x, y in map.png
      { "duration": 100, "images": [[124, 0]] },
      { "duration": 800, "images": [[248, 0]] }
    ]},
    "Thinking": { "frames": [
      { "duration": 120, "images": [[0, 93]] },
      { "duration": 120, "images": [[124, 93]] }
    ]}
  }
});
```

Optionale Felder je Frame:

* `"sound": "3"` – spielt den Ton mit dieser Kennung (muss in `sounds` stehen
  und in den Sound-Dateien als Base64-Audio hinterlegt sein),
* `"exitBranch": 12` – Sprungziel, wenn die Animation vorzeitig beendet wird,
* `"branching": {"branches": [{"frameIndex": 21, "weight": 100}]}` – Zufalls-
  verzweigung (Summe der Gewichte ≤ 100), erzeugt lebendigere Leerläufe.

Das ganze Objekt ist reines JSON hinter `clippy.ready('<Name>', …);` – eine
einzige Anweisung, keine weiteren Zeilen.

---

## 5. LLM-Prompts

Die folgenden Vorlagen sind zum Kopieren gedacht. Die Platzhalter in
`<spitzen Klammern>` ersetzen.

### 5.1 Bildmodell – Figur entwerfen (Referenzbild)

```text
Entwirf eine freundliche Maskottchen-Figur als Software-Assistent für eine
Unternehmens-Weboberfläche.

Figur:      <z.B. ein abgerundeter Roboter mit einem Auge und Antenne>
Farben:     Hauptfarbe <#6366F1>, Sekundärfarbe <#232833>, sonst neutral
Stil:       flache Vektor-Illustration, klare Konturen, keine Verläufe,
            keine Texturen, keine Textur-Schatten
Ansicht:    frontal, leicht nach rechts geneigt, Ganzkörper
Hintergrund: vollständig transparent, KEIN Boden, KEIN Schlagschatten
Format:     quadratisch, Figur zentriert mit etwas Rand
Ausdruck:   neutral-freundlich (Ruhepose)

Wichtig: Diese Figur wird später in mehreren Posen wiederverwendet. Halte das
Design einfach und einprägsam – wenige Bauteile, klare Silhouette.
```

### 5.2 Bildmodell – Posen und Frames

Bildmodelle liefern **kein** exaktes Raster. Praxiserprobter Ablauf: das
Referenzbild aus 5.1 als Vorlage nehmen und je Pose ein Einzelbild erzeugen
(Bildbearbeitung/„Variation" auf Basis des Referenzbildes), dann mit
`build_agent.py` zusammenbauen.

```text
Nimm die beigefügte Figur als verbindliche Vorlage. Erzeuge dieselbe Figur in
folgender Pose – identischer Stil, identische Farben, identische Größe und
identische Position im Bild, nur die genannten Teile verändert:

Pose: <"beide Arme leicht angehoben, Mund offen – spricht/erklärt">

Unverändert bleiben müssen: Körperform, Farbwerte, Strichstärke, Blickrichtung,
Abstand zum Bildrand, transparenter Hintergrund.
Kein Text, keine Sprechblase, kein Rahmen, kein Schatten.
```

Posen für den Minimalsatz:

| Animation | Posen (je 3–6 Frames) |
|---|---|
| `Idle1_1` | Ruhepose, leichtes Atmen/Blinzeln |
| `Thinking` | Blick nach oben, Hand am Kinn, Punkte über dem Kopf |
| `Explain` | Arme öffnend, Mund offen |
| `Greeting` | Winken in 3 Stufen |

### 5.3 Code-LLM – `agent.js` aus einem vorhandenen Spritesheet

Nur nötig, wenn das Spritesheet **nicht** mit `build_agent.py` entstanden ist
(z.B. ein fertiges Sheet aus einem Grafikprogramm).

```text
Schreibe die Datei agent.js für die Bibliothek clippy.js.

Gegeben ist ein Spritesheet map.png:
  Gesamtgröße:   <3348>x<3162> px
  Rahmengröße:   <124>x<93> px (gleichmäßiges Raster, links oben beginnend,
                 zeilenweise gefüllt)
  Agentenname:   <Nexerius>
  Belegung:      Frame 0–<5>  = Ruhepose (Idle1_1)
                 Frame <6>–<11> = Nachdenken (Thinking)
                 Frame <12>–<17> = Erklären (Explain)
                 Frame <18>–<23> = Winken (Greeting)

Regeln:
- Die Datei besteht aus GENAU einer Anweisung:
  clippy.ready('<Name>', { ... });
- Das Objekt hat die Schlüssel overlayCount (1), sounds ([]), framesize
  ([Breite, Höhe]) und animations.
- Jede Animation ist { "frames": [ { "duration": <ms>, "images": [[x, y]] }, … ] }.
- x/y sind die Pixel-Koordinaten der LINKEN OBEREN Ecke des Frames im
  Spritesheet, berechnet aus dem Rasterindex:
  x = (index % spalten) * rahmenbreite, y = (index / spalten | 0) * rahmenhöhe.
  spalten = gesamtbreite / rahmenbreite.
- duration: 100 ms je Frame, beim letzten Frame einer Animation 800 ms.
- Mindestens eine Animation muss mit "Idle" beginnen.
- Kein zusätzlicher Code, keine Kommentare, keine Modul-Exporte.

Gib danach die Rechnung für die ersten drei Koordinaten jeder Animation an,
damit ich sie nachprüfen kann.
```

### 5.4 Code-LLM – Frames als SVG erzeugen (Vektor-Weg)

Für ein technisch-neutrales Design ohne Bildmodell. Ergebnis sind SVG-Dateien,
die anschließend zu PNG gerendert werden.

```text
Erzeuge <5> SVG-Dateien, die zusammen eine Animation "<Winken>" einer
Assistenten-Figur ergeben.

Vorgaben für JEDE Datei:
- viewBox="0 0 124 93", width/height ebenfalls 124/93
- transparenter Hintergrund (kein <rect> über die volle Fläche)
- Figur: <Beschreibung wie in 5.1>
- Farben ausschließlich als feste Hex-Werte: Akzent <#6366F1>, Fläche <#232833>
- identische Geometrie in allen Dateien; NUR <der rechte Arm> ändert sich
- keine <style>-Blöcke, keine CSS-Animationen, keine Filter, keine Schriften
- Ausgabe je Datei in einem eigenen Codeblock mit Dateinamen 001.svg … <005>.svg
```

Rendern und bauen:

```bash
# ImageMagick liegt auf dem Entwicklungsrechner bereits vor.
# PNG32: erzwingt echtes RGBA – ohne das entsteht ein Palettenbild,
# dessen Transparenz je nach Browser als schwarze Fläche erscheint.
for f in Greeting/*.svg; do
    convert -background none -density 200 "$f" -resize 124x93 "PNG32:${f%.svg}.png"
done
python3 skills/avatar/tools/build_agent.py meine_figur Nexerius
```

---

## 6. Prüfliste vor dem Ausrollen

- [ ] Ordnername, Name in `agent.js`, Name in beiden Sound-Dateien identisch
- [ ] mindestens eine `Idle*`-Animation vorhanden
- [ ] `sounds-mp3.js` **und** `sounds-ogg.js` vorhanden
- [ ] alle Frames gleich groß, `framesize` passt zum Raster
- [ ] transparenter Hintergrund, im Hell- **und** Dunkel-Modus geprüft
- [ ] `agent.js` ist gültiges JSON hinter `clippy.ready(…)` (Browser-Konsole
      zeigt sonst einen Syntaxfehler)
- [ ] im Browser: Figur erscheint, Klick öffnet das Panel, während einer Frage
      wechselt die Animation

## 7. Fehlerbilder

| Symptom | Ursache | Abhilfe |
|---|---|---|
| Nach ~6 s erscheint **Clippy** statt der eigenen Figur | Ladefehler oder Hänger – meist fehlende/falsch benannte Sound-Datei, 404 auf `map.png`/`agent.js` | Regel 1 und 3; Netzwerk-Tab des Browsers auf 404 prüfen |
| Ecke bleibt **leer**, keine Fehlermeldung | keine `Idle*`-Animation | Regel 2 |
| Figur erscheint, aber **falscher Bildausschnitt** | `framesize` oder Koordinaten stimmen nicht | Regel 4; Rasterrechnung nachprüfen |
| Figur **springt** zwischen den Frames | Motiv liegt in den Frames unterschiedlich | Frames in der Bildbearbeitung an einer gemeinsamen Grundlinie ausrichten |
| Weißer Kasten hinter der Figur | PNG ohne Alphakanal | Regel 5 |
| Alte Figur bleibt sichtbar | Browser-Cache (`map.png`) | hart neu laden; bei Bedarf Dateinamen des Agenten ändern |
| Auswahlfeld zeigt den Namen nicht | Ordner unvollständig (`agent.js` **und** `map.png` nötig) oder auf dem falschen Server | `ls /opt/jarvis/frontend/vendor/clippy/agents/` |

## 8. Rechtliches

`clippy.js`, die zugehörige CSS-Datei und jQuery stehen unter MIT und liegen
selbst gehostet unter `frontend/vendor/clippy/`. Die **Grafiken und Töne der
Microsoft-Agenten (Clippy und Verwandte) sind Eigentum von Microsoft** und hier
nur zu Demonstrationszwecken enthalten. Für den produktiven Einsatz unter
eigenem Namen gehört eine eigene Figur nach Weg C hierher.
