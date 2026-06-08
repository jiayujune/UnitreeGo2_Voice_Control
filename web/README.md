# Go2 Voice Control — Web 前端

给 [voice_control_essential](../voice_control_essential) 主线流程配的全栈网页:
**文字 / 麦克风 → Whisper STT → 意图解析 → 安全规则 → 机器人控制**。

```text
web/
  backend/    FastAPI,包装现有 Python 模块(意图解析 / 转写 / 规划 / SSH 控制)
  frontend/   React + Vite 单页应用
```

## 架构

```text
浏览器 (React :5173)
   │  /api/* (Vite 代理)
   ▼
FastAPI (:8001)
   ├─ intent_parser.parse_intent / apply_safety_rules   规则解析 + 安全层
   ├─ llm_intent_parser.parse_intent_with_llm           LLM 解析(失败回退规则)
   ├─ transcriber.build_transcriber                     local / openai / groq STT
   ├─ task_planner.plan_from_intent                     高层任务规划
   └─ ssh → robot_command_once.py                       真实机器人控制
```

## 安全:默认 dry-run

**真实控制默认关闭。** 后端只有在 `GO2_EXECUTE=1` 时才会真的 SSH 给机器人发命令;
否则所有「执行」都是空跑(dry run),不会发送任何东西。网页右上角的状态条会显示
当前是 `DRY RUN` 还是 `LIVE EXECUTION`。运动类命令(前进/后退/转向)始终需要二次确认。

## 运行

### 1. 后端

```bash
cd web
./run_backend.sh          # 首次会自动建 venv 并装依赖,然后启动 :8001
```

或手动:

```bash
cd web/backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app:app --port 8001 --reload
```

### 2. 前端

```bash
cd web/frontend
npm install      # 首次
npm run dev      # 启动 :5173
```

打开 http://localhost:5173

## 功能

- **文字指令输入框** — 输入英文指令,显示解析出的意图 JSON、安全判定、高层 plan。
- **浏览器麦克风录音** — 网页内录音上传后端做 STT(需要 STT 后端,见下)。
- **动作按钮面板** — 站立/趴下/平衡/恢复/前进/后退/左转/右转/STOP;运动类带二次确认。
- **命令历史日志** — 读取 `runtime/web_command_log.jsonl`,新命令在最上方。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `GO2_EXECUTE` | `0` | 设为 `1` 才会真实 SSH 控制机器人 |
| `GO2_SSH` | `unitree@192.168.1.200` | 机器人 SSH 目标 |
| `GO2_IFACE` | `eth0` | 网络接口 |
| `GO2_PROJECT_DIR` | `~/jiayu/UnitreeGo2_Voice_Control_Test` | 机器人端项目目录 |
| `GO2_PYTHON` | `/home/unitree/go2_sdk_venv/bin/python` | 机器人端 Python |
| `GROQ_API_KEY` | — | 用 Groq 做 STT / LLM 解析时需要 |
| `OPENAI_API_KEY` | — | 用 OpenAI 做 STT / LLM 解析时需要 |

> **STT 说明:** 浏览器录音默认用 `groq` STT(需 `GROQ_API_KEY`),也可在网页里切到 `openai`。
> 本地 Whisper(`local`)需要额外安装 `openai-whisper` + `torch`,本仓库未预装。
> 文字指令用规则解析(`rule`)无需任何 API key,开箱即用。

## 真实控制机器人

```bash
cd web/backend
GO2_EXECUTE=1 ./.venv/bin/uvicorn app:app --port 8001
```

确认 Go2 与电脑同网段、SSH 与 Unitree SDK 可用、机器人处于安全可控状态后再开启。
