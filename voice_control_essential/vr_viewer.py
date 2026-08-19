#!/usr/bin/env python3
"""
Go2 VR Viewer — streams robot camera into VIVE headset via SteamVR overlay.

Requires:
  - SteamVR running
  - ROS2 driver running (writes /dev/shm/go2_cam.jpg)
  - motion server on :8003  (python3 robot_motion_server_ros2.py)

Run:
  python3 vr_viewer.py
"""

import io
import json
import os
import sys
import termios
import tty
import time
import threading
import urllib.request

from PIL import Image
import openvr

MOTION_URL    = "http://localhost:8003/move"
SHM_CAM       = "/dev/shm/go2_cam.jpg"   # written atomically by go2_driver_node
VR_PNG        = "/dev/shm/go2_vr.png"    # converted PNG for setOverlayFromFile
OVERLAY_KEY   = "go2.camera.overlay"
OVERLAY_TITLE = "Go2 Camera"
OVERLAY_WIDTH = 2.5   # metres wide
OVERLAY_DIST  = -1.8  # metres in front of HMD

MOVE_DURATION = 0.5
HTTP_TIMEOUT  = 1.0


# ── OpenVR init ──────────────────────────────────────────────────────────────
print("[VR] Initialising SteamVR overlay...")
openvr.init(openvr.VRApplication_Overlay)
vr_sys = openvr.VRSystem()
vr_ovr = openvr.IVROverlay()

_overlay_transform = openvr.HmdMatrix34_t()
_overlay_transform[0][0] = 1;  _overlay_transform[0][3] = 0.0
_overlay_transform[1][1] = 1;  _overlay_transform[1][3] = 0.0
_overlay_transform[2][2] = 1;  _overlay_transform[2][3] = OVERLAY_DIST


def _create_overlay() -> int:
    try:
        stale = vr_ovr.findOverlay(OVERLAY_KEY)
        h = stale[1] if isinstance(stale, tuple) else stale
        if h:
            vr_ovr.destroyOverlay(h)
    except Exception:
        pass
    result = vr_ovr.createOverlay(OVERLAY_KEY, OVERLAY_TITLE)
    h = result[1] if isinstance(result, tuple) else result
    vr_ovr.setOverlayWidthInMeters(h, OVERLAY_WIDTH)
    vr_ovr.setOverlayTransformTrackedDeviceRelative(
        h, openvr.k_unTrackedDeviceIndex_Hmd, _overlay_transform)
    vr_ovr.setOverlayAlpha(h, 1.0)
    vr_ovr.showOverlay(h)
    return h


handle = _create_overlay()
print(f"[VR] Overlay ready — {OVERLAY_WIDTH}m wide, {abs(OVERLAY_DIST)}m in front")

# Diagnose controller status at startup
for _idx in range(openvr.k_unMaxTrackedDeviceCount):
    if vr_sys.getTrackedDeviceClass(_idx) != openvr.TrackedDeviceClass_Controller:
        continue
    try:
        batt = vr_sys.getFloatTrackedDeviceProperty(
            _idx, openvr.Prop_DeviceBatteryPercentage_Float)
        connected = vr_sys.getBoolTrackedDeviceProperty(
            _idx, openvr.Prop_DeviceIsCharging_Bool)
        print(f"[VR] Controller {_idx}: battery={batt*100:.0f}% charging={connected}")
    except Exception as _e:
        print(f"[VR] Controller {_idx}: could not read battery ({_e})")

# ── Startup test: show a red rectangle to verify overlay is working ──────────
_TEST_PNG = "/dev/shm/go2_vr_test.png"
try:
    test_img = Image.new("RGB", (640, 360), color=(255, 0, 0))
    test_img.save(_TEST_PNG, "PNG")
    vr_ovr.setOverlayFromFile(handle, _TEST_PNG)
    print("[VR] Test image displayed — you should see a RED rectangle in headset")
    print("[VR] If headset is black, check SteamVR is running and headset is worn")
except Exception as e:
    print(f"[VR] Test image failed: {repr(e)}")


# ── Robot motion ─────────────────────────────────────────────────────────────
_last_action   = ""
_last_action_t = 0.0
_moving        = False


def _send(action: str):
    global _last_action, _last_action_t
    now = time.time()
    if action == _last_action and now - _last_action_t < 0.45:
        return
    _last_action, _last_action_t = action, now
    print(f"[Move] → {action}")

    def _do():
        try:
            body = json.dumps({"action": action, "duration": MOVE_DURATION}).encode()
            req  = urllib.request.Request(
                MOTION_URL, data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
        except Exception as e:
            print(f"[Move] error: {type(e).__name__}: {e}")

    threading.Thread(target=_do, daemon=True).start()


TRACKPAD_BTN   = openvr.k_EButton_SteamVR_Touchpad
TRIGGER_THRESH = 0.5


_debug_poll_count = 0

def _poll_controllers():
    global _moving, _debug_poll_count
    moved = False
    for idx in range(openvr.k_unMaxTrackedDeviceCount):
        if vr_sys.getTrackedDeviceClass(idx) != openvr.TrackedDeviceClass_Controller:
            continue
        ok, state = vr_sys.getControllerState(idx)
        if not ok:
            continue
        touched = bool(state.ulButtonTouched & (1 << TRACKPAD_BTN))
        pressed = bool(state.ulButtonPressed & (1 << TRACKPAD_BTN))
        trigger = state.rAxis[1].x
        x = state.rAxis[0].x
        y = state.rAxis[0].y
        _debug_poll_count += 1
        if _debug_poll_count % 60 == 1 or touched or pressed or abs(x) > 0.05 or abs(y) > 0.05:
            axes = [(round(state.rAxis[i].x, 2), round(state.rAxis[i].y, 2)) for i in range(5)]
            print(f"[Ctrl {idx}] btnT={state.ulButtonTouched} btnP={state.ulButtonPressed} "
                  f"trigger={trigger:.2f} axes={axes}")
        if not (touched or pressed or trigger > TRIGGER_THRESH):
            continue
        if abs(x) < 0.25 and abs(y) < 0.25:
            continue
        moved = True
        if abs(y) >= abs(x):
            _send("forward" if y > 0 else "backward")
        else:
            _send("turn_left" if x < 0 else "turn_right")
    if not moved and _moving:
        _send("stop")
    _moving = moved


# ── Keyboard fallback ────────────────────────────────────────────────────────
def _keyboard_thread():
    """WASD / arrow keys → robot motion. For testing when controller is unreliable."""
    KEY_MAP = {
        "w": "forward", "W": "forward",
        "s": "backward", "S": "backward",
        "a": "turn_left", "A": "turn_left",
        "d": "turn_right", "D": "turn_right",
        " ": "stop",
    }
    try:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        tty.setraw(fd)
        print("\n[KB] Keyboard active: W/S/A/D = forward/back/left/right, Space = stop")
        while True:
            ch = sys.stdin.read(1)
            if ch == "\x03":   # Ctrl+C
                break
            if ch in KEY_MAP:
                _send(KEY_MAP[ch])
    except Exception as e:
        print(f"[KB] keyboard thread error: {e}")
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass

threading.Thread(target=_keyboard_thread, daemon=True).start()

# ── Main loop ────────────────────────────────────────────────────────────────
print(f"[VR] Reading camera from {SHM_CAM}")
print("[VR] VIVE trackpad OR keyboard W/S/A/D to move. Ctrl+C to exit.")

_last_mtime    = 0.0
_overlay_errors = 0
_frame_count   = 0
_status_t      = time.time()

try:
    while True:
        # Push new JPEG frame to overlay whenever file changes
        try:
            mtime = os.path.getmtime(SHM_CAM)
            if mtime > _last_mtime:
                _last_mtime = mtime
                _frame_count += 1
                if _frame_count <= 3:
                    print(f"[Camera] frame #{_frame_count}")
                try:
                    # Convert JPEG → PNG at half resolution (SteamVR loads faster)
                    with open(SHM_CAM, "rb") as f:
                        raw = f.read()
                    img = Image.open(io.BytesIO(raw))
                    img = img.resize((640, 360), Image.BILINEAR)
                    img.save(VR_PNG, "PNG", compress_level=1)
                    png_size = os.path.getsize(VR_PNG)
                    if _frame_count <= 3:
                        print(f"[Camera] PNG {img.width}x{img.height} "
                              f"mode={img.mode} {png_size//1024}KB")
                    vr_ovr.setOverlayFromFile(handle, VR_PNG)
                    vr_ovr.setOverlayAlpha(handle, 1.0)
                    if _overlay_errors > 0:
                        print(f"[VR] overlay recovered after {_overlay_errors} errors")
                        _overlay_errors = 0
                except Exception as e:
                    _overlay_errors += 1
                    if _overlay_errors <= 3 or _overlay_errors % 30 == 0:
                        print(f"[VR] overlay error #{_overlay_errors}: "
                              f"{type(e).__name__}: {repr(e)}")
                    if _overlay_errors % 60 == 0:
                        print("[VR] Recreating overlay...")
                        try:
                            handle = _create_overlay()
                            print("[VR] Overlay recreated")
                        except Exception as e2:
                            print(f"[VR] Recreate failed: {repr(e2)}")
        except (FileNotFoundError, OSError):
            pass  # driver not running yet

        now = time.time()
        if now - _status_t > 10.0:
            _status_t = now
            if _frame_count == 0:
                print("[Camera] waiting for frames — is go2_driver_node running?")

        try:
            _poll_controllers()
        except Exception as e:
            print(f"[Ctrl] error: {type(e).__name__}: {e}")
        time.sleep(0.033)

except KeyboardInterrupt:
    print("\n[VR] Exiting...")
finally:
    _send("stop")
    try:
        vr_ovr.destroyOverlay(handle)
    except Exception:
        pass
    openvr.shutdown()
