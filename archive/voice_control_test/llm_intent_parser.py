import json
import os
import re
import urllib.error
import urllib.request

from intent_parser import apply_safety_rules, parse_intent as parse_rule_based_intent


PROVIDER_CONFIGS = {
    "groq": {
        "api_key_env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.1-8b-instant",
    },
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-flash",
    },
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
}

DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()

SYSTEM_PROMPT = """
You are an intent parser for a Unitree Go2 robot voice-control prototype.
Convert the user's natural language into exactly one JSON object.

Allowed executable high-level robot actions:
- stop
- balance
- stand_up
- stand_down
- recovery
- forward
- backward
- turn_left
- turn_right

Supported non-executable high-level intents:
- need_food with action find_food and target food
- object_request with action find_object and a target object
- unknown with action none

Rules:
- Output JSON only. No markdown.
- Never invent low-level motor commands.
- Never output shell commands or code.
- Requests to run code, Python, scripts, programs, shell commands, terminal
  commands, SSH commands, or operating-system commands on the robot are
  unsupported. They must map to intent unknown, action none, executable false.
- If the transcript negates a robot action, for example "can't sit down",
  "do not sit down", "don't move forward", or "do not turn", do not execute
  that action. Map it to intent unknown, action none, executable false unless
  the user clearly asks for stop.
- If the request is a direct supported robot command, use intent robot_control.
- Interpret "sit down", "lie down", "lay down", "stand down", and "go down"
  as action stand_down.
- Interpret "stand up", "get up", and "rise up" as action stand_up.
- Interpret "recovery", "recover", and "recovery stand" as action recovery.
- Interpret "step back", "take a step back", "move back", and "back up" as action backward.
- Interpret "step forward", "move ahead", and "walk ahead" as action forward.
- Interpret "turn to your left" or "rotate left" as action turn_left.
- Interpret "turn to your right" or "rotate right" as action turn_right.
- If an ASR transcript contains repeated or conflicting commands, prioritize
  safety: stop first, then recovery, then the first clear supported command.
- If the request is about hunger or food, use intent need_food, action find_food,
  target food, executable false.
- If the request asks for an object such as an apple, use intent object_request,
  action find_object, target object name, executable false.
- If the request is not supported, use intent unknown, action none, executable false.
- Movement actions should have duration 0.8 and need_confirmation true.
- Stop should be executable true and need_confirmation false.

Required JSON keys:
original_text, intent, action, duration, executable, need_confirmation, reason.
Optional JSON key:
target.

Example JSON output:
{
  "original_text": "I feel hungry",
  "intent": "need_food",
  "action": "find_food",
  "target": "food",
  "duration": 0.0,
  "executable": false,
  "need_confirmation": false,
  "reason": "The user is expressing hunger, which requires perception or manipulation before execution."
}
""".strip()


class LLMIntentParserError(Exception):
    pass


def compact_text_for_llm(text, max_chars=500):
    text = str(text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def infer_provider():
    if os.getenv("LLM_PROVIDER"):
        return os.getenv("LLM_PROVIDER").lower()
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    if os.getenv("DEEPSEEK_API_KEY"):
        return "deepseek"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return DEFAULT_PROVIDER


def get_provider_config(provider=None, model=None):
    provider = (provider or infer_provider()).lower()
    config = PROVIDER_CONFIGS.get(provider)

    if config is None:
        if provider != "custom":
            raise LLMIntentParserError(
                f"Unknown LLM_PROVIDER '{provider}'. Use groq, deepseek, openai, or custom."
            )

        config = {
            "api_key_env": "LLM_API_KEY",
            "base_url": os.getenv("LLM_BASE_URL", ""),
            "default_model": os.getenv("LLM_MODEL", ""),
        }

    provider_model_env = f"{provider.upper()}_MODEL"
    selected_model = (
        model
        or os.getenv("LLM_MODEL")
        or os.getenv(provider_model_env)
        or os.getenv("OPENAI_INTENT_MODEL")
        or config["default_model"]
    )

    base_url = os.getenv("LLM_BASE_URL", config["base_url"]).rstrip("/")
    api_key = os.getenv("LLM_API_KEY") or os.getenv(config["api_key_env"])

    if not base_url:
        raise LLMIntentParserError("LLM_BASE_URL is required for custom providers.")
    if not selected_model:
        raise LLMIntentParserError("LLM_MODEL is required for custom providers.")
    if not api_key:
        raise LLMIntentParserError(
            f"Missing API key. Set LLM_API_KEY or {config['api_key_env']}."
        )

    return {
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "model": selected_model,
    }


def extract_json_object(text):
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        raise LLMIntentParserError("LLM did not return a JSON object.")

    return json.loads(match.group(0))


def _string_value(value, default):
    if value is None:
        return default
    return str(value).strip()


def _bool_value(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


def _float_value(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_llm_intent(original_text, candidate):
    if not isinstance(candidate, dict):
        raise LLMIntentParserError("LLM JSON output must be an object.")

    normalized = {
        "original_text": original_text,
        "intent": _string_value(candidate.get("intent"), "unknown"),
        "action": _string_value(candidate.get("action"), "none"),
        "duration": _float_value(candidate.get("duration"), 0.0),
        "executable": _bool_value(candidate.get("executable")),
        "need_confirmation": _bool_value(candidate.get("need_confirmation")),
        "reason": _string_value(candidate.get("reason"), "LLM intent parser output."),
    }

    target = candidate.get("target")
    if target is not None:
        normalized["target"] = _string_value(target, "")

    return apply_safety_rules(normalized)


def _chat_completions_url(base_url):
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def call_llm_intent_parser(text, provider=None, model=None):
    config = get_provider_config(provider=provider, model=model)
    llm_text = compact_text_for_llm(text)
    payload = {
        "model": config["model"],
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": llm_text},
        ],
        "stream": False,
        "max_tokens": 400,
    }

    if config["provider"] in {"groq", "deepseek", "openai"}:
        payload["response_format"] = {"type": "json_object"}

    if config["provider"] == "deepseek":
        payload["thinking"] = {"type": "disabled"}

    request = urllib.request.Request(
        _chat_completions_url(config["base_url"]),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "go2-voice-control-intent-parser/0.1",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise LLMIntentParserError(
            f"{config['provider']} API HTTP {exc.code}: {error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise LLMIntentParserError(f"{config['provider']} API request failed: {exc}") from exc

    data = json.loads(response_body)
    try:
        return data["choices"][0]["message"]["content"], config
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMIntentParserError(f"Unexpected LLM API response: {response_body}") from exc


def parse_intent_with_llm(text, provider=None, model=None, fallback=True):
    try:
        raw_output, config = call_llm_intent_parser(text, provider=provider, model=model)
        candidate = extract_json_object(raw_output)
        intent = normalize_llm_intent(text, candidate)
        intent["parser"] = "llm"
        intent["llm_provider"] = config["provider"]
        intent["llm_model"] = config["model"]
        return intent
    except Exception as exc:
        if not fallback:
            raise

        intent = parse_rule_based_intent(text)
        intent["parser"] = "rule_fallback"
        intent["llm_error"] = str(exc)
        intent["llm_provider"] = provider or infer_provider()
        return intent


def main():
    print("LLM intent parser test mode.")
    print("Set GROQ_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY to use an LLM.")
    print("Optional: set LLM_PROVIDER and LLM_MODEL. Otherwise this falls back to rules.")
    print("Type a natural language command. Press Ctrl+C to quit.\n")

    while True:
        text = input("User command: ")
        result = parse_intent_with_llm(text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print()


if __name__ == "__main__":
    main()
