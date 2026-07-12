"""
streamlit_app.py — Fraud & Audit Command Center (Streamlit-in-Snowflake)
------------------------------------------------------------------
Premium dark "command center" UI over the live inference view
FRAUD_DB.ANALYTICS.FRAUD_PREDICTIONS. Runs inside Snowflake (container
runtime). Uses only stable Streamlit APIs + a theme file + Altair so it
renders reliably on the SiS runtime.
"""

import altair as alt
import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session

st.set_page_config(
    page_title="Fraud & Audit Command Center",
    page_icon="\U0001F6E1\uFE0F",
    layout="wide",
)

# --- Palette ---------------------------------------------------------------
BLUE = "#29B5E8"
RED = "#FF4B4B"
AMBER = "#F5A623"
GREEN = "#2ECC71"
MUTED = "#8AA0BC"
CARD_BG = "linear-gradient(145deg,#16233A,#101A2B)"

# --- Global CSS (safe: layout padding, pulse animation, scrollbar) ---------
st.markdown(
    """
    <style>
      .stApp {background-color: #0B1220;}
      [data-testid="stAppViewContainer"], [data-testid="stMain"] {background-color: #0B1220;}
      [data-testid="stHeader"] {background: rgba(0,0,0,0);}
      body, .stApp, .stMarkdown, p, span, li, h1, h2, h3, h4 {color: #E6EDF3;}
      .block-container {padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1500px;}
      @keyframes pulse {0%{opacity:1;} 50%{opacity:0.25;} 100%{opacity:1;}}
      .live-dot {height:9px; width:9px; background:#2ECC71; border-radius:50%;
                 display:inline-block; margin-right:7px; animation:pulse 1.6s infinite;}
      ::-webkit-scrollbar {height:8px; width:8px;}
      ::-webkit-scrollbar-thumb {background:#2A3A52; border-radius:8px;}
    </style>
    """,
    unsafe_allow_html=True,
)

session = get_active_session()


@st.cache_data(ttl=60, show_spinner="Loading scored transactions from Snowflake...")
def load_predictions() -> pd.DataFrame:
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


def severity(row) -> str:
    if not row["ML_ANOMALY_FLAG"]:
        return "Normal"
    return "Critical" if row["ANOMALY_SCORE"] >= 0.78 else "High"


df = load_predictions()
df["STATUS"] = df.apply(severity, axis=1)

# --- Aggregates ------------------------------------------------------------
total_txns = len(df)
flagged = df[df["ML_ANOMALY_FLAG"]]
n_flagged = len(flagged)
n_critical = int((df["STATUS"] == "Critical").sum())
exposure = float(flagged["AMOUNT"].sum())
flag_rate = (n_flagged / total_txns * 100) if total_txns else 0
tp = int((df["ML_ANOMALY_FLAG"] & df["IS_SYNTHETIC_ANOMALY"]).sum())
precision = (tp / n_flagged) if n_flagged else 0.0
recall = (tp / int(df["IS_SYNTHETIC_ANOMALY"].sum())) if df["IS_SYNTHETIC_ANOMALY"].sum() else 0.0


def theme(ch):
    return (
        ch.configure(background="rgba(0,0,0,0)")
        .configure_view(strokeWidth=0)
        .configure_axis(labelColor="#9BB0C9", titleColor="#C9D6E5",
                        gridColor="#1E2A3C", domainColor="#2A3A52", tickColor="#2A3A52")
        .configure_legend(labelColor="#C9D6E5", titleColor="#C9D6E5")
    )


STATUS_SCALE = alt.Scale(domain=["Normal", "High", "Critical"],
                         range=["#3E5C76", AMBER, RED])

# =============================================================================
# Hero banner
# =============================================================================
st.markdown(
    """
    <div style="background:linear-gradient(120deg,#0E2338 0%,#123A57 55%,#0B2E4A 100%);
         border:1px solid #1E3A57; border-radius:16px; padding:22px 26px; margin-bottom:18px;
         box-shadow:0 6px 26px rgba(0,0,0,0.4);">
      <div style="display:flex; align-items:center; gap:16px; flex-wrap:wrap;">
        <span style="font-size:36px;">&#x1F6E1;&#xFE0F;</span>
        <div>
          <div style="font-size:27px; font-weight:800; color:#E6F2FB; letter-spacing:0.3px;">
            Fraud &amp; Audit Command Center</div>
          <div style="font-size:13px; color:#8FB6D4; margin-top:2px;">
            Real-time detection &middot; 100% native Snowflake &middot;
            streaming &rarr; Dynamic Tables &rarr; Isolation Forest V2</div>
        </div>
        <div style="margin-left:auto; text-align:right;">
          <div style="font-size:12px; color:#2ECC71; font-weight:700;">
            <span class="live-dot"></span>MONITORING ACTIVE</div>
          <div style="font-size:11px; color:#6E86A3; margin-top:3px;">Model V2 &middot; serverless alerts armed</div>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

hc1, hc2 = st.columns([6, 1])
with hc2:
    if st.button("Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# =============================================================================
# KPI tiles
# =============================================================================
def kpi(label, value, accent, sub):
    return (
        f'<div style="flex:1; min-width:190px; background:{CARD_BG}; border:1px solid #22314A;'
        f' border-left:4px solid {accent}; border-radius:14px; padding:16px 20px;'
        f' box-shadow:0 4px 18px rgba(0,0,0,0.35);">'
        f'<div style="font-size:11px; letter-spacing:1.2px; text-transform:uppercase; color:{MUTED};">{label}</div>'
        f'<div style="font-size:30px; font-weight:800; color:{accent}; margin-top:6px;">{value}</div>'
        f'<div style="font-size:12px; color:#7E93AE; margin-top:4px;">{sub}</div></div>'
    )


st.markdown(
    '<div style="display:flex; gap:16px; flex-wrap:wrap; margin-bottom:20px;">'
    + kpi("Transactions Scored", f"{total_txns:,}", BLUE, "live inference view")
    + kpi("Anomalies Flagged", f"{n_flagged:,}", RED, f"{flag_rate:.1f}% of volume &middot; {n_critical} critical")
    + kpi("Flagged $ Exposure", f"${exposure:,.0f}", AMBER, "value at risk")
    + kpi("Detection Precision / Recall", f"{precision:.0%} / {recall:.0%}", GREEN, "Isolation Forest V2")
    + "</div>",
    unsafe_allow_html=True,
)

# =============================================================================
# Centerpiece: anomaly landscape
# =============================================================================
st.markdown("#### Anomaly Landscape &mdash; every transaction scored", unsafe_allow_html=True)
scatter = (
    alt.Chart(df).mark_circle(opacity=0.8, stroke="#0B1220", strokeWidth=0.4).encode(
        x=alt.X("AMOUNT_ZSCORE:Q", title="Deviation from user's norm (z-score, symlog)",
                scale=alt.Scale(type="symlog")),
        y=alt.Y("ANOMALY_SCORE:Q", title="Isolation Forest anomaly score"),
        size=alt.Size("AMOUNT:Q", title="Amount", scale=alt.Scale(range=[30, 900]),
                      legend=alt.Legend(orient="bottom")),
        color=alt.Color("STATUS:N", scale=STATUS_SCALE,
                        legend=alt.Legend(orient="bottom", title="Risk tier")),
        tooltip=[alt.Tooltip("USER_ID:N", title="User"),
                 alt.Tooltip("AMOUNT:Q", title="Amount", format="$,.2f"),
                 alt.Tooltip("COUNTRY_CODE:N", title="Country"),
                 alt.Tooltip("CHANNEL:N", title="Channel"),
                 alt.Tooltip("ANOMALY_SCORE:Q", title="ML score", format=".3f"),
                 alt.Tooltip("STATUS:N", title="Risk")],
    ).properties(height=360)
)
st.altair_chart(theme(scatter), use_container_width=True)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# =============================================================================
# Worklist + by-country
# =============================================================================
left, right = st.columns([3, 2])

with left:
    st.markdown("#### &#x1F6A8; Auditor Worklist &mdash; highest risk first", unsafe_allow_html=True)
    badge = {"Critical": "\U0001F534 Critical", "High": "\U0001F7E0 High"}
    worklist = flagged.sort_values("ANOMALY_SCORE", ascending=False).copy()
    worklist["Risk"] = worklist["STATUS"].map(badge)
    show = worklist[["Risk", "EVENT_TS", "USER_ID", "AMOUNT", "MERCHANT_CATEGORY",
                     "COUNTRY_CODE", "CHANNEL", "AMOUNT_ZSCORE", "ANOMALY_SCORE"]].rename(
        columns={"EVENT_TS": "Time", "USER_ID": "User", "AMOUNT": "Amount",
                 "MERCHANT_CATEGORY": "Category", "COUNTRY_CODE": "Country",
                 "CHANNEL": "Channel", "AMOUNT_ZSCORE": "Z-score", "ANOMALY_SCORE": "ML score"})
    st.dataframe(
        show, hide_index=True, use_container_width=True, height=360,
        column_config={
            "Amount": st.column_config.NumberColumn(format="$%.2f"),
            "Z-score": st.column_config.NumberColumn(format="%.1f"),
            "ML score": st.column_config.ProgressColumn(
                format="%.3f", min_value=float(df["ANOMALY_SCORE"].min()),
                max_value=float(df["ANOMALY_SCORE"].max())),
        },
    )

with right:
    st.markdown("#### &#x1F30D; Flagged by Country", unsafe_allow_html=True)
    by_country = (flagged.groupby("COUNTRY_CODE").size().reset_index(name="count")
                  .sort_values("count", ascending=False))
    country_chart = (
        alt.Chart(by_country).mark_bar(cornerRadiusEnd=4, color=RED).encode(
            x=alt.X("count:Q", title="Flagged transactions"),
            y=alt.Y("COUNTRY_CODE:N", sort="-x", title=None),
            tooltip=["COUNTRY_CODE", "count"],
        ).properties(height=360)
    )
    st.altair_chart(theme(country_chart), use_container_width=True)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# =============================================================================
# Category breakdown + score distribution
# =============================================================================
c1, c2 = st.columns(2)

with c1:
    st.markdown("#### Flagged by Merchant Category", unsafe_allow_html=True)
    by_cat = (flagged.groupby("MERCHANT_CATEGORY").size().reset_index(name="count")
              .sort_values("count", ascending=False))
    cat_chart = (
        alt.Chart(by_cat).mark_bar(cornerRadiusEnd=4, color=AMBER).encode(
            x=alt.X("count:Q", title="Flagged transactions"),
            y=alt.Y("MERCHANT_CATEGORY:N", sort="-x", title=None),
            tooltip=["MERCHANT_CATEGORY", "count"],
        ).properties(height=300)
    )
    st.altair_chart(theme(cat_chart), use_container_width=True)

with c2:
    st.markdown("#### Score Distribution &mdash; Normal vs Flagged", unsafe_allow_html=True)
    dist_df = df.assign(Group=df["ML_ANOMALY_FLAG"].map({True: "Flagged", False: "Normal"}))
    hist = (
        alt.Chart(dist_df).mark_bar(opacity=0.75).encode(
            x=alt.X("ANOMALY_SCORE:Q", bin=alt.Bin(maxbins=40), title="Anomaly score"),
            y=alt.Y("count():Q", title="Transactions", stack=None),
            color=alt.Color("Group:N",
                            scale=alt.Scale(domain=["Normal", "Flagged"], range=["#3E5C76", RED]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["Group", "count()"],
        ).properties(height=300)
    )
    st.altair_chart(theme(hist), use_container_width=True)

st.markdown(
    "<div style='text-align:center; margin-top:14px; font-size:11px; color:#5E738F;'>"
    "Snowflake-native pipeline &middot; Snowpipe Streaming &rarr; Dynamic Tables &rarr; Model Registry (V2) "
    "&rarr; Streamlit-in-Snowflake &middot; serverless email alerts</div>",
    unsafe_allow_html=True,
)
