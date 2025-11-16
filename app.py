from flask import Flask, render_template, request, jsonify, send_from_directory
import cv2
import numpy as np
import base64
import datetime
import os
import threading
import io
from PIL import Image

app = Flask(__name__, static_folder="static", template_folder="templates")

# ========== Configuration & State ==========
YUNET_PATH = os.path.join("models", "face_detection_yunet_2023mar.onnx")
CAFFE_PROTO = os.path.join("models", "deploy.prototxt")
CAFFE_MODEL = os.path.join("models", "res10_300x300_ssd_iter_140000.caffemodel")

# Default thresholds (can be updated from client)
state = {
    "head_pose_threshold": 0.25,
    "head_pose_alert_duration": 3.0,
    "voice_threshold": 0.08,   # client RMS threshold (normalized)
    "voice_alert_duration": 2.0,
    "multiple_persons_threshold": 1,
    "min_face_size": 80,
    "confidence_threshold": 0.6
}

LOG_FILE = "proctoring_log.txt"

# Detector placeholders
detector_yunet = None
net_caffe = None
face_cascade = None

# Initialize log
def initialize_log():
    with open(LOG_FILE, "w") as f:
        f.write("Web Proctoring Log\n")
        f.write("="*50 + "\n")
        f.write(f"Session started: {datetime.datetime.now()}\n\n")

def log_event(event_type, details):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {event_type}: {details}\n"
    print(entry.strip())
    with open(LOG_FILE, "a") as f:
        f.write(entry)

initialize_log()

# ========== Load detectors (YuNet -> Caffe -> Haar) ==========
def init_detectors():
    global detector_yunet, net_caffe, face_cascade
    try:
        if os.path.exists(YUNET_PATH):
            detector_yunet = cv2.FaceDetectorYN.create(
                YUNET_PATH, "", (0, 0), 0.9, 0.3, 5000
            )
            print("YuNet loaded.")
        elif os.path.exists(CAFFE_PROTO) and os.path.exists(CAFFE_MODEL):
            net_caffe = cv2.dnn.readNetFromCaffe(CAFFE_PROTO, CAFFE_MODEL)
            print("Caffe DNN loaded.")
        else:
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            print("Using Haar cascade fallback.")
    except Exception as e:
        print("Detector init error:", e)
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

init_detectors()

# ========== Utilities ==========
def b64_to_image(base64_data):
    header, encoded = base64_data.split(",", 1) if "," in base64_data else (None, base64_data)
    binary = base64.b64decode(encoded)
    image = Image.open(io.BytesIO(binary)).convert("RGB")
    return np.array(image)[:, :, ::-1]  # PIL RGB -> OpenCV BGR

def detect_faces_stable(frame):
    """
    More permissive face detection:
    - supports YuNet, Caffe, Haar fallback
    - returns list of (x,y,w,h) and optional landmarks (for first face only)
    """
    h, w = frame.shape[:2]
    faces = []
    landmarks = None

    # --- YuNet detector (if available) ---
    if detector_yunet is not None:
        try:
            # Ensure input size set
            detector_yunet.setInputSize((w, h))
            # detect returns (retval, detections) depending on OpenCV version
            result = detector_yunet.detect(frame)
            # result may be (retval, detections) or just detections
            detections = None
            if isinstance(result, tuple) and len(result) >= 2:
                detections = result[1]
            else:
                detections = result

            if detections is not None and len(detections) > 0:
                for d in detections:
                    # each d: [x,y,w,h, ...landmarks...]
                    x, y, ww, hh = map(int, d[:4])
                    # accept smaller faces as well (but not tiny)
                    if ww >= max(24, int(state.get("min_face_size", 40) * 0.5)) and hh >= max(24, int(state.get("min_face_size", 40) * 0.5)):
                        faces.append((x, y, ww, hh))
                # try extract landmarks from first detection if present
                if detections.shape[1] >= 14:
                    try:
                        landmark_data = detections[0][4:14].reshape(5, 2)
                        landmarks = landmark_data.tolist()
                    except Exception:
                        landmarks = None
            return faces, landmarks
        except Exception as e:
            print("YuNet error (continuing to fallback):", e)

    # --- Caffe SSD fallback ---
    if net_caffe is not None:
        try:
            blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 1.0,
                                         (300, 300), (104.0, 177.0, 123.0))
            net_caffe.setInput(blob)
            detections = net_caffe.forward()
            for i in range(0, detections.shape[2]):
                confidence = float(detections[0, 0, i, 2])
                if confidence > state.get("confidence_threshold", 0.5):
                    box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                    (startX, startY, endX, endY) = box.astype("int")
                    x = max(0, startX)
                    y = max(0, startY)
                    ww = max(0, endX - startX)
                    hh = max(0, endY - startY)
                    # allow more aspect ratios and smaller faces
                    if ww >= max(24, int(state.get("min_face_size", 40) * 0.5)) and hh >= max(24, int(state.get("min_face_size", 40) * 0.5)):
                        faces.append((int(x), int(y), int(ww), int(hh)))
            return faces, None
        except Exception as e:
            print("Caffe error (continuing to Haar):", e)

    # --- Haar Cascade fallback ---
    if face_cascade is not None:
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # loosen params to be more permissive
            haar_faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.05,
                minNeighbors=3,
                minSize=(max(24, int(state.get("min_face_size", 40) * 0.5)), max(24, int(state.get("min_face_size", 40) * 0.5)))
            )
            for (x, y, ww, hh) in haar_faces:
                faces.append((int(x), int(y), int(ww), int(hh)))
            return faces, None
        except Exception as e:
            print("Haar error:", e)

    return [], None


def estimate_head_pose_simple(landmarks, face_rect):
    if landmarks is None or len(landmarks) < 3:
        return 0.0, "Center", 0.0
    try:
        x, y, w, h = face_rect
        right_eye = landmarks[0]
        left_eye = landmarks[1]
        nose = landmarks[2]
        face_center_x = x + w/2
        nose_offset = (nose[0] - face_center_x) / (w/2)
        eye_center_x = (right_eye[0] + left_eye[0])/2
        eye_offset = (eye_center_x - face_center_x) / (w/2)
        combined = (nose_offset + eye_offset) / 2
        if combined < -state["head_pose_threshold"]:
            direction = "Right"
            severity = abs(combined)
        elif combined > state["head_pose_threshold"]:
            direction = "Left"
            severity = abs(combined)
        else:
            direction = "Center"
            severity = 0.0
        return combined*100, direction, severity
    except Exception as e:
        return 0.0, "Center", 0.0

# ========== Flask routes ==========

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/analyze_frame", methods=["POST"])
def analyze_frame():
    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"error":"no image"}), 400
    try:
        frame = b64_to_image(data["image"])
        faces, landmarks = detect_faces_stable(frame)
        head_pose = None
        if faces and landmarks:
            ratio, direction, severity = estimate_head_pose_simple(landmarks, faces[0])
            head_pose = {"ratio": float(ratio), "direction": direction, "severity": float(severity)}
        faces_out = [{"x":int(x),"y":int(y),"w":int(w_),"h":int(h_)} for (x,y,w_,h_) in faces]

        # Log counts for debugging
        fc = len(faces_out)
        log_event("DETECT", f"Detected {fc} face(s)")

        return jsonify({
            "faces": faces_out,
            "face_count": fc,
            "landmarks": landmarks,
            "head_pose": head_pose
        })
    except Exception as e:
        print("analyze_frame error:", e)
        return jsonify({"error":str(e)}), 500

    
@app.route('/questions.json')
def questions():
    return send_from_directory('.', 'questions.json')


@app.route("/voice_event", methods=["POST"])
def voice_event():
    """
    Client sends voice RMS or events:
    { "rms": 0.02, "duration": 1.3, "event": "voice_start"/"voice_stop"/"periodic" }
    """
    payload = request.get_json()
    if not payload:
        return jsonify({"error":"no data"}), 400
    rms = payload.get("rms")
    ev = payload.get("event","periodic")
    dur = payload.get("duration", 0.0)
    try:
        if ev == "voice_start":
            log_event("VOICE", f"Client voice started (rms={rms:.4f})")
        elif ev == "voice_stop":
            log_event("VOICE", f"Client voice stopped (duration={dur:.2f}s)")
            # Check if duration > threshold (client provides duration)
            if dur >= state["voice_alert_duration"]:
                log_event("VOICE_ALERT", f"Voice for {dur:.1f}s")
        else:
            # periodic update
            if rms is not None and rms > state["voice_threshold"]:
                log_event("VOICE", f"RMS {rms:.4f} over threshold")
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/update_params", methods=["POST"])
def update_params():
    payload = request.get_json()
    if not payload:
        return jsonify({"error":"no data"}), 400
    for k in ("head_pose_threshold","head_pose_alert_duration","voice_threshold","voice_alert_duration","multiple_persons_threshold"):
        if k in payload:
            try:
                val = float(payload[k])
                state[k] = val
            except:
                pass
    log_event("PARAM_UPDATE", str(payload))
    return jsonify({"ok":True, "state": state})

@app.route("/get_log")
def get_log():
    if os.path.exists(LOG_FILE):
        return send_from_directory(".", LOG_FILE)
    return "No log yet", 404

# ========== Run server ==========
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)