import time
import wave
from pathlib import Path

import numpy as np


DEFAULT_SAMPLE_RATE = 16000


def write_wav(path, audio, sample_rate=DEFAULT_SAMPLE_RATE):
    wav_path = Path(path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.clip(np.asarray(audio, dtype=np.float32).reshape(-1), -1.0, 1.0)
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


def record_fixed_duration(
    output_path,
    seconds,
    sample_rate=DEFAULT_SAMPLE_RATE,
    device=None,
):
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("Install sounddevice to record from a microphone.") from exc

    device_label = "default input device" if device is None else f"device {device}"
    print(f"\nRecording from {device_label} for {seconds:g} seconds at {sample_rate} Hz.")
    print("Say one command, for example: go two stop")

    audio = sd.rec(
        int(seconds * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=device,
    )
    sd.wait()

    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    write_wav(output_path, audio, sample_rate)
    stats = audio_level_stats(audio)

    print(f"Recording finished: {output_path}")
    print(
        "Recorded level: "
        f"peak={stats['peak']:.5f}, rms={stats['rms']:.5f}, p99={stats['abs_p99']:.5f}"
    )
    return output_path


def cut_speech_from_file(
    input_path,
    output_path,
    sample_rate=DEFAULT_SAMPLE_RATE,
    threshold=0.5,
):
    import torch
    import warnings

    if hasattr(torch.backends, "nnpack"):
        torch.backends.nnpack.enabled = False

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*NNPACK.*")
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
    get_speech_timestamps, save_audio, read_audio, _, collect_chunks = utils

    wav = read_audio(input_path, sampling_rate=sample_rate)
    speech_timestamps = get_speech_timestamps(
        wav,
        model,
        sampling_rate=sample_rate,
        threshold=threshold,
    )

    print("Speech timestamps:", speech_timestamps)
    if not speech_timestamps:
        print("No speech detected.")
        write_wav(output_path, np.zeros(0, dtype=np.float32), sample_rate)
        return {
            "speech_detected": False,
            "segments": [],
            "output_path": output_path,
        }

    speech_audio = collect_chunks(speech_timestamps, wav)
    save_audio(output_path, speech_audio, sampling_rate=sample_rate)
    print(f"Saved speech segment: {output_path}")
    return {
        "speech_detected": True,
        "segments": speech_timestamps,
        "output_path": output_path,
    }


class SileroVADRecorder:
    def __init__(
        self,
        sample_rate=DEFAULT_SAMPLE_RATE,
        threshold=0.5,
        min_speech_ms=250,
        silence_ms=800,
        pre_roll_ms=300,
        chunk_samples=512,
        device=None,
    ):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.min_speech_ms = min_speech_ms
        self.silence_ms = silence_ms
        self.pre_roll_ms = pre_roll_ms
        self.chunk_samples = chunk_samples
        self.device = device
        self._model = None
        self._vad_iterator = None

    def _load(self):
        if self._vad_iterator is not None:
            self._vad_iterator.reset_states()
            return

        import torch
        import warnings

        if hasattr(torch.backends, "nnpack"):
            torch.backends.nnpack.enabled = False

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*NNPACK.*")
            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
            )
        (_, _, _, vad_iterator_cls, _) = utils
        self._model = model
        self._vad_iterator = vad_iterator_cls(
            model,
            threshold=self.threshold,
            sampling_rate=self.sample_rate,
        )

    def record_until_speech_ends(
        self,
        output_path,
        max_seconds=8.0,
        start_timeout_seconds=5.0,
    ):
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("Install sounddevice to record from a microphone.") from exc

        import torch

        self._load()
        assert self._vad_iterator is not None

        print("\nListening with Silero VAD...")
        print("Speak one command. Recording stops after speech ends.")

        chunks = []
        pre_roll = []
        triggered = False
        speech_started_at = None
        speech_ended_at = None
        start_time = time.monotonic()
        max_pre_roll_chunks = max(
            1,
            int((self.pre_roll_ms / 1000.0) * self.sample_rate / self.chunk_samples),
        )

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.chunk_samples,
            device=self.device,
        ) as stream:
            while True:
                now = time.monotonic()
                if now - start_time > max_seconds:
                    break
                if not triggered and now - start_time > start_timeout_seconds:
                    print("No speech detected before timeout.")
                    break

                data, overflowed = stream.read(self.chunk_samples)
                if overflowed:
                    print("Microphone input overflowed; continuing.")

                chunk = np.asarray(data, dtype=np.float32).reshape(-1)
                vad_event = self._vad_iterator(torch.from_numpy(chunk))

                if not triggered:
                    pre_roll.append(chunk)
                    if len(pre_roll) > max_pre_roll_chunks:
                        pre_roll.pop(0)

                if vad_event:
                    if "start" in vad_event and not triggered:
                        triggered = True
                        speech_started_at = now
                        chunks.extend(pre_roll)
                        pre_roll = []
                        print("Speech started.")
                    elif "end" in vad_event and triggered:
                        speech_ended_at = now

                if triggered:
                    chunks.append(chunk)
                    if (
                        speech_ended_at is not None
                        and now - speech_ended_at >= self.silence_ms / 1000.0
                    ):
                        break

        if not chunks:
            write_wav(output_path, np.zeros(0, dtype=np.float32), self.sample_rate)
            return {
                "path": output_path,
                "speech_detected": False,
                "duration": 0.0,
                "stats": audio_level_stats([]),
            }

        audio = np.concatenate(chunks).astype(np.float32)
        duration = audio.size / float(self.sample_rate)
        min_speech_seconds = self.min_speech_ms / 1000.0
        speech_detected = bool(speech_started_at is not None and duration >= min_speech_seconds)

        write_wav(output_path, audio, self.sample_rate)
        stats = audio_level_stats(audio)
        print(f"VAD recording saved: {output_path}")
        print(f"VAD clip duration: {duration:.2f}s, speech_detected={speech_detected}")
        print(
            "Recorded level: "
            f"peak={stats['peak']:.5f}, rms={stats['rms']:.5f}, p99={stats['abs_p99']:.5f}"
        )
        return {
            "path": output_path,
            "speech_detected": speech_detected,
            "duration": duration,
            "stats": stats,
        }
