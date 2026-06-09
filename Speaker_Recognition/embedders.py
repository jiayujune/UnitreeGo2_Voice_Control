"""
Pluggable speaker embedders, all exposing the same signature:
    embed(audio: np.ndarray, sample_rate: int) -> np.ndarray   # 1-D float32 vector

  - "mfcc"        : the lightweight from-scratch MFCC-statistics baseline (no deps)
  - "resemblyzer" : a pretrained deep d-vector encoder (GE2E, trained on VoxCeleb;
                    needs torch + resemblyzer)
"""

import numpy as np

from .features import speaker_embedding as _mfcc_embed

_voice_encoder = None


def _resemblyzer_embed(audio, sample_rate):
    from resemblyzer import VoiceEncoder, preprocess_wav

    global _voice_encoder
    if _voice_encoder is None:
        _voice_encoder = VoiceEncoder(verbose=False)
    wav = preprocess_wav(np.asarray(audio, dtype=np.float32), source_sr=int(sample_rate))
    return _voice_encoder.embed_utterance(wav).astype(np.float32)


def get_embedder(name: str):
    if name == "mfcc":
        return _mfcc_embed
    if name == "resemblyzer":
        return _resemblyzer_embed
    raise ValueError(f"Unknown encoder '{name}'. Use mfcc or resemblyzer.")
