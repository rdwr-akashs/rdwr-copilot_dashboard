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

    // Precision scales with magnitude. A fixed 4 decimals made aggregate
    // figures read as raw floats rather than money ("$100.3124"), while a
    // fixed 2 would collapse every per-call and per-1M-token price to
    // "$0.00". So: dollars-and-cents (grouped) at $1 and above, 4 decimals
    // below it where the fractions are the whole point.
    export function formatCost(value) {
      const n = Number(value || 0);
      if (Math.abs(n) >= 1) {
        return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      }
      return `$${n.toFixed(4)}`;
    }

    // GitHub meters paid Copilot plans in AI credits, where 1 credit = $0.01 of
    // model usage (premium_requests.CREDIT_USD server-side). Any credit figure
    // shown in the UI is a dollar cost x 100 — never a count of calls or
    // prompts — so the conversion lives in exactly one place.
    export const CREDIT_USD = 0.01;

    export function creditsFromCost(cost) {
      return Number(cost || 0) / CREDIT_USD;
    }

    // Credit counts run from fractions (a single cheap call) to five figures
    // (a month of agentic CLI use), so the same magnitude rule as money
    // applies: group thousands and drop the decimal once the tenths stop
    // carrying information ("10,031", not "10031.2").
    export function formatCreditValue(cost) {
      const credits = creditsFromCost(cost);
      if (Math.abs(credits) >= 1000) return Math.round(credits).toLocaleString();
      return credits.toFixed(1);
    }

    export function formatCredits(cost) {
      return `${formatCreditValue(cost)} credits`;
    }

    // -------------------------------------------------------------------
    // Cost provenance
    //
    // A CLI cost can come from three places, and the difference matters to
    // anyone using this to reason about real spend:
    //
    //   "billed"   `assistant_usage_events.total_nano_aiu` — the charge GitHub
    //              recorded for that call. Exact, by definition.
    //   "rates"    the per-token-type rates GitHub applied, from
    //              `token_details_json`. Exact: promotions, the auto-model
    //              -selection discount and long-context tiers are all already
    //              baked into those rates.
    //   "estimate" priced from this repo's published-rate table because neither
    //              of the above was recorded (an older CLI build, or VS Code
    //              chat data, which exposes no billing figure at all). Cannot
    //              see discounts or auto-routing, so it can be a few percent
    //              off in either direction.
    //
    // "mixed" means one bucket contains calls from more than one of those, so
    // it must not be labelled exact. Showing all four identically would be the
    // worst outcome: a developer checking their spend could not tell which
    // number is authoritative.
    // -------------------------------------------------------------------

    export const COST_SOURCE_INFO = {
      billed: {
        label: 'exact',
        badgeClass: 'confidence-high',
        title: "Exact: GitHub's own recorded charge for each call (total_nano_aiu), summed.",
      },
      rates: {
        label: 'exact',
        badgeClass: 'confidence-high',
        title: 'Exact: priced from the per-token rates GitHub actually applied to each call (token_details_json), which already include promotions, discounts and long-context tiers.',
      },
      mixed: {
        label: 'partly exact',
        badgeClass: 'confidence-medium',
        title: "Mixed: some calls carry GitHub's billed figure, others had to be estimated from published rates. Treat the total as approximate.",
      },
      estimate: {
        label: 'estimated',
        badgeClass: 'confidence-low',
        title: 'Estimated from the published pricing table — no billed figure was recorded for these calls, so promotions and the 10% auto-model-selection discount are not reflected.',
      },
    };

    export function costProvenance(row) {
      const source = String((row && row.costSource) || 'estimate');
      const info = COST_SOURCE_INFO[source] || COST_SOURCE_INFO.estimate;
      const exact = row && typeof row.costExact === 'boolean'
        ? row.costExact
        : (source === 'billed' || source === 'rates');
      const counts = (row && row.costSources) || {};
      const breakdown = Object.keys(counts)
        .map((key) => `${formatInteger(counts[key])} ${key}`)
        .join(', ');
      return {
        source,
        exact,
        label: info.label,
        badgeClass: info.badgeClass,
        title: breakdown ? `${info.title} (calls by source: ${breakdown})` : info.title,
      };
    }

    export function costProvenanceBadge(row) {
      const p = costProvenance(row);
      return `<span class="badge ${p.badgeClass}" title="${escapeHtml(p.title)}">${escapeHtml(p.label)}</span>`;
    }

    // "Billed cost" is only an honest label when the figure came from GitHub;
    // otherwise say "Estimated cost" and mean it.
    export function costLabel(row, noun = 'cost') {
      return costProvenance(row).exact ? `Billed ${noun}` : `Estimated ${noun}`;
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
    // Mirrors model_pricing.calculate_cost(). `inputTokens` is all-inclusive -
    // it already contains the cached reads and cache writes - so those are
    // carved out of it rather than charged on top, and cache writes bill at
    // their own (higher) rate where the model has one. Above a model's
    // long-context threshold the whole call bills at the tier rates instead.
    //
    // `cacheWriteTokens` defaults to 0 for the chat-side callers, whose
    // telemetry has no cache-write counter; the CLI passes its real value.
    export function calcModelCost(inputTokens, cachedTokens, outputTokens, pricing, cacheWriteTokens = 0) {
      const cacheWrite = Math.max(0, Number(cacheWriteTokens || 0));
      const cached = Math.max(0, Number(cachedTokens || 0));
      const uncached = Math.max(0, Number(inputTokens || 0) - cached - cacheWrite);
      const tier = pricing.longContext;
      const rates = tier && Number(inputTokens || 0) > Number(tier.threshold || 0)
        ? {
          input: tier.input,
          cached: tier.cached,
          // Absent on a long-context row means the model does not price cache
          // writes at all - keep the (zero) default rather than inventing one.
          cacheWrite: tier.cacheWrite === undefined ? (pricing.cacheWrite || 0) : tier.cacheWrite,
          output: tier.output,
        }
        : { input: pricing.input, cached: pricing.cached, cacheWrite: pricing.cacheWrite || 0, output: pricing.output };
      return (uncached / 1e6) * Number(rates.input || 0)
        + (cached / 1e6) * Number(rates.cached || 0)
        + (cacheWrite / 1e6) * Number(rates.cacheWrite || 0)
        + (Number(outputTokens || 0) / 1e6) * Number(rates.output || 0);
    }
