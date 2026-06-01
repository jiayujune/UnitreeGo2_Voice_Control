import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field


APP_DIR = Path(__file__).resolve().parent
DEFAULT_IFACE = "eth0"
DEFAULT_TIMEOUT_SECONDS = 90
PIPER_DIR = "/home/unitree/piper_bin/piper"
PIPER_BIN = f"{PIPER_DIR}/piper"
PIPER_MODEL = "/home/unitree/piper_bin/voices/en_US-lessac-medium.onnx"

app = FastAPI(title="Go2 Speaker Server")


class SayRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    iface: str = DEFAULT_IFACE
    verbose: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


@app.get("/health")
def health():
    return {"ok": True}


def speak_with_paplay(text: str, timeout_seconds: float):
    fd, wav_path = tempfile.mkstemp(prefix="go2_direct_tts_", suffix=".wav")
    os.close(fd)

    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = PIPER_DIR + ":" + env.get("LD_LIBRARY_PATH", "")

    try:
        synth = subprocess.run(
            [PIPER_BIN, "-m", PIPER_MODEL, "-f", wav_path],
            input=text,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
        if synth.returncode != 0:
            return {
                "ok": False,
                "returncode": synth.returncode,
                "stdout": synth.stdout,
                "stderr": synth.stderr,
                "backend": "paplay",
                "stage": "synthesize",
            }

        play = subprocess.run(
            ["paplay", wav_path],
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "ok": play.returncode == 0,
            "returncode": play.returncode,
            "stdout": play.stdout,
            "stderr": play.stderr,
            "backend": "paplay",
            "stage": "play",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error": "paplay_timeout",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "backend": "paplay",
        }
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


@app.post("/say")
def say(request: SayRequest):
    python_code = (
        "from go2_speaker import speak_on_robot; "
        f"result = speak_on_robot({request.text!r}, "
        f"iface={request.iface!r}, verbose={request.verbose!r}); "
        "print(result)"
    )

    try:
        result = subprocess.run(
            [sys.executable, "-u", "-c", python_code],
            cwd=str(APP_DIR),
            text=True,
            capture_output=True,
            timeout=request.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error": "speaker_timeout",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }

    result_payload = {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "backend": "audiohub",
    }
    if result_payload["ok"]:
        return result_payload

    fallback = speak_with_paplay(request.text, request.timeout_seconds)
    fallback["audiohub_error"] = result_payload
    return fallback
