from __future__ import annotations
import os
import json
import re
from dataclasses import dataclass
from assistant.memory import ConversationStore
from assistant.models import ModelMessage, ModelProvider, OpenAICompatibleProvider
from assistant.prompts.system import SYSTEM_PROMPT
from assistant.prompts.data import DATA_PROMPT

@dataclass(frozen=True)
class AssistantConfiguration:
    endpoint: str
    api_key: str
    model: str
    timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "AssistantConfiguration":
        return cls(os.getenv("MES_AI_API_ENDPOINT", "").strip(),
                   os.getenv("MES_AI_API_KEY", "").strip(),
                   os.getenv("MES_AI_MODEL", "").strip(),
                   float(os.getenv("MES_AI_TIMEOUT_SECONDS", "30")))

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.api_key and self.model)

class AssistantNotConfigured(RuntimeError):
    pass

class AssistantService:
    def __init__(self, store: ConversationStore | None = None) -> None:
        self.store = store or ConversationStore()

    def status(self) -> dict:
        config = AssistantConfiguration.from_environment()
        return {"configured": config.configured, "model": config.model or None, "phase": 6}

    def _provider(self, config: AssistantConfiguration) -> ModelProvider:
        return OpenAICompatibleProvider(config.endpoint, config.api_key, config.model, config.timeout_seconds)

    async def chat(self, key: str, message: str) -> tuple[str, str]:
        config = AssistantConfiguration.from_environment()
        if not config.configured:
            raise AssistantNotConfigured("Configure MES_AI_API_ENDPOINT, MES_AI_API_KEY, and MES_AI_MODEL in .env")
        history = self.store.get(key)
        response = await self._provider(config).generate([
            ModelMessage("system", SYSTEM_PROMPT), *history, ModelMessage("user", message)
        ], temperature=0)
        self.store.replace(key, [*history, ModelMessage("user", message),
                                 ModelMessage("assistant", response.content)])
        return response.content, response.model

    async def grounded_chat(self, key: str, question: str, intent: str, tool_context: dict) -> tuple[str, str]:
        config = AssistantConfiguration.from_environment()
        if not config.configured:
            raise AssistantNotConfigured("Configure MES_AI_API_ENDPOINT, MES_AI_API_KEY, and MES_AI_MODEL in .env")
        history = self.store.get(key)
        evidence = json.dumps(tool_context, separators=(",", ":"), default=str)
        user_content = f"Question: {question}\nDetected intent: {intent}\nMES tool result: {evidence}"
        response = await self._provider(config).generate([
            ModelMessage("system", DATA_PROMPT), *history, ModelMessage("user", user_content)
        ], temperature=0)
        sources = tool_context.get("sources", [])
        source_lines = [f"- {item['type']}: {item['id']}" for item in sources]
        answer = re.sub(
            r"\n\s*Sources\s*\n.*$", "", response.content,
            flags=re.IGNORECASE | re.DOTALL,
        ).strip()
        if source_lines:
            answer = f"{answer}\n\nSources\n" + "\n".join(source_lines)
        self.store.replace(key, [*history, ModelMessage("user", question),
                                 ModelMessage("assistant", answer)])
        return answer, response.model

    def remember_exchange(self, key: str, question: str, answer: str) -> None:
        history = self.store.get(key)
        self.store.replace(key, [*history, ModelMessage("user", question),
                                 ModelMessage("assistant", answer)])

    def clear(self, key: str) -> None:
        self.store.clear(key)
