# simple-cli

> 从零学习 Agent —— 一个类似 Claude-CLI 的终端 AI 助手

simple-cli 是一个为**学习 Agent 原理**而构建的终端 AI 编程助手。不依赖任何 Agent 框架，仅用 `openai` SDK + Python 标准库从零实现。支持 DeepSeek / GLM / Qwen / OpenAI / Ollama 等多种大模型后端自由切换。

---

## 快速开始

### 1. 安装

```bash
# 克隆仓库
git clone https://github.com/wangxjb/simple-agent-cli.git
cd simple-agent-cli

# 安装（Python >= 3.11）
pip install -e .
```

### 2. 配置 API Key

```bash
# 方式 A：设置环境变量（推荐）
export DEEPSEEK_API_KEY="sk-你的key"

# 方式 B：直接编辑 config.toml，把 api_key = "${DEEPSEEK_API_KEY}" 改成你的真实 key
# 注意：用方式 B 后，执行 git update-index --skip-worktree config.toml 防止误提交
```

### 3. 启动

```bash
# REPL 交互模式
simple-cli

# 单轮模式
simple-cli "帮我读一下 README.md"

# 指定模型和范式
simple-cli --model glm --mode react "1+1等于几?"
```

Windows 终端需要 `-X utf8` 或设 `PYTHONUTF8=1` 来正确显示中文。Tab 补全需要 `pip install pyreadline3`。

---

## REPL 内置命令

| 命令 | 功能 |
|------|------|
| `/help` | 显示所有命令 |
| `/model <name>` | 切换模型（deepseek/glm/qwen/openai/ollama） |
| `/mode <type>` | 切换 Agent 范式（react/fc） |
| `/resume [name]` | 恢复历史会话（交互选择） |
| `/sessions` | 列出已保存的会话 |
| `/save [name]` | 保存当前会话 |
| `/tools` | 列出启用的工具 |
| `/history` | 查看当前会话历史 |
| `/clear` | 清除会话历史 |
| `/exit` | 退出（自动保存会话） |

---

## 架构

```
main.py (CLI 入口)
  └─→ repl.py (REPL 循环 / 命令处理 / Tab 补全)
        ├─→ config.py (TOML 配置 → AppConfig → create_llm_from_config)
        │     └─→ llm/client.py (统一 LLM 客户端，兼容 OpenAI 协议)
        ├─→ tools/ (可插拔工具系统)
        │     ├─→ base.py (Tool 基类 + ToolRegistry + JSON Schema 生成)
        │     └─→ builtin/ (5 个内置工具)
        ├─→ agent/ (Agent 核心)
        │     ├─→ base.py (Agent 基类 — LLM + ToolRegistry + 上下文管理)
        │     ├─→ react.py (ReAct Agent — 文本解析驱动，所有模型可用)
        │     └─→ fc.py (Function Calling Agent — 结构化 tool_calls)
        ├─→ context.py (TokenCounter + HistoryCompressor — 上下文窗口管理)
        └─→ session.py (SessionStore — 多会话 JSON 持久化)
```

### 两种 Agent 范式

| | ReAct | Function Calling |
|---|-------|-----------------|
| 驱动方式 | Prompt 模板教 LLM 输出 `Action: tool[param]` 文本 | Tools JSON Schema，LLM 返回结构化 `tool_calls` |
| 解析方式 | 正则表达式 | 直接读 Python 字段 |
| 模型兼容 | **所有**对话模型 | 需 API 支持 `tools` 参数 |
| 并行工具 | 不支持 | 原生支持 |
| 推理可见性 | 完全可见（Thought） | 隐藏在模型内部 |
| 学习价值 | 理解 Agent 本质 | 工业级实践 |

在 REPL 中用 `/mode react` 和 `/mode fc` 切换，同一问题观察两种范式的不同行为。

### 5 个内置工具

| 工具 | 功能 |
|------|------|
| `read_file` | 读取文件，支持分页 |
| `write_file` | 创建或覆盖文件 |
| `run_command` | 执行 shell 命令 |
| `list_directory` | 列出目录结构 |
| `web_search` | DuckDuckGo 搜索（零 API Key） |

工具通过 `config.toml` 中 `[tools.xxx] enabled = true/false` 开关。

### 上下文窗口管理

长对话自动管理 token，防止超出模型窗口上限：

- **Token 计数** — 基于 `tiktoken` 的增量精确计数，O(1) 开销
- **历史压缩** — LLM 生成五字段结构化摘要（任务目标/关键决策/已完成工作/待处理/重要发现）
- **滑动窗口** — 保留最近 3 轮完整对话，早期内容压缩为摘要
- **透明集成** — 在 `add_to_history()` 中自动触发，所有 Agent 子类无需修改

---

## 学习文档

`simple_cli/docs/` 下有 6 份详细文档，每份含 Mermaid 流程图/时序图/状态图：

| 文档 | 内容 |
|------|------|
| [01-llm-client.md](simple_cli/docs/01-llm-client.md) | LLM 客户端原理、流式 SSE、系统提示工程 |
| [02-tool-system.md](simple_cli/docs/02-tool-system.md) | 可插拔工具系统、JSON Schema 生成、注册表模式 |
| [03-agent-core.md](simple_cli/docs/03-agent-core.md) | ReAct vs Function Calling 两种范式详解 |
| [04-session-persistence.md](simple_cli/docs/04-session-persistence.md) | 多会话持久化、`/resume` 交互设计 |
| [05-gap-analysis.md](simple_cli/docs/05-gap-analysis.md) | 与 Claude Code 的差距分析 |
| [06-context-engineering.md](simple_cli/docs/06-context-engineering.md) | 上下文窗口管理、Token 计数、历史压缩 |

---

## 项目结构

```
simple-cli/
├── config.toml                  # 配置模板（模型、工具、系统提示）
├── pyproject.toml               # 项目依赖（仅 openai + 标准库）
├── CLAUDE.md                    # Claude Code 项目指令
├── README.md                    # 你正在读的这份文件
│
└── simple_cli/
    ├── main.py                  # CLI 入口（argparse + 模式分发）
    ├── repl.py                  # REPL 循环 + 命令处理 + Tab 补全
    ├── config.py                # TOML 加载 + ${ENV} 展开 + 多提供商管理
    ├── session.py               # SessionStore（多会话 JSON 持久化）
    ├── context.py               # TokenCounter + HistoryCompressor（上下文管理）
    │
    ├── llm/
    │   └── client.py            # HelloAgentsLLM（stream / invoke / invoke_with_tools）
    │
    ├── tools/
    │   ├── base.py              # Tool + ToolParameter + ToolRegistry
    │   └── builtin/
    │       ├── read_file.py     # 读文件工具
    │       ├── write_file.py    # 写文件工具
    │       ├── run_command.py   # 执行命令工具
    │       ├── list_dir.py      # 列目录工具
    │       └── web_search.py    # 网页搜索工具（DuckDuckGo）
    │
    ├── agent/
    │   ├── base.py              # Agent 基类 + Message
    │   ├── react.py             # ReAct Agent
    │   └── fc.py                # Function Calling Agent
    │
    └── docs/
        ├── 01-llm-client.md
        ├── 02-tool-system.md
        ├── 03-agent-core.md
        ├── 04-session-persistence.md
        ├── 05-gap-analysis.md
        └── 06-context-engineering.md
```

---

## 配置详解

`config.toml` 有三个核心节：

### [general] — 通用设置

```toml
[general]
default_provider = "deepseek"    # 默认 LLM 提供商
agent_type = "fc"                # fc 或 react
max_steps = 10                   # 最大工具调用步数
system_prompt = """..."""        # 系统提示词（Agent 的行为规范）
```

### [providers] — LLM 提供商

支持任何兼容 OpenAI API 的提供商，只需配置 `base_url` + `api_key` + `model`。

`api_key` 支持 `${ENV_VAR}` 从环境变量读取，避免密钥写死在配置文件中。

### [tools] — 工具开关

按场景启用或禁用工具。工具越少 → Schema 越小 → Token 省 → LLM 选错工具概率越低。

---

## 多会话管理

退出时自动保存会话到 `.simple_cli/sessions/{name}.json`。下次启动用 `/resume` 恢复：

```
> /sessions              # 列出所有已保存的会话
> /resume                # 交互式选择恢复
> /resume my-session     # 直接恢复指定会话
```

会话文件是标准 JSON，可以直接 `cat` 查看。

---

## 依赖

- **Python** >= 3.11
- **openai** >= 1.0.0
- **tiktoken** >= 0.5.0（Token 计数）
- **pyreadline3**（可选，Tab 补全）
