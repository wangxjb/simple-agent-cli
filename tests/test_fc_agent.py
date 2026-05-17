import unittest

from simple_cli.agent.fc import FCAgent
from simple_cli.tools import ToolRegistry


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


if __name__ == "__main__":
    unittest.main()
