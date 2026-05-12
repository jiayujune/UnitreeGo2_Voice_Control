import re
import whisper

AUDIO_FILE = "test.wav"
MODEL_NAME = "base"


def clean_text(text):
    text = text.lower()
    text = re.sub(r"[^a-z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_command(text):
    text = clean_text(text)

    # stop should always have the highest priority
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


print("Loading Whisper model...")
model = whisper.load_model(MODEL_NAME, device="cpu")
print("Model loaded.")

result = model.transcribe(AUDIO_FILE, language="en", fp16=False)
text = result["text"]

command = parse_command(text)

print("\nWhisper recognized:")
print(text)

print("\nCleaned text:")
print(clean_text(text))

print("\nParsed robot command:")
print(command)

