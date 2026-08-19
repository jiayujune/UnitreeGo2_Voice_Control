"""
ROS2 motion server for Go2 Air (runs on the laptop, port 8001).

Drop-in replacement for robot_motion_server.py for robots that use go2_ros2_sdk
instead of the Unitree SDK2 directly (e.g. Go2 Air via WebRTC).

Accepts the same HTTP POST /move interface as the original motion server, but
publishes geometry_msgs/Twist to /cmd_vel_out instead of calling SportClient.

Launch alongside the ROS2 driver:
    # Terminal 1
    source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash
    export CONN_TYPE=webrtc ROBOT_IP=192.168.12.1
    ros2 launch go2_robot_sdk robot_minimal.launch.py

    # Terminal 2
    source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash
    cd ~/go2/voice_control_essential
    python3 robot_motion_server_ros2.py

Then point the web backend at localhost:
    export GO2_MOTION_URL=http://localhost:8001/move
    export GO2_EXECUTE=1
"""

import threading
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# ---------------------------------------------------------------------------
# Velocity vectors (same values as robot_motion_server.py)
# ---------------------------------------------------------------------------
MOVE_VECTORS = {
    "forward":    ( 0.3, 0.0,  0.0),
    "backward":   (-0.3, 0.0,  0.0),
    "turn_left":  ( 0.0, 0.0,  0.7),
    "turn_right": ( 0.0, 0.0, -0.7),
}
POSTURE_ACTIONS = {"stop", "balance", "stand_up", "stand_down", "recovery"}

DEFAULT_DURATION = 0.6
MAX_DURATION = 1.0
CMD_VEL_TOPIC = "/cmd_vel_out"
PUBLISH_HZ = 20


def clamp_duration(d):
    try:
        d = float(d)
    except (TypeError, ValueError):
        d = DEFAULT_DURATION
    return max(0.1, min(d if d > 0 else DEFAULT_DURATION, MAX_DURATION))


# ---------------------------------------------------------------------------
# Async velocity state — HTTP requests update this and return immediately.
# A background loop publishes at PUBLISH_HZ; no request ever blocks.
# ---------------------------------------------------------------------------
_cmd_lock = threading.Lock()
_cmd = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0, "stop_at": 0.0}


def _set_velocity(vx: float, vy: float, vyaw: float, duration: float):
    with _cmd_lock:
        _cmd["vx"] = vx
        _cmd["vy"] = vy
        _cmd["vyaw"] = vyaw
        _cmd["stop_at"] = time.monotonic() + duration


def _clear_velocity():
    with _cmd_lock:
        _cmd["vx"] = _cmd["vy"] = _cmd["vyaw"] = 0.0
        _cmd["stop_at"] = 0.0


# ---------------------------------------------------------------------------
# ROS2 publisher node (runs in a background thread)
# ---------------------------------------------------------------------------
class Go2ROS2Node(Node):
    def __init__(self):
        super().__init__("go2_motion_server")
        self._pub = self.create_publisher(Twist, CMD_VEL_TOPIC, 10)
        self.get_logger().info(f"Publishing to {CMD_VEL_TOPIC}")

    def publish_current(self):
        with _cmd_lock:
            now = time.monotonic()
            if now < _cmd["stop_at"]:
                vx, vy, vyaw = _cmd["vx"], _cmd["vy"], _cmd["vyaw"]
            else:
                vx = vy = vyaw = 0.0
        msg = Twist()
        msg.linear.x = vx
        msg.linear.y = vy
        msg.angular.z = vyaw
        self._pub.publish(msg)

    def stop(self):
        _clear_velocity()
        self._pub.publish(Twist())


# Shared node
_node: Go2ROS2Node | None = None


def _ros2_spin_thread():
    rclpy.init()
    global _node
    _node = Go2ROS2Node()
    rclpy.spin(_node)


def _publish_loop():
    interval = 1.0 / PUBLISH_HZ
    while True:
        if _node is not None:
            _node.publish_current()
        time.sleep(interval)


threading.Thread(target=_ros2_spin_thread, daemon=True).start()
threading.Thread(target=_publish_loop, daemon=True).start()

# Wait for node to initialise
for _ in range(50):
    if _node is not None:
        break
    time.sleep(0.1)

# ---------------------------------------------------------------------------
# FastAPI — same interface as robot_motion_server.py
# ---------------------------------------------------------------------------
app = FastAPI(title="Go2 ROS2 Motion Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class MoveRequest(BaseModel):
    action: str = Field(..., min_length=1)
    duration: float = DEFAULT_DURATION
    iface: str = "webrtc"


@app.get("/health")
def health():
    return {"ok": True, "backend": "ros2", "topic": CMD_VEL_TOPIC}


@app.post("/move")
def move(req: MoveRequest):
    action = req.action

    if action not in MOVE_VECTORS and action not in POSTURE_ACTIONS:
        return {"ok": False, "error": f"Unknown action '{action}'."}

    if _node is None:
        return {"ok": False, "error": "ROS2 node not ready."}

    if action in MOVE_VECTORS:
        vx, vy, vyaw = MOVE_VECTORS[action]
        duration = clamp_duration(req.duration)
        _set_velocity(vx, vy, vyaw, duration)
        return {"ok": True, "action": action, "duration": round(duration, 2)}

    if action == "stop":
        _node.stop()
        return {"ok": True, "action": "stop"}

    # stand_up / stand_down / balance / recovery not yet mapped via /cmd_vel
    _node.get_logger().warn(f"Posture action '{action}' not implemented in ROS2 mode.")
    return {"ok": True, "action": action, "note": "Posture commands not yet mapped in ROS2 mode."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)
