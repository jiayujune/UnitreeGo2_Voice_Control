import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""

import re
import subprocess
import whisper


AUDIO_FILE = "command.wav"
MODEL_NAME = "base"
RECORD_SECONDS = 5


def record_audio():
    print("\nRecording for 5 seconds...")
    print("Say ONE command only:")
    print("forward / stop / left / right / back")

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


def clean_text(text):
    text = text.lower()
    text = re.sub(r"[^a-z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_command(text):
    text = clean_text(text)

    # Safety first: stop has the highest priority
    # Even if the user does not say "robot", stop should still work.
    if "stop" in text or "halt" in text or "freeze" in text:
        return "stop"

    # For movement commands, require the wake word "robot"
    if "robot" not in text:
        return "unknown"

    if text in ["robot forward", "robot go forward", "robot move forward"]:
        return "forward"

    if text in ["robot left", "robot turn left"]:
        return "turn_left"

    if text in ["robot right", "robot turn right"]:
        return "turn_right"

    if text in ["robot back", "robot backward", "robot go back", "robot move back"]:
        return "backward"

    return "unknown"


def print_robot_action(command):
    if command == "stop":
        print("Robot action: STOP")
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
            initial_prompt="The speaker will say one robot command: robot forward, robot stop, robot left, robot right, robot back, or stop."
        )

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

except KeyboardInterrupt:
    print("\nProgram stopped.")