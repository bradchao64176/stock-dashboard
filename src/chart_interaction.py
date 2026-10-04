"""Presentation-only Plotly hover helpers; never alter source market data."""
import logging
from numbers import Number
import pandas as pd

logger = logging.getLogger(__name__)


def _xaxis_names(fig):
    names = {name for name in fig.layout.to_plotly_json() if name.startswith("xaxis")}
    names.update("xaxis" + (getattr(trace, "xaxis", None) or "x")[1:] for trace in fig.data
                 if hasattr(trace, "x"))
    return names


def chart_date(value):
    """Reject numeric indices/epochs rather than interpreting them as dates."""
    if value is None or isinstance(value, Number):
        return pd.NaT
    try:
        result = pd.Timestamp(value)
        if pd.isna(result):
            return pd.NaT
        if result.tzinfo is not None:
            result = result.tz_convert("Asia/Taipei").tz_localize(None)
        return result
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


def normalize_chart_history(history):
    """Normalize a presentation copy; never modify scanner/cache history."""
    result = history.copy()
    result.index = pd.DatetimeIndex([chart_date(value) for value in result.index])
    result = result.loc[result.index.notna()].sort_index()
    logger.debug("Chart min date: %s; Chart max date: %s", result.index.min(), result.index.max())
    return result


def validate_date_chart(fig):
    """Normalize date-coordinate traces/overlays; leave domain coordinates alone."""
    def required(value):
        date = chart_date(value)
        if pd.isna(date):
            raise ValueError("Invalid chart date coordinate; numeric indices/epochs are not dates")
        return date.to_pydatetime()

    for trace in fig.data:
        if getattr(trace, "x", None) is not None:
            trace.x = [required(value) for value in trace.x]
            logger.debug("Chart trace %s: %s .. %s", trace.name,
                         trace.x[0] if len(trace.x) else None, trace.x[-1] if len(trace.x) else None)
    for shape in fig.layout.shapes:
        ref = shape.xref or "x"
        if ref.startswith("x") and not ref.endswith(" domain"):
            shape.x0, shape.x1 = required(shape.x0), required(shape.x1)
    for annotation in fig.layout.annotations:
        if (annotation.xref or "x").startswith("x") and not (annotation.xref or "x").endswith(" domain"):
            annotation.x = required(annotation.x)
        if annotation.axref and annotation.axref.startswith("x"):
            annotation.ax = required(annotation.ax)
    for name in _xaxis_names(fig):
        fig.layout[name].update(type="date")
    return fig


def apply_crosshair(fig, *, stacked=False):
    fig.update_layout(hovermode="x unified", spikedistance=-1)
    if "hoversubplots" in fig.layout._valid_props:
        fig.update_layout(hoversubplots="axis")
    if stacked:
        # matched axes alone do not propagate Plotly hover across subplots.
        fig.update_traces(xaxis="x")
        # Remap EVERY reference before removing unused axes. An orphaned
        # 'x3 domain' hline can be coerced by Plotly.js to date-axis x=0/1.
        for shape in fig.layout.shapes:
            if shape.xref and shape.xref.startswith("x"):
                shape.xref = "x domain" if shape.xref.endswith(" domain") else "x"
        for annotation in fig.layout.annotations:
            if annotation.xref and annotation.xref.startswith("x"):
                annotation.xref = "x domain" if annotation.xref.endswith(" domain") else "x"
            if annotation.axref and annotation.axref.startswith("x"):
                annotation.axref = "x"
        fig.update_yaxes(anchor="x")
        fig.layout.xaxis.matches = None
        fig.layout.xaxis.update(anchor="y3", showticklabels=True)
        fig.layout.xaxis2 = None
        fig.layout.xaxis3 = None
    axes = dict(showspikes=True, spikemode="across", spikesnap="cursor",
                showline=True, spikethickness=1, spikedash="dot")
    # update_xaxes uses make_subplots' original grid and recreates deleted axes.
    for name in _xaxis_names(fig):
        fig.layout[name].update(**axes, hoverformat="%Y/%m/%d")
    fig.update_yaxes(**axes)
    for trace in fig.data:
        if trace.type in ("scatter", "bar") and not trace.hovertemplate:
            fmt = ",.0f" if "volume" in (trace.name or "").lower() or trace.name == "成交股數" else ".2f"
            trace.hovertemplate = "%{y:" + fmt + "}<extra>%{fullData.name}</extra>"
    return fig


def apply_price_hover(fig, history):
    """Use existing OHLCV/MA values in a single candle tooltip."""
    def value(row, column):
        number = row.get(column)
        return "N/A" if pd.isna(number) else format(number, ",.0f" if column == "Volume" else ".2f")

    for trace in fig.data:
        if trace.type != "candlestick":
            continue
        view = history.reindex(pd.DatetimeIndex(trace.x))
        trace.text = ["<br>".join(f"{column}: {value(row, column)}" for column in
                                ("Open", "High", "Low", "Close", "Volume", "MA20", "MA60"))
                      for _, row in view.iterrows()]
        trace.hoverinfo = "text"
    # MA values are already in candle tooltips; preserve their visual lines.
    if any(trace.type == "candlestick" for trace in fig.data):
        for trace in fig.data:
            if trace.name in ("MA20", "MA60"):
                trace.hoverinfo = "skip"
                trace.hovertemplate = None
    return fig
