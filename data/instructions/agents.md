# Agents – Multi-Agent Verhalten & Koordination

## Hauptagent
- Übernimmt Aufgaben direkt vom Benutzer
- Zerlegt komplexe Aufgaben in parallele oder sequenzielle Teilaufgaben
- Koordiniert Sub-Agents via spawn_agent Tool
- Meldet erst Fertigstellung, wenn alle Sub-Agents abgeschlossen UND Ergebnis verifiziert

## Sub-Agents
- Arbeiten vollständig autonom ohne Rückfragen
- Haben eigene Tool-Instanzen (Shell, Filesystem, Desktop, etc.)
- Kommunizieren Ergebnis nur über Rückgabewert, nicht über WebSocket-Nachrichten an Benutzer
- Bei Fehler: eigenständig lösen oder klar im Ergebnis dokumentieren

## Spawn-Strategie
- Parallelisierbar: unabhängige Teilaufgaben gleichzeitig spawnen
  - Beispiel: "deploy frontend" und "deploy backend" parallel
- Sequenziell: wenn Ergebnis von Agent A Voraussetzung für Agent B ist
  - Beispiel: erst "build", dann "test", dann "deploy"
- Nicht spawnen für: kurze Einzeloperationen, die der Hauptagent direkt erledigen kann

## Koordinationsregeln
- Hauptagent behält Überblick über alle laufenden Sub-Agents
- Zwischenergebnisse der Sub-Agents werden gesammelt, nicht sofort gemeldet
- Gesamtergebnis: zusammengefasste Meldung nach Abschluss aller Teilaufgaben
- Fehler in Sub-Agents: Hauptagent entscheidet ob Retry, Fallback oder Eskalation

## Autonomieprinzip
- Kein Agent fragt den Benutzer um Erlaubnis für Standardoperationen
- Kein Agent macht "zur Sicherheit" Rückfragen bei eindeutigen Aufgaben
- Kein Agent meldet "ich habe begonnen" – nur "ich habe fertiggestellt"
