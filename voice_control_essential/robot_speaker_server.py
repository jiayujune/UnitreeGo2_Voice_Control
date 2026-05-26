import json
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field


APP_DIR = Path(__file__).resolve().parent
DEFAULT_IFACE = "eth0"
DEFAULT_TIMEOUT_SECONDS = 90

app = FastAPI(title="Go2 Speaker Server")


class SayRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    iface: str = DEFAULT_IFACE
    verbose: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


@app.get("/health")
def health():
    return {"ok": True}


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

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
