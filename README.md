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
| `/compress` | 手动压缩对话历史 |
| `/remember <内容>` | 保存跨会话记忆 |
| `/memory` | 列出所有记忆 |
| `/plan <任务>` | 规划模式：生成方案等待审批 |
| `/approve` | 批准并执行当前计划 |
| `/reject` | 放弃当前计划 |
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
        │     └─→ builtin/ (6 个内置工具)
        ├─→ agent/ (Agent 核心 — auto 自动选择 FC/ReAct)
        │     ├─→ base.py (Agent 基类 — LLM + ToolRegistry + 上下文管理)
        │     ├─→ react.py (ReAct Agent — 文本解析驱动，所有模型可用)
        │     └─→ fc.py (Function Calling Agent — 结构化 tool_calls)
        ├─→ context.py (TokenCounter + HistoryCompressor — 上下文窗口管理)
        ├─→ prompt.py (PromptBuilder — 动态系统提示五维度组装)
        ├─→ memory.py (MemoryStore — 跨会话持久化记忆)
        ├─→ mcp.py (MCPClient — JSON-RPC 外部工具协议)
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

### 6 个内置工具

| 工具 | 功能 |
|------|------|
| `read_file` | 读取文件，支持分页 |
| `write_file` | 创建或覆盖文件 |
| `run_command` | 执行 shell 命令 |
| `list_directory` | 列出目录结构 |
| `web_search` | DuckDuckGo 搜索（零 API Key） |
| `verify_file` | 验证文件正确性（Python 语法 / HTML 结构 / JS 节点检查） |

工具通过 `config.toml` 中 `[tools.xxx] enabled = true/false` 开关。

### 上下文窗口管理

长对话自动管理 token，防止超出模型窗口上限：

- **Token 计数** — 基于 `tiktoken` 的增量精确计数，O(1) 开销
- **历史压缩** — LLM 生成五字段结构化摘要（任务目标/关键决策/已完成工作/待处理/重要发现）
- **滑动窗口** — 保留最近 3 轮完整对话，早期内容压缩为摘要
- **透明集成** — 在 `add_to_history()` 中自动触发，所有 Agent 子类无需修改

---

## 学习文档

`simple_cli/docs/` 下有 14 份详细文档，每份含 Mermaid 流程图/时序图/状态图：

| 文档 | 内容 |
|------|------|
| [01-llm-client.md](simple_cli/docs/01-llm-client.md) | LLM 客户端原理、流式 SSE、系统提示工程 |
| [02-tool-system.md](simple_cli/docs/02-tool-system.md) | 可插拔工具系统、JSON Schema 生成、注册表模式 |
| [03-agent-core.md](simple_cli/docs/03-agent-core.md) | ReAct vs FC 详解、参数映射演进、循环检测 |
| [04-session-persistence.md](simple_cli/docs/04-session-persistence.md) | 多会话持久化、`/resume` 交互设计 |
| [05-gap-analysis.md](simple_cli/docs/05-gap-analysis.md) | 与 Claude Code 的差距分析 |
| [06-context-engineering.md](simple_cli/docs/06-context-engineering.md) | 上下文窗口管理、Token 计数、历史压缩 |
| [07-system-prompt-engineering.md](simple_cli/docs/07-system-prompt-engineering.md) | 动态系统提示、五维度注入 |
| [08-error-recovery.md](simple_cli/docs/08-error-recovery.md) | 错误重试、指数退避 |
| [09-subagent.md](simple_cli/docs/09-subagent.md) | 子代理、上下文隔离、摘要返回 |
| [10-memory-system.md](simple_cli/docs/10-memory-system.md) | 跨会话记忆系统 |
| [11-plan-mode.md](simple_cli/docs/11-plan-mode.md) | 计划模式：规划→审批→执行 |
| [12-mcp-protocol.md](simple_cli/docs/12-mcp-protocol.md) | MCP 协议、JSON-RPC 工具桥接 |
| [13-verify-loop.md](simple_cli/docs/13-verify-loop.md) | 验证回环、创建→验证→修复 |
| [14-react-optimization.md](simple_cli/docs/14-react-optimization.md) | ReAct 优化、自动 FC 检测、工业对比 |

---

## 项目结构

```
simple-cli/
├── config.example.toml          # 配置模板（复制为 config.toml 使用）
├── pyproject.toml               # 项目依赖
├── CLAUDE.md                    # Claude Code 项目指令
├── README.md                    # 你正在读的这份文件
│
└── simple_cli/
    ├── main.py                  # CLI 入口（argparse + 模式分发）
    ├── repl.py                  # REPL 循环 + 命令处理 + Tab 补全
    ├── config.py                # TOML 加载 + ${ENV} 展开 + auto FC 检测
    ├── session.py               # SessionStore（多会话 JSON 持久化）
    ├── context.py               # TokenCounter + HistoryCompressor（上下文管理）
    ├── prompt.py                # PromptBuilder（动态系统提示五维度组装）
    ├── memory.py                # MemoryStore（跨会话记忆）
    ├── mcp.py                   # MCPClient（JSON-RPC 外部工具协议）
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
    │       ├── web_search.py    # 网页搜索工具
    │       └── verify_file.py   # 文件验证工具
    │
    ├── agent/
    │   ├── base.py              # Agent 基类（子代理 + 上下文管理 + 循环检测）
    │   ├── react.py             # ReAct Agent（Prompt 优化 + KV 双分隔符）
    │   └── fc.py                # Function Calling Agent（结构化 tool_calls）
    │
    └── docs/
        ├── 01-llm-client.md
        ├── 02-tool-system.md
        ├── ...
        └── 14-react-optimization.md
```

---

## 配置详解

`config.toml` 有三个核心节：

### [general] — 通用设置

```toml
[general]
default_provider = "deepseek"    # 默认 LLM 提供商
agent_type = "auto"              # auto = 自动检测, fc = 强制FC, react = 强制ReAct
max_steps = 0                    # 0 = 不限制，靠上下文窗口管理
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
