from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from src.models import AIAnalysis, Article, CollectionSummary, PendingArticle


SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    published_at TEXT NOT NULL,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    stock_symbol TEXT,
    company_name TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    UNIQUE (url),
    UNIQUE (title, published_at)
);

CREATE INDEX IF NOT EXISTS idx_articles_published_at
    ON articles (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_category
    ON articles (category);
CREATE INDEX IF NOT EXISTS idx_articles_stock_symbol
    ON articles (stock_symbol);

CREATE TABLE IF NOT EXISTS article_stocks (
    article_id INTEGER NOT NULL,
    stock_symbol TEXT NOT NULL,
    company_name TEXT,
    associated_at TEXT NOT NULL,
    PRIMARY KEY (article_id, stock_symbol),
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_article_stocks_symbol
    ON article_stocks (stock_symbol, article_id);

CREATE TABLE IF NOT EXISTS collection_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    new_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS article_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL,
    stock_symbol TEXT NOT NULL,
    company_name TEXT NOT NULL,
    ai_summary TEXT NOT NULL,
    sentiment TEXT NOT NULL CHECK (sentiment IN ('positive', 'neutral', 'negative')),
    sentiment_score REAL NOT NULL CHECK (sentiment_score BETWEEN -1.0 AND 1.0),
    importance_score INTEGER NOT NULL CHECK (importance_score BETWEEN 1 AND 5),
    topic TEXT NOT NULL,
    per_stock_news_score REAL NOT NULL CHECK (per_stock_news_score BETWEEN -1.0 AND 1.0),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE,
    UNIQUE (article_id, stock_symbol, provider, model, prompt_version)
);

CREATE INDEX IF NOT EXISTS idx_article_analyses_stock
    ON article_analyses (stock_symbol, analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_article_analyses_article
    ON article_analyses (article_id);
"""


class NewsDatabase:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)
        self.connection.execute(
            """
            INSERT OR IGNORE INTO article_stocks (
                article_id, stock_symbol, company_name, associated_at
            )
            SELECT id, stock_symbol, company_name, collected_at
            FROM articles
            WHERE stock_symbol IS NOT NULL
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def start_run(self, started_at: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO collection_runs (started_at, status) VALUES (?, ?)",
            (started_at, "running"),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def insert_article(self, article: Article) -> bool:
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO articles (
                published_at, source, category, stock_symbol, company_name,
                title, summary, url, collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.published_at,
                article.source,
                article.category,
                article.stock_symbol,
                article.company_name,
                article.title,
                article.summary,
                article.url,
                article.collected_at,
            ),
        )
        inserted = cursor.rowcount == 1
        article_id = cursor.lastrowid if inserted else None
        if article_id is None:
            row = self.connection.execute(
                """
                SELECT id FROM articles
                WHERE url = ? OR (title = ? AND published_at = ?)
                ORDER BY id LIMIT 1
                """,
                (article.url, article.title, article.published_at),
            ).fetchone()
            article_id = row[0] if row else None
        if article_id is not None and article.stock_symbol:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO article_stocks (
                    article_id, stock_symbol, company_name, associated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    article_id,
                    article.stock_symbol,
                    article.company_name,
                    article.collected_at,
                ),
            )
        self.connection.commit()
        return inserted

    def finish_run(
        self,
        run_id: int,
        completed_at: str,
        summary: CollectionSummary,
        error_summary: Optional[str] = None,
    ) -> None:
        status = "completed_with_errors" if summary.errors else "completed"
        self.connection.execute(
            """
            UPDATE collection_runs
            SET completed_at = ?, fetched_count = ?, new_count = ?,
                duplicate_count = ?, error_count = ?, status = ?, error_summary = ?
            WHERE id = ?
            """,
            (
                completed_at,
                summary.fetched,
                summary.new,
                summary.duplicates,
                summary.errors,
                status,
                error_summary,
                run_id,
            ),
        )
        self.connection.commit()

    def get_pending_articles(
        self,
        stock_symbol: str,
        provider: str,
        model: str,
        prompt_version: str,
        limit: int,
    ) -> list[PendingArticle]:
        rows = self.connection.execute(
            """
            SELECT a.id, a.published_at, s.stock_symbol,
                   COALESCE(s.company_name, a.company_name),
                   a.title, a.summary, a.source
            FROM articles AS a
            JOIN article_stocks AS s ON s.article_id = a.id
            WHERE s.stock_symbol = ?
              AND NOT EXISTS (
                  SELECT 1 FROM article_analyses AS x
                  WHERE x.article_id = a.id
                    AND x.stock_symbol = s.stock_symbol
                    AND x.provider = ?
                    AND x.model = ?
                    AND x.prompt_version = ?
              )
            ORDER BY a.published_at DESC
            LIMIT ?
            """,
            (stock_symbol, provider, model, prompt_version, limit),
        ).fetchall()
        return [PendingArticle(*row) for row in rows]

    def save_analysis(
        self,
        article_id: int,
        analysis: AIAnalysis,
        provider: str,
        model: str,
        prompt_version: str,
        analyzed_at: str,
    ) -> bool:
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO article_analyses (
                article_id, stock_symbol, company_name, ai_summary, sentiment,
                sentiment_score, importance_score, topic, per_stock_news_score,
                provider, model, prompt_version, analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                analysis.stock_symbol,
                analysis.company_name,
                analysis.ai_summary,
                analysis.sentiment,
                analysis.sentiment_score,
                analysis.importance_score,
                analysis.topic,
                analysis.per_stock_news_score,
                provider,
                model,
                prompt_version,
                analyzed_at,
            ),
        )
        self.connection.commit()
        return cursor.rowcount == 1
