from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class ModelMessage:
    role: str
    content: str

@dataclass(frozen=True)
class ModelResponse:
    content: str
    model: str

class ProviderError(RuntimeError):
    """Safe model-provider failure."""

class ModelProvider(ABC):
    @abstractmethod
    async def generate(self, messages: list[ModelMessage], temperature: float = 0) -> ModelResponse:
        """Generate a provider-independent response."""
