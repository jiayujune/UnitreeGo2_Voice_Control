# Voice Control Essential

Go2 语音控制系统主线代码。完整流程：

```text
麦克风 ──► VAD ──► Whisper STT ──► 意图解析 ──► 说话人门禁 ──► 安全过滤 ──► 机器人
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `local_voice_to_robot_ssh.py` | **主入口**：完整语音控制流水线 |
| `audio_pipeline.py` | 麦克风录音 + Silero VAD 语音端点检测 |
| `transcriber.py` | STT 封装（本地 Whisper / OpenAI / Groq） |
| `intent_parser.py` | 规则式意图解析（关键词匹配，无需 API） |
| `llm_intent_parser.py` | LLM 意图解析（Groq / DeepSeek / OpenAI） |
| `speaker_gate.py` | 说话人识别门禁（Resemblyzer 嵌入，余弦相似度） |
| `robot_motion_server_ros2.py` | ROS2 Motion Server（`:8003`）：接收 HTTP /move，发布 Twist 到 `/cmd_vel_out` |
| `robot_controller.py` | 直接 SDK 控制接口（Go2 Pro/EDU，需 CycloneDDS） |
| `robot_command_once.py` | 单次命令执行脚本（被 SSH 调用） |
| `vision_server.py` | 视觉服务器（`:8002`）：人脸检测/追踪 + MJPEG 视频流 |
| `pipeline_metrics.py` | 各阶段时延统计（STT / 解析 / 发送） |
| `voice_intent_eval.py` | 意图解析评测（支持文本模式，无需麦克风） |
| `task_planner.py` | 高层任务规划（意图 → 动作序列） |
| `world_model.py` | 场景/物体状态追踪 |

## 快速开始

### Go2 Air（WebRTC，无需 SDK）

```bash
# Terminal 1：ROS2 驱动
source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash
export CONN_TYPE=webrtc ROBOT_IP=192.168.12.1
ros2 launch go2_robot_sdk robot_minimal.launch.py

# Terminal 2：Motion Server
source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash
cd ~/go2/voice_control_essential
python3 robot_motion_server_ros2.py

# Terminal 3：语音控制
python3 local_voice_to_robot_ssh.py --input-mode vad --stt groq \
  --parser llm --llm-provider groq --speech-output off
```

### Go2 Pro/EDU（直接 SDK，需 CycloneDDS）

```bash
python3 local_voice_to_robot_ssh.py --input-mode vad --stt groq --parser llm
```

### 纯文本测试（不需要麦克风，不连机器人）

```bash
python3 local_voice_to_robot_ssh.py --text "go two forward" --dry-run
python3 local_voice_to_robot_ssh.py --text "go forward then turn right" --dry-run
```

## 说话人门禁

只有已注册的声纹才能控制机器人：

```bash
# 注册自己的声纹（录 3 条）
python3 local_voice_to_robot_ssh.py --enroll your_name

# 启用门禁运行
python3 local_voice_to_robot_ssh.py --input-mode vad --speaker-gate on \
  --speaker-encoder resemblyzer
```

## 意图解析评测

```bash
# 快速回归测试（无需麦克风）
python3 voice_intent_eval.py --text-only --parser rule

# 指定数量
python3 voice_intent_eval.py --text-only --parser llm --limit 10
```

## 流水线时延统计

```bash
python3 pipeline_metrics.py voice_command_log.jsonl
```

## 视觉服务器（可选）

提供人脸检测/追踪和实时视频流，依赖 ROS2 driver 运行：

```bash
source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash
python3 -m uvicorn vision_server:app --host 0.0.0.0 --port 8002
# 视频流：http://localhost:8002/video_feed
# 人脸追踪：POST http://localhost:8002/track
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `GROQ_API_KEY` | — | Groq STT / LLM 解析 |
| `OPENAI_API_KEY` | — | OpenAI STT / LLM 解析 |
| `GO2_MOTION_URL` | `http://localhost:8003/move` | Motion server 地址 |
| `LLM_PROVIDER` | `groq` | 默认 LLM 提供商 |
