import { unifiedFilteredBySourceKey, unifiedFilteredDailyRows, unifiedFilteredTotals } from './aggregate.js';
import { switchAnalysisTab, switchTab } from './actions.js';
import { currentFilters, filterInsightsBySource } from './filters.js';
import { renderUnifiedTrendChart } from './charts.js';
import { creditsFromCost, escapeHtml, formatCompact, formatCost, formatInteger, formatPercent, pickTokenBlock } from './format.js';
import { APP_DATA, STATE, isBilledMode } from './state.js';

    // Maps a status ('ok'|'warn'|'critical') onto the CSS state-class
    // contract in components.css -- colour, border weight, and an icon
    // glyph are all driven by this class alone; never hand-tune colour here.
    function stateClass(status) {
      return `state-${status === 'critical' ? 'critical' : status === 'warn' ? 'warn' : 'ok'}`;
    }

    // The budget is denominated in AI credits (1 credit = $0.01 of model
    // usage), which is how GitHub meters paid plans: `used` is this month's
    // billed cost x 100, not a count of calls or prompts. Legacy
    // premium-request figures live in `budget.legacyRequests` and are shown
    // separately so the two units are never mixed in one number.
    function renderBudgetPanel() {
      const budget = APP_DATA.premium?.budget || {};
      const hasAllowance = budget.allowance !== null && budget.allowance !== undefined;
      const legacy = budget.legacyRequests || {};
      // Gauge fill is clamped to 0-100%; the caption reports the real
      // percentage so an overrun stays visible as an overrun.
      const rawPct = Number(budget.percentUsed || 0);
      const pct = Math.max(0, Math.min(100, rawPct));
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
          <div class="section-title">AI credit budget (plan: ${escapeHtml(String(budget.plan || 'unknown'))})</div>
          <div class="note small">1 credit = ${formatCost(budget.creditUsd ?? 0.01)} of model usage. Credits used = this calendar month's billed cost x 100, across both sources.</div>
          <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:10px 0">
            <div style="flex:1;min-width:220px">
              <div class="gauge ${gaugeState}"><div class="gauge-fill ${gaugeState}" style="width:${hasAllowance ? pct.toFixed(1) : 0}%"></div></div>
              <div class="note small" style="margin-top:6px">${hasAllowance ? `${formatPercent(rawPct)} of the monthly credit allowance used` : 'No credit allowance configured — usage tracked, not budget-compared'}</div>
            </div>
            <div class="summary-grid" style="flex:2;min-width:280px">
              <div class="summary-card"><div class="label">Allowance (credits)</div><div class="value">${hasAllowance ? formatInteger(budget.allowance) : '—'}</div></div>
              <div class="summary-card"><div class="label">Credits used</div><div class="value">${formatInteger(budget.used)}</div><div class="note small">${formatCost(budget.usedUsd || 0)}</div></div>
              <div class="summary-card"><div class="label">Remaining</div><div class="value">${budget.remaining !== null && budget.remaining !== undefined ? formatInteger(budget.remaining) : '—'}</div></div>
              <div class="summary-card"><div class="label">Burn rate / day</div><div class="value">${formatCompact(budget.burnRatePerDay || 0)}</div></div>
              <div class="summary-card"><div class="label">Projected month-end</div><div class="value">${formatCompact(budget.projectedMonthEnd || 0)}</div></div>
              <div class="summary-card"><div class="label">Projected %</div><div class="value">${hasAllowance ? formatPercent(budget.projectedPercent || 0) : '—'}</div></div>
            </div>
          </div>
          ${alertsHtml ? `<div class="insights-grid">${alertsHtml}</div>` : ''}
          <div class="note small" style="margin-top:8px">Legacy premium requests this month: <strong>${formatInteger(legacy.used || 0)}</strong>${legacy.allowance ? ` of ${formatInteger(legacy.allowance)}` : ''} — counted per user prompt x model multiplier, and applicable only to annual Pro/Pro+ subscriptions still billed in requests. Not used for the gauge above.</div>
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
            <div class="note small">${formatInteger(source.sessionCount)} sessions · ${formatInteger(block.input + block.output)} tokens · ${formatInteger(source.modelCalls ?? source.callCount)} model calls · ${formatInteger(source.promptCount ?? source.callCount)} prompts</div>
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
          ${insight.estimatedSavings ? `<div class="note small">Est. savings: ${formatCost(insight.estimatedSavings.cost || 0)} · ${creditsFromCost(insight.estimatedSavings.cost || 0).toFixed(0)} AI credits</div>` : ''}
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
          <div class="summary-card" title="Model API calls — an agent loop makes many per prompt."><div class="label">Model calls</div><div class="value">${formatInteger(totals.modelCalls ?? totals.callCount)}</div></div>
          <div class="summary-card" title="User prompts submitted — the unit legacy premium requests are charged in."><div class="label">Prompts</div><div class="value">${formatInteger(totals.promptCount ?? totals.callCount)}</div></div>
          <div class="summary-card"><div class="label">Input tokens</div><div class="value input">${formatInteger(block.input)}</div></div>
          <div class="summary-card"><div class="label">Cached tokens</div><div class="value cached">${formatInteger(block.cached)}</div></div>
          <div class="summary-card"><div class="label">Output tokens</div><div class="value output">${formatInteger(block.output)}</div></div>
          <div class="summary-card"><div class="label">${isBilledMode() ? 'Billed cost' : 'Attributed est. cost'}</div><div class="value cost">${formatCost(block.cost)}</div></div>
          <div class="summary-card" title="1 AI credit = $0.01 of model usage."><div class="label">AI credits</div><div class="value credits">${creditsFromCost(block.cost).toFixed(1)}</div></div>
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
            <strong>Estimate disclaimer:</strong> token pricing, AI-credit plan allowances, and legacy premium-request multipliers shown throughout this dashboard are local estimates maintained in this repo (see <code>model_pricing.py</code> / <code>premium_requests.py</code>), fully configurable, and are <strong>not</strong> official GitHub billing data. Costs exclude cache-write tokens, long-context pricing tiers, and the auto-model-selection discount, so they run low. For authoritative credit consumption and billing, see your GitHub account's Copilot billing/usage page.
          </div>
        </div>`;
    }
