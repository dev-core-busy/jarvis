"""Basis-Klasse für alle Jarvis Tools."""

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Abstrakte Basisklasse für Agent-Tools."""

    # True NUR fuer Werkzeuge, deren Ergebnis einen Agenten-Auftrag traegt
    # (``{"_spawn_agent": …}`` bzw. ``{"_delegate": …}``). Der Agent wertet den
    # Marker ausschliesslich bei diesen Werkzeugen aus – vorher bei JEDEM
    # Ergebnis, eine gelesene Datei mit diesem JSON startete damit einen
    # autonomen Sub-Agenten (Prompt-Injection, Code-Review 2026-10-18).
    liefert_agenten_auftrag: bool = False

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
