import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch
import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest
from strategies.supertrend_kd import SupertrendConfig, calculate_indicators, seeded_average
from services.supertrend_data import load_prices, prepare_bars, request_start, cutoff_date, market_sessions
from services.supertrend_scanner import evaluate_universe, run_scan
from services.supertrend_line import preview, send_manual
from src.supertrend_panel import chart
from services.taiwan_universe import normalize_companies


def bars(n=320):
    x=np.arange(n)
    close=100+x*.25+4*np.sin(x*.6)
    frame=pd.DataFrame(dict(Open=close-.1,High=close+1,Low=close-1,Close=close,Volume=np.full(n,2_000_000.)),
                       index=pd.bdate_range('2024-01-01',periods=n))
    frame['valid_bar']=True
    frame['trading_value']=frame.Close*frame.Volume
    frame['available_at']=frame.index+pd.Timedelta(hours=14)
    return frame


CFG=SupertrendConfig(ema_period=20,warmup=5,atr_period=5,multiplier=4,kd_period=5,k_smoothing=3,d_smoothing=3,kd_ceiling=100)


def matching_bars():
    data=bars()
    calculated=calculate_indicators(data,CFG)
    hits=np.flatnonzero(calculated.BUY.to_numpy())
    assert len(hits), 'Fixture must contain BUY events'
    return data.iloc[:hits[-1]+1].copy()


def universe(n=2):
    return pd.DataFrame([dict(ticker=f'{2000+i}.TW' if i%2==0 else f'{2000+i}.TWO',stock_code=str(2000+i),
                             stock_name=f'Stock{i}',market='TWSE' if i%2==0 else 'TPEx',security_type='common_stock') for i in range(n)])


def seed_db(path,frame,ticker='2000.TW'):
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE daily_prices(ticker TEXT,date TEXT,payload TEXT,PRIMARY KEY(ticker,date))')
        db.executemany('INSERT INTO daily_prices VALUES (?,?,?)',[(ticker,str(day.date()),row.to_json()) for day,row in frame.iterrows()])
        db.commit()


class IndicatorTests(unittest.TestCase):
    def test_ema_filter_disabled_skips_only_price_condition(self):
        data=matching_bars()
        data.loc[data.index[:200],['Open','High','Low','Close']]*=3
        cfg=replace(CFG,ema_period=200)
        enabled=calculate_indicators(data,cfg)
        disabled=calculate_indicators(data,replace(cfg,ema_enabled=False))
        self.assertLess(data.Close.iloc[-1],enabled.EMA.iloc[-1])
        self.assertFalse(enabled.ema_ok.iloc[-1]);self.assertFalse(enabled.BUY.iloc[-1])
        self.assertTrue(disabled.ema_ok.all());self.assertTrue(disabled.BUY.iloc[-1])
        for column in ('EMA','Supertrend','K','D','kd_ok','value_ok','deviation_ok'):
            pd.testing.assert_series_equal(enabled[column],disabled[column])

    def test_disabled_ema_does_not_require_ema_history(self):
        cfg=replace(CFG,ema_period=500,ema_enabled=False)
        self.assertEqual(cfg.required_bars,17)
        out=calculate_indicators(bars(80),cfg)
        self.assertTrue(out.EMA.isna().all());self.assertTrue(out.ready.iloc[-1])
        self.assertTrue(out.ema_ok.all())

    def test_custom_ema_period_and_default_enabled(self):
        self.assertTrue(SupertrendConfig().ema_enabled)
        self.assertEqual(SupertrendConfig().ema_period,200)
        data=bars(80)
        out=calculate_indicators(data,replace(CFG,ema_period=10))
        self.assertAlmostEqual(out.EMA.iloc[9],data.Close.iloc[:10].mean())
        pd.testing.assert_series_equal(out.ema_ok,(out.Close>out.EMA).rename('ema_ok'))

    def test_ema_and_wilder_seed(self):
        np.testing.assert_allclose(seeded_average([1,2,3,4,5],3,.5),[np.nan,np.nan,2,3,4],equal_nan=True)
        np.testing.assert_allclose(seeded_average([1,2,3,4],3,1/3),[np.nan,np.nan,2,8/3],equal_nan=True)

    def test_kd_formula_and_confirmed_transition(self):
        data=bars(50); out=calculate_indicators(data,CFG)
        k=d=50.
        for i in range(CFG.kd_period-1,len(data)):
            window=data.iloc[i-CFG.kd_period+1:i+1]
            rsv=100*(data.Close.iloc[i]-window.Low.min())/(window.High.max()-window.Low.min())
            k=(2*k+rsv)/3; d=(2*d+k)/3
            self.assertAlmostEqual(out.K.iloc[i],k);self.assertAlmostEqual(out.D.iloc[i],d)
        self.assertTrue(((out.K>out.D)&~out.kd_cross).any())
        for i in np.flatnonzero(out.kd_cross):
            self.assertGreater(out.K.iloc[i],out.D.iloc[i])
            self.assertLessEqual(out.K.iloc[i-1],out.D.iloc[i-1])

    def test_supertrend_bands_and_atr(self):
        data=bars(80); out=calculate_indicators(data,CFG)
        tr=np.maximum(data.High-data.Low,np.maximum(abs(data.High-data.Close.shift()),abs(data.Low-data.Close.shift())))
        tr.iloc[0]=data.High.iloc[0]-data.Low.iloc[0]
        self.assertAlmostEqual(out.ATR.iloc[4],tr.iloc[:5].mean())
        self.assertTrue(out.loc[out.supertrend_bullish,'Close'].ge(out.loc[out.supertrend_bullish,'Supertrend']).all())
        self.assertTrue(out.loc[out.ATR.notna()&~out.supertrend_bullish,'Close'].le(out.loc[out.ATR.notna()&~out.supertrend_bullish,'Supertrend']).all())

    def test_deviation_configurable(self):
        data=matching_bars(); out=calculate_indicators(data,CFG)
        self.assertTrue(out.BUY.iloc[-1])
        self.assertAlmostEqual(out.deviation_pct.iloc[-1],100*(data.Close.iloc[-1]/out.Supertrend.iloc[-1]-1))
        self.assertFalse(calculate_indicators(data,replace(CFG,deviation_max=0)).BUY.iloc[-1])
        self.assertTrue(calculate_indicators(data,replace(CFG,deviation_max=0,deviation_enabled=False)).BUY.iloc[-1])

    def test_liquidity_threshold_and_missing(self):
        data=matching_bars();data.loc[data.index[-1],'trading_value']=100_000_000
        self.assertTrue(calculate_indicators(data,CFG).BUY.iloc[-1])
        data.loc[data.index[-1],'trading_value']=99_999_999
        self.assertFalse(calculate_indicators(data,CFG).BUY.iloc[-1])
        data.loc[data.index[-1],'trading_value']=np.nan
        self.assertFalse(calculate_indicators(data,CFG).BUY.iloc[-1])
        self.assertTrue(calculate_indicators(data,replace(CFG,value_enabled=False)).BUY.iloc[-1])

    def test_ceiling_applies_to_both(self):
        data=matching_bars();out=calculate_indicators(data,CFG)
        self.assertFalse(calculate_indicators(data,replace(CFG,kd_ceiling=float(out.K.iloc[-1]))).BUY.iloc[-1])
        self.assertFalse(calculate_indicators(data,replace(CFG,kd_ceiling=float(out.D.iloc[-1]))).BUY.iloc[-1])

    def test_prefix_stability_and_input_immutable(self):
        data=bars(); before=data.copy(deep=True); full=calculate_indicators(data,CFG)
        for n in (35,60,100,200):
            pd.testing.assert_frame_equal(calculate_indicators(data.iloc[:n],CFG),full.iloc[:n])
        pd.testing.assert_frame_equal(data,before)

    def test_invalid_and_flat_bars(self):
        data=bars();data.loc[data.index[-2],'valid_bar']=False
        out=calculate_indicators(data,CFG)
        self.assertFalse(out.ready.iloc[-1]);self.assertFalse(out.BUY.iloc[-1])
        data[['High','Low','Close']]=100.
        self.assertTrue(calculate_indicators(data,CFG).K.isna().all())

    def test_only_daily_configuration_accepted(self):
        for mode in ('Weekly','Dual'):
            with self.assertRaisesRegex(ValueError,'Daily data only'):
                SupertrendConfig(timeframe=mode)

    def test_daily_history_requirement(self):
        cfg=SupertrendConfig();cut=pd.Timestamp('2026-10-23')
        self.assertEqual(cfg.required_bars,250)
        self.assertEqual((cut-request_start(cfg,cut)).days,515)
        self.assertEqual(cutoff_date('2026-10-23 10:00'),pd.Timestamp('2026-10-22'))
        with self.assertRaises(ValueError):SupertrendConfig(deviation_min=11,deviation_max=10)


class DataAndScannerTests(unittest.TestCase):
    def test_split_adjusted_yahoo_history_keeps_warmup(self):
        data=bars();data['Stock Splits']=0.;data.loc[data.index[-3],'Stock Splits']=2.
        prepared=prepare_bars(data,data.index,data.index[-1])
        self.assertTrue(prepared.valid_bar.all())
        self.assertTrue(calculate_indicators(prepared,SupertrendConfig()).ready.iloc[-1])
        data.loc[data.index[-3],['Open','High','Low','Close']]/=2
        self.assertFalse(prepare_bars(data,data.index,data.index[-1]).valid_bar.iloc[-3])

    def test_marketwide_yahoo_placeholder_not_a_trading_candle(self):
        data=bars();last=data.index[-1]
        data.loc[last,['Open','High','Low','Close']]=100.;data.loc[last,'Volume']=0
        sessions,no_trade=market_sessions({'A':data,'B':data.copy()},last)
        self.assertNotIn(last,sessions);self.assertIn(last,no_trade)
        clean=prepare_bars(data,sessions,last)
        self.assertTrue(clean.valid_bar.all())
        other=bars();sessions,no_trade=market_sessions({'A':data,'B':other},last)
        self.assertIn(last,sessions);self.assertNotIn(last,no_trade)
        self.assertFalse(prepare_bars(data,sessions,last).valid_bar.iloc[-1])
        _,no_trade=market_sessions({'A':data},last)
        self.assertFalse(len(no_trade))

    def test_cache_reuse_incremental_and_no_overwrite(self):
        data=bars(30).drop(columns=['available_at','valid_bar','trading_value'])
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'original.db';cache=Path(tmp)/'new.db';seed_db(base,data.iloc[5:25])
            digest=hashlib.sha256(base.read_bytes()).hexdigest();calls=[]
            def downloader(tickers,**kwargs):
                calls.append(kwargs)
                return {'2000.TW':data.loc[(data.index>=kwargs['start'])&(data.index<kwargs['end'])]},{}
            args=dict(existing_path=base,cache_path=cache,downloader=downloader)
            histories,errors,stats=load_prices(['2000.TW'],data.index[0],data.index[-1]+pd.Timedelta(days=1),**args)
            self.assertEqual(len(histories['2000.TW']),30);self.assertFalse(errors);self.assertEqual(len(calls),2)
            self.assertEqual(hashlib.sha256(base.read_bytes()).hexdigest(),digest)
            calls.clear();load_prices(['2000.TW'],data.index[0],data.index[-1]+pd.Timedelta(days=1),**args)
            self.assertFalse(calls)

    def test_empty_refresh_preserves_cache(self):
        data=bars(30).drop(columns=['available_at','valid_bar','trading_value'])
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'base.db';seed_db(base,data)
            digest=hashlib.sha256(base.read_bytes()).hexdigest()
            histories,errors,_=load_prices(['2000.TW'],data.index[0],data.index[-1]+pd.Timedelta(days=3),existing_path=base,
                cache_path=Path(tmp)/'new.db',downloader=lambda *a,**k:({}, {'2000.TW':'rate limit'}))
            self.assertEqual(len(histories['2000.TW']),30);self.assertIn('2000.TW',errors)
            self.assertEqual(hashlib.sha256(base.read_bytes()).hexdigest(),digest)

    def test_adjustment_conflict_fails_closed(self):
        data=bars(30).drop(columns=['available_at','valid_bar','trading_value'])
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'base.db';seed_db(base,data.iloc[:-2]);fresh=data.copy();fresh.Close*=2
            history,errors,_=load_prices(['2000.TW'],data.index[0],data.index[-1]+pd.Timedelta(days=1),existing_path=base,
                cache_path=Path(tmp)/'new.db',downloader=lambda *a,**k:({'2000.TW':fresh},{}))
            self.assertIn('DATA_CONSISTENCY_ERROR',errors['2000.TW']);self.assertEqual(len(history['2000.TW']),28)

    def test_full_roster_not_other_candidates(self):
        all_stocks=universe(1200);seen=[]
        def loader(tickers,*args,**kwargs):
            seen.extend(tickers);return {},{},{}
        with patch('services.scanner_entry_service.analyze_scanner_candidates',side_effect=AssertionError('Forbidden')):
            result=run_scan(CFG,universe_fetcher=lambda:(all_stocks,{}),price_loader=loader)
        self.assertEqual(seen,all_stocks.ticker.tolist());self.assertEqual(result['stats']['total_eligible'],1200)
        self.assertEqual(result['stats']['errors'],1200)

    def test_exchange_suffix_and_selection(self):
        roster=[{'公司代號':'2330','公司簡稱':'Test'},{'公司代號':'0050','公司簡稱':'ETF'},{'公司代號':'1234A','公司簡稱':'Preferred'}]
        self.assertEqual(normalize_companies(roster,'TWSE').ticker.tolist(),['2330.TW'])
        self.assertEqual(normalize_companies(roster,'TPEx').ticker.tolist(),['2330.TWO'])
        seen=[]
        result=run_scan(CFG,('TPEx',),universe_fetcher=lambda:(universe(),{}),price_loader=lambda ts,*a,**k:(seen.extend(ts) or {},{},{}))
        self.assertEqual(seen,['2001.TWO'])

    def test_errors_insufficient_and_matches_isolated(self):
        data=matching_bars();u=universe(4)
        histories={u.ticker[0]:data,u.ticker[1]:bars(3),u.ticker[2]:pd.DataFrame({'Close':[1]})}
        result=evaluate_universe(u,histories,CFG,data.index[-1]+pd.Timedelta(hours=15))
        self.assertEqual(result['stats']['matched'],1);self.assertEqual(result['stats']['insufficient'],1 if bars(3).index[-1]==data.index[-1] else 0)
        self.assertEqual(result['stats']['errors'],2);self.assertEqual(result['results'].ticker.tolist(),[u.ticker[0]])

    def test_recent_listing_daily_short_history(self):
        data=bars(249)
        result=evaluate_universe(universe(1),{'2000.TW':data},SupertrendConfig(),data.index[-1]+pd.Timedelta(hours=15))
        self.assertEqual(result['stats']['insufficient'],1)

    def test_daily_ema_has_200_days_plus_warmup(self):
        data=bars(280)
        out=calculate_indicators(data,SupertrendConfig())
        self.assertFalse(out.ready.iloc[248]);self.assertTrue(out.ready.iloc[249])
        self.assertAlmostEqual(out.EMA.iloc[199],data.Close.iloc[:200].mean())

    def test_entry_timing_is_only_downstream(self):
        from services.supertrend_scanner import entry_analysis
        data=matching_bars()
        with patch('services.entry_timing_service.calculate_entry_analysis') as analyzer:
            result=evaluate_universe(universe(1),{'2000.TW':data},CFG,data.index[-1]+pd.Timedelta(hours=15))
            analyzer.assert_not_called()
            before=result['results'].copy(deep=True);analyzer.return_value={'entry_status':'WATCH'}
            analysis=entry_analysis(result);analyzer.assert_called_once()
            self.assertEqual(len(analysis),1);pd.testing.assert_frame_equal(before,result['results'])

    def test_stale_and_missing_sessions(self):
        data=bars();prepared=prepare_bars(data.drop(data.index[-2]),data.index,data.index[-1])
        self.assertFalse(prepared.valid_bar.iloc[-2])
        result=evaluate_universe(universe(1),{'2000.TW':data},CFG,data.index[-1]+pd.Timedelta(days=7,hours=15))
        self.assertEqual(result['stats']['stale'],1);self.assertTrue(result['results'].empty)


class InterfaceTests(unittest.TestCase):
    def test_ema_controls_reach_scan_configuration(self):
        app=AppTest.from_string('from src.supertrend_panel import render_supertrend_panel\nrender_supertrend_panel()')
        with patch('src.supertrend_panel.run_scan',return_value=self.snapshot()) as runner:
            app.run()
            checkbox=next(c for c in app.checkbox if c.label=='Enable EMA Filter')
            period=next(n for n in app.number_input if n.label=='EMA period')
            self.assertTrue(checkbox.value);self.assertEqual(period.value,200)
            checkbox.uncheck();period.set_value(50)
            next(b for b in app.button if b.label=='Scan all eligible stocks').click().run()
            self.assertFalse(app.exception)
            cfg=runner.call_args.args[0]
            self.assertFalse(cfg.ema_enabled);self.assertEqual(cfg.ema_period,50)

    def test_non_daily_saved_snapshot_cleared(self):
        app=AppTest.from_string('from src.supertrend_panel import render_supertrend_panel\nrender_supertrend_panel()')
        snapshot=self.snapshot();snapshot['config']['timeframe']='Weekly'
        app.session_state['supertrend_ema_kd_snapshot']=snapshot
        with patch('src.supertrend_panel.run_scan') as scan,patch('src.supertrend_panel.send_manual') as send:
            app.run();self.assertFalse(app.exception)
            self.assertFalse(any(s.label=='Timeframe' for s in app.selectbox))
            self.assertFalse(any(b.key=='supertrend_ema_kd_line_send' for b in app.button))
            self.assertNotIn('supertrend_ema_kd_snapshot',app.session_state)
            scan.assert_not_called();send.assert_not_called()

    def snapshot(self):
        data=matching_bars()
        return evaluate_universe(universe(1),{'2000.TW':data},CFG,data.index[-1]+pd.Timedelta(hours=15))

    def test_chart_dates_and_crosshair(self):
        data=calculate_indicators(bars(),CFG);fig=chart(data)
        self.assertEqual(fig.layout.hovermode,'x unified');self.assertTrue(fig.layout.xaxis.showspikes)
        self.assertTrue(fig.layout.yaxis.showspikes)
        for trace in fig.data:
            self.assertTrue(all(pd.Timestamp(x).year>=2024 for x in trace.x))

    def test_preview_send_exact_and_duplicate_prevention(self):
        snapshot=self.snapshot();frame=snapshot['results'];packet=preview(frame);sent=[]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'notify.db'
            outcome=send_manual(packet,frame,path,lambda text,key:sent.append(text) or {'ok':True})
            self.assertEqual(sent,packet['messages']);self.assertEqual(outcome['sent'],len(frame))
            with self.assertRaises(ValueError):send_manual(packet,frame,path,lambda *a:self.fail('Duplicate'))
            modified=frame.copy();modified['current_price']+=1
            with self.assertRaises(ValueError):send_manual(packet,modified,path)

    def test_failed_line_not_sent(self):
        frame=self.snapshot()['results']
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'notify.db';out=send_manual(preview(frame),frame,path,lambda *a:{'ok':False})
            self.assertEqual(out['sent'],0)
            with closing(sqlite3.connect(path)) as db:self.assertEqual(db.execute('SELECT status FROM supertrend_notifications').fetchone()[0],'UNCERTAIN')

    def test_page_load_and_rerun_never_scan_or_send(self):
        app=AppTest.from_string('from src.supertrend_panel import render_supertrend_panel\nrender_supertrend_panel()')
        with patch('src.supertrend_panel.run_scan') as scan,patch('src.supertrend_panel.send_manual') as send:
            app.run();self.assertFalse(app.exception)
            self.assertTrue(app.checkbox[0].value);self.assertTrue(app.checkbox[1].value)
            app.session_state['supertrend_ema_kd_snapshot']=self.snapshot();app.run()
            self.assertFalse(app.exception);scan.assert_not_called();send.assert_not_called()
            button=next(b for b in app.button if b.key=='supertrend_ema_kd_line_send')
            send.return_value={'sent':1,'failed':0};button.click().run()
            self.assertFalse(app.exception);scan.assert_not_called();send.assert_called_once()


if __name__=='__main__':unittest.main()
