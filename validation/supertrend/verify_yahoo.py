"""Verify Daily data using Yahoo prices, no production cache writes."""
import json
from pathlib import Path
import pandas as pd
from services.yahoo_history import download_histories
from services.supertrend_data import prepare_bars, cutoff_date, market_sessions, request_start
from services.supertrend_scanner import evaluate_universe
from strategies.supertrend_kd import SupertrendConfig, calculate_indicators


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--saved',action='store_true')
    saved=parser.parse_args().saved
    out=Path('validation/supertrend/yahoo');out.mkdir(parents=True,exist_ok=True)
    now=pd.Timestamp.now(tz='Asia/Taipei');cutoff=cutoff_date(now)
    if saved:
        histories={t:pd.read_csv(out/(t+'.csv'),index_col=0,parse_dates=True) for t in ['2330.TW','3293.TWO']};errors={}
    else:
        histories,errors=download_histories(['2330.TW','3293.TWO'],start=str(request_start(SupertrendConfig(),cutoff).date()),
             end=str((cutoff+pd.Timedelta(days=1)).date()),actions=True,retries=1)
    sessions,no_trade=market_sessions(histories,cutoff)
    reports=[]
    for ticker,raw in histories.items():
        raw.to_csv(out/(ticker+'.csv'))
        daily=prepare_bars(raw,sessions,cutoff)
        stock=pd.DataFrame([dict(ticker=ticker,stock_code=ticker.split('.')[0],stock_name='TSMC' if ticker=='2330.TW' else 'International Games System',market='TWSE' if ticker.endswith('.TW') else 'TPEx')])
        result=evaluate_universe(stock,histories,SupertrendConfig(),now)
        calculated=calculate_indicators(daily,SupertrendConfig())
        calculated.to_csv(out/(ticker+'_Daily_indicators.csv'))
        reports.append(dict(ticker=ticker,timeframe='Daily',daily_rows=len(daily),
                            first_date=str(daily.index.min()),latest_date=str(daily.index.max()),
                            stats=result['stats'],audit=result['audit'].to_dict('records'),
                            latest=calculated.iloc[-1].to_dict()))
    payload=dict(verified_at=now.isoformat(),source='Yahoo daily downloads, auto_adjust=False',
                 reuses_saved_yahoo_downloads=saved,yahoo_no_trade_dates=[str(d.date()) for d in no_trade],
                 errors=errors,results=reports)
    (out/'verification.json').write_text(json.dumps(payload,indent=2,default=str),encoding='utf-8')
    print(json.dumps(payload,indent=2,default=str))
    if len(histories)!=2:
        raise SystemExit('Yahoo verification incomplete: missing requested histories')


if __name__=='__main__':main()
