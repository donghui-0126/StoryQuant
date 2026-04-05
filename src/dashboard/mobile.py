"""
StoryQuant Mobile Dashboard
Lightweight FastAPI + HTML mobile-optimized web app.

Usage:
    python -m src.dashboard.mobile          # http://localhost:8502
    python -m src.dashboard.mobile --port 9000
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = str(ROOT / "data" / "storyquant.db")

app = FastAPI(title="StoryQuant Mobile")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── API endpoints ──────────────────────────────────────────

@app.get("/api/overview")
def api_overview():
    conn = _conn()
    now = datetime.now(timezone.utc)
    h24 = (now - timedelta(hours=24)).isoformat()
    h1 = (now - timedelta(hours=1)).isoformat()

    articles = conn.execute("SELECT COUNT(*) FROM articles WHERE published_at >= ?", [h24]).fetchone()[0]
    events_24h = conn.execute("SELECT COUNT(*) FROM events WHERE timestamp >= ? AND event_type IS NOT NULL", [h24]).fetchone()[0]
    events_1h = conn.execute("SELECT COUNT(*) FROM events WHERE timestamp >= ? AND event_type IS NOT NULL", [h1]).fetchone()[0]

    # Recent events
    events = conn.execute("""
        SELECT e.ticker, e.event_type, e.return_1h, e.severity, e.timestamp,
               ar.title as cause
        FROM events e
        LEFT JOIN attributions a ON a.event_id = e.id AND a.rank = 1
        LEFT JOIN articles ar ON a.article_id = ar.id
        WHERE e.event_type IS NOT NULL AND e.timestamp >= ?
        ORDER BY ABS(e.return_1h) DESC LIMIT 10
    """, [h24]).fetchall()

    # Hot topics
    topics = conn.execute("""
        SELECT topic_label, frequency, momentum_score, novelty_score
        FROM topics ORDER BY created_at DESC LIMIT 10
    """).fetchall()

    # Latest prices per ticker
    prices = conn.execute("""
        SELECT ticker, close, timestamp FROM prices
        WHERE (ticker, timestamp) IN (
            SELECT ticker, MAX(timestamp) FROM prices GROUP BY ticker
        )
    """).fetchall()

    # Paper trading PnL
    pnl_row = conn.execute("""
        SELECT
            COUNT(*) as trades,
            SUM(CASE WHEN direction='long' THEN (exit_price - entry_price)/entry_price*100
                     ELSE (entry_price - exit_price)/entry_price*100 END) as total_pnl,
            SUM(CASE WHEN
                (direction='long' AND exit_price > entry_price) OR
                (direction='short' AND exit_price < entry_price)
                THEN 1 ELSE 0 END) * 100.0 / MAX(COUNT(*), 1) as win_rate
        FROM trades WHERE status = 'closed'
    """).fetchone()

    conn.close()

    return {
        "kpi": {
            "articles_24h": articles,
            "events_24h": events_24h,
            "events_1h": events_1h,
            "trades": pnl_row[0] or 0,
            "total_pnl": round(pnl_row[1] or 0, 2),
            "win_rate": round(pnl_row[2] or 0, 0),
        },
        "events": [dict(r) for r in events],
        "topics": [dict(r) for r in topics],
        "prices": [dict(r) for r in prices],
    }


@app.get("/api/signals")
def api_signals():
    conn = _conn()
    h48 = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()

    events = conn.execute("""
        SELECT e.ticker, e.event_type, e.return_1h, e.severity, e.timestamp,
               ar.title as cause, a.total_score as confidence
        FROM events e
        LEFT JOIN attributions a ON a.event_id = e.id AND a.rank = 1
        LEFT JOIN articles ar ON a.article_id = ar.id
        WHERE e.event_type IS NOT NULL AND e.severity IN ('high','medium')
            AND e.timestamp >= ?
        ORDER BY e.timestamp DESC LIMIT 30
    """, [h48]).fetchall()

    # Cross-market
    cross = conn.execute("""
        SELECT e1.ticker as leader, e2.ticker as follower,
               e1.return_1h as leader_return, e2.return_1h as follower_return,
               ROUND((julianday(e2.timestamp) - julianday(e1.timestamp)) * 24, 1) as lag_hours
        FROM events e1
        JOIN events e2 ON e1.ticker != e2.ticker
            AND e2.timestamp > e1.timestamp
            AND e2.timestamp <= datetime(e1.timestamp, '+24 hours')
            AND ABS(e1.return_1h) > 0.02 AND ABS(e2.return_1h) > 0.01
        WHERE e1.timestamp >= ?
        ORDER BY ABS(e2.return_1h) DESC LIMIT 10
    """, [h48]).fetchall()

    conn.close()
    return {
        "events": [dict(r) for r in events],
        "cross_market": [dict(r) for r in cross],
    }


@app.get("/api/news")
def api_news():
    conn = _conn()
    h12 = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()

    articles = conn.execute("""
        SELECT title, source, market, published_at, url, source_type
        FROM articles WHERE published_at >= ?
        ORDER BY published_at DESC LIMIT 30
    """, [h12]).fetchall()

    conn.close()
    return {"articles": [dict(r) for r in articles]}


# ── Mobile HTML ────────────────────────────────────────────

MOBILE_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0d0f14">
<title>StoryQuant</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
:root {
  --bg: #0d0f14; --surface: #141720; --border: #1f2535;
  --text: #e8ecf4; --dim: #8892a4; --muted: #5a6480;
  --accent: #3b82f6; --green: #22c55e; --red: #f87171;
  --gold: #fbbf24;
}
body {
  font-family: -apple-system, 'Pretendard', sans-serif;
  background: var(--bg); color: var(--text);
  -webkit-font-smoothing: antialiased;
  padding-bottom: 72px;
}

/* Header */
.header {
  position: sticky; top: 0; z-index: 100;
  background: var(--bg); border-bottom: 1px solid var(--border);
  padding: 12px 16px; display: flex; justify-content: space-between; align-items: center;
}
.header h1 { font-size: 18px; font-weight: 700; color: var(--accent); }
.header .time { font-size: 11px; color: var(--muted); font-family: 'SF Mono', monospace; }

/* Tab bar */
.tabs {
  position: fixed; bottom: 0; left: 0; right: 0; z-index: 100;
  background: var(--surface); border-top: 1px solid var(--border);
  display: flex; padding: 6px 0 env(safe-area-inset-bottom);
}
.tab {
  flex: 1; text-align: center; padding: 8px 4px; font-size: 10px;
  color: var(--muted); cursor: pointer; transition: color 0.2s;
}
.tab.active { color: var(--accent); }
.tab .icon { font-size: 20px; display: block; margin-bottom: 2px; }

/* KPI strip */
.kpi-strip {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
  padding: 12px 16px;
}
.kpi {
  background: var(--surface); border-radius: 10px; padding: 12px;
  border: 1px solid var(--border);
}
.kpi .value { font-size: 22px; font-weight: 700; font-family: 'SF Mono', monospace; }
.kpi .label { font-size: 10px; color: var(--muted); margin-top: 2px; text-transform: uppercase; letter-spacing: 0.5px; }
.kpi.green .value { color: var(--green); }
.kpi.red .value { color: var(--red); }

/* Section */
.section { padding: 0 16px; margin-bottom: 16px; }
.section-title {
  font-size: 13px; font-weight: 600; color: var(--dim);
  text-transform: uppercase; letter-spacing: 1px;
  margin-bottom: 8px; padding-top: 12px;
  border-top: 1px solid var(--border);
}

/* Event card */
.event-card {
  background: var(--surface); border-radius: 10px; padding: 12px;
  margin-bottom: 8px; border: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: flex-start;
}
.event-left { flex: 1; min-width: 0; }
.event-ticker { font-size: 15px; font-weight: 700; }
.event-type { font-size: 11px; color: var(--dim); margin-top: 2px; }
.event-cause {
  font-size: 12px; color: var(--dim); margin-top: 6px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.event-time { font-size: 10px; color: var(--muted); margin-top: 4px; font-family: monospace; }
.event-return {
  font-size: 20px; font-weight: 700; font-family: 'SF Mono', monospace;
  white-space: nowrap; margin-left: 12px;
}
.event-severity {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 6px; vertical-align: middle;
}
.sev-high { background: var(--red); }
.sev-medium { background: var(--gold); }
.sev-low { background: var(--green); }

/* Topic bar */
.topic-item {
  display: flex; align-items: center; margin-bottom: 6px; gap: 8px;
}
.topic-rank {
  width: 20px; height: 20px; border-radius: 50%; background: var(--border);
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700; flex-shrink: 0;
}
.topic-rank.r1 { background: var(--gold); color: #000; }
.topic-rank.r2 { background: #94a3b8; color: #000; }
.topic-rank.r3 { background: #b45309; color: #fff; }
.topic-label { font-size: 13px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.topic-bar-wrap { width: 80px; height: 6px; background: var(--border); border-radius: 3px; flex-shrink: 0; }
.topic-bar { height: 100%; border-radius: 3px; background: var(--accent); }
.topic-score { font-size: 10px; color: var(--muted); width: 32px; text-align: right; flex-shrink: 0; font-family: monospace; }

/* News card */
.news-card {
  background: var(--surface); border-radius: 10px; padding: 12px;
  margin-bottom: 8px; border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
}
.news-card.crypto { border-left-color: var(--gold); }
.news-card.us { border-left-color: var(--green); }
.news-card.kr { border-left-color: var(--red); }
.news-title { font-size: 14px; font-weight: 500; line-height: 1.4; }
.news-meta { font-size: 11px; color: var(--muted); margin-top: 4px; display: flex; justify-content: space-between; }

/* Price row */
.price-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 0; border-bottom: 1px solid var(--border);
}
.price-ticker { font-size: 14px; font-weight: 600; }
.price-value { font-size: 14px; font-family: 'SF Mono', monospace; }

/* Pane visibility */
.pane { display: none; }
.pane.active { display: block; }

/* PnL card */
.pnl-card {
  background: var(--surface); border-radius: 12px; padding: 20px;
  text-align: center; border: 1px solid var(--border); margin: 0 16px 12px;
}
.pnl-value { font-size: 36px; font-weight: 700; font-family: 'SF Mono', monospace; }
.pnl-label { font-size: 12px; color: var(--muted); margin-top: 4px; }

/* Cross market */
.cross-card {
  background: var(--surface); border-radius: 10px; padding: 12px;
  margin-bottom: 8px; border: 1px solid var(--border);
  display: flex; align-items: center; gap: 8px;
}
.cross-arrow { font-size: 16px; color: var(--accent); }

/* Pull to refresh indicator */
.refresh-hint { text-align: center; padding: 8px; font-size: 11px; color: var(--muted); }

/* Loading */
.loading { text-align: center; padding: 40px; color: var(--muted); }
</style>
</head>
<body>

<div class="header">
  <h1>StoryQuant</h1>
  <span class="time" id="update-time">--:--</span>
</div>

<div id="pane-overview" class="pane active"></div>
<div id="pane-signals" class="pane"></div>
<div id="pane-news" class="pane"></div>
<div id="pane-perf" class="pane"></div>

<div class="tabs">
  <div class="tab active" data-pane="overview"><span class="icon">📊</span>Overview</div>
  <div class="tab" data-pane="signals"><span class="icon">⚡</span>Signals</div>
  <div class="tab" data-pane="news"><span class="icon">📰</span>News</div>
  <div class="tab" data-pane="perf"><span class="icon">💰</span>Performance</div>
</div>

<script>
// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.pane').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('pane-' + tab.dataset.pane).classList.add('active');
  });
});

function fmt(v) { return v >= 0 ? `+${(v*100).toFixed(1)}%` : `${(v*100).toFixed(1)}%`; }
function fmtPct(v) { return v >= 0 ? `+${v.toFixed(1)}%` : `${v.toFixed(1)}%`; }
function timeAgo(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  const now = new Date();
  const diff = (now - d) / 60000;
  if (diff < 60) return Math.floor(diff) + 'm ago';
  if (diff < 1440) return Math.floor(diff/60) + 'h ago';
  return Math.floor(diff/1440) + 'd ago';
}
function sevClass(s) { return s === 'high' ? 'sev-high' : s === 'medium' ? 'sev-medium' : 'sev-low'; }
function retColor(v) { return v >= 0 ? 'var(--green)' : 'var(--red)'; }

async function loadOverview() {
  const el = document.getElementById('pane-overview');
  try {
    const r = await fetch('/api/overview');
    const d = await r.json();
    const k = d.kpi;

    let pnlClass = k.total_pnl >= 0 ? 'green' : 'red';
    let html = `
      <div class="kpi-strip">
        <div class="kpi"><div class="value">${k.articles_24h}</div><div class="label">News 24h</div></div>
        <div class="kpi"><div class="value">${k.events_24h}</div><div class="label">Events 24h</div></div>
        <div class="kpi ${pnlClass}"><div class="value">${fmtPct(k.total_pnl)}</div><div class="label">PnL</div></div>
      </div>
    `;

    // Events
    if (d.events.length) {
      html += `<div class="section"><div class="section-title">Recent Events</div>`;
      d.events.slice(0, 8).forEach(e => {
        const ret = e.return_1h || 0;
        html += `
          <div class="event-card">
            <div class="event-left">
              <div class="event-ticker"><span class="event-severity ${sevClass(e.severity)}"></span>${e.ticker}</div>
              <div class="event-type">${e.event_type}${e.severity === 'high' ? ' !!!' : ''}</div>
              ${e.cause ? `<div class="event-cause">${e.cause}</div>` : ''}
              <div class="event-time">${timeAgo(e.timestamp)}</div>
            </div>
            <div class="event-return" style="color:${retColor(ret)}">${fmt(ret)}</div>
          </div>`;
      });
      html += `</div>`;
    }

    // Topics
    if (d.topics.length) {
      html += `<div class="section"><div class="section-title">Hot Topics</div>`;
      d.topics.slice(0, 7).forEach((t, i) => {
        const m = (t.momentum_score || 0);
        const rc = i === 0 ? 'r1' : i === 1 ? 'r2' : i === 2 ? 'r3' : '';
        html += `
          <div class="topic-item">
            <div class="topic-rank ${rc}">${i+1}</div>
            <div class="topic-label">${t.topic_label}</div>
            <div class="topic-bar-wrap"><div class="topic-bar" style="width:${m*100}%"></div></div>
            <div class="topic-score">${(m*100).toFixed(0)}%</div>
          </div>`;
      });
      html += `</div>`;
    }

    // Prices
    if (d.prices.length) {
      html += `<div class="section"><div class="section-title">Latest Prices</div>`;
      d.prices.forEach(p => {
        html += `
          <div class="price-row">
            <span class="price-ticker">${p.ticker}</span>
            <span class="price-value">$${Number(p.close).toLocaleString(undefined, {maximumFractionDigits: 2})}</span>
          </div>`;
      });
      html += `</div>`;
    }

    html += `<div class="refresh-hint">Auto-refresh every 30s</div>`;
    el.innerHTML = html;
  } catch(e) { el.innerHTML = '<div class="loading">Failed to load</div>'; }
}

async function loadSignals() {
  const el = document.getElementById('pane-signals');
  try {
    const r = await fetch('/api/signals');
    const d = await r.json();
    let html = '';

    if (d.events.length) {
      html += `<div class="section"><div class="section-title">Price Signals (48h)</div>`;
      d.events.forEach(e => {
        const ret = e.return_1h || 0;
        const conf = e.confidence ? `${(e.confidence*100).toFixed(0)}%` : '';
        html += `
          <div class="event-card">
            <div class="event-left">
              <div class="event-ticker"><span class="event-severity ${sevClass(e.severity)}"></span>${e.ticker}</div>
              <div class="event-type">${e.event_type} ${conf ? '| conf ' + conf : ''}</div>
              ${e.cause ? `<div class="event-cause">${e.cause}</div>` : ''}
              <div class="event-time">${timeAgo(e.timestamp)}</div>
            </div>
            <div class="event-return" style="color:${retColor(ret)}">${fmt(ret)}</div>
          </div>`;
      });
      html += `</div>`;
    } else {
      html += `<div class="section"><div class="section-title">Price Signals</div><div class="loading">No signals in last 48h</div></div>`;
    }

    if (d.cross_market.length) {
      html += `<div class="section"><div class="section-title">Cross-Market</div>`;
      d.cross_market.forEach(c => {
        html += `
          <div class="cross-card">
            <span style="font-weight:600">${c.leader}</span>
            <span style="color:${retColor(c.leader_return)};font-family:monospace;font-size:12px">${fmt(c.leader_return)}</span>
            <span class="cross-arrow">→</span>
            <span style="font-weight:600">${c.follower}</span>
            <span style="color:${retColor(c.follower_return)};font-family:monospace;font-size:12px">${fmt(c.follower_return)}</span>
            <span style="font-size:10px;color:var(--muted);margin-left:auto">${c.lag_hours}h</span>
          </div>`;
      });
      html += `</div>`;
    }

    el.innerHTML = html || '<div class="loading">No data</div>';
  } catch(e) { el.innerHTML = '<div class="loading">Failed to load</div>'; }
}

async function loadNews() {
  const el = document.getElementById('pane-news');
  try {
    const r = await fetch('/api/news');
    const d = await r.json();
    let html = `<div class="section"><div class="section-title">Latest News (12h)</div>`;

    if (d.articles.length) {
      d.articles.forEach(a => {
        const mkt = a.market || '';
        html += `
          <div class="news-card ${mkt}">
            <div class="news-title">${a.title}</div>
            <div class="news-meta">
              <span>${a.source}</span>
              <span>${timeAgo(a.published_at)}</span>
            </div>
          </div>`;
      });
    } else {
      html += `<div class="loading">No recent news</div>`;
    }

    html += `</div>`;
    el.innerHTML = html;
  } catch(e) { el.innerHTML = '<div class="loading">Failed to load</div>'; }
}

async function loadPerf() {
  const el = document.getElementById('pane-perf');
  try {
    const r = await fetch('/api/overview');
    const d = await r.json();
    const k = d.kpi;
    const pnlColor = k.total_pnl >= 0 ? 'var(--green)' : 'var(--red)';

    el.innerHTML = `
      <div class="pnl-card">
        <div class="pnl-value" style="color:${pnlColor}">${fmtPct(k.total_pnl)}</div>
        <div class="pnl-label">Total Paper Trading PnL</div>
      </div>
      <div class="kpi-strip">
        <div class="kpi"><div class="value">${k.trades}</div><div class="label">Trades</div></div>
        <div class="kpi"><div class="value">${k.win_rate}%</div><div class="label">Win Rate</div></div>
        <div class="kpi"><div class="value">${k.events_24h}</div><div class="label">Signals 24h</div></div>
      </div>
      <div class="section">
        <div class="section-title">Recent Events as Signals</div>
        ${d.events.slice(0, 5).map(e => `
          <div class="event-card">
            <div class="event-left">
              <div class="event-ticker"><span class="event-severity ${sevClass(e.severity)}"></span>${e.ticker}</div>
              <div class="event-type">${e.event_type}</div>
              <div class="event-time">${timeAgo(e.timestamp)}</div>
            </div>
            <div class="event-return" style="color:${retColor(e.return_1h||0)}">${fmt(e.return_1h||0)}</div>
          </div>
        `).join('')}
      </div>
    `;
  } catch(e) { el.innerHTML = '<div class="loading">Failed to load</div>'; }
}

// Initial load
document.getElementById('update-time').textContent = new Date().toLocaleTimeString('en', {hour:'2-digit',minute:'2-digit'});
loadOverview();

// Tab-aware lazy loading
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const p = tab.dataset.pane;
    if (p === 'overview') loadOverview();
    else if (p === 'signals') loadSignals();
    else if (p === 'news') loadNews();
    else if (p === 'perf') loadPerf();
    document.getElementById('update-time').textContent = new Date().toLocaleTimeString('en', {hour:'2-digit',minute:'2-digit'});
  });
});

// Auto refresh overview every 30s
setInterval(() => {
  const active = document.querySelector('.tab.active');
  if (active && active.dataset.pane === 'overview') {
    loadOverview();
    document.getElementById('update-time').textContent = new Date().toLocaleTimeString('en', {hour:'2-digit',minute:'2-digit'});
  }
}, 30000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def mobile_home():
    return MOBILE_HTML


if __name__ == "__main__":
    port = 8502
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        port = int(sys.argv[idx + 1])
    print(f"StoryQuant Mobile: http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
