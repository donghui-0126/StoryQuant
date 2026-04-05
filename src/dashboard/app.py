"""
StoryQuant Dashboard
뉴스 기반 멀티에셋 Hot Topic & Price Move Attribution 대시보드
SQLite 기반 (CSV 폴백 지원)
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
DB_PATH = str(DATA_DIR / "storyquant.db")

# ── Page config ──────────────────────────────────────────────
st.set_page_config(page_title="StoryQuant", page_icon="📊", layout="wide")

import plotly.io as pio
pio.templates.default = "plotly_dark"

st.markdown("""
<style>
    /* Compact metrics */
    [data-testid="stMetric"] {
        background-color: #1e1e2e;
        border: 1px solid #333;
        border-radius: 8px;
        padding: 12px;
    }
    [data-testid="stMetric"] label {
        font-size: 0.85rem;
    }
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-size: 1.4rem;
    }
    /* Better tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 6px 6px 0 0;
    }
    /* Compact dataframes */
    .stDataFrame {
        font-size: 0.85rem;
    }
    /* News cards */
    .news-card {
        background-color: #1a1a2e;
        border-left: 3px solid #4a9eff;
        padding: 8px 12px;
        margin-bottom: 8px;
        border-radius: 0 4px 4px 0;
    }
    .news-card.exchange {
        border-left-color: #ffd700;
    }
    .news-card.twitter {
        border-left-color: #1da1f2;
    }
    .news-card.community {
        border-left-color: #22c55e;
    }
    /* Sidebar compact */
    section[data-testid="stSidebar"] {
        width: 280px;
    }
    /* Hide hamburger menu */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ── DB connection ────────────────────────────────────────────

@st.cache_resource
def get_db():
    try:
        from src.db.schema import get_connection, init_db
        conn = get_connection(DB_PATH)
        init_db(conn)
        return conn
    except Exception:
        return None


def db_available() -> bool:
    conn = get_db()
    if conn is None:
        return False
    try:
        conn.execute("SELECT 1 FROM articles LIMIT 1")
        return True
    except Exception:
        return False


# ── Data loaders (DB with CSV fallback) ─────────────────────

@st.cache_data(ttl=30)
def load_articles(hours: int = 24, market: list = None) -> pd.DataFrame:
    conn = get_db()
    if conn is not None:
        try:
            from src.db.queries import get_recent_articles
            frames = []
            if market:
                for m in market:
                    frames.append(get_recent_articles(conn, hours=hours, market=m))
            else:
                frames.append(get_recent_articles(conn, hours=hours))
            df = pd.concat(frames, ignore_index=True).drop_duplicates(subset="id") if frames else pd.DataFrame()
            return df
        except Exception:
            pass
    return _csv_fallback("news")


@st.cache_data(ttl=30)
def load_topics(hours: int = 24) -> pd.DataFrame:
    conn = get_db()
    if conn is not None:
        try:
            from src.db.queries import get_recent_topics
            return get_recent_topics(conn, hours=hours)
        except Exception:
            pass
    return _csv_fallback("topics")


@st.cache_data(ttl=30)
def load_events(hours: int = 24) -> pd.DataFrame:
    conn = get_db()
    if conn is not None:
        try:
            from src.db.queries import get_recent_events
            return get_recent_events(conn, hours=hours)
        except Exception:
            pass
    return _csv_fallback("events")


@st.cache_data(ttl=30)
def load_prices(ticker: str = None, hours: int = 72) -> pd.DataFrame:
    conn = get_db()
    if conn is not None:
        try:
            from src.db.queries import get_recent_prices
            return get_recent_prices(conn, ticker=ticker, hours=hours)
        except Exception:
            pass
    return _csv_fallback("prices")


@st.cache_data(ttl=30)
def load_attributions(event_ids: list = None) -> pd.DataFrame:
    conn = get_db()
    if conn is not None:
        try:
            from src.db.queries import get_attributions_for_events
            ids = event_ids or []
            return get_attributions_for_events(conn, ids)
        except Exception:
            pass
    return _csv_fallback_attribution()


@st.cache_data(ttl=60)
def load_historical_patterns(ticker: str = None) -> pd.DataFrame:
    conn = get_db()
    if conn is not None:
        try:
            from src.db.queries import get_historical_patterns
            return get_historical_patterns(conn, ticker=ticker)
        except Exception:
            pass
    return pd.DataFrame()


def _csv_fallback(subdir: str) -> pd.DataFrame:
    folder = DATA_DIR / subdir
    if not folder.exists():
        return pd.DataFrame()
    files = sorted(folder.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return pd.DataFrame()
    return pd.read_csv(files[0])


def _csv_fallback_attribution() -> pd.DataFrame:
    folder = DATA_DIR / "events"
    if not folder.exists():
        return pd.DataFrame()
    files = sorted(folder.glob("attribution_*.csv"))
    return pd.read_csv(files[-1]) if files else pd.DataFrame()


@st.cache_data(ttl=30)
def get_db_stats() -> dict:
    conn = get_db()
    if conn is None:
        return {}
    try:
        stats = {}
        stats["articles"] = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        stats["events"] = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        stats["prices"] = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        db_file = Path(DB_PATH)
        stats["db_size_mb"] = round(db_file.stat().st_size / 1024 / 1024, 2) if db_file.exists() else 0
        return stats
    except Exception:
        return {}


# ── Background ingester support ─────────────────────────────

_bg_ingester = None

def get_background_ingester():
    global _bg_ingester
    if _bg_ingester is None:
        try:
            from src.background import BackgroundIngester
            _bg_ingester = BackgroundIngester()
        except ImportError:
            pass
    return _bg_ingester


# ── Sidebar ──────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ StoryQuant")
    st.markdown("---")

    # Pipeline controls
    st.markdown("### 파이프라인")
    if st.button("🔄 파이프라인 실행", use_container_width=True):
        with st.spinner("데이터 수집 및 분석 중..."):
            try:
                from src.pipeline import run_pipeline
                results = run_pipeline()
                st.success(f"완료! 뉴스 {len(results.get('news', []))}건 처리")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"오류: {e}")

    # Background ingester toggle
    ingester = get_background_ingester()
    if ingester is not None:
        try:
            is_running = ingester.is_running()
        except Exception:
            is_running = False
        label = "⏹ 백그라운드 중지" if is_running else "▶ 백그라운드 시작"
        if st.button(label, use_container_width=True):
            try:
                if is_running:
                    ingester.stop()
                    st.info("백그라운드 인제스터 중지됨")
                else:
                    ingester.start()
                    st.success("백그라운드 인제스터 시작됨")
            except Exception as e:
                st.error(f"오류: {e}")
        if is_running:
            st.success("백그라운드: 실행 중")
        else:
            st.warning("백그라운드: 중지됨")
    else:
        st.caption("백그라운드 인제스터 미설치")

    st.markdown("---")
    st.markdown("### 필터")
    market_filter = st.multiselect(
        "시장", ["crypto", "us", "kr"], default=["crypto", "us", "kr"]
    )
    source_type_filter = st.multiselect(
        "소스 유형", ["rss", "twitter", "exchange_announcement"],
        default=["rss", "twitter", "exchange_announcement"]
    )

    st.markdown("---")
    st.markdown("### DB 통계")
    stats = get_db_stats()
    if stats:
        st.metric("총 기사", f"{stats.get('articles', 0):,}건")
        st.metric("총 이벤트", f"{stats.get('events', 0):,}건")
        st.metric("DB 크기", f"{stats.get('db_size_mb', 0)} MB")
    else:
        st.caption("DB 연결 없음")

    # Telegram status
    st.markdown("---")
    st.markdown("### 📱 알림")
    try:
        from src.alerts.telegram_bot import telegram_available
        if telegram_available():
            st.success("✅ Telegram 연결됨")
        else:
            st.caption("Telegram 미설정")
            with st.popover("설정 방법"):
                st.markdown(
                    "1. Telegram에서 @BotFather로 봇 생성\n"
                    "2. @userinfobot으로 Chat ID 확인\n"
                    "3. 환경변수 설정:\n"
                    "```\nexport TELEGRAM_BOT_TOKEN=xxx\nexport TELEGRAM_CHAT_ID=xxx\n```"
                )
    except ImportError:
        pass

    st.markdown("---")
    st.caption(f"마지막 갱신: {datetime.now().strftime('%H:%M:%S')}")
    st.markdown(
        "**StoryQuant PoC**  \n"
        "뉴스 기반 멀티에셋  \n"
        "Hot Topic & Attribution"
    )

# ── Load data ────────────────────────────────────────────────

news_df = load_articles(hours=168, market=market_filter if market_filter else None)
topics_df = load_topics(hours=168)
events_df = load_events(hours=168)
prices_df = load_prices()

# Apply source_type filter to news
if not news_df.empty and "source_type" in news_df.columns and source_type_filter:
    news_df = news_df[news_df["source_type"].isin(source_type_filter)]

# ── Header ───────────────────────────────────────────────────

st.title("📊 StoryQuant Dashboard")
st.caption("뉴스 기반 멀티에셋 Hot Topic & Price Move Attribution")

# ── KPI Row ──────────────────────────────────────────────────

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("📰 수집 뉴스", f"{len(news_df):,}건")
with col2:
    st.metric("🔥 Hot Topics", f"{len(topics_df):,}개")
with col3:
    event_only = events_df[events_df["event_type"].notna()] if not events_df.empty and "event_type" in events_df.columns else pd.DataFrame()
    st.metric("⚡ 가격 이벤트", f"{len(event_only):,}건")
with col4:
    if not event_only.empty and "id" in event_only.columns:
        attr_df = load_attributions(event_ids=event_only["id"].tolist())
    else:
        attr_df = _csv_fallback_attribution()
    n_attr = len(attr_df[attr_df["confidence"].notna()]) if not attr_df.empty and "confidence" in attr_df.columns else 0
    st.metric("🔗 Attribution", f"{n_attr:,}건")

st.markdown("---")

# ── Market View (Claude Code 시장 분석) ──────────────────
with st.expander("🧠 AI 시장 분석 (Claude Code)", expanded=False):
    try:
        from src.analysis.claude_hook import generate_market_report, get_latest_report, list_reports
        from src.analysis.market_view import generate_market_view

        col_btn1, col_btn2, col_info = st.columns([1, 1, 3])

        with col_btn1:
            run_claude = st.button("🚀 Claude Code 분석 실행", key="run_claude_analysis")
        with col_btn2:
            run_fallback = st.button("📋 빠른 요약 (룰 기반)", key="run_fallback")

        if run_claude:
            with st.spinner("🧠 Claude Code가 시장 데이터를 분석하고 있습니다... (최대 2분)"):
                result = generate_market_report(timeout=120)
                if result["success"]:
                    st.success("분석 완료!")
                    st.markdown(result["report_text"])
                else:
                    st.error(f"분석 실패: {result['error']}")
        elif run_fallback:
            conn_fb = get_db()
            if conn_fb:
                view = generate_market_view(conn_fb, language="ko")
                st.markdown(view)
        else:
            # Show latest report if exists
            latest = get_latest_report()
            if latest["exists"]:
                st.caption(f"마지막 분석: {latest['generated_at']}")
                st.markdown(latest["report_text"])
            else:
                st.info(
                    "아직 분석 리포트가 없습니다.\n\n"
                    "- **🚀 Claude Code 분석**: Claude Code 세션을 띄워서 DB 데이터를 직접 분석합니다 (추천)\n"
                    "- **📋 빠른 요약**: 룰 기반으로 즉시 요약을 생성합니다"
                )

        # Show report history
        reports = list_reports(5)
        if reports:
            with st.popover("📂 이전 리포트"):
                for r in reports:
                    st.caption(f"{r['generated_at']} ({r['size_kb']}KB)")

    except ImportError as e:
        st.warning(f"시장 분석 모듈 로드 실패: {e}")
    except Exception as e:
        st.error(f"오류: {e}")

st.markdown("---")

# ── Tab Layout ───────────────────────────────────────────────

tab_rt, tab_topics, tab_events, tab_attr, tab_hist, tab_corr, tab_deriv, tab_whale, tab_news, tab_paper = st.tabs([
    "📡 실시간", "🔥 Hot Topics", "📈 Price Events", "🔗 Attribution",
    "📊 히스토리컬 분석", "🔄 상관관계", "💧 청산/OI", "🐋 고래 추적", "📰 뉴스 피드", "📊 페이퍼 트레이딩",
])

# ── Tab 1: 실시간 (Real-time) ────────────────────────────────

with tab_rt:
    st.subheader("📡 실시간 이벤트 피드")
    st.caption("최근 1시간 가격 이벤트 및 매칭된 뉴스 (30초 자동 갱신)")

    recent_events = load_events(hours=1)
    recent_articles = load_articles(hours=1)

    if recent_events.empty:
        st.info("최근 1시간 내 감지된 가격 이벤트가 없습니다. 파이프라인을 실행해주세요.")
    else:
        # KPI strip
        rt_col1, rt_col2, rt_col3 = st.columns(3)
        with rt_col1:
            st.metric("이벤트 (1h)", f"{len(recent_events)}건")
        with rt_col2:
            n_high = len(recent_events[recent_events.get("severity", pd.Series()) == "high"]) if "severity" in recent_events.columns else 0
            st.metric("고위험", f"{n_high}건")
        with rt_col3:
            st.metric("관련 뉴스", f"{len(recent_articles)}건")

        st.markdown("---")

        for _, ev in recent_events.iterrows():
            severity = ev.get("severity", "")
            sev_color = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
            event_type = ev.get("event_type", "")
            ret = ev.get("return_1h", 0.0)
            try:
                ret_str = f"{float(ret):+.2%}"
            except (TypeError, ValueError):
                ret_str = str(ret)
            ticker = ev.get("ticker", "N/A")
            ts = ev.get("timestamp", "")

            with st.container():
                c1, c2 = st.columns([1, 3])
                with c1:
                    st.markdown(
                        f"### {sev_color} {ticker}  \n"
                        f"`{ret_str}` | {event_type}  \n"
                        f"<small>{ts}</small>",
                        unsafe_allow_html=True,
                    )
                with c2:
                    # Show matched news articles if available
                    ev_id = ev.get("id")
                    matched = pd.DataFrame()
                    if ev_id and not recent_articles.empty:
                        conn = get_db()
                        if conn is not None:
                            try:
                                from src.db.queries import get_attributions_for_events
                                ev_attr = get_attributions_for_events(conn, [int(ev_id)])
                                if not ev_attr.empty and "article_id" in ev_attr.columns:
                                    art_ids = ev_attr["article_id"].dropna().astype(int).tolist()
                                    if art_ids and "id" in recent_articles.columns:
                                        matched = recent_articles[recent_articles["id"].isin(art_ids)]
                            except Exception:
                                pass

                    if not matched.empty:
                        for _, art in matched.head(2).iterrows():
                            st.markdown(
                                f"- **{art.get('title', 'N/A')}**  \n"
                                f"  <small>{art.get('source', '')} · {art.get('published_at', '')}</small>",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("매칭된 뉴스 없음")

            st.markdown("---")

# ── Tab 2: Hot Topics ────────────────────────────────────────

with tab_topics:
    if topics_df.empty:
        st.info("토픽 데이터가 없습니다. 사이드바에서 파이프라인을 실행해주세요.")
    else:
        st.subheader("실시간 Hot Topic 랭킹")

        col_left, col_right = st.columns([3, 2])

        with col_left:
            if "frequency" in topics_df.columns and "topic_label" in topics_df.columns:
                display_df = topics_df.sort_values("frequency", ascending=True).tail(10)
                fig = px.bar(
                    display_df,
                    x="frequency",
                    y="topic_label",
                    orientation="h",
                    title="Topic Frequency Ranking",
                    color="frequency",
                    color_continuous_scale="YlOrRd",
                )
                fig.update_layout(
                    height=400,
                    showlegend=False,
                    yaxis_title="",
                    xaxis_title="빈도",
                    coloraxis_showscale=False,
                )
                st.plotly_chart(fig, use_container_width=True)

        with col_right:
            if "momentum_score" in topics_df.columns:
                score_cols = ["topic_label", "frequency", "momentum_score", "novelty_score"]
                available_cols = [c for c in score_cols if c in topics_df.columns]
                sort_col = "momentum_score" if "momentum_score" in available_cols else "frequency"
                st.dataframe(
                    topics_df[available_cols].sort_values(sort_col, ascending=False),
                    use_container_width=True,
                    hide_index=True,
                )

        # Topic heatmap by market
        if "market" in topics_df.columns and "topic_label" in topics_df.columns:
            st.subheader("시장별 Topic Heatmap")
            pivot = topics_df.pivot_table(
                index="topic_label", columns="market", values="frequency", aggfunc="sum", fill_value=0
            )
            fig_heat = px.imshow(
                pivot,
                text_auto=True,
                color_continuous_scale="Blues",
                title="Market x Topic Frequency",
            )
            fig_heat.update_layout(height=350)
            st.plotly_chart(fig_heat, use_container_width=True)

        # Topic persistence chart
        if "created_at" in topics_df.columns and "topic_label" in topics_df.columns:
            st.subheader("토픽 지속 시간")
            try:
                df_persist = topics_df.copy()
                df_persist["created_at"] = pd.to_datetime(df_persist["created_at"], utc=True, errors="coerce")
                now = pd.Timestamp.now(tz="UTC")
                df_persist = df_persist.dropna(subset=["created_at"])
                if not df_persist.empty:
                    df_persist["hours_active"] = (now - df_persist["created_at"]).dt.total_seconds() / 3600
                    # Use earliest appearance per topic_label
                    persist_agg = (
                        df_persist.groupby("topic_label")["hours_active"]
                        .max()
                        .reset_index()
                        .sort_values("hours_active", ascending=False)
                        .head(10)
                    )
                    fig_persist = px.bar(
                        persist_agg,
                        x="hours_active",
                        y="topic_label",
                        orientation="h",
                        title="토픽별 최장 활성 시간 (시간)",
                        color="hours_active",
                        color_continuous_scale="Purples",
                    )
                    fig_persist.update_layout(
                        height=350,
                        yaxis_title="",
                        xaxis_title="시간 (h)",
                        coloraxis_showscale=False,
                    )
                    st.plotly_chart(fig_persist, use_container_width=True)
            except Exception:
                st.caption("토픽 지속 시간 차트를 생성할 수 없습니다.")

# ── Tab 3: Price Events ─────────────────────────────────────

with tab_events:
    if event_only.empty:
        st.info("가격 이벤트 데이터가 없습니다. 파이프라인을 실행해주세요.")
    else:
        st.subheader("가격 변동 이벤트")

        col_a, col_b = st.columns(2)
        with col_a:
            if "event_type" in event_only.columns:
                type_counts = event_only["event_type"].value_counts()
                fig_pie = px.pie(
                    values=type_counts.values,
                    names=type_counts.index,
                    title="이벤트 유형 분포",
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig_pie.update_layout(height=350)
                st.plotly_chart(fig_pie, use_container_width=True)

        with col_b:
            if "severity" in event_only.columns:
                sev_counts = event_only["severity"].value_counts()
                fig_sev = px.bar(
                    x=sev_counts.index,
                    y=sev_counts.values,
                    title="이벤트 심각도 분포",
                    color=sev_counts.index,
                    color_discrete_map={"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"},
                )
                fig_sev.update_layout(
                    height=350, showlegend=False, xaxis_title="", yaxis_title="건수"
                )
                st.plotly_chart(fig_sev, use_container_width=True)

        st.subheader("이벤트 상세")
        display_cols = [
            c for c in ["ticker", "timestamp", "return_1h", "volume_ratio", "event_type", "severity"]
            if c in event_only.columns
        ]
        sort_col = "timestamp" if "timestamp" in display_cols else display_cols[0]
        st.dataframe(
            event_only[display_cols].sort_values(sort_col, ascending=False),
            column_config={
                "return_1h": st.column_config.NumberColumn("수익률(1h)", format="%.2f%%"),
                "volume_ratio": st.column_config.NumberColumn("거래량비율", format="%.1f"),
            },
            use_container_width=True,
            hide_index=True,
        )

    # Price candlestick from DB
    if not prices_df.empty and "ticker" in prices_df.columns:
        st.subheader("가격 추이 (캔들스틱)")
        ticker_list = sorted(prices_df["ticker"].unique().tolist())
        selected_ticker = st.selectbox("자산 선택", ticker_list)
        ticker_data = load_prices(ticker=selected_ticker, hours=72)
        if not ticker_data.empty and "timestamp" in ticker_data.columns:
            ticker_data["timestamp"] = pd.to_datetime(ticker_data["timestamp"], errors="coerce")
            ticker_data = ticker_data.dropna(subset=["timestamp"])
            required = {"open", "high", "low", "close"}
            if required.issubset(set(ticker_data.columns)):
                # Build time selector before chart so vline can be drawn
                timestamps = ticker_data["timestamp"].sort_values().reset_index(drop=True)
                time_options = timestamps.dt.strftime("%Y-%m-%d %H:%M").tolist()
                selected_idx = st.selectbox(
                    "시간대 선택 (캔들 탐색)",
                    range(len(time_options)),
                    format_func=lambda i: time_options[i],
                    index=len(time_options) - 1,
                    key="candle_time_selector",
                )
                selected_time = timestamps.iloc[selected_idx]

                fig_price = go.Figure()
                fig_price.add_trace(go.Candlestick(
                    x=ticker_data["timestamp"],
                    open=ticker_data["open"],
                    high=ticker_data["high"],
                    low=ticker_data["low"],
                    close=ticker_data["close"],
                    name=selected_ticker,
                    increasing_line_color="#22c55e",
                    decreasing_line_color="#ef4444",
                ))
                fig_price.update_layout(
                    title=f"{selected_ticker} 가격 차트 (72h)",
                    height=400,
                    xaxis_rangeslider_visible=False,
                )
                # Highlight selected candle with a vertical dashed line
                fig_price.add_vline(
                    x=selected_time.timestamp() * 1000,
                    line_dash="dash",
                    line_color="yellow",
                    opacity=0.7,
                )
                st.plotly_chart(fig_price, use_container_width=True)

                # ── Candle-to-news explorer ──────────────────────────
                st.subheader("🔍 캔들 클릭 → 뉴스 탐색")
                st.caption("시간대를 선택하면 해당 시점의 관련 뉴스를 볼 수 있습니다")

                # Show OHLC metrics for selected candle
                candle = ticker_data[ticker_data["timestamp"] == selected_time]
                if not candle.empty:
                    row = candle.iloc[0]
                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        st.metric("시가", f"{float(row['open']):,.2f}")
                    with c2:
                        st.metric("고가", f"{float(row['high']):,.2f}")
                    with c3:
                        st.metric("저가", f"{float(row['low']):,.2f}")
                    with c4:
                        open_val = float(row['open'])
                        close_val = float(row['close'])
                        change = ((close_val - open_val) / open_val * 100) if open_val else 0
                        st.metric("종가", f"{close_val:,.2f}", f"{change:+.2f}%")

                conn_ev = get_db()
                if conn_ev is not None:
                    # Make window timestamps timezone-naive strings for SQLite
                    sel_naive = selected_time.tz_localize(None) if selected_time.tzinfo is not None else selected_time
                    window_start = (sel_naive - pd.Timedelta(hours=1)).isoformat()
                    window_end = (sel_naive + pd.Timedelta(hours=1)).isoformat()

                    # Show events near the selected time
                    try:
                        nearby_events = pd.read_sql_query(
                            "SELECT * FROM events WHERE ticker = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
                            conn_ev,
                            params=[selected_ticker, window_start, window_end],
                        )
                    except Exception:
                        nearby_events = pd.DataFrame()

                    if not nearby_events.empty:
                        st.markdown("#### ⚡ 이 시간대 이벤트")
                        for _, ev in nearby_events.iterrows():
                            sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                                str(ev.get("severity", "")), "⚪"
                            )
                            ret_val = float(ev.get("return_1h", 0) or 0)
                            st.markdown(
                                f"{sev_icon} **{ev.get('event_type', '')}** | return: `{ret_val:+.2%}`"
                            )

                    # Show news near the selected time
                    try:
                        nearby_news = pd.read_sql_query(
                            "SELECT * FROM articles WHERE published_at BETWEEN ? AND ? ORDER BY published_at DESC",
                            conn_ev,
                            params=[window_start, window_end],
                        )
                    except Exception:
                        nearby_news = pd.DataFrame()

                    if nearby_news.empty:
                        st.info("이 시간대에 관련 뉴스가 없습니다.")
                    else:
                        st.markdown(f"#### 📰 관련 뉴스 ({len(nearby_news)}건)")
                        for _, art in nearby_news.iterrows():
                            source_type = str(art.get("source_type", "rss") or "rss")
                            badge = {
                                "rss": "📡",
                                "twitter": "🐦",
                                "exchange_announcement": "🏛️",
                                "community": "💬",
                            }.get(source_type, "📰")
                            title = art.get("title", "N/A") or "N/A"
                            source = art.get("source", "") or ""
                            pub = art.get("published_at", "") or ""
                            url = art.get("url", "") or ""
                            if url:
                                st.markdown(
                                    f"{badge} **[{title}]({url})**  \n<small>{source} · {pub}</small>",
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.markdown(
                                    f"{badge} **{title}**  \n<small>{source} · {pub}</small>",
                                    unsafe_allow_html=True,
                                )
                else:
                    st.info("DB 연결이 없어 뉴스를 불러올 수 없습니다.")
        else:
            st.info(f"{selected_ticker} 가격 데이터가 없습니다.")

# ── Tab 4: Attribution ───────────────────────────────────────

with tab_attr:
    st.subheader("뉴스 <-> 가격 변동 Attribution")

    if attr_df.empty:
        st.info("Attribution 데이터가 없습니다. 파이프라인을 실행해주세요.")
    else:
        # Join with articles to get titles and URLs
        conn = get_db()
        enriched_attr = attr_df.copy()
        if conn is not None and "article_id" in attr_df.columns:
            try:
                art_ids = attr_df["article_id"].dropna().astype(int).tolist()
                if art_ids:
                    placeholders = ",".join("?" * len(art_ids))
                    art_detail = pd.read_sql_query(
                        f"SELECT id, title, url, source, source_type FROM articles WHERE id IN ({placeholders})",
                        conn,
                        params=art_ids,
                    )
                    enriched_attr = enriched_attr.merge(
                        art_detail.rename(columns={"id": "article_id"}),
                        on="article_id",
                        how="left",
                    )
            except Exception:
                pass

        # Join with events for ticker context
        if conn is not None and "event_id" in attr_df.columns:
            try:
                ev_ids = attr_df["event_id"].dropna().astype(int).tolist()
                if ev_ids:
                    placeholders = ",".join("?" * len(ev_ids))
                    ev_detail = pd.read_sql_query(
                        f"SELECT id, ticker, return_1h, event_type FROM events WHERE id IN ({placeholders})",
                        conn,
                        params=ev_ids,
                    )
                    enriched_attr = enriched_attr.merge(
                        ev_detail.rename(columns={"id": "event_id"}),
                        on="event_id",
                        how="left",
                        suffixes=("", "_ev"),
                    )
            except Exception:
                pass

        # Display cards with links
        if "title" in enriched_attr.columns:
            for _, row in enriched_attr.sort_values(
                "total_score" if "total_score" in enriched_attr.columns else enriched_attr.columns[0],
                ascending=False,
            ).head(20).iterrows():
                confidence = row.get("confidence", "")
                sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(confidence, "⚪")
                ticker = row.get("ticker", "")
                ret = row.get("return_1h", None)
                try:
                    ret_str = f"{float(ret):+.2%}" if ret is not None else ""
                except (TypeError, ValueError):
                    ret_str = ""
                title = row.get("title", "N/A")
                url = row.get("url", "")
                source = row.get("source", "")
                score = row.get("total_score", "")
                try:
                    score_str = f"{float(score):.2f}" if score != "" else ""
                except (TypeError, ValueError):
                    score_str = str(score)

                title_link = f"[{title}]({url})" if url else title
                st.markdown(
                    f"{sev_icon} **{ticker}** `{ret_str}` — {title_link}  \n"
                    f"<small>{source} | 점수: {score_str} | 신뢰도: {confidence}</small>",
                    unsafe_allow_html=True,
                )
                st.markdown("---")
        else:
            display_cols = [
                c for c in ["ticker", "event_id", "article_id", "total_score", "confidence"]
                if c in enriched_attr.columns
            ]
            if display_cols:
                st.dataframe(
                    enriched_attr[display_cols].sort_values(
                        "total_score" if "total_score" in display_cols else display_cols[0],
                        ascending=False,
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        # Attribution confidence distribution
        if "confidence" in attr_df.columns:
            st.subheader("Attribution Confidence 분포")
            conf_counts = attr_df["confidence"].value_counts()
            fig_conf = px.pie(
                values=conf_counts.values,
                names=conf_counts.index,
                color=conf_counts.index,
                color_discrete_map={"high": "#22c55e", "medium": "#f59e0b", "low": "#ef4444"},
            )
            fig_conf.update_layout(height=300)
            st.plotly_chart(fig_conf, use_container_width=True)

# ── Tab 5: 히스토리컬 분석 ───────────────────────────────────

with tab_hist:
    st.subheader("히스토리컬 분석")

    # News Impact table
    st.markdown("#### 토픽별 가격 영향 (News Impact)")
    hist_df = load_historical_patterns()
    if hist_df.empty:
        st.info("히스토리컬 패턴 데이터가 없습니다. 파이프라인을 더 실행하면 데이터가 쌓입니다.")
    else:
        display_hist_cols = [
            c for c in ["topic_label", "ticker", "avg_return_1h", "avg_return_24h", "occurrence_count", "last_seen"]
            if c in hist_df.columns
        ]
        sort_h = "avg_return_1h" if "avg_return_1h" in display_hist_cols else display_hist_cols[0]
        st.dataframe(
            hist_df[display_hist_cols].sort_values(sort_h, ascending=False, key=abs),
            use_container_width=True,
            hide_index=True,
        )

    # Source reliability chart
    st.markdown("#### 소스 신뢰도 (Source Reliability)")
    conn = get_db()
    if conn is not None:
        try:
            reliability_df = pd.read_sql_query(
                """
                SELECT
                    a.source,
                    a.source_type,
                    COUNT(DISTINCT atr.id) AS attribution_count,
                    AVG(atr.total_score) AS avg_score,
                    COUNT(DISTINCT a.id) AS article_count
                FROM articles a
                LEFT JOIN attributions atr ON atr.article_id = a.id
                GROUP BY a.source, a.source_type
                HAVING article_count > 0
                ORDER BY attribution_count DESC
                LIMIT 20
                """,
                conn,
            )
            if not reliability_df.empty:
                fig_rel = px.bar(
                    reliability_df,
                    x="source",
                    y="attribution_count",
                    color="source_type",
                    title="소스별 Attribution 횟수 (예측력 지표)",
                    color_discrete_map={
                        "rss": "#3b82f6",
                        "twitter": "#1d9bf0",
                        "exchange_announcement": "#f59e0b",
                    },
                )
                fig_rel.update_layout(height=350, xaxis_title="", yaxis_title="Attribution 횟수")
                st.plotly_chart(fig_rel, use_container_width=True)
            else:
                st.info("소스 신뢰도 데이터가 없습니다.")
        except Exception:
            st.info("소스 신뢰도 분석을 위한 데이터가 부족합니다.")

    # Event continuation analysis
    st.markdown("#### 이벤트 후 연속 패턴 (Event Continuation)")
    try:
        from src.analysis import historical_analysis  # noqa: F401 - may not exist yet
        st.info("분석 모듈 로드됨. 데이터가 쌓이면 자동으로 표시됩니다.")
    except ImportError:
        pass

    if not events_df.empty and "event_type" in events_df.columns and "return_1h" in events_df.columns:
        cont_df = events_df.copy()
        cont_df = cont_df[cont_df["event_type"].notna() & cont_df["return_1h"].notna()]
        if not cont_df.empty:
            avg_by_type = (
                cont_df.groupby("event_type")["return_1h"]
                .agg(["mean", "count"])
                .reset_index()
                .rename(columns={"mean": "평균 수익률", "count": "발생 횟수"})
            )
            fig_cont = px.bar(
                avg_by_type,
                x="event_type",
                y="평균 수익률",
                text="발생 횟수",
                title="이벤트 유형별 평균 1h 수익률",
                color="평균 수익률",
                color_continuous_scale="RdYlGn",
                color_continuous_midpoint=0,
            )
            fig_cont.update_layout(
                height=350,
                xaxis_title="이벤트 유형",
                yaxis_title="평균 1h 수익률",
                coloraxis_showscale=False,
            )
            fig_cont.update_traces(textposition="outside")
            st.plotly_chart(fig_cont, use_container_width=True)
        else:
            st.info("이벤트 연속 패턴을 분석할 데이터가 없습니다.")

# ── Tab 6: 상관관계 ───────────────────────────────────────────

with tab_corr:
    st.subheader("🔄 자산간 상관관계 분석")

    try:
        from src.analysis.correlation import generate_correlation_report
        conn = get_db()
        if conn:
            report = generate_correlation_report(conn)

            # 1. Correlation Heatmap
            corr_matrix = report["correlation_matrix"]
            if not corr_matrix.empty:
                st.markdown("### 수익률 상관관계 매트릭스")
                corr_display = corr_matrix.fillna(0)
                fig = px.imshow(corr_display, text_auto=".2f",
                               color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                               title="1시간 수익률 상관관계 (72시간)")
                fig.update_layout(height=500)
                st.plotly_chart(fig, use_container_width=True)
                st.caption("NaN = 거래시간이 겹치지 않는 자산 페어 (표시 목적으로 0으로 대체)")

            # 2. Lead-Lag relationships
            lead_lag = report["lead_lag"]
            if not lead_lag.empty:
                st.markdown("### 선행-후행 관계 (Lead-Lag)")
                st.caption("어떤 자산이 다른 자산보다 먼저 움직이는지 보여줍니다")
                # Show as bar chart: leader -> follower with correlation
                fig_ll = px.bar(lead_lag.head(15), x="correlation", y=lead_lag.head(15).apply(
                    lambda r: f"{r['leader']} → {r['follower']} ({r['lag_hours']}h)", axis=1),
                    orientation="h", color="correlation", color_continuous_scale="RdBu_r",
                    title="선행-후행 상관관계 (|corr| > 0.3)")
                fig_ll.update_layout(height=400, yaxis_title="")
                st.plotly_chart(fig_ll, use_container_width=True)
            else:
                st.info("선행-후행 관계 데이터가 부족합니다.")

            # 3. Event Spillover
            spillover = report["event_spillover"]
            if not spillover.empty:
                st.markdown("### 이벤트 전파 효과 (Spillover)")
                st.caption("한 자산에서 이벤트 발생 시 다른 자산의 반응")
                st.dataframe(spillover.sort_values("occurrence_count", ascending=False),
                            use_container_width=True, hide_index=True)
            else:
                st.info("이벤트 전파 데이터가 부족합니다.")

            # 4. Sector Correlation
            sector_corr = report["sector_correlation"]
            if not sector_corr.empty:
                sector_corr = sector_corr.dropna(subset=["avg_correlation"])
            if not sector_corr.empty:
                st.markdown("### 섹터간 상관관계")
                pivot = sector_corr.pivot_table(index="sector_a", columns="sector_b", values="avg_correlation", fill_value=0)
                fig_sec = px.imshow(pivot, text_auto=".2f", color_continuous_scale="Viridis",
                                   title="섹터별 평균 상관관계")
                fig_sec.update_layout(height=400)
                st.plotly_chart(fig_sec, use_container_width=True)
        else:
            st.info("DB 연결을 확인해주세요.")
    except ImportError:
        st.info("상관관계 분석 모듈이 아직 설치되지 않았습니다.")
    except Exception as e:
        st.error(f"상관관계 분석 중 오류: {e}")

# ── Tab 7: 청산/OI ───────────────────────────────────────────

with tab_deriv:
    st.subheader("💧 청산맵 & 미결제약정 (OI)")

    conn = get_db()
    if conn:
        try:
            oi_df = pd.read_sql_query(
                "SELECT * FROM open_interest ORDER BY timestamp DESC LIMIT 500", conn
            )
        except Exception:
            oi_df = pd.DataFrame()
        try:
            liq_df = pd.read_sql_query(
                "SELECT * FROM liquidations ORDER BY timestamp DESC LIMIT 500", conn
            )
        except Exception:
            liq_df = pd.DataFrame()

        if oi_df.empty and liq_df.empty:
            st.info("파생상품 데이터가 없습니다. 백그라운드 수집을 시작해주세요.")
        else:
            deriv_ticker = st.selectbox(
                "자산 선택", ["BTC-USDT", "ETH-USDT", "SOL-USDT"], key="deriv_ticker"
            )

            col1, col2 = st.columns(2)

            with col1:
                if not oi_df.empty:
                    ticker_oi = oi_df[oi_df["ticker"] == deriv_ticker].copy()
                    if not ticker_oi.empty:
                        ticker_oi["timestamp"] = pd.to_datetime(
                            ticker_oi["timestamp"], errors="coerce"
                        )
                        fig_oi = go.Figure()
                        fig_oi.add_trace(go.Scatter(
                            x=ticker_oi["timestamp"], y=ticker_oi["oi_value_usd"],
                            mode="lines", name="OI (USD)", fill="tozeroy",
                            line=dict(color="#4a9eff")
                        ))
                        fig_oi.update_layout(title=f"{deriv_ticker} 미결제약정", height=350)
                        st.plotly_chart(fig_oi, use_container_width=True)

                        latest = ticker_oi.iloc[0]
                        prev = ticker_oi.iloc[min(1, len(ticker_oi) - 1)]
                        prev_oi = prev.get("open_interest") or 0
                        oi_change = (
                            ((latest.get("open_interest") or 0) - prev_oi) / prev_oi * 100
                            if prev_oi else 0
                        )
                        m1, m2, m3 = st.columns(3)
                        with m1:
                            st.metric("현재 OI", f"${latest.get('oi_value_usd') or 0:,.0f}")
                        with m2:
                            st.metric("OI 변화", f"{oi_change:+.1f}%")
                        with m3:
                            st.metric("롱/숏 비율", f"{latest.get('long_short_ratio', 'N/A')}")

            with col2:
                if not oi_df.empty:
                    ticker_oi = oi_df[oi_df["ticker"] == deriv_ticker].copy()
                    if not ticker_oi.empty and "long_pct" in ticker_oi.columns:
                        ticker_oi["timestamp"] = pd.to_datetime(
                            ticker_oi["timestamp"], errors="coerce"
                        )
                        fig_ls = go.Figure()
                        fig_ls.add_trace(go.Bar(
                            x=ticker_oi["timestamp"], y=ticker_oi["long_pct"],
                            name="Long %", marker_color="#22c55e"
                        ))
                        fig_ls.add_trace(go.Bar(
                            x=ticker_oi["timestamp"], y=ticker_oi["short_pct"],
                            name="Short %", marker_color="#ef4444"
                        ))
                        fig_ls.update_layout(title="롱/숏 비율", barmode="stack", height=350)
                        st.plotly_chart(fig_ls, use_container_width=True)

            st.markdown("### 🔥 최근 청산 내역")
            if not liq_df.empty:
                ticker_liq = liq_df[liq_df["ticker"] == deriv_ticker].copy()
                if not ticker_liq.empty:
                    ticker_liq["timestamp"] = pd.to_datetime(
                        ticker_liq["timestamp"], errors="coerce"
                    )
                    fig_liq = px.scatter(
                        ticker_liq, x="timestamp", y="total_usd",
                        color="side", size="total_usd",
                        color_discrete_map={"SELL": "#ef4444", "BUY": "#22c55e"},
                        title="청산 타임라인 (크기 = USD 규모)",
                        labels={"total_usd": "청산 규모 (USD)", "side": "방향"},
                    )
                    fig_liq.update_layout(height=350)
                    st.plotly_chart(fig_liq, use_container_width=True)

                    s1, s2, s3 = st.columns(3)
                    with s1:
                        st.metric("총 청산 건수", f"{len(ticker_liq)}건")
                    with s2:
                        total_long = ticker_liq[ticker_liq["side"] == "BUY"]["total_usd"].sum()
                        st.metric("롱 청산 (숏→)", f"${total_long:,.0f}")
                    with s3:
                        total_short = ticker_liq[ticker_liq["side"] == "SELL"]["total_usd"].sum()
                        st.metric("숏 청산 (롱→)", f"${total_short:,.0f}")

                    st.dataframe(
                        ticker_liq[["timestamp", "side", "quantity", "price", "total_usd"]].head(20),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info(f"{deriv_ticker}의 최근 청산 데이터가 없습니다.")
            else:
                st.info("청산 데이터가 없습니다.")
    else:
        st.info("DB 연결을 확인해주세요.")

# ── Tab 8: 고래 추적 ─────────────────────────────────────────

with tab_whale:
    st.subheader("🐋 고래 추적 (Whale Tracking)")

    try:
        from src.prices.whale_tracker import get_whale_summary
        summary = get_whale_summary()
        provider = summary["provider"]

        if provider == "None":
            st.warning(
                "⚠️ API 키가 설정되지 않았습니다.\n\n"
                "**Arkham Intelligence** (추천)\n"
                "1. https://intel.arkm.com/api 에서 API 접근 신청\n"
                "2. `export ARKHAM_API_KEY=your_key`\n\n"
                "**Whale Alert** (무료 대안)\n"
                "1. https://whale-alert.io 에서 가입\n"
                "2. `export WHALE_ALERT_API_KEY=your_key`"
            )
        else:
            st.success(f"✅ {provider} API 연결됨")

        conn = get_db()
        if conn:
            whale_df = pd.read_sql_query(
                "SELECT * FROM whale_transfers ORDER BY timestamp DESC LIMIT 200", conn
            )

            if whale_df.empty:
                st.info("고래 이체 데이터가 없습니다. API 키를 설정하고 백그라운드 수집을 시작해주세요.")
            else:
                # KPIs
                w1, w2, w3 = st.columns(3)
                with w1:
                    st.metric("총 이체 건수", f"{len(whale_df)}건")
                with w2:
                    total_usd = whale_df["usd_value"].sum()
                    st.metric("총 이체 규모", f"${total_usd:,.0f}")
                with w3:
                    avg_usd = whale_df["usd_value"].mean()
                    st.metric("평균 이체 규모", f"${avg_usd:,.0f}")

                # Top transfers table
                st.markdown("### 최근 대규모 이체")
                display_cols = [c for c in ["timestamp", "from_entity", "to_entity", "usd_value", "token", "chain"] if c in whale_df.columns]
                st.dataframe(
                    whale_df[display_cols].head(30),
                    column_config={
                        "usd_value": st.column_config.NumberColumn("규모 (USD)", format="$%,.0f"),
                    },
                    use_container_width=True,
                    hide_index=True,
                )

                # Entity flow chart
                if "to_entity" in whale_df.columns:
                    st.markdown("### 거래소별 유입량")
                    exchange_flows = whale_df.groupby("to_entity")["usd_value"].sum().sort_values(ascending=False).head(10)
                    if not exchange_flows.empty:
                        fig_flow = px.bar(
                            x=exchange_flows.index, y=exchange_flows.values,
                            title="수신 엔티티별 총 유입량",
                            labels={"x": "엔티티", "y": "USD"},
                            color=exchange_flows.values,
                            color_continuous_scale="Blues",
                        )
                        fig_flow.update_layout(height=350, coloraxis_showscale=False)
                        st.plotly_chart(fig_flow, use_container_width=True)

                # Token breakdown
                if "token" in whale_df.columns:
                    st.markdown("### 토큰별 이체")
                    token_flows = whale_df.groupby("token")["usd_value"].sum().sort_values(ascending=False).head(8)
                    fig_token = px.pie(values=token_flows.values, names=token_flows.index, title="토큰별 이체 규모")
                    fig_token.update_layout(height=350)
                    st.plotly_chart(fig_token, use_container_width=True)

    except ImportError:
        st.info("고래 추적 모듈이 설치되지 않았습니다.")
    except Exception as e:
        st.error(f"고래 추적 오류: {e}")

# ── Tab 9: 뉴스 피드 ─────────────────────────────────────────

with tab_news:
    if news_df.empty:
        st.info("뉴스 데이터가 없습니다. 파이프라인을 실행해주세요.")
    else:
        st.subheader(f"수집된 뉴스 ({len(news_df):,}건)")

        # Source type badge colors
        source_type_colors = {
            "rss": "#3b82f6",
            "twitter": "#1d9bf0",
            "exchange_announcement": "#f59e0b",
        }

        def source_badge(stype: str) -> str:
            color = source_type_colors.get(stype, "#6b7280")
            label = {"rss": "RSS", "twitter": "X/Twitter", "exchange_announcement": "거래소"}.get(stype, stype)
            return f'<span style="background:{color};color:white;padding:1px 6px;border-radius:4px;font-size:11px">{label}</span>'

        # Sub-tabs: all / market breakdown / source type breakdown
        news_sub_tabs = ["전체"] + market_filter + ["거래소 공지", "X/Twitter"]
        market_tabs = st.tabs(news_sub_tabs)

        def render_news(df: pd.DataFrame, limit: int = 30) -> None:
            if df.empty:
                st.info("해당 뉴스가 없습니다.")
                return
            sorted_df = df.sort_values("published_at", ascending=False) if "published_at" in df.columns else df
            for _, row in sorted_df.head(limit).iterrows():
                source_type = row.get("source_type", "rss")
                card_class = {"twitter": "twitter", "exchange_announcement": "exchange", "community": "community"}.get(source_type, "")
                badge = {"rss": "📡 RSS", "twitter": "🐦 X", "exchange_announcement": "🏛️ 거래소", "community": "💬 커뮤니티"}.get(source_type, "📰")
                title = row.get("title", "N/A")
                url = row.get("url", "")
                title_display = f'<a href="{url}" target="_blank">{title}</a>' if url else title
                pub = row.get("published_at", row.get("timestamp", ""))
                source = row.get("source", "")
                st.markdown(
                    f'<div class="news-card {card_class}">'
                    f'<strong>{badge} {title_display}</strong><br>'
                    f'<small style="color: #888;">{source} · {pub}</small>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        with market_tabs[0]:
            render_news(news_df, limit=40)

        for i, mkt in enumerate(market_filter):
            with market_tabs[i + 1]:
                if "market" in news_df.columns:
                    render_news(news_df[news_df["market"] == mkt], limit=25)
                else:
                    st.info("시장 정보가 없습니다.")

        # Exchange announcements tab
        ea_idx = len(market_filter) + 1
        with market_tabs[ea_idx]:
            if "source_type" in news_df.columns:
                render_news(news_df[news_df["source_type"] == "exchange_announcement"], limit=25)
            else:
                st.info("거래소 공지 데이터가 없습니다.")

        # Twitter/X tab
        tw_idx = len(market_filter) + 2
        with market_tabs[tw_idx]:
            if "source_type" in news_df.columns:
                render_news(news_df[news_df["source_type"] == "twitter"], limit=25)
            else:
                st.info("X/Twitter 데이터가 없습니다.")

        # Source distribution chart
        if "source" in news_df.columns:
            st.subheader("뉴스 소스 분포")
            source_counts = news_df["source"].value_counts().head(20)
            fig_src = px.bar(
                x=source_counts.index,
                y=source_counts.values,
                title="소스별 뉴스 건수 (상위 20)",
                color=source_counts.values,
                color_continuous_scale="Viridis",
            )
            fig_src.update_layout(
                height=300,
                xaxis_title="",
                yaxis_title="건수",
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig_src, use_container_width=True)

        # Source type breakdown
        if "source_type" in news_df.columns:
            st.subheader("소스 유형 분포")
            st_counts = news_df["source_type"].value_counts()
            fig_st = px.pie(
                values=st_counts.values,
                names=st_counts.index,
                title="소스 유형별 비율",
                color=st_counts.index,
                color_discrete_map={
                    "rss": "#3b82f6",
                    "twitter": "#1d9bf0",
                    "exchange_announcement": "#f59e0b",
                },
            )
            fig_st.update_layout(height=300)
            st.plotly_chart(fig_st, use_container_width=True)

# ── Tab 10: 페이퍼 트레이딩 ──────────────────────────────────

with tab_paper:
    try:
        from src.db.queries import get_open_trades, get_trade_history, get_trade_stats
        conn = get_db()
        if conn is None:
            st.info("페이퍼 트레이딩 데이터가 없습니다")
        else:
            stats = get_trade_stats(conn)
            open_trades_df = get_open_trades(conn)
            history_df = get_trade_history(conn, limit=100)

            if stats["total"] == 0 and open_trades_df.empty:
                st.info("페이퍼 트레이딩 데이터가 없습니다")
            else:
                # KPI metrics
                st.subheader("트레이딩 성과")
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("총 거래", stats.get("total", 0))
                c2.metric("승률", f"{stats.get('win_rate', 0):.1f}%")
                c3.metric("평균 PnL", f"{stats.get('avg_pnl', 0):.2f}%")
                c4.metric("누적 PnL", f"{stats.get('total_pnl', 0):.2f}%")
                c5.metric("최고/최저", f"{stats.get('best', 0):.1f}% / {stats.get('worst', 0):.1f}%")

                # Open positions
                st.subheader(f"오픈 포지션 ({len(open_trades_df)}개)")
                if not open_trades_df.empty:
                    display_cols = [c for c in ["id", "ticker", "direction", "entry_price", "entry_time", "signal_type", "status"] if c in open_trades_df.columns]
                    st.dataframe(open_trades_df[display_cols], use_container_width=True)
                else:
                    st.info("오픈 포지션 없음")

                # Closed trade history
                if not history_df.empty:
                    st.subheader("거래 내역")
                    hist_display = [c for c in ["id", "ticker", "direction", "entry_price", "exit_price", "pnl_pct", "status", "signal_type", "entry_time", "exit_time"] if c in history_df.columns]
                    st.dataframe(history_df[hist_display], use_container_width=True)

                    # PnL curve
                    closed_df = history_df[history_df["status"] == "closed"].copy()
                    if not closed_df.empty and "pnl_pct" in closed_df.columns and "exit_time" in closed_df.columns:
                        closed_df = closed_df.dropna(subset=["pnl_pct", "exit_time"])
                        closed_df = closed_df.sort_values("exit_time")
                        closed_df["cumulative_pnl"] = closed_df["pnl_pct"].cumsum()
                        fig_pnl = px.line(
                            closed_df,
                            x="exit_time",
                            y="cumulative_pnl",
                            title="누적 PnL 곡선 (%)",
                            markers=True,
                        )
                        fig_pnl.update_layout(height=350, xaxis_title="", yaxis_title="누적 PnL (%)")
                        st.plotly_chart(fig_pnl, use_container_width=True)

                    # Signal type breakdown
                    if "signal_type" in history_df.columns:
                        st.subheader("시그널 유형 분포")
                        sig_counts = history_df["signal_type"].value_counts()
                        fig_sig = px.pie(
                            values=sig_counts.values,
                            names=sig_counts.index,
                            title="시그널 유형별 거래 비율",
                        )
                        fig_sig.update_layout(height=300)
                        st.plotly_chart(fig_sig, use_container_width=True)

    except Exception as e:
        st.error(f"페이퍼 트레이딩 오류: {e}")
