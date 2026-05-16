"""Agent 基类 — ReActAgent 和 FCAgent 的共享基础设施"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from ..llm import HelloAgentsLLM
from ..tools import ToolRegistry


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
    - 步数限制：避免无限循环
    """

    def __init__(
        self,
        llm: HelloAgentsLLM,
        tool_registry: Optional[ToolRegistry] = None,
        system_prompt: Optional[str] = None,
        max_steps: int = 5,
    ):
        self.llm = llm
        self.tool_registry = tool_registry or ToolRegistry()
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.history: List[Message] = []

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
        """添加一条消息到历史"""
        self.history.append(Message(content, role))

    def clear_history(self):
        """清空历史"""
        self.history.clear()

    def get_history_text(self) -> str:
        """格式化为纯文本历史（ReAct 用）"""
        return "\n".join(
            f"[{msg.role}]: {msg.content}" for msg in self.history
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.llm.model}, tools={len(self.tool_registry)})"
