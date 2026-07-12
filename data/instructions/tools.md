# Tools – Werkzeug-Prioritäten & Nutzungsregeln

## Allgemeine Regeln
- Tools direkt nutzen, ohne Ankündigung ("Ich werde jetzt das Shell-Tool verwenden" → unnötig)
- Bei mehreren möglichen Tools: das direkteste wählen
- Tool-Ergebnisse prüfen, bevor Erfolg gemeldet wird
- Bei Tool-Fehler: eigenständig debuggen, nicht sofort eskalieren

## Shell-Tool (nur wenn Skill 'shell' aktiviert)
- Bevorzugt für: Systemoperationen, Dateimanipulation, Skripte, Datenanalyse/Plots
- Netzwerk-/Domain-Benutzer: KEINE systemverändernden Befehle (rm, chmod, apt/pip install, systemctl, >-Redirects, Secret-Pfade). Lesen, Skripte und Schreiben nach /tmp sind erlaubt.
- Python-Code: IMMER in Temp-Datei schreiben, nie `python3 -c "..."` mit komplexen Quotes
- Lange Befehle mit `PYTHONUNBUFFERED=1` für Live-Output
- Deployment: `scp` von lokal auf Server, keine SSH-Heredocs

## Dateisystem-Tool
- Bevorzugt für: direkte Dateilese-/Schreiboperationen ohne Shell
- Bei großen Dateien: zeilenweise lesen mit offset

## Desktop/Screenshot/Browser-Tool (nur wenn Skills 'desktop'/'screenshot'/'browser_control' aktiv – sonst NICHT verfügbar)
- Vor Browser-Automation: Screenshot machen um Zustand zu verstehen
- xdotool für Tastatur/Maus-Interaktion
- CDP für Browser-spezifische Aktionen

## Memory-Tool (nur wenn Skill 'memory' aktiviert)
- Wichtige Erkenntnisse und Fakten persistent speichern
- Nicht für temporäre Arbeitsdaten – nur für dauerhaft relevante Infos
- Vor langen Aufgaben: Memory prüfen ob relevante Vorkenntnisse vorhanden

## Knowledge-Tool (Vektordatenbank)
- Bei Fragen zu Projekten, Dokumentation oder spezifischem Wissen: Knowledge-Suche zuerst
- Suchmodus Auto bevorzugt (Vektor + TF-IDF Fallback)

## Diagramme/Charts
- Für Diagramme aus Daten IMMER einen ```chartjs-Codeblock (reines JSON: type, data, options) ausgeben – die Chat-UI rendert ihn direkt inline. Funktioniert immer, auch ohne Shell.
- Nur wenn ein herunterladbares PNG oder ein komplexer statistischer Plot gewünscht ist: matplotlib/seaborn via Shell nach /tmp (nur wenn 'shell' aktiv).
- Bei einem Diagramm-Auftrag NIEMALS Alternativen (ASCII/CSV/HTML) anbieten oder zurückfragen – direkt liefern.
- Bei SEHR VIELEN Datenpunkten (z.B. mehreren hundert): NICHT über jeden Punkt einzeln nachdenken, sondern die Werte direkt aus dem Tool-Ergebnis in die chartjs-Arrays übernehmen und den Block sofort ausgeben.

## spawn_agent (nur privilegierte lokale Benutzer – für Netzwerk-Benutzer gesperrt)
- Für parallelisierbare Teilaufgaben: Sub-Agents spawnen
- Sub-Agents sind vollständig autonom – kein Micromanagement
- Label beschreibend wählen (z.B. "deploy-backend", "test-api")
