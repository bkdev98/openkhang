"""Dual-mode agent core for the openkhang digital twin.

Outward mode: acts AS Khanh to colleagues in Google Chat.
Inward mode: acts AS assistant to Khanh via dashboard/CLI.
"""

from .pipeline import AgentPipeline, AgentResult
from .llm_client import LLMClient, LLMResponse
from .classifier import Classifier
from .prompt_builder import PromptBuilder
from .confidence import ConfidenceScorer
from .draft_queue import DraftQueue
from .matrix_sender import MatrixSender

__all__ = [
    "AgentPipeline",
    "AgentResult",
    "LLMClient",
    "LLMResponse",
    "Classifier",
    "PromptBuilder",
    "ConfidenceScorer",
    "DraftQueue",
    "MatrixSender",
]
