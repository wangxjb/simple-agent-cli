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

        # 构建消息列表（使用基类的上下文管理）
        messages: List[Dict[str, Any]] = self._build_base_messages()

        # 如果没有自定义 system_prompt，用内置默认
        if not self.system_prompt and not any(
            m.get("role") == "system" for m in messages
        ):
            messages.insert(0, {"role": "system", "content": FC_SYSTEM_PROMPT})

        # 工具 Schema
        tool_schemas = self._build_tool_schemas()
        step = 0

        # 循环检测状态
        last_content = ""
        repeat_count = 0        # 连续相同内容的次数
        no_tool_count = 0       # 连续无工具调用的次数

        max_steps = self.max_steps if self.max_steps > 0 else float('inf')
        while step < max_steps:
            step += 1
            print(f"\n--- Step {step} ---")

            # 1. 调用 LLM（带 tools）
            print(f"  [LLM 思考中...]", end="", flush=True)
            progress_state = {"next_chars": 2048, "printed": False}

            def _show_stream_progress(event: str, chars: int) -> None:
                if chars >= progress_state["next_chars"]:
                    print(".", end="", flush=True)
                    progress_state["printed"] = True
                    progress_state["next_chars"] += 2048

            try:
                response = self.llm.invoke_with_tools(
                    messages=messages,
                    tools=tool_schemas,
                    stream=True,
                    on_progress=_show_stream_progress,
                )
            except Exception as e:
                return f"错误: LLM 调用失败 — {e}"
            if progress_state["printed"]:
                print("", flush=True)

            # 2. 检查是否有 tool_calls
            tool_calls = response.get("tool_calls", [])

            if not tool_calls:
                # 没有工具调用 → 检查是否为最终回复或死循环
                content = response.get("content") or ""

                if content.strip():
                    self.add_to_history(content, "assistant")
                    return content

                # 循环检测: 连续3次相同内容 → 强制终止
                if content.strip() == last_content.strip():
                    repeat_count += 1
                    if repeat_count >= 3:
                        self.add_to_history(content, "assistant")
                        return content
                else:
                    repeat_count = 0
                    last_content = content

                no_tool_count += 1
                # 连续2次无工具调用 → 应该是最终回复了
                if no_tool_count >= 2:
                    self.add_to_history(content, "assistant")
                    return content

                # 将当前回复追加到消息列表，让模型有机会追加
                messages.append({"role": "assistant", "content": content})
                continue

            # 有工具调用 → 重置循环检测
            repeat_count = 0
            no_tool_count = 0

            # 3. 记录助手消息（含 tool_calls）
            assistant_msg = {"role": "assistant", "content": response.get("content") or ""}
            reasoning_content = response.get("reasoning_content")
            if reasoning_content:
                assistant_msg["reasoning_content"] = reasoning_content
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

                # tool 消息不进入持久化历史
                # （它们的 tool_call_id 与当次 LLM 调用绑定，跨轮无意义）

            # 6. 循环继续 → LLM 基于工具结果继续推理

        return "警告: 已达到最大步数限制，任务可能未完成。可以增加 config.toml 中 max_steps 的值（设为 0 则不限制）。"
