"""Exact displayed-snapshot formatting and explicit manual delivery."""
import math
import uuid
import pandas as pd

from services import line_bot_service
from services.scanner_entry_service import SCANNER_NAMES
from services.liquidity_filter import format_trading_value
from services.entry_timing_service import STATUS_LABELS

MAX_STOCKS_PER_MESSAGE = 5
MAX_TEXT_UNITS = 5000


def get_line_eligible_candidates(entry_analysis_df):
    """Deliver every displayed row. Compatibility name; no eligibility filtering."""
    if entry_analysis_df is None:
        return pd.DataFrame()
    return entry_analysis_df.copy(deep=True)


def eligible_candidates(results, scanner_id=None):
    # Compatibility name. Page identity belongs to the UI snapshot boundary,
    # never a second row-selection pipeline.
    return get_line_eligible_candidates(results)


def _fmt(value, spec=".2f"):
    try:
        return format(float(value), spec) if math.isfinite(float(value)) else "N/A"
    except (TypeError, ValueError):
        return "N/A"


def _text(value):
    if value is None or pd.isna(value):
        return "N/A"
    return str(value).replace("\n", " ").replace("\r", " ")[:100]


def stock_message(row):
    status = STATUS_LABELS.get(row.get("entry_status"), "❔ " + _text(row.get("entry_status")))
    message = (f"{status.split()[0]} {_text(row.get('stock_code', row.get('ticker')))} {_text(row.get('stock_name'))}\n"
               f"資料日期：{_text(row.get('analysis_date'))}\n目前價：${_fmt(row.get('current_price'), '.2f')}\n成交值：{format_trading_value(row.get('trading_value'))}\n進場型態：{status}\n"
               f"參考進場區：${_fmt(row.get('entry_zone_low'), '.2f')} ～ ${_fmt(row.get('entry_zone_high'), '.2f')}\n"
               f"MA20：${_fmt(row.get('ma20'), '.2f')}\nMA60：${_fmt(row.get('ma60'), '.2f')}\n距 MA20：{_fmt(row.get('distance_ma20_pct', row.get('distance_to_ma20_pct')), '+.2f')}%\n"
               f"Impulse MACD：{_fmt(row.get('impulse_macd'), '.2f')}\nSignal：{_fmt(row.get('impulse_signal'), '.2f')}\n"
               f"Histogram：{_fmt(row.get('histogram'), '+.2f')} {_text(row.get('histogram_direction'))}\n"
               f"參考停損：${_fmt(row.get('reference_stop'), '.2f')}\n風險：{_fmt(row.get('risk_pct'), '.1f')}%\n"
               f"2R Target：${_fmt(row.get('target_2r'), '.2f')}\n3R Target：${_fmt(row.get('target_3r'), '.2f')}")
    fields = {
        "impulse_macd": [("Golden Cross Date", "golden_cross_date"), ("Cross Zone", "cross_zone"), ("Strong Golden Cross Score", "strong_golden_cross_score")],
        "bear_flag": [("Flag Breakout Price", "upper_flag_trendline"), ("Flag High", "flag_high"), ("Flag Low", "flag_low"), ("Breakout Date", "breakout_date")],
        "bear_flag_backtest": [("Current Breakout Date", "breakout_date"), ("Flag Breakout Price", "upper_flag_trendline")],
        "bear_flag_gap": [("Gap Price", "gap_top"), ("Breakout Price", "breakout_close")],
        "unfilled_gap": [("Gap Low", "gap_bottom"), ("Gap High", "gap_top"), ("Gap Status", "gap_status")],
    }[row["scanner_id"]]
    for label, key in fields:
        message += f"\n{label}：{_text(row.get(key))}"
    if row["scanner_id"] in ("bear_flag_gap", "unfilled_gap"):
        gap = row.get("gap_pct")
        try:
            gap = float(gap)
            gap_text = f"{gap:.2%}" if math.isfinite(gap) else "N/A"
        except (TypeError, ValueError):
            gap_text = "N/A"
        message += "\nGap %：" + gap_text
    return message


def build_preview(results, scanner_id, now=None):
    eligible = eligible_candidates(results, scanner_id)
    if len(eligible) != (0 if results is None else len(results)):
        raise ValueError("LINE candidate count differs from displayed Entry Timing analysis")
    stamp = pd.Timestamp.now(tz="Asia/Taipei") if now is None else pd.Timestamp(now)
    stamp = stamp.tz_localize("Asia/Taipei") if stamp.tzinfo is None else stamp.tz_convert("Asia/Taipei")
    header = f"📈 Stock Dashboard\n進場候選通知\n\n選股策略：\n{SCANNER_NAMES[scanner_id]}\n\n時間：\n{stamp:%Y/%m/%d %H:%M}\n\n符合進場條件：\n{len(eligible)} 檔\n"
    chunks, counts, current = [], [], []
    for row in eligible.to_dict("records"):
        block = stock_message(row)
        # Leave room for headers, part numbering and a short reference-level label.
        if len((header + block).encode("utf-16-le")) // 2 > MAX_TEXT_UNITS - 150:
            raise ValueError("Stock message exceeds LINE length limit")
        tentative = "\n\n".join(current + [block])
        if current and (len(current) >= MAX_STOCKS_PER_MESSAGE or len((header + tentative).encode("utf-16-le")) // 2 > MAX_TEXT_UNITS - 150):
            chunks.append("\n\n".join(current)); counts.append(len(current)); current = []
        current.append(block)
    if current:
        chunks.append("\n\n".join(current)); counts.append(len(current))
    messages = [header + f"\n第 {i+1}/{len(chunks)} 則\n\n" + body + "\n\n技術參考區域與風險目標，非價格預測。" for i, body in enumerate(chunks)]
    return dict(scanner_id=scanner_id, messages=messages, counts=counts, candidate_count=len(eligible), stock_codes=eligible.get("stock_code", pd.Series(dtype=str)).tolist())


def send_preview(preview, event_id):
    """No implicit retries; one invocation represents one user's send action."""
    sent = stocks = 0
    for i, text in enumerate(preview["messages"]):
        result = line_bot_service.send_text(text, str(uuid.uuid5(uuid.UUID(event_id), str(i))))
        if not result["ok"]:
            return dict(ok=False, messages_sent=sent, stocks_sent=stocks, error=result["error"])
        sent += 1
        stocks += preview["counts"][i]
    return dict(ok=True, messages_sent=sent, stocks_sent=stocks, error=None)
