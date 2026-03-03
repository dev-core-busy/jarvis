# Jarvis Projektinfo

Jarvis ist ein autonomer KI-Agent fuer Linux-Systeme mit modularem Skill-System und WhatsApp-Integration.

## Server
- Server-IP: ${SERVER_IP} (aus .env)
- Betriebssystem: Debian 13 (Trixie)
- Display: X11, physisches Display :0
- Services: jarvis.service + whatsapp-bridge.service (systemd)

## Technologie-Stack
- Backend: Python 3.13, FastAPI, Uvicorn (HTTPS Port 8000)
- Frontend: HTML/CSS/JS (kein Framework), Dark Glassmorphism Theme
- LLM: Multi-Provider (Google Gemini, OpenRouter, Anthropic, OpenAI-compatible)
- VNC: x11vnc + websockify + noVNC (Port 5900 / 6080)
- WhatsApp Bridge: Node.js + Baileys v7 (Port 3001, nur localhost)
- Speech-to-Text: faster-whisper (CTranslate2, CPU, int8)

## Skill-System
Modulares Plugin-System. Jeder Skill hat ein `skill.json` Manifest und ein Python-Modul.

### System-Skills (immer geladen)
| Skill | Tool-Name | Beschreibung |
|-------|-----------|--------------|
| Shell | shell_execute | Bash-Befehle ausfuehren |
| Desktop | desktop_control | X11 Maus/Tastatur/Fenster steuern |
| Dateisystem | filesystem | Dateien lesen/schreiben/auflisten |
| Screenshot | screenshot | Desktop-Screenshots erstellen (Base64) |
| Wissensdatenbank | knowledge_search | TF-IDF Suche in data/knowledge/ |
| Memory | memory_manage | Persistenter Key-Value-Speicher |

### Externe Skills
| Skill | Tool-Names | Beschreibung |
|-------|------------|--------------|
| Browser Control | browser_control | Chrome/Firefox Steuerung (Navigation, Tabs, Zoom) |
| WhatsApp | whatsapp_send, whatsapp_status | Nachrichten senden, Status abfragen |

## WhatsApp-Integration
Jarvis kann ueber WhatsApp gesteuert werden. Sprachnachrichten werden automatisch transkribiert und als Aufgaben ausgefuehrt.

### Architektur
```
Smartphone → WhatsApp Server → Baileys Bridge (:3001) → Jarvis Backend (:8000)
                                                         ↓
                                                    faster-whisper (falls Voice)
                                                         ↓
                                                    Agent fuehrt Aufgabe aus
                                                         ↓
                                                    Antwort → WhatsApp
```

### WhatsApp-Endpoints
- `GET /api/whatsapp/status` – Verbindungsstatus
- `GET /api/whatsapp/qr` – QR-Code zum Pairing
- `POST /api/whatsapp/incoming` – Webhook fuer eingehende Nachrichten
- `POST /api/whatsapp/logout` – WhatsApp abmelden
- `POST /api/whatsapp/reconnect` – Verbindung neu herstellen

### WhatsApp Skill-Konfiguration (ueber Settings-UI)
- `auto_reply`: Automatische Antworten an/aus
- `allowed_numbers`: Kommagetrennte Whitelist (leer = alle)
- `process_voice`: Sprachnachrichten verarbeiten
- `process_text`: Textnachrichten verarbeiten
- `whisper_model`: tiny/base/small/medium/large (Standard: small)

## Wichtige Pfade
- Projekt: /opt/jarvis (Service) + /home/bender/jarvis (Entwicklung)
- Skills: /opt/jarvis/skills/
- WhatsApp Bridge: /opt/jarvis/services/whatsapp-bridge/
- Zertifikate: /opt/jarvis/certs/
- Knowledge Base: /opt/jarvis/data/knowledge/
- Memory: /opt/jarvis/data/memory.json
- Settings: /opt/jarvis/data/settings.json

## Zugang
- HTTPS Port: 8000 (Backend + Frontend)
- VNC Port: 5900
- Websockify Port: 6080
- WhatsApp Bridge Port: 3001 (nur localhost)

## API-Uebersicht
- `POST /api/login` – PAM-Login
- `GET /api/settings` + `POST /api/settings` – Einstellungen
- `GET /api/profiles` + CRUD – KI-Profile verwalten
- `GET /api/skills` – Alle Skills auflisten
- `POST /api/skills/{name}/enable|disable` – Skill an/aus
- `GET|POST /api/skills/{name}/config` – Skill-Konfiguration
- `POST /api/skills/reload` – Hot-Reload
- `GET /api/whatsapp/status|qr` – WhatsApp Status/QR
- `POST /api/whatsapp/incoming|logout|reconnect` – WhatsApp Steuerung
- `WS /ws` – WebSocket fuer Agent-Tasks und Live-Updates
