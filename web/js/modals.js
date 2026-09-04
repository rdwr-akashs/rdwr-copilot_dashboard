import { analysisForMode, computeChatDeletionTargets, visibleCliSessions, visibleSessions } from './aggregate.js';
import { calcModelCost, escapeHtml, eventDisplayChatTokens, formatCompact, formatCost, formatDuration, formatInteger, formatTimestamp, sessionDisplayTotals } from './format.js';
import { APP_DATA, PRICING_TABLE, STATE, isBilledMode, tokenModeLabel } from './state.js';
import { renderContextBreakdown, renderEvent, renderSessionMeta, renderSessionTokenBreakdown } from './tab-chats.js';


    export function renderPart(part) {
      if (part.type === 'tool_call') {
        return `<div class="part-card"><div class="part-label">${escapeHtml(part.label)}</div><pre>${escapeHtml(part.arguments_pretty || '')}</pre></div>`;
      }
      return `<div class="part-card"><div class="part-label">${escapeHtml(part.label || part.type || 'Part')}</div><pre>${escapeHtml(part.text || '')}</pre></div>`;
    }

    export function renderMessage(message) {
      return `<div class="message-card"><div class="message-header"><span class="badge ${message.role === 'user' ? 'user' : message.role === 'assistant' ? 'chat' : 'tool'}">${escapeHtml(message.role)}</span><span class="note small">${formatInteger(message.parts?.length || 0)} parts</span></div><div class="message-parts">${(message.parts || []).map(renderPart).join('')}</div></div>`;
    }

    // Cache of full session payloads ({session, assets}) fetched on demand.
    const FULL_SESSIONS = {};

    export function findSessionAndEvent(sessionId, eventId) {
      const full = FULL_SESSIONS[sessionId];
      const session = full?.session;
      const event = session?.events?.find((item) => item.id === eventId);
      return { session, event, assets: full?.assets || { systemPrompts: {}, toolSets: {} } };
    }

    export function renderGenAiModal(sessionId, eventId) {
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
        requestShape: event.request_shape,
      };

      document.getElementById('genaiModalTitle').textContent = event.title;
      document.getElementById('genaiModalSubtitle').textContent = `${session.title} · ${event.model} · ${formatTimestamp(event.ts)}`;
      document.getElementById('genaiModalStats').innerHTML = `
        <div class="meta-card"><div class="label">Prompt now</div><div class="value input">${formatInteger(event.prompt_tokens)}</div></div>
        <div class="meta-card"><div class="label">Segment</div><div class="value">${formatInteger(event.segment_index || 1)}</div></div>
        <div class="meta-card"><div class="label">Total input</div><div class="value input">${formatInteger(selectedTokens.input)}</div></div>
        <div class="meta-card"><div class="label">Uncached input</div><div class="value uncached">${formatInteger(selectedTokens.uncached)}</div></div>
        <div class="meta-card"><div class="label">Cached-read</div><div class="value cached">${formatInteger(selectedTokens.cached)}</div></div>
        <div class="meta-card"><div class="label">Output</div><div class="value output">${formatInteger(selectedTokens.output)}</div></div>
        <div class="meta-card"><div class="label">TTFT</div><div class="value">${formatDuration(event.ttft_ms)}</div></div>
        <div class="meta-card"><div class="label">${isBilledMode() ? 'Billed cost' : 'Attributed est. cost'}</div><div class="value cost">${formatCost(selectedTokens.cost)}</div></div>`;

      const tabs = [
        ['io', 'Input & output'],
        ['tools', `Tools${toolSet?.tool_names?.length ? ' ' + toolSet.tool_names.length : ''}`],
        ['context', 'Context window'],
        ['details', 'Details'],
      ];
      document.getElementById('genaiModalTabs').innerHTML = tabs.map(([id, title], index) => `<button type="button" data-tab="${id}" class="modal-tab ${index === 0 ? 'active' : ''}" onclick="switchGenAiTab('${id}')">${escapeHtml(title)}</button>`).join('');

      document.getElementById('genaiModalContent').innerHTML = `
        <div id="genai-panel-io" class="modal-panel active">
          <div class="split-grid">
            <div class="event-section"><h4>System prompt</h4><pre>${escapeHtml(systemPrompt?.plain_text || '[not available]')}</pre></div>
            <div class="event-section"><h4>Assistant output</h4><div class="message-list">${(event.response_messages || []).map(renderMessage).join('') || '<div class="note">No structured output was stored.</div>'}</div></div>
          </div>
          <div class="event-section"><h4>Input messages Copilot sent into this call</h4><div class="message-list">${(event.input_messages || []).map(renderMessage).join('') || '<div class="note">No input messages were recorded.</div>'}</div></div>
          <div class="event-section"><h4>New context added since previous call</h4><div class="message-list">${(event.new_messages || []).map(renderMessage).join('') || '<div class="note">No new messages detected or the prompt was rebuilt.</div>'}</div></div>
        </div>
        <div id="genai-panel-tools" class="modal-panel">
          <div class="event-section"><h4>Tool definitions available to the model</h4>${toolSet?.tool_names?.length ? `<div class="pill-list">${toolSet.tool_names.map((name) => `<span class="pill">${escapeHtml(name)}</span>`).join('')}</div>` : '<div class="note">No tool definitions were captured for this call.</div>'}</div>
          <div class="split-grid">
            <div class="event-section"><h4>Emitted tool calls</h4><div class="message-list">${(event.tool_calls_emitted || []).map((tool) => `<div class="message-card"><div class="message-header"><span class="badge tool">Tool call</span><strong>${escapeHtml(tool.name)}</strong></div><pre>${escapeHtml(tool.arguments || '')}</pre></div>`).join('') || '<div class="note">This chat call did not emit a tool call.</div>'}</div></div>
            <div class="event-section"><h4>Tool definition payload</h4><pre>${escapeHtml(toolSet?.plain_text || '[not available]')}</pre></div>
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
            <div class="event-section"><h4>Reasoning</h4><pre>${escapeHtml(event.reasoning || '[not recorded]')}</pre></div>
            <div class="event-section"><h4>Raw response text</h4><pre>${escapeHtml(event.response_text || '[empty]')}</pre></div>
          </div>
        </div>`;

      document.getElementById('genaiModalBackdrop').classList.add('open');
    }

    export function switchGenAiTab(tabId) {
      document.querySelectorAll('#genaiModalTabs .modal-tab').forEach((button) => button.classList.toggle('active', button.dataset.tab === tabId));
      document.querySelectorAll('#genaiModalContent .modal-panel').forEach((panel) => panel.classList.toggle('active', panel.id === `genai-panel-${tabId}`));
    }

    export async function openGenAiModal(sessionId, eventId) {
      if (!FULL_SESSIONS[sessionId]) {
        try {
          await fetchFullSession(sessionId);
        } catch (err) {
          // Previously silently no-op'd, so a click on "GenAI details" (in
          // the rare case it's reachable without a preceding successful
          // "Show full chat" load, e.g. a live server that went down after
          // caching once) looked like the button was completely broken.
          // Surface the same actionable message the full-chat modal shows.
          document.getElementById('genaiModalTitle').textContent = 'GenAI details unavailable';
          document.getElementById('genaiModalSubtitle').textContent = '';
          document.getElementById('genaiModalStats').innerHTML = '';
          document.getElementById('genaiModalTabs').innerHTML = '';
          document.getElementById('genaiModalContent').innerHTML = `<div class="is-empty">${describeFullSessionError(err)}</div>`;
          document.getElementById('genaiModalBackdrop').classList.add('open');
          return;
        }
      }
      renderGenAiModal(sessionId, eventId);
    }

    export function closeGenAiModal(event) {
      if (event && event.target && event.target !== document.getElementById('genaiModalBackdrop')) return;
      document.getElementById('genaiModalBackdrop').classList.remove('open');
    }

    // Distinguishes a network-level failure (typical when this page was
    // opened as the static `dashboard_core.py -o file.html` export, which
    // deliberately does NOT embed full per-call session bodies -- doing so
    // would balloon the "single self-contained file" by 1-2MB+ per chat --
    // so `/api/session` simply doesn't exist to fetch) from a genuine
    // HTTP-level failure (e.g. a live server that no longer recognises this
    // session id after the underlying logs were regenerated). Browsers
    // reject `fetch()` itself (a TypeError, no Response) for the former;
    // `response.ok === false` covers the latter.
    function describeFullSessionError(err) {
      if (err && err.code === 'network') {
        return 'Full per-call chat detail (timeline, GenAI details, raw chat JSON export) needs the live dashboard server -- this static export only embeds per-session summaries, not full chat bodies, to keep the file a reasonable size. Run <code>python serve_dashboard.py</code> in this project folder and open the printed http://localhost:8765 URL instead to see it.';
      }
      return escapeHtml(String((err && err.message) || err || 'Full chat detail is not available for this session.'));
    }

    export async function fetchFullSession(sessionId) {
      if (FULL_SESSIONS[sessionId]) return FULL_SESSIONS[sessionId];
      let response;
      try {
        response = await fetch(`/api/session?id=${encodeURIComponent(sessionId)}`);
      } catch (_networkErr) {
        const err = new Error('Failed to reach the dashboard server.');
        err.code = 'network';
        throw err;
      }
      if (!response.ok) {
        // A generic static-file server (or `file://`) that doesn't
        // understand the `/api/session` route typically answers with its
        // own 404 HTML page rather than throwing, so treat any non-OK
        // response the same way a network failure is treated: it's
        // indistinguishable from "no live server" without more signal.
        const err = new Error(`Failed to load chat (${response.status})`);
        err.code = 'network';
        throw err;
      }
      const payload = await response.json();
      if (!payload || !payload.session) {
        throw new Error('Full chat detail is not available for this session.');
      }
      FULL_SESSIONS[sessionId] = payload;
      return payload;
    }

    export function renderFullChatBody(session) {
      const events = Array.isArray(session?.events) ? session.events : [];
      const timeline = events.length
        ? events.map((event) => renderEvent(event, session)).join('')
        : '<div class="note">No per-call events were recorded for this chat.</div>';
      return `
        ${renderSessionMeta(session)}
        ${renderSessionTokenBreakdown(session)}
        <div class="timeline">${timeline}</div>`;
    }

    export async function openFullChatModal(sessionId) {
      const meta = (APP_DATA.sessions || []).find((item) => item.id === sessionId);
      const backdrop = document.getElementById('fullChatModalBackdrop');
      document.getElementById('fullChatModalTitle').textContent = meta?.title || 'Full chat';
      document.getElementById('fullChatModalSubtitle').textContent = meta
        ? `${meta.model || 'unknown'} · ${formatTimestamp(meta.timestamp)} · ${formatInteger(meta.chat_count)} calls · ${formatInteger(meta.tool_count)} tools`
        : '';
      const exportBtn = document.getElementById('fullChatExportBtn');
      if (exportBtn) exportBtn.onclick = () => exportSessionToJson(sessionId);
      const body = document.getElementById('fullChatModalContent');
      body.innerHTML = '<div class="note" style="padding:24px;text-align:center">Loading full chat detail…</div>';
      backdrop.classList.add('open');
      try {
        const payload = await fetchFullSession(sessionId);
        body.innerHTML = renderFullChatBody(payload.session);
      } catch (err) {
        body.innerHTML = `<div class="is-empty" style="padding:24px">${describeFullSessionError(err)}</div>`;
      }
    }

    export function closeFullChatModal(event) {
      if (event && event.target && event.target !== document.getElementById('fullChatModalBackdrop')) return;
      document.getElementById('fullChatModalBackdrop').classList.remove('open');
    }

    export function renderFileUsageSummary(file) {
      const rows = [...(file?.toolUsage || [])].sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0) || Number(b.count || 0) - Number(a.count || 0));
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
          <div class="note">Aggregated per tool and mode for this file — no per-call timeline is stored here.</div>
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
                <th class="num">AI credits</th>
              </tr></thead>
              <tbody>
                ${rows.map((row) => `<tr>
                  <td><strong>${escapeHtml(row.name || 'unknown')}</strong></td>
                  <td>${escapeHtml(row.mode || 'other')}</td>
                  <td class="num">${formatInteger(row.count || 0)}</td>
                  <td class="num">${formatInteger(row.sessionCount || 0)}</td>
                  <td class="num">${formatDuration(row.avgDurationMs || 0)}</td>
                  <td class="num"><span class="value input">${formatCompact(row.input || 0)}</span></td>
                  <td class="num"><span class="value output">${formatCompact(row.output || 0)}</span></td>
                  <td class="num"><span class="value cached">${formatCompact(row.cached || 0)}</span></td>
                  <td class="num">${formatInteger(row.payloadTokens || 0)}</td>
                  <td class="num"><span class="value cost">${formatCost(row.cost || 0)}</span></td>
                </tr>`).join('')}
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

    export function openFileModal(pathEncoded) {
      const path = decodeURIComponent(pathEncoded);
      const file = (analysisForMode().files || []).find((item) => item.path === path);
      if (!file) return;
      document.getElementById('fileExportBtn').onclick = () => exportFileToJson(pathEncoded);
      document.getElementById('fileModalTitle').textContent = file.name;
      document.getElementById('fileModalSubtitle').textContent = file.shortPath + ' · ' + tokenModeLabel() + ' mode · ' + formatInteger(file.toolReferenceCount || 0) + ' tool refs';
      const totalFileOps = file.readCount + file.editCount;
      document.getElementById('fileModalStats').innerHTML = `
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
      document.getElementById('fileModalContent').innerHTML = `
        ${renderFileUsageSummary(file)}`;
      document.getElementById('fileModalBackdrop').classList.add('open');
    }

    export function closeFileModal(event) {
      if (event && event.target && event.target !== document.getElementById('fileModalBackdrop')) return;
      document.getElementById('fileModalBackdrop').classList.remove('open');
    }

    export function exportFileToJson(pathEncoded) {
      const path = decodeURIComponent(pathEncoded);
      const file = (analysisForMode().files || []).find((item) => item.path === path);
      if (!file) return;
      const blob = new Blob([JSON.stringify(file, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const safeName = (file.name || 'file').replace(/[^a-zA-Z0-9._-]/g, '_');
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      a.href = url;
      a.download = `file-activity-${safeName}-${ts}.json`;
      a.click();
      URL.revokeObjectURL(url);
    }

    export function updateChatDeletePreview() {
      const previewEl = document.getElementById('chatDeletePreview');
      const applyBtn = document.getElementById('chatDeleteApplyBtn');
      if (!previewEl || !applyBtn) return;

      const isCli = STATE.deleteTarget === 'cli';
      const visibleCount = isCli ? visibleCliSessions().length : visibleSessions().length;
      const targets = computeChatDeletionTargets();
      const label = isCli ? 'CLI sessions' : 'chats';
      const tabLabel = isCli ? 'CLI tab' : 'Chats tab';
      previewEl.innerHTML = `This action will hide <strong>${formatInteger(targets.length)}</strong> of <strong>${formatInteger(visibleCount)}</strong> visible ${label} from the ${tabLabel}.`;
      applyBtn.disabled = !targets.length;
      applyBtn.style.opacity = targets.length ? '1' : '0.5';
      applyBtn.style.cursor = targets.length ? 'pointer' : 'default';

      const customDateInput = document.getElementById('deleteSpecificDate');
      if (customDateInput) {
        customDateInput.disabled = STATE.deleteAgePreset !== 'custom';
      }
    }

    export function openChatDeleteModal(target = 'chats') {
      STATE.deleteTarget = target === 'cli' ? 'cli' : 'chats';
      const isCli = STATE.deleteTarget === 'cli';
      if (!STATE.deleteCustomDate) {
        STATE.deleteCustomDate = new Date().toISOString().slice(0, 10);
      }

      const radios = document.querySelectorAll('input[name="chatDeleteMode"]');
      radios.forEach((radio) => {
        radio.checked = radio.value === STATE.deleteMode;
      });
      const agePreset = document.getElementById('deleteAgePreset');
      if (agePreset) agePreset.value = STATE.deleteAgePreset;
      const specificDate = document.getElementById('deleteSpecificDate');
      if (specificDate) specificDate.value = STATE.deleteCustomDate;
      const keepCount = document.getElementById('deleteKeepCount');
      if (keepCount) keepCount.value = STATE.deleteKeepCount;

      const titleEl = document.getElementById('chatDeleteModalTitle');
      const subtitleEl = document.getElementById('chatDeleteModalSubtitle');
      const applyBtn = document.getElementById('chatDeleteApplyBtn');
      const keepLastLabel = document.getElementById('chatDeleteKeepLastLabel');
      const allLabel = document.getElementById('chatDeleteAllLabel');
      if (titleEl) titleEl.textContent = isCli ? 'Delete CLI sessions from view' : 'Delete chats from view';
      if (subtitleEl) subtitleEl.textContent = isCli
        ? 'This hides CLI sessions locally in your browser (from the CLI tab). It does not modify session-store.db.'
        : 'This hides chats locally in your browser (from the Chats tab). It does not delete raw debug logs.';
      if (applyBtn) applyBtn.textContent = isCli ? 'Delete selected CLI sessions' : 'Delete selected chats';
      if (allLabel) allLabel.textContent = isCli ? 'Delete all visible CLI sessions' : 'Delete all visible chats';
      if (keepLastLabel) keepLastLabel.textContent = isCli ? 'sessions' : 'chats';

      updateChatDeletePreview();
      document.getElementById('chatDeleteModalBackdrop').classList.add('open');
    }

    export function closeChatDeleteModal(event) {
      if (event && event.target && event.target !== document.getElementById('chatDeleteModalBackdrop')) return;
      document.getElementById('chatDeleteModalBackdrop').classList.remove('open');
    }

    export async function exportSessionToJson(sessionId) {
      const meta = (APP_DATA.sessions || []).find((s) => s.id === sessionId);
      const safeName = (meta?.title || 'chat').replace(/[^a-zA-Z0-9._-]/g, '_').slice(0, 40);
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      let exportData;
      try {
        // The full chat detail lives in the on-demand full-session cache file.
        const payload = await fetchFullSession(sessionId);
        exportData = payload.session;
      } catch (err) {
        // Fall back to the compact summary if the full payload cannot be
        // loaded (e.g. this static export has no live server to fetch
        // from). Mark it so the exported JSON doesn't silently look like a
        // full per-call export when it's actually just the summary row.
        exportData = meta ? { ...meta, _exportNote: 'Full per-call chat detail was unavailable (no live dashboard server); this is the compact session summary only.' } : null;
      }
      if (!exportData) return;
      const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `chat-${safeName}-${ts}.json`;
      a.click();
      URL.revokeObjectURL(url);
    }

    export function openModelCompareModal(sessionId) {
      const session = APP_DATA.sessions.find((s) => s.id === sessionId);
      if (!session) return;
      const totals = sessionDisplayTotals(session);
      const inputTokens = totals.input || 0;
      const cachedTokens = totals.cached || 0;
      const outputTokens = totals.output || 0;
      const actualModel = session.model || 'unknown';
      const actualCost = totals.cost || 0;

      document.getElementById('modelCompareModalTitle').textContent = 'Model cost comparison';
      document.getElementById('modelCompareModalSubtitle').textContent = session.title + ' · ' + formatInteger(inputTokens) + ' input · ' + formatInteger(outputTokens) + ' output tokens (' + tokenModeLabel() + ')';

      // No cache-write argument: VS Code chat telemetry exposes no cache-write
      // counter, so there is no count to price. Passing nothing keeps those
      // tokens inside the uncached remainder, which is the closest available
      // approximation - see the caveat rendered below.
      const rows = Object.entries(PRICING_TABLE).map(([model, pricing]) => ({
        model,
        cost: calcModelCost(inputTokens, cachedTokens, outputTokens, pricing),
        pricing,
      })).sort((a, b) => a.cost - b.cost);

      const minCost = rows[0]?.cost || 0;

      document.getElementById('modelCompareModalContent').innerHTML = `
        <div class="note small" style="margin-bottom:12px">Estimated cost if this chat's ${escapeHtml(tokenModeLabel())} token usage (<strong>${formatInteger(inputTokens)}</strong> input, <strong>${formatInteger(cachedTokens)}</strong> cached, <strong>${formatInteger(outputTokens)}</strong> output) was processed by each model. Assumes same cache hit pattern.</div>
        <div class="note small" style="margin-bottom:12px">Chat telemetry reports no cache-write counter, so cache writes are priced here at each model's input rate rather than its (usually higher) cache-write rate. For models that charge a cache-write premium — Anthropic bills 1.25× input — these figures are a lower bound. Copilot CLI sessions do report the counter, so the CLI tab's costs come straight from what GitHub charged and need no such assumption.</div>
        <div style="overflow-x:auto">
        <table>
          <thead><tr>
            <th>Model</th>
            <th class="num">Input cr/M</th>
            <th class="num">Cached cr/M</th>
            <th class="num">Output cr/M</th>
            <th class="num">Est. AI credits</th>
            <th class="num">vs actual</th>
          </tr></thead>
          <tbody>
            ${rows.map((row) => {
              const isActual = row.model === actualModel;
              const delta = row.cost - actualCost;
              const isCheapest = Math.abs(row.cost - minCost) < 0.000001;
              return `<tr style="${isActual ? 'background:rgba(88,166,255,0.08);border-left:2px solid var(--blue)' : ''}">
                <td><strong style="${isCheapest ? 'color:var(--green)' : ''}">${escapeHtml(row.model)}</strong>${isActual ? ' <span class="badge chat" style="font-size:0.65rem;padding:2px 6px">current</span>' : ''}${isCheapest ? ' <span class="badge mode-read" style="font-size:0.65rem;padding:2px 6px">cheapest</span>' : ''}</td>
                <td class="num">${formatCost(row.pricing.input)}</td>
                <td class="num">${formatCost(row.pricing.cached)}</td>
                <td class="num">${formatCost(row.pricing.output)}</td>
                <td class="num"><strong style="color:var(--teal)">${formatCost(row.cost)}</strong></td>
                <td class="num" style="color:${delta < -0.0001 ? 'var(--green)' : delta > 0.0001 ? 'var(--red)' : 'var(--muted)'}">${isActual ? '—' : (delta >= 0 ? '+' : '') + formatCost(Math.abs(delta))}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
        </div>`;

      document.getElementById('modelCompareModalBackdrop').classList.add('open');
    }

    export function closeModelCompareModal(event) {
      if (event && event.target && event.target !== document.getElementById('modelCompareModalBackdrop')) return;
      document.getElementById('modelCompareModalBackdrop').classList.remove('open');
    }

    // Global Escape-to-close: any open modal backdrop (genai/full-chat/file/delete/model-compare)
    // is dismissed on Escape, regardless of which tab (Chats or CLI) opened it, since CLI reuses
    // the fullChatModalBackdrop/modelCompareModalBackdrop elements.
    const MODAL_BACKDROP_IDS = [
      'genaiModalBackdrop',
      'fullChatModalBackdrop',
      'fileModalBackdrop',
      'chatDeleteModalBackdrop',
      'modelCompareModalBackdrop',
    ];
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape' && event.key !== 'Esc') return;
      MODAL_BACKDROP_IDS.forEach((id) => {
        const el = document.getElementById(id);
        if (el && el.classList.contains('open')) el.classList.remove('open');
      });
    });
