"""
World model placeholder for the Go2 voice-control system.

Vision / perception is not wired up yet, so the operator describes the space
around the robot by hand (via the web Scene Editor) and we persist it as a list
of objects, each with a *bearing* and *distance* relative to the robot. This lets
the planner turn a high-level request ("I'm hungry, there's an apple behind you")
into an EXECUTABLE orient-and-approach motion instead of refusing outright.

Everything here is an ASSUMED world, not a perceived one. When a real perception
module lands it can emit the same ``{name, bearing_deg, distance_m}`` list and the
planner keeps working unchanged -- the Scene Editor simply becomes a live
visualization of what the robot sees.

Bearing convention: degrees in [-180, 180], measured from the robot's front.
  0   = straight ahead
  +90 = to the robot's right        -90  = to the robot's left
  ±180 = directly behind
"""

import json
import math
from pathlib import Path


# --- Rough motion calibration ----------------------------------------------
# One "pulse" runs robot_controller.move_short for a fixed duration (turns use
# TURN_PULSE_SECONDS, forward uses the shorter FORWARD_PULSE_SECONDS) at the
# controller's fixed speeds. Without odometry the orient/approach is best-effort
# and intentionally coarse; the safety layer still caps each pulse at <= 1 s.
# Tune these against the real Go2.
TURN_PULSE_SECONDS = 1.0
# Forward pulse: 1.0 s at the motion server's raised 0.6 m/s forward speed, so
# each pulse covers ~0.6 m (earlier 0.3-0.5 m steps were too short). M_PER_PULSE
# is an estimate -- re-measure on the robot and adjust if the real distance differs.
FORWARD_PULSE_SECONDS = 1.0
# Calibrated from real-robot observation: a 180-deg ("behind") target planned as
# 4 * 45-deg pulses overshot by ~45 deg, i.e. the Go2 actually yaws ~56 deg per
# 1.0 s turn pulse (momentum + the balance_stand settle before each Move).
DEG_PER_PULSE = 56.0                 # ~225 deg observed over 4 pulses
M_PER_PULSE = 0.55                   # MEASURED: 1.0 s @ 0.6 m/s travels ~0.5-0.6 m on the real robot

MAX_TURN_PULSES = 5                  # up to ~225 deg; any bearing (<=180) reachable
# Forward pulses scale with distance, capped at ~1.8 m of travel (3 * 0.6 m)
# because positions are operator-assumed (no odometry); raise/lower to trade
# reach for caution. Objects farther than this are approached up to the cap.
MAX_FORWARD_PULSES = 3               # up to ~1.8 m

# Obstacle handling (assumed world): a non-target object intruding the straight
# path to the target is detoured around. Clearance ~ obstacle half-width + robot
# half-width. A detour traverses more ground, so it gets a larger forward budget.
CLEAR_RADIUS_M = 0.45
DETOUR_MARGIN_M = 0.25
# A detour side is only acceptable if the WHOLE detour path keeps at least this
# much room from every other object. If neither side clears, the robot stops
# short of the obstacle and reports it (rather than plowing into a second object).
DETOUR_MIN_CLEARANCE_M = 0.35
# An obstacle closer than this is within the robot's own footprint / turn radius;
# there is no room to maneuver around it open-loop, so stop short and report
# instead of attempting a detour that would clip it.
MIN_DETOUR_OBSTACLE_DIST_M = 0.55
MAX_PATH_FORWARD_PULSES = 8          # total forward pulses when a detour is planned (~2.4 m)

# Names that satisfy a generic "food" request.
FOOD_NAMES = {"apple", "banana", "orange", "food", "snack", "treat", "bone"}

DEFAULT_SCENE = {"objects": []}


def load_scene(path) -> dict:
    """Read the persisted scene, returning an empty scene if missing/invalid."""
    p = Path(path)
    if not p.exists():
        return dict(DEFAULT_SCENE)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_SCENE)
    if not isinstance(data, dict) or not isinstance(data.get("objects"), list):
        return dict(DEFAULT_SCENE)
    return data


def _normalize_bearing(bearing: float) -> float:
    return ((float(bearing) + 180.0) % 360.0) - 180.0


def save_scene(path, scene) -> dict:
    """Validate and persist a scene. Canvas coords (x, y) are kept for the UI to
    redraw; bearing_deg / distance_m are what the planner consumes."""
    objects = []
    for obj in (scene or {}).get("objects", []):
        name = str(obj.get("name", "")).strip().lower()
        if not name:
            continue
        try:
            bearing = _normalize_bearing(obj.get("bearing_deg", 0.0))
            distance = max(0.0, float(obj.get("distance_m", 0.0)))
        except (TypeError, ValueError):
            continue
        clean = {
            "id": str(obj.get("id") or name),
            "name": name,
            "bearing_deg": round(bearing, 1),
            "distance_m": round(distance, 2),
        }
        # Preserve canvas position for round-tripping the editor, if provided.
        for k in ("x", "y"):
            if obj.get(k) is not None:
                try:
                    clean[k] = round(float(obj[k]), 2)
                except (TypeError, ValueError):
                    pass
        objects.append(clean)

    result = {"objects": objects}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def resolve_target(scene: dict, target: str):
    """Find the scene object that best matches an intent target name.

    A generic 'food' request matches any food-like object; otherwise match by
    exact name or substring. Returns the NEAREST matching object, or None."""
    target = (target or "").strip().lower()
    if not target:
        return None

    matches = []
    for obj in scene.get("objects", []):
        name = str(obj.get("name", "")).strip().lower()
        if not name:
            continue
        if target in ("food", "something to eat") and name in FOOD_NAMES:
            matches.append(obj)
        elif name == target or target in name or name in target:
            matches.append(obj)

    if not matches:
        return None
    return min(matches, key=lambda o: float(o.get("distance_m", 9e9)))


def bearing_direction(bearing_deg: float) -> str:
    """Human-friendly direction word (robot's own frame) for a bearing."""
    b = _normalize_bearing(bearing_deg)
    a = abs(b)
    if a <= 25:
        return "right ahead"
    if a >= 155:
        return "behind me"
    side = "right" if b > 0 else "left"
    if a <= 90:
        return f"on my {side}"
    return f"behind me on the {side}"


def plan_motion_to(bearing_deg: float, distance_m: float) -> list:
    """Turn to roughly face the bearing, then step forward to approach.

    Returns an ordered list of ``{action, duration}`` pulses, each <= 1 s. Turn
    direction follows the bearing sign; counts are capped for safety because the
    target position is assumed, not measured."""
    b = _normalize_bearing(bearing_deg)
    steps = []

    turn_pulses = min(MAX_TURN_PULSES, round(abs(b) / DEG_PER_PULSE))
    turn_action = "turn_right" if b > 0 else "turn_left"
    for _ in range(int(turn_pulses)):
        steps.append({"action": turn_action, "duration": TURN_PULSE_SECONDS})

    fwd_pulses = min(MAX_FORWARD_PULSES, round(max(0.0, distance_m) / M_PER_PULSE))
    # Take at least one approach step when there is any distance, so the robot
    # visibly moves toward the target even if it is close.
    if distance_m > 0 and fwd_pulses == 0:
        fwd_pulses = 1
    for _ in range(int(fwd_pulses)):
        steps.append({"action": "forward", "duration": FORWARD_PULSE_SECONDS})

    return steps


def _to_xy(bearing_deg, distance_m):
    """Object position in the robot's body frame: x = right, y = forward."""
    a = math.radians(_normalize_bearing(bearing_deg))
    return (distance_m * math.sin(a), distance_m * math.cos(a))


def _segment_distance(p, a, b):
    """Distance from point p to segment a-b, plus the projection parameter t."""
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 1e-9:
        return math.hypot(px - ax, py - ay), 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / l2
    tc = max(0.0, min(1.0, t))
    cx, cy = ax + tc * dx, ay + tc * dy
    return math.hypot(px - cx, py - cy), t


def _find_obstacle(scene, target_obj, target_xy):
    """The nearest non-target object that intrudes the straight path to the target
    (within CLEAR_RADIUS_M of the line, between the endpoints, and closer than the
    target). Returns (object, position_xy) or None."""
    a = (0.0, 0.0)
    target_dist = math.hypot(*target_xy)
    best = None
    for obj in scene.get("objects", []):
        if obj is target_obj:
            continue
        if not str(obj.get("name", "")).strip():
            continue
        p = _to_xy(obj.get("bearing_deg", 0.0), max(0.0, float(obj.get("distance_m", 0.0))))
        dist, t = _segment_distance(p, a, target_xy)
        if dist < CLEAR_RADIUS_M and 0.05 < t < 0.95 and math.hypot(*p) < target_dist:
            if best is None or t < best[1]:
                best = (obj, t, p)
    return (best[0], best[2]) if best else None


def _waypoint_for_side(target_xy, obstacle_xy, side):
    """Waypoint offset perpendicular to the path past the obstacle, on the given
    side (+1 = robot's right, -1 = left), leaving CLEAR_RADIUS_M + margin of room."""
    bx, by = target_xy
    length = math.hypot(bx, by) or 1.0
    dx, dy = bx / length, by / length
    perp = (dy * side, -dx * side)  # +1 -> right of the path, -1 -> left
    off = CLEAR_RADIUS_M + DETOUR_MARGIN_M
    return (obstacle_xy[0] + perp[0] * off, obstacle_xy[1] + perp[1] * off)


def _other_positions(scene, target_obj):
    """Positions (x, y) of every scene object except the target."""
    out = []
    for obj in scene.get("objects", []):
        if obj is target_obj or not str(obj.get("name", "")).strip():
            continue
        out.append(_to_xy(obj.get("bearing_deg", 0.0), max(0.0, float(obj.get("distance_m", 0.0)))))
    return out


def _path_min_clearance(points, obstacles_xy):
    """Smallest distance from any obstacle to any leg of the polyline
    robot(0,0) -> points[0] -> points[1] ... Larger is roomier."""
    if not obstacles_xy:
        return float("inf")
    legs = []
    prev = (0.0, 0.0)
    for p in points:
        legs.append((prev, p))
        prev = p
    best = float("inf")
    for ox in obstacles_xy:
        for a, b in legs:
            d, _ = _segment_distance(ox, a, b)
            best = min(best, d)
    return best


def _path_to_steps(points, max_forward_pulses):
    """Discretize a polyline (robot at origin facing +y) into turn/forward pulses,
    tracking heading so each leg turns relative to the previous one."""
    steps = []
    heading = 0.0  # degrees; 0 = facing forward, + = turned right
    cur = (0.0, 0.0)
    budget = max_forward_pulses
    for p in points:
        dx, dy = p[0] - cur[0], p[1] - cur[1]
        leg = math.hypot(dx, dy)
        if leg < 1e-3:
            continue
        leg_heading = math.degrees(math.atan2(dx, dy))  # 0 = forward, + = right
        delta = _normalize_bearing(leg_heading - heading)
        turn_pulses = min(MAX_TURN_PULSES, round(abs(delta) / DEG_PER_PULSE))
        turn_action = "turn_right" if delta > 0 else "turn_left"
        for _ in range(int(turn_pulses)):
            steps.append({"action": turn_action, "duration": TURN_PULSE_SECONDS})
        if turn_pulses:
            heading = _normalize_bearing(heading + math.copysign(turn_pulses * DEG_PER_PULSE, delta))

        fwd = round(leg / M_PER_PULSE)
        if leg > 0 and fwd == 0:
            fwd = 1
        fwd = min(fwd, budget)
        for _ in range(int(fwd)):
            steps.append({"action": "forward", "duration": FORWARD_PULSE_SECONDS})
        budget -= fwd
        cur = p
        if budget <= 0:
            break
    return steps


def plan_to_object(scene: dict, target: str):
    """Resolve ``target`` in the assumed world and build an orient/approach plan,
    detouring around any object that blocks the straight path.

    Returns a dict with the matched object, its bearing/distance, a direction
    word, the motion ``steps``, and (when relevant) the obstacle that was avoided;
    or None when the target is not in the scene."""
    obj = resolve_target(scene, target)
    if not obj:
        return None
    bearing = _normalize_bearing(obj.get("bearing_deg", 0.0))
    distance = max(0.0, float(obj.get("distance_m", 0.0)))
    target_xy = _to_xy(bearing, distance)

    obstacle = _find_obstacle(scene, obj, target_xy)
    detour = None
    blocked = False
    if not obstacle:
        steps = _path_to_steps([target_xy], MAX_FORWARD_PULSES)
    else:
        obstacle_name = str(obstacle[0].get("name", "object"))
        others = _other_positions(scene, obj)
        # Try detouring around BOTH sides; score each by how much room the whole
        # detour path keeps from every other object, then take the roomier side.
        # This avoids steering the detour straight into a second object.
        candidates = []
        for side in (1, -1):  # +1 = right, -1 = left
            waypoint = _waypoint_for_side(target_xy, obstacle[1], side)
            clearance = _path_min_clearance([waypoint, target_xy], others)
            candidates.append((clearance, side, waypoint))
        candidates.sort(reverse=True)  # best clearance first
        best_clearance, _side, waypoint = candidates[0]

        # Too close to maneuver around, or no clear side: stop short and report.
        too_close = math.hypot(*obstacle[1]) < MIN_DETOUR_OBSTACLE_DIST_M
        if not too_close and best_clearance >= DETOUR_MIN_CLEARANCE_M:
            steps = _path_to_steps([waypoint, target_xy], MAX_PATH_FORWARD_PULSES)
            detour = obstacle_name
        else:
            # Both sides are blocked by other objects: stop short of the obstacle
            # and report, instead of walking into something.
            length = math.hypot(*target_xy) or 1.0
            unit = (target_xy[0] / length, target_xy[1] / length)
            stop_dist = max(0.0, math.hypot(*obstacle[1]) - CLEAR_RADIUS_M)
            stop_xy = (unit[0] * stop_dist, unit[1] * stop_dist)
            steps = _path_to_steps([stop_xy], MAX_FORWARD_PULSES) if stop_dist > 1e-3 else []
            # Always at least orient toward the target so the intent is visible.
            if not steps:
                turn = _path_to_steps([(unit[0] * 0.01, unit[1] * 0.01)], 0)
                steps = turn
            blocked = obstacle_name

    # Note: a fully-blocked target can yield zero steps (nothing safe to do); we
    # still return the plan so the caller can report "blocked" instead of nothing.
    result = {
        "object": str(obj.get("name", "object")),
        "bearing_deg": round(bearing, 1),
        "distance_m": round(distance, 2),
        "direction": bearing_direction(bearing),
        "steps": steps,
    }
    if detour:
        result["detour"] = detour
    if blocked:
        result["blocked_by"] = blocked
    return result
