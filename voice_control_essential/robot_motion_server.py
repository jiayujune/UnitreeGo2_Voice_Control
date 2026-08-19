"""
Persistent motion server for the Go2 (runs ON the robot, port 8001).

Why this exists: the web backend used to SSH in and run robot_command_once.py for
every single pulse, which re-initialized the whole SDK (ChannelFactoryInitialize +
SportClient.Init, ~1-1.5 s) and re-balanced + settled (~0.5 s) on EVERY step. For a
multi-step sequence that overhead dominated the wall-clock and caused the large
gaps between actions.

This server initializes the SDK ONCE at startup and holds a single SportClient
alive. It also balances only once across a run of consecutive moves (StopMove
keeps the robot in balance-stand, so the next move skips the re-balance + settle).
That removes the two biggest per-step costs.

Mirrors the existing robot_speaker_server (FastAPI on a robot port). Launch under
the SDK venv with the CycloneDDS env exported, e.g.:

    export CYCLONEDDS_HOME=/home/unitree/cyclonedds_ws/install/cyclonedds
    export LD_LIBRARY_PATH=$CYCLONEDDS_HOME/lib:$LD_LIBRARY_PATH
    /home/unitree/go2_sdk_venv/bin/uvicorn robot_motion_server:app --host 0.0.0.0 --port 8001
"""

import threading
import time

from fastapi import FastAPI
from pydantic import BaseModel, Field

from robot_controller import RobotController


DEFAULT_IFACE = "eth0"
MOVE_REFRESH_INTERVAL = 0.05          # 20 Hz, same watchdog refresh as move_short
BALANCE_SETTLE_SECONDS = 0.4          # only paid once per run of consecutive moves
MAX_MOVEMENT_DURATION_SECONDS = 1.0
DEFAULT_MOVEMENT_DURATION_SECONDS = 0.8


def clamp_movement_duration(duration):
    """Cap a movement duration to the safe range. Defined locally so the server
    does not depend on the robot's (older) robot_controller having this helper."""
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = DEFAULT_MOVEMENT_DURATION_SECONDS
    if duration <= 0:
        duration = DEFAULT_MOVEMENT_DURATION_SECONDS
    return max(0.1, min(duration, MAX_MOVEMENT_DURATION_SECONDS))

# Velocity vectors per movement action. Forward/backward speed raised to 0.6 m/s
# (from 0.3) so each pulse covers a more useful distance; turn rate unchanged.
MOVE_VECTORS = {
    "forward": (0.6, 0.0, 0.0),
    "backward": (-0.6, 0.0, 0.0),
    "turn_left": (0.0, 0.0, 0.7),
    "turn_right": (0.0, 0.0, -0.7),
}
POSTURE_ACTIONS = {"stop", "balance", "stand_up", "stand_down", "recovery"}

app = FastAPI(title="Go2 Motion Server")

# Single long-lived SDK client + a lock so overlapping requests never interleave
# Move() calls. _balanced tracks whether the robot is already in balance-stand so
# a run of consecutive moves balances + settles only once.
_state = {"controller": None, "balanced": False, "iface": DEFAULT_IFACE}
_lock = threading.Lock()


class MoveRequest(BaseModel):
    action: str = Field(..., min_length=1)
    duration: float = 0.0
    iface: str = DEFAULT_IFACE


def _get_controller(iface: str) -> RobotController:
    """Initialize the SDK once and reuse the client for every later request."""
    if _state["controller"] is None:
        _state["iface"] = iface
        _state["controller"] = RobotController(iface)   # ChannelFactoryInitialize + Init
    return _state["controller"]


@app.get("/health")
def health():
    return {"ok": True, "initialized": _state["controller"] is not None, "balanced": _state["balanced"]}


@app.post("/move")
def move(req: MoveRequest):
    action = req.action

    if action not in MOVE_VECTORS and action not in POSTURE_ACTIONS:
        return {"ok": False, "error": f"Unknown action '{action}'."}

    with _lock:
        try:
            controller = _get_controller(req.iface)
            sport = controller.sport_client

            if action in MOVE_VECTORS:
                # Balance + settle only when not already balanced (i.e. the first
                # move of a run). Consecutive moves skip this -- the big win.
                if not _state["balanced"]:
                    sport.BalanceStand()
                    time.sleep(BALANCE_SETTLE_SECONDS)
                    _state["balanced"] = True

                vx, vy, vyaw = MOVE_VECTORS[action]
                duration = clamp_movement_duration(req.duration)
                end = time.monotonic() + duration
                ret = 0
                while time.monotonic() < end:
                    ret = sport.Move(vx, vy, vyaw)
                    time.sleep(MOVE_REFRESH_INTERVAL)
                sport.StopMove()   # stops motion but stays in balance-stand
                return {"ok": ret == 0, "action": action, "ret": ret, "duration": round(duration, 2)}

            # Posture commands change stance, so the next move must re-balance.
            _state["balanced"] = False
            controller.execute_command(action)
            return {"ok": True, "action": action}

        except Exception as exc:  # noqa: BLE001 - surface any SDK error to the caller
            return {"ok": False, "action": action, "error": str(exc)}
