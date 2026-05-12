import re
from difflib import get_close_matches


COMMAND_ALIASES = {
    "stop": [
        "stop",
        "halt",
        "freeze",
    ],
    "stand_up": [
        "stand",
        "stand up",
        "get up",
    ],
    "stand_down": [
        "stand down",
        "lie down",
        "lay down",
        "sit down",
        "down",
    ],
    "balance": [
        "balance",
        "balance stand",
    ],
    "recovery": [
        "recovery",
        "recover",
        "recovery stand",
    ],
    "forward": [
        "forward",
        "go forward",
        "move forward",
        "for word",
        "foreword",
    ],
    "backward": [
        "back",
        "backward",
        "go back",
        "move back",
        "back up",
    ],
    "turn_left": [
        "left",
        "turn left",
        "go left",
    ],
    "turn_right": [
        "right",
        "turn right",
        "go right",
    ],
}

WAKE_WORDS = [
    "robot",
    "go2",
    "go two",
    "go to",
    "g o two",
]

def clean_text(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_wake_word(text):
    for wake_word in WAKE_WORDS:
        if text == wake_word:
            return ""

        if text.startswith(wake_word + " "):
            return text[len(wake_word):].strip()

    return text


def parse_command(text):
    text = clean_text(text)
    command_text = strip_wake_word(text)

    # stop should always have the highest priority
    if any(alias in text.split() for alias in COMMAND_ALIASES["stop"]):
        return "stop"

    for command, aliases in COMMAND_ALIASES.items():
        if command == "stop":
            continue

        if command_text in aliases:
            return command

    all_aliases = {
        alias: command
        for command, aliases in COMMAND_ALIASES.items()
        for alias in aliases
        if command != "stop"
    }
    fuzzy_match = get_close_matches(command_text, all_aliases.keys(), n=1, cutoff=0.82)
    if fuzzy_match:
        return all_aliases[fuzzy_match[0]]

    return "unknown"


if __name__ == "__main__":
    text = "Okay, move forward."
    command = parse_command(text)

    print("Input text:")
    print(text)

    print("Cleaned text:")
    print(clean_text(text))

    print("Parsed command:")
    print(command)
