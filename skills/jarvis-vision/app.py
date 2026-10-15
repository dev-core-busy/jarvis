from flask import Flask, render_template, Response, request, jsonify, send_from_directory
from camera_manager import CameraManager
import json
import os
import datetime
import threading
import time

last_action_face_id = None
last_action_time = 0

logs = []

def add_log(msg):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    logs.append(f"[{timestamp}] {msg}")
    if len(logs) > 100: logs.pop(0)

add_log("Jarvis Vision System gestartet")

app = Flask(__name__)
camera = CameraManager()

CONFIG_FILE = 'config.json'

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"profiles": {}, "actions": []}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    def gen():
        while True:
            frame = camera.get_frame_bytes()
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def status():
    status_data = camera.get_status()
    config = load_config()
    
    if not status_data.get("training_mode") and status_data.get("current_face_id"):
        face_id = str(status_data["current_face_id"])
        if face_id in config.get("profiles", {}):
            profile = config["profiles"][face_id]
            name = profile.get("name", "Unbekannt")
            action = profile.get("action", "log")
            
            action_label = action
            for act in config.get("actions", []):
                if act.get("id") == action:
                    action_label = act.get("label", action)
                    break
                    
            status_data["detected_info"] = f"{name} (Aktion: {action_label})"
            
            global last_action_face_id, last_action_time
            current_time = time.time()
            if face_id != last_action_face_id or (current_time - last_action_time > 10):
                last_action_face_id = face_id
                last_action_time = current_time
                add_log(f"Aktion '{action_label}' für {name} ausgelöst.")
            
    return jsonify(status_data)

@app.route('/api/logs')
def get_logs():
    return jsonify({"logs": logs})

@app.route('/api/cameras', methods=['GET'])
def get_cameras():
    force = request.args.get('refresh', 'false').lower() == 'true'
    return jsonify({
        "available": camera.get_available_cameras(force_refresh=force),
        "current": camera.camera_index
    })

@app.route('/api/camera/select', methods=['POST'])
def select_camera():
    index = request.json.get('index', 0)
    success = camera.switch_camera(index)
    return jsonify({"status": "ok" if success else "mock"})

@app.route('/api/camera/preview/<int:index>')
def camera_preview(index):
    frame = camera.get_snapshot(index)
    if frame:
        return Response(frame, mimetype='image/jpeg')
    return "Kein Bild", 404

@app.route('/api/profile/thumbnail/<string:id>')
def get_thumbnail(id):
    dataset_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dataset')
    filename = f"user.{id}.1.jpg"
    if os.path.exists(os.path.join(dataset_path, filename)):
        return send_from_directory(dataset_path, filename)
    return "Not found", 404

@app.route('/api/profiles', methods=['GET'])
def get_profiles():
    config = load_config()
    dataset_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dataset')
    
    def get_timestamp(pid):
        img_path = os.path.join(dataset_path, f"user.{pid}.1.jpg")
        if os.path.exists(img_path):
            mtime = os.path.getmtime(img_path)
            return datetime.datetime.fromtimestamp(mtime).strftime('%d.%m.%Y %H:%M')
        return "Unbekannt"

    # IDs aus dem Dataset extrahieren, die noch nicht in den Profilen sind
    dataset_ids = set()
    if os.path.exists(dataset_path):
        for f in os.listdir(dataset_path):
            if f.startswith('user.'):
                dataset_ids.add(f.split('.')[1])
                
    # Zeitstempel für bekannte Profile injizieren
    for pid in config["profiles"]:
        config["profiles"][pid]["created_at"] = get_timestamp(pid)
        
    # Unbenannte Profile mit Zeitstempel aufbauen
    unnamed = []
    for pid in list(dataset_ids - set(config["profiles"].keys())):
        unnamed.append({
            "id": pid,
            "created_at": get_timestamp(pid)
        })
    
    return jsonify({
        "profiles": config["profiles"],
        "unnamed_profiles": unnamed,
        "actions": config["actions"]
    })

@app.route('/api/profiles', methods=['POST'])
def update_profile():
    data = request.json
    config = load_config()
    profile_id = str(data.get('id'))
    config["profiles"][profile_id] = {
        "name": data.get('name', 'Unbekannt'),
        "action": data.get('action', 'log'),
        "action_value": data.get('action_value', '')
    }
    save_config(config)
    return jsonify({"status": "ok"})

@app.route('/api/profile/delete', methods=['POST'])
def delete_profile():
    data = request.json
    profile_id = str(data.get('id'))
    
    # Aus Config löschen
    config = load_config()
    if profile_id in config["profiles"]:
        del config["profiles"][profile_id]
    save_config(config)
    
    # Aus Dataset löschen
    camera.delete_person(profile_id)
    
    # Modell asynchron neu trainieren
    threading.Thread(target=camera.train_model).start()
    
    return jsonify({"status": "deleted"})

@app.route('/api/training/start', methods=['POST'])
def start_training():
    person_id = request.json.get('id')
    camera.start_training(person_id)
    return jsonify({"status": "started"})

@app.route('/api/training/stop', methods=['POST'])
def stop_training():
    camera.stop_training()
    # Training im Hintergrund starten, um Timeout zu vermeiden
    thread = threading.Thread(target=camera.train_model)
    thread.start()
    return jsonify({"status": "stopped"})

@app.route('/api/cleanup', methods=['POST'])
def cleanup():
    camera.cleanup_dataset()
    config = load_config()
    config["profiles"] = {}
    save_config(config)
    return jsonify({"status": "cleaned"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
