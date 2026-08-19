"""Speaker-recognition gate for the voice-control mainline.

Only audio from an enrolled, recognized speaker is allowed through to intent
parsing and robot control. Authorized-speaker profiles live in their own file
(default: authorized_speakers.json next to this module), separate from the
benchmark profiles under Speaker_Recognition/.

The deep encoder (resemblyzer) is the default because the LibriSpeech benchmark
showed it cleanly separates known vs unknown speakers (top-1 1.00, EER ~1%),
while the MFCC baseline cannot reliably reject strangers (EER ~14%).
"""

import sys
from pathlib import Path

# Make the Speaker_Recognition package importable from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Speaker_Recognition.embedders import get_embedder  # noqa: E402
from Speaker_Recognition.recognizer import SpeakerRecognizer  # noqa: E402

DEFAULT_PROFILES = str(Path(__file__).resolve().parent / "authorized_speakers.json")
DEFAULT_ENCODER = "resemblyzer"
DEFAULT_THRESHOLD = 0.75


def build_gate(encoder=DEFAULT_ENCODER, profiles_path=DEFAULT_PROFILES, threshold=DEFAULT_THRESHOLD):
    """Build a recognizer for the authorized-speaker profiles. The CLI threshold
    always wins over any value stored in the profile file."""
    recognizer = SpeakerRecognizer(
        profile_path=profiles_path,
        threshold=threshold,
        embed_fn=get_embedder(encoder),
    )
    recognizer.threshold = threshold
    return recognizer


def authorized_speakers(recognizer):
    return sorted(recognizer.profiles.keys())


def identify(recognizer, wav_path):
    """Return (speaker_id_or_None, score). speaker_id is None when no enrolled
    speaker matched above the threshold — i.e. the speaker is not authorized."""
    result = recognizer.identify_file(wav_path)
    return result.speaker_id, result.score
