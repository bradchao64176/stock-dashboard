from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import AIAnalysis, PendingArticle


class AnalysisProviderError(RuntimeError):
    pass


class NewsAnalysisProvider(ABC):
    """Extension point for local or future hosted analysis models."""

    name: str
    model: str

    @abstractmethod
    def analyze(self, article: PendingArticle) -> AIAnalysis:
        raise NotImplementedError
