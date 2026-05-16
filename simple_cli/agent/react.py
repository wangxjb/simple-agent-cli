"""
ReAct Agent — Reasoning + Acting

核心思想: 用 Prompt 模板引导 LLM 输出 Thought/Action 文本，正则解析后执行工具。
任何支持对话的大模型都能用，不依赖 Function Calling 能力。

每一轮的输出格式:
    Thought: <推理过程>
    Action: tool_name[参数] | Finish[最终答案]
"""
import re
from typing import Optional
from .base import Agent
from ..llm import HelloAgentsLLM
from ..tools import ToolRegistry

# ReAct Agent 的灵魂 —— Prompt 模板
REACT_PROMPT = """你是一个能够使用工具的智能助手。

## 可用工具
{tools}

## 回复格式（必须严格遵守）
Thought: 分析问题并规划下一步行动
Action: 以下格式之一：
- tool_name[参数] — 调用工具
- Finish[最终答案] — 任务完成

## 开始
Question: {question}
{history}"""


class ReActAgent(Agent):
    """
    ReAct Agent — 纯文本解析驱动。

    特点:
    - 所有 LLM 都支持（即使不支持 Function Calling）
    - 推理过程（Thought）完全可见
    - Prompt 模板占一定 token，但调试友好
    """

    def run(self, question: str) -> str:
        self.add_to_history(question, "user")
        step = 0

        while step < self.max_steps:
            step += 1
            print(f"\n--- Step {step} ---", flush=True)

            # 1. 构建 Prompt
            tools_desc = self._build_tool_descriptions()
            history_str = self.get_history_text()
            prompt = REACT_PROMPT.format(
                tools=tools_desc,
                question=question,
                history=history_str,
            )

            # 2. 调用 LLM（流式）
            messages = [{"role": "user", "content": prompt}]
            print(f"  [LLM 思考中...]", end="", flush=True)

            response_text = ""
            for chunk in self.llm.stream(messages):
                if response_text == "":
                    print("")  # 换行
                print(chunk, end="", flush=True)
                response_text += chunk

            if not response_text.strip():
                return "错误: LLM 未返回有效响应"

            # 3. 解析 Thought 和 Action
            thought, action = self._parse_output(response_text)

            if thought:
                self.add_to_history(f"Thought: {thought}", "assistant")

            if not action:
                self.add_to_history(f"Action 解析失败，请检查格式", "system")
                continue

            # 4. 判断终止条件
            if action.startswith("Finish"):
                final_answer = self._extract_action_content(action)
                self.add_to_history(final_answer, "assistant")
                return final_answer

            # 5. 解析并执行工具
            tool_name, tool_input = self._parse_action(action)

            if not tool_name:
                self.add_to_history(
                    f"Observation: 无效的 Action 格式，应为 tool_name[参数]",
                    "system"
                )
                continue

            # 将字符串参数映射到工具的第一个必填参数
            params = self._build_tool_params(tool_name, tool_input)
            result = self._execute_tool(tool_name, params)

            # 6. 观察 → 追加历史 → 继续循环
            self.add_to_history(f"Action: {action}", "assistant")
            self.add_to_history(f"Observation: {result}", "system")

        return "已达到最大步数限制，任务未完成。"

    # ===== 解析方法 =====

    def _parse_output(self, text: str) -> tuple:
        """从 LLM 输出中提取 Thought 和 Action"""
        # Thought: 匹配到 Action: 或文本末尾
        thought_match = re.search(
            r"Thought:\s*(.*?)(?=\nAction:|$)", text, re.DOTALL
        )
        # Action: 匹配到文本末尾
        action_match = re.search(r"Action:\s*(.*)", text, re.DOTALL)

        thought = thought_match.group(1).strip() if thought_match else None
        action = action_match.group(1).strip() if action_match else None
        return thought, action

    def _parse_action(self, action_text: str) -> tuple:
        """从 Action 文本中提取工具名和参数"""
        match = re.match(r"(\w+)\[(.*)\]", action_text, re.DOTALL)
        if not match:
            return None, None
        return match.group(1), match.group(2)

    def _extract_action_content(self, action_text: str) -> str:
        """从 Finish[xxx] 中提取最终答案"""
        match = re.match(r"\w+\[(.*)\]", action_text, re.DOTALL)
        return match.group(1) if match else action_text

    def _build_tool_params(self, tool_name: str, tool_input: str) -> dict:
        """
        将 ReAct 的字符串输入映射到工具的实际参数。

        ReAct 模型输出的是纯文本: read_file[README.md]
        工具期望的是字典: {"path": "README.md"}

        这里做智能映射：
        1. 如果 input 是 key:value 格式 → 解析为字典
        2. 否则 → 映射到工具的第一个必填参数
        """
        tool = self.tool_registry.get(tool_name)
        if not tool:
            return {}

        params = tool.get_parameters()

        # 尝试解析 key:value 格式 (如: path: ".", recursive: false)
        if ":" in tool_input and len(params) > 0:
            return self._parse_kv_input(tool_input, params)

        # 单值 → 映射到第一个必填参数
        for p in params:
            if p.required:
                return {p.name: tool_input.strip()}

        # 没有必填参数 → 第一个参数
        if params:
            return {params[0].name: tool_input.strip()}

        return {}

    def _parse_kv_input(self, text: str, parameters: list) -> dict:
        """解析 key: value, key2: value2 格式的输入"""
        result = {}
        # 按逗号或分号拆分，同时注意不要拆分引号内的内容
        parts = re.split(r',\s*(?=(?:[^"]*"[^"]*")*[^"]*$)', text)
        for part in parts:
            kv = part.split(":", 1)
            if len(kv) == 2:
                key = kv[0].strip()
                val = kv[1].strip().strip('"').strip("'")
                result[key] = val
        if not result:
            # 解析失败 → 回退到单值映射
            return {}
        return result
