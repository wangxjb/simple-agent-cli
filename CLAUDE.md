# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

simple-cli 是一个**从零学习 Agent 原理的终端 AI 助手**，类似 Claude-CLI。仅依赖 `openai` SDK + Python 标准库，支持 DeepSeek/GLM/Qwen/OpenAI/Ollama 等多种大模型后端。

## 常用命令

```bash
# 安装开发依赖
pip install -e .

# 启动 REPL 交互模式
python -X utf8 -c "from simple_cli.repl import repl; from simple_cli.config import load_config; repl(load_config())"

# 单轮模式
python -X utf8 -c "from simple_cli.main import main; import sys; sys.argv=['simple-cli', '你的问题']; main()"

# 快速验证（无需 API Key）
python -c "from simple_cli.tools import ToolRegistry; from simple_cli.tools.builtin import *; r=ToolRegistry(); r.register(ListDirTool()); print(r.execute('list_directory', {'path':'.'}))"

# 指定模型和范式
python -X utf8 -c "...main()" -- --model glm --mode react
```

Windows 终端需要 `-X utf8` 或 `PYTHONUTF8=1` 来正确显示中文。Tab 补全需要 `pyreadline3`（`pip install pyreadline3`）。

## 架构

核心循环是 **6 个模块的协作**，数据从用户输入到 LLM 再到工具执行，形成闭环：

```
main.py (CLI 入口)
  └─→ repl.py (REPL 循环 / 命令处理 / Tab 补全)
        ├─→ config.py (TOML 配置 → AppConfig → create_llm_from_config)
        │     └─→ llm/client.py (HelloAgentsLLM — OpenAI 协议兼容层)
        ├─→ tools/base.py (ToolRegistry → 按 config.toml 中 [tools] 节开关)
        │     └─→ tools/builtin/*.py (5 个内置工具)
        ├─→ agent/ (两种 Agent: ReActAgent 文本解析 vs FCAgent Function Calling)
        │     └─→ agent/base.py (Agent 基类 — LLM + ToolRegistry + 历史管理)
        └─→ session.py (SessionStore — 多会话 JSON 持久化)
```

**两种 Agent 范式的关键区别：**
- `ReActAgent`：Prompt 模板教 LLM 输出 `Action: tool[param]` 文本，正则解析执行。**任何模型都支持。**
- `FCAgent`：传 `tools` JSON Schema 给 LLM，LLM 返回结构化 `tool_calls`。需要模型支持 Function Calling。

**LLM 层 `HelloAgentsLLM`** 只依赖 `openai` SDK，通过切换 `base_url` 适配不同厂商。提供三个方法：`stream()`（逐 token yield）、`invoke()`（非流式返回完整结果）、`invoke_with_tools()`（Function Calling）。

**工具系统** 通过 `ToolRegistry.to_openai_schemas()` 自动生成 OpenAI Function Calling 格式的 JSON Schema。工具开关由 `config.toml` 中 `[tools.xxx] enabled = true/false` 控制。

**会话持久化** 使用 `SessionStore`，每次对话后自动保存到 `.simple_cli/sessions/{name}.json`。`/resume` 命令支持按序号、精确名称、模糊匹配三种方式恢复。

## 配置文件查找优先级

1. `SIMPLE_CLI_CONFIG` 环境变量指定的路径
2. 当前工作目录 `./config.toml`
3. `~/.simple_cli/config.toml`
4. `simple_cli/` 包目录下的 `config.toml`

`api_key` 支持 `${ENV_VAR}` 语法，运行时由 `os.path.expandvars()` 展开。

## 学习文档

`simple_cli/docs/` 目录下有 5 份详细文档，每份都包含 Mermaid 流程图/时序图/状态图：
- `01-llm-client.md` — LLM 客户端原理 + 系统提示工程
- `02-tool-system.md` — 可插拔工具系统 + JSON Schema 生成
- `03-agent-core.md` — ReAct vs FC 两种 Agent 范式详解
- `04-session-persistence.md` — 多会话持久化 + /resume 设计
- `05-gap-analysis.md` — 与 Claude Code 的差距分析
