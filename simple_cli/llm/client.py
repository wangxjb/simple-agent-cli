"""统一 LLM 客户端 — 兼容所有 OpenAI 接口协议的大模型"""

import os
import time
import random
from typing import Iterator, List, Dict, Optional, Any
from openai import OpenAI, AuthenticationError, APIStatusError, APITimeoutError, RateLimitError


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

        self.max_retries = 3          # 最大重试次数
        self.base_wait = 1.0          # 基础等待时间 (秒)
        self.max_wait = 30.0          # 最大等待时间

    # ==================== 重试逻辑 ====================

    def _retry(self, func, *args, **kwargs):
        """
        带指数退避的重试包装器。

        可重试: RateLimitError(429), APIStatusError(5xx), APITimeoutError
        不可重试: AuthenticationError(401), 参数错误(400)
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except RateLimitError as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = min(self.base_wait * (2 ** attempt) * 5, self.max_wait)
                    wait += random.uniform(0, wait * 0.25)
                    print(f"  [速率限制, {wait:.0f}s 后重试...]", flush=True)
                    time.sleep(wait)
            except APIStatusError as e:
                if e.status_code >= 500:
                    last_error = e
                    if attempt < self.max_retries:
                        wait = min(self.base_wait * (2 ** attempt), self.max_wait)
                        wait += random.uniform(0, wait * 0.25)
                        print(f"  [服务端错误 {e.status_code}, {wait:.0f}s 后重试...]", flush=True)
                        time.sleep(wait)
                else:
                    raise  # 4xx 非 429 不重试
            except APITimeoutError as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = min(self.base_wait * (2 ** attempt), self.max_wait)
                    print(f"  [超时, {wait:.0f}s 后重试...]", flush=True)
                    time.sleep(wait)
            except AuthenticationError:
                raise  # 认证失败直接抛，不重试

        raise RuntimeError(
            f"重试 {self.max_retries} 次后仍然失败: {last_error}"
        )

    # ==================== 非流式调用 ====================

    def invoke(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """
        非流式调用 LLM，返回完整结果。
        自动重试 429/5xx/超时，不重试 401/400。
        """
        def _call():
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

        try:
            return self._retry(_call)
        except AuthenticationError:
            raise RuntimeError(
                f"API Key 认证失败，请检查 {self.base_url} 的密钥是否正确"
            )

    # ==================== 流式调用 ====================

    def stream(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[str]:
        """
        流式调用 LLM，逐个 token 返回。
        自动重试 429/5xx/超时。
        """
        self.last_usage: Dict[str, int] = {}
        collected: List[str] = []

        def _call_and_collect():
            nonlocal collected
            collected = []
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
                if hasattr(chunk, "usage") and chunk.usage:
                    self.last_usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens or 0,
                        "completion_tokens": chunk.usage.completion_tokens or 0,
                        "total_tokens": chunk.usage.total_tokens or 0,
                    }
            if not self.last_usage:
                self.last_usage = {
                    "prompt_tokens": 0,
                    "completion_tokens": len("".join(collected)) // 2,
                    "total_tokens": len("".join(collected)) // 2,
                }

        try:
            yield from self._retry(_call_and_collect)
        except AuthenticationError:
            raise RuntimeError("API Key 认证失败，请检查环境变量或配置文件中的密钥")

    # ==================== Function Calling ====================

    def invoke_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        **kwargs,
    ) -> Dict[str, Any]:
        """
        调用 LLM 并请求 Function Calling 响应。
        自动重试 429/5xx/超时。
        """
        import json

        def _build_request_kwargs(stream: bool) -> Dict[str, Any]:
            request_kwargs = {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                "stream": stream,
            }
            thinking = kwargs.get("thinking")
            is_deepseek_v4 = (
                "api.deepseek.com" in (self.base_url or "").lower()
                and self.model.startswith("deepseek-v4")
            )
            if thinking or is_deepseek_v4:
                request_kwargs["extra_body"] = {
                    "thinking": {"type": thinking or "disabled"}
                }
            return request_kwargs

        def _stream_call() -> Dict[str, Any]:
            on_progress = kwargs.get("on_progress")
            content_parts: List[str] = []
            reasoning_parts: List[str] = []
            tool_parts: Dict[int, Dict[str, str]] = {}
            usage = {}

            response = self.client.chat.completions.create(
                **_build_request_kwargs(stream=True),
            )
            for chunk in response:
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens or 0,
                        "completion_tokens": chunk.usage.completion_tokens or 0,
                        "total_tokens": chunk.usage.total_tokens or 0,
                    }
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                reasoning_delta = getattr(delta, "reasoning_content", None)
                if reasoning_delta:
                    reasoning_parts.append(reasoning_delta)
                    if on_progress:
                        on_progress("reasoning", len("".join(reasoning_parts)))

                content_delta = getattr(delta, "content", None)
                if content_delta:
                    content_parts.append(content_delta)
                    if on_progress:
                        on_progress("content", len("".join(content_parts)))

                for tc in getattr(delta, "tool_calls", None) or []:
                    index = getattr(tc, "index", 0) or 0
                    current = tool_parts.setdefault(
                        index,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    tool_id = getattr(tc, "id", None)
                    if tool_id:
                        current["id"] = tool_id
                    function = getattr(tc, "function", None)
                    if function:
                        name_delta = getattr(function, "name", None)
                        if name_delta:
                            current["name"] += name_delta
                        args_delta = getattr(function, "arguments", None)
                        if args_delta:
                            current["arguments"] += args_delta
                            if on_progress:
                                on_progress("tool_arguments", len(current["arguments"]))

            tool_calls = []
            for index in sorted(tool_parts):
                tc = tool_parts[index]
                try:
                    arguments = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    arguments = {}
                tool_calls.append({
                    "id": tc["id"],
                    "name": tc["name"],
                    "arguments": arguments,
                })

            return {
                "content": "".join(content_parts),
                "reasoning_content": "".join(reasoning_parts) or None,
                "tool_calls": tool_calls,
                "usage": usage,
            }

        def _call():
            if kwargs.get("stream"):
                return _stream_call()

            response = self.client.chat.completions.create(
                **_build_request_kwargs(stream=False),
            )
            choice = response.choices[0]
            msg = choice.message

            tool_calls = []
            if msg.tool_calls:
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
                "reasoning_content": getattr(msg, "reasoning_content", None),
                "tool_calls": tool_calls,
                "usage": usage,
            }

        try:
            return self._retry(_call)
        except AuthenticationError:
            raise RuntimeError(
                "API Key 认证失败，请检查环境变量或配置文件中的密钥"
            )

    def __repr__(self) -> str:
        return f"HelloAgentsLLM(model={self.model}, base_url={self.base_url})"
