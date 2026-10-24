"""Delivery only: consumes the exact final, displayed CHOCH analysis snapshot."""
import math
import uuid
from services.line_bot_service import send_text
from .notification_repository import reserve, finish, snapshot_hash, DEFAULT_PATH


def fmt(value):
    try:
        return f"{float(value):,.2f}" if math.isfinite(float(value)) else "N/A"
    except (ValueError, TypeError):
        return "N/A"


def build_preview(frame):
    messages, ids = [], []
    for row in frame.to_dict("records"):
        text = ("Stock Dashboard — SMC / CHOCH\n"
                f"{row['stock_code']} {str(row['stock_name'])[:80]}\n{row['timeframe']} {row['structure_type']} {row['direction']} CHOCH\n"
                f"Signal date: {row['signal_date']}\nAnalysis date: {row['analysis_date']}\n"
                f"Structure: {row['market_structure']}\nCHOCH level: {fmt(row['level'])}\n"
                f"BOS confirmed: {row['bos_confirmed']}\nOB: {fmt(row['ob_low'])} – {fmt(row['ob_high'])}\n"
                f"Entry status: {row['entry_status']}\nReference entry: {fmt(row['entry_price'])}\n"
                f"Reference stop: {fmt(row['stop_loss'])}\nTarget: {fmt(row['target_price'])}\n"
                f"Risk/reward: {fmt(row['risk_reward'])}\nTraded value TWD: {fmt(row['traded_value'])}\n"
                f"Signal ID: {row['signal_id']}\nTechnical reference, not a guaranteed outcome.")
        if len(text.encode("utf-16-le"))//2 > 5000:
            raise ValueError("CHOCH message exceeds LINE limit")
        messages.append(text); ids.append(row["signal_id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate signal IDs in displayed snapshot")
    return dict(messages=messages, signal_ids=ids, count=len(frame), fingerprint=snapshot_hash(frame))


def send_manual(preview, frame, path=DEFAULT_PATH, transport=None):
    if preview["fingerprint"] != snapshot_hash(frame) or preview["count"] != len(frame):
        raise ValueError("Analysis changed; review the new snapshot")
    if not len(frame):
        return dict(sent=0, failed=0)
    reserve(preview, path)
    transport = transport or send_text
    sent = failed = 0
    for ident, message in zip(preview["signal_ids"], preview["messages"]):
        try:
            outcome = transport(message, str(uuid.uuid5(uuid.NAMESPACE_URL, "smc-choch:"+ident)))
        except Exception:
            outcome = dict(ok=False, error="Delivery uncertain; no automatic retry")
        # Store only safe fixed text, never arbitrary provider exceptions/secrets.
        finish(ident, outcome["ok"], "LINE delivery failed or uncertain; manual review required", path)
        sent += int(outcome["ok"]); failed += int(not outcome["ok"])
    return dict(sent=sent, failed=failed)
