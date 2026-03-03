"""Basis-Klasse für alle Jarvis Tools."""

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Abstrakte Basisklasse für Agent-Tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Eindeutiger Name des Tools."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Beschreibung für das LLM."""
        ...

    @abstractmethod
    def parameters_schema(self) -> dict:
        """JSON Schema der Parameter für Gemini."""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Tool ausführen und Ergebnis als String zurückgeben."""
        ...
