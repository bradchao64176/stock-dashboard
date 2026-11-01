"""Run full live scans or explicitly labelled read-only cached coverage studies."""
import argparse
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import sqlite3
import pandas as pd
from strategies.supertrend_kd import SupertrendConfig
from services.supertrend_scanner import run_scan, evaluate_universe
from services.supertrend_data import EXISTING_CACHE, STRATEGY_CACHE, load_prices, request_start, cutoff_date


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--offline',action='store_true',help='Cached-symbol research only; does not claim full current exchange coverage')
    parser.add_argument('--timeframe',choices=['Daily'],default='Daily',help='Daily data only')
    parser.add_argument('--output',default='validation/supertrend')
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    paths=list(Path('data').glob('*.db'))
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    cfg=SupertrendConfig(timeframe=args.timeframe)
    def progress(done,total,label):
        if done%100==0 or done==total:print(f'{label}: {done}/{total}',flush=True)
    if args.offline:
        with closing(sqlite3.connect(EXISTING_CACHE.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            symbols=[r[0] for r in db.execute('SELECT DISTINCT ticker FROM daily_prices ORDER BY ticker')]
            latest=db.execute('SELECT MAX(date) FROM daily_prices').fetchone()[0]
            database_stats=db.execute('SELECT COUNT(*),COUNT(DISTINCT ticker),MIN(date),MAX(date) FROM daily_prices').fetchone()
            schema=db.execute('SELECT name,sql FROM sqlite_master').fetchall()
        now=pd.Timestamp(latest)+pd.Timedelta(hours=15)
        cutoff=cutoff_date(now)
        histories,errors,stats=load_prices(symbols,request_start(cfg,cutoff),cutoff+pd.Timedelta(days=1),offline=True)
        universe=pd.DataFrame([dict(ticker=t,stock_code=t.split('.')[0],stock_name='(cached symbol; name not loaded)',
                                    market='TPEx' if t.endswith('.TWO') else 'TWSE') for t in symbols])
        result=evaluate_universe(universe,histories,cfg,now,errors,progress)
        result.update(download_stats=stats,mode='OFFLINE cached symbols; not a live exchange-universe verification',database_stats=database_stats,schema=schema)
    else:
        result=run_scan(cfg,progress=progress);result['mode']='LIVE authoritative exchange universe + Yahoo'
    result['results'].to_csv(out/'matches.csv',index=False,encoding='utf-8-sig')
    result['audit'].to_csv(out/'audit.csv',index=False)
    report={key:result[key] for key in ['stats','download_stats','scan_time','mode']}
    report['config']=asdict(cfg)
    if args.offline:
        report.update(database_stats=result['database_stats'],schema=result['schema'])
    report['existing_databases_changed']=[p for p,h in before.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h and Path(p).resolve()!=STRATEGY_CACHE.resolve()]
    report['database_hashes_before']=before
    (out/'coverage.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['schema','database_hashes_before']},indent=2,default=str))


if __name__=='__main__':main()
