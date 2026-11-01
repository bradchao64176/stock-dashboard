"""Full security-master scan, independent of all existing candidate lists."""
from dataclasses import asdict
import hashlib
import pandas as pd
from services.taiwan_universe import fetch_taiwan_universe
from services.supertrend_data import load_prices, prepare_bars, cutoff_date, request_start, market_sessions
from strategies.supertrend_kd import SupertrendConfig, STRATEGY_ID, calculate_indicators


def evaluate_universe(universe, histories, config, asof, data_errors=None, progress=None):
    cutoff=cutoff_date(asof)
    sessions,no_trade=market_sessions(histories,cutoff)
    expected_days=pd.bdate_range(end=cutoff,periods=31).difference(no_trade)
    expected=expected_days[-1] if len(expected_days) else cutoff
    rows,details,audits,entry_histories=[],{},[],{}
    for number,stock in enumerate(universe.to_dict('records'),1):
        ticker=stock['ticker']; status='ERROR'; reason=''; detail=None
        try:
            if (data_errors or {}).get(ticker,'').startswith('DATA_CONSISTENCY_ERROR'):
                raise ValueError(data_errors[ticker])
            if ticker not in histories:
                raise ValueError((data_errors or {}).get(ticker,'No downloaded or cached history'))
            daily=prepare_bars(histories[ticker],sessions,cutoff)
            if daily.index[-1] < expected:
                status,reason='STALE','Latest data precedes expected completed weekday; suspended/holiday/provider delay'
            else:
                if len(daily)<config.required_bars:
                    status,reason='INSUFFICIENT',f'Requires {config.required_bars} completed daily bars'
                else:
                    calculated=calculate_indicators(daily,config)
                    if not bool(calculated.ready.iloc[-1]):
                        status,reason='INSUFFICIENT','Invalid, missing or split-action bars interrupted indicator warm-up'
                    else:
                        bar=calculated.iloc[-1]
                        status='MATCH' if bool(bar.BUY) else 'EXCLUDED'
                        checks=['trend_ok','deviation_ok','kd_ok','value_ok']
                        reason='; '.join(k for k in checks if not bool(bar[k])) or 'All configured conditions passed'
                        if status=='MATCH':
                            day=calculated.index[-1]
                            ident=hashlib.sha256(f'{STRATEGY_ID}|{ticker}|{config.timeframe}|{day.date()}'.encode()).hexdigest()
                            row=dict(stock, strategy_id=STRATEGY_ID, signal_id=ident, timeframe=config.timeframe,
                                     signal_date=day, current_price=float(bar.Close), ema=float(bar.EMA),
                                     supertrend=float(bar.Supertrend), supertrend_bullish=bool(bar.supertrend_bullish),
                                     deviation_pct=float(bar.deviation_pct), K=float(bar.K), D=float(bar.D),
                                     previous_K=float(calculated.K.iloc[-2]),previous_D=float(calculated.D.iloc[-2]),
                                     kd_cross=bool(bar.kd_cross), trading_value=float(bar.trading_value),
                                     Volume=float(bar.Volume), signal='BUY')
                            rows.append(row); details[ticker]=calculated
                            # Entry Timing is optional downstream daily analysis, never a universe/filter input.
                            entry_histories[ticker]=daily
        except Exception as error:
            status,reason='ERROR',f'{type(error).__name__}: {error}'
        audits.append(dict(ticker=ticker,status=status,reason=reason))
        if progress:
            progress(number,len(universe),'Evaluating strategy')
    audit=pd.DataFrame(audits,columns=['ticker','status','reason'])
    counts=audit.status.value_counts()
    stats=dict(total_eligible=len(universe),processed=len(audit),evaluated=int(counts.get('MATCH',0)+counts.get('EXCLUDED',0)),
               matched=int(counts.get('MATCH',0)),excluded=int(counts.get('EXCLUDED',0)),
               insufficient=int(counts.get('INSUFFICIENT',0)),stale=int(counts.get('STALE',0)),errors=int(counts.get('ERROR',0)))
    return dict(results=pd.DataFrame(rows),details=details,entry_histories=entry_histories,audit=audit,stats=stats,
                config=asdict(config),scan_time=pd.Timestamp(asof).isoformat(),
                expected_session=str(expected.date()),yahoo_no_trade_dates=[str(d.date()) for d in no_trade])


def run_scan(config=SupertrendConfig(), exchanges=('TWSE','TPEx'), asof=None, progress=None,
             universe_fetcher=None, price_loader=None):
    if not exchanges or not set(exchanges).issubset({'TWSE','TPEx'}):
        raise ValueError('Select TWSE and/or TPEx')
    now=pd.Timestamp.now(tz='Asia/Taipei') if asof is None else pd.Timestamp(asof)
    universe,roster_errors=(universe_fetcher or fetch_taiwan_universe)()
    universe=universe.loc[universe.market.isin(exchanges)].drop_duplicates('ticker').copy()
    if universe.empty:
        raise ValueError('No eligible common stocks available from the exchange security master')
    cutoff=cutoff_date(now)
    histories,errors,download_stats=(price_loader or load_prices)(universe.ticker.tolist(),request_start(config,cutoff),
                              cutoff+pd.Timedelta(days=1),progress=progress)
    result=evaluate_universe(universe,histories,config,now,errors,progress)
    result.update(universe=universe,universe_errors={k:v for k,v in roster_errors.items() if k in exchanges},
                  data_errors=errors,download_stats=download_stats)
    return result


def entry_analysis(snapshot):
    """Optional consumer of qualified results. No I/O and no change to matches."""
    from services.entry_timing_service import calculate_entry_analysis
    rows=[]
    for source in snapshot['results'].to_dict('records'):
        history=snapshot['entry_histories'][source['ticker']]
        candidate=dict(source)
        # Never invent a signal candle absent from the saved daily history.
        if candidate['signal_date'] not in history.index:
            candidate['signal_date']=None
        row=calculate_entry_analysis(candidate,history,candidate_kind='SIGNAL')
        row.update(signal_id=source['signal_id'],strategy_id=STRATEGY_ID,trading_value=source['trading_value'])
        rows.append(row)
    return pd.DataFrame(rows)
