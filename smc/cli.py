import argparse
from dataclasses import replace
from pathlib import Path
import pandas as pd
from .config import SMCConfig
from .data import read_histories, completed_cutoff
from .calendar import yahoo_session_calendar
from services.yahoo_history import download_histories
from services.taiwan_universe import fetch_taiwan_universe
from .backtest import compare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols",default="",help="Blank scans all TWSE/TPEx common stocks; explicit list is optional")
    parser.add_argument("--output",default="validation/smc_choch")
    parser.add_argument("--asof",default=None)
    parser.add_argument("--calendar-csv",help="Offline official closure dates CSV, column date")
    parser.add_argument("--cache-only",action="store_true",help="Explicit offline research mode; default downloads Yahoo daily prices")
    args=parser.parse_args()
    symbols=[symbol.strip() for symbol in args.symbols.split(',') if symbol.strip()]
    histories=read_histories(symbols or None) if args.cache_only else {}
    asof=pd.Timestamp(args.asof) if args.asof else pd.Timestamp.now(tz="Asia/Taipei")
    if not args.cache_only:
        if not symbols:
            universe, roster_errors=fetch_taiwan_universe()
            print('Universe issues:',roster_errors)
            symbols=universe.ticker.tolist()
        downloaded, errors=download_histories(symbols,start=(asof-pd.DateOffset(years=4)).date().isoformat(),
                                              end=(completed_cutoff(asof)+pd.Timedelta(days=1)).date().isoformat(),actions=True)
        histories=downloaded
        print('Yahoo download issues:', errors)
    if not histories:
        raise ValueError('No Yahoo daily histories available')
    first=min(frame.index.min().year for frame in histories.values())-1
    if args.calendar_csv:
        from .calendar import TradingCalendar
        closed=pd.to_datetime(pd.read_csv(args.calendar_csv).date)
        calendar=TradingCalendar(frozenset(range(first,asof.year+1)),frozenset(closed))
    else:
        calendar=yahoo_session_calendar(histories,asof)
    result=compare(pd.DataFrame({"ticker":list(histories)}),histories,SMCConfig(),calendar,asof,
                   progress=lambda done,total: print(f'Comparison {done}/{total}',flush=True) if done==1 or done%100==0 else None)
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    result["summary"].to_csv(out/'comparison.csv',index=False)
    result["trades"].to_csv(out/'trades.csv',index=False)
    (out/'assumptions.txt').write_text(result["assumptions"]+'\n'+str(result['errors']),encoding='utf-8')
    print(result['summary'].to_string(index=False))


if __name__=="__main__":
    main()
