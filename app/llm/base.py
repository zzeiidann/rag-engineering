from typing import Protocol

from app.models import ContextItem


class LLMClient(Protocol):
    def generate(self, query: str, context: list[ContextItem]) -> str: ...
