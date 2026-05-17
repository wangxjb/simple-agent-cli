# T2-⑥: 计划模式 — 规划→审批→执行

## 学习目标

理解工作流模板模式：大任务前先规划后执行，避免盲目行动导致返工。

---

## 一、问题：Agent 容易"埋头就干"

```
用户: "帮我实现一个用户认证系统"

Agent（无计划模式）:
  直接就写 auth.py → 写到一半发现需要先改数据库 → 推到重来
  → 浪费 10 轮对话

Agent（有计划模式）:
  先探索代码库 → 分析依赖 → 生成计划 → 用户审批 → 逐步执行
  → 每一步都有方向
```

## 二、计划模式状态机

```mermaid
stateDiagram-v2
    [*] --> Normal: 正常对话

    Normal --> Planning: /plan "大任务"
    Planning --> 展示计划: 探索 → 分析 → 生成方案
    展示计划 --> Normal: /reject 放弃计划
    展示计划 --> Executing: /approve 批准执行
    Executing --> Normal: 执行完成
```

## 三、命令

| 命令 | 功能 |
|------|------|
| `/plan <任务>` | 进入计划模式，Agent 探索并生成方案 |
| `/approve` | 批准当前计划，进入执行阶段 |
| `/reject` | 拒绝计划，回到正常模式 |

## 四、与时序图

```mermaid
sequenceDiagram
    participant User
    participant Agent
    participant LLM

    User->>Agent: /plan "实现用户认证"
    Agent->>LLM: 探索代码库 + 分析依赖
    LLM-->>Agent: 项目结构、现有代码

    Agent->>LLM: 根据上下文设计方案
    LLM-->>Agent: 结构化计划

    Agent-->>User: 展示计划:<br/>1. 创建 auth/models.py<br/>2. 实现登录/注册<br/>3. 添加中间件<br/>...

    User->>Agent: /approve
    Agent->>Agent: 按计划逐步执行
    Agent-->>User: 执行完成
```
