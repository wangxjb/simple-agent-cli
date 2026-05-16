"""读文件工具"""

import os
from typing import Any, Dict, List
from ..base import Tool, ToolParameter


class ReadFileTool(Tool):
    def __init__(self):
        super().__init__(
            name="read_file",
            description="读取指定路径的文件内容。支持分页读取（offset + limit）。"
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter("path", "string", "要读取的文件路径（相对于当前工作目录或绝对路径）", required=True),
            ToolParameter("offset", "integer", "从第几行开始读，默认 0（第一行）", required=False, default=0),
            ToolParameter("limit", "integer", "最多读多少行，默认 200 行", required=False, default=200),
        ]

    def run(self, params: Dict[str, Any]) -> str:
        path = params["path"]
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", 200))

        if not os.path.exists(path):
            return f"错误: 文件不存在 — {path}"

        if not os.path.isfile(path):
            return f"错误: 路径不是文件 — {path}"

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)
            selected = lines[offset:offset + limit]

            header = f"文件: {path} (共 {total_lines} 行, 显示第 {offset + 1}-{min(offset + limit, total_lines)} 行)"
            content = "".join(selected).rstrip("\n")

            return f"{header}\n{'=' * 50}\n{content}"

        except PermissionError:
            return f"错误: 没有权限读取文件 — {path}"
        except Exception as e:
            return f"错误: 读取文件时发生异常 — {e}"
