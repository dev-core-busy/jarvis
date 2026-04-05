# Tools – Werkzeug-Prioritäten & Nutzungsregeln

## Allgemeine Regeln
- Tools direkt nutzen, ohne Ankündigung ("Ich werde jetzt das Shell-Tool verwenden" → unnötig)
- Bei mehreren möglichen Tools: das direkteste wählen
- Tool-Ergebnisse prüfen, bevor Erfolg gemeldet wird
- Bei Tool-Fehler: eigenständig debuggen, nicht sofort eskalieren

## Shell-Tool
- Bevorzugt für: Systemoperationen, Dateimanipulation, Paketinstallation, Skripte
- Python-Code: IMMER in Temp-Datei schreiben, nie `python3 -c "..."` mit komplexen Quotes
- Lange Befehle mit `PYTHONUNBUFFERED=1` für Live-Output
- Deployment: `scp` von lokal auf Server, keine SSH-Heredocs

## Dateisystem-Tool
- Bevorzugt für: direkte Dateilese-/Schreiboperationen ohne Shell
- Bei großen Dateien: zeilenweise lesen mit offset

## Desktop/Screenshot-Tool
- Vor Browser-Automation: Screenshot machen um Zustand zu verstehen
- xdotool für Tastatur/Maus-Interaktion
- CDP für Browser-spezifische Aktionen

## Memory-Tool
- Wichtige Erkenntnisse und Fakten persistent speichern
- Nicht für temporäre Arbeitsdaten – nur für dauerhaft relevante Infos
- Vor langen Aufgaben: Memory prüfen ob relevante Vorkenntnisse vorhanden

## Knowledge-Tool (Vektordatenbank)
- Bei Fragen zu Projekten, Dokumentation oder spezifischem Wissen: Knowledge-Suche zuerst
- Suchmodus Auto bevorzugt (Vektor + TF-IDF Fallback)

## spawn_agent
- Für parallelisierbare Teilaufgaben: Sub-Agents spawnen
- Sub-Agents sind vollständig autonom – kein Micromanagement
- Label beschreibend wählen (z.B. "deploy-backend", "test-api")
