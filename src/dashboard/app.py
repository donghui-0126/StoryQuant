"""
StoryQuant v2 Dashboard — Graph-Driven
5 tabs: Narratives | Signals & Events | News Feed | Knowledge Graph | Performance
Data sources: amure-db graph API + SQLite (prices/OI/liquidations)
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.config.settings import SQLITE_DB_PATH, AMURE_DB_URL

# ── Page config ──────────────────────────────────────────────
st.set_page_config(
    page_title="StoryQuant v2",
    page_icon="▲",
    layout="wide",
    initial_sidebar_state="expanded",
)

import plotly.io as pio
pio.templates.default = "plotly_dark"

# ── Global CSS (preserved from v1) ──────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600&display=swap');
  html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
  #MainMenu { visibility: hidden; }
  footer    { visibility: hidden; }
  header    { visibility: hidden; }
  .stApp { background-color: #0d0f14; }

  [data-testid="stMetric"] {
    background: #141720; border: 1px solid #1f2535; border-radius: 6px; padding: 14px 16px;
  }
  [data-testid="stMetricLabel"] p {
    font-size: 0.72rem !important; letter-spacing: 0.08em; text-transform: uppercase;
    color: #5a6480 !important; font-family: 'DM Mono', monospace !important;
  }
  [data-testid="stMetricValue"] {
    font-size: 1.55rem !important; font-weight: 600 !important; color: #e8ecf4 !important;
  }
  [data-testid="stMetricDelta"] { font-size: 0.78rem !important; font-family: 'DM Mono', monospace !important; }

  .stTabs [data-baseweb="tab-list"] { background: transparent; gap: 2px; border-bottom: 1px solid #1f2535; }
  .stTabs [data-baseweb="tab"] {
    background: transparent; border-radius: 0; color: #5a6480; font-size: 0.82rem;
    letter-spacing: 0.06em; text-transform: uppercase; padding: 8px 18px;
    border-bottom: 2px solid transparent; font-family: 'DM Mono', monospace;
  }
  .stTabs [aria-selected="true"] { color: #e8ecf4 !important; border-bottom: 2px solid #3b82f6 !important; background: transparent !important; }

  .sq-section {
    font-size: 0.7rem; letter-spacing: 0.12em; text-transform: uppercase; color: #3b82f6;
    font-family: 'DM Mono', monospace; margin: 0 0 10px 0; padding-bottom: 6px; border-bottom: 1px solid #1f2535;
  }

  .news-card {
    background: #141720; border-left: 3px solid #3b82f6; padding: 10px 14px;
    margin-bottom: 6px; border-radius: 0 4px 4px 0;
  }
  .news-card.exchange  { border-left-color: #f59e0b; }
  .news-card.twitter   { border-left-color: #38bdf8; }
  .news-card.community { border-left-color: #22c55e; }
  .news-card.whale     { border-left-color: #a855f7; }
  .news-card-time { font-family: 'DM Mono', monospace; font-size: 0.68rem; color: #5a6480; }
  .news-card-title { font-size: 0.82rem; color: #c8d0e0; line-height: 1.35; margin: 3px 0 0 0; }
  .news-card-source { font-family: 'DM Mono', monospace; font-size: 0.65rem; color: #3b82f6; text-transform: uppercase; margin-top: 4px; }
  .news-card-sentiment { font-family: 'DM Mono', monospace; font-size: 0.62rem; margin-left: 10px; }

  .narrative-card {
    background: #141720; border-radius: 6px; padding: 14px 16px; margin-bottom: 10px; border: 1px solid #1f2535;
  }
  .narrative-card.emerging { border-left: 4px solid #3b82f6; }
  .narrative-card.building { border-left: 4px solid #22c55e; }
  .narrative-card.peaking  { border-left: 4px solid #f59e0b; }
  .narrative-card.fading   { border-left: 4px solid #6b7280; }
  .narrative-title { font-size: 0.95rem; font-weight: 600; color: #e8ecf4; }
  .narrative-meta { font-family: 'DM Mono', monospace; font-size: 0.68rem; color: #5a6480; margin-top: 3px; }
  .narrative-keywords { font-family: 'DM Mono', monospace; font-size: 0.7rem; color: #8892a4; margin-top: 6px; }

  .alert-badge { display: inline-block; padding: 2px 8px; border-radius: 3px; font-family: 'DM Mono', monospace; font-size: 0.65rem; letter-spacing: 0.06em; text-transform: uppercase; font-weight: 500; }
  .alert-high   { background: #2d0f0f; color: #f87171; border: 1px solid #7f1d1d; }
  .alert-medium { background: #2d1f0f; color: #fbbf24; border: 1px solid #78350f; }
  .alert-low    { background: #0f1f2d; color: #60a5fa; border: 1px solid #1e3a5f; }

  section[data-testid="stSidebar"] { background: #0d0f14; border-right: 1px solid #1f2535; }
  .sq-sidebar-label { font-family: 'DM Mono', monospace; font-size: 0.65rem; letter-spacing: 0.1em; text-transform: uppercase; color: #5a6480; margin-bottom: 6px; }
  .sq-divider { border: none; border-top: 1px solid #1f2535; margin: 16px 0; }

  .graph-stat { background: #141720; border: 1px solid #1f2535; border-radius: 6px; padding: 10px 14px; text-align: center; }
  .graph-stat-value { font-size: 1.3rem; font-weight: 600; color: #e8ecf4; font-family: 'DM Mono', monospace; }
  .graph-stat-label { font-size: 0.65rem; color: #5a6480; text-transform: uppercase; letter-spacing: 0.08em; font-family: 'DM Mono', monospace; }
</style>
""", unsafe_allow_html=True)


# ── Graph client (cached) ─────��──────────────────────────────

@st.cache_resource
def get_graph_client():
    from src.graph.client import AmureClient
    return AmureClient()


# ── Data loaders (graph-based) ───────────────────────────────

@st.cache_data(ttl=30)
def load_narratives() -> list:
    try:
        from src.graph.reasoning import get_active_narratives
        client = get_graph_client()
        if not client.is_available():
            return []
        return get_active_narratives(client)
    except Exception:
        return []


@st.cache_data(ttl=30)
def load_events() -> list:
    try:
        from src.graph.reasoning import get_recent_events_from_graph
        client = get_graph_client()
        if not client.is_available():
            return []
        return get_recent_events_from_graph(client, limit=100)
    except Exception:
        return []


@st.cache_data(ttl=30)
def load_evidence(market: str = None) -> list:
    try:
        from src.graph.reasoning import get_recent_evidence
        client = get_graph_client()
        if not client.is_available():
            return []
        return get_recent_evidence(client, market=market, limit=100)
    except Exception:
        return []


@st.cache_data(ttl=30)
def load_graph_summary() -> dict:
    try:
        client = get_graph_client()
        if not client.is_available():
            return {}
        return client.graph_summary()
    except Exception:
        return {}


@st.cache_data(ttl=60)
def load_knowledge_health() -> dict:
    try:
        from src.graph.reasoning import check_knowledge_health
        client = get_graph_client()
        if not client.is_available():
            return {}
        return check_knowledge_health(client)
    except Exception:
        return {}


@st.cache_data(ttl=60)
def load_contradictions() -> list:
    try:
        client = get_graph_client()
        if not client.is_available():
            return []
        return client.detect_contradictions()
    except Exception:
        return []


@st.cache_data(ttl=30)
def load_prices(ticker: str = None, hours: int = 72) -> pd.DataFrame:
    try:
        from src.db.schema import thread_connection
        from src.db.queries import get_recent_prices
        with thread_connection() as conn:
            return get_recent_prices(conn, ticker=ticker, hours=hours)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def get_db_stats() -> dict:
    try:
        from src.db.schema import thread_connection
        with thread_connection() as conn:
            stats = {}
            stats["prices"] = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
            try:
                stats["oi"] = conn.execute("SELECT COUNT(*) FROM open_interest").fetchone()[0]
            except Exception:
                stats["oi"] = 0
            db_file = Path(SQLITE_DB_PATH)
            stats["db_size_mb"] = round(db_file.stat().st_size / 1024 / 1024, 2) if db_file.exists() else 0
            return stats
    except Exception:
        return {}


# ── Helpers ───���──────────────────────────────────────────────

def fmt_pct(val, decimals=2) -> str:
    try:
        v = float(val)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.{decimals}f}%"
    except Exception:
        return "—"


def _no_data(label: str = "No data available"):
    st.markdown(
        f'<div style="padding:24px;text-align:center;color:#5a6480;'
        f'font-family:DM Mono,monospace;font-size:0.78rem;border:1px dashed #1f2535;'
        f'border-radius:6px;">{label}</div>',
        unsafe_allow_html=True,
    )


def _section(title: str):
    st.markdown(f'<p class="sq-section">{title}</p>', unsafe_allow_html=True)


_LIFECYCLE_ICON = {"emerging": "🌱", "building": "📈", "peaking": "🔥", "fading": "📉"}
_LIFECYCLE_COLOR = {"emerging": "#3b82f6", "building": "#22c55e", "peaking": "#f59e0b", "fading": "#6b7280"}


def _time_ago(ts_str) -> str:
    try:
        ts = pd.to_datetime(ts_str, utc=True)
        delta = datetime.now(timezone.utc) - ts.to_pydatetime()
        minutes = int(delta.total_seconds() / 60)
        if minutes < 60:
            return f"{minutes}m ago"
        hours_ago = minutes // 60
        if hours_ago < 24:
            return f"{hours_ago}h ago"
        return f"{hours_ago // 24}d ago"
    except Exception:
        return str(ts_str)[:16] if ts_str else "?"


def _source_class(src_type: str) -> str:
    s = str(src_type).lower()
    if "exchange" in s or "binance" in s:
        return "exchange"
    if "twitter" in s:
        return "twitter"
    if "community" in s:
        return "community"
    if "whale" in s:
        return "whale"
    return ""


def _sentiment_badge(sentiment: str, score: float = 0) -> str:
    if sentiment == "bullish":
        return f'<span class="news-card-sentiment" style="color:#22c55e;">▲ {score:+.2f}</span>'
    elif sentiment == "bearish":
        return f'<span class="news-card-sentiment" style="color:#f87171;">▼ {score:+.2f}</span>'
    return ""


# ── Sidebar ──────��───────────────────��───────────────────────

with st.sidebar:
    st.markdown(
        '<span style="font-family:DM Mono,monospace;font-size:1.05rem;'
        'font-weight:500;color:#e8ecf4;letter-spacing:0.05em;">▲ StoryQuant v2</span>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<span style="font-family:DM Mono,monospace;font-size:0.65rem;color:#3b82f6;">'
        'Graph-Powered Market Intelligence</span>',
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

    # Graph + DB stats
    graph_summary = load_graph_summary()
    db_stats = get_db_stats()

    if graph_summary:
        node_count = graph_summary.get("total_nodes", graph_summary.get("node_count", 0))
        edge_count = graph_summary.get("total_edges", graph_summary.get("edge_count", 0))
        st.markdown(
            f'<p style="font-family:DM Mono,monospace;font-size:0.65rem;color:#5a6480;">'
            f'Graph: {node_count} nodes · {edge_count} edges</p>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<p style="font-family:DM Mono,monospace;font-size:0.65rem;color:#f87171;">'
            'amure-db offline</p>',
            unsafe_allow_html=True,
        )

    if db_stats:
        st.markdown(
            f'<p style="font-family:DM Mono,monospace;font-size:0.65rem;color:#5a6480;">'
            f'SQLite: {db_stats.get("prices",0):,} prices · {db_stats.get("db_size_mb",0)}MB</p>',
            unsafe_allow_html=True,
        )

    st.caption(f"Updated {datetime.now().strftime('%H:%M:%S')}")


# ── Header ───────��───────────────────────────────────────────

_now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
st.markdown(
    f'<div style="display:flex;align-items:baseline;gap:16px;margin-bottom:8px;">'
    f'<span style="font-size:1.35rem;font-weight:600;color:#e8ecf4;letter-spacing:-0.01em;">StoryQuant</span>'
    f'<span style="font-family:DM Mono,monospace;font-size:0.78rem;color:#5a6480;">그래프 기반 시장 내러티브 인텔리전스</span>'
    f'<span style="margin-left:auto;font-family:DM Mono,monospace;font-size:0.68rem;color:#3b4560;">{_now_str}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# ── KPI strip ────────────────────────────────────────────────

summary = load_graph_summary()
k1, k2, k3, k4 = st.columns(4)
with k1:
    narratives_list = load_narratives()
    active = sum(1 for n in narratives_list if n.get("status") in ("Active", "Accepted"))
    st.metric("Active Narratives", active)
with k2:
    events_list = load_events()
    st.metric("Recent Events", len(events_list))
with k3:
    evidence_list = load_evidence()
    st.metric("Evidence Nodes", len(evidence_list))
with k4:
    health = load_knowledge_health()
    stale = health.get("stale_count", 0)
    total = health.get("total", 0)
    st.metric("Knowledge Health", f"{total - stale}/{total}" if total else "—")


# ── Main tabs ────────────────────────────────────────────────

tab_narratives, tab_signals, tab_news, tab_graph, tab_perf = st.tabs([
    "Narratives", "Signals & Events", "News Feed", "Knowledge Graph", "Performance"
])


# ═══════════════════════════════════════════════════════════
# TAB 1 — NARRATIVES
# ══════���══════════════════════════════��═════════════════════

with tab_narratives:
    _section("Active Narratives")

    if not narratives_list:
        _no_data("No active narratives detected — amure-db may be offline or no data ingested yet")
    else:
        filtered_narratives = narratives_list
        if market_filter and set(market_filter) != {"crypto", "us", "kr"}:
            filtered_narratives = [
                n for n in narratives_list
                if n.get("market", "") in market_filter or not n.get("market")
            ]

        n_cols = min(len(filtered_narratives), 2) if filtered_narratives else 1
        if filtered_narratives:
            col_pairs = st.columns(n_cols)
            for i, n in enumerate(filtered_narratives):
                with col_pairs[i % n_cols]:
                    lc = n.get("lifecycle", "fading")
                    icon = _LIFECYCLE_ICON.get(lc, "")
                    lc_color = _LIFECYCLE_COLOR.get(lc, "#6b7280")
                    ev_count = n.get("evidence_count", 0)
                    keywords = n.get("keywords", [])[:5]
                    kw_html = " ".join(
                        f'<span style="background:#1f2535;padding:2px 6px;border-radius:3px;'
                        f'font-size:0.68rem;color:#8892a4;font-family:DM Mono,monospace;">{k}</span>'
                        for k in keywords
                    )

                    st.markdown(f"""
<div class="narrative-card {lc}">
  <div style="display:flex;align-items:center;justify-content:space-between;">
    <span class="narrative-title">{icon} {n.get("statement", "")[:80]}</span>
    <span style="font-family:DM Mono,monospace;font-size:0.68rem;
                 color:{lc_color};font-weight:600;letter-spacing:0.08em;">{lc.upper()}</span>
  </div>
  <p class="narrative-meta">
    Evidence: {ev_count} | Status: {n.get("status", "Draft")}
    {f' | Market: {n.get("market", "")}' if n.get("market") else ''}
  </p>
  <div class="narrative-keywords">{kw_html}</div>
</div>
""", unsafe_allow_html=True)
        else:
            _no_data("No narratives match the selected market filter")


# ═══════════════════════════════════════════════════════���═══
# TAB 2 — SIGNALS & EVENTS
# ═══════════════════════════════════════════════════════════

with tab_signals:
    _section("Price Events (from Graph)")

    if not events_list:
        _no_data("No price events detected — run the pipeline first")
    else:
        filtered_events = events_list
        if market_filter and set(market_filter) != {"crypto", "us", "kr"}:
            filtered_events = [e for e in events_list if e.get("market", "") in market_filter]

        # Filters
        fc1, fc2 = st.columns(2)
        with fc1:
            sev_opts = ["All"] + sorted(set(e.get("severity", "") for e in filtered_events if e.get("severity")))
            sev_filter = st.selectbox("Severity", sev_opts)
        with fc2:
            etype_opts = ["All"] + sorted(set(e.get("event_type", "") for e in filtered_events if e.get("event_type")))
            etype_filter = st.selectbox("Event Type", etype_opts)

        if sev_filter != "All":
            filtered_events = [e for e in filtered_events if e.get("severity") == sev_filter]
        if etype_filter != "All":
            filtered_events = [e for e in filtered_events if e.get("event_type") == etype_filter]

        if filtered_events:
            rows = []
            for e in filtered_events[:50]:
                ret = e.get("return_1h", 0)
                rows.append({
                    "Time": _time_ago(e.get("timestamp", "")),
                    "Ticker": e.get("ticker", ""),
                    "Type": e.get("event_type", ""),
                    "Return": fmt_pct(float(ret) * 100 if ret else 0, 2),
                    "Severity": e.get("severity", ""),
                    "Attributions": e.get("attribution_count", 0),
                    "Attributed": "✓" if e.get("attributed") else "—",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            _no_data("No events match filters")

    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)

    # ── Event detail (causal explanation) ──
    _section("Causal Explanation")

    if events_list:
        event_options = {
            f"{e.get('ticker', '')} {e.get('event_type', '')} ({_time_ago(e.get('timestamp', ''))})": e.get("id", "")
            for e in events_list[:20]
        }
        if event_options:
            selected_label = st.selectbox("Select event to explain", list(event_options.keys()))
            selected_id = event_options.get(selected_label, "")

            if selected_id and st.button("Explain"):
                try:
                    from src.graph.reasoning import get_causal_explanation
                    client = get_graph_client()
                    explanation = get_causal_explanation(client, selected_id)

                    if explanation.get("evidence"):
                        st.markdown("**Supporting Evidence:**")
                        for ev in explanation["evidence"][:5]:
                            st.markdown(f"- {ev.get('statement', '')[:100]}")

                    if explanation.get("reasons"):
                        st.markdown("**Synthesized Reasons:**")
                        for r in explanation["reasons"][:3]:
                            st.markdown(f"- {r.get('statement', '')[:150]}")

                    if explanation.get("narratives"):
                        st.markdown("**Related Narratives:**")
                        for n in explanation["narratives"][:3]:
                            st.markdown(f"- {n.get('statement', '')[:100]} [{n.get('status', '')}]")

                    if explanation.get("causal_chains"):
                        st.markdown(f"**Causal Chains:** {explanation['chain_count']} paths found")
                except Exception as ex:
                    st.error(f"Explanation failed: {ex}")
    else:
        _no_data("Select an event to see its causal explanation")


# ═══��═════════════════════════��═════════════════════════════
# TAB 3 — NEWS FEED
# ═════════════���═════════════════════════════════════════════

with tab_news:
    nf1, nf2 = st.columns([1, 2])
    with nf1:
        news_market = st.radio(
            "Market", options=["All", "Crypto", "US", "KR"],
            index=0, horizontal=True, label_visibility="visible",
        )

    mkt_arg = None if news_market == "All" else news_market.lower()
    articles = load_evidence(market=mkt_arg)

    _section(f"News Feed — {len(articles)} articles (from Graph)")

    if not articles:
        _no_data("No news articles — check amure-db connection and run the pipeline")
    else:
        for a in articles[:50]:
            source_type = a.get("source_type", "")
            src_class = _source_class(source_type)
            time_str = _time_ago(a.get("published_at", ""))
            title = a.get("statement", "")
            source = a.get("source", "")
            sentiment = a.get("sentiment", "")
            score = a.get("sentiment_score", 0)
            sent_html = _sentiment_badge(sentiment, score)

            st.markdown(
                f'<div class="news-card {src_class}">'
                f'<span class="news-card-time">{time_str}</span>{sent_html}'
                f'<p class="news-card-title">{title}</p>'
                f'<span class="news-card-source">{source} · {source_type}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ══════════════════════���════════════════════════════════════
# TAB 4 — KNOWLEDGE GRAPH
# ════════════════════════════════���══════════════════════════

with tab_graph:
    _section("Graph Overview")

    if not summary:
        _no_data("amure-db is offline — start with 'cargo run' in the amure-db directory")
    else:
        # Node/Edge counts by kind
        g1, g2, g3, g4, g5 = st.columns(5)
        kinds = summary.get("by_kind", summary.get("nodes_by_kind", {}))
        with g1:
            st.markdown(f'<div class="graph-stat"><div class="graph-stat-value">{kinds.get("Evidence", kinds.get("evidence", 0))}</div><div class="graph-stat-label">Evidence</div></div>', unsafe_allow_html=True)
        with g2:
            st.markdown(f'<div class="graph-stat"><div class="graph-stat-value">{kinds.get("Fact", kinds.get("fact", 0))}</div><div class="graph-stat-label">Facts</div></div>', unsafe_allow_html=True)
        with g3:
            st.markdown(f'<div class="graph-stat"><div class="graph-stat-value">{kinds.get("Claim", kinds.get("claim", 0))}</div><div class="graph-stat-label">Claims</div></div>', unsafe_allow_html=True)
        with g4:
            st.markdown(f'<div class="graph-stat"><div class="graph-stat-value">{kinds.get("Reason", kinds.get("reason", 0))}</div><div class="graph-stat-label">Reasons</div></div>', unsafe_allow_html=True)
        with g5:
            st.markdown(f'<div class="graph-stat"><div class="graph-stat-value">{kinds.get("Experiment", kinds.get("experiment", 0))}</div><div class="graph-stat-label">Experiments</div></div>', unsafe_allow_html=True)

    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)

    # ── RAG Search ──
    _section("RAG Search")

    search_query = st.text_input("Search the knowledge graph", placeholder="e.g., BTC ETF inflow, 삼성전자 HBM...")
    if search_query:
        client = get_graph_client()
        results = client.search(search_query, top_k=15)
        if results:
            for r in results:
                kind_colors = {"Evidence": "#3b82f6", "Fact": "#f59e0b", "Claim": "#22c55e", "Reason": "#a855f7", "Experiment": "#8b5cf6"}
                kind_color = kind_colors.get(r.kind, "#8892a4")
                failed_tag = ' <span style="color:#f87171;">[FAILED PATH]</span>' if r.failed_path else ""

                st.markdown(
                    f'<div style="background:#141720;border:1px solid #1f2535;border-radius:6px;padding:10px 14px;margin-bottom:6px;">'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.65rem;color:{kind_color};font-weight:600;">{r.kind}</span>'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.65rem;color:#5a6480;margin-left:10px;">score: {r.score:.3f} | hop: {r.hop_distance}</span>'
                    f'{failed_tag}'
                    f'<p style="font-size:0.82rem;color:#c8d0e0;margin:4px 0 0 0;">{r.statement[:150]}</p>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            _no_data(f"No results for '{search_query}'")

    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)

    # ── Contradictions ──
    _section("Contradictions")

    contradictions = load_contradictions()
    if contradictions:
        for c in contradictions[:10]:
            st.markdown(
                f'<div style="background:#2d0f0f;border:1px solid #7f1d1d;border-radius:6px;padding:10px 14px;margin-bottom:6px;">'
                f'<span style="font-family:DM Mono,monospace;font-size:0.65rem;color:#f87171;">CONTRADICTION</span>'
                f'<p style="font-size:0.82rem;color:#c8d0e0;margin:4px 0;">{c}</p>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        _no_data("No contradictions detected")

    # ── Knowledge Health ──
    _section("Knowledge Health")

    if health.get("stale_nodes"):
        for node in health["stale_nodes"][:10]:
            st.markdown(
                f'<div style="background:#141720;border-left:3px solid #fbbf24;padding:8px 12px;margin-bottom:4px;border-radius:0 4px 4px 0;">'
                f'<span style="font-family:DM Mono,monospace;font-size:0.68rem;color:#fbbf24;">'
                f'{node.get("urgency", "OVERDUE")}</span> '
                f'<span style="font-size:0.78rem;color:#c8d0e0;">{node.get("statement", str(node))[:100]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        _no_data("All knowledge nodes are up to date")


# ══��═════════════════���═════════════════════════════════════���
# TAB 5 — PERFORMANCE
# ═══════════════════════════════════════════════════════════

with tab_perf:
    _section("Attribution Performance")

    all_events = load_events()
    attributed = [e for e in all_events if e.get("attributed")]
    unattributed = [e for e in all_events if not e.get("attributed")]

    pk1, pk2, pk3, pk4 = st.columns(4)
    with pk1:
        st.metric("Total Events", len(all_events))
    with pk2:
        st.metric("Attributed", len(attributed))
    with pk3:
        rate = len(attributed) / len(all_events) * 100 if all_events else 0
        st.metric("Attribution Rate", f"{rate:.0f}%")
    with pk4:
        avg_attr = sum(e.get("attribution_count", 0) for e in attributed) / len(attributed) if attributed else 0
        st.metric("Avg Attributions", f"{avg_attr:.1f}")

    st.markdown('<hr class="sq-divider">', unsafe_allow_html=True)

    _section("Price Data Coverage")

    price_df = load_prices(hours=72)
    if not price_df.empty:
        ticker_counts = price_df.groupby("ticker").size().reset_index(name="rows")
        st.dataframe(ticker_counts.sort_values("rows", ascending=False).head(20),
                      use_container_width=True, hide_index=True)
    else:
        _no_data("No price data in SQLite")
