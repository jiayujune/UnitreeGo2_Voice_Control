import json
import re


ALLOWED_ROBOT_ACTIONS = {
    "stop",
    "balance",
    "stand_up",
    "stand_down",
    "recovery",
    "forward",
    "backward",
    "turn_left",
    "turn_right",
}

MOVEMENT_ACTIONS = {
    "forward",
    "backward",
    "turn_left",
    "turn_right",
}

MAX_MOVEMENT_DURATION_SECONDS = 1.0
DEFAULT_MOVEMENT_DURATION_SECONDS = 0.8

NEGATED_ACTION_PATTERNS = [
    r"\b(can't|cannot|don't|do not|not)\s+(sit down|stand down|go down|lie down|lay down)\b",
    r"\b(can't|cannot|don't|do not|not)\s+(stand up|get up|rise up)\b",
    r"\b(can't|cannot|don't|do not|not)\s+(move|go|walk|step)\s+(forward|back|backward)\b",
    r"\b(can't|cannot|don't|do not|not)\s+(turn|rotate)\s+(left|right)\b",
]


def clean_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9'\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def has_negated_action(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in NEGATED_ACTION_PATTERNS)


def apply_safety_rules(intent: dict) -> dict:
    """
    Normalize parser output before anything can be sent to the robot.

    Later, an LLM can produce the first draft of this JSON, but this function
    should still be kept as a deterministic safety layer.
    """

    result = dict(intent)
    action = result.get("action", "none")
    executable = bool(result.get("executable", False))

    if not executable:
        return result

    if action not in ALLOWED_ROBOT_ACTIONS:
        result["executable"] = False
        result["need_confirmation"] = False
        result["duration"] = 0.0
        result["reason"] = (
            f"Action '{action}' is not in the allowed high-level SDK action list."
        )
        return result

    if action == "stop":
        result["duration"] = 0.0
        result["need_confirmation"] = False
        return result

    if action in MOVEMENT_ACTIONS:
        duration = float(result.get("duration", DEFAULT_MOVEMENT_DURATION_SECONDS))
        duration = max(0.1, min(duration, MAX_MOVEMENT_DURATION_SECONDS))
        result["duration"] = duration
        result["need_confirmation"] = True
        return result

    result["duration"] = 0.0
    result["need_confirmation"] = False
    return result


def build_intent(
    *,
    original_text: str,
    intent: str,
    action: str,
    duration: float = 0.0,
    executable: bool = False,
    need_confirmation: bool = False,
    reason: str,
    target: str | None = None,
) -> dict:
    result = {
        "original_text": original_text,
        "intent": intent,
        "action": action,
        "duration": duration,
        "executable": executable,
        "need_confirmation": need_confirmation,
        "reason": reason,
    }

    if target is not None:
        result["target"] = target

    return apply_safety_rules(result)


def parse_intent(text: str) -> dict:
    """
    First version of the intent parser.

    This version is rule-based.
    Later, we can replace this function with an LLM-based parser
    while keeping the same JSON output format.
    """

    original_text = text
    text = clean_text(text)

    if has_negated_action(text):
        return build_intent(
            original_text=original_text,
            intent="unknown",
            action="none",
            executable=False,
            reason="Negated robot action detected. No command will be executed.",
        )

    # ---------- emergency / stop ----------
    if any(phrase in text for phrase in [
        "stop",
        "stop moving",
        "hold on",
        "freeze",
        "do not move",
        "don't move",
    ]):
        return build_intent(
            original_text=original_text,
            intent="robot_control",
            action="stop",
            executable=True,
            reason="Stop command detected. This command is safe and should be executed immediately.",
        )

    # ---------- recovery ----------
    if any(phrase in text for phrase in [
        "recovery",
        "recover",
        "recovery stand",
    ]):
        return build_intent(
            original_text=original_text,
            intent="robot_control",
            action="recovery",
            executable=True,
            reason="Recovery posture command detected.",
        )

    # ---------- posture commands ----------
    if any(phrase in text for phrase in [
        "stand up",
        "standup",
        "get up",
        "rise up",
    ]):
        return build_intent(
            original_text=original_text,
            intent="robot_control",
            action="stand_up",
            executable=True,
            reason="Posture command detected: stand up.",
        )

    if any(phrase in text for phrase in [
        "stand down",
        "standdown",
        "sit down",
        "lie down",
        "lay down",
        "go down",
    ]):
        return build_intent(
            original_text=original_text,
            intent="robot_control",
            action="stand_down",
            executable=True,
            reason="Posture command detected: stand down.",
        )

    if any(phrase in text for phrase in [
        "balance",
        "balance stand",
        "stand still",
        "stay balanced",
    ]):
        return build_intent(
            original_text=original_text,
            intent="robot_control",
            action="balance",
            executable=True,
            reason="Balance posture command detected.",
        )

    # ---------- movement commands ----------
    if any(phrase in text for phrase in [
        "forward",
        "move forward",
        "go forward",
        "walk forward",
        "move ahead",
        "for word",
        "foreword",
    ]):
        return build_intent(
            original_text=original_text,
            intent="robot_control",
            action="forward",
            duration=DEFAULT_MOVEMENT_DURATION_SECONDS,
            executable=True,
            need_confirmation=True,
            reason="Movement command detected. Confirmation is required before execution.",
        )

    if any(phrase in text for phrase in [
        "backward",
        "move backward",
        "go backward",
        "walk backward",
        "move back",
        "go back",
        "back",
    ]):
        return build_intent(
            original_text=original_text,
            intent="robot_control",
            action="backward",
            duration=DEFAULT_MOVEMENT_DURATION_SECONDS,
            executable=True,
            need_confirmation=True,
            reason="Movement command detected. Confirmation is required before execution.",
        )

    if any(phrase in text for phrase in [
        "turn left",
        "left",
        "rotate left",
    ]):
        return build_intent(
            original_text=original_text,
            intent="robot_control",
            action="turn_left",
            duration=DEFAULT_MOVEMENT_DURATION_SECONDS,
            executable=True,
            need_confirmation=True,
            reason="Turning command detected. Confirmation is required before execution.",
        )

    if any(phrase in text for phrase in [
        "turn right",
        "right",
        "rotate right",
    ]):
        return build_intent(
            original_text=original_text,
            intent="robot_control",
            action="turn_right",
            duration=DEFAULT_MOVEMENT_DURATION_SECONDS,
            executable=True,
            need_confirmation=True,
            reason="Turning command detected. Confirmation is required before execution.",
        )

    # ---------- high-level human intent ----------
    if any(phrase in text for phrase in [
        "i am hungry",
        "i'm hungry",
        "i need food",
        "get me food",
        "bring me food",
        "find food",
    ]):
        return build_intent(
            original_text=original_text,
            intent="need_food",
            action="find_food",
            target="food",
            executable=False,
            reason="High-level human intent detected. The current robot setup requires perception and possibly manipulation before this task can be executed.",
        )

    if any(phrase in text for phrase in [
        "apple",
        "find the apple",
        "get the apple",
        "bring me the apple",
        "pick up the apple",
    ]):
        return build_intent(
            original_text=original_text,
            intent="object_request",
            action="find_object",
            target="apple",
            executable=False,
            reason="Object-related task detected. The current setup does not yet support object detection or grasping.",
        )

    # ---------- unknown ----------
    return build_intent(
        original_text=original_text,
        intent="unknown",
        action="none",
        executable=False,
        reason="No supported intent was detected.",
    )


def main():
    print("Intent parser test mode.")
    print("Type a natural language command.")
    print("Examples:")
    print("  move forward a little")
    print("  sit down")
    print("  I am hungry")
    print("  find the apple")
    print("  go two stop")
    print("Press Ctrl+C to quit.\n")

    while True:
        text = input("User command: ")
        result = parse_intent(text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print()


if __name__ == "__main__":
    main()
