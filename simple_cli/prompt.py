"""
动态系统提示组装器 — 五个维度注入

维度:
    1. 角色定义 (config.toml system_prompt)
    2. 运行环境 (平台 + 工作目录 + 模型 + Python 版本)
    3. 可用工具 (ToolRegistry 中已启用的)
    4. 项目上下文 (CLAUDE.md 自动加载)
    5. 对话状态 (压缩次数 + token 使用)
"""

import os
import sys
from pathlib import Path
from typing import List, Optional


class PromptBuilder:
    """
    动态系统提示组装器。

    用法:
        builder = PromptBuilder(base_prompt=config.system_prompt)
        prompt = builder.build(agent)  # 每次 run() 前调用
    """

    def __init__(self, base_prompt: Optional[str] = None):
        self.base_prompt = base_prompt or "你是一个 AI 编程助手。"

    def build(self, agent) -> str:
        """组装完整系统提示"""
        sections = [self.base_prompt]

        # 1. 运行环境
        env = self._build_env_section(agent)
        if env:
            sections.append(env)

        # 2. 可用工具
        tools = self._build_tools_section(agent)
        if tools:
            sections.append(tools)

        # 3. 项目上下文
        project = self._build_project_section()
        if project:
            sections.append(project)

        # 4. 对话状态（如果已压缩过）
        status = self._build_status_section(agent)
        if status:
            sections.append(status)

        return "\n\n".join(sections)

    # ---- 各段组装 ----

    def _build_env_section(self, agent) -> str:
        lines = ["## 运行环境"]
        lines.append(f"- 操作系统: {sys.platform}")
        try:
            lines.append(f"- 当前目录: {Path.cwd()}")
        except Exception:
            pass
        lines.append(f"- 当前模型: {agent.llm.model}")
        lines.append(f"- Agent 类型: {agent.__class__.__name__}")
        lines.append(f"- Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        return "\n".join(lines)

    def _build_tools_section(self, agent) -> str:
        if not agent.tool_registry or len(agent.tool_registry) == 0:
            return ""

        lines = ["## 可用工具"]
        for name in agent.tool_registry.list_names():
            tool = agent.tool_registry.get(name)
            if tool:
                params = ", ".join(
                    f"{p.name}:{p.type}" for p in tool.get_parameters()
                )
                lines.append(f"- `{name}({params})` — {tool.description}")
        return "\n".join(lines)

    def _build_project_section(self) -> str:
        """自动读取项目根目录的 CLAUDE.md"""
        candidates = [
            Path.cwd() / "CLAUDE.md",
            Path.cwd() / "README.md",
        ]

        for p in candidates:
            if p.is_file():
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    # 取前 2000 字符作为项目上下文
                    preview = content[:2000]
                    if len(content) > 2000:
                        preview += "\n... (已截断)"
                    return f"## 项目上下文（来自 {p.name}）\n{preview}"
                except Exception:
                    pass
        return ""

    def _build_status_section(self, agent) -> str:
        """当前对话的压缩和 token 状态"""
        parts = []
        if getattr(agent, '_compression_count', 0) > 0:
            parts.append(f"- 历史已压缩 {agent._compression_count} 次")
        if hasattr(agent, 'token_usage'):
            usage = agent.token_usage()
            parts.append(
                f"- Token 使用: {usage['current_tokens']}/{usage['threshold']} "
                f"({usage['percent']}%)"
            )
        if not parts:
            return ""
        return "## 对话状态\n" + "\n".join(parts)
