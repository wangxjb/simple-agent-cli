"""统一 LLM 客户端 — 兼容所有 OpenAI 接口协议的大模型"""

import os
from typing import Iterator, List, Dict, Optional, Any
from openai import OpenAI, AuthenticationError, APIStatusError, APITimeoutError


class LLMResponse:
    """非流式响应的结构化结果"""

    def __init__(self, content: str, usage: Dict[str, int], model: str):
        self.content = content
        self.usage = usage        # { "prompt_tokens": n, "completion_tokens": n, "total_tokens": n }
        self.model = model

    def __repr__(self) -> str:
        return f"LLMResponse(model={self.model}, len={len(self.content)}, usage={self.usage})"


class HelloAgentsLLM:
    """
    统一 LLM 客户端。

    —— 切换 base_url 即可切换模型提供商，无需修改其他代码。

    用法:
        llm = HelloAgentsLLM(
            base_url="https://api.deepseek.com",
            api_key="sk-xxx",
            model="deepseek-chat"
        )
        for chunk in llm.stream(messages): ...
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        timeout: int = 120,
    ):
        if not all([base_url, api_key, model]):
            raise ValueError("base_url、api_key、model 三者必须全部提供")

        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

    # ==================== 非流式调用 ====================

    def invoke(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """
        非流式调用 LLM，返回完整结果。

        Args:
            messages: [{"role": "user", "content": "..."}, ...]
            **kwargs: 可覆盖 temperature, max_tokens

        Returns:
            LLMResponse(content, usage, model)
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                stream=False,
            )
            choice = response.choices[0]
            content = choice.message.content or ""

            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            return LLMResponse(content=content, usage=usage, model=self.model)

        except AuthenticationError:
            raise RuntimeError(
                f"API Key 认证失败，请检查 {self.base_url} 的密钥是否正确"
            )
        except APITimeoutError:
            raise RuntimeError(f"请求超时，请检查网络连接或 {self.base_url} 服务状态")

    # ==================== 流式调用 ====================

    def stream(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[str]:
        """
        流式调用 LLM，逐个 token 返回。

        Args:
            messages: [{"role": "user", "content": "..."}, ...]
            **kwargs: 可覆盖 temperature, max_tokens

        Yields:
            str: 每个文本片段

        —— 调用结束后，可通过 self.last_usage 获取 token 统计。
        """
        self.last_usage: Dict[str, int] = {}
        collected: List[str] = []

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                stream=True,
            )

            for chunk in response:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                content = delta.content or ""

                if content:
                    collected.append(content)
                    yield content

                # 最后一个 chunk 可能带 usage
                if hasattr(chunk, "usage") and chunk.usage:
                    self.last_usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens or 0,
                        "completion_tokens": chunk.usage.completion_tokens or 0,
                        "total_tokens": chunk.usage.total_tokens or 0,
                    }

            # 如果没有通过 chunk.usage 拿到统计，估算一个
            if not self.last_usage:
                self.last_usage = {
                    "prompt_tokens": 0,
                    "completion_tokens": len("".join(collected)) // 2,
                    "total_tokens": len("".join(collected)) // 2,
                }

        except AuthenticationError:
            raise RuntimeError(
                "API Key 认证失败，请检查环境变量或配置文件中的密钥"
            )
        except APITimeoutError:
            raise RuntimeError("请求超时，请检查网络连接")
        except APIStatusError as e:
            raise RuntimeError(f"API 返回错误 (HTTP {e.status_code}): {e.message}")

    # ==================== Function Calling ====================

    def invoke_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        **kwargs,
    ) -> Dict[str, Any]:
        """
        调用 LLM 并请求 Function Calling 响应。

        Args:
            messages: 消息列表
            tools: OpenAI 格式的 tool schemas
            **kwargs: 可覆盖 temperature, max_tokens

        Returns:
            {
                "content": str | None,        # 文本回复（可能为空）
                "tool_calls": [               # 工具调用列表（可能为空）
                    {
                        "id": str,
                        "name": str,
                        "arguments": dict
                    }
                ],
                "usage": { prompt_tokens, completion_tokens, total_tokens }
            }
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                stream=False,
            )

            choice = response.choices[0]
            msg = choice.message

            tool_calls = []
            if msg.tool_calls:
                import json
                for tc in msg.tool_calls:
                    try:
                        arguments = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": arguments,
                    })

            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            return {
                "content": msg.content,
                "tool_calls": tool_calls,
                "usage": usage,
            }

        except AuthenticationError:
            raise RuntimeError(
                "API Key 认证失败，请检查环境变量或配置文件中的密钥"
            )

    def __repr__(self) -> str:
        return f"HelloAgentsLLM(model={self.model}, base_url={self.base_url})"
