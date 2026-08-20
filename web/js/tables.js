import { changePage, setPageSize } from './actions.js';
import { escapeHtml, formatInteger } from './format.js';
import { STATE } from './state.js';


    export function renderStatCell(label, value, className = '', hideMobile = false) {
      return `
        <div class="stat-col ${hideMobile ? 'hide-mobile' : ''}">
          <div class="label">${label}</div>
          <div class="value ${className}">${value}</div>
        </div>`;
    }

    export function renderPagination(allCount, pageCount) {
      return `
        <div class="pagination">
          <div class="note">Showing ${allCount ? `${(STATE.page - 1) * STATE.pageSize + 1}-${Math.min(STATE.page * STATE.pageSize, allCount)}` : '0'} of ${formatInteger(allCount)} chats</div>
          <div class="pagination-controls">
            <label class="note">Per page</label>
            <select onchange="setPageSize(this.value)">
              ${[5, 10, 20, 50, 100].map((size) => `<option value="${size}" ${STATE.pageSize === size ? 'selected' : ''}>${size}</option>`).join('')}
            </select>
            <button type="button" onclick="changePage(-1)" ${STATE.page <= 1 ? 'disabled' : ''}>Prev</button>
            <span class="note">Page ${STATE.page} / ${pageCount}</span>
            <button type="button" onclick="changePage(1)" ${STATE.page >= pageCount ? 'disabled' : ''}>Next</button>
          </div>
        </div>`;
    }

    export function renderTable(columns, rows, options = {}) {
      const rowRenderer = options.rowRenderer || ((row) => `<tr>${columns.map((column) => `<td class="${column.numeric ? 'num' : ''}">${column.render(row)}</td>`).join('')}</tr>`);
      const exportId = options.exportId;
      if (exportId) registerTableExport(exportId, columns, rows, options.exportFilename);
      return `
        <div class="panel">
          ${exportId ? renderCsvExportButton(exportId) : ''}
          <table>
            <thead>
              <tr>${columns.map((column) => `<th class="${column.numeric ? 'num' : ''}">${column.header ? column.header() : escapeHtml(column.title)}</th>`).join('')}</tr>
            </thead>
            <tbody>${rows.map((row) => rowRenderer(row)).join('')}</tbody>
          </table>
        </div>`;
    }

    export function sortRows(rows, sortKey, sortDir) {
      const dir = sortDir === 'desc' ? -1 : 1;
      rows.sort((a, b) => {
        const av = a[sortKey]; const bv = b[sortKey];
        if (typeof av === 'string' || typeof bv === 'string') return String(av || '').localeCompare(String(bv || '')) * dir;
        return (Number(av || 0) - Number(bv || 0)) * dir;
      });
      return rows;
    }

    export function sortFiles(sourceRows) {
      const rows = [...(sourceRows || [])];
      rows.sort((a, b) => {
        const key = STATE.fileSortKey;
        const dir = STATE.fileSortDir === 'desc' ? -1 : 1;
        const av = a[key];
        const bv = b[key];
        if (typeof av === 'string' || typeof bv === 'string') {
          return String(av).localeCompare(String(bv)) * dir;
        }
        return ((Number(av || 0) - Number(bv || 0)) * dir);
      });
      return rows;
    }

    export function shortenPath(path, maxLen) {
      maxLen = maxLen || 50;
      if (!path || path.length <= maxLen) return escapeHtml(path || '');
      const parts = path.split('/');
      if (parts.length <= 3) return escapeHtml(path.slice(0, maxLen/2) + '…' + path.slice(-(maxLen/2)));
      const head = parts.slice(0, 2).join('/');
      const tail = parts.slice(-2).join('/');
      return escapeHtml(head + '/…/' + tail);
    }

    // ---------------------------------------------------------------------
    // CSV export — reusable by ANY renderTable(...) caller (Analysis, CLI,
    // Overview) via the `options.exportId` shown above, or directly via
    // registerTableExport()/renderCsvExportButton() for hand-rolled
    // <table> markup that doesn't go through renderTable(). No network
    // round-trip: the CSV text is built client-side from already-rendered
    // (i.e. currently filtered + sorted) rows and downloaded via a Blob +
    // object URL, keeping the page a single self-contained file.
    //
    // Public API for other modules:
    //   registerTableExport(exportId, columns, rows, filename?)
    //     -> stashes {columns, rows, filename} for exportId. Re-registering
    //        the same id (e.g. on every re-render) overwrites the previous
    //        entry, so the exported CSV always matches what's on screen at
    //        click time — call this with the SAME filtered/sorted `rows`
    //        array you pass to the table renderer, not the raw dataset.
    //   renderCsvExportButton(exportId, label?)
    //     -> HTML for a small "⬇ CSV" button wired to exportTableCsv(id).
    //   columns: same shape renderTable() takes, i.e. `{ title, render,
    //     numeric, csv? }`. `column.csv(row)` should return a raw
    //     string/number for the CSV cell; when omitted, the column's
    //     `render(row)` HTML output is stripped of tags/entities as a
    //     best-effort fallback (works for simple cells, but a `csv`
    //     accessor is recommended wherever `render` embeds nested markup).
    //   csvEscapeField(value) / tableRowsToCsv(columns, rows) / downloadCsv(...)
    //     -> lower-level building blocks if a caller wants to build/trigger
    //        a CSV export without the registry (e.g. a one-off button).
    //   exportTableCsv(exportId)
    //     -> looks up the registry entry and triggers the download; this is
    //        also the literal inline onclick target and is bound onto
    //        `window` at the bottom of this file.
    // ---------------------------------------------------------------------

    const TABLE_EXPORT_REGISTRY = new Map();

    export function registerTableExport(exportId, columns, rows, filename) {
      TABLE_EXPORT_REGISTRY.set(exportId, {
        columns: columns || [],
        rows: rows || [],
        filename: filename || `${exportId || 'export'}.csv`,
      });
    }

    export function renderCsvExportButton(exportId, label = '⬇ CSV') {
      return `<div class="table-export-bar" style="display:flex;justify-content:flex-end;margin-bottom:8px"><button type="button" class="copy-button" onclick="exportTableCsv('${escapeHtml(String(exportId))}')">${escapeHtml(label)}</button></div>`;
    }

    function stripHtmlToText(html) {
      return String(html === null || html === undefined ? '' : html)
        .replace(/<[^>]*>/g, '')
        .replace(/&nbsp;/gi, ' ')
        .replace(/&amp;/gi, '&')
        .replace(/&lt;/gi, '<')
        .replace(/&gt;/gi, '>')
        .replace(/&quot;/gi, '"')
        .replace(/&#39;/gi, "'")
        .replace(/\s+/g, ' ')
        .trim();
    }

    // CSV-injection safe: quotes/commas/newlines get RFC4180 quoting, and a
    // leading =, +, -, or @ (formula triggers in Excel/Sheets) is neutralized
    // with a leading apostrophe, since these files are meant to be opened
    // directly in a spreadsheet app.
    export function csvEscapeField(value) {
      let text = value === null || value === undefined ? '' : String(value);
      if (/^[=+\-@]/.test(text)) text = `'${text}`;
      if (/[",\n\r]/.test(text)) text = `"${text.replace(/"/g, '""')}"`;
      return text;
    }

    export function tableRowsToCsv(columns, rows) {
      const cols = columns || [];
      const header = cols.map((column) => csvEscapeField(column.title || '')).join(',');
      const body = (rows || []).map((row) => cols.map((column) => {
        const raw = typeof column.csv === 'function'
          ? column.csv(row)
          : stripHtmlToText(typeof column.render === 'function' ? column.render(row) : '');
        return csvEscapeField(raw);
      }).join(',')).join('\r\n');
      return body ? `${header}\r\n${body}` : header;
    }

    export function downloadCsv(filename, csvText) {
      const blob = new Blob([csvText], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename || 'export.csv';
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    export function exportTableCsv(exportId) {
      const entry = TABLE_EXPORT_REGISTRY.get(exportId);
      if (!entry) return;
      downloadCsv(entry.filename, tableRowsToCsv(entry.columns, entry.rows));
    }

    // tables.js owns this handler's window binding directly (same pattern
    // filters.js uses for window.CopilotFilters) since it's invoked via an
    // inline onclick generated right here in renderCsvExportButton(), and
    // app.js (owned by another agent) isn't editable to add it there.
    if (typeof window !== 'undefined') {
      Object.assign(window, { exportTableCsv });
    }

