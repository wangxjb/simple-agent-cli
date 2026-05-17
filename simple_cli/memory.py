"""
记忆系统 — 跨会话持久化的用户/项目/反馈记忆

与 session.py 的区别:
    session.py = "上次聊了什么"（对话历史，当前目录）
    memory.py  = "你是谁 / 项目是什么 / 偏好是什么"（全局共享）

存储结构:
    ~/.simple_cli/memory/
    ├── MEMORY.md          # 索引（自动加载）
    ├── user_role.md       # 用户角色记忆
    └── project_xxx.md     # 项目记忆
"""

import re
from pathlib import Path
from typing import Dict, List, Optional


class MemoryStore:
    """跨会话记忆管理器"""

    def __init__(self, memory_dir: Optional[Path] = None):
        self.memory_dir = memory_dir or Path.home() / ".simple_cli" / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    # ===== 保存 =====

    def save(self, name: str, content: str, mem_type: str = "user", description: str = "") -> Path:
        """
        保存一条记忆。

        Args:
            name: 文件名（不含 .md）
            content: 记忆正文
            mem_type: user / feedback / project
            description: 一行描述（用于索引）
        """
        text = f"""---
name: {name}
description: {description or name}
type: {mem_type}
---

{content}
"""
        filepath = self.memory_dir / f"{name}.md"
        filepath.write_text(text, encoding="utf-8")
        self._rebuild_index()
        return filepath

    def delete(self, name: str) -> bool:
        """删除一条记忆"""
        filepath = self.memory_dir / f"{name}.md"
        if filepath.is_file():
            filepath.unlink()
            self._rebuild_index()
            return True
        return False

    # ===== 加载 =====

    def load_all(self) -> List[Dict[str, str]]:
        """
        加载所有记忆，返回列表。

        Returns:
            [{"name": "user_role", "type": "user", "content": "..."}, ...]
        """
        memories = []
        if not self.memory_dir.is_dir():
            return memories

        for f in sorted(self.memory_dir.glob("*.md")):
            if f.stem == "MEMORY":
                continue  # 跳过索引文件
            data = self._parse_file(f)
            if data:
                memories.append(data)
        return memories

    def load_for_prompt(self) -> str:
        """
        将所有记忆组装为系统提示中可注入的文本块。

        Returns:
            "## 用户记忆\n- 你是资深Python开发者...\n\n## 项目记忆\n..."
        """
        memories = self.load_all()
        if not memories:
            return ""

        grouped: Dict[str, List[str]] = {"user": [], "feedback": [], "project": []}
        type_names = {"user": "## 关于用户", "feedback": "## 行为偏好", "project": "## 项目上下文"}

        for m in memories:
            t = m.get("type", "user")
            grouped.setdefault(t, []).append(f"- {m['content']}")

        sections = []
        for t in ["user", "feedback", "project"]:
            if grouped.get(t):
                sections.append(type_names.get(t, f"## {t}"))
                sections.append("\n".join(grouped[t]))

        return "\n\n".join(sections) if sections else ""

    def list_all(self) -> List[Dict[str, str]]:
        """列出所有记忆的元数据"""
        return [
            {"name": m["name"], "type": m["type"], "preview": m["content"][:80]}
            for m in self.load_all()
        ]

    # ===== 内部 =====

    def _parse_file(self, filepath: Path) -> Optional[Dict[str, str]]:
        """解析记忆文件（YAML frontmatter + Markdown body）"""
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

        # 解析 frontmatter
        frontmatter: Dict[str, str] = {}
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().split("\n"):
                    line = line.strip()
                    if ":" in line:
                        k, v = line.split(":", 1)
                        frontmatter[k.strip()] = v.strip()
                body = parts[2].strip()
            else:
                body = text
        else:
            body = text

        name = frontmatter.get("name", filepath.stem)
        mem_type = frontmatter.get("type", "user")

        return {"name": name, "type": mem_type, "content": body}

    def _rebuild_index(self):
        """重建 MEMORY.md 索引"""
        memories = self.load_all()
        lines = ["# Memory Index\n"]

        for m in memories:
            name = m["name"]
            mem_type = m["type"]
            preview = m["content"][:100].replace("\n", " ")
            lines.append(f"- [{name}]({name}.md) [{mem_type}] — {preview}")

        index_path = self.memory_dir / "MEMORY.md"
        index_path.write_text("\n".join(lines), encoding="utf-8")
