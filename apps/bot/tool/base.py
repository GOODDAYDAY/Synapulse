"""Base classes for all tool implementations.

BaseTool defines the core contract (name, description, parameters, execute).
Format mixins (OpenAITool, AnthropicTool, ...) add format-specific output methods.
A tool inherits from one or more format mixins to declare which LLM APIs it supports.
"""

from abc import ABC, abstractmethod


class BaseTool(ABC):
    """Core tool definition — what it is and how to run it."""

    name: str
    description: str
    parameters: dict  # JSON Schema

    def validate(self) -> None:
        """Override to validate tool-specific config (e.g. API keys)."""

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute the tool with the given arguments and return a text result."""


class OpenAITool(BaseTool):
    """Mixin: tool can output OpenAI function calling format."""

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class AnthropicTool(BaseTool):
    """Mixin: tool can output Anthropic tool use format."""

    def to_anthropic(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }
