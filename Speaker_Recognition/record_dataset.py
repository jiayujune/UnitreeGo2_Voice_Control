"""
Guided recorder that builds an evaluation dataset in the layout evaluate.py expects.

It walks you through recording, one clip at a time (press Enter, speak, repeat):
  - enrollment + test clips for each named speaker
  - a few VAD "speech" clips (you talk) and "nonspeech" clips (stay quiet)

Usage (run with the audio venv so sounddevice is available):
    ./.venv-audio/bin/python -m Speaker_Recognition.record_dataset \
        Speaker_Recognition/dataset --speakers alice bob --enroll 3 --test 3 --seconds 3

Then evaluate:
    ./.venv-audio/bin/python -m Speaker_Recognition.evaluate Speaker_Recognition/dataset
"""

import argparse
from pathlib import Path

from .audio_io import record_microphone

SAMPLE_RATE = 16000


def _record_clip(path: Path, seconds, device, prompt):
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        input(f"\n{prompt}\n  -> Press Enter to start ({seconds:g}s)...")
        record_microphone(seconds, output_path=str(path), sample_rate=SAMPLE_RATE, device=device)
        again = input("  Keep this clip? [Enter=keep, r=redo] ").strip().lower()
        if again != "r":
            return


def main():
    parser = argparse.ArgumentParser(description="Record a speaker-recognition evaluation dataset.")
    parser.add_argument("out_dir", help="Dataset output directory.")
    parser.add_argument("--speakers", nargs="+", required=True,
                        help="Speaker IDs to record (use 2+ different people for meaningful speaker-ID numbers).")
    parser.add_argument("--enroll", type=int, default=3, help="Enrollment clips per speaker.")
    parser.add_argument("--test", type=int, default=3, help="Test clips per speaker.")
    parser.add_argument("--vad", type=int, default=3, help="VAD speech + nonspeech clips each.")
    parser.add_argument("--seconds", type=float, default=3.0, help="Seconds per clip.")
    parser.add_argument("--device", help="Optional input device index/name (see CLI list-devices).")
    args = parser.parse_args()

    root = Path(args.out_dir)
    print(f"\nBuilding dataset at: {root.resolve()}")
    print("Speak a short, natural sentence for each clip (a few seconds of normal talking).")

    for spk in args.speakers:
        print(f"\n========== Speaker: {spk} ==========")
        for i in range(args.enroll):
            _record_clip(root / "enroll" / spk / f"{i}.wav", args.seconds, args.device,
                         f"[{spk}] ENROLLMENT clip {i + 1}/{args.enroll} - say a sentence")
        for i in range(args.test):
            _record_clip(root / "test" / spk / f"{i}.wav", args.seconds, args.device,
                         f"[{spk}] TEST clip {i + 1}/{args.test} - say a (different) sentence")

    if args.vad > 0:
        print("\n========== VAD: speech ==========")
        for i in range(args.vad):
            _record_clip(root / "vad" / "speech" / f"{i}.wav", args.seconds, args.device,
                         f"VAD SPEECH clip {i + 1}/{args.vad} - talk normally")
        print("\n========== VAD: non-speech (stay quiet / ambient noise) ==========")
        for i in range(args.vad):
            _record_clip(root / "vad" / "nonspeech" / f"{i}.wav", args.seconds, args.device,
                         f"VAD NON-SPEECH clip {i + 1}/{args.vad} - DO NOT talk (silence / room noise)")

    print(f"\nDone. Dataset written to {root.resolve()}")
    print("Next: ./.venv-audio/bin/python -m Speaker_Recognition.evaluate", args.out_dir)


if __name__ == "__main__":
    main()
