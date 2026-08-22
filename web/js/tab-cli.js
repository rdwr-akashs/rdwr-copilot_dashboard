import { monthlyTrendMetricConfig, visibleCliSessions } from './aggregate.js';
import { renderApp } from './app.js';
import { renderMonthlyTrendChart } from './charts.js';
import { calcModelCost, escapeHtml, formatCost, formatDuration, formatInteger, formatPercent, formatTimestamp } from './format.js';
import { openChatDeleteModal } from './modals.js';
import { APP_DATA, HIDDEN_CLI_SESSION_IDS, PRICING_TABLE, STATE, markCliSessionsHidden, restoreHiddenCliSessions } from './state.js';
import { renderStatCell, renderTable } from './tables.js';

    // ---------------------------------------------------------------------
    // Global filter integration (window.CopilotFilters)
    //
    // Another agent publishes `window.CopilotFilters` (period/source/date
    // filtering) independently of this module. It may not exist yet (still
    // being built) or may exist in a slightly different shape than the
    // agreed contract, so every access below is guarded with typeof checks
    // and try/catch, falling back to the current unfiltered behavior.
    // ---------------------------------------------------------------------

    function getCliFilterState() {
      const cf = window.CopilotFilters;
      if (!cf || typeof cf !== 'object') return { active: false };
      try {
        const sourceOk = typeof cf.matchesSource === 'function' ? cf.matchesSource('cli') !== false : true;
        const current = typeof cf.currentFilters === 'function' ? cf.currentFilters() : null;
        return { active: true, cf, sourceOk, current };
      } catch (_err) {
        return { active: false };
      }
    }

    function applyGlobalSessionFilter(sessions, filterState) {
      if (!filterState.active) return sessions;
      if (filterState.sourceOk === false) return [];
      const { cf } = filterState;
      if (typeof cf.filterSessions === 'function') {
        try {
          const out = cf.filterSessions(sessions, 'cli');
          if (Array.isArray(out)) return out;
        } catch (_err) {
          // fall through to unfiltered
        }
      }
      return sessions;
    }

    function filterLabel(filterState) {
      if (!filterState.active || !filterState.current) return '';
      const f = filterState.current || {};
      const parts = [];
      if (f.period) parts.push(f.period === 'custom' ? 'custom range' : f.period);
      if (f.source && f.source !== 'all') parts.push(`source: ${f.source}`);
      return parts.length ? ` · Global filters applied (${escapeHtml(parts.join(', '))})` : '';
    }

    // ---------------------------------------------------------------------
    // Local LEGACY premium-request estimation for CLI sessions.
    //
    // Premium requests are legacy (credit-billed plans are metered on cost —
    // see the AI credit budget panel); this exists for accounts still on
    // request-billed annual Pro/Pro+ and for reading historical data.
    //
    // The backend only attaches `premiumRequests` onto chat sessions and
    // `cli.byModel` rows (see dashboard_core.py), not onto individual CLI
    // session objects. When we need a per-session or per-repo estimate (for
    // filtered recompute / rollups) we replicate the backend's accounting
    // exactly, driven off `APP_DATA.premium.multipliers` so it stays in sync
    // with the backend config:
    //   * the same tolerant exact -> prefix -> substring -> default(1.0)
    //     match as premium_requests.py::get_multiplier, including its
    //     longest-key-first ordering (a shorter key that prefixes a longer one
    //     must not win just because it was declared first);
    //   * charged per user PROMPT, not per model call. `session.turnCount`
    //     counts prompts while `modelBreakdown[].calls` counts model calls,
    //     and an agent loop makes many calls per prompt — so prompts are
    //     apportioned across a session's model buckets by call share, exactly
    //     as usage_model.records_from_cli does.
    // This is a local estimate only, same caveat as the backend.
    // ---------------------------------------------------------------------

    function premiumMultiplierForModel(modelName) {
      const table = (APP_DATA.premium && APP_DATA.premium.multipliers) || {};
      const name = String(modelName || '').toLowerCase();
      if (Object.prototype.hasOwnProperty.call(table, name)) return Number(table[name]);
      for (const key of Object.keys(table).sort((a, b) => b.length - a.length)) {
        if (name.startsWith(key) || name.includes(key)) return Number(table[key]);
      }
      return 1.0;
    }

    // Prompts attributable to one modelBreakdown row of a session.
    function rowPromptCount(session, row) {
      const rows = session.modelBreakdown || [];
      const sessionCalls = rows.reduce((sum, r) => sum + Number(r.calls || 0), 0);
      if (!sessionCalls) return 0;
      // A session with calls but no recorded turnCount still had >= 1 prompt.
      const prompts = Number(session.turnCount || 0) || 1;
      return prompts * (Number(row.calls || 0) / sessionCalls);
    }

    function sessionPremiumRequests(session) {
      return (session.modelBreakdown || []).reduce(
        (sum, row) => sum + rowPromptCount(session, row) * premiumMultiplierForModel(row.model),
        0,
      );
    }

    function computeCliSummaryFromSessions(sessions) {
      const summary = {
        sessionCount: sessions.length, callCount: 0, totalInput: 0, totalOutput: 0,
        totalCached: 0, totalCost: 0, fileCount: 0, toolCallCount: 0, premiumRequests: 0,
      };
      const filePaths = new Set();
      sessions.forEach((session) => {
        summary.callCount += Number(session.callCount || 0);
        summary.totalInput += Number(session.input || 0);
        summary.totalOutput += Number(session.output || 0);
        summary.totalCached += Number(session.cached || 0);
        summary.totalCost += Number(session.cost || 0);
        summary.premiumRequests += sessionPremiumRequests(session);
        (session.files || []).forEach((file) => filePaths.add(file.path));
        (session.tools || []).forEach((tool) => { summary.toolCallCount += Number(tool.calls || 0); });
      });
      summary.fileCount = filePaths.size;
      return summary;
    }

    function computeCliByModelFromSessions(sessions) {
      const map = new Map();
      sessions.forEach((session) => {
        (session.modelBreakdown || []).forEach((row) => {
          const key = row.model;
          const bucket = map.get(key) || {
            model: key, calls: 0, input: 0, cached: 0, output: 0, cost: 0, premiumRequests: 0, sessionIds: new Set(),
          };
          bucket.calls += Number(row.calls || 0);
          bucket.input += Number(row.input || 0);
          bucket.cached += Number(row.cached || 0);
          bucket.output += Number(row.output || 0);
          bucket.cost += Number(row.cost || 0);
          bucket.premiumRequests += rowPromptCount(session, row) * premiumMultiplierForModel(row.model);
          bucket.sessionIds.add(session.id);
          map.set(key, bucket);
        });
      });
      return [...map.values()]
        .map((bucket) => ({ ...bucket, uncached: Math.max(0, bucket.input - bucket.cached), sessionCount: bucket.sessionIds.size }))
        .sort((a, b) => b.cost - a.cost);
    }

    // ---------------------------------------------------------------------
    // Trend charts (daily/monthly cost, tokens, sessions).
    //
    // Built directly from each CLI session's own `dayKey`/`monthKey`
    // (attached by cli_usage.py), so this works even if the separate
    // `APP_DATA.unified` pipeline is unavailable, and stays consistent with
    // whatever session set is currently visible (global filters + search).
    // Reuses `monthlyTrendMetricConfig()`/`renderMonthlyTrendChart()` from
    // the Chat side so the visual language matches, with our own metric/
    // granularity state so switching one tab's trend metric doesn't affect
    // the other's.
    // ---------------------------------------------------------------------

    function buildCliTrendRows(sessions, granularity) {
      const buckets = new Map();
      sessions.forEach((session) => {
        const key = granularity === 'daily' ? session.dayKey : session.monthKey;
        if (!key) return;
        const bucket = buckets.get(key) || {
          input: 0, uncached: 0, cached: 0, output: 0, cost: 0, sessionCount: 0, callCount: 0, toolCallCount: 0,
        };
        bucket.input += Number(session.input || 0);
        bucket.uncached += Number(session.uncached || 0);
        bucket.cached += Number(session.cached || 0);
        bucket.output += Number(session.output || 0);
        bucket.cost += Number(session.cost || 0);
        bucket.sessionCount += 1;
        bucket.callCount += Number(session.callCount || 0);
        bucket.toolCallCount += (session.tools || []).reduce((sum, tool) => sum + Number(tool.calls || 0), 0);
        buckets.set(key, bucket);
      });
      return [...buckets.keys()].sort().map((key) => {
        const bucket = buckets.get(key);
        return {
          monthKey: key,
          label: key,
          totals: { input: bucket.input, uncached: bucket.uncached, cached: bucket.cached, output: bucket.output, cost: bucket.cost },
          sessionCount: bucket.sessionCount,
          chatCallCount: bucket.callCount,
          toolCallCount: bucket.toolCallCount,
          cacheHitRate: bucket.input ? (bucket.cached / bucket.input) * 100 : 0,
        };
      });
    }

    export function switchCliTrendGranularity(value) {
      STATE.cliTrendGranularity = value === 'daily' ? 'daily' : 'monthly';
      renderApp();
    }

    export function switchCliTrendMetric(key) {
      STATE.cliTrendMetric = key;
      renderApp();
    }

    export function renderCliTrendSection(sessions) {
      if (!sessions.length) return '';
      const granularity = STATE.cliTrendGranularity === 'daily' ? 'daily' : 'monthly';
      const rows = buildCliTrendRows(sessions, granularity);
      if (!rows.length) {
        return `<section class="panel"><h2 class="section-title">CLI usage trends</h2><div class="is-empty">📈<div>No dated CLI sessions to chart yet.</div></div></section>`;
      }
      const metrics = monthlyTrendMetricConfig();
      const metricKey = metrics[STATE.cliTrendMetric] ? STATE.cliTrendMetric : 'cost';
      return `
        <section class="panel">
          <h2 class="section-title">CLI usage trends</h2>
          <div class="section-subtitle">Cost, token, and session trends across CLI sessions currently in view, bucketed by ${granularity === 'daily' ? 'day' : 'month'}.</div>
          <div class="analysis-subtabs" style="margin-bottom:8px">
            <button type="button" class="subtab-button ${granularity === 'monthly' ? 'active' : ''}" onclick="switchCliTrendGranularity('monthly')">Monthly</button>
            <button type="button" class="subtab-button ${granularity === 'daily' ? 'active' : ''}" onclick="switchCliTrendGranularity('daily')">Daily</button>
          </div>
          <div class="analysis-subtabs">
            ${Object.entries(metrics).filter(([key]) => key !== 'chatCalls' && key !== 'toolCalls').map(([key, cfg]) => `<button type="button" class="subtab-button ${metricKey === key ? 'active' : ''}" onclick="switchCliTrendMetric('${key}')">${escapeHtml(cfg.short)}</button>`).join('')}
          </div>
          ${renderMonthlyTrendChart(rows, metricKey)}
          <div class="note small" style="margin-top:8px">Bar tooltips read "Chats: N / Tools: M" — for the CLI tab those are CLI model calls / OTel <code>execute_tool</code> spans in that bucket (0 if OTel is off), reusing the same chart component as the Chats tab.</div>
        </section>`;
    }

    // ---------------------------------------------------------------------
    // Efficiency / waste views.
    //
    // Only surfaces metrics the underlying data can actually support:
    // session-store.db records tokens per model call (no per-tool token or
    // cost attribution), and OTel execute_tool spans carry durations only
    // (no tokens/cost). We do not fabricate a "cost per tool call" or
    // "wasted tokens" figure for the CLI the way the Chat-side tool-waste
    // view does, because the CLI backend has no data to support it.
    // ---------------------------------------------------------------------

    export function renderCliEfficiencySection(sessions, cli) {
      if (!sessions.length) return '';
      const overallInput = sessions.reduce((sum, s) => sum + Number(s.input || 0), 0);
      const overallCached = sessions.reduce((sum, s) => sum + Number(s.cached || 0), 0);
      const overallCacheHitRate = overallInput ? (overallCached / overallInput) * 100 : 0;

      const withRates = sessions.map((session) => ({
        session,
        cacheHitRate: session.input ? (session.cached / session.input) * 100 : 0,
        costPer1kOutput: session.output ? session.cost / (session.output / 1000) : 0,
      }));

      const lowestCacheHit = [...withRates].filter((r) => r.session.input > 0).sort((a, b) => a.cacheHitRate - b.cacheHitRate).slice(0, 5);
      const priciestSessions = [...sessions].sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0)).slice(0, 10);
      const priciestPer1k = [...withRates].filter((r) => r.session.output > 0).sort((a, b) => b.costPer1kOutput - a.costPer1kOutput).slice(0, 5);
      const priciestModels = [...((cli.byModel || []))].slice(0, 10);

      const sessionLabel = (session) => escapeHtml((session.repository || session.cwd || session.id || '').toString().slice(0, 60));

      const cacheHitGauge = `
        <div class="gauge state-${overallCacheHitRate >= 50 ? 'ok' : overallCacheHitRate >= 20 ? 'warn' : 'critical'}">
          <div class="gauge-fill state-${overallCacheHitRate >= 50 ? 'ok' : overallCacheHitRate >= 20 ? 'warn' : 'critical'}" style="width:${Math.min(100, overallCacheHitRate).toFixed(1)}%"></div>
        </div>
        <div class="gauge-label"><span>Overall cache-hit rate</span><span>${formatPercent(overallCacheHitRate)} of ${formatInteger(overallInput)} input tokens</span></div>`;

      function cacheStateClass(rate) {
        return rate >= 50 ? 'state-ok' : rate >= 20 ? 'state-warn' : 'state-critical';
      }

      const priciestSessionsTable = renderTable([
        { title: 'Session', render: (row) => sessionLabel(row) },
        { title: 'Cost', numeric: true, render: (row) => `<span class="value cost">${formatCost(row.cost)}</span>` },
        { title: 'Cost / 1K output', numeric: true, render: (row) => formatCost(row.output ? row.cost / (row.output / 1000) : 0) },
        { title: 'Cache hit rate', numeric: true, render: (row) => {
          const rate = row.input ? (row.cached / row.input) * 100 : 0;
          return `<span class="${cacheStateClass(rate)}">${formatPercent(rate)}</span>`;
        } },
      ], priciestSessions);

      const lowestCacheHitTable = lowestCacheHit.length ? renderTable([
        { title: 'Session', render: (row) => sessionLabel(row.session) },
        { title: 'Cache hit rate', numeric: true, render: (row) => `<span class="${cacheStateClass(row.cacheHitRate)}">${formatPercent(row.cacheHitRate)}</span>` },
        { title: 'Total input', numeric: true, render: (row) => formatInteger(row.session.input) },
        { title: 'Cost', numeric: true, render: (row) => formatCost(row.session.cost) },
      ], lowestCacheHit) : '<div class="is-empty">Not enough sessions with input tokens to rank yet.</div>';

      const priciestPer1kTable = priciestPer1k.length ? renderTable([
        { title: 'Session', render: (row) => sessionLabel(row.session) },
        { title: 'Cost / 1K output', numeric: true, render: (row) => `<span class="value cost">${formatCost(row.costPer1kOutput)}</span>` },
        { title: 'Output tokens', numeric: true, render: (row) => formatInteger(row.session.output) },
      ], priciestPer1k) : '<div class="is-empty">No sessions with output tokens to rank yet.</div>';

      const priciestModelsTable = renderTable([
        { title: 'Model', render: (row) => `<strong>${escapeHtml(row.model)}</strong>` },
        { title: 'Cost', numeric: true, render: (row) => `<span class="value cost">${formatCost(row.cost)}</span>` },
        { title: 'Premium reqs (legacy est.)', numeric: true, render: (row) => formatInteger(row.premiumRequests) },
        { title: 'Calls', numeric: true, render: (row) => formatInteger(row.calls) },
      ], priciestModels);

      const cliTools = cli.tools || [];
      const otelToolSection = cli.otelAvailable && cliTools.length
        ? `
          <div class="event-section" style="margin-top:14px">
            <h4>Slowest tools (avg duration, OTel)</h4>
            <div class="table-scroll">${renderTable([
              { title: 'Tool', render: (row) => `<strong>${escapeHtml(row.tool)}</strong>` },
              { title: 'Avg duration', numeric: true, render: (row) => formatDuration(row.avgDurationMs) },
              { title: 'Calls', numeric: true, render: (row) => formatInteger(row.calls) },
            ], [...cliTools].sort((a, b) => Number(b.avgDurationMs || 0) - Number(a.avgDurationMs || 0)).slice(0, 10))}</div>
          </div>
          <div class="event-section" style="margin-top:14px">
            <h4>Most-called tools (OTel)</h4>
            <div class="table-scroll">${renderTable([
              { title: 'Tool', render: (row) => `<strong>${escapeHtml(row.tool)}</strong>` },
              { title: 'Calls', numeric: true, render: (row) => formatInteger(row.calls) },
              { title: 'Total duration', numeric: true, render: (row) => formatDuration(row.totalDurationMs) },
            ], [...cliTools].sort((a, b) => Number(b.calls || 0) - Number(a.calls || 0)).slice(0, 10))}</div>
          </div>
          <div class="note small" style="margin-top:8px">OTel <code>execute_tool</code> spans carry duration only — no token or cost attribution — so these tables cannot show a "cost per tool call" figure the way model calls can.</div>`
        : `<div class="is-empty">Tool duration/call-count breakdown needs the CLI's OpenTelemetry file export — see the OpenTelemetry status panel at the bottom of this tab for setup steps.</div>`;

      return `
        <section class="panel">
          <h2 class="section-title">Efficiency &amp; cost outliers</h2>
          <div class="section-subtitle">Cache-hit rate, cost-per-session and cost-per-1K-output-token outliers across CLI sessions currently in view. Cache-hit rate here is per model call (input vs. cache-read tokens reported by <code>session-store.db</code>), not a token-level trace of what was reused.</div>
          ${cacheHitGauge}
          <div class="event-section" style="margin-top:14px"><h4>Most expensive sessions</h4><div class="table-scroll">${priciestSessionsTable}</div></div>
          <div class="event-section" style="margin-top:14px"><h4>Lowest cache-hit-rate sessions</h4>${lowestCacheHit.length ? `<div class="table-scroll">${lowestCacheHitTable}</div>` : lowestCacheHitTable}</div>
          <div class="event-section" style="margin-top:14px"><h4>Highest cost per 1K output tokens</h4>${priciestPer1k.length ? `<div class="table-scroll">${priciestPer1kTable}</div>` : priciestPer1kTable}</div>
          <div class="event-section" style="margin-top:14px"><h4>Most expensive models</h4><div class="table-scroll">${priciestModelsTable}</div></div>
          ${otelToolSection}
        </section>`;
    }

    // ---------------------------------------------------------------------
    // Repository / branch rollup.
    // ---------------------------------------------------------------------

    export function renderCliRepoRollupSection(sessions) {
      if (!sessions.length) return '';
      const map = new Map();
      sessions.forEach((session) => {
        const repository = session.repository || session.cwd || 'unknown';
        const branch = session.branch || '—';
        const key = `${repository}\u0000${branch}`;
        const bucket = map.get(key) || { repository, branch, cost: 0, input: 0, output: 0, cached: 0, sessionCount: 0, premiumRequests: 0 };
        bucket.cost += Number(session.cost || 0);
        bucket.input += Number(session.input || 0);
        bucket.output += Number(session.output || 0);
        bucket.cached += Number(session.cached || 0);
        bucket.sessionCount += 1;
        bucket.premiumRequests += sessionPremiumRequests(session);
        map.set(key, bucket);
      });
      const rows = [...map.values()].sort((a, b) => b.cost - a.cost);
      // Custom markup (rather than the shared renderTable() helper) so this
      // table can opt into `.table-collapse` + `data-label` per cell, which
      // reflows it into cards on narrow screens instead of scrolling.
      const table = `
        <div class="panel">
          <table class="table-collapse rollup-table">
            <thead>
              <tr>
                <th>Repository</th><th>Branch</th><th class="num">Sessions</th>
                <th class="num">Input</th><th class="num">Output</th><th class="num">Cost</th><th class="num">Premium reqs (legacy est.)</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map((row) => `<tr>
                <td data-label="Repository"><span style="word-break:break-all">${escapeHtml(row.repository)}</span></td>
                <td data-label="Branch">${escapeHtml(row.branch)}</td>
                <td data-label="Sessions" class="num">${formatInteger(row.sessionCount)}</td>
                <td data-label="Input" class="num"><span class="value input">${formatInteger(row.input)}</span></td>
                <td data-label="Output" class="num"><span class="value output">${formatInteger(row.output)}</span></td>
                <td data-label="Cost" class="num"><span class="value cost">${formatCost(row.cost)}</span></td>
                <td data-label="Premium reqs (legacy est.)" class="num">${formatInteger(row.premiumRequests)}</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
      return `
        <section class="panel">
          <h2 class="section-title">By repository &amp; branch</h2>
          <div class="section-subtitle">CLI usage grouped by repository and branch (falls back to working directory when no git repository was detected).</div>
          ${table}
        </section>`;
    }

    // ---------------------------------------------------------------------
    // OTel status & setup panel.
    // ---------------------------------------------------------------------

    export function copyCliSetupSnippet(elementId, buttonEl) {
      const el = document.getElementById(elementId);
      if (!el) return;
      const text = el.textContent || '';
      const finish = () => {
        if (!buttonEl) return;
        const original = buttonEl.textContent;
        buttonEl.textContent = '✓ Copied';
        buttonEl.classList.add('copied');
        setTimeout(() => {
          buttonEl.textContent = original;
          buttonEl.classList.remove('copied');
        }, 1500);
      };
      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        navigator.clipboard.writeText(text).then(finish).catch(() => {});
      }
    }

    export function renderCliOtelPanel(cli) {
      const on = !!cli.otelAvailable;
      const paths = cli.otelPaths || [];
      const tools = cli.tools || [];
      const totalSpans = tools.reduce((sum, tool) => sum + Number(tool.calls || 0), 0);
      const toolTypeCount = tools.length;
      const toolTypesLinked = tools.filter((tool) => Number(tool.sessionCount || 0) > 0).length;
      const dbFound = !!cli.available;
      const dbStatus = dbFound
        ? `Found at <code>${escapeHtml(cli.dbPath || '')}</code>.`
        : `Not found${cli.dbPath ? ` (looked at <code>${escapeHtml(cli.dbPath)}</code>)` : ' (no path resolved — set <code>COPILOT_CLI_DB</code> or use <code>--cli-db</code>)'}. This is why the CLI tab is empty above.`;

      const statusBody = on
        ? `
          <div class="state-ok" style="padding:8px 12px;border-radius:8px;background:var(--panel-2)">OTel enrichment is <strong>active</strong> — parsed from ${paths.length ? paths.map((p) => `<code>${escapeHtml(p)}</code>`).join(', ') : 'a configured file-exporter path'}.</div>
          <div class="note small" style="margin-top:10px">
            <strong>Spans read:</strong> ${formatInteger(totalSpans)} <code>execute_tool</code> spans across ${formatInteger(toolTypeCount)} distinct tool names.<br>
            <strong>Session join:</strong> ${formatInteger(toolTypesLinked)}/${formatInteger(toolTypeCount)} tool names linked to at least one session via <code>gen_ai.conversation.id</code>. The backend does not currently expose a per-span join count, only per-tool session linkage, so treat this as a lower bound on the true join rate — spans without a conversation ID exist but aren't attributable to any session and are excluded from the "linked" count.<br>
            <strong>CLI database:</strong> ${dbStatus}
          </div>`
        : `
          <div class="${dbFound ? 'state-warn' : 'state-critical'}" style="padding:8px 12px;border-radius:8px;background:var(--panel-2);margin-bottom:10px">OTel enrichment is <strong>off</strong> — no <code>execute_tool</code> spans were parsed${paths.length ? ` from the configured path(s) (${paths.map((p) => `<code>${escapeHtml(p)}</code>`).join(', ')})` : ' (no file-exporter path is configured)'}. Without it, the Tool impact section and OTel-based efficiency views above stay hidden — this is expected, not an error.</div>
          <div class="note small" style="margin-bottom:8px"><strong>CLI database:</strong> ${dbStatus}</div>
          <div class="note small" style="margin-bottom:8px">Per the official docs, CLI OTel activates when any of <code>COPILOT_OTEL_ENABLED=true</code>, <code>OTEL_EXPORTER_OTLP_ENDPOINT</code>, or <code>COPILOT_OTEL_FILE_EXPORTER_PATH</code> is set. This dashboard reads the <strong>file exporter</strong> format, so set <code>COPILOT_OTEL_FILE_EXPORTER_PATH</code> before running <code>copilot</code>, then point the dashboard at that file with <code>--cli-otel-log &lt;path&gt;</code>.</div>
          <div class="code-block" style="margin-bottom:10px">
            <div class="note small" style="margin-bottom:6px;font-weight:700">PowerShell</div>
            <pre id="cliOtelPsSnippet" style="margin:0;white-space:pre-wrap">$env:COPILOT_OTEL_FILE_EXPORTER_PATH = "$HOME\\.copilot\\otel.jsonl"
copilot
# then, next time you generate the dashboard:
python dashboard_core.py --cli-otel-log "$HOME\\.copilot\\otel.jsonl"</pre>
            <button type="button" class="copy-button" onclick="copyCliSetupSnippet('cliOtelPsSnippet', this)">⧉ Copy</button>
          </div>
          <div class="code-block">
            <div class="note small" style="margin-bottom:6px;font-weight:700">bash</div>
            <pre id="cliOtelBashSnippet" style="margin:0;white-space:pre-wrap">export COPILOT_OTEL_FILE_EXPORTER_PATH="$HOME/.copilot/otel.jsonl"
copilot
# then, next time you generate the dashboard:
python dashboard_core.py --cli-otel-log "$HOME/.copilot/otel.jsonl"</pre>
            <button type="button" class="copy-button" onclick="copyCliSetupSnippet('cliOtelBashSnippet', this)">⧉ Copy</button>
          </div>`;

      return `
        <section class="panel">
          <h2 class="section-title">OpenTelemetry status</h2>
          <div class="section-subtitle">Diagnostics for the CLI's optional OpenTelemetry file-exporter enrichment layer, and the underlying <code>session-store.db</code> read.</div>
          ${statusBody}
        </section>`;
    }

    export function renderCliTab() {
      const cli = APP_DATA.cli || {};
      if (!cli.available) {
        return `
          <section class="panel">
            <h2 class="section-title">GitHub Copilot CLI usage</h2>
            <div class="is-empty">
              🖥️
              <div>No local CLI usage database found${cli.dbPath ? ` at <code>${escapeHtml(cli.dbPath)}</code>` : ''}.</div>
              <div class="note small">This reads <code>~/.copilot/session-store.db</code> (override with the <code>COPILOT_CLI_DB</code> env var or <code>--cli-db</code> flag), which the Copilot CLI populates locally as you use it — nothing to enable, just use the CLI on this machine.</div>
            </div>
          </section>
          ${renderCliOtelPanel(cli)}`;
      }

      const filterState = getCliFilterState();
      const allSessions = visibleCliSessions();
      const sessions = applyGlobalSessionFilter(allSessions, filterState);
      const filtersReducedSet = filterState.active && sessions.length !== allSessions.length;
      const summary = filtersReducedSet ? computeCliSummaryFromSessions(sessions) : (cli.summary || {});
      const byModelRows = filtersReducedSet ? computeCliByModelFromSessions(sessions) : (cli.byModel || []);
      const models = [...new Set(sessions.flatMap((row) => row.models || []))].sort();
      const search = (STATE.cliSearch || '').trim().toLowerCase();
      const modelFiltered = STATE.cliModel ? sessions.filter((row) => (row.models || []).includes(STATE.cliModel)) : sessions;
      const filtered = search
        ? modelFiltered.filter((row) => [row.id, row.cwd, row.repository, row.branch, row.summary, ...(row.models || [])].some((value) => String(value || '').toLowerCase().includes(search)))
        : modelFiltered;
      const hiddenCliCount = HIDDEN_CLI_SESSION_IDS.size;
      const totalPremiumRequests = byModelRows.reduce((sum, row) => sum + Number(row.premiumRequests || 0), 0);

      // Cards + caveat live inside the tab's header panel. As a bare
      // `.summary-grid` they sat on the page background outside any panel,
      // so the row and its footnote ran edge-to-edge and broke the column
      // alignment every other section on the page follows.
      const summaryCards = `
        <section class="panel">
          <h2 class="section-title">GitHub Copilot CLI usage</h2>
          <div class="section-subtitle">Read directly from <code>${escapeHtml(cli.dbPath || '')}</code> on this machine — local CLI usage only, kept separate from VS Code chat sessions.${filterLabel(filterState)}</div>
          <div class="summary-grid">
            <div class="summary-card"><div class="label">CLI sessions</div><div class="value">${formatInteger(summary.sessionCount)}</div></div>
            <div class="summary-card"><div class="label">Model calls</div><div class="value">${formatInteger(summary.callCount)}</div></div>
            <div class="summary-card"><div class="label">Input tokens</div><div class="value input">${formatInteger(summary.totalInput)}</div></div>
            <div class="summary-card"><div class="label">Cached-read input</div><div class="value cached">${formatInteger(summary.totalCached)}</div></div>
            <div class="summary-card"><div class="label">Output tokens</div><div class="value output">${formatInteger(summary.totalOutput)}</div></div>
            <div class="summary-card"><div class="label">Estimated cost</div><div class="value cost">${formatCost(summary.totalCost)}</div></div>
            <div class="summary-card"><div class="label">Files touched</div><div class="value">${formatInteger(summary.fileCount)}</div></div>
            <div class="summary-card" title="Legacy per-prompt meter. Credit-billed plans are metered on cost instead — see the AI credit budget on Overview."><div class="label">Premium requests</div><div class="value">${formatInteger(totalPremiumRequests)}</div><div class="note small">legacy est.</div></div>
            ${cli.otelAvailable ? `<div class="summary-card"><div class="label">Tool calls</div><div class="value">${formatInteger(summary.toolCallCount)}</div><div class="note small">from OTel</div></div>` : ''}
          </div>
          <details class="method-note">
            <summary class="note small">How premium requests are estimated here</summary>
            <div class="note small" style="margin-top:8px">Premium requests are the legacy meter (annual request-billed Pro/Pro+ only); credit-billed plans are metered on cost — see the AI credit budget on Overview. Counts are local estimates: one per user prompt (apportioned from <code>turnCount</code>, not per model call) times the model multiplier from <code>APP_DATA.premium.multipliers</code>, not official GitHub billing — check github.com/settings/billing for the authoritative figures.</div>
          </details>
          ${filterState.active && filterState.sourceOk === false ? '<div class="state-warn" style="padding:8px 12px;border-radius:8px;background:var(--panel-2);margin-top:12px">CLI data is currently hidden by the global source filter. Switch the source filter to "All" or "CLI" to see it here.</div>' : ''}
        </section>`;

      const byModelTable = renderTable([
        { title: 'Model', render: (row) => `<div><strong>${escapeHtml(row.model)}</strong><div class="note small">${formatInteger(row.calls)} calls across ${formatInteger(row.sessionCount)} sessions</div></div>` },
        { title: 'Input', numeric: true, render: (row) => `<span class="value input">${formatInteger(row.input)}</span>` },
        { title: 'Uncached input', numeric: true, render: (row) => `<span class="value uncached">${formatInteger(row.uncached)}</span>` },
        { title: 'Cached-read input', numeric: true, render: (row) => `<span class="value cached">${formatInteger(row.cached)}</span>` },
        { title: 'Output', numeric: true, render: (row) => `<span class="value output">${formatInteger(row.output)}</span>` },
        { title: 'Cost', numeric: true, render: (row) => `<span class="value cost">${formatCost(row.cost)}</span>` },
        { title: 'Premium reqs (legacy est.)', numeric: true, render: (row) => formatInteger(row.premiumRequests) },
      ], byModelRows);

      const cliTools = cli.tools || [];
      const toolImpactTable = cliTools.length ? renderTable([
        { title: 'Tool', render: (row) => `<strong>${escapeHtml(row.tool)}</strong>` },
        { title: 'Calls', numeric: true, render: (row) => formatInteger(row.calls) },
        { title: 'Sessions', numeric: true, render: (row) => formatInteger(row.sessionCount) },
        { title: 'Avg duration', numeric: true, render: (row) => formatDuration(row.avgDurationMs) },
        { title: 'Total duration', numeric: true, render: (row) => formatDuration(row.totalDurationMs) },
      ], cliTools) : '';
      const toolImpactSection = cli.otelAvailable
        ? `
        <section class="panel">
          <h2 class="section-title">Tool impact <span class="note small" style="font-weight:400">(from OpenTelemetry export)</span></h2>
          <div class="section-subtitle">Real per-tool-call counts and durations, parsed from the CLI's OpenTelemetry JSONL export${(cli.otelPaths || []).length ? `: <code>${escapeHtml((cli.otelPaths || []).join(', '))}</code>` : ''}. Joined onto sessions via <code>gen_ai.conversation.id</code>.</div>
          ${toolImpactTable ? `<div class="table-scroll">${toolImpactTable}</div>` : '<div class="is-empty">No execute_tool spans found in the OTel export yet.</div>'}
        </section>`
        : '';

      const fileSearch = (STATE.cliFileSearch || '').trim().toLowerCase();
      const files = (cli.files || []).filter((row) => !fileSearch || String(row.path || '').toLowerCase().includes(fileSearch));
      const filesTable = renderTable([
        { title: 'File', render: (row) => `<span class="note small" style="word-break:break-all">${escapeHtml(row.path)}</span>` },
        { title: 'Created', numeric: true, render: (row) => formatInteger(row.created) },
        { title: 'Edited', numeric: true, render: (row) => formatInteger(row.edited) },
        { title: 'Total touches', numeric: true, render: (row) => `<strong>${formatInteger(row.touches)}</strong>` },
        { title: 'Sessions', numeric: true, render: (row) => formatInteger(row.sessionCount) },
        { title: 'Last touched', render: (row) => formatTimestamp(row.lastTouched) },
      ], files.slice(0, 200));

      const cliPageSize = STATE.cliPageSize || 10;
      const cliPageCount = Math.max(1, Math.ceil(filtered.length / cliPageSize));
      if (STATE.cliPage > cliPageCount) STATE.cliPage = cliPageCount;
      const cliPage = Math.max(1, STATE.cliPage || 1);
      const pageSlice = filtered.slice((cliPage - 1) * cliPageSize, cliPage * cliPageSize);
      const sessionCardsHtml = pageSlice.map((session) => renderCliSession(session)).join('');

      // Section order mirrors the Chats tab: the session list is the thing
      // people come here to read, so it sits directly under the summary cards
      // rather than below every rollup/diagnostic panel (which used to push it
      // ~1500px down the page). Aggregate analyses and the OTel diagnostics
      // follow it, in cheapest-to-scan-first order.
      const sessionListSection = `
        <section class="panel">
          <div class="filter-bar">
            <input type="text" id="cliSearchInput" placeholder="Search by repository, cwd, branch, session ID, or model…" value="${escapeHtml(STATE.cliSearch || '')}" oninput="setCliSearch(this.value)">
            <select onchange="setCliModelFilter(this.value)">
              <option value="">All models</option>
              ${models.map((model) => `<option value="${escapeHtml(model)}" ${STATE.cliModel === model ? 'selected' : ''}>${escapeHtml(model)}</option>`).join('')}
            </select>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-left:auto">
              <button type="button" class="action-chip action-chip--red" onclick="openChatDeleteModal('cli')">🗑 Delete CLI sessions</button>
              ${hiddenCliCount ? `<button type="button" class="action-chip action-chip--blue" onclick="restoreHiddenCliSessions()">↩ Restore hidden (${formatInteger(hiddenCliCount)})</button>` : ''}
            </div>
          </div>
          <div class="pagination" style="margin-top:8px">
            <div class="note">Showing ${filtered.length ? `${(cliPage - 1) * cliPageSize + 1}-${Math.min(cliPage * cliPageSize, filtered.length)}` : '0'} of ${formatInteger(filtered.length)} CLI sessions</div>
            <div class="pagination-controls">
              <label class="note">Per page</label>
              <select onchange="setCliPageSize(this.value)">
                ${[5, 10, 20, 50].map((size) => `<option value="${size}" ${cliPageSize === size ? 'selected' : ''}>${size}</option>`).join('')}
              </select>
              <button type="button" onclick="changeCliPage(-1)" ${cliPage <= 1 ? 'disabled' : ''}>Prev</button>
              <span class="note">Page ${cliPage} / ${cliPageCount}</span>
              <button type="button" onclick="changeCliPage(1)" ${cliPage >= cliPageCount ? 'disabled' : ''}>Next</button>
            </div>
          </div>
          <details class="method-note">
            <summary class="note small">About deleting sessions</summary>
            <div class="note small" style="margin-top:8px">Delete actions hide CLI sessions in this browser view (persisted locally) and can be reverted with <em>Restore hidden</em>. They do not modify <code>session-store.db</code>.</div>
          </details>
        </section>
        <section class="session-list">${sessionCardsHtml || '<div class="panel"><div class="is-empty">No CLI sessions match the current filter.</div></div>'}</section>`;

      return `
        ${summaryCards}
        ${sessionListSection}
        <section class="panel">
          <h2 class="section-title">By model</h2>
          <div class="table-scroll">${byModelTable}</div>
        </section>
        ${renderCliTrendSection(sessions)}
        ${toolImpactSection}
        ${renderCliEfficiencySection(sessions, cli)}
        ${renderCliRepoRollupSection(sessions)}
        <section class="panel">
          <h2 class="section-title">File activity (aggregate, all sessions)</h2>
          <div class="note small">Files created or edited across all CLI sessions combined (from local file-write history). Expand a session card above and see "Files touched in this session" for a per-session breakdown of the same data. ${cli.otelAvailable ? 'Per-tool token/cost breakdown is not shown here since OTel execute_tool spans don\'t carry token/cost data; see the Tool impact section above for real per-tool call counts and durations.' : 'Enable the CLI\'s built-in OpenTelemetry export (set <code>COPILOT_OTEL_FILE_EXPORTER_PATH</code> before running <code>copilot</code>, then pass the file via <code>--cli-otel-log</code>) to also unlock a Tool impact view above.'}</div>
          <div class="filter-bar" style="margin-top:8px">
            <input type="text" id="cliFileSearchInput" placeholder="Search by file path…" value="${escapeHtml(STATE.cliFileSearch || '')}" oninput="setCliFileSearch(this.value)">
          </div>
          <h2 class="section-title" style="margin-top:12px">Files (${formatInteger(files.length)}${files.length > 200 ? ', showing top 200' : ''})</h2>
          <div class="table-scroll">${filesTable}</div>
        </section>
        ${renderCliOtelPanel(cli)}`;
    }

    export function renderCliSession(session) {
      const modelBadges = (session.models || []).slice(0, 3).map((modelName) => `<span class="badge model">${escapeHtml(modelName)}</span>`).join('');
      const extraModels = (session.models || []).length > 3 ? `<span class="badge source">+${formatInteger(session.models.length - 3)} models</span>` : '';
      const titleText = session.repository || session.cwd || session.id;
      return `
        <details class="session-card">
          <summary class="session-summary-row">
            <div class="title-col">
              <div class="title-line">
                ${modelBadges || '<span class="badge model">unknown</span>'}
                ${extraModels}
                <span class="badge source">CLI</span>
                <span class="title-text">${escapeHtml(titleText)}</span>
              </div>
              <div class="subtext">${escapeHtml(session.id)}${session.branch ? ` · ${escapeHtml(session.branch)}` : ''} · ${escapeHtml(formatTimestamp(session.lastActivity))} · ${formatInteger(session.callCount)} calls · ${formatInteger(session.turnCount)} turns</div>
            </div>
            ${renderStatCell('Total input', formatInteger(session.input), 'input')}
            ${renderStatCell('Uncached', formatInteger(session.uncached), 'uncached')}
            ${renderStatCell('Cached-read', formatInteger(session.cached), 'cached', true)}
            ${renderStatCell('Output', formatInteger(session.output), 'output')}
            ${renderStatCell('Turns', formatInteger(session.turnCount))}
            ${renderStatCell('Cost', formatCost(session.cost), 'cost')}
          </summary>
          <div class="session-body">
            <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:12px;flex-wrap:wrap">
              <button type="button" class="action-chip action-chip--blue" onclick="event.stopPropagation();openCliFullChatModal('${session.id}')">📂 Show full chat</button>
              <button type="button" class="action-chip action-chip--purple" onclick="event.stopPropagation();openCliModelCompareModal('${session.id}')">⚖ Compare models</button>
              <button type="button" class="action-chip action-chip--teal" onclick="event.stopPropagation();exportCliSessionToJson('${session.id}')">⬇ Export chat JSON</button>
              <button type="button" class="action-chip action-chip--red" onclick="event.stopPropagation();deleteCliSessionPrompt('${session.id}')">🗑 Delete chat</button>
            </div>
            ${renderCliSessionMeta(session)}
            ${renderCliModelBreakdown(session)}
            ${renderCliSessionFiles(session)}
            <div class="note small" style="margin-top:12px;text-align:center">Turn-by-turn conversation (user messages + assistant responses) loads in the full chat view — press <strong>📂 Show full chat</strong>.</div>
          </div>
        </details>`;
    }

    export function renderCliSessionMeta(session) {
      return `
        <div class="session-meta">
          <div class="meta-card"><div class="label">Session ID</div><div class="value">${escapeHtml(session.id)}</div></div>
          <div class="meta-card"><div class="label">Repository</div><div class="value">${escapeHtml(session.repository || '—')}</div></div>
          <div class="meta-card"><div class="label">Working directory</div><div class="value" style="word-break:break-all">${escapeHtml(session.cwd || '—')}</div></div>
          <div class="meta-card"><div class="label">Branch</div><div class="value">${escapeHtml(session.branch || '—')}</div></div>
          <div class="meta-card"><div class="label">Model(s) used</div><div class="value">${escapeHtml((session.models || []).join(', ') || 'unknown')}</div></div>
          <div class="meta-card"><div class="label">Model calls</div><div class="value">${formatInteger(session.callCount)}</div></div>
          <div class="meta-card"><div class="label">Turns</div><div class="value">${formatInteger(session.turnCount)}</div></div>
          <div class="meta-card"><div class="label">Total input</div><div class="value input">${formatInteger(session.input)}</div></div>
          <div class="meta-card"><div class="label">Uncached input</div><div class="value uncached">${formatInteger(session.uncached)}</div></div>
          <div class="meta-card"><div class="label">Cached-read</div><div class="value cached">${formatInteger(session.cached)}</div></div>
          <div class="meta-card"><div class="label">Total output</div><div class="value output">${formatInteger(session.output)}</div></div>
          <div class="meta-card"><div class="label">Estimated cost</div><div class="value cost">${formatCost(session.cost)}</div></div>
          <div class="meta-card"><div class="label">Cache hit rate</div><div class="value cached">${formatPercent(session.input ? (session.cached / session.input) * 100 : 0)}</div></div>
          <div class="meta-card"><div class="label">Files touched</div><div class="value">${formatInteger((session.files || []).length)}</div></div>
          <div class="meta-card"><div class="label">Created</div><div class="value">${escapeHtml(formatTimestamp(session.createdAt))}</div></div>
          <div class="meta-card"><div class="label">Last activity</div><div class="value">${escapeHtml(formatTimestamp(session.lastActivity))}</div></div>
        </div>`;
    }

    export function renderCliModelBreakdown(session) {
      const rows = session.modelBreakdown || [];
      if (!rows.length) return '';
      return `
        <div class="event-section" style="margin-bottom:14px">
          <h4>Per-model breakdown</h4>
          <table>
            <thead><tr><th>Model</th><th class="num">Calls</th><th class="num">Input</th><th class="num">Cached-read</th><th class="num">Output</th><th class="num">Cost</th></tr></thead>
            <tbody>
              ${rows.map((row) => `<tr>
                <td>${escapeHtml(row.model)}</td>
                <td class="num">${formatInteger(row.calls)}</td>
                <td class="num"><span class="value input">${formatInteger(row.input)}</span></td>
                <td class="num"><span class="value cached">${formatInteger(row.cached)}</span></td>
                <td class="num"><span class="value output">${formatInteger(row.output)}</span></td>
                <td class="num"><span class="value cost">${formatCost(row.cost)}</span></td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    }

    export function renderCliSessionFiles(session) {
      const rows = session.files || [];
      if (!rows.length) return '';
      return `
        <div class="event-section" style="margin-bottom:14px">
          <h4>Files touched in this session (${formatInteger(rows.length)})</h4>
          <table>
            <thead><tr><th>File</th><th class="num">Created</th><th class="num">Edited</th><th class="num">Total touches</th><th>Last touched</th></tr></thead>
            <tbody>
              ${rows.map((row) => `<tr>
                <td><span class="note small" style="word-break:break-all">${escapeHtml(row.path)}</span></td>
                <td class="num">${formatInteger(row.created)}</td>
                <td class="num">${formatInteger(row.edited)}</td>
                <td class="num"><strong>${formatInteger(row.touches)}</strong></td>
                <td>${escapeHtml(formatTimestamp(row.lastTouched))}</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    }

    export function renderCliTurn(turn) {
      const userText = turn.userMessage || '(empty)';
      const assistantText = turn.assistantResponse || '(empty)';
      return `
        <details class="event-card">
          <summary class="event-summary-row">
            <div class="title-col">
              <div class="title-line">
                <span class="badge user">turn ${formatInteger(turn.turnIndex)}</span>
                <span class="title-text">${escapeHtml((turn.userMessage || '').slice(0, 90) || '(no user message)')}</span>
              </div>
              <div class="subtext">${escapeHtml(formatTimestamp(turn.timestamp))}</div>
            </div>
          </summary>
          <div class="event-body">
            <div class="split-grid">
              <div class="event-section"><h4>User</h4><pre>${escapeHtml(userText)}${turn.userMessageTruncated ? '\n…(truncated)' : ''}</pre></div>
              <div class="event-section"><h4>Assistant</h4><pre>${escapeHtml(assistantText)}${turn.assistantResponseTruncated ? '\n…(truncated)' : ''}</pre></div>
            </div>
          </div>
        </details>`;
    }

    export function setCliSearch(value) {
      STATE.cliSearch = value;
      STATE.cliPage = 1;
      renderApp();
    }

    export function setCliModelFilter(value) {
      STATE.cliModel = value;
      STATE.cliPage = 1;
      renderApp();
    }

    export function setCliFileSearch(value) {
      STATE.cliFileSearch = value;
      renderApp();
    }

    export function setCliPageSize(value) {
      STATE.cliPageSize = Number(value || 10);
      STATE.cliPage = 1;
      renderApp();
    }

    export function changeCliPage(delta) {
      STATE.cliPage = Math.max(1, (STATE.cliPage || 1) + delta);
      renderApp();
    }

    export function openCliFullChatModal(sessionId) {
      const cli = APP_DATA.cli || {};
      const session = (cli.sessions || []).find((item) => item.id === sessionId);
      const backdrop = document.getElementById('fullChatModalBackdrop');
      document.getElementById('fullChatModalTitle').textContent = session ? (session.repository || session.cwd || session.id) : 'Full chat';
      document.getElementById('fullChatModalSubtitle').textContent = session
        ? `${(session.models || []).join(', ') || 'unknown'} · ${formatTimestamp(session.lastActivity)} · ${formatInteger(session.callCount)} calls · ${formatInteger(session.turnCount)} turns`
        : '';
      const exportBtn = document.getElementById('fullChatExportBtn');
      if (exportBtn) exportBtn.onclick = () => exportCliSessionToJson(sessionId);
      const body = document.getElementById('fullChatModalContent');
      if (!session) {
        body.innerHTML = '<div class="note" style="padding:24px;text-align:center;color:var(--red)">CLI session not found.</div>';
        backdrop.classList.add('open');
        return;
      }
      const turns = [...(session.turns || [])].sort((a, b) => Number(a.turnIndex || 0) - Number(b.turnIndex || 0));
      const timeline = turns.length
        ? turns.map((turn) => renderCliTurn(turn)).join('')
        : '<div class="note">No conversation turns were recorded for this session.</div>';
      body.innerHTML = `
        ${renderCliSessionMeta(session)}
        ${renderCliModelBreakdown(session)}
        <div class="timeline">${timeline}</div>`;
      backdrop.classList.add('open');
    }

    export function exportCliSessionToJson(sessionId) {
      const cli = APP_DATA.cli || {};
      const session = (cli.sessions || []).find((item) => item.id === sessionId);
      if (!session) return;
      const safeName = (session.repository || session.cwd || session.id || 'cli-chat').replace(/[^a-zA-Z0-9._-]/g, '_').slice(0, 40);
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const blob = new Blob([JSON.stringify(session, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `cli-chat-${safeName}-${ts}.json`;
      a.click();
      URL.revokeObjectURL(url);
    }

    export function deleteCliSessionPrompt(sessionId) {
      const session = ((APP_DATA.cli || {}).sessions || []).find((item) => item.id === sessionId);
      if (!session) return;
      const title = (session.repository || session.cwd || session.id || 'this CLI session').slice(0, 90);
      if (!confirm(`Delete "${title}" from the CLI tab?`)) return;
      const changed = markCliSessionsHidden([sessionId]);
      if (changed) renderApp();
    }

    export function openCliModelCompareModal(sessionId) {
      const session = ((APP_DATA.cli || {}).sessions || []).find((s) => s.id === sessionId);
      if (!session) return;
      const inputTokens = session.input || 0;
      const cachedTokens = session.cached || 0;
      const outputTokens = session.output || 0;
      const actualModel = (session.models || [])[0] || 'unknown';
      const actualCost = session.cost || 0;
      const titleText = session.repository || session.cwd || session.id;

      document.getElementById('modelCompareModalTitle').textContent = 'Model cost comparison';
      document.getElementById('modelCompareModalSubtitle').textContent = titleText + ' · ' + formatInteger(inputTokens) + ' input · ' + formatInteger(outputTokens) + ' output tokens (session total)';

      const rows = Object.entries(PRICING_TABLE).map(([model, pricing]) => ({
        model,
        cost: calcModelCost(inputTokens, cachedTokens, outputTokens, pricing),
        pricing,
      })).sort((a, b) => a.cost - b.cost);

      const minCost = rows[0]?.cost || 0;

      document.getElementById('modelCompareModalContent').innerHTML = `
        <div class="note small" style="margin-bottom:12px">Estimated cost if this session's total token usage (<strong>${formatInteger(inputTokens)}</strong> input, <strong>${formatInteger(cachedTokens)}</strong> cached, <strong>${formatInteger(outputTokens)}</strong> output) was processed by each model. Assumes same cache hit pattern.</div>
        <div style="overflow-x:auto">
        <table>
          <thead><tr>
            <th>Model</th>
            <th class="num">Input $/M</th>
            <th class="num">Cached $/M</th>
            <th class="num">Output $/M</th>
            <th class="num">Est. Cost</th>
            <th class="num">vs actual</th>
          </tr></thead>
          <tbody>
            ${rows.map((row) => {
              const isActual = row.model === actualModel;
              const delta = row.cost - actualCost;
              const isCheapest = Math.abs(row.cost - minCost) < 0.000001;
              return `<tr style="${isActual ? 'background:rgba(88,166,255,0.08);border-left:2px solid var(--blue)' : ''}">
                <td><strong style="${isCheapest ? 'color:var(--green)' : ''}">${escapeHtml(row.model)}</strong>${isActual ? ' <span class="badge chat" style="font-size:0.65rem;padding:2px 6px">current</span>' : ''}${isCheapest ? ' <span class="badge mode-read" style="font-size:0.65rem;padding:2px 6px">cheapest</span>' : ''}</td>
                <td class="num">${formatCost(row.pricing.input)}</td>
                <td class="num">${formatCost(row.pricing.cached)}</td>
                <td class="num">${formatCost(row.pricing.output)}</td>
                <td class="num"><strong style="color:var(--teal)">${formatCost(row.cost)}</strong></td>
                <td class="num" style="color:${delta < -0.0001 ? 'var(--green)' : delta > 0.0001 ? 'var(--red)' : 'var(--muted)'}">${isActual ? '—' : (delta >= 0 ? '+' : '') + formatCost(Math.abs(delta))}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
        </div>`;

      document.getElementById('modelCompareModalBackdrop').classList.add('open');
    }

    // ---------------------------------------------------------------------
    // Bind every new inline onclick/onchange handler introduced in this
    // module onto `window`. This module owns web/js/tab-cli.js and cannot
    // edit web/js/app.js (see web/README.md's window-binding constraint),
    // so it self-registers here rather than relying on app.js's
    // Object.assign block. All handlers already present before this phase
    // (setCliSearch, changeCliPage, exportCliSessionToJson, etc.) remain
    // bound by app.js unchanged.
    // ---------------------------------------------------------------------
    Object.assign(window, {
      switchCliTrendGranularity,
      switchCliTrendMetric,
      copyCliSetupSnippet,
    });
