"""
多会话持久化 — 支持多个独立会话，按名存取

目录结构:
    .simple_cli/sessions/
    ├── 2026-05-16-183800.json     ← 自动命名（时间戳）
    ├── 2026-05-16-191500.json
    └── my-debug-session.json      ← 用户自定义命名

原理:
    每个会话一个 JSON 文件，存储完整的对话历史 + 元数据。
    /resume 列出所有会话 → 用户选择 → 从 JSON 反序列化恢复历史
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from .agent.base import Message


class SessionStore:
    """多会话持久化管理器"""

    def __init__(self, sessions_dir: Optional[Path] = None):
        self.sessions_dir = sessions_dir or Path.cwd() / ".simple_cli" / "sessions"

    # ===== 保存 =====

    def save(
        self,
        name: str,
        history: List[Message],
        provider: str = "",
        agent_type: str = "",
    ) -> Path:
        """
        保存会话到指定名称的文件。

        Args:
            name: 会话名称（不含 .json 后缀），如 "2026-05-16-183800" 或 "my-session"
            history: 消息列表
            provider: LLM 提供商
            agent_type: Agent 类型

        Returns:
            保存的文件路径
        """
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now().isoformat()

        # 尝试从已有文件保留 created_at
        created_at = now
        existing = self._read_file(name)
        if existing:
            created_at = existing.get("created_at", now)

        data: Dict[str, Any] = {
            "name": name,
            "created_at": created_at,
            "updated_at": now,
            "provider": provider,
            "agent_type": agent_type,
            "message_count": len(history),
            "history": [
                {"role": msg.role, "content": msg.content}
                for msg in history
            ],
        }

        filepath = self.sessions_dir / f"{name}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return filepath

    def auto_save(
        self,
        history: List[Message],
        provider: str = "",
        agent_type: str = "",
    ) -> Path:
        """
        自动保存（用当前时间戳作为会话名）。

        Returns:
            保存的文件路径
        """
        name = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        return self.save(name, history, provider, agent_type)

    # ===== 加载 =====

    def load(self, name: str) -> Optional[Dict[str, Any]]:
        """
        按名加载会话。

        Args:
            name: 会话名称（不含 .json）

        Returns:
            dict 或 None
        """
        return self._read_file(name)

    def restore_history(self, name: str) -> List[Message]:
        """
        按名恢复历史消息。

        Args:
            name: 会话名称

        Returns:
            List[Message]
        """
        data = self._read_file(name)
        if not data:
            return []

        return [
            Message(content=item["content"], role=item["role"])
            for item in data.get("history", [])
        ]

    # ===== 列表 =====

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        列出所有已保存的会话，按更新时间倒序。

        Returns:
            [{"name": "...", "updated_at": "...", "message_count": 4, "provider": "deepseek", "agent_type": "fc"}, ...]
        """
        if not self.sessions_dir.is_dir():
            return []

        sessions = []
        for f in sorted(self.sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            data = self._read_file(f.stem)
            if data:
                sessions.append({
                    "name": data.get("name", f.stem),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "message_count": data.get("message_count", 0),
                    "provider": data.get("provider", ""),
                    "agent_type": data.get("agent_type", ""),
                    # 提取首条用户消息作为预览
                    "preview": self._extract_preview(data),
                })
        return sessions

    def _extract_preview(self, data: Dict[str, Any]) -> str:
        """提取会话预览（第一条用户消息的前 60 字符）"""
        history = data.get("history", [])
        for msg in history:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if len(content) > 60:
                    return content[:60] + "..."
                return content
        return "(空会话)"

    # ===== 删除 =====

    def delete(self, name: str) -> bool:
        """删除指定会话"""
        filepath = self.sessions_dir / f"{name}.json"
        if filepath.is_file():
            filepath.unlink()
            return True
        return False

    def delete_all(self) -> int:
        """删除所有会话，返回删除数量"""
        count = 0
        if self.sessions_dir.is_dir():
            for f in self.sessions_dir.glob("*.json"):
                f.unlink()
                count += 1
        return count

    # ===== 查询 =====

    def exists(self, name: str) -> bool:
        """指定会话是否存在"""
        return (self.sessions_dir / f"{name}.json").is_file()

    def has_any(self) -> bool:
        """是否有任何已保存的会话"""
        if not self.sessions_dir.is_dir():
            return False
        return any(self.sessions_dir.glob("*.json"))

    # ===== 内部 =====

    def _read_file(self, name: str) -> Optional[Dict[str, Any]]:
        """读取单个会话文件"""
        filepath = self.sessions_dir / f"{name}.json"
        if not filepath.is_file():
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
