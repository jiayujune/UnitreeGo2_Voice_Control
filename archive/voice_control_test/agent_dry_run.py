import argparse
import json

from perception_stub import DEFAULT_SIMULATED_OBJECTS, detect_target
from task_planner import parse_text, plan_from_intent


def find_perception_target(plan):
    for step in plan.get("steps", []):
        if step.get("type") == "perception":
            return step.get("target")
    return None


def build_recommendation(intent, plan, perception):
    if intent.get("intent") == "robot_control":
        if intent.get("executable"):
            return {
                "next_action": "ready_for_safety_checked_robot_command",
                "should_send_robot_command": False,
                "reason": "Dry run only. Real execution still requires the existing safety/confirmation path.",
            }
        return {
            "next_action": "do_not_execute",
            "should_send_robot_command": False,
            "reason": "Robot control intent is not executable after safety checks.",
        }

    if plan.get("goal") in {"find_object", "help_user_find_food"}:
        if perception and perception.get("detected"):
            detection = perception["best_detection"]
            return {
                "next_action": "notify_user_target_found",
                "should_send_robot_command": False,
                "reason": (
                    f"Simulated perception found {detection['label']} at "
                    f"{detection['relative_position']} about {detection['distance_m']}m away. "
                    "Navigation/approach is not executed yet."
                ),
            }

        return {
            "next_action": "ask_user_or_continue_search",
            "should_send_robot_command": False,
            "reason": "Target was not detected by the simulated perception module.",
        }

    return {
        "next_action": "ask_user_to_rephrase",
        "should_send_robot_command": False,
        "reason": "Unsupported or ambiguous request.",
    }


def run_agent_dry_run(
    text,
    parser_mode="llm",
    llm_provider="groq",
    llm_model=None,
    target_missing=False,
):
    intent = parse_text(
        text,
        parser_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    plan = plan_from_intent(intent)

    target = find_perception_target(plan)
    perception = None
    if target:
        simulated_objects = {} if target_missing else DEFAULT_SIMULATED_OBJECTS
        perception = detect_target(target, simulated_objects=simulated_objects)

    recommendation = build_recommendation(intent, plan, perception)

    return {
        "input_text": text,
        "intent": intent,
        "plan": plan,
        "perception": perception,
        "recommendation": recommendation,
        "dry_run": True,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Dry-run agent pipeline: intent -> plan -> simulated perception -> recommendation."
    )
    parser.add_argument("--text", required=True)
    parser.add_argument(
        "--parser",
        choices=["rule", "llm"],
        default="llm",
        help="Intent parser to use.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["groq", "deepseek", "openai", "custom"],
        default="groq",
    )
    parser.add_argument("--llm-model")
    parser.add_argument(
        "--target-missing",
        action="store_true",
        help="Simulate that the requested target is not visible.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    result = run_agent_dry_run(
        args.text,
        parser_mode=args.parser,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        target_missing=args.target_missing,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
