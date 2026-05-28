from dataclasses import dataclass

import numpy as np

from .features import frame_audio, rms_db, zero_crossing_rate


@dataclass
class VoiceActivityResult:
    is_speech: bool
    voiced_audio: np.ndarray
    segments: list
    speech_ratio: float
    threshold_db: float


class VoiceActivityDetector:
    """Energy/ZCR VAD for separating speech from common steady noise."""

    def __init__(
        self,
        frame_ms=30.0,
        hop_ms=10.0,
        min_speech_ms=250.0,
        energy_margin_db=9.0,
        min_rms_db=-65.0,
        max_voice_zcr=0.35,
        padding_ms=120.0,
    ):
        self.frame_ms = frame_ms
        self.hop_ms = hop_ms
        self.min_speech_ms = min_speech_ms
        self.energy_margin_db = energy_margin_db
        self.min_rms_db = min_rms_db
        self.max_voice_zcr = max_voice_zcr
        self.padding_ms = padding_ms

    def detect(self, audio, sample_rate):
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return VoiceActivityResult(False, samples, [], 0.0, self.min_rms_db)

        samples = self._normalize(samples)
        frames = frame_audio(samples, sample_rate, self.frame_ms, self.hop_ms)
        db = rms_db(frames)
        zcr = zero_crossing_rate(frames)

        quiet_count = max(1, int(0.5 * 1000.0 / self.hop_ms))
        noise_floor = float(np.percentile(db[:quiet_count], 60))
        threshold = max(noise_floor + self.energy_margin_db, self.min_rms_db)
        speech_frames = (db >= threshold) & (zcr <= self.max_voice_zcr)

        speech_frames = self._smooth(speech_frames)
        segments = self._segments_from_frames(speech_frames, samples.size, sample_rate)
        voiced = self._concat_segments(samples, segments, sample_rate)
        speech_ratio = float(np.mean(speech_frames)) if speech_frames.size else 0.0
        min_samples = int(sample_rate * self.min_speech_ms / 1000.0)
        is_speech = bool(voiced.size >= min_samples)

        return VoiceActivityResult(is_speech, voiced, segments, speech_ratio, threshold)

    @staticmethod
    def _normalize(audio):
        audio = audio - float(np.mean(audio))
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 1.0:
            audio = audio / peak
        return audio.astype(np.float32)

    def _smooth(self, mask):
        if mask.size == 0:
            return mask
        close_frames = max(1, int(80.0 / self.hop_ms))
        smoothed = mask.copy()
        for idx in range(mask.size):
            start = max(0, idx - close_frames)
            end = min(mask.size, idx + close_frames + 1)
            smoothed[idx] = np.mean(mask[start:end]) >= 0.35
        return smoothed

    def _segments_from_frames(self, mask, sample_count, sample_rate):
        min_frames = max(1, int(self.min_speech_ms / self.hop_ms))
        padding = int(sample_rate * self.padding_ms / 1000.0)
        hop = int(sample_rate * self.hop_ms / 1000.0)
        frame_size = int(sample_rate * self.frame_ms / 1000.0)

        segments = []
        start = None
        for idx, active in enumerate(mask):
            if active and start is None:
                start = idx
            if (not active or idx == mask.size - 1) and start is not None:
                end = idx if not active else idx + 1
                if end - start >= min_frames:
                    start_sample = max(0, start * hop - padding)
                    end_sample = min(sample_count, end * hop + frame_size + padding)
                    segments.append((start_sample, end_sample))
                start = None

        return self._merge_segments(segments)

    @staticmethod
    def _merge_segments(segments):
        if not segments:
            return []
        merged = [segments[0]]
        for start, end in segments[1:]:
            prev_start, prev_end = merged[-1]
            if start <= prev_end:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))
        return merged

    @staticmethod
    def _concat_segments(audio, segments, sample_rate):
        if not segments:
            return np.zeros(0, dtype=np.float32)
        gap = np.zeros(int(0.05 * sample_rate), dtype=np.float32)
        parts = []
        for idx, (start, end) in enumerate(segments):
            if idx:
                parts.append(gap)
            parts.append(audio[start:end])
        return np.concatenate(parts).astype(np.float32)
