import argparse
import atexit
import csv
import json
import os
import shutil
import time
import urllib.error
import urllib.request
import subprocess
from datetime import datetime, timezone

from audio_pipeline import SileroVADRecorder, record_fixed_duration
from intent_parser import clean_text, parse_intent, split_command_segments
from llm_intent_parser import get_provider_config, parse_intent_with_llm
from task_planner import plan_from_intent
from transcriber import build_transcriber


ROBOT_SSH = "unitree@192.168.1.200"
ROBOT_PROJECT_DIR = "~/jiayu/UnitreeGo2_Voice_Control_Test"
ROBOT_PYTHON = "/home/unitree/go2_sdk_venv/bin/python"
ROBOT_SPEAKER_URL = "http://192.168.1.200:8000/say"
NETWORK_INTERFACE = "eth0"

# Plain SSH does not source ~/.bashrc, so the robot-side cyclonedds binding loads
# the wrong libddsc and any DDS write (motion command) segfaults. Export the
# correct CycloneDDS paths in every robot command. See docs/go2-audio-output-issue.md.
CYCLONEDDS_HOME = "/home/unitree/cyclonedds_ws/install/cyclonedds"
ROBOT_ENV_PREFIX = (
    f"export CYCLONEDDS_HOME={CYCLONEDDS_HOME} && "
    f"export LD_LIBRARY_PATH={CYCLONEDDS_HOME}/lib:$LD_LIBRARY_PATH && "
)

AUDIO_FILE = "local_command.wav"
COMMAND_LOG_FILE = "voice_command_log.jsonl"
COMMAND_CSV_LOG_FILE = "voice_command_log.csv"
MODEL_NAME = "base"
RECORD_SECONDS = 5
SAMPLE_RATE = 16000
STT_LANGUAGE = "en"
SPEECH_COMMAND = "spd-say"
PRE_COMMAND_SPEECH_DELAY_SECONDS = 1.0
SSH_COMMAND_TIMEOUT_SECONDS = 20.0
MAX_SEQUENCE_COMMANDS = 4

# Reuse one multiplexed SSH connection across commands so each command skips the
# TCP + auth handshake (~hundreds of ms). The master is opened once and kept
# alive by ControlPersist; subsequent ssh calls ride the same socket.
SSH_CONTROL_PATH = os.path.expanduser("~/.ssh/cm-go2-voice-%C")
SSH_CONTROL_PERSIST_SECONDS = 120
SSH_BASE_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=5",
    "-o", "ControlMaster=auto",
    "-o", f"ControlPath={SSH_CONTROL_PATH}",
    "-o", f"ControlPersist={SSH_CONTROL_PERSIST_SECONDS}",
]
ROBOT_COMMAND_STT_PROMPT = (
    "The speaker will say one robot command or high-level request: "
    "go two stop, go two balance, go two stand up, go two stand down, "
    "go two recovery, go two forward, go two back, go two left, go two right, "
    "I am hungry, find food, find the apple."
)
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
    return record_fixed_duration(
        AUDIO_FILE,
        seconds=RECORD_SECONDS,
        sample_rate=SAMPLE_RATE,
    )


def log_intent_event(
    text,
    intent,
    sent_to_robot,
    sent_command=None,
    dry_run=False,
    parser_mode="rule",
    timings=None,
):
    timestamp = datetime.now(timezone.utc).isoformat()
    timings = timings or {}
    event = {
        "timestamp": timestamp,
        "transcript": text,
        "cleaned_text": clean_text(text),
        "intent": intent,
        "sent_to_robot": sent_to_robot,
        "sent_command": sent_command,
        "dry_run": dry_run,
        "parser_mode": parser_mode,
        "stt_ms": timings.get("stt_ms"),
        "parse_ms": timings.get("parse_ms"),
        "send_ms": timings.get("send_ms"),
        "total_ms": timings.get("total_ms"),
    }

    with open(COMMAND_LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(event, ensure_ascii=False) + "\n")

    csv_exists = os.path.exists(COMMAND_CSV_LOG_FILE)
    csv_row = {
        "timestamp": timestamp,
        "transcript": text,
        "cleaned_text": clean_text(text),
        "intent": intent.get("intent"),
        "action": intent.get("action"),
        "target": intent.get("target", ""),
        "duration": intent.get("duration", 0.0),
        "executable": intent.get("executable", False),
        "need_confirmation": intent.get("need_confirmation", False),
        "parser": intent.get("parser", parser_mode),
        "llm_provider": intent.get("llm_provider", ""),
        "llm_model": intent.get("llm_model", ""),
        "sent_to_robot": sent_to_robot,
        "sent_command": sent_command or "",
        "dry_run": dry_run,
        "reason": intent.get("reason", ""),
        "stt_ms": timings.get("stt_ms"),
        "parse_ms": timings.get("parse_ms"),
        "send_ms": timings.get("send_ms"),
        "total_ms": timings.get("total_ms"),
    }

    with open(COMMAND_CSV_LOG_FILE, "a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(csv_row.keys()))
        if not csv_exists:
            writer.writeheader()
        writer.writerow(csv_row)


def warm_ssh_connection():
    """Open the multiplexed SSH master connection ahead of time so the first
    real command does not pay the full handshake. Best-effort: a failure here
    just means commands fall back to opening their own connection (and will
    report honestly if the robot is unreachable)."""
    try:
        result = subprocess.run(
            ["ssh", *SSH_BASE_OPTS, ROBOT_SSH, "true"],
            check=False,
            timeout=SSH_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(f"SSH warm-up timed out. Robot may be offline at {ROBOT_SSH}.")
        return False

    if result.returncode != 0:
        print(f"SSH warm-up failed (exit code {result.returncode}). "
              f"Commands will still be attempted when needed.")
        return False

    print(f"SSH connection to {ROBOT_SSH} is warm (multiplexed, reused for commands).")
    return True


def close_ssh_connection():
    """Tear down the shared SSH master socket on exit."""
    subprocess.run(
        ["ssh", "-O", "exit", "-o", f"ControlPath={SSH_CONTROL_PATH}", ROBOT_SSH],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def send_command_to_robot(command, duration=0.0):
    remote_cmd = (
        f"{ROBOT_ENV_PREFIX}"
        f"cd {ROBOT_PROJECT_DIR} && "
        f"{ROBOT_PYTHON} robot_command_once.py {NETWORK_INTERFACE} {command} {duration:.2f}"
    )

    print("\nSending command to robot over SSH:")
    print(command)
    print("Duration:", duration)

    try:
        result = subprocess.run(
            ["ssh", *SSH_BASE_OPTS, ROBOT_SSH, remote_cmd],
            check=False,
            timeout=SSH_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(f"\nSSH command timed out after {SSH_COMMAND_TIMEOUT_SECONDS}s. "
              f"Is the robot reachable at {ROBOT_SSH}?")
        return False

    if result.returncode != 0:
        print(f"\nSSH command failed (exit code {result.returncode}). "
              "Command was NOT executed on the robot.")
        return False

    return True


def parse_with_mode(text, parser_mode, llm_provider=None, llm_model=None):
    if parser_mode == "llm":
        return parse_intent_with_llm(text, provider=llm_provider, model=llm_model)

    intent = parse_intent(text)
    intent["parser"] = "rule"
    return intent


def capture_audio(args, vad_recorder=None):
    if args.input_mode == "vad":
        if vad_recorder is None:
            vad_recorder = SileroVADRecorder(
                sample_rate=SAMPLE_RATE,
                threshold=args.vad_threshold,
                min_speech_ms=args.vad_min_speech_ms,
                silence_ms=args.vad_silence_ms,
            )

        result = vad_recorder.record_until_speech_ends(
            AUDIO_FILE,
            max_seconds=args.max_listen_seconds,
            start_timeout_seconds=args.vad_start_timeout,
        )
        if not result["speech_detected"]:
            print("Skipping transcription because no speech was detected.")
            return None
        return AUDIO_FILE

    return record_audio()


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


def _sequence_timings(stt_ms, parse_ms, send_ms=None, is_first=False):
    """Per-command timings inside a sequence. STT latency is attributed only to
    the first command so it is not counted once per segment in the metrics."""
    stt_part = round(stt_ms, 1) if (stt_ms is not None and is_first) else None
    total = (stt_ms or 0.0 if is_first else 0.0) + parse_ms + (send_ms or 0.0)
    timings = {
        "stt_ms": stt_part,
        "parse_ms": round(parse_ms, 1),
        "total_ms": round(total, 1),
    }
    if send_ms is not None:
        timings["send_ms"] = round(send_ms, 1)
    return timings


def process_sequence(
    segments,
    *,
    dry_run,
    parser_mode,
    llm_provider,
    llm_model,
    speech_output,
    stt_ms,
):
    """Execute several commands from one utterance, in order. Returns True if it
    handled the input; False if no executable command was found (so the caller
    can fall back to single-command handling on the whole transcript)."""
    parsed = []
    for segment in segments:
        parse_start = time.perf_counter()
        intent = parse_with_mode(segment, parser_mode, llm_provider, llm_model)
        parse_ms = (time.perf_counter() - parse_start) * 1000.0
        parsed.append((segment, intent, parse_ms))

    executable = [(s, i, m) for (s, i, m) in parsed if i.get("executable", False)]
    if not executable:
        return False

    skipped = [s for (s, i, _) in parsed if not i.get("executable", False)]
    if skipped:
        print("\nSkipping unrecognized parts of the sequence:", skipped)

    if len(executable) > MAX_SEQUENCE_COMMANDS:
        print(f"\nSequence has {len(executable)} commands; running only the first "
              f"{MAX_SEQUENCE_COMMANDS} for safety.")
        executable = executable[:MAX_SEQUENCE_COMMANDS]

    labels = [robot_action_label(i.get("action")) for (_, i, _) in executable]
    plan_sentence = ", then ".join(labels)
    print("\nCommand sequence:", " -> ".join(labels))

    def log_each(send_ms_list, sent_flags):
        for idx, (segment, intent, parse_ms) in enumerate(executable):
            log_intent_event(
                segment,
                intent,
                sent_to_robot=sent_flags[idx],
                sent_command=intent.get("action"),
                dry_run=dry_run,
                parser_mode=parser_mode,
                timings=_sequence_timings(
                    stt_ms, parse_ms, send_ms_list[idx], is_first=(idx == 0)
                ),
            )

    if dry_run:
        print(f"\nDRY RUN: would run sequence: {plan_sentence}")
        speak(f"Dry run. I would {plan_sentence}.", speech_output)
        log_each([None] * len(executable), [False] * len(executable))
        return True

    if any(i.get("need_confirmation", False) for (_, i, _) in executable):
        confirm = input(f"Run command sequence [{plan_sentence}]? Type yes: ")
        if confirm.strip().lower() != "yes":
            print("Cancelled.")
            speak("Cancelled.", speech_output)
            return True

    speech_ok = speak(f"Okay. I will {plan_sentence}.", speech_output)
    if speech_output == "robot" and not speech_ok:
        print("\nRobot speech did not complete. Sequence was not sent.")
        return True
    if speech_output in {"computer", "robot-fallback"}:
        time.sleep(PRE_COMMAND_SPEECH_DELAY_SECONDS)

    send_ms_list = [None] * len(executable)
    sent_flags = [False] * len(executable)
    for idx, (segment, intent, parse_ms) in enumerate(executable):
        action = intent.get("action")
        duration = float(intent.get("duration", 0.0))
        send_start = time.perf_counter()
        sent_ok = send_command_to_robot(action, duration=duration)
        send_ms_list[idx] = (time.perf_counter() - send_start) * 1000.0
        sent_flags[idx] = sent_ok

        if not sent_ok:
            print("Aborting remaining sequence: robot unreachable.")
            speak("I could not reach the robot.", speech_output)
            break
        if action == "stop":
            print("Stop command reached; halting the rest of the sequence.")
            break

    log_each(send_ms_list, sent_flags)
    return True


def process_transcript(
    text,
    dry_run=False,
    parser_mode="rule",
    llm_provider=None,
    llm_model=None,
    show_plan=False,
    speech_output="computer",
    stt_ms=None,
):
    segments = split_command_segments(text)
    if len(segments) > 1:
        print("\nDetected a multi-command utterance:")
        print(text)
        handled = process_sequence(
            segments,
            dry_run=dry_run,
            parser_mode=parser_mode,
            llm_provider=llm_provider,
            llm_model=llm_model,
            speech_output=speech_output,
            stt_ms=stt_ms,
        )
        if handled:
            return
        print("\nNo executable command found in the sequence; "
              "parsing the whole utterance instead.")

    parse_start = time.perf_counter()
    intent = parse_with_mode(text, parser_mode, llm_provider, llm_model)
    parse_ms = (time.perf_counter() - parse_start) * 1000.0
    timings = {
        "stt_ms": round(stt_ms, 1) if stt_ms is not None else None,
        "parse_ms": round(parse_ms, 1),
        "total_ms": round((stt_ms or 0.0) + parse_ms, 1),
    }
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
            timings=timings,
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
            timings=timings,
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
                timings=timings,
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
            timings=timings,
        )
        return

    if speech_output in {"computer", "robot-fallback"}:
        time.sleep(PRE_COMMAND_SPEECH_DELAY_SECONDS)

    send_start = time.perf_counter()
    sent_ok = send_command_to_robot(command, duration=duration)
    send_ms = (time.perf_counter() - send_start) * 1000.0
    timings["send_ms"] = round(send_ms, 1)
    timings["total_ms"] = round((stt_ms or 0.0) + parse_ms + send_ms, 1)
    if not sent_ok:
        speak("I could not reach the robot.", speech_output)
    log_intent_event(
        text,
        intent,
        sent_to_robot=sent_ok,
        sent_command=command,
        dry_run=False,
        parser_mode=parser_mode,
        timings=timings,
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
    parser.add_argument(
        "--robot-speaker-url",
        help=f"Robot speaker server URL. Default: {ROBOT_SPEAKER_URL}",
    )
    parser.add_argument(
        "--input-mode",
        choices=["fixed", "vad"],
        default="fixed",
        help="Use fixed-length recording or Silero VAD speech segmentation.",
    )
    parser.add_argument(
        "--stt",
        choices=["local", "openai", "groq"],
        default="local",
        help="Speech-to-text backend: local Whisper, OpenAI Whisper API, or Groq Whisper API.",
    )
    parser.add_argument(
        "--stt-model",
        help="Whisper model name. Defaults to base for local STT and whisper-1 for OpenAI STT.",
    )
    parser.add_argument(
        "--record-seconds",
        type=float,
        default=RECORD_SECONDS,
        help="Seconds to record in fixed input mode.",
    )
    parser.add_argument(
        "--max-listen-seconds",
        type=float,
        default=8.0,
        help="Maximum seconds to listen in VAD input mode.",
    )
    parser.add_argument(
        "--vad-start-timeout",
        type=float,
        default=5.0,
        help="Seconds to wait for speech to start in VAD input mode.",
    )
    parser.add_argument(
        "--vad-threshold",
        type=float,
        default=0.5,
        help="Silero VAD speech threshold.",
    )
    parser.add_argument(
        "--vad-silence-ms",
        type=int,
        default=800,
        help="Silence after speech before VAD recording stops.",
    )
    parser.add_argument(
        "--vad-min-speech-ms",
        type=int,
        default=250,
        help="Minimum speech duration required before transcribing a VAD clip.",
    )
    parser.add_argument(
        "--speaker-gate",
        choices=["off", "on"],
        default="off",
        help="Require an enrolled, recognized speaker before any command runs.",
    )
    parser.add_argument(
        "--speaker-encoder",
        choices=["mfcc", "resemblyzer"],
        default="resemblyzer",
        help="Embedding model for the speaker gate (resemblyzer is far more accurate).",
    )
    parser.add_argument(
        "--speaker-profiles",
        default=None,
        help="Path to authorized-speaker profiles (default: authorized_speakers.json).",
    )
    parser.add_argument(
        "--speaker-threshold",
        type=float,
        default=0.75,
        help="Cosine similarity threshold for accepting a speaker.",
    )
    parser.add_argument(
        "--enroll",
        metavar="SPEAKER_ID",
        help="Enrollment mode: record clips of a voice, save it as an authorized speaker, then exit.",
    )
    parser.add_argument(
        "--enroll-clips",
        type=int,
        default=3,
        help="Number of clips to record during --enroll.",
    )
    return parser.parse_args()


def run_enrollment(args):
    """Record a few clips of a voice and save it as an authorized speaker."""
    import speaker_gate

    profiles = args.speaker_profiles or speaker_gate.DEFAULT_PROFILES
    gate = speaker_gate.build_gate(
        encoder=args.speaker_encoder,
        profiles_path=profiles,
        threshold=args.speaker_threshold,
    )
    print(f"\nEnrolling '{args.enroll}' — {args.enroll_clips} clip(s), encoder={args.speaker_encoder}.")
    print("Speak naturally, as you would when commanding the robot.")
    saved = 0
    for i in range(args.enroll_clips):
        input(f"\n[{i + 1}/{args.enroll_clips}] Press Enter, then speak for ~{RECORD_SECONDS:.0f}s...")
        record_audio()
        try:
            profile = gate.enroll_file(args.enroll, AUDIO_FILE)
            saved += 1
            print(f"  clip {i + 1} enrolled (total samples for {args.enroll}: {profile.sample_count}).")
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"  clip {i + 1} skipped: {exc}")

    if saved:
        print(f"\nDone. Authorized speakers: {', '.join(speaker_gate.authorized_speakers(gate))}")
        print(f"Profiles saved to: {profiles}")
    else:
        print("\nNo clips were enrolled (no speech detected). Nothing saved.")


def main():
    args = parse_args()
    speech_output = "off" if args.no_speech else args.speech_output

    if args.enroll:
        run_enrollment(args)
        return

    global RECORD_SECONDS
    global ROBOT_SPEAKER_URL
    RECORD_SECONDS = args.record_seconds
    if args.robot_speaker_url:
        ROBOT_SPEAKER_URL = args.robot_speaker_url

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

    transcriber = build_transcriber(
        args.stt,
        model_name=args.stt_model,
        language=STT_LANGUAGE,
    )
    vad_recorder = None
    if args.input_mode == "vad":
        vad_recorder = SileroVADRecorder(
            sample_rate=SAMPLE_RATE,
            threshold=args.vad_threshold,
            min_speech_ms=args.vad_min_speech_ms,
            silence_ms=args.vad_silence_ms,
        )

    gate = None
    if args.speaker_gate == "on":
        import speaker_gate

        gate = speaker_gate.build_gate(
            encoder=args.speaker_encoder,
            profiles_path=args.speaker_profiles or speaker_gate.DEFAULT_PROFILES,
            threshold=args.speaker_threshold,
        )
        speakers = speaker_gate.authorized_speakers(gate)
        if not speakers:
            print("\nSpeaker gate is ON but no authorized speakers are enrolled.")
            print("Enroll yourself first, e.g.:")
            print("  python local_voice_to_robot_ssh.py --enroll your_name")
            print("Disabling the speaker gate for this session.")
            gate = None
        else:
            print(f"\nSpeaker gate ON — authorized: {', '.join(speakers)} "
                  f"(encoder={args.speaker_encoder}, threshold={args.speaker_threshold}).")

    if args.dry_run:
        print(f"\nComputer microphone -> {args.input_mode} capture -> {args.stt} STT -> intent JSON")
        print("DRY RUN MODE: no SSH commands will be sent.")
    else:
        print(f"\nComputer microphone -> {args.input_mode} capture -> {args.stt} STT -> SSH -> robot")
        atexit.register(close_ssh_connection)
        warm_ssh_connection()

    print("Press Ctrl+C to quit.")

    while True:
        input("\nPress Enter to listen for a command...")

        audio_path = capture_audio(args, vad_recorder=vad_recorder)
        if audio_path is None:
            continue

        if gate is not None:
            import speaker_gate

            speaker_id, score = speaker_gate.identify(gate, audio_path)
            if speaker_id is None:
                print(f"Speaker not recognized (best score {score:.2f}). Command ignored.")
                speak("Sorry, I do not recognize your voice.", speech_output)
                continue
            print(f"Speaker recognized: {speaker_id} (score {score:.2f}) — authorized.")

        stt_start = time.perf_counter()
        text = transcriber.transcribe(
            audio_path,
            prompt=ROBOT_COMMAND_STT_PROMPT,
        )
        stt_ms = (time.perf_counter() - stt_start) * 1000.0
        if not text.strip():
            print("No usable speech recognized (empty or filtered). Listening again.")
            continue
        process_transcript(
            text,
            dry_run=args.dry_run,
            parser_mode=args.parser,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
            show_plan=args.show_plan,
            speech_output=speech_output,
            stt_ms=stt_ms,
        )


if __name__ == "__main__":
    main()
