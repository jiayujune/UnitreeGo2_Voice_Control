import tempfile
import unittest
from pathlib import Path

import numpy as np

from .audio_io import write_wav
from .recognizer import SpeakerRecognizer
from .vad import VoiceActivityDetector


SAMPLE_RATE = 16000


def synthetic_voice(freq, seconds=1.2):
    t = np.arange(int(seconds * SAMPLE_RATE), dtype=np.float32) / SAMPLE_RATE
    carrier = 0.35 * np.sin(2.0 * np.pi * freq * t)
    harmonic = 0.12 * np.sin(2.0 * np.pi * freq * 2.0 * t)
    envelope = np.clip(np.sin(np.pi * t / seconds), 0.0, 1.0)
    silence = np.zeros(int(0.25 * SAMPLE_RATE), dtype=np.float32)
    return np.concatenate([silence, (carrier + harmonic) * envelope, silence]).astype(np.float32)


class SpeakerRecognitionTests(unittest.TestCase):
    def test_vad_detects_voice_like_audio(self):
        audio = synthetic_voice(180.0)
        result = VoiceActivityDetector().detect(audio, SAMPLE_RATE)
        self.assertTrue(result.is_speech)
        self.assertGreater(result.voiced_audio.size, 0)

    def test_vad_rejects_silence(self):
        audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        result = VoiceActivityDetector().detect(audio, SAMPLE_RATE)
        self.assertFalse(result.is_speech)

    def test_enroll_and_identify(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile_path = tmp_path / "profiles.json"
            a_path = tmp_path / "speaker_a.wav"
            b_path = tmp_path / "speaker_b.wav"
            query_path = tmp_path / "query.wav"

            write_wav(a_path, synthetic_voice(180.0), SAMPLE_RATE)
            write_wav(b_path, synthetic_voice(260.0), SAMPLE_RATE)
            write_wav(query_path, synthetic_voice(180.0), SAMPLE_RATE)

            recognizer = SpeakerRecognizer(profile_path, threshold=0.5)
            recognizer.enroll_file("speaker_a", a_path)
            recognizer.enroll_file("speaker_b", b_path)

            result = recognizer.identify_file(query_path)
            self.assertTrue(result.is_speech)
            self.assertEqual(result.speaker_id, "speaker_a")


if __name__ == "__main__":
    unittest.main()
