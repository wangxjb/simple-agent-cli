# P7 & P8: 会话持久化与多会话管理

## 学习目标

理解 Agent 如何实现跨进程"记忆"——序列化/反序列化、多会话管理、`/resume` 交互设计、以及退出安全机制。

---

## 一、从失忆到记忆

```mermaid
sequenceDiagram
    participant P1 as 进程 A
    participant Disk as 磁盘
    participant P2 as 进程 B

    Note over P1: 聊了 10 轮
    P1->>Disk: json.dumps(history) → session.json
    Note over P1: 进程退出

    Note over P2: 启动
    P2->>Disk: json.loads(session.json) → List[Message]
    Note over P2: 历史恢复，继续聊
```

没有持久化时，Agent 每次启动都是"白纸一张"。持久化让它能"记住上次聊了什么"。

---

## 二、数据流：Python ↔ JSON ↔ 磁盘

```mermaid
flowchart LR
    subgraph Python内存
        H["Agent.history 列表<br/>Message 对象: role + content"]
    end

    subgraph JSON文件
        J["会话 JSON 对象<br/>name + history + provider + agent_type"]
    end

    subgraph 磁盘
        D[".simple_cli/sessions/<br/>  ├── 2026-05-16-183800.json<br/>  ├── 2026-05-16-191500.json<br/>  └── my-test.json"]
    end

    H -->|"json.dumps()"| J
    J -->|"write()"| D
    D -->|"read()"| J
    J -->|"json.loads() → Message()"| H
```

---

## 三、SessionStore 类设计

```mermaid
classDiagram
    class SessionStore {
        +sessions_dir: Path
        +save(name, history, provider, agent_type) Path
        +auto_save(history, provider, agent_type) Path
        +load(name) dict | None
        +restore_history(name) List~Message~
        +list_sessions() List~dict~
        +delete(name) bool
        +delete_all() int
        +exists(name) bool
        +has_any() bool
        -_read_file(name) dict | None
        -_extract_preview(data) str
    }

    class SessionFile {
        +name: str
        +created_at: str
        +updated_at: str
        +provider: str
        +agent_type: str
        +message_count: int
        +history: List~Message~
    }

    SessionStore --> SessionFile : 读写
```

### 关键方法详解

| 方法 | 输入 | 输出 | 用途 |
|------|------|------|------|
| `save(name, ...)` | 会话名 + 历史 + 配置 | 文件路径 | 命名保存 |
| `auto_save(...)` | 历史 + 配置 | 文件路径 | 时间戳自动命名 |
| `load(name)` | 会话名 | dict 或 None | 读取会话数据 |
| `restore_history(name)` | 会话名 | `List[Message]` | 恢复为消息对象 |
| `list_sessions()` | 无 | 会话列表（按时间倒序） | `/sessions` 和 `/resume` 命令 |
| `delete(name)` | 会话名 | bool | 删除单个会话 |

---

## 四、三个保存时机

```mermaid
stateDiagram-v2
    [*] --> 新会话

    state 新会话 {
        [*] --> 等待输入
        等待输入 --> 执行对话: 用户输入
        执行对话 --> 自动保存: 对话完成
        自动保存 --> 等待输入
    }

    state 手动保存 {
        等待输入 --> 保存命令: /save [name]
        保存命令 --> 等待输入
    }

    state 退出保存 {
        等待输入 --> 退出: /exit / Ctrl+C / Ctrl+D
        退出 --> 最终保存
        最终保存 --> [*]
    }
```

| 时机 | 触发方式 | 目的 |
|------|----------|------|
| ① 自动保存 | 每次 `agent.run()` 完成后 | 防崩溃丢数据 |
| ② 手动保存 | `/save` 或 `/save myname` | 标记重要节点 |
| ③ 退出保存 | `/exit`、Ctrl+C、Ctrl+D | 确保最新对话不丢失 |

### 退出安全的三条路径

```mermaid
flowchart TD
    Exit[输入 /exit] --> Save[保存会话]
    CtrlC[按下 Ctrl+C] --> Signal[SIGINT 信号捕获]
    Signal --> Save
    CtrlD[按下 Ctrl+D 或 EOF] --> EOF[EOFError 异常捕获]
    EOF --> Save
    Save --> Bye[打印再见并退出]
```

关键代码：

```python
# 注册 Ctrl+C 处理器
signal.signal(signal.SIGINT, _handle_interrupt)

# 主循环中捕获 Ctrl+D
try:
    user_input = input("> ").strip()
except (EOFError, KeyboardInterrupt):
    # 保存后退出
    _do_save(store, agent, current_provider, current_mode, current_session_name)
    break
```

---

## 五、/resume 恢复交互设计

### 5.1 完整交互流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant REPL as REPL
    participant Store as SessionStore
    participant Disk as 磁盘
    participant Agent as Agent

    User->>REPL: /resume
    REPL->>Store: list_sessions()
    Store->>Disk: 扫描 sessions/*.json
    Disk-->>Store: 文件列表
    Store-->>REPL: [{name, time, count, preview}, ...]

    REPL-->>User: 显示会话列表（表格形式）

    User->>REPL: 输入 "2" 或 "my-test"

    REPL->>Store: restore_history("my-test")
    Store->>Disk: 读取 my-test.json
    Disk-->>Store: JSON 数据
    Store-->>REPL: List[Message]

    REPL->>Agent: agent.history = restored_messages
    REPL->>REPL: 恢复 provider + agent_type
    REPL-->>User: "已恢复会话 'my-test' (4 条消息)"
```

### 5.2 三级匹配策略

```mermaid
flowchart TD
    Input[用户输入选择] --> Try1{能转为数字?}

    Try1 -->|是| ByIndex["按序号匹配<br/>sessions[idx-1]['name']"]
    Try1 -->|否| Try2{精确名称匹配?}

    ByIndex --> Found

    Try2 -->|是 store.exists| Exact["直接使用该名称"]
    Try2 -->|否| Try3{模糊包含匹配?}

    Exact --> Found

    Try3 -->|唯一匹配| Fuzzy["使用模糊匹配结果"]
    Try3 -->|多个匹配| Error["提示: 多个匹配"]
    Try3 -->|无匹配| NotFound["提示: 未找到"]

    Fuzzy --> Found
    Found[找到目标会话] --> Restore[调用 restore_history]
```

```python
# ① 按序号
try: idx = int(choice) - 1; target = sessions[idx]["name"]
except: pass

# ② 按名称精确匹配
if store.exists(choice): target = choice

# ③ 模糊匹配
matches = [s for s in sessions if choice.lower() in s["name"].lower()]
if len(matches) == 1: target = matches[0]
elif len(matches) > 1: print("多个匹配...")
```

### 5.3 恢复时同时恢复配置

```mermaid
flowchart TD
    Load[加载 session JSON] --> Provider{provider 在<br/>配置中存在?}
    Provider -->|是| SwitchLLM[切换到该 provider]
    Provider -->|否| KeepLLM[保持当前 LLM]

    Load --> Mode{agent_type 是<br/>react 或 fc?}
    Mode -->|是| SwitchMode[切换 Agent 类型]
    Mode -->|否| KeepMode[保持当前类型]

    SwitchLLM --> Create[重新创建 Agent]
    SwitchMode --> Create
    KeepLLM --> Create
    KeepMode --> Create

    Create --> Fill[逐条恢复 history]
    Fill --> Ready[会话就绪]
```

---

## 六、会话文件格式

```json
{
  "name": "my-test",
  "created_at": "2026-05-16T18:47:00",
  "updated_at": "2026-05-16T18:50:00",
  "provider": "deepseek",
  "agent_type": "fc",
  "message_count": 4,
  "history": [
    {"role": "user", "content": "我的名字是赵六"},
    {"role": "assistant", "content": "你好，赵六！"},
    {"role": "user", "content": "我叫什么名字？"},
    {"role": "assistant", "content": "你叫赵六"}
  ]
}
```

**各字段的设计理由：**

| 字段 | 为什么需要 |
|------|-----------|
| `name` | 文件名即会话名，列目录即可获取 |
| `created_at` | 首次创建时记录，后续覆盖不改变（保留"开始时间"） |
| `updated_at` | 每次保存更新（排序和展示用） |
| `provider` | 恢复时自动切回当时的模型 |
| `agent_type` | 恢复时自动切回当时的 Agent 范式 |
| `message_count` | **冗余字段**，避免列出所有会话时逐个读取文件统计 |

---

## 七、为什么用 JSON 而不是其他格式？

| 方案 | 优势 | 劣势 | 适用场景 |
|------|------|------|----------|
| **JSON** | 零依赖、人类可读、`cat` 就能看 | 大文件慢、无索引 | **学习阶段** |
| SQLite | 支持 SQL 查询、事务安全 | 需要额外库、不可直接阅读 | 生产环境 |
| pickle | Python 原生序列化 | 不安全、跨版本不兼容 | **永远不要用** |
| SQLAlchemy + PostgreSQL | 完整 ORM、并发、索引 | 重依赖、过度设计 | 企业级应用 |

---

## 八、与 Claude Code 的对比

| 能力 | Claude Code | simple-cli |
|------|------------|------------|
| 会话存储 | 内置自动 | 自动 + 手动 |
| 恢复命令 | `/resume` | `/resume [name]` |
| 多会话 | 支持 | 支持 |
| 会话预览 | 首条消息 | 首条用户消息 60 字符 |
| 存储格式 | 未公开 | JSON，人类可读 |
| 配置恢复 | 自动 | 自动恢复 provider + mode |
| 退出安全 | 3 种退出方式均保存 | 3 种退出方式均保存 |
