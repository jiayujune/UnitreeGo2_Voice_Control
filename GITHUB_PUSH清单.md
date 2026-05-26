# Go2 项目 GitHub Push 清单

这份清单用于决定当前项目哪些文件适合提交到 GitHub，哪些应该留在本地。

## 推荐提交的核心演示版

优先 push 这个目录。它是目前最适合汇报、展示和复现实验主流程的精简版。

```text
voice_control_essential/
  README_中文说明.md
  local_voice_to_robot_ssh.py
  intent_parser.py
  llm_intent_parser.py
  task_planner.py
  robot_command_once.py
  robot_controller.py
  robot_speaker_server.py
  voice_intent_eval.py
```

不要提交这个目录里的运行产物：

```text
voice_control_essential/__pycache__/
voice_control_essential/local_command.wav
voice_control_essential/voice_command_log.jsonl
```

## 推荐提交的测试/评估代码

如果你希望老师或同学看到完整实验过程，可以提交 `voice_control_test/` 里的源码和测试文件。

```text
voice_control_test/
  agent_dry_run.py
  command_parser.py
  connect_only_test.py
  generate_eval_report.py
  intent_parser.py
  llm_intent_parser.py
  local_voice_to_robot_ssh.py
  perception_stub.py
  robot_command_once.py
  robot_controller.py
  robot_controller_test.py
  robot_speaker_server.py
  task_planner.py
  test_agent_dry_run.py
  test_intent_parser.py
  test_llm_intent_parser.py
  test_task_planner.py
  text_intent_eval.py
  voice_command_from_file.py
  voice_intent_eval.py
  voice_loop.py
  voice_loop_old.py
  voice_loop_robot.py
  voice_loop_voice_only_success.py
```

不要提交：

```text
voice_control_test/.venv/
voice_control_test/__pycache__/
voice_control_test/.vscode/
voice_control_test/*.wav
voice_control_test/*.jsonl
voice_control_test/*.log
```

注意：`voice_control_essential/` 里的 8 个核心 `.py` 文件目前和 `voice_control_test/` 中同名文件内容一致。如果只想提交最终版，可以不提交 `voice_control_test/`。

## 可选提交的对话实验版

`go2_conversation_test/` 是语音聊天和动作控制实验。当前建议只提交 v4 主线：

```text
go2_conversation_test/
  voice_llm_talk_v4.py
  motion_interface.py
  run_voice_llm_talk_v4.sh
  requirements.txt
```

不要提交：

```text
go2_conversation_test/.venv/
go2_conversation_test/__pycache__/
go2_conversation_test/*.wav
go2_conversation_test/*.jsonl
```

## 可选提交的本地 Web GUI

如果 GitHub 项目想展示图形界面，可以提交：

```text
go2_gui_local/
  go2_web_gui_local.py
  go2_web_gui_v2_local.py
```

不要提交：

```text
go2_gui_local/__pycache__/
go2_gui_local/.vscode/
```

## SDK 和仿真器

### unitree_sdk2_python

如果你希望别人 clone 后能直接看到 SDK 依赖代码，可以提交 `unitree_sdk2_python/`，但不要提交虚拟环境和构建产物。

必须排除：

```text
unitree_sdk2_python/venv/
unitree_sdk2_python/__pycache__/
unitree_sdk2_python/unitree_sdk2py/__pycache__/
unitree_sdk2_python/unitree_sdk2py.egg-info/
unitree_sdk2_python/cyclonedds/build/
unitree_sdk2_python/cyclonedds/install/
```

更推荐的做法：GitHub README 里说明需要安装 Unitree SDK，而不是把完整第三方 SDK 都放进自己的项目仓库。

### unitree_mujoco

如果你的 GitHub 项目主题是“语音控制真实 Go2”，可以不提交 `unitree_mujoco/`。

如果你还要展示仿真，才提交它。这个目录包含大量模型资源，仓库会变大。

## 最推荐的 GitHub 仓库结构

如果目标是课程汇报/项目展示，建议提交：

```text
.
├── .gitignore
├── GITHUB_PUSH清单.md
├── voice_control_essential/
├── go2_conversation_test/
└── go2_gui_local/
```

如果目标是完整复现开发和测试，再额外提交：

```text
voice_control_test/
```

如果目标是离线完整运行，并且不介意仓库很大，再考虑提交：

```text
unitree_sdk2_python/
unitree_mujoco/
```

## 当前 GitHub 仓库地址

```text
https://github.com/jiayujune/UnitreeGo2_Voice_Control
```

首次提交可以使用：

```bash
cd /home/jiayu/go2
git init
git branch -M main
git remote add origin https://github.com/jiayujune/UnitreeGo2_Voice_Control.git
git add .gitignore GITHUB_PUSH清单.md voice_control_essential go2_conversation_test go2_gui_local
git commit -m "Add Go2 voice control project"
git push -u origin main
```

如果你也想提交开发测试目录，再额外执行：

```bash
git add voice_control_test
git commit -m "Add voice control tests"
git push
```

## 不建议提交到 GitHub 的文件类型

```text
*.wav
*.jsonl
*.log
__pycache__/
*.pyc
.venv/
venv/
.env
.vscode/
```

这些文件要么是运行时生成的，要么是本机环境相关，要么可能包含私人记录或密钥信息。
