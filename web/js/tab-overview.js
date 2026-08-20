import { unifiedFilteredBySourceKey, unifiedFilteredDailyRows, unifiedFilteredTotals } from './aggregate.js';
import { switchAnalysisTab, switchTab } from './actions.js';
import { currentFilters, filterInsightsBySource } from './filters.js';
import { renderUnifiedTrendChart } from './charts.js';
import { escapeHtml, formatCompact, formatCost, formatInteger, formatPercent, pickTokenBlock } from './format.js';
import { APP_DATA, STATE, isBilledMode } from './state.js';

    // Maps a status ('ok'|'warn'|'critical') onto the CSS state-class
    // contract in components.css -- colour, border weight, and an icon
    // glyph are all driven by this class alone; never hand-tune colour here.
    function stateClass(status) {
      return `state-${status === 'critical' ? 'critical' : status === 'warn' ? 'warn' : 'ok'}`;
    }

    function renderBudgetPanel() {
      const budget = APP_DATA.premium?.budget || {};
      const hasAllowance = budget.allowance !== null && budget.allowance !== undefined;
      const pct = Math.max(0, Math.min(100, Number(budget.percentUsed || 0)));
      const gaugeState = stateClass(budget.status);
      const alerts = Array.isArray(budget.alerts) ? budget.alerts : [];
      const alertsHtml = alerts.length
        ? alerts.map((alert) => `
            <div class="insight-card ${stateClass(alert.severity)}">
              <div style="font-weight:700">${escapeHtml(alert.title || '')}</div>
              <div class="note small">${escapeHtml(alert.detail || '')}</div>
            </div>`).join('')
        : '';
      return `
        <div class="panel">
          <div class="section-title">Premium request budget (plan: ${escapeHtml(String(budget.plan || 'unknown'))})</div>
          <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:10px 0">
            <div style="flex:1;min-width:220px">
              <div class="gauge ${gaugeState}"><div class="gauge-fill ${gaugeState}" style="width:${hasAllowance ? pct.toFixed(1) : 0}%"></div></div>
              <div class="note small" style="margin-top:6px">${hasAllowance ? `${formatPercent(pct)} used` : 'No allowance configured — usage tracked, not budget-compared'}</div>
            </div>
            <div class="summary-grid" style="flex:2;min-width:280px">
              <div class="summary-card"><div class="label">Allowance</div><div class="value">${hasAllowance ? formatInteger(budget.allowance) : '—'}</div></div>
              <div class="summary-card"><div class="label">Used</div><div class="value">${formatInteger(budget.used)}</div></div>
              <div class="summary-card"><div class="label">Remaining</div><div class="value">${budget.remaining !== null && budget.remaining !== undefined ? formatInteger(budget.remaining) : '—'}</div></div>
              <div class="summary-card"><div class="label">Burn rate / day</div><div class="value">${formatCompact(budget.burnRatePerDay || 0)}</div></div>
              <div class="summary-card"><div class="label">Projected month-end</div><div class="value">${formatCompact(budget.projectedMonthEnd || 0)}</div></div>
              <div class="summary-card"><div class="label">Projected %</div><div class="value">${hasAllowance ? formatPercent(budget.projectedPercent || 0) : '—'}</div></div>
            </div>
          </div>
          ${alertsHtml ? `<div class="insights-grid">${alertsHtml}</div>` : ''}
        </div>`;
    }

    function renderSourceSplitPanel() {
      const chat = unifiedFilteredBySourceKey('chat');
      const cli = unifiedFilteredBySourceKey('cli');
      const row = (label, source) => {
        const block = pickTokenBlock(source.attributed, source.billed);
        return `
          <div class="summary-card">
            <div class="label">${escapeHtml(label)}</div>
            <div class="value cost">${formatCost(block.cost)}</div>
            <div class="note small">${formatInteger(source.sessionCount)} sessions · ${formatInteger(block.input + block.output)} tokens · ${formatInteger(source.callCount)} calls</div>
          </div>`;
      };
      return `
        <div class="panel">
          <div class="section-title">Chat vs CLI split</div>
          <div class="summary-grid">
            ${row('Chat (VS Code)', chat)}
            ${row('CLI', cli)}
          </div>
        </div>`;
    }

    function renderTopRollup(title, rows, keyName, keyLabel, noteWhenEmpty) {
      const top = (rows || []).slice(0, 5);
      if (!top.length) {
        return `<div class="panel"><div class="section-title">${escapeHtml(title)}</div><div class="note is-empty">${escapeHtml(noteWhenEmpty)}</div></div>`;
      }
      const body = top.map((row) => {
        const block = pickTokenBlock(row.attributed, row.billed);
        return `<tr>
          <td data-label="${escapeHtml(keyLabel)}">${escapeHtml(String(row[keyName] ?? 'unknown'))}</td>
          <td class="num" data-label="Cost">${formatCost(block.cost)}</td>
          <td class="num" data-label="Tokens">${formatInteger(block.input + block.output)}</td>
          <td class="num" data-label="Sessions">${formatInteger(row.sessionCount)}</td>
        </tr>`;
      }).join('');
      return `
        <div class="panel">
          <div class="section-title">${escapeHtml(title)}</div>
          <div class="note small">Across full history, all sources — not narrowed by the period/source filters above (these lists have no per-day breakdown server-side).</div>
          <div class="table-scroll">
            <table class="rollup-table table-collapse">
              <thead><tr><th>${escapeHtml(keyLabel)}</th><th class="num">Cost</th><th class="num">Tokens</th><th class="num">Sessions</th></tr></thead>
              <tbody>${body}</tbody>
            </table>
          </div>
        </div>`;
    }

    function severityRank(severity) {
      return { critical: 0, warn: 1, info: 2 }[severity] ?? 3;
    }

    function severityStateClass(severity) {
      if (severity === 'critical') return 'state-critical';
      if (severity === 'warn') return 'state-warn';
      return '';
    }

    // Scoped by the same global source filter Analysis -> Insights uses
    // (filters.js `filterInsightsBySource`), so the top 3 here are always a
    // subset of what that tab lists — never a different set of findings.
    function renderTopInsights() {
      const scoped = filterInsightsBySource(APP_DATA.insights);
      const insights = scoped.visible.slice().sort((a, b) => severityRank(a.severity) - severityRank(b.severity)).slice(0, 3);
      if (!insights.length) {
        const filteredOut = (APP_DATA.insights || []).length > 0;
        const emptyNote = filteredOut
          ? `No recommendations for the ${escapeHtml(scoped.source === 'cli' ? 'CLI' : 'Chat')} source — set the source filter to <strong>All</strong> to see every finding.`
          : 'No recommendations yet — insights are computed from unified usage + premium-request data.';
        return `<div class="panel"><div class="section-title">Top recommendations</div><div class="note is-empty">${emptyNote}</div></div>`;
      }
      const cards = insights.map((insight) => `
        <div class="insight-card ${severityStateClass(insight.severity)}">
          <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline">
            <div style="font-weight:700">${escapeHtml(insight.title || '')}</div>
            <span class="badge">${escapeHtml(insight.severity || 'info')}</span>
          </div>
          <div class="note small">${escapeHtml(insight.detail || '')}</div>
          ${insight.estimatedSavings ? `<div class="note small">Est. savings: ${formatCost(insight.estimatedSavings.cost || 0)} · ${formatInteger(insight.estimatedSavings.premiumRequests || 0)} premium requests</div>` : ''}
        </div>`).join('');
      return `
        <div class="panel">
          <div class="section-title">Top recommendations</div>
          <div class="insights-grid">${cards}</div>
          <div class="note small" style="margin-top:10px"><a href="#" onclick="openInsightsFromOverview(); return false;">View all insights in Analysis → Insights →</a></div>
        </div>`;
    }

    export function openInsightsFromOverview() {
      switchTab('analysis');
      switchAnalysisTab('insights');
    }

    export function renderOverviewTab() {
      const totals = unifiedFilteredTotals();
      const block = pickTokenBlock(totals.attributed, totals.billed);
      const unified = APP_DATA.unified || {};
      const dailyRows = unifiedFilteredDailyRows();
      const trendRows = dailyRows.length ? dailyRows : (unified.monthly || []);
      const filters = currentFilters();

      const kpis = `
        <div class="summary-grid">
          <div class="summary-card"><div class="label">Sessions</div><div class="value">${formatInteger(totals.sessionCount)}</div></div>
          <div class="summary-card"><div class="label">Calls</div><div class="value">${formatInteger(totals.callCount)}</div></div>
          <div class="summary-card"><div class="label">Input tokens</div><div class="value input">${formatInteger(block.input)}</div></div>
          <div class="summary-card"><div class="label">Cached tokens</div><div class="value cached">${formatInteger(block.cached)}</div></div>
          <div class="summary-card"><div class="label">Output tokens</div><div class="value output">${formatInteger(block.output)}</div></div>
          <div class="summary-card"><div class="label">${isBilledMode() ? 'Billed cost' : 'Attributed est. cost'}</div><div class="value cost">${formatCost(block.cost)}</div></div>
          <div class="summary-card"><div class="label">Premium requests</div><div class="value">${formatInteger(totals.premiumRequests)}</div></div>
        </div>`;

      const emptyNote = (!dailyRows.length && !(unified.monthly || []).length)
        ? '<div class="note is-empty">No usage data recorded yet for the selected filters.</div>'
        : '';

      return `
        <div class="panel">
          <div class="section-title">Overview — ${escapeHtml(filters.source === 'all' ? 'All sources' : filters.source)} · ${escapeHtml(filters.period)}</div>
          ${kpis}
        </div>
        ${renderBudgetPanel()}
        <div class="panel">
          <div class="section-title">Cost &amp; token trend (Chat vs CLI)</div>
          ${trendRows.length ? renderUnifiedTrendChart(trendRows, STATE.monthlyTrendMetric === 'input' || STATE.monthlyTrendMetric === 'output' ? 'tokens' : 'cost') : emptyNote}
        </div>
        ${renderSourceSplitPanel()}
        ${renderTopRollup('Top models', unified.byModel, 'model', 'Model', 'No model usage recorded yet.')}
        ${renderTopRollup('Top repositories', unified.byRepo, 'repository', 'Repository', 'No repository usage recorded yet.')}
        ${renderTopRollup(`Top ${APP_DATA.anonymized ? 'developers (anonymized)' : 'developers / hosts'}`, unified.byHost, 'host', 'Developer / host', 'No host/developer usage recorded yet.')}
        ${renderTopInsights()}
        <div class="panel">
          <div class="note small">
            <strong>Estimate disclaimer:</strong> token pricing, premium-request multipliers, and plan allowances shown throughout this dashboard are local estimates maintained in this repo (see <code>model_pricing.py</code> / <code>premium_requests.py</code>), fully configurable, and are <strong>not</strong> official GitHub billing data. For authoritative premium-request counts and billing, see your GitHub account's Copilot billing/usage page.
          </div>
        </div>`;
    }
