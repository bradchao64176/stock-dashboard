"""Streamlit presentation for the reusable PChome services."""
import json
import sqlite3

import requests
import streamlit as st

from services.institutional_analysis import DEFAULT_WEIGHTS, analyze_institutions, combine_stock_scores
from services.institutional_history import save_history
from services.pchome_scraper import fetch_stock, normalize_stock_id, stock_url


LABELS = {"foreign": "Foreign Investors", "investment_trust": "Investment Trust",
          "dealer": "Dealers", "institutional_total": "Total Institutional Investors"}


@st.cache_data(ttl=300, show_spinner=False)
def cached_stock(stock_id):
    return fetch_stock(stock_id)


def _display(value, suffix=""):
    return "Unavailable" if value is None else f"{value:,.2f}{suffix}"


def render_pchome_panel(project_root, load_news):
    with st.expander("PChome Taiwan Stock & Institutional Investors", expanded=True):
        with st.form("pchome_search"):
            code = st.text_input("PChome stock code", value="2409",
                                 help="Examples: 2409, 2330, 0050, 00981A. Leading zeros are preserved.")
            submitted = st.form_submit_button("Search PChome")
        if submitted:
            st.session_state.pop("pchome_result", None)
            try:
                with st.spinner("Retrieving PChome stock and institutional data..."):
                    result = cached_stock(normalize_stock_id(code))
                    try:
                        result = save_history(result, project_root / "data" / "pchome_history.db")
                    except (sqlite3.Error, OSError) as error:
                        result["warnings"].append(f"History could not be saved: {error}")
                    st.session_state["pchome_result"] = result
            except requests.Timeout:
                st.error("PChome did not respond within 15 seconds. Please try again.")
            except requests.RequestException as error:
                st.error(f"Unable to retrieve PChome stock data: {error}")
            except ValueError as error:
                st.error(str(error))
        result = st.session_state.get("pchome_result")
        if not result:
            st.caption("Search to load stock prices and institutional activity. Results are cached for five minutes.")
            return

        analysis = analyze_institutions(result)
        st.subheader(f'{result["stock_id"]} {result["name"]}')
        st.link_button("Open source on PChome", stock_url(result["stock_id"]))
        st.caption(f'Fetched: {result["fetched_at"]} · Institutional data: {analysis["as_of"] or "unavailable"} '
                   '· Prices: TWD · All volumes and holdings: lots (張), not individual shares')
        columns = st.columns(3)
        delta = None
        if result["change"] is not None:
            delta = f'{result["change"]:+.2f}'
            if result["change_percent"] is not None:
                delta += f' ({result["change_percent"]:+.2f}%)'
        columns[0].metric("Current price (TWD)", _display(result["price"]), delta=delta)
        columns[1].metric("Trading volume (lots)", _display(result["volume"]))
        columns[2].metric("Institutional score", _display(analysis["score"], " / 100"))
        st.caption(f'{analysis["interpretation"]} · Institutional factor coverage: {analysis["factor_coverage"]:.0%}')
        st.dataframe([{label: result[key] for key, label in
                       (("open", "Open"), ("high", "High"), ("low", "Low"), ("previous_close", "Previous close"))}],
                     hide_index=True, use_container_width=True)

        st.write("Institutional Investors")
        tabs = st.tabs(list(LABELS.values()))
        for tab, (category, label) in zip(tabs, LABELS.items()):
            with tab:
                rows = result["history"][category]
                if rows:
                    st.dataframe(rows, hide_index=True, use_container_width=True)
                else:
                    st.info(f"No {label.lower()} data is available.")
                indicator = analysis["indicators"][category]
                streak = indicator["consecutive_buy_days"]
                prefix = "At least " if indicator["streak_is_lower_bound"] else ""
                st.caption(f'Consecutive buying: {prefix}{streak} trading days' if streak is not None
                           else "Consecutive buying: unavailable")
                cols = st.columns(3)
                for col, days in zip(cols, (5, 10, 20)):
                    col.metric(f"{days}-day net buy (lots)", _display(indicator[f"net_{days}d"]))
                st.caption(f'{indicator["available_days"]} daily observations available. '
                           'A window requires every daily net value; overlapping searches extend saved history.')
        ratio = analysis["institutional_buy_ratio"]
        st.metric("Institutional net buy / trading volume", "Unavailable" if ratio is None else f"{ratio:.2%}")
        for warning in result["warnings"]:
            st.caption(warning)

        # Load only this Taiwan stock's analyzed news, independently of the main ticker.
        news_score = None
        try:
            articles = load_news(stock_symbol=result["stock_id"], limit=20)
            analyzed = [a for a in articles if a.get("sentiment_score") is not None
                        and a.get("importance_score") is not None]
            importance = sum(a["importance_score"] for a in analyzed)
            if importance > 0:
                sentiment = sum(a["sentiment_score"] * a["importance_score"] for a in analyzed) / importance
                news_score = (sentiment + 1) * 50
        except sqlite3.Error:
            st.caption("News scoring is unavailable until the news database is initialized.")
        st.write("Combined stock score")
        cols = st.columns(4)
        weights = {key: col.number_input(f"{key.title()} weight", min_value=0, max_value=100,
                                         value=value, key=f"pchome_weight_{key}")
                   for col, (key, value) in zip(cols, DEFAULT_WEIGHTS.items())}
        scores = {"fundamental": None, "technical": None, "news": news_score,
                  "institutional": analysis["score"]}
        combined = None
        try:
            combined = combine_stock_scores(scores, weights)
            st.metric("Partial stock score" if combined["missing"] else "Total stock score",
                      _display(combined["score"], " / 100"))
            st.caption(f'Configured weight coverage: {combined["coverage"]:.0%}. '
                       f'Missing components: {", ".join(combined["missing"]) or "none"}. '
                       'Available components are reweighted proportionally.')
        except ValueError as error:
            st.warning(str(error))
        st.caption("News uses up to 20 collected articles for this stock and maps sentiment from −1…1 to 0…100. "
                   "Fundamental and technical scoring providers are not configured.")
        with st.container(border=True):
            st.write("Scoring methodology and reusable data")
            st.write("Institutional score = 50 + 50 × mean of available factors. Daily investor net buying "
                     "and 5/20-day foreign/total net buying use −1, 0, or +1. Signed buying/selling streaks "
                     "scale to ±1 over five observations. A date-matched volume ratio scales to ±1 at ±20%. "
                     "Missing factors are excluded. This is a heuristic, not a calibrated forecast.")
            st.write("80–100: Strong Institutional Buying; 60–<80: Positive; 40–<60: Neutral; "
                     "20–<40: Negative; 0–<20: Strong Institutional Selling.")
            st.caption("PChome identifies some holdings as provider estimates, and some OTC values may be missing.")
            payload = dict(result, institutional_analysis=analysis, combined_score=combined)
            st.download_button("Download structured JSON", json.dumps(payload, ensure_ascii=False, indent=2),
                               file_name=f'pchome_{result["stock_id"]}.json', mime="application/json")
