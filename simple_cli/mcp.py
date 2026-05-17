"""
MCP (Model Context Protocol) 客户端 — JSON-RPC over stdio

核心原理:
    1. 通过子进程启动 MCP Server
    2. 通过 stdio 发送 JSON-RPC 请求
    3. 解析响应，提取工具列表和调用结果
    4. 将 MCP 工具桥接为 simple-cli 的 Tool 接口

协议:
    请求 {"jsonrpc":"2.0", "method":"tools/list", "id":1}
    响应 {"jsonrpc":"2.0", "result":{"tools":[...]}, "id":1}
"""

import json
import subprocess
import sys
from typing import Dict, Any, List, Optional


class MCPClient:
    """
    MCP 客户端 — 连接外部工具服务器。

    用法:
        client = MCPClient()
        client.connect("python my_mcp_server.py")
        tools = client.list_tools()
        result = client.call_tool("weather", {"city": "北京"})
    """

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0

    def connect(self, command: str) -> bool:
        """
        启动 MCP Server 子进程。

        Args:
            command: 启动命令，如 "python weather_server.py"

        Returns:
            是否连接成功
        """
        try:
            self._process = subprocess.Popen(
                command,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            # 发送 initialize 请求
            init_result = self._send("initialize", {
                "protocolVersion": "0.1.0",
                "clientInfo": {"name": "simple-cli"},
            })
            return init_result is not None
        except Exception as e:
            print(f"MCP 连接失败: {e}")
            return False

    def list_tools(self) -> List[Dict[str, Any]]:
        """获取 MCP Server 提供的工具列表"""
        result = self._send("tools/list")
        if result and "tools" in result:
            return result["tools"]
        return []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """
        调用 MCP 工具。

        Args:
            name: 工具名
            arguments: 参数字典

        Returns:
            工具执行结果文本
        """
        result = self._send("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if not result:
            return f"错误: MCP 工具 '{name}' 调用失败"

        # 提取文本内容
        content = result.get("content", [])
        if isinstance(content, list):
            return "\n".join(
                item.get("text", str(item))
                for item in content
                if isinstance(item, dict)
            )
        return str(content)

    def close(self):
        """关闭 MCP Server 连接"""
        if self._process:
            try:
                self._process.stdin.close()
                self._process.stdout.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            self._process = None

    def _send(self, method: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """发送 JSON-RPC 请求并读取响应"""
        if not self._process or self._process.stdin is None:
            return None

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._request_id,
        }

        try:
            payload = json.dumps(request, ensure_ascii=False)
            self._process.stdin.write(payload + "\n")
            self._process.stdin.flush()

            # 读取一行响应
            line = self._process.stdout.readline()
            if not line:
                return None

            response = json.loads(line)
            if "error" in response:
                err = response["error"]
                print(f"MCP Error [{method}]: {err.get('message', err)}", file=sys.stderr)
                return None
            return response.get("result")
        except Exception as e:
            print(f"MCP 通信失败 [{method}]: {e}", file=sys.stderr)
            return None


class MCPToolBridge:
    """
    将 MCP Server 的工具桥接为 simple-cli Tool 接口。

    效果: Agent 不区分工具是内置的还是 MCP 的。
    """

    def __init__(self, client: MCPClient, tool_def: Dict[str, Any]):
        self.client = client
        self._def = tool_def

    @property
    def name(self) -> str:
        return self._def.get("name", "")

    @property
    def description(self) -> str:
        return self._def.get("description", "")

    def get_parameters(self) -> List[Any]:
        """从 inputSchema 中提取参数定义"""
        from .tools.base import ToolParameter

        schema = self._def.get("inputSchema", {})
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        params = []
        for prop_name, prop_info in properties.items():
            params.append(ToolParameter(
                name=prop_name,
                type=prop_info.get("type", "string"),
                description=prop_info.get("description", ""),
                required=prop_name in required,
            ))
        return params

    def run(self, params: Dict[str, Any]) -> str:
        return self.client.call_tool(self.name, params)

    def to_openai_schema(self) -> Dict[str, Any]:
        """生成 OpenAI Function Calling 格式"""
        from .tools.base import Tool

        params = self.get_parameters()
        properties = {}
        required_list = []
        for p in params:
            properties[p.name] = {"type": p.type, "description": p.description}
            if p.required:
                required_list.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required_list,
                },
            },
        }
