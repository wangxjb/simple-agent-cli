# P3 & P4: Agent 核心 — ReAct + Function Calling

## 学习目标

理解 Agent 的核心工作原理：**while 循环 + 工具调用**。掌握两种驱动范式（文本解析 vs 结构化 JSON），理解 Prompt 工程在 Agent 中的核心地位。

---

## 一、Agent 的本质：一个 while 循环

```mermaid
flowchart TD
    Start([用户输入问题]) --> Init[构建消息列表<br/>system_prompt + history + question]

    Init --> Call[调用 LLM]
    Call --> Parse{解析 LLM 输出}

    Parse -->|有工具调用| Exec[执行工具]
    Exec --> Append[工具结果回灌到消息列表]
    Append --> Call

    Parse -->|最终答案| Return[返回答案给用户]

    Call -->|超过 max_steps| Force[强制终止]
```

```python
# Agent 的本质，三行伪代码
while not done and step < max_steps:
    response = llm.think(messages)    # 思考
    action, params = parse(response)   # 解析动作
    result = execute(action, params)   # 执行工具
    messages.append(result)            # 反馈结果
```

这就是 Agent 的全部秘密——**不是魔法，是循环**。

---

## 二、两种驱动范式总览

```mermaid
flowchart LR
    subgraph ReAct
        R1[Prompt 模板<br/>含工具描述] --> R2[LLM 输出文本]
        R2 --> R3[正则解析<br/>Thought/Action]
        R3 --> R4[执行工具]
        R4 --> R5[Observation 回灌]
        R5 --> R2
    end

    subgraph FunctionCalling
        F1[工具 JSON Schema] --> F2[LLM 输出 JSON]
        F2 --> F3[直接读<br/>response.tool_calls]
        F3 --> F4[执行工具]
        F4 --> F5[tool 消息回灌]
        F5 --> F2
    end
```

| | ReAct | Function Calling |
|---|-------|-----------------|
| 模型要求 | **所有**对话模型 | 仅支持 FC 的模型 |
| 驱动方式 | 文本解析 | 结构化 JSON |
| 可靠性 | ~90%（正则可能失败） | ~99%（JSON 保证结构） |
| 并行工具 | 不支持 | 原生支持 |
| 推理可见性 | 完全可见（Thought） | 隐藏在模型内部 |
| Token 消耗 | Prompt 模板大 | JSON Schema 大 |

---

## 三、ReAct Agent 完整流程

### 3.1 ReAct 循环状态图

```mermaid
stateDiagram-v2
    [*] --> 构建Prompt: 用户提问
    构建Prompt --> LLM思考: 含工具描述+历史
    LLM思考 --> 解析输出: 流式接收文本

    解析输出 --> 执行工具: Action: tool[params]
    解析输出 --> 返回答案: Action: Finish[answer]
    解析输出 --> 错误处理: 解析失败

    执行工具 --> 记录结果: Observation: ...
    记录结果 --> 构建Prompt: 继续循环

    返回答案 --> [*]
    错误处理 --> 构建Prompt: 提示重试

    note right of 解析输出
        正则:
        r"Thought:\s*(.+?)(?=\nAction:|$)"
        r"Action:\s*(.+)"
    end note
```

### 3.2 ReAct 的 Prompt 模板（Agent 的灵魂）

```
你是一个能够使用工具的智能助手。

## 可用工具
{tools}                ← 由 ToolRegistry 动态生成

## 回复格式（必须严格遵守，每一项都不可省略）

### 格式规则
1. **必须**先写 Thought 行，再写 Action 行
2. Thought 和 Action **各占一行**
3. Action 只能是以下两种之一：
   - 调用工具: Action: 工具名[参数名=值1, 参数名=值2]
   - 完成任务: Action: Finish[你的最终回答]

### 工具调用规则
- 参数用 `=` 连接（不是 `:`），如 `path=config.toml`
- 多个参数用 `, ` 分隔
- 参数值中**可以**包含引号、逗号、冒号
- 工具名**必须**与上面可用工具列表中的名称完全一致

### 示例
正确: Action: read_file[path=README.md]
正确: Action: write_file[path=test.py, content=print("hello")]
错误: Action: 列出文件  ← 没有指定工具名
错误: Action: ListDir[.] ← 工具名不匹配
```

**关键理解：** Prompt 里的每一条规则都是踩过坑后加的——`=` vs `:` 的歧义、参数值含逗号导致拆碎、模型随意起工具名——这些都是实战中暴露的真实问题。

### 3.3 ReAct 解析逻辑

```mermaid
flowchart TD
    Text["LLM 输出文本<br/>含 Thought 和 Action 两行"] --> Step1

    Step1["第一步: 提取 Thought<br/>正则匹配 Thought: 到 Action: 之间的内容"]
    Step1 --> T["thought = 我需要查看文件"]

    Text --> Step2["第二步: 提取 Action<br/>正则匹配 Action: 行"]
    Step2 --> A["action = read_file[config.py]"]

    A --> Step3["第三步: 拆解 Action<br/>正则提取工具名和参数"]
    Step3 --> TN["tool_name = read_file"]
    Step3 --> TI["tool_input = config.py"]

    TI --> Map["第四步: 参数映射<br/>单值映射到第一个必填参数"]
    Map --> Exec["第五步: 执行工具<br/>registry.execute"]
```

### 3.4 ReAct 参数映射（关键实现）

ReAct 的 Action 中是纯文本参数 `read_file[config.py]`，但工具期望的是字典 `{"path": "config.py"}`。`_build_tool_params` 做智能映射，经历了多次迭代：

#### 分层映射策略

```mermaid
flowchart TD
    Input[tool_input 字符串] --> Detect{以参数名开头?<br/>例: path=... 或 path: ...}

    Detect -->|是，多参数| KV["_parse_kv_input<br/>按参数名锚点定位值边界"]
    Detect -->|否，单值| Simple["映射到第一个必填参数<br/>自动剥除可能的 param= 前缀"]

    KV --> KVDetail["支持 : 和 = 两种分隔符<br/>按参数名顺序确定值边界<br/>不依赖逗号分割"]

    Simple --> Result["{path: config.py}"]
    KVDetail --> Result
```

#### 进化历程（踩过的坑）

| 版本 | 做法 | 问题 |
|------|------|------|
| v1 | 逗号分割 `, ` | HTML 内容的逗号把参数拆碎 |
| v2 | 参数名 + `:` 锚点 | 模型用 `=` 时找不到分隔符 |
| v3（当前） | 参数名 + `[:=]` 锚点 + `=`/`:` 双支持 + 边界定位 | — |

#### v3 核心代码

```python
def _build_tool_params(self, tool_name, tool_input):
    params = tool.get_parameters()
    if len(params) > 0:
        first_param = params[0].name
        # 检测: 以 "paramName:" 或 "paramName=" 开头 → KV 模式
        if re.match(rf'{first_param}\s*[:=]', tool_input):
            return self._parse_kv_input(tool_input, params)

    # 单值: 去掉 "paramName=" 前缀，映射到第一个必填参数
    cleaned = re.sub(r'^\w+\s*[:=]\s*', '', tool_input.strip(), count=1)
    for p in params:
        if p.required:
            return {p.name: cleaned}
    return {params[0].name: cleaned} if params else {}
```

#### `_parse_kv_input` — 按参数名锚点定位

```
输入: "path= /tmp/x.html, content= <html>,<body>hi</body></html>"
                               ↑
                    不是在这里切（旧方案）
                               ↓
找到 "path=" → 值到 "content=" 前 → path = "/tmp/x.html"
找到 "content=" → 值到末尾 → content = "<html>,<body>hi</body></html>"
```

关键：用下一个参数名作为当前参数值的**边界**，而非依赖逗号。

#### `_strip_quotes` — 智能引号剥离

```python
@staticmethod
def _strip_quotes(val):
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        return val[1:-1]    # 整体包裹才去引号
    return val               # 否则保留
```

### 3.5 循环检测 — 防止死循环

`max_steps=0`（不限制步数）后，Agent 可能在完成任务后反复输出。三层检测：

| 检测类型 | 触发条件 | 处理 |
|----------|----------|------|
| **相同 Action** | 连续 2 次完全相同 | 强制终止 |
| **解析连续失败** | 连续 5 次 Action 解析失败 | 强制终止 |
| **内部错误** | Action 格式无效 | 打印提示，不写入持久化历史 |

### 3.6 ReAct 的优势与局限

**优势：**
- 所有模型都支持，包括本地 Ollama 模型
- 推理过程完全透明（可以看到 Thought）
- Prompt 简单直观，易于调试
- 学习 Agent 原理的最佳入口

**局限：**
- 正则解析不是 100% 可靠（模型有时不遵守格式）
- 不能一次调用多个工具
- Prompt 模板自身占 token

---

## 四、Function Calling Agent 完整流程

### 4.1 FC 循环状态图

```mermaid
stateDiagram-v2
    [*] --> 构建Messages: 用户提问
    构建Messages --> LLM调用: invoke_with_tools(messages, tools=schemas)

    LLM调用 --> 处理工具调用: response.tool_calls 非空
    LLM调用 --> 返回答案: response.content 纯文本

    处理工具调用 --> 追加assistant消息: 含 tool_calls 字段
    追加assistant消息 --> 执行每个工具: 可能并行多个

    执行每个工具 --> 追加tool消息: 含 tool_call_id
    追加tool消息 --> LLM调用: 模型基于结果继续推理

    返回答案 --> [*]

    note right of LLM调用
        tools 参数 = registry.to_openai_schemas()
        即每个工具的 JSON Schema
    end note
```

### 4.2 FC 消息结构（与 ReAct 的关键区别）

```mermaid
sequenceDiagram
    participant Agent as FCAgent
    participant LLM as 大模型
    participant Reg as ToolRegistry
    participant Tool as 工具

    Agent->>LLM: invoke_with_tools(messages, tools=schemas)
    Note over LLM: messages = [<br/>  {role:"system", content:"..."},<br/>  {role:"user", content:"读 README"}<br/>]
    LLM-->>Agent: {<br/>  content: null,<br/>  tool_calls: [{<br/>    id: "call_1",<br/>    name: "read_file",<br/>    arguments: {path:"README.md"}<br/>  }]<br/>}

    Agent->>Agent: 追加 assistant 消息<br/>+ tool_calls 字段
    Agent->>Reg: execute("read_file", {path:"README.md"})
    Reg->>Tool: run({path:"README.md"})
    Tool-->>Agent: "文件内容: ..."

    Agent->>Agent: 追加 tool 消息<br/>{role:"tool", tool_call_id:"call_1", content:"文件内容: ..."}

    Agent->>LLM: 再次 invoke_with_tools (含 tool 结果)
    LLM-->>Agent: {content: "README.md 的内容是...", tool_calls: null}
    Agent-->>Agent: 返回 "README.md 的内容是..."
```

### 4.3 FC 并行工具调用

FC 的核心优势之一：**一次 LLM 调用可以触发多个工具并行执行**。

```
用户: "列出目录文件并读 config.toml"

LLM 一次返回:
{
  tool_calls: [
    {id:"1", name:"list_directory", arguments:{path:"."}},
    {id:"2", name:"read_file", arguments:{path:"config.toml"}}
  ]
}

Agent 执行:
  并行: list_directory(".")  +  read_file("config.toml")
        ↓                          ↓
     "3个文件:..."           "内容: [project]..."
        ↓                          ↓
  追加两条 tool 消息 → 再次调用 LLM → 综合答案
```

---

## 五、两种范式对比总结

```mermaid
flowchart TD
    subgraph ReAct范式
        RP[Prompt含工具描述文本] --> RL[LLM输出自然语言]
        RL --> RR[正则提取 Action 和 tool_name]
        RR --> RE[执行工具]
        RE --> RO[Observation文本回灌]
        RO --> RL
    end

    subgraph FC范式
        FP[Schema含工具JSON定义] --> FL[LLM输出结构化JSON]
        FL --> FR[直接读取 response.tool_calls]
        FR --> FE[执行工具]
        FE --> FO[tool消息含 tool_call_id]
        FO --> FL
    end
```

对比维度总结：

| 维度 | ReAct | Function Calling |
|------|-------|-----------------|
| 驱动方式 | Prompt 教模型"说"工具调用 | LLM 原生支持，输出 JSON |
| 解析方式 | 正则表达式 | 直接访问 Python 字段 |
| 模型兼容性 | 任何对话模型 | 需 API 支持 tools 参数 |
| 并行工具调用 | 不支持 | 原生支持 |
| 推理过程 | 完全可见 (Thought) | 隐藏 |
| 可靠性 | ~90% | ~99% |
| 调试友好度 | 极高（看 Thought） | 一般（看不到推理） |
| 学习价值 | 理解 Agent 本质 | 工业级最佳实践 |

---

## 六、Agent 基类的设计

```mermaid
classDiagram
    class Agent {
        <<abstract>>
        +llm: HelloAgentsLLM
        +tool_registry: ToolRegistry
        +history: List~Message~
        +max_steps: int
        +system_prompt: str
        +run(question) str*
        +clear_history()
        +get_history_text() str
        #_build_tool_schemas() List~dict~
        #_build_tool_descriptions() str
        #_execute_tool(name, params) str
    }

    class ReActAgent {
        +run(question) str
        #_parse_output(text) tuple
        #_parse_action(text) tuple
        #_build_tool_params(name, input) dict
    }

    class FCAgent {
        +run(question) str
    }

    class Message {
        +content: str
        +role: str
        +to_dict() dict
    }

    Agent <|-- ReActAgent
    Agent <|-- FCAgent
    Agent o-- Message : history
```

基类封装了所有 Agent 共用的基础设施：LLM 客户端、工具注册表、历史管理、步数限制。子类只需实现 `run()` 方法，决定用什么策略驱动工具调用。
