"""Jarvis Vision Engine – DNN-basierte Gesichtserkennung mit face_recognition/dlib.

Laeuft als Hintergrund-Thread und erkennt bekannte Personen in Echtzeit.
Pro Profil koennen Aktionen festgelegt werden: Webhook, LLM-Prompt oder Logging.
"""

import glob
import json
import logging
import os
import pickle
import shutil
import ssl
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import urllib.request

import cv2
import numpy as np

try:
    import face_recognition
except ImportError:
    face_recognition = None


class MjpegStreamReader:
    """Liest MJPEG-Frames direkt per HTTP – umgeht OpenCV's Buffer-Problem.

    OpenCV's VideoCapture puffert MJPEG-Streams intern und liefert
    immer denselben (alten) Frame. Dieser Reader parst den Multipart-
    Stream manuell und liefert immer den neuesten Frame.
    """

    def __init__(self, url: str, timeout: float = 10):
        self._url = url
        self._timeout = timeout
        self._stream = None
        self._buffer = b""

    def open(self) -> bool:
        """Verbindung herstellen (unterstuetzt HTTPS mit self-signed Zertifikaten)."""
        try:
            ctx = None
            if self._url.startswith("https"):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            self._stream = urllib.request.urlopen(
                self._url, timeout=self._timeout, context=ctx
            )
            return True
        except Exception as e:
            log.warning("MJPEG-Stream Verbindungsfehler: %s", e)
            return False

    def read(self) -> tuple:
        """Nächsten Frame lesen. Gibt (True, np.ndarray) oder (False, None) zurück."""
        if not self._stream:
            return False, None

        try:
            # Daten lesen bis wir einen vollstaendigen JPEG-Frame haben
            while True:
                chunk = self._stream.read(4096)
                if not chunk:
                    return False, None
                self._buffer += chunk

                # JPEG Start (FFD8) und Ende (FFD9) suchen
                start = self._buffer.find(b"\xff\xd8")
                if start == -1:
                    # Kein JPEG-Start gefunden – alten Muell wegwerfen
                    self._buffer = self._buffer[-2:]
                    continue

                end = self._buffer.find(b"\xff\xd9", start + 2)
                if end == -1:
                    # Noch nicht komplett – weiter lesen
                    # Buffer nicht zu gross werden lassen
                    if len(self._buffer) > 2_000_000:
                        self._buffer = self._buffer[start:]
                    continue

                # Vollstaendiger JPEG-Frame gefunden
                jpeg_data = self._buffer[start:end + 2]
                self._buffer = self._buffer[end + 2:]

                # JPEG zu numpy-Array dekodieren
                arr = np.frombuffer(jpeg_data, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    return True, frame
                # Dekodierung fehlgeschlagen – naechsten Frame versuchen

        except Exception as e:
            log.warning("MJPEG-Stream Lesefehler: %s", e)
            return False, None

    def release(self):
        """Verbindung schliessen."""
        try:
            if self._stream:
                self._stream.close()
        except Exception:
            pass
        self._stream = None
        self._buffer = b""

    def isOpened(self) -> bool:
        return self._stream is not None

log = logging.getLogger("jarvis.vision")

# ── Konstanten ────────────────────────────────────────────────────────────────
MAX_EVENTS = 100           # Ring-Buffer für Erkennungs-Events
DEFAULT_TOLERANCE = 0.6    # face_recognition Toleranz (niedriger = strenger)
DEFAULT_INTERVAL = 1.0     # Erkennungsintervall in Sekunden
DEFAULT_SAMPLES = 30       # Trainingsbilder pro Person
COOLDOWN_SECONDS = 10      # Cooldown pro Person (Aktions-Spam vermeiden)
FRAME_WIDTH = 640
FRAME_HEIGHT = 480


class VisionEngine:
    """Singleton-Engine für Kamera-Capture + Gesichtserkennung."""

    def __init__(self, data_dir: str = "data/vision"):
        self.data_dir = Path(data_dir)
        self.faces_dir = self.data_dir / "faces"
        self.encodings_path = self.data_dir / "encodings.pkl"
        self.config_path = self.data_dir / "config.json"
        self.events_path = self.data_dir / "events.json"

        # Verzeichnisse anlegen
        self.faces_dir.mkdir(parents=True, exist_ok=True)

        # Kamera-State
        self._cap: Optional[cv2.VideoCapture] = None
        self._source: Union[int, str] = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._fps: float = 0.0
        self._last_frame_time: float = 0.0  # Zeitpunkt des letzten guten Frames

        # Erkennung
        self._known_encodings: dict[str, list] = {}  # {name: [encoding, ...]}
        self._current_faces: list[dict] = []
        self._current_face_crops: list[bytes] = []  # JPEG-Crops der erkannten Gesichter
        self._recent_events: list[dict] = []
        self._last_action_time: dict[str, float] = {}  # Cooldown pro Person
        self._tolerance = DEFAULT_TOLERANCE
        self._interval = DEFAULT_INTERVAL
        self._detection_model = "hog"  # "hog" oder "cnn"

        # Training
        self._training_active = False
        self._training_name = ""
        self._training_target = DEFAULT_SAMPLES
        self._training_count = 0
        self._training_phase = "idle"  # idle, capturing, encoding, done
        self._training_result = ""     # Encoding-Ergebnis für Status-Anzeige

        # Config + Daten laden
        self._config = self._load_config()
        self._load_encodings()
        self._load_events()

        # Action-Callback (wird vom Skill gesetzt)
        self.on_action: Optional[callable] = None

    # ── Konfiguration ─────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        """Lade config.json mit Profilen und Aktionen."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.warning("Config laden fehlgeschlagen: %s", e)
        return {
            "profiles": {},
            "actions": [
                {"id": "greet", "label": "Begrüßung (Lautsprecher)", "type": "prompt"},
                {"id": "llm", "label": "An LLM senden", "type": "prompt"},
                {"id": "door", "label": "Tür öffnen", "type": "none"},
                {"id": "webhook", "label": "Webhook aufrufen", "type": "url"},
                {"id": "log", "label": "Nur Loggen", "type": "none"},
            ],
        }

    def _save_config(self):
        """Speichere config.json."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error("Config speichern fehlgeschlagen: %s", e)

    # ── Encodings ─────────────────────────────────────────────────────────

    def _load_encodings(self):
        """Lade vorberechnete Gesichts-Encodings aus Pickle."""
        if self.encodings_path.exists():
            try:
                with open(self.encodings_path, "rb") as f:
                    self._known_encodings = pickle.load(f)
                log.info("Encodings geladen: %d Profile", len(self._known_encodings))
            except Exception as e:
                log.warning("Encodings laden fehlgeschlagen: %s", e)
                self._known_encodings = {}
        else:
            self._known_encodings = {}

    def _save_encodings(self):
        """Speichere Gesichts-Encodings als Pickle."""
        try:
            with open(self.encodings_path, "wb") as f:
                pickle.dump(self._known_encodings, f)
        except Exception as e:
            log.error("Encodings speichern fehlgeschlagen: %s", e)

    # ── Events ────────────────────────────────────────────────────────────

    def _load_events(self):
        """Lade letzte Erkennungs-Events."""
        if self.events_path.exists():
            try:
                with open(self.events_path, "r", encoding="utf-8") as f:
                    self._recent_events = json.load(f)
            except Exception:
                self._recent_events = []
        else:
            self._recent_events = []

    def _save_events(self):
        """Speichere Events-Buffer."""
        try:
            with open(self.events_path, "w", encoding="utf-8") as f:
                json.dump(self._recent_events[-MAX_EVENTS:], f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error("Events speichern fehlgeschlagen: %s", e)

    def _add_event(self, name: str, confidence: float, action_taken: str = ""):
        """Fuege ein Erkennungs-Event zum Ring-Buffer hinzu."""
        event = {
            "name": name,
            "confidence": round(confidence, 3),
            "timestamp": datetime.now().isoformat(),
            "action": action_taken,
        }
        self._recent_events.append(event)
        if len(self._recent_events) > MAX_EVENTS:
            self._recent_events = self._recent_events[-MAX_EVENTS:]
        self._save_events()

    # ── Kamera-Verwaltung ─────────────────────────────────────────────────

    def list_cameras(self) -> list[dict]:
        """Verfuegbare Kameras auflisten (Linux: /dev/video*)."""
        cameras = []
        # Suche /dev/video* Devices
        for dev in sorted(glob.glob("/dev/video*")):
            try:
                idx = int(dev.replace("/dev/video", ""))
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    cameras.append({
                        "index": idx,
                        "device": dev,
                        "name": f"USB Camera {idx}",
                    })
                    cap.release()
            except (ValueError, Exception):
                continue
        return cameras

    def start(self, source: Union[int, str] = 0) -> str:
        """Starte den Kamera-Feed und die Erkennung."""
        if face_recognition is None:
            return "Fehler: face_recognition nicht installiert. Bitte 'pip install face-recognition' ausführen."

        if self._running:
            return "Erkennung läuft bereits."

        # Quelle parsen (int für USB, str für RTSP/HTTP)
        try:
            source = int(source)
        except (ValueError, TypeError):
            pass

        self._source = source
        if isinstance(source, str):
            # URL-Stream: Eigener MJPEG-Reader (umgeht OpenCV Buffer-Bug)
            reader = MjpegStreamReader(source)
            if not reader.open():
                return f"Fehler: Stream '{source}' konnte nicht geöffnet werden."
            self._cap = reader
            log.info("URL-Stream via MjpegStreamReader geöffnet")
        else:
            # USB-Kamera: OpenCV VideoCapture
            self._cap = cv2.VideoCapture(source)
            if not self._cap.isOpened():
                self._cap = None
                return f"Fehler: Kamera '{source}' konnte nicht geöffnet werden."
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

        self._running = True
        self._thread = threading.Thread(target=self._recognition_loop, daemon=True)
        self._thread.start()
        log.info("Vision-Engine gestartet (Quelle: %s)", source)
        return f"Kamera-Feed gestartet (Quelle: {source})."

    def stop(self) -> str:
        """Stoppe den Kamera-Feed."""
        if not self._running:
            return "Erkennung ist nicht aktiv."

        self._running = False
        self._training_active = False

        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

        if self._cap:
            self._cap.release()
            self._cap = None

        self._frame = None
        self._current_faces = []
        log.info("Vision-Engine gestoppt.")
        return "Kamera-Feed gestoppt."

    def is_running(self) -> bool:
        return self._running

    def configure(self, tolerance: float = None, interval: float = None,
                  detection_model: str = None):
        """Engine-Parameter konfigurieren."""
        if tolerance is not None:
            self._tolerance = max(0.0, min(1.0, tolerance))
        if interval is not None:
            self._interval = max(0.1, interval)
        if detection_model is not None and detection_model in ("hog", "cnn"):
            self._detection_model = detection_model

    # ── Erkennungs-Loop ───────────────────────────────────────────────────

    def _recognition_loop(self):
        """Hintergrund-Thread: Frame lesen → Gesichter erkennen → Events."""
        last_recognition = 0
        frame_count = 0
        fps_start = time.time()
        fail_count = 0
        MAX_FAILS = 50  # Nach 50 Fehlern (ca. 5s) Reconnect versuchen

        while self._running:
            try:
                if not self._cap or not self._cap.isOpened():
                    # Reconnect-Versuch bei URL-Quellen
                    if isinstance(self._source, str) and fail_count < 3:
                        log.warning("Kamera nicht offen – Reconnect in 3s (Versuch %d)...", fail_count + 1)
                        time.sleep(3)
                        reader = MjpegStreamReader(self._source)
                        if reader.open():
                            self._cap = reader
                        fail_count += 1
                        continue
                    time.sleep(0.5)
                    continue

                ret, frame = self._cap.read()

                if not ret:
                    fail_count += 1
                    # FPS auf 0 setzen wenn keine Frames kommen
                    if fail_count >= 5:
                        self._fps = 0.0
                    if fail_count >= MAX_FAILS and isinstance(self._source, str):
                        # Reconnect bei URL-Streams
                        log.warning("Kein Frame seit %d Versuchen – Reconnect...", fail_count)
                        try:
                            self._cap.release()
                        except Exception:
                            pass
                        time.sleep(2)
                        reader = MjpegStreamReader(self._source)
                        if reader.open():
                            self._cap = reader
                            log.info("Stream-Reconnect erfolgreich: %s", self._source)
                        else:
                            log.warning("Stream-Reconnect fehlgeschlagen: %s", self._source)
                        fail_count = 0
                    elif fail_count >= MAX_FAILS:
                        time.sleep(1)
                    else:
                        time.sleep(0.1)
                    continue

                # Erfolgreicher Frame – Fail-Counter zurücksetzen
                fail_count = 0
                self._last_frame_time = time.time()

                # Frame speichern (Thread-sicher)
                with self._lock:
                    self._frame = frame.copy()

                # FPS berechnen
                frame_count += 1
                elapsed = time.time() - fps_start
                if elapsed >= 1.0:
                    self._fps = frame_count / elapsed
                    frame_count = 0
                    fps_start = time.time()

                # Training-Modus: Bilder sammeln
                if self._training_active:
                    self._capture_training_frame(frame)

                # Erkennungs-Zyklus (NICHT waehrend Encoding – Segfault-Gefahr)
                now = time.time()
                if now - last_recognition >= self._interval and self._training_phase != "encoding":
                    last_recognition = now
                    self._detect_and_recognize(frame)

                # Pause: URL-Streams brauchen keine, USB-Kameras kurze Pause
                if isinstance(self._source, int):
                    time.sleep(0.033)

            except Exception as e:
                log.error("Fehler im Erkennungs-Loop: %s", e, exc_info=True)
                time.sleep(1)

    def _detect_and_recognize(self, frame: np.ndarray):
        """Gesichter im Frame erkennen und abgleichen."""
        if face_recognition is None:
            return

        # Frame verkleinern für Geschwindigkeit
        small = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
        rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        # Gesichter finden
        locations = face_recognition.face_locations(rgb_small, model=self._detection_model)
        encodings = face_recognition.face_encodings(rgb_small, locations)

        detected = []
        crops = []
        for (top, right, bottom, left), encoding in zip(locations, encodings):
            # Koordinaten zurück auf Original-Größe
            ot, or_, ob, ol = top * 2, right * 2, bottom * 2, left * 2
            bbox = {"top": ot, "right": or_, "bottom": ob, "left": ol}

            name = "Unbekannt"
            confidence = 0.0

            if self._known_encodings:
                # Alle bekannten Encodings sammeln
                all_names = []
                all_encs = []
                for pname, pencs in self._known_encodings.items():
                    for enc in pencs:
                        all_names.append(pname)
                        all_encs.append(enc)

                if all_encs:
                    # Distanzen berechnen
                    distances = face_recognition.face_distance(all_encs, encoding)
                    best_idx = int(np.argmin(distances))
                    best_dist = distances[best_idx]

                    if best_dist <= self._tolerance:
                        name = all_names[best_idx]
                        confidence = round(1.0 - best_dist, 3)

                        # Event + Aktion (mit Cooldown)
                        self._trigger_action(name, confidence)

            detected.append({
                "name": name,
                "confidence": confidence,
                "bbox": bbox,
            })

            # Face-Crop für Vorschau (kleines JPEG)
            try:
                h, w = frame.shape[:2]
                margin = 15
                ct, cl = max(0, ot - margin), max(0, ol - margin)
                cb, cr = min(h, ob + margin), min(w, or_ + margin)
                crop = frame[ct:cb, cl:cr]
                if crop.size > 0:
                    crop_resized = cv2.resize(crop, (80, 80))
                    _, jpeg = cv2.imencode(".jpg", crop_resized, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    crops.append(jpeg.tobytes())
                else:
                    crops.append(b"")
            except Exception:
                crops.append(b"")

        with self._lock:
            self._current_faces = detected
            self._current_face_crops = crops

    def _trigger_action(self, name: str, confidence: float):
        """Aktion für erkannte Person ausführen (mit Cooldown)."""
        now = time.time()
        last = self._last_action_time.get(name, 0)
        if now - last < COOLDOWN_SECONDS:
            return

        self._last_action_time[name] = now

        # Profil-Aktion holen
        profiles = self._config.get("profiles", {})
        profile = profiles.get(name, {})
        action_type = profile.get("action", "log")
        action_value = profile.get("action_value", "")

        action_taken = action_type
        if action_type == "webhook" and action_value:
            self._execute_webhook(action_value, name, confidence)
        elif action_type == "llm" and action_value:
            self._execute_llm_action(action_value, name, confidence)
        elif action_type == "greet":
            self._execute_greet(action_value, name, confidence)
        elif action_type == "door":
            self._execute_door(name, confidence)

        self._add_event(name, confidence, action_taken)

    def _execute_webhook(self, url: str, name: str, confidence: float):
        """Webhook POST an konfigurierte URL."""
        try:
            import urllib.request
            data = json.dumps({
                "event": "face_recognized",
                "name": name,
                "confidence": confidence,
                "timestamp": datetime.now().isoformat(),
            }).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            urllib.request.urlopen(req, timeout=5)
            log.info("Webhook gesendet: %s -> %s", name, url)
        except Exception as e:
            log.warning("Webhook fehlgeschlagen: %s", e)

    def _execute_llm_action(self, prompt: str, name: str, confidence: float):
        """LLM-Aktion ausführen (via Callback)."""
        # Platzhalter im Prompt ersetzen
        filled = prompt.replace("{name}", name).replace(
            "{confidence}", f"{confidence:.1%}"
        )
        if self.on_action:
            try:
                self.on_action("llm", filled, name)
            except Exception as e:
                log.warning("LLM-Aktion fehlgeschlagen: %s", e)
        else:
            log.info("LLM-Aktion (kein Callback): %s", filled)

    def _execute_greet(self, text: str, name: str, confidence: float):
        """Begrüßung über Lautsprecher (Dummy – TODO: TTS-Integration)."""
        display_name = name.replace("_", " ").title()
        greeting = text.replace("{name}", display_name) if text else f"Hallo {display_name}!"
        log.info("Begrüßung (Dummy): '%s' (Konfidenz: %.0f%%)", greeting, confidence * 100)
        # TODO: espeak/piper TTS o.ä. für echte Sprachausgabe
        #   subprocess.run(["espeak", "-vde", greeting])

    def _execute_door(self, name: str, confidence: float):
        """Tür öffnen (Dummy – TODO: GPIO/Relay/API-Integration)."""
        log.info("Tür öffnen (Dummy) für '%s' (Konfidenz: %.0f%%)", name, confidence * 100)
        # TODO: GPIO-Pin setzen, Relay-API aufrufen, etc.

    # ── Training ──────────────────────────────────────────────────────────

    def start_training(self, name: str, num_samples: int = DEFAULT_SAMPLES) -> str:
        """Starte Training für ein neues Gesicht."""
        if not self._running:
            return "Fehler: Kamera-Feed muss zuerst gestartet werden."
        if self._training_active:
            return f"Fehler: Training für '{self._training_name}' läuft bereits."
        if not name or not name.strip():
            return "Fehler: Name darf nicht leer sein."

        name = name.strip().lower().replace(" ", "_")
        person_dir = self.faces_dir / name
        person_dir.mkdir(parents=True, exist_ok=True)

        self._training_name = name
        self._training_target = max(5, num_samples)
        self._training_count = 0
        self._training_active = True
        self._training_phase = "capturing"
        self._training_result = ""

        log.info("Training gestartet: '%s' (%d Samples)", name, num_samples)
        return f"Training gestartet für '{name}' ({num_samples} Aufnahmen)."

    def stop_training(self) -> str:
        """Stoppe Training und trainiere Modell neu."""
        if not self._training_active:
            return "Kein Training aktiv."

        name = self._training_name
        count = self._training_count
        self._training_active = False
        self._training_name = ""
        self._training_count = 0
        self._training_phase = "idle"
        self._training_result = ""

        if count == 0:
            return "Training abgebrochen – keine Bilder aufgenommen."

        # Encodings für die neuen Bilder berechnen
        result = self._compute_encodings(name)
        return f"Training beendet: {count} Bilder aufgenommen. {result}"

    def get_training_status(self) -> dict:
        """Aktuellen Training-Fortschritt abfragen."""
        return {
            "active": self._training_active,
            "name": self._training_name,
            "progress": self._training_count,
            "total": self._training_target,
            "phase": self._training_phase,
            "result": self._training_result,
        }

    def _capture_training_frame(self, frame: np.ndarray):
        """Ein Trainingsbild aufnehmen (Gesicht im Frame erkennen + speichern)."""
        if not self._training_active:
            return
        # Nur waehrend Capturing-Phase Bilder aufnehmen
        if self._training_phase != "capturing":
            return
        if self._training_count >= self._training_target:
            # Sofort Phase wechseln um Race-Condition zu vermeiden
            # (sonst spawnt jeder Frame einen neuen Thread → Segfault)
            self._training_phase = "encoding"
            threading.Thread(target=self._finish_training, daemon=True).start()
            return

        if face_recognition is None:
            return

        # Gesicht im Frame suchen
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb, model=self._detection_model)
        if not locations:
            return  # Kein Gesicht gefunden, naechster Frame

        # Groesstes Gesicht waehlen
        largest = max(locations, key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3]))
        top, right, bottom, left = largest

        # Etwas Rand hinzufuegen
        h, w = frame.shape[:2]
        margin = 30
        top = max(0, top - margin)
        left = max(0, left - margin)
        bottom = min(h, bottom + margin)
        right = min(w, right + margin)

        face_crop = frame[top:bottom, left:right]
        if face_crop.size == 0:
            return

        # Speichern
        self._training_count += 1
        filename = f"{self._training_count:03d}.jpg"
        filepath = self.faces_dir / self._training_name / filename
        cv2.imwrite(str(filepath), face_crop)

        # Pause zwischen Aufnahmen (verschiedene Winkel ermoeglichen)
        time.sleep(0.2)

    def _finish_training(self):
        """Training automatisch beenden wenn genug Samples."""
        name = self._training_name
        count = self._training_count

        # Phase "encoding" ist bereits in _capture_training_frame gesetzt
        log.info("Training-Aufnahme fertig: '%s' (%d Bilder), berechne Encodings...", name, count)

        result = self._compute_encodings(name)

        # Phase: Fertig
        self._training_phase = "done"
        self._training_result = result
        log.info("Training komplett: '%s' – %s", name, result)

        # Nach 5 Sekunden Status zurücksetzen
        time.sleep(5)
        self._training_active = False
        self._training_name = ""
        self._training_count = 0
        self._training_phase = "idle"
        self._training_result = ""

    def _compute_encodings(self, name: str) -> str:
        """Encodings für eine Person aus den Trainingsbildern berechnen."""
        if face_recognition is None:
            return "face_recognition nicht verfügbar."

        person_dir = self.faces_dir / name
        if not person_dir.exists():
            return f"Keine Trainingsbilder für '{name}' gefunden."

        encodings = []
        image_files = sorted(person_dir.glob("*.jpg"))

        for img_path in image_files:
            try:
                img = face_recognition.load_image_file(str(img_path))
                encs = face_recognition.face_encodings(img)
                if encs:
                    encodings.append(encs[0])
            except Exception as e:
                log.warning("Encoding für %s fehlgeschlagen: %s", img_path.name, e)

        if not encodings:
            return f"Keine Gesichts-Encodings aus Bildern extrahiert für '{name}'."

        self._known_encodings[name] = encodings
        self._save_encodings()

        # Profil anlegen wenn nicht vorhanden
        if name not in self._config.get("profiles", {}):
            self._config.setdefault("profiles", {})[name] = {
                "name": name.replace("_", " ").title(),
                "action": "log",
                "action_value": "",
                "created_at": datetime.now().isoformat(),
            }
            self._save_config()

        return f"{len(encodings)} Encodings aus {len(image_files)} Bildern berechnet."

    # ── Profile ───────────────────────────────────────────────────────────

    def list_profiles(self) -> list[dict]:
        """Alle bekannten Profile auflisten."""
        profiles = []
        for name, data in self._config.get("profiles", {}).items():
            person_dir = self.faces_dir / name
            num_images = len(list(person_dir.glob("*.jpg"))) if person_dir.exists() else 0
            num_encodings = len(self._known_encodings.get(name, []))

            profiles.append({
                "id": name,
                "name": data.get("name", name),
                "action": data.get("action", "log"),
                "action_value": data.get("action_value", ""),
                "created_at": data.get("created_at", ""),
                "num_images": num_images,
                "num_encodings": num_encodings,
            })
        return profiles

    def update_profile(self, name: str, display_name: str = None,
                       action: str = None, action_value: str = None) -> str:
        """Profil-Daten aktualisieren."""
        profiles = self._config.setdefault("profiles", {})
        if name not in profiles:
            return f"Profil '{name}' nicht gefunden."

        if display_name is not None:
            profiles[name]["name"] = display_name
        if action is not None:
            profiles[name]["action"] = action
        if action_value is not None:
            profiles[name]["action_value"] = action_value

        self._save_config()
        return f"Profil '{name}' aktualisiert."

    def delete_profile(self, name: str) -> str:
        """Profil komplett löschen (Bilder + Encodings + Config)."""
        # Config
        profiles = self._config.get("profiles", {})
        if name in profiles:
            del profiles[name]
            self._save_config()

        # Encodings
        if name in self._known_encodings:
            del self._known_encodings[name]
            self._save_encodings()

        # Bilder
        person_dir = self.faces_dir / name
        if person_dir.exists():
            shutil.rmtree(person_dir)

        return f"Profil '{name}' geloescht."

    def rename_profile(self, old_name: str, new_name: str) -> str:
        """Profil umbenennen."""
        new_name = new_name.strip().lower().replace(" ", "_")
        if not new_name:
            return "Fehler: Neuer Name darf nicht leer sein."

        profiles = self._config.get("profiles", {})
        if old_name not in profiles:
            return f"Profil '{old_name}' nicht gefunden."
        if new_name in profiles:
            return f"Profil '{new_name}' existiert bereits."

        # Config umbenennen
        profiles[new_name] = profiles.pop(old_name)
        profiles[new_name]["name"] = new_name.replace("_", " ").title()
        self._save_config()

        # Encodings umbenennen
        if old_name in self._known_encodings:
            self._known_encodings[new_name] = self._known_encodings.pop(old_name)
            self._save_encodings()

        # Bilder-Verzeichnis umbenennen
        old_dir = self.faces_dir / old_name
        new_dir = self.faces_dir / new_name
        if old_dir.exists():
            old_dir.rename(new_dir)

        return f"Profil '{old_name}' umbenannt zu '{new_name}'."

    def get_thumbnail(self, name: str) -> Optional[bytes]:
        """Erstes Trainingsbild als JPEG zurückgeben."""
        person_dir = self.faces_dir / name
        if not person_dir.exists():
            return None

        images = sorted(person_dir.glob("*.jpg"))
        if not images:
            return None

        try:
            return images[0].read_bytes()
        except Exception:
            return None

    # ── Status ────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Vollstaendigen Engine-Status abfragen."""
        return {
            "running": self._running,
            "camera_source": str(self._source),
            "fps": round(self._fps, 1),
            "current_faces": self.get_current_faces(),
            "recent_events": self.get_recent_events(10),
            "profiles_count": len(self._config.get("profiles", {})),
            "training": self.get_training_status(),
            "detection_model": self._detection_model,
            "tolerance": self._tolerance,
            "interval": self._interval,
        }

    def get_current_faces(self) -> list[dict]:
        """Aktuell sichtbare Gesichter."""
        with self._lock:
            return list(self._current_faces)

    def get_recent_events(self, limit: int = 20) -> list[dict]:
        """Letzte Erkennungs-Events."""
        return self._recent_events[-limit:]

    def get_snapshot(self, annotate: bool = True) -> Optional[bytes]:
        """Aktuellen Frame als JPEG (optional mit Markierungen)."""
        with self._lock:
            frame = self._frame.copy() if self._frame is not None else None
            faces = list(self._current_faces) if annotate else []

        if frame is None:
            return None

        if annotate and faces:
            for face in faces:
                bbox = face.get("bbox", {})
                name = face.get("name", "?")
                conf = face.get("confidence", 0)

                top = bbox.get("top", 0)
                right = bbox.get("right", 0)
                bottom = bbox.get("bottom", 0)
                left = bbox.get("left", 0)

                # Rahmen
                color = (0, 255, 0) if name != "Unbekannt" else (0, 165, 255)
                cv2.rectangle(frame, (left, top), (right, bottom), color, 2)

                # Label
                label = f"{name} ({conf:.0%})" if conf > 0 else name
                cv2.putText(frame, label, (left, top - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # Training-Indikator
        if self._training_active:
            tname = self._training_name if not self._training_name.startswith("_training_") else "Neues Gesicht"
            text = f"TRAINING: {tname} ({self._training_count}/{self._training_target})"
            cv2.putText(frame, text, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # Als JPEG kodieren
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return jpeg.tobytes()

    def get_preview(self, camera_index: int) -> Optional[bytes]:
        """Einzelbild von einer bestimmten Kamera (für Preview in Einstellungen)."""
        try:
            cap = cv2.VideoCapture(camera_index)
            if not cap.isOpened():
                return None
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
            ret, frame = cap.read()
            cap.release()
            if not ret:
                return None
            _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return jpeg.tobytes()
        except Exception:
            return None

    # ── Aktionen ──────────────────────────────────────────────────────────

    def get_available_actions(self) -> list[dict]:
        """Verfuegbare Aktions-Typen auflisten."""
        return self._config.get("actions", [])

    # ── System ────────────────────────────────────────────────────────────

    def cleanup(self) -> str:
        """Alle Daten zurücksetzen (Profile, Encodings, Events)."""
        # Erkennung stoppen
        if self._running:
            self.stop()

        # Bilder löschen
        if self.faces_dir.exists():
            shutil.rmtree(self.faces_dir)
            self.faces_dir.mkdir(parents=True, exist_ok=True)

        # Encodings löschen
        if self.encodings_path.exists():
            self.encodings_path.unlink()
        self._known_encodings = {}

        # Config zurücksetzen
        self._config["profiles"] = {}
        self._save_config()

        # Events löschen
        self._recent_events = []
        self._save_events()

        log.info("Vision-System zurückgesetzt.")
        return "Alle Vision-Daten zurückgesetzt."
