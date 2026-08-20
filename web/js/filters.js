// ---------------------------------------------------------------------------
// window.CopilotFilters — the global filter contract for the Copilot Usage
// Explorer. This comment block IS the contract other modules/agents code
// against (CLI tab, Analysis tab, Overview tab); keep it accurate.
//
// STATE.filters shape (see state.js `loadFilters()`/`defaultFilters()`):
//   {
//     source: 'all' | 'chat' | 'cli',
//     period: 'today' | '7d' | '30d' | 'month' | 'all' | 'custom',
//     start:  epoch-ms | null,   // only meaningful when period === 'custom'
//     end:    epoch-ms | null,   // only meaningful when period === 'custom'
//     tokenMode: 'attributed' | 'billed', // mirror of STATE.tokenMode, kept
//                                          // in sync by switchTokenMode()
//                                          // (actions.js) — read it here for
//                                          // convenience/deep-linking, but
//                                          // STATE.tokenMode remains the
//                                          // source of truth.
//   }
// Persisted to localStorage ('copilot-dashboard-filters-v1') and restored on
// load; STATE.usagePeriod ('monthly'/'allTime') is migrated into
// filters.period once (see state.js `defaultFilters()`) rather than
// duplicated — old persisted usagePeriod behavior keeps working because nothing
// deletes/ignores STATE.usagePeriod; it is now driven by `setFilter('period', ...)`
// for the two periods it understands ('month' -> 'monthly', 'all' -> 'allTime').
//
// Public API (also published as `window.CopilotFilters` for any module that
// prefers not to import this file directly, e.g. the CLI/Analysis tab
// modules owned by other agents):
//
//   currentFilters()
//     -> a shallow copy of STATE.filters (tokenMode always the normalized
//        current STATE.tokenMode, so it can never drift out of sync).
//
//   periodRange(period = STATE.filters.period)
//     -> { start: epoch-ms|null, end: epoch-ms|null }
//        'all' -> { start: null, end: null } (no bound, matches everything).
//        'today' -> local midnight..now. '7d'/'30d' -> now-N days..now.
//        'month' -> first of current calendar month..now.
//        'custom' -> STATE.filters.start/end verbatim (either may be null).
//
//   matchesSource(source)
//     -> boolean; does a record/session's source ('chat'|'cli') pass the
//        active STATE.filters.source ('all' always matches).
//
//   filterInsightsBySource(insights)
//     -> { visible, hiddenCrossSource, source } for an APP_DATA.insights-shaped
//        array. Source is the ONLY global filter recommendations honor (see
//        the note on the function itself for why period cannot apply), and it
//        is honored here rather than by any per-panel control so Overview's
//        "Top recommendations" and Analysis -> Insights can never disagree.
//
//   filterUnifiedRows(rows)
//     -> filters an array of APP_DATA.unified.daily/monthly-shaped rows
//        (rows with a `dayKey` 'YYYY-MM-DD' or `monthKey` 'YYYY-MM') down to
//        the active period. Source filtering is NOT applied here (these rows
//        are pre-aggregated across both sources): callers that need a
//        single source's numbers should read `row.bySource[filters.source]`
//        per row when `filters.source !== 'all'` (see
//        `aggregate.js#unifiedFilteredTotals` for a worked example).
//
//   filterSessions(sessions, sourceKind)
//     -> filters a chat- or CLI-session array by both the active period
//        (session.timestamp for chat sessions, session.lastActivity for CLI
//        sessions) and by source: pass the literal source kind of the array
//        being filtered ('chat' or 'cli') and it is compared against
//        `filters.source` (returns [] outright if the array's source doesn't
//        match a specific non-'all' source filter).
//
//   setFilter(key, value)
//     -> sets STATE.filters[key] (key must be one of source/period/start/end/
//        tokenMode), persists to localStorage, resets pagination (STATE.page/
//        STATE.cliPage back to 1), and re-renders (calls renderApp()).
//        NOTE: to change tokenMode prefer `switchTokenMode()` (actions.js) —
//        it keeps STATE.tokenMode and STATE.filters.tokenMode in sync and is
//        already wired to the Attributed/Billed toggle.
//
//   setCustomRange(startMs, endMs)
//     -> convenience wrapper: sets period to 'custom' and both bounds in one
//        render pass (used by the two custom date inputs in the filter bar).
//
// Deep links: `encodeHashFromState()` serializes {tab, subtab, source,
// period, start, end, tokenMode} into `location.hash` using
// `history.replaceState` (no extra history entries), called once at the end
// of every `renderApp()`. `decodeHashIntoState()` does the reverse and is
// called once at startup (app.js), after STATE/STATE.filters already have
// their localStorage-restored defaults, so a bookmarked/shared URL always
// wins over whatever was last persisted locally.
// ---------------------------------------------------------------------------

import { STATE, normalizeTokenMode, persistFilters } from './state.js';
import { renderApp } from './app.js';

const VALID_PERIODS = new Set(['today', '7d', '30d', 'month', 'all', 'custom']);
const VALID_SOURCES = new Set(['all', 'chat', 'cli']);
const VALID_FILTER_KEYS = new Set(['source', 'period', 'start', 'end', 'tokenMode']);

function startOfLocalDay(ms) {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function startOfCurrentMonth() {
  const d = new Date();
  d.setDate(1);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function currentFilters() {
  return { ...STATE.filters, tokenMode: normalizeTokenMode(STATE.tokenMode) };
}

export function periodRange(period) {
  const p = period || STATE.filters.period;
  const now = Date.now();
  switch (p) {
    case 'today':
      return { start: startOfLocalDay(now), end: now };
    case '7d':
      return { start: now - 7 * 86400000, end: now };
    case '30d':
      return { start: now - 30 * 86400000, end: now };
    case 'month':
      return { start: startOfCurrentMonth(), end: now };
    case 'custom':
      return { start: STATE.filters.start ?? null, end: STATE.filters.end ?? null };
    case 'all':
    default:
      return { start: null, end: null };
  }
}

export function matchesSource(source) {
  const active = STATE.filters.source;
  if (active === 'all') return true;
  return String(source || '') === active;
}

// Recommendations (APP_DATA.insights) are precomputed once at generation time
// (dashboard_core.py -> insights_engine.build_insights) over the whole parsed
// dataset, and each finding is tagged source: 'chat' | 'cli' | 'both' ('both' =
// an inherently cross-source finding, e.g. the chat-vs-CLI cost comparison).
// Consequences for filtering:
//   * source CAN be applied here, by tag.
//   * period CANNOT — the rules would have to be re-run over a date-bounded
//     slice of the data, which only the Python engine can do; the UI therefore
//     states plainly that the period filter does not apply to recommendations
//     rather than pretending otherwise.
// When a single source is active, 'both' findings are hidden outright (a
// chat-vs-CLI comparison is meaningless with one side filtered out) and their
// count is returned so callers can say so instead of silently dropping them.
export function filterInsightsBySource(insights) {
  const all = Array.isArray(insights) ? insights : [];
  const active = STATE.filters.source;
  if (active === 'all') return { visible: all, hiddenCrossSource: 0, source: active };
  return {
    visible: all.filter((insight) => String(insight?.source || '') === active),
    hiddenCrossSource: all.filter((insight) => String(insight?.source || '') === 'both').length,
    source: active,
  };
}

function unifiedRowMs(row) {
  if (row && row.dayKey) {
    const t = new Date(`${row.dayKey}T00:00:00`).getTime();
    return Number.isFinite(t) ? t : null;
  }
  if (row && row.monthKey) {
    const t = new Date(`${row.monthKey}-01T00:00:00`).getTime();
    return Number.isFinite(t) ? t : null;
  }
  return null;
}

export function filterUnifiedRows(rows) {
  const { start, end } = periodRange();
  return (rows || []).filter((row) => {
    const ms = unifiedRowMs(row);
    if (ms === null) return true;
    if (start !== null && ms < start) return false;
    if (end !== null && ms > end) return false;
    return true;
  });
}

export function filterSessions(sessions, sourceKind) {
  if (!matchesSource(sourceKind)) return [];
  const { start, end } = periodRange();
  if (start === null && end === null) return sessions || [];
  return (sessions || []).filter((session) => {
    const ts = Number(session?.timestamp ?? session?.lastActivity ?? session?.updatedAt ?? session?.createdAt ?? 0);
    if (!ts) return true;
    if (start !== null && ts < start) return false;
    if (end !== null && ts > end) return false;
    return true;
  });
}

function syncLegacyUsagePeriod() {
  // aggregate.js's pre-computed monthly/allTime bundles (used by the
  // Analysis tab and legacy header path) only understand two buckets; keep
  // them pointed at the closest equivalent so those still-STATE.usagePeriod-
  // driven views stay sane for the two periods they can represent exactly.
  if (STATE.filters.period === 'month') STATE.usagePeriod = 'monthly';
  else if (STATE.filters.period === 'all') STATE.usagePeriod = 'allTime';
}

// Tabs that only make sense for one source; when the global source filter
// excludes that source, the tab button itself is hidden from the tab bar
// (see app.js renderTabs()) rather than left clickable-but-empty.
const TAB_SOURCE_REQUIREMENT = { chats: 'chat', cli: 'cli' };

export function setFilter(key, value) {
  if (!VALID_FILTER_KEYS.has(key)) return;
  if (key === 'source' && !VALID_SOURCES.has(value)) return;
  if (key === 'period' && !VALID_PERIODS.has(value)) return;
  STATE.filters[key] = value;
  syncLegacyUsagePeriod();
  persistFilters(STATE.filters);
  STATE.page = 1;
  STATE.cliPage = 1;
  // If the newly active source filter hides the tab currently open (e.g.
  // switching to "Chat" while on the CLI tab), bounce back to Overview so
  // the user never lands on a tab with a "hidden by filter" dead-end.
  if (key === 'source') {
    const required = TAB_SOURCE_REQUIREMENT[STATE.activeTab];
    if (required && value !== 'all' && value !== required) {
      STATE.activeTab = 'overview';
    }
  }
  renderApp();
}

export function setCustomRange(startMs, endMs) {
  STATE.filters.period = 'custom';
  STATE.filters.start = Number.isFinite(Number(startMs)) ? Number(startMs) : null;
  STATE.filters.end = Number.isFinite(Number(endMs)) ? Number(endMs) : null;
  persistFilters(STATE.filters);
  STATE.page = 1;
  STATE.cliPage = 1;
  renderApp();
}

// Bound to the two <input type="date"> elements in the sticky filter bar's
// "Custom" period; reads their current values and applies both bounds in a
// single setCustomRange() call/re-render.
export function applyCustomDateInputs() {
  const startEl = document.getElementById('filterCustomStart');
  const endEl = document.getElementById('filterCustomEnd');
  const startMs = startEl && startEl.value ? new Date(`${startEl.value}T00:00:00`).getTime() : null;
  const endMs = endEl && endEl.value ? new Date(`${endEl.value}T23:59:59`).getTime() : null;
  setCustomRange(Number.isFinite(startMs) ? startMs : null, Number.isFinite(endMs) ? endMs : null);
}

function subtabForActiveTab() {
  if (STATE.activeTab === 'analysis') return STATE.analysisTab;
  if (STATE.activeTab === 'reference') return STATE.dataTab;
  return '';
}

export function encodeHashFromState() {
  const params = new URLSearchParams();
  params.set('tab', STATE.activeTab);
  const subtab = subtabForActiveTab();
  if (subtab) params.set('subtab', subtab);
  params.set('source', STATE.filters.source);
  params.set('period', STATE.filters.period);
  if (STATE.filters.period === 'custom') {
    if (STATE.filters.start) params.set('start', String(STATE.filters.start));
    if (STATE.filters.end) params.set('end', String(STATE.filters.end));
  }
  params.set('tokenMode', normalizeTokenMode(STATE.tokenMode));
  const nextHash = `#${params.toString()}`;
  if (window.location.hash !== nextHash && typeof window.history?.replaceState === 'function') {
    window.history.replaceState(null, '', nextHash);
  }
}

export function decodeHashIntoState() {
  const raw = String(window.location.hash || '').replace(/^#/, '');
  if (!raw) return;
  let params;
  try {
    params = new URLSearchParams(raw);
  } catch (_err) {
    return;
  }

  const tab = params.get('tab');
  if (tab && ['overview', 'chats', 'analysis', 'cli', 'reference'].includes(tab)) {
    STATE.activeTab = tab;
  }
  const subtab = params.get('subtab');
  if (subtab) {
    if (STATE.activeTab === 'analysis') STATE.analysisTab = subtab;
    else if (STATE.activeTab === 'reference') STATE.dataTab = subtab;
  }
  const source = params.get('source');
  if (VALID_SOURCES.has(source)) STATE.filters.source = source;
  const period = params.get('period');
  if (VALID_PERIODS.has(period)) STATE.filters.period = period;
  const start = params.get('start');
  const end = params.get('end');
  if (start && Number.isFinite(Number(start))) STATE.filters.start = Number(start);
  if (end && Number.isFinite(Number(end))) STATE.filters.end = Number(end);
  const tokenMode = params.get('tokenMode');
  if (tokenMode) {
    STATE.tokenMode = normalizeTokenMode(tokenMode);
    STATE.filters.tokenMode = STATE.tokenMode;
  }
  syncLegacyUsagePeriod();
  persistFilters(STATE.filters);
  // Guard against a stale/hand-edited deep link pointing at a tab the
  // decoded source filter would hide (e.g. tab=cli&source=chat).
  const requiredSource = TAB_SOURCE_REQUIREMENT[STATE.activeTab];
  if (requiredSource && STATE.filters.source !== 'all' && STATE.filters.source !== requiredSource) {
    STATE.activeTab = 'overview';
  }
}

if (typeof window !== 'undefined') {
  window.CopilotFilters = {
    currentFilters,
    periodRange,
    matchesSource,
    filterInsightsBySource,
    filterUnifiedRows,
    filterSessions,
    setFilter,
    setCustomRange,
    applyCustomDateInputs,
  };
}
