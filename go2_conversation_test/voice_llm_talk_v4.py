import os
import re
import json
import sys
import subprocess
from datetime import datetime

from motion_interface import create_robot_controller, execute_motion

import pyttsx3
from groq import Groq


# -----------------------------
# 1. Check Groq API key
# -----------------------------
api_key = os.environ.get("GROQ_API_KEY")

if not api_key:
    print("Error: GROQ_API_KEY is not set.")
    print("Please run:")
    print('export GROQ_API_KEY="your_api_key_here"')
    exit(1)

client = Groq(api_key=api_key)

CHAT_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
WHISPER_MODEL = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")

LOG_FILE = "conversation_log.jsonl"
AUDIO_DEVICE = os.environ.get("GO2_AUDIO_DEVICE", "default")


# -----------------------------
# 2. Text-to-speech setup
# -----------------------------
engine = pyttsx3.init()
engine.setProperty("rate", 160)


def speak(text):
    print("Go2:", text)
    engine.say(text)
    engine.runAndWait()


# -----------------------------
# 3. Save conversation log
# -----------------------------
def save_log(user_text, reply, raw_text=None, intent_info=None):
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "raw_transcription": raw_text,
        "cleaned_user_text": user_text,
        "intent_info": intent_info,
        "go2_reply": reply,
    }

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# -----------------------------
# 4. Record audio
# -----------------------------
def record_audio(filename="user_input.wav", seconds=5, device=AUDIO_DEVICE):
    print(f"\nRecording for {seconds} seconds. Please speak now...")
    print(f"Audio input device: {device}")

    command = [
        "arecord",
        "-D", device,
        "-f", "cd",
        "-t", "wav",
        "-d", str(seconds),
        filename
    ]

    subprocess.run(command, check=True)

    print("Recording finished.")
    return filename


def list_audio_devices():
    print("Available ALSA/PipeWire recording devices:", flush=True)
    subprocess.run(["arecord", "-L"], check=False)


def list_network_interfaces():
    net_dir = "/sys/class/net"
    if not os.path.isdir(net_dir):
        return []

    interfaces = []
    for name in sorted(os.listdir(net_dir)):
        operstate_path = os.path.join(net_dir, name, "operstate")
        try:
            with open(operstate_path, "r", encoding="utf-8") as f:
                state = f.read().strip()
        except OSError:
            state = "unknown"
        interfaces.append((name, state))
    return interfaces


def print_network_interface_hint(network_interface):
    interfaces = list_network_interfaces()
    matching = [state for name, state in interfaces if name == network_interface]

    if not matching:
        print(f"Warning: network interface '{network_interface}' was not found by Linux.")
        print("Available interfaces:")
        for name, state in interfaces:
            print(f"  {name} ({state})")
        return

    state = matching[0]
    print(f"Linux sees network interface '{network_interface}' with state: {state}")
    if state != "up":
        print("Warning: this interface is not up. Unitree SDK may reject it.")
        print(f"Try: sudo ip link set {network_interface} up")


# -----------------------------
# 5. Speech to text
# -----------------------------
def transcribe_audio(filename):
    print("Transcribing your speech...")

    with open(filename, "rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            file=(filename, audio_file.read()),
            model=WHISPER_MODEL,
        )

    text = transcription.text.strip()
    return text


def clean_transcription(text):
    """
    Fix common speech recognition mistakes.
    Go2 is often misheard as God, go to, go too, or go two.
    """

    cleaned = text

    cleaned = re.sub(r"\bGod\b", "Go2", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bgo to\b", "Go2", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bgo too\b", "Go2", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bgo two\b", "Go2", cleaned, flags=re.IGNORECASE)

    # Fix common motion command transcription mistakes
    cleaned = re.sub(r"\bblackfleet\b", "backflip", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bback fleet\b", "backflip", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bback flip\b", "backflip", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bset down\b", "sit down", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bseed down\b", "sit down", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


def should_exit(user_text):
    text = user_text.lower().strip()

    exit_phrases = [
        "exit",
        "quit",
        "stop talking",
        "goodbye",
        "bye",
        "end conversation",
        "that's all",
        "that is all",
    ]

    for phrase in exit_phrases:
        if phrase in text:
            return True

    return False


def looks_unclear(user_text):
    """
    Detect likely bad transcription or random noise.
    This helps avoid weird replies when Whisper hears background noise.
    """

    text = user_text.strip().lower()

    if len(text) < 2:
        return True

    unclear_phrases = [
        "z majjah",
        "bu ne",
        "sağırlıyorum",
        "tico leto",
        "adoro",
    ]

    for phrase in unclear_phrases:
        if phrase in text:
            return True

    return False


# -----------------------------
# 6. Motion intent detection
# -----------------------------
def extract_duration(text):
    """
    Try to find duration like:
    2 seconds, 3 sec, 5 secs
    """

    match = re.search(r"(\d+(\.\d+)?)\s*(seconds|second|secs|sec)\b", text.lower())

    if match:
        return float(match.group(1))

    if "small step" in text.lower() or "little bit" in text.lower() or "a little" in text.lower():
        return 1.0

    return 2.0


def extract_speed(text):
    text = text.lower()

    if "slow" in text or "slowly" in text:
        return "slow"

    if "fast" in text or "quick" in text or "quickly" in text:
        return "fast"

    return "normal"


def detect_motion_intent(user_text):
    """
    This function decides whether the user is giving a motion command.

    For now, this does not control the real robot.
    It only recognizes the command and prepares a structured result.
    """

    text = user_text.lower()

    unsafe_keywords = [
        "backflip",
        "flip",
        "jump",
        "attack",
        "kick",
        "run into",
        "go downstairs",
        "go upstairs",
        "stairs",
    ]

    for word in unsafe_keywords:
        if word in text:
            return {
                "intent": "motion_command",
                "action": word,
                "speed": extract_speed(user_text),
                "duration": extract_duration(user_text),
                "safe_to_attempt": False,
                "motion_connected": False,
                "executable": False,
                "reason": "This action may be unsafe or is not supported yet."
            }

    action = None

    if "stop" in text or "freeze" in text:
        action = "stop"

    elif "stand up" in text or "stand" in text:
        action = "stand"

    elif "sit down" in text or "sit" in text:
        action = "sit"

    elif "move forward" in text or "go forward" in text or "walk forward" in text or "forward" in text:
        action = "forward"

    elif "move backward" in text or "go backward" in text or "walk backward" in text or "backward" in text or "step back" in text:
        action = "backward"

    elif "turn left" in text:
        action = "turn_left"

    elif "turn right" in text:
        action = "turn_right"

    elif "move left" in text or "step left" in text:
        action = "move_left"

    elif "move right" in text or "step right" in text:
        action = "move_right"

    if action is None:
        return {
            "intent": "chat",
            "action": None,
            "speed": None,
            "duration": None,
            "safe_to_attempt": None,
            "motion_connected": False,
            "executable": False,
            "reason": "No motion command detected."
        }

    return {
        "intent": "motion_command",
        "action": action,
        "speed": extract_speed(user_text),
        "duration": extract_duration(user_text),
        "safe_to_attempt": True,
        "motion_connected": True,
        "executable": True,
        "reason": "Motion command recognized."
    }


def reply_to_motion_command(intent_info):
    action = intent_info["action"]
    speed = intent_info["speed"]
    duration = intent_info["duration"]

    if not intent_info["safe_to_attempt"]:
        return (
            f"I understand this as a motion command: {action}. "
            "But this action may be unsafe or unsupported, so I will not execute it."
        )

    if action == "stop":
        return (
            "I understand this as a stop command. "
            "Motion control is not connected yet, so I will not send the command."
        )

    return (
        f"I understand this as a motion command: {action}, "
        f"speed {speed}, duration {duration} seconds. "
        "Motion control is not connected yet, so I will not move."
    )


# -----------------------------
# 7. LLM chat setup
# -----------------------------
system_prompt = """
You are Go2, a friendly robot dog conversation assistant.

Your job is to have a smooth, simple voice conversation with the user.

Important rules:
1. Keep replies short, usually 1 or 2 sentences.
2. Speak in a friendly, calm, and slightly robotic dog-like tone.
3. Do not give long technical explanations unless the user asks.
4. Do not claim that you can physically move yet.
5. If the user asks what you are, say you are Go2, a quadruped robot dog.
6. If the user's speech recognition says "Go2", just treat it as your name. Do not correct the user.
7. Encourage the user while they are learning robot dogs.
8. Always reply in English.
9. If the user's speech is unclear or seems like random transcription noise, politely ask the user to repeat.
"""

conversation_history = []


def get_llm_reply(user_text):
    conversation_history.append({
        "role": "user",
        "content": user_text
    })

    recent_history = conversation_history[-8:]
    messages = [{"role": "system", "content": system_prompt}] + recent_history

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        temperature=0.4,
        max_tokens=100,
    )

    reply = response.choices[0].message.content.strip()

    conversation_history.append({
        "role": "assistant",
        "content": reply
    })

    return reply


def parse_runtime_mode():
    if len(sys.argv) >= 2 and sys.argv[1] == "--list-audio":
        list_audio_devices()
        sys.exit(0)

    if len(sys.argv) < 2 or sys.argv[1].lower() == "dry":
        return None

    if sys.argv[1] in ["-h", "--help", "help"]:
        print("Usage:")
        print("  python3 voice_llm_talk_v4.py dry")
        print("  python3 voice_llm_talk_v4.py <network_interface>")
        print("  python3 voice_llm_talk_v4.py --list-audio")
        print("")
        print("Audio input:")
        print("  GO2_AUDIO_DEVICE=default python3 voice_llm_talk_v4.py dry")
        print("  GO2_AUDIO_DEVICE=pipewire python3 voice_llm_talk_v4.py dry")
        print("")
        print("Example real robot mode:")
        print("  python3 voice_llm_talk_v4.py enp2s0")
        sys.exit(0)

    return sys.argv[1]


# -----------------------------
# 8. Main loop
# -----------------------------
def main():
    network_interface = parse_runtime_mode()
    robot = None

    print("Go2 voice conversation demo v4 started.")
    print("New feature: chat + motion intent detection + optional real robot control.")
    print("Press Enter to record your voice.")
    print("Say 'goodbye', 'exit', or 'stop talking' to quit by voice.")
    print("Type q and press Enter to quit manually.")
    print(f"Audio input device: {AUDIO_DEVICE}")
    print()

    if network_interface is None:
        print("DRY RUN MODE: motion commands will not be sent to the robot.")
    else:
        print("REAL ROBOT MODE")
        print(f"Network interface: {network_interface}")
        print_network_interface_hint(network_interface)
        print("Before continuing, make sure the robot is in a clear area.")
        input("Press Enter to initialize robot high-level SDK...")
        robot = create_robot_controller(network_interface)

    speak("Hello, I am Go2. I can chat with you and recognize simple motion commands.")

    try:
        while True:
            command = input("\nPress Enter to speak, or type q to quit: ")

            if command.lower() in ["q", "quit", "exit"]:
                speak("Goodbye. I will stop talking now.")
                break

            try:
                audio_filename = record_audio(seconds=5)

                raw_text = transcribe_audio(audio_filename)
                user_text = clean_transcription(raw_text)

                if not user_text:
                    reply = "Sorry, I did not hear anything clearly."
                    speak(reply)
                    save_log(user_text="", reply=reply, raw_text=raw_text)
                    continue

                print("Raw transcription:", raw_text)
                print("Cleaned text:", user_text)

                if should_exit(user_text):
                    reply = "Goodbye. I enjoyed talking with you."
                    speak(reply)
                    save_log(user_text=user_text, reply=reply, raw_text=raw_text)
                    break

                if looks_unclear(user_text):
                    reply = "Sorry, I did not understand that clearly. Could you please repeat?"
                    speak(reply)
                    save_log(user_text=user_text, reply=reply, raw_text=raw_text)
                    continue

                intent_info = detect_motion_intent(user_text)

                print("Intent info:", json.dumps(intent_info, indent=2))

                if intent_info["intent"] == "motion_command":
                    motion_result = execute_motion(intent_info, robot=robot)

                    print("Motion interface result:", json.dumps(motion_result, indent=2))

                    if motion_result["executed"]:
                        reply = f"I recognized your motion command: {intent_info['action']}. I sent it to my body."
                    elif "robot_return_code" in motion_result:
                        reply = (
                            f"I recognized your motion command: {intent_info['action']}, "
                            "but my body did not accept the command. Please check the robot connection."
                        )
                    elif "command" not in motion_result:
                        reply = (
                            f"I recognized your motion command: {intent_info['action']}. "
                            "That motion is not mapped to a robot command yet, so I did not move."
                        )
                    elif intent_info["safe_to_attempt"]:
                        reply = (
                            f"I recognized your motion command: {intent_info['action']}. "
                            "Dry run mode is on, so I did not move."
                        )
                    else:
                        reply = reply_to_motion_command(intent_info)

                else:
                    reply = get_llm_reply(user_text)

                speak(reply)
                save_log(
                    user_text=user_text,
                    reply=reply,
                    raw_text=raw_text,
                    intent_info=intent_info
                )

            except subprocess.CalledProcessError:
                print("Recording error: arecord failed.")
                speak("Sorry, I could not record audio from the microphone.")

            except Exception as e:
                print("Error:", e)
                speak("Sorry, something went wrong.")

    except KeyboardInterrupt:
        print("\nProgram stopped.")

    finally:
        if robot is not None:
            print("Sending final stop command...")
            robot.stop()


if __name__ == "__main__":
    main()
