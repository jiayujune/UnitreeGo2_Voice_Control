"""
Convert a LibriSpeech split (e.g. dev-clean) into the layout evaluate.py expects.

LibriSpeech layout:
    <root>/<speaker_id>/<chapter_id>/<speaker_id>-<chapter_id>-<utt>.flac   (16 kHz mono)

Output (consumable by Speaker_Recognition.evaluate):
    <out>/enroll/<speaker_id>/*.wav      known speakers, enrollment clips
    <out>/test/<speaker_id>/*.wav        known speakers, test clips
    <out>/test/unknown/*.wav             held-out speakers -> impostor trials (real EER)
    <out>/vad/speech/*.wav               real speech clips
    <out>/vad/nonspeech/*.wav            synthesized silence / low noise

Usage (with the audio venv so soundfile is available):
    ./.venv-audio/bin/python -m Speaker_Recognition.prepare_librispeech \
        Speaker_Recognition/_data/LibriSpeech/dev-clean Speaker_Recognition/libri_dataset \
        --known 15 --unknown 5 --enroll 3 --test 5 --vad 10
"""

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

from .audio_io import write_wav

TARGET_SR = 16000


def list_speakers(root: Path):
    speakers = {}
    for spk_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        flacs = sorted(spk_dir.rglob("*.flac"))
        if flacs:
            speakers[spk_dir.name] = flacs
    return speakers


def _resample(audio, sr):
    if sr == TARGET_SR:
        return audio
    duration = len(audio) / sr
    n = max(1, int(duration * TARGET_SR))
    src_x = np.linspace(0.0, duration, num=len(audio), endpoint=False)
    dst_x = np.linspace(0.0, duration, num=n, endpoint=False)
    return np.interp(dst_x, src_x, audio).astype(np.float32)


def load_clip(path: Path, max_seconds, min_seconds):
    audio, sr = sf.read(str(path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = _resample(audio, sr)
    if len(audio) < int(min_seconds * TARGET_SR):
        return None
    if max_seconds:
        audio = audio[: int(max_seconds * TARGET_SR)]
    return audio


def pick_clips(flacs, count, max_seconds, min_seconds):
    """Take up to `count` usable clips (long enough), in order."""
    out = []
    for f in flacs:
        clip = load_clip(f, max_seconds, min_seconds)
        if clip is not None:
            out.append(clip)
        if len(out) >= count:
            break
    return out


def main():
    ap = argparse.ArgumentParser(description="Convert LibriSpeech to the evaluation layout.")
    ap.add_argument("libri_root", help="Path to LibriSpeech/<split> (contains speaker folders).")
    ap.add_argument("out_dir", help="Output dataset directory.")
    ap.add_argument("--known", type=int, default=15, help="Number of enrolled speakers.")
    ap.add_argument("--unknown", type=int, default=5, help="Number of held-out (impostor) speakers.")
    ap.add_argument("--enroll", type=int, default=3, help="Enrollment clips per known speaker.")
    ap.add_argument("--test", type=int, default=5, help="Test clips per speaker.")
    ap.add_argument("--vad", type=int, default=10, help="VAD speech + nonspeech clips each.")
    ap.add_argument("--max-seconds", type=float, default=6.0, help="Trim clips to this length.")
    ap.add_argument("--min-seconds", type=float, default=3.0, help="Skip clips shorter than this.")
    args = ap.parse_args()

    root = Path(args.libri_root)
    if not root.is_dir():
        ap.error(f"LibriSpeech root not found: {root}")
    out = Path(args.out_dir)

    speakers = list_speakers(root)
    ids = list(speakers.keys())
    need = args.known + args.unknown
    if len(ids) < need:
        ap.error(f"Only {len(ids)} speakers available, need {need}.")

    known_ids = ids[: args.known]
    unknown_ids = ids[args.known: args.known + args.unknown]
    print(f"Speakers: {len(ids)} total -> {len(known_ids)} known, {len(unknown_ids)} unknown")

    # known: enroll + test
    for spk in known_ids:
        clips = pick_clips(speakers[spk], args.enroll + args.test, args.max_seconds, args.min_seconds)
        for i, clip in enumerate(clips[: args.enroll]):
            write_wav(out / "enroll" / spk / f"{i}.wav", clip, TARGET_SR)
        for i, clip in enumerate(clips[args.enroll: args.enroll + args.test]):
            write_wav(out / "test" / spk / f"{i}.wav", clip, TARGET_SR)

    # unknown: impostor test clips
    uidx = 0
    for spk in unknown_ids:
        clips = pick_clips(speakers[spk], args.test, args.max_seconds, args.min_seconds)
        for clip in clips:
            write_wav(out / "test" / "unknown" / f"{uidx}.wav", clip, TARGET_SR)
            uidx += 1

    # VAD speech: real clips pooled from several speakers
    speech_pool = []
    for spk in known_ids:
        speech_pool.extend(speakers[spk])
    vad_speech = pick_clips(speech_pool, args.vad, args.max_seconds, args.min_seconds)
    for i, clip in enumerate(vad_speech):
        write_wav(out / "vad" / "speech" / f"{i}.wav", clip, TARGET_SR)

    # VAD nonspeech: synthesized silence + faint noise (LibriSpeech has none)
    rng = np.random.default_rng(0)
    for i in range(args.vad):
        noise = (0.002 * rng.standard_normal(int(args.max_seconds * TARGET_SR))).astype(np.float32)
        write_wav(out / "vad" / "nonspeech" / f"{i}.wav", noise, TARGET_SR)

    n = lambda d: len(list((out / d).rglob("*.wav")))
    print(f"Done -> {out}")
    print(f"  enroll: {n('enroll')}  test: {n('test')}  "
          f"vad/speech: {n('vad/speech')}  vad/nonspeech: {n('vad/nonspeech')}")
    print(f"Next: ./.venv-audio/bin/python -m Speaker_Recognition.evaluate {out}")


if __name__ == "__main__":
    main()
