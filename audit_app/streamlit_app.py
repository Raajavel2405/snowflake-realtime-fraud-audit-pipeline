"""
streamlit_app.py — Fraud & Audit Command Center (Streamlit-in-Snowflake)
------------------------------------------------------------------
Runs INSIDE Snowflake (container runtime). Reads the live inference view
FRAUD_DB.ANALYTICS.FRAUD_PREDICTIONS, which scores the auto-refreshing
Dynamic Table pipeline with the registered Isolation Forest (V2).

No data leaves Snowflake. No BI license. RBAC-governed. Always current.
"""

import altair as alt
import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session

st.set_page_config(
    page_title="Fraud & Audit Command Center",
    page_icon="🛡️",
    layout="wide",
)

session = get_active_session()


@st.cache_data(ttl=60, show_spinner="Loading scored transactions from Snowflake...")
def load_predictions() -> pd.DataFrame:
    """Pull the live inference view. TTL=60s keeps it near-real-time."""
    df = session.sql(
        """
        SELECT txn_id, event_ts, user_id, amount, merchant_category,
               country_code, card_present, channel, amount_zscore,
               amount_to_avg_ratio, anomaly_score, ml_anomaly_flag,
               is_synthetic_anomaly
        FROM FRAUD_DB.ANALYTICS.FRAUD_PREDICTIONS
        """
    ).to_pandas()
    df["EVENT_TS"] = pd.to_datetime(df["EVENT_TS"])
    return df


df = load_predictions()

# ---------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------
hcol1, hcol2 = st.columns([5, 1])
with hcol1:
    st.title("🛡️ Fraud & Audit Command Center")
with hcol2:
    if st.button("Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
st.caption("100% native Snowflake — streaming → Dynamic Tables → Isolation Forest (V2) → this app")

# ---------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------
total_txns = len(df)
flagged = df[df["ML_ANOMALY_FLAG"]]
n_flagged = len(flagged)
exposure = float(flagged["AMOUNT"].sum())

# Audit metric: how well ML flags align with ground truth (eval-only label)
tp = int((df["ML_ANOMALY_FLAG"] & df["IS_SYNTHETIC_ANOMALY"]).sum())
precision = (tp / n_flagged) if n_flagged else 0.0
recall = (tp / int(df["IS_SYNTHETIC_ANOMALY"].sum())) if df["IS_SYNTHETIC_ANOMALY"].sum() else 0.0

k = st.columns(4)
k[0].metric("Transactions scored", f"{total_txns:,}")
k[1].metric("Anomalies flagged", f"{n_flagged:,}")
k[2].metric("Flagged $ exposure", f"${exposure:,.0f}")
k[3].metric("Detection precision / recall", f"{precision:.0%} / {recall:.0%}")

st.divider()

# ---------------------------------------------------------------------
# Flagged anomalies table (the auditor's worklist)
# ---------------------------------------------------------------------
left, right = st.columns([3, 2])

with left:
    st.subheader("Flagged anomalies (highest risk first)")
    worklist = (
        flagged.sort_values("ANOMALY_SCORE", ascending=False)[
            ["EVENT_TS", "USER_ID", "AMOUNT", "MERCHANT_CATEGORY", "COUNTRY_CODE",
             "CHANNEL", "AMOUNT_ZSCORE", "ANOMALY_SCORE"]
        ]
        .rename(columns={
            "EVENT_TS": "Time", "USER_ID": "User", "AMOUNT": "Amount",
            "MERCHANT_CATEGORY": "Category", "COUNTRY_CODE": "Country",
            "CHANNEL": "Channel", "AMOUNT_ZSCORE": "Z-score", "ANOMALY_SCORE": "ML score",
        })
    )
    st.dataframe(
        worklist, hide_index=True, use_container_width=True, height=420,
        column_config={
            "Amount": st.column_config.NumberColumn(format="$%.2f"),
            "Z-score": st.column_config.NumberColumn(format="%.1f"),
            "ML score": st.column_config.ProgressColumn(
                format="%.3f", min_value=float(df["ANOMALY_SCORE"].min()),
                max_value=float(df["ANOMALY_SCORE"].max()),
            ),
        },
    )

with right:
    st.subheader("Flagged anomalies by country")
    by_country = (
        flagged.groupby("COUNTRY_CODE").size().reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    st.altair_chart(
        alt.Chart(by_country).mark_bar().encode(
            x=alt.X("count:Q", title="Flagged count"),
            y=alt.Y("COUNTRY_CODE:N", sort="-x", title=None),
            tooltip=["COUNTRY_CODE", "count"],
        ).properties(height=420),
        use_container_width=True,
    )

st.divider()

# ---------------------------------------------------------------------
# Score landscape: z-score vs ML score, colored by flag
# ---------------------------------------------------------------------
st.subheader("Anomaly landscape — every transaction scored")
plot_df = df.assign(
    Status=df["ML_ANOMALY_FLAG"].map({True: "Flagged", False: "Normal"})
)
st.altair_chart(
    alt.Chart(plot_df).mark_circle(size=70, opacity=0.7).encode(
        x=alt.X("AMOUNT_ZSCORE:Q", title="Amount z-score (deviation from user norm)",
                scale=alt.Scale(type="symlog")),
        y=alt.Y("ANOMALY_SCORE:Q", title="Isolation Forest anomaly score"),
        color=alt.Color("Status:N",
                        scale=alt.Scale(domain=["Normal", "Flagged"], range=["#7fb3d5", "#e74c3c"]),
                        legend=alt.Legend(orient="top")),
        tooltip=["USER_ID", "AMOUNT", "COUNTRY_CODE", "CHANNEL",
                 "AMOUNT_ZSCORE", "ANOMALY_SCORE"],
    ).properties(height=380),
    use_container_width=True,
)
