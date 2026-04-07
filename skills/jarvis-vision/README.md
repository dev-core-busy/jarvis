# Jarvis Vision System (Pi Zero Face Recognition)

Ein leichtgewichtiges Gesichtserkennungssystem, das für den Raspberry Pi Zero optimiert ist. Es nutzt OpenCV (Haar Cascades / LBPHFaceRecognizer) für performante Erkennung auf ressourcenbeschränkter Hardware und bietet eine Flask-basierte Weboberfläche zur Verwaltung.

## Features

- **Echtzeit-Gesichtserkennung:** Nutzt die Kamera (inkl. Mock-Kamera für Tests) zur Erkennung.
- **Web-Dashboard:** Flask-Webserver zur Live-Anzeige des Kamerabilds und Systemstatus (`http://<ip>:5000`).
- **Profilverwaltung:** Gesichter können erfasst, trainiert und mit Aktionen (z. B. Webhooks) verknüpft werden.
- **Dynamisches Training:** Asynchrones Training des Modells im Hintergrund, ohne die Kamera aufzuhalten.
- **Automatisches Logging:** Erkannte Personen lösen Log-Einträge mit einstellbarem Cooldown (10s) aus, um Spam zu vermeiden.
- **Log-Aktualisierung:** Manueller "Aktualisieren"-Button in der UI für sofortiges Log-Feedback.
- **Aktionen:** Erkannte Personen können benutzerdefinierte Aktionen auslösen (derzeit signalisiert im Dashboard und in den Logs).

## Installation

1. **Abhängigkeiten installieren:**
   ```bash
   pip install -r requirements.txt
   ```
   (Auf dem Raspberry Pi kann es notwendig sein, OpenCV aus den Systempaketen zu installieren: `sudo apt install python3-opencv`)

2. **Kaskaden-Dateien:**
   Das System benötigt die OpenCV Haar-Cascade `haarcascade_frontalface_default.xml` im Ordner `models/`. (Wird vom Agenten oder manuell heruntergeladen, falls fehlend).

3. **Starten:**
   ```bash
   python app.py
   ```
   Das Dashboard ist dann unter `http://localhost:5000` (bzw. der IP des Pi) erreichbar.

## Projektstruktur

- `app.py`: Der Flask-Webserver und API-Controller.
- `camera_manager.py`: Kernlogik für Kamerazugriff, Gesichtserkennung (LBPH) und Hintergrund-Training.
- `config.json`: Speichert Profile und Aktionen.
- `dataset/`: Speichert die Rohbilder der registrierten Gesichter für das Training.
- `models/`: Speichert das trainierte Modell (`trainer.yml`) und die Haar-Cascade.
- `templates/`, `static/`: Frontend-Dateien (HTML/CSS/JS).

Das Backend übermittelt im Status-Endpoint (`/api/status`), wenn eine angelernte Person erkannt wird. Es schlägt die erkannte ID in der `config.json` nach und sendet den Namen und die verknüpfte Aktion an das Frontend, welches dieses Ereignis im Dashboard visualisiert.

## LLM & Smart Home Integration

Das Jarvis Vision System ist so konzipiert, dass es nahtlos mit externen Large Language Models (LLMs) wie **Ollama**, **Jarvis** oder **Home Assistant** zusammenarbeiten kann.

### API-Schnittstelle zur Erkennung
Die zentrale Schnittstelle ist der Endpoint:
`GET /api/status`

**Response Example:**
```json
{
  "current_face_id": "1710456789",
  "detected_info": "Namens-Check: Max (Aktion: Willkommen)",
  "training_mode": false,
  "camera_index": 0
}
```

### Integration mit LLMs (z.B. Ollama)
Ein externer Agent kann diesen Endpoint pollen, um personalisierte Aktionen auszulösen:
1. **Identifikation:** Wenn `current_face_id` nicht `null` ist, wurde eine bekannte Person erkannt.
2. **Kontext-Check:** Der Agent liest den Namen aus `detected_info`.
3. **LLM-Prompt:** Ein LLM kann nun personalisierte Begrüßungen generieren, z.B.:
   *   *Input:* "Max ist gerade den Raum betreten."
   *   *LLM Output:* "Willkommen zurück, Max! Soll ich die Kaffeemaschine starten?"

### Webhooks
In der `config.json` können Aktionen hinterlegt werden. Zukünftige Erweiterungen können diese Strings direkt als Webhook-URLs interpretieren, um HTTP-Requests an Smart Home Zentralen zu senden.

## Fehlerbehebung (VMware / Virtualisierung)

Beim Betrieb in einer virtuellen Maschine (z. B. VMware) kann es zu Problemen mit USB-Kameras kommen, wenn Hardware-Probes zu schnell oder zu häufig erfolgen. 

**Symptom:** Beim Aufrufen der Kamera-Liste wird die USB-Kamera vom Gast-System getrennt oder der Prozess stürzt ab.
**Lösung:** 
- In `camera_manager.py` wurde ein Caching-System für die verfügbaren Kameras implementiert.
- Zwischen den Probes der einzelnen Indizes wurde ein Handshake-Delay von 100ms eingebaut.
- Das Frontend nutzt standardmäßig den Cache. Ein gezielter Hardware-Scan erfolgt nur manuell über den Button "Liste laden" in den Einstellungen.
