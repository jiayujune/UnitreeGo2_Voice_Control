# Unitree Go2 Voice & VR Control

基于语音识别、意图解析和 VR 沉浸式控制的 Unitree Go2 机器人控制系统。

## 系统概览

```text
【语音控制】
麦克风 → VAD → Whisper STT → 意图解析(规则/LLM) → 说话人门禁 → 安全过滤 → Go2

【VR 控制】
Go2 摄像头(WebRTC) → VIVE Pro 头显实时画面
VIVE Wand 手柄 → ROS2 Twist → Go2 运动
```

## 目录结构

```text
voice_control_essential/   语音控制系统（VAD / STT / 意图解析 / 说话人门禁 / Motion Server）
vr_control/                VR 沉浸式控制（VIVE Pro 头显 + VIVE Wand 手柄）
web/                       Web 控制界面（React 前端 + FastAPI 后端）
Speaker_Recognition/       说话人识别实验模块（MFCC / Resemblyzer / MySQL 存储）
tools/                     本地测试脚本（录音、VAD、Whisper 测试）
archive/                   旧实验代码归档
docs/                      技术文档（CycloneDDS 配置等）
runtime/                   本地运行时数据（日志、录音，不提交）
```

## 快速启动

### Go2 Air（WebRTC）—— 语音 + VR 同时运行

```bash
# 0. 连接机器人 WiFi
nmcli dev wifi connect "Go2_18636" password "88888888" ifname wlx1cbfce35e632

# 1. ROS2 驱动（Terminal 1）
source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash
export CONN_TYPE=webrtc ROBOT_IP=192.168.12.1
ros2 launch go2_robot_sdk robot_minimal.launch.py

# 2. Motion Server（Terminal 2）
source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash
cd voice_control_essential
python3 robot_motion_server_ros2.py

# 3A. 语音控制（Terminal 3）
python3 local_voice_to_robot_ssh.py --input-mode vad --stt groq \
  --parser llm --llm-provider groq

# 3B. 或 VR 控制（Terminal 3，需先启动 SteamVR）
cd ../vr_control
python3 vr_viewer.py

# 4. 切换 Sport Mode（必须）
ros2 topic pub /webrtc_req go2_interfaces/msg/WebRtcReq \
  "{api_id: 1016, topic: 'rt/api/sport/request'}" --once
```

### 纯文本测试（无麦克风，不连机器人）

```bash
cd voice_control_essential
python3 local_voice_to_robot_ssh.py --text "go two forward" --dry-run
python3 local_voice_to_robot_ssh.py --text "go forward then turn right" --dry-run
```

## 各模块详细文档

- [voice_control_essential/README.md](voice_control_essential/README.md) — 语音控制系统
- [vr_control/README.md](vr_control/README.md) — VR 沉浸式控制系统
- [web/README.md](web/README.md) — Web 控制界面
- [Speaker_Recognition/README.md](Speaker_Recognition/README.md) — 说话人识别

## 说话人门禁

只有已注册声纹的人才能向机器人发送命令：

```bash
cd voice_control_essential
python3 local_voice_to_robot_ssh.py --enroll your_name   # 注册声纹
python3 local_voice_to_robot_ssh.py --input-mode vad --speaker-gate on
```

## 流水线时延统计

```bash
cd voice_control_essential
python3 pipeline_metrics.py voice_command_log.jsonl
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `GROQ_API_KEY` | Groq STT / LLM 解析 |
| `OPENAI_API_KEY` | OpenAI STT / LLM 解析 |
| `GO2_EXECUTE` | 设为 `1` 才真实控制机器人（Web 后端用） |

使用前请确认机器人处于安全可控状态。
