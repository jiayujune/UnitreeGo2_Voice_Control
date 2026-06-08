# Issue Record — Go2 Audio Output (Robot Speaker) Choppy / Silent

**Date:** 2026-05-24 → 2026-05-30
**Component:** Go2 built-in speaker (TTS output), robot-side `~/jiayu/robot_speaker_server.py` + `~/jiayu/go2_speaker.py`, web speaker integration (`web/backend`).
**Status:** Silence → **fixed**. Choppy/truncated speech → **partially mitigated, root cause is firmware-level (open).**

---

## 1. Symptom

- The Go2's built-in speaker produced **no sound at all** when driven from the voice-control pipeline / web app, even though the speaker server returned `ok: true`.
- After the silence was fixed, speech plays but is **choppy / stutters and sometimes cuts off mid-sentence**.

## 2. How the Go2 speaker actually works

- The dog's **built-in speaker is driven only by the `audiohub` DDS service** (upload a WAV clip over DDS RPC, then `play`).
- The Jetson's Linux audio (`paplay` / `pyttsx3` / `espeak` → `alsa_output.platform-sound.analog-stereo`) is **not wired to the dog's speaker** → those paths are silent. So robot speech *must* go through audiohub.
- `robot_speaker_server.py` had a `paplay` fallback that reported success but was inaudible — this masked the real failure.

## 3. Root cause #1 — total silence: cyclonedds libddsc ABI mismatch (FIXED)

- Every `cyclonedds` **Python write** (`dds_write`, reached via unitree_sdk2py RPC: SportClient / AudiohubClient / VuiClient, and even raw cyclonedds) **segfaulted** in `cyclonedds/pub.py:189 write`. Reads/subscribers worked fine.
- Sport motion appeared to "work" only because the DDS request reaches the robot just before the process crashes; audiohub needs a full request→response→upload→play sequence in one process, so the crash killed it → no audio.
- **Cause:** the `go2_sdk_venv` cyclonedds binding (0.10.2) was built against `CYCLONEDDS_HOME=/home/unitree/cyclonedds_ws/install/cyclonedds`, but at runtime over plain SSH (which does **not** source `~/.bashrc`) it loaded `/usr/local/lib/libddsc.so.0` instead — a *different* 0.10.2 build (`/home/pi/...`). **Same version number, incompatible ABI → segfault on write.**

### Fix
Set, before running any DDS code:
```bash
export CYCLONEDDS_HOME=/home/unitree/cyclonedds_ws/install/cyclonedds
export LD_LIBRARY_PATH=/home/unitree/cyclonedds_ws/install/cyclonedds/lib:$LD_LIBRARY_PATH
```
`~/.bashrc` already sets these for interactive shells ("Fix CycloneDDS library path for unitree SDK"), so the bug only bites non-interactive / service contexts.

Made permanent in the robot speaker systemd service `~/.config/systemd/user/go2-speaker.service`:
```ini
Environment=CYCLONEDDS_HOME=/home/unitree/cyclonedds_ws/install/cyclonedds
Environment=LD_LIBRARY_PATH=/home/unitree/cyclonedds_ws/install/cyclonedds/lib
```
After the fix, raw write, audiohub upload/play, and `vui` volume control all work (no segfault). **Any new robot-side script run over plain SSH must export these too.**

## 4. Root cause #2 — choppy / truncated speech (OPEN, firmware-level)

After the silence fix, audiohub plays sound but speech is choppy and sometimes truncated. Isolation tests:

| Test | Result |
|------|--------|
| 3 s pure 440 Hz tone (single block) | **smooth, complete** |
| Multi-slice TTS (8 kHz, original slicing path) | choppy |
| Multi-block single 16 kHz / 22.05 kHz clip (no resampling) | still choppy |
| Short single-block phrase ("Hello there.", ~1 s, 1 block) | **smooth** |
| ~5–8 word reply (~3 s, 2 blocks) | slightly choppy / cuts off |

**Conclusions:**
- It is **not** our slicing gaps, **not** resampling, and **not** the sample rate (a directly-generated tone is smooth at the same rates).
- The audiohub `PlayerState` never confirms `is_playing` ("state start not confirmed; using startup_ms fallback"), so playback timing is estimated.
- Single-block clips (≤ ~46 KB ≈ ~2.8 s @ 8 kHz / ~1.4 s @ 16 kHz) play reliably; longer multi-block audio degrades.
- → The defect is in the **Go2 audiohub / audio-MCU playback layer (firmware)**, below the application code. Not fixable in `go2_speaker.py` or the web app.

### Mitigation in place
- Web backend caps spoken Go2 replies to **one short phrase (≤ ~6 words)** (`CHAT_SYSTEM_PROMPT`, `max_tokens=24`) so each reply fits a single audio block.
- Speaker volume set to max via `vui.SetVolume(10)` (resets on reboot).

## 5. Open items / next steps

- Raise the audiohub speech-playback (choppy/truncated, `is_playing` never asserted) issue with **Unitree support**, or evaluate the official audio client path.
- Optionally: have `go2_speaker` split text at sentence/clause boundaries into single-block clips and tune `gap_ms` so natural pauses hide the seams (best-effort, may not fully resolve a firmware issue).
- Fallback for demos: play replies through the **computer/app speaker** (browser TTS with `espeak-ng` installed) instead of the robot speaker.

## 6. Related

- Memory: `go2-cyclonedds-libddsc-abi-fix`, `go2-robot-speaker-audiohub`.
- Robot speaker server runs as a systemd **user** service with linger enabled (auto-starts on boot, auto-restarts on crash).
