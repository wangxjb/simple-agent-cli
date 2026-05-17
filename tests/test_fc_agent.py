import unittest

from simple_cli.agent.fc import FCAgent
from simple_cli.tools import Tool, ToolParameter, ToolRegistry


class FakeLLM:
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def invoke(self, messages, **kwargs):
        raise AssertionError("invoke should not be used by FCAgent")

    def invoke_with_tools(self, messages, tools, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "我可以帮你写代码、读写文件、运行命令和分析问题。",
                "tool_calls": [],
                "usage": {},
            }
        return {
            "content": "不应该生成第二轮回答",
            "tool_calls": [],
            "usage": {},
        }


class ToolCallingLLM:
    model = "fake-model"

    def __init__(self):
        self.calls = 0
        self.second_messages = None

    def invoke(self, messages, **kwargs):
        raise AssertionError("invoke should not be used by FCAgent")

    def invoke_with_tools(self, messages, tools, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "I need to inspect the directory.",
                "reasoning_content": "Need a directory listing before answering.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "list_directory",
                        "arguments": {"path": "."},
                    }
                ],
                "usage": {},
            }

        self.second_messages = messages
        return {
            "content": "Done.",
            "tool_calls": [],
            "usage": {},
        }


class ListDirectoryTool(Tool):
    def __init__(self):
        super().__init__("list_directory", "List files")

    def get_parameters(self):
        return [ToolParameter("path", "string")]

    def run(self, params):
        return "README.md"


class FCAgentTests(unittest.TestCase):
    def test_returns_first_content_without_extra_no_tool_round(self):
        llm = FakeLLM()
        agent = FCAgent(
            llm=llm,
            tool_registry=ToolRegistry(),
            system_prompt="你是一个中文编程助手。",
            max_steps=5,
        )

        result = agent.run("你能为我做什么")

        self.assertEqual("我可以帮你写代码、读写文件、运行命令和分析问题。", result)
        self.assertEqual(1, llm.calls)

    def test_passes_reasoning_content_back_after_tool_call(self):
        llm = ToolCallingLLM()
        registry = ToolRegistry()
        registry.register(ListDirectoryTool())
        agent = FCAgent(
            llm=llm,
            tool_registry=registry,
            system_prompt="You are a coding assistant.",
            max_steps=5,
        )

        result = agent.run("list files")

        self.assertEqual("Done.", result)
        assistant_messages = [
            msg for msg in llm.second_messages
            if msg.get("role") == "assistant" and msg.get("tool_calls")
        ]
        self.assertEqual(1, len(assistant_messages))
        self.assertEqual(
            "Need a directory listing before answering.",
            assistant_messages[0].get("reasoning_content"),
        )


if __name__ == "__main__":
    unittest.main()
