import sys

from robot_controller import RobotController, clamp_movement_duration


MOVEMENT_COMMANDS = {
    "forward",
    "backward",
    "turn_left",
    "turn_right",
}


def parse_duration(raw_duration):
    if raw_duration is None:
        return None

    try:
        return clamp_movement_duration(float(raw_duration))
    except ValueError:
        return None


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 robot_command_once.py networkInterface command [duration]")
        print("Example: python3 robot_command_once.py eth0 forward 0.8")
        return

    network_interface = sys.argv[1]
    command = sys.argv[2]
    duration = parse_duration(sys.argv[3]) if len(sys.argv) >= 4 else None

    robot = RobotController(network_interface)

    try:
        if command in MOVEMENT_COMMANDS:
            robot.execute_command(command, duration=duration)
        else:
            robot.execute_command(command)
    finally:
        if command in MOVEMENT_COMMANDS:
            robot.stop()


if __name__ == "__main__":
    main()
