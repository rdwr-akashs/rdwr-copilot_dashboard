#!/usr/bin/env python3
"""Apply all dashboard improvements - version 2."""

with open('dashboard_core.py', 'r') as f:
    content = f.read()

# ============================================================
# 1. Replace renderToolsSubtab (from tools_start to sort_files_start)
# ============================================================
tools_start = content.find('    function renderToolsSubtab() {')
sort_files_start = content.find('    function sortFiles()', tools_start)
assert tools_start > 0 and sort_files_start > tools_start

new_tools = '''    function renderToolsSubtab() {
      const tools = [...APP_DATA.analysis.tools];
      const sortKey = STATE.toolSortKey || 'cost';
      const sortDir = STATE.toolSortDir || 'desc';
      tools.sort((a, b) => {
        const av = a[sortKey]; const bv = b[sortKey];
        const dir = sortDir === 'desc' ? -1 : 1;
        if (typeof av === 'string') return String(av).localeCompare(String(bv)) * dir;
        return ((Number(av || 0) - Number(bv || 0)) * dir);
      });
      function toolSortArrow(key) {
        if ((STATE.toolSortKey || 'cost') !== key) return '<span style="opacity:.4">\\u2195</span>';
        return (STATE.toolSortDir || 'desc') === 'desc' ? '\\u2193' : '\\u2191';
      }
      function thBtn(key, line1, line2) {
        return `<th class="num"><button type="button" onclick="setToolSort('${key}')" style="all:unset;cursor:pointer;color:inherit;text-align:right;display:block;width:100%"><span style="display:block;line-height:1.2;font-size:.72rem">${line1}</span><span style="display:block;line-height:1.2;font-size:.72rem">${line2} ${toolSortArrow(key)}</span></button></th>`;
      }
      const totals = { count: 0, errors: 0, durationMs: 0, input: 0, output: 0, cached: 0, cost: 0, payloadTokens: 0 };
      tools.forEach(t => { totals.count += t.count; totals.errors += t.errors; totals.durationMs += t.durationMs; totals.input += t.input; totals.output += t.output; totals.cached += t.cached; totals.cost += t.cost; totals.payloadTokens += t.payloadTokens; });
      return `
        <section class="panel">
          <h2 class="section-title">Tool impact</h2>
          <div class="section-subtitle"><strong>Payload</strong> = approx token size of tool input + output text, used as weight when splitting prompt growth.</div>
          <div style="overflow-x:auto">
          <table>
            <thead><tr>
              <th><button type="button" onclick="setToolSort('name')" style="all:unset;cursor:pointer;color:inherit">Tool ${toolSortArrow('name')}</button></th>
              ${thBtn('count', 'Calls', '')}
              ${thBtn('avgDurationMs', 'Avg', 'Duration')}
              ${thBtn('avgInput', 'Avg', 'Input')}
              ${thBtn('avgOutput', 'Avg', 'Output')}
              ${thBtn('avgCached', 'Avg', 'Cached')}
              ${thBtn('avgCost', 'Avg', 'Cost')}
              ${thBtn('input', 'Total', 'Input')}
              ${thBtn('output', 'Total', 'Output')}
              ${thBtn('cached', 'Total', 'Cached')}
              ${thBtn('cost', 'Total', 'Cost')}
              ${thBtn('avgPayloadTokens', 'Avg', 'Payload')}
            </tr></thead>
            <tbody>
              ${tools.map(row => `<tr>
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
              </tr>`).join('')}
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
          </div>
        </section>`;
    }

'''
content = content[:tools_start] + new_tools + content[sort_files_start:]
print("1. renderToolsSubtab replaced")

# ============================================================
# 2. Replace renderFilesSubtab (from files_start to insights_start)
# ============================================================
files_start = content.find('    function renderFilesSubtab() {')
insights_start = content.find('    function renderInsightsSubtab() {')
assert files_start > 0 and insights_start > files_start

new_files = '''    function shortenPath(path, maxLen) {
      maxLen = maxLen || 50;
      if (!path || path.length <= maxLen) return escapeHtml(path || '');
      const parts = path.split('/');
      if (parts.length <= 3) return escapeHtml(path.slice(0, maxLen/2) + '\\u2026' + path.slice(-(maxLen/2)));
      const head = parts.slice(0, 2).join('/');
      const tail = parts.slice(-2).join('/');
      return escapeHtml(head + '/\\u2026/' + tail);
    }

    function renderFilesSubtab() {
      const rows = sortFiles();
      const columns = [
        ['name', 'File'],
        ['readCount', 'Reads'],
        ['editCount', 'Edits'],
        ['avgInput', 'Avg Input'],
        ['avgOutput', 'Avg Output'],
        ['avgCached', 'Avg Cached'],
        ['input', 'Total Input'],
        ['output', 'Total Output'],
        ['cached', 'Total Cached'],
        ['payloadTokens', 'Payload'],
        ['cost', 'Cost'],
      ];
      const fileTotals = { readCount: 0, editCount: 0, input: 0, output: 0, cached: 0, cost: 0, payloadTokens: 0 };
      rows.forEach(r => { fileTotals.readCount += r.readCount; fileTotals.editCount += r.editCount; fileTotals.input += r.input; fileTotals.output += r.output; fileTotals.cached += r.cached; fileTotals.cost += r.cost; fileTotals.payloadTokens += r.payloadTokens; });
      const totalOps = fileTotals.readCount + fileTotals.editCount;
      return `
        <section class="panel">
          <h2 class="section-title">File activity</h2>
          <div class="section-subtitle">Click a file to see per-invocation timeline. Long paths shortened; hover for full path.</div>
          <div style="overflow-x:auto">
          <table>
            <thead>
              <tr>
                ${columns.map(([key, label]) => `<th class="${key !== 'name' ? 'num' : ''}"><button type="button" onclick="setFileSort('${key}')" style="all:unset;cursor:pointer;color:inherit">${escapeHtml(label)} ${sortArrow(key)}</button></th>`).join('')}
              </tr>
            </thead>
            <tbody>
              ${rows.map((row) => `<tr class="clickable-row" onclick="openFileModal('${encodeURIComponent(row.path)}')">
                <td><div title="${escapeHtml(row.path)}"><strong>${escapeHtml(row.name)}</strong><div class="note small">${shortenPath(row.shortPath, 45)}</div></div></td>
                <td class="num">${formatInteger(row.readCount)}</td>
                <td class="num">${formatInteger(row.editCount)}</td>
                <td class="num"><span class="value input">${formatInteger(row.avgInput)}</span></td>
                <td class="num"><span class="value output">${formatInteger(row.avgOutput)}</span></td>
                <td class="num"><span class="value cached">${formatInteger(row.avgCached)}</span></td>
                <td class="num"><span class="value input">${formatCompact(row.input)}</span></td>
                <td class="num"><span class="value output">${formatCompact(row.output)}</span></td>
                <td class="num"><span class="value cached">${formatCompact(row.cached)}</span></td>
                <td class="num">${formatInteger(row.payloadTokens)}</td>
                <td class="num"><span class="value cost">${formatCost(row.cost)}</span></td>
              </tr>`).join('')}
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
                <td class="num"><span class="value cost">${formatCost(fileTotals.cost)}</span></td>
              </tr>
            </tbody>
          </table>
          </div>
        </section>`;
    }

'''
content = content[:files_start] + new_files + content[insights_start:]
print("2. renderFilesSubtab replaced")

# ============================================================
# 3. Replace renderInsightsSubtab with collapsible version
# ============================================================
insights_start = content.find('    function renderInsightsSubtab() {')
telemetry_start = content.find('    function renderTelemetrySubtab() {')
assert insights_start > 0 and telemetry_start > insights_start

new_insights = '''    function renderInsightsSubtab() {
      const summary = APP_DATA.summary;
      const analysis = APP_DATA.analysis;
      const overheadCards = Object.entries(analysis.overhead).map(([name, block]) => `
        <div class="insight-card">
          <h4>${escapeHtml(name.replace(/_/g, ' '))}</h4>
          <div class="note small">Estimated prompt-growth bucket</div>
          <div class="pill-list" style="margin-top:10px;">
            <span class="pill">Input ${formatInteger(block.input)}</span>
            <span class="pill">Output ${formatInteger(block.output)}</span>
            <span class="pill">Cached ${formatInteger(block.cached)}</span>
            <span class="pill">Cost ${formatCost(block.cost)}</span>
          </div>
        </div>`).join('');
      const expensiveChats = analysis.topChats.map((chat) => `
        <div class="insight-card">
          <h4 title="${escapeHtml(chat.title)}">${escapeHtml(chat.title.length > 60 ? chat.title.slice(0,57) + '...' : chat.title)}</h4>
          <div class="note small">${escapeHtml((chat.sessionTitle||'').slice(0,40))} \\u00b7 ${escapeHtml(formatTimestamp(chat.timestamp))}</div>
          <div class="pill-list" style="margin-top:10px;">
            <span class="pill">${escapeHtml(chat.model)}</span>
            <span class="pill">Prompt ${formatInteger(chat.promptTokens)}</span>
            <span class="pill">Cached ${formatInteger(chat.cached)}</span>
            <span class="pill">Cost ${formatCost(chat.cost)}</span>
          </div>
        </div>`).join('');
      const slowestTools = analysis.slowestTools.map((tool) => `
        <div class="insight-card">
          <h4 title="${escapeHtml(tool.title)}">${escapeHtml(tool.title.length > 55 ? tool.title.slice(0,52) + '...' : tool.title)}</h4>
          <div class="note small">${escapeHtml((tool.sessionTitle||'').slice(0,40))} \\u00b7 ${escapeHtml(formatTimestamp(tool.timestamp))}</div>
          <div class="pill-list" style="margin-top:10px;">
            <span class="pill">${escapeHtml(tool.name)}</span>
            <span class="pill">${formatDuration(tool.durationMs)}</span>
            <span class="pill">Input ${formatInteger(tool.estimated.input)}</span>
            <span class="pill">${formatCost(tool.estimated.cost)}</span>
          </div>
        </div>`).join('');

      function collapsible(title, innerHtml, startOpen) {
        const openAttr = startOpen ? ' open' : '';
        return `<details class="panel collapsible-section" style="cursor:default"${openAttr}>
          <summary style="cursor:pointer;display:flex;align-items:center;gap:8px;user-select:none;padding:14px 18px">
            <span style="font-size:1.2rem;font-weight:700;width:22px;text-align:center;font-family:monospace" class="collapse-icon">${startOpen ? '\\u2212' : '+'}</span>
            <h2 class="section-title" style="margin:0">${title}</h2>
          </summary>
          <div style="padding:0 18px 18px">${innerHtml}</div>
        </details>`;
      }

      return `
        <div class="analysis-grid">
          ${collapsible('Interesting breakdowns', `
            <div class="insights-grid">
              <div class="insight-card">
                <h4>Top-level summary</h4>
                <ul class="help-list">
                  <li>${formatInteger(summary.sessionCount)} sessions</li>
                  <li>${formatInteger(summary.chatCallCount)} chat calls</li>
                  <li>${formatInteger(summary.toolCallCount)} tool calls</li>
                  <li>${formatPercent(summary.cacheHitRate)} cached share of billed prompt</li>
                  <li>${formatCost(summary.totals.cost)} total API-style spend</li>
                </ul>
              </div>
              ${overheadCards}
            </div>`, false)}
          ${collapsible('Expensive chats', `<div class="insights-grid">${expensiveChats}</div>`, false)}
          ${collapsible('Slowest tools', `<div class="insights-grid">${slowestTools}</div>`, false)}
        </div>`;
    }

'''
content = content[:insights_start] + new_insights + content[telemetry_start:]
print("3. renderInsightsSubtab replaced")

# ============================================================
# 4. Replace renderFileTimelineChart with per-invocation bars
# ============================================================
chart_start = content.find('    function renderFileTimelineChart(events) {')
open_file_modal = content.find('    function openFileModal(', chart_start)
assert chart_start > 0 and open_file_modal > chart_start

new_chart = '''    function renderFileTimelineChart(events) {
      const filtered = (events || []).filter((item) => (item.estimated_tokens?.cost || 0) > 0 || (item.estimated_tokens?.input || 0) + (item.estimated_tokens?.output || 0) + (item.estimated_tokens?.cached || 0) > 0);
      if (!filtered.length) {
        return '<div class="note">No non-zero activity captured for this file.</div>';
      }
      const width = 900;
      const height = 260;
      const padLeft = 50;
      const padRight = 24;
      const padTop = 20;
      const padBottom = 34;
      const innerWidth = width - padLeft - padRight;
      const innerHeight = height - padTop - padBottom;
      const maxVal = Math.max(...filtered.map(i => Math.max(i.estimated_tokens.input || 0, i.estimated_tokens.output || 0, i.estimated_tokens.cached || 0)), 1);
      const barGroupWidth = Math.min(40, Math.max(12, innerWidth / filtered.length * 0.75));
      const barWidth = barGroupWidth / 3;

      const bars = filtered.map((item, index) => {
        const x = padLeft + (filtered.length === 1 ? innerWidth / 2 : (innerWidth * index) / Math.max(1, filtered.length - 1));
        const inp = item.estimated_tokens.input || 0;
        const out = item.estimated_tokens.output || 0;
        const cch = item.estimated_tokens.cached || 0;
        const hInp = (inp / maxVal) * innerHeight;
        const hOut = (out / maxVal) * innerHeight;
        const hCch = (cch / maxVal) * innerHeight;
        const baseY = padTop + innerHeight;
        const tooltip = `${escapeHtml(item.tool)} \\u00b7 ${formatTimestamp(item.ts)}\\nInput: ${formatInteger(inp)} \\u00b7 Output: ${formatInteger(out)} \\u00b7 Cached: ${formatInteger(cch)}\\nCost: ${formatCost(item.estimated_tokens.cost || 0)}`;
        return `<rect x="${x - barGroupWidth/2}" y="${baseY - hInp}" width="${barWidth}" height="${Math.max(1,hInp)}" fill="rgba(88,166,255,.6)"><title>${tooltip}</title></rect>` +
               `<rect x="${x - barGroupWidth/2 + barWidth}" y="${baseY - hOut}" width="${barWidth}" height="${Math.max(1,hOut)}" fill="rgba(255,155,80,.6)"><title>${tooltip}</title></rect>` +
               `<rect x="${x - barGroupWidth/2 + barWidth*2}" y="${baseY - hCch}" width="${barWidth}" height="${Math.max(1,hCch)}" fill="rgba(63,185,80,.6)"><title>${tooltip}</title></rect>`;
      }).join('');

      return `
        <div class="chart-card">
          <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
            <line x1="${padLeft}" y1="${padTop + innerHeight}" x2="${width - padRight}" y2="${padTop + innerHeight}" stroke="rgba(255,255,255,.18)" />
            <line x1="${padLeft}" y1="${padTop}" x2="${padLeft}" y2="${padTop + innerHeight}" stroke="rgba(255,255,255,.18)" />
            ${bars}
          </svg>
          <div class="chart-legend">
            <span class="legend-item"><span class="legend-swatch" style="background: rgba(88,166,255,.6);"></span>Input tokens</span>
            <span class="legend-item"><span class="legend-swatch" style="background: rgba(255,155,80,.6);"></span>Output tokens</span>
            <span class="legend-item"><span class="legend-swatch" style="background: rgba(63,185,80,.6);"></span>Cached tokens</span>
          </div>
          <div class="note" style="margin-top:8px">Each bar group = one tool invocation on this file. Hover for details.</div>
        </div>`;
    }

'''
content = content[:chart_start] + new_chart + content[open_file_modal:]
print("4. renderFileTimelineChart replaced")

# ============================================================
# 5. Fix setSearch to use debounce
# ============================================================
old_search = '    function setSearch(value) {\n      STATE.search = value;\n      STATE.page = 1;\n      renderApp();\n    }'
new_search = '    let _searchTimer = null;\n    function setSearch(value) {\n      STATE.search = value;\n      STATE.page = 1;\n      if (_searchTimer) clearTimeout(_searchTimer);\n      _searchTimer = setTimeout(() => renderApp(), 300);\n    }'
assert old_search in content, f"Could not find setSearch"
content = content.replace(old_search, new_search)
print("5. setSearch debounce added")

# ============================================================
# 6. Add setToolSort after setFileSort
# ============================================================
old_file_sort = "    function setFileSort(key) {\n      if (STATE.fileSortKey === key) {\n        STATE.fileSortDir = STATE.fileSortDir === 'desc' ? 'asc' : 'desc';\n      } else {\n        STATE.fileSortKey = key;\n        STATE.fileSortDir = key === 'name' ? 'asc' : 'desc';\n      }\n      renderApp();\n    }"
new_file_sort = old_file_sort + "\n\n    function setToolSort(key) {\n      if (STATE.toolSortKey === key) {\n        STATE.toolSortDir = (STATE.toolSortDir || 'desc') === 'desc' ? 'asc' : 'desc';\n      } else {\n        STATE.toolSortKey = key;\n        STATE.toolSortDir = key === 'name' ? 'asc' : 'desc';\n      }\n      renderApp();\n    }"
assert old_file_sort in content, "Could not find setFileSort"
content = content.replace(old_file_sort, new_file_sort)
print("6. setToolSort added")

# ============================================================
# 7. Update STATE to include toolSortKey/toolSortDir
# ============================================================
old_state = "      fileSortKey: 'cost',\n      fileSortDir: 'desc',\n    };"
new_state = "      fileSortKey: 'cost',\n      fileSortDir: 'desc',\n      toolSortKey: 'cost',\n      toolSortDir: 'desc',\n    };"
assert old_state in content, "Could not find STATE closing"
content = content.replace(old_state, new_state)
print("7. STATE updated")

# ============================================================
# 8. Update renderSession to show totals and duration
# ============================================================
render_session_start = content.find('    function renderSession(session, sessionIndex) {')
render_pagination_start = content.find('    function renderPagination(', render_session_start)
assert render_session_start > 0 and render_pagination_start > render_session_start

new_session = '''    function renderSession(session, sessionIndex) {
      const dur = session.duration_ms || 0;
      const durLabel = dur > 60000 ? `${(dur / 60000).toFixed(0)}m` : dur > 1000 ? `${(dur / 1000).toFixed(0)}s` : dur ? `${dur.toFixed(0)}ms` : '\\u2014';
      return `
        <details class="session-card">
          <summary class="session-summary-row">
            <div class="title-col">
              <div class="title-line">
                <span class="badge model">${escapeHtml(session.model || 'unknown')}</span>
                <span class="title-text">${escapeHtml(session.title)}</span>
              </div>
              <div class="subtext">${escapeHtml(formatTimestamp(session.timestamp))} \\u00b7 ${formatInteger(session.chat_count)} calls \\u00b7 ${formatInteger(session.tool_count)} tools \\u00b7 ${durLabel}</div>
            </div>
            ${renderStatCell('Total Input', formatInteger(session.totals.input), 'input')}
            ${renderStatCell('Total Output', formatInteger(session.totals.output), 'output')}
            ${renderStatCell('Cached', formatInteger(session.totals.cached), 'cached', true)}
            ${renderStatCell('Duration', durLabel)}
            ${renderStatCell('Cost', formatCost(session.totals.cost), 'cost')}
          </summary>
          <div class="session-body">
            ${renderSessionMeta(session)}
            <div class="timeline">${session.events.map((event) => renderEvent(event, sessionIndex)).join('')}</div>
          </div>
        </details>`;
    }

'''
content = content[:render_session_start] + new_session + content[render_pagination_start:]
print("8. renderSession replaced")

# ============================================================
# 9. Update renderSessionMeta
# ============================================================
session_meta_start = content.find('    function renderSessionMeta(session) {')
next_after_meta = content.find('    function renderContextBreakdown(', session_meta_start)
assert session_meta_start > 0 and next_after_meta > session_meta_start

new_meta = '''    function renderSessionMeta(session) {
      const dur = session.duration_ms || 0;
      const durLabel = dur > 60000 ? `${(dur / 60000).toFixed(1)}min` : dur > 1000 ? `${(dur / 1000).toFixed(0)}s` : '\\u2014';
      return `
        <div class="session-meta">
          <div class="meta-card"><div class="label">Primary model</div><div class="value">${escapeHtml(session.model || 'unknown')}</div></div>
          <div class="meta-card"><div class="label">Duration</div><div class="value">${durLabel}</div></div>
          <div class="meta-card"><div class="label">Total input</div><div class="value input">${formatInteger(session.totals.input)}</div></div>
          <div class="meta-card"><div class="label">Total output</div><div class="value output">${formatInteger(session.totals.output)}</div></div>
          <div class="meta-card"><div class="label">Total cached</div><div class="value cached">${formatInteger(session.totals.cached)}</div></div>
          <div class="meta-card"><div class="label">Total cost</div><div class="value cost">${formatCost(session.totals.cost)}</div></div>
          <div class="meta-card"><div class="label">Cache hit rate</div><div class="value cached">${formatPercent(session.cache_hit_rate)}</div></div>
          <div class="meta-card"><div class="label">Peak prompt</div><div class="value">${formatInteger(session.peak_prompt_tokens)}</div></div>
        </div>`;
    }

'''
content = content[:session_meta_start] + new_meta + content[next_after_meta:]
print("9. renderSessionMeta replaced")

# ============================================================
# 10. Fix file modal stats to remove "est."
# ============================================================
old_modal_stats = '''      document.getElementById('fileModalStats').innerHTML = `
        <div class="meta-card"><div class="label">Reads</div><div class="value">${formatInteger(file.readCount)}</div></div>
        <div class="meta-card"><div class="label">Edits</div><div class="value">${formatInteger(file.editCount)}</div></div>
        <div class="meta-card"><div class="label">Input est.</div><div class="value input">${formatInteger(file.input)}</div></div>
        <div class="meta-card"><div class="label">Output est.</div><div class="value output">${formatInteger(file.output)}</div></div>
        <div class="meta-card"><div class="label">Cached est.</div><div class="value cached">${formatInteger(file.cached)}</div></div>
        <div class="meta-card"><div class="label">Cost est.</div><div class="value cost">${formatCost(file.cost)}</div></div>`;'''

new_modal_stats = '''      const totalFileOps = file.readCount + file.editCount;
      document.getElementById('fileModalStats').innerHTML = `
        <div class="meta-card"><div class="label">Reads</div><div class="value">${formatInteger(file.readCount)}</div></div>
        <div class="meta-card"><div class="label">Edits</div><div class="value">${formatInteger(file.editCount)}</div></div>
        <div class="meta-card"><div class="label">Total Input</div><div class="value input">${formatInteger(file.input)}</div></div>
        <div class="meta-card"><div class="label">Total Output</div><div class="value output">${formatInteger(file.output)}</div></div>
        <div class="meta-card"><div class="label">Total Cached</div><div class="value cached">${formatInteger(file.cached)}</div></div>
        <div class="meta-card"><div class="label">Avg Input</div><div class="value input">${formatInteger(totalFileOps ? file.input / totalFileOps : 0)}</div></div>
        <div class="meta-card"><div class="label">Avg Cost</div><div class="value cost">${formatCost(totalFileOps ? file.cost / totalFileOps : 0)}</div></div>
        <div class="meta-card"><div class="label">Total Cost</div><div class="value cost">${formatCost(file.cost)}</div></div>`;'''

assert old_modal_stats in content, "Could not find file modal stats"
content = content.replace(old_modal_stats, new_modal_stats)
print("10. File modal stats updated")

# ============================================================
# 11. Fix file modal table headers
# ============================================================
old_headers = '<thead><tr><th>Time</th><th>Mode</th><th>Tool</th><th class="num">Input est.</th><th class="num">Output est.</th><th class="num">Cached est.</th><th class="num">Cost est.</th></tr></thead>'
new_headers = '<thead><tr><th>Time</th><th>Mode</th><th>Tool</th><th class="num">Input</th><th class="num">Output</th><th class="num">Cached</th><th class="num">Cost</th></tr></thead>'
assert old_headers in content, "Could not find file table headers"
content = content.replace(old_headers, new_headers)
print("11. File table headers fixed")

# ============================================================
# 12. Add search input id for focus preservation
# ============================================================
old_input = 'placeholder="Search by chat title or model\\u2026" value="${escapeHtml(STATE.search)}" oninput="setSearch(this.value)"'
if old_input in content:
    content = content.replace(old_input, 'id="chatSearchInput" ' + old_input)
    print("12. Search input id added")
else:
    # Try ASCII ellipsis
    old_input2 = 'placeholder="Search by chat title or model\xe2\x80\xa6" value="${escapeHtml(STATE.search)}" oninput="setSearch(this.value)"'
    if old_input2 in content:
        content = content.replace(old_input2, 'id="chatSearchInput" ' + old_input2)
        print("12. Search input id added (utf8)")
    else:
        # Search for it more loosely
        import re
        m = re.search(r'placeholder="Search by chat title or model[^"]*" value="\$\{escapeHtml\(STATE\.search\)\}" oninput="setSearch\(this\.value\)"', content)
        if m:
            content = content[:m.start()] + 'id="chatSearchInput" ' + content[m.start():]
            print("12. Search input id added (regex)")
        else:
            print("12. SKIPPED - search input not found")

# ============================================================
# 13. Update renderApp to preserve search focus
# ============================================================
old_render = '    function renderApp() {\n      const app = document.getElementById(\'app\');\n      const pages = pagedSessions();\n      if (STATE.page > pages.pageCount) STATE.page = pages.pageCount;\n      app.innerHTML = `\n        ${renderHeader()}\n        <section class="tab-panel ${STATE.activeTab === \'chats\' ? \'active\' : \'\'}">${renderChatsTab()}</section>\n        <section class="tab-panel ${STATE.activeTab === \'analysis\' ? \'active\' : \'\'}">${renderAnalysisTab()}</section>`;\n    }'

new_render = '''    function renderApp() {
      const app = document.getElementById('app');
      const pages = pagedSessions();
      if (STATE.page > pages.pageCount) STATE.page = pages.pageCount;
      const activeEl = document.activeElement;
      const hadSearchFocus = activeEl && activeEl.id === 'chatSearchInput';
      const selStart = hadSearchFocus ? activeEl.selectionStart : null;
      const selEnd = hadSearchFocus ? activeEl.selectionEnd : null;
      app.innerHTML = `
        ${renderHeader()}
        <section class="tab-panel ${STATE.activeTab === 'chats' ? 'active' : ''}">${renderChatsTab()}</section>
        <section class="tab-panel ${STATE.activeTab === 'analysis' ? 'active' : ''}">${renderAnalysisTab()}</section>`;
      if (hadSearchFocus) {
        const newInput = document.getElementById('chatSearchInput');
        if (newInput) {
          newInput.focus();
          if (selStart !== null) newInput.setSelectionRange(selStart, selEnd);
        }
      }
    }'''

assert old_render in content, "Could not find renderApp"
content = content.replace(old_render, new_render)
print("13. renderApp focus preservation added")

# ============================================================
# 14. Update legend
# ============================================================
old_legend = 'Chat rows show the latest prompt size, peak prompt size, and total billed cost for the whole chat. Inside each chat, every model call shows the actual prompt size for that call plus the diff from the previous call.'
new_legend = 'Each row shows total billed tokens and cost for the chat session. Expand for per-call breakdown. Token counts follow OTel gen_ai conventions: input includes cached portion.'
if old_legend in content:
    content = content.replace(old_legend, new_legend)
    print("14. Legend updated")
else:
    print("14. SKIPPED - legend not found")

# ============================================================
# 15. Add CSS for collapsible sections
# ============================================================
css_marker = '    .insights-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }}'
if css_marker in content:
    extra_css = '''
    details.collapsible-section > summary {{ list-style: none; }}
    details.collapsible-section > summary::-webkit-details-marker {{ display: none; }}
    details.collapsible-section {{ border-radius: 18px; }}
    .insight-card h4 {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }}'''
    content = content.replace(css_marker, css_marker + extra_css)
    print("15. Collapsible CSS added")
else:
    print("15. SKIPPED - CSS marker not found")

# ============================================================
# Write result
# ============================================================
with open('dashboard_core.py', 'w') as f:
    f.write(content)

print(f"\n=== All replacements applied! File size: {len(content)} bytes ===")
