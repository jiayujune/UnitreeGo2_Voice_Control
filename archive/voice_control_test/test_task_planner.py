import unittest

from task_planner import plan_from_intent


class TaskPlannerTest(unittest.TestCase):
    def test_food_request_is_not_executable_and_lists_missing_capabilities(self):
        plan = plan_from_intent(
            {
                "intent": "need_food",
                "action": "find_food",
                "target": "food",
                "executable": False,
                "need_confirmation": False,
            }
        )

        self.assertEqual(plan["goal"], "help_user_find_food")
        self.assertFalse(plan["executable_now"])
        self.assertIn("object_detection", plan["missing_capabilities"])
        self.assertIn("safe_navigation_to_target", plan["missing_capabilities"])

    def test_object_request_is_reinterpreted_without_manipulation(self):
        plan = plan_from_intent(
            {
                "intent": "object_request",
                "action": "find_object",
                "target": "apple",
                "executable": False,
                "need_confirmation": False,
            }
        )

        self.assertEqual(plan["goal"], "find_object")
        self.assertFalse(plan["executable_now"])
        self.assertIn("target_tracking", plan["missing_capabilities"])
        self.assertTrue(
            any("no manipulator" in note.lower() for note in plan["safety_notes"])
        )

    def test_movement_command_plan_keeps_confirmation_requirement(self):
        plan = plan_from_intent(
            {
                "intent": "robot_control",
                "action": "forward",
                "duration": 0.8,
                "executable": True,
                "need_confirmation": True,
            }
        )

        self.assertEqual(plan["goal"], "direct_robot_control")
        self.assertTrue(plan["executable_now"])
        self.assertTrue(plan["requires_user_confirmation"])

    def test_unknown_request_is_rejected(self):
        plan = plan_from_intent(
            {
                "intent": "unknown",
                "action": "none",
                "executable": False,
                "need_confirmation": False,
            }
        )

        self.assertEqual(plan["goal"], "unsupported_request")
        self.assertFalse(plan["executable_now"])
        self.assertEqual(plan["steps"][0]["action"], "ask_user_to_rephrase")


if __name__ == "__main__":
    unittest.main()
