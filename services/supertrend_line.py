"""Manual-only delivery for an exact Supertrend snapshot; isolated reservations."""
from contextlib import closing
from pathlib import Path
import hashlib
import sqlite3
import uuid
from services.line_bot_service import send_text
from services.supertrend_data import STRATEGY_CACHE


def fingerprint(frame):
    return hashlib.sha256(frame.to_json(date_format='iso').encode()).hexdigest()


def preview(frame):
    messages=[]
    for row in frame.to_dict('records'):
        messages.append(f"Stock Dashboard\nSupertrend + EMA200 + KD\n{row['stock_code']} {str(row['stock_name'])[:80]}\n"
            f"{row['timeframe']} BUY | {row['signal_date']}\nPrice: {row['current_price']:.2f}\n"
            f"EMA: {row['ema']:.2f}\nSupertrend: {row['supertrend']:.2f}\nDeviation: {row['deviation_pct']:.2f}%\n"
            f"K: {row['K']:.2f} D: {row['D']:.2f}\nTraded value: NT${row['trading_value']:,.0f}\n"
            f"Signal ID: {row['signal_id']}\nTechnical signal, not a guaranteed outcome.")
    return dict(messages=messages,ids=frame.get('signal_id',[]).tolist() if len(frame) else [],fingerprint=fingerprint(frame))


def send_manual(packet, frame, path=STRATEGY_CACHE, transport=None):
    if packet['fingerprint']!=fingerprint(frame) or len(packet['messages'])!=len(frame):
        raise ValueError('Displayed snapshot changed')
    if not len(frame):
        return dict(sent=0,failed=0)
    if len(set(packet['ids']))!=len(frame):
        raise ValueError('Duplicate signal in snapshot')
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(str(path),timeout=30)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS supertrend_notifications(signal_id TEXT PRIMARY KEY,status TEXT,attempted_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        # Reserve the entire preview atomically; retries/reruns cannot duplicate delivery.
        db.execute('BEGIN IMMEDIATE')
        try:
            db.executemany('INSERT INTO supertrend_notifications(signal_id,status) VALUES (?,?)',[(v,'PENDING') for v in packet['ids']])
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            raise ValueError('One or more signals were already sent or reserved; no messages sent')
        sent=failed=0
        for ident,message in zip(packet['ids'],packet['messages']):
            try:
                ok=bool((transport or send_text)(message,str(uuid.uuid5(uuid.NAMESPACE_URL,'supertrend:'+ident))).get('ok'))
            except Exception:
                ok=False
            db.execute('UPDATE supertrend_notifications SET status=? WHERE signal_id=?',('SENT' if ok else 'UNCERTAIN',ident)); db.commit()
            sent+=int(ok); failed+=int(not ok)
    return dict(sent=sent,failed=failed)
