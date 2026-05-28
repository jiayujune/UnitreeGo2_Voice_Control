import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio_io import DEFAULT_SAMPLE_RATE, read_wav
from .features import cosine_similarity, speaker_embedding
from .vad import VoiceActivityDetector


@dataclass
class SpeakerProfile:
    speaker_id: str
    embedding: np.ndarray
    sample_count: int = 1


@dataclass
class RecognitionResult:
    is_speech: bool
    speaker_id: str | None
    score: float
    scores: dict
    segments: list


class SpeakerRecognizer:
    def __init__(self, profile_path="speaker_profiles.json", threshold=0.82, vad=None):
        self.profile_path = Path(profile_path)
        self.threshold = threshold
        self.vad = vad or VoiceActivityDetector()
        self.profiles = {}
        if self.profile_path.exists():
            self.load()

    def load(self):
        data = json.loads(self.profile_path.read_text(encoding="utf-8"))
        self.threshold = float(data.get("threshold", self.threshold))
        self.profiles = {}
        for item in data.get("profiles", []):
            self.profiles[item["speaker_id"]] = SpeakerProfile(
                speaker_id=item["speaker_id"],
                embedding=np.asarray(item["embedding"], dtype=np.float32),
                sample_count=int(item.get("sample_count", 1)),
            )

    def save(self):
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "threshold": self.threshold,
            "profiles": [
                {
                    "speaker_id": profile.speaker_id,
                    "embedding": profile.embedding.astype(float).tolist(),
                    "sample_count": profile.sample_count,
                }
                for profile in sorted(self.profiles.values(), key=lambda p: p.speaker_id)
            ],
        }
        self.profile_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def enroll_file(self, speaker_id, wav_path, sample_rate=DEFAULT_SAMPLE_RATE):
        audio, sr = read_wav(wav_path, target_sample_rate=sample_rate)
        return self.enroll_audio(speaker_id, audio, sr)

    def enroll_audio(self, speaker_id, audio, sample_rate):
        vad_result = self.vad.detect(audio, sample_rate)
        if not vad_result.is_speech:
            raise ValueError("No speech detected in enrollment audio.")

        embedding = speaker_embedding(vad_result.voiced_audio, sample_rate)
        existing = self.profiles.get(speaker_id)
        if existing:
            count = existing.sample_count + 1
            mixed = (existing.embedding * existing.sample_count + embedding) / count
            norm = np.linalg.norm(mixed)
            if norm > 0:
                mixed = mixed / norm
            self.profiles[speaker_id] = SpeakerProfile(speaker_id, mixed.astype(np.float32), count)
        else:
            self.profiles[speaker_id] = SpeakerProfile(speaker_id, embedding, 1)
        self.save()
        return self.profiles[speaker_id]

    def identify_file(self, wav_path, sample_rate=DEFAULT_SAMPLE_RATE):
        audio, sr = read_wav(wav_path, target_sample_rate=sample_rate)
        return self.identify_audio(audio, sr)

    def identify_audio(self, audio, sample_rate):
        vad_result = self.vad.detect(audio, sample_rate)
        if not vad_result.is_speech:
            return RecognitionResult(False, None, 0.0, {}, vad_result.segments)

        if not self.profiles:
            return RecognitionResult(True, None, 0.0, {}, vad_result.segments)

        embedding = speaker_embedding(vad_result.voiced_audio, sample_rate)
        scores = {
            speaker_id: cosine_similarity(embedding, profile.embedding)
            for speaker_id, profile in self.profiles.items()
        }
        speaker_id, score = max(scores.items(), key=lambda item: item[1])
        if score < self.threshold:
            speaker_id = None

        return RecognitionResult(True, speaker_id, float(score), scores, vad_result.segments)
