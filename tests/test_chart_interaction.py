import unittest
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from src.chart_interaction import apply_crosshair, apply_price_hover, normalize_chart_history, validate_date_chart


class ChartInteractionTests(unittest.TestCase):
    def test_crosshair_preserves_overlays_and_zoom(self):
        fig = go.Figure(go.Scatter(x=[1, 2], y=[10, 11], name="Price"))
        fig.add_hrect(y0=10, y1=11)
        fig.add_hline(y=9)
        fig.add_hline(y=13)
        shapes = fig.layout.shapes
        fig.update_layout(dragmode="pan", xaxis_range=[1, 2])
        apply_crosshair(fig)
        self.assertEqual(fig.layout.hovermode, "x unified")
        for axis in (fig.layout.xaxis, fig.layout.yaxis):
            self.assertTrue(axis.showspikes)
            self.assertEqual(axis.spikemode, "across")
            self.assertEqual(axis.spikesnap, "cursor")
        self.assertEqual(fig.layout.shapes, shapes)
        self.assertEqual(fig.layout.dragmode, "pan")
        self.assertEqual(fig.layout.xaxis.range, (1, 2))
        self.assertEqual(list(fig.data[0].y), [10, 11])

    def test_stacked_dates_and_candle_values(self):
        data = pd.DataFrame(dict(Open=[10., 11.], High=[12., 13.], Low=[9., 10.],
                                 Close=[11., 12.], Volume=[1000, 2000], MA20=[10., 10.5], MA60=[9., 9.5]),
                            index=pd.date_range("2026-10-01", periods=2))
        before = data.copy(deep=True)
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True)
        fig.add_trace(go.Candlestick(x=data.index, open=data.Open, high=data.High, low=data.Low, close=data.Close), row=1, col=1)
        fig.add_trace(go.Bar(x=data.index, y=data.Volume, name="Volume"), row=2, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=[.1, .2], name="Impulse MACD"), row=3, col=1)
        fig.add_hline(y=0, row=3, col=1)
        apply_price_hover(apply_crosshair(fig, stacked=True), data)
        self.assertEqual({trace.xaxis for trace in fig.data}, {"x"})
        self.assertEqual([trace.yaxis for trace in fig.data], ["y", "y2", "y3"])
        self.assertEqual(fig.layout.hoversubplots, "axis")
        self.assertEqual(fig.layout.shapes[0].xref, "x domain")
        self.assertEqual((fig.layout.shapes[0].x0, fig.layout.shapes[0].x1), (0, 1))
        self.assertEqual(fig.layout.yaxis2.anchor, "x")
        self.assertEqual(fig.layout.yaxis3.anchor, "x")
        self.assertNotIn("xaxis3", fig.layout.to_plotly_json())
        self.assertIn("Volume: 2,000", fig.data[0].text[1])
        self.assertIn("MA60: 9.50", fig.data[0].text[1])
        pd.testing.assert_frame_equal(data, before)

    def test_normalization_drops_invalid_and_numeric_dates_without_mutation(self):
        data = pd.DataFrame({"Close": [2, 0, 1, 3, 4]},
                            index=["2026-10-02", 0, "2026-10-01", None, "invalid"])
        before = data.copy(deep=True)
        normalized = normalize_chart_history(data)
        self.assertEqual(normalized.index.tolist(), list(pd.date_range("2026-10-01", periods=2)))
        self.assertEqual(normalized.Close.tolist(), [1, 2])
        pd.testing.assert_frame_equal(data, before)

    def test_date_axis_rejects_numeric_marker_or_shape(self):
        fig = go.Figure(go.Scatter(x=[0], y=[10]))
        with self.assertRaisesRegex(ValueError, "Invalid chart date"):
            validate_date_chart(fig)
        fig = go.Figure(go.Scatter(x=["2026-10-02"], y=[10]))
        fig.add_shape(type="line", xref="x", x0=0, x1=1, y0=10, y1=10)
        with self.assertRaisesRegex(ValueError, "Invalid chart date"):
            validate_date_chart(fig)
        fig.layout.shapes[0].xref = "paper"
        validate_date_chart(fig)
        self.assertEqual(fig.layout.xaxis.type, "date")

    def test_real_impulse_builder_all_traces_use_market_dates(self):
        from src.impulse_panel import impulse_chart
        dates = pd.bdate_range("2026-04-01", "2026-10-02")
        data = pd.DataFrame({name: [100.] * len(dates) for name in
                            ["Open", "High", "Low", "Close", "Volume", "MA20", "MA60",
                             "Volume_MA20", "Impulse_MACD", "Impulse_Signal", "Impulse_Histogram"]}, index=dates)
        before = data.copy(deep=True)
        fig = impulse_chart(data, pd.Series(dict(golden_cross_date="2026-10-01", signal_close=100.)))
        for trace in fig.data:
            actual = pd.DatetimeIndex(trace.x)
            self.assertTrue(actual.isin(dates).all(), trace.name)
            if trace.name != "Golden cross":
                self.assertEqual(actual.min(), dates.min())
                self.assertEqual(actual.max(), dates.max())
            self.assertEqual(trace.xaxis, "x")
        self.assertEqual(fig.layout.xaxis.type, "date")
        self.assertIsNone(fig.layout.xaxis.range)
        self.assertEqual(fig.layout.shapes[0].xref, "x domain")
        self.assertEqual(fig.layout.hovermode, "x unified")
        pd.testing.assert_frame_equal(data, before)
