from __future__ import annotations

import logging

from src.analysis.ollama_provider import PROMPT_VERSION
from src.analysis.provider import NewsAnalysisProvider
from src.database import NewsDatabase
from src.models import AnalysisSummary
from src.normalizer import utc_now_iso


def analyze_pending_articles(
    database: NewsDatabase,
    provider: NewsAnalysisProvider,
    stock_symbol: str,
    limit: int,
    logger: logging.Logger,
    prompt_version: str = PROMPT_VERSION,
) -> AnalysisSummary:
    pending = database.get_pending_articles(
        stock_symbol=stock_symbol,
        provider=provider.name,
        model=provider.model,
        prompt_version=prompt_version,
        limit=limit,
    )
    summary = AnalysisSummary(pending=len(pending))
    for article in pending:
        try:
            analysis = provider.analyze(article)
            if database.save_analysis(
                article_id=article.id,
                analysis=analysis,
                provider=provider.name,
                model=provider.model,
                prompt_version=prompt_version,
                analyzed_at=utc_now_iso(),
            ):
                summary.analyzed += 1
            else:
                summary.skipped += 1
        except Exception:
            summary.errors += 1
            logger.exception("AI analysis failed for article %s", article.id)
    return summary
