import unittest
from unittest.mock import patch

from llm_intent_parser import (
    compact_text_for_llm,
    extract_json_object,
    get_provider_config,
    normalize_llm_intent,
    parse_intent_with_llm,
)


class LLMIntentParserTest(unittest.TestCase):
    def test_extract_json_from_markdown_block(self):
        result = extract_json_object(
            """
            ```json
            {"intent": "robot_control", "action": "stop", "executable": true}
            ```
            """
        )

        self.assertEqual(result["intent"], "robot_control")
        self.assertEqual(result["action"], "stop")
        self.assertTrue(result["executable"])

    def test_compact_text_for_llm_truncates_long_asr_output(self):
        text = "recovery " + ("back " * 300)
        compacted = compact_text_for_llm(text, max_chars=80)

        self.assertLessEqual(len(compacted), 83)
        self.assertTrue(compacted.endswith("..."))

    def test_safety_blocks_unsupported_executable_action(self):
        intent = normalize_llm_intent(
            "run a shell command",
            {
                "intent": "robot_control",
                "action": "run_shell",
                "duration": 10,
                "executable": True,
                "need_confirmation": False,
                "reason": "Bad LLM output.",
            },
        )

        self.assertEqual(intent["action"], "run_shell")
        self.assertFalse(intent["executable"])
        self.assertFalse(intent["need_confirmation"])
        self.assertEqual(intent["duration"], 0.0)

    def test_code_execution_request_is_non_executable_if_llm_marks_unknown(self):
        intent = normalize_llm_intent(
            "run python code on the robot",
            {
                "intent": "unknown",
                "action": "none",
                "duration": 0,
                "executable": False,
                "need_confirmation": False,
                "reason": "Code execution is unsupported.",
            },
        )

        self.assertEqual(intent["intent"], "unknown")
        self.assertEqual(intent["action"], "none")
        self.assertFalse(intent["executable"])
        self.assertFalse(intent["need_confirmation"])

    def test_safety_clamps_movement_duration_and_requires_confirmation(self):
        intent = normalize_llm_intent(
            "go forward for ten seconds",
            {
                "intent": "robot_control",
                "action": "forward",
                "duration": 10,
                "executable": True,
                "need_confirmation": False,
                "reason": "Move forward.",
            },
        )

        self.assertEqual(intent["action"], "forward")
        self.assertTrue(intent["executable"])
        self.assertTrue(intent["need_confirmation"])
        self.assertEqual(intent["duration"], 1.0)

    def test_high_level_object_request_stays_non_executable(self):
        intent = normalize_llm_intent(
            "bring me the apple",
            {
                "intent": "object_request",
                "action": "find_object",
                "target": "apple",
                "duration": 0,
                "executable": False,
                "need_confirmation": False,
                "reason": "Needs perception and manipulation.",
            },
        )

        self.assertEqual(intent["intent"], "object_request")
        self.assertEqual(intent["action"], "find_object")
        self.assertEqual(intent["target"], "apple")
        self.assertFalse(intent["executable"])

    def test_llm_parser_falls_back_when_sdk_or_key_is_missing(self):
        intent = parse_intent_with_llm("go two stop")

        self.assertEqual(intent["action"], "stop")
        self.assertIn(intent["parser"], {"llm", "rule_fallback"})

    def test_groq_provider_config_uses_groq_key_and_default_model(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}, clear=True):
            config = get_provider_config(provider="groq")

        self.assertEqual(config["provider"], "groq")
        self.assertEqual(config["base_url"], "https://api.groq.com/openai/v1")
        self.assertEqual(config["model"], "llama-3.1-8b-instant")

    def test_deepseek_provider_config_uses_deepseek_key_and_default_model(self):
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
            config = get_provider_config(provider="deepseek")

        self.assertEqual(config["provider"], "deepseek")
        self.assertEqual(config["base_url"], "https://api.deepseek.com")
        self.assertEqual(config["model"], "deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()
