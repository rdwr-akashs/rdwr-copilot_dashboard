import { deleteSessionPrompt, setModelFilter, setSearch } from './actions.js';
import { pagedSessions, visibleSessions } from './aggregate.js';
import { boundaryLabel, buildOverheadBreakdown, cacheHitRateForBlock, escapeHtml, eventDisplayChatTokens, eventDisplayEstimatedTokens, formatCost, formatDuration, formatInteger, formatPercent, formatTimestamp, promptWindowLabel, sessionDisplayTotals, sessionOverheadForMode } from './format.js';
import { exportSessionToJson, openChatDeleteModal, openFullChatModal, openGenAiModal, openModelCompareModal } from './modals.js';
import { HIDDEN_SESSION_IDS, STATE, isBilledMode, restoreHiddenChats, tokenModeLabel } from './state.js';
import { renderPagination, renderStatCell } from './tables.js';


    export function renderSessionMeta(session) {
      const dur = session.duration_ms || 0;
      const durLabel = dur > 60000 ? `${(dur / 60000).toFixed(1)}min` : dur > 1000 ? `${(dur / 1000).toFixed(0)}s` : '—';
      const modelNames = session.model_names?.length ? session.model_names.join(', ') : (session.model || 'unknown');
      const totals = sessionDisplayTotals(session);
      return `
        <div class="session-meta">
          <div class="meta-card"><div class="label">Source IP</div><div class="value">${escapeHtml(session.source_ip || 'unknown-ip')}</div></div>
          <div class="meta-card"><div class="label">Session ID</div><div class="value">${escapeHtml(session.session_id || session.id || 'unknown')}</div></div>
          <div class="meta-card"><div class="label">Primary model</div><div class="value">${escapeHtml(session.model || 'unknown')}</div></div>
          <div class="meta-card"><div class="label">Models used</div><div class="value">${escapeHtml(modelNames)}</div></div>
          <div class="meta-card"><div class="label">Duration</div><div class="value">${durLabel}</div></div>
          <div class="meta-card"><div class="label">Segments</div><div class="value">${formatInteger(session.segment_count || 0)}</div></div>
          <div class="meta-card"><div class="label">Total input</div><div class="value input">${formatInteger(totals.input)}</div></div>
          <div class="meta-card"><div class="label">Uncached input</div><div class="value uncached">${formatInteger(totals.uncached)}</div></div>
          <div class="meta-card"><div class="label">Cached-read</div><div class="value cached">${formatInteger(totals.cached)}</div></div>
          <div class="meta-card"><div class="label">Total output</div><div class="value output">${formatInteger(totals.output)}</div></div>
          <div class="meta-card"><div class="label">${isBilledMode() ? 'Billed cost' : 'Attributed est. cost'}</div><div class="value cost">${formatCost(totals.cost)}</div></div>
          <div class="meta-card"><div class="label">Cache hit rate</div><div class="value cached">${formatPercent(cacheHitRateForBlock(totals))}</div></div>
          <div class="meta-card"><div class="label">Peak prompt</div><div class="value">${formatInteger(session.peak_prompt_tokens)}</div></div>
          <div class="meta-card"><div class="label">Model switches</div><div class="value">${formatInteger(session.boundary_counts?.model_switch || 0)}</div></div>
          <div class="meta-card"><div class="label">Context resets</div><div class="value">${formatInteger(session.boundary_counts?.context_reset || 0)}</div></div>
          <div class="meta-card"><div class="label">Cache resets</div><div class="value">${formatInteger(session.boundary_counts?.cache_reset || 0)}</div></div>
        </div>`;
    }

    export function renderContextBreakdown(breakdown) {
      if (!breakdown) {
        return '<div class="note">No context window breakdown available.</div>';
      }
      const segments = breakdown.categories.map((item) => {
        const colors = {
          system_instructions: 'var(--blue)',
          tool_definitions: 'var(--purple)',
          messages: 'var(--orange)',
          tool_results: 'var(--green)',
          other: 'var(--faint)',
        };
        return `<div title="${escapeHtml(item.label)} · ${formatInteger(item.tokens)} tokens (${formatPercent(item.percent_of_prompt)} of prompt)" style="width:${item.percent_of_prompt}%; background:${colors[item.key]}; height:100%;"></div>`;
      }).join('');
      const reserved = breakdown.reserved_percent_of_window
        ? `<div title="Reserved for response · ${formatInteger(breakdown.reserved_response_tokens)} tokens" style="width:${breakdown.reserved_percent_of_window}%; height:100%; background: repeating-linear-gradient(135deg, rgba(188,140,255,.45), rgba(188,140,255,.45) 6px, rgba(188,140,255,.18) 6px, rgba(188,140,255,.18) 12px);"></div>`
        : '';
      return `
        <div class="event-section">
          <h4>Context window estimate</h4>
          <div class="note">Prompt now: <strong>${promptWindowLabel(breakdown)}</strong> · Cached inside prompt: <strong>${formatInteger(breakdown.cached_tokens)}</strong> · Uncached prompt: <strong>${formatInteger(breakdown.uncached_tokens)}</strong></div>
          <div style="display:flex; width:100%; height:16px; overflow:hidden; border-radius:999px; margin:12px 0; background:var(--overlay-06);border:1px solid var(--overlay-08);">
            ${segments}
            ${reserved}
          </div>
          <table>
            <thead>
              <tr><th>Section</th><th class="num">Tokens</th><th class="num">% of prompt</th><th class="num">% of window</th></tr>
            </thead>
            <tbody>
              ${breakdown.categories.map((item) => `<tr><td>${escapeHtml(item.label)}</td><td class="num">${formatInteger(item.tokens)}</td><td class="num">${formatPercent(item.percent_of_prompt)}</td><td class="num">${item.percent_of_window ? formatPercent(item.percent_of_window) : '—'}</td></tr>`).join('')}
              ${breakdown.reserved_response_tokens ? `<tr><td>Reserved for response</td><td class="num">${formatInteger(breakdown.reserved_response_tokens)}</td><td class="num">—</td><td class="num">${breakdown.reserved_percent_of_window ? formatPercent(breakdown.reserved_percent_of_window) : '—'}</td></tr>` : ''}
            </tbody>
          </table>
        </div>`;
    }

    export function renderEventDetailSections(event) {
      if (event.kind === 'user_message') {
        return `<div class="event-section"><h4>Full user message</h4><pre>${escapeHtml(event.content || '')}</pre></div>`;
      }

      if (event.kind === 'tool') {
        const files = event.files?.length
          ? `<div class="pill-list">${event.files.map((file) => `<span class="pill">${escapeHtml(file)}</span>`).join('')}</div>`
          : '<div class="note">No file path detected in tool arguments.</div>';
        return `
          <div class="event-body-grid">
            <div class="event-section"><h4>Files involved</h4>${files}</div>
            <div class="split-grid">
              <div class="event-section"><h4>Tool input</h4><pre>${escapeHtml(event.args_pretty || '')}</pre></div>
              <div class="event-section"><h4>Tool output</h4><pre>${escapeHtml(event.result_text || '')}</pre></div>
            </div>
          </div>`;
      }

      const emittedTools = (event.tool_calls_emitted || []).length
        ? `<div class="event-section"><h4>Tools emitted by this chat call</h4><div class="message-list">${event.tool_calls_emitted.map((tool) => `<div class="message-card"><div class="message-header"><span class="badge tool">Tool</span><strong>${escapeHtml(tool.name)}</strong></div><pre>${escapeHtml(tool.arguments || '')}</pre></div>`).join('')}</div></div>`
        : '';

      const boundarySummary = (event.boundary_reasons || []).length
        ? `<div class="event-section"><h4>Segment boundary</h4><div class="pill-list">${event.boundary_reasons.map((reason) => `<span class="badge boundary">${escapeHtml(boundaryLabel(reason))}</span>`).join('')}</div><div class="note" style="margin-top:8px">${isBilledMode() ? 'This call started a new internal segment. In billed mode we use per-call billed totals directly.' : 'This call started a new internal segment, so tool/file attribution uses the full billed input for this call instead of only the prompt-growth delta from the previous call.'}</div></div>`
        : '';

      return `
        <div class="event-body-grid">
          ${boundarySummary}
          ${renderContextBreakdown(event.context_breakdown)}
          <div class="split-grid">
            <div class="event-section"><h4>Reasoning</h4><pre>${escapeHtml(event.reasoning || '[not recorded]')}</pre></div>
            <div class="event-section"><h4>Assistant output</h4><pre>${escapeHtml(event.response_text || '[empty]')}</pre></div>
          </div>
          ${emittedTools}
        </div>`;
    }

    export function renderEvent(event, session) {
      const kindBadgeClass = event.kind === 'chat' ? 'chat' : event.kind === 'tool' ? 'tool' : 'user';
      const timing = `${formatTimestamp(event.ts)} · ${formatDuration(event.duration_ms)}`;
      const modeBadge = event.kind === 'tool' ? `<span class="badge mode-${event.mode || 'other'}">${escapeHtml(event.mode || 'other')}</span>` : '';
      const genAiButton = event.kind === 'chat'
        ? `<button type="button" class="genai-button" onclick="event.stopPropagation(); openGenAiModal('${session.id}', '${event.id}')">GenAI details</button>`
        : '';
      const boundaryBadges = (event.boundary_reasons || []).map((reason) => `<span class="badge boundary">${escapeHtml(boundaryLabel(reason))}</span>`).join('');

      if (event.kind === 'chat') {
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
                <div class="subtext">${escapeHtml(timing)} · segment ${formatInteger(event.segment_index || 1)} · prompt snapshot + ${escapeHtml(tokenModeLabel())} call totals</div>
              </div>
              ${renderStatCell('Prompt now', formatInteger(event.prompt_tokens))}
              ${renderStatCell('Total input', formatInteger(chatTokens.input), 'input')}
              ${renderStatCell('Uncached', formatInteger(chatTokens.uncached), 'uncached')}
              ${renderStatCell('Cached-read', formatInteger(chatTokens.cached), 'cached', true)}
              ${renderStatCell('Output', formatInteger(chatTokens.output), 'output', true)}
              ${renderStatCell(isBilledMode() ? 'Billed cost' : 'Attributed est. cost', formatCost(chatTokens.cost), 'cost')}
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
                <span class="badge ${kindBadgeClass}">${escapeHtml(event.kind.replace('_', ' '))}</span>
                <span class="title-text">${escapeHtml(event.title)}</span>
                <span class="badge source">${escapeHtml(event.source)}</span>
                ${modeBadge}
              </div>
              <div class="subtext">${escapeHtml(timing)} · estimated ${escapeHtml(tokenModeLabel())} impact</div>
            </div>
            ${renderStatCell('Status', escapeHtml(event.status || '—'))}
            ${renderStatCell('Duration', formatDuration(event.duration_ms))}
            ${renderStatCell('Input', '≈ ' + formatInteger(estimated.input), 'input')}
            ${renderStatCell('Output', '≈ ' + formatInteger(estimated.output), 'output')}
            ${renderStatCell('Cached', '≈ ' + formatInteger(estimated.cached), 'cached', true)}
            ${renderStatCell('Cost', formatCost(estimated.cost), 'cost')}
          </summary>
          <div class="event-body">${renderEventDetailSections(event)}</div>
        </details>`;
    }

    export function renderSessionTokenBreakdown(session) {
      const overhead = sessionOverheadForMode(session);
      const totals = sessionDisplayTotals(session);
      const totalInput = Number(totals.input || 0);
      if (!totalInput) return '';

      const categories = buildOverheadBreakdown(overhead, totalInput);

      const definitions = [
        '<strong>Chat History</strong> = earlier assistant replies carried forward into later turns.',
        '<strong>Tools</strong> = tool-call payload inside chat context (tool call arguments/results, plus non-file tool metadata).',
        '<strong>Files</strong> = file-related context from read/edit tool turns (mode-aware split estimate).',
      ];

      const segments = categories
        .filter((c) => c.pct > 0)
        .map((c) => `<div title="${escapeHtml(c.label)} · ${formatInteger(c.input)} tokens (${c.pct.toFixed(1)}%)" style="width:${c.pct}%;background:${c.color};height:100%;"></div>`)
        .join('');

      return `
        <div class="event-section" style="margin-bottom:14px">
          <h4>Session token breakdown (${isBilledMode() ? 'estimated billed distribution' : 'estimated attribution'})</h4>
          <div class="note small" style="margin-bottom:8px">Where did this chat's <strong>${formatInteger(totalInput)}</strong> ${escapeHtml(tokenModeLabel())} input tokens go? This uses the same category model as the global token breakdown. Numbers can differ from a single Copilot screenshot because screenshots show one call's current prompt window, while this view aggregates usage across many calls.</div>
          <div style="display:flex;width:100%;height:16px;overflow:hidden;border-radius:999px;margin:8px 0;background:var(--overlay-06);border:1px solid var(--overlay-08);">
            ${segments}
          </div>
          <table style="margin-top:8px">
            <thead><tr><th>Category</th><th class="num">Input tokens</th><th class="num">% of total</th><th class="num">Est. cost</th></tr></thead>
            <tbody>
              ${categories.map((c) => `<tr><td><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${c.color};margin-right:6px;vertical-align:middle"></span>${escapeHtml(c.label)}</td><td class="num">${formatInteger(c.input)}</td><td class="num">${c.pct.toFixed(1)}%</td><td class="num">${c.cost > 0 ? formatCost(c.cost) : '—'}</td></tr>`).join('')}
            </tbody>
          </table>
          <div class="note small" style="margin-top:10px">${definitions.join('<br>')}</div>
        </div>`;
    }

    export function renderSession(session, sessionIndex) {
      const dur = session.duration_ms || 0;
      const durLabel = dur > 60000 ? `${(dur / 60000).toFixed(0)}m` : dur > 1000 ? `${(dur / 1000).toFixed(0)}s` : dur ? `${dur.toFixed(0)}ms` : '—';
      const modelNames = (session.model_names?.length ? session.model_names : [session.model]).filter(Boolean);
      const modelBadges = modelNames.slice(0, 3).map((modelName) => `<span class="badge model">${escapeHtml(modelName)}</span>`).join('');
      const extraModels = modelNames.length > 3 ? `<span class="badge source">+${formatInteger(modelNames.length - 3)} models</span>` : '';
      const sourceBadge = `<span class="badge source">${escapeHtml(session.source_ip || 'unknown-ip')}</span>`;
      const totals = sessionDisplayTotals(session);
      return `
        <details class="session-card">
          <summary class="session-summary-row">
            <div class="title-col">
              <div class="title-line">
                ${modelBadges || `<span class="badge model">${escapeHtml(session.model || 'unknown')}</span>`}
                ${extraModels}
                ${sourceBadge}
                <span class="title-text">${escapeHtml(session.title)}</span>
              </div>
              <div class="subtext">${escapeHtml(formatTimestamp(session.timestamp))} · ${formatInteger(session.chat_count)} calls · ${formatInteger(session.tool_count)} tools · ${formatInteger(session.segment_count || 0)} segments · ${durLabel}</div>
            </div>
            ${renderStatCell('Total input', formatInteger(totals.input), 'input')}
            ${renderStatCell('Uncached', formatInteger(totals.uncached), 'uncached')}
            ${renderStatCell('Cached-read', formatInteger(totals.cached), 'cached', true)}
            ${renderStatCell('Output', formatInteger(totals.output), 'output')}
            ${renderStatCell('Segments', formatInteger(session.segment_count || 0))}
            ${renderStatCell('Cost', formatCost(totals.cost), 'cost')}
          </summary>
          <div class="session-body">
            <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:12px;flex-wrap:wrap">
              <button type="button" class="action-chip action-chip--blue" onclick="event.stopPropagation();openFullChatModal('${session.id}')">📂 Show full chat</button>
              <button type="button" class="action-chip action-chip--purple" onclick="event.stopPropagation();openModelCompareModal('${session.id}')">⚖ Compare models</button>
              <button type="button" class="action-chip action-chip--teal" onclick="event.stopPropagation();exportSessionToJson('${session.id}')">⬇ Export chat JSON</button>
              <button type="button" class="action-chip action-chip--red" onclick="event.stopPropagation();deleteSessionPrompt('${session.id}')">🗑 Delete chat</button>
            </div>
            ${renderSessionMeta(session)}
            ${renderSessionTokenBreakdown(session)}
            <div class="note small" style="margin-top:12px;text-align:center">Per-call timeline, tool calls and GenAI details load on demand — press <strong>📂 Show full chat</strong>.</div>
          </div>
        </details>`;
    }

    export function renderChatsTab() {
      const models = [...new Set(visibleSessions().flatMap((session) => (session.model_names?.length ? session.model_names : [session.model]).filter(Boolean)))].sort();
      const pages = pagedSessions();
      const sessionsHtml = pages.slice.map((session) => renderSession(session)).join('');
      const hiddenCount = HIDDEN_SESSION_IDS.size;
      return `
        <section class="panel">
          <div class="filter-bar">
            <input type="text" id="chatSearchInput" placeholder="Search by chat title, model, session ID, or IP…" value="${escapeHtml(STATE.search)}" oninput="setSearch(this.value)">
            <select onchange="setModelFilter(this.value)">
              <option value="">All models</option>
              ${models.map((model) => `<option value="${escapeHtml(model)}" ${STATE.model === model ? 'selected' : ''}>${escapeHtml(model)}</option>`).join('')}
            </select>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-left:auto">
              <button type="button" class="action-chip action-chip--red" onclick="openChatDeleteModal()">🗑 Delete chats</button>
              ${hiddenCount ? `<button type="button" class="action-chip action-chip--blue" onclick="restoreHiddenChats()">↩ Restore hidden (${formatInteger(hiddenCount)})</button>` : ''}
            </div>
          </div>
          ${renderPagination(pages.all.length, pages.pageCount)}
          <!-- Methodology behind a disclosure: it is a paragraph you read
               once, and inline it pushed the first session card a full screen
               down every visit. Collapsed keeps it one click away. -->
          <details class="method-note">
            <summary class="note small">How these totals are computed</summary>
            <div class="legend" style="margin-top:8px">${isBilledMode() ? 'Each session total uses <strong>billed per-call totals</strong> directly from API usage fields.' : 'Each session total uses <strong>prompt-growth attribution</strong>: the first call in each segment is counted at full billed cost (fresh context); subsequent calls within a segment contribute only the net-new prompt delta + output. This avoids double-counting the growing conversation history across turns.'} Model switches and context resets start new segments. <code>input</code> includes cached-read tokens; uncached input is shown separately.</div>
            <div class="note small" style="margin-top:8px">Delete actions hide chats in this browser view (persisted locally) and can be reverted with <em>Restore hidden</em>. They do not erase raw debug logs.</div>
          </details>
        </section>
        <section class="session-list">${sessionsHtml || '<div class="panel"><div class="note">No sessions match the current filter.</div></div>'}</section>`;
    }
