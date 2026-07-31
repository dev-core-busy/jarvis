# NOTICE — Fremdkomponenten und Lizenzhinweise

Jarvis steht unter der **Apache License 2.0** (siehe `LICENSE`).

Diese Datei enthält die Hinweise, die bei einer **Weitergabe** mitzuliefern sind:
getroffene Lizenzwahlen, geforderte Namensnennungen und die Quelltext-Angebote für
Copyleft-Komponenten. Sie ist bewusst kurz und nennt nur, was eine Pflicht auslöst.

**Die vollständige Inventur aller 330 Komponenten steht in
[`used_licenses.md`](used_licenses.md)** — dort mit Version, Lizenz und Herkunft je Paket.

---

## 1. Getroffene Lizenzwahl: FreeType (Windows-Client)

Der Windows-Client (`windows-app-go/`) bindet über Fyne das Paket
`github.com/golang/freetype` ein. Dieses ist **dual lizenziert** und verlangt vom
Verwender eine ausdrückliche Wahl:

> „Use of the Freetype-Go software is subject to your choice of exactly one of the
> following two licenses: The FreeType License … or the GNU General Public License
> (GPL), version 2 or later."

**Wir wählen die FreeType License (FTL).** Der von ihr geforderte Hinweis lautet:

> Portions of this software are copyright © The FreeType Project
> (<https://www.freetype.org>). All rights reserved.

Diese Wahl ist verbindlich und darf nicht stillschweigend geändert werden — die
Alternative wäre GPL-2.0-or-later und damit Copyleft auf der ausgelieferten Binärdatei.

## 2. Copyleft-Komponenten und Quelltext-Angebot

### GPL-3.0 — nur bei aktivierter WhatsApp-Anbindung

`@whiskeysockets/libsignal-node` (GPL-3.0) ist eine Laufzeit-Abhängigkeit von Baileys
und damit des Dienstes `whatsapp-bridge.service`.

**Abgrenzung:** Die Bridge ist ein **eigenständiger Node.js-Prozess**. Sie kommuniziert
mit dem Python-Backend ausschließlich über HTTP auf `localhost:3001` — keine Verlinkung,
kein gemeinsamer Adressraum, kein gemeinsamer Prozess. Das Backend bildet daher nach
gängiger Auslegung kein abgeleitetes Werk.

**Pflicht bei Weitergabe:** Wer Jarvis **als Ganzes** weitergibt (Appliance, VM-Abbild,
Installationspaket) und die Bridge mitliefert, verteilt damit GPL-3.0-Software und
schuldet deren Quelltext samt Installationsinformationen. Der unveränderte Quelltext ist
zu beziehen über <https://github.com/WhiskeySockets/Baileys>; auf Anfrage stellen wir ihn
in der ausgelieferten Fassung bereit.

*Ist der WhatsApp-Skill nicht aktiviert, ist die Bridge nicht installiert und dieser
Abschnitt gegenstandslos.*

### LGPL — dynamisch eingebunden, unverändert

`edge-tts`, `ldap3`, `python-telegram-bot` (alle LGPL-3.0) sowie serverseitig
`websockify` (LGPL-3) und `ffmpeg` (LGPL-2.1+) werden **unverändert** und als
austauschbare Bibliotheken bzw. eigenständige Prozesse verwendet. Die Austauschbarkeit
bleibt gewahrt: Alle sind über die üblichen Paketwege durch eine eigene Fassung
ersetzbar. Quelltexte sind bei den jeweiligen Projekten zu beziehen.

### MPL-2.0 — dateiweises Copyleft, unverändert

`certifi`, `orjson`, `tqdm` (Python) sowie serverseitig noVNC und LibreOffice. Keine der
Dateien wurde geändert; damit entstehen keine weitergehenden Pflichten.

## 3. Namensnennungen (Frontend)

| Komponente | Lizenz | Hinweis |
|---|---|---|
| jQuery 3.7.1 | MIT | © OpenJS Foundation and other contributors |
| Chart.js 4.4.9 | MIT | © Chart.js Contributors |
| clippy.js | MIT | © Smore Inc. |
| noVNC 1.6.0 | MPL-2.0 | serverseitig ausgeliefert |

### ⚠ Die Avatar-Figur ist NICHT mitlizenziert

Die MIT-Lizenz von clippy.js deckt **deren Quelltext**. Die Bilddaten und Klänge unter
`frontend/vendor/clippy/agents/Clippy/` zeigen den **Office-Assistenten von Microsoft**
und sind davon **nicht** erfasst. Für den internen Betrieb ist das regelmäßig
unproblematisch; für eine öffentliche Vermarktung ist es zu klären oder durch eine eigene
Figur zu ersetzen (`skills/avatar/AVATAR-DESIGN.md` beschreibt den Weg).

## 4. Nachgetragene Lizenzangaben

Zwei Pakete deklarieren ihre Lizenz nicht in den Metadaten. Sie sind hier von Hand
festgehalten, damit eine automatische Inventur sie nicht als „ungeklärt" führt:

| Paket | Tatsächliche Lizenz | Warum sie fehlt |
|---|---|---|
| `chroma-hnswlib` 0.7.6 | Apache-2.0 | Das Projekt ist Apache-2.0, das Rad deklariert es nicht. |
| `github.com/jsummers/gobmp` | MIT | Die angeheftete Fassung von 2015 liefert keine `LICENSE`-Datei mit; spätere Fassungen enthalten `COPYING.txt`. |

## 5. Proprietäre Komponenten

`hdbcli` (SAP HANA Client) unterliegt den Lizenzbedingungen der SAP SE und setzt eine
gültige SAP-Lizenz voraus. Das Paket wird **nur** bei aktiviertem `sap`-Skill installiert
und ist nicht Bestandteil der Standardauslieferung. Gleiches gilt für `pyrfc`, das
zusätzlich das nur über ein SAP-Kundenkonto beziehbare NetWeaver RFC SDK benötigt.

---

*Pflege: Bei Änderungen an den Abhängigkeiten `used_licenses.md` mit
`tests/tools/lizenzen_erheben.py` neu erzeugen und diese Datei prüfen — sie ist
Handarbeit und wird nicht generiert.*
