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

        # 循环检测
        last_action = ""
        parse_fail_count = 0   # 解析失败连续计数

        max_steps = self.max_steps if self.max_steps > 0 else float('inf')
        while step < max_steps:
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
                parse_fail_count += 1
                if parse_fail_count >= 5:
                    return f"循环检测: 连续 {parse_fail_count} 次 Action 解析失败，强制终止"
                # 不写入持久化历史（内部反馈，不污染上下文）
                print(f"  [提示] Action 解析失败，重试中...", flush=True)
                continue

            # 4. 判断终止条件
            if action.startswith("Finish"):
                final_answer = self._extract_action_content(action)
                self.add_to_history(final_answer, "assistant")
                return final_answer

            # 5. 循环检测
            if action and action == last_action:
                return f"循环检测: 连续执行相同操作，强制终止。结果: {self.history[-1].content if self.history else '无'}"
            last_action = action
            parse_fail_count = 0  # 有有效 Action 则重置

            # 6. 解析并执行工具
            tool_name, tool_input = self._parse_action(action)

            if not tool_name:
                print(f"  [提示] 无效的 Action 格式，重试中...", flush=True)
                continue

            # 将字符串参数映射到工具的第一个必填参数
            params = self._build_tool_params(tool_name, tool_input)
            result = self._execute_tool(tool_name, params)

            # 6. 观察 → 追加历史 → 继续循环
            self.add_to_history(f"Action: {action}", "assistant")
            self.add_to_history(f"Observation: {result}", "system")

        return "警告: 已达到最大步数限制，任务可能未完成。可以增加 config.toml 中 max_steps 的值。"

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

        # 尝试解析 key:value 或 key=value 格式
        if len(params) > 0:
            # 检测是否包含参数名引导的 KV 格式
            first_param = params[0].name
            if re.match(rf'{first_param}\s*[:=]', tool_input, re.IGNORECASE):
                return self._parse_kv_input(tool_input, params)

        # 单值 → 去掉可能的前缀 "name=" 或 "name:"，映射到第一个必填参数
        cleaned = re.sub(r'^\w+\s*[:=]\s*', '', tool_input.strip(), count=1)
        for p in params:
            if p.required:
                return {p.name: cleaned}

        # 没有必填参数 → 第一个参数
        if params:
            return {params[0].name: cleaned}

        return {}

    def _parse_kv_input(self, text: str, parameters: list) -> dict:
        """
        解析 key: value, key2: value2 格式的输入。

        对于多参数工具（如 write_file(path, content)），按参数名定位：
        找到每个参数名作为锚点，提取其值（到下一个参数名之前）。
        这对于 content 参数包含 HTML/代码等含逗号冒号的文本至关重要。
        """
        result = {}
        param_names = [p.name for p in parameters]

        # 策略: 按参数名定位
        # 如: "path: /tmp/x.html, content: <html>,</html>"
        # 或: "command=python -c \"...\""
        # → 支持 : 和 = 两种分隔符

        remaining = text
        for i, pname in enumerate(param_names):
            # 查找当前参数名后跟 : 或 = 的位置
            pattern = re.compile(rf'{pname}\s*[:=]\s*', re.IGNORECASE)
            match = pattern.search(remaining)
            if not match:
                continue

            # 值的起始位置（冒号之后）
            val_start = match.end()
            remaining_after_key = remaining[val_start:]

            # 找下一个参数名的位置（作为当前值的边界）
            if i + 1 < len(param_names):
                next_pattern = re.compile(
                    rf',?\s*{param_names[i + 1]}\s*[:=]\s*', re.IGNORECASE
                )
                next_match = next_pattern.search(remaining_after_key)
                if next_match:
                    val = remaining_after_key[:next_match.start()].strip()
                    val = self._strip_quotes(val)
                    result[pname] = val
                    remaining = remaining_after_key[next_match.start():]
                else:
                    val = remaining_after_key.strip()
                    val = self._strip_quotes(val)
                    result[pname] = val
                    break
            else:
                # 最后一个参数，取到末尾
                val = remaining_after_key.strip()
                val = self._strip_quotes(val)
                result[pname] = val

        if not result:
            return {}
        return result

    @staticmethod
    def _strip_quotes(val: str) -> str:
        """只在值整体被匹配引号包裹时才去掉引号"""
        if len(val) >= 2:
            if (val[0] == val[-1] and val[0] in ('"', "'")):
                return val[1:-1]
        return val
