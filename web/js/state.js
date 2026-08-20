import { renderApp } from './app.js';

    export const APP_DATA = __APP_JSON__;

    const STORAGE_KEYS = {
      hiddenSessions: 'copilot-dashboard-hidden-sessions-v1',
      hiddenCliSessions: 'copilot-dashboard-hidden-cli-sessions-v1',
      tokenMode: 'copilot-dashboard-token-mode-v1',
      lastTab: 'copilot-dashboard-last-tab-v1',
      filters: 'copilot-dashboard-filters-v1',
      theme: 'copilot-dashboard-theme-v1',
    };

    const VALID_TABS = new Set(['overview', 'chats', 'analysis', 'cli', 'reference']);

    function loadLastTab() {
      try {
        const raw = localStorage.getItem(STORAGE_KEYS.lastTab);
        return VALID_TABS.has(raw) ? raw : 'overview';
      } catch (_err) {
        return 'overview';
      }
    }

    export function persistLastTab(tabName) {
      try {
        if (VALID_TABS.has(tabName)) localStorage.setItem(STORAGE_KEYS.lastTab, tabName);
      } catch (_err) {
        // Ignore storage failures (private mode / disabled storage).
      }
    }

    const VALID_PERIODS = new Set(['today', '7d', '30d', 'month', 'all', 'custom']);
    const VALID_SOURCES = new Set(['all', 'chat', 'cli']);

    function defaultFilters() {
      // Migrate the legacy STATE.usagePeriod value ('monthly'/'allTime') into
      // the new period model so a fresh STATE.filters still reflects whatever
      // the old (still-used-elsewhere) usagePeriod default resolved to.
      const legacyPeriod = ((APP_DATA.periods && APP_DATA.periods.default) || 'monthly') === 'allTime' ? 'all' : 'month';
      return { source: 'all', period: legacyPeriod, start: null, end: null, tokenMode: 'attributed' };
    }

    export function loadFilters() {
      const base = defaultFilters();
      try {
        const raw = localStorage.getItem(STORAGE_KEYS.filters);
        const parsed = raw ? JSON.parse(raw) : null;
        if (!parsed || typeof parsed !== 'object') return base;
        return {
          source: VALID_SOURCES.has(parsed.source) ? parsed.source : base.source,
          period: VALID_PERIODS.has(parsed.period) ? parsed.period : base.period,
          start: Number.isFinite(Number(parsed.start)) ? Number(parsed.start) : null,
          end: Number.isFinite(Number(parsed.end)) ? Number(parsed.end) : null,
          tokenMode: parsed.tokenMode === 'billed' ? 'billed' : 'attributed',
        };
      } catch (_err) {
        return base;
      }
    }

    export function persistFilters(filters) {
      try {
        localStorage.setItem(STORAGE_KEYS.filters, JSON.stringify(filters || {}));
      } catch (_err) {
        // Ignore storage failures (private mode / disabled storage).
      }
    }

    export const STATE = {
      activeTab: loadLastTab(),
      usagePeriod: (APP_DATA.periods && APP_DATA.periods.default) || 'monthly',
      filters: loadFilters(),
      tokenMode: 'attributed',
      analysisTab: 'models',
      toolImpactTab: 'usage',
      dataTab: 'prices',
      monthlyTrendMetric: 'cost',
      toolCatalogSearch: '',
      toolCatalogSortKey: 'descriptionTokens',
      toolCatalogSortDir: 'desc',
      toolWasteSortKey: 'wastedInputTokens',
      toolWasteSortDir: 'desc',
      toolImpactSearch: '',
      search: '',
      cliSearch: '',
      cliFileSearch: '',
      cliPage: 1,
      cliPageSize: 10,
      cliModel: '',
      deleteTarget: 'chats',
      model: '',
      page: 1,
      pageSize: 10,
      fileSearch: '',
      fileSortKey: 'cost',
      fileSortDir: 'desc',
      toolSortKey: 'cost',
      toolSortDir: 'desc',
      autoRefresh: false,
      refreshInterval: 60000,
      refreshTimer: null,
      deleteMode: 'all',
      deleteAgePreset: 'week',
      deleteCustomDate: '',
      deleteKeepCount: 10,
    };

    export function loadHiddenIdSet(storageKey) {
      try {
        const raw = localStorage.getItem(storageKey);
        const parsed = raw ? JSON.parse(raw) : [];
        if (!Array.isArray(parsed)) return new Set();
        return new Set(parsed.filter((value) => typeof value === 'string' && value));
      } catch (_err) {
        return new Set();
      }
    }

    export function loadHiddenSessionIds() {
      return loadHiddenIdSet(STORAGE_KEYS.hiddenSessions);
    }

    export const HIDDEN_SESSION_IDS = loadHiddenSessionIds();
    export const HIDDEN_CLI_SESSION_IDS = loadHiddenIdSet(STORAGE_KEYS.hiddenCliSessions);

    export function normalizeTokenMode(mode) {
      return mode === 'billed' ? 'billed' : 'attributed';
    }

    export function loadTokenMode() {
      try {
        return normalizeTokenMode(localStorage.getItem(STORAGE_KEYS.tokenMode));
      } catch (_err) {
        return 'attributed';
      }
    }

    STATE.tokenMode = loadTokenMode();
    STATE.filters.tokenMode = STATE.tokenMode;

    export function persistHiddenSessionIds() {
      try {
        localStorage.setItem(STORAGE_KEYS.hiddenSessions, JSON.stringify(Array.from(HIDDEN_SESSION_IDS)));
      } catch (_err) {
        // Ignore storage failures (private mode / disabled storage).
      }
    }

    export function persistHiddenCliSessionIds() {
      try {
        localStorage.setItem(STORAGE_KEYS.hiddenCliSessions, JSON.stringify(Array.from(HIDDEN_CLI_SESSION_IDS)));
      } catch (_err) {
        // Ignore storage failures (private mode / disabled storage).
      }
    }

    export function persistTokenMode() {
      try {
        localStorage.setItem(STORAGE_KEYS.tokenMode, normalizeTokenMode(STATE.tokenMode));
      } catch (_err) {
        // Ignore storage failures (private mode / disabled storage).
      }
    }

    export function isSessionHidden(sessionId) {
      return HIDDEN_SESSION_IDS.has(sessionId);
    }

    export function isCliSessionHidden(sessionId) {
      return HIDDEN_CLI_SESSION_IDS.has(sessionId);
    }

    export function isBilledMode() {
      return normalizeTokenMode(STATE.tokenMode) === 'billed';
    }

    export function tokenModeLabel() {
      return isBilledMode() ? 'billed' : 'attributed';
    }

    // ---- Theme (dark/light) ----
    // The CSS palette contract lives entirely in web/styles/tokens.css via
    // `:root[data-theme="light"]` (explicit choice) and
    // `:root:not([data-theme])` + `prefers-color-scheme` (first-visit OS
    // default). This module only persists/restores an explicit user choice;
    // an inline script in index.html applies any saved value before the
    // bundle parses, to avoid a flash of the wrong theme.
    export function normalizeTheme(theme) {
      return theme === 'light' ? 'light' : 'dark';
    }

    export function loadTheme() {
      try {
        const raw = localStorage.getItem(STORAGE_KEYS.theme);
        if (raw === 'light' || raw === 'dark') return raw;
      } catch (_err) {
        // Ignore storage failures.
      }
      // No explicit choice yet: reflect whatever the pre-paint inline
      // script / prefers-color-scheme CSS already applied to <html>, so
      // the toggle button's initial label matches what the user sees.
      const current = document.documentElement.dataset.theme;
      if (current === 'light' || current === 'dark') return current;
      return 'dark';
    }

    export function persistTheme(theme) {
      try {
        localStorage.setItem(STORAGE_KEYS.theme, normalizeTheme(theme));
      } catch (_err) {
        // Ignore storage failures (private mode / disabled storage).
      }
    }

    STATE.theme = loadTheme();

    export function applyTheme(theme) {
      const normalized = normalizeTheme(theme);
      STATE.theme = normalized;
      document.documentElement.dataset.theme = normalized;
      persistTheme(normalized);
    }

    export function markSessionsHidden(sessionIds) {
      let changed = 0;
      for (const sessionId of sessionIds || []) {
        if (!sessionId || HIDDEN_SESSION_IDS.has(sessionId)) continue;
        HIDDEN_SESSION_IDS.add(sessionId);
        changed += 1;
      }
      if (changed) {
        persistHiddenSessionIds();
      }
      return changed;
    }

    export function markCliSessionsHidden(sessionIds) {
      let changed = 0;
      for (const sessionId of sessionIds || []) {
        if (!sessionId || HIDDEN_CLI_SESSION_IDS.has(sessionId)) continue;
        HIDDEN_CLI_SESSION_IDS.add(sessionId);
        changed += 1;
      }
      if (changed) {
        persistHiddenCliSessionIds();
      }
      return changed;
    }

    export function restoreHiddenChats() {
      if (!HIDDEN_SESSION_IDS.size) return;
      if (!confirm(`Restore ${HIDDEN_SESSION_IDS.size} hidden chats to the Chats tab?`)) return;
      HIDDEN_SESSION_IDS.clear();
      persistHiddenSessionIds();
      renderApp();
    }

    export function restoreHiddenCliSessions() {
      if (!HIDDEN_CLI_SESSION_IDS.size) return;
      if (!confirm(`Restore ${HIDDEN_CLI_SESSION_IDS.size} hidden CLI sessions to the CLI tab?`)) return;
      HIDDEN_CLI_SESSION_IDS.clear();
      persistHiddenCliSessionIds();
      renderApp();
    }

    export const PRICING_TABLE = __PRICING_JSON__;


    export function captureInputFocusState() {
      const activeEl = document.activeElement;
      if (!activeEl || !activeEl.id) return null;
      const tagName = String(activeEl.tagName || '').toLowerCase();
      if (tagName !== 'input' && tagName !== 'textarea') return null;
      const inputType = String(activeEl.type || '').toLowerCase();
      const supportsSelection = typeof activeEl.selectionStart === 'number' && typeof activeEl.selectionEnd === 'number' && inputType !== 'number';
      return {
        id: activeEl.id,
        selectionStart: supportsSelection ? activeEl.selectionStart : null,
        selectionEnd: supportsSelection ? activeEl.selectionEnd : null,
      };
    }

    export function restoreInputFocusState(state) {
      if (!state || !state.id) return;
      const nextEl = document.getElementById(state.id);
      if (!nextEl) return;
      nextEl.focus();
      if (state.selectionStart === null || state.selectionEnd === null) return;
      if (typeof nextEl.setSelectionRange !== 'function') return;
      try {
        nextEl.setSelectionRange(state.selectionStart, state.selectionEnd);
      } catch (_err) {
        // Some input types do not support selection ranges.
      }
    }
