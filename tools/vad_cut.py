import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from voice_control_essential.audio_pipeline import cut_speech_from_file


def parse_args():
    parser = argparse.ArgumentParser(description="Silero VAD file-cut test.")
    parser.add_argument("--input", default="test.wav", help="Input WAV file.")
    parser.add_argument("--output", default="speech_segment.wav", help="Output speech WAV file.")
    parser.add_argument("--threshold", type=float, default=0.5, help="Silero VAD threshold.")
    return parser.parse_args()


def main():
    args = parse_args()
    cut_speech_from_file(
        args.input,
        args.output,
        threshold=args.threshold,
    )


if __name__ == "__main__":
    main()
