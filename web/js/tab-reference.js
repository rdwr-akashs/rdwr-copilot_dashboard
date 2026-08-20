import { setToolCatalogSearch, setToolCatalogSort, switchDataTab } from './actions.js';
import { activeAnalysis, analysisForMode } from './aggregate.js';
import { escapeHtml, formatCost, formatInteger, formatPercent } from './format.js';
import { PRICING_TABLE, STATE } from './state.js';
import { sortRows } from './tables.js';


    export function dataSubtabs() {
      const tabs = [
        ['prices', 'Model prices'],
        ['toolCatalog', 'Tool catalog'],
        ['tips', 'Tips & Advice'],
        ['telemetry', 'Telemetry'],
      ];
      return `<div class="analysis-subtabs">${tabs.map(([id, label]) => `<button type="button" class="subtab-button ${STATE.dataTab === id ? 'active' : ''}" onclick="switchDataTab('${id}')">${escapeHtml(label)}</button>`).join('')}</div>`;
    }

    export function renderModelPricesSubtab() {
      const rows = Object.entries(PRICING_TABLE)
        .map(([name, pricing]) => ({ name, ...pricing }))
        .sort((a, b) => {
          const totalA = Number(a.input || 0) + Number(a.cached || 0) + Number(a.output || 0);
          const totalB = Number(b.input || 0) + Number(b.cached || 0) + Number(b.output || 0);
          return totalA - totalB;
        });

      return `
        <section class="panel">
          <h2 class="section-title">Model prices</h2>
          <div class="section-subtitle">Info: API-style prices per 1M tokens used by cost estimation in this dashboard.</div>
          <div class="compact-prices-wrap">
            <table class="compact-prices-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Input $/M</th>
                  <th>Cached-read $/M</th>
                  <th>Output $/M</th>
                </tr>
              </thead>
              <tbody>
                ${rows.map((row) => `<tr><td><strong>${escapeHtml(row.name)}</strong></td><td>${formatCost(row.input)}</td><td>${formatCost(row.cached)}</td><td>${formatCost(row.output)}</td></tr>`).join('')}
              </tbody>
            </table>
          </div>
        </section>`;
    }

    export function renderToolCatalogSubtab() {
      const analysis = analysisForMode();
      const allRows = [...(analysis.toolCatalog || [])];
      if (!allRows.length) {
        return `<section class="panel"><h2 class="section-title">Tool catalog</h2><div class="note">No tool definitions were captured in the scanned logs yet.</div></section>`;
      }

      const search = (STATE.toolCatalogSearch || '').trim().toLowerCase();
      const sortKey = STATE.toolCatalogSortKey || 'descriptionTokens';
      const sortDir = STATE.toolCatalogSortDir || 'desc';

      const rows = sortRows(allRows
        .filter((row) => {
          if (!search) return true;
          return String(row.name || '').toLowerCase().includes(search) || String(row.description || '').toLowerCase().includes(search);
        }), sortKey, sortDir);

      function arrow(key) {
        if ((STATE.toolCatalogSortKey || 'descriptionTokens') !== key) return '<span style="opacity:.4">↕</span>';
        return (STATE.toolCatalogSortDir || 'desc') === 'desc' ? '↓' : '↑';
      }
      function th(key, label, numeric) {
        return `<th class="${numeric ? 'num' : ''}"><button type="button" onclick="setToolCatalogSort('${key}')" style="all:unset;cursor:pointer;color:inherit;display:block;width:100%;text-align:${numeric ? 'right' : 'left'}">${label} ${arrow(key)}</button></th>`;
      }

      return `
        <section class="panel">
          <h2 class="section-title">Tool description token footprint</h2>
          <div class="section-subtitle">Find context-heavy tools quickly. <strong>Tool sets</strong> means the number of distinct tool-definition payloads in which a tool appeared. Click any column header to sort ascending/descending; expand a tool name to view the full captured description.</div>
          <div class="tool-catalog-controls">
            <input type="text" id="toolCatalogSearchInput" placeholder="Search by tool name or description…" value="${escapeHtml(STATE.toolCatalogSearch)}" oninput="setToolCatalogSearch(this.value)">
          </div>
          <div class="note small" style="margin-bottom:10px">Showing ${formatInteger(rows.length)} of ${formatInteger(allRows.length)} tools.</div>
          <div style="overflow-x:auto">
          <table>
            <thead><tr>
              ${th('name', 'Tool', false)}
              ${th('descriptionTokens', 'Description tokens', true)}
              ${th('callCount', 'Calls', true)}
              ${th('sessionCount', 'Sessions', true)}
              ${th('toolSetCount', 'Tool sets', true)}
              ${th('presentCount', 'Present in calls', true)}
              ${th('wastePercent', 'Waste %', true)}
            </tr></thead>
            <tbody>
              ${rows.length ? rows.map((row) => `<tr>
                <td><details><summary><strong>${escapeHtml(row.name)}</strong></summary><pre>${escapeHtml(row.description || '[No description captured for this tool in scanned tool-definition payloads.]')}</pre></details></td>
                <td class="num"><span class="value uncached">${formatInteger(row.descriptionTokens || 0)}</span></td>
                <td class="num">${formatInteger(row.callCount || 0)}</td>
                <td class="num">${formatInteger(row.sessionCount || 0)}</td>
                <td class="num">${formatInteger(row.toolSetCount || 0)}</td>
                <td class="num">${formatInteger(row.presentCount || 0)}</td>
                <td class="num">${formatPercent(row.wastePercent || 0)}</td>
              </tr>`).join('') : '<tr><td colspan="7"><div class="note">No tools matched your search.</div></td></tr>'}
            </tbody>
          </table>
          </div>
        </section>`;
    }

    export function renderTipsSubtab() {
      const tips = [
        {
          icon: '🔁',
          title: "Don't switch models mid-chat",
          severity: 'high',
          body: "Every time you switch models in a conversation, the context cache is invalidated. The next call must re-read the entire accumulated context as fresh (uncached) tokens. This can 3–10× the cost of that single turn. Start a new chat when you want to try a different model.",
        },
        {
          icon: '✂️',
          title: 'Keep chats short',
          severity: 'high',
          body: "Every new message in a chat is appended to an ever-growing context window. By turn 20, the model is re-reading the entire history on every call. Split long tasks into focused sub-chats, each under 10–15 turns. Your cache hit rate will be much higher and costs much lower.",
        },
        {
          icon: '🔧',
          title: 'Reduce active tools',
          severity: 'medium',
          body: "Tool definitions are included in every single prompt sent to the model — even if no tools are called. With 30+ tools enabled, you may be spending thousands of tokens per call just on tool schema overhead. Disable tools or skills you do not need for the current task.",
        },
        {
          icon: '🆕',
          title: 'Start a new chat for each new topic',
          severity: 'medium',
          body: "Continuing an existing chat for unrelated tasks forces the model to carry irrelevant context (previous files, messages, tool results). This inflates the prompt size and reduces cache effectiveness. A fresh chat starts with a minimal context and much better cache hit rates.",
        },
        {
          icon: '💾',
          title: 'Let the cache warm up',
          severity: 'medium',
          body: "Copilot uses prompt caching — identical leading content across consecutive turns is billed at a fraction of normal input cost. The longer you continue a focused conversation, the higher your cache hit rate becomes. Avoid making large edits to files mid-chat as this changes the prompt shape and busts the cache.",
        },
        {
          icon: '📄',
          title: 'Be selective with context files',
          severity: 'medium',
          body: "#file references and workspace context are included in every prompt turn. Attaching large files or entire directories significantly inflates your context window. Reference only the specific files relevant to the current task and remove them when no longer needed.",
        },
        {
          icon: '📝',
          title: 'Keep system prompts lean',
          severity: 'low',
          body: "Custom instructions and system prompts are prepended to every API call. A 2,000-token system prompt added to 600 chat calls costs you 1.2M extra input tokens. Audit your .github/copilot-instructions.md and VS Code custom instructions — keep them focused and concise.",
        },
        {
          icon: '⚡',
          title: 'Use cheaper models for simple tasks',
          severity: 'low',
          body: "Not every task needs a frontier model. Simple code completions, renaming, or straightforward Q&A work just as well with faster, cheaper models (e.g. gpt-4o-mini, claude-haiku). Reserve expensive models for complex reasoning, architecture decisions, or tasks that genuinely need deep understanding.",
        },
        {
          icon: '🔍',
          title: 'Monitor your cache hit rate',
          severity: 'low',
          body: "A healthy cache hit rate is 85%+ — meaning most of your input tokens are billed at the cheap cached rate. If your cache hit rate drops below 70%, you are probably switching contexts too often, switching models, or having frequent context resets. Check the Analysis → Insights tab for patterns.",
        },
        {
          icon: '🤖',
          title: 'Avoid long agentic loops',
          severity: 'low',
          body: "Autonomous agent tasks with many tool call loops (read_file, replace_string_in_file, run_in_terminal repeated 30+ times) accumulate massive context quickly. Break large agentic tasks into smaller, focused steps. If a subagent approach is available, use it — subagents start fresh contexts.",
        },
      ];

      const severityColors = {
        high: 'var(--red)',
        medium: 'var(--yellow)',
        low: 'var(--green)',
      };
      const severityLabels = { high: 'High impact', medium: 'Medium impact', low: 'Low impact' };

      return `
        <div class="analysis-grid">
          <section class="panel">
            <h2 class="section-title">Tips & Advice — Reducing Token Usage and Costs</h2>
            <div class="section-subtitle">Based on analysis of common usage patterns. High-impact tips can reduce costs by 50–80%. The <span style="color:var(--red)">red</span> badges indicate the biggest wins.</div>
            <div class="insights-grid" style="grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))">
              ${tips.map((tip) => `
                <div class="insight-card" style="border-left:3px solid ${severityColors[tip.severity]}">
                  <h4 style="display:flex;align-items:center;gap:8px;white-space:normal">
                    <span style="font-size:1.4rem">${tip.icon}</span>
                    <span>${escapeHtml(tip.title)}</span>
                    <span style="margin-left:auto;font-size:0.7rem;font-weight:700;color:${severityColors[tip.severity]};white-space:nowrap">${severityLabels[tip.severity]}</span>
                  </h4>
                  <div class="note small" style="line-height:1.6">${escapeHtml(tip.body)}</div>
                </div>`).join('')}
            </div>
          </section>
        </div>`;
    }

    export function renderTelemetrySubtab() {
      const telemetry = activeAnalysis().telemetry || { sections: [], observedFields: [], entryTypes: {} };
      return `
        <div class="analysis-grid">
          <section class="panel">
            <h2 class="section-title">Telemetry coverage</h2>
            <div class="section-subtitle">What the current Copilot debug / OTel data gives directly, and what the dashboard must estimate.</div>
            <div class="insights-grid">
              ${(telemetry.sections || []).map((section) => `<div class="insight-card"><h4>${escapeHtml(section.name)}</h4><ul class="help-list">${(section.items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>`).join('')}
            </div>
          </section>
          <section class="panel">
            <h2 class="section-title">Observed attribute fields</h2>
            <pre>${escapeHtml(JSON.stringify(telemetry.observedFields, null, 2))}</pre>
          </section>
        </div>`;
    }

    export function renderReferenceTab() {
      const tabBodies = {
        prices: renderModelPricesSubtab,
        toolCatalog: renderToolCatalogSubtab,
        tips: renderTipsSubtab,
        telemetry: renderTelemetrySubtab,
      };
      if (!tabBodies[STATE.dataTab]) {
        STATE.dataTab = 'prices';
      }
      return `<section class="panel">${dataSubtabs()}</section>${tabBodies[STATE.dataTab]()}`;
    }
