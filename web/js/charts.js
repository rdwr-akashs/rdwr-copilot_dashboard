import { monthlyTrendMetricConfig } from './aggregate.js';
import { buildOverheadBreakdown, escapeHtml, formatCompact, formatCost, formatInteger, summaryDisplayTotals } from './format.js';
import { tokenModeLabel, isBilledMode } from './state.js';


    export function renderMonthlyTrendChart(rows, metricKey) {
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
        const y = padTop + innerHeight - (innerHeight * ratio);
        const label = metric.format(maxValue * ratio);
        return `
          <line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}"  stroke="var(--overlay-08)" />
          <text x="${padLeft - 8}" y="${y + 4}" fill="var(--muted)" font-size="12" text-anchor="end">${escapeHtml(label)}</text>`;
      }).join('');

      const bars = rows.map((row, index) => {
        const value = Number(metric.value(row) || 0);
        const x = padLeft + step * index + step / 2;
        const barHeight = (value / maxValue) * innerHeight;
        const y = padTop + innerHeight - barHeight;
        const month = row.monthKey || row.label || `M${index + 1}`;
        const tooltip = `${row.label || month}
${metric.label}: ${metric.format(value)}
Sessions: ${formatInteger(row.sessionCount || 0)} · Chats: ${formatInteger(row.chatCallCount || 0)} · Tools: ${formatInteger(row.toolCallCount || 0)}`;
        return `
          <rect x="${x - barWidth / 2}" y="${y}" width="${barWidth}" height="${Math.max(1, barHeight)}" rx="6" fill="${metric.color}" opacity="0.82"><title>${escapeHtml(tooltip)}</title></rect>
          <text x="${x}" y="${height - 16}" fill="var(--muted)" font-size="12" text-anchor="middle">${escapeHtml(month)}</text>`;
      }).join('');

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

    export function renderGlobalTokenPieChart(summary, analysis) {
      const totals = summaryDisplayTotals(summary);
      const totalInput = Number(totals.input || 0);
      if (!totalInput) return '<div class="note">No token data available.</div>';

      const overhead = analysis.overhead || {};
      const categories = buildOverheadBreakdown(overhead, totalInput);
      const cats = categories.filter((c) => c.input > 0);

      // SVG pie chart
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
      }).join('');

      const legend = categories.map((cat) => {
        return `
          <tr>
            <td><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:${cat.color};margin-right:8px;vertical-align:middle"></span>${escapeHtml(cat.label)}</td>
            <td class="num">${formatInteger(cat.input)}</td>
            <td class="num">${cat.pct.toFixed(1)}%</td>
            <td class="num">${cat.cost > 0 ? formatCost(cat.cost) : '—'}</td>
          </tr>`;
      }).join('');

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

    // Additive: a Chat-vs-CLI stacked-bar cost/token trend chart over
    // APP_DATA.unified.daily/monthly rows, for the Overview tab
    // (tab-overview.js). Reuses the same SVG-bar-chart shape as
    // renderMonthlyTrendChart above rather than inventing a new approach.
    export function renderUnifiedTrendChart(rows, metricKey) {
      if (!rows || !rows.length) {
        return '<div class="note">No usage data available for the selected filters.</div>';
      }
      const metric = (metricKey === 'tokens')
        ? { label: 'Total tokens', color: 'var(--blue)', value: (block) => Number(block.input || 0) + Number(block.output || 0), format: formatInteger }
        : { label: 'Cost', color: 'var(--teal)', value: (block) => Number(block.cost || 0), format: formatCost };
      const blockKey = isBilledMode() ? 'billed' : 'attributed';

      const points = rows.map((row) => {
        const key = row.dayKey || row.monthKey || '';
        const chat = (row.bySource && row.bySource.chat && row.bySource.chat[blockKey]) || null;
        const cli = (row.bySource && row.bySource.cli && row.bySource.cli[blockKey]) || null;
        return {
          key,
          chat: chat ? metric.value(chat) : 0,
          cli: cli ? metric.value(cli) : 0,
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
        const y = padTop + innerHeight - (innerHeight * ratio);
        const label = metric.format(maxValue * ratio);
        return `
          <line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}" stroke="var(--overlay-08)" />
          <text x="${padLeft - 8}" y="${y + 4}" fill="var(--muted)" font-size="12" text-anchor="end">${escapeHtml(label)}</text>`;
      }).join('');

      const bars = points.map((point, index) => {
        const x = padLeft + step * index + step / 2;
        const chatHeight = maxValue ? (point.chat / maxValue) * innerHeight : 0;
        const cliHeight = maxValue ? (point.cli / maxValue) * innerHeight : 0;
        const cliY = padTop + innerHeight - cliHeight;
        const chatY = cliY - chatHeight;
        const tooltip = `${point.key}\nChat ${metric.label}: ${metric.format(point.chat)}\nCLI ${metric.label}: ${metric.format(point.cli)}`;
        return `
          <rect x="${x - barWidth / 2}" y="${cliY}" width="${barWidth}" height="${Math.max(0, cliHeight)}" fill="var(--yellow)" opacity="0.85"><title>${escapeHtml(tooltip)}</title></rect>
          <rect x="${x - barWidth / 2}" y="${Math.max(padTop, chatY)}" width="${barWidth}" height="${Math.max(0, chatHeight)}" fill="${metric.color}" opacity="0.85"><title>${escapeHtml(tooltip)}</title></rect>
          <text x="${x}" y="${height - 16}" fill="var(--muted)" font-size="11" text-anchor="middle">${escapeHtml(point.key.slice(5) || point.key)}</text>`;
      }).join('');

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
