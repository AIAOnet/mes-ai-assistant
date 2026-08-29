import json
import os
import unittest
from unittest.mock import MagicMock, patch

from assistant.memory import ConversationStore
from assistant.models import ModelMessage, ModelResponse, OpenAICompatibleProvider
from assistant.models.openai_compatible import final_answer
from assistant.service import AssistantConfiguration, AssistantNotConfigured, AssistantService


class FakeProvider:
    def __init__(self) -> None:
        self.calls = []

    async def generate(self, messages, temperature=0):
        self.calls.append((messages, temperature))
        return ModelResponse("OEE combines availability, performance, and quality.", "test-model")


class AssistantConfigurationTests(unittest.TestCase):
    def test_status_never_returns_api_key_or_endpoint(self) -> None:
        environment = {"MES_AI_API_ENDPOINT": "https://models.example/chat/completions",
                       "MES_AI_API_KEY": "top-secret", "MES_AI_MODEL": "factory-model"}
        with patch.dict(os.environ, environment, clear=True):
            status = AssistantService().status()
        self.assertEqual(status, {"configured": True, "model": "factory-model", "phase": 1})
        self.assertNotIn("top-secret", json.dumps(status))
        self.assertNotIn("models.example", json.dumps(status))

    def test_configuration_requires_endpoint_key_and_model(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(AssistantConfiguration.from_environment().configured)


class ConversationStoreTests(unittest.TestCase):
    def test_history_is_bounded(self) -> None:
        store = ConversationStore(max_messages=2)
        store.replace("session", [ModelMessage("user", "one"), ModelMessage("assistant", "two"),
                                  ModelMessage("user", "three")])
        self.assertEqual([item.content for item in store.get("session")], ["two", "three"])


class AssistantServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_includes_follow_up_history(self) -> None:
        provider, service = FakeProvider(), AssistantService()
        environment = {"MES_AI_API_ENDPOINT": "https://models.example/chat/completions",
                       "MES_AI_API_KEY": "secret", "MES_AI_MODEL": "test-model"}
        with patch.dict(os.environ, environment, clear=True), patch.object(service, "_provider", return_value=provider):
            await service.chat("alice:one", "What is OEE?")
            await service.chat("alice:one", "Explain quality.")
        second_messages = provider.calls[1][0]
        self.assertEqual([item.role for item in second_messages], ["system", "user", "assistant", "user"])
        self.assertEqual(second_messages[-1].content, "Explain quality.")

    async def test_unconfigured_service_fails_without_guessing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AssistantNotConfigured):
                await AssistantService().chat("local:one", "What is the pressure?")


class OpenAICompatibleProviderTests(unittest.TestCase):
    def test_reasoning_tags_are_removed_from_user_facing_answer(self) -> None:
        self.assertEqual(final_answer("<think>private reasoning</think>Final answer"), "Final answer")
        self.assertEqual(final_answer("private reasoning</think>\n\nFinal answer"), "Final answer")

    def test_request_uses_bearer_key_and_chat_completions_shape(self) -> None:
        response = MagicMock()
        response.read.return_value = json.dumps({
            "model": "returned-model", "choices": [{"message": {"content": "Answer"}}]
        }).encode()
        response.__enter__.return_value = response
        provider = OpenAICompatibleProvider("https://models.example/chat", "secret", "configured-model")
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = provider._generate_sync([ModelMessage("user", "Hello")], 0)
        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.headers["Authorization"], "Bearer secret")
        self.assertEqual(body["messages"], [{"role": "user", "content": "Hello"}])
        self.assertEqual(result, ModelResponse("Answer", "returned-model"))


if __name__ == "__main__":
    unittest.main()
