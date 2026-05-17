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


class FakeStreamingCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            reasoning_content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="call_1",
                                    function=SimpleNamespace(name="write_file", arguments='{"path": "'),
                                )
                            ],
                        )
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            reasoning_content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id=None,
                                    function=SimpleNamespace(name=None, arguments='game.html", "content": "hi"}'),
                                )
                            ],
                        )
                    )
                ],
                usage=None,
            ),
        ]
        return iter(chunks)


class FakeStreamingClient:
    def __init__(self):
        self.completions = FakeStreamingCompletions()
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

    def test_streaming_tool_calls_are_accumulated(self):
        llm = HelloAgentsLLM(
            base_url="https://api.deepseek.com",
            api_key="test-key",
            model="deepseek-v4-pro",
        )
        fake_client = FakeStreamingClient()
        llm.client = fake_client
        progress = []

        response = llm.invoke_with_tools(
            messages=[{"role": "user", "content": "write a file"}],
            tools=[],
            stream=True,
            on_progress=lambda event, value: progress.append((event, value)),
        )

        self.assertTrue(fake_client.completions.kwargs["stream"])
        self.assertEqual(
            [
                {
                    "id": "call_1",
                    "name": "write_file",
                    "arguments": {"path": "game.html", "content": "hi"},
                }
            ],
            response["tool_calls"],
        )
        self.assertTrue(any(event == "tool_arguments" for event, _ in progress))


if __name__ == "__main__":
    unittest.main()
