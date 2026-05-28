import numpy as np


EPS = 1e-10


def frame_audio(audio, sample_rate, frame_ms=25.0, hop_ms=10.0):
    samples = np.asarray(audio, dtype=np.float32)
    frame_size = max(1, int(sample_rate * frame_ms / 1000.0))
    hop_size = max(1, int(sample_rate * hop_ms / 1000.0))

    if samples.size < frame_size:
        samples = np.pad(samples, (0, frame_size - samples.size))

    frame_count = 1 + int(np.ceil((samples.size - frame_size) / float(hop_size)))
    padded_size = frame_size + (frame_count - 1) * hop_size
    if padded_size > samples.size:
        samples = np.pad(samples, (0, padded_size - samples.size))

    indexes = np.arange(frame_size)[None, :] + hop_size * np.arange(frame_count)[:, None]
    return samples[indexes]


def rms_db(frames):
    energy = np.mean(np.square(frames), axis=1)
    return 10.0 * np.log10(energy + EPS)


def zero_crossing_rate(frames):
    signs = np.signbit(frames)
    return np.mean(signs[:, 1:] != signs[:, :-1], axis=1)


def hz_to_mel(freq_hz):
    return 2595.0 * np.log10(1.0 + freq_hz / 700.0)


def mel_to_hz(mel):
    return 700.0 * (np.power(10.0, mel / 2595.0) - 1.0)


def mel_filterbank(sample_rate, n_fft, n_filters=26, min_hz=80.0, max_hz=None):
    max_hz = max_hz or sample_rate / 2.0
    mel_points = np.linspace(hz_to_mel(min_hz), hz_to_mel(max_hz), n_filters + 2)
    hz_points = mel_to_hz(mel_points)
    bins = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)
    bins = np.clip(bins, 0, n_fft // 2)

    filters = np.zeros((n_filters, n_fft // 2 + 1), dtype=np.float32)
    for idx in range(1, n_filters + 1):
        left, center, right = bins[idx - 1], bins[idx], bins[idx + 1]
        if center == left:
            center += 1
        if right == center:
            right += 1
        for bin_idx in range(left, min(center, filters.shape[1])):
            filters[idx - 1, bin_idx] = (bin_idx - left) / float(center - left)
        for bin_idx in range(center, min(right, filters.shape[1])):
            filters[idx - 1, bin_idx] = (right - bin_idx) / float(right - center)
    return filters


def dct_type_2(values, keep):
    matrix = np.asarray(values, dtype=np.float32)
    n = matrix.shape[1]
    basis = np.cos(np.pi / n * (np.arange(n) + 0.5)[:, None] * np.arange(keep)[None, :])
    return matrix @ basis


def mfcc(audio, sample_rate, n_mfcc=13, n_filters=26, frame_ms=25.0, hop_ms=10.0):
    """Compute lightweight MFCC features without scipy/librosa."""
    samples = np.asarray(audio, dtype=np.float32)
    if samples.size == 0:
        return np.zeros((0, n_mfcc), dtype=np.float32)

    emphasized = np.append(samples[0], samples[1:] - 0.97 * samples[:-1])
    frames = frame_audio(emphasized, sample_rate, frame_ms=frame_ms, hop_ms=hop_ms)
    frames *= np.hamming(frames.shape[1]).astype(np.float32)

    n_fft = 1
    while n_fft < frames.shape[1]:
        n_fft *= 2
    spectrum = np.fft.rfft(frames, n=n_fft)
    power = (np.abs(spectrum) ** 2) / n_fft
    filters = mel_filterbank(sample_rate, n_fft, n_filters=n_filters)
    log_mel = np.log(np.maximum(power @ filters.T, EPS))
    coeffs = dct_type_2(log_mel, n_mfcc)
    return coeffs.astype(np.float32)


def speaker_embedding(audio, sample_rate):
    """Return a compact speaker embedding from MFCC statistics."""
    coeffs = mfcc(audio, sample_rate)
    if coeffs.size == 0:
        return np.zeros(39, dtype=np.float32)

    delta = np.diff(coeffs, axis=0, prepend=coeffs[:1])
    stats = np.concatenate(
        [
            coeffs.mean(axis=0),
            coeffs.std(axis=0),
            delta.mean(axis=0),
        ]
    )
    norm = np.linalg.norm(stats)
    if norm > EPS:
        stats = stats / norm
    return stats.astype(np.float32)


def cosine_similarity(left, right):
    left = np.asarray(left, dtype=np.float32)
    right = np.asarray(right, dtype=np.float32)
    denom = np.linalg.norm(left) * np.linalg.norm(right)
    if denom <= EPS:
        return 0.0
    return float(np.dot(left, right) / denom)
