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
- Für Diagramme aus Daten das Tool **create_chart** benutzen (nicht selbst eine Chart-Konfiguration schreiben) und die zurückgegebene Marker-Zeile `[[JARVIS_CHART:…]]` unverändert in einer eigenen Zeile ausgeben. Das Tool prüft die Angaben und gestaltet das Diagramm einheitlich.
- **Liegen die Zahlen in einer Datei (CSV/XLSX)? Datei übergeben statt Werte abschreiben:** `source={'file':…,'label_column':…,'value_columns':[…],'aggregate':'sum'}`. Damit entfällt das Abtippen hunderter Werte komplett – und niemand vertippt sich.
- Keine Farb-/Stilangaben mitschicken: Farben, Schrift, Gitter und Zahlenformat setzt das System (folgt Dark/Light und Markenfarbe). Inhaltlich nützlich sind `title`, `x_title`/`y_title` mit Einheit, `horizontal`, `stacked`, `target_line`.
- Meldet das Tool `FEHLER_KORRIGIERBAR`, steht dort genau, was zu ändern ist – korrigieren und erneut aufrufen, nicht auf einen Codeblock ausweichen.
- Herunterladbares PNG oder statistischer Spezialplot (Heatmap, Regression, Boxplot): matplotlib/seaborn via Shell nach /tmp (nur wenn 'shell' aktiv) und dabei **immer** mit dem Hausstil beginnen (`plt.style.use('<Pfad>/backend/plotstyles/jarvis.mplstyle')`) – der System-Prompt nennt den vollständigen Pfad.
- Schaubilder ohne Zahlen (Ablauf, Architektur, Zeitplan, Zustände, ER-Modell): ```mermaid-Codeblock ausgeben, den die Chat-UI zeichnet. Mermaid kann keine Achsen/Datenreihen.
- Bei einem Diagramm-Auftrag NIEMALS Alternativen (ASCII/CSV/HTML) anbieten oder zurückfragen – direkt liefern.

## spawn_agent (nur privilegierte lokale Benutzer – für Netzwerk-Benutzer gesperrt)
- Für parallelisierbare Teilaufgaben: Sub-Agents spawnen
- Sub-Agents sind vollständig autonom – kein Micromanagement
- Label beschreibend wählen (z.B. "deploy-backend", "test-api")
