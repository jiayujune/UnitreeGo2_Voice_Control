# Unitree Go2 Voice Control

基于语音识别和意图解析的 Unitree Go2 控制项目。系统流程是：

```text
麦克风录音 -> Whisper 语音识别 -> 意图解析 -> 安全规则过滤 -> SSH/SDK 控制 Go2
```

## 目录说明

```text
voice_control_essential/   主线演示版：VAD -> STT -> intent -> safety -> Go2
Speaker_Recognition/       说话人识别相关实验模块
tools/                     小型本地测试脚本，例如录音、VAD、Whisper 测试
archive/                   旧实验代码归档，不作为当前主线入口
external/                  Unitree SDK、MuJoCo 等第三方/外部依赖
runtime/                   本地临时录音、日志、测试输出
```

## 核心入口

```bash
cd voice_control_essential
python3 local_voice_to_robot_ssh.py --text "go two stand up" --speech-output off
python3 local_voice_to_robot_ssh.py --text "go forward then turn right"   # 复合命令: 依次执行
python3 local_voice_to_robot_ssh.py --input-mode vad --stt groq --parser llm --llm-provider groq --speech-output robot-fallback

# 说话人门禁: 只有注册过的授权说话人能控制机器人
python3 local_voice_to_robot_ssh.py --enroll your_name          # 先录几条自己的声音注册
python3 local_voice_to_robot_ssh.py --input-mode vad --stt groq --parser llm --speaker-gate on
python3 voice_intent_eval.py --parser rule --limit 5 --record-seconds 2.5
python3 voice_intent_eval.py --text-only --parser rule   # 无需麦克风的快速回归测试(含误触发负例)
```

使用 Groq API 时先设置：

```bash
export GROQ_API_KEY="your_groq_api_key"
```

真实控制机器人前，请确认 Go2 与电脑在同一网络，SSH 和 Unitree SDK 环境可用，并保证机器人处于安全可控状态。

## 工具脚本

```bash
python3 tools/record_test.py --seconds 3 --output runtime/test.wav
python3 tools/vad_cut.py --input runtime/test.wav --output runtime/speech_segment.wav
python3 tools/whisper_local_test.py --input runtime/speech_segment.wav
```

## 指标统计

流水线已记录每条指令的分阶段耗时(STT / 意图解析 / 总时延)。从日志统计时延与指令映射成功率:

```bash
cd voice_control_essential
python3 pipeline_metrics.py voice_command_log.jsonl
```

说话人识别模块的评测(VAD 精确率/召回率、说话人 top-1、EER、阈值标定):

```bash
python3 -m Speaker_Recognition.evaluate <dataset>
python3 -m Speaker_Recognition.evaluate --demo   # 合成自测,无需数据
```

虚拟环境、录音、日志、缓存和本地配置不应提交。
