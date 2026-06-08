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
)
from llm_intent_parser import (  # noqa: E402
    LLMIntentParserError,
    get_provider_config,
    parse_intent_with_llm,
)
from task_planner import plan_from_intent  # noqa: E402
from transcriber import build_transcriber  # noqa: E402

# --- Robot / SSH configuration (overridable via env) ------------------------
ROBOT_SSH = os.getenv("GO2_SSH", "unitree@192.168.1.200")
ROBOT_PROJECT_DIR = os.getenv("GO2_PROJECT_DIR", "~/jiayu/UnitreeGo2_Voice_Control_Test")
ROBOT_PYTHON = os.getenv("GO2_PYTHON", "/home/unitree/go2_sdk_venv/bin/python")
NETWORK_INTERFACE = os.getenv("GO2_IFACE", "eth0")
ROBOT_SPEAKER_URL = os.getenv("GO2_SPEAKER_URL", "http://192.168.1.200:8000/say")
EXECUTE_ENABLED = os.getenv("GO2_EXECUTE", "0") == "1"

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


def log_event(event: dict) -> None:
    event = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def send_command_to_robot(command: str, duration: float = 0.0) -> dict:
    """Run the same robot_command_once.py call the CLI uses, over SSH."""
    remote_cmd = (
        f"cd {ROBOT_PROJECT_DIR} && "
        f"{ROBOT_PYTHON} robot_command_once.py {NETWORK_INTERFACE} {command} {duration:.2f}"
    )
    try:
        result = subprocess.run(
            ["ssh", ROBOT_SSH, remote_cmd],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "SSH command timed out."}
    except FileNotFoundError:
        return {"ok": False, "error": "ssh client not found on this machine."}

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


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

    intent = parse_with_mode(text, req.parser, req.llm_provider, req.llm_model)
    plan = plan_from_intent(intent)
    chat = maybe_chat_reply(text, intent, req.llm_provider, req.llm_model, req.voice_output)
    log_event(
        {
            "source": "text",
            "transcript": text,
            "cleaned_text": clean_text(text),
            "intent": intent,
            "parser_mode": req.parser,
            "executed": False,
            **({"chat_reply": chat["chat_reply"]} if "chat_reply" in chat else {}),
        }
    )
    return {
        "transcript": text,
        "cleaned_text": clean_text(text),
        "intent": intent,
        "plan": plan,
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

    intent = parse_with_mode(transcript, parser, llm_provider, llm_model)
    plan = plan_from_intent(intent)
    chat = maybe_chat_reply(transcript, intent, llm_provider, llm_model, voice_output)
    log_event(
        {
            "source": "audio",
            "stt": stt,
            "transcript": transcript,
            "cleaned_text": clean_text(transcript),
            "intent": intent,
            "parser_mode": parser,
            "executed": False,
            **({"chat_reply": chat["chat_reply"]} if "chat_reply" in chat else {}),
        }
    )
    return {
        "transcript": transcript,
        "cleaned_text": clean_text(transcript),
        "intent": intent,
        "plan": plan,
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
