"""Agent 基类 — ReActAgent 和 FCAgent 的共享基础设施"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from ..llm import HelloAgentsLLM
from ..tools import ToolRegistry
from ..context import TokenCounter, HistoryCompressor
from ..prompt import PromptBuilder


class Message:
    """一条对话消息"""

    def __init__(self, content: str, role: str):
        self.content = content
        self.role = role    # system / user / assistant / tool

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}

    def __repr__(self) -> str:
        preview = self.content[:60].replace("\n", " ")
        return f"Message({self.role}: {preview}...)"


class Agent(ABC):
    """
    Agent 基类。

    所有 Agent 共享：
    - LLM 客户端：负责调用大模型
    - 工具注册表：管理可用工具
    - 历史记录：维护多轮对话上下文
    - 上下文管理：token 计数 + 自动压缩
    - 步数限制：避免无限循环
    """

    def __init__(
        self,
        llm: HelloAgentsLLM,
        tool_registry: Optional[ToolRegistry] = None,
        system_prompt: Optional[str] = None,
        max_steps: int = 5,
        context_window: int = 65536,
        compression_threshold: float = 0.8,
        min_retain_rounds: int = 3,
    ):
        self.llm = llm
        self.tool_registry = tool_registry or ToolRegistry()
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.history: List[Message] = []

        # 上下文管理
        self.token_counter = TokenCounter(model=llm.model)
        self._token_count = 0
        self._compressor = HistoryCompressor(
            llm=llm,
            context_window=context_window,
            compression_threshold=compression_threshold,
            min_retain_rounds=min_retain_rounds,
            token_counter=self.token_counter,
        )
        # 动态系统提示
        self.prompt_builder = PromptBuilder(base_prompt=system_prompt)

        self._compression_count = 0  # 压缩次数统计
        self._summary = ""  # 当前有效的历史摘要

    @abstractmethod
    def run(self, question: str) -> str:
        """执行 Agent，返回最终回答"""
        ...

    # ===== 公共工具方法 =====

    def _build_tool_schemas(self) -> List[Dict[str, Any]]:
        """生成 OpenAI Function Calling 格式的工具列表"""
        return self.tool_registry.to_openai_schemas()

    def _build_tool_descriptions(self) -> str:
        """生成人类可读的工具描述（ReAct 用）"""
        if not self.tool_registry:
            return "无可用工具"

        lines = []
        for name in self.tool_registry.list_names():
            tool = self.tool_registry.get(name)
            if tool:
                params_desc = ", ".join(
                    f"{p.name}: {p.type}" for p in tool.get_parameters()
                )
                lines.append(f"- {name}[{params_desc}]: {tool.description}")
        return "\n".join(lines)

    def _execute_tool(self, name: str, params: Dict[str, Any]) -> str:
        """执行工具并返回结果字符串"""
        return self.tool_registry.execute(name, params)

    def add_to_history(self, content: str, role: str):
        """
        添加一条消息到历史，并自动检查是否需要压缩。

        增量 token 计数：只计算新消息的 token，不重复计算历史。
        """
        self.history.append(Message(content, role))

        # 增量计算 token
        self._token_count += self.token_counter.count_message(content)

        # 检查是否需要压缩
        if self._compressor.should_compress(self._token_count):
            self._do_compress()

    def clear_history(self):
        """清空历史及上下文管理状态"""
        self.history.clear()
        self._token_count = 0
        self._summary = ""
        self._compression_count = 0

    def get_history_text(self) -> str:
        """格式化为纯文本历史（ReAct 用）"""
        return "\n".join(
            f"[{msg.role}]: {msg.content}" for msg in self.history
        )

    def token_usage(self) -> Dict[str, Any]:
        """返回当前 token 使用情况"""
        return {
            "current_tokens": self._token_count,
            "threshold": self._compressor.threshold,
            "percent": round(self._token_count / self._compressor.threshold * 100, 1) if self._compressor.threshold else 0,
            "compressions": self._compression_count,
            "message_count": len(self.history),
        }

    # ===== 上下文压缩 =====

    def compress_history(self) -> Dict[str, Any]:
        """
        手动触发历史压缩。

        即使 token 未超阈值，也可以主动压缩。
        返回压缩前后的统计信息。
        """
        before = self.token_usage()
        if len(self.history) < 4:
            return {"status": "skip", "reason": "消息太少，无需压缩"}

        # 检查是否真的能压缩（轮数 > min_retain_rounds）
        raw = [{"role": m.role, "content": m.content} for m in self.history]
        rounds = self._compressor._find_round_boundaries(raw)
        if len(rounds) <= self._compressor.min_retain_rounds:
            return {"status": "skip",
                    "reason": f"只有 {len(rounds)} 轮对话，需超过 {self._compressor.min_retain_rounds} 轮才压缩"}

        self._do_compress()
        after = self.token_usage()
        return {
            "status": "ok",
            "before_tokens": before["current_tokens"],
            "after_tokens": after["current_tokens"],
            "reduced": before["current_tokens"] - after["current_tokens"],
            "compressions": self._compression_count,
        }

    def _do_compress(self):
        """
        执行历史压缩。

        将 history 转为 dict 列表 → 压缩 → 重新解析为 Message 列表。
        压缩后重新计算 token。
        """
        raw = [{"role": m.role, "content": m.content} for m in self.history]
        compressed = self._compressor.compress(raw)

        # 提取摘要
        for msg in compressed:
            if msg["role"] == "system" and msg["content"].startswith("[历史摘要]"):
                self._summary = msg["content"]
                break

        # 重建 history（跳过 system 角色中纯摘要的，因为每次都会重新注入）
        new_history = []
        for msg in compressed:
            if msg["role"] == "system" and msg["content"].startswith("[历史摘要]"):
                continue  # 摘要由 _build_base_messages 动态注入
            new_history.append(Message(msg["content"], msg["role"]))

        self.history = new_history
        self._token_count = self.token_counter.count_messages(compressed)
        self._compression_count += 1

    def _build_base_messages(self) -> List[Dict[str, Any]]:
        """
        构建基础消息列表（动态 system_prompt + 摘要 + history）。

        子类的 run() 方法应使用此方法构建初始 messages。
        """
        messages: List[Dict[str, Any]] = []

        # 动态系统提示（角色 + 环境 + 工具 + 项目 + 状态）
        dynamic_prompt = self.prompt_builder.build(self)
        messages.append({"role": "system", "content": dynamic_prompt})

        # 历史摘要（如果已压缩）
        if self._summary:
            messages.append({"role": "system", "content": self._summary})

        # 历史消息
        for msg in self.history:
            messages.append(msg.to_dict())

        return messages

    # ===== 子代理 =====

    def run_as_subagent(
        self,
        task: str,
        tool_filter: Optional[List[str]] = None,
        max_steps_override: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        作为子代理运行任务 — 上下文隔离模式。

        保存当前状态 → 创建独立上下文 → 执行 → 恢复 → 返回摘要。

        Args:
            task: 子任务描述
            tool_filter: 允许使用的工具名列表，None = 全部可用
            max_steps_override: 覆盖 max_steps

        Returns:
            {
                "success": bool,
                "summary": str,
                "metadata": {steps, tools_used, duration_seconds, ...}
            }
        """
        import time

        # 1. 保存主 Agent 状态
        saved_history = list(self.history)
        saved_token_count = self._token_count
        saved_summary = self._summary

        # 2. 工具过滤
        disabled_tools = {}
        if tool_filter and self.tool_registry:
            for name in self.tool_registry.list_names():
                if name not in tool_filter:
                    disabled_tools[name] = self.tool_registry.get(name)
                    self.tool_registry.unregister(name)

        # 3. 覆盖 max_steps
        original_max_steps = self.max_steps
        if max_steps_override is not None:
            self.max_steps = max_steps_override

        # 4. 隔离上下文
        self.history = []
        self._token_count = 0
        self._summary = ""

        # 5. 执行
        start = time.time()
        success = True
        result = ""
        try:
            result = self.run(task)
        except Exception as e:
            success = False
            result = f"子代理执行失败: {e}"

        duration = round(time.time() - start, 2)
        steps = len([m for m in self.history if m.role == "assistant"])
        # 提取工具名: "Tool read_file({'path':'x'}) → ..." → "read_file"
        tools_used = []
        for m in self.history:
            if m.role == "tool":
                name = m.content.split("(")[0].replace("Tool ", "").strip()
                if name and name not in tools_used:
                    tools_used.append(name)

        # 6. 生成摘要
        summary = self._make_subagent_summary(task, result, steps, tools_used, duration)

        # 7. 恢复主 Agent 状态
        self.history = saved_history
        self._token_count = saved_token_count
        self._summary = saved_summary
        self.max_steps = original_max_steps
        for name, tool in disabled_tools.items():
            self.tool_registry.register(tool)

        return {
            "success": success,
            "summary": summary,
            "result": result,
            "metadata": {
                "steps": steps,
                "tools_used": tools_used,
                "duration_seconds": duration,
                "requested_tools": tool_filter or list(disabled_tools.keys()) or self.tool_registry.list_names(),
            },
        }

    def _make_subagent_summary(
        self, task: str, result: str, steps: int,
        tools_used: List[str], duration: float,
    ) -> str:
        """生成子代理执行摘要（轻量，不调用 LLM）"""
        preview = result[:300]
        if len(result) > 300:
            preview += "..."
        parts = [
            f"任务: {task}",
            f"结果: {preview}",
            f"步数: {steps}, 耗时: {duration}s",
        ]
        if tools_used:
            parts.append(f"使用工具: {', '.join(tools_used)}")
        return "\n".join(parts)

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}(model={self.llm.model}, "
                f"tools={len(self.tool_registry)}, tokens={self._token_count})")
