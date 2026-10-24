"""Isolated Streamlit control/result page. Market IO occurs only on Scan."""
from dataclasses import asdict, replace
import pandas as pd
import streamlit as st
from services.taiwan_universe import fetch_taiwan_universe
from services.yahoo_history import download_histories
from smc.config import SMCConfig
from smc.data import read_histories, completed_cutoff
from smc.calendar import yahoo_session_calendar
from smc.scanner import scan, notification_snapshot
from smc.notifications import build_preview, send_manual
from smc.notification_repository import attempted_ids, DEFAULT_PATH
from src.smc_choch_chart import smc_chart


def run_scan(config, codes="", market="All", limit=0, refresh=True, extra_closed=()):
    now = pd.Timestamp.now(tz="Asia/Taipei")
    universe, universe_errors = fetch_taiwan_universe()
    if universe.empty:
        raise ValueError("Taiwan company roster unavailable; cannot enumerate all stocks")
    if market != "All":
        universe = universe.loc[universe.market.eq(market)]
    selected = {v.strip() for v in codes.split(',') if v.strip()}
    if selected:
        universe = universe.loc[universe.ticker.isin(selected) | universe.stock_code.astype(str).isin(selected)]
    universe = universe.sort_values("ticker")
    if limit:
        universe = universe.head(limit)
    if universe.empty:
        raise ValueError("No symbols match the selected universe")
    histories = {}
    errors = {}
    if refresh:
        # Explicit user request, unchanged shared downloader; never call cache-writing loaders.
        start = (now-pd.DateOffset(years=4)).date().isoformat()
        end = (completed_cutoff(now)+pd.Timedelta(days=1)).date().isoformat()
        download_progress = st.progress(0.,text="Downloading Yahoo Finance daily prices")
        try:
            histories, errors = download_histories(universe.ticker.tolist(), start=start, end=end, actions=True,
                progress=lambda done,total: download_progress.progress(done/total,text=f"Yahoo {done}/{total}"))
        finally:
            download_progress.empty()
    else:
        histories = read_histories(universe.ticker.tolist())
    if not histories:
        raise ValueError("No daily history available")
    calendar = yahoo_session_calendar(histories, now, tuple(extra_closed))
    progress = st.progress(0.,text="SMC / CHOCH scanning")
    try:
        result = scan(universe, histories, config, calendar, now,
                      progress=lambda done,total: progress.progress(done/total,text=f"SMC {done}/{total}"))
    finally:
        progress.empty()
    result.update(histories=histories, universe=universe, calendar=calendar,
                  download_errors=errors, universe_errors=universe_errors,
                  data_source="Yahoo Finance daily download" if refresh else "Explicit cached research",
                  download_success=len(histories), download_failed=len(universe)-len(histories))
    return result


def _send_click(preview):
    frame = st.session_state.get("smc_choch_delivery")
    try:
        st.session_state.smc_choch_line_outcome = send_manual(preview, frame)
    except Exception:
        st.session_state.smc_choch_line_outcome = dict(sent=0, failed=preview["count"],
            error="Not sent or delivery uncertain. Snapshot may have changed or already been reserved; review the CHOCH ledger. No automatic retry.")


def render_notifications(results):
    st.subheader("CHOCH Entry Analysis — current LINE candidates")
    previous = attempted_ids()
    delivery = notification_snapshot(results, previous)
    st.session_state.smc_choch_delivery = delivery
    st.dataframe(delivery,hide_index=True,use_container_width=True)
    st.caption("Only current READY/TRIGGERED records not previously reserved are included. Historical/stale signals are excluded here, before preview.")
    preview = build_preview(delivery)
    st.write(f"CHOCH Entry Analysis candidates: {len(delivery)} · LINE: {preview['count']}")
    with st.expander("Preview CHOCH LINE messages"):
        for message in preview["messages"]:
            st.text(message)
    exists = DEFAULT_PATH.exists()
    if not exists:
        st.info("Manual sending awaits approval/initialization of the separate CHOCH notification ledger. Scanning, charts and CSV remain available.")
    st.button(f"📲 Send {len(delivery)} CHOCH candidates to LINE", key="smc_choch_line_send",
              type="primary",disabled=delivery.empty or not exists,on_click=_send_click,args=(preview,))
    outcome = st.session_state.get("smc_choch_line_outcome")
    if outcome:
        st.write(f"LINE accepted: {outcome['sent']} · failed/uncertain: {outcome['failed']}")
        if outcome.get("error"):
            st.error(outcome["error"])


def render_smc_choch_panel():
    st.title("SMC / CHOCH Stock Screener")
    st.caption("SMC_CHOCH_REVERSAL · Independent daily/weekly reversal research · Completed candles only")
    with st.form("smc_choch_controls"):
        mode = st.selectbox("Screening mode", ["Bullish CHOCH","Bearish CHOCH","CHOCH + MACD Confirmation",
                           "CHOCH Followed by BOS Confirmation","CHOCH + Order Block Retest"])
        a,b,c = st.columns(3)
        timeframe = a.selectbox("Timeframe",["Daily","Weekly"])
        direction = b.selectbox("Direction for combined modes",["BULLISH","BEARISH"])
        structure = c.selectbox("Structure type",["SWING","INTERNAL"])
        sl = a.number_input("Swing pivot left",1,30,5); sr = b.number_input("Swing pivot right",1,30,5)
        il = a.number_input("Internal pivot left",1,30,3); ir = b.number_input("Internal pivot right",1,30,3)
        lookback = c.number_input("Structure lookback (candles)",10,500,60)
        age = c.number_input("Signal age (candles)",1,120,10)
        volume = a.number_input("Minimum volume ratio",0.,20.,1.5,.1)
        volume_period = b.number_input("Prior volume average (candles)",2,100,20)
        value = c.number_input("Minimum traded value (TWD per selected candle)",0,10_000_000_000,100_000_000,10_000_000)
        buffer = a.number_input("Breakout buffer (%)",0.,20.,.5,.1)/100
        weekly = b.checkbox("Weekly trend filter")
        macd = c.checkbox("MACD cross confirmation")
        macd_age = c.number_input("Recent MACD cross age (candles)",1,30,3)
        bos = a.checkbox("BOS confirmation")
        ob = b.checkbox("Order Block retest confirmation")
        entry_mode = a.selectbox("Entry mode",["BREAKOUT","RETEST","ORDER_BLOCK","BOS"])
        stop = b.number_input("Structural stop safety buffer (%)",0.,20.,.5,.1)/100
        target = c.number_input("Reference target (R)",.1,20.,2.,.1)
        ob_lookback = c.number_input("Order block search candles",1,100,10)
        market = a.selectbox("Market",["All","TWSE","TPEx"])
        limit = b.number_input("Maximum stocks (0 = all)",0,3000,0)
        codes = st.text_input("Optional stock codes / Yahoo symbols (blank = all stocks)")
        refresh = True
        closures = st.text_input("Additional exchange closure dates (YYYY-MM-DD, comma-separated)")
        st.caption("Default: all TWSE/TPEx common stocks → Yahoo Finance daily downloads → CHOCH rules → matching stocks. Prices stay in CHOCH memory. Session dates come from the downloaded Yahoo universe; no separate calendar API is called. A market-wide Yahoo outage cannot be distinguished from a closure. Missing individual-stock bars remain invalid. Weekly turnover sums daily traded values. No MA trend or revenue rule is imposed.")
        submitted = st.form_submit_button("Download Yahoo prices and scan CHOCH",type="primary")
    if submitted:
        config = SMCConfig(timeframe=timeframe,swing_left=sl,swing_right=sr,internal_left=il,internal_right=ir,
                           lookback=lookback,min_volume_ratio=volume,volume_period=volume_period,min_traded_value=value,
                           breakout_buffer=buffer,direction="BULLISH" if mode=="Bullish CHOCH" else "BEARISH" if mode=="Bearish CHOCH" else direction,
                           structure_type=structure,weekly_filter=weekly,macd_confirmation=macd or mode=="CHOCH + MACD Confirmation",
                           macd_age=macd_age,bos_confirmation=bos or mode=="CHOCH Followed by BOS Confirmation",
                           ob_retest=ob or mode=="CHOCH + Order Block Retest",entry_mode=entry_mode,
                           stop_buffer=stop,target_r=target,signal_age=age,ob_lookback=ob_lookback)
        try:
            with st.spinner("Downloading Yahoo daily prices for CHOCH"):
                st.session_state.smc_choch_snapshot = run_scan(config,codes,market,limit,refresh,
                    [pd.Timestamp(d.strip()).date().isoformat() for d in closures.split(',') if d.strip()])
            st.session_state.pop("smc_choch_line_outcome",None)
            st.session_state.pop("smc_choch_backtest",None)
        except Exception as error:
            st.error("CHOCH scan could not complete: "+str(error))
    snapshot = st.session_state.get("smc_choch_snapshot")
    if snapshot is None:
        return
    st.caption("Snapshot: "+snapshot["asof"]+" · Existing scanner snapshots remain independent.")
    rows = snapshot["results"]
    st.write(f"Stocks scanned: {snapshot['stocks_scanned']} · CHOCH records: {len(rows)} · Data issues: {len(snapshot['issues'])}")
    if "download_success" in snapshot:
        st.write(f"Yahoo downloaded: {snapshot['download_success']} · Download unavailable: {snapshot['download_failed']}")
    if snapshot.get("universe_errors"):
        st.warning("Company roster is incomplete for one or more markets. This result is a partial-market scan.")
    with st.expander("Data issues / configuration"):
        st.json(snapshot["issues"])
        st.json(snapshot.get("download_errors",{}))
        st.json(snapshot.get("universe_errors",{}))
        st.json(asdict(snapshot["config"]))
    if rows.empty:
        st.info("No CHOCH signals satisfy the configured signal-date filters. Thresholds were not relaxed.")
    else:
        statuses = st.multiselect("Displayed entry states",["WAIT","READY","TRIGGERED","INVALIDATED"],
                                 default=["WAIT","READY","TRIGGERED","INVALIDATED"],key="smc_choch_status_filter")
        visible = rows.loc[rows.entry_status.isin(statuses)].copy()
        st.session_state.smc_choch_entry_results = visible
        st.dataframe(visible,hide_index=True,use_container_width=True)
        st.download_button("Export CHOCH CSV",visible.to_csv(index=False).encode("utf-8-sig"),"smc_choch.csv","text/csv",key="smc_choch_export")
        if not visible.empty:
            ident = st.selectbox("CHOCH chart signal",visible.signal_id.tolist(),
                                 format_func=lambda i: " / ".join(str(visible.loc[visible.signal_id.eq(i)].iloc[0][k]) for k in ["ticker","signal_date","direction"]),key="smc_choch_chart_signal")
            row = visible.loc[visible.signal_id.eq(ident)].iloc[0].to_dict()
            overlays = st.multiselect("Chart overlays",["HH/HL/LH/LL","CHOCH","BOS","Protected levels","Order block","Entry/Stop/Target","Secondary structure"],
                                     default=["CHOCH","BOS","Protected levels","Entry/Stop/Target"],key="smc_choch_overlays")
            st.plotly_chart(smc_chart(snapshot["details"][row["ticker"]],row,overlays),use_container_width=True)
            st.caption("Pivot markers are drawn at pivot time but become available only at their displayed confirmation time. Off-scale reference levels do not expand the price axis.")
        render_notifications(visible)
    with st.expander("Historical strategy comparison — independent research"):
        st.caption("Uses this snapshot's histories only. Next-session execution, fixed shares, conservative same-bar exits, costs included. Current-universe and historical-revision bias remain.")
        if st.button("Run cached historical comparison",key="smc_choch_backtest_run"):
            from smc.backtest import compare
            with st.spinner("Comparing cached historical signals"):
                st.session_state.smc_choch_backtest = compare(snapshot["universe"],snapshot["histories"],snapshot["config"],snapshot["calendar"],snapshot["asof"])
        if "smc_choch_backtest" in st.session_state:
            report = st.session_state.smc_choch_backtest
            st.dataframe(report["summary"],hide_index=True)
            st.download_button("Export comparison trades",report["trades"].to_csv(index=False),"smc_comparison.csv",key="smc_choch_backtest_export")
