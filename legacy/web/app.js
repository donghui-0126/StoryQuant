/**
 * StoryQuant v2 — Static Dashboard
 * Connects to amure-db graph API for all knowledge data.
 */

// ── State ──
let API_URL = localStorage.getItem('amure_api_url') || 'http://localhost:8081';
let allNodes = [];
let allEdges = [];
let refreshTimer = null;

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setupSettings();
  setupSearch();
  setupFilters();
  setupMarketButtons();
  updateClock();
  setInterval(updateClock, 1000);
  refresh();
  refreshTimer = setInterval(refresh, 30000);
});

// ── Tabs ──
function setupTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(`panel-${tab.dataset.tab}`).classList.add('active');
    });
  });
}

// ── Settings ──
function setupSettings() {
  const toggle = document.getElementById('settings-toggle');
  const overlay = document.getElementById('settings-overlay');
  const save = document.getElementById('settings-save');
  const cancel = document.getElementById('settings-cancel');
  const input = document.getElementById('api-url-input');

  input.value = API_URL;
  toggle.addEventListener('click', () => overlay.classList.remove('hidden'));
  cancel.addEventListener('click', () => overlay.classList.add('hidden'));
  save.addEventListener('click', () => {
    API_URL = input.value.replace(/\/+$/, '');
    localStorage.setItem('amure_api_url', API_URL);
    overlay.classList.add('hidden');
    refresh();
  });
}

// ── Clock ──
function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent = now.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

// ── API helpers ──
async function api(path) {
  const resp = await fetch(`${API_URL}${path}`, { signal: AbortSignal.timeout(8000) });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

function setStatus(online) {
  const badge = document.getElementById('status-badge');
  badge.textContent = online ? 'ONLINE' : 'OFFLINE';
  badge.className = `status-badge ${online ? 'online' : 'offline'}`;
}

// ── Main refresh ──
async function refresh() {
  try {
    const [allData, summary] = await Promise.all([
      api('/api/graph/all'),
      api('/api/graph/summary'),
    ]);
    setStatus(true);

    allNodes = allData.nodes || [];
    allEdges = allData.edges || [];

    renderKPI(summary);
    renderNarratives();
    renderEvents();
    renderNews();
    renderGraphSummary(summary);
    loadContradictions();
    loadHealth();
  } catch (e) {
    setStatus(false);
    console.warn('Refresh failed:', e.message);
  }
}

// ── KPI ──
function renderKPI(summary) {
  const kinds = summary.by_kind || summary.nodes_by_kind || {};
  const claims = allNodes.filter(n => n.kind === 'Claim');
  const active = claims.filter(c => ['Active', 'Accepted'].includes(c.status));
  const facts = allNodes.filter(n => n.kind === 'Fact');
  const evidence = allNodes.filter(n => n.kind === 'Evidence');

  document.getElementById('kpi-narratives').textContent = active.length;
  document.getElementById('kpi-events').textContent = facts.length;
  document.getElementById('kpi-evidence').textContent = evidence.length;
  document.getElementById('kpi-nodes').textContent = summary.total_nodes || summary.node_count || allNodes.length;
  document.getElementById('kpi-edges').textContent = summary.total_edges || summary.edge_count || allEdges.length;
}

// ── Narratives ──
function renderNarratives() {
  const grid = document.getElementById('narratives-grid');
  const claims = allNodes.filter(n => n.kind === 'Claim');

  // Count support edges per claim
  const supportCount = {};
  allEdges.forEach(e => {
    if (e.kind === 'Support') {
      supportCount[e.target] = (supportCount[e.target] || 0) + 1;
    }
  });

  claims.sort((a, b) => (supportCount[b.id] || 0) - (supportCount[a.id] || 0));

  if (!claims.length) {
    grid.innerHTML = '<div class="empty-state">No narratives detected — run the pipeline to create Claim nodes</div>';
    return;
  }

  const icons = { emerging: '🌱', building: '📈', peaking: '🔥', fading: '📉' };
  const colors = { emerging: '#3b82f6', building: '#22c55e', peaking: '#f59e0b', fading: '#6b7280' };

  grid.innerHTML = claims.map(c => {
    const meta = c.metadata || {};
    const lc = meta.lifecycle || 'emerging';
    const evCount = supportCount[c.id] || 0;
    const keywords = (c.keywords || []).slice(0, 5);
    const strength = Math.min(100, evCount * 15);

    return `
      <div class="narrative-card ${lc}">
        <div class="narrative-header">
          <span class="narrative-title">${icons[lc] || ''} ${esc(c.statement || '').slice(0, 80)}</span>
          <span class="narrative-lifecycle" style="color:${colors[lc] || '#6b7280'}">${lc.toUpperCase()}</span>
        </div>
        <div class="narrative-meta">
          Evidence: ${evCount} | Status: ${c.status || 'Draft'}${meta.market ? ` | ${meta.market}` : ''}
        </div>
        <div class="strength-bar-bg">
          <div class="strength-bar-fill" style="width:${strength}%;background:${colors[lc] || '#6b7280'}"></div>
        </div>
        <div class="narrative-keywords">
          ${keywords.map(k => `<span class="keyword-tag">${esc(k)}</span>`).join('')}
        </div>
      </div>`;
  }).join('');
}

// ── Events ──
function renderEvents() {
  const facts = allNodes.filter(n => n.kind === 'Fact');
  facts.sort((a, b) => {
    const ta = (a.metadata || {}).timestamp || '';
    const tb = (b.metadata || {}).timestamp || '';
    return tb.localeCompare(ta);
  });

  // Support edge counts
  const supportCount = {};
  allEdges.forEach(e => {
    if (e.kind === 'Support') supportCount[e.target] = (supportCount[e.target] || 0) + 1;
  });

  const tbody = document.getElementById('events-tbody');
  const select = document.getElementById('event-select');

  // Populate event select for causal explanation
  select.innerHTML = '<option value="">Select an event...</option>' +
    facts.slice(0, 30).map(f => {
      const m = f.metadata || {};
      return `<option value="${f.id}">${m.ticker || '?'} ${m.event_type || ''} (${timeAgo(m.timestamp)})</option>`;
    }).join('');

  select.onchange = () => { if (select.value) loadCausalExplanation(select.value); };

  applyEventFilters(facts, supportCount);
}

function applyEventFilters(facts, supportCount) {
  const sevFilter = document.getElementById('filter-severity').value;
  const typeFilter = document.getElementById('filter-event-type').value;
  const mktFilter = document.getElementById('filter-market').value;

  let filtered = facts;
  if (sevFilter) filtered = filtered.filter(f => (f.metadata || {}).severity === sevFilter);
  if (typeFilter) filtered = filtered.filter(f => (f.metadata || {}).event_type === typeFilter);
  if (mktFilter) filtered = filtered.filter(f => (f.metadata || {}).market === mktFilter);

  const tbody = document.getElementById('events-tbody');

  if (!filtered.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state" style="border:none;">No events match filters</td></tr>';
    return;
  }

  tbody.innerHTML = filtered.slice(0, 50).map(f => {
    const m = f.metadata || {};
    const ret = parseFloat(m.return_1h || 0) * 100;
    const retClass = ret >= 0 ? 'return-positive' : 'return-negative';
    const retStr = (ret >= 0 ? '+' : '') + ret.toFixed(2) + '%';
    const sev = m.severity || 'low';
    const attrCount = supportCount[f.id] || 0;

    return `<tr>
      <td>${timeAgo(m.timestamp)}</td>
      <td style="color:var(--text-primary);font-weight:500;">${esc(m.ticker || '')}</td>
      <td>${esc(m.event_type || '')}</td>
      <td class="${retClass}">${retStr}</td>
      <td><span class="severity-badge severity-${sev}">${sev}</span></td>
      <td>${attrCount}</td>
    </tr>`;
  }).join('');
}

function setupFilters() {
  ['filter-severity', 'filter-event-type', 'filter-market'].forEach(id => {
    document.getElementById(id).addEventListener('change', () => {
      const facts = allNodes.filter(n => n.kind === 'Fact');
      const supportCount = {};
      allEdges.forEach(e => { if (e.kind === 'Support') supportCount[e.target] = (supportCount[e.target] || 0) + 1; });
      applyEventFilters(facts, supportCount);
    });
  });
}

// ── Causal Explanation ──
async function loadCausalExplanation(factId) {
  const container = document.getElementById('causal-result');
  container.innerHTML = '<div class="empty-state">Loading...</div>';

  try {
    const [walkData, chainsData] = await Promise.all([
      api(`/api/graph/walk/${factId}?hops=2`),
      api(`/api/graph/causal-chains/${factId}`),
    ]);

    const nodes = walkData.nodes || walkData || [];
    const chains = chainsData.chains || chainsData || [];

    const evidence = nodes.filter(n => n.kind === 'Evidence');
    const reasons = nodes.filter(n => n.kind === 'Reason');
    const claims = nodes.filter(n => n.kind === 'Claim');

    let html = '';

    if (evidence.length) {
      html += `<div class="causal-section"><div class="causal-label">Supporting Evidence (${evidence.length})</div>`;
      evidence.slice(0, 5).forEach(e => {
        html += `<div class="causal-item">${esc((e.statement || '').slice(0, 120))}</div>`;
      });
      html += '</div>';
    }

    if (reasons.length) {
      html += '<div class="causal-section"><div class="causal-label">Synthesized Reasons</div>';
      reasons.slice(0, 3).forEach(r => {
        html += `<div class="causal-item" style="border-left-color:var(--accent-green)">${esc((r.statement || '').slice(0, 150))}</div>`;
      });
      html += '</div>';
    }

    if (claims.length) {
      html += '<div class="causal-section"><div class="causal-label">Related Narratives</div>';
      claims.slice(0, 3).forEach(c => {
        html += `<div class="causal-item" style="border-left-color:var(--accent-yellow)">${esc((c.statement || '').slice(0, 100))} [${c.status || ''}]</div>`;
      });
      html += '</div>';
    }

    if (chains.length) {
      html += `<div class="causal-section"><div class="causal-label">Causal Chains: ${chains.length} paths</div></div>`;
    }

    container.innerHTML = html || '<div class="empty-state">No causal data found for this event</div>';
  } catch (e) {
    container.innerHTML = `<div class="empty-state">Failed to load: ${esc(e.message)}</div>`;
  }
}

// ── News Feed ──
let currentMarket = '';

function renderNews(market) {
  if (market !== undefined) currentMarket = market;
  const feed = document.getElementById('news-feed');
  let evidence = allNodes.filter(n => n.kind === 'Evidence');

  if (currentMarket) {
    evidence = evidence.filter(n => (n.metadata || {}).market === currentMarket);
  }

  evidence.sort((a, b) => {
    const ta = (a.metadata || {}).published_at || '';
    const tb = (b.metadata || {}).published_at || '';
    return tb.localeCompare(ta);
  });

  if (!evidence.length) {
    feed.innerHTML = '<div class="empty-state">No news articles available</div>';
    return;
  }

  feed.innerHTML = evidence.slice(0, 50).map(e => {
    const m = e.metadata || {};
    const srcType = m.source_type || '';
    const srcClass = getSourceClass(srcType);
    const sentiment = m.sentiment || '';
    const score = parseFloat(m.sentiment_score || 0);
    let sentHtml = '';
    if (sentiment === 'bullish') sentHtml = `<span class="news-card-sentiment sentiment-bullish">▲ +${score.toFixed(2)}</span>`;
    else if (sentiment === 'bearish') sentHtml = `<span class="news-card-sentiment sentiment-bearish">▼ ${score.toFixed(2)}</span>`;

    return `
      <div class="news-card ${srcClass}">
        <div class="news-card-header">
          <span class="news-card-time">${timeAgo(m.published_at)}</span>
          ${sentHtml}
        </div>
        <div class="news-card-title">${esc(e.statement || '')}</div>
        <div class="news-card-source">${esc(m.source || '')} · ${esc(srcType)}</div>
      </div>`;
  }).join('');
}

function setupMarketButtons() {
  document.querySelectorAll('.market-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.market-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderNews(btn.dataset.market);
    });
  });
}

// ── Knowledge Graph tab ──
function renderGraphSummary(summary) {
  const grid = document.getElementById('graph-summary-grid');
  const kinds = summary.by_kind || summary.nodes_by_kind || {};

  const items = [
    { label: 'Evidence', value: kinds.Evidence || kinds.evidence || 0 },
    { label: 'Facts', value: kinds.Fact || kinds.fact || 0 },
    { label: 'Claims', value: kinds.Claim || kinds.claim || 0 },
    { label: 'Reasons', value: kinds.Reason || kinds.reason || 0 },
    { label: 'Experiments', value: kinds.Experiment || kinds.experiment || 0 },
  ];

  grid.innerHTML = items.map(i => `
    <div class="graph-stat">
      <div class="graph-stat-value">${i.value}</div>
      <div class="graph-stat-label">${i.label}</div>
    </div>
  `).join('');
}

async function loadContradictions() {
  const container = document.getElementById('contradictions-list');
  try {
    const data = await api('/api/detect-contradictions');
    const items = data.contradictions || data || [];
    if (!items.length) {
      container.innerHTML = '<div class="empty-state">No contradictions detected</div>';
      return;
    }
    container.innerHTML = items.slice(0, 10).map(c => {
      const text = typeof c === 'string' ? c : JSON.stringify(c);
      return `<div class="contradiction-card"><span class="contradiction-label">CONTRADICTION</span><p style="font-size:0.82rem;color:#c8d0e0;margin-top:4px;">${esc(text)}</p></div>`;
    }).join('');
  } catch (e) {
    container.innerHTML = '<div class="empty-state">Could not load contradictions</div>';
  }
}

async function loadHealth() {
  const container = document.getElementById('health-list');
  try {
    const data = await api('/api/check-revalidation');
    const items = data.nodes || data || [];
    if (!items.length) {
      container.innerHTML = '<div class="empty-state">All knowledge nodes up to date</div>';
      return;
    }
    container.innerHTML = items.slice(0, 10).map(n => `
      <div class="health-item">
        <span class="health-urgency">${esc(n.urgency || 'OVERDUE')}</span>
        <span style="font-size:0.78rem;color:var(--text-secondary);margin-left:8px;">${esc((n.statement || JSON.stringify(n)).slice(0, 100))}</span>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = '<div class="empty-state">All knowledge nodes up to date</div>';
  }
}

// ── Search ──
function setupSearch() {
  const input = document.getElementById('search-input');
  const btn = document.getElementById('search-btn');

  btn.addEventListener('click', () => doSearch(input.value));
  input.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(input.value); });
}

async function doSearch(query) {
  if (!query.trim()) return;
  const container = document.getElementById('search-results');
  container.innerHTML = '<div class="empty-state">Searching...</div>';

  try {
    const data = await api(`/api/graph/search?q=${encodeURIComponent(query)}&top_k=15`);
    const results = data.results || data || [];

    if (!results.length) {
      container.innerHTML = `<div class="empty-state">No results for "${esc(query)}"</div>`;
      return;
    }

    container.innerHTML = results.map(r => {
      const kindClass = `kind-${(r.kind || '').toLowerCase()}`;
      const failedTag = r.failed_path ? '<span class="search-result-failed"> [FAILED PATH]</span>' : '';
      return `
        <div class="search-result">
          <div class="search-result-header">
            <span class="search-result-kind ${kindClass}">${esc(r.kind || '')}</span>
            <span class="search-result-score">score: ${(r.score || 0).toFixed(3)} | hop: ${r.hop_distance || 0}</span>
            ${failedTag}
          </div>
          <div class="search-result-statement">${esc((r.statement || '').slice(0, 150))}</div>
        </div>`;
    }).join('');
  } catch (e) {
    container.innerHTML = `<div class="empty-state">Search failed: ${esc(e.message)}</div>`;
  }
}

// ── Utilities ──
function timeAgo(ts) {
  if (!ts) return '?';
  try {
    const d = new Date(ts);
    const now = Date.now();
    const diff = Math.floor((now - d.getTime()) / 60000);
    if (diff < 0) return 'just now';
    if (diff < 60) return `${diff}m ago`;
    const hours = Math.floor(diff / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  } catch { return ts.slice(0, 16); }
}

function getSourceClass(srcType) {
  const s = (srcType || '').toLowerCase();
  if (s.includes('exchange') || s.includes('binance')) return 'exchange';
  if (s.includes('twitter')) return 'twitter';
  if (s.includes('community')) return 'community';
  if (s.includes('whale')) return 'whale';
  return '';
}

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}
