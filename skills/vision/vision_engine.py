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
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import cv2
import numpy as np

try:
    import face_recognition
except ImportError:
    face_recognition = None

log = logging.getLogger("jarvis.vision")

# ── Konstanten ────────────────────────────────────────────────────────────────
MAX_EVENTS = 100           # Ring-Buffer fuer Erkennungs-Events
DEFAULT_TOLERANCE = 0.6    # face_recognition Toleranz (niedriger = strenger)
DEFAULT_INTERVAL = 1.0     # Erkennungsintervall in Sekunden
DEFAULT_SAMPLES = 30       # Trainingsbilder pro Person
COOLDOWN_SECONDS = 10      # Cooldown pro Person (Aktions-Spam vermeiden)
FRAME_WIDTH = 640
FRAME_HEIGHT = 480


class VisionEngine:
    """Singleton-Engine fuer Kamera-Capture + Gesichtserkennung."""

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

        # Erkennung
        self._known_encodings: dict[str, list] = {}  # {name: [encoding, ...]}
        self._current_faces: list[dict] = []
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
                {"id": "webhook", "label": "Webhook senden", "type": "url"},
                {"id": "llm", "label": "LLM informieren", "type": "prompt"},
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
            return "Fehler: face_recognition nicht installiert. Bitte 'pip install face-recognition' ausfuehren."

        if self._running:
            return "Erkennung laeuft bereits."

        # Quelle parsen (int fuer USB, str fuer RTSP/HTTP)
        try:
            source = int(source)
        except (ValueError, TypeError):
            pass

        self._source = source
        self._cap = cv2.VideoCapture(source)
        if not self._cap.isOpened():
            self._cap = None
            return f"Fehler: Kamera '{source}' konnte nicht geoeffnet werden."

        # Aufloesung setzen
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

        while self._running:
            if not self._cap or not self._cap.isOpened():
                time.sleep(0.1)
                continue

            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.1)
                continue

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

            # Erkennungs-Zyklus
            now = time.time()
            if now - last_recognition >= self._interval:
                last_recognition = now
                self._detect_and_recognize(frame)

            # Kurze Pause (ca. 30 FPS Capture)
            time.sleep(0.033)

    def _detect_and_recognize(self, frame: np.ndarray):
        """Gesichter im Frame erkennen und abgleichen."""
        if face_recognition is None:
            return

        # Frame verkleinern fuer Geschwindigkeit
        small = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
        rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        # Gesichter finden
        locations = face_recognition.face_locations(rgb_small, model=self._detection_model)
        encodings = face_recognition.face_encodings(rgb_small, locations)

        detected = []
        for (top, right, bottom, left), encoding in zip(locations, encodings):
            # Koordinaten zurueck auf Original-Groesse
            bbox = {
                "top": top * 2, "right": right * 2,
                "bottom": bottom * 2, "left": left * 2,
            }

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

        with self._lock:
            self._current_faces = detected

    def _trigger_action(self, name: str, confidence: float):
        """Aktion fuer erkannte Person ausfuehren (mit Cooldown)."""
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
        """LLM-Aktion ausfuehren (via Callback)."""
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

    # ── Training ──────────────────────────────────────────────────────────

    def start_training(self, name: str, num_samples: int = DEFAULT_SAMPLES) -> str:
        """Starte Training fuer ein neues Gesicht."""
        if not self._running:
            return "Fehler: Kamera-Feed muss zuerst gestartet werden."
        if self._training_active:
            return f"Fehler: Training fuer '{self._training_name}' laeuft bereits."
        if not name or not name.strip():
            return "Fehler: Name darf nicht leer sein."

        name = name.strip().lower().replace(" ", "_")
        person_dir = self.faces_dir / name
        person_dir.mkdir(parents=True, exist_ok=True)

        self._training_name = name
        self._training_target = max(5, num_samples)
        self._training_count = 0
        self._training_active = True

        log.info("Training gestartet: '%s' (%d Samples)", name, num_samples)
        return f"Training gestartet fuer '{name}' ({num_samples} Aufnahmen)."

    def stop_training(self) -> str:
        """Stoppe Training und trainiere Modell neu."""
        if not self._training_active:
            return "Kein Training aktiv."

        name = self._training_name
        count = self._training_count
        self._training_active = False
        self._training_name = ""
        self._training_count = 0

        if count == 0:
            return "Training abgebrochen – keine Bilder aufgenommen."

        # Encodings fuer die neuen Bilder berechnen
        result = self._compute_encodings(name)
        return f"Training beendet: {count} Bilder aufgenommen. {result}"

    def get_training_status(self) -> dict:
        """Aktuellen Training-Fortschritt abfragen."""
        return {
            "active": self._training_active,
            "name": self._training_name,
            "progress": self._training_count,
            "total": self._training_target,
        }

    def _capture_training_frame(self, frame: np.ndarray):
        """Ein Trainingsbild aufnehmen (Gesicht im Frame erkennen + speichern)."""
        if not self._training_active:
            return
        if self._training_count >= self._training_target:
            # Automatisch Training beenden
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
        self._training_active = False
        self._training_name = ""
        count = self._training_count
        self._training_count = 0

        self._compute_encodings(name)
        log.info("Training automatisch beendet: '%s' (%d Bilder)", name, count)

    def _compute_encodings(self, name: str) -> str:
        """Encodings fuer eine Person aus den Trainingsbildern berechnen."""
        if face_recognition is None:
            return "face_recognition nicht verfuegbar."

        person_dir = self.faces_dir / name
        if not person_dir.exists():
            return f"Keine Trainingsbilder fuer '{name}' gefunden."

        encodings = []
        image_files = sorted(person_dir.glob("*.jpg"))

        for img_path in image_files:
            try:
                img = face_recognition.load_image_file(str(img_path))
                encs = face_recognition.face_encodings(img)
                if encs:
                    encodings.append(encs[0])
            except Exception as e:
                log.warning("Encoding fuer %s fehlgeschlagen: %s", img_path.name, e)

        if not encodings:
            return f"Keine Gesichts-Encodings aus Bildern extrahiert fuer '{name}'."

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
        """Profil komplett loeschen (Bilder + Encodings + Config)."""
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
        """Erstes Trainingsbild als JPEG zurueckgeben."""
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
            text = f"TRAINING: {self._training_name} ({self._training_count}/{self._training_target})"
            cv2.putText(frame, text, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # Als JPEG kodieren
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return jpeg.tobytes()

    def get_preview(self, camera_index: int) -> Optional[bytes]:
        """Einzelbild von einer bestimmten Kamera (fuer Preview in Einstellungen)."""
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
        """Alle Daten zuruecksetzen (Profile, Encodings, Events)."""
        # Erkennung stoppen
        if self._running:
            self.stop()

        # Bilder loeschen
        if self.faces_dir.exists():
            shutil.rmtree(self.faces_dir)
            self.faces_dir.mkdir(parents=True, exist_ok=True)

        # Encodings loeschen
        if self.encodings_path.exists():
            self.encodings_path.unlink()
        self._known_encodings = {}

        # Config zuruecksetzen
        self._config["profiles"] = {}
        self._save_config()

        # Events loeschen
        self._recent_events = []
        self._save_events()

        log.info("Vision-System zurueckgesetzt.")
        return "Alle Vision-Daten zurueckgesetzt."
