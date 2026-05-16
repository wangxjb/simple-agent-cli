"""工具基类 + 注册表 — 可插拔工具系统的核心"""

from typing import Dict, Any, List, Optional, Callable
from abc import ABC, abstractmethod


class ToolParameter:
    """工具参数定义"""

    def __init__(self, name: str, type: str, description: str = "", required: bool = True, default: Any = None):
        self.name = name
        self.type = type          # string / integer / number / boolean
        self.description = description
        self.required = required
        self.default = default

    def __repr__(self) -> str:
        return f"ToolParameter({self.name}: {self.type}, required={self.required})"


class Tool(ABC):
    """
    工具基类。

    每个工具 = name + description + parameters + run()

    子类只需实现 run() 和 get_parameters()。
    """

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    @abstractmethod
    def get_parameters(self) -> List[ToolParameter]:
        """返回工具的参数定义列表"""
        ...

    @abstractmethod
    def run(self, params: Dict[str, Any]) -> str:
        """执行工具，返回字符串结果"""
        ...

    def to_openai_schema(self) -> Dict[str, Any]:
        """
        生成 OpenAI Function Calling 要求的 JSON Schema。

        这是工具系统与 LLM 之间的"握手协议"——
        模型通过这段 JSON Schema 知道：
        - 有哪些工具可用
        - 每个工具需要什么参数
        - 参数的类型和是否必需
        """
        params = self.get_parameters()
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for p in params:
            prop: Dict[str, Any] = {
                "type": p.type,
                "description": p.description,
            }
            if p.default is not None:
                prop["description"] = f"{p.description} (默认: {p.default})"
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def __repr__(self) -> str:
        return f"Tool({self.name})"


class ToolRegistry:
    """
    工具注册表 — 管理所有已注册的工具。

    核心职责：
    1. 注册工具（register）
    2. 按名查找（get）
    3. 生成所有工具的 JSON Schema 列表（to_openai_schemas）
    4. 执行指定工具（execute）

    用法:
        registry = ToolRegistry()
        registry.register(ReadFileTool())
        registry.register(WebSearchTool())

        schemas = registry.to_openai_schemas()  # 给 LLM
        result = registry.execute("read_file", {"path": "README.md"})
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具实例"""
        if tool.name in self._tools:
            print(f"警告: 工具 '{tool.name}' 被覆盖")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """移除一个工具"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> Optional[Tool]:
        """按名获取工具"""
        return self._tools.get(name)

    def list_names(self) -> List[str]:
        """列出所有已注册工具的名称"""
        return list(self._tools.keys())

    def to_openai_schemas(self) -> List[Dict[str, Any]]:
        """生成所有工具的 OpenAI JSON Schema 列表"""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def execute(self, name: str, params: Dict[str, Any]) -> str:
        """
        执行指定工具，返回字符串结果。

        参数验证 + 默认值填充 + 异常捕获。
        """
        tool = self.get(name)
        if not tool:
            return f"错误: 未找到工具 '{name}'。可用工具: {', '.join(self.list_names())}"

        try:
            # 填充默认值
            for p in tool.get_parameters():
                if p.name not in params and p.default is not None:
                    params[p.name] = p.default

            result = tool.run(params)
            return str(result)

        except Exception as e:
            return f"工具 '{name}' 执行失败: {e}"

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry({len(self._tools)} tools: {self.list_names()})"
