"""Independent full-universe Supertrend scanner page and frozen manual actions."""
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from strategies.supertrend_kd import SupertrendConfig
from services.supertrend_scanner import run_scan, entry_analysis
from services.supertrend_line import preview, send_manual
from src.chart_interaction import apply_crosshair, validate_date_chart

PREFIX='supertrend_ema_kd_'


def chart(frame):
    data=frame.tail(180)
    fig=make_subplots(rows=3,cols=1,shared_xaxes=True,row_heights=[.6,.15,.25],vertical_spacing=.03)
    fig.add_trace(go.Candlestick(x=data.index,open=data.Open,high=data.High,low=data.Low,close=data.Close,name='Price'),row=1,col=1)
    fig.add_trace(go.Scatter(x=data.index,y=data.EMA,name='EMA',line=dict(color='orange')),row=1,col=1)
    for bullish,color in ((True,'green'),(False,'red')):
        fig.add_trace(go.Scatter(x=data.index,y=data.Supertrend.where(data.supertrend_bullish.eq(bullish)),
            name='Supertrend '+('bullish' if bullish else 'bearish'),line=dict(color=color),connectgaps=False),row=1,col=1)
    buys=data.loc[data.BUY]
    fig.add_trace(go.Scatter(x=buys.index,y=buys.Low,mode='markers',name='BUY',marker=dict(symbol='triangle-up',color='green',size=12)),row=1,col=1)
    fig.add_trace(go.Bar(x=data.index,y=data.Volume,name='Volume'),row=2,col=1)
    for name in ('K','D'):
        fig.add_trace(go.Scatter(x=data.index,y=data[name],name=name),row=3,col=1)
    fig.update_layout(height=800,xaxis_rangeslider_visible=False)
    apply_crosshair(fig,stacked=True)
    return validate_date_chart(fig)


def _send(packet):
    try:
        if st.session_state[PREFIX+'snapshot']['config'].get('timeframe') != 'Daily':
            raise ValueError('A new daily analysis is required')
        st.session_state[PREFIX+'line_outcome']=send_manual(packet,st.session_state[PREFIX+'snapshot']['results'])
    except Exception:
        st.session_state[PREFIX+'line_outcome']={'error':'Not sent, already reserved, or delivery uncertain. Review the strategy ledger; no automatic retry.'}


def render_supertrend_panel():
    st.title('Supertrend + EMA200 + KD Scanner')
    st.caption('Independent full TWSE/TPEx common-stock scan · Yahoo daily OHLCV · Volume in shares · TWD traded value')
    with st.form(PREFIX+'form'):
        twse=st.checkbox('TWSE',True); tpex=st.checkbox('TPEx',True)
        st.caption('Timeframe: Daily (日線)')
        a,b,c=st.columns(3)
        with a:
            ema_enabled=st.checkbox('Enable EMA Filter',value=True)
            ema=st.number_input('EMA period',min_value=2,max_value=500,value=200)
            warmup=st.number_input('Additional warm-up candles',min_value=0,max_value=500,value=50)
            atr=st.number_input('Supertrend ATR period',min_value=1,max_value=100,value=10)
            factor=st.number_input('Supertrend ATR multiplier',min_value=.1,max_value=20.,value=3.,step=.1)
        with b:
            kd=st.number_input('KD RSV period',min_value=2,max_value=100,value=9)
            k=st.number_input('K recursive smoothing',min_value=1,max_value=30,value=3)
            d=st.number_input('D recursive smoothing',min_value=1,max_value=30,value=3)
            ceiling=st.number_input('K and D must each be below',min_value=1.,max_value=100.,value=40.)
        with c:
            deviation=st.checkbox('Enable Supertrend deviation filter',True)
            low=st.number_input('Minimum deviation (%)',min_value=0.,value=0.)
            high=st.number_input('Maximum deviation (%)',min_value=0.,value=10.)
            liquidity=st.checkbox('Enable minimum traded value',True)
            value=st.number_input('Minimum traded value (TWD)',min_value=0,value=100_000_000,step=10_000_000)
        st.caption('All indicators and BUY conditions use completed daily candles. Flat RSV windows are unknown. Existing cache is read-only; new bars use a separate strategy cache.')
        submitted=st.form_submit_button('Scan all eligible stocks',type='primary')
    if submitted:
        progress=st.progress(0.)
        try:
            config=SupertrendConfig(ema_enabled=ema_enabled,ema_period=int(ema),warmup=int(warmup),atr_period=int(atr),multiplier=factor,
                kd_period=int(kd),k_smoothing=int(k),d_smoothing=int(d),kd_ceiling=ceiling,deviation_enabled=deviation,
                deviation_min=low,deviation_max=high,value_enabled=liquidity,min_value=value)
            exchanges=tuple(x for x,on in [('TWSE',twse),('TPEx',tpex)] if on)
            snapshot=run_scan(config,exchanges,progress=lambda done,total,label: progress.progress(done/max(total,1),text=f'{label}: {done}/{total}'))
            st.session_state[PREFIX+'snapshot']=snapshot
            st.session_state.pop(PREFIX+'entries',None); st.session_state.pop(PREFIX+'line_outcome',None)
        except Exception as error:
            st.error('Scan failed: '+str(error))
        finally:
            progress.empty()
    snapshot=st.session_state.get(PREFIX+'snapshot')
    if snapshot is not None and snapshot.get('config',{}).get('timeframe') != 'Daily':
        # Old weekly/dual snapshots must never remain available for charts or LINE.
        for suffix in ('snapshot','entries','line_outcome'):
            st.session_state.pop(PREFIX+suffix,None)
        st.info('Previous non-daily analysis cleared. Run a new daily scan.')
        return
    if snapshot is None:
        return
    st.caption('Last scan: '+snapshot['scan_time'])
    if snapshot.get('yahoo_no_trade_dates'):
        st.caption('Yahoo market-wide no-trade rows excluded. Latest expected session: '+snapshot['expected_session']+
                   '. This is observed Yahoo coverage, not an official holiday calendar.')
    st.json(dict(snapshot['stats'],**snapshot.get('download_stats',{})))
    if snapshot.get('universe_errors'):
        st.warning('Exchange roster incomplete: results cover only the available markets.')
    with st.expander('Coverage, errors and applied parameters'):
        st.json(snapshot['config']); st.json(snapshot.get('universe_errors',{})); st.json(snapshot.get('data_errors',{}))
        st.dataframe(snapshot['audit'],hide_index=True)
        st.download_button('Export scan audit',snapshot['audit'].to_csv(index=False),'supertrend_audit.csv',key=PREFIX+'audit_csv')
    results=snapshot['results']
    st.subheader(f'Matching stocks: {len(results)}')
    st.dataframe(results,hide_index=True,use_container_width=True)
    st.download_button('Export matches CSV',results.to_csv(index=False).encode('utf-8-sig'),'supertrend_matches.csv',key=PREFIX+'csv')
    if not results.empty:
        ticker=st.selectbox('Stock chart',results.ticker.tolist(),key=PREFIX+'chart')
        st.plotly_chart(chart(snapshot['details'][ticker]),use_container_width=True)
        if st.button('Analyze these matches with shared Entry Timing',key=PREFIX+'entry_button'):
            st.session_state[PREFIX+'entries']=entry_analysis(snapshot)
        if PREFIX+'entries' in st.session_state:
            st.caption('Optional daily Entry Timing context. It does not change this strategy’s matches.')
            st.dataframe(st.session_state[PREFIX+'entries'],hide_index=True)
    st.subheader('Manual LINE notification')
    packet=preview(results)
    st.write(f'Displayed strategy matches / LINE preview: {len(results)}')
    with st.expander('Preview exact LINE messages'):
        for message in packet['messages']:
            st.text(message)
    st.button(f'Send {len(results)} Supertrend matches to LINE',type='primary',key=PREFIX+'line_send',
              disabled=results.empty,on_click=_send,args=(packet,))
    if PREFIX+'line_outcome' in st.session_state:
        st.write(st.session_state[PREFIX+'line_outcome'])
