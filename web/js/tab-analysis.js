import { setFileSearch, setFileSort, setToolImpactSearch, setToolSort, setToolWasteSort, switchAnalysisTab, switchMonthlyTrendMetric, switchToolImpactTab } from './actions.js';
import { activeSummary, analysisForMode, cliMonthlyBuckets, monthlyTrendMetricConfig } from './aggregate.js';
import { renderApp } from './app.js';
import { renderGlobalTokenPieChart, renderMonthlyTrendChart } from './charts.js';
import { filterInsightsBySource } from './filters.js';
import { cacheHitRateForBlock, creditsFromCost, escapeHtml, formatCompact, formatCost, formatDuration, formatInteger, formatPercent, formatTimestamp, overheadLabel, sortArrow, summaryDisplayTotals } from './format.js';
import { openFileModal } from './modals.js';
import { APP_DATA, STATE, isBilledMode, tokenModeLabel } from './state.js';
import { registerTableExport, renderCsvExportButton, renderTable, sortFiles, sortRows } from './tables.js';

    // ---------------------------------------------------------------------
    // Global filter integration (window.CopilotFilters)
    //
    // Another agent publishes `window.CopilotFilters` (period/source/date
    // filtering) independently of this module. It may not exist yet or may
    // differ slightly from the agreed contract, so every access is guarded
    // with typeof checks, falling back to current unfiltered behavior.
    //
    // Scope note: several Analysis subtabs (Model usage, Tool impact, File
    // activity) are built from already-aggregated rows with no per-row
    // timestamp (a file's/tool's totals are summed across every session it
    // appeared in), so a date-range filter can't be meaningfully applied to
    // them without re-deriving that aggregation — that logic lives in
    // aggregate.js, which this module does not own/edit. Where a source or
    // period split IS honorable without touching aggregate.js, it is
    // applied below (source toggle on the chat/CLI split sections; period
    // range on rows that do carry a timestamp — Insights' "Expensive
    // chats"/"Slowest tools" cards and Monthly trends' month buckets).
    // ---------------------------------------------------------------------

    function getAnalysisFilterState() {
      const cf = window.CopilotFilters;
      if (!cf || typeof cf !== 'object') return { active: false };
      try {
        const current = typeof cf.currentFilters === 'function' ? cf.currentFilters() : null;
        const range = typeof cf.periodRange === 'function' ? cf.periodRange() : { start: null, end: null };
        return { active: true, cf, current, range };
      } catch (_err) {
        return { active: false };
      }
    }

    function sourceAllows(filterState, sourceKind) {
      if (!filterState.active || !filterState.current) return true;
      const activeSource = filterState.current.source;
      if (!activeSource || activeSource === 'all') return true;
      return activeSource === sourceKind;
    }

    function withinRange(filterState, timestampMs) {
      if (!filterState.active) return true;
      const { start, end } = filterState.range || {};
      const ts = Number(timestampMs || 0);
      if (!ts) return true;
      if (start !== null && start !== undefined && ts < start) return false;
      if (end !== null && end !== undefined && ts > end) return false;
      return true;
    }

    function analysisFilterLabel(filterState) {
      if (!filterState.active || !filterState.current) return '';
      const f = filterState.current || {};
      const parts = [];
      if (f.period) parts.push(f.period === 'custom' ? 'custom range' : f.period);
      if (f.source && f.source !== 'all') parts.push(`source: ${f.source}`);
      return parts.length ? ` · Global filters applied (${escapeHtml(parts.join(', '))})` : '';
    }


    export function analysisSubtabs() {
      const tabs = [
        ['models', 'Model usage'],
        ['tools', 'Tool impact'],
        ['files', 'File activity'],
        ['monthlyTrends', 'Monthly trends'],
        ['insights', 'Insights'],
      ];
      return `<div class="analysis-subtabs">${tabs.map(([id, label]) => `<button type="button" class="subtab-button ${STATE.analysisTab === id ? 'active' : ''}" onclick="switchAnalysisTab('${id}')">${escapeHtml(label)}</button>`).join('')}</div>`;
    }

    export function renderModelsSubtab() {
      const analysis = analysisForMode();
      const cli = APP_DATA.cli || {};
      const filterState = getAnalysisFilterState();
      const showChat = sourceAllows(filterState, 'chat');
      const showCli = sourceAllows(filterState, 'cli');
      const cliModelsSection = showCli && cli.available && (cli.byModel || []).length ? `
        <section class="panel" style="margin-top:16px">
          <h2 class="section-title">GitHub Copilot CLI – model usage</h2>
          <div class="section-subtitle">Separate cost pool from VS Code Copilot Chat (session-store.db totals).</div>
          ${renderTable([
            { title: 'Model', render: (row) => `<div><strong>${escapeHtml(row.name)}</strong><div class="note small">${formatInteger(row.calls)} calls</div></div>`, csv: (row) => row.name },
            { title: 'Input', numeric: true, render: (row) => `<span class="value input">${formatInteger(row.input)}</span>`, csv: (row) => row.input },
            { title: 'Cached-read input', numeric: true, render: (row) => `<span class="value cached">${formatInteger(row.cached)}</span>`, csv: (row) => row.cached },
            { title: 'Output', numeric: true, render: (row) => `<span class="value output">${formatInteger(row.output)}</span>`, csv: (row) => row.output },
            { title: 'Cost', numeric: true, render: (row) => `<span class="value cost">${formatCost(row.cost)}</span>`, csv: (row) => row.cost },
          ], cli.byModel || [], { exportId: 'analysis-cli-models', exportFilename: 'cli-model-usage.csv' })}
        </section>` : '';
      const chatModelsSection = showChat ? `
        <section class="panel">
          <h2 class="section-title">Model usage</h2>
          <div class="section-subtitle">These totals use <strong>${isBilledMode() ? 'billed per-call totals' : 'prompt-growth attribution'}</strong>. If a session switches models, each call is counted under the model that served it.${analysisFilterLabel(filterState)}</div>
          ${renderTable([
            { title: 'Model', render: (row) => `<div><strong>${escapeHtml(row.name)}</strong><div class="note small">${formatInteger(row.count)} chat calls across ${formatInteger(row.sessionCount)} sessions</div></div>`, csv: (row) => row.name },
            { title: 'Total input', numeric: true, render: (row) => `<span class="value input">${formatInteger(row.input)}</span>`, csv: (row) => row.input },
            { title: 'Uncached input', numeric: true, render: (row) => `<span class="value uncached">${formatInteger(row.uncached)}</span>`, csv: (row) => row.uncached },
            { title: 'Cached-read input', numeric: true, render: (row) => `<span class="value cached">${formatInteger(row.cached)}</span>`, csv: (row) => row.cached },
            { title: 'Output', numeric: true, render: (row) => `<span class="value output">${formatInteger(row.output)}</span>`, csv: (row) => row.output },
            { title: 'Cached share', numeric: true, render: (row) => formatPercent(row.cacheHitRate), csv: (row) => row.cacheHitRate },
            { title: 'Avg TTFT', numeric: true, render: (row) => formatDuration(row.avgTtftMs), csv: (row) => row.avgTtftMs },
            { title: 'Cost', numeric: true, render: (row) => `<span class="value cost">${formatCost(row.cost)}</span>`, csv: (row) => row.cost },
          ], analysis.models || [], { exportId: 'analysis-models', exportFilename: 'model-usage.csv' })}
        </section>` : `<div class="panel is-empty">Chat models hidden by the global source filter (showing CLI only).</div>`;
      return `${chatModelsSection}
        ${cliModelsSection}`;
    }

    export function renderToolImpactSubtabs() {
      const tabs = [
        ['usage', isBilledMode() ? 'Usage (billed est.)' : 'Usage attribution'],
        ['waste', 'Unused tool waste'],
      ];
      return `<div class="analysis-subtabs" style="margin-top:10px">${tabs.map(([id, label]) => `<button type="button" class="subtab-button ${STATE.toolImpactTab === id ? 'active' : ''}" onclick="switchToolImpactTab('${id}')">${escapeHtml(label)}</button>`).join('')}</div>`;
    }

    export function renderToolsUsageSubtab() {
      const analysis = analysisForMode();
      const search = (STATE.toolImpactSearch || '').trim().toLowerCase();
      const filteredTools = [...(analysis.tools || [])].filter((row) => {
        if (!search) return true;
        return String(row.name || '').toLowerCase().includes(search) || String(row.mode || '').toLowerCase().includes(search);
      });
      const tools = sortRows(filteredTools, STATE.toolSortKey || 'cost', STATE.toolSortDir || 'desc');
      function toolSortArrow(key) {
        if ((STATE.toolSortKey || 'cost') !== key) return '<span style="opacity:.4">↕</span>';
        return (STATE.toolSortDir || 'desc') === 'desc' ? '↓' : '↑';
      }
      function thBtn(key, line1, line2) {
        return `<th class="num"><button type="button" onclick="setToolSort('${key}')" style="all:unset;cursor:pointer;color:inherit;text-align:right;display:block;width:100%"><span style="display:block;line-height:1.2;font-size:.72rem">${line1}</span><span style="display:block;line-height:1.2;font-size:.72rem">${line2} ${toolSortArrow(key)}</span></button></th>`;
      }
      const totals = { count: 0, errors: 0, durationMs: 0, input: 0, output: 0, cached: 0, cost: 0, payloadTokens: 0 };
      tools.forEach(t => { totals.count += t.count; totals.errors += t.errors; totals.durationMs += t.durationMs; totals.input += t.input; totals.output += t.output; totals.cached += t.cached; totals.cost += t.cost; totals.payloadTokens += t.payloadTokens; });
      registerTableExport('analysis-tools-usage', [
        { title: 'Tool', csv: (row) => row.name },
        { title: 'Mode', csv: (row) => row.mode },
        { title: 'Calls', csv: (row) => row.count },
        { title: 'Errors', csv: (row) => row.errors },
        { title: 'Avg duration ms', csv: (row) => row.avgDurationMs },
        { title: 'Avg input', csv: (row) => row.avgInput },
        { title: 'Avg output', csv: (row) => row.avgOutput },
        { title: 'Avg cached', csv: (row) => row.avgCached },
        { title: 'Avg cost', csv: (row) => row.avgCost },
        { title: 'Total input', csv: (row) => row.input },
        { title: 'Total output', csv: (row) => row.output },
        { title: 'Total cached', csv: (row) => row.cached },
        { title: 'Total cost', csv: (row) => row.cost },
        { title: 'Avg payload', csv: (row) => row.avgPayloadTokens },
      ], tools, 'tool-usage.csv');
      return `
          <div class="section-subtitle">${isBilledMode() ? '<strong>Payload</strong> = approx token size of tool input + output text. In billed mode, tool/file splits are billed-adjusted estimates derived from attribution shares.' : '<strong>Payload</strong> = approx token size of tool input + output text, used as weight when splitting prompt growth.'}</div>
          <div style="display:flex;justify-content:flex-end;margin-bottom:8px">${renderCsvExportButton('analysis-tools-usage')}</div>
          <div class="table-scroll">
          <table>
            <thead><tr>
              <th><button type="button" onclick="setToolSort('name')" style="all:unset;cursor:pointer;color:inherit">Tool ${toolSortArrow('name')}</button></th>
              ${thBtn('count', 'Calls', '')}
              ${thBtn('avgDurationMs', 'Avg', 'Duration')}
              ${thBtn('avgInput', 'Avg', 'Input')}
              ${thBtn('avgOutput', 'Avg', 'Output')}
              ${thBtn('avgCached', 'Avg', 'Cached')}
              ${thBtn('avgCost', 'Avg', 'Cost')}
              ${thBtn('input', 'Total', 'Input')}
              ${thBtn('output', 'Total', 'Output')}
              ${thBtn('cached', 'Total', 'Cached')}
              ${thBtn('cost', 'Total', 'Cost')}
              ${thBtn('avgPayloadTokens', 'Avg', 'Payload')}
            </tr></thead>
            <tbody>
              ${tools.length ? tools.map(row => `<tr>
                <td><div><strong>${escapeHtml(row.name)}</strong><div class="pill-list"><span class="pill">${escapeHtml(row.mode)}</span><span class="pill">${formatInteger(row.errors)} err</span></div></div></td>
                <td class="num">${formatInteger(row.count)}</td>
                <td class="num">${formatDuration(row.avgDurationMs)}</td>
                <td class="num"><span class="value input">${formatInteger(row.avgInput)}</span></td>
                <td class="num"><span class="value output">${formatInteger(row.avgOutput)}</span></td>
                <td class="num"><span class="value cached">${formatInteger(row.avgCached)}</span></td>
                <td class="num"><span class="value cost">${formatCost(row.avgCost)}</span></td>
                <td class="num"><span class="value input">${formatCompact(row.input)}</span></td>
                <td class="num"><span class="value output">${formatCompact(row.output)}</span></td>
                <td class="num"><span class="value cached">${formatCompact(row.cached)}</span></td>
                <td class="num"><span class="value cost">${formatCost(row.cost)}</span></td>
                <td class="num">${formatInteger(row.avgPayloadTokens)}</td>
              </tr>`).join('') : `<tr><td colspan="12" class="note">No tools matched your search.</td></tr>`}
              <tr style="border-top:2px solid var(--border);font-weight:700">
                <td>TOTAL</td>
                <td class="num">${formatInteger(totals.count)}</td>
                <td class="num">${formatDuration(totals.durationMs / (totals.count || 1))}</td>
                <td class="num"><span class="value input">${formatInteger(totals.input / (totals.count || 1))}</span></td>
                <td class="num"><span class="value output">${formatInteger(totals.output / (totals.count || 1))}</span></td>
                <td class="num"><span class="value cached">${formatInteger(totals.cached / (totals.count || 1))}</span></td>
                <td class="num"><span class="value cost">${formatCost(totals.cost / (totals.count || 1))}</span></td>
                <td class="num"><span class="value input">${formatCompact(totals.input)}</span></td>
                <td class="num"><span class="value output">${formatCompact(totals.output)}</span></td>
                <td class="num"><span class="value cached">${formatCompact(totals.cached)}</span></td>
                <td class="num"><span class="value cost">${formatCost(totals.cost)}</span></td>
                <td class="num">${formatInteger(totals.payloadTokens / (totals.count || 1))}</td>
              </tr>
            </tbody>
          </table>
          </div>`;
    }

    export function renderToolWasteSubtab() {
      const analysis = analysisForMode();
      const search = (STATE.toolImpactSearch || '').trim().toLowerCase();
      const filteredRows = [...(analysis.toolCatalog || [])].filter((row) => {
        if (!search) return true;
        return String(row.name || '').toLowerCase().includes(search) || String(row.description || '').toLowerCase().includes(search);
      });
      const rows = sortRows(filteredRows, STATE.toolWasteSortKey || 'wastedInputTokens', STATE.toolWasteSortDir || 'desc');
      function arrow(key) {
        if ((STATE.toolWasteSortKey || 'wastedInputTokens') !== key) return '<span style="opacity:.4">↕</span>';
        return (STATE.toolWasteSortDir || 'desc') === 'desc' ? '↓' : '↑';
      }
      function th(key, label, numeric) {
        return `<th class="${numeric ? 'num' : ''}"><button type="button" onclick="setToolWasteSort('${key}')" style="all:unset;cursor:pointer;color:inherit;display:block;width:100%;text-align:${numeric ? 'right' : 'left'}">${label} ${arrow(key)}</button></th>`;
      }
      const totals = rows.reduce((acc, row) => {
        acc.present += Number(row.presentCount || 0);
        acc.unused += Number(row.unusedPresentCount || 0);
        acc.wastedInput += Number(row.wastedInputTokens || 0);
        acc.wastedUncached += Number(row.wastedUncachedTokens || 0);
        acc.wastedCached += Number(row.wastedCachedTokens || 0);
        return acc;
      }, { present: 0, unused: 0, wastedInput: 0, wastedUncached: 0, wastedCached: 0 });
      const totalWastePercent = totals.present ? (totals.unused / totals.present * 100) : 0;
      registerTableExport('analysis-tools-waste', [
        { title: 'Tool', csv: (row) => row.name },
        { title: 'Description tokens', csv: (row) => row.descriptionTokens },
        { title: 'Present in calls', csv: (row) => row.presentCount },
        { title: 'Actual calls', csv: (row) => row.callCount },
        { title: 'Unused passes', csv: (row) => row.unusedPresentCount },
        { title: 'Waste %', csv: (row) => row.wastePercent },
        { title: 'Waste total input', csv: (row) => row.wastedInputTokens },
        { title: 'Waste uncached input', csv: (row) => row.wastedUncachedTokens },
        { title: 'Waste cached-read input', csv: (row) => row.wastedCachedTokens },
        { title: 'Sessions', csv: (row) => row.sessionCount },
        { title: 'Tool sets', csv: (row) => row.toolSetCount },
      ], rows, 'tool-waste.csv');
      return `
        <div class="section-subtitle"><strong>Waste</strong> estimates the description tokens for a tool each time that tool was present in the model toolset but was not called by that LLM response. Cached/uncached split is estimated from that call's observed cache-read ratio.${isBilledMode() ? ' In billed mode, these totals are billed-adjusted estimates.' : ''}</div>
        <div style="display:flex;justify-content:flex-end;margin-bottom:8px">${renderCsvExportButton('analysis-tools-waste')}</div>
        <div class="table-scroll">
        <table>
          <thead><tr>
            ${th('name', 'Tool', false)}
            ${th('descriptionTokens', 'Description tokens', true)}
            ${th('presentCount', 'Present in calls', true)}
            ${th('callCount', 'Actual calls', true)}
            ${th('unusedPresentCount', 'Unused passes', true)}
            ${th('wastePercent', 'Waste %', true)}
            ${th('wastedInputTokens', 'Waste total input', true)}
            ${th('wastedUncachedTokens', 'Waste uncached input', true)}
            ${th('wastedCachedTokens', 'Waste cached-read input', true)}
            ${th('sessionCount', 'Sessions', true)}
            ${th('toolSetCount', 'Tool sets', true)}
          </tr></thead>
          <tbody>
            ${rows.length ? rows.map(row => `<tr>
              <td><details><summary><strong>${escapeHtml(row.name)}</strong></summary><pre>${escapeHtml(row.description || '[No description captured for this tool.]')}</pre></details></td>
              <td class="num">${formatInteger(row.descriptionTokens || 0)}</td>
              <td class="num">${formatInteger(row.presentCount || 0)}</td>
              <td class="num">${formatInteger(row.callCount || 0)}</td>
              <td class="num">${formatInteger(row.unusedPresentCount || 0)}</td>
              <td class="num">${formatPercent(row.wastePercent || 0)}</td>
              <td class="num"><span class="value input">${formatCompact(row.wastedInputTokens || 0)}</span></td>
              <td class="num"><span class="value uncached">${formatCompact(row.wastedUncachedTokens || 0)}</span></td>
              <td class="num"><span class="value cached">${formatCompact(row.wastedCachedTokens || 0)}</span></td>
              <td class="num">${formatInteger(row.sessionCount || 0)}</td>
              <td class="num">${formatInteger(row.toolSetCount || 0)}</td>
            </tr>`).join('') : `<tr><td colspan="11" class="note">No tools matched your search.</td></tr>`}
            <tr style="border-top:2px solid var(--border);font-weight:700">
              <td>TOTAL</td>
              <td class="num"></td>
              <td class="num">${formatInteger(totals.present)}</td>
              <td class="num"></td>
              <td class="num">${formatInteger(totals.unused)}</td>
              <td class="num">${formatPercent(totalWastePercent)}</td>
              <td class="num"><span class="value input">${formatCompact(totals.wastedInput)}</span></td>
              <td class="num"><span class="value uncached">${formatCompact(totals.wastedUncached)}</span></td>
              <td class="num"><span class="value cached">${formatCompact(totals.wastedCached)}</span></td>
              <td class="num"></td>
              <td class="num"></td>
            </tr>
          </tbody>
        </table>
        </div>`;
    }

    export function renderCliToolImpactSection() {
      const cli = APP_DATA.cli || {};
      if (!sourceAllows(getAnalysisFilterState(), 'cli')) return '';
      if (!cli.otelAvailable || !(cli.tools || []).length) return '';
      return `
        <section class="panel" style="margin-top:16px">
          <h2 class="section-title">GitHub Copilot CLI – tool impact</h2>
          <div class="section-subtitle">From native OpenTelemetry <code>execute_tool</code> spans. Calls/duration only — no token/cost figures (CLI's session-store.db does not attribute tokens per tool).</div>
          ${renderTable([
            { title: 'Tool', render: (row) => `<strong>${escapeHtml(row.tool)}</strong>`, csv: (row) => row.tool },
            { title: 'Calls', numeric: true, render: (row) => formatInteger(row.calls), csv: (row) => row.calls },
            { title: 'Sessions', numeric: true, render: (row) => formatInteger(row.sessionCount), csv: (row) => row.sessionCount },
            { title: 'Avg duration', numeric: true, render: (row) => formatDuration(row.avgDurationMs), csv: (row) => row.avgDurationMs },
            { title: 'Total duration', numeric: true, render: (row) => formatDuration(row.totalDurationMs), csv: (row) => row.totalDurationMs },
          ], cli.tools || [], { exportId: 'analysis-cli-tools', exportFilename: 'cli-tool-impact.csv' })}
        </section>`;
    }

    export function renderToolsSubtab() {
      const filterState = getAnalysisFilterState();
      if (!sourceAllows(filterState, 'chat')) {
        return `<div class="panel is-empty">Chat tool impact hidden by the global source filter (showing CLI only).</div>${renderCliToolImpactSection()}`;
      }
      return `
        <section class="panel">
          <h2 class="section-title">Tool impact</h2>
          <div class="tool-catalog-controls">
            <input type="text" id="toolImpactSearchInput" placeholder="Search tools by name/mode/description…" value="${escapeHtml(STATE.toolImpactSearch)}" oninput="setToolImpactSearch(this.value)">
          </div>
          ${analysisFilterLabel(filterState) ? `<div class="note small">${analysisFilterLabel(filterState)}</div>` : ''}
          ${renderToolImpactSubtabs()}
          ${STATE.toolImpactTab === 'waste' ? renderToolWasteSubtab() : renderToolsUsageSubtab()}
        </section>
        ${renderCliToolImpactSection()}`;
    }

    export function renderFilesSubtab() {
      const analysis = analysisForMode();
      const filterState = getAnalysisFilterState();
      if (!sourceAllows(filterState, 'chat')) {
        return `<div class="panel is-empty">Chat file activity hidden by the global source filter (showing CLI only).</div>${renderCliFilesSection()}`;
      }
      const search = (STATE.fileSearch || '').trim().toLowerCase();
      const filtered = [...(analysis.files || [])].filter((row) => {
        if (!search) return true;
        const tools = (row.tools || []).join(' ').toLowerCase();
        return String(row.name || '').toLowerCase().includes(search)
          || String(row.path || '').toLowerCase().includes(search)
          || String(row.shortPath || '').toLowerCase().includes(search)
          || tools.includes(search);
      });
      const rows = sortFiles(filtered);
      const columns = [
        ['name', 'File'],
        ['readCount', 'Reads'],
        ['editCount', 'Edits'],
        ['avgInput', 'Avg Input'],
        ['avgOutput', 'Avg Output'],
        ['avgCached', 'Avg Cached'],
        ['input', 'Total Input'],
        ['output', 'Total Output'],
        ['cached', 'Total Cached'],
        ['payloadTokens', 'Payload'],
        ['avgCost', 'Avg Cost'],
        ['cost', 'Cost'],
      ];
      registerTableExport('analysis-files', columns.map(([key, label]) => ({ title: label, csv: (row) => row[key] })), rows, 'file-activity.csv');
      const fileTotals = { readCount: 0, editCount: 0, input: 0, output: 0, cached: 0, cost: 0, payloadTokens: 0 };
      rows.forEach(r => { fileTotals.readCount += r.readCount; fileTotals.editCount += r.editCount; fileTotals.input += r.input; fileTotals.output += r.output; fileTotals.cached += r.cached; fileTotals.cost += r.cost; fileTotals.payloadTokens += r.payloadTokens; });
      const totalOps = fileTotals.readCount + fileTotals.editCount;
      return `
        <section class="panel">
          <h2 class="section-title">File activity</h2>
          <div class="section-subtitle">Click a file to see per-tool usage summary. ${isBilledMode() ? 'Values are billed-adjusted estimates based on observed attribution shares.' : 'Long paths shortened; hover for full path.'}${analysisFilterLabel(filterState)}</div>
          <div class="tool-catalog-controls" style="justify-content:space-between">
            <input type="text" id="fileSearchInput" placeholder="Search files by name/path/tool…" value="${escapeHtml(STATE.fileSearch)}" oninput="setFileSearch(this.value)">
            ${renderCsvExportButton('analysis-files')}
          </div>
          <div class="table-scroll">
          <table class="table-collapse">
            <thead>
              <tr>
                ${columns.map(([key, label]) => `<th class="${key !== 'name' ? 'num' : ''}"><button type="button" onclick="setFileSort('${key}')" style="all:unset;cursor:pointer;color:inherit">${escapeHtml(label)} ${sortArrow(key)}</button></th>`).join('')}
              </tr>
            </thead>
            <tbody>
              ${rows.map((row) => `<tr class="clickable-row" onclick="openFileModal('${encodeURIComponent(row.path)}')">
                <td data-label="File"><div title="${escapeHtml(row.path)}"><strong>${escapeHtml(row.name)}</strong></div></td>
                <td class="num" data-label="Reads">${formatInteger(row.readCount)}</td>
                <td class="num" data-label="Edits">${formatInteger(row.editCount)}</td>
                <td class="num" data-label="Avg Input"><span class="value input">${formatInteger(row.avgInput)}</span></td>
                <td class="num" data-label="Avg Output"><span class="value output">${formatInteger(row.avgOutput)}</span></td>
                <td class="num" data-label="Avg Cached"><span class="value cached">${formatInteger(row.avgCached)}</span></td>
                <td class="num" data-label="Total Input"><span class="value input">${formatCompact(row.input)}</span></td>
                <td class="num" data-label="Total Output"><span class="value output">${formatCompact(row.output)}</span></td>
                <td class="num" data-label="Total Cached"><span class="value cached">${formatCompact(row.cached)}</span></td>
                <td class="num" data-label="Payload">${formatInteger(row.payloadTokens)}</td>
                <td class="num" data-label="Avg Cost"><span class="value cost">${formatCost(row.avgCost)}</span></td>
                <td class="num" data-label="Cost"><span class="value cost">${formatCost(row.cost)}</span></td>
              </tr>`).join('')}
              <tr style="border-top:2px solid var(--border);font-weight:700">
                <td>TOTAL (${rows.length} files)</td>
                <td class="num">${formatInteger(fileTotals.readCount)}</td>
                <td class="num">${formatInteger(fileTotals.editCount)}</td>
                <td class="num"><span class="value input">${formatInteger(totalOps ? fileTotals.input / totalOps : 0)}</span></td>
                <td class="num"><span class="value output">${formatInteger(totalOps ? fileTotals.output / totalOps : 0)}</span></td>
                <td class="num"><span class="value cached">${formatInteger(totalOps ? fileTotals.cached / totalOps : 0)}</span></td>
                <td class="num"><span class="value input">${formatCompact(fileTotals.input)}</span></td>
                <td class="num"><span class="value output">${formatCompact(fileTotals.output)}</span></td>
                <td class="num"><span class="value cached">${formatCompact(fileTotals.cached)}</span></td>
                <td class="num">${formatInteger(fileTotals.payloadTokens)}</td>
                <td class="num"><span class="value cost">${formatCost(totalOps ? fileTotals.cost / totalOps : 0)}</span></td>
                <td class="num"><span class="value cost">${formatCost(fileTotals.cost)}</span></td>
              </tr>
            </tbody>
          </table>
          </div>
        </section>
        ${renderCliFilesSection()}`;
    }

    export function renderCliFilesSection() {
      const cli = APP_DATA.cli || {};
      if (!sourceAllows(getAnalysisFilterState(), 'cli')) return '';
      const cliFiles = (cli.files || []).slice(0, 20);
      if (!cli.available || !cliFiles.length) return '';
      return `
        <section class="panel" style="margin-top:16px">
          <h2 class="section-title">GitHub Copilot CLI – file activity <span class="note small" style="font-weight:400">(top ${cliFiles.length} of ${formatInteger((cli.files || []).length)})</span></h2>
          <div class="section-subtitle">Files touched via CLI sessions (create/edit tool calls), aggregated across all sessions. See the CLI tab for the per-session breakdown.</div>
          ${renderTable([
            { title: 'File', render: (row) => `<div title="${escapeHtml(row.path)}"><strong>${escapeHtml(row.path.split('/').pop() || row.path)}</strong></div>`, csv: (row) => row.path },
            { title: 'Created', numeric: true, render: (row) => formatInteger(row.created), csv: (row) => row.created },
            { title: 'Edited', numeric: true, render: (row) => formatInteger(row.edited), csv: (row) => row.edited },
            { title: 'Total touches', numeric: true, render: (row) => formatInteger(row.touches), csv: (row) => row.touches },
            { title: 'Sessions', numeric: true, render: (row) => formatInteger(row.sessionCount), csv: (row) => row.sessionCount },
          ], cliFiles, { exportId: 'analysis-cli-files', exportFilename: 'cli-file-activity.csv' })}
        </section>`;
    }

    function monthKeyToMs(monthKey) {
      if (!monthKey) return null;
      const t = new Date(`${monthKey}-01T00:00:00`).getTime();
      return Number.isFinite(t) ? t : null;
    }

    export function renderMonthlyTrendsSubtab() {
      const analysis = analysisForMode();
      const filterState = getAnalysisFilterState();
      const allRows = [...(analysis.monthlyTrends || [])].sort((a, b) => String(a.monthKey || '').localeCompare(String(b.monthKey || '')));
      const rows = filterState.active ? allRows.filter((row) => withinRange(filterState, monthKeyToMs(row.monthKey))) : allRows;
      const cliBuckets = cliMonthlyBuckets();
      const cliHasData = sourceAllows(filterState, 'cli') && Object.keys(cliBuckets).length > 0;
      if (!rows.length) {
        return `<section class="panel"><h2 class="section-title">Monthly trends</h2><div class="is-empty">No monthly data found for the current global filters. Try widening the period or switching source back to "All".</div></section>`;
      }

      const metricConfig = monthlyTrendMetricConfig();
      const metricKey = metricConfig[STATE.monthlyTrendMetric] ? STATE.monthlyTrendMetric : 'cost';
      const metric = metricConfig[metricKey];
      const latest = rows[rows.length - 1];
      const previous = rows.length > 1 ? rows[rows.length - 2] : null;
      const latestValue = Number(metric.value(latest) || 0);
      const previousValue = Number(previous ? metric.value(previous) : 0);
      const delta = latestValue - previousValue;
      const deltaPercent = previous ? (previousValue ? (delta / previousValue) * 100 : null) : null;
      const deltaSign = delta > 0 ? '+' : '';
      const comparisonValue = previous ? escapeHtml(metric.format(previousValue)) : '';
      const deltaLabel = metric.isRate
        ? `${delta > 0 ? '+' : ''}${delta.toFixed(1)} pp`
        : `${deltaSign}${escapeHtml(metric.format(Math.abs(delta)))}${deltaPercent === null ? '' : `, ${deltaPercent > 0 ? '+' : ''}${deltaPercent.toFixed(1)}%`}`;

      registerTableExport('analysis-monthly-trends', [
        { title: 'Month', csv: (row) => row.label || row.monthKey },
        { title: 'Sessions', csv: (row) => row.sessionCount },
        { title: 'Chat calls', csv: (row) => row.chatCallCount },
        { title: 'Tool calls', csv: (row) => row.toolCallCount },
        { title: 'Input', csv: (row) => row.totals?.input },
        { title: 'Uncached', csv: (row) => row.totals?.uncached },
        { title: 'Cached', csv: (row) => row.totals?.cached },
        { title: 'Output', csv: (row) => row.totals?.output },
        { title: 'Cost', csv: (row) => row.totals?.cost },
        { title: 'Cache hit %', csv: (row) => row.cacheHitRate },
        ...(cliHasData ? [
          { title: 'CLI sessions', csv: (row) => (cliBuckets[row.monthKey] || {}).sessionCount },
          { title: 'CLI cost', csv: (row) => (cliBuckets[row.monthKey] || {}).cost },
        ] : []),
      ], rows, 'monthly-trends.csv');

      return `
        <section class="panel">
          <h2 class="section-title">Monthly trends</h2>
          <div class="section-subtitle">Track month-over-month progress across usage, cost, and efficiency patterns (${escapeHtml(tokenModeLabel())} mode).${analysisFilterLabel(filterState)}</div>
          <div class="analysis-subtabs">
            ${Object.entries(metricConfig).map(([key, cfg]) => `<button type="button" class="subtab-button ${metricKey === key ? 'active' : ''}" onclick="switchMonthlyTrendMetric('${key}')">${escapeHtml(cfg.short)}</button>`).join('')}
          </div>
          <div class="note" style="margin-bottom:10px">
            Latest (${escapeHtml(latest.label || latest.monthKey || 'current month')}): <strong>${escapeHtml(metric.format(latestValue))}</strong>
            ${previous ? ` · vs ${escapeHtml(previous.label || previous.monthKey || 'previous month')}: <strong style="color:${delta < 0 ? 'var(--green)' : delta > 0 ? 'var(--red)' : 'var(--muted)'}">${comparisonValue}</strong>${deltaLabel ? ` (${deltaLabel})` : ''}` : ''}
          </div>
          ${renderMonthlyTrendChart(rows, metricKey)}
          <div style="display:flex;justify-content:flex-end;margin-top:12px">${renderCsvExportButton('analysis-monthly-trends')}</div>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Month</th>
                  <th class="num">Sessions</th>
                  <th class="num">Chat calls</th>
                  <th class="num">Tool calls</th>
                  <th class="num">Input</th>
                  <th class="num">Uncached</th>
                  <th class="num">Cached</th>
                  <th class="num">Output</th>
                  <th class="num">Cost</th>
                  <th class="num">Cache hit</th>
                  ${cliHasData ? '<th class="num">CLI sessions</th><th class="num">CLI cost</th>' : ''}
                </tr>
              </thead>
              <tbody>
                ${rows.map((row) => `<tr>
                  <td>${escapeHtml(row.label || row.monthKey || '—')}</td>
                  <td class="num">${formatInteger(row.sessionCount || 0)}</td>
                  <td class="num">${formatInteger(row.chatCallCount || 0)}</td>
                  <td class="num">${formatInteger(row.toolCallCount || 0)}</td>
                  <td class="num"><span class="value input">${formatCompact(row.totals?.input || 0)}</span></td>
                  <td class="num"><span class="value uncached">${formatCompact(row.totals?.uncached || 0)}</span></td>
                  <td class="num"><span class="value cached">${formatCompact(row.totals?.cached || 0)}</span></td>
                  <td class="num"><span class="value output">${formatCompact(row.totals?.output || 0)}</span></td>
                  <td class="num"><span class="value cost">${formatCost(row.totals?.cost || 0)}</span></td>
                  <td class="num">${formatPercent(row.cacheHitRate || 0)}</td>
                  ${cliHasData ? `<td class="num">${formatInteger((cliBuckets[row.monthKey] || {}).sessionCount || 0)}</td><td class="num"><span class="value cost">${formatCost((cliBuckets[row.monthKey] || {}).cost || 0)}</span></td>` : ''}
                </tr>`).join('')}
              </tbody>
            </table>
          </div>
          ${cliHasData ? '<div class="note small" style="margin-top:8px">CLI sessions/cost columns come from GitHub Copilot CLI usage (session-store.db), bucketed by month and shown alongside VS Code Copilot Chat trends for a whole-project view.</div>' : ''}
        </section>`;
    }

    // ---------------------------------------------------------------------
    // Recommendations (APP_DATA.insights) — Phase 6 front-end.
    // ---------------------------------------------------------------------

    // Insights-local filter state only. Source deliberately does NOT live here:
    // it is owned by the global filter bar (filters.js
    // `filterInsightsBySource`) so this panel and Overview's "Top
    // recommendations" can never show a different set of findings. Severity and
    // savingsOnly are recommendation-specific concepts with no global
    // equivalent, so they stay local.
    function ensureInsightFilterState() {
      if (!STATE.insightFilters || typeof STATE.insightFilters !== 'object') {
        STATE.insightFilters = { severity: 'all', savingsOnly: false };
      }
      return STATE.insightFilters;
    }

    function insightSeverityStateClass(severity) {
      if (severity === 'critical') return 'state-critical';
      if (severity === 'warn') return 'state-warn';
      return 'state-ok';
    }

    function insightConfidenceBadgeClass(confidence) {
      if (confidence === 'high') return 'confidence-high';
      if (confidence === 'medium') return 'confidence-medium';
      return 'confidence-low';
    }

    function humanizeEvidenceKey(key) {
      return String(key || '')
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .replace(/^./, (c) => c.toUpperCase());
    }

    function formatEvidenceValue(key, value) {
      if (value === null || value === undefined || value === '') return '—';
      if (Array.isArray(value)) return value.length ? value.join(', ') : '—';
      const lowerKey = String(key || '').toLowerCase();
      if (typeof value === 'number') {
        if (lowerKey.includes('cost')) return formatCost(value);
        if (lowerKey.includes('percent') || lowerKey.includes('rate') || lowerKey.includes('fraction')) {
          return lowerKey.includes('fraction') ? formatPercent(value * 100) : formatPercent(value);
        }
        if (lowerKey.includes('timestamp') || lowerKey.endsWith('ts')) return formatTimestamp(value);
        return formatInteger(value);
      }
      return String(value);
    }

    // Evidence rows are flat dicts (see insights_engine.py); when every row
    // in one insight's evidence array shares the same keys, render an
    // actual table (readable, sortable-by-eye). Irregular shapes (rare —
    // only the neutral chat-vs-cli comparison insight mixes differing rows
    // today) fall back to a per-row key/value list instead of guessing a
    // column layout that would drop data.
    function renderEvidenceBlock(evidence, insightId) {
      if (!Array.isArray(evidence) || !evidence.length) {
        return '<div class="note small">No supporting evidence was attached to this finding.</div>';
      }
      const keySets = evidence.map((row) => Object.keys(row || {}));
      const firstKeys = keySets[0];
      const sameShape = keySets.every((keys) => keys.length === firstKeys.length && keys.every((k) => firstKeys.includes(k)));
      if (sameShape) {
        return `
          <div class="table-scroll">
            <table class="rollup-table table-collapse">
              <thead><tr>${firstKeys.map((k) => `<th>${escapeHtml(humanizeEvidenceKey(k))}</th>`).join('')}</tr></thead>
              <tbody>
                ${evidence.map((row) => `<tr>${firstKeys.map((k) => `<td data-label="${escapeHtml(humanizeEvidenceKey(k))}">${escapeHtml(formatEvidenceValue(k, row[k]))}</td>`).join('')}</tr>`).join('')}
              </tbody>
            </table>
          </div>`;
      }
      return evidence.map((row, idx) => `
        <div class="meta-card" style="margin-bottom:8px">
          <div class="label">Evidence row ${idx + 1}</div>
          <ul class="help-list">
            ${Object.entries(row || {}).map(([k, v]) => `<li><strong>${escapeHtml(humanizeEvidenceKey(k))}:</strong> ${escapeHtml(formatEvidenceValue(k, v))}</li>`).join('')}
          </ul>
        </div>`).join('');
    }

    function insightSourceLabel(source) {
      if (source === 'chat') return 'Chat';
      if (source === 'cli') return 'CLI';
      return 'Both';
    }

    function renderRecommendationCard(insight, index) {
      const sevClass = insightSeverityStateClass(insight.severity);
      const savings = insight.estimatedSavings || {};
      const hasSavings = Number(savings.cost || 0) > 0 || Number(savings.premiumRequests || 0) > 0;
      const evidenceCount = Array.isArray(insight.evidence) ? insight.evidence.length : 0;
      return `
        <div class="insight-card ${sevClass}" data-insight-id="${escapeHtml(insight.id || '')}">
          <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap">
            <h4 style="margin:0">${escapeHtml(insight.title || 'Untitled finding')}</h4>
            <div class="pill-list">
              <span class="badge source">${escapeHtml(insightSourceLabel(insight.source))}</span>
              <span class="badge ${insightConfidenceBadgeClass(insight.confidence)}">${escapeHtml(String(insight.confidence || 'low').toUpperCase())} confidence</span>
            </div>
          </div>
          <p class="note" style="margin:10px 0 0">${escapeHtml(insight.detail || '')}</p>
          <div class="note small" style="margin-top:10px"><strong>Recommended action:</strong> ${escapeHtml(insight.action || '—')}</div>
          ${hasSavings ? `
          <div class="pill-list" style="margin-top:10px;">
            ${Number(savings.cost || 0) > 0 ? `<span class="pill">Est. saving ${escapeHtml(formatCost(savings.cost))}</span>` : ''}
            ${Number(savings.cost || 0) > 0 ? `<span class="pill">${escapeHtml(creditsFromCost(savings.cost).toFixed(0))} AI credits</span>` : ''}
            ${Number(savings.premiumRequests || 0) > 0 ? `<span class="pill" title="Legacy meter: annual request-billed Pro/Pro+ only.">${escapeHtml(formatInteger(savings.premiumRequests))} premium req. (legacy)</span>` : ''}
          </div>` : `<div class="note small" style="margin-top:10px">Informational — no quantifiable saving.</div>`}
          <details style="margin-top:10px" id="insight-evidence-${index}">
            <summary class="note small">Evidence (${formatInteger(evidenceCount)})</summary>
            <div style="margin-top:8px">${renderEvidenceBlock(insight.evidence, insight.id)}</div>
          </details>
        </div>`;
    }

    // Global source filter first (authoritative), then the two local controls.
    // Returns the hidden cross-source count too so the panel can report what
    // the source filter removed rather than silently shrinking the list.
    function filteredInsights() {
      const state = ensureInsightFilterState();
      const scoped = filterInsightsBySource(APP_DATA.insights);
      const visible = scoped.visible.filter((insight) => {
        if (state.severity !== 'all' && insight.severity !== state.severity) return false;
        if (state.savingsOnly) {
          const savings = insight.estimatedSavings || {};
          if (!(Number(savings.cost || 0) > 0 || Number(savings.premiumRequests || 0) > 0)) return false;
        }
        return true;
      });
      return { visible, hiddenCrossSource: scoped.hiddenCrossSource, source: scoped.source };
    }

    function filteredInsightsList() {
      return filteredInsights().visible;
    }

    function renderRecommendationsPanel() {
      const state = ensureInsightFilterState();
      const allInsights = Array.isArray(APP_DATA.insights) ? APP_DATA.insights : [];
      const { visible, hiddenCrossSource, source: activeSource } = filteredInsights();
      const totalCost = visible.reduce((acc, i) => acc + Number((i.estimatedSavings || {}).cost || 0), 0);
      const totalPremium = visible.reduce((acc, i) => acc + Number((i.estimatedSavings || {}).premiumRequests || 0), 0);

      if (!allInsights.length) {
        return `
          <section class="panel is-empty">
            <div style="font-size:1.4rem">✓</div>
            <div><strong>No recommendations fired for this data.</strong></div>
            <div class="note small">This dashboard's insights engine only surfaces a finding when a deterministic rule's threshold is actually crossed (see the Info tab for how thresholds are configured) — an empty list here means nothing in the current usage data looked wasteful, risky, or worth flagging, not a broken feature.</div>
          </section>`;
      }

      const severityOptions = [['all', 'All severities'], ['critical', 'Critical'], ['warn', 'Warn'], ['info', 'Info']];
      const sourceLabel = activeSource === 'cli' ? 'CLI' : activeSource === 'chat' ? 'Chat' : 'all sources';

      const cards = visible.length
        ? `<div class="insights-grid">${visible.map((insight, idx) => renderRecommendationCard(insight, idx)).join('')}</div>`
        : `<div class="is-empty">No recommendations match the current filters. Try another severity, set the source filter above to <strong>All</strong>, or uncheck "only show insights with an estimated saving".</div>`;

      return `
        <section class="panel">
          <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:14px;align-items:flex-start">
            <div>
              <h2 class="section-title" style="margin-bottom:2px">Recommendations</h2>
              <div class="section-subtitle" style="margin-bottom:0">${formatInteger(allInsights.length)} deterministic, evidence-backed finding(s) computed from <strong>all</strong> parsed usage data — no LLM calls, always reproducible from the same data. The global source filter applies here; the period filter does not, because the rules run once over the whole dataset when the dashboard is generated.</div>
            </div>
            <div style="text-align:right">
              <div class="label" style="color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.04em">Estimated savings available</div>
              <div style="font-size:1.3rem;font-weight:700" class="value cost">${escapeHtml(formatCost(totalCost))}${totalPremium ? ` <span class="note small" style="font-weight:400">= ${escapeHtml(creditsFromCost(totalCost).toFixed(0))} AI credits</span>` : ''}</div>
            </div>
          </div>
          <div class="filter-bar" style="margin-top:14px;margin-bottom:0;align-items:center">
            <div class="segmented-control" role="group" aria-label="Filter recommendations by severity">
              ${severityOptions.map(([value, label]) => `<button type="button" class="subtab-button ${state.severity === value ? 'active' : ''}" onclick="setInsightSeverityFilter('${value}')">${escapeHtml(label)}</button>`).join('')}
            </div>
            <label class="note small" style="display:flex;align-items:center;gap:6px;min-height:44px">
              <input type="checkbox" ${state.savingsOnly ? 'checked' : ''} onchange="setInsightSavingsOnly(this.checked)"> Only show insights with an estimated saving
            </label>
            <button type="button" class="copy-button" onclick="copyInsightsMarkdown(this)">📋 Copy summary as Markdown</button>
          </div>
          <div class="note small" style="margin-top:12px">${formatInteger(visible.length)} of ${formatInteger(allInsights.length)} shown (source: ${escapeHtml(sourceLabel)}).${hiddenCrossSource ? ` ${formatInteger(hiddenCrossSource)} cross-source finding(s) are hidden because they compare Chat against CLI — switch the source filter to <strong>All</strong> to see them.` : ''} Dollar, AI-credit (1 credit = $0.01) and legacy premium-request figures throughout this panel are local estimates derived from parsed usage data — not official GitHub billing.</div>
          <div style="margin-top:14px">${cards}</div>
        </section>`;
    }

    export function renderInsightsSubtab() {
      const summary = activeSummary();
      const analysis = analysisForMode();
      const summaryTotals = summaryDisplayTotals(summary);
      const cli = APP_DATA.cli || {};
      const cliSummary = cli.summary || {};
      const filterState = getAnalysisFilterState();
      const cliCard = cli.available ? `
        <div class="insight-card">
          <h4>GitHub Copilot CLI usage</h4>
          <div class="note small">Separate data source (<code>session-store.db</code>), shown here for a project-wide view</div>
          <ul class="help-list">
            <li>${formatInteger(cliSummary.sessionCount)} CLI sessions · ${formatInteger(cliSummary.callCount)} model calls</li>
            <li>${formatInteger(cliSummary.totalInput)} input / ${formatInteger(cliSummary.totalOutput)} output tokens</li>
            <li>${formatPercent(cliSummary.totalInput ? (cliSummary.totalCached / cliSummary.totalInput) * 100 : 0)} cached-read share</li>
            <li>${formatCost(cliSummary.totalCost)} estimated CLI spend</li>
            <li>${formatInteger(cliSummary.fileCount)} files touched across CLI sessions</li>
            ${cli.otelAvailable ? `<li>${formatInteger(cliSummary.toolCallCount)} tool calls captured via OpenTelemetry (see CLI tab → Tool impact)</li>` : '<li>Enable OpenTelemetry export (see CLI tab) for a per-tool breakdown</li>'}
          </ul>
        </div>` : `
        <div class="insight-card">
          <h4>GitHub Copilot CLI usage</h4>
          <div class="note small">No local CLI usage found on this machine — see the CLI tab for setup details.</div>
        </div>`;
      const combinedCost = (summaryTotals.cost || 0) + (cliSummary.totalCost || 0);
      const combinedInput = (summaryTotals.input || 0) + (cliSummary.totalInput || 0);
      const combinedOutput = (summaryTotals.output || 0) + (cliSummary.totalOutput || 0);
      const combinedSessions = (summary.sessionCount || 0) + (cliSummary.sessionCount || 0);
      const overheadCards = Object.entries(analysis.overhead || {}).map(([name, block]) => `
        <div class="insight-card">
          <h4>${escapeHtml(overheadLabel(name))}</h4>
          <div class="note small">Estimated ${escapeHtml(tokenModeLabel())} bucket</div>
          <div class="pill-list" style="margin-top:10px;">
            <span class="pill">Input ${formatInteger(block.input)}</span>
            <span class="pill">Output ${formatInteger(block.output)}</span>
            <span class="pill">Cached ${formatInteger(block.cached)}</span>
            <span class="pill">Cost ${formatCost(block.cost)}</span>
          </div>
        </div>`).join('');
      const expensiveChats = (analysis.topChats || [])
        .filter((chat) => withinRange(filterState, chat.timestamp))
        .slice(0, 6).map((chat) => `
        <div class="insight-card">
          <h4 title="${escapeHtml(chat.title)}">${escapeHtml(chat.title.length > 60 ? chat.title.slice(0,57) + '...' : chat.title)}</h4>
          <div class="note small">${escapeHtml((chat.sessionTitle||'').slice(0,40))} · ${escapeHtml(formatTimestamp(chat.timestamp))}</div>
          <div class="pill-list" style="margin-top:10px;">
            <span class="pill">${escapeHtml(chat.model)}</span>
            <span class="pill">Prompt ${formatInteger(chat.promptTokens)}</span>
            <span class="pill">Cached ${formatInteger(chat.cached)}</span>
            <span class="pill">Cost ${formatCost(chat.cost)}</span>
          </div>
        </div>`).join('');
      const slowestTools = (analysis.slowestTools || [])
        .filter((tool) => withinRange(filterState, tool.timestamp))
        .slice(0, 6).map((tool) => `
        <div class="insight-card">
          <h4 title="${escapeHtml(tool.title)}">${escapeHtml(tool.title.length > 55 ? tool.title.slice(0,52) + '...' : tool.title)}</h4>
          <div class="note small">${escapeHtml((tool.sessionTitle||'').slice(0,40))} · ${escapeHtml(formatTimestamp(tool.timestamp))}</div>
          <div class="pill-list" style="margin-top:10px;">
            <span class="pill">${escapeHtml(tool.name)}</span>
            <span class="pill">${formatDuration(tool.durationMs)}</span>
            <span class="pill">Input ${formatInteger(tool.estimated.input)}</span>
            <span class="pill">${formatCost(tool.estimated.cost)}</span>
          </div>
        </div>`).join('');

      function collapsible(title, innerHtml, startOpen) {
        const openAttr = startOpen ? ' open' : '';
        return `<details class="panel collapsible-section" style="cursor:default"${openAttr}>
          <summary style="cursor:pointer;display:flex;align-items:center;gap:8px;user-select:none;padding:14px 18px">
            <span style="font-size:1.2rem;font-weight:700;width:22px;text-align:center;font-family:monospace" class="collapse-icon">${startOpen ? '−' : '+'}</span>
            <h2 class="section-title" style="margin:0">${title}</h2>
          </summary>
          <div style="padding:0 18px 18px">${innerHtml}</div>
        </details>`;
      }

      return `
        <div class="analysis-grid">
          ${renderRecommendationsPanel()}
          ${collapsible('Interesting breakdowns', `
            <div class="insights-grid">
              <div class="insight-card">
                <h4>Top-level summary <span class="note small" style="font-weight:400">(VS Code Copilot Chat only)</span></h4>
                <ul class="help-list">
                  <li>${formatInteger(summary.sessionCount)} sessions</li>
                  <li>${formatInteger(summary.chatCallCount)} chat calls</li>
                  <li>${formatInteger(summary.toolCallCount)} tool calls</li>
                  <li>${formatInteger(summary.modelCount)} distinct models across ${formatInteger(summary.segmentCount)} inferred segments</li>
                  <li>${formatInteger(summary.modelSwitchCount)} model switches and ${formatInteger(summary.contextResetCount)} inferred context resets</li>
                  <li>${formatPercent(cacheHitRateForBlock(summaryTotals))} cached-read share of ${escapeHtml(tokenModeLabel())} input</li>
                  <li>${formatCost(summaryTotals.cost)} total ${escapeHtml(tokenModeLabel())} spend</li>
                </ul>
              </div>
              <div class="insight-card">
                <h4>Project-wide total <span class="note small" style="font-weight:400">(VS Code + CLI)</span></h4>
                <div class="note small">Combines the summary above with GitHub Copilot CLI usage below — the two sources use different token-attribution models, so treat this as a rough combined view, not an exact merge.</div>
                <ul class="help-list">
                  <li>${formatInteger(combinedSessions)} sessions total (${formatInteger(summary.sessionCount)} VS Code + ${formatInteger(cliSummary.sessionCount || 0)} CLI)</li>
                  <li>${formatInteger(combinedInput)} combined input tokens</li>
                  <li>${formatInteger(combinedOutput)} combined output tokens</li>
                  <li>${formatCost(combinedCost)} combined estimated spend</li>
                </ul>
              </div>
              ${cliCard}
              ${overheadCards}
            </div>`, false)}
          ${collapsible('Expensive chats', `<div class="insights-grid">${expensiveChats}</div>`, false)}
          ${collapsible('Slowest tools', `<div class="insights-grid">${slowestTools}</div>`, false)}
          ${collapsible('Global token breakdown', renderGlobalTokenPieChart(summary, analysis), true)}
        </div>`;
    }

    export function renderAnalysisTab() {
      const tabBodies = {
        models: renderModelsSubtab,
        tools: renderToolsSubtab,
        files: renderFilesSubtab,
        monthlyTrends: renderMonthlyTrendsSubtab,
        insights: renderInsightsSubtab,
      };
      if (!tabBodies[STATE.analysisTab]) {
        STATE.analysisTab = 'models';
      }
      return `<section class="panel">${analysisSubtabs()}</section>${tabBodies[STATE.analysisTab]()}`;
    }

    // ---------------------------------------------------------------------
    // Insight filter handlers (inline onclick/onchange targets below).
    // ---------------------------------------------------------------------

    export function setInsightSeverityFilter(value) {
      ensureInsightFilterState().severity = value;
      renderApp();
    }

    // No setInsightSourceFilter: source comes from the global filter bar's
    // setFilter('source', ...) (filters.js) — one control, one source of truth.

    export function setInsightSavingsOnly(checked) {
      ensureInsightFilterState().savingsOnly = !!checked;
      renderApp();
    }

    function fallbackCopyToClipboard(text) {
      try {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        return true;
      } catch (_err) {
        return false;
      }
    }

    function flashCopyButton(buttonEl) {
      if (!buttonEl) return;
      const original = buttonEl.textContent;
      buttonEl.textContent = '✓ Copied';
      buttonEl.classList.add('copied');
      setTimeout(() => {
        buttonEl.textContent = original;
        buttonEl.classList.remove('copied');
      }, 1500);
    }

    // Copies the currently-filtered recommendation list (see
    // filteredInsightsList()) as a Markdown bullet list — exports what the
    // user sees, not the full unfiltered APP_DATA.insights array — so it's
    // ready to paste into a GitHub issue/PR description.
    export function copyInsightsMarkdown(buttonEl) {
      const insights = filteredInsightsList();
      if (!insights.length) {
        alert('No recommendations match the current filters — nothing to copy.');
        return;
      }
      const lines = insights.map((insight) => {
        const savings = insight.estimatedSavings || {};
        const savingsBits = [];
        if (Number(savings.cost || 0) > 0) savingsBits.push(formatCost(savings.cost));
        if (Number(savings.premiumRequests || 0) > 0) savingsBits.push(`${formatInteger(savings.premiumRequests)} premium req. (legacy)`);
        const savingsText = savingsBits.length ? ` (est. saving: ${savingsBits.join(', ')})` : '';
        return `- **[${String(insight.severity || 'info').toUpperCase()}] ${insight.title}**${savingsText}\n  ${insight.detail}\n  _Action:_ ${insight.action}`;
      });
      const markdown = `## Copilot usage recommendations\n\n${lines.join('\n\n')}\n\n_Estimates are local approximations derived from parsed usage data, not official GitHub billing._`;
      const finish = () => { flashCopyButton(buttonEl); };
      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        navigator.clipboard.writeText(markdown).then(finish).catch(() => {
          if (fallbackCopyToClipboard(markdown)) finish();
          else alert('Copy failed — please copy the summary manually from the browser console.');
        });
      } else if (fallbackCopyToClipboard(markdown)) {
        finish();
      } else {
        alert('Copy failed — please copy the summary manually from the browser console.');
      }
    }

    // This module owns the Insights UI's inline handlers; since app.js
    // (owned by another agent) can't be edited to add them to its curated
    // Object.assign(window, {...}) block, they're bound here directly —
    // same pattern filters.js uses for window.CopilotFilters.
    if (typeof window !== 'undefined') {
      Object.assign(window, {
        setInsightSeverityFilter,
        setInsightSavingsOnly,
        copyInsightsMarkdown,
      });
    }
