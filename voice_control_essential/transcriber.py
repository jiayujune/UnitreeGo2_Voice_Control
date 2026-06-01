import json
import os
import uuid
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_LOCAL_WHISPER_MODEL = "base"
DEFAULT_OPENAI_TRANSCRIPTION_MODEL = "whisper-1"
DEFAULT_GROQ_TRANSCRIPTION_MODEL = "whisper-large-v3-turbo"


class TranscriptionError(Exception):
    pass


class LocalWhisperTranscriber:
    def __init__(self, model_name=DEFAULT_LOCAL_WHISPER_MODEL, language="en"):
        self.model_name = model_name
        self.language = language
        self._model = None

    def _load(self):
        if self._model is not None:
            return

        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        import whisper

        print(f"Loading local Whisper model: {self.model_name}")
        self._model = whisper.load_model(self.model_name, device="cpu")
        print("Local Whisper model loaded.")

    def transcribe(self, audio_path, prompt=None):
        self._load()
        assert self._model is not None

        result = self._model.transcribe(
            str(audio_path),
            language=self.language,
            fp16=False,
            temperature=0,
            condition_on_previous_text=False,
            initial_prompt=prompt,
        )
        return str(result.get("text", "")).strip()


class OpenAIWhisperAPITranscriber:
    def __init__(
        self,
        model_name=None,
        api_key=None,
        base_url=None,
        language="en",
        api_key_env="OPENAI_API_KEY",
        default_base_url="https://api.openai.com/v1",
        default_model=DEFAULT_OPENAI_TRANSCRIPTION_MODEL,
        provider_label="OpenAI",
    ):
        self.model_name = (
            model_name
            or os.getenv(f"{provider_label.upper()}_TRANSCRIBE_MODEL")
            or default_model
        )
        self.api_key_env = api_key_env
        self.api_key = api_key or os.getenv(api_key_env)
        self.base_url = (base_url or os.getenv(f"{provider_label.upper()}_BASE_URL") or default_base_url).rstrip("/")
        self.language = language
        self.provider_label = provider_label

    def transcribe(self, audio_path, prompt=None):
        if not self.api_key:
            raise TranscriptionError(f"Missing {self.api_key_env} for {self.provider_label} transcription API.")

        path = Path(audio_path)
        boundary = f"----go2-voice-{uuid.uuid4().hex}"
        body = self._build_multipart_body(path, boundary, prompt)
        request = urllib.request.Request(
            f"{self.base_url}/audio/transcriptions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
                "User-Agent": "go2-voice-control-transcriber/0.1",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise TranscriptionError(f"{self.provider_label} transcription HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise TranscriptionError(f"{self.provider_label} transcription request failed: {exc}") from exc

        data = json.loads(response_body)
        return str(data.get("text", "")).strip()

    def _build_multipart_body(self, path, boundary, prompt):
        parts = [
            self._field(boundary, "model", self.model_name),
            self._field(boundary, "language", self.language),
            self._field(boundary, "response_format", "json"),
        ]
        if prompt:
            parts.append(self._field(boundary, "prompt", prompt))

        file_header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8")
        parts.append(file_header + path.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(parts)

    @staticmethod
    def _field(boundary, name, value):
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")


class GroqWhisperAPITranscriber(OpenAIWhisperAPITranscriber):
    def __init__(self, model_name=None, api_key=None, base_url=None, language="en"):
        super().__init__(
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            language=language,
            api_key_env="GROQ_API_KEY",
            default_base_url="https://api.groq.com/openai/v1",
            default_model=DEFAULT_GROQ_TRANSCRIPTION_MODEL,
            provider_label="Groq",
        )


def build_transcriber(stt_mode, model_name=None, language="en"):
    if stt_mode == "openai":
        return OpenAIWhisperAPITranscriber(model_name=model_name, language=language)
    if stt_mode == "groq":
        return GroqWhisperAPITranscriber(model_name=model_name, language=language)
    if stt_mode == "local":
        return LocalWhisperTranscriber(model_name=model_name or DEFAULT_LOCAL_WHISPER_MODEL, language=language)
    raise ValueError(f"Unknown STT mode: {stt_mode}")
