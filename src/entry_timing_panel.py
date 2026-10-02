"""Additional Strong result analysis, using only the existing scan snapshot."""
import streamlit as st

from services.entry_timing_config import EntryTimingConfig
from services.entry_timing_service import analyze_candidates, STATUS_LABELS


def render_entry_timing_panel(snapshot, impulse_config):
    st.subheader("🎯 Entry Timing Analysis")
    st.caption("Strong Golden Cross Entry Analysis · 技術進場區域分析。Reference zones and risk-unit targets are not price forecasts.")
    candidates = snapshot["candidates"]
    if candidates.empty:
        st.info("No existing Strong Golden Cross candidates to analyze.")
        return
    result = analyze_candidates(candidates, snapshot["details"], impulse_config=impulse_config)
    display = result.copy()
    display["entry_status"] = display.entry_status.map(STATUS_LABELS)
    columns = ["stock_code", "stock_name", "analysis_date", "current_price", "strong_golden_cross_score", "ma20", "ma60",
               "distance_ma20_pct", "impulse_macd", "impulse_signal", "histogram", "histogram_direction", "entry_status",
               "primary_entry_type", "entry_zone_low", "entry_zone_high", "entry_reference_price", "reference_stop", "risk_pct", "target_2r", "target_3r"]
    st.dataframe(display[columns], hide_index=True, use_container_width=True)
    st.download_button("Download entry analysis CSV", result.to_csv(index=False).encode("utf-8-sig"),
                       "entry_timing_analysis.csv", "text/csv", key="entry_timing_export")
    ticker = st.selectbox("Entry analysis stock", result.ticker.tolist(), key="entry_timing_stock")
    row = result[result.ticker == ticker].iloc[0].to_dict()
    st.markdown(f"**{row['stock_code']} {row['stock_name']} — {STATUS_LABELS[row['entry_status']]}**")
    if row["entry_status"] == "UNKNOWN":
        st.info(row["reason"] or "Missing required data")
        return
    st.write({"Price date": row["analysis_date"], "Current Price": row["current_price"], "Strong Golden Cross Score": row["strong_golden_cross_score"],
              "Impulse MACD": row["impulse_macd"], "Signal": row["impulse_signal"], "Histogram": row["histogram"],
              "Histogram Direction": row["histogram_direction"], "MA20": row["ma20"], "MA60": row["ma60"], "Distance MA20 %": row["distance_ma20_pct"]})
    zone = lambda lo, hi: f"${row[lo]:.2f} ～ ${row[hi]:.2f}"
    st.write({"Primary Entry Type": row["primary_entry_type"], "Primary Reference Entry Zone": zone("entry_zone_low", "entry_zone_high"),
              "Pullback Entry Zone": zone("pullback_entry_low", "pullback_entry_high"),
              "Breakout Entry Zone": zone("breakout_entry_low", "breakout_entry_high"),
              "Cross Entry Zone": zone("cross_entry_low", "cross_entry_high"), "Cross Date": row["cross_date"], "Cross Age (sessions)": row["cross_age_days"]})
    if row["entry_status"] == "HIGHLY_EXTENDED":
        st.warning("Current price is significantly above the reference pullback zone. WAIT FOR PULLBACK.")
    elif row["action"] == "REFERENCE_ZONE_ACTIVE":
        st.info(f"Current price is inside the {row['primary_entry_type'].lower()} zone.")
    else:
        st.info(row["action"].replace("_", " "))
    if row["cross_entry_missed"]:
        st.caption("Cross Entry Missed. Use the current entry status; if no other zone is active, wait for pullback.")
    contraction = row["volume_contraction"]
    st.write("Volume Behavior:", "UNKNOWN" if contraction is None else ("Contracting on Pullback" if contraction else "Volume Not Contracting"))
    st.write({"Current Volume Ratio": row["current_volume_ratio"], "Cross Day Volume Ratio": row["cross_day_volume_ratio"]})
    st.markdown("**Risk management references**")
    st.write({"Reference Entry": row["entry_reference_price"], "Reference Stop": row["reference_stop"], "Stop Source": row["stop_source"],
              "Risk %": row["risk_pct"], "2R Target": row["target_2r"], "3R Target": row["target_3r"], "Risk Structure": row["risk_status"]})
    with st.expander("Entry Timing configuration"):
        st.json(vars(EntryTimingConfig()))
        st.caption("Percent thresholds use fractions. STRUCTURAL prefers a positive prior swing low below Reference Entry; otherwise MA20 − 0.5 × ATR14. All zones are technical references, including when the current trend is invalid.")
