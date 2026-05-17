"""
上下文工程 — Token 计数 + 历史压缩 + 滑动窗口

原理:
    1. 每次追加消息时增量计算 token
    2. token 超过阈值 → LLM 生成早期对话摘要
    3. 保留最近 N 轮完整，旧的替换为摘要

关键概念:
    - Token: 模型理解的最小语义单元（≈0.75个英文单词，≈0.4个中文字）
    - Context Window: 模型一次能处理的最大 token 数（DeepSeek: 64K）
    - 压缩阈值: context_window * 0.8，留余量给输出
"""

from typing import List, Optional

import tiktoken


class TokenCounter:
    """
    Token 计数器。

    使用 tiktoken 精确计算 token 数（而非字符数估算）。
    支持 openai/claude 等多种编码，默认 cl100k_base（GPT-4 / DeepSeek 通用）。
    """

    # 模型 → tiktoken encoding 映射
    ENCODING_MAP = {
        "gpt-4": "cl100k_base",
        "gpt-4o": "o200k_base",
        "gpt-3.5-turbo": "cl100k_base",
        "deepseek-chat": "cl100k_base",
        "deepseek-reasoner": "cl100k_base",
        "glm-4": "cl100k_base",
        "qwen": "cl100k_base",
        "default": "cl100k_base",
    }

    def __init__(self, model: str = "default"):
        encoding_name = self.ENCODING_MAP.get(model, self.ENCODING_MAP["default"])
        try:
            self.encoding = tiktoken.get_encoding(encoding_name)
        except Exception:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        self.model = model

    def count(self, text: str) -> int:
        """计算单段文本的 token 数"""
        if not text:
            return 0
        try:
            return len(self.encoding.encode(text))
        except Exception:
            return len(text) // 2  # 回退估算

    def count_message(self, content: str) -> int:
        """
        计算一条消息的 token 数。

        OpenAI 消息格式有约 4 token 的结构开销
        (role 标记 + 分隔符等)
        """
        return self.count(content) + 4

    def count_messages(self, messages: List[dict]) -> int:
        """计算消息列表的总 token 数"""
        total = 0
        for msg in messages:
            total += self.count_message(msg.get("content", ""))
        return total + 2  # 对话级别的结构开销


class HistoryCompressor:
    """
    历史压缩器。

    策略:
        1. 找到轮次边界（user-assistant 消息对）
        2. 保留最近 min_retain_rounds 轮完整
        3. 将更早的消息压缩为 LLM 生成的摘要
        4. 摘要以 system 消息形式注入 messages 列表前面
    """

    def __init__(
        self,
        llm,  # HelloAgentsLLM，用于生成摘要
        context_window: int = 65536,
        compression_threshold: float = 0.8,
        min_retain_rounds: int = 3,
        token_counter: Optional[TokenCounter] = None,
    ):
        self.llm = llm
        self.context_window = context_window
        self.threshold = int(context_window * compression_threshold)
        self.min_retain_rounds = min_retain_rounds
        self.token_counter = token_counter or TokenCounter()

    def should_compress(self, token_count: int) -> bool:
        """判断是否需要压缩"""
        return token_count > self.threshold

    def compress(self, messages: List[dict]) -> List[dict]:
        """
        压缩消息列表。

        Args:
            messages: 完整的消息列表 [system?, user, assistant, user, assistant, ...]

        Returns:
            压缩后的消息列表 [system?, summary_as_system, ...recent_rounds]
        """
        # 1. 找到轮次边界
        rounds = self._find_round_boundaries(messages)

        if len(rounds) <= self.min_retain_rounds:
            return messages  # 还不够多，不需要压缩

        # 2. 分离: 保留最近 N 轮，压缩前面的
        keep_from = rounds[-self.min_retain_rounds]
        to_compress = messages[:keep_from]
        to_keep = messages[keep_from:]

        # 3. 生成摘要
        summary = self._generate_summary(to_compress)

        # 4. 构建新消息列表
        result = []
        # 保留原始 system 消息（如果存在且在压缩部分）
        if to_compress and to_compress[0].get("role") == "system":
            result.append(to_compress[0])

        # 注入摘要（伪装为 system 消息不会触发 tool 角色要求）
        result.append({
            "role": "system",
            "content": f"[历史摘要] {summary}",
        })

        result.extend(to_keep)
        return result

    def _find_round_boundaries(self, messages: List[dict]) -> List[int]:
        """
        找到每轮对话的起始索引。

        一轮 = user 消息及其后续的所有非 user 消息（直到下一个 user）。

        Returns:
            [0, 2, 5, 8, ...]  每轮第一条消息的索引
        """
        boundaries = []
        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                boundaries.append(i)
        return boundaries

    def _generate_summary(self, messages: List[dict]) -> str:
        """
        用 LLM 生成结构化对话摘要（参考 Claude Code 的压缩格式）。

        保留五个维度的关键信息:
        1. 任务目标 — 用户想要完成什么
        2. 关键决策 — 做了哪些重要选择
        3. 已完成工作 — 完成了哪些任务（列表形式）
        4. 待处理事项 — 还有什么未完成
        5. 重要发现 — 有哪些关键信息或错误
        """
        if not messages:
            return "无历史"

        history_text = self._format_for_summary(messages)
        summary_prompt = f"""请将以下对话历史压缩为结构化摘要，保留关键信息：

## 对话历史
{history_text}

## 摘要要求（严格按此格式输出）
1. **任务目标**：用户想要完成什么？
2. **关键决策**：做了哪些重要决定？
3. **已完成工作**：完成了哪些任务？（列表形式）
4. **待处理事项**：还有什么未完成？
5. **重要发现**：有哪些关键信息或问题？

请用简洁的中文输出，每部分不超过 3 行。"""

        try:
            msgs = [
                {"role": "system", "content": "你是一个专业的对话摘要助手，擅长提取和结构化关键信息。输出简洁准确，不遗漏重要细节。"},
                {"role": "user", "content": summary_prompt},
            ]
            response = self.llm.invoke(msgs, temperature=0.0, max_tokens=400)
            result = response.content.strip()
            return f"## 历史摘要（{len(self._find_round_boundaries(messages))} 轮对话）\n{result}\n\n---\n（已压缩，保留最近 {self.min_retain_rounds} 轮完整对话）"
        except Exception:
            return self._simple_summary(messages)

    def _format_for_summary(self, messages: List[dict]) -> str:
        """格式化历史消息为摘要用的纯文本"""
        lines = []
        for msg in messages:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            # 截断过长消息
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"[{role}] {content}")
        return "\n\n".join(lines)

    def _simple_summary(self, messages: List[dict]) -> str:
        """简单摘要（LLM 失败时的回退）"""
        rounds = self._find_round_boundaries(messages)
        user_msgs = sum(1 for m in messages if m.get("role") == "user")
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")

        # 提取用户在首轮提出的问题（任务目标）
        first_question = ""
        for m in messages:
            if m.get("role") == "user":
                first_question = m.get("content", "")[:100]
                break

        return (
            f"## 历史摘要（{len(rounds)} 轮对话）\n"
            f"1. **任务目标**：{first_question}\n"
            f"2. **关键决策**：（智能摘要生成失败，未提取）\n"
            f"3. **已完成工作**：用户消息 {user_msgs} 条，助手回复 {assistant_msgs} 条\n"
            f"4. **待处理事项**：（未知）\n"
            f"5. **重要发现**：（未知）\n\n"
            f"---\n"
            f"（已压缩，保留最近 {self.min_retain_rounds} 轮完整对话）"
        )
