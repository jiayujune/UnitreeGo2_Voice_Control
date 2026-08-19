import argparse
import json
import os
from datetime import datetime, timezone

from intent_parser import clean_text, parse_intent
from llm_intent_parser import parse_intent_with_llm
import local_voice_to_robot_ssh


EVAL_LOG_FILE = "voice_intent_eval_results.jsonl"

TEST_PROMPTS = [
    {
        "text": "go two stop",
        "expected": {"intent": "robot_control", "action": "stop", "executable": True},
    },
    {
        "text": "stop moving",
        "expected": {"intent": "robot_control", "action": "stop", "executable": True},
    },
    {
        "text": "freeze",
        "expected": {"intent": "robot_control", "action": "stop", "executable": True},
    },
    {
        "text": "do not move",
        "expected": {"intent": "robot_control", "action": "stop", "executable": True},
    },
    {
        "text": "go two balance",
        "expected": {"intent": "robot_control", "action": "balance", "executable": True},
    },
    {
        "text": "stand up",
        "expected": {"intent": "robot_control", "action": "stand_up", "executable": True},
    },
    {
        "text": "get up",
        "expected": {"intent": "robot_control", "action": "stand_up", "executable": True},
    },
    {
        "text": "sit down",
        "expected": {"intent": "robot_control", "action": "stand_down", "executable": True},
    },
    {
        "text": "lie down",
        "expected": {"intent": "robot_control", "action": "stand_down", "executable": True},
    },
    {
        "text": "recovery stand",
        "expected": {"intent": "robot_control", "action": "recovery", "executable": True},
    },
    {
        "text": "go two forward",
        "expected": {"intent": "robot_control", "action": "forward", "executable": True},
    },
    {
        "text": "move forward",
        "expected": {"intent": "robot_control", "action": "forward", "executable": True},
    },
    {
        "text": "walk forward",
        "expected": {"intent": "robot_control", "action": "forward", "executable": True},
    },
    {
        "text": "go two back",
        "expected": {"intent": "robot_control", "action": "backward", "executable": True},
    },
    {
        "text": "move back",
        "expected": {"intent": "robot_control", "action": "backward", "executable": True},
    },
    {
        "text": "go back",
        "expected": {"intent": "robot_control", "action": "backward", "executable": True},
    },
    {
        "text": "turn left",
        "expected": {"intent": "robot_control", "action": "turn_left", "executable": True},
    },
    {
        "text": "rotate left",
        "expected": {"intent": "robot_control", "action": "turn_left", "executable": True},
    },
    {
        "text": "turn right",
        "expected": {"intent": "robot_control", "action": "turn_right", "executable": True},
    },
    {
        "text": "rotate right",
        "expected": {"intent": "robot_control", "action": "turn_right", "executable": True},
    },
    {
        "text": "I am hungry",
        "expected": {"intent": "need_food", "action": "find_food", "executable": False},
    },
    {
        "text": "I'm hungry",
        "expected": {"intent": "need_food", "action": "find_food", "executable": False},
    },
    {
        "text": "find food",
        "expected": {"intent": "need_food", "action": "find_food", "executable": False},
    },
    {
        "text": "bring me food",
        "expected": {"intent": "need_food", "action": "find_food", "executable": False},
    },
    {
        "text": "find the apple",
        "expected": {"intent": "object_request", "action": "find_object", "executable": False},
    },
    {
        "text": "bring me the apple",
        "expected": {"intent": "object_request", "action": "find_object", "executable": False},
    },
    {
        "text": "pick up the apple",
        "expected": {"intent": "object_request", "action": "find_object", "executable": False},
    },
    {
        "text": "make coffee",
        "expected": {"intent": "unknown", "action": "none", "executable": False},
    },
    {
        "text": "play music",
        "expected": {"intent": "unknown", "action": "none", "executable": False},
    },
    {
        "text": "open the door",
        "expected": {"intent": "unknown", "action": "none", "executable": False},
    },
]


# Sentences that contain command-like substrings but are NOT robot commands.
# These guard against the rule parser firing on bare "back"/"left"/"right"/etc.
# inside ordinary speech. None of them should be executable.
NEGATIVE_PROMPTS = [
    {"text": "please come back later", "expected": {"executable": False}},
    {"text": "turn the light on the left", "expected": {"executable": False}},
    {"text": "I left my keys on the table", "expected": {"executable": False}},
    {"text": "that is right", "expected": {"executable": False}},
    {"text": "you are right about that", "expected": {"executable": False}},
    {"text": "I have a background in music", "expected": {"executable": False}},
    {"text": "I would like some pineapple juice", "expected": {"executable": False}},
    {"text": "the meeting is moved forward to Monday", "expected": {"executable": False}},
    {"text": "I am looking forward to it", "expected": {"executable": False}},
]


def matches_expected(intent, expected):
    return all(intent.get(key) == value for key, value in expected.items())


def log_result(result):
    with open(EVAL_LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(result, ensure_ascii=False) + "\n")


def parse_with_mode(text, parser_mode, llm_provider=None, llm_model=None):
    if parser_mode == "llm":
        return parse_intent_with_llm(text, provider=llm_provider, model=llm_model)

    intent = parse_intent(text)
    intent["parser"] = "rule"
    return intent


def print_result(index, total, prompt, transcript, intent, expected, passed):
    status = "PASS" if passed else "FAIL"
    print(f"\n[{index}/{total}] {status}")
    print("Prompt:    ", prompt)
    print("Transcript:", transcript)
    print("Cleaned:   ", clean_text(transcript))
    print("Expected:  ", expected)
    print(
        "Actual:    ",
        {
            "intent": intent.get("intent"),
            "action": intent.get("action"),
            "executable": intent.get("executable"),
        },
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a batch voice test for Whisper -> intent parser."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=len(TEST_PROMPTS),
        help="Number of prompts to test.",
    )
    parser.add_argument(
        "--model",
        default="base",
        help="Whisper model name.",
    )
    parser.add_argument(
        "--record-seconds",
        type=float,
        default=2.5,
        help="Seconds to record for each short command.",
    )
    parser.add_argument(
        "--indexes",
        help="Comma-separated 1-based prompt numbers to test, for example: 5,9,10.",
    )
    parser.add_argument(
        "--parser",
        choices=["rule", "llm"],
        default="rule",
        help="Intent parser to evaluate. llm falls back to rule-based parsing if unavailable.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["groq", "deepseek", "openai", "custom"],
        help="Provider to use with --parser llm. Can also be set with LLM_PROVIDER.",
    )
    parser.add_argument(
        "--llm-model",
        help="Model to use with --parser llm. Can also be set with LLM_MODEL.",
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Skip the microphone and Whisper. Run the parser directly on each "
             "prompt's text, including the negative (false-positive) prompts. "
             "Fast, deterministic regression check for the intent parser.",
    )
    return parser.parse_args()


def run_text_only(args):
    """Mic-free parser regression check over positive and negative prompts."""
    cases = [(i, item, True) for i, item in enumerate(TEST_PROMPTS, start=1)]
    cases += [(i, item, False) for i, item in enumerate(NEGATIVE_PROMPTS, start=1)]

    print("Text-only intent parser evaluation (no microphone, no Whisper).")
    print(f"Intent parser: {args.parser}")
    print(f"Positive prompts: {len(TEST_PROMPTS)} | Negative prompts: {len(NEGATIVE_PROMPTS)}")

    passed_count = 0
    failures = []
    for number, item, is_positive in cases:
        transcript = item["text"]
        expected = item["expected"]
        intent = parse_with_mode(
            transcript,
            args.parser,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
        )
        passed = matches_expected(intent, expected)
        if passed:
            passed_count += 1
        else:
            failures.append((is_positive, transcript, expected, intent))

        label = "POS" if is_positive else "NEG"
        status = "PASS" if passed else "FAIL"
        print(f"[{label} #{number}] {status}: {transcript!r} -> "
              f"action={intent.get('action')} executable={intent.get('executable')}")

    total = len(cases)
    print(f"\nPassed: {passed_count}/{total}")
    if failures:
        print("\nFailures:")
        for is_positive, transcript, expected, intent in failures:
            print(f"  [{'POS' if is_positive else 'NEG'}] {transcript!r}")
            print(f"      expected {expected}")
            print(f"      actual   action={intent.get('action')} "
                  f"intent={intent.get('intent')} executable={intent.get('executable')}")
    return passed_count == total


def select_prompts(limit, indexes):
    if not indexes:
        return list(enumerate(TEST_PROMPTS[:limit], start=1))

    selected = []
    for raw_index in indexes.split(","):
        prompt_number = int(raw_index.strip())
        selected.append((prompt_number, TEST_PROMPTS[prompt_number - 1]))
    return selected


def main():
    args = parse_args()

    if args.text_only:
        all_passed = run_text_only(args)
        raise SystemExit(0 if all_passed else 1)

    prompts = select_prompts(args.limit, args.indexes)
    local_voice_to_robot_ssh.RECORD_SECONDS = args.record_seconds

    os.environ["CUDA_VISIBLE_DEVICES"] = ""

    import whisper

    print("Loading Whisper model...")
    model = whisper.load_model(args.model, device="cpu")
    print("Model loaded.")
    print("\nVoice intent evaluation.")
    print("No robot commands will be sent.")
    print(f"Intent parser: {args.parser}")
    if args.parser == "llm":
        print(f"LLM provider: {args.llm_provider or 'env/default'}")
        print(f"LLM model: {args.llm_model or 'env/default'}")
    print("For each item, read the prompt exactly, then wait for recording to finish.")

    passed_count = 0

    for index, (prompt_number, item) in enumerate(prompts, start=1):
        prompt = item["text"]
        expected = item["expected"]

        input(
            f"\n[{index}/{len(prompts)} | prompt #{prompt_number}] "
            f"Press Enter, then say: {prompt}"
        )
        local_voice_to_robot_ssh.record_audio()

        result = model.transcribe(
            local_voice_to_robot_ssh.AUDIO_FILE,
            language="en",
            fp16=False,
            temperature=0,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,
            logprob_threshold=-1.0,
            no_speech_threshold=0.6,
            initial_prompt=(
                "The speaker will say one robot command or high-level request: "
                "go two stop, balance, stand up, sit down, recovery, forward, "
                "back, left, right, I am hungry, find food, find the apple."
            ),
        )

        transcript = result["text"].strip()
        intent = parse_with_mode(
            transcript,
            args.parser,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
        )
        passed = matches_expected(intent, expected)

        if passed:
            passed_count += 1

        eval_result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt_number": prompt_number,
            "prompt": prompt,
            "transcript": transcript,
            "cleaned_text": clean_text(transcript),
            "expected": expected,
            "actual": intent,
            "passed": passed,
            "parser_mode": args.parser,
        }
        log_result(eval_result)
        print_result(index, len(prompts), prompt, transcript, intent, expected, passed)

    accuracy = passed_count / len(prompts) if prompts else 0.0
    print("\nEvaluation finished.")
    print(f"Passed: {passed_count}/{len(prompts)}")
    print(f"Intent accuracy: {accuracy:.1%}")
    print(f"Saved results to: {EVAL_LOG_FILE}")


if __name__ == "__main__":
    main()
