import { exportToJson, switchTab, switchTokenMode, switchUsagePeriod } from './actions.js';
import { activePeriodLabel, activeSummary, pagedSessions, unifiedFilteredTotals } from './aggregate.js';
import { cacheHitRateForBlock, escapeHtml, formatCost, formatInteger, formatPercent, pickTokenBlock, summaryDisplayTotals } from './format.js';
import { applyCustomDateInputs, currentFilters, decodeHashIntoState, encodeHashFromState, setFilter } from './filters.js';
import { APP_DATA, STATE, applyTheme, captureInputFocusState, isBilledMode, normalizeTokenMode, restoreInputFocusState, tokenModeLabel } from './state.js';
import { renderAnalysisTab } from './tab-analysis.js';
import { renderChatsTab } from './tab-chats.js';
import { renderCliTab } from './tab-cli.js';
import { openInsightsFromOverview, renderOverviewTab } from './tab-overview.js';
import { renderReferenceTab } from './tab-reference.js';
import { applyChatDeletion, changePage, deleteSessionPrompt, setDeleteAgePreset, setDeleteKeepCount, setDeleteMode, setDeleteSpecificDate, setFileSearch, setFileSort, setModelFilter, setPageSize, setSearch, setToolCatalogSearch, setToolCatalogSort, setToolImpactSearch, setToolSort, setToolWasteSort, switchAnalysisTab, switchDataTab, switchMonthlyTrendMetric, switchToolImpactTab } from './actions.js';
import { closeChatDeleteModal, closeFileModal, closeFullChatModal, closeGenAiModal, closeModelCompareModal, exportSessionToJson, openChatDeleteModal, openFileModal, openFullChatModal, openGenAiModal, openModelCompareModal, switchGenAiTab } from './modals.js';
import { restoreHiddenChats, restoreHiddenCliSessions } from './state.js';
import { changeCliPage, deleteCliSessionPrompt, exportCliSessionToJson, openCliFullChatModal, openCliModelCompareModal, setCliFileSearch, setCliModelFilter, setCliPageSize, setCliSearch } from './tab-cli.js';


    // Maps a premium.budget.status ('ok'|'warn'|'critical') to the CSS
    // state class contract published in components.css. Never hand-tune
    // colours in JS -- only ever flip this class.
    function stateClass(status) {
      return `state-${status === 'critical' ? 'critical' : status === 'warn' ? 'warn' : 'ok'}`;
    }

    export function toggleTheme() {
      applyTheme(STATE.theme === 'light' ? 'dark' : 'light');
      renderApp();
    }

    // Unified (chat+CLI, STATE.filters-aware) header summary cards. Replaces
    // the old chat-only summaryDisplayTotals()-based cards so switching the
    // source segmented control (All/Chat/CLI) actually changes the headline
    // numbers, per the "Copilot Usage Explorer" header requirement.
    export function renderSummaryCards() {
      const totals = unifiedFilteredTotals();
      const block = pickTokenBlock(totals.attributed, totals.billed);
      const costLabel = isBilledMode() ? 'Billed API cost' : 'Attributed est. cost';
      const creditsLabel = isBilledMode() ? 'Billed AI credits' : 'Attributed AI credits';
      const budget = APP_DATA.premium?.budget || {};
      const hasAllowance = budget.allowance !== null && budget.allowance !== undefined;
      const pct = hasAllowance ? Math.max(0, Math.min(100, Number(budget.percentUsed || 0))) : 0;
      const quotaLabel = hasAllowance ? `${formatPercent(pct)} of ${formatInteger(budget.allowance)}` : 'no allowance set';
      const quotaGauge = hasAllowance
        ? `<div class="gauge ${stateClass(budget.status)}" style="margin-top:6px"><div class="gauge-fill ${stateClass(budget.status)}" style="width:${pct}%"></div></div>`
        : '';
      return `
        <div class="summary-groups">
          <div class="summary-group">
            <div class="summary-group-label">Usage</div>
            <div class="summary-grid">
              <div class="summary-card"><div class="label">Sessions</div><div class="value">${formatInteger(totals.sessionCount)}</div></div>
              <div class="summary-card"><div class="label">Calls</div><div class="value">${formatInteger(totals.callCount)}</div></div>
              <div class="summary-card"><div class="label">Total input tokens</div><div class="value input">${formatInteger(block.input)}</div></div>
              <div class="summary-card"><div class="label">Uncached input tokens</div><div class="value uncached">${formatInteger(block.uncached)}</div></div>
              <div class="summary-card"><div class="label">Cached-read input tokens</div><div class="value cached">${formatInteger(block.cached)}</div></div>
              <div class="summary-card"><div class="label">Output tokens</div><div class="value output">${formatInteger(block.output)}</div></div>
            </div>
          </div>
          <div class="summary-group">
            <div class="summary-group-label">Cost &amp; premium</div>
            <div class="summary-grid">
              <div class="summary-card"><div class="label">${escapeHtml(costLabel)}</div><div class="value cost">${formatCost(block.cost)}</div></div>
              <div class="summary-card"><div class="label">${escapeHtml(creditsLabel)}</div><div class="value credits">${(block.cost / 0.01).toFixed(1)}</div></div>
              <div class="summary-card"><div class="label">Premium requests</div><div class="value">${formatInteger(totals.premiumRequests)}</div></div>
              <div class="summary-card"><div class="label">Premium quota used</div><div class="value">${escapeHtml(quotaLabel)}</div>${quotaGauge}</div>
            </div>
          </div>
        </div>`;
    }

    // The sticky global filter bar: source segmented control, period control
    // (with a custom range revealed only when period === 'custom'), and the
    // existing Attributed/Billed token-mode toggle. See filters.js's
    // top-of-file comment for the STATE.filters contract this drives.
    // Uses the styles agent's `.filter-bar-sticky` / `.segmented-control`
    // contract (layout.css / tabs.css); `.is-stuck` is toggled from JS via
    // an IntersectionObserver against the sentinel just above the bar (see
    // initStickyObserver()) rather than a scroll-position calculation.
    export function renderFilterBar() {
      const filters = currentFilters();
      const sourceOptions = [['all', 'All'], ['chat', 'Chat'], ['cli', 'CLI']];
      const periodOptions = [['today', 'Today'], ['7d', '7 days'], ['30d', '30 days'], ['month', 'This month'], ['all', 'All time'], ['custom', 'Custom']];
      const sourceButtons = sourceOptions.map(([value, label]) => `<button type="button" class="subtab-button ${filters.source === value ? 'active' : ''}" onclick="setFilter('source', '${value}')">${escapeHtml(label)}</button>`).join('');
      const periodButtons = periodOptions.map(([value, label]) => `<button type="button" class="subtab-button ${filters.period === value ? 'active' : ''}" onclick="setFilter('period', '${value}')">${escapeHtml(label)}</button>`).join('');
      const startVal = filters.start ? new Date(filters.start).toISOString().slice(0, 10) : '';
      const endVal = filters.end ? new Date(filters.end).toISOString().slice(0, 10) : '';
      const customInputs = filters.period === 'custom'
        ? `<span style="display:inline-flex;gap:6px;align-items:center;margin-left:8px">
             <input type="date" id="filterCustomStart" value="${escapeHtml(startVal)}" onchange="applyCustomDateInputs()">
             <span class="note small">to</span>
             <input type="date" id="filterCustomEnd" value="${escapeHtml(endVal)}" onchange="applyCustomDateInputs()">
           </span>`
        : '';
      return `
        <div id="filterBarSentinel" style="height:0"></div>
        <div class="filter-bar filter-bar-sticky" id="filterBarSticky">
          <div><span class="note small" style="margin-right:6px">Source</span><span class="segmented-control">${sourceButtons}</span></div>
          <div><span class="note small" style="margin-right:6px">Period</span><span class="segmented-control">${periodButtons}</span>${customInputs}</div>
          <div><span class="note small" style="margin-right:6px">Tokens</span><span class="segmented-control">
            <button type="button" class="subtab-button ${normalizeTokenMode(STATE.tokenMode) === 'attributed' ? 'active' : ''}" onclick="switchTokenMode('attributed')">Attributed</button>
            <button type="button" class="subtab-button ${normalizeTokenMode(STATE.tokenMode) === 'billed' ? 'active' : ''}" onclick="switchTokenMode('billed')">Billed</button>
          </span></div>
        </div>`;
    }

    export function renderHeader() {
      const summary = activeSummary();
      const legacyTotals = summaryDisplayTotals(summary);
      const modeLabel = tokenModeLabel();
      const periodLabel = activePeriodLabel();
      const filters = currentFilters();
      const anonymizedBadge = APP_DATA.anonymized
        ? '<span class="badge" title="Host/user identifiers were replaced with dev-xxxx pseudonyms (--anonymize)">🕶 anonymized</span>'
        : '';
      const themeIsLight = STATE.theme === 'light';
      return `
        <section class="header">
          <div class="header-top">
            <div>
              <h1>📊 Copilot Usage Explorer ${anonymizedBadge}</h1>
              <div class="subtitle">Unified view across VS Code Copilot Chat and the GitHub Copilot CLI: <strong>prompt snapshots</strong> vs. <strong>billed per-call usage</strong>, premium-request budget tracking, and cost/quota recommendations.</div>
              <div class="subtitle small">Generated: ${escapeHtml(APP_DATA.generatedAt)} · Legacy chat period: <strong>${escapeHtml(periodLabel)}</strong> · Token mode: <strong>${escapeHtml(modeLabel)}</strong> · Chat cached share: ${formatPercent(cacheHitRateForBlock(legacyTotals))}</div>
            </div>
            <div style="display:flex;gap:12px;flex-direction:column;align-items:flex-end;min-width:200px">
              <div style="display:flex;gap:8px">
                <button type="button" class="action-chip" onclick="toggleTheme()" title="Switch to ${themeIsLight ? 'dark' : 'light'} theme">${themeIsLight ? '🌙 Dark' : '☀️ Light'}</button>
                <button type="button" class="action-chip action-chip--teal" onclick="exportToJson()">⬇ Export JSON</button>
              </div>
            </div>          </div>
          ${renderFilterBar()}
          ${renderSummaryCards()}
          <div class="tabs">
            <button class="tab-button ${STATE.activeTab === 'overview' ? 'active' : ''}" onclick="switchTab('overview')">Overview</button>
            ${filters.source !== 'cli' ? `<button class="tab-button ${STATE.activeTab === 'chats' ? 'active' : ''}" onclick="switchTab('chats')">Chats</button>` : ''}
            <button class="tab-button ${STATE.activeTab === 'analysis' ? 'active' : ''}" onclick="switchTab('analysis')">Analysis</button>
            ${filters.source !== 'chat' ? `<button class="tab-button ${STATE.activeTab === 'cli' ? 'active' : ''}" onclick="switchTab('cli')">CLI</button>` : ''}
            <button class="tab-button ${STATE.activeTab === 'reference' ? 'active' : ''}" onclick="switchTab('reference')">Info</button>
          </div>
        </section>`;
    }

    // ---- Incremental rendering ----
    // renderApp() used to rebuild #app's entire innerHTML on every state
    // change (every debounced keystroke, every filter click, every tab
    // switch), which is the dashboard's main interaction-latency cost and
    // the reason captureInputFocusState()/restoreInputFocusState() existed.
    // Instead: build a stable skeleton of named region containers once,
    // then on every render recompute each region's HTML string (cheap) but
    // only touch the DOM (expensive: reflow, listener teardown, focus/
    // scroll loss) for a region whose string actually changed. This is
    // always behaviourally identical to a full rebuild -- every region is
    // still recomputed fresh from current STATE every call -- it only skips
    // redundant DOM writes for regions nothing changed in. Typing in the
    // Chats search box, for example, only rewrites the Chats region; the
    // header, Overview, Analysis, CLI and Reference regions are left
    // untouched (preserving their scroll position, any open <details>, etc).
    const REGIONS = [
      ['regionHeader', 'header', renderHeader],
      ['regionOverview', 'overview', renderOverviewTab],
      ['regionChats', 'chats', renderChatsTab],
      ['regionAnalysis', 'analysis', renderAnalysisTab],
      ['regionCli', 'cli', renderCliTab],
      ['regionReference', 'reference', renderReferenceTab],
    ];

    const _regionHtmlCache = Object.create(null);
    let _stickyObserver = null;

    function ensureAppSkeleton(app) {
      if (app.dataset.skeletonReady === '1') return;
      app.innerHTML = REGIONS.map(([id, tab]) => (
        tab === 'header' ? `<div id="${id}"></div>` : `<section class="tab-panel" id="${id}"></section>`
      )).join('');
      app.dataset.skeletonReady = '1';
    }

    function updateRegion(id, html) {
      if (_regionHtmlCache[id] === html) return false;
      _regionHtmlCache[id] = html;
      const el = document.getElementById(id);
      if (el) el.innerHTML = html;
      return true;
    }

    // `.is-stuck` (elevated/shadowed pinned look) is driven purely by
    // whether the sentinel placed just above the sticky filter bar has
    // scrolled out of view -- re-initialised after every header repaint
    // since a header DOM write replaces the sentinel/bar nodes.
    function initStickyObserver() {
      const sentinel = document.getElementById('filterBarSentinel');
      const bar = document.getElementById('filterBarSticky');
      if (!sentinel || !bar || typeof IntersectionObserver === 'undefined') return;
      if (_stickyObserver) _stickyObserver.disconnect();
      _stickyObserver = new IntersectionObserver(([entry]) => {
        bar.classList.toggle('is-stuck', !entry.isIntersecting);
      }, { threshold: 0 });
      _stickyObserver.observe(sentinel);
    }

    export function renderApp() {
      const app = document.getElementById('app');
      const pages = pagedSessions();
      if (STATE.page > pages.pageCount) STATE.page = pages.pageCount;
      ensureAppSkeleton(app);
      const focusState = captureInputFocusState();
      let headerChanged = false;
      REGIONS.forEach(([id, tab, renderFn]) => {
        const changed = updateRegion(id, renderFn());
        if (tab === 'header') headerChanged = changed;
        else document.getElementById(id)?.classList.toggle('active', STATE.activeTab === tab);
      });
      restoreInputFocusState(focusState);
      if (headerChanged) initStickyObserver();
      encodeHashFromState();
    }


// Attach every function referenced from an inline onclick/onchange/
// oninput/onsubmit="..." attribute to `window` so those handlers keep
// resolving once this module is bundled (module scope is not global).
Object.assign(window, {
  applyChatDeletion,
  applyCustomDateInputs,
  changeCliPage,
  changePage,
  closeChatDeleteModal,
  closeFileModal,
  closeFullChatModal,
  closeGenAiModal,
  closeModelCompareModal,
  deleteCliSessionPrompt,
  deleteSessionPrompt,
  exportCliSessionToJson,
  exportSessionToJson,
  exportToJson,
  openChatDeleteModal,
  openCliFullChatModal,
  openCliModelCompareModal,
  openFileModal,
  openFullChatModal,
  openGenAiModal,
  openInsightsFromOverview,
  openModelCompareModal,
  restoreHiddenChats,
  restoreHiddenCliSessions,
  setCliFileSearch,
  setCliModelFilter,
  setCliPageSize,
  setCliSearch,
  setDeleteAgePreset,
  setDeleteKeepCount,
  setDeleteMode,
  setDeleteSpecificDate,
  setFileSearch,
  setFileSort,
  setFilter,
  setModelFilter,
  setPageSize,
  setSearch,
  setToolCatalogSearch,
  setToolCatalogSort,
  setToolImpactSearch,
  setToolSort,
  setToolWasteSort,
  switchAnalysisTab,
  switchDataTab,
  switchGenAiTab,
  switchMonthlyTrendMetric,
  switchTab,
  switchTokenMode,
  switchToolImpactTab,
  switchUsagePeriod,
  toggleTheme,
});

    decodeHashIntoState();
    renderApp();

