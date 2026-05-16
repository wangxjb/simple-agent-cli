"""网页搜索工具 (DuckDuckGo — 零 API Key)"""

import urllib.request
import urllib.parse
import re
from typing import Any, Dict, List
from ..base import Tool, ToolParameter


class WebSearchTool(Tool):
    def __init__(self):
        super().__init__(
            name="web_search",
            description="搜索网页获取信息。当需要最新信息或你不知道的内容时使用。返回前 5 条结果。"
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter("query", "string", "搜索关键词", required=True),
        ]

    def run(self, params: Dict[str, Any]) -> str:
        query = params["query"]

        try:
            results = self._search_duckduckgo(query)

            if not results:
                return f"未找到与 '{query}' 相关的结果。"

            lines = [f"搜索: {query}", "=" * 50]
            for i, (title, snippet, url) in enumerate(results, 1):
                lines.append(f"\n[{i}] {title}")
                lines.append(f"    {snippet}")
                lines.append(f"    URL: {url}")

            return "\n".join(lines)

        except Exception as e:
            return f"搜索失败: {e}"

    def _search_duckduckgo(self, query: str, max_results: int = 5) -> List[tuple]:
        """
        使用 DuckDuckGo HTML 搜索。

        为什么不用 Google/Bing API？
        —— 不需要 API Key，零配置，适合学习和离线环境。

        原理: WWW 请求 → 解析 HTML → 提取结果
        """
        url = "https://html.duckduckgo.com/html/?"
        encoded = urllib.parse.urlencode({"q": query})
        full_url = url + encoded

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        req = urllib.request.Request(full_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        return self._parse_results(html, max_results)

    def _parse_results(self, html: str, max_results: int) -> List[tuple]:
        """从 DuckDuckGo HTML 提取搜索结果"""
        results = []

        # 匹配每条结果的标题、摘要和链接
        # DuckDuckGo HTML 结果结构: <a class="result__a">标题</a> ... <a class="result__snippet">摘要</a> ... <a class="result__url">URL</a>
        snippet_pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*>(.*?)</a>'
            r'.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>'
            r'.*?'
            r'<a[^>]*class="result__url"[^>]*>(.*?)</a>',
            re.DOTALL
        )

        for match in snippet_pattern.finditer(html):
            title = self._clean_html(match.group(1))
            snippet = self._clean_html(match.group(2))
            url = match.group(3).strip()

            if title and snippet:
                results.append((title, snippet, url))
                if len(results) >= max_results:
                    break

        return results

    @staticmethod
    def _clean_html(text: str) -> str:
        """去掉 HTML 标签和多余空白"""
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
