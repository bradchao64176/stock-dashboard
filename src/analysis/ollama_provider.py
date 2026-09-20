from __future__ import annotations

import json
import os
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.analysis.provider import AnalysisProviderError, NewsAnalysisProvider
from src.analysis.validation import SENTIMENTS, TOPICS, validate_analysis
from src.models import AIAnalysis, PendingArticle


PROMPT_VERSION = "stock-news-v1"


class OllamaNewsAnalysisProvider(NewsAnalysisProvider):
    """Analyze news with an Ollama model running on the local computer."""

    name = "ollama"

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 120,
        transport: Optional[Any] = None,
    ):
        self.model = model or os.environ.get(
            "OLLAMA_MODEL", "gemma-2-9b-it-Q4_K_M:latest"
        )
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = timeout
        self.transport = transport or self._post_json

    @staticmethod
    def _schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "stock_symbol": {"type": "string"},
                "company_name": {"type": "string"},
                "ai_summary": {"type": "string"},
                "sentiment": {"type": "string", "enum": sorted(SENTIMENTS)},
                "sentiment_score": {
                    "type": "number",
                    "minimum": -1.0,
                    "maximum": 1.0,
                },
                "importance_score": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                },
                "topic": {"type": "string", "enum": sorted(TOPICS)},
            },
            "required": [
                "stock_symbol",
                "company_name",
                "ai_summary",
                "sentiment",
                "sentiment_score",
                "importance_score",
                "topic",
            ],
            "additionalProperties": False,
        }

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
            raise AnalysisProviderError(
                f"Could not use local Ollama at {self.base_url}: {exc}"
            ) from exc

    def analyze(self, article: PendingArticle) -> AIAnalysis:
        schema = self._schema()
        article_data = {
            "expected_stock_symbol": article.stock_symbol,
            "known_company_name": article.company_name or None,
            "published_at": article.published_at,
            "source": article.source,
            "title": article.title,
            "article_summary": article.summary or "",
        }
        prompt = (
            "Analyze only this financial news article. Identify the company for the expected "
            "stock symbol. Return a concise, factual stock-relevant summary without investment "
            "advice. Classify sentiment from that company's perspective, score it from -1 to 1, "
            "score importance from 1 to 5, and select exactly one allowed topic. Use Traditional "
            "Chinese for ai_summary when the article is Chinese. Return only JSON matching this "
            f"schema: {json.dumps(schema, ensure_ascii=False)}\n\n"
            f"Article: {json.dumps(article_data, ensure_ascii=False)}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
        }
        try:
            response = self.transport(payload)
            content = response["message"]["content"]
            return validate_analysis(json.loads(content), article)
        except AnalysisProviderError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AnalysisProviderError(f"Invalid local Ollama analysis response: {exc}") from exc
