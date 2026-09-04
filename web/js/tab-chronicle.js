import { escapeHtml, formatCreditUnits, formatInteger, formatPercent } from './format.js';
import { APP_DATA } from './state.js';
import { renderTable } from './tables.js';

    // The Chronicle tab answers two questions the rest of the dashboard cannot:
    //
    //   "did the export actually run, and is anything still waiting?"  —  from
    //   the per-stream watermarks in chronicle_state.json, compared against the
    //   row counts in the live session store.
    //
    //   "what was the spend spent ON?"  —  the per-token-type credit split
    //   `chronicle_export.cost_split()` derives from the rate table GitHub
    //   applied to each call, which is the only place the prompt cache's saving
    //   is visible as a number rather than as a hit rate.
    //
    // Both come from `chronicle_view.build_chronicle_payload` (app_data.chronicle)
    // and are read from the local store, so this tab is meaningful even when
    // OpenObserve is unreachable — an endpoint column that shows where rows go
    // is not a claim that they arrived.
    //
    // Every credit figure here is ALREADY in credits (GitHub prices calls in
    // nano-AIU, not dollars), hence formatCreditUnits() throughout rather than
    // the formatCost() the rest of the dashboard uses on its USD floats.

    function chronicleData() {
      return APP_DATA.chronicle || {};
    }

    // Whether the tab is worth offering at all. A store that simply isn't there
    // has nothing chronicle-specific to say — the CLI tab already reports "no
    // session store" — so the tab is hidden rather than added as a dead end. A
    // store that exists but failed to read IS worth showing, because that is a
    // problem the user can act on.
    export function hasChronicleData() {
      const data = chronicleData();
      return Boolean(data.available) || data.reason === 'query_failed';
    }

    function emptyPanel(title, note) {
      return `<div class="panel"><div class="section-title">${escapeHtml(title)}</div><div class="note is-empty">${escapeHtml(note)}</div></div>`;
    }

    // `sentAt` is an ISO-8601 string written by the exporter, not the epoch-ms
    // number formatTimestamp() takes, so it gets its own (locale) rendering.
    function formatIsoStamp(value) {
      if (!value) return 'never';
      const parsed = new Date(String(value));
      if (!Number.isFinite(parsed.getTime())) return String(value);
      return parsed.toLocaleString();
    }

    function unavailableReason(data) {
      if (data.reason === 'no_db') {
        return 'No Copilot CLI session store was found, so there is nothing for the chronicle export to ship. Point --cli-db at ~/.copilot/session-store.db if it lives somewhere else.';
      }
      if (data.reason === 'query_failed') {
        return `Reading the session store failed, so export status and the credit split are unavailable: ${data.error || 'unknown error'}`;
      }
      return 'Chronicle data is unavailable for this build.';
    }

    function renderExportStatusPanel(data) {
      const streams = Array.isArray(data.streams) ? data.streams : [];
      const totals = data.totals || {};
      const pending = Number(totals.pending || 0);
      const neverShipped = streams.filter((row) => !row.everShipped).length;
      // "Pending" is counted against each stream's watermark, not derived as
      // max(id) - last_id, so a pruned store does not read as a huge backlog.
      const statusNote = !streams.length
        ? ''
        : neverShipped === streams.length
          ? 'The export has never run — every row in the store is still waiting.'
          : pending > 0
            ? `${formatInteger(pending)} row(s) recorded since the last export. Re-run with --chronicle to ship them.`
            : 'Every stream is caught up with the local store.';
      const statusClass = !streams.length ? '' : neverShipped === streams.length ? 'is-critical' : pending > 0 ? 'is-warn' : 'is-ok';

      const columns = [
        { title: 'Stream', render: (row) => `<code>${escapeHtml(row.stream)}</code>`, csv: (row) => row.stream },
        { title: 'Source table', render: (row) => `<code>${escapeHtml(row.table)}</code>`, csv: (row) => row.table },
        { title: 'Watermark', render: (row) => `<code>${escapeHtml(row.watermarkColumn)}</code> = ${row.lastId === null || row.lastId === undefined ? '—' : escapeHtml(String(row.lastId))}`, csv: (row) => `${row.watermarkColumn}=${row.lastId ?? ''}` },
        { title: 'Rows in store', numeric: true, render: (row) => formatInteger(row.rowsInDb), csv: (row) => row.rowsInDb },
        { title: 'Shipped', numeric: true, render: (row) => formatInteger(row.shipped), csv: (row) => row.shipped },
        {
          title: 'Pending',
          numeric: true,
          render: (row) => (Number(row.pending || 0) > 0
            ? `<span class="badge confidence-medium">${formatInteger(row.pending)}</span>`
            : formatInteger(row.pending)),
          csv: (row) => row.pending,
        },
        { title: 'Last shipped at', render: (row) => escapeHtml(formatIsoStamp(row.sentAt)), csv: (row) => row.sentAt || '' },
        { title: 'Endpoint', render: (row) => (row.endpoint ? `<span class="note small">${escapeHtml(row.endpoint)}</span>` : '—'), csv: (row) => row.endpoint || '' },
      ];

      return `
        <div class="panel">
          <div class="section-title">Chronicle export status</div>
          <div class="section-subtitle small">Per-stream watermarks from <code>${escapeHtml(data.statePath || 'chronicle_state.json')}</code>, compared against the live store at <code>${escapeHtml(data.dbPath || '—')}</code>. Counted locally: the endpoint column says where rows are sent, not that OpenObserve accepted them.</div>
          <div class="summary-grid" style="margin:10px 0">
            <div class="summary-card"><div class="label">Rows shipped</div><div class="value">${formatInteger(totals.shipped)}</div><div class="note small">of ${formatInteger(totals.rowsInDb)} in the store</div></div>
            <div class="summary-card"><div class="label">Rows pending</div><div class="value ${statusClass}">${formatInteger(pending)}</div><div class="note small">${escapeHtml(neverShipped ? `${formatInteger(neverShipped)} stream(s) never shipped` : 'all streams shipped at least once')}</div></div>
            <div class="summary-card"><div class="label">Last export run</div><div class="value">${escapeHtml(formatIsoStamp(totals.lastRunAt))}</div><div class="note small">most recent stream watermark</div></div>
            <div class="summary-card"><div class="label">Streams</div><div class="value">${formatInteger(streams.length)}</div><div class="note small">plus <code>${escapeHtml(data.advice?.stream || '')}</code> for advice</div></div>
          </div>
          ${statusNote ? `<div class="note small">${escapeHtml(statusNote)}</div>` : ''}
          ${streams.length
            ? renderTable(columns, streams, { exportId: 'chronicleStreams', exportFilename: 'chronicle-streams.csv' })
            : '<div class="note is-empty">No chronicle streams are configured.</div>'}
        </div>`;
    }

    // The cross-foot, shown whether or not it passes. `copilot_chronicle_costs`
    // re-prices every call from its own rate table and `copilot_chronicle_usage`
    // reports the charge GitHub recorded, so the two sums must agree; a gap
    // means the rate table grew a token type the split is dropping, which would
    // understate spend everywhere it appears. Saying so is the point — a silent
    // total that is missing a column is the failure mode worth avoiding.
    function renderDriftPanel(drift) {
      const ok = drift.withinTolerance !== false;
      const difference = Number(drift.difference || 0);
      const unpricedCalls = Number(drift.callsUnpriced || 0);
      const headline = ok
        ? '✅ Re-priced credits match GitHub’s billed credits exactly'
        : '⚠️ Re-priced credits disagree with GitHub’s billed credits';
      const detail = ok
        ? `Both sides sum to ${formatCreditUnits(drift.creditsTotal)} across ${formatInteger(drift.callsPriced)} priced call(s), so the per-token-type split below accounts for every credit charged on those calls.`
        : `The split adds up to ${formatCreditUnits(drift.creditsTotal)} but GitHub billed ${formatCreditUnits(drift.aiCredits)} for the same calls — a gap of ${formatCreditUnits(difference)}, against a tolerance of ${formatCreditUnits(drift.tolerance)}. The usual cause is a new token type in the rate table that cost_split() is not summing, which makes every credit figure derived from the split an understatement. Treat the billed figure as authoritative until the split is fixed.`;
      // Calls with no rate table are excluded from BOTH sides above rather than
      // counted as billed-but-unsplit, so missing coverage can never masquerade
      // as arithmetic drift. It still has to be said out loud, since those
      // credits were charged and do not appear in the breakdown below.
      const coverageNote = unpricedCalls
        ? `${formatInteger(unpricedCalls)} further call(s) recorded no per-token rate table, so their ${formatCreditUnits(drift.creditsUnpriced)} is billed but cannot be split. They are excluded from both figures above and from the breakdown below; ${formatCreditUnits(drift.billedTotal)} was billed in total.`
        : '';
      return `
        <div class="panel">
          <div class="section-title">Cross-foot: split vs billed</div>
          <div class="section-subtitle small">Two independent derivations of the same spend: <code>copilot_chronicle_costs</code> re-prices each call from its own rate table, <code>copilot_chronicle_usage</code> reports the charge GitHub recorded. They must agree.</div>
          <div class="insight-card ${ok ? '' : 'state-critical'}" style="margin-top:10px">
            <div style="font-weight:700">${headline}</div>
            <div class="note small" style="margin-top:6px">${escapeHtml(detail)}</div>
          </div>
          <div class="summary-grid" style="margin-top:12px">
            <div class="summary-card" title="Sum of credits_total across copilot_chronicle_costs — each call re-priced from the rates GitHub applied to it."><div class="label">Re-priced (costs stream)</div><div class="value cost">${formatCreditUnits(drift.creditsTotal)}</div><div class="note small">${formatInteger(drift.callsPriced)} call(s) priced</div></div>
            <div class="summary-card" title="Sum of ai_credits across copilot_chronicle_usage — the charge GitHub recorded, from total_nano_aiu — for those same calls."><div class="label">Billed (usage stream)</div><div class="value cost">${formatCreditUnits(drift.aiCredits)}</div><div class="note small">${formatInteger(drift.callsBilled)} call(s) billed</div></div>
            <div class="summary-card"><div class="label">Difference</div><div class="value ${ok ? 'is-ok' : 'is-critical'}">${formatCreditUnits(difference)}</div><div class="note small">tolerance ${formatCreditUnits(drift.tolerance)}</div></div>
          </div>
          ${coverageNote ? `<div class="note small" style="margin-top:10px">${escapeHtml(coverageNote)}</div>` : ''}
        </div>`;
    }

    function renderSplitTotalsPanel(totals) {
      const ifNoCache = Number(totals.creditsIfNoCache || 0);
      const saved = Number(totals.creditsCacheSaved || 0);
      const savedPct = Number(totals.cacheSavedPercent || 0);
      const bar = (label, value, color) => {
        const total = Number(totals.creditsTotal || 0);
        const pct = total ? (Number(value || 0) / total) * 100 : 0;
        return `
          <div style="margin-bottom:8px">
            <div class="note small" style="display:flex;justify-content:space-between">
              <span>${escapeHtml(label)}</span>
              <span><strong>${formatCreditUnits(value)}</strong> · ${formatPercent(pct)}</span>
            </div>
            <div class="gauge"><div class="gauge-fill" style="width:${Math.max(0, Math.min(100, pct)).toFixed(1)}%;background:${color}"></div></div>
          </div>`;
      };
      return `
        <div class="panel">
          <div class="section-title">Where the credits went</div>
          <div class="section-subtitle small">Each call split across the four token types using the per-token rates GitHub applied to it (<code>token_details_json</code>), so promotions, the auto-model-selection discount and long-context tiers are already reflected. Exact, not estimated.</div>
          <div class="summary-grid" style="margin:10px 0">
            <div class="summary-card"><div class="label">Total charged</div><div class="value cost">${formatCreditUnits(totals.creditsTotal)}</div><div class="note small">${formatInteger(totals.callsPriced)} of ${formatInteger(totals.calls)} call(s) priced</div></div>
            <div class="summary-card" title="What the same tokens would have cost with every cached read billed at the full uncached input rate and no cache writes."><div class="label">Without the prompt cache</div><div class="value">${formatCreditUnits(ifNoCache)}</div><div class="note small">hypothetical</div></div>
            <div class="summary-card"><div class="label">Saved by the cache</div><div class="value is-ok">${formatCreditUnits(saved)}</div><div class="note small">${formatPercent(savedPct)} of the uncached price</div></div>
          </div>
          <!-- Same colour per token type as the rest of the dashboard uses for
               .value.uncached / .cached / .output, so the bars read as the
               token types the summary cards already name. -->
          ${bar('Uncached input', totals.creditsInput, 'var(--yellow)')}
          ${bar('Cached reads', totals.creditsCacheRead, 'var(--green)')}
          ${bar('Cache writes', totals.creditsCacheWrite, 'var(--purple)')}
          ${bar('Output', totals.creditsOutput, 'var(--orange)')}
          <div class="note small" style="margin-top:10px">Cache writes are charged at their own (higher) rate and are the price of the saving above — a cache that is written but never read costs more than no cache at all.</div>
        </div>`;
    }

    function splitColumns(keyTitle, keyRender, keyCsv) {
      return [
        { title: keyTitle, render: keyRender, csv: keyCsv },
        {
          // Priced calls, with the unpriced remainder named rather than dropped:
          // a bucket reading "0 credits" needs to say it was never priced, or it
          // looks like a model that ran for free.
          title: 'Calls priced',
          numeric: true,
          render: (row) => (Number(row.calls || 0) === Number(row.callsPriced || 0)
            ? formatInteger(row.callsPriced)
            : `${formatInteger(row.callsPriced)} <span class="note small">of ${formatInteger(row.calls)}</span>`),
          csv: (row) => row.callsPriced,
        },
        { title: 'Uncached input', numeric: true, render: (row) => formatCreditUnits(row.creditsInput), csv: (row) => row.creditsInput },
        { title: 'Cached reads', numeric: true, render: (row) => formatCreditUnits(row.creditsCacheRead), csv: (row) => row.creditsCacheRead },
        { title: 'Cache writes', numeric: true, render: (row) => formatCreditUnits(row.creditsCacheWrite), csv: (row) => row.creditsCacheWrite },
        { title: 'Output', numeric: true, render: (row) => formatCreditUnits(row.creditsOutput), csv: (row) => row.creditsOutput },
        { title: 'Total', numeric: true, render: (row) => `<strong>${formatCreditUnits(row.creditsTotal)}</strong>`, csv: (row) => row.creditsTotal },
        { title: 'Cache saved', numeric: true, render: (row) => `${formatCreditUnits(row.creditsCacheSaved)} <span class="note small">(${formatPercent(row.cacheSavedPercent)})</span>`, csv: (row) => row.creditsCacheSaved },
      ];
    }

    function renderByModelPanel(rows) {
      if (!rows.length) return '';
      return `
        <div class="panel">
          <div class="section-title">Credit split by model</div>
          <div class="section-subtitle small">Sorted by total credits charged. A model with a low cache-saved percentage is one whose context is being rebuilt rather than reused.</div>
          <div class="table-scroll">
            ${renderTable(splitColumns('Model', (row) => escapeHtml(String(row.model || 'unknown')), (row) => row.model), rows, { exportId: 'chronicleByModel', exportFilename: 'chronicle-credits-by-model.csv' })}
          </div>
        </div>`;
    }

    function renderByDayPanel(rows) {
      if (!rows.length) return '';
      // Newest first: the question this table gets asked is "what did today
      // cost", and that answer should not be at the bottom of 30+ rows.
      const ordered = [...rows].reverse();
      return `
        <div class="panel">
          <div class="section-title">Credit split by day</div>
          <div class="section-subtitle small">Local calendar days, newest first — grouped the way every other per-day figure on this dashboard is, so the two can be compared.</div>
          <div class="table-scroll" style="max-height:520px;overflow:auto">
            ${renderTable(splitColumns('Day', (row) => escapeHtml(String(row.day || '')), (row) => row.day), ordered, { exportId: 'chronicleByDay', exportFilename: 'chronicle-credits-by-day.csv' })}
          </div>
        </div>`;
    }

    export function renderChronicleTab() {
      const data = chronicleData();
      if (!data.available) {
        return emptyPanel('Chronicle', unavailableReason(data));
      }
      const costs = data.costs || {};
      const totals = costs.totals || {};
      const drift = data.drift || {};
      const byModel = Array.isArray(costs.byModel) ? costs.byModel : [];
      const byDay = Array.isArray(costs.byDay) ? costs.byDay : [];
      const hasSplit = Number(totals.callsPriced || 0) > 0;
      return `
        ${renderExportStatusPanel(data)}
        ${hasSplit ? renderDriftPanel(drift) : ''}
        ${hasSplit
          ? `${renderSplitTotalsPanel(totals)}${renderByModelPanel(byModel)}${renderByDayPanel(byDay)}`
          : emptyPanel('Where the credits went', 'No call in the store carries a per-token rate table (token_details_json), which older Copilot CLI builds did not record. The credit split needs those rates; the CLI tab still shows billed totals.')}`;
    }
