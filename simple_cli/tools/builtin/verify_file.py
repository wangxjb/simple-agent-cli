"""文件验证工具 — 检查文件基本正确性"""

import os
import re
from typing import Any, Dict, List
from ..base import Tool, ToolParameter


class VerifyFileTool(Tool):
    def __init__(self):
        super().__init__(
            name="verify_file",
            description="验证文件正确性。对 .py 做语法检查，对 .html 做结构检查，对 .js 做 node 检查。应在创建/修改文件后立即调用。"
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter("path", "string", "要验证的文件路径", required=True),
        ]

    def run(self, params: Dict[str, Any]) -> str:
        path = params["path"]

        if not os.path.exists(path):
            return f"验证失败: 文件不存在 — {path}"

        if not os.path.isfile(path):
            return f"验证失败: 路径不是文件 — {path}"

        size = os.path.getsize(path)
        if size == 0:
            return f"验证失败: 文件为空 — {path}"

        # 根据扩展名选择验证策略
        ext = os.path.splitext(path)[1].lower()

        if ext == ".py":
            return self._verify_python(path, size)
        elif ext in (".html", ".htm"):
            return self._verify_html(path, size)
        elif ext == ".js":
            return self._verify_javascript(path, size)
        else:
            # 通用检查：存在 + 非空 + 大小
            return f"验证通过 ({ext} 文件, {size} 字节, 无特定检查器)"

    def _verify_python(self, path: str, size: int) -> str:
        """用 compile 做 Python 语法检查"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
            compile(source, path, "exec")
            return f"验证通过: Python 语法正确 ({path}, {size} 字节)"
        except SyntaxError as e:
            return f"验证失败: Python 语法错误 — {e}"

    def _verify_html(self, path: str, size: int) -> str:
        """检查 HTML 文件的基本结构"""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return f"验证失败: 无法读取文件 — {e}"

        issues = []

        # 检查基本标签
        if not re.search(r"<!DOCTYPE\s+html", content, re.IGNORECASE):
            issues.append("缺少 <!DOCTYPE html> 声明")
        if "<html" not in content.lower():
            issues.append("缺少 <html> 标签")
        if "<head>" not in content.lower() and "</head>" not in content.lower():
            issues.append("缺少 <head> 标签")
        if "<body" not in content.lower():
            issues.append("缺少 <body> 标签")

        # 检查标签配对（简化版）
        for tag in ["html", "head", "body", "script", "style", "title"]:
            opens = len(re.findall(rf"<{tag}[>\s]", content, re.IGNORECASE))
            closes = len(re.findall(rf"</{tag}>", content, re.IGNORECASE))
            if opens > closes:
                issues.append(f"<{tag}> 未正确闭合 (开 {opens} 次, 闭 {closes} 次)")

        # 检查 JavaScript 常见错误
        js_errors = self._check_js_snippets(content)
        issues.extend(js_errors)

        if issues:
            return f"验证失败: HTML 结构问题 —\n" + "\n".join(f"  - {i}" for i in issues)
        return f"验证通过: HTML 结构正确 ({path}, {size} 字节)"

    def _check_js_snippets(self, content: str) -> List[str]:
        """检查 HTML 中内嵌 JavaScript 的常见错误"""
        issues = []
        # 提取 <script> 标签中的内容
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
        for i, script in enumerate(scripts):
            # 检查常见问题
            opens_brace = script.count("{")
            closes_brace = script.count("}")
            if opens_brace != closes_brace:
                issues.append(f"script #{i+1}: 花括号不匹配 ({{{opens_brace}}} vs {{{closes_brace}}})")

            opens_paren = script.count("(")
            closes_paren = script.count(")")
            if opens_paren != closes_paren:
                issues.append(f"script #{i+1}: 圆括号不匹配 (({opens_paren}) vs ){closes_paren})")
        return issues

    def _verify_javascript(self, path: str, size: int) -> str:
        """尝试用 node --check 验证 JS"""
        import subprocess
        import shutil

        node = shutil.which("node")
        if not node:
            return f"验证跳过: 未安装 Node.js ({path}, {size} 字节)"

        try:
            result = subprocess.run(
                [node, "--check", path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return f"验证通过: JavaScript 语法正确 ({path}, {size} 字节)"
            else:
                return f"验证失败: JavaScript 语法错误 —\n{result.stderr[:500]}"
        except subprocess.TimeoutExpired:
            return f"验证超时: {path}"
        except Exception as e:
            return f"验证失败: {e}"
