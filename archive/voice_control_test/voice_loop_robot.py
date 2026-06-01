import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""

import sys
import subprocess
import whisper

from command_parser import clean_text, parse_command
from robot_controller import RobotController


AUDIO_FILE = "command.wav"
MODEL_NAME = "base"
RECORD_SECONDS = 5


def record_audio():
    print("\nRecording for 5 seconds...")
    print("Say ONE command only:")
    print("go two forward / go two stand down / go two stop / go two left / go two right / go two back / stop")

    subprocess.run([
        "arecord",
        "-D", "default",
        "-r", "16000",
        "-c", "1",
        "-f", "S16_LE",
        "-d", str(RECORD_SECONDS),
        AUDIO_FILE
    ], check=True)

    print("Recording finished.")


def print_robot_action(command):
    if command == "stop":
        print("Robot action: STOP")
    elif command == "stand_up":
        print("Robot action: STAND UP")
    elif command == "stand_down":
        print("Robot action: STAND DOWN")
    elif command == "balance":
        print("Robot action: BALANCE STAND")
    elif command == "recovery":
        print("Robot action: RECOVERY STAND")
    elif command == "forward":
        print("Robot action: MOVE FORWARD")
    elif command == "backward":
        print("Robot action: MOVE BACKWARD")
    elif command == "turn_left":
        print("Robot action: TURN LEFT")
    elif command == "turn_right":
        print("Robot action: TURN RIGHT")
    else:
        print("Robot action: DO NOTHING")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Dry run only:")
        print("    python voice_loop_robot.py dry")
        print("")
        print("  Real robot mode:")
        print("    python voice_loop_robot.py enp2s0")
        return

    mode_or_interface = sys.argv[1]

    use_real_robot = mode_or_interface != "dry"
    robot = None

    if use_real_robot:
        network_interface = mode_or_interface

        print("REAL ROBOT MODE")
        print("Before continuing, make sure:")
        print("1. The robot is in a clear area.")
        print("2. Someone is ready to stop it.")
        print("3. You are using high-level control only.")
        input("Press Enter to initialize robot high-level SDK...")

        robot = RobotController(network_interface)
        robot.balance_stand()

    else:
        print("DRY RUN MODE: no commands will be sent to the robot.")

    print("Loading Whisper model...")
    model = whisper.load_model(MODEL_NAME, device="cpu")
    print("Model loaded.")

    try:
        while True:
            input("\nPress Enter to record a command. Press Ctrl+C to quit.")

            record_audio()

            result = model.transcribe(
                AUDIO_FILE,
                language="en",
                fp16=False,
                temperature=0,
                condition_on_previous_text=False,
                initial_prompt="The speaker will say one robot command. Prefer go two as the wake phrase: go two stand up, go two stand down, go two balance, go two recovery, go two forward, go two stop, go two left, go two right, go two back, or stop.")

            text = result["text"]
            cleaned = clean_text(text)
            command = parse_command(text)

            print("\nWhisper recognized:")
            print(text)

            print("\nCleaned text:")
            print(cleaned)

            print("\nParsed robot command:")
            print(command)

            print_robot_action(command)

            if use_real_robot and robot is not None:
                robot.execute_command(command)

    except KeyboardInterrupt:
        print("\nProgram stopped.")
        if use_real_robot and robot is not None:
            print("Sending final stop command...")
            robot.stop()


if __name__ == "__main__":
    main()
