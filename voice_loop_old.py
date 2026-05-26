import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""

import re
import subprocess
import whisper


AUDIO_FILE = "command.wav"
MODEL_NAME = "base"
RECORD_SECONDS = 4


def record_audio():
    print("\nRecording...")
    print("Please say a command:")
    print("move forward / stop / turn left / turn right / move backward")

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
    if "stop" in text or "halt" in text or "freeze" in text:
        return "stop"

    if "turn left" in text or "left" in text:
        return "turn_left"

    if "turn right" in text or "right" in text:
        return "turn_right"

    if "backward" in text or "move back" in text or "go back" in text or "back up" in text:
        return "backward"

    if "forward" in text or "move forward" in text or "go forward" in text:
        return "forward"

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

        result = model.transcribe(AUDIO_FILE, language="en", fp16=False)
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

