"""执行 shell 命令工具"""

import subprocess
from typing import Any, Dict, List
from ..base import Tool, ToolParameter


class RunCommandTool(Tool):
    def __init__(self, timeout: int = 30, max_output_chars: int = 2000):
        super().__init__(
            name="run_command",
            description="执行 shell 命令并返回输出。适用于运行脚本、安装依赖、代码检查等。"
        )
        self.timeout = timeout
        self.max_output_chars = max_output_chars

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter("command", "string", "要执行的 shell 命令", required=True),
        ]

    def run(self, params: Dict[str, Any]) -> str:
        command = params["command"]

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                encoding="utf-8",
                errors="replace",
            )

            output = result.stdout or "(无输出)"
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"

            # 截断过长输出
            if len(output) > self.max_output_chars:
                output = output[:self.max_output_chars] + f"\n... (输出已截断，原始长度 {len(output)} 字符)"

            exit_info = f"退出码: {result.returncode}"
            return f"{exit_info}\n{output}"

        except subprocess.TimeoutExpired:
            return f"错误: 命令执行超时 ({self.timeout} 秒) — {command}"
        except Exception as e:
            return f"错误: 执行命令时发生异常 — {e}"
