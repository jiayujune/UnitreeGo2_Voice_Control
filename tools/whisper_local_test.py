import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from voice_control_essential.transcriber import LocalWhisperTranscriber


def parse_args():
    parser = argparse.ArgumentParser(description="Local Whisper transcription test.")
    parser.add_argument("--input", default="speech_segment.wav", help="Input WAV file.")
    parser.add_argument("--model", default="base", help="Local Whisper model name.")
    return parser.parse_args()


def main():
    args = parse_args()
    transcriber = LocalWhisperTranscriber(model_name=args.model)
    text = transcriber.transcribe(args.input)
    print("\nResult:")
    print(text)


if __name__ == "__main__":
    main()
