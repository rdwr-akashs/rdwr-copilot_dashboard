import { zeroOverheadBuckets } from './aggregate.js';
import { STATE, isBilledMode } from './state.js';


    export function currentMonthKey() {
      const now = new Date();
      const year = now.getFullYear();
      const month = String(now.getMonth() + 1).padStart(2, '0');
      return `${year}-${month}`;
    }

    export function formatMonthLabelFromKey(monthKey) {
      if (!monthKey || !/^\d{4}-\d{2}$/.test(String(monthKey))) {
        return 'Current month';
      }
      const date = new Date(`${monthKey}-01T12:00:00`);
      if (!Number.isFinite(date.getTime())) {
        return String(monthKey);
      }
      return date.toLocaleString(undefined, { month: 'long', year: 'numeric' });
    }

    export function zeroTokenBlock() {
      return { input: 0, uncached: 0, output: 0, cached: 0, cost: 0 };
    }

    export function addTokenBlock(target, block, factor = 1) {
      if (!target || !block) return target;
      target.input += Number(block.input || 0) * factor;
      target.uncached += Number(block.uncached || 0) * factor;
      target.output += Number(block.output || 0) * factor;
      target.cached += Number(block.cached || 0) * factor;
      target.cost += Number(block.cost || 0) * factor;
      return target;
    }

    export function cloneTokenBlock(block) {
      const src = block || {};
      return {
        input: Number(src.input || 0),
        uncached: Number(src.uncached || 0),
        output: Number(src.output || 0),
        cached: Number(src.cached || 0),
        cost: Number(src.cost || 0),
      };
    }

    export function pickTokenBlock(attributedBlock, billedBlock) {
      if (isBilledMode()) {
        return cloneTokenBlock(billedBlock || attributedBlock || zeroTokenBlock());
      }
      return cloneTokenBlock(attributedBlock || billedBlock || zeroTokenBlock());
    }

    export function summaryDisplayTotals(summary) {
      return pickTokenBlock(summary?.totals, summary?.billedTotals);
    }

    export function sessionDisplayTotals(session) {
      return pickTokenBlock(session?.totals, session?.billed_totals);
    }

    export function eventDisplayChatTokens(event) {
      return pickTokenBlock(event?.attribution_tokens, event?.billed_tokens);
    }

    export function cacheHitRateForBlock(block) {
      const input = Number(block?.input || 0);
      if (!input) return 0;
      return (Number(block?.cached || 0) / input) * 100;
    }

    export function tokenScale(base, target) {
      const from = Number(base || 0);
      const to = Number(target || 0);
      if (from > 0) return to / from;
      if (to > 0) return 1;
      return 0;
    }

    export function tokenScaleFactors(attributedBlock, billedBlock) {
      const source = attributedBlock || zeroTokenBlock();
      const target = billedBlock || source;
      return {
        input: tokenScale(source.input, target.input),
        uncached: tokenScale(source.uncached, target.uncached),
        output: tokenScale(source.output, target.output),
        cached: tokenScale(source.cached, target.cached),
        cost: tokenScale(source.cost, target.cost),
      };
    }

    export function scaleTokenBlock(block, factors, factor = 1) {
      const src = block || zeroTokenBlock();
      const scale = factors || { input: 1, uncached: 1, output: 1, cached: 1, cost: 1 };
      return {
        input: Number(src.input || 0) * Number(scale.input || 0) * factor,
        uncached: Number(src.uncached || 0) * Number(scale.uncached || 0) * factor,
        output: Number(src.output || 0) * Number(scale.output || 0) * factor,
        cached: Number(src.cached || 0) * Number(scale.cached || 0) * factor,
        cost: Number(src.cost || 0) * Number(scale.cost || 0) * factor,
      };
    }

    export function sessionScaleFactors(session) {
      return tokenScaleFactors(session?.totals, session?.billed_totals || session?.totals);
    }

    export function eventDisplayEstimatedTokens(event, session) {
      const estimated = cloneTokenBlock(event?.estimated_tokens || zeroTokenBlock());
      if (!isBilledMode()) return estimated;
      return scaleTokenBlock(estimated, sessionScaleFactors(session));
    }

    export function sessionOverheadForMode(session) {
      const overhead = session?.overhead || {};
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

    export function monthKeyFromTimestamp(ts) {
      if (!ts && ts !== 0) return null;
      const parsed = new Date(Number(ts));
      if (!Number.isFinite(parsed.getTime())) return null;
      const month = String(parsed.getMonth() + 1).padStart(2, '0');
      return `${parsed.getFullYear()}-${month}`;
    }

    export function escapeHtml(value) {
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    export function formatInteger(value) {
      return Math.round(Number(value || 0)).toLocaleString();
    }

    export function formatCompact(value) {
      const n = Number(value || 0);
      if (Math.abs(n) >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
      if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}K`;
      return Math.round(n).toString();
    }

    export function formatCost(value) {
      return `$${Number(value || 0).toFixed(4)}`;
    }

    // GitHub meters paid Copilot plans in AI credits, where 1 credit = $0.01 of
    // model usage (premium_requests.CREDIT_USD server-side). Any credit figure
    // shown in the UI is a dollar cost x 100 — never a count of calls or
    // prompts — so the conversion lives in exactly one place.
    export const CREDIT_USD = 0.01;

    export function creditsFromCost(cost) {
      return Number(cost || 0) / CREDIT_USD;
    }

    export function formatCredits(cost) {
      return `${creditsFromCost(cost).toFixed(1)} credits`;
    }

    export function formatDuration(ms) {
      const value = Number(ms || 0);
      if (!value) return '—';
      if (value < 1000) return `${value.toFixed(0)}ms`;
      return `${(value / 1000).toFixed(2)}s`;
    }

    export function formatTimestamp(ts) {
      if (!ts) return '—';
      return new Date(Number(ts)).toLocaleString();
    }

    export function formatPercent(value) {
      return `${Number(value || 0).toFixed(1)}%`;
    }

    export function formatSigned(value) {
      const n = Number(value || 0);
      const prefix = n > 0 ? '+' : '';
      return `${prefix}${Math.round(n).toLocaleString()}`;
    }

    export function sortArrow(key) {
      if (STATE.fileSortKey !== key) return '↕';
      return STATE.fileSortDir === 'desc' ? '↓' : '↑';
    }

    export function promptWindowLabel(breakdown) {
      if (!breakdown) return '—';
      if (breakdown.max_context_window_tokens) {
        return `${formatCompact(breakdown.prompt_tokens)} / ${formatCompact(breakdown.max_context_window_tokens)} (${formatPercent(breakdown.used_percent_of_window)})`;
      }
      return formatCompact(breakdown.prompt_tokens);
    }

    export function boundaryLabel(reason) {
      const labels = {
        model_switch: 'model switch',
        context_reset: 'context reset',
        cache_reset: 'cache reset',
      };
      return labels[reason] || String(reason || '').replace(/_/g, ' ');
    }

    export function overheadLabel(key) {
      const labels = {
        system_prompt: 'System Instructions',
        tool_definitions: 'Tool Definitions',
        assistant_context: 'Chat History',
        user_messages: 'User Messages',
        tools: 'Tools',
        files: 'Files',
        unattributed: 'Unattributed',
      };
      return labels[key] || String(key || '').replace(/_/g, ' ');
    }

    export function overheadColor(key) {
      const colors = {
        system_prompt: 'var(--blue)',
        tool_definitions: 'var(--purple)',
        assistant_context: 'var(--orange)',
        user_messages: 'var(--green)',
        tools: 'var(--yellow)',
        files: 'var(--teal)',
        unattributed: 'var(--faint)',
      };
      return colors[key] || 'var(--faint)';
    }

    export function buildOverheadBreakdown(overhead, totalInput) {
      const keys = ['system_prompt', 'tool_definitions', 'assistant_context', 'user_messages', 'tools', 'files', 'unattributed'];
      const rows = keys.map((key) => ({
        key,
        label: overheadLabel(key),
        color: overheadColor(key),
        input: Number(overhead?.[key]?.input || 0),
        cost: Number(overhead?.[key]?.cost || 0),
      }));

      const normalizedTotal = Number(totalInput || 0);
      const assigned = rows.reduce((sum, row) => sum + row.input, 0);
      if (normalizedTotal > assigned) {
        const unattributed = rows.find((row) => row.key === 'unattributed');
        if (unattributed) {
          unattributed.input += (normalizedTotal - assigned);
        }
      }

      return rows.map((row) => ({
        ...row,
        pct: normalizedTotal ? (row.input / normalizedTotal) * 100 : 0,
      }));
    }
    export function calcModelCost(inputTokens, cachedTokens, outputTokens, pricing) {
      const uncached = Math.max(0, inputTokens - cachedTokens);
      return (uncached / 1e6) * pricing.input + (cachedTokens / 1e6) * pricing.cached + (outputTokens / 1e6) * pricing.output;
    }
