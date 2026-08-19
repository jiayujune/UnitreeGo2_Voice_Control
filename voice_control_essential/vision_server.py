"""
Vision server for the Go2 — face detection, identification, and face-tracking (port 8002).

Reads camera frames from the robot's own camera via ROS2 topic /go2_camera/color/image,
so the robot tracks faces from its own perspective.

Requires the ROS2 driver (robot_minimal.launch.py) to be running first.

Launch:
    source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash
    cd ~/go2/voice_control_essential
    python3 -m uvicorn vision_server:app --host 0.0.0.0 --port 8002

Env vars:
    GO2_MOTION_URL    motion server URL          (default http://localhost:8003/move)
    VISION_ENROLL_DIR directory for embeddings    (default <repo>/runtime/enrolled_faces)
    VISION_CMD_VEL    ROS2 cmd_vel topic          (default /cmd_vel_out)
    VISION_CAM_TOPIC  ROS2 camera topic           (default /go2_camera/color/image)

Endpoints:
    GET  /health          status, enrolled names, tracking state
    GET  /detect          one-shot detect + identify faces in current frame
    POST /track           start tracking  body: {"name": "alice" | null}
    POST /track/stop      stop tracking
    POST /enroll          register a face body: {"name": "alice", "image_b64": "<base64 JPEG/PNG>"}
    DELETE /enroll/{name} remove an enrolled person
"""

import base64
import io
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Image as RosImage
from facenet_pytorch import MTCNN, InceptionResnetV1
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MOTION_URL    = os.getenv("GO2_MOTION_URL",   "http://localhost:8003/move")
ENROLL_DIR    = Path(os.getenv("VISION_ENROLL_DIR",
    str(Path(__file__).resolve().parents[1] / "runtime" / "enrolled_faces")))
CMD_VEL_TOPIC = os.getenv("VISION_CMD_VEL",   "/cmd_vel_out")
CAM_TOPIC     = os.getenv("VISION_CAM_TOPIC", "/camera/image_raw")

DEVICE = "cpu"  # force CPU — GPU occupied by training

IDENTIFY_THRESHOLD = 0.60
DETECT_CONFIDENCE  = 0.90
TRACK_PULSE        = 0.30
SEARCH_PULSE       = 0.35
CENTER_BAND        = 0.25
MAX_SEARCH_TURNS   = 10


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
_mtcnn  = MTCNN(keep_all=True, device=DEVICE, min_face_size=40,
                thresholds=[0.6, 0.7, 0.7], post_process=False)
_resnet = InceptionResnetV1(pretrained="vggface2").eval().to(DEVICE)


# ---------------------------------------------------------------------------
# Enrolled faces
# ---------------------------------------------------------------------------
_enrolled: dict[str, torch.Tensor] = {}
_enrolled_lock = threading.Lock()


def _load_enrolled_from_disk() -> None:
    ENROLL_DIR.mkdir(parents=True, exist_ok=True)
    for npy in ENROLL_DIR.glob("*.npy"):
        _enrolled[npy.stem] = torch.from_numpy(np.load(str(npy))).float()


_load_enrolled_from_disk()


# ---------------------------------------------------------------------------
# ROS2 node — camera subscriber + cmd_vel publisher
# ---------------------------------------------------------------------------
class VisionNode(Node):
    def __init__(self):
        super().__init__("go2_vision_server")
        self._latest_frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()

        cam_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self._cam_sub = self.create_subscription(
            RosImage, CAM_TOPIC, self._on_image, cam_qos)
        self._cmd_pub = self.create_publisher(Twist, CMD_VEL_TOPIC, 10)
        self.get_logger().info(f"Subscribed to {CAM_TOPIC}, publishing to {CMD_VEL_TOPIC}")

    def _on_image(self, msg: RosImage):
        arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(
            (msg.height, msg.width, -1))
        # Convert BGR→RGB if needed
        if msg.encoding.lower() in ("bgr8", "bgr"):
            arr = arr[:, :, ::-1].copy()
        with self._frame_lock:
            self._latest_frame = arr

    def get_frame(self) -> np.ndarray | None:
        with self._frame_lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    def publish_twist(self, vx: float, vy: float, vyaw: float, duration: float):
        msg = Twist()
        msg.linear.x  = float(vx)
        msg.linear.y  = float(vy)
        msg.angular.z = float(vyaw)
        interval = 0.05
        end = time.monotonic() + duration
        while time.monotonic() < end:
            self._cmd_pub.publish(msg)
            time.sleep(interval)
        self._cmd_pub.publish(Twist())   # stop

    def stop(self):
        self._cmd_pub.publish(Twist())


_ros_node: VisionNode | None = None
_ros_lock = threading.Lock()


def _ros_spin():
    rclpy.init()
    global _ros_node
    _ros_node = VisionNode()
    rclpy.spin(_ros_node)


threading.Thread(target=_ros_spin, daemon=True).start()
for _ in range(50):
    if _ros_node is not None:
        break
    time.sleep(0.1)


# ---------------------------------------------------------------------------
# Embedding + identification
# ---------------------------------------------------------------------------
def _embedding_for(face_crop: Image.Image) -> torch.Tensor:
    img = face_crop.convert("RGB").resize((160, 160))
    t = torch.from_numpy(np.array(img)).float().permute(2, 0, 1).unsqueeze(0)
    t = (t - 127.5) / 128.0
    with torch.no_grad():
        emb = _resnet(t.to(DEVICE))
    return F.normalize(emb.squeeze(0), dim=0).cpu()


def _best_match(emb: torch.Tensor) -> tuple[str | None, float]:
    with _enrolled_lock:
        if not _enrolled:
            return None, 0.0
        best_name, best_sim = None, 0.0
        emb_gpu = emb.to(DEVICE)
        for name, ref in _enrolled.items():
            sim = F.cosine_similarity(
                emb_gpu.unsqueeze(0), ref.to(DEVICE).unsqueeze(0)).item()
            if sim > best_sim:
                best_sim, best_name = sim, name
    return (best_name, best_sim) if best_sim >= IDENTIFY_THRESHOLD else (None, best_sim)


# ---------------------------------------------------------------------------
# Frame analysis
# ---------------------------------------------------------------------------
def detect_frame(frame: np.ndarray) -> list[dict]:
    pil = Image.fromarray(frame)
    boxes, probs = _mtcnn.detect(pil)
    if boxes is None:
        return []
    h, w = frame.shape[:2]
    results = []
    for box, prob in zip(boxes, probs):
        if prob is None or float(prob) < DETECT_CONFIDENCE:
            continue
        x1, y1, x2, y2 = (max(0, int(v)) for v in box)
        emb  = _embedding_for(pil.crop((x1, y1, x2, y2)))
        name, sim = _best_match(emb)
        cx = (x1 + x2) / 2
        results.append({
            "box":        [x1, y1, x2 - x1, y2 - y1],
            "confidence": round(float(prob), 3),
            "name":       name,
            "similarity": round(float(sim), 3),
            "position":   "left" if cx < w / 3 else ("right" if cx > 2 * w / 3 else "center"),
            "center_x":   round(cx / w, 3),
        })
    return results


# ---------------------------------------------------------------------------
# Tracking thread
# ---------------------------------------------------------------------------
_track_state = {"active": False, "target": None, "status": "idle", "last_seen": None}
_track_lock  = threading.Lock()
_track_thread: threading.Thread | None = None


def _tracking_loop():
    search_count = 0
    while True:
        with _track_lock:
            if not _track_state["active"]:
                _track_state["status"] = "idle"
                return
            target = _track_state["target"]

        frame = _ros_node.get_frame() if _ros_node else None
        if frame is None:
            time.sleep(0.1)
            continue

        faces = detect_frame(frame)
        target_face = None
        if target:
            for f in faces:
                if f.get("name") == target:
                    target_face = f
                    break
        elif faces:
            target_face = faces[0]

        if target_face:
            search_count = 0
            cx = target_face["center_x"]
            with _track_lock:
                _track_state["status"]    = "tracking"
                _track_state["last_seen"] = target_face.get("name")

            if cx < 0.5 - CENTER_BAND / 2:
                _ros_node.publish_twist(0.0, 0.0, 0.5, TRACK_PULSE)
            elif cx > 0.5 + CENTER_BAND / 2:
                _ros_node.publish_twist(0.0, 0.0, -0.5, TRACK_PULSE)
            else:
                time.sleep(0.15)
        else:
            search_count += 1
            with _track_lock:
                _track_state["status"] = "searching"
            if search_count > MAX_SEARCH_TURNS:
                with _track_lock:
                    _track_state["active"] = False
                    _track_state["status"] = "idle"
                return
            _ros_node.publish_twist(0.0, 0.0, -0.5, SEARCH_PULSE)


def _start_tracking(target: str | None):
    global _track_thread
    with _track_lock:
        _track_state.update({"active": True, "target": target, "status": "tracking"})
    if _track_thread is None or not _track_thread.is_alive():
        _track_thread = threading.Thread(target=_tracking_loop, daemon=True)
        _track_thread.start()


def _stop_tracking():
    with _track_lock:
        _track_state.update({"active": False, "status": "idle"})


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
app = FastAPI(title="Go2 Vision Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

VR_HTML = Path(__file__).parent / "vr_controller.html"


@app.get("/vr")
def vr_page():
    return FileResponse(VR_HTML, media_type="text/html")


class TrackRequest(BaseModel):
    name: str | None = None


class EnrollRequest(BaseModel):
    name: str
    image_b64: str


_SHM_CAM = "/dev/shm/go2_cam.jpg"

def _mjpeg_generator():
    """Serve MJPEG directly from FFmpeg JPEG output (shared memory file).
    Bypasses ROS2 to eliminate serialization latency and duplicate-frame flicker."""
    last_mtime = 0.0
    while True:
        try:
            mtime = os.path.getmtime(_SHM_CAM)
            if mtime <= last_mtime:
                time.sleep(0.008)
                continue
            with open(_SHM_CAM, "rb") as f:
                jpeg = f.read()
            last_mtime = mtime
        except (FileNotFoundError, OSError):
            time.sleep(0.05)
            continue
        if not jpeg:
            time.sleep(0.05)
            continue
        header = (
            b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
            + str(len(jpeg)).encode()
            + b"\r\n\r\n"
        )
        yield header + jpeg + b"\r\n"


@app.get("/video_feed")
def video_feed():
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/health")
def health():
    with _track_lock:
        state = dict(_track_state)
    with _enrolled_lock:
        enrolled = list(_enrolled.keys())
    frame = _ros_node.get_frame() if _ros_node else None
    return {
        "ok":       True,
        "device":   DEVICE,
        "camera":   "connected" if frame is not None else "waiting for frames",
        "enrolled": enrolled,
        "tracking": state,
    }


@app.get("/detect")
def detect():
    if _ros_node is None:
        raise HTTPException(status_code=503, detail="ROS2 node not ready.")
    frame = _ros_node.get_frame()
    if frame is None:
        raise HTTPException(status_code=503, detail="No camera frame yet. Is the ROS2 driver running?")
    h, w = frame.shape[:2]
    return {"faces": detect_frame(frame), "frame_shape": [h, w]}


@app.post("/track")
def start_track(req: TrackRequest):
    target = (req.name or "").strip().lower() or None
    if target:
        with _enrolled_lock:
            if target not in _enrolled:
                raise HTTPException(
                    status_code=404,
                    detail=f"'{target}' is not enrolled. Use POST /enroll first.")
    _start_tracking(target)
    return {"ok": True, "tracking": target or "any face"}


@app.post("/track/stop")
def stop_track():
    _stop_tracking()
    if _ros_node:
        _ros_node.stop()
    return {"ok": True}


@app.post("/enroll")
def enroll(req: EnrollRequest):
    name = req.name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        img = Image.open(io.BytesIO(base64.b64decode(req.image_b64))).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image: {exc}") from exc

    boxes, probs = _mtcnn.detect(img)
    if boxes is None or len(boxes) == 0:
        raise HTTPException(status_code=422, detail="No face detected in the provided image.")

    best = int(np.argmax(probs))
    x1, y1, x2, y2 = (max(0, int(v)) for v in boxes[best])
    emb = _embedding_for(img.crop((x1, y1, x2, y2)))

    ENROLL_DIR.mkdir(parents=True, exist_ok=True)
    np.save(str(ENROLL_DIR / f"{name}.npy"), emb.numpy())
    with _enrolled_lock:
        _enrolled[name] = emb
    return {"ok": True, "name": name}


@app.delete("/enroll/{name}")
def remove_enrolled(name: str):
    name = name.strip().lower()
    with _enrolled_lock:
        if name not in _enrolled:
            raise HTTPException(status_code=404, detail=f"'{name}' is not enrolled.")
        del _enrolled[name]
    npy = ENROLL_DIR / f"{name}.npy"
    if npy.exists():
        npy.unlink()
    return {"ok": True, "removed": name}
