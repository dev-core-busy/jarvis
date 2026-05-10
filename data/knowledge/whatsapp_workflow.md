# WhatsApp – Wichtige Verhaltensregeln

## Kontakt per Name finden – IMMER erst Telefonbuch suchen

Wenn der Benutzer eine WhatsApp-Nachricht an eine Person **per Name** (nicht per Telefonnummer) senden will:

1. **ZUERST** das Tool `whatsapp_contacts` aufrufen mit dem Namen als Suchbegriff
2. Die gefundene Telefonnummer aus dem Ergebnis verwenden
3. **NIEMALS** den Benutzer nach der Telefonnummer fragen – das Telefonbuch ist über `whatsapp_contacts` direkt abrufbar

### Beispiel-Workflow
Benutzer: "Schreib Oliver Barthel eine WhatsApp: Angebot prüfen"
→ `whatsapp_contacts(search="Oliver Barthel")` → Nummer +49... erhalten
→ `whatsapp_send(to="+49...", message="Angebot prüfen")`

## WhatsApp-Verbindung
- WhatsApp-Bridge läuft als separater Node.js-Prozess (Port 3001, localhost)
- Status prüfen: `whatsapp_status` Tool
- Whitelist: Nur autorisierte Nummern können Jarvis per WhatsApp steuern

## Nachrichten formatieren
- Kein Markdown (kein **fett**, keine Listen mit -)
- Kurz und prägnant, WhatsApp-tauglich
- Emojis erlaubt

## Fehlerursachen (bekannt)
- "Bridge nicht erreichbar": `systemctl restart whatsapp-bridge.service`
- Neue Nummer: Erst per QR-Code neu einloggen
