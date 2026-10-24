"""CHOCH presentation only. Existing chart builders and indicators remain untouched."""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from src.chart_interaction import apply_crosshair, apply_price_hover, validate_date_chart


def smc_chart(detail, row, categories=()):
    data = detail["data"].tail(160)
    indicators = detail["indicators"].reindex(data.index)
    hover_data = data.copy()
    for column in ("MA20", "MA60"):
        hover_data[column] = indicators[column]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[.6,.15,.25], vertical_spacing=.03)
    fig.add_trace(go.Candlestick(x=data.index, open=data.Open, high=data.High, low=data.Low, close=data.Close, name="Price"), row=1,col=1)
    for column in ("MA20", "MA60"):
        fig.add_trace(go.Scatter(x=data.index,y=indicators[column],name=column),row=1,col=1)
    fig.add_trace(go.Bar(x=data.index,y=data.Volume,name="Volume"),row=2,col=1)
    for column in ("Impulse_MACD","Impulse_Signal"):
        fig.add_trace(go.Scatter(x=data.index,y=indicators[column],name=column),row=3,col=1)
    fig.add_trace(go.Bar(x=data.index,y=indicators.Impulse_Histogram,name="Histogram"),row=3,col=1)
    fig.add_hline(y=0,row=3,col=1)
    primary = row.get("structure_type", "SWING")
    secondary = "INTERNAL" if primary == "SWING" else "SWING"
    for source, structure in ((primary, detail["structure"]), (secondary, detail["other_structure"])):
        if source == secondary and "Secondary structure" not in categories:
            continue
        if "HH/HL/LH/LL" in categories:
            for pivot in structure["pivots"]:
                if pivot["pivot_time"] in data.index:
                    fig.add_trace(go.Scatter(x=[pivot["pivot_time"]],y=[pivot["price"]],mode="markers",
                                            name=source+" "+pivot["label"],text=["Confirmed: "+str(pivot["confirmed_at"])],
                                            hovertemplate="%{text}<extra>%{fullData.name}</extra>",showlegend=False),row=1,col=1)
        for event in structure["events"]:
            if event["kind"] in categories and event["signal_date"] in data.index:
                fig.add_trace(go.Scatter(x=[event["signal_date"]], y=[event["signal_close"]],mode="markers",
                                        marker=dict(size=12,symbol="triangle-up" if event["direction"]=="BULLISH" else "triangle-down"),
                                        name=event["direction"]+" "+event["kind"]),row=1,col=1)
    if "Protected levels" in categories:
        state = detail["structure"]["states"][-1]
        for field in ("protected_high","protected_low"):
            if state[field] is not None:
                fig.add_hline(y=state[field],line_dash="dash",row=1,col=1)
    if "Order block" in categories and pd.notna(row.get("ob_low")):
        fig.add_hrect(y0=row["ob_low"],y1=row["ob_high"],fillcolor="orange",opacity=.15,line_width=0,row=1,col=1)
    if "Entry/Stop/Target" in categories:
        for field, color in (("entry_price","blue"),("stop_loss","red"),("target_price","green")):
            if pd.notna(row.get(field)):
                fig.add_hline(y=row[field],line_color=color,line_dash="dot",row=1,col=1)
    # Reference levels must not expand price scale. The user can still zoom/pan/autoscale.
    lo, hi = data.Low.min(), data.High.max()
    padding = max((hi-lo)*.05, hi*.005)
    fig.update_yaxes(range=[lo-padding,hi+padding],row=1,col=1)
    fig.update_layout(height=730,xaxis_rangeslider_visible=False)
    return validate_date_chart(apply_price_hover(apply_crosshair(fig,stacked=True),hover_data))
