import unittest

from agent_dry_run import build_recommendation, find_perception_target, run_agent_dry_run
from perception_stub import detect_target


class AgentDryRunTest(unittest.TestCase):
    def test_detect_target_finds_simulated_apple(self):
        result = detect_target("apple")

        self.assertTrue(result["detected"])
        self.assertEqual(result["best_detection"]["label"], "apple")

    def test_detect_target_reports_missing_object(self):
        result = detect_target("banana")

        self.assertFalse(result["detected"])
        self.assertEqual(result["detections"], [])

    def test_find_perception_target_from_plan(self):
        plan = {
            "steps": [
                {"type": "communication", "action": "notify_user"},
                {"type": "perception", "action": "search_for_object", "target": "apple"},
            ]
        }

        self.assertEqual(find_perception_target(plan), "apple")

    def test_recommendation_notifies_when_target_detected(self):
        intent = {"intent": "object_request", "action": "find_object"}
        plan = {"goal": "find_object"}
        perception = detect_target("apple")

        recommendation = build_recommendation(intent, plan, perception)

        self.assertEqual(recommendation["next_action"], "notify_user_target_found")
        self.assertFalse(recommendation["should_send_robot_command"])

    def test_recommendation_does_not_execute_robot_control_in_dry_run(self):
        intent = {"intent": "robot_control", "action": "forward", "executable": True}
        plan = {"goal": "direct_robot_control"}

        recommendation = build_recommendation(intent, plan, None)

        self.assertEqual(
            recommendation["next_action"],
            "ready_for_safety_checked_robot_command",
        )
        self.assertFalse(recommendation["should_send_robot_command"])

    def test_agent_dry_run_can_simulate_missing_target(self):
        result = run_agent_dry_run(
            "Please bring me the apple",
            parser_mode="rule",
            target_missing=True,
        )

        self.assertFalse(result["perception"]["detected"])
        self.assertEqual(
            result["recommendation"]["next_action"],
            "ask_user_or_continue_search",
        )


if __name__ == "__main__":
    unittest.main()
