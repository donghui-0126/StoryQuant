"""
StoryQuant v2 Dashboard — Cause-to-Return Intelligence
3 tabs: Signals | Events | Explorer
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.config.settings import AMURE_DB_URL

st.set_page_config(page_title="StoryQuant", page_icon="▲", layout="wide", initial_sidebar_state="collapsed")

import plotly.io as pio
pio.templates.default = "plotly_dark"

# ── CSS ──
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&display=swap');
  html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
  #MainMenu, footer, header { visibility: hidden; }
  .stApp { background: #0a0c10; }

  [data-testid="stMetric"] { background: #12141a; border: 1px solid #1c1f2e; border-radius: 8px; padding: 16px; }
  [data-testid="stMetricLabel"] p { font-size: 0.7rem !important; letter-spacing: 0.1em; text-transform: uppercase; color: #4a5068 !important; font-family: 'DM Mono', monospace !important; }
  [data-testid="stMetricValue"] { font-size: 1.6rem !important; font-weight: 700 !important; color: #e4e8f0 !important; }

  .stTabs [data-baseweb="tab-list"] { background: transparent; gap: 0; border-bottom: 1px solid #1c1f2e; }
  .stTabs [data-baseweb="tab"] { background: transparent; color: #4a5068; font-family: 'DM Mono', monospace; font-size: 0.8rem; letter-spacing: 0.08em; text-transform: uppercase; padding: 10px 24px; border-bottom: 2px solid transparent; }
  .stTabs [aria-selected="true"] { color: #e4e8f0 !important; border-bottom: 2px solid #3b82f6 !important; }

  .sec { font-family: 'DM Mono', monospace; font-size: 0.68rem; letter-spacing: 0.12em; text-transform: uppercase; color: #3b82f6; border-bottom: 1px solid #1c1f2e; padding-bottom: 6px; margin: 20px 0 12px; }
  .empty { padding: 20px; text-align: center; color: #4a5068; font-family: 'DM Mono', monospace; font-size: 0.78rem; border: 1px dashed #1c1f2e; border-radius: 8px; }
  hr.div { border: none; border-top: 1px solid #1c1f2e; margin: 20px 0; }

  /* Signal Card */
  .sig-card { background: #12141a; border-radius: 8px; padding: 16px 18px; margin-bottom: 10px; border: 1px solid #1c1f2e; }
  .sig-card:hover { border-color: #2a2f42; }
  .sig-dir { font-family: 'DM Mono', monospace; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.06em; padding: 3px 10px; border-radius: 4px; }
  .sig-long  { background: #0a2a1a; color: #22c55e; border: 1px solid #15803d; }
  .sig-short { background: #2a0a0a; color: #f87171; border: 1px solid #7f1d1d; }
  .sig-title { font-size: 0.92rem; font-weight: 600; color: #e4e8f0; margin-top: 8px; line-height: 1.4; }
  .sig-meta { font-family: 'DM Mono', monospace; font-size: 0.68rem; color: #4a5068; margin-top: 6px; }
  .sig-return { font-family: 'DM Mono', monospace; font-size: 1.1rem; font-weight: 700; margin-top: 8px; }
  .sig-return.positive { color: #22c55e; }
  .sig-return.negative { color: #f87171; }
  .sig-evidence { font-size: 0.75rem; color: #6b7280; margin-top: 8px; padding-top: 8px; border-top: 1px solid #1c1f2e; }
  .sig-kw { display: inline-block; background: #1c1f2e; padding: 2px 6px; border-radius: 3px; font-family: 'DM Mono', monospace; font-size: 0.62rem; color: #6b7280; margin: 2px 2px 0 0; }

  /* Event Row */
  .ev-card { background: #12141a; border-left: 3px solid #3b82f6; padding: 10px 14px; margin-bottom: 4px; border-radius: 0 6px 6px 0; display: flex; align-items: center; gap: 14px; }
  .ev-card.surge { border-left-color: #22c55e; }
  .ev-card.crash { border-left-color: #f87171; }
  .ev-card.volume_spike { border-left-color: #f59e0b; }
  .ev-ticker { font-family: 'DM Mono', monospace; font-size: 0.82rem; font-weight: 600; color: #e4e8f0; min-width: 90px; }
  .ev-return { font-family: 'DM Mono', monospace; font-size: 0.82rem; font-weight: 600; min-width: 70px; }
  .ev-cause { font-size: 0.78rem; color: #8892a4; flex: 1; }
  .ev-time { font-family: 'DM Mono', monospace; font-size: 0.65rem; color: #4a5068; min-width: 60px; text-align: right; }

  /* Search */
  .sr-card { background: #12141a; border: 1px solid #1c1f2e; border-radius: 8px; padding: 12px 16px; margin-bottom: 6px; }
  .sr-kind { font-family: 'DM Mono', monospace; font-size: 0.62rem; font-weight: 600; }
  .sr-score { font-family: 'DM Mono', monospace; font-size: 0.62rem; color: #4a5068; }
  .sr-stmt { font-size: 0.82rem; color: #c0c8d8; margin-top: 4px; }
  .k-evidence { color: #3b82f6; } .k-fact { color: #f59e0b; } .k-claim { color: #22c55e; }
  .k-reason { color: #a855f7; } .k-experiment { color: #8b5cf6; }
</style>
""", unsafe_allow_html=True)


# ── Graph client ──
@st.cache_resource
def get_client():
    from src.graph.client import AmureClient
    return AmureClient()


# ── Data loaders ──
@st.cache_data(ttl=30)
def load_all():
    try:
        c = get_client()
        if not c.is_available():
            return {"nodes": [], "edges": []}
        return c.get_all()
    except Exception:
        return {"nodes": [], "edges": []}


@st.cache_data(ttl=30)
def load_summary():
    try:
        c = get_client()
        return c.graph_summary() if c.is_available() else {}
    except Exception:
        return {}


@st.cache_data(ttl=30)
def load_prices(hours=72):
    try:
        from src.db.schema import thread_connection
        from src.db.queries import get_recent_prices
        with thread_connection() as conn:
            return get_recent_prices(conn, hours=hours)
    except Exception:
        return pd.DataFrame()


def time_ago(ts):
    try:
        t = pd.to_datetime(ts, utc=True)
        m = int((datetime.now(timezone.utc) - t.to_pydatetime()).total_seconds() / 60)
        if m < 60: return f"{m}m"
        h = m // 60
        return f"{h}h" if h < 24 else f"{h//24}d"
    except Exception:
        return "?"


# ── Load data ──
all_data = load_all()
nodes = all_data.get("nodes", [])
edges = all_data.get("edges", [])
summary = load_summary()

claims = [n for n in nodes if n.get("kind") == "Claim"]
facts = [n for n in nodes if n.get("kind") == "Fact"]
evidence = [n for n in nodes if n.get("kind") == "Evidence"]
experiments = [n for n in nodes if n.get("kind") == "Experiment"]

# Build support count map
support_count = {}
support_sources = {}
for e in edges:
    if e.get("kind") == "Support":
        t = e.get("target", "")
        support_count[t] = support_count.get(t, 0) + 1
        support_sources.setdefault(t, []).append(e.get("source", ""))

# Build node lookup
node_map = {n.get("id", ""): n for n in nodes}


# ── Header ──
now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
online = bool(summary)
status_html = '<span style="color:#22c55e;">ONLINE</span>' if online else '<span style="color:#f87171;">OFFLINE</span>'

st.markdown(
    f'<div style="display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-bottom:1px solid #1c1f2e;margin-bottom:16px;">'
    f'<div><span style="font-family:DM Mono,monospace;font-size:1.1rem;font-weight:600;color:#e4e8f0;">StoryQuant</span>'
    f'<span style="font-family:DM Mono,monospace;font-size:0.7rem;color:#4a5068;margin-left:12px;">Cause-to-Return Intelligence</span></div>'
    f'<div style="font-family:DM Mono,monospace;font-size:0.65rem;">{status_html}'
    f'<span style="color:#4a5068;margin-left:12px;">{summary.get("n_nodes",0)} nodes / {summary.get("n_edges",0)} edges</span>'
    f'<span style="color:#3b4560;margin-left:12px;">{now_str}</span></div></div>',
    unsafe_allow_html=True,
)

# ── Tabs ──
tab_signals, tab_events, tab_trading, tab_explorer = st.tabs(["Signals", "Events", "Paper Trade", "Explorer"])


# ═══════════════════════════════════════════════
# TAB 1 — SIGNALS (Cause → Expected Return)
# ═══════════════════════════════════════════════
with tab_signals:

    if not claims:
        st.markdown('<div class="empty">No narratives detected. Run pipeline first.</div>', unsafe_allow_html=True)
    else:
        # Sort claims by evidence count
        claims_sorted = sorted(claims, key=lambda c: support_count.get(c.get("id",""), 0), reverse=True)

        # Compute returns from linked Facts for each claim
        signal_data = []
        for c in claims_sorted:
            cid = c.get("id", "")
            meta = c.get("metadata", {})
            lifecycle = meta.get("lifecycle", "emerging")
            ev_count = support_count.get(cid, 0)

            linked_sources = support_sources.get(cid, [])
            linked_facts = [node_map[s] for s in linked_sources if s in node_map and node_map[s].get("kind") == "Fact"]
            returns = [float(f.get("metadata", {}).get("return_1h", 0)) for f in linked_facts if f.get("metadata", {}).get("return_1h")]

            if returns:
                avg_ret = sum(returns) / len(returns) * 100
                cum_ret = sum(returns) * 100
                max_ret = max(returns) * 100
                min_ret = min(returns) * 100
                win_count = sum(1 for r in returns if r > 0)
                win_rate = win_count / len(returns) * 100
            else:
                avg_ret = cum_ret = max_ret = min_ret = win_rate = 0

            # Direction from ACTUAL returns, not metadata
            if avg_ret > 0.1:
                dir_html = '<span class="sig-dir sig-long">LONG</span>'
            elif avg_ret < -0.1:
                dir_html = '<span class="sig-dir sig-short">SHORT</span>'
            else:
                dir_html = '<span class="sig-dir" style="background:#1c1f2e;color:#6b7280;">NEUTRAL</span>'
            ret_class = "positive" if avg_ret >= 0 else "negative"

            ret_str = f"{avg_ret:+.2f}%" if returns else "N/A"
            cum_str = f"{cum_ret:+.1f}%" if returns else ""
            range_str = f"{min_ret:+.1f}% ~ {max_ret:+.1f}%" if len(returns) >= 2 else ""
            wr_str = f"{win_rate:.0f}%" if returns else ""

            kw_html = "".join(f'<span class="sig-kw">{k}</span>' for k in c.get("keywords", [])[:6])

            linked_evidence = [node_map[s] for s in linked_sources if s in node_map and node_map[s].get("kind") == "Evidence"]
            ev_html = ""
            if linked_evidence:
                headlines = [e.get("statement", "")[:80] for e in linked_evidence[:3]]
                ev_html = '<div class="sig-evidence">' + "<br>".join(f"&rarr; {h}" for h in headlines) + "</div>"

            lifecycle_icons = {"emerging": "🌱", "building": "📈", "peaking": "🔥", "fading": "📉"}

            # Collect event timeline (ticker, time, return)
            event_timeline = []
            affected_tickers = set()
            for f in linked_facts:
                fm = f.get("metadata", {})
                t = fm.get("ticker", "")
                ts = fm.get("timestamp", "")
                r = float(fm.get("return_1h", 0))
                if t and ts:
                    event_timeline.append({"ticker": t, "time": ts, "return": r})
                    affected_tickers.add(t)
            event_timeline.sort(key=lambda x: x["time"], reverse=True)

            signal_data.append({
                "statement": c.get("statement", ""),
                "avg_ret": avg_ret, "cum_ret": cum_ret, "win_rate": win_rate,
                "n_events": len(returns), "ev_count": ev_count,
                "tickers": list(affected_tickers),
            })

            # Event timeline HTML
            timeline_html = ""
            if event_timeline:
                rows = ""
                for ev in event_timeline[:6]:
                    r = ev["return"] * 100
                    rc = "#22c55e" if r >= 0 else "#f87171"
                    rows += (
                        f'<div style="display:flex;gap:10px;padding:3px 0;border-bottom:1px solid #1a1c24;">'
                        f'<span style="font-family:DM Mono,monospace;font-size:0.62rem;color:#4a5068;min-width:45px;">{time_ago(ev["time"])}</span>'
                        f'<span style="font-family:DM Mono,monospace;font-size:0.65rem;color:#e4e8f0;min-width:75px;">{ev["ticker"]}</span>'
                        f'<span style="font-family:DM Mono,monospace;font-size:0.65rem;color:{rc};">{r:+.2f}%</span></div>'
                    )
                timeline_html = (
                    f'<div style="margin-top:8px;padding-top:8px;border-top:1px solid #1c1f2e;">'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.58rem;color:#3b82f6;letter-spacing:0.08em;">EVENT TIMELINE</span>'
                    f'{rows}</div>'
                )

            st.markdown(f"""
<div class="sig-card">
  <div style="display:flex;align-items:center;justify-content:space-between;">
    {dir_html}
    <span style="font-family:DM Mono,monospace;font-size:0.65rem;color:#4a5068;">{lifecycle_icons.get(lifecycle,'')} {lifecycle.upper()} &middot; {ev_count} evidence &middot; {len(returns)} events</span>
  </div>
  <div class="sig-title">{c.get("statement","")[:100]}</div>
  <div style="display:flex;align-items:baseline;gap:16px;margin-top:10px;">
    <div><span style="font-family:DM Mono,monospace;font-size:0.6rem;color:#4a5068;">AVG</span><br><span class="sig-return {ret_class}">{ret_str}</span></div>
    <div><span style="font-family:DM Mono,monospace;font-size:0.6rem;color:#4a5068;">CUMULATIVE</span><br><span class="sig-return {ret_class}">{cum_str}</span></div>
    <div><span style="font-family:DM Mono,monospace;font-size:0.6rem;color:#4a5068;">WIN RATE</span><br><span style="font-family:DM Mono,monospace;font-size:1.1rem;font-weight:700;color:#e4e8f0;">{wr_str}</span></div>
    <div><span style="font-family:DM Mono,monospace;font-size:0.6rem;color:#4a5068;">RANGE</span><br><span style="font-family:DM Mono,monospace;font-size:0.78rem;color:#6b7280;">{range_str}</span></div>
  </div>
  <div class="sig-meta">{kw_html}</div>
  {ev_html}
  {timeline_html}
</div>""", unsafe_allow_html=True)

            # Mini price chart for affected tickers
            if affected_tickers:
                price_df = load_prices(hours=120)
                if not price_df.empty:
                    import plotly.graph_objects as go
                    chart_tickers = list(affected_tickers)[:3]
                    chart_data = price_df[price_df["ticker"].isin(chart_tickers)]
                    if not chart_data.empty:
                        fig = go.Figure()
                        colors = ["#3b82f6", "#22c55e", "#f59e0b"]
                        for i, tk in enumerate(chart_tickers):
                            td = chart_data[chart_data["ticker"] == tk].sort_values("timestamp")
                            if td.empty:
                                continue
                            # Normalize to % change from first price
                            first_price = td["close"].iloc[0]
                            if first_price and first_price > 0:
                                td_pct = ((td["close"] / first_price) - 1) * 100
                                fig.add_trace(go.Scatter(
                                    x=td["timestamp"], y=td_pct,
                                    name=tk, mode="lines",
                                    line=dict(color=colors[i % 3], width=1.5),
                                ))
                        fig.update_layout(
                            height=160, margin=dict(l=0, r=0, t=0, b=0),
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            xaxis=dict(showgrid=False, color="#4a5068", tickfont=dict(size=9)),
                            yaxis=dict(showgrid=True, gridcolor="#1c1f2e", color="#4a5068",
                                       tickfont=dict(size=9), ticksuffix="%"),
                            legend=dict(orientation="h", font=dict(size=9, color="#6b7280"),
                                        bgcolor="rgba(0,0,0,0)", x=0, y=1.15),
                            hovermode="x unified",
                        )
                        st.plotly_chart(fig, use_container_width=True, key=f"chart_{cid}")

        # ── Cumulative Performance Summary ──
        st.markdown('<p class="sec">Cumulative Performance</p>', unsafe_allow_html=True)
        if signal_data:
            perf_rows = []
            for s in sorted(signal_data, key=lambda x: abs(x["cum_ret"]), reverse=True):
                if s["n_events"] == 0:
                    continue
                perf_rows.append({
                    "Narrative": s["statement"][:50],
                    "Avg Return": f"{s['avg_ret']:+.2f}%",
                    "Cumulative": f"{s['cum_ret']:+.1f}%",
                    "Win Rate": f"{s['win_rate']:.0f}%",
                    "Events": s["n_events"],
                    "Evidence": s["ev_count"],
                })
            if perf_rows:
                st.dataframe(pd.DataFrame(perf_rows), use_container_width=True, hide_index=True)
            else:
                st.markdown('<div class="empty">No performance data yet</div>', unsafe_allow_html=True)

    # ── Experiments ──
    if experiments:
        st.markdown('<p class="sec">Testable Hypotheses</p>', unsafe_allow_html=True)
        for exp in experiments:
            meta = exp.get("metadata", {})
            horizon = meta.get("horizon", "?")
            method = meta.get("method", "")
            st.markdown(
                f'<div style="background:#12141a;border-left:3px solid #8b5cf6;padding:8px 14px;margin-bottom:4px;border-radius:0 6px 6px 0;">'
                f'<span style="font-family:DM Mono,monospace;font-size:0.62rem;color:#8b5cf6;">{method}</span>'
                f'<span style="font-family:DM Mono,monospace;font-size:0.62rem;color:#4a5068;margin-left:10px;">horizon: {horizon}</span>'
                f'<div style="font-size:0.8rem;color:#c0c8d8;margin-top:2px;">{exp.get("statement","")[:120]}</div></div>',
                unsafe_allow_html=True,
            )


# ═══════════════════════════════════════════════
# TAB 2 — EVENTS (What happened + Why)
# ═══════════════════════════════════════════════
with tab_events:

    facts_sorted = sorted(facts, key=lambda f: f.get("metadata",{}).get("timestamp",""), reverse=True)

    if not facts_sorted:
        st.markdown('<div class="empty">No price events detected.</div>', unsafe_allow_html=True)
    else:
        # Filters
        fc1, fc2 = st.columns(2)
        with fc1:
            mkt_filter = st.selectbox("Market", ["All", "crypto", "us", "kr"], index=0)
        with fc2:
            type_filter = st.selectbox("Type", ["All", "surge", "crash", "volume_spike", "vol_shock"], index=0)

        filtered = facts_sorted
        if mkt_filter != "All":
            filtered = [f for f in filtered if f.get("metadata",{}).get("market") == mkt_filter]
        if type_filter != "All":
            filtered = [f for f in filtered if f.get("metadata",{}).get("event_type") == type_filter]

        for f in filtered[:40]:
            meta = f.get("metadata", {})
            fid = f.get("id", "")
            ticker = meta.get("ticker", "?")
            ret = float(meta.get("return_1h", 0)) * 100
            evt = meta.get("event_type", "")
            sev = meta.get("severity", "")
            ts = meta.get("timestamp", "")

            ret_color = "#22c55e" if ret >= 0 else "#f87171"
            ret_str = f"{ret:+.2f}%"

            # Find cause (top support evidence)
            sources = support_sources.get(fid, [])
            cause_parts = []
            for sid in sources[:2]:
                sn = node_map.get(sid)
                if sn:
                    cause_parts.append(sn.get("statement", "")[:60])
            cause_str = " | ".join(cause_parts) if cause_parts else "no attribution"

            # Format timestamp for display
            try:
                ts_display = pd.to_datetime(ts).strftime("%m/%d %H:%M") if ts else "?"
            except Exception:
                ts_display = time_ago(ts)

            st.markdown(
                f'<div class="ev-card {evt}">'
                f'<span class="ev-ticker">{ticker}</span>'
                f'<span class="ev-return" style="color:{ret_color};">{ret_str}</span>'
                f'<span class="ev-cause">{cause_str}</span>'
                f'<span style="font-family:DM Mono,monospace;font-size:0.62rem;color:#4a5068;min-width:90px;text-align:right;">{ts_display}</span>'
                f'<span class="ev-time">{time_ago(ts)}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # ── Asset Price Charts ──
        st.markdown('<p class="sec">Asset Charts</p>', unsafe_allow_html=True)

        # Get unique tickers from filtered events
        event_tickers = list(dict.fromkeys(
            f.get("metadata", {}).get("ticker", "") for f in filtered[:40] if f.get("metadata", {}).get("ticker")
        ))[:8]

        if event_tickers:
            selected_ticker = st.selectbox("Ticker", event_tickers, label_visibility="collapsed")
            price_df = load_prices(hours=120)
            if not price_df.empty and selected_ticker:
                import plotly.graph_objects as go
                tk_data = price_df[price_df["ticker"] == selected_ticker].sort_values("timestamp")
                if not tk_data.empty:
                    # Candlestick chart
                    fig = go.Figure(data=[go.Candlestick(
                        x=tk_data["timestamp"],
                        open=tk_data["open"], high=tk_data["high"],
                        low=tk_data["low"], close=tk_data["close"],
                        increasing_line_color="#22c55e", decreasing_line_color="#f87171",
                        increasing_fillcolor="#22c55e", decreasing_fillcolor="#f87171",
                    )])

                    # Mark events on chart
                    tk_events = [f for f in filtered if f.get("metadata", {}).get("ticker") == selected_ticker]
                    for ev in tk_events[:10]:
                        ev_ts = ev.get("metadata", {}).get("timestamp", "")
                        ev_ret = float(ev.get("metadata", {}).get("return_1h", 0)) * 100
                        ev_type = ev.get("metadata", {}).get("event_type", "")
                        try:
                            ev_time = pd.to_datetime(ev_ts)
                            # Find closest price
                            closest = tk_data.iloc[(tk_data["timestamp"] - ev_time).abs().argsort()[:1]]
                            if not closest.empty:
                                y_val = float(closest["high"].iloc[0]) * 1.005
                                color = "#22c55e" if ev_ret >= 0 else "#f87171"
                                fig.add_annotation(
                                    x=ev_time, y=y_val,
                                    text=f"{ev_type}<br>{ev_ret:+.1f}%",
                                    showarrow=True, arrowhead=2, arrowsize=0.8,
                                    arrowcolor=color, font=dict(size=9, color=color),
                                    bgcolor="rgba(18,20,26,0.9)", bordercolor=color,
                                    borderwidth=1, borderpad=3,
                                )
                        except Exception:
                            pass

                    fig.update_layout(
                        height=300, margin=dict(l=0, r=0, t=10, b=0),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        xaxis=dict(showgrid=False, color="#4a5068", tickfont=dict(size=9),
                                   rangeslider=dict(visible=False)),
                        yaxis=dict(showgrid=True, gridcolor="#1c1f2e", color="#4a5068",
                                   tickfont=dict(size=9)),
                        hovermode="x unified",
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.markdown(f'<div class="empty">No price data for {selected_ticker}</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════
# TAB 3 — PAPER TRADE
# ═══════════════════════════════════════════════
with tab_trading:
    from src.db.schema import thread_connection, init_db as _init_db

    # Ensure trades table exists
    with thread_connection() as _conn:
        _init_db(_conn)

    # ── Open New Trade ──
    st.markdown('<p class="sec">Open Trade from Signal</p>', unsafe_allow_html=True)

    if claims:
        # Build signal options with direction
        sig_options = {}
        for c in claims:
            cid = c.get("id", "")
            linked_s = support_sources.get(cid, [])
            linked_f = [node_map[s] for s in linked_s if s in node_map and node_map[s].get("kind") == "Fact"]
            rets = [float(f.get("metadata", {}).get("return_1h", 0)) for f in linked_f if f.get("metadata", {}).get("return_1h")]
            avg = sum(rets) / len(rets) * 100 if rets else 0
            direction = "long" if avg > 0 else "short"
            tickers_in = list(set(f.get("metadata", {}).get("ticker", "") for f in linked_f if f.get("metadata", {}).get("ticker")))
            sig_options[c.get("statement", "")[:60]] = {
                "id": cid, "direction": direction, "tickers": tickers_in[:5], "avg_ret": avg
            }

        tc1, tc2, tc3 = st.columns([3, 1, 1])
        with tc1:
            sel_sig = st.selectbox("Signal", list(sig_options.keys()), label_visibility="collapsed")
        sig_info = sig_options.get(sel_sig, {})
        with tc2:
            trade_ticker = st.selectbox("Ticker", sig_info.get("tickers", ["BTC-USD"]) or ["BTC-USD"], label_visibility="collapsed")
        with tc3:
            trade_dir = st.selectbox("Direction", ["long", "short"], index=0 if sig_info.get("direction") == "long" else 1, label_visibility="collapsed")

        if st.button("Execute Paper Trade", type="primary"):
            # Get current price from SQLite
            price_df = load_prices(hours=24)
            tk_prices = price_df[price_df["ticker"] == trade_ticker].sort_values("timestamp")
            if not tk_prices.empty:
                entry_price = float(tk_prices["close"].iloc[-1])
                entry_time = datetime.now(timezone.utc).isoformat()
                from src.db.queries import open_trade
                with thread_connection() as conn:
                    tid = open_trade(conn, sig_info.get("id", ""), sel_sig, trade_ticker, trade_dir, entry_price, entry_time)
                st.success(f"Opened {trade_dir.upper()} {trade_ticker} @ {entry_price:.2f} (trade #{tid})")
            else:
                st.error(f"No price data for {trade_ticker}")

    else:
        st.markdown('<div class="empty">No signals available to trade</div>', unsafe_allow_html=True)

    st.markdown('<hr class="div">', unsafe_allow_html=True)

    # ── Open Positions ──
    st.markdown('<p class="sec">Open Positions</p>', unsafe_allow_html=True)

    from src.db.queries import get_open_trades, close_trade as _close_trade, get_trade_history, get_trade_stats
    with thread_connection() as conn:
        open_trades = get_open_trades(conn)

    if not open_trades.empty:
        price_df = load_prices(hours=24)
        for _, trade in open_trades.iterrows():
            tk = trade["ticker"]
            direction = trade["direction"]
            entry_p = trade["entry_price"]
            tid = trade["id"]

            # Get current price
            tk_p = price_df[price_df["ticker"] == tk].sort_values("timestamp")
            current_p = float(tk_p["close"].iloc[-1]) if not tk_p.empty else entry_p
            if direction == "long":
                unrealized = (current_p - entry_p) / entry_p * 100
            else:
                unrealized = (entry_p - current_p) / entry_p * 100

            pnl_color = "#22c55e" if unrealized >= 0 else "#f87171"
            pnl_str = f"{unrealized:+.2f}%"

            col_a, col_b, col_c = st.columns([3, 1, 1])
            with col_a:
                st.markdown(
                    f'<div style="background:#12141a;border-left:3px solid {pnl_color};padding:10px 14px;border-radius:0 6px 6px 0;">'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.82rem;font-weight:600;color:#e4e8f0;">{tk}</span>'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.68rem;color:#4a5068;margin-left:10px;">{direction.upper()}</span>'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.68rem;color:#4a5068;margin-left:10px;">entry: {entry_p:.2f}</span>'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.68rem;color:#4a5068;margin-left:10px;">now: {current_p:.2f}</span>'
                    f'<span style="font-family:DM Mono,monospace;font-size:0.92rem;font-weight:700;color:{pnl_color};margin-left:14px;">{pnl_str}</span>'
                    f'<div style="font-size:0.7rem;color:#4a5068;margin-top:2px;">{trade.get("narrative","")[:50]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with col_b:
                st.markdown("")  # spacer
            with col_c:
                if st.button(f"Close #{tid}", key=f"close_{tid}"):
                    with thread_connection() as conn:
                        pnl = _close_trade(conn, tid, current_p, datetime.now(timezone.utc).isoformat())
                    st.rerun()
    else:
        st.markdown('<div class="empty">No open positions</div>', unsafe_allow_html=True)

    st.markdown('<hr class="div">', unsafe_allow_html=True)

    # ── Performance ──
    st.markdown('<p class="sec">Trading Performance</p>', unsafe_allow_html=True)

    with thread_connection() as conn:
        stats = get_trade_stats(conn)
        history = get_trade_history(conn, limit=50)

    if stats["total"] > 0:
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Total Trades", stats["total"])
        s2.metric("Win Rate", f"{stats['win_rate']}%")
        s3.metric("Avg P&L", f"{stats['avg_pnl']:+.2f}%")
        s4.metric("Total P&L", f"{stats['total_pnl']:+.2f}%")

    if not history.empty:
        display_cols = [c for c in ["ticker", "direction", "entry_price", "exit_price", "pnl_pct", "status", "narrative", "entry_time"]
                        if c in history.columns]
        disp = history[display_cols].copy()
        if "pnl_pct" in disp.columns:
            disp["pnl_pct"] = disp["pnl_pct"].apply(lambda v: f"{v:+.2f}%" if pd.notna(v) else "open")
        if "narrative" in disp.columns:
            disp["narrative"] = disp["narrative"].str[:40]
        st.dataframe(disp, use_container_width=True, hide_index=True)
    elif stats["total"] == 0:
        st.markdown('<div class="empty">No trades yet. Open a trade from a signal above.</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════
# TAB 4 — EXPLORER (RAG Search + Graph Stats)
# ═══════════════════════════════════════════════
with tab_explorer:

    # Search
    st.markdown('<p class="sec">RAG Search</p>', unsafe_allow_html=True)
    query = st.text_input("Search", placeholder="BTC ETF, semiconductor HBM, tariff crash...", label_visibility="collapsed")
    if query:
        client = get_client()
        results = client.search(query, top_k=15)
        if results:
            for r in results:
                kind_class = f"k-{r.kind.lower()}"
                failed = ' <span style="color:#f87171;font-size:0.62rem;">[FAILED]</span>' if r.failed_path else ""
                st.markdown(
                    f'<div class="sr-card">'
                    f'<span class="sr-kind {kind_class}">{r.kind}</span>'
                    f'<span class="sr-score" style="margin-left:10px;">score: {r.score:.3f}</span>{failed}'
                    f'<div class="sr-stmt">{r.statement[:150]}</div></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(f'<div class="empty">No results for "{query}"</div>', unsafe_allow_html=True)

    # Graph stats
    st.markdown('<p class="sec">Graph Overview</p>', unsafe_allow_html=True)
    kinds = summary.get("node_kinds", {})
    edge_kinds = summary.get("edge_kinds", {})

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Claims", kinds.get("Claim", 0))
    c2.metric("Evidence", kinds.get("Evidence", 0))
    c3.metric("Facts", kinds.get("Fact", 0))
    c4.metric("Reasons", kinds.get("Reason", 0))
    c5.metric("Experiments", kinds.get("Experiment", 0))

    st.markdown('<hr class="div">', unsafe_allow_html=True)

    ec1, ec2, ec3 = st.columns(3)
    ec1.metric("Support", edge_kinds.get("Support", 0))
    ec2.metric("DependsOn", edge_kinds.get("DependsOn", 0))
    ec3.metric("DerivedFrom", edge_kinds.get("DerivedFrom", 0))

    # Causal explanation
    st.markdown('<p class="sec">Causal Trace</p>', unsafe_allow_html=True)
    if facts:
        options = {
            f"{f.get('metadata',{}).get('ticker','')} {f.get('metadata',{}).get('event_type','')} ({time_ago(f.get('metadata',{}).get('timestamp',''))})": f.get("id","")
            for f in facts_sorted[:20]
        }
        sel = st.selectbox("Select event", [""] + list(options.keys()), label_visibility="collapsed")
        if sel and options.get(sel):
            client = get_client()
            neighbors = client.walk(options[sel], hops=2)
            if isinstance(neighbors, dict):
                neighbors = neighbors.get("nodes", [])
            for n in neighbors[:10]:
                kind = n.get("kind", "")
                kind_class = f"k-{kind.lower()}"
                st.markdown(
                    f'<div style="background:#12141a;border-left:3px solid #1c1f2e;padding:8px 12px;margin-bottom:4px;border-radius:0 4px 4px 0;">'
                    f'<span class="{kind_class}" style="font-family:DM Mono,monospace;font-size:0.62rem;font-weight:600;">{kind}</span> '
                    f'<span style="font-size:0.78rem;color:#c0c8d8;">{n.get("statement","")[:100]}</span></div>',
                    unsafe_allow_html=True,
                )
