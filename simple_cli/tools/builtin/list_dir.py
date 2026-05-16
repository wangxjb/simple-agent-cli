"""列目录工具"""

import os
from typing import Any, Dict, List
from ..base import Tool, ToolParameter


class ListDirTool(Tool):
    def __init__(self, max_depth: int = 2):
        super().__init__(
            name="list_directory",
            description="列出目录中的文件和子目录。支持递归展示（最大深度 2 层）。"
        )
        self.max_depth = max_depth

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter("path", "string", "要列出内容的目录路径，默认当前目录 '.'", required=False, default="."),
            ToolParameter("recursive", "boolean", "是否递归显示子目录，默认 false", required=False, default=False),
        ]

    def run(self, params: Dict[str, Any]) -> str:
        path = params.get("path", ".")
        recursive = params.get("recursive", False)

        if isinstance(recursive, str):
            recursive = recursive.lower() in ("true", "1", "yes")

        if not os.path.exists(path):
            return f"错误: 目录不存在 — {path}"
        if not os.path.isdir(path):
            return f"错误: 路径不是目录 — {path}"

        try:
            lines: List[str] = []
            self._walk(path, lines, depth=0, recursive=recursive)

            return f"目录: {path}\n{'-' * 40}\n" + "\n".join(lines)

        except PermissionError:
            return f"错误: 没有权限读取目录 — {path}"
        except Exception as e:
            return f"错误: 列目录时发生异常 — {e}"

    def _walk(self, path: str, lines: List[str], depth: int, recursive: bool):
        if depth > self.max_depth:
            return

        try:
            entries = sorted(os.listdir(path))
        except PermissionError:
            lines.append(f"{'  ' * depth}[无权限]")
            return

        for entry in entries:
            full = os.path.join(path, entry)
            prefix = "  " * depth + ("  📁 " if os.path.isdir(full) else "  📄 ")
            lines.append(f"{prefix}{entry}")

            if recursive and os.path.isdir(full) and depth < self.max_depth:
                self._walk(full, lines, depth + 1, recursive)
