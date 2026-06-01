import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from voice_control_essential.audio_pipeline import cut_speech_from_file


def parse_args():
    parser = argparse.ArgumentParser(description="Print Silero VAD segments for a WAV file.")
    parser.add_argument("--input", default="test.wav", help="Input WAV file.")
    parser.add_argument("--threshold", type=float, default=0.5, help="Silero VAD threshold.")
    return parser.parse_args()


def main():
    args = parse_args()
    result = cut_speech_from_file(
        args.input,
        "runtime/vad_test_segment.wav",
        threshold=args.threshold,
    )
    print("Detected speech segments:")
    print(result["segments"])


if __name__ == "__main__":
    main()
