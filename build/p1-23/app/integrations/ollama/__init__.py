"""Local Ollama boundary owned by the Orchestrator."""

from .client import OllamaClient, OllamaContractError, OllamaUnavailableError

__all__ = ["OllamaClient", "OllamaContractError", "OllamaUnavailableError"]
