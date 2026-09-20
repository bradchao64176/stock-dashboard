import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from src.collector import collect_news
from src.analysis.ollama_provider import OllamaNewsAnalysisProvider
from src.analysis.pipeline import analyze_pending_articles
from src.analysis.provider import AnalysisProviderError
from src.database import NewsDatabase
from src.logging_config import configure_logging
from src.models import FeedSource, WatchlistStock
from src.sources.yahoo_global import fetch_yahoo_finance_news
from src.pchome_panel import render_pchome_panel


PROJECT_ROOT = Path(__file__).resolve().parent
NEWS_DATABASE = PROJECT_ROOT / "data" / "stock_news.db"


st.set_page_config(page_title="Stock Dashboard", page_icon="🍎", layout="wide")


@st.cache_data(ttl=300)
def get_stock_data(ticker, period):
    """Download price history for the selected ticker from Yahoo Finance."""
    stock = yf.Ticker(ticker)
    history = stock.history(period=period, auto_adjust=False)
    recent = stock.history(period="5d", auto_adjust=False)
    one_year = stock.history(period="1y", auto_adjust=False)
    return history, recent, one_year


@st.cache_data(ttl=60)
def get_news_filter_options():
    """Return available categories, stocks, and the most recent collection run."""
    if not NEWS_DATABASE.exists():
        return [], [], None
    with sqlite3.connect(NEWS_DATABASE) as connection:
        categories = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT category FROM articles ORDER BY category"
            ).fetchall()
        ]
        stocks = connection.execute(
            """
            SELECT stock_symbol, MAX(company_name)
            FROM articles
            WHERE stock_symbol IS NOT NULL
            GROUP BY stock_symbol
            ORDER BY stock_symbol
            """
        ).fetchall()
        latest_run = connection.execute(
            """
            SELECT completed_at, fetched_count, new_count, duplicate_count,
                   error_count, status
            FROM collection_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return categories, stocks, latest_run


@st.cache_data(ttl=60)
def get_news_articles(category=None, stock_symbol=None, limit=30):
    """Load recent normalized news articles from the collector database."""
    if not NEWS_DATABASE.exists():
        return []
    conditions = []
    parameters = []
    if category:
        conditions.append("a.category = ?")
        parameters.append(category)
    if stock_symbol:
        conditions.append("s.stock_symbol = ?")
        parameters.append(stock_symbol)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    parameters.append(limit)

    with sqlite3.connect(NEWS_DATABASE) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            f"""
            SELECT a.published_at, a.source, a.category, s.stock_symbol,
                   COALESCE(x.company_name, s.company_name, a.company_name) AS company_name,
                   a.title, a.summary, a.url, a.collected_at,
                   x.ai_summary, x.sentiment, x.sentiment_score,
                   x.importance_score, x.topic, x.per_stock_news_score,
                   x.model, x.analyzed_at
            FROM articles AS a
            JOIN article_stocks AS s ON s.article_id = a.id
            LEFT JOIN article_analyses AS x ON x.id = (
                SELECT x2.id
                FROM article_analyses AS x2
                WHERE x2.article_id = a.id
                  AND x2.stock_symbol = s.stock_symbol
                ORDER BY x2.id DESC
                LIMIT 1
            )
            {where_clause}
            ORDER BY a.published_at DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


def collect_news_for_ticker(stock_symbol, is_taiwan_stock):
    """Collect from Yahoo Taiwan RSS or Yahoo Finance global news."""
    safe_symbol = quote(stock_symbol, safe="")
    target_stock = WatchlistStock(
        symbol=stock_symbol,
        company_name="",
    )
    if is_taiwan_stock:
        source = FeedSource(
            name=f"Yahoo Taiwan Stock - {stock_symbol}",
            url=f"https://tw.stock.yahoo.com/rss?s={safe_symbol}",
            category="stock",
            stock=target_stock,
        )
        fetcher = None
    else:
        source = FeedSource(
            name=f"Yahoo Finance Global - {stock_symbol}",
            url=stock_symbol,
            category="stock",
            stock=target_stock,
        )
        fetcher = fetch_yahoo_finance_news
    logger = configure_logging(PROJECT_ROOT / "logs" / "collector.log")
    database = NewsDatabase(NEWS_DATABASE)
    try:
        arguments = dict(
            database=database,
            sources=[source],
            watchlist=[],
            timeout=20,
            logger=logger,
        )
        if fetcher is not None:
            arguments["fetcher"] = fetcher
        return collect_news(**arguments)
    finally:
        database.close()


def analyze_news_for_ticker(stock_symbol, limit=20):
    """Analyze pending collected articles through the configured AI provider."""
    logger = configure_logging(PROJECT_ROOT / "logs" / "collector.log")
    database = NewsDatabase(NEWS_DATABASE)
    try:
        provider = OllamaNewsAnalysisProvider()
        return analyze_pending_articles(
            database=database,
            provider=provider,
            stock_symbol=stock_symbol,
            limit=limit,
            logger=logger,
        )
    finally:
        database.close()


st.markdown(
    """
    <style>
    .stock-card {
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        padding: 20px;
        min-height: 130px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
    }
    .card-label {
        color: #6b7280;
        font-size: 0.9rem;
        font-weight: 600;
        margin-bottom: 8px;
    }
    .card-value {
        color: #111827;
        font-size: 1.8rem;
        font-weight: 700;
        line-height: 1.2;
    }
    .card-note {
        color: #6b7280;
        font-size: 0.8rem;
        margin-top: 8px;
    }
    .positive { color: #16a34a; }
    .negative { color: #dc2626; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Stock Dashboard")
render_pchome_panel(PROJECT_ROOT, get_news_articles)
with st.expander("Yahoo Taiwan Bull/Bear", expanded=True):
    st.caption("Enter a Taiwan stock code and choose its listing market.")
    bullbear_code_col, bullbear_market_col = st.columns(2)
    bullbear_code = bullbear_code_col.text_input(
        "Taiwan stock code", value="3293", key="bullbear_code",
        help="Enter 4–6 digits, preserving leading zeros (for example, 3293 or 0050).",
    ).strip()
    bullbear_market = bullbear_market_col.selectbox(
        "Taiwan listing market", ["TWO", "TW"], key="bullbear_market",
        format_func=lambda market: "TPEx / OTC (.TWO)" if market == "TWO" else "TWSE / Listed (.TW)",
    )
    if re.fullmatch(r"[0-9]{4,6}", bullbear_code):
        bullbear_symbol = f"{bullbear_code}.{bullbear_market}"
        bullbear_url = f"https://tw.stock.yahoo.com/quote/{bullbear_symbol}/bullbear"
        st.link_button(f"Open {bullbear_symbol} Bull/Bear on Yahoo Taiwan", bullbear_url)
        st.caption("Open the Bull/Bear page in a new tab using the button above.")
    elif bullbear_code:
        st.warning("Enter a Taiwan stock code containing 4–6 digits, such as 3293.")
    else:
        st.info("Enter a Taiwan stock code to open its Bull/Bear page.")

ticker_input = st.text_input("Search by ticker symbol", value="AAPL")
ticker = ticker_input.strip().upper() or "AAPL"
st.caption(f"Showing ticker: {ticker} • Data from Yahoo Finance")

period_options = {
    "1 Month": "1mo",
    "3 Months": "3mo",
    "6 Months": "6mo",
    "1 Year": "1y",
    "5 Years": "5y",
}

selected_label = st.selectbox("Select a time period", period_options.keys(), index=3)
selected_period = period_options[selected_label]
chart_type = st.selectbox("Select a chart type", ["Line", "Candlestick"])

st.write("Moving averages")
ma_col1, ma_col2, ma_col3 = st.columns(3)
show_ma_20 = ma_col1.checkbox("20-day MA", value=True)
show_ma_50 = ma_col2.checkbox("50-day MA", value=True)
show_ma_200 = ma_col3.checkbox("200-day MA", value=True)

try:
    history, recent, one_year = get_stock_data(ticker, selected_period)

    if history.empty or recent.empty or one_year.empty:
        st.warning(f"No stock data was found for {ticker}. Check the ticker and try again.")
        st.stop()

    current_price = float(recent["Close"].iloc[-1])
    previous_close = float(recent["Close"].iloc[-2]) if len(recent) >= 2 else current_price
    price_change = current_price - previous_close
    percentage_change = (price_change / previous_close) * 100 if previous_close else 0
    week_52_high = float(one_year["High"].max())
    week_52_low = float(one_year["Low"].min())
    change_class = "positive" if price_change >= 0 else "negative"

    moving_average_source = history if len(history) >= len(one_year) else one_year
    ma_20 = moving_average_source["Close"].rolling(window=20).mean().reindex(history.index)
    ma_50 = moving_average_source["Close"].rolling(window=50).mean().reindex(history.index)
    ma_200 = moving_average_source["Close"].rolling(window=200).mean().reindex(history.index)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f"""<div class="stock-card"><div class="card-label">Current Price</div>
            <div class="card-value">${current_price:,.2f}</div>
            <div class="card-note">Previous close: ${previous_close:,.2f}</div></div>""",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"""<div class="stock-card"><div class="card-label">Daily Change</div>
            <div class="card-value {change_class}">${price_change:+,.2f}</div>
            <div class="card-note {change_class}">{percentage_change:+.2f}%</div></div>""",
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"""<div class="stock-card"><div class="card-label">52 Week High</div>
            <div class="card-value">${week_52_high:,.2f}</div>
            <div class="card-note">Highest price in the past year</div></div>""",
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            f"""<div class="stock-card"><div class="card-label">52 Week Low</div>
            <div class="card-value">${week_52_low:,.2f}</div>
            <div class="card-note">Lowest price in the past year</div></div>""",
            unsafe_allow_html=True,
        )

    st.subheader(f"Historical Closing Price — {selected_label}")
    if chart_type == "Line":
        price_chart = go.Figure(
            go.Scatter(
                x=history.index,
                y=history["Close"],
                mode="lines",
                name="Close",
                line=dict(color="#2563eb", width=2),
            )
        )
    else:
        price_chart = go.Figure(
            go.Candlestick(
                x=history.index,
                open=history["Open"],
                high=history["High"],
                low=history["Low"],
                close=history["Close"],
                name=ticker,
                increasing_line_color="#16a34a",
                decreasing_line_color="#dc2626",
            )
        )

    if show_ma_20:
        price_chart.add_trace(
            go.Scatter(x=history.index, y=ma_20, mode="lines", name="20-day MA", line=dict(color="#f59e0b"))
        )
    if show_ma_50:
        price_chart.add_trace(
            go.Scatter(x=history.index, y=ma_50, mode="lines", name="50-day MA", line=dict(color="#7c3aed"))
        )
    if show_ma_200:
        price_chart.add_trace(
            go.Scatter(x=history.index, y=ma_200, mode="lines", name="200-day MA", line=dict(color="#0891b2"))
        )

    price_chart.update_layout(
        height=480,
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_title="Date",
        yaxis_title="Price (USD)",
        hovermode="x unified" if chart_type == "Line" else "closest",
        template="plotly_white",
        xaxis_rangeslider_visible=False,
    )
    st.plotly_chart(price_chart, use_container_width=True, config={"scrollZoom": True})

    st.subheader(f"Trading Volume — {selected_label}")
    volume_chart = go.Figure(
        go.Bar(x=history.index, y=history["Volume"], marker_color="#64748b", name="Volume")
    )
    volume_chart.update_layout(
        height=300,
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_title="Date",
        yaxis_title="Volume",
        hovermode="x unified",
        template="plotly_white",
    )
    st.plotly_chart(volume_chart, use_container_width=True, config={"scrollZoom": True})

    st.subheader("Technical Indicators")

    with st.expander("RSI (Relative Strength Index)"):
        price_difference = history["Close"].diff()
        gains = price_difference.clip(lower=0)
        losses = -price_difference.clip(upper=0)
        average_gain = gains.rolling(window=14).mean()
        average_loss = losses.rolling(window=14).mean()
        relative_strength = average_gain / average_loss
        rsi = 100 - (100 / (1 + relative_strength))

        rsi_chart = go.Figure()
        rsi_chart.add_trace(go.Scatter(x=history.index, y=rsi, name="RSI", line=dict(color="#7c3aed")))
        rsi_chart.add_hline(y=70, line_dash="dash", line_color="#dc2626", annotation_text="Overbought")
        rsi_chart.add_hline(y=30, line_dash="dash", line_color="#16a34a", annotation_text="Oversold")
        rsi_chart.update_layout(
            height=320,
            margin=dict(l=10, r=10, t=20, b=10),
            xaxis_title="Date",
            yaxis_title="RSI",
            yaxis_range=[0, 100],
            template="plotly_white",
        )
        st.plotly_chart(rsi_chart, use_container_width=True)

    with st.expander("MACD (Moving Average Convergence Divergence)"):
        ema_12 = history["Close"].ewm(span=12, adjust=False).mean()
        ema_26 = history["Close"].ewm(span=26, adjust=False).mean()
        macd = ema_12 - ema_26
        signal = macd.ewm(span=9, adjust=False).mean()
        histogram = macd - signal
        histogram_colors = ["#16a34a" if value >= 0 else "#dc2626" for value in histogram]

        macd_chart = go.Figure()
        macd_chart.add_trace(go.Scatter(x=history.index, y=macd, name="MACD", line=dict(color="#2563eb")))
        macd_chart.add_trace(go.Scatter(x=history.index, y=signal, name="Signal", line=dict(color="#f59e0b")))
        macd_chart.add_trace(
            go.Bar(x=history.index, y=histogram, name="Histogram", marker_color=histogram_colors)
        )
        macd_chart.update_layout(
            height=340,
            margin=dict(l=10, r=10, t=20, b=10),
            xaxis_title="Date",
            yaxis_title="MACD",
            hovermode="x unified",
            template="plotly_white",
        )
        st.plotly_chart(macd_chart, use_container_width=True)

    with st.expander("Bollinger Bands"):
        middle_band = history["Close"].rolling(window=20).mean()
        standard_deviation = history["Close"].rolling(window=20).std()
        upper_band = middle_band + (standard_deviation * 2)
        lower_band = middle_band - (standard_deviation * 2)

        bands_chart = go.Figure()
        bands_chart.add_trace(
            go.Scatter(x=history.index, y=upper_band, name="Upper Band", line=dict(color="#94a3b8"))
        )
        bands_chart.add_trace(
            go.Scatter(
                x=history.index,
                y=lower_band,
                name="Lower Band",
                line=dict(color="#94a3b8"),
                fill="tonexty",
                fillcolor="rgba(148, 163, 184, 0.18)",
            )
        )
        bands_chart.add_trace(
            go.Scatter(x=history.index, y=middle_band, name="20-day Average", line=dict(color="#f59e0b"))
        )
        bands_chart.add_trace(
            go.Scatter(x=history.index, y=history["Close"], name="Close", line=dict(color="#2563eb"))
        )
        bands_chart.update_layout(
            height=360,
            margin=dict(l=10, r=10, t=20, b=10),
            xaxis_title="Date",
            yaxis_title="Price (USD)",
            hovermode="x unified",
            template="plotly_white",
        )
        st.plotly_chart(bands_chart, use_container_width=True)

    st.subheader("Historical Data")
    table = history.reset_index()
    date_column = table.columns[0]
    table = table.rename(columns={date_column: "Date"})
    table["Date"] = table["Date"].dt.strftime("%Y-%m-%d")
    table = table[["Date", "Open", "High", "Low", "Close", "Volume"]]
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Open": st.column_config.NumberColumn(format="$%.2f"),
            "High": st.column_config.NumberColumn(format="$%.2f"),
            "Low": st.column_config.NumberColumn(format="$%.2f"),
            "Close": st.column_config.NumberColumn(format="$%.2f"),
            "Volume": st.column_config.NumberColumn(format="localized"),
        },
    )

except Exception as error:
    st.error(f"Could not load data for {ticker}. Check the ticker or your internet connection.")
    st.exception(error)


st.divider()
st.header("Financial News")

ticker_upper = ticker.strip().upper()
is_taiwan_stock = ticker_upper.endswith((".TW", ".TWO")) or ticker_upper.isdigit()
ticker_stock = ticker_upper.split(".", 1)[0] if is_taiwan_stock else ticker_upper
st.caption(f"Showing and collecting news only for the searched ticker: {ticker_stock}")

# Collect once when the searched ticker changes. Other Streamlit controls do not
# trigger another network collection for the same ticker during this session.
if st.session_state.get("news_collected_for") != ticker_stock:
    with st.spinner(f"Collecting the latest news for {ticker_stock}..."):
        collection_summary = collect_news_for_ticker(ticker_stock, is_taiwan_stock)
    st.session_state["news_collected_for"] = ticker_stock
    st.session_state["news_collection_summary"] = collection_summary
    get_news_filter_options.clear()
    get_news_articles.clear()

collection_summary = st.session_state.get("news_collection_summary")
if collection_summary:
    st.caption(
        f"Fetched {collection_summary.fetched} · New {collection_summary.new} · "
        f"Duplicates {collection_summary.duplicates} · Errors {collection_summary.errors}"
    )
    if collection_summary.errors:
        st.warning("Some RSS entries could not be collected. See logs/collector.log for details.")

control_col1, control_col2, control_col3 = st.columns([1, 1, 1])
article_limit = control_col1.selectbox("Articles", [10, 20, 30, 50], index=1)
if control_col2.button(f"Collect latest news for {ticker_stock}"):
    with st.spinner(f"Collecting the latest news for {ticker_stock}..."):
        st.session_state["news_collection_summary"] = collect_news_for_ticker(
            ticker_stock, is_taiwan_stock
        )
    get_news_filter_options.clear()
    get_news_articles.clear()
    st.rerun()

if control_col3.button(f"Analyze pending news for {ticker_stock}"):
    try:
        with st.spinner(f"Analyzing news locally for {ticker_stock}..."):
            analysis_summary = analyze_news_for_ticker(ticker_stock, article_limit)
        st.session_state["analysis_summary"] = analysis_summary
        get_news_articles.clear()
        st.rerun()
    except AnalysisProviderError as error:
        st.error(str(error))

analysis_summary = st.session_state.get("analysis_summary")
if analysis_summary:
    st.caption(
        f"AI analysis: pending {analysis_summary.pending} · "
        f"analyzed {analysis_summary.analyzed} · skipped {analysis_summary.skipped} · "
        f"errors {analysis_summary.errors}"
    )

articles = get_news_articles(stock_symbol=ticker_stock, limit=article_limit)
if not articles:
    st.info(f"Yahoo returned no collected news for {ticker_stock}.")
else:
    st.caption(f"Showing {len(articles)} articles for {ticker_stock}, newest first")
    analyzed_articles = [article for article in articles if article["sentiment_score"] is not None]
    if analyzed_articles:
        total_importance = sum(article["importance_score"] for article in analyzed_articles)
        aggregate_score = (
            sum(
                article["sentiment_score"] * article["importance_score"]
                for article in analyzed_articles
            )
            / total_importance
            if total_importance
            else 0.0
        )
        score_col1, score_col2 = st.columns(2)
        score_col1.metric("Per-stock news score", f"{aggregate_score:+.2f}")
        score_col2.metric("Analyzed articles", len(analyzed_articles))
        with st.expander("How to interpret the news score"):
            st.markdown(
                """
                | Score range | Description |
                |---:|---|
                | **+0.61 to +1.00** | Strong positive impact |
                | **+0.21 to +0.60** | Moderate positive impact |
                | **-0.20 to +0.20** | Neutral or limited impact |
                | **-0.60 to -0.21** | Moderate negative impact |
                | **-1.00 to -0.61** | Strong negative impact |

                The score estimates news impact, not future price movement or investment advice.
                """
            )

    for article in articles:
        metadata = [article["published_at"], article["source"], ticker_stock]
        with st.container(border=True):
            st.subheader(article["title"])
            st.caption(" · ".join(metadata))
            if article["ai_summary"]:
                sentiment_icons = {"positive": "🟢", "neutral": "⚪", "negative": "🔴"}
                st.write(article["ai_summary"])
                st.caption(
                    f'{sentiment_icons.get(article["sentiment"], "")} '
                    f'{article["sentiment"].title()} {article["sentiment_score"]:+.2f} · '
                    f'Importance {article["importance_score"]}/5 · '
                    f'Topic: {article["topic"]} · '
                    f'Impact: {article["per_stock_news_score"]:+.2f}'
                )
            elif article["summary"]:
                st.write(article["summary"])
                st.caption("Not analyzed yet")
            st.link_button("Open original article", article["url"])
