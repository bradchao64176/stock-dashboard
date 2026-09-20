from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WatchlistStock:
    symbol: str
    company_name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeedSource:
    name: str
    url: str
    category: str
    stock: Optional[WatchlistStock] = None


@dataclass(frozen=True)
class Article:
    published_at: str
    source: str
    category: str
    stock_symbol: Optional[str]
    company_name: Optional[str]
    title: str
    summary: Optional[str]
    url: str
    collected_at: str


@dataclass
class CollectionSummary:
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    errors: int = 0


@dataclass(frozen=True)
class PendingArticle:
    id: int
    published_at: str
    stock_symbol: str
    company_name: Optional[str]
    title: str
    summary: Optional[str]
    source: str


@dataclass(frozen=True)
class AIAnalysis:
    stock_symbol: str
    company_name: str
    ai_summary: str
    sentiment: str
    sentiment_score: float
    importance_score: int
    topic: str

    @property
    def per_stock_news_score(self) -> float:
        return round(self.sentiment_score * self.importance_score / 5.0, 4)


@dataclass
class AnalysisSummary:
    pending: int = 0
    analyzed: int = 0
    skipped: int = 0
    errors: int = 0
