---
description: Finde, analysiere und importiere einen OpenClaw-Skill aus dem ClawHub (lokal und sicher).
---

# Importiere einen neuen OpenClaw Skill (Safe & Local)

Dieser Workflow definiert den Prozess, wie ein gewünschter Skill in natürlicher Sprache angefragt wird und sicher vom Agenten bereitgestellt wird – ohne potenziell gefährliche automatisierte nachgelagerte Downloads auszuführen.

## 1. Skill-Entdeckung und Angebot
- **Nutzer:** Beschreibt den gewünschten Skill (z. B. "Ich suche einen Skill für Gmail").
- **Agent:** Durchsuche das Web und den offiziellen **ClawHub (OpenClaw Marketplace)** nach passenden Skills.
- **Agent:** Präsentiere dem Nutzer die gefundenen Optionen (die größten und beliebtesten) und frage explizit: *"Welche dieser Optionen soll ich herunterladen und für dich analysieren?"*.

## 2. Download und Sicherheitsanalyse
- **Agent:** Lade die Repo-Dateien (z. B. `SKILL.md`, `_meta.json`) des ausgewählten Skills herunter.
- **Agent:** Analysiere den Code auf Sicherheitsrisiken. Achte besonders auf unregulierte Installationsbefehle, z. B. per Homebrew (`install:[{"id":"brew"...]`), npm, bash-Pipes oder curl-Downloads.
- **Agent:** Erstelle einen detaillierten `analyse_bericht.md` im temporären Arbeitsbereich und präsentiere dem Nutzer die Ergebnisse.

## 3. Entschärfen und Lokalisieren
- **Agent:** Sobald der Nutzer zustimmt, wandle den Skill in eine rein **lokale, geschlossene Umgebung** um.
- **Agent:** Lege das finale Verzeichnis für den Skill **immer** mit dem Präfix `openclaw_` an (Bsp: `/home/bender/ai_jarvis/skills_from_openclaw/openclaw_<skill_name>/`).
- **Agent:** Falls der Skill Binärdateien erfordert (wie z.B. `gogcli`), lade diese manuell und verifiziert aus deren Originalquelle (z. B. GitHub Release) für die Systemarchitektur (`linux_amd64`) in das neu angelegte Skill-Verzeichnis herunter.
- **Agent:** Mache die Binärdatei ausführbar (`chmod +x`).

## 4. Konfiguration & Interaktion (Eingabemaske)
- **Agent:** Prüfe, ob der Skill für sein Setup Konfigurationsdateien (wie z. B. `client_secret.json`) oder Umgebungsvariablen (wie `API_KEY`) benötigt.
- **Agent:** Wenn die Anzahl der benötigten Parameter **10 oder weniger** beträgt, darf der Ziel-Agent nicht einfach den Pfad zu einer Datei verlangen. Stattdessen implementierst du eine **interaktive Eingabemaske** (grafisch oder über strukturierte Chat-Rückfragen).
- **Agent:** Die Ziel-KI muss dem Nutzer explizit mitteilen, dass der Skill konfiguriert werden muss, und die Parameter interaktiv erfragen.
- **Agent:** Speichere diese Konfigurationen dann lokal und sicher für den Skill ab.

## 5. Agent-Instruktionen erstellen
- **Agent:** Erstelle eine `agent_instructions.md` im Skill-Verzeichnis. Diese Datei sagt dem aufrufenden Agenten genau, wie er das lokale Tool nutzen muss (z. B. via `./gog` statt `gog`) und wie er die zuvor erstellte interaktive Konfiguration aufzurufen hat.
- **Agent:** Entferne alle externen Installationsanweisungen aus den Skill-Beschreibungen. Es dürfen keine nachgelagerten Downloads durch die OpenClaw-Engine mehr stattfinden.

## 6. Aufräumen (Cleanup)
- **Agent:** Entferne die nicht mehr benötigten Originaldateien des Skills (wie die ursprüngliche `SKILL.md`, `_meta.json` oder ZIP/TAR-Archive).
- **Agent:** Im finalen Verzeichnis dürfen nur noch die ausführbare Binaries, die `agent_instructions.md` und der `analyse_bericht.md` übrig bleiben.

## Abschluss
- Informiere den Nutzer, dass der Skill sicher konvertiert, analysiert und jetzt als vollständig lokales Werkzeug für den AI-Agenten bereitsteht.
