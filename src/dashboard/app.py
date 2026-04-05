"""
StoryQuant Dashboard — Redesigned
4-tab layout: Overview | Signals | News & Topics | Performance
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = str(ROOT / "data" / "storyquant.db")

# ── Page config (must be first Streamlit call) ────────────────
st.set_page_config(
    page_title="StoryQuant",
    page_icon="▲",
    layout="wide",
    initial_sidebar_state="expanded",
)

import plotly.io as pio
pio.templates.default = "plotly_dark"

# ── Global CSS ────────────────────────────────────────────────
st.markdown("""
<style>
  /* ---- Base ---- */
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600&display=swap');

  html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
  }

  /* ---- Hide chrome ---- */
  #MainMenu { visibility: hidden; }
  footer    { visibility: hidden; }
  header    { visibility: hidden; }

  /* ---- App background ---- */
  .stApp { background-color: #0d0f14; }

  /* ---- KPI cards ---- */
  [data-testid="stMetric"] {
    background: #141720;
    border: 1px solid #1f2535;
    border-radius: 6px;
    padding: 14px 16px;
  }
  [data-testid="stMetricLabel"] p {
    font-size: 0.72rem !important;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #5a6480 !important;
    font-family: 'DM Mono', monospace !important;
  }
  [data-testid="stMetricValue"] {
    font-size: 1.55rem !important;
    font-weight: 600 !important;
    color: #e8ecf4 !important;
  }
  [data-testid="stMetricDelta"] {
    font-size: 0.78rem !important;
    font-family: 'DM Mono', monospace !important;
  }

  /* ---- Tabs ---- */
  .stTabs [data-baseweb="tab-list"] {
    background: transparent;
    gap: 2px;
    border-bottom: 1px solid #1f2535;
  }
  .stTabs [data-baseweb="tab"] {
    background: transparent;
    border-radius: 0;
    color: #5a6480;
    font-size: 0.82rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 8px 18px;
    border-bottom: 2px solid transparent;
    font-family: 'DM Mono', monospace;
  }
  .stTabs [aria-selected="true"] {
    color: #e8ecf4 !important;
    border-bottom: 2px solid #3b82f6 !important;
    background: transparent !important;
  }

  /* ---- Section headers ---- */
  .sq-section {
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #3b82f6;
    font-family: 'DM Mono', monospace;
    margin: 0 0 10px 0;
    padding-bottom: 6px;
    border-bottom: 1px solid #1f2535;
  }

  /* ---- News cards ---- */
  .news-card {
    background: #141720;
    border-left: 3px solid #3b82f6;
    padding: 10px 14px;
    margin-bottom: 6px;
    border-radius: 0 4px 4px 0;
  }
  .news-card.exchange  { border-left-color: #f59e0b; }
  .news-card.twitter   { border-left-color: #38bdf8; }
  .news-card.community { border-left-color: #22c55e; }
  .news-card-time {
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: #5a6480;
  }
  .news-card-title {
    font-size: 0.82rem;
    color: #c8d0e0;
    line-height: 1.35;
    margin: 3px 0 0 0;
  }
  .news-card-source {
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    color: #3b82f6;
    text-transform: uppercase;
    margin-top: 4px;
  }

  /* ---- Alert badge ---- */
  .alert-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-weight: 500;
  }
  .alert-high   { background: #2d0f0f; color: #f87171; border: 1px solid #7f1d1d; }
  .alert-medium { background: #2d1f0f; color: #fbbf24; border: 1px solid #78350f; }
  .alert-low    { background: #0f1f2d; color: #60a5fa; border: 1px solid #1e3a5f; }

  /* ---- Sidebar ---- */
  section[data-testid="stSidebar"] {
    background: #0d0f14;
    border-right: 1px solid #1f2535;
  }
  section[data-testid="stSidebar"] .sq-sidebar-label {
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #5a6480;
    margin-bottom: 6px;
  }

  /* ---- Dataframe ---- */
  .stDataFrame {
    font-size: 0.8rem;
  }

  /* ---- Divider ---- */
  .sq-divider {
    border: none;
    border-top: 1px solid #1f2535;
    margin: 16px 0;
  }
</style>
""", unsafe_allow_html=True)


# ── DB connection ─────────────────────────────────────────────

@st.cache_resource
def get_db():
    try:
        from src.db.schema import thread_connection, init_db, get_connection
        conn = get_connection(DB_PATH)
        init_db(conn)
        return conn
    except Exception:
        return None


# ── Data loaders ──────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_articles(hours: int = 24, market: str = None) -> pd.DataFrame:
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    try:
        from src.db.queries import get_recent_articles
        return get_recent_articles(conn, hours=hours, market=market)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def load_topics(hours: int = 24) -> pd.DataFrame:
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    try:
        from src.db.queries import get_recent_topics
        return get_recent_topics(conn, hours=hours)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def load_events(hours: int = 24) -> pd.DataFrame:
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    try:
        from src.db.queries import get_recent_events
        return get_recent_events(conn, hours=hours)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def load_prices(ticker: str = None, hours: int = 72) -> pd.DataFrame:
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    try:
        from src.db.queries import get_recent_prices
        return get_recent_prices(conn, ticker=ticker, hours=hours)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_cross_market_signals() -> pd.DataFrame:
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    try:
        from src.analysis.cross_market import detect_cross_market_signals
        return detect_cross_market_signals(conn, hours=48)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=120)
def load_performance(days: int = 30) -> dict:
    conn = get_db()
    if conn is None:
        return {"has_data": False}
    try:
        from src.analysis.leaderboard import compute_performance
        return compute_performance(conn, days=days)
    except Exception:
        return {"has_data": False}


@st.cache_data(ttl=30)
def load_trade_stats() -> dict:
    conn = get_db()
    if conn is None:
        return {}
    try:
        from src.db.queries import get_trade_stats
        return get_trade_stats(conn)
    except Exception:
        return {}


@st.cache_data(ttl=30)
def load_trade_history(limit: int = 50) -> pd.DataFrame:
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    try:
        from src.db.queries import get_trade_history
        return get_trade_history(conn, limit=limit)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def get_db_stats() -> dict:
    conn = get_db()
    if conn is None:
        return {}
    try:
        stats = {}
        stats["articles"] = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        stats["events"]   = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        stats["prices"]   = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        stats["trades"]   = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        db_file = Path(DB_PATH)
        stats["db_size_mb"] = round(db_file.stat().st_size / 1024 / 1024, 2) if db_file.exists() else 0
        return stats
    except Exception:
        return {}


# ── Helper utilities ──────────────────────────────────────────

def fmt_pct(val, decimals=2) -> str:
    try:
        v = float(val)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.{decimals}f}%"
    except Exception:
        return "—"


def pct_delta(val) -> str:
    """Return delta string suitable for st.metric."""
    try:
        v = float(val)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"
    except Exception:
        return None


def severity_color(sev: str) -> str:
    m = {"high": "#f87171", "medium": "#fbbf24", "low": "#60a5fa"}
    return m.get(str(sev).lower(), "#8892a4")


def return_color(val) -> str:
    try:
        return "#22c55e" if float(val) >= 0 else "#f87171"
    except Exception:
        return "#8892a4"


def source_type_class(st_val: str) -> str:
    m = {
        "exchange_announcement": "exchange",
        "twitter": "twitter",
        "community": "community",
    }
    return m.get(str(st_val).lower(), "")


def _no_data(label: str = "No data available"):
    st.markdown(
        f'<div style="padding:24px;text-align:center;color:#5a6480;'
        f'font-family:DM Mono,monospace;font-size:0.78rem;border:1px dashed #1f2535;'
        f'border-radius:6px;">{label}</div>',
        unsafe_allow_html=True,
    )


def _section(title: str):
    st.markdown(f'<p class="sq-section">{title}</p>', unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────

with st.sidebar:
    st.markdown(
        '<span style="font-family:DM Mono,monospace;font-size:1.05rem;'
        'font-weight:500;color:#e8ecf4;letter-spacing:0.05em;">▲ StoryQuant</span>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr style="border-color:#1f2535;margin:10px 0 16px 0;">', unsafe_allow_html=True)

    # Market filter
    st.markdown('<p class="sq-sidebar-label">Market</p>', unsafe_allow_html=True)
    market_filter = st.multiselect(
        label="market",
        options=["crypto", "us", "kr"],
        default=["crypto", "us", "kr"],
        label_visibility="collapsed",
    )

    st.markdown('<hr style="border-color:#1f2535;margin:12px 0;">', unsafe_allow_html=True)

    # Time window
    st.markdown('<p class="sq-sidebar-label">Time Window</p>', unsafe_allow_html=True)
    time_window = st.radio(
        label="time_window",
        options=["1h", "6h", "24h", "7d"],
        index=2,
        horizontal=True,
        label_visibility="collapsed",
    )
    _hours_map = {"1h": 1, "6h": 6, "24h": 24, "7d": 168}
    selected_hours = _hours_map[time_window]

    st.markdown('<hr style="border-color:#1f2535;margin:12px 0;">', unsafe_allow_html=True)

    # DB stats (compact)
    stats = get_db_stats()
    if stats:
        st.markdown('<p class="sq-sidebar-label">Database</p>', unsafe_allow_html=True)
        cols = st.columns(2)
        with cols[0]:
            st.metric("Articles", f"{stats.get('articles', 0):,}")
            st.metric("Prices", f"{stats.get('prices', 0):,}")
        with cols[1]:
            st.metric("Events", f"{stats.get('events', 0):,}")
            st.metric("Trades", f"{stats.get('trades', 0):,}")
        st.caption(f"DB: {stats.get('db_size_mb', 0)} MB")
    else:
        st.caption("No DB connection")

    st.markdown('<hr style="border-color:#1f2535;margin:12px 0;">', unsafe_allow_html=True)
    st.caption(f"Updated {datetime.now().strftime('%H:%M:%S')}")


# ── Top-level header ──────────────────────────────────────────

_now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
st.markdown(
    f'<div style="display:flex;align-items:baseline;gap:16px;margin-bottom:8px;">'
    f'<span style="font-size:1.35rem;font-weight:600;color:#e8ecf4;'
    f'font-family:DM Sans,sans-serif;letter-spacing:-0.01em;">StoryQuant</span>'
    f'<span style="font-family:DM Mono,monospace;font-size:0.7rem;color:#5a6480;">'
    f'News-driven multi-asset intelligence</span>'
    f'<span style="margin-left:auto;font-family:DM Mono,monospace;font-size:0.68rem;'
    f'color:#3b4560;">{_now_str}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# ── Main tabs ─────────────────────────────────────────────────

tab_overview, tab_signals, tab_news, tab_perf = st.tabs([
    "Overview", "Signals", "News & Topics", "Performance"
])


# ══════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════

with tab_overview:

    # Load data for the selected window
    ov_events   = load_events(hours=selected_hours)
    ov_articles = load_articles(hours=selected_hours)
    ov_topics   = load_topics(hours=selected_hours)
    trade_stats = load_trade_stats()

    # ── KPI row ──
    k1, k2, k3, k4 = st.columns(4)

    with k1:
        st.metric(
            "Articles",
            f"{len(ov_articles):,}",
            delta=f"{time_window} window",
        )
    with k2:
        n_events = len(ov_events) if not ov_events.empty else 0
        n_high   = 0
        if not ov_events.empty and "severity" in ov_events.columns:
            n_high = int((ov_events["severity"] == "high").sum())
        st.metric(
            "Events",
            f"{n_events:,}",
            delta=f"{n_high} high severity" if n_high else None,
            delta_color="inverse" if n_high else "normal",
        )
    with k3:
        # Top signal: highest absolute return event
        top_signal_label = "—"
        if not ov_events.empty and "return_1h" in ov_events.columns:
            ev_sorted = ov_events.dropna(subset=["return_1h"]).copy()
            if not ev_sorted.empty:
                ev_sorted["_abs"] = ev_sorted["return_1h"].abs()
                top_ev = ev_sorted.loc[ev_sorted["_abs"].idxmax()]
                ticker = top_ev.get("ticker", "?")
                ret    = top_ev["return_1h"]
                top_signal_label = f"{ticker} {fmt_pct(ret * 100, 1)}"
        st.metric("Top Signal", top_signal_label)
    with k4:
        pnl_val  = trade_stats.get("total_pnl", 0)
        win_rate = trade_stats.get("win_rate", 0)
        st.metric(
            "Portfolio PnL",
            fmt_pct(pnl_val),
            delta=f"Win rate {win_rate:.0f}%" if win_rate else None,
            delta_color="normal" if pnl_val >= 0 else "inverse",
        )

    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)

    # ── Two-column layout ──
    col_left, col_right = st.columns([3, 2])

    with col_left:
        # Price sparklines for BTC, ETH, SPY
        _section("Price Overview — BTC / ETH / SPY")
        sparkline_tickers = ["BTC-USD", "ETH-USD", "SPY"]
        price_frames = {}
        for _t in sparkline_tickers:
            _df = load_prices(ticker=_t, hours=selected_hours)
            if not _df.empty and "timestamp" in _df.columns and "close" in _df.columns:
                _df["timestamp"] = pd.to_datetime(_df["timestamp"], utc=True, errors="coerce")
                _df = _df.dropna(subset=["timestamp", "close"]).sort_values("timestamp")
                price_frames[_t] = _df

        if price_frames:
            _COLORS = {"BTC-USD": "#f59e0b", "ETH-USD": "#8b5cf6", "SPY": "#22c55e"}
            fig = go.Figure()
            for _t, _df in price_frames.items():
                # Normalize to % change from first point
                first = _df["close"].iloc[0]
                pct   = (_df["close"] / first - 1) * 100
                fig.add_trace(go.Scatter(
                    x=_df["timestamp"],
                    y=pct,
                    name=_t.replace("-USD", ""),
                    mode="lines",
                    line=dict(color=_COLORS.get(_t, "#60a5fa"), width=1.5),
                    hovertemplate="%{x|%H:%M}<br>%{y:+.2f}%<extra>" + _t + "</extra>",
                ))
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                height=160,
                margin=dict(l=0, r=0, t=8, b=0),
                showlegend=True,
                legend=dict(
                    orientation="h", x=0, y=1.15,
                    font=dict(size=10, color="#8892a4"),
                    bgcolor="rgba(0,0,0,0)",
                ),
                xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                yaxis=dict(
                    showgrid=True,
                    gridcolor="#1a1f2e",
                    tickformat="+.1f",
                    ticksuffix="%",
                    tickfont=dict(size=9, color="#5a6480"),
                    zeroline=True,
                    zerolinecolor="#2a3050",
                    zerolinewidth=1,
                ),
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            _no_data("No price data in selected window")

        # Recent events table
        st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)
        _section(f"Recent Events (last 5)")

        if not ov_events.empty:
            display_cols = []
            col_map = {
                "timestamp":  "Time",
                "ticker":     "Ticker",
                "event_type": "Type",
                "return_1h":  "Return",
                "severity":   "Severity",
            }
            ev_disp = ov_events.copy()

            # Format timestamp
            if "timestamp" in ev_disp.columns:
                ev_disp["timestamp"] = pd.to_datetime(
                    ev_disp["timestamp"], utc=True, errors="coerce"
                ).dt.strftime("%m-%d %H:%M")

            # Format return
            if "return_1h" in ev_disp.columns:
                ev_disp["return_1h"] = ev_disp["return_1h"].apply(
                    lambda x: fmt_pct(float(x) * 100, 2) if pd.notna(x) else "—"
                )

            keep = [c for c in col_map if c in ev_disp.columns]
            ev_disp = ev_disp[keep].rename(columns=col_map).head(5)

            st.dataframe(
                ev_disp,
                use_container_width=True,
                hide_index=True,
                height=190,
            )
        else:
            _no_data(f"No events in the last {time_window}")

    with col_right:
        # Hot Topics bar chart
        _section("Hot Topics — Top 5")

        if not ov_topics.empty:
            tc = ov_topics.copy()
            # Pick ranking column
            rank_col = None
            for c in ["momentum_score", "frequency", "novelty_score"]:
                if c in tc.columns:
                    rank_col = c
                    break

            if rank_col and "topic_label" in tc.columns:
                tc = tc.dropna(subset=["topic_label", rank_col])
                tc = tc.sort_values(rank_col, ascending=False).head(5)
                tc["topic_label"] = tc["topic_label"].str[:30]

                # Color by momentum
                if "momentum_score" in tc.columns:
                    max_m = tc["momentum_score"].max()
                    min_m = tc["momentum_score"].min()
                    def _bar_color(m):
                        if max_m == min_m:
                            return "#3b82f6"
                        norm = (m - min_m) / (max_m - min_m)
                        if norm > 0.66:
                            return "#22c55e"
                        elif norm > 0.33:
                            return "#3b82f6"
                        return "#6366f1"
                    bar_colors = tc["momentum_score"].apply(_bar_color).tolist()
                else:
                    bar_colors = ["#3b82f6"] * len(tc)

                fig_t = go.Figure(go.Bar(
                    y=tc["topic_label"].tolist(),
                    x=tc[rank_col].tolist(),
                    orientation="h",
                    marker_color=bar_colors,
                    hovertemplate="%{y}<br>Score: %{x:.2f}<extra></extra>",
                ))
                fig_t.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    height=175,
                    margin=dict(l=0, r=0, t=4, b=0),
                    showlegend=False,
                    xaxis=dict(showgrid=True, gridcolor="#1a1f2e", tickfont=dict(size=9)),
                    yaxis=dict(showgrid=False, tickfont=dict(size=10, color="#c8d0e0")),
                )
                st.plotly_chart(fig_t, use_container_width=True, config={"displayModeBar": False})
            else:
                _no_data("Topic data incomplete")
        else:
            _no_data(f"No topics in the last {time_window}")

        # Cross-market alerts
        st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)
        _section("Cross-Market Alerts")

        xm_df = load_cross_market_signals()
        if not xm_df.empty:
            for _, row in xm_df.head(4).iterrows():
                src = row.get("source_ticker", "?")
                tgt = row.get("target_ticker", "?")
                tgt_ret = row.get("target_return", 0)
                lag     = row.get("lag_hours", 0)
                ret_pct = float(tgt_ret) * 100
                color   = "#22c55e" if ret_pct >= 0 else "#f87171"
                st.markdown(
                    f'<div style="background:#141720;border-left:3px solid {color};'
                    f'padding:7px 12px;margin-bottom:5px;border-radius:0 4px 4px 0;">'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.72rem;'
                    f'color:#8892a4;">{src}</span>'
                    f'<span style="color:#5a6480;margin:0 6px;">→</span>'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.72rem;'
                    f'color:#c8d0e0;">{tgt}</span>'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.72rem;'
                    f'color:{color};margin-left:8px;">{fmt_pct(ret_pct, 1)}</span>'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.65rem;'
                    f'color:#3b4560;margin-left:8px;">{lag:.0f}h lag</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            _no_data("No cross-market signals detected")


# ══════════════════════════════════════════════════════════════
# TAB 2 — SIGNALS
# ══════════════════════════════════════════════════════════════

with tab_signals:

    # ── Filters row ──
    f_col1, f_col2, f_col3 = st.columns([2, 2, 4])
    with f_col1:
        sev_filter = st.radio(
            "Severity",
            options=["All", "High", "Medium"],
            horizontal=True,
            index=0,
        )
    with f_col2:
        mkt_filter = st.radio(
            "Market",
            options=["All", "Crypto", "US", "KR"],
            horizontal=True,
            index=0,
        )

    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)

    # ── Events table ──
    _section("Price Events")

    sig_events = load_events(hours=selected_hours).copy()

    # Apply filters
    if not sig_events.empty:
        if sev_filter != "All" and "severity" in sig_events.columns:
            sig_events = sig_events[
                sig_events["severity"].str.lower() == sev_filter.lower()
            ]
        if mkt_filter != "All":
            _mkt_ticker_map = {
                "Crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "BTC-USDT", "ETH-USDT", "SOL-USDT"],
                "US":     ["NVDA", "AAPL", "TSLA", "SPY"],
                "KR":     ["005930.KS", "000660.KS", "035420.KS"],
            }
            allowed = _mkt_ticker_map.get(mkt_filter, [])
            if "ticker" in sig_events.columns:
                sig_events = sig_events[sig_events["ticker"].isin(allowed)]

    if not sig_events.empty:
        ev_table = sig_events.copy()

        # Format columns
        if "timestamp" in ev_table.columns:
            ev_table["timestamp"] = pd.to_datetime(
                ev_table["timestamp"], utc=True, errors="coerce"
            ).dt.strftime("%m-%d %H:%M")

        if "return_1h" in ev_table.columns:
            ev_table["return_1h"] = ev_table["return_1h"].apply(
                lambda x: fmt_pct(float(x) * 100, 2) if pd.notna(x) else "—"
            )

        if "volume_ratio" in ev_table.columns:
            ev_table["volume_ratio"] = ev_table["volume_ratio"].apply(
                lambda x: f"{float(x):.1f}x" if pd.notna(x) else "—"
            )

        keep_cols = {
            "timestamp":    "Time",
            "ticker":       "Ticker",
            "event_type":   "Type",
            "severity":     "Severity",
            "return_1h":    "Return",
            "volume_ratio": "Vol Ratio",
        }
        present = [c for c in keep_cols if c in ev_table.columns]
        ev_table = ev_table[present].rename(columns=keep_cols)

        st.dataframe(
            ev_table,
            use_container_width=True,
            hide_index=True,
            height=320,
        )
    else:
        _no_data(f"No events match the selected filters ({time_window})")

    # ── Cross-market signals ──
    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)
    _section("Cross-Market Lead-Lag Signals")

    xm_signals = load_cross_market_signals()

    if not xm_signals.empty:
        xm_display = xm_signals.copy()

        if "source_return" in xm_display.columns:
            xm_display["source_return"] = xm_display["source_return"].apply(
                lambda x: fmt_pct(float(x) * 100, 2) if pd.notna(x) else "—"
            )
        if "target_return" in xm_display.columns:
            xm_display["target_return"] = xm_display["target_return"].apply(
                lambda x: fmt_pct(float(x) * 100, 2) if pd.notna(x) else "—"
            )
        if "lag_hours" in xm_display.columns:
            xm_display["lag_hours"] = xm_display["lag_hours"].apply(
                lambda x: f"{float(x):.0f}h" if pd.notna(x) else "—"
            )

        col_rename = {
            "source_ticker": "Leader",
            "source_event":  "Leader Event",
            "source_return": "Leader Return",
            "target_ticker": "Follower",
            "target_event":  "Follower Event",
            "target_return": "Follower Return",
            "lag_hours":     "Lag",
        }
        present = [c for c in col_rename if c in xm_display.columns]
        xm_display = xm_display[present].rename(columns=col_rename)

        st.dataframe(
            xm_display,
            use_container_width=True,
            hide_index=True,
            height=220,
        )
    else:
        _no_data("No cross-market signals detected in the last 48h")


# ══════════════════════════════════════════════════════════════
# TAB 3 — NEWS & TOPICS
# ══════════════════════════════════════════════════════════════

with tab_news:

    news_col, topic_col = st.columns([3, 2])

    # ── News feed ──
    with news_col:
        _section(f"News Feed — {time_window}")

        news_df = load_articles(hours=selected_hours)

        # Apply market filter
        if not news_df.empty and market_filter and "market" in news_df.columns:
            news_df = news_df[news_df["market"].isin(market_filter)]

        if not news_df.empty:
            # Ensure timestamp is parsed
            if "published_at" in news_df.columns:
                news_df["published_at"] = pd.to_datetime(
                    news_df["published_at"], utc=True, errors="coerce"
                )
                news_df = news_df.sort_values("published_at", ascending=False)

            shown = 0
            for _, row in news_df.iterrows():
                if shown >= 30:
                    break
                title    = row.get("title", "")
                source   = row.get("source", "")
                src_type = str(row.get("source_type", "rss"))
                market   = str(row.get("market", ""))
                ts       = row.get("published_at", None)

                if not title:
                    continue

                ts_str = ""
                if pd.notna(ts):
                    ts_str = pd.Timestamp(ts).strftime("%m-%d %H:%M")

                card_class = source_type_class(src_type)
                mkt_badge  = f'<span style="font-size:0.6rem;background:#1a2535;color:#60a5fa;padding:1px 6px;border-radius:2px;margin-left:6px;">{market.upper()}</span>' if market else ""

                st.markdown(
                    f'<div class="news-card {card_class}">'
                    f'<div class="news-card-time">{ts_str}{mkt_badge}</div>'
                    f'<div class="news-card-title">{title}</div>'
                    f'<div class="news-card-source">{source}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                shown += 1
        else:
            _no_data(f"No articles in the last {time_window}")

    # ── Topics panel ──
    with topic_col:
        _section(f"Topic Ranking — {time_window}")

        topics_df = load_topics(hours=selected_hours)

        if not topics_df.empty:
            rank_col = None
            for c in ["momentum_score", "frequency", "novelty_score"]:
                if c in topics_df.columns:
                    rank_col = c
                    break

            if rank_col and "topic_label" in topics_df.columns:
                tc = topics_df.dropna(subset=["topic_label", rank_col]).copy()
                tc = tc.sort_values(rank_col, ascending=False).head(15)
                tc["topic_label"] = tc["topic_label"].str[:32]

                # Render as ranked list
                for i, (_, row) in enumerate(tc.iterrows(), 1):
                    label = row["topic_label"]
                    score = float(row[rank_col])
                    freq  = int(row["frequency"]) if "frequency" in row and pd.notna(row.get("frequency")) else 0

                    # Bar width as percentage of max
                    max_score = float(tc[rank_col].max())
                    bar_w = int((score / max_score) * 100) if max_score > 0 else 0

                    rank_color = "#22c55e" if i <= 3 else "#3b82f6" if i <= 7 else "#6366f1"

                    st.markdown(
                        f'<div style="margin-bottom:8px;">'
                        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:3px;">'
                        f'<span style="font-family:DM Mono,monospace;font-size:0.65rem;'
                        f'color:{rank_color};width:18px;">#{i}</span>'
                        f'<span style="font-size:0.8rem;color:#c8d0e0;">{label}</span>'
                        f'<span style="margin-left:auto;font-family:DM Mono,monospace;'
                        f'font-size:0.68rem;color:#5a6480;">{freq} art</span>'
                        f'</div>'
                        f'<div style="height:3px;background:#1a1f2e;border-radius:2px;">'
                        f'<div style="height:3px;width:{bar_w}%;background:{rank_color};border-radius:2px;"></div>'
                        f'</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        else:
            _no_data(f"No topics in the last {time_window}")

        # Topic heatmap (if enough data)
        st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)
        _section("Topic Momentum Heatmap")

        if not topics_df.empty and "momentum_score" in topics_df.columns and "topic_label" in topics_df.columns:
            hm_data = topics_df.dropna(subset=["topic_label", "momentum_score"]).copy()
            hm_data = hm_data.sort_values("momentum_score", ascending=False).head(12)

            if len(hm_data) >= 4:
                fig_hm = go.Figure(go.Bar(
                    x=hm_data["topic_label"].str[:20].tolist(),
                    y=hm_data["momentum_score"].tolist(),
                    marker=dict(
                        color=hm_data["momentum_score"].tolist(),
                        colorscale=[[0, "#1e3a5f"], [0.5, "#3b82f6"], [1, "#22c55e"]],
                        showscale=False,
                    ),
                    hovertemplate="%{x}<br>Momentum: %{y:.3f}<extra></extra>",
                ))
                fig_hm.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    height=160,
                    margin=dict(l=0, r=0, t=4, b=40),
                    showlegend=False,
                    xaxis=dict(
                        showgrid=False,
                        tickangle=-30,
                        tickfont=dict(size=9, color="#8892a4"),
                    ),
                    yaxis=dict(
                        showgrid=True,
                        gridcolor="#1a1f2e",
                        tickfont=dict(size=9, color="#5a6480"),
                    ),
                )
                st.plotly_chart(fig_hm, use_container_width=True, config={"displayModeBar": False})
            else:
                _no_data("Not enough topic data for heatmap")
        else:
            _no_data("No momentum data available")


# ══════════════════════════════════════════════════════════════
# TAB 4 — PERFORMANCE
# ══════════════════════════════════════════════════════════════

with tab_perf:

    perf_days = st.select_slider(
        "Performance window",
        options=[7, 14, 30, 60, 90],
        value=30,
        label_visibility="collapsed",
        format_func=lambda x: f"Last {x} days",
    )

    perf = load_performance(days=perf_days)

    # ── KPI row ──
    p1, p2, p3, p4 = st.columns(4)

    if perf.get("has_data"):
        with p1:
            total_pnl = perf.get("total_pnl", 0)
            st.metric(
                "Total PnL",
                fmt_pct(total_pnl),
                delta=pct_delta(total_pnl),
                delta_color="normal" if total_pnl >= 0 else "inverse",
            )
        with p2:
            wr = perf.get("win_rate", 0)
            wins   = perf.get("wins", 0)
            losses = perf.get("losses", 0)
            st.metric(
                "Win Rate",
                f"{wr:.0%}",
                delta=f"{wins}W / {losses}L",
            )
        with p3:
            pf = perf.get("profit_factor", 0)
            st.metric(
                "Profit Factor",
                f"{pf:.2f}" if pf != float("inf") else "∞",
                delta="above 1 is profitable" if pf > 1 else None,
            )
        with p4:
            st.metric(
                "Trades",
                f"{perf.get('closed_trades', 0)}",
                delta=f"{perf.get('open_trades', 0)} open",
            )
    else:
        with p1:
            st.metric("Total PnL", "—")
        with p2:
            st.metric("Win Rate", "—")
        with p3:
            st.metric("Profit Factor", "—")
        with p4:
            st.metric("Trades", "—")

    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)

    # ── Per-ticker table ──
    perf_left, perf_right = st.columns([3, 2])

    with perf_left:
        _section("Per-Ticker Performance")

        if perf.get("has_data") and perf.get("per_ticker"):
            ticker_rows = []
            for ticker, s in sorted(
                perf["per_ticker"].items(),
                key=lambda x: x[1]["total_pnl"],
                reverse=True,
            ):
                ticker_rows.append({
                    "Ticker":    ticker,
                    "Trades":    s["trades"],
                    "Win Rate":  f"{s['win_rate']:.0%}",
                    "Total PnL": fmt_pct(s["total_pnl"], 2),
                    "Avg PnL":   fmt_pct(s["avg_pnl"], 2),
                    "Best":      fmt_pct(s["best"], 2),
                    "Worst":     fmt_pct(s["worst"], 2),
                })

            st.dataframe(
                pd.DataFrame(ticker_rows),
                use_container_width=True,
                hide_index=True,
                height=260,
            )
        else:
            _no_data("No closed trades in the selected period")

    with perf_right:
        _section("Summary Stats")

        if perf.get("has_data"):
            summary_items = [
                ("Avg PnL / Trade", fmt_pct(perf.get("avg_pnl", 0), 2)),
                ("Best Trade",      fmt_pct(perf.get("max_win", 0), 2)),
                ("Worst Trade",     fmt_pct(perf.get("max_loss", 0), 2)),
                ("Win Streak",      str(perf.get("max_win_streak", 0))),
                ("Loss Streak",     str(perf.get("max_loss_streak", 0))),
                ("Period",          f"{perf.get('period_days', perf_days)}d"),
            ]
            for label, value in summary_items:
                is_pos = value.startswith("+")
                is_neg = value.startswith("-")
                val_color = "#22c55e" if is_pos else "#f87171" if is_neg else "#c8d0e0"
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'padding:8px 0;border-bottom:1px solid #1a1f2e;">'
                    f'<span style="font-size:0.8rem;color:#8892a4;">{label}</span>'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.82rem;'
                    f'color:{val_color};font-weight:500;">{value}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            _no_data("No performance data available")

    # ── Trade history ──
    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)
    _section("Trade History")

    trade_hist = load_trade_history(limit=50)
    if not trade_hist.empty:
        th = trade_hist.copy()

        # Format timestamps
        for tc in ["entry_time", "exit_time", "created_at"]:
            if tc in th.columns:
                th[tc] = pd.to_datetime(th[tc], errors="coerce").dt.strftime("%m-%d %H:%M")

        # Format pnl
        if "pnl_pct" in th.columns:
            th["pnl_pct"] = th["pnl_pct"].apply(
                lambda x: fmt_pct(float(x), 2) if pd.notna(x) else "—"
            )

        keep = {
            "entry_time":   "Entry",
            "exit_time":    "Exit",
            "ticker":       "Ticker",
            "direction":    "Dir",
            "signal_type":  "Signal",
            "entry_price":  "Entry $",
            "exit_price":   "Exit $",
            "pnl_pct":      "PnL",
            "status":       "Status",
        }
        present = [c for c in keep if c in th.columns]
        th = th[present].rename(columns=keep)

        # Round price columns
        for col in ["Entry $", "Exit $"]:
            if col in th.columns:
                th[col] = pd.to_numeric(th[col], errors="coerce").round(4)

        st.dataframe(
            th,
            use_container_width=True,
            hide_index=True,
            height=280,
        )
    else:
        _no_data("No trade history available")
