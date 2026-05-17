import unittest
from types import SimpleNamespace

from simple_cli.llm.client import HelloAgentsLLM


class FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        message = SimpleNamespace(content="OK", tool_calls=None, reasoning_content=None)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice], usage=None)


class FakeClient:
    def __init__(self):
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


class HelloAgentsLLMTests(unittest.TestCase):
    def test_deepseek_v4_tool_calls_disable_thinking_by_default(self):
        llm = HelloAgentsLLM(
            base_url="https://api.deepseek.com",
            api_key="test-key",
            model="deepseek-v4-pro",
        )
        fake_client = FakeClient()
        llm.client = fake_client

        llm.invoke_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "noop",
                        "description": "Noop",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )

        self.assertEqual(
            {"thinking": {"type": "disabled"}},
            fake_client.completions.kwargs.get("extra_body"),
        )


if __name__ == "__main__":
    unittest.main()
