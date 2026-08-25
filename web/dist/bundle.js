(() => {
  // web/js/state.js
  var APP_DATA = __APP_JSON__;
  var STORAGE_KEYS = {
    hiddenSessions: "copilot-dashboard-hidden-sessions-v1",
    hiddenCliSessions: "copilot-dashboard-hidden-cli-sessions-v1",
    tokenMode: "copilot-dashboard-token-mode-v1",
    lastTab: "copilot-dashboard-last-tab-v1",
    filters: "copilot-dashboard-filters-v1",
    theme: "copilot-dashboard-theme-v1"
  };
  var VALID_TABS = /* @__PURE__ */ new Set(["overview", "chats", "analysis", "cli", "reference"]);
  function loadLastTab() {
    try {
      const raw = localStorage.getItem(STORAGE_KEYS.lastTab);
      return VALID_TABS.has(raw) ? raw : "overview";
    } catch (_err) {
      return "overview";
    }
  }
  function persistLastTab(tabName) {
    try {
      if (VALID_TABS.has(tabName)) localStorage.setItem(STORAGE_KEYS.lastTab, tabName);
    } catch (_err) {
    }
  }
  var VALID_PERIODS = /* @__PURE__ */ new Set(["today", "7d", "30d", "month", "all", "custom"]);
  var VALID_SOURCES = /* @__PURE__ */ new Set(["all", "chat", "cli"]);
  function defaultFilters() {
    const legacyPeriod = (APP_DATA.periods && APP_DATA.periods.default || "monthly") === "allTime" ? "all" : "month";
    return { source: "all", period: legacyPeriod, start: null, end: null, tokenMode: "attributed" };
  }
  function loadFilters() {
    const base = defaultFilters();
    try {
      const raw = localStorage.getItem(STORAGE_KEYS.filters);
      const parsed = raw ? JSON.parse(raw) : null;
      if (!parsed || typeof parsed !== "object") return base;
      return {
        source: VALID_SOURCES.has(parsed.source) ? parsed.source : base.source,
        period: VALID_PERIODS.has(parsed.period) ? parsed.period : base.period,
        start: Number.isFinite(Number(parsed.start)) ? Number(parsed.start) : null,
        end: Number.isFinite(Number(parsed.end)) ? Number(parsed.end) : null,
        tokenMode: parsed.tokenMode === "billed" ? "billed" : "attributed"
      };
    } catch (_err) {
      return base;
    }
  }
  function persistFilters(filters) {
    try {
      localStorage.setItem(STORAGE_KEYS.filters, JSON.stringify(filters || {}));
    } catch (_err) {
    }
  }
  var STATE = {
    activeTab: loadLastTab(),
    usagePeriod: APP_DATA.periods && APP_DATA.periods.default || "monthly",
    filters: loadFilters(),
    tokenMode: "attributed",
    analysisTab: "models",
    toolImpactTab: "usage",
    dataTab: "prices",
    monthlyTrendMetric: "cost",
    toolCatalogSearch: "",
    toolCatalogSortKey: "descriptionTokens",
    toolCatalogSortDir: "desc",
    toolWasteSortKey: "wastedInputTokens",
    toolWasteSortDir: "desc",
    toolImpactSearch: "",
    search: "",
    cliSearch: "",
    cliFileSearch: "",
    cliPage: 1,
    cliPageSize: 10,
    cliModel: "",
    deleteTarget: "chats",
    model: "",
    page: 1,
    pageSize: 10,
    fileSearch: "",
    fileSortKey: "cost",
    fileSortDir: "desc",
    toolSortKey: "cost",
    toolSortDir: "desc",
    autoRefresh: false,
    refreshInterval: 6e4,
    refreshTimer: null,
    deleteMode: "all",
    deleteAgePreset: "week",
    deleteCustomDate: "",
    deleteKeepCount: 10
  };
  function loadHiddenIdSet(storageKey) {
    try {
      const raw = localStorage.getItem(storageKey);
      const parsed = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(parsed)) return /* @__PURE__ */ new Set();
      return new Set(parsed.filter((value) => typeof value === "string" && value));
    } catch (_err) {
      return /* @__PURE__ */ new Set();
    }
  }
  function loadHiddenSessionIds() {
    return loadHiddenIdSet(STORAGE_KEYS.hiddenSessions);
  }
  var HIDDEN_SESSION_IDS = loadHiddenSessionIds();
  var HIDDEN_CLI_SESSION_IDS = loadHiddenIdSet(STORAGE_KEYS.hiddenCliSessions);
  function normalizeTokenMode(mode) {
    return mode === "billed" ? "billed" : "attributed";
  }
  function loadTokenMode() {
    try {
      return normalizeTokenMode(localStorage.getItem(STORAGE_KEYS.tokenMode));
    } catch (_err) {
      return "attributed";
    }
  }
  STATE.tokenMode = loadTokenMode();
  STATE.filters.tokenMode = STATE.tokenMode;
  function persistHiddenSessionIds() {
    try {
      localStorage.setItem(STORAGE_KEYS.hiddenSessions, JSON.stringify(Array.from(HIDDEN_SESSION_IDS)));
    } catch (_err) {
    }
  }
  function persistHiddenCliSessionIds() {
    try {
      localStorage.setItem(STORAGE_KEYS.hiddenCliSessions, JSON.stringify(Array.from(HIDDEN_CLI_SESSION_IDS)));
    } catch (_err) {
    }
  }
  function persistTokenMode() {
    try {
      localStorage.setItem(STORAGE_KEYS.tokenMode, normalizeTokenMode(STATE.tokenMode));
    } catch (_err) {
    }
  }
  function isSessionHidden(sessionId) {
    return HIDDEN_SESSION_IDS.has(sessionId);
  }
  function isCliSessionHidden(sessionId) {
    return HIDDEN_CLI_SESSION_IDS.has(sessionId);
  }
  function isBilledMode() {
    return normalizeTokenMode(STATE.tokenMode) === "billed";
  }
  function tokenModeLabel() {
    return isBilledMode() ? "billed" : "attributed";
  }
  function normalizeTheme(theme) {
    return theme === "light" ? "light" : "dark";
  }
  function loadTheme() {
    try {
      const raw = localStorage.getItem(STORAGE_KEYS.theme);
      if (raw === "light" || raw === "dark") return raw;
    } catch (_err) {
    }
    const current = document.documentElement.dataset.theme;
    if (current === "light" || current === "dark") return current;
    return "dark";
  }
  function persistTheme(theme) {
    try {
      localStorage.setItem(STORAGE_KEYS.theme, normalizeTheme(theme));
    } catch (_err) {
    }
  }
  STATE.theme = loadTheme();
  function applyTheme(theme) {
    const normalized = normalizeTheme(theme);
    STATE.theme = normalized;
    document.documentElement.dataset.theme = normalized;
    persistTheme(normalized);
  }
  function markSessionsHidden(sessionIds) {
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
  function markCliSessionsHidden(sessionIds) {
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
  function restoreHiddenChats() {
    if (!HIDDEN_SESSION_IDS.size) return;
    if (!confirm(`Restore ${HIDDEN_SESSION_IDS.size} hidden chats to the Chats tab?`)) return;
    HIDDEN_SESSION_IDS.clear();
    persistHiddenSessionIds();
    renderApp();
  }
  function restoreHiddenCliSessions() {
    if (!HIDDEN_CLI_SESSION_IDS.size) return;
    if (!confirm(`Restore ${HIDDEN_CLI_SESSION_IDS.size} hidden CLI sessions to the CLI tab?`)) return;
    HIDDEN_CLI_SESSION_IDS.clear();
    persistHiddenCliSessionIds();
    renderApp();
  }
  var PRICING_TABLE = __PRICING_JSON__;
  function captureInputFocusState() {
    const activeEl = document.activeElement;
    if (!activeEl || !activeEl.id) return null;
    const tagName = String(activeEl.tagName || "").toLowerCase();
    if (tagName !== "input" && tagName !== "textarea") return null;
    const inputType = String(activeEl.type || "").toLowerCase();
    const supportsSelection = typeof activeEl.selectionStart === "number" && typeof activeEl.selectionEnd === "number" && inputType !== "number";
    return {
      id: activeEl.id,
      selectionStart: supportsSelection ? activeEl.selectionStart : null,
      selectionEnd: supportsSelection ? activeEl.selectionEnd : null
    };
  }
  function restoreInputFocusState(state) {
    if (!state || !state.id) return;
    const nextEl = document.getElementById(state.id);
    if (!nextEl) return;
    nextEl.focus();
    if (state.selectionStart === null || state.selectionEnd === null) return;
    if (typeof nextEl.setSelectionRange !== "function") return;
    try {
      nextEl.setSelectionRange(state.selectionStart, state.selectionEnd);
    } catch (_err) {
    }
  }

  // web/js/format.js
  function currentMonthKey() {
    const now = /* @__PURE__ */ new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    return `${year}-${month}`;
  }
  function formatMonthLabelFromKey(monthKey) {
    if (!monthKey || !/^\d{4}-\d{2}$/.test(String(monthKey))) {
      return "Current month";
    }
    const date = /* @__PURE__ */ new Date(`${monthKey}-01T12:00:00`);
    if (!Number.isFinite(date.getTime())) {
      return String(monthKey);
    }
    return date.toLocaleString(void 0, { month: "long", year: "numeric" });
  }
  function zeroTokenBlock() {
    return { input: 0, uncached: 0, output: 0, cached: 0, cost: 0 };
  }
  function addTokenBlock(target, block, factor = 1) {
    if (!target || !block) return target;
    target.input += Number(block.input || 0) * factor;
    target.uncached += Number(block.uncached || 0) * factor;
    target.output += Number(block.output || 0) * factor;
    target.cached += Number(block.cached || 0) * factor;
    target.cost += Number(block.cost || 0) * factor;
    return target;
  }
  function cloneTokenBlock(block) {
    const src = block || {};
    return {
      input: Number(src.input || 0),
      uncached: Number(src.uncached || 0),
      output: Number(src.output || 0),
      cached: Number(src.cached || 0),
      cost: Number(src.cost || 0)
    };
  }
  function pickTokenBlock(attributedBlock, billedBlock) {
    if (isBilledMode()) {
      return cloneTokenBlock(billedBlock || attributedBlock || zeroTokenBlock());
    }
    return cloneTokenBlock(attributedBlock || billedBlock || zeroTokenBlock());
  }
  function summaryDisplayTotals(summary) {
    return pickTokenBlock(summary == null ? void 0 : summary.totals, summary == null ? void 0 : summary.billedTotals);
  }
  function sessionDisplayTotals(session) {
    return pickTokenBlock(session == null ? void 0 : session.totals, session == null ? void 0 : session.billed_totals);
  }
  function eventDisplayChatTokens(event) {
    return pickTokenBlock(event == null ? void 0 : event.attribution_tokens, event == null ? void 0 : event.billed_tokens);
  }
  function cacheHitRateForBlock(block) {
    const input = Number((block == null ? void 0 : block.input) || 0);
    if (!input) return 0;
    return Number((block == null ? void 0 : block.cached) || 0) / input * 100;
  }
  function tokenScale(base, target) {
    const from = Number(base || 0);
    const to = Number(target || 0);
    if (from > 0) return to / from;
    if (to > 0) return 1;
    return 0;
  }
  function tokenScaleFactors(attributedBlock, billedBlock) {
    const source = attributedBlock || zeroTokenBlock();
    const target = billedBlock || source;
    return {
      input: tokenScale(source.input, target.input),
      uncached: tokenScale(source.uncached, target.uncached),
      output: tokenScale(source.output, target.output),
      cached: tokenScale(source.cached, target.cached),
      cost: tokenScale(source.cost, target.cost)
    };
  }
  function scaleTokenBlock(block, factors, factor = 1) {
    const src = block || zeroTokenBlock();
    const scale = factors || { input: 1, uncached: 1, output: 1, cached: 1, cost: 1 };
    return {
      input: Number(src.input || 0) * Number(scale.input || 0) * factor,
      uncached: Number(src.uncached || 0) * Number(scale.uncached || 0) * factor,
      output: Number(src.output || 0) * Number(scale.output || 0) * factor,
      cached: Number(src.cached || 0) * Number(scale.cached || 0) * factor,
      cost: Number(src.cost || 0) * Number(scale.cost || 0) * factor
    };
  }
  function sessionScaleFactors(session) {
    return tokenScaleFactors(session == null ? void 0 : session.totals, (session == null ? void 0 : session.billed_totals) || (session == null ? void 0 : session.totals));
  }
  function eventDisplayEstimatedTokens(event, session) {
    const estimated = cloneTokenBlock((event == null ? void 0 : event.estimated_tokens) || zeroTokenBlock());
    if (!isBilledMode()) return estimated;
    return scaleTokenBlock(estimated, sessionScaleFactors(session));
  }
  function sessionOverheadForMode(session) {
    const overhead = (session == null ? void 0 : session.overhead) || {};
    if (!isBilledMode()) return overhead;
    const adjusted = zeroOverheadBuckets();
    const factors = sessionScaleFactors(session);
    Object.keys(adjusted).forEach((key) => {
      if (overhead[key]) {
        addTokenBlock(adjusted[key], scaleTokenBlock(overhead[key], factors));
      }
    });
    return adjusted;
  }
  function escapeHtml(value) {
    return String(value != null ? value : "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function formatInteger(value) {
    return Math.round(Number(value || 0)).toLocaleString();
  }
  function formatCompact(value) {
    const n = Number(value || 0);
    if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
    if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
    return Math.round(n).toString();
  }
  function formatCost(value) {
    const n = Number(value || 0);
    if (Math.abs(n) >= 1) {
      return `$${n.toLocaleString(void 0, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return `$${n.toFixed(4)}`;
  }
  var CREDIT_USD = 0.01;
  function creditsFromCost(cost) {
    return Number(cost || 0) / CREDIT_USD;
  }
  function formatCreditValue(cost) {
    const credits = creditsFromCost(cost);
    if (Math.abs(credits) >= 1e3) return Math.round(credits).toLocaleString();
    return credits.toFixed(1);
  }
  var COST_SOURCE_INFO = {
    billed: {
      label: "exact",
      badgeClass: "confidence-high",
      title: "Exact: GitHub's own recorded charge for each call (total_nano_aiu), summed."
    },
    rates: {
      label: "exact",
      badgeClass: "confidence-high",
      title: "Exact: priced from the per-token rates GitHub actually applied to each call (token_details_json), which already include promotions, discounts and long-context tiers."
    },
    mixed: {
      label: "partly exact",
      badgeClass: "confidence-medium",
      title: "Mixed: some calls carry GitHub's billed figure, others had to be estimated from published rates. Treat the total as approximate."
    },
    estimate: {
      label: "estimated",
      badgeClass: "confidence-low",
      title: "Estimated from the published pricing table \u2014 no billed figure was recorded for these calls, so promotions and the 10% auto-model-selection discount are not reflected."
    }
  };
  function costProvenance(row) {
    const source = String(row && row.costSource || "estimate");
    const info = COST_SOURCE_INFO[source] || COST_SOURCE_INFO.estimate;
    const exact = row && typeof row.costExact === "boolean" ? row.costExact : source === "billed" || source === "rates";
    const counts = row && row.costSources || {};
    const breakdown = Object.keys(counts).map((key) => `${formatInteger(counts[key])} ${key}`).join(", ");
    return {
      source,
      exact,
      label: info.label,
      badgeClass: info.badgeClass,
      title: breakdown ? `${info.title} (calls by source: ${breakdown})` : info.title
    };
  }
  function costProvenanceBadge(row) {
    const p = costProvenance(row);
    return `<span class="badge ${p.badgeClass}" title="${escapeHtml(p.title)}">${escapeHtml(p.label)}</span>`;
  }
  function costLabel(row, noun = "cost") {
    return costProvenance(row).exact ? `Billed ${noun}` : `Estimated ${noun}`;
  }
  function formatDuration(ms) {
    const value = Number(ms || 0);
    if (!value) return "\u2014";
    if (value < 1e3) return `${value.toFixed(0)}ms`;
    return `${(value / 1e3).toFixed(2)}s`;
  }
  function formatTimestamp(ts) {
    if (!ts) return "\u2014";
    return new Date(Number(ts)).toLocaleString();
  }
  function formatPercent(value) {
    return `${Number(value || 0).toFixed(1)}%`;
  }
  function formatSigned(value) {
    const n = Number(value || 0);
    const prefix = n > 0 ? "+" : "";
    return `${prefix}${Math.round(n).toLocaleString()}`;
  }
  function sortArrow(key) {
    if (STATE.fileSortKey !== key) return "\u2195";
    return STATE.fileSortDir === "desc" ? "\u2193" : "\u2191";
  }
  function promptWindowLabel(breakdown) {
    if (!breakdown) return "\u2014";
    if (breakdown.max_context_window_tokens) {
      return `${formatCompact(breakdown.prompt_tokens)} / ${formatCompact(breakdown.max_context_window_tokens)} (${formatPercent(breakdown.used_percent_of_window)})`;
    }
    return formatCompact(breakdown.prompt_tokens);
  }
  function boundaryLabel(reason) {
    const labels = {
      model_switch: "model switch",
      context_reset: "context reset",
      cache_reset: "cache reset"
    };
    return labels[reason] || String(reason || "").replace(/_/g, " ");
  }
  function overheadLabel(key) {
    const labels = {
      system_prompt: "System Instructions",
      tool_definitions: "Tool Definitions",
      assistant_context: "Chat History",
      user_messages: "User Messages",
      tools: "Tools",
      files: "Files",
      unattributed: "Unattributed"
    };
    return labels[key] || String(key || "").replace(/_/g, " ");
  }
  function overheadColor(key) {
    const colors = {
      system_prompt: "var(--blue)",
      tool_definitions: "var(--purple)",
      assistant_context: "var(--orange)",
      user_messages: "var(--green)",
      tools: "var(--yellow)",
      files: "var(--teal)",
      unattributed: "var(--faint)"
    };
    return colors[key] || "var(--faint)";
  }
  function buildOverheadBreakdown(overhead, totalInput) {
    const keys = ["system_prompt", "tool_definitions", "assistant_context", "user_messages", "tools", "files", "unattributed"];
    const rows = keys.map((key) => {
      var _a, _b;
      return {
        key,
        label: overheadLabel(key),
        color: overheadColor(key),
        input: Number(((_a = overhead == null ? void 0 : overhead[key]) == null ? void 0 : _a.input) || 0),
        cost: Number(((_b = overhead == null ? void 0 : overhead[key]) == null ? void 0 : _b.cost) || 0)
      };
    });
    const normalizedTotal = Number(totalInput || 0);
    const assigned = rows.reduce((sum, row) => sum + row.input, 0);
    if (normalizedTotal > assigned) {
      const unattributed = rows.find((row) => row.key === "unattributed");
      if (unattributed) {
        unattributed.input += normalizedTotal - assigned;
      }
    }
    return rows.map((row) => ({
      ...row,
      pct: normalizedTotal ? row.input / normalizedTotal * 100 : 0
    }));
  }
  function calcModelCost(inputTokens, cachedTokens, outputTokens, pricing, cacheWriteTokens = 0) {
    const cacheWrite = Math.max(0, Number(cacheWriteTokens || 0));
    const cached = Math.max(0, Number(cachedTokens || 0));
    const uncached = Math.max(0, Number(inputTokens || 0) - cached - cacheWrite);
    const tier = pricing.longContext;
    const rates = tier && Number(inputTokens || 0) > Number(tier.threshold || 0) ? {
      input: tier.input,
      cached: tier.cached,
      // Absent on a long-context row means the model does not price cache
      // writes at all - keep the (zero) default rather than inventing one.
      cacheWrite: tier.cacheWrite === void 0 ? pricing.cacheWrite || 0 : tier.cacheWrite,
      output: tier.output
    } : { input: pricing.input, cached: pricing.cached, cacheWrite: pricing.cacheWrite || 0, output: pricing.output };
    return uncached / 1e6 * Number(rates.input || 0) + cached / 1e6 * Number(rates.cached || 0) + cacheWrite / 1e6 * Number(rates.cacheWrite || 0) + Number(outputTokens || 0) / 1e6 * Number(rates.output || 0);
  }

  // web/js/filters.js
  var VALID_PERIODS2 = /* @__PURE__ */ new Set(["today", "7d", "30d", "month", "all", "custom"]);
  var VALID_SOURCES2 = /* @__PURE__ */ new Set(["all", "chat", "cli"]);
  var VALID_FILTER_KEYS = /* @__PURE__ */ new Set(["source", "period", "start", "end", "tokenMode"]);
  function startOfLocalDay(ms) {
    const d = new Date(ms);
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  }
  function startOfCurrentMonth() {
    const d = /* @__PURE__ */ new Date();
    d.setDate(1);
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  }
  function currentFilters() {
    return { ...STATE.filters, tokenMode: normalizeTokenMode(STATE.tokenMode) };
  }
  function periodRange(period) {
    var _a, _b;
    const p = period || STATE.filters.period;
    const now = Date.now();
    switch (p) {
      case "today":
        return { start: startOfLocalDay(now), end: now };
      case "7d":
        return { start: now - 7 * 864e5, end: now };
      case "30d":
        return { start: now - 30 * 864e5, end: now };
      case "month":
        return { start: startOfCurrentMonth(), end: now };
      case "custom":
        return { start: (_a = STATE.filters.start) != null ? _a : null, end: (_b = STATE.filters.end) != null ? _b : null };
      case "all":
      default:
        return { start: null, end: null };
    }
  }
  function matchesSource(source) {
    const active = STATE.filters.source;
    if (active === "all") return true;
    return String(source || "") === active;
  }
  function filterInsightsBySource(insights) {
    const all = Array.isArray(insights) ? insights : [];
    const active = STATE.filters.source;
    if (active === "all") return { visible: all, hiddenCrossSource: 0, source: active };
    return {
      visible: all.filter((insight) => String((insight == null ? void 0 : insight.source) || "") === active),
      hiddenCrossSource: all.filter((insight) => String((insight == null ? void 0 : insight.source) || "") === "both").length,
      source: active
    };
  }
  function unifiedRowMs(row) {
    if (row && row.dayKey) {
      const t = (/* @__PURE__ */ new Date(`${row.dayKey}T00:00:00`)).getTime();
      return Number.isFinite(t) ? t : null;
    }
    if (row && row.monthKey) {
      const t = (/* @__PURE__ */ new Date(`${row.monthKey}-01T00:00:00`)).getTime();
      return Number.isFinite(t) ? t : null;
    }
    return null;
  }
  function filterUnifiedRows(rows) {
    const { start, end } = periodRange();
    return (rows || []).filter((row) => {
      const ms = unifiedRowMs(row);
      if (ms === null) return true;
      if (start !== null && ms < start) return false;
      if (end !== null && ms > end) return false;
      return true;
    });
  }
  function filterSessions(sessions, sourceKind) {
    if (!matchesSource(sourceKind)) return [];
    const { start, end } = periodRange();
    if (start === null && end === null) return sessions || [];
    return (sessions || []).filter((session) => {
      var _a, _b, _c, _d;
      const ts = Number((_d = (_c = (_b = (_a = session == null ? void 0 : session.timestamp) != null ? _a : session == null ? void 0 : session.lastActivity) != null ? _b : session == null ? void 0 : session.updatedAt) != null ? _c : session == null ? void 0 : session.createdAt) != null ? _d : 0);
      if (!ts) return true;
      if (start !== null && ts < start) return false;
      if (end !== null && ts > end) return false;
      return true;
    });
  }
  function syncLegacyUsagePeriod() {
    if (STATE.filters.period === "month") STATE.usagePeriod = "monthly";
    else if (STATE.filters.period === "all") STATE.usagePeriod = "allTime";
  }
  var TAB_SOURCE_REQUIREMENT = { chats: "chat", cli: "cli" };
  function setFilter(key, value) {
    if (!VALID_FILTER_KEYS.has(key)) return;
    if (key === "source" && !VALID_SOURCES2.has(value)) return;
    if (key === "period" && !VALID_PERIODS2.has(value)) return;
    STATE.filters[key] = value;
    syncLegacyUsagePeriod();
    persistFilters(STATE.filters);
    STATE.page = 1;
    STATE.cliPage = 1;
    if (key === "source") {
      const required = TAB_SOURCE_REQUIREMENT[STATE.activeTab];
      if (required && value !== "all" && value !== required) {
        STATE.activeTab = "overview";
      }
    }
    renderApp();
  }
  function setCustomRange(startMs, endMs) {
    STATE.filters.period = "custom";
    STATE.filters.start = Number.isFinite(Number(startMs)) ? Number(startMs) : null;
    STATE.filters.end = Number.isFinite(Number(endMs)) ? Number(endMs) : null;
    persistFilters(STATE.filters);
    STATE.page = 1;
    STATE.cliPage = 1;
    renderApp();
  }
  function applyCustomDateInputs() {
    const startEl = document.getElementById("filterCustomStart");
    const endEl = document.getElementById("filterCustomEnd");
    const startMs = startEl && startEl.value ? (/* @__PURE__ */ new Date(`${startEl.value}T00:00:00`)).getTime() : null;
    const endMs = endEl && endEl.value ? (/* @__PURE__ */ new Date(`${endEl.value}T23:59:59`)).getTime() : null;
    setCustomRange(Number.isFinite(startMs) ? startMs : null, Number.isFinite(endMs) ? endMs : null);
  }
  function subtabForActiveTab() {
    if (STATE.activeTab === "analysis") return STATE.analysisTab;
    if (STATE.activeTab === "reference") return STATE.dataTab;
    return "";
  }
  function encodeHashFromState() {
    var _a;
    const params = new URLSearchParams();
    params.set("tab", STATE.activeTab);
    const subtab = subtabForActiveTab();
    if (subtab) params.set("subtab", subtab);
    params.set("source", STATE.filters.source);
    params.set("period", STATE.filters.period);
    if (STATE.filters.period === "custom") {
      if (STATE.filters.start) params.set("start", String(STATE.filters.start));
      if (STATE.filters.end) params.set("end", String(STATE.filters.end));
    }
    params.set("tokenMode", normalizeTokenMode(STATE.tokenMode));
    const nextHash = `#${params.toString()}`;
    if (window.location.hash !== nextHash && typeof ((_a = window.history) == null ? void 0 : _a.replaceState) === "function") {
      window.history.replaceState(null, "", nextHash);
    }
  }
  function decodeHashIntoState() {
    const raw = String(window.location.hash || "").replace(/^#/, "");
    if (!raw) return;
    let params;
    try {
      params = new URLSearchParams(raw);
    } catch (_err) {
      return;
    }
    const tab = params.get("tab");
    if (tab && ["overview", "chats", "analysis", "cli", "reference"].includes(tab)) {
      STATE.activeTab = tab;
    }
    const subtab = params.get("subtab");
    if (subtab) {
      if (STATE.activeTab === "analysis") STATE.analysisTab = subtab;
      else if (STATE.activeTab === "reference") STATE.dataTab = subtab;
    }
    const source = params.get("source");
    if (VALID_SOURCES2.has(source)) STATE.filters.source = source;
    const period = params.get("period");
    if (VALID_PERIODS2.has(period)) STATE.filters.period = period;
    const start = params.get("start");
    const end = params.get("end");
    if (start && Number.isFinite(Number(start))) STATE.filters.start = Number(start);
    if (end && Number.isFinite(Number(end))) STATE.filters.end = Number(end);
    const tokenMode = params.get("tokenMode");
    if (tokenMode) {
      STATE.tokenMode = normalizeTokenMode(tokenMode);
      STATE.filters.tokenMode = STATE.tokenMode;
    }
    syncLegacyUsagePeriod();
    persistFilters(STATE.filters);
    const requiredSource = TAB_SOURCE_REQUIREMENT[STATE.activeTab];
    if (requiredSource && STATE.filters.source !== "all" && STATE.filters.source !== requiredSource) {
      STATE.activeTab = "overview";
    }
  }
  if (typeof window !== "undefined") {
    window.CopilotFilters = {
      currentFilters,
      periodRange,
      matchesSource,
      filterInsightsBySource,
      filterUnifiedRows,
      filterSessions,
      setFilter,
      setCustomRange,
      applyCustomDateInputs
    };
  }

  // web/js/aggregate.js
  function zeroUnifiedBucket() {
    return {
      attributed: zeroTokenBlock(),
      billed: zeroTokenBlock(),
      premiumRequests: 0,
      callCount: 0,
      modelCalls: 0,
      promptCount: 0,
      sessionCount: 0
    };
  }
  function addUnifiedBucket(target, src) {
    var _a, _b, _c, _d;
    if (!src) return target;
    addTokenBlock(target.attributed, src.attributed);
    addTokenBlock(target.billed, src.billed);
    target.premiumRequests += Number(src.premiumRequests || 0);
    target.callCount += Number(src.callCount || 0);
    target.modelCalls += Number((_b = (_a = src.modelCalls) != null ? _a : src.callCount) != null ? _b : 0);
    target.promptCount += Number((_d = (_c = src.promptCount) != null ? _c : src.callCount) != null ? _d : 0);
    target.sessionCount += Number(src.sessionCount || 0);
    return target;
  }
  function unifiedFilteredDailyRows() {
    var _a;
    return filterUnifiedRows(((_a = APP_DATA.unified) == null ? void 0 : _a.daily) || []);
  }
  function unifiedFilteredTotals() {
    const unified = APP_DATA.unified || {};
    const filters = currentFilters();
    const dailyRows = filterUnifiedRows(unified.daily || []);
    const totals = zeroUnifiedBucket();
    const pickSource = (row) => filters.source === "all" ? row : (row.bySource || {})[filters.source];
    if ((unified.daily || []).length) {
      dailyRows.forEach((row) => addUnifiedBucket(totals, pickSource(row)));
      return totals;
    }
    if (filters.period === "all") {
      if (filters.source === "all") {
        addUnifiedBucket(totals, unified.totals);
      } else {
        const row = (unified.bySource || []).find((r) => r.source === filters.source);
        addUnifiedBucket(totals, row);
      }
    }
    return totals;
  }
  function unifiedFilteredBySourceKey(sourceKey) {
    const unified = APP_DATA.unified || {};
    const dailyRows = filterUnifiedRows(unified.daily || []);
    const totals = zeroUnifiedBucket();
    if ((unified.daily || []).length) {
      dailyRows.forEach((row2) => addUnifiedBucket(totals, (row2.bySource || {})[sourceKey]));
      return totals;
    }
    const row = (unified.bySource || []).find((r) => r.source === sourceKey);
    addUnifiedBucket(totals, row);
    return totals;
  }
  function analysisForMode() {
    const bundle = activePeriodBundle();
    if (isBilledMode()) {
      return bundle.analysisBilled || bundle.analysis || APP_DATA.analysis || {};
    }
    return bundle.analysis || APP_DATA.analysis || {};
  }
  function zeroOverheadBuckets() {
    return {
      system_prompt: zeroTokenBlock(),
      tool_definitions: zeroTokenBlock(),
      assistant_context: zeroTokenBlock(),
      user_messages: zeroTokenBlock(),
      tools: zeroTokenBlock(),
      files: zeroTokenBlock(),
      unattributed: zeroTokenBlock()
    };
  }
  function emptyMonthlyBundle(monthKey) {
    var _a, _b, _c;
    const fallbackAnalysis = ((_c = (_b = (_a = APP_DATA) == null ? void 0 : _a.periods) == null ? void 0 : _b.allTime) == null ? void 0 : _c.analysis) || APP_DATA.analysis || {};
    return {
      monthKey,
      label: formatMonthLabelFromKey(monthKey),
      summary: {
        sessionCount: 0,
        chatCallCount: 0,
        toolCallCount: 0,
        messageCount: 0,
        modelCount: 0,
        segmentCount: 0,
        modelSwitchCount: 0,
        contextResetCount: 0,
        totals: zeroTokenBlock(),
        cacheHitRate: 0,
        aiCredits: 0,
        peakPromptTokens: 0
      },
      analysis: {
        models: [],
        tools: [],
        toolCatalog: [],
        files: [],
        topChats: [],
        slowestTools: [],
        overhead: zeroOverheadBuckets(),
        telemetry: fallbackAnalysis.telemetry || { sections: [], observedFields: [], entryTypes: {} },
        monthlyTrends: fallbackAnalysis.monthlyTrends || []
      },
      analysisBilled: {
        models: [],
        tools: [],
        toolCatalog: [],
        files: [],
        topChats: [],
        slowestTools: [],
        overhead: zeroOverheadBuckets(),
        telemetry: fallbackAnalysis.telemetry || { sections: [], observedFields: [], entryTypes: {} },
        monthlyTrends: fallbackAnalysis.monthlyTrends || []
      },
      sessionIds: []
    };
  }
  function activePeriodBundle() {
    const periods = APP_DATA.periods || {};
    if (STATE.usagePeriod === "allTime") {
      return periods.allTime || {
        summary: APP_DATA.summary || {},
        analysis: APP_DATA.analysis || {},
        sessionIds: (APP_DATA.sessions || []).map((session) => session.id)
      };
    }
    const monthly = periods.monthly;
    const monthKey = currentMonthKey();
    if (monthly && monthly.monthKey === monthKey) {
      return monthly;
    }
    return emptyMonthlyBundle(monthKey);
  }
  function activeSummary() {
    return activePeriodBundle().summary || APP_DATA.summary || {};
  }
  function activeAnalysis() {
    return activePeriodBundle().analysis || APP_DATA.analysis || {};
  }
  function activePeriodLabel() {
    var _a, _b;
    if (STATE.usagePeriod === "allTime") {
      return ((_b = (_a = APP_DATA.periods) == null ? void 0 : _a.labels) == null ? void 0 : _b.allTime) || "All time";
    }
    const bundle = activePeriodBundle();
    if (bundle == null ? void 0 : bundle.label) return bundle.label;
    return formatMonthLabelFromKey(currentMonthKey());
  }
  function sessionsForActivePeriod() {
    const bundle = activePeriodBundle();
    if (!Array.isArray(bundle == null ? void 0 : bundle.sessionIds)) {
      return APP_DATA.sessions || [];
    }
    const allowed = new Set(bundle.sessionIds);
    return (APP_DATA.sessions || []).filter((session) => allowed.has(session.id));
  }
  function visibleSessions() {
    return sessionsForActivePeriod().filter((session) => !isSessionHidden(session.id));
  }
  function visibleCliSessions() {
    return ((APP_DATA.cli || {}).sessions || []).filter((session) => !isCliSessionHidden(session.id));
  }
  function filteredSessions() {
    return filterSessions(visibleSessions(), "chat").filter((session) => {
      var _a;
      const title = (session.title || "").toLowerCase();
      const models = (((_a = session.model_names) == null ? void 0 : _a.length) ? session.model_names : [session.model]).filter(Boolean).map((name) => String(name).toLowerCase());
      const sessionId = String(session.session_id || session.id || "").toLowerCase();
      const sourceIp = String(session.source_ip || "").toLowerCase();
      const search = STATE.search.toLowerCase();
      const searchMatch = !search || title.includes(search) || sessionId.includes(search) || sourceIp.includes(search) || models.some((name) => name.includes(search));
      const modelMatch = !STATE.model || models.includes(STATE.model.toLowerCase());
      return searchMatch && modelMatch;
    });
  }
  function pagedSessions() {
    const sessions = filteredSessions();
    const start = (STATE.page - 1) * STATE.pageSize;
    return {
      all: sessions,
      slice: sessions.slice(start, start + STATE.pageSize),
      pageCount: Math.max(1, Math.ceil(sessions.length / STATE.pageSize))
    };
  }
  function monthlyTrendMetricConfig() {
    return {
      cost: {
        label: "Cost",
        short: "Cost",
        color: "var(--teal)",
        value: (row) => {
          var _a;
          return Number(((_a = row == null ? void 0 : row.totals) == null ? void 0 : _a.cost) || 0);
        },
        format: (value) => formatCost(value)
      },
      input: {
        label: "Input tokens",
        short: "Input",
        color: "var(--blue)",
        value: (row) => {
          var _a;
          return Number(((_a = row == null ? void 0 : row.totals) == null ? void 0 : _a.input) || 0);
        },
        format: (value) => formatInteger(value)
      },
      uncached: {
        label: "Uncached input",
        short: "Uncached",
        color: "var(--yellow)",
        value: (row) => {
          var _a;
          return Number(((_a = row == null ? void 0 : row.totals) == null ? void 0 : _a.uncached) || 0);
        },
        format: (value) => formatInteger(value)
      },
      cached: {
        label: "Cached input",
        short: "Cached",
        color: "var(--green)",
        value: (row) => {
          var _a;
          return Number(((_a = row == null ? void 0 : row.totals) == null ? void 0 : _a.cached) || 0);
        },
        format: (value) => formatInteger(value)
      },
      output: {
        label: "Output tokens",
        short: "Output",
        color: "var(--orange)",
        value: (row) => {
          var _a;
          return Number(((_a = row == null ? void 0 : row.totals) == null ? void 0 : _a.output) || 0);
        },
        format: (value) => formatInteger(value)
      },
      sessions: {
        label: "Sessions",
        short: "Sessions",
        color: "var(--purple)",
        value: (row) => Number((row == null ? void 0 : row.sessionCount) || 0),
        format: (value) => formatInteger(value)
      },
      chatCalls: {
        label: "Chat calls",
        short: "Chat calls",
        color: "var(--blue)",
        value: (row) => Number((row == null ? void 0 : row.chatCallCount) || 0),
        format: (value) => formatInteger(value)
      },
      toolCalls: {
        label: "Tool calls",
        short: "Tool calls",
        color: "var(--yellow)",
        value: (row) => Number((row == null ? void 0 : row.toolCallCount) || 0),
        format: (value) => formatInteger(value)
      },
      cacheHitRate: {
        label: "Cache hit rate",
        short: "Cache hit %",
        color: "var(--green)",
        value: (row) => Number((row == null ? void 0 : row.cacheHitRate) || 0),
        format: (value) => formatPercent(value),
        isRate: true
      }
    };
  }
  function cliMonthlyBuckets() {
    const cli = APP_DATA.cli || {};
    const map = {};
    const bucketFor = (monthKey) => map[monthKey] || (map[monthKey] = { sessionCount: 0, cost: 0 });
    (cli.sessions || []).forEach((session) => {
      const callRows = Array.isArray(session.callBuckets) && session.callBuckets.length ? session.callBuckets : null;
      if (callRows) {
        const months = /* @__PURE__ */ new Set();
        callRows.forEach((row) => {
          const monthKey = row.monthKey || (row.dayKey ? String(row.dayKey).slice(0, 7) : null);
          if (!monthKey) return;
          bucketFor(monthKey).cost += Number(row.cost || 0);
          months.add(monthKey);
        });
        months.forEach((monthKey) => {
          bucketFor(monthKey).sessionCount += 1;
        });
        return;
      }
      const ts = session.lastActivity || session.updatedAt || session.createdAt;
      if (!ts) return;
      const d = new Date(ts);
      const bucket = bucketFor(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
      bucket.sessionCount += 1;
      bucket.cost += Number(session.cost || 0);
    });
    return map;
  }
  function visibleSessionsSortedByTimestamp() {
    return visibleSessions().slice().sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0));
  }
  function visibleCliSessionsSortedByTimestamp() {
    return visibleCliSessions().slice().sort((a, b) => Number(b.lastActivity || 0) - Number(a.lastActivity || 0));
  }
  function computeChatDeletionTargets() {
    const isCli = STATE.deleteTarget === "cli";
    const sessions = isCli ? visibleCliSessionsSortedByTimestamp() : visibleSessionsSortedByTimestamp();
    const timestampOf = (session) => Number((isCli ? session.lastActivity : session.timestamp) || 0);
    const mode = STATE.deleteMode || "all";
    if (!sessions.length) return [];
    if (mode === "all") {
      return sessions.map((session) => session.id);
    }
    if (mode === "keep_last") {
      const keepCount = Math.max(1, Number(STATE.deleteKeepCount || 10));
      return sessions.slice(keepCount).map((session) => session.id);
    }
    if (mode === "before_date") {
      let cutoffMs = 0;
      if (STATE.deleteAgePreset === "day") {
        cutoffMs = Date.now() - 24 * 60 * 60 * 1e3;
      } else if (STATE.deleteAgePreset === "week") {
        cutoffMs = Date.now() - 7 * 24 * 60 * 60 * 1e3;
      } else if (STATE.deleteAgePreset === "month") {
        cutoffMs = Date.now() - 30 * 24 * 60 * 60 * 1e3;
      } else {
        if (!STATE.deleteCustomDate) return [];
        cutoffMs = (/* @__PURE__ */ new Date(`${STATE.deleteCustomDate}T00:00:00`)).getTime();
        if (!Number.isFinite(cutoffMs)) return [];
      }
      return sessions.filter((session) => timestampOf(session) < cutoffMs).map((session) => session.id);
    }
    return [];
  }

  // web/js/tables.js
  function renderStatCell(label, value, className = "", hideMobile = false) {
    return `
        <div class="stat-col ${hideMobile ? "hide-mobile" : ""}">
          <div class="label">${label}</div>
          <div class="value ${className}">${value}</div>
        </div>`;
  }
  function renderPagination(allCount, pageCount) {
    return `
        <div class="pagination">
          <div class="note">Showing ${allCount ? `${(STATE.page - 1) * STATE.pageSize + 1}-${Math.min(STATE.page * STATE.pageSize, allCount)}` : "0"} of ${formatInteger(allCount)} chats</div>
          <div class="pagination-controls">
            <label class="note">Per page</label>
            <select onchange="setPageSize(this.value)">
              ${[5, 10, 20, 50, 100].map((size) => `<option value="${size}" ${STATE.pageSize === size ? "selected" : ""}>${size}</option>`).join("")}
            </select>
            <button type="button" onclick="changePage(-1)" ${STATE.page <= 1 ? "disabled" : ""}>Prev</button>
            <span class="note">Page ${STATE.page} / ${pageCount}</span>
            <button type="button" onclick="changePage(1)" ${STATE.page >= pageCount ? "disabled" : ""}>Next</button>
          </div>
        </div>`;
  }
  function renderTable(columns, rows, options = {}) {
    const rowRenderer = options.rowRenderer || ((row) => `<tr>${columns.map((column) => `<td class="${column.numeric ? "num" : ""}">${column.render(row)}</td>`).join("")}</tr>`);
    const exportId = options.exportId;
    if (exportId) registerTableExport(exportId, columns, rows, options.exportFilename);
    return `
        <div class="panel">
          ${exportId ? renderCsvExportButton(exportId) : ""}
          <table>
            <thead>
              <tr>${columns.map((column) => `<th class="${column.numeric ? "num" : ""}">${column.header ? column.header() : escapeHtml(column.title)}</th>`).join("")}</tr>
            </thead>
            <tbody>${rows.map((row) => rowRenderer(row)).join("")}</tbody>
          </table>
        </div>`;
  }
  function sortRows(rows, sortKey, sortDir) {
    const dir = sortDir === "desc" ? -1 : 1;
    rows.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "string" || typeof bv === "string") return String(av || "").localeCompare(String(bv || "")) * dir;
      return (Number(av || 0) - Number(bv || 0)) * dir;
    });
    return rows;
  }
  function sortFiles(sourceRows) {
    const rows = [...sourceRows || []];
    rows.sort((a, b) => {
      const key = STATE.fileSortKey;
      const dir = STATE.fileSortDir === "desc" ? -1 : 1;
      const av = a[key];
      const bv = b[key];
      if (typeof av === "string" || typeof bv === "string") {
        return String(av).localeCompare(String(bv)) * dir;
      }
      return (Number(av || 0) - Number(bv || 0)) * dir;
    });
    return rows;
  }
  var TABLE_EXPORT_REGISTRY = /* @__PURE__ */ new Map();
  function registerTableExport(exportId, columns, rows, filename) {
    TABLE_EXPORT_REGISTRY.set(exportId, {
      columns: columns || [],
      rows: rows || [],
      filename: filename || `${exportId || "export"}.csv`
    });
  }
  function renderCsvExportButton(exportId, label = "\u2B07 CSV") {
    return `<div class="table-export-bar" style="display:flex;justify-content:flex-end;margin-bottom:8px"><button type="button" class="copy-button" onclick="exportTableCsv('${escapeHtml(String(exportId))}')">${escapeHtml(label)}</button></div>`;
  }
  function stripHtmlToText(html) {
    return String(html === null || html === void 0 ? "" : html).replace(/<[^>]*>/g, "").replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&").replace(/&lt;/gi, "<").replace(/&gt;/gi, ">").replace(/&quot;/gi, '"').replace(/&#39;/gi, "'").replace(/\s+/g, " ").trim();
  }
  function csvEscapeField(value) {
    let text = value === null || value === void 0 ? "" : String(value);
    if (/^[=+\-@]/.test(text)) text = `'${text}`;
    if (/[",\n\r]/.test(text)) text = `"${text.replace(/"/g, '""')}"`;
    return text;
  }
  function tableRowsToCsv(columns, rows) {
    const cols = columns || [];
    const header = cols.map((column) => csvEscapeField(column.title || "")).join(",");
    const body = (rows || []).map((row) => cols.map((column) => {
      const raw = typeof column.csv === "function" ? column.csv(row) : stripHtmlToText(typeof column.render === "function" ? column.render(row) : "");
      return csvEscapeField(raw);
    }).join(",")).join("\r\n");
    return body ? `${header}\r
${body}` : header;
  }
  function downloadCsv(filename, csvText) {
    const blob = new Blob([csvText], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename || "export.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1e3);
  }
  function exportTableCsv(exportId) {
    const entry = TABLE_EXPORT_REGISTRY.get(exportId);
    if (!entry) return;
    downloadCsv(entry.filename, tableRowsToCsv(entry.columns, entry.rows));
  }
  if (typeof window !== "undefined") {
    Object.assign(window, { exportTableCsv });
  }

  // web/js/tab-chats.js
  function renderSessionMeta(session) {
    var _a, _b, _c, _d;
    const dur = session.duration_ms || 0;
    const durLabel = dur > 6e4 ? `${(dur / 6e4).toFixed(1)}min` : dur > 1e3 ? `${(dur / 1e3).toFixed(0)}s` : "\u2014";
    const modelNames = ((_a = session.model_names) == null ? void 0 : _a.length) ? session.model_names.join(", ") : session.model || "unknown";
    const totals = sessionDisplayTotals(session);
    return `
        <div class="session-meta">
          <div class="meta-card"><div class="label">Source IP</div><div class="value">${escapeHtml(session.source_ip || "unknown-ip")}</div></div>
          <div class="meta-card"><div class="label">Session ID</div><div class="value">${escapeHtml(session.session_id || session.id || "unknown")}</div></div>
          <div class="meta-card"><div class="label">Primary model</div><div class="value">${escapeHtml(session.model || "unknown")}</div></div>
          <div class="meta-card"><div class="label">Models used</div><div class="value">${escapeHtml(modelNames)}</div></div>
          <div class="meta-card"><div class="label">Duration</div><div class="value">${durLabel}</div></div>
          <div class="meta-card"><div class="label">Segments</div><div class="value">${formatInteger(session.segment_count || 0)}</div></div>
          <div class="meta-card"><div class="label">Total input</div><div class="value input">${formatInteger(totals.input)}</div></div>
          <div class="meta-card"><div class="label">Uncached input</div><div class="value uncached">${formatInteger(totals.uncached)}</div></div>
          <div class="meta-card"><div class="label">Cached-read</div><div class="value cached">${formatInteger(totals.cached)}</div></div>
          <div class="meta-card"><div class="label">Total output</div><div class="value output">${formatInteger(totals.output)}</div></div>
          <div class="meta-card"><div class="label">${isBilledMode() ? "Billed cost" : "Attributed est. cost"}</div><div class="value cost">${formatCost(totals.cost)}</div></div>
          <div class="meta-card"><div class="label">Cache hit rate</div><div class="value cached">${formatPercent(cacheHitRateForBlock(totals))}</div></div>
          <div class="meta-card"><div class="label">Peak prompt</div><div class="value">${formatInteger(session.peak_prompt_tokens)}</div></div>
          <div class="meta-card"><div class="label">Model switches</div><div class="value">${formatInteger(((_b = session.boundary_counts) == null ? void 0 : _b.model_switch) || 0)}</div></div>
          <div class="meta-card"><div class="label">Context resets</div><div class="value">${formatInteger(((_c = session.boundary_counts) == null ? void 0 : _c.context_reset) || 0)}</div></div>
          <div class="meta-card"><div class="label">Cache resets</div><div class="value">${formatInteger(((_d = session.boundary_counts) == null ? void 0 : _d.cache_reset) || 0)}</div></div>
        </div>`;
  }
  function renderContextBreakdown(breakdown) {
    if (!breakdown) {
      return '<div class="note">No context window breakdown available.</div>';
    }
    const segments = breakdown.categories.map((item) => {
      const colors = {
        system_instructions: "var(--blue)",
        tool_definitions: "var(--purple)",
        messages: "var(--orange)",
        tool_results: "var(--green)",
        other: "var(--faint)"
      };
      return `<div title="${escapeHtml(item.label)} \xB7 ${formatInteger(item.tokens)} tokens (${formatPercent(item.percent_of_prompt)} of prompt)" style="width:${item.percent_of_prompt}%; background:${colors[item.key]}; height:100%;"></div>`;
    }).join("");
    const reserved = breakdown.reserved_percent_of_window ? `<div title="Reserved for response \xB7 ${formatInteger(breakdown.reserved_response_tokens)} tokens" style="width:${breakdown.reserved_percent_of_window}%; height:100%; background: repeating-linear-gradient(135deg, rgba(188,140,255,.45), rgba(188,140,255,.45) 6px, rgba(188,140,255,.18) 6px, rgba(188,140,255,.18) 12px);"></div>` : "";
    return `
        <div class="event-section">
          <h4>Context window estimate</h4>
          <div class="note">Prompt now: <strong>${promptWindowLabel(breakdown)}</strong> \xB7 Cached inside prompt: <strong>${formatInteger(breakdown.cached_tokens)}</strong> \xB7 Uncached prompt: <strong>${formatInteger(breakdown.uncached_tokens)}</strong></div>
          <div style="display:flex; width:100%; height:16px; overflow:hidden; border-radius:999px; margin:12px 0; background:var(--overlay-06);border:1px solid var(--overlay-08);">
            ${segments}
            ${reserved}
          </div>
          <table>
            <thead>
              <tr><th>Section</th><th class="num">Tokens</th><th class="num">% of prompt</th><th class="num">% of window</th></tr>
            </thead>
            <tbody>
              ${breakdown.categories.map((item) => `<tr><td>${escapeHtml(item.label)}</td><td class="num">${formatInteger(item.tokens)}</td><td class="num">${formatPercent(item.percent_of_prompt)}</td><td class="num">${item.percent_of_window ? formatPercent(item.percent_of_window) : "\u2014"}</td></tr>`).join("")}
              ${breakdown.reserved_response_tokens ? `<tr><td>Reserved for response</td><td class="num">${formatInteger(breakdown.reserved_response_tokens)}</td><td class="num">\u2014</td><td class="num">${breakdown.reserved_percent_of_window ? formatPercent(breakdown.reserved_percent_of_window) : "\u2014"}</td></tr>` : ""}
            </tbody>
          </table>
        </div>`;
  }
  function renderEventDetailSections(event) {
    var _a;
    if (event.kind === "user_message") {
      return `<div class="event-section"><h4>Full user message</h4><pre>${escapeHtml(event.content || "")}</pre></div>`;
    }
    if (event.kind === "tool") {
      const files = ((_a = event.files) == null ? void 0 : _a.length) ? `<div class="pill-list">${event.files.map((file) => `<span class="pill">${escapeHtml(file)}</span>`).join("")}</div>` : '<div class="note">No file path detected in tool arguments.</div>';
      return `
          <div class="event-body-grid">
            <div class="event-section"><h4>Files involved</h4>${files}</div>
            <div class="split-grid">
              <div class="event-section"><h4>Tool input</h4><pre>${escapeHtml(event.args_pretty || "")}</pre></div>
              <div class="event-section"><h4>Tool output</h4><pre>${escapeHtml(event.result_text || "")}</pre></div>
            </div>
          </div>`;
    }
    const emittedTools = (event.tool_calls_emitted || []).length ? `<div class="event-section"><h4>Tools emitted by this chat call</h4><div class="message-list">${event.tool_calls_emitted.map((tool) => `<div class="message-card"><div class="message-header"><span class="badge tool">Tool</span><strong>${escapeHtml(tool.name)}</strong></div><pre>${escapeHtml(tool.arguments || "")}</pre></div>`).join("")}</div></div>` : "";
    const boundarySummary = (event.boundary_reasons || []).length ? `<div class="event-section"><h4>Segment boundary</h4><div class="pill-list">${event.boundary_reasons.map((reason) => `<span class="badge boundary">${escapeHtml(boundaryLabel(reason))}</span>`).join("")}</div><div class="note" style="margin-top:8px">${isBilledMode() ? "This call started a new internal segment. In billed mode we use per-call billed totals directly." : "This call started a new internal segment, so tool/file attribution uses the full billed input for this call instead of only the prompt-growth delta from the previous call."}</div></div>` : "";
    return `
        <div class="event-body-grid">
          ${boundarySummary}
          ${renderContextBreakdown(event.context_breakdown)}
          <div class="split-grid">
            <div class="event-section"><h4>Reasoning</h4><pre>${escapeHtml(event.reasoning || "[not recorded]")}</pre></div>
            <div class="event-section"><h4>Assistant output</h4><pre>${escapeHtml(event.response_text || "[empty]")}</pre></div>
          </div>
          ${emittedTools}
        </div>`;
  }
  function renderEvent(event, session) {
    const kindBadgeClass = event.kind === "chat" ? "chat" : event.kind === "tool" ? "tool" : "user";
    const timing = `${formatTimestamp(event.ts)} \xB7 ${formatDuration(event.duration_ms)}`;
    const modeBadge = event.kind === "tool" ? `<span class="badge mode-${event.mode || "other"}">${escapeHtml(event.mode || "other")}</span>` : "";
    const genAiButton = event.kind === "chat" ? `<button type="button" class="genai-button" onclick="event.stopPropagation(); openGenAiModal('${session.id}', '${event.id}')">GenAI details</button>` : "";
    const boundaryBadges = (event.boundary_reasons || []).map((reason) => `<span class="badge boundary">${escapeHtml(boundaryLabel(reason))}</span>`).join("");
    if (event.kind === "chat") {
      const chatTokens = eventDisplayChatTokens(event);
      return `
          <details class="event-card">
            <summary class="event-summary-row">
              <div class="title-col">
                <div class="title-line">
                  <span class="badge ${kindBadgeClass}">chat</span>
                  <span class="title-text">${escapeHtml(event.title)}</span>
                  <span class="badge source">${escapeHtml(event.source)}</span>
                  ${boundaryBadges}
                  ${genAiButton}
                </div>
                <div class="subtext">${escapeHtml(timing)} \xB7 segment ${formatInteger(event.segment_index || 1)} \xB7 prompt snapshot + ${escapeHtml(tokenModeLabel())} call totals</div>
              </div>
              ${renderStatCell("Prompt now", formatInteger(event.prompt_tokens))}
              ${renderStatCell("Total input", formatInteger(chatTokens.input), "input")}
              ${renderStatCell("Uncached", formatInteger(chatTokens.uncached), "uncached")}
              ${renderStatCell("Cached-read", formatInteger(chatTokens.cached), "cached", true)}
              ${renderStatCell("Output", formatInteger(chatTokens.output), "output", true)}
              ${renderStatCell(isBilledMode() ? "Billed cost" : "Attributed est. cost", formatCost(chatTokens.cost), "cost")}
            </summary>
            <div class="event-body">${renderEventDetailSections(event)}</div>
          </details>`;
    }
    const estimated = eventDisplayEstimatedTokens(event, session);
    return `
        <details class="event-card">
          <summary class="event-summary-row">
            <div class="title-col">
              <div class="title-line">
                <span class="badge ${kindBadgeClass}">${escapeHtml(event.kind.replace("_", " "))}</span>
                <span class="title-text">${escapeHtml(event.title)}</span>
                <span class="badge source">${escapeHtml(event.source)}</span>
                ${modeBadge}
              </div>
              <div class="subtext">${escapeHtml(timing)} \xB7 estimated ${escapeHtml(tokenModeLabel())} impact</div>
            </div>
            ${renderStatCell("Status", escapeHtml(event.status || "\u2014"))}
            ${renderStatCell("Duration", formatDuration(event.duration_ms))}
            ${renderStatCell("Input", "\u2248 " + formatInteger(estimated.input), "input")}
            ${renderStatCell("Output", "\u2248 " + formatInteger(estimated.output), "output")}
            ${renderStatCell("Cached", "\u2248 " + formatInteger(estimated.cached), "cached", true)}
            ${renderStatCell("Cost", formatCost(estimated.cost), "cost")}
          </summary>
          <div class="event-body">${renderEventDetailSections(event)}</div>
        </details>`;
  }
  function renderSessionTokenBreakdown(session) {
    const overhead = sessionOverheadForMode(session);
    const totals = sessionDisplayTotals(session);
    const totalInput = Number(totals.input || 0);
    if (!totalInput) return "";
    const categories = buildOverheadBreakdown(overhead, totalInput);
    const definitions = [
      "<strong>Chat History</strong> = earlier assistant replies carried forward into later turns.",
      "<strong>Tools</strong> = tool-call payload inside chat context (tool call arguments/results, plus non-file tool metadata).",
      "<strong>Files</strong> = file-related context from read/edit tool turns (mode-aware split estimate)."
    ];
    const segments = categories.filter((c) => c.pct > 0).map((c) => `<div title="${escapeHtml(c.label)} \xB7 ${formatInteger(c.input)} tokens (${c.pct.toFixed(1)}%)" style="width:${c.pct}%;background:${c.color};height:100%;"></div>`).join("");
    return `
        <div class="event-section" style="margin-bottom:14px">
          <h4>Session token breakdown (${isBilledMode() ? "estimated billed distribution" : "estimated attribution"})</h4>
          <div class="note small" style="margin-bottom:8px">Where did this chat's <strong>${formatInteger(totalInput)}</strong> ${escapeHtml(tokenModeLabel())} input tokens go? This uses the same category model as the global token breakdown. Numbers can differ from a single Copilot screenshot because screenshots show one call's current prompt window, while this view aggregates usage across many calls.</div>
          <div style="display:flex;width:100%;height:16px;overflow:hidden;border-radius:999px;margin:8px 0;background:var(--overlay-06);border:1px solid var(--overlay-08);">
            ${segments}
          </div>
          <table style="margin-top:8px">
            <thead><tr><th>Category</th><th class="num">Input tokens</th><th class="num">% of total</th><th class="num">Est. cost</th></tr></thead>
            <tbody>
              ${categories.map((c) => `<tr><td><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${c.color};margin-right:6px;vertical-align:middle"></span>${escapeHtml(c.label)}</td><td class="num">${formatInteger(c.input)}</td><td class="num">${c.pct.toFixed(1)}%</td><td class="num">${c.cost > 0 ? formatCost(c.cost) : "\u2014"}</td></tr>`).join("")}
            </tbody>
          </table>
          <div class="note small" style="margin-top:10px">${definitions.join("<br>")}</div>
        </div>`;
  }
  function renderSession(session, sessionIndex) {
    var _a;
    const dur = session.duration_ms || 0;
    const durLabel = dur > 6e4 ? `${(dur / 6e4).toFixed(0)}m` : dur > 1e3 ? `${(dur / 1e3).toFixed(0)}s` : dur ? `${dur.toFixed(0)}ms` : "\u2014";
    const modelNames = (((_a = session.model_names) == null ? void 0 : _a.length) ? session.model_names : [session.model]).filter(Boolean);
    const modelBadges = modelNames.slice(0, 3).map((modelName) => `<span class="badge model">${escapeHtml(modelName)}</span>`).join("");
    const extraModels = modelNames.length > 3 ? `<span class="badge source">+${formatInteger(modelNames.length - 3)} models</span>` : "";
    const sourceBadge = `<span class="badge source">${escapeHtml(session.source_ip || "unknown-ip")}</span>`;
    const totals = sessionDisplayTotals(session);
    return `
        <details class="session-card">
          <summary class="session-summary-row">
            <div class="title-col">
              <div class="title-line">
                ${modelBadges || `<span class="badge model">${escapeHtml(session.model || "unknown")}</span>`}
                ${extraModels}
                ${sourceBadge}
                <span class="title-text">${escapeHtml(session.title)}</span>
              </div>
              <div class="subtext">${escapeHtml(formatTimestamp(session.timestamp))} \xB7 ${formatInteger(session.chat_count)} calls \xB7 ${formatInteger(session.tool_count)} tools \xB7 ${formatInteger(session.segment_count || 0)} segments \xB7 ${durLabel}</div>
            </div>
            ${renderStatCell("Total input", formatInteger(totals.input), "input")}
            ${renderStatCell("Uncached", formatInteger(totals.uncached), "uncached")}
            ${renderStatCell("Cached-read", formatInteger(totals.cached), "cached", true)}
            ${renderStatCell("Output", formatInteger(totals.output), "output")}
            ${renderStatCell("Segments", formatInteger(session.segment_count || 0))}
            ${renderStatCell("Cost", formatCost(totals.cost), "cost")}
          </summary>
          <div class="session-body">
            <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:12px;flex-wrap:wrap">
              <button type="button" class="action-chip action-chip--blue" onclick="event.stopPropagation();openFullChatModal('${session.id}')">\u{1F4C2} Show full chat</button>
              <button type="button" class="action-chip action-chip--purple" onclick="event.stopPropagation();openModelCompareModal('${session.id}')">\u2696 Compare models</button>
              <button type="button" class="action-chip action-chip--teal" onclick="event.stopPropagation();exportSessionToJson('${session.id}')">\u2B07 Export chat JSON</button>
              <button type="button" class="action-chip action-chip--red" onclick="event.stopPropagation();deleteSessionPrompt('${session.id}')">\u{1F5D1} Delete chat</button>
            </div>
            ${renderSessionMeta(session)}
            ${renderSessionTokenBreakdown(session)}
            <div class="note small" style="margin-top:12px;text-align:center">Per-call timeline, tool calls and GenAI details load on demand \u2014 press <strong>\u{1F4C2} Show full chat</strong>.</div>
          </div>
        </details>`;
  }
  function renderChatsTab() {
    const models = [...new Set(visibleSessions().flatMap((session) => {
      var _a;
      return (((_a = session.model_names) == null ? void 0 : _a.length) ? session.model_names : [session.model]).filter(Boolean);
    }))].sort();
    const pages = pagedSessions();
    const sessionsHtml = pages.slice.map((session) => renderSession(session)).join("");
    const hiddenCount = HIDDEN_SESSION_IDS.size;
    return `
        <section class="panel">
          <div class="filter-bar">
            <input type="text" id="chatSearchInput" placeholder="Search by chat title, model, session ID, or IP\u2026" value="${escapeHtml(STATE.search)}" oninput="setSearch(this.value)">
            <select onchange="setModelFilter(this.value)">
              <option value="">All models</option>
              ${models.map((model) => `<option value="${escapeHtml(model)}" ${STATE.model === model ? "selected" : ""}>${escapeHtml(model)}</option>`).join("")}
            </select>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-left:auto">
              <button type="button" class="action-chip action-chip--red" onclick="openChatDeleteModal()">\u{1F5D1} Delete chats</button>
              ${hiddenCount ? `<button type="button" class="action-chip action-chip--blue" onclick="restoreHiddenChats()">\u21A9 Restore hidden (${formatInteger(hiddenCount)})</button>` : ""}
            </div>
          </div>
          ${renderPagination(pages.all.length, pages.pageCount)}
          <!-- Methodology behind a disclosure: it is a paragraph you read
               once, and inline it pushed the first session card a full screen
               down every visit. Collapsed keeps it one click away. -->
          <details class="method-note">
            <summary class="note small">How these totals are computed</summary>
            <div class="legend" style="margin-top:8px">${isBilledMode() ? "Each session total uses <strong>billed per-call totals</strong> directly from API usage fields." : "Each session total uses <strong>prompt-growth attribution</strong>: the first call in each segment is counted at full billed cost (fresh context); subsequent calls within a segment contribute only the net-new prompt delta + output. This avoids double-counting the growing conversation history across turns."} Model switches and context resets start new segments. <code>input</code> includes cached-read tokens; uncached input is shown separately.</div>
            <div class="note small" style="margin-top:8px">Delete actions hide chats in this browser view (persisted locally) and can be reverted with <em>Restore hidden</em>. They do not erase raw debug logs.</div>
          </details>
        </section>
        <section class="session-list">${sessionsHtml || '<div class="panel"><div class="note">No sessions match the current filter.</div></div>'}</section>`;
  }

  // web/js/modals.js
  function renderPart(part) {
    if (part.type === "tool_call") {
      return `<div class="part-card"><div class="part-label">${escapeHtml(part.label)}</div><pre>${escapeHtml(part.arguments_pretty || "")}</pre></div>`;
    }
    return `<div class="part-card"><div class="part-label">${escapeHtml(part.label || part.type || "Part")}</div><pre>${escapeHtml(part.text || "")}</pre></div>`;
  }
  function renderMessage(message) {
    var _a;
    return `<div class="message-card"><div class="message-header"><span class="badge ${message.role === "user" ? "user" : message.role === "assistant" ? "chat" : "tool"}">${escapeHtml(message.role)}</span><span class="note small">${formatInteger(((_a = message.parts) == null ? void 0 : _a.length) || 0)} parts</span></div><div class="message-parts">${(message.parts || []).map(renderPart).join("")}</div></div>`;
  }
  var FULL_SESSIONS = {};
  function findSessionAndEvent(sessionId, eventId) {
    var _a;
    const full = FULL_SESSIONS[sessionId];
    const session = full == null ? void 0 : full.session;
    const event = (_a = session == null ? void 0 : session.events) == null ? void 0 : _a.find((item) => item.id === eventId);
    return { session, event, assets: (full == null ? void 0 : full.assets) || { systemPrompts: {}, toolSets: {} } };
  }
  function renderGenAiModal(sessionId, eventId) {
    var _a, _b;
    const { session, event, assets } = findSessionAndEvent(sessionId, eventId);
    if (!session || !event) return;
    const selectedTokens = eventDisplayChatTokens(event);
    const systemPrompt = event.system_prompt_id ? (assets.systemPrompts || {})[event.system_prompt_id] : null;
    const toolSet = event.tools_id ? (assets.toolSets || {})[event.tools_id] : null;
    const details = {
      source: event.source,
      debugName: event.debug_name,
      responseId: event.response_id,
      durationMs: event.duration_ms,
      ttftMs: event.ttft_ms,
      segmentIndex: event.segment_index,
      boundaryReasons: event.boundary_reasons,
      maxTokens: event.max_tokens,
      diffMode: event.diff_mode,
      attributionTokens: event.attribution_tokens,
      requestOptions: event.request_options,
      requestShape: event.request_shape
    };
    document.getElementById("genaiModalTitle").textContent = event.title;
    document.getElementById("genaiModalSubtitle").textContent = `${session.title} \xB7 ${event.model} \xB7 ${formatTimestamp(event.ts)}`;
    document.getElementById("genaiModalStats").innerHTML = `
        <div class="meta-card"><div class="label">Prompt now</div><div class="value input">${formatInteger(event.prompt_tokens)}</div></div>
        <div class="meta-card"><div class="label">Segment</div><div class="value">${formatInteger(event.segment_index || 1)}</div></div>
        <div class="meta-card"><div class="label">Total input</div><div class="value input">${formatInteger(selectedTokens.input)}</div></div>
        <div class="meta-card"><div class="label">Uncached input</div><div class="value uncached">${formatInteger(selectedTokens.uncached)}</div></div>
        <div class="meta-card"><div class="label">Cached-read</div><div class="value cached">${formatInteger(selectedTokens.cached)}</div></div>
        <div class="meta-card"><div class="label">Output</div><div class="value output">${formatInteger(selectedTokens.output)}</div></div>
        <div class="meta-card"><div class="label">TTFT</div><div class="value">${formatDuration(event.ttft_ms)}</div></div>
        <div class="meta-card"><div class="label">${isBilledMode() ? "Billed cost" : "Attributed est. cost"}</div><div class="value cost">${formatCost(selectedTokens.cost)}</div></div>`;
    const tabs = [
      ["io", "Input & output"],
      ["tools", `Tools${((_a = toolSet == null ? void 0 : toolSet.tool_names) == null ? void 0 : _a.length) ? " " + toolSet.tool_names.length : ""}`],
      ["context", "Context window"],
      ["details", "Details"]
    ];
    document.getElementById("genaiModalTabs").innerHTML = tabs.map(([id, title], index) => `<button type="button" data-tab="${id}" class="modal-tab ${index === 0 ? "active" : ""}" onclick="switchGenAiTab('${id}')">${escapeHtml(title)}</button>`).join("");
    document.getElementById("genaiModalContent").innerHTML = `
        <div id="genai-panel-io" class="modal-panel active">
          <div class="split-grid">
            <div class="event-section"><h4>System prompt</h4><pre>${escapeHtml((systemPrompt == null ? void 0 : systemPrompt.plain_text) || "[not available]")}</pre></div>
            <div class="event-section"><h4>Assistant output</h4><div class="message-list">${(event.response_messages || []).map(renderMessage).join("") || '<div class="note">No structured output was stored.</div>'}</div></div>
          </div>
          <div class="event-section"><h4>Input messages Copilot sent into this call</h4><div class="message-list">${(event.input_messages || []).map(renderMessage).join("") || '<div class="note">No input messages were recorded.</div>'}</div></div>
          <div class="event-section"><h4>New context added since previous call</h4><div class="message-list">${(event.new_messages || []).map(renderMessage).join("") || '<div class="note">No new messages detected or the prompt was rebuilt.</div>'}</div></div>
        </div>
        <div id="genai-panel-tools" class="modal-panel">
          <div class="event-section"><h4>Tool definitions available to the model</h4>${((_b = toolSet == null ? void 0 : toolSet.tool_names) == null ? void 0 : _b.length) ? `<div class="pill-list">${toolSet.tool_names.map((name) => `<span class="pill">${escapeHtml(name)}</span>`).join("")}</div>` : '<div class="note">No tool definitions were captured for this call.</div>'}</div>
          <div class="split-grid">
            <div class="event-section"><h4>Emitted tool calls</h4><div class="message-list">${(event.tool_calls_emitted || []).map((tool) => `<div class="message-card"><div class="message-header"><span class="badge tool">Tool call</span><strong>${escapeHtml(tool.name)}</strong></div><pre>${escapeHtml(tool.arguments || "")}</pre></div>`).join("") || '<div class="note">This chat call did not emit a tool call.</div>'}</div></div>
            <div class="event-section"><h4>Tool definition payload</h4><pre>${escapeHtml((toolSet == null ? void 0 : toolSet.plain_text) || "[not available]")}</pre></div>
          </div>
        </div>
        <div id="genai-panel-context" class="modal-panel">
          ${renderContextBreakdown(event.context_breakdown)}
        </div>
        <div id="genai-panel-details" class="modal-panel">
          <div class="split-grid">
            <div class="event-section"><h4>Observed request metrics</h4><pre>${escapeHtml(JSON.stringify({ promptTokens: event.prompt_tokens, promptDiff: event.prompt_diff, cachedTokens: event.cached_tokens, uncachedPromptTokens: event.uncached_prompt_tokens, selectedMode: tokenModeLabel(), selectedTokens, billed: event.billed_tokens, attributionTokens: event.attribution_tokens, boundaryReasons: event.boundary_reasons }, null, 2))}</pre></div>
            <div class="event-section"><h4>Request metadata</h4><pre>${escapeHtml(JSON.stringify(details, null, 2))}</pre></div>
          </div>
          <div class="split-grid">
            <div class="event-section"><h4>Reasoning</h4><pre>${escapeHtml(event.reasoning || "[not recorded]")}</pre></div>
            <div class="event-section"><h4>Raw response text</h4><pre>${escapeHtml(event.response_text || "[empty]")}</pre></div>
          </div>
        </div>`;
    document.getElementById("genaiModalBackdrop").classList.add("open");
  }
  function switchGenAiTab(tabId) {
    document.querySelectorAll("#genaiModalTabs .modal-tab").forEach((button) => button.classList.toggle("active", button.dataset.tab === tabId));
    document.querySelectorAll("#genaiModalContent .modal-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `genai-panel-${tabId}`));
  }
  async function openGenAiModal(sessionId, eventId) {
    if (!FULL_SESSIONS[sessionId]) {
      try {
        await fetchFullSession(sessionId);
      } catch (err) {
        document.getElementById("genaiModalTitle").textContent = "GenAI details unavailable";
        document.getElementById("genaiModalSubtitle").textContent = "";
        document.getElementById("genaiModalStats").innerHTML = "";
        document.getElementById("genaiModalTabs").innerHTML = "";
        document.getElementById("genaiModalContent").innerHTML = `<div class="is-empty">${describeFullSessionError(err)}</div>`;
        document.getElementById("genaiModalBackdrop").classList.add("open");
        return;
      }
    }
    renderGenAiModal(sessionId, eventId);
  }
  function closeGenAiModal(event) {
    if (event && event.target && event.target !== document.getElementById("genaiModalBackdrop")) return;
    document.getElementById("genaiModalBackdrop").classList.remove("open");
  }
  function describeFullSessionError(err) {
    if (err && err.code === "network") {
      return "Full per-call chat detail (timeline, GenAI details, raw chat JSON export) needs the live dashboard server -- this static export only embeds per-session summaries, not full chat bodies, to keep the file a reasonable size. Run <code>python serve_dashboard.py</code> in this project folder and open the printed http://localhost:8765 URL instead to see it.";
    }
    return escapeHtml(String(err && err.message || err || "Full chat detail is not available for this session."));
  }
  async function fetchFullSession(sessionId) {
    if (FULL_SESSIONS[sessionId]) return FULL_SESSIONS[sessionId];
    let response;
    try {
      response = await fetch(`/api/session?id=${encodeURIComponent(sessionId)}`);
    } catch (_networkErr) {
      const err = new Error("Failed to reach the dashboard server.");
      err.code = "network";
      throw err;
    }
    if (!response.ok) {
      const err = new Error(`Failed to load chat (${response.status})`);
      err.code = "network";
      throw err;
    }
    const payload = await response.json();
    if (!payload || !payload.session) {
      throw new Error("Full chat detail is not available for this session.");
    }
    FULL_SESSIONS[sessionId] = payload;
    return payload;
  }
  function renderFullChatBody(session) {
    const events = Array.isArray(session == null ? void 0 : session.events) ? session.events : [];
    const timeline = events.length ? events.map((event) => renderEvent(event, session)).join("") : '<div class="note">No per-call events were recorded for this chat.</div>';
    return `
        ${renderSessionMeta(session)}
        ${renderSessionTokenBreakdown(session)}
        <div class="timeline">${timeline}</div>`;
  }
  async function openFullChatModal(sessionId) {
    const meta = (APP_DATA.sessions || []).find((item) => item.id === sessionId);
    const backdrop = document.getElementById("fullChatModalBackdrop");
    document.getElementById("fullChatModalTitle").textContent = (meta == null ? void 0 : meta.title) || "Full chat";
    document.getElementById("fullChatModalSubtitle").textContent = meta ? `${meta.model || "unknown"} \xB7 ${formatTimestamp(meta.timestamp)} \xB7 ${formatInteger(meta.chat_count)} calls \xB7 ${formatInteger(meta.tool_count)} tools` : "";
    const exportBtn = document.getElementById("fullChatExportBtn");
    if (exportBtn) exportBtn.onclick = () => exportSessionToJson(sessionId);
    const body = document.getElementById("fullChatModalContent");
    body.innerHTML = '<div class="note" style="padding:24px;text-align:center">Loading full chat detail\u2026</div>';
    backdrop.classList.add("open");
    try {
      const payload = await fetchFullSession(sessionId);
      body.innerHTML = renderFullChatBody(payload.session);
    } catch (err) {
      body.innerHTML = `<div class="is-empty" style="padding:24px">${describeFullSessionError(err)}</div>`;
    }
  }
  function closeFullChatModal(event) {
    if (event && event.target && event.target !== document.getElementById("fullChatModalBackdrop")) return;
    document.getElementById("fullChatModalBackdrop").classList.remove("open");
  }
  function renderFileUsageSummary(file) {
    const rows = [...(file == null ? void 0 : file.toolUsage) || []].sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0) || Number(b.count || 0) - Number(a.count || 0));
    if (!rows.length) {
      return '<div class="note">No aggregated tool usage captured for this file.</div>';
    }
    const totals = rows.reduce((acc, row) => {
      acc.count += Number(row.count || 0);
      acc.durationMs += Number(row.durationMs || 0);
      acc.input += Number(row.input || 0);
      acc.output += Number(row.output || 0);
      acc.cached += Number(row.cached || 0);
      acc.cost += Number(row.cost || 0);
      acc.payloadTokens += Number(row.payloadTokens || 0);
      return acc;
    }, { count: 0, durationMs: 0, input: 0, output: 0, cached: 0, cost: 0, payloadTokens: 0 });
    return `
        <div class="panel">
          <div class="note">Aggregated per tool and mode for this file \u2014 no per-call timeline is stored here.</div>
          <div style="overflow-x:auto;margin-top:10px">
            <table>
              <thead><tr>
                <th>Tool</th>
                <th>Mode</th>
                <th class="num">Calls</th>
                <th class="num">Sessions</th>
                <th class="num">Avg Duration</th>
                <th class="num">Total Input</th>
                <th class="num">Total Output</th>
                <th class="num">Total Cached</th>
                <th class="num">Payload</th>
                <th class="num">Cost</th>
              </tr></thead>
              <tbody>
                ${rows.map((row) => `<tr>
                  <td><strong>${escapeHtml(row.name || "unknown")}</strong></td>
                  <td>${escapeHtml(row.mode || "other")}</td>
                  <td class="num">${formatInteger(row.count || 0)}</td>
                  <td class="num">${formatInteger(row.sessionCount || 0)}</td>
                  <td class="num">${formatDuration(row.avgDurationMs || 0)}</td>
                  <td class="num"><span class="value input">${formatCompact(row.input || 0)}</span></td>
                  <td class="num"><span class="value output">${formatCompact(row.output || 0)}</span></td>
                  <td class="num"><span class="value cached">${formatCompact(row.cached || 0)}</span></td>
                  <td class="num">${formatInteger(row.payloadTokens || 0)}</td>
                  <td class="num"><span class="value cost">${formatCost(row.cost || 0)}</span></td>
                </tr>`).join("")}
                <tr style="border-top:2px solid var(--border);font-weight:700">
                  <td>TOTAL</td>
                  <td></td>
                  <td class="num">${formatInteger(totals.count)}</td>
                  <td class="num">${formatInteger(file.sessionCount || 0)}</td>
                  <td class="num">${formatDuration(totals.count ? totals.durationMs / totals.count : 0)}</td>
                  <td class="num"><span class="value input">${formatCompact(totals.input)}</span></td>
                  <td class="num"><span class="value output">${formatCompact(totals.output)}</span></td>
                  <td class="num"><span class="value cached">${formatCompact(totals.cached)}</span></td>
                  <td class="num">${formatInteger(totals.payloadTokens)}</td>
                  <td class="num"><span class="value cost">${formatCost(totals.cost)}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>`;
  }
  function openFileModal(pathEncoded) {
    const path = decodeURIComponent(pathEncoded);
    const file = (analysisForMode().files || []).find((item) => item.path === path);
    if (!file) return;
    document.getElementById("fileExportBtn").onclick = () => exportFileToJson(pathEncoded);
    document.getElementById("fileModalTitle").textContent = file.name;
    document.getElementById("fileModalSubtitle").textContent = file.shortPath + " \xB7 " + tokenModeLabel() + " mode \xB7 " + formatInteger(file.toolReferenceCount || 0) + " tool refs";
    const totalFileOps = file.readCount + file.editCount;
    document.getElementById("fileModalStats").innerHTML = `
        <div class="meta-card"><div class="label">Reads</div><div class="value">${formatInteger(file.readCount)}</div></div>
        <div class="meta-card"><div class="label">Edits</div><div class="value">${formatInteger(file.editCount)}</div></div>
        <div class="meta-card"><div class="label">Tool refs</div><div class="value">${formatInteger(file.toolReferenceCount || 0)}</div></div>
        <div class="meta-card"><div class="label">Unique tools</div><div class="value">${formatInteger((file.toolUsage || []).length)}</div></div>
        <div class="meta-card"><div class="label">Total Input</div><div class="value input">${formatInteger(file.input)}</div></div>
        <div class="meta-card"><div class="label">Total Output</div><div class="value output">${formatInteger(file.output)}</div></div>
        <div class="meta-card"><div class="label">Total Cached</div><div class="value cached">${formatInteger(file.cached)}</div></div>
        <div class="meta-card"><div class="label">Avg Input</div><div class="value input">${formatInteger(totalFileOps ? file.input / totalFileOps : 0)}</div></div>
        <div class="meta-card"><div class="label">Avg Cost</div><div class="value cost">${formatCost(totalFileOps ? file.cost / totalFileOps : 0)}</div></div>
        <div class="meta-card"><div class="label">Total Cost</div><div class="value cost">${formatCost(file.cost)}</div></div>`;
    document.getElementById("fileModalContent").innerHTML = `
        ${renderFileUsageSummary(file)}`;
    document.getElementById("fileModalBackdrop").classList.add("open");
  }
  function closeFileModal(event) {
    if (event && event.target && event.target !== document.getElementById("fileModalBackdrop")) return;
    document.getElementById("fileModalBackdrop").classList.remove("open");
  }
  function exportFileToJson(pathEncoded) {
    const path = decodeURIComponent(pathEncoded);
    const file = (analysisForMode().files || []).find((item) => item.path === path);
    if (!file) return;
    const blob = new Blob([JSON.stringify(file, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const safeName = (file.name || "file").replace(/[^a-zA-Z0-9._-]/g, "_");
    const ts = (/* @__PURE__ */ new Date()).toISOString().replace(/[:.]/g, "-").slice(0, 19);
    a.href = url;
    a.download = `file-activity-${safeName}-${ts}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  function updateChatDeletePreview() {
    const previewEl = document.getElementById("chatDeletePreview");
    const applyBtn = document.getElementById("chatDeleteApplyBtn");
    if (!previewEl || !applyBtn) return;
    const isCli = STATE.deleteTarget === "cli";
    const visibleCount = isCli ? visibleCliSessions().length : visibleSessions().length;
    const targets = computeChatDeletionTargets();
    const label = isCli ? "CLI sessions" : "chats";
    const tabLabel = isCli ? "CLI tab" : "Chats tab";
    previewEl.innerHTML = `This action will hide <strong>${formatInteger(targets.length)}</strong> of <strong>${formatInteger(visibleCount)}</strong> visible ${label} from the ${tabLabel}.`;
    applyBtn.disabled = !targets.length;
    applyBtn.style.opacity = targets.length ? "1" : "0.5";
    applyBtn.style.cursor = targets.length ? "pointer" : "default";
    const customDateInput = document.getElementById("deleteSpecificDate");
    if (customDateInput) {
      customDateInput.disabled = STATE.deleteAgePreset !== "custom";
    }
  }
  function openChatDeleteModal(target = "chats") {
    STATE.deleteTarget = target === "cli" ? "cli" : "chats";
    const isCli = STATE.deleteTarget === "cli";
    if (!STATE.deleteCustomDate) {
      STATE.deleteCustomDate = (/* @__PURE__ */ new Date()).toISOString().slice(0, 10);
    }
    const radios = document.querySelectorAll('input[name="chatDeleteMode"]');
    radios.forEach((radio) => {
      radio.checked = radio.value === STATE.deleteMode;
    });
    const agePreset = document.getElementById("deleteAgePreset");
    if (agePreset) agePreset.value = STATE.deleteAgePreset;
    const specificDate = document.getElementById("deleteSpecificDate");
    if (specificDate) specificDate.value = STATE.deleteCustomDate;
    const keepCount = document.getElementById("deleteKeepCount");
    if (keepCount) keepCount.value = STATE.deleteKeepCount;
    const titleEl = document.getElementById("chatDeleteModalTitle");
    const subtitleEl = document.getElementById("chatDeleteModalSubtitle");
    const applyBtn = document.getElementById("chatDeleteApplyBtn");
    const keepLastLabel = document.getElementById("chatDeleteKeepLastLabel");
    const allLabel = document.getElementById("chatDeleteAllLabel");
    if (titleEl) titleEl.textContent = isCli ? "Delete CLI sessions from view" : "Delete chats from view";
    if (subtitleEl) subtitleEl.textContent = isCli ? "This hides CLI sessions locally in your browser (from the CLI tab). It does not modify session-store.db." : "This hides chats locally in your browser (from the Chats tab). It does not delete raw debug logs.";
    if (applyBtn) applyBtn.textContent = isCli ? "Delete selected CLI sessions" : "Delete selected chats";
    if (allLabel) allLabel.textContent = isCli ? "Delete all visible CLI sessions" : "Delete all visible chats";
    if (keepLastLabel) keepLastLabel.textContent = isCli ? "sessions" : "chats";
    updateChatDeletePreview();
    document.getElementById("chatDeleteModalBackdrop").classList.add("open");
  }
  function closeChatDeleteModal(event) {
    if (event && event.target && event.target !== document.getElementById("chatDeleteModalBackdrop")) return;
    document.getElementById("chatDeleteModalBackdrop").classList.remove("open");
  }
  async function exportSessionToJson(sessionId) {
    const meta = (APP_DATA.sessions || []).find((s) => s.id === sessionId);
    const safeName = ((meta == null ? void 0 : meta.title) || "chat").replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 40);
    const ts = (/* @__PURE__ */ new Date()).toISOString().replace(/[:.]/g, "-").slice(0, 19);
    let exportData;
    try {
      const payload = await fetchFullSession(sessionId);
      exportData = payload.session;
    } catch (err) {
      exportData = meta ? { ...meta, _exportNote: "Full per-call chat detail was unavailable (no live dashboard server); this is the compact session summary only." } : null;
    }
    if (!exportData) return;
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chat-${safeName}-${ts}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  function openModelCompareModal(sessionId) {
    var _a;
    const session = APP_DATA.sessions.find((s) => s.id === sessionId);
    if (!session) return;
    const totals = sessionDisplayTotals(session);
    const inputTokens = totals.input || 0;
    const cachedTokens = totals.cached || 0;
    const outputTokens = totals.output || 0;
    const actualModel = session.model || "unknown";
    const actualCost = totals.cost || 0;
    document.getElementById("modelCompareModalTitle").textContent = "Model cost comparison";
    document.getElementById("modelCompareModalSubtitle").textContent = session.title + " \xB7 " + formatInteger(inputTokens) + " input \xB7 " + formatInteger(outputTokens) + " output tokens (" + tokenModeLabel() + ")";
    const rows = Object.entries(PRICING_TABLE).map(([model, pricing]) => ({
      model,
      cost: calcModelCost(inputTokens, cachedTokens, outputTokens, pricing),
      pricing
    })).sort((a, b) => a.cost - b.cost);
    const minCost = ((_a = rows[0]) == null ? void 0 : _a.cost) || 0;
    document.getElementById("modelCompareModalContent").innerHTML = `
        <div class="note small" style="margin-bottom:12px">Estimated cost if this chat's ${escapeHtml(tokenModeLabel())} token usage (<strong>${formatInteger(inputTokens)}</strong> input, <strong>${formatInteger(cachedTokens)}</strong> cached, <strong>${formatInteger(outputTokens)}</strong> output) was processed by each model. Assumes same cache hit pattern.</div>
        <div class="note small" style="margin-bottom:12px">Chat telemetry reports no cache-write counter, so cache writes are priced here at each model's input rate rather than its (usually higher) cache-write rate. For models that charge a cache-write premium \u2014 Anthropic bills 1.25\xD7 input \u2014 these figures are a lower bound. Copilot CLI sessions do report the counter, so the CLI tab's costs come straight from what GitHub charged and need no such assumption.</div>
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
      const isCheapest = Math.abs(row.cost - minCost) < 1e-6;
      return `<tr style="${isActual ? "background:rgba(88,166,255,0.08);border-left:2px solid var(--blue)" : ""}">
                <td><strong style="${isCheapest ? "color:var(--green)" : ""}">${escapeHtml(row.model)}</strong>${isActual ? ' <span class="badge chat" style="font-size:0.65rem;padding:2px 6px">current</span>' : ""}${isCheapest ? ' <span class="badge mode-read" style="font-size:0.65rem;padding:2px 6px">cheapest</span>' : ""}</td>
                <td class="num">${formatCost(row.pricing.input)}</td>
                <td class="num">${formatCost(row.pricing.cached)}</td>
                <td class="num">${formatCost(row.pricing.output)}</td>
                <td class="num"><strong style="color:var(--teal)">${formatCost(row.cost)}</strong></td>
                <td class="num" style="color:${delta < -1e-4 ? "var(--green)" : delta > 1e-4 ? "var(--red)" : "var(--muted)"}">${isActual ? "\u2014" : (delta >= 0 ? "+" : "") + formatCost(Math.abs(delta))}</td>
              </tr>`;
    }).join("")}
          </tbody>
        </table>
        </div>`;
    document.getElementById("modelCompareModalBackdrop").classList.add("open");
  }
  function closeModelCompareModal(event) {
    if (event && event.target && event.target !== document.getElementById("modelCompareModalBackdrop")) return;
    document.getElementById("modelCompareModalBackdrop").classList.remove("open");
  }
  var MODAL_BACKDROP_IDS = [
    "genaiModalBackdrop",
    "fullChatModalBackdrop",
    "fileModalBackdrop",
    "chatDeleteModalBackdrop",
    "modelCompareModalBackdrop"
  ];
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" && event.key !== "Esc") return;
    MODAL_BACKDROP_IDS.forEach((id) => {
      const el = document.getElementById(id);
      if (el && el.classList.contains("open")) el.classList.remove("open");
    });
  });

  // web/js/actions.js
  var _searchTimer = null;
  function setSearch(value) {
    STATE.search = value;
    STATE.page = 1;
    if (_searchTimer) clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => renderApp(), 300);
  }
  var _toolCatalogSearchTimer = null;
  function setToolCatalogSearch(value) {
    STATE.toolCatalogSearch = value;
    if (_toolCatalogSearchTimer) clearTimeout(_toolCatalogSearchTimer);
    _toolCatalogSearchTimer = setTimeout(() => renderApp(), 120);
  }
  var _toolImpactSearchTimer = null;
  function setToolImpactSearch(value) {
    STATE.toolImpactSearch = value;
    if (_toolImpactSearchTimer) clearTimeout(_toolImpactSearchTimer);
    _toolImpactSearchTimer = setTimeout(() => renderApp(), 120);
  }
  var _fileSearchTimer = null;
  function setFileSearch(value) {
    STATE.fileSearch = value;
    if (_fileSearchTimer) clearTimeout(_fileSearchTimer);
    _fileSearchTimer = setTimeout(() => renderApp(), 120);
  }
  function setToolCatalogSort(key) {
    if (STATE.toolCatalogSortKey === key) {
      STATE.toolCatalogSortDir = (STATE.toolCatalogSortDir || "desc") === "desc" ? "asc" : "desc";
    } else {
      STATE.toolCatalogSortKey = key;
      STATE.toolCatalogSortDir = key === "name" ? "asc" : "desc";
    }
    renderApp();
  }
  function switchToolImpactTab(tab) {
    STATE.toolImpactTab = tab;
    renderApp();
  }
  function switchMonthlyTrendMetric(metricKey) {
    STATE.monthlyTrendMetric = metricKey;
    renderApp();
  }
  function setToolWasteSort(key) {
    if (STATE.toolWasteSortKey === key) {
      STATE.toolWasteSortDir = (STATE.toolWasteSortDir || "desc") === "desc" ? "asc" : "desc";
    } else {
      STATE.toolWasteSortKey = key;
      STATE.toolWasteSortDir = key === "name" ? "asc" : "desc";
    }
    renderApp();
  }
  function setModelFilter(value) {
    STATE.model = value;
    STATE.page = 1;
    renderApp();
  }
  function setPageSize(value) {
    STATE.pageSize = Number(value || 10);
    STATE.page = 1;
    renderApp();
  }
  function changePage(delta) {
    const pages = pagedSessions();
    STATE.page = Math.max(1, Math.min(pages.pageCount, STATE.page + delta));
    renderApp();
  }
  function switchTab(tabName) {
    STATE.activeTab = tabName;
    persistLastTab(tabName);
    renderApp();
  }
  function switchUsagePeriod(periodName) {
    if (periodName !== "monthly" && periodName !== "allTime") return;
    STATE.usagePeriod = periodName;
    STATE.page = 1;
    renderApp();
  }
  function switchTokenMode(modeName) {
    const normalized = normalizeTokenMode(modeName);
    if (STATE.tokenMode === normalized) return;
    STATE.tokenMode = normalized;
    STATE.filters.tokenMode = normalized;
    persistTokenMode();
    renderApp();
  }
  function switchAnalysisTab(tabName) {
    STATE.analysisTab = tabName;
    renderApp();
  }
  function switchDataTab(tabName) {
    STATE.dataTab = tabName;
    renderApp();
  }
  function deleteSessionPrompt(sessionId) {
    const session = APP_DATA.sessions.find((item) => item.id === sessionId);
    if (!session) return;
    const title = (session.title || "this chat").slice(0, 90);
    if (!confirm(`Delete "${title}" from the Chats tab?`)) return;
    const changed = markSessionsHidden([sessionId]);
    if (changed) renderApp();
  }
  function setDeleteMode(mode) {
    STATE.deleteMode = mode;
    updateChatDeletePreview();
  }
  function setDeleteAgePreset(value) {
    STATE.deleteAgePreset = value;
    updateChatDeletePreview();
  }
  function setDeleteSpecificDate(value) {
    STATE.deleteCustomDate = value;
    updateChatDeletePreview();
  }
  function setDeleteKeepCount(value) {
    const parsed = Number(value || 10);
    STATE.deleteKeepCount = Number.isFinite(parsed) ? Math.max(1, Math.floor(parsed)) : 10;
    const input = document.getElementById("deleteKeepCount");
    if (input && Number(input.value) !== STATE.deleteKeepCount) {
      input.value = STATE.deleteKeepCount;
    }
    updateChatDeletePreview();
  }
  function applyChatDeletion() {
    const isCli = STATE.deleteTarget === "cli";
    const targets = computeChatDeletionTargets();
    if (!targets.length) {
      alert(isCli ? "No CLI sessions matched this delete rule." : "No chats matched this delete rule.");
      return;
    }
    if (!confirm(`Delete ${targets.length} ${isCli ? "CLI session(s)" : "chat(s)"} from the ${isCli ? "CLI" : "Chats"} tab view?`)) return;
    const changed = isCli ? markCliSessionsHidden(targets) : markSessionsHidden(targets);
    closeChatDeleteModal();
    if (changed) {
      renderApp();
    }
  }
  function setFileSort(key) {
    if (STATE.fileSortKey === key) {
      STATE.fileSortDir = STATE.fileSortDir === "desc" ? "asc" : "desc";
    } else {
      STATE.fileSortKey = key;
      STATE.fileSortDir = key === "name" ? "asc" : "desc";
    }
    renderApp();
  }
  function setToolSort(key) {
    if (STATE.toolSortKey === key) {
      STATE.toolSortDir = (STATE.toolSortDir || "desc") === "desc" ? "asc" : "desc";
    } else {
      STATE.toolSortKey = key;
      STATE.toolSortDir = key === "name" ? "asc" : "desc";
    }
    renderApp();
  }
  function exportToJson() {
    const blob = new Blob([JSON.stringify(APP_DATA, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const ts = (/* @__PURE__ */ new Date()).toISOString().replace(/[:.]/g, "-").slice(0, 19);
    a.href = url;
    a.download = `copilot-dashboard-${ts}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // web/js/diagnostics.js
  var DISMISS_KEY = "copilot-dashboard-dismissed-diagnostics-v1";
  var EMPTY_SUMMARY = { total: 0, errors: 0, warnings: 0, costImpacting: 0 };
  function diagnosticsPayload() {
    const payload = APP_DATA.diagnostics;
    if (!payload || typeof payload !== "object") return { entries: [], summary: EMPTY_SUMMARY };
    return {
      entries: Array.isArray(payload.entries) ? payload.entries : [],
      summary: payload.summary && typeof payload.summary === "object" ? payload.summary : EMPTY_SUMMARY
    };
  }
  function costImpactingDiagnostics() {
    return diagnosticsPayload().entries.filter((entry) => entry && entry.impact === "cost");
  }
  function diagnosticsSignature(entries) {
    return entries.map((entry) => `${entry.code}@${entry.source || ""}#${entry.count || 1}`).sort().join("|");
  }
  function readDismissedSignature() {
    try {
      return localStorage.getItem(DISMISS_KEY) || "";
    } catch (_err) {
      return "";
    }
  }
  function dismissDiagnosticsBanner() {
    const entries = costImpactingDiagnostics();
    try {
      localStorage.setItem(DISMISS_KEY, diagnosticsSignature(entries));
    } catch (_err) {
    }
    renderApp();
  }
  function severityColor(severity) {
    if (severity === "error") return "var(--red)";
    if (severity === "warning") return "var(--yellow)";
    return "var(--muted)";
  }
  function occurrenceSuffix(count) {
    const total = Number(count || 1);
    return total > 1 ? ` <span class="note small">(${formatInteger(total)}x)</span>` : "";
  }
  function renderDiagnosticsBanner() {
    const entries = costImpactingDiagnostics();
    if (!entries.length) return "";
    if (readDismissedSignature() === diagnosticsSignature(entries)) return "";
    const affected = entries.reduce((total, entry) => total + Number(entry.count || 1), 0);
    const headline = entries.length === 1 ? "1 data source failed to load" : `${formatInteger(entries.length)} data sources failed to load`;
    return `
        <div class="diagnostics-banner" role="alert">
          <span class="diagnostics-banner__icon" aria-hidden="true">\u26A0\uFE0F</span>
          <div class="diagnostics-banner__body">
            <strong>Totals on this page may be understated.</strong>
            ${escapeHtml(headline)} while building this dashboard${affected > entries.length ? ` (${formatInteger(affected)} occurrences)` : ""}, so
            whatever they contained is missing from every figure shown.
            <div class="note small" style="margin-top:4px">
              Full details in <strong>Info \u2192 Telemetry</strong>. Re-running with
              <code>--force-recalculate</code> rebuilds the cache from the raw logs.
            </div>
          </div>
          <button type="button" class="action-chip" onclick="dismissDiagnosticsBanner()" title="Hide until something different fails">Dismiss</button>
        </div>`;
  }
  function renderDiagnosticsPanel() {
    const { entries, summary } = diagnosticsPayload();
    if (!entries.length) {
      return `
          <section class="panel">
            <h2 class="section-title">Data collection problems</h2>
            <div class="section-subtitle">None. Every cache entry and log file read cleanly for this build, so no session is missing from the totals below.</div>
          </section>`;
    }
    const costCount = Number(summary.costImpacting || 0);
    const lead = costCount ? `<strong style="color:var(--red)">${formatInteger(costCount)} of these affect cost figures</strong> - the sessions behind them are missing from every total on this dashboard.` : "None of these affect cost figures; the totals on this dashboard are complete.";
    return `
        <section class="panel">
          <h2 class="section-title">Data collection problems</h2>
          <div class="section-subtitle">Failures recorded while building this dashboard. ${lead}</div>
          <table class="compact-prices-table">
            <thead>
              <tr>
                <th>Impact</th>
                <th>Code</th>
                <th>What happened</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              ${entries.map((entry) => `
                <tr>
                  <td><span class="badge ${entry.impact === "cost" ? "boundary" : "source"}">${escapeHtml(entry.impact === "cost" ? "cost" : entry.impact || "none")}</span></td>
                  <td><code style="color:${severityColor(entry.severity)}">${escapeHtml(entry.code || "")}</code>${occurrenceSuffix(entry.count)}</td>
                  <td>${escapeHtml(entry.message || "")}</td>
                  <td class="note small" style="word-break:break-all">${escapeHtml(entry.source || "-")}</td>
                </tr>`).join("")}
            </tbody>
          </table>
        </section>`;
  }

  // web/js/charts.js
  function renderMonthlyTrendChart(rows, metricKey) {
    const metrics = monthlyTrendMetricConfig();
    const metric = metrics[metricKey] || metrics.cost;
    const values = rows.map((row) => Number(metric.value(row) || 0));
    const maxValue = Math.max(...values, 1);
    const width = Math.max(720, rows.length * 104);
    const height = 320;
    const padLeft = 72;
    const padRight = 20;
    const padTop = 16;
    const padBottom = 54;
    const innerWidth = width - padLeft - padRight;
    const innerHeight = height - padTop - padBottom;
    const step = Math.max(1, innerWidth / Math.max(rows.length, 1));
    const barWidth = Math.max(10, Math.min(48, step * 0.5));
    const gridLines = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
      const y = padTop + innerHeight - innerHeight * ratio;
      const label = metric.format(maxValue * ratio);
      return `
          <line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}"  stroke="var(--overlay-08)" />
          <text x="${padLeft - 8}" y="${y + 4}" fill="var(--muted)" font-size="12" text-anchor="end">${escapeHtml(label)}</text>`;
    }).join("");
    const bars = rows.map((row, index) => {
      const value = Number(metric.value(row) || 0);
      const x = padLeft + step * index + step / 2;
      const barHeight = value / maxValue * innerHeight;
      const y = padTop + innerHeight - barHeight;
      const month = row.monthKey || row.label || `M${index + 1}`;
      const tooltip = `${row.label || month}
${metric.label}: ${metric.format(value)}
Sessions: ${formatInteger(row.sessionCount || 0)} \xB7 Chats: ${formatInteger(row.chatCallCount || 0)} \xB7 Tools: ${formatInteger(row.toolCallCount || 0)}`;
      return `
          <rect x="${x - barWidth / 2}" y="${y}" width="${barWidth}" height="${Math.max(1, barHeight)}" rx="6" fill="${metric.color}" opacity="0.82"><title>${escapeHtml(tooltip)}</title></rect>
          <text x="${x}" y="${height - 16}" fill="var(--muted)" font-size="12" text-anchor="middle">${escapeHtml(month)}</text>`;
    }).join("");
    return `
        <div class="chart-card">
          <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
            ${gridLines}
            <line x1="${padLeft}" y1="${padTop + innerHeight}" x2="${width - padRight}" y2="${padTop + innerHeight}" stroke="var(--border)" />
            ${bars}
          </svg>
          <div class="chart-legend">
            <span class="legend-item"><span class="legend-swatch" style="background:${metric.color}"></span>${escapeHtml(metric.label)}</span>
            <span class="legend-item">Bars are month totals (hover bars for details).</span>
          </div>
        </div>`;
  }
  function renderGlobalTokenPieChart(summary, analysis) {
    const totals = summaryDisplayTotals(summary);
    const totalInput = Number(totals.input || 0);
    if (!totalInput) return '<div class="note">No token data available.</div>';
    const overhead = analysis.overhead || {};
    const categories = buildOverheadBreakdown(overhead, totalInput);
    const cats = categories.filter((c) => c.input > 0);
    const cx = 110, cy = 110, r = 90;
    let startAngle = -Math.PI / 2;
    const slices = cats.map((cat) => {
      const pct = cat.input / totalInput;
      const angle = pct * 2 * Math.PI;
      const x1 = cx + r * Math.cos(startAngle);
      const y1 = cy + r * Math.sin(startAngle);
      const endAngle = startAngle + angle;
      const x2 = cx + r * Math.cos(endAngle);
      const y2 = cy + r * Math.sin(endAngle);
      const largeArc = angle > Math.PI ? 1 : 0;
      const d = `M ${cx} ${cy} L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`;
      const label = `${cat.label}: ${formatInteger(cat.input)} tokens (${(pct * 100).toFixed(1)}%)`;
      startAngle = endAngle;
      return `<path d="${d}" fill="${cat.color}" opacity="0.85"><title>${label}</title></path>`;
    }).join("");
    const legend = categories.map((cat) => {
      return `
          <tr>
            <td><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:${cat.color};margin-right:8px;vertical-align:middle"></span>${escapeHtml(cat.label)}</td>
            <td class="num">${formatInteger(cat.input)}</td>
            <td class="num">${cat.pct.toFixed(1)}%</td>
            <td class="num">${cat.cost > 0 ? formatCost(cat.cost) : "\u2014"}</td>
          </tr>`;
    }).join("");
    return `
        <div style="display:grid;grid-template-columns:220px 1fr;gap:24px;align-items:start">
          <div>
            <svg viewBox="0 0 220 220" width="220" height="220" style="display:block">
              ${slices}
              <circle cx="${cx}" cy="${cy}" r="38" fill="var(--panel-2)"/>
              <text x="${cx}" y="${cy - 6}" text-anchor="middle" fill="var(--muted)" font-size="11" font-family="inherit">Total input</text>
              <text x="${cx}" y="${cy + 10}" text-anchor="middle" fill="var(--text)" font-size="12" font-weight="700" font-family="inherit">${formatCompact(totalInput)}</text>
            </svg>
          </div>
          <div>
            <div class="note small" style="margin-bottom:10px">Cross-chat global breakdown of all <strong>${formatInteger(totalInput)}</strong> ${escapeHtml(tokenModeLabel())} input tokens. Shows what your prompts are actually made of across all sessions. This will not exactly match a single in-chat screenshot, which represents one request's prompt snapshot (window usage), not multi-call aggregated totals.</div>
            <table>
              <thead><tr><th>Category</th><th class="num">Input tokens</th><th class="num">% of total</th><th class="num">Est. cost</th></tr></thead>
              <tbody>${legend}</tbody>
            </table>
            <div class="note small" style="margin-top:10px">
              <strong>Chat History</strong> = earlier assistant replies carried into later turns.<br>
              <strong>Tools</strong> = tool-call payload in context (arguments/results + non-file tool metadata).<br>
              <strong>Files</strong> = file-related context from read/edit tool turns (mode-aware split estimate).
            </div>
          </div>
        </div>`;
  }
  function renderUnifiedTrendChart(rows, metricKey) {
    if (!rows || !rows.length) {
      return '<div class="note">No usage data available for the selected filters.</div>';
    }
    const metric = metricKey === "tokens" ? { label: "Total tokens", color: "var(--blue)", value: (block) => Number(block.input || 0) + Number(block.output || 0), format: formatInteger } : { label: "Cost", color: "var(--teal)", value: (block) => Number(block.cost || 0), format: formatCost };
    const blockKey = isBilledMode() ? "billed" : "attributed";
    const points = rows.map((row) => {
      const key = row.dayKey || row.monthKey || "";
      const chat = row.bySource && row.bySource.chat && row.bySource.chat[blockKey] || null;
      const cli = row.bySource && row.bySource.cli && row.bySource.cli[blockKey] || null;
      return {
        key,
        chat: chat ? metric.value(chat) : 0,
        cli: cli ? metric.value(cli) : 0
      };
    });
    const maxValue = Math.max(...points.map((p) => p.chat + p.cli), 1);
    const width = Math.max(720, points.length * 64);
    const height = 280;
    const padLeft = 72, padRight = 20, padTop = 16, padBottom = 54;
    const innerWidth = width - padLeft - padRight;
    const innerHeight = height - padTop - padBottom;
    const step = Math.max(1, innerWidth / Math.max(points.length, 1));
    const barWidth = Math.max(8, Math.min(36, step * 0.6));
    const gridLines = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
      const y = padTop + innerHeight - innerHeight * ratio;
      const label = metric.format(maxValue * ratio);
      return `
          <line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}" stroke="var(--overlay-08)" />
          <text x="${padLeft - 8}" y="${y + 4}" fill="var(--muted)" font-size="12" text-anchor="end">${escapeHtml(label)}</text>`;
    }).join("");
    const bars = points.map((point, index) => {
      const x = padLeft + step * index + step / 2;
      const chatHeight = maxValue ? point.chat / maxValue * innerHeight : 0;
      const cliHeight = maxValue ? point.cli / maxValue * innerHeight : 0;
      const cliY = padTop + innerHeight - cliHeight;
      const chatY = cliY - chatHeight;
      const tooltip = `${point.key}
Chat ${metric.label}: ${metric.format(point.chat)}
CLI ${metric.label}: ${metric.format(point.cli)}`;
      return `
          <rect x="${x - barWidth / 2}" y="${cliY}" width="${barWidth}" height="${Math.max(0, cliHeight)}" fill="var(--yellow)" opacity="0.85"><title>${escapeHtml(tooltip)}</title></rect>
          <rect x="${x - barWidth / 2}" y="${Math.max(padTop, chatY)}" width="${barWidth}" height="${Math.max(0, chatHeight)}" fill="${metric.color}" opacity="0.85"><title>${escapeHtml(tooltip)}</title></rect>
          <text x="${x}" y="${height - 16}" fill="var(--muted)" font-size="11" text-anchor="middle">${escapeHtml(point.key.slice(5) || point.key)}</text>`;
    }).join("");
    return `
        <div class="chart-card">
          <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
            ${gridLines}
            <line x1="${padLeft}" y1="${padTop + innerHeight}" x2="${width - padRight}" y2="${padTop + innerHeight}" stroke="var(--border)" />
            ${bars}
          </svg>
          <div class="chart-legend">
            <span class="legend-item"><span class="legend-swatch" style="background:${metric.color}"></span>Chat ${escapeHtml(metric.label)}</span>
            <span class="legend-item"><span class="legend-swatch" style="background:var(--yellow)"></span>CLI ${escapeHtml(metric.label)}</span>
          </div>
        </div>`;
  }

  // web/js/tab-analysis.js
  function getAnalysisFilterState() {
    const cf = window.CopilotFilters;
    if (!cf || typeof cf !== "object") return { active: false };
    try {
      const current = typeof cf.currentFilters === "function" ? cf.currentFilters() : null;
      const range = typeof cf.periodRange === "function" ? cf.periodRange() : { start: null, end: null };
      return { active: true, cf, current, range };
    } catch (_err) {
      return { active: false };
    }
  }
  function sourceAllows(filterState, sourceKind) {
    if (!filterState.active || !filterState.current) return true;
    const activeSource = filterState.current.source;
    if (!activeSource || activeSource === "all") return true;
    return activeSource === sourceKind;
  }
  function withinRange(filterState, timestampMs) {
    if (!filterState.active) return true;
    const { start, end } = filterState.range || {};
    const ts = Number(timestampMs || 0);
    if (!ts) return true;
    if (start !== null && start !== void 0 && ts < start) return false;
    if (end !== null && end !== void 0 && ts > end) return false;
    return true;
  }
  function analysisFilterLabel(filterState) {
    if (!filterState.active || !filterState.current) return "";
    const f = filterState.current || {};
    const parts = [];
    if (f.period) parts.push(f.period === "custom" ? "custom range" : f.period);
    if (f.source && f.source !== "all") parts.push(`source: ${f.source}`);
    return parts.length ? ` \xB7 Global filters applied (${escapeHtml(parts.join(", "))})` : "";
  }
  function analysisSubtabs() {
    const tabs = [
      ["models", "Model usage"],
      ["tools", "Tool impact"],
      ["files", "File activity"],
      ["monthlyTrends", "Monthly trends"],
      ["insights", "Insights"]
    ];
    return `<div class="analysis-subtabs">${tabs.map(([id, label]) => `<button type="button" class="subtab-button ${STATE.analysisTab === id ? "active" : ""}" onclick="switchAnalysisTab('${id}')">${escapeHtml(label)}</button>`).join("")}</div>`;
  }
  function renderModelsSubtab() {
    const analysis = analysisForMode();
    const cli = APP_DATA.cli || {};
    const filterState = getAnalysisFilterState();
    const showChat = sourceAllows(filterState, "chat");
    const showCli = sourceAllows(filterState, "cli");
    const cliModelsSection = showCli && cli.available && (cli.byModel || []).length ? `
        <section class="panel" style="margin-top:16px">
          <h2 class="section-title">GitHub Copilot CLI \u2013 model usage</h2>
          <div class="section-subtitle">Separate cost pool from VS Code Copilot Chat (session-store.db totals).</div>
          ${renderTable([
      { title: "Model", render: (row) => `<div><strong>${escapeHtml(row.name)}</strong><div class="note small">${formatInteger(row.calls)} calls</div></div>`, csv: (row) => row.name },
      { title: "Input", numeric: true, render: (row) => `<span class="value input">${formatInteger(row.input)}</span>`, csv: (row) => row.input },
      { title: "Cached-read input", numeric: true, render: (row) => `<span class="value cached">${formatInteger(row.cached)}</span>`, csv: (row) => row.cached },
      { title: "Output", numeric: true, render: (row) => `<span class="value output">${formatInteger(row.output)}</span>`, csv: (row) => row.output },
      { title: "Cost", numeric: true, render: (row) => `<span class="value cost">${formatCost(row.cost)}</span>`, csv: (row) => row.cost }
    ], cli.byModel || [], { exportId: "analysis-cli-models", exportFilename: "cli-model-usage.csv" })}
        </section>` : "";
    const chatModelsSection = showChat ? `
        <section class="panel">
          <h2 class="section-title">Model usage</h2>
          <div class="section-subtitle">These totals use <strong>${isBilledMode() ? "billed per-call totals" : "prompt-growth attribution"}</strong>. If a session switches models, each call is counted under the model that served it.${analysisFilterLabel(filterState)}</div>
          ${renderTable([
      { title: "Model", render: (row) => `<div><strong>${escapeHtml(row.name)}</strong><div class="note small">${formatInteger(row.count)} chat calls across ${formatInteger(row.sessionCount)} sessions</div></div>`, csv: (row) => row.name },
      { title: "Total input", numeric: true, render: (row) => `<span class="value input">${formatInteger(row.input)}</span>`, csv: (row) => row.input },
      { title: "Uncached input", numeric: true, render: (row) => `<span class="value uncached">${formatInteger(row.uncached)}</span>`, csv: (row) => row.uncached },
      { title: "Cached-read input", numeric: true, render: (row) => `<span class="value cached">${formatInteger(row.cached)}</span>`, csv: (row) => row.cached },
      { title: "Output", numeric: true, render: (row) => `<span class="value output">${formatInteger(row.output)}</span>`, csv: (row) => row.output },
      { title: "Cached share", numeric: true, render: (row) => formatPercent(row.cacheHitRate), csv: (row) => row.cacheHitRate },
      { title: "Avg TTFT", numeric: true, render: (row) => formatDuration(row.avgTtftMs), csv: (row) => row.avgTtftMs },
      { title: "Cost", numeric: true, render: (row) => `<span class="value cost">${formatCost(row.cost)}</span>`, csv: (row) => row.cost }
    ], analysis.models || [], { exportId: "analysis-models", exportFilename: "model-usage.csv" })}
        </section>` : `<div class="panel is-empty">Chat models hidden by the global source filter (showing CLI only).</div>`;
    return `${chatModelsSection}
        ${cliModelsSection}`;
  }
  function renderToolImpactSubtabs() {
    const tabs = [
      ["usage", isBilledMode() ? "Usage (billed est.)" : "Usage attribution"],
      ["waste", "Unused tool waste"]
    ];
    return `<div class="analysis-subtabs" style="margin-top:10px">${tabs.map(([id, label]) => `<button type="button" class="subtab-button ${STATE.toolImpactTab === id ? "active" : ""}" onclick="switchToolImpactTab('${id}')">${escapeHtml(label)}</button>`).join("")}</div>`;
  }
  function renderToolsUsageSubtab() {
    const analysis = analysisForMode();
    const search = (STATE.toolImpactSearch || "").trim().toLowerCase();
    const filteredTools = [...analysis.tools || []].filter((row) => {
      if (!search) return true;
      return String(row.name || "").toLowerCase().includes(search) || String(row.mode || "").toLowerCase().includes(search);
    });
    const tools = sortRows(filteredTools, STATE.toolSortKey || "cost", STATE.toolSortDir || "desc");
    function toolSortArrow(key) {
      if ((STATE.toolSortKey || "cost") !== key) return '<span style="opacity:.4">\u2195</span>';
      return (STATE.toolSortDir || "desc") === "desc" ? "\u2193" : "\u2191";
    }
    function thBtn(key, line1, line2) {
      return `<th class="num"><button type="button" onclick="setToolSort('${key}')" style="all:unset;cursor:pointer;color:inherit;text-align:right;display:block;width:100%"><span style="display:block;line-height:1.2;font-size:.72rem">${line1}</span><span style="display:block;line-height:1.2;font-size:.72rem">${line2} ${toolSortArrow(key)}</span></button></th>`;
    }
    const totals = { count: 0, errors: 0, durationMs: 0, input: 0, output: 0, cached: 0, cost: 0, payloadTokens: 0 };
    tools.forEach((t) => {
      totals.count += t.count;
      totals.errors += t.errors;
      totals.durationMs += t.durationMs;
      totals.input += t.input;
      totals.output += t.output;
      totals.cached += t.cached;
      totals.cost += t.cost;
      totals.payloadTokens += t.payloadTokens;
    });
    registerTableExport("analysis-tools-usage", [
      { title: "Tool", csv: (row) => row.name },
      { title: "Mode", csv: (row) => row.mode },
      { title: "Calls", csv: (row) => row.count },
      { title: "Errors", csv: (row) => row.errors },
      { title: "Avg duration ms", csv: (row) => row.avgDurationMs },
      { title: "Avg input", csv: (row) => row.avgInput },
      { title: "Avg output", csv: (row) => row.avgOutput },
      { title: "Avg cached", csv: (row) => row.avgCached },
      { title: "Avg cost", csv: (row) => row.avgCost },
      { title: "Total input", csv: (row) => row.input },
      { title: "Total output", csv: (row) => row.output },
      { title: "Total cached", csv: (row) => row.cached },
      { title: "Total cost", csv: (row) => row.cost },
      { title: "Avg payload", csv: (row) => row.avgPayloadTokens }
    ], tools, "tool-usage.csv");
    return `
          <div class="section-subtitle">${isBilledMode() ? "<strong>Payload</strong> = approx token size of tool input + output text. In billed mode, tool/file splits are billed-adjusted estimates derived from attribution shares." : "<strong>Payload</strong> = approx token size of tool input + output text, used as weight when splitting prompt growth."}</div>
          <div style="display:flex;justify-content:flex-end;margin-bottom:8px">${renderCsvExportButton("analysis-tools-usage")}</div>
          <div class="table-scroll">
          <table>
            <thead><tr>
              <th><button type="button" onclick="setToolSort('name')" style="all:unset;cursor:pointer;color:inherit">Tool ${toolSortArrow("name")}</button></th>
              ${thBtn("count", "Calls", "")}
              ${thBtn("avgDurationMs", "Avg", "Duration")}
              ${thBtn("avgInput", "Avg", "Input")}
              ${thBtn("avgOutput", "Avg", "Output")}
              ${thBtn("avgCached", "Avg", "Cached")}
              ${thBtn("avgCost", "Avg", "Cost")}
              ${thBtn("input", "Total", "Input")}
              ${thBtn("output", "Total", "Output")}
              ${thBtn("cached", "Total", "Cached")}
              ${thBtn("cost", "Total", "Cost")}
              ${thBtn("avgPayloadTokens", "Avg", "Payload")}
            </tr></thead>
            <tbody>
              ${tools.length ? tools.map((row) => `<tr>
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
              </tr>`).join("") : `<tr><td colspan="12" class="note">No tools matched your search.</td></tr>`}
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
  function renderToolWasteSubtab() {
    const analysis = analysisForMode();
    const search = (STATE.toolImpactSearch || "").trim().toLowerCase();
    const filteredRows = [...analysis.toolCatalog || []].filter((row) => {
      if (!search) return true;
      return String(row.name || "").toLowerCase().includes(search) || String(row.description || "").toLowerCase().includes(search);
    });
    const rows = sortRows(filteredRows, STATE.toolWasteSortKey || "wastedInputTokens", STATE.toolWasteSortDir || "desc");
    function arrow(key) {
      if ((STATE.toolWasteSortKey || "wastedInputTokens") !== key) return '<span style="opacity:.4">\u2195</span>';
      return (STATE.toolWasteSortDir || "desc") === "desc" ? "\u2193" : "\u2191";
    }
    function th(key, label, numeric) {
      return `<th class="${numeric ? "num" : ""}"><button type="button" onclick="setToolWasteSort('${key}')" style="all:unset;cursor:pointer;color:inherit;display:block;width:100%;text-align:${numeric ? "right" : "left"}">${label} ${arrow(key)}</button></th>`;
    }
    const totals = rows.reduce((acc, row) => {
      acc.present += Number(row.presentCount || 0);
      acc.unused += Number(row.unusedPresentCount || 0);
      acc.wastedInput += Number(row.wastedInputTokens || 0);
      acc.wastedUncached += Number(row.wastedUncachedTokens || 0);
      acc.wastedCached += Number(row.wastedCachedTokens || 0);
      return acc;
    }, { present: 0, unused: 0, wastedInput: 0, wastedUncached: 0, wastedCached: 0 });
    const totalWastePercent = totals.present ? totals.unused / totals.present * 100 : 0;
    registerTableExport("analysis-tools-waste", [
      { title: "Tool", csv: (row) => row.name },
      { title: "Description tokens", csv: (row) => row.descriptionTokens },
      { title: "Present in calls", csv: (row) => row.presentCount },
      { title: "Actual calls", csv: (row) => row.callCount },
      { title: "Unused passes", csv: (row) => row.unusedPresentCount },
      { title: "Waste %", csv: (row) => row.wastePercent },
      { title: "Waste total input", csv: (row) => row.wastedInputTokens },
      { title: "Waste uncached input", csv: (row) => row.wastedUncachedTokens },
      { title: "Waste cached-read input", csv: (row) => row.wastedCachedTokens },
      { title: "Sessions", csv: (row) => row.sessionCount },
      { title: "Tool sets", csv: (row) => row.toolSetCount }
    ], rows, "tool-waste.csv");
    return `
        <div class="section-subtitle"><strong>Waste</strong> estimates the description tokens for a tool each time that tool was present in the model toolset but was not called by that LLM response. Cached/uncached split is estimated from that call's observed cache-read ratio.${isBilledMode() ? " In billed mode, these totals are billed-adjusted estimates." : ""}</div>
        <div style="display:flex;justify-content:flex-end;margin-bottom:8px">${renderCsvExportButton("analysis-tools-waste")}</div>
        <div class="table-scroll">
        <table>
          <thead><tr>
            ${th("name", "Tool", false)}
            ${th("descriptionTokens", "Description tokens", true)}
            ${th("presentCount", "Present in calls", true)}
            ${th("callCount", "Actual calls", true)}
            ${th("unusedPresentCount", "Unused passes", true)}
            ${th("wastePercent", "Waste %", true)}
            ${th("wastedInputTokens", "Waste total input", true)}
            ${th("wastedUncachedTokens", "Waste uncached input", true)}
            ${th("wastedCachedTokens", "Waste cached-read input", true)}
            ${th("sessionCount", "Sessions", true)}
            ${th("toolSetCount", "Tool sets", true)}
          </tr></thead>
          <tbody>
            ${rows.length ? rows.map((row) => `<tr>
              <td><details><summary><strong>${escapeHtml(row.name)}</strong></summary><pre>${escapeHtml(row.description || "[No description captured for this tool.]")}</pre></details></td>
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
            </tr>`).join("") : `<tr><td colspan="11" class="note">No tools matched your search.</td></tr>`}
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
  function renderCliToolImpactSection() {
    const cli = APP_DATA.cli || {};
    if (!sourceAllows(getAnalysisFilterState(), "cli")) return "";
    if (!cli.otelAvailable || !(cli.tools || []).length) return "";
    return `
        <section class="panel" style="margin-top:16px">
          <h2 class="section-title">GitHub Copilot CLI \u2013 tool impact</h2>
          <div class="section-subtitle">From native OpenTelemetry <code>execute_tool</code> spans. Calls/duration only \u2014 no token/cost figures (CLI's session-store.db does not attribute tokens per tool).</div>
          ${renderTable([
      { title: "Tool", render: (row) => `<strong>${escapeHtml(row.tool)}</strong>`, csv: (row) => row.tool },
      { title: "Calls", numeric: true, render: (row) => formatInteger(row.calls), csv: (row) => row.calls },
      { title: "Sessions", numeric: true, render: (row) => formatInteger(row.sessionCount), csv: (row) => row.sessionCount },
      { title: "Avg duration", numeric: true, render: (row) => formatDuration(row.avgDurationMs), csv: (row) => row.avgDurationMs },
      { title: "Total duration", numeric: true, render: (row) => formatDuration(row.totalDurationMs), csv: (row) => row.totalDurationMs }
    ], cli.tools || [], { exportId: "analysis-cli-tools", exportFilename: "cli-tool-impact.csv" })}
        </section>`;
  }
  function renderToolsSubtab() {
    const filterState = getAnalysisFilterState();
    if (!sourceAllows(filterState, "chat")) {
      return `<div class="panel is-empty">Chat tool impact hidden by the global source filter (showing CLI only).</div>${renderCliToolImpactSection()}`;
    }
    return `
        <section class="panel">
          <h2 class="section-title">Tool impact</h2>
          <div class="tool-catalog-controls">
            <input type="text" id="toolImpactSearchInput" placeholder="Search tools by name/mode/description\u2026" value="${escapeHtml(STATE.toolImpactSearch)}" oninput="setToolImpactSearch(this.value)">
          </div>
          ${analysisFilterLabel(filterState) ? `<div class="note small">${analysisFilterLabel(filterState)}</div>` : ""}
          ${renderToolImpactSubtabs()}
          ${STATE.toolImpactTab === "waste" ? renderToolWasteSubtab() : renderToolsUsageSubtab()}
        </section>
        ${renderCliToolImpactSection()}`;
  }
  function renderFilesSubtab() {
    const analysis = analysisForMode();
    const filterState = getAnalysisFilterState();
    if (!sourceAllows(filterState, "chat")) {
      return `<div class="panel is-empty">Chat file activity hidden by the global source filter (showing CLI only).</div>${renderCliFilesSection()}`;
    }
    const search = (STATE.fileSearch || "").trim().toLowerCase();
    const filtered = [...analysis.files || []].filter((row) => {
      if (!search) return true;
      const tools = (row.tools || []).join(" ").toLowerCase();
      return String(row.name || "").toLowerCase().includes(search) || String(row.path || "").toLowerCase().includes(search) || String(row.shortPath || "").toLowerCase().includes(search) || tools.includes(search);
    });
    const rows = sortFiles(filtered);
    const columns = [
      ["name", "File"],
      ["readCount", "Reads"],
      ["editCount", "Edits"],
      ["avgInput", "Avg Input"],
      ["avgOutput", "Avg Output"],
      ["avgCached", "Avg Cached"],
      ["input", "Total Input"],
      ["output", "Total Output"],
      ["cached", "Total Cached"],
      ["payloadTokens", "Payload"],
      ["avgCost", "Avg Cost"],
      ["cost", "Cost"]
    ];
    registerTableExport("analysis-files", columns.map(([key, label]) => ({ title: label, csv: (row) => row[key] })), rows, "file-activity.csv");
    const fileTotals = { readCount: 0, editCount: 0, input: 0, output: 0, cached: 0, cost: 0, payloadTokens: 0 };
    rows.forEach((r) => {
      fileTotals.readCount += r.readCount;
      fileTotals.editCount += r.editCount;
      fileTotals.input += r.input;
      fileTotals.output += r.output;
      fileTotals.cached += r.cached;
      fileTotals.cost += r.cost;
      fileTotals.payloadTokens += r.payloadTokens;
    });
    const totalOps = fileTotals.readCount + fileTotals.editCount;
    return `
        <section class="panel">
          <h2 class="section-title">File activity</h2>
          <div class="section-subtitle">Click a file to see per-tool usage summary. ${isBilledMode() ? "Values are billed-adjusted estimates based on observed attribution shares." : "Long paths shortened; hover for full path."}${analysisFilterLabel(filterState)}</div>
          <div class="tool-catalog-controls" style="justify-content:space-between">
            <input type="text" id="fileSearchInput" placeholder="Search files by name/path/tool\u2026" value="${escapeHtml(STATE.fileSearch)}" oninput="setFileSearch(this.value)">
            ${renderCsvExportButton("analysis-files")}
          </div>
          <div class="table-scroll">
          <table class="table-collapse">
            <thead>
              <tr>
                ${columns.map(([key, label]) => `<th class="${key !== "name" ? "num" : ""}"><button type="button" onclick="setFileSort('${key}')" style="all:unset;cursor:pointer;color:inherit">${escapeHtml(label)} ${sortArrow(key)}</button></th>`).join("")}
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
              </tr>`).join("")}
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
  function renderCliFilesSection() {
    const cli = APP_DATA.cli || {};
    if (!sourceAllows(getAnalysisFilterState(), "cli")) return "";
    const cliFiles = (cli.files || []).slice(0, 20);
    if (!cli.available || !cliFiles.length) return "";
    return `
        <section class="panel" style="margin-top:16px">
          <h2 class="section-title">GitHub Copilot CLI \u2013 file activity <span class="note small" style="font-weight:400">(top ${cliFiles.length} of ${formatInteger((cli.files || []).length)})</span></h2>
          <div class="section-subtitle">Files touched via CLI sessions (create/edit tool calls), aggregated across all sessions. See the CLI tab for the per-session breakdown.</div>
          ${renderTable([
      { title: "File", render: (row) => `<div title="${escapeHtml(row.path)}"><strong>${escapeHtml(row.path.split("/").pop() || row.path)}</strong></div>`, csv: (row) => row.path },
      { title: "Created", numeric: true, render: (row) => formatInteger(row.created), csv: (row) => row.created },
      { title: "Edited", numeric: true, render: (row) => formatInteger(row.edited), csv: (row) => row.edited },
      { title: "Total touches", numeric: true, render: (row) => formatInteger(row.touches), csv: (row) => row.touches },
      { title: "Sessions", numeric: true, render: (row) => formatInteger(row.sessionCount), csv: (row) => row.sessionCount }
    ], cliFiles, { exportId: "analysis-cli-files", exportFilename: "cli-file-activity.csv" })}
        </section>`;
  }
  function monthKeyToMs(monthKey) {
    if (!monthKey) return null;
    const t = (/* @__PURE__ */ new Date(`${monthKey}-01T00:00:00`)).getTime();
    return Number.isFinite(t) ? t : null;
  }
  function renderMonthlyTrendsSubtab() {
    const analysis = analysisForMode();
    const filterState = getAnalysisFilterState();
    const allRows = [...analysis.monthlyTrends || []].sort((a, b) => String(a.monthKey || "").localeCompare(String(b.monthKey || "")));
    const rows = filterState.active ? allRows.filter((row) => withinRange(filterState, monthKeyToMs(row.monthKey))) : allRows;
    const cliBuckets = cliMonthlyBuckets();
    const cliHasData = sourceAllows(filterState, "cli") && Object.keys(cliBuckets).length > 0;
    if (!rows.length) {
      return `<section class="panel"><h2 class="section-title">Monthly trends</h2><div class="is-empty">No monthly data found for the current global filters. Try widening the period or switching source back to "All".</div></section>`;
    }
    const metricConfig = monthlyTrendMetricConfig();
    const metricKey = metricConfig[STATE.monthlyTrendMetric] ? STATE.monthlyTrendMetric : "cost";
    const metric = metricConfig[metricKey];
    const latest = rows[rows.length - 1];
    const previous = rows.length > 1 ? rows[rows.length - 2] : null;
    const latestValue = Number(metric.value(latest) || 0);
    const previousValue = Number(previous ? metric.value(previous) : 0);
    const delta = latestValue - previousValue;
    const deltaPercent = previous ? previousValue ? delta / previousValue * 100 : null : null;
    const deltaSign = delta > 0 ? "+" : "";
    const comparisonValue = previous ? escapeHtml(metric.format(previousValue)) : "";
    const deltaLabel = metric.isRate ? `${delta > 0 ? "+" : ""}${delta.toFixed(1)} pp` : `${deltaSign}${escapeHtml(metric.format(Math.abs(delta)))}${deltaPercent === null ? "" : `, ${deltaPercent > 0 ? "+" : ""}${deltaPercent.toFixed(1)}%`}`;
    registerTableExport("analysis-monthly-trends", [
      { title: "Month", csv: (row) => row.label || row.monthKey },
      { title: "Sessions", csv: (row) => row.sessionCount },
      { title: "Chat calls", csv: (row) => row.chatCallCount },
      { title: "Tool calls", csv: (row) => row.toolCallCount },
      { title: "Input", csv: (row) => {
        var _a;
        return (_a = row.totals) == null ? void 0 : _a.input;
      } },
      { title: "Uncached", csv: (row) => {
        var _a;
        return (_a = row.totals) == null ? void 0 : _a.uncached;
      } },
      { title: "Cached", csv: (row) => {
        var _a;
        return (_a = row.totals) == null ? void 0 : _a.cached;
      } },
      { title: "Output", csv: (row) => {
        var _a;
        return (_a = row.totals) == null ? void 0 : _a.output;
      } },
      { title: "Cost", csv: (row) => {
        var _a;
        return (_a = row.totals) == null ? void 0 : _a.cost;
      } },
      { title: "Cache hit %", csv: (row) => row.cacheHitRate },
      ...cliHasData ? [
        { title: "CLI sessions", csv: (row) => (cliBuckets[row.monthKey] || {}).sessionCount },
        { title: "CLI cost", csv: (row) => (cliBuckets[row.monthKey] || {}).cost }
      ] : []
    ], rows, "monthly-trends.csv");
    return `
        <section class="panel">
          <h2 class="section-title">Monthly trends</h2>
          <div class="section-subtitle">Track month-over-month progress across usage, cost, and efficiency patterns (${escapeHtml(tokenModeLabel())} mode).${analysisFilterLabel(filterState)}</div>
          <div class="analysis-subtabs">
            ${Object.entries(metricConfig).map(([key, cfg]) => `<button type="button" class="subtab-button ${metricKey === key ? "active" : ""}" onclick="switchMonthlyTrendMetric('${key}')">${escapeHtml(cfg.short)}</button>`).join("")}
          </div>
          <div class="note" style="margin-bottom:10px">
            Latest (${escapeHtml(latest.label || latest.monthKey || "current month")}): <strong>${escapeHtml(metric.format(latestValue))}</strong>
            ${previous ? ` \xB7 vs ${escapeHtml(previous.label || previous.monthKey || "previous month")}: <strong style="color:${delta < 0 ? "var(--green)" : delta > 0 ? "var(--red)" : "var(--muted)"}">${comparisonValue}</strong>${deltaLabel ? ` (${deltaLabel})` : ""}` : ""}
          </div>
          ${renderMonthlyTrendChart(rows, metricKey)}
          <div style="display:flex;justify-content:flex-end;margin-top:12px">${renderCsvExportButton("analysis-monthly-trends")}</div>
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
                  ${cliHasData ? '<th class="num">CLI sessions</th><th class="num">CLI cost</th>' : ""}
                </tr>
              </thead>
              <tbody>
                ${rows.map((row) => {
      var _a, _b, _c, _d, _e;
      return `<tr>
                  <td>${escapeHtml(row.label || row.monthKey || "\u2014")}</td>
                  <td class="num">${formatInteger(row.sessionCount || 0)}</td>
                  <td class="num">${formatInteger(row.chatCallCount || 0)}</td>
                  <td class="num">${formatInteger(row.toolCallCount || 0)}</td>
                  <td class="num"><span class="value input">${formatCompact(((_a = row.totals) == null ? void 0 : _a.input) || 0)}</span></td>
                  <td class="num"><span class="value uncached">${formatCompact(((_b = row.totals) == null ? void 0 : _b.uncached) || 0)}</span></td>
                  <td class="num"><span class="value cached">${formatCompact(((_c = row.totals) == null ? void 0 : _c.cached) || 0)}</span></td>
                  <td class="num"><span class="value output">${formatCompact(((_d = row.totals) == null ? void 0 : _d.output) || 0)}</span></td>
                  <td class="num"><span class="value cost">${formatCost(((_e = row.totals) == null ? void 0 : _e.cost) || 0)}</span></td>
                  <td class="num">${formatPercent(row.cacheHitRate || 0)}</td>
                  ${cliHasData ? `<td class="num">${formatInteger((cliBuckets[row.monthKey] || {}).sessionCount || 0)}</td><td class="num"><span class="value cost">${formatCost((cliBuckets[row.monthKey] || {}).cost || 0)}</span></td>` : ""}
                </tr>`;
    }).join("")}
              </tbody>
            </table>
          </div>
          ${cliHasData ? '<div class="note small" style="margin-top:8px">CLI sessions/cost columns come from GitHub Copilot CLI usage (session-store.db), bucketed by month and shown alongside VS Code Copilot Chat trends for a whole-project view.</div>' : ""}
        </section>`;
  }
  function ensureInsightFilterState() {
    if (!STATE.insightFilters || typeof STATE.insightFilters !== "object") {
      STATE.insightFilters = { severity: "all", savingsOnly: false };
    }
    return STATE.insightFilters;
  }
  function insightSeverityStateClass(severity) {
    if (severity === "critical") return "state-critical";
    if (severity === "warn") return "state-warn";
    return "state-ok";
  }
  function insightConfidenceBadgeClass(confidence) {
    if (confidence === "high") return "confidence-high";
    if (confidence === "medium") return "confidence-medium";
    return "confidence-low";
  }
  function humanizeEvidenceKey(key) {
    return String(key || "").replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/^./, (c) => c.toUpperCase());
  }
  function formatEvidenceValue(key, value) {
    if (value === null || value === void 0 || value === "") return "\u2014";
    if (Array.isArray(value)) return value.length ? value.join(", ") : "\u2014";
    const lowerKey = String(key || "").toLowerCase();
    if (typeof value === "number") {
      if (lowerKey.includes("cost")) return formatCost(value);
      if (lowerKey.includes("percent") || lowerKey.includes("rate") || lowerKey.includes("fraction")) {
        return lowerKey.includes("fraction") ? formatPercent(value * 100) : formatPercent(value);
      }
      if (lowerKey.includes("timestamp") || lowerKey.endsWith("ts")) return formatTimestamp(value);
      return formatInteger(value);
    }
    return String(value);
  }
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
              <thead><tr>${firstKeys.map((k) => `<th>${escapeHtml(humanizeEvidenceKey(k))}</th>`).join("")}</tr></thead>
              <tbody>
                ${evidence.map((row) => `<tr>${firstKeys.map((k) => `<td data-label="${escapeHtml(humanizeEvidenceKey(k))}">${escapeHtml(formatEvidenceValue(k, row[k]))}</td>`).join("")}</tr>`).join("")}
              </tbody>
            </table>
          </div>`;
    }
    return evidence.map((row, idx) => `
        <div class="meta-card" style="margin-bottom:8px">
          <div class="label">Evidence row ${idx + 1}</div>
          <ul class="help-list">
            ${Object.entries(row || {}).map(([k, v]) => `<li><strong>${escapeHtml(humanizeEvidenceKey(k))}:</strong> ${escapeHtml(formatEvidenceValue(k, v))}</li>`).join("")}
          </ul>
        </div>`).join("");
  }
  function insightSourceLabel(source) {
    if (source === "chat") return "Chat";
    if (source === "cli") return "CLI";
    return "Both";
  }
  function renderRecommendationCard(insight, index) {
    const sevClass = insightSeverityStateClass(insight.severity);
    const savings = insight.estimatedSavings || {};
    const hasSavings = Number(savings.cost || 0) > 0 || Number(savings.premiumRequests || 0) > 0;
    const evidenceCount = Array.isArray(insight.evidence) ? insight.evidence.length : 0;
    return `
        <div class="insight-card ${sevClass}" data-insight-id="${escapeHtml(insight.id || "")}">
          <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap">
            <h4 style="margin:0">${escapeHtml(insight.title || "Untitled finding")}</h4>
            <div class="pill-list">
              <span class="badge source">${escapeHtml(insightSourceLabel(insight.source))}</span>
              <span class="badge ${insightConfidenceBadgeClass(insight.confidence)}">${escapeHtml(String(insight.confidence || "low").toUpperCase())} confidence</span>
            </div>
          </div>
          <p class="note" style="margin:10px 0 0">${escapeHtml(insight.detail || "")}</p>
          <div class="note small" style="margin-top:10px"><strong>Recommended action:</strong> ${escapeHtml(insight.action || "\u2014")}</div>
          ${hasSavings ? `
          <div class="pill-list" style="margin-top:10px;">
            ${Number(savings.cost || 0) > 0 ? `<span class="pill">Est. saving ${escapeHtml(formatCost(savings.cost))}</span>` : ""}
            ${Number(savings.cost || 0) > 0 ? `<span class="pill">${escapeHtml(formatCreditValue(savings.cost))} AI credits</span>` : ""}
            ${Number(savings.premiumRequests || 0) > 0 ? `<span class="pill" title="Legacy meter: annual request-billed Pro/Pro+ only.">${escapeHtml(formatInteger(savings.premiumRequests))} premium req. (legacy)</span>` : ""}
          </div>` : `<div class="note small" style="margin-top:10px">Informational \u2014 no quantifiable saving.</div>`}
          <details style="margin-top:10px" id="insight-evidence-${index}">
            <summary class="note small">Evidence (${formatInteger(evidenceCount)})</summary>
            <div style="margin-top:8px">${renderEvidenceBlock(insight.evidence, insight.id)}</div>
          </details>
        </div>`;
  }
  function filteredInsights() {
    const state = ensureInsightFilterState();
    const scoped = filterInsightsBySource(APP_DATA.insights);
    const visible = scoped.visible.filter((insight) => {
      if (state.severity !== "all" && insight.severity !== state.severity) return false;
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
            <div style="font-size:1.4rem">\u2713</div>
            <div><strong>No recommendations fired for this data.</strong></div>
            <div class="note small">This dashboard's insights engine only surfaces a finding when a deterministic rule's threshold is actually crossed (see the Info tab for how thresholds are configured) \u2014 an empty list here means nothing in the current usage data looked wasteful, risky, or worth flagging, not a broken feature.</div>
          </section>`;
    }
    const severityOptions = [["all", "All severities"], ["critical", "Critical"], ["warn", "Warn"], ["info", "Info"]];
    const sourceLabel = activeSource === "cli" ? "CLI" : activeSource === "chat" ? "Chat" : "all sources";
    const cards = visible.length ? `<div class="insights-grid">${visible.map((insight, idx) => renderRecommendationCard(insight, idx)).join("")}</div>` : `<div class="is-empty">No recommendations match the current filters. Try another severity, set the source filter above to <strong>All</strong>, or uncheck "only show insights with an estimated saving".</div>`;
    return `
        <section class="panel">
          <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:14px;align-items:flex-start">
            <div>
              <h2 class="section-title" style="margin-bottom:2px">Recommendations</h2>
              <div class="section-subtitle" style="margin-bottom:0">${formatInteger(allInsights.length)} deterministic, evidence-backed finding(s) computed from <strong>all</strong> parsed usage data \u2014 no LLM calls, always reproducible from the same data. The global source filter applies here; the period filter does not, because the rules run once over the whole dataset when the dashboard is generated.</div>
            </div>
            <div style="text-align:right">
              <div class="label" style="color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.04em">Estimated savings available</div>
              <div style="font-size:1.3rem;font-weight:700" class="value cost">${escapeHtml(formatCost(totalCost))}${totalPremium ? ` <span class="note small" style="font-weight:400">= ${escapeHtml(formatCreditValue(totalCost))} AI credits</span>` : ""}</div>
            </div>
          </div>
          <div class="filter-bar" style="margin-top:14px;margin-bottom:0;align-items:center">
            <div class="segmented-control" role="group" aria-label="Filter recommendations by severity">
              ${severityOptions.map(([value, label]) => `<button type="button" class="subtab-button ${state.severity === value ? "active" : ""}" onclick="setInsightSeverityFilter('${value}')">${escapeHtml(label)}</button>`).join("")}
            </div>
            <label class="note small" style="display:flex;align-items:center;gap:6px;min-height:44px">
              <input type="checkbox" ${state.savingsOnly ? "checked" : ""} onchange="setInsightSavingsOnly(this.checked)"> Only show insights with an estimated saving
            </label>
            <button type="button" class="copy-button" onclick="copyInsightsMarkdown(this)">\u{1F4CB} Copy summary as Markdown</button>
          </div>
          <div class="note small" style="margin-top:12px">${formatInteger(visible.length)} of ${formatInteger(allInsights.length)} shown (source: ${escapeHtml(sourceLabel)}).${hiddenCrossSource ? ` ${formatInteger(hiddenCrossSource)} cross-source finding(s) are hidden because they compare Chat against CLI \u2014 switch the source filter to <strong>All</strong> to see them.` : ""} Dollar, AI-credit (1 credit = $0.01) and legacy premium-request figures throughout this panel are local estimates derived from parsed usage data \u2014 not official GitHub billing.</div>
          <div style="margin-top:14px">${cards}</div>
        </section>`;
  }
  function renderInsightsSubtab() {
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
            <li>${formatInteger(cliSummary.sessionCount)} CLI sessions \xB7 ${formatInteger(cliSummary.callCount)} model calls</li>
            <li>${formatInteger(cliSummary.totalInput)} input / ${formatInteger(cliSummary.totalOutput)} output tokens</li>
            <li>${formatPercent(cliSummary.totalInput ? cliSummary.totalCached / cliSummary.totalInput * 100 : 0)} cached-read share</li>
            <li>${formatCost(cliSummary.totalCost)} estimated CLI spend</li>
            <li>${formatInteger(cliSummary.fileCount)} files touched across CLI sessions</li>
            ${cli.otelAvailable ? `<li>${formatInteger(cliSummary.toolCallCount)} tool calls captured via OpenTelemetry (see CLI tab \u2192 Tool impact)</li>` : "<li>Enable OpenTelemetry export (see CLI tab) for a per-tool breakdown</li>"}
          </ul>
        </div>` : `
        <div class="insight-card">
          <h4>GitHub Copilot CLI usage</h4>
          <div class="note small">No local CLI usage found on this machine \u2014 see the CLI tab for setup details.</div>
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
        </div>`).join("");
    const expensiveChats = (analysis.topChats || []).filter((chat) => withinRange(filterState, chat.timestamp)).slice(0, 6).map((chat) => `
        <div class="insight-card">
          <h4 title="${escapeHtml(chat.title)}">${escapeHtml(chat.title.length > 60 ? chat.title.slice(0, 57) + "..." : chat.title)}</h4>
          <div class="note small">${escapeHtml((chat.sessionTitle || "").slice(0, 40))} \xB7 ${escapeHtml(formatTimestamp(chat.timestamp))}</div>
          <div class="pill-list" style="margin-top:10px;">
            <span class="pill">${escapeHtml(chat.model)}</span>
            <span class="pill">Prompt ${formatInteger(chat.promptTokens)}</span>
            <span class="pill">Cached ${formatInteger(chat.cached)}</span>
            <span class="pill">Cost ${formatCost(chat.cost)}</span>
          </div>
        </div>`).join("");
    const slowestTools = (analysis.slowestTools || []).filter((tool) => withinRange(filterState, tool.timestamp)).slice(0, 6).map((tool) => `
        <div class="insight-card">
          <h4 title="${escapeHtml(tool.title)}">${escapeHtml(tool.title.length > 55 ? tool.title.slice(0, 52) + "..." : tool.title)}</h4>
          <div class="note small">${escapeHtml((tool.sessionTitle || "").slice(0, 40))} \xB7 ${escapeHtml(formatTimestamp(tool.timestamp))}</div>
          <div class="pill-list" style="margin-top:10px;">
            <span class="pill">${escapeHtml(tool.name)}</span>
            <span class="pill">${formatDuration(tool.durationMs)}</span>
            <span class="pill">Input ${formatInteger(tool.estimated.input)}</span>
            <span class="pill">${formatCost(tool.estimated.cost)}</span>
          </div>
        </div>`).join("");
    function collapsible(title, innerHtml, startOpen) {
      const openAttr = startOpen ? " open" : "";
      return `<details class="panel collapsible-section" style="cursor:default"${openAttr}>
          <summary style="cursor:pointer;display:flex;align-items:center;gap:8px;user-select:none;padding:14px 18px">
            <span style="font-size:1.2rem;font-weight:700;width:22px;text-align:center;font-family:monospace" class="collapse-icon">${startOpen ? "\u2212" : "+"}</span>
            <h2 class="section-title" style="margin:0">${title}</h2>
          </summary>
          <div style="padding:0 18px 18px">${innerHtml}</div>
        </details>`;
    }
    return `
        <div class="analysis-grid">
          ${renderRecommendationsPanel()}
          ${collapsible("Interesting breakdowns", `
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
                <div class="note small">Combines the summary above with GitHub Copilot CLI usage below \u2014 the two sources use different token-attribution models, so treat this as a rough combined view, not an exact merge.</div>
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
          ${collapsible("Expensive chats", `<div class="insights-grid">${expensiveChats}</div>`, false)}
          ${collapsible("Slowest tools", `<div class="insights-grid">${slowestTools}</div>`, false)}
          ${collapsible("Global token breakdown", renderGlobalTokenPieChart(summary, analysis), true)}
        </div>`;
  }
  function renderAnalysisTab() {
    const tabBodies = {
      models: renderModelsSubtab,
      tools: renderToolsSubtab,
      files: renderFilesSubtab,
      monthlyTrends: renderMonthlyTrendsSubtab,
      insights: renderInsightsSubtab
    };
    if (!tabBodies[STATE.analysisTab]) {
      STATE.analysisTab = "models";
    }
    return `<section class="panel">${analysisSubtabs()}</section>${tabBodies[STATE.analysisTab]()}`;
  }
  function setInsightSeverityFilter(value) {
    ensureInsightFilterState().severity = value;
    renderApp();
  }
  function setInsightSavingsOnly(checked) {
    ensureInsightFilterState().savingsOnly = !!checked;
    renderApp();
  }
  function fallbackCopyToClipboard(text) {
    try {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      return true;
    } catch (_err) {
      return false;
    }
  }
  function flashCopyButton(buttonEl) {
    if (!buttonEl) return;
    const original = buttonEl.textContent;
    buttonEl.textContent = "\u2713 Copied";
    buttonEl.classList.add("copied");
    setTimeout(() => {
      buttonEl.textContent = original;
      buttonEl.classList.remove("copied");
    }, 1500);
  }
  function copyInsightsMarkdown(buttonEl) {
    const insights = filteredInsightsList();
    if (!insights.length) {
      alert("No recommendations match the current filters \u2014 nothing to copy.");
      return;
    }
    const lines = insights.map((insight) => {
      const savings = insight.estimatedSavings || {};
      const savingsBits = [];
      if (Number(savings.cost || 0) > 0) savingsBits.push(formatCost(savings.cost));
      if (Number(savings.premiumRequests || 0) > 0) savingsBits.push(`${formatInteger(savings.premiumRequests)} premium req. (legacy)`);
      const savingsText = savingsBits.length ? ` (est. saving: ${savingsBits.join(", ")})` : "";
      return `- **[${String(insight.severity || "info").toUpperCase()}] ${insight.title}**${savingsText}
  ${insight.detail}
  _Action:_ ${insight.action}`;
    });
    const markdown = `## Copilot usage recommendations

${lines.join("\n\n")}

_Estimates are local approximations derived from parsed usage data, not official GitHub billing._`;
    const finish = () => {
      flashCopyButton(buttonEl);
    };
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      navigator.clipboard.writeText(markdown).then(finish).catch(() => {
        if (fallbackCopyToClipboard(markdown)) finish();
        else alert("Copy failed \u2014 please copy the summary manually from the browser console.");
      });
    } else if (fallbackCopyToClipboard(markdown)) {
      finish();
    } else {
      alert("Copy failed \u2014 please copy the summary manually from the browser console.");
    }
  }
  if (typeof window !== "undefined") {
    Object.assign(window, {
      setInsightSeverityFilter,
      setInsightSavingsOnly,
      copyInsightsMarkdown
    });
  }

  // web/js/tab-cli.js
  function getCliFilterState() {
    const cf = window.CopilotFilters;
    if (!cf || typeof cf !== "object") return { active: false };
    try {
      const sourceOk = typeof cf.matchesSource === "function" ? cf.matchesSource("cli") !== false : true;
      const current = typeof cf.currentFilters === "function" ? cf.currentFilters() : null;
      return { active: true, cf, sourceOk, current };
    } catch (_err) {
      return { active: false };
    }
  }
  function applyGlobalSessionFilter(sessions, filterState) {
    if (!filterState.active) return sessions;
    if (filterState.sourceOk === false) return [];
    const { cf } = filterState;
    if (typeof cf.filterSessions === "function") {
      try {
        const out = cf.filterSessions(sessions, "cli");
        if (Array.isArray(out)) return out;
      } catch (_err) {
      }
    }
    return sessions;
  }
  function filterLabel(filterState) {
    if (!filterState.active || !filterState.current) return "";
    const f = filterState.current || {};
    const parts = [];
    if (f.period) parts.push(f.period === "custom" ? "custom range" : f.period);
    if (f.source && f.source !== "all") parts.push(`source: ${f.source}`);
    return parts.length ? ` \xB7 Global filters applied (${escapeHtml(parts.join(", "))})` : "";
  }
  function premiumMultiplierForModel(modelName) {
    const table = APP_DATA.premium && APP_DATA.premium.multipliers || {};
    const name = String(modelName || "").toLowerCase();
    if (Object.prototype.hasOwnProperty.call(table, name)) return Number(table[name]);
    for (const key of Object.keys(table).sort((a, b) => b.length - a.length)) {
      if (name.startsWith(key) || name.includes(key)) return Number(table[key]);
    }
    return 1;
  }
  function rowPromptCount(session, row) {
    const rows = session.modelBreakdown || [];
    const sessionCalls = rows.reduce((sum, r) => sum + Number(r.calls || 0), 0);
    if (!sessionCalls) return 0;
    const prompts = Number(session.turnCount || 0) || 1;
    return prompts * (Number(row.calls || 0) / sessionCalls);
  }
  function sessionPremiumRequests(session) {
    return (session.modelBreakdown || []).reduce(
      (sum, row) => sum + rowPromptCount(session, row) * premiumMultiplierForModel(row.model),
      0
    );
  }
  var COST_TYPES = ["input", "cache_read", "cache_write", "output"];
  function activeDateRange(filterState) {
    var _a, _b, _c;
    if (!filterState.active || typeof ((_a = filterState.cf) == null ? void 0 : _a.periodRange) !== "function") return null;
    try {
      const range = filterState.cf.periodRange();
      if (!range) return null;
      const start = (_b = range.start) != null ? _b : null;
      const end = (_c = range.end) != null ? _c : null;
      return start === null && end === null ? null : { start, end };
    } catch (_err) {
      return null;
    }
  }
  function bucketInRange(bucket, range) {
    const ts = Number(bucket.lastTs || 0);
    if (!ts) return true;
    if (range.start !== null && ts < range.start) return false;
    if (range.end !== null && ts > range.end) return false;
    return true;
  }
  function sessionRollupRows(session, range) {
    const buckets = session.callBuckets;
    if (!range || !Array.isArray(buckets) || !buckets.length) return session.modelBreakdown || [];
    return buckets.filter((bucket) => bucketInRange(bucket, range));
  }
  function zeroCostByType() {
    return { input: 0, cache_read: 0, cache_write: 0, output: 0 };
  }
  function addCostProvenance(bucket, row) {
    bucket.cost += Number(row.cost || 0);
    const byType = row.costByType || {};
    COST_TYPES.forEach((key) => {
      bucket.costByType[key] += Number(byType[key] || 0);
    });
    const sources = row.costSources || (row.costSource ? { [row.costSource]: 1 } : {});
    Object.keys(sources).forEach((key) => {
      bucket.costSources[key] = Number(bucket.costSources[key] || 0) + Number(sources[key] || 0);
    });
  }
  function finalizeCostProvenance(bucket) {
    const used = Object.keys(bucket.costSources).filter((key) => Number(bucket.costSources[key]) > 0);
    bucket.costSource = used.length === 1 ? used[0] : used.length ? "mixed" : "estimate";
    bucket.costExact = used.length > 0 && used.every((key) => key === "billed" || key === "rates");
    bucket.credits = creditsFromCost(bucket.cost);
    return bucket;
  }
  function computeCliSummaryFromSessions(sessions, range) {
    const summary = {
      sessionCount: 0,
      callCount: 0,
      totalInput: 0,
      totalOutput: 0,
      totalCached: 0,
      totalCacheWrite: 0,
      totalInputBillable: 0,
      totalUncached: 0,
      cost: 0,
      costByType: zeroCostByType(),
      costSources: {},
      fileCount: 0,
      toolCallCount: 0,
      premiumRequests: 0
    };
    const filePaths = /* @__PURE__ */ new Set();
    sessions.forEach((session) => {
      const rows = sessionRollupRows(session, range);
      if (!rows.length) return;
      summary.sessionCount += 1;
      rows.forEach((row) => {
        summary.callCount += Number(row.calls || 0);
        summary.totalInput += Number(row.input || 0);
        summary.totalOutput += Number(row.output || 0);
        summary.totalCached += Number(row.cached || 0);
        summary.totalCacheWrite += Number(row.cacheWrite || 0);
        summary.totalInputBillable += Number(row.inputBillable || 0);
        summary.premiumRequests += rowPromptCount(session, row) * premiumMultiplierForModel(row.model);
        addCostProvenance(summary, row);
      });
      (session.files || []).forEach((file) => filePaths.add(file.path));
      (session.tools || []).forEach((tool) => {
        summary.toolCallCount += Number(tool.calls || 0);
      });
    });
    summary.fileCount = filePaths.size;
    summary.totalUncached = summary.totalInputBillable;
    finalizeCostProvenance(summary);
    summary.totalCost = summary.cost;
    summary.totalCredits = summary.credits;
    return summary;
  }
  function computeCliByModelFromSessions(sessions, range) {
    const map = /* @__PURE__ */ new Map();
    sessions.forEach((session) => {
      sessionRollupRows(session, range).forEach((row) => {
        const key = row.model;
        const bucket = map.get(key) || {
          model: key,
          calls: 0,
          input: 0,
          inputBillable: 0,
          cached: 0,
          cacheWrite: 0,
          output: 0,
          cost: 0,
          costByType: zeroCostByType(),
          costSources: {},
          premiumRequests: 0,
          sessionIds: /* @__PURE__ */ new Set()
        };
        bucket.calls += Number(row.calls || 0);
        bucket.input += Number(row.input || 0);
        bucket.inputBillable += Number(row.inputBillable || 0);
        bucket.cached += Number(row.cached || 0);
        bucket.cacheWrite += Number(row.cacheWrite || 0);
        bucket.output += Number(row.output || 0);
        addCostProvenance(bucket, row);
        bucket.premiumRequests += rowPromptCount(session, row) * premiumMultiplierForModel(row.model);
        bucket.sessionIds.add(session.id);
        map.set(key, bucket);
      });
    });
    return [...map.values()].map((bucket) => finalizeCostProvenance({ ...bucket, uncached: bucket.inputBillable, sessionCount: bucket.sessionIds.size })).sort((a, b) => b.cost - a.cost);
  }
  function buildCliTrendRows(sessions, granularity) {
    const buckets = /* @__PURE__ */ new Map();
    const bucketFor = (key) => {
      let bucket = buckets.get(key);
      if (!bucket) {
        bucket = {
          input: 0,
          uncached: 0,
          cached: 0,
          output: 0,
          cost: 0,
          sessionIds: /* @__PURE__ */ new Set(),
          callCount: 0,
          toolCallCount: 0
        };
        buckets.set(key, bucket);
      }
      return bucket;
    };
    sessions.forEach((session) => {
      const callRows = Array.isArray(session.callBuckets) && session.callBuckets.length ? session.callBuckets : null;
      if (callRows) {
        callRows.forEach((row) => {
          var _a, _b;
          const key = granularity === "daily" ? row.dayKey : row.monthKey;
          if (!key) return;
          const bucket = bucketFor(key);
          bucket.input += Number(row.input || 0);
          bucket.uncached += Number((_b = (_a = row.uncached) != null ? _a : row.inputBillable) != null ? _b : 0);
          bucket.cached += Number(row.cached || 0);
          bucket.output += Number(row.output || 0);
          bucket.cost += Number(row.cost || 0);
          bucket.callCount += Number(row.calls || 0);
          bucket.sessionIds.add(session.id);
        });
      } else {
        const key = granularity === "daily" ? session.dayKey : session.monthKey;
        if (key) {
          const bucket = bucketFor(key);
          bucket.input += Number(session.input || 0);
          bucket.uncached += Number(session.uncached || 0);
          bucket.cached += Number(session.cached || 0);
          bucket.output += Number(session.output || 0);
          bucket.cost += Number(session.cost || 0);
          bucket.callCount += Number(session.callCount || 0);
          bucket.sessionIds.add(session.id);
        }
      }
      const sessionKey = granularity === "daily" ? session.dayKey : session.monthKey;
      if (sessionKey) {
        bucketFor(sessionKey).toolCallCount += (session.tools || []).reduce((sum, tool) => sum + Number(tool.calls || 0), 0);
      }
    });
    return [...buckets.keys()].sort().map((key) => {
      const bucket = buckets.get(key);
      return {
        monthKey: key,
        label: key,
        totals: { input: bucket.input, uncached: bucket.uncached, cached: bucket.cached, output: bucket.output, cost: bucket.cost },
        sessionCount: bucket.sessionIds.size,
        chatCallCount: bucket.callCount,
        toolCallCount: bucket.toolCallCount,
        cacheHitRate: bucket.input ? bucket.cached / bucket.input * 100 : 0
      };
    });
  }
  function switchCliTrendGranularity(value) {
    STATE.cliTrendGranularity = value === "daily" ? "daily" : "monthly";
    renderApp();
  }
  function switchCliTrendMetric(key) {
    STATE.cliTrendMetric = key;
    renderApp();
  }
  function renderCliTrendSection(sessions) {
    if (!sessions.length) return "";
    const granularity = STATE.cliTrendGranularity === "daily" ? "daily" : "monthly";
    const rows = buildCliTrendRows(sessions, granularity);
    if (!rows.length) {
      return `<section class="panel"><h2 class="section-title">CLI usage trends</h2><div class="is-empty">\u{1F4C8}<div>No dated CLI sessions to chart yet.</div></div></section>`;
    }
    const metrics = monthlyTrendMetricConfig();
    const metricKey = metrics[STATE.cliTrendMetric] ? STATE.cliTrendMetric : "cost";
    return `
        <section class="panel">
          <h2 class="section-title">CLI usage trends</h2>
          <div class="section-subtitle">Cost, token, and session trends across CLI sessions currently in view, bucketed by ${granularity === "daily" ? "day" : "month"}.</div>
          <div class="analysis-subtabs" style="margin-bottom:8px">
            <button type="button" class="subtab-button ${granularity === "monthly" ? "active" : ""}" onclick="switchCliTrendGranularity('monthly')">Monthly</button>
            <button type="button" class="subtab-button ${granularity === "daily" ? "active" : ""}" onclick="switchCliTrendGranularity('daily')">Daily</button>
          </div>
          <div class="analysis-subtabs">
            ${Object.entries(metrics).filter(([key]) => key !== "chatCalls" && key !== "toolCalls").map(([key, cfg]) => `<button type="button" class="subtab-button ${metricKey === key ? "active" : ""}" onclick="switchCliTrendMetric('${key}')">${escapeHtml(cfg.short)}</button>`).join("")}
          </div>
          ${renderMonthlyTrendChart(rows, metricKey)}
          <div class="note small" style="margin-top:8px">Bar tooltips read "Chats: N / Tools: M" \u2014 for the CLI tab those are CLI model calls / OTel <code>execute_tool</code> spans in that bucket (0 if OTel is off), reusing the same chart component as the Chats tab.</div>
        </section>`;
  }
  function renderCliEfficiencySection(sessions, cli) {
    if (!sessions.length) return "";
    const overallInput = sessions.reduce((sum, s) => sum + Number(s.input || 0), 0);
    const overallCached = sessions.reduce((sum, s) => sum + Number(s.cached || 0), 0);
    const overallCacheHitRate = overallInput ? overallCached / overallInput * 100 : 0;
    const withRates = sessions.map((session) => ({
      session,
      cacheHitRate: session.input ? session.cached / session.input * 100 : 0,
      costPer1kOutput: session.output ? session.cost / (session.output / 1e3) : 0
    }));
    const lowestCacheHit = [...withRates].filter((r) => r.session.input > 0).sort((a, b) => a.cacheHitRate - b.cacheHitRate).slice(0, 5);
    const priciestSessions = [...sessions].sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0)).slice(0, 10);
    const priciestPer1k = [...withRates].filter((r) => r.session.output > 0).sort((a, b) => b.costPer1kOutput - a.costPer1kOutput).slice(0, 5);
    const priciestModels = [...cli.byModel || []].slice(0, 10);
    const sessionLabel = (session) => escapeHtml((session.repository || session.cwd || session.id || "").toString().slice(0, 60));
    const cacheHitGauge = `
        <div class="gauge state-${overallCacheHitRate >= 50 ? "ok" : overallCacheHitRate >= 20 ? "warn" : "critical"}">
          <div class="gauge-fill state-${overallCacheHitRate >= 50 ? "ok" : overallCacheHitRate >= 20 ? "warn" : "critical"}" style="width:${Math.min(100, overallCacheHitRate).toFixed(1)}%"></div>
        </div>
        <div class="gauge-label"><span>Overall cache-hit rate</span><span>${formatPercent(overallCacheHitRate)} of ${formatInteger(overallInput)} input tokens</span></div>`;
    function cacheStateClass(rate) {
      return rate >= 50 ? "state-ok" : rate >= 20 ? "state-warn" : "state-critical";
    }
    const priciestSessionsTable = renderTable([
      { title: "Session", render: (row) => sessionLabel(row) },
      { title: "Cost", numeric: true, render: (row) => `<span class="value cost">${formatCost(row.cost)}</span>` },
      { title: "Cost / 1K output", numeric: true, render: (row) => formatCost(row.output ? row.cost / (row.output / 1e3) : 0) },
      { title: "Cache hit rate", numeric: true, render: (row) => {
        const rate = row.input ? row.cached / row.input * 100 : 0;
        return `<span class="${cacheStateClass(rate)}">${formatPercent(rate)}</span>`;
      } }
    ], priciestSessions);
    const lowestCacheHitTable = lowestCacheHit.length ? renderTable([
      { title: "Session", render: (row) => sessionLabel(row.session) },
      { title: "Cache hit rate", numeric: true, render: (row) => `<span class="${cacheStateClass(row.cacheHitRate)}">${formatPercent(row.cacheHitRate)}</span>` },
      { title: "Total input", numeric: true, render: (row) => formatInteger(row.session.input) },
      { title: "Cost", numeric: true, render: (row) => formatCost(row.session.cost) }
    ], lowestCacheHit) : '<div class="is-empty">Not enough sessions with input tokens to rank yet.</div>';
    const priciestPer1kTable = priciestPer1k.length ? renderTable([
      { title: "Session", render: (row) => sessionLabel(row.session) },
      { title: "Cost / 1K output", numeric: true, render: (row) => `<span class="value cost">${formatCost(row.costPer1kOutput)}</span>` },
      { title: "Output tokens", numeric: true, render: (row) => formatInteger(row.session.output) }
    ], priciestPer1k) : '<div class="is-empty">No sessions with output tokens to rank yet.</div>';
    const priciestModelsTable = renderTable([
      { title: "Model", render: (row) => `<strong>${escapeHtml(row.model)}</strong>` },
      { title: "Cost", numeric: true, render: (row) => `<span class="value cost">${formatCost(row.cost)}</span>` },
      { title: "Premium reqs (legacy est.)", numeric: true, render: (row) => formatInteger(row.premiumRequests) },
      { title: "Calls", numeric: true, render: (row) => formatInteger(row.calls) }
    ], priciestModels);
    const cliTools = cli.tools || [];
    const otelToolSection = cli.otelAvailable && cliTools.length ? `
          <div class="event-section" style="margin-top:14px">
            <h4>Slowest tools (avg duration, OTel)</h4>
            <div class="table-scroll">${renderTable([
      { title: "Tool", render: (row) => `<strong>${escapeHtml(row.tool)}</strong>` },
      { title: "Avg duration", numeric: true, render: (row) => formatDuration(row.avgDurationMs) },
      { title: "Calls", numeric: true, render: (row) => formatInteger(row.calls) }
    ], [...cliTools].sort((a, b) => Number(b.avgDurationMs || 0) - Number(a.avgDurationMs || 0)).slice(0, 10))}</div>
          </div>
          <div class="event-section" style="margin-top:14px">
            <h4>Most-called tools (OTel)</h4>
            <div class="table-scroll">${renderTable([
      { title: "Tool", render: (row) => `<strong>${escapeHtml(row.tool)}</strong>` },
      { title: "Calls", numeric: true, render: (row) => formatInteger(row.calls) },
      { title: "Total duration", numeric: true, render: (row) => formatDuration(row.totalDurationMs) }
    ], [...cliTools].sort((a, b) => Number(b.calls || 0) - Number(a.calls || 0)).slice(0, 10))}</div>
          </div>
          <div class="note small" style="margin-top:8px">OTel <code>execute_tool</code> spans carry duration only \u2014 no token or cost attribution \u2014 so these tables cannot show a "cost per tool call" figure the way model calls can.</div>` : `<div class="is-empty">Tool duration/call-count breakdown needs the CLI's OpenTelemetry file export \u2014 see the OpenTelemetry status panel at the bottom of this tab for setup steps.</div>`;
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
  function renderCliRepoRollupSection(sessions) {
    if (!sessions.length) return "";
    const map = /* @__PURE__ */ new Map();
    sessions.forEach((session) => {
      const repository = session.repository || session.cwd || "unknown";
      const branch = session.branch || "\u2014";
      const key = `${repository}\0${branch}`;
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
              </tr>`).join("")}
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
  var COST_TYPE_LABELS = {
    input: "Uncached input",
    cache_read: "Cached reads",
    cache_write: "Cache writes",
    output: "Output"
  };
  function renderCliCostProvenance(summary) {
    const total = Number(summary.totalCost || 0);
    const byType = summary.costByType || {};
    const provenance = costProvenance(summary);
    const counts = summary.costSources || {};
    const callsBySource = Object.keys(counts).sort((a, b) => Number(counts[b]) - Number(counts[a])).map((key) => `${formatInteger(counts[key])} ${escapeHtml(key)}`).join(" \xB7 ");
    const rows = COST_TYPES.filter((key) => Number(byType[key] || 0) !== 0).map((key) => {
      const value = Number(byType[key] || 0);
      const share = total ? value / total * 100 : 0;
      return `<li><strong>${COST_TYPE_LABELS[key]}:</strong> ${formatCost(value)} (${formatPercent(share)})</li>`;
    }).join("");
    const sourceExplanation = provenance.exact ? `Every figure above is what GitHub <strong>actually charged</strong>, read per call out of <code>~/.copilot/session-store.db</code> (<code>total_nano_aiu</code>, and the exact per-token rates in <code>token_details_json</code>) and summed \u2014 not re-derived from a rate table. Promotional pricing, long-context tiers and the 10% auto-model-selection discount are therefore already included.` : provenance.source === "mixed" ? `Some calls carry GitHub's own charge and others had to be priced from the published rate table (${callsBySource}), so treat the total as approximate. Calls recorded by an older CLI build have no billing columns to read.` : `No billed figure was recorded for these calls, so the cost is priced from the published rate table. That table cannot see promotions or the 10% auto-model-selection discount, so this can be a few percent off in either direction.`;
    return `
        <details class="method-note">
          <summary class="note small">Where this cost comes from ${costProvenanceBadge(summary)}</summary>
          <div class="note small" style="margin-top:8px">${sourceExplanation}</div>
          ${rows ? `<div class="note small" style="margin-top:8px"><strong>Where the money went</strong><ul style="margin:4px 0 0 18px">${rows}</ul></div>` : ""}
          <div class="note small" style="margin-top:8px">Costs are always summed <em>per call</em>. Re-pricing a month's aggregated tokens in one go would blend rates that differed call to call, so it is never done \u2014 which is why these components add up to the total exactly.</div>
          ${callsBySource ? `<div class="note small" style="margin-top:8px"><strong>Calls by cost source:</strong> ${callsBySource}</div>` : ""}
        </details>`;
  }
  function copyCliSetupSnippet(elementId, buttonEl) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const text = el.textContent || "";
    const finish = () => {
      if (!buttonEl) return;
      const original = buttonEl.textContent;
      buttonEl.textContent = "\u2713 Copied";
      buttonEl.classList.add("copied");
      setTimeout(() => {
        buttonEl.textContent = original;
        buttonEl.classList.remove("copied");
      }, 1500);
    };
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      navigator.clipboard.writeText(text).then(finish).catch(() => {
      });
    }
  }
  function renderCliOtelPanel(cli) {
    const on = !!cli.otelAvailable;
    const paths = cli.otelPaths || [];
    const tools = cli.tools || [];
    const totalSpans = tools.reduce((sum, tool) => sum + Number(tool.calls || 0), 0);
    const toolTypeCount = tools.length;
    const toolTypesLinked = tools.filter((tool) => Number(tool.sessionCount || 0) > 0).length;
    const dbFound = !!cli.available;
    const dbStatus = dbFound ? `Found at <code>${escapeHtml(cli.dbPath || "")}</code>.` : `Not found${cli.dbPath ? ` (looked at <code>${escapeHtml(cli.dbPath)}</code>)` : " (no path resolved \u2014 set <code>COPILOT_CLI_DB</code> or use <code>--cli-db</code>)"}. This is why the CLI tab is empty above.`;
    const statusBody = on ? `
          <div class="state-ok" style="padding:8px 12px;border-radius:8px;background:var(--panel-2)">OTel enrichment is <strong>active</strong> \u2014 parsed from ${paths.length ? paths.map((p) => `<code>${escapeHtml(p)}</code>`).join(", ") : "a configured file-exporter path"}.</div>
          <div class="note small" style="margin-top:10px">
            <strong>Spans read:</strong> ${formatInteger(totalSpans)} <code>execute_tool</code> spans across ${formatInteger(toolTypeCount)} distinct tool names.<br>
            <strong>Session join:</strong> ${formatInteger(toolTypesLinked)}/${formatInteger(toolTypeCount)} tool names linked to at least one session via <code>gen_ai.conversation.id</code>. The backend does not currently expose a per-span join count, only per-tool session linkage, so treat this as a lower bound on the true join rate \u2014 spans without a conversation ID exist but aren't attributable to any session and are excluded from the "linked" count.<br>
            <strong>CLI database:</strong> ${dbStatus}
          </div>` : `
          <div class="${dbFound ? "state-warn" : "state-critical"}" style="padding:8px 12px;border-radius:8px;background:var(--panel-2);margin-bottom:10px">OTel enrichment is <strong>off</strong> \u2014 no spans or metrics were parsed${paths.length ? ` from the configured path(s) (${paths.map((p) => `<code>${escapeHtml(p)}</code>`).join(", ")})` : " (no file-exporter path is configured)"}. Without it, the Tool impact section and OTel-based efficiency views above stay hidden, and there is no independent source to cross-check the billed cost against \u2014 this is expected, not an error. <strong>Cost is unaffected:</strong> it comes from <code>session-store.db</code>, which records what GitHub charged.</div>
          <div class="note small" style="margin-bottom:8px"><strong>CLI database:</strong> ${dbStatus}</div>
          <div class="note small" style="margin-bottom:8px">Per the official docs, CLI OTel activates when any of <code>COPILOT_OTEL_ENABLED=true</code>, <code>OTEL_EXPORTER_OTLP_ENDPOINT</code>, or <code>COPILOT_OTEL_FILE_EXPORTER_PATH</code> is set. This dashboard reads the <strong>file exporter</strong> format, so set <code>COPILOT_OTEL_FILE_EXPORTER_PATH</code> before running <code>copilot</code>, then point the dashboard at that file with <code>--cli-otel-log &lt;path&gt;</code>. With the default <code>otlp-http</code> exporter the CLI posts spans and metrics to a collector on <code>:4318</code> and drops them if nothing is listening, which is why an unset file-exporter path leaves this panel empty.</div>
          <div class="code-block" style="margin-bottom:10px">
            <div class="note small" style="margin-bottom:6px;font-weight:700">PowerShell</div>
            <pre id="cliOtelPsSnippet" style="margin:0;white-space:pre-wrap">$env:COPILOT_OTEL_FILE_EXPORTER_PATH = "$HOME\\.copilot\\otel.jsonl"
copilot
# then, next time you generate the dashboard:
python dashboard_core.py --cli-otel-log "$HOME\\.copilot\\otel.jsonl"</pre>
            <button type="button" class="copy-button" onclick="copyCliSetupSnippet('cliOtelPsSnippet', this)">\u29C9 Copy</button>
          </div>
          <div class="code-block">
            <div class="note small" style="margin-bottom:6px;font-weight:700">bash</div>
            <pre id="cliOtelBashSnippet" style="margin:0;white-space:pre-wrap">export COPILOT_OTEL_FILE_EXPORTER_PATH="$HOME/.copilot/otel.jsonl"
copilot
# then, next time you generate the dashboard:
python dashboard_core.py --cli-otel-log "$HOME/.copilot/otel.jsonl"</pre>
            <button type="button" class="copy-button" onclick="copyCliSetupSnippet('cliOtelBashSnippet', this)">\u29C9 Copy</button>
          </div>`;
    return `
        <section class="panel">
          <h2 class="section-title">OpenTelemetry status</h2>
          <div class="section-subtitle">Diagnostics for the CLI's optional OpenTelemetry file-exporter enrichment layer, and the underlying <code>session-store.db</code> read.</div>
          ${statusBody}
          ${renderCliOtelMetrics(cli)}
        </section>`;
  }
  function renderOtelDelta(row, formatValue) {
    if (!row || row.otel === null || row.otel === void 0 || row.db === null || row.db === void 0) {
      return '<span class="note small">not reported</span>';
    }
    const delta = Number(row.delta || 0);
    if (!delta) return '<span class="badge confidence-high">exact match</span>';
    const pct = row.deltaPct === null || row.deltaPct === void 0 ? "" : ` (${formatSigned(row.deltaPct)}%)`;
    const cls = delta < 0 ? "confidence-medium" : "confidence-low";
    const direction = delta < 0 ? "OTel is short" : "OTel is over";
    return `<span class="badge ${cls}" title="${escapeHtml(direction)} \u2014 the dashboard reports the session-store.db figure regardless.">${formatValue(delta)}${pct}</span>`;
  }
  function renderCliOtelMetrics(cli) {
    const otel = cli.otel || {};
    if (!otel.available) return "";
    const instruments = otel.instruments || [];
    const counts = otel.recordCounts || {};
    const tokens = otel.tokens || {};
    const spend = otel.spend || {};
    const recon = cli.otelReconciliation || {};
    const instrumentTable = instruments.length ? renderTable([
      { title: "Instrument", render: (row) => `<code>${escapeHtml(row.instrument)}</code>` },
      { title: "Unit", render: (row) => row.unit ? `<code>${escapeHtml(row.unit)}</code>` : "\u2014" },
      {
        title: "Read as",
        render: (row) => row.kind ? `<span class="badge ${row.kind === "spend" ? "tool" : "chat"}">${escapeHtml(row.kind)}</span>` : '<span class="badge confidence-low" title="Not recognised as a token or spend instrument, so it is reported but not used.">unclassified</span>'
      },
      { title: "Data points", numeric: true, render: (row) => formatInteger(row.points) },
      { title: "Total", numeric: true, render: (row) => formatInteger(row.total) }
    ], instruments) : "";
    const tokenRecon = recon.tokens || {};
    const tokenReconRows = COST_TYPES.filter((key) => tokenRecon[key]).map((key) => ({ type: key, ...tokenRecon[key] }));
    const tokenReconTable = tokenReconRows.length ? renderTable([
      { title: "Token type", render: (row) => COST_TYPE_LABELS[row.type] || row.type },
      { title: "From OTel", numeric: true, render: (row) => formatInteger(row.otel) },
      { title: "From session-store.db", numeric: true, render: (row) => formatInteger(row.db) },
      { title: "Agreement", render: (row) => renderOtelDelta(row, (delta) => formatSigned(delta)) }
    ], tokenReconRows) : "";
    const spendRecon = recon.spend || {};
    const spendBlock = spend.instrument ? `
          <div class="note small" style="margin-top:10px">
            <strong>Spend instrument:</strong> <code>${escapeHtml(spend.instrument)}</code> reporting ${formatInteger(spend.raw)} <code>${escapeHtml(spend.unit || "unknown unit")}</code>${spend.usd === null || spend.usd === void 0 ? " \u2014 its unit is not one this dashboard can convert to money, so it is shown raw rather than guessed at. A wrong conversion factor would be indistinguishable from a real cost." : ` = ${formatCost(spend.usd)}, versus ${formatCost(spendRecon.db)} billed in <code>session-store.db</code>: ${renderOtelDelta(spendRecon, (delta) => formatCost(delta))}`}
          </div>` : '<div class="note small" style="margin-top:10px">No spend/credit instrument was present in the export, so there is nothing to cross-check the billed cost against. This does not affect the cost shown above, which comes from <code>session-store.db</code>.</div>';
    return `
        <h3 style="margin-top:18px">Metrics &amp; cross-check</h3>
        <div class="note small" style="margin-bottom:10px">
          <strong>Records read:</strong> ${formatInteger(counts.span)} spans, ${formatInteger(counts.metric)} metrics${Number(counts.other || 0) ? `, ${formatInteger(counts.other)} other records skipped` : ""}.
          ${Number(counts.metric || 0) ? "" : " No metric records were found \u2014 with the default <code>otlp-http</code> exporter the CLI sends metrics to a collector instead of a file, and they never reach the dashboard."}
        </div>
        <div class="note small" style="margin-bottom:10px">
          <strong>Tokens seen in metrics/spans:</strong>
          ${COST_TYPES.map((key) => `${COST_TYPE_LABELS[key]} ${formatInteger(tokens[key])}`).join(" \xB7 ")}
        </div>
        ${instrumentTable ? `<div class="table-scroll" style="margin-bottom:10px">${instrumentTable}</div>` : ""}
        ${spendBlock}
        ${tokenReconTable ? `
          <div class="note small" style="margin:12px 0 6px"><strong>OTel vs <code>session-store.db</code></strong> \u2014 two independent records of the same sessions. The dashboard always reports the database figure, since that is what GitHub billed; a non-zero delta means the export is missing (or double-counting) usage, not that the cost is wrong.</div>
          <div class="table-scroll">${tokenReconTable}</div>` : ""}`;
  }
  function renderCliTab() {
    const cli = APP_DATA.cli || {};
    if (!cli.available) {
      return `
          <section class="panel">
            <h2 class="section-title">GitHub Copilot CLI usage</h2>
            <div class="is-empty">
              \u{1F5A5}\uFE0F
              <div>No local CLI usage database found${cli.dbPath ? ` at <code>${escapeHtml(cli.dbPath)}</code>` : ""}.</div>
              <div class="note small">This reads <code>~/.copilot/session-store.db</code> (override with the <code>COPILOT_CLI_DB</code> env var or <code>--cli-db</code> flag), which the Copilot CLI populates locally as you use it \u2014 nothing to enable, just use the CLI on this machine.</div>
            </div>
          </section>
          ${renderCliOtelPanel(cli)}`;
    }
    const filterState = getCliFilterState();
    const allSessions = visibleCliSessions();
    const sessions = applyGlobalSessionFilter(allSessions, filterState);
    const dateRange = activeDateRange(filterState);
    const filtersReducedSet = filterState.active && (dateRange !== null || sessions.length !== allSessions.length);
    const summary = filtersReducedSet ? computeCliSummaryFromSessions(sessions, dateRange) : cli.summary || {};
    const byModelRows = filtersReducedSet ? computeCliByModelFromSessions(sessions, dateRange) : cli.byModel || [];
    const models = [...new Set(sessions.flatMap((row) => row.models || []))].sort();
    const search = (STATE.cliSearch || "").trim().toLowerCase();
    const modelFiltered = STATE.cliModel ? sessions.filter((row) => (row.models || []).includes(STATE.cliModel)) : sessions;
    const filtered = search ? modelFiltered.filter((row) => [row.id, row.cwd, row.repository, row.branch, row.summary, ...row.models || []].some((value) => String(value || "").toLowerCase().includes(search))) : modelFiltered;
    const hiddenCliCount = HIDDEN_CLI_SESSION_IDS.size;
    const totalPremiumRequests = byModelRows.reduce((sum, row) => sum + Number(row.premiumRequests || 0), 0);
    const summaryCards = `
        <section class="panel">
          <h2 class="section-title">GitHub Copilot CLI usage</h2>
          <div class="section-subtitle">Read directly from <code>${escapeHtml(cli.dbPath || "")}</code> on this machine \u2014 local CLI usage only, kept separate from VS Code chat sessions.${filterLabel(filterState)}</div>
          <div class="summary-grid">
            <div class="summary-card"><div class="label">CLI sessions</div><div class="value">${formatInteger(summary.sessionCount)}</div></div>
            <div class="summary-card"><div class="label">Model calls</div><div class="value">${formatInteger(summary.callCount)}</div></div>
            <div class="summary-card" title="All-inclusive prompt tokens: uncached input + cached reads + cache writes."><div class="label">Input tokens</div><div class="value input">${formatInteger(summary.totalInput)}</div></div>
            <div class="summary-card"><div class="label">Cached-read input</div><div class="value cached">${formatInteger(summary.totalCached)}</div></div>
            <div class="summary-card" title="Prompt tokens written into the provider cache. Billed at their own, higher rate (1.25x input for Anthropic models) \u2014 not at the input rate."><div class="label">Cache-write input</div><div class="value">${formatInteger(summary.totalCacheWrite)}</div></div>
            <div class="summary-card"><div class="label">Output tokens</div><div class="value output">${formatInteger(summary.totalOutput)}</div></div>
            <div class="summary-card"><div class="label">${costLabel(summary)}</div><div class="value cost">${formatCost(summary.totalCost)}</div><div class="note small">${costProvenanceBadge(summary)}</div></div>
            <div class="summary-card" title="GitHub meters paid plans in AI credits: 1 credit = $0.01 of model usage."><div class="label">AI credits</div><div class="value cost">${formatCreditValue(summary.totalCost)}</div></div>
            <div class="summary-card"><div class="label">Files touched</div><div class="value">${formatInteger(summary.fileCount)}</div></div>
            <div class="summary-card" title="Legacy per-prompt meter. Credit-billed plans are metered on cost instead \u2014 see the AI credit budget on Overview."><div class="label">Premium requests</div><div class="value">${formatInteger(totalPremiumRequests)}</div><div class="note small">legacy est.</div></div>
            ${cli.otelAvailable ? `<div class="summary-card"><div class="label">Tool calls</div><div class="value">${formatInteger(summary.toolCallCount)}</div><div class="note small">from OTel</div></div>` : ""}
          </div>
          ${renderCliCostProvenance(summary)}
          <details class="method-note">
            <summary class="note small">How premium requests are estimated here</summary>
            <div class="note small" style="margin-top:8px">Premium requests are the legacy meter (annual request-billed Pro/Pro+ only); credit-billed plans are metered on cost \u2014 see the AI credit budget on Overview. Counts are local estimates: one per user prompt (apportioned from <code>turnCount</code>, not per model call) times the model multiplier from <code>APP_DATA.premium.multipliers</code>, not official GitHub billing \u2014 check github.com/settings/billing for the authoritative figures.</div>
          </details>
          ${filterState.active && filterState.sourceOk === false ? '<div class="state-warn" style="padding:8px 12px;border-radius:8px;background:var(--panel-2);margin-top:12px">CLI data is currently hidden by the global source filter. Switch the source filter to "All" or "CLI" to see it here.</div>' : ""}
        </section>`;
    const byModelTable = renderTable([
      { title: "Model", render: (row) => `<div><strong>${escapeHtml(row.model)}</strong><div class="note small">${formatInteger(row.calls)} calls across ${formatInteger(row.sessionCount)} sessions</div></div>` },
      { title: "Input", numeric: true, render: (row) => `<span class="value input">${formatInteger(row.input)}</span>` },
      { title: "Uncached input", numeric: true, render: (row) => `<span class="value uncached">${formatInteger(row.uncached)}</span>` },
      { title: "Cached-read input", numeric: true, render: (row) => `<span class="value cached">${formatInteger(row.cached)}</span>` },
      { title: "Cache-write input", numeric: true, render: (row) => `<span class="value">${formatInteger(row.cacheWrite)}</span>` },
      { title: "Output", numeric: true, render: (row) => `<span class="value output">${formatInteger(row.output)}</span>` },
      { title: "Cost", numeric: true, render: (row) => `<div><span class="value cost">${formatCost(row.cost)}</span><div class="note small">${costProvenanceBadge(row)}</div></div>` },
      { title: "Credits", numeric: true, render: (row) => `<span class="value cost">${formatCreditValue(row.cost)}</span>` },
      { title: "Premium reqs (legacy est.)", numeric: true, render: (row) => formatInteger(row.premiumRequests) }
    ], byModelRows);
    const cliTools = cli.tools || [];
    const toolImpactTable = cliTools.length ? renderTable([
      { title: "Tool", render: (row) => `<strong>${escapeHtml(row.tool)}</strong>` },
      { title: "Calls", numeric: true, render: (row) => formatInteger(row.calls) },
      { title: "Sessions", numeric: true, render: (row) => formatInteger(row.sessionCount) },
      { title: "Avg duration", numeric: true, render: (row) => formatDuration(row.avgDurationMs) },
      { title: "Total duration", numeric: true, render: (row) => formatDuration(row.totalDurationMs) }
    ], cliTools) : "";
    const toolImpactSection = cli.otelAvailable ? `
        <section class="panel">
          <h2 class="section-title">Tool impact <span class="note small" style="font-weight:400">(from OpenTelemetry export)</span></h2>
          <div class="section-subtitle">Real per-tool-call counts and durations, parsed from the CLI's OpenTelemetry JSONL export${(cli.otelPaths || []).length ? `: <code>${escapeHtml((cli.otelPaths || []).join(", "))}</code>` : ""}. Joined onto sessions via <code>gen_ai.conversation.id</code>.</div>
          ${toolImpactTable ? `<div class="table-scroll">${toolImpactTable}</div>` : '<div class="is-empty">No execute_tool spans found in the OTel export yet.</div>'}
        </section>` : "";
    const fileSearch = (STATE.cliFileSearch || "").trim().toLowerCase();
    const files = (cli.files || []).filter((row) => !fileSearch || String(row.path || "").toLowerCase().includes(fileSearch));
    const filesTable = renderTable([
      { title: "File", render: (row) => `<span class="note small" style="word-break:break-all">${escapeHtml(row.path)}</span>` },
      { title: "Created", numeric: true, render: (row) => formatInteger(row.created) },
      { title: "Edited", numeric: true, render: (row) => formatInteger(row.edited) },
      { title: "Total touches", numeric: true, render: (row) => `<strong>${formatInteger(row.touches)}</strong>` },
      { title: "Sessions", numeric: true, render: (row) => formatInteger(row.sessionCount) },
      { title: "Last touched", render: (row) => formatTimestamp(row.lastTouched) }
    ], files.slice(0, 200));
    const cliPageSize = STATE.cliPageSize || 10;
    const cliPageCount = Math.max(1, Math.ceil(filtered.length / cliPageSize));
    if (STATE.cliPage > cliPageCount) STATE.cliPage = cliPageCount;
    const cliPage = Math.max(1, STATE.cliPage || 1);
    const pageSlice = filtered.slice((cliPage - 1) * cliPageSize, cliPage * cliPageSize);
    const sessionCardsHtml = pageSlice.map((session) => renderCliSession(session)).join("");
    const sessionListSection = `
        <section class="panel">
          <div class="filter-bar">
            <input type="text" id="cliSearchInput" placeholder="Search by repository, cwd, branch, session ID, or model\u2026" value="${escapeHtml(STATE.cliSearch || "")}" oninput="setCliSearch(this.value)">
            <select onchange="setCliModelFilter(this.value)">
              <option value="">All models</option>
              ${models.map((model) => `<option value="${escapeHtml(model)}" ${STATE.cliModel === model ? "selected" : ""}>${escapeHtml(model)}</option>`).join("")}
            </select>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-left:auto">
              <button type="button" class="action-chip action-chip--red" onclick="openChatDeleteModal('cli')">\u{1F5D1} Delete CLI sessions</button>
              ${hiddenCliCount ? `<button type="button" class="action-chip action-chip--blue" onclick="restoreHiddenCliSessions()">\u21A9 Restore hidden (${formatInteger(hiddenCliCount)})</button>` : ""}
            </div>
          </div>
          <div class="pagination" style="margin-top:8px">
            <div class="note">Showing ${filtered.length ? `${(cliPage - 1) * cliPageSize + 1}-${Math.min(cliPage * cliPageSize, filtered.length)}` : "0"} of ${formatInteger(filtered.length)} CLI sessions</div>
            <div class="pagination-controls">
              <label class="note">Per page</label>
              <select onchange="setCliPageSize(this.value)">
                ${[5, 10, 20, 50].map((size) => `<option value="${size}" ${cliPageSize === size ? "selected" : ""}>${size}</option>`).join("")}
              </select>
              <button type="button" onclick="changeCliPage(-1)" ${cliPage <= 1 ? "disabled" : ""}>Prev</button>
              <span class="note">Page ${cliPage} / ${cliPageCount}</span>
              <button type="button" onclick="changeCliPage(1)" ${cliPage >= cliPageCount ? "disabled" : ""}>Next</button>
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
          <div class="note small">Files created or edited across all CLI sessions combined (from local file-write history). Expand a session card above and see "Files touched in this session" for a per-session breakdown of the same data. ${cli.otelAvailable ? "Per-tool token/cost breakdown is not shown here since OTel execute_tool spans don't carry token/cost data; see the Tool impact section above for real per-tool call counts and durations." : "Enable the CLI's built-in OpenTelemetry export (set <code>COPILOT_OTEL_FILE_EXPORTER_PATH</code> before running <code>copilot</code>, then pass the file via <code>--cli-otel-log</code>) to also unlock a Tool impact view above."}</div>
          <div class="filter-bar" style="margin-top:8px">
            <input type="text" id="cliFileSearchInput" placeholder="Search by file path\u2026" value="${escapeHtml(STATE.cliFileSearch || "")}" oninput="setCliFileSearch(this.value)">
          </div>
          <h2 class="section-title" style="margin-top:12px">Files (${formatInteger(files.length)}${files.length > 200 ? ", showing top 200" : ""})</h2>
          <div class="table-scroll">${filesTable}</div>
        </section>
        ${renderCliOtelPanel(cli)}`;
  }
  function renderCliSession(session) {
    const modelBadges = (session.models || []).slice(0, 3).map((modelName) => `<span class="badge model">${escapeHtml(modelName)}</span>`).join("");
    const extraModels = (session.models || []).length > 3 ? `<span class="badge source">+${formatInteger(session.models.length - 3)} models</span>` : "";
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
              <div class="subtext">${escapeHtml(session.id)}${session.branch ? ` \xB7 ${escapeHtml(session.branch)}` : ""} \xB7 ${escapeHtml(formatTimestamp(session.lastActivity))} \xB7 ${formatInteger(session.callCount)} calls \xB7 ${formatInteger(session.turnCount)} turns</div>
            </div>
            ${renderStatCell("Total input", formatInteger(session.input), "input")}
            ${renderStatCell("Uncached", formatInteger(session.uncached), "uncached")}
            ${renderStatCell("Cached-read", formatInteger(session.cached), "cached", true)}
            ${renderStatCell("Output", formatInteger(session.output), "output")}
            ${renderStatCell("Turns", formatInteger(session.turnCount))}
            ${renderStatCell("Cost", formatCost(session.cost), "cost")}
          </summary>
          <div class="session-body">
            <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:12px;flex-wrap:wrap">
              <button type="button" class="action-chip action-chip--blue" onclick="event.stopPropagation();openCliFullChatModal('${session.id}')">\u{1F4C2} Show full chat</button>
              <button type="button" class="action-chip action-chip--purple" onclick="event.stopPropagation();openCliModelCompareModal('${session.id}')">\u2696 Compare models</button>
              <button type="button" class="action-chip action-chip--teal" onclick="event.stopPropagation();exportCliSessionToJson('${session.id}')">\u2B07 Export chat JSON</button>
              <button type="button" class="action-chip action-chip--red" onclick="event.stopPropagation();deleteCliSessionPrompt('${session.id}')">\u{1F5D1} Delete chat</button>
            </div>
            ${renderCliSessionMeta(session)}
            ${renderCliModelBreakdown(session)}
            ${renderCliSessionFiles(session)}
            <div class="note small" style="margin-top:12px;text-align:center">Turn-by-turn conversation (user messages + assistant responses) loads in the full chat view \u2014 press <strong>\u{1F4C2} Show full chat</strong>.</div>
          </div>
        </details>`;
  }
  function renderCliSessionMeta(session) {
    return `
        <div class="session-meta">
          <div class="meta-card"><div class="label">Session ID</div><div class="value">${escapeHtml(session.id)}</div></div>
          <div class="meta-card"><div class="label">Repository</div><div class="value">${escapeHtml(session.repository || "\u2014")}</div></div>
          <div class="meta-card"><div class="label">Working directory</div><div class="value" style="word-break:break-all">${escapeHtml(session.cwd || "\u2014")}</div></div>
          <div class="meta-card"><div class="label">Branch</div><div class="value">${escapeHtml(session.branch || "\u2014")}</div></div>
          <div class="meta-card"><div class="label">Model(s) used</div><div class="value">${escapeHtml((session.models || []).join(", ") || "unknown")}</div></div>
          <div class="meta-card"><div class="label">Model calls</div><div class="value">${formatInteger(session.callCount)}</div></div>
          <div class="meta-card"><div class="label">Turns</div><div class="value">${formatInteger(session.turnCount)}</div></div>
          <div class="meta-card"><div class="label">Total input</div><div class="value input">${formatInteger(session.input)}</div></div>
          <div class="meta-card"><div class="label">Uncached input</div><div class="value uncached">${formatInteger(session.uncached)}</div></div>
          <div class="meta-card"><div class="label">Cached-read</div><div class="value cached">${formatInteger(session.cached)}</div></div>
          <div class="meta-card" title="Prompt tokens written into the provider cache, billed at their own higher rate."><div class="label">Cache-write</div><div class="value">${formatInteger(session.cacheWrite)}</div></div>
          <div class="meta-card"><div class="label">Total output</div><div class="value output">${formatInteger(session.output)}</div></div>
          <div class="meta-card"><div class="label">${costLabel(session)}</div><div class="value cost">${formatCost(session.cost)}</div><div class="note small">${costProvenanceBadge(session)}</div></div>
          <div class="meta-card" title="1 AI credit = $0.01 of model usage."><div class="label">AI credits</div><div class="value cost">${formatCreditValue(session.cost)}</div></div>
          <div class="meta-card"><div class="label">Cache hit rate</div><div class="value cached">${formatPercent(session.input ? session.cached / session.input * 100 : 0)}</div></div>
          <div class="meta-card"><div class="label">Files touched</div><div class="value">${formatInteger((session.files || []).length)}</div></div>
          <div class="meta-card"><div class="label">Created</div><div class="value">${escapeHtml(formatTimestamp(session.createdAt))}</div></div>
          <div class="meta-card"><div class="label">Last activity</div><div class="value">${escapeHtml(formatTimestamp(session.lastActivity))}</div></div>
        </div>`;
  }
  function renderCliModelBreakdown(session) {
    const rows = session.modelBreakdown || [];
    if (!rows.length) return "";
    return `
        <div class="event-section" style="margin-bottom:14px">
          <h4>Per-model breakdown</h4>
          <table>
            <thead><tr><th>Model</th><th class="num">Calls</th><th class="num">Input</th><th class="num">Cached-read</th><th class="num">Cache-write</th><th class="num">Output</th><th class="num">Cost</th><th class="num">Credits</th></tr></thead>
            <tbody>
              ${rows.map((row) => `<tr>
                <td>${escapeHtml(row.model)}</td>
                <td class="num">${formatInteger(row.calls)}</td>
                <td class="num"><span class="value input">${formatInteger(row.input)}</span></td>
                <td class="num"><span class="value cached">${formatInteger(row.cached)}</span></td>
                <td class="num"><span class="value">${formatInteger(row.cacheWrite)}</span></td>
                <td class="num"><span class="value output">${formatInteger(row.output)}</span></td>
                <td class="num"><span class="value cost">${formatCost(row.cost)}</span> ${costProvenanceBadge(row)}</td>
                <td class="num"><span class="value cost">${formatCreditValue(row.cost)}</span></td>
              </tr>`).join("")}
            </tbody>
          </table>
        </div>`;
  }
  function renderCliSessionFiles(session) {
    const rows = session.files || [];
    if (!rows.length) return "";
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
              </tr>`).join("")}
            </tbody>
          </table>
        </div>`;
  }
  function renderCliTurn(turn) {
    const userText = turn.userMessage || "(empty)";
    const assistantText = turn.assistantResponse || "(empty)";
    return `
        <details class="event-card">
          <summary class="event-summary-row">
            <div class="title-col">
              <div class="title-line">
                <span class="badge user">turn ${formatInteger(turn.turnIndex)}</span>
                <span class="title-text">${escapeHtml((turn.userMessage || "").slice(0, 90) || "(no user message)")}</span>
              </div>
              <div class="subtext">${escapeHtml(formatTimestamp(turn.timestamp))}</div>
            </div>
          </summary>
          <div class="event-body">
            <div class="split-grid">
              <div class="event-section"><h4>User</h4><pre>${escapeHtml(userText)}${turn.userMessageTruncated ? "\n\u2026(truncated)" : ""}</pre></div>
              <div class="event-section"><h4>Assistant</h4><pre>${escapeHtml(assistantText)}${turn.assistantResponseTruncated ? "\n\u2026(truncated)" : ""}</pre></div>
            </div>
          </div>
        </details>`;
  }
  function setCliSearch(value) {
    STATE.cliSearch = value;
    STATE.cliPage = 1;
    renderApp();
  }
  function setCliModelFilter(value) {
    STATE.cliModel = value;
    STATE.cliPage = 1;
    renderApp();
  }
  function setCliFileSearch(value) {
    STATE.cliFileSearch = value;
    renderApp();
  }
  function setCliPageSize(value) {
    STATE.cliPageSize = Number(value || 10);
    STATE.cliPage = 1;
    renderApp();
  }
  function changeCliPage(delta) {
    STATE.cliPage = Math.max(1, (STATE.cliPage || 1) + delta);
    renderApp();
  }
  function openCliFullChatModal(sessionId) {
    const cli = APP_DATA.cli || {};
    const session = (cli.sessions || []).find((item) => item.id === sessionId);
    const backdrop = document.getElementById("fullChatModalBackdrop");
    document.getElementById("fullChatModalTitle").textContent = session ? session.repository || session.cwd || session.id : "Full chat";
    document.getElementById("fullChatModalSubtitle").textContent = session ? `${(session.models || []).join(", ") || "unknown"} \xB7 ${formatTimestamp(session.lastActivity)} \xB7 ${formatInteger(session.callCount)} calls \xB7 ${formatInteger(session.turnCount)} turns` : "";
    const exportBtn = document.getElementById("fullChatExportBtn");
    if (exportBtn) exportBtn.onclick = () => exportCliSessionToJson(sessionId);
    const body = document.getElementById("fullChatModalContent");
    if (!session) {
      body.innerHTML = '<div class="note" style="padding:24px;text-align:center;color:var(--red)">CLI session not found.</div>';
      backdrop.classList.add("open");
      return;
    }
    const turns = [...session.turns || []].sort((a, b) => Number(a.turnIndex || 0) - Number(b.turnIndex || 0));
    const timeline = turns.length ? turns.map((turn) => renderCliTurn(turn)).join("") : '<div class="note">No conversation turns were recorded for this session.</div>';
    body.innerHTML = `
        ${renderCliSessionMeta(session)}
        ${renderCliModelBreakdown(session)}
        <div class="timeline">${timeline}</div>`;
    backdrop.classList.add("open");
  }
  function exportCliSessionToJson(sessionId) {
    const cli = APP_DATA.cli || {};
    const session = (cli.sessions || []).find((item) => item.id === sessionId);
    if (!session) return;
    const safeName = (session.repository || session.cwd || session.id || "cli-chat").replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 40);
    const ts = (/* @__PURE__ */ new Date()).toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const blob = new Blob([JSON.stringify(session, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cli-chat-${safeName}-${ts}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  function deleteCliSessionPrompt(sessionId) {
    const session = ((APP_DATA.cli || {}).sessions || []).find((item) => item.id === sessionId);
    if (!session) return;
    const title = (session.repository || session.cwd || session.id || "this CLI session").slice(0, 90);
    if (!confirm(`Delete "${title}" from the CLI tab?`)) return;
    const changed = markCliSessionsHidden([sessionId]);
    if (changed) renderApp();
  }
  function openCliModelCompareModal(sessionId) {
    var _a;
    const session = ((APP_DATA.cli || {}).sessions || []).find((s) => s.id === sessionId);
    if (!session) return;
    const inputTokens = session.input || 0;
    const cachedTokens = session.cached || 0;
    const cacheWriteTokens = session.cacheWrite || 0;
    const outputTokens = session.output || 0;
    const actualModel = (session.models || [])[0] || "unknown";
    const actualCost = session.cost || 0;
    const actualProvenance = costProvenance(session);
    const titleText = session.repository || session.cwd || session.id;
    document.getElementById("modelCompareModalTitle").textContent = "Model cost comparison";
    document.getElementById("modelCompareModalSubtitle").textContent = titleText + " \xB7 " + formatInteger(inputTokens) + " input \xB7 " + formatInteger(outputTokens) + " output tokens (session total)";
    const rows = Object.entries(PRICING_TABLE).map(([model, pricing]) => ({
      model,
      cost: calcModelCost(inputTokens, cachedTokens, outputTokens, pricing, cacheWriteTokens),
      pricing
    })).sort((a, b) => a.cost - b.cost);
    const minCost = ((_a = rows[0]) == null ? void 0 : _a.cost) || 0;
    document.getElementById("modelCompareModalContent").innerHTML = `
        <div class="note small" style="margin-bottom:12px">Estimated cost if this session's total token usage (<strong>${formatInteger(inputTokens)}</strong> input, of which <strong>${formatInteger(cachedTokens)}</strong> cached reads and <strong>${formatInteger(cacheWriteTokens)}</strong> cache writes, plus <strong>${formatInteger(outputTokens)}</strong> output) was processed by each model. Assumes the same cache hit pattern.</div>
        <div class="note small" style="margin-bottom:12px">Every figure in the <strong>Est. Cost</strong> column is priced from the published rate table, so it carries that table's caveats \u2014 notably that the 10% auto-model-selection discount is not modelled. The <strong>vs actual</strong> column compares against ${escapeHtml(actualProvenance.exact ? "this session's billed cost, which is exact" : "this session's estimated cost, which is itself approximate")}, so read small differences with that in mind.</div>
        <div style="overflow-x:auto">
        <table>
          <thead><tr>
            <th>Model</th>
            <th class="num">Input $/M</th>
            <th class="num">Cached $/M</th>
            <th class="num" title="Writing a prompt into the provider cache. Models that do not price cache writes show $0.">Cache-write $/M</th>
            <th class="num">Output $/M</th>
            <th class="num">Est. Cost</th>
            <th class="num">vs actual</th>
          </tr></thead>
          <tbody>
            ${rows.map((row) => {
      const isActual = row.model === actualModel;
      const delta = row.cost - actualCost;
      const isCheapest = Math.abs(row.cost - minCost) < 1e-6;
      return `<tr style="${isActual ? "background:rgba(88,166,255,0.08);border-left:2px solid var(--blue)" : ""}">
                <td><strong style="${isCheapest ? "color:var(--green)" : ""}">${escapeHtml(row.model)}</strong>${isActual ? ' <span class="badge chat" style="font-size:0.65rem;padding:2px 6px">current</span>' : ""}${isCheapest ? ' <span class="badge mode-read" style="font-size:0.65rem;padding:2px 6px">cheapest</span>' : ""}</td>
                <td class="num">${formatCost(row.pricing.input)}</td>
                <td class="num">${formatCost(row.pricing.cached)}</td>
                <td class="num">${Number(row.pricing.cacheWrite || 0) ? formatCost(row.pricing.cacheWrite) : '<span class="note small">n/a</span>'}</td>
                <td class="num">${formatCost(row.pricing.output)}</td>
                <td class="num"><strong style="color:var(--teal)">${formatCost(row.cost)}</strong></td>
                <td class="num" style="color:${delta < -1e-4 ? "var(--green)" : delta > 1e-4 ? "var(--red)" : "var(--muted)"}">${isActual ? "\u2014" : (delta >= 0 ? "+" : "") + formatCost(Math.abs(delta))}</td>
              </tr>`;
    }).join("")}
          </tbody>
        </table>
        </div>`;
    document.getElementById("modelCompareModalBackdrop").classList.add("open");
  }
  Object.assign(window, {
    switchCliTrendGranularity,
    switchCliTrendMetric,
    copyCliSetupSnippet
  });

  // web/js/tab-overview.js
  function stateClass(status) {
    return `state-${status === "critical" ? "critical" : status === "warn" ? "warn" : "ok"}`;
  }
  function renderBudgetPanel() {
    var _a, _b;
    const budget = ((_a = APP_DATA.premium) == null ? void 0 : _a.budget) || {};
    const hasAllowance = budget.allowance !== null && budget.allowance !== void 0;
    const legacy = budget.legacyRequests || {};
    const rawPct = Number(budget.percentUsed || 0);
    const pct = Math.max(0, Math.min(100, rawPct));
    const gaugeState = stateClass(budget.status);
    const alerts = Array.isArray(budget.alerts) ? budget.alerts : [];
    const alertsHtml = alerts.length ? alerts.map((alert2) => `
            <div class="insight-card ${stateClass(alert2.severity)}">
              <div style="font-weight:700">${escapeHtml(alert2.title || "")}</div>
              <div class="note small">${escapeHtml(alert2.detail || "")}</div>
            </div>`).join("") : "";
    const creditUsd = Number((_b = budget.creditUsd) != null ? _b : CREDIT_USD);
    return `
        <div class="panel">
          <div class="section-title">AI credit budget <span class="note small" style="font-weight:400">\xB7 plan ${escapeHtml(String(budget.plan || "unknown"))}</span></div>
          <div class="section-subtitle small">1 credit = $${creditUsd.toFixed(2)} of model usage. Credits used = this calendar month's billed cost x 100, across both sources.</div>
          <!-- flex-start, not center: the gauge column is ~40px tall and the
               card grid beside it ~250px, so centring the gauge left a band of
               dead space above and below it once the row got narrow enough for
               the grid to wrap into several rows. -->
          <div style="display:flex;align-items:flex-start;gap:16px;flex-wrap:wrap;margin:10px 0">
            <div style="flex:1;min-width:220px">
              <div class="gauge ${gaugeState}${rawPct > 100 ? " is-over" : ""}"><div class="gauge-fill ${gaugeState}" style="width:${hasAllowance ? pct.toFixed(1) : 0}%"></div></div>
              <div class="note small" style="margin-top:8px">${hasAllowance ? `<strong>${formatPercent(rawPct)}</strong> of the monthly credit allowance used${rawPct > 100 ? " \u2014 allowance exceeded" : ""}` : "No credit allowance configured \u2014 usage tracked, not budget-compared"}</div>
            </div>
            <div class="summary-grid" style="flex:2;min-width:280px">
              <div class="summary-card"><div class="label">Allowance</div><div class="value">${hasAllowance ? formatInteger(budget.allowance) : "\u2014"}</div><div class="note small">credits / month</div></div>
              <div class="summary-card"><div class="label">Credits used</div><div class="value">${formatInteger(budget.used)}</div><div class="note small">${formatCost(budget.usedUsd || 0)}</div></div>
              <div class="summary-card"><div class="label">Remaining</div><div class="value">${budget.remaining !== null && budget.remaining !== void 0 ? formatInteger(budget.remaining) : "\u2014"}</div></div>
              <div class="summary-card"><div class="label">Burn rate / day</div><div class="value">${formatCompact(budget.burnRatePerDay || 0)}</div></div>
              <div class="summary-card"><div class="label">Projected total</div><div class="value">${formatCompact(budget.projectedMonthEnd || 0)}</div><div class="note small">by month end</div></div>
              <div class="summary-card"><div class="label">Projected %</div><div class="value">${hasAllowance ? formatPercent(budget.projectedPercent || 0) : "\u2014"}</div></div>
            </div>
          </div>
          ${alertsHtml ? `<div class="insights-grid">${alertsHtml}</div>` : ""}
          <div class="note small" style="margin-top:12px">Legacy premium requests this month: <strong>${formatInteger(legacy.used || 0)}</strong>${legacy.allowance ? ` of ${formatInteger(legacy.allowance)}` : ""} \u2014 counted per user prompt x model multiplier, and applicable only to annual Pro/Pro+ subscriptions still billed in requests. Not used for the gauge above.</div>
        </div>`;
  }
  function renderSourceSplitPanel() {
    const chat = unifiedFilteredBySourceKey("chat");
    const cli = unifiedFilteredBySourceKey("cli");
    const row = (label, source) => {
      var _a, _b;
      const block = pickTokenBlock(source.attributed, source.billed);
      return `
          <div class="summary-card">
            <div class="label">${escapeHtml(label)}</div>
            <div class="value cost">${formatCost(block.cost)}</div>
            <div class="note small">${formatInteger(source.sessionCount)} sessions \xB7 ${formatInteger(block.input + block.output)} tokens \xB7 ${formatInteger((_a = source.modelCalls) != null ? _a : source.callCount)} model calls \xB7 ${formatInteger((_b = source.promptCount) != null ? _b : source.callCount)} prompts</div>
          </div>`;
    };
    return `
        <div class="panel">
          <div class="section-title">Chat vs CLI split</div>
          <div class="summary-grid">
            ${row("Chat (VS Code)", chat)}
            ${row("CLI", cli)}
          </div>
        </div>`;
  }
  function renderTopRollup(title, rows, keyName, keyLabel, noteWhenEmpty) {
    const top = (rows || []).slice(0, 5);
    if (!top.length) {
      return `<div class="panel"><div class="section-title">${escapeHtml(title)}</div><div class="note is-empty">${escapeHtml(noteWhenEmpty)}</div></div>`;
    }
    const body = top.map((row) => {
      var _a;
      const block = pickTokenBlock(row.attributed, row.billed);
      return `<tr>
          <td data-label="${escapeHtml(keyLabel)}">${escapeHtml(String((_a = row[keyName]) != null ? _a : "unknown"))}</td>
          <td class="num" data-label="Cost">${formatCost(block.cost)}</td>
          <td class="num" data-label="Tokens">${formatInteger(block.input + block.output)}</td>
          <td class="num" data-label="Sessions">${formatInteger(row.sessionCount)}</td>
        </tr>`;
    }).join("");
    return `
        <div class="panel">
          <div class="section-title">${escapeHtml(title)}</div>
          <div class="note small">Across full history, all sources \u2014 not narrowed by the period/source filters above (these lists have no per-day breakdown server-side).</div>
          <div class="table-scroll">
            <table class="rollup-table table-collapse">
              <thead><tr><th>${escapeHtml(keyLabel)}</th><th class="num">Cost</th><th class="num">Tokens</th><th class="num">Sessions</th></tr></thead>
              <tbody>${body}</tbody>
            </table>
          </div>
        </div>`;
  }
  function severityRank(severity) {
    var _a;
    return (_a = { critical: 0, warn: 1, info: 2 }[severity]) != null ? _a : 3;
  }
  function severityStateClass(severity) {
    if (severity === "critical") return "state-critical";
    if (severity === "warn") return "state-warn";
    return "";
  }
  function renderTopInsights() {
    const scoped = filterInsightsBySource(APP_DATA.insights);
    const insights = scoped.visible.slice().sort((a, b) => severityRank(a.severity) - severityRank(b.severity)).slice(0, 3);
    if (!insights.length) {
      const filteredOut = (APP_DATA.insights || []).length > 0;
      const emptyNote = filteredOut ? `No recommendations for the ${escapeHtml(scoped.source === "cli" ? "CLI" : "Chat")} source \u2014 set the source filter to <strong>All</strong> to see every finding.` : "No recommendations yet \u2014 insights are computed from unified usage + premium-request data.";
      return `<div class="panel"><div class="section-title">Top recommendations</div><div class="note is-empty">${emptyNote}</div></div>`;
    }
    const cards = insights.map((insight) => `
        <div class="insight-card ${severityStateClass(insight.severity)}">
          <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline">
            <div style="font-weight:700">${escapeHtml(insight.title || "")}</div>
            <span class="badge">${escapeHtml(insight.severity || "info")}</span>
          </div>
          <div class="note small">${escapeHtml(insight.detail || "")}</div>
          ${insight.estimatedSavings ? `<div class="note small">Est. savings: ${formatCost(insight.estimatedSavings.cost || 0)} \xB7 ${formatCreditValue(insight.estimatedSavings.cost || 0)} AI credits</div>` : ""}
        </div>`).join("");
    return `
        <div class="panel">
          <div class="section-title">Top recommendations</div>
          <div class="insights-grid">${cards}</div>
          <div class="note small" style="margin-top:10px"><a href="#" onclick="openInsightsFromOverview(); return false;">View all insights in Analysis \u2192 Insights \u2192</a></div>
        </div>`;
  }
  function openInsightsFromOverview() {
    switchTab("analysis");
    switchAnalysisTab("insights");
  }
  function renderOverviewTab() {
    const unified = APP_DATA.unified || {};
    const dailyRows = unifiedFilteredDailyRows();
    const trendRows = dailyRows.length ? dailyRows : unified.monthly || [];
    const emptyNote = !dailyRows.length && !(unified.monthly || []).length ? '<div class="note is-empty">No usage data recorded yet for the selected filters.</div>' : "";
    return `
        ${renderBudgetPanel()}
        <div class="panel">
          <div class="section-title">Cost &amp; token trend (Chat vs CLI)</div>
          ${trendRows.length ? renderUnifiedTrendChart(trendRows, STATE.monthlyTrendMetric === "input" || STATE.monthlyTrendMetric === "output" ? "tokens" : "cost") : emptyNote}
        </div>
        ${renderSourceSplitPanel()}
        ${renderTopRollup("Top models", unified.byModel, "model", "Model", "No model usage recorded yet.")}
        ${renderTopRollup("Top repositories", unified.byRepo, "repository", "Repository", "No repository usage recorded yet.")}
        ${renderTopRollup(`Top ${APP_DATA.anonymized ? "developers (anonymized)" : "developers / hosts"}`, unified.byHost, "host", "Developer / host", "No host/developer usage recorded yet.")}
        ${renderTopInsights()}
        <div class="panel">
          <div class="note small">
            <strong>Estimate disclaimer:</strong> token pricing, AI-credit plan allowances, and legacy premium-request multipliers shown throughout this dashboard are local estimates maintained in this repo (see <code>model_pricing.py</code> / <code>premium_requests.py</code>), fully configurable, and are <strong>not</strong> official GitHub billing data. Costs exclude cache-write tokens, long-context pricing tiers, and the auto-model-selection discount, so they run low. For authoritative credit consumption and billing, see your GitHub account's Copilot billing/usage page.
          </div>
        </div>`;
  }

  // web/js/tab-reference.js
  function dataSubtabs() {
    const tabs = [
      ["prices", "Model prices"],
      ["toolCatalog", "Tool catalog"],
      ["tips", "Tips & Advice"],
      ["telemetry", "Telemetry"]
    ];
    return `<div class="analysis-subtabs">${tabs.map(([id, label]) => `<button type="button" class="subtab-button ${STATE.dataTab === id ? "active" : ""}" onclick="switchDataTab('${id}')">${escapeHtml(label)}</button>`).join("")}</div>`;
  }
  function renderModelPricesSubtab() {
    const rows = Object.entries(PRICING_TABLE).map(([name, pricing]) => ({ name, ...pricing })).sort((a, b) => {
      const totalA = Number(a.input || 0) + Number(a.cached || 0) + Number(a.output || 0);
      const totalB = Number(b.input || 0) + Number(b.cached || 0) + Number(b.output || 0);
      return totalA - totalB;
    });
    const longContextCell = (row) => {
      const tier = row.longContext;
      if (!tier) return '<span class="note small">single tier</span>';
      const threshold = Number(tier.threshold || 0);
      const parts = [
        `${formatCost(tier.input)} in`,
        `${formatCost(tier.cached)} cached`,
        tier.cacheWrite === void 0 ? null : `${formatCost(tier.cacheWrite)} cache-write`,
        `${formatCost(tier.output)} out`
      ].filter(Boolean);
      return `<span title="Above ${formatInteger(threshold)} prompt tokens the whole call bills at these rates instead.">&gt;${Math.round(threshold / 1e3)}K: ${parts.join(" / ")}</span>`;
    };
    return `
        <section class="panel">
          <h2 class="section-title">Model prices</h2>
          <div class="section-subtitle">Prices per 1M tokens, quoted from GitHub's official <a href="https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing" target="_blank" rel="noopener">models and pricing</a> page and configurable in <code>model_pricing.py</code>. Sorted cheapest first.</div>
          <div class="note small" style="margin-bottom:10px">
            <strong>This table is a fallback, not the primary cost source.</strong> Copilot CLI usage is priced from what GitHub actually charged each call (recorded in <code>~/.copilot/session-store.db</code>), so those figures are exact and already include promotional pricing, long-context tiers and the 10% auto-model-selection discount. This table prices the VS Code chat half of the data, where no billing figure is exposed, and backstops CLI rows recorded by an older CLI build. Two caveats apply to those fallback estimates: the 10% auto-model-selection discount is not modelled (nothing in either data source flags a call as auto-routed), and chat telemetry exposes no cache-write counter, so cache-heavy chat sessions read as a lower bound.
          </div>
          <div class="compact-prices-wrap">
            <table class="compact-prices-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Input $/M</th>
                  <th>Cached-read $/M</th>
                  <th title="Writing a prompt into the provider cache. Anthropic charges 1.25x input; models whose pricing row prints &quot;Not applicable&quot; are billed nothing, shown here as $0.">Cache-write $/M</th>
                  <th>Output $/M</th>
                  <th title="Above the listed prompt size, the entire call bills at the long-context rates instead of the default ones.">Long-context tier</th>
                </tr>
              </thead>
              <tbody>
                ${rows.map((row) => `<tr><td><strong>${escapeHtml(row.name)}</strong></td><td>${formatCost(row.input)}</td><td>${formatCost(row.cached)}</td><td>${Number(row.cacheWrite || 0) ? formatCost(row.cacheWrite) : '<span class="note small">n/a</span>'}</td><td>${formatCost(row.output)}</td><td>${longContextCell(row)}</td></tr>`).join("")}
              </tbody>
            </table>
          </div>
        </section>`;
  }
  function renderToolCatalogSubtab() {
    const analysis = analysisForMode();
    const allRows = [...analysis.toolCatalog || []];
    if (!allRows.length) {
      return `<section class="panel"><h2 class="section-title">Tool catalog</h2><div class="note">No tool definitions were captured in the scanned logs yet.</div></section>`;
    }
    const search = (STATE.toolCatalogSearch || "").trim().toLowerCase();
    const sortKey = STATE.toolCatalogSortKey || "descriptionTokens";
    const sortDir = STATE.toolCatalogSortDir || "desc";
    const rows = sortRows(allRows.filter((row) => {
      if (!search) return true;
      return String(row.name || "").toLowerCase().includes(search) || String(row.description || "").toLowerCase().includes(search);
    }), sortKey, sortDir);
    function arrow(key) {
      if ((STATE.toolCatalogSortKey || "descriptionTokens") !== key) return '<span style="opacity:.4">\u2195</span>';
      return (STATE.toolCatalogSortDir || "desc") === "desc" ? "\u2193" : "\u2191";
    }
    function th(key, label, numeric) {
      return `<th class="${numeric ? "num" : ""}"><button type="button" onclick="setToolCatalogSort('${key}')" style="all:unset;cursor:pointer;color:inherit;display:block;width:100%;text-align:${numeric ? "right" : "left"}">${label} ${arrow(key)}</button></th>`;
    }
    return `
        <section class="panel">
          <h2 class="section-title">Tool description token footprint</h2>
          <div class="section-subtitle">Find context-heavy tools quickly. <strong>Tool sets</strong> means the number of distinct tool-definition payloads in which a tool appeared. Click any column header to sort ascending/descending; expand a tool name to view the full captured description.</div>
          <div class="tool-catalog-controls">
            <input type="text" id="toolCatalogSearchInput" placeholder="Search by tool name or description\u2026" value="${escapeHtml(STATE.toolCatalogSearch)}" oninput="setToolCatalogSearch(this.value)">
          </div>
          <div class="note small" style="margin-bottom:10px">Showing ${formatInteger(rows.length)} of ${formatInteger(allRows.length)} tools.</div>
          <div style="overflow-x:auto">
          <table>
            <thead><tr>
              ${th("name", "Tool", false)}
              ${th("descriptionTokens", "Description tokens", true)}
              ${th("callCount", "Calls", true)}
              ${th("sessionCount", "Sessions", true)}
              ${th("toolSetCount", "Tool sets", true)}
              ${th("presentCount", "Present in calls", true)}
              ${th("wastePercent", "Waste %", true)}
            </tr></thead>
            <tbody>
              ${rows.length ? rows.map((row) => `<tr>
                <td><details><summary><strong>${escapeHtml(row.name)}</strong></summary><pre>${escapeHtml(row.description || "[No description captured for this tool in scanned tool-definition payloads.]")}</pre></details></td>
                <td class="num"><span class="value uncached">${formatInteger(row.descriptionTokens || 0)}</span></td>
                <td class="num">${formatInteger(row.callCount || 0)}</td>
                <td class="num">${formatInteger(row.sessionCount || 0)}</td>
                <td class="num">${formatInteger(row.toolSetCount || 0)}</td>
                <td class="num">${formatInteger(row.presentCount || 0)}</td>
                <td class="num">${formatPercent(row.wastePercent || 0)}</td>
              </tr>`).join("") : '<tr><td colspan="7"><div class="note">No tools matched your search.</div></td></tr>'}
            </tbody>
          </table>
          </div>
        </section>`;
  }
  function renderTipsSubtab() {
    const tips = [
      {
        icon: "\u{1F501}",
        title: "Don't switch models mid-chat",
        severity: "high",
        body: "Every time you switch models in a conversation, the context cache is invalidated. The next call must re-read the entire accumulated context as fresh (uncached) tokens. This can 3\u201310\xD7 the cost of that single turn. Start a new chat when you want to try a different model."
      },
      {
        icon: "\u2702\uFE0F",
        title: "Keep chats short",
        severity: "high",
        body: "Every new message in a chat is appended to an ever-growing context window. By turn 20, the model is re-reading the entire history on every call. Split long tasks into focused sub-chats, each under 10\u201315 turns. Your cache hit rate will be much higher and costs much lower."
      },
      {
        icon: "\u{1F527}",
        title: "Reduce active tools",
        severity: "medium",
        body: "Tool definitions are included in every single prompt sent to the model \u2014 even if no tools are called. With 30+ tools enabled, you may be spending thousands of tokens per call just on tool schema overhead. Disable tools or skills you do not need for the current task."
      },
      {
        icon: "\u{1F195}",
        title: "Start a new chat for each new topic",
        severity: "medium",
        body: "Continuing an existing chat for unrelated tasks forces the model to carry irrelevant context (previous files, messages, tool results). This inflates the prompt size and reduces cache effectiveness. A fresh chat starts with a minimal context and much better cache hit rates."
      },
      {
        icon: "\u{1F4BE}",
        title: "Let the cache warm up",
        severity: "medium",
        body: "Copilot uses prompt caching \u2014 identical leading content across consecutive turns is billed at a fraction of normal input cost. The longer you continue a focused conversation, the higher your cache hit rate becomes. Avoid making large edits to files mid-chat as this changes the prompt shape and busts the cache."
      },
      {
        icon: "\u{1F4C4}",
        title: "Be selective with context files",
        severity: "medium",
        body: "#file references and workspace context are included in every prompt turn. Attaching large files or entire directories significantly inflates your context window. Reference only the specific files relevant to the current task and remove them when no longer needed."
      },
      {
        icon: "\u{1F4DD}",
        title: "Keep system prompts lean",
        severity: "low",
        body: "Custom instructions and system prompts are prepended to every API call. A 2,000-token system prompt added to 600 chat calls costs you 1.2M extra input tokens. Audit your .github/copilot-instructions.md and VS Code custom instructions \u2014 keep them focused and concise."
      },
      {
        icon: "\u26A1",
        title: "Use cheaper models for simple tasks",
        severity: "low",
        body: "Not every task needs a frontier model. Simple code completions, renaming, or straightforward Q&A work just as well with faster, cheaper models (e.g. gpt-4o-mini, claude-haiku). Reserve expensive models for complex reasoning, architecture decisions, or tasks that genuinely need deep understanding."
      },
      {
        icon: "\u{1F50D}",
        title: "Monitor your cache hit rate",
        severity: "low",
        body: "A healthy cache hit rate is 85%+ \u2014 meaning most of your input tokens are billed at the cheap cached rate. If your cache hit rate drops below 70%, you are probably switching contexts too often, switching models, or having frequent context resets. Check the Analysis \u2192 Insights tab for patterns."
      },
      {
        icon: "\u{1F916}",
        title: "Avoid long agentic loops",
        severity: "low",
        body: "Autonomous agent tasks with many tool call loops (read_file, replace_string_in_file, run_in_terminal repeated 30+ times) accumulate massive context quickly. Break large agentic tasks into smaller, focused steps. If a subagent approach is available, use it \u2014 subagents start fresh contexts."
      }
    ];
    const severityColors = {
      high: "var(--red)",
      medium: "var(--yellow)",
      low: "var(--green)"
    };
    const severityLabels = { high: "High impact", medium: "Medium impact", low: "Low impact" };
    return `
        <div class="analysis-grid">
          <section class="panel">
            <h2 class="section-title">Tips & Advice \u2014 Reducing Token Usage and Costs</h2>
            <div class="section-subtitle">Based on analysis of common usage patterns. High-impact tips can reduce costs by 50\u201380%. The <span style="color:var(--red)">red</span> badges indicate the biggest wins.</div>
            <div class="insights-grid" style="grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))">
              ${tips.map((tip) => `
                <div class="insight-card" style="border-left:3px solid ${severityColors[tip.severity]}">
                  <h4 style="display:flex;align-items:center;gap:8px;white-space:normal">
                    <span style="font-size:1.4rem">${tip.icon}</span>
                    <span>${escapeHtml(tip.title)}</span>
                    <span style="margin-left:auto;font-size:0.7rem;font-weight:700;color:${severityColors[tip.severity]};white-space:nowrap">${severityLabels[tip.severity]}</span>
                  </h4>
                  <div class="note small" style="line-height:1.6">${escapeHtml(tip.body)}</div>
                </div>`).join("")}
            </div>
          </section>
        </div>`;
  }
  function renderTelemetrySubtab() {
    const telemetry = activeAnalysis().telemetry || { sections: [], observedFields: [], entryTypes: {} };
    return `
        <div class="analysis-grid">
          ${renderDiagnosticsPanel()}
          <section class="panel">
            <h2 class="section-title">Telemetry coverage</h2>
            <div class="section-subtitle">What the current Copilot debug / OTel data gives directly, and what the dashboard must estimate.</div>
            <div class="insights-grid">
              ${(telemetry.sections || []).map((section) => `<div class="insight-card"><h4>${escapeHtml(section.name)}</h4><ul class="help-list">${(section.items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`).join("")}
            </div>
          </section>
          <section class="panel">
            <h2 class="section-title">Observed attribute fields</h2>
            <pre>${escapeHtml(JSON.stringify(telemetry.observedFields, null, 2))}</pre>
          </section>
        </div>`;
  }
  function renderReferenceTab() {
    const tabBodies = {
      prices: renderModelPricesSubtab,
      toolCatalog: renderToolCatalogSubtab,
      tips: renderTipsSubtab,
      telemetry: renderTelemetrySubtab
    };
    if (!tabBodies[STATE.dataTab]) {
      STATE.dataTab = "prices";
    }
    return `<section class="panel">${dataSubtabs()}</section>${tabBodies[STATE.dataTab]()}`;
  }

  // web/js/app.js
  function toggleTheme() {
    applyTheme(STATE.theme === "light" ? "dark" : "light");
    renderApp();
  }
  function renderSummaryCards() {
    var _a, _b, _c;
    const totals = unifiedFilteredTotals();
    const block = pickTokenBlock(totals.attributed, totals.billed);
    const costLabel2 = isBilledMode() ? "Billed API cost" : "Attributed est. cost";
    const creditsLabel = isBilledMode() ? "Billed AI credits" : "Attributed AI credits";
    const budget = ((_a = APP_DATA.premium) == null ? void 0 : _a.budget) || {};
    const hasAllowance = budget.allowance !== null && budget.allowance !== void 0;
    const rawPct = hasAllowance ? Number(budget.percentUsed || 0) : 0;
    const quotaValue = hasAllowance ? formatPercent(rawPct) : "\u2014";
    const quotaNote = hasAllowance ? `of ${formatInteger(budget.allowance)} credits${rawPct > 100 ? " \xB7 over allowance" : ""}` : "no allowance set";
    const quotaValueClass = hasAllowance ? ` is-${budget.status === "critical" ? "critical" : budget.status === "warn" ? "warn" : "ok"}` : "";
    return `
        <div class="summary-groups">
          <div class="summary-group">
            <div class="summary-group-label">Usage</div>
            <div class="summary-grid">
              <div class="summary-card"><div class="label">Sessions</div><div class="value">${formatInteger(totals.sessionCount)}</div></div>
              <div class="summary-card" title="Model API calls. An agentic CLI session makes many calls per prompt, so this is much larger than the prompt count."><div class="label">Model calls</div><div class="value">${formatInteger((_b = totals.modelCalls) != null ? _b : totals.callCount)}</div></div>
              <div class="summary-card" title="User prompts submitted. This is what legacy premium-request billing counts, not model calls."><div class="label">Prompts</div><div class="value">${formatInteger((_c = totals.promptCount) != null ? _c : totals.callCount)}</div></div>
              <div class="summary-card" title="Total input tokens, including cached-read tokens."><div class="label">Input tokens</div><div class="value input">${formatInteger(block.input)}</div></div>
              <div class="summary-card" title="Input tokens billed at the full uncached rate."><div class="label">Uncached input</div><div class="value uncached">${formatInteger(block.uncached)}</div></div>
              <div class="summary-card" title="Input tokens served from the prompt cache, billed at the discounted cached rate."><div class="label">Cached-read input</div><div class="value cached">${formatInteger(block.cached)}</div></div>
              <div class="summary-card"><div class="label">Output tokens</div><div class="value output">${formatInteger(block.output)}</div></div>
            </div>
          </div>
          <div class="summary-group">
            <div class="summary-group-label">Cost &amp; AI credits</div>
            <div class="summary-grid">
              <div class="summary-card"><div class="label">${escapeHtml(costLabel2)}</div><div class="value cost">${formatCost(block.cost)}</div></div>
              <div class="summary-card" title="1 AI credit = $0.01 of model usage \u2014 the unit GitHub meters paid plans in."><div class="label">${escapeHtml(creditsLabel)}</div><div class="value credits">${formatCreditValue(block.cost)}</div></div>
              <div class="summary-card"><div class="label">Credit allowance used</div><div class="value${quotaValueClass}">${escapeHtml(quotaValue)}</div><div class="note small">${escapeHtml(quotaNote)}</div></div>
              <div class="summary-card" title="Legacy premium-request estimate (one per user prompt x model multiplier). Applies only to annual Pro/Pro+ plans still billed in requests."><div class="label">Premium requests (legacy)</div><div class="value">${formatInteger(totals.premiumRequests)}</div></div>
            </div>
          </div>
        </div>`;
  }
  function renderFilterBar() {
    const filters = currentFilters();
    const sourceOptions = [["all", "All"], ["chat", "Chat"], ["cli", "CLI"]];
    const periodOptions = [["today", "Today"], ["7d", "7 days"], ["30d", "30 days"], ["month", "This month"], ["all", "All time"], ["custom", "Custom"]];
    const sourceButtons = sourceOptions.map(([value, label]) => `<button type="button" class="subtab-button ${filters.source === value ? "active" : ""}" onclick="setFilter('source', '${value}')">${escapeHtml(label)}</button>`).join("");
    const periodButtons = periodOptions.map(([value, label]) => `<button type="button" class="subtab-button ${filters.period === value ? "active" : ""}" onclick="setFilter('period', '${value}')">${escapeHtml(label)}</button>`).join("");
    const startVal = filters.start ? new Date(filters.start).toISOString().slice(0, 10) : "";
    const endVal = filters.end ? new Date(filters.end).toISOString().slice(0, 10) : "";
    const customInputs = filters.period === "custom" ? `<span style="display:inline-flex;gap:6px;align-items:center;margin-left:8px">
             <input type="date" id="filterCustomStart" value="${escapeHtml(startVal)}" onchange="applyCustomDateInputs()">
             <span class="note small">to</span>
             <input type="date" id="filterCustomEnd" value="${escapeHtml(endVal)}" onchange="applyCustomDateInputs()">
           </span>` : "";
    return `
        <div id="filterBarSentinel" style="height:0"></div>
        <div class="filter-bar filter-bar-sticky" id="filterBarSticky">
          <div><span class="note small" style="margin-right:6px">Source</span><span class="segmented-control">${sourceButtons}</span></div>
          <div><span class="note small" style="margin-right:6px">Period</span><span class="segmented-control">${periodButtons}</span>${customInputs}</div>
          <div><span class="note small" style="margin-right:6px">Tokens</span><span class="segmented-control">
            <button type="button" class="subtab-button ${normalizeTokenMode(STATE.tokenMode) === "attributed" ? "active" : ""}" onclick="switchTokenMode('attributed')">Attributed</button>
            <button type="button" class="subtab-button ${normalizeTokenMode(STATE.tokenMode) === "billed" ? "active" : ""}" onclick="switchTokenMode('billed')">Billed</button>
          </span></div>
        </div>`;
  }
  function renderHeader() {
    const summary = activeSummary();
    const legacyTotals = summaryDisplayTotals(summary);
    const modeLabel = tokenModeLabel();
    const periodLabel = activePeriodLabel();
    const filters = currentFilters();
    const anonymizedBadge = APP_DATA.anonymized ? '<span class="badge" title="Host/user identifiers were replaced with dev-xxxx pseudonyms (--anonymize)">\u{1F576} anonymized</span>' : "";
    const themeIsLight = STATE.theme === "light";
    return `
        <section class="header">
          ${renderDiagnosticsBanner()}
          <div class="header-top">
            <div>
              <h1>\u{1F4CA} Copilot Usage Explorer ${anonymizedBadge}</h1>
              <div class="subtitle">Token, cost and AI-credit usage across VS Code Copilot Chat and the GitHub Copilot CLI, with cost-reduction recommendations.</div>
              <div class="subtitle small">Generated ${escapeHtml(APP_DATA.generatedAt)} \xB7 Tokens <strong>${escapeHtml(modeLabel)}</strong> \xB7 Chat cache hit <strong>${formatPercent(cacheHitRateForBlock(legacyTotals))}</strong> \xB7 <span title="A few chat-only panels (model usage, tool impact, telemetry) are precomputed per month server-side and stay scoped to this period rather than the global period filter above.">chat-only panels scoped to <strong>${escapeHtml(periodLabel)}</strong></span></div>
            </div>
            <div style="display:flex;gap:12px;flex-direction:column;align-items:flex-end;min-width:200px">
              <div style="display:flex;gap:8px">
                <button type="button" class="action-chip" onclick="toggleTheme()" title="Switch to ${themeIsLight ? "dark" : "light"} theme">${themeIsLight ? "\u{1F319} Dark" : "\u2600\uFE0F Light"}</button>
                <button type="button" class="action-chip action-chip--teal" onclick="exportToJson()">\u2B07 Export JSON</button>
              </div>
            </div>          </div>
          ${renderFilterBar()}
          <!-- Tabs sit above the summary cards, not below them: with eleven
               cards in between, the primary navigation started ~570px down
               the page and was pushed off the fold on smaller screens. The
               cards read as context for whichever tab is open, which is
               exactly where they now sit. -->
          <div class="tabs">
            <button class="tab-button ${STATE.activeTab === "overview" ? "active" : ""}" onclick="switchTab('overview')">Overview</button>
            ${filters.source !== "cli" ? `<button class="tab-button ${STATE.activeTab === "chats" ? "active" : ""}" onclick="switchTab('chats')">Chats</button>` : ""}
            <button class="tab-button ${STATE.activeTab === "analysis" ? "active" : ""}" onclick="switchTab('analysis')">Analysis</button>
            ${filters.source !== "chat" ? `<button class="tab-button ${STATE.activeTab === "cli" ? "active" : ""}" onclick="switchTab('cli')">CLI</button>` : ""}
            <button class="tab-button ${STATE.activeTab === "reference" ? "active" : ""}" onclick="switchTab('reference')">Info</button>
          </div>
          ${renderSummaryCards()}
        </section>`;
  }
  var REGIONS = [
    ["regionHeader", "header", renderHeader],
    ["regionOverview", "overview", renderOverviewTab],
    ["regionChats", "chats", renderChatsTab],
    ["regionAnalysis", "analysis", renderAnalysisTab],
    ["regionCli", "cli", renderCliTab],
    ["regionReference", "reference", renderReferenceTab]
  ];
  var _regionHtmlCache = /* @__PURE__ */ Object.create(null);
  var _stickyObserver = null;
  function ensureAppSkeleton(app) {
    if (app.dataset.skeletonReady === "1") return;
    app.innerHTML = REGIONS.map(([id, tab]) => tab === "header" ? `<div id="${id}"></div>` : `<section class="tab-panel" id="${id}"></section>`).join("");
    app.dataset.skeletonReady = "1";
  }
  function updateRegion(id, html) {
    if (_regionHtmlCache[id] === html) return false;
    _regionHtmlCache[id] = html;
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
    return true;
  }
  function initStickyObserver() {
    const sentinel = document.getElementById("filterBarSentinel");
    const bar = document.getElementById("filterBarSticky");
    if (!sentinel || !bar || typeof IntersectionObserver === "undefined") return;
    if (_stickyObserver) _stickyObserver.disconnect();
    _stickyObserver = new IntersectionObserver(([entry]) => {
      bar.classList.toggle("is-stuck", !entry.isIntersecting);
    }, { threshold: 0 });
    _stickyObserver.observe(sentinel);
  }
  function renderApp() {
    const app = document.getElementById("app");
    const pages = pagedSessions();
    if (STATE.page > pages.pageCount) STATE.page = pages.pageCount;
    ensureAppSkeleton(app);
    const focusState = captureInputFocusState();
    let headerChanged = false;
    REGIONS.forEach(([id, tab, renderFn]) => {
      var _a;
      const changed = updateRegion(id, renderFn());
      if (tab === "header") headerChanged = changed;
      else (_a = document.getElementById(id)) == null ? void 0 : _a.classList.toggle("active", STATE.activeTab === tab);
    });
    restoreInputFocusState(focusState);
    if (headerChanged) initStickyObserver();
    encodeHashFromState();
  }
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
    dismissDiagnosticsBanner,
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
    toggleTheme
  });
  decodeHashIntoState();
  renderApp();
})();
