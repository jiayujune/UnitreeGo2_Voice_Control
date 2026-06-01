import argparse
import json


DEFAULT_SIMULATED_OBJECTS = {
    "apple": {
        "label": "apple",
        "confidence": 0.91,
        "relative_position": "front_left",
        "distance_m": 1.8,
    },
    "food": {
        "label": "apple",
        "confidence": 0.91,
        "relative_position": "front_left",
        "distance_m": 1.8,
    },
}


def detect_target(target, simulated_objects=None):
    if simulated_objects is None:
        simulated_objects = DEFAULT_SIMULATED_OBJECTS
    normalized_target = str(target or "").lower().strip()
    detection = simulated_objects.get(normalized_target)

    if detection is None:
        return {
            "target": target,
            "detected": False,
            "detections": [],
            "reason": "No matching simulated detection.",
        }

    return {
        "target": target,
        "detected": True,
        "detections": [detection],
        "best_detection": detection,
        "reason": "Simulated perception result.",
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Simulated perception module for Go2 high-level planning."
    )
    parser.add_argument("--target", required=True)
    parser.add_argument(
        "--missing",
        action="store_true",
        help="Force the target to be missing.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    simulated_objects = {} if args.missing else DEFAULT_SIMULATED_OBJECTS
    result = detect_target(args.target, simulated_objects=simulated_objects)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
