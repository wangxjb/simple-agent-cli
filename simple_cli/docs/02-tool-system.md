# P2: 可插拔工具系统 — Agent 的"手和脚"

## 学习目标

理解 Agent 如何通过工具与外部世界交互，掌握 JSON Schema 生成、注册表模式、工具参数验证、以及可插拔架构的设计方法。

---

## 一、没有工具 vs 有工具

```mermaid
flowchart LR
    subgraph 没有工具
        Q1["当前目录有哪些文件?"] --> L1[LLM]
        L1 --> R1["抱歉，我无法访问<br/>你的文件系统"]
        style R1 fill:#faa
    end

    subgraph 有工具
        Q2["当前目录有哪些文件?"] --> L2[LLM]
        L2 --> TC[tool_calls:<br/>list_directory]
        TC --> T[Tool 执行]
        T --> O["'找到3个文件: a, b, c'"]
        O --> L3[LLM 再次思考]
        L3 --> R2["当前目录包含3个文件: a, b, c"]
        style R2 fill:#afa
    end
```

工具就是 Agent 与外部世界交互的**唯一通道**。LLM 本身是一个纯函数的黑盒——输入文字，输出文字。工具让这个黑盒有了读写文件、执行命令、搜索网页的能力。

---

## 二、工具在 Agent 循环中的位置

```mermaid
sequenceDiagram
    participant User as 用户
    participant Agent as Agent
    participant LLM as 大模型
    participant Reg as ToolRegistry
    participant Tool as 具体工具
    participant FS as 文件系统

    User->>Agent: "读 README.md"
    Agent->>Reg: to_openai_schemas()
    Reg-->>Agent: [工具 JSON Schema 列表]

    Agent->>LLM: invoke_with_tools(messages, tools=schemas)
    LLM-->>Agent: tool_calls: [{name:"read_file", args:{path:"README.md"}}]

    Agent->>Reg: execute("read_file", {path:"README.md"})
    Reg->>Reg: get("read_file") → ReadFileTool
    Reg->>Tool: run({path:"README.md"})
    Tool->>FS: open("README.md").read()
    FS-->>Tool: "文件内容..."
    Tool-->>Reg: "文件: README.md\n=====\n文件内容..."
    Reg-->>Agent: 执行结果字符串

    Agent->>LLM: 追加 tool 消息，再次调用
    LLM-->>Agent: "README.md 的内容是..."
    Agent-->>User: 最终答案
```

---

## 三、工具的三要素

```mermaid
classDiagram
    class Tool {
        +name: str
        +description: str
        +get_parameters() List~ToolParameter~
        +run(params) str
        +to_openai_schema() dict
    }

    class ToolParameter {
        +name: str
        +type: str
        +description: str
        +required: bool
        +default: Any
    }

    class ReadFileTool {
        +name = "read_file"
        +description = "读取文件内容"
        +get_parameters() [path, offset, limit]
        +run(params)
    }

    class RunCommandTool {
        +name = "run_command"
        +description = "执行shell命令"
        +get_parameters() [command]
        +run(params)
    }

    Tool *-- ToolParameter : 包含 N 个
    ReadFileTool --|> Tool : 继承
    RunCommandTool --|> Tool : 继承
```

一个工具 = **名称**（模型用这个调用） + **描述**（模型判断何时调用） + **参数**（模型传什么输入）。

---

## 四、注册表模式（Registry Pattern）

```mermaid
flowchart TD
    subgraph ToolRegistry 内部结构
        T["_tools 字典:<br/>'read_file' → ReadFileTool<br/>'write_file' → WriteFileTool<br/>'run_command' → RunCommandTool<br/>'list_directory' → ListDirTool<br/>'web_search' → WebSearchTool"]
    end

    T --> Register["register(tool): 按名存入"]
    T --> Get["get(name): 按名取出"]
    T --> List["list_names(): 返回所有名称"]
    T --> Schema["to_openai_schemas(): 生成 JSON Schema"]
    T --> Exec["execute(name, params): 执行并捕获异常"]
```

关键代码 (`tools/base.py`):

```python
class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def to_openai_schemas(self) -> List[dict]:
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def execute(self, name: str, params: dict) -> str:
        tool = self.get(name)
        if not tool:
            return f"错误: 未找到工具 '{name}'"
        try:
            return str(tool.run(params))
        except Exception as e:
            return f"工具执行失败: {e}"
```

---

## 五、JSON Schema 生成（工具与 LLM 的握手协议）

这是工具系统里**最关键**的设计。LLM 需要结构化的工具描述才能决定何时调用哪个工具。

### 5.1 生成流程

```mermaid
flowchart LR
    P[ToolParameter 列表] --> S[to_openai_schema 方法]
    S --> J["生成 OpenAI Function Calling 格式 JSON"]
    J --> LLM[传给大模型作为 tools 参数]
```

### 5.2 类型映射

| Python type | JSON Schema type | 用途 |
|-------------|-----------------|------|
| `str` | `"string"` | 文件路径、搜索关键词 |
| `int` | `"integer"` | 行号、端口号 |
| `float` | `"number"` | 温度、概率值 |
| `bool` | `"boolean"` | 递归开关、是否确认 |
| `list` | `"array"` | 文件列表 |
| `dict` | `"object"` | 复杂配置 |

### 5.3 为什么 Schema 质量决定 Agent 质量？

```
Schema 写得好 → LLM 准确知道何时调用 → 工具调用正确率高
Schema 写得差 → LLM 不知道该调哪个 → 调错工具或忘调工具

关键:
- name: 简洁、唯一、见名知意 (read_file > rf)
- description: 说清楚"什么时候用"而不仅是"做什么"
  ❌ "读取文件"
  ✅ "当需要查看文件内容、代码、配置时使用。支持分页读取"
- parameters: 类型精确 (integer 不用 string)
```

---

## 六、可插拔设计

```mermaid
flowchart TD
    Config[config.toml] --> Parse[解析 tools 节]

    Parse --> RF{read_file<br/>enabled?}
    RF -->|true| RF_Reg[注册 ReadFileTool]
    RF -->|false| RF_Skip[跳过]

    Parse --> WF{write_file<br/>enabled?}
    WF -->|true| WF_Reg[注册 WriteFileTool]
    WF -->|false| WF_Skip[跳过]

    Parse --> RC{run_command<br/>enabled?}
    RC -->|true| RC_Reg[注册 RunCommandTool]
    RC -->|false| RC_Skip[跳过]

    RF_Reg --> Agent[Agent 携带已注册工具]
    WF_Reg --> Agent
    RC_Reg --> Agent
    RF_Skip --> Agent
    WF_Skip --> Agent
    RC_Skip --> Agent

    Agent --> LLM[传给 LLM 的工具 Schema = 只有已启用的]
```

**可插拔的意义：** 工具越多 → Schema 越大 → Token 消耗越大 → LLM 选错工具的概率越高。按场景按需启用，精准控制。

---

## 七、5 个内置工具详解

### 7.1 read_file

```mermaid
sequenceDiagram
    participant Agent
    participant Tool as ReadFileTool
    participant FS as 文件系统

    Agent->>Tool: run({path:"config.py", limit:50})
    Tool->>FS: exists("config.py")?
    FS-->>Tool: True
    Tool->>FS: open("config.py").readlines()
    FS-->>Tool: ["line1", "line2", ...]
    Tool-->>Agent: "文件: config.py (共200行)\n=====\nline1\nline2\n..."
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 文件路径 |
| `offset` | integer | 否 | 起始行号，默认 0 |
| `limit` | integer | 否 | 读取行数，默认 200 |

### 7.2 write_file

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 文件路径 |
| `content` | string | 是 | 写入内容 |

设计特点：自动创建父目录 (`os.makedirs`)，覆盖模式不追加。

### 7.3 run_command

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `command` | string | 是 | Shell 命令 |

设计特点：30 秒超时，同时捕获 stdout/stderr，输出截断 2000 字符。

### 7.4 list_directory

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 否 | 目录路径，默认 "." |
| `recursive` | boolean | 否 | 是否递归，默认 false |

设计特点：递归深度限制 2 层，避免扫出几千行输出。

### 7.5 web_search

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 搜索关键词 |

设计特点：使用 DuckDuckGo HTML 搜索，**零 API Key**，返回前 5 条结果。原理：`urllib` 请求 → 正则解析 HTML → 提取标题+摘要+URL。

---

## 八、工具执行的完整数据流

```mermaid
flowchart TD
    A[LLM 返回 tool_calls] --> B{工具名存在?}
    B -->|否| E[返回错误: 未找到工具]
    B -->|是| C[获取 Tool 实例]

    C --> D[填充默认值]
    D --> F{参数验证通过?}
    F -->|否| G[返回错误: 参数缺失]
    F -->|是| H[tool.run params]

    H --> I{执行结果?}
    I -->|成功| J[返回字符串结果]
    I -->|异常| K[捕获异常<br/>返回错误字符串]
```

核心代码 (`tools/base.py`):

```python
def execute(self, name: str, params: dict) -> str:
    tool = self.get(name)
    if not tool:
        return f"错误: 未找到工具 '{name}'"
    try:
        for p in tool.get_parameters():
            if p.name not in params and p.default is not None:
                params[p.name] = p.default
        return str(tool.run(params))
    except Exception as e:
        return f"工具 '{name}' 执行失败: {e}"
```

---

## 九、如何添加一个新工具？

以添加一个 `get_current_time` 工具为例，只需 3 步：

```python
# 1. 定义工具类
class GetTimeTool(Tool):
    def __init__(self):
        super().__init__("get_current_time", "获取当前系统时间")

    def get_parameters(self):
        return []  # 无参数

    def run(self, params):
        from datetime import datetime
        return datetime.now().isoformat()

# 2. 注册
registry.register(GetTimeTool())

# 3. 在 config.toml 中加一行
# [tools.get_current_time]
# enabled = true
```
