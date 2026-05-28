import wave
from pathlib import Path

import numpy as np


DEFAULT_SAMPLE_RATE = 16000


def read_wav(path, target_sample_rate=DEFAULT_SAMPLE_RATE):
    """Read a mono WAV file as float32 samples in [-1, 1]."""
    wav_path = Path(path)
    with wave.open(str(wav_path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sample_width == 1:
        audio = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
        audio = (audio - 128.0) / 128.0
    elif sample_width == 2:
        audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    if target_sample_rate and sample_rate != target_sample_rate:
        audio = resample_linear(audio, sample_rate, target_sample_rate)
        sample_rate = target_sample_rate

    return audio.astype(np.float32), sample_rate


def write_wav(path, audio, sample_rate=DEFAULT_SAMPLE_RATE):
    """Write float audio in [-1, 1] as 16-bit mono WAV."""
    wav_path = Path(path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm = (samples * 32767.0).astype("<i2")
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def audio_level_stats(audio):
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return {"peak": 0.0, "rms": 0.0, "abs_p99": 0.0}

    return {
        "peak": float(np.max(np.abs(samples))),
        "rms": float(np.sqrt(np.mean(samples * samples))),
        "abs_p99": float(np.percentile(np.abs(samples), 99)),
    }


def resample_linear(audio, source_rate, target_rate):
    if source_rate == target_rate:
        return np.asarray(audio, dtype=np.float32)

    samples = np.asarray(audio, dtype=np.float32)
    if samples.size == 0:
        return samples

    duration = samples.size / float(source_rate)
    target_count = max(1, int(round(duration * target_rate)))
    source_x = np.linspace(0.0, duration, num=samples.size, endpoint=False)
    target_x = np.linspace(0.0, duration, num=target_count, endpoint=False)
    return np.interp(target_x, source_x, samples).astype(np.float32)


def record_microphone(seconds, output_path=None, sample_rate=None, device=None):
    """Record from the default microphone. Requires sounddevice."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("Install sounddevice to record from a microphone.") from exc

    if sample_rate is None:
        device_info = sd.query_devices(device, "input")
        sample_rate = int(device_info["default_samplerate"])

    device_label = "default input device" if device is None else f"device {device}"
    print(f"Recording from {device_label} for {seconds:g} seconds at {sample_rate} Hz.")
    print("Start speaking now...")

    frame_count = int(seconds * sample_rate)
    audio = sd.rec(
        frame_count,
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=device,
    )
    sd.wait()
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    stats = audio_level_stats(audio)

    if output_path:
        write_wav(output_path, audio, sample_rate)
        print(f"Recording finished. Saved WAV to {output_path}")
    else:
        print("Recording finished.")
    print(
        "Recorded level: "
        f"peak={stats['peak']:.5f}, rms={stats['rms']:.5f}, p99={stats['abs_p99']:.5f}"
    )

    return audio, sample_rate


def list_audio_devices():
    """Return available PortAudio devices. Requires sounddevice."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("Install sounddevice to list audio devices.") from exc

    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    default_input, default_output = sd.default.device
    results = []
    for index, device in enumerate(devices):
        hostapi_name = hostapis[device["hostapi"]]["name"]
        results.append(
            {
                "index": index,
                "name": device["name"],
                "hostapi": hostapi_name,
                "max_input_channels": int(device["max_input_channels"]),
                "max_output_channels": int(device["max_output_channels"]),
                "default_samplerate": float(device["default_samplerate"]),
                "default_input": index == default_input,
                "default_output": index == default_output,
            }
        )
    return results
