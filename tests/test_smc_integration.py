import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from unittest.mock import patch
import pandas as pd
from streamlit.testing.v1 import AppTest
from smc.data import read_histories, prepare_daily
from smc.scanner import scan, notification_snapshot
from smc.notifications import build_preview, send_manual
from smc.notification_repository import initialize, attempted_ids
from smc.order_blocks import find_order_block, retest_at
from smc.backtest import compare, execute
from smc.timeframes import weekly_bars
from smc.calendar import yahoo_session_calendar
from src.smc_choch_chart import smc_chart
from tests.test_smc_engine import fixture, CFG, CAL


def snapshot():
    data=fixture()
    asof=data.index[-1]+pd.Timedelta(hours=15)
    result=scan(pd.DataFrame([dict(ticker="2330.TW",stock_name="Test")]),{"2330.TW":data},CFG,CAL,asof)
    result.update(histories={"2330.TW":data},universe=pd.DataFrame([dict(ticker="2330.TW")]),calendar=CAL)
    return result


class SMCIntegrationTests(unittest.TestCase):
    def test_yahoo_session_alignment_preserves_holidays_and_stock_gaps(self):
        full=fixture().drop(fixture().index[2])
        other=full.drop(full.index[3])
        asof=full.index[-1]+pd.Timedelta(hours=15)
        calendar=yahoo_session_calendar({'A':full,'B':other},asof)
        complete=prepare_daily(full,asof,calendar)
        missing=prepare_daily(other,asof,calendar)
        self.assertTrue(complete.valid_bar.all())
        self.assertFalse(missing.valid_bar.loc[full.index[3]])
        self.assertNotIn(fixture().index[2],complete.index)

    def test_weekly_confirmation_never_executes_before_available(self):
        data=fixture()
        event=dict(signal_date=data.index[1],confirmed_at=data.index[4]+pd.Timedelta(hours=14),stop=1.,direction='BULLISH')
        result=execute(data,event,horizon=2)
        self.assertEqual(result['entry_date'],data.index[5])

    def test_default_scan_downloads_entire_universe_not_first_100(self):
        from src.smc_choch_panel import run_scan
        from unittest.mock import MagicMock
        universe=pd.DataFrame([dict(ticker=f'{1000+i}.TW' if i%2 else f'{1000+i}.TWO',
                                    stock_code=str(1000+i),stock_name='Test',market='TWSE' if i%2 else 'TPEx') for i in range(1200)])
        histories={t:fixture() for t in universe.ticker}
        fake=dict(results=pd.DataFrame(),details={},issues={},stocks_scanned=1200)
        with patch('src.smc_choch_panel.fetch_taiwan_universe',return_value=(universe,{})), \
             patch('src.smc_choch_panel.download_histories',return_value=(histories,{})) as download, \
             patch('src.smc_choch_panel.read_histories',side_effect=AssertionError('No cache substitution')), \
             patch('src.smc_choch_panel.scan',return_value=fake) as scanner, \
             patch('src.smc_choch_panel.st.progress',return_value=MagicMock()):
            result=run_scan(CFG)
        self.assertEqual(set(download.call_args.args[0]),set(universe.ticker))
        self.assertEqual(len(scanner.call_args.args[0]),1200)
        self.assertEqual(result['download_success'],1200)
        self.assertEqual(result['data_source'],'Yahoo Finance daily download')

    def test_all_stocks_ui_default(self):
        app=AppTest.from_string('from src.smc_choch_panel import render_smc_choch_panel\nrender_smc_choch_panel()')
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(next(v for v in app.number_input if v.label=='Maximum stocks (0 = all)').value,0)
        self.assertEqual(next(v for v in app.selectbox if v.label=='Market').value,'All')

    def test_combined_modes_only_return_confirmed_matches(self):
        data=fixture().iloc[:16]
        universe=pd.DataFrame([dict(ticker='2330.TW')])
        for cfg in (replace(CFG,bos_confirmation=True),replace(CFG,macd_confirmation=True)):
            self.assertTrue(scan(universe,{'2330.TW':data},cfg,CAL,data.index[-1]+pd.Timedelta(hours=15))['results'].empty)

    def test_scan_and_entry_are_independent_and_inputs_unchanged(self):
        data=fixture(); before=data.copy(deep=True)
        with patch("services.line_bot_service.send_text") as send, patch("yfinance.download",side_effect=AssertionError("No download")):
            result=scan(pd.DataFrame([dict(ticker="2330.TW")]),{"2330.TW":data},CFG,CAL,data.index[-1]+pd.Timedelta(hours=15))
            self.assertEqual(len(result['results']),1)
            send.assert_not_called()
        pd.testing.assert_frame_equal(data,before)
        self.assertEqual(result['results'].entry_status.iloc[0],"TRIGGERED")

    def test_readonly_cache_schema_and_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'prices.db'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE daily_prices(ticker TEXT,date TEXT,payload TEXT)')
                db.execute('INSERT INTO daily_prices VALUES(?,?,?)',('2330.TW','2026-01-05',json.dumps(dict(Open=1,High=2,Low=1,Close=2,Volume=100))))
                db.commit()
            before=path.read_bytes()
            frames=read_histories(path=path)
            self.assertEqual(len(frames['2330.TW']),1)
            self.assertEqual(before,path.read_bytes())

    def test_line_snapshot_preview_payload_and_duplicate_block(self):
        rows=notification_snapshot(snapshot()['results'])
        self.assertEqual(len(rows),1)
        preview=build_preview(rows)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'smc_choch.db'
            self.assertFalse(initialize(path)['exists'])
            self.assertFalse(path.exists())
            initialize(path,True)
            with patch('yfinance.download',side_effect=AssertionError('No Yahoo')), patch('smc.scanner.scan',side_effect=AssertionError('No scan')), patch('smc.notifications.send_text',return_value={'ok':True}) as send:
                result=send_manual(preview,rows,path)
                self.assertEqual(result['sent'],len(rows))
                self.assertEqual([c.args[0] for c in send.call_args_list],preview['messages'])
                with self.assertRaises(sqlite3.IntegrityError): send_manual(preview,rows,path)
                send.assert_called_once()
            self.assertEqual(attempted_ids(path),set(rows.signal_id))
            self.assertTrue(notification_snapshot(rows,attempted_ids(path)).empty)

    def test_uncertain_delivery_reserved_and_all_candidates_processed(self):
        rows=notification_snapshot(snapshot()['results'])
        rows=pd.concat([rows,rows.assign(signal_id='second',stock_code='5483',ticker='5483.TWO')],ignore_index=True)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'smc_choch.db'; initialize(path,True)
            with patch('smc.notifications.send_text',side_effect=[RuntimeError('secret'),{'ok':True}]) as send:
                result=send_manual(build_preview(rows),rows,path)
            self.assertEqual(result,dict(sent=1,failed=1))
            self.assertEqual(send.call_count,2)
            self.assertEqual(len(attempted_ids(path)),2)

    def test_stale_changed_or_historical_rows_not_delivered(self):
        rows=snapshot()['results']
        self.assertTrue(notification_snapshot(rows.assign(fresh=False)).empty)
        for status in ['WAIT','INVALIDATED']:
            self.assertTrue(notification_snapshot(rows.assign(entry_status=status)).empty)
        preview=build_preview(rows)
        with self.assertRaisesRegex(ValueError,'Analysis changed'):
            send_manual(preview,rows.assign(entry_price=0))

    def test_chart_shape_references_dates_and_overlays(self):
        result=snapshot(); row=result['results'].iloc[0].to_dict()
        fig=smc_chart(result['details']['2330.TW'],row,['HH/HL/LH/LL','CHOCH','BOS','Protected levels','Order block','Entry/Stop/Target'])
        self.assertEqual(fig.layout.hovermode,'x unified')
        self.assertEqual(fig.layout.xaxis.type,'date')
        for trace in fig.data:
            self.assertTrue((pd.DatetimeIndex(trace.x).year==2026).all())
        self.assertTrue(all(s.xref=='x domain' for s in fig.layout.shapes))
        self.assertTrue(fig.layout.yaxis.showspikes)

    def test_ui_load_does_not_scan_or_send_and_render_uses_snapshot(self):
        app=AppTest.from_string('from src.smc_choch_panel import render_smc_choch_panel\nrender_smc_choch_panel()')
        with patch('src.smc_choch_panel.run_scan') as runner,patch('smc.notifications.send_text') as send:
            app.run(); self.assertFalse(app.exception)
            runner.assert_not_called();send.assert_not_called()
            app.session_state.smc_choch_snapshot=snapshot()
            app.run(); self.assertFalse(app.exception)
            runner.assert_not_called();send.assert_not_called()
            pd.testing.assert_frame_equal(app.session_state.smc_choch_entry_results,snapshot()['results'])

    def test_missing_weekly_day_and_corporate_action_are_invalid(self):
        daily=prepare_daily(fixture().drop(fixture().index[2]),'2026-02-01',CAL)
        week=weekly_bars(daily,'2026-02-01',CAL)
        self.assertFalse(week.valid_bar.iloc[0])
        data=fixture();data['Stock Splits']=0.;data.loc[data.index[4],'Stock Splits']=2.
        daily=prepare_daily(data,'2026-02-01',CAL)
        self.assertFalse(daily.valid_bar.iloc[4])

    def test_order_block_retest_after_activation_only(self):
        data=fixture(); signal=snapshot()['details']['2330.TW']['structure']['events']
        event=next(e for e in signal if e['kind']=='CHOCH')
        zone=find_order_block(data,event)
        self.assertLess(zone['candle_date'],event['signal_date'])
        self.assertIsNone(retest_at(data.iloc[:13],event,zone))
        changed=data.copy(); changed.loc[changed.index[13],['Low','High','Close']]=[zone['low'],zone['high']+1,zone['high']+.5]
        self.assertEqual(retest_at(changed,event,zone),changed.index[13])

    def test_backtest_next_open_and_future_changes_cannot_change_entry(self):
        data=fixture()
        event=dict(signal_date=data.index[12],stop=6.,direction='BULLISH')
        result=execute(data,event,horizon=3)
        self.assertEqual(result['entry_date'],data.index[13])
        self.assertEqual(result['entry_price'],data.Open.iloc[13])
        self.assertIsNone(execute(data,dict(event,stop=100),horizon=3))
        report=compare(pd.DataFrame([dict(ticker='2330.TW')]),{'2330.TW':data},CFG,CAL,'2026-02-01')
        self.assertEqual(len(report['summary']),4)

    def test_signal_filters_not_shared_macd_ma_rules(self):
        result=snapshot()['results']
        self.assertEqual(len(result),1)  # Indicator warmup is incomplete; optional MACD off.
        data=fixture()
        strict=replace(CFG,min_traded_value=1e12)
        self.assertTrue(scan(pd.DataFrame([dict(ticker='2330.TW')]),{'2330.TW':data},strict,CAL,'2026-02-01')['results'].empty)
