import argparse
import json

from intent_parser import parse_intent
from llm_intent_parser import parse_intent_with_llm


ROBOT_CAPABILITIES = {
    "high_level_motion": True,
    "camera": True,
    "object_detection": False,
    "navigation": False,
    "manipulation": False,
}


def make_step(step_type, action, *, target=None, executable_now=False, note=""):
    step = {
        "type": step_type,
        "action": action,
        "executable_now": executable_now,
    }
    if target is not None:
        step["target"] = target
    if note:
        step["note"] = note
    return step


def plan_robot_control(intent):
    action = intent.get("action", "none")
    return {
        "goal": "direct_robot_control",
        "source_intent": intent,
        "executable_now": bool(intent.get("executable", False)),
        "requires_user_confirmation": bool(intent.get("need_confirmation", False)),
        "missing_capabilities": [],
        "safety_notes": [
            "Only allowlisted high-level SDK actions may be executed.",
            "Movement duration is capped by the safety layer.",
            "Movement actions require user confirmation before real robot execution.",
        ],
        "steps": [
            make_step(
                "robot_control",
                action,
                executable_now=bool(intent.get("executable", False)),
                note="Direct high-level SDK action after safety checks.",
            )
        ],
    }


def plan_find_food(intent):
    return {
        "goal": "help_user_find_food",
        "source_intent": intent,
        "executable_now": False,
        "requires_user_confirmation": False,
        "missing_capabilities": [
            "object_detection",
            "semantic_scene_understanding",
            "safe_navigation_to_target",
        ],
        "safety_notes": [
            "Go2 has no manipulator, so it cannot pick up or bring food.",
            "The current safe behavior is to identify likely food, approach or orient toward it later, and notify the user.",
        ],
        "steps": [
            make_step(
                "perception",
                "search_for_food_or_food_container",
                target="food",
                note="Requires object detection or visual-language perception.",
            ),
            make_step(
                "navigation",
                "approach_detected_target",
                target="food",
                note="Requires safe navigation and obstacle avoidance.",
            ),
            make_step(
                "communication",
                "notify_user_target_found",
                target="food",
                executable_now=True,
                note="Can be implemented as a printed or spoken response.",
            ),
        ],
    }


def plan_find_object(intent):
    target = intent.get("target", "object")
    return {
        "goal": "find_object",
        "source_intent": intent,
        "executable_now": False,
        "requires_user_confirmation": False,
        "missing_capabilities": [
            "object_detection",
            "target_tracking",
            "safe_navigation_to_target",
        ],
        "safety_notes": [
            "Go2 has no manipulator, so requests like bring, get, or pick up are reinterpreted as locate/approach/notify.",
            "The robot should not claim it can grasp or deliver the object.",
        ],
        "steps": [
            make_step(
                "perception",
                "search_for_object",
                target=target,
                note="Requires object detection from the robot camera.",
            ),
            make_step(
                "orientation",
                "turn_camera_toward_target",
                target=target,
                note="Could become executable after visual target localization.",
            ),
            make_step(
                "navigation",
                "approach_detected_target",
                target=target,
                note="Requires safe navigation and obstacle avoidance.",
            ),
            make_step(
                "communication",
                "notify_user_target_found",
                target=target,
                executable_now=True,
                note="Can be implemented as a printed or spoken response.",
            ),
        ],
    }


def plan_unknown(intent):
    return {
        "goal": "unsupported_request",
        "source_intent": intent,
        "executable_now": False,
        "requires_user_confirmation": False,
        "missing_capabilities": [],
        "safety_notes": [
            "Unsupported or ambiguous requests are rejected.",
            "No robot command should be sent for unknown intents.",
        ],
        "steps": [
            make_step(
                "communication",
                "ask_user_to_rephrase",
                executable_now=True,
                note="Tell the user the request is not supported yet.",
            )
        ],
    }


def plan_from_intent(intent):
    intent_name = intent.get("intent", "unknown")
    action = intent.get("action", "none")

    if intent_name == "robot_control":
        return plan_robot_control(intent)
    if intent_name == "need_food" or action == "find_food":
        return plan_find_food(intent)
    if intent_name == "object_request" or action == "find_object":
        return plan_find_object(intent)
    return plan_unknown(intent)


def parse_text(text, parser_mode, llm_provider=None, llm_model=None):
    if parser_mode == "llm":
        return parse_intent_with_llm(text, provider=llm_provider, model=llm_model)

    intent = parse_intent(text)
    intent["parser"] = "rule"
    return intent


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create a safe high-level plan from an intent JSON."
    )
    parser.add_argument("--text", required=True, help="Natural language request.")
    parser.add_argument(
        "--parser",
        choices=["rule", "llm"],
        default="llm",
        help="Intent parser to use before planning.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["groq", "deepseek", "openai", "custom"],
        default="groq",
        help="LLM provider when --parser llm is used.",
    )
    parser.add_argument("--llm-model", help="Optional LLM model override.")
    return parser.parse_args()


def main():
    args = parse_args()
    intent = parse_text(
        args.text,
        args.parser,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
    )
    plan = plan_from_intent(intent)
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
