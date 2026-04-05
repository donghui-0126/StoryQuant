"""
StoryQuant Dashboard — Narrative-Driven
4-tab layout: Narratives | Signals & Events | News Feed | Performance
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

  /* ---- Narrative cards ---- */
  .narrative-card {
    background: #141720;
    border-radius: 6px;
    padding: 14px 16px;
    margin-bottom: 10px;
    border: 1px solid #1f2535;
  }
  .narrative-card.emerging { border-left: 4px solid #3b82f6; }
  .narrative-card.building { border-left: 4px solid #22c55e; }
  .narrative-card.peaking  { border-left: 4px solid #f59e0b; }
  .narrative-card.fading   { border-left: 4px solid #6b7280; }
  .narrative-title {
    font-size: 0.95rem;
    font-weight: 600;
    color: #e8ecf4;
  }
  .narrative-meta {
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: #5a6480;
    margin-top: 3px;
  }
  .narrative-assets {
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    color: #8892a4;
    margin-top: 6px;
  }
  .narrative-headline {
    font-size: 0.78rem;
    color: #5a6480;
    font-style: italic;
    margin-top: 4px;
  }
  .narrative-signal {
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    color: #60a5fa;
    margin-top: 6px;
    font-weight: 500;
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

  /* ---- Signal chip ---- */
  .signal-chip {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    font-weight: 500;
    margin-right: 6px;
    margin-bottom: 4px;
  }
  .chip-buy  { background: #052a1a; color: #22c55e; border: 1px solid #15803d; }
  .chip-sell { background: #2a0505; color: #f87171; border: 1px solid #7f1d1d; }
  .chip-neutral { background: #141720; color: #8892a4; border: 1px solid #1f2535; }

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
        from src.db.schema import thread_connection
        return thread_connection
    except Exception:
        return None


# ── Data loaders ──────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_narratives(hours: int = 24) -> list:
    try:
        from src.db.schema import thread_connection
        from src.analysis.narrative import detect_narratives
        with thread_connection() as conn:
            return detect_narratives(conn, hours=hours)
    except Exception:
        return []


@st.cache_data(ttl=30)
def load_composite_signals(hours: int = 6) -> pd.DataFrame:
    try:
        from src.db.schema import thread_connection
        from src.analysis.news_quant import compute_composite_signal
        with thread_connection() as conn:
            return compute_composite_signal(conn, hours=hours)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def load_articles(hours: int = 24, market: str = None) -> pd.DataFrame:
    try:
        from src.db.schema import thread_connection
        from src.db.queries import get_recent_articles
        with thread_connection() as conn:
            return get_recent_articles(conn, hours=hours, market=market)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def load_events(hours: int = 24) -> pd.DataFrame:
    try:
        from src.db.schema import thread_connection
        from src.db.queries import get_recent_events
        with thread_connection() as conn:
            return get_recent_events(conn, hours=hours)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_cross_market_signals() -> pd.DataFrame:
    try:
        from src.db.schema import thread_connection
        from src.analysis.cross_market import detect_cross_market_signals
        with thread_connection() as conn:
            return detect_cross_market_signals(conn, hours=48)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_cross_market_correlations() -> pd.DataFrame:
    try:
        from src.db.schema import thread_connection
        from src.analysis.cross_market import compute_cross_market_correlations
        with thread_connection() as conn:
            return compute_cross_market_correlations(conn)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=120)
def load_performance(days: int = 30) -> dict:
    try:
        from src.db.schema import thread_connection
        from src.analysis.leaderboard import compute_performance
        with thread_connection() as conn:
            return compute_performance(conn, days=days)
    except Exception:
        return {"has_data": False}


@st.cache_data(ttl=300)
def load_historical_context() -> str:
    try:
        from src.db.schema import thread_connection
        from src.analysis.historical import generate_historical_context
        with thread_connection() as conn:
            return generate_historical_context(conn)
    except Exception:
        return ""


@st.cache_data(ttl=30)
def get_db_stats() -> dict:
    try:
        from src.db.schema import thread_connection
        with thread_connection() as conn:
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


def severity_color(sev: str) -> str:
    m = {"high": "#f87171", "medium": "#fbbf24", "low": "#60a5fa"}
    return m.get(str(sev).lower(), "#8892a4")


def return_color(val) -> str:
    try:
        return "#22c55e" if float(val) >= 0 else "#f87171"
    except Exception:
        return "#8892a4"


def _no_data(label: str = "No data available"):
    st.markdown(
        f'<div style="padding:24px;text-align:center;color:#5a6480;'
        f'font-family:DM Mono,monospace;font-size:0.78rem;border:1px dashed #1f2535;'
        f'border-radius:6px;">{label}</div>',
        unsafe_allow_html=True,
    )


def _section(title: str):
    st.markdown(f'<p class="sq-section">{title}</p>', unsafe_allow_html=True)


_LIFECYCLE_ICON = {
    "EMERGING": "🌱",
    "BUILDING": "📈",
    "PEAKING":  "🔥",
    "FADING":   "📉",
}

_LIFECYCLE_COLOR = {
    "EMERGING": "#3b82f6",
    "BUILDING": "#22c55e",
    "PEAKING":  "#f59e0b",
    "FADING":   "#6b7280",
}

_LIFECYCLE_CLASS = {
    "EMERGING": "emerging",
    "BUILDING": "building",
    "PEAKING":  "peaking",
    "FADING":   "fading",
}


def _render_narrative_card(n: dict):
    lc = n.get("lifecycle", "FADING")
    icon = _LIFECYCLE_ICON.get(lc, "")
    lc_color = _LIFECYCLE_COLOR.get(lc, "#6b7280")
    lc_class = _LIFECYCLE_CLASS.get(lc, "fading")
    strength_pct = int(n.get("strength", 0) * 100)
    direction = n.get("direction", "bullish")
    dir_icon = "📈" if direction == "bullish" else "📉"
    dir_color = "#22c55e" if direction == "bullish" else "#f87171"
    sentiment = n.get("sentiment_bias", 0)
    sent_str = f"+{sentiment:.2f}" if sentiment >= 0 else f"{sentiment:.2f}"
    article_count = n.get("article_count", 0)
    label_ko = n.get("label_ko", n.get("label", ""))

    # Assets with price reactions
    assets = n.get("affected_assets", [])
    reactions = n.get("price_reactions", {})
    asset_parts = []
    for ticker in assets[:4]:
        ret = reactions.get(ticker, 0)
        ret_str = fmt_pct(ret * 100, 1) if ret != 0 else "+0.0%"
        color = "#22c55e" if ret >= 0 else "#f87171"
        asset_parts.append(
            f'<span style="color:{color};font-family:DM Mono,monospace;font-size:0.7rem;">'
            f'{ticker} {ret_str}</span>'
        )
    assets_html = " | ".join(asset_parts) if asset_parts else "—"

    # Sample headline
    headlines = n.get("headlines", [])
    headline_html = ""
    if headlines:
        h = headlines[0][:80] + ("…" if len(headlines[0]) > 80 else "")
        headline_html = f'<p class="narrative-headline">→ "{h}"</p>'

    # Signal tickers
    sigs = [
        f'{t} {"LONG" if direction == "bullish" else "SHORT"}'
        for t in assets[:3]
    ]
    signal_str = ", ".join(sigs) if sigs else ""

    st.markdown(f"""
<div class="narrative-card {lc_class}">
  <div style="display:flex;align-items:center;justify-content:space-between;">
    <span class="narrative-title">{icon} {label_ko}</span>
    <span style="font-family:DM Mono,monospace;font-size:0.68rem;
                 color:{lc_color};font-weight:600;letter-spacing:0.08em;">{lc} &nbsp;{strength_pct}%</span>
  </div>
  <p class="narrative-meta">
    <span style="color:{dir_color};">{dir_icon} {direction.upper()}</span>
    &nbsp;|&nbsp; 기사 {article_count}건
    &nbsp;|&nbsp; 감성 {sent_str}
  </p>
  <div style="margin:8px 0 4px 0;">
    <div style="background:#1f2535;border-radius:3px;height:4px;">
      <div style="background:{lc_color};width:{strength_pct}%;height:4px;border-radius:3px;"></div>
    </div>
  </div>
  <p class="narrative-assets">자산: {assets_html}</p>
  {headline_html}
  <p class="narrative-signal">⚡ Signal: {signal_str}</p>
</div>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────

with st.sidebar:
    st.markdown(
        '<span style="font-family:DM Mono,monospace;font-size:1.05rem;'
        'font-weight:500;color:#e8ecf4;letter-spacing:0.05em;">▲ StoryQuant</span>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr style="border-color:#1f2535;margin:10px 0 16px 0;">', unsafe_allow_html=True)

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

    # Market filter
    st.markdown('<p class="sq-sidebar-label">Market</p>', unsafe_allow_html=True)
    market_filter = st.multiselect(
        label="market",
        options=["crypto", "us", "kr"],
        default=["crypto", "us", "kr"],
        label_visibility="collapsed",
    )

    st.markdown('<hr style="border-color:#1f2535;margin:12px 0;">', unsafe_allow_html=True)

    # DB stats (compact)
    stats = get_db_stats()
    if stats:
        st.markdown(
            f'<p style="font-family:DM Mono,monospace;font-size:0.65rem;color:#5a6480;">'
            f'기사 {stats.get("articles",0):,} · 이벤트 {stats.get("events",0):,} · '
            f'가격 {stats.get("prices",0):,} · DB {stats.get("db_size_mb",0)}MB</p>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("No DB connection")

    st.caption(f"Updated {datetime.now().strftime('%H:%M:%S')}")


# ── Top-level header ──────────────────────────────────────────

_now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
st.markdown(
    f'<div style="display:flex;align-items:baseline;gap:16px;margin-bottom:8px;">'
    f'<span style="font-size:1.35rem;font-weight:600;color:#e8ecf4;'
    f'font-family:DM Sans,sans-serif;letter-spacing:-0.01em;">StoryQuant</span>'
    f'<span style="font-family:DM Mono,monospace;font-size:0.78rem;color:#5a6480;">'
    f'시장을 움직이는 스토리</span>'
    f'<span style="margin-left:auto;font-family:DM Mono,monospace;font-size:0.68rem;'
    f'color:#3b4560;">{_now_str}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# ── Main tabs ─────────────────────────────────────────────────

tab_narratives, tab_signals, tab_news, tab_perf = st.tabs([
    "Narratives", "Signals & Events", "News Feed", "Performance"
])


# ══════════════════════════════════════════════════════════════
# TAB 1 — NARRATIVES
# ══════════════════════════════════════════════════════════════

with tab_narratives:
    narratives = load_narratives(hours=selected_hours)

    # ── Active Narrative Cards ──
    _section("Active Narratives")

    if not narratives:
        _no_data(f"No active narratives detected in the last {time_window}")
    else:
        n_cols = min(len(narratives), 2)
        col_pairs = st.columns(n_cols)
        for i, n in enumerate(narratives):
            with col_pairs[i % n_cols]:
                _render_narrative_card(n)

    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)

    # ── Narrative Signals table ──
    _section("Narrative Signals")

    if narratives:
        try:
            from src.analysis.narrative import get_narrative_signals
            signals = get_narrative_signals(narratives)
        except Exception:
            signals = []

        if signals:
            sig_rows = []
            for s in signals:
                dir_icon = "🟢 LONG" if s["direction"] == "long" else "🔴 SHORT"
                conf_pct = f"{s['confidence']:.0%}"
                sig_rows.append({
                    "Ticker":     s["ticker"],
                    "Direction":  dir_icon,
                    "Narrative":  s["narrative"],
                    "Lifecycle":  s["lifecycle"],
                    "Confidence": conf_pct,
                })
            st.dataframe(
                pd.DataFrame(sig_rows),
                use_container_width=True,
                hide_index=True,
            )
        else:
            _no_data("No actionable signals (need EMERGING/BUILDING narratives with strength ≥ 30%)")
    else:
        _no_data("No narrative signals available")

    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)

    # ── News Quant Summary strip ──
    _section("News Quant — Composite Signals")

    composite_df = load_composite_signals(hours=min(selected_hours, 24))
    if not composite_df.empty and "composite_signal" in composite_df.columns:
        top3 = composite_df.nlargest(3, "signal_strength") if "signal_strength" in composite_df.columns else composite_df.head(3)
        chips_html = ""
        for _, row in top3.iterrows():
            ticker = row.get("ticker", "?")
            sig = row.get("composite_signal", 0)
            label = row.get("signal_label", "NEUTRAL")
            is_buy = sig > 0.05
            is_sell = sig < -0.05
            chip_class = "chip-buy" if is_buy else ("chip-sell" if is_sell else "chip-neutral")
            icon = "🟢" if is_buy else ("🔴" if is_sell else "⚪")
            sig_str = f"+{sig:.2f}" if sig >= 0 else f"{sig:.2f}"
            chips_html += f'<span class="signal-chip {chip_class}">{icon} {ticker} {label} {sig_str}</span>'

        st.markdown(
            f'<div style="padding:10px 0;">{chips_html}</div>',
            unsafe_allow_html=True,
        )
    else:
        _no_data("Composite signals not available")


# ══════════════════════════════════════════════════════════════
# TAB 2 — SIGNALS & EVENTS
# ══════════════════════════════════════════════════════════════

with tab_signals:

    # ── Price Events ──
    _section("Price Events")

    events_df = load_events(hours=selected_hours)

    if not events_df.empty:
        # Filters
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            sev_opts = ["All"] + sorted(events_df["severity"].dropna().unique().tolist()) if "severity" in events_df.columns else ["All"]
            sev_filter = st.selectbox("Severity", sev_opts, label_visibility="visible")
        with fc2:
            mkt_opts = ["All"] + sorted(events_df["market"].dropna().unique().tolist()) if "market" in events_df.columns else ["All"]
            mkt_sel = st.selectbox("Market", mkt_opts, label_visibility="visible")
        with fc3:
            etype_opts = ["All"] + sorted(events_df["event_type"].dropna().unique().tolist()) if "event_type" in events_df.columns else ["All"]
            etype_sel = st.selectbox("Event Type", etype_opts, label_visibility="visible")

        filtered = events_df.copy()
        if sev_filter != "All" and "severity" in filtered.columns:
            filtered = filtered[filtered["severity"] == sev_filter]
        if mkt_sel != "All" and "market" in filtered.columns:
            filtered = filtered[filtered["market"] == mkt_sel]
        if etype_sel != "All" and "event_type" in filtered.columns:
            filtered = filtered[filtered["event_type"] == etype_sel]

        display_cols = [c for c in ["timestamp", "ticker", "event_type", "return_1h", "severity", "cause"]
                        if c in filtered.columns]
        if display_cols:
            disp = filtered[display_cols].copy().head(100)
            if "return_1h" in disp.columns:
                disp["return_1h"] = disp["return_1h"].apply(
                    lambda v: fmt_pct(v * 100, 2) if pd.notna(v) else "—"
                )
            st.dataframe(disp, use_container_width=True, hide_index=True)
        else:
            st.dataframe(filtered.head(100), use_container_width=True, hide_index=True)
    else:
        _no_data(f"No price events in the last {time_window}")

    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)

    # ── Cross-Market Correlations ──
    _section("Cross-Market Correlations")

    corr_df = load_cross_market_correlations()
    if not corr_df.empty:
        display_cols = [c for c in ["leader", "follower", "correlation", "lag_hours", "signal_count"]
                        if c in corr_df.columns]
        if not display_cols:
            display_cols = corr_df.columns.tolist()
        st.dataframe(
            corr_df[display_cols].head(30),
            use_container_width=True,
            hide_index=True,
        )
    else:
        _no_data("Cross-market correlations not available (requires price history)")


# ══════════════════════════════════════════════════════════════
# TAB 3 — NEWS FEED
# ══════════════════════════════════════════════════════════════

with tab_news:

    # Time / market filter bar
    nf1, nf2 = st.columns([1, 2])
    with nf1:
        news_hours = st.radio(
            "Time",
            options=["1h", "6h", "12h", "24h"],
            index=2,
            horizontal=True,
            label_visibility="visible",
        )
        news_hours_int = {"1h": 1, "6h": 6, "12h": 12, "24h": 24}[news_hours]
    with nf2:
        news_market = st.radio(
            "Market",
            options=["All", "Crypto", "US", "KR"],
            index=0,
            horizontal=True,
            label_visibility="visible",
        )

    mkt_arg = None if news_market == "All" else news_market.lower()
    articles_df = load_articles(hours=news_hours_int, market=mkt_arg)

    _section(f"News Feed — {len(articles_df)} articles")

    if articles_df.empty:
        _no_data(f"No articles found for the last {news_hours}")
    else:
        now_utc = datetime.now(timezone.utc)

        def _time_ago(ts_str) -> str:
            try:
                ts = pd.to_datetime(ts_str, utc=True)
                delta = now_utc - ts.to_pydatetime()
                minutes = int(delta.total_seconds() / 60)
                if minutes < 60:
                    return f"{minutes}m ago"
                hours_ago = minutes // 60
                if hours_ago < 24:
                    return f"{hours_ago}h ago"
                return f"{hours_ago // 24}d ago"
            except Exception:
                return ts_str or "?"

        def _source_class(src: str) -> str:
            s = str(src).lower()
            if "exchange" in s or "binance" in s or "coinbase" in s:
                return "exchange"
            if "twitter" in s or "tweet" in s:
                return "twitter"
            if "reddit" in s or "community" in s:
                return "community"
            return ""

        for _, row in articles_df.head(50).iterrows():
            title = row.get("title", "")
            source = row.get("source", "")
            pub = row.get("published_at", row.get("timestamp", ""))
            src_class = _source_class(source)
            time_str = _time_ago(pub)

            st.markdown(
                f'<div class="news-card {src_class}">'
                f'<span class="news-card-time">{time_str}</span>'
                f'<p class="news-card-title">{title}</p>'
                f'<span class="news-card-source">{source}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ══════════════════════════════════════════════════════════════
# TAB 4 — PERFORMANCE
# ══════════════════════════════════════════════════════════════

with tab_perf:

    perf = load_performance(days=30)

    # ── KPI strip ──
    k1, k2, k3 = st.columns(3)
    with k1:
        total_pnl = perf.get("total_pnl_pct", perf.get("total_pnl", 0))
        st.metric(
            "Total PnL",
            fmt_pct(total_pnl),
            delta_color="normal" if float(total_pnl or 0) >= 0 else "inverse",
        )
    with k2:
        win_rate = perf.get("win_rate", 0)
        st.metric("Win Rate", f"{float(win_rate or 0):.1f}%")
    with k3:
        pf = perf.get("profit_factor", 0)
        st.metric("Profit Factor", f"{float(pf or 0):.2f}")

    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)

    # ── Per-ticker table ──
    _section("Per-Ticker Performance")

    ticker_perf = perf.get("by_ticker")
    if ticker_perf is not None and len(ticker_perf) > 0:
        if isinstance(ticker_perf, list):
            tp_df = pd.DataFrame(ticker_perf)
        elif isinstance(ticker_perf, pd.DataFrame):
            tp_df = ticker_perf
        else:
            tp_df = pd.DataFrame()

        if not tp_df.empty:
            st.dataframe(tp_df, use_container_width=True, hide_index=True)
        else:
            _no_data("No per-ticker data")
    else:
        if not perf.get("has_data", True) or perf.get("total_trades", 0) == 0:
            _no_data("No closed trades yet — performance data will appear after first signals are closed")
        else:
            _no_data("Per-ticker breakdown not available")

    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)

    # ── Historical Context ──
    _section("Historical Context")

    hist_ctx = load_historical_context()
    if hist_ctx:
        st.markdown(
            f'<div style="background:#141720;border:1px solid #1f2535;border-radius:6px;'
            f'padding:14px 16px;font-family:DM Mono,monospace;font-size:0.75rem;'
            f'color:#8892a4;white-space:pre-wrap;line-height:1.6;">{hist_ctx}</div>',
            unsafe_allow_html=True,
        )
    else:
        _no_data("Historical context requires accumulated trade and price data")
