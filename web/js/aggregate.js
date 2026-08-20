import { addTokenBlock, cacheHitRateForBlock, cloneTokenBlock, currentMonthKey, formatCost, formatInteger, formatMonthLabelFromKey, formatPercent, monthKeyFromTimestamp, scaleTokenBlock, sessionOverheadForMode, sessionScaleFactors, tokenScaleFactors, zeroTokenBlock } from './format.js';
import { currentFilters, filterSessions, filterUnifiedRows } from './filters.js';
import { APP_DATA, STATE, isBilledMode, isCliSessionHidden, isSessionHidden } from './state.js';

    // --- Unified (chat+CLI) aggregation honouring STATE.filters --------------
    // Shared by the Overview tab (tab-overview.js) and the header summary
    // cards (app.js). See filters.js's top-of-file comment for the
    // STATE.filters contract these helpers read.

    function zeroUnifiedBucket() {
      return {
        attributed: zeroTokenBlock(),
        billed: zeroTokenBlock(),
        premiumRequests: 0,
        callCount: 0,
        sessionCount: 0,
      };
    }

    function addUnifiedBucket(target, src) {
      if (!src) return target;
      addTokenBlock(target.attributed, src.attributed);
      addTokenBlock(target.billed, src.billed);
      target.premiumRequests += Number(src.premiumRequests || 0);
      target.callCount += Number(src.callCount || 0);
      target.sessionCount += Number(src.sessionCount || 0);
      return target;
    }

    // Rows of APP_DATA.unified.daily narrowed to the active period filter
    // (source filtering is applied per-row via row.bySource[source] by the
    // callers below, since daily rows are pre-aggregated across sources).
    export function unifiedFilteredDailyRows() {
      return filterUnifiedRows(APP_DATA.unified?.daily || []);
    }

    export function unifiedFilteredTotals() {
      const unified = APP_DATA.unified || {};
      const filters = currentFilters();
      const dailyRows = filterUnifiedRows(unified.daily || []);
      const totals = zeroUnifiedBucket();

      const pickSource = (row) => (filters.source === 'all' ? row : (row.bySource || {})[filters.source]);

      if ((unified.daily || []).length) {
        dailyRows.forEach((row) => addUnifiedBucket(totals, pickSource(row)));
        return totals;
      }

      // No day-level granularity available (e.g. very small/synthetic
      // datasets) - only period 'all' can be answered from the flat totals;
      // anything narrower legitimately has no matching data.
      if (filters.period === 'all') {
        if (filters.source === 'all') {
          addUnifiedBucket(totals, unified.totals);
        } else {
          const row = (unified.bySource || []).find((r) => r.source === filters.source);
          addUnifiedBucket(totals, row);
        }
      }
      return totals;
    }

    export function unifiedFilteredBySourceKey(sourceKey) {
      const unified = APP_DATA.unified || {};
      const dailyRows = filterUnifiedRows(unified.daily || []);
      const totals = zeroUnifiedBucket();
      if ((unified.daily || []).length) {
        dailyRows.forEach((row) => addUnifiedBucket(totals, (row.bySource || {})[sourceKey]));
        return totals;
      }
      const row = (unified.bySource || []).find((r) => r.source === sourceKey);
      addUnifiedBucket(totals, row);
      return totals;
    }


    export function buildMonthlyBilledTrends(sessions) {
      const byMonth = new Map();
      (sessions || []).forEach((session) => {
        const key = monthKeyFromTimestamp(session?.timestamp);
        if (!key) return;
        if (!byMonth.has(key)) {
          byMonth.set(key, {
            monthKey: key,
            label: formatMonthLabelFromKey(key),
            sessionCount: 0,
            chatCallCount: 0,
            toolCallCount: 0,
            messageCount: 0,
            modelCount: 0,
            segmentCount: 0,
            modelSwitchCount: 0,
            contextResetCount: 0,
            totals: zeroTokenBlock(),
            peakPromptTokens: 0,
            modelNames: new Set(),
          });
        }
        const row = byMonth.get(key);
        const sessionTotals = cloneTokenBlock(session?.billed_totals || session?.totals || zeroTokenBlock());
        row.sessionCount += 1;
        row.chatCallCount += Number(session?.chat_count || 0);
        row.toolCallCount += Number(session?.tool_count || 0);
        row.messageCount += Number(session?.message_count || 0);
        row.segmentCount += Number(session?.segment_count || 0);
        row.modelSwitchCount += Number(session?.boundary_counts?.model_switch || 0);
        row.contextResetCount += Number(session?.boundary_counts?.context_reset || 0);
        row.peakPromptTokens = Math.max(row.peakPromptTokens, Number(session?.peak_prompt_tokens || 0));
        addTokenBlock(row.totals, sessionTotals);
        const names = Array.isArray(session?.model_names) && session.model_names.length
          ? session.model_names
          : [session?.model];
        names.filter(Boolean).forEach((name) => row.modelNames.add(String(name)));
      });

      return Array.from(byMonth.values())
        .sort((a, b) => String(a.monthKey).localeCompare(String(b.monthKey)))
        .map((row) => {
          const cacheHitRate = cacheHitRateForBlock(row.totals);
          return {
            monthKey: row.monthKey,
            label: row.label,
            sessionCount: row.sessionCount,
            chatCallCount: row.chatCallCount,
            toolCallCount: row.toolCallCount,
            messageCount: row.messageCount,
            modelCount: row.modelNames.size,
            segmentCount: row.segmentCount,
            modelSwitchCount: row.modelSwitchCount,
            contextResetCount: row.contextResetCount,
            totals: row.totals,
            cacheHitRate,
            aiCredits: Number(row.totals.cost || 0) / 0.01,
            peakPromptTokens: row.peakPromptTokens,
          };
        });
    }

    const BILLED_ANALYSIS_CACHE = {
      key: null,
      value: null,
    };

    export function buildTopChatsForMode(sessions, useBilledTokens) {
      const rows = [];
      (sessions || []).forEach((session) => {
        const sessionId = String(session?.id || '');
        const sessionTitle = String(session?.title || 'Untitled chat');
        (session?.events || []).forEach((event) => {
          if (event?.kind !== 'chat') return;
          const block = cloneTokenBlock(
            useBilledTokens
              ? (event?.billed_tokens || event?.attribution_tokens || zeroTokenBlock())
              : (event?.attribution_tokens || event?.billed_tokens || zeroTokenBlock())
          );
          rows.push({
            sessionId,
            sessionTitle,
            model: String(event?.model || 'unknown'),
            title: event?.title || 'chat',
            durationMs: Number(event?.duration_ms || 0),
            cost: Number(block.cost || 0),
            input: Number(block.input || 0),
            uncached: Number(block.uncached || 0),
            output: Number(block.output || 0),
            cached: Number(block.cached || 0),
            promptTokens: Number(event?.prompt_tokens || 0),
            timestamp: event?.ts,
          });
        });
      });
      return rows.sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0)).slice(0, 6);
    }

    export function buildBilledAnalysis(baseAnalysis, sessions) {
      const analysis = baseAnalysis || {};
      const modelMap = new Map();
      const toolMap = new Map();
      const fileMap = new Map();
      const overhead = zeroOverheadBuckets();
      const topChats = [];
      const slowestTools = [];

      (sessions || []).forEach((session) => {
        const sessionId = String(session?.id || '');
        const sessionTitle = String(session?.title || 'Untitled chat');
        const factors = sessionScaleFactors(session);

        Object.entries(sessionOverheadForMode(session) || {}).forEach(([key, block]) => {
          if (overhead[key]) addTokenBlock(overhead[key], block);
        });

        (session?.events || []).forEach((event) => {
          const kind = event?.kind;
          if (kind === 'chat') {
            const modelName = String(event?.model || 'unknown');
            if (!modelMap.has(modelName)) {
              modelMap.set(modelName, {
                name: modelName,
                count: 0,
                durationMs: 0,
                ttftMs: 0,
                totals: zeroTokenBlock(),
                sessionIds: new Set(),
              });
            }
            const bucket = modelMap.get(modelName);
            const billed = cloneTokenBlock(event?.billed_tokens || event?.attribution_tokens || zeroTokenBlock());
            bucket.count += 1;
            bucket.durationMs += Number(event?.duration_ms || 0);
            bucket.ttftMs += Number(event?.ttft_ms || 0);
            addTokenBlock(bucket.totals, billed);
            bucket.sessionIds.add(sessionId);

            topChats.push({
              sessionId,
              sessionTitle,
              model: modelName,
              title: event?.title || `chat ${modelName}`,
              durationMs: Number(event?.duration_ms || 0),
              cost: Number(billed.cost || 0),
              input: Number(billed.input || 0),
              uncached: Number(billed.uncached || 0),
              output: Number(billed.output || 0),
              cached: Number(billed.cached || 0),
              promptTokens: Number(event?.prompt_tokens || 0),
              timestamp: event?.ts,
            });
            return;
          }

          if (kind !== 'tool') return;

          const toolName = String(event?.name || 'unknown');
          const mode = String(event?.mode || 'other');
          const toolKey = `${toolName}::${mode}`;
          const billedEstimated = scaleTokenBlock(event?.estimated_tokens || zeroTokenBlock(), factors);
          const payloadTokens = Number(event?.payload_tokens_estimate || 0);

          if (!toolMap.has(toolKey)) {
            toolMap.set(toolKey, {
              name: toolName,
              mode,
              count: 0,
              errors: 0,
              durationMs: 0,
              payloadTokens: 0,
              totals: zeroTokenBlock(),
              sessionIds: new Set(),
            });
          }
          const toolBucket = toolMap.get(toolKey);
          toolBucket.count += 1;
          toolBucket.errors += event?.status === 'ok' ? 0 : 1;
          toolBucket.durationMs += Number(event?.duration_ms || 0);
          toolBucket.payloadTokens += payloadTokens;
          addTokenBlock(toolBucket.totals, billedEstimated);
          toolBucket.sessionIds.add(sessionId);

          slowestTools.push({
            sessionId,
            sessionTitle,
            name: toolName,
            title: event?.title || toolName,
            durationMs: Number(event?.duration_ms || 0),
            status: event?.status || 'unknown',
            estimated: billedEstimated,
            timestamp: event?.ts,
          });

          const filePaths = (event?.files || []).filter((path) => typeof path === 'string' && path);
          if (!filePaths.length) return;
          const fileShare = 1 / filePaths.length;

          filePaths.forEach((filePath) => {
            if (!fileMap.has(filePath)) {
              const parts = String(filePath).split('/').filter(Boolean);
              const name = parts[parts.length - 1] || String(filePath);
              fileMap.set(filePath, {
                path: filePath,
                shortPath: filePath,
                name,
                readCount: 0,
                editCount: 0,
                payloadTokens: 0,
                totals: zeroTokenBlock(),
                tools: new Set(),
                sessionIds: new Set(),
                  toolUsage: new Map(),
                  toolReferenceCount: 0,
              });
            }
            const fileBucket = fileMap.get(filePath);
            const eventShare = scaleTokenBlock(billedEstimated, { input: 1, uncached: 1, output: 1, cached: 1, cost: 1 }, fileShare);
            fileBucket.payloadTokens += payloadTokens * fileShare;
            fileBucket.tools.add(toolName);
            fileBucket.sessionIds.add(sessionId);
              fileBucket.toolReferenceCount += 1;
            if (mode === 'read') fileBucket.readCount += 1;
            if (mode === 'edit') fileBucket.editCount += 1;
            addTokenBlock(fileBucket.totals, eventShare);

              const usageKey = `${toolName}::${mode}`;
              if (!fileBucket.toolUsage.has(usageKey)) {
                fileBucket.toolUsage.set(usageKey, {
                  name: toolName,
                  mode,
                  count: 0,
                  durationMs: 0,
                  payloadTokens: 0,
                  totals: zeroTokenBlock(),
                  sessionIds: new Set(),
                });
              }
              const usageBucket = fileBucket.toolUsage.get(usageKey);
              usageBucket.count += 1;
              usageBucket.durationMs += Number(event?.duration_ms || 0);
              usageBucket.payloadTokens += payloadTokens * fileShare;
              addTokenBlock(usageBucket.totals, eventShare);
              usageBucket.sessionIds.add(sessionId);
          });
        });
      });

      const models = Array.from(modelMap.values()).map((bucket) => ({
        name: bucket.name,
        count: bucket.count,
        sessionCount: bucket.sessionIds.size,
        durationMs: bucket.durationMs,
        avgDurationMs: bucket.count ? bucket.durationMs / bucket.count : 0,
        avgTtftMs: bucket.count ? bucket.ttftMs / bucket.count : 0,
        input: bucket.totals.input,
        uncached: bucket.totals.uncached,
        output: bucket.totals.output,
        cached: bucket.totals.cached,
        cost: bucket.totals.cost,
        cacheHitRate: cacheHitRateForBlock(bucket.totals),
      })).sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0));

      const tools = Array.from(toolMap.values()).map((bucket) => ({
        name: bucket.name,
        mode: bucket.mode,
        count: bucket.count,
        sessionCount: bucket.sessionIds.size,
        errors: bucket.errors,
        durationMs: bucket.durationMs,
        avgDurationMs: bucket.count ? bucket.durationMs / bucket.count : 0,
        payloadTokens: bucket.payloadTokens,
        avgPayloadTokens: bucket.count ? bucket.payloadTokens / bucket.count : 0,
        input: bucket.totals.input,
        uncached: bucket.totals.uncached,
        output: bucket.totals.output,
        cached: bucket.totals.cached,
        cost: bucket.totals.cost,
        avgInput: bucket.count ? bucket.totals.input / bucket.count : 0,
        avgOutput: bucket.count ? bucket.totals.output / bucket.count : 0,
        avgCached: bucket.count ? bucket.totals.cached / bucket.count : 0,
        avgCost: bucket.count ? bucket.totals.cost / bucket.count : 0,
      }));

      const files = Array.from(fileMap.values()).map((bucket) => {
        const ops = bucket.readCount + bucket.editCount;
        const toolUsage = Array.from(bucket.toolUsage.values()).map((usage) => ({
          name: usage.name,
          mode: usage.mode,
          count: usage.count,
          sessionCount: usage.sessionIds.size,
          durationMs: usage.durationMs,
          avgDurationMs: usage.count ? usage.durationMs / usage.count : 0,
          payloadTokens: usage.payloadTokens,
          avgPayloadTokens: usage.count ? usage.payloadTokens / usage.count : 0,
          input: usage.totals.input,
          uncached: usage.totals.uncached,
          output: usage.totals.output,
          cached: usage.totals.cached,
          cost: usage.totals.cost,
          avgInput: usage.count ? usage.totals.input / usage.count : 0,
          avgOutput: usage.count ? usage.totals.output / usage.count : 0,
          avgCached: usage.count ? usage.totals.cached / usage.count : 0,
          avgCost: usage.count ? usage.totals.cost / usage.count : 0,
        })).sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0) || Number(b.count || 0) - Number(a.count || 0));
        return {
          path: bucket.path,
          shortPath: bucket.shortPath,
          name: bucket.name,
          readCount: bucket.readCount,
          editCount: bucket.editCount,
          sessionCount: bucket.sessionIds.size,
          payloadTokens: bucket.payloadTokens,
          avgInput: ops ? bucket.totals.input / ops : 0,
          avgOutput: ops ? bucket.totals.output / ops : 0,
          avgCached: ops ? bucket.totals.cached / ops : 0,
          avgCost: ops ? bucket.totals.cost / ops : 0,
          input: bucket.totals.input,
          uncached: bucket.totals.uncached,
          output: bucket.totals.output,
          cached: bucket.totals.cached,
          cost: bucket.totals.cost,
          tools: Array.from(bucket.tools).sort(),
          toolUsage,
          toolReferenceCount: bucket.toolReferenceCount,
        };
      });

      const baseSummary = activeSummary();
      const wasteFactors = tokenScaleFactors(baseSummary?.totals, baseSummary?.billedTotals || baseSummary?.totals);
      const toolCatalog = (analysis.toolCatalog || []).map((row) => ({
        ...row,
        wastedInputTokens: Number(row.wastedInputTokens || 0) * Number(wasteFactors.input || 0),
        wastedUncachedTokens: Number(row.wastedUncachedTokens || 0) * Number(wasteFactors.uncached || 0),
        wastedCachedTokens: Number(row.wastedCachedTokens || 0) * Number(wasteFactors.cached || 0),
      }));

      const monthlyTrends = buildMonthlyBilledTrends(sessions);

      return {
        ...analysis,
        models,
        tools,
        files,
        overhead,
        topChats: topChats.sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0)).slice(0, 6),
        slowestTools: slowestTools.sort((a, b) => Number(b.durationMs || 0) - Number(a.durationMs || 0)).slice(0, 6),
        toolCatalog,
        monthlyTrends,
      };
    }

    export function analysisForMode() {
      // Attributed and billed analyses are both pre-computed server-side, so the
      // mode toggle is a pure selection — no client-side recomputation needed.
      const bundle = activePeriodBundle();
      if (isBilledMode()) {
        return bundle.analysisBilled || bundle.analysis || APP_DATA.analysis || {};
      }
      return bundle.analysis || APP_DATA.analysis || {};
    }

    export function zeroOverheadBuckets() {
      return {
        system_prompt: zeroTokenBlock(),
        tool_definitions: zeroTokenBlock(),
        assistant_context: zeroTokenBlock(),
        user_messages: zeroTokenBlock(),
        tools: zeroTokenBlock(),
        files: zeroTokenBlock(),
        unattributed: zeroTokenBlock(),
      };
    }

    export function emptyMonthlyBundle(monthKey) {
      const fallbackAnalysis = APP_DATA?.periods?.allTime?.analysis || APP_DATA.analysis || {};
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
          peakPromptTokens: 0,
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
          monthlyTrends: fallbackAnalysis.monthlyTrends || [],
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
          monthlyTrends: fallbackAnalysis.monthlyTrends || [],
        },
        sessionIds: [],
      };
    }

    export function activePeriodBundle() {
      const periods = APP_DATA.periods || {};
      if (STATE.usagePeriod === 'allTime') {
        return periods.allTime || {
          summary: APP_DATA.summary || {},
          analysis: APP_DATA.analysis || {},
          sessionIds: (APP_DATA.sessions || []).map((session) => session.id),
        };
      }

      const monthly = periods.monthly;
      const monthKey = currentMonthKey();
      if (monthly && monthly.monthKey === monthKey) {
        return monthly;
      }
      return emptyMonthlyBundle(monthKey);
    }

    export function activeSummary() {
      return activePeriodBundle().summary || APP_DATA.summary || {};
    }

    export function activeAnalysis() {
      return activePeriodBundle().analysis || APP_DATA.analysis || {};
    }

    export function activePeriodLabel() {
      if (STATE.usagePeriod === 'allTime') {
        return (APP_DATA.periods?.labels?.allTime) || 'All time';
      }
      const bundle = activePeriodBundle();
      if (bundle?.label) return bundle.label;
      return formatMonthLabelFromKey(currentMonthKey());
    }

    export function sessionsForActivePeriod() {
      const bundle = activePeriodBundle();
      if (!Array.isArray(bundle?.sessionIds)) {
        return APP_DATA.sessions || [];
      }
      const allowed = new Set(bundle.sessionIds);
      return (APP_DATA.sessions || []).filter((session) => allowed.has(session.id));
    }

    export function visibleSessions() {
      return sessionsForActivePeriod().filter((session) => !isSessionHidden(session.id));
    }

    export function visibleCliSessions() {
      return ((APP_DATA.cli || {}).sessions || []).filter((session) => !isCliSessionHidden(session.id));
    }

    export function filteredSessions() {
      return filterSessions(visibleSessions(), 'chat').filter((session) => {
        const title = (session.title || '').toLowerCase();
        const models = (session.model_names?.length ? session.model_names : [session.model]).filter(Boolean).map((name) => String(name).toLowerCase());
        const sessionId = String(session.session_id || session.id || '').toLowerCase();
        const sourceIp = String(session.source_ip || '').toLowerCase();
        const search = STATE.search.toLowerCase();
        const searchMatch = !search || title.includes(search) || sessionId.includes(search) || sourceIp.includes(search) || models.some((name) => name.includes(search));
        const modelMatch = !STATE.model || models.includes(STATE.model.toLowerCase());
        return searchMatch && modelMatch;
      });
    }

    export function pagedSessions() {
      const sessions = filteredSessions();
      const start = (STATE.page - 1) * STATE.pageSize;
      return {
        all: sessions,
        slice: sessions.slice(start, start + STATE.pageSize),
        pageCount: Math.max(1, Math.ceil(sessions.length / STATE.pageSize)),
      };
    }

    export function monthlyTrendMetricConfig() {
      return {
        cost: {
          label: 'Cost',
          short: 'Cost',
          color: 'var(--teal)',
          value: (row) => Number(row?.totals?.cost || 0),
          format: (value) => formatCost(value),
        },
        input: {
          label: 'Input tokens',
          short: 'Input',
          color: 'var(--blue)',
          value: (row) => Number(row?.totals?.input || 0),
          format: (value) => formatInteger(value),
        },
        uncached: {
          label: 'Uncached input',
          short: 'Uncached',
          color: 'var(--yellow)',
          value: (row) => Number(row?.totals?.uncached || 0),
          format: (value) => formatInteger(value),
        },
        cached: {
          label: 'Cached input',
          short: 'Cached',
          color: 'var(--green)',
          value: (row) => Number(row?.totals?.cached || 0),
          format: (value) => formatInteger(value),
        },
        output: {
          label: 'Output tokens',
          short: 'Output',
          color: 'var(--orange)',
          value: (row) => Number(row?.totals?.output || 0),
          format: (value) => formatInteger(value),
        },
        sessions: {
          label: 'Sessions',
          short: 'Sessions',
          color: 'var(--purple)',
          value: (row) => Number(row?.sessionCount || 0),
          format: (value) => formatInteger(value),
        },
        chatCalls: {
          label: 'Chat calls',
          short: 'Chat calls',
          color: 'var(--blue)',
          value: (row) => Number(row?.chatCallCount || 0),
          format: (value) => formatInteger(value),
        },
        toolCalls: {
          label: 'Tool calls',
          short: 'Tool calls',
          color: 'var(--yellow)',
          value: (row) => Number(row?.toolCallCount || 0),
          format: (value) => formatInteger(value),
        },
        cacheHitRate: {
          label: 'Cache hit rate',
          short: 'Cache hit %',
          color: 'var(--green)',
          value: (row) => Number(row?.cacheHitRate || 0),
          format: (value) => formatPercent(value),
          isRate: true,
        },
      };
    }

    export function cliMonthlyBuckets() {
      const cli = APP_DATA.cli || {};
      const map = {};
      (cli.sessions || []).forEach((session) => {
        const ts = session.lastActivity || session.updatedAt || session.createdAt;
        if (!ts) return;
        const d = new Date(ts);
        const monthKey = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        const bucket = map[monthKey] || (map[monthKey] = { sessionCount: 0, cost: 0 });
        bucket.sessionCount += 1;
        bucket.cost += Number(session.cost || 0);
      });
      return map;
    }

    export function visibleSessionsSortedByTimestamp() {
      return visibleSessions().slice().sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0));
    }

    export function visibleCliSessionsSortedByTimestamp() {
      return visibleCliSessions().slice().sort((a, b) => Number(b.lastActivity || 0) - Number(a.lastActivity || 0));
    }

    export function computeChatDeletionTargets() {
      const isCli = STATE.deleteTarget === 'cli';
      const sessions = isCli ? visibleCliSessionsSortedByTimestamp() : visibleSessionsSortedByTimestamp();
      const timestampOf = (session) => Number((isCli ? session.lastActivity : session.timestamp) || 0);
      const mode = STATE.deleteMode || 'all';
      if (!sessions.length) return [];

      if (mode === 'all') {
        return sessions.map((session) => session.id);
      }

      if (mode === 'keep_last') {
        const keepCount = Math.max(1, Number(STATE.deleteKeepCount || 10));
        return sessions.slice(keepCount).map((session) => session.id);
      }

      if (mode === 'before_date') {
        let cutoffMs = 0;
        if (STATE.deleteAgePreset === 'day') {
          cutoffMs = Date.now() - 24 * 60 * 60 * 1000;
        } else if (STATE.deleteAgePreset === 'week') {
          cutoffMs = Date.now() - 7 * 24 * 60 * 60 * 1000;
        } else if (STATE.deleteAgePreset === 'month') {
          cutoffMs = Date.now() - 30 * 24 * 60 * 60 * 1000;
        } else {
          if (!STATE.deleteCustomDate) return [];
          cutoffMs = new Date(`${STATE.deleteCustomDate}T00:00:00`).getTime();
          if (!Number.isFinite(cutoffMs)) return [];
        }
        return sessions.filter((session) => timestampOf(session) < cutoffMs).map((session) => session.id);
      }

      return [];
    }
