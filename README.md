# Unitree Go2 Voice Control

基于语音识别和意图解析的 Unitree Go2 控制项目。系统流程是：

```text
麦克风录音 -> Whisper 语音识别 -> 意图解析 -> 安全规则过滤 -> SSH/SDK 控制 Go2
```

## 目录说明

```text
voice_control_essential/   最终精简演示版，推荐优先阅读
go2_conversation_test/     语音聊天与动作控制实验版
go2_gui_local/             本地 Web GUI 控制实验
voice_control_test/        开发测试与评估脚本，可选提交
```

## 核心入口

```bash
cd voice_control_essential
python local_voice_to_robot_ssh.py --text "move forward"
python local_voice_to_robot_ssh.py --dry-run --speech-output off
python voice_intent_eval.py --parser rule --limit 5 --record-seconds 2.5
```

真实控制机器人前，请确认 Go2 与电脑在同一网络，SSH 和 Unitree SDK 环境可用，并保证机器人处于安全可控状态。

## GitHub 提交说明

提交前请参考 [GITHUB_PUSH清单.md](GITHUB_PUSH清单.md)。虚拟环境、录音、日志、缓存和本地配置不应提交。
