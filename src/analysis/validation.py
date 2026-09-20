from __future__ import annotations

from typing import Any

from src.models import AIAnalysis, PendingArticle


SENTIMENTS = {"positive", "neutral", "negative"}
TOPICS = {
    "earnings",
    "guidance",
    "corporate_action",
    "product",
    "operations",
    "regulation",
    "macroeconomics",
    "market",
    "analyst_research",
    "legal",
    "management",
    "financing",
    "mergers_acquisitions",
    "other",
}


def validate_analysis(data: dict[str, Any], article: PendingArticle) -> AIAnalysis:
    symbol = str(data.get("stock_symbol", "")).strip().upper()
    if article.stock_symbol.isdigit() and symbol.endswith((".TW", ".TWO")):
        symbol = symbol.split(".", 1)[0]
    if symbol != article.stock_symbol:
        raise ValueError(
            f"Model returned stock symbol {symbol!r}; expected {article.stock_symbol!r}"
        )

    company_name = str(data.get("company_name", "")).strip()
    ai_summary = str(data.get("ai_summary", "")).strip()
    sentiment = str(data.get("sentiment", "")).strip().lower()
    topic = str(data.get("topic", "")).strip().lower()
    if not company_name:
        raise ValueError("Model returned an empty company name")
    if not ai_summary:
        raise ValueError("Model returned an empty summary")
    if sentiment not in SENTIMENTS:
        raise ValueError(f"Invalid sentiment: {sentiment}")
    if topic not in TOPICS:
        raise ValueError(f"Invalid topic: {topic}")

    try:
        sentiment_score = float(data["sentiment_score"])
        importance_score = int(data["importance_score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid sentiment or importance score") from exc
    if not -1.0 <= sentiment_score <= 1.0:
        raise ValueError("sentiment_score must be between -1.0 and 1.0")
    if importance_score not in range(1, 6):
        raise ValueError("importance_score must be between 1 and 5")
    if sentiment == "positive" and sentiment_score <= 0:
        raise ValueError("Positive sentiment requires a positive score")
    if sentiment == "negative" and sentiment_score >= 0:
        raise ValueError("Negative sentiment requires a negative score")
    if sentiment == "neutral" and abs(sentiment_score) > 0.2:
        raise ValueError("Neutral sentiment score must be between -0.2 and 0.2")

    return AIAnalysis(
        stock_symbol=symbol,
        company_name=company_name,
        ai_summary=ai_summary,
        sentiment=sentiment,
        sentiment_score=round(sentiment_score, 4),
        importance_score=importance_score,
        topic=topic,
    )
