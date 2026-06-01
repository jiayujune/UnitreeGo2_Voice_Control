import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from voice_control_essential.audio_pipeline import record_fixed_duration


def parse_args():
    parser = argparse.ArgumentParser(description="Record a short microphone WAV test.")
    parser.add_argument("--output", default="runtime/test.wav", help="Output WAV path.")
    parser.add_argument("--seconds", type=float, default=5.0, help="Seconds to record.")
    return parser.parse_args()


def main():
    args = parse_args()
    record_fixed_duration(args.output, seconds=args.seconds)


if __name__ == "__main__":
    main()
