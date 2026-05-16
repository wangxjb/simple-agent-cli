"""写文件工具"""

import os
from typing import Any, Dict, List
from ..base import Tool, ToolParameter


class WriteFileTool(Tool):
    def __init__(self):
        super().__init__(
            name="write_file",
            description="创建或覆盖文件。会自动创建父目录，返回写入的字符数。"
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter("path", "string", "要写入的文件路径", required=True),
            ToolParameter("content", "string", "要写入文件的完整内容", required=True),
        ]

    def run(self, params: Dict[str, Any]) -> str:
        path = params["path"]
        content = params["content"]

        try:
            # 自动创建父目录
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            return f"成功写入 {len(content)} 个字符到文件: {path}"

        except PermissionError:
            return f"错误: 没有权限写入文件 — {path}"
        except IsADirectoryError:
            return f"错误: 路径是目录不是文件 — {path}"
        except Exception as e:
            return f"错误: 写入文件时发生异常 — {e}"
