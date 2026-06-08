"""
Evaluation harness for the Speaker Recognition module.

Reports:
  - VAD: precision / recall / F1 / accuracy on a speech-vs-nonspeech clip set.
  - Speaker identification: closed-set top-1 accuracy.
  - Open-set verification: EER, and a threshold sweep (FAR / FRR / accuracy)
    so the matching threshold can be calibrated instead of hand-set.

Expected dataset layout (all parts optional; provide what you have):

    <dataset>/
      enroll/<speaker_id>/*.wav     enrollment clips, one folder per speaker
      test/<speaker_id>/*.wav       test clips for known (enrolled) speakers
      test/unknown/*.wav            (optional) out-of-set speakers -> should be rejected
      vad/speech/*.wav              (optional) clips that ARE speech
      vad/nonspeech/*.wav           (optional) silence / noise -> NOT speech

Usage:
    python -m Speaker_Recognition.evaluate <dataset> [--threshold 0.82] [--json out.json]
    python -m Speaker_Recognition.evaluate --demo      # synthetic self-test, no data needed
"""

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np

from .audio_io import read_wav, write_wav
from .features import speaker_embedding, cosine_similarity
from .recognizer import SpeakerRecognizer
from .vad import VoiceActivityDetector

UNKNOWN_LABEL = "unknown"
AUDIO_EXTS = (".wav",)


# --------------------------------------------------------------------------- #
# dataset discovery
# --------------------------------------------------------------------------- #
def _wavs(directory: Path):
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.suffix.lower() in AUDIO_EXTS)


def _speaker_dirs(directory: Path):
    if not directory.is_dir():
        return {}
    return {p.name: _wavs(p) for p in sorted(directory.iterdir()) if p.is_dir()}


# --------------------------------------------------------------------------- #
# VAD evaluation
# --------------------------------------------------------------------------- #
def evaluate_vad(vad: VoiceActivityDetector, dataset: Path):
    speech = _wavs(dataset / "vad" / "speech")
    nonspeech = _wavs(dataset / "vad" / "nonspeech")
    if not speech and not nonspeech:
        return None

    tp = fp = fn = tn = 0
    for wav in speech:  # label = speech
        audio, sr = read_wav(wav)
        if vad.detect(audio, sr).is_speech:
            tp += 1
        else:
            fn += 1
    for wav in nonspeech:  # label = non-speech
        audio, sr = read_wav(wav)
        if vad.detect(audio, sr).is_speech:
            fp += 1
        else:
            tn += 1

    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "clips": total,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": (tp + tn) / total if total else 0.0,
    }


# --------------------------------------------------------------------------- #
# speaker identification / verification
# --------------------------------------------------------------------------- #
def enroll_speakers(recognizer: SpeakerRecognizer, dataset: Path):
    enrolled = []
    for speaker_id, clips in _speaker_dirs(dataset / "enroll").items():
        for clip in clips:
            recognizer.enroll_file(speaker_id, clip)
        if clips:
            enrolled.append(speaker_id)
    return enrolled


def score_test_clips(recognizer: SpeakerRecognizer, dataset: Path):
    """Return per-clip (true_label, scores_dict) for every test clip."""
    rows = []
    for label, clips in _speaker_dirs(dataset / "test").items():
        for clip in clips:
            result = recognizer.identify_file(clip)
            if not result.is_speech:
                continue  # VAD gated it out; not a speaker-ID trial
            rows.append((label, result.scores))
    return rows


def compute_eer(genuine, impostor):
    """Equal Error Rate from genuine vs impostor trial scores."""
    if not genuine or not impostor:
        return None
    candidates = sorted(set(genuine) | set(impostor))
    g = np.asarray(genuine, dtype=float)
    i = np.asarray(impostor, dtype=float)
    best = None
    for t in candidates:
        far = float(np.mean(i >= t))   # impostors wrongly accepted
        frr = float(np.mean(g < t))    # genuines wrongly rejected
        gap = abs(far - frr)
        if best is None or gap < best[0]:
            best = (gap, t, (far + frr) / 2.0)
    return {"eer": best[2], "threshold": best[1]}


def threshold_sweep(rows, enrolled, points):
    """Open-set accuracy / FAR / FRR across candidate thresholds."""
    genuine, impostor = [], []
    for true_label, scores in rows:
        for spk, sc in scores.items():
            if spk == true_label:
                genuine.append(sc)
            else:
                impostor.append(sc)

    table = []
    for t in points:
        correct = 0
        far_n = far_d = frr_n = frr_d = 0
        for true_label, scores in rows:
            if not scores:
                continue
            best_spk, best_sc = max(scores.items(), key=lambda kv: kv[1])
            pred = best_spk if best_sc >= t else UNKNOWN_LABEL
            known = true_label in enrolled
            if pred == true_label or (not known and pred == UNKNOWN_LABEL):
                correct += 1
            if known:
                frr_d += 1
                if pred == UNKNOWN_LABEL:
                    frr_n += 1     # known speaker rejected
            else:
                far_d += 1
                if pred != UNKNOWN_LABEL:
                    far_n += 1     # unknown speaker accepted as someone
        table.append({
            "threshold": round(float(t), 3),
            "accuracy": correct / len(rows) if rows else 0.0,
            "far": far_n / far_d if far_d else None,
            "frr": frr_n / frr_d if frr_d else None,
        })
    return table, genuine, impostor


def evaluate_identification(recognizer, dataset, enrolled, sweep_points=21):
    rows = score_test_clips(recognizer, dataset)
    if not rows:
        return None

    known_rows = [(lbl, sc) for lbl, sc in rows if lbl in enrolled]
    top1_correct = sum(
        1 for lbl, sc in known_rows if sc and max(sc.items(), key=lambda kv: kv[1])[0] == lbl
    )
    top1 = top1_correct / len(known_rows) if known_rows else None

    points = np.linspace(0.0, 1.0, sweep_points)
    table, genuine, impostor = threshold_sweep(rows, set(enrolled), points)
    eer = compute_eer(genuine, impostor)
    best_acc = max(table, key=lambda r: r["accuracy"]) if table else None

    return {
        "test_clips": len(rows),
        "known_clips": len(known_rows),
        "unknown_clips": len(rows) - len(known_rows),
        "top1_accuracy": top1,
        "eer": eer,
        "recommended_threshold_by_eer": eer["threshold"] if eer else None,
        "best_accuracy_point": best_acc,
        "sweep": table,
    }


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def print_report(report):
    print("\n=== Speaker Recognition Evaluation ===")

    vad = report.get("vad")
    print("\n[VAD: speech vs non-speech]")
    if vad:
        print(f"  clips={vad['clips']}  precision={vad['precision']:.3f}  "
              f"recall={vad['recall']:.3f}  F1={vad['f1']:.3f}  acc={vad['accuracy']:.3f}")
        print(f"  TP={vad['tp']} FP={vad['fp']} FN={vad['fn']} TN={vad['tn']}")
    else:
        print("  (no vad/speech or vad/nonspeech clips found - skipped)")

    sid = report.get("identification")
    print("\n[Speaker identification]")
    if sid:
        t1 = sid["top1_accuracy"]
        print(f"  test clips={sid['test_clips']} (known={sid['known_clips']}, "
              f"unknown={sid['unknown_clips']})")
        print(f"  closed-set top-1 accuracy: {t1:.3f}" if t1 is not None else
              "  closed-set top-1 accuracy: n/a")
        if sid["eer"]:
            print(f"  open-set EER: {sid['eer']['eer']:.3f} "
                  f"(at threshold {sid['eer']['threshold']:.3f})")
        if sid["best_accuracy_point"]:
            b = sid["best_accuracy_point"]
            print(f"  best-accuracy threshold: {b['threshold']:.3f} "
                  f"(acc {b['accuracy']:.3f})")
        print("\n  threshold   accuracy    FAR     FRR")
        for r in sid["sweep"]:
            far = f"{r['far']:.3f}" if r["far"] is not None else "  -  "
            frr = f"{r['frr']:.3f}" if r["frr"] is not None else "  -  "
            print(f"   {r['threshold']:.3f}      {r['accuracy']:.3f}    {far}   {frr}")
    else:
        print("  (no enroll/test clips found - skipped)")
    print()


# --------------------------------------------------------------------------- #
# synthetic self-test
# --------------------------------------------------------------------------- #
def _synthetic_voice(freq, sr=16000, seconds=1.2, jitter=0.0):
    t = np.arange(int(seconds * sr), dtype=np.float32) / sr
    sig = 0.35 * np.sin(2 * np.pi * (freq + jitter) * t) + 0.12 * np.sin(2 * np.pi * 2 * freq * t)
    env = np.clip(np.sin(np.pi * t / seconds), 0.0, 1.0)
    sil = np.zeros(int(0.25 * sr), dtype=np.float32)
    return np.concatenate([sil, sig * env, sil]).astype(np.float32)


def _build_demo_dataset(root: Path):
    sr = 16000
    speakers = {"alice": 180.0, "bob": 260.0}
    for spk, f in speakers.items():
        for i in range(3):
            write_wav(root / "enroll" / spk / f"{i}.wav", _synthetic_voice(f, sr, jitter=i * 2), sr)
        for i in range(3):
            write_wav(root / "test" / spk / f"{i}.wav", _synthetic_voice(f, sr, jitter=i * 3 + 1), sr)
    # an out-of-set speaker that should be rejected
    for i in range(3):
        write_wav(root / "test" / UNKNOWN_LABEL / f"{i}.wav", _synthetic_voice(420.0, sr, jitter=i), sr)
    # VAD clips
    for i in range(3):
        write_wav(root / "vad" / "speech" / f"{i}.wav", _synthetic_voice(200.0, sr, jitter=i * 5), sr)
        write_wav(root / "vad" / "nonspeech" / f"{i}.wav",
                  (0.001 * np.random.randn(sr)).astype(np.float32), sr)


# --------------------------------------------------------------------------- #
def run(dataset: Path, threshold: float):
    vad = VoiceActivityDetector()
    recognizer = SpeakerRecognizer(dataset / "_eval_profiles.json", threshold=threshold, vad=vad)
    recognizer.profiles = {}  # start clean each run

    report = {"dataset": str(dataset), "threshold": threshold}
    report["vad"] = evaluate_vad(vad, dataset)
    enrolled = enroll_speakers(recognizer, dataset)
    report["enrolled_speakers"] = enrolled
    report["identification"] = (
        evaluate_identification(recognizer, dataset, enrolled) if enrolled else None
    )
    # clean up the scratch profile file
    try:
        (dataset / "_eval_profiles.json").unlink()
    except OSError:
        pass
    return report


def main():
    parser = argparse.ArgumentParser(description="Evaluate the Speaker Recognition module.")
    parser.add_argument("dataset", nargs="?", help="Path to the evaluation dataset directory.")
    parser.add_argument("--threshold", type=float, default=0.82)
    parser.add_argument("--json", help="Optional path to write the full report as JSON.")
    parser.add_argument("--demo", action="store_true",
                        help="Build a synthetic dataset and self-test (no real data needed).")
    args = parser.parse_args()

    if args.demo:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_demo_dataset(root)
            report = run(root, args.threshold)
            print_report(report)
            if args.json:
                Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        return

    if not args.dataset:
        parser.error("provide a dataset directory, or use --demo")
    dataset = Path(args.dataset)
    if not dataset.is_dir():
        parser.error(f"dataset directory not found: {dataset}")

    report = run(dataset, args.threshold)
    print_report(report)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote report to {args.json}")


if __name__ == "__main__":
    main()
