import argparse
import json
from pathlib import Path

import numpy as np

from .audio_io import audio_level_stats, list_audio_devices, record_microphone, read_wav, write_wav
from .features import frame_audio, rms_db
from .recognizer import SpeakerRecognizer
from .vad import VoiceActivityDetector


DEFAULT_PROFILE_PATH = Path(__file__).with_name("speaker_profiles.json")


def result_to_dict(result):
    return {
        "is_speech": result.is_speech,
        "speaker_id": result.speaker_id,
        "score": round(result.score, 4),
        "scores": {key: round(value, 4) for key, value in result.scores.items()},
        "segments": result.segments,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Step 1 VAD + Step 2 speaker identification for Go2 voice control."
    )
    parser.add_argument(
        "--profiles",
        default=str(DEFAULT_PROFILE_PATH),
        help="Speaker profile JSON path.",
    )
    parser.add_argument("--threshold", type=float, default=0.82)
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect = subparsers.add_parser("detect", help="Run voice activity detection on a WAV file.")
    detect.add_argument("wav")
    detect.add_argument("--voice-out", help="Optional WAV path for extracted voice.")
    detect.add_argument("--debug", action="store_true", help="Print audio level and frame energy stats.")

    enroll = subparsers.add_parser("enroll", help="Enroll one speaker from a WAV file.")
    enroll.add_argument("speaker_id")
    enroll.add_argument("wav")

    identify = subparsers.add_parser("identify", help="Identify speaker from a WAV file.")
    identify.add_argument("wav")

    record_only = subparsers.add_parser("record", help="Record microphone audio to a WAV file.")
    record_only.add_argument("--seconds", type=float, default=4.0)
    record_only.add_argument("--device")
    record_only.add_argument(
        "--sample-rate",
        type=int,
        help="Optional recording sample rate. By default, use the device default rate.",
    )
    record_only.add_argument("--wav-out", default="speaker_recording.wav")

    record = subparsers.add_parser("record-identify", help="Record microphone audio then identify.")
    record.add_argument("--seconds", type=float, default=4.0)
    record.add_argument("--device")
    record.add_argument(
        "--sample-rate",
        type=int,
        help="Optional recording sample rate. By default, use the device default rate.",
    )
    record.add_argument("--wav-out", default="speaker_query.wav")

    subparsers.add_parser("list-devices", help="List available microphone/audio devices.")

    return parser.parse_args()


def main():
    args = parse_args()
    vad = VoiceActivityDetector()
    recognizer = SpeakerRecognizer(args.profiles, threshold=args.threshold, vad=vad)

    if args.command == "detect":
        audio, sample_rate = read_wav(args.wav)
        result = vad.detect(audio, sample_rate)
        if args.voice_out and result.voiced_audio.size:
            write_wav(args.voice_out, result.voiced_audio, sample_rate)
        payload = {
            "is_speech": result.is_speech,
            "speech_ratio": round(result.speech_ratio, 4),
            "threshold_db": round(result.threshold_db, 2),
            "segments": result.segments,
        }
        if args.debug:
            frames = frame_audio(audio, sample_rate, vad.frame_ms, vad.hop_ms)
            db = rms_db(frames)
            level = audio_level_stats(audio)
            payload["audio"] = {
                "sample_rate": sample_rate,
                "seconds": round(len(audio) / sample_rate, 3),
                "peak": round(level["peak"], 6),
                "rms": round(level["rms"], 6),
                "p99": round(level["abs_p99"], 6),
                "frame_db_min": round(float(db.min()), 2),
                "frame_db_median": round(float(np.median(db)), 2),
                "frame_db_max": round(float(db.max()), 2),
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.command == "enroll":
        profile = recognizer.enroll_file(args.speaker_id, args.wav)
        print(
            json.dumps(
                {
                    "speaker_id": profile.speaker_id,
                    "sample_count": profile.sample_count,
                    "profiles": str(recognizer.profile_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "identify":
        result = recognizer.identify_file(args.wav)
        print(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2))
        return

    if args.command == "record":
        record_microphone(
            args.seconds,
            output_path=args.wav_out,
            sample_rate=args.sample_rate,
            device=args.device,
        )
        return

    if args.command == "record-identify":
        audio, sample_rate = record_microphone(
            args.seconds,
            output_path=args.wav_out,
            sample_rate=args.sample_rate,
            device=args.device,
        )
        result = recognizer.identify_audio(audio, sample_rate)
        print(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2))
        return

    if args.command == "list-devices":
        print(json.dumps(list_audio_devices(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
