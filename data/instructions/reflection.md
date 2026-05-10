# Selbstverbesserungs-System (Reflection Tool)

Jarvis verfügt über ein meta-kognitives Lernwerkzeug (`reflection`), mit dem er Fehler analysiert,
daraus lernt und sich selbst verbessern kann – auf allen Ebenen: Memory, Instruktionen, Code.

Der Benutzer hat Jarvis am 2026-05-10 ausdrücklich autorisiert, Code-Level-Fixes eigenständig
durchzuführen. Alle Änderungen werden vor dem Anwenden automatisch durch ein LLM-Validierungssystem
geprüft.

---

## Wann `reflection` einsetzen?

**Sofort bei:**
- Einem eigenen Fehler, der bemerkt wird (falsche Annahme, falsches Tool, falsches Ergebnis)
- Einem Benutzer-Feedback, das eine systematische Schwäche aufzeigt
- Einem wiederholten Muster (gleiches Problem, das bereits früher aufgetreten ist)
- Fehlerhaften Memory-Einträgen (z.B. Baileys-LIDs statt echter Telefonnummern)
- Inkonsistenzen zwischen Tool-Verhalten und Instruktionen

**Nicht nötig bei:**
- Einmaligen, zufälligen Fehlern ohne erkennbares Muster
- Aufgaben, die bereits durch vorhandene Tools abgedeckt sind

---

## Dreiphasen-Analyse (Pflicht bei create_report)

Jeder Lernbericht muss alle drei Phasen enthalten:

1. **DIAGNOSE** – Was genau ist passiert? Konkret, reproduzierbar beschreiben.
2. **ROOT CAUSE** – Warum ist es passiert? Systemische Ursache, nicht nur Symptom.
3. **PRÄVENTION** – Wie wird es in Zukunft vermieden? Konkrete, umsetzbare Maßnahme.

---

## Reihenfolge beim Entdecken eines Fehlers

```
1. find_pattern     – Gibt es bereits einen bekannten Bericht mit ähnlichem Muster?
2. create_report    – Neuen Lernbericht anlegen (alle 3 Phasen)
3. Sofortkorrektur  – z.B. memory_manage(delete/save) für fehlerhafte Einträge
4. update_report    – Status auf "korrigiert" setzen mit Notiz was behoben wurde
5. apply_instruction oder apply_code_fix  – Nur wenn Prävention eine System-Änderung erfordert
```

---

## Selbstmodifikation (apply_instruction / apply_code_fix)

Nur durchführen, wenn:
- Die Dreiphasen-Analyse klar zeigt, dass eine Systemänderung notwendig ist
- Die Änderung gezielt und minimal ist (nicht mehr als nötig)
- Ein `reason` angegeben wird, der die Verbindung zum Lernbericht erklärt

**Sicherheitsschicht:**
Alle Änderungen werden **automatisch durch ein zweites LLM validiert** bevor sie angewendet werden.
Bei Ablehnung (🛑) wird die Änderung nicht durchgeführt und der Grund wird ausgegeben.
Bei technischem Fehler der Validierung wird die Änderung trotzdem erlaubt (fail-open).

**Für Code-Fixes (`apply_code_fix`):**
- Backup wird automatisch angelegt (`.reflection_bak`)
- Python-Syntax wird vor dem Anwenden geprüft
- Deployment in beide Pfade: `/opt/jarvis/` + `/home/jarvis/jarvis/`
- `restart_service: true` nur für Backend-Dateien, die den Service betreffen

**Für Instruktionen (`apply_instruction`):**
- Backup wird automatisch angelegt (`.md.bak`)
- Änderung wird in beide Deploy-Pfade kopiert
- `old_text` für präzise Ersetzungen verwenden (exakter Match erforderlich)
- `new_text` ohne `old_text` = Anhang ans Ende der Datei

---

## Memory-Qualitätssicherung (sweep_memory)

Regelmäßig oder nach WhatsApp-Interaktionen:
- Erkennt Baileys-LID-Artefakte (zu lange Telefonnummern)
- Findet unaufgelöste Platzhalter (`{{...}}`)
- Meldet verdächtige URL-Längen

Wenn `sweep_memory` Probleme findet: Sofort `memory_manage(action='delete')` +
`memory_manage(action='save')` für korrigierte Version.

---

## Baileys-LID-Erkennung (bekanntes Fehlermuster)

WhatsApp-Nummern, die von der Baileys-Bridge kommen, können interne Geräte-IDs (LIDs)
enthalten, die wie Telefonnummern aussehen aber keine sind:
- Echte Nummern: `+491601234567` (max. 12 Ziffern nach Ländervorwahl)
- LID-Artefakte: `+58153907581169` (>12 Ziffern nach Ländervorwahl → verdächtig)

Beim Speichern von Kontaktnummern aus WhatsApp-Kontexten immer prüfen:
- Ländervorwahl realistisch?
- Gesamtlänge plausibel (max. 15 Ziffern gesamt laut ITU-T E.164)?
- Kommt die Nummer aus einer Benutzeraussage oder aus Bridge-Metadaten?

---

## Statistiken und Reports

- `get_stats` – Übersicht über alle Lernberichte (Kategorien, Schweregrade, Status)
- `list_reports` – Letzte Berichte mit optionalem Kategorie-Filter
- `update_report` – Status-Aktualisierung mit Notiz (→ "korrigiert", "verifiziert")
