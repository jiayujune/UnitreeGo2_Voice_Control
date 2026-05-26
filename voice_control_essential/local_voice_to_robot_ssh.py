import argparse
import json
import os
import shutil
import time
import urllib.error
import urllib.request
import wave
import subprocess
from datetime import datetime, timezone

from intent_parser import clean_text, parse_intent
from llm_intent_parser import get_provider_config, parse_intent_with_llm
from task_planner import plan_from_intent


ROBOT_SSH = "unitree@192.168.1.200"
ROBOT_PROJECT_DIR = "~/jiayu/UnitreeGo2_Voice_Control_Test"
ROBOT_PYTHON = "/home/unitree/go2_sdk_venv/bin/python"
ROBOT_SPEAKER_URL = "http://192.168.1.200:8000/say"
NETWORK_INTERFACE = "eth0"

AUDIO_FILE = "local_command.wav"
COMMAND_LOG_FILE = "voice_command_log.jsonl"
MODEL_NAME = "base"
RECORD_SECONDS = 5
SAMPLE_RATE = 16000
SPEECH_COMMAND = "spd-say"
PRE_COMMAND_SPEECH_DELAY_SECONDS = 1.0
CHAT_SYSTEM_PROMPT = """
You are Go2, a friendly quadruped robot dog talking through a speaker.
Reply naturally to casual conversation in one or two short sentences.
Do not claim that you performed a robot motion unless the control layer did it.
If the user asks for an unsupported robot task, briefly say what you can do safely.
""".strip()


def speak_on_computer(message):
    if shutil.which(SPEECH_COMMAND) is None:
        print(f"Computer voice reply unavailable: {SPEECH_COMMAND} not found.")
        return False

    result = subprocess.run([SPEECH_COMMAND, message], check=False)
    return result.returncode == 0


def speak_on_robot(message):
    print("\nSpeaking through Go2 speaker:")
    print(message)

    payload = json.dumps(
        {
            "text": message,
            "iface": NETWORK_INTERFACE,
            "verbose": True,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ROBOT_SPEAKER_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(f"Robot speech HTTP {exc.code}: {error_body}")
        return False
    except urllib.error.URLError as exc:
        print(f"Robot speaker server request failed: {exc}")
        print(f"Make sure the server is running at {ROBOT_SPEAKER_URL}")
        return False

    try:
        result = json.loads(response_body)
    except json.JSONDecodeError:
        print(f"Robot speaker returned non-JSON response: {response_body}")
        return False

    if not result.get("ok", False):
        print("Robot speaker reported failure:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return False

    return True


def speak(message, speech_output="computer"):
    if speech_output == "off":
        return True

    if speech_output == "robot":
        return speak_on_robot(message)

    if speech_output == "robot-fallback":
        if speak_on_robot(message):
            return True

        print("Falling back to computer speech.")
        return speak_on_computer(message)

    return speak_on_computer(message)


def robot_action_label(command):
    labels = {
        "stop": "stop",
        "balance": "balance stand",
        "stand_up": "stand up",
        "stand_down": "stand down",
        "recovery": "recovery stand",
        "forward": "move forward",
        "backward": "move backward",
        "turn_left": "turn left",
        "turn_right": "turn right",
    }
    return labels.get(command, command.replace("_", " "))


def record_audio():
    import numpy as np
    import sounddevice as sd

    print(f"\nRecording from COMPUTER microphone for {RECORD_SECONDS:g} seconds...")
    print("Say one command, for example: go two stop")

    audio = sd.rec(
        int(RECORD_SECONDS * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
    )
    sd.wait()

    audio = np.asarray(audio)

    with wave.open(AUDIO_FILE, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())

    print("Recording finished:", AUDIO_FILE)


def log_intent_event(
    text,
    intent,
    sent_to_robot,
    sent_command=None,
    dry_run=False,
    parser_mode="rule",
):
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "transcript": text,
        "cleaned_text": clean_text(text),
        "intent": intent,
        "sent_to_robot": sent_to_robot,
        "sent_command": sent_command,
        "dry_run": dry_run,
        "parser_mode": parser_mode,
    }

    with open(COMMAND_LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(event, ensure_ascii=False) + "\n")


def send_command_to_robot(command, duration=0.0):
    remote_cmd = (
        f"cd {ROBOT_PROJECT_DIR} && "
        f"{ROBOT_PYTHON} robot_command_once.py {NETWORK_INTERFACE} {command} {duration:.2f}"
    )

    print("\nSending command to robot over SSH:")
    print(command)
    print("Duration:", duration)

    subprocess.run(
        ["ssh", ROBOT_SSH, remote_cmd],
        check=False,
    )


def parse_with_mode(text, parser_mode, llm_provider=None, llm_model=None):
    if parser_mode == "llm":
        return parse_intent_with_llm(text, provider=llm_provider, model=llm_model)

    intent = parse_intent(text)
    intent["parser"] = "rule"
    return intent


def chat_completions_url(base_url):
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def generate_chat_reply(text, llm_provider=None, llm_model=None):
    config = get_provider_config(provider=llm_provider, model=llm_model)
    payload = {
        "model": config["model"],
        "temperature": 0.4,
        "messages": [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": text.strip()},
        ],
        "stream": False,
        "max_tokens": 80,
    }

    request = urllib.request.Request(
        chat_completions_url(config["base_url"]),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "go2-voice-control-chat/0.1",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        response_body = response.read().decode("utf-8")

    data = json.loads(response_body)
    reply = data["choices"][0]["message"]["content"].strip()
    return " ".join(reply.split())


def process_transcript(
    text,
    dry_run=False,
    parser_mode="rule",
    llm_provider=None,
    llm_model=None,
    show_plan=False,
    speech_output="computer",
):
    intent = parse_with_mode(text, parser_mode, llm_provider, llm_model)
    command = intent.get("action", "none")

    print("\nWhisper recognized / input text:")
    print(text)

    print("\nCleaned text:")
    print(clean_text(text))

    print("\nParsed intent JSON:")
    print(json.dumps(intent, ensure_ascii=False, indent=2))

    if show_plan:
        plan = plan_from_intent(intent)
        print("\nHigh-level plan:")
        print(json.dumps(plan, ensure_ascii=False, indent=2))

    if not intent.get("executable", False):
        print("\nIntent is not executable yet. Nothing sent to robot.")
        print("Reason:", intent.get("reason", "No reason provided."))
        if intent.get("intent") == "unknown" and parser_mode == "llm":
            try:
                reply = generate_chat_reply(
                    text,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                )
            except Exception as exc:
                reply = "Hi, I am Go2. I can chat, and I can follow simple safe movement commands."
                print(f"Chat reply fallback because LLM chat failed: {exc}")

            print("\nChat reply:")
            print(reply)
            speak(reply, speech_output)
        elif intent.get("intent") in {"need_food", "object_request"}:
            speak("I understand, but I cannot do that safely yet.", speech_output)
        else:
            speak("I did not understand a supported robot command.", speech_output)
        log_intent_event(
            text,
            intent,
            sent_to_robot=False,
            dry_run=dry_run,
            parser_mode=parser_mode,
        )
        return

    duration = float(intent.get("duration", 0.0))

    if dry_run:
        print("\nDRY RUN: no SSH command sent.")
        print(f"Would send command='{command}', duration={duration:.2f}")
        speak(f"Dry run. I would {robot_action_label(command)}.", speech_output)
        log_intent_event(
            text,
            intent,
            sent_to_robot=False,
            sent_command=command,
            dry_run=True,
            parser_mode=parser_mode,
        )
        return

    if intent.get("need_confirmation", False):
        confirm = input(f"Movement command '{command}'. Send to robot? Type yes: ")
        if confirm.strip().lower() != "yes":
            print("Cancelled.")
            speak("Cancelled.", speech_output)
            log_intent_event(
                text,
                intent,
                sent_to_robot=False,
                dry_run=False,
                parser_mode=parser_mode,
            )
            return

    speech_ok = speak(f"I will {robot_action_label(command)} now.", speech_output)
    if speech_output == "robot" and not speech_ok:
        print("\nRobot speech did not complete. Command was not sent.")
        log_intent_event(
            text,
            intent,
            sent_to_robot=False,
            sent_command=command,
            dry_run=False,
            parser_mode=parser_mode,
        )
        return

    if speech_output in {"computer", "robot-fallback"}:
        time.sleep(PRE_COMMAND_SPEECH_DELAY_SECONDS)

    send_command_to_robot(command, duration=duration)
    log_intent_event(
        text,
        intent,
        sent_to_robot=True,
        sent_command=command,
        dry_run=False,
        parser_mode=parser_mode,
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Computer microphone or text -> intent JSON -> optional SSH -> Go2"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command that would be sent, but do not SSH to the robot.",
    )
    parser.add_argument(
        "--text",
        help="Test one transcript directly without recording audio. This always runs as dry-run.",
    )
    parser.add_argument(
        "--parser",
        choices=["rule", "llm"],
        default="rule",
        help="Intent parser to use. llm falls back to rule-based parsing if unavailable.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["groq", "deepseek", "openai", "custom"],
        help="Provider to use with --parser llm. Can also be set with LLM_PROVIDER.",
    )
    parser.add_argument(
        "--llm-model",
        help="Model to use with --parser llm. Can also be set with LLM_MODEL.",
    )
    parser.add_argument(
        "--show-plan",
        action="store_true",
        help="Print the high-level task plan after intent parsing.",
    )
    parser.add_argument(
        "--no-speech",
        action="store_true",
        help="Disable spoken replies from the computer.",
    )
    parser.add_argument(
        "--speech-output",
        choices=["computer", "robot", "robot-fallback", "off"],
        default="computer",
        help="Where spoken replies should play.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    speech_output = "off" if args.no_speech else args.speech_output

    if args.text:
        process_transcript(
            args.text,
            dry_run=True,
            parser_mode=args.parser,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
            show_plan=args.show_plan,
            speech_output=speech_output,
        )
        return

    os.environ["CUDA_VISIBLE_DEVICES"] = ""

    import whisper

    print("Loading Whisper model on COMPUTER...")
    model = whisper.load_model(MODEL_NAME, device="cpu")
    print("Model loaded.")

    if args.dry_run:
        print("\nComputer microphone -> local Whisper -> intent JSON")
        print("DRY RUN MODE: no SSH commands will be sent.")
    else:
        print("\nComputer microphone -> local Whisper -> SSH -> robot")

    print("Press Ctrl+C to quit.")

    while True:
        input("\nPress Enter to record a command...")

        record_audio()

        result = model.transcribe(
            AUDIO_FILE,
            language="en",
            fp16=False,
            temperature=0,
            condition_on_previous_text=False,
            initial_prompt=(
                "The speaker will say one robot command: "
                "go two stop, go two balance, go two stand up, "
                "go two stand down, go two recovery, go two forward, "
                "go two back, go two left, go two right."
            ),
        )

        text = result["text"]
        process_transcript(
            text,
            dry_run=args.dry_run,
            parser_mode=args.parser,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
            show_plan=args.show_plan,
            speech_output=speech_output,
        )


if __name__ == "__main__":
    main()
