import cv2
import threading
import time
import os
import json
import numpy as np
import glob
from PIL import Image

class CameraManager:
    def __init__(self, camera_index=0):
        self.lock = threading.Lock()
        self.camera_index = camera_index
        self.frame = None
        self.is_running = True
        self.mock_mode = True
        
        self._initialize_camera(camera_index)
        
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        
        # Recognition & Training State
        self.recognizer = cv2.face.LBPHFaceRecognizer_create()
        cascade_path = os.path.join(self.base_path, 'models', 'haarcascade_frontalface_default.xml')
        self.detector = cv2.CascadeClassifier(cascade_path)
        if self.detector.empty():
            print(f"[ERROR] Haar-Cascade konnte nicht geladen werden unter: {cascade_path}")
        self.load_model()
        
        self.training_mode = False
        self.training_id = None
        self.training_count = 0
        self.training_limit = 30
        
        self.detected_info = "Warten..."
        self.current_face_id = None
        self.available_cameras = []
        self._refresh_camera_list()
        
        # Thread starten
        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()

    def _initialize_camera(self, index):
        if hasattr(self, 'cam') and self.cam:
            self.cam.release()
        
        self.cam = cv2.VideoCapture(index)
        
        # Versuche MJPG für bessere Kompatibilität mit HD USB-Cams
        self.cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        if not self.cam.isOpened():
            print(f"[WARNING] Kamera {index} konnte nicht geöffnet werden. Versuche ohne MJPG...")
            self.cam = cv2.VideoCapture(index)
            self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

        if not self.cam.isOpened():
            print(f"[WARNING] Kamera {index} endgültig gescheitert. Mock-Modus aktiv.")
            self.mock_mode = True
        else:
            print(f"[INFO] Kamera {index} erfolgreich initialisiert.")
            self.mock_mode = False
            self.camera_index = index

    def _refresh_camera_list(self):
        cameras = []
        # Fallback auf Dateiebene (Linux), um aggressive Hardware-Probes zu vermeiden (VMware Fix)
        video_devices = glob.glob('/dev/video*')
        
        # Extrahiere IDs aus /dev/videoX
        found_ids = []
        for dev in video_devices:
            try:
                # Pfad ist /dev/video0 -> 0 am Ende
                idx = int(dev.replace('/dev/video', ''))
                # V4L2 erzeugt oft Video0 und Video1 für dieselbe Kamera (Metadaten-Node)
                # Wir nehmen nur gerade Nummern oder wir filtern nach Erreichbarkeit
                if idx < 10: found_ids.append(idx)
            except: continue
        
        if not found_ids:
            # Falls glob nichts findet (z.B. anderes OS), probieren wir nur den aktuellen Index
            if not self.mock_mode: cameras.append(self.camera_index)
        else:
            # Wir prüfen nur die IDs, die vom System gemeldet wurden
            # Das ist viel sicherer als blind 0-10 durchzuprobieren
            for i in sorted(list(set(found_ids))):
                if i == self.camera_index and not self.mock_mode:
                    cameras.append(i)
                    continue
                
                # Nur kurz prüfen, ob wirklich Capture-Node
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    # Prüfen, ob MJPG oder ähnliches unterstützt wird (optional)
                    cameras.append(i)
                    cap.release()
                    time.sleep(0.2) # Noch längerer Delay für VMware
        
        self.available_cameras = cameras
        return cameras

    def get_available_cameras(self, force_refresh=False):
        if force_refresh or not self.available_cameras:
            return self._refresh_camera_list()
        return self.available_cameras

    def switch_camera(self, index):
        with self.lock:
            self._initialize_camera(index)
        return not self.mock_mode

    def get_snapshot(self, index):
        # Wenn es die aktuelle Kamera ist, nehmen wir das letzte Frame
        if index == self.camera_index and not self.mock_mode:
            return self.get_frame_bytes()
        
        # Sonst kurz öffnen
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            return None
        
        ret, frame = cap.read()
        cap.release()
        
        if ret:
            # Komprimieren
            _, buffer = cv2.imencode('.jpg', frame)
            return buffer.tobytes()
        return None

    def get_status(self):
        return {
            "mock_mode": self.mock_mode,
            "camera_index": self.camera_index,
            "training_mode": self.training_mode,
            "detected_info": self.detected_info,
            "current_face_id": getattr(self, 'current_face_id', None)
        }

    def load_model(self):
        trainer_path = os.path.join(self.base_path, 'models', 'trainer.yml')
        if os.path.exists(trainer_path):
            self.recognizer.read(trainer_path)
            return True
        return False

    def _update_loop(self):
        last_recognition_time = 0
        recognition_interval = 0.5 
        
        while self.is_running:
            if self.mock_mode:
                # Mock-Frame generieren (Dunkelgrau mit Text)
                img = np.zeros((240, 320, 3), dtype=np.uint8) + 40
                cv2.putText(img, "MOCK CAMERA", (60, 120), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                ret = True
                time.sleep(0.1) # Simulate FPS
            else:
                ret, img = self.cam.read()
            
            if not ret:
                continue
            
            # Kopie für Analyse (Graustufen)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            with self.lock:
                current_time = time.time()
                
                # Gesichtserkennung (nicht jedes Frame)
                if current_time - last_recognition_time > recognition_interval:
                    faces = self.detector.detectMultiScale(gray, 1.2, 5)
                    self.detected_info = "Kein Gesicht"
                    self.current_face_id = None
                    
                    for (x, y, w, h) in faces:
                        # Overlay zeichnen
                        cv2.rectangle(img, (x, y), (x+w, y+h), (0, 255, 0), 2)
                        
                        if not self.training_mode and os.path.exists(os.path.join(self.base_path, 'models', 'trainer.yml')):
                            try:
                                id, confidence = self.recognizer.predict(gray[y:y+h, x:x+w])
                                if confidence < 80:
                                    self.detected_info = f"ID: {id} ({round(100-confidence)}%)"
                                    self.current_face_id = str(id)
                                else:
                                    self.detected_info = "Unbekannt"
                                    self.current_face_id = None
                            except cv2.error:
                                # Modell existiert zwar, ist aber evtl. leer/inkompatibel
                                self.detected_info = "System bereit (Modell fehlt)"
                                self.current_face_id = None
                        
                        # Live Training Logik
                        if self.training_mode and self.training_id:
                            self.training_count += 1
                            file_path = os.path.join(self.base_path, 'dataset', f"user.{self.training_id}.{self.training_count}.jpg")
                            cv2.imwrite(file_path, gray[y:y+h, x:x+w])
                            self.detected_info = f"Training: {self.training_count}/{self.training_limit}"
                            
                            if self.training_count >= self.training_limit:
                                self.training_mode = False
                                self.training_id = None
                                self.detected_info = "Training abgeschlossen. Modell wird optimiert..."
                                # Training asynchron starten, um den Loop nicht zu blockieren
                                threading.Thread(target=self.train_model, daemon=True).start()
                    
                    last_recognition_time = current_time
                
                self.frame = img

    def get_frame_bytes(self):
        with self.lock:
            if self.frame is None:
                return None
            ret, buffer = cv2.imencode('.jpg', self.frame)
            return buffer.tobytes()

    def start_training(self, person_id):
        with self.lock:
            self.training_mode = True
            self.training_id = person_id
            self.training_count = 0
            # Alten Datenmüll für diese ID entfernen?
            # Hier vereinfacht: wird einfach überschrieben/ergänzt

    def stop_training(self):
        with self.lock:
            self.training_mode = False
            self.training_id = None

    def train_model(self):
        try:
            path = os.path.join(self.base_path, 'dataset')
            imagePaths = [os.path.join(path, f) for f in os.listdir(path) if f.endswith('.jpg')]
            faceSamples = []
            ids = []

            for imagePath in imagePaths:
                PIL_img = Image.open(imagePath).convert('L')
                img_numpy = np.array(PIL_img, 'uint8')
                try:
                    id = int(os.path.split(imagePath)[-1].split(".")[1])
                    # Die Bilder im Dataset sind bereits zugeschnittene Gesichter!
                    # Wir müssen detectMultiScale hier nicht nochmal ausführen.
                    faceSamples.append(img_numpy)
                    ids.append(id)
                except:
                    continue

            if len(ids) > 0:
                # Neues lokales Modell trainieren (blockiert nicht den Haupt-Thread)
                local_recognizer = cv2.face.LBPHFaceRecognizer_create()
                local_recognizer.train(faceSamples, np.array(ids, dtype=np.int32))
                
                trainer_path = os.path.join(self.base_path, 'models', 'trainer.yml')
                local_recognizer.write(trainer_path)
                
                # Fertiges Modell atomar im Haupt-Thread austauschen
                with self.lock:
                    self.recognizer = local_recognizer
                    self.detected_info = "Modell-Update erfolgreich!"
                print(f"[INFO] Modell für {len(ids)} Gesichter erfolgreich trainiert.")
                return True
            else:
                print("[WARNING] Keine Trainingsdaten gefunden (len(ids) == 0).")
            return False
        except Exception as e:
            import traceback
            print(f"[ERROR] Fehler beim Training: {e}")
            traceback.print_exc()
            with self.lock:
                self.detected_info = "Training fehlgeschlagen!"
            return False

    def delete_person(self, person_id):
        with self.lock:
            # Alle Bilder für diese ID im dataset löschen
            dataset_path = os.path.join(self.base_path, 'dataset')
            prefix = f"user.{person_id}."
            for f in os.listdir(dataset_path):
                if f.startswith(prefix) and f.endswith('.jpg'):
                    try:
                        os.remove(os.path.join(dataset_path, f))
                    except:
                        pass
        # Training wird jetzt vom Caller (app.py) asynchron gestartet

    def cleanup_dataset(self):
        # Alle Dateien im dataset löschen
        dataset_path = os.path.join(self.base_path, 'dataset')
        for f in os.listdir(dataset_path):
            if f.endswith('.jpg'):
                os.remove(os.path.join(dataset_path, f))
        
        # Modell löschen
        trainer_path = os.path.join(self.base_path, 'models', 'trainer.yml')
        if os.path.exists(trainer_path):
            os.remove(trainer_path)
        # Recognizer zurücksetzen
        self.recognizer = cv2.face.LBPHFaceRecognizer_create()

    def stop(self):
        self.is_running = False
        self.cam.release()
