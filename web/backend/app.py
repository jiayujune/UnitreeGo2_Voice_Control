"""
FastAPI backend for the Go2 voice-control web frontend.

It wraps the existing prototype modules in ``voice_control_essential``:
  - intent_parser.parse_intent / apply_safety_rules   (rule-based intent + safety layer)
  - llm_intent_parser.parse_intent_with_llm           (LLM intent, falls back to rules)
  - task_planner.plan_from_intent                     (high-level plan)
  - transcriber.build_transcriber                     (local / openai / groq STT)
  - robot control over SSH                            (same command as the CLI)

Real robot execution is OFF by default. Set GO2_EXECUTE=1 to actually SSH to the
robot; otherwise every "execute" call is a dry run and nothing is sent.
"""

import json
import os
import random
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Make the existing prototype modules importable -------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
ESSENTIAL_DIR = REPO_ROOT / "voice_control_essential"
if str(ESSENTIAL_DIR) not in sys.path:
    sys.path.insert(0, str(ESSENTIAL_DIR))

from intent_parser import (  # noqa: E402
    ALLOWED_ROBOT_ACTIONS,
    MOVEMENT_ACTIONS,
    apply_safety_rules,
    clean_text,
    parse_intent,
    split_command_segments,
)
from llm_intent_parser import (  # noqa: E402
    LLMIntentParserError,
    get_provider_config,
    parse_intent_with_llm,
)
from task_planner import plan_from_intent  # noqa: E402
from transcriber import build_transcriber  # noqa: E402
from world_model import (  # noqa: E402
    load_scene as wm_load_scene,
    plan_to_object as wm_plan_to_object,
    save_scene as wm_save_scene,
)

# --- Robot / SSH configuration (overridable via env) ------------------------
ROBOT_SSH = os.getenv("GO2_SSH", "unitree@192.168.1.200")
ROBOT_PROJECT_DIR = os.getenv("GO2_PROJECT_DIR", "~/jiayu/UnitreeGo2_Voice_Control_Test")
ROBOT_PYTHON = os.getenv("GO2_PYTHON", "/home/unitree/go2_sdk_venv/bin/python")
NETWORK_INTERFACE = os.getenv("GO2_IFACE", "eth0")
ROBOT_SPEAKER_URL = os.getenv("GO2_SPEAKER_URL", "http://192.168.1.200:8000/say")
VISION_SERVER_URL = os.getenv("GO2_VISION_URL", "http://localhost:8002")
# Persistent motion server on the robot (robot_motion_server.py). Initializes the
# SDK once and balances once per run, so a sequence is far faster than SSH-ing a
# fresh robot_command_once.py per pulse. Falls back to SSH if unreachable.
ROBOT_MOTION_URL = os.getenv("GO2_MOTION_URL", "http://192.168.1.200:8001/move")
EXECUTE_ENABLED = os.getenv("GO2_EXECUTE", "0") == "1"

# Reuse one multiplexed SSH connection across commands so each command skips the
# TCP + auth handshake (~hundreds of ms). The master opens on first use and is
# kept alive by ControlPersist; subsequent ssh calls ride the same socket. This
# is what makes a multi-step sequence run without re-connecting every pulse.
# Mirrors the CLI (local_voice_to_robot_ssh.py).
SSH_CONTROL_PATH = os.path.expanduser("~/.ssh/cm-go2-web-%C")
SSH_CONTROL_PERSIST_SECONDS = 120
SSH_BASE_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=5",
    "-o", "ControlMaster=auto",
    "-o", f"ControlPath={SSH_CONTROL_PATH}",
    "-o", f"ControlPersist={SSH_CONTROL_PERSIST_SECONDS}",
]

# Plain SSH does not source ~/.bashrc, so the robot-side cyclonedds binding loads
# the wrong libddsc and any DDS write (motion command) segfaults. Export the
# correct CycloneDDS paths in every robot command, matching the go2-speaker
# systemd service. See docs/go2-audio-output-issue.md.
CYCLONEDDS_HOME = os.getenv("GO2_CYCLONEDDS_HOME", "/home/unitree/cyclonedds_ws/install/cyclonedds")
ROBOT_ENV_PREFIX = (
    f"export CYCLONEDDS_HOME={CYCLONEDDS_HOME} && "
    f"export LD_LIBRARY_PATH={CYCLONEDDS_HOME}/lib:$LD_LIBRARY_PATH && "
)

CHAT_SYSTEM_PROMPT = """
You are Go2, a friendly quadruped robot dog talking through a speaker.
Reply in AT MOST 6 words. One very short phrase only. No punctuation-heavy or
multi-clause answers. The reply is spoken aloud and longer audio plays choppily,
so brevity is critical (e.g. "Doing great, ready to play!").
Do not claim you performed a robot motion unless the control layer did it.
""".strip()

STT_LANGUAGE = "en"
STT_PROMPT = (
    "The speaker will say one robot command or high-level request: "
    "go two stop, go two balance, go two stand up, go two stand down, "
    "go two recovery, go two forward, go two back, go two left, go two right, "
    "I am hungry, find food, find the apple."
)

LOG_FILE = REPO_ROOT / "runtime" / "web_command_log.jsonl"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# Operator-described surroundings (the "assumed world"), edited via the web Scene
# Editor. No vision yet, so this stands in for perception. See world_model.py.
SCENE_FILE = REPO_ROOT / "runtime" / "scene.json"

# API keys saved from the UI are persisted here (gitignored under runtime/).
SETTINGS_FILE = REPO_ROOT / "runtime" / "web_settings.json"
# Keys the UI is allowed to set, mapped to the env var the prototype modules read.
SETTABLE_KEYS = {
    "groq_api_key": "GROQ_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
}

# Cache transcribers per STT mode so models / clients are reused.
_TRANSCRIBERS: dict[str, object] = {}


def load_persisted_settings() -> None:
    """On startup, push any saved API keys into the process environment."""
    if not SETTINGS_FILE.exists():
        return
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    for env_name, value in saved.items():
        if value and not os.getenv(env_name):
            os.environ[env_name] = value


load_persisted_settings()

app = FastAPI(title="Go2 Voice Control API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- helpers ----------------------------------------------------------------
def parse_with_mode(text, parser_mode, llm_provider=None, llm_model=None):
    if parser_mode == "llm":
        return parse_intent_with_llm(text, provider=llm_provider, model=llm_model)
    intent = parse_intent(text)
    intent["parser"] = "rule"
    return intent


# Spoken/label phrasing per action, mirroring robot_action_label in the CLI.
ACTION_LABELS = {
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


def action_label(action):
    return ACTION_LABELS.get(action, (action or "").replace("_", " "))


def parse_command_sequence(text, parser_mode, llm_provider=None, llm_model=None):
    """Split a possibly-compound utterance into ordered command segments and
    parse each one. Returns (segments, commands) where commands is the list of
    executable robot commands in order. A single command yields a one-item list,
    so callers behave exactly as before for non-compound input."""
    segments = split_command_segments(text)
    commands = []
    for segment in segments:
        intent = parse_with_mode(segment, parser_mode, llm_provider, llm_model)
        if intent.get("executable"):
            commands.append(
                {
                    "action": intent.get("action"),
                    "duration": float(intent.get("duration", 0.0)),
                    "label": action_label(intent.get("action")),
                    "segment": segment,
                    "need_confirmation": bool(intent.get("need_confirmation")),
                    "intent": intent,
                }
            )
    return segments, commands


# Locate/approach intents that the world model can turn into real motion.
WORLD_MODEL_ACTIONS = {"find_food", "find_object"}


def scene_based_commands(intent: dict):
    """If the intent is a locate/approach request and its target exists in the
    assumed world model, build an executable orient-and-approach command sequence.

    Returns (commands, world_info, reply) so the find_food / find_object case can
    actually move the robot instead of being rejected. Returns (None, None, None)
    when there is no usable target in the scene."""
    if intent.get("action") not in WORLD_MODEL_ACTIONS:
        return None, None, None

    scene = wm_load_scene(SCENE_FILE)
    plan = wm_plan_to_object(scene, intent.get("target"))
    if not plan:
        return None, None, None

    commands = []
    for step in plan["steps"]:
        # Each pulse goes through the same deterministic safety layer as any
        # other movement (action allowlist + duration cap + confirmation flag).
        step_intent = apply_safety_rules(
            {
                "original_text": f"[world-model] approach {plan['object']}",
                "intent": "robot_control",
                "action": step["action"],
                "duration": step["duration"],
                "executable": True,
                "need_confirmation": False,
                "reason": f"Orient/approach {plan['object']} (assumed world model).",
            }
        )
        if not step_intent.get("executable"):
            continue
        commands.append(
            {
                "action": step_intent.get("action"),
                "duration": float(step_intent.get("duration", 0.0)),
                "label": action_label(step_intent.get("action")),
                "segment": f"approach {plan['object']}",
                "need_confirmation": bool(step_intent.get("need_confirmation")),
                "intent": step_intent,
            }
        )

    detour = plan.get("detour")
    blocked = plan.get("blocked_by")

    # No executable steps and not blocked => nothing to surface; let the normal
    # chat path handle it. A blocked target still reports (even with zero steps).
    if not commands and not blocked:
        return None, None, None
    world_info = {
        "used": True,
        "assumed": True,
        "object": plan["object"],
        "bearing_deg": plan["bearing_deg"],
        "distance_m": plan["distance_m"],
        "direction": plan["direction"],
        "step_count": len(commands),
        "detour_around": detour,
        "blocked_by": blocked,
    }
    # Honest, deterministic reply: it states an ASSUMPTION and never claims to
    # grasp/fetch (the robot has no manipulator). Kept short for the choppy speaker.
    if blocked:
        reply = f"A {blocked} is blocking the way to the {plan['object']}. I can't get around it."
    elif detour:
        reply = f"A {detour} is in the way. Going around to the {plan['object']}, but I can't grab it."
    else:
        reply = f"The {plan['object']} is {plan['direction']}. Heading over, but I can't grab it."
    return commands, world_info, reply


def scene_chat(reply: str, voice_output: str) -> dict:
    """Wrap a deterministic world-model reply like maybe_chat_reply does, speaking
    it on the robot when requested instead of asking the LLM for a phrase."""
    out = {"chat_reply": reply}
    if voice_output == "robot":
        speak_result = speak_on_robot(reply)
        out["spoke_on_robot"] = bool(speak_result.get("ok"))
        if not speak_result.get("ok"):
            out["speak_error"] = speak_result.get("error") or json.dumps(speak_result, ensure_ascii=False)
    return out


def log_event(event: dict) -> None:
    event = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


_SPORT_RET_RE = re.compile(r"ret:\s*\(?\s*(-?\d+)")


def robot_output_error(stdout: str) -> str | None:
    """The robot-side script exits 0 even when the SDK call fails (e.g. the sport
    service rejects the request). Detect those failures from its stdout so we do
    not report a false 'sent to robot'. Returns a short error string or None."""
    if not stdout:
        return None
    if "send request error" in stdout:
        # Almost always: robot motion mode is not active (low battery / sport
        # service off). Surface the SDK return code if present.
        codes = [c for c in _SPORT_RET_RE.findall(stdout) if c != "0"]
        detail = f" (sdk ret {codes[0]})" if codes else ""
        return f"Robot rejected the command{detail}: motion service not active (check battery / sport mode)."
    nonzero = [c for c in _SPORT_RET_RE.findall(stdout) if c != "0"]
    if nonzero:
        return f"Robot SDK call failed (ret {nonzero[0]})."
    return None


def send_command_via_http(command: str, duration: float = 0.0) -> dict:
    """Send the action to the persistent motion server on the robot.

    Raises urllib URLError (connection refused / timeout) when the server is
    unreachable, so the caller can fall back to SSH. An HTTP error or an ok:false
    body is a real failure and is returned (never retried via SSH, to avoid
    executing the same motion twice)."""
    payload = json.dumps(
        {"action": command, "duration": duration, "iface": NETWORK_INTERFACE}
    ).encode("utf-8")
    request = urllib.request.Request(
        ROBOT_MOTION_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "via": "motion-server", "error": f"Motion server HTTP {exc.code}: {body}"}

    out = {"ok": bool(data.get("ok")), "via": "motion-server", "result": data}
    if not data.get("ok"):
        out["error"] = data.get("error") or (
            f"Robot rejected '{command}'"
            + (f" (sdk ret {data.get('ret')})" if data.get("ret") is not None else "")
        )
    return out


def send_command_to_robot(command: str, duration: float = 0.0) -> dict:
    """Prefer the persistent motion server; fall back to the per-call SSH path if
    it is unreachable (so the system still works before the server is started)."""
    try:
        return send_command_via_http(command, duration)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        result = send_command_via_ssh(command, duration)
        result["motion_server_error"] = f"unreachable, used SSH fallback: {exc}"
        return result


def send_command_via_ssh(command: str, duration: float = 0.0) -> dict:
    """Run the same robot_command_once.py call the CLI uses, over SSH."""
    remote_cmd = (
        f"{ROBOT_ENV_PREFIX}"
        f"cd {ROBOT_PROJECT_DIR} && "
        f"{ROBOT_PYTHON} robot_command_once.py {NETWORK_INTERFACE} {command} {duration:.2f}"
    )
    try:
        result = subprocess.run(
            ["ssh", *SSH_BASE_OPTS, ROBOT_SSH, remote_cmd],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "SSH command timed out."}
    except FileNotFoundError:
        return {"ok": False, "error": "ssh client not found on this machine."}

    sdk_error = robot_output_error(result.stdout)
    ok = result.returncode == 0 and sdk_error is None
    out = {
        "ok": ok,
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }
    if sdk_error:
        out["error"] = sdk_error
    return out


def _chat_completions_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def generate_chat_reply(text: str, provider: str | None = None, model: str | None = None) -> str:
    """Free-form conversational reply from the configured LLM (Go2 persona)."""
    config = get_provider_config(provider=provider, model=model)
    payload = {
        "model": config["model"],
        "temperature": 0.4,
        "messages": [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": text.strip()},
        ],
        "stream": False,
        "max_tokens": 24,
    }
    request = urllib.request.Request(
        _chat_completions_url(config["base_url"]),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "go2-voice-control-chat/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LLMIntentParserError(f"Chat HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise LLMIntentParserError(f"Chat request failed: {exc}") from exc

    reply = data["choices"][0]["message"]["content"].strip()
    return " ".join(reply.split())


SUGGEST_SYSTEM_PROMPT = """
You suggest what a user might say next to a Unitree Go2 robot dog through a
voice-control web app. The user can give robot commands or just chat with Go2.

Supported robot commands (use natural phrasings of these): stand up, stand down /
sit down, balance, recovery, move forward, move backward, turn left, turn right, stop.
The user can also chat casually (greetings, questions, small talk) or make
high-level requests (I'm hungry, find the apple).

Given the recent context, propose 6 SHORT phrases (2-6 words each) the user is
likely to say next. Make them feel like a natural continuation of the
conversation. Mix a few robot commands with a couple of chat lines. Vary them.
Return ONLY a JSON object: {"suggestions": ["...", "...", ...]} with exactly 6 items.
""".strip()

# Used when no LLM is available, or to seed before the first LLM call.
FALLBACK_SUGGESTIONS = [
    "go two stand up",
    "sit down",
    "move forward a little",
    "turn left",
    "turn right",
    "balance",
    "recovery stand",
    "stop",
    "how are you, Go2?",
    "what can you do?",
    "good boy!",
    "I am hungry",
    "find the apple",
    "are you ready?",
    "come back here",
    "well done",
]


def _fallback_suggestions(avoid):
    avoid_set = {a.strip().lower() for a in (avoid or [])}
    pool = [s for s in FALLBACK_SUGGESTIONS if s.lower() not in avoid_set]
    random.shuffle(pool)
    return pool[:6] if len(pool) >= 6 else (pool + FALLBACK_SUGGESTIONS)[:6]


def generate_suggestions(context: str, avoid=None, provider=None, model=None) -> dict:
    """Ask the LLM for likely next utterances; fall back to a shuffled pool."""
    avoid = avoid or []
    try:
        config = get_provider_config(provider=provider, model=model)
    except Exception:
        return {"suggestions": _fallback_suggestions(avoid), "source": "fallback"}

    user_msg = "Recent context:\n" + (context.strip() or "(conversation just started)")
    if avoid:
        user_msg += "\n\nDo NOT repeat any of these: " + ", ".join(avoid[:12])

    payload = {
        "model": config["model"],
        "temperature": 1.0,
        "messages": [
            {"role": "system", "content": SUGGEST_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
        "max_tokens": 160,
    }
    if config["provider"] in {"groq", "deepseek", "openai"}:
        payload["response_format"] = {"type": "json_object"}

    request = urllib.request.Request(
        _chat_completions_url(config["base_url"]),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "go2-voice-control-suggest/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        items = parsed.get("suggestions") if isinstance(parsed, dict) else parsed
        cleaned = []
        avoid_set = {a.strip().lower() for a in avoid}
        for item in items or []:
            text = " ".join(str(item).split()).strip()
            if text and text.lower() not in avoid_set and text not in cleaned:
                cleaned.append(text)
        if len(cleaned) >= 3:
            return {"suggestions": cleaned[:6], "source": "llm"}
    except Exception:
        pass

    return {"suggestions": _fallback_suggestions(avoid), "source": "fallback"}


def maybe_chat_reply(text: str, intent: dict, provider=None, model=None, voice_output="off") -> dict:
    """If the input is not an executable robot action, generate a chat reply.

    When voice_output == 'robot', the reply is also spoken on the robot here
    (server-side) so it does not depend on the browser firing a second call.
    """
    if intent.get("executable"):
        return {}
    if not text.strip():
        return {}
    try:
        reply = generate_chat_reply(text, provider=provider, model=model)
    except Exception as exc:  # noqa: BLE001 - chat is best-effort, never blocks parsing
        return {"chat_error": str(exc)}

    out = {"chat_reply": reply}
    if voice_output == "robot":
        speak_result = speak_on_robot(reply)
        out["spoke_on_robot"] = bool(speak_result.get("ok"))
        if not speak_result.get("ok"):
            out["speak_error"] = speak_result.get("error") or json.dumps(speak_result, ensure_ascii=False)
    return out


def _speaker_base_url() -> str:
    """Robot speaker server base URL derived from the /say endpoint."""
    url = ROBOT_SPEAKER_URL
    return url[:-4] if url.endswith("/say") else url.rsplit("/", 1)[0]


def robot_volume_get() -> dict:
    request = urllib.request.Request(f"{_speaker_base_url()}/volume", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}


def robot_volume_set(level: int) -> dict:
    payload = json.dumps({"level": level, "iface": NETWORK_INTERFACE}).encode("utf-8")
    request = urllib.request.Request(
        f"{_speaker_base_url()}/volume",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}"}
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}


def speak_on_robot(message: str) -> dict:
    """Send text to the robot speaker server (piper/paplay TTS on the Go2)."""
    payload = json.dumps({"text": message, "iface": NETWORK_INTERFACE, "verbose": True}).encode("utf-8")
    request = urllib.request.Request(
        ROBOT_SPEAKER_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"Speaker HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}"}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": f"Speaker server unreachable at {ROBOT_SPEAKER_URL}: {exc}"}

    try:
        result = json.loads(body)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"Speaker returned non-JSON: {body}"}
    return result


def call_vision_server(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """Call the local vision server. Returns the parsed JSON response or an error dict."""
    url = VISION_SERVER_URL.rstrip("/") + "/" + path.lstrip("/")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"Vision server HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}"}
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        return {"ok": False, "error": f"Vision server unreachable: {exc}"}


def handle_vision_intent(intent: dict, voice_output: str = "off") -> dict:
    """Route a vision_control intent to the vision server; return a reply dict."""
    action = intent.get("action")
    target = (intent.get("target") or "").strip().lower() or None

    if action == "follow_person":
        result = call_vision_server("/track", "POST", {"name": target})
        reply = (
            f"Now following {target}." if target else "Following whoever I see."
        ) if result.get("ok") else f"Could not start tracking: {result.get('error')}"

    elif action == "stop_following":
        result = call_vision_server("/track/stop", "POST", {})
        reply = "Stopped following." if result.get("ok") else f"Stop-tracking failed: {result.get('error')}"

    elif action == "identify_person":
        result = call_vision_server("/detect", "GET")
        faces = result.get("faces", [])
        named = [f for f in faces if f.get("name")]
        if not result.get("ok", True) and "error" in result:
            reply = f"Vision server error: {result['error']}"
        elif not faces:
            reply = "I don't see anyone."
        elif not named:
            reply = f"I see {len(faces)} face(s) but don't recognise them."
        elif len(named) == 1:
            reply = f"That's {named[0]['name']}."
        else:
            reply = "I see " + ", ".join(f["name"] for f in named) + "."
        result["reply"] = reply

    else:
        return {"ok": False, "error": f"Unknown vision action: {action}"}

    out = {"vision_result": result, "chat_reply": reply}
    if voice_output == "robot":
        speak_result = speak_on_robot(reply)
        out["spoke_on_robot"] = bool(speak_result.get("ok"))
        if not speak_result.get("ok"):
            out["speak_error"] = speak_result.get("error")
    return out


def get_transcriber(stt_mode: str):
    if stt_mode not in _TRANSCRIBERS:
        _TRANSCRIBERS[stt_mode] = build_transcriber(stt_mode, language=STT_LANGUAGE)
    return _TRANSCRIBERS[stt_mode]


# --- request models ---------------------------------------------------------
class TextIntentRequest(BaseModel):
    text: str
    parser: str = "rule"
    llm_provider: str | None = None
    llm_model: str | None = None
    voice_output: str = "off"  # off | browser | robot


class ActionRequest(BaseModel):
    command: str
    duration: float = 0.8
    confirmed: bool = False


class ExecuteRequest(BaseModel):
    command: str
    duration: float = 0.0
    transcript: str = ""
    parser: str = "rule"


class SuggestRequest(BaseModel):
    context: str = ""
    avoid: list[str] = []
    llm_provider: str | None = None
    llm_model: str | None = None


class SpeakRequest(BaseModel):
    text: str


class VolumeRequest(BaseModel):
    level: int


class SettingsRequest(BaseModel):
    groq_api_key: str | None = None
    openai_api_key: str | None = None


class SceneRequest(BaseModel):
    # Loose dicts; world_model.save_scene validates and normalizes each object.
    objects: list[dict] = []


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    return f"…{value[-4:]}" if len(value) > 4 else "set"


def settings_status() -> dict:
    return {
        "groq_api_key_set": bool(os.getenv("GROQ_API_KEY")),
        "groq_api_key_hint": _mask(os.getenv("GROQ_API_KEY")),
        "openai_api_key_set": bool(os.getenv("OPENAI_API_KEY")),
        "openai_api_key_hint": _mask(os.getenv("OPENAI_API_KEY")),
    }


# --- routes -----------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    return settings_status()


@app.post("/api/settings")
def save_settings(req: SettingsRequest):
    """Save API keys into the process env and persist them (gitignored)."""
    saved = {}
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saved = {}

    updated = []
    for field, env_name in SETTABLE_KEYS.items():
        value = getattr(req, field, None)
        if value is None:
            continue
        value = value.strip()
        if value:
            os.environ[env_name] = value
            saved[env_name] = value
            updated.append(field)
        else:  # empty string clears the key
            os.environ.pop(env_name, None)
            saved.pop(env_name, None)
            updated.append(field)

    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")

    # Cached transcribers captured the old key at build time; drop them.
    _TRANSCRIBERS.clear()

    return {"updated": updated, **settings_status()}


@app.get("/api/config")
def config():
    return {
        "allowed_actions": sorted(ALLOWED_ROBOT_ACTIONS),
        "movement_actions": sorted(MOVEMENT_ACTIONS),
        "parsers": ["rule", "llm"],
        "llm_providers": ["groq", "deepseek", "openai", "custom"],
        "stt_modes": ["local", "openai", "groq"],
        "execute_enabled": EXECUTE_ENABLED,
        "robot": {
            "ssh": ROBOT_SSH,
            "iface": NETWORK_INTERFACE,
            "project_dir": ROBOT_PROJECT_DIR,
            "speaker_url": ROBOT_SPEAKER_URL,
        },
    }


@app.post("/api/intent/text")
def intent_from_text(req: TextIntentRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    _segments, commands = parse_command_sequence(text, req.parser, req.llm_provider, req.llm_model)
    # Primary intent for display: first executable command, else a single parse
    # so non-command input still yields a sensible intent / chat reply.
    intent = commands[0]["intent"] if commands else parse_with_mode(
        text, req.parser, req.llm_provider, req.llm_model
    )
    plan = plan_from_intent(intent)

    # No direct robot command? Try the assumed world model: a known target turns
    # a locate/approach request into an executable orient-and-approach sequence.
    world = None
    vision = None
    if not commands:
        if intent.get("intent") == "vision_control":
            vision_out = handle_vision_intent(intent, req.voice_output)
            vision = vision_out.get("vision_result")
            chat = {k: v for k, v in vision_out.items() if k != "vision_result"}
        else:
            scene_cmds, world, scene_reply = scene_based_commands(intent)
            if scene_cmds:
                commands = scene_cmds
            chat = (
                scene_chat(scene_reply, req.voice_output)
                if world
                else maybe_chat_reply(text, intent, req.llm_provider, req.llm_model, req.voice_output)
            )
    else:
        chat = maybe_chat_reply(text, intent, req.llm_provider, req.llm_model, req.voice_output)
    log_event(
        {
            "source": "text",
            "transcript": text,
            "cleaned_text": clean_text(text),
            "intent": intent,
            "commands_count": len(commands),
            "parser_mode": req.parser,
            "executed": False,
            **({"world_model": world} if world else {}),
            **({"vision": vision} if vision else {}),
            **({"chat_reply": chat.get("chat_reply")} if chat.get("chat_reply") else {}),
        }
    )
    return {
        "transcript": text,
        "cleaned_text": clean_text(text),
        "intent": intent,
        "commands": commands,
        "plan": plan,
        "world_model": world,
        "vision": vision,
        **chat,
    }


@app.post("/api/intent/audio")
async def intent_from_audio(
    file: UploadFile = File(...),
    parser: str = Form("rule"),
    stt: str = Form("groq"),
    llm_provider: str | None = Form(None),
    llm_model: str | None = Form(None),
    voice_output: str = Form("off"),
):
    suffix = Path(file.filename or "clip.webm").suffix or ".webm"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty audio upload")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        transcriber = get_transcriber(stt)
        transcript = transcriber.transcribe(tmp_path, prompt=STT_PROMPT)
    except Exception as exc:  # noqa: BLE001 - surface any STT failure to the UI
        raise HTTPException(status_code=502, detail=f"Transcription failed: {exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    _segments, commands = parse_command_sequence(transcript, parser, llm_provider, llm_model)
    intent = commands[0]["intent"] if commands else parse_with_mode(
        transcript, parser, llm_provider, llm_model
    )
    plan = plan_from_intent(intent)

    world = None
    vision = None
    if not commands:
        if intent.get("intent") == "vision_control":
            vision_out = handle_vision_intent(intent, voice_output)
            vision = vision_out.get("vision_result")
            chat = {k: v for k, v in vision_out.items() if k != "vision_result"}
        else:
            scene_cmds, world, scene_reply = scene_based_commands(intent)
            if scene_cmds:
                commands = scene_cmds
            chat = (
                scene_chat(scene_reply, voice_output)
                if world
                else maybe_chat_reply(transcript, intent, llm_provider, llm_model, voice_output)
            )
    else:
        chat = maybe_chat_reply(transcript, intent, llm_provider, llm_model, voice_output)
    log_event(
        {
            "source": "audio",
            "stt": stt,
            "transcript": transcript,
            "cleaned_text": clean_text(transcript),
            "intent": intent,
            "commands_count": len(commands),
            "parser_mode": parser,
            "executed": False,
            **({"world_model": world} if world else {}),
            **({"vision": vision} if vision else {}),
            **({"chat_reply": chat.get("chat_reply")} if chat.get("chat_reply") else {}),
        }
    )
    return {
        "transcript": transcript,
        "cleaned_text": clean_text(transcript),
        "intent": intent,
        "commands": commands,
        "plan": plan,
        "world_model": world,
        "vision": vision,
        **chat,
    }


@app.post("/api/action")
def direct_action(req: ActionRequest):
    """Build a safety-checked intent for an action button, then maybe execute it."""
    intent = apply_safety_rules(
        {
            "original_text": f"[button] {req.command}",
            "intent": "robot_control",
            "action": req.command,
            "duration": req.duration,
            "executable": True,
            "need_confirmation": False,
            "reason": "Direct action button.",
        }
    )

    if not intent.get("executable"):
        log_event({"source": "button", "intent": intent, "executed": False})
        return {"intent": intent, "executed": False, "result": None}

    if intent.get("need_confirmation") and not req.confirmed:
        return {"intent": intent, "executed": False, "needs_confirmation": True, "result": None}

    duration = float(intent.get("duration", 0.0))
    if not EXECUTE_ENABLED:
        log_event({"source": "button", "intent": intent, "executed": False, "dry_run": True})
        return {
            "intent": intent,
            "executed": False,
            "dry_run": True,
            "result": {"ok": True, "message": "Dry run: GO2_EXECUTE is off, nothing sent."},
        }

    result = send_command_to_robot(intent["action"], duration=duration)
    log_event({"source": "button", "intent": intent, "executed": result.get("ok", False), "result": result})
    return {"intent": intent, "executed": result.get("ok", False), "result": result}


@app.post("/api/execute")
def execute(req: ExecuteRequest):
    """Execute an already-parsed command (used by the 'send to robot' button)."""
    intent = apply_safety_rules(
        {
            "original_text": req.transcript or f"[execute] {req.command}",
            "intent": "robot_control",
            "action": req.command,
            "duration": req.duration,
            "executable": True,
            "need_confirmation": False,
            "reason": "Execute confirmed intent.",
        }
    )
    if not intent.get("executable"):
        raise HTTPException(status_code=400, detail=intent.get("reason", "Not executable."))

    duration = float(intent.get("duration", 0.0))
    if not EXECUTE_ENABLED:
        log_event({"source": "execute", "intent": intent, "executed": False, "dry_run": True})
        return {
            "executed": False,
            "dry_run": True,
            "result": {"ok": True, "message": "Dry run: GO2_EXECUTE is off, nothing sent."},
        }

    result = send_command_to_robot(intent["action"], duration=duration)
    log_event({"source": "execute", "intent": intent, "executed": result.get("ok", False), "result": result})
    return {"executed": result.get("ok", False), "result": result}


@app.post("/api/suggestions")
def suggestions(req: SuggestRequest):
    return generate_suggestions(req.context, req.avoid, req.llm_provider, req.llm_model)


@app.post("/api/speak")
def speak(req: SpeakRequest):
    """Play a phrase through the robot's speaker."""
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    result = speak_on_robot(text)
    return {"ok": bool(result.get("ok")), "result": result}


@app.get("/api/volume")
def get_volume():
    return robot_volume_get()


@app.post("/api/volume")
def set_volume(req: VolumeRequest):
    level = max(0, min(int(req.level), 10))
    return robot_volume_set(level)


@app.get("/api/scene")
def get_scene():
    """The assumed world model the operator drew in the Scene Editor."""
    return wm_load_scene(SCENE_FILE)


@app.post("/api/scene")
def post_scene(req: SceneRequest):
    """Persist the edited scene. Returns the normalized scene that was saved."""
    return wm_save_scene(SCENE_FILE, {"objects": req.objects})


class VisionTrackRequest(BaseModel):
    name: str | None = None


class VisionEnrollRequest(BaseModel):
    name: str
    image_b64: str


@app.get("/api/vision/status")
def vision_status():
    """Proxy to the vision server health endpoint."""
    return call_vision_server("/health")


@app.get("/api/vision/detect")
def vision_detect():
    """One-shot face detection + identification from the camera."""
    return call_vision_server("/detect")


@app.post("/api/vision/track")
def vision_track(req: VisionTrackRequest):
    """Start face-tracking mode. Pass name=null to follow any face."""
    return call_vision_server("/track", "POST", {"name": req.name})


@app.post("/api/vision/track/stop")
def vision_track_stop():
    """Stop face-tracking mode."""
    return call_vision_server("/track/stop", "POST", {})


@app.post("/api/vision/enroll")
def vision_enroll(req: VisionEnrollRequest):
    """Register a face with the vision server. image_b64 is base64-encoded JPEG/PNG."""
    return call_vision_server("/enroll", "POST", {"name": req.name, "image_b64": req.image_b64})


@app.delete("/api/vision/enroll/{name}")
def vision_remove(name: str):
    """Remove an enrolled person from the vision server."""
    return call_vision_server(f"/enroll/{name}", "DELETE")


@app.get("/api/logs")
def logs(limit: int = 50):
    if not LOG_FILE.exists():
        return {"events": []}
    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    events = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    events.reverse()  # newest first
    return {"events": events}


@app.delete("/api/logs")
def clear_logs():
    """Wipe the command history file. Used by the 'Clear' button in the UI."""
    if LOG_FILE.exists():
        LOG_FILE.write_text("", encoding="utf-8")
    return {"cleared": True}
