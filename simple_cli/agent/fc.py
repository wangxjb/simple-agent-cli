"""
Function Calling Agent — 利用模型原生 tool_calls 驱动

核心思想: 把工具列表作为 JSON Schema 传给 LLM，LLM 返回结构化的 tool_calls，
不需要文本解析，可靠性更高。但要求模型支持 Function Calling。

与 ReAct 的关键区别:
- ReAct: LLM 输出文本 → 正则匹配 Action → 执行
- FC:    LLM 输出 JSON tool_calls → 直接读字段 → 执行
"""
import json
from typing import List, Dict, Any
from .base import Agent, Message
from ..llm import HelloAgentsLLM
from ..tools import ToolRegistry

# Function Calling Agent 的系统提示
FC_SYSTEM_PROMPT = """你是一个能够使用工具的智能助手。

你有以下工作原则：
1. 仔细分析用户问题，确定需要哪些工具
2. 工具调用结果会以 tool 消息的形式返回给你
3. 基于工具结果给出准确、完整的回答
4. 如果工具返回错误，尝试其他方法或如实告知用户
5. 使用中文回复"""


class FCAgent(Agent):
    """
    Function Calling Agent — 结构化工具调用驱动。

    特点:
    - 需要模型支持 Function Calling
    - 工具调用是结构化的 JSON，极可靠
    - 支持一次调用多个工具（并行）
    - 推理过程不可见（模型内部完成）
    """

    def run(self, question: str) -> str:
        self.add_to_history(question, "user")

        # 构建消息列表
        messages: List[Dict[str, Any]] = []

        # 系统提示
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        else:
            messages.append({"role": "system", "content": FC_SYSTEM_PROMPT})

        # 历史消息
        for msg in self.history:
            messages.append(msg.to_dict())

        # 工具 Schema
        tool_schemas = self._build_tool_schemas()
        step = 0

        while step < self.max_steps:
            step += 1
            print(f"\n--- Step {step} ---")

            # 1. 调用 LLM（带 tools）
            print(f"  [LLM 思考中...]", end="", flush=True)
            try:
                response = self.llm.invoke_with_tools(
                    messages=messages,
                    tools=tool_schemas,
                )
            except Exception as e:
                return f"错误: LLM 调用失败 — {e}"

            # 2. 检查是否有 tool_calls
            tool_calls = response.get("tool_calls", [])

            if not tool_calls:
                # 没有工具调用 → 这是最终回复
                content = response.get("content") or ""
                self.add_to_history(content, "assistant")
                return content

            # 3. 记录助手消息（含 tool_calls）
            assistant_msg = {"role": "assistant", "content": response.get("content") or ""}
            if tool_calls:
                # OpenAI 需要 tool_calls 字段的格式
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                        },
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_msg)

            # 4. 执行每个工具调用
            for tc in tool_calls:
                tool_name = tc["name"]
                tool_call_id = tc["id"]
                arguments = tc.get("arguments", {})

                print(f"\n  [tool] {tool_name}({arguments})")
                result = self._execute_tool(tool_name, arguments)
                print(f"  [result] {result[:200]}")

                # 5. 工具结果回灌到消息
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result,
                })

                # 也记录到本地历史
                self.add_to_history(
                    f"Tool {tool_name}({arguments}) → {result}", "tool"
                )

            # 6. 循环继续 → LLM 基于工具结果继续推理

        return "已达到最大步数限制，任务未完成。"
