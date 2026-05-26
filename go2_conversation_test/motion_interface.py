import sys
from pathlib import Path


ACTION_TO_COMMAND = {
    "stop": "stop",
    "stand": "stand_up",
    "sit": "stand_down",
    "forward": "forward",
    "backward": "backward",
    "turn_left": "turn_left",
    "turn_right": "turn_right",
}

MOVEMENT_COMMANDS = {
    "forward",
    "backward",
    "turn_left",
    "turn_right",
}


def clamp_motion_duration(duration):
    if duration is None:
        return 1.0

    return max(0.3, min(float(duration), 2.0))


def create_robot_controller(network_interface):
    repo_root = Path(__file__).resolve().parents[1]
    sdk_dir = repo_root / "unitree_sdk2_python"

    if str(sdk_dir) not in sys.path:
        sys.path.insert(0, str(sdk_dir))

    from robot_controller import RobotController

    return RobotController(network_interface)


def execute_motion(intent_info, robot=None):
    """
    Bridge recognized motion intent to either dry-run output or the real robot.
    """

    action = intent_info.get("action")
    speed = intent_info.get("speed")
    duration = intent_info.get("duration")
    safe_to_attempt = intent_info.get("safe_to_attempt", False)
    command = ACTION_TO_COMMAND.get(action)

    if not safe_to_attempt:
        return {
            "executed": False,
            "reason": "Motion command was blocked because it is unsafe.",
            "action": action,
            "speed": speed,
            "duration": duration,
        }

    if command is None:
        return {
            "executed": False,
            "reason": "This motion is recognized, but no real robot command is mapped yet.",
            "action": action,
            "speed": speed,
            "duration": duration,
        }

    if robot is None:
        print("\n[DRY RUN MOTION INTERFACE]")
        print(f"Received action: {action}")
        print(f"Mapped robot command: {command}")
        print(f"Received speed: {speed}")
        print(f"Received duration: {duration}")
        print("No real robot command was sent.")
        print("[END DRY RUN MOTION INTERFACE]\n")

        return {
            "executed": False,
            "reason": "Dry run mode: motion command was recognized but not sent to the robot.",
            "action": action,
            "command": command,
            "speed": speed,
            "duration": duration,
        }

    print("\n[REAL MOTION INTERFACE]")
    print(f"Received action: {action}")
    print(f"Mapped robot command: {command}")
    print(f"Received speed: {speed}")
    print(f"Received duration: {duration}")
    if command in MOVEMENT_COMMANDS:
        ret = robot.execute_command(command, duration=clamp_motion_duration(duration))
    else:
        ret = robot.execute_command(command)
    print("[END REAL MOTION INTERFACE]\n")

    executed = ret == 0

    return {
        "executed": executed,
        "reason": (
            "Motion command was accepted by the robot."
            if executed
            else f"Robot command failed or timed out. Return code: {ret}"
        ),
        "action": action,
        "command": command,
        "speed": speed,
        "duration": duration,
        "robot_return_code": ret,
    }
