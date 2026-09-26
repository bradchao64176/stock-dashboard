<<<<<<< HEAD
# Apple Stock Dashboard

A beginner-friendly Streamlit app that displays current and historical stock data from Yahoo Finance. It starts with Apple (`AAPL`) and can search for other ticker symbols.

## Features

- Search for any stock by ticker symbol (AAPL by default)
- Current price, previous close, and daily price change
- Selectable periods from one month to five years
- Interactive Plotly line and candlestick price charts
- Optional 20-day, 50-day, and 200-day moving-average overlays
- Interactive Plotly trading-volume chart
- Expandable RSI, MACD, and Bollinger Bands indicators
- Historical Open, High, Low, Close, and Volume table
- Yahoo Taiwan Bull/Bear page with a separate Taiwan stock code and listing-market selector
- PChome Taiwan quotes, institutional holdings, daily net-buy indicators, and configurable scoring

## Installation

Python 3.8 or newer is recommended.

1. Install the required packages:

   ```bash
   pip install -r requirements.txt
   ```

## Usage

1. Start Streamlit:

   ```bash
   streamlit run app.py
   ```

2. Open the local URL shown in the terminal (usually `http://localhost:8501`).

3. Enter a ticker such as `AAPL`, `MSFT`, or `GOOGL` in the search box.

4. Choose a time period and select either the line or candlestick price chart.

5. Hover over the Plotly charts to inspect values. Use the toolbar or mouse to zoom, pan, and reset the view.

Stock data is supplied by Yahoo Finance through the `yfinance` package and may be delayed.

### Taiwan Bull/Bear

Open **Yahoo Taiwan Bull/Bear** at the top of the dashboard. Enter a numeric Taiwan
stock code (default: `3293`) and select **TPEx / OTC (.TWO)** or **TWSE / Listed (.TW)**.
For example, `3293` with `.TWO` opens
`https://tw.stock.yahoo.com/quote/3293.TWO/bullbear`; `2330` with `.TW` opens
`https://tw.stock.yahoo.com/quote/2330.TW/bullbear`. Leading zeros are preserved.

Use the **Open … Bull/Bear on Yahoo Taiwan** button to open the page in a new tab.
The dashboard does not embed the page, avoiding blank or blocked frames. Page availability
depends on Yahoo and the selected stock/market combination. This section has its
own input; the existing price-chart and financial-news ticker remains independent.

### PChome stock and institutional analysis

Open **PChome Taiwan Stock & Institutional Investors**, enter a stock code, and click
**Search PChome**. Codes such as `2409`, `2330`, `0050`, and `00981A` are supported.
The dashboard retrieves and parses HTML; it does not embed PChome in a frame.
Results are cached for 300 seconds. Changing scoring weights does not request the page again.

The reusable service uses `requests`, BeautifulSoup, and `pandas.read_html` with `lxml`:

```python
from services.pchome_scraper import fetch_stock
from services.institutional_analysis import analyze_institutions, combine_stock_scores

stock = fetch_stock("2409")
analysis = analyze_institutions(stock)
combined = combine_stock_scores({"institutional": analysis["score"]})
```

`fetch_stock` returns a JSON-compatible dictionary containing quote fields, latest
foreign/investment-trust/dealer/total records, daily `history`, source URL, UTC fetch time,
and missing-data warnings. Invalid codes and unusable pages raise `ValueError` (including
`PChomeParseError`); HTTP failures and timeouts raise `requests.RequestException`.
The public same-page `is_check` loading form is submitted when present. Arbitrary form
destinations and JavaScript are never executed. Tables are identified by headings and
column labels, not fixed indices. Published net values are preserved despite rounding.

All trading and holding volumes, including `shares_held`, are **lots (張)**, as reported
by PChome. Ownership percentages are percentage points: `13.73` means `13.73%`.
Missing or invalid numeric values become `None`, not zero. Prices are TWD.

The inspected PChome page provides **five daily rows per category**; its longer chart
contains weekly observations and is not used for daily indicators. Searches persist
overlapping daily snapshots in `data/pchome_history.db`, retaining up to 120 observations.
Search regularly (with overlapping five-day windows) to build history. Non-overlapping
snapshots restart the continuous history instead of silently bridging a gap. The scraper
does not backfill unavailable daily rows. Five-, ten-, and twenty-day totals require the
full window with no missing net values. Buying streaks reaching the available history
boundary are labeled “at least.” History is separate for each stock and investor category.

PChome's quote section does not specify a trading date. The volume ratio is therefore
unavailable until a matching dated volume is supplied. Reusable callers may pass
`analyze_institutions(stock, daily_volumes={"YYYY-MM-DD": volume_in_lots})`, or provide
a verified `stock["quote_date"]`. The analysis uses only the institutional date's volume;
zero volume and mismatched dates remain unavailable.

The institutional score is a transparent heuristic: `50 + 50 * mean(available factors)`.
The eleven potential factors are three current investor net directions, three signed
buy/sell streaks capped at five observations, foreign/total 5- and 20-day net directions,
and the same-date volume ratio (scaled to ±1 at ±20%). Direction factors are −1/0/+1.
Missing factors are excluded and factor coverage is displayed. Thresholds are 80, 60,
40, and 20 for Strong Institutional Buying, Positive, Neutral, Negative, and Strong
Institutional Selling. This heuristic has not been calibrated as a return forecast.

The combined model accepts 0–100 fundamental, technical, news, and institutional scores.
Default weights are 25/30/20/25 and can be changed in the dashboard or passed to
`combine_stock_scores(scores, weights)`. Existing importance-weighted news sentiment
for the **same stock** is converted from −1…1 to 0…100 using `(sentiment + 1) * 50`.
The current project has no fundamental or technical score providers, so those components
remain unavailable. A result with missing components is explicitly a **partial score**,
with available weights renormalized and configured weight coverage shown. No missing
component is silently filled with a neutral score.

Use **Download structured JSON** to export the quote, history, indicators, factor values,
and combined score for other analysis functions. PChome notes that some holdings are
provider estimates and some OTC data is unavailable; source missing values are preserved.

## Financial news collector

The Streamlit app automatically collects and displays Yahoo news only for the ticker entered in
its search box. Taiwan tickers use Yahoo Taiwan Stock RSS; US and other international tickers use
Yahoo Finance global news. It does not collect a fixed watchlist or broad market feeds.

Install the dependencies and run:

```bash
pip install -r requirements.txt
python src/main.py 2330
python src/main.py AAPL
python src/main.py 7203.T
```

The SQLite database is created at `data/stock_news.db`, and operational errors are written to
`logs/collector.log`. The command requires one explicit ticker, so it never collects unrelated
watchlist or general-market feeds. Taiwan tickers such as `2330.TW` are normalized to `2330` for
the Yahoo Taiwan RSS request. International exchange suffixes such as `.T` and `.AS` are retained.
One article can be associated with multiple stock symbols without duplicating its content.

Duplicate articles are rejected when either the canonical URL already exists or the same title
and publication time already exist. All stored timestamps use ISO 8601 UTC.

Run the automated tests with:

```bash
python -m unittest discover -s tests -v
```

Yahoo Taiwan states that its RSS data is available for personal and noncommercial use and that
Yahoo Stock attribution must be retained. Review its RSS terms before redistributing or using
the collected content commercially.

## AI stock-news analysis

The analysis pipeline converts each collected article into stock-level intelligence:

- identified stock symbol and company name
- concise AI summary
- `positive`, `neutral`, or `negative` sentiment
- sentiment score from `-1.0` to `+1.0`
- importance score from `1` to `5`
- one normalized topic
- article impact score calculated as `sentiment_score * importance_score / 5`

AI results are stored in the `article_analyses` table. A unique provider/model/prompt-version key
prevents duplicate paid analysis while allowing future models to analyze the same article.

Install [Ollama for Windows](https://ollama.com/download/windows), then download a local model
suited to Traditional Chinese financial text:

```powershell
ollama pull gemma-2-9b-it-Q4_K_M
```

Ollama runs locally at `http://localhost:11434`. No OpenAI API key is used and article content
is not sent to OpenAI. Optionally select another installed local model or Ollama address; the
defaults are shown below:

```powershell
$env:OLLAMA_MODEL="gemma-2-9b-it-Q4_K_M:latest"
$env:OLLAMA_BASE_URL="http://localhost:11434"
```

Analyze up to 20 pending articles for one stock:

```powershell
python src/analyze.py 2330 --limit 20
```

The Streamlit Financial News section also has an **Analyze pending news** button. Local model
inference is never started merely by opening an already-analyzed article. The displayed per-stock
score is the importance-weighted mean sentiment score across the analyzed articles currently
shown; it is an informational signal, not investment advice.
=======
# stock-dashboard
stock-dashboard
>>>>>>> b981ec86a1bdd501570f116da7ec23cd9a84dcbe
