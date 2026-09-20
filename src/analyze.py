from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.ollama_provider import OllamaNewsAnalysisProvider  # noqa: E402
from src.analysis.pipeline import analyze_pending_articles  # noqa: E402
from src.analysis.provider import AnalysisProviderError  # noqa: E402
from src.database import NewsDatabase  # noqa: E402
from src.logging_config import configure_logging  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze collected news for one stock.")
    parser.add_argument("symbol", help="Stock code, for example 2330 or 2330.TW")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--model", default=None, help="Local Ollama model; defaults to OLLAMA_MODEL")
    arguments = parser.parse_args()
    ticker = arguments.symbol.strip().upper()
    symbol = (
        ticker.split(".", 1)[0]
        if ticker.endswith((".TW", ".TWO")) or ticker.isdigit()
        else ticker
    )
    if not symbol or arguments.limit < 1:
        parser.error("symbol is required and --limit must be positive")

    logger = configure_logging(PROJECT_ROOT / "logs" / "collector.log")
    database = NewsDatabase(PROJECT_ROOT / "data" / "stock_news.db")
    try:
        provider = OllamaNewsAnalysisProvider(model=arguments.model)
        summary = analyze_pending_articles(
            database, provider, symbol, arguments.limit, logger
        )
    except AnalysisProviderError as exc:
        print(f"News Analysis Failed: {exc}", file=sys.stderr)
        return 1
    finally:
        database.close()

    print("News Analysis Complete")
    print(f"Stock: {symbol}")
    print(f"Pending: {summary.pending}")
    print(f"Analyzed: {summary.analyzed}")
    print(f"Skipped: {summary.skipped}")
    print(f"Errors: {summary.errors}")
    return 0 if not summary.errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
