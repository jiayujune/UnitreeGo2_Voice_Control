import unittest

from intent_parser import parse_intent


class IntentParserTest(unittest.TestCase):
    def test_stop_is_executable_without_confirmation(self):
        intent = parse_intent("go two stop")

        self.assertEqual(intent["intent"], "robot_control")
        self.assertEqual(intent["action"], "stop")
        self.assertTrue(intent["executable"])
        self.assertFalse(intent["need_confirmation"])

    def test_movement_requires_confirmation_and_has_limited_duration(self):
        intent = parse_intent("go two forward")

        self.assertEqual(intent["action"], "forward")
        self.assertTrue(intent["executable"])
        self.assertTrue(intent["need_confirmation"])
        self.assertLessEqual(intent["duration"], 1.0)

    def test_go_two_back_maps_to_backward(self):
        intent = parse_intent("go two back")

        self.assertEqual(intent["action"], "backward")
        self.assertTrue(intent["executable"])
        self.assertTrue(intent["need_confirmation"])

    def test_recovery_wins_over_extra_posture_words(self):
        intent = parse_intent("recovery stand up recovery forward back")

        self.assertEqual(intent["action"], "recovery")
        self.assertTrue(intent["executable"])
        self.assertFalse(intent["need_confirmation"])

    def test_lay_down_maps_to_stand_down(self):
        intent = parse_intent("lay down")

        self.assertEqual(intent["action"], "stand_down")
        self.assertTrue(intent["executable"])
        self.assertFalse(intent["need_confirmation"])

    def test_hungry_is_high_level_but_not_executable_yet(self):
        intent = parse_intent("I am hungry")

        self.assertEqual(intent["intent"], "need_food")
        self.assertEqual(intent["action"], "find_food")
        self.assertEqual(intent["target"], "food")
        self.assertFalse(intent["executable"])

    def test_apple_request_is_not_executable_without_perception(self):
        intent = parse_intent("bring me the apple")

        self.assertEqual(intent["intent"], "object_request")
        self.assertEqual(intent["action"], "find_object")
        self.assertEqual(intent["target"], "apple")
        self.assertFalse(intent["executable"])

    def test_unknown_command_is_not_executable(self):
        intent = parse_intent("please make coffee")

        self.assertEqual(intent["intent"], "unknown")
        self.assertEqual(intent["action"], "none")
        self.assertFalse(intent["executable"])


if __name__ == "__main__":
    unittest.main()
