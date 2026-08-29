from __future__ import annotations
import asyncio
import json
import re
import urllib.error
import urllib.request
from .base import ModelMessage, ModelProvider, ModelResponse, ProviderError


def final_answer(content: str) -> str:
    """Remove provider reasoning blocks and return only user-facing text."""
    cleaned = re.sub(r"<think\b[^>]*>.*?</think>\s*", "", content, flags=re.IGNORECASE | re.DOTALL)
    if re.search(r"</think>", cleaned, flags=re.IGNORECASE):
        cleaned = re.split(r"</think>", cleaned, flags=re.IGNORECASE)[-1]
    return cleaned.strip()

class OpenAICompatibleProvider(ModelProvider):
    def __init__(self, endpoint: str, api_key: str, model: str, timeout_seconds: float = 30) -> None:
        self.endpoint, self.api_key, self.model = endpoint, api_key, model
        self.timeout_seconds = timeout_seconds

    async def generate(self, messages: list[ModelMessage], temperature: float = 0) -> ModelResponse:
        return await asyncio.to_thread(self._generate_sync, messages, temperature)

    def _generate_sync(self, messages: list[ModelMessage], temperature: float) -> ModelResponse:
        payload = json.dumps({"model": self.model, "messages": [
            {"role": item.role, "content": item.content} for item in messages
        ], "temperature": temperature}).encode("utf-8")
        request = urllib.request.Request(self.endpoint, data=payload, headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"
        }, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise ProviderError(f"Model service returned HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise ProviderError("Model service is unavailable") from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProviderError("Model service returned an invalid response") from error
        try:
            content = final_answer(result["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise ProviderError("Model service response did not contain an assistant message") from error
        if not content:
            raise ProviderError("Model service returned an empty response")
        return ModelResponse(content, result.get("model", self.model))
