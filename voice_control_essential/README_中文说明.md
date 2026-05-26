# Unitree Go2 语音控制系统精简版

这个文件夹只保留汇报和演示最重要的代码文件，适合讲解系统主流程。

## 文件说明

| 文件 | 作用 |
|---|---|
| `voice_intent_eval.py` | 语音意图识别评估脚本，负责批量录音、Whisper 转文字、意图解析、计算准确率 |
| `local_voice_to_robot_ssh.py` | 主控制程序，负责录音、语音识别、意图解析、安全判断、通过 SSH 发送机器人命令 |
| `intent_parser.py` | 规则意图解析核心，把自然语言转换成结构化动作 JSON |
| `llm_intent_parser.py` | LLM 意图解析模块，用于支持更灵活的自然语言表达 |
| `task_planner.py` | 根据意图生成高层任务计划 |
| `robot_command_once.py` | 机器人端单次动作执行入口 |
| `robot_controller.py` | Unitree Go2 SDK 控制封装 |
| `robot_speaker_server.py` | 机器人扬声器服务，用于让 Go2 说话 |

## 推荐演示命令

文本输入测试：

```bash
python local_voice_to_robot_ssh.py --text "move forward"
```

语音 dry-run，不发送机器人命令：

```bash
python local_voice_to_robot_ssh.py --dry-run --speech-output off
```

语音意图评估：

```bash
python voice_intent_eval.py --parser rule --limit 5 --record-seconds 2.5
```

真实控制机器人：

```bash
python local_voice_to_robot_ssh.py
```

真实控制需要 Go2 和电脑在同一网络，SSH 可以连接机器人，并且机器人处于安全可控状态。
