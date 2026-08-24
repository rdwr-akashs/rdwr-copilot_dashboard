import { renderApp } from './app.js';
import { escapeHtml, formatInteger } from './format.js';
import { APP_DATA } from './state.js';

    // Surfacing build-time parse/cache failures (see diagnostics.py).
    //
    // The point of this file is one specific failure mode: when a cache entry
    // will not decompress or a session will not parse, the backend historically
    // dropped it and every total came out lower than the truth, rendered with
    // exactly the same authority as a correct figure. Nothing here changes a
    // number - it says out loud when a number is known to be incomplete.

    const DISMISS_KEY = 'copilot-dashboard-dismissed-diagnostics-v1';

    const EMPTY_SUMMARY = { total: 0, errors: 0, warnings: 0, costImpacting: 0 };

    export function diagnosticsPayload() {
      const payload = APP_DATA.diagnostics;
      if (!payload || typeof payload !== 'object') return { entries: [], summary: EMPTY_SUMMARY };
      return {
        entries: Array.isArray(payload.entries) ? payload.entries : [],
        summary: payload.summary && typeof payload.summary === 'object' ? payload.summary : EMPTY_SUMMARY,
      };
    }

    export function costImpactingDiagnostics() {
      return diagnosticsPayload().entries.filter((entry) => entry && entry.impact === 'cost');
    }

    // Dismissal is keyed on WHAT was wrong, not on "the user clicked x".
    //
    // A plain dismissed-forever flag would recreate the very bug this feature
    // exists to fix: dismiss once, and the next run's brand-new corruption
    // stays hidden behind an understated total. Keying on (code, source, count)
    // means dismissing "these known problems" and nothing else - a new failure,
    // or more occurrences of the same one, changes the signature and the banner
    // returns. Rebuilds that reproduce the identical set stay quiet.
    function diagnosticsSignature(entries) {
      return entries
        .map((entry) => `${entry.code}@${entry.source || ''}#${entry.count || 1}`)
        .sort()
        .join('|');
    }

    function readDismissedSignature() {
      try {
        return localStorage.getItem(DISMISS_KEY) || '';
      } catch (_err) {
        // Private mode / storage disabled: fall through to showing the banner.
        // Erring toward visible is deliberate for a correctness warning.
        return '';
      }
    }

    export function dismissDiagnosticsBanner() {
      const entries = costImpactingDiagnostics();
      try {
        localStorage.setItem(DISMISS_KEY, diagnosticsSignature(entries));
      } catch (_err) {
        // Ignore storage failures (private mode / disabled storage); the banner
        // simply returns on the next render.
      }
      renderApp();
    }

    function severityColor(severity) {
      if (severity === 'error') return 'var(--red)';
      if (severity === 'warning') return 'var(--yellow)';
      return 'var(--muted)';
    }

    function occurrenceSuffix(count) {
      const total = Number(count || 1);
      return total > 1 ? ` <span class="note small">(${formatInteger(total)}x)</span>` : '';
    }

    /**
     * The header banner. Rendered ONLY when something cost-bearing failed.
     *
     * Deliberately not driven by severity: a malformed OpenTelemetry line is an
     * honest failure but can never move a cost figure, and a banner that fires
     * on those gets trained away as noise - at which point it no longer works
     * for the case that matters. `impact: 'cost'` is the trigger.
     */
    export function renderDiagnosticsBanner() {
      const entries = costImpactingDiagnostics();
      if (!entries.length) return '';
      if (readDismissedSignature() === diagnosticsSignature(entries)) return '';

      const affected = entries.reduce((total, entry) => total + Number(entry.count || 1), 0);
      const headline = entries.length === 1
        ? '1 data source failed to load'
        : `${formatInteger(entries.length)} data sources failed to load`;

      return `
        <div class="diagnostics-banner" role="alert">
          <span class="diagnostics-banner__icon" aria-hidden="true">⚠️</span>
          <div class="diagnostics-banner__body">
            <strong>Totals on this page may be understated.</strong>
            ${escapeHtml(headline)} while building this dashboard${affected > entries.length ? ` (${formatInteger(affected)} occurrences)` : ''}, so
            whatever they contained is missing from every figure shown.
            <div class="note small" style="margin-top:4px">
              Full details in <strong>Info → Telemetry</strong>. Re-running with
              <code>--force-recalculate</code> rebuilds the cache from the raw logs.
            </div>
          </div>
          <button type="button" class="action-chip" onclick="dismissDiagnosticsBanner()" title="Hide until something different fails">Dismiss</button>
        </div>`;
    }

    /**
     * The full list, for the Info -> Telemetry subtab - which is already the
     * "what this data does and does not contain" surface.
     */
    export function renderDiagnosticsPanel() {
      const { entries, summary } = diagnosticsPayload();
      if (!entries.length) {
        return `
          <section class="panel">
            <h2 class="section-title">Data collection problems</h2>
            <div class="section-subtitle">None. Every cache entry and log file read cleanly for this build, so no session is missing from the totals below.</div>
          </section>`;
      }

      const costCount = Number(summary.costImpacting || 0);
      const lead = costCount
        ? `<strong style="color:var(--red)">${formatInteger(costCount)} of these affect cost figures</strong> - the sessions behind them are missing from every total on this dashboard.`
        : 'None of these affect cost figures; the totals on this dashboard are complete.';

      return `
        <section class="panel">
          <h2 class="section-title">Data collection problems</h2>
          <div class="section-subtitle">Failures recorded while building this dashboard. ${lead}</div>
          <table class="compact-prices-table">
            <thead>
              <tr>
                <th>Impact</th>
                <th>Code</th>
                <th>What happened</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              ${entries.map((entry) => `
                <tr>
                  <td><span class="badge ${entry.impact === 'cost' ? 'boundary' : 'source'}">${escapeHtml(entry.impact === 'cost' ? 'cost' : entry.impact || 'none')}</span></td>
                  <td><code style="color:${severityColor(entry.severity)}">${escapeHtml(entry.code || '')}</code>${occurrenceSuffix(entry.count)}</td>
                  <td>${escapeHtml(entry.message || '')}</td>
                  <td class="note small" style="word-break:break-all">${escapeHtml(entry.source || '-')}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </section>`;
    }
