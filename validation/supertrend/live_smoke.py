"""Small live provider smoke check, no price-cache writes and no LINE calls."""
import json
from pathlib import Path
import pandas as pd
from services.taiwan_universe import fetch_taiwan_universe
from services.yahoo_history import download_histories


def main():
    universe,errors=fetch_taiwan_universe()
    symbols=[ticker for ticker in ('2330.TW','3293.TWO') if ticker in set(universe.ticker)]
    histories,failed=download_histories(symbols,period='1mo',actions=True,retries=1)
    report=dict(timestamp=pd.Timestamp.now(tz='Asia/Taipei').isoformat(),
                universe_total=len(universe),markets=universe.market.value_counts().to_dict(),
                universe_errors=errors,download_errors=failed,
                samples={t:dict(rows=len(f),first=str(f.index.min()),last=str(f.index.max()),columns=list(f.columns)) for t,f in histories.items()})
    Path('validation/supertrend/live_smoke.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
    print(json.dumps(report,indent=2,default=str))


if __name__=='__main__':main()
