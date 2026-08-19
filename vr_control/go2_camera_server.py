#!/usr/bin/env python3
"""
Standalone Go2 camera server — bypasses aiortc H264 decoder entirely.

Flow:
  Go2 --WebRTC--> aiortc (signaling only) --H264 packets--> FFmpeg --> MJPEG --> port 8002

Run:
  source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash
  cd ~/go2/voice_control_essential
  python3 go2_camera_server.py
"""

import asyncio
import io
import subprocess
import sys
import threading
import time
import fractions

import av
import aiortc.codecs.h264 as _h264_mod
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn

# ── Patch H264Decoder to pipe raw data to FFmpeg ─────────────────────────────
# We intercept encoded_frame.data (Annex-B H264) BEFORE aiortc tries to decode
# it, and feed it straight into FFmpeg which handles error recovery far better.

_ffmpeg_proc: subprocess.Popen | None = None
_latest_jpeg: bytes | None = None
_jpeg_lock = threading.Lock()


def _start_ffmpeg():
    global _ffmpeg_proc
    _ffmpeg_proc = subprocess.Popen(
        [
            "ffmpeg",
            "-fflags", "+discardcorrupt+genpts",
            "-err_detect", "ignore_err",
            "-f", "h264",
            "-i", "pipe:0",
            "-f", "mjpeg",
            "-q:v", "4",
            "-r", "20",
            "pipe:1",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    print("[FFmpeg] process started")

    def _read_jpeg():
        global _latest_jpeg
        buf = b""
        while _ffmpeg_proc and _ffmpeg_proc.poll() is None:
            try:
                chunk = _ffmpeg_proc.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk
                # Extract complete JPEG frames
                while True:
                    a = buf.find(b"\xff\xd8")
                    if a == -1:
                        buf = b""
                        break
                    b = buf.find(b"\xff\xd9", a + 2)
                    if b == -1:
                        buf = buf[a:]  # keep partial frame
                        break
                    with _jpeg_lock:
                        _latest_jpeg = buf[a : b + 2]
                    buf = buf[b + 2:]
            except Exception:
                break
        print("[FFmpeg] output reader exited")

    threading.Thread(target=_read_jpeg, daemon=True).start()


_VIDEO_TIME_BASE = fractions.Fraction(1, 90000)

def _noop_init(self):
    # Keep a real codec context so aiortc SDP negotiation doesn't break
    self.codec = av.CodecContext.create("h264", "r")

def _ffmpeg_decode(self, encoded_frame):
    global _ffmpeg_proc
    data = encoded_frame.data
    if not data:
        return []
    if _ffmpeg_proc is None:
        _start_ffmpeg()
    if _ffmpeg_proc and _ffmpeg_proc.poll() is None:
        try:
            _ffmpeg_proc.stdin.write(data)
            _ffmpeg_proc.stdin.flush()
        except Exception:
            _ffmpeg_proc = None
    return []  # aiortc's track.recv() won't be called — no need to return frames

_h264_mod.H264Decoder.__init__ = _noop_init
_h264_mod.H264Decoder.decode  = _ffmpeg_decode

print("[Patch] H264Decoder patched — using FFmpeg subprocess for decoding")

# ── WebRTC connection to Go2 ──────────────────────────────────────────────────
import os, sys
sys.path.insert(0, "/home/jiayu/ros2_ws/build/go2_robot_sdk")

from go2_robot_sdk.infrastructure.webrtc.go2_connection import Go2Connection

ROBOT_IP  = os.getenv("ROBOT_IP",  "192.168.12.1")
ROBOT_NUM = int(os.getenv("ROBOT_NUM", "0"))

_go2_conn: Go2Connection | None = None


def _on_validated(robot_num):
    print(f"[Go2] validated — robot {robot_num}")


def _on_message(raw, parsed, robot_num):
    pass  # we don't need data channel messages here


async def _on_track(track, robot_num):
    print(f"[Go2] video track received (kind={track.kind}) — draining into FFmpeg")
    # We intentionally do NOT call track.recv().
    # Our patched H264Decoder feeds the data straight to FFmpeg.
    # We just need to keep the event loop alive so RTP keeps flowing.
    while True:
        await asyncio.sleep(5)


async def _connect():
    global _go2_conn
    while True:
        try:
            print(f"[Go2] connecting to {ROBOT_IP}…")
            _go2_conn = Go2Connection(
                robot_ip=ROBOT_IP,
                robot_num=ROBOT_NUM,
                on_validated=_on_validated,
                on_message=_on_message,
                on_video_frame=_on_track,
            )
            await _go2_conn.connect()
            print("[Go2] WebRTC connected — camera data flowing into FFmpeg")
            return
        except Exception as e:
            print(f"[Go2] connection failed ({e.__class__.__name__}), retrying in 8s…")
            await asyncio.sleep(8)


# ── FastAPI MJPEG server ──────────────────────────────────────────────────────
app = FastAPI(title="Go2 Camera Server")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def _mjpeg_generator():
    while True:
        with _jpeg_lock:
            jpeg = _latest_jpeg
        if jpeg is not None:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        else:
            time.sleep(0.05)
            continue
        time.sleep(1 / 20)


@app.get("/video_feed")
def video_feed():
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/health")
def health():
    with _jpeg_lock:
        has_frame = _latest_jpeg is not None
    return {
        "ok": True,
        "camera": "streaming" if has_frame else "waiting",
        "ffmpeg": "running" if (_ffmpeg_proc and _ffmpeg_proc.poll() is None) else "stopped",
    }


# ── Main ──────────────────────────────────────────────────────────────────────
async def _main():
    # Start FFmpeg immediately
    _start_ffmpeg()

    # Connect to robot in background
    asyncio.ensure_future(_connect())

    # Run uvicorn in the same event loop
    config = uvicorn.Config(app, host="0.0.0.0", port=8002, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(_main())
